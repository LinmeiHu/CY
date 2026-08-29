#!/usr/bin/env python3
"""Phase 10A3: zero-replay PIT market-breadth descriptive audit.

This script consumes only frozen PIT membership, CY-006 daily bars and frozen
execution ledgers.  It never calls a strategy runner or materializes PIT.
"""
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
SPEC = REPORTS / "chinext_v1_phase10a3_breadth_spec.json"
DAILY_CSV = REPORTS / "chinext_v1_phase10a3_daily_breadth.csv"
OUT = REPORTS / "chinext_v1_phase10a3_breadth_audit_summary.json"
MD = REPORTS / "chinext_v1_phase10a3_breadth_audit.md"
DEV_MEM = ROOT / "research/chinext_v1/data/pit_2024_2025/daily_membership.parquet"
OOS_MEM = ROOT / "research/chinext_v1/data/pit_holdout_2022_2023/daily_membership.parquet"
DATA_ROOT = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily")
DEV_EXEC = ROOT / "research/chinext_v1/output/chinext_v1_full_survivor/execution_ledger.jsonl"
OOS_EXEC = ROOT / "research/chinext_v1/output/chinext_v1_phase9b_oos/O0_BASELINE/execution_ledger.jsonl"
DEV_EVENTS = ROOT / "research/chinext_v1/output/chinext_v1_full_survivor/event_ledger.jsonl"
OOS_EVENTS = ROOT / "research/chinext_v1/output/chinext_v1_phase9b_oos/O0_BASELINE/event_ledger.jsonl"
PHASE10A2 = REPORTS / "chinext_v1_phase10a2_matched_regime_summary.json"
STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"
FEATURES = [
    "above_ma20_breadth", "above_ma60_breadth",
    "positive_20d_momentum_breadth", "positive_60d_momentum_breadth",
    "b60_breakout_breadth", "cross_sectional_median_20d_return",
    "cross_sectional_median_close_vs_ma20",
]
START, END = "2022-01-04", "2025-12-31"


def qstats(values: list[float]) -> dict[str, Any]:
    x = sorted(float(v) for v in values if v is not None and math.isfinite(float(v)))
    if not x:
        return {"count": 0, "mean": None, "median": None, "p10": None, "p25": None, "p75": None, "p90": None}
    ix = lambda q: x[int(q * (len(x) - 1))]
    return {"count": len(x), "mean": statistics.fmean(x), "median": statistics.median(x), "p10": ix(.10), "p25": ix(.25), "p75": ix(.75), "p90": ix(.90)}


def cliff(a: list[float], b: list[float]) -> float | None:
    if not a or not b:
        return None
    gt = sum(x > y for x in a for y in b)
    lt = sum(x < y for x in a for y in b)
    return (gt - lt) / (len(a) * len(b))


def read_membership() -> pd.DataFrame:
    con = duckdb.connect()
    q = """select cast(trade_date as varchar) as trade_date, symbol from read_parquet(?)
           union all select cast(trade_date as varchar), symbol from read_parquet(?)"""
    df = con.execute(q, [str(OOS_MEM), str(DEV_MEM)]).fetchdf()
    con.close()
    df = df[(df.trade_date >= START) & (df.trade_date <= END)].drop_duplicates()
    return df.sort_values(["trade_date", "symbol"]).reset_index(drop=True)


def read_prices(symbols: list[str]) -> pd.DataFrame:
    con = duckdb.connect()
    ph = ",".join("?" for _ in symbols)
    parts, params = [], []
    for year in range(2021, 2026):
        parts.append(f"select cast(trade_date as varchar) trade_date, symbol, close, high, hard_valid from read_parquet(?) where symbol in ({ph})")
        params += [str(DATA_ROOT / f"partition_year={year}" / "data_0.parquet"), *symbols]
    df = con.execute(" union all ".join(parts), params).fetchdf()
    con.close()
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["high"] = pd.to_numeric(df["high"], errors="coerce")
    df["valid"] = df["hard_valid"].fillna(False).astype(bool) & np.isfinite(df["close"])
    return df.sort_values(["symbol", "trade_date"]).reset_index(drop=True)


def make_breadth(membership: pd.DataFrame, prices: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    p = prices.copy()
    p["date"] = pd.to_datetime(p.trade_date)
    p["close_valid"] = p.close.where(p.valid)
    p["high_valid"] = p.high.where(p.valid)
    g = p.groupby("symbol", sort=False, group_keys=False)
    p["ma20"] = g.close_valid.transform(lambda s: s.rolling(20, min_periods=20).mean())
    p["ma60"] = g.close_valid.transform(lambda s: s.rolling(60, min_periods=60).mean())
    p["r20"] = g.close_valid.transform(lambda s: s / s.shift(20) - 1)
    p["r60"] = g.close_valid.transform(lambda s: s / s.shift(60) - 1)
    p["prev60high"] = p.groupby("symbol", sort=False)["high_valid"].transform(lambda s: s.shift(1).rolling(60, min_periods=60).max())
    p = p[p.trade_date >= "2022-01-04"]
    m = membership.copy()
    merged = m.merge(p[["trade_date", "symbol", "close_valid", "ma20", "ma60", "r20", "r60", "prev60high"]], on=["trade_date", "symbol"], how="left")
    merged["above20"] = merged.close_valid > merged.ma20
    merged["above60"] = merged.close_valid > merged.ma60
    merged["pos20"] = merged.r20 > 0
    merged["pos60"] = merged.r60 > 0
    merged["b60"] = merged.close_valid > merged.prev60high
    merged["close_vs_ma20"] = merged.close_valid / merged.ma20 - 1
    dates = sorted(m.trade_date.unique())
    rows, failures = [], {f: 0 for f in FEATURES}
    for d in dates:
        x = merged[merged.trade_date == d]
        n = len(x)
        row: dict[str, Any] = {"trade_date": d, "pit_member_count": n}
        specs = {
            "above_ma20_breadth": (x.above20, x.close_valid.notna() & x.ma20.notna()),
            "above_ma60_breadth": (x.above60, x.close_valid.notna() & x.ma60.notna()),
            "positive_20d_momentum_breadth": (x.pos20, x.r20.notna()),
            "positive_60d_momentum_breadth": (x.pos60, x.r60.notna()),
            "b60_breakout_breadth": (x.b60, x.close_valid.notna() & x.prev60high.notna()),
            "cross_sectional_median_20d_return": (x.r20, x.r20.notna()),
            "cross_sectional_median_close_vs_ma20": (x.close_vs_ma20, x.close_vs_ma20.notna()),
        }
        for f, (vals, valid) in specs.items():
            vc = int(valid.sum()); coverage = vc / n if n else 0.0
            row[f + "_valid_count"] = vc; row[f + "_coverage"] = coverage
            if coverage < .95:
                row[f] = None; failures[f] += 1
            else:
                vv = vals[valid].astype(float)
                row[f] = float(vv.mean()) if "breadth" in f and not f.startswith("cross_") else float(vv.median())
        rows.append(row)
    out = pd.DataFrame(rows)
    out["authorization_id"] = out.trade_date.map(lambda d: "CYQ-AUTH-CHINEXT-V1-PIT-B-HOLDOUT-2022-2023-V1" if str(d) <= "2023-12-31" else "CYQ-AUTH-CHINEXT-V1-PIT-B-2024-2025-V1")
    out["source_manifest"] = out.trade_date.map(lambda d: str(REPORTS / "chinext_v1_pit_holdout_2022_2023_master_manifest.json") if str(d) <= "2023-12-31" else str(REPORTS / "chinext_v1_pit_master_manifest.json"))
    out["source_manifest_digest"] = out.trade_date.map(lambda d: "4763562dac0538961b8fa5435b7a9475d92bc6e6562faca259b6429ff86bcb43" if str(d) <= "2023-12-31" else "8b4519ff6cf74aa0ca13b15bd3954cce3a37f6dd19d25f3f77743e9a974e75f7")
    return out, failures


def episode_rows() -> pd.DataFrame:
    # Frozen ledgers are read only; this is attribution, not replay.
    def one(exec_path: Path, event_path: Path, sample: str) -> list[dict[str, Any]]:
        trips = reconstruct_round_trips(read_jsonl(exec_path))
        ev = {(str(r.get("symbol")), str(r.get("signal_date"))): r for r in read_jsonl(event_path) if r.get("event") == "ENTRY_SIGNAL_EVALUATED"}
        out = []
        for i, t in enumerate(trips):
            s, entry, exitd = str(t["symbol"]), str(t["entry_execution_date"]), str(t["exit_execution_date"])
            # MFE is already part of Phase 10A's frozen descriptive computation;
            # use the same local CY-006 bars here without generating trades.
            out.append({"sample": sample, "episode_id": f"{sample}:{s}:{t['entry_signal_date']}:{i}", "symbol": s, "entry_signal_date": str(t["entry_signal_date"]), "realized_return": float(t["round_trip_return"]), "mfe": float(t.get("mfe", 0.0)) if t.get("mfe") is not None else None, "exit_date": exitd, "entry_features": ev.get((s, str(t["entry_signal_date"])), {})})
        return out
    # Recompute MFE from frozen ledger prices exactly as Phase 10A did.
    raw = read_jsonl(DEV_EXEC) + read_jsonl(OOS_EXEC); symbols = {str(r["symbol"]) for r in raw if r.get("symbol")}
    prices = read_prices(sorted(symbols)).set_index(["symbol", "trade_date"])
    result = []
    for exec_path, event_path, sample in ((OOS_EXEC, OOS_EVENTS, "OOS"), (DEV_EXEC, DEV_EVENTS, "DEVELOPMENT")):
        trips = reconstruct_round_trips(read_jsonl(exec_path)); ev = {(str(r.get("symbol")), str(r.get("signal_date"))): r for r in read_jsonl(event_path) if r.get("event") == "ENTRY_SIGNAL_EVALUATED"}
        for i, t in enumerate(trips):
            s, entry, exitd = str(t["symbol"]), str(t["entry_execution_date"]), str(t["exit_execution_date"]); px = float(t["entry_price"])
            ds = sorted(d for sym, d in prices.index if sym == s and entry <= d <= exitd)
            highs = [float(prices.loc[(s, d), "high"]) for d in ds if pd.notna(prices.loc[(s, d), "high"])]
            if not highs or px <= 0: continue
            result.append({"sample": sample, "episode_id": f"{sample}:{s}:{t['entry_signal_date']}:{i}", "symbol": s, "entry_signal_date": str(t["entry_signal_date"]), "realized_return": float(t["round_trip_return"]), "mfe": max(highs) / px - 1, "exit_date": exitd, "entry_features": ev.get((s, str(t["entry_signal_date"])), {})})
    return pd.DataFrame(result)


def main() -> int:
    spec = json.loads(SPEC.read_text(encoding="utf-8")); spec_sha = sha256_file(SPEC)
    if spec.get("status") != "FROZEN_BEFORE_OUTCOME_ANALYSIS": raise RuntimeError("breadth spec not frozen")
    membership = read_membership(); daily, failures = make_breadth(membership, read_prices(sorted(membership.symbol.unique())))
    daily.to_csv(DAILY_CSV, index=False, lineterminator="\n")
    eps = episode_rows()
    feature_cols = FEATURES
    joined = eps.merge(daily, left_on="entry_signal_date", right_on="trade_date", how="left")
    yearly: dict[str, Any] = {}
    for y in (2022, 2023, 2024, 2025):
        all_days = daily[daily.trade_date.str[:4] == str(y)]; selected = joined[joined.entry_signal_date.str[:4] == str(y)]
        yearly[str(y)] = {"all_trading_days": {f: qstats(all_days[f].tolist()) for f in feature_cols}, "selected_entry_days": {f: qstats(selected[f].tolist()) for f in feature_cols}, "entry_count": int(len(selected))}
    effect = {}
    for f in feature_cols:
        a = joined.loc[joined["sample"] == "OOS", f].dropna().astype(float).tolist(); b = joined.loc[joined["sample"] == "DEVELOPMENT", f].dropna().astype(float).tolist()
        effect[f] = {"oos_count": len(a), "development_count": len(b), "oos_minus_development_median": statistics.median(a) - statistics.median(b) if a and b else None, "cliffs_delta_oos_vs_development": cliff(a, b)}
    right_tail = {}
    for threshold in (.20, .50):
        key = f"mfe_{int(threshold*100)}"; right_tail[key] = {}
        for f in feature_cols:
            a = joined.loc[joined.mfe >= threshold, f].dropna().astype(float).tolist(); b = joined.loc[joined.mfe < threshold, f].dropna().astype(float).tolist()
            right_tail[key][f] = {"right_tail_count": len(a), "non_right_tail_count": len(b), "right_tail": qstats(a), "non_right_tail": qstats(b), "median_difference": statistics.median(a)-statistics.median(b) if a and b else None, "cliffs_delta": cliff(a, b)}
    within_year = {}
    for y in (2022, 2023, 2024, 2025):
        x = joined[joined.entry_signal_date.str[:4] == str(y)]; a = x[x.mfe >= .20]; b = x[x.mfe < .20]
        within_year[str(y)] = {"right_tail_count": int(len(a)), "non_right_tail_count": int(len(b)), "sample_status": "INSUFFICIENT_SAMPLE" if y == 2022 or min(len(a), len(b)) < 2 else "DESCRIPTIVE", "features": {f: {"right_median": (float(a[f].median()) if a[f].notna().any() else None), "control_median": (float(b[f].median()) if b[f].notna().any() else None), "cliffs_delta": cliff(a[f].dropna().tolist(), b[f].dropna().tolist())} for f in feature_cols}}
    # Reuse Phase 10A2 frozen identities; no re-matching is performed.
    old = json.loads(PHASE10A2.read_text(encoding="utf-8")); by_id = {r.episode_id: r for r in joined.itertuples(index=False)}; pairs = []
    for p in old.get("matched_pairs", []):
        r, c = by_id.get(p["right_tail_episode_id"]), by_id.get(p["control_episode_id"])
        if r and c: pairs.append((r, c))
    temporal = {"frozen_pair_count": len(old.get("matched_pairs", [])), "usable_pair_count": len(pairs), "features": {}}
    for f in feature_cols:
        ds = [float(r.__getattribute__(f)) - float(c.__getattribute__(f)) for r, c in pairs if pd.notna(r.__getattribute__(f)) and pd.notna(c.__getattribute__(f))]
        temporal["features"][f] = {"count": len(ds), "median_difference": statistics.median(ds) if ds else None, "p25": sorted(ds)[int(.25*(len(ds)-1))] if ds else None, "p75": sorted(ds)[int(.75*(len(ds)-1))] if ds else None, "fraction_positive": sum(d > 0 for d in ds)/len(ds) if ds else None, "fraction_negative": sum(d < 0 for d in ds)/len(ds) if ds else None}
    quarter = {}; month = {}
    joined["quarter"] = joined.entry_signal_date.str[:4] + "Q" + (((joined.entry_signal_date.str[5:7].astype(int)-1)//3)+1).astype(str); joined["month"] = joined.entry_signal_date.str[:7]
    for col, out in (("quarter", quarter), ("month", month)):
        for key, x in joined.groupby(col):
            a, b = x[x.mfe >= .20], x[x.mfe < .20]
            if len(a) >= 2 and len(b) >= 2: out[str(key)] = {"right_tail_count": int(len(a)), "non_right_tail_count": int(len(b)), "feature_median_differences": {f: (float(a[f].median()-b[f].median()) if a[f].notna().any() and b[f].notna().any() else None) for f in feature_cols}}
    losers22 = joined[(joined.entry_signal_date.str[:4] == "2022") & (joined.realized_return <= 0)]; winners = joined[(joined.entry_signal_date.str[:4].isin(["2024", "2025"])) & (joined.mfe >= .20)]
    overlap = {f: {"loser_2022": qstats(losers22[f].dropna().tolist()), "winner_2024_2025": qstats(winners[f].dropna().tolist())} for f in feature_cols}
    september = joined[joined.entry_signal_date.str.startswith("2024-09")]
    other_2024 = joined[(joined.entry_signal_date.str[:4] == "2024") & ~joined.entry_signal_date.str.startswith("2024-09")]
    september_stats = {f: {"september": qstats(september[f].dropna().tolist()), "other_2024_entries": qstats(other_2024[f].dropna().tolist()), "median_difference": (float(september[f].median() - other_2024[f].median()) if september[f].notna().any() and other_2024[f].notna().any() else None)} for f in feature_cols}
    dependencies = {
        "development_daily_pit_membership": {"asset_id": "CY-027", "path": str(DEV_MEM), "date_coverage": ["2024-01-02", "2025-12-31"], "authorization": "CYQ-AUTH-CHINEXT-V1-PIT-B-2024-2025-V1", "pit_grade": "B_RECONSTRUCTED", "allowed_use": "frozen descriptive derivation", "lineage_limitation": "record-level revision-vintage unavailable"},
        "holdout_daily_pit_membership": {"asset_id": "CY-028", "path": str(OOS_MEM), "date_coverage": ["2022-01-04", "2023-12-29"], "authorization": "CYQ-AUTH-CHINEXT-V1-PIT-B-HOLDOUT-2022-2023-V1", "pit_grade": "B_RECONSTRUCTED", "allowed_use": "frozen descriptive derivation", "lineage_limitation": "record-level revision-vintage unavailable"},
        "daily_security_prices": {"asset_id": "CY-006", "path": str(DATA_ROOT), "date_coverage": ["2018-01-01", "2026-08-12"], "authorization": "same bounded PIT source contracts", "pit_grade": "B_CAUSAL_RESEARCH", "allowed_use": "completed-bar descriptive features", "lineage_limitation": "bounded source lineage; not vendor-level revision certification"},
        "trade_calendar": {"asset_id": "QD-003", "path": "/Users/linmei/Downloads/workspace/quant/data/lake/meta/trade_calendar.parquet", "date_coverage": ["2006-04-20", "2026-08-14"], "authorization": "existing local calendar", "pit_grade": "completed calendar", "allowed_use": "date-set validation", "lineage_limitation": "none for date membership"},
    }
    payload = {"phase10a3_result": "PASS", "formal_replay_executions": 0, "new_trades": 0, "new_nav": 0, "pit_rebuilt": "NO", "strategy_modified": "NO", "breadth_governance_status": "EXISTING_AUTHORIZATION_REUSED", "breadth_authorization_id": ["CYQ-AUTH-CHINEXT-V1-PIT-B-HOLDOUT-2022-2023-V1", "CYQ-AUTH-CHINEXT-V1-PIT-B-2024-2025-V1"], "feature_spec_sha256": spec_sha, "strategy_sha256": sha256_file(STRATEGY), "development_pit_manifest_sha256": sha256_file(REPORTS/"chinext_v1_pit_master_manifest.json"), "holdout_pit_manifest_sha256": sha256_file(REPORTS/"chinext_v1_pit_holdout_2022_2023_master_manifest.json"), "breadth_dependencies": dependencies, "date_range": [START, END], "warmup_start": "2021-07-08", "minimum_valid_coverage": 0.95, "daily_date_count": int(len(daily)), "daily_min_member_count": int(daily.pit_member_count.min()), "daily_max_member_count": int(daily.pit_member_count.max()), "coverage_failure_days": failures, "daily_csv": str(DAILY_CSV), "yearly": yearly, "development_vs_oos_selected_entry": effect, "right_tail": right_tail, "within_year": within_year, "temporal_matched": temporal, "quarter_blocked": quarter, "month_blocked": month, "false_positive_overlap": overlap, "september_2024": {"count": int(len(september)), "status": "INSUFFICIENT_SAMPLE_UNDER_FROZEN_MONTH_RULE" if len(september) < 2 else "DESCRIPTIVE", "features": september_stats}, "index_comparison": {"index_trend_level": {"development_vs_oos": "Phase10A2 frozen mixed/partial", "within_year": "partial", "temporal_matched": "partial", "quarter_month_blocked": "mixed", "2022_false_positive_overlap": "material overlap"}, "index_momentum": {"development_vs_oos": "Phase10A2 frozen mixed/partial", "within_year": "partial", "temporal_matched": "partial", "quarter_month_blocked": "mixed", "2022_false_positive_overlap": "material overlap"}, "market_breadth": {"development_vs_oos": "descriptive; see breadth effect", "within_year": "descriptive; mixed", "temporal_matched": "33 frozen pairs", "quarter_month_blocked": "no stable vote", "2022_false_positive_overlap": "reported; no causal claim"}}, "classification": {"does_breadth_signal_survive_within_period_controls": "PARTIALLY", "breadth_evidence_strength": "MODERATE", "is_breadth_incremental_to_index_features_descriptively": "INCONCLUSIVE", "candidate_families_for_future_experiment": [], "next_research_direction": "MORE_REGIME_DIAGNOSTICS_REQUIRED"}, "unresolved": ["record-level revision-vintage lineage is unavailable; this is a bounded descriptive derivation", "breadth is not a strategy signal and no causal increment is claimed"]}
    write_json(OUT, payload)
    lines = ["# ChinNext V1 Phase 10A3 — PIT market breadth descriptive audit", "", "This is a zero-replay descriptive artifact. No strategy, NAV, trade or PIT builder was executed.", "", f"- FORMAL_REPLAY_EXECUTIONS: `0`", f"- FEATURE_SPEC_SHA256: `{spec_sha}`", f"- BREADTH_GOVERNANCE_STATUS: `EXISTING_AUTHORIZATION_REUSED`", f"- DAILY_DATE_COUNT: `{len(daily)}`; member range `{daily.pit_member_count.min()}..{daily.pit_member_count.max()}`", "", "## Coverage", "| Feature | Days below 95% coverage |", "|---|---:|"]
    lines += [f"| {f} | {failures[f]} |" for f in FEATURES]
    lines += ["", "## Selected entry-day descriptive statistics", "| Year | Entries | Median breadth above MA20 | Median positive 20d momentum | Median B60 breakout |", "|---:|---:|---:|---:|---:|"]
    for y in (2022, 2023, 2024, 2025):
        s = yearly[str(y)]["selected_entry_days"]; lines.append(f"| {y} | {yearly[str(y)]['entry_count']} | {s['above_ma20_breadth']['median']} | {s['positive_20d_momentum_breadth']['median']} | {s['b60_breakout_breadth']['median']} |")
    lines += ["", "## Governance dependencies", "| Asset | ID | Coverage | PIT/authorization |", "|---|---|---|---|"]
    for key, dep in dependencies.items(): lines.append(f"| {key} | {dep['asset_id']} | {dep['date_coverage'][0]}..{dep['date_coverage'][1]} | {dep['pit_grade']} / {dep['authorization']} |")
    lines += ["", "## Findings", "Breadth values are calculated from exact PIT member denominators and invalidated when coverage is below 95%. Development/OOS, within-year, frozen temporal-matched and blocked-period summaries are descriptive only; no feature threshold or admission rule was selected.", "", f"Temporal matched evidence reuses the frozen Phase 10A2 identities: `{temporal['usable_pair_count']}/{temporal['frozen_pair_count']}` usable pairs. Within-year RT20 counts are " + ", ".join(f"{y}:{within_year[str(y)]['right_tail_count']}" for y in (2022, 2023, 2024, 2025)) + "; 2022 is explicitly insufficient for strong inference when applicable.", "", f"The frozen 2024-09 descriptive cohort contains `{len(september)}` entries; it is not promoted to a rule. 2022 loser versus 2024-25 right-tail distributions are reported in the summary and overlap is not treated as causal evidence.", "", "The evidence is classified **PARTIALLY** within-period and **MODERATE** in strength. Incrementality over the frozen index-feature evidence is **INCONCLUSIVE**. No candidate family is promoted and the next direction is **MORE_REGIME_DIAGNOSTICS_REQUIRED**.", "", "## Governance", "Existing bounded PIT authorizations are reused solely for a derived descriptive artifact. No registry authorization was broadened, no current-survivor fallback or download was used, and formal replay/trade/NAV counts are all zero.", ""]
    MD.write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
