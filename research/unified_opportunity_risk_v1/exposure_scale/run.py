"""Frozen Candidate-B exposure response curve, using the same Native account replay."""
from concurrent.futures import ProcessPoolExecutor
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
import argparse
import json
import math
import time
import numpy as np
import pandas as pd
from research.portfolio_closure_v1 import repair
from research.unified_opportunity_risk_v1 import engine,run as base
from research.unified_opportunity_risk_v1.data import OUT as PARENT_OUT,CONTRACT
from research.shared_capital_v1.causal_adapters import corrected_function
from research.capital_scaling_v1.run import save_account

HERE=Path(__file__).resolve().parent
OUT=HERE/'output'
SCALES=[1.,1.5,2.,3.,5.,8.,10.,'MAX_FILL']
REASONS=['NO_QUALIFYING_OPPORTUNITY','SINGLE_SECURITY_CAP','LIQUIDITY_CAP','GROSS_CAP','CASH_EXHAUSTED','SOFT_RISK_BUDGET','FAMILY_RISK_BUDGET']
BASE_CONFIG=next(c for c in base.configs() if c['case_id']=='R1_RP100_S10_F1')


def label(scale):return 'MAX_FILL' if scale=='MAX_FILL' else f'X{scale:g}'


class Platform(engine.PoolPlatform):
    def defer_buy(self,symbol,requested,price,target_weight,desired,volume_cap):
        # This is the SAME registered 50%-window/100-share execution limit.
        # Separate it from the Native target delta, which is a sizing request.
        event_id=f'SMV6|{self.current_date}|{symbol}|{len(self.intent_rows)}'
        self.physical.pool.etf_limits[event_id]=volume_cap*price
        return super().defer_buy(symbol,requested,price,target_weight,desired,volume_cap)


class ScalePool(engine.Pool):
    def __init__(self,config,liquidity,native_requests):
        super().__init__(config,liquidity,native_requests)
        self.scale=config['exposure_scale'];self.max_fill=self.scale=='MAX_FILL'
        self.etf_limits={};self.cash_attribution=[]

    def target(self,i,baseline_liquidity,desired,denom,native):
        baseline=min(desired,baseline_liquidity)
        if i.strategy=='SMV6':hard=self.etf_limits[i.event_id]
        else:hard=.01*denom if np.isfinite(denom) and denom>0 else native/(1+i.fee_rate)
        request=hard if self.max_fill else self.scale*baseline
        return baseline,min(request,hard),hard,request

    def simulate(self,eligible,safe_nav,*,liquidity=True,soft=True,family=True):
        """Read-only same-clock cash waterfall; no NAV or exits are synthesized."""
        a=self.account;cash=max(0.,a.cash)
        risk,sec,fam,mv,_=self.holdings(safe_nav);used=defaultdict(float)
        shared={s:(sum(r['liquidity_cap'] for i,q,r in eligible if i.symbol==s)
                   if all(r['liquidity_source']=='NATIVE_EXECUTABLE_FALLBACK' for i,q,r in eligible if i.symbol==s)
                   else min(r['liquidity_cap'] for i,q,r in eligible if i.symbol==s)) for s in {i.symbol for i,q,r in eligible}}
        rp=self.config['risk_profile']
        for rank in sorted({r['rank'] for i,q,r in eligible},reverse=True):
            group=[(i,q,r) for i,q,r in eligible if r['rank']==rank]
            targets=[r['scaled_request'] if soft else max(0.,a.cash) for i,q,r in group]
            constraints=[]
            for symbol in sorted({i.symbol for i,q,r in group}):
                flags=[float(i.symbol==symbol) for i,q,r in group]
                if liquidity:constraints.append((flags,shared[symbol]-used[symbol]))
                constraints.append((flags,.1*safe_nav-mv[symbol]))
                if soft:constraints.append(([f*r['tail']/safe_nav for f,(i,q,r) in zip(flags,group)],rp*self.refs['security']-sec[symbol]))
            if family:
                for family_name in sorted({q['family'] for i,q,r in group}):
                    constraints.append(([r['tail']/safe_nav if q['family']==family_name else 0. for i,q,r in group],rp*self.refs['family_risk']-fam[family_name]))
            if soft:constraints.append(([r['tail']/safe_nav for i,q,r in group],rp*self.refs['account']-risk))
            constraints.append(([1+i.fee_rate for i,q,r in group],cash))
            if liquidity:targets=[min(t,r['liquidity_cap']) for t,(i,q,r) in zip(targets,group)]
            amounts=engine.constrain_pro_rata(targets,constraints)
            for (i,q,r),amount in zip(group,amounts):
                qty=amount/i.price
                if i.lot_size:qty=math.floor(qty/i.lot_size)*i.lot_size
                value=qty*i.price;cash-=value*(1+i.fee_rate)
                used[i.symbol]+=value;mv[i.symbol]+=value
                delta=value/safe_nav*r['tail'];risk+=delta;sec[i.symbol]+=delta;fam[q['family']]+=delta
        return max(0.,a.cash)-cash

    def diagnose(self,eligible,state,safe_nav):
        cash=max(0.,self.account.cash);parts={k:0. for k in REASONS}
        if not eligible:
            parts['NO_QUALIFYING_OPPORTUNITY']=cash;levels=[0.,0.,0.,0.]
        else:
            security=self.simulate(eligible,safe_nav,liquidity=False,soft=False,family=False)
            hard=self.simulate(eligible,safe_nav,soft=False,family=False)
            soft=hard if self.max_fill else self.simulate(eligible,safe_nav,soft=True,family=False)
            full=hard if self.max_fill else self.simulate(eligible,safe_nav,soft=True,family=True)
            parts['SINGLE_SECURITY_CAP']=cash-security
            parts['LIQUIDITY_CAP']=security-hard
            parts['SOFT_RISK_BUDGET']=hard-soft
            parts['FAMILY_RISK_BUDGET']=soft-full
            levels=[security,hard,soft,full]
        self.pending=dict(timestamp=state['decision_at'],cash_before=cash,eligible_requests=len(eligible),
            security_only_deployable=levels[0],hard_only_deployable=levels[1],without_family_deployable=levels[2],all_constraints_deployable=levels[3],**parts)

    _allocate=corrected_function(engine.Pool.allocate,[
        ("desired=rp*self.refs['opportunity']*safe_nav/tail","desired=self.refs['opportunity']*safe_nav/tail"),
        ("target=min(desired,liq);rank=", "baseline_target,target,liq,scaled_request=self.target(i,liq,desired,denom,native);rank="),
        ("liquidity_denominator=denom,liquidity_source=liq_source,target=target", "baseline_target=baseline_target,scaled_request=scaled_request,liquidity_denominator=denom,liquidity_source=liq_source,target=target"),
        ('    security_liquidity={}','    self.diagnose(eligible,state,safe_nav)\n    security_liquidity={}'),
        ("constraints.append(([f*r['tail']/safe_nav for f,(_,_,r) in zip(flags,group)],rp*self.refs['security']-sec[symbol]))", "if not self.max_fill:constraints.append(([f*r['tail']/safe_nav for f,(_,_,r) in zip(flags,group)],rp*self.refs['security']-sec[symbol]))"),
        ("if self.config['family_cap']:","if not self.max_fill and self.config['family_cap']:"),
        ("constraints.append(([r['tail']/safe_nav for _,_,r in group],rp*self.refs['account']-risk))", "if not self.max_fill:constraints.append(([r['tail']/safe_nav for _,_,r in group],rp*self.refs['account']-risk))"),
        ("account_budget=rp*self.refs['account']", "account_budget=np.nan if self.max_fill else rp*self.refs['account']"),
    ])

    def allocate(self,intents,when):
        self._allocate(intents,when)
        row=self.pending;row['cash_after']=max(0.,self.account.cash)
        # Integer lots / Native legal rechecks can leave an execution remainder.
        residual=row['cash_after']-sum(row[k] for k in REASONS)
        row['native_execution_residual']=residual;row['LIQUIDITY_CAP']+=residual
        assert abs(sum(row[k] for k in REASONS)-row['cash_after'])<1e-6
        if self.max_fill:assert row['SOFT_RISK_BUDGET']==row['FAMILY_RISK_BUDGET']==0
        self.cash_attribution.append(row)


def identity():
    files=[Path(__file__),HERE/'contract.json',CONTRACT,Path(engine.__file__),PARENT_OUT/'calibration_frozen.json',PARENT_OUT/'risk_references_frozen.json']
    return {str(p):repair.digest(p) for p in files}


def job(scale):
    dest=OUT/'accounts'/label(scale);dest.mkdir(parents=True,exist_ok=True);receipt=dest/'receipt.json'
    binding=identity()
    if receipt.exists():
        saved=json.loads(receipt.read_text());assert saved['identity']==binding
        for name,digest in saved['hashes'].items():assert repair.digest(dest/name)==digest
        print('VERIFIED',label(scale),flush=True);return str(dest)
    config=dict(BASE_CONFIG,exposure_scale=scale,risk_profile=1. if scale=='MAX_FILL' else scale)
    data,liq,req=base.load('2026-09-04');start=time.monotonic();print('START',label(scale),flush=True)
    run=corrected_function(engine.run,[],Pool=ScalePool,PoolPlatform=Platform)
    # engine.run refers to PhysicalPlatform=PoolPlatform in its local binding.
    a,d,p,platform=run(data,config,liq,req,'2026-09-04')
    save_account(dest,a,d,None)
    for name,rows in [('admission',p.admissions),('risk_history',p.risk_history),('cash_attribution',p.cash_attribution),('smv6_events',platform.events),('cash_distributions',a.cash_distributions)]:
        pd.DataFrame(rows).to_parquet(dest/f'{name}.parquet',index=False)
    repair.write_json(receipt,dict(status='PASS',scale=scale,identity=binding,config=config,seconds=time.monotonic()-start,
        hashes={p.name:repair.digest(p) for p in sorted(dest.glob('*.parquet'))}|{'account.json':repair.digest(dest/'account.json')}))
    print('PASS',label(scale),round(time.monotonic()-start,1),flush=True);return str(dest)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--scale');parser.add_argument('--workers',type=int,default=3);args=parser.parse_args()
    if args.scale:job('MAX_FILL' if args.scale=='MAX_FILL' else float(args.scale))
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:list(pool.map(job,SCALES))
