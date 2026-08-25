#!/usr/bin/env python3
"""Invalidate scan-bound v2 and preregister bucket-coalesced exact engine v3."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from cyq_game.strategy.ledger import LedgerEntry, TrialLedger
from cyq_game.strategy.markup_retest import MarkupRetestConfig, StrategyStage
from cyq_game.strategy.research import entry_parameter_grid

PROTOCOL_VERSION = "ENTRY_ECONOMIC_EXACT_ENGINE_V3"


def main() -> int:
    config = MarkupRetestConfig.load(
        "configs/markup_retest_main_chinext_2020_2023_v1.yaml"
    )
    ledger = TrialLedger(config.trial_ledger)
    entries = ledger.read_verified()
    _assert_holdout_locked(config, entries)
    v2 = _single_event(entries, "ENTRY_ECONOMIC_EXACT_ENGINE_V2")
    v2_benchmark = _single_event(
        entries,
        "ENTRY_ECONOMIC_EXACT_ENGINE_BENCHMARK",
    )
    if (
        v2_benchmark.payload.get("run_id") != v2.payload.get("run_id")
        or v2_benchmark.payload.get("status") != "FAIL"
        or v2_benchmark.payload.get("full_result_exact_parity") is not True
        or float(v2_benchmark.payload.get("wall_clock_speedup", 0.0)) >= 5.0
    ):
        raise ValueError("v2 benchmark does not match the reviewed scan-bound failure")
    invalidation = {
        "event_id": hashlib.sha256(
            f"{v2.payload['run_id']}|{v2_benchmark.entry_hash}|INVALIDATE".encode()
        ).hexdigest(),
        "run_id": v2.payload["run_id"],
        "superseded_protocol_version": v2.payload["protocol_version"],
        "superseded_benchmark_manifest": v2_benchmark.payload["manifest_path"],
        "superseded_benchmark_sha256": v2_benchmark.payload["manifest_sha256"],
        "status": "DIAGNOSTIC_ONLY",
        "formal_engine_eligible": False,
        "reason": "SPEEDUP_BELOW_PREREGISTERED_MINIMUM",
        "full_result_exact_parity": True,
        "observed_wall_clock_speedup": v2_benchmark.payload["wall_clock_speedup"],
        "root_cause": (
            "Each short-lived symbol-bucket task rescanned every annual execution "
            "Parquet file, so execution I/O dominated both lifecycle implementations."
        ),
        "holdout_accessed": False,
    }
    invalidation_entry = _append_idempotent(
        ledger,
        "ENTRY_ECONOMIC_EXACT_ENGINE_V2_INVALIDATED",
        invalidation,
    )

    entry_protocol = _single_event(entries, "ENTRY_ECONOMIC_SELECTION_PROTOCOL_V2")
    parameters = entry_parameter_grid(config)
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
    protocol = {
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
            "exact_entry_and_exit_simulators_unchanged": True,
            "full_result_scalar_parity_required": True,
            "optimization": (
                "Keep a stable worker alive for multiple panel symbol buckets so "
                "each worker scans the frozen annual execution files once."
            ),
            "temporary_or_persistent_execution_cache_created": False,
        },
        "activation_gate": {
            "synthetic_full_81_field_exact_parity": "REQUIRED",
            "real_symbol_full_result_sha256_parity": "REQUIRED",
            "real_symbol_minimum_count": 32,
            "real_symbol_bucket_coverage": 32,
            "vectorized_worker_count": 4,
            "scalar_baseline_worker_count": 10,
            "minimum_wall_clock_speedup": 5.0,
            "failure_policy": "DO_NOT_USE_V3_ENGINE",
        },
        "source_inventory": code,
        "code_set_sha256": code_set_sha,
        "return_thresholds_changed_after_v2_benchmark": False,
        "holdout_accessed": False,
    }
    protocol_entry = _append_idempotent(
        ledger,
        "ENTRY_ECONOMIC_EXACT_ENGINE_V3",
        protocol,
    )
    review = {
        "schema_version": 1,
        "status": "PREREGISTERED_BENCHMARK_REQUIRED",
        "v2_invalidation": invalidation,
        "protocol": protocol,
        "ledger": {
            "v2_invalidation_sequence": invalidation_entry.sequence,
            "v2_invalidation_entry_hash": invalidation_entry.entry_hash,
            "v3_protocol_sequence": protocol_entry.sequence,
            "v3_protocol_entry_hash": protocol_entry.entry_hash,
        },
        "holdout_accessed": False,
    }
    target = (
        config.outputs.validation_root
        / StrategyStage.DEVELOPMENT.value
        / config.sha256[:12]
        / "entry_economic_exact_engine_v3_preregistered.json"
    )
    _write_immutable_json(target, review)
    print(
        json.dumps(
            {
                "status": review["status"],
                "run_id": run_id,
                "v2_invalidation_sequence": invalidation_entry.sequence,
                "v3_protocol_sequence": protocol_entry.sequence,
                "code_set_sha256": code_set_sha,
                "holdout_accessed": False,
            },
            indent=2,
        )
    )
    return 0


def _single_event(entries: Sequence[LedgerEntry], event_type: str) -> LedgerEntry:
    matches = [item for item in entries if item.event_type == event_type]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {event_type} event")
    return matches[0]


def _assert_holdout_locked(
    config: MarkupRetestConfig,
    entries: Sequence[LedgerEntry],
) -> None:
    if config.freeze_manifest.exists():
        raise ValueError("exact engine preregistration must precede strategy freeze")
    if any(item.payload.get("holdout_accessed") is True for item in entries):
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
            raise FileExistsError(f"immutable exact-engine v3 review differs: {path}")
        return
    path.write_text(raw, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
