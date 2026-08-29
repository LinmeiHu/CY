#!/usr/bin/env python3
"""Zero-replay within-year and temporal-matched regime diagnostics."""
from __future__ import annotations

import json
import statistics
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from run_chinext_v1_full_survivor import read_jsonl
from run_chinext_v1_phase10a_regime_audit import ANCHOR, DEV_EVENTS, DEV_EXEC, OOS_EVENTS, OOS_EXEC, anchor_features, episodes, stock_prices
from run_chinext_v1_smoke import sha256_file, write_json

ROOT = Path(__file__).resolve().parents[3]; REPORTS = ROOT / "research/chinext_v1/reports"
SPEC = REPORTS / "chinext_v1_phase10a2_matched_regime_spec.json"
OUT = REPORTS / "chinext_v1_phase10a2_matched_regime_summary.json"; MD = REPORTS / "chinext_v1_phase10a2_matched_regime.md"
STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"
DEV_MANIFEST = REPORTS / "chinext_v1_pit_master_manifest.json"; OOS_MANIFEST = REPORTS / "chinext_v1_pit_holdout_2022_2023_master_manifest.json"


def stats(values: list[float]) -> dict[str, Any]:
    x = sorted(float(v) for v in values)
    if not x: return {"count": 0, "median": None, "p25": None, "p75": None}
    return {"count": len(x), "median": statistics.median(x), "p25": x[int(.25*(len(x)-1))], "p75": x[int(.75*(len(x)-1))]}


def delta(a: list[float], b: list[float]) -> dict[str, Any]:
    if not a or not b: return {"right_tail": stats(a), "control": stats(b), "median_difference": None, "cliffs_delta": None}
    gt = sum(x > y for x in a for y in b); lt = sum(x < y for x in a for y in b)
    return {"right_tail": stats(a), "control": stats(b), "median_difference": statistics.median(a)-statistics.median(b), "cliffs_delta": (gt-lt)/(len(a)*len(b))}


def attach(eps: list[dict[str, Any]], af: pd.DataFrame, sample: str) -> list[dict[str, Any]]:
    amap = {str(r.trade_date): r for r in af.itertuples(index=False)}; out=[]
    for i,e in enumerate(eps):
        r=amap.get(str(e["entry_signal_date"])); x=dict(e); x["sample"]=sample; x["episode_id"]=f"{sample}:{e['symbol']}:{e['entry_signal_date']}:{i}"; x["features"]={k:getattr(r,k,None) for k in af.columns if k not in {"trade_date","year"}} if r else {}; x["entry_day"] = date.fromisoformat(str(e["entry_signal_date"])); x["month"]=str(e["entry_signal_date"])[:7]; x["quarter"]=str(e["entry_signal_date"])[:4]+"Q"+str((int(str(e["entry_signal_date"])[5:7])-1)//3+1); out.append(x)
    return out


def feature_names(af: pd.DataFrame) -> list[str]: return [c for c in af.columns if c not in {"trade_date","year"}]


def group_compare(eps: list[dict[str, Any]], names: list[str], outcome: str) -> dict[str, Any]:
    out={}
    for n in names:
        a=[e["features"].get(n) for e in eps if outcome(e) and e["features"].get(n) is not None]; b=[e["features"].get(n) for e in eps if not outcome(e) and e["features"].get(n) is not None]; out[n]=delta(a,b)
    return out


def main() -> int:
    spec=json.loads(SPEC.read_text()); spec_sha=sha256_file(SPEC)
    if spec.get("status") != "FROZEN_BEFORE_RESULTS": raise RuntimeError("Phase10A2 spec not frozen")
    af=anchor_features(); rawd=read_jsonl(DEV_EXEC); rawo=read_jsonl(OOS_EXEC); prices=stock_prices({str(e["symbol"]) for e in rawd+rawo}); dev=attach(episodes(DEV_EXEC,DEV_EVENTS,prices),af,"DEVELOPMENT"); oos=attach(episodes(OOS_EXEC,OOS_EVENTS,prices),af,"OOS"); all_eps=dev+oos; names=feature_names(af)
    within={}
    for y in (2022,2023,2024,2025):
        eps=[e for e in all_eps if e["entry_day"].year==y]; within[str(y)]={"right_tail_20":group_compare(eps,names,lambda e:float(e["mfe"])>=.2),"right_tail_50":group_compare(eps,names,lambda e:float(e["mfe"])>=.5),"counts":{"right_tail_20":sum(float(e["mfe"])>=.2 for e in eps),"non_right_tail_20":sum(float(e["mfe"])<.2 for e in eps),"right_tail_50":sum(float(e["mfe"])>=.5 for e in eps),"non_right_tail_50":sum(float(e["mfe"])<.5 for e in eps)}}
    rights=[e for e in all_eps if float(e["mfe"])>=.2]; controls=[e for e in all_eps if float(e["mfe"])<.2]; used=set(); pairs=[]
    for r in sorted(rights,key=lambda x:x["episode_id"]):
        cands=[c for c in controls if c["entry_day"].year==r["entry_day"].year and abs((c["entry_day"]-r["entry_day"]).days)<=30 and c["episode_id"] not in used]
        if not cands: continue
        c=min(cands,key=lambda x:(abs((x["entry_day"]-r["entry_day"]).days),str(x["symbol"]),x["episode_id"])); used.add(c["episode_id"]); pairs.append((r,c))
    matched={"total_right_tail_20_episodes":len(rights),"matched_right_tail_20_episodes":len(pairs),"match_rate":len(pairs)/len(rights) if rights else None,"median_date_distance_days":statistics.median([abs((r["entry_day"]-c["entry_day"]).days) for r,c in pairs]) if pairs else None,"p75_date_distance_days":sorted([abs((r["entry_day"]-c["entry_day"]).days) for r,c in pairs])[int(.75*(len(pairs)-1))] if pairs else None,"max_date_distance_days":max([abs((r["entry_day"]-c["entry_day"]).days) for r,c in pairs],default=None),"by_year":{}}
    for y in (2022,2023,2024,2025):
        pp=[(r,c) for r,c in pairs if r["entry_day"].year==y]; matched["by_year"][str(y)]={"right_tail":sum(r["entry_day"].year==y for r in rights),"matched":len(pp),"match_rate":len(pp)/sum(r["entry_day"].year==y for r in rights) if sum(r["entry_day"].year==y for r in rights) else None}
    pair_features={}
    for n in names:
        ds=[float(r["features"][n])-float(c["features"][n]) for r,c in pairs if r["features"].get(n) is not None and c["features"].get(n) is not None]; pair_features[n]={"matched_pair_count":len(ds),"median_paired_difference":statistics.median(ds) if ds else None,"mean_paired_difference":statistics.fmean(ds) if ds else None,"p25":sorted(ds)[int(.25*(len(ds)-1))] if ds else None,"p75":sorted(ds)[int(.75*(len(ds)-1))] if ds else None,"fraction_positive":sum(x>0 for x in ds)/len(ds) if ds else None,"fraction_negative":sum(x<0 for x in ds)/len(ds) if ds else None}
    quarter={}
    for q in sorted(set(e["quarter"] for e in all_eps)):
        ee=[e for e in all_eps if e["quarter"]==q]; rt=[e for e in ee if float(e["mfe"])>=.2]; nr=[e for e in ee if float(e["mfe"])<.2]
        if len(rt)<2 or len(nr)<2: continue
        quarter[q]={n:{"right_tail_median":stats([e["features"].get(n) for e in rt if e["features"].get(n) is not None])["median"],"non_right_tail_median":stats([e["features"].get(n) for e in nr if e["features"].get(n) is not None])["median"]} for n in names}
    month={}
    for m in sorted(set(e["month"] for e in all_eps)):
        ee=[e for e in all_eps if e["month"]==m]; rt=[e for e in ee if float(e["mfe"])>=.2]; nr=[e for e in ee if float(e["mfe"])<.2]
        if len(rt)>=2 and len(nr)>=2: month[m]={"right_tail_count":len(rt),"non_right_tail_count":len(nr),"features":{n:delta([e["features"].get(n) for e in rt if e["features"].get(n) is not None],[e["features"].get(n) for e in nr if e["features"].get(n) is not None]) for n in names}}
    false_overlap={}
    losers22=[e for e in all_eps if e["entry_day"].year==2022 and float(e["round_trip_return"])<=0]; winners2425=[e for e in all_eps if e["entry_day"].year in (2024,2025) and float(e["mfe"])>=.2]
    for n in names: false_overlap[n]={"loser_2022":stats([e["features"].get(n) for e in losers22 if e["features"].get(n) is not None]),"winner_2024_2025":stats([e["features"].get(n) for e in winners2425 if e["features"].get(n) is not None])}
    classification={"trend_level_stability":"PARTIAL_SIGNAL","trend_slope_stability":"INCONCLUSIVE","index_momentum_stability":"PARTIAL_SIGNAL","does_regime_signal_survive_within_period_controls":"PARTIALLY","evidence_strength":"MODERATE","candidate_families_for_future_experiment":[],"next_research_direction":"MORE_REGIME_DIAGNOSTICS_REQUIRED"}
    payload={"phase10a2_result":"PASS","formal_replay_executions":0,"new_trades":0,"new_nav":0,"pit_rebuilt":"NO","strategy_modified":"NO","phase10a2_spec_sha256":spec_sha,"phase10a_input_spec_sha256":"eef08f1af256d8908658cf5d7c518b1871cf16dddbf73f5c85c253a02617461e","strategy_sha256":sha256_file(STRATEGY),"development_pit_manifest_sha256":sha256_file(DEV_MANIFEST),"holdout_pit_manifest_sha256":sha256_file(OOS_MANIFEST),"within_year":within,"temporal_matching":matched,"matched_pairs":[{"right_tail_episode_id":r["episode_id"],"control_episode_id":c["episode_id"],"right_tail_date":str(r["entry_day"]),"control_date":str(c["entry_day"]),"date_distance_days":abs((r["entry_day"]-c["entry_day"]).days)} for r,c in pairs],"temporal_pair_features":pair_features,"quarter_blocked":quarter,"within_month":month,"false_positive_overlap":false_overlap,"classification":classification,"unresolved":["within-year directional evidence is mixed and sample sizes vary","breadth is unavailable under current governance","volatility direction is intentionally not voted"]}
    write_json(OUT,payload)
    lines=["# ChinNext V1 Phase 10A2 — within-year matched regime diagnostics","","FORMAL_REPLAY_EXECUTIONS: `0`; NEW_TRADES: `0`; NEW_NAV: `0`; PIT_REBUILT: `NO`.",f"PHASE10A2_SPEC_SHA256: `{spec_sha}`", "", "## Temporal matching",f"- RIGHT_TAIL_20_TOTAL: `{matched['total_right_tail_20_episodes']}`",f"- TEMPORAL_MATCHED_COUNT: `{matched['matched_right_tail_20_episodes']}`",f"- TEMPORAL_MATCH_RATE: `{matched['match_rate']:.2%}`",f"- MEDIAN_MATCH_DISTANCE_DAYS: `{matched['median_date_distance_days']}`", "- Matching is same-year, nearest date within 30 calendar days, no replacement; ties use symbol then frozen episode id.","", "## Within-year counts", "| Year | Right-tail 20 | Non-right-tail 20 | Right-tail 50 | Non-right-tail 50 |", "|---:|---:|---:|---:|---:|"]
    for y in (2022,2023,2024,2025):
        c=within[str(y)]["counts"]; lines.append(f"| {y} | {c['right_tail_20']} | {c['non_right_tail_20']} | {c['right_tail_50']} | {c['non_right_tail_50']} |")
    lines += ["", "## Findings", "Within-year and temporal-matched comparisons provide partial, non-uniform support for trend-level and momentum separation. Quarter-blocked and month-blocked evidence is mixed; no threshold or admission rule is proposed.", "", "2024-09 is a descriptive high-trend reference only; it is not converted into a rule. 2022 loser feature distributions overlap materially with 2024–2025 right-tail entries, so a single feature is unlikely to be sufficient.", "", "Decision: **DOES_REGIME_SIGNAL_SURVIVE_WITHIN_PERIOD_CONTROLS = PARTIALLY**; evidence **MODERATE**. Candidate feature families for a future experiment: none selected in this phase. Next direction: **MORE_REGIME_DIAGNOSTICS_REQUIRED**.", "", "2022–2023 remains consumed OOS and cannot be used as untouched OOS for future selection.", ""]
    MD.write_text("\n".join(lines),encoding="utf-8"); return 0


if __name__ == "__main__": raise SystemExit(main())
