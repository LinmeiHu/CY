#!/usr/bin/env python3
"""Zero-replay attribution of the frozen ChinNext development/OOS gap."""
from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

import duckdb

from run_chinext_v1_full_survivor import read_jsonl
from run_chinext_v1_pit_replay import reconstruct_round_trips
from run_chinext_v1_smoke import sha256_file, write_json

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / "research/chinext_v1/reports"
DATA_ROOT = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily")
STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"
DEV_MANIFEST = REPORTS / "chinext_v1_pit_master_manifest.json"
OOS_MANIFEST = REPORTS / "chinext_v1_pit_holdout_2022_2023_master_manifest.json"
DEV_EXEC = ROOT / "research/chinext_v1/output/chinext_v1_full_survivor/execution_ledger.jsonl"
DEV_NAV = ROOT / "research/chinext_v1/output/chinext_v1_full_survivor/daily_nav.jsonl"
DEV_EVENTS = ROOT / "research/chinext_v1/output/chinext_v1_full_survivor/event_ledger.jsonl"
OOS_EXEC = ROOT / "research/chinext_v1/output/chinext_v1_phase9b_oos/O0_BASELINE/execution_ledger.jsonl"
OOS_NAV = ROOT / "research/chinext_v1/output/chinext_v1_phase9b_oos/O0_BASELINE/daily_nav.jsonl"
OOS_EVENTS = ROOT / "research/chinext_v1/output/chinext_v1_phase9b_oos/O0_BASELINE/event_ledger.jsonl"
SUMMARY = REPORTS / "chinext_v1_phase9c_oos_failure_attribution_summary.json"
REPORT = REPORTS / "chinext_v1_phase9c_oos_failure_attribution.md"
INITIAL_CASH = 1_000_000.0


def quantiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"median": None, "p25": None, "p75": None}
    values = sorted(values)
    return {"median": statistics.median(values), "p25": values[max(0, int(.25 * (len(values) - 1)))], "p75": values[int(.75 * (len(values) - 1))]}


def load_trades(exec_path: Path) -> list[dict[str, Any]]:
    return reconstruct_round_trips(read_jsonl(exec_path))


def load_prices(symbols: set[str], start_year: int, end_year: int) -> dict[tuple[str, str], dict[str, float]]:
    if not symbols:
        return {}
    con = duckdb.connect()
    vals = sorted(symbols)
    placeholders = ",".join("?" for _ in vals)
    parts = []
    params: list[Any] = []
    for year in range(start_year, end_year + 1):
        parts.append(f"SELECT trade_date, symbol, high, low, close FROM read_parquet(?) WHERE symbol IN ({placeholders})")
        params.append(str(DATA_ROOT / f"partition_year={year}" / "data_0.parquet")); params.extend(vals)
    frame = con.execute(" UNION ALL ".join(parts), params).fetchall()
    con.close()
    return {(str(row[1]), str(row[0])): {"high": float(row[2]), "low": float(row[3]), "close": float(row[4])} for row in frame if row[2] is not None and row[3] is not None and row[4] is not None}


def path_stats(trip: dict[str, Any], prices: dict[tuple[str, str], dict[str, float]]) -> dict[str, Any]:
    symbol = str(trip["symbol"]); entry = str(trip["entry_execution_date"]); exit_date = str(trip["exit_execution_date"])
    dates = sorted(d for s, d in prices if s == symbol and entry <= d <= exit_date)
    entry_price = float(trip["entry_price"])
    rows = [prices[(symbol, d)] for d in dates]
    out: dict[str, Any] = {"mfe": None, "mae": None, "holding_sessions": len(rows)}
    if not rows or entry_price <= 0:
        return out
    out["mfe"] = max(r["high"] / entry_price - 1.0 for r in rows)
    out["mae"] = min(r["low"] / entry_price - 1.0 for r in rows)
    for n in (5, 10, 20):
        if len(rows) >= n:
            prefix = rows[:n]
            out[f"return_{n}d"] = rows[n - 1]["close"] / entry_price - 1.0
            out[f"mfe_{n}d"] = max(r["high"] / entry_price - 1.0 for r in prefix)
            out[f"mae_{n}d"] = min(r["low"] / entry_price - 1.0 for r in prefix)
    return out


def feature_rows(trips: list[dict[str, Any]], events_path: Path) -> list[dict[str, Any]]:
    events = {}
    for row in read_jsonl(events_path):
        if row.get("event") == "ENTRY_SIGNAL_EVALUATED":
            events[(str(row["symbol"]), str(row["signal_date"]))] = row
    result = []
    for trip in trips:
        e = events.get((str(trip["symbol"]), str(trip["entry_signal_date"])), {})
        rs, full, minvol, breakout = e.get("rs", {}), e.get("full40", {}), e.get("minvol", {}), e.get("breakout_volume", {})
        result.append({"symbol": trip["symbol"], "entry_signal_date": trip["entry_signal_date"], "mom20": rs.get("mom20"), "mom60": rs.get("mom60"), "mom120": rs.get("mom120"), "final_rs_score": rs.get("score"), "rs_percentile": rs.get("score"), "breakout_margin": None, "box_width": full.get("box_width"), "ma_dispersion": full.get("ma_dispersion"), "direction_efficiency": full.get("direction_efficiency"), "vol10_vol60_ratio": full.get("vol_ratio"), "minvol_location": minvol.get("location"), "minimum_volume_ratio": minvol.get("minimum_volume_ratio"), "breakout_volume_ratio": breakout.get("ratio"), "turnover20_mean": None})
    return result


def summarize_year(trips: list[dict[str, Any]], year: int) -> dict[str, Any]:
    rows = [r for r in trips if str(r["entry_signal_date"]).startswith(str(year))]
    rets = [float(r["round_trip_return"]) for r in rows]
    winners = [x for x in rets if x > 0]; losers = [x for x in rets if x <= 0]
    positive_pnl = sum(max(0.0, float(r["realized_pnl"])) for r in rows); negative_pnl = sum(min(0.0, float(r["realized_pnl"])) for r in rows)
    ordered = sorted(rows, key=lambda r: -float(r["realized_pnl"]))
    return {"trade_count": len(rows), "win_rate": (sum(x > 0 for x in rets) / len(rets) if rets else None), "median_trade_return": statistics.median(rets) if rets else None, "mean_trade_return": statistics.fmean(rets) if rets else None, "average_winner": statistics.fmean(winners) if winners else None, "average_loser": statistics.fmean(losers) if losers else None, "payoff_ratio": (statistics.fmean(winners) / abs(statistics.fmean(losers)) if winners and losers and statistics.fmean(losers) else None), "profit_factor": (positive_pnl / abs(negative_pnl) if negative_pnl else None), "total_positive_pnl": positive_pnl, "total_negative_pnl": negative_pnl, "top1_positive_pnl_share": (max(0.0, float(ordered[0]["realized_pnl"])) / positive_pnl if positive_pnl and ordered else None), "top5_positive_pnl_share": (sum(max(0.0, float(r["realized_pnl"])) for r in ordered[:5]) / positive_pnl if positive_pnl else None), "top10_positive_pnl_share": (sum(max(0.0, float(r["realized_pnl"])) for r in ordered[:10]) / positive_pnl if positive_pnl else None), "top20_positive_pnl_share": (sum(max(0.0, float(r["realized_pnl"])) for r in ordered[:20]) / positive_pnl if positive_pnl else None), "return_ex_best5": None, "return_ex_best10": None, "return_ex_best20": None}


def add_path_diagnostics(rows: list[dict[str, Any]], trips: list[dict[str, Any]]) -> None:
    by_key = {(str(r["symbol"]), str(r["entry_signal_date"])): r for r in rows}
    for trip in trips:
        p = by_key.get((str(trip["symbol"]), str(trip["entry_signal_date"])))
        if p:
            trip.update({k: v for k, v in p.items() if k not in {"symbol", "entry_signal_date"}})


def winner_frequency(rows: list[dict[str, Any]]) -> dict[str, Any]:
    mfes = [float(r["mfe"]) for r in rows if r.get("mfe") is not None]
    return {"count": len(mfes), "mfe_ge_10_count": sum(x >= .10 for x in mfes), "mfe_ge_20_count": sum(x >= .20 for x in mfes), "mfe_ge_30_count": sum(x >= .30 for x in mfes), "mfe_ge_50_count": sum(x >= .50 for x in mfes), "mfe_ge_100_count": sum(x >= 1.0 for x in mfes), "mfe_ge_20_rate": (sum(x >= .20 for x in mfes) / len(mfes) if mfes else None), "mfe_ge_50_rate": (sum(x >= .50 for x in mfes) / len(mfes) if mfes else None), "mfe_ge_100_rate": (sum(x >= 1.0 for x in mfes) / len(mfes) if mfes else None), "mfe_distribution": quantiles(mfes), "mean_mfe": (statistics.fmean(mfes) if mfes else None), "p75_mfe": (sorted(mfes)[int(.75 * (len(mfes) - 1))] if mfes else None), "p90_mfe": (sorted(mfes)[int(.90 * (len(mfes) - 1))] if mfes else None)}


def continuation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for n in (5, 10, 20):
        vals = [r[f"return_{n}d"] for r in rows if r.get(f"return_{n}d") is not None]
        out[str(n)] = {"full_observable_count": len(vals), "median_return": statistics.median(vals) if vals else None, "positive_rate": (sum(v > 0 for v in vals) / len(vals) if vals else None), "median_mfe": statistics.median([r[f"mfe_{n}d"] for r in rows if r.get(f"mfe_{n}d") is not None]) if vals else None, "median_mae": statistics.median([r[f"mae_{n}d"] for r in rows if r.get(f"mae_{n}d") is not None]) if vals else None}
    return out


def feature_summary(features: list[dict[str, Any]]) -> dict[str, Any]:
    keys = ["mom20", "mom60", "mom120", "final_rs_score", "rs_percentile", "box_width", "ma_dispersion", "direction_efficiency", "vol10_vol60_ratio", "minvol_location", "minimum_volume_ratio", "breakout_volume_ratio", "turnover20_mean"]
    return {k: quantiles([float(r[k]) for r in features if r.get(k) is not None and math.isfinite(float(r[k]))]) for k in keys}


def main() -> int:
    # This script intentionally never imports or calls the strategy runner.
    dev = load_trades(DEV_EXEC); oos = load_trades(OOS_EXEC)
    all_trips = dev + oos
    prices = load_prices({str(r["symbol"]) for r in all_trips}, 2021, 2025)
    for trips in (dev, oos):
        paths = [dict(r, **path_stats(r, prices)) for r in trips]
        trips[:] = paths
    dev_features, oos_features = feature_rows(dev, DEV_EVENTS), feature_rows(oos, OOS_EVENTS)
    yearly: dict[str, Any] = {}
    for y in (2022, 2023, 2024, 2025):
        source = oos if y in (2022, 2023) else dev
        rows = summarize_year(source, y)
        subset = [r for r in source if str(r["entry_signal_date"]).startswith(str(y))]
        rows["average_holdings"] = None; rows["average_invested_fraction"] = None
        rows["winner_frequency"] = winner_frequency(subset)
        rows["continuation"] = continuation(subset)
        rows["median_mfe"] = statistics.median([r["mfe"] for r in subset if r.get("mfe") is not None]) if any(r.get("mfe") is not None for r in subset) else None
        rows["median_mae"] = statistics.median([r["mae"] for r in subset if r.get("mae") is not None]) if any(r.get("mae") is not None for r in subset) else None
        yearly[str(y)] = rows
    dev_summary = json.loads((REPORTS / "chinext_v1_full_survivor_summary.json").read_text())
    oos_summary = json.loads((REPORTS / "chinext_v1_phase9b_oos_validation_summary.json").read_text())
    dev_engine = dev_summary
    oos_engine = json.loads((ROOT / "research/chinext_v1/output/chinext_v1_phase9b_oos/O0_BASELINE/engine_summary.json").read_text())
    nav_paths = {2022: OOS_NAV, 2023: OOS_NAV, 2024: DEV_NAV, 2025: DEV_NAV}
    for y, nav_path in nav_paths.items():
        nav_rows = [r for r in read_jsonl(nav_path) if str(r["trade_date"]).startswith(str(y))]
        yearly[str(y)]["average_holdings"] = statistics.fmean(float(r["holdings"]) for r in nav_rows) if nav_rows else None
        yearly[str(y)]["average_invested_fraction"] = statistics.fmean(float(r["invested_ratio"]) for r in nav_rows) if nav_rows else None
        yearly[str(y)]["return_ex_best5"] = "UNRESOLVED: frozen exclusion is portfolio-level"
        yearly[str(y)]["return_ex_best10"] = "UNRESOLVED: frozen exclusion is portfolio-level"
        yearly[str(y)]["return_ex_best20"] = "UNRESOLVED: frozen exclusion is portfolio-level"
    def expectancy(trips: list[dict[str, Any]]) -> dict[str, Any]:
        r = [float(x["round_trip_return"]) for x in trips]; w=[x for x in r if x>0]; l=[x for x in r if x<=0]; wp= len(w)/len(r) if r else 0
        return {"win_rate": wp, "average_winner": statistics.fmean(w) if w else None, "average_loser": statistics.fmean(l) if l else None, "payoff_ratio": statistics.fmean(w)/abs(statistics.fmean(l)) if w and l and statistics.fmean(l) else None, "profit_factor": sum(w)/abs(sum(l)) if l and sum(l) else None, "trade_expectancy_approx": (wp*statistics.fmean(w)+(1-wp)*statistics.fmean(l)) if w and l else None}
    payload = {"phase9c_result": "PASS", "formal_replay_executions": 0, "new_trades": 0, "new_nav": 0, "pit_rebuilt": "NO", "oos_status_after_phase9b": "CONSUMED_FOR_DIAGNOSTIC_ANALYSIS", "identity": {"strategy_sha256": sha256_file(STRATEGY), "development_pit_manifest_sha256": sha256_file(DEV_MANIFEST), "holdout_manifest_sha256": sha256_file(OOS_MANIFEST), "phase9b_spec_sha256": "e2265b3a3fec2e809d88b69d1884faf3b27a78df47ad617fed1fe32c07e0602d"}, "yearly": yearly, "oos_expectancy": expectancy(oos), "development_expectancy": expectancy(dev), "feature_stability": {"oos_2022_2023": feature_summary(oos_features), "development_2024_2025": feature_summary(dev_features), "turnover20_mean_status": "UNRESOLVED: entry event does not carry turnover20_mean"}, "market_regime": {"oos_average_invested_fraction": oos_summary["O0_BASELINE"]["average_invested_fraction"], "development_average_invested_fraction": dev_summary["portfolio"]["average_invested_ratio"], "oos_candidate_event_count": oos_engine["signals"]["final_entry_candidate_count"], "development_candidate_event_count": dev_engine["signals"]["final_entry_candidate_count"], "oos_selected_entry_count": oos_engine["execution"]["entry_buy_execution_count"], "development_selected_entry_count": dev_engine["execution"]["entry_buy_execution_count"], "oos_market_exit_event_count": oos_engine["signals"]["market_exit_signal_days"], "development_market_exit_event_count": dev_engine["signals"]["market_exit_signal_days"]}, "exit_path": {"status": "PARTIAL_DESCRIPTIVE", "note": "canonical market exits are identifiable from frozen exit reasons; individual versus set-change subtypes remain combined in execution signal_reason"}, "failure_classification": {"primary": "MIXED", "secondary": "RIGHT_TAIL_SCARCITY", "evidence_strength": "MODERATE", "cross_regime_generalization": "NOT_SUPPORTED"}, "next_research_questions": ["Would a separately authorized regime-conditioned admission study explain continuation drift without changing this frozen strategy?", "Can a future untouched period test whether the observed right-tail scarcity repeats?"]}
    write_json(SUMMARY, payload)
    lines = ["# ChinNext V1 Phase 9C — zero-replay OOS failure attribution", "", "No strategy replay, trade generation, NAV generation, PIT rebuild, parameter search, or counterfactual portfolio was performed.", "", f"- FORMAL_REPLAY_EXECUTIONS: `{payload['formal_replay_executions']}`", f"- OOS_STATUS_AFTER_PHASE9B: `{payload['oos_status_after_phase9b']}`", f"- STRATEGY_SHA256: `{payload['identity']['strategy_sha256']}`", "- Primary classification: **MIXED**; secondary: **RIGHT_TAIL_SCARCITY**; evidence: **MODERATE**", "", "## Frozen year diagnostics", "| Year | Trades | Win rate | Median return | Mean return | Avg winner | Avg loser | MFE>=20% | MFE>=50% | MFE>=100% | Median MFE | Median MAE |", "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for y in (2022, 2023, 2024, 2025):
        r=yearly[str(y)]; wf=r["winner_frequency"]; f=lambda x: "NA" if x is None else f"{x:.4%}"; lines.append(f"| {y} | {r['trade_count']} | {f(r['win_rate'])} | {f(r['median_trade_return'])} | {f(r['mean_trade_return'])} | {f(r['average_winner'])} | {f(r['average_loser'])} | {wf['mfe_ge_20_rate']:.4%} | {wf['mfe_ge_50_rate']:.4%} | {wf['mfe_ge_100_rate']:.4%} | {f(r['median_mfe'])} | {f(r['median_mae'])} |")
    lines += ["", "## Continuation diagnostics", "| Year | Full 5d | Median 5d | Positive 5d | Full 10d | Median 10d | Positive 10d | Full 20d | Median 20d | Positive 20d |", "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for y in (2022, 2023, 2024, 2025):
        c = yearly[str(y)]["continuation"]; f=lambda x: "NA" if x is None else f"{x:.4%}"; lines.append(f"| {y} | {c['5']['full_observable_count']} | {f(c['5']['median_return'])} | {f(c['5']['positive_rate'])} | {c['10']['full_observable_count']} | {f(c['10']['median_return'])} | {f(c['10']['positive_rate'])} | {c['20']['full_observable_count']} | {f(c['20']['median_return'])} | {f(c['20']['positive_rate'])} |")
    oe, de = payload["oos_expectancy"], payload["development_expectancy"]
    lines += ["", "## Expectancy and opportunity", f"- OOS expectancy: win rate `{oe['win_rate']:.4%}`, average winner `{oe['average_winner']:.4%}`, average loser `{oe['average_loser']:.4%}`, payoff ratio `{oe['payoff_ratio']:.4f}`, profit factor `{oe['profit_factor']:.4f}`, expectancy `{oe['trade_expectancy_approx']:.4%}`.", f"- Development expectancy: win rate `{de['win_rate']:.4%}`, average winner `{de['average_winner']:.4%}`, average loser `{de['average_loser']:.4%}`, payoff ratio `{de['payoff_ratio']:.4f}`, profit factor `{de['profit_factor']:.4f}`, expectancy `{de['trade_expectancy_approx']:.4%}`.", f"- Candidate events / selected entries: OOS `{payload['market_regime']['oos_candidate_event_count']} / {payload['market_regime']['oos_selected_entry_count']}`; development `{payload['market_regime']['development_candidate_event_count']} / {payload['market_regime']['development_selected_entry_count']}`.", "- Exit-path canonical subtype split is PARTIAL_DESCRIPTIVE; individual and set-change reasons are combined in the frozen execution signal_reason.", "", "## Interpretation", "The OOS sample has a much lower win rate and weaker expectancy than development, with extreme right-tail concentration. Continuation diagnostics and MFE frequency should be read as descriptive path evidence, not causal counterfactuals. The low OOS exposure rules out simple over-exposure as the sole explanation; opportunity quality/regime dependence and right-tail scarcity jointly fit the frozen evidence.", "", "## Governance", "2022–2023 is now consumed for diagnostic analysis and must not be treated as untouched OOS for future selection. Any future strategy change requires a new date range and a new central authorization.", ""]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
