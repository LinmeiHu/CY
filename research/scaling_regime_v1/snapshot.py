"""Restore the frozen manifest-bound MCB industry identity, without a fallback."""
import json
from pathlib import Path

import duckdb
import pandas as pd

from five_strategy_bundle.strategies import mcb
from research.shared_capital_v1.causal_adapters import corrected_function
from .audit import HERE, ROOT, ROLL, sha256, write_json

CACHE = HERE / 'cache'
MANIFEST = Path('/Users/linmei/Documents/CY/data/input_snapshots/CYQ-PREP-2018-2026-20260820.json')
INVENTORY = Path('/Users/linmei/Documents/CY/data/input_inventories/QD-008-eastmoney-pit-20260820.json')
INDUSTRY = Path('/Users/linmei/Downloads/workspace/quant/data/lake/meta/industry_daily.parquet')
HIST = Path('/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/pit_daily_compact_2013_2023.parquet')


def binding():
    data = json.loads(MANIFEST.read_text())
    source = next(r for r in data['bindings'] if r['role'] == 'industry_membership')
    if sha256(INVENTORY) != source['inventory_sha256']:
        raise ValueError('DATA_INPUT_MISSING: industry inventory identity drift')
    files = json.loads(INVENTORY.read_text())['files']
    for row in files:
        if sha256(Path(source['path']) / row['path']) != row['sha256']:
            raise ValueError('DATA_INPUT_MISSING: original industry snapshot file drift')
    if not source['snapshot_id']:
        raise ValueError('DATA_INPUT_MISSING: industry snapshot identity absent')
    return source


def producer(end):
    # Only the temporal extent changes. The original snapshot predicate remains.
    return corrected_function(mcb.build_v53, [
        ("trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'", f"trade_date BETWEEN DATE '2013-01-01' AND DATE '{end}'"),
        ("d.trade_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31'", f"d.trade_date BETWEEN DATE '2014-01-01' AND DATE '{end}'")])


def prepare():
    CACHE.mkdir(exist_ok=True)
    source = binding()
    with duckdb.connect() as c:
        c.execute('SET threads=4')
        # Exact full_market.py normalization and backward ASOF join. Snapshot ID
        # is a dataset binding, while industry_valid is the distinct row gate.
        c.execute("""CREATE TEMP TABLE industry AS SELECT trade_date,
          CASE WHEN symbol LIKE '6%' THEN symbol||'.SH' ELSE symbol||'.SZ' END symbol,
          industry,source_notice_date,source_report_date,source
          FROM read_parquet(?) WHERE coalesce(industry,'') NOT IN ('','UNKNOWN')
          AND source_notice_date<trade_date
          QUALIFY row_number() OVER(PARTITION BY trade_date,symbol
          ORDER BY source_notice_date DESC,source_report_date DESC NULLS LAST)=1""", [str(INDUSTRY)])
        c.execute("""CREATE TEMP TABLE checked AS SELECT d.trade_date,d.symbol,d.causal_industry,
          d.industry_valid,d.available_at,d.decision_at,i.industry source_industry,
          i.source_notice_date,i.source_report_date,i.source,i.trade_date source_effective_date
          FROM read_parquet(?) d ASOF LEFT JOIN industry i
          ON d.symbol=i.symbol AND d.trade_date>=i.trade_date""", [str(ROLL / 'daily.parquet')])
        coverage = c.execute("""SELECT year(trade_date) AS calendar_year,count(*) AS row_count,
          count(*) FILTER(WHERE industry_valid AND (source_industry IS NULL OR source_industry<>causal_industry)) AS mismatch,
          count(*) FILTER(WHERE source_notice_date>=trade_date) AS late,
          max(source_effective_date) AS last_source_effective_date
          FROM checked GROUP BY 1 ORDER BY 1""").fetchdf()
        coverage.to_csv(HERE / 'output/industry_snapshot_coverage.csv', index=False)
        c.execute(f"COPY (SELECT * FROM checked WHERE industry_valid AND (source_industry IS NULL OR source_industry<>causal_industry)) TO '{CACHE}/industry_mismatch.parquet' (FORMAT PARQUET)")
        missing=c.execute('SELECT count(*) FROM checked WHERE industry_valid AND source_industry IS NULL').fetchone()[0]
        if missing or coverage.late.sum():
            raise ValueError('DATA_INPUT_MISSING: original industry history unavailable or noncausal')
        c.execute(f"COPY checked TO '{CACHE}/industry_join.parquet' (FORMAT PARQUET)")
        ids = c.execute('SELECT DISTINCT industry_snapshot_id FROM read_parquet(?)', [str(HIST)]).fetchall()
        if ids != [(source['snapshot_id'],)]:
            raise ValueError('parent snapshot binding differs')
        # The legacy intersection dropped the constant identity column. Restore
        # it only after its original files, binding and row provenance pass.
        c.execute(f"""COPY (SELECT d.* EXCLUDE(industry,causal_industry),
          CASE WHEN d.industry_valid THEN j.source_industry ELSE d.industry END industry,
          CASE WHEN d.industry_valid THEN j.source_industry ELSE d.causal_industry END causal_industry,
          ?::VARCHAR industry_snapshot_id FROM read_parquet(?) d JOIN checked j USING(symbol,trade_date))
          TO '{CACHE}/daily_with_snapshot.parquet' (FORMAT PARQUET)""",
                  [source['snapshot_id'], str(ROLL / 'daily.parquet')])
        c.execute(f'''COPY (WITH w AS (SELECT *,
          lag(cal_idx) OVER w AS prev_idx,
          lag(coord_close,20) OVER w AS lag20_close,lag(cal_idx,20) OVER w AS lag20_idx,
          lag(coord_close,60) OVER w AS lag60_close,lag(cal_idx,60) OVER w AS lag60_idx,
          arg_max(CASE WHEN history_valid THEN trade_date END,CASE WHEN history_valid THEN coord_high END) OVER p AS prior250_peak_date,
          arg_max(CASE WHEN history_valid THEN invalid_step_cum END,CASE WHEN history_valid THEN coord_high END) OVER p AS prior250_peak_invalid_cum
          FROM read_parquet('{CACHE}/daily_with_snapshot.parquet') WINDOW w AS(PARTITION BY symbol ORDER BY trade_date),
          p AS(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 250 PRECEDING AND 1 PRECEDING))
          SELECT *,CASE WHEN prev_idx=cal_idx-1 THEN coord_close/prior_coord_close-1 END AS step_return,
          CASE WHEN lag20_idx=cal_idx-20 THEN coord_close/lag20_close-1 END AS ret20,
          CASE WHEN lag60_idx=cal_idx-60 THEN coord_close/lag60_close-1 END AS ret60
          FROM w) TO '{CACHE}/mcb_features.parquet' (FORMAT PARQUET)''')
        c.execute(f'''COPY (WITH b AS(SELECT * FROM read_parquet('{CACHE}/mcb_features.parquet')
          WHERE current_valid AND hard_valid AND NOT is_st),
          m AS(SELECT trade_date,count(*) market_n,median(ret20) market20,median(ret60) market60,
            avg((ret20>0)::INT) market_breadth20,avg((ret60>0)::INT) market_breadth60 FROM b GROUP BY 1),
          i AS(SELECT trade_date,causal_industry,count(*) industry_n,median(ret20) industry20,
            median(ret60) industry60,avg((ret20>0)::INT) industry_breadth20,
            avg((ret60>0)::INT) industry_breadth60 FROM b GROUP BY 1,2)
          SELECT * FROM i JOIN m USING(trade_date)) TO '{CACHE}/mcb_market_industry_state.parquet' (FORMAT PARQUET)''')
    proof = dict(snapshot_id=source['snapshot_id'], manifest=str(MANIFEST), inventory=str(INVENTORY),
                 industry_daily_sha256=sha256(INDUSTRY), original_predicate='industry_snapshot_id IS NOT NULL',
                 source_end='2026-08-13', extension='same frozen snapshot backward ASOF carry; no claim of newer industry disclosures',
                 grade='PIT_B_CAUSAL_RESEARCH_NOT_STRICT_ARCHIVE', coverage_status='PASS',
                 repaired_taxonomy_rows=int(coverage.mismatch.sum()))
    write_json(HERE/'output/mcb_snapshot_source_proof.json', proof)
    print('SNAPSHOT_RESTORED', coverage.to_dict('records'), flush=True)


def signals(end='2026-09-04'):
    binding()
    folder = CACHE / ('mcb_' + end)
    folder.mkdir(exist_ok=True)
    state = CACHE / 'mcb_market_industry_state.parquet'
    fn = producer(end)
    v53 = fn(CACHE/'mcb_features.parquet', state, folder/'v53.parquet')
    v65 = mcb.build_v65(v53, folder/'v65.parquet')
    selected = mcb.build_v72(v65, folder/'signals.parquet')
    # Obtain every pre-cooldown candidate before this one guard, for comparison
    # only. Production above always used the original guard.
    import inspect
    original = inspect.getsource(mcb.build_v53)
    revised = original.replace("DATE '2023-12-31'", f"DATE '{end}'")
    revised = revised.replace('AND d.industry_snapshot_id IS NOT NULL', '')
    revised = revised.replace('frame = con.execute(query).fetchdf()', 'frame = con.execute(query).fetchdf()\n        return frame')
    diagnostic = corrected_function(mcb.build_v53, [(original,revised)])
    candidates = diagnostic(CACHE/'mcb_features.parquet', state, folder/'unused.parquet')
    joined = pd.read_parquet(CACHE/'industry_join.parquet')
    evidence = candidates[['signal_date','symbol','causal_industry','industry_snapshot_id','available_at']].rename(columns={'signal_date':'date'})
    evidence = evidence.merge(joined[['trade_date','symbol','source','source_notice_date','source_effective_date']],
                              left_on=['date','symbol'],right_on=['trade_date','symbol'],validate='one_to_one').drop(columns='trade_date')
    evidence['parent_predicate'] = evidence.industry_snapshot_id.notna()
    evidence['rollforward_old_predicate'] = evidence.causal_industry.notna()
    evidence['same_result'] = evidence.parent_predicate.eq(evidence.rollforward_old_predicate)
    evidence.to_csv(HERE/'output/mcb_snapshot_predicate_equivalence.csv',index=False)
    old = pd.read_parquet(ROOT/'research/shared_capital_v1/cache/mcb/signals.parquet')
    prefix = selected.loc[selected.signal_date.le('2023-12-31')]
    if set(old.event_id) != set(prefix.event_id):
        raise ValueError('MCB historical signals changed')
    print('MCB_SIGNALS',len(selected),'PREFIX',len(prefix),'CANDIDATE_COMPARISON',len(evidence),flush=True)
    return selected


if __name__ == '__main__':
    prepare()
    signals()
