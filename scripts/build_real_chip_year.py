#!/usr/bin/env python3
"""Build one year of reusable real 1-minute chip inventory, in parallel buckets."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import shutil
import struct
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from datetime import time as clock_time
from itertools import pairwise
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cyq_game.chip._migration_kernel import stable_sum  # noqa: E402
from cyq_game.chip.daily_feature_fact import build_daily_feature_fact  # noqa: E402
from cyq_game.chip.ensemble_v2 import SELLER_MODEL_ORDER  # noqa: E402
from cyq_game.chip.migration_v2 import (  # noqa: E402
    DEFAULT_MAX_HOLDING_DAYS,
    NONPOSITIVE_ECONOMIC_BUCKET,
    DailyMigrationEngine,
    InventoryEvent,
    InventoryEventKind,
    MinuteBar,
    MutableChipState,
    PreparedMinutePath,
    StableLogPriceGrid,
    bucket_for_economic_break_even,
    economic_break_even_for_bucket,
    initial_unknown_snapshot,
    prepare_minute_path,
)
from cyq_game.chip.operator_index import build_operator_symbol_index  # noqa: E402
from cyq_game.chip.peaks import (  # noqa: E402
    detect_canonical_peaks,
    dominant_canonical_peak,
)
from cyq_game.chip.profile_metrics import compute_distribution_metrics  # noqa: E402
from cyq_game.chip.price_coordinate import (  # noqa: E402
    canonical_action_component_id,
    parse_action_ids,
)
from cyq_game.chip.state_v2 import (  # noqa: E402
    ChipSnapshotV2,
    InventoryCell,
    SellerModel,
    SnapshotPhase,
    SparseChipInventory,
    TurnoverSensitivity,
    stable_cell_id,
    tolerance,
)
from cyq_game.strategy.semantic_contract import (  # noqa: E402
    CHIP_STATE_SCHEMA_VERSION,
    OPERATOR_LOG_VERSION,
    semantic_fingerprint_fields,
)

DAILY_ROOT = ROOT / "data/processed/pit_b_daily_2018_2026_v2/daily"
MINUTE_ROOT = Path(
    "/Users/linmei/Downloads/workspace/quant/data/lake/"
    "stock_1min_canonical_none_20260813/bars"
)
MODEL_VERSION = "real-chip-inventory-v2.1"
GRID_VERSION = "log-grid-25bp-v1"
STORAGE_VERSION = OPERATOR_LOG_VERSION
STAGE_LAYOUT_VERSION = "bucket-symbol-v3-mixed-native-resolution"
MINUTE_YEAR_SUPPLEMENTS: dict[int, tuple[str, ...]] = {
    2026: ("2026_qmt_tail.parquet",),
}
CHECKPOINT_INTERVAL_DAYS = 20
OUTPUT_ROW_GROUP_SIZE = 4096
PARQUET_COMPRESSION_LEVEL = 3
RETENTION_RAW = 0
RETENTION_CONSTANT = 1
RETENTION_PALETTE_U8 = 2
RETENTION_BY_SENSITIVITY = 3
RETENTION_XOR = 4
RETENTION_XOR_BYTE_SHUFFLE = 5
# Seller retention is fully determined by the previous checkpoint, registered
# minute bars and seller-model version.  Persisting thousands of fractions per
# day duplicates source data, so every transition uses deterministic replay.
# This marker must never be interpreted as an empty/all-retained vector.
RETENTION_SOURCE_REPLAY = 6
RETENTION_PALETTE_BITPACK = 7

SENSITIVITY_CODE = {
    TurnoverSensitivity.ACTIVE: 0,
    TurnoverSensitivity.NEUTRAL: 1,
    TurnoverSensitivity.STICKY: 2,
}
TZ = ZoneInfo("Asia/Shanghai")


def _aware(day: date, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime.combine(day, clock_time(hour, minute, second), tzinfo=TZ)


def _date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _timestamp(value: datetime) -> datetime:
    return value.replace(tzinfo=TZ) if value.tzinfo is None else value.astimezone(TZ)


def _snapshot_ids(row: dict[str, Any]) -> tuple[str, ...]:
    values = {
        str(row[key])
        for key in (
            "snapshot_id",
            "daily_snapshot_id",
            "float_snapshot_id",
            "corporate_action_snapshot_id",
        )
        if row.get(key)
    }
    values.add(f"daily-row:{row['symbol']}:{_date(row['trade_date']).isoformat()}")
    return tuple(sorted(values))


def _minute_bars(rows: list[dict[str, Any]], trading_date: date) -> tuple[MinuteBar, ...]:
    bars: list[MinuteBar] = []
    # Convert each timestamp once.  The previous implementation converted it
    # twice while checking order and then a third time while building the bar.
    timed_rows = [(_timestamp(row["bar_end_time"]), row) for row in rows]
    if any(
        current[0] <= previous[0]
        for previous, current in pairwise(timed_rows)
    ):
        timed_rows.sort(key=lambda item: item[0])
    for _, row in timed_rows:
        values = tuple(float(row[key]) for key in ("open", "high", "low", "close"))
        open_price, high, low, close = values
        volume = float(row["volume"])
        amount = float(row["amount"])
        if (
            any(not math.isfinite(value) or value <= 0 for value in values)
            or high < max(open_price, close)
            or low > min(open_price, close)
            or low > high
            or not math.isfinite(volume)
            or volume < 0
            or not math.isfinite(amount)
            or amount < 0
            or (volume > 0 and amount <= 0)
        ):
            # Reject the whole intraday path instead of silently dropping a bad
            # bar and breaking daily volume conservation.  The caller will use
            # its explicit daily fallback (or carry state on a zero-volume day).
            return ()
    for timestamp, row in timed_rows:
        if _date(row["trade_date"]) != trading_date:
            continue
        volume = float(row["volume"])
        amount = float(row["amount"])
        low = float(row["low"])
        high = float(row["high"])
        vwap = amount / volume if volume > 0 and amount > 0 else None
        if vwap is not None:
            # QMT stores amount, volume and OHLC at different precisions.  A
            # rounded amount/volume can therefore sit just outside the minute
            # range.  Keep the observed turnover information at the nearest
            # physically possible price instead of discarding it and falling
            # back to OHLC4.
            vwap = min(max(vwap, low), high)
        bars.append(
            MinuteBar(
                timestamp=timestamp,
                available_at=timestamp,
                snapshot_id=(
                    f"{row.get('minute_source', 'qmt-none-1m')}:"
                    f"{row['symbol']}:{timestamp.isoformat()}"
                ),
                open=float(row["open"]),
                high=high,
                low=low,
                close=float(row["close"]),
                volume_shares=volume,
                vwap=vwap,
            )
        )
    return tuple(bars)


def _event_available(value: Any, effective_at: datetime) -> datetime:
    available = _aware(_date(value), 0)
    if available > effective_at:
        raise ValueError("inventory event is not PIT-available")
    return available


def _pro_rata_removals(
    snapshot: ChipSnapshotV2 | MutableChipState, share_ratio: float, shares: float
) -> tuple[tuple[int, float], ...]:
    candidates = sorted(
        (cell.cell_id, cell.shares * share_ratio)
        for cell in snapshot.inventory.cells
        if cell.shares > 0
    )
    total = math.fsum(value for _, value in candidates)
    remaining = shares
    result: list[tuple[int, float]] = []
    for index, (cell_id, available) in enumerate(candidates):
        amount = remaining if index == len(candidates) - 1 else shares * available / total
        amount = min(amount, available)
        if amount > 0:
            result.append((cell_id, amount))
            remaining -= amount
    if abs(remaining) > tolerance(shares):
        raise ValueError("could not allocate explicit float removal")
    return tuple(result)


def _inventory_events(
    previous: ChipSnapshotV2 | MutableChipState, row: dict[str, Any]
) -> tuple[InventoryEvent, ...]:
    trading_date = _date(row["trade_date"])
    action_available = _event_available(
        row["corporate_action_available_date"], _aware(trading_date, 9)
    )
    float_available = _event_available(
        row["float_available_date"], _aware(trading_date, 9, 0, 2)
    )
    input_id = str(row.get("corporate_action_snapshot_id") or row["snapshot_id"])
    source_action_ids = parse_action_ids(row.get("corporate_action_ids"))
    events: list[InventoryEvent] = []
    cash = float(row.get("cash_per_share") or 0.0)
    ratio = float(row.get("share_multiplier") or 1.0)
    if cash > 0:
        events.append(
            InventoryEvent(
                event_id=canonical_action_component_id(
                    symbol=previous.symbol,
                    effective_date=trading_date,
                    kind="CASH_DIVIDEND",
                    source_action_ids=source_action_ids,
                    snapshot_id=input_id,
                    cash_per_share=cash,
                ),
                kind=InventoryEventKind.CASH_DIVIDEND,
                effective_at=_aware(trading_date, 9),
                available_at=action_available,
                snapshot_id=input_id,
                cash_per_share=cash,
            )
        )
    if ratio != 1.0:
        events.append(
            InventoryEvent(
                event_id=canonical_action_component_id(
                    symbol=previous.symbol,
                    effective_date=trading_date,
                    kind="SPLIT",
                    source_action_ids=source_action_ids,
                    snapshot_id=input_id,
                    share_multiplier=ratio,
                ),
                kind=InventoryEventKind.SPLIT,
                effective_at=_aware(trading_date, 9, 0, 1),
                available_at=action_available,
                snapshot_id=input_id,
                share_ratio=ratio,
            )
        )
    expected_float = float(row["circulating_shares"])
    bridged_float = previous.free_float_shares * ratio
    delta = expected_float - bridged_float
    float_snapshot_id = str(row.get("float_snapshot_id") or row["snapshot_id"])
    if delta > tolerance(expected_float):
        events.append(
            InventoryEvent(
                event_id=canonical_action_component_id(
                    symbol=previous.symbol,
                    effective_date=trading_date,
                    kind="FLOAT_ADD_UNKNOWN",
                    source_action_ids=(),
                    snapshot_id=float_snapshot_id,
                    shares=delta,
                ),
                kind=InventoryEventKind.FLOAT_ADD_UNKNOWN,
                effective_at=_aware(trading_date, 9, 0, 2),
                available_at=float_available,
                snapshot_id=float_snapshot_id,
                shares=delta,
                sensitivity=TurnoverSensitivity.NEUTRAL,
            )
        )
    elif delta < -tolerance(expected_float):
        removed = -delta
        events.append(
            InventoryEvent(
                event_id=canonical_action_component_id(
                    symbol=previous.symbol,
                    effective_date=trading_date,
                    kind="FLOAT_REMOVE_EXPLICIT",
                    source_action_ids=(),
                    snapshot_id=float_snapshot_id,
                    shares=removed,
                ),
                kind=InventoryEventKind.FLOAT_REMOVE_EXPLICIT,
                effective_at=_aware(trading_date, 9, 0, 2),
                available_at=float_available,
                snapshot_id=float_snapshot_id,
                shares=removed,
                source_removals=_pro_rata_removals(previous, ratio, removed),
            )
        )
    return tuple(events)


OUTPUT_SCHEMA = pa.schema(
    [
        ("storage_version", pa.string()),
        ("model_version", pa.string()),
        ("symbol", pa.string()),
        ("trade_date", pa.date32()),
        ("seller_model", pa.string()),
        ("snapshot_id", pa.string()),
        ("decision_at", pa.timestamp("us", tz="Asia/Shanghai")),
        ("available_at", pa.timestamp("us", tz="Asia/Shanghai")),
        # The complete input id list is already committed into snapshot_id.  A
        # fixed digest keeps independently verifiable provenance without copying
        # hundreds of strings into every seller-model row.
        ("input_snapshot_digest", pa.binary(32)),
        ("free_float_shares", pa.float64()),
        ("known_cost_fraction", pa.float64()),
        ("unknown_cost_fraction", pa.float64()),
        ("profile_close", pa.float64()),
        ("average_cost", pa.float64()),
        ("cost_p01", pa.float64()),
        ("cost_p10", pa.float64()),
        ("cost_p50", pa.float64()),
        ("cost_p90", pa.float64()),
        ("cost_p99", pa.float64()),
        ("profit_ratio", pa.float64()),
        ("asr", pa.float64()),
        ("cbw", pa.float64()),
        ("concentration_20", pa.float64()),
        ("main_peak", pa.float64()),
        ("dominant_peak_today", pa.float64()),
        ("dominant_band_lower", pa.float64()),
        ("dominant_band_upper", pa.float64()),
        ("dominant_band_mass", pa.float64()),
        ("peak_count", pa.int32()),
        ("model_quality", pa.float64()),
        ("checkpoint_local_ids", pa.list_(pa.uint64())),
        ("checkpoint_shares", pa.list_(pa.float64())),
        ("checkpoint_economic_bucket_ids", pa.list_(pa.int32())),
        ("transition_id", pa.string()),
        ("source_cell_ids_override", pa.list_(pa.uint64())),
        ("destination_override_positions", pa.list_(pa.uint32())),
        ("destination_override_cell_ids", pa.list_(pa.uint64())),
        ("retention_encoding", pa.uint8()),
        ("retention_values", pa.list_(pa.float64())),
        ("retention_codes", pa.binary()),
        ("inventory_adjustment_local_ids", pa.list_(pa.uint64())),
        ("inventory_adjustment_shares", pa.list_(pa.float64())),
        ("inventory_adjustment_economic_bucket_ids", pa.list_(pa.int32())),
        ("cash_dividend_per_share", pa.float64()),
        ("share_multiplier", pa.float64()),
        ("action_provenance_ids", pa.list_(pa.string())),
        ("fixed_pre_eligible_shares", pa.float64()),
        ("executed_sell_shares", pa.float64()),
        ("same_day_resale_shares", pa.float64()),
        ("conservation_error_shares", pa.float64()),
        ("minute_fallback", pa.bool_()),
        ("hard_valid", pa.bool_()),
        ("research_valid", pa.bool_()),
        ("quality_reason_codes", pa.list_(pa.string())),
    ]
)


_RESEARCH_RECOVERABLE_QUALITY_CODES = frozenset(
    {
        "UNKNOWN_COST_INITIALIZATION",
        "UNKNOWN_COST_PRESENT",
        "TURNOVER_CAPPED_AT_FLOAT",
    }
)


def _research_valid(state: MutableChipState) -> bool:
    """Allow explicit pre-history uncertainty in research, never in strict PIT."""

    return all(
        reason in _RESEARCH_RECOVERABLE_QUALITY_CODES
        for reason in state.quality_reason_codes
    )


class _ColumnarOutputBatch:
    """Accumulate Arrow columns directly instead of allocating one dict per row."""

    __slots__ = ("_columns", "_row_count")

    def __init__(self) -> None:
        self._columns: list[list[Any]] = [[] for _ in OUTPUT_SCHEMA]
        self._row_count = 0

    def __len__(self) -> int:
        return self._row_count

    def append(self, values: tuple[Any, ...]) -> None:
        if len(values) != len(self._columns):
            raise ValueError(
                f"output value count {len(values)} != schema field count {len(self._columns)}"
            )
        for column, value in zip(self._columns, values, strict=True):
            column.append(value)
        self._row_count += 1

    def to_table(self) -> pa.Table:
        arrays = [
            pa.array(column, type=schema_field.type)
            for column, schema_field in zip(self._columns, OUTPUT_SCHEMA, strict=True)
        ]
        return pa.Table.from_arrays(arrays, schema=OUTPUT_SCHEMA)

    def clear(self) -> None:
        for column in self._columns:
            column.clear()
        self._row_count = 0

TERMINAL_CELL_TYPE = pa.struct(
    [
        ("cell_id", pa.int64()),
        ("cost_bucket_id", pa.int64()),
        ("holding_days", pa.int16()),
        ("sensitivity", pa.string()),
        ("acquisition_cost", pa.float64()),
        ("economic_break_even", pa.float64()),
        ("shares", pa.float64()),
        ("initialization_prior_units", pa.float64()),
    ]
)

TERMINAL_SCHEMA = pa.schema(
    [
        ("storage_version", pa.string()),
        ("model_version", pa.string()),
        ("grid_version", pa.string()),
        ("symbol", pa.string()),
        ("trading_date", pa.date32()),
        ("decision_at", pa.timestamp("us", tz="Asia/Shanghai")),
        ("effective_at", pa.timestamp("us", tz="Asia/Shanghai")),
        ("available_at", pa.timestamp("us", tz="Asia/Shanghai")),
        ("phase", pa.string()),
        ("snapshot_id", pa.string()),
        ("seller_model", pa.string()),
        ("free_float_shares", pa.float64()),
        ("latent_supply_shares", pa.float64()),
        ("input_snapshot_ids", pa.list_(pa.string())),
        ("pit_grade", pa.string()),
        ("hard_valid", pa.bool_()),
        ("quality_reason_codes", pa.list_(pa.string())),
        ("cells", pa.list_(TERMINAL_CELL_TYPE)),
    ]
)

CELL_SENSITIVITY_BITS = 2
CELL_HOLDING_BITS = 8
CELL_DIMENSION_BITS = CELL_SENSITIVITY_BITS + CELL_HOLDING_BITS
CELL_HOLDING_MASK = (1 << CELL_HOLDING_BITS) - 1
CELL_COST_CODE_MAX = (1 << (32 - CELL_DIMENSION_BITS)) - 1


def _pack_cell_dimensions(
    cost_bucket_id: int | None,
    holding_days: int,
    sensitivity_code: int,
) -> int:
    """Pack immutable cell dimensions into a reversible uint32 id."""

    if not -1 <= holding_days < CELL_HOLDING_MASK:
        raise ValueError(f"holding_days outside packed range: {holding_days}")
    if not 0 <= sensitivity_code < (1 << CELL_SENSITIVITY_BITS):
        raise ValueError(f"sensitivity_code outside packed range: {sensitivity_code}")
    if cost_bucket_id is None:
        cost_code = 0
    else:
        zigzag = 2 * cost_bucket_id if cost_bucket_id >= 0 else -2 * cost_bucket_id - 1
        cost_code = zigzag + 1
    if cost_code > CELL_COST_CODE_MAX:
        raise ValueError(f"cost_bucket_id outside packed range: {cost_bucket_id}")
    holding_code = holding_days + 1
    return (
        (cost_code << CELL_DIMENSION_BITS)
        | (holding_code << CELL_SENSITIVITY_BITS)
        | sensitivity_code
    )


def _unpack_cell_dimensions(packed_id: int) -> tuple[int | None, int, int]:
    """Inverse of :func:`_pack_cell_dimensions`."""

    sensitivity_code = packed_id & ((1 << CELL_SENSITIVITY_BITS) - 1)
    holding_code = (packed_id >> CELL_SENSITIVITY_BITS) & CELL_HOLDING_MASK
    cost_code = packed_id >> CELL_DIMENSION_BITS
    if cost_code == 0:
        cost_bucket_id = None
    else:
        zigzag = cost_code - 1
        cost_bucket_id = zigzag // 2 if zigzag % 2 == 0 else -(zigzag // 2) - 1
    return cost_bucket_id, holding_code - 1, sensitivity_code


@dataclass
class _CellCodec:
    """Map stable hashes to reversible packed dimension ids."""

    by_cell_id: dict[int, int] = field(default_factory=dict)
    normal_destination_by_cell_id: dict[int, int] = field(default_factory=dict)

    def register_snapshot(self, snapshot: ChipSnapshotV2) -> None:
        for cell in snapshot.inventory.cells:
            if cell.cell_id in self.by_cell_id:
                continue
            self.by_cell_id[cell.cell_id] = _pack_cell_dimensions(
                cell.cost_bucket_id,
                cell.holding_days,
                SENSITIVITY_CODE[cell.sensitivity],
            )

    def snapshot_view_and_economic_buckets(
        self, snapshot: ChipSnapshotV2, grid: StableLogPriceGrid
    ) -> tuple[
        dict[int, tuple[int | None, int, TurnoverSensitivity, float]],
        dict[int, int | None],
    ]:
        """Freeze the prior POST state before the mutable engine advances it."""

        self.register_snapshot(snapshot)
        view: dict[int, tuple[int | None, int, TurnoverSensitivity, float]] = {}
        economic: dict[int, int | None] = {}
        for cell in snapshot.inventory.cells:
            view[cell.cell_id] = (
                cell.cost_bucket_id,
                cell.holding_days,
                cell.sensitivity,
                cell.shares,
            )
            economic[cell.cell_id] = (
                None
                if cell.economic_break_even is None
                else bucket_for_economic_break_even(grid, cell.economic_break_even)
            )
        return view, economic

    def local_id(self, cell_id: int) -> int:
        """v12 persists the full causal cell identity, never a lossy local code."""

        return cell_id

    def register_state(
        self, state: MutableChipState, grid: StableLogPriceGrid
    ) -> dict[int, tuple[int | None, int, TurnoverSensitivity, float]]:
        """Register canonical mutable lots and return the lightweight daily view."""

        view, _, _, _ = self.register_state_and_profile(state, grid)
        return view

    def register_state_and_profile(
        self, state: MutableChipState, grid: StableLogPriceGrid
    ) -> tuple[
        dict[int, tuple[int | None, int, TurnoverSensitivity, float]],
        dict[int, float],
        float,
        dict[int, int | None],
    ]:
        """Register lots and aggregate the daily price profile in one pass."""

        view: dict[int, tuple[int | None, int, TurnoverSensitivity, float]] = {}
        by_bucket: dict[int, float] = defaultdict(float)
        economic_bucket_by_cell_id: dict[int, int | None] = {}
        known_shares = 0.0
        packed = state.packed_lots
        if packed is not None:
            sensitivities = (
                TurnoverSensitivity.ACTIVE,
                TurnoverSensitivity.NEUTRAL,
                TurnoverSensitivity.STICKY,
            )
            size = len(packed)
            shares_array = packed._shares[:size]
            active_indices = np.flatnonzero(shares_array > 0)
            cell_ids = packed._cell_ids
            bucket_ids = packed._cost_bucket_ids
            acquisition_costs = packed._acquisition_costs
            economic_break_evens = packed._economic_break_evens
            holding_days_array = packed._holding_days
            sensitivity_codes = packed._sensitivity_codes

            known_indices = active_indices[
                np.isfinite(economic_break_evens[active_indices])
            ]
            if known_indices.size:
                economic_values = economic_break_evens[known_indices]
                economic_buckets = np.full(
                    economic_values.shape,
                    NONPOSITIVE_ECONOMIC_BUCKET,
                    dtype=np.int64,
                )
                positive = economic_values > 0
                economic_buckets[positive] = np.floor(
                    np.log(economic_values[positive] / grid.reference_price)
                    / math.log1p(grid.step_pct)
                    + 0.5
                ).astype(np.int64)
                unique_buckets, inverse = np.unique(
                    economic_buckets, return_inverse=True
                )
                # Keep the vectorized bucket mapping above, but use the same
                # deterministic, order-independent summation contract as the
                # legacy replay when aggregating each bucket's shares.
                order = np.argsort(inverse, kind="stable")
                ordered_inverse = inverse[order]
                ordered_shares = shares_array[known_indices][order]
                boundaries = np.flatnonzero(
                    ordered_inverse[1:] != ordered_inverse[:-1]
                ) + 1
                starts = np.concatenate((np.array([0]), boundaries))
                stops = np.concatenate((boundaries, np.array([order.size])))
                bucket_mass = np.fromiter(
                    (
                        math.fsum(ordered_shares[start:stop].tolist())
                        for start, stop in zip(starts, stops, strict=True)
                    ),
                    dtype=np.float64,
                    count=unique_buckets.size,
                )
                by_bucket = {
                    int(bucket): float(mass)
                    for bucket, mass in zip(unique_buckets, bucket_mass, strict=True)
                }
                known_shares = math.fsum(bucket_mass.tolist())

            for index_value in active_indices:
                index = int(index_value)
                shares = float(shares_array[index])
                cell_id = int(cell_ids[index])
                raw_bucket = int(bucket_ids[index])
                acquisition_cost = float(acquisition_costs[index])
                cost_bucket_id = raw_bucket if math.isfinite(acquisition_cost) else None
                holding_days = int(holding_days_array[index])
                sensitivity = sensitivities[int(sensitivity_codes[index])]
                if cell_id not in self.by_cell_id:
                    self.by_cell_id[cell_id] = _pack_cell_dimensions(
                        cost_bucket_id,
                        holding_days,
                        SENSITIVITY_CODE[sensitivity],
                    )
                view[cell_id] = (
                    cost_bucket_id,
                    holding_days,
                    sensitivity,
                    shares,
                )
                economic_break_even = float(economic_break_evens[index])
                economic_bucket_by_cell_id[cell_id] = (
                    bucket_for_economic_break_even(grid, economic_break_even)
                    if math.isfinite(economic_break_even)
                    else None
                )
            return view, by_bucket, known_shares, economic_bucket_by_cell_id

        if not isinstance(state.lots, list):
            raise TypeError("unexpected chip inventory representation")
        for lot in state.lots:
            if lot.shares <= 0:
                continue
            cell_id = lot.cell_id
            if cell_id not in self.by_cell_id:
                self.by_cell_id[cell_id] = _pack_cell_dimensions(
                    lot.cost_bucket_id,
                    lot.holding_days,
                    SENSITIVITY_CODE[lot.sensitivity],
                )
            view[cell_id] = (
                lot.cost_bucket_id,
                lot.holding_days,
                lot.sensitivity,
                lot.shares,
            )
            if lot.economic_break_even is not None:
                economic_bucket = bucket_for_economic_break_even(
                    grid, lot.economic_break_even
                )
                by_bucket[economic_bucket] += lot.shares
                known_shares += lot.shares
                economic_bucket_by_cell_id[cell_id] = economic_bucket
            else:
                economic_bucket_by_cell_id[cell_id] = None
        return view, by_bucket, known_shares, economic_bucket_by_cell_id

    def normal_destination(
        self,
        cell_id: int,
        cell: tuple[int | None, int, TurnoverSensitivity, float],
        *,
        max_holding_days: int = DEFAULT_MAX_HOLDING_DAYS,
    ) -> int:
        cached = self.normal_destination_by_cell_id.get(cell_id)
        if cached is not None:
            return cached
        cost_bucket_id, holding_days, sensitivity, _ = cell
        aged_holding_days = (
            -1 if holding_days < 0 else min(holding_days + 1, max_holding_days)
        )
        destination = stable_cell_id(
            cost_bucket_id=cost_bucket_id,
            holding_days=aged_holding_days,
            sensitivity=sensitivity,
        )
        self.normal_destination_by_cell_id[cell_id] = destination
        return destination


def _pack_xor_floats(values: tuple[float, ...]) -> bytes:
    """Losslessly delta-code IEEE-754 bits; no retention precision is discarded."""

    if not values:
        return b""
    previous = struct.unpack("<Q", struct.pack("<d", values[0]))[0]
    output = bytearray(struct.pack("<Q", previous))
    for value in values[1:]:
        current = struct.unpack("<Q", struct.pack("<d", value))[0]
        delta = current ^ previous
        if delta == 0:
            output.append(0)
        else:
            offset = 0
            while (delta & 0xFF) == 0:
                offset += 1
                delta >>= 8
            length = (delta.bit_length() + 7) // 8
            output.append((offset << 4) | length)
            output.extend(delta.to_bytes(length, "little"))
        previous = current
    return bytes(output)


def _pack_palette_indexes(indexes: tuple[int, ...], bits: int) -> bytes:
    """Pack exact palette indexes using the minimum fixed number of bits."""

    if not indexes:
        return b""
    if not 1 <= bits <= 8:
        raise ValueError("palette bit width must be in [1,8]")
    output = bytearray((len(indexes) * bits + 7) // 8)
    bit_offset = 0
    limit = 1 << bits
    for index in indexes:
        if not 0 <= index < limit:
            raise ValueError("palette index exceeds bit width")
        byte_offset = bit_offset >> 3
        shift = bit_offset & 7
        output[byte_offset] |= index << shift & 0xFF
        if shift + bits > 8:
            output[byte_offset + 1] |= index >> (8 - shift)
        bit_offset += bits
    return bytes(output)


def _unpack_palette_indexes(payload: bytes, count: int, bits: int) -> tuple[int, ...]:
    """Inverse of :func:`_pack_palette_indexes`."""

    expected_size = (count * bits + 7) // 8
    if len(payload) != expected_size:
        raise ValueError("invalid bit-packed palette payload size")
    mask = (1 << bits) - 1
    indexes: list[int] = []
    bit_offset = 0
    for _ in range(count):
        byte_offset = bit_offset >> 3
        shift = bit_offset & 7
        value = payload[byte_offset] >> shift
        if shift + bits > 8:
            value |= payload[byte_offset + 1] << (8 - shift)
        indexes.append(value & mask)
        bit_offset += bits
    return tuple(indexes)


def _unpack_xor_floats(payload: bytes, count: int) -> tuple[float, ...]:
    """Inverse of :func:`_pack_xor_floats`, used by replay and focused tests."""

    if count == 0:
        if payload:
            raise ValueError("unexpected XOR payload for empty retention sequence")
        return ()
    if len(payload) < 8:
        raise ValueError("truncated XOR retention payload")
    previous = struct.unpack("<Q", payload[:8])[0]
    values = [struct.unpack("<d", struct.pack("<Q", previous))[0]]
    cursor = 8
    for _ in range(count - 1):
        if cursor >= len(payload):
            raise ValueError("truncated XOR retention payload")
        tag = payload[cursor]
        cursor += 1
        if tag:
            offset = tag >> 4
            length = tag & 0x0F
            if length == 0 or offset + length > 8 or cursor + length > len(payload):
                raise ValueError("invalid XOR retention payload")
            delta = int.from_bytes(payload[cursor : cursor + length], "little")
            cursor += length
            previous ^= delta << (offset * 8)
        values.append(struct.unpack("<d", struct.pack("<Q", previous))[0])
    if cursor != len(payload):
        raise ValueError("trailing bytes in XOR retention payload")
    return tuple(values)


def _pack_xor_byte_shuffled_floats(values: tuple[float, ...]) -> bytes:
    """Store exact XOR words in byte planes for stronger outer compression."""

    if not values:
        return b""
    # This is the hot path for daily high-cardinality survival vectors.  Keep
    # the exact IEEE-754 representation, but perform XOR and byte shuffling in
    # contiguous native arrays instead of thousands of Python pack/unpack calls.
    words = np.asarray(values, dtype="<f8").view("<u8")
    xor_words = words.copy()
    xor_words[1:] = np.bitwise_xor(words[1:], words[:-1])
    return xor_words.view(np.uint8).reshape(-1, 8).T.tobytes()


def _unpack_xor_byte_shuffled_floats(
    payload: bytes, count: int
) -> tuple[float, ...]:
    """Inverse byte-plane shuffle without changing any IEEE-754 bit."""

    if len(payload) != count * 8:
        raise ValueError("invalid byte-shuffled XOR retention payload size")
    if count == 0:
        return ()
    raw = bytearray(len(payload))
    for byte_offset in range(8):
        plane_start = byte_offset * count
        raw[byte_offset::8] = payload[plane_start : plane_start + count]
    xor_words = struct.unpack(f"<{count}Q", raw)
    previous = 0
    values: list[float] = []
    for position, word in enumerate(xor_words):
        current = word if position == 0 else word ^ previous
        values.append(struct.unpack("<d", struct.pack("<Q", current))[0])
        previous = current
    return tuple(values)


def _encode_retention(
    fractions: tuple[float, ...], sensitivity_codes: tuple[int, ...]
) -> tuple[int, list[float], bytes]:
    """Use cheap exact encodings and leave bulk compression to Parquet/Zstd."""

    if len(fractions) != len(sensitivity_codes):
        raise ValueError("retention and sensitivity lengths differ")
    if not fractions:
        return RETENTION_RAW, [], b""

    # Searching palettes and XOR-packing every large daily vector saved disk at
    # the cost of repeatedly walking millions of Python floats.  The annual
    # files are comfortably inside the storage budget with raw doubles, and
    # Parquet/Zstd still compresses them as a column.  Keep the compact search
    # only for small vectors where its CPU cost is negligible.
    if len(fractions) >= 128:
        first = fractions[0]
        if all(value == first for value in fractions[1:]):
            return RETENTION_CONSTANT, [first], b""
        return RETENTION_RAW, list(fractions), b""

    candidates: list[tuple[int, int, list[float], bytes]] = [
        (len(fractions) * 8, RETENTION_RAW, list(fractions), b"")
    ]
    # Most real daily vectors have far more than 255 exact rates.  Stop palette
    # discovery as soon as that encoding is impossible instead of hashing the
    # complete vector and then traversing it again.
    palette: list[float] = []
    palette_indexes: dict[float, int] = {}
    high_cardinality = False
    for value in fractions:
        if value in palette_indexes:
            continue
        if len(palette) == 255:
            high_cardinality = True
            break
        palette_indexes[value] = len(palette)
        palette.append(value)
    if len(palette) == 1:
        return RETENTION_CONSTANT, palette, b""
    if not high_cardinality:
        index_values = tuple(palette_indexes[value] for value in fractions)
        payload = bytes(index_values)
        candidates.append(
            (
                len(palette) * 8 + len(payload),
                RETENTION_PALETTE_U8,
                palette,
                payload,
            )
        )
        bits = max(1, (len(palette) - 1).bit_length())
        packed_payload = _pack_palette_indexes(index_values, bits)
        candidates.append(
            (
                len(palette) * 8 + len(packed_payload),
                RETENTION_PALETTE_BITPACK,
                palette,
                packed_payload,
            )
        )

    bases: list[float] = []
    for sensitivity in range(3):
        group = [
            value
            for value, code in zip(fractions, sensitivity_codes, strict=True)
            if code == sensitivity
        ]
        bases.append(Counter(group).most_common(1)[0][0] if group else 0.0)
    override_positions = [
        position
        for position, (value, code) in enumerate(
            zip(fractions, sensitivity_codes, strict=True)
        )
        if value != bases[code]
    ]
    group_values = bases + [fractions[position] for position in override_positions]
    group_payload = (
        struct.pack(f"<{len(override_positions)}I", *override_positions)
        if override_positions
        else b""
    )
    candidates.append(
        (
            len(group_values) * 8 + len(group_payload),
            RETENTION_BY_SENSITIVITY,
            group_values,
            group_payload,
        )
    )

    xor_payload = _pack_xor_floats(fractions)
    candidates.append((len(xor_payload), RETENTION_XOR, [], xor_payload))
    _, encoding, values, payload = min(candidates, key=lambda item: item[0])
    return encoding, values, payload


def _decode_retention(
    encoding: int,
    values: list[float],
    payload: bytes,
    sensitivity_codes: tuple[int, ...],
) -> tuple[float, ...]:
    """Replay one exact retention vector from the compact operator log."""

    count = len(sensitivity_codes)
    if encoding == RETENTION_RAW:
        result = tuple(values)
    elif encoding == RETENTION_CONSTANT:
        result = (values[0],) * count
    elif encoding == RETENTION_PALETTE_U8:
        if len(payload) != count:
            raise ValueError("invalid palette payload size")
        if any(index >= len(values) for index in payload):
            raise ValueError("palette index is out of range")
        result = tuple(values[index] for index in payload)
    elif encoding == RETENTION_PALETTE_BITPACK:
        bits = max(1, (len(values) - 1).bit_length())
        indexes = _unpack_palette_indexes(payload, count, bits)
        if any(index >= len(values) for index in indexes):
            raise ValueError("palette index is out of range")
        result = tuple(values[index] for index in indexes)
    elif encoding == RETENTION_BY_SENSITIVITY:
        override_values = values[3:]
        if len(payload) != len(override_values) * 4:
            raise ValueError("invalid sensitivity retention payload")
        result_list = [values[code] for code in sensitivity_codes]
        if override_values:
            positions = struct.unpack(f"<{len(override_values)}I", payload)
            for position, value in zip(positions, override_values, strict=True):
                result_list[position] = value
        result = tuple(result_list)
    elif encoding == RETENTION_XOR:
        result = _unpack_xor_floats(payload, count)
    elif encoding == RETENTION_XOR_BYTE_SHUFFLE:
        result = _unpack_xor_byte_shuffled_floats(payload, count)
    elif encoding == RETENTION_SOURCE_REPLAY:
        raise ValueError(
            "retention vector is source-replay-only; regenerate it from the "
            "registered daily/minute inputs and model version"
        )
    else:
        raise ValueError(f"unknown retention encoding: {encoding}")
    if len(result) != count:
        raise ValueError("decoded retention length differs from source inventory")
    return result


def _normally_aged_cell_id(
    cell: Any, *, max_holding_days: int = DEFAULT_MAX_HOLDING_DAYS
) -> int:
    holding_days = (
        -1 if cell.holding_days < 0 else min(cell.holding_days + 1, max_holding_days)
    )
    return stable_cell_id(
        cost_bucket_id=cell.cost_bucket_id,
        holding_days=holding_days,
        sensitivity=cell.sensitivity,
    )


def _storage_source_key(cell: Any) -> tuple[bool, int, int, int, int]:
    """Order sources by economic dimensions so exact float deltas compress well."""

    return (
        cell.cost_bucket_id is None,
        0 if cell.cost_bucket_id is None else cell.cost_bucket_id,
        cell.holding_days,
        SENSITIVITY_CODE[cell.sensitivity],
        cell.cell_id,
    )


def _storage_source_view_key(
    item: tuple[int, tuple[int | None, int, TurnoverSensitivity, float]],
) -> tuple[bool, int, int, int, int]:
    cell_id, (cost_bucket_id, holding_days, sensitivity, _) = item
    return (
        cost_bucket_id is None,
        0 if cost_bucket_id is None else cost_bucket_id,
        holding_days,
        SENSITIVITY_CODE[sensitivity],
        cell_id,
    )


def _sql_paths(paths: list[Path]) -> str:
    return "[" + ",".join("'" + str(path).replace("'", "''") + "'" for path in paths) + "]"


def _file_sha256(path: Path | None) -> str | None:
    if path is None:
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _minute_paths_for_year(year: int, root: Path = MINUTE_ROOT) -> list[Path]:
    return [
        root / f"{year}_day_parquet_none.parquet",
        *(root / name for name in MINUTE_YEAR_SUPPLEMENTS.get(year, ())),
    ]


def _stage_marker_matches(
    metadata: dict[str, Any],
    *,
    year: int,
    warmup_start: int,
    buckets: int,
    symbols: tuple[str, ...],
    prior_history_start: int | None = None,
    end_date: date | None = None,
    daily_root: Path = DAILY_ROOT,
    minute_root: Path = MINUTE_ROOT,
    action_override_sha256: str | None = None,
    baostock_delta_sha256: str | None = None,
) -> bool:
    base = {
        "year": year,
        "warmup_start": warmup_start,
        "buckets": buckets,
        "layout_version": STAGE_LAYOUT_VERSION,
        "prior_history_start": prior_history_start,
        "end_date": None if end_date is None else end_date.isoformat(),
        "daily_root": str(daily_root.resolve()),
        "minute_root": str(minute_root.resolve()),
        "action_override_sha256": action_override_sha256,
        "baostock_delta_sha256": baostock_delta_sha256,
    }
    comparable = dict(metadata)
    comparable.setdefault("daily_root", str(DAILY_ROOT.resolve()))
    comparable.setdefault("minute_root", str(MINUTE_ROOT.resolve()))
    comparable.setdefault("action_override_sha256", None)
    comparable.setdefault("baostock_delta_sha256", None)
    if any(comparable.get(key) != value for key, value in base.items()):
        return False
    staged_symbols = metadata.get("symbols")
    if not symbols:
        return staged_symbols is None
    # A full-market stage is a valid superset for a targeted run.
    if staged_symbols is None:
        return True
    if not isinstance(staged_symbols, list):
        return False
    return set(symbols).issubset(staged_symbols)


def _stage_inputs(
    *,
    year: int,
    warmup_start: int,
    buckets: int,
    stage_root: Path,
    symbols: tuple[str, ...] = (),
    prior_history_start: int | None = None,
    end_date: date | None = None,
    daily_root: Path = DAILY_ROOT,
    minute_root: Path = MINUTE_ROOT,
    research_action_overrides: Path | None = None,
    baostock_delta_file: Path | None = None,
) -> None:
    action_override_sha256 = _file_sha256(research_action_overrides)
    baostock_delta_sha256 = _file_sha256(baostock_delta_file)
    marker = stage_root / "COMPLETE.json"
    if marker.exists():
        try:
            metadata = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            metadata = {}
        if _stage_marker_matches(
            metadata,
            year=year,
            warmup_start=warmup_start,
            buckets=buckets,
            symbols=symbols,
            prior_history_start=prior_history_start,
            end_date=end_date,
            daily_root=daily_root,
            minute_root=minute_root,
            action_override_sha256=action_override_sha256,
            baostock_delta_sha256=baostock_delta_sha256,
        ):
            return
    if stage_root.exists():
        shutil.rmtree(stage_root)
    daily_paths = [
        daily_root / f"partition_year={value}/data_0.parquet"
        for value in range(warmup_start, year + 1)
    ]
    minute_paths = [
        path
        for value in range(warmup_start, year + 1)
        for path in _minute_paths_for_year(value, minute_root)
    ]
    required_paths = daily_paths + minute_paths
    if research_action_overrides is not None:
        required_paths.append(research_action_overrides)
    if baostock_delta_file is not None:
        required_paths.append(baostock_delta_file)
    missing = [path for path in required_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing inputs: {missing[:3]}")
    daily_out = stage_root / "daily"
    minute_out = stage_root / "minute"
    daily_out.mkdir(parents=True)
    minute_out.mkdir(parents=True)
    temp_out = stage_root / "_duckdb_tmp"
    temp_out.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute(f"SET threads={buckets}")
    connection.execute("SET memory_limit='8GiB'")
    connection.execute("SET preserve_insertion_order=false")
    connection.execute("SET partitioned_write_max_open_files=32")
    escaped_temp_out = str(temp_out.resolve()).replace("'", "''")
    connection.execute(f"SET temp_directory='{escaped_temp_out}'")
    if symbols:
        values = ",".join(
            "('" + symbol.replace("'", "''") + "')"
            for symbol in sorted(set(symbols))
        )
        universe_sql = f"""
            SELECT symbol
            FROM (VALUES {values}) AS requested(symbol)
            WHERE regexp_matches(symbol, '^(00|30|60)')
        """
    else:
        target_path = daily_root / f"partition_year={year}/data_0.parquet"
        universe_sql = f"""
            SELECT DISTINCT symbol
            FROM read_parquet('{str(target_path).replace("'", "''")}')
            WHERE regexp_matches(symbol, '^(00|30|60)')
        """
    prior_symbols: list[str] = []
    end_date_predicate = (
        "TRUE"
        if end_date is None
        else f"trade_date <= DATE '{end_date.isoformat()}'"
    )
    if prior_history_start is not None and prior_history_start < year:
        prior_paths = [
            daily_root / f"partition_year={value}/data_0.parquet"
            for value in range(prior_history_start, year)
        ]
        missing_prior = [path for path in prior_paths if not path.exists()]
        if missing_prior:
            raise FileNotFoundError(f"missing prior-history inputs: {missing_prior[:3]}")
        prior_symbols = [
            str(row[0])
            for row in connection.execute(
                f"""
                WITH universe AS ({universe_sql})
                SELECT DISTINCT d.symbol
                FROM read_parquet({_sql_paths(prior_paths)}) d
                SEMI JOIN universe u ON d.symbol = u.symbol
                """
            ).fetchall()
        ]
    if research_action_overrides is None:
        action_override_sql = """
            SELECT
                CAST(NULL AS VARCHAR) AS symbol,
                CAST(NULL AS DATE) AS trade_date,
                CAST(NULL AS BOOLEAN) AS apply_action,
                CAST(NULL AS DOUBLE) AS share_multiplier,
                CAST(NULL AS DOUBLE) AS cash_per_share,
                CAST(NULL AS DOUBLE) AS circulating_shares_override,
                CAST(NULL AS TIMESTAMP) AS known_at,
                CAST(NULL AS VARCHAR) AS snapshot_id
            WHERE false
        """
    else:
        escaped_override = str(research_action_overrides.resolve()).replace("'", "''")
        action_override_sql = f"""
            SELECT symbol, trade_date, apply_action, share_multiplier,
                   cash_per_share, circulating_shares_override, known_at,
                   snapshot_id
            FROM read_parquet('{escaped_override}')
        """
    minute_source_sql = f"""
        SELECT m.qmt_code, m.trade_date, m.bar_end_time,
               m.open, m.high, m.low, m.close, m.volume, m.amount,
               'qmt-none-1m' AS minute_source
        FROM read_parquet({_sql_paths(minute_paths)}) m
    """
    if baostock_delta_file is not None:
        escaped_delta = str(baostock_delta_file.resolve()).replace("'", "''")
        minute_source_sql += f"""
          UNION ALL
          SELECT SUBSTR(code, 4) || '.' || UPPER(SUBSTR(code, 1, 2)) AS qmt_code,
                 CAST(date AS DATE) AS trade_date,
                 STRPTIME(SUBSTR(time, 1, 14), '%Y%m%d%H%M%S') AS bar_end_time,
                 TRY_CAST(open AS DOUBLE) AS open,
                 TRY_CAST(high AS DOUBLE) AS high,
                 TRY_CAST(low AS DOUBLE) AS low,
                 TRY_CAST(close AS DOUBLE) AS close,
                 TRY_CAST(volume AS DOUBLE) AS volume,
                 TRY_CAST(amount AS DOUBLE) AS amount,
                 'baostock-none-5m' AS minute_source
          FROM read_parquet('{escaped_delta}')
        """
    daily_bucketed = stage_root / "_daily_bucketed"
    minute_bucketed = stage_root / "_minute_bucketed"

    def split_bucketed_by_symbol(bucketed_root: Path, output_root: Path) -> None:
        for bucket in range(buckets):
            bucket_root = bucketed_root / f"bucket={bucket}"
            source_paths = sorted(bucket_root.glob("*.parquet"))
            if not source_paths:
                continue
            destination = output_root / f"bucket={bucket}"
            destination.mkdir(parents=True, exist_ok=True)
            escaped_destination = str(destination.resolve()).replace("'", "''")
            connection.execute(
                f"""
                COPY (
                    SELECT *
                    FROM read_parquet(
                        {_sql_paths(source_paths)},
                        hive_partitioning=false,
                        union_by_name=true
                    )
                ) TO '{escaped_destination}'
                (FORMAT PARQUET, PARTITION_BY(symbol), COMPRESSION ZSTD,
                 ROW_GROUP_SIZE 262144)
                """
            )
            shutil.rmtree(bucket_root)
        bucketed_root.rmdir()

    connection.execute(
        f"""
        COPY (
            WITH universe AS ({universe_sql}),
            action_override AS ({action_override_sql})
            SELECT d.symbol, d.trade_date, d.open, d.high, d.low, d.close,
                   d.volume, d.amount, d.trade_status,
                   d.turnover_fraction AS turnover,
                   CASE WHEN o.symbol IS NOT NULL
                        THEN o.circulating_shares_override
                        ELSE d.circulating_shares END AS circulating_shares,
                   d.float_available_date, d.corporate_action_available_date,
                   CASE WHEN o.symbol IS NOT NULL
                        THEN false ELSE d.corporate_action_blocking
                   END AS corporate_action_blocking,
                   CASE WHEN coalesce(o.apply_action, false)
                        THEN o.share_multiplier ELSE d.share_multiplier
                   END AS share_multiplier,
                   CASE WHEN coalesce(o.apply_action, false)
                        THEN o.cash_per_share ELSE d.cash_per_share
                   END AS cash_per_share,
                   d.available_at,
                   CASE WHEN o.symbol IS NOT NULL
                        THEN concat_ws('|', d.snapshot_id, o.snapshot_id)
                        ELSE d.snapshot_id END AS snapshot_id,
                   d.daily_snapshot_id, d.float_snapshot_id,
                   CASE WHEN o.symbol IS NOT NULL
                        THEN o.snapshot_id ELSE d.corporate_action_snapshot_id
                   END AS corporate_action_snapshot_id,
                   CASE WHEN o.symbol IS NOT NULL THEN
                        d.bar_valid AND d.trading_state_valid AND d.industry_valid
                        AND d.float_valid AND d.market_valid AND d.market_rule_valid
                        AND d.historical_identity_valid
                        ELSE d.hard_valid END AS hard_valid,
                   CAST(hash(d.symbol) % {buckets} AS INTEGER) AS bucket
            FROM read_parquet({_sql_paths(daily_paths)}) d
            SEMI JOIN universe u ON d.symbol = u.symbol
            LEFT JOIN action_override o USING (symbol, trade_date)
            WHERE {end_date_predicate}
        ) TO '{str(daily_bucketed).replace("'", "''")}'
        (FORMAT PARQUET, PARTITION_BY(bucket), COMPRESSION ZSTD,
         ROW_GROUP_SIZE 262144)
        """
    )
    split_bucketed_by_symbol(daily_bucketed, daily_out)
    connection.execute(
        f"""
        COPY (
            WITH universe AS ({universe_sql}),
            minute_source AS ({minute_source_sql})
            SELECT m.qmt_code AS symbol, m.trade_date, m.bar_end_time,
                   m.open, m.high, m.low, m.close, m.volume, m.amount,
                   m.minute_source,
                   CAST(hash(m.qmt_code) % {buckets} AS INTEGER) AS bucket
            FROM minute_source m
            SEMI JOIN universe u ON m.qmt_code = u.symbol
            WHERE {end_date_predicate}
        ) TO '{str(minute_bucketed).replace("'", "''")}'
        (FORMAT PARQUET, PARTITION_BY(bucket), COMPRESSION ZSTD,
         ROW_GROUP_SIZE 262144)
        """
    )
    split_bucketed_by_symbol(minute_bucketed, minute_out)
    connection.close()
    marker_metadata: dict[str, Any] = {
        "year": year,
        "warmup_start": warmup_start,
        "buckets": buckets,
        "layout_version": STAGE_LAYOUT_VERSION,
        "prior_history_start": prior_history_start,
        "end_date": None if end_date is None else end_date.isoformat(),
        "daily_root": str(daily_root.resolve()),
        "minute_root": str(minute_root.resolve()),
        "action_override_sha256": action_override_sha256,
        "baostock_delta_sha256": baostock_delta_sha256,
    }
    if symbols:
        marker_metadata["symbols"] = sorted(set(symbols))
    (stage_root / "PRIOR_SYMBOLS.json").write_text(
        json.dumps(sorted(prior_symbols), ensure_ascii=False), encoding="utf-8"
    )
    marker.write_text(
        json.dumps(marker_metadata, ensure_ascii=False), encoding="utf-8"
    )


def _symbol_partition_dirs(
    stage_root: Path, kind: str, bucket: int
) -> dict[str, Path]:
    root = stage_root / kind / f"bucket={bucket}"
    return {
        path.name.removeprefix("symbol="): path
        for path in root.glob("symbol=*")
        if path.is_dir()
    }


def _read_symbol_partition(path: Path | None, symbol: str) -> list[dict[str, Any]]:
    """Read one stock only; partition columns are restored without a global sort."""

    if path is None:
        return []
    rows: list[dict[str, Any]] = []
    for parquet_path in sorted(path.glob("*.parquet")):
        for row in pq.ParquetFile(parquet_path).read().to_pylist():
            row["symbol"] = symbol
            rows.append(row)
    return rows


def _read_prior_symbols(stage_root: Path) -> set[str]:
    path = stage_root / "PRIOR_SYMBOLS.json"
    if not path.exists():
        return set()
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ValueError("invalid staged prior-symbol index")
    return set(values)


def _resolve_resume_root(
    *,
    output_root: Path,
    year: int,
    warmup_start: int,
    explicit: Path | None,
    auto_resume: bool,
) -> tuple[Path | None, str]:
    """Use the adjacent year's exact terminal state unless explicitly disabled."""

    if explicit is not None:
        return explicit, "explicit"
    if auto_resume and year > warmup_start:
        candidate = output_root.parent / f"year={year - 1}"
        if (candidate / "terminal").is_dir():
            return candidate, "auto_adjacent_year"
    return None, "none"


def _daily_fallback_bar(row: dict[str, Any]) -> tuple[MinuteBar, ...]:
    volume = float(row.get("volume") or 0.0)
    if volume <= 0:
        return ()
    day = _date(row["trade_date"])
    timestamp = _aware(day, 15)
    amount = float(row.get("amount") or 0.0)
    low = float(row["low"])
    high = float(row["high"])
    vwap = amount / volume if amount > 0 else float(row["close"])
    if not low <= vwap <= high:
        vwap = float(row["close"])
    return (
        MinuteBar(
            timestamp=timestamp,
            available_at=timestamp,
            snapshot_id=f"daily-fallback:{row['symbol']}:{day.isoformat()}",
            open=float(row["open"]),
            high=high,
            low=low,
            close=float(row["close"]),
            volume_shares=volume,
            vwap=vwap,
        ),
    )


def _cap_prepared_minute_path(
    path: PreparedMinutePath, *, max_volume: float
) -> PreparedMinutePath:
    """Saturate modeled turnover at the causal PRE float without changing prices.

    Raw daily/minute volume remains untouched in its registered source.  This
    only scales the migration operator when the observed volume implies more
    than one sale per PRE share, which cannot be represented under A-share T+1.
    """

    if not math.isfinite(max_volume) or max_volume <= 0:
        raise ValueError("turnover cap must be finite and positive")
    if path.total_volume <= max_volume + tolerance(max_volume):
        return path
    # Leave a one-billionth numerical headroom instead of asking the bounded
    # seller allocator to hit an exactly empty floating-point inventory.
    capped_volume = max_volume * (1.0 - 1e-9)
    scale = capped_volume / path.total_volume
    scaled_volumes = path.volumes * scale
    scaled_purchase_volumes = path.purchase_volumes * scale
    return replace(
        path,
        purchases=tuple(
            (bucket, price, volume * scale)
            for bucket, price, volume in path.purchases
        ),
        bucket_purchases=tuple(
            (bucket, price, volume * scale)
            for bucket, price, volume in path.bucket_purchases
        ),
        total_volume=stable_sum(scaled_volumes),
        volumes=scaled_volumes,
        purchase_volumes=scaled_purchase_volumes,
    )


def _profile_from_bucket_mass(
    by_bucket: dict[int, float],
    grid: StableLogPriceGrid,
    *,
    current_price: float | None = None,
) -> dict[str, float | None] | None:
    if not by_bucket:
        return None
    pairs = [
        (economic_break_even_for_bucket(grid, bucket_id), mass, bucket_id)
        for bucket_id, mass in sorted(by_bucket.items())
    ]
    profile_total = math.fsum(mass for _, mass, _ in pairs)
    if current_price is None:
        raise ValueError("non-empty chip mass requires the real daily close")
    thresholds = tuple(
        profile_total * probability for probability in (0.01, 0.10, 0.50, 0.90, 0.99)
    )
    quantiles: list[float] = []
    cumulative = 0.0
    threshold_index = 0
    for price, mass, _ in pairs:
        cumulative += mass
        while threshold_index < len(thresholds) and cumulative >= thresholds[threshold_index]:
            quantiles.append(price)
            threshold_index += 1
    if threshold_index < len(thresholds):
        quantiles.extend([pairs[-1][0]] * (len(thresholds) - threshold_index))
    peaks = detect_canonical_peaks(
        by_bucket,
        price_for_bucket=lambda bucket: economic_break_even_for_bucket(grid, bucket),
        as_of=date.min,
    )
    dominant = dominant_canonical_peak(peaks)
    prices = [item[0] for item in pairs]
    masses = [item[1] for item in pairs]
    profit_ratio = math.fsum(
        mass for price, mass in zip(prices, masses, strict=True) if price <= current_price
    ) / profile_total
    asr = math.fsum(
        mass
        for price, mass in zip(prices, masses, strict=True)
        if 0.9 * current_price <= price <= 1.1 * current_price
    ) / profile_total
    concentration_20 = 0.0
    right = 0
    window_mass = 0.0
    for left, price in enumerate(prices):
        while right < len(prices) and prices[right] <= price * 1.20:
            window_mass += masses[right]
            right += 1
        concentration_20 = max(concentration_20, window_mass / profile_total)
        window_mass -= masses[left]
    return {
        "average": math.fsum(price * mass for price, mass, _ in pairs) / profile_total,
        "p01": quantiles[0],
        "p10": quantiles[1],
        "p50": quantiles[2],
        "p90": quantiles[3],
        "p99": quantiles[4],
        "profit_ratio": profit_ratio,
        "asr": asr,
        "cbw": 100.0 * (quantiles[4] - quantiles[0]) / quantiles[0],
        "concentration_20": concentration_20,
        "dominant_peak_today": None if dominant is None else dominant.center_price,
        "dominant_band_lower": None if dominant is None else dominant.lower_price,
        "dominant_band_upper": None if dominant is None else dominant.upper_price,
        "dominant_band_mass": None if dominant is None else dominant.mass,
        "peak_count": len(peaks),
    }


def _output_row(
    *,
    state: MutableChipState,
    transition: Any,
    fallback: bool,
    previous_post: dict[int, tuple[int | None, int, TurnoverSensitivity, float]] | None,
    previous_economic_buckets: dict[int, int | None] | None,
    codec: _CellCodec,
    grid: StableLogPriceGrid,
    cash_dividend_per_share: float = 0.0,
    share_multiplier: float = 1.0,
    action_provenance_ids: tuple[str, ...] = (),
    force_checkpoint: bool = False,
    current_price: float | None = None,
) -> tuple[
    tuple[Any, ...],
    dict[int, tuple[int | None, int, TurnoverSensitivity, float]],
    dict[int, int | None],
]:
    """Encode a checkpoint or a compact daily operator/replay locator."""

    current, by_bucket, known_shares, current_economic_buckets = (
        codec.register_state_and_profile(state, grid)
    )
    metrics = None
    profile_close = current_price
    if by_bucket:
        if profile_close is None:
            raise ValueError("non-empty chip mass requires the real daily close")
        metrics = compute_distribution_metrics(
            by_bucket,
            close=profile_close,
            grid=grid,
        )
    total = state.free_float_shares
    checkpoint_local_ids: list[int] = []
    checkpoint_shares: list[float] = []
    checkpoint_economic_bucket_ids: list[int | None] = []
    source_override: list[int] = []
    destination_override_positions: list[int] = []
    destination_override_cell_ids: list[int] = []
    retention_encoding = RETENTION_RAW
    retention_values: list[float] = []
    retention_codes = b""
    adjustment_local_ids: list[int] = []
    adjustment_shares: list[float] = []
    adjustment_economic_bucket_ids: list[int | None] = []

    if previous_post is None or force_checkpoint:
        checkpoint_local_ids = [codec.local_id(cell_id) for cell_id in current]
        checkpoint_shares = [cell[3] for cell in current.values()]
        checkpoint_economic_bucket_ids = [
            current_economic_buckets[cell_id] for cell_id in current
        ]
    # Keep the transition on checkpoint rows too.  A lifecycle anchor may sit
    # before this checkpoint (or in the prior year) and must replay through it.
    if previous_post is not None:
        previous_by_id = previous_post
        actual_sources = tuple(transition.source_cell_ids)
        # v12 ids are full economic identities and are intentionally not
        # reversible packed dimension codes.  Numeric id order is the compact,
        # deterministic source order shared with the replay decoder.
        expected_sources = tuple(sorted(previous_by_id))
        sources_are_unique = all(
            left != right for left, right in pairwise(actual_sources)
        )
        sources_match_previous = len(actual_sources) == len(previous_by_id) and all(
            source_id in previous_by_id for source_id in actual_sources
        )
        if sources_are_unique and sources_match_previous:
            arc_by_source = {
                source_id: (destination_id, retained_fraction)
                for source_id, destination_id, retained_fraction in zip(
                    transition.source_cell_ids,
                    transition.destination_cell_ids,
                    transition.retained_fractions,
                    strict=True,
                )
            }
            ordered_sources = expected_sources
            ordered_destinations = tuple(
                arc_by_source[source_id][0] for source_id in ordered_sources
            )
            ordered_fractions = tuple(
                arc_by_source[source_id][1] for source_id in ordered_sources
            )
        else:
            # Preserve unusual multi-arc transitions exactly instead of guessing an order.
            source_override = [codec.local_id(cell_id) for cell_id in actual_sources]
            ordered_sources = actual_sources
            ordered_destinations = tuple(transition.destination_cell_ids)
            ordered_fractions = tuple(transition.retained_fractions)
        predicted: dict[int, float] = {}
        for position, (source_id, destination_id, retained_fraction) in enumerate(
            zip(
                ordered_sources,
                ordered_destinations,
                ordered_fractions,
                strict=True,
            )
        ):
            source_cell = previous_by_id.get(source_id)
            if source_cell is None:
                missing = sorted(set(ordered_sources) - set(previous_by_id))
                extra = sorted(set(previous_by_id) - set(ordered_sources))
                raise ValueError(
                    "transition source is absent from prior POST inventory: "
                    f"symbol={state.symbol}, date={state.trading_date}, "
                    f"model={state.seller_model.value}, source={source_id}, "
                    f"prior_cells={len(previous_by_id)}, arcs={len(ordered_sources)}, "
                    f"cash={cash_dividend_per_share}, split={share_multiplier}, "
                    f"missing={missing[:3]}, extra={extra[:3]}, "
                    f"missing_dims={[codec.by_cell_id.get(value) for value in missing[:3]]}, "
                    f"extra_dims={[codec.by_cell_id.get(value) for value in extra[:3]]}"
                )
            # v12 never infers a destination from a source id: economic-cost
            # coordinates are state identity and can change on an action day.
            destination_override_positions.append(position)
            destination_override_cell_ids.append(codec.local_id(destination_id))
            retained_shares = source_cell[3] * retained_fraction
            if retained_shares != 0.0:
                predicted[destination_id] = (
                    predicted.get(destination_id, 0.0) + retained_shares
                )

        # v12 must be independently replayable without deriving sensitivity
        # from a compact id.  Retention is therefore stored exactly, and every
        # destination is explicit below.
        retention_encoding = RETENTION_RAW
        retention_values = list(ordered_fractions)
        retention_codes = b""
        for cell_id, cell in current.items():
            delta = cell[3] - predicted.get(cell_id, 0.0)
            if delta != 0.0:
                adjustment_local_ids.append(codec.local_id(cell_id))
                adjustment_shares.append(delta)
                adjustment_economic_bucket_ids.append(
                    current_economic_buckets.get(cell_id)
                )
        for cell_id, predicted_shares in predicted.items():
            if cell_id not in current:
                adjustment_local_ids.append(codec.local_id(cell_id))
                adjustment_shares.append(-predicted_shares)
                adjustment_economic_bucket_ids.append(
                    None
                    if previous_economic_buckets is None
                    else previous_economic_buckets.get(cell_id)
                )
        reconstructed_total = math.fsum(predicted.values()) + math.fsum(adjustment_shares)
        if abs(reconstructed_total - total) > tolerance(total):
            raise ValueError(
                "compact operator does not conserve inventory: "
                f"{reconstructed_total} != {total}"
            )
    row = (
        STORAGE_VERSION,
        state.model_version,
        state.symbol,
        state.trading_date,
        state.seller_model.value,
        state.snapshot_id,
        state.decision_at,
        state.available_at,
        hashlib.sha256(
            "\n".join(state.input_snapshot_ids).encode("utf-8")
        ).digest(),
        total,
        known_shares / total,
        (total - known_shares) / total,
        float(profile_close) if profile_close is not None else None,
        None if metrics is None else metrics.average_cost,
        None if metrics is None else metrics.cost_p01,
        None if metrics is None else metrics.cost_p10,
        None if metrics is None else metrics.cost_p50,
        None if metrics is None else metrics.cost_p90,
        None if metrics is None else metrics.cost_p99,
        None if metrics is None else metrics.profit_ratio,
        None if metrics is None else metrics.asr,
        None if metrics is None else metrics.cbw,
        None if metrics is None else metrics.concentration_20,
        None if metrics is None else metrics.main_peak,
        None if metrics is None else metrics.main_peak,
        None if metrics is None else metrics.dominant_band_lower,
        None if metrics is None else metrics.dominant_band_upper,
        None if metrics is None else metrics.dominant_band_mass,
        None if metrics is None else metrics.peak_count,
        1.0 if state.hard_valid else 0.0,
        checkpoint_local_ids,
        checkpoint_shares,
        checkpoint_economic_bucket_ids,
        transition.transition_id,
        source_override,
        destination_override_positions,
        destination_override_cell_ids,
        retention_encoding,
        retention_values,
        retention_codes,
        adjustment_local_ids,
        adjustment_shares,
        adjustment_economic_bucket_ids,
        cash_dividend_per_share,
        share_multiplier,
        list(action_provenance_ids),
        transition.fixed_pre_eligible_shares,
        transition.executed_sell_shares,
        transition.same_day_resale_shares,
        state.conservation_error,
        fallback,
        state.hard_valid,
        _research_valid(state),
        list(state.quality_reason_codes),
    )
    return row, current, current_economic_buckets


def _run_symbol(
    symbol: str,
    daily_rows: list[dict[str, Any]],
    minute_rows: list[dict[str, Any]],
    year: int,
    writer: pq.ParquetWriter | None,
    initial_snapshots: dict[SellerModel, ChipSnapshotV2] | None = None,
    *,
    emit_operators: bool = True,
    emit_start_date: date | None = None,
) -> tuple[dict[str, Any], dict[SellerModel, ChipSnapshotV2]]:
    daily_rows.sort(key=lambda row: _date(row["trade_date"]))
    if not daily_rows:
        raise ValueError("no daily rows")
    minute_by_date: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for row in minute_rows:
        minute_by_date[_date(row["trade_date"])].append(row)
    grid = StableLogPriceGrid(1.0, 0.0025, GRID_VERSION)
    aged_cell_id_cache: dict[int, int] = {}
    engines = {
        model: DailyMigrationEngine(
            grid=grid,
            seller_model=model,
            model_version=MODEL_VERSION,
            aged_cell_id_cache=aged_cell_id_cache,
        )
        for model in SELLER_MODEL_ORDER
    }
    first_index = next(
        (
            index
            for index, row in enumerate(daily_rows)
            if row.get("circulating_shares") is not None
            and float(row["circulating_shares"]) > 0
        ),
        None,
    )
    if first_index is None:
        raise ValueError("no daily row has a known positive circulating share count")
    first = daily_rows[first_index]
    first_date = _date(first["trade_date"])
    if initial_snapshots is None:
        if len(daily_rows) - first_index < 2:
            raise ValueError("fewer than two daily rows without a prior terminal state")
        current = {
            model: initial_unknown_snapshot(
                symbol=symbol,
                decision_at=_aware(first_date, 15),
                available_at=_aware(first_date, 15),
                free_float_shares=float(first["circulating_shares"]),
                latent_supply_shares=0.0,
                seller_model=model,
                model_version=MODEL_VERSION,
                grid_version=GRID_VERSION,
                input_snapshot_ids=_snapshot_ids(first),
            )
            for model in SELLER_MODEL_ORDER
        }
        rows_to_process = daily_rows[first_index + 1 :]
    else:
        if set(initial_snapshots) != set(SELLER_MODEL_ORDER):
            raise ValueError("terminal state must contain all seller models")
        staged_years = {_date(row["trade_date"]).year for row in daily_rows}
        if staged_years != {year}:
            raise ValueError(
                "resumed calculation must stage only the target year: "
                f"target={year}, staged={sorted(staged_years)}"
            )
        current = dict(initial_snapshots)
        for model, snapshot in current.items():
            if snapshot.symbol != symbol or snapshot.seller_model != model:
                raise ValueError("terminal state symbol/model mismatch")
            if snapshot.model_version != MODEL_VERSION or snapshot.grid_version != GRID_VERSION:
                raise ValueError("terminal state version mismatch")
            if snapshot.phase != SnapshotPhase.POST:
                raise ValueError("terminal state must be POST")
            if snapshot.trading_date >= first_date:
                raise ValueError("terminal state must precede the first staged day")
        rows_to_process = daily_rows
    codec = _CellCodec()
    emitted_models: set[SellerModel] = set()
    previous_output_states: dict[
        SellerModel,
        dict[int, tuple[int | None, int, TurnoverSensitivity, float]],
    ] = {}
    previous_output_economic_buckets: dict[
        SellerModel, dict[int, int | None]
    ] = {}
    output_rows = _ColumnarOutputBatch()
    output_count = 0
    emitted_day_count = 0
    target_day_count = 0
    fallback_days = 0
    max_mass_error = 0.0
    max_same_day_resale = 0.0
    for row in rows_to_process:
        trading_date = _date(row["trade_date"])
        state_dates = {state.trading_date for state in current.values()}
        if len(state_dates) != 1:
            raise RuntimeError("seller-model states are not aligned to one trading date")
        previous_state_date = next(iter(state_dates))
        if trading_date.year != previous_state_date.year:
            # Annual resume reads the canonical terminal snapshot.  Match that
            # representation in an uninterrupted replay so internal duplicate
            # lots cannot make the two execution paths diverge by float-order.
            current = {
                model: state
                if isinstance(state, ChipSnapshotV2)
                else state.to_snapshot()
                for model, state in current.items()
            }
        input_hard_valid = bool(row.get("hard_valid", False))
        raw_free_float = row.get("circulating_shares")
        missing_free_float = raw_free_float is None or float(raw_free_float) <= 0
        if missing_free_float and input_hard_valid:
            raise ValueError(
                "hard-valid daily row has no positive circulating share count"
            )
        bars = (
            []
            if missing_free_float
            else _minute_bars(minute_by_date.get(trading_date, []), trading_date)
        )
        fallback = False
        if not missing_free_float and not bars and float(row.get("volume") or 0.0) > 0:
            bars = _daily_fallback_bar(row)
            fallback = True
            fallback_days += 1
        decision_at = _aware(trading_date, 15)
        prepared_minute_path = prepare_minute_path(
            grid=grid,
            decision_at=decision_at,
            minute_bars=bars,
        )
        additional_input_snapshot_ids = _snapshot_ids(row)
        expected_free_float_shares = (
            next(iter(current.values())).free_float_shares
            if missing_free_float
            else float(raw_free_float)
        )
        quality_reasons: list[str] = []
        if missing_free_float:
            quality_reasons.append("MISSING_FLOAT_STATE_CARRIED")
        elif fallback:
            quality_reasons.append("DAILY_BAR_FALLBACK")
        if (
            prepared_minute_path.total_volume
            > expected_free_float_shares + tolerance(expected_free_float_shares)
        ):
            prepared_minute_path = _cap_prepared_minute_path(
                prepared_minute_path,
                max_volume=expected_free_float_shares,
            )
            quality_reasons.append("TURNOVER_CAPPED_AT_FLOAT")
        input_quality_reason_codes = tuple(quality_reasons)
        for model in SELLER_MODEL_ORDER:
            previous_post = current[model]
            in_output_year = trading_date.year == year
            emit_day = (
                emit_operators
                and in_output_year
                and (emit_start_date is None or trading_date >= emit_start_date)
            )
            if emit_day and model not in previous_output_states:
                if isinstance(previous_post, ChipSnapshotV2):
                    previous_view, previous_economic = (
                        codec.snapshot_view_and_economic_buckets(previous_post, grid)
                    )
                else:
                    previous_view, _, _, previous_economic = (
                        codec.register_state_and_profile(previous_post, grid)
                    )
                previous_output_states[model] = previous_view
                previous_output_economic_buckets[model] = previous_economic
            inventory_events = _inventory_events(previous_post, row)
            mutable_state = engines[model].advance_packed_warmup_day(
                previous_post=previous_post,
                decision_at=decision_at,
                available_at=decision_at,
                inventory_events=inventory_events,
                expected_free_float_shares=expected_free_float_shares,
                additional_input_snapshot_ids=additional_input_snapshot_ids,
                input_hard_valid=input_hard_valid,
                input_quality_reason_codes=input_quality_reason_codes,
                prepared_minute_path=prepared_minute_path,
                build_transition=emit_day,
            )
            current[model] = mutable_state
            max_mass_error = max(
                max_mass_error, abs(mutable_state.conservation_error)
            )
            if emit_day:
                if writer is None:
                    raise RuntimeError("operator emission requires an output writer")
                transition = mutable_state.last_transition
                if transition is None:
                    raise RuntimeError("output-year transition was not built")
                max_same_day_resale = max(
                    max_same_day_resale, abs(transition.same_day_resale_shares)
                )
                output_row, output_state, output_economic = _output_row(
                    state=mutable_state,
                    transition=transition,
                    fallback=fallback,
                    previous_post=(
                        None
                        if emit_start_date is not None and model not in emitted_models
                        else previous_output_states.get(model)
                    ),
                    previous_economic_buckets=(
                        None
                        if emit_start_date is not None and model not in emitted_models
                        else previous_output_economic_buckets.get(model)
                    ),
                    codec=codec,
                    grid=grid,
                    cash_dividend_per_share=float(
                        row.get("cash_per_share") or 0.0
                    ),
                    share_multiplier=float(row.get("share_multiplier") or 1.0),
                    action_provenance_ids=parse_action_ids(
                        row.get("corporate_action_ids")
                    ),
                    force_checkpoint=(
                        model not in emitted_models
                        or emitted_day_count % CHECKPOINT_INTERVAL_DAYS == 0
                    ),
                    current_price=float(row["close"]),
                )
                output_rows.append(output_row)
                previous_output_states[model] = output_state
                previous_output_economic_buckets[model] = output_economic
                emitted_models.add(model)
                if len(output_rows) >= OUTPUT_ROW_GROUP_SIZE:
                    writer.write_table(
                        output_rows.to_table(),
                        row_group_size=OUTPUT_ROW_GROUP_SIZE,
                    )
                    output_count += len(output_rows)
                    output_rows.clear()
        if emit_operators and trading_date.year == year and (
            emit_start_date is None or trading_date >= emit_start_date
        ):
            emitted_day_count += 1
        if trading_date.year == year:
            target_day_count += 1
    if output_rows:
        if writer is None:
            raise RuntimeError("operator emission requires an output writer")
        writer.write_table(
            output_rows.to_table(),
            row_group_size=OUTPUT_ROW_GROUP_SIZE,
        )
        output_count += len(output_rows)
        output_rows.clear()
    if emit_operators and output_count == 0:
        raise ValueError(f"no output rows for {year}")
    terminal_snapshots = {
        model: state if isinstance(state, ChipSnapshotV2) else state.to_snapshot()
        for model, state in current.items()
    }
    return {
        "symbol": symbol,
        "rows": output_count,
        "input_days": len(daily_rows),
        "processed_days": len(rows_to_process),
        "target_days": target_day_count,
        "emitted_days": emitted_day_count,
        "replayed_prior_year_days": sum(
            _date(row["trade_date"]).year < year for row in rows_to_process
        ),
        "state_resumed": initial_snapshots is not None,
        "fallback_days": fallback_days,
        "max_mass_error": max_mass_error,
        "max_same_day_resale": max_same_day_resale,
        # Exact transitions are persisted for all three models. Strategy-anchor
        # lineage is replayed on demand; rebuilding a throwaway annual tracer
        # here duplicated the same transition walk without producing data.
        "lineage_models": len(emitted_models),
        "cells": len(codec.by_cell_id),
    }, terminal_snapshots


def _part_path(output_root: Path, bucket: int, symbol: str) -> Path:
    return output_root / "parts" / f"bucket={bucket}" / f"{symbol.replace('.', '_')}.parquet"


def _terminal_path(output_root: Path, bucket: int, symbol: str) -> Path:
    return (
        output_root
        / "terminal"
        / f"bucket={bucket}"
        / f"{symbol.replace('.', '_')}.parquet"
    )


def _feature_fact_path(output_root: Path, bucket: int, symbol: str) -> Path:
    return (
        output_root
        / "daily_feature_fact"
        / f"symbol_bucket={bucket}"
        / f"{symbol.replace('.', '_')}.parquet"
    )


def _write_terminal_snapshots(
    path: Path, snapshots: dict[SellerModel, ChipSnapshotV2]
) -> None:
    if set(snapshots) != set(SELLER_MODEL_ORDER):
        raise ValueError("terminal state must contain all seller models")
    rows: list[dict[str, Any]] = []
    for model in SELLER_MODEL_ORDER:
        snapshot = snapshots[model]
        rows.append(
            {
                "storage_version": STORAGE_VERSION,
                "model_version": snapshot.model_version,
                "grid_version": snapshot.grid_version,
                "symbol": snapshot.symbol,
                "trading_date": snapshot.trading_date,
                "decision_at": snapshot.decision_at,
                "effective_at": snapshot.effective_at,
                "available_at": snapshot.available_at,
                "phase": snapshot.phase.value,
                "snapshot_id": snapshot.snapshot_id,
                "seller_model": snapshot.seller_model.value,
                "free_float_shares": snapshot.free_float_shares,
                "latent_supply_shares": snapshot.latent_supply_shares,
                "input_snapshot_ids": list(snapshot.input_snapshot_ids),
                "pit_grade": snapshot.pit_grade,
                "hard_valid": snapshot.hard_valid,
                "quality_reason_codes": list(snapshot.quality_reason_codes),
                "cells": [
                    {
                        "cell_id": cell.cell_id,
                        "cost_bucket_id": cell.cost_bucket_id,
                        "holding_days": cell.holding_days,
                        "sensitivity": cell.sensitivity.value,
                        "acquisition_cost": cell.acquisition_cost,
                        "economic_break_even": cell.economic_break_even,
                        "shares": cell.shares,
                        "initialization_prior_units": cell.initialization_prior_units,
                    }
                    for cell in snapshot.inventory.cells
                ],
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(rows, schema=TERMINAL_SCHEMA),
        path,
        compression="zstd",
        compression_level=PARQUET_COMPRESSION_LEVEL,
        use_dictionary=True,
    )


def _read_terminal_snapshots(
    path: Path,
    symbol: str,
    *,
    before_year: int | None = None,
    expected_year: int | None = None,
) -> dict[SellerModel, ChipSnapshotV2]:
    table = pq.read_table(path, schema=TERMINAL_SCHEMA)
    if table.num_rows != len(SELLER_MODEL_ORDER):
        raise ValueError("terminal state must have exactly three model rows")
    snapshots: dict[SellerModel, ChipSnapshotV2] = {}
    dates: set[date] = set()
    for row in table.to_pylist():
        if row["storage_version"] not in {"chip-operator-log-v11", STORAGE_VERSION}:
            raise ValueError("terminal storage version mismatch")
        if row["model_version"] != MODEL_VERSION or row["grid_version"] != GRID_VERSION:
            raise ValueError("terminal model/grid version mismatch")
        if row["symbol"] != symbol:
            raise ValueError("terminal symbol mismatch")
        model = SellerModel(row["seller_model"])
        if model in snapshots:
            raise ValueError("duplicate terminal seller model")
        trading_date = _date(row["trading_date"])
        if before_year is not None and trading_date >= date(before_year, 1, 1):
            raise ValueError("terminal state does not precede target year")
        dates.add(trading_date)
        cells = tuple(
            InventoryCell.create(
                cost_bucket_id=(
                    None
                    if cell["cost_bucket_id"] is None
                    else int(cell["cost_bucket_id"])
                ),
                holding_days=int(cell["holding_days"]),
                sensitivity=TurnoverSensitivity(cell["sensitivity"]),
                acquisition_cost=cell["acquisition_cost"],
                economic_break_even=cell["economic_break_even"],
                shares=float(cell["shares"]),
                initialization_prior_units=float(cell["initialization_prior_units"]),
            )
            for cell in row["cells"]
        )
        snapshots[model] = ChipSnapshotV2(
            symbol=symbol,
            trading_date=trading_date,
            decision_at=_timestamp(row["decision_at"]),
            effective_at=_timestamp(row["effective_at"]),
            available_at=_timestamp(row["available_at"]),
            phase=SnapshotPhase(row["phase"]),
            snapshot_id=row["snapshot_id"],
            model_version=row["model_version"],
            grid_version=row["grid_version"],
            seller_model=model,
            inventory=SparseChipInventory.canonical(cells),
            free_float_shares=float(row["free_float_shares"]),
            latent_supply_shares=float(row["latent_supply_shares"]),
            input_snapshot_ids=tuple(row["input_snapshot_ids"]),
            pit_grade=row["pit_grade"],
            hard_valid=bool(row["hard_valid"]),
            quality_reason_codes=tuple(row["quality_reason_codes"]),
        )
    if set(snapshots) != set(SELLER_MODEL_ORDER) or len(dates) != 1:
        raise ValueError("terminal state model/date set is incomplete")
    if expected_year is not None and {value.year for value in dates} != {
        expected_year
    }:
        raise ValueError(
            "terminal state must come from the immediately previous year: "
            f"expected={expected_year}, actual={sorted(value.year for value in dates)}"
        )
    return snapshots


def _existing_part_result(
    path: Path,
    symbol: str,
    terminal_path: Path | None = None,
    year: int | None = None,
) -> dict[str, Any] | None:
    """Read only the small scalar columns needed to resume a completed symbol."""
    if not path.exists():
        return None
    try:
        parquet_file = pq.ParquetFile(path)
        if not {"storage_version", "model_version"}.issubset(
            parquet_file.schema_arrow.names
        ):
            return None
        table = pq.read_table(
            path,
            columns=[
                "storage_version",
                "model_version",
                "trade_date",
                "seller_model",
                "minute_fallback",
                "conservation_error_shares",
                "same_day_resale_shares",
            ],
        )
    except (KeyError, OSError, pa.ArrowInvalid):
        return None
    if table.num_rows == 0:
        return None
    values = table.to_pydict()
    if set(values["storage_version"]) != {STORAGE_VERSION}:
        return None
    if set(values["model_version"]) != {MODEL_VERSION}:
        return None
    if terminal_path is not None:
        if year is None:
            raise ValueError("year is required when validating a terminal state")
        try:
            terminal = _read_terminal_snapshots(
                terminal_path, symbol, before_year=year + 1
            )
        except (OSError, ValueError, pa.ArrowInvalid):
            return None
        if {snapshot.trading_date.year for snapshot in terminal.values()} != {year}:
            return None
    fallback_dates = {
        trading_date
        for trading_date, fallback in zip(
            values["trade_date"], values["minute_fallback"], strict=True
        )
        if fallback
    }
    return {
        "symbol": symbol,
        "rows": table.num_rows,
        "input_days": 0,
        "processed_days": 0,
        "target_days": len(set(values["trade_date"])),
        "emitted_days": len(set(values["trade_date"])),
        "replayed_prior_year_days": 0,
        "state_resumed": None,
        "compute_seconds": 0.0,
        "fallback_days": len(fallback_dates),
        "max_mass_error": max(
            (abs(value) for value in values["conservation_error_shares"]),
            default=0.0,
        ),
        "max_same_day_resale": max(
            (abs(value) for value in values["same_day_resale_shares"]),
            default=0.0,
        ),
        "lineage_models": len(set(values["seller_model"])),
        "cells": 0,
        "resumed": True,
    }


def _existing_terminal_result(
    terminal_path: Path, symbol: str, year: int
) -> dict[str, Any] | None:
    if not terminal_path.exists():
        return None
    try:
        snapshots = _read_terminal_snapshots(
            terminal_path,
            symbol,
            before_year=year + 1,
            expected_year=year,
        )
    except (OSError, ValueError, pa.ArrowInvalid):
        return None
    return {
        "symbol": symbol,
        "rows": 0,
        "input_days": 0,
        "processed_days": 0,
        "target_days": 0,
        "emitted_days": 0,
        "replayed_prior_year_days": 0,
        "state_resumed": None,
        "compute_seconds": 0.0,
        "fallback_days": 0,
        "max_mass_error": max(
            abs(snapshot.conservation_error) for snapshot in snapshots.values()
        ),
        "max_same_day_resale": 0.0,
        "lineage_models": len(snapshots),
        "cells": sum(len(snapshot.inventory.cells) for snapshot in snapshots.values()),
        "resumed": True,
    }


def _write_symbol_part(
    *,
    path: Path,
    terminal_path: Path,
    symbol: str,
    daily_rows: list[dict[str, Any]],
    minute_rows: list[dict[str, Any]],
    year: int,
    initial_snapshots: dict[SellerModel, ChipSnapshotV2] | None = None,
    emit_operators: bool = True,
    emit_start_date: date | None = None,
) -> dict[str, Any]:
    output_root = path.parents[2]
    bucket = int(path.parent.name.split("=", 1)[1])
    feature_path = _feature_fact_path(output_root, bucket, symbol)
    resumed = (
        _existing_part_result(path, symbol, terminal_path, year)
        if emit_operators
        else _existing_terminal_result(terminal_path, symbol, year)
    )
    if emit_operators and not feature_path.is_file():
        resumed = None
    if resumed is not None:
        return resumed
    started = time.perf_counter()
    if emit_operators:
        path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp.parquet")
    temp_terminal_path = terminal_path.with_suffix(".tmp.parquet")
    temp_path.unlink(missing_ok=True)
    temp_terminal_path.unlink(missing_ok=True)
    writer = (
        pq.ParquetWriter(
            temp_path,
            OUTPUT_SCHEMA,
            compression="zstd",
            compression_level=PARQUET_COMPRESSION_LEVEL,
            use_dictionary=True,
        )
        if emit_operators
        else None
    )
    gc_was_enabled = gc.isenabled()
    if gc_was_enabled:
        gc.disable()
    try:
        result, terminal_snapshots = _run_symbol(
            symbol,
            daily_rows,
            minute_rows,
            year,
            writer,
            initial_snapshots,
            emit_operators=emit_operators,
            emit_start_date=emit_start_date,
        )
    except Exception:
        if writer is not None:
            writer.close()
        temp_path.unlink(missing_ok=True)
        temp_terminal_path.unlink(missing_ok=True)
        raise
    finally:
        if gc_was_enabled:
            gc.enable()
    if writer is not None:
        writer.close()
    temp_feature_path = feature_path.with_suffix(".tmp.parquet")
    temp_feature_path.unlink(missing_ok=True)
    try:
        if emit_operators:
            build_daily_feature_fact(temp_path, temp_feature_path)
        _write_terminal_snapshots(temp_terminal_path, terminal_snapshots)
        _read_terminal_snapshots(temp_terminal_path, symbol, before_year=year + 1)
    except Exception:
        temp_path.unlink(missing_ok=True)
        temp_terminal_path.unlink(missing_ok=True)
        temp_feature_path.unlink(missing_ok=True)
        raise
    terminal_path.parent.mkdir(parents=True, exist_ok=True)
    temp_terminal_path.replace(terminal_path)
    if emit_operators:
        temp_path.replace(path)
        feature_path.parent.mkdir(parents=True, exist_ok=True)
        temp_feature_path.replace(feature_path)
    result["resumed"] = False
    result["compute_seconds"] = round(time.perf_counter() - started, 3)
    return result


def _run_bucket(
    payload: tuple[
        int,
        int,
        Path,
        Path,
        Path | None,
        float,
        tuple[str, ...],
        bool,
        date | None,
    ]
) -> dict[str, Any]:
    (
        bucket,
        year,
        stage_root,
        output_root,
        resume_root,
        _memory_limit_gb,
        symbols,
        emit_operators,
        emit_start_date,
    ) = payload
    started = time.perf_counter()
    daily_partitions = _symbol_partition_dirs(stage_root, "daily", bucket)
    minute_partitions = _symbol_partition_dirs(stage_root, "minute", bucket)
    prior_symbols = _read_prior_symbols(stage_root)
    selected = sorted(daily_partitions)
    if symbols:
        requested = set(symbols)
        selected = [symbol for symbol in selected if symbol in requested]
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    new_listing_symbols = 0
    for position, symbol in enumerate(selected, start=1):
        part_path = _part_path(output_root, bucket, symbol)
        terminal_path = _terminal_path(output_root, bucket, symbol)
        resumed = (
            _existing_part_result(part_path, symbol, terminal_path, year)
            if emit_operators
            else _existing_terminal_result(terminal_path, symbol, year)
        )
        if emit_operators and not _feature_fact_path(
            output_root, bucket, symbol
        ).is_file():
            resumed = None
        if resumed is not None:
            results.append(resumed)
            continue
        try:
            daily_rows = _read_symbol_partition(daily_partitions[symbol], symbol)
            initial_snapshots = None
            if resume_root is not None:
                previous_terminal = _terminal_path(resume_root, bucket, symbol)
                if previous_terminal.exists():
                    initial_snapshots = _read_terminal_snapshots(
                        previous_terminal,
                        symbol,
                        before_year=year,
                        expected_year=year - 1,
                    )
                elif symbol in prior_symbols:
                    raise FileNotFoundError(
                        "prior-history symbol is missing its adjacent-year terminal state"
                    )
                else:
                    # The stock first appears inside this horizon. Its opening
                    # inventory is unknown cost; do not replay unrelated years.
                    new_listing_symbols += 1
            results.append(
                _write_symbol_part(
                    path=part_path,
                    terminal_path=terminal_path,
                    symbol=symbol,
                    daily_rows=daily_rows,
                    minute_rows=_read_symbol_partition(
                        minute_partitions.get(symbol), symbol
                    ),
                    year=year,
                    initial_snapshots=initial_snapshots,
                    emit_operators=emit_operators,
                    emit_start_date=emit_start_date,
                )
            )
        except Exception as error:
            if os.environ.get("CYQ_RAISE_TASK_ERRORS") == "1":
                raise
            failures.append(
                {"symbol": symbol, "error": f"{type(error).__name__}: {error}"}
            )
        if position % 25 == 0:
            gc.collect()
    return {
        "bucket": bucket,
        "symbols": len(selected),
        "passed": len(results),
        "failed": len(failures),
        "rows": sum(item["rows"] for item in results),
        "input_days": sum(item["input_days"] for item in results),
        "processed_days": sum(item["processed_days"] for item in results),
        "target_days": sum(item["target_days"] for item in results),
        "emitted_days": sum(item["emitted_days"] for item in results),
        "replayed_prior_year_days": sum(
            item["replayed_prior_year_days"] for item in results
        ),
        "state_resumed_symbols": sum(
            item.get("state_resumed") is True for item in results
        ),
        "new_listing_symbols": new_listing_symbols,
        "compute_seconds": round(
            sum(item["compute_seconds"] for item in results), 3
        ),
        "fallback_days": sum(item["fallback_days"] for item in results),
        "max_mass_error": max((item["max_mass_error"] for item in results), default=0.0),
        "max_same_day_resale": max(
            (item["max_same_day_resale"] for item in results), default=0.0
        ),
        "lineage_pass": all(item["lineage_models"] in (0, 3) for item in results),
        "resumed_symbols": sum(bool(item.get("resumed")) for item in results),
        "failures": failures,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def _task_payloads(
    *,
    selected_buckets: list[int],
    year: int,
    stage_root: Path,
    output_root: Path,
    resume_root: Path | None,
    memory_per_worker_gb: float,
    requested_symbols: tuple[str, ...],
    workers: int,
    symbols_per_task: int,
    emit_operators: bool,
    emit_start_date: date | None,
) -> list[
    tuple[
        int,
        int,
        Path,
        Path,
        Path | None,
        float,
        tuple[str, ...],
        bool,
        date | None,
    ]
]:
    """Split physical buckets into dynamic symbol tasks.

    The staged files stay bucket-partitioned, but workers no longer own one
    whole bucket for the entire run.  Shorter tasks let a free worker take work
    from a slower bucket instead of leaving a CPU idle near the end.
    """

    requested = set(requested_symbols)
    payloads: list[
        tuple[
            int,
            int,
            Path,
            Path,
            Path | None,
            float,
            tuple[str, ...],
            bool,
            date | None,
        ]
    ] = []
    for bucket in selected_buckets:
        available = sorted(_symbol_partition_dirs(stage_root, "daily", bucket))
        if requested:
            available = [symbol for symbol in available if symbol in requested]
        if not available:
            continue
        if workers <= 1 or len(available) <= symbols_per_task:
            chunks = [tuple(available)]
        else:
            chunks = [
                tuple(available[start : start + symbols_per_task])
                for start in range(0, len(available), symbols_per_task)
            ]
        payloads.extend(
            (
                bucket,
                year,
                stage_root,
                output_root,
                resume_root,
                memory_per_worker_gb,
                chunk,
                emit_operators,
                emit_start_date,
            )
            for chunk in chunks
        )
    return payloads


def _aggregate_bucket_tasks(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep summary compatibility after dynamic task splitting."""

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        grouped[result["bucket"]].append(result)
    aggregated: list[dict[str, Any]] = []
    summed = (
        "symbols",
        "passed",
        "failed",
        "rows",
        "input_days",
        "processed_days",
        "target_days",
        "emitted_days",
        "replayed_prior_year_days",
        "state_resumed_symbols",
        "new_listing_symbols",
        "compute_seconds",
        "fallback_days",
        "resumed_symbols",
        "elapsed_seconds",
    )
    for bucket, tasks in sorted(grouped.items()):
        item: dict[str, Any] = {"bucket": bucket}
        item.update({key: sum(task[key] for task in tasks) for key in summed})
        item["max_mass_error"] = max(task["max_mass_error"] for task in tasks)
        item["max_same_day_resale"] = max(
            task["max_same_day_resale"] for task in tasks
        )
        item["lineage_pass"] = all(task["lineage_pass"] for task in tasks)
        item["failures"] = [
            failure for task in tasks for failure in task["failures"]
        ]
        item["task_count"] = len(tasks)
        aggregated.append(item)
    return aggregated


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2020)
    parser.add_argument("--warmup-start", type=int, default=2018)
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        help="Stop the target year at this inclusive date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--workers", type=int, default=min(10, max(1, os.cpu_count() or 8))
    )
    parser.add_argument("--buckets", type=int, default=10)
    parser.add_argument("--memory-per-worker-gb", type=float, default=1.5)
    parser.add_argument(
        "--symbols-per-task",
        type=int,
        default=24,
        help="Dynamic scheduling chunk size; smaller chunks reduce idle tail time",
    )
    parser.add_argument("--bucket", type=int)
    parser.add_argument("--symbols", nargs="*", default=[])
    parser.add_argument("--symbols-file", type=Path)
    parser.add_argument("--stage-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--daily-root", type=Path, default=DAILY_ROOT)
    parser.add_argument("--minute-root", type=Path, default=MINUTE_ROOT)
    parser.add_argument(
        "--baostock-delta-file",
        type=Path,
        help="Optional registered raw BaoStock native-5m delta for the target year.",
    )
    parser.add_argument(
        "--research-action-overrides",
        type=Path,
        help="Registered PIT-B reference-price action/float bridge overlay",
    )
    parser.add_argument(
        "--resume-from",
        type=Path,
        help="Previous year's output root containing exact terminal states",
    )
    parser.add_argument(
        "--no-auto-resume",
        action="store_true",
        help="Disable automatic adjacent-year terminal-state discovery",
    )
    parser.add_argument(
        "--terminal-only",
        action="store_true",
        help="Advance all states but persist only exact year-end terminal snapshots.",
    )
    parser.add_argument(
        "--emit-start-date",
        type=date.fromisoformat,
        help="Persist operators only on or after this target-year date.",
    )
    args = parser.parse_args()
    if args.symbols_per_task < 1:
        parser.error("--symbols-per-task must be positive")
    if args.end_date is not None and args.end_date.year != args.year:
        parser.error("--end-date must belong to --year")
    if args.emit_start_date is not None and args.emit_start_date.year != args.year:
        parser.error("--emit-start-date must belong to --year")
    if args.terminal_only and args.emit_start_date is not None:
        parser.error("--terminal-only and --emit-start-date are mutually exclusive")
    started = time.perf_counter()
    selected_buckets = [args.bucket] if args.bucket is not None else list(range(args.buckets))
    if any(bucket < 0 or bucket >= args.buckets for bucket in selected_buckets):
        parser.error("--bucket must be between 0 and --buckets - 1")
    file_symbols = (
        tuple(
            line.strip()
            for line in args.symbols_file.read_text().splitlines()
            if line.strip()
        )
        if args.symbols_file is not None
        else ()
    )
    symbols = tuple(dict.fromkeys((*args.symbols, *file_symbols)))
    output_root = args.output or ROOT / f"data/processed/real_chip_inventory_v2/year={args.year}"
    stage_root = args.stage_root or output_root / "_staging"
    resume_root, resume_mode = _resolve_resume_root(
        output_root=output_root,
        year=args.year,
        warmup_start=args.warmup_start,
        explicit=args.resume_from,
        auto_resume=not args.no_auto_resume,
    )
    stage_warmup_start = args.year if resume_root is not None else args.warmup_start
    _stage_inputs(
        year=args.year,
        warmup_start=stage_warmup_start,
        buckets=args.buckets,
        stage_root=stage_root,
        symbols=symbols,
        prior_history_start=args.warmup_start if resume_root is not None else None,
        end_date=args.end_date,
        daily_root=args.daily_root,
        minute_root=args.minute_root,
        research_action_overrides=args.research_action_overrides,
        baostock_delta_file=args.baostock_delta_file,
    )
    payloads = _task_payloads(
        selected_buckets=selected_buckets,
        year=args.year,
        stage_root=stage_root,
        output_root=output_root,
        resume_root=resume_root,
        memory_per_worker_gb=args.memory_per_worker_gb,
        requested_symbols=symbols,
        workers=args.workers,
        symbols_per_task=args.symbols_per_task,
        emit_operators=not args.terminal_only,
        emit_start_date=args.emit_start_date,
    )
    if not payloads:
        parser.error("no staged symbols matched the requested scope")
    results: list[dict[str, Any]] = []
    worker_count = min(args.workers, len(payloads))
    if worker_count == 1:
        for payload in payloads:
            result = _run_bucket(payload)
            results.append(result)
            print(
                json.dumps(
                    {
                        "bucket": result["bucket"],
                        "passed": result["passed"],
                        "failed": result["failed"],
                        "elapsed_seconds": result["elapsed_seconds"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    else:
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(_run_bucket, payload): payload[0] for payload in payloads
            }
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                print(
                    json.dumps(
                        {
                            "bucket": result["bucket"],
                            "passed": result["passed"],
                            "failed": result["failed"],
                            "elapsed_seconds": result["elapsed_seconds"],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
    results.sort(key=lambda item: (item["bucket"], item["symbols"]))
    bucket_results = _aggregate_bucket_tasks(results)
    operator_index = (
        None if args.terminal_only else build_operator_symbol_index(output_root)
    )
    passed = sum(item["passed"] for item in results)
    total = sum(item["symbols"] for item in results)
    evidence = {
        **semantic_fingerprint_fields(),
        "status": "PASS" if passed / max(total, 1) >= 0.95 else "FAIL",
        "year": args.year,
        "end_date": None if args.end_date is None else args.end_date.isoformat(),
        "warmup_start": args.warmup_start,
        "stage_warmup_start": stage_warmup_start,
        "resume_from": None if resume_root is None else str(resume_root),
        "resume_mode": resume_mode,
        "daily_root": str(args.daily_root.resolve()),
        "minute_root": str(args.minute_root.resolve()),
        "research_action_overrides": (
            None
            if args.research_action_overrides is None
            else str(args.research_action_overrides.resolve())
        ),
        "research_action_overrides_sha256": _file_sha256(
            args.research_action_overrides
        ),
        "baostock_delta_file": (
            None
            if args.baostock_delta_file is None
            else str(args.baostock_delta_file.resolve())
        ),
        "baostock_delta_sha256": _file_sha256(args.baostock_delta_file),
        "terminal_only": args.terminal_only,
        "emit_start_date": (
            None if args.emit_start_date is None else args.emit_start_date.isoformat()
        ),
        "workers": worker_count,
        "task_count": len(payloads),
        "symbols_per_task": args.symbols_per_task,
        "symbols": total,
        "passed_symbols": passed,
        "coverage": passed / max(total, 1),
        "rows": sum(item["rows"] for item in results),
        "input_days": sum(item["input_days"] for item in results),
        "processed_days": sum(item["processed_days"] for item in results),
        "target_days": sum(item["target_days"] for item in results),
        "emitted_days": sum(item["emitted_days"] for item in results),
        "replayed_prior_year_days": sum(
            item["replayed_prior_year_days"] for item in results
        ),
        "state_resumed_symbols": sum(
            item["state_resumed_symbols"] for item in results
        ),
        "new_listing_symbols": sum(item["new_listing_symbols"] for item in results),
        "compute_seconds": round(
            sum(item["compute_seconds"] for item in results), 3
        ),
        "fallback_days": sum(item["fallback_days"] for item in results),
        "max_mass_error": max(item["max_mass_error"] for item in results),
        "max_same_day_resale": max(item["max_same_day_resale"] for item in results),
        "lineage_pass": all(item["lineage_pass"] for item in results),
        "resumed_symbols": sum(item["resumed_symbols"] for item in results),
        "output_glob": (
            None
            if args.terminal_only
            else str(output_root / "parts" / "bucket=*" / "*.parquet")
        ),
        "terminal_glob": str(
            output_root / "terminal" / "bucket=*" / "*.parquet"
        ),
        "cell_id_encoding": "uint64-hashed-cost-age-sensitivity-economic-v2",
        "chip_state_schema_version": CHIP_STATE_SCHEMA_VERSION,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "operator_symbol_index": None if operator_index is None else str(operator_index),
        "buckets": bucket_results,
    }
    summary_path = output_root / "summary.json"
    summary_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: evidence[key] for key in ("status", "coverage", "rows", "elapsed_seconds")}, ensure_ascii=False))
    print(summary_path)
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
