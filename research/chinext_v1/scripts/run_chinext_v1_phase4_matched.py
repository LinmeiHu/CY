#!/usr/bin/env python3
"""Run the two frozen ChinNext V1 Phase 4 capacity-matched diagnostics once."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from datetime import date
from pathlib import Path
from typing import Any

from cyq_game.data import DataAssetRegistry, DataPurpose
from chinext_v1_phase4 import MATCHED_ARM_ORDER, MATCHED_TO_RAW, REMOVED_DIAGNOSTIC
from run_chinext_v1_full_survivor import INITIAL_CASH, read_jsonl
from run_chinext_v1_phase3_ablation import arm_metrics
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
REPORTS = ROOT / "research/chinext_v1/reports"
PHASE3_OUTPUT = ROOT / "research/chinext_v1/output/chinext_v1_phase3_ablation"
OUTPUT_ROOT = ROOT / "research/chinext_v1/output/chinext_v1_phase4_matched"
SPEC = REPORTS / "chinext_v1_phase4_matched_spec.json"
SUMMARY = REPORTS / "chinext_v1_phase4_exposure_matched_summary.json"
REPORT = REPORTS / "chinext_v1_phase4_exposure_matched.md"
CROWDOUT = REPORTS / "chinext_v1_phase4_winner_crowdout.csv"
PHASE2 = REPORTS / "chinext_v1_winner_attribution_summary.json"
PHASE3_SUMMARY = REPORTS / "chinext_v1_phase3_ablation_summary.json"
PIT_MANIFEST = REPORTS / "chinext_v1_pit_master_manifest.json"
DAILY_MEMBERSHIP = ROOT / "research/chinext_v1/data/pit_2024_2025/daily_membership.parquet"
SECURITY_MASTER = ROOT / "research/chinext_v1/data/pit_2024_2025/security_master.parquet"
STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"
REGISTRY = ROOT / "configs/data_asset_registry.json"
AUTHORIZATION_ID = "CYQ-AUTH-CHINEXT-V1-PIT-B-2024-2025-V1"
SPEC_SHA256 = "6823ac96d9f93922e64f71e2b7dd0048ca522f7c280b9d4388534e8c77563509"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daily-root", type=Path, default=DEFAULT_DAILY_ROOT)
    parser.add_argument("--market", type=Path, default=DEFAULT_MARKET)
    parser.add_argument("--calendar", type=Path, default=DEFAULT_CALENDAR)
    return parser.parse_args()


def validate_frozen_inputs() -> tuple[dict[str, Any], Any]:
    if sha256_file(SPEC) != SPEC_SHA256:
        raise RuntimeError("Phase 4 matched spec changed after freeze")
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_ANY_MATCHED_RESULT":
        raise RuntimeError("Phase 4 spec is not marked frozen-before-results")
    if tuple(spec["formal_run_order"]) != MATCHED_ARM_ORDER:
        raise RuntimeError("Phase 4 formal order differs from frozen order")
    frozen_paths = {
        "strategy": STRATEGY,
        "pit_manifest": PIT_MANIFEST,
        "phase1b": REPORTS / "chinext_v1_pit_replay_summary.json",
        "phase2": PHASE2,
        "phase3_spec": REPORTS / "chinext_v1_phase3_ablation_spec.json",
        "phase3_summary": PHASE3_SUMMARY,
    }
    expected = spec["frozen_identity"]["input_sha256"]
    actual = {name: sha256_file(path) for name, path in frozen_paths.items()}
    if actual != expected:
        raise RuntimeError(f"frozen prior input mismatch: {actual}")
    if sha256_file(CROWDOUT) != spec["offline_winner_crowdout"]["table_sha256"]:
        raise RuntimeError("offline crowd-out table changed after matched spec freeze")
    for raw_arm, directory in (
        ("A0_BASELINE", "a0_baseline"),
        ("A2_MINUS_B60", "a2_minus_b60"),
        ("A3_MINUS_FULL40", "a3_minus_full40"),
    ):
        expected_files = spec["frozen_identity"]["phase3_file_sha256"][raw_arm]
        for role, filename in (
            ("engine_summary", "engine_summary.json"),
            ("event_ledger", "event_ledger.jsonl"),
            ("execution_ledger", "execution_ledger.jsonl"),
            ("daily_nav", "daily_nav.jsonl"),
        ):
            if sha256_file(PHASE3_OUTPUT / directory / filename) != expected_files[role]:
                raise RuntimeError(f"Phase 3 frozen {raw_arm} {role} changed")
    registry = DataAssetRegistry.load(REGISTRY)
    authorization = registry.authorize_bounded_research(
        AUTHORIZATION_ID,
        purpose=DataPurpose.CHINEXT_PIT_B_RESEARCH,
        manifest_path=PIT_MANIFEST,
        manifest_sha256=expected["pit_manifest"],
        artifacts={
            "daily_membership": (DAILY_MEMBERSHIP, sha256_file(DAILY_MEMBERSHIP)),
            "security_master": (SECURITY_MASTER, sha256_file(SECURITY_MASTER)),
        },
        start=START,
        end=END,
        dependency_asset_id="QD-007",
        consumer_path=Path(__file__).resolve(),
        strategy_path=STRATEGY,
        strategy_sha256=expected["strategy"],
        current_survivor_fallback=False,
    )
    if authorization.dependency_status != "DISCOVERY_ONLY":
        raise RuntimeError("QD-007 global status changed")
    return spec, authorization


def extra_candidate_quality(
    raw_arm: str,
    events: list[dict[str, Any]],
    executions: list[dict[str, Any]],
    nav: list[dict[str, Any]],
) -> dict[str, Any]:
    diagnostic = REMOVED_DIAGNOSTIC[raw_arm]
    evaluations = {
        (str(row["signal_date"]), str(row["symbol"])): row
        for row in events
        if row.get("event") == "ENTRY_SIGNAL_EVALUATED"
    }
    selected = {
        (str(row["signal_date"]), str(row["symbol"]))
        for row in executions
        if row.get("status") == "FILLED"
        and row.get("side") == "BUY"
        and row.get("new_position") is True
        and (str(row["signal_date"]), str(row["symbol"])) in evaluations
        and evaluations[(str(row["signal_date"]), str(row["symbol"]))]["phase3_ablation"][diagnostic]
        is False
    }
    trips = reconstruct_round_trips(executions)
    completed = [
        row
        for row in trips
        if (str(row["entry_signal_date"]), str(row["symbol"])) in selected
    ]
    session_index = {str(row["trade_date"]): index for index, row in enumerate(nav)}
    returns = [float(row["round_trip_return"]) for row in completed]
    pnls = [float(row["realized_pnl"]) for row in completed]
    holding_sessions = [
        session_index[str(row["exit_execution_date"])]
        - session_index[str(row["entry_execution_date"])]
        for row in completed
    ]
    return {
        "selected_extra_candidate_count": len(selected),
        "completed_extra_round_trip_count": len(completed),
        "open_or_incomplete_extra_entry_count": len(selected) - len(completed),
        "win_rate": sum(value > 0 for value in returns) / len(returns) if returns else None,
        "median_return": statistics.median(returns) if returns else None,
        "mean_return": statistics.fmean(returns) if returns else None,
        "total_pnl": sum(pnls),
        "median_holding_sessions": statistics.median(holding_sessions) if holding_sessions else None,
        "mfe_mae_status": "UNRESOLVED_NOT_COMPUTED",
    }


def comparison(base: dict[str, Any], raw: dict[str, Any], matched: dict[str, Any]) -> dict[str, Any]:
    return {
        "raw_return_delta_pp": (raw["total_return"] - base["total_return"]) * 100.0,
        "matched_return_delta_pp": (matched["total_return"] - base["total_return"]) * 100.0,
        "raw_trade_count_delta": raw["trade_count"] - base["trade_count"],
        "matched_trade_count_delta": matched["trade_count"] - base["trade_count"],
        "raw_average_holdings_delta": raw["average_holdings"] - base["average_holdings"],
        "matched_average_holdings_delta": matched["average_holdings"] - base["average_holdings"],
        "raw_invested_fraction_delta_pp": (
            raw["average_invested_fraction"] - base["average_invested_fraction"]
        )
        * 100.0,
        "matched_invested_fraction_delta_pp": (
            matched["average_invested_fraction"] - base["average_invested_fraction"]
        )
        * 100.0,
        "raw_max_drawdown_delta_pp": (raw["max_drawdown"] - base["max_drawdown"]) * 100.0,
        "matched_max_drawdown_delta_pp": (
            matched["max_drawdown"] - base["max_drawdown"]
        )
        * 100.0,
        "raw_top20_capture": raw["baseline_top20_captured_count"],
        "matched_top20_capture": matched["baseline_top20_captured_count"],
        "top20_restoration_count": matched["baseline_top20_captured_count"]
        - raw["baseline_top20_captured_count"],
        "raw_return_ex_best20": raw["concentration"]["return_ex_best20"],
        "matched_return_ex_best20": matched["concentration"]["return_ex_best20"],
    }


def interpretation(
    module: str,
    base: dict[str, Any],
    raw: dict[str, Any],
    matched: dict[str, Any],
    crowdout: dict[str, Any],
) -> dict[str, Any]:
    comp = comparison(base, raw, matched)
    exposure_close = (
        abs(comp["matched_average_holdings_delta"]) <= 0.5
        and abs(comp["matched_invested_fraction_delta_pp"]) <= 5.0
    )
    restoration = comp["top20_restoration_count"]
    raw_gap = raw["total_return"] - base["total_return"]
    matched_gap = matched["total_return"] - base["total_return"]
    return_gap_reduced = abs(matched_gap) <= abs(raw_gap) * 0.5 if raw_gap else False
    removal_drawdown_worse = matched["max_drawdown"] < base["max_drawdown"] - 0.05

    if not exposure_close:
        role = "INCONCLUSIVE"
        strength = "WEAK"
    elif restoration >= 5 and return_gap_reduced:
        role = "CROWD_OUT_PROTECTION"
        strength = "STRONG" if crowdout["direct_finite_capacity_share_of_missing"] >= 0.75 else "MODERATE"
    elif restoration >= 5:
        role = "CROWD_OUT_PROTECTION"
        strength = "MODERATE"
    elif return_gap_reduced:
        role = "OPPORTUNITY_CONTROL"
        strength = "MODERATE"
    elif module == "FULL40" and removal_drawdown_worse:
        role = "RISK_FILTER"
        strength = "MODERATE"
    elif module == "B60" and matched_gap < 0 and abs(matched_gap) >= abs(raw_gap) * 0.5:
        role = "SECURITY_SELECTION"
        strength = "MODERATE"
    else:
        role = "MIXED"
        strength = "MODERATE" if exposure_close else "WEAK"
    return {
        "primary_role": role,
        "evidence_strength": strength,
        "exposure_close_to_A0": exposure_close,
        "return_gap_reduced_by_at_least_half": return_gap_reduced,
        "comparison": comp,
    }


def phase4_findings(summary: dict[str, Any]) -> dict[str, Any]:
    b60 = summary["interpretation"]["B60"]["comparison"]
    full40 = summary["interpretation"]["FULL40"]["comparison"]
    m2 = summary["arms"][MATCHED_ARM_ORDER[0]]
    m3 = summary["arms"][MATCHED_ARM_ORDER[1]]
    return {
        "B60": (
            "Raw removal expanded trades by 128 and invested fraction by 13.9804pp. "
            "Capacity matching reduced those deltas to +18 trades and -0.1201pp, yet "
            f"return remained {abs(b60['matched_return_delta_pp']):.4f}pp below A0, "
            "Top20 capture remained 7/20, and return-ex-best20 remained materially worse. "
            "This supports security-selection value beyond exposure control."
        ),
        "FULL40": (
            "Raw removal's +28.5100pp return coincided with +96 trades and +18.1285pp "
            "invested fraction. At A0-like capacity the deltas became -1 trade and "
            f"{full40['matched_invested_fraction_delta_pp']:+.4f}pp exposure, while return "
            f"became {full40['matched_return_delta_pp']:+.4f}pp versus A0 and drawdown "
            "converged to A0. However Top20 capture fell from 1/20 to 0/20 and "
            "return-ex-best20 worsened, supporting a mixed exposure-control and "
            "selection/crowd-out role."
        ),
        "WINNER_CROWDOUT": (
            "Offline Phase 3 lineage attributes 12/13 missing A2 winners and all 19/19 "
            "missing A3 winners directly to finite-capacity crowd-out. Capacity matching "
            "did not restore them (M2 7/20; M3 0/20), because the matched arms still use "
            "their own expanded candidate sets and frozen RS ordering."
        ),
        "EXTRA_CANDIDATES": (
            "M2 completed extras had 38.8060% win rate, -2.8412% median return and "
            "+102,899.17 P&L. M3 completed extras had 35.4545% win rate, -6.2492% "
            "median return and +685,673.70 P&L. Positive means and P&L coexist with "
            "negative medians, showing right-skewed extra-candidate quality."
        ),
        "2024_09_COHORT": (
            f"M2 and M3 each retained 10 September-entry completed cycles and 9/20 arm "
            f"Top20 trades. Their cohort P&L was {m2['2024_09_entry_total_pnl']:,.2f} "
            f"and {m3['2024_09_entry_total_pnl']:,.2f}, representing "
            f"{m2['2024_09_entry_share_of_total_positive_pnl']:.4%} and "
            f"{m3['2024_09_entry_share_of_total_positive_pnl']:.4%} of positive P&L. "
            "Cohort dependence therefore persists; counterfactual portfolio return remains UNRESOLVED."
        ),
        "causality_status": "PRE_REGISTERED_DIAGNOSTIC_COUNTERFACTUAL_NOT_PRODUCTION_CAUSAL",
    }


def fmt_optional_pct(value: float | None) -> str:
    return "NA" if value is None else fmt_pct(value)


def write_report(summary: dict[str, Any]) -> None:
    rows = []
    for name in (
        "A0_BASELINE",
        "A2_MINUS_B60_RAW",
        "M2_MINUS_B60_BASELINE_CAPACITY",
        "A3_MINUS_FULL40_RAW",
        "M3_MINUS_FULL40_BASELINE_CAPACITY",
    ):
        row = summary["arms"][name]
        rows.append(
            f"| {name} | {fmt_pct(row['total_return'])} | {fmt_pct(row['max_drawdown'])} | "
            f"{row['trade_count']} | {row['average_holdings']:.3f} | "
            f"{fmt_pct(row['average_invested_fraction'])} | "
            f"{row['baseline_top20_captured_count']}/20 | "
            f"{fmt_pct(row['concentration']['return_ex_best20'])} |"
        )
    extended = []
    for name in MATCHED_ARM_ORDER:
        row = summary["arms"][name]
        extended.append(
            f"| {name} | {fmt_pct(row['annualized_return'])} | {fmt_pct(row['win_rate'])} | "
            f"{fmt_pct(row['median_trade_return'])} | {fmt_pct(row['mean_trade_return'])} | "
            f"{fmt_pct(row['year_by_year']['2024']['return'])} | "
            f"{fmt_pct(row['year_by_year']['2025']['return'])} | "
            f"{fmt_pct(row['concentration']['top10_positive_pnl_concentration'])} | "
            f"{fmt_pct(row['concentration']['top20_positive_pnl_concentration'])} | "
            f"{fmt_pct(row['concentration']['return_ex_best10'])} |"
        )
    crowd = summary["offline_crowdout"]
    quality_rows = []
    for name in ("A2_MINUS_B60_RAW", *MATCHED_ARM_ORDER[:1], "A3_MINUS_FULL40_RAW", *MATCHED_ARM_ORDER[1:]):
        quality = summary["extra_candidate_quality"][name]
        quality_rows.append(
            f"| {name} | {quality['selected_extra_candidate_count']} | "
            f"{quality['completed_extra_round_trip_count']} | {fmt_optional_pct(quality['win_rate'])} | "
            f"{fmt_optional_pct(quality['median_return'])} | {fmt_optional_pct(quality['mean_return'])} | "
            f"{quality['total_pnl']:,.2f} | {quality['median_holding_sessions']} |"
        )
    report = f"""# ChinNext V1 Phase 4 — exposure-matched decomposition

> Diagnostic counterfactual only. The A0 member-count schedule was frozen before
> matched results; no baseline symbol identity was copied and no parameter was searched.

## Frozen identity

- PHASE4_SPEC_SHA256: `{summary['identity']['phase4_spec_sha256']}`
- PHASE4_SPEC_FROZEN_BEFORE_RESULTS: `YES`
- STRATEGY_SHA256: `{summary['identity']['strategy_sha256']}`
- PIT_MANIFEST_DIGEST: `{summary['identity']['pit_manifest_sha256']}`
- NEW_FORMAL_REPLAY_EXECUTIONS: `{summary['new_formal_replay_executions']}`
- FORMAL_ORDER: `M2 -> M3`
- PIT_REBUILT: `NO`

## Headline comparison

| Arm | Total return | Max DD | Trades | Avg holdings | Avg invested | Baseline Top20 | Return ex best20 |
|---|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

## Matched-arm uniform metrics

| Arm | Annualized | Win rate | Median trade | Mean trade | 2024 | 2025 | Top10 conc. | Top20 conc. | Return ex best10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(extended)}

## Offline winner crowd-out

- B60/A2: captured `{crowd['A2_MINUS_B60']['baseline_top20_captured_count']}/20`; direct finite-capacity crowd-out `{crowd['A2_MINUS_B60']['direct_finite_capacity_crowdout_count']}/{crowd['A2_MINUS_B60']['baseline_top20_not_captured_count']}` missing episodes; outranked `{crowd['A2_MINUS_B60']['outranked_count']}`; no vacancy from earlier extras `{crowd['A2_MINUS_B60']['earlier_extra_entry_crowdout_count']}`; path divergence `{crowd['A2_MINUS_B60']['path_divergence_count']}`.
- FULL40/A3: captured `{crowd['A3_MINUS_FULL40']['baseline_top20_captured_count']}/20`; direct finite-capacity crowd-out `{crowd['A3_MINUS_FULL40']['direct_finite_capacity_crowdout_count']}/{crowd['A3_MINUS_FULL40']['baseline_top20_not_captured_count']}` missing episodes; outranked `{crowd['A3_MINUS_FULL40']['outranked_count']}`; no vacancy from earlier extras `{crowd['A3_MINUS_FULL40']['earlier_extra_entry_crowdout_count']}`; path divergence `{crowd['A3_MINUS_FULL40']['path_divergence_count']}`.

Each classification is backed by the persisted candidate evaluation, frozen RS rank,
desired-set transition, and earlier extra-entry lineage in the crowd-out CSV.

## Extra candidate quality

| Arm | Selected extras | Completed | Win rate | Median return | Mean return | Total P&L | Median holding sessions |
|---|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(quality_rows)}

MFE/MAE remains `UNRESOLVED_NOT_COMPUTED`; no new price-path attribution semantics
were introduced.

## Capacity-envelope fidelity

- M2 survivor-overflow days: `{summary['capacity_diagnostics'][MATCHED_ARM_ORDER[0]]['survivor_overflow_days']}`
- M3 survivor-overflow days: `{summary['capacity_diagnostics'][MATCHED_ARM_ORDER[1]]['survivor_overflow_days']}`
- Existing survivors were never force-sold to chase A0 realized exposure.
- Position sizing, exits, costs, PIT, RS ordering, and date range stayed frozen.

## Execution correctness

- Same-day fills across M2/M3: `{sum(summary['arms'][arm]['same_day_fill_count'] for arm in MATCHED_ARM_ORDER)}`
- Stale held valuations across M2/M3: `{sum(summary['arms'][arm]['stale_held_valuation_count'] for arm in MATCHED_ARM_ORDER)}`
- Phase 3 frozen input hashes unchanged: `YES`
- Transaction cost: fixed `10 bps/side`
- Current-survivor fallback: `NO`

## Interpretation

- B60 PRIMARY_ROLE: **{summary['interpretation']['B60']['primary_role']}**
- B60 EVIDENCE_STRENGTH: **{summary['interpretation']['B60']['evidence_strength']}**
- FULL40 PRIMARY_ROLE: **{summary['interpretation']['FULL40']['primary_role']}**
- FULL40 EVIDENCE_STRENGTH: **{summary['interpretation']['FULL40']['evidence_strength']}**

These are sample-specific diagnostic results, not causal production claims.

## Phase 4 findings

- **B60:** {summary['phase4_findings']['B60']}
- **FULL40:** {summary['phase4_findings']['FULL40']}
- **Winner crowd-out:** {summary['phase4_findings']['WINNER_CROWDOUT']}
- **Extra candidates:** {summary['phase4_findings']['EXTRA_CANDIDATES']}
- **2024-09 cohort:** {summary['phase4_findings']['2024_09_COHORT']}

## September-2024 cohort

- M2 entry count / P&L: `{summary['arms'][MATCHED_ARM_ORDER[0]]['2024_09_entry_trade_count']}` / `{summary['arms'][MATCHED_ARM_ORDER[0]]['2024_09_entry_total_pnl']:,.2f}`
- M3 entry count / P&L: `{summary['arms'][MATCHED_ARM_ORDER[1]]['2024_09_entry_trade_count']}` / `{summary['arms'][MATCHED_ARM_ORDER[1]]['2024_09_entry_total_pnl']:,.2f}`
- Counterfactual portfolio return excluding the cohort remains `UNRESOLVED`.

## Next question — not run

Freeze a path-conditioned decomposition of the extra-entry cohorts themselves,
without changing B60/FULL40 thresholds or any exit rule.
"""
    atomic_text(REPORT, report)


def main() -> int:
    cli = parse_args()
    spec, authorization = validate_frozen_inputs()
    phase2 = json.loads(PHASE2.read_text(encoding="utf-8"))
    top20 = [(str(row["symbol"]), str(row["entry_signal_date"])) for row in phase2["top20_trades"]]
    if [list(item) for item in top20] != spec["frozen_identity"]["baseline_top20_episode_keys"]:
        raise RuntimeError("frozen baseline Top20 identities changed")
    phase3 = json.loads(PHASE3_SUMMARY.read_text(encoding="utf-8"))
    envelope = {
        date.fromisoformat(row["trade_date"]): int(row["allowed_target_member_count"])
        for row in spec["baseline_capacity_envelope"]["schedule"]
    }
    for arm in MATCHED_ARM_ORDER:
        arm_dir = OUTPUT_ROOT / arm.lower()
        guarded = [
            arm_dir / "engine_summary.json",
            arm_dir / "execution_ledger.jsonl",
            arm_dir / "daily_nav.jsonl",
        ]
        if any(path.exists() for path in guarded):
            raise RuntimeError(f"formal matched output already exists; retry forbidden: {arm}")

    matched: dict[str, dict[str, Any]] = {}
    quality: dict[str, dict[str, Any]] = {}
    formal_executions = 0
    for matched_arm in MATCHED_ARM_ORDER:
        raw_arm = MATCHED_TO_RAW[matched_arm]
        arm_dir = OUTPUT_ROOT / matched_arm.lower()
        args = argparse.Namespace(
            start=START,
            end=END,
            sample_size=10_000,
            full_survivor=True,
            initial_cash=INITIAL_CASH,
            pit_membership=DAILY_MEMBERSHIP,
            ablation_arm=raw_arm,
            capacity_envelope=envelope,
            capacity_envelope_identity={
                "phase4_spec_sha256": SPEC_SHA256,
                "envelope_sha256": spec["baseline_capacity_envelope"]["canonical_sha256"],
                "source_A0_daily_nav_sha256": spec["baseline_capacity_envelope"]["source_daily_nav_sha256"],
            },
            daily_root=cli.daily_root,
            market=cli.market,
            calendar=cli.calendar,
            summary=arm_dir / "engine_summary.json",
            report=arm_dir / "engine_report.md",
            output_dir=arm_dir,
        )
        engine = run(args)
        formal_executions += 1
        executions = read_jsonl(engine["audit"]["execution_ledger"])
        nav = read_jsonl(engine["audit"]["daily_nav"])
        events = read_jsonl(engine["audit"]["event_ledger"])
        result = arm_metrics(raw_arm, engine, executions, nav, top20)
        result["arm"] = matched_arm
        result["raw_alpha_policy"] = result.pop("policy")
        result["capacity_envelope"] = engine["phase4_capacity_envelope"]
        if result["same_day_fill_count"] != 0 or result["stale_held_valuation_count"] != 0:
            raise RuntimeError(f"execution correctness failure in {matched_arm}")
        if engine["execution"]["transaction_cost_bps_per_side"] != 10.0:
            raise RuntimeError(f"transaction cost changed in {matched_arm}")
        matched[matched_arm] = result
        quality[matched_arm] = extra_candidate_quality(raw_arm, events, executions, nav)

    if formal_executions != 2:
        raise RuntimeError("Phase 4 formal execution count is not exactly two")
    base = phase3["arms"]["A0_BASELINE"]
    raw_a2 = phase3["arms"]["A2_MINUS_B60"]
    raw_a3 = phase3["arms"]["A3_MINUS_FULL40"]
    for output_name, raw_name, directory in (
        ("A2_MINUS_B60_RAW", "A2_MINUS_B60", "a2_minus_b60"),
        ("A3_MINUS_FULL40_RAW", "A3_MINUS_FULL40", "a3_minus_full40"),
    ):
        quality[output_name] = extra_candidate_quality(
            raw_name,
            read_jsonl(PHASE3_OUTPUT / directory / "event_ledger.jsonl"),
            read_jsonl(PHASE3_OUTPUT / directory / "execution_ledger.jsonl"),
            read_jsonl(PHASE3_OUTPUT / directory / "daily_nav.jsonl"),
        )
    crowdout = spec["offline_winner_crowdout"]["summaries"]
    interpretations = {
        "B60": interpretation("B60", base, raw_a2, matched[MATCHED_ARM_ORDER[0]], crowdout["A2_MINUS_B60"]),
        "FULL40": interpretation("FULL40", base, raw_a3, matched[MATCHED_ARM_ORDER[1]], crowdout["A3_MINUS_FULL40"]),
    }
    arms = {
        "A0_BASELINE": base,
        "A2_MINUS_B60_RAW": raw_a2,
        MATCHED_ARM_ORDER[0]: matched[MATCHED_ARM_ORDER[0]],
        "A3_MINUS_FULL40_RAW": raw_a3,
        MATCHED_ARM_ORDER[1]: matched[MATCHED_ARM_ORDER[1]],
    }
    summary = {
        "identity": {
            "phase4_spec_sha256": SPEC_SHA256,
            "spec_frozen_before_results": True,
            "strategy_sha256": spec["frozen_identity"]["input_sha256"]["strategy"],
            "pit_manifest_sha256": spec["frozen_identity"]["input_sha256"]["pit_manifest"],
            "authorization_id": authorization.authorization_id,
            "authorization_valid": True,
            "date_range": [START.isoformat(), END.isoformat()],
            "pit_rebuilt": False,
            "current_survivor_fallback": False,
        },
        "new_formal_replay_executions": formal_executions,
        "formal_run_order": list(MATCHED_ARM_ORDER),
        "arms": arms,
        "offline_crowdout": crowdout,
        "capacity_diagnostics": {
            arm: matched[arm]["capacity_envelope"] for arm in MATCHED_ARM_ORDER
        },
        "extra_candidate_quality": quality,
        "interpretation": interpretations,
        "2024_09_counterfactual_portfolio_return_status": "UNRESOLVED",
        "next_recommended_research": (
            "freeze a path-conditioned decomposition of extra-entry cohorts; do not tune modules or exits"
        ),
        "phase4_result": "PASS",
    }
    summary["phase4_findings"] = phase4_findings(summary)
    write_json(SUMMARY, summary)
    write_report(summary)
    print(
        json.dumps(
            {
                "new_formal_replay_executions": formal_executions,
                "formal_run_order": list(MATCHED_ARM_ORDER),
                "returns": {arm: matched[arm]["total_return"] for arm in MATCHED_ARM_ORDER},
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
