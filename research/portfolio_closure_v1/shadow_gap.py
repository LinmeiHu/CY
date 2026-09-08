"""Recompute native Gap exits from raw minute bars, then execute isolated ledgers."""
from dataclasses import replace
import inspect
import json
from pathlib import Path
from types import MethodType
import duckdb
import pandas as pd
from five_strategy_bundle.strategies import ogr
from research.shared_capital_v1.causal_adapters import corrected_function
from research.shared_capital_v1 import gap_p0
from research.shared_capital_v1.shared_account.engine import PhysicalAccount
from .repair import OUT, END, ROOT, CACHE, SOURCE, write_json
from .shadow import path_metrics
from .assemble import csv

TOOLS=Path('/Users/linmei/Documents/CY-worktrees/five-strategy-capital-scaling-v1/research/capital_scaling_v1')
MINUTES=Path('/Users/linmei/Downloads/workspace/quant/data/lake/stock_1min_canonical_none_20260813/bars')
ROLL=Path('/Volumes/quant/CY_quant_research/five_strategy_capital_scaling_rollforward_v2')


def minute_sql(raw):
    paths=[raw]
    if raw.name.startswith('2026_'):
        paths.append(MINUTES/'2026_qmt_tail.parquet')
        requested=json.loads((TOOLS/'stock_minute_request.json').read_text())['symbols']
        paths.extend(TOOLS/'qmt_stock_delta'/f'{s}_1m.parquet' for s in requested)
    for p in paths:
        if not p.is_file():raise FileNotFoundError('Registered Gap minute input missing: '+str(p))
    return '['+','.join("'"+str(p).replace("'","''")+"'" for p in paths)+']'


def rebuild(entries,daily):
    config=json.loads((ROOT/'research/five_strategy_exit_risk_v1/input_config.json').read_text())['inputs']
    source=inspect.getsource(ogr.load_actions)
    fn=corrected_function(ogr.load_actions,[(source,source.replace("DATE '2022-03-31'",f"DATE '{END}'"))])
    actions=fn(Path(config['qd010_distributions']),Path(config['qd010_rights']),entries.symbol.tolist())
    source=inspect.getsource(ogr.build_outcomes)
    revised=source.replace(', 2023):',', 2027):').replace("DATE '2022-03-31'",f"DATE '{END}'")
    revised=revised.replace("read_parquet('{_sql_path(raw)}')",'read_parquet({minute_sql(raw)}, union_by_name=true)')
    revised=revised.replace('raise ReproductionError("OGR outcome calendar tail missing")','bounds["path_end_date"] = bounds.path_end_date.fillna(calendar.trade_date.max())')
    revised=revised.replace('if checkpoint.empty:\n            raise ReproductionError(f"OGR missing H20 checkpoint: {entry.gap_id}")\n        trigger = pd.Timestamp(checkpoint.trade_date.iloc[0]) + pd.Timedelta(hours=15)',
        'trigger = (pd.Timestamp(checkpoint.trade_date.iloc[0]) if len(checkpoint) else pd.Timestamp(calendar.trade_date.max())) + pd.Timedelta(hours=15)')
    revised=revised.replace('chosen = sorted(choices, key=lambda x:', '''if not choices:
            rows.append({**entry._asdict(), "alpha":0.67, "horizon":20, "stop":"NONE", "target_coordinate":target_coord,
                "exit_time":pd.NaT,"exit_date":pd.NaT,"exit_raw_price":float("nan"),"exit_cal_idx":float("nan"),
                "exit_reason":"OPEN_POSITION_AT_DATA_END","net_return":float("nan"),"holding_sessions":int(calendar.cal_idx.max())-int(entry.entry_cal_idx),
                "cash_events_json":"[]","lineage_break_before_exit":False})
            continue
        chosen = sorted(choices, key=lambda x:''')
    # Explicitly drop all inherited outcomes before invoking the native producer.
    entries=entries.drop(columns=[c for c in entries if c.startswith('exit_') or c in ['net_return','cash_events_json','lineage_break_before_exit','holding_sessions']],errors='ignore')
    return corrected_function(ogr.build_outcomes,[(source,revised)],minute_sql=minute_sql)(entries,daily,MINUTES,actions)


def isolated(request,entry,daily,actions):
    s=request['strategy'];eid=request['event_id'];start=str(pd.Timestamp(request['funding_at']).date())
    seed=max(1e6,request['requested_increase_notional']*200)
    a=PhysicalAccount(s,initial_cash=seed*4);a.strategies=(s,);a.initial_cash=a.cash=seed;a.sleeve_cash={s:seed};a.realized={s:0.}
    def fund(self,intents,home,policy,when,**kwargs):
        for i in intents:
            i=replace(i,native_requested_quantity=request['native_requested_quantity'])
            self.validate_intents([i],when);self._fill(i,i.native_requested_notional,'BASE',when)
    a.fund=MethodType(fund,a)
    actions=actions.loc[actions.symbol.eq(request['symbol'][:6])]
    stream,result=gap_p0.replay(s,entry,daily,start,END,physical=a,stream_only=True,action_registry=actions)
    path=[];exit_at=None
    for event in stream:
        event.callback()
        if a.fills:
            path.append(dict(timestamp=pd.Timestamp(event.when),pnl=a.cash+a.exposure()-seed,exposure=a.exposure()))
            if not a.lots and not a.held_actions[s].active:
                exit_at=pd.Timestamp(event.when);break
    f=pd.DataFrame(a.fills);buy=f.loc[f.side.eq('BUY')].iloc[0];outlay=buy.funded_notional
    row=dict(opportunity_id=eid,strategy=s,symbol=request['symbol'],entry_at=buy.entry,exit_at=exit_at,
        exit_reason=entry.exit_reason.iloc[0] if exit_at is not None else '',entry_notional=outlay,fees=a.fees,
        corporate_actions=json.dumps(a.held_actions[s].audit,sort_keys=True,default=str),status='COMPLETED' if exit_at is not None else 'RIGHT_CENSORED',
        **path_metrics(path,outlay,buy.entry,exit_at))
    return row,f


def run():
    op=pd.read_csv(OUT/'precapital_opportunities_v2.csv.gz')
    op=op.loc[op.strategy.isin(['OGR','IFCGR'])]
    old=pd.read_parquet(SOURCE/'research/shared_capital_v1/cache/ogr/outcomes.parquet')
    new=pd.read_parquet(ROLL/'ogr/outcomes_post2023.parquet')
    entries=pd.concat([old.loc[old.signal_date.lt('2024-01-01')],new],ignore_index=True)
    entries=entries.loc[entries.gap_id.isin(op.event_id)]
    symbols=pd.DataFrame({'symbol':entries.symbol.unique()})
    with duckdb.connect() as c:
        c.execute('SET threads=2');c.register('symbols',symbols)
        daily=c.execute('SELECT d.* FROM read_parquet(?) d JOIN symbols USING(symbol) ORDER BY symbol,trade_date',[str(CACHE/'daily_with_snapshot.parquet')]).fetchdf()
    p=OUT/'gap_recomputed_outcomes_v2.parquet'
    if not p.exists():
        print('GAP_RAW_RECOMPUTE',len(entries),flush=True)
        r=rebuild(entries,daily);r.to_parquet(p,index=False)
    else:r=pd.read_parquet(p)
    j=r.merge(entries,on='gap_id',suffixes=('_replay','_native'),validate='one_to_one')
    j['identity']=j.exit_time_replay.eq(j.exit_time_native)|(j.exit_time_replay.isna()&j.exit_time_native.isna())
    j['identity'] &= ((j.exit_raw_price_replay-j.exit_raw_price_native).abs().lt(1e-9)|(j.exit_raw_price_replay.isna()&j.exit_raw_price_native.isna()))
    csv(j[['gap_id','exit_time_replay','exit_time_native','exit_raw_price_replay','exit_raw_price_native','identity']],'gap_raw_exit_identity_v2.csv')
    if not j.identity.all():raise ValueError('Gap raw native exit identity mismatch; inspect exact differences')
    actions=pd.read_parquet(ROLL/'atrdr/action_registry.parquet');rows=[];identity=[]
    for n,q in enumerate(op.to_dict('records')):
        e=r.loc[r.gap_id.eq(q['event_id'])];d=daily.loc[daily.symbol.eq(q['symbol']),['symbol','trade_date','open','close']]
        row,f=isolated(q,e,d,actions);rows.append(row)
        folder=OUT/'repair_accounts'/f'{q["strategy"]}__{END}'
        native=pd.read_parquet(folder/'fills.parquet');nf=native.loc[native.event_id.eq(q['event_id'])]
        if nf.side.eq('BUY').any():
            fields=[x for x in ['side','entry','exit','quantity','filled_quantity','price','exit_price','fee','pnl'] if x in f and x in nf]
            try:
                pd.testing.assert_frame_equal(f[fields].reset_index(drop=True),nf[fields].reset_index(drop=True),check_dtype=False,rtol=1e-10,atol=1e-6);status='PASS';err=''
            except AssertionError as error:status='FAIL';err=str(error)
            identity.append(dict(opportunity_id=q['event_id'],strategy=q['strategy'],status=status,error=err))
        if n%50==0:print('GAP_SHADOW',n,flush=True)
    csv(pd.DataFrame(rows),'shadow_gap_lifecycle_v2.csv.gz');csv(pd.DataFrame(identity),'shadow_gap_identity_v2.csv')


if __name__=='__main__':run()
