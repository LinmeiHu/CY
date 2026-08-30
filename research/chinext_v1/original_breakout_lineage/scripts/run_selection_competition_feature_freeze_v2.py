#!/usr/bin/env python3
"""Clean EXP-OBL-009 reexecution of the unchanged selection construction."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

import sys

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/original_breakout_lineage"
SCRIPTS = WORK / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_selection_competition_feature_freeze as base  # noqa: E402

SPEC = WORK / "experiments/EXP-OBL-009_spec.json"
OUTPUT_TABLE = WORK / "artifacts/selection_competition_features_v2.csv"
OUTPUT_AUDIT = WORK / "artifacts/EXP-OBL-009_audit.json"
LINEAGE_FREEZE = WORK / "lineage_freezes/LINEAGE-OBL-009.json"
REPORT = WORK / "reports/EXP-OBL-009_selection_competition_freeze.md"


class SelectionFreezeV2Error(RuntimeError):
    """Raised when a fresh binding or unchanged construction gate fails."""


def validate_spec_and_inputs() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-OBL-009":
        raise SelectionFreezeV2Error("unexpected experiment identity")
    if spec.get("status") != "FROZEN_BEFORE_EVENT_REPLAY":
        raise SelectionFreezeV2Error("selection experiment is not frozen")
    if spec.get("outcome_access") is not False:
        raise SelectionFreezeV2Error("outcome prohibition changed")
    identities: dict[str, str] = {}
    mismatches: dict[str, dict[str, str]] = {}
    for role, binding in spec["input_bindings"].items():
        path = base.resolve_path(binding["path"])
        if not path.is_file():
            raise SelectionFreezeV2Error(f"missing bound input: {role}: {path}")
        actual = base.sha256_file(path)
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatches[role] = {"expected": binding["sha256"], "actual": actual}
    if mismatches:
        raise SelectionFreezeV2Error(f"frozen input mismatch: {mismatches}")
    base.daily_base.phase2.validate_inputs()
    cy006 = base.daily_base.inventory_files(
        base.daily_base.CY006_INVENTORY,
        [f"partition_year={year}/data_0.parquet" for year in range(2018, 2026)],
    )
    if len(cy006) != 8:
        raise SelectionFreezeV2Error("CY-006 partition count changed")
    return spec, identities


def render_report(audit: dict[str, Any], freeze_id: str) -> str:
    feature = audit["feature_audit"]
    return (
        "# EXP-OBL-009 outcome-blind selection-lineage freeze\n\n"
        f"LINEAGE_FREEZE_ID: `{freeze_id}`.\n\n"
        f"Lineage counts: `{feature['lineage_counts']}`.\n\n"
        "This clean reexecution preserves the exact EXP-OBL-008 capacity "
        "boundary, assignments, event-only access, population, and context. Only "
        "the outcome-blind balance gates changed from 50/85% to 40/90%.\n\n"
        "No outcome, NAV, execution, summary, report, or source-worktree ledger was "
        "read. The neutral IDs encode no favorable outcome meaning and authorize no "
        "strategy rule or CY-011 access.\n"
    )


def main() -> None:
    spec, identities = validate_spec_and_inputs()
    replay_spec = base.extended.load_replay_spec()
    with tempfile.TemporaryDirectory(prefix="obl-selection-freeze-v2-") as raw_temporary:
        temporary = Path(raw_temporary)
        transient = temporary / "extended_inputs"
        prepared = base.extended.materialize_transient_inputs(transient)
        base.extended.validate_prepared_manifest(prepared, replay_spec)
        records: list[dict[str, Any]] = []
        replay_audit: list[dict[str, Any]] = []
        for block in base.BLOCKS:
            events, block_audit = base.run_block(block, temporary / "runs", transient)
            records.extend(base.selection_records(str(block["name"]), events))
            replay_audit.append(block_audit)
    reconstructed = pd.DataFrame(records)
    projected = base.load_identity_projection()
    frame = projected.merge(
        reconstructed,
        on=["baseline_block", "symbol", "entry_signal_date"],
        how="left",
        validate="one_to_one",
    )
    feature_columns = [
        "candidate_count",
        "vacancies_before_selection",
        "selection_pressure",
        "selected_rank",
        "selected_rank_percentile",
        "selected_rs_score",
        "selection_lineage_id",
    ]
    if frame[feature_columns].isna().any().any():
        missing = frame.loc[frame[feature_columns].isna().any(axis=1), "trade_id"].tolist()
        raise SelectionFreezeV2Error(
            f"accepted identity lacks selection context: {missing[:10]}"
        )
    frame["entry_year"] = frame.entry_signal_date.str[:4].astype(int)
    frame = frame.sort_values("trade_id").reset_index(drop=True)
    feature_audit = base.audit_features(frame, spec)
    base.atomic_csv(OUTPUT_TABLE, frame)
    table_sha = base.sha256_file(OUTPUT_TABLE)
    freeze_id = f"LINEAGE-OBL-009-{table_sha[:16].upper()}"
    audit = {
        "experiment_id": "EXP-OBL-009",
        "hypothesis_id": "H-OBL-007",
        "status": "FROZEN_OUTCOME_BLIND_SELECTION_LINEAGE",
        "lineage_freeze_id": freeze_id,
        "scientific_definitions_changed_from_exp_obl_008": False,
        "construction_gate_change_only": {
            "minimum_lineage_size": [50, 40],
            "maximum_lineage_fraction": [0.85, 0.90],
        },
        "outcome_columns_read": [],
        "performance_files_read": [],
        "population": {
            "events": len(frame),
            "years": sorted(frame.entry_year.unique().tolist()),
        },
        "feature_audit": feature_audit,
        "replay_audit": replay_audit,
        "feature_table_sha256": table_sha,
        "input_identities": identities,
        "available_at_timestamp": "signal session 15:30 Asia/Shanghai",
        "potential_action_timestamp": "T+1 open or later",
    }
    base.atomic_write(
        OUTPUT_AUDIT,
        json.dumps(base.clean_json(audit), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
    )
    manifest = {
        "schema_version": "1.0.0",
        "lineage_freeze_id": freeze_id,
        "experiment_id": "EXP-OBL-009",
        "status": "FROZEN_BEFORE_OUTCOME_JOIN",
        "spec_path": str(SPEC.relative_to(ROOT)),
        "spec_sha256": base.sha256_file(SPEC),
        "runner_path": str(Path(__file__).resolve().relative_to(ROOT)),
        "runner_sha256": base.sha256_file(Path(__file__).resolve()),
        "feature_table": str(OUTPUT_TABLE.relative_to(ROOT)),
        "feature_table_sha256": table_sha,
        "audit_path": str(OUTPUT_AUDIT.relative_to(ROOT)),
        "audit_sha256": base.sha256_file(OUTPUT_AUDIT),
        "lineage_ids": ["L_CONTESTED", "L_UNCONTESTED"],
        "outcome_access_before_freeze": False,
        "outcome_columns_read": [],
        "performance_files_read": [],
    }
    base.atomic_write(
        LINEAGE_FREEZE,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    base.atomic_write(REPORT, render_report(audit, freeze_id))
    print(json.dumps(base.clean_json(audit), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
