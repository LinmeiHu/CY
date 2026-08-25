#!/usr/bin/env python3
"""Register action-coordinate and placebo-identifiability corrections."""

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

ROOT = Path("output/chip_incremental_validation_v1")
PROTOCOL = ROOT / "protocol_manifest.json"
PRIOR = ROOT / "addenda/addendum_04_manifest.json"
DOCUMENT = Path("docs/CHIP_INCREMENTAL_VALIDATION_PROTOCOL_V1_ADDENDUM_05.md")
MANIFEST = ROOT / "addenda/addendum_05_manifest.json"
LEDGER = ROOT / "trials/events.jsonl"


def main() -> int:
    protocol_path = PROTOCOL.resolve()
    prior_path = PRIOR.resolve()
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
        raise ValueError("identifiability correction requires the blind protocol chain")
    identity = {
        "protocol_event_id": protocol["event_id"],
        "protocol_manifest_sha256": _sha256(protocol_path),
        "prior_addendum_event_id": prior["event_id"],
        "prior_addendum_manifest_sha256": _sha256(prior_path),
        "addendum_id": "CHIP_INCREMENTAL_VALIDATION_V1_ADDENDUM_05",
        "addendum_document_sha256": _sha256(document_path),
    }
    event_id = hashlib.sha256(_canonical(identity).encode()).hexdigest()
    payload: dict[str, Any] = {
        "schema_version": 1,
        "status": "PREREGISTERED_IDENTIFIABILITY_CORRECTION_BEFORE_OUTCOMES",
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
            "cost_coordinate": {
                "share_product": "CUMULATIVE_PRODUCT_SHARE_MULTIPLIER",
                "cash_base": "CUMULATIVE_SUM_CASH_PER_SHARE_TIMES_PRIOR_SHARE_PRODUCT",
                "economic_cost": "RAW_COST_TIMES_SHARE_PRODUCT_PLUS_CASH_BASE",
            },
            "informative_pair_definition": (
                "SCORE_SWAP_CHANGES_AT_LEAST_ONE_Q1_OR_Q5_MEMBERSHIP"
            ),
            "minimum_informative_swappable_rows": 396,
            "minimum_informative_distinct_weeks": 52,
            "minimum_informative_distinct_weeks_per_fold": 20,
            "insufficient_action": "INSUFFICIENT_EVIDENCE",
            "permutations_unchanged": 199,
            "familywise_method_unchanged": "HOLM_0.05",
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
        "CHIP_INCREMENTAL_VALIDATION_V1_ADDENDUM_05",
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
            raise ValueError("identifiability-addendum ledger collision")
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
            raise FileExistsError(f"immutable identifiability addendum differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw, encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


if __name__ == "__main__":
    raise SystemExit(main())
