"""Resumable physical-account research; discovery output cannot see later rows."""
from concurrent.futures import ProcessPoolExecutor
from itertools import product
import argparse
import hashlib
import json
from pathlib import Path
import time
import duckdb
import numpy as np
import pandas as pd
from research.portfolio_closure_v1 import repair
from research.unified_opportunity_risk_v1.data import HERE,OUT,CONTRACT,csv
from research.unified_opportunity_risk_v1 import engine
from research.capital_scaling_v1.run import save_account


def configs():
    return [dict(case_id=f'{rank}_RP{int(rp*100)}_S{int(cap*100)}_F{int(fam)}',ranking=rank,risk_profile=rp,security_cap=cap,family_cap=fam,
                 architecture='P1_UNIFIED_RISK_ONLY' if rank=='R0' else 'P3_UNIFIED_RANKING_FAMILY_RISK' if fam else 'P2_UNIFIED_RANKING')
            for rank,rp,cap,fam in product(['R0','R1','R2'],[.75,1.,1.25,1.5],[.10,.15,.20],[False,True])]


def prepare():
    dest=OUT/'liquidity.parquet'
    if not dest.exists():
        with duckdb.connect() as con:
            con.execute('SET threads=2')
            frame=con.execute('''SELECT symbol,trade_date,amount,volume,close,
                CASE WHEN count(CASE WHEN amount>0 AND volume>0 AND abs(amount/(volume*close)-1)<0.5 THEN 1 END) OVER w=20
                THEN avg(amount) OVER w ELSE NULL END AS adv20
                FROM read_parquet(?) WINDOW w AS(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)''',[str(repair.CACHE/'daily_with_snapshot.parquet')]).fetchdf()
        frame.to_parquet(dest,index=False)
    return dest

_DATA=None;_LIQ=None;_REQ=None

def load(end):
    global _DATA,_LIQ,_REQ
    if _DATA is None:
        print('LOAD_WORKER',end,flush=True);_DATA=repair.load(end)
        liq=pd.read_parquet(OUT/'liquidity.parquet',columns=['symbol','trade_date','adv20'])
        symbols=set(_DATA['ATRDR'][0].symbol)|set(_DATA['MCB'][0].symbol)|set(_DATA['OGR'].symbol)
        liq=liq.loc[liq.trade_date.between('2018-01-01',end)&liq.symbol.isin(symbols)&liq.adv20.notna()]
        _LIQ={(r.symbol,r.trade_date):r.adv20 for r in liq.itertuples(index=False)}
        requests=pd.read_parquet(OUT/'native_replay/OGR/precapital.parquet')
        _REQ={(r.strategy,r.event_id):r.requested_increase_notional for r in requests.itertuples(index=False)}
    return _DATA,_LIQ,_REQ


def case(config,end='2021-12-31',group='discovery',force=False):
    dest=OUT/'accounts'/group/config['case_id'];dest.mkdir(parents=True,exist_ok=True)
    identity={p.name:repair.digest(p) for p in [CONTRACT,OUT/'calibration_frozen.json',OUT/'risk_references_frozen.json',HERE/'engine.py']}
    receipt=dest/'receipt.json'
    if receipt.exists() and not force:
        r=json.loads(receipt.read_text())
        if r['identity']!=identity:raise ValueError('cached configuration binding changed')
        print('VERIFIED',config['case_id'],flush=True);return r
    data,liq,req=load(end);start=time.monotonic();print('RUN',config['case_id'],end,flush=True)
    account,nav,pool,platform=engine.run(data,config,liq,req,end)
    save_account(dest,account,nav,None)
    pd.DataFrame(account.cash_distributions).to_parquet(dest/'cash_distributions.parquet',index=False)
    pd.DataFrame(pool.admissions).to_parquet(dest/'admission.parquet',index=False)
    pd.DataFrame(pool.risk_history).to_parquet(dest/'risk_history.parquet',index=False)
    pd.DataFrame(platform.events).to_parquet(dest/'smv6_events.parquet',index=False)
    row=dict(status='PASS',config=config,end=end,days=len(nav),initial_nav=account.initial_cash,seconds=time.monotonic()-start,identity=identity,
             hashes={p.name:repair.digest(p) for p in sorted(dest.glob('*.parquet'))})
    repair.write_json(receipt,row);print('PASS',config['case_id'],row['seconds'],flush=True);return row


def metrics(dest,start,end,initial=None):
    d=pd.read_parquet(dest/'daily.parquet');d.trade_date=pd.to_datetime(d.trade_date)
    before=d.loc[d.trade_date.lt(start)];g=d.loc[d.trade_date.between(start,end)].copy()
    account=json.loads((dest/'account.json').read_text());seed=float(before.nav.iloc[-1]) if len(before) else float(account['initial_cash'])
    values=np.r_[seed,g.nav.to_numpy()];r=pd.Series(values).pct_change().dropna();total=values[-1]/seed-1
    years=(pd.Timestamp(end)+pd.Timedelta(days=1)-pd.Timestamp(start)).days/365.25
    dd=1-values/np.maximum.accumulate(values);tail=r.nsmallest(max(1,int(np.ceil(len(r)*.05))))
    fees=float(g.fees.iloc[-1]-(before.fees.iloc[-1] if len(before) else 0.))
    roots=json.loads(g.root_pnl_json.iloc[-1]);prior=json.loads(before.root_pnl_json.iloc[-1]) if len(before) else {}
    pnl=pd.Series({k:v-prior.get(k,0.) for k,v in roots.items()});positive=pnl.clip(lower=0)
    f=pd.read_parquet(dest/'fills.parquet');f['when']=pd.to_datetime(f.exit).fillna(pd.to_datetime(f.entry))
    f=f.loc[f.when.between(start,pd.Timestamp(end)+pd.Timedelta(days=1))];symbol_by_root={r.event_id:r.symbol for r in f.itertuples()}
    symbol=pd.Series({k:0. for k in set(symbol_by_root.values())})
    for root,p in positive.items():
        s=symbol_by_root.get(root,root.split('|')[-1]);symbol.loc[s]=symbol.get(s,0.)+p
    turnover=sum(float(x.funded_notional) if x.side=='BUY' else float(x.filled_quantity*x.exit_price) for x in f.itertuples())/g.nav.mean()/years
    gross=g.gross_exposure/g.nav
    if 'max_family_exposure' not in g and (OUT/'native_family_exposure.csv.gz').exists():
        family=pd.read_csv(OUT/'native_family_exposure.csv.gz',parse_dates=['trade_date'])
        g=g.merge(family[['trade_date','max_family_exposure']],on='trade_date',how='left',validate='one_to_one')
        assert g.loc[g.max_family_exposure.isna(),'gross_exposure'].eq(0).all()
        g['max_family_exposure']=g.max_family_exposure.fillna(0.)
    monthly=pd.Series(values[1:],index=g.trade_date).resample('ME').last();monthret=monthly.pct_change();monthret.iloc[0]=monthly.iloc[0]/seed-1
    return dict(start=start,end=end,return_=total,CAGR=(1+total)**(1/years)-1,MaxDD=float(dd.max()),CVaR5=float(-tail.mean()),
        Sharpe=float(r.mean()/r.std()*np.sqrt(252)) if r.std()>0 else 0.,average_gross=gross.mean(),P95_gross=gross.quantile(.95),cash_ratio=(g.cash/g.nav).mean(),
        fees=fees,turnover=turnover,worst_month=monthret.min(),max_security=(g.max_security_exposure/g.nav).max(),
        max_family=(g.max_family_exposure/g.nav).max() if 'max_family_exposure' in g else np.nan,
        top5_day_concentration=r.clip(lower=0).nlargest(5).sum()/r.clip(lower=0).sum() if r.clip(lower=0).sum()>0 else 0.,
        top5_event_concentration=positive.nlargest(5).sum()/positive.sum() if positive.sum()>0 else 0.,
        top5_symbol_concentration=symbol.nlargest(5).sum()/symbol.sum() if symbol.sum()>0 else 0.,net_pnl=values[-1]-seed)


def discover():
    rows=[]
    for c in configs():
        dest=OUT/'accounts/discovery'/c['case_id']
        if not (dest/'receipt.json').exists():continue
        m=metrics(dest,'2018-01-01','2021-12-31');a=pd.read_parquet(dest/'admission.parquet');rh=pd.read_parquet(dest/'risk_history.parquet')
        rows.append(dict(c,**m,opportunity_count=len(a),funded_count=a.allocated.gt(0).sum(),rejected_quality=a.reason.eq('QUALITY_NONPOSITIVE').sum(),
            rejected_risk=a.reason.eq('RISK_OR_CASH_OR_LOT').sum(),liquidity_capped=(a.liquidity_cap<a.risk_desired).sum(),estimated_risk_utilization=(rh.tail_risk/rh.account_budget).mean()))
    frame=pd.DataFrame(rows);csv(frame,'unified_discovery_grid.csv')
    if len(frame)!=72:raise ValueError(f'incomplete actual grid {len(frame)}/72')
    scores=frame[['CAGR','MaxDD','CVaR5','Sharpe','top5_event_concentration']].to_numpy()*[1,-1,-1,1,-1]
    frame['pareto']=[not any(np.all(s>=v) and np.any(s>v) for s in scores) for v in scores]
    csv(frame,'unified_discovery_pareto.csv')
    frozen=[];used=set()
    for band in [.05,.08,.10,.15]:
        g=frame.loc[frame.MaxDD.le(band)].sort_values(['pareto','Sharpe','CAGR'],ascending=False)
        architectures=set();paths=set();n=0
        for r in g.to_dict('records'):
            signature=(r['ranking'],r['family_cap']);equity=pd.read_parquet(OUT/'accounts/discovery'/r['case_id']/'daily.parquet',columns=['cash','nav','gross_exposure'])
            curve=hashlib.sha256(np.round(equity.to_numpy(dtype=float),6).tobytes()).hexdigest()
            if signature in architectures or curve in paths:continue
            architectures.add(signature);paths.add(curve);r['DD_band']=band;frozen.append(r);n+=1
            if n==3:break
    candidates=pd.DataFrame(frozen);csv(candidates,'frozen_validation_candidates.csv')
    repair.write_json(OUT/'candidate_freeze_receipt.json',dict(contract_sha256=repair.digest(CONTRACT),candidates_sha256=repair.digest(OUT/'frozen_validation_candidates.csv'),
        grid_sha256=repair.digest(OUT/'unified_discovery_grid.csv'),frozen_before_validation=True,validation_cases=sorted(set(candidates.case_id)) if len(candidates) else []))
    return candidates

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--smoke',action='store_true');p.add_argument('--workers',type=int,default=2);p.add_argument('--discover',action='store_true');p.add_argument('--case');p.add_argument('--end',default='2021-12-31');p.add_argument('--group',default='discovery');args=p.parse_args()
    prepare()
    if args.smoke:case(configs()[0],end='2018-03-31',group='smoke',force=True)
    elif args.case:case(next(c for c in configs() if c['case_id']==args.case),end=args.end,group=args.group)
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:list(pool.map(case,configs()))
        discover()
