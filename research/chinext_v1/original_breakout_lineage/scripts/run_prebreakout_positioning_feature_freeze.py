#!/usr/bin/env python3
"""Freeze EXP-OBL-006 prebreakout positioning without outcome access."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/original_breakout_lineage"
SCRIPTS = WORK / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_outcome_blind_lineage_freeze as base  # noqa: E402

SPEC = WORK / "experiments/EXP-OBL-006_spec.json"
FROZEN_FORMATION = WORK / "artifacts/formation_features_v3.csv"
OUTPUT_TABLE = WORK / "artifacts/prebreakout_positioning_features.csv"
OUTPUT_AUDIT = WORK / "artifacts/EXP-OBL-006_audit.json"
FEATURE_FREEZE = WORK / "feature_freezes/FEATURE-OBL-006.json"
REPORT = WORK / "reports/EXP-OBL-006_prebreakout_positioning_feature_freeze.md"
FORBIDDEN_COLUMNS = base.FORBIDDEN_COLUMNS


class PositioningFreezeError(RuntimeError):
    """Raised when input, PIT, reconciliation, or feature stability fails."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    frame.to_csv(temporary, index=False, float_format="%.12g", lineterminator="\n")
    os.replace(temporary, path)


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if pd.isna(value):
        return None
    return value


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def validate_spec_and_inputs() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-OBL-006":
        raise PositioningFreezeError("unexpected experiment identity")
    if spec.get("status") != "FROZEN_BEFORE_FEATURE_MATERIALIZATION":
        raise PositioningFreezeError("feature experiment is not frozen")
    if spec.get("outcome_access") is not False:
        raise PositioningFreezeError("outcome prohibition changed")
    identities: dict[str, str] = {}
    mismatches: dict[str, dict[str, str]] = {}
    for role, binding in spec["input_bindings"].items():
        path = resolve_path(binding["path"])
        if not path.is_file():
            raise PositioningFreezeError(f"missing bound input: {role}: {path}")
        actual = sha256_file(path)
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatches[role] = {"expected": binding["sha256"], "actual": actual}
    if mismatches:
        raise PositioningFreezeError(f"frozen input mismatch: {mismatches}")
    base.phase2.validate_inputs()
    return spec, identities


def construct_features(identities: pd.DataFrame, history: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for trade_id, rows in history.groupby("trade_id", sort=True):
        rows = rows.sort_values("cal_idx").reset_index(drop=True)
        signal_idx = int(rows.signal_idx.iloc[0])
        if rows.cal_idx.astype(int).tolist() != list(range(signal_idx - 79, signal_idx + 1)):
            raise PositioningFreezeError(f"incomplete 80-session history: {trade_id}")
        if not rows.critical_valid.astype(bool).all():
            raise PositioningFreezeError(f"hard-invalid daily row: {trade_id}")
        if not rows.iloc[1:].coordinate_step_valid.astype(bool).all():
            raise PositioningFreezeError(f"invalid action coordinate: {trade_id}")
        prior60 = rows.iloc[-61:-1].copy()
        signal = rows.iloc[-1]
        reference = float(prior60.adjusted_close.max())
        signal_close = float(signal.adjusted_close)
        if not signal_close > reference:
            raise PositioningFreezeError(f"event fails canonical strict breakout: {trade_id}")
        positions = np.flatnonzero(
            np.isclose(
                prior60.adjusted_close.to_numpy(float),
                reference,
                rtol=1e-12,
                atol=1e-12,
            )
        )
        if not len(positions):
            raise PositioningFreezeError(f"reference position missing: {trade_id}")
        t1 = float(prior60.adjusted_close.iloc[-1])
        t3 = float(prior60.adjusted_close.iloc[-3])
        t5 = float(prior60.adjusted_close.iloc[-5])
        records.append(
            {
                "trade_id": trade_id,
                "baseline_block": rows.baseline_block.iloc[0],
                "symbol": rows.symbol.iloc[0],
                "entry_signal_date": pd.Timestamp(signal.trade_date).date().isoformat(),
                "entry_year": int(pd.Timestamp(signal.trade_date).year),
                "feature_available_at": pd.Timestamp(signal.available_at).isoformat(),
                "daily_snapshot_id": signal.snapshot_id,
                "prebreakout_distance_t1": math.log(t1 / reference),
                "prebreakout_distance_t3": math.log(t3 / reference),
                "prebreakout_distance_t5": math.log(t5 / reference),
                "signal_displacement_from_t1": math.log(signal_close / t1),
                "breakout_margin_log": math.log(signal_close / reference),
                "sessions_since_reference": int(len(prior60) - 1 - int(positions[-1])),
            }
        )
    frame = pd.DataFrame(records).sort_values("trade_id").reset_index(drop=True)
    if len(frame) != 399 or frame.trade_id.nunique() != 399:
        raise PositioningFreezeError("feature output is not 399 unique events")
    if FORBIDDEN_COLUMNS.intersection(frame.columns):
        raise PositioningFreezeError("outcome column entered positioning frame")
    expected = identities.sort_values("trade_id").trade_id.reset_index(drop=True)
    if not frame.trade_id.equals(expected):
        raise PositioningFreezeError("feature identities differ from frozen population")
    return frame


def safe_spearman(frame: pd.DataFrame, left: str, right: str) -> float:
    if frame[left].nunique() < 2 or frame[right].nunique() < 2:
        raise PositioningFreezeError(f"nonvarying feature: {left}/{right}")
    return float(spearmanr(frame[left], frame[right]).statistic)


def audit_features(frame: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    frozen = pd.read_csv(
        FROZEN_FORMATION,
        usecols=["trade_id", "prebreakout_distance", "sessions_since_reference"],
    )
    joined = frame.merge(frozen, on="trade_id", validate="one_to_one")
    exact = {
        "t1_distance": bool(
            np.allclose(
                joined.prebreakout_distance_t1,
                joined.prebreakout_distance,
                rtol=1e-12,
                atol=1e-12,
            )
        ),
        "reference_age": bool(
            np.array_equal(
                joined.sessions_since_reference_x.to_numpy(int),
                joined.sessions_since_reference_y.to_numpy(int),
            )
        ),
        "log_additivity": bool(
            np.allclose(
                frame.prebreakout_distance_t1 + frame.signal_displacement_from_t1,
                frame.breakout_margin_log,
                rtol=1e-12,
                atol=1e-12,
            )
        ),
    }
    neighbor = {
        "t3": safe_spearman(frame, "prebreakout_distance_t1", "prebreakout_distance_t3"),
        "t5": safe_spearman(frame, "prebreakout_distance_t1", "prebreakout_distance_t5"),
    }
    yearly_direction: dict[str, dict[str, float]] = {}
    for year, sample in frame.groupby("entry_year", sort=True):
        yearly_direction[str(year)] = {
            "t3": safe_spearman(sample, "prebreakout_distance_t1", "prebreakout_distance_t3"),
            "t5": safe_spearman(sample, "prebreakout_distance_t1", "prebreakout_distance_t5"),
        }
    gates_spec = spec["construction_gates"]
    gates = {
        "complete_coverage": len(frame) == 399 and frame.trade_id.nunique() == 399,
        "exact_reconciliation": all(exact.values()),
        "continuous_variation": int(frame.prebreakout_distance_t1.nunique())
        >= gates_spec["minimum_primary_unique_values"],
        "neighbor_stability": min(neighbor.values())
        >= gates_spec["minimum_neighbor_spearman"],
        "yearly_neighbor_direction": all(
            sum(item[name] > 0 for item in yearly_direction.values())
            >= gates_spec["minimum_positive_years_per_neighbor"]
            for name in ("t3", "t5")
        ),
        "no_outcome_columns": not bool(FORBIDDEN_COLUMNS.intersection(frame.columns)),
    }
    if not all(gates.values()):
        raise PositioningFreezeError(
            f"positioning feature gates failed: {gates}; neighbors={neighbor}; "
            f"yearly={yearly_direction}"
        )
    return {
        "gates": gates,
        "exact_reconciliation": exact,
        "neighbor_spearman": neighbor,
        "yearly_neighbor_spearman": yearly_direction,
        "primary_distribution": {
            "minimum": float(frame.prebreakout_distance_t1.min()),
            "maximum": float(frame.prebreakout_distance_t1.max()),
            "mean": float(frame.prebreakout_distance_t1.mean()),
            "median": float(frame.prebreakout_distance_t1.median()),
            "unique_values": int(frame.prebreakout_distance_t1.nunique()),
        },
    }


def render_report(audit: dict[str, Any], freeze_id: str) -> str:
    feature = audit["feature_audit"]
    return (
        "# EXP-OBL-006 prebreakout-positioning feature freeze\n\n"
        f"FEATURE_FREEZE_ID: `{freeze_id}`.\n\n"
        "No outcome column was read. The primary is action-safe "
        "log(close[t-1] / canonical prior-60 close reference); values nearer zero "
        "mean price was already positioned closer to resistance.\n\n"
        f"- T-1/T-3 and T-1/T-5 rhos: `{feature['neighbor_spearman']}`\n"
        f"- Primary distribution: `{feature['primary_distribution']}`\n"
        "- Available at: before the signal session; combined frozen feature artifact "
        "is timestamped at signal-session 15:30 and applies T+1 or later\n\n"
        "No threshold or strategy rule is authorized.\n"
    )


def main() -> None:
    spec, identities = validate_spec_and_inputs()
    events = base.load_identities()
    years = list(range(2018, 2026))
    cy006 = base.inventory_files(
        base.CY006_INVENTORY,
        [f"partition_year={year}/data_0.parquet" for year in years],
    )
    if len(cy006) != 8:
        raise PositioningFreezeError("CY-006 partition count changed")
    history, daily_audit = base.build_daily_history(events)
    features = construct_features(events, history)
    feature_audit = audit_features(features, spec)
    atomic_csv(OUTPUT_TABLE, features)
    feature_sha = sha256_file(OUTPUT_TABLE)
    freeze_id = f"FEATURE-OBL-006-{feature_sha[:16].upper()}"
    audit = {
        "experiment_id": "EXP-OBL-006",
        "hypothesis_id": "H-OBL-005",
        "status": "FROZEN_OUTCOME_BLIND_FEATURE",
        "feature_freeze_id": freeze_id,
        "outcome_columns_read": [],
        "population": {
            "events": len(features),
            "years": sorted(features.entry_year.unique().astype(int).tolist()),
            "history_rows": len(history),
        },
        "feature_audit": feature_audit,
        "daily_reconstruction": daily_audit,
        "feature_table_sha256": feature_sha,
        "input_identities": identities,
        "available_at_timestamp": "primary known before signal; frozen artifact at signal 15:30",
        "potential_action_timestamp": "entry execution T+1 open or later",
    }
    atomic_write(
        OUTPUT_AUDIT,
        json.dumps(clean_json(audit), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    manifest = {
        "schema_version": "1.0.0",
        "feature_freeze_id": freeze_id,
        "experiment_id": "EXP-OBL-006",
        "status": "FROZEN_BEFORE_OUTCOME_JOIN",
        "spec_path": str(SPEC.relative_to(ROOT)),
        "spec_sha256": sha256_file(SPEC),
        "runner_path": str(Path(__file__).resolve().relative_to(ROOT)),
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "feature_table": str(OUTPUT_TABLE.relative_to(ROOT)),
        "feature_table_sha256": feature_sha,
        "audit_path": str(OUTPUT_AUDIT.relative_to(ROOT)),
        "audit_sha256": sha256_file(OUTPUT_AUDIT),
        "primary_feature": "prebreakout_distance_t1",
        "neighbors": ["prebreakout_distance_t3", "prebreakout_distance_t5"],
        "outcome_access_before_freeze": False,
        "outcome_columns_read": [],
    }
    atomic_write(
        FEATURE_FREEZE,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    atomic_write(REPORT, render_report(audit, freeze_id))
    print(json.dumps(clean_json(audit), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
