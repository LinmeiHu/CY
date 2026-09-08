"""Frozen full-matrix analysis and independent cash/quantity audit; no fitted trading rules."""
import json,math,hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from .common import HERE,OUT,CACHE,sha,dump,parquet,scenarios
from .run import publish_summary

STATS=OUT/'statistics'

def pair_baseline(s):
    group=s['group'].split('_')[0];r=s['signal'];mode=s['capital'];e=s['exit']
    if group=='A':
        base={'D01':'D00','D02':'D01','D03':'D00','D04':'D03','D05':'D03','D06':'D00','D07':'D06','D08':'D06','D09':'D02','H01':'D02','H02':'D05'}.get(r)
        return f'A_{base}_{mode}_{e}' if base else None
    if group in ['B','C']:return f'A_{r}_{mode}_E10'
    if group=='D':return f'D_{r}_{mode}_R_ONCE' if s['overlay']=='R_STAGE' else f'A_{r}_{mode}_EST'
    if group=='E':return f'E_P0_POOL_{mode}_{e}' if r!='P0_POOL' else f'A_D02_{mode}_{e}'
    if group=='Q' and s['arm']=='ENHANCED':return f"{s['overlay']}_BASE_{mode}_{e}"


def account_audit(s,d,nav,tr,orders,audit,op,hold):
    buy=orders[orders.status=='FILLED'].copy() if len(orders) else pd.DataFrame();flow=pd.Series(0.,index=nav.date)
    if len(buy):
        for t,g in buy.groupby('t'):flow.iloc[int(t)-int(nav.t.iloc[0])]-=g.debit.sum()
    if len(audit) and 'cash_delta' in audit:
        for day,g in audit[audit.cash_delta.notna()].groupby('day'):flow.loc[day]+=g.cash_delta.sum()
    casherr=float(np.max(abs(1e6+flow.cumsum().to_numpy()-nav.book_cash.to_numpy())))
    eqerr=float(abs(nav.cash+nav.market_value+nav.receivable-nav.nav).max())
    hv=hold.groupby('date').value.sum().reindex(nav.date,fill_value=0).to_numpy() if len(hold) else np.zeros(len(nav));hold_err=float(np.max(abs(hv-nav.market_value)))
    assert max(casherr,eqerr,hold_err)<1e-5,(s['id'],casherr,eqerr,hold_err)
    assert (nav.cash>=-1e-7).all() and (nav.market_value<=nav.nav+1e-7).all() and (nav.borrowed_cash==0).all() and (nav.margin==0).all()
    if len(hold):assert not hold.duplicated(['t','j']).any();assert np.allclose(hold.q,np.round(hold.q)) and np.allclose(hold.pending,np.round(hold.pending))
    if len(tr):assert (tr.exit_t>tr.e).all();assert all(int(r.exit_t)>int(x['e']) for r in tr.itertuples() for x in r.lots)
    if len(buy):assert (buy.fill<=buy.limit+1e-8).all();assert (buy.debit<=buy.reserved+1e-7).all();assert not buy.duplicated(['t','symbol']).any()
    pnl=float(tr.pnl.sum()) if len(tr) else 0.
    if len(op):pnl+=sum((p['q']+p['pending'])*p['mark']+p['dividend_accrued']+p['sell_value']-p['sell_fees']-p['entry_cash'] for p in op.to_dict('records'))
    pnlerr=abs(pnl-(nav.nav.iloc[-1]-1e6));assert pnlerr<1e-5,(s['id'],'pnl',pnlerr)
    return dict(id=s['id'],cash_flow_max_error=casherr,nav_identity_max_error=eqerr,holdings_max_error=hold_err,realized_plus_open_pnl_error=pnlerr,min_cash=float(nav.cash.min()),max_gross_ratio=float(nav.exposure.max()),unique_physical_security=True,integer_stock_quantities=True,t1_lots=True,pass_=True)


def main():
    STATS.mkdir(exist_ok=True);publish_summary();summary=pd.read_csv(HERE/'scenario_summary.csv');rows=summary[summary.status.isin(['COMPLETED_NEW','NO_ELIGIBLE_SIGNAL'])];navs={};checks=[];annual=[];monthly=[];states=[];contrib=[];status=[];bindings=[];risk=[];behavior=[];trades_all=[];fills=[]
    ax=json.loads((CACHE/'axes.json').read_text());market=pd.read_csv(CACHE/'market.csv');idx=market['index'];ma=idx.rolling(60).mean();phase=np.where((idx>=ma)&(ma>=ma.shift(20)),'BULL',np.where((idx<ma)&(ma<ma.shift(20)),'BEAR','TRANSITION'))
    for r in rows.to_dict('records'):
        d=Path(r['output']);s=next(s for s in scenarios() if s['id']==r['id']);nav,tr,orders,audit,op,hold=[pd.read_parquet(d/(f+'.parquet')) for f in ['nav','trades','orders','audit','open_positions','holdings']]
        checks.append(account_audit(s,d,nav,tr,orders,audit,op,hold));navs[s['id']]=nav
        # All pre-authorized years and months, including flat and losing periods.
        for key,target in [(nav.date.str[:4],annual),(nav.date.str[:7],monthly)]:
            for period,g in nav.groupby(key):
                v=np.r_[1.,np.cumprod(1+g.return_daily)];target.append(dict(id=s['id'],period=period,net_return=v[-1]-1,maxdd=float((v/np.maximum.accumulate(v)-1).min()),mean_exposure=g.exposure.mean(),max_exposure=g.exposure.max(),trading_days=len(g),flat_days=int((g.holdings==0).sum())))
        nav['prior_close_phase']=phase[np.maximum(nav.t.to_numpy()-1,0)]
        for ph,g in nav.groupby('prior_close_phase'):states.append(dict(id=s['id'],phase=ph,sessions=len(g),mean_daily_return=g.return_daily.mean(),mean_exposure=g.exposure.mean(),log_return_contribution=float(np.log1p(g.return_daily).sum())))
        for day,v in nav.nlargest(5,'return_daily')[['date','return_daily']].itertuples(index=False):contrib.append(dict(id=s['id'],type='BEST_DAY_RETURN',key=day,value=v))
        if len(tr):
            totals=tr.groupby('symbol').pnl.sum()
            for sym,v in totals.nlargest(5).items():contrib.append(dict(id=s['id'],type='TOP_REALIZED_STOCK_PNL',key=sym,value=v,total_realized_pnl=tr.pnl.sum()))
            tt=tr.copy();tt['id']=s['id'];tt['route']=s['signal'];tt['capital']=s['capital'];tt['exit']=s['exit'];trades_all.append(tt)
        if len(orders):
            for k,v in orders.status.value_counts().items():status.append(dict(id=s['id'],status=k,count=int(v)))
            b=orders[orders.status=='FILLED'].copy();b['id']=s['id'];b['entry_style']='TAIL' if s['id'].startswith('Q4_') or s['id'].startswith('Q3_ENHANCED') else 'OPEN';fills.append(b)
        if len(hold):
            value=hold.groupby(['date','industry']).value.sum();maxindustry=(value.groupby('date').max()/nav.set_index('date').nav).max()
            risk.append(dict(id=s['id'],max_single_industry=float(maxindustry),max_plan_risk_nav=float((hold.groupby('date').risk_used.sum()/nav.set_index('date').nav).max()),max_mark_risk_nav=float((hold.groupby('date').mark_risk.sum()/nav.set_index('date').nav).max()),max_mark_risk_cny=float(hold.groupby('date').mark_risk.sum().max())))
        ident=json.loads((d/'identity.json').read_text());bindings.append(dict(id=s['id'],identity=sha(d/'identity.json'),artifacts=ident['artifacts']))
        behavior.append(dict(id=s['id'],nav_hash=ident['artifacts']['nav.parquet'],trades_hash=ident['artifacts']['trades.parquet'],economic_hash=hashlib.sha256(nav[['cash','market_value','receivable','nav','fees_cum','slippage_cum','turnover_cum','holdings']].to_numpy(dtype=np.float64).tobytes()).hexdigest()))
    for name,data in [('account_audit',checks),('annual',annual),('monthly',monthly),('market_phase',states),('concentration',contrib),('order_status',status),('risk_and_industry',risk),('behavior_identity',behavior)]:pd.DataFrame(data).to_csv(STATS/(name+'.csv'),index=False)
    dump(HERE/'ACCOUNT_AUDIT.json',dict(accounts=len(checks),all_pass=all(x['pass_'] for x in checks),checks_path=str(STATS/'account_audit.csv'),maximum_cash_error=max(x['cash_flow_max_error'] for x in checks),no_financing=True))
    parquet(STATS/'all_trades.parquet',pd.concat(trades_all,ignore_index=True));parquet(STATS/'all_filled_buys.parquet',pd.concat(fills,ignore_index=True))
    # Fixed, paired circular moving-block bootstrap. It resamples shared dates, not individual trades.
    rng=np.random.default_rng(20260908);n=len(next(iter(navs.values())));starts=rng.integers(0,n,(1000,math.ceil(n/20)));samples=((starts[:,:,None]+np.arange(20))%n).reshape(1000,-1)[:,:n]
    pairs=[]
    for s in scenarios():
        base=pair_baseline(s);sid=s['id']
        if not base or sid not in navs or base not in navs:continue
        a=navs[sid];b=navs[base];ar=a.return_daily.to_numpy();br=b.return_daily.to_numpy();boot=np.expm1(252*np.log1p(ar[samples]).mean(axis=1))-np.expm1(252*np.log1p(br[samples]).mean(axis=1));delta=ar-br
        X=np.column_stack([np.ones(n),market.market_return.to_numpy()[a.t],(a.exposure.to_numpy()-b.exposure.to_numpy())*market.market_return.to_numpy()[a.t]])
        coef=np.linalg.lstsq(X,delta,rcond=None)[0];exp_ratio=a.exposure.mean()/b.exposure.mean() if b.exposure.mean()>0 else np.nan
        pairs.append(dict(id=sid,baseline=base,net_return_difference=a.nav.iloc[-1]/1e6-b.nav.iloc[-1]/1e6,cagr_difference=(a.nav.iloc[-1]/1e6)**(252/n)-(b.nav.iloc[-1]/1e6)**(252/n),maxdd_difference=float((a.nav/np.maximum.accumulate(np.r_[1e6,a.nav])[1:]-1).min()-(b.nav/np.maximum.accumulate(np.r_[1e6,b.nav])[1:]-1).min()),mean_exposure_difference=a.exposure.mean()-b.exposure.mean(),mean_exposure_ratio=exp_ratio,bootstrap_cagr_diff_p025=float(np.quantile(boot,.025)),bootstrap_cagr_diff_p975=float(np.quantile(boot,.975)),bootstrap_positive_fraction=float((boot>0).mean()),mean_daily_difference=float(delta.mean()),exposure_scaled_base_annual_mean_difference=float(252*(ar-br*exp_ratio).mean()) if np.isfinite(exp_ratio) else None,market_and_exposure_regression_intercept_ann=float(coef[0]*252),inference_grade='EXPLORATORY_SHARED_CONSUMED_SAMPLE_NOT_OOS'))
    pd.DataFrame(pairs).to_csv(HERE/'incremental_comparison.csv',index=False)
    pd.DataFrame([dict(id=s['id'],nav_group=i+1,group_size=len(g)) for i,(_,g) in enumerate(pd.DataFrame(behavior).groupby('economic_hash')) for s in g.to_dict('records')]).to_csv(STATS/'behavior_equivalence.csv',index=False)
    dump(HERE/'ANALYSIS_MANIFEST.json',dict(accounts=len(navs),all_account_bindings=bindings,files={str(p):sha(p) for p in [STATS/n for n in ['account_audit.csv','annual.csv','monthly.csv','market_phase.csv','concentration.csv','order_status.csv','risk_and_industry.csv','behavior_identity.csv','behavior_equivalence.csv','all_trades.parquet','all_filled_buys.parquet']] if p.is_file()},pairs=sha(HERE/'incremental_comparison.csv'),bootstrap=dict(seed=20260908,block_sessions=20,repetitions=1000),cutoff='2023-12-31'))
    print('ANALYSIS_COMPLETE',len(navs),len(pairs),flush=True)
if __name__=='__main__':main()
