#!/usr/bin/env python3
"""Clean EXP-OBL-014 reexecution with canonical null-rights coalescing."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/original_breakout_lineage"
SCRIPTS = WORK / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_minvol_anchor_lineage_freeze as base  # noqa: E402

SPEC = WORK / "experiments/EXP-OBL-014_spec.json"
FEATURES = WORK / "artifacts/minvol_anchor_features_v2.csv"
ASSIGNMENTS = WORK / "artifacts/minvol_anchor_assignments_v2.csv"
AUDIT = WORK / "artifacts/EXP-OBL-014_audit.json"
FREEZE = WORK / "lineage_freezes/LINEAGE-OBL-014.json"
REPORT = WORK / "reports/EXP-OBL-014_minvol_anchor_freeze.md"


class MinVolV2FreezeError(RuntimeError):
    """Raised when the fresh binding or inherited construction gates fail."""


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def validate_spec_and_inputs() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-OBL-014":
        raise MinVolV2FreezeError("unexpected experiment identity")
    if spec.get("status") != "FROZEN_CLEAN_REEXECUTION_BEFORE_CONSTRUCTION":
        raise MinVolV2FreezeError("clean minimum-volume reexecution is not frozen")
    if spec.get("outcome_access") is not False:
        raise MinVolV2FreezeError("outcome prohibition changed")
    identities: dict[str, str] = {}
    mismatches: dict[str, dict[str, str]] = {}
    for role, binding in spec["input_bindings"].items():
        path = resolve_path(binding["path"])
        if not path.is_file():
            raise MinVolV2FreezeError(f"missing bound input: {role}: {path}")
        actual = base.source.sha256_file(path)
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatches[role] = {"expected": binding["sha256"], "actual": actual}
    if mismatches:
        raise MinVolV2FreezeError(f"frozen input mismatch: {mismatches}")
    base.source.phase2.validate_inputs()
    return spec, identities


def canonical_optional_zero(value: Any) -> float:
    """Match canonical finite_or_default(value, 0.0) for optional rights."""
    return 0.0 if pd.isna(value) else float(value)


def volumes_in_signal_coordinate(rows: pd.DataFrame) -> np.ndarray:
    """Apply visible action multipliers to prior rows; null rights mean zero."""
    result = rows.volume.to_numpy(float).copy()
    for position, item in rows.reset_index(drop=True).iterrows():
        action_count = int(item.corporate_action_count or 0)
        if action_count <= 0:
            continue
        multiplier = float(item.share_multiplier)
        rights = canonical_optional_zero(item.rights_ratio)
        visible = (
            pd.notna(item.corporate_action_available_date)
            and pd.Timestamp(item.corporate_action_available_date).date()
            <= pd.Timestamp(item.trade_date).date()
        )
        valid_flag = pd.notna(item.corporate_action_valid) and bool(
            item.corporate_action_valid
        )
        blocking = pd.isna(item.corporate_action_blocking) or bool(
            item.corporate_action_blocking
        )
        valid = (
            valid_flag
            and not blocking
            and visible
            and rights == 0.0
            and math.isfinite(multiplier)
            and multiplier > 0.0
        )
        if not valid:
            raise MinVolV2FreezeError(
                f"invalid corporate action: trade={item.trade_id} date={item.trade_date}"
            )
        result[:position] *= multiplier
    if not np.isfinite(result).all() or (result <= 0).any():
        raise MinVolV2FreezeError("invalid rebased volume history")
    return result


def render_report(audit: dict[str, Any], freeze_id: str) -> str:
    lines = [
        "# EXP-OBL-014 clean outcome-blind minimum-volume anchor freeze",
        "",
        f"Decision: `{audit['decision']}`.",
        "",
        f"LINEAGE_FREEZE_ID: `{freeze_id}`.",
        "",
        "This is a scientifically unchanged clean reexecution of EXP-OBL-013. The only correction coalesces null optional rights ratio to canonical zero.",
        "",
        "| Neutral lineage | Count |",
        "|---|---:|",
    ]
    lines.extend(f"| {name} | {count} |" for name, count in sorted(audit["counts"].items()))
    lines.extend(
        [
            "",
            f"Low-support/close-support neighboring agreement: `{audit['neighbor_assignment_agreement']:.6f}`.",
            "",
            f"Events with canonical earliest-minimum ties: `{audit['events_with_tied_minimum_volume']}`.",
            "",
            "No post-entry outcome was read. No strategy rule is authorized.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    spec, identities = validate_spec_and_inputs()
    events = base.source.load_identities()
    history, history_audit = base.build_history(events)
    base.volumes_in_signal_coordinate = volumes_in_signal_coordinate
    frame = base.build_features(history)
    audit = base.construction_audit(frame, spec)
    if not all(audit["gates"].values()):
        raise MinVolV2FreezeError(f"frozen construction gates failed: {audit}")
    feature_columns = [
        column for column in frame.columns if column not in {"lineage_id", "neighbor_lineage_id"}
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
    base.source.atomic_csv(FEATURES, frame[feature_columns])
    base.source.atomic_csv(ASSIGNMENTS, frame[assignment_columns])
    feature_sha = base.source.sha256_file(FEATURES)
    assignment_sha = base.source.sha256_file(ASSIGNMENTS)
    freeze_id = f"LINEAGE-OBL-014-{assignment_sha[:16].upper()}"
    audit.update(
        {
            "experiment_id": "EXP-OBL-014",
            "hypothesis_id": "H-OBL-011",
            "clean_reexecution_of": "EXP-OBL-013",
            "scientific_definitions_changed": False,
            "engineering_correction": "coalesce null optional rights_ratio to canonical zero",
            "outcome_access": False,
            "input_identities": identities,
            "history_audit": history_audit,
            "feature_table_sha256": feature_sha,
            "assignment_table_sha256": assignment_sha,
            "lineage_freeze_id": freeze_id,
        }
    )
    base.source.atomic_write(
        AUDIT,
        json.dumps(base.source.clean_json(audit), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    manifest = {
        "lineage_freeze_id": freeze_id,
        "experiment_id": "EXP-OBL-014",
        "hypothesis_id": "H-OBL-011",
        "clean_reexecution_of": "EXP-OBL-013",
        "scientific_definitions_changed": False,
        "outcome_access_before_freeze": False,
        "available_at_timestamp": "completed signal session 15:30 Asia/Shanghai",
        "potential_action_timestamp": "T+1 open or later",
        "feature_table_sha256": feature_sha,
        "assignment_table_sha256": assignment_sha,
        "audit_sha256": base.source.sha256_file(AUDIT),
        "modification_after_outcome_reveal": "FORBIDDEN",
    }
    base.source.atomic_write(
        FREEZE,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    base.source.atomic_write(REPORT, render_report(audit, freeze_id))
    print(json.dumps(base.source.clean_json(audit), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
