"""Fork native SMV6 causal callback state and execute independent suffixes."""
from copy import copy, deepcopy
import json
from types import SimpleNamespace
import pandas as pd
from five_strategy_bundle.strategies import smv6
from research.scaling_regime_v1.boundary import load_etf
from research.shared_capital_v1.smv6_physical import PhysicalPlatform
from research.shared_capital_v1.shared_account.engine import PhysicalAccount
from .repair import OUT, END
from .shadow import path_metrics
from .assemble import csv


def clone(p):
    q=copy(p)
    for name in ['positions','shares','intent_rows']:
        setattr(q,name,deepcopy(getattr(p,name)))
    q.events=[];q.accounts=[]
    a=PhysicalAccount('OGR')
    for name in ['cash','initial_cash','sleeve_cash','lots','positions','marks','mark_times','pending_positions','price_bases','realized','fees','seen','native_failures','strategies']:
        setattr(a,name,deepcopy(getattr(p.physical,name)))
    q.physical=a
    c=SimpleNamespace(**deepcopy({k:v for k,v in vars(p.native_context).items() if k!='portfolio'}))
    c.portfolio=SimpleNamespace(stock_account=SimpleNamespace(positions=q.positions))
    q.native_context=c
    return q


def phase(p,ns,phase):
    c=p.native_context
    if phase=='before':
        p.event_stage='before_trading';ns['before_trading'](c)
    elif phase=='open':
        p.event_stage='open';ns['execute_pending_open'](c,p.bar_dict(),'LOCAL_09_30')
    elif phase=='signal':
        p.event_stage='signal';ns['run_1457_exit_signal'](c,p.bar_dict(include_signal=True))
    else:
        p.event_stage='close';ns['execute_pending_close_sells'](c,p.bar_dict(include_close=True));p.record_account()


def suffix(p,calendar,day_index,targets):
    q=clone(p);ns=smv6.frozen_namespace(q)
    paths={eid:[] for eid in targets};entries={};released={}
    # q contains causal pre-open state. The suffix has no access to parent fills
    # or parent future funding decisions: native callbacks use q's own cash.
    for idx in range(day_index,len(calendar)):
        q.current_date=calendar[idx].date()
        if idx>day_index:phase(q,ns,'before')
        for stage,hour,minute in [('open',9,30),('signal',14,57),('close',15,0)]:
            phase(q,ns,stage)
            when=calendar[idx]+pd.Timedelta(hours=hour,minutes=minute)
            for eid in targets:
                if eid in released:continue
                own=[f for f in q.physical.fills if f['event_id']==eid]
                buy=next((f for f in own if f['side']=='BUY'),None)
                if buy is None:continue
                entries[eid]=buy
                sales=[f for f in own if f['side']=='SELL']
                lot=q.physical.lots.get(eid)
                mark=None
                if lot is not None:
                    if stage=='signal':mark=q._minute_price(lot['symbol'],'PSEUDO_CLOSE_14_57_OPEN','pre_adj_open')
                    else:
                        role='OPEN_BAR_09_30' if stage=='open' else 'FINAL_CLOSE_BAR'
                        mark=q._minute_price(lot['symbol'],role,'pre_adj_open' if stage=='open' else 'pre_adj_close')
                    missing_quote=not __import__('math').isfinite(mark)
                    if missing_quote:
                        # Carry only an already observed account mark. Never
                        # substitute the current day's future daily close.
                        mark=q.physical.marks[lot['symbol']]
                value=0. if lot is None else lot['quantity']*mark
                pnl=sum(f['pnl'] for f in sales)+(value-lot['remaining_outlay'] if lot else 0.)
                paths[eid].append(dict(timestamp=when,pnl=pnl,exposure=value,quantity=0 if lot is None else lot['quantity'],mark_status='CARRY_PRIOR_LEGAL_MARK_MISSING_CHECKPOINT_QUOTE' if lot is not None and missing_quote else 'OBSERVED_OR_RELEASED'))
                if lot is None:released[eid]=max(pd.Timestamp(f['exit']) for f in sales)
        if all(eid in released for eid in targets):break
    rows=[];identity=[]
    for eid in targets:
        if eid not in entries:raise ValueError('cloned native opportunity not funded: '+eid)
        buy=entries[eid];exit_at=released.get(eid);own=[f for f in q.physical.fills if f['event_id']==eid]
        outlay=buy['funded_notional'];entry_at=pd.Timestamp(buy['entry'])
        rows.append(dict(opportunity_id=eid,strategy='SMV6',symbol=buy['symbol'],entry_at=entry_at,exit_at=exit_at,
            exit_reason='NATIVE_EXIT' if exit_at is not None else '',entry_notional=outlay,
            fees=sum(f['fee'] for f in own),corporate_actions='PRE_ADJUSTED_ETF_NATIVE_COORDINATE',
            status='COMPLETED' if exit_at is not None else 'RIGHT_CENSORED',**path_metrics(paths[eid],outlay,entry_at,exit_at)))
        identity.extend(own)
    return rows,identity, [dict(row,opportunity_id=eid) for eid,path in paths.items() for row in path]


def run(limit=None):
    requests=pd.read_parquet(OUT/'repair_accounts'/f'IFCGR__{END}'/'precapital.parquet')
    requests=requests.loc[requests.strategy.eq('SMV6')]
    if limit:requests=requests.head(limit)
    targets={day:list(g.event_id) for day,g in requests.groupby(requests.funding_at.dt.normalize())}
    daily,minute,availability=load_etf(END)
    calendar=list(daily['000852.SH'].loc['2018-01-01':END].dropna(subset=['pre_adj_close']).index)
    p=PhysicalPlatform(daily,minute,availability,calendar,initial_cash=1e6,lot_size=100,fee_bps=0)
    ns=smv6.frozen_namespace(p)
    p.native_context=SimpleNamespace(portfolio=SimpleNamespace(stock_account=SimpleNamespace(positions=p.positions)))
    ns['init'](p.native_context)
    rows=[];fills=[];allpaths=[]
    for idx,day in enumerate(calendar):
        p.current_date=day.date();phase(p,ns,'before')
        if day in targets:
            r,f,path=suffix(p,calendar,idx,targets[day]);rows.extend(r);fills.extend(f);allpaths.extend(path)
            print('SMV6_SHADOW',day.date(),'opportunities',len(rows),flush=True)
        for stage in ['open','signal','close']:phase(p,ns,stage)
        if len(rows)==len(requests):break
    actual=pd.DataFrame(fills);native=pd.read_parquet(OUT/'repair_accounts'/f'IFCGR__{END}'/'fills.parquet')
    identity=[]
    for eid,g in actual.groupby('event_id',sort=False):
        expected=native.loc[native.event_id.eq(eid)]
        fields=['side','entry','exit','quantity','filled_quantity','price','exit_price','fee','pnl']
        fields=[f for f in fields if f in g and f in expected]
        try:
            pd.testing.assert_frame_equal(g[fields].reset_index(drop=True),expected[fields].reset_index(drop=True),check_dtype=False,rtol=1e-10,atol=1e-6)
            status='PASS';error=''
        except AssertionError as err:status='FAIL';error=str(err)
        identity.append(dict(opportunity_id=eid,status=status,error=error))
    csv(pd.DataFrame(rows),'shadow_smv6_lifecycle_v2.csv.gz');csv(pd.DataFrame(identity),'shadow_smv6_identity_v2.csv')
    csv(pd.DataFrame(allpaths),'shadow_smv6_marked_paths_v2.csv.gz')
    print('SMV6_IDENTITY',pd.DataFrame(identity).status.value_counts().to_dict(),flush=True)


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--limit',type=int);a=p.parse_args();run(a.limit)
