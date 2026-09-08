"""Phase A: event timeline and matched-account entry/exit-clock attribution."""
import math
import numpy as np
import pandas as pd
from .common import HERE,OUT,V3,V4,dump,log
from ..usic_market_router_v4.market import Market

BASE=V3/'A_D08_C_10_E10'; DELAY=V3/'B_D08_C_10_DELAY1'

def val(m,k,t,j):
    return float(m.a[k][t,j]) if 0<=t<len(m.dates) else np.nan

def coord(m,k,t,j):
    return val(m,k,t,j)*val(m,'factor',t,j)

def rank_corr(x,y):
    z=pd.DataFrame({'x':x,'y':y}).dropna()
    return z.x.rank().corr(z.y.rank()) if len(z)>2 else np.nan

def account_events(path,prefix):
    o=pd.read_parquet(path/'orders.parquet');t=pd.read_parquet(path/'trades.parquet')
    f=o[o.status=='FILLED'][['setup_id','signal_t','symbol','t','fill','quantity','debit']].copy()
    if f.duplicated(['signal_t','symbol']).any():raise AssertionError(prefix+' account has ambiguous filled event key')
    t=t.merge(f[['setup_id','signal_t','symbol']],on=['signal_t','symbol'],how='left',validate='one_to_one')
    keep=['setup_id','pnl','entry_cash','entry','e','exit_t','exit_price','held_sessions','sell_fees','dividend_accrued']
    return o[['setup_id','status']].rename(columns={'status':prefix+'_status'}),t[keep].rename(columns={c:prefix+'_'+c for c in keep if c!='setup_id'})

def timeline(m):
    sig=pd.read_parquet(BASE/'input_signals.parquet');states=pd.read_parquet(V4/'state_daily.parquet').set_index('t')
    rows=[]
    for r in sig.to_dict('records'):
        t=int(r['t']);j=int(r['j']);fac=float(r['factor']);U=r['U']*fac;S0=r['S0']*fac;A=r['a0']*fac
        x=dict(setup_id=r['setup_id'],parent_id=r['parent_id'],symbol=r['symbol'],board=r['board'],industry=int(r['industry']),
            t=t,signal_date=m.dates[t],score=r['score'],U_coord=U,S0_coord=S0,ATR_coord=A,limit_coord=r['limit']*fac,
            signal_close_extension_A=(coord(m,'close',t,j)-U)/A,signal_close_vs_U=(coord(m,'close',t,j)/U-1),
            information_cutoff=m.dates[t]+'T15:00:00+08:00')
        for d in [1,2]:
            q=t+d;pre='t'+str(d);f=val(m,'factor',q,j);op=coord(m,'open',q,j);hi=coord(m,'high',q,j);lo=coord(m,'low',q,j);cl=coord(m,'close',q,j)
            prior=coord(m,'close',q-1,j);rng=hi-lo
            legal=m.legal(q,j) if q<len(m.dates) else 'END_BOUNDARY'
            limit=math.floor(r['limit']*r['factor']/f*100+1e-8)/100 if np.isfinite(f) and f>0 else np.nan
            slipped=math.ceil(val(m,'open',q,j)*1.0005*100-1e-8)/100 if np.isfinite(val(m,'open',q,j)) else np.nan
            executable=not legal and slipped<=limit+1e-8 and slipped<=val(m,'up_limit_price',q,j)+1e-8
            pastvol=m.a['volume'][max(0,q-20):q,j];pastamt=m.a['amount'][max(0,q-20):q,j]
            x.update({pre+'_date':m.dates[q] if q<len(m.dates) else '',pre+'_open_extension_A':(op-U)/A,pre+'_open_gap_A':(op-prior)/A,
                pre+'_open_vs_signal_close_A':(op-coord(m,'close',t,j))/A,pre+'_high_extension_A':(hi-U)/A,pre+'_low_extension_A':(lo-U)/A,
                pre+'_close_extension_A':(cl-U)/A,pre+'_close_vs_S0_A':(cl-S0)/A,pre+'_range_A':rng/A,
                pre+'_close_location':(cl-lo)/rng if rng>0 else np.nan,pre+'_upper_reversal_A':(hi-cl)/A,
                pre+'_volume_vs20':val(m,'volume',q,j)/np.nanmedian(pastvol) if np.any(np.isfinite(pastvol)) and np.nanmedian(pastvol)>0 else np.nan,
                pre+'_amount_vs20':val(m,'amount',q,j)/np.nanmedian(pastamt) if np.any(np.isfinite(pastamt)) and np.nanmedian(pastamt)>0 else np.nan,
                pre+'_structure_holds':bool(cl>S0),pre+'_above_U_close':bool(cl>=U),pre+'_false_breakout_close':bool(cl<U),
                pre+'_reversal':bool((hi-cl)>=.5*A and (cl-lo)<(hi-cl)),pre+'_legal':legal,pre+'_frozen_limit':limit,
                pre+'_slipped_open':slipped,pre+'_executable':bool(executable)})
        x['t2_reentered_frozen_zone']=bool(x['t2_open_extension_A']<=.5 and x['t2_open_extension_A']>=((S0-U)/A))
        x['t2_price_better']=bool(x['t2_open_extension_A']<x['t1_open_extension_A'])
        x['t1_digest_to_quarter_A']=bool(x['t1_structure_holds'] and x['t1_close_extension_A']<=.25)
        # Outcomes are labels only; no later field is allowed into an entry rule.
        entry=coord(m,'open',t+1,j)
        path=[]
        for d in range(1,11):
            q=t+1+d
            if q<len(m.dates):path.append((d,(coord(m,'high',q,j)/entry-1),(coord(m,'low',q,j)/entry-1),(coord(m,'close',q,j)/entry-1)))
        for d in [1,3,5,10]:x['after_t1_close_return_'+str(d)]=next((z[3] for z in path if z[0]==d),np.nan)
        x['after_t1_mfe_10']=max([z[1] for z in path],default=np.nan);x['after_t1_mae_10']=min([z[2] for z in path],default=np.nan)
        adverse=[d for d,_,_,c in path if c<0];x['first_adverse_close']=min(adverse) if adverse else np.nan
        mfe_day=max(path,key=lambda z:z[1])[0] if path else np.nan;mae_day=min(path,key=lambda z:z[2])[0] if path else np.nan;x['mfe_before_mae']=bool(mfe_day<mae_day) if path else False
        st=states.loc[t] if t in states.index else None
        if st is not None:
            for c in ['S1','B20','B60','DB20']:x[c]=st.get(c,np.nan)
            x['market_vol20']=st.get('vol20',np.nan);x['market_drawdown60']=st.get('past_drawdown',np.nan)
        # Strictly prior stock beta and liquidity context.
        sclose=m.a['coord'][max(0,t-120):t+1,j];market=m.a['market'][max(0,t-120):t+1]
        sr=np.diff(np.log(sclose));mr=np.diff(np.log(market));ok=np.isfinite(sr)&np.isfinite(mr)
        x['pre_beta120']=np.cov(sr[ok],mr[ok],ddof=1)[0,1]/np.var(mr[ok],ddof=1) if ok.sum()>30 and np.var(mr[ok])>0 else np.nan
        x['pre_log_amount20']=np.log(r['amount20']) if r['amount20']>0 else np.nan
        rows.append(x)
    return pd.DataFrame(rows)

def matched(m,events):
    bo,bt=account_events(BASE,'base');do,dt=account_events(DELAY,'delay')
    x=events.merge(bo,on='setup_id').merge(do,on='setup_id').merge(bt,on='setup_id',how='left').merge(dt,on='setup_id',how='left')
    x['fill_group']=np.select([(x.base_status=='FILLED')&(x.delay_status=='FILLED'),(x.base_status=='FILLED')&(x.delay_status!='FILLED'),(x.base_status!='FILLED')&(x.delay_status=='FILLED')],['BOTH_FILLED','T1_ONLY','T2_ONLY'],default='NEITHER')
    c=x[x.fill_group=='BOTH_FILLED'].copy()
    f=np.asarray(m.a['factor'])
    def factor_at(col):return np.array([f[int(t),m.symbols.index(s)] for t,s in zip(c[col],c.symbol)])
    e0=c.base_e.astype(int).to_numpy();e1=c.delay_e.astype(int).to_numpy();z0=c.base_exit_t.astype(int).to_numpy();z1=c.delay_exit_t.astype(int).to_numpy()
    js=np.array([m.symbols.index(s) for s in c.symbol])
    ep0=c.base_entry.to_numpy()*f[e0,js];ep1=c.delay_entry.to_numpy()*f[e1,js];xp0=c.base_exit_price.to_numpy()*f[z0,js];xp1=c.delay_exit_price.to_numpy()*f[z1,js]
    c['gross_log_base']=np.log(xp0/ep0);c['gross_log_delay']=np.log(xp1/ep1)
    c['entry_price_effect_log']=np.log(ep0/ep1);c['exit_clock_effect_log']=np.log(xp1/xp0)
    c['gross_log_reconcile']=c.gross_log_delay-c.gross_log_base-c.entry_price_effect_log-c.exit_clock_effect_log
    c['base_net_return']=c.base_pnl/c.base_entry_cash;c['delay_net_return']=c.delay_pnl/c.delay_entry_cash
    c['net_return_delta']=c.delay_net_return-c.base_net_return
    c['fee_dividend_residual']=c.net_return_delta-(np.exp(c.gross_log_delay)-1)+(np.exp(c.gross_log_base)-1)
    assert c.gross_log_reconcile.abs().max()<1e-12
    return x,c

def summaries(events,all_events,common):
    groups=[]
    for cols in [['year'],['year','t1_extension_bin'],['year','t1_false_breakout_close'],['year','t1_reversal'],['year','t1_digest_to_quarter_A']]:
        for key,g in events.groupby(cols,dropna=False):
            key=(key,) if not isinstance(key,tuple) else key
            row=dict(zip(cols,key));row.update(signals=len(g),dates=g.t.nunique(),t1_executable=g.t1_executable.mean(),t2_executable=g.t2_executable.mean(),
                t1_gap_A=g.t1_open_gap_A.mean(),t1_extension_A=g.t1_open_extension_A.mean(),t1_close_location=g.t1_close_location.mean(),
                t1_amount_vs20=g.t1_amount_vs20.mean(),false_breakout=g.t1_false_breakout_close.mean(),t2_reenter=g.t2_reentered_frozen_zone.mean(),
                mfe=g.after_t1_mfe_10.mean(),mae=g.after_t1_mae_10.mean(),mfe_before_mae=g.mfe_before_mae.mean(),return10=g.after_t1_close_return_10.mean())
            groups.append(row)
    pd.DataFrame(groups).to_csv(HERE/'entry_timing_diagnostics.csv',index=False)
    yearly=[]
    for year,g in common.groupby('year'):
        yearly.append(dict(year=year,common=len(g),base_pnl=g.base_pnl.sum(),delay_pnl=g.delay_pnl.sum(),mean_net_delta=g.net_return_delta.mean(),
            entry_price_effect_log=g.entry_price_effect_log.mean(),exit_clock_effect_log=g.exit_clock_effect_log.mean(),
            t1_gap_A=g.t1_open_gap_A.mean(),t1_extension_A=g.t1_open_extension_A.mean(),t1_close_location=g.t1_close_location.mean(),t1_amount_vs20=g.t1_amount_vs20.mean(),
            false_breakout=g.t1_false_breakout_close.mean(),t2_reenter=g.t2_reentered_frozen_zone.mean(),mfe=g.after_t1_mfe_10.mean(),mae=g.after_t1_mae_10.mean(),mfe_before_mae=g.mfe_before_mae.mean(),
            high_industry_share=g.industry.value_counts(normalize=True).iloc[0],high_board_share=g.board.value_counts(normalize=True).iloc[0],B20=g.B20.mean(),DB20=g.DB20.mean(),market_vol20=g.market_vol20.mean(),beta=g.pre_beta120.mean(),log_amount20=g.pre_log_amount20.mean()))
    pd.DataFrame(yearly).to_csv(HERE/'2022_vs_2023.csv',index=False)
    stats=[]
    for v in ['t1_open_extension_A','t1_open_gap_A','t1_close_location','t1_upper_reversal_A','t1_volume_vs20','t1_amount_vs20','t1_close_extension_A']:
        for year,g in common.groupby('year'):
            stats.append(dict(variable=v,year=year,n=g[v].notna().sum(),rank_corr_net_delta=rank_corr(g[v],g.net_return_delta),rank_corr_delay_return=rank_corr(g[v],g.delay_net_return),rank_corr_base_return=rank_corr(g[v],g.base_net_return)))
        stats.append(dict(variable=v,year='ALL',n=common[v].notna().sum(),rank_corr_net_delta=rank_corr(common[v],common.net_return_delta),rank_corr_delay_return=rank_corr(common[v],common.delay_net_return),rank_corr_base_return=rank_corr(common[v],common.base_net_return)))
    pd.DataFrame(stats).to_csv(HERE/'diagnostic_correlations.csv',index=False)
    counts=all_events.fill_group.value_counts().rename_axis('fill_group').reset_index(name='events');counts.to_csv(HERE/'matched_fill_groups.csv',index=False)

def main():
    if not (HERE/'RESEARCH_LOG.jsonl').exists():log('A0','V4 verified D08/C10 base 15.15%; fixed T+2 41.64%; common-event clock contribution unresolved','Delay may arise from overextension, failed-breakout screening, price, exit clock, capital path, or year interaction','diagnostics only; no new account','V4 A_D08_C_10_E10 and B_D08_C_10_DELAY1','one or more observables separate common-event delta and 2022/2023','no stable observable relation or delta dominated by exit/capital path closes conditional-rule branch',phase='BEFORE_DIAGNOSIS')
    m=Market();events=timeline(m);events['year']=events.signal_date.str[:4].astype(int)
    events['t1_extension_bin']=pd.cut(events.t1_open_extension_A,[-np.inf,0,.25,.5,np.inf],labels=['AT_OR_BELOW_U','U_TO_0.25A','0.25A_TO_0.5A','ABOVE_LIMIT_SCALE'])
    events.to_parquet(OUT/'event_timeline.parquet',index=False)
    all_events,common=matched(m,events);all_events.to_parquet(OUT/'matched_all_events.parquet',index=False);common.to_parquet(OUT/'matched_common_trades.parquet',index=False)
    summaries(events,all_events,common)
    dump(HERE/'diagnostic_status.json',dict(events=len(events),matched_events=len(all_events),unmatched_end_boundary=len(events)-len(all_events),common=len(common),fill_groups=all_events.fill_group.value_counts().to_dict(),input_cutoff='T or T+1 close explicitly named; all future fields labels only',gross_log_reconciliation_max=float(common.gross_log_reconcile.abs().max()),new_accounts_run=0))
    print((HERE/'2022_vs_2023.csv').read_text());print((HERE/'diagnostic_correlations.csv').read_text())

if __name__=='__main__':main()
