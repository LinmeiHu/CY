#!/usr/bin/env python3
"""Run the unregistered V12 Phase 2 three-symbol writer prototype."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import shutil
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cyq_game.chip.checkpoint_journal_contract import (  # noqa: E402
    SELLER_MODEL_ORDER,
    TERMINAL_COMPLETENESS_VERSION,
    CellIdentity,
    CheckpointLot,
    CheckpointModelState,
    LifecycleContinuation,
    SellerContinuation,
    f64be_bits,
    logical_sha256,
)
from cyq_game.chip.checkpoint_journal_writer import (  # noqa: E402
    _JOURNAL_COLUMNS,
    CHECKPOINT_CADENCE,
    PHASE2_SYMBOLS,
    PHASE2_TARGET_YEAR,
    PHASE2_WARMUP_YEARS,
    PHASE2_WRITER_VERSION,
    ArtifactFileMetadata,
    SymbolArtifacts,
    arrow_exact_mismatch_count,
    build_checkpoint_logical,
    build_journal_day,
    build_journal_logical,
    checkpoint_dates,
    finish_symbol_artifacts,
    regular_file_bytes,
    sha256_file,
    verify_root,
    write_checkpoint_part,
    write_index,
    write_journal_part,
    write_json,
)

OUTPUT_ROOT = ROOT / "data/validation/v12_checkpoint_journal_phase2_3symbol"
LEGACY_ROOT = ROOT / "data/validation/v12_rc1_2020_output"
STAGE_ROOT = Path("/tmp/v12_checkpoint_journal_phase2_stage")
CANDIDATE_ROOT = Path("/tmp/v12_checkpoint_journal_phase2_candidate")
TEMP_PREFIX = "/tmp/v12_checkpoint_journal_phase2_"
BUNDLE_ID = "v12-checkpoint-journal-phase2-3symbol-2020"
ROOT_ID = "v12-checkpoint-journal-phase2-3symbol-root-v1"
_EMPTY_DIGEST = __import__("hashlib").sha256(b"").hexdigest()


@dataclass(frozen=True)
class CapturedCell:
    cell_id: int
    cost_bucket_id: int | None
    holding_days: int
    sensitivity: str
    acquisition_cost: float | None
    economic_break_even: float | None
    shares: float
    initialization_prior_units: float


@dataclass(frozen=True)
class CapturedModelState:
    seller_model: str
    decision_at: Any
    available_at: Any
    effective_at: Any
    phase: str
    snapshot_id: str
    model_version: str
    grid_version: str
    cells: tuple[CapturedCell, ...]
    free_float_shares: float
    latent_supply_shares: float
    conservation_error: float
    input_snapshot_ids: tuple[str, ...]
    pit_grade: str
    hard_valid: bool
    quality_reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class CapturedCheckpoint:
    symbol: str
    trading_date: date
    model_states: tuple[CapturedModelState, ...]


def capture_model_state(snapshot: Any) -> CapturedModelState:
    cells = tuple(
        CapturedCell(
            cell_id=int(cell.cell_id),
            cost_bucket_id=(
                None if cell.cost_bucket_id is None else int(cell.cost_bucket_id)
            ),
            holding_days=int(cell.holding_days),
            sensitivity=str(getattr(cell.sensitivity, "value", cell.sensitivity)),
            acquisition_cost=(
                None if cell.acquisition_cost is None else float(cell.acquisition_cost)
            ),
            economic_break_even=(
                None
                if cell.economic_break_even is None
                else float(cell.economic_break_even)
            ),
            shares=float(cell.shares),
            initialization_prior_units=float(cell.initialization_prior_units),
        )
        for cell in sorted(snapshot.inventory.cells, key=lambda item: item.cell_id)
    )
    return CapturedModelState(
        seller_model=str(getattr(snapshot.seller_model, "value", snapshot.seller_model)),
        decision_at=snapshot.decision_at,
        available_at=snapshot.available_at,
        effective_at=snapshot.effective_at,
        phase=str(getattr(snapshot.phase, "value", snapshot.phase)),
        snapshot_id=str(snapshot.snapshot_id),
        model_version=str(snapshot.model_version),
        grid_version=str(snapshot.grid_version),
        cells=cells,
        free_float_shares=float(snapshot.free_float_shares),
        latent_supply_shares=float(snapshot.latent_supply_shares),
        conservation_error=float(snapshot.conservation_error),
        input_snapshot_ids=tuple(
            sorted(set(snapshot.input_snapshot_ids), key=lambda item: item.encode("utf-8"))
        ),
        pit_grade=str(snapshot.pit_grade),
        hard_valid=bool(snapshot.hard_valid),
        quality_reason_codes=tuple(
            sorted(
                set(snapshot.quality_reason_codes),
                key=lambda item: item.encode("utf-8"),
            )
        ),
    )


def _checkpoint_logical(
    captured: CapturedCheckpoint,
    feature: Mapping[str, Any],
    *,
    label: str,
    dependency_manifest_digest: str,
    replay_parameter_manifest_digest: str,
    replay_contract_hash: str,
    semantic_fingerprint: str,
    runtime_fingerprint: str,
    terminal_completeness_digest: str,
) -> Any:
    identities_by_id: dict[int, CellIdentity] = {}
    for state in captured.model_states:
        for cell in state.cells:
            identity = CellIdentity(
                cell_id=cell.cell_id,
                cost_bucket_id=cell.cost_bucket_id,
                holding_days=cell.holding_days,
                sensitivity=cell.sensitivity,
                economic_break_even_bits=(
                    None
                    if cell.economic_break_even is None
                    else f64be_bits(cell.economic_break_even)
                ),
                economic_coordinate_version="causal-economic-price-v2",
            )
            previous = identities_by_id.setdefault(cell.cell_id, identity)
            if previous != identity:
                raise ValueError("same cell_id has conflicting checkpoint identity")
    identities = tuple(identities_by_id[key] for key in sorted(identities_by_id))
    positions = {identity.cell_id: index for index, identity in enumerate(identities)}
    empty_lifecycle = LifecycleContinuation(
        lifecycle_version="phase2-no-active-anchor-v1",
        active_anchor_ids=(),
        anchors=(),
        identity_digest=_EMPTY_DIGEST,
        share_digest=_EMPTY_DIGEST,
        retention_digest=_EMPTY_DIGEST,
        destination_digest=_EMPTY_DIGEST,
    )
    model_states = []
    for state in captured.model_states:
        lots = tuple(
            CheckpointLot(
                identity_position=positions[cell.cell_id],
                shares_bits=f64be_bits(cell.shares),
                acquisition_cost_bits=(
                    None
                    if cell.acquisition_cost is None
                    else f64be_bits(cell.acquisition_cost)
                ),
                initialization_prior_units_bits=f64be_bits(
                    cell.initialization_prior_units
                ),
            )
            for cell in state.cells
        )
        lot_total = math.fsum(cell.shares for cell in state.cells)
        if f64be_bits(lot_total - state.free_float_shares) != f64be_bits(
            state.conservation_error
        ):
            raise ValueError("captured checkpoint conservation residual is not exact")
        model_states.append(
            CheckpointModelState(
                seller_model=state.seller_model,
                decision_at=state.decision_at,
                available_at=state.available_at,
                effective_at=state.effective_at,
                phase=state.phase,
                snapshot_id=state.snapshot_id,
                model_version=state.model_version,
                grid_version=state.grid_version,
                lots=lots,
                free_float_shares_bits=f64be_bits(state.free_float_shares),
                latent_supply_shares_bits=f64be_bits(state.latent_supply_shares),
                conservation_error_bits=f64be_bits(state.conservation_error),
                input_snapshot_ids=state.input_snapshot_ids,
                pit_grade=state.pit_grade,
                hard_valid=state.hard_valid,
                quality_reason_codes=state.quality_reason_codes,
                seller_continuation=SellerContinuation(
                    continuation_version="canonical-seller-continuation-v1",
                    values={
                        "seller_model": state.seller_model,
                        "snapshot_id": state.snapshot_id,
                    },
                ),
                lifecycle_continuation=empty_lifecycle,
            )
        )
    return build_checkpoint_logical(
        symbol=captured.symbol,
        trading_date=captured.trading_date,
        identities=identities,
        model_states=tuple(model_states),
        feature=feature,
        label=label,
        dependency_manifest_digest=dependency_manifest_digest,
        replay_parameter_manifest_digest=replay_parameter_manifest_digest,
        replay_contract_hash=replay_contract_hash,
        semantic_fingerprint=semantic_fingerprint,
        runtime_fingerprint=runtime_fingerprint,
        terminal_completeness_digest=terminal_completeness_digest,
    )


def write_symbol_artifacts(
    *,
    root: Path,
    symbol: str,
    captured_checkpoints: Mapping[date, CapturedCheckpoint],
    operator_path: Path,
    feature_source_path: Path,
    terminal_source_path: Path,
    dependency_manifest_digest: str,
    replay_parameter_manifest_digest: str,
    replay_contract_hash: str,
    semantic_fingerprint: str,
    runtime_fingerprint: str,
    terminal_completeness_digest: str,
    bundle_id: str,
    root_id: str,
    replayable_dates: Sequence[date] | None = None,
) -> SymbolArtifacts:
    operator_rows = pq.read_table(operator_path, columns=list(_JOURNAL_COLUMNS)).to_pylist()
    features = pq.read_table(feature_source_path).to_pylist()
    feature_by_date = {row["trade_date"]: row for row in features}
    rows_by_date: dict[date, list[Mapping[str, Any]]] = {}
    for row in operator_rows:
        rows_by_date.setdefault(row["trade_date"], []).append(row)
    trading_dates = tuple(sorted(rows_by_date))
    if replayable_dates is not None:
        authoritative_dates = tuple(replayable_dates)
        if trading_dates != authoritative_dates:
            raise ValueError("operator dates differ from authoritative replayable dates")
        trading_dates = authoritative_dates
    cadence_dates = checkpoint_dates(trading_dates)
    if set(cadence_dates) != set(captured_checkpoints):
        raise ValueError("captured checkpoint dates do not match frozen cadence")

    checkpoint_parts: dict[date, tuple[ArtifactFileMetadata, str]] = {}
    checkpoint_digests: dict[date, str] = {}
    for position, checkpoint_date in enumerate(cadence_dates):
        label = (
            f"opening-{checkpoint_date.isoformat()}"
            if position == 0
            else f"month-{checkpoint_date.month:02d}-{checkpoint_date.isoformat()}"
        )
        logical = _checkpoint_logical(
            captured_checkpoints[checkpoint_date],
            feature_by_date[checkpoint_date],
            label=label,
            dependency_manifest_digest=dependency_manifest_digest,
            replay_parameter_manifest_digest=replay_parameter_manifest_digest,
            replay_contract_hash=replay_contract_hash,
            semantic_fingerprint=semantic_fingerprint,
            runtime_fingerprint=runtime_fingerprint,
            terminal_completeness_digest=terminal_completeness_digest,
        )
        metadata, logical_digest = write_checkpoint_part(root, logical)
        checkpoint_parts[checkpoint_date] = (metadata, logical_digest)
        checkpoint_digests[checkpoint_date] = logical_digest

    journal_parts: dict[tuple[date, date], ArtifactFileMetadata] = {}
    for month in sorted({item.month for item in trading_dates}):
        month_dates = tuple(item for item in trading_dates if item.month == month)
        start, end = month_dates[0], month_dates[-1]
        anchor = max(item for item in cadence_dates if item <= start)
        rows = tuple(
            build_journal_day(
                rows_by_date[item],
                feature_by_date[item],
                sequence=sequence,
                checkpoint_parent_digest=checkpoint_digests[anchor],
                dependency_manifest_digest=dependency_manifest_digest,
                replay_parameter_manifest_digest=replay_parameter_manifest_digest,
                replay_contract_hash=replay_contract_hash,
                runtime_fingerprint=runtime_fingerprint,
            )
            for sequence, item in enumerate(month_dates)
        )
        logical = build_journal_logical(
            symbol=symbol,
            target_year=PHASE2_TARGET_YEAR,
            rows=rows,
            dependency_manifest_digest=dependency_manifest_digest,
            replay_parameter_manifest_digest=replay_parameter_manifest_digest,
        )
        metadata = write_journal_part(root, logical)
        journal_parts[(start, end)] = metadata

    return finish_symbol_artifacts(
        root=root,
        symbol=symbol,
        replayable_dates=trading_dates,
        checkpoint_parts=checkpoint_parts,
        journal_parts=journal_parts,
        features=features,
        feature_source_path=feature_source_path,
        terminal_source_path=terminal_source_path,
        dependency_manifest_digest=dependency_manifest_digest,
        replay_parameter_manifest_digest=replay_parameter_manifest_digest,
        terminal_completeness_digest=terminal_completeness_digest,
        bundle_id=bundle_id,
        root_id=root_id,
    )


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
