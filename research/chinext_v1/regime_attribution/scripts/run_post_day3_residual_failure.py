#!/usr/bin/env python3
"""Falsify whether H-023 precedes additional failure after Day 3."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/regime_attribution"
if str(WORK / "scripts") not in sys.path:
    sys.path.insert(0, str(WORK / "scripts"))

import run_day5_market_stock_decomposition as d5d  # noqa: E402
import run_early_severe_loss_formation as slf  # noqa: E402
import run_winner_loser_trajectory_archaeology as wla  # noqa: E402

SPEC = WORK / "experiments/EXP-SLP-001_spec.json"
PATHS = WORK / "artifacts/early_severe_loss_formation.csv"
ACCEPTED_RESULT = WORK / "artifacts/early_severe_loss_formation.json"
ACCEPTED_DAY5_PERSISTENCE = WORK / "artifacts/post_landmark_persistence.json"
OUTPUT_TABLE = WORK / "artifacts/post_day3_residual_failure.csv"
OUTPUT_JSON = WORK / "artifacts/post_day3_residual_failure.json"
REPORT = WORK / "reports/post_day3_residual_failure.md"
EVIDENCE_PACKET = WORK / "reports/post_day3_residual_failure_evidence_packet.md"

BASE_CONTROLS = d5d.BASE_CONTROLS


class ResidualFailureError(RuntimeError):
    """Raised when a frozen identity, sample, or residual invariant fails."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def validate_spec() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-SLP-001":
        raise ResidualFailureError("unexpected residual-failure identity")
    if spec.get("status") != "FROZEN_BEFORE_FIRST_RESIDUAL_FAILURE_TEST":
        raise ResidualFailureError("experiment is not frozen before results")
    identities: dict[str, str] = {}
    mismatches: dict[str, dict[str, str]] = {}
    for name, binding in spec["input_bindings"].items():
        path = resolve_path(binding["path"])
        actual = sha256_file(path) if path.is_file() else "MISSING"
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatches[name] = {"expected": binding["sha256"], "actual": actual}
    if mismatches:
        raise ResidualFailureError(f"frozen input mismatch: {mismatches}")
    return spec, identities


def multiplicative_residual(terminal: pd.Series, landmark: pd.Series) -> pd.Series:
    if (terminal <= -1).any() or (landmark <= -1).any():
        raise ResidualFailureError("return is invalid for multiplicative residual")
    return (1.0 + terminal) / (1.0 + landmark) - 1.0


def load_frame(spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame = pd.read_csv(PATHS)
    if len(frame) != 399 or frame.trade_id.nunique() != 399:
        raise ResidualFailureError("accepted H-023 table changed")
    for column in ("severe_loss", "false_breakout", "extreme_loss20"):
        frame[column] = frame[column].astype(bool)
    frame["residual_return_after_2d"] = multiplicative_residual(
        frame.round_trip_return, frame.return_2d
    )
    frame["future_failure_after_2d"] = -frame.residual_return_after_2d
    frame["residual_return_after_3d"] = multiplicative_residual(
        frame.round_trip_return, frame.return_3d
    )
    frame["future_failure_after_3d"] = -frame.residual_return_after_3d
    frame["residual_return_after_5d"] = multiplicative_residual(
        frame.round_trip_return, frame.return_5d_rebuilt
    )
    frame["future_failure_after_5d"] = -frame.residual_return_after_5d
    sample = spec["sample"]
    audit = {
        "cycles": int(len(frame)),
        "day2_residuals": int(frame.future_failure_after_2d.notna().sum()),
        "day3_residuals": int(frame.future_failure_after_3d.notna().sum()),
        "day5_residuals": int(frame.future_failure_after_5d.notna().sum()),
        "day3_fixed_control_complete": int(
            frame.loc[
                frame.future_failure_after_3d.notna(), list(BASE_CONTROLS)
            ].notna().all(axis=1).sum()
        ),
        "day3_severe_losses": int(
            frame.loc[frame.future_failure_after_3d.notna(), "severe_loss"].sum()
        ),
    }
    expected = {key: sample[key] for key in audit}
    if audit != expected:
        raise ResidualFailureError(f"residual sample changed: {audit}")
    if frame.loc[frame.return_3d.notna(), "adverse_stock_specific_3d"].isna().any():
        raise ResidualFailureError("frozen H-023 primary feature is incomplete")
    audit.update(
        {
            "available_at_timestamp": "DAY3_SESSION_15:30_ASIA_SHANGHAI",
            "potential_action_timestamp": "NEXT_VALID_SESSION_OR_LATER_ONLY; EXPLANATORY_TEST_AUTHORIZES_NO_ACTION",
            "post_exit_prices_read": 0,
            "counterfactual_returns": 0,
            "strategy_replays": 0,
            "thresholds_or_rules_tested": 0,
        }
    )
    return frame, audit


def analyze(frame: pd.DataFrame) -> dict[str, Any]:
    feature = "adverse_stock_specific_3d"
    endpoint = "future_failure_after_3d"
    day3 = frame[frame[endpoint].notna()].copy()
    raw = wla.rank_association(day3, feature, endpoint)
    controlled = d5d.controlled_loyo(
        day3, feature, endpoint, extra_controls=("market_day3_log_return",)
    )
    beta = wla.rank_association(day3, "adverse_beta_adjusted_3d", endpoint)
    day2 = wla.rank_association(
        frame, "adverse_stock_specific_2d", "future_failure_after_2d"
    )
    day5 = wla.rank_association(
        frame[frame.future_failure_after_5d.notna()],
        "adverse_stock_specific_5d",
        "future_failure_after_5d",
    )
    duration_exit = d5d.partial_rank(
        day3,
        feature,
        endpoint,
        extra_controls=("market_day3_log_return", "holding_trading_days"),
        category_controls=("entry_year", "canonical_exit_reason"),
    )
    bottom4 = slf.bottom_flag(day3, 4)
    ex_bottom4 = wla.rank_association(day3.loc[~bottom4], feature, endpoint)
    ex_severe = wla.rank_association(day3.loc[~day3.severe_loss], feature, endpoint)
    security = wla.omit_group_sensitivity(day3, feature, endpoint, "symbol")
    industry = wla.omit_group_sensitivity(
        day3[day3.entry_industry.notna()], feature, endpoint, "entry_industry"
    )
    blocks = {
        str(name): wla.safe_spearman(rows[feature], rows[endpoint])
        for name, rows in day3.groupby("baseline_block", sort=True)
    }
    block_rhos = [packet["rho"] for packet in blocks.values() if packet["rho"] is not None]
    raw_gate = bool(
        raw["rho"] is not None
        and raw["rho"] >= 0.10
        and raw["within_year_rank_rho"] is not None
        and raw["within_year_rank_rho"] > 0
        and raw["loyo_positive_count"] >= 7
    )
    controlled_gate = bool(
        controlled["partial_rank_rho"] is not None
        and controlled["partial_rank_rho"] >= 0.10
        and controlled["loyo_positive_count"] >= 7
    )
    neighbor_gate = bool(
        beta["rho"] is not None
        and beta["rho"] > 0
        and beta["loyo_positive_count"] >= 6
        and day2["rho"] is not None
        and day2["rho"] > 0
        and day2["loyo_positive_count"] >= 6
        and day5["rho"] is not None
        and day5["rho"] > 0
        and day5["loyo_positive_count"] >= 6
    )
    temporal_gate = bool(
        len(block_rhos) == 3
        and sum(value > 0 for value in block_rhos) >= 2
        and min(block_rhos) >= 0
    )
    falsification_gate = bool(
        duration_exit["partial_rank_rho"] is not None
        and duration_exit["partial_rank_rho"] >= 0.08
        and ex_bottom4["rho"] is not None
        and ex_bottom4["rho"] > 0
        and ex_severe["rho"] is not None
        and ex_severe["rho"] > 0
        and security["positive_fraction"] is not None
        and security["positive_fraction"] >= 0.80
        and industry["positive_fraction"] is not None
        and industry["positive_fraction"] >= 0.80
    )
    if all((raw_gate, controlled_gate, neighbor_gate, temporal_gate, falsification_gate)):
        decision = "DEEPEN"
        verdict = "DAY3_ADVERSE_STATE_PRECEDES_ADDITIONAL_FAILURE"
    elif raw_gate and controlled_gate:
        decision = "REFINE"
        verdict = "POST_DAY3_FAILURE_SURVIVES_CORE_BUT_NOT_FULL_FALSIFICATION"
    elif raw_gate:
        decision = "PIVOT"
        verdict = "RAW_POST_DAY3_FAILURE_IS_REDUNDANT_OR_UNSTABLE"
    else:
        decision = "REJECT"
        verdict = "NO_STABLE_POST_DAY3_FAILURE_PERSISTENCE"
    return {
        "experiment_id": "EXP-SLP-001",
        "decision": decision,
        "mechanism_verdict": verdict,
        "primary": {
            "raw": raw,
            "controlled": controlled,
            "beta_adjusted_neighbor": beta,
            "day2_neighbor": day2,
            "day5_neighbor": day5,
            "duration_exit_control": duration_exit,
            "ex_bottom4_pnl": ex_bottom4,
            "ex_severe_loss": ex_severe,
            "leave_one_security_out": security,
            "leave_one_industry_out": industry,
            "blocks": blocks,
            "raw_gate": raw_gate,
            "controlled_gate": controlled_gate,
            "neighbor_gate": neighbor_gate,
            "temporal_gate": temporal_gate,
            "falsification_gate": falsification_gate,
        },
        "strategy_modification": "NONE",
        "interpretation_boundary": (
            "residual failure is measured under the actual frozen exit path; "
            "association cannot by itself authorize a stop, hold, or exit rule"
        ),
    }


def fmt(value: Any) -> str:
    number = wla.finite_or_none(value)
    return "NA" if number is None else f"{number:.3f}"


def build_report(result: dict[str, Any], audit: dict[str, Any]) -> str:
    primary = result["primary"]
    return "\n".join(
        [
            "# Post-Day3 residual failure falsification",
            "",
            "EXP-SLP-001 removes Day-3 return multiplicatively before testing whether the frozen H-023 adverse state precedes additional failure. It is not a stop or exit experiment.",
            "",
            "## Frozen tests",
            "",
            f"- Day-3 residual population/control-complete: `{audit['day3_residuals']}` / `{audit['day3_fixed_control_complete']}`.",
            f"- Raw/controlled rho: `{fmt(primary['raw']['rho'])}` / `{fmt(primary['controlled']['partial_rank_rho'])}`.",
            f"- Day2/Day5/beta neighbors: `{fmt(primary['day2_neighbor']['rho'])}` / `{fmt(primary['day5_neighbor']['rho'])}` / `{fmt(primary['beta_adjusted_neighbor']['rho'])}`.",
            f"- Gates raw/control/neighbor/temporal/falsification: `{primary['raw_gate']}` / `{primary['controlled_gate']}` / `{primary['neighbor_gate']}` / `{primary['temporal_gate']}` / `{primary['falsification_gate']}`.",
            "",
            "## Decision",
            "",
            f"`{result['decision']}` / `{result['mechanism_verdict']}`.",
            "",
            "No stop, exit, hold, threshold, replay, or strategy modification was tested or authorized.",
            "",
        ]
    )


def main() -> int:
    spec, identities = validate_spec()
    accepted = json.loads(ACCEPTED_RESULT.read_text(encoding="utf-8"))
    if accepted.get("experiment_id") != "EXP-SLF-001" or accepted.get("decision") != "DEEPEN":
        raise ResidualFailureError("accepted H-023 result changed")
    day5_persistence = json.loads(
        ACCEPTED_DAY5_PERSISTENCE.read_text(encoding="utf-8")
    )
    if (
        day5_persistence.get("experiment_id") != "EXP-PLP-001"
        or day5_persistence.get("decision") != "REJECT"
    ):
        raise ResidualFailureError("accepted H-014 Day-5 non-persistence result changed")
    frame, audit = load_frame(spec)
    result = analyze(frame)
    result.update(
        {
            "spec_sha256": sha256_file(SPEC),
            "input_identities": identities,
            "audit": audit,
            "evidence_grade": "EXPLORATORY_HOLDING_PATH_FALSIFICATION",
        }
    )
    columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_year",
        "entry_industry",
        "return_2d",
        "return_3d",
        "return_5d_rebuilt",
        "residual_return_after_2d",
        "residual_return_after_3d",
        "residual_return_after_5d",
        "future_failure_after_2d",
        "future_failure_after_3d",
        "future_failure_after_5d",
        "adverse_stock_specific_2d",
        "adverse_stock_specific_3d",
        "adverse_stock_specific_5d",
        "adverse_beta_adjusted_3d",
        "market_day3_log_return",
        "severe_loss",
        "round_trip_return",
        "realized_pnl",
        "holding_trading_days",
        "canonical_exit_reason",
        *BASE_CONTROLS,
    ]
    atomic_write(
        OUTPUT_TABLE,
        frame[columns].sort_values("trade_id").to_csv(
            index=False, lineterminator="\n", float_format="%.17g"
        ),
    )
    atomic_write(
        OUTPUT_JSON, json.dumps(wla.clean_json(result), indent=2, sort_keys=True) + "\n"
    )
    report = build_report(result, audit)
    atomic_write(REPORT, report)
    atomic_write(
        EVIDENCE_PACKET,
        report.replace("# Post-Day3", "# EXP-SLP-001 structured evidence — Post-Day3"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
