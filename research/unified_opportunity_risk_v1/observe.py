"""Read-only lifecycle instrumentation on the existing authoritative scheduler."""
from collections import defaultdict
import json
from pathlib import Path
import pandas as pd
from research.portfolio_closure_v1 import repair
from research.scaling_regime_v1 import accounts
from research.shared_capital_v1.causal_adapters import corrected_function
from research.capital_scaling_v1.run import save_account

HERE=Path(__file__).resolve().parent
OUT=HERE/'output'


def run(gap):
    dest=OUT/'native_replay'/gap;dest.mkdir(parents=True,exist_ok=True)
    rows=[];realized=defaultdict(float);last_fill=0;last_credit=0;meta={}
    def initialize(gap,states):
        account=repair.observed_initialize(gap,states)
        original=account.fund
        def fund(intents,home,policy,when,**kwargs):
            snapshot=json.dumps({eid:dict(strategy=l['strategy'],route=l['route'],symbol=l['symbol'],root_event_id=l.get('root_event_id',eid),exposure=(l['quantity']+l.get('pending_quantity',0.))*account.marks[l['symbol']]) for eid,l in account.lots.items()},sort_keys=True)
            ordinal=len(account.capital_events)
            result=original(intents,home,policy,when,**kwargs)
            account.capital_events[ordinal]['risk_holdings_json']=snapshot
            return result
        account.fund=fund
        return account
    def capture(when,account):
        nonlocal last_fill,last_credit
        touched=set()
        for f in account.fills[last_fill:]:
            root=f.get('root_event_id',f['event_id']);touched.add(root)
            meta[root]=(f['strategy'],f['symbol'])
            if f['side']=='SELL':realized[root]+=f['pnl']
        last_fill=len(account.fills)
        for c in account.cash_distributions[last_credit:]:
            root=c['root_event_id'];realized[root]+=c['amount'];touched.add(root)
        last_credit=len(account.cash_distributions)
        exposure=defaultdict(float);basis=defaultdict(float);quantity=defaultdict(float);pending=defaultdict(float)
        for eid,l in account.lots.items():
            root=l.get('root_event_id',eid);touched.add(root);meta[root]=(l['strategy'],l['symbol'])
            exposure[root]+=(l['quantity']+l.get('pending_quantity',0.))*account.marks[l['symbol']]
            basis[root]+=l['remaining_outlay'];quantity[root]+=l['quantity'];pending[root]+=l.get('pending_quantity',0.)
        for root in sorted(touched):
            strategy,symbol=meta.get(root,('',''))
            rows.append(dict(timestamp=pd.Timestamp(when),opportunity_id=root,strategy=strategy,symbol=symbol,
                exposure=exposure[root],quantity=quantity[root],pending_quantity=pending[root],
                pnl=realized[root]+exposure[root]-basis[root],realized_pnl=realized[root],remaining_outlay=basis[root],
                source='AUTHORITATIVE_PHYSICAL_ACCOUNT_ACTUAL_HOLDINGS'))
    replay=corrected_function(accounts.replay,[
        ('row=account.complete_timestamp(when)','capture(when,account)\n        row=account.complete_timestamp(when)'),
        ('daily.append(dict(row,trade_date=when.normalize()))','daily_observation(account,platform,scaling,row)\n            daily.append(dict(row,trade_date=when.normalize()))')],
        initialize=initialize,PhysicalPlatform=repair.ObservedPlatform,capture=capture,daily_observation=accounts.daily_observation)
    print('AUTHORITATIVE_LOAD',gap,flush=True);data=repair.load(repair.END)
    print('AUTHORITATIVE_OBSERVED_REPLAY',gap,flush=True)
    account,nav,results,platform,trace=replay(data,gap,accounts.PERIOD,'2018-01-01',repair.END)
    save_account(dest,account,nav,None)
    pd.DataFrame(rows).to_parquet(dest/'actual_root_paths.parquet',index=False)
    for name,frame in [('precapital',pd.DataFrame(account.precapital)),('capital_events',pd.DataFrame(account.capital_events)),
        ('callback_requests',pd.DataFrame(account.callback_requests)),('cash_distributions',pd.DataFrame(account.cash_distributions)),
        ('smv6_events',pd.DataFrame(platform.events))]:
        if 'native_priority' in frame:frame.native_priority=frame.native_priority.map(json.dumps)
        frame.to_parquet(dest/(name+'.parquet'),index=False)
    reference=repair.CACHE/'accounts'/f'{gap}__independent__NATIVE__FULL_BOOK_NORMALIZATION__{repair.END}'
    checks=[]
    for name,fields in [('timeline',['timestamp','cash','nav','gross_exposure','fees']),('daily',['trade_date','cash','nav','gross_exposure','fees','positions_json','lots_json','root_pnl_json']),
                        ('fills',['event_id','root_event_id','strategy','symbol','side','entry','exit','quantity','filled_quantity','price','exit_price','fee','pnl','reason'])]:
        actual=pd.read_parquet(dest/(name+'.parquet'));expected=pd.read_parquet(reference/(name+'.parquet'))
        pd.testing.assert_frame_equal(actual[fields],expected[fields],check_dtype=False,rtol=1e-10,atol=1e-6)
        checks.append(dict(gap=gap,artifact=name,rows=len(actual),status='PASS'))
    actual_snapshot=json.loads((dest/'account.json').read_text());expected_snapshot=json.loads((reference/'account.json').read_text())
    assert actual_snapshot==expected_snapshot, 'authoritative terminal/account-capital-days snapshot drift'
    checks.append(dict(gap=gap,artifact='account_snapshot_including_capital_days',rows=1,status='PASS'))
    repair.write_json(dest/'observation_receipt.json',dict(status='PASS',reconciliation=checks,
        path_source='Existing authoritative native scheduler; no shadow execution',
        hashes={p.name:repair.digest(p) for p in sorted(dest.glob('*.parquet'))}))
    print('AUTHORITATIVE_IDENTITY_PASS',checks,flush=True)


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--gap',choices=['OGR','IFCGR'],default='IFCGR');a=p.parse_args();run(a.gap)
