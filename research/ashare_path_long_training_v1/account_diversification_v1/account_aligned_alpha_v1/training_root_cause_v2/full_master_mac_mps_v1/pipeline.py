#!/usr/bin/env python3
"""Resumable CY-FULL-MASTER P1-P4 pipeline.

The runner uses one MPS job at a time. Large immutable features live on the
validated external volume; code/spec/results remain in the repository.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import json
import math
import multiprocessing as mp
import os
import sys
import time
import traceback
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import torch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = HERE.parents[5]
VOL = Path("/Volumes/quant/CY_quant_research/ashare_path_long_training_v1")
EXT = VOL / "account_diversification_v1/account_aligned_alpha_v1/full_master_mac_mps_v1"
CACHE = EXT / "alpha158_daily"
MODELS = EXT / "models"
PREP = EXT / "preprocessing"
PRED = EXT / "predictions"
PANEL = VOL / "panel"
FULL = VOL / "account_diversification_v1/account_aligned_alpha_v1/full_date_cross_stock_reconciliation_v1/full_forward"
MARKET_PATH = VOL / "account_diversification_v1/account_aligned_alpha_v1/master_guided_o2_joint_v1/market/MASTER_63_RAW.parquet"
SEEDS = (17, 29, 43)
ARMS = ("M-T", "M-GT", "M-TS", "M-GTS")
LRS = (1e-5, 1e-4)

sys.path.insert(0, str(HERE))
from alpha158 import PanelAlpha158  # noqa: E402
from model import FullMaster  # noqa: E402


def clean(v):
    if isinstance(v,dict): return {str(k):clean(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)): return [clean(x) for x in v]
    if isinstance(v,(np.integer,)): return int(v)
    if isinstance(v,(np.floating,float)): return float(v) if np.isfinite(v) else None
    if isinstance(v,Path): return str(v)
    return v


def dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(clean(value),ensure_ascii=False,indent=2,allow_nan=False)+"\n"); tmp.replace(path)


def sha(path: Path) -> str:
    with path.open("rb") as f: return hashlib.file_digest(f,"sha256").hexdigest()


def state(status: str, stage: str, **extra) -> None:
    dump(HERE/"ORCHESTRATION_STATE.json",{"status":status,"stage":stage,"updated_at":pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),**extra})


class Data:
    def __init__(self):
        self.axes=json.loads((PANEL/"axes.json").read_text()); self.dates=np.asarray(self.axes["dates"]); self.symbols=np.asarray(self.axes["symbols"])
        self.hard=np.load(PANEL/"hard_valid.npy",mmap_mode="r"); self.history=np.load(PANEL/"history.npy",mmap_mode="r")
        self.entry=np.load(PANEL/"entryok.npy",mmap_mode="r"); self.exit=np.load(PANEL/"exitok.npy",mmap_mode="r")
        self.coord=np.load(PANEL/"coordok.npy",mmap_mode="r"); self.adj_open=np.load(PANEL/"adj_open.npy",mmap_mode="r")
        mf=pd.read_parquet(MARKET_PATH); mf["date"]=pd.to_datetime(mf.date); self.market=mf.set_index("date")

    def universe(self,t:int)->np.ndarray: return np.flatnonzero(self.hard[t]&(self.history[t]>=60))

    def target(self,t:int,cutoff:int|None=None)->tuple[np.ndarray,np.ndarray]:
        stocks=self.universe(t); y=np.full(len(stocks),np.nan,np.float32); e=t+1; last=e+20
        if last>=len(self.dates) or (cutoff is not None and last>cutoff): return stocks,y
        good=self.entry[e,stocks]&self.exit[last,stocks]&np.all(self.coord[e:last+1,stocks],axis=0)
        y[good]=(self.adj_open[last,stocks[good]]/self.adj_open[e,stocks[good]]-1).astype(np.float32)
        if good.any(): y[good]-=float(np.nanmean(y))
        return stocks,y

    def decision_dates(self,cutoff:int,start:int|None=None,end:int|None=None)->list[int]:
        lo=0 if start is None else start; hi=cutoff if end is None else end; out=[]
        for t in range(max(lo,7),hi+1):
            if len(self.universe(t))<50: continue
            _,y=self.target(t,cutoff); 
            if np.isfinite(y).sum()>=50: out.append(t)
        return out


_WORKER_PANEL: PanelAlpha158|None=None
_WORKER_STOCKS: np.ndarray|None=None


def _init_worker():
    global _WORKER_PANEL,_WORKER_STOCKS
    warnings.filterwarnings("ignore"); _WORKER_PANEL=PanelAlpha158(PANEL); _WORKER_STOCKS=np.arange(len(_WORKER_PANEL.axes["symbols"]))


def _cache_one(t:int)->dict:
    assert _WORKER_PANEL is not None and _WORKER_STOCKS is not None
    path=CACHE/f"{t:04d}.npy"
    if path.exists(): return {"t":t,"status":"REUSED","seconds":0,"bytes":path.stat().st_size}
    began=time.monotonic(); x=_WORKER_PANEL._snapshot(t,_WORKER_STOCKS).astype(np.float16); tmp=path.with_suffix(".tmp.npy")
    np.save(tmp,x,allow_pickle=False); tmp.replace(path)
    return {"t":t,"status":"BUILT","seconds":time.monotonic()-began,"bytes":path.stat().st_size}


def build_cache(data:Data,through_year:int=2021)->None:
    CACHE.mkdir(parents=True,exist_ok=True); end=int(np.flatnonzero(data.dates<=f"{through_year}-12-31")[-1])
    legal=np.flatnonzero((data.hard[:end+1]&(data.history[:end+1]>=60)).sum(1)>=50); start=max(0,int(legal[0])-7)
    todo=[t for t in range(start,end+1) if not (CACHE/f"{t:04d}.npy").exists()]
    state("RUNNING","FEATURE_CACHE",start=start,end=end,remaining=len(todo))
    rows=[]; workers=min(8,max(1,os.cpu_count() or 1))
    if todo:
        ctx=mp.get_context("fork")
        with ctx.Pool(workers,initializer=_init_worker,maxtasksperchild=100) as pool:
            for k,row in enumerate(pool.imap_unordered(_cache_one,todo,chunksize=1),1):
                rows.append(row)
                if k%25==0: state("RUNNING","FEATURE_CACHE",completed=k,total=len(todo),last_t=row["t"])
    manifest={"status":"COMPLETE","start":start,"end":end,"dates":end-start+1,"new_files":len(rows),"workers":workers,
              "bytes":sum((CACHE/f"{t:04d}.npy").stat().st_size for t in range(start,end+1)),"source":"Qlib Alpha158 formulas; CY adjusted panel"}
    dump(CACHE/"MANIFEST.json",manifest)


def factor_sequence(t:int,stocks:np.ndarray,mean:np.ndarray,scale:np.ndarray)->np.ndarray:
    x=np.stack([np.asarray(np.load(CACHE/f"{day:04d}.npy",mmap_mode="r")[stocks],np.float32) for day in range(t-7,t+1)],axis=1)
    x=(x-mean.reshape(1,1,-1))/scale.reshape(1,1,-1)
    return np.nan_to_num(np.clip(x,-5,5),nan=0.0,posinf=5.0,neginf=-5.0).astype(np.float32)


def preprocessing(data:Data,cutoff:int,name:str)->dict:
    path=PREP/f"{name}.npz"; meta=PREP/f"{name}.json"; PREP.mkdir(parents=True,exist_ok=True)
    if path.exists() and meta.exists():
        z=np.load(path); return {"mean":z["mean"],"scale":z["scale"],"market_mean":z["market_mean"],"market_scale":z["market_scale"],"target_scale":float(z["target_scale"]),"meta":json.loads(meta.read_text())}
    dates=data.decision_dates(cutoff); count=np.zeros(158,np.int64); total=np.zeros(158); total2=np.zeros(158); ty2=0.; tyn=0
    for k,t in enumerate(dates,1):
        stocks,y=data.target(t,cutoff); x=np.asarray(np.load(CACHE/f"{t:04d}.npy",mmap_mode="r")[stocks],np.float32); ok=np.isfinite(x)
        count+=ok.sum(0); z=np.where(ok,x,0.0); total+=z.sum(0); total2+=(z*z).sum(0); good=np.isfinite(y); ty2+=float((y[good]**2).sum()); tyn+=int(good.sum())
        if k%250==0: state("RUNNING","PREPROCESSING",name=name,completed=k,total=len(dates))
    mean=total/np.maximum(count,1); var=total2/np.maximum(count,1)-mean*mean; scale=np.sqrt(np.maximum(var,1e-8)); scale=np.where(np.isfinite(scale)&(scale>1e-6),scale,1.)
    mdates=pd.to_datetime(data.dates[dates]); mx=data.market.reindex(mdates).to_numpy(float); market_mean=np.nanmedian(mx,axis=0); market_scale=np.nanmedian(np.abs(mx-market_mean),axis=0)*1.4826; market_scale=np.where(np.isfinite(market_scale)&(market_scale>1e-8),market_scale,1.)
    target_scale=math.sqrt(ty2/max(tyn,1)); np.savez(path,mean=mean.astype(np.float32),scale=scale.astype(np.float32),market_mean=market_mean.astype(np.float32),market_scale=market_scale.astype(np.float32),target_scale=np.float32(target_scale))
    md={"fit_cutoff":str(data.dates[cutoff]),"decision_dates":len(dates),"stock_dates":int(tyn),"target_scale":target_scale,"feature_rule":"training-window mean/std on current-date legal snapshots; common across temporal tokens and arms","market_rule":"training-date median/MAD*1.4826","sha256":sha(path)}; dump(meta,md)
    return {"mean":mean,"scale":scale,"market_mean":market_mean,"market_scale":market_scale,"target_scale":target_scale,"meta":md}


def market_vec(data:Data,t:int,prep:dict)->np.ndarray:
    x=data.market.reindex([pd.Timestamp(str(data.dates[t]))]).to_numpy(float)[0]; x=(x-prep["market_mean"])/prep["market_scale"]
    return np.nan_to_num(np.clip(x,-3,3),nan=0.,posinf=3.,neginf=-3.).astype(np.float32)


def matched_model(arm:str,seed:int,width:int=256)->FullMaster:
    torch.manual_seed(seed); full=FullMaster("M-GTS",d_model=width,dropout=.5,query_chunk=256,checkpoint_chunks=True)
    full_state=full.state_dict(); torch.manual_seed(seed); model=FullMaster(arm,d_model=width,dropout=.5,query_chunk=256,checkpoint_chunks=True)
    state0=model.state_dict()
    for key in list(state0):
        if key in full_state and state0[key].shape==full_state[key].shape: state0[key]=full_state[key]
    model.load_state_dict(state0); return model


def learning_curve_rows()->list[dict]:
    path=HERE/"LEARNING_CURVES.csv"
    return pd.read_csv(path).to_dict("records") if path.exists() and path.stat().st_size>20 else []


def write_curves(rows:list[dict])->None:
    pd.DataFrame(rows).sort_values(["phase","job","epoch"]).to_csv(HERE/"LEARNING_CURVES.csv",index=False)


def validate(model:FullMaster,data:Data,dates:list[int],prep:dict,device:torch.device)->float:
    model.eval(); losses=[]
    with torch.no_grad():
        for t in dates:
            stocks,y=data.target(t,int(np.flatnonzero(data.dates<="2019-12-31")[-1])); good=np.isfinite(y)
            x=torch.as_tensor(factor_sequence(t,stocks,prep["mean"],prep["scale"]),device=device); m=torch.as_tensor(market_vec(data,t,prep),device=device)
            p=model(x,m).cpu().numpy(); losses.append(float(np.mean((p[good]-y[good]/prep["target_scale"])**2)))
    return float(np.mean(losses))


def train_job(data:Data,phase:str,arm:str,seed:int,lr:float,epochs:int,cutoff:int,prep_name:str,validation:list[int]|None=None)->Path:
    job=f"{phase}_{arm}_s{seed}_lr{lr:g}"; folder=MODELS/job; folder.mkdir(parents=True,exist_ok=True); done=folder/"COMPLETE.json"
    if done.exists() and json.loads(done.read_text())["epochs"]>=epochs: return folder
    prep=preprocessing(data,cutoff,prep_name); dates=data.decision_dates(cutoff); device=torch.device("mps"); model=matched_model(arm,seed).to(device); opt=torch.optim.Adam(model.parameters(),lr=lr)
    start_epoch=1; resume_pos=0; order=None; last=folder/"LAST.pt"; active=0.
    if last.exists():
        ck=torch.load(last,map_location=device,weights_only=False); model.load_state_dict(ck["model"]); opt.load_state_dict(ck["optim"]); torch.set_rng_state(ck["torch_rng"]); np.random.set_state(ck["numpy_rng"]); start_epoch=ck["epoch"]; resume_pos=ck["position"]; order=ck["order"]; active=float(ck.get("active_seconds",0))
        if resume_pos>=len(order): start_epoch+=1; resume_pos=0; order=None
    curves=learning_curve_rows()
    for epoch in range(start_epoch,epochs+1):
        if order is None: order=np.random.default_rng(seed+epoch*1009).permutation(dates).tolist()
        model.train(); losses=[]; began=time.monotonic()
        for pos in range(resume_pos,len(order)):
            t=int(order[pos]); stocks,y=data.target(t,cutoff); good=np.isfinite(y)
            x=torch.as_tensor(factor_sequence(t,stocks,prep["mean"],prep["scale"]),device=device); m=torch.as_tensor(market_vec(data,t,prep),device=device); target=torch.as_tensor(y[good]/prep["target_scale"],device=device)
            opt.zero_grad(set_to_none=True); pred=model(x,m); loss=(pred[torch.as_tensor(good,device=device)]-target).square().mean()
            if not torch.isfinite(loss): raise RuntimeError(f"NONFINITE_LOSS {job} epoch={epoch} t={t}")
            loss.backward(); torch.nn.utils.clip_grad_value_(model.parameters(),3.0); opt.step(); losses.append(float(loss.detach().cpu()))
            if (pos+1)%100==0:
                torch.mps.synchronize(); elapsed=active+time.monotonic()-began; payload={"model":model.state_dict(),"optim":opt.state_dict(),"epoch":epoch,"position":pos+1,"order":order,"torch_rng":torch.get_rng_state(),"numpy_rng":np.random.get_state(),"active_seconds":elapsed}; tmp=last.with_suffix(".tmp"); torch.save(payload,tmp); tmp.replace(last); state("RUNNING",phase,job=job,epoch=epoch,position=pos+1,total=len(order),active_seconds=elapsed)
        torch.mps.synchronize(); active+=time.monotonic()-began; train_loss=float(np.mean(losses)); val_loss=validate(model,data,validation,prep,device) if validation else None
        ckpath=folder/f"EPOCH_{epoch:02d}.pt"; torch.save({"model":model.state_dict(),"epoch":epoch,"prep":prep_name,"arm":arm,"seed":seed,"lr":lr},ckpath)
        curves=[r for r in curves if not(r["job"]==job and int(r["epoch"])==epoch)]; curves.append({"phase":phase,"job":job,"arm":arm,"seed":seed,"lr":lr,"epoch":epoch,"train_loss":train_loss,"validation_loss":val_loss,"updates":len(order),"active_seconds_cumulative":active,"checkpoint":str(ckpath)}); write_curves(curves)
        payload={"model":model.state_dict(),"optim":opt.state_dict(),"epoch":epoch,"position":len(order),"order":order,"torch_rng":torch.get_rng_state(),"numpy_rng":np.random.get_state(),"active_seconds":active}; tmp=last.with_suffix(".tmp"); torch.save(payload,tmp); tmp.replace(last); resume_pos=0; order=None
    dump(done,{"status":"COMPLETE","phase":phase,"job":job,"arm":arm,"seed":seed,"lr":lr,"epochs":epochs,"updates":epochs*len(dates),"train_dates":len(dates),"active_seconds":active,"prep":prep_name,"last_checkpoint":str(folder/f"EPOCH_{epochs:02d}.pt")})
    return folder


def p1(data:Data)->dict:
    cutoff=int(np.flatnonzero(data.dates<="2019-06-30")[-1]); vstart=int(np.flatnonzero(data.dates>="2019-07-01")[0]); vend=int(np.flatnonzero(data.dates<="2019-12-31")[-1]); validation=data.decision_dates(vend,vstart,vend)
    for lr in LRS:
        for arm in ARMS: train_job(data,"P1",arm,17,lr,12,cutoff,"INNER_2019H1",validation)
    curves=pd.read_csv(HERE/"LEARNING_CURVES.csv"); x=curves[(curves.phase=="P1")&(curves.epoch>=3)&(curves.epoch<=12)]
    agg=x.groupby(["lr","epoch"],as_index=False).validation_loss.mean().sort_values(["validation_loss","epoch","lr"]); best=agg.iloc[0]
    # Pre-registered one-time extension applies only if both aggregate curves still improve from 10 to 12.
    by=x.groupby("epoch")[["train_loss","validation_loss"]].mean(); extend=bool(by.loc[12,"train_loss"]<by.loc[10,"train_loss"] and by.loc[12,"validation_loss"]<by.loc[10,"validation_loss"])
    selected={"lr":float(best.lr),"epoch":int(best.epoch),"extended_to_20":False,"inner_train_cutoff":str(data.dates[cutoff]),"validation_start":str(data.dates[vstart]),"validation_end":str(data.dates[vend]),"validation_dates":len(validation),"aggregate_table":agg.to_dict("records")}
    # Extension cost can exceed the 72-hour envelope; defer instead of silently exceeding it.
    if extend:
        used=sum(json.loads(p.read_text())["active_seconds"] for p in MODELS.glob("P1_*/COMPLETE.json"))/3600
        projected_extra=used*(8/12)
        if used+projected_extra<=72:
            for lr in LRS:
                for arm in ARMS: train_job(data,"P1",arm,17,lr,20,cutoff,"INNER_2019H1",validation)
            curves=pd.read_csv(HERE/"LEARNING_CURVES.csv"); x=curves[(curves.phase=="P1")&(curves.epoch>=3)&(curves.epoch<=20)]; agg=x.groupby(["lr","epoch"],as_index=False).validation_loss.mean().sort_values(["validation_loss","epoch","lr"]); best=agg.iloc[0]; selected.update(lr=float(best.lr),epoch=int(best.epoch),extended_to_20=True,aggregate_table=agg.to_dict("records"))
        else: selected["extension_not_run_reason"]="PROJECTED_72H_BUDGET"
    dump(HERE/"P1_SELECTION.json",selected); return selected


def predict_job(data:Data,year:int,arm:str,seed:int,folder:Path,epoch:int,prep_name:str)->Path:
    out=PRED/f"{year}_{arm}_s{seed}.parquet"; PRED.mkdir(parents=True,exist_ok=True)
    if out.exists(): return out
    prep=preprocessing(data,int(np.flatnonzero(data.dates<f"{year}-01-01")[-1]),prep_name); ck=torch.load(folder/f"EPOCH_{epoch:02d}.pt",map_location="mps",weights_only=False); model=matched_model(arm,seed).to("mps"); model.load_state_dict(ck["model"]); model.eval()
    keys=pd.read_parquet(FULL/str(year)/"KEYS.parquet"); rows=[]
    with torch.no_grad():
        for t,g in keys.groupby("t",sort=True):
            stocks=g.j.to_numpy(int); expected=data.universe(int(t)); assert np.array_equal(stocks,expected)
            x=torch.as_tensor(factor_sequence(int(t),stocks,prep["mean"],prep["scale"]),device="mps"); m=torch.as_tensor(market_vec(data,int(t),prep),device="mps"); score=model(x,m).cpu().numpy()*prep["target_scale"]
            rows.append(g.assign(score=score,model_id=f"{arm}_{year}_s{seed}"))
    frame=pd.concat(rows,ignore_index=True); frame.to_parquet(out,index=False); dump(out.with_suffix(".json"),{"rows":len(frame),"dates":frame.t.nunique(),"sha256":sha(out),"checkpoint":str(folder/f"EPOCH_{epoch:02d}.pt"),"checkpoint_sha256":sha(folder/f"EPOCH_{epoch:02d}.pt")}); return out


def p2_p3(data:Data,selected:dict)->None:
    lr=float(selected["lr"]); epochs=int(selected["epoch"])
    for year in (2020,2021):
        cutoff=int(np.flatnonzero(data.dates<f"{year}-01-01")[-1]); prep_name=f"PRE{year}"
        for seed in SEEDS:
            for arm in ARMS:
                folder=train_job(data,f"P{2 if seed==17 else 3}_{year}",arm,seed,lr,epochs,cutoff,prep_name,None)
                predict_job(data,year,arm,seed,folder,epochs,prep_name)


def percentile(x:np.ndarray)->np.ndarray:
    return pd.Series(x).rank(method="average",pct=True).to_numpy(float)


def evaluate_signals()->pd.DataFrame:
    sys.path.insert(0,str(ROOT/"full_date_cross_stock_reconciliation_v1")); from evaluator import evaluate_daily, aggregate_daily, paired_robustness
    rows=[]; mechanism=[]
    for year in (2020,2021):
        keys=pd.read_parquet(FULL/str(year)/"KEYS.parquet"); ret10=np.load(FULL/str(year)/"ret10.npy"); ret20=np.load(FULL/str(year)/"ret20.npy")
        base={}
        for seed in SEEDS:
            score=np.load(FULL/str(year)/f"I0_s{seed}.npy"); base[seed]=score
            frame=keys.assign(score=score,ret10=ret10,ret20=ret20); daily=evaluate_daily(frame)
            for h in (10,20):
                agg=aggregate_daily(daily); rows.append({"year":year,"seed":str(seed),"arm":"I0","horizon":h,"dates":int(daily[f"top10_ret{h}"].notna().sum()),"rankic":agg[f"rankic{h}"],"top10_return":agg[f"top10_ret{h}"],"top10_lift":agg[f"top10_lift{h}"],"top50_lift":agg[f"top50_lift{h}"]})
        allscores={"I0":base}
        for arm in ARMS:
            scores={}
            for seed in SEEDS:
                f=pd.read_parquet(PRED/f"{year}_{arm}_s{seed}.parquet"); assert np.array_equal(f[["t","j"]],keys[["t","j"]]); scores[seed]=f.score.to_numpy(float)
                daily=evaluate_daily(keys.assign(score=scores[seed],ret10=ret10,ret20=ret20))
                for h in (10,20):
                    agg=aggregate_daily(daily); rows.append({"year":year,"seed":str(seed),"arm":arm,"horizon":h,"dates":int(daily[f"top10_ret{h}"].notna().sum()),"rankic":agg[f"rankic{h}"],"top10_return":agg[f"top10_ret{h}"],"top10_lift":agg[f"top10_lift{h}"],"top50_lift":agg[f"top50_lift{h}"]})
            allscores[arm]=scores
        for arm,scores in allscores.items():
            fixed=np.empty(len(keys));
            for _,ix in keys.groupby("t",sort=False).indices.items(): fixed[ix]=np.mean([percentile(scores[s][ix]) for s in SEEDS],axis=0)
            out=PRED/f"{year}_{arm}_FIXED3.parquet"; keys.assign(score=fixed,model_id=f"{arm}_{year}_FIXED3").to_parquet(out,index=False)
            daily=evaluate_daily(keys.assign(score=fixed,ret10=ret10,ret20=ret20)); daily.to_parquet(PRED/f"{year}_{arm}_FIXED3_DAILY.parquet",index=False)
            for h in (10,20):
                agg=aggregate_daily(daily); rows.append({"year":year,"seed":"FIXED3","arm":arm,"horizon":h,"dates":int(daily[f"top10_ret{h}"].notna().sum()),"rankic":agg[f"rankic{h}"],"top10_return":agg[f"top10_ret{h}"],"top10_lift":agg[f"top10_lift{h}"],"top50_lift":agg[f"top50_lift{h}"]})
        # Factorial paired Top10 Ret20 effects use four-arm common daily support.
        d={a:pd.read_parquet(PRED/f"{year}_{a}_FIXED3_DAILY.parquet") for a in ARMS}
        common=d[ARMS[0]][["t","top10_ret20"]].rename(columns={"top10_ret20":ARMS[0]})
        for a in ARMS[1:]: common=common.merge(d[a][["t","top10_ret20"]].rename(columns={"top10_ret20":a}),on="t",validate="one_to_one")
        common=common.dropna(); effects={"S_EFFECT_NO_GATE":common["M-TS"]-common["M-T"],"S_EFFECT_WITH_GATE":common["M-GTS"]-common["M-GT"],"G_EFFECT_NO_STOCK":common["M-GT"]-common["M-T"],"G_EFFECT_WITH_STOCK":common["M-GTS"]-common["M-TS"]}
        effects["INTERACTION"]=effects["S_EFFECT_WITH_GATE"]-effects["S_EFFECT_NO_GATE"]
        for name,z in effects.items(): mechanism.append({"year":year,"comparison":name,"metric":"paired_top10_ret20","dates":len(z),"mean":z.mean(),"positive_fraction":float((z>0).mean()),"leave_best1":z.drop(z.idxmax()).mean(),"leave_best3":z.drop(z.nlargest(3).index).mean()})
    result=pd.DataFrame(rows); result.to_csv(HERE/"SIGNAL_AND_FACTORIAL_RESULTS.csv",index=False); pd.DataFrame(mechanism).to_csv(HERE/"MECHANISM_DIAGNOSTICS.csv",index=False)
    manifest=[]
    for p in sorted(PRED.glob("*.parquet")): manifest.append({"path":str(p),"sha256":sha(p),"bytes":p.stat().st_size})
    dump(HERE/"FULL_DAILY_PREDICTIONS_MANIFEST.json",{"status":"COMPLETE_2020_2021","artifacts":manifest,"2022":"NOT_OPENED_PENDING_GATE","2023":"NOT_OPENED","2024_2026":"SEALED"})
    return result


def ledger()->None:
    rows=[]
    for p in sorted(MODELS.glob("*/COMPLETE.json")): rows.append(json.loads(p.read_text()))
    pd.DataFrame(rows).to_csv(HERE/"TRAINING_LEDGER.csv",index=False)


def run()->None:
    lock=HERE/"PIPELINE.lock"
    if lock.exists():
        try:
            pid=int(lock.read_text()); os.kill(pid,0); raise RuntimeError(f"ACTIVE_PIPELINE_PID={pid}")
        except ProcessLookupError: lock.unlink()
    lock.write_text(str(os.getpid()))
    try:
        data=Data(); build_cache(data,2021); state("RUNNING","P1_INNER")
        selected=p1(data); ledger()
        used=sum(json.loads(p.read_text()).get("active_seconds",0) for p in MODELS.glob("*/COMPLETE.json"))/3600
        epoch_hours=json.loads((HERE/"DECISION_PACKET.json").read_text())["budget"]["pre2020_epoch_hours"]+json.loads((HERE/"DECISION_PACKET.json").read_text())["budget"]["pre2021_epoch_hours"]
        projected=4*3*selected["epoch"]*epoch_hours
        if used+projected>72:
            state("COMPLETE","P1_COMPUTE_LIMITED",used_training_hours=used,projected_development_hours=projected)
            finalize("INCONCLUSIVE_TRAINING_OR_COMPUTE_LIMITED",selected,None,"P1 complete; frozen E* formal matrix would exceed remaining 72-hour training budget.")
            return
        state("RUNNING","P2_P3_FORMAL",selection=selected); p2_p3(data,selected); ledger(); state("RUNNING","SIGNAL_EVALUATION"); signal=evaluate_signals()
        # Account replay is a separate deterministic stage; mark Codex handoff if this process reaches it.
        state("BLOCKED_NEEDS_CODEX","P4_ACCOUNT_ADAPTER",selection=selected,reason="Formal signals complete; canonical account adapter and qualification/finalization required.")
    except Exception as exc:
        dump(HERE/"ERROR_PACKET.json",{"error":f"{type(exc).__name__}: {exc}","traceback":traceback.format_exc(),"pid":os.getpid()}); state("BLOCKED_NEEDS_CODEX","ERROR",error=str(exc)); raise
    finally:
        with contextlib.suppress(FileNotFoundError): lock.unlink()


def finalize(status:str,selected:dict|None,signal:pd.DataFrame|None,reason:str)->None:
    packet=json.loads((HERE/"DECISION_PACKET.json").read_text())
    packet.update({"FINAL_STATUS":status,"SELECTED_LR":selected.get("lr") if selected else None,
                   "TRUE_EPOCHS":selected.get("epoch") if selected else None,"reason":reason,
                   "NEW_TRAINING_TRAJECTORIES":len(list(MODELS.glob("*/COMPLETE.json"))),
                   "2023_NEWLY_OPENED_IN_THIS_TASK":False,"SEALED_2024_2026_NEWLY_OPENED_IN_THIS_TASK":False,
                   "PRODUCTION_APPROVED":False})
    dump(HERE/"DECISION_PACKET.json",packet)


if __name__=="__main__": run()
