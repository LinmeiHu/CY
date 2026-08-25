#!/usr/bin/env python3
"""Freeze the completed economic region or the preregistered NO_TRADE action."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cyq_game.strategy.ledger import LedgerEntry, TrialLedger  # type: ignore[import-untyped]
from cyq_game.strategy.markup_retest import (  # type: ignore[import-untyped]
    MarkupRetestConfig,
    StrategyParameters,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/markup_retest_main_chinext_2020_2023_v1.yaml"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = MarkupRetestConfig.load(args.config)
    ledger = TrialLedger(config.trial_ledger)
    entries = ledger.read_verified()
    completion = _one(entries, "ENTRY_ECONOMIC_SELECTION_PROTOCOL_V2_COMPLETE")
    p0 = _passing_p0(entries)
    manifest_path = Path(str(completion.payload["manifest_path"]))
    if _sha256_file(manifest_path) != completion.payload["manifest_sha256"]:
        raise ValueError("economic selection manifest identity changed")
    economic = _read_object(manifest_path)
    if (
        economic.get("status") != "COMPLETE"
        or economic.get("parameter_evaluation_count") != 81
        or economic.get("parameter_evaluation_coverage") != 1.0
        or economic.get("holdout_accessed") is not False
        or economic.get("holdout_outcomes_observed") is not False
        or economic.get("parameters_frozen") is not False
    ):
        raise ValueError("economic selection is not eligible for freeze")
    decision = str(economic["terminal_decision"])
    if decision not in {"PASS", "NO_TRADE"}:
        raise ValueError(f"illegal economic terminal decision: {decision}")
    selected_id = economic.get("selected_parameter_id")
    component = tuple(str(item) for item in economic["selected_component"])
    if decision == "PASS":
        if not isinstance(selected_id, str) or len(component) < 3:
            raise ValueError("PASS freeze requires a robust three-point component")
        metrics = _read_object(manifest_path.parent / "parameter_metrics.json")
        selected = [
            item
            for item in metrics["parameters"]
            if item["parameter_id"] == selected_id
        ]
        if len(selected) != 1 or selected[0]["economic_gate_status"] != "PASS":
            raise ValueError("selected medoid has no passing economic assessment")
        selected_parameters = {
            key: float(value) for key, value in selected[0]["parameters"].items()
        }
        canonical = StrategyParameters(**selected_parameters)
        if canonical.parameter_id != selected_id:
            raise ValueError("selected freeze parameter hash changed")
        final_parameters: dict[str, float] | None = selected_parameters
    else:
        if selected_id is not None or component:
            raise ValueError("NO_TRADE freeze cannot carry a selected parameter region")
        final_parameters = None
    if config.freeze_manifest.is_file():
        existing = _read_object(config.freeze_manifest)
        if (
            existing.get("status") != "FROZEN"
            or existing.get("config_sha256") != config.sha256
            or existing.get("economic_selection_snapshot_id")
            != economic["economic_selection_snapshot_id"]
            or existing.get("freeze_decision") != decision
            or existing.get("selected_parameter_id") != selected_id
            or existing.get("selected_component") != list(component)
            or existing.get("final_parameters") != final_parameters
        ):
            raise FileExistsError("existing strategy freeze differs")
        entry = _append(
            ledger,
            "STRATEGY_FREEZE_PASS_OR_NO_TRADE",
            _freeze_event(existing, config.freeze_manifest),
        )
        _print_brief(existing, config.freeze_manifest, entry.sequence)
        return 0
    payload = {
        "schema_version": 1,
        "status": "FROZEN",
        "freeze_decision": decision,
        "config_path": str(config.path.resolve()),
        "config_sha256": config.sha256,
        "economic_selection_snapshot_id": economic["economic_selection_snapshot_id"],
        "economic_selection_manifest": str(manifest_path.resolve()),
        "economic_selection_manifest_sha256": completion.payload["manifest_sha256"],
        "p0_gate_event_id": p0.payload["event_id"],
        "selected_parameter_id": selected_id,
        "selected_component": list(component),
        "final_parameters": final_parameters,
        "allowed_holdout_access_count": 1 if decision == "PASS" else 0,
        "retuning_after_freeze": False,
        "edge_card_authorized": False,
        "kelly_authorized": False,
        "holdout_accessed": False,
        "global_physical_2023_access_incident": True,
        "formal_2023_untouched_claim_allowed": False,
        "holdout_outcomes_observed": False,
        "created_at": datetime.now(UTC).isoformat(),
    }
    payload["freeze_snapshot_id"] = "strategy-freeze-" + _digest(
        json.dumps(
            {key: value for key, value in payload.items() if key != "created_at"},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    _write_immutable_json(config.freeze_manifest, payload)
    event_payload = _freeze_event(payload, config.freeze_manifest)
    entry = _append(ledger, "STRATEGY_FREEZE_PASS_OR_NO_TRADE", event_payload)
    _print_brief(payload, config.freeze_manifest, entry.sequence)
    return 0


def _freeze_event(payload: Mapping[str, Any], path: Path) -> dict[str, Any]:
    return {
        "event_id": _digest(f"{payload['freeze_snapshot_id']}|LEDGER"),
        "freeze_snapshot_id": payload["freeze_snapshot_id"],
        "freeze_manifest": str(path.resolve()),
        "freeze_manifest_sha256": _sha256_file(path),
        "freeze_decision": payload["freeze_decision"],
        "selected_parameter_id": payload["selected_parameter_id"],
        "selected_component": payload["selected_component"],
        "holdout_accessed": False,
        "global_physical_2023_access_incident": True,
        "holdout_outcomes_observed": False,
    }


def _print_brief(
    payload: Mapping[str, Any], path: Path, ledger_sequence: int
) -> None:
    print(
        json.dumps(
            {
                "status": "FROZEN",
                "freeze_decision": payload["freeze_decision"],
                "selected_parameter_id": payload["selected_parameter_id"],
                "selected_component_size": len(payload["selected_component"]),
                "freeze_manifest": str(path.resolve()),
                "ledger_sequence": ledger_sequence,
                "holdout_accessed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _one(entries: Sequence[LedgerEntry], event_type: str) -> LedgerEntry:
    found = [item for item in entries if item.event_type == event_type]
    if len(found) != 1:
        raise ValueError(f"expected exactly one {event_type}")
    return found[0]


def _passing_p0(entries: Sequence[LedgerEntry]) -> LedgerEntry:
    found = [
        item
        for item in entries
        if item.event_type == "PIT_B_TRUE_OOS_CALIBRATION_GATE_COMPLETE"
        and item.payload.get("status") == "PASS"
    ]
    if len(found) != 1:
        raise ValueError("strategy freeze requires exactly one passing true-OOS P0 gate")
    return found[0]


def _append(
    ledger: TrialLedger, event_type: str, payload: Mapping[str, Any]
) -> LedgerEntry:
    for entry in ledger.read_verified():
        if entry.payload.get("event_id") != payload["event_id"]:
            continue
        if entry.event_type != event_type or entry.payload != payload:
            raise ValueError("strategy freeze ledger event collision")
        return entry
    return ledger.append(event_type, payload)


def _read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return payload


def _write_immutable_json(path: Path, payload: Mapping[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != raw:
            raise FileExistsError(f"immutable strategy freeze differs: {path}")
        return
    path.write_text(raw, encoding="utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
