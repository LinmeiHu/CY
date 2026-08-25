#!/usr/bin/env python3
"""Invalidate v5 and preregister bounded-memory exact replay v6."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from cyq_game.strategy.ledger import LedgerEntry, TrialLedger
from cyq_game.strategy.markup_retest import MarkupRetestConfig, StrategyStage
from cyq_game.strategy.research import entry_parameter_grid

VERSION = "ENTRY_ECONOMIC_EXACT_ENGINE_V6"


def main() -> int:
    config = MarkupRetestConfig.load(
        "configs/markup_retest_main_chinext_2020_2023_v1.yaml"
    )
    ledger = TrialLedger(config.trial_ledger)
    entries = ledger.read_verified()
    incident = _locked_with_audited_incident(config, entries)
    v5 = _one(entries, "ENTRY_ECONOMIC_EXACT_ENGINE_V5")
    benchmark = _one(entries, "ENTRY_ECONOMIC_EXACT_ENGINE_V5_BENCHMARK")
    if (
        benchmark.payload.get("run_id") != v5.payload.get("run_id")
        or benchmark.payload.get("status") != "FAIL"
        or benchmark.payload.get("full_result_exact_parity") is not True
        or float(benchmark.payload.get("wall_clock_speedup", 0.0)) >= 5.0
    ):
        raise ValueError("v5 benchmark does not match the reviewed speed failure")
    invalidation = {
        "event_id": _digest(
            f"{v5.payload['run_id']}|{benchmark.entry_hash}|INVALIDATE"
        ),
        "run_id": v5.payload["run_id"],
        "superseded_protocol_version": v5.payload["protocol_version"],
        "superseded_benchmark_manifest": benchmark.payload["manifest_path"],
        "superseded_benchmark_sha256": benchmark.payload["manifest_sha256"],
        "status": "DIAGNOSTIC_ONLY",
        "formal_engine_eligible": False,
        "reason": "SPEEDUP_BELOW_PREREGISTERED_MINIMUM",
        "full_result_exact_parity": True,
        "observed_wall_clock_speedup": benchmark.payload["wall_clock_speedup"],
        "root_cause": (
            "The checkpoint-correct cache retained every full daily inventory and "
            "economic map. A high-state symbol used roughly 3.7-4.3 GB RSS; ten "
            "workers therefore created severe aggregate memory pressure."
        ),
        "correction": (
            "Keep the checkpoint-scoped exact cache, but bound it to 512 LRU "
            "operator steps per worker and release all symbol state at the symbol "
            "boundary. No disk cache or approximate lineage is allowed."
        ),
        "holdout_accessed": False,
    }
    invalidated = _append(
        ledger,
        "ENTRY_ECONOMIC_EXACT_ENGINE_V5_INVALIDATED",
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
            "operator_cache_policy": "LRU_MAX_512_STEPS_PER_WORKER",
            "operator_cache_released_at_symbol_boundary": True,
            "persistent_or_temporary_data_cache_created": False,
        },
        "resource_evidence": {
            "high_state_symbol_unbounded_peak_rss_bytes": 3_707_928_576,
            "high_state_symbol_lru512_peak_rss_bytes": 1_272_561_664,
            "memory_reduction_fraction": 0.656799,
            "single_symbol_speed_is_not_activation_evidence": True,
        },
        "activation_gate": {
            "synthetic_tests_required": True,
            "lru_eviction_exact_retention_test_required": True,
            "real_full_result_sha256_parity_required": True,
            "real_symbol_count": 64,
            "real_symbol_bucket_count": 32,
            "dynamic_one_bucket_tasks": True,
            "worker_count": 10,
            "minimum_wall_clock_speedup": 5.0,
            "failure_policy": "DO_NOT_USE_V6_ENGINE",
        },
        "holdout_incident": {
            "event_id": incident.payload["event_id"],
            "ledger_sequence": incident.sequence,
            "physical_2023_accessed": True,
            "outcomes_observed": False,
            "used_for_parameter_selection_or_thresholds": False,
            "further_2023_reads": "FORBIDDEN_BEFORE_DEVELOPMENT_FREEZE",
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
        "v5_invalidation": invalidation,
        "protocol": protocol,
        "ledger": {
            "v5_invalidation_sequence": invalidated.sequence,
            "v6_protocol_sequence": registered.sequence,
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
        / "entry_economic_exact_engine_v6_preregistered.json"
    )
    _write(target, review)
    print(
        json.dumps(
            {
                "status": review["status"],
                "run_id": run_id,
                "v5_invalidation_sequence": invalidated.sequence,
                "v6_protocol_sequence": registered.sequence,
                "code_set_sha256": code_sha,
                "physical_2023_access_incident": True,
                "holdout_outcomes_observed": False,
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


def _locked_with_audited_incident(
    config: MarkupRetestConfig, entries: Sequence[LedgerEntry]
) -> LedgerEntry:
    if config.freeze_manifest.exists():
        raise ValueError("engine registration must precede strategy freeze")
    accessed = [
        item for item in entries if item.payload.get("holdout_accessed") is True
    ]
    if len(accessed) != 1 or accessed[0].event_type != "HOLDOUT_ACCESS_INCIDENT":
        raise ValueError("unexpected or unaudited 2023 holdout access")
    incident = accessed[0]
    if (
        incident.payload.get("holdout_outcomes_observed") is not False
        or incident.payload.get("used_for_parameter_selection_or_thresholds") is not False
        or incident.payload.get("formal_2023_untouched_claim_allowed") is not False
    ):
        raise ValueError("2023 incident is not eligible for metadata-only containment")
    return incident


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
            raise FileExistsError(f"immutable v6 review differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
