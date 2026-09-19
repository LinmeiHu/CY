"""Registered identifiability boundary, never a fallback for missing action facts."""
from decimal import Decimal as D, ROUND_FLOOR, ROUND_CEILING
import pandas as pd
from entitlement_contract_v1 import apportion

class BranchRequired(Exception):
    def __init__(self,evidence):self.evidence=evidence;super().__init__(str(evidence))

REGISTRY={}

def resolve_event(rights,t,day,choices):
    groups={}
    for a in rights:
        if not a['effective'] and str(a['source']['effective_date'].date())==day:groups.setdefault(a['source']['event_id'],[]).append(a)
    allocations={}
    for event,group in groups.items():
        extras=[D(a['base_q'])*(D(str(a['source']['share_multiplier']))-1) for a in group]
        if all(x==x.to_integral_value() for x in extras):continue
        src=group[0]['source'];evidence=REGISTRY.get(event)
        assert evidence and evidence['public_integer_allocation_unidentifiable'], 'UNPROVEN_ENTITLEMENT_IDENTIFIABILITY:'+event
        for a in group:
            s=a['source']
            for k in ['known_at','record_date','effective_date','share_credit_date','share_multiplier','cash_per_share_gross','bonus_share_ratio']:
                assert k in s and pd.notna(s[k]), 'MISSING_REQUIRED_ACTION_FACT:'+k
            assert s['known_at']<=pd.Timestamp(day)+pd.Timedelta(hours=9,minutes=15)
            assert s['record_date']<s['effective_date']<=s['share_credit_date']
            assert s.get('source_terms_complete')==True and s.get('execution_timing_resolved')==True
            assert D(str(s['share_multiplier']))==D(evidence['share_multiplier'])
            assert str(s['effective_date'].date())==evidence['effective_date']
            assert s['symbol']==evidence['symbol']
            assert a['base_q']>0 and int(a['base_q'])==a['base_q']
            # Retain the frozen V1 proof of allocation-independent physical orders.
            assert a['position']['due']<=t,'ALLOCATION_ORDER_INVARIANCE_NOT_PROVEN'
            assert D(str(s['cash_per_share_gross']))==0 and D(str(s['bonus_share_ratio']))==0,'TAX_ALLOCATION_NOT_PROVEN'
        assert len({str(a['source']['share_credit_date']) for a in group})==1
        ids=[a['position']['lot_id'] for a in group];assert len(set(ids))==len(ids)
        q=sum(extras,D(0));low=int(q.to_integral_value(rounding=ROUND_FLOOR));high=int(q.to_integral_value(rounding=ROUND_CEILING));assert low>=0
        if low!=high and event not in choices:
            raise BranchRequired(dict(event_id=event,t=t,date=day,record_shares=sum(a['base_q'] for a in group),theoretical_extra=str(q),LOW=low,HIGH=high,branches_are_not_strategies=True))
        if low==high:total=low
        else:
            assert choices[event] in ['LOW','HIGH'];total=low if choices[event]=='LOW' else high
        values=apportion(total,[a['base_q'] for a in group],ids)
        allocations.update({(event,lid):v for lid,v in zip(ids,values)})
    return allocations
