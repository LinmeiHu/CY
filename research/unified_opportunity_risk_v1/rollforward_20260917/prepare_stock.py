"""Extend the frozen stock input using the same PIT-B guards and QD010 chain."""
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path
import duckdb
from research.portfolio_closure_v1 import repair
from research.scaling_regime_v1 import snapshot
from research.shared_capital_v1.causal_adapters import corrected_function

HERE=Path(__file__).resolve().parent
CACHE=HERE/'cache'
END='2026-09-16'
SOURCE=Path('/Users/linmei/Documents/CY-supermind-v6-autonomous-20260830')
OLD=repair.CACHE/'daily_with_snapshot.parquet'


def main():
    market=CACHE/'qmt_market'
    manifest=json.loads((market/'manifest.json').read_text())
    # An unfinished collector must never become a replay input.
    assert (market/'raw_daily.parquet').exists()
    spec=importlib.util.spec_from_file_location('bound_current_daily_builder',SOURCE/'scripts/build_current_daily_pit_b.py')
    builder=importlib.util.module_from_spec(spec);sys.modules[spec.name]=builder;spec.loader.exec_module(builder)
    builder.START=date(2026,9,7);builder.END=date(2026,9,16)
    builder._create_delta_sources=corrected_function(builder._create_delta_sources,[("ELSE 'baostock_none_daily' END","ELSE 'qmt_none_daily+captured_baostock_universe' END")])
    registry=json.loads((SOURCE/'configs/data_asset_registry.json').read_text())
    ids=['CY-033','CY-023','QD-008-BS-MERGED-20260821','QD-009','QD-010']
    assets={i:builder._asset(registry,i) for i in ids}
    for i in ['CY-033','QD-008-BS-MERGED-20260821','QD-009','QD-010']:builder._verify_inventory(assets[i])
    builder._verify_asset_file_hashes(assets['CY-023'])
    binding=snapshot.binding()
    metadata=builder._SnapshotManifest({
        role:(asset,assets[asset]['lineage'].get('snapshot_id',asset))
        for role,asset in [('industry_membership','CY-023'),('circulating_shares','QD-009'),('corporate_actions','QD-010')]})
    for role in ['daily_bars','trading_state','index_daily']:
        metadata.snapshots[role]=('CANDIDATE_B_20260916_MARKET',repair.digest(market/'manifest.json'))
    with duckdb.connect() as c:
        c.execute('SET threads=4')
        builder._create_delta_sources(c,market_root=market,industry_root=Path(assets['CY-023']['location']),
            base_industry_root=Path(assets['QD-008-BS-MERGED-20260821']['location']),
            base_daily_root=builder._daily_partition_root(assets['CY-033']),
            float_root=Path(assets['QD-009']['location']),action_root=Path(assets['QD-010']['location']))
        c.execute('CREATE TEMP TABLE registered_distributions AS SELECT * FROM distributions_raw')
        c.execute(f"CREATE OR REPLACE TEMP VIEW distributions_raw AS SELECT * FROM registered_distributions UNION ALL SELECT symbol||CASE WHEN symbol LIKE '6%' THEN '.SH' ELSE '.SZ' END,event_id,announcement_date::DATE,known_at::DATE,effective_date::DATE,share_multiplier,cash_per_share_gross,source_terms_complete,execution_timing_resolved,source FROM read_parquet('{HERE}/official_facts/stock_action_combined_delta.parquet')")
        builder._create_float_timeline(c,builder.END);builder._create_action_events(c,builder.START,builder.END)
        builder._create_enriched(c,metadata,'CANDIDATE_B_ROLLFORWARD_20260916');builder._strengthen_delta(c)
        c.execute(f"COPY delta_enriched TO '{CACHE}/pit_delta.parquet' (FORMAT PARQUET)")
        full=CACHE/'pit_full/daily';full.mkdir(parents=True,exist_ok=True)
        base_root=builder._daily_partition_root(assets['CY-033'])
        for year in range(2018,2026):
            link=full/f'partition_year={year}';link.symlink_to(base_root/f'partition_year={year}',target_is_directory=True) if not link.exists() else None
        target=full/'partition_year=2026';target.mkdir(exist_ok=True)
        c.execute(f"COPY (SELECT * FROM read_parquet('{base_root}/partition_year=2026/data_0.parquet') UNION ALL BY NAME SELECT * FROM delta_enriched) TO '{target}/data_0.parquet' (FORMAT PARQUET)")
        quality=c.execute('SELECT count(*) n,sum(hard_valid::INT) valid_count,count(DISTINCT trade_date) day_count,max(trade_date) last_date FROM delta_enriched').fetchdf().iloc[0]
        reasons=c.execute('SELECT invalid_reasons,count(*) n FROM delta_enriched WHERE NOT hard_valid GROUP BY 1 ORDER BY 2 DESC').fetchdf()
        reasons.to_csv(HERE/'stock_invalid_reasons.csv',index=False)
        assert str(quality['last_date'])[:10]==END and quality['day_count']==8
        assert quality['valid_count']/quality['n']>=.95,quality.to_dict()
        c.execute(f"CREATE VIEW old AS SELECT * FROM read_parquet('{OLD}')")
        c.execute('CREATE TEMP TABLE seed AS SELECT * FROM old QUALIFY row_number() OVER(PARTITION BY symbol ORDER BY trade_date DESC)=1')
        c.execute('CREATE TEMP TABLE calendar AS SELECT trade_date,(SELECT max(cal_idx) FROM old)+row_number() OVER(ORDER BY trade_date) cal_idx FROM (SELECT DISTINCT trade_date FROM delta_enriched)')
        # Exact original validity predicates, followed by the same frozen industry ASOF binding.
        c.execute('''CREATE TEMP TABLE base AS SELECT d.*,s.sleeve,c.cal_idx,
          (d.hard_valid IS TRUE AND d.bar_valid IS TRUE AND d.trading_state_valid IS TRUE
           AND d.corporate_action_valid IS TRUE AND d.market_rule_valid IS TRUE
           AND d.historical_identity_valid IS TRUE AND d.corporate_action_blocking IS FALSE
           AND d.available_at IS NOT NULL AND d.available_at<=d.decision_at
           AND d.close IS NOT NULL AND isfinite(d.close) AND d.close>0
           AND d.open IS NOT NULL AND isfinite(d.open) AND d.open>0
           AND d.high IS NOT NULL AND isfinite(d.high) AND d.high>=greatest(d.open,d.close,d.low)
           AND d.low IS NOT NULL AND isfinite(d.low) AND d.low<=least(d.open,d.close,d.high)) history_valid,
          (d.hard_valid IS TRUE AND d.trade_status=1 AND d.current_day_data_tradable IS TRUE
           AND d.volume IS NOT NULL AND isfinite(d.volume) AND d.volume>0) current_valid
          FROM delta_enriched d JOIN seed s USING(symbol) JOIN calendar c ON d.trade_date=c.trade_date''')
        c.execute('''CREATE TEMP TABLE steps AS SELECT b.*,
          coalesce(lag(b.close) OVER w,s.close) previous_close,
          coalesce(lag(b.history_valid) OVER w,s.history_valid) previous_history_valid,
          coalesce(lag(b.cal_idx) OVER w,s.cal_idx) previous_cal_idx,
          s.adjusted_close seed_adjusted_close,s.invalid_step_cum seed_invalid_step_cum
          FROM base b JOIN seed s USING(symbol) WINDOW w AS(PARTITION BY b.symbol ORDER BY b.trade_date)''')
        c.execute('''CREATE TEMP TABLE chain AS SELECT *,
          history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1 AND
          (coalesce(corporate_action_count,0)=0 OR (corporate_action_count>0
           AND corporate_action_available_date IS NOT NULL AND corporate_action_available_date<=trade_date
           AND coalesce(rights_ratio,0)=0 AND coalesce(share_multiplier,1)>0
           AND (previous_close-coalesce(cash_per_share,0))/coalesce(share_multiplier,1)>0)) coordinate_step_valid,
          CASE WHEN corporate_action_count>0 THEN
            (previous_close-coalesce(cash_per_share,0))/coalesce(share_multiplier,1)
            ELSE previous_close END reference
          FROM steps''')
        c.execute('''CREATE TEMP TABLE adjusted AS SELECT *,
          seed_adjusted_close*exp(sum(CASE WHEN coordinate_step_valid THEN ln(close/reference) ELSE 0. END) OVER w) adjusted_close,
          seed_invalid_step_cum+sum(CASE WHEN coordinate_step_valid THEN 0 ELSE 1 END) OVER w invalid_step_cum
          FROM chain WINDOW w AS(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)''')
        c.execute('''CREATE TEMP TABLE industry_source AS SELECT trade_date,
          CASE WHEN symbol LIKE '6%' THEN symbol||'.SH' ELSE symbol||'.SZ' END symbol,
          industry,source_notice_date,source_report_date FROM read_parquet(?)
          WHERE coalesce(industry,'') NOT IN ('','UNKNOWN') AND source_notice_date<trade_date
          QUALIFY row_number() OVER(PARTITION BY trade_date,symbol ORDER BY source_notice_date DESC,source_report_date DESC NULLS LAST)=1''',[str(snapshot.INDUSTRY)])
        c.execute('''CREATE TEMP TABLE joined AS SELECT d.*,i.industry source_industry
          FROM adjusted d ASOF LEFT JOIN industry_source i ON d.symbol=i.symbol AND d.trade_date>=i.trade_date''')
        assert c.execute('SELECT count(*) FROM joined WHERE industry_valid AND source_industry IS NULL').fetchone()[0]==0
        cols=[r[0] for r in c.execute('DESCRIBE old').fetchall()]
        expressions={k:k for k in cols}
        expressions.update(coordinate_factor='adjusted_close/close',coord_close='adjusted_close',
            coord_open='open*adjusted_close/close',coord_high='high*adjusted_close/close',coord_low='low*adjusted_close/close',
            prior_coord_close='coalesce(lag(adjusted_close) OVER(PARTITION BY symbol ORDER BY trade_date),seed_adjusted_close)',
            industry='CASE WHEN industry_valid THEN source_industry ELSE industry END',
            causal_industry='CASE WHEN industry_valid THEN source_industry ELSE NULL END',
            industry_snapshot_id="'"+binding['snapshot_id']+"'")
        select=','.join(expressions[k]+' AS '+k for k in cols)
        c.execute(f"COPY (SELECT {select} FROM joined) TO '{CACHE}/compact_delta.parquet' (FORMAT PARQUET)")
        c.execute(f"COPY (SELECT * FROM old UNION ALL SELECT * FROM read_parquet('{CACHE}/compact_delta.parquet')) TO '{CACHE}/daily_with_snapshot.parquet' (FORMAT PARQUET)")
        assert c.execute(f"SELECT count(*) FROM (SELECT * FROM old EXCEPT ALL SELECT * FROM read_parquet('{CACHE}/daily_with_snapshot.parquet') WHERE trade_date<='2026-09-04')").fetchone()[0]==0
        repair.write_json(HERE/'stock_data_audit.json',dict(status='PASS',quality=quality.to_dict(),old_prefix='EXACT',
            inputs={str(OLD):repair.digest(OLD),str(market/'manifest.json'):repair.digest(market/'manifest.json')},
            builder_sha256=repair.digest(SOURCE/'scripts/build_current_daily_pit_b.py'),industry_snapshot=binding))
    print('STOCK INPUT EXTENDED',quality.to_dict(),flush=True)


if __name__=='__main__':main()
