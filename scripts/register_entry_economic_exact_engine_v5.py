#!/usr/bin/env python3
"""Invalidate v4 and preregister checkpoint-scoped lineage caching v5."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from cyq_game.strategy.ledger import LedgerEntry, TrialLedger
from cyq_game.strategy.markup_retest import MarkupRetestConfig, StrategyStage
from cyq_game.strategy.research import entry_parameter_grid

VERSION = "ENTRY_ECONOMIC_EXACT_ENGINE_V5"


def main() -> int:
    config = MarkupRetestConfig.load(
        "configs/markup_retest_main_chinext_2020_2023_v1.yaml"
    )
    ledger = TrialLedger(config.trial_ledger)
    entries = ledger.read_verified()
    _locked(config, entries)
    v4 = _one(entries, "ENTRY_ECONOMIC_EXACT_ENGINE_V4")
    benchmark = _one(entries, "ENTRY_ECONOMIC_EXACT_ENGINE_V4_BENCHMARK")
    if (
        benchmark.payload.get("run_id") != v4.payload.get("run_id")
        or benchmark.payload.get("status") != "FAIL"
        or benchmark.payload.get("full_result_exact_parity") is not False
    ):
        raise ValueError("v4 benchmark does not match the reviewed parity failure")
    invalidation = {
        "event_id": _digest(
            f"{v4.payload['run_id']}|{benchmark.entry_hash}|INVALIDATE"
        ),
        "run_id": v4.payload["run_id"],
        "superseded_protocol_version": v4.payload["protocol_version"],
        "superseded_benchmark_manifest": benchmark.payload["manifest_path"],
        "superseded_benchmark_sha256": benchmark.payload["manifest_sha256"],
        "status": "DIAGNOSTIC_ONLY",
        "formal_engine_eligible": False,
        "reason": "FULL_RESULT_EXACT_PARITY_FAILED",
        "root_cause": (
            "Operator cache key omitted the checkpoint origin. Two anchors may "
            "reconstruct the same trade date from different frozen checkpoints; "
            "sharing their full inventory state is not bit-exact."
        ),
        "correction": (
            "Key every shared operator/full-inventory step by symbol, seller model, "
            "checkpoint date and trade date; keep anchor lineage states independent."
        ),
        "holdout_accessed": False,
    }
    invalidated = _append(
        ledger,
        "ENTRY_ECONOMIC_EXACT_ENGINE_V4_INVALIDATED",
        invalidation,
    )

    economic = _one(entries, "ENTRY_ECONOMIC_SELECTION_PROTOCOL_V2")
    parameters = entry_parameter_grid(config)
    files = [
        Path("src/cyq_game/strategy/chip_lineage.py"),
        Path("src/cyq_game/strategy/exact_replay.py"),
        Path("src/cyq_game/strategy/research.py"),
        Path("src/cyq_game/strategy/execution.py"),
        Path("src/cyq_game/strategy/markup_retest.py"),
        Path("src/cyq_game/strategy/signals.py"),
        Path("tests/test_chip_lineage_resolver.py"),
        Path("tests/test_exact_replay.py"),
        Path(__file__),
    ]
    inventory = [_file(item) for item in files]
    code_sha = _digest(
        "\n".join(f"{item['path']}|{item['sha256']}" for item in inventory)
    )
    run_id = _digest(
        f"{VERSION}|{config.sha256}|{economic.payload['run_id']}|{code_sha}"
    )
    protocol = {
        "event_id": _digest(f"{run_id}|PREREGISTER"),
        "run_id": run_id,
        "protocol_version": VERSION,
        "entry_economic_protocol_run_id": economic.payload["run_id"],
        "config_sha256": config.sha256,
        "parameter_count": len(parameters),
        "parameter_ids": [item.parameter_id for item in parameters],
        "controlled_exit_parameters": {
            "distribution_score_min": config.parameters.distribution_score_min,
            "protective_stop_atr": config.parameters.protective_stop_atr,
        },
        "semantic_contract": {
            "canonical_signal_and_execution_code_unchanged": True,
            "per_anchor_lineage_state_independent": True,
            "shared_cache_key": [
                "symbol",
                "seller_model",
                "checkpoint_date",
                "trade_date",
            ],
            "checkpoint_cross_contamination_forbidden": True,
            "operator_cache_released_at_symbol_boundary": True,
            "persistent_or_temporary_data_cache_created": False,
        },
        "activation_gate": {
            "synthetic_tests_required": True,
            "real_full_result_sha256_parity_required": True,
            "real_symbol_count": 64,
            "real_symbol_bucket_count": 32,
            "dynamic_one_bucket_tasks": True,
            "worker_count": 10,
            "minimum_wall_clock_speedup": 5.0,
            "failure_policy": "DO_NOT_USE_V5_ENGINE",
        },
        "source_inventory": inventory,
        "code_set_sha256": code_sha,
        "economic_thresholds_changed": False,
        "holdout_accessed": False,
    }
    registered = _append(ledger, VERSION, protocol)
    review = {
        "schema_version": 1,
        "status": "PREREGISTERED_BENCHMARK_REQUIRED",
        "v4_invalidation": invalidation,
        "protocol": protocol,
        "ledger": {
            "v4_invalidation_sequence": invalidated.sequence,
            "v5_protocol_sequence": registered.sequence,
        },
        "holdout_accessed": False,
    }
    target = (
        config.outputs.validation_root
        / StrategyStage.DEVELOPMENT.value
        / config.sha256[:12]
        / "entry_economic_exact_engine_v5_preregistered.json"
    )
    _write(target, review)
    print(
        json.dumps(
            {
                "status": review["status"],
                "run_id": run_id,
                "v4_invalidation_sequence": invalidated.sequence,
                "v5_protocol_sequence": registered.sequence,
                "code_set_sha256": code_sha,
                "holdout_accessed": False,
            },
            indent=2,
        )
    )
    return 0


def _one(entries: Sequence[LedgerEntry], event_type: str) -> LedgerEntry:
    found = [item for item in entries if item.event_type == event_type]
    if len(found) != 1:
        raise ValueError(f"expected exactly one {event_type}")
    return found[0]


def _locked(config: MarkupRetestConfig, entries: Sequence[LedgerEntry]) -> None:
    if config.freeze_manifest.exists():
        raise ValueError("engine registration must precede strategy freeze")
    if any(item.payload.get("holdout_accessed") is True for item in entries):
        raise ValueError("2023 holdout has already been accessed")


def _append(
    ledger: TrialLedger,
    event_type: str,
    payload: Mapping[str, Any],
) -> LedgerEntry:
    for entry in ledger.read_verified():
        if entry.payload.get("event_id") != payload["event_id"]:
            continue
        if entry.event_type != event_type or entry.payload != payload:
            raise ValueError("ledger event collision")
        return entry
    return ledger.append(event_type, payload)


def _file(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    return {
        "path": str(resolved),
        "bytes": resolved.stat().st_size,
        "sha256": _file_sha(resolved),
    }


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != raw:
            raise FileExistsError(f"immutable v5 review differs: {path}")
        return
    path.write_text(raw, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
