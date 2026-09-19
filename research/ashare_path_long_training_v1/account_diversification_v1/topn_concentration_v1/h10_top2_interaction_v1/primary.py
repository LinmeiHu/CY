"""Frozen RAW O2 H10 Top2; reuse authoritative Top10 annual start states."""
import argparse, fcntl, json, os, pickle
from pathlib import Path
from decimal import Decimal as D
import numpy as np
import pandas as pd
import m0_three_arm_accounts as a
import corporate_action_engine_v2 as e
import corporate_action_contract_v2 as ca

W=Path(__file__).resolve().parent
H=W.parents[1]/'signal_holding_horizon_2x2_v1'
HB=a.OUT.parent/'signal_holding_horizon_2x2_v1'
OUT=a.OUT.parent/'topn_concentration_v1/h10_top2_interaction_v1'

def source(topn):
    spec=json.loads((H/'ACCOUNT_ADAPTER_SPEC.json').read_text())
    assert a.sha(Path(e.__file__))==spec['parent_sha256']
    # Initial horizon spec predates the documented numerical repair used by
    # its completed accounts. Pin the repaired contract, do not revert it.
    assert a.sha(Path(ca.__file__))=='6e47013c634300389331f974d2ac77eb42ffec1b1840d964639dcdfa633eb21c'
    assert a.sha(H/'HORIZON_RUN_SOURCE.py')==spec['adapter_sha256']
    s=(H/'HORIZON_RUN_SOURCE.py').read_text()
    assert s.count("D('.005')")==2 and s.count('slots=10 if stagger')==1
    s=s.replace("D('.005')",f"(D('.05')/D({topn}))").replace('slots=10 if stagger',f'slots={topn} if stagger')
    # Read-only planning audit. The operations which size orders are unchanged.
    s=s.replace('for r in candidates.itertuples():','for candidate_rank,r in enumerate(candidates.itertuples(),1):')
    s=s.replace("     qty=size(budget,cap,day,symbols[j])", "     audit=dict(t=t,j=j,candidate_rank=candidate_rank,nav=str(navnow),available=str(available),budget_after_cap=str(budget),existing_q=existing if stagger else 0,cap=str(cap),single_name_room=str(max(D(0),navnow*D('.1')-dec(existing)*cap)) if stagger else None,per_name_budget=str(navnow*((D('.05')/D("+str(topn)+"))*D(20)/D(holding_horizon))*stagger_scale),live_lots=sum(p['j']==j for p in positions.values()))\n     qty=size(budget,cap,day,symbols[j]);audit.update(quantity=qty,status='PLANNED' if qty else 'ZERO_SIZE');planning_audit.append(audit)")
    return s

def reconcile(read,ts):
    nav=read('nav');g=nav[nav.t.isin(ts)].copy();assert len(g)==len(ts)
    cash=D(1000000)
    for z in read('cashflows').itertuples():cash+=D(z.cash_delta);assert cash==D(z.cash_after)
    physical=read('inventory').groupby('t').value.agg(lambda z:sum(map(D,z),D(0)))
    virtual=read('lot_inventory').groupby('t').value.agg(lambda z:sum(map(D,z),D(0)))
    for z in g.itertuples():
        assert D(z.cash)+D(z.market_value)+D(z.receivable)==D(z.nav)
        assert physical.get(z.t,D(0))==virtual.get(z.t,D(0))==D(z.market_value)
    return g

def run(year,parity=False,scale='1'):
    assert 2010<=year<=2019
    topn=10 if parity or scale!='1' else 2
    arm='IDENTITY_TOP10' if parity else 'FIXED_TOP10' if scale!='1' else 'H10_TOP2'
    dest=OUT/arm/str(year);dest.mkdir(parents=True,exist_ok=True)
    lock=open(dest/'lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    dates,symbols,ts,actions,cfg,market,_=a.context(year)
    for eid,z in json.loads((a.DOC/'ACTION_TIMING_SUPPLEMENT.json').read_text()).items():
        ix=actions.event_id==eid;assert ix.sum()==1 and actions.loc[ix,'row_hash'].iloc[0]==z['parent_row_hash']
        actions.loc[ix,'share_credit_date']=pd.Timestamp(z['engine_share_credit_date'])
    ca.EVIDENCE=json.loads((a.DOC/'CORPORATE_ACTION_EVIDENCE_REGISTRY.json').read_text());ca.MODE='ECONOMIC_CASH';ca.AUDIT=[]
    proof=json.loads((HB/'annual'/str(year)/'STARTS.json').read_text())
    assert proof['adapter']==json.loads((H/'ACCOUNT_ADAPTER_SPEC.json').read_text())['adapter_sha256']
    starts=[s for s in proof['starts'] if s['arm']=='B'];assert starts
    f=pd.read_parquet(HB/'daily'/f'{year}.parquet',columns=['t','j','A_RESIDUAL_positive_gate','A_RESIDUAL_score','A_RESIDUAL_pred20','logamount20'])
    assert f.t.min()>=ts[0] and f.t.max()<=ts[-1]
    sig=f.loc[f.A_RESIDUAL_positive_gate,['t','j','A_RESIDUAL_score','A_RESIDUAL_pred20','logamount20']].rename(columns={'A_RESIDUAL_score':'score','A_RESIDUAL_pred20':'pred20'})
    assert (sig.pred20>0).all()
    e.OUT=dest/'ledgers';e.OUT.mkdir(exist_ok=True)
    src=source(topn);(dest/'RUN_SOURCE.py').write_text(src)
    scope=dict(e.__dict__,holding_horizon=10,normalize_t=None,planning_audit=[]);exec(src,scope)
    end=ts[4] if parity and year!=2015 else ts[-1];results=[];checks=[]
    for start in starts:
        assert a.sha(Path(start['path']))==start['hash'] and D(start['START_NAV'])==1000000
        queue=[(start['choices'],start['tag'])];leaves=0
        while queue:
            choices,tag=queue.pop(0);name=f'Y{year}_{arm}_{tag}';done=dest/(name+'_RESULT.json')
            identity=dict(start=start['hash'],signal=a.sha(HB/'daily'/f'{year}.parquet'),source=a.sha(dest/'RUN_SOURCE.py'),choices=choices,scale=scale)
            if done.exists():
                old=json.loads(done.read_text());assert old['identity']==identity;results.append(old);continue
            scope['planning_audit']=[];ca.AUDIT=[]
            r=scope['run'](name,sig,market,actions,dates,symbols,forecast_through=end,stagger=True,stagger_scale=D(scale),resume_path=start['path'],snapshot_path=dest/(name+'.pkl'),entitlement_branch=choices)
            a.write(dest/(name+'_ENGINE.json'),r)
            if r['status']=='ENTITLEMENT_BRANCH_REQUIRED':
                assert len(queue)+leaves+2<=cfg['max_leaves']
                queue.extend([({**choices,r['block']['event_id']:v},tag+'_'+v) for v in ['LOW','HIGH']]);continue
            assert r['block'] is None,r
            pd.DataFrame(scope['planning_audit']).to_parquet(dest/(name+'_PLANNING.parquet'),index=False)
            read=lambda k:pd.read_parquet(e.OUT/f'{name}_funded_prefix_{k}.parquet')
            g=reconcile(read,[t for t in ts if t<=end])
            if parity:
                for kind in ['nav','orders','cashflows','inventory','inventory_events','lot_inventory','lot_fills','lot_actions']:
                    actual=read(kind);expected=pd.read_parquet(HB/'annual'/str(year)/'ledgers'/f'Y{year}_B_{tag}_funded_prefix_{kind}.parquet')
                    if 't' in actual:actual=actual[actual.t.between(ts[0],end)].reset_index(drop=True)
                    else:assert actual.empty
                    if 't' in expected:expected=expected[expected.t.between(ts[0],end)].reset_index(drop=True)
                    else:assert expected.empty
                    if actual.empty and expected.empty:pass  # No events; full-year schema may include later events.
                    else:pd.testing.assert_frame_equal(actual,expected,check_exact=True)
                    checks.append(dict(year=year,branch=tag,table=kind,rows=len(actual),exact=True))
            fills=read('lot_fills');fills=fills[fills.t.isin(ts)];orders=read('orders');bu=orders[(orders.side=='BUY')&orders.t.isin(ts)];ff=fills[fills.side=='BUY'];v=g.nav.astype(float);ret=float(v.iloc[-1]/1e6-1);dd=-float(np.min(v/np.maximum.accumulate(np.r_[1e6,v])[1:]-1));expo=g.market_value.astype(float)/v
            requested=float(bu.reserved.astype(float).sum());funded=float(-ff.cash_delta.astype(float).sum())
            result=dict(identity=identity,year=year,arm=arm,branch=tag,MODEL_LINEAGE='RAW_O2_A_RESIDUAL',MODEL_IDENTITY='A_RESIDUAL_B32768_FIXED3',SEED_SET='17,29,43',SIGNAL_IDENTITY='RET20_PERCENTILE_CONSENSUS_RAW_MEAN_GATE',HOLDING_HORIZON=10,TOPN=topn,annual_return=ret,MaxDD=dd,Calmar=ret/dd if dd else None,average_exposure=float(expo.mean()),peak_exposure=float(expo.max()),average_cash=float((g.cash.astype(float)/v).mean()),turnover=float((fills.quantity*fills.price.astype(float)).sum()/v.mean()),fees=float(fills.fees.astype(float).sum()),requested_new_capital=requested,filled_new_capital=funded,buy_fills=len(ff),zero_new_cohort_days=len(ts)-bu.decision_t.nunique(),filled_requested_ratio=funded/requested if requested else None,account_reconciliation='EXACT_DECIMAL',canonical_start_NAV='1000000',year_end_forced_liquidation=False,ledger=str(e.OUT),policy=name)
            a.write(done,result);results.append(result);leaves+=1;print('ACCOUNT_COMPLETE',year,arm,tag,ret,dd,flush=True)
    pd.DataFrame(results).to_csv(dest/'RESULTS.csv',index=False)
    if parity:a.write(W/f'PRIMARY_IDENTITY_PARITY_{year}.json',dict(status='PASS',checks=checks,source=a.sha(dest/'RUN_SOURCE.py')))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--year',type=int,required=True);p.add_argument('--parity',action='store_true');p.add_argument('--scale',default='1');args=p.parse_args()
    run(args.year,args.parity,args.scale)
