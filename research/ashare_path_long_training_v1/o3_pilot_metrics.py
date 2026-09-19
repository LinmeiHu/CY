"""Matched full-cross-section signal metrics, all ranks before label masking."""
import pandas as pd
from common import *
from train import mature
from o3_pilot_protocol import YEAR,STEPS,LOCAL,TOPK,PCTS
DOC=HERE/'account_diversification_v1'
def corr(x,y):
 ok=np.isfinite(x)&np.isfinite(y)
 return float(pd.Series(np.asarray(x)[ok]).corr(pd.Series(np.asarray(y)[ok]),method='spearman')) if ok.sum()>=5 and np.std(np.asarray(x)[ok])>0 and np.std(np.asarray(y)[ok])>0 else np.nan

def day_metrics(g,score,label):
 p=g[score].to_numpy();y=g[label].to_numpy();assert np.isfinite(p).all();order=np.lexsort((g.j.to_numpy(),-p));valid=np.isfinite(y);market=np.nanmean(y) if valid.any() else np.nan;rows=[]
 def add(scope,metric,value,n):rows.append(dict(scope=scope,metric=metric,value=value,n=int(n)))
 def mean(v):return float(np.nanmean(v)) if np.isfinite(v).any() else np.nan
 add('GLOBAL','rank_ic',corr(p,y),valid.sum());add('GLOBAL','mse20',mean((p-y)**2),valid.sum());e=abs(10*(p-y));add('GLOBAL','huber20_scaled',mean(np.where(e<1,.5*e**2,e-.5)),valid.sum());add('GLOBAL','label_coverage',valid.mean(),len(y))
 for pct in LOCAL:
  ix=order[:max(1,int(np.ceil(len(y)*pct)))];add(f'LOCAL_{pct:g}','rank_ic',corr(p[ix],y[ix]),np.isfinite(y[ix]).sum())
 for scope,k in [(f'K{k}',k) for k in TOPK]+[(f'P{v:g}',int(np.ceil(len(y)*v))) for v in PCTS]:
  ix=order[:max(1,k)];v=y[ix];add(scope,'return',mean(v),np.isfinite(v).sum());add(scope,'lift',mean(v)-market,np.isfinite(v).sum())
  if scope=='K10':
   add(scope,'median_return',float(np.nanmedian(v)) if np.isfinite(v).any() else np.nan,np.isfinite(v).sum())
   for q in [.01,.05,.1]:add(scope,f'return_quantile_{q:g}',float(np.nanquantile(v,q)) if np.isfinite(v).any() else np.nan,np.isfinite(v).sum())
   if 'mae20' in g:
    mae=g.mae20.to_numpy()[ix];add(scope,'mean_mae20',mean(mae),np.isfinite(mae).sum());add(scope,'mae_label_coverage',float(np.isfinite(mae).mean()),len(mae))
 # Winners restricted to known labels; report observed-selected precision and coverage.
 yr=pd.Series(y).rank(pct=True,method='average').to_numpy()
 for win in [.05,.1,.2]:
  winners=valid&(yr>1-win);prevalence=winners.sum()/max(1,valid.sum())
  for k in [5,10,20,50]:
   ix=order[:k];hits=int(winners[ix].sum());obs=int(valid[ix].sum());prec=hits/obs if obs else np.nan;scope=f'WIN{win:g}_K{k}'
   add(scope,'precision',prec,obs);add(scope,'recall',hits/max(1,winners.sum()),obs);add(scope,'random_lift',prec/prevalence if prevalence else np.nan,obs);add(scope,'selected_label_coverage',obs/len(ix),len(ix))
 for lo,hi in [(0,10),(10,20),(20,50),(50,100),(100,200)]:
  ix=order[lo:hi];ok=valid[ix];scope=f'CAL_{lo+1}_{hi}';add(scope,'predicted',mean(p[ix][ok]),ok.sum());add(scope,'realized',mean(y[ix]),ok.sum());add(scope,'error',mean(p[ix][ok]-y[ix][ok]),ok.sum());add(scope,'absolute_error',abs(mean(p[ix][ok]-y[ix][ok])),ok.sum())
 for bins in [10,20]:
  means=[]
  for i,ix in enumerate(np.array_split(order,bins)):
   v=mean(y[ix]);means.append(v);add(f'Q{bins}_{i+1}','return',v,np.isfinite(y[ix]).sum())
  add(f'Q{bins}','monotonicity',corr(-np.arange(bins),np.array(means)),bins);add(f'Q{bins}','top_bottom_spread',means[0]-means[-1],bins)
 return rows

def main(seed=17):
 dest=OUT/'account_diversification_v1'/f'o3_pilot_s{seed}';daily=pd.read_parquet(dest/'DAILY.parquet');manifest=json.loads((DOC/'CANONICAL_CACHE_MANIFEST.json').read_text());label=[]
 for b in manifest['parts']:
  # Date keys are authoritative, no new inference or label reconstruction.
  t=int(b['t'])
  if t not in set(daily.t.unique()):continue
  v=pd.read_parquet(b['path'],columns=['t','j','ret20','mae20','outcome_end_date20']);v.loc[v.outcome_end_date20.isna()|(v.outcome_end_date20>='2021-01-01'),'ret20']=np.nan;v.loc[v.ret20.isna(),'mae20']=np.nan;label.append(v[['t','j','ret20','mae20']])
 daily=daily.merge(pd.concat(label),on=['t','j'],validate='one_to_one');assert len(daily)==len(pd.read_parquet(dest/'DAILY.parquet'))
 allrows=[]
 for step in STEPS:
  for obj in [2,3]:
   for t,g in daily.groupby('t'):
    allrows.extend(dict(t=int(t),date=g.decision_date.iloc[0],role='DEV_DAILY',step=step,objective=obj,**v) for v in day_metrics(g,f'O{obj}_B{step}_pred20','ret20'))
 idx=pd.read_parquet(OUT/'index.parquet');dates=np.array(json.loads((PANEL/'axes.json').read_text())['dates']);cut=np.searchsorted(dates,'2020-01-01')-1;lab=mature(np.load(OUT/'labels.npy',mmap_mode='r'),idx.t.to_numpy(),cut);labels=idx[['t','j']].copy();labels['ret20']=lab[:,1]
 for step in STEPS:
  for obj in [2,3]:
   f=pd.read_parquet(OUT/f'M1_OFFSET_{YEAR}_s{seed}_O{obj}_B{step}_TRAIN_FITTED_DIAGNOSTIC_ONLY_pred.parquet');f=f.merge(labels,on=['t','j'],validate='one_to_one')
   for t,g in f.groupby('t'):
    if g.ret20.notna().sum()<20:continue
    allrows.extend(dict(t=int(t),date=g.decision_date.iloc[0],role='TRAIN_FITTED_ORIGINAL_GRID',step=step,objective=obj,**v) for v in day_metrics(g,'pred20','ret20'))
 a=pd.DataFrame(allrows);a.to_parquet(dest/'SIGNAL_DAILY.parquet',index=False);summary=a.groupby(['role','step','objective','scope','metric']).agg(mean=('value','mean'),median=('value','median'),std=('value','std'),positive_fraction=('value',lambda v:float((v.dropna()>0).mean())),dates=('value','count')).reset_index();summary['icir']=summary['mean']/summary['std'];summary.to_csv(DOC/f'O3_PILOT_s{seed}_SIGNAL_SUMMARY.csv',index=False)
 keys=['role','step','t','date','scope','metric'];base=a[a.objective==2][keys+['value']];can=a[a.objective==3][keys+['value']];pair=base.merge(can,on=keys,suffixes=('_o2','_o3'),validate='one_to_one');pair['delta']=pair.value_o3-pair.value_o2;pair.to_parquet(dest/'SIGNAL_PAIRED.parquet',index=False);s=pair.groupby(['role','step','scope','metric']).agg(baseline=('value_o2','mean'),candidate=('value_o3','mean'),delta=('delta','mean'),dates=('delta','count')).reset_index();s.to_csv(DOC/f'O3_PILOT_s{seed}_SIGNAL_DELTAS.csv',index=False)
 z=pair[pair.role=='DEV_DAILY'].copy();z['month']=z.date.str[:7];z.groupby(['step','month','scope','metric'])[['value_o2','value_o3','delta']].mean().to_csv(DOC/f'O3_PILOT_s{seed}_MONTHLY.csv')
 # Fixed20-date circular block intervals on paired daily changes for primary metrics.
 rng=np.random.default_rng(1747);ci=[]
 for (step,scope,metric),g in z.groupby(['step','scope','metric']):
  if not ((metric=='rank_ic' and scope in ['GLOBAL','LOCAL_0.01','LOCAL_0.02','LOCAL_0.05']) or (metric=='lift' and scope in ['K10','K50'])):continue
  v=g.sort_values('t').delta.to_numpy();n=len(v);starts=rng.integers(0,n,size=(2000,int(np.ceil(n/20))));ii=((starts[:,:,None]+np.arange(20))%n).reshape(2000,-1)[:,:n];boot=np.nanmean(v[ii],axis=1);lo,hi=np.nanquantile(boot,[.05,.95]);ci.append(dict(step=step,scope=scope,metric=metric,delta=np.nanmean(v),low90=lo,high90=hi,block_dates=20))
 pd.DataFrame(ci).to_csv(DOC/f'O3_PILOT_s{seed}_BLOCK_CI.csv',index=False);dump('account_diversification_v1/O3_PILOT_STATE.json',dict(at=now(),status='SIGNAL_COMPLETE_ACCOUNT_NEXT',seed=seed,role='SINGLE_FOLD_PILOT'))
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--seed',type=int,default=17);main(p.parse_args().seed)
