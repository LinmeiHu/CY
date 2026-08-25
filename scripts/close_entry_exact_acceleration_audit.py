#!/usr/bin/env python3
"""Close failed acceleration trials and select the canonical scalar fallback."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from cyq_game.strategy.ledger import LedgerEntry, TrialLedger
from cyq_game.strategy.markup_retest import MarkupRetestConfig, StrategyStage
from cyq_game.strategy.research import entry_parameter_grid


def main() -> int:
    config = MarkupRetestConfig.load(
        "configs/markup_retest_main_chinext_2020_2023_v1.yaml"
    )
    ledger = TrialLedger(config.trial_ledger)
    entries = ledger.read_verified()
    incident = _audited_incident(config, entries)
    v6 = _one(entries, "ENTRY_ECONOMIC_EXACT_ENGINE_V6")
    benchmark = _one(entries, "ENTRY_ECONOMIC_EXACT_ENGINE_V6_BENCHMARK")
    if (
        benchmark.payload.get("run_id") != v6.payload.get("run_id")
        or benchmark.payload.get("status") != "FAIL"
        or benchmark.payload.get("full_result_exact_parity") is not True
        or float(benchmark.payload.get("wall_clock_speedup", 0.0)) >= 5.0
    ):
        raise ValueError("v6 benchmark does not match the reviewed speed failure")
    invalidation = {
        "event_id": _digest(
            f"{v6.payload['run_id']}|{benchmark.entry_hash}|INVALIDATE"
        ),
        "run_id": v6.payload["run_id"],
        "superseded_protocol_version": v6.payload["protocol_version"],
        "superseded_benchmark_manifest": benchmark.payload["manifest_path"],
        "superseded_benchmark_sha256": benchmark.payload["manifest_sha256"],
        "status": "DIAGNOSTIC_ONLY",
        "formal_engine_eligible": False,
        "reason": "SPEEDUP_BELOW_PREREGISTERED_MINIMUM",
        "full_result_exact_parity": True,
        "observed_wall_clock_speedup": benchmark.payload["wall_clock_speedup"],
        "observed_vector_wall_seconds": 298.34104004199617,
        "correction": "RESTORE_V5_SOURCE_BYTES_AND_STOP_ACCELERATION_TRIALS",
        "holdout_accessed": False,
    }
    invalidated = _append(
        ledger,
        "ENTRY_ECONOMIC_EXACT_ENGINE_V6_INVALIDATED",
        invalidation,
    )

    v5 = _one(entries, "ENTRY_ECONOMIC_EXACT_ENGINE_V5")
    mismatches = _source_mismatches(v5.payload["source_inventory"])
    if mismatches:
        raise ValueError(f"v5 source restoration mismatch: {mismatches}")
    parameters = entry_parameter_grid(config)
    run_id = _digest(
        "|".join(
            (
                "ENTRY_ECONOMIC_REFERENCE_SCALAR_ENGINE_V1",
                config.sha256,
                str(v5.payload["code_set_sha256"]),
                benchmark.entry_hash,
            )
        )
    )
    fallback = {
        "event_id": _digest(f"{run_id}|CLOSE_ACCELERATION"),
        "run_id": run_id,
        "protocol_version": "ENTRY_ECONOMIC_REFERENCE_SCALAR_ENGINE_V1",
        "status": "ACTIVE_REFERENCE_FALLBACK",
        "config_sha256": config.sha256,
        "parameter_count": len(parameters),
        "parameter_ids": [item.parameter_id for item in parameters],
        "engine_function": "evaluate_exact_parameter_lattice_symbol",
        "file_driver": "evaluate_exact_parameter_lattice_files",
        "vectorized_entry_grid": False,
        "worker_count": 4,
        "worker_rationale": {
            "physical_memory_bytes": 34_359_738_368,
            "performance_cores": 4,
            "efficiency_cores": 6,
            "observed_high_state_worker_peak_rss_bytes": 4_285_366_272,
            "policy": "FOUR_PERFORMANCE_WORKERS_AVOID_SWAP_AND_DISK_PRESSURE",
        },
        "correctness_evidence": {
            "v5_source_inventory_restored_exactly": True,
            "v5_code_set_sha256": v5.payload["code_set_sha256"],
            "v5_real_64_symbol_full_result_parity": True,
            "v6_real_64_symbol_full_result_parity": True,
            "synthetic_full_81_exact_tests": "PASS",
            "scalar_lifecycle_is_canonical_source_of_truth": True,
        },
        "acceleration_audit_closed": True,
        "acceleration_trials_v2_through_v6_formal_use": "FORBIDDEN",
        "economic_thresholds_changed": False,
        "persistent_or_temporary_data_cache_created": False,
        "holdout_incident": {
            "event_id": incident.payload["event_id"],
            "ledger_sequence": incident.sequence,
            "physical_2023_accessed": True,
            "outcomes_observed": False,
            "used_for_parameter_selection_or_thresholds": False,
        },
        "holdout_accessed": False,
    }
    closed = _append(
        ledger,
        "ENTRY_ECONOMIC_EXACT_ACCELERATION_CLOSED",
        fallback,
    )
    report = {
        "schema_version": 1,
        "status": "ACTIVE_REFERENCE_FALLBACK",
        "v6_invalidation": invalidation,
        "reference_fallback": fallback,
        "ledger": {
            "v6_invalidation_sequence": invalidated.sequence,
            "acceleration_closed_sequence": closed.sequence,
            "holdout_incident_sequence": incident.sequence,
        },
        "holdout_accessed": False,
        "global_physical_2023_access_incident": True,
        "holdout_outcomes_observed": False,
    }
    target = (
        config.outputs.validation_root
        / StrategyStage.DEVELOPMENT.value
        / config.sha256[:12]
        / "entry_economic_exact_acceleration_closed.json"
    )
    _write(target, report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "v6_invalidation_sequence": invalidated.sequence,
                "acceleration_closed_sequence": closed.sequence,
                "worker_count": fallback["worker_count"],
                "v5_source_inventory_restored_exactly": True,
                "holdout_outcomes_observed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _one(entries: Sequence[LedgerEntry], event_type: str) -> LedgerEntry:
    found = [item for item in entries if item.event_type == event_type]
    if len(found) != 1:
        raise ValueError(f"expected exactly one {event_type}")
    return found[0]


def _audited_incident(
    config: MarkupRetestConfig, entries: Sequence[LedgerEntry]
) -> LedgerEntry:
    if config.freeze_manifest.exists():
        raise ValueError("acceleration closure must precede strategy freeze")
    accessed = [
        item for item in entries if item.payload.get("holdout_accessed") is True
    ]
    if len(accessed) != 1 or accessed[0].event_type != "HOLDOUT_ACCESS_INCIDENT":
        raise ValueError("unexpected or unaudited 2023 holdout access")
    incident = accessed[0]
    if (
        incident.payload.get("holdout_outcomes_observed") is not False
        or incident.payload.get("used_for_parameter_selection_or_thresholds") is not False
    ):
        raise ValueError("holdout outcome or tuning access blocks fallback registration")
    return incident


def _source_mismatches(inventory: object) -> list[str]:
    if not isinstance(inventory, list):
        raise TypeError("v5 source inventory must be a list")
    mismatches: list[str] = []
    for raw in inventory:
        if not isinstance(raw, dict):
            raise TypeError("v5 source inventory row must be an object")
        path = Path(str(raw["path"]))
        if not path.is_file() or _file_sha(path) != str(raw["sha256"]):
            mismatches.append(str(path))
    return mismatches


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
            raise FileExistsError(f"immutable closure review differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
