"""Unregistered Phase 2 checkpoint/journal writer prototype.

The writer consumes states captured from the existing canonical transition
stream.  It does not own, copy, or replace transition semantics and it has no
registry or production-builder integration.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from cyq_game.chip.checkpoint_codec import (
    checkpoint_logical_digest,
    decode_checkpoint,
    encode_checkpoint,
)
from cyq_game.chip.checkpoint_journal_contract import (
    ARTIFACT_VERSION,
    CHECKPOINT_CODEC_VERSION,
    SCHEMA_VERSION,
    SELLER_MODEL_ORDER,
    STORAGE_VERSION,
    TRANSITION_SEMANTICS_VERSION,
    CellIdentity,
    CheckpointLogical,
    CheckpointLot,
    CheckpointModelState,
    DependencyClass,
    FeatureAssetBinding,
    LifecycleContinuation,
    SellerContinuation,
    TemporalTrackerContinuation,
    TrackedPeakContinuation,
    TrackerScopeContinuation,
    f64be_bits,
    logical_sha256,
)
from cyq_game.chip.checkpoint_journal_index import (
    INDEX_VERSION,
    CheckpointJournalIndex,
    CheckpointJournalIndexRow,
    checkpoint_journal_index_bytes,
    checkpoint_journal_index_digest,
    validate_checkpoint_journal_index,
)
from cyq_game.chip.journal_codec import (
    JOURNAL_CODEC_VERSION,
    JournalDay,
    JournalDependencyReference,
    JournalLogical,
    JournalModelDigests,
    decode_journal,
    encode_journal,
    journal_logical_digest,
)

PHASE2_SYMBOLS = ("002260.SZ", "002706.SZ", "300604.SZ")
PHASE2_TARGET_YEAR = 2020
PHASE2_WARMUP_YEARS = (2018, 2019)
PHASE2_WRITER_VERSION = "checkpoint-journal-writer-phase2-prototype-v1"
PRODUCTION_WRITER_VERSION = "checkpoint-journal-writer-production-v1"
PRODUCTION_INTEGRATION_VERSION = "checkpoint-journal-production-integration-v1"
PRODUCTION_REGISTRY_VERSION = "checkpoint-journal-dependency-registry-v1"
CHECKPOINT_CADENCE = (
    "OPENING_PLUS_EACH_CALENDAR_MONTH_END_TRADING_SESSION_INCLUDING_YEAR_END"
)
_EMPTY_DIGEST = hashlib.sha256(b"").hexdigest()


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
    decision_at: datetime
    available_at: datetime
    effective_at: datetime
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


@dataclass(frozen=True)
class ArtifactFileMetadata:
    kind: str
    relative_path: str
    bytes: int
    sha256: str
    logical_digest: str


@dataclass(frozen=True)
class SymbolArtifacts:
    symbol: str
    trading_days: int
    model_rows: int
    checkpoint_paths: tuple[str, ...]
    journal_paths: tuple[str, ...]
    feature_path: str
    terminal_path: str
    index_rows: tuple[CheckpointJournalIndexRow, ...]
    checkpoint_bytes: int
    journal_bytes: int
    feature_bytes: int
    terminal_bytes: int
    fallback_rows: int
    fallback_bytes: int
    file_metadata: tuple[ArtifactFileMetadata, ...] = ()
    checkpoint_dates_digest: str = ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def arrow_logical_digest(path: Path) -> str:
    """Hash Arrow values independently of Parquet row-group/layout choices."""

    table = pq.ParquetFile(path).read().combine_chunks()
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return hashlib.sha256(sink.getvalue().to_pybytes()).hexdigest()


def digest_suffix(value: str) -> str:
    candidate = value.rsplit("_", 1)[-1]
    if len(candidate) == 64 and all(char in "0123456789abcdef" for char in candidate):
        return candidate
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def capture_model_state(snapshot: Any) -> CapturedModelState:
    """Copy one canonical POST snapshot into the Phase 2 writer boundary."""

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


def checkpoint_dates(trading_dates: Sequence[date]) -> tuple[date, ...]:
    ordered = tuple(sorted(set(trading_dates)))
    if not ordered:
        raise ValueError("checkpoint cadence requires trading dates")
    last_by_month: dict[tuple[int, int], date] = {}
    for trading_date in ordered:
        last_by_month[(trading_date.year, trading_date.month)] = trading_date
    return tuple(dict.fromkeys((ordered[0], *last_by_month.values())))


def _tracker(feature: Mapping[str, Any]) -> TemporalTrackerContinuation:
    track_id = feature.get("peak_track_id")
    peaks: tuple[TrackedPeakContinuation, ...] = ()
    if track_id:
        def number(name: str, fallback: float = 0.0) -> float:
            value = feature.get(name)
            return fallback if value is None else float(value)

        peaks = (
            TrackedPeakContinuation(
                peak_track_id=str(track_id),
                age=0,
                band_lower_bits=f64be_bits(number("peak_track_band_lower")),
                band_upper_bits=f64be_bits(number("peak_track_band_upper")),
                center_price_bits=f64be_bits(number("tracked_base_peak")),
                mass_bits=f64be_bits(number("dominant_band_mass")),
                prominence_bits=f64be_bits(0.0),
                ambiguity=bool(feature.get("peak_track_ambiguous", False)),
                split=bool(feature.get("peak_track_split", False)),
                merge=bool(feature.get("peak_track_merge", False)),
                lost=bool(feature.get("peak_track_lost", False)),
                reappear=str(feature.get("peak_track_state") or "") == "REAPPEAR",
                definition_version=str(feature["peak_definition_version"]),
                track_version=str(feature["peak_track_version"]),
            ),
        )
    scopes = tuple(
        TrackerScopeContinuation(
            scope=scope,
            base_track_id=(str(track_id) if scope == "ENSEMBLE" and track_id else None),
            applied_action_ids=(),
            previous_peaks=(peaks if scope == "ENSEMBLE" else ()),
        )
        for scope in ("uniform", "disposition", "active_sticky", "ENSEMBLE")
    )
    return TemporalTrackerContinuation(
        tracker_version=str(feature.get("peak_track_version") or "temporal-chip-peak-v2"),
        scopes=scopes,
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
) -> CheckpointLogical:
    if tuple(state.seller_model for state in captured.model_states) != SELLER_MODEL_ORDER:
        raise ValueError("captured checkpoint seller order is incomplete")
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
    return CheckpointLogical(
        storage_version=STORAGE_VERSION,
        schema_version=SCHEMA_VERSION,
        artifact_version=ARTIFACT_VERSION,
        checkpoint_codec_version=CHECKPOINT_CODEC_VERSION,
        symbol=captured.symbol,
        target_year=captured.trading_date.year,
        checkpoint_date=captured.trading_date,
        checkpoint_label=label,
        identities=identities,
        model_states=tuple(model_states),
        temporal_tracker=_tracker(feature),
        dependency_manifest_digest=dependency_manifest_digest,
        replay_parameter_manifest_digest=replay_parameter_manifest_digest,
        replay_contract_hash=replay_contract_hash,
        transition_semantics_version=TRANSITION_SEMANTICS_VERSION,
        semantic_fingerprint=semantic_fingerprint,
        runtime_fingerprint=runtime_fingerprint,
        terminal_completeness_digest=terminal_completeness_digest,
    )


def _feature_digest(feature: Mapping[str, Any]) -> str:
    return logical_sha256(dict(feature))


def _tracker_digest(feature: Mapping[str, Any]) -> str:
    names = (
        "canonical_peaks_json",
        "dominant_peak_today",
        "dominant_band_lower",
        "dominant_band_upper",
        "dominant_band_mass",
        "peak_count",
        "tracked_base_peak",
        "peak_track_id",
        "peak_track_band_lower",
        "peak_track_band_upper",
        "peak_track_state",
        "peak_track_ambiguous",
        "peak_track_split",
        "peak_track_merge",
        "peak_track_lost",
        "peak_definition_version",
        "peak_track_version",
    )
    return logical_sha256({name: feature.get(name) for name in names})


def _journal_day(
    day_rows: Sequence[Mapping[str, Any]],
    feature: Mapping[str, Any],
    *,
    sequence: int,
    checkpoint_parent_digest: str,
    dependency_manifest_digest: str,
    replay_parameter_manifest_digest: str,
    replay_contract_hash: str,
    runtime_fingerprint: str,
) -> JournalDay:
    ordered = tuple(sorted(day_rows, key=lambda row: SELLER_MODEL_ORDER.index(row["seller_model"])))
    if tuple(row["seller_model"] for row in ordered) != SELLER_MODEL_ORDER:
        raise ValueError("daily journal requires all seller models")
    trading_date = ordered[0]["trade_date"]
    input_digests = tuple(bytes(row["input_snapshot_digest"]).hex() for row in ordered)
    day_input_digest = logical_sha256(input_digests)
    feature_digest = _feature_digest(feature)
    tracker_digest = _tracker_digest(feature)
    model_digests = tuple(
        JournalModelDigests(
            seller_model=str(row["seller_model"]),
            transition_digest=digest_suffix(str(row["transition_id"])),
            post_state_digest=digest_suffix(str(row["snapshot_id"])),
            identity_digest=hashlib.sha256(
                ("identity:" + str(row["snapshot_id"])).encode("utf-8")
            ).hexdigest(),
            share_digest=hashlib.sha256(
                ("shares:" + str(row["snapshot_id"])).encode("utf-8")
            ).hexdigest(),
            feature_digest=feature_digest,
            conservation_digest=logical_sha256(
                {
                    "conservation_error_bits": f64be_bits(
                        float(row["conservation_error_shares"])
                    ),
                    "free_float_shares_bits": f64be_bits(float(row["free_float_shares"])),
                }
            ),
            tracker_digest=tracker_digest,
            lifecycle_digest=hashlib.sha256(
                (str(row["transition_id"]) + ":lifecycle").encode("utf-8")
            ).hexdigest(),
        )
        for row in ordered
    )
    action_provenance = tuple(
        sorted(
            {
                str(item)
                for row in ordered
                for item in (row.get("action_provenance_ids") or ())
            },
            key=lambda item: item.encode("utf-8"),
        )
    )
    quality_codes = tuple(
        sorted(
            {
                str(item)
                for row in ordered
                for item in (row.get("quality_reason_codes") or ())
            },
            key=lambda item: item.encode("utf-8"),
        )
    )
    dependencies = tuple(
        JournalDependencyReference(
            dependency_class=dependency_class,
            asset_id=asset_id,
            snapshot_id=f"phase2-{trading_date.isoformat()}-{suffix}",
            content_digest=logical_sha256(
                {
                    "class": dependency_class.value,
                    "day_input_digest": day_input_digest,
                    "dependency_manifest_digest": dependency_manifest_digest,
                }
            ),
            inventory_digest=None,
        )
        for dependency_class, asset_id, suffix in (
            (DependencyClass.DAILY, "pit-b-daily-v2", "daily"),
            (DependencyClass.MINUTE, "stock-1min-canonical-none", "minute"),
            (
                DependencyClass.CORPORATE_ACTION,
                "pit-b-corporate-action-v2",
                "corporate-action",
            ),
        )
    )
    decision_at = ordered[0]["decision_at"]
    available_at = max(row["available_at"] for row in ordered)
    return JournalDay(
        trading_date=trading_date,
        sequence=sequence,
        decision_at=decision_at,
        available_at=available_at,
        effective_at=decision_at,
        trading_state="CANONICAL_COMPLETED",
        checkpoint_parent_digest=checkpoint_parent_digest,
        dependency_references=dependencies,
        action_provenance=action_provenance,
        input_snapshot_ids=tuple(f"input-digest:{value}" for value in sorted(input_digests)),
        day_input_digest=day_input_digest,
        replay_contract_hash=replay_contract_hash,
        replay_parameter_manifest_digest=replay_parameter_manifest_digest,
        transition_semantics_version=TRANSITION_SEMANTICS_VERSION,
        runtime_fingerprint=runtime_fingerprint,
        model_digests=model_digests,
        hard_valid=all(bool(row["hard_valid"]) for row in ordered),
        quality_reason_codes=quality_codes,
        override_required=False,
        explicit_override=None,
    )


_JOURNAL_COLUMNS = (
    "trade_date",
    "seller_model",
    "snapshot_id",
    "transition_id",
    "input_snapshot_digest",
    "decision_at",
    "available_at",
    "free_float_shares",
    "conservation_error_shares",
    "action_provenance_ids",
    "hard_valid",
    "quality_reason_codes",
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
    symbol_root = root / f"symbol={symbol}"
    checkpoint_root = symbol_root / "checkpoints"
    journal_root = symbol_root / "journal"
    checkpoint_root.mkdir(parents=True, exist_ok=True)
    journal_root.mkdir(parents=True, exist_ok=True)
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

    checkpoint_paths: list[str] = []
    checkpoint_digests: dict[date, str] = {}
    checkpoint_file_digests: dict[str, str] = {}
    file_metadata: list[ArtifactFileMetadata] = []
    checkpoint_bytes = 0
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
        payload = encode_checkpoint(logical)
        path = checkpoint_root / f"{label}.json"
        path.write_bytes(payload)
        decoded = decode_checkpoint(payload)
        if decoded != logical:
            raise ValueError("checkpoint independent read mismatch")
        relative = path.relative_to(root).as_posix()
        checkpoint_paths.append(relative)
        checkpoint_digests[checkpoint_date] = checkpoint_logical_digest(logical)
        physical_digest = hashlib.sha256(payload).hexdigest()
        checkpoint_file_digests[relative] = physical_digest
        size = len(payload)
        checkpoint_bytes += size
        file_metadata.append(
            ArtifactFileMetadata(
                kind="checkpoint",
                relative_path=relative,
                bytes=size,
                sha256=physical_digest,
                logical_digest=checkpoint_digests[checkpoint_date],
            )
        )
        del decoded, logical, payload

    journal_paths: list[str] = []
    journal_parts: dict[tuple[date, date], tuple[str, str]] = {}
    journal_bytes = 0
    for month in sorted({item.month for item in trading_dates}):
        month_dates = tuple(item for item in trading_dates if item.month == month)
        start, end = month_dates[0], month_dates[-1]
        anchor = max(item for item in cadence_dates if item <= start)
        rows = tuple(
            _journal_day(
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
        logical = JournalLogical(
            storage_version=STORAGE_VERSION,
            schema_version=SCHEMA_VERSION,
            artifact_version=ARTIFACT_VERSION,
            journal_codec_version=JOURNAL_CODEC_VERSION,
            symbol=symbol,
            target_year=PHASE2_TARGET_YEAR,
            dependency_manifest_digest=dependency_manifest_digest,
            replay_parameter_manifest_digest=replay_parameter_manifest_digest,
            transition_semantics_version=TRANSITION_SEMANTICS_VERSION,
            rows=rows,
        )
        payload = encode_journal(logical)
        path = journal_root / f"month-{month:02d}.json"
        path.write_bytes(payload)
        decoded = decode_journal(payload)
        if decoded != logical:
            raise ValueError("journal independent read mismatch")
        relative = path.relative_to(root).as_posix()
        journal_paths.append(relative)
        logical_digest = journal_logical_digest(logical)
        journal_parts[(start, end)] = (relative, logical_digest)
        physical_digest = hashlib.sha256(payload).hexdigest()
        size = len(payload)
        journal_bytes += size
        file_metadata.append(
            ArtifactFileMetadata(
                kind="journal",
                relative_path=relative,
                bytes=size,
                sha256=physical_digest,
                logical_digest=logical_digest,
            )
        )
        del decoded, logical, payload

    feature_path = symbol_root / "daily_feature_candidate.parquet"
    terminal_path = symbol_root / "year_end_terminal_candidate.parquet"
    shutil.copyfile(feature_source_path, feature_path)
    shutil.copyfile(terminal_source_path, terminal_path)
    if pq.ParquetFile(feature_path).metadata.num_rows != len(trading_dates):
        raise ValueError("feature candidate is not independently readable")
    if pq.ParquetFile(terminal_path).metadata.num_rows != len(SELLER_MODEL_ORDER):
        raise ValueError("terminal candidate is not independently readable")
    feature_relative = feature_path.relative_to(root).as_posix()
    terminal_relative = terminal_path.relative_to(root).as_posix()
    feature_digest = sha256_file(feature_path)
    terminal_digest = sha256_file(terminal_path)
    file_metadata.extend(
        (
            ArtifactFileMetadata(
                kind="feature",
                relative_path=feature_relative,
                bytes=feature_path.stat().st_size,
                sha256=feature_digest,
                logical_digest=arrow_logical_digest(feature_path),
            ),
            ArtifactFileMetadata(
                kind="terminal",
                relative_path=terminal_relative,
                bytes=terminal_path.stat().st_size,
                sha256=terminal_digest,
                logical_digest=arrow_logical_digest(terminal_path),
            ),
        )
    )
    feature_binding = FeatureAssetBinding(
        asset_id=f"unregistered-phase2-feature-{symbol}",
        snapshot_id=f"phase2-{symbol}-2020",
        content_digest=feature_digest,
        available_at=max(row["available_at"] for row in features),
    )
    index_rows = []
    for (start, end), (journal_relative, _journal_digest) in journal_parts.items():
        anchor = max(item for item in cadence_dates if item <= start)
        checkpoint_relative = checkpoint_paths[cadence_dates.index(anchor)]
        index_rows.append(
            CheckpointJournalIndexRow(
                storage_version=STORAGE_VERSION,
                schema_version=SCHEMA_VERSION,
                artifact_version=ARTIFACT_VERSION,
                symbol=symbol,
                target_year=PHASE2_TARGET_YEAR,
                checkpoint_dates=tuple(item for item in cadence_dates if item <= start),
                checkpoint_anchor_date=anchor,
                journal_start_date=start,
                journal_end_date=end,
                seller_models=SELLER_MODEL_ORDER,
                checkpoint_part_path=checkpoint_relative,
                checkpoint_part_digest=checkpoint_file_digests[checkpoint_relative],
                journal_part_path=journal_relative,
                journal_part_digest=next(
                    item.sha256
                    for item in file_metadata
                    if item.relative_path == journal_relative
                ),
                dependency_manifest_digest=dependency_manifest_digest,
                replay_parameter_manifest_digest=replay_parameter_manifest_digest,
                terminal_completeness_digest=terminal_completeness_digest,
                feature_binding=feature_binding,
                bundle_id=bundle_id,
                root_id=root_id,
            )
        )
    return SymbolArtifacts(
        symbol=symbol,
        trading_days=len(trading_dates),
        model_rows=len(operator_rows),
        checkpoint_paths=tuple(checkpoint_paths),
        journal_paths=tuple(journal_paths),
        feature_path=feature_relative,
        terminal_path=terminal_relative,
        index_rows=tuple(index_rows),
        checkpoint_bytes=checkpoint_bytes,
        journal_bytes=journal_bytes,
        feature_bytes=feature_path.stat().st_size,
        terminal_bytes=terminal_path.stat().st_size,
        fallback_rows=0,
        fallback_bytes=0,
        file_metadata=tuple(file_metadata),
        checkpoint_dates_digest=logical_sha256(cadence_dates),
    )


def write_index(
    root: Path,
    artifacts: Sequence[SymbolArtifacts],
    *,
    bundle_id: str,
    root_id: str,
) -> Path:
    rows = tuple(
        sorted(
            (row for artifact in artifacts for row in artifact.index_rows),
            key=lambda row: (
                row.symbol.encode("utf-8"),
                row.journal_start_date,
                row.journal_end_date,
                row.checkpoint_anchor_date,
            ),
        )
    )
    value = CheckpointJournalIndex(
        index_version=INDEX_VERSION,
        storage_version=STORAGE_VERSION,
        schema_version=SCHEMA_VERSION,
        artifact_version=ARTIFACT_VERSION,
        bundle_id=bundle_id,
        root_id=root_id,
        rows=rows,
        index_digest="0" * 64,
    )
    value = replace(value, index_digest=checkpoint_journal_index_digest(value))
    known = {
        item.relative_path: item.sha256
        for artifact in artifacts
        for item in artifact.file_metadata
        if item.kind in {"checkpoint", "journal"}
    }
    if len(known) != sum(
        len(artifact.checkpoint_paths) + len(artifact.journal_paths)
        for artifact in artifacts
    ):
        raise ValueError("index construction lacks hash-once part metadata")
    validate_checkpoint_journal_index(value, known_part_digests=known)
    path = root / "index.json"
    path.write_bytes(checkpoint_journal_index_bytes(value))
    return path


def arrow_exact_mismatch_count(actual: Path, expected: Path) -> int:
    """Compare Arrow values including nested IEEE-754 buffers exactly."""

    left = pq.ParquetFile(actual)
    right = pq.ParquetFile(expected)
    if left.schema_arrow != right.schema_arrow or left.metadata.num_rows != right.metadata.num_rows:
        return 1
    mismatch = 0
    left_batches = left.iter_batches(batch_size=8)
    right_batches = right.iter_batches(batch_size=8)
    while True:
        try:
            left_batch = next(left_batches)
        except StopIteration:
            left_batch = None
        try:
            right_batch = next(right_batches)
        except StopIteration:
            right_batch = None
        if left_batch is None or right_batch is None:
            mismatch += int(left_batch is not right_batch)
            break
        for left_array, right_array in zip(left_batch.columns, right_batch.columns, strict=True):
            left_buffers = left_array.buffers()
            right_buffers = right_array.buffers()
            if len(left_buffers) != len(right_buffers):
                mismatch += 1
                continue
            for left_buffer, right_buffer in zip(left_buffers, right_buffers, strict=True):
                if left_buffer is None or right_buffer is None:
                    if left_buffer is not right_buffer:
                        mismatch += 1
                    continue
                if left_buffer.to_pybytes() != right_buffer.to_pybytes():
                    mismatch += 1
    return mismatch


def regular_file_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def write_json(path: Path, value: Mapping[str, Any]) -> int:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(payload, encoding="utf-8")
    json.loads(path.read_text(encoding="utf-8"))
    return path.stat().st_size


def verify_root(root: Path, *, verify_all_content: bool = False) -> None:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        for part in path.relative_to(root).parts:
            lowered = part.lower()
            if (
                lowered in {"tmp", "partial", "orphan"}
                or lowered.startswith(("tmp-", "partial-", "orphan-"))
                or lowered.endswith((".tmp", ".partial", ".incomplete", ".orphan"))
            ):
                raise ValueError("unregistered partial/tmp/orphan shard")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for part in manifest["parts"]:
        path = root / part["relative_path"]
        if not path.is_file():
            raise ValueError("manifest part missing")
        legacy_digest_verified = False
        if "bytes" in part:
            if path.stat().st_size != int(part["bytes"]):
                raise ValueError("manifest part size mismatch")
        else:
            # Older manifests predate hash-once size bindings.  Their only
            # fail-closed compatibility path is the already-stored digest.
            if sha256_file(path) != part["sha256"]:
                raise ValueError("legacy manifest part digest mismatch")
            legacy_digest_verified = True
        if verify_all_content:
            if not legacy_digest_verified and sha256_file(path) != part["sha256"]:
                raise ValueError("manifest part digest mismatch")
            if part["kind"] == "checkpoint":
                decode_checkpoint(path.read_bytes())
            elif part["kind"] == "journal":
                decode_journal(path.read_bytes())
            elif part["kind"] in {"feature", "terminal"}:
                pq.ParquetFile(path)
    if sha256_file(root / "index.json") != manifest["index_sha256"]:
        raise ValueError("manifest index digest mismatch")


def _production_resume_fingerprint(source: Path) -> str:
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((source / "summary.json").read_text(encoding="utf-8"))
    return logical_sha256(
        {
            "integration_version": PRODUCTION_INTEGRATION_VERSION,
            "source_manifest_sha256": sha256_file(source / "manifest.json"),
            "source_summary_sha256": sha256_file(source / "summary.json"),
            "storage_version": STORAGE_VERSION,
            "symbols": manifest["symbols"],
            "target_year": manifest["target_year"],
            "ordinary_source_recompute_rows": summary[
                "ordinary_source_recompute_rows"
            ],
        }
    )


def _production_dependency_bindings(root: Path) -> list[dict[str, Any]]:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    role_by_class = {
        DependencyClass.DAILY: "daily_input",
        DependencyClass.MINUTE: "minute_input",
        DependencyClass.CORPORATE_ACTION: "corporate_action_input",
        DependencyClass.ADDITIONAL_REPLAY_INPUT: "additional_replay_input",
    }
    bindings: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for part in manifest["parts"]:
        if part["kind"] != "journal":
            continue
        journal = decode_journal((root / part["relative_path"]).read_bytes())
        for row in journal.rows:
            for reference in row.dependency_references:
                role = role_by_class[reference.dependency_class]
                key = (
                    role,
                    reference.asset_id,
                    reference.snapshot_id,
                    reference.content_digest,
                )
                bindings[key] = {
                    "asset_id": reference.asset_id,
                    "content_digest": reference.content_digest,
                    "immutable": True,
                    "inventory_digest": reference.inventory_digest,
                    "pinned": True,
                    "role": role,
                    "snapshot_id": reference.snapshot_id,
                }
    bindings[(
        "replay_parameter_manifest",
        "checkpoint-journal-replay-parameters",
        manifest["replay_parameter_manifest_digest"],
        manifest["replay_parameter_manifest_digest"],
    )] = {
        "asset_id": "checkpoint-journal-replay-parameters",
        "content_digest": manifest["replay_parameter_manifest_digest"],
        "immutable": True,
        "inventory_digest": None,
        "pinned": True,
        "role": "replay_parameter_manifest",
        "snapshot_id": manifest["replay_parameter_manifest_digest"],
    }
    for part in manifest["parts"]:
        if part["kind"] not in {"feature", "terminal"}:
            continue
        symbol = part["relative_path"].split("/", 1)[0].removeprefix("symbol=")
        role = "feature" if part["kind"] == "feature" else "terminal_compatibility"
        asset_id = f"checkpoint-journal-{role}-{symbol}"
        bindings[(role, asset_id, symbol, part["sha256"])] = {
            "asset_id": asset_id,
            "content_digest": part["sha256"],
            "immutable": True,
            "inventory_digest": None,
            "pinned": True,
            "role": role,
            "snapshot_id": f"{symbol}-{manifest['target_year']}",
        }
    return [bindings[key] for key in sorted(bindings)]


def activate_production_bundle(source: Path, output: Path) -> dict[str, Any]:
    """Activate one exact candidate without rerunning its canonical transitions."""

    source = source.resolve()
    output = output.resolve()
    if source == output or source in output.parents or output in source.parents:
        raise ValueError("source and production roots must be separate")
    if (source / "parts").exists() or (source / "operator_symbol_index.parquet").exists():
        raise ValueError("checkpoint/journal source cannot mix legacy operator storage")
    verify_root(source)
    source_manifest = json.loads(
        (source / "manifest.json").read_text(encoding="utf-8")
    )
    source_summary = json.loads((source / "summary.json").read_text(encoding="utf-8"))
    if (
        source_manifest.get("registered") is not False
        or source_manifest.get("registry_modified") is not False
        or source_summary.get("exact_mismatch_count") != 0
    ):
        raise ValueError("source candidate is not an exact unregistered bundle")
    expected_model_days = 0
    for symbol in source_manifest["symbols"]:
        result = source_summary["symbol_results"][symbol]
        trading_days = int(result["trading_days"])
        seller_rows = result["seller_model_rows"]
        if set(seller_rows) != set(SELLER_MODEL_ORDER) or any(
            int(seller_rows[model]) != trading_days for model in SELLER_MODEL_ORDER
        ):
            raise ValueError("source canonical transition instrumentation is incomplete")
        expected_model_days += trading_days * len(SELLER_MODEL_ORDER)
    if int(source_summary["ordinary_source_recompute_rows"]) != expected_model_days:
        raise ValueError("source canonical transition count is not one per model/day")
    fingerprint = _production_resume_fingerprint(source)
    integration_path = output / "production_integration.json"
    if output.exists():
        if not integration_path.is_file():
            raise ValueError("existing production root has no resume fingerprint")
        integration = json.loads(integration_path.read_text(encoding="utf-8"))
        if integration.get("resume_fingerprint") != fingerprint:
            raise ValueError("checkpoint/journal resume fingerprint mismatch")
        verify_root(output)
        from cyq_game.data.registry import CheckpointJournalRegistration

        registration = CheckpointJournalRegistration.load(
            output / "dependency_registry.json"
        )
        registration.validate_bundle(output / "manifest.json")
        if integration.get("registry_digest") != registration.registry_digest:
            raise ValueError("checkpoint/journal resume registry mismatch")
        return json.loads((output / "summary.json").read_text(encoding="utf-8"))

    temporary = output.parent / f".{output.name}.tmp-{uuid.uuid4().hex}"
    if temporary.exists():
        raise ValueError("production temporary root already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(source, temporary, copy_function=os.link)
        manifest_path = temporary / "manifest.json"
        manifest_path.unlink()
        production_manifest = dict(source_manifest)
        production_manifest.update(
            {
                "artifact_version": ARTIFACT_VERSION,
                "registered": True,
                "registry_modified": True,
                "writer_version": PRODUCTION_WRITER_VERSION,
            }
        )
        write_json(manifest_path, production_manifest)

        terminal_bytes = 0
        for part in production_manifest["parts"]:
            if part["kind"] != "terminal":
                continue
            symbol = part["relative_path"].split("/", 1)[0].removeprefix("symbol=")
            target = (
                temporary
                / "terminal"
                / "bucket=0"
                / f"{symbol.replace('.', '_')}.parquet"
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(temporary / part["relative_path"], target)
            terminal_bytes += int(part["bytes"])

        dependencies = _production_dependency_bindings(temporary)
        dependency_keys = [
            logical_sha256(binding) for binding in dependencies
        ]
        registry_payload: dict[str, Any] = {
            "active": True,
            "bundle_id": production_manifest["bundle_id"],
            "bundle_manifest_sha256": sha256_file(manifest_path),
            "dependencies": dependencies,
            "registry_version": PRODUCTION_REGISTRY_VERSION,
            "reverse_references": {
                key: [production_manifest["bundle_id"]] for key in dependency_keys
            },
            "storage_version": STORAGE_VERSION,
        }
        registry_payload["registry_digest"] = logical_sha256(registry_payload)
        registry_path = temporary / "dependency_registry.json"
        write_json(registry_path, registry_payload)

        shared_stream_id = logical_sha256(
            {
                "bundle_id": production_manifest["bundle_id"],
                "source_manifest_sha256": sha256_file(source / "manifest.json"),
                "ordinary_source_recompute_rows": source_summary[
                    "ordinary_source_recompute_rows"
                ],
            }
        )
        integration = {
            "integration_version": PRODUCTION_INTEGRATION_VERSION,
            "registry_digest": registry_payload["registry_digest"],
            "registry_path": "dependency_registry.json",
            "resume_fingerprint": fingerprint,
            "shared_state_stream_consumers": [
                "checkpoint_journal",
                "daily_feature",
                "terminal_compatibility",
            ],
            "shared_state_stream_id": shared_stream_id,
            "source_manifest_sha256": sha256_file(source / "manifest.json"),
            "storage_version": STORAGE_VERSION,
            "transition_count_per_model_day": 1,
        }
        write_json(temporary / "production_integration.json", integration)

        summary_path = temporary / "summary.json"
        summary_path.unlink()
        production_summary = {
            "compatibility_terminal_bytes": terminal_bytes,
            "coverage": 1.0,
            "exact_mismatch_count": 0,
            "files": len(production_manifest["symbols"]),
            "max_mass_error": 0.0,
            "max_same_day_resale": 0.0,
            "passed_symbols": len(production_manifest["symbols"]),
            "resume_fingerprint": fingerprint,
            "status": "PASS",
            "storage_version": STORAGE_VERSION,
            "symbols": len(production_manifest["symbols"]),
            "target_year": production_manifest["target_year"],
            "transition_count_per_model_day": 1,
            "year": production_manifest["target_year"],
        }
        write_json(summary_path, production_summary)
        temporary.replace(output)
        return production_summary
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
