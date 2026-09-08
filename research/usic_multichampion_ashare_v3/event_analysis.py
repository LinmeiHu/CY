"""Full signal/episode diagnostics and fixed nuisance-factor regressions, never a new account search."""
import json
import numpy as np
import pandas as pd
import duckdb
from .common import HERE,OUT,CACHE,sha,dump,parquet,rank
from .analyze import STATS


def main():
    STATS.mkdir(exist_ok=True);ax=json.loads((CACHE/'axes.json').read_text());ds=ax['dates'];sy={s:i for i,s in enumerate(ax['symbols'])};di={d:t for t,d in enumerate(ds)}
    a={p.stem:np.load(p,mmap_mode='r') for p in CACHE.glob('*.npy')};n,z=a['close'].shape
    capfile=STATS/'circulating_capital.npy'
    if not capfile.exists():
        cap=np.full((n,z),np.nan)
        for year in range(2018,2024):
            src=f'/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily/partition_year={year}/data_0.parquet'
            with duckdb.connect() as con:f=con.execute('SELECT trade_date,symbol,circulating_shares,close FROM read_parquet(?) WHERE float_valid AND float_available_date<=trade_date',[src]).fetchdf()
            t=f.trade_date.astype(str).str[:10].map(di);j=f.symbol.map(sy);good=t.notna()&j.notna();cap[t[good].astype(int),j[good].astype(int)]=f.loc[good,'circulating_shares']*f.loc[good,'close']
        np.save(capfile,cap)
    cap=np.load(capfile,mmap_mode='r');mr=pd.read_csv(CACHE/'market.csv').market_return.to_numpy();mvar=pd.Series(mr).rolling(120).var().to_numpy()
    controls={};events=[];routes=[f'D{i:02d}' for i in range(10)]+['H01','H02'];f=pd.concat([pd.read_parquet(OUT/f'{r}_signals.parquet') for r in routes],ignore_index=True)
    for j,g in f.groupby('j'):
        j=int(j);c=a['coord'][:,j];rr=a['step'][:,j];v=pd.Series(rr);beta=v.rolling(120).cov(pd.Series(mr)).to_numpy()/mvar;vol=v.rolling(30).std().to_numpy();mx=v.rolling(30).max().to_numpy();liq=pd.Series(a['amount'][:,j]).rolling(20).median().to_numpy()
        for r in g.to_dict('records'):
            t=int(r['t']);e=t+1;q=t-1;fac=a['factor'][e,j] if e<n else np.nan;limit=np.floor(r['limit']*r['factor']/fac*100+1e-8)/100 if fac>0 else np.nan;op=a['open'][e,j] if e<n else np.nan;price=np.ceil(op*1.0005*100-1e-8)/100
            filled=bool(e<n and np.isfinite(price+limit) and a['hard_valid'][e,j]==1 and a['buy_blocked_open'][e,j]==0 and a['trade_status'][e,j]==1 and a['volume'][e,j]>0 and op<a['up_limit_price'][e,j]-1e-6 and price<=min(limit,a['up_limit_price'][e,j])+1e-8)
            row=dict(route=r['route'],t=t,j=j,symbol=r['symbol'],board=ax['boards'][j],industry=int(a['industry'][q,j]),setup_id=r['setup_id'],score=r['score'],year=ds[t][:4],date=ds[t],e=e,pre_return30=c[q]/c[q-30]-1,pre_max30=mx[q],pre_volatility30=vol[q],pre_beta120=beta[q],log_liquidity20=np.log(liq[q]) if liq[q]>0 else np.nan,log_float_cap=np.log(cap[q,j]) if cap[q,j]>0 else np.nan,signal_to_open_return=op*fac/(a['coord'][t,j])-1 if e<n else np.nan,signal_proxy_executable=filled,low_open_below_U=bool(op<r['U']*r['factor']/fac) if filled else False,avwap_status=r.get('avwap_status'),avwap_pass=r.get('avwap_pass'))
            for h in [1,3,5,10,20,40]:
                complete=filled and e+h<n and np.isfinite(c[e:e+h+1]).all();row[f'r{h}']=float(c[e+h]/(price*fac)-1) if complete else np.nan
            if filled:
                end=min(n,e+41);hh=a['high'][e:end,j]*a['factor'][e:end,j]/(price*fac)-1;ll=a['low'][e:end,j]*a['factor'][e:end,j]/(price*fac)-1;close=c[e:end]/(price*fac)-1;neg=np.flatnonzero(close<0);row.update(mfe40=float(np.nanmax(hh)),mae40=float(np.nanmin(ll)),first_adverse_session=int(neg[0]) if len(neg) else None,forward40_censored=end<e+41)
            events.append(row)
    ev=pd.DataFrame(events);parquet(STATS/'signal_event_diagnostics.parquet',ev)
    cols=['pre_return30','signal_to_open_return','r1','r3','r5','r10','r20','r40','mfe40','mae40'];agg=ev.groupby('route')[cols].agg(['count','mean','median']);agg.columns=['_'.join(c) for c in agg.columns];agg['signals']=ev.groupby('route').size();agg['proxy_fill_rate']=ev.groupby('route').signal_proxy_executable.mean();agg.to_csv(HERE/'route_event_summary.csv')
    for key in ['year','board']:
        ev.groupby(['route',key]).agg(signals=('t','size'),proxy_fill_rate=('signal_proxy_executable','mean'),r10_count=('r10','count'),r10_mean=('r10','mean'),r40_mean=('r40','mean'),mfe40_mean=('mfe40','mean'),mae40_mean=('mae40','mean')).to_csv(STATS/f'events_by_{key}.csv')
    # D04 matched coverage is COMPLETE AVWAP anchor data on D03, not a missing-data comparison.
    av=ev[(ev.route=='D03')&(ev.avwap_status=='COMPLETE')].copy();av.groupby('avwap_pass').agg(signals=('t','size'),proxy_fill_rate=('signal_proxy_executable','mean'),r10_mean=('r10','mean'),r40_mean=('r40','mean'),mae40_mean=('mae40','mean')).to_csv(STATS/'avwap_matched_event_diagnostic.csv')
    regs=[];factors=['pre_return30','pre_max30','pre_volatility30','pre_beta120','log_liquidity20','log_float_cap']
    for new,base in [('D01','D00'),('D02','D01'),('D03','D00'),('D04','D03'),('D05','D03'),('D06','D00'),('D07','D06'),('D08','D06'),('D09','D02'),('H01','D02'),('H02','D05')]:
        if new=='D04':g=av.copy();g['treated']=g.avwap_pass.astype(float)
        else:g=ev[ev.route.isin([new,base])].copy();g['treated']=(g.route==new).astype(float)
        prior=len(g);g=g.dropna(subset=factors+['r10']);g=g[g.groupby('t').treated.transform('nunique')==2].copy()
        if len(g)<200:regs.append(dict(route=new,baseline=base,status='INSUFFICIENT_MATCHED_SUPPORT',n=len(g),prior_rows=prior));continue
        num=g[['treated']+factors].copy();num[factors]=(num[factors]-num[factors].mean())/num[factors].std();dummy=pd.get_dummies(g[['board','industry']].astype(str),drop_first=True,dtype=float);X=pd.concat([num,dummy],axis=1);X=X-X.groupby(g.t).transform('mean');y=g.r10-g.groupby('t').r10.transform('mean');xx=X.to_numpy();yy=y.to_numpy();coef=np.linalg.lstsq(xx,yy,rcond=1e-10)[0];res=yy-np.einsum('ij,j->i',xx,coef,optimize=False);gram=np.einsum('ni,nj->ij',xx,xx,optimize=False);values,vectors=np.linalg.eigh(gram);keep=values>values.max()*1e-10;bread0=np.einsum('ij,j->i',vectors[:,keep],vectors[0,keep]/values[keep],optimize=False);variance=0.;assert np.isfinite(coef).all()
        for ix in g.groupby(g.t//20).indices.values():
            score=np.einsum('ij,i->j',xx[ix],res[ix],optimize=False);variance+=float(np.sum(score*bread0))**2
        se=float(np.sqrt(variance));assert np.isfinite(se)
        regs.append(dict(route=new,baseline=base,status='DESCRIPTIVE_FIXED_REGRESSION',n=len(g),prior_rows=prior,missing_or_no_same_day_support=prior-len(g),treated_r10_coefficient=coef[0],block20_se=se,ci_low=coef[0]-1.96*se,ci_high=coef[0]+1.96*se,controls='same-day demean; board; industry; prior30 return/MAX/volatility; beta120; liquidity20; PIT-B circulating cap',target='CAUSAL_PRICE_COORDINATE_DIAGNOSTIC_NOT_CASH_PNL'))
    pd.DataFrame(regs).to_csv(HERE/'factor_incremental_diagnostic.csv',index=False)
    ep=pd.read_parquet(OUT/'episodes.parquet');ep.groupby(['route','status']).size().rename('episodes').to_csv(STATS/'parent_episode_status.csv')
    # All D09 frozen episodes; both arms may have no trigger, no fill, or censored outcome.
    paired=[]
    for r in ep[ep.route=='D09_EPISODE'].to_dict('records'):
        j=int(r['j']);row=dict(setup_id=r['setup_id'],j=j,formation_t=r['formation_t'],status=r['status'],advance_t=r['advance_t'],breakout_t=r['breakout_t'])
        for arm,field,L in [('advance','advance_t',r['U']+.1*r['A']),('breakout','breakout_t',r['U']+.5*r['A'])]:
            t=r[field];fill=False;rr=np.nan
            if pd.notna(t):
                e=int(t)+1
                if e<n:
                    px=np.ceil(a['open'][e,j]*1.0005*100-1e-8)/100;fac=a['factor'][e,j];fill=bool(np.isfinite(px+fac) and a['hard_valid'][e,j]==1 and a['buy_blocked_open'][e,j]==0 and px*fac<=L+1e-8 and a['open'][e,j]<a['up_limit_price'][e,j]-1e-6)
                    if fill and e+10<n:rr=a['coord'][e+10,j]/(px*fac)-1
            row[arm+'_fill']=fill;row[arm+'_r10']=rr
        paired.append(row)
    pe=pd.DataFrame(paired);parquet(STATS/'d09_all_episode_pairing.parquet',pe);pe.groupby(['advance_fill','breakout_fill']).agg(episodes=('j','size'),advance_mean=('advance_r10','mean'),breakout_mean=('breakout_r10','mean')).to_csv(STATS/'d09_episode_pair_summary.csv')
    # Corroboration and route overlap are descriptive counts, not independent sources of capital.
    sets={r:set(zip(g.t,g.j)) for r,g in ev.groupby('route')};overlap=[]
    for r,s1 in sets.items():
        for b,s2 in sets.items():overlap.append(dict(route=r,other=b,same_day_stock_intersection=len(s1&s2),jaccard=len(s1&s2)/len(s1|s2)))
    pd.DataFrame(overlap).to_csv(STATS/'route_signal_overlap.csv',index=False)
    dump(HERE/'EVENT_ANALYSIS_MANIFEST.json',dict(source=sha(__file__),all_signal_rows=len(ev),all_D09_episodes=len(pe),sample_cutoff='2023-12-31',diagnostic_return_grade='CAUSAL_PRICE_COORDINATE_NOT_REALIZED_CASH_PNL',files={str(p):sha(p) for p in [STATS/'signal_event_diagnostics.parquet',STATS/'d09_all_episode_pairing.parquet',HERE/'factor_incremental_diagnostic.csv',HERE/'route_event_summary.csv']}))
    print('EVENT_ANALYSIS_COMPLETE',len(ev),len(pe),flush=True)
if __name__=='__main__':main()
