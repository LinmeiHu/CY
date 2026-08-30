#!/usr/bin/env python3
"""Outcome-blind EXP-OBL-015 binary minimum-volume support refinement."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/original_breakout_lineage"
SCRIPTS = WORK / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_minvol_anchor_lineage_freeze as base  # noqa: E402
import run_minvol_anchor_lineage_freeze_v2 as corrected  # noqa: E402

SPEC = WORK / "experiments/EXP-OBL-015_spec.json"
FEATURES = WORK / "artifacts/minvol_support_features.csv"
ASSIGNMENTS = WORK / "artifacts/minvol_support_assignments.csv"
AUDIT = WORK / "artifacts/EXP-OBL-015_audit.json"
FREEZE = WORK / "lineage_freezes/LINEAGE-OBL-015.json"
REPORT = WORK / "reports/EXP-OBL-015_minvol_support_freeze.md"

PRIMARY_NAMES = {False: "L_SUPPORT_BROKEN", True: "L_SUPPORT_HELD"}


class MinVolSupportFreezeError(RuntimeError):
    """Raised when the refined binary freeze contract fails."""


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def validate_spec_and_inputs() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-OBL-015":
        raise MinVolSupportFreezeError("unexpected experiment identity")
    if spec.get("status") != "FROZEN_OUTCOME_BLIND_FEASIBILITY_REFINEMENT":
        raise MinVolSupportFreezeError("binary support refinement is not frozen")
    if spec.get("outcome_access") is not False:
        raise MinVolSupportFreezeError("outcome prohibition changed")
    identities: dict[str, str] = {}
    mismatches: dict[str, dict[str, str]] = {}
    for role, binding in spec["input_bindings"].items():
        path = resolve_path(binding["path"])
        if not path.is_file():
            raise MinVolSupportFreezeError(f"missing bound input: {role}: {path}")
        actual = base.source.sha256_file(path)
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatches[role] = {"expected": binding["sha256"], "actual": actual}
    if mismatches:
        raise MinVolSupportFreezeError(f"frozen input mismatch: {mismatches}")
    base.source.phase2.validate_inputs()
    return spec, identities


def refine_assignments(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["support_lineage_id"] = result.low_support_held.map(PRIMARY_NAMES)
    result["neighbor_support_lineage_id"] = result.close_support_held_neighbor.map(
        PRIMARY_NAMES
    )
    return result


def construction_audit(frame: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    expected = sorted(PRIMARY_NAMES.values())
    counts = frame.support_lineage_id.value_counts().reindex(expected, fill_value=0)
    by_year = pd.crosstab(frame.entry_year, frame.support_lineage_id).reindex(
        index=range(2018, 2026), columns=expected, fill_value=0
    )
    by_block = pd.crosstab(frame.baseline_block, frame.support_lineage_id).reindex(
        columns=expected, fill_value=0
    )
    agreement = float(
        frame.support_lineage_id.eq(frame.neighbor_support_lineage_id).mean()
    )
    gates_spec = spec["construction_gates"]
    gates = {
        "complete_coverage": len(frame) == 399 and frame.trade_id.nunique() == 399,
        "both_lineages": bool((counts > 0).all()),
        "minimum_lineage_size": int(counts.min()) >= gates_spec["minimum_lineage_size"],
        "maximum_lineage_fraction": float(counts.max() / len(frame))
        <= gates_spec["maximum_lineage_fraction"],
        "every_lineage_in_every_year": int(by_year.min().min())
        >= gates_spec["minimum_lineage_count_per_year"],
        "neighbor_assignment_agreement": agreement
        >= gates_spec["minimum_neighbor_assignment_agreement"],
        "canonical_minvol_passed_all": bool(
            (frame.minimum_volume_ratio <= 0.70 + 1e-12).all()
            and (frame.minimum_volume_location <= 0.50 + 1e-12).all()
        ),
        "no_outcome_columns": not bool(base.FORBIDDEN_COLUMNS.intersection(frame.columns)),
    }
    return {
        "counts": counts.to_dict(),
        "fractions": (counts / len(frame)).to_dict(),
        "counts_by_year": by_year.to_dict(orient="index"),
        "counts_by_block": by_block.to_dict(orient="index"),
        "neighbor_assignment_agreement": agreement,
        "events_with_tied_minimum_volume": int((frame.minimum_volume_tie_count > 1).sum()),
        "rejected_recovery_axis_counts": frame.recovered_above_anchor_close.value_counts().sort_index().to_dict(),
        "gates": gates,
        "decision": "FREEZE_LINEAGE" if all(gates.values()) else "REJECT_BEFORE_OUTCOME",
    }


def render_report(audit: dict[str, Any], freeze_id: str) -> str:
    lines = [
        "# EXP-OBL-015 outcome-blind minimum-volume support freeze",
        "",
        f"Decision: `{audit['decision']}`.",
        "",
        f"LINEAGE_FREEZE_ID: `{freeze_id}`.",
        "",
        "| Neutral support lineage | Count |",
        "|---|---:|",
    ]
    lines.extend(f"| {name} | {count} |" for name, count in sorted(audit["counts"].items()))
    lines.extend(
        [
            "",
            f"Low-support/close-support neighboring agreement: `{audit['neighbor_assignment_agreement']:.6f}`.",
            "",
            "The recovery axis was removed only because outcome-blind EXP-OBL-014 showed structural class collapse; it is not part of this lineage and cannot be promoted later.",
            "",
            "No post-entry outcome was read. No strategy rule is authorized.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    spec, identities = validate_spec_and_inputs()
    events = base.source.load_identities()
    history, history_audit = base.build_history(events)
    base.volumes_in_signal_coordinate = corrected.volumes_in_signal_coordinate
    frame = refine_assignments(base.build_features(history))
    audit = construction_audit(frame, spec)
    if not all(audit["gates"].values()):
        raise MinVolSupportFreezeError(f"frozen construction gates failed: {audit}")
    feature_columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_signal_date",
        "entry_year",
        "available_at_timestamp",
        "daily_snapshot_id",
        "minimum_volume_index_0_29",
        "sessions_since_minimum_volume",
        "minimum_volume_tie_count",
        "minimum_volume_ratio",
        "minimum_volume_location",
        "anchor_close",
        "anchor_low",
        "post_anchor_min_close_log_distance",
        "post_anchor_min_low_log_distance",
        "low_support_held",
        "close_support_held_neighbor",
    ]
    assignment_columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_signal_date",
        "entry_year",
        "support_lineage_id",
        "neighbor_support_lineage_id",
    ]
    base.source.atomic_csv(FEATURES, frame[feature_columns])
    base.source.atomic_csv(ASSIGNMENTS, frame[assignment_columns])
    feature_sha = base.source.sha256_file(FEATURES)
    assignment_sha = base.source.sha256_file(ASSIGNMENTS)
    freeze_id = f"LINEAGE-OBL-015-{assignment_sha[:16].upper()}"
    audit.update(
        {
            "experiment_id": "EXP-OBL-015",
            "hypothesis_id": "H-OBL-011",
            "outcome_blind_refinement_of": "EXP-OBL-014",
            "refinement": "remove structurally collapsed recovery axis; preserve canonical anchor and support definitions",
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
        "experiment_id": "EXP-OBL-015",
        "hypothesis_id": "H-OBL-011",
        "outcome_blind_refinement_of": "EXP-OBL-014",
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
