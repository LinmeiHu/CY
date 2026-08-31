#!/usr/bin/env python3
"""Run the fixed simple CHINEXT admission-veto strategy translation."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
CHX = ROOT / "research/chinext_v1"
SCRIPTS = CHX / "scripts"
SRC = ROOT / "src"
for import_root in (str(SCRIPTS), str(SRC)):
    if import_root not in sys.path:
        sys.path.insert(0, import_root)

import run_chinext_v1_extended_replay as development  # noqa: E402
import run_chinext_v1_smoke as engine_module  # noqa: E402
from run_chinext_v1_full_survivor import (  # noqa: E402
    INITIAL_CASH,
    performance_extensions,
    read_jsonl,
)
from run_chinext_v1_pit_replay import reconstruct_round_trips  # noqa: E402

SPEC_PATH = PROGRAM / "experiments/HAB-CHX-DOWNREV-STRAT-001_spec.json"
RESULT_PATH = PROGRAM / "artifacts/HAB-CHX-DOWNREV-STRAT-001_result.json"
REPORT_PATH = PROGRAM / "reports/HAB-CHX-DOWNREV-STRAT-001_strategy_translation.md"
OUTPUT_ROOT = PROGRAM / "artifacts/HAB-CHX-DOWNREV-STRAT-001"
EXPECTED_SPEC_SHA256 = "0a7c3c2ee8908a13fa0b9913a8e7d1be7a8804709f6fdef1c128fdeb3f4a8df6"

STATE = "downside_extreme_participation_70_pit_3y_pct"
ACTIVATION = date(2020, 7, 28)
END = date(2023, 12, 29)
THRESHOLD = 0.20


class StrategyTranslationError(RuntimeError):
    """Fail-closed simple strategy translation error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (date, pd.Timestamp)):
        return value.isoformat()
    if pd.isna(value):
        return None
    return value


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise StrategyTranslationError("strategy-translation spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec.get("research_level") != "EXPLORE_STRATEGY_TRANSLATION"
        or spec.get("status") != "POST_DISCOVERY_FIXED_SIMPLE_RULE"
        or "inspected before" not in spec.get("honesty_boundary", "")
    ):
        raise StrategyTranslationError("strategy exploration honesty boundary changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise StrategyTranslationError(f"bound input identity mismatch: {name}")
    rule = spec["state_rule"]
    if (
        rule["coordinate"] != STATE
        or rule["activation_date"] != ACTIVATION.isoformat()
        or rule["block_new_admissions_when"] != "coordinate <= 0.20"
        or rule["threshold_search"] is not False
    ):
        raise StrategyTranslationError("simple rule changed")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("same-bar fill", "post-2023", "CY-011", "untouched OOS"):
        if phrase not in prohibited:
            raise StrategyTranslationError(f"missing prohibition: {phrase}")
    return spec


def _load_state(spec: dict[str, Any]) -> dict[date, float | None]:
    frame = pd.read_csv(
        _resolve(spec["inputs"]["state_panel"]["path"]),
        usecols=[
            "trade_date",
            "market_view",
            "denominator",
            "decision_at",
            "available_at",
            STATE,
        ],
        parse_dates=["trade_date"],
    )
    frame = frame.loc[
        frame.market_view.eq("CHINEXT_BOARD")
        & frame.denominator.eq("ALL_STATUS")
    ].copy()
    if frame.trade_date.duplicated().any():
        raise StrategyTranslationError("duplicate CHINEXT state date")
    if not frame.available_at.eq(frame.decision_at).all():
        raise StrategyTranslationError("state availability exceeds decision time")
    if not frame.decision_at.str.contains("T15:00:00+08:00", regex=False).all():
        raise StrategyTranslationError("state decision timestamp changed")
    frame = frame.loc[frame.trade_date.dt.date.between(ACTIVATION, END)].copy()
    finite = frame[STATE].dropna().to_numpy(float)
    if not np.isfinite(finite).all():
        raise StrategyTranslationError("nonfinite active state")
    calendar = pd.read_parquet(_resolve(spec["inputs"]["calendar"]["path"]))
    column = "trade_date" if "trade_date" in calendar else "cal_date"
    sessions = pd.to_datetime(calendar[column]).dt.date
    expected = set(sessions[(sessions >= ACTIVATION) & (sessions <= END)])
    observed = set(frame.trade_date.dt.date)
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        raise StrategyTranslationError(
            f"active state/session mismatch: missing={missing[:3]}, extra={extra[:3]}"
        )
    values = [None if pd.isna(value) else float(value) for value in frame[STATE]]
    return dict(zip(frame.trade_date.dt.date, values, strict=True))


@contextmanager
def _admission_veto(
    state: dict[date, float | None], audit: dict[str, Any]
) -> Iterator[None]:
    original = engine_module.rank_candidates_for_arm

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
            raise StrategyTranslationError(f"missing required t-close state: {day}")
        audit["active_sessions"].add(day)
        value = state[day]
        if value is None:
            audit["missing_state_sessions"].add(day)
            audit["veto_sessions"].add(day)
            audit["vetoed_ranked_candidates"] += len(ranked)
            if ranked:
                audit["vetoed_candidate_sessions"].add(day)
            return []
        if value <= THRESHOLD:
            audit["veto_sessions"].add(day)
            audit["vetoed_ranked_candidates"] += len(ranked)
            if ranked:
                audit["vetoed_candidate_sessions"].add(day)
            return []
        return ranked

    engine_module.rank_candidates_for_arm = gated_rank
    try:
        yield
    finally:
        engine_module.rank_candidates_for_arm = original


def _new_audit() -> dict[str, Any]:
    return {
        "active_sessions": set(),
        "veto_sessions": set(),
        "missing_state_sessions": set(),
        "vetoed_candidate_sessions": set(),
        "vetoed_ranked_candidates": 0,
    }


def _run_development(
    state: dict[date, float | None]
) -> tuple[dict[str, Any], dict[str, Any]]:
    output = OUTPUT_ROOT / "development_2018_2021"
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="hab-chx-downrev-dev-") as temporary:
        input_root = Path(temporary)
        prepared = development.materialize_transient_inputs(input_root)
        replay_spec = development.load_replay_spec()
        development.validate_prepared_manifest(prepared, replay_spec)
        args = argparse.Namespace(
            start=development.START,
            end=development.END,
            sample_size=10_000,
            full_survivor=True,
            initial_cash=INITIAL_CASH,
            pit_membership=input_root / "daily_membership.parquet",
            daily_root=input_root,
            market=development.MARKET,
            calendar=development.CALENDAR,
            summary=output / "engine_summary.json",
            report=output / "engine_report.md",
            output_dir=output,
            warmup_start=development.WARMUP_START,
        )
        audit = _new_audit()
        with _admission_veto(state, audit):
            result = engine_module.run(args)
    audit["input_manifest_sha256"] = prepared["canonical_sha256"]
    return result, audit


def _run_consumed_block(
    spec: dict[str, Any], state: dict[date, float | None]
) -> tuple[dict[str, Any], dict[str, Any]]:
    output = OUTPUT_ROOT / "consumed_2022_2023"
    output.mkdir(parents=True, exist_ok=False)
    args = argparse.Namespace(
        start=date(2022, 1, 4),
        end=date(2023, 12, 29),
        warmup_start=date(2021, 7, 8),
        sample_size=10_000,
        full_survivor=True,
        initial_cash=INITIAL_CASH,
        pit_membership=_resolve(spec["inputs"]["holdout_membership"]["path"]),
        daily_root=engine_module.DEFAULT_DAILY_ROOT,
        market=_resolve(spec["inputs"]["market_anchor"]["path"]),
        calendar=_resolve(spec["inputs"]["calendar"]["path"]),
        summary=output / "engine_summary.json",
        report=output / "engine_report.md",
        output_dir=output,
        ablation_arm="O0_BASELINE",
    )
    audit = _new_audit()
    with _admission_veto(state, audit):
        result = engine_module.run(args)
    return result, audit


def _concentration(trips: list[dict[str, Any]]) -> float | None:
    positive = sum(max(0.0, float(row["realized_pnl"])) for row in trips)
    if positive <= 0:
        return None
    ordered = sorted(
        trips,
        key=lambda row: (
            -float(row["realized_pnl"]),
            str(row["symbol"]),
            str(row["exit_execution_date"]),
        ),
    )
    return sum(max(0.0, float(row["realized_pnl"])) for row in ordered[:20]) / positive


def _candidate_metrics(engine: dict[str, Any]) -> dict[str, Any]:
    executions = read_jsonl(Path(engine["audit"]["execution_ledger"]))
    nav = read_jsonl(Path(engine["audit"]["daily_nav"]))
    trips = reconstruct_round_trips(executions)
    returns = np.asarray([float(row["round_trip_return"]) for row in trips], dtype=float)
    extended = performance_extensions(nav)
    portfolio = engine["portfolio"]
    return {
        "total_return": float(portfolio["total_return"]),
        "annualized_return": float(portfolio["annualized_return"]),
        "max_drawdown": float(portfolio["max_drawdown"]),
        "sharpe_rf0": float(extended["sharpe_zero_risk_free"]),
        "trade_count": len(trips),
        "win_rate": float(np.mean(returns > 0)) if len(returns) else None,
        "mean_trade_return": float(np.mean(returns)) if len(returns) else None,
        "median_trade_return": float(np.median(returns)) if len(returns) else None,
        "severe_loss_rate": float(np.mean(returns <= -0.10)) if len(returns) else None,
        "average_invested_fraction": float(portfolio["average_invested_ratio"]),
        "turnover": float(engine["execution"]["turnover"]),
        "top20_positive_pnl_concentration": _concentration(trips),
        "same_day_fills": sum(
            row.get("status") == "FILLED"
            and row.get("signal_date") == row.get("execution_date")
            for row in executions
        ),
        "t1_blocked_exits": int(engine["execution"]["t1_blocked_exit_count"]),
        "failed_open_executions": int(engine["execution"]["failed_open_execution_count"]),
    }


def _baseline_metrics(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    development_baseline = json.loads(
        _resolve(spec["inputs"]["development_baseline"]["path"]).read_text()
    )
    holdout = json.loads(_resolve(spec["inputs"]["holdout_baseline"]["path"]).read_text())[
        "O0_BASELINE"
    ]
    portfolio = development_baseline["portfolio"]
    return {
        "development_2018_2021": {
            "total_return": float(portfolio["total_return"]),
            "annualized_return": float(portfolio["annualized_return"]),
            "max_drawdown": float(portfolio["max_drawdown"]),
            "sharpe_rf0": float(portfolio["sharpe_zero_risk_free"]),
            "trade_count": int(development_baseline["execution"]["completed_round_trip_count"]),
            "win_rate": float(portfolio["win_rate"]),
            "mean_trade_return": float(portfolio["average_trade_return"]),
            "median_trade_return": float(portfolio["median_trade_return"]),
            "severe_loss_rate": None,
            "average_invested_fraction": float(portfolio["average_invested_ratio"]),
            "turnover": float(development_baseline["execution"]["turnover"]),
            "top20_positive_pnl_concentration": float(
                development_baseline["pnl_concentration"][
                    "top20_positive_pnl_concentration"
                ]
            ),
        },
        "consumed_2022_2023": {
            "total_return": float(holdout["total_return"]),
            "annualized_return": float(holdout["annualized_return"]),
            "max_drawdown": float(holdout["max_drawdown"]),
            "sharpe_rf0": float(holdout["sharpe_rf0"]),
            "trade_count": int(holdout["trade_count"]),
            "win_rate": float(holdout["win_rate"]),
            "mean_trade_return": float(holdout["mean_trade_return"]),
            "median_trade_return": float(holdout["median_trade_return"]),
            "severe_loss_rate": None,
            "average_invested_fraction": float(holdout["average_invested_fraction"]),
            "turnover": None,
            "top20_positive_pnl_concentration": float(holdout["top20_concentration"]),
        },
    }


def _serialize_gate_audit(audit: dict[str, Any]) -> dict[str, Any]:
    return {
        "active_session_count": len(audit["active_sessions"]),
        "veto_session_count": len(audit["veto_sessions"]),
        "missing_state_session_count": len(audit["missing_state_sessions"]),
        "vetoed_candidate_session_count": len(audit["vetoed_candidate_sessions"]),
        "vetoed_ranked_candidate_count": int(audit["vetoed_ranked_candidates"]),
        "input_manifest_sha256": audit.get("input_manifest_sha256"),
    }


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
    baselines = _baseline_metrics(spec)
    candidates = {
        "development_2018_2021": _candidate_metrics(development_engine),
        "consumed_2022_2023": _candidate_metrics(consumed_engine),
    }
    comparisons: dict[str, Any] = {}
    for block in candidates:
        comparisons[block] = {
            "baseline": baselines[block],
            "candidate": candidates[block],
            "candidate_minus_baseline": _delta(candidates[block], baselines[block]),
        }
    return_better = all(
        value["candidate"]["total_return"] > value["baseline"]["total_return"]
        for value in comparisons.values()
    )
    trade_retention = all(
        value["candidate"]["trade_count"] >= 0.60 * value["baseline"]["trade_count"]
        for value in comparisons.values()
    )
    severe_loss_lower = all(
        value["candidate"]["severe_loss_rate"]
        < (0.119 if block == "development_2018_2021" else 0.064)
        for block, value in comparisons.items()
    )
    checks = {
        "total_return_improves_both_blocks": return_better,
        "severe_loss_incidence_lower_both_blocks_vs_screen_baseline": severe_loss_lower,
        "at_least_60pct_baseline_trades_both_blocks": trade_retention,
        "zero_same_day_fills": all(
            value["candidate"]["same_day_fills"] == 0 for value in comparisons.values()
        ),
    }
    promising = all(checks.values())
    combined_baseline = (
        (1 + baselines["development_2018_2021"]["total_return"])
        * (1 + baselines["consumed_2022_2023"]["total_return"])
        - 1
    )
    combined_candidate = (
        (1 + candidates["development_2018_2021"]["total_return"])
        * (1 + candidates["consumed_2022_2023"]["total_return"])
        - 1
    )
    return {
        "experiment_id": spec["experiment_id"],
        "research_level": spec["research_level"],
        "status": "COMPLETE_SIMPLE_EXECUTABLE_STRATEGY_TRANSLATION",
        "classification": (
            "STRATEGY_CANDIDATE_DOWNSIDE_PARTICIPATION_ADMISSION_VETO"
            if promising
            else "PARKED_OR_REJECTED_DOWNSIDE_PARTICIPATION_ADMISSION_VETO"
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
            "development_2018_2021": _serialize_gate_audit(development_audit),
            "consumed_2022_2023": _serialize_gate_audit(consumed_audit),
        },
        "checks": checks,
        "strategy_candidate": promising,
        "claim_boundary": {
            "untouched_validation": False,
            "threshold_optimized": False,
            "post_2023_read": False,
            "cy011_read": False,
            "same_bar_fill_assumed": False,
            "existing_execution_engine_changed_on_disk": False,
        },
        "hashes": {
            "spec_sha256": EXPECTED_SPEC_SHA256,
            "inputs": {name: value["sha256"] for name, value in spec["inputs"].items()},
        },
    }


def _render_report(result: dict[str, Any]) -> str:
    lines = [
        "# HAB-CHX-DOWNREV-STRAT-001 — simple executable strategy translation",
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
            "The rule reads only the completed t close and suppresses new admissions; existing "
            "positions, exits, ranking on allowed dates, t+1 execution, limits, costs, T+1, and "
            "corporate-action handling remain unchanged.",
            "",
            "Both periods are consumed development history for this newly discovered rule. No "
            "post-2023 or CY-011 data was read.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    spec = _load_spec()
    state = _load_state(spec)
    if OUTPUT_ROOT.exists() or RESULT_PATH.exists() or REPORT_PATH.exists():
        raise StrategyTranslationError("strategy translation output already exists")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=False)
    try:
        development_engine, development_audit = _run_development(state)
        consumed_engine, consumed_audit = _run_consumed_block(spec, state)
        result = _analyze(
            spec,
            development_engine,
            development_audit,
            consumed_engine,
            consumed_audit,
        )
        _atomic_write(REPORT_PATH, _render_report(result))
        result["hashes"]["report_sha256"] = sha256_file(REPORT_PATH)
        for block in ("development_2018_2021", "consumed_2022_2023"):
            directory = OUTPUT_ROOT / block
            result["hashes"][block] = {
                name: sha256_file(directory / name)
                for name in (
                    "engine_summary.json",
                    "event_ledger.jsonl",
                    "execution_ledger.jsonl",
                    "daily_nav.jsonl",
                )
            }
        _atomic_write(
            RESULT_PATH,
            json.dumps(_clean(result), indent=2, sort_keys=True, allow_nan=False) + "\n",
        )
        print(json.dumps(_clean(result), indent=2, sort_keys=True, allow_nan=False))
    except Exception:
        if OUTPUT_ROOT.exists():
            shutil.rmtree(OUTPUT_ROOT)
        if REPORT_PATH.exists():
            REPORT_PATH.unlink()
        raise


if __name__ == "__main__":
    main()
