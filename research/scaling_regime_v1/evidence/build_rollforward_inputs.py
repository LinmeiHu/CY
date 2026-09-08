"""Rebuild same-rule signal inputs on the audited extended raw daily panel."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pandas as pd

from five_strategy_bundle.strategies import atrdr, mcb, ogr
from research.shared_capital_v1.causal_adapters import corrected_function

BASE = Path('/Volumes/quant/CY_quant_research')
HIST = BASE / 'ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/pit_daily_compact_2013_2023.parquet'
TAIL = BASE / 'bull_medium_participation_industry_ignition_v64/post_2023_exact_diagnostic_through_2026_09_04/pit_daily_qd010_exact_frozen_symbols_2022_2026_09_04.parquet'
OUT = BASE / 'five_strategy_capital_scaling_rollforward_v2'
END = '2026-09-04'


def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as c:
        c.execute('SET threads=4')
        mismatch = c.execute('''SELECT count(*) FROM
          (SELECT DISTINCT symbol FROM read_parquet(?) EXCEPT SELECT DISTINCT symbol FROM read_parquet(?))''', [str(HIST), str(TAIL)]).fetchone()[0]
        reverse = c.execute('''SELECT count(*) FROM
          (SELECT DISTINCT symbol FROM read_parquet(?) EXCEPT SELECT DISTINCT symbol FROM read_parquet(?))''', [str(TAIL), str(HIST)]).fetchone()[0]
        overlap = c.execute('''SELECT count(*),sum((h.cal_idx<>t.cal_idx)::INT),
          sum((abs(h.coord_close-t.coord_close)>1e-8)::INT)
          FROM read_parquet(?) h JOIN read_parquet(?) t USING(symbol,trade_date)''', [str(HIST), str(TAIL)]).fetchone()
        if mismatch or reverse or overlap[1] or overlap[2]:
            raise ValueError(f'raw universe/coordinate mismatch: {mismatch}, {reverse}, {overlap}')
        common = sorted(set(c.execute('DESCRIBE SELECT * FROM read_parquet(?)',[str(HIST)]).fetchdf().column_name)
                        & set(c.execute('DESCRIBE SELECT * FROM read_parquet(?)',[str(TAIL)]).fetchdf().column_name))
        columns = ','.join(common)
        daily = OUT / 'daily.parquet'
        c.execute(f'''COPY (SELECT {columns} FROM read_parquet('{HIST}')
          UNION ALL SELECT {columns} FROM read_parquet('{TAIL}') WHERE trade_date>DATE '2023-12-31')
          TO '{daily}' (FORMAT PARQUET)''')
        (OUT/'raw_overlap_audit.json').write_text(json.dumps(dict(overlap_rows=overlap[0],
            cal_idx_mismatches=overlap[1],coordinate_mismatches=overlap[2],missing_symbols=mismatch,
            extra_symbols=reverse,history=str(HIST),tail=str(TAIL),end=END),indent=2))
    return daily


def screens(daily):
    folder = OUT/'atrdr'
    folder.mkdir(exist_ok=True)
    print('Rebuilding continuous V29 market and mother screens', flush=True)
    market = atrdr.build_market_state(daily, folder/'market.parquet',end=END)
    mother = atrdr.build_oai_mother(daily,folder/'fast_mother.parquet',end=END,expected_count=None)
    fast = atrdr.select_fast_bear(mother,market,folder/'fast_signals.parquet')
    slow = atrdr.build_slow_mother(daily,folder/'market.parquet',folder/'slow_signals.parquet',end=END)
    bull_fn = corrected_function(atrdr.build_simple_bull,[("DATE '2023-12-31'",f"DATE '{END}'")])
    bull = bull_fn(daily,folder/'bull_signals.parquet')
    rows=[]
    for name,frame in [('fast',fast),('slow',slow),('bull',bull)]:
        dates=pd.to_datetime(frame.signal_date)
        rows.append(dict(route=name,rows=len(frame),post2023=int((dates>='2024-01-01').sum()),last_signal=str(dates.max())))
    pd.DataFrame(rows).to_csv(folder/'signal_coverage.csv',index=False)
    print(pd.DataFrame(rows).to_string(index=False),flush=True)


def mcb_screens(daily):
    folder=OUT/'mcb'
    folder.mkdir(exist_ok=True)
    feature=folder/'daily_features.parquet'
    state=folder/'market_industry_state.parquet'
    with duckdb.connect() as c:
        c.execute('SET threads=4')
        c.execute(f'''COPY (WITH w AS (SELECT *,
          lag(cal_idx) OVER w AS prev_idx,
          lag(coord_close,20) OVER w AS lag20_close,lag(cal_idx,20) OVER w AS lag20_idx,
          lag(coord_close,60) OVER w AS lag60_close,lag(cal_idx,60) OVER w AS lag60_idx,
          arg_max(CASE WHEN history_valid THEN trade_date END,CASE WHEN history_valid THEN coord_high END) OVER p AS prior250_peak_date,
          arg_max(CASE WHEN history_valid THEN invalid_step_cum END,CASE WHEN history_valid THEN coord_high END) OVER p AS prior250_peak_invalid_cum
          FROM read_parquet('{daily}') WINDOW w AS(PARTITION BY symbol ORDER BY trade_date),
          p AS(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 250 PRECEDING AND 1 PRECEDING))
          SELECT *,CASE WHEN prev_idx=cal_idx-1 THEN coord_close/prior_coord_close-1 END AS step_return,
          CASE WHEN lag20_idx=cal_idx-20 THEN coord_close/lag20_close-1 END AS ret20,
          CASE WHEN lag60_idx=cal_idx-60 THEN coord_close/lag60_close-1 END AS ret60
          FROM w) TO '{feature}' (FORMAT PARQUET)''')
        c.execute(f'''COPY (WITH b AS(SELECT * FROM read_parquet('{feature}')
          WHERE current_valid AND hard_valid AND NOT is_st),
          m AS(SELECT trade_date,count(*) market_n,median(ret20) market20,median(ret60) market60,
            avg((ret20>0)::INT) market_breadth20,avg((ret60>0)::INT) market_breadth60 FROM b GROUP BY 1),
          i AS(SELECT trade_date,causal_industry,count(*) industry_n,median(ret20) industry20,
            median(ret60) industry60,avg((ret20>0)::INT) industry_breadth20,
            avg((ret60>0)::INT) industry_breadth60 FROM b GROUP BY 1,2)
          SELECT * FROM i JOIN m USING(trade_date)) TO '{state}' (FORMAT PARQUET)''')
    # Post-2023 raw panel supplies causal_industry and industry_valid, but no snapshot-id column.
    function=corrected_function(mcb.build_v53,[
        ("trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'",f"trade_date BETWEEN DATE '2013-01-01' AND DATE '{END}'"),
        ("d.trade_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31'",f"d.trade_date BETWEEN DATE '2014-01-01' AND DATE '{END}'"),
        ('d.industry_snapshot_id IS NOT NULL','d.causal_industry IS NOT NULL'),
    ])
    v53=function(feature,state,folder/'v53.parquet')
    v65=mcb.build_v65(v53,folder/'v65.parquet')
    signals=mcb.build_v72(v65,folder/'signals.parquet')
    old=pd.read_parquet(Path(__file__).resolve().parents[2]/'shared_capital_v1/cache/mcb/signals.parquet')
    prefix=signals.loc[pd.to_datetime(signals.signal_date)<'2024-01-01']
    missing=set(old.event_id)-set(prefix.event_id)
    extra=set(prefix.event_id)-set(old.event_id)
    audit=dict(historical_rows=len(old),rebuilt_historical_rows=len(prefix),missing=len(missing),extra=len(extra),
               new_signals=int((pd.to_datetime(signals.signal_date)>='2024-01-01').sum()),last_signal=str(signals.signal_date.max()))
    (folder/'signal_parity.json').write_text(json.dumps(audit,indent=2))
    print(audit,flush=True)
    if missing or extra:
        raise ValueError('MCB historical signal identity mismatch')


def entries(daily, strategy):
    from research.shared_capital_v1 import build_inputs
    folder=OUT/strategy.lower()
    def cached(name):
        return lambda *args, **kwargs: pd.read_parquet(folder/(name+'.parquet'))
    if strategy=='ATRDR':
        producer=SimpleNamespace(build_market_state=cached('market'),build_oai_mother=cached('fast_mother'),
            select_fast_bear=cached('fast_signals'),build_slow_mother=cached('slow_signals'),build_simple_bull=cached('bull_signals'))
        fn=corrected_function(build_inputs.atrdr_inputs,[],atrdr=producer,execution_paths=lambda inputs:[daily],
            emit=lambda message:print(message.replace('<=2023',f'through {END}'),flush=True))
    else:
        producer=SimpleNamespace(build_v53=cached('v53'),build_v64=lambda *args:None,
            build_v65=cached('v65'),build_v72=cached('signals'))
        fn=corrected_function(build_inputs.mcb_inputs,[],mcb=producer,execution_paths=lambda inputs:[daily],
            emit=lambda message:print(message.replace('<=2023',f'through {END}'),flush=True))
    fn(dict(daily_hist=daily,mcb_market_industry_state=folder/'market_industry_state.parquet'),folder)


def stock_account(daily,strategy):
    from research.shared_capital_v1.stock_p0 import replay
    from research.shared_capital_v1.shared_account.held_actions import registered_actions
    folder=OUT/strategy.lower()
    population=pd.read_parquet(folder/'precapital_entry_population.parquet')
    with duckdb.connect() as c:
        registry=pd.DataFrame({'symbol':population.symbol.unique()})
        c.register('registry',registry)
        prices=c.execute('SELECT d.* FROM read_parquet(?) d JOIN registry USING(symbol)',[str(daily)]).fetchdf()
    actions=corrected_function(registered_actions,[("'2023-12-31'",f"'{END}'")])()
    # Issuer implementation notice 2025-021, pages 1-2 (CNInfo 1223695580).
    event=actions.event_id.eq('cninfo:distribution:88c85b37759f6715fa8085123538eb7b')
    if event.sum()!=1:
        raise ValueError('official action identity drift')
    actions.loc[event,'tradable_date']=pd.Timestamp('2025-06-05')
    actions.loc[event,'pay_date']=pd.Timestamp('2025-06-05')
    actions.loc[event,'evidence_source']='https://static.cninfo.com.cn/finalpage/2025-05-28/1223695580.PDF'
    event=actions.event_id.eq('cninfo:distribution:8471f7867a9f8d06619862d8fc961e85')
    if event.sum()!=1:
        raise ValueError('official action identity drift')
    actions.loc[event,'tradable_date']=pd.Timestamp('2026-05-29')
    actions.loc[event,'pay_date']=pd.Timestamp('2026-05-29')
    actions.loc[event,'evidence_source']='https://static.cninfo.com.cn/finalpage/2026-05-21/1225323425.PDF'
    from correct_rollforward_facts import receipt
    for url in ['https://static.cninfo.com.cn/finalpage/2025-05-28/1223695580.PDF',
                'https://static.cninfo.com.cn/finalpage/2026-05-21/1225323425.PDF']:
        evidence=receipt(url)
        actions.loc[actions.evidence_source.eq(url),'evidence_hash']=evidence['sha256']
        actions.loc[actions.evidence_source.eq(url),'retrieved_at']=evidence['retrieved_at']
    actions.to_parquet(folder/'action_registry.parquet',index=False)
    account,intents,rejects,nav,blocker=replay(strategy,population,prices,'2014-01-01',END,
        boundaries=('2018-01-01','2022-01-01','2024-01-01'),action_registry=actions)
    nav.to_parquet(folder/'continuous_nav.parquet',index=False)
    pd.DataFrame(account.held_actions[strategy].audit).to_csv(folder/'held_actions.csv',index=False)
    pd.DataFrame(account.fills).to_parquet(folder/'continuous_fills.parquet',index=False)
    status=dict(strategy=strategy,required_end=END,observed_end=str(nav.trade_date.max()),blocker=blocker,days=len(nav))
    (folder/'account_status.json').write_text(json.dumps(status,indent=2,default=str))
    print(status,flush=True)
    if blocker:
        raise ValueError(blocker)


def gap_candidates(daily):
    folder=OUT/'ogr'
    folder.mkdir(exist_ok=True)
    with duckdb.connect() as c:
        frame=c.execute("SELECT * FROM read_parquet(?) WHERE trade_date>='2022-01-01' ORDER BY symbol,trade_date",[str(daily)]).fetchdf()
    frame['symbol_seq']=frame.groupby('symbol',sort=False).cumcount()
    gaps=ogr.build_all_true_gaps(frame)
    print(f'OGR raw gaps {len(gaps)}',flush=True)
    candidates=ogr.build_v13_candidates(frame,gaps)
    candidates=candidates.loc[candidates.signal_date>='2024-01-01']
    candidates.to_parquet(folder/'v13_post2023_candidates.parquet',index=False)
    print(f'OGR raw candidates {len(candidates)} through {candidates.signal_date.max()}',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--stage',choices=['daily','atrdr','mcb','atrdr-entries','mcb-entries','atrdr-account','mcb-account','ogr-candidates','all'],default='all')
    args=parser.parse_args()
    daily=prepare() if args.stage in ('daily','all') else OUT/'daily.parquet'
    if args.stage in ('atrdr','all'):
        screens(daily)
    if args.stage in ('mcb','all'):
        mcb_screens(daily)
    for strategy in ('ATRDR','MCB'):
        if args.stage in (strategy.lower()+'-entries','all'):
            entries(daily,strategy)
        if args.stage in (strategy.lower()+'-account','all'):
            stock_account(daily,strategy)
    if args.stage in ('ogr-candidates','all'):
        gap_candidates(daily)
