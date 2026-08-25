#!/usr/bin/env python3
"""Append the accidental 2023 metadata-only file access to the trial ledger."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from cyq_game.strategy.ledger import TrialLedger
from cyq_game.strategy.markup_retest import MarkupRetestConfig, StrategyStage

EVENT_TYPE = "HOLDOUT_ACCESS_INCIDENT"
ACCESSED_PATH = Path(
    "data/registered_inputs/"
    "CY-019-MARKUP-RETEST-MAIN-CHINEXT-2020-2023-V11/lineage/"
    "year=2023/parts/bucket=2/300257_SZ.parquet"
)


def main() -> int:
    config = MarkupRetestConfig.load(
        "configs/markup_retest_main_chinext_2020_2023_v1.yaml"
    )
    ledger = TrialLedger(config.trial_ledger)
    incident_identity = "|".join(
        (
            EVENT_TYPE,
            config.sha256,
            str(ACCESSED_PATH.resolve()),
            "PYARROW_READ_TABLE_SCHEMA_ROW_COUNT_DIAGNOSTIC",
        )
    )
    payload: dict[str, Any] = {
        "event_id": hashlib.sha256(incident_identity.encode()).hexdigest(),
        "status": "CONTAINED_AUDIT_RECORDED",
        "config_sha256": config.sha256,
        "accessed_path": str(ACCESSED_PATH.resolve()),
        "accessed_file_bytes": ACCESSED_PATH.stat().st_size,
        "access_mechanism": "PYARROW_READ_TABLE_SCHEMA_ROW_COUNT_DIAGNOSTIC",
        "observed_output": {
            "row_count": 726,
            "schema_column_names": True,
            "file_presence_and_size": True,
            "cell_values_printed": False,
            "returns_or_labels_printed": False,
            "signals_or_strategy_metrics_printed": False,
        },
        "holdout_accessed": True,
        "holdout_outcomes_observed": False,
        "used_for_parameter_selection_or_thresholds": False,
        "freeze_performed": False,
        "formal_2023_untouched_claim_allowed": False,
        "development_scope": "2020-2022_ONLY",
        "development_evidence_invalidated": False,
        "containment": [
            "STOP_UNBOUNDED_GLOB_DIAGNOSTIC",
            "FORBID_FURTHER_2023_INPUT_READS_BEFORE_DEVELOPMENT_FREEZE",
            "DO_NOT_USE_2023_METADATA_FOR_PARAMETER_SELECTION",
            "DISCLOSE_INCIDENT_IN_FINAL_REPORT",
        ],
        "recovery_policy": (
            "Continue preregistered 2020-2022 development only. The 2023 interval "
            "may not be described as physically untouched; no 2023 outcome was "
            "observed or used for tuning."
        ),
    }
    entry = _append_idempotent(ledger, payload)
    report = {
        "schema_version": 1,
        "event_type": EVENT_TYPE,
        "ledger_sequence": entry.sequence,
        "payload": payload,
    }
    target = (
        config.outputs.validation_root
        / StrategyStage.DEVELOPMENT.value
        / config.sha256[:12]
        / "holdout_access_incident_20260824.json"
    )
    _write_immutable(target, report)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "ledger_sequence": entry.sequence,
                "holdout_accessed": True,
                "holdout_outcomes_observed": False,
                "used_for_parameter_selection_or_thresholds": False,
                "manifest": str(target.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _append_idempotent(
    ledger: TrialLedger, payload: Mapping[str, Any]
):
    for entry in ledger.read_verified():
        if entry.payload.get("event_id") != payload["event_id"]:
            continue
        if entry.event_type != EVENT_TYPE or entry.payload != payload:
            raise ValueError("holdout incident event_id collision")
        return entry
    return ledger.append(EVENT_TYPE, payload)


def _write_immutable(path: Path, payload: Mapping[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != raw:
            raise FileExistsError(f"immutable incident manifest differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
