"""Resolve strategy-anchor survival from persisted PIT chip transitions."""

from __future__ import annotations

import math
import struct
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from cyq_game.chip.ensemble_v2 import (
    SELLER_MODEL_ORDER,
    AnchorRetentionEstimate,
    trace_to_date,
)
from cyq_game.chip.migration_v2 import (
    DEFAULT_MAX_HOLDING_DAYS,
    StableLogPriceGrid,
    bucket_for_economic_break_even,
    economic_break_even_for_bucket,
)
from cyq_game.chip.state_v2 import (
    AnchorTraceCache,
    ChipSnapshotV2,
    ChipStateContractError,
    OriginSurvivalTransition,
    OriginTracer,
    SellerModel,
    SnapshotPhase,
    tolerance,
)
from cyq_game.strategy.markup_retest import LifecycleAnchor, LifecycleObservation
from cyq_game.strategy.semantic_contract import OPERATOR_LOG_VERSION

_OPERATOR_STORAGE_VERSION = OPERATOR_LOG_VERSION
_COMPATIBLE_OPERATOR_STORAGE_VERSIONS = frozenset(
    {
        "chip-operator-log-v8",
        "chip-operator-log-v9",
        "chip-operator-log-v10",
        "chip-operator-log-v11",
        _OPERATOR_STORAGE_VERSION,
    }
)
_OPERATOR_GRID = StableLogPriceGrid(1.0, 0.0025, "log-grid-25bp-v1")
_RETENTION_RAW = 0
_RETENTION_CONSTANT = 1
_RETENTION_PALETTE_U8 = 2
_RETENTION_BY_SENSITIVITY = 3
_RETENTION_XOR = 4
_RETENTION_XOR_BYTE_SHUFFLE = 5
_RETENTION_PALETTE_BITPACK = 7


@dataclass(frozen=True)
class PersistedDailyBucketMass:
    symbol: str
    trade_date: date
    seller_model: SellerModel
    snapshot_id: str
    available_at: Any
    free_float_shares: float
    bucket_mass: tuple[tuple[int, float], ...]
    unknown_mass: float
    research_valid: bool
    average_cost: float
    cost_p10: float
    cost_p50: float
    cost_p90: float
    cash_dividend_per_share: float
    share_multiplier: float
    action_provenance: tuple[str, ...]


@dataclass
class _IncrementalTraceState:
    checkpoint_date: date
    current_date: date
    inventory: dict[int, float]
    lineage: dict[int, float]
    economic_buckets: dict[int, int | None]
    anchor_mass: float


@dataclass(frozen=True)
class _CachedOperatorStep:
    next_inventory: dict[int, float]
    next_economic_buckets: dict[int, int | None]
    lineage_operator: tuple[tuple[int, int, float], ...]


def _unpack_local_id(local_id: int) -> tuple[int | None, int, int]:
    sensitivity = local_id & 3
    holding_code = (local_id >> 2) & 255
    cost_code = local_id >> 10
    if cost_code == 0:
        cost_bucket = None
    else:
        zigzag = cost_code - 1
        cost_bucket = zigzag // 2 if zigzag % 2 == 0 else -(zigzag // 2) - 1
    return cost_bucket, holding_code - 1, sensitivity


def _pack_local_id(cost_bucket: int | None, holding_days: int, sensitivity: int) -> int:
    if cost_bucket is None:
        cost_code = 0
    else:
        zigzag = 2 * cost_bucket if cost_bucket >= 0 else -2 * cost_bucket - 1
        cost_code = zigzag + 1
    return (cost_code << 10) | ((holding_days + 1) << 2) | sensitivity


def _aged_local_id(local_id: int) -> int:
    # Holding code occupies bits 2..9 and equals holding_days + 1.  Aging an
    # ordinary cell is therefore an exact +4 until the cap; UNKNOWN_COST uses
    # code zero and remains unchanged.  Avoid unpacking/repacking every cell on
    # every replay day.
    holding_code = (local_id >> 2) & 255
    if holding_code == 0 or holding_code >= DEFAULT_MAX_HOLDING_DAYS + 1:
        return local_id
    return local_id + 4


def _source_sort_key(local_id: int) -> tuple[bool, int, int, int, int]:
    sensitivity = local_id & 3
    holding_days = ((local_id >> 2) & 255) - 1
    cost_code = local_id >> 10
    if cost_code == 0:
        cost_bucket = None
    else:
        zigzag = cost_code - 1
        cost_bucket = zigzag // 2 if zigzag % 2 == 0 else -(zigzag // 2) - 1
    return (
        cost_bucket is None,
        0 if cost_bucket is None else cost_bucket,
        holding_days,
        sensitivity,
        local_id,
    )


def _unpack_palette(payload: bytes, count: int, bits: int) -> tuple[int, ...]:
    if len(payload) != (count * bits + 7) // 8:
        raise ChipStateContractError("invalid bit-packed retention payload")
    mask = (1 << bits) - 1
    result: list[int] = []
    bit_offset = 0
    for _ in range(count):
        byte_offset = bit_offset >> 3
        shift = bit_offset & 7
        value = payload[byte_offset] >> shift
        if shift + bits > 8:
            value |= payload[byte_offset + 1] << (8 - shift)
        result.append(value & mask)
        bit_offset += bits
    return tuple(result)


def _unpack_xor(payload: bytes, count: int) -> tuple[float, ...]:
    if count == 0:
        if payload:
            raise ChipStateContractError("unexpected empty retention payload")
        return ()
    if len(payload) < 8:
        raise ChipStateContractError("truncated XOR retention payload")
    previous = struct.unpack("<Q", payload[:8])[0]
    result = [struct.unpack("<d", struct.pack("<Q", previous))[0]]
    cursor = 8
    for _ in range(count - 1):
        if cursor >= len(payload):
            raise ChipStateContractError("truncated XOR retention payload")
        tag = payload[cursor]
        cursor += 1
        if tag:
            offset = tag >> 4
            length = tag & 15
            if length == 0 or offset + length > 8 or cursor + length > len(payload):
                raise ChipStateContractError("invalid XOR retention payload")
            delta = int.from_bytes(payload[cursor : cursor + length], "little")
            cursor += length
            previous ^= delta << (offset * 8)
        result.append(struct.unpack("<d", struct.pack("<Q", previous))[0])
    if cursor != len(payload):
        raise ChipStateContractError("trailing XOR retention bytes")
    return tuple(result)


def _unpack_shuffled_xor(payload: bytes, count: int) -> tuple[float, ...]:
    if len(payload) != count * 8:
        raise ChipStateContractError("invalid shuffled XOR retention payload")
    if count == 0:
        return ()
    raw = bytearray(len(payload))
    for byte_offset in range(8):
        start = byte_offset * count
        raw[byte_offset::8] = payload[start : start + count]
    previous = 0
    result: list[float] = []
    for position, word in enumerate(struct.unpack(f"<{count}Q", raw)):
        current = word if position == 0 else word ^ previous
        result.append(struct.unpack("<d", struct.pack("<Q", current))[0])
        previous = current
    return tuple(result)


def _decode_retention(
    row: Mapping[str, Any], sensitivities: tuple[int, ...]
) -> tuple[float, ...]:
    encoding = int(row["retention_encoding"])
    values = tuple(float(value) for value in row["retention_values"])
    payload = bytes(row["retention_codes"] or b"")
    count = len(sensitivities)
    if encoding == _RETENTION_RAW:
        result = values
    elif encoding == _RETENTION_CONSTANT:
        result = (values[0],) * count
    elif encoding == _RETENTION_PALETTE_U8:
        result = tuple(values[index] for index in payload)
    elif encoding == _RETENTION_PALETTE_BITPACK:
        bits = max(1, (len(values) - 1).bit_length())
        result = tuple(values[index] for index in _unpack_palette(payload, count, bits))
    elif encoding == _RETENTION_BY_SENSITIVITY:
        if len(values) < 3 or len(payload) != (len(values) - 3) * 4:
            raise ChipStateContractError("invalid sensitivity retention payload")
        mutable = [values[code] for code in sensitivities]
        if len(values) > 3:
            positions = struct.unpack(f"<{len(values) - 3}I", payload)
            for position, value in zip(positions, values[3:], strict=True):
                mutable[position] = value
        result = tuple(mutable)
    elif encoding == _RETENTION_XOR:
        result = _unpack_xor(payload, count)
    elif encoding == _RETENTION_XOR_BYTE_SHUFFLE:
        result = _unpack_shuffled_xor(payload, count)
    else:
        raise ChipStateContractError(f"unsupported retention encoding {encoding}")
    if len(result) != count or any(not 0.0 <= value <= 1.0 for value in result):
        raise ChipStateContractError("invalid decoded retention vector")
    return result


def _lineage_operator(
    inventory: Mapping[int, float],
    row: Mapping[str, Any],
) -> tuple[tuple[int, int, float], ...]:
    source_override = tuple(
        int(value) for value in (row.get("source_cell_ids_override") or ())
    )
    sources = source_override or tuple(
        sorted(inventory)
        if row.get("storage_version") == _OPERATOR_STORAGE_VERSION
        else sorted(inventory, key=_source_sort_key)
    )
    sensitivities = tuple(source & 3 for source in sources)
    retentions = _decode_retention(row, sensitivities)
    destination_overrides = dict(
        zip(
            (int(value) for value in (row.get("destination_override_positions") or ())),
            (int(value) for value in (row.get("destination_override_cell_ids") or ())),
            strict=True,
        )
    )
    return tuple(
        (
            source,
            destination_overrides.get(position, _aged_local_id(source)),
            retained,
        )
        for position, (source, retained) in enumerate(
            zip(sources, retentions, strict=True)
        )
    )


def _apply_lineage_operator(
    lineage: Mapping[int, float] | None,
    operator: Sequence[tuple[int, int, float]],
) -> dict[int, float]:
    if lineage is None:
        return {}
    next_lineage: dict[int, float] = {}
    collisions: dict[int, list[float]] = {}
    for source, destination, retained in operator:
        shares = lineage.get(source)
        if shares is None:
            continue
        retained_lineage = shares * retained
        if retained_lineage <= 0.0:
            continue
        previous = next_lineage.get(destination)
        if previous is None:
            next_lineage[destination] = retained_lineage
            continue
        collision = collisions.get(destination)
        if collision is None:
            collisions[destination] = [previous, retained_lineage]
        else:
            collision.append(retained_lineage)
    for local_id, parts in collisions.items():
        next_lineage[local_id] = math.fsum(parts)
    return next_lineage


class ChipLineageResolver:
    """Join one lifecycle anchor to all three exact seller-model lineages.

    Daily chip snapshots and transitions are strategy independent.  This
    resolver freezes only cells that existed inside the strategy anchor's
    original cost interval and follows their descendants.  New chips entering
    that interval can therefore never masquerade as retained base inventory.
    """

    def __init__(
        self,
        snapshots: Iterable[ChipSnapshotV2],
        transitions: Iterable[OriginSurvivalTransition],
        *,
        ensemble_version: str = "chip-lineage-ensemble-v1",
    ) -> None:
        if not ensemble_version:
            raise ChipStateContractError("ensemble_version cannot be empty")
        self.ensemble_version = ensemble_version
        self._snapshots_by_key: dict[tuple[str, date, SellerModel], ChipSnapshotV2] = {}
        self._snapshots_by_id: dict[str, ChipSnapshotV2] = {}
        self._transitions_by_source: dict[str, OriginSurvivalTransition] = {}
        self._anchor_contracts: dict[str, tuple[str, date, float, float]] = {}
        self._result_cache: dict[tuple[str, str, date, str], AnchorRetentionEstimate] = {}
        # AnchorTraceCacheKey intentionally omits seller_model.  Keep a cache
        # per root/model so equal version strings cannot cross-contaminate.
        self._trace_caches: dict[tuple[str, SellerModel], AnchorTraceCache] = {}

        for snapshot in snapshots:
            if snapshot.phase != SnapshotPhase.POST:
                continue
            key = (snapshot.symbol, snapshot.trading_date, snapshot.seller_model)
            existing = self._snapshots_by_key.get(key)
            if existing is not None and existing != snapshot:
                raise ChipStateContractError(
                    "conflicting POST snapshots for symbol/date/seller model"
                )
            by_id = self._snapshots_by_id.get(snapshot.snapshot_id)
            if by_id is not None and by_id != snapshot:
                raise ChipStateContractError("conflicting snapshot_id definitions")
            self._snapshots_by_key[key] = snapshot
            self._snapshots_by_id[snapshot.snapshot_id] = snapshot

        for transition in transitions:
            existing_transition = self._transitions_by_source.get(transition.source_snapshot_id)
            if existing_transition is not None and existing_transition != transition:
                raise ChipStateContractError("multiple transitions leave the same source snapshot")
            self._transitions_by_source[transition.source_snapshot_id] = transition

    @property
    def cached_result_count(self) -> int:
        return len(self._result_cache)

    @property
    def trace_cache_count(self) -> int:
        return sum(len(cache) for cache in self._trace_caches.values())

    def __call__(
        self,
        anchor: LifecycleAnchor,
        observation: LifecycleObservation,
    ) -> AnchorRetentionEstimate | None:
        current_date = observation.decision_at.date()
        if current_date < anchor.created_at:
            raise ChipStateContractError("observation predates lifecycle anchor")

        contract = (
            anchor.symbol,
            anchor.created_at,
            anchor.lower,
            anchor.upper,
        )
        if anchor.symbol != observation.symbol:
            raise ChipStateContractError("lifecycle anchor symbol does not match observation")
        existing_contract = self._anchor_contracts.get(anchor.root_anchor_id)
        if existing_contract is not None and existing_contract != contract:
            raise ChipStateContractError(
                "root anchor identity was reused with different frozen bounds"
            )
        self._anchor_contracts[anchor.root_anchor_id] = contract

        result_key = (
            anchor.root_anchor_id,
            observation.symbol,
            current_date,
            self.ensemble_version,
        )
        cached_result = self._result_cache.get(result_key)
        if cached_result is not None:
            return cached_result

        tracers: dict[SellerModel, OriginTracer] = {}
        for seller_model in SELLER_MODEL_ORDER:
            anchor_snapshot = self._snapshots_by_key.get(
                (observation.symbol, anchor.created_at, seller_model)
            )
            current_snapshot = self._snapshots_by_key.get(
                (observation.symbol, current_date, seller_model)
            )
            if anchor_snapshot is None or current_snapshot is None:
                return None
            if (
                anchor_snapshot.available_at > observation.decision_at
                or current_snapshot.available_at > observation.decision_at
            ):
                return None
            if (
                anchor_snapshot.model_version != current_snapshot.model_version
                or anchor_snapshot.grid_version != current_snapshot.grid_version
            ):
                return None

            price_tolerance = tolerance(max(abs(anchor.lower), abs(anchor.upper)))
            selected_cell_ids = tuple(
                sorted(
                    cell.cell_id
                    for cell in anchor_snapshot.inventory.cells
                    if cell.cost_known
                    and cell.shares > 0
                    and cell.economic_break_even is not None
                    and anchor.lower - price_tolerance
                    <= cell.economic_break_even
                    <= anchor.upper + price_tolerance
                )
            )
            if not selected_cell_ids:
                return None
            tracer = OriginTracer.from_snapshot(
                anchor_id=anchor.root_anchor_id,
                snapshot=anchor_snapshot,
                selected_cell_ids=selected_cell_ids,
            )
            chain = self._transition_chain(
                anchor_snapshot=anchor_snapshot,
                current_snapshot=current_snapshot,
                observation=observation,
            )
            if chain is None:
                return None
            trace_cache = self._trace_caches.setdefault(
                (anchor.root_anchor_id, seller_model), AnchorTraceCache()
            )
            advanced = trace_to_date(
                tracer,
                chain,
                current_date=current_date,
                cache=trace_cache,
            )
            if advanced.current_snapshot_id != current_snapshot.snapshot_id:
                return None
            tracers[seller_model] = advanced

        estimate = AnchorRetentionEstimate.from_tracers(
            tracers,
            current_date=current_date,
            ensemble_version=self.ensemble_version,
        )
        self._result_cache[result_key] = estimate
        return estimate

    def _transition_chain(
        self,
        *,
        anchor_snapshot: ChipSnapshotV2,
        current_snapshot: ChipSnapshotV2,
        observation: LifecycleObservation,
    ) -> tuple[OriginSurvivalTransition, ...] | None:
        if anchor_snapshot.snapshot_id == current_snapshot.snapshot_id:
            return ()
        chain: list[OriginSurvivalTransition] = []
        seen: set[str] = set()
        cursor = anchor_snapshot
        while cursor.snapshot_id != current_snapshot.snapshot_id:
            if cursor.snapshot_id in seen:
                raise ChipStateContractError("cycle in chip transition chain")
            seen.add(cursor.snapshot_id)
            transition = self._transitions_by_source.get(cursor.snapshot_id)
            if transition is None:
                return None
            if (
                transition.symbol != anchor_snapshot.symbol
                or transition.model_version != anchor_snapshot.model_version
                or transition.grid_version != anchor_snapshot.grid_version
                or transition.available_at > observation.decision_at
                or transition.trading_date > current_snapshot.trading_date
            ):
                return None
            destination = self._snapshots_by_id.get(transition.destination_snapshot_id)
            if destination is None:
                return None
            if (
                destination.symbol != anchor_snapshot.symbol
                or destination.seller_model != anchor_snapshot.seller_model
                or destination.model_version != anchor_snapshot.model_version
                or destination.grid_version != anchor_snapshot.grid_version
                or destination.available_at > observation.decision_at
            ):
                return None
            chain.append(transition)
            cursor = destination
        return tuple(chain)


class PersistedChipLineageResolver:
    """Trace anchor bloodlines directly from the compact daily operator log."""

    def __init__(
        self,
        root: str | Path,
        *,
        ensemble_version: str = "chip-lineage-operator-v8",
    ) -> None:
        self.root = Path(root)
        self.ensemble_version = ensemble_version
        self._symbol_rows: dict[str, dict[SellerModel, dict[date, dict[str, Any]]]] = {}
        self._loaded_symbol_paths: dict[str, set[Path]] = {}
        self._anchor_contracts: dict[str, tuple[str, date, float, float]] = {}
        self._result_cache: dict[tuple[str, str, date, str], AnchorRetentionEstimate] = {}
        self._trace_state_cache: dict[
            tuple[str, SellerModel], _IncrementalTraceState
        ] = {}
        self._operator_step_cache: dict[
            tuple[str, SellerModel, date, date], _CachedOperatorStep
        ] = {}

    @property
    def cached_result_count(self) -> int:
        return len(self._result_cache)

    @property
    def loaded_symbol_count(self) -> int:
        return len(self._symbol_rows)

    @property
    def cached_operator_step_count(self) -> int:
        return len(self._operator_step_cache)

    def release_symbol(self, symbol: str) -> None:
        """Release replay state after a canonical scan has left ``symbol``.

        Signal and lattice scans are strictly ordered by symbol/date, so a
        completed symbol can never be requested again in that scan.  Keeping
        its decoded operator rows and anchor traces only increases memory and
        can force the operating system to swap without changing any result.
        """

        anchor_ids = {
            anchor_id
            for anchor_id, contract in self._anchor_contracts.items()
            if contract[0] == symbol
        }
        self._symbol_rows.pop(symbol, None)
        self._loaded_symbol_paths.pop(symbol, None)
        self._anchor_contracts = {
            anchor_id: contract
            for anchor_id, contract in self._anchor_contracts.items()
            if anchor_id not in anchor_ids
        }
        self._result_cache = {
            key: estimate
            for key, estimate in self._result_cache.items()
            if key[1] != symbol
        }
        self._trace_state_cache = {
            key: state
            for key, state in self._trace_state_cache.items()
            if key[0] not in anchor_ids
        }
        self._operator_step_cache = {
            key: step
            for key, step in self._operator_step_cache.items()
            if key[0] != symbol
        }

    def __call__(
        self,
        anchor: LifecycleAnchor,
        observation: LifecycleObservation,
    ) -> AnchorRetentionEstimate | None:
        current_date = observation.decision_at.date()
        if current_date < anchor.created_at:
            raise ChipStateContractError("observation predates lifecycle anchor")
        if anchor.symbol != observation.symbol:
            raise ChipStateContractError("lifecycle anchor symbol does not match observation")
        contract = (anchor.symbol, anchor.created_at, anchor.lower, anchor.upper)
        existing = self._anchor_contracts.get(anchor.root_anchor_id)
        if existing is not None and existing != contract:
            raise ChipStateContractError(
                "root anchor identity was reused with different frozen bounds"
            )
        self._anchor_contracts[anchor.root_anchor_id] = contract

        cache_key = (
            anchor.root_anchor_id,
            anchor.symbol,
            current_date,
            self.ensemble_version,
        )
        cached = self._result_cache.get(cache_key)
        if cached is not None:
            return cached

        rows_by_model = self._load_symbol(anchor.symbol, anchor.created_at, current_date)
        if rows_by_model is None:
            return None
        model_retentions: dict[SellerModel, float] = {}
        for model in SELLER_MODEL_ORDER:
            rows = rows_by_model.get(model)
            if not rows:
                return None
            retention = self._trace_model(
                rows=rows,
                anchor=anchor,
                current_date=current_date,
                decision_at=observation.decision_at,
                cache_key=(anchor.root_anchor_id, model),
            )
            if retention is None:
                return None
            model_retentions[model] = retention

        estimate = AnchorRetentionEstimate.from_model_retentions(
            anchor_id=anchor.root_anchor_id,
            symbol=anchor.symbol,
            anchor_date=anchor.created_at,
            current_date=current_date,
            model_retentions=cast(
                Mapping[SellerModel | str, float], model_retentions
            ),
            ensemble_version=self.ensemble_version,
        )
        self._result_cache[cache_key] = estimate
        return estimate

    def iter_daily_bucket_mass(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> Iterable[PersistedDailyBucketMass]:
        """Replay each model once and expose the causal economic-cost inventory."""

        rows_by_model = self._load_symbol(symbol, start, end)
        if rows_by_model is None:
            return
        for model in SELLER_MODEL_ORDER:
            rows = rows_by_model.get(model) or {}
            checkpoint_dates = [
                day for day, row in rows.items() if day <= start and row["checkpoint_local_ids"]
            ]
            if not checkpoint_dates:
                checkpoint_dates = [
                    day
                    for day, row in rows.items()
                    if start <= day <= end and row["checkpoint_local_ids"]
                ]
            if not checkpoint_dates:
                continue
            checkpoint_date = (
                max(day for day in checkpoint_dates if day <= start)
                if any(day <= start for day in checkpoint_dates)
                else min(checkpoint_dates)
            )
            checkpoint = rows[checkpoint_date]
            ids = tuple(int(value) for value in checkpoint["checkpoint_local_ids"])
            shares = tuple(float(value) for value in checkpoint["checkpoint_shares"])
            raw_economic = checkpoint.get("checkpoint_economic_bucket_ids")
            if raw_economic is None:
                raw_economic = [_unpack_local_id(value)[0] for value in ids]
            if len(ids) != len(shares) or len(ids) != len(raw_economic):
                raise ChipStateContractError("checkpoint inventory columns differ in length")
            inventory = dict(zip(ids, shares, strict=True))
            economic = {
                local_id: None if bucket is None else int(bucket)
                for local_id, bucket in zip(ids, raw_economic, strict=True)
            }
            for day in sorted(day for day in rows if checkpoint_date <= day <= end):
                row = rows[day]
                if day != checkpoint_date:
                    inventory, _, economic = self._advance(inventory, None, economic, row)
                if day < start:
                    continue
                by_bucket: dict[int, list[float]] = {}
                unknown_parts: list[float] = []
                for local_id, mass in inventory.items():
                    bucket = economic.get(local_id)
                    if bucket is None:
                        unknown_parts.append(mass)
                    else:
                        by_bucket.setdefault(bucket, []).append(mass)
                bucket_mass = tuple(
                    (bucket, math.fsum(parts)) for bucket, parts in sorted(by_bucket.items())
                )
                # A fully UNKNOWN_COST inventory has no economic-cost feature yet.
                # Keep it in the operator log, but do not expose a fabricated cost row.
                if not bucket_mass:
                    continue
                yield PersistedDailyBucketMass(
                    symbol=symbol,
                    trade_date=day,
                    seller_model=model,
                    snapshot_id=str(row["snapshot_id"]),
                    available_at=row["available_at"],
                    free_float_shares=float(row["free_float_shares"]),
                    bucket_mass=bucket_mass,
                    unknown_mass=math.fsum(unknown_parts),
                    research_valid=bool(row.get("research_valid", row["hard_valid"])),
                    average_cost=float(row["average_cost"]),
                    cost_p10=float(row["cost_p10"]),
                    cost_p50=float(row["cost_p50"]),
                    cost_p90=float(row["cost_p90"]),
                    cash_dividend_per_share=float(
                        row.get("cash_dividend_per_share") or 0.0
                    ),
                    share_multiplier=float(row.get("share_multiplier") or 1.0),
                    action_provenance=tuple(
                        str(value)
                        for value in (row.get("action_provenance_ids") or ())
                        if str(value)
                    ),
                )

    def _paths(self, symbol: str, start: date, end: date) -> tuple[Path, ...]:
        filename = f"{symbol.replace('.', '_')}.parquet"
        paths = set(self.root.glob(f"parts/bucket=*/{filename}"))
        for year in range(start.year, end.year + 1):
            paths.update(self.root.glob(f"year={year}/parts/bucket=*/{filename}"))
        if self.root.is_file() and self.root.name == filename:
            paths.add(self.root)
        return tuple(sorted(paths))

    def _load_symbol(
        self, symbol: str, start: date, end: date
    ) -> dict[SellerModel, dict[date, dict[str, Any]]] | None:
        paths = self._paths(symbol, start, end)
        result = self._symbol_rows.get(symbol)
        if result is None and not paths:
            return None
        if result is None:
            result = {model: {} for model in SELLER_MODEL_ORDER}
            self._symbol_rows[symbol] = result
        loaded_paths = self._loaded_symbol_paths.setdefault(symbol, set())
        for path in (path for path in paths if path not in loaded_paths):
            for row in pq.read_table(path).to_pylist():
                if row["storage_version"] not in _COMPATIBLE_OPERATOR_STORAGE_VERSIONS:
                    raise ChipStateContractError(f"unsupported chip operator storage in {path}")
                if row["symbol"] != symbol:
                    raise ChipStateContractError(f"symbol mismatch in {path}")
                model = SellerModel(row["seller_model"])
                trade_date = row["trade_date"]
                previous = result[model].get(trade_date)
                if previous is not None and previous != row:
                    raise ChipStateContractError(
                        "conflicting persisted chip rows for symbol/date/model"
                    )
                result[model][trade_date] = row
            loaded_paths.add(path)
        return result

    def _trace_model(
        self,
        *,
        rows: dict[date, dict[str, Any]],
        anchor: LifecycleAnchor,
        current_date: date,
        decision_at: Any,
        cache_key: tuple[str, SellerModel],
    ) -> float | None:
        if anchor.created_at not in rows or current_date not in rows:
            return None
        cached_state = self._trace_state_cache.get(cache_key)
        if cached_state is not None and cached_state.current_date <= current_date:
            inventory = cached_state.inventory
            lineage = cached_state.lineage
            economic_buckets = cached_state.economic_buckets
            for day in sorted(
                day for day in rows if cached_state.current_date < day <= current_date
            ):
                row = rows[day]
                if row["available_at"] > decision_at:
                    return None
                inventory, lineage, economic_buckets = self._advance_trace(
                    inventory,
                    lineage,
                    economic_buckets,
                    row,
                    symbol=anchor.symbol,
                    model=cache_key[1],
                    checkpoint_date=cached_state.checkpoint_date,
                    trade_date=day,
                )
            cached_state.current_date = current_date
            cached_state.inventory = inventory
            cached_state.lineage = lineage
            cached_state.economic_buckets = economic_buckets
            retained_mass = math.fsum(lineage.values())
            return min(1.0, max(0.0, retained_mass / cached_state.anchor_mass))
        checkpoint_dates = [
            day
            for day, row in rows.items()
            if day <= anchor.created_at and row["checkpoint_local_ids"]
        ]
        if not checkpoint_dates:
            return None
        checkpoint_date = max(checkpoint_dates)
        ordered_dates = sorted(day for day in rows if checkpoint_date <= day <= current_date)
        checkpoint = rows[checkpoint_date]
        if checkpoint["available_at"] > decision_at:
            return None
        checkpoint_ids = tuple(int(value) for value in checkpoint["checkpoint_local_ids"])
        checkpoint_shares = tuple(float(value) for value in checkpoint["checkpoint_shares"])
        if len(checkpoint_ids) != len(checkpoint_shares):
            raise ChipStateContractError("checkpoint cell/share lengths differ")
        inventory = dict(zip(checkpoint_ids, checkpoint_shares, strict=True))
        raw_checkpoint_economic = checkpoint.get("checkpoint_economic_bucket_ids")
        if raw_checkpoint_economic is None:
            raw_checkpoint_economic = [_unpack_local_id(value)[0] for value in checkpoint_ids]
        if len(raw_checkpoint_economic) != len(checkpoint_ids):
            raise ChipStateContractError("checkpoint economic bucket lengths differ")
        economic_buckets = {
            local_id: None if bucket is None else int(bucket)
            for local_id, bucket in zip(
                checkpoint_ids, raw_checkpoint_economic, strict=True
            )
        }

        for day in ordered_dates:
            if day == checkpoint_date:
                continue
            if day > anchor.created_at:
                break
            row = rows[day]
            if row["available_at"] > decision_at:
                return None
            inventory, _, economic_buckets = self._advance_trace(
                inventory,
                None,
                economic_buckets,
                row,
                symbol=anchor.symbol,
                model=cache_key[1],
                checkpoint_date=checkpoint_date,
                trade_date=day,
            )
        anchor_inventory = inventory
        price_tolerance = tolerance(max(abs(anchor.lower), abs(anchor.upper)))
        lineage = {
            local_id: shares
            for local_id, shares in anchor_inventory.items()
            if shares > 0
            and (cost_bucket := economic_buckets.get(local_id)) is not None
            and anchor.lower - price_tolerance
            <= economic_break_even_for_bucket(_OPERATOR_GRID, cost_bucket)
            <= anchor.upper + price_tolerance
        }
        anchor_mass = math.fsum(lineage.values())
        if anchor_mass <= tolerance(float(rows[anchor.created_at]["free_float_shares"])):
            return None

        inventory = anchor_inventory
        for day in ordered_dates:
            if day <= anchor.created_at:
                continue
            row = rows[day]
            inventory, lineage, economic_buckets = self._advance_trace(
                inventory,
                lineage,
                economic_buckets,
                row,
                symbol=anchor.symbol,
                model=cache_key[1],
                checkpoint_date=checkpoint_date,
                trade_date=day,
            )
        self._trace_state_cache[cache_key] = _IncrementalTraceState(
            checkpoint_date=checkpoint_date,
            current_date=current_date,
            inventory=inventory,
            lineage=lineage,
            economic_buckets=economic_buckets,
            anchor_mass=anchor_mass,
        )
        retained_mass = math.fsum(lineage.values())
        value = retained_mass / anchor_mass
        if not -1e-12 <= value <= 1.0 + 1e-12:
            raise ChipStateContractError("persisted anchor retention outside [0, 1]")
        return min(1.0, max(0.0, value))

    def _advance_trace(
        self,
        inventory: dict[int, float],
        lineage: dict[int, float] | None,
        economic_buckets: dict[int, int | None],
        row: dict[str, Any],
        *,
        symbol: str,
        model: SellerModel,
        checkpoint_date: date,
        trade_date: date,
    ) -> tuple[dict[int, float], dict[int, float], dict[int, int | None]]:
        key = (symbol, model, checkpoint_date, trade_date)
        cached = self._operator_step_cache.get(key)
        if cached is not None:
            return (
                cached.next_inventory,
                _apply_lineage_operator(lineage, cached.lineage_operator),
                cached.next_economic_buckets,
            )
        operator = _lineage_operator(inventory, row)
        next_inventory, next_lineage, next_economic = self._advance(
            inventory,
            lineage,
            economic_buckets,
            row,
            lineage_operator=operator,
        )
        self._operator_step_cache[key] = _CachedOperatorStep(
            next_inventory=next_inventory,
            next_economic_buckets=next_economic,
            lineage_operator=operator,
        )
        return next_inventory, next_lineage, next_economic

    @staticmethod
    def _advance(
        inventory: dict[int, float],
        lineage: dict[int, float] | None,
        economic_buckets: dict[int, int | None],
        row: dict[str, Any],
        *,
        lineage_operator: Sequence[tuple[int, int, float]] | None = None,
    ) -> tuple[dict[int, float], dict[int, float], dict[int, int | None]]:
        cash_dividend = float(row.get("cash_dividend_per_share") or 0.0)
        share_multiplier = float(row.get("share_multiplier") or 1.0)
        if share_multiplier <= 0:
            raise ChipStateContractError("share multiplier must be positive")
        adjusts_economic_cost = cash_dividend != 0.0 or share_multiplier != 1.0

        def adjusted_economic_bucket(local_id: int) -> int | None:
            bucket = economic_buckets.get(local_id)
            if bucket is None:
                return None
            if not adjusts_economic_cost:
                return bucket
            adjusted_price = (
                economic_break_even_for_bucket(_OPERATOR_GRID, bucket) - cash_dividend
            ) / share_multiplier
            return bucket_for_economic_break_even(_OPERATOR_GRID, adjusted_price)

        operator = (
            lineage_operator
            if lineage_operator is not None
            else _lineage_operator(inventory, row)
        )
        next_inventory: dict[int, float] = {}
        inventory_collisions: dict[int, list[float]] = {}
        next_lineage: dict[int, float] = {}
        lineage_collisions: dict[int, list[float]] = {}
        next_economic_parts: dict[
            int,
            tuple[float, int | None] | list[tuple[float, int | None]],
        ] = {}
        for source, destination, retained in operator:
            if source not in inventory:
                raise ChipStateContractError("operator source is missing from inventory")
            retained_inventory = inventory[source] * retained
            if retained_inventory <= 0.0:
                continue
            previous_inventory = next_inventory.get(destination)
            if previous_inventory is None:
                next_inventory[destination] = retained_inventory
            else:
                collision = inventory_collisions.get(destination)
                if collision is None:
                    inventory_collisions[destination] = [
                        previous_inventory,
                        retained_inventory,
                    ]
                else:
                    collision.append(retained_inventory)
            economic_part = (retained_inventory, adjusted_economic_bucket(source))
            previous_economic = next_economic_parts.get(destination)
            if previous_economic is None:
                next_economic_parts[destination] = economic_part
            elif isinstance(previous_economic, tuple):
                next_economic_parts[destination] = [previous_economic, economic_part]
            else:
                previous_economic.append(economic_part)
            if lineage is not None and source in lineage:
                retained_lineage = lineage[source] * retained
                if retained_lineage > 0.0:
                    previous_lineage = next_lineage.get(destination)
                    if previous_lineage is None:
                        next_lineage[destination] = retained_lineage
                    else:
                        collision = lineage_collisions.get(destination)
                        if collision is None:
                            lineage_collisions[destination] = [
                                previous_lineage,
                                retained_lineage,
                            ]
                        else:
                            collision.append(retained_lineage)
        for local_id, parts in inventory_collisions.items():
            next_inventory[local_id] = math.fsum(parts)
        for local_id, parts in lineage_collisions.items():
            next_lineage[local_id] = math.fsum(parts)
        for local_id, adjustment in zip(
            row.get("inventory_adjustment_local_ids") or (),
            row.get("inventory_adjustment_shares") or (),
            strict=True,
        ):
            local_id = int(local_id)
            next_inventory[local_id] = next_inventory.get(local_id, 0.0) + float(adjustment)
        adjustment_ids = tuple(
            int(value) for value in (row.get("inventory_adjustment_local_ids") or ())
        )
        raw_adjustment_economic = row.get("inventory_adjustment_economic_bucket_ids")
        if raw_adjustment_economic is None:
            raw_adjustment_economic = [_unpack_local_id(value)[0] for value in adjustment_ids]
        if len(raw_adjustment_economic) != len(adjustment_ids):
            raise ChipStateContractError("adjustment economic bucket lengths differ")
        expected_mass = float(row["free_float_shares"])
        mass_tolerance = tolerance(expected_mass)
        cleaned: dict[int, float] = {}
        for local_id, shares in next_inventory.items():
            if shares < -mass_tolerance:
                raise ChipStateContractError("operator produced negative inventory")
            # Small positive cells are real inventory.  Dropping each cell at the
            # aggregate mass tolerance changes the source count expected by the
            # next persisted operator and accumulates a replay mass deficit.
            if shares > 0.0:
                cleaned[local_id] = shares
        actual_mass = math.fsum(cleaned.values())
        if abs(actual_mass - expected_mass) > mass_tolerance:
            raise ChipStateContractError(
                f"persisted operator does not conserve mass: {actual_mass} != {expected_mass}"
            )
        next_economic: dict[int, int | None] = {}
        for local_id in cleaned:
            raw_economic_parts = next_economic_parts.get(local_id)
            if isinstance(raw_economic_parts, tuple):
                next_economic[local_id] = raw_economic_parts[1]
                continue
            economic_parts = raw_economic_parts or []
            known_parts = [
                (shares, bucket)
                for shares, bucket in economic_parts
                if bucket is not None
            ]
            unknown_mass = math.fsum(
                shares for shares, bucket in economic_parts if bucket is None
            )
            if unknown_mass > 0 or not known_parts:
                next_economic[local_id] = None
                continue
            total_known = math.fsum(shares for shares, _ in known_parts)
            price = math.fsum(
                shares
                * economic_break_even_for_bucket(_OPERATOR_GRID, int(bucket))
                for shares, bucket in known_parts
            ) / total_known
            next_economic[local_id] = bucket_for_economic_break_even(
                _OPERATOR_GRID, price
            )
        for local_id, adjustment, bucket in zip(
            adjustment_ids,
            (row.get("inventory_adjustment_shares") or ()),
            raw_adjustment_economic,
            strict=True,
        ):
            if float(adjustment) > 0 and local_id in cleaned:
                next_economic[local_id] = None if bucket is None else int(bucket)
        return cleaned, next_lineage, next_economic
