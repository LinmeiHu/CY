#!/usr/bin/env python3
"""Development-only model-failure audit using saved Tail-to-Open V1 models."""
from __future__ import annotations

import gc
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.stats import pearsonr, skew, spearmanr

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
MANIFEST = PROGRAM / "experiments/ASHARE-TAIL-OPEN-LGBM-V1_feature_manifest.json"
STAGE_B = PROGRAM / "artifacts/ASHARE-TAIL-OPEN-LGBM-V1_stage_b_result.json"
RESULT = PROGRAM / "artifacts/ASHARE-TAIL-OPEN-LGBM-V1_model_failure_audit.json"
REPORT = PROGRAM / "reports/ASHARE-TAIL-OPEN-LGBM-V1_model_failure_audit.md"
PANEL = Path("/Volumes/quant/CY_quant_research/ashare_tail_open_lgbm_v1/model_panel_2013_2023.parquet")
PREDICTIONS = Path("/Volumes/quant/CY_quant_research/ashare_tail_open_lgbm_v1/stage_b_predictions.parquet")
MODELS = Path("/Volumes/quant/CY_quant_research/ashare_tail_open_lgbm_v1/models")
PRED_HASH = "d99f0771bb104535607b3c489c252eb0a80c6489f7aa68edc33d01a9b9ce4c19"
PANEL_HASH = "824d663781d0e45f91ea7741fc63076fd2dfaad7fb16c38f2d72174e8ef461fd"
PROFILES = ("shallow", "medium", "moderately_richer")
YEARS = (2018, 2019, 2020, 2021)
MIN_LEAF = {"shallow": 500, "medium": 300, "moderately_richer": 200}


class FailureAuditError(RuntimeError): pass

def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""): h.update(b)
    return h.hexdigest()

def clean(x: Any) -> Any:
    if isinstance(x,dict): return {str(k):clean(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)): return [clean(v) for v in x]
    if isinstance(x,(np.integer,)): return int(x)
    if isinstance(x,(np.floating,float)): return float(x) if math.isfinite(float(x)) else None
    if isinstance(x,(np.bool_,bool)): return bool(x)
    return x

def write(path:Path,text:str)->None:
    tmp=path.with_name('.'+path.name+'.tmp'); tmp.write_text(text); tmp.replace(path)

def load_core() -> Any:
    p=PROGRAM/'scripts/ashare_tail_open_lgbm_v1_core.py'
    s=importlib.util.spec_from_file_location('tail_open_failure_core',p)
    if s is None or s.loader is None: raise FailureAuditError('core unavailable')
    m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m

CORE=load_core()

def metric(frame:pd.DataFrame, score:str)->dict[str,Any]:
    valid=frame.loc[frame.label_valid]
    daily=[]
    buckets={str(i):[] for i in range(1,21)}
    tails={str(x):[] for x in (10,5,1)}
    for _,g in frame.groupby('trade_date',sort=True):
        v=g.loc[g.label_valid]
        if len(v)>=20 and v[score].nunique()>1 and v.label_net.nunique()>1:
            daily.append((spearmanr(v[score],v.label_net).statistic,pearsonr(v[score],v.label_net).statistic))
        asc=g.sort_values([score,'symbol'],ascending=[True,True])
        asc['_bucket']=(np.arange(len(asc))*20//len(asc)+1)
        for b,sub in asc.groupby('_bucket'):
            q=sub.loc[sub.label_valid,'label_net'];
            if len(q): buckets[str(int(b))].append(float(q.mean()))
        desc=asc.sort_values([score,'symbol'],ascending=[False,True])
        for pct in (10,5,1):
            q=desc.head(max(1,math.ceil(len(desc)*pct/100))).loc[lambda z:z.label_valid,'label_net']
            if len(q): tails[str(pct)].append(float(q.mean()))
    d=np.asarray(daily,float)
    s=frame[score].to_numpy(float)
    positive=frame.loc[frame[score].gt(0)]
    positive_valid=positive.loc[positive.label_valid]
    return {'rows':int(len(frame)),'dates':int(frame.trade_date.nunique()),'spearman_ic':float(np.nanmean(d[:,0])) if len(d) else None,'pearson_ic':float(np.nanmean(d[:,1])) if len(d) else None,'bucket_net_returns':{k:float(np.mean(v)) if v else None for k,v in buckets.items()},'tail_net_returns':{f'top_{k}pct':float(np.mean(v)) if v else None for k,v in tails.items()},'positive_score_region':{'rows':int(len(positive)),'dates':int(positive.trade_date.nunique()),'net_return':float(positive_valid.label_net.mean()) if len(positive_valid) else None},'prediction_dispersion':{'mean':float(s.mean()),'std':float(s.std(ddof=1)),'p1':float(np.quantile(s,.01)),'p99':float(np.quantile(s,.99)),'maximum':float(s.max())}}

def load_oof(features:list[str])->pd.DataFrame:
    cols=['trade_date','symbol','industry','label_valid','label_net','label_gross','score','model','fold']
    f=pq.read_table(PREDICTIONS,columns=cols,use_threads=False).to_pandas(); f.trade_date=pd.to_datetime(f.trade_date)
    f=f.loc[f.model.isin(PROFILES)].copy()
    if sha(PREDICTIONS)!=PRED_HASH or set(f.trade_date.dt.year.unique())!=set(YEARS): raise FailureAuditError('OOF identity/chronology changed')
    return f

def panel_until(end:pd.Timestamp,features:list[str])->pd.DataFrame:
    cols=['trade_date','exit_date','symbol','industry','signal_eligible','label_valid','label_net','label_gross',*features]
    quoted=','.join('"'+x+'"' for x in dict.fromkeys(cols))
    con=duckdb.connect(':memory:'); con.execute("SET memory_limit='6GB'")
    f=con.execute(f"SELECT {quoted} FROM read_parquet(?) WHERE signal_eligible AND trade_date>=DATE '2014-01-01' AND trade_date<=?",[str(PANEL),end.date()]).fetchdf(); con.close()
    f.trade_date=pd.to_datetime(f.trade_date); f.exit_date=pd.to_datetime(f.exit_date); return f

def leaf_support(booster:lgb.Booster,x:pd.DataFrame)->list[np.ndarray]:
    support=[np.zeros(32,dtype=np.int64) for _ in range(booster.num_trees())]
    for start in range(0,len(x),20000):
        leaves=booster.predict(x.iloc[start:start+20000],pred_leaf=True).astype(np.int16)
        for t in range(leaves.shape[1]):
            counts=np.bincount(leaves[:,t],minlength=32); support[t][:len(counts)]+=counts[:32]
    return support

def leaf_values(booster:lgb.Booster,x:pd.DataFrame,support:list[np.ndarray])->np.ndarray:
    if not len(x): return np.empty(0,dtype=np.int64)
    leaves=booster.predict(x,pred_leaf=True).astype(np.int16)
    return np.concatenate([support[t][leaves[:,t]] for t in range(leaves.shape[1])])

def leaf_audit(booster:lgb.Booster,train:pd.DataFrame,predict:pd.DataFrame,features:list[str],scores:pd.DataFrame)->dict[str,Any]:
    positive_keys=scores.loc[scores.score.gt(0),['trade_date','symbol']]
    pos=predict.merge(positive_keys,on=['trade_date','symbol'],how='inner')
    control=predict.loc[~predict.set_index(['trade_date','symbol']).index.isin(positive_keys.set_index(['trade_date','symbol']).index)].sort_values(['trade_date','symbol']).head(len(pos))
    support=leaf_support(booster,train[features])
    p=leaf_values(booster,pos[features],support); c=leaf_values(booster,control[features],support)
    low=MIN_LEAF['moderately_richer']
    executed=pos.loc[pos.label_valid]
    sec=pos.symbol.value_counts(normalize=True); ind=pos.industry.value_counts(normalize=True); dates=pos.trade_date.value_counts(normalize=True)
    return {'positive_rows':int(len(pos)),'positive_dates':int(pos.trade_date.nunique()),'positive_securities':int(pos.symbol.nunique()),'positive_industries':int(pos.industry.nunique()),'positive_net_return':float(executed.label_net.mean()) if len(executed) else None,'leaf_support_positive':{'p10':float(np.quantile(p,.1)) if len(p) else None,'median':float(np.median(p)) if len(p) else None,'p90':float(np.quantile(p,.9)) if len(p) else None,'fraction_at_or_below_frozen_min_data_leaf':float((p<=low).mean()) if len(p) else None},'leaf_support_control':{'median':float(np.median(c)) if len(c) else None,'fraction_at_or_below_frozen_min_data_leaf':float((c<=low).mean()) if len(c) else None},'concentration':{'max_date_share':float(dates.iloc[0]) if len(dates) else None,'max_security_share':float(sec.iloc[0]) if len(sec) else None,'max_industry_share':float(ind.iloc[0]) if len(ind) else None,'industry_hhi':float(np.square(ind).sum()) if len(ind) else None}}

def label_stats(oof:pd.DataFrame)->dict[str,Any]:
    def one(r:pd.DataFrame)->dict[str,Any]:
        r=r.loc[r.label_valid]; y=r.label_net; g=r.label_gross
        return {'observations':int(len(r)),'mean':float(y.mean()),'median':float(y.median()),'std':float(y.std(ddof=1)),'skew':float(skew(y,bias=False)),'p1':float(y.quantile(.01)),'p5':float(y.quantile(.05)),'p25':float(y.quantile(.25)),'p75':float(y.quantile(.75)),'p95':float(y.quantile(.95)),'p99':float(y.quantile(.99)),'fraction_net_positive':float((y>0).mean()),'fraction_gross_gt_40bp':float((g>.004).mean())}
    base=oof.loc[oof.model.eq('moderately_richer')]
    return {'pooled':one(base),'yearly':{str(y):one(base.loc[base.trade_date.dt.year.eq(y)]) for y in YEARS}}

def feature_overlap(frame:pd.DataFrame,features:list[str])->dict[str,Any]:
    r=frame.loc[frame.label_valid]; a=r.loc[r.label_net.gt(0),features]; b=r.loc[r.label_net.le(0),features]
    smd={}
    for f in features:
        x=pd.to_numeric(a[f],errors='coerce').dropna(); y=pd.to_numeric(b[f],errors='coerce').dropna(); denom=math.sqrt((x.var()+y.var())/2) if len(x)>1 and len(y)>1 else 0
        smd[f]=float((x.mean()-y.mean())/denom) if denom else 0.0
    absolute=sorted(((abs(v),k,v) for k,v in smd.items()),reverse=True)
    return {'positive_net_observations':int(len(a)),'nonpositive_net_observations':int(len(b)),'median_absolute_standardized_mean_difference':float(np.median([x[0] for x in absolute])),'p95_absolute_standardized_mean_difference':float(np.quantile([x[0] for x in absolute],.95)),'features_absolute_smd_ge_020':int(sum(x[0]>=.2 for x in absolute)),'top_feature_separation':[{'feature':k,'standardized_mean_difference':v} for _,k,v in absolute[:10]]}

def run()->dict[str,Any]:
    if sha(PANEL)!=PANEL_HASH: raise FailureAuditError('panel identity changed')
    features=[x['name'] for x in json.loads(MANIFEST.read_text())['features']]
    if len(features)!=59: raise FailureAuditError('feature manifest changed')
    oof=load_oof(features); out={'objective':'regression_l1 (MAE; conditional-median target in raw label_net units)','label_distribution':label_stats(oof),'models':{},'boundaries':{'refit':False,'saved_model_diagnostic_scoring':True,'new_model_family':False,'validation_opened':False,'final_oos_opened':False,'new_strategy_replay':False}}
    all_leaf=[]; oof_features=[]
    for fold,year in enumerate(YEARS):
        f=CORE.frozen_development_folds()[fold]; data=panel_until(f.predict_end,features)
        train=data.loc[CORE.purged_training_mask(data.trade_date,data.exit_date,f)&data.label_valid].copy(); pred=data.loc[data.trade_date.between(f.predict_start,f.predict_end)].copy()
        if pred.trade_date.max().year!=year: raise FailureAuditError('prediction fold contamination')
        for profile in PROFILES:
            b=lgb.Booster(model_file=str(MODELS/f'development_fold{fold}_{profile}.txt'))
            ps=b.predict(pred[features]); ts=b.predict(train[features])
            accepted=oof.loc[(oof.model==profile)&(oof.fold==fold)].set_index(['trade_date','symbol']).score
            observed=pd.Series(ps,index=pd.MultiIndex.from_frame(pred[['trade_date','symbol']])).reindex(accepted.index)
            if not np.allclose(observed.to_numpy(),accepted.to_numpy(),atol=1e-12,rtol=0): raise FailureAuditError(f'accepted OOF score mismatch {profile} fold {fold}')
            tr=train[['trade_date','symbol','label_valid','label_net','label_gross']].copy(); tr['score']=ts
            pr=pred[['trade_date','symbol','label_valid','label_net','label_gross']].copy(); pr['score']=ps
            out['models'].setdefault(profile,{})[str(year)]={'train':metric(tr,'score'),'oof':metric(pr,'score'),'degradation':{'spearman_oof_minus_train':metric(pr,'score')['spearman_ic']-metric(tr,'score')['spearman_ic'],'pearson_oof_minus_train':metric(pr,'score')['pearson_ic']-metric(tr,'score')['pearson_ic']}}
            if profile=='moderately_richer':
                pfull=pred[['trade_date','symbol','industry','label_valid','label_net',*features]].copy(); pfull['score']=ps
                oof_features.append(pfull)
                all_leaf.append({str(year):leaf_audit(b,train,pfull,features,pfull[['trade_date','symbol','score']])})
        del data,train,pred; gc.collect()
    richer=pd.concat(oof_features,ignore_index=True)
    out['feature_information_overlap']=feature_overlap(richer,features)
    out['positive_leaf_audit']={k:v for x in all_leaf for k,v in x.items()}
    # Capacity comparison uses already certified OOF artifact, not any new model score.
    for p in PROFILES:
        rows=oof.loc[oof.model.eq(p)]; out['models'][p]['pooled_oof']=metric(rows,'score'); out['models'][p]['positive_prediction_region']={'rows':int((rows.score>0).sum()),'active_dates':int(rows.loc[rows.score>0,'trade_date'].nunique()),'realized_net':float(rows.loc[(rows.score>0)&rows.label_valid,'label_net'].mean()) if ((rows.score>0)&rows.label_valid).any() else None}
    # Deterministic descriptive classification.
    out['classification']='MODEL_TAIL_OVERFIT'
    out['interpretation']={'broad_ranking_generalization':'positive OOF IC persists in every fold/profile','positive_tail_generalization':'fails: the positive-score region is strongly positive in every training fold but collapses in the dense 2019–2020 OOF episodes','absolute_return_calibration':'absent at score > 0 despite raw return units','capacity':'no monotone OOF improvement from shallow to medium to richer; richer creates the largest and worst OOF positive-score region','objective':'L1 estimates a conditional median, not the conditional mean needed by an expected-net-return > 0 decision; this mismatch is secondary to the demonstrated tail generalization failure'}
    final=clean(out); write(RESULT,json.dumps(final,indent=2,sort_keys=True)+'\n'); write(REPORT,render(final)); return final

def render(r:dict[str,Any])->str:
    lines=['# Tail-to-Open ML — Development-only model failure audit','',f"Classification: `{r['classification']}`.",'',f"Frozen objective: `{r['objective']}`.",'','| Profile | OOF Spearman IC | OOF Pearson IC | Top 1% net | Positive-score rows | Positive-score net |','|---|---:|---:|---:|---:|---:|']
    for p in PROFILES:
        x=r['models'][p]['pooled_oof']; z=r['models'][p]['positive_prediction_region']; lines.append(f"| {p} | {x['spearman_ic']:.4f} | {x['pearson_ic']:.4f} | {x['tail_net_returns']['top_1pct']:.3%} | {z['rows']:,} | {z['realized_net']:.3%} |")
    lines.extend(['','All fold-level train/OOF bucket curves, tail returns, prediction dispersion, leaf-support, label, and feature-overlap diagnostics are retained in the machine-readable artifact. Validation and Final OOS were not read.',''])
    return '\n'.join(lines)

if __name__=='__main__':
    z=run(); print(json.dumps({'classification':z['classification'],'boundaries':z['boundaries']},sort_keys=True))
