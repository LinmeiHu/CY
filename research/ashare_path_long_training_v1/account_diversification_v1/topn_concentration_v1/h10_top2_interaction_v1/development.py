"""Consumed-development H10 accounts; frozen centered three/seven-seed signals."""
import argparse,fcntl,json,pickle
from pathlib import Path
from decimal import Decimal as D
import numpy as np
import pandas as pd
import entitlement_boundary_engine as e
import entitlement_boundary as boundary
from common import OUT as ROOT,PANEL,get,sha
from primary import W,OUT,reconcile,a

DOC=W.parents[1];BROOT=ROOT/'account_diversification_v1';B7=BROOT/'topn_concentration_v1/centered_vote7';B3=BROOT/'topn_concentration_v1/centered_vote_top2'
W7=W.parent/'centered_vote7';W3=W.parent/'centered_vote_top2'
def load(p):return json.loads(p.read_text())
def source(year,h,n):
    path=BROOT/'linear_positive_gate_transfer_2020_2023_v1'/str(year)/'RUN_SOURCE.py'
    assert sha(path)=='f1cab2cba4ce9e4dc125254e839b86c46f0dbb293961606bac3904475dfd770b'
    s=path.read_text();assert s.count('t+20')==2 and s.count("D('.005')")==3 and s.count("D('.05')")==1
    # One invariant formula: total .05 * 20/H, per name total/N.
    s=s.replace('t+20',f't+{h}').replace("D('.005')",f"(D('.05')*D(20)/D({h})/D({n}))").replace("navnow*D('.05')*day_scale",f"navnow*(D('.05')*D(20)/D({h}))*day_scale").replace('slots=10 if stagger',f'slots={n} if stagger')
    s=s.replace('for r in candidates.itertuples():','for candidate_rank,r in enumerate(candidates.itertuples(),1):')
    original=next(x for x in s.splitlines() if 'planning_audit.append(' in x)
    replacement="     audit=dict(t=t,j=j,candidate_rank=candidate_rank,nav=str(navnow),available=str(available),budget_after_cap=str(budget),existing_q=existing,cap=str(cap),single_name_room=str(max(D(0),navnow*D('.1')-dec(existing)*cap)),per_name_budget=str(navnow*(D('.05')*D(20)/D("+str(h)+")/D("+str(n)+"))*day_scale),live_lots=sum(p['j']==j for p in positions.values()));qty=size(budget,cap,day,symbols[j]);audit.update(quantity=qty,status='PLANNED' if qty else 'ZERO_SIZE');planning_audit.append(audit)"
    s=s.replace(original,replacement);return s

def run(year,scale=None):
    assert 2020<=year<=2023
    assert load(W/'PRIMARY_STAGE_VERDICT.json')['primary_stage_complete']
    dest=OUT/('development_control' if scale else 'development')/str(year);dest.mkdir(parents=True,exist_ok=True);lock=open(dest/'lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if scale:
        original=OUT/'development'/str(year)
        for k in ['H20_IDENTITY_PARITY.json','H10_CANONICAL_STARTS.json']:
            assert (original/k).exists();(dest/k).write_bytes((original/k).read_bytes())
    meta=load(PANEL/'axes.json');dates=[d for d in meta['dates'] if d<'2024'];symbols=meta['symbols'];ts=[t for t,d in enumerate(dates) if d.startswith(str(year))];start,end=ts[0],ts[-1]
    cfg=load(DOC/'GENERAL_ENTITLEMENT_INFRASTRUCTURE.json');boundary.REGISTRY=cfg['events'];market={k:get(k)[:len(dates)] for k in ['up_limit_price','limit_pct']}
    assert sha(B7/'REGISTERED_ACTIONS_THROUGH2023.parquet')==load(W7/'INPUT_BINDINGS.json')['actions_sha256']
    actions=pd.read_parquet(B7/'REGISTERED_ACTIONS_THROUGH2023.parquet')
    assert sha(B7/'SIGNALS.parquet')==load(W7/'INPUT_BINDINGS.json')['signals_sha256']
    warm=start-60;raw=pd.read_parquet(B7/'SIGNALS.parquet');raw=raw[raw.t.between(warm,end)]
    signals={'CENTERED_TOP10_H10':raw}
    for arm,b,w in [('VOTE3_TOP2_H10',B3,W3),('VOTE7_TOP2_H10',B7,W7)]:
        assert sha(b/'VOTE_SIGNALS.parquet')==load(w/'VOTE_INPUT_MANIFEST.json')['signals_sha256']
        f=pd.read_parquet(b/'VOTE_SIGNALS.parquet');signals[arm]=f[f.t.between(start,end)]
    if scale:signals={'FIXED_CENTERED_TOP10_H10':raw}
    e.OUT=dest/'ledgers';e.OUT.mkdir(exist_ok=True);scope=dict(e.__dict__,normalize_t=None,scale_for=lambda t:D(scale) if scale else D(1),planning_audit=[])
    # Five-session H20 baseline identity validates the adapter before changing H.
    parityfile=dest/'H20_IDENTITY_PARITY.json'
    if not parityfile.exists():
        exec(source(year,20,10),scope);checks=[]
        for c in load(B7/str(year)/'CANONICAL_MANIFEST.json'):
            assert sha(Path(c['path']))==c['hash'];name='H20_PARITY_'+c['tag']
            q=scope['run'](name,raw[raw.t>=start],market,actions,dates,symbols,forecast_through=start+4,stagger=True,resume_path=c['path'],snapshot_path=dest/(name+'.pkl'),entitlement_branch=c['choices']);assert q['block'] is None,q
            old=BROOT/'linear_positive_gate_transfer_2020_2023_v1'/str(year)/'ledgers'
            for k in ['nav','orders','cashflows','inventory','inventory_events','lot_inventory','lot_fills','lot_actions']:
                x=pd.read_parquet(e.OUT/f'{name}_funded_prefix_{k}.parquet');z=pd.read_parquet(old/f'Y{year}_RAW_{c["tag"]}_funded_prefix_{k}.parquet')
                if 't' in x:x=x[x.t.between(start,start+4)].reset_index(drop=True)
                else:assert x.empty
                if 't' in z:z=z[z.t.between(start,start+4)].reset_index(drop=True)
                else:assert z.empty
                if not(x.empty and z.empty):
                    # Later blocked orders make the archived full-year quantity
                    # nullable float. Compare exact prefix values, not inferred
                    # storage dtype; no rounding or value tolerance is used.
                    pd.testing.assert_frame_equal(x,z,check_exact=True,check_dtype=False)
                checks.append(dict(table=k,branch=c['tag'],exact=True))
        a.write(parityfile,dict(status='PASS',checks=checks))
    exec(source(year,10,10),scope)
    canonfile=dest/'H10_CANONICAL_STARTS.json'
    if not canonfile.exists():
        # Horizon-specific legal common warmup; no conversion of existing H20
        # lots to H10 and no retrospective editing of their planned orders.
        cash=D(1000000)
        for attempt in range(12):
            init=dest/f'INITIAL_{attempt}.pkl';flow=[dict(t=warm-1,date=dates[warm-1],kind='WARMUP_INITIAL_CAPITAL',cash_delta=str(cash-D(1000000)),j=-1,event_id='',cash_after=str(cash))]
            with init.open('wb') as f:pickle.dump(dict(t=warm,dates=dates,symbols=symbols,state=(cash,cash,{},[],[],flow,[],[],[],[],[],[],[],[])),f)
            queue=[({},'ROOT')];canon=[];retry=False;scope['normalize_t']=start-1
            while queue:
                choices,tag=queue.pop(0);name=f'H10_WARM_{attempt}_{tag}';snap=dest/(name+'.pkl')
                q=scope['run'](name,raw,market,actions,dates,symbols,forecast_through=end,stagger=True,resume_path=init,save_before_t=start,snapshot_path=snap,entitlement_branch=choices)
                if q['status']=='ENTITLEMENT_BRANCH_REQUIRED':
                    assert len(queue)+len(canon)+2<=cfg['max_leaves'];queue.extend([({**choices,q['block']['event_id']:v},tag+'_'+v) for v in ['LOW','HIGH']]);continue
                if q['block']:
                    if 'NORMALIZATION_NEGATIVE_CASH' in str(q['block']):retry=True;break
                    raise RuntimeError(q['block'])
                with snap.open('rb') as f:s=pickle.load(f)
                n=s['state'][4][-1];assert s['t']==start and D(n['nav'])==D(1000000) and D(n['cash'])>=0
                age=max([start-p['entry_t'] for p in s['state'][2].values()] or [0]);assert age<40,'WARMUP_BOUNDARY_SURVIVOR_REQUIRES_EXTENSION'
                assert all(p['scheduled_expiry']==p['entry_t']+10 for p in s['state'][2].values())
                canon.append(dict(path=str(snap),hash=sha(snap),choices=choices,tag=tag,START_NAV=n['nav'],START_CASH=n['cash'],START_STOCK_VALUE=n['market_value'],warm_t=warm,warm_signal_first_t=int(raw.t.min()),max_lot_age=age,initial_cash=str(cash),live_lots=len(s['state'][2]),first_day_orders_preserved=True))
            if retry:cash=(cash*D('.8')).quantize(D('.01'));continue
            a.write(canonfile,canon);break
        else:raise RuntimeError('COMMON_H10_WARMUP_NORMALIZATION_EXHAUSTED')
    canon=load(canonfile);scope['normalize_t']=None;results=[]
    for arm,sig in signals.items():
        topn=10 if arm in ['CENTERED_TOP10_H10','FIXED_CENTERED_TOP10_H10'] else 2;src=source(year,10,topn);exec(src,scope);srcpath=dest/(arm+'_RUN_SOURCE.py');srcpath.write_text(src)
        sig=sig[sig.t.between(start,end)]
        for c in canon:
            assert sha(Path(c['path']))==c['hash'];queue=[(c['choices'],c['tag'])];leaves=0
            while queue:
                ch,tag=queue.pop(0);name=f'Y{year}_{arm}_{tag}';done=dest/(name+'_RESULT.json')
                identity=dict(canonical=c['hash'],source=sha(srcpath),signal_hash=sha(B7/'SIGNALS.parquet' if topn==10 else (B3 if arm=='VOTE3_TOP2_H10' else B7)/'VOTE_SIGNALS.parquet'),choices=ch)
                if scale:identity['fixed_exposure_control_scale']=scale
                if done.exists():
                    old=load(done);assert old['identity']==identity;results.append(old);continue
                scope['planning_audit']=[]
                q=scope['run'](name,sig,market,actions,dates,symbols,forecast_through=end,stagger=True,resume_path=c['path'],snapshot_path=dest/(name+'.pkl'),entitlement_branch=ch);a.write(dest/(name+'_ENGINE.json'),q)
                if q['status']=='ENTITLEMENT_BRANCH_REQUIRED':
                    assert len(queue)+leaves+2<=cfg['max_leaves'];queue.extend([({**ch,q['block']['event_id']:v},tag+'_'+v) for v in ['LOW','HIGH']]);continue
                assert q['block'] is None,q
                pd.DataFrame(scope['planning_audit']).to_parquet(dest/(name+'_PLANNING.parquet'),index=False)
                read=lambda k:pd.read_parquet(e.OUT/f'{name}_funded_prefix_{k}.parquet')
                g=reconcile(read,ts);fills=read('lot_fills');fills=fills[fills.t.isin(ts)];orders=read('orders');bu=orders[(orders.side=='BUY')&orders.t.isin(ts)];ff=fills[fills.side=='BUY'];v=g.nav.astype(float);ret=float(v.iloc[-1]/1e6-1);dd=-float(np.min(v/np.maximum.accumulate(np.r_[1e6,v])[1:]-1));expo=g.market_value.astype(float)/v
                requested=float(bu.reserved.astype(float).sum());funded=float(-ff.cash_delta.astype(float).sum())
                r=dict(identity=identity,year=year,arm=arm,branch=tag,MODEL_LINEAGE='CENTERED_RELATIVE_BRANCH',MODEL_IDENTITY='FROZEN_CENTERED_32K',SEED_SET='17,29,43,47,59,71,83' if arm=='VOTE7_TOP2_H10' else '17,29,43',SIGNAL_IDENTITY='FIXED_VOTE_TOP10_UNION_MEAN_PRED_TIEBREAK' if topn==2 else 'FIXED_PERCENTILE_CONSENSUS',HOLDING_HORIZON=10,TOPN=topn,annual_return=ret,MaxDD=dd,Calmar=ret/dd if dd else None,average_exposure=float(expo.mean()),peak_exposure=float(expo.max()),average_cash=float((g.cash.astype(float)/v).mean()),turnover=float((fills.quantity*fills.price.astype(float)).sum()/v.mean()),fees=float(fills.fees.astype(float).sum()),requested_new_capital=requested,filled_new_capital=funded,buy_fills=len(ff),zero_new_cohort_days=len(ts)-bu.decision_t.nunique(),filled_requested_ratio=funded/requested if requested else None,account_reconciliation='EXACT_DECIMAL',canonical_start_NAV='1000000',year_end_forced_liquidation=False,ledger=str(e.OUT),policy=name)
                a.write(done,r);results.append(r);leaves+=1;print('ACCOUNT_COMPLETE',year,arm,tag,ret,dd,flush=True)
    pd.DataFrame(results).to_csv(dest/'RESULTS.csv',index=False)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--year',type=int,required=True);p.add_argument('--scale');args=p.parse_args();run(args.year,args.scale)
