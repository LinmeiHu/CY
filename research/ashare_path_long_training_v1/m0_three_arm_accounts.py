"""Original H20 engine, identical existing annual RMB1m starting states."""
import argparse
import fcntl
import json
import pickle
from decimal import Decimal as D
from pathlib import Path
import numpy as np
import pandas as pd
import entitlement_boundary_engine as e
import entitlement_boundary as boundary
from alpha_train_timing import validate_asset
from m0_three_arm_matched import DOC, OUT, ROOT, HERE, ARMS, sha, write, stamp

BASE=ROOT/'account_diversification_v1/fixed_1m_annual_account_reaudit_v1'
CACHE=ROOT/'account_diversification_v1/alpha_held_risk_v2'


def context(year):
    assert 2010<=year<=2019
    meta=json.loads((ROOT/'panel/axes.json').read_text());dates=[d for d in meta['dates'] if d<'2020'];symbols=meta['symbols']
    ts=[i for i,d in enumerate(dates) if d.startswith(str(year))]
    actions=validate_asset(CACHE/'REGISTERED_ACTIONS_PRE2020_TIMING_V1.parquet')
    cfg=json.loads((DOC.parent/'GENERAL_ENTITLEMENT_INFRASTRUCTURE.json').read_text());boundary.REGISTRY=cfg['events']
    expected=json.loads((DOC.parent/'positive_gate_calibration_v2_autonomous/ACCOUNT_EXECUTION_SPEC.json').read_text())['engine_sha256']
    assert sha(Path(e.__file__))==expected
    market={k:e.get(k)[:len(dates)] for k in ['up_limit_price','limit_pct']}
    canonical=json.loads((BASE/str(year)/'CANONICAL_MANIFEST.json').read_text())
    for c in canonical:
        assert sha(Path(c['path']))==c['hash'] and D(c['START_NAV'])==D(1000000)
        with open(c['path'],'rb') as f:s=pickle.load(f)
        assert s['dates']==dates and s['symbols']==symbols and s['t']==ts[0]
        assert D(s['state'][4][-1]['nav'])==D(1000000) and D(s['state'][0])>=0
    return dates,symbols,ts,actions,cfg,market,canonical


def parity():
    dates,symbols,ts,actions,cfg,market,canonical=context(2010)
    dest=OUT/'ACCOUNT_PARITY';dest.mkdir(exist_ok=True);e.OUT=dest
    sig=pd.read_parquet(CACHE/'SIGNALS.parquet');sig=sig[(sig.t>=ts[0])&(sig.t<=ts[4])]
    checks=[]
    for c in canonical:
        name='PARITY_'+c['tag'];r=e.run(name,sig,market,actions,dates,symbols,forecast_through=ts[4],stagger=True,
            resume_path=c['path'],snapshot_path=dest/(name+'.pkl'),entitlement_branch=c['choices'])
        assert r['block'] is None,r
        original=BASE/'2010/ledgers'
        for kind in ['nav','orders','cashflows','inventory','lot_inventory','lot_fills']:
            a=pd.read_parquet(dest/f'{name}_funded_prefix_{kind}.parquet')
            b=pd.read_parquet(original/f'Y2010_RAW_{c["tag"]}_funded_prefix_{kind}.parquet')
            a=a[(a.t>=ts[0])&(a.t<=ts[4])].reset_index(drop=True)
            b=b[(b.t>=ts[0])&(b.t<=ts[4])].reset_index(drop=True)
            pd.testing.assert_frame_equal(a,b,check_exact=True)
            checks.append(dict(branch=c['tag'],kind=kind,rows=len(a),exact=True))
    write(DOC/'ACCOUNT_ADAPTER_PARITY.json',dict(at=stamp(),scope='First five sessions2010 identical canonical state and originalRAW signals; diagnostic replay only',checks=checks,
        engine_sha256=sha(Path(e.__file__)),adapter_sha256=sha(Path(__file__)),passed=True,no_candidate_account=True))
    print('ACCOUNT_PARITY_PASS',flush=True)


def run_year(year):
    proof=json.loads((DOC/'ACCOUNT_ADAPTER_PARITY.json').read_text());assert proof['passed'] and proof['adapter_sha256']==sha(Path(__file__))
    done=json.loads((OUT/'DAILY_INFERENCE_COMPLETE.json').read_text())
    dest=OUT/'annual_accounts'/str(year);dest.mkdir(parents=True,exist_ok=True)
    with open(dest/'lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        dates,symbols,ts,actions,cfg,market,canonical=context(year)
        frame=pd.read_parquet(OUT/'daily'/f'{year}.parquet');assert frame.t.min()>=ts[0] and frame.t.max()<=ts[-1]
        e.OUT=dest/'ledgers';e.OUT.mkdir(exist_ok=True)
        rows=[]
        for arm in ARMS:
            sig=frame.loc[frame[arm+'_positive_gate'],['t','j',arm+'_score',arm+'_pred20','logamount20']].rename(columns={arm+'_score':'score',arm+'_pred20':'pred20'})
            for c in canonical:
                pending=[(c['choices'],c['tag'])];leaves=0
                while pending:
                    choices,tag=pending.pop(0);name=f'Y{year}_{arm}_{tag}';file=dest/(name+'.json')
                    identity=dict(inference=done['identity'],signals_sha256=sha(OUT/'daily'/f'{year}.parquet'),canonical=c['hash'],choices=choices,engine=proof['engine_sha256'],adapter=proof['adapter_sha256'])
                    if file.exists():
                        old=json.loads(file.read_text());assert old['identity']==identity
                        if old.get('account_reconciliation')=='EXACT_DECIMAL':rows.append(old);continue
                    r=e.run(name,sig,market,actions,dates,symbols,forecast_through=ts[-1],stagger=True,resume_path=c['path'],snapshot_path=dest/(name+'.pkl'),entitlement_branch=choices)
                    if r['status']=='ENTITLEMENT_BRANCH_REQUIRED':
                        assert len(pending)+leaves+2<=cfg['max_leaves']
                        pending.extend([({**choices,r['block']['event_id']:v},tag+'_'+v) for v in ['LOW','HIGH']]);continue
                    assert r['block'] is None,r
                    read=lambda k:pd.read_parquet(e.OUT/f'{name}_funded_prefix_{k}.parquet')
                    nav=read('nav');g=nav[nav.t.isin(ts)];assert len(g)==len(ts)
                    cash=D(1000000)
                    for f in read('cashflows').itertuples():cash+=D(f.cash_delta);assert cash==D(f.cash_after)
                    physical=read('inventory').groupby('t').value.agg(lambda x:sum(map(D,x),D(0)))
                    virtual=read('lot_inventory').groupby('t').value.agg(lambda x:sum(map(D,x),D(0)))
                    for n in g.itertuples():assert D(n.cash)+D(n.market_value)+D(n.receivable)==D(n.nav) and physical.get(n.t,D(0))==virtual.get(n.t,D(0))==D(n.market_value)
                    fills=read('lot_fills');fills=fills[fills.t.isin(ts)];v=g.nav.astype(float);ret=float(v.iloc[-1]/1e6-1);dd=-float(np.min(v/np.maximum.accumulate(np.r_[1e6,v])[1:]-1))
                    result=dict(identity=identity,year=year,arm=arm,branch=tag,annual_return=ret,MaxDD=dd,Calmar=ret/dd if dd else None,
                        average_exposure=float((g.market_value.astype(float)/v).mean()),average_cash=float((g.cash.astype(float)/v).mean()),
                        turnover=float((fills.quantity*fills.price.astype(float)).sum()/v.mean()),fees=float(fills.fees.astype(float).sum()),
                        account_reconciliation='EXACT_DECIMAL',canonical_start_nav='1000000',year_end_liquidation=False,model_scope='RAW_O2_THREE_ARM_NO_CENTERED_READOUT',production_alpha_changed=False)
                    write(file,result);rows.append(result);leaves+=1;print('ACCOUNT',year,arm,tag,ret,dd,flush=True)
        pd.DataFrame(rows).to_csv(dest/'YEARLY_RESULTS.csv',index=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--parity',action='store_true');parser.add_argument('--year',type=int);a=parser.parse_args()
    if a.parity:parity()
    else:run_year(a.year)
