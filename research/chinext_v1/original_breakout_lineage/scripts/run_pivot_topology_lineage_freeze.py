#!/usr/bin/env python3
"""Construct EXP-OBL-012 pivot-topology lineages without outcomes."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/original_breakout_lineage"
SCRIPTS = WORK / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_outcome_blind_lineage_freeze as source  # noqa: E402

SPEC = WORK / "experiments/EXP-OBL-012_spec.json"
FEATURES = WORK / "artifacts/pivot_topology_features.csv"
ASSIGNMENTS = WORK / "artifacts/pivot_topology_assignments.csv"
AUDIT = WORK / "artifacts/EXP-OBL-012_audit.json"
FREEZE = WORK / "lineage_freezes/LINEAGE-OBL-012.json"
REPORT = WORK / "reports/EXP-OBL-012_pivot_topology_freeze.md"

FORBIDDEN_COLUMNS = source.FORBIDDEN_COLUMNS | {
    "opportunity20",
    "non_false_breakout",
    "terminal_return",
}
LINEAGES = {
    (False, False): "L00_NONRISING_TROUGH_NONFALLING_PEAK",
    (False, True): "L01_NONRISING_TROUGH_LOWER_HIGH",
    (True, False): "L10_HIGHER_LOW_NONFALLING_PEAK",
    (True, True): "L11_HIGHER_LOW_LOWER_HIGH",
}


class PivotFreezeError(RuntimeError):
    """Raised when outcome blindness, PIT lineage, or construction gates fail."""


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def validate_spec_and_inputs() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-OBL-012":
        raise PivotFreezeError("unexpected experiment identity")
    if spec.get("status") != "FROZEN_BEFORE_OUTCOME_BLIND_CONSTRUCTION":
        raise PivotFreezeError("pivot construction is not frozen")
    if spec.get("outcome_access") is not False:
        raise PivotFreezeError("outcome prohibition changed")
    identities: dict[str, str] = {}
    mismatches: dict[str, dict[str, str]] = {}
    for role, binding in spec["input_bindings"].items():
        path = resolve_path(binding["path"])
        if not path.is_file():
            raise PivotFreezeError(f"missing bound input: {role}: {path}")
        actual = source.sha256_file(path)
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatches[role] = {"expected": binding["sha256"], "actual": actual}
    if mismatches:
        raise PivotFreezeError(f"frozen input mismatch: {mismatches}")
    source.phase2.validate_inputs()
    return spec, identities


def strict_extrema(
    values: np.ndarray,
    radius: int,
    kind: Literal["min", "max"],
) -> list[int]:
    """Return centered strict extrema; ties are never pivots."""
    if radius < 1 or len(values) < 2 * radius + 1:
        raise PivotFreezeError("invalid pivot radius or history")
    positions: list[int] = []
    for center in range(radius, len(values) - radius):
        window = values[center - radius : center + radius + 1]
        peers = np.delete(window, radius)
        value = values[center]
        if kind == "min" and np.all(value < peers):
            positions.append(center)
        elif kind == "max" and np.all(value > peers):
            positions.append(center)
    return positions


def topology(
    lows: np.ndarray,
    highs: np.ndarray,
    radius: int,
) -> dict[str, Any]:
    troughs = strict_extrema(lows, radius, "min")
    peaks = strict_extrema(highs, radius, "max")
    if len(troughs) < 2 or len(peaks) < 2:
        return {
            "complete": False,
            "trough_count": len(troughs),
            "peak_count": len(peaks),
        }
    prior_trough, last_trough = troughs[-2:]
    prior_peak, last_peak = peaks[-2:]
    trough_log_change = math.log(float(lows[last_trough]) / float(lows[prior_trough]))
    peak_log_change = math.log(float(highs[last_peak]) / float(highs[prior_peak]))
    higher_low = trough_log_change > 0.0
    lower_high = peak_log_change < 0.0
    return {
        "complete": True,
        "trough_count": len(troughs),
        "peak_count": len(peaks),
        "prior_trough_position": prior_trough,
        "last_trough_position": last_trough,
        "prior_peak_position": prior_peak,
        "last_peak_position": last_peak,
        "trough_log_change": trough_log_change,
        "peak_log_change": peak_log_change,
        "higher_low": higher_low,
        "lower_high": lower_high,
        "lineage_id": LINEAGES[(higher_low, lower_high)],
    }


def build_features(history: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    incomplete: list[dict[str, Any]] = []
    for trade_id, rows in history.groupby("trade_id", sort=True):
        rows = rows.sort_values("cal_idx").reset_index(drop=True)
        signal_idx = int(rows.signal_idx.iloc[0])
        if rows.cal_idx.astype(int).tolist() != list(range(signal_idx - 79, signal_idx + 1)):
            raise PivotFreezeError(f"incomplete 80-session history: {trade_id}")
        if not rows.critical_valid.astype(bool).all():
            raise PivotFreezeError(f"hard-invalid daily row: {trade_id}")
        if not rows.iloc[1:].coordinate_step_valid.astype(bool).all():
            raise PivotFreezeError(f"invalid action coordinate: {trade_id}")
        prior60 = rows.iloc[-61:-1].reset_index(drop=True)
        signal = rows.iloc[-1]
        numeric = prior60[["adjusted_low", "adjusted_high", "adjusted_close"]].to_numpy(float)
        if not np.isfinite(numeric).all() or (numeric <= 0).any():
            raise PivotFreezeError(f"invalid prior-60 prices: {trade_id}")
        reference = float(prior60.adjusted_close.max())
        if not float(signal.adjusted_close) > reference:
            raise PivotFreezeError(f"event fails canonical breakout: {trade_id}")
        primary = topology(
            prior60.adjusted_low.to_numpy(float),
            prior60.adjusted_high.to_numpy(float),
            radius=1,
        )
        neighbor = topology(
            prior60.adjusted_low.to_numpy(float),
            prior60.adjusted_high.to_numpy(float),
            radius=2,
        )
        if not primary["complete"] or not neighbor["complete"]:
            incomplete.append(
                {
                    "trade_id": trade_id,
                    "primary": primary,
                    "neighbor": neighbor,
                }
            )
            continue
        records.append(
            {
                "trade_id": trade_id,
                "baseline_block": rows.baseline_block.iloc[0],
                "symbol": rows.symbol.iloc[0],
                "entry_signal_date": pd.Timestamp(signal.trade_date).date().isoformat(),
                "entry_year": int(pd.Timestamp(signal.trade_date).year),
                "available_at_timestamp": pd.Timestamp(signal.available_at).isoformat(),
                "daily_snapshot_id": signal.snapshot_id,
                "pivot_radius": 1,
                "trough_count": primary["trough_count"],
                "peak_count": primary["peak_count"],
                "prior_trough_position": primary["prior_trough_position"],
                "last_trough_position": primary["last_trough_position"],
                "prior_peak_position": primary["prior_peak_position"],
                "last_peak_position": primary["last_peak_position"],
                "trough_log_change": primary["trough_log_change"],
                "peak_log_change": primary["peak_log_change"],
                "higher_low": primary["higher_low"],
                "lower_high": primary["lower_high"],
                "lineage_id": primary["lineage_id"],
                "neighbor_pivot_radius": 2,
                "neighbor_trough_count": neighbor["trough_count"],
                "neighbor_peak_count": neighbor["peak_count"],
                "neighbor_trough_log_change": neighbor["trough_log_change"],
                "neighbor_peak_log_change": neighbor["peak_log_change"],
                "neighbor_higher_low": neighbor["higher_low"],
                "neighbor_lower_high": neighbor["lower_high"],
                "neighbor_lineage_id": neighbor["lineage_id"],
            }
        )
    if incomplete:
        raise PivotFreezeError(
            f"events lack two strict peaks/troughs under a frozen definition: {incomplete[:8]}; "
            f"total={len(incomplete)}"
        )
    frame = pd.DataFrame(records).sort_values("trade_id").reset_index(drop=True)
    if FORBIDDEN_COLUMNS.intersection(frame.columns):
        raise PivotFreezeError("outcome column entered pivot frame")
    return frame


def construction_audit(
    frame: pd.DataFrame,
    spec: dict[str, Any],
) -> dict[str, Any]:
    expected = sorted(LINEAGES.values())
    counts = frame.lineage_id.value_counts().reindex(expected, fill_value=0)
    by_year = pd.crosstab(frame.entry_year, frame.lineage_id).reindex(
        index=range(2018, 2026), columns=expected, fill_value=0
    )
    by_block = pd.crosstab(frame.baseline_block, frame.lineage_id).reindex(
        columns=expected, fill_value=0
    )
    agreement = float(frame.lineage_id.eq(frame.neighbor_lineage_id).mean())
    gates_spec = spec["construction_gates"]
    gates = {
        "complete_coverage": len(frame) == 399 and frame.trade_id.nunique() == 399,
        "all_four_lineages": bool((counts > 0).all()),
        "minimum_lineage_size": int(counts.min()) >= gates_spec["minimum_lineage_size"],
        "maximum_lineage_fraction": float(counts.max() / len(frame))
        <= gates_spec["maximum_lineage_fraction"],
        "every_lineage_in_every_year": int(by_year.min().min())
        >= gates_spec["minimum_lineage_count_per_year"],
        "neighbor_assignment_agreement": agreement
        >= gates_spec["minimum_neighbor_assignment_agreement"],
        "no_outcome_columns": not bool(FORBIDDEN_COLUMNS.intersection(frame.columns)),
    }
    return {
        "counts": counts.to_dict(),
        "fractions": (counts / len(frame)).to_dict(),
        "counts_by_year": by_year.to_dict(orient="index"),
        "counts_by_block": by_block.to_dict(orient="index"),
        "neighbor_assignment_agreement": agreement,
        "gates": gates,
        "decision": "FREEZE_LINEAGE" if all(gates.values()) else "REJECT_BEFORE_OUTCOME",
    }


def render_report(audit: dict[str, Any], freeze_id: str) -> str:
    lines = [
        "# EXP-OBL-012 outcome-blind pivot-topology freeze",
        "",
        f"Decision: `{audit['decision']}`.",
        "",
        f"LINEAGE_FREEZE_ID: `{freeze_id}`.",
        "",
        "| Neutral lineage | Count |",
        "|---|---:|",
    ]
    lines.extend(f"| {name} | {count} |" for name, count in sorted(audit["counts"].items()))
    lines.extend(
        [
            "",
            f"Three-session/five-session neighboring assignment agreement: `{audit['neighbor_assignment_agreement']:.6f}`.",
            "",
            "No future outcome or post-entry field was read or calculated. The IDs describe only the ordering of the two latest strict prior-60 troughs and peaks.",
            "",
            "Features are available at the completed signal close; potential action is T+1 open or later. No strategy rule is authorized.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    spec, identities = validate_spec_and_inputs()
    events = source.load_identities()
    history, history_audit = source.build_daily_history(events)
    frame = build_features(history)
    audit = construction_audit(frame, spec)
    if not all(audit["gates"].values()):
        raise PivotFreezeError(f"frozen construction gates failed: {audit}")
    feature_columns = [
        column
        for column in frame.columns
        if column not in {"lineage_id", "neighbor_lineage_id"}
    ]
    assignment_columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_signal_date",
        "entry_year",
        "lineage_id",
        "neighbor_lineage_id",
    ]
    source.atomic_csv(FEATURES, frame[feature_columns])
    source.atomic_csv(ASSIGNMENTS, frame[assignment_columns])
    feature_sha = source.sha256_file(FEATURES)
    assignment_sha = source.sha256_file(ASSIGNMENTS)
    freeze_id = f"LINEAGE-OBL-012-{assignment_sha[:16].upper()}"
    audit.update(
        {
            "experiment_id": "EXP-OBL-012",
            "hypothesis_id": "H-OBL-010",
            "outcome_access": False,
            "input_identities": identities,
            "history_audit": history_audit,
            "feature_table_sha256": feature_sha,
            "assignment_table_sha256": assignment_sha,
            "lineage_freeze_id": freeze_id,
        }
    )
    source.atomic_write(
        AUDIT,
        json.dumps(source.clean_json(audit), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    manifest = {
        "lineage_freeze_id": freeze_id,
        "experiment_id": "EXP-OBL-012",
        "hypothesis_id": "H-OBL-010",
        "outcome_access_before_freeze": False,
        "available_at_timestamp": "completed signal session 15:30 Asia/Shanghai",
        "potential_action_timestamp": "T+1 open or later",
        "feature_table_sha256": feature_sha,
        "assignment_table_sha256": assignment_sha,
        "audit_sha256": source.sha256_file(AUDIT),
        "modification_after_outcome_reveal": "FORBIDDEN",
    }
    source.atomic_write(
        FREEZE,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    source.atomic_write(REPORT, render_report(audit, freeze_id))
    print(json.dumps(source.clean_json(audit), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
