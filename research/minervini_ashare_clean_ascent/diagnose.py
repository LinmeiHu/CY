"""Fixed event attribution; no learned rank or parameter search."""
import json,math
from pathlib import Path
import numpy as np,pandas as pd
from .common import HERE,OUT,dump,sha
from .replay import Market

def event_labels(m,f):
    f=f.copy();t=f.t.to_numpy(int);j=f.j.to_numpy(int);e=t+1;n=len(m.dates);inside=e<n;ec=np.minimum(e,n-1)
    op=m.a['open'][ec,j];factor=m.a['coord'][ec-1,j]/((m.a['close'][ec-1,j]-m.a['cash_per_share'][ec,j])/m.a['share_multiplier'][ec,j]);limit=np.floor(f['limit'].to_numpy()*f.factor.to_numpy()/factor*100+1e-8)/100
    entry=np.ceil(op*1.0005*100-1e-8)/100
    legal=inside&(m.a['trade_status'][ec,j]==1)&(m.a['volume'][ec,j]>0)&(m.a['buy_blocked_open'][ec,j]==0)&(m.a['hard_valid'][ec,j]==1)&(op<m.a['up_limit_price'][ec,j])&(entry<=limit)&(entry<=m.a['up_limit_price'][ec,j])
    legal&=np.isfinite(factor)&(factor>0)&(m.a['corporate_action_blocking'][ec,j]==0)&(np.nan_to_num(m.a['rights_ratio'][ec,j],nan=0)==0)
    minimum_qty=np.where(np.array(m.boards)[j]=='STAR',200,100);transfer_entry=np.where(np.array(m.dates)[ec]<'2022-04-29',.00002,.00001)
    minimum_debit=minimum_qty*entry*(1+transfer_entry)+np.maximum(5,minimum_qty*entry*.0003)
    legal&=minimum_debit<=f.amount20.to_numpy()*.01
    f['event_entry_legal']=legal;f['event_lowopen']=op<f.U.to_numpy()*f.factor.to_numpy()/factor
    actions=np.cumsum(np.nan_to_num(m.a['corporate_action_count'],nan=0)>0,axis=0)
    for horizon in [5,10,20]:
        x=e+horizon
        # Find next independently legal open without crossing the allowed final session.
        for _ in range(n):
            xc=np.minimum(x,n-1)
            blocked=(m.a['sell_blocked_open'][xc,j]!=0)|(m.a['trade_status'][xc,j]!=1)|(m.a['volume'][xc,j]<=0)|(m.a['open'][xc,j]<=m.a['down_limit_price'][xc,j])|~np.isfinite(m.a['open'][xc,j])|(np.floor(m.a['open'][xc,j]*.9995*100+1e-8)/100<m.a['down_limit_price'][xc,j])
            adjust=legal&(x<n)&blocked
            if not adjust.any():break
            x[adjust]+=1
        xc=np.minimum(x,n-1);outprice=np.floor(m.a['open'][xc,j]*.9995*100+1e-8)/100
        valid=legal&(x<n)&(outprice>=m.a['down_limit_price'][xc,j])
        # Strict simple event cohort: action paths kept in physical accounts, not approximated here.
        hasaction=actions[xc,j]-actions[np.maximum(e-1,0).clip(max=n-1),j]>0
        valid&=~hasaction
        gross=outprice/entry-1
        dates=np.array(m.dates)[xc];transfer_in=np.where(np.array(m.dates)[ec]<'2022-04-29',.00002,.00001);transfer_out=np.where(dates<'2022-04-29',.00002,.00001)
        qty=np.where(np.array(m.boards)[j]=='STAR',200,100)
        buy=qty*entry+np.maximum(5,qty*entry*.0003)+qty*entry*transfer_in
        sell=qty*outprice-np.maximum(5,qty*outprice*.0003)-qty*outprice*(transfer_out+np.where(dates<'2023-08-28',.001,.0005))
        f[f'net{horizon}']=np.where(valid,sell/buy-1,np.nan);f[f'gross{horizon}']=np.where(valid,gross,np.nan)
        f[f'action_excluded{horizon}']=hasaction;f[f'incomplete{horizon}']=x>=n
    # Pure diagnostic MFE/MAE on same no-action H10 cohort.
    hi=np.full(len(f),-np.inf);lo=np.full(len(f),np.inf)
    for off in range(10):
        k=np.minimum(e+off,n-1);hi=np.maximum(hi,m.a['high'][k,j]);lo=np.minimum(lo,m.a['low'][k,j])
    f['MFE']=np.where(f.net10.notna(),hi/entry-1,np.nan);f['MAE']=np.where(f.net10.notna(),lo/entry-1,np.nan)
    return f

def regress(f,extra,label):
    controls=['retA','ret30','ret60','ret252','volatility','MAX','log_amount','static_width']+(['beta'] if 'beta' in f else [])
    fields=list(dict.fromkeys(controls+extra));d=f[['t','board','net10']+fields].replace([np.inf,-np.inf],np.nan).dropna().copy()
    if len(d)<100:return []
    # Full date-by-board fixed effects, no future-normalized rank training.
    z=d[fields+['net10']]-d.groupby(['t','board'])[fields+['net10']].transform('mean');sd=z[fields].std();use=sd[sd>1e-12].index.tolist();X=z[use].to_numpy()/sd[use].to_numpy();y=z.net10.to_numpy();coef=np.linalg.lstsq(X,y,rcond=None)[0]
    residual=y-np.einsum("ij,j->i",X,coef);out=[]
    # Cluster by signal date for overlapping stock observations, descriptive only.
    ev,vec=np.linalg.eigh(np.einsum("ki,kj->ij",X,X));inv=np.zeros_like(ev);ok=ev>ev.max()*1e-12;inv[ok]=1/ev[ok];xx=np.einsum("ik,k,jk->ij",vec,inv,vec);meat=np.zeros((len(use),len(use)))
    for ids in d.groupby('t').indices.values():
        score=np.einsum("ij,i->j",X[ids],residual[ids]);meat+=np.outer(score,score)
    se=np.sqrt(np.diag(np.einsum("ik,kl,lj->ij",xx,meat,xx)));assert np.isfinite(coef).all() and np.isfinite(se).all()
    for k,b,err in zip(use,coef,se):out.append(dict(model=label,variable=k,coefficient_per_sd=b,cluster_date_se=err,n=len(d),dates=d.t.nunique()))
    return out

def run():
    m=Market();reg=[];groups=[];coverage=[]
    for family in ['OLD_30_5','N']:
        f=pd.read_parquet(OUT/(family+'_signals.parquet'));f=event_labels(m,f)
        f['log_amount']=np.log(f.amount20);f['static_width']=f.V2 if family=='N' else f.C1
        f['ret30']=m.a['coord'][f.t.to_numpy()-1,f.j.to_numpy()]/m.a['coord'][f.t.to_numpy()-31,f.j.to_numpy()]-1
        if family!='N':
            betas=[]
            for r in f.itertuples():
                q=r.t-6;stock=m.a['step'][q-119:q+1,r.j];market=m.a['market'][q-119:q+1]
                betas.append(float(np.mean((stock-stock.mean())*(market-market.mean()))/np.var(market)) if len(stock)==120 and np.isfinite(stock).all() and np.var(market)>0 else np.nan)
            f['beta']=betas
        coverage.append(dict(family=family,signals=len(f),legal_open=int(f.event_entry_legal.sum()),labels10=int(f.net10.notna().sum()),actions_excluded=int(f.action_excluded10.sum()),incomplete10=int(f.incomplete10.sum())))
        extra=['Path','Consolidation'] if family!='N' else ['Path','VCP_GUARD','MR','Volume','long']
        for z in ['VCP_GUARD','long']:
            if z in f:f[z]=f[z].astype(float)
        reg+=regress(f,extra,family+'_FULL')
        if family=='N':
            reg+=regress(f[f.long==1],['Path','VCP_GUARD','MR','Volume'],'N_LONG_ONLY')
            reg+=regress(f[(f.long==1)&(f.VCP_GUARD==1)],['Path','VCP','MR','Volume'],'N_ADMITTED_RANK_ONLY')
            # Static width matched guard comparison, within date/board and prior gain bins.
            d=f[f.long==1].dropna(subset=['net10']).copy()
            d['width_bin']=d.groupby(['t','board']).static_width.rank(pct=True).mul(5).apply(np.ceil)
            d['gain_bin']=d.groupby(['t','board']).retA.rank(pct=True).mul(5).apply(np.ceil)
            cells=d.groupby(['t','board','width_bin','gain_bin','VCP_GUARD']).net10.agg(['mean','size']).reset_index()
            paired=cells.pivot(index=['t','board','width_bin','gain_bin'],columns='VCP_GUARD',values='mean').dropna()
            dump(HERE/'static_width_matched_vcp.json',dict(cells=len(paired),guard_minus_no_guard=float((paired[1.]-paired[0.]).mean()) if len(paired) and 1. in paired and 0. in paired else None,scope='unweighted common date/board/width/prior-gain cells; execution-simple cohort, descriptive'))
            for col in ['market_gate','VCP_GUARD','long','board']:
                g=f.groupby(col).net10.agg(['size','count','mean','median']).reset_index();g['family']=family;g['split']=col;g=g.rename(columns={col:'cell'});groups.append(g)
        # Ten-session de-dup is chronology only, never based on outcome.
        last={};keep=[]
        for r in f.sort_values(['t','symbol']).itertuples():
            k=r.t-last.get(r.symbol,-10000)>=10;keep.append(k)
            if k:last[r.symbol]=r.t
        dedup=f.sort_values(['t','symbol']).loc[np.array(keep)]
        groups.append(pd.DataFrame([dict(family=family,split='DEDUP10',cell='all',size=len(dedup),count=dedup.net10.notna().sum(),mean=dedup.net10.mean(),median=dedup.net10.median())]))
        f.to_parquet(OUT/(family+'_events.parquet'),index=False)
    pd.DataFrame(coverage).to_csv(HERE/'event_coverage.csv',index=False);pd.DataFrame(reg).to_csv(HERE/'attribution_regression.csv',index=False);pd.concat(groups,ignore_index=True).to_csv(HERE/'event_stratification.csv',index=False)
    print('EVENT_DIAGNOSTICS_COMPLETE',coverage,flush=True)
if __name__=='__main__':run()
