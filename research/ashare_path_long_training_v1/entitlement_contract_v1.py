"""Physical entitlement branch first; virtual allocation never sets physical total."""
from decimal import Decimal as D
EVENT='cninfo:distribution:e599c21023d59644156873091cf21818'

def apportion(total,bases,ids):
    assert total>=0 and sum(bases)>0 and len(set(ids))==len(ids)
    den=sum(bases);q=[total*b//den for b in bases];rem=[total*b%den for b in bases]
    for i in sorted(range(len(bases)),key=lambda i:(-rem[i],str(ids[i])))[:total-sum(q)]:q[i]+=1
    assert sum(q)==total
    return q

def resolve_event(rights,t,day,branch):
    assert branch in ['LOW','HIGH']
    group=[a for a in rights if a['source']['event_id']==EVENT and not a['effective'] and str(a['source']['effective_date'].date())==day]
    if not group:return {}
    assert day=='2015-03-26'
    bases=[a['base_q'] for a in group];ids=[a['position']['lot_id'] for a in group]
    assert sum(bases)==66100, 'UNREGISTERED_PHYSICAL_OWNERSHIP_REQUIRES_NEW_CONTRACT'
    assert all(D(str(a['source']['share_multiplier']))==D('1.7000522') for a in group)
    # All lots must already be due, and receive shares simultaneously. Then physical
    # execution aggregates them before selling: any internal apportionment yields
    # exactly the same physical orders within this branch. Not a general lot-rounding rule.
    assert all(a['position']['due']<=t for a in group),'ALLOCATION_ORDER_INVARIANCE_NOT_PROVEN'
    assert len({str(a['source']['share_credit_date']) for a in group})==1
    assert all(D(str(a['source']['cash_per_share_gross']))==0 and D(str(a['source']['bonus_share_ratio']))==0 for a in group),'TAX_ALLOCATION_NEEDS_SEPARATE_PROOF'
    total=46273 if branch=='LOW' else 46274
    values=apportion(total,bases,ids)
    return {(EVENT,lid):q for lid,q in zip(ids,values)}
