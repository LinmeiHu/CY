#!/usr/bin/env python3
"""Blind full-record parity and speed benchmark for exact 81-entry replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

import duckdb

from cyq_game.strategy.exact_replay import (
    ExactReplayResult,
    evaluate_exact_parameter_lattice_files,
)
from cyq_game.strategy.ledger import LedgerEntry, TrialLedger
from cyq_game.strategy.markup_retest import MarkupRetestConfig, StrategyStage
from cyq_game.strategy.research import entry_parameter_grid

PROTOCOL_VERSION = "ENTRY_ECONOMIC_EXACT_ENGINE_V6"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/markup_retest_main_chinext_2020_2023_v1.yaml"),
    )
    parser.add_argument("--vector-threads", type=int, default=10)
    parser.add_argument("--scalar-threads", type=int, default=10)
    parser.add_argument("--symbols-per-bucket", type=int, default=2)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = MarkupRetestConfig.load(args.config)
    ledger = TrialLedger(config.trial_ledger)
    engine_event = _engine_event(ledger)
    _assert_holdout_locked(config, ledger.read_verified())
    entry = _entry_artifact(config)
    panel_manifest = Path(str(entry["panel_manifest"]))
    panel_files = tuple(sorted(panel_manifest.parent.rglob("*.parquet")))
    if not panel_files:
        raise FileNotFoundError("development panel Parquet files are missing")
    symbols = _benchmark_symbols(config, args.symbols_per_bucket)
    if len(symbols) < 32 or _bucket_count(symbols) != 32:
        raise ValueError("real benchmark must cover all 32 symbol buckets")
    parameters = entry_parameter_grid(config)
    scalar_baseline = _preserved_scalar_baseline(config, symbols)

    vector_started = time.perf_counter()
    vectorized = evaluate_exact_parameter_lattice_files(
        panel_files,
        config,
        StrategyStage.DEVELOPMENT,
        parameters,
        panel_snapshot_id=str(entry["panel_snapshot_id"]),
        threads=args.vector_threads,
        symbols=symbols,
        vectorized_entry_grid=True,
        coalesce_buckets=False,
    )
    vector_seconds = time.perf_counter() - vector_started

    vector_digest = _result_sha256(vectorized)
    scalar_digest = str(scalar_baseline["scalar_result_sha256"])
    scalar_seconds = float(scalar_baseline["scalar_wall_seconds"])
    parity = vector_digest == scalar_digest
    speedup = scalar_seconds / vector_seconds
    required_speedup = float(engine_event.payload["activation_gate"]["minimum_wall_clock_speedup"])
    status = "PASS" if parity and speedup >= required_speedup else "FAIL"
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": status,
        "protocol_version": PROTOCOL_VERSION,
        "engine_run_id": engine_event.payload["run_id"],
        "config_sha256": config.sha256,
        "scope": "QA_ONLY_ENGINE_PARITY_NOT_ECONOMIC_EVIDENCE",
        "parameter_count": len(parameters),
        "symbol_count": len(symbols),
        "symbol_bucket_count": _bucket_count(symbols),
        "symbols_sha256": _sha256_text("\n".join(symbols)),
        "panel_snapshot_id": entry["panel_snapshot_id"],
        "vectorized_threads": args.vector_threads,
        "vectorized_bucket_coalescing": False,
        "scalar_threads": args.scalar_threads,
        "scalar_bucket_coalescing": False,
        "execution_order": [
            "VECTORIZED_V6_LRU512_COLD_FIRST",
            "PRESERVED_V2_SCALAR_BASELINE",
        ],
        "vectorized_wall_seconds": vector_seconds,
        "scalar_wall_seconds": scalar_seconds,
        "wall_clock_speedup": speedup,
        "minimum_required_speedup": required_speedup,
        "full_result_exact_parity": parity,
        "vectorized_result_sha256": vector_digest,
        "scalar_result_sha256": scalar_digest,
        "scalar_baseline_manifest": scalar_baseline["manifest_path"],
        "scalar_baseline_manifest_sha256": scalar_baseline["manifest_sha256"],
        "parity_proof": (
            "V3 vector full-result hash equals the preserved V2 scalar hash; the V2 "
            "benchmark already proved its vector and scalar result objects equal."
        ),
        "result_shape": _result_shape(vectorized),
        "return_metrics_printed_or_used_for_thresholds": False,
        "holdout_accessed": False,
        "global_physical_2023_access_incident": True,
        "holdout_outcomes_observed": False,
    }
    target = (
        config.outputs.validation_root
        / StrategyStage.DEVELOPMENT.value
        / config.sha256[:12]
        / "entry_economic_exact_engine_v6_benchmark.json"
    )
    report_sha = _write_immutable_json(target, report)
    event = {
        "event_id": hashlib.sha256(
            f"{engine_event.payload['run_id']}|{report_sha}|BENCHMARK".encode()
        ).hexdigest(),
        "run_id": engine_event.payload["run_id"],
        "protocol_version": PROTOCOL_VERSION,
        "status": status,
        "manifest_path": str(target),
        "manifest_sha256": report_sha,
        "parameter_count": len(parameters),
        "symbol_count": len(symbols),
        "symbol_bucket_count": _bucket_count(symbols),
        "full_result_exact_parity": parity,
        "wall_clock_speedup": speedup,
        "minimum_required_speedup": required_speedup,
        "holdout_accessed": False,
        "global_physical_2023_access_incident": True,
        "holdout_outcomes_observed": False,
    }
    completion = _append_idempotent(
        ledger,
        "ENTRY_ECONOMIC_EXACT_ENGINE_V6_BENCHMARK",
        event,
    )
    print(
        json.dumps(
            {
                "status": status,
                "parameter_count": len(parameters),
                "symbol_count": len(symbols),
                "symbol_bucket_count": _bucket_count(symbols),
                "full_result_exact_parity": parity,
                "vectorized_wall_seconds": vector_seconds,
                "scalar_wall_seconds": scalar_seconds,
                "wall_clock_speedup": speedup,
                "ledger_sequence": completion.sequence,
                "holdout_accessed": False,
                "global_physical_2023_access_incident": True,
                "holdout_outcomes_observed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if status == "PASS" else 1


def _engine_event(ledger: TrialLedger) -> LedgerEntry:
    events = [
        item
        for item in ledger.read_verified()
        if item.event_type == "ENTRY_ECONOMIC_EXACT_ENGINE_V6"
    ]
    if len(events) != 1:
        raise ValueError("expected exactly one preregistered exact-engine v6 event")
    return events[0]


def _entry_artifact(config: MarkupRetestConfig) -> dict[str, Any]:
    path = (
        config.outputs.validation_root
        / StrategyStage.DEVELOPMENT.value
        / config.sha256[:12]
        / "entry_frequency.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("config_sha256") != config.sha256:
        raise ValueError("diagnostic entry artifact identity mismatch")
    return payload


def _benchmark_symbols(
    config: MarkupRetestConfig,
    symbols_per_bucket: int,
) -> tuple[str, ...]:
    if symbols_per_bucket < 1:
        raise ValueError("symbols_per_bucket must be positive")
    source = (
        config.outputs.validation_root
        / StrategyStage.DEVELOPMENT.value
        / config.sha256[:12]
        / "exact_exit_lattice-335858bafb51-coordinate-v2"
        / "signals.parquet"
    )
    if not source.is_file():
        raise FileNotFoundError("preserved diagnostic exact signals are missing")
    connection = duckdb.connect()
    try:
        rows = connection.execute(
            """
            WITH symbols AS (
              SELECT DISTINCT symbol, abs(hash(symbol) % 32)::INTEGER AS bucket
              FROM read_parquet(?)
            ), ranked AS (
              SELECT symbol, bucket,
                     ROW_NUMBER() OVER (PARTITION BY bucket ORDER BY symbol) AS rank
              FROM symbols
            )
            SELECT symbol
            FROM ranked
            WHERE rank <= ?
            ORDER BY bucket, symbol
            """,
            [str(source), symbols_per_bucket],
        ).fetchall()
    finally:
        connection.close()
    return tuple(str(row[0]) for row in rows)


def _preserved_scalar_baseline(
    config: MarkupRetestConfig,
    symbols: Sequence[str],
) -> dict[str, Any]:
    path = (
        config.outputs.validation_root
        / StrategyStage.DEVELOPMENT.value
        / config.sha256[:12]
        / "entry_economic_exact_engine_v2_benchmark.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("preserved v2 benchmark must be an object")
    if (
        payload.get("full_result_exact_parity") is not True
        or payload.get("parameter_count") != 81
        or payload.get("symbol_count") != len(symbols)
        or payload.get("symbols_sha256") != _sha256_text("\n".join(symbols))
        or payload.get("symbol_bucket_count") != 32
    ):
        raise ValueError("preserved scalar baseline scope or parity mismatch")
    payload["manifest_path"] = str(path)
    payload["manifest_sha256"] = _sha256_file(path)
    return payload


def _bucket_count(symbols: Sequence[str]) -> int:
    connection = duckdb.connect()
    try:
        value = connection.execute(
            "SELECT COUNT(DISTINCT abs(hash(unnest) % 32)) FROM unnest(?)",
            [list(symbols)],
        ).fetchone()
    finally:
        connection.close()
    return int(value[0]) if value is not None else 0


def _result_shape(result: ExactReplayResult) -> dict[str, int]:
    return {
        "input_rows": result.input_rows,
        "evaluation_rows": result.evaluation_rows,
        "signals": len(result.signals),
        "trades": len(result.trades),
        "open_exposures": len(result.open_exposures),
    }


def _result_sha256(result: ExactReplayResult) -> str:
    payload = asdict(result)
    return _sha256_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )


def _assert_holdout_locked(
    config: MarkupRetestConfig,
    entries: Sequence[LedgerEntry],
) -> None:
    if config.freeze_manifest.exists():
        raise ValueError("engine benchmark must precede strategy freeze")
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


def _write_immutable_json(path: Path, payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    digest = _sha256_text(raw)
    if path.exists():
        if path.read_text(encoding="utf-8") != raw:
            raise FileExistsError(f"immutable engine benchmark differs: {path}")
        return digest
    path.write_text(raw, encoding="utf-8")
    return digest


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
