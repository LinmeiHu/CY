"""Evaluate newly qualified gap parents with frozen VAP and CY033 filters."""
import sys,importlib.util,inspect,json
from pathlib import Path
import pandas as pd
import duckdb
from five_strategy_bundle.strategies import ogr
from research.shared_capital_v1.causal_adapters import corrected_function
from research.portfolio_closure_v1 import repair
from .prepare_stock import HERE,CACHE,END
TOOLS=Path('/Users/linmei/Documents/CY-worktrees/five-strategy-capital-scaling-v1/research/capital_scaling_v1/tools')
sys.path.insert(0,str(TOOLS))
import build_gap_rollforward as native
ORIGINAL_MINUTE_SQL=native.minute_sql

def minute_sql(raw):
    original=ORIGINAL_MINUTE_SQL(raw)
    if not raw.name.startswith('2026_'):return original
    extras=sorted((CACHE/'gap_minutes').glob('*_1m.parquet'))
    assert len(extras)==2
    return original[:-1]+','+','.join("'"+str(p)+"'" for p in extras)+']'

def main():
    folder=CACHE/'ogr/new';folder.mkdir(exist_ok=True)
    with duckdb.connect() as c:
        daily=c.execute("SELECT * FROM read_parquet(?) WHERE trade_date>='2022-01-01' ORDER BY symbol,trade_date",[str(CACHE/'daily_with_snapshot.parquet')]).fetchdf()
    daily['symbol_seq']=daily.groupby('symbol',sort=False).cumcount()
    pre=pd.read_parquet(CACHE/'ogr/new_daily_qualified_candidates.parquet')
    vap=corrected_function(ogr.attach_v13_vap,[("read_parquet('{_sql_path(raw)}')",'read_parquet({minute_sql(raw)}, union_by_name=true)'),('    panel = entries.merge(metrics,',"    metrics.to_parquet(output/'minute_quality_metrics.parquet',index=False)\n    panel = entries.merge(metrics,")],minute_sql=minute_sql)
    result=vap(pre,daily,native.MINUTES,folder)
    quality=pd.read_parquet(folder/'minute_quality_metrics.parquet')
    assert len(quality)==len(pre) and quality.exact_minute_history.all(),quality.to_dict('records')
    print('NEW VAP SURVIVORS',len(result),'complete histories',len(quality),flush=True)
    for name in ['select_v28','select_v28r1','select_v28r2']:
        if result.empty:break
        fn=getattr(ogr,name);source=inspect.getsource(fn)
        result=corrected_function(fn,[(source,source.replace('(2018, 2019, 2020, 2021)','(2024, 2025, 2026)'))])(result,CACHE/'pit_full')
        result.to_parquet(folder/f'{name}.parquet',index=False);print(name,len(result),flush=True)
    ifcgr_new=result.iloc[:0].copy();outcomes_new=None
    if len(result):
        from five_strategy_bundle.strategies import ifcgr
        capture=CACHE/'issuer_capture'
        seal=json.loads((capture/'asset_manifest.json').read_text())
        assert seal['immutable']
        titles=pd.read_parquet(capture/'announcements.parquet')
        assert titles.hard_valid.all() and titles.exchange.eq('SZSE').all()
        assert titles.source_query_date_field.eq('publishTime').all()
        routes=titles.copy();routes['causal_available_at']=pd.to_datetime(routes.available_at)
        routes.to_parquet(capture/'causal_routes.parquet',index=False)
        fn=corrected_function(ifcgr.select_issuer_facts,[("TIMESTAMP '2022-01-01'",f"TIMESTAMP '{END}'")])
        ifcgr_new,rejected,classified=fn(result,capture/'causal_routes.parquet',capture/'announcements.parquet',capture/'announcements.parquet')
        for name,frame in [('selected',ifcgr_new),('rejected',rejected),('classified',classified)]:frame.to_parquet(capture/f'{name}.parquet',index=False)
        extension=CACHE/'gap_extension';(extension/'ogr').mkdir(parents=True,exist_ok=True)
        link=extension/'daily.parquet'
        if not link.exists():link.symlink_to(CACHE/'daily_with_snapshot.parquet')
        result.to_parquet(extension/'ogr/signals_post2023.parquet',index=False)
        native.OUT=extension;native.END=END;native.minute_sql=minute_sql
        native.outcomes()
        outcomes_new=pd.read_parquet(extension/'ogr/outcomes_post2023.parquet')
    parent=repair.SOURCE/'research/shared_capital_v1/cache'
    roll=Path('/Volumes/quant/CY_quant_research/five_strategy_capital_scaling_rollforward_v2')
    for strategy in ['ogr','ifcgr']:
        old=pd.read_parquet(parent/'ogr/signals.parquet') if strategy=='ogr' else pd.concat([pd.read_parquet(parent/'ifcgr'/p/'signals.parquet') for p in ['2018_2021','2022_2023']])
        new=pd.read_parquet(roll/strategy/'signals_post2023.parquet')
        out=CACHE/strategy;out.mkdir(exist_ok=True)
        pd.concat([old.loc[old.signal_date.lt('2024-01-01')],new,result if strategy=='ogr' else ifcgr_new],ignore_index=True).to_parquet(out/'signals_all.parquet',index=False)
    old=pd.read_parquet(parent/'ogr/outcomes.parquet');new=pd.read_parquet(roll/'ogr/outcomes_post2023.parquet')
    assert new.exit_date.notna().all() and new.exit_date.le('2026-09-04').all()
    pd.concat([old.loc[old.signal_date.lt('2024-01-01')],new]+([] if outcomes_new is None else [outcomes_new]),ignore_index=True).to_parquet(CACHE/'ogr/outcomes_all.parquet',index=False)
    repair.write_json(HERE/'gap_signal_audit.json',dict(status='PASS',end=END,new_daily_candidates=len(pre),new_final_parents=len(result),new_IFCGR=len(ifcgr_new),IFCGR='Frozen classifier on complete official 120-day SZSE window; source pages sealed',outcomes='Original outcomes preserved; new parent evaluated with Native one-minute execution and end censoring'))
if __name__=='__main__':main()
