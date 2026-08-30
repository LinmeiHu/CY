#!/usr/bin/env python3
"""Execute EXP-OBL-016 against frozen minimum-volume support lineage."""
from __future__ import annotations
import json, sys
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[4]
WORK=ROOT/"research/chinext_v1/original_breakout_lineage"
SCRIPTS=WORK/"scripts"
if str(SCRIPTS) not in sys.path: sys.path.insert(0,str(SCRIPTS))
import run_lineage_outcome_reveal as stats  # noqa: E402

SPEC=WORK/"experiments/EXP-OBL-016_spec.json"
FEATURES=WORK/"artifacts/minvol_support_features.csv"
ASSIGNMENTS=WORK/"artifacts/minvol_support_assignments.csv"
OUTCOMES=ROOT/"research/chinext_v1/regime_attribution/artifacts/trade_mechanism_attribution.csv"
CONTROLS=ROOT/"research/chinext_v1/regime_attribution/artifacts/pre_entry_transitions.csv"
TRADES=ROOT/"research/chinext_v1/regime_attribution/artifacts/yearly_trades.csv"
OUTPUT=WORK/"artifacts/minvol_support_outcome_reveal.csv"
RESULT=WORK/"artifacts/EXP-OBL-016_result.json"
REPORT=WORK/"reports/EXP-OBL-016_minvol_support_outcome_reveal.md"
EVIDENCE=WORK/"reports/EXP-OBL-016_evidence_packet.md"
PREDICTOR="support_held"
ENDPOINTS=stats.PRIMARY_ENDPOINTS
CONTROLS_FIXED=(*stats.CONTROL_COLUMNS,"minimum_volume_ratio","sessions_since_minimum_volume")

class RevealError(RuntimeError): pass
def path(raw:str)->Path:
    p=Path(raw); return p if p.is_absolute() else ROOT/p
def validate()->tuple[dict[str,Any],dict[str,str]]:
    spec=json.loads(SPEC.read_text())
    if spec.get("experiment_id")!="EXP-OBL-016" or spec.get("status")!="FROZEN_BEFORE_FIRST_OUTCOME_JOIN": raise RevealError("reveal identity/status changed")
    ids={}; bad={}
    for role,b in spec["input_bindings"].items():
        p=path(b["path"]); actual=stats.sha256_file(p) if p.is_file() else "MISSING"; ids[str(p)]=actual
        if actual!=b["sha256"]: bad[role]={"expected":b["sha256"],"actual":actual}
    if bad: raise RevealError(f"frozen input mismatch: {bad}")
    return spec,ids
def load(spec:dict[str,Any])->pd.DataFrame:
    a=pd.read_csv(ASSIGNMENTS); f=pd.read_csv(FEATURES)
    o=pd.read_csv(OUTCOMES,usecols=["trade_id","mfe","round_trip_return","realized_pnl","opportunity20","false_breakout","severe_loss"])
    c=pd.read_csv(CONTROLS,usecols=["trade_id","entry_industry",*stats.CONTROL_COLUMNS])
    t=pd.read_csv(TRADES,usecols=["trade_id","entry_execution_date","mae","holding_trading_days","canonical_exit_reason"])
    for name,x in (("assignments",a),("features",f),("outcomes",o),("controls",c),("trades",t)):
        if len(x)!=399 or x.trade_id.nunique()!=399: raise RevealError(f"{name} population changed")
    x=a.merge(f,on=["trade_id","baseline_block","symbol","entry_signal_date","entry_year"],validate="one_to_one").merge(o,on="trade_id",validate="one_to_one").merge(c,on="trade_id",validate="one_to_one").merge(t,on="trade_id",validate="one_to_one")
    x[PREDICTOR]=x.support_lineage_id.eq("L_SUPPORT_HELD").astype(float)
    x["neighbor_support_held"]=x.neighbor_support_lineage_id.eq("L_SUPPORT_HELD").astype(float)
    for col in ("opportunity20","false_breakout","severe_loss"): x[col]=x[col].astype(bool)
    x["non_false_breakout"]=(~x.false_breakout).astype(float); x["extreme_winner"]=x.round_trip_return>=.50
    actual={k:int(x[k].sum()) for k in spec["population"]["expected_outcome_counts"]}
    if actual!=spec["population"]["expected_outcome_counts"]: raise RevealError(f"outcome counts changed: {actual}")
    if x.support_lineage_id.value_counts().to_dict()!={"L_SUPPORT_BROKEN":267,"L_SUPPORT_HELD":132}: raise RevealError("freeze counts changed")
    x["entry_year"]=x.entry_year.astype(int); return x
def packet(frame:pd.DataFrame,predictor:str,endpoint:str)->dict[str,Any]: return stats.endpoint_packet(frame,predictor,endpoint,CONTROLS_FIXED)
def analyze(frame:pd.DataFrame,spec:dict[str,Any])->dict[str,Any]:
    primary={e:packet(frame,PREDICTOR,e) for e in ENDPOINTS}; q=stats.benjamini_hochberg({e:primary[e]["raw"]["pvalue"] for e in ENDPOINTS})
    for e in ENDPOINTS: primary[e]["raw_bh_qvalue"]=q[e]
    attacks={"neighbor":{e:packet(frame,"neighbor_support_held",e) for e in ENDPOINTS}}
    samples={"ex_top1pct":frame[~frame.trade_id.isin(set(frame.assign(abs_pnl=frame.realized_pnl.abs()).nlargest(4,"abs_pnl").trade_id))],"ex_extreme_winners":frame[~frame.extreme_winner],"ex_severe_losses":frame[~frame.severe_loss],"ex_2025":frame[frame.entry_year!=2025]}
    attacks.update({n:{e:stats.association(s,PREDICTOR,e) for e in ENDPOINTS} for n,s in samples.items()})
    d=pd.get_dummies(frame.canonical_exit_reason.astype(str),prefix="exit",drop_first=True,dtype=float); h=pd.concat([frame.reset_index(drop=True),d.reset_index(drop=True)],axis=1); h,years=stats.add_year_dummies(h)
    attacks["duration_exit"]={e:stats.partial_rank(h,PREDICTOR,e,(*CONTROLS_FIXED,"holding_trading_days",*tuple(d.columns),*years)) for e in ENDPOINTS}
    attacks["security"]={e:stats.leave_group_out(frame,"symbol",PREDICTOR,e) for e in ENDPOINTS}; attacks["industry"]={e:stats.leave_group_out(frame,"entry_industry",PREDICTOR,e) for e in ENDPOINTS}
    g=spec["decision_gates"]
    raw=all(primary[e]["raw"]["rho"]>=g["raw_minimum_rho"] and primary[e]["raw_loyo"]["positive"]>=g["raw_minimum_positive_loyo"] and primary[e]["raw_bh_qvalue"]<=g["maximum_bh_qvalue"] for e in ENDPOINTS)
    ctl=all(primary[e]["controlled"]["partial_rank_rho"]>=g["controlled_minimum_rho"] and primary[e]["controlled_loyo"]["positive"]>=g["controlled_minimum_positive_loyo"] for e in ENDPOINTS)
    temporal=all(sum(v["rho"]>0 for v in primary[e]["blocks"].values())>=g["minimum_positive_blocks"] and min(v["rho"] for v in primary[e]["blocks"].values())>g["minimum_block_rho_exclusive"] for e in ENDPOINTS)
    falsify=all(attacks[n][e]["rho"]>0 for n in samples for e in ENDPOINTS) and all(attacks["neighbor"][e]["raw"]["rho"]>0 and attacks["duration_exit"][e]["partial_rank_rho"]>0 for e in ENDPOINTS) and all(attacks[n][e]["positive_fraction"]>=.85 and attacks[n][e]["minimum"]>-.02 for n in ("security","industry") for e in ENDPOINTS)
    gates={"raw":raw,"controlled":ctl,"temporal":temporal,"falsification":falsify}; support={e:primary[e]["raw"]["rho"]>=g["raw_minimum_rho"] and primary[e]["controlled"]["partial_rank_rho"]>=g["controlled_minimum_rho"] for e in ENDPOINTS}
    decision="VALIDATE" if all(gates.values()) else ("REFINE" if any(support.values()) else "REJECTED")
    return {"experiment_id":"EXP-OBL-016","hypothesis_id":"H-OBL-012","lineage_freeze_id":"LINEAGE-OBL-015-65FA3D5627E3182F","population":{"events":len(frame)},"primary":primary,"attacks":attacks,"gates":gates,"decision":decision,"endpoint_support":support,"interpretation_boundary":"No threshold, rule, V1 change, or CY-011 access."}
def main()->None:
    spec,ids=validate(); frame=load(spec); result=analyze(frame,spec); result["input_identities"]=ids
    cols=["trade_id","baseline_block","symbol","entry_signal_date","entry_year","support_lineage_id","neighbor_support_lineage_id",PREDICTOR,"neighbor_support_held","minimum_volume_ratio","minimum_volume_location","sessions_since_minimum_volume",*ENDPOINTS,"round_trip_return","realized_pnl","mae","false_breakout","extreme_winner","severe_loss","holding_trading_days","canonical_exit_reason","entry_industry",*stats.CONTROL_COLUMNS]
    stats.atomic_csv(OUTPUT,frame[cols].sort_values("trade_id")); result["output_table_sha256"]=stats.sha256_file(OUTPUT); stats.atomic_write(RESULT,json.dumps(stats.clean_json(result),indent=2,sort_keys=True)+"\n")
    lines=["# EXP-OBL-016 minimum-volume support reveal","",f"Decision: `{result['decision']}`.","",f"Gates: `{json.dumps(result['gates'],sort_keys=True)}`.",""]
    for e in ENDPOINTS: lines.append(f"- {e}: raw `{result['primary'][e]['raw']['rho']:.6f}`, controlled `{result['primary'][e]['controlled']['partial_rank_rho']:.6f}`")
    stats.atomic_write(REPORT,"\n".join(lines)+"\n"); stats.atomic_write(EVIDENCE,"# EXP-OBL-016 evidence packet\n\n"+"\n".join(lines[2:])+"\n")
    print(json.dumps(stats.clean_json(result),sort_keys=True))
if __name__=="__main__": main()
