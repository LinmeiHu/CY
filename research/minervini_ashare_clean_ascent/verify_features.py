"""Bounded raw-prefix reconstruction, complete-cross-section membership and temporal checks."""
import json
import numpy as np
import pandas as pd
from .common import HERE,OUT,dump,pivots,rank

def price_prefix(raw,last):
    a={k:v[:last+1] for k,v in raw.items()};c=a['close'];mult=a['share_multiplier']
    good=(a['hard_valid']==1)&(np.nan_to_num(a['rights_ratio'],nan=0)==0)&(a['corporate_action_blocking']==0)&(c>0)
    coord=np.empty_like(c);coord[0]=np.where(c[0]>0,c[0],1.);sf=np.ones_like(c);step=np.full_like(c,np.nan)
    for t in range(1,len(c)):
        ref=(c[t-1]-a['cash_per_share'][t])/mult[t];r=c[t]/ref-1;ok=good[t]&good[t-1]&(ref>0)&np.isfinite(r)
        step[t]=np.where(ok,r,np.nan);coord[t]=coord[t-1]*np.where(ok,1+r,1.);sf[t]=sf[t-1]*np.where(good[t]&np.isfinite(mult[t])&(mult[t]>0),mult[t],1.)
    factor=coord/c;coord[~good]=np.nan
    return coord,factor,step,sf,good

def run():
    raw={f:np.load(OUT/(f+'.npy'),mmap_mode='r') for f in ['close','high','low','volume','amount','hard_valid','rights_ratio','corporate_action_blocking','share_multiplier','cash_per_share','is_st']}
    axes=json.loads((OUT/'axes.json').read_text());boards=np.array(axes['boards']);dates=axes['dates'];saved=np.load(OUT/'coord.npy',mmap_mode='r');market_saved=np.load(OUT/'market.npy',mmap_mode='r');frame=pd.read_parquet(OUT/'N_candidates.parquet');rows=[]
    first=np.argmax(np.isfinite(raw['close'])&(raw['close']>0),axis=0)
    for family in ['OLD_30_5','OLD_20_3','OLD_40_8','N']:
        f=pd.read_parquet(OUT/(family+'_candidates.parquet'));assert ((f.t.to_numpy()-first[f.j.to_numpy()])>=120).all(),family
    for day in ['2020-03-31','2021-06-30','2022-09-30','2023-12-20']:
        t=dates.index(day);c,factor,step,sf,good=price_prefix(raw,t);np.testing.assert_allclose(c,saved[:t+1],rtol=1e-12,atol=1e-10,equal_nan=True)
        previous=np.vstack([np.zeros((1,len(boards)),bool),good[:-1]])
        with np.errstate(invalid='ignore'):
            market=np.nanmean(np.where(previous&(boards[None,:]!='UNSUPPORTED'),step,np.nan),axis=1)
        market[0]=0;np.testing.assert_allclose(market,market_saved[:t+1],rtol=1e-12,atol=1e-12,equal_nan=True)
        hh=raw['high'][:t+1]*factor;ll=raw['low'][:t+1]*factor;hh[~good]=np.nan;ll[~good]=np.nan;vv=raw['volume'][:t+1]/sf
        q=t-31;start=t-61;tr=np.maximum(hh[q-19:q+1]-ll[q-19:q+1],np.maximum(abs(hh[q-19:q+1]-c[q-20:q]),abs(ll[q-19:q+1]-c[q-20:q])));atr=tr.mean(axis=0)
        eligible=good[t]&(raw['is_st'][t]==0)&(boards!='UNSUPPORTED')&((t-first)>=120)&np.isfinite(atr)&(atr>0)&np.isfinite(step[start+1:t]).all(axis=0)&np.isfinite(step[q-251:q+1]).all(axis=0)
        gains=c[q]/c[start]-1;rs=np.full(len(boards),np.nan)
        for b in ['MAIN','CHINEXT','STAR']:
            ix=np.where(eligible&(boards==b))[0];rs[ix]=rank(pd.Series(gains[ix])).to_numpy()
        long={};medium={}
        for z in [q,t-1]:
            histvalid=np.isfinite(step[z-251:z+1]).all(axis=0);r252=c[z]/c[z-252]-1;r252[~histvalid]=np.nan;ranks=np.full(len(boards),np.nan)
            for b in ['MAIN','CHINEXT','STAR']:
                ix=np.where(boards==b)[0];ranks[ix]=pd.Series(r252[ix]).rank(pct=True).to_numpy()
            both=(c[z]>=1.3*np.min(ll[z-251:z+1],axis=0))&(c[z]>=.75*np.max(hh[z-251:z+1],axis=0))&(ranks>=.7)&histvalid
            for windows,dest in [([50,150,200],long),([20,60,120],medium)]:
                a,b,w=windows;ma=lambda n,at:c[at-n+1:at+1].mean(axis=0)
                dest[z]=both&(c[z]>ma(a,z))&(ma(a,z)>ma(b,z))&(ma(b,z)>ma(w,z))&(ma(w,z)>ma(w,z-20))
        records=[]
        for j in np.where(eligible&(gains>0)&(rs>=.7))[0]:
            med1=np.median(vv[t-30:t-10,j]);med2=np.median(vv[t-20:t,j]);rpre=step[q-119:q+1,j];mpre=market[q-119:q+1]
            if med1<=0 or med2<=0 or not np.isfinite(vv[t,j]) or not np.isfinite(rpre).all() or np.var(mpre)<=0:continue
            A=c[start:q+1,j];log=np.log(A[1:]/A[:-1]);positive=log[log>0];beta=np.mean((rpre-rpre.mean())*(mpre-mpre.mean()))/np.var(mpre);down=market[t-30:t]<0
            reason,legs,_=pivots(hh[t-30:t,j],ll[t-30:t,j],vv[t-30:t,j]);U=hh[t-5:t,j].max();FL=ll[t-5:t,j].min()
            records.append(dict(j=j,board=boards[j],RS=rs[j],P1=np.mean(1-A[1:]/np.maximum.accumulate(A)[1:]),P2=np.sort(positive)[-3:].sum()/positive.sum(),long=long[q][j]&long[t-1][j],medium=medium[q][j]&medium[t-1][j],beta=beta,resilience=np.median(step[t-30:t,j][down]-beta*market[t-30:t][down]) if down.sum()>=5 else 0.,Q1=np.median(vv[t-5:t,j])/med1,Q2=vv[t,j]/med2,VCP_GUARD=reason=='PASS',breakout=c[t,j]>U,U=U/factor[t,j],limit=(U+.5*atr[j])/factor[t,j],S0=(FL-.1*atr[j])/factor[t,j]))
        expected=pd.DataFrame(records).set_index('j').sort_index();actual=frame[frame.t==t].set_index('j').sort_index();assert expected.index.tolist()==actual.index.tolist(),day
        for col in expected.columns.difference(['board']):np.testing.assert_allclose(expected[col].to_numpy(float),actual[col].to_numpy(float),rtol=1e-9,atol=1e-10,equal_nan=True,err_msg=day+':'+col)
        for b,g in expected.groupby('board'):
            p=(rank(g.P1,True)+rank(g.P2,True))/2;np.testing.assert_allclose(p,actual.loc[g.index,'Path'],rtol=1e-12,atol=1e-12)
        rows.append(dict(date=day,full_universe=len(boards),strong_candidates=len(expected),breakout_signals=int(expected.breakout.sum()),status='PASS_RAW_PREFIX_AND_FULL_CROSS_SECTION'))
    dump(HERE/'raw_prefix_checks.json',dict(status='PASS',snapshots=rows,listing_age_all_four_caches='PASS',scope='raw price chain, ordinary-stock benchmark, complete N cross-section and RS/Path/TT/VCP/MR inputs/volume/trigger/order levels; four dates, not an independent rerun of every date or PIT-A certification'))
    print('RAW_PREFIX_CHECKS_PASS',rows,flush=True)
if __name__=='__main__':run()
