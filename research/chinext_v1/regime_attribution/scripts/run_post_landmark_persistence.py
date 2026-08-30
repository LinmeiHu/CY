#!/usr/bin/env python3
"""Execute the preregistered post-landmark residual-return falsification."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/regime_attribution"
if str(WORK / "scripts") not in sys.path:
    sys.path.insert(0, str(WORK / "scripts"))

import run_post_entry_landmark_emergence as landmark  # noqa: E402
import run_winner_loser_trajectory_archaeology as wla  # noqa: E402

SPEC = WORK / "experiments/EXP-PLP-001_spec.json"
LANDMARK_TABLE = WORK / "artifacts/post_entry_landmark_attribution.csv"
LANDMARK_RESULT = WORK / "artifacts/post_entry_landmark_emergence.json"
TRANSITIONS = WORK / "artifacts/pre_entry_transitions.csv"
OUTPUT_TABLE = WORK / "artifacts/post_landmark_persistence.csv"
OUTPUT_JSON = WORK / "artifacts/post_landmark_persistence.json"
REPORT = WORK / "reports/post_landmark_persistence.md"

LANDMARKS = (5, 10, 20)
PRIMARY_LANDMARK = 5


class PersistenceError(RuntimeError):
    """Raised when a frozen identity, sample, or arithmetic invariant fails."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def residual_return(terminal: pd.Series, landmark_return: pd.Series) -> pd.Series:
    """Return earned after a landmark under multiplicative return arithmetic."""
    denominator = 1.0 + landmark_return.astype(float)
    if ((denominator <= 0) & landmark_return.notna()).any():
        raise PersistenceError("landmark return has non-positive wealth denominator")
    return (1.0 + terminal.astype(float)) / denominator - 1.0


def validate_spec() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-PLP-001":
        raise PersistenceError("unexpected experiment identity")
    if spec.get("status") != "FROZEN_BEFORE_FIRST_RESIDUAL_RETURN_TEST":
        raise PersistenceError("experiment is not frozen before results")
    identities: dict[str, str] = {}
    mismatch: dict[str, Any] = {}
    for name, binding in spec["input_bindings"].items():
        path = resolve_path(binding["path"])
        if not path.is_file():
            raise PersistenceError(f"missing bound input: {name}: {path}")
        actual = sha256_file(path)
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatch[name] = {"expected": binding["sha256"], "actual": actual}
    if mismatch:
        raise PersistenceError(f"frozen input mismatch: {mismatch}")
    return spec, identities


def load_frame(spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    upstream = json.loads(LANDMARK_RESULT.read_text(encoding="utf-8"))
    if (
        upstream.get("experiment_id") != "EXP-PEL-001"
        or upstream.get("decision") != "DEEPEN"
        or upstream.get("strategy_modification") != "NONE"
    ):
        raise PersistenceError("accepted landmark result identity/status changed")
    path = pd.read_csv(LANDMARK_TABLE)
    if len(path) != 295 or path.trade_id.nunique() != 295:
        raise PersistenceError("accepted landmark table is not 295 unique cycles")
    expected = spec["sample"]["expected_available"]
    actual = {
        "return_5d": int(path.return_5d.notna().sum()),
        "return_10d": int(path.return_10d.notna().sum()),
        "return_20d": int(path.return_20d.notna().sum()),
    }
    if actual != expected:
        raise PersistenceError(f"landmark availability changed: {actual} != {expected}")
    controls = pd.read_csv(TRANSITIONS)
    if len(controls) != 399 or controls.trade_id.nunique() != 399:
        raise PersistenceError("accepted pre-entry controls are not 399 unique cycles")
    control_columns = ["trade_id", *landmark.BASE_CONTROLS]
    frame = path.merge(
        controls[control_columns], on="trade_id", how="left", validate="one_to_one"
    )
    if frame[list(landmark.BASE_CONTROLS)].isna().all(axis=1).any():
        raise PersistenceError("a landmark cycle failed to join pre-entry controls")
    if (frame.round_trip_return <= -1.0).any():
        raise PersistenceError("terminal return has non-positive wealth value")
    maximum_reconstruction_error: dict[str, float] = {}
    for day in LANDMARKS:
        source = f"return_{day}d"
        target = f"residual_return_after_{day}d"
        frame[target] = residual_return(frame.round_trip_return, frame[source])
        subset = frame[source].notna()
        reconstructed = (1.0 + frame.loc[subset, source]) * (
            1.0 + frame.loc[subset, target]
        ) - 1.0
        error = float(
            np.max(np.abs(reconstructed - frame.loc[subset, "round_trip_return"]))
        )
        maximum_reconstruction_error[str(day)] = error
        if error > 1e-12:
            raise PersistenceError(f"multiplicative residual reconstruction failed at {day}")
    audit = {
        "primary_cycles": int(len(frame)),
        "available": actual,
        "maximum_reconstruction_error": maximum_reconstruction_error,
        "post_exit_price_rows_read": 0,
        "strategy_replays": 0,
        "counterfactual_paths": 0,
        "entry_or_exit_rules_tested": 0,
    }
    return frame, audit


def controlled_loyo(
    frame: pd.DataFrame,
    feature: str,
    endpoint: str,
    *,
    duration_exit: bool = False,
) -> dict[str, Any]:
    def estimate(rows: pd.DataFrame) -> dict[str, Any]:
        if duration_exit:
            return landmark.partial_rank(
                rows,
                feature,
                endpoint,
                extra_controls=("holding_trading_days",),
                category_controls=("entry_year", "canonical_exit_reason"),
            )
        return landmark.partial_rank(rows, feature, endpoint)

    full = estimate(frame)
    loyo = {
        str(year): estimate(frame[frame.entry_year != year])
        for year in range(2018, 2026)
    }
    positive = sum(
        item["partial_rank_rho"] is not None and item["partial_rank_rho"] > 0
        for item in loyo.values()
    )
    negative = sum(
        item["partial_rank_rho"] is not None and item["partial_rank_rho"] < 0
        for item in loyo.values()
    )
    return {
        **full,
        "loyo": loyo,
        "loyo_positive_count": int(positive),
        "loyo_negative_count": int(negative),
    }


def analyze(frame: pd.DataFrame) -> dict[str, Any]:
    feature = "return_5d"
    endpoint = "residual_return_after_5d"
    raw = wla.rank_association(frame, feature, endpoint)
    controlled = controlled_loyo(frame, feature, endpoint)
    duration_exit = controlled_loyo(
        frame, feature, endpoint, duration_exit=True
    )
    yearly = {
        str(year): wla.safe_spearman(rows[feature], rows[endpoint])
        for year, rows in frame.groupby("entry_year", sort=True)
    }
    blocks = {
        str(name): wla.safe_spearman(rows[feature], rows[endpoint])
        for name, rows in frame.groupby("baseline_block", sort=True)
    }
    top4 = wla.deterministic_top_flag(frame, 4)
    ex_top4 = wla.rank_association(frame.loc[~top4], feature, endpoint)
    ex_severe_loss = wla.rank_association(
        frame.loc[~frame.severe_loss.astype(bool)], feature, endpoint
    )
    ex_extreme_winner = wla.rank_association(
        frame.loc[~frame.extreme_winner.astype(bool)], feature, endpoint
    )
    security = wla.omit_group_sensitivity(frame, feature, endpoint, "symbol")
    industry = wla.omit_group_sensitivity(
        frame[frame.entry_industry.notna()], feature, endpoint, "entry_industry"
    )
    neighbors: dict[str, Any] = {}
    for day in (10, 20):
        neighbor_feature = f"return_{day}d"
        neighbor_endpoint = f"residual_return_after_{day}d"
        subset = frame[frame[neighbor_feature].notna()].copy()
        neighbors[str(day)] = wla.rank_association(
            subset, neighbor_feature, neighbor_endpoint
        )
    quintile_frame = frame[[feature, endpoint]].dropna().copy()
    quintile_frame["day5_quintile"] = pd.qcut(
        quintile_frame[feature].rank(method="first"), 5, labels=False
    ) + 1
    quintiles = {
        str(int(name)): {
            "n": int(len(rows)),
            "median_day5_return": wla.finite_or_none(rows[feature].median()),
            "median_residual_return": wla.finite_or_none(rows[endpoint].median()),
        }
        for name, rows in quintile_frame.groupby("day5_quintile", sort=True)
    }
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
    mechanical_gate = bool(
        duration_exit["partial_rank_rho"] is not None
        and duration_exit["partial_rank_rho"] >= 0.05
        and duration_exit["loyo_positive_count"] >= 7
        and ex_top4["rho"] is not None
        and ex_top4["rho"] > 0
        and ex_severe_loss["rho"] is not None
        and ex_severe_loss["rho"] > 0
        and security["positive_fraction"] is not None
        and security["positive_fraction"] >= 0.80
        and industry["positive_fraction"] is not None
        and industry["positive_fraction"] >= 0.80
    )
    neighbor_gate = all(
        item["rho"] is not None
        and item["rho"] > 0
        and item["loyo_positive_count"] >= 6
        for item in neighbors.values()
    )
    stable_negative = bool(
        raw["rho"] is not None
        and raw["rho"] <= -0.10
        and raw["loyo_negative_count"] >= 7
    )
    if raw_gate and controlled_gate and mechanical_gate and neighbor_gate:
        decision = "DEEPEN"
        verdict = "POST_LANDMARK_PERSISTENCE_SURVIVES_SHARED_ARITHMETIC_FALSIFICATION"
    elif raw_gate and controlled_gate and mechanical_gate:
        decision = "REFINE"
        verdict = "DAY5_PERSISTENCE_PRESENT_BUT_NOT_LATER_LANDMARK_STABLE"
    elif stable_negative:
        decision = "PIVOT"
        verdict = "EARLY_STRENGTH_ASSOCIATES_WITH_POST_LANDMARK_GIVEBACK"
    else:
        decision = "REJECT"
        verdict = "DAY5_SEPARATION_DOES_NOT_IMPLY_INCREMENTAL_POST_DAY5_PERSISTENCE"
    return {
        "experiment_id": "EXP-PLP-001",
        "decision": decision,
        "mechanism_verdict": verdict,
        "primary": {
            "raw": raw,
            "controlled_preentry": controlled,
            "controlled_duration_exit": duration_exit,
            "yearly": yearly,
            "baseline_block": blocks,
            "ex_global_top1pct_pnl": ex_top4,
            "ex_severe_losers": ex_severe_loss,
            "ex_extreme_winners": ex_extreme_winner,
            "leave_one_security_out": security,
            "leave_one_industry_out": industry,
            "raw_gate": raw_gate,
            "controlled_gate": controlled_gate,
            "mechanical_gate": mechanical_gate,
            "neighbor_gate": neighbor_gate,
        },
        "neighbors": neighbors,
        "day5_quintiles": quintiles,
        "return_identity": "(1 + terminal_return) = (1 + landmark_return) * (1 + residual_return)",
        "interpretation_boundary": "residual return removes direct shared arithmetic but remains conditional on survival and frozen exit-path mechanics",
        "strategy_modification": "NONE",
    }


def fmt(value: Any, digits: int = 3) -> str:
    number = wla.finite_or_none(value)
    return "NA" if number is None else f"{number:.{digits}f}"


def build_report(audit: dict[str, Any], result: dict[str, Any]) -> str:
    p = result["primary"]
    lines = [
        "# Post-landmark persistence falsification",
        "",
        "EXP-PLP-001 removes day-5 return from terminal return multiplicatively, then asks whether early strength is associated with the return earned afterward. It is holding-path attribution, not a sell/hold experiment.",
        "",
        "## Integrity and arithmetic",
        "",
        f"- Primary/later survivor samples: `{audit['available']['return_5d']}` / `{audit['available']['return_10d']}` / `{audit['available']['return_20d']}`.",
        f"- Maximum day-5 reconstruction error: `{audit['maximum_reconstruction_error']['5']:.3e}`.",
        f"- Post-exit price rows/replays/counterfactual paths/rules tested: `{audit['post_exit_price_rows_read']}` / `{audit['strategy_replays']}` / `{audit['counterfactual_paths']}` / `{audit['entry_or_exit_rules_tested']}`.",
        "",
        "## Primary day-5 residual-return test",
        "",
        "| Raw rho | Within-year rho | LOYO + | Pre-entry controlled rho | LOYO + | Duration/exit rho | LOYO + | Ex-top-1% | Ex-severe-loss |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| {fmt(p['raw']['rho'])} | {fmt(p['raw']['within_year_rank_rho'])} | {p['raw']['loyo_positive_count']}/8 | "
        f"{fmt(p['controlled_preentry']['partial_rank_rho'])} | {p['controlled_preentry']['loyo_positive_count']}/8 | "
        f"{fmt(p['controlled_duration_exit']['partial_rank_rho'])} | {p['controlled_duration_exit']['loyo_positive_count']}/8 | "
        f"{fmt(p['ex_global_top1pct_pnl']['rho'])} | {fmt(p['ex_severe_losers']['rho'])} |",
        "",
        "## Fixed later-landmark confirmation",
        "",
        "| Landmark | N | Raw rho | Within-year rho | LOYO + |",
        "|---|---:|---:|---:|---:|",
    ]
    for day, item in result["neighbors"].items():
        lines.append(
            f"| day {day} | {item['n']} | {fmt(item['rho'])} | "
            f"{fmt(item['within_year_rank_rho'])} | {item['loyo_positive_count']}/8 |"
        )
    lines += [
        "",
        "## Preregistered gates",
        "",
        f"- Raw / pre-entry controlled / mechanical / neighbor: `{'PASS' if p['raw_gate'] else 'FAIL'}` / `{'PASS' if p['controlled_gate'] else 'FAIL'}` / `{'PASS' if p['mechanical_gate'] else 'FAIL'}` / `{'PASS' if p['neighbor_gate'] else 'FAIL'}`.",
        "",
        "## Scientific decision",
        "",
        f"`{result['decision']}` / `{result['mechanism_verdict']}`.",
        "",
        "Residualization removes the direct fact that day-5 return is contained in terminal return. It does not remove survivor conditioning or the strategy's frozen exit mechanics, so even a surviving association is descriptive and cannot authorize a hold rule.",
        "",
        "## Strategy candidate",
        "",
        "None. No entry, hold, exit, ranking, sizing, or production modification was tested or authorized.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    spec, identities = validate_spec()
    frame, audit = load_frame(spec)
    result = analyze(frame)
    result.update(
        {
            "spec_sha256": sha256_file(SPEC),
            "input_identities": identities,
            "audit": audit,
            "evidence_grade": "EXPLORATORY_HOLDING_PATH_FALSIFICATION",
            "breadth_h004_status": "PROSPECTIVE_VALIDATION_PENDING_FROZEN",
        }
    )
    output_columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_year",
        "entry_industry",
        "outcome_class",
        "return_5d",
        "residual_return_after_5d",
        "return_10d",
        "residual_return_after_10d",
        "return_20d",
        "residual_return_after_20d",
        "round_trip_return",
        "realized_pnl",
        "holding_trading_days",
        "canonical_exit_reason",
        "extreme_winner",
        "severe_loss",
    ]
    atomic_write(
        OUTPUT_TABLE,
        frame[output_columns].sort_values("trade_id").to_csv(
            index=False, lineterminator="\n", float_format="%.17g"
        ),
    )
    atomic_write(
        OUTPUT_JSON, json.dumps(wla.clean_json(result), indent=2, sort_keys=True) + "\n"
    )
    atomic_write(REPORT, build_report(audit, result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
