#!/usr/bin/env python3
"""Preregister the chip-incremental falsification protocol before outcomes."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from cyq_game.strategy.ledger import (  # type: ignore[import-untyped]
    LedgerEntry,
    TrialLedger,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/chip_incremental_validation_v1.yaml"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("protocol config must be a mapping")
    _validate(raw)
    governance = _mapping(raw, "governance")
    document_path = Path(str(governance["protocol_document"])).resolve()
    predecessor_path = Path(
        str(_mapping(raw, "protocol")["predecessor_freeze"])
    ).resolve()
    predecessor = _read_object(predecessor_path)
    if (
        predecessor.get("status") != "FROZEN"
        or predecessor.get("freeze_decision") != "NO_TRADE"
        or predecessor.get("selected_parameter_id") is not None
        or predecessor.get("allowed_holdout_access_count") != 0
    ):
        raise ValueError("scientific protocol requires the immutable NO_TRADE predecessor")

    identity = {
        "protocol_id": _mapping(raw, "protocol")["id"],
        "config_sha256": _sha256(config_path),
        "document_sha256": _sha256(document_path),
        "predecessor_freeze_sha256": _sha256(predecessor_path),
        "maximum_input_date": _mapping(raw, "data_lock")["maximum_input_date"],
        "stage_1_outcome_runs": _mapping(raw, "sequential_budget")[
            "stage_1_outcome_runs"
        ],
    }
    event_id = hashlib.sha256(_canonical(identity).encode()).hexdigest()
    manifest = {
        "schema_version": 1,
        "status": "PREREGISTERED",
        "event_id": event_id,
        **identity,
        "config_path": str(config_path),
        "document_path": str(document_path),
        "predecessor_freeze": str(predecessor_path),
        "predecessor_freeze_snapshot_id": predecessor["freeze_snapshot_id"],
        "predecessor_unchanged": True,
        "holdout_accessed": False,
        "holdout_outcomes_observed": False,
        "global_physical_2023_access_incident": True,
        "protocol": raw,
    }
    manifest_path = Path(str(governance["protocol_manifest"])).resolve()
    _write_immutable(manifest_path, manifest)
    event_payload = {
        "event_id": event_id,
        "protocol_id": identity["protocol_id"],
        "protocol_manifest": str(manifest_path),
        "protocol_manifest_sha256": _sha256(manifest_path),
        "predecessor_freeze_snapshot_id": predecessor["freeze_snapshot_id"],
        "predecessor_decision": "NO_TRADE",
        "separate_research_line": True,
        "development_scope": "2020-2022_ONLY",
        "new_outcome_values_observed_before_registration": False,
        "holdout_accessed": False,
        "holdout_outcomes_observed": False,
        "global_physical_2023_access_incident": True,
    }
    new_ledger = TrialLedger(Path(str(governance["trial_ledger"])).resolve())
    new_entry = _append_once(
        new_ledger, "CHIP_INCREMENTAL_VALIDATION_PROTOCOL_V1", event_payload
    )
    predecessor_ledger = TrialLedger(
        predecessor_path.parent / "trials" / "events.jsonl"
    )
    cross_entry = _append_once(
        predecessor_ledger,
        "SEPARATE_CHIP_INCREMENTAL_RESEARCH_LINE_OPENED",
        event_payload,
    )
    print(
        json.dumps(
            {
                "status": "PREREGISTERED",
                "event_id": event_id,
                "new_ledger_sequence": new_entry.sequence,
                "predecessor_ledger_sequence": cross_entry.sequence,
                "holdout_accessed": False,
            },
            indent=2,
        )
    )
    return 0


def _validate(raw: Mapping[str, Any]) -> None:
    protocol = _mapping(raw, "protocol")
    data_lock = _mapping(raw, "data_lock")
    outcome = _mapping(raw, "outcome")
    gates = _mapping(raw, "selection_gates")
    budget = _mapping(raw, "sequential_budget")
    if protocol.get("id") != "CHIP_INCREMENTAL_VALIDATION_PROTOCOL_V1":
        raise ValueError("unexpected protocol id")
    if protocol.get("predecessor_decision_required") != "NO_TRADE":
        raise ValueError("predecessor decision must remain NO_TRADE")
    if data_lock.get("maximum_input_date") != "2022-12-30":
        raise ValueError("protocol must fail closed before 2023")
    if data_lock.get("holdout_outcomes_may_be_read") is not False:
        raise ValueError("holdout outcomes must remain locked")
    if outcome.get("primary") != "EXACT_FIXED_20_SESSION_NET_RETURN":
        raise ValueError("stage 1 must use a fixed outcome")
    if int(gates.get("deterministic_within_stratum_placebos", 0)) != 199:
        raise ValueError("placebo budget changed")
    if int(budget.get("stage_1_outcome_runs", 0)) != 1:
        raise ValueError("stage 1 must have exactly one outcome run")
    if int(budget.get("stage_2_maximum_threshold_variants", 0)) > 12:
        raise ValueError("stage 2 threshold budget exceeds preregistered maximum")


def _append_once(
    ledger: TrialLedger, event_type: str, payload: Mapping[str, Any]
) -> LedgerEntry:
    for entry in ledger.read_verified():
        if entry.payload.get("event_id") != payload["event_id"]:
            continue
        if entry.event_type != event_type or entry.payload != payload:
            raise ValueError("protocol ledger event collision")
        return entry
    return ledger.append(event_type, payload)


def _mapping(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"protocol section {key!r} must be a mapping")
    return value


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return value


def _write_immutable(path: Path, value: Mapping[str, Any]) -> None:
    raw = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != raw:
            raise FileExistsError(f"immutable protocol manifest differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw, encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


if __name__ == "__main__":
    raise SystemExit(main())
