"""Evidence-gated synthetic entitlement economics, separate from real CSDC credit."""
from decimal import Decimal as D, ROUND_FLOOR
from collections import defaultdict
import pandas as pd
import entitlement_boundary as legacy
from entitlement_contract_v1 import apportion

EVIDENCE = {}
MODE = 'ECONOMIC_CASH'  # LOW/HIGH are materiality paths, never strategies.
AUDIT = []

def dec(x):return D(str(x))

def initial_tax_rate(record_date):
    if record_date < '2013-01-01':return D('.1')
    if record_date < '2015-09-08':return D('.05')
    return D(0)

def physical_terms(q, ratio, dividend, prior_price, mode='ECONOMIC_CASH'):
    q,ratio,dividend,prior_price=map(dec,(q,ratio,dividend,prior_price))
    assert q>=0 and q==q.to_integral_value() and ratio>=0 and prior_price>dividend>=0
    assert mode in ['ECONOMIC_CASH','LOW','HIGH']
    theoretical=q*ratio;n=int(theoretical.to_integral_value(rounding=ROUND_FLOOR));f=theoretical-n
    pref=(prior_price-dividend)/(1+ratio)
    exact_cash=f*pref if mode=='ECONOMIC_CASH' else D(0)
    cash=exact_cash.quantize(D('1e-18'))
    cash_rounding_residual=exact_cash-cash
    if mode=='HIGH' and f:n+=1
    error=(q+n)*pref+cash+q*dividend-q*prior_price
    if mode=='ECONOMIC_CASH':assert abs(error)<=D('1e-18')
    return dict(theoretical=str(theoretical),shares=n,fraction=str(f),fraction_cash=str(cash),reference_price=str(pref),gross_dividend=str(q*dividend),coordinate_error=str(error),mode=mode,cash_rounding_residual=str(cash_rounding_residual))

def resolve_event(rights,t,day,choices,prior_price):
    groups=defaultdict(list)
    for a in rights:
        if not a['effective'] and str(a['source']['effective_date'].date())==day:groups[a['source']['event_id']].append(a)
    selected=set();alloc={}
    for eid,g in groups.items():
        extras=[dec(a['base_q'])*(dec(a['source']['share_multiplier'])-1) for a in g]
        if all(x==x.to_integral_value() for x in extras):continue
        # Existing zero-cash registered branch is unchanged.
        if eid not in EVIDENCE:continue
        ev=EVIDENCE[eid]
        assert ev['public_tail_allocation_unobservable'] and ev['official_source_sha256']
        s=g[0]['source'];assert ev['row_hash']==s['row_hash']
        for a in g:
            s=a['source']
            for k in ['known_at','record_date','effective_date','share_credit_date','pay_date','share_multiplier','cash_per_share_gross','bonus_share_ratio']:
                assert k in s and pd.notna(s[k]), 'MISSING_REQUIRED_ACTION_FACT:'+k
            assert s['known_at']<=pd.Timestamp(day)+pd.Timedelta(hours=9,minutes=15)
            assert s['record_date']<s['effective_date']<=s['share_credit_date']
            assert s['source_terms_complete'] and s['execution_timing_resolved']
            assert s['event_type']!='rights_issue' and dec(s['bonus_share_ratio'])==0
            assert a['base_q']>0 and int(a['base_q'])==a['base_q']
            assert a['position']['due']<=t,'ALLOCATION_ORDER_INVARIANCE_NOT_PROVEN'
            assert s['share_multiplier']==g[0]['source']['share_multiplier']
        assert len({str(a['source']['share_credit_date']) for a in g})==1
        g=sorted(g,key=lambda a:str(a['position']['lot_id']));s=g[0]['source']
        q=sum(a['base_q'] for a in g);z=physical_terms(q,dec(s['share_multiplier'])-1,s['cash_per_share_gross'],prior_price(g[0]['position']['j']),MODE)
        ids=[a['position']['lot_id'] for a in g];shares=apportion(z['shares'],[a['base_q'] for a in g],ids)
        for i,(a,n) in enumerate(zip(g,shares)):
            alloc[eid,a['position']['lot_id']]=n
            # Physical synthetic receivable assigned once, not per-lot rounded.
            a['fractional_cash_due']=dec(z['fraction_cash']) if i==0 else D(0)
            a['fractional_cash_paid']=False
        AUDIT.append(dict(event_id=eid,date=day,t=t,record_shares=q,**z));selected.add(eid)
    alloc.update(legacy.resolve_event([a for a in rights if a['source']['event_id'] not in selected],t,day,choices))
    return alloc
