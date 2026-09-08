"""One fixed, causal daily lifecycle representation; no parameter search."""
from pathlib import Path
import hashlib, json
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
CACHE=Path('/Volumes/quant/CY_quant_research/usic_multichampion_ashare_v3/cache')
OUT=Path('/Volumes/quant/CY_quant_research/ashare_strong_stock_lifecycle_v1'); OUT.mkdir(parents=True,exist_ok=True)

def write(name, x):
    p=HERE/name
    if isinstance(x,pd.DataFrame): x.to_csv(p,index=False)
    else: p.write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str)+'\n')

def qbin(s):
    return pd.qcut(s.rank(method='first'),5,labels=False,duplicates='drop')+1 if s.notna().sum()>=10 else pd.Series(np.nan,index=s.index)

def summarise(d, feature, label):
    z=d.dropna(subset=[feature,'fwd10']).copy(); z['quintile']=z.groupby('year')[feature].transform(qbin)
    return z.groupby('quintile',observed=True).agg(observations=('symbol','size'),mean_fwd10=('fwd10','mean'),median_fwd10=('fwd10','median'),mean_mfe10=('mfe10','mean'),mean_mae10=('mae10','mean'),new_high10=('new_high10','mean')).reset_index().assign(mechanism=label,feature=feature)

def main():
    ax=json.loads((CACHE/'axes.json').read_text()); dates=np.array(ax['dates']); symbols=np.array(ax['symbols']); n=len(dates)
    a={k:np.load(CACHE/(k+'.npy'),mmap_mode='r') for k in ['coord','close','high','low','amount','hard_valid','industry','is_st','up_limit_price','preclose','market']}
    c=np.asarray(a['coord'],float); valid=(np.asarray(a['hard_valid'])==1)&(np.asarray(a['is_st'])==0)&np.isfinite(c)&(c>0)&(np.asarray(a['industry'])>=0)
    r20=np.full_like(c,np.nan);r60=np.full_like(c,np.nan); r20[20:]=c[20:]/c[:-20]-1;r60[60:]=c[60:]/c[:-60]-1
    r20[~valid]=np.nan;r60[~valid]=np.nan
    # Daily ranks are representations, not optimized entry filters.
    rs60=pd.DataFrame(r60).rank(axis=1,pct=True).to_numpy(); rs20=pd.DataFrame(r20).rank(axis=1,pct=True).to_numpy()
    m=np.asarray(a['market'],float); mr5=np.full(n,np.nan);mr5[5:]=m[5:]/m[:-5]-1
    mz=pd.Series(mr5).rolling(60,min_periods=60).mean(); ms=pd.Series(mr5).rolling(60,min_periods=60).std(); mz=((pd.Series(mr5)-mz)/ms).to_numpy()
    # Preaggregate each day's historical PIT industry state once. Event-level
    # leave-one-out values below are sums/counts minus the candidate itself.
    ind_all=np.asarray(a['industry'],int); ng=int(ind_all.max())+1
    sec_sum=np.zeros((n,ng)); sec1_sum=np.zeros((n,ng)); sec_count=np.zeros((n,ng)); broad_sum=np.zeros((n,ng))
    ret5=np.full_like(c,np.nan); ret5[5:]=c[5:]/c[:-5]-1
    ma20=np.full_like(c,np.nan)
    for t in range(20,n):
        ma20[t]=np.nanmean(c[t-20:t],axis=0)
        ids=np.where(valid[t]&np.isfinite(ret5[t]))[0]
        np.add.at(sec_sum[t],ind_all[t,ids],ret5[t,ids]); np.add.at(sec1_sum[t],ind_all[t,ids],c[t,ids]/c[t-1,ids]-1); np.add.at(sec_count[t],ind_all[t,ids],1)
        np.add.at(broad_sum[t],ind_all[t,ids],(c[t,ids]>ma20[t,ids]).astype(float))
    sec_ret=np.divide(sec_sum,sec_count,out=np.full_like(sec_sum,np.nan),where=sec_count>0)
    sec1_ret=np.divide(sec1_sum,sec_count,out=np.full_like(sec1_sum,np.nan),where=sec_count>0)
    sec_z=(pd.DataFrame(sec_ret).subtract(pd.DataFrame(sec_ret).rolling(60,min_periods=60).mean()).divide(pd.DataFrame(sec_ret).rolling(60,min_periods=60).std())).to_numpy()
    rows=[]
    # Fixed sparse sampling: each qualifying stock is observed at most once every 20 sessions.
    last=np.full(c.shape[1],-999)
    for t in range(125,n-26):
        if dates[t]<'2020-01-01':
            continue
        leaders=valid[t]&valid[t-5]&(rs60[t-5]>=.70)&(t-last>=20)
        ids=np.where(leaders)[0]
        ind=np.asarray(a['industry'][t],int)
        # sector daily return/breadth computed from only current valid, PIT-mapped names.
        one=np.asarray(c[t]/c[t-1]-1); ma20=np.nanmean(np.stack([c[t-k] for k in range(1,21)]),axis=0)
        for j in ids:
            g=ind[j]; cnt=sec_count[t,g]-1
            if cnt<5: continue
            sr5=(sec_sum[t,g]-ret5[t,j])/cnt; sb=float((broad_sum[t,g]-(c[t,j]>ma20[j]))/cnt)
            sz=sec_z[t,g]
            pressure=(mz[t]<=-1) or (sz<=-1)
            # Past-only OLS sensitivities, with no contemporaneous/future rows in estimation.
            y=c[t-60:t,j]/c[t-61:t-1,j]-1; xm=m[t-60:t]/m[t-61:t-1]-1
            xs=sec1_ret[t-60:t,g]
            ok=np.isfinite(y)&np.isfinite(xm)&np.isfinite(xs)
            if ok.sum()<40: continue
            beta_m,beta_s=np.linalg.lstsq(np.c_[np.ones(ok.sum()),xm[ok],xs[ok]],y[ok],rcond=None)[0][1:]
            actual=one[j]; expected=beta_m*(m[t]/m[t-1]-1)+beta_s*sec1_ret[t,g]; residual=actual-expected
            repair=False
            if pressure:
                repair=any((c[u,j]>c[t,j]) and ((c[u,j]/c[u-1,j]-1)-beta_m*(m[u]/m[u-1]-1)>0) for u in range(t+1,t+6))
            base=t+5; future=c[base+1:base+21,j]/c[base,j]-1
            rec=dict(t=t,date=dates[t],symbol=symbols[j],industry=g,year=int(dates[t][:4]),ret20=r20[t,j],ret60=r60[t,j],rs20=rs20[t,j],rs60=rs60[t,j],sector_ret5=sr5,sector_breadth20=sb,market_ret5=mr5[t],market_pressure_z=mz[t],sector_pressure_z=sz,pressure=pressure,resilience=residual,repair=repair,limit_close=bool(np.isfinite(a['up_limit_price'][t,j]) and abs(a['close'][t,j]-a['up_limit_price'][t,j])<.011),turnover_rel=a['amount'][t,j]/np.nanmedian(a['amount'][t-20:t,j]))
            for h in [5,10,20]:
                x=future[:h];rec[f'fwd{h}']=x[-1] if len(x)==h and np.isfinite(x).all() else np.nan;rec[f'mfe{h}']=np.nanmax(x) if len(x)==h else np.nan;rec[f'mae{h}']=np.nanmin(x) if len(x)==h else np.nan;rec[f'new_high{h}']=float(np.nanmax(c[base+1:base+h+1,j])>c[base,j]) if len(x)==h else np.nan
            rows.append(rec);last[j]=t
    d=pd.DataFrame(rows);d['group']=np.where(~d.pressure,'G0',np.where(d.resilience<=0,'G1',np.where(d.repair,'G3','G2')))
    d.to_parquet(OUT/'strong_stock_panel.parquet',index=False)
    write('STRONG_STOCK_PANEL_MANIFEST.json',dict(status='COMPLETE',observations=len(d),dates=[str(d.date.min()),str(d.date.max())],symbols=int(d.symbol.nunique()),definition='Ret60 cross-sectional percentile >= .70 at t-5; one event per symbol per 20 sessions',outcome_anchor='t+5 close then next session',data_cache=str(CACHE)))
    sector=pd.concat([summarise(d,'sector_breadth20','sector_resonance'),summarise(d,'rs60','stock_leadership')]);write('sector_resonance_summary.csv',sector[sector.mechanism=='sector_resonance']);write('leadership_summary.csv',sector[sector.mechanism=='stock_leadership'])
    pr=d[d.pressure].copy();write('resilience_summary.csv',summarise(pr,'resilience','resilience'))
    seq=pr.groupby('group').agg(observations=('symbol','size'),mean_fwd5=('fwd5','mean'),mean_fwd10=('fwd10','mean'),mean_fwd20=('fwd20','mean'),new_high10=('new_high10','mean'),median_fwd10=('fwd10','median')).reset_index();write('divergence_repair_summary.csv',seq)
    lim=pd.concat([summarise(d,'turnover_rel','turnover'),d.groupby('limit_close').agg(observations=('symbol','size'),mean_fwd10=('fwd10','mean'),mean_mfe10=('mfe10','mean'),mean_mae10=('mae10','mean')).reset_index().assign(mechanism='limit_close',feature='limit_close')]);write('limit_turnover_summary.csv',lim)
    # Simple fixed-effect descriptive association, no feature selection.
    terms=['ret20','ret60','rs20','rs60','sector_ret5','sector_breadth20','resilience']
    x=d.replace([np.inf,-np.inf],np.nan).dropna(subset=['fwd10']+terms).copy(); X=np.c_[np.ones(len(x)),x[terms].to_numpy()]; coef=np.linalg.lstsq(X,x.fwd10,rcond=None)[0];write('incrementality_summary.csv',pd.DataFrame({'term':['intercept']+terms,'coefficient':coef,'observations':len(x)}))
    annual=d.groupby('year').agg(events=('symbol','size'),stocks=('symbol','nunique'),sectors=('industry','nunique'),mean_fwd10=('fwd10','mean'),pressure_events=('pressure','sum')).reset_index()
    for feature, source in [('sector_breadth20',d),('resilience',pr)]:
        gap=[]
        for year,g in source.groupby('year'):
            cut=g[feature].median(); gap.append((year,g.loc[g[feature]>=cut,'fwd10'].mean()-g.loc[g[feature]<cut,'fwd10'].mean()))
        annual=annual.merge(pd.DataFrame(gap,columns=['year',feature+'_high_minus_low_fwd10']),on='year',how='left')
    write('annual_stability.csv',annual)
    # Past-only: 2020 relation signs applied to 2021, then expanding years; median split fixed from past data.
    po=[]
    for feature, source in [('sector_breadth20',d),('resilience',pr)]:
        for y in [2021,2022,2023]:
            train=source[source.year<y]; test=source[source.year==y]; cut=train[feature].median(); po.append(dict(test_year=y,train_end=y-1,feature=feature,high_minus_low_fwd10=test.loc[test[feature]>=cut,'fwd10'].mean()-test.loc[test[feature]<cut,'fwd10'].mean(),train_observations=len(train),test_observations=len(test)))
    write('past_only_reconstruction.csv',pd.DataFrame(po))
    cc=[]
    for feature in ['sector_breadth20','resilience']:
        z=(pr if feature=='resilience' else d).dropna(subset=[feature,'fwd10']);cut=z[feature].median(); z=z[z[feature]>=cut]; total=z.fwd10.sum();
        for group,col in [('stock','symbol'),('date','date'),('sector','industry')]:
            top=z.groupby(col).fwd10.sum().sort_values(ascending=False);cc.append(dict(feature=feature,dimension=group,observations=len(z),top1_contribution=top.iloc[0]/total if total else np.nan,top5_contribution=top.head(5).sum()/total if total else np.nan,mean_fwd10=z.fwd10.mean(),median_fwd10=z.fwd10.median()))
    write('concentration.csv',pd.DataFrame(cc))
    failed=[]
    for f in ['sector_breadth20','resilience','turnover_rel']:
        s=summarise(pr if f=='resilience' else d,f,f); means=s.sort_values('quintile').mean_fwd10.to_list(); failed.append(dict(hypothesis=f,status='DESCRIPTIVE_ONLY',evidence='natural quintile relation recorded; no threshold promotion',monotonic_non_decreasing=all(b>=a for a,b in zip(means,means[1:]))))
    write('failed_hypotheses.csv',pd.DataFrame(failed));write('RESEARCH_LOG.jsonl','')
    (HERE/'RESEARCH_LOG.jsonl').write_text(json.dumps(dict(hypothesis_id='R1',evidence='Fixed broad event panel built from CY-006 cache.',economic_sequence='Leadership -> pressure -> residual resilience -> five-session repair observation -> later outcome.',hypothesis='Sector state and resilience have descriptive information beyond past returns.',change='One predeclared representation; no threshold sweep.',baseline='Natural quintiles and fixed descriptive OLS.',expected='Stable direction across annual and past-only tables.',falsifier='No broad relation, sign instability, or concentration.'),ensure_ascii=False)+'\n')
    write('DELIVERY_STATUS.json',dict(status='EVENT_RESEARCH_COMPLETE_NO_ACCOUNT_STAGE',reason='This run is descriptive development evidence only; account gate requires stable mechanism judgement.',panel_rows=len(d),pressure_rows=int(d.pressure.sum())))
if __name__=='__main__': main()
