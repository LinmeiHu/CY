"""Aggregate existing ranking artifacts only; never rerun inference or labels."""
import pandas as pd
from common import *
import account_formation as af

def hac_mean(g,col):
    g=g.dropna(subset=[col]).sort_values('t');x=g[col].to_numpy(float);t=g.t.to_numpy();n=len(x)
    if n<3:return dict(mean=float(x.mean()) if n else None,se=None,lower=None,upper=None,n=n)
    e=x-x.mean();lag=abs(t[:,None]-t[None,:]);w=np.maximum(0,1-lag/21);variance=float(e@w@e)/(n*n);se=np.sqrt(max(0,variance))
    return dict(mean=float(x.mean()),se=float(se),lower=float(x.mean()-1.96*se),upper=float(x.mean()+1.96*se),n=n)

def periods(d):
    yield from d.groupby('year')
    yield 'ALL',d

def main():
    data=af.DATA;doc=HERE/af.DOC
    names=['IC','BUCKETS','TOPK','MARGINS','SEED_STABILITY'];tables={k:pd.read_parquet(data/f'RANKING_{k}_DATE.parquet') for k in names}
    ic=tables['IC'];q=tables['BUCKETS'];top=tables['TOPK'];margin=tables['MARGINS'];st=tables['SEED_STABILITY'];summ=[];quant=[];mon=[];lifts=[]
    for (seed,target),d in ic.groupby(['seed','target']):
        for year,g in periods(d):
            v=g.ic.dropna();sd=v.std();summ.append(dict(seed=seed,target=target,year=year,median=v.median(),positive_ratio=(v>0).mean(),ic_std=sd,icir=v.mean()/sd if sd>0 else None,coverage=g.coverage.mean(),**hac_mean(g,'ic')))
    for (seed,target,groups),d in q.groupby(['seed','target','groups']):
        for year,g in periods(d):
            a=g.groupby('bucket').agg(mean=('mean','mean'),mean_daily_median=('median','mean'),mean_daily_positive_ratio=('positive_ratio','mean'),samples=('observed','sum'),selected=('selected','sum')).reset_index()
            for r in a.to_dict('records'):quant.append(dict(seed=seed,target=target,groups=int(groups),year=year,**r))
            pivot=g.pivot(index='t',columns='bucket',values='mean');spread=(pivot[groups]-pivot[1]).rename('spread').reset_index()
            mon.append(dict(seed=seed,target=target,groups=int(groups),year=year,bucket_mean_spearman=a.bucket.corr(a['mean'],method='spearman'),adjacent_increasing_ratio=float((np.diff(a['mean'])>0).mean()),top_mean=a['mean'].iloc[-1],middle_mean=a['mean'].iloc[(groups-1)//2:(groups//2)+1].mean(),bottom_mean=a['mean'].iloc[0],spread=hac_mean(spread,'spread')))
    for (seed,target,k),d in top.groupby(['seed','target','k']):
        for year,g in periods(d):lifts.append(dict(seed=seed,target=target,k=int(k),year=year,return_mean=g['mean'].mean(),mean_daily_median=g['median'].mean(),universe=g.universe.mean(),top_percentile=g.top10_percent.mean(),positive_date_lift_ratio=(g.lift.dropna()>0).mean(),observed=g.observed.sum(),selected=g.selected.sum(),**hac_mean(g,'lift')))
    for name,rows in [('IC_SUMMARY',summ),('QUANTILE_SUMMARY',quant),('MONOTONICITY',mon),('TOPK_SUMMARY',lifts)]:
        pd.DataFrame(rows).to_csv(doc/f'RANKING_{name}.csv',index=False)
    ic['month']=ic.date.str[:7];ic.groupby(['seed','target','month']).agg(mean_ic=('ic','mean'),positive_ratio=('ic',lambda x:(x.dropna()>0).mean()),dates=('ic','count')).to_csv(doc/'RANKING_IC_MONTHLY.csv')
    top['month']=top.date.str[:7];top.groupby(['seed','target','k','month']).agg(mean_return=('mean','mean'),mean_lift=('lift','mean'),dates=('lift','count')).to_csv(doc/'RANKING_TOPK_MONTHLY.csv')
    st.groupby(['pair','year']).mean(numeric_only=True).drop(columns='t').to_csv(doc/'RANKING_SEED_STABILITY_ANNUAL.csv')
    st.groupby('pair').mean(numeric_only=True).drop(columns=['t','year']).to_csv(doc/'RANKING_SEED_STABILITY_ALL.csv')
    for k in ['10_20','10_50','20_100']:margin[f'normalized_gap_{k}']=margin[f'cumulative_score_gap_{k}']/margin.score_std.replace(0,np.nan)
    margin.groupby(['seed','year']).mean(numeric_only=True).drop(columns='t').to_csv(doc/'RANKING_SCORE_MARGIN_ANNUAL.csv')
    # EW subtraction must not manufacture independent rank evidence.
    same=ic[ic.target=='absolute'].merge(ic[ic.target=='ew_relative'],on=['seed','t']);assert np.allclose(same.ic_x,same.ic_y,equal_nan=True)
    abs_summary=[r for r in summ if r['target']=='absolute' and r['year']!='ALL'];top2020=[r for r in lifts if r['target']=='absolute' and r['year']==2020 and r['k']==10]
    positive_global=all(r['mean']>0 for r in abs_summary);tail_failure=all(r['mean']<0 for r in top2020)
    classification='ROBUST_RANKING_BUT_WEAK_TOP_TAIL' if positive_global and tail_failure else 'INCONCLUSIVE'
    result=dict(at=now(),status='SUMMARY_COMPLETE',classification=classification,evidence_strength='Development descriptive convergence; inspect HAC bounds.2020 weaker; robust does not mean every seed-year individually significant.',annual_ic=abs_summary,top10_2020=top2020,monotonicity=mon,limitations=['No training/inference/label recomputation','Quantile median summary is mean of daily medians, not pooled stock median; full daily statistics retained','Bartlett HAC uses actual trading-session distance20, including sparse residual grid;95%normal intervals descriptive with no multiple-testing claim','Industry relative daily; beta/style residual only original10-session grid; style support sparse','Weak top-tail is strongest in2020 and partly2023; not proof all top-tail signal absent'],next='2020_ROOT_CAUSE_DIAGNOSIS using global vs tail vs account evidence')
    dump(af.DOC+'RANKING_AUDIT_SUMMARY.json',result)
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axs=plt.subplots(3,2,figsize=(20,18))
    for seed in ['s17','s29','s43','ensemble']:
        g=ic[(ic.seed==seed)&(ic.target=='absolute')];axs[0,0].plot(pd.to_datetime(g.date),g.rolling60_decision_ic,label=seed)
        a=pd.DataFrame(quant);a=a[(a.seed==seed)&(a.target=='absolute')&(a.groups==20)&(a.year=='ALL')];axs[0,1].plot(a.bucket,a['mean'],label=seed)
        a=pd.DataFrame(lifts);a=a[(a.seed==seed)&(a.target=='absolute')&(a.year==2020)];axs[1,0].plot(a.k,a['mean'],marker='o',label=seed)
        a=margin[margin.seed==seed].groupby('year').normalized_gap_10_20.mean();axs[2,1].plot(a.index,a.values,marker='o',label=seed)
    for pair,g in st.groupby('pair'):
        axs[1,1].plot([10,20,50,100,200],[g[f'overlap{k}'].mean() for k in [10,20,50,100,200]],marker='o',label=pair)
    for target,g in ic[ic.seed=='ensemble'].groupby('target'):
        a=g.groupby('year').ic.mean();axs[2,0].plot(a.index,a.values,marker='o',label=target)
    for ax,title in zip(axs.flat,['Rolling60 decision-day RankIC','Four-year ventile returns / equal date weighting','2020 Top-K lift vs eligible EW','Seed Top-K overlap','Ensemble residual RankIC / grid limitation applies','Top10-minus-Top20 score gap / daily score std']):ax.set_title(title);ax.axhline(0,color='gray',lw=.5);ax.grid(alpha=.2);ax.legend(fontsize=8)
    fig.suptitle('CROSS-SECTIONAL RANKING AUDIT /2020–2023 DEVELOPMENT / frozen32k');fig.tight_layout(rect=[0,0,1,.97]);fig.savefig(doc/'RANKING_AUDIT_KEY_RESULTS.png',dpi=150);plt.close(fig)
    return result

if __name__=='__main__':main()
