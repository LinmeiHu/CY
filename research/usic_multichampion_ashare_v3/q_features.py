"""Q3/Q4 features from prior daily history plus a validated 14:25 minute prefix."""
import json,time
import numpy as np
import pandas as pd
import duckdb
from .common import HERE,OUT,CACHE,sha,dump,parquet,rank
from .features import Features,smooth
from .legacy_common import pivots

def prior_states(m):
    dest=OUT/'q_prior_states.parquet'
    if dest.exists():return pd.read_parquet(dest)
    c=m.a['coord'];n,z=c.shape;v=np.isfinite(m.a['step']);count=pd.DataFrame(v).rolling(252).sum().to_numpy();r252=c/np.roll(c,252,axis=0)-1;r252[:252]=np.nan;r252[count!=252]=np.nan
    rs252=np.full_like(c,np.nan)
    for b in ['MAIN','CHINEXT','STAR']:
        ids=np.flatnonzero(np.array(m.boards)==b);rs252[:,ids]=pd.DataFrame(r252[:,ids]).rank(axis=1,pct=True).to_numpy()
    # At each T, reference eligibility is frozen at T-1; T volume/close never enter it.
    rs=np.full_like(c,np.nan);retA=c/np.roll(c,30,axis=0)-1;eligible=np.zeros_like(c,dtype=bool)
    for j in range(z):
        if m.boards[j]=='UNSUPPORTED':continue
        x=m.symbol(j);cum=np.r_[0,np.cumsum(~v[:,j])]
        for t in range(283,n):
            q=t-31
            eligible[t,j]=count[q,j]==252 and cum[t]==cum[t-60] and x['good'][t-1] and m.a['is_st'][t-1,j]==0
    for t in range(283,n):
        for b in ['MAIN','CHINEXT','STAR']:
            ids=np.flatnonzero(eligible[t]&(np.array(m.boards)==b));rr=rank(pd.Series(retA[t-31,ids]));rs[t,ids]=rr.to_numpy()
    rows=[];t0=time.time()
    for j in range(z):
        if m.boards[j]=='UNSUPPORTED':continue
        x=m.symbol(j);cc=x['c'];hh=x['h'];ll=x['l'];fac=x['factor'];tr=np.maximum(hh-ll,np.maximum(abs(hh-np.r_[np.nan,cc[:-1]]),abs(ll-np.r_[np.nan,cc[:-1]])));atr=pd.Series(tr).rolling(20).mean().to_numpy()
        ma={k:pd.Series(cc).rolling(k).mean().to_numpy() for k in [50,150,200]};lo=pd.Series(ll).rolling(252).min().to_numpy();hi=pd.Series(hh).rolling(252).max().to_numpy()
        long=(cc>ma[50])&(ma[50]>ma[150])&(ma[150]>ma[200])&(ma[200]>np.roll(ma[200],20))&(cc>=1.3*lo)&(cc>=.75*hi)&(rs252[:,j]>=.7)&(count[:,j]==252)
        mult=np.where(x['good']&np.isfinite(m.a['share_multiplier'][:,j]),m.a['share_multiplier'][:,j],1.);vv=m.a['volume'][:,j]/np.cumprod(mult)
        for t in np.flatnonzero(eligible[:,j]&(rs[:,j]>=.7)):
            if m.dates[t]<'2020-01-01':continue
            q=t-31;start=q-30;A=atr[q]
            if not np.isfinite(A) or A<=0 or not np.all(np.isfinite(m.a['step'][q-119:q+1,j])):continue
            ar=cc[q]/cc[start]-1;log=np.diff(np.log(cc[start:q+1]));pos=log[log>0]
            if ar<=0 or not len(pos):continue
            if np.median(vv[t-30:t-10])<=0 or np.median(vv[t-20:t])<=0:continue
            U=np.max(hh[t-5:t]);FL=np.min(ll[t-5:t]);reason,legs,amb=pivots(hh[t-30:t],ll[t-30:t],vv[t-30:t]);guard=reason=='PASS'
            rows.append(dict(t=int(t),j=j,symbol=m.symbols[j],board=m.boards[j],factor=fac[t-1],U=U,S0=FL-.1*A,a0=A,FL=FL,RS=rs[t,j],P1=np.mean(1-cc[start+1:q+1]/np.maximum.accumulate(cc[start:q+1])[1:]),P2=np.sort(pos)[-3:].sum()/pos.sum(),long=bool(long[q] and long[t-1]),guard=guard,V1=legs[-1]['depth']/legs[0]['depth'] if guard else np.nan,V2=(U-FL)/A,V3=max(0,np.max(hh[t-30:t])-FL)/A,industry=int(m.a['industry'][t-1,j])))
        if j%500==0:print('Q_PRIOR',j,len(rows),round(time.time()-t0),flush=True)
    f=pd.DataFrame(rows);g=f.groupby(['t','board']);f['Path']=(g.P1.transform(lambda x:rank(x,True))+g.P2.transform(lambda x:rank(x,True)))/2
    sub=f[f.guard];g=sub.groupby(['t','board']);f.loc[sub.index,'VCP']=sum(g[v].transform(lambda x:rank(x,True)) for v in ['V1','V2','V3'])/3
    f['score']=.5*f.RS+.25*f.Path+.25*f.VCP
    parquet(dest,f);return f

def main():
    m=Features();sy={s:i for i,s in enumerate(m.symbols)};dates={d:i for i,d in enumerate(m.dates)};n,z=m.a['coord'].shape
    prior=prior_states(m);states=prior[prior.long&prior.guard].copy();parquet(OUT/'q3_prior_valid_states.parquet',states)
    atr=np.full((n,z),np.nan);elig=np.zeros((n,z),bool)
    for j in range(z):
        if m.boards[j]=='UNSUPPORTED':continue
        x=m.symbol(j);atr[:,j]=x['atr']
        for t in range(283,n):elig[t,j]=x['hist'][t-31] and x['good'][t-1] and m.a['is_st'][t-1,j]==0 and np.all(x['good'][t-90:t])
    rows=[];coverage=[];prefixes=[]
    for p in sorted((OUT/'minute').glob('prefix_*.parquet')):
        f=pd.read_parquet(p);f['j']=f.symbol.map(sy);f['t']=f.trade_date.astype(str).str[:10].map(dates);before=len(f);f=f[f.j.notna()&f.t.notna()].copy();f['j']=f.j.astype(int);f['t']=f.t.astype(int)
        ts=f.t.to_numpy();js=f.j.to_numpy();valid=(f.n_prefix==206)&(f.n_distinct==206)&(f.invalid_clock==0)&f.valid_ohlcv.fillna(False)&(f.close1425>0)&(f.volume_prefix>0)&elig[ts,js]
        coverage.append(dict(month=p.stem[-6:],source_rows=before,daily_identity_rows=len(f),valid_prior_and_prefix=int(valid.sum()),missing_or_ineligible=int((~valid).sum())))
        f=f[valid].copy();ts=f.t.to_numpy();js=f.j.to_numpy()
        # The date-effective factor is algebraically prior coord / raw ex-reference, independent of today's close.
        factor=m.a['coord'][ts-1,js]/((m.a['close'][ts-1,js]-m.a['cash_per_share'][ts,js])/m.a['share_multiplier'][ts,js])
        bridge=np.isfinite(factor)&(factor>0)&(m.a['corporate_action_blocking'][ts,js]==0)&(m.a['is_st'][ts,js]==0)&~(np.isfinite(m.a['rights_ratio'][ts,js])&(m.a['rights_ratio'][ts,js]!=0))
        # Explicit cash/share adjustment may alter the raw exchange reference beyond preclose convention.
        f['factor']=factor;f['A']=atr[ts-1,js]/factor;f['bridge_identity']=bridge
        f=f[f.bridge_identity&f.A.gt(0)].copy();prefixes.append(f[['t','j','factor','open_prefix','high_prefix','low_prefix','close1425']])
        op=f.open_prefix;high=f.morning_high;c=f.close1425;A=f.A
        base=(f.morning_close-op>=A)&(high-op>=1.5*A)&(c>=op+.5*(high-op))&(c<=high+.5*A)
        enhanced=base&(f.flag_high-f.flag_low<=.75*A)&(f.flag_low>=high-A)&(f.width_first>f.width_last)&(c>f.prior25_high)&(c<=f.prior25_high+.5*A)
        q=f[base].copy();q['enhanced']=enhanced[base];q['score_raw']=(q.close1425-q.open_prefix)/q.A;q['limit']=q.morning_high+.5*q.A;q['U']=q.morning_high;q['S0']=q.morning_high-q.A;q['a0']=q.A;q['route']='Q4';q['industry']=m.a['industry'][q.t.to_numpy()-1,q.j.to_numpy()];rows.append(q)
        print('Q_MINUTE',p.stem,len(f),len(q),int(enhanced.sum()),flush=True)
    prefixes=pd.concat(prefixes,ignore_index=True);parquet(OUT/'q_prefix_marks.parquet',prefixes)
    f=pd.concat(rows,ignore_index=True);f['score']=f.groupby('t').score_raw.transform(rank)
    for k,g in [('BASE',f),('ENHANCED',f[f.enhanced])]:
        g=g.drop(columns=[c for c in g if c.startswith('exec_')]).copy();g['setup_id']='Q4:'+g.symbol+':'+g.t.astype(str);g['decision_at']=[m.dates[t]+'T14:25:00+08:00' for t in g.t];g['known_at']=g.decision_at;g['known_t']=g.t;g['formation_at']=[m.dates[t]+'T11:30:00+08:00' for t in g.t];parquet(OUT/f'Q4_{k}_signals.parquet',g)
    # Frozen ten-session episodes, including no-trigger and structurally failed observations.
    q3=[];episodes=[];pg={int(j):g.set_index('t') for j,g in prefixes.groupby('j')}
    for j,g in states.groupby('j'):
        end=-1;j=int(j);p=pg.get(j)
        if p is None:continue
        for r in g.sort_values('t').to_dict('records'):
            t=int(r['t'])
            if t<=end:continue
            end=t+9;U=r['U'];S=r['S0'];A=r['a0'];ep=dict(route='Q3',j=j,formation_t=t,expiry_t=end,advance_t=None,status='NO_TRIGGER',setup_id=f'Q3:{m.symbols[j]}:{t}')
            for e in range(t,min(end+1,n)):
                if e not in p.index:continue
                px=p.loc[e];fac=px.factor;close=px.close1425*fac
                if close<S:ep.update(status='STRUCTURE_INVALID',invalidated_t=e);break
                if U-.3*A<=close<=U and close>px.open_prefix*fac and px.low_prefix*fac>=r['FL']:
                    q3.append(dict(route='Q3',t=e,j=j,symbol=m.symbols[j],factor=fac,U=U/fac,limit=(U+.1*A)/fac,S0=S/fac,a0=A/fac,score=r['score'],industry=int(r['industry']),setup_id=ep['setup_id'],formation_t=t,expiry_t=end,decision_at=m.dates[e]+'T14:25:00+08:00',known_at=m.dates[t-1]+'T15:00:00+08:00'));ep.update(status='TRIGGERED',advance_t=e);break
            episodes.append(ep)
    parquet(OUT/'Q3_signals.parquet',pd.DataFrame(q3));parquet(OUT/'Q3_episodes.parquet',pd.DataFrame(episodes));pd.DataFrame(coverage).to_csv(HERE/'minute_coverage.csv',index=False)
    files=[OUT/'q_prior_states.parquet',OUT/'q_prefix_marks.parquet',OUT/'Q3_signals.parquet',OUT/'Q4_BASE_signals.parquet',OUT/'Q4_ENHANCED_signals.parquet']
    dump(HERE/'Q_FEATURE_MANIFEST.json',dict(source_hash=sha(__file__),files={str(p):sha(p) for p in files},q3_signals=len(q3),q4_base=len(f),q4_enhanced=int(f.enhanced.sum()),source_cutoff='2023-12-31',no_account_outcomes_read=True))
if __name__=='__main__':main()
