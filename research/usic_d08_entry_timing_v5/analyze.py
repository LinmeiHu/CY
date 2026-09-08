"""Final account, mechanism, paired-block and concentration attribution."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .common import HERE,OUT,V3,V4,sha,dump
from .market import Market

ROOTS={
 'BASE_T1':V3/'A_D08_C_10_E10','FIXED_T2':V3/'B_D08_C_10_DELAY1','BASE_T1_COST2':V3/'B_D08_C_10_COST2',
 'S1_T1':V4/'accounts/R1_S1_D08_C_10','S1_FIXED_T2':V4/'accounts/R1_S1_D08_DELAY1_C_10',
 'E3_HALF':OUT/'accounts/E3_FROZEN_BAND_C10_E10','E3_QUARTER':OUT/'accounts/E3_QUARTER_BAND_C10_E10_CA',
 'FIXED_T2_COST2':OUT/'accounts/E1_FIXED_T2_COST2_C10_E10','FIXED_T3':OUT/'accounts/E1_FIXED_T3_C10_E10',
 'E3_QUARTER_COST2':OUT/'accounts/E3_QUARTER_COST2_C10_E10','E3_QUARTER_S1':OUT/'accounts/E3_QUARTER_S1_C10_E10',
 'E3_QUARTER_CMAX':OUT/'accounts/E3_QUARTER_CMAX_E10'}

def result(path):return json.loads((path/'result.json').read_text())

def trades(path):
    t=pd.read_parquet(path/'trades.parquet');o=pd.read_parquet(path/'orders.parquet');f=o[o.status=='FILLED'][['t','symbol','setup_id']]
    assert not f.duplicated(['t','symbol']).any() and not t.duplicated(['e','symbol']).any()
    return t.merge(f,left_on=['e','symbol'],right_on=['t','symbol'],validate='one_to_one')

def metrics():
    rows=[]
    for key,path in ROOTS.items():
        r=result(path);n=pd.read_parquet(path/'nav.parquet');t=pd.read_parquet(path/'trades.parquet')
        assert len(n)==970 and (n.cash>=-1e-7).all() and (n.borrowed_cash==0).all() and (n.margin==0).all()
        art=r.get('artifacts',json.loads((path/'identity.json').read_text()).get('artifacts',{}) if (path/'identity.json').exists() else {})
        assert all(sha(path/name)==h for name,h in art.items())
        rows.append(dict(key=key,id=r['id'],status='VERIFIED_REUSE' if path.parts[-2]!='accounts' or key.startswith('S1_') else r['status'],source='V3' if path.is_relative_to(V3) else 'V4' if path.is_relative_to(V4) else 'V5',output=str(path),
            net_return=r['net_return'],cagr=r['cagr'],maxdd=r['maxdd'],volatility=r['volatility'],sharpe=r['sharpe'],mean_exposure=r['mean_exposure'],max_single=r['max_single'],trades=r['trades'],profit_factor=r['profit_factor'],fees=r['fees'],turnover=r['turnover'],min_cash=r['min_cash']))
    # Preserve the actual locally blocked attempt; its recovered account is separate.
    b=result(OUT/'accounts/E3_QUARTER_BAND_C10_E10')
    rows.append(dict(key='E3_QUARTER_BLOCKED',id=b['id'],status=b['status'],source='V5',output=str(OUT/'accounts/E3_QUARTER_BAND_C10_E10'),reason=b['reason'],resolved_by='E3_QUARTER_BAND_C10_E10_CA'))
    pd.DataFrame(rows).to_csv(HERE/'scenario_summary.csv',index=False)

def pair(a,b):
    # Return B minus A. Symmetric arithmetic split: common return, common capital, unique paths, residual.
    aa=trades(ROOTS[a]).set_index('setup_id');bb=trades(ROOTS[b]).set_index('setup_id');j=aa.join(bb,how='outer',lsuffix='_a',rsuffix='_b');c=j.dropna(subset=['pnl_a','pnl_b'])
    ra=c.pnl_a/c.entry_cash_a;rb=c.pnl_b/c.entry_cash_b
    weight=float(((ra+rb)/2*(c.entry_cash_b-c.entry_cash_a)).sum());ret=float(((c.entry_cash_a+c.entry_cash_b)/2*(rb-ra)).sum())
    onlyb=float(j[j.pnl_a.isna()].pnl_b.sum());misseda=float(-j[j.pnl_b.isna()].pnl_a.sum())
    na=pd.read_parquet(ROOTS[a]/'nav.parquet');nb=pd.read_parquet(ROOTS[b]/'nav.parquet');delta=float(nb.nav.iloc[-1]-na.nav.iloc[-1])
    return dict(baseline=a,candidate=b,common=len(c),only_candidate=int(j.pnl_a.isna().sum()),only_baseline=int(j.pnl_b.isna().sum()),common_capital_effect=weight,common_return_effect=ret,unique_candidate_pnl=onlyb,missed_baseline_pnl=misseda,residual=delta-weight-ret-onlyb-misseda,total_nav_increment=delta)

def paired():
    pairs=[('BASE_T1','FIXED_T2'),('BASE_T1_COST2','FIXED_T2_COST2'),('FIXED_T2','E3_QUARTER'),('S1_FIXED_T2','E3_QUARTER_S1'),('E3_QUARTER','E3_QUARTER_S1'),('FIXED_T2_COST2','E3_QUARTER_COST2'),('FIXED_T2','FIXED_T3')]
    parts=[];blocks=[];annual=[];rng=np.random.default_rng(20260908)
    for a,b in pairs:
        parts.append(pair(a,b));na=pd.read_parquet(ROOTS[a]/'nav.parquet');nb=pd.read_parquet(ROOTS[b]/'nav.parquet');assert (na.date==nb.date).all()
        da=na.nav.diff().fillna(na.nav.iloc[0]-1e6);db=nb.nav.diff().fillna(nb.nav.iloc[0]-1e6);z=pd.DataFrame({'date':na.date,'delta':db-da});z['block']=np.arange(len(z))//20;s=z.groupby('block').delta.sum().to_numpy()/1e6
        draws=s[rng.integers(0,len(s),(10000,len(s)))].sum(axis=1)
        blocks.append(dict(baseline=a,candidate=b,actual_total_return_increment=s.sum(),block20_bootstrap_low=np.quantile(draws,.025),block20_bootstrap_high=np.quantile(draws,.975),blocks=len(s),method='paired 20-session PnL blocks; 10,000 deterministic resamples; consumed development'))
        z['year']=z.date.str[:4]
        for year,g in z.groupby('year'):annual.append(dict(baseline=a,candidate=b,year=year,pnl_increment=g.delta.sum(),return_on_initial_capital=g.delta.sum()/1e6))
    pd.DataFrame(parts).to_csv(HERE/'matched_trade_attribution.csv',index=False);pd.DataFrame(blocks).to_csv(HERE/'paired_20d_intervals.csv',index=False);pd.DataFrame(annual).to_csv(HERE/'annual_pair_increment.csv',index=False)

def mechanisms():
    c=pd.read_parquet(OUT/'matched_common_trades.parquet');allx=pd.read_parquet(OUT/'matched_all_events.parquet')
    rows=[]
    for year,g in list(c.groupby('year'))+[('ALL',c)]:
        rows.append(dict(year=year,common=len(g),base_net=g.base_net_return.mean(),delay_net=g.delay_net_return.mean(),net_delta=g.net_return_delta.mean(),
            entry_price_effect_log=g.entry_price_effect_log.mean(),exit_clock_effect_log=g.exit_clock_effect_log.mean(),fee_dividend_residual=g.fee_dividend_residual.mean(),
            t2_price_better=g.t2_price_better.mean(),t1_close_extension_A=g.t1_close_extension_A.mean(),t1_close_location=g.t1_close_location.mean()))
    pd.DataFrame(rows).to_csv(HERE/'common_trade_mechanism.csv',index=False)
    screen=[]
    for (year,group),g in allx.groupby(['year','fill_group']):
        screen.append(dict(year=year,fill_group=group,events=len(g),base_pnl=g.base_pnl.sum(),delay_pnl=g.delay_pnl.sum(),future10_from_t1=g.after_t1_close_return_10.mean(),false_breakout=g.t1_false_breakout_close.mean(),t2_reenter=g.t2_reentered_frozen_zone.mean()))
    pd.DataFrame(screen).to_csv(HERE/'screening_attribution.csv',index=False)
    # Same symmetric cash/trade split by entry year for the core T+1 versus T+2 question.
    a=trades(ROOTS['BASE_T1']);b=trades(ROOTS['FIXED_T2']);a['year']=a.entry_date.str[:4].astype(int);b['year']=b.entry_date.str[:4].astype(int);yr=[]
    for year in range(2020,2024):
        aa=a[a.year==year].set_index('setup_id');bb=b[b.year==year].set_index('setup_id');j=aa.join(bb,how='outer',lsuffix='_a',rsuffix='_b');z=j.dropna(subset=['pnl_a','pnl_b']);ra=z.pnl_a/z.entry_cash_a;rb=z.pnl_b/z.entry_cash_b
        yr.append(dict(year=year,common=len(z),only_t2=int(j.pnl_a.isna().sum()),only_t1=int(j.pnl_b.isna().sum()),
            common_capital_effect=((ra+rb)/2*(z.entry_cash_b-z.entry_cash_a)).sum(),common_return_effect=((z.entry_cash_a+z.entry_cash_b)/2*(rb-ra)).sum(),
            t2_unique_pnl=j[j.pnl_a.isna()].pnl_b.sum(),missed_t1_pnl=-j[j.pnl_b.isna()].pnl_a.sum(),trade_pnl_increment=b[b.year==year].pnl.sum()-a[a.year==year].pnl.sum()))
    pd.DataFrame(yr).to_csv(HERE/'2022_vs_2023_cash_path.csv',index=False)

def years_and_paths():
    rows=[];curve=[];conc=[];m=Market()
    for key,path in ROOTS.items():
        n=pd.read_parquet(path/'nav.parquet');n['year']=n.date.str[:4];t=trades(path);t['year']=t.entry_date.str[:4]
        for year,g in n.groupby('year'):rows.append(dict(key=key,year=int(year),net_return=(1+g.return_daily).prod()-1,maxdd=(g.nav/g.nav.cummax()-1).min(),mean_exposure=g.exposure.mean(),fees=g.fees_cum.iloc[-1]-g.fees_cum.iloc[0]))
        total=t.pnl.abs().sum()
        for typ,col in [('industry','industry')]:
            for name,g in t.groupby(col):conc.append(dict(key=key,type=typ,value=name,trades=len(g),pnl=g.pnl.sum(),abs_pnl_share=g.pnl.abs().sum()/total if total else np.nan))
        for name,g in t.groupby(t.symbol.str[-2:]):conc.append(dict(key=key,type='board_suffix',value=name,trades=len(g),pnl=g.pnl.sum(),abs_pnl_share=g.pnl.abs().sum()/total if total else np.nan))
        for r in t.to_dict('records'):
            j=int(r['j']);e=int(r['e']);ep=r['entry']*m.val('factor',e,j)
            for d in range(1,11):
                q=e+d
                if q<len(m.dates):curve.append(dict(key=key,year=int(r['year']),setup_id=r['setup_id'],day=d,close_return=m.val('close',q,j)*m.val('factor',q,j)/ep-1))
    pd.DataFrame(rows).to_csv(HERE/'annual.csv',index=False);pd.DataFrame(conc).to_csv(HERE/'concentration.csv',index=False)
    q=pd.DataFrame(curve);q.groupby(['key','year','day']).close_return.agg(['count','mean','median']).reset_index().to_csv(HERE/'holding_return_curve.csv',index=False)

def failure_log():
    pd.DataFrame([
      dict(item='E2_OPEN_EXTENSION_GATE',status='CLOSED_WITHOUT_ACCOUNT',reason='T+1 open extension rank correlation with common-event delay delta was 0.0007 overall and changed sign by year.'),
      dict(item='E3_FROZEN_BAND_0.5A',status='NOT_ADVANCED',reason='35.04% beat base but remained below fixed T+2 41.64%; 2023 remained -8.71%.'),
      dict(item='E3_QUARTER_INITIAL',status='BLOCKED_INPUT_RECOVERED',reason='600161 2021 annual capitalization lacked share tradable date; official implementation index fixed it at 2022-07-18; recovered account kept separately.'),
      dict(item='E1_FIXED_T3',status='CLOSED',reason='12.26% did not preserve T+2 result; timing edge is not monotonic waiting.'),
      dict(item='E3_QUARTER_CMAX',status='CLOSED',reason='8.58% with -32.54% max drawdown; confirms no linear sizing expansion.'),
      dict(item='THRESHOLD_SEARCH',status='NOT_RUN',reason='Only frozen 0.5A boundary and one predeclared narrower 0.25A neighbor were tested.'),
    ]).to_csv(HERE/'failed_attempts.csv',index=False)

def year_comparison():
    e=pd.read_parquet(OUT/'matched_all_events.parquet');c=pd.read_parquet(OUT/'matched_common_trades.parquet');annual=pd.read_csv(HERE/'annual.csv');cash=pd.read_csv(HERE/'2022_vs_2023_cash_path.csv');rows=[]
    for year,g in e.groupby('year'):
        z=c[c.year==year]
        def annual_ret(key):return annual[(annual.key==key)&(annual.year==year)].net_return.iloc[0]
        rows.append(dict(year=year,signals=len(g),signal_dates=g.t.nunique(),base_fill_rate=(g.base_status=='FILLED').mean(),delay_fill_rate=(g.delay_status=='FILLED').mean(),common_trades=len(z),
            base_account_return=annual_ret('BASE_T1'),delay_account_return=annual_ret('FIXED_T2'),t1_gap_A=g.t1_open_gap_A.mean(),t1_extension_A=g.t1_open_extension_A.mean(),
            t1_close_location=g.t1_close_location.mean(),t1_volume_vs20=g.t1_volume_vs20.mean(),t1_amount_vs20=g.t1_amount_vs20.mean(),false_breakout_rate=g.t1_false_breakout_close.mean(),
            t2_reenter_frozen_zone=g.t2_reentered_frozen_zone.mean(),mfe10=g.after_t1_mfe_10.mean(),mae10=g.after_t1_mae_10.mean(),mfe_before_mae=g.mfe_before_mae.mean(),
            top_industry_signal_share=g.industry.value_counts(normalize=True).iloc[0],top_board_signal_share=g.board.value_counts(normalize=True).iloc[0],breadth20=g.B20.mean(),breadth_change10=g.DB20.mean(),market_vol20=g.market_vol20.mean(),stock_beta120=g.pre_beta120.mean(),log_amount20=g.pre_log_amount20.mean(),
            common_net_delta=z.net_return_delta.mean(),common_entry_price_effect_log=z.entry_price_effect_log.mean(),common_exit_clock_effect_log=z.exit_clock_effect_log.mean()))
    pd.DataFrame(rows).merge(cash,on='year',how='left').to_csv(HERE/'2022_vs_2023.csv',index=False)

def main():
    metrics();paired();mechanisms();years_and_paths();year_comparison();failure_log()
    checks=dict(accounts=len(ROOTS),all_account_hashes_and_no_financing=True,common_log_decomposition_max=float(pd.read_parquet(OUT/'matched_common_trades.parquet').gross_log_reconcile.abs().max()),new_completed_accounts=7,new_blocked_attempts=1,new_economic_hypotheses=7,sealed_data_opened=False)
    dump(HERE/'analysis_status.json',checks);print(json.dumps(checks))

if __name__=='__main__':main()
