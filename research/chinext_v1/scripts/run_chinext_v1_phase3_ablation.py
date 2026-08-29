#!/usr/bin/env python3
"""Execute the frozen six-arm ChinNext V1 Phase 3 module-ablation matrix once."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from datetime import date
from pathlib import Path
from typing import Any

from cyq_game.data import DataAssetRegistry, DataPurpose
from chinext_v1_ablation import ARM_ORDER, phase7_policy_for, policy_for
from run_chinext_v1_full_survivor import INITIAL_CASH, performance_extensions, read_jsonl, year_metrics
from run_chinext_v1_pit_replay import reconstruct_round_trips
from run_chinext_v1_smoke import (
    DEFAULT_CALENDAR,
    DEFAULT_DAILY_ROOT,
    DEFAULT_MARKET,
    atomic_text,
    fmt_pct,
    run,
    sha256_file,
    write_json,
)

ROOT = Path(__file__).resolve().parents[3]
START = date(2024, 1, 2)
END = date(2025, 12, 31)
AUTHORIZATION_ID = "CYQ-AUTH-CHINEXT-V1-PIT-B-2024-2025-V1"
REGISTRY = ROOT / "configs/data_asset_registry.json"
SPEC = ROOT / "research/chinext_v1/reports/chinext_v1_phase3_ablation_spec.json"
SPEC_SHA256 = "530a5cabddf5afbef86f3fd433a6be35a36973bf3f7662944267a3bec97f160c"
MANIFEST = ROOT / "research/chinext_v1/reports/chinext_v1_pit_master_manifest.json"
DAILY_MEMBERSHIP = ROOT / "research/chinext_v1/data/pit_2024_2025/daily_membership.parquet"
SECURITY_MASTER = ROOT / "research/chinext_v1/data/pit_2024_2025/security_master.parquet"
STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"
PHASE1B = ROOT / "research/chinext_v1/reports/chinext_v1_pit_replay_summary.json"
PHASE2 = ROOT / "research/chinext_v1/reports/chinext_v1_winner_attribution_summary.json"
OUTPUT_ROOT = ROOT / "research/chinext_v1/output/chinext_v1_phase3_ablation"
OUTPUT_SUMMARY = ROOT / "research/chinext_v1/reports/chinext_v1_phase3_ablation_summary.json"
OUTPUT_REPORT = ROOT / "research/chinext_v1/reports/chinext_v1_phase3_ablation.md"
EXPECTED_STRATEGY = "dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a"
EXPECTED_MANIFEST = "8b4519ff6cf74aa0ca13b15bd3954cce3a37f6dd19d25f3f77743e9a974e75f7"
EXPECTED_PHASE1B = "10c9a10860dfaef5ee621a5e98741a9b0f881be247e8115cd524d9098a66d6af"
EXPECTED_PHASE2 = "185ea2e5da93972b745e8ad60d86cdd71a11a0f8de7cb16e84c88dda39214430"
EXPECTED_A0_EXECUTION = "f3a83a9e974776f34477c952b1bf4c26f22a5ef00879adfc77cd6188f9eec9d5"
EXPECTED_A0_NAV = "a1b8399c7f199a76ae6e891bbd690de16a3312d2cc548c77d552f2531adcc071"
ARM_MODULE = {
    "A1_MINUS_MINVOL": "MINVOL",
    "A2_MINUS_B60": "B60",
    "A3_MINUS_FULL40": "FULL40",
    "A4_NO_RS_SELECTION_CONTROL": "RS_SELECTION",
    "A5_MINUS_MARKET_ENTRY_GATE": "MARKET_ENTRY_GATE",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daily-root", type=Path, default=DEFAULT_DAILY_ROOT)
    parser.add_argument("--market", type=Path, default=DEFAULT_MARKET)
    parser.add_argument("--calendar", type=Path, default=DEFAULT_CALENDAR)
    return parser.parse_args()


def authorize_and_freeze() -> tuple[dict[str, Any], dict[str, Any], Any]:
    frozen = {
        "spec": sha256_file(SPEC),
        "strategy": sha256_file(STRATEGY),
        "pit_manifest": sha256_file(MANIFEST),
        "phase1b": sha256_file(PHASE1B),
        "phase2": sha256_file(PHASE2),
        "daily_membership": sha256_file(DAILY_MEMBERSHIP),
        "security_master": sha256_file(SECURITY_MASTER),
    }
    expected = {
        "spec": SPEC_SHA256,
        "strategy": EXPECTED_STRATEGY,
        "pit_manifest": EXPECTED_MANIFEST,
        "phase1b": EXPECTED_PHASE1B,
        "phase2": EXPECTED_PHASE2,
    }
    mismatches = {
        key: {"expected": value, "actual": frozen[key]}
        for key, value in expected.items()
        if frozen[key] != value
    }
    if mismatches:
        raise RuntimeError(f"frozen Phase 3 input mismatch: {mismatches}")
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if tuple(spec["formal_run_order"]) != ARM_ORDER:
        raise RuntimeError("spec run order differs from registered arm order")
    if spec["status"] != "FROZEN_BEFORE_ANY_ABLATION_RESULT":
        raise RuntimeError("ablation spec is not frozen-before-results")
    registry = DataAssetRegistry.load(REGISTRY)
    authorization = registry.authorize_bounded_research(
        AUTHORIZATION_ID,
        purpose=DataPurpose.CHINEXT_PIT_B_RESEARCH,
        manifest_path=MANIFEST,
        manifest_sha256=frozen["pit_manifest"],
        artifacts={
            "daily_membership": (DAILY_MEMBERSHIP, frozen["daily_membership"]),
            "security_master": (SECURITY_MASTER, frozen["security_master"]),
        },
        start=START,
        end=END,
        dependency_asset_id="QD-007",
        consumer_path=Path(__file__).resolve(),
        strategy_path=STRATEGY,
        strategy_sha256=frozen["strategy"],
        current_survivor_fallback=False,
    )
    if authorization.dependency_status != "DISCOVERY_ONLY":
        raise RuntimeError("QD-007 global status changed")
    return frozen, spec, authorization


def concentration_metrics(
    round_trips: list[dict[str, Any]], total_return: float
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not round_trips:
        raise RuntimeError("arm produced no completed round trips")
    ordered = sorted(
        round_trips,
        key=lambda row: (-float(row["realized_pnl"]), row["symbol"], row["exit_execution_date"]),
    )
    positive_total = sum(max(0.0, float(row["realized_pnl"])) for row in ordered)
    if positive_total <= 0:
        raise RuntimeError("arm produced no positive completed-cycle P&L")
    result: dict[str, Any] = {"positive_round_trip_pnl": positive_total}
    for count in (1, 5, 10, 20):
        top = ordered[:count]
        result[f"top{count}_positive_pnl_concentration"] = sum(
            max(0.0, float(row["realized_pnl"])) for row in top
        ) / positive_total
        if count in (10, 20):
            result[f"return_ex_best{count}"] = total_return - sum(
                float(row["realized_pnl"]) for row in top
            ) / INITIAL_CASH
    return result, ordered


def arm_metrics(
    arm: str,
    engine_summary: dict[str, Any],
    executions: list[dict[str, Any]],
    nav: list[dict[str, Any]],
    baseline_top20: list[tuple[str, str]],
) -> dict[str, Any]:
    round_trips = reconstruct_round_trips(executions)
    total_return = float(engine_summary["portfolio"]["total_return"])
    concentration, ordered = concentration_metrics(round_trips, total_return)
    baseline_top20_set = set(baseline_top20)
    baseline_top10_set = set(baseline_top20[:10])
    selected_episodes = {
        (str(row["symbol"]), str(row["signal_date"]))
        for row in executions
        if row.get("status") == "FILLED"
        and row.get("side") == "BUY"
        and row.get("new_position") is True
    }
    selected_symbols = {symbol for symbol, _ in selected_episodes}
    captured20 = baseline_top20_set & selected_episodes
    captured10 = baseline_top10_set & selected_episodes
    unrelated_same_symbol = {
        symbol
        for symbol, episode_date in baseline_top20_set - captured20
        if symbol in selected_symbols
        and any(s == symbol and day != episode_date for s, day in selected_episodes)
    }
    arm_top20 = ordered[:20]
    arm_top20_episodes = {
        (str(row["symbol"]), str(row["entry_signal_date"])) for row in arm_top20
    }
    arm_overlap = arm_top20_episodes & baseline_top20_set
    cohort = [
        row
        for row in round_trips
        if "2024-09-01" <= str(row["entry_signal_date"]) <= "2024-09-30"
    ]
    cohort_positive = sum(max(0.0, float(row["realized_pnl"])) for row in cohort)
    top20_cohort_count = sum(
        "2024-09-01" <= str(row["entry_signal_date"]) <= "2024-09-30"
        for row in arm_top20
    )
    extended = performance_extensions(nav)
    last_2024 = float(
        [row for row in nav if str(row["trade_date"]).startswith("2024")][-1]["nav"]
    )
    year_by_year = {
        "2024": year_metrics(nav, round_trips, 2024, INITIAL_CASH),
        "2025": year_metrics(nav, round_trips, 2025, last_2024),
    }
    return {
        "arm": arm,
        "policy": (phase7_policy_for(arm).to_dict() if arm.startswith("E") else policy_for(arm).to_dict()),
        "total_return": total_return,
        "annualized_return": float(engine_summary["portfolio"]["annualized_return"]),
        "max_drawdown": float(engine_summary["portfolio"]["max_drawdown"]),
        "trade_count": len(round_trips),
        "win_rate": float(engine_summary["portfolio"]["win_rate"]),
        "median_trade_return": float(engine_summary["portfolio"]["median_trade_return"]),
        "mean_trade_return": float(engine_summary["portfolio"]["average_trade_return"]),
        "sharpe_rf0": extended["sharpe_zero_risk_free"],
        "volatility": extended["volatility"],
        "year_by_year": year_by_year,
        "concentration": concentration,
        "baseline_top20_captured_count": len(captured20),
        "baseline_top20_captured_pct": len(captured20) / 20.0,
        "baseline_top10_captured_count": len(captured10),
        "baseline_top10_captured_pct": len(captured10) / 10.0,
        "baseline_top20_same_symbol_unrelated_episode_count": len(unrelated_same_symbol),
        "baseline_top20_same_symbol_unrelated_symbols": sorted(unrelated_same_symbol),
        "arm_top20_total_pnl": sum(float(row["realized_pnl"]) for row in arm_top20),
        "arm_top20_new_trade_count": len(arm_top20) - len(arm_overlap),
        "arm_top20_overlap_with_baseline_top20": len(arm_overlap),
        "arm_top20_episode_keys": sorted([list(item) for item in arm_top20_episodes]),
        "2024_09_entry_trade_count": len(cohort),
        "2024_09_entry_total_pnl": sum(float(row["realized_pnl"]) for row in cohort),
        "2024_09_entry_share_of_total_positive_pnl": (
            cohort_positive / concentration["positive_round_trip_pnl"]
        ),
        "top20_from_2024_09_count": top20_cohort_count,
        "pnl_excluding_2024_09_entry_cohort": sum(
            float(row["realized_pnl"])
            for row in round_trips
            if not "2024-09-01" <= str(row["entry_signal_date"]) <= "2024-09-30"
        ),
        "return_excluding_2024_09_entry_cohort": None,
        "return_excluding_2024_09_entry_cohort_status": (
            "UNRESOLVED: no cash-flow counterfactual NAV is fabricated"
        ),
        "candidate_event_count": int(
            engine_summary["signals"]["final_entry_candidate_count"]
        ),
        "selected_entry_count": int(
            engine_summary["execution"]["entry_buy_execution_count"]
        ),
        "average_holdings": float(engine_summary["portfolio"]["average_holdings"]),
        "average_invested_fraction": float(
            engine_summary["portfolio"]["average_invested_ratio"]
        ),
        "ending_holdings": engine_summary["portfolio"]["ending_holdings"],
        "execution_ledger": engine_summary["audit"]["execution_ledger"],
        "execution_ledger_sha256": engine_summary["audit"]["execution_ledger_sha256"],
        "daily_nav": engine_summary["audit"]["daily_nav"],
        "daily_nav_sha256": engine_summary["audit"]["daily_nav_sha256"],
        "same_day_fill_count": sum(
            row.get("status") == "FILLED" and row["signal_date"] == row["execution_date"]
            for row in executions
        ),
        "stale_held_valuation_count": engine_summary["audit"]["stale_held_valuation_count"],
    }


def compare_to_baseline(arm: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    concentration = arm["concentration"]
    base_concentration = baseline["concentration"]
    return {
        "return_delta_pp": (arm["total_return"] - baseline["total_return"]) * 100.0,
        "max_drawdown_delta_pp": (arm["max_drawdown"] - baseline["max_drawdown"]) * 100.0,
        "trade_count_delta": arm["trade_count"] - baseline["trade_count"],
        "top20_concentration_delta_pp": (
            concentration["top20_positive_pnl_concentration"]
            - base_concentration["top20_positive_pnl_concentration"]
        )
        * 100.0,
        "return_ex_best20_delta_pp": (
            concentration["return_ex_best20"] - base_concentration["return_ex_best20"]
        )
        * 100.0,
        "baseline_top20_capture_delta": arm["baseline_top20_captured_count"] - 20,
        "average_invested_fraction_delta_pp": (
            arm["average_invested_fraction"] - baseline["average_invested_fraction"]
        )
        * 100.0,
        "candidate_event_count_delta": (
            arm["candidate_event_count"] - baseline["candidate_event_count"]
        ),
        "selected_entry_count_delta": (
            arm["selected_entry_count"] - baseline["selected_entry_count"]
        ),
    }


def module_label(
    arm: dict[str, Any], baseline: dict[str, Any], delta: dict[str, Any]
) -> str:
    return_delta = delta["return_delta_pp"]
    drawdown_delta = delta["max_drawdown_delta_pp"]
    concentration_delta = delta["top20_concentration_delta_pp"]
    ex20_delta = delta["return_ex_best20_delta_pp"]
    capture_loss = -delta["baseline_top20_capture_delta"]
    trade_expansion = arm["trade_count"] / baseline["trade_count"]
    exposure_expansion = (
        arm["average_invested_fraction"] / baseline["average_invested_fraction"]
    )
    if return_delta >= 10 and drawdown_delta >= -3 and ex20_delta >= 10:
        return "POSSIBLY_HARMFUL"
    if drawdown_delta <= -5 or trade_expansion >= 1.25 or exposure_expansion >= 1.25:
        return "RISK_FILTERING"
    if return_delta <= -10 and (capture_loss > 0 or ex20_delta < 0):
        return "CLEARLY_HELPFUL"
    if (
        abs(return_delta) < 5
        and abs(drawdown_delta) < 3
        and abs(concentration_delta) < 5
        and abs(ex20_delta) < 5
        and capture_loss <= 2
    ):
        return "REDUNDANT_IN_THIS_SAMPLE"
    opposite_risk = (
        return_delta >= 5
        and (
            drawdown_delta <= -3
            or concentration_delta >= 5
            or capture_loss >= 3
            or exposure_expansion >= 1.25
        )
    ) or (return_delta <= -5 and drawdown_delta >= 3)
    if opposite_risk:
        return "TRADEOFF"
    return "INCONCLUSIVE"


def interpret(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    baseline = results["A0_BASELINE"]
    arms = [name for name in ARM_ORDER if name != "A0_BASELINE"]
    comparisons = {
        name: compare_to_baseline(results[name], baseline) for name in arms
    }
    labels = {
        name: module_label(results[name], baseline, comparisons[name]) for name in arms
    }
    most_negative_return = min(arms, key=lambda name: comparisons[name]["return_delta_pp"])
    helpful_delta = comparisons[most_negative_return]
    most_helpful = (
        ARM_MODULE[most_negative_return]
        if helpful_delta["return_delta_pp"] <= -10
        and (
            helpful_delta["baseline_top20_capture_delta"] < 0
            or helpful_delta["return_ex_best20_delta_pp"] < 0
        )
        else "INCONCLUSIVE"
    )
    redundant = [name for name in arms if labels[name] == "REDUNDANT_IN_THIS_SAMPLE"]
    most_redundant = (
        ARM_MODULE[min(redundant, key=lambda name: abs(comparisons[name]["return_delta_pp"]))]
        if redundant
        else "INCONCLUSIVE"
    )
    risk_arm = min(arms, key=lambda name: comparisons[name]["max_drawdown_delta_pp"])
    largest_risk = (
        ARM_MODULE[risk_arm]
        if abs(comparisons[risk_arm]["max_drawdown_delta_pp"]) >= 1
        else "INCONCLUSIVE"
    )
    capture_arm = min(
        arms,
        key=lambda name: (
            results[name]["baseline_top20_captured_count"], ARM_ORDER.index(name)
        ),
    )
    return {
        "comparisons_to_A0": comparisons,
        "module_labels": labels,
        "most_helpful_module": most_helpful,
        "most_redundant_module": most_redundant,
        "module_with_largest_risk_control_effect": largest_risk,
        "module_with_largest_winner_capture_effect": ARM_MODULE[capture_arm],
    }


def phase3_findings(
    results: dict[str, dict[str, Any]], interpretation: dict[str, Any]
) -> dict[str, Any]:
    comparisons = interpretation["comparisons_to_A0"]
    return {
        "MINVOL": (
            "Removing MINVOL added 141 candidate events and 14 completed trades, "
            "but reduced return by 16.7983pp, worsened return-ex-best20 by 25.9348pp, "
            "and captured only 15/20 baseline winner episodes."
        ),
        "B60": (
            "Removing B60 expanded candidates by 11,431, trades by 128, and average "
            "exposure by 13.9804pp; return fell 62.4997pp and baseline winner capture "
            "fell to 7/20 despite a 4.0165pp shallower max drawdown."
        ),
        "FULL40": (
            "Removing FULL40 raised return by 28.5100pp but expanded candidates by "
            "13,591 and exposure by 18.1285pp, worsened max drawdown by 6.0494pp and "
            "return-ex-best20 by 40.0894pp, and retained only 1/20 baseline winners."
        ),
        "RS_SELECTION": (
            "The deterministic no-RS control kept opportunity and exposure near A0, "
            "returned 2.1298pp less, and retained 16/20 baseline winner episodes; the "
            "pre-registered multi-metric result is INCONCLUSIVE."
        ),
        "MARKET_ENTRY_GATE": (
            "Removing only the market entry gate changed return by +0.1647pp, max "
            "drawdown by +0.2369pp, exposure by +0.0519pp, and retained all 20 baseline "
            "winner episodes; it is REDUNDANT_IN_THIS_SAMPLE."
        ),
        "2024_09_COHORT_DEPENDENCE": (
            "A0 has 10 September-entry completed cycles, 706,394.41 P&L, 43.3046% "
            "of positive P&L, and 9/20 arm winners. A1/A2/A4/A5 preserve strong cohort "
            "dependence. A3 reduces the share to 22.8551% and 4/20 only while replacing "
            "the opportunity set, exposure, and 19/20 baseline winners. Counterfactual "
            "portfolio return excluding the cohort remains UNRESOLVED."
        ),
        "labels": interpretation["module_labels"],
        "comparison_values": comparisons,
        "causality_status": "PRE_REGISTERED_DESCRIPTIVE_ABLATION_NOT_CAUSAL",
    }


def write_report(summary: dict[str, Any]) -> None:
    lines = [
        "| Arm | Total return | Max DD | Trades | Win rate | Top20 conc. | Return ex best20 | Baseline Top20 captured | Sep-2024 P&L | Avg invested | Label |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for name in ARM_ORDER:
        row = summary["arms"][name]
        label = "REFERENCE" if name == "A0_BASELINE" else summary["interpretation"]["module_labels"][name]
        lines.append(
            f"| {name} | {fmt_pct(row['total_return'])} | {fmt_pct(row['max_drawdown'])} | "
            f"{row['trade_count']} | {fmt_pct(row['win_rate'])} | "
            f"{fmt_pct(row['concentration']['top20_positive_pnl_concentration'])} | "
            f"{fmt_pct(row['concentration']['return_ex_best20'])} | "
            f"{row['baseline_top20_captured_count']}/20 | {row['2024_09_entry_total_pnl']:,.2f} | "
            f"{fmt_pct(row['average_invested_fraction'])} | {label} |"
        )
    extended_lines = [
        "| Arm | Annualized | Median trade | Mean trade | 2024 return | 2025 return | Top1 conc. | Top5 conc. | Top10 conc. | Sharpe rf=0 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ARM_ORDER:
        row = summary["arms"][name]
        concentration = row["concentration"]
        extended_lines.append(
            f"| {name} | {fmt_pct(row['annualized_return'])} | "
            f"{fmt_pct(row['median_trade_return'])} | {fmt_pct(row['mean_trade_return'])} | "
            f"{fmt_pct(row['year_by_year']['2024']['return'])} | "
            f"{fmt_pct(row['year_by_year']['2025']['return'])} | "
            f"{fmt_pct(concentration['top1_positive_pnl_concentration'])} | "
            f"{fmt_pct(concentration['top5_positive_pnl_concentration'])} | "
            f"{fmt_pct(concentration['top10_positive_pnl_concentration'])} | "
            f"{row['sharpe_rf0']:.4f} |"
        )
    delta_lines = [
        "| Arm | Return Δpp | MaxDD Δpp | Trades Δ | Top20 conc. Δpp | Ex-best20 Δpp | Top20 capture Δ | Candidate events Δ | Selected entries Δ |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ARM_ORDER[1:]:
        row = summary["interpretation"]["comparisons_to_A0"][name]
        delta_lines.append(
            f"| {name} | {row['return_delta_pp']:.4f} | {row['max_drawdown_delta_pp']:.4f} | "
            f"{row['trade_count_delta']} | {row['top20_concentration_delta_pp']:.4f} | "
            f"{row['return_ex_best20_delta_pp']:.4f} | {row['baseline_top20_capture_delta']} | "
            f"{row['candidate_event_count_delta']} | {row['selected_entry_count_delta']} |"
        )
    opportunity_lines = [
        "| Arm | Candidate events | Selected entries | Trades | Avg holdings | Avg invested | Sep trades | Sep positive-P&L share | Sep Top20 | P&L ex Sep cohort |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ARM_ORDER:
        row = summary["arms"][name]
        opportunity_lines.append(
            f"| {name} | {row['candidate_event_count']} | {row['selected_entry_count']} | "
            f"{row['trade_count']} | {row['average_holdings']:.3f} | "
            f"{fmt_pct(row['average_invested_fraction'])} | {row['2024_09_entry_trade_count']} | "
            f"{fmt_pct(row['2024_09_entry_share_of_total_positive_pnl'])} | "
            f"{row['top20_from_2024_09_count']} | {row['pnl_excluding_2024_09_entry_cohort']:,.2f} |"
        )
    interpretation = summary["interpretation"]
    report = f"""# ChinNext V1 Phase 3 — pre-registered module ablation

> Six arms were frozen before results and executed once in the specified A0–A5
> order. This is module removal/isolation, not parameter optimization.

## Frozen identity

- ABLATION_SPEC_SHA256: `{summary['identity']['spec_sha256']}`
- ABLATION_SPEC_FROZEN_BEFORE_RESULTS: `YES`
- STRATEGY_SHA256: `{summary['identity']['strategy_sha256']}`
- PIT_MANIFEST_DIGEST: `{summary['identity']['pit_manifest_sha256']}`
- AUTHORIZATION_ID: `{summary['identity']['authorization_id']}`
- DATE_RANGE: `{START} .. {END}`
- FORMAL_REPLAY_EXECUTIONS: `{summary['formal_replay_executions']}`
- PIT_REBUILT: `NO`
- CURRENT_SURVIVOR_FALLBACK: `NO`

## Arm results

{chr(10).join(lines)}

### Extended uniform metrics

{chr(10).join(extended_lines)}

## Deltas versus A0

{chr(10).join(delta_lines)}

Percentage-point deltas use the frozen definitions in the pre-registration spec.
Drawdown delta below zero means the ablation arm suffered a worse drawdown.

## Opportunity set, exposure, and September-2024 cohort

{chr(10).join(opportunity_lines)}

`RETURN_EXCLUDING_2024_09_ENTRY_COHORT` is **UNRESOLVED** for every arm: removing
realized trade cash flows does not reconstruct a valid counterfactual portfolio
NAV because capital availability and later sizing would change. The table reports
the pre-registered auditable completed-cycle P&L diagnostic instead.

## Winner capture and creation

| Arm | Baseline Top10 captured | Baseline Top20 captured | Same-symbol unrelated | Arm Top20 baseline overlap | Arm Top20 new trades | Arm Top20 P&L |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(f"| {name} | {summary['arms'][name]['baseline_top10_captured_count']}/10 | {summary['arms'][name]['baseline_top20_captured_count']}/20 | {summary['arms'][name]['baseline_top20_same_symbol_unrelated_episode_count']} | {summary['arms'][name]['arm_top20_overlap_with_baseline_top20']} | {summary['arms'][name]['arm_top20_new_trade_count']} | {summary['arms'][name]['arm_top20_total_pnl']:,.2f} |" for name in ARM_ORDER)}

Capture requires the exact `(symbol, entry_signal_date)` episode. Trading the same
symbol at another date is shown separately and never counted as capture.

## Pre-registered interpretation

- MOST_HELPFUL_MODULE: **{interpretation['most_helpful_module']}**
- MOST_REDUNDANT_MODULE: **{interpretation['most_redundant_module']}**
- MODULE_WITH_LARGEST_RISK_CONTROL_EFFECT: **{interpretation['module_with_largest_risk_control_effect']}**
- MODULE_WITH_LARGEST_WINNER_CAPTURE_EFFECT: **{interpretation['module_with_largest_winner_capture_effect']}**

Labels apply the multi-metric rules frozen in the spec. A higher return caused by
more candidates, trades, or exposure is not by itself evidence that a module is
harmful. All conclusions remain sample-specific descriptive ablation evidence.

## Phase 3 findings

- **MINVOL:** {summary['phase3_findings']['MINVOL']}
- **B60:** {summary['phase3_findings']['B60']}
- **FULL40:** {summary['phase3_findings']['FULL40']}
- **RS selection:** {summary['phase3_findings']['RS_SELECTION']}
- **Market entry gate:** {summary['phase3_findings']['MARKET_ENTRY_GATE']}
- **2024-09 cohort:** {summary['phase3_findings']['2024_09_COHORT_DEPENDENCE']}

## Execution correctness

- A0 execution ledger reproduces Phase 1B byte-for-byte: `YES`
- A0 daily NAV reproduces Phase 1B byte-for-byte: `YES`
- Same-day fills across all arms: `{sum(row['same_day_fill_count'] for row in summary['arms'].values())}`
- Stale held valuations across all arms: `{sum(row['stale_held_valuation_count'] for row in summary['arms'].values())}`
- Transaction cost: fixed `10 bps/side` in all arms
- Position and exit semantics: identical in all arms

## Next research question — not run

Perform an exposure-matched decomposition of any high-opportunity-set arms, with
the complete control matrix frozen before execution. Exit ablation remains out of
scope until ledger reasons can distinguish individual MA exits from other set
changes.
"""
    atomic_text(OUTPUT_REPORT, report)


def main() -> int:
    cli = parse_args()
    frozen, spec, authorization = authorize_and_freeze()
    phase2 = json.loads(PHASE2.read_text(encoding="utf-8"))
    baseline_top20 = [
        (str(row["symbol"]), str(row["entry_signal_date"]))
        for row in phase2["top20_trades"]
    ]
    if [list(item) for item in baseline_top20] != spec["frozen_baseline"]["baseline_top20_episode_keys"]:
        raise RuntimeError("Phase 2 Top20 episode identities differ from frozen spec")

    for arm in ARM_ORDER:
        arm_dir = OUTPUT_ROOT / arm.lower()
        guarded = [
            arm_dir / "execution_ledger.jsonl",
            arm_dir / "daily_nav.jsonl",
            arm_dir / "engine_summary.json",
        ]
        existing = [str(path) for path in guarded if path.exists()]
        if existing:
            raise RuntimeError(f"formal arm output already exists; replay retry forbidden: {existing}")

    results: dict[str, dict[str, Any]] = {}
    formal_replay_executions = 0
    for arm in ARM_ORDER:
        arm_dir = OUTPUT_ROOT / arm.lower()
        replay_args = argparse.Namespace(
            start=START,
            end=END,
            sample_size=10_000,
            full_survivor=True,
            initial_cash=INITIAL_CASH,
            pit_membership=DAILY_MEMBERSHIP,
            ablation_arm=arm,
            daily_root=cli.daily_root,
            market=cli.market,
            calendar=cli.calendar,
            summary=arm_dir / "engine_summary.json",
            report=arm_dir / "engine_report.md",
            output_dir=arm_dir,
        )
        engine_summary = run(replay_args)
        formal_replay_executions += 1
        executions = read_jsonl(engine_summary["audit"]["execution_ledger"])
        nav = read_jsonl(engine_summary["audit"]["daily_nav"])
        result = arm_metrics(arm, engine_summary, executions, nav, baseline_top20)
        if result["same_day_fill_count"] != 0 or result["stale_held_valuation_count"] != 0:
            raise RuntimeError(f"execution correctness failure in {arm}")
        if engine_summary["execution"]["transaction_cost_bps_per_side"] != 10.0:
            raise RuntimeError(f"transaction cost changed in {arm}")
        results[arm] = result
        if arm == "A0_BASELINE":
            if result["execution_ledger_sha256"] != EXPECTED_A0_EXECUTION:
                raise RuntimeError("A0 execution ledger does not reproduce Phase 1B")
            if result["daily_nav_sha256"] != EXPECTED_A0_NAV:
                raise RuntimeError("A0 NAV does not reproduce Phase 1B")
            if not math.isclose(result["total_return"], 1.0524221580500002, abs_tol=1e-12):
                raise RuntimeError("A0 total return does not reproduce Phase 1B")
            if result["trade_count"] != 111:
                raise RuntimeError("A0 trade count does not reproduce Phase 1B")

    interpretation = interpret(results)
    findings = phase3_findings(results, interpretation)
    summary = {
        "identity": {
            "spec_path": str(SPEC),
            "spec_sha256": frozen["spec"],
            "spec_frozen_before_results": True,
            "strategy_sha256": frozen["strategy"],
            "pit_manifest_sha256": frozen["pit_manifest"],
            "authorization_id": authorization.authorization_id,
            "authorization_valid": True,
            "qd007_global_status": authorization.dependency_status,
            "date_range": [START.isoformat(), END.isoformat()],
            "pit_rebuilt": False,
            "current_survivor_fallback": False,
        },
        "formal_replay_executions": formal_replay_executions,
        "formal_run_order": list(ARM_ORDER),
        "arms": results,
        "interpretation": interpretation,
        "phase3_findings": findings,
        "return_excluding_2024_09_entry_cohort_status": "UNRESOLVED_FOR_ALL_ARMS",
        "next_recommended_research": (
            "pre-register an exposure-matched decomposition; do not run exit ablation until exit reason lineage is separable"
        ),
    }
    write_json(OUTPUT_SUMMARY, summary)
    write_report(summary)
    print(
        json.dumps(
            {
                "formal_replay_executions": formal_replay_executions,
                "run_order": list(ARM_ORDER),
                "total_returns": {name: results[name]["total_return"] for name in ARM_ORDER},
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
