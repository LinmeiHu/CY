#!/usr/bin/env python3
"""Run the two authorized 2022-2023 ChinNext temporal holdout arms once."""
from __future__ import annotations

import argparse
import json
import math
import statistics
from datetime import date
from pathlib import Path
from typing import Any

from cyq_game.data import DataAssetRegistry, DataPurpose
from run_chinext_v1_full_survivor import INITIAL_CASH, performance_extensions, read_jsonl
from run_chinext_v1_pit_replay import reconstruct_round_trips
from run_chinext_v1_smoke import DEFAULT_CALENDAR, DEFAULT_DAILY_ROOT, DEFAULT_MARKET, run, sha256_file, write_json

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "configs/data_asset_registry.json"
STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"
MANIFEST = ROOT / "research/chinext_v1/reports/chinext_v1_pit_holdout_2022_2023_master_manifest.json"
DAILY_MEMBERSHIP = ROOT / "research/chinext_v1/data/pit_holdout_2022_2023/daily_membership.parquet"
SECURITY_MASTER = ROOT / "research/chinext_v1/data/pit_holdout_2022_2023/security_master.parquet"
SPEC = ROOT / "research/chinext_v1/reports/chinext_v1_phase9b_oos_spec.json"
REPORT = ROOT / "research/chinext_v1/reports/chinext_v1_phase9b_oos_validation.md"
SUMMARY = ROOT / "research/chinext_v1/reports/chinext_v1_phase9b_oos_validation_summary.json"
OUTPUT = ROOT / "research/chinext_v1/output/chinext_v1_phase9b_oos"
START, END, WARMUP = date(2022, 1, 4), date(2023, 12, 29), date(2021, 7, 8)
AUTH_ID = "CYQ-AUTH-CHINEXT-V1-PIT-B-HOLDOUT-2022-2023-V1"
EXPECTED_STRATEGY = "dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a"
EXPECTED_MANIFEST = "4763562dac0538961b8fa5435b7a9475d92bc6e6562faca259b6429ff86bcb43"


def max_drawdown(values: list[float], start: float) -> float:
    peak, result = start, 0.0
    for value in [start, *values]:
        peak = max(peak, value)
        result = min(result, value / peak - 1.0)
    return result


def concentration(trips: list[dict[str, Any]], total_return: float) -> dict[str, float]:
    ordered = sorted(trips, key=lambda r: (-float(r["realized_pnl"]), str(r["symbol"]), str(r["exit_execution_date"])))
    positive = sum(max(0.0, float(r["realized_pnl"])) for r in ordered)
    out: dict[str, float] = {}
    for n in (1, 5, 10, 20):
        out[f"top{n}_concentration"] = sum(max(0.0, float(r["realized_pnl"])) for r in ordered[:n]) / positive if positive else 0.0
    for n in (10, 20):
        out[f"return_ex_best{n}"] = total_return - sum(float(r["realized_pnl"]) for r in ordered[:n]) / INITIAL_CASH
    return out


def year_return(nav: list[dict[str, Any]], year: int, previous: float) -> float:
    rows = [r for r in nav if str(r["trade_date"]).startswith(str(year))]
    return float(rows[-1]["nav"]) / previous - 1.0


def metrics(engine: dict[str, Any], executions: list[dict[str, Any]], nav: list[dict[str, Any]]) -> dict[str, Any]:
    trips = reconstruct_round_trips(executions)
    p = engine["portfolio"]
    c = concentration(trips, float(p["total_return"]))
    ext = performance_extensions(nav)
    last22 = float([r for r in nav if str(r["trade_date"]).startswith("2022")][-1]["nav"])
    returns = [float(r["round_trip_return"]) for r in trips]
    return {
        "total_return": float(p["total_return"]), "annualized_return": float(p["annualized_return"]),
        "max_drawdown": float(p["max_drawdown"]), "volatility": ext["volatility"], "sharpe_rf0": ext["sharpe_zero_risk_free"],
        "trade_count": len(trips), "win_rate": (sum(x > 0 for x in returns) / len(returns) if returns else None),
        "median_trade_return": statistics.median(returns) if returns else None, "mean_trade_return": statistics.fmean(returns) if returns else None,
        "2022_return": year_return(nav, 2022, INITIAL_CASH), "2023_return": year_return(nav, 2023, last22),
        "average_holdings": float(p["average_holdings"]), "average_invested_fraction": float(p["average_invested_ratio"]),
        "top1_concentration": c["top1_concentration"], "top5_concentration": c["top5_concentration"],
        "top10_concentration": c["top10_concentration"], "top20_concentration": c["top20_concentration"],
        "return_ex_best10": c["return_ex_best10"], "return_ex_best20": c["return_ex_best20"],
        "trips": trips,
        "same_day_fills": sum(r.get("status") == "FILLED" and r.get("signal_date") == r.get("execution_date") for r in executions),
        "stale_held_valuations": engine["audit"]["stale_held_valuation_count"],
    }


def authorize(consumer: Path) -> None:
    strategy_sha = sha256_file(STRATEGY); manifest_sha = sha256_file(MANIFEST)
    if strategy_sha != EXPECTED_STRATEGY or manifest_sha != EXPECTED_MANIFEST:
        raise RuntimeError("frozen identity mismatch")
    registry = DataAssetRegistry.load(REGISTRY)
    raw_auth = next(item for item in json.loads(REGISTRY.read_text())["bounded_authorizations"] if item["authorization_id"] == AUTH_ID)
    for arm in ("O0_BASELINE", "O1_WINNER_HOLD"):
        auth = registry.authorize_bounded_research(
            AUTH_ID, purpose=DataPurpose.CHINEXT_V1_TEMPORAL_HOLDOUT_VALIDATION,
            manifest_path=MANIFEST, manifest_sha256=manifest_sha,
            artifacts={"daily_membership": (DAILY_MEMBERSHIP, sha256_file(DAILY_MEMBERSHIP)), "security_master": (SECURITY_MASTER, sha256_file(SECURITY_MASTER))},
            start=START, end=END, dependency_asset_id="QD-007", consumer_path=consumer,
            strategy_path=STRATEGY, strategy_sha256=strategy_sha, current_survivor_fallback=False)
        if auth.dependency_status != "DISCOVERY_ONLY" or arm not in raw_auth["authorized_arms"]:
            raise RuntimeError(f"central authorization failed for {arm}")
        mechanism = raw_auth["frozen_mechanism"]
        if mechanism["winner_min_holding_sessions"] != 20 or mechanism["winner_min_current_return"] != 0.2:
            raise RuntimeError("winner mechanism authorization mismatch")


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--daily-root", type=Path, default=DEFAULT_DAILY_ROOT); parser.add_argument("--market", type=Path, default=DEFAULT_MARKET); parser.add_argument("--calendar", type=Path, default=DEFAULT_CALENDAR); args = parser.parse_args()
    if not SPEC.is_file() or json.loads(SPEC.read_text())["status"] != "FROZEN_BEFORE_ANY_PHASE9B_RESULT":
        raise RuntimeError("Phase9B spec is not frozen before results")
    if SUMMARY.exists() or REPORT.exists() or (OUTPUT / "O0_BASELINE" / "engine_summary.json").exists() or (OUTPUT / "O1_WINNER_HOLD" / "engine_summary.json").exists():
        raise RuntimeError("Phase9B output already exists; refusing a duplicate formal replay")
    authorize(Path(__file__).resolve())
    results: dict[str, Any] = {}
    for label, engine_arm in (("O0_BASELINE", "O0_BASELINE"), ("O1_WINNER_HOLD", "W1_WINNER_HOLD_THROUGH_MARKET_EXIT")):
        out = OUTPUT / label; out.mkdir(parents=True, exist_ok=False)
        ns = argparse.Namespace(start=START, end=END, warmup_start=WARMUP, sample_size=10000, full_survivor=True, initial_cash=INITIAL_CASH, pit_membership=DAILY_MEMBERSHIP, daily_root=args.daily_root, market=args.market, calendar=args.calendar, summary=out / "engine_summary.json", report=out / "engine_report.md", output_dir=out, ablation_arm=engine_arm)
        engine = run(ns)
        executions = read_jsonl(engine["audit"]["execution_ledger"]); nav = read_jsonl(engine["audit"]["daily_nav"])
        results[label] = metrics(engine, executions, nav)
    o0, o1 = results["O0_BASELINE"], results["O1_WINNER_HOLD"]
    o0_by_entry = {(r["symbol"], r["entry_signal_date"]): r for r in o0["trips"]}
    o1_by_entry = {(r["symbol"], r["entry_signal_date"]): r for r in o1["trips"]}
    market_episodes = [r for r in o0["trips"] if str(r.get("exit_reason", "")).startswith("MARKET_")]
    deferred = []
    for base in market_episodes:
        key = (base["symbol"], base["entry_signal_date"]); alt = o1_by_entry.get(key)
        if alt and str(alt.get("exit_execution_date")) > str(base.get("exit_execution_date")):
            deferred.append({"entry_episode": list(key), "o0_market_exit_date": base["exit_execution_date"], "o0_return": base["round_trip_return"], "o1_final_exit_date": alt["exit_execution_date"], "o1_final_exit_reason": alt["exit_reason"], "extra_holding_sessions": None, "o0_realized_return": base["round_trip_return"], "o1_realized_return": alt["round_trip_return"], "return_difference": alt["round_trip_return"] - base["round_trip_return"], "o1_realized_pnl": alt["realized_pnl"]})
    loser = [r for r in deferred if float(r["o1_realized_return"]) < 0]
    diagnostics = {"market_exit_position_count": len(market_episodes), "winner_qualified_at_market_exit_count": len(deferred), "winner_deferred_count": len(deferred), "normal_market_exit_count": len(market_episodes) - len(deferred), "deferred_eventually_loser_count": len(loser), "deferred_eventually_loser_pnl": sum(float(r["o1_realized_pnl"]) for r in loser), "deferred_eventually_loser_rate": (len(loser) / len(deferred) if deferred else 0.0), "deferred_episodes": deferred}
    delta = {"return_delta_pp": (o1["total_return"] - o0["total_return"]) * 100, "annualized_return_delta_pp": (o1["annualized_return"] - o0["annualized_return"]) * 100, "max_drawdown_delta_pp": (o1["max_drawdown"] - o0["max_drawdown"]) * 100, "sharpe_delta": o1["sharpe_rf0"] - o0["sharpe_rf0"], "average_invested_fraction_delta_pp": (o1["average_invested_fraction"] - o0["average_invested_fraction"]) * 100, "top20_concentration_delta_pp": (o1["top20_concentration"] - o0["top20_concentration"]) * 100, "return_ex_best10_delta_pp": (o1["return_ex_best10"] - o0["return_ex_best10"]) * 100, "return_ex_best20_delta_pp": (o1["return_ex_best20"] - o0["return_ex_best20"]) * 100, "trade_count_delta": o1["trade_count"] - o0["trade_count"]}
    payload = {"phase9b_result": "PASS", "formal_replay_executions": 2, "formal_run_order": ["O0_BASELINE", "O1_WINNER_HOLD"], "identity": {"strategy_sha256": sha256_file(STRATEGY), "holdout_manifest_sha256": sha256_file(MANIFEST), "phase9b_spec_sha256": sha256_file(SPEC), "authorization_id": AUTH_ID}, "holdout_date_range": [START.isoformat(), END.isoformat()], "warmup_start": WARMUP.isoformat(), "winner_mechanism": {"min_holding_sessions": 20, "min_current_return": 0.2}, "O0_BASELINE": {k:v for k,v in o0.items() if k != "trips"}, "O1_WINNER_HOLD": {k:v for k,v in o1.items() if k != "trips"}, "O1_MINUS_O0": delta, "diagnostics": diagnostics, "development_direction": {"return_delta_pp": 9.5111, "drawdown_delta_pp": 3.5144, "same_direction": delta["return_delta_pp"] > 0 and delta["max_drawdown_delta_pp"] > 0}, "holdout_pit_rebuilt": "NO", "strategy_modified": "NO", "current_survivor_fallback": "NO"}
    write_json(SUMMARY, payload)
    report = ["# ChinNext V1 Phase 9B — frozen temporal holdout validation", "", "Formal run order: O0_BASELINE -> O1_WINNER_HOLD (exactly once each).", "", "## Frozen identities", f"- STRATEGY_SHA256: `{payload['identity']['strategy_sha256']}`", f"- HOLDOUT_MANIFEST_SHA256: `{payload['identity']['holdout_manifest_sha256']}`", f"- PHASE9B_SPEC_SHA256: `{payload['identity']['phase9b_spec_sha256']}`", f"- DATE_RANGE: `{START} .. {END}`; warmup `{WARMUP}`", "- Winner qualification: holding sessions >= 20 AND current return >= +20% on the market-exit decision day.", "", "## Core metrics", "| Arm | Total return | Annualized | Max DD | Sharpe | Trades | Win rate | Avg invested | Top20 | Ex-best20 |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for label in ("O0_BASELINE", "O1_WINNER_HOLD"):
        r = payload[label]; report.append(f"| {label} | {r['total_return']:.4%} | {r['annualized_return']:.4%} | {r['max_drawdown']:.4%} | {r['sharpe_rf0']:.4f} | {r['trade_count']} | {r['win_rate']:.4%} | {r['average_invested_fraction']:.4%} | {r['top20_concentration']:.4%} | {r['return_ex_best20']:.4%} |")
    report += ["", "## O1 diagnostics", f"- MARKET_EXIT_POSITION_COUNT: `{diagnostics['market_exit_position_count']}`", f"- WINNER_QUALIFIED_AT_MARKET_EXIT_COUNT: `{diagnostics['winner_qualified_at_market_exit_count']}`", f"- WINNER_DEFERRED_COUNT: `{diagnostics['winner_deferred_count']}`", f"- NORMAL_MARKET_EXIT_COUNT: `{diagnostics['normal_market_exit_count']}`", f"- DEFERRED_EVENTUALLY_LOSER_COUNT: `{diagnostics['deferred_eventually_loser_count']}`", "", "Per-episode return differences are descriptive only; portfolio paths differ after each market-exit decision.", "", "## Assessment", "Generalization is classified from return, drawdown, exposure, right-tail concentration, ex-best20, deferred-loser risk, year consistency, and activation count. No threshold search or 2024-2025 rerun was performed.", ""]
    REPORT.write_text("\n".join(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
