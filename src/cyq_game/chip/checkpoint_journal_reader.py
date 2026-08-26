"""Fail-closed Phase 3 reader for unregistered checkpoint/journal bundles."""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Protocol, Sequence

import pyarrow.parquet as pq

from cyq_game.chip.checkpoint_codec import (
    checkpoint_logical_digest,
    decode_checkpoint,
)
from cyq_game.chip.checkpoint_journal_contract import (
    ARTIFACT_VERSION,
    SCHEMA_VERSION,
    SELLER_MODEL_ORDER,
    STORAGE_VERSION,
    CheckpointLogical,
    ContractError,
    DependencyClass,
    FeatureAssetBinding,
    bits_f64be,
    strict_json_loads,
)
from cyq_game.chip.checkpoint_journal_index import (
    INDEX_VERSION,
    CheckpointJournalIndex,
    CheckpointJournalIndexRow,
    validate_checkpoint_journal_index,
)
from cyq_game.chip.checkpoint_journal_writer import digest_suffix, sha256_file
from cyq_game.chip.journal_codec import (
    JournalDay,
    JournalDependencyReference,
    JournalModelDigests,
    decode_journal,
)
from cyq_game.chip.migration_v2 import (
    StableLogPriceGrid,
    bucket_for_economic_break_even,
)

PHASE3_READER_VERSION = "checkpoint-journal-reader-phase3-v1"
PHASE2_MANIFEST_VERSION = "v12-phase2-checkpoint-journal-3symbol-candidate-v1"
CANONICAL_ECONOMIC_COORDINATE = "economic_break_even_bits"
FROZEN_ECONOMIC_COORDINATE_VERSION = "causal-economic-price-v2"
FROZEN_ECONOMIC_BUCKET_RULE = "log-grid-25bp-v1"
_FROZEN_ECONOMIC_GRID = StableLogPriceGrid(
    1.0, 0.0025, FROZEN_ECONOMIC_BUCKET_RULE
)


class CheckpointJournalReadError(ContractError):
    """A root, dependency, replay, or compatibility check failed closed."""


def derive_economic_bucket(
    economic_break_even_bits: int | None,
    *,
    coordinate_version: str,
) -> int | None:
    """Derive the compatibility bucket from the canonical binary64 coordinate."""

    if coordinate_version != FROZEN_ECONOMIC_COORDINATE_VERSION:
        raise CheckpointJournalReadError("unknown economic coordinate version")
    if economic_break_even_bits is None:
        return None
    value = bits_f64be(economic_break_even_bits)
    if not math.isfinite(value) or value <= 0.0:
        raise CheckpointJournalReadError("invalid canonical economic coordinate")
    return bucket_for_economic_break_even(_FROZEN_ECONOMIC_GRID, value)


@dataclass(frozen=True)
class DependencyRecord:
    dependency_class: DependencyClass
    asset_id: str
    snapshot_id: str
    content_digest: str
    inventory_digest: str | None


class DependencyCatalog:
    def __init__(self, records: Sequence[DependencyRecord]) -> None:
        self._records: dict[tuple[DependencyClass, str, str], DependencyRecord] = {}
        for record in records:
            key = (record.dependency_class, record.asset_id, record.snapshot_id)
            if key in self._records:
                raise CheckpointJournalReadError("duplicate dependency catalog binding")
            self._records[key] = record

    @classmethod
    def from_journal_rows(cls, rows: Sequence[JournalDay]) -> DependencyCatalog:
        """Build a validation-only catalog from independently frozen bindings."""

        records: dict[tuple[DependencyClass, str, str], DependencyRecord] = {}
        for row in rows:
            for reference in row.dependency_references:
                record = DependencyRecord(
                    dependency_class=reference.dependency_class,
                    asset_id=reference.asset_id,
                    snapshot_id=reference.snapshot_id,
                    content_digest=reference.content_digest,
                    inventory_digest=reference.inventory_digest,
                )
                key = (record.dependency_class, record.asset_id, record.snapshot_id)
                previous = records.setdefault(key, record)
                if previous != record:
                    raise CheckpointJournalReadError(
                        "dependency identity has conflicting frozen digests"
                    )
        return cls(tuple(records.values()))

    def validate(self, reference: JournalDependencyReference) -> None:
        key = (
            reference.dependency_class,
            reference.asset_id,
            reference.snapshot_id,
        )
        record = self._records.get(key)
        if record is None:
            raise CheckpointJournalReadError("required replay dependency is missing")
        if (
            record.content_digest != reference.content_digest
            or record.inventory_digest != reference.inventory_digest
        ):
            raise CheckpointJournalReadError("replay dependency digest mismatch")


@dataclass(frozen=True)
class ReplayStep:
    state: Any
    model_digests: tuple[JournalModelDigests, ...]


class ReplayBackend(Protocol):
    def restore_checkpoint(self, checkpoint: CheckpointLogical) -> Any: ...

    def advance_day(self, state: Any, row: JournalDay) -> ReplayStep: ...


@dataclass(frozen=True)
class RestoredDay:
    symbol: str
    trading_date: date
    checkpoint_date: date
    replayed_dates: tuple[date, ...]
    model_digests: tuple[JournalModelDigests, ...]
    state: Any


def _safe_relative(value: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise CheckpointJournalReadError("artifact path is not canonical POSIX relative")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise CheckpointJournalReadError("artifact path escapes the immutable root")
    if path.as_posix() != value:
        raise CheckpointJournalReadError("artifact path is not canonical")
    return Path(*path.parts)


def _timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise CheckpointJournalReadError("index timestamp is not canonical UTC")
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise CheckpointJournalReadError("invalid index timestamp") from exc
    if result.tzinfo is None:
        raise CheckpointJournalReadError("index timestamp must be timezone-aware")
    return result


def _integer(value: Any, name: str) -> int:
    if not isinstance(value, str) or not value or value.startswith("+"):
        raise CheckpointJournalReadError(f"{name} is not a canonical integer string")
    try:
        result = int(value)
    except ValueError as exc:
        raise CheckpointJournalReadError(f"{name} is invalid") from exc
    if str(result) != value:
        raise CheckpointJournalReadError(f"{name} is not canonical")
    return result


def _parse_index_row(raw: Any) -> CheckpointJournalIndexRow:
    if not isinstance(raw, dict):
        raise CheckpointJournalReadError("index row must be an object")
    expected = {
        "artifact_version",
        "bundle_id",
        "checkpoint_anchor_date",
        "checkpoint_dates",
        "checkpoint_part_digest",
        "checkpoint_part_path",
        "dependency_manifest_digest",
        "feature_binding",
        "journal_end_date",
        "journal_part_digest",
        "journal_part_path",
        "journal_start_date",
        "replay_parameter_manifest_digest",
        "root_id",
        "schema_version",
        "seller_models",
        "storage_version",
        "symbol",
        "target_year",
        "terminal_completeness_digest",
    }
    if set(raw) != expected:
        raise CheckpointJournalReadError("index row fields mismatch")
    feature = raw["feature_binding"]
    if not isinstance(feature, dict) or set(feature) != {
        "asset_id",
        "available_at",
        "content_digest",
        "snapshot_id",
    }:
        raise CheckpointJournalReadError("feature binding fields mismatch")
    try:
        checkpoint_dates = tuple(date.fromisoformat(item) for item in raw["checkpoint_dates"])
        checkpoint_anchor = date.fromisoformat(raw["checkpoint_anchor_date"])
        journal_start = date.fromisoformat(raw["journal_start_date"])
        journal_end = date.fromisoformat(raw["journal_end_date"])
    except (TypeError, ValueError) as exc:
        raise CheckpointJournalReadError("invalid index date") from exc
    return CheckpointJournalIndexRow(
        storage_version=raw["storage_version"],
        schema_version=raw["schema_version"],
        artifact_version=raw["artifact_version"],
        symbol=raw["symbol"],
        target_year=_integer(raw["target_year"], "target_year"),
        checkpoint_dates=checkpoint_dates,
        checkpoint_anchor_date=checkpoint_anchor,
        journal_start_date=journal_start,
        journal_end_date=journal_end,
        seller_models=tuple(raw["seller_models"]),
        checkpoint_part_path=raw["checkpoint_part_path"],
        checkpoint_part_digest=raw["checkpoint_part_digest"],
        journal_part_path=raw["journal_part_path"],
        journal_part_digest=raw["journal_part_digest"],
        dependency_manifest_digest=raw["dependency_manifest_digest"],
        replay_parameter_manifest_digest=raw["replay_parameter_manifest_digest"],
        terminal_completeness_digest=raw["terminal_completeness_digest"],
        feature_binding=FeatureAssetBinding(
            asset_id=feature["asset_id"],
            snapshot_id=feature["snapshot_id"],
            content_digest=feature["content_digest"],
            available_at=_timestamp(feature["available_at"]),
        ),
        bundle_id=raw["bundle_id"],
        root_id=raw["root_id"],
    )


def _read_index(path: Path, known: Mapping[str, str]) -> CheckpointJournalIndex:
    raw = strict_json_loads(path.read_bytes())
    if not isinstance(raw, dict) or set(raw) != {
        "artifact_version",
        "bundle_id",
        "index_digest",
        "index_version",
        "root_id",
        "rows",
        "schema_version",
        "storage_version",
    }:
        raise CheckpointJournalReadError("index fields mismatch")
    if not isinstance(raw["rows"], list):
        raise CheckpointJournalReadError("index rows must be an array")
    value = CheckpointJournalIndex(
        index_version=raw["index_version"],
        storage_version=raw["storage_version"],
        schema_version=raw["schema_version"],
        artifact_version=raw["artifact_version"],
        bundle_id=raw["bundle_id"],
        root_id=raw["root_id"],
        rows=tuple(_parse_index_row(item) for item in raw["rows"]),
        index_digest=raw["index_digest"],
    )
    validate_checkpoint_journal_index(value, known_part_digests=known)
    return value


class CheckpointJournalReader:
    def __init__(
        self,
        root: str | Path,
        *,
        replay_parameter_manifest_digest: str,
        dependency_catalog: DependencyCatalog,
    ) -> None:
        self.root = Path(root)
        self.dependency_catalog = dependency_catalog
        self.expected_replay_parameter_manifest_digest = (
            replay_parameter_manifest_digest
        )
        self.manifest = self._read_manifest()
        if (
            self.manifest["replay_parameter_manifest_digest"]
            != replay_parameter_manifest_digest
        ):
            raise CheckpointJournalReadError("replay parameter manifest mismatch")
        known = {
            part["relative_path"]: part["sha256"]
            for part in self.manifest["parts"]
            if part["kind"] in {"checkpoint", "journal"}
        }
        index_path = self.root / _safe_relative(self.manifest["index_path"])
        if sha256_file(index_path) != self.manifest["index_sha256"]:
            raise CheckpointJournalReadError("index physical digest mismatch")
        self.index = _read_index(index_path, known)
        if (
            self.index.bundle_id != self.manifest["bundle_id"]
            or self.index.root_id != self.manifest["root_id"]
        ):
            raise CheckpointJournalReadError("manifest/index root identity mismatch")

    def _read_manifest(self) -> dict[str, Any]:
        path = self.root / "manifest.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CheckpointJournalReadError("missing or invalid root manifest") from exc
        if not isinstance(raw, dict):
            raise CheckpointJournalReadError("root manifest must be an object")
        expected = {
            "artifact_version",
            "bundle_id",
            "checkpoint_cadence",
            "dependency_manifest_digest",
            "index_path",
            "index_sha256",
            "parts",
            "registered",
            "registry_modified",
            "replay_contract_hash",
            "replay_parameter_manifest_digest",
            "root_id",
            "seller_models",
            "symbols",
            "target_year",
            "terminal_completeness_digest",
            "writer_version",
        }
        if set(raw) != expected:
            raise CheckpointJournalReadError("root manifest fields mismatch")
        if raw["artifact_version"] != PHASE2_MANIFEST_VERSION:
            raise CheckpointJournalReadError("unknown or mixed root version")
        if raw["registered"] is not False or raw["registry_modified"] is not False:
            raise CheckpointJournalReadError("Phase 3 cannot read an activated prototype root")
        if tuple(raw["seller_models"]) != SELLER_MODEL_ORDER:
            raise CheckpointJournalReadError("root seller model coverage mismatch")
        if not isinstance(raw["parts"], list):
            raise CheckpointJournalReadError("manifest parts must be an array")
        seen: set[str] = set()
        for part in raw["parts"]:
            if not isinstance(part, dict) or set(part) != {
                "bytes",
                "kind",
                "relative_path",
                "sha256",
            }:
                raise CheckpointJournalReadError("manifest part is invalid")
            relative = part["relative_path"]
            if relative in seen:
                raise CheckpointJournalReadError("manifest part path is duplicated")
            seen.add(relative)
            physical = self.root / _safe_relative(relative)
            if not physical.is_file():
                raise CheckpointJournalReadError("manifest part is missing")
            if sha256_file(physical) != part["sha256"]:
                raise CheckpointJournalReadError("manifest part physical digest mismatch")
        return raw

    def _coverage(self, symbol: str, target: date) -> CheckpointJournalIndexRow:
        matches = tuple(
            row
            for row in self.index.rows
            if row.symbol == symbol
            and row.journal_start_date <= target <= row.journal_end_date
        )
        if len(matches) != 1:
            raise CheckpointJournalReadError("target date lacks unique index coverage")
        return matches[0]

    def _checkpoint(self, row: CheckpointJournalIndexRow) -> CheckpointLogical:
        path = self.root / _safe_relative(row.checkpoint_part_path)
        if sha256_file(path) != row.checkpoint_part_digest:
            raise CheckpointJournalReadError("checkpoint physical digest mismatch")
        value = decode_checkpoint(path.read_bytes())
        if (
            value.symbol != row.symbol
            or value.checkpoint_date != row.checkpoint_anchor_date
            or value.replay_parameter_manifest_digest
            != self.expected_replay_parameter_manifest_digest
        ):
            raise CheckpointJournalReadError("checkpoint/index identity mismatch")
        return value

    def _journal(self, row: CheckpointJournalIndexRow) -> tuple[JournalDay, ...]:
        path = self.root / _safe_relative(row.journal_part_path)
        if sha256_file(path) != row.journal_part_digest:
            raise CheckpointJournalReadError("journal physical digest mismatch")
        value = decode_journal(path.read_bytes())
        if (
            value.symbol != row.symbol
            or value.replay_parameter_manifest_digest
            != self.expected_replay_parameter_manifest_digest
            or not value.rows
            or value.rows[0].trading_date != row.journal_start_date
            or value.rows[-1].trading_date != row.journal_end_date
        ):
            raise CheckpointJournalReadError("journal/index identity mismatch")
        return value.rows

    def restore(
        self,
        symbol: str,
        target: date,
        *,
        backend: ReplayBackend,
    ) -> RestoredDay:
        coverage = self._coverage(symbol, target)
        checkpoint = self._checkpoint(coverage)
        journal_rows = self._journal(coverage)
        expected_checkpoint_digest = checkpoint_logical_digest(checkpoint)
        for row in journal_rows:
            if row.checkpoint_parent_digest != expected_checkpoint_digest:
                raise CheckpointJournalReadError("journal checkpoint parent mismatch")
        state = backend.restore_checkpoint(checkpoint)
        replayed: list[date] = []
        result_digests: tuple[JournalModelDigests, ...] | None = None
        for row in journal_rows:
            if row.trading_date > target:
                break
            for dependency in row.dependency_references:
                self.dependency_catalog.validate(dependency)
            if row.trading_date <= checkpoint.checkpoint_date:
                if row.trading_date == target:
                    self._validate_checkpoint_ids(checkpoint, row.model_digests)
                    result_digests = row.model_digests
                continue
            step = backend.advance_day(state, row)
            if step.model_digests != row.model_digests:
                raise CheckpointJournalReadError("recomputed daily state digest mismatch")
            state = step.state
            result_digests = step.model_digests
            replayed.append(row.trading_date)
        if result_digests is None:
            raise CheckpointJournalReadError("target day was not restored")
        return RestoredDay(
            symbol=symbol,
            trading_date=target,
            checkpoint_date=checkpoint.checkpoint_date,
            replayed_dates=tuple(replayed),
            model_digests=result_digests,
            state=state,
        )

    @staticmethod
    def _validate_checkpoint_ids(
        checkpoint: CheckpointLogical,
        digests: tuple[JournalModelDigests, ...],
    ) -> None:
        if tuple(item.seller_model for item in digests) != SELLER_MODEL_ORDER:
            raise CheckpointJournalReadError("checkpoint target seller models are incomplete")
        for state, digest in zip(checkpoint.model_states, digests, strict=True):
            if digest_suffix(state.snapshot_id) != digest.post_state_digest:
                raise CheckpointJournalReadError("checkpoint state ID mismatch")

    def latest_checkpoint(self, symbol: str) -> CheckpointLogical:
        parts = [
            part
            for part in self.manifest["parts"]
            if part["kind"] == "checkpoint"
            and part["relative_path"].startswith(f"symbol={symbol}/")
        ]
        values = [
            decode_checkpoint((self.root / _safe_relative(part["relative_path"])).read_bytes())
            for part in parts
        ]
        if not values:
            raise CheckpointJournalReadError("symbol has no checkpoint")
        latest = max(values, key=lambda value: value.checkpoint_date)
        if latest.symbol != symbol:
            raise CheckpointJournalReadError("latest checkpoint symbol mismatch")
        return latest

    def terminal_compatibility_mismatch_count(self, symbol: str) -> int:
        checkpoint = self.latest_checkpoint(symbol)
        terminal_parts = [
            part
            for part in self.manifest["parts"]
            if part["kind"] == "terminal"
            and part["relative_path"].startswith(f"symbol={symbol}/")
        ]
        if len(terminal_parts) != 1:
            raise CheckpointJournalReadError("symbol terminal candidate is missing or duplicated")
        path = self.root / _safe_relative(terminal_parts[0]["relative_path"])
        actual = pq.ParquetFile(path).read().to_pylist()
        expected = _terminal_rows(checkpoint)
        if len(actual) != len(expected):
            return 1
        return sum(
            not _exact_value_equal(left, right)
            for left, right in zip(actual, expected, strict=True)
        )


def _terminal_rows(checkpoint: CheckpointLogical) -> list[dict[str, Any]]:
    identities = checkpoint.identities
    result = []
    for state in checkpoint.model_states:
        cells = []
        for lot in state.lots:
            identity = identities[lot.identity_position]
            cells.append(
                {
                    "cell_id": identity.cell_id,
                    "cost_bucket_id": identity.cost_bucket_id,
                    "holding_days": identity.holding_days,
                    "sensitivity": identity.sensitivity,
                    "acquisition_cost": (
                        None
                        if lot.acquisition_cost_bits is None
                        else bits_f64be(lot.acquisition_cost_bits)
                    ),
                    "economic_break_even": (
                        None
                        if identity.economic_break_even_bits is None
                        else bits_f64be(identity.economic_break_even_bits)
                    ),
                    "shares": bits_f64be(lot.shares_bits),
                    "initialization_prior_units": bits_f64be(
                        lot.initialization_prior_units_bits
                    ),
                }
            )
        result.append(
            {
                "storage_version": "chip-operator-log-v13",
                "model_version": state.model_version,
                "grid_version": state.grid_version,
                "symbol": checkpoint.symbol,
                "trading_date": checkpoint.checkpoint_date,
                "decision_at": state.decision_at,
                "effective_at": state.effective_at,
                "available_at": state.available_at,
                "phase": state.phase,
                "snapshot_id": state.snapshot_id,
                "seller_model": state.seller_model,
                "free_float_shares": bits_f64be(state.free_float_shares_bits),
                "latent_supply_shares": bits_f64be(state.latent_supply_shares_bits),
                "input_snapshot_ids": list(state.input_snapshot_ids),
                "pit_grade": state.pit_grade,
                "hard_valid": state.hard_valid,
                "quality_reason_codes": list(state.quality_reason_codes),
                "cells": cells,
            }
        )
    return result


def _exact_value_equal(left: Any, right: Any) -> bool:
    if isinstance(left, float) and isinstance(right, float):
        return struct.pack(">d", left) == struct.pack(">d", right)
    if isinstance(left, datetime) and isinstance(right, datetime):
        return left.astimezone(UTC) == right.astimezone(UTC)
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return set(left) == set(right) and all(
            _exact_value_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, Sequence) and isinstance(right, Sequence) and not isinstance(
        left, (str, bytes, bytearray)
    ):
        return len(left) == len(right) and all(
            _exact_value_equal(a, b) for a, b in zip(left, right, strict=True)
        )
    return left == right


def journal_rows_for_catalog(root: str | Path) -> tuple[JournalDay, ...]:
    """Read all journal rows after root integrity validation by the caller."""

    bundle_root = Path(root)
    manifest = json.loads((bundle_root / "manifest.json").read_text(encoding="utf-8"))
    rows: list[JournalDay] = []
    for part in manifest["parts"]:
        if part["kind"] == "journal":
            path = bundle_root / _safe_relative(part["relative_path"])
            if sha256_file(path) != part["sha256"]:
                raise CheckpointJournalReadError("journal catalog source digest mismatch")
            rows.extend(decode_journal(path.read_bytes()).rows)
    return tuple(rows)
