#!/usr/bin/env python3
"""Freeze EXP-OBL-005 resistance-test topology without outcome access."""

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

SPEC = WORK / "experiments/EXP-OBL-005_spec.json"
FROZEN_FORMATION = WORK / "artifacts/formation_features_v3.csv"
OUTPUT_TABLE = WORK / "artifacts/resistance_test_features.csv"
OUTPUT_AUDIT = WORK / "artifacts/EXP-OBL-005_audit.json"
FEATURE_FREEZE = WORK / "feature_freezes/FEATURE-OBL-005.json"
REPORT = WORK / "reports/EXP-OBL-005_resistance_test_feature_freeze.md"

ZONE_WIDTHS = (0.01, 0.02, 0.03)
FORBIDDEN_COLUMNS = base.FORBIDDEN_COLUMNS


class ResistanceFreezeError(RuntimeError):
    """Raised when feature identity, PIT, coverage, or stability fails."""


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
    if spec.get("experiment_id") != "EXP-OBL-005":
        raise ResistanceFreezeError("unexpected experiment identity")
    if spec.get("status") != "FROZEN_BEFORE_FEATURE_MATERIALIZATION":
        raise ResistanceFreezeError("feature experiment is not frozen")
    if spec.get("outcome_access") is not False:
        raise ResistanceFreezeError("outcome prohibition changed")
    identities: dict[str, str] = {}
    mismatches: dict[str, dict[str, str]] = {}
    for role, binding in spec["input_bindings"].items():
        path = resolve_path(binding["path"])
        if not path.is_file():
            raise ResistanceFreezeError(f"missing bound input: {role}: {path}")
        actual = sha256_file(path)
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatches[role] = {"expected": binding["sha256"], "actual": actual}
    if mismatches:
        raise ResistanceFreezeError(f"frozen input mismatch: {mismatches}")
    base.phase2.validate_inputs()
    return spec, identities


def episode_count(in_zone: np.ndarray) -> int:
    flags = in_zone.astype(bool)
    if not len(flags):
        return 0
    return int(flags[0]) + int(np.sum((~flags[:-1]) & flags[1:]))


def maximum_run(in_zone: np.ndarray) -> int:
    best = current = 0
    for value in in_zone.astype(bool):
        current = current + 1 if value else 0
        best = max(best, current)
    return best


def construct_features(
    identities: pd.DataFrame,
    history: pd.DataFrame,
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for trade_id, rows in history.groupby("trade_id", sort=True):
        rows = rows.sort_values("cal_idx").reset_index(drop=True)
        signal_idx = int(rows.signal_idx.iloc[0])
        if rows.cal_idx.astype(int).tolist() != list(range(signal_idx - 79, signal_idx + 1)):
            raise ResistanceFreezeError(f"incomplete 80-session history: {trade_id}")
        if not rows.critical_valid.astype(bool).all():
            raise ResistanceFreezeError(f"hard-invalid daily row: {trade_id}")
        if not rows.iloc[1:].coordinate_step_valid.astype(bool).all():
            raise ResistanceFreezeError(f"invalid action coordinate: {trade_id}")
        prior60 = rows.iloc[-61:-1].copy()
        reference = float(prior60.adjusted_close.max())
        signal = rows.iloc[-1]
        if not float(signal.adjusted_close) > reference:
            raise ResistanceFreezeError(f"event fails canonical strict breakout: {trade_id}")
        values: dict[str, Any] = {}
        for width in ZONE_WIDTHS:
            label = f"{int(width * 100)}pct"
            in_zone = prior60.adjusted_close.to_numpy(float) >= (1.0 - width) * reference
            values[f"zone_day_count_{label}"] = int(in_zone.sum())
            values[f"test_episode_count_{label}"] = episode_count(in_zone)
            values[f"maximum_zone_run_{label}"] = maximum_run(in_zone)
        max_positions = np.flatnonzero(
            np.isclose(
                prior60.adjusted_close.to_numpy(float),
                reference,
                rtol=1e-12,
                atol=1e-12,
            )
        )
        if not len(max_positions):
            raise ResistanceFreezeError(f"reference position missing: {trade_id}")
        records.append(
            {
                "trade_id": trade_id,
                "baseline_block": rows.baseline_block.iloc[0],
                "symbol": rows.symbol.iloc[0],
                "entry_signal_date": pd.Timestamp(signal.trade_date).date().isoformat(),
                "entry_year": int(pd.Timestamp(signal.trade_date).year),
                "feature_available_at": pd.Timestamp(signal.available_at).isoformat(),
                "daily_snapshot_id": signal.snapshot_id,
                "reference_adjusted": reference,
                "sessions_since_reference": int(len(prior60) - 1 - int(max_positions[-1])),
                "prebreakout_distance": math.log(
                    float(prior60.adjusted_close.iloc[-1]) / reference
                ),
                "breakout_margin": math.log(float(signal.adjusted_close) / reference),
                **values,
            }
        )
    frame = pd.DataFrame(records).sort_values("trade_id").reset_index(drop=True)
    if len(frame) != 399 or frame.trade_id.nunique() != 399:
        raise ResistanceFreezeError("feature output is not 399 unique events")
    if FORBIDDEN_COLUMNS.intersection(frame.columns):
        raise ResistanceFreezeError("outcome column entered resistance feature frame")
    expected_ids = identities.sort_values("trade_id").trade_id.reset_index(drop=True)
    if not frame.trade_id.equals(expected_ids):
        raise ResistanceFreezeError("feature identities differ from frozen population")
    return frame


def spearman(frame: pd.DataFrame, left: str, right: str) -> float:
    if frame[left].nunique() < 2 or frame[right].nunique() < 2:
        raise ResistanceFreezeError(f"nonvarying neighbor feature: {left}/{right}")
    return float(spearmanr(frame[left], frame[right]).statistic)


def audit_features(frame: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    frozen = pd.read_csv(
        FROZEN_FORMATION,
        usecols=[
            "trade_id",
            "prior60_reference_test_count_2pct",
            "sessions_since_reference",
            "prebreakout_distance",
            "breakout_margin",
        ],
    )
    joined = frame.merge(frozen, on="trade_id", suffixes=("", "_frozen"), validate="one_to_one")
    exact_checks = {
        "zone_day_count_2pct": bool(
            np.array_equal(
                joined.zone_day_count_2pct.to_numpy(int),
                joined.prior60_reference_test_count_2pct.to_numpy(int),
            )
        ),
        "sessions_since_reference": bool(
            np.array_equal(
                joined.sessions_since_reference.to_numpy(int),
                joined.sessions_since_reference_frozen.to_numpy(int),
            )
        ),
        "prebreakout_distance": bool(
            np.allclose(
                joined.prebreakout_distance,
                joined.prebreakout_distance_frozen,
                rtol=1e-12,
                atol=1e-12,
            )
        ),
        "breakout_margin": bool(
            np.allclose(
                joined.breakout_margin,
                joined.breakout_margin_frozen,
                rtol=1e-12,
                atol=1e-12,
            )
        ),
    }
    primary = "test_episode_count_2pct"
    yearly_unique = frame.groupby("entry_year")[primary].nunique().to_dict()
    neighbor_rhos = {
        "1pct": spearman(frame, primary, "test_episode_count_1pct"),
        "3pct": spearman(frame, primary, "test_episode_count_3pct"),
    }
    gates_spec = spec["construction_gates"]
    gates = {
        "complete_coverage": len(frame) == 399 and frame.trade_id.nunique() == 399,
        "exact_reconciliation": all(exact_checks.values()),
        "overall_variation": int(frame[primary].nunique())
        >= gates_spec["minimum_primary_unique_values"],
        "every_year_variation": min(yearly_unique.values())
        >= gates_spec["minimum_primary_unique_values_per_year"],
        "neighbor_stability": min(neighbor_rhos.values())
        >= gates_spec["minimum_neighbor_spearman"],
        "no_outcome_columns": not bool(FORBIDDEN_COLUMNS.intersection(frame.columns)),
    }
    if not all(gates.values()):
        raise ResistanceFreezeError(
            f"resistance feature gates failed: {gates}; yearly={yearly_unique}; "
            f"neighbors={neighbor_rhos}"
        )
    return {
        "gates": gates,
        "exact_reconciliation": exact_checks,
        "primary_distribution": {
            "minimum": int(frame[primary].min()),
            "maximum": int(frame[primary].max()),
            "unique_values": int(frame[primary].nunique()),
            "mean": float(frame[primary].mean()),
            "median": float(frame[primary].median()),
            "value_counts": frame[primary].value_counts().sort_index().to_dict(),
        },
        "yearly_unique_values": yearly_unique,
        "neighbor_spearman": neighbor_rhos,
    }


def render_report(audit: dict[str, Any], freeze_id: str) -> str:
    distribution = audit["feature_audit"]["primary_distribution"]
    return (
        "# EXP-OBL-005 resistance-test feature freeze\n\n"
        f"FEATURE_FREEZE_ID: `{freeze_id}`.\n\n"
        "No outcome column was read or calculated. The primary feature is the number "
        "of distinct prior-60 entries into the fixed 2% zone below the canonical "
        "closing-price reference. One long stay counts as one episode.\n\n"
        f"- Range: `{distribution['minimum']}..{distribution['maximum']}` episodes\n"
        f"- Unique values: `{distribution['unique_values']}`\n"
        f"- 1%/3% neighbor rhos: `{audit['feature_audit']['neighbor_spearman']}`\n"
        "- Available at: signal-session 15:30; potential action T+1 or later\n\n"
        "No threshold, entry rule, exit rule, size rule, or production action is authorized.\n"
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
        raise ResistanceFreezeError("CY-006 partition count changed")
    history, daily_audit = base.build_daily_history(events)
    features = construct_features(events, history)
    feature_audit = audit_features(features, spec)
    atomic_csv(OUTPUT_TABLE, features)
    feature_sha = sha256_file(OUTPUT_TABLE)
    freeze_id = f"FEATURE-OBL-005-{feature_sha[:16].upper()}"
    audit = {
        "experiment_id": "EXP-OBL-005",
        "hypothesis_id": "H-OBL-004",
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
        "available_at_timestamp": "entry signal session 15:30 Asia/Shanghai",
        "potential_action_timestamp": "entry execution T+1 open or later",
    }
    atomic_write(
        OUTPUT_AUDIT,
        json.dumps(clean_json(audit), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    manifest = {
        "schema_version": "1.0.0",
        "feature_freeze_id": freeze_id,
        "experiment_id": "EXP-OBL-005",
        "status": "FROZEN_BEFORE_OUTCOME_JOIN",
        "spec_path": str(SPEC.relative_to(ROOT)),
        "spec_sha256": sha256_file(SPEC),
        "runner_path": str(Path(__file__).resolve().relative_to(ROOT)),
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "feature_table": str(OUTPUT_TABLE.relative_to(ROOT)),
        "feature_table_sha256": feature_sha,
        "audit_path": str(OUTPUT_AUDIT.relative_to(ROOT)),
        "audit_sha256": sha256_file(OUTPUT_AUDIT),
        "primary_feature": "test_episode_count_2pct",
        "neighbors": ["test_episode_count_1pct", "test_episode_count_3pct"],
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
