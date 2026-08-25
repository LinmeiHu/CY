#!/usr/bin/env python3
"""Preregister the exact 81-entry execution engine before real-return parity."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from cyq_game.strategy.ledger import LedgerEntry, TrialLedger
from cyq_game.strategy.markup_retest import MarkupRetestConfig, StrategyStage
from cyq_game.strategy.research import entry_parameter_grid

PROTOCOL_VERSION = "ENTRY_ECONOMIC_EXACT_ENGINE_V2"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/markup_retest_main_chinext_2020_2023_v1.yaml"),
    )
    return parser.parse_args()


def main() -> int:
    config = MarkupRetestConfig.load(parse_args().config)
    ledger = TrialLedger(config.trial_ledger)
    entries = ledger.read_verified()
    entry_protocol = next(
        (
            item
            for item in reversed(entries)
            if item.event_type == "ENTRY_ECONOMIC_SELECTION_PROTOCOL_V2"
        ),
        None,
    )
    if entry_protocol is None:
        raise ValueError("entry economic protocol v2 is not preregistered")
    _assert_holdout_locked(config, entries)
    parameters = entry_parameter_grid(config)
    if len(parameters) != 81:
        raise ValueError("exact engine must bind all 81 entry parameters")
    code = [
        _file_record(Path("src/cyq_game/strategy/exact_replay.py")),
        _file_record(Path("src/cyq_game/strategy/research.py")),
        _file_record(Path("src/cyq_game/strategy/execution.py")),
        _file_record(Path("src/cyq_game/strategy/markup_retest.py")),
        _file_record(Path("src/cyq_game/strategy/signals.py")),
        _file_record(Path("tests/test_exact_replay.py")),
        _file_record(Path(__file__)),
    ]
    code_set_sha = _sha256_text(
        "\n".join(f"{item['path']}|{item['sha256']}" for item in code)
    )
    run_id = hashlib.sha256(
        (
            f"{PROTOCOL_VERSION}|{config.sha256}|"
            f"{entry_protocol.payload['run_id']}|{code_set_sha}"
        ).encode()
    ).hexdigest()
    payload = {
        "event_id": hashlib.sha256(f"{run_id}|PREREGISTER".encode()).hexdigest(),
        "run_id": run_id,
        "protocol_version": PROTOCOL_VERSION,
        "entry_economic_protocol_run_id": entry_protocol.payload["run_id"],
        "config_sha256": config.sha256,
        "parameter_count": len(parameters),
        "parameter_ids": [item.parameter_id for item in parameters],
        "controlled_exit_parameters": {
            "distribution_score_min": config.parameters.distribution_score_min,
            "protective_stop_atr": config.parameters.protective_stop_atr,
        },
        "semantic_contract": {
            "canonical_signal_constructor_unchanged": True,
            "exact_entry_simulator_unchanged": True,
            "exact_exit_simulator_unchanged": True,
            "next_legal_5m_window_unchanged": True,
            "blocked_exit_persistence_unchanged": True,
            "corporate_action_quantity_reconciliation_unchanged": True,
            "only_optimization": (
                "Represent 81 independent lifecycle memories as arrays and share "
                "identical observation/lineage computations."
            ),
        },
        "activation_gate": {
            "synthetic_full_81_field_exact_parity": "REQUIRED",
            "real_symbol_full_result_sha256_parity": "REQUIRED",
            "real_symbol_minimum_count": 32,
            "real_symbol_bucket_coverage": 32,
            "minimum_wall_clock_speedup": 5.0,
            "failure_policy": "DO_NOT_USE_VECTORIZED_ENGINE",
        },
        "source_inventory": code,
        "code_set_sha256": code_set_sha,
        "remaining_79_return_metrics_inspected_before_registration": False,
        "holdout_accessed": False,
    }
    entry = _append_idempotent(ledger, "ENTRY_ECONOMIC_EXACT_ENGINE_V2", payload)
    review = {
        "schema_version": 1,
        "status": "PREREGISTERED_BENCHMARK_REQUIRED",
        "protocol": payload,
        "ledger": {
            "sequence": entry.sequence,
            "entry_hash": entry.entry_hash,
        },
        "holdout_accessed": False,
    }
    target = (
        config.outputs.validation_root
        / StrategyStage.DEVELOPMENT.value
        / config.sha256[:12]
        / "entry_economic_exact_engine_v2_preregistered.json"
    )
    _write_immutable_json(target, review)
    print(
        json.dumps(
            {
                "status": review["status"],
                "run_id": run_id,
                "ledger_sequence": entry.sequence,
                "code_set_sha256": code_set_sha,
                "holdout_accessed": False,
            },
            indent=2,
        )
    )
    return 0


def _assert_holdout_locked(
    config: MarkupRetestConfig,
    entries: tuple[LedgerEntry, ...],
) -> None:
    if config.freeze_manifest.exists():
        raise ValueError("exact engine preregistration must precede strategy freeze")
    for entry in entries:
        if entry.payload.get("holdout_accessed") is True:
            raise ValueError("2023 holdout has already been accessed")


def _append_idempotent(
    ledger: TrialLedger,
    event_type: str,
    payload: Mapping[str, Any],
) -> LedgerEntry:
    event_id = str(payload["event_id"])
    for entry in ledger.read_verified():
        if entry.payload.get("event_id") != event_id:
            continue
        if entry.event_type != event_type or entry.payload != payload:
            raise ValueError(f"trial ledger event collision: {event_id}")
        return entry
    return ledger.append(event_type, payload)


def _file_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    return {
        "path": str(resolved),
        "bytes": resolved.stat().st_size,
        "sha256": _sha256_file(resolved),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _write_immutable_json(path: Path, payload: Mapping[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != raw:
            raise FileExistsError(f"immutable exact-engine review differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
