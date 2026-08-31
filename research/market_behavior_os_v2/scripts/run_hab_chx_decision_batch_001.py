#!/usr/bin/env python3
"""Run two fixed, simple CHINEXT decision translations on consumed pre-2024 history."""

from __future__ import annotations

import json
import math
import shutil
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_hab_chx_downrev_strat_001 as shared  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/HAB-CHX-DECISION-BATCH-001_spec.json"
RESULT_PATH = PROGRAM / "artifacts/HAB-CHX-DECISION-BATCH-001_result.json"
REPORT_PATH = PROGRAM / "reports/HAB-CHX-DECISION-BATCH-001_strategy_replay.md"
OUTPUT_ROOT = PROGRAM / "artifacts/HAB-CHX-DECISION-BATCH-001"
EXPECTED_SPEC_SHA256 = "777c8a5675bb8fd98bf4b88184c1a5801f775be998a1527e82c1ef6eb3fd6918"

SELECTION_ARM = "RS_ACCEL_OVEREXTENSION_VETO"
EXPOSURE_ARM = "MINVOL_HIGH_HALF_GROSS"
RS_ACCEL_THRESHOLD = 0.20
STATE = "minute_realized_volatility__ordinal_progression__pit_3y_pct"
STATE_THRESHOLD = 0.80
STATE_ACTIVATION = date(2020, 2, 7)
END = date(2023, 12, 29)
BASE_TARGET = 0.10
HIGH_TARGET = 0.05


class DecisionBatchError(RuntimeError):
    """Fail-closed two-arm replay error."""


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_spec() -> dict[str, Any]:
    if shared.sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise DecisionBatchError("decision-batch spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "POST_SCREEN_FIXED_TWO_ARM_CONTRACT":
        raise DecisionBatchError("decision-batch honesty status changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or shared.sha256_file(path) != binding["sha256"]:
            raise DecisionBatchError(f"bound input identity mismatch: {name}")
    selection = spec["arms"][SELECTION_ARM]
    exposure = spec["arms"][EXPOSURE_ARM]
    if (
        selection["rule"] != "exclude a new candidate when r20 - r120 >= 0.20"
        or selection["threshold_search"] is not False
        or exposure["rule"]
        != "target 5% per selected holding when coordinate >= 0.80; otherwise baseline 10%"
        or exposure["threshold_search"] is not False
        or exposure["exposure_search"] is not False
    ):
        raise DecisionBatchError("fixed decision rule changed")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("same-bar fill", "post-2023", "CY-011", "untouched OOS", "rescuing"):
        if phrase not in prohibited:
            raise DecisionBatchError(f"missing prohibition: {phrase}")
    return spec


def _load_minute_state(spec: dict[str, Any]) -> dict[date, float]:
    frame = pd.read_csv(
        _resolve(spec["inputs"]["minute_state_panel"]["path"]),
        usecols=["trade_date", "market_view", "denominator", "available_at", "hard_valid", STATE],
        parse_dates=["trade_date"],
    )
    frame = frame.loc[
        frame.market_view.eq("CHINEXT_BOARD") & frame.denominator.eq("ALL_STATUS")
    ].copy()
    if frame.trade_date.duplicated().any():
        raise DecisionBatchError("duplicate CHINEXT minute-state date")
    if not frame.hard_valid.eq(True).all():
        raise DecisionBatchError("minute state is not hard-valid")
    expected_available = frame.trade_date.dt.strftime("%Y-%m-%dT15:30:00")
    if not frame.available_at.eq(expected_available).all():
        raise DecisionBatchError("minute state is not available exactly at t 15:30")
    frame = frame.loc[frame.trade_date.dt.date.between(STATE_ACTIVATION, END)].copy()
    values = frame[STATE].to_numpy(float)
    if len(values) == 0 or not np.isfinite(values).all():
        raise DecisionBatchError("missing or nonfinite active minute state")
    calendar = pd.read_parquet(_resolve(spec["inputs"]["calendar"]["path"]))
    column = "trade_date" if "trade_date" in calendar else "cal_date"
    sessions = pd.to_datetime(calendar[column]).dt.date
    expected = set(sessions[(sessions >= STATE_ACTIVATION) & (sessions <= END)])
    observed = set(frame.trade_date.dt.date)
    if observed != expected:
        raise DecisionBatchError("minute state does not cover every active trading session")
    return dict(zip(frame.trade_date.dt.date, values, strict=True))


def _new_selection_audit() -> dict[str, Any]:
    return {
        "active_sessions": set(),
        "veto_sessions": set(),
        "missing_state_sessions": set(),
        "vetoed_candidate_sessions": set(),
        "vetoed_ranked_candidates": 0,
        "candidate_count": 0,
        "vetoed_candidate_count": 0,
        "candidate_sessions": set(),
    }


@contextmanager
def _selection_veto(_unused: Any, audit: dict[str, Any]) -> Iterator[None]:
    original = shared.engine_module.rank_candidates_for_arm

    def filtered_rank(
        candidate_symbols: list[str], rs: dict[str, Any], day: date, policy: Any
    ) -> list[str]:
        eligible: list[str] = []
        if candidate_symbols:
            audit["candidate_sessions"].add(day)
        for symbol in candidate_symbols:
            row = rs.get(symbol)
            if row is None:
                raise DecisionBatchError(f"candidate lacks PIT RS row: {day} {symbol}")
            r20 = float(row["r20"])
            r120 = float(row["r120"])
            if not math.isfinite(r20) or not math.isfinite(r120):
                raise DecisionBatchError(f"candidate has nonfinite PIT RS row: {day} {symbol}")
            audit["candidate_count"] += 1
            acceleration = Decimal(str(row["r20"])) - Decimal(str(row["r120"]))
            if acceleration >= Decimal(str(RS_ACCEL_THRESHOLD)):
                audit["vetoed_candidate_count"] += 1
                continue
            eligible.append(symbol)
        return original(eligible, rs, day, policy)

    shared.engine_module.rank_candidates_for_arm = filtered_rank
    try:
        yield
    finally:
        shared.engine_module.rank_candidates_for_arm = original


def _new_exposure_audit() -> dict[str, Any]:
    return {
        "active_sessions": set(),
        "veto_sessions": set(),
        "missing_state_sessions": set(),
        "vetoed_candidate_sessions": set(),
        "vetoed_ranked_candidates": 0,
        "current_signal_date": None,
        "current_target": BASE_TARGET,
        "planned_target": BASE_TARGET,
        "high_state_sessions": set(),
        "exposure_transition_sessions": set(),
        "target_order_count": 0,
    }


@contextmanager
def _exposure_budget(state: dict[date, float], audit: dict[str, Any]) -> Iterator[None]:
    original_rank = shared.engine_module.rank_candidates_for_arm
    original_change = shared.engine_module.set_change_required
    original_schedule = shared.engine_module.schedule_target_set

    def state_aware_rank(
        candidate_symbols: list[str], rs: dict[str, Any], day: date, policy: Any
    ) -> list[str]:
        audit["current_signal_date"] = day
        target = BASE_TARGET
        if day >= STATE_ACTIVATION:
            if day not in state:
                raise DecisionBatchError(f"missing required t-15:30 state: {day}")
            audit["active_sessions"].add(day)
            if state[day] >= STATE_THRESHOLD:
                target = HIGH_TARGET
                audit["high_state_sessions"].add(day)
        audit["current_target"] = target
        return original_rank(candidate_symbols, rs, day, policy)

    def exposure_or_set_change(previous: Any, desired: Any) -> bool:
        membership_change = original_change(previous, desired)
        exposure_change = bool(set(desired)) and not math.isclose(
            float(audit["current_target"]), float(audit["planned_target"]), abs_tol=1e-12
        )
        return membership_change or exposure_change

    def schedule_exposure_target(
        *,
        desired: tuple[str, ...],
        previous: tuple[str, ...],
        positions: dict[str, Any],
        pending: dict[str, Any],
        signal_date: date,
        reason: str,
        config: Any,
    ) -> None:
        selected = sorted(set(desired))
        if len(selected) > config.max_holdings:
            raise DecisionBatchError("desired member set exceeds max holdings")
        target_weight = float(audit["current_target"])
        weights = {symbol: target_weight for symbol in selected}
        relevant = set(previous) | set(desired) | set(positions) | set(pending)
        if not math.isclose(target_weight, float(audit["planned_target"]), abs_tol=1e-12):
            audit["exposure_transition_sessions"].add(signal_date)
        for symbol in sorted(relevant):
            target = weights.get(symbol, 0.0)
            if target == 0.0 and symbol not in positions:
                pending.pop(symbol, None)
                continue
            existing = pending.get(symbol)
            if existing is not None and existing.target_weight == target:
                continue
            pending[symbol] = shared.engine_module.PendingOrder(
                symbol, target, signal_date, reason
            )
            audit["target_order_count"] += 1
        audit["planned_target"] = target_weight

    shared.engine_module.rank_candidates_for_arm = state_aware_rank
    shared.engine_module.set_change_required = exposure_or_set_change
    shared.engine_module.schedule_target_set = schedule_exposure_target
    try:
        yield
    finally:
        shared.engine_module.rank_candidates_for_arm = original_rank
        shared.engine_module.set_change_required = original_change
        shared.engine_module.schedule_target_set = original_schedule


@contextmanager
def _configured_shared_runner(output_root: Path, decision_context: Any) -> Iterator[None]:
    original_output_root = shared.OUTPUT_ROOT
    original_veto = shared._admission_veto
    shared.OUTPUT_ROOT = output_root
    shared._admission_veto = decision_context
    try:
        yield
    finally:
        shared.OUTPUT_ROOT = original_output_root
        shared._admission_veto = original_veto


def _run_arm(
    spec: dict[str, Any], arm: str, state: dict[date, float] | None
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    output_root = OUTPUT_ROOT / arm
    if arm == SELECTION_ARM:
        context = _selection_veto
        dev_state: Any = None
        consumed_state: Any = None
    elif arm == EXPOSURE_ARM:
        context = _exposure_budget
        if state is None:
            raise DecisionBatchError("exposure arm lacks required state")
        dev_state = state
        consumed_state = state
    else:
        raise DecisionBatchError(f"unknown arm: {arm}")
    if arm == SELECTION_ARM:
        original_audit = shared._new_audit
        shared._new_audit = _new_selection_audit
    else:
        original_audit = shared._new_audit
        shared._new_audit = _new_exposure_audit
    try:
        with _configured_shared_runner(output_root, context):
            development_engine, development_audit = shared._run_development(dev_state)
            consumed_engine, consumed_audit = shared._run_consumed_block(spec, consumed_state)
    finally:
        shared._new_audit = original_audit
    return development_engine, development_audit, consumed_engine, consumed_audit


def _baseline_metrics(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    baselines = shared._baseline_metrics(spec)
    mapping = {
        "development_2018_2021": "development_execution_ledger",
        "consumed_2022_2023": "holdout_execution_ledger",
    }
    for block, input_name in mapping.items():
        executions = shared.read_jsonl(_resolve(spec["inputs"][input_name]["path"]))
        trips = shared.reconstruct_round_trips(executions)
        returns = np.asarray([float(row["round_trip_return"]) for row in trips])
        if len(returns) == 0 or not np.isfinite(returns).all():
            raise DecisionBatchError(f"invalid baseline trips: {block}")
        baselines[block]["severe_loss_rate"] = float(np.mean(returns <= -0.10))
    return baselines


def _serialize_audit(arm: str, audit: dict[str, Any]) -> dict[str, Any]:
    common = {"input_manifest_sha256": audit.get("input_manifest_sha256")}
    if arm == SELECTION_ARM:
        common.update(
            {
                "candidate_session_count": len(audit["candidate_sessions"]),
                "candidate_count": int(audit["candidate_count"]),
                "vetoed_candidate_count": int(audit["vetoed_candidate_count"]),
            }
        )
    else:
        common.update(
            {
                "active_session_count": len(audit["active_sessions"]),
                "high_state_session_count": len(audit["high_state_sessions"]),
                "exposure_transition_session_count": len(audit["exposure_transition_sessions"]),
                "target_order_count": int(audit["target_order_count"]),
            }
        )
    return common


def _delta(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    fields = [
        "total_return",
        "annualized_return",
        "max_drawdown",
        "sharpe_rf0",
        "trade_count",
        "win_rate",
        "mean_trade_return",
        "median_trade_return",
        "severe_loss_rate",
        "average_invested_fraction",
        "turnover",
        "top20_positive_pnl_concentration",
    ]
    return {
        field: None
        if candidate.get(field) is None or baseline.get(field) is None
        else candidate[field] - baseline[field]
        for field in fields
    }


def _analyze_arm(
    spec: dict[str, Any],
    arm: str,
    baselines: dict[str, dict[str, Any]],
    development_engine: dict[str, Any],
    development_audit: dict[str, Any],
    consumed_engine: dict[str, Any],
    consumed_audit: dict[str, Any],
) -> dict[str, Any]:
    candidates = {
        "development_2018_2021": shared._candidate_metrics(development_engine),
        "consumed_2022_2023": shared._candidate_metrics(consumed_engine),
    }
    comparisons = {
        block: {
            "baseline": baselines[block],
            "candidate": candidate,
            "candidate_minus_baseline": _delta(candidate, baselines[block]),
        }
        for block, candidate in candidates.items()
    }
    checks = {
        "total_return_improves_both_blocks": all(
            row["candidate"]["total_return"] > row["baseline"]["total_return"]
            for row in comparisons.values()
        ),
        "max_drawdown_no_worse_both_blocks": all(
            row["candidate"]["max_drawdown"] >= row["baseline"]["max_drawdown"]
            for row in comparisons.values()
        ),
        "sharpe_improves_both_blocks": all(
            row["candidate"]["sharpe_rf0"] > row["baseline"]["sharpe_rf0"]
            for row in comparisons.values()
        ),
        "severe_loss_no_higher_both_blocks": all(
            row["candidate"]["severe_loss_rate"] <= row["baseline"]["severe_loss_rate"]
            for row in comparisons.values()
        ),
        "at_least_60pct_baseline_cycles_both_blocks": all(
            row["candidate"]["trade_count"] >= 0.60 * row["baseline"]["trade_count"]
            for row in comparisons.values()
        ),
        "zero_same_day_fills": all(
            row["candidate"]["same_day_fills"] == 0 for row in comparisons.values()
        ),
    }
    passes = all(checks.values())
    prefix = "STRATEGY_CANDIDATE" if passes else "PARKED_OR_REJECTED"
    return {
        "arm": arm,
        "role": spec["arms"][arm]["role"],
        "classification": f"{prefix}_{arm}",
        "passes_promotion_rule": passes,
        "comparisons": comparisons,
        "checks": checks,
        "audit": {
            "development_2018_2021": _serialize_audit(arm, development_audit),
            "consumed_2022_2023": _serialize_audit(arm, consumed_audit),
        },
    }


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# HAB-CHX-DECISION-BATCH-001 — fixed selection and risk-budget replays",
        "",
        "Two predeclared decision translations were replayed through the unchanged "
        "CHINEXT V1 execution engine. Both blocks are consumed exploration.",
        "",
        "| Arm | Block | Baseline return | Candidate return | Delta | Baseline DD | "
        "Candidate DD | Sharpe delta | Cycles |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm, arm_result in result["arms"].items():
        for block, row in arm_result["comparisons"].items():
            baseline = row["baseline"]
            candidate = row["candidate"]
            delta = row["candidate_minus_baseline"]
            lines.append(
                f"| {arm} | {block} | {baseline['total_return']:.3%} | "
                f"{candidate['total_return']:.3%} | {delta['total_return']:.3%} | "
                f"{baseline['max_drawdown']:.3%} | "
                f"{candidate['max_drawdown']:.3%} | {delta['sharpe_rf0']:.3f} | "
                f"{candidate['trade_count']} / {baseline['trade_count']} |"
            )
    lines.extend(["", "## Decisions", ""])
    for arm, arm_result in result["arms"].items():
        failed = [name for name, passed in arm_result["checks"].items() if not passed]
        failed_text = ", ".join(failed) if failed else "none"
        lines.append(
            f"- `{arm}`: `{arm_result['classification']}`. Failed gates: "
            f"{failed_text}."
        )
    lines.extend(
        [
            "",
            "The selection arm changes only which new candidates are admitted. The "
            "exposure arm changes only selected-position target weights on broad state "
            "transitions; it keeps the holding set, ranking, exits, T+1, limits, costs, "
            "and corporate-action handling intact.",
            "",
            "No post-2023 row or CY-011 input was read by this experiment. Because "
            "unrelated post-2023 summary metadata was accidentally exposed during "
            "repository inventory, future confirmation must use a separately "
            "quarantined block.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    spec = _load_spec()
    state = _load_minute_state(spec)
    if OUTPUT_ROOT.exists() or RESULT_PATH.exists() or REPORT_PATH.exists():
        raise DecisionBatchError("decision-batch output already exists")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=False)
    baselines = _baseline_metrics(spec)
    try:
        arms: dict[str, Any] = {}
        for arm in (SELECTION_ARM, EXPOSURE_ARM):
            engine_dev, audit_dev, engine_later, audit_later = _run_arm(spec, arm, state)
            arms[arm] = _analyze_arm(
                spec, arm, baselines, engine_dev, audit_dev, engine_later, audit_later
            )
        result = {
            "experiment_id": spec["experiment_id"],
            "research_level": spec["research_level"],
            "status": "COMPLETE_TWO_ARM_REPLAY",
            "honesty_boundary": spec["honesty_boundary"],
            "boundary_incident": spec["boundary_incident"],
            "arms": arms,
            "claim_boundary": {
                "untouched_validation": False,
                "post_2023_rows_read_by_experiment": False,
                "post_2023_external_boundary_contaminated": True,
                "cy011_read": False,
                "same_bar_fill_assumed": False,
                "threshold_or_exposure_optimized": False,
                "existing_engine_changed_on_disk": False,
            },
            "hashes": {
                "spec_sha256": EXPECTED_SPEC_SHA256,
                "inputs": {name: binding["sha256"] for name, binding in spec["inputs"].items()},
            },
        }
        shared._atomic_write(REPORT_PATH, _render(result))
        result["hashes"]["report_sha256"] = shared.sha256_file(REPORT_PATH)
        for arm in (SELECTION_ARM, EXPOSURE_ARM):
            result["hashes"][arm] = {}
            for block in ("development_2018_2021", "consumed_2022_2023"):
                directory = OUTPUT_ROOT / arm / block
                result["hashes"][arm][block] = {
                    name: shared.sha256_file(directory / name)
                    for name in (
                        "engine_summary.json",
                        "event_ledger.jsonl",
                        "execution_ledger.jsonl",
                        "daily_nav.jsonl",
                    )
                }
        shared._atomic_write(
            RESULT_PATH,
            json.dumps(shared._clean(result), indent=2, sort_keys=True, allow_nan=False) + "\n",
        )
        print(json.dumps(shared._clean(result), indent=2, sort_keys=True, allow_nan=False))
    except Exception:
        if OUTPUT_ROOT.exists():
            shutil.rmtree(OUTPUT_ROOT)
        if REPORT_PATH.exists():
            REPORT_PATH.unlink()
        raise


if __name__ == "__main__":
    main()
