#!/usr/bin/env python3
"""Freeze the NO_TRADE prospective shadow contract after current data activation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from cyq_game.data.registry import DataAssetRegistry, DataOperation, InputSnapshotManifest
from cyq_game.strategy.ledger import TrialLedger

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_CONFIG = ROOT / "configs/chip_mechanism_interaction_v1.json"
PROTOCOL_MANIFEST = ROOT / "output/chip_mechanism_interaction_v1/protocol_manifest.json"
TRAINING_MANIFEST = (
    ROOT / "output/chip_mechanism_interaction_v1/training_v1/manifest.json"
)
TRAINING_DECISION = (
    ROOT
    / "output/chip_mechanism_interaction_v1/training_v1/robust_region_decision.json"
)
LEDGER = ROOT / "output/chip_incremental_validation_v1/trials/events.jsonl"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-snapshot", type=Path, required=True)
    parser.add_argument(
        "--registry", type=Path, default=ROOT / "configs/data_asset_registry.json"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "configs/chip_mechanism_interaction_shadow_v1.json",
    )
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def main() -> int:
    args = _parse_args()
    protocol_config = _read(PROTOCOL_CONFIG)
    protocol = _read(PROTOCOL_MANIFEST)
    training = _read(TRAINING_MANIFEST)
    decision = _read(TRAINING_DECISION)
    if protocol.get("config_sha256") != _sha256(PROTOCOL_CONFIG):
        raise ValueError("preregistered protocol config changed")
    if training.get("status") != "COMPLETE" or training.get("decision") != "NO_TRADE":
        raise ValueError("training result is not a completed NO_TRADE decision")
    if decision.get("selected_parameter_id") is not None:
        raise ValueError("NO_TRADE shadow cannot carry a selected parameter")
    if training.get("2023_or_later_accessed") is not False:
        raise ValueError("training selection accessed forbidden years")
    registry_path = args.registry.resolve()
    registry = DataAssetRegistry.load(registry_path)
    snapshot = InputSnapshotManifest.load(args.input_snapshot.resolve(), registry=registry)
    snapshot.authorize(DataOperation.STATE_GENERATION, registry=registry)
    event_id = hashlib.sha256(
        (
            f"{training['run_id']}|{snapshot.sha256}|"
            "CHIP_MECHANISM_INTERACTION_PROSPECTIVE_SHADOW_V1"
        ).encode()
    ).hexdigest()
    payload = {
        "schema_version": 1,
        "status": "READY_FOR_PROSPECTIVE_OBSERVATION",
        "event_id": event_id,
        "protocol_id": protocol_config["protocol_id"],
        "run_id": training["run_id"],
        "training_decision": "NO_TRADE",
        "selected_parameter_id": None,
        "active_order_action": "NO_TRADE",
        "prospective_shadow_start": "2026-08-25",
        "minimum_prospective_weeks": 52,
        "registered_parameter_grid": protocol_config["mechanism_parameters"],
        "fixed_mechanism_gates": protocol_config["fixed_mechanism_gates"],
        "evaluation": protocol_config["evaluation"],
        "input_snapshot": {
            "path": str(snapshot.path),
            "sha256": snapshot.sha256,
            "manifest_id": snapshot.manifest_id,
            "scope_start": snapshot.scope_start.isoformat(),
            "scope_end": snapshot.scope_end.isoformat(),
        },
        "source_manifests": {
            "protocol": {
                "path": str(PROTOCOL_MANIFEST),
                "sha256": _sha256(PROTOCOL_MANIFEST),
            },
            "training": {
                "path": str(TRAINING_MANIFEST),
                "sha256": _sha256(TRAINING_MANIFEST),
            },
            "decision": {
                "path": str(TRAINING_DECISION),
                "sha256": _sha256(TRAINING_DECISION),
            },
        },
        "risk_contract": {
            "live_orders_enabled": False,
            "kelly_enabled": False,
            "edge_card_authorized": False,
            "parameter_changes_during_shadow_forbidden": True,
            "failed_or_missing_data_action": "NO_TRADE",
        },
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output.exists() and output.read_text(encoding="utf-8") != content:
        raise FileExistsError("existing prospective shadow contract differs")
    output.write_text(content, encoding="utf-8")
    ledger_payload = {
        "event_id": event_id,
        "run_id": training["run_id"],
        "protocol_id": protocol_config["protocol_id"],
        "config_path": str(output),
        "config_sha256": _sha256(output),
        "input_manifest_id": snapshot.manifest_id,
        "input_manifest_sha256": snapshot.sha256,
        "training_decision": "NO_TRADE",
        "selected_parameter_id": None,
        "live_orders_enabled": False,
        "kelly_enabled": False,
    }
    ledger = TrialLedger(LEDGER)
    matches = [
        entry
        for entry in ledger.read_verified()
        if entry.event_type == "CHIP_MECHANISM_INTERACTION_PROSPECTIVE_SHADOW_READY"
        and entry.payload.get("event_id") == event_id
    ]
    if matches:
        if len(matches) != 1 or dict(matches[0].payload) != ledger_payload:
            raise ValueError("conflicting prospective shadow ledger event")
    else:
        ledger.append(
            "CHIP_MECHANISM_INTERACTION_PROSPECTIVE_SHADOW_READY", ledger_payload
        )
    print(f"PASS shadow=NO_TRADE config={output} event_id={event_id}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
