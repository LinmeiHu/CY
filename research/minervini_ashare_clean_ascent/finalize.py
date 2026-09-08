"""Independent ledger reconciliation and fixed comparisons; Chinese reporting."""
import json,math,subprocess
from pathlib import Path
import numpy as np,pandas as pd
from .common import HERE,OUT,sha,dump,scenarios

def table(d,columns=None):
    if columns is not None:d=d[columns]
    return d.to_markdown(index=False,floatfmt='.4f')

def run():
    summary=pd.read_csv(HERE/'scenario_summary.csv');rows=[];annual=[];paired=[];diagnostics=[];identities=[];navs={};trades={};auditsall=[]
    axes=json.loads((OUT/'axes.json').read_text());rng=np.random.default_rng(20260908)
    for s in summary[summary.status=='NEWLY_EXECUTED'].to_dict('records'):
        d=Path(s['output']);nav=pd.read_parquet(d/'nav.parquet');tr=pd.read_parquet(d/'trades.parquet');o=pd.read_parquet(d/'orders.parquet');a=pd.read_parquet(d/'audit.parquet');op=pd.read_parquet(d/'open_positions.parquet')
        navs[s['id']]=nav;trades[s['id']]=tr
        identity=json.loads((d/'identity.json').read_text())
        assert identity['source_hash']==sha(HERE/'replay.py'),s['id']
        assert identity['config_hash']==s['config_hash']
        assert identity['execution_input_hash']==sha(HERE/'execution_input_binding.json')
        for name,h in identity['artifacts'].items():assert sha(d/name)==h
        identities.append(dict(scenario=s['id'],identity_hash=sha(d/'identity.json'),**identity))
        buys=o[o.status=='FILLED'].copy();buyflow=buys.groupby('t').debit.sum() if len(buys) else pd.Series(dtype=float)
        cashflow=a.groupby('day').cash_delta.sum() if len(a) and 'cash_delta' in a else pd.Series(dtype=float)
        expected=1e6;error=0.
        for z in nav.itertuples():
            expected+=cashflow.get(z.date,0.)-buyflow.get(z.t,0.);error=max(error,abs(expected-z.book_cash))
        assert error<1e-6,(s['id'],error)
        reconcile=(nav.nav-nav.cash-nav.market_value-nav.receivable).abs().max();assert reconcile<1e-6
        assert nav.cash.min()>=0 and (nav.market_value<=nav.nav+1e-7).all() and (nav.borrowed_cash==0).all() and (nav.margin==0).all()
        assert (buys.debit<=buys.reserved+1e-7).all() and (buys.fill<=buys.limit+1e-8).all()
        assert ((buys.t-buys.signal_t)==s['delay']).all()
        if len(tr):assert (tr.exit_t>tr.e).all()
        rows.append(dict(scenario=s['id'],status='PASS',cash_reconstruction_max_error=error,nav_reconciliation_max_error=reconcile,min_cash=nav.cash.min(),max_exposure=nav.exposure.max(),legal_entry_lag=True,T_plus_1_sell=True))
        nav['fees_daily']=nav.fees_cum.diff().fillna(nav.fees_cum.iloc[0])
        for year,g in nav.groupby(nav.date.str[:4]):annual.append(dict(scenario=s['id'],year=year,net_return=np.prod(1+g.return_daily)-1,mean_exposure=g.exposure.mean(),fees=g.fees_daily.sum()))
        g=tr if len(tr) else pd.DataFrame()
        diag=dict(scenario=s['id'],signals=len(o),filled=len(buys),lowopen_count=int(buys.lowopen.sum()) if len(buys) else 0,lowopen_pnl=g.loc[g.lowopen,'pnl'].sum() if len(g) else 0,lowopen_pnl_other=g.loc[~g.lowopen,'pnl'].sum() if len(g) else 0,buy_day_structure_breaches=int(g.buy_day_breach.sum()) if len(g) else 0,intraday_only_structure_touches=int(g.intraday_only.sum()) if len(g) else 0,open_positions=len(op),stale_open_positions=int((op.stale>0).sum()) if len(op) else 0,unallocated_fraction=float(a.unallocated_fraction.sum()) if 'unallocated_fraction' in a else 0,integer_allocation_uncertain_events=int((a.type=='FRACTIONAL_ALLOCATION_LOWER_BOUND').sum()) if len(a) else 0)
        if len(g):
            contr=g.groupby('symbol').pnl.sum().sort_values(ascending=False);diag.update(best_stock=contr.index[0],best_stock_pnl=contr.iloc[0],pnl_ex_best_stock=g.pnl.sum()-contr.iloc[0],largest_trade_pnl=g.pnl.max(),worst_trade_pnl=g.pnl.min(),planned_risk_exceeded=int((-g.pnl>g.planned_risk).sum()),max_planned_risk_nav=(g.planned_risk/g.nav_at_order).max())
            y=nav.return_daily.to_numpy();diag.update(return_ex_best_day=np.prod(1+np.delete(y,np.argmax(y)))-1,return_ex_best_five_days=np.prod(1+np.delete(y,np.argsort(y)[-5:]))-1)
        diagnostics.append(diag)
        a['scenario']=s['id'];auditsall.append(a)
    pd.DataFrame(rows).to_csv(HERE/'accounting_checks.csv',index=False);pd.DataFrame(annual).to_csv(HERE/'annual_results.csv',index=False);pd.DataFrame(diagnostics).to_csv(HERE/'execution_diagnostics.csv',index=False)
    dump(HERE/'run_identity_index.json',identities)
    for mode in ['MAX_DEPLOYABLE','CAP10']:
        pairs=[('OLD_MAIN_B0_'+mode,'OLD_MAIN_'+v+'_'+mode) for v in ['P','C','PC']]+[('N_MAIN_N0_'+mode,'N_MAIN_N1_'+mode)]+[('N_MAIN_N1_'+mode,'N_MAIN_'+v+'_'+mode) for v in ['N2','N3','N4']]+[('N_MAIN_N4_'+mode,'N_MAIN_'+v+'_'+mode) for v in ['N5','N6','N7','N8','N9']]+[(f'INDUSTRY_N4_MATCH_{mode}',f'INDUSTRY_N4_PLUS_{mode}')]
        for v in ['N1','N4','N9']:
            pairs += [(f'N_MAIN_{v}_{mode}',f'{group}_{v}_{mode}') for group in ['N_COST','N_DELAY','N_EXIT']]
        for base,other in pairs:
            if base not in navs or other not in navs:continue
            b=navs[base];n=navs[other];assert b.date.tolist()==n.date.tolist();diff=(n.return_daily-b.return_daily).to_numpy();count=len(diff);boot=[]
            for _ in range(1000):
                starts=rng.integers(0,count-20+1,size=math.ceil(count/20));idx=(starts[:,None]+np.arange(20)).ravel()[:count];boot.append(diff[idx].mean()*252)
            paired.append(dict(baseline=base,enhanced=other,cumulative_return_delta=n.nav.iloc[-1]/1e6-b.nav.iloc[-1]/1e6,annualized_arithmetic_delta=diff.mean()*252,block20_ci_low=np.quantile(boot,.025),block20_ci_high=np.quantile(boot,.975),exposure_delta=n.exposure.mean()-b.exposure.mean()))
    pd.DataFrame(paired).to_csv(HERE/'paired_comparisons.csv',index=False)
    # Light-weight immutable historical five-strategy NAV-cache comparison, no replays.
    source=Path('/Users/linmei/Documents/CY-worktrees/five-strategy-shared-capital-v1/research/shared_capital_v1/cache');cor=[];sourceindex=[]
    for strategy in ['atrdr','mcb','ogr','ifcgr','smv6']:
        paths=[source/'common_p0'/('OGR' if strategy=='ogr' else 'IFCGR')/y/(strategy+'_native_nav.parquet') for y in ['2018_2021','2022_2023']] if strategy!='smv6' else [source/strategy/y/'physical_p0_nav.parquet' for y in ['2018_2021','2022_2023']]
        if not all(p.exists() for p in paths):continue
        series=[]
        for p in paths:
            before=sha(p);f=pd.read_parquet(p);assert sha(p)==before;f['date']=pd.to_datetime(f.trade_date).dt.strftime('%Y-%m-%d');assert f.date.max()<'2024-01-01'
            f=f.sort_values('date').drop_duplicates('date',keep='last');f['r']=f.nav.pct_change();series.append(f[['date','r']]);sourceindex.append(dict(strategy=strategy,path=str(p),sha256=before,grade='EXISTING_RESEARCH_CACHE_NOT_NATIVE_PLATFORM_CERTIFICATION'))
        five=pd.concat(series).drop_duplicates('date').set_index('date').r
        for sid in ['N_MAIN_N4_MAX_DEPLOYABLE','N_MAIN_N4_CAP10','N_MAIN_N9_MAX_DEPLOYABLE','N_MAIN_N9_CAP10']:
            if sid not in navs:continue
            n=navs[sid].set_index('date').return_daily;joined=pd.concat([n.rename('n'),five.rename('five')],axis=1).dropna()
            cor.append(dict(scenario=sid,strategy=strategy,n=len(joined),status='PARTIAL_ALIGNED_RESEARCH_NAV' if len(joined)>=252 and joined.five.std()>0 else 'NOT_ASSESSED_INSUFFICIENT_OR_CONSTANT_NAV',correlation=joined.n.corr(joined.five) if len(joined)>=252 and joined.five.std()>0 else np.nan,joint_negative_days=int(((joined.n<0)&(joined.five<0)).sum()) if len(joined) else None))
    pd.DataFrame(cor).to_csv(HERE/'five_strategy_correlation.csv',index=False);dump(HERE/'five_strategy_source_index.json',sourceindex)
    if auditsall:pd.concat(auditsall,ignore_index=True).to_parquet(OUT/'all_account_audit.parquet',index=False)
    # Fixed illustrative selection contains fills, failures and execution rejects.
    cases=[]
    for sid in ['OLD_MAIN_PC_MAX_DEPLOYABLE','N_MAIN_N4_MAX_DEPLOYABLE']:
        if sid not in trades:continue
        g=trades[sid]
        for name,subset in [('first_profitable',g[g.pnl>0]),('first_loss',g[g.pnl<0]),('first_deferred',g[g.exit_delay>0])]:
            if len(subset):cases.append(dict(scenario=sid,case=name,**subset.sort_values(['e','symbol']).iloc[0].to_dict()))
        o=pd.read_parquet(OUT/sid/'orders.parquet');bad=o[o.status.isin(['OVER_LIMIT','LIMIT_OPEN','LIMIT_OR_STATUS_BLOCK'])]
        if len(bad):cases.append(dict(scenario=sid,case='first_unfilled',**bad.sort_values(['t','symbol']).iloc[0].to_dict()))
    pd.DataFrame(cases).to_csv(HERE/'cases.csv',index=False)
    print('FINAL_AUDIT',len(rows),'complete accounts',flush=True)
if __name__=='__main__':run()
