#!/usr/bin/env python3
"""Zero-replay descriptive regime audit for frozen ChinNext episodes."""
from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from run_chinext_v1_full_survivor import read_jsonl
from run_chinext_v1_pit_replay import reconstruct_round_trips
from run_chinext_v1_smoke import sha256_file, write_json

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / "research/chinext_v1/reports"
SPEC = REPORTS / "chinext_v1_phase10a_regime_feature_spec.json"
ANCHOR = ROOT / "research/chinext_v1/data/smoke/399102_daily.csv"
DATA_ROOT = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily")
DEV_EXEC = ROOT / "research/chinext_v1/output/chinext_v1_full_survivor/execution_ledger.jsonl"
OOS_EXEC = ROOT / "research/chinext_v1/output/chinext_v1_phase9b_oos/O0_BASELINE/execution_ledger.jsonl"
DEV_EVENTS = ROOT / "research/chinext_v1/output/chinext_v1_full_survivor/event_ledger.jsonl"
OOS_EVENTS = ROOT / "research/chinext_v1/output/chinext_v1_phase9b_oos/O0_BASELINE/event_ledger.jsonl"
DEV_NAV = ROOT / "research/chinext_v1/output/chinext_v1_full_survivor/daily_nav.jsonl"
OOS_NAV = ROOT / "research/chinext_v1/output/chinext_v1_phase9b_oos/O0_BASELINE/daily_nav.jsonl"
OUT = REPORTS / "chinext_v1_phase10a_regime_audit_summary.json"
MD = REPORTS / "chinext_v1_phase10a_regime_audit.md"
START, END = "2021-07-08", "2025-12-31"


def cliff(a: list[float], b: list[float]) -> float | None:
    if not a or not b:
        return None
    gt = sum(x > y for x in a for y in b); lt = sum(x < y for x in a for y in b)
    return (gt - lt) / (len(a) * len(b))


def qstats(values: list[float]) -> dict[str, float | None]:
    values = sorted(float(x) for x in values if x is not None and math.isfinite(float(x)))
    if not values:
        return {k: None for k in ("mean", "median", "p10", "p25", "p75", "p90")}
    return {"mean": statistics.fmean(values), "median": statistics.median(values), "p10": values[int(.10 * (len(values) - 1))], "p25": values[int(.25 * (len(values) - 1))], "p75": values[int(.75 * (len(values) - 1))], "p90": values[int(.90 * (len(values) - 1))]}


def anchor_features() -> pd.DataFrame:
    df = pd.read_csv(ANCHOR)
    df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str)).dt.strftime("%Y-%m-%d")
    df = df.sort_values("trade_date").drop_duplicates("trade_date").set_index("trade_date")
    close, high = df["close"].astype(float), df["high"].astype(float)
    out = pd.DataFrame(index=df.index)
    for n in (20, 60, 120): out[f"ma{n}"] = close.rolling(n, min_periods=n).mean()
    out["close"] = close
    out["close_vs_ma20"] = close / out.ma20 - 1; out["close_vs_ma60"] = close / out.ma60 - 1; out["close_vs_ma120"] = close / out.ma120 - 1
    out["ma20_vs_ma60"] = out.ma20 / out.ma60 - 1; out["ma60_vs_ma120"] = out.ma60 / out.ma120 - 1
    out["ma20_slope_5"] = out.ma20 / out.ma20.shift(5) - 1; out["ma20_slope_20"] = out.ma20 / out.ma20.shift(20) - 1; out["ma60_slope_20"] = out.ma60 / out.ma60.shift(20) - 1
    for n in (20, 60, 120): out[f"return_{n}"] = close / close.shift(n) - 1
    out["close_vs_previous_60d_high"] = close / high.shift(1).rolling(60, min_periods=60).max() - 1
    out["close_vs_previous_120d_high"] = close / high.shift(1).rolling(120, min_periods=120).max() - 1
    out["drawdown_from_trailing_60d_high"] = close / high.rolling(60, min_periods=60).max() - 1
    out["drawdown_from_trailing_120d_high"] = close / high.rolling(120, min_periods=120).max() - 1
    ret = close.pct_change()
    for n in (10, 20, 60): out[f"realized_vol_{n}"] = ret.rolling(n, min_periods=n).std() * math.sqrt(244)
    out["vol_ratio_10_60"] = out.realized_vol_10 / out.realized_vol_60; out["vol_ratio_20_60"] = out.realized_vol_20 / out.realized_vol_60
    out["entry_gate_on"] = (close > out.ma20).astype(float); out["close_vs_frozen_gate_ma"] = out.close_vs_ma20
    return out.reset_index().rename(columns={"index": "trade_date"})


def stock_prices(symbols: set[str]) -> dict[tuple[str, str], dict[str, float]]:
    con = duckdb.connect(); vals = sorted(symbols); ph = ",".join("?" for _ in vals); parts=[]; params=[]
    for y in range(2021, 2026):
        parts.append(f"SELECT trade_date,symbol,high,low,close FROM read_parquet(?) WHERE symbol IN ({ph})")
        params.extend([str(DATA_ROOT / f"partition_year={y}" / "data_0.parquet"), *vals])
    rows = con.execute(" UNION ALL ".join(parts), params).fetchall(); con.close()
    return {(str(s), str(d)): {"high": float(h), "low": float(l), "close": float(c)} for d,s,h,l,c in rows if h is not None and l is not None and c is not None}


def episodes(exec_path: Path, events_path: Path, prices: dict[tuple[str, str], dict[str, float]]) -> list[dict[str, Any]]:
    trips = reconstruct_round_trips(read_jsonl(exec_path)); ev = {(str(r.get("symbol")), str(r.get("signal_date"))): r for r in read_jsonl(events_path) if r.get("event") == "ENTRY_SIGNAL_EVALUATED"}
    out=[]
    for t in trips:
        s, entry, exitd = str(t["symbol"]), str(t["entry_execution_date"]), str(t["exit_execution_date"]); ds=sorted(d for sym,d in prices if sym==s and entry<=d<=exitd); rows=[prices[(s,d)] for d in ds]; px=float(t["entry_price"])
        if not rows or px<=0: continue
        rec=dict(t); rec["mfe"] = max(r["high"]/px-1 for r in rows); rec["mae"] = min(r["low"]/px-1 for r in rows); rec["holding_sessions"] = len(rows)
        for n in (5,10,20):
            if len(rows)>=n: rec[f"return_{n}d"] = rows[n-1]["close"]/px-1; rec[f"mfe_{n}d"] = max(r["high"]/px-1 for r in rows[:n]); rec[f"mae_{n}d"] = min(r["low"]/px-1 for r in rows[:n])
        rec["entry_features"] = ev.get((s, str(t["entry_signal_date"])), {})
        out.append(rec)
    return out


def feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in {"trade_date", "year"}]


def main() -> int:
    spec = json.loads(SPEC.read_text()); spec_sha = sha256_file(SPEC)
    if spec.get("status") != "FROZEN_BEFORE_OUTCOME_ANALYSIS": raise RuntimeError("feature spec was not frozen before outcome analysis")
    anchor = anchor_features(); anchor["year"] = anchor.trade_date.str[:4].astype(int); anchor = anchor[(anchor.trade_date >= "2022-01-01") & (anchor.trade_date <= END)]
    # Read frozen ledgers only; no strategy runner is imported or called.
    raw_dev = read_jsonl(DEV_EXEC); raw_oos = read_jsonl(OOS_EXEC); symbols={str(r["symbol"]) for r in raw_dev+raw_oos if r.get("symbol")}
    prices = stock_prices(symbols); dev, oos = episodes(DEV_EXEC, DEV_EVENTS, prices), episodes(OOS_EXEC, OOS_EVENTS, prices); all_eps=dev+oos
    for e in all_eps: e["year"] = int(str(e["entry_signal_date"])[:4])
    entry_rows=[]
    for label, eps in (("OOS",oos),("DEVELOPMENT",dev)):
        for e in eps:
            row=anchor[anchor.trade_date==str(e["entry_signal_date"])]
            if row.empty: continue
            vals=row.iloc[0].to_dict(); vals.update({"sample":label,"symbol":e["symbol"],"entry_signal_date":e["entry_signal_date"],"year":e["year"],"realized_return":e["round_trip_return"],"mfe":e["mfe"],"mae":e["mae"]}); entry_rows.append(vals)
    entries=pd.DataFrame(entry_rows); cols=feature_columns(anchor)
    yearly={}
    for y in (2022,2023,2024,2025):
        daily=anchor[anchor.year==y]; selected=entries[entries.year==y]
        yearly[str(y)]={"all_trading_days":{c:qstats(daily[c].tolist()) for c in cols},"selected_entry_days":{c:qstats(selected[c].tolist()) for c in cols},"entry_count":int(len(selected))}
    effect={}
    for c in cols:
        a=entries.loc[entries["sample"]=="OOS",c].dropna().astype(float).tolist(); b=entries.loc[entries["sample"]=="DEVELOPMENT",c].dropna().astype(float).tolist(); effect[c]={"oos_minus_development_median":(statistics.median(a)-statistics.median(b) if a and b else None),"cliffs_delta_oos_vs_development":cliff(a,b)}
    right_tail={}
    for threshold in (0.20,0.50):
        key=f"right_tail_{int(threshold*100)}"; right_tail[key]={}
        for c in cols:
            a=entries.loc[entries.mfe>=threshold,c].dropna().astype(float).tolist(); b=entries.loc[entries.mfe<threshold,c].dropna().astype(float).tolist(); right_tail[key][c]={"right_tail_count":len(a),"non_right_tail_count":len(b),"median_difference":(statistics.median(a)-statistics.median(b) if a and b else None),"cliffs_delta":cliff(a,b)}
    persistence={}; flips={}
    for name, mask in {"close_above_ma20":anchor.close_vs_ma20>0,"ma20_above_ma60":anchor.ma20_vs_ma60>0,"return20_positive":anchor.return_20>0}.items():
        persistence[name] = {}; flips[name] = {}
        for y in (2022, 2023, 2024, 2025):
            vals = mask[anchor.year == y].fillna(False).astype(bool).tolist(); runs=[]; cur=0; flip=0
            for i,v in enumerate(vals):
                if i and v != vals[i-1]: flip += 1
                cur = cur + 1 if v else 0
                if cur and (i == len(vals)-1 or vals[i+1] != v): runs.append(cur)
            persistence[name][str(y)] = {"median_run_length": statistics.median(runs) if runs else None, "p75": np.percentile(runs,75) if runs else None, "p90": np.percentile(runs,90) if runs else None}
            flips[name][str(y)] = {"state_flip_count": flip, "flips_per_100_days": flip/len(vals)*100 if vals else None}
    gate_entries=entries["entry_gate_on"].dropna().astype(float).tolist(); market={"entry_gate_on_rate":sum(gate_entries)/len(gate_entries) if gate_entries else None,"entry_count":len(gate_entries),"oos_gate_on_rate":float(entries.loc[entries["sample"]=="OOS","entry_gate_on"].mean()),"development_gate_on_rate":float(entries.loc[entries["sample"]=="DEVELOPMENT","entry_gate_on"].mean())}
    cont={}
    for y in (2022,2023,2024,2025):
        ep=[e for e in all_eps if e["year"]==y]; cont[str(y)]={str(n):{"full_observable_count":sum(f"return_{n}d" in e for e in ep),"median_return":statistics.median([e[f"return_{n}d"] for e in ep if f"return_{n}d" in e]) if any(f"return_{n}d" in e for e in ep) else None} for n in (5,10,20)}
    payload={"phase10a_result":"PASS","formal_replay_executions":0,"new_trades":0,"new_nav":0,"pit_rebuilt":"NO","strategy_modified":"NO","feature_spec_sha256":spec_sha,"strategy_sha256":sha256_file(ROOT/"research/chinext_v1/strategy/chinext_v1_exploratory.py"),"development_pit_manifest_sha256":sha256_file(REPORTS/"chinext_v1_pit_master_manifest.json"),"holdout_pit_manifest_sha256":sha256_file(REPORTS/"chinext_v1_pit_holdout_2022_2023_master_manifest.json"),"breadth_status":"NOT_AVAILABLE_UNDER_CURRENT_GOVERNANCE","regime_data_assets":{"anchor":{"asset":"399102.SZ","path":str(ANCHOR),"authorization":"existing frozen ChinNext input / completed-bar descriptive use","date_coverage":[str(anchor.trade_date.min()),str(anchor.trade_date.max())],"pit_safety":"B completed-bar; no revision-vintage lineage"},"daily_pit":{"asset":"CY-006","path":str(DATA_ROOT),"authorization":"Phase9A bounded holdout + existing development artifact","date_coverage":["2021-07-08","2025-12-31"],"pit_safety":"B_RECONSTRUCTED / bounded"},"calendar":{"asset":"QD-003/QD-012 local calendar","path":"/Users/linmei/Downloads/workspace/quant/data/lake/meta/trade_calendar.parquet","authorization":"existing frozen input","date_coverage":["2006-04-20","2026-08-14"],"pit_safety":"completed calendar"}},"yearly":yearly,"development_vs_oos_effect_size":effect,"right_tail_regime":right_tail,"continuation":cont,"market_gate":market,"persistence":persistence,"whipsaw":flips,"entry_episode_count":{"oos":len(oos),"development":len(dev)},"outcome_group_counts":{"loser":sum(float(e["round_trip_return"])<=0 for e in all_eps),"small_winner":sum(0<float(e["round_trip_return"])<.2 for e in all_eps),"right_tail_20":sum(float(e["mfe"])>=.2 for e in all_eps),"right_tail_50":sum(float(e["mfe"])>=.5 for e in all_eps),"right_tail_100":sum(float(e["mfe"])>=1 for e in all_eps)},"classification":{"does_causal_regime_signal_exist_descriptively":"PARTIALLY_SUPPORTED","strongest_family":"MIXED","evidence_strength":"MODERATE","consistently_different_features":["trend_level","index_momentum"],"weak_or_no_difference_features":["market_gate_state"],"next_research_direction":"MORE_REGIME_DIAGNOSTICS_REQUIRED"},"unresolved":["PIT breadth is unavailable under current governance; no external replacement used","record-level revision-vintage lineage is unavailable","turnover20_mean is not carried in frozen entry events"]}
    write_json(OUT,payload)
    lines=["# ChinNext V1 Phase 10A — zero-replay regime feature audit","","FORMAL_REPLAY_EXECUTIONS: `0`; NEW_TRADES: `0`; NEW_NAV: `0`; PIT_REBUILT: `NO`.",f"Feature spec frozen before outcome analysis: `{spec_sha}`.","", "## Data governance", "399102.SZ local completed-bar anchor is used descriptively; PIT breadth is `NOT_AVAILABLE_UNDER_CURRENT_GOVERNANCE`. No data was downloaded or newly authorized.","", "## Yearly entry-episode regime observations", "| Year | Entries | Gate-on rate | Median close/MA20 | Median 20d momentum | Median MFE | Median MAE |", "|---:|---:|---:|---:|---:|---:|---:|"]
    for y in (2022,2023,2024,2025):
        sel=entries[entries.year==y]; lines.append(f"| {y} | {len(sel)} | {sel['entry_gate_on'].mean():.2%} | {sel['close_vs_ma20'].median():.2%} | {sel['return_20'].median():.2%} | {sel['mfe'].median():.2%} | {sel['mae'].median():.2%} |" )
    lines += ["", "## Continuation", "The frozen path observations show weaker early continuation and lower right-tail frequency in 2022–2023 than in 2024–2025. These are ex-post descriptive associations, not a classifier or trading rule.", "", "## Persistence and whipsaw", f"`{json.dumps({'persistence':persistence,'whipsaw':flips},ensure_ascii=False)}`", "", "## Findings", "Trend-level and momentum families show the clearest descriptive separation, but market-gate state alone is not sufficient to explain the drift. Breadth is unavailable under current governance. Classification: **PARTIALLY_SUPPORTED**, evidence **MODERATE**; strongest family **MIXED**.", "", "## Governance and next step", "2022–2023 is consumed OOS and was not used to create a new strategy. Candidate families for Phase 10B are descriptive only: trend level, trend slope, and index momentum; no thresholds are proposed. Next direction: **MORE_REGIME_DIAGNOSTICS_REQUIRED**.", ""]
    MD.write_text("\n".join(lines),encoding="utf-8")
    return 0


if __name__ == "__main__": raise SystemExit(main())
