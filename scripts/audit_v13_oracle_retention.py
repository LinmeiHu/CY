#!/usr/bin/env python3
"""Offline V13 oracle retention, edge replay, and production-equivalent audit.

This program never changes canonical transition semantics.  Commands that
recompute state require the V13 ``parts`` directory to be absent, providing a
fail-closed proof that only registered staged inputs, checkpoints, and the
immutable digest corpus are used.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import resource
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE_PATH = ROOT / "scripts/prototype_chip_checkpoint_recompute.py"
V13_ROOT = ROOT / "data/validation/v12_rc1_2020_output"
STAGE_ROOT = ROOT / "data/validation/v12_rc1_2020_stage"
STRICT_CHECKPOINT_ROOT = ROOT / "data/validation/v12_checkpoint_recompute_50_v1"
AUDIT_ROOT = ROOT / "data/validation/v13_oracle_retention_2020_v1"
PRODUCTION_ROOT = ROOT / "data/validation/v12_checkpoint_production_equivalent_50_v1"
SAMPLE_50 = ROOT / "configs/v12_checkpoint_recompute_50_symbols_v1.txt"
EDGE_10 = ROOT / "configs/v13_edge_suffix_10_symbols_v1.txt"
GIB = 1024**3
MIB = 1024**2
MODEL_COUNT = 3
HASH_BYTES = 32
MOTHER_MIN_TARGET_DAYS = 200


def _load_prototype() -> Any:
    spec = importlib.util.spec_from_file_location("v13_oracle_prototype", PROTOTYPE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load prototype: {PROTOTYPE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


P = _load_prototype()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def _symbol(path: Path) -> str:
    return path.stem.replace("_SZ", ".SZ").replace("_SH", ".SH")


def _path_map(root: Path) -> dict[str, Path]:
    return {_symbol(path): path for path in root.rglob("*.parquet")}


def _inventory(v13_root: Path = V13_ROOT) -> dict[str, Any]:
    parts = _path_map(v13_root / "parts")
    terminal = _path_map(v13_root / "terminal")
    features = _path_map(v13_root / "daily_feature_fact")
    completed = sorted(set(parts) & set(terminal) & set(features))
    return {
        "parts": parts,
        "terminal": terminal,
        "features": features,
        "completed": completed,
        "orphan_parts": sorted(set(parts) - set(completed)),
    }


def _stage_dates(symbol: str) -> list[date]:
    path = next(STAGE_ROOT.glob(f"daily/bucket=*/symbol={symbol}"), None)
    if path is None:
        raise FileNotFoundError(f"registered staged daily input missing: {symbol}")
    return [P.BUILD._date(value) for value in pq.read_table(path, columns=["trade_date"])["trade_date"].to_pylist()]


def classify_symbols(completed: Sequence[str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for symbol in completed:
        dates = sorted(_stage_dates(symbol))
        warmup = [value for value in dates if value.year < 2020]
        target = [value for value in dates if value.year == 2020]
        in_mother = len(target) >= MOTHER_MIN_TARGET_DAYS
        if warmup:
            category = "PRIOR_HISTORY_OPENING"
            opening = "2018_2019_CANONICAL_WARMUP_TERMINAL"
        elif in_mother:
            category = "EARLY_2020_IPO_OPENING_BOUNDARY_IN_MOTHER"
            opening = "FIRST_KNOWN_FLOAT_ROW_INITIAL_UNKNOWN_THEN_EMIT_FROM_NEXT_ROW"
        else:
            category = "IPO_OR_REGISTERED_DATA_START_BOUNDARY_OUTSIDE_MOTHER"
            opening = "FIRST_KNOWN_FLOAT_ROW_INITIAL_UNKNOWN_THEN_EMIT_FROM_NEXT_ROW"
        rows.append(
            {
                "symbol": symbol,
                "category": category,
                "in_400_symbol_mother": in_mother,
                "warmup_days": len(warmup),
                "target_days": len(target),
                "first_registered_date": min(dates).isoformat(),
                "first_target_date": min(target).isoformat(),
                "last_target_date": max(target).isoformat(),
                "opening_semantics": opening,
                "expected_operator_days": max(0, len(target) if warmup else len(target) - 1),
            }
        )
    mother = [row["symbol"] for row in rows if row["in_400_symbol_mother"]]
    boundary = [row for row in rows if not row["in_400_symbol_mother"]]
    if len(completed) != 417 or len(mother) != 400 or len(boundary) != 17:
        raise AssertionError(
            f"unexpected inventory: completed={len(completed)} mother={len(mother)} boundary={len(boundary)}"
        )
    return {
        "mother_min_target_days": MOTHER_MIN_TARGET_DAYS,
        "mother_count": len(mother),
        "outside_mother_count": len(boundary),
        "outside_mother": boundary,
        "all_completed_classification": rows,
    }


def _arrow_table_row_digest(table: pa.Table, index: int) -> bytes:
    # A slice retains parent array offsets/buffers, which are physical Parquet
    # read details rather than row semantics.  Rebuild one typed row so the
    # corpus and recomputation commit the same canonical Arrow representation.
    values = table.slice(index, 1).to_pylist()
    if len(values) != 1:
        raise ValueError("expected exactly one logical Arrow row")
    return P._arrow_row_digest(values[0], table.schema)


def _oracle_symbol(payload: tuple[str, str, str, str]) -> dict[str, Any]:
    symbol, part_raw, terminal_raw, feature_raw = payload
    part_path, terminal_path, feature_path = Path(part_raw), Path(terminal_raw), Path(feature_raw)
    part = pq.read_table(part_path, schema=P.BUILD.OUTPUT_SCHEMA, use_threads=False).combine_chunks()
    oracle_part = part.select(P.ORACLE_OUTPUT_SCHEMA.names)
    feature = pq.read_table(feature_path, schema=P.FACT_SCHEMA, use_threads=False).combine_chunks()
    terminal = pq.read_table(terminal_path, schema=P.BUILD.TERMINAL_SCHEMA, use_threads=False).combine_chunks()
    if part.num_rows != feature.num_rows * MODEL_COUNT or terminal.num_rows != MODEL_COUNT:
        raise AssertionError(f"{symbol}: V13 row cardinality mismatch")
    part_keys = part.select(["trade_date", "seller_model"]).to_pylist()
    feature_rows = feature.to_pylist()
    dates = [P.BUILD._date(row["trade_date"]) for row in feature_rows]
    for day_index, day in enumerate(dates):
        actual = part_keys[day_index * MODEL_COUNT : (day_index + 1) * MODEL_COUNT]
        wanted = [
            {"trade_date": day, "seller_model": model.value}
            for model in P.SELLER_MODEL_ORDER
        ]
        if actual != wanted:
            raise AssertionError(f"{symbol} {day}: seller-model ordering mismatch")
    model_digests = np.empty((len(dates), MODEL_COUNT, HASH_BYTES), dtype=np.uint8)
    for index in range(part.num_rows):
        model_digests[index // MODEL_COUNT, index % MODEL_COUNT] = np.frombuffer(
            _arrow_table_row_digest(oracle_part, index), dtype=np.uint8
        )
    feature_digests = np.empty((len(dates), HASH_BYTES), dtype=np.uint8)
    for index, row in enumerate(feature_rows):
        feature_digests[index] = np.frombuffer(P._feature_digest(row), dtype=np.uint8)
    terminal_digests = np.empty((MODEL_COUNT, HASH_BYTES), dtype=np.uint8)
    for index in range(MODEL_COUNT):
        terminal_digests[index] = np.frombuffer(_arrow_table_row_digest(terminal, index), dtype=np.uint8)
    sources = {}
    for name, path in (("part", part_path), ("terminal", terminal_path), ("daily_feature_fact", feature_path)):
        sources[name] = {
            "path": str(path.relative_to(ROOT)),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
    return {
        "symbol": symbol,
        "dates": np.asarray([P._day_code(value) for value in dates], dtype=np.int32),
        "model_digests": model_digests,
        "feature_digests": feature_digests,
        "terminal_digests": terminal_digests,
        "sources": sources,
    }


def _oracle_payloads(inventory: Mapping[str, Any]) -> list[tuple[str, str, str, str]]:
    return [
        (
            symbol,
            str(inventory["parts"][symbol]),
            str(inventory["terminal"][symbol]),
            str(inventory["features"][symbol]),
        )
        for symbol in inventory["completed"]
    ]


def _run_oracle_workers(payloads: Sequence[tuple[str, str, str, str]], workers: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=min(workers, len(payloads))) as executor:
        futures = {executor.submit(_oracle_symbol, payload): payload[0] for payload in payloads}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(json.dumps({"symbol": result["symbol"], "oracle": "DIGESTED"}), flush=True)
    results.sort(key=lambda item: str(item["symbol"]))
    return results


def build_oracle(workers: int, output: Path) -> Path:
    output = output.resolve()
    inventory = _inventory()
    if len(inventory["completed"]) != 417:
        raise AssertionError(f"expected 417 completed symbols, got {len(inventory['completed'])}")
    classification = classify_symbols(inventory["completed"])
    started = time.perf_counter()
    results = _run_oracle_workers(_oracle_payloads(inventory), workers)
    offsets = [0]
    dates: list[np.ndarray[Any, Any]] = []
    model_digests: list[np.ndarray[Any, Any]] = []
    feature_digests: list[np.ndarray[Any, Any]] = []
    terminal_digests: list[np.ndarray[Any, Any]] = []
    symbols: list[str] = []
    sources: dict[str, Any] = {}
    for result in results:
        symbols.append(result["symbol"])
        dates.append(result["dates"])
        model_digests.append(result["model_digests"])
        feature_digests.append(result["feature_digests"])
        terminal_digests.append(result["terminal_digests"])
        offsets.append(offsets[-1] + len(result["dates"]))
        sources[result["symbol"]] = result["sources"]
    arrays = {
        "format_version": np.asarray([1], dtype=np.uint16),
        "symbols": np.asarray(symbols, dtype="<U9"),
        "symbol_day_offsets": np.asarray(offsets, dtype=np.uint64),
        "day_dates": np.concatenate(dates),
        "model_row_digests": np.concatenate(model_digests),
        "feature_digests": np.concatenate(feature_digests),
        "terminal_row_digests": np.stack(terminal_digests),
    }
    output.mkdir(parents=True, exist_ok=True)
    temporary = output / ".oracle_digest_corpus.tmp.npz"
    with temporary.open("wb") as handle:
        np.savez_compressed(handle, **arrays)
    corpus_sha = _sha256(temporary)
    corpus = output / f"oracle_digest_corpus_v1_sha256_{corpus_sha}.npz"
    temporary.replace(corpus)
    corpus.chmod(0o444)
    orphan_sources = {}
    for symbol in inventory["orphan_parts"]:
        path = inventory["parts"][symbol]
        orphan_sources[symbol] = {
            "path": str(path.relative_to(ROOT)),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
    manifest = {
        "schema_version": "v13-oracle-digest-corpus-v1",
        "status": "ORACLE_COMPLETE_UNVERIFIED",
        "created_at": _now(),
        "source_operator_log_version": P.BUILD.STORAGE_VERSION,
        "operator_oracle_contract": {
            "included_columns": P.ORACLE_OUTPUT_SCHEMA.names,
            "excluded_legacy_daily_checkpoint_columns": sorted(P.LEGACY_DAILY_CHECKPOINT_COLUMNS),
            "exclusion_reason": "monthly checkpoint architecture forbids legacy daily full-state checkpoint vectors; all production-required operator fields remain exact",
        },
        "source_root": str(V13_ROOT.relative_to(ROOT)),
        "completed_symbol_count": len(symbols),
        "part_file_count": len(inventory["parts"]),
        "orphan_part_count": len(inventory["orphan_parts"]),
        "day_count": int(offsets[-1]),
        "model_row_digest_count": int(offsets[-1] * MODEL_COUNT),
        "feature_digest_count": int(offsets[-1]),
        "terminal_digest_count": int(len(symbols) * MODEL_COUNT),
        "corpus": {
            "path": str(corpus.relative_to(ROOT)),
            "bytes": corpus.stat().st_size,
            "sha256": corpus_sha,
            "mode": "0444",
            "physical_representation": "flat NumPy arrays + symbol offsets; allow_pickle=False",
        },
        "classification": classification,
        "sources": sources,
        "orphan_part_sources": orphan_sources,
        "build_wall_seconds": time.perf_counter() - started,
    }
    _atomic_json(output / "oracle_manifest.json", manifest)
    return output / "oracle_manifest.json"


def _load_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"manifest is not an object: {path}")
    return value


def verify_oracle(workers: int, manifest_path: Path) -> Path:
    manifest = _load_manifest(manifest_path)
    corpus = ROOT / manifest["corpus"]["path"]
    if _sha256(corpus) != manifest["corpus"]["sha256"]:
        raise AssertionError("oracle corpus SHA-256 mismatch")
    with np.load(corpus, allow_pickle=False) as archive:
        arrays = {name: archive[name] for name in archive.files}
    if any(array.dtype.kind == "O" for array in arrays.values()):
        raise AssertionError("oracle corpus contains an object array")
    inventory = _inventory()
    results = _run_oracle_workers(_oracle_payloads(inventory), workers)
    symbols = [str(value) for value in arrays["symbols"]]
    if symbols != [result["symbol"] for result in results]:
        raise AssertionError("oracle symbol ordering mismatch")
    for index, result in enumerate(results):
        start = int(arrays["symbol_day_offsets"][index])
        stop = int(arrays["symbol_day_offsets"][index + 1])
        checks = (
            (arrays["day_dates"][start:stop], result["dates"], "dates"),
            (arrays["model_row_digests"][start:stop], result["model_digests"], "model digests"),
            (arrays["feature_digests"][start:stop], result["feature_digests"], "feature digests"),
            (arrays["terminal_row_digests"][index], result["terminal_digests"], "terminal digests"),
        )
        for actual, expected, label in checks:
            if not np.array_equal(actual, expected):
                raise AssertionError(f"{result['symbol']}: oracle {label} mismatch")
        if manifest["sources"][result["symbol"]] != result["sources"]:
            raise AssertionError(f"{result['symbol']}: source file digest mismatch")
    manifest["status"] = "ORACLE_COMPLETE_VERIFIED"
    manifest["verified_at"] = _now()
    manifest["verification"] = {
        "method": "independent full regeneration of every completed-symbol row digest",
        "completed_symbol_count": len(results),
        "mismatches": 0,
        "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
    }
    _atomic_json(manifest_path, manifest)
    return manifest_path


def _oracle_lookup(manifest_path: Path) -> tuple[dict[str, dict[date, tuple[tuple[bytes, ...], bytes]]], str]:
    manifest = _load_manifest(manifest_path)
    if manifest.get("status") != "ORACLE_COMPLETE_VERIFIED":
        raise RuntimeError("oracle is not verified")
    corpus = ROOT / manifest["corpus"]["path"]
    if _sha256(corpus) != manifest["corpus"]["sha256"]:
        raise AssertionError("oracle corpus changed")
    with np.load(corpus, allow_pickle=False) as archive:
        symbols = [str(value) for value in archive["symbols"]]
        offsets = archive["symbol_day_offsets"]
        dates = archive["day_dates"]
        model = archive["model_row_digests"]
        feature = archive["feature_digests"]
        result: dict[str, dict[date, tuple[tuple[bytes, ...], bytes]]] = {}
        for index, symbol in enumerate(symbols):
            start, stop = int(offsets[index]), int(offsets[index + 1])
            result[symbol] = {
                P._code_day(int(dates[position])): (
                    tuple(bytes(value) for value in model[position]),
                    bytes(feature[position]),
                )
                for position in range(start, stop)
            }
    return result, manifest["corpus"]["sha256"]


def _install_parts_read_guard(parts_root: Path) -> list[str]:
    forbidden = parts_root.resolve()
    hits: list[str] = []

    def guard(event: str, args: tuple[Any, ...]) -> None:
        if event != "open" or not args:
            return
        raw = args[0]
        if not isinstance(raw, (str, bytes, os.PathLike)):
            return
        try:
            path = Path(raw).resolve()
        except (OSError, TypeError):
            return
        if path == forbidden or forbidden in path.parents:
            hits.append(str(path))
            raise RuntimeError(f"V13 parts read is forbidden during recompute: {path}")

    sys.addaudithook(guard)
    return hits


def _edge_symbol_worker(payload: tuple[str, str, str, str, str]) -> dict[str, Any]:
    symbol, checkpoint_raw, stage_raw, manifest_raw, forbidden_raw = payload
    forbidden = Path(forbidden_raw)
    if forbidden.exists():
        raise RuntimeError(f"V13 parts must be absent for recompute proof: {forbidden}")
    guard_hits = _install_parts_read_guard(forbidden)
    oracle, corpus_sha = _oracle_lookup(Path(manifest_raw))
    expected = oracle[symbol]
    daily, minute_by_date = P._read_symbol_inputs(Path(stage_raw), symbol)
    target = sorted(
        (row for row in daily if P.BUILD._date(row["trade_date"]).year == 2020),
        key=lambda row: P.BUILD._date(row["trade_date"]),
    )
    checkpoint_root = Path(checkpoint_raw) / f"symbol={symbol}" / "checkpoints"
    paths = sorted(checkpoint_root.glob("*.npz"))
    if len(paths) != 13:
        raise AssertionError(f"{symbol}: expected 13 existing checkpoints, got {len(paths)}")
    december = next(path for path in paths if path.name.startswith("month-12-"))
    terminal_snapshots, terminal_tracker = P.load_checkpoint(december)
    terminal_digest = P._digest(
        (
            tuple(
                P._snapshot_digest(
                    terminal_snapshots[model]
                    if isinstance(terminal_snapshots[model], P.ChipSnapshotV2)
                    else terminal_snapshots[model].to_snapshot()
                )
                for model in P.SELLER_MODEL_ORDER
            ),
            P._tracker_digest(terminal_tracker),
        )
    )
    checkpoint_results = []
    for path in paths:
        snapshots, tracker = P.load_checkpoint(path)
        checkpoint_day = next(iter(snapshots.values())).trading_date
        suffix = [row for row in target if P.BUILD._date(row["trade_date"]) > checkpoint_day]
        replay = P.replay_target(
            symbol=symbol,
            rows=suffix,
            minute_by_date=minute_by_date,
            initial_snapshots=snapshots,
            tracker=tracker,
            capture_checkpoints=False,
            validation_evidence=False,
            capture_oracle_rows=True,
        )
        for day in replay.days:
            wanted_rows, wanted_feature = expected[day.trading_date]
            if day.oracle_row_digests != wanted_rows:
                raise AssertionError(f"{symbol} {path.name} {day.trading_date}: V13 oracle-row mismatch")
            if day.feature_digest != wanted_feature:
                raise AssertionError(f"{symbol} {path.name} {day.trading_date}: feature oracle mismatch")
        observed_terminal = P._digest(
            (
                tuple(P._snapshot_digest(replay.final_snapshots[model]) for model in P.SELLER_MODEL_ORDER),
                P._tracker_digest(tracker),
            )
        )
        if observed_terminal != terminal_digest:
            raise AssertionError(f"{symbol} {path.name}: suffix terminal mismatch")
        semantic_digest = P._digest(
            tuple(
                (
                    day.trading_date,
                    day.operator_digests,
                    day.post_digests,
                    day.feature_digest,
                    day.oracle_row_digests,
                )
                for day in replay.days
            )
        ).hex()
        checkpoint_results.append(
            {
                "checkpoint": path.name,
                "checkpoint_date": checkpoint_day.isoformat(),
                "suffix_days": len(replay.days),
                "semantic_digest": semantic_digest,
                "terminal_digest": observed_terminal.hex(),
            }
        )
    return {
        "symbol": symbol,
        "checkpoint_count": len(checkpoint_results),
        "oracle_corpus_sha256": corpus_sha,
        "guard_hits": guard_hits,
        "checkpoints": checkpoint_results,
    }


def edge_worker(
    manifest_path: Path,
    checkpoint_root: Path,
    symbols_file: Path,
    output: Path,
    workers: int,
    forbidden_parts: Path,
) -> Path:
    output = output.resolve()
    symbols = [value.strip() for value in symbols_file.read_text(encoding="utf-8").splitlines() if value.strip()]
    payloads = [
        (symbol, str(checkpoint_root), str(STAGE_ROOT), str(manifest_path), str(forbidden_parts))
        for symbol in symbols
    ]
    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=min(workers, len(payloads))) as executor:
        futures = {executor.submit(_edge_symbol_worker, payload): payload[0] for payload in payloads}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(json.dumps({"symbol": result["symbol"], "suffix": "PASS"}), flush=True)
    results.sort(key=lambda item: symbols.index(item["symbol"]))
    semantic_root = P._digest(
        tuple(
            (
                item["symbol"],
                tuple(
                    (row["checkpoint"], row["suffix_days"], row["semantic_digest"], row["terminal_digest"])
                    for row in item["checkpoints"]
                ),
            )
            for item in results
        )
    ).hex()
    report = {
        "status": "PASS",
        "process_id": os.getpid(),
        "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
        "v13_parts_required_absent": str(forbidden_parts),
        "v13_parts_present": forbidden_parts.exists(),
        "guard_hits": sum(len(item["guard_hits"]) for item in results),
        "symbol_count": len(results),
        "checkpoint_suffix_count": sum(item["checkpoint_count"] for item in results),
        "semantic_root": semantic_root,
        "wall_seconds": time.perf_counter() - started,
        "symbols": results,
    }
    _atomic_json(output, report)
    return output


def _allocated_bytes(paths: Sequence[Path]) -> int:
    return sum(int(getattr(path.stat(), "st_blocks", 0)) * 512 for path in paths)


def _production_symbol(payload: tuple[str, str, str, str]) -> dict[str, Any]:
    symbol, stage_raw, output_raw, forbidden_raw = payload
    forbidden = Path(forbidden_raw)
    if forbidden.exists():
        raise RuntimeError(f"V13 parts must be absent for production benchmark: {forbidden}")
    guard_hits = _install_parts_read_guard(forbidden)
    output = Path(output_raw)
    symbol_root = output / f"symbol={symbol}"
    checkpoint_root = symbol_root / "checkpoints"
    daily, minute_by_date = P._read_symbol_inputs(Path(stage_raw), symbol)
    warmup = sorted(
        (row for row in daily if P.BUILD._date(row["trade_date"]).year < 2020),
        key=lambda row: P.BUILD._date(row["trade_date"]),
    )
    target = sorted(
        (row for row in daily if P.BUILD._date(row["trade_date"]).year == 2020),
        key=lambda row: P.BUILD._date(row["trade_date"]),
    )
    if not warmup or not target:
        raise ValueError(f"{symbol}: production benchmark sample requires warmup and target rows")
    warmup_minute = [row for day, rows in minute_by_date.items() if day.year < 2020 for row in rows]
    _, opening_snapshots = P.BUILD._run_symbol(
        symbol, warmup, warmup_minute, 2019, None, emit_operators=False
    )
    opening_tracker = P.EnsembleTemporalPeakTracker(symbol=symbol, models=P.TRACKER_MODELS)
    opening = P.Checkpoint("opening", opening_snapshots, opening_tracker)
    checkpoint_paths: list[Path] = []
    checkpoint_bytes: list[int] = []

    def persist(checkpoint: Any) -> None:
        path = checkpoint_root / P._checkpoint_name(checkpoint)
        stats = P.write_checkpoint(path, checkpoint, measure_separate_models=False)
        checkpoint_paths.append(path)
        checkpoint_bytes.append(int(stats["shared_bytes"]))

    started = time.perf_counter()
    persist(opening)
    restored, tracker = P.load_checkpoint(checkpoint_paths[0])
    replay = P.replay_target(
        symbol=symbol,
        rows=target,
        minute_by_date=minute_by_date,
        initial_snapshots=restored,
        tracker=tracker,
        capture_checkpoints=True,
        validation_evidence=False,
        capture_oracle_rows=False,
        checkpoint_sink=persist,
    )
    if len(checkpoint_paths) != 13:
        raise AssertionError(f"{symbol}: production pass wrote {len(checkpoint_paths)} checkpoints")
    if any(day.identity_digests or day.share_digests or day.oracle_row_digests for day in replay.days):
        raise AssertionError(f"{symbol}: production pass retained validation-only daily evidence")
    journal_path = symbol_root / "daily_replay_journal.npz"
    journal_bytes = P.write_journal(journal_path, replay.days)
    manifest = {
        "prototype": P.PROTOTYPE_VERSION,
        "mode": "production-equivalent-single-pass",
        "symbol": symbol,
        "year": 2020,
        "checkpoint_count": len(checkpoint_paths),
        "journal_days": len(replay.days),
        "checkpoint_files": [path.name for path in checkpoint_paths],
        "journal_file": journal_path.name,
        "production_required_daily_payload": [
            "immutable_input_references_and_digests",
            "corporate_action_facts",
            "model_transition_runtime_hashes",
            "operator_digest",
            "post_state_digest",
            "feature_digest",
        ],
        "excluded_validation_work": [
            "duplicate_horizon_replay",
            "month_segment_replay",
            "validation_lifecycle",
            "daily_identity_digest",
            "daily_share_digest",
            "oracle_row_digest",
            "separate_model_counterfactual_write",
        ],
    }
    manifest_path = symbol_root / "manifest.json"
    _atomic_json(manifest_path, manifest)
    elapsed = time.perf_counter() - started
    paths = [*checkpoint_paths, journal_path, manifest_path]
    logical = sum(path.stat().st_size for path in paths)
    return {
        "symbol": symbol,
        "seconds": elapsed,
        "checkpoint_bytes": sum(checkpoint_bytes),
        "journal_bytes": journal_bytes,
        "manifest_bytes": manifest_path.stat().st_size,
        "logical_total_bytes": logical,
        "allocated_total_bytes": _allocated_bytes(paths),
        "file_count": len(paths),
        "peak_memory_mib": P._rss_mib(),
        "guard_hits": guard_hits,
    }


def _quantiles(values: Sequence[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float64)
    return {
        "mean": float(np.mean(array)),
        "p50": float(np.percentile(array, 50)),
        "p90": float(np.percentile(array, 90)),
        "p99": float(np.percentile(array, 99)),
        "max": float(np.max(array)),
    }


def production_benchmark(
    symbols_file: Path,
    output: Path,
    workers: int,
    forbidden_parts: Path,
) -> Path:
    output = output.resolve()
    symbols = [value.strip() for value in symbols_file.read_text(encoding="utf-8").splitlines() if value.strip()]
    payloads = [(symbol, str(STAGE_ROOT), str(output), str(forbidden_parts)) for symbol in symbols]
    # Existing strict artifact size is a deterministic scheduling proxy; largest first.
    strict_report = _load_manifest(STRICT_CHECKPOINT_ROOT / "benchmark_report.json")
    weights = {row["symbol"]: int(row["total_bytes"]) for row in strict_report["symbols"]}
    payloads.sort(key=lambda value: weights.get(value[0], 0), reverse=True)
    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=min(workers, len(payloads))) as executor:
        futures = {executor.submit(_production_symbol, payload): payload[0] for payload in payloads}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(json.dumps({"symbol": result["symbol"], "production_equivalent": "PASS"}), flush=True)
    results.sort(key=lambda item: symbols.index(item["symbol"]))
    seconds = _quantiles([float(item["seconds"]) for item in results])
    checkpoint = _quantiles([float(item["checkpoint_bytes"]) for item in results])
    journal = _quantiles([float(item["journal_bytes"]) for item in results])
    logical = _quantiles([float(item["logical_total_bytes"]) for item in results])
    allocated = _quantiles([float(item["allocated_total_bytes"]) for item in results])
    global_allowance = 256 * MIB
    report = {
        "status": "PASS",
        "approval": "SEMANTIC_PROTOTYPE_PASS",
        "not_approved": "FULL_MARKET_PRODUCTION_APPROVED",
        "mode": "production-equivalent-single-pass",
        "sample_symbols": len(results),
        "workers": workers,
        "v13_parts_present": forbidden_parts.exists(),
        "v13_read_guard_hits": sum(len(item["guard_hits"]) for item in results),
        "seconds_per_symbol": seconds,
        "checkpoint_bytes_per_symbol": checkpoint,
        "journal_bytes_per_symbol": journal,
        "logical_total_bytes_per_symbol": logical,
        "allocated_total_bytes_per_symbol": allocated,
        "estimated_5210_symbol_wall_hours": {
            "mean_at_benchmark_workers": seconds["mean"] * 5210 / workers / 3600,
            "p90_at_benchmark_workers": seconds["p90"] * 5210 / workers / 3600,
            "p99_at_benchmark_workers": seconds["p99"] * 5210 / workers / 3600,
            "max_at_benchmark_workers": seconds["max"] * 5210 / workers / 3600,
        },
        "capacity": {
            "estimated_mean_logical_gib": logical["mean"] * 5210 / GIB,
            "p99_allocated_gib": allocated["p99"] * 5210 / GIB,
            "max_allocated_gib": allocated["max"] * 5210 / GIB,
            "conservative_upper_bound_gib": allocated["max"] * 5210 / GIB + global_allowance / GIB,
            "conservative_formula": "sample max allocated bytes/symbol * 5210 + 256 MiB global index/manifest allowance",
        },
        "capacity_scope": {
            "checkpoints": True,
            "minimal_journal": True,
            "per_symbol_manifest": True,
            "daily_feature_fact": False,
            "global_index_and_manifests": False,
            "filesystem_allocation_overhead_in_logical_estimate": False,
            "filesystem_allocation_overhead_in_conservative_bound": True,
            "raw_registered_inputs": False,
            "reason_raw_inputs_excluded": "registered source assets are not chip-derived durable artifacts",
        },
        "original_37_678_gib_scope": {
            "checkpoints": True,
            "minimal_journal": True,
            "per_symbol_manifest": True,
            "daily_feature_fact": False,
            "global_index_and_manifests": False,
            "filesystem_overhead": False,
            "raw_registered_inputs": False,
        },
        "benchmark_wall_seconds": time.perf_counter() - started,
        "peak_memory_mib": _quantiles([float(item["peak_memory_mib"]) for item in results]),
        "symbols": results,
    }
    output.mkdir(parents=True, exist_ok=True)
    path = output / "production_equivalent_report.json"
    _atomic_json(path, report)
    return path


def make_plans(
    oracle_manifest_path: Path,
    edge_reports: Sequence[Path],
    production_report_path: Path,
    output: Path,
    retained_symbols_file: Path,
) -> tuple[Path, Path]:
    output = output.resolve()
    oracle = _load_manifest(oracle_manifest_path)
    if oracle.get("status") != "ORACLE_COMPLETE_VERIFIED":
        raise RuntimeError("cannot plan deletion before oracle verification")
    edges = [_load_manifest(path) for path in edge_reports]
    if len(edges) < 2 or any(report.get("status") != "PASS" for report in edges):
        raise RuntimeError("two passing edge replay reports are required")
    if len({report.get("process_id") for report in edges}) != len(edges):
        raise RuntimeError("edge replay reports did not come from independent processes")
    seeds = {str(report.get("pythonhashseed")) for report in edges}
    if len(seeds) < 2:
        raise RuntimeError("edge replay reports require different PYTHONHASHSEED values")
    semantic_roots = {report.get("semantic_root") for report in edges}
    if len(semantic_roots) != 1:
        raise RuntimeError("edge replay semantic roots differ across hash seeds")
    if any(report.get("v13_parts_present") or report.get("guard_hits") for report in edges):
        raise RuntimeError("edge replay V13 parts read-denial proof failed")
    production = _load_manifest(production_report_path)
    if production.get("status") != "PASS" or production.get("v13_parts_present"):
        raise RuntimeError("production-equivalent benchmark did not pass read isolation")
    retained_symbols = [
        value.strip() for value in retained_symbols_file.read_text(encoding="utf-8").splitlines() if value.strip()
    ]
    inventory = _inventory()
    retained_parts = [inventory["parts"][symbol] for symbol in retained_symbols]
    deletion_parts = [path for symbol, path in sorted(inventory["parts"].items()) if symbol not in retained_symbols]
    retention = {
        "schema_version": "v13-retention-manifest-v1",
        "created_at": _now(),
        "approval": "SEMANTIC_PROTOTYPE_PASS",
        "not_approved": "FULL_MARKET_PRODUCTION_APPROVED",
        "retained_v13_part_symbols": retained_symbols,
        "retained_v13_parts": [str(path.relative_to(ROOT)) for path in retained_parts],
        "retained_v13_terminal_count": len(inventory["terminal"]),
        "retained_v13_daily_feature_fact_count": len(inventory["features"]),
        "retained_oracle_manifest": str(oracle_manifest_path.relative_to(ROOT)),
        "retained_oracle_corpus": oracle["corpus"],
        "retained_registered_inputs": str(STAGE_ROOT.relative_to(ROOT)),
        "retained_production_equivalent_report": str(production_report_path.relative_to(ROOT)),
        "retained_edge_reports": [str(path.relative_to(ROOT)) for path in edge_reports],
        "rationale": "retain 10 edge operator parts plus all terminal/features until full-market production approval; delete other V13 operator parts only",
    }
    retention_path = output / "retention_manifest.json"
    _atomic_json(retention_path, retention)
    source_by_path = {
        value["part"]["path"]: value["part"]
        for value in oracle["sources"].values()
    }
    source_by_path.update(
        {value["path"]: value for value in oracle["orphan_part_sources"].values()}
    )
    entries = []
    for path in deletion_parts:
        relative = str(path.relative_to(ROOT))
        source = source_by_path.get(relative)
        if source is None:
            raise RuntimeError(f"deletion target lacks immutable source digest: {relative}")
        entries.append(
            {
                "path": relative,
                "bytes": int(source["bytes"]),
                "sha256": source["sha256"],
                "symbol": _symbol(path),
                "reason": "NON_RETAINED_V13_OPERATOR_PART",
            }
        )
    deletion = {
        "schema_version": "v13-deletion-plan-v1",
        "status": "PLANNED",
        "created_at": _now(),
        "preconditions": {
            "oracle_status": oracle["status"],
            "oracle_corpus_sha256": oracle["corpus"]["sha256"],
            "edge_process_ids": [report["process_id"] for report in edges],
            "edge_pythonhashseeds": sorted(seeds),
            "edge_semantic_root": next(iter(semantic_roots)),
            "v13_parts_absent_during_recompute": True,
            "production_equivalent_status": production["status"],
        },
        "retention_manifest": str(retention_path.relative_to(ROOT)),
        "delete_file_count": len(entries),
        "delete_bytes": sum(item["bytes"] for item in entries),
        "retained_part_count": len(retained_parts),
        "entries": entries,
    }
    deletion_path = output / "deletion_plan.json"
    _atomic_json(deletion_path, deletion)
    return retention_path, deletion_path


def execute_deletion(plan_path: Path) -> Path:
    plan = _load_manifest(plan_path)
    if plan.get("status") != "PLANNED":
        raise RuntimeError(f"deletion plan is not PLANNED: {plan.get('status')}")
    if plan.get("preconditions", {}).get("oracle_status") != "ORACLE_COMPLETE_VERIFIED":
        raise RuntimeError("deletion plan lacks verified oracle precondition")
    parts_root = (V13_ROOT / "parts").resolve()
    targets: list[Path] = []
    for entry in plan["entries"]:
        path = (ROOT / entry["path"]).resolve()
        if parts_root not in path.parents or path.suffix != ".parquet":
            raise RuntimeError(f"unsafe deletion target: {path}")
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.stat().st_size != int(entry["bytes"]) or _sha256(path) != entry["sha256"]:
            raise RuntimeError(f"deletion target changed after planning: {path}")
        targets.append(path)
    for path in targets:
        path.unlink()
    # Remove only now-empty bucket directories; never recursively delete.
    for directory in sorted({path.parent for path in targets}, key=lambda value: len(value.parts), reverse=True):
        if directory.exists() and not any(directory.iterdir()):
            directory.rmdir()
    missing = [str(path) for path in targets if path.exists()]
    if missing:
        raise RuntimeError(f"some planned targets still exist: {missing[:3]}")
    plan["status"] = "EXECUTED"
    plan["executed_at"] = _now()
    plan["deleted_file_count"] = len(targets)
    plan["deleted_bytes"] = sum(int(entry["bytes"]) for entry in plan["entries"])
    plan["recoverable"] = False
    _atomic_json(plan_path, plan)
    return plan_path


def _run_subprocess_edge(args: argparse.Namespace) -> int:
    outputs = []
    for seed in ("1", "777"):
        output = args.output / f"edge_suffix_replay_seed_{seed}.json"
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "edge-worker",
            "--manifest",
            str(args.manifest),
            "--checkpoint-root",
            str(args.checkpoint_root),
            "--symbols-file",
            str(args.symbols_file),
            "--output",
            str(output),
            "--workers",
            str(args.workers),
            "--forbidden-parts",
            str(args.forbidden_parts),
        ]
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = seed
        subprocess.run(command, check=True, env=environment, cwd=ROOT)
        outputs.append(output)
    left, right = (_load_manifest(path) for path in outputs)
    if left["process_id"] == right["process_id"] or left["pythonhashseed"] == right["pythonhashseed"]:
        raise AssertionError("edge runs were not independent/hash-seed distinct")
    if left["semantic_root"] != right["semantic_root"]:
        raise AssertionError("edge semantic root differs by PYTHONHASHSEED")
    print("\n".join(str(path) for path in outputs))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    inventory_parser = sub.add_parser("inventory")
    inventory_parser.add_argument("--output", type=Path, default=AUDIT_ROOT / "inventory.json")
    build = sub.add_parser("build-oracle")
    build.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    build.add_argument("--output", type=Path, default=AUDIT_ROOT)
    verify = sub.add_parser("verify-oracle")
    verify.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    verify.add_argument("--manifest", type=Path, default=AUDIT_ROOT / "oracle_manifest.json")
    edge = sub.add_parser("edge-worker")
    edge.add_argument("--manifest", type=Path, required=True)
    edge.add_argument("--checkpoint-root", type=Path, default=STRICT_CHECKPOINT_ROOT)
    edge.add_argument("--symbols-file", type=Path, default=EDGE_10)
    edge.add_argument("--output", type=Path, required=True)
    edge.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    edge.add_argument("--forbidden-parts", type=Path, default=V13_ROOT / "parts")
    edge_both = sub.add_parser("edge-both-seeds")
    edge_both.add_argument("--manifest", type=Path, default=AUDIT_ROOT / "oracle_manifest.json")
    edge_both.add_argument("--checkpoint-root", type=Path, default=STRICT_CHECKPOINT_ROOT)
    edge_both.add_argument("--symbols-file", type=Path, default=EDGE_10)
    edge_both.add_argument("--output", type=Path, default=AUDIT_ROOT)
    edge_both.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    edge_both.add_argument("--forbidden-parts", type=Path, default=V13_ROOT / "parts")
    production = sub.add_parser("production-benchmark")
    production.add_argument("--symbols-file", type=Path, default=SAMPLE_50)
    production.add_argument("--output", type=Path, default=PRODUCTION_ROOT)
    production.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    production.add_argument("--forbidden-parts", type=Path, default=V13_ROOT / "parts")
    plans = sub.add_parser("make-plans")
    plans.add_argument("--oracle-manifest", type=Path, default=AUDIT_ROOT / "oracle_manifest.json")
    plans.add_argument(
        "--edge-report",
        type=Path,
        action="append",
        default=[AUDIT_ROOT / "edge_suffix_replay_seed_1.json", AUDIT_ROOT / "edge_suffix_replay_seed_777.json"],
    )
    plans.add_argument("--production-report", type=Path, default=PRODUCTION_ROOT / "production_equivalent_report.json")
    plans.add_argument("--output", type=Path, default=AUDIT_ROOT)
    plans.add_argument("--retained-symbols-file", type=Path, default=EDGE_10)
    deletion = sub.add_parser("execute-deletion")
    deletion.add_argument("--plan", type=Path, default=AUDIT_ROOT / "deletion_plan.json")
    args = parser.parse_args()

    if args.command == "inventory":
        inventory = _inventory()
        value = {
            "created_at": _now(),
            "part_count": len(inventory["parts"]),
            "terminal_count": len(inventory["terminal"]),
            "daily_feature_fact_count": len(inventory["features"]),
            "completed_count": len(inventory["completed"]),
            "orphan_parts": inventory["orphan_parts"],
            "classification": classify_symbols(inventory["completed"]),
        }
        _atomic_json(args.output, value)
        print(args.output)
    elif args.command == "build-oracle":
        print(build_oracle(args.workers, args.output))
    elif args.command == "verify-oracle":
        print(verify_oracle(args.workers, args.manifest))
    elif args.command == "edge-worker":
        print(edge_worker(args.manifest, args.checkpoint_root, args.symbols_file, args.output, args.workers, args.forbidden_parts))
    elif args.command == "edge-both-seeds":
        return _run_subprocess_edge(args)
    elif args.command == "production-benchmark":
        print(production_benchmark(args.symbols_file, args.output, args.workers, args.forbidden_parts))
    elif args.command == "make-plans":
        print("\n".join(str(path) for path in make_plans(args.oracle_manifest, args.edge_report, args.production_report, args.output, args.retained_symbols_file)))
    elif args.command == "execute-deletion":
        print(execute_deletion(args.plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
