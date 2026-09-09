"""One-factor MAX_FILL security-cap diagnostic; unchanged frozen signal machinery."""
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import json
import time
import pandas as pd
from research.portfolio_closure_v1 import repair
from research.unified_opportunity_risk_v1 import engine,run as base
from research.unified_opportunity_risk_v1.exposure_scale import run as previous
from research.shared_capital_v1.causal_adapters import corrected_function
from research.capital_scaling_v1.run import save_account

HERE=Path(__file__).resolve().parent
OUT=HERE/'output'
CAPS=[.1,.15,.2,.3]

class CapPool(previous.ScalePool):
    # Only the read-only attribution simulator hardcoded 10%; the actual
    # allocator already reads config.security_cap. Keep the two consistent.
    simulate=corrected_function(previous.ScalePool.simulate,[('.1*safe_nav',"self.config['security_cap']*safe_nav")])


def directory(cap):return previous.OUT/'accounts/MAX_FILL' if cap==.1 else OUT/'accounts'/f'Y{round(cap*100)}'


def identity():
    files=[Path(__file__),HERE/'contract.json',Path(previous.__file__),Path(engine.__file__),previous.CONTRACT,previous.PARENT_OUT/'calibration_frozen.json',previous.PARENT_OUT/'risk_references_frozen.json']
    return {str(p):repair.digest(p) for p in files}


def job(cap):
    dest=directory(cap);dest.mkdir(parents=True,exist_ok=True);receipt=dest/'receipt.json';binding=identity()
    if receipt.exists():
        old=json.loads(receipt.read_text());assert old['identity']==(previous.identity() if cap==.1 else binding)
        for name,digest in old['hashes'].items():assert repair.digest(dest/name)==digest
        print('VERIFIED',cap,flush=True);return
    config=dict(previous.BASE_CONFIG,exposure_scale='MAX_FILL',risk_profile=1.,security_cap=cap)
    data,liq,req=base.load('2026-09-04');start=time.monotonic();print('START',cap,flush=True)
    replay=corrected_function(engine.run,[],Pool=CapPool,PoolPlatform=previous.Platform)
    a,d,p,platform=replay(data,config,liq,req,'2026-09-04');save_account(dest,a,d,None)
    for name,rows in [('admission',p.admissions),('risk_history',p.risk_history),('cash_attribution',p.cash_attribution),('smv6_events',platform.events),('cash_distributions',a.cash_distributions)]:
        pd.DataFrame(rows).to_parquet(dest/f'{name}.parquet',index=False)
    repair.write_json(receipt,dict(status='PASS',security_cap=cap,config=config,identity=binding,seconds=time.monotonic()-start,
        hashes={p.name:repair.digest(p) for p in dest.glob('*.parquet')}|{'account.json':repair.digest(dest/'account.json')}))
    print('PASS',cap,round(time.monotonic()-start,1),flush=True)

if __name__=='__main__':
    job(.1)
    with ProcessPoolExecutor(max_workers=3) as pool:list(pool.map(job,CAPS[1:]))
