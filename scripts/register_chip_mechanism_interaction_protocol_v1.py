#!/usr/bin/env python3
"""Freeze the training-only chip mechanism interaction protocol before scoring."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from cyq_game.strategy.ledger import LedgerEntry, TrialLedger

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/chip_mechanism_interaction_v1.json"
STAGE1_MANIFEST = ROOT / "output/chip_incremental_validation_v1/stage1/manifest.json"
LEDGER = ROOT / "output/chip_incremental_validation_v1/trials/events.jsonl"
OUTPUT = ROOT / "output/chip_mechanism_interaction_v1/protocol_manifest.json"
EVENT_TYPE = "CHIP_MECHANISM_INTERACTION_PROTOCOL_V1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _append_idempotent(
    ledger: TrialLedger, event_type: str, payload: dict[str, Any]
) -> LedgerEntry:
    matches = [
        entry
        for entry in ledger.read_verified()
        if entry.event_type == event_type
        and entry.payload.get("event_id") == payload["event_id"]
    ]
    if matches:
        if len(matches) != 1 or dict(matches[0].payload) != payload:
            raise ValueError("existing protocol ledger event conflicts")
        return matches[0]
    return ledger.append(event_type, payload)


def main() -> int:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    if config.get("status") != "PREREGISTRATION_PENDING":
        raise ValueError("unexpected protocol config state")
    expected_data_hash = config["data_contract"]["development_input_sha256"]
    data_path = ROOT / config["data_contract"]["development_input"]
    if _sha256(data_path) != expected_data_hash:
        raise ValueError("development evidence hash changed")
    stage1 = json.loads(STAGE1_MANIFEST.read_text(encoding="utf-8"))
    if (
        stage1.get("terminal_decision") != "NO_CHIP_INCREMENTAL_VALUE"
        or stage1.get("stage_2_authorized") is not False
        or stage1.get("maximum_physical_data_year") != 2022
    ):
        raise ValueError("predecessor Stage 1 state changed")
    config_hash = _sha256(CONFIG)
    stage1_hash = _sha256(STAGE1_MANIFEST)
    identity = (
        f"{config['protocol_id']}|{config_hash}|{stage1_hash}|{expected_data_hash}"
    )
    run_id = hashlib.sha256(identity.encode()).hexdigest()
    payload = {
        "event_id": hashlib.sha256(f"{run_id}|PROTOCOL".encode()).hexdigest(),
        "run_id": run_id,
        "protocol_id": config["protocol_id"],
        "config_path": str(CONFIG),
        "config_sha256": config_hash,
        "predecessor_stage1_manifest": str(STAGE1_MANIFEST),
        "predecessor_stage1_manifest_sha256": stage1_hash,
        "predecessor_decision": "NO_CHIP_INCREMENTAL_VALUE",
        "development_classification": "PREVIOUSLY_OBSERVED_TRAINING_ONLY",
        "development_period": ["2020-01-02", "2022-12-30"],
        "parameter_count": 27,
        "new_interaction_metrics_observed_before_registration": False,
        "holdout_accessed_by_protocol_registration": False,
        "2023_untouched_claim_allowed": False,
        "selection_uses_2023_or_later": False,
        "prospective_shadow_start": "2026-08-25",
        "promotion_before_52_prospective_weeks": "FAIL_CLOSED",
        "legal_terminal_decisions": [
            "TRAINING_CANDIDATE_PROSPECTIVE_ONLY",
            "NO_TRADE",
        ],
    }
    entry = _append_idempotent(TrialLedger(LEDGER), EVENT_TYPE, payload)
    manifest = {
        "schema_version": 1,
        "status": "PREREGISTERED",
        "protocol": config,
        "config_path": str(CONFIG),
        "config_sha256": config_hash,
        "predecessor_stage1_manifest": str(STAGE1_MANIFEST),
        "predecessor_stage1_manifest_sha256": stage1_hash,
        "ledger": {
            "path": str(LEDGER),
            "sequence": entry.sequence,
            "entry_hash": entry.entry_hash,
            "event_id": payload["event_id"],
            "run_id": run_id,
        },
    }
    serialized = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if OUTPUT.exists() and OUTPUT.read_text(encoding="utf-8") != serialized:
        raise ValueError("existing protocol manifest conflicts")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(serialized, encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
