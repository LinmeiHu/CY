"""Bounded CY-006 input binding and task-only shared feature cache."""
import json,time
from pathlib import Path
import duckdb,numpy as np,pandas as pd
from .common import HERE,OUT,INV,sha,dump,scenarios,pivots,rank

def bound_inputs():
    OUT.mkdir(parents=True,exist_ok=True)
    reg=json.loads((HERE.parents[1]/'configs/data_asset_registry.json').read_text())
    invpath=INV/'CY-006-pit-b-daily-v2-2018-2026-20260821.json'
    assert sha(invpath)=='de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2'
    inv=json.loads(invpath.read_text()); files=[]
    for x in inv['files']:
        year=int(x['path'].split('=')[1][:4])
        if not 2018<=year<=2023:continue
        p=Path(inv['root'])/x['path'];assert sha(p)==x['sha256'],str(p);files.append(dict(x,absolute_path=str(p)))
    assert len(files)==6
    dump(HERE/'input_binding.json',dict(files=files,registry_hash=sha(HERE.parents[1]/'configs/data_asset_registry.json'),daily_manifest_hash=sha(invpath),permissions='2018-2019 warmup; 2020-2023 consumed research; 2024+ and CY-011 excluded'))
    dump(HERE/'scenarios.json',scenarios())
    return [x['absolute_path'] for x in files]

def roll(a,n,method='mean'):
    return getattr(pd.DataFrame(a).rolling(n,min_periods=n),method)().to_numpy()
def lag(a,n=1):
    b=np.full_like(a,np.nan,dtype=float);b[n:]=a[:-n];return b

def prepare():
    files=bound_inputs();con=duckdb.connect();con.execute("SET threads=1");con.execute("SET memory_limit='3GB'")
    con.from_parquet(files).create_view('raw')
    dates=con.sql('select distinct trade_date from raw order by trade_date').fetchdf().trade_date
    symbols=con.sql('select distinct symbol from raw order by symbol').fetchdf().symbol.tolist()
    assert dates.max()<=pd.Timestamp('2023-12-31')
    ds=pd.Index(dates);ss=pd.Index(symbols);shape=(len(ds),len(ss));data={}
    fields=['open','high','low','close','preclose','volume','amount','up_limit_price','down_limit_price','share_multiplier','cash_per_share','rights_ratio','corporate_action_count']
    bools=['hard_valid','trade_status','is_st','buy_blocked_open','sell_blocked_open','current_day_data_tradable','corporate_action_blocking']
    for f in fields+bools:data[f]=np.full(shape,np.nan)
    ind=np.full(shape,-1,dtype=np.int16);industry_names=[];imd={}
    audit=[]
    for file in files:
        d=con.execute('select * from read_parquet(?)',[file]).fetchdf();i=ds.get_indexer(d.trade_date);j=ss.get_indexer(d.symbol)
        assert not d.duplicated(['trade_date','symbol']).any()
        causal=(d.available_at<=d.decision_at)&d.snapshot_id.notna()
        assert not (d.hard_valid&~causal).any()
        for f in fields+bools:data[f][i,j]=pd.to_numeric(d[f],errors='coerce').to_numpy(dtype=float,na_value=np.nan)
        ok=d.industry_valid&(d.source_notice_date<=d.trade_date)&d.industry.notna()&~d.industry.isin(['','UNKNOWN'])
        for s in d.loc[ok,'industry'].unique():
            if s not in imd:imd[s]=len(industry_names);industry_names.append(s)
        ind[i[ok],j[ok]]=d.loc[ok,'industry'].map(imd).to_numpy(dtype=np.int16)
        audit.append(dict(year=str(d.trade_date.min().year),rows=len(d),symbols=d.symbol.nunique(),hard_valid=int(d.hard_valid.sum()),industry_valid=int(ok.sum())))
        print('INPUT',audit[-1],flush=True)
    del d
    data['industry']=ind
    c=data['close'];h=data['high'];l=data['low'];v=data['volume'];mult=data['share_multiplier'];cash=data['cash_per_share']
    good=(data['hard_valid']==1)&(np.nan_to_num(data['rights_ratio'],nan=0)==0)&(data['corporate_action_blocking']==0)&(c>0)
    # causal forward coordinate. Invalid steps break every required historical window.
    prev=lag(c);reference=(prev-cash)/mult
    step=c/reference-1;validstep=good&(lag(good)==1)&(reference>0)&np.isfinite(step)
    step[~validstep]=np.nan
    coord=np.empty(shape);coord[0]=np.where(c[0]>0,c[0],1.)
    sf=np.ones(shape)
    for t in range(1,len(ds)):
        coord[t]=coord[t-1]*np.where(validstep[t],1+step[t],1.)
        sf[t]=sf[t-1]*np.where(good[t]&np.isfinite(mult[t])&(mult[t]>0),mult[t],1)
    factor=coord/c;ch=h*factor;cl=l*factor;co=data['open']*factor
    # Known date-effective shares only; future splits never change old volume scores.
    vol=v/sf;coord[~good]=np.nan;ch[~good]=np.nan;cl[~good]=np.nan
    count252=roll(validstep.astype(float),252,'sum')
    ret252=coord/lag(coord,252)-1;ret252[count252<252]=np.nan
    first_seen=np.argmax(np.isfinite(c)&(c>0),axis=0)
    boards=np.array(['STAR' if s.startswith('688') else 'CHINEXT' if s.startswith(('300','301')) else 'MAIN' if s.startswith(('60','00')) else 'UNSUPPORTED' for s in symbols])
    rs252=np.full(shape,np.nan)
    for b in ['MAIN','CHINEXT','STAR']:
        ix=np.where(boards==b)[0];rs252[:,ix]=pd.DataFrame(ret252[:,ix]).rank(axis=1,pct=True).to_numpy()
    ma={n:roll(coord,n) for n in [10,20,50,60,120,150,200]}
    low252=roll(cl,252,'min');high252=roll(ch,252,'max')
    long=(coord>ma[50])&(ma[50]>ma[150])&(ma[150]>ma[200])&(ma[200]>lag(ma[200],20))
    medium=(coord>ma[20])&(ma[20]>ma[60])&(ma[60]>ma[120])&(ma[120]>lag(ma[120],20))
    both=(coord>=1.3*low252)&(coord>=.75*high252)&(rs252>=.7)&(count252==252)
    long&=both;medium&=both
    # Equal weight prior valid universe, missing priced separately; suspension returns remain real quoted returns.
    market=np.nanmean(np.where((lag(good)==1)&(boards[None,:]!='UNSUPPORTED'),step,np.nan),axis=1);market[0]=0
    market_index=np.cumprod(1+np.nan_to_num(market,nan=0))
    ms=pd.Series(market_index).rolling(60).mean();gate=~((market_index<ms)&(ms<ms.shift(20))).to_numpy()
    breadth=np.nanmean(np.where(good,coord>ma[20],np.nan),axis=1)
    data.update(coord=coord,factor=factor,ma10=ma[10],market=market,market_gate=gate,breadth=breadth,step=step)
    for f,a in data.items():np.save(OUT/(f+'.npy'),a)
    dump(OUT/'axes.json',dict(dates=[str(x.date()) for x in ds],symbols=symbols,boards=boards.tolist(),industries=industry_names))
    pd.DataFrame(audit).to_csv(HERE/'input_coverage.csv',index=False)
    pd.DataFrame(dict(date=ds,market_return=market,index=market_index,gate=gate,breadth=breadth,valid_returns=(np.isfinite(step)&(boards[None,:]!='UNSUPPORTED')).sum(axis=1),prior_members=((lag(good)==1)&(boards[None,:]!='UNSUPPORTED')).sum(axis=1))).to_csv(OUT/'market.csv',index=False)
    tr=np.maximum(ch-cl,np.maximum(abs(ch-lag(coord)),abs(cl-lag(coord))))
    atr=roll(tr,20);amount20=roll(data['amount'],20)
    ret60=coord/lag(coord,60)-1
    # freeze feature collection before any outcome is computed
    for a,w,family in [(30,5,'OLD_30_5'),(20,3,'OLD_20_3'),(40,8,'OLD_40_8'),(30,30,'N')]:
        frames=[];t0=time.time()
        for j,sym in enumerate(symbols):
            if boards[j]=='UNSUPPORTED':continue
            rows=[]
            cc=coord[:,j];hh=ch[:,j];ll=cl[:,j];vv=vol[:,j];rr=step[:,j]
            for t in range(max(283 if family=='N' else 120,a+w+21),len(ds)):
                if ds[t]<pd.Timestamp('2020-01-01') or t-first_seen[j]<120 or not good[t,j] or data['is_st'][t,j]!=0:continue
                q=t-w-1;start=q-a
                if family=='N' and count252[q,j]!=252:continue
                if not np.all(validstep[start+1:t,j]) or not np.isfinite(atr[q,j]) or atr[q,j]<=0:continue
                ar=cc[q]/cc[start]-1
                if ar<=0:continue
                A=cc[start:q+1];log=np.log(A[1:]/A[:-1]);positive=log[log>0]
                if not len(positive) or positive.sum()<=0:continue
                P1=np.mean(1-A[1:]/np.maximum.accumulate(A)[1:]);P2=np.sort(positive)[-3:].sum()/positive.sum()
                W=slice(t-w,t);F=slice(t-5,t) if family=='N' else W
                U=hh[F].max();FL=ll[F].min();a0=atr[q,j]
                row=dict(t=t,j=j,symbol=sym,board=boards[j]+('_20' if boards[j]=='CHINEXT' and ds[t]>=pd.Timestamp('2020-08-24') else '_10' if boards[j]=='CHINEXT' else ''),retA=ar,P1=P1,P2=P2,C1=(hh[W].max()-ll[W].min())/a0,C2=max(0,hh[start+1:q+1].max()-ll[W].min())/a0,U=U/factor[t,j],limit=(U+.5*a0)/factor[t,j],S0=(FL-.1*a0)/factor[t,j],a0=a0/factor[t,j],factor=factor[t,j],breakout=cc[t]>U,amount20=amount20[t-1,j],volatility=np.std(rr[start+1:q+1]),MAX=np.max(rr[start+1:q+1]),ret60=ret60[t-1,j],ret252=ret252[t-1,j],industry=int(ind[t-1,j]))
                if family=='N':
                    rpre=rr[q-119:q+1];mpre=market[q-119:q+1]
                    if not np.all(np.isfinite(rpre)) or np.var(mpre)<=0:continue
                    beta=np.mean((rpre-rpre.mean())*(mpre-mpre.mean()))/np.var(mpre)
                    down=market[t-w:t]<0;support=int(down.sum());res=np.median(rr[t-w:t][down]-beta*market[t-w:t][down]) if support>=5 else 0.
                    med1=np.median(vv[t-w:t-w+20]);med2=np.median(vv[t-20:t])
                    if med1<=0 or med2<=0 or not np.isfinite(vv[t]):continue
                    reason,legs,amb=pivots(hh[W],ll[W],vv[W]);guard=reason=='PASS'
                    row.update(long=bool(long[q,j] and long[t-1,j]),medium=bool(medium[q,j] and medium[t-1,j]),beta=beta,resilience=res,mr_support=support,market_gate=bool(gate[t-1]),Q1=np.median(vv[t-5:t])/med1,Q2=vv[t]/med2,VCP_GUARD=guard,V1=legs[-1]['depth']/legs[0]['depth'] if guard else np.nan,V2=(U-FL)/a0,V3=max(0,hh[W].max()-FL)/a0,pivot_reason=reason,legs=json.dumps(legs),ambiguous=json.dumps(amb))
                rows.append(row)
            if rows:frames.append(pd.DataFrame(rows))
            if j%500==0:print('FEATURES',family,j,len(symbols),'secs',int(time.time()-t0),flush=True)
        frame=pd.concat(frames,ignore_index=True);del frames
        group=frame.groupby(['t','board'])
        # Positive-only pool would incorrectly inflate top 30%; percentile computed against all eligible history returns below.
        allret=coord/lag(coord,a)-1
        # A return evaluated at q; eligibility as of T matches the collection above. Include nonpositive eligible observations in denominator.
        ranks={}
        for t in frame.t.unique():
            q=t-w-1;start=q-a
            eligible=good[t]&((t-first_seen)>=120)&(data['is_st'][t]==0)&(boards!='UNSUPPORTED')&np.isfinite(atr[q])&(atr[q]>0)&np.all(validstep[start+1:t],axis=0)
            if family=='N':eligible&=(count252[q]==252)
            for b in ['MAIN','CHINEXT','STAR']:
                ids=np.where(eligible&(boards==b))[0];vals=pd.Series(allret[q,ids],index=ids);ranks.update({(int(t),int(j)):float(r) for j,r in rank(vals).items()})
        frame['RS']= [ranks[(int(t),int(j))] for t,j in zip(frame.t,frame.j)]
        frame=frame[frame.RS>=.7].copy();group=frame.groupby(['t','board'])
        for f in ['P1','P2','C1','C2']:frame[f+'_score']=group[f].transform(lambda s:rank(s,True))
        frame['Path']=(frame.P1_score+frame.P2_score)/2;frame['Consolidation']=(frame.C1_score+frame.C2_score)/2
        if family=='N':
            g=frame.loc[frame.VCP_GUARD].groupby(['t','board'])
            for f in ['V1','V2','V3']:frame.loc[frame.VCP_GUARD,f+'_score']=g[f].transform(lambda s:rank(s,True))
            frame['VCP']=frame[['V1_score','V2_score','V3_score']].mean(axis=1)
            frame['MR']=group.resilience.transform(rank);frame.loc[frame.mr_support<5,'MR']=.5
            frame['Volume']=(group.Q1.transform(lambda s:rank(s,True))+group.Q2.transform(rank))/2
            frame['Q1_normalized']=frame.Q1/group.Q1.transform('median');frame['Q2_normalized']=frame.Q2/group.Q2.transform('median')
            # PIT industry full eligible members, not only strong candidate selection.
            indscore={}
            for t in frame.t.unique():
                vals=pd.DataFrame(dict(j=np.arange(len(ss)),industry=ind[t-1],r=ret60[t-1]))
                vals=vals[(vals.industry>=0)&vals.r.notna()&good[t-1]&(boards!='UNSUPPORTED')&np.isfinite(step[t-60:t]).all(axis=0)];g=vals.groupby('industry').r
                vals['n']=g.transform('size');vals['ir']=(g.transform('sum')-vals.r)/(vals.n-1)
                means=vals[vals.n>=5].groupby('industry').r.mean().sort_values().to_numpy()
                vals=vals[vals.n>=5]
                vals['score']=np.searchsorted(means,vals.ir,side='right')/len(means) if len(means) else np.nan
                indscore.update({(int(t),int(j)):float(x) for j,x in zip(vals.j,vals.score)})
            frame['Industry']=[indscore.get((int(t),int(j)),np.nan) for t,j in zip(frame.t,frame.j)]
        funnel=frame.groupby('t').agg(strong=('j','size'),breakout=('breakout','sum'))
        if family=='N':
            funnel['long']=frame.groupby('t').long.sum();funnel['vcp']=frame.groupby('t').VCP_GUARD.sum()
        funnel.to_csv(OUT/(family+'_funnel.csv'))
        frame.to_parquet(OUT/(family+'_candidates.parquet'),index=False)
        frame[frame.breakout].to_parquet(OUT/(family+'_signals.parquet'),index=False)
        print('COMPLETE_FEATURE',family,len(frame),int(frame.breakout.sum()),flush=True)
    dump(HERE/'feature_manifest.json',dict(artifacts=[dict(path=str(p),sha256=sha(p),size=p.stat().st_size) for p in sorted(OUT.glob('*')) if p.is_file() and (p.suffix=='.npy' or p.name in ['axes.json','market.csv'] or p.name.endswith(('_candidates.parquet','_signals.parquet','_funnel.csv')))],outcomes_read=False))
if __name__=='__main__':prepare()
