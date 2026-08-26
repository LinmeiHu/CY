"""Pure Phase 1 checkpoint/journal index types and fail-closed validation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import PurePosixPath

from cyq_game.chip.checkpoint_journal_contract import (
    ARTIFACT_VERSION,
    SCHEMA_VERSION,
    SELLER_MODEL_ORDER,
    STORAGE_VERSION,
    ContractError,
    FeatureAssetBinding,
    canonical_json_bytes,
    logical_sha256,
)

INDEX_VERSION = "chip-checkpoint-journal-index-v1"
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class CheckpointJournalIndexRow:
    storage_version: str
    schema_version: str
    artifact_version: str
    symbol: str
    target_year: int
    checkpoint_dates: tuple[date, ...]
    checkpoint_anchor_date: date
    journal_start_date: date
    journal_end_date: date
    seller_models: tuple[str, ...]
    checkpoint_part_path: str
    checkpoint_part_digest: str
    journal_part_path: str
    journal_part_digest: str
    dependency_manifest_digest: str
    replay_parameter_manifest_digest: str
    terminal_completeness_digest: str
    feature_binding: FeatureAssetBinding
    bundle_id: str
    root_id: str


@dataclass(frozen=True)
class CheckpointJournalIndex:
    index_version: str
    storage_version: str
    schema_version: str
    artifact_version: str
    bundle_id: str
    root_id: str
    rows: tuple[CheckpointJournalIndexRow, ...]
    index_digest: str


def _digest(value: str, name: str) -> None:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise ContractError(f"{name} must be a lowercase SHA-256 digest")


def _safe_part_path(value: str) -> None:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ContractError("index part path must be a non-empty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or value.startswith("/"):
        raise ContractError("absolute index part path/root escape is forbidden")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ContractError("index part path traversal/root escape is forbidden")
    for part in path.parts:
        lowered = part.lower()
        if (
            lowered in {"tmp", "partial"}
            or lowered.startswith("tmp-")
            or lowered.startswith("partial-")
            or lowered.endswith((".tmp", ".partial", ".incomplete"))
        ):
            raise ContractError("index cannot reference partial/tmp shard")
    if path.as_posix() != value:
        raise ContractError("index part path is not canonical")


def _index_payload(value: CheckpointJournalIndex) -> dict[str, object]:
    return {
        "artifact_version": value.artifact_version,
        "bundle_id": value.bundle_id,
        "index_version": value.index_version,
        "root_id": value.root_id,
        "rows": value.rows,
        "schema_version": value.schema_version,
        "storage_version": value.storage_version,
    }


def checkpoint_journal_index_digest(value: CheckpointJournalIndex) -> str:
    return logical_sha256(_index_payload(value))


def checkpoint_journal_index_bytes(value: CheckpointJournalIndex) -> bytes:
    validate_checkpoint_journal_index(value)
    return canonical_json_bytes({**_index_payload(value), "index_digest": value.index_digest})


def validate_checkpoint_journal_index(
    value: CheckpointJournalIndex,
    *,
    known_part_digests: Mapping[str, str] | None = None,
) -> None:
    if (
        value.index_version,
        value.storage_version,
        value.schema_version,
        value.artifact_version,
    ) != (INDEX_VERSION, STORAGE_VERSION, SCHEMA_VERSION, ARTIFACT_VERSION):
        raise ContractError("index contains an unknown or mixed version")
    if not value.bundle_id or not value.root_id:
        raise ContractError("index bundle/root identity cannot be empty")
    if not value.rows:
        raise ContractError("checkpoint/journal index cannot be empty")
    ordering = tuple(
        (
            row.symbol.encode("utf-8"),
            row.journal_start_date,
            row.journal_end_date,
            row.checkpoint_anchor_date,
        )
        for row in value.rows
    )
    if ordering != tuple(sorted(ordering)):
        raise ContractError("index rows are not in deterministic canonical order")
    seen_ranges: set[tuple[str, date, date]] = set()
    last_end_by_symbol: dict[str, date] = {}
    for row in value.rows:
        if (
            row.storage_version,
            row.schema_version,
            row.artifact_version,
        ) != (STORAGE_VERSION, SCHEMA_VERSION, ARTIFACT_VERSION):
            raise ContractError("same index/root mixed versions are forbidden")
        if row.bundle_id != value.bundle_id or row.root_id != value.root_id:
            raise ContractError("index row bundle/root identity mismatch")
        if not row.symbol or not 1900 <= row.target_year <= 9999:
            raise ContractError("invalid index symbol/target year")
        if row.seller_models != SELLER_MODEL_ORDER:
            raise ContractError("index row is missing a seller model or has wrong order")
        if row.journal_start_date > row.journal_end_date:
            raise ContractError("journal date range is inverted")
        if (
            row.journal_start_date.year != row.target_year
            or row.journal_end_date.year != row.target_year
        ):
            raise ContractError("journal range is outside target year")
        if not row.checkpoint_dates:
            raise ContractError("index row has no checkpoint coverage")
        if row.checkpoint_dates != tuple(sorted(set(row.checkpoint_dates))):
            raise ContractError("checkpoint dates must be unique and sorted")
        if any(item.year != row.target_year for item in row.checkpoint_dates):
            raise ContractError("checkpoint date is outside target year")
        eligible = tuple(item for item in row.checkpoint_dates if item <= row.journal_start_date)
        if not eligible or row.checkpoint_anchor_date != eligible[-1]:
            raise ContractError("journal range lacks its latest checkpoint anchor coverage")
        range_key = (row.symbol, row.journal_start_date, row.journal_end_date)
        if range_key in seen_ranges:
            raise ContractError("duplicate symbol/journal range")
        seen_ranges.add(range_key)
        previous_end = last_end_by_symbol.get(row.symbol)
        if previous_end is not None and row.journal_start_date <= previous_end:
            raise ContractError("overlapping journal ranges")
        last_end_by_symbol[row.symbol] = row.journal_end_date
        for part_path, part_digest, name in (
            (row.checkpoint_part_path, row.checkpoint_part_digest, "checkpoint part digest"),
            (row.journal_part_path, row.journal_part_digest, "journal part digest"),
        ):
            _safe_part_path(part_path)
            _digest(part_digest, name)
            if known_part_digests is not None:
                if part_path not in known_part_digests:
                    raise ContractError("index references a missing part")
                if known_part_digests[part_path] != part_digest:
                    raise ContractError("index references a stale/mismatched part digest")
        for digest_value, name in (
            (row.dependency_manifest_digest, "dependency manifest digest"),
            (row.replay_parameter_manifest_digest, "replay parameter manifest digest"),
            (row.terminal_completeness_digest, "terminal completeness digest"),
            (row.feature_binding.content_digest, "feature binding digest"),
        ):
            _digest(digest_value, name)
        if not row.feature_binding.asset_id or not row.feature_binding.snapshot_id:
            raise ContractError("feature asset binding is incomplete")
        if (
            row.feature_binding.available_at.tzinfo is None
            or row.feature_binding.available_at.utcoffset() is None
        ):
            raise ContractError("feature binding available_at must be timezone-aware")
    _digest(value.index_digest, "index digest")
    if checkpoint_journal_index_digest(value) != value.index_digest:
        raise ContractError("index digest mismatch")
