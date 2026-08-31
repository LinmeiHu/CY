#!/usr/bin/env python3
"""Run the fixed 15:30 minute-volatility-path admission-veto translation."""

from __future__ import annotations

import json
import math
import os
import shutil
import sys
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_hab_chx_downrev_strat_001 as shared

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/HAB-CHX-MINVOLPATH-STRAT-001_spec.json"
RESULT_PATH = PROGRAM / "artifacts/HAB-CHX-MINVOLPATH-STRAT-001_result.json"
REPORT_PATH = PROGRAM / "reports/HAB-CHX-MINVOLPATH-STRAT-001_strategy_translation.md"
OUTPUT_ROOT = PROGRAM / "artifacts/HAB-CHX-MINVOLPATH-STRAT-001"
EXPECTED_SPEC_SHA256 = "7d39ed3c2e1d84a5720fd474fdaaa4a3208c5ad5098f8ff538039572466c648f"

STATE = "minute_realized_volatility__ordinal_progression__pit_3y_pct"
ACTIVATION = date(2020, 2, 7)
END = date(2023, 12, 29)
THRESHOLD = 0.80


class MinutePathStrategyError(RuntimeError):
    """Fail-closed strategy-translation error."""


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_spec() -> dict[str, Any]:
    if shared.sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise MinutePathStrategyError("strategy-translation spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec.get("research_level") != "EXPLORE_STRATEGY_TRANSLATION"
        or spec.get("status") != "POST_DISCOVERY_FIXED_SIMPLE_RULE"
        or "inspected before" not in spec.get("honesty_boundary", "")
    ):
        raise MinutePathStrategyError("strategy exploration honesty boundary changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or shared.sha256_file(path) != binding["sha256"]:
            raise MinutePathStrategyError(f"bound input identity mismatch: {name}")
    rule = spec["state_rule"]
    if (
        rule["coordinate"] != STATE
        or rule["activation_date"] != ACTIVATION.isoformat()
        or rule["block_new_admissions_when"] != "coordinate >= 0.80"
        or rule["market_gate_decision_timestamp"] != "15:30 Asia/Shanghai"
        or rule["threshold_search"] is not False
    ):
        raise MinutePathStrategyError("simple 15:30 rule changed")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("same-bar fill", "post-2023", "CY-011", "untouched OOS"):
        if phrase not in prohibited:
            raise MinutePathStrategyError(f"missing prohibition: {phrase}")
    return spec


def _load_state(spec: dict[str, Any]) -> dict[date, float]:
    frame = pd.read_csv(
        _resolve(spec["inputs"]["state_panel"]["path"]),
        usecols=[
            "trade_date",
            "market_view",
            "denominator",
            "available_at",
            "hard_valid",
            STATE,
        ],
        parse_dates=["trade_date"],
    )
    frame = frame.loc[
        frame.market_view.eq("CHINEXT_BOARD")
        & frame.denominator.eq("ALL_STATUS")
    ].copy()
    if frame.trade_date.duplicated().any():
        raise MinutePathStrategyError("duplicate CHINEXT state date")
    if not frame.hard_valid.eq(True).all():  # noqa: E712
        raise MinutePathStrategyError("active market state is not hard-valid")
    expected_available = frame.trade_date.dt.strftime("%Y-%m-%dT15:30:00")
    if not frame.available_at.eq(expected_available).all():
        raise MinutePathStrategyError("state is not available exactly at t 15:30")
    frame = frame.loc[frame.trade_date.dt.date.between(ACTIVATION, END)].copy()
    values = frame[STATE].to_numpy(float)
    if len(values) == 0 or not np.isfinite(values).all():
        raise MinutePathStrategyError("missing or nonfinite active state")
    calendar = pd.read_parquet(_resolve(spec["inputs"]["calendar"]["path"]))
    column = "trade_date" if "trade_date" in calendar else "cal_date"
    sessions = pd.to_datetime(calendar[column]).dt.date
    expected = set(sessions[(sessions >= ACTIVATION) & (sessions <= END)])
    observed = set(frame.trade_date.dt.date)
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        raise MinutePathStrategyError(
            f"active state/session mismatch: missing={missing[:3]}, extra={extra[:3]}"
        )
    return dict(zip(frame.trade_date.dt.date, values, strict=True))


@contextmanager
def _admission_veto(
    state: dict[date, float], audit: dict[str, Any]
) -> Iterator[None]:
    original = shared.engine_module.rank_candidates_for_arm

    def gated_rank(
        candidate_symbols: list[str],
        rs: dict[str, Any],
        day: date,
        policy: Any,
    ) -> list[str]:
        ranked = original(candidate_symbols, rs, day, policy)
        if day < ACTIVATION:
            return ranked
        if day not in state:
            raise MinutePathStrategyError(f"missing required t-15:30 state: {day}")
        audit["active_sessions"].add(day)
        if state[day] >= THRESHOLD:
            audit["veto_sessions"].add(day)
            audit["vetoed_ranked_candidates"] += len(ranked)
            if ranked:
                audit["vetoed_candidate_sessions"].add(day)
            return []
        return ranked

    shared.engine_module.rank_candidates_for_arm = gated_rank
    try:
        yield
    finally:
        shared.engine_module.rank_candidates_for_arm = original


@contextmanager
def _configured_shared_runner() -> Iterator[None]:
    original_output_root = shared.OUTPUT_ROOT
    original_veto = shared._admission_veto
    shared.OUTPUT_ROOT = OUTPUT_ROOT
    shared._admission_veto = _admission_veto
    try:
        yield
    finally:
        shared.OUTPUT_ROOT = original_output_root
        shared._admission_veto = original_veto


def _baseline_severe_loss_rates(spec: dict[str, Any]) -> dict[str, float]:
    mapping = {
        "development_2018_2021": "development_execution_ledger",
        "consumed_2022_2023": "holdout_execution_ledger",
    }
    rates: dict[str, float] = {}
    for block, input_name in mapping.items():
        executions = shared.read_jsonl(_resolve(spec["inputs"][input_name]["path"]))
        trips = shared.reconstruct_round_trips(executions)
        returns = np.asarray([float(row["round_trip_return"]) for row in trips])
        if len(returns) == 0 or not np.isfinite(returns).all():
            raise MinutePathStrategyError(f"invalid baseline trips: {block}")
        rates[block] = float(np.mean(returns <= -0.10))
    return rates


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
        "top20_positive_pnl_concentration",
    ]
    return {
        field: (
            None
            if candidate.get(field) is None or baseline.get(field) is None
            else candidate[field] - baseline[field]
        )
        for field in fields
    }


def _analyze(
    spec: dict[str, Any],
    development_engine: dict[str, Any],
    development_audit: dict[str, Any],
    consumed_engine: dict[str, Any],
    consumed_audit: dict[str, Any],
) -> dict[str, Any]:
    baselines = shared._baseline_metrics(spec)
    severe = _baseline_severe_loss_rates(spec)
    for block, rate in severe.items():
        baselines[block]["severe_loss_rate"] = rate
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
            value["candidate"]["total_return"] > value["baseline"]["total_return"]
            for value in comparisons.values()
        ),
        "severe_loss_incidence_lower_both_blocks": all(
            value["candidate"]["severe_loss_rate"]
            < value["baseline"]["severe_loss_rate"]
            for value in comparisons.values()
        ),
        "at_least_60pct_baseline_trades_both_blocks": all(
            value["candidate"]["trade_count"]
            >= 0.60 * value["baseline"]["trade_count"]
            for value in comparisons.values()
        ),
        "zero_same_day_fills": all(
            value["candidate"]["same_day_fills"] == 0
            for value in comparisons.values()
        ),
    }
    promising = all(checks.values())
    combined_baseline = math.prod(
        1 + baselines[block]["total_return"] for block in baselines
    ) - 1
    combined_candidate = math.prod(
        1 + candidates[block]["total_return"] for block in candidates
    ) - 1
    return {
        "experiment_id": spec["experiment_id"],
        "research_level": spec["research_level"],
        "status": "COMPLETE_SIMPLE_EXECUTABLE_STRATEGY_TRANSLATION",
        "classification": (
            "STRATEGY_CANDIDATE_MINUTE_VOLATILITY_PATH_ADMISSION_VETO"
            if promising
            else "PARKED_OR_REJECTED_MINUTE_VOLATILITY_PATH_ADMISSION_VETO"
        ),
        "honesty_boundary": spec["honesty_boundary"],
        "rule": spec["state_rule"],
        "comparisons": comparisons,
        "combined_compounded_return": {
            "baseline": combined_baseline,
            "candidate": combined_candidate,
            "candidate_minus_baseline": combined_candidate - combined_baseline,
        },
        "gate_audit": {
            "development_2018_2021": shared._serialize_gate_audit(development_audit),
            "consumed_2022_2023": shared._serialize_gate_audit(consumed_audit),
        },
        "checks": checks,
        "strategy_candidate": promising,
        "claim_boundary": {
            "untouched_validation": False,
            "threshold_optimized": False,
            "post_2023_read": False,
            "cy011_read": False,
            "same_bar_fill_assumed": False,
            "state_used_before_available_at": False,
            "existing_execution_engine_changed_on_disk": False,
        },
        "hashes": {
            "spec_sha256": EXPECTED_SPEC_SHA256,
            "inputs": {name: value["sha256"] for name, value in spec["inputs"].items()},
        },
    }


def _render_report(result: dict[str, Any]) -> str:
    lines = [
        "# HAB-CHX-MINVOLPATH-STRAT-001 — 15:30 minute-path strategy translation",
        "",
        f"`{result['classification']}`.",
        "",
        "| Block | Baseline return | Candidate return | Delta | Baseline DD | Candidate DD | Trades |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for block, value in result["comparisons"].items():
        baseline = value["baseline"]
        candidate = value["candidate"]
        delta = value["candidate_minus_baseline"]
        lines.append(
            f"| {block} | {baseline['total_return']:.4%} | {candidate['total_return']:.4%} | "
            f"{delta['total_return']:.4%} | {baseline['max_drawdown']:.4%} | "
            f"{candidate['max_drawdown']:.4%} | {candidate['trade_count']} / "
            f"{baseline['trade_count']} |"
        )
    combined = result["combined_compounded_return"]
    lines.extend(
        [
            "",
            f"Compounded block return is {combined['candidate']:.4%} versus "
            f"{combined['baseline']:.4%}, a {combined['candidate_minus_baseline']:.4%} difference.",
            "",
            "The market gate becomes available at t 15:30, after the stock signal at t 15:00. "
            "It suppresses only new admissions at the existing next-session open; existing "
            "positions, exits, allowed-date ranking, T+1 execution, limits, costs, and "
            "corporate-action handling remain unchanged.",
            "",
            "Both periods are consumed development history for this newly translated rule. "
            "No post-2023 or CY-011 data was read.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    spec = _load_spec()
    state = _load_state(spec)
    if OUTPUT_ROOT.exists() or RESULT_PATH.exists() or REPORT_PATH.exists():
        raise MinutePathStrategyError("strategy translation output already exists")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=False)
    try:
        with _configured_shared_runner():
            development_engine, development_audit = shared._run_development(state)
            consumed_engine, consumed_audit = shared._run_consumed_block(spec, state)
        result = _analyze(
            spec,
            development_engine,
            development_audit,
            consumed_engine,
            consumed_audit,
        )
        shared._atomic_write(REPORT_PATH, _render_report(result))
        result["hashes"]["report_sha256"] = shared.sha256_file(REPORT_PATH)
        for block in ("development_2018_2021", "consumed_2022_2023"):
            directory = OUTPUT_ROOT / block
            result["hashes"][block] = {
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
            json.dumps(shared._clean(result), indent=2, sort_keys=True, allow_nan=False)
            + "\n",
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
