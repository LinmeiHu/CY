#!/usr/bin/env python3
"""Register fixed primitive and module formulas before outcome access."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from cyq_game.strategy.ledger import (  # type: ignore[import-untyped]
    LedgerEntry,
    TrialLedger,
)

PROTOCOL = Path("output/chip_incremental_validation_v1/protocol_manifest.json")
ADDENDUM_01 = Path(
    "output/chip_incremental_validation_v1/addenda/addendum_01_manifest.json"
)
DOCUMENT = Path("docs/CHIP_INCREMENTAL_VALIDATION_PROTOCOL_V1_ADDENDUM_02.md")
MANIFEST = Path(
    "output/chip_incremental_validation_v1/addenda/addendum_02_manifest.json"
)
LEDGER = Path("output/chip_incremental_validation_v1/trials/events.jsonl")


def main() -> int:
    protocol_path = PROTOCOL.resolve()
    prior_path = ADDENDUM_01.resolve()
    document_path = DOCUMENT.resolve()
    manifest_path = MANIFEST.resolve()
    protocol = _object(protocol_path)
    prior = _object(prior_path)
    if (
        protocol.get("status") != "PREREGISTERED"
        or protocol.get("holdout_outcomes_observed") is not False
        or prior.get("protocol_event_id") != protocol.get("event_id")
        or prior.get("holdout_outcomes_observed") is not False
    ):
        raise ValueError("feature addendum requires the outcome-blind protocol chain")
    identity = {
        "protocol_event_id": protocol["event_id"],
        "protocol_manifest_sha256": _sha256(protocol_path),
        "prior_addendum_event_id": prior["event_id"],
        "prior_addendum_manifest_sha256": _sha256(prior_path),
        "addendum_id": "CHIP_INCREMENTAL_VALIDATION_V1_ADDENDUM_02",
        "addendum_document_sha256": _sha256(document_path),
        "scope": "FIXED_PRIMITIVES_MODULE_COMPOSITE_AND_STALE_CONTROL",
    }
    event_id = hashlib.sha256(_canonical(identity).encode()).hexdigest()
    payload: dict[str, Any] = {
        "schema_version": 1,
        "status": "PREREGISTERED_FEATURE_FORMULAS_BEFORE_OUTCOMES",
        "event_id": event_id,
        **identity,
        "protocol_manifest": str(protocol_path),
        "prior_addendum_manifest": str(prior_path),
        "addendum_document": str(document_path),
        "outcome_values_observed_before_registration": False,
        "holdout_accessed": False,
        "holdout_outcomes_observed": False,
        "maximum_input_date": "2022-12-30",
        "fixed_contract": {
            "known_cost_fraction_minimum": 0.95,
            "seller_model_disagreement_training_quantile_maximum": 0.80,
            "module_weights": "EQUAL_THREE_WAY",
            "module_transform": "DIRECTION_ALIGNED_TRAINING_ECDF",
            "stale_sessions": 20,
            "stale_must_be_strictly_weaker": True,
            "primitive_direction_passes_required": 2,
        },
    }
    _write(manifest_path, payload)
    event_payload = {
        "event_id": event_id,
        "addendum_id": identity["addendum_id"],
        "addendum_manifest": str(manifest_path),
        "addendum_manifest_sha256": _sha256(manifest_path),
        "protocol_event_id": protocol["event_id"],
        "outcome_values_observed_before_registration": False,
        "holdout_accessed": False,
        "holdout_outcomes_observed": False,
        "development_scope": "2020-2022_ONLY",
    }
    entry = _append_once(
        TrialLedger(LEDGER.resolve()),
        "CHIP_INCREMENTAL_VALIDATION_V1_ADDENDUM_02",
        event_payload,
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "event_id": event_id,
                "ledger_sequence": entry.sequence,
                "holdout_accessed": False,
            },
            indent=2,
        )
    )
    return 0


def _append_once(
    ledger: TrialLedger, event_type: str, payload: Mapping[str, Any]
) -> LedgerEntry:
    for entry in ledger.read_verified():
        if entry.payload.get("event_id") != payload["event_id"]:
            continue
        if entry.event_type != event_type or entry.payload != payload:
            raise ValueError("feature-addendum ledger collision")
        return entry
    return ledger.append(event_type, payload)


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return value


def _write(path: Path, value: Mapping[str, Any]) -> None:
    raw = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != raw:
            raise FileExistsError(f"immutable feature addendum differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw, encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


if __name__ == "__main__":
    raise SystemExit(main())
