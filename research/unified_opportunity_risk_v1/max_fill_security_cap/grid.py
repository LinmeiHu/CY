"""Complete the user-requested 8 x 4 grid with 21 additional physical accounts."""
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import argparse
import json
import time
import pandas as pd
from research.portfolio_closure_v1 import repair
from research.unified_opportunity_risk_v1 import engine,run as base
from research.unified_opportunity_risk_v1.exposure_scale import run as previous
from research.unified_opportunity_risk_v1.max_fill_security_cap import run as max_runs
from research.shared_capital_v1.causal_adapters import corrected_function
from research.capital_scaling_v1.run import save_account

HERE,OUT=max_runs.HERE,max_runs.OUT
XS=previous.SCALES
YS=max_runs.CAPS


def directory(x,y):
    if y==.1:return previous.OUT/'accounts'/previous.label(x)
    if x=='MAX_FILL':return max_runs.directory(y)
    return OUT/'accounts'/f'Y{round(y*100)}_{previous.label(x)}'


def identity():
    files=[Path(__file__),HERE/'grid_contract.json',Path(max_runs.__file__),Path(previous.__file__),Path(engine.__file__),previous.CONTRACT,
           previous.PARENT_OUT/'calibration_frozen.json',previous.PARENT_OUT/'risk_references_frozen.json']
    return {str(p):repair.digest(p) for p in files}


def verify(x,y):
    dest=directory(x,y);saved=json.loads((dest/'receipt.json').read_text())
    expected=previous.identity() if y==.1 else max_runs.identity() if x=='MAX_FILL' else identity()
    assert saved['identity']==expected,(x,y,'source binding drift')
    for name,digest in saved['hashes'].items():assert repair.digest(dest/name)==digest
    return saved


def job(pair):
    x,y=pair;dest=directory(x,y);dest.mkdir(parents=True,exist_ok=True);receipt=dest/'receipt.json'
    if receipt.exists():verify(x,y);print('VERIFIED',x,y,flush=True);return
    assert y!=.1 and x!='MAX_FILL','expected existing baseline cell absent'
    binding=identity();config=dict(previous.BASE_CONFIG,exposure_scale=x,risk_profile=x,security_cap=y)
    data,liq,req=base.load('2026-09-04');start=time.monotonic();print('START',x,y,flush=True)
    replay=corrected_function(engine.run,[],Pool=max_runs.CapPool,PoolPlatform=previous.Platform)
    a,d,p,platform=replay(data,config,liq,req,'2026-09-04');save_account(dest,a,d,None)
    for name,rows in [('admission',p.admissions),('risk_history',p.risk_history),('cash_attribution',p.cash_attribution),('smv6_events',platform.events),('cash_distributions',a.cash_distributions)]:
        pd.DataFrame(rows).to_parquet(dest/f'{name}.parquet',index=False)
    repair.write_json(receipt,dict(status='PASS',X=x,Y=y,config=config,identity=binding,seconds=time.monotonic()-start,
        hashes={p.name:repair.digest(p) for p in dest.glob('*.parquet')}|{'account.json':repair.digest(dest/'account.json')}))
    print('PASS',x,y,round(time.monotonic()-start,1),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=3);args=parser.parse_args()
    for x in XS:verify(x,.1)
    for y in YS[1:]:verify('MAX_FILL',y)
    jobs=[(x,y) for x in reversed(XS[:-1]) for y in YS[1:]]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:list(pool.map(job,jobs))
