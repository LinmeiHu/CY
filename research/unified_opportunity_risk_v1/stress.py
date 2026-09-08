"""Finalist-only actual ledger reruns with frozen signals/ranks and higher costs."""
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
import json
from types import MethodType
import pandas as pd
from research.portfolio_closure_v1 import repair
from research.unified_opportunity_risk_v1.data import OUT,HERE,CONTRACT,csv
from research.unified_opportunity_risk_v1.run import load,configs,metrics
from research.unified_opportunity_risk_v1 import engine
from research.capital_scaling_v1.run import save_account

BASE_INIT=engine.initialize;BASE_POOL=engine.Pool;BASE_PLATFORM=engine.PoolPlatform

def job(args):
    config,multiplier,end=args;dest=OUT/'accounts/cost'/f"{config['case_id']}_C{int(multiplier*100)}";dest.mkdir(parents=True,exist_ok=True)
    identity={p.name:repair.digest(p) for p in [CONTRACT,HERE/'engine.py',HERE/'stress.py',OUT/'calibration_frozen.json',OUT/'risk_references_frozen.json']}
    receipt=dest/'receipt.json'
    if receipt.exists():
        old=json.loads(receipt.read_text());assert old['identity']==identity;return str(dest)
    def init(gap,states):
        a=BASE_INIT(gap,states);close=a.close
        def cost_close(event_id,price,when,fee_rate,**kwargs):return close(event_id,price,when,fee_rate*multiplier,**kwargs)
        a.close=cost_close;return a
    class CostPool(BASE_POOL):
        def allocate(self,intents,when):return super().allocate([replace(i,fee_rate=i.fee_rate*multiplier) for i in intents],when)
    class CostPlatform(BASE_PLATFORM):
        def _fill_price(self,raw_price,side):return raw_price*(1+side*self.slippage_total*multiplier/2)
    engine.initialize=init;engine.Pool=CostPool;engine.PoolPlatform=CostPlatform
    data,liq,req=load(end);print('COST_RUN',config['case_id'],multiplier,end,flush=True)
    try:a,d,p,platform=engine.run(data,config,liq,req,end)
    finally:engine.initialize=BASE_INIT;engine.Pool=BASE_POOL;engine.PoolPlatform=BASE_PLATFORM
    save_account(dest,a,d,None);pd.DataFrame(a.cash_distributions).to_parquet(dest/'cash_distributions.parquet',index=False);pd.DataFrame(p.admissions).to_parquet(dest/'admission.parquet',index=False)
    repair.write_json(receipt,dict(config=config,multiplier=multiplier,end=end,identity=identity,status='PASS',hashes={p.name:repair.digest(p) for p in dest.glob('*.parquet')}))
    return str(dest)

def run(workers=3):
    selected=json.loads((OUT/'candidate_freeze_receipt.json').read_text())['validation_cases'];survivors=json.loads((OUT/'validation_survivors.json').read_text())['survivors'];cfg={c['case_id']:c for c in configs()}
    jobs=[(cfg[key],m,'2026-09-04' if key in survivors else '2023-12-31') for key in selected for m in [1.5,2.]]
    with ProcessPoolExecutor(max_workers=workers) as pool:list(pool.map(job,jobs))
    rows=[]
    for key in selected:
        end='2026-09-04' if key in survivors else '2023-12-31'
        for factor in [1.,1.5,2.]:
            dest=OUT/'accounts'/('diagnostic' if key in survivors else 'validation')/key if factor==1 else OUT/'accounts/cost'/f'{key}_C{int(factor*100)}'
            rows.append(dict(case_id=key,cost_multiplier=factor,**metrics(dest,'2018-01-01',end),method='ACTUAL_PHYSICAL_ACCOUNT_RERUN_FROZEN_RANKS_NATIVE_EXITS'))
    csv(pd.DataFrame(rows),'finalist_cost_stress.csv')

if __name__=='__main__':run()
