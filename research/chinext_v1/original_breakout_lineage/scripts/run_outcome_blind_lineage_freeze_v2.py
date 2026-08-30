#!/usr/bin/env python3
"""Clean EXP-OBL-002 execution of the frozen outcome-blind lineage contract."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/original_breakout_lineage"
SCRIPTS = WORK / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_outcome_blind_lineage_freeze as base  # noqa: E402

SPEC = WORK / "experiments/EXP-OBL-002_spec.json"
FEATURE_TABLE = WORK / "artifacts/formation_features_v2.csv"
ASSIGNMENT_TABLE = WORK / "artifacts/lineage_assignments_v2.csv"
AUDIT_JSON = WORK / "artifacts/EXP-OBL-002_audit.json"
FREEZE_MANIFEST = WORK / "lineage_freezes/LINEAGE-OBL-002.json"
REPORT = WORK / "reports/EXP-OBL-002_outcome_blind_lineage_freeze.md"


def validate_spec_and_inputs() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-OBL-002":
        raise base.LineageFreezeError("unexpected experiment identity")
    if spec.get("status") != "FROZEN_BEFORE_OUTCOME_REVEAL":
        raise base.LineageFreezeError("experiment is not frozen before outcome reveal")
    if spec.get("outcome_access") is not False:
        raise base.LineageFreezeError("outcome access prohibition changed")
    identities: dict[str, str] = {}
    mismatches: dict[str, dict[str, str]] = {}
    for role, binding in spec["input_bindings"].items():
        path = base.resolve_path(binding["path"])
        if not path.is_file():
            raise base.LineageFreezeError(f"missing bound input: {role}: {path}")
        actual = base.sha256_file(path)
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatches[role] = {"expected": binding["sha256"], "actual": actual}
    if mismatches:
        raise base.LineageFreezeError(f"frozen input mismatch: {mismatches}")
    base.phase2.validate_inputs()
    return spec, identities


def render_report(audit: dict[str, Any], freeze_id: str) -> str:
    return base.render_report(audit, freeze_id).replace("EXP-OBL-001", "EXP-OBL-002")


def main() -> None:
    spec, bound_identities = validate_spec_and_inputs()
    identities = base.load_identities()
    years = list(range(2018, 2026))
    cy006 = base.inventory_files(
        base.CY006_INVENTORY,
        [f"partition_year={year}/data_0.parquet" for year in years],
    )
    qd004 = base.inventory_files(
        base.QD004_INVENTORY,
        [f"bars/{year}_day_parquet_none.parquet" for year in years],
    )
    cy008 = base.inventory_files(
        base.CY008_INVENTORY,
        [
            path
            for year in years
            for path in (
                f"daily/partition_year={year}/data_0.parquet",
                f"execution_5m/partition_year={year}/data_0.parquet",
            )
        ],
    )
    cross_audit = json.loads(base.CY008_AUDIT.read_text(encoding="utf-8"))
    if cross_audit.get("pass") is not True or not all(
        cross_audit.get("checks", {}).values()
    ):
        raise base.LineageFreezeError("CY-008 cross-year audit is not PASS")
    if len(cy006) != 8:
        raise base.LineageFreezeError("CY-006 required partition count changed")

    history, daily_audit = base.build_daily_history(identities)
    daily = base.daily_features(history)
    intraday, intraday_audit = base.build_intraday_features(
        identities, daily, qd004, cy008
    )
    features = identities.merge(daily, on="trade_id", validate="one_to_one")
    features = features.merge(intraday, on="trade_id", validate="one_to_one")
    features, lineage_audit = base.construct_lineages(features, spec)
    if base.FORBIDDEN_COLUMNS.intersection(features.columns):
        raise base.LineageFreezeError("outcome columns entered final feature table")

    feature_columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_signal_date",
        "entry_execution_date",
        "entry_year",
        "feature_available_at",
        "daily_available_at",
        "daily_snapshot_id",
        "minute_snapshot_id",
        "minute_daily_snapshot_id",
        "entry_industry",
        "breakout_reference_raw",
        "breakout_margin",
        "support_shift20",
        "resistance_shift20",
        "range_contraction20",
        "volatility_contraction20",
        "downside_amount_contraction20",
        "prior60_reference_test_count_2pct",
        "sessions_since_reference",
        "prebreakout_distance",
        "first_cross_index",
        "time_above_reference",
        "volume_above_reference",
        "reference_loss_count",
        "longest_below_reference_run",
        "below_reference_resilience",
        "close_reference_retention",
        "postcross_max_drawdown",
        "base_repair_score",
        "breakout_acceptance_score",
        "base_neighbor_score",
        "acceptance_neighbor_5m_score",
        "assignment_margin",
        "lineage_id",
        "neighbor_lineage_id",
    ]
    assignment_columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_signal_date",
        "entry_execution_date",
        "entry_year",
        "feature_available_at",
        "lineage_id",
        "neighbor_lineage_id",
        "base_repair_score",
        "breakout_acceptance_score",
        "assignment_margin",
    ]
    feature_output = features[feature_columns].sort_values("trade_id").reset_index(drop=True)
    assignment_output = features[assignment_columns].sort_values("trade_id").reset_index(drop=True)
    base.atomic_csv(FEATURE_TABLE, feature_output)
    base.atomic_csv(ASSIGNMENT_TABLE, assignment_output)
    feature_sha = base.sha256_file(FEATURE_TABLE)
    assignment_sha = base.sha256_file(ASSIGNMENT_TABLE)
    input_aggregate = hashlib.sha256(
        "\n".join(
            f"{path}:{digest}" for path, digest in sorted(bound_identities.items())
        ).encode()
    ).hexdigest()
    freeze_id = f"LINEAGE-OBL-002-{assignment_sha[:16].upper()}"
    audit = {
        "experiment_id": "EXP-OBL-002",
        "hypothesis_id": "H-OBL-002",
        "status": "FROZEN_OUTCOME_BLIND_LINEAGES",
        "lineage_freeze_id": freeze_id,
        "outcome_columns_read": [],
        "population": {
            "events": len(features),
            "unique_trade_ids": int(features.trade_id.nunique()),
            "date_min": features.entry_signal_date.min().date().isoformat(),
            "date_max": features.entry_signal_date.max().date().isoformat(),
            "years": sorted(features.entry_year.unique().astype(int).tolist()),
        },
        "daily": {
            **daily_audit,
            "history_rows": len(history),
            "maximum_breakout_margin_coordinate_error": daily.attrs[
                "maximum_breakout_margin_error"
            ],
        },
        "intraday": intraday_audit,
        "lineage": lineage_audit,
        "artifact_hashes": {
            str(FEATURE_TABLE.relative_to(ROOT)): feature_sha,
            str(ASSIGNMENT_TABLE.relative_to(ROOT)): assignment_sha,
        },
        "bound_input_hashes": bound_identities,
        "bound_input_aggregate_sha256": input_aggregate,
        "available_at_timestamp": "entry signal session 15:30 Asia/Shanghai",
        "potential_action_timestamp": "entry execution T+1 open or later",
        "interpretation": "neutral structural taxonomy; no outcome meaning assigned",
    }
    base.atomic_write(
        AUDIT_JSON,
        json.dumps(base.clean_json(audit), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
    )
    freeze_manifest = {
        "schema_version": "1.0.0",
        "lineage_freeze_id": freeze_id,
        "experiment_id": "EXP-OBL-002",
        "status": "FROZEN_BEFORE_OUTCOME_REVEAL",
        "spec_path": str(SPEC.relative_to(ROOT)),
        "spec_sha256": base.sha256_file(SPEC),
        "runner_path": str(Path(__file__).resolve().relative_to(ROOT)),
        "runner_sha256": base.sha256_file(Path(__file__).resolve()),
        "feature_table": str(FEATURE_TABLE.relative_to(ROOT)),
        "feature_table_sha256": feature_sha,
        "assignment_table": str(ASSIGNMENT_TABLE.relative_to(ROOT)),
        "assignment_table_sha256": assignment_sha,
        "audit_path": str(AUDIT_JSON.relative_to(ROOT)),
        "audit_sha256": base.sha256_file(AUDIT_JSON),
        "lineage_ids": sorted(base.LINEAGE_NAMES.values()),
        "outcome_access_before_freeze": False,
        "outcome_columns_read": [],
        "immutable_scientific_elements": spec["immutable_scientific_elements"],
    }
    base.atomic_write(
        FREEZE_MANIFEST,
        json.dumps(freeze_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    base.atomic_write(REPORT, render_report(audit, freeze_id))
    print(json.dumps(base.clean_json(audit), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
