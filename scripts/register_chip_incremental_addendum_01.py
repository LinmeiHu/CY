#!/usr/bin/env python3
"""Register the outcome-blind correction to the price-volume cohort."""

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

PROTOCOL_MANIFEST = Path(
    "output/chip_incremental_validation_v1/protocol_manifest.json"
)
ADDENDUM_DOCUMENT = Path(
    "docs/CHIP_INCREMENTAL_VALIDATION_PROTOCOL_V1_ADDENDUM_01.md"
)
ADDENDUM_MANIFEST = Path(
    "output/chip_incremental_validation_v1/addenda/addendum_01_manifest.json"
)
TRIAL_LEDGER = Path("output/chip_incremental_validation_v1/trials/events.jsonl")


def main() -> int:
    protocol_path = PROTOCOL_MANIFEST.resolve()
    document_path = ADDENDUM_DOCUMENT.resolve()
    manifest_path = ADDENDUM_MANIFEST.resolve()
    protocol = _read_object(protocol_path)
    if (
        protocol.get("status") != "PREREGISTERED"
        or protocol.get("holdout_accessed") is not False
        or protocol.get("holdout_outcomes_observed") is not False
    ):
        raise ValueError("addendum requires an outcome-blind preregistered protocol")
    identity = {
        "protocol_event_id": protocol["event_id"],
        "protocol_manifest_sha256": _sha256(protocol_path),
        "addendum_id": "CHIP_INCREMENTAL_VALIDATION_V1_ADDENDUM_01",
        "addendum_document_sha256": _sha256(document_path),
        "scope": "PRICE_VOLUME_CANDIDATE_SEMANTIC_CORRECTION_ONLY",
    }
    event_id = hashlib.sha256(_canonical(identity).encode()).hexdigest()
    payload: dict[str, Any] = {
        "schema_version": 1,
        "status": "PREREGISTERED_CORRECTION_BEFORE_OUTCOMES",
        "event_id": event_id,
        **identity,
        "protocol_manifest": str(protocol_path),
        "addendum_document": str(document_path),
        "outcome_values_observed_before_registration": False,
        "holdout_accessed": False,
        "holdout_outcomes_observed": False,
        "maximum_input_date": "2022-12-30",
        "correction": {
            "forbidden_old_fields": ["support_regained", "breakout_excess_atr"],
            "price_resistance_lookback_sessions": 60,
            "breakout_to_retest_min_sessions": 1,
            "breakout_to_retest_max_sessions": 10,
            "breakout_excess_atr_minimum": 0.25,
            "support_tolerance_atr": 0.25,
            "cooldown_sessions": 20,
            "market_and_sector_state_threshold": 0.02,
        },
    }
    _write_immutable(manifest_path, payload)
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
        TrialLedger(TRIAL_LEDGER.resolve()),
        "CHIP_INCREMENTAL_VALIDATION_V1_ADDENDUM_01",
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
            raise ValueError("addendum ledger event collision")
        return entry
    return ledger.append(event_type, payload)


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return value


def _write_immutable(path: Path, value: Mapping[str, Any]) -> None:
    raw = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != raw:
            raise FileExistsError(f"immutable addendum manifest differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw, encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


if __name__ == "__main__":
    raise SystemExit(main())
