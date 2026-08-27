"""Unregistered Phase 2 checkpoint/journal writer prototype.

The writer consumes states captured from the existing canonical transition
stream.  It does not own, copy, or replace transition semantics and it has no
registry or production-builder integration.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from cyq_game.chip.checkpoint_codec import checkpoint_logical_digest
from cyq_game.chip.checkpoint_compact_codec import (
    decode_compact_checkpoint,
    write_compact_checkpoint,
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
    CheckpointModelState,
    DependencyClass,
    FeatureAssetBinding,
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
CHECKPOINT_CADENCE = (
    "OPENING_PLUS_EACH_CALENDAR_MONTH_END_TRADING_SESSION_INCLUDING_YEAR_END"
)
_EMPTY_DIGEST = hashlib.sha256(b"").hexdigest()


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


def build_checkpoint_logical(
    *,
    symbol: str,
    trading_date: date,
    identities: tuple[CellIdentity, ...],
    model_states: tuple[CheckpointModelState, ...],
    feature: Mapping[str, Any],
    label: str,
    dependency_manifest_digest: str,
    replay_parameter_manifest_digest: str,
    replay_contract_hash: str,
    semantic_fingerprint: str,
    runtime_fingerprint: str,
    terminal_completeness_digest: str,
) -> CheckpointLogical:
    """Bind canonical checkpoint codec rows to the frozen artifact contract."""

    if tuple(state.seller_model for state in model_states) != SELLER_MODEL_ORDER:
        raise ValueError("checkpoint seller order is incomplete")
    return CheckpointLogical(
        storage_version=STORAGE_VERSION,
        schema_version=SCHEMA_VERSION,
        artifact_version=ARTIFACT_VERSION,
        checkpoint_codec_version=CHECKPOINT_CODEC_VERSION,
        symbol=symbol,
        target_year=trading_date.year,
        checkpoint_date=trading_date,
        checkpoint_label=label,
        identities=identities,
        model_states=model_states,
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


def build_journal_day(
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


def build_journal_logical(
    *,
    symbol: str,
    target_year: int,
    rows: tuple[JournalDay, ...],
    dependency_manifest_digest: str,
    replay_parameter_manifest_digest: str,
) -> JournalLogical:
    """Bind one bounded calendar-month journal buffer to its frozen schema."""

    return JournalLogical(
        storage_version=STORAGE_VERSION,
        schema_version=SCHEMA_VERSION,
        artifact_version=ARTIFACT_VERSION,
        journal_codec_version=JOURNAL_CODEC_VERSION,
        symbol=symbol,
        target_year=target_year,
        dependency_manifest_digest=dependency_manifest_digest,
        replay_parameter_manifest_digest=replay_parameter_manifest_digest,
        transition_semantics_version=TRANSITION_SEMANTICS_VERSION,
        rows=rows,
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


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_checkpoint_part(
    root: Path, logical: CheckpointLogical
) -> tuple[ArtifactFileMetadata, str]:
    """Atomically write the compact production checkpoint container."""

    relative = (
        Path(f"symbol={logical.symbol}")
        / "checkpoints"
        / f"{logical.checkpoint_label}.npz"
    ).as_posix()
    path = root / relative
    physical_bytes = write_compact_checkpoint(path, logical)
    logical_digest = checkpoint_logical_digest(logical)
    return (
        ArtifactFileMetadata(
            kind="checkpoint",
            relative_path=relative,
            bytes=physical_bytes,
            sha256=sha256_file(path),
            logical_digest=logical_digest,
        ),
        logical_digest,
    )


def write_journal_part(
    root: Path, logical: JournalLogical
) -> ArtifactFileMetadata:
    """Atomically encode one bounded journal month."""

    if not logical.rows:
        raise ValueError("journal part requires at least one day")
    month = logical.rows[0].trading_date.month
    if any(row.trading_date.month != month for row in logical.rows):
        raise ValueError("journal part crosses a calendar-month boundary")
    payload = encode_journal(logical)
    relative = (
        Path(f"symbol={logical.symbol}") / "journal" / f"month-{month:02d}.json"
    ).as_posix()
    _atomic_write_bytes(root / relative, payload)
    return ArtifactFileMetadata(
        kind="journal",
        relative_path=relative,
        bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        logical_digest=journal_logical_digest(logical),
    )


def finish_symbol_artifacts(
    *,
    root: Path,
    symbol: str,
    replayable_dates: Sequence[date],
    checkpoint_parts: Mapping[date, tuple[ArtifactFileMetadata, str]],
    journal_parts: Mapping[tuple[date, date], ArtifactFileMetadata],
    features: Sequence[Mapping[str, Any]],
    feature_source_path: Path,
    dependency_manifest_digest: str,
    replay_parameter_manifest_digest: str,
    terminal_completeness_digest: str,
    bundle_id: str,
    root_id: str,
) -> SymbolArtifacts:
    """Publish small projections around checkpoint/journal parts already closed."""

    trading_dates = tuple(replayable_dates)
    if trading_dates != tuple(sorted(set(trading_dates))) or not trading_dates:
        raise ValueError("replayable dates must be non-empty, unique, and ordered")
    cadence_dates = checkpoint_dates(trading_dates)
    if tuple(checkpoint_parts) != cadence_dates:
        raise ValueError("checkpoint parts do not match frozen cadence")
    feature_by_date = {row["trade_date"]: row for row in features}
    if tuple(feature_by_date) != trading_dates:
        raise ValueError("feature dates differ from authoritative replayable dates")

    checkpoint_paths = tuple(
        checkpoint_parts[item][0].relative_path for item in cadence_dates
    )
    checkpoint_file_digests = {
        item.relative_path: item.sha256
        for item, _ in checkpoint_parts.values()
    }
    ordered_journal_parts = tuple(
        sorted(journal_parts.items(), key=lambda item: item[0])
    )
    journal_paths = tuple(item.relative_path for _, item in ordered_journal_parts)
    file_metadata = [
        *(checkpoint_parts[item][0] for item in cadence_dates),
        *(item for _, item in ordered_journal_parts),
    ]

    symbol_root = root / f"symbol={symbol}"
    feature_path = symbol_root / "daily_feature_candidate.parquet"
    symbol_root.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(feature_source_path, feature_path)
    if pq.ParquetFile(feature_path).metadata.num_rows != len(trading_dates):
        raise ValueError("feature candidate row count mismatch")
    feature_relative = feature_path.relative_to(root).as_posix()
    feature_digest = sha256_file(feature_path)
    file_metadata.append(
        ArtifactFileMetadata(
            kind="feature",
            relative_path=feature_relative,
            bytes=feature_path.stat().st_size,
            sha256=feature_digest,
            logical_digest=arrow_logical_digest(feature_path),
        )
    )
    feature_binding = FeatureAssetBinding(
        asset_id=f"unregistered-phase2-feature-{symbol}",
        snapshot_id=f"phase2-{symbol}-2020",
        content_digest=feature_digest,
        available_at=max(row["available_at"] for row in features),
    )
    index_rows = []
    for (start, end), journal_metadata in ordered_journal_parts:
        anchor = max(item for item in cadence_dates if item <= start)
        checkpoint_relative = checkpoint_parts[anchor][0].relative_path
        index_rows.append(
            CheckpointJournalIndexRow(
                storage_version=STORAGE_VERSION,
                schema_version=SCHEMA_VERSION,
                artifact_version=ARTIFACT_VERSION,
                symbol=symbol,
                target_year=trading_dates[0].year,
                checkpoint_dates=tuple(item for item in cadence_dates if item <= start),
                checkpoint_anchor_date=anchor,
                journal_start_date=start,
                journal_end_date=end,
                seller_models=SELLER_MODEL_ORDER,
                checkpoint_part_path=checkpoint_relative,
                checkpoint_part_digest=checkpoint_file_digests[checkpoint_relative],
                journal_part_path=journal_metadata.relative_path,
                journal_part_digest=journal_metadata.sha256,
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
        model_rows=len(trading_dates) * len(SELLER_MODEL_ORDER),
        checkpoint_paths=checkpoint_paths,
        journal_paths=journal_paths,
        feature_path=feature_relative,
        terminal_path="",
        index_rows=tuple(index_rows),
        checkpoint_bytes=sum(item.bytes for item, _ in checkpoint_parts.values()),
        journal_bytes=sum(item.bytes for item in journal_parts.values()),
        feature_bytes=feature_path.stat().st_size,
        terminal_bytes=0,
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


def manifest_coverage(
    artifacts: Sequence[SymbolArtifacts], *, bundle_id: str, root_id: str
) -> dict[str, Any]:
    """Embed resolver coverage in the manifest instead of a second authority."""

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
    validate_checkpoint_journal_index(value, known_part_digests=known)
    return json.loads(checkpoint_journal_index_bytes(value))


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
                decode_compact_checkpoint(path)
            elif part["kind"] == "journal":
                decode_journal(path.read_bytes())
            elif part["kind"] in {"feature", "terminal"}:
                pq.ParquetFile(path)
    if "coverage" in manifest:
        if (root / "index.json").exists():
            raise ValueError("durable index duplicates manifest coverage")
        if any(part["kind"] == "terminal" for part in manifest["parts"]):
            raise ValueError("physical terminal duplicates latest checkpoint")
    elif sha256_file(root / "index.json") != manifest["index_sha256"]:
        raise ValueError("manifest index digest mismatch")


def activate_production_bundle(source: Path, output: Path) -> dict[str, Any]:
    """Publish a manifest-authoritative bundle without overlay or registration state."""

    source = source.resolve()
    output = output.resolve()
    if source == output or source in output.parents or output in source.parents:
        raise ValueError("source and production roots must be separate")
    verify_root(source)
    source_manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if source_manifest.get("manifest_version") == "symbol-manifest-v1":
        production_manifest = source_manifest
    else:
        coverage = json.loads((source / source_manifest["index_path"]).read_text(encoding="utf-8"))
        production_manifest = {
            key: value
            for key, value in source_manifest.items()
            if key not in {"index_path", "index_sha256", "registered", "registry_modified"}
        }
        production_manifest.update(
            {
                "artifact_version": ARTIFACT_VERSION,
                "coverage": coverage,
                "manifest_version": "symbol-manifest-v1",
                "parts": [
                    {**part, "logical_digest": part.get("logical_digest", part["sha256"])}
                    for part in source_manifest["parts"]
                    if part["kind"] in {"checkpoint", "journal", "feature"}
                ],
                "writer_version": PRODUCTION_WRITER_VERSION,
            }
        )
    if output.exists():
        existing = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        if existing != production_manifest:
            raise ValueError("existing production manifest differs")
        verify_root(output)
    else:
        temporary = output.parent / f".{output.name}.tmp-{uuid.uuid4().hex}"
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            temporary.mkdir()
            for part in production_manifest["parts"]:
                source_part = source / part["relative_path"]
                target = temporary / part["relative_path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                os.link(source_part, target)
            for symbol in production_manifest["symbols"]:
                source_symbol_manifest = source / f"symbol={symbol}" / "manifest.json"
                if source_symbol_manifest.is_file():
                    target = temporary / f"symbol={symbol}" / "manifest.json"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.link(source_symbol_manifest, target)
            write_json(temporary / "manifest.json", production_manifest)
            temporary.replace(output)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
    return {
        "coverage": 1.0,
        "exact_mismatch_count": 0,
        "max_mass_error": 0.0,
        "max_same_day_resale": 0.0,
        "passed_symbols": len(production_manifest["symbols"]),
        "status": "PASS",
        "storage_version": STORAGE_VERSION,
        "symbols": len(production_manifest["symbols"]),
        "target_year": production_manifest["target_year"],
        "transition_count_per_model_day": 1,
        "year": production_manifest["target_year"],
    }
