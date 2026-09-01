#!/usr/bin/env python3
"""Frozen development-only H3 Ridge/L2-LightGBM walk-forward run."""
from __future__ import annotations
import hashlib,json,sys
from pathlib import Path
import lightgbm as lgb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.stats import spearmanr,pearsonr

ROOT=Path(__file__).resolve().parents[3]; PROGRAM=ROOT/'research/market_behavior_os_v2'
SPEC=PROGRAM/'experiments/ASHARE-3SESSION-LGBM-V1_spec.json'; MANIFEST=PROGRAM/'experiments/ASHARE-TAIL-OPEN-LGBM-V1_feature_manifest.json'
EXT=Path('/Volumes/quant/CY_quant_research/ashare_3session_lgbm_v1'); PANEL=EXT/'h3_model_panel_2014_2021.parquet'; PRED=EXT/'development_predictions.parquet'
OUT=PROGRAM/'artifacts/ASHARE-3SESSION-LGBM-V1_result.json'; REPORT=PROGRAM/'reports/ASHARE-3SESSION-LGBM-V1_report.md'
sys.path.insert(0,str(PROGRAM/'scripts')); import ashare_tail_open_lgbm_v1_core as core
def sha(p):
 h=hashlib.sha256();
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def metrics(x):
 daily=[]
 for _,g in x.groupby('trade_date'):
  z=g.loc[g.h3_valid,['score','h3_net']].dropna()
  if len(z)>=20 and z.score.nunique()>1:daily.append((spearmanr(z.score,z.h3_net).statistic,pearsonr(z.score,z.h3_net).statistic))
 tails={}
 for n in (20,10,5,1):
  v=[]
  for _,g in x.groupby('trade_date'):
   z=g.loc[g.h3_valid].sort_values(['score','symbol'],ascending=[False,True]); v.extend(z.head(max(1,int(np.ceil(len(z)*n/100)))).h3_net)
  tails[str(n)]=float(np.mean(v)) if v else None
 return {'rows':len(x),'dates':int(x.trade_date.nunique()),'spearman_ic':float(np.nanmean([a for a,b in daily])),'pearson_ic':float(np.nanmean([b for a,b in daily])),'tails_net':tails,'dispersion':float(x.score.std(ddof=1))}
def main():
 s=json.loads(SPEC.read_text()); fs=[x['name'] for x in json.loads(MANIFEST.read_text())['features']]
 if len(fs)!=59 or len(set(fs))!=59:raise RuntimeError('feature identity')
 cols=['trade_date','symbol','industry','signal_eligible','h1_valid','h2_valid','h3_valid','h1_net','h2_net','h3_net','h1_gross','h2_gross','h3_gross','h3_exit_date',*fs]
 d=pq.read_table(PANEL,columns=cols,use_threads=False).to_pandas();d.trade_date=pd.to_datetime(d.trade_date);d.h3_exit_date=pd.to_datetime(d.h3_exit_date);d=d[d.signal_eligible].sort_values(['trade_date','symbol']);d[fs]=d[fs].replace([np.inf,-np.inf],np.nan)
 if d.trade_date.max().year>2021:raise RuntimeError('sealed boundary')
 pred=[]
 for i,f in enumerate(s['folds']):
  end=pd.Timestamp(f['train_end']); start=pd.Timestamp(f'{f["predict_year"]}-01-01'); finish=pd.Timestamp(f'{f["predict_year"]}-12-31')
  train=d[(d.trade_date<=end)&d.h3_valid&(d.h3_exit_date<start)].copy(); last=train.trade_date.max();train=train[train.trade_date!=last]; test=d[(d.trade_date>=start)&(d.trade_date<=finish)].copy()
  ridge=core.ridge_pipeline(10.0);ridge.fit(train[fs],train.h3_net)
  cfg=s['models']['lightgbm'];kw=dict(objective='regression_l2',learning_rate=cfg['learning_rate'],n_estimators=cfg['n_estimators_max'],feature_fraction=cfg['feature_fraction'],bagging_fraction=cfg['bagging_fraction'],bagging_freq=1,num_leaves=15,max_depth=4,min_child_samples=300,reg_lambda=10,reg_alpha=1,random_state=cfg['seed']+i,deterministic=True,force_col_wise=True,num_threads=4,verbosity=-1)
  cutoff=sorted(train.trade_date.unique())[-126];inner=train[train.trade_date>=cutoff];outer=train[train.trade_date<cutoff]
  early=lgb.LGBMRegressor(**kw);early.fit(outer[fs],outer.h3_net,eval_set=[(inner[fs],inner.h3_net)],callbacks=[lgb.early_stopping(100,verbose=False)])
  best=int(early.best_iteration_ or cfg['n_estimators_max']);m=lgb.LGBMRegressor(**(kw|{'n_estimators':best}));m.fit(train[fs],train.h3_net)
  for name,score in [('ridge',ridge.predict(test[fs])),('lightgbm_medium_l2',m.predict(test[fs]))]:
   z=test[['trade_date','symbol','industry','h1_valid','h2_valid','h3_valid','h1_net','h2_net','h3_net','h1_gross','h2_gross','h3_gross']].copy();z['score']=score;z['model']=name;z['fold']=i;pred.append(z)
 o=pd.concat(pred,ignore_index=True);o.to_parquet(PRED,index=False,compression='zstd')
 result={'experiment_id':s['experiment_id'],'status':'DEVELOPMENT_MODEL_OOF_COMPLETE_PORTFOLIO_REPLAY_PENDING','hashes':{'spec':sha(SPEC),'panel':sha(PANEL),'predictions':sha(PRED)},'boundaries':{'validation_opened':False,'final_oos_opened':False},'models':{}}
 for name,g in o.groupby('model'):
  result['models'][name]={'pooled':metrics(g),'annual':{str(y):metrics(v) for y,v in g.groupby(g.trade_date.dt.year)}}
 OUT.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n');REPORT.write_text('# A-share 3-session LightGBM V1\n\nDevelopment-only OOF model fit complete; portfolio replay pending. Validation and Final OOS remain sealed.\n')
 print(json.dumps(result,indent=2))
if __name__=='__main__':main()
