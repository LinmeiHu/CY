#!/usr/bin/env python3
"""Run the preregistered 81-point development replay in resumable bucket parts."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from cyq_game.strategy.exact_replay import (
    ExactReplayResult,
    evaluate_exact_parameter_lattice_files,
)
from cyq_game.strategy.ledger import LedgerEntry, TrialLedger
from cyq_game.strategy.markup_retest import (
    MarkupRetestConfig,
    StrategyParameters,
    StrategyStage,
)
from cyq_game.strategy.research import entry_parameter_grid

PROTOCOL_VERSION = "ENTRY_ECONOMIC_EXACT_REPLAY_V2"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/markup_retest_main_chinext_2020_2023_v1.yaml"),
    )
    parser.add_argument("--workers", type=int, default=4)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.workers != 4:
        raise ValueError("reference fallback is registered for exactly four workers")
    config = MarkupRetestConfig.load(args.config)
    ledger = TrialLedger(config.trial_ledger)
    entries = ledger.read_verified()
    protocol = _one(entries, "ENTRY_ECONOMIC_SELECTION_PROTOCOL_V2")
    fallback = _one(entries, "ENTRY_ECONOMIC_EXACT_ACCELERATION_CLOSED")
    p0 = _passing_p0(entries)
    incident = _audited_incident(config, entries)
    entry = _entry_artifact(config)
    parameters = entry_parameter_grid(config)
    expected_ids = tuple(protocol.payload["parameter_grid"]["parameter_ids"])
    if tuple(item.parameter_id for item in parameters) != expected_ids:
        raise ValueError("entry grid differs from preregistered 81 parameter ids")
    if (
        fallback.payload.get("vectorized_entry_grid") is not False
        or fallback.payload.get("worker_count") != args.workers
    ):
        raise ValueError("active reference fallback contract mismatch")
    panel_manifest = Path(str(entry["panel_manifest"]))
    panel_files = tuple(sorted(panel_manifest.parent.rglob("*.parquet")))
    groups = _panel_groups(panel_files)
    if tuple(bucket for bucket, _ in groups) != tuple(range(32)):
        raise ValueError("development panel must contain all 32 symbol buckets")
    _assert_development_only(panel_files)

    source_identity = "|".join(
        (
            PROTOCOL_VERSION,
            config.sha256,
            str(protocol.payload["run_id"]),
            str(fallback.payload["run_id"]),
            str(p0.payload["manifest_sha256"]),
            str(entry["panel_snapshot_id"]),
            _sha256_file(Path(__file__)),
        )
    )
    run_id = _digest(source_identity)
    root = (
        config.outputs.validation_root
        / StrategyStage.DEVELOPMENT.value
        / config.sha256[:12]
        / f"entry_economic_exact_replay_v2-{run_id[:12]}"
    )
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root.with_suffix(".lock")
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("entry economic exact replay is already running") from error
        return _run_locked(
            config=config,
            ledger=ledger,
            protocol=protocol,
            fallback=fallback,
            p0=p0,
            incident=incident,
            entry=entry,
            parameters=parameters,
            groups=groups,
            workers=args.workers,
            run_id=run_id,
            root=root,
        )


def _run_locked(
    *,
    config: MarkupRetestConfig,
    ledger: TrialLedger,
    protocol: LedgerEntry,
    fallback: LedgerEntry,
    p0: LedgerEntry,
    incident: LedgerEntry,
    entry: Mapping[str, Any],
    parameters: tuple[StrategyParameters, ...],
    groups: tuple[tuple[int, tuple[Path, ...]], ...],
    workers: int,
    run_id: str,
    root: Path,
) -> int:
    final_manifest = root / "manifest.json"
    if final_manifest.is_file():
        existing_payload = json.loads(final_manifest.read_text(encoding="utf-8"))
        if (
            existing_payload.get("run_id") != run_id
            or existing_payload.get("status") != "COMPLETE"
        ):
            raise FileExistsError("existing exact replay manifest differs")
        print(json.dumps(_brief(existing_payload), ensure_ascii=False, indent=2))
        return 0

    started = {
        "event_id": _digest(f"{run_id}|STARTED"),
        "run_id": run_id,
        "protocol_version": PROTOCOL_VERSION,
        "economic_protocol_run_id": protocol.payload["run_id"],
        "reference_fallback_run_id": fallback.payload["run_id"],
        "config_sha256": config.sha256,
        "panel_snapshot_id": entry["panel_snapshot_id"],
        "parameter_count": len(parameters),
        "bucket_count": len(groups),
        "worker_count": workers,
        "stage": "development",
        "evaluation_years": [2020, 2021, 2022],
        "holdout_accessed": False,
        "global_physical_2023_access_incident": True,
        "holdout_outcomes_observed": False,
    }
    started_entry = _append(ledger, "ENTRY_ECONOMIC_EXACT_REPLAY_V2_STARTED", started)
    completed = {
        bucket
        for bucket, _ in groups
        if _valid_bucket(root / "parts" / f"bucket={bucket:02d}", run_id, parameters)
    }
    _write_progress(root, run_id, completed, len(groups), workers)
    pending = [(bucket, files) for bucket, files in groups if bucket not in completed]
    started_at = time.perf_counter()
    if pending:
        arguments = [
            (
                bucket,
                files,
                config,
                parameters,
                str(entry["panel_snapshot_id"]),
            )
            for bucket, files in pending
        ]
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_run_bucket, argument): argument[0]
                for argument in arguments
            }
            for future in as_completed(futures):
                bucket = futures.pop(future)
                result, wall_seconds = future.result()
                _write_bucket(
                    root / "parts" / f"bucket={bucket:02d}",
                    bucket=bucket,
                    run_id=run_id,
                    result=result,
                    wall_seconds=wall_seconds,
                )
                completed.add(bucket)
                _write_progress(root, run_id, completed, len(groups), workers)
                print(
                    json.dumps(
                        {
                            "bucket": bucket,
                            "completed_buckets": len(completed),
                            "total_buckets": len(groups),
                            "bucket_wall_seconds": wall_seconds,
                            "signals": len(result.signals),
                            "trades": len(result.trades),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                del result
    if completed != set(range(32)):
        raise RuntimeError("exact replay ended without all 32 bucket parts")
    bucket_manifests = [
        json.loads(
            (root / "parts" / f"bucket={bucket:02d}" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        for bucket in range(32)
    ]
    payload: dict[str, Any] = {
        "schema_version": 1,
        "status": "COMPLETE",
        "run_id": run_id,
        "protocol_version": PROTOCOL_VERSION,
        "economic_protocol_run_id": protocol.payload["run_id"],
        "reference_fallback_run_id": fallback.payload["run_id"],
        "p0_gate_event_id": p0.payload["event_id"],
        "started_ledger_sequence": started_entry.sequence,
        "config_path": str(config.path.resolve()),
        "config_sha256": config.sha256,
        "panel_manifest": entry["panel_manifest"],
        "panel_snapshot_id": entry["panel_snapshot_id"],
        "stage": "development",
        "evaluation_years": [2020, 2021, 2022],
        "classification": "WALK_FORWARD_DEVELOPMENT_EVIDENCE",
        "parameter_count": len(parameters),
        "parameter_ids": [item.parameter_id for item in parameters],
        "parameters": [item.canonical() for item in parameters],
        "controlled_exit_parameters": {
            "distribution_score_min": config.parameters.distribution_score_min,
            "protective_stop_atr": config.parameters.protective_stop_atr,
        },
        "engine_function": "evaluate_exact_parameter_lattice_symbol",
        "vectorized_entry_grid": False,
        "worker_count": workers,
        "bucket_count": len(bucket_manifests),
        "panel_passes": 1,
        "input_rows": sum(int(item["input_rows"]) for item in bucket_manifests),
        "evaluation_rows": sum(
            int(item["evaluation_rows"]) for item in bucket_manifests
        ),
        "signals": sum(int(item["signals"]) for item in bucket_manifests),
        "trades": sum(int(item["trades"]) for item in bucket_manifests),
        "open_exposures": sum(
            int(item["open_exposures"]) for item in bucket_manifests
        ),
        "elapsed_this_invocation_seconds": time.perf_counter() - started_at,
        "bucket_manifests": bucket_manifests,
        "holdout_incident_event_id": incident.payload["event_id"],
        "holdout_accessed": False,
        "global_physical_2023_access_incident": True,
        "holdout_outcomes_observed": False,
        "used_for_parameter_selection_or_thresholds": False,
        "created_at": datetime.now(UTC).isoformat(),
    }
    payload["exact_replay_snapshot_id"] = "entry-economic-exact-replay-" + _digest(
        json.dumps(
            {
                key: value
                for key, value in payload.items()
                if key not in {"created_at", "elapsed_this_invocation_seconds"}
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    _write_immutable_json(final_manifest, payload)
    completion = {
        "event_id": _digest(f"{run_id}|{payload['exact_replay_snapshot_id']}|COMPLETE"),
        "run_id": run_id,
        "protocol_version": PROTOCOL_VERSION,
        "config_sha256": config.sha256,
        "exact_replay_snapshot_id": payload["exact_replay_snapshot_id"],
        "manifest_path": str(final_manifest.resolve()),
        "manifest_sha256": _sha256_file(final_manifest),
        "parameter_count": len(parameters),
        "bucket_count": 32,
        "signals": payload["signals"],
        "trades": payload["trades"],
        "holdout_accessed": False,
        "global_physical_2023_access_incident": True,
        "holdout_outcomes_observed": False,
    }
    completed_entry = _append(
        ledger,
        "ENTRY_ECONOMIC_EXACT_REPLAY_V2_COMPLETE",
        completion,
    )
    payload["completion_ledger_sequence"] = completed_entry.sequence
    print(json.dumps(_brief(payload), ensure_ascii=False, indent=2))
    return 0


def _run_bucket(
    arguments: tuple[
        int,
        tuple[Path, ...],
        MarkupRetestConfig,
        tuple[StrategyParameters, ...],
        str,
    ]
) -> tuple[ExactReplayResult, float]:
    _, files, config, parameters, panel_snapshot_id = arguments
    started = time.perf_counter()
    result = evaluate_exact_parameter_lattice_files(
        files,
        config,
        StrategyStage.DEVELOPMENT,
        parameters,
        panel_snapshot_id=panel_snapshot_id,
        threads=1,
        vectorized_entry_grid=False,
    )
    return result, time.perf_counter() - started


def _write_bucket(
    target: Path,
    *,
    bucket: int,
    run_id: str,
    result: ExactReplayResult,
    wall_seconds: float,
) -> None:
    if target.exists():
        if _valid_bucket(target, run_id, result.parameters):
            return
        raise FileExistsError(f"incomplete or mismatched bucket output: {target}")
    temp = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    temp.mkdir(parents=True)
    inventory: list[dict[str, Any]] = []
    for name, rows in (
        ("signals.parquet", result.signals),
        ("trades.parquet", result.trades),
        ("open_exposures.parquet", result.open_exposures),
    ):
        path = temp / name
        table = pa.Table.from_pylist(list(rows)) if rows else pa.table({"empty": []})
        pq.write_table(table, path, compression="zstd")
        inventory.append(
            {
                "path": name,
                "rows": table.num_rows,
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    payload = {
        "schema_version": 1,
        "status": "COMPLETE",
        "run_id": run_id,
        "bucket": bucket,
        "parameter_ids": [item.parameter_id for item in result.parameters],
        "input_rows": result.input_rows,
        "evaluation_rows": result.evaluation_rows,
        "signals": len(result.signals),
        "trades": len(result.trades),
        "open_exposures": len(result.open_exposures),
        "worker_wall_seconds": wall_seconds,
        "inventory": inventory,
        "holdout_accessed": False,
    }
    (temp / "manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    temp.replace(target)


def _valid_bucket(
    target: Path,
    run_id: str,
    parameters: Sequence[StrategyParameters],
) -> bool:
    manifest = target / "manifest.json"
    if not manifest.is_file():
        return False
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if (
        payload.get("status") != "COMPLETE"
        or payload.get("run_id") != run_id
        or payload.get("parameter_ids")
        != [item.parameter_id for item in parameters]
    ):
        return False
    for raw in payload.get("inventory", []):
        path = target / str(raw["path"])
        if not path.is_file() or _sha256_file(path) != raw["sha256"]:
            return False
    return True


def _panel_groups(
    files: Sequence[Path],
) -> tuple[tuple[int, tuple[Path, ...]], ...]:
    grouped: dict[int, list[Path]] = {}
    for path in files:
        raw = next(
            (
                part.partition("=")[2]
                for part in path.parts
                if part.startswith("symbol_bucket=")
            ),
            None,
        )
        if raw is None or not raw.isdigit():
            raise ValueError(f"panel file has no symbol bucket: {path}")
        grouped.setdefault(int(raw), []).append(path)
    return tuple(
        (bucket, tuple(sorted(grouped[bucket]))) for bucket in sorted(grouped)
    )


def _assert_development_only(files: Sequence[Path]) -> None:
    years = {
        int(part.partition("=")[2])
        for path in files
        for part in path.parts
        if part.startswith("partition_year=")
    }
    if not years or max(years) > 2022:
        raise ValueError(f"development replay contains forbidden panel years: {years}")


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


def _passing_p0(entries: Sequence[LedgerEntry]) -> LedgerEntry:
    found = [
        item
        for item in entries
        if item.event_type == "PIT_B_TRUE_OOS_CALIBRATION_GATE_COMPLETE"
        and item.payload.get("status") == "PASS"
    ]
    if len(found) != 1:
        raise ValueError("exactly one passing P0 calibration gate is required")
    return found[0]


def _audited_incident(
    config: MarkupRetestConfig, entries: Sequence[LedgerEntry]
) -> LedgerEntry:
    if config.freeze_manifest.exists():
        raise ValueError("development replay must precede strategy freeze")
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
        raise ValueError("holdout outcome or tuning access blocks development replay")
    return incident


def _one(entries: Sequence[LedgerEntry], event_type: str) -> LedgerEntry:
    found = [item for item in entries if item.event_type == event_type]
    if len(found) != 1:
        raise ValueError(f"expected exactly one {event_type}")
    return found[0]


def _append(
    ledger: TrialLedger, event_type: str, payload: Mapping[str, Any]
) -> LedgerEntry:
    for entry in ledger.read_verified():
        if entry.payload.get("event_id") != payload["event_id"]:
            continue
        if entry.event_type != event_type or entry.payload != payload:
            raise ValueError("trial ledger event collision")
        return entry
    return ledger.append(event_type, payload)


def _write_progress(
    root: Path,
    run_id: str,
    completed: set[int],
    total: int,
    workers: int,
) -> None:
    payload = {
        "status": "RUNNING" if len(completed) < total else "PARTS_COMPLETE",
        "run_id": run_id,
        "completed_buckets": sorted(completed),
        "completed_count": len(completed),
        "total_buckets": total,
        "workers": workers,
        "updated_at": datetime.now(UTC).isoformat(),
        "holdout_accessed": False,
    }
    path = root / "progress.json"
    temp = path.with_suffix(".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def _write_immutable_json(path: Path, payload: Mapping[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != raw:
            raise FileExistsError(f"immutable exact replay manifest differs: {path}")
        return
    path.write_text(raw, encoding="utf-8")


def _brief(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": payload["status"],
        "run_id": payload["run_id"],
        "parameter_count": payload["parameter_count"],
        "bucket_count": payload["bucket_count"],
        "signals": payload["signals"],
        "trades": payload["trades"],
        "manifest": payload.get("manifest_path"),
        "holdout_accessed": payload["holdout_accessed"],
        "global_physical_2023_access_incident": payload.get(
            "global_physical_2023_access_incident"
        ),
        "holdout_outcomes_observed": payload.get("holdout_outcomes_observed"),
    }


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
