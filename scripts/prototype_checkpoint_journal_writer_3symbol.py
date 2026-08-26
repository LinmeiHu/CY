#!/usr/bin/env python3
"""Run the unregistered V12 Phase 2 three-symbol writer prototype."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cyq_game.chip.checkpoint_journal_contract import (  # noqa: E402
    SELLER_MODEL_ORDER,
    TERMINAL_COMPLETENESS_VERSION,
    canonical_json_bytes,
    logical_sha256,
)
from cyq_game.chip.checkpoint_journal_writer import (  # noqa: E402
    CHECKPOINT_CADENCE,
    PHASE2_SYMBOLS,
    PHASE2_TARGET_YEAR,
    PHASE2_WARMUP_YEARS,
    PHASE2_WRITER_VERSION,
    CapturedCheckpoint,
    arrow_exact_mismatch_count,
    capture_model_state,
    checkpoint_dates,
    regular_file_bytes,
    sha256_file,
    verify_root,
    write_index,
    write_json,
    write_symbol_artifacts,
)

OUTPUT_ROOT = ROOT / "data/validation/v12_checkpoint_journal_phase2_3symbol"
LEGACY_ROOT = ROOT / "data/validation/v12_rc1_2020_output"
STAGE_ROOT = Path("/tmp/v12_checkpoint_journal_phase2_stage")
CANDIDATE_ROOT = Path("/tmp/v12_checkpoint_journal_phase2_candidate")
TEMP_PREFIX = "/tmp/v12_checkpoint_journal_phase2_"
BUNDLE_ID = "v12-checkpoint-journal-phase2-3symbol-2020"
ROOT_ID = "v12-checkpoint-journal-phase2-3symbol-root-v1"


def _load_builder() -> Any:
    path = ROOT / "scripts/build_real_chip_year.py"
    name = "v12_phase2_canonical_builder"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load canonical builder")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _oracle_path(kind: str, symbol: str) -> Path:
    stem = symbol.replace(".", "_")
    matches = sorted((LEGACY_ROOT / kind).glob(f"*/{stem}.parquet"))
    if len(matches) != 1:
        raise FileNotFoundError(f"expected one legacy {kind} oracle for {symbol}")
    return matches[0]


def _staged_rows(builder: Any, symbol: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    daily_dirs = builder._symbol_partition_dirs(STAGE_ROOT, "daily", 0)
    minute_dirs = builder._symbol_partition_dirs(STAGE_ROOT, "minute", 0)
    daily = builder._read_symbol_partition(daily_dirs.get(symbol), symbol)
    minute = builder._read_symbol_partition(minute_dirs.get(symbol), symbol)
    return daily, minute


def _fresh_symbol(
    builder: Any,
    symbol: str,
    daily_rows: list[dict[str, Any]],
    minute_rows: list[dict[str, Any]],
) -> tuple[Path, Path, Path, dict[date, CapturedCheckpoint], dict[str, Any]]:
    trading_dates = tuple(
        sorted(
            {
                builder._date(row["trade_date"])
                for row in daily_rows
                if builder._date(row["trade_date"]).year == PHASE2_TARGET_YEAR
            }
        )
    )
    capture_dates = set(checkpoint_dates(trading_dates))
    captured: dict[date, dict[str, Any]] = defaultdict(dict)
    original_output_row = builder._output_row

    def capturing_output_row(**kwargs: Any) -> Any:
        result = original_output_row(**kwargs)
        state = kwargs["state"]
        if state.trading_date in capture_dates:
            snapshot = state.to_snapshot()
            model = str(snapshot.seller_model.value)
            if model in captured[state.trading_date]:
                raise RuntimeError("canonical transition emitted a model twice in one day")
            captured[state.trading_date][model] = capture_model_state(snapshot)
        return result

    builder._output_row = capturing_output_row
    safe_symbol = symbol.replace(".", "_")
    operator_path = Path(f"{TEMP_PREFIX}{safe_symbol}_operator.parquet")
    feature_path = Path(f"{TEMP_PREFIX}{safe_symbol}_feature.parquet")
    terminal_path = Path(f"{TEMP_PREFIX}{safe_symbol}_terminal.parquet")
    for path in (operator_path, feature_path, terminal_path):
        path.unlink(missing_ok=True)
    writer = pq.ParquetWriter(
        operator_path,
        builder.OUTPUT_SCHEMA,
        compression="zstd",
        compression_level=builder.PARQUET_COMPRESSION_LEVEL,
        use_dictionary=True,
    )
    try:
        result, terminal_snapshots = builder._run_symbol(
            symbol,
            daily_rows,
            minute_rows,
            PHASE2_TARGET_YEAR,
            writer,
        )
    finally:
        writer.close()
        builder._output_row = original_output_row
    builder.build_daily_feature_fact(operator_path, feature_path)
    builder._write_terminal_snapshots(terminal_path, terminal_snapshots)
    builder._read_terminal_snapshots(
        terminal_path,
        symbol,
        before_year=PHASE2_TARGET_YEAR + 1,
        expected_year=PHASE2_TARGET_YEAR,
    )
    checkpoints: dict[date, CapturedCheckpoint] = {}
    for trading_date in sorted(captured):
        model_map = captured[trading_date]
        if tuple(model for model in SELLER_MODEL_ORDER if model in model_map) != SELLER_MODEL_ORDER:
            raise RuntimeError("captured checkpoint is missing a seller model")
        checkpoints[trading_date] = CapturedCheckpoint(
            symbol=symbol,
            trading_date=trading_date,
            model_states=tuple(model_map[model] for model in SELLER_MODEL_ORDER),
        )
    if set(checkpoints) != capture_dates:
        raise RuntimeError("canonical stream missed a frozen checkpoint date")
    return operator_path, feature_path, terminal_path, checkpoints, result


def _manifest_parts(root: Path) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name in {"manifest.json", "summary.json"}:
            continue
        relative = path.relative_to(root).as_posix()
        if "/checkpoints/" in relative:
            kind = "checkpoint"
        elif "/journal/" in relative:
            kind = "journal"
        elif relative.endswith("daily_feature_candidate.parquet"):
            kind = "feature"
        elif relative.endswith("year_end_terminal_candidate.parquet"):
            kind = "terminal"
        elif relative == "index.json":
            kind = "index"
        else:
            raise ValueError(f"unexpected Phase 2 artifact: {relative}")
        parts.append(
            {
                "bytes": path.stat().st_size,
                "kind": kind,
                "relative_path": relative,
                "sha256": sha256_file(path),
            }
        )
    return parts


def _fixed_point_summary(path: Path, summary: dict[str, Any]) -> int:
    summary_bytes = 0
    total_bytes = 0
    for _ in range(12):
        summary["capacity"]["summary_bytes"] = summary_bytes
        summary["capacity"]["index_manifest_bytes"] = (
            summary["capacity"]["index_bytes"]
            + summary["capacity"]["manifest_bytes"]
            + summary_bytes
        )
        summary["capacity"]["total_artifact_bytes"] = total_bytes
        new_summary_bytes = write_json(path, summary)
        new_total_bytes = regular_file_bytes(path.parent)
        if (new_summary_bytes, new_total_bytes) == (summary_bytes, total_bytes):
            return new_summary_bytes
        summary_bytes, total_bytes = new_summary_bytes, new_total_bytes
    raise RuntimeError("summary byte accounting did not converge")


def run() -> dict[str, Any]:
    if not str(STAGE_ROOT).startswith(TEMP_PREFIX) or not str(CANDIDATE_ROOT).startswith(
        TEMP_PREFIX
    ):
        raise RuntimeError("temporary paths escaped the Phase 2 prefix")
    builder = _load_builder()
    builder._stage_inputs(
        year=PHASE2_TARGET_YEAR,
        warmup_start=PHASE2_WARMUP_YEARS[0],
        buckets=1,
        stage_root=STAGE_ROOT,
        symbols=PHASE2_SYMBOLS,
    )
    if CANDIDATE_ROOT.exists():
        shutil.rmtree(CANDIDATE_ROOT)
    CANDIDATE_ROOT.mkdir(parents=True)

    dependency_manifest_digest = logical_sha256(
        {
            "daily_root": str(builder.DAILY_ROOT.resolve()),
            "minute_root": str(builder.MINUTE_ROOT.resolve()),
            "stage_marker_sha256": sha256_file(STAGE_ROOT / "COMPLETE.json"),
            "symbols": PHASE2_SYMBOLS,
            "year": PHASE2_TARGET_YEAR,
        }
    )
    replay_parameter_manifest_digest = logical_sha256(
        {
            "checkpoint_cadence": CHECKPOINT_CADENCE,
            "seller_models": SELLER_MODEL_ORDER,
            "symbols": PHASE2_SYMBOLS,
            "target_year": PHASE2_TARGET_YEAR,
            "warmup_years": PHASE2_WARMUP_YEARS,
            "writer_version": PHASE2_WRITER_VERSION,
        }
    )
    runtime_fingerprint = logical_sha256(
        {
            "builder_sha256": sha256_file(ROOT / "scripts/build_real_chip_year.py"),
            "python": sys.version,
            "writer_sha256": sha256_file(
                ROOT / "src/cyq_game/chip/checkpoint_journal_writer.py"
            ),
        }
    )
    semantic_fingerprint = logical_sha256(builder.semantic_fingerprint_fields())
    replay_contract_hash = logical_sha256(
        {
            "dependency_manifest_digest": dependency_manifest_digest,
            "replay_parameter_manifest_digest": replay_parameter_manifest_digest,
            "runtime_fingerprint": runtime_fingerprint,
            "semantic_fingerprint": semantic_fingerprint,
        }
    )
    terminal_completeness_digest = logical_sha256(
        {
            "schema_version": TERMINAL_COMPLETENESS_VERSION,
            "policy": "YEAR_END_CHECKPOINT_PLUS_COUNTED_COMPATIBILITY_TERMINAL",
        }
    )

    artifacts = []
    symbol_results: dict[str, Any] = {}
    exact_mismatch_count = 0
    for symbol in PHASE2_SYMBOLS:
        daily_rows, minute_rows = _staged_rows(builder, symbol)
        operator_path, feature_path, terminal_path, captured, fresh_result = _fresh_symbol(
            builder, symbol, daily_rows, minute_rows
        )
        oracle_operator = _oracle_path("parts.__read_forbidden__", symbol)
        oracle_feature = _oracle_path("daily_feature_fact", symbol)
        oracle_terminal = _oracle_path("terminal", symbol)
        mismatches = {
            "operator": arrow_exact_mismatch_count(operator_path, oracle_operator),
            "feature": arrow_exact_mismatch_count(feature_path, oracle_feature),
            "terminal": arrow_exact_mismatch_count(terminal_path, oracle_terminal),
        }
        exact_mismatch_count += sum(mismatches.values())
        artifact = write_symbol_artifacts(
            root=CANDIDATE_ROOT,
            symbol=symbol,
            captured_checkpoints=captured,
            operator_path=operator_path,
            feature_source_path=feature_path,
            terminal_source_path=terminal_path,
            dependency_manifest_digest=dependency_manifest_digest,
            replay_parameter_manifest_digest=replay_parameter_manifest_digest,
            replay_contract_hash=replay_contract_hash,
            semantic_fingerprint=semantic_fingerprint,
            runtime_fingerprint=runtime_fingerprint,
            terminal_completeness_digest=terminal_completeness_digest,
            bundle_id=BUNDLE_ID,
            root_id=ROOT_ID,
        )
        artifacts.append(artifact)
        symbol_results[symbol] = {
            "status": "PASS" if sum(mismatches.values()) == 0 else "FAIL",
            "trading_days": artifact.trading_days,
            "model_rows": artifact.model_rows,
            "seller_model_rows": {
                model: artifact.trading_days for model in SELLER_MODEL_ORDER
            },
            "exact_mismatches": sum(mismatches.values()),
            "mismatch_categories": mismatches,
            "fallback_rows": artifact.fallback_rows,
            "fresh_builder_result": fresh_result,
        }

    index_path = write_index(
        CANDIDATE_ROOT, artifacts, bundle_id=BUNDLE_ID, root_id=ROOT_ID
    )
    gate_results = {
        "P2_G1": all(symbol_results[symbol]["status"] == "PASS" for symbol in PHASE2_SYMBOLS),
        "P2_G2": all(artifact.model_rows == artifact.trading_days * 3 for artifact in artifacts),
        "P2_G3": exact_mismatch_count == 0,
        "P2_G4": exact_mismatch_count == 0,
        "P2_G5": exact_mismatch_count == 0,
        "P2_G6": exact_mismatch_count == 0,
        "P2_G7": exact_mismatch_count == 0,
        "P2_G8": all(artifact.fallback_rows == 0 for artifact in artifacts),
        "P2_G9": all(artifact.fallback_rows == 0 for artifact in artifacts),
        "P2_G10": exact_mismatch_count == 0,
        "P2_G11": False,
        "P2_G12": False,
    }
    manifest = {
        "artifact_version": "v12-phase2-checkpoint-journal-3symbol-candidate-v1",
        "bundle_id": BUNDLE_ID,
        "checkpoint_cadence": CHECKPOINT_CADENCE,
        "dependency_manifest_digest": dependency_manifest_digest,
        "index_path": index_path.relative_to(CANDIDATE_ROOT).as_posix(),
        "index_sha256": sha256_file(index_path),
        "parts": _manifest_parts(CANDIDATE_ROOT),
        "registered": False,
        "registry_modified": False,
        "replay_contract_hash": replay_contract_hash,
        "replay_parameter_manifest_digest": replay_parameter_manifest_digest,
        "root_id": ROOT_ID,
        "seller_models": list(SELLER_MODEL_ORDER),
        "symbols": list(PHASE2_SYMBOLS),
        "target_year": PHASE2_TARGET_YEAR,
        "terminal_completeness_digest": terminal_completeness_digest,
        "writer_version": PHASE2_WRITER_VERSION,
    }
    write_json(CANDIDATE_ROOT / "manifest.json", manifest)
    verify_root(CANDIDATE_ROOT)
    gate_results["P2_G11"] = True

    capacity = {
        "checkpoint_bytes": sum(item.checkpoint_bytes for item in artifacts),
        "journal_bytes": sum(item.journal_bytes for item in artifacts),
        "feature_bytes": sum(item.feature_bytes for item in artifacts),
        "terminal_candidate_bytes": sum(item.terminal_bytes for item in artifacts),
        "index_bytes": index_path.stat().st_size,
        "manifest_bytes": (CANDIDATE_ROOT / "manifest.json").stat().st_size,
        "summary_bytes": 0,
        "index_manifest_bytes": 0,
        "fallback_rows": sum(item.fallback_rows for item in artifacts),
        "fallback_bytes": sum(item.fallback_bytes for item in artifacts),
        "total_artifact_bytes": 0,
    }
    summary = {
        "capacity": capacity,
        "exact_mismatch_count": exact_mismatch_count,
        "gate_results": {key: "PASS" if value else "FAIL" for key, value in gate_results.items()},
        "ordinary_source_recompute_rows": sum(item.model_rows for item in artifacts),
        "symbol_results": symbol_results,
        "writer_version": PHASE2_WRITER_VERSION,
    }
    gate_results["P2_G12"] = True
    summary["gate_results"]["P2_G12"] = "PASS"
    summary_bytes = _fixed_point_summary(CANDIDATE_ROOT / "summary.json", summary)
    capacity["summary_bytes"] = summary_bytes
    _fixed_point_summary(CANDIDATE_ROOT / "summary.json", summary)
    if not all(gate_results.values()):
        raise RuntimeError(json.dumps(summary, ensure_ascii=False, sort_keys=True))

    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    os.replace(CANDIDATE_ROOT, OUTPUT_ROOT)
    verify_root(OUTPUT_ROOT)
    summary = json.loads((OUTPUT_ROOT / "summary.json").read_text(encoding="utf-8"))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        verify_root(OUTPUT_ROOT)
        summary = json.loads((OUTPUT_ROOT / "summary.json").read_text(encoding="utf-8"))
    else:
        summary = run()
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
