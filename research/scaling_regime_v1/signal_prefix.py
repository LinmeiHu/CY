"""Re-run bounded stock feature/signal producers, retain Gap parent identities."""
import importlib.util
import inspect
import json
from types import SimpleNamespace
import duckdb
import pandas as pd
from five_strategy_bundle.strategies import atrdr,mcb
from research.shared_capital_v1.causal_adapters import corrected_function
from .snapshot import CACHE,producer
from .audit import HERE,ROOT,ROLL,write_json,sha256

ENDS=['2021-12-31','2022-12-31','2023-12-31','2024-12-31','2025-12-31','2026-09-04']


def run(end):
    base=CACHE/'signal_prefix'/end;base.mkdir(parents=True,exist_ok=True)
    path=HERE/'evidence/build_rollforward_inputs.py'
    spec=importlib.util.spec_from_file_location('bounded_signal_producer',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.OUT=base;module.END=end
    daily=base/'daily.parquet'
    with duckdb.connect() as c:
        c.execute('SET threads=2')
        c.execute(f"COPY (SELECT * FROM read_parquet('{CACHE}/daily_with_snapshot.parquet') WHERE trade_date<=?) TO '{daily}' (FORMAT PARQUET)",[end])
    module.screens(daily)
    # Re-use the original feature SQL only. Stop before the unauthorized guard
    # substitution and execute the original mcb.build_v53 predicate explicitly.
    original=inspect.getsource(module.mcb_screens)
    pre=original.split('    # Post-2023 raw panel')[0]
    pre+='    return feature,state\n'
    feature,state=corrected_function(module.mcb_screens,[(original,pre)])(daily)
    v53=producer(end)(feature,state,base/'mcb/v53.parquet')
    v65=mcb.build_v65(v53,base/'mcb/v65.parquet')
    result=mcb.build_v72(v65,base/'mcb/signals.parquet')
    rows=[]
    for strategy,name,identity in [('ATRDR','fast_signals','event_id'),('ATRDR','slow_signals','event_id'),('ATRDR','bull_signals','event_id'),('MCB','signals','event_id')]:
        a=pd.read_parquet(base/strategy.lower()/(name+'.parquet'))
        b=pd.read_parquet(CACHE/strategy.lower()/(name+'.parquet'))
        b=b.loc[b.signal_date.le(end)]
        # Compare the entire signal record, including pre-trade scores and ranks.
        fields=sorted(set(a.columns)&set(b.columns))
        sort=[identity] if identity in fields else ['signal_date','symbol']
        pd.testing.assert_frame_equal(a[fields].sort_values(sort).reset_index(drop=True),b[fields].sort_values(sort).reset_index(drop=True),check_dtype=False,rtol=1e-10,atol=1e-10)
        rows.append(dict(end=end,strategy=strategy,layer=name,rows=len(a),status='PASS',scope='RAW_DAILY_BOUND_BEFORE_FEATURE_AND_SIGNAL_PRODUCTION'))
    # Gap inputs are frozen signal intermediates. Their identity/decision times
    # are invariant; future exit metadata is removed by every account prefix.
    # Explicitly retain this evidence grade rather than claiming a raw-minute rerun.
    for strategy in ['OGR','IFCGR']:
        parent=ROOT/'research/shared_capital_v1/cache'
        old=pd.read_parquet(parent/'ogr/signals.parquet') if strategy=='OGR' else pd.concat([pd.read_parquet(parent/'ifcgr'/p/'signals.parquet') for p in ['2018_2021','2022_2023']])
        new=pd.read_parquet(ROLL/strategy.lower()/'signals_post2023.parquet')
        full=pd.concat([old.loc[old.signal_date.lt('2024-01-01')],new])
        a=full.loc[full.signal_date.le(end)].copy()
        assert not a.gap_id.duplicated().any()
        assert pd.to_datetime(a.signal_time).le(pd.Timestamp(end)+pd.Timedelta(hours=23)).all()
        a.to_parquet(base/(strategy.lower()+'_bound_signals.parquet'),index=False)
        rows.append(dict(end=end,strategy=strategy,layer='frozen_predecision_signal_identity',rows=len(a),status='PASS',scope='FROZEN_INTERMEDIATE_PREFIX_PLUS_ACTUAL_ACCOUNT_INTENT_PREFIX;NOT_RAW_MINUTE_REPRODUCTION'))
    write_json(base/'receipt.json',dict(end=end,rows=rows,source_sha256=sha256(daily),producer_sha256=sha256(path)))
    print('SIGNAL_PREFIX_PASS',end,flush=True)
    return rows


def main():
    rows=[]
    for end in ENDS:
        receipt=CACHE/'signal_prefix'/end/'receipt.json'
        if receipt.exists():rows+=json.loads(receipt.read_text())['rows']
        else:rows+=run(end)
        pd.DataFrame(rows).to_csv(HERE/'output/continuous_signal_prefix_invariance.csv',index=False)


if __name__=='__main__':main()
