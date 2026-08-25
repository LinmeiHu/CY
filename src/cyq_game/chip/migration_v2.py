"""Causal minute-path migration for the strategy-independent chip inventory.

The engine consumes one immutable previous-day POST inventory.  Corporate
actions and supply events create the current PRE inventory.  Every one-minute
sale is then allocated only against that fixed PRE pool; purchases created by
those sales are accumulated separately and cannot be sold again on the same
day.  This is the T+1 boundary required by the A-share model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from itertools import pairwise
from typing import cast

import numpy as np
import numpy.typing as npt

from cyq_game.chip._migration_kernel import (
    disposition_path_no_saturation,
    stable_sum,
    stable_weighted_sum,
)
from cyq_game.chip.price_coordinate import rebase_economic_price
from cyq_game.chip.state_v2 import (
    ChipSnapshotV2,
    ChipStateContractError,
    InventoryCell,
    OriginSurvivalTransition,
    SellerModel,
    SnapshotPhase,
    SparseChipInventory,
    TurnoverSensitivity,
    require_aware,
    stable_cell_id,
    stable_id,
    tolerance,
)

DEFAULT_MAX_HOLDING_DAYS = 180

FloatArray = npt.NDArray[np.float64]
Int64Array = npt.NDArray[np.int64]
Int16Array = npt.NDArray[np.int16]
Int8Array = npt.NDArray[np.int8]
BoolArray = npt.NDArray[np.bool_]


def _active_sticky_path_no_saturation(
    original: FloatArray,
    volumes: FloatArray,
) -> tuple[FloatArray, bool]:
    """Deplete three sensitivity groups without tiny NumPy-array operations."""

    active = float(original[0])
    neutral = float(original[1])
    sticky = float(original[2])
    for requested in volumes:
        if requested == 0.0:
            continue
        active_weight = 2.0 * active
        neutral_weight = neutral
        sticky_weight = 0.25 * sticky
        total_weight = active_weight + neutral_weight + sticky_weight
        if total_weight <= 0.0:
            return original.copy(), False
        scale = float(requested) / total_weight
        active_sale = active_weight * scale
        neutral_sale = neutral_weight * scale
        sticky_sale = sticky_weight * scale
        if active_sale > active or neutral_sale > neutral or sticky_sale > sticky:
            return original.copy(), False
        active -= active_sale
        neutral -= neutral_sale
        sticky -= sticky_sale
    return np.asarray((active, neutral, sticky), dtype=np.float64), True


@dataclass(frozen=True)
class StableLogPriceGrid:
    """Versioned global log grid whose integer bucket identity never shifts."""

    reference_price: float
    step_pct: float
    grid_version: str

    def __post_init__(self) -> None:
        if not math.isfinite(self.reference_price) or self.reference_price <= 0:
            raise ChipStateContractError("grid reference_price must be positive")
        if not math.isfinite(self.step_pct) or not 0 < self.step_pct < 1:
            raise ChipStateContractError("grid step_pct must be in (0, 1)")
        if not self.grid_version:
            raise ChipStateContractError("grid_version cannot be empty")

    def bucket_for_price(self, price: float) -> int:
        if not math.isfinite(price) or price <= 0:
            raise ChipStateContractError("price must be finite and positive")
        raw = math.log(price / self.reference_price) / math.log1p(self.step_pct)
        return math.floor(raw + 0.5)

    def price_for_bucket(self, bucket_id: int) -> float:
        return self.reference_price * (1 + self.step_pct) ** bucket_id


# Economic break-even differs from a market price: cumulative cash distributions can
# legitimately move it to zero or below.  Persisted operator logs use signed int32
# buckets, so reserve the minimum value for the whole non-positive half-line.  All
# observable A-share prices are positive, making 0.0 an exact decision-equivalent
# decode for profit/loss comparisons without fabricating a negative market price.
NONPOSITIVE_ECONOMIC_BUCKET = -(1 << 31)


def bucket_for_economic_break_even(grid: StableLogPriceGrid, value: float) -> int:
    if not math.isfinite(value):
        raise ChipStateContractError("economic break-even must be finite")
    if value <= 0:
        return NONPOSITIVE_ECONOMIC_BUCKET
    bucket = grid.bucket_for_price(value)
    if not NONPOSITIVE_ECONOMIC_BUCKET < bucket < (1 << 31):
        raise ChipStateContractError("economic break-even bucket exceeds int32 storage")
    return bucket


def economic_break_even_for_bucket(grid: StableLogPriceGrid, bucket_id: int) -> float:
    if bucket_id == NONPOSITIVE_ECONOMIC_BUCKET:
        return 0.0
    return grid.price_for_bucket(bucket_id)


@dataclass(frozen=True)
class MinuteBar:
    """One causally available one-minute price-path observation."""

    timestamp: datetime
    available_at: datetime
    snapshot_id: str
    open: float
    high: float
    low: float
    close: float
    volume_shares: float
    vwap: float | None = None

    def __post_init__(self) -> None:
        require_aware(self.timestamp, "minute timestamp")
        require_aware(self.available_at, "minute available_at")
        if self.available_at < self.timestamp:
            raise ChipStateContractError("minute data cannot be available before its bar")
        if not self.snapshot_id:
            raise ChipStateContractError("minute snapshot_id cannot be empty")
        prices = (self.open, self.high, self.low, self.close)
        if any(not math.isfinite(value) or value <= 0 for value in prices):
            raise ChipStateContractError("minute OHLC must be finite and positive")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ChipStateContractError("minute OHLC range is inconsistent")
        if self.low > self.high:
            raise ChipStateContractError("minute low cannot exceed high")
        if not math.isfinite(self.volume_shares) or self.volume_shares < 0:
            raise ChipStateContractError("minute volume must be finite and non-negative")
        if self.vwap is not None:
            if not math.isfinite(self.vwap) or self.vwap <= 0:
                raise ChipStateContractError("minute VWAP must be finite and positive")
            if self.vwap < self.low - tolerance(self.low) or self.vwap > self.high + tolerance(
                self.high
            ):
                raise ChipStateContractError("minute VWAP must lie inside the OHLC range")

    @property
    def migration_price(self) -> float:
        """Use observed VWAP when present; otherwise use the bar's typical price."""

        if self.vwap is not None:
            return self.vwap
        return (self.open + self.high + self.low + self.close) / 4


@dataclass(frozen=True)
class PreparedMinutePath:
    """Day-level facts shared by every seller model.

    Seller depletion remains model-specific.  Only causal validation and the
    observed buyer path are prepared once, avoiding the same price-grid and
    input-lineage work for all three hypotheses.
    """

    decision_at: datetime
    grid_version: str
    minute_bars: tuple[MinuteBar, ...]
    purchases: tuple[tuple[int, float, float], ...]
    # Buyer inventory depends only on the observed minute path, not on the
    # seller hypothesis.  Aggregate it once so the three seller models do not
    # repeat the same ~240-bar dictionary work.
    bucket_purchases: tuple[tuple[int, float, float], ...]
    total_volume: float
    snapshot_ids: tuple[str, ...]
    latest_timestamp: datetime | None
    # These arrays are immutable by convention and deliberately excluded from
    # dataclass equality.  All three seller models consume the same observed
    # path, so materialising them once avoids six repeated stock-day scans.
    prices: FloatArray = field(repr=False, compare=False)
    volumes: FloatArray = field(repr=False, compare=False)
    purchase_bucket_ids: Int64Array = field(repr=False, compare=False)
    purchase_prices: FloatArray = field(repr=False, compare=False)
    purchase_volumes: FloatArray = field(repr=False, compare=False)


def _merge_sorted_unique(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[str, ...]:
    """Merge already ordered lineage ids without rebuilding and sorting a set."""

    if not left:
        return right
    if not right:
        return left
    merged: list[str] = []
    left_index = 0
    right_index = 0
    while left_index < len(left) and right_index < len(right):
        left_value = left[left_index]
        right_value = right[right_index]
        if left_value < right_value:
            value = left_value
            left_index += 1
        elif right_value < left_value:
            value = right_value
            right_index += 1
        else:
            value = left_value
            left_index += 1
            right_index += 1
        if not merged or merged[-1] != value:
            merged.append(value)
    for remaining in left[left_index:]:
        if not merged or merged[-1] != remaining:
            merged.append(remaining)
    for remaining in right[right_index:]:
        if not merged or merged[-1] != remaining:
            merged.append(remaining)
    return tuple(merged)


def prepare_minute_path(
    *,
    grid: StableLogPriceGrid,
    decision_at: datetime,
    minute_bars: tuple[MinuteBar, ...],
) -> PreparedMinutePath:
    """Validate and bucket one trading day's observed minute path once."""

    require_aware(decision_at, "decision_at")
    bar_times = tuple(bar.timestamp for bar in minute_bars)
    previous_time: datetime | None = None
    for bar_time in bar_times:
        if previous_time is not None and bar_time <= previous_time:
            raise ChipStateContractError("minute bars must be unique and time sorted")
        previous_time = bar_time
    for bar in minute_bars:
        if bar.timestamp.date() != decision_at.date():
            raise ChipStateContractError("minute bar is outside the trading date")
        if bar.timestamp > decision_at or bar.available_at > decision_at:
            raise ChipStateContractError("minute bar uses information after decision_at")
    purchases: list[tuple[int, float, float]] = []
    bucket_totals: dict[int, list[float]] = {}
    prices = np.empty(len(minute_bars), dtype=np.float64)
    volumes = np.empty(len(minute_bars), dtype=np.float64)
    for index, bar in enumerate(minute_bars):
        price = bar.migration_price
        prices[index] = price
        volumes[index] = bar.volume_shares
        if bar.volume_shares <= 0:
            continue
        bucket_id = grid.bucket_for_price(price)
        purchases.append((bucket_id, price, bar.volume_shares))
        totals = bucket_totals.setdefault(bucket_id, [0.0, 0.0])
        totals[0] += bar.volume_shares
        totals[1] += bar.volume_shares * price
    snapshot_ids = tuple(dict.fromkeys(bar.snapshot_id for bar in minute_bars))
    if any(current <= previous for previous, current in pairwise(snapshot_ids)):
        snapshot_ids = tuple(sorted(set(snapshot_ids)))
    bucket_purchases = tuple(
        (bucket_id, totals[1] / totals[0], totals[0]) for bucket_id, totals in bucket_totals.items()
    )
    return PreparedMinutePath(
        decision_at=decision_at,
        grid_version=grid.grid_version,
        minute_bars=minute_bars,
        purchases=tuple(purchases),
        bucket_purchases=bucket_purchases,
        total_volume=math.fsum(volumes),
        # Strictly increasing bar timestamps make the builder's timestamp-based
        # ids unique and ordered.  Preserve that order instead of sorting the
        # same ~240 ids again for every stock-day.
        snapshot_ids=snapshot_ids,
        latest_timestamp=max(bar_times) if bar_times else None,
        prices=prices,
        volumes=volumes,
        purchase_bucket_ids=np.fromiter((item[0] for item in bucket_purchases), dtype=np.int64),
        purchase_prices=np.fromiter((item[1] for item in bucket_purchases), dtype=np.float64),
        purchase_volumes=np.fromiter((item[2] for item in bucket_purchases), dtype=np.float64),
    )


class InventoryEventKind(StrEnum):
    CASH_DIVIDEND = "CASH_DIVIDEND"
    SPLIT = "SPLIT"
    FLOAT_ADD_KNOWN = "FLOAT_ADD_KNOWN"
    FLOAT_ADD_UNKNOWN = "FLOAT_ADD_UNKNOWN"
    FLOAT_REMOVE_EXPLICIT = "FLOAT_REMOVE_EXPLICIT"
    LATENT_SUPPLY_CHANGE = "LATENT_SUPPLY_CHANGE"


@dataclass(frozen=True)
class InventoryEvent:
    """One PIT inventory bridge applied before the current-day PRE snapshot."""

    event_id: str
    kind: InventoryEventKind
    effective_at: datetime
    available_at: datetime
    snapshot_id: str
    cash_per_share: float = 0.0
    share_ratio: float = 1.0
    shares: float = 0.0
    issue_price: float | None = None
    sensitivity: TurnoverSensitivity = TurnoverSensitivity.NEUTRAL
    source_removals: tuple[tuple[int, float], ...] = ()
    latent_supply_delta: float = 0.0

    def __post_init__(self) -> None:
        require_aware(self.effective_at, "event effective_at")
        require_aware(self.available_at, "event available_at")
        if self.available_at > self.effective_at:
            # Publication may occur before or on the effective time, never after
            # if the event is to be admitted to that day's PRE inventory.
            raise ChipStateContractError("inventory event was unavailable at effective_at")
        if not self.event_id or not self.snapshot_id:
            raise ChipStateContractError("inventory event identity cannot be empty")
        numeric = (
            self.cash_per_share,
            self.share_ratio,
            self.shares,
            self.latent_supply_delta,
        )
        if any(not math.isfinite(value) for value in numeric):
            raise ChipStateContractError("inventory event numeric fields must be finite")
        if self.kind == InventoryEventKind.CASH_DIVIDEND:
            if self.cash_per_share < 0:
                raise ChipStateContractError("cash dividend cannot be negative")
        elif self.kind == InventoryEventKind.SPLIT:
            if self.share_ratio <= 0:
                raise ChipStateContractError("split ratio must be positive")
        elif self.kind == InventoryEventKind.FLOAT_ADD_KNOWN:
            if self.shares <= 0 or self.issue_price is None or self.issue_price <= 0:
                raise ChipStateContractError("known float addition needs shares and issue price")
        elif self.kind == InventoryEventKind.FLOAT_ADD_UNKNOWN:
            if self.shares <= 0 or self.issue_price is not None:
                raise ChipStateContractError("unknown float addition must not invent a cost")
        elif self.kind == InventoryEventKind.FLOAT_REMOVE_EXPLICIT:
            if self.shares <= 0 or not self.source_removals:
                raise ChipStateContractError("float removal requires explicit source lots")
            source_ids = tuple(source for source, _ in self.source_removals)
            if source_ids != tuple(sorted(set(source_ids))):
                raise ChipStateContractError("float-removal source ids must be unique and sorted")
            if any(amount <= 0 or not math.isfinite(amount) for _, amount in self.source_removals):
                raise ChipStateContractError("float-removal amounts must be positive")
            removed = math.fsum(amount for _, amount in self.source_removals)
            if abs(removed - self.shares) > tolerance(self.shares):
                raise ChipStateContractError("explicit removals do not sum to event shares")
        elif self.kind == InventoryEventKind.LATENT_SUPPLY_CHANGE:
            if self.latent_supply_delta == 0:
                raise ChipStateContractError("latent supply change cannot be zero")


@dataclass(slots=True)
class _WorkingLot:
    """Mutable lot used only inside one deterministic daily migration."""

    source_cell_id: int | None
    cost_bucket_id: int | None
    holding_days: int
    sensitivity: TurnoverSensitivity
    acquisition_cost: float | None
    economic_break_even: float | None
    shares: float
    initialization_prior_units: float
    lineage_denominator_shares: float
    cell_id: int = field(init=False)

    def __post_init__(self) -> None:
        self.refresh_cell_id()

    def refresh_cell_id(self) -> None:
        """Recompute when a causal state coordinate changes."""

        self.cell_id = stable_cell_id(
            cost_bucket_id=self.cost_bucket_id,
            holding_days=self.holding_days,
            sensitivity=self.sensitivity,
            economic_break_even=self.economic_break_even,
        )

    def to_cell(self) -> InventoryCell:
        return InventoryCell(
            cell_id=self.cell_id,
            cost_bucket_id=self.cost_bucket_id,
            holding_days=self.holding_days,
            sensitivity=self.sensitivity,
            acquisition_cost=self.acquisition_cost,
            economic_break_even=self.economic_break_even,
            shares=self.shares,
            initialization_prior_units=self.initialization_prior_units,
        )


_UNKNOWN_BUCKET_ID = np.iinfo(np.int64).min
_SENSITIVITY_BY_CODE = (
    TurnoverSensitivity.ACTIVE,
    TurnoverSensitivity.NEUTRAL,
    TurnoverSensitivity.STICKY,
)


def _sensitivity_code(value: TurnoverSensitivity) -> int:
    if value == TurnoverSensitivity.ACTIVE:
        return 0
    if value == TurnoverSensitivity.NEUTRAL:
        return 1
    return 2


@dataclass(slots=True, init=False)
class _PackedWorkingLots:
    """Persistent structure-of-arrays inventory used on ordinary trading days.

    This is deliberately an internal execution representation.  Immutable
    snapshots and company-action processing keep using the exact domain
    objects at their boundaries, while the multi-year warm-up loop carries
    these arrays directly from one day to the next.
    """

    _cell_ids: Int64Array
    _cost_bucket_ids: Int64Array
    _holding_days: Int16Array
    _sensitivity_codes: Int8Array
    _acquisition_costs: FloatArray
    _economic_break_evens: FloatArray
    _shares: FloatArray
    _initialization_prior_units: FloatArray
    _size: int
    _cell_ids_current: bool

    _ARRAY_NAMES = (
        "cell_ids",
        "cost_bucket_ids",
        "holding_days",
        "sensitivity_codes",
        "acquisition_costs",
        "economic_break_evens",
        "shares",
        "initialization_prior_units",
    )

    def __init__(
        self,
        *,
        cell_ids: Int64Array,
        cost_bucket_ids: Int64Array,
        holding_days: Int16Array,
        sensitivity_codes: Int8Array,
        acquisition_costs: FloatArray,
        economic_break_evens: FloatArray,
        shares: FloatArray,
        initialization_prior_units: FloatArray,
    ) -> None:
        arrays = (
            cell_ids,
            cost_bucket_ids,
            holding_days,
            sensitivity_codes,
            acquisition_costs,
            economic_break_evens,
            shares,
            initialization_prior_units,
        )
        size = int(shares.size)
        if any(array.ndim != 1 or int(array.size) != size for array in arrays):
            raise ChipStateContractError("packed inventory columns must be aligned")
        capacity = max(16, size + max(16, size // 4))
        for name, source in zip(self._ARRAY_NAMES, arrays, strict=True):
            source_array = cast(npt.NDArray[np.generic], source)
            target = np.empty(capacity, dtype=source_array.dtype)
            target[:size] = source_array
            setattr(self, f"_{name}", target)
        self._size = size
        self._cell_ids_current = True

    @property
    def cell_ids(self) -> Int64Array:
        return self._cell_ids[: self._size]

    @property
    def cost_bucket_ids(self) -> Int64Array:
        return self._cost_bucket_ids[: self._size]

    @property
    def holding_days(self) -> Int16Array:
        return self._holding_days[: self._size]

    @property
    def sensitivity_codes(self) -> Int8Array:
        return self._sensitivity_codes[: self._size]

    @property
    def acquisition_costs(self) -> FloatArray:
        return self._acquisition_costs[: self._size]

    @property
    def economic_break_evens(self) -> FloatArray:
        return self._economic_break_evens[: self._size]

    @property
    def shares(self) -> FloatArray:
        return self._shares[: self._size]

    @property
    def initialization_prior_units(self) -> FloatArray:
        return self._initialization_prior_units[: self._size]

    def __len__(self) -> int:
        return self._size

    @property
    def capacity(self) -> int:
        return int(self._shares.size)

    def _ensure_capacity(self, required: int) -> None:
        if required <= self.capacity:
            return
        capacity = max(required, self.capacity + max(16, self.capacity // 2))
        for name in self._ARRAY_NAMES:
            source = getattr(self, f"_{name}")
            target = np.empty(capacity, dtype=source.dtype)
            target[: self._size] = source[: self._size]
            setattr(self, f"_{name}", target)

    @classmethod
    def from_cells(cls, cells: tuple[InventoryCell, ...]) -> _PackedWorkingLots:
        return cls(
            cell_ids=np.fromiter(
                (
                    stable_cell_id(
                        cost_bucket_id=cell.cost_bucket_id,
                        holding_days=cell.holding_days,
                        sensitivity=cell.sensitivity,
                        economic_break_even=cell.economic_break_even,
                    )
                    for cell in cells
                ),
                dtype=np.int64,
            ),
            cost_bucket_ids=np.fromiter(
                (
                    _UNKNOWN_BUCKET_ID if cell.cost_bucket_id is None else cell.cost_bucket_id
                    for cell in cells
                ),
                dtype=np.int64,
            ),
            holding_days=np.fromiter((cell.holding_days for cell in cells), dtype=np.int16),
            sensitivity_codes=np.fromiter(
                (_sensitivity_code(cell.sensitivity) for cell in cells),
                dtype=np.int8,
            ),
            acquisition_costs=np.fromiter(
                (
                    np.nan if cell.acquisition_cost is None else cell.acquisition_cost
                    for cell in cells
                ),
                dtype=np.float64,
            ),
            economic_break_evens=np.fromiter(
                (
                    np.nan if cell.economic_break_even is None else cell.economic_break_even
                    for cell in cells
                ),
                dtype=np.float64,
            ),
            shares=np.fromiter((cell.shares for cell in cells), dtype=np.float64),
            initialization_prior_units=np.fromiter(
                (cell.initialization_prior_units for cell in cells),
                dtype=np.float64,
            ),
        )

    @classmethod
    def from_working_lots(cls, lots: list[_WorkingLot]) -> _PackedWorkingLots:
        positive = [lot for lot in lots if lot.shares > 0]
        return cls(
            cell_ids=np.fromiter((lot.cell_id for lot in positive), dtype=np.int64),
            cost_bucket_ids=np.fromiter(
                (
                    _UNKNOWN_BUCKET_ID if lot.cost_bucket_id is None else lot.cost_bucket_id
                    for lot in positive
                ),
                dtype=np.int64,
            ),
            holding_days=np.fromiter((lot.holding_days for lot in positive), dtype=np.int16),
            sensitivity_codes=np.fromiter(
                (_sensitivity_code(lot.sensitivity) for lot in positive),
                dtype=np.int8,
            ),
            acquisition_costs=np.fromiter(
                (
                    np.nan if lot.acquisition_cost is None else lot.acquisition_cost
                    for lot in positive
                ),
                dtype=np.float64,
            ),
            economic_break_evens=np.fromiter(
                (
                    np.nan if lot.economic_break_even is None else lot.economic_break_even
                    for lot in positive
                ),
                dtype=np.float64,
            ),
            shares=np.fromiter((lot.shares for lot in positive), dtype=np.float64),
            initialization_prior_units=np.fromiter(
                (lot.initialization_prior_units for lot in positive),
                dtype=np.float64,
            ),
        )

    def append(self, other: _PackedWorkingLots) -> None:
        if len(other) == 0:
            return
        start = self._size
        stop = start + len(other)
        self._ensure_capacity(stop)
        for name in self._ARRAY_NAMES:
            getattr(self, f"_{name}")[start:stop] = getattr(other, name)
        self._size = stop
        self._cell_ids_current = self._cell_ids_current and other._cell_ids_current

    def refresh_cell_ids(self) -> None:
        """Materialize stable ids only at a public/lineage boundary.

        During warm-up the three integer dimensions are authoritative.  Hashing
        every surviving lot after every daily age increment is pure repeated
        work; one materialization restores the exact public ids when output or
        lineage is requested.
        """

        if self._cell_ids_current:
            return
        size = self._size
        if size == 0:
            self._cell_ids_current = True
            return
        dimensions = np.empty(
            size,
            dtype=[
                ("bucket", np.int64),
                ("holding", np.int16),
                ("sensitivity", np.int8),
                ("economic", np.float64),
            ],
        )
        dimensions["bucket"] = self._cost_bucket_ids[:size]
        dimensions["holding"] = self._holding_days[:size]
        dimensions["sensitivity"] = self._sensitivity_codes[:size]
        dimensions["economic"] = self._economic_break_evens[:size]
        unique_dimensions, inverse = np.unique(dimensions, return_inverse=True)
        unique_ids = np.fromiter(
            (
                stable_cell_id(
                    cost_bucket_id=(
                        None if int(bucket) == _UNKNOWN_BUCKET_ID else int(bucket)
                    ),
                    holding_days=int(holding_days),
                    sensitivity=_SENSITIVITY_BY_CODE[int(sensitivity_code)],
                    economic_break_even=(
                        None
                        if int(bucket) == _UNKNOWN_BUCKET_ID
                        else float(economic_break_even)
                    ),
                )
                for bucket, holding_days, sensitivity_code, economic_break_even in unique_dimensions
            ),
            dtype=np.int64,
            count=int(unique_dimensions.shape[0]),
        )
        self._cell_ids[:size] = unique_ids[inverse]
        self._cell_ids_current = True

    def append_purchases(
        self,
        minute_path: PreparedMinutePath,
        *,
        seller_model: SellerModel,
        active_purchase_fraction: float,
    ) -> None:
        """Append the shared buyer batch without Python lot construction."""

        bucket_count = int(minute_path.purchase_bucket_ids.size)
        if bucket_count == 0:
            return
        multiplier = 2 if seller_model == SellerModel.ACTIVE_STICKY else 1
        start = self._size
        stop = start + bucket_count * multiplier
        self._ensure_capacity(stop)
        sensitivity_codes: Int8Array
        if multiplier == 1:
            bucket_ids = minute_path.purchase_bucket_ids
            prices = minute_path.purchase_prices
            volumes = minute_path.purchase_volumes
            sensitivity_codes = np.full(bucket_count, 1, dtype=np.int8)
        else:
            bucket_ids = np.repeat(minute_path.purchase_bucket_ids, 2)
            prices = np.repeat(minute_path.purchase_prices, 2)
            volumes = np.empty(bucket_count * 2, dtype=np.float64)
            volumes[0::2] = minute_path.purchase_volumes * active_purchase_fraction
            volumes[1::2] = minute_path.purchase_volumes * (1.0 - active_purchase_fraction)
            sensitivity_codes = np.tile(np.asarray([0, 2], dtype=np.int8), bucket_count)
            positive = volumes > 0
            bucket_ids = bucket_ids[positive]
            prices = prices[positive]
            volumes = volumes[positive]
            sensitivity_codes = sensitivity_codes[positive]
            stop = start + int(volumes.size)
        count = stop - start
        self._cost_bucket_ids[start:stop] = bucket_ids
        self._holding_days[start:stop] = 0
        self._sensitivity_codes[start:stop] = sensitivity_codes
        self._acquisition_costs[start:stop] = prices
        self._economic_break_evens[start:stop] = prices
        self._shares[start:stop] = volumes
        self._initialization_prior_units[start:stop] = 0.0
        if self._cell_ids_current:
            self._cell_ids[start:stop] = np.fromiter(
                (
                    stable_cell_id(
                        cost_bucket_id=int(bucket_ids[index]),
                        holding_days=0,
                        sensitivity=_SENSITIVITY_BY_CODE[int(sensitivity_codes[index])],
                        economic_break_even=float(prices[index]),
                    )
                    for index in range(count)
                ),
                dtype=np.int64,
                count=count,
            )
        else:
            self._cell_ids[start:stop] = 0
        self._size = stop

    def retain(self, mask: BoolArray) -> None:
        if mask.ndim != 1 or int(mask.size) != self._size:
            raise ChipStateContractError("packed inventory retain mask is misaligned")
        retained = int(np.count_nonzero(mask))
        for name in self._ARRAY_NAMES:
            backing = getattr(self, f"_{name}")
            backing[:retained] = backing[: self._size][mask]
        self._size = retained

    def to_working_lots(self) -> list[_WorkingLot]:
        result: list[_WorkingLot] = []
        for index in range(len(self)):
            bucket = int(self.cost_bucket_ids[index])
            known = bucket != _UNKNOWN_BUCKET_ID
            result.append(
                _WorkingLot(
                    source_cell_id=None,
                    cost_bucket_id=bucket if known else None,
                    holding_days=int(self.holding_days[index]),
                    sensitivity=_SENSITIVITY_BY_CODE[int(self.sensitivity_codes[index])],
                    acquisition_cost=(float(self.acquisition_costs[index]) if known else None),
                    economic_break_even=(
                        float(self.economic_break_evens[index]) if known else None
                    ),
                    shares=float(self.shares[index]),
                    initialization_prior_units=float(self.initialization_prior_units[index]),
                    lineage_denominator_shares=0.0,
                )
            )
        return result

    def to_cells(self) -> tuple[InventoryCell, ...]:
        self.refresh_cell_ids()
        cells: list[InventoryCell] = []
        for index in range(len(self)):
            bucket = int(self.cost_bucket_ids[index])
            known = bucket != _UNKNOWN_BUCKET_ID
            cells.append(
                InventoryCell(
                    cell_id=stable_cell_id(
                        cost_bucket_id=bucket if known else None,
                        holding_days=int(self.holding_days[index]),
                        sensitivity=_SENSITIVITY_BY_CODE[int(self.sensitivity_codes[index])],
                        economic_break_even=(
                            float(self.economic_break_evens[index]) if known else None
                        ),
                    ),
                    cost_bucket_id=bucket if known else None,
                    holding_days=int(self.holding_days[index]),
                    sensitivity=_SENSITIVITY_BY_CODE[int(self.sensitivity_codes[index])],
                    acquisition_cost=(float(self.acquisition_costs[index]) if known else None),
                    economic_break_even=(
                        float(self.economic_break_evens[index]) if known else None
                    ),
                    shares=float(self.shares[index]),
                    initialization_prior_units=float(self.initialization_prior_units[index]),
                )
            )
        return tuple(cells)


def _canonicalize_working_lots(lots: list[_WorkingLot]) -> list[_WorkingLot]:
    """Aggregate an EOD working inventory while reusing existing lot objects.

    The previous implementation sorted every lot and rebuilt every surviving
    cell on every warm-up day.  Most cells are already unique; only aged-cap
    collisions and today's purchases need aggregation.  Dict insertion order
    is deterministic for deterministic market input, so a second full sort is
    unnecessary; immutable/public snapshots canonicalize at their boundary.
    """

    grouped: dict[int, _WorkingLot | list[_WorkingLot]] = {}
    for lot in lots:
        if lot.shares <= 0:
            continue
        cell_id = lot.cell_id
        existing = grouped.get(cell_id)
        if existing is None:
            grouped[cell_id] = lot
        elif isinstance(existing, list):
            existing.append(lot)
        else:
            grouped[cell_id] = [existing, lot]
    if not grouped:
        raise ChipStateContractError("inventory cannot be empty after aggregation")
    combined: list[_WorkingLot] = []
    for cell_id, value in grouped.items():
        if isinstance(value, list):
            first = value[0]
            shares = math.fsum(part.shares for part in value)
            initialization_prior_units = math.fsum(
                part.initialization_prior_units for part in value
            )
            if first.cost_bucket_id is None:
                acquisition_cost = None
                economic_break_even = None
            else:
                acquisition_cost = (
                    math.fsum(
                        part.shares * cast(float, part.acquisition_cost) for part in value
                    )
                    / shares
                )
                economic_break_even = (
                    math.fsum(
                        part.shares * cast(float, part.economic_break_even) for part in value
                    )
                    / shares
                )
            # Compute every aggregate before mutating ``first``: it is also a
            # member of ``value``, so changing its shares earlier double-counts
            # its weight in the cost numerators.
            first.shares = shares
            first.initialization_prior_units = initialization_prior_units
            first.acquisition_cost = acquisition_cost
            first.economic_break_even = economic_break_even
        else:
            first = value
        first.source_cell_id = None
        first.lineage_denominator_shares = 0.0
        first.cell_id = cell_id
        combined.append(first)
    return combined


def _compact_working_lots_at_cap(
    lots: list[_WorkingLot],
    collision_cell_ids: set[int],
) -> list[_WorkingLot]:
    """Drop depleted lots and merge only known holding-age-cap collisions.

    The incoming EOD inventory is already canonical.  On an ordinary day,
    aging can create duplicates only where a max-age cell and the cell just
    below it both map to the same capped identity.  Rebuilding a dictionary
    for the complete inventory every day is therefore unnecessary.  Company
    action days continue to use the general canonicalizer.
    """

    compacted: list[_WorkingLot] = []
    grouped: dict[int, list[_WorkingLot]] = {}
    for lot in lots:
        if lot.shares <= 0:
            continue
        if lot.cell_id not in collision_cell_ids:
            compacted.append(lot)
            continue
        parts = grouped.get(lot.cell_id)
        if parts is None:
            grouped[lot.cell_id] = [lot]
            compacted.append(lot)
        else:
            parts.append(lot)

    if not compacted:
        raise ChipStateContractError("inventory cannot be empty after aggregation")

    for cell_id, parts in grouped.items():
        if len(parts) == 1:
            continue
        first = parts[0]
        shares = math.fsum(part.shares for part in parts)
        initialization_prior_units = math.fsum(part.initialization_prior_units for part in parts)
        if first.cost_bucket_id is None:
            acquisition_cost = None
            economic_break_even = None
        else:
            acquisition_cost = (
                math.fsum(
                    part.shares * cast(float, part.acquisition_cost) for part in parts
                )
                / shares
            )
            economic_break_even = (
                math.fsum(
                    part.shares * cast(float, part.economic_break_even) for part in parts
                )
                / shares
            )
        first.shares = shares
        first.initialization_prior_units = initialization_prior_units
        first.acquisition_cost = acquisition_cost
        first.economic_break_even = economic_break_even
        first.source_cell_id = None
        first.lineage_denominator_shares = 0.0
        first.cell_id = cell_id
    return compacted


def _compact_packed_lots_at_cap(
    lots: _PackedWorkingLots,
    collision_cell_ids: set[int],
) -> None:
    """Drop depleted cells and merge only age-cap collisions in packed form."""

    positive = lots.shares > 0
    if not bool(np.any(positive)):
        raise ChipStateContractError("inventory cannot be empty after aggregation")
    keep = positive.copy()
    for cell_id in collision_cell_ids:
        members = np.flatnonzero((lots.cell_ids == cell_id) & positive)
        if members.size < 2:
            continue
        first = int(members[0])
        shares = lots.shares[members]
        combined_shares = stable_sum(shares)
        lots.initialization_prior_units[first] = stable_sum(
            lots.initialization_prior_units[members]
        )
        if int(lots.cost_bucket_ids[first]) != _UNKNOWN_BUCKET_ID:
            lots.acquisition_costs[first] = (
                stable_weighted_sum(shares, lots.acquisition_costs[members]) / combined_shares
            )
            lots.economic_break_evens[first] = (
                stable_weighted_sum(shares, lots.economic_break_evens[members]) / combined_shares
            )
        lots.shares[first] = combined_shares
        keep[members[1:]] = False
    lots.retain(keep)


def _compact_packed_lots_by_dimensions(
    lots: _PackedWorkingLots,
    *,
    max_holding_days: int,
) -> None:
    """Drop depleted lots and merge age-cap collisions without stable hashes."""

    size = len(lots)
    positive = lots._shares[:size] > 0
    if not bool(np.any(positive)):
        raise ChipStateContractError("inventory cannot be empty after aggregation")
    keep = positive.copy()
    capped = np.flatnonzero(positive & (lots._holding_days[:size] == max_holding_days))
    if capped.size > 1:
        buckets = lots._cost_bucket_ids[capped]
        sensitivities = lots._sensitivity_codes[capped]
        economic = lots._economic_break_evens[capped]
        economic_keys = np.nan_to_num(economic, nan=-math.inf)
        order = np.lexsort((economic_keys, sensitivities, buckets))
        ordered = capped[order]
        ordered_buckets = lots._cost_bucket_ids[ordered]
        ordered_sensitivities = lots._sensitivity_codes[ordered]
        ordered_economic = np.nan_to_num(
            lots._economic_break_evens[ordered], nan=-math.inf
        )
        group_starts = np.flatnonzero(
            np.r_[
                True,
                (ordered_buckets[1:] != ordered_buckets[:-1])
                | (ordered_sensitivities[1:] != ordered_sensitivities[:-1])
                | (ordered_economic[1:] != ordered_economic[:-1]),
            ]
        )
        group_stops = np.r_[group_starts[1:], ordered.size]
        for start, stop in zip(group_starts, group_stops, strict=True):
            if stop - start < 2:
                continue
            members = ordered[start:stop]
            first = int(members[0])
            member_shares = lots._shares[members]
            combined_shares = stable_sum(member_shares)
            lots._initialization_prior_units[first] = stable_sum(
                lots._initialization_prior_units[members]
            )
            if int(lots._cost_bucket_ids[first]) != _UNKNOWN_BUCKET_ID:
                lots._acquisition_costs[first] = (
                    stable_weighted_sum(member_shares, lots._acquisition_costs[members])
                    / combined_shares
                )
                lots._economic_break_evens[first] = (
                    stable_weighted_sum(member_shares, lots._economic_break_evens[members])
                    / combined_shares
                )
            lots._shares[first] = combined_shares
            keep[members[1:]] = False
    if not bool(np.all(keep)):
        lots.retain(keep)


@dataclass(frozen=True, slots=True)
class _WorkingTransition:
    """Compact transition view for bulk generation after in-place checks."""

    transition_id: str
    source_cell_ids: tuple[int, ...]
    destination_cell_ids: tuple[int, ...]
    retained_fractions: tuple[float, ...]
    fixed_pre_eligible_shares: float
    executed_sell_shares: float
    same_day_resale_shares: float = 0.0


@dataclass(frozen=True, slots=True)
class _PreparedSourceState:
    """Dense PRE seller arrays built during the daily inventory scan."""

    indices: Int64Array
    shares: FloatArray
    costs: FloatArray
    sensitivity_codes: Int8Array


@dataclass(slots=True)
class MutableChipState:
    """Compact transient POST state used only before the requested output year."""

    symbol: str
    trading_date: date
    decision_at: datetime
    effective_at: datetime
    available_at: datetime
    snapshot_id: str
    model_version: str
    grid_version: str
    seller_model: SellerModel
    lots: list[_WorkingLot] | _PackedWorkingLots
    free_float_shares: float
    latent_supply_shares: float
    input_snapshot_ids: tuple[str, ...]
    hard_valid: bool
    quality_reason_codes: tuple[str, ...]
    last_transition: OriginSurvivalTransition | _WorkingTransition | None = None
    _conservation_error: float = field(default=0.0, repr=False)

    @property
    def phase(self) -> SnapshotPhase:
        return SnapshotPhase.POST

    @property
    def pit_grade(self) -> str:
        return "A" if self.hard_valid else "B_RESEARCH_ONLY"

    @property
    def inventory(self) -> SparseChipInventory:
        if isinstance(self.lots, _PackedWorkingLots):
            return SparseChipInventory.canonical(self.lots.to_cells())
        return SparseChipInventory.canonical(
            tuple(lot.to_cell() for lot in self.lots if lot.shares > 0)
        )

    @property
    def packed_lots(self) -> _PackedWorkingLots | None:
        return self.lots if isinstance(self.lots, _PackedWorkingLots) else None

    @property
    def conservation_error(self) -> float:
        return self._conservation_error

    @classmethod
    def from_snapshot(cls, snapshot: ChipSnapshotV2, *, packed: bool = False) -> MutableChipState:
        return cls(
            symbol=snapshot.symbol,
            trading_date=snapshot.trading_date,
            decision_at=snapshot.decision_at,
            effective_at=snapshot.effective_at,
            available_at=snapshot.available_at,
            snapshot_id=snapshot.snapshot_id,
            model_version=snapshot.model_version,
            grid_version=snapshot.grid_version,
            seller_model=snapshot.seller_model,
            lots=_PackedWorkingLots.from_cells(snapshot.inventory.cells)
            if packed
            else [
                _WorkingLot(
                    source_cell_id=None,
                    cost_bucket_id=cell.cost_bucket_id,
                    holding_days=cell.holding_days,
                    sensitivity=cell.sensitivity,
                    acquisition_cost=cell.acquisition_cost,
                    economic_break_even=cell.economic_break_even,
                    shares=cell.shares,
                    initialization_prior_units=cell.initialization_prior_units,
                    lineage_denominator_shares=0.0,
                )
                for cell in snapshot.inventory.cells
            ],
            free_float_shares=snapshot.free_float_shares,
            latent_supply_shares=snapshot.latent_supply_shares,
            input_snapshot_ids=snapshot.input_snapshot_ids,
            hard_valid=snapshot.hard_valid,
            quality_reason_codes=snapshot.quality_reason_codes,
            _conservation_error=snapshot.conservation_error,
        )

    def to_snapshot(self) -> ChipSnapshotV2:
        inventory = self.inventory
        snapshot = _make_snapshot(
            symbol=self.symbol,
            trading_date=self.trading_date,
            decision_at=self.decision_at,
            effective_at=self.effective_at,
            available_at=self.available_at,
            phase=SnapshotPhase.POST,
            model_version=self.model_version,
            grid_version=self.grid_version,
            seller_model=self.seller_model,
            inventory=inventory,
            free_float_shares=self.free_float_shares,
            latent_supply_shares=self.latent_supply_shares,
            input_snapshot_ids=self.input_snapshot_ids,
            hard_valid=self.hard_valid,
            quality_reason_codes=self.quality_reason_codes,
        )
        if snapshot.snapshot_id != self.snapshot_id:
            if isinstance(self.lots, _PackedWorkingLots):
                lot_total = math.fsum(self.lots.shares.tolist())
                lot_known = math.fsum(
                    self.lots.shares[self.lots.cost_bucket_ids != _UNKNOWN_BUCKET_ID].tolist()
                )
            else:
                lot_total = math.fsum(lot.shares for lot in self.lots)
                lot_known = math.fsum(
                    lot.shares for lot in self.lots if lot.cost_bucket_id is not None
                )
            raise ChipStateContractError(
                "transient POST snapshot identity changed: "
                f"cells={len(self.lots)}/{len(inventory.cells)} "
                f"total={lot_total!r}/{inventory.total_shares!r} "
                f"known={lot_known!r}/{inventory.known_cost_shares!r}"
            )
        return snapshot


@dataclass(frozen=True)
class DailyMigrationResult:
    pre_snapshot: ChipSnapshotV2 | None
    post_snapshot: ChipSnapshotV2
    transition: OriginSurvivalTransition | None


def _snapshot_id(
    *,
    symbol: str,
    trading_date: date,
    decision_at: datetime,
    effective_at: datetime,
    available_at: datetime,
    phase: SnapshotPhase,
    model_version: str,
    grid_version: str,
    seller_model: SellerModel,
    free_float_shares: float,
    latent_supply_shares: float,
    input_snapshot_ids: tuple[str, ...],
    hard_valid: bool,
    quality_reason_codes: tuple[str, ...],
    inventory_cell_count: int,
    inventory_total_shares: float,
    known_cost_shares: float,
    unknown_cost_shares: float,
) -> str:
    payload: dict[str, object] = {
        "symbol": symbol,
        "trading_date": trading_date.isoformat(),
        "decision_at": decision_at.isoformat(),
        "effective_at": effective_at.isoformat(),
        "available_at": available_at.isoformat(),
        "phase": phase.value,
        "model_version": model_version,
        "grid_version": grid_version,
        "seller_model": seller_model.value,
        "free_float_shares": free_float_shares,
        "latent_supply_shares": latent_supply_shares,
        "input_snapshot_ids": input_snapshot_ids,
        "hard_valid": hard_valid,
        "quality_reason_codes": quality_reason_codes,
        "inventory_cell_count": inventory_cell_count,
        "inventory_total_shares": inventory_total_shares,
        "known_cost_shares": known_cost_shares,
        "unknown_cost_shares": unknown_cost_shares,
    }
    return stable_id("chip_snapshot_v2", payload)


def _make_snapshot(
    *,
    symbol: str,
    trading_date: date,
    decision_at: datetime,
    effective_at: datetime,
    available_at: datetime,
    phase: SnapshotPhase,
    model_version: str,
    grid_version: str,
    seller_model: SellerModel,
    inventory: SparseChipInventory,
    free_float_shares: float,
    latent_supply_shares: float,
    input_snapshot_ids: tuple[str, ...],
    hard_valid: bool,
    quality_reason_codes: tuple[str, ...],
) -> ChipSnapshotV2:
    return ChipSnapshotV2(
        symbol=symbol,
        trading_date=trading_date,
        decision_at=decision_at,
        effective_at=effective_at,
        available_at=available_at,
        phase=phase,
        snapshot_id=_snapshot_id(
            symbol=symbol,
            trading_date=trading_date,
            decision_at=decision_at,
            effective_at=effective_at,
            available_at=available_at,
            phase=phase,
            model_version=model_version,
            grid_version=grid_version,
            seller_model=seller_model,
            free_float_shares=free_float_shares,
            latent_supply_shares=latent_supply_shares,
            input_snapshot_ids=input_snapshot_ids,
            hard_valid=hard_valid,
            quality_reason_codes=quality_reason_codes,
            inventory_cell_count=len(inventory.cells),
            inventory_total_shares=inventory.total_shares,
            known_cost_shares=inventory.known_cost_shares,
            unknown_cost_shares=inventory.unknown_cost_shares,
        ),
        model_version=model_version,
        grid_version=grid_version,
        seller_model=seller_model,
        inventory=inventory,
        free_float_shares=free_float_shares,
        latent_supply_shares=latent_supply_shares,
        input_snapshot_ids=input_snapshot_ids,
        pit_grade="A" if hard_valid else "B_RESEARCH_ONLY",
        hard_valid=hard_valid,
        quality_reason_codes=quality_reason_codes,
    )


def initial_unknown_snapshot(
    *,
    symbol: str,
    decision_at: datetime,
    available_at: datetime,
    free_float_shares: float,
    latent_supply_shares: float,
    seller_model: SellerModel,
    model_version: str,
    grid_version: str,
    input_snapshot_ids: tuple[str, ...],
) -> ChipSnapshotV2:
    """Represent missing pre-history as UNKNOWN_COST, never a fabricated band."""

    require_aware(decision_at, "decision_at")
    require_aware(available_at, "available_at")
    if available_at > decision_at:
        raise ChipStateContractError("initial state is unavailable at decision_at")
    if not math.isfinite(free_float_shares) or free_float_shares <= 0:
        raise ChipStateContractError("initial free float must be positive")
    if not math.isfinite(latent_supply_shares) or latent_supply_shares < 0:
        raise ChipStateContractError("initial latent supply cannot be negative")
    input_ids = tuple(sorted(set(input_snapshot_ids)))
    if not input_ids:
        raise ChipStateContractError("initial state requires registered input snapshots")
    allocations: tuple[tuple[TurnoverSensitivity, float], ...]
    if seller_model == SellerModel.ACTIVE_STICKY:
        allocations = (
            (TurnoverSensitivity.ACTIVE, 0.35),
            (TurnoverSensitivity.STICKY, 0.65),
        )
    else:
        allocations = ((TurnoverSensitivity.NEUTRAL, 1.0),)
    cells = tuple(
        InventoryCell.create(
            cost_bucket_id=None,
            holding_days=-1,
            sensitivity=sensitivity,
            acquisition_cost=None,
            economic_break_even=None,
            shares=free_float_shares * weight,
            initialization_prior_units=weight,
        )
        for sensitivity, weight in allocations
    )
    inventory = SparseChipInventory.canonical(cells)
    return _make_snapshot(
        symbol=symbol,
        trading_date=decision_at.date(),
        decision_at=decision_at,
        effective_at=decision_at,
        available_at=available_at,
        phase=SnapshotPhase.POST,
        model_version=model_version,
        grid_version=grid_version,
        seller_model=seller_model,
        inventory=inventory,
        free_float_shares=free_float_shares,
        latent_supply_shares=latent_supply_shares,
        input_snapshot_ids=input_ids,
        hard_valid=False,
        quality_reason_codes=("UNKNOWN_COST_INITIALIZATION",),
    )


class DailyMigrationEngine:
    """Advance one seller hypothesis over one day without T+1 leakage."""

    def __init__(
        self,
        *,
        grid: StableLogPriceGrid,
        seller_model: SellerModel,
        model_version: str,
        max_holding_days: int = DEFAULT_MAX_HOLDING_DAYS,
        active_purchase_fraction: float = 0.7,
        aged_cell_id_cache: dict[int, int] | None = None,
    ) -> None:
        if not model_version:
            raise ChipStateContractError("model_version cannot be empty")
        if max_holding_days < 1:
            raise ChipStateContractError("max_holding_days must be positive")
        if not 0 <= active_purchase_fraction <= 1:
            raise ChipStateContractError("active purchase fraction must be in [0, 1]")
        self.grid = grid
        self.seller_model = seller_model
        self.model_version = model_version
        self.max_holding_days = max_holding_days
        self.active_purchase_fraction = active_purchase_fraction
        # Aging is model-independent.  A full symbol replay otherwise performs
        # millions of cached-hash calls for the same cell -> next-day cell map.
        # The annual builder shares this small map across its three models.
        self._aged_cell_id_cache = aged_cell_id_cache if aged_cell_id_cache is not None else {}

    def _age_lot(self, lot: _WorkingLot) -> None:
        if lot.holding_days < 0 or lot.holding_days >= self.max_holding_days:
            return
        previous_cell_id = lot.cell_id
        lot.holding_days += 1
        aged_cell_id = self._aged_cell_id_cache.get(previous_cell_id)
        if aged_cell_id is None:
            aged_cell_id = stable_cell_id(
                cost_bucket_id=lot.cost_bucket_id,
                holding_days=lot.holding_days,
                sensitivity=lot.sensitivity,
                economic_break_even=lot.economic_break_even,
            )
            self._aged_cell_id_cache[previous_cell_id] = aged_cell_id
        lot.cell_id = aged_cell_id

    def advance_day(
        self,
        *,
        previous_post: ChipSnapshotV2,
        decision_at: datetime,
        available_at: datetime,
        minute_bars: tuple[MinuteBar, ...] | None,
        inventory_events: tuple[InventoryEvent, ...],
        expected_free_float_shares: float,
        additional_input_snapshot_ids: tuple[str, ...] = (),
        input_hard_valid: bool = True,
        input_quality_reason_codes: tuple[str, ...] = (),
        materialize_pre_snapshot: bool = True,
        build_transition: bool = True,
        prepared_minute_path: PreparedMinutePath | None = None,
    ) -> DailyMigrationResult:
        require_aware(decision_at, "decision_at")
        require_aware(available_at, "available_at")
        if prepared_minute_path is None:
            if minute_bars is None:
                raise ChipStateContractError("minute bars or a prepared minute path are required")
            prepared_minute_path = prepare_minute_path(
                grid=self.grid,
                decision_at=decision_at,
                minute_bars=minute_bars,
            )
        else:
            if prepared_minute_path.decision_at != decision_at:
                raise ChipStateContractError("prepared minute path decision_at mismatch")
            if prepared_minute_path.grid_version != self.grid.grid_version:
                raise ChipStateContractError("prepared minute path grid_version mismatch")
            if minute_bars is not None and minute_bars != prepared_minute_path.minute_bars:
                raise ChipStateContractError("prepared minute path does not match minute bars")
        self._validate_daily_inputs(
            previous_post=previous_post,
            decision_at=decision_at,
            available_at=available_at,
            inventory_events=inventory_events,
        )
        lots = self._age_previous_inventory(previous_post)
        free_float = previous_post.free_float_shares
        latent_supply = previous_post.latent_supply_shares
        for event in inventory_events:
            free_float, latent_supply = self._apply_inventory_event(
                lots=lots,
                free_float=free_float,
                latent_supply=latent_supply,
                event=event,
            )
        if abs(free_float - expected_free_float_shares) > tolerance(expected_free_float_shares):
            raise ChipStateContractError(
                "inventory events do not bridge expected free float: "
                f"ledger={free_float:.17g}, expected={expected_free_float_shares:.17g}"
            )
        pre_total_shares = math.fsum(lot.shares for lot in lots if lot.shares > 0)
        pre_known_cost_shares = math.fsum(
            lot.shares for lot in lots if lot.shares > 0 and lot.cost_bucket_id is not None
        )
        pre_unknown_cost_shares = pre_total_shares - pre_known_cost_shares
        if abs(pre_total_shares - free_float) > tolerance(free_float):
            raise ChipStateContractError("PRE inventory lost mass before snapshot creation")

        pre_input_ids = tuple(
            sorted(
                {
                    previous_post.snapshot_id,
                    *(event.snapshot_id for event in inventory_events),
                    *additional_input_snapshot_ids,
                }
            )
        )
        quality_codes, hard_valid = self._quality_state_from_mass(
            previous_post=previous_post,
            total_shares=pre_total_shares,
            unknown_cost_shares=pre_unknown_cost_shares,
            input_hard_valid=input_hard_valid,
            input_quality_reason_codes=input_quality_reason_codes,
        )
        pre_effective_at = max(
            (previous_post.effective_at, *(event.effective_at for event in inventory_events))
        )
        pre_snapshot: ChipSnapshotV2 | None = None
        if materialize_pre_snapshot:
            pre_inventory = SparseChipInventory.canonical(
                tuple(lot.to_cell() for lot in lots if lot.shares > 0)
            )
            pre_snapshot = _make_snapshot(
                symbol=previous_post.symbol,
                trading_date=decision_at.date(),
                decision_at=decision_at,
                effective_at=pre_effective_at,
                available_at=available_at,
                phase=SnapshotPhase.PRE,
                model_version=self.model_version,
                grid_version=self.grid.grid_version,
                seller_model=self.seller_model,
                inventory=pre_inventory,
                free_float_shares=free_float,
                latent_supply_shares=latent_supply,
                input_snapshot_ids=pre_input_ids,
                hard_valid=hard_valid,
                quality_reason_codes=quality_codes,
            )
            pre_snapshot_id = pre_snapshot.snapshot_id
        else:
            pre_snapshot_id = _snapshot_id(
                symbol=previous_post.symbol,
                trading_date=decision_at.date(),
                decision_at=decision_at,
                effective_at=pre_effective_at,
                available_at=available_at,
                phase=SnapshotPhase.PRE,
                model_version=self.model_version,
                grid_version=self.grid.grid_version,
                seller_model=self.seller_model,
                free_float_shares=free_float,
                latent_supply_shares=latent_supply,
                input_snapshot_ids=pre_input_ids,
                hard_valid=hard_valid,
                quality_reason_codes=quality_codes,
                inventory_cell_count=len({lot.cell_id for lot in lots if lot.shares > 0}),
                inventory_total_shares=pre_total_shares,
                known_cost_shares=pre_known_cost_shares,
                unknown_cost_shares=pre_unknown_cost_shares,
            )

        # Only inventory descended from the previous POST snapshot may supply
        # today's sellers.  A float-add event is present in PRE for mass
        # conservation, but it did not exist in yesterday's tradable inventory
        # and therefore cannot be recycled through today's minute path.
        source_indices: list[int] = []
        source_shares: list[float] = []
        source_costs: list[float] = []
        source_sensitivity_codes: list[int] = []
        needs_costs = self.seller_model == SellerModel.DISPOSITION
        needs_sensitivity_codes = self.seller_model == SellerModel.ACTIVE_STICKY
        for index, lot in enumerate(lots):
            if lot.source_cell_id is None or lot.shares <= 0:
                continue
            source_indices.append(index)
            source_shares.append(lot.shares)
            if needs_costs:
                source_costs.append(
                    np.nan if lot.acquisition_cost is None else lot.acquisition_cost
                )
            if needs_sensitivity_codes:
                if lot.sensitivity == TurnoverSensitivity.ACTIVE:
                    source_sensitivity_codes.append(0)
                elif lot.sensitivity == TurnoverSensitivity.NEUTRAL:
                    source_sensitivity_codes.append(1)
                else:
                    source_sensitivity_codes.append(2)
        fixed_pre_eligible_shares = math.fsum(source_shares)
        total_volume = prepared_minute_path.total_volume
        if total_volume > fixed_pre_eligible_shares + tolerance(fixed_pre_eligible_shares):
            raise ChipStateContractError(
                "daily minute volume exceeds fixed PRE seller pool under T+1"
            )
        prepared_source = _PreparedSourceState(
            indices=np.asarray(source_indices, dtype=np.int64),
            shares=np.asarray(source_shares, dtype=float),
            costs=np.asarray(source_costs, dtype=float),
            sensitivity_codes=np.asarray(source_sensitivity_codes, dtype=np.int8),
        )
        purchases, _ = self._migrate_minute_path(lots, prepared_source, prepared_minute_path)

        remaining_cells = tuple(lot.to_cell() for lot in lots if lot.shares > 0)
        post_inventory = SparseChipInventory.canonical(
            (*remaining_cells, *(lot.to_cell() for lot in purchases))
        )
        if abs(post_inventory.total_shares - free_float) > tolerance(free_float):
            raise ChipStateContractError("POST inventory migration failed mass conservation")
        post_input_ids = tuple(sorted({*pre_input_ids, *prepared_minute_path.snapshot_ids}))
        post_codes, post_hard_valid = self._quality_state(
            previous_post=previous_post,
            inventory=post_inventory,
            input_hard_valid=input_hard_valid,
            input_quality_reason_codes=input_quality_reason_codes,
        )
        post_effective_at = (
            pre_effective_at
            if prepared_minute_path.latest_timestamp is None
            else max(pre_effective_at, prepared_minute_path.latest_timestamp)
        )
        post_snapshot = _make_snapshot(
            symbol=previous_post.symbol,
            trading_date=decision_at.date(),
            decision_at=decision_at,
            effective_at=post_effective_at,
            available_at=available_at,
            phase=SnapshotPhase.POST,
            model_version=self.model_version,
            grid_version=self.grid.grid_version,
            seller_model=self.seller_model,
            inventory=post_inventory,
            free_float_shares=free_float,
            latent_supply_shares=latent_supply,
            input_snapshot_ids=post_input_ids,
            hard_valid=post_hard_valid,
            quality_reason_codes=post_codes,
        )
        transition = None
        if build_transition:
            transition = self._build_transition(
                previous_post=previous_post,
                pre_snapshot_id=pre_snapshot_id,
                post_snapshot=post_snapshot,
                source_lots=lots,
                decision_at=decision_at,
                available_at=available_at,
                effective_at=post_effective_at,
                fixed_pre_eligible_shares=fixed_pre_eligible_shares,
                executed_sell_shares=total_volume,
                input_snapshot_ids=post_input_ids,
            )
        return DailyMigrationResult(
            pre_snapshot=pre_snapshot,
            post_snapshot=post_snapshot,
            transition=transition,
        )

    def advance_packed_warmup_day(
        self,
        *,
        previous_post: ChipSnapshotV2 | MutableChipState,
        decision_at: datetime,
        available_at: datetime,
        inventory_events: tuple[InventoryEvent, ...],
        expected_free_float_shares: float,
        additional_input_snapshot_ids: tuple[str, ...],
        input_hard_valid: bool,
        input_quality_reason_codes: tuple[str, ...],
        prepared_minute_path: PreparedMinutePath,
        build_transition: bool = False,
    ) -> MutableChipState:
        """Advance an ordinary day directly from the previous packed EOD state.

        Company-action and float-change days deliberately use the exact object
        implementation, then repack once at the boundary.  Ordinary days keep
        the SoA arrays alive across dates and avoid rebuilding Python lots.
        """

        if inventory_events:
            if (
                isinstance(previous_post, MutableChipState)
                and previous_post.packed_lots is not None
            ):
                packed_lots = previous_post.packed_lots
                previous_post = MutableChipState(
                    symbol=previous_post.symbol,
                    trading_date=previous_post.trading_date,
                    decision_at=previous_post.decision_at,
                    effective_at=previous_post.effective_at,
                    available_at=previous_post.available_at,
                    snapshot_id=previous_post.snapshot_id,
                    model_version=previous_post.model_version,
                    grid_version=previous_post.grid_version,
                    seller_model=previous_post.seller_model,
                    lots=packed_lots.to_working_lots(),
                    free_float_shares=previous_post.free_float_shares,
                    latent_supply_shares=previous_post.latent_supply_shares,
                    input_snapshot_ids=previous_post.input_snapshot_ids,
                    hard_valid=previous_post.hard_valid,
                    quality_reason_codes=previous_post.quality_reason_codes,
                    last_transition=previous_post.last_transition,
                    _conservation_error=previous_post.conservation_error,
                )
            result = self.advance_warmup_day(
                previous_post=previous_post,
                decision_at=decision_at,
                available_at=available_at,
                inventory_events=inventory_events,
                expected_free_float_shares=expected_free_float_shares,
                additional_input_snapshot_ids=additional_input_snapshot_ids,
                input_hard_valid=input_hard_valid,
                input_quality_reason_codes=input_quality_reason_codes,
                prepared_minute_path=prepared_minute_path,
                build_transition=build_transition,
            )
            if not isinstance(result.lots, _PackedWorkingLots):
                result.lots = _PackedWorkingLots.from_working_lots(result.lots)
            return result

        require_aware(decision_at, "decision_at")
        require_aware(available_at, "available_at")
        if prepared_minute_path.decision_at != decision_at:
            raise ChipStateContractError("prepared minute path decision_at mismatch")
        if prepared_minute_path.grid_version != self.grid.grid_version:
            raise ChipStateContractError("prepared minute path grid_version mismatch")
        self._validate_daily_inputs(
            previous_post=previous_post,
            decision_at=decision_at,
            available_at=available_at,
            inventory_events=inventory_events,
        )
        state = (
            previous_post
            if isinstance(previous_post, MutableChipState)
            else MutableChipState.from_snapshot(previous_post, packed=True)
        )
        if state.packed_lots is None:
            object_lots = state.lots
            if not isinstance(object_lots, list):
                raise ChipStateContractError("unexpected packed inventory state")
            state.lots = _PackedWorkingLots.from_working_lots(object_lots)
        lots = state.packed_lots
        if lots is None:
            raise ChipStateContractError("packed inventory conversion failed")
        if build_transition:
            lots.refresh_cell_ids()

        previous_snapshot_id = state.snapshot_id
        # Keep active array views local.  Accessing the sliced properties inside
        # the per-lot loop created millions of tiny ndarray views per symbol.
        size = len(lots)
        cell_ids = lots._cell_ids[:size]
        cost_bucket_ids = lots._cost_bucket_ids[:size]
        holding_days = lots._holding_days[:size]
        sensitivity_codes = lots._sensitivity_codes[:size]
        shares = lots._shares[:size]
        acquisition_costs = lots._acquisition_costs[:size]
        economic_break_evens = lots._economic_break_evens[:size]
        initialization_prior_units = lots._initialization_prior_units[:size]
        source_cell_ids = cell_ids.copy() if build_transition else None
        age_mask = (holding_days >= 0) & (holding_days < self.max_holding_days)
        holding_days[age_mask] += 1
        if build_transition:
            aged_cell_id_cache = self._aged_cell_id_cache
            age_indices = np.flatnonzero(age_mask)
            # Many lots have the same canonical dimensions.  Age each distinct
            # cell id once in Python, then broadcast the result in NumPy.
            aged_from_ids, first_positions, inverse = np.unique(
                cell_ids[age_indices], return_index=True, return_inverse=True
            )
            aged_to_ids = np.empty_like(aged_from_ids)
            for unique_position, previous_cell_id_raw in enumerate(aged_from_ids):
                previous_cell_id = int(previous_cell_id_raw)
                aged_cell_id = aged_cell_id_cache.get(previous_cell_id)
                if aged_cell_id is None:
                    item = int(age_indices[int(first_positions[unique_position])])
                    bucket = int(cost_bucket_ids[item])
                    aged_cell_id = stable_cell_id(
                        cost_bucket_id=(None if bucket == _UNKNOWN_BUCKET_ID else bucket),
                        holding_days=int(holding_days[item]),
                        sensitivity=_SENSITIVITY_BY_CODE[int(sensitivity_codes[item])],
                        economic_break_even=(
                            None
                            if bucket == _UNKNOWN_BUCKET_ID
                            else float(economic_break_evens[item])
                        ),
                    )
                    aged_cell_id_cache[previous_cell_id] = aged_cell_id
                aged_to_ids[unique_position] = aged_cell_id
            cell_ids[age_indices] = aged_to_ids[inverse]
            lots._cell_ids_current = True
        else:
            lots._cell_ids_current = False

        free_float = state.free_float_shares
        latent_supply = state.latent_supply_shares
        if abs(free_float - expected_free_float_shares) > tolerance(expected_free_float_shares):
            raise ChipStateContractError(
                "ordinary day changed free float without an inventory event"
            )
        positive = shares > 0
        source_indices = np.flatnonzero(positive).astype(np.int64, copy=False)
        # Source shares must survive the in-place depletion below, but there is
        # no reason to copy depleted slots or every other inventory column.
        source_shares = shares[source_indices].copy()
        pre_total = math.fsum(source_shares.tolist())
        known_mask = cost_bucket_ids[source_indices] != _UNKNOWN_BUCKET_ID
        pre_known = math.fsum(source_shares[known_mask].tolist())
        pre_unknown = math.fsum(source_shares[~known_mask].tolist())
        if abs(pre_total - free_float) > tolerance(free_float):
            raise ChipStateContractError("PRE inventory lost mass before migration")

        pre_input_ids = tuple(sorted({state.snapshot_id, *additional_input_snapshot_ids}))
        pre_effective_at = state.effective_at
        pre_snapshot_id = ""
        if build_transition:
            pre_codes, pre_hard_valid = self._quality_state_from_mass(
                previous_post=state,
                total_shares=pre_total,
                unknown_cost_shares=pre_unknown,
                input_hard_valid=input_hard_valid,
                input_quality_reason_codes=input_quality_reason_codes,
            )
            pre_snapshot_id = _snapshot_id(
                symbol=state.symbol,
                trading_date=decision_at.date(),
                decision_at=decision_at,
                effective_at=pre_effective_at,
                available_at=available_at,
                phase=SnapshotPhase.PRE,
                model_version=self.model_version,
                grid_version=self.grid.grid_version,
                seller_model=self.seller_model,
                free_float_shares=free_float,
                latent_supply_shares=latent_supply,
                input_snapshot_ids=pre_input_ids,
                hard_valid=pre_hard_valid,
                quality_reason_codes=pre_codes,
                inventory_cell_count=len(set(cell_ids[source_indices].tolist())),
                inventory_total_shares=pre_total,
                known_cost_shares=pre_known,
                unknown_cost_shares=pre_unknown,
            )

        fixed_pre_eligible = pre_total
        if prepared_minute_path.total_volume > fixed_pre_eligible + tolerance(fixed_pre_eligible):
            raise ChipStateContractError(
                "daily minute volume exceeds fixed PRE seller pool under T+1"
            )
        prepared_source = _PreparedSourceState(
            indices=source_indices,
            shares=source_shares,
            costs=(
                acquisition_costs[source_indices]
                if self.seller_model == SellerModel.DISPOSITION
                else np.asarray([], dtype=float)
            ),
            sensitivity_codes=(
                sensitivity_codes[source_indices]
                if self.seller_model == SellerModel.ACTIVE_STICKY
                else np.asarray([], dtype=np.int8)
            ),
        )
        remaining_indices, remaining = self._source_remaining_after_path(
            prepared_source, prepared_minute_path
        )
        before = shares[remaining_indices].copy()
        shares[remaining_indices] = np.maximum(0.0, remaining)
        initialization_prior_units[remaining_indices] *= shares[remaining_indices] / before
        exhausted_source = bool(np.any(shares[remaining_indices] == 0.0))

        arcs: list[tuple[int, int, float]] = []
        if build_transition:
            if source_cell_ids is None:
                raise ChipStateContractError("source lineage ids were not retained")
            retained = shares[remaining_indices] / source_shares
            retained[np.abs(retained) <= tolerance(1.0)] = 0.0
            retained[np.abs(retained - 1.0) <= tolerance(1.0)] = 1.0
            if bool(np.any((retained < 0) | (retained > 1))):
                raise ChipStateContractError(
                    "daily source lineage retained fraction is outside [0, 1]"
                )
            arcs = sorted(
                zip(
                    source_cell_ids[source_indices].tolist(),
                    cell_ids[source_indices].tolist(),
                    retained.tolist(),
                    strict=True,
                )
            )
            if any(previous[:2] == current[:2] for previous, current in pairwise(arcs)):
                raise ChipStateContractError("daily source lineage produced duplicate arcs")

        lots.append_purchases(
            prepared_minute_path,
            seller_model=self.seller_model,
            active_purchase_fraction=self.active_purchase_fraction,
        )
        if exhausted_source or bool(np.any(lots.holding_days == self.max_holding_days)):
            _compact_packed_lots_by_dimensions(
                lots,
                max_holding_days=self.max_holding_days,
            )

        post_total = math.fsum(lots.shares.tolist())
        post_known_mask = lots.cost_bucket_ids != _UNKNOWN_BUCKET_ID
        post_known = math.fsum(lots.shares[post_known_mask].tolist())
        post_unknown = math.fsum(lots.shares[~post_known_mask].tolist())
        if abs(post_total - free_float) > tolerance(free_float):
            raise ChipStateContractError("POST inventory migration failed mass conservation")
        post_input_ids = _merge_sorted_unique(pre_input_ids, prepared_minute_path.snapshot_ids)
        post_codes, post_hard_valid = self._quality_state_from_mass(
            previous_post=state,
            total_shares=post_total,
            unknown_cost_shares=post_unknown,
            input_hard_valid=input_hard_valid,
            input_quality_reason_codes=input_quality_reason_codes,
        )
        post_effective_at = (
            pre_effective_at
            if prepared_minute_path.latest_timestamp is None
            else max(pre_effective_at, prepared_minute_path.latest_timestamp)
        )
        snapshot_id = _snapshot_id(
            symbol=state.symbol,
            trading_date=decision_at.date(),
            decision_at=decision_at,
            effective_at=post_effective_at,
            available_at=available_at,
            phase=SnapshotPhase.POST,
            model_version=self.model_version,
            grid_version=self.grid.grid_version,
            seller_model=self.seller_model,
            free_float_shares=free_float,
            latent_supply_shares=latent_supply,
            input_snapshot_ids=post_input_ids,
            hard_valid=post_hard_valid,
            quality_reason_codes=post_codes,
            inventory_cell_count=len(lots),
            inventory_total_shares=post_total,
            known_cost_shares=post_known,
            unknown_cost_shares=post_unknown,
        )
        transition = None
        if build_transition:
            payload: dict[str, object] = {
                "symbol": state.symbol,
                "trading_date": decision_at.date().isoformat(),
                "source_snapshot_id": previous_snapshot_id,
                "pre_snapshot_id": pre_snapshot_id,
                "destination_snapshot_id": snapshot_id,
                "model_version": self.model_version,
                "grid_version": self.grid.grid_version,
                "arc_count": len(arcs),
                "fixed_pre_eligible_shares": fixed_pre_eligible,
                "executed_sell_shares": prepared_minute_path.total_volume,
                "input_snapshot_ids": post_input_ids,
            }
            transition = _WorkingTransition(
                transition_id=stable_id("origin_survival_transition", payload),
                source_cell_ids=tuple(source for source, _, _ in arcs),
                destination_cell_ids=tuple(destination for _, destination, _ in arcs),
                retained_fractions=tuple(retained for _, _, retained in arcs),
                fixed_pre_eligible_shares=fixed_pre_eligible,
                executed_sell_shares=prepared_minute_path.total_volume,
                same_day_resale_shares=0.0,
            )
        return MutableChipState(
            symbol=state.symbol,
            trading_date=decision_at.date(),
            decision_at=decision_at,
            effective_at=post_effective_at,
            available_at=available_at,
            snapshot_id=snapshot_id,
            model_version=self.model_version,
            grid_version=self.grid.grid_version,
            seller_model=self.seller_model,
            lots=lots,
            free_float_shares=free_float,
            latent_supply_shares=latent_supply,
            input_snapshot_ids=post_input_ids,
            hard_valid=post_hard_valid,
            quality_reason_codes=post_codes,
            last_transition=transition,
        )

    def advance_warmup_day(
        self,
        *,
        previous_post: ChipSnapshotV2 | MutableChipState,
        decision_at: datetime,
        available_at: datetime,
        inventory_events: tuple[InventoryEvent, ...],
        expected_free_float_shares: float,
        additional_input_snapshot_ids: tuple[str, ...],
        input_hard_valid: bool,
        input_quality_reason_codes: tuple[str, ...],
        prepared_minute_path: PreparedMinutePath,
        build_transition: bool = False,
    ) -> MutableChipState:
        """Advance one day in place; optionally retain the exact output operator."""

        require_aware(decision_at, "decision_at")
        require_aware(available_at, "available_at")
        if prepared_minute_path.decision_at != decision_at:
            raise ChipStateContractError("prepared minute path decision_at mismatch")
        if prepared_minute_path.grid_version != self.grid.grid_version:
            raise ChipStateContractError("prepared minute path grid_version mismatch")
        self._validate_daily_inputs(
            previous_post=previous_post,
            decision_at=decision_at,
            available_at=available_at,
            inventory_events=inventory_events,
        )
        state = (
            previous_post
            if isinstance(previous_post, MutableChipState)
            else MutableChipState.from_snapshot(previous_post)
        )
        previous_snapshot_id = state.snapshot_id
        lots = state.lots
        if isinstance(lots, _PackedWorkingLots):
            lots = lots.to_working_lots()
            state.lots = lots
        # This loop is executed for every cell, day and seller model.  Keeping
        # aging inline avoids millions of Python method calls while preserving
        # the exact same shared cell-id mapping across the three models.
        aged_cell_id_cache = self._aged_cell_id_cache
        cache_get = aged_cell_id_cache.get
        max_holding_days = self.max_holding_days
        capped_dimensions: set[tuple[int | None, TurnoverSensitivity]] = set()
        capped_collision_cell_ids: set[int] = set()
        pre_known_parts: list[float] = []
        pre_unknown_parts: list[float] = []
        pre_total_parts: list[float] = []
        source_indices: list[int] = []
        source_shares: list[float] = []
        source_costs: list[float] = []
        source_sensitivity_codes: list[int] = []
        needs_costs = self.seller_model == SellerModel.DISPOSITION
        needs_sensitivity_codes = self.seller_model == SellerModel.ACTIVE_STICKY
        # Inventory events are rare.  On ordinary days collect the PRE seller
        # arrays while aging the previous POST state, avoiding a second full
        # Python scan over every lot.  Event days retain the separate scan
        # because an event can add, remove or reprice lots before migration.
        collect_sources_during_aging = not inventory_events
        for index, lot in enumerate(lots):
            lot.source_cell_id = lot.cell_id
            lot.lineage_denominator_shares = lot.shares
            holding_days = lot.holding_days
            if 0 <= holding_days < max_holding_days:
                previous_cell_id = lot.cell_id
                lot.holding_days = holding_days + 1
                aged_cell_id = cache_get(previous_cell_id)
                if aged_cell_id is None:
                    aged_cell_id = stable_cell_id(
                        cost_bucket_id=lot.cost_bucket_id,
                        holding_days=holding_days + 1,
                        sensitivity=lot.sensitivity,
                        economic_break_even=lot.economic_break_even,
                    )
                    aged_cell_id_cache[previous_cell_id] = aged_cell_id
                lot.cell_id = aged_cell_id
            if lot.holding_days == max_holding_days:
                dimension = (lot.cost_bucket_id, lot.sensitivity)
                if dimension in capped_dimensions:
                    capped_collision_cell_ids.add(lot.cell_id)
                else:
                    capped_dimensions.add(dimension)
            if collect_sources_during_aging and lot.shares > 0:
                pre_total_parts.append(lot.shares)
                if lot.cost_bucket_id is None:
                    pre_unknown_parts.append(lot.shares)
                else:
                    pre_known_parts.append(lot.shares)
                if lot.source_cell_id is not None:
                    source_indices.append(index)
                    source_shares.append(lot.shares)
                    if needs_costs:
                        source_costs.append(
                            np.nan if lot.acquisition_cost is None else lot.acquisition_cost
                        )
                    if needs_sensitivity_codes:
                        if lot.sensitivity == TurnoverSensitivity.ACTIVE:
                            source_sensitivity_codes.append(0)
                        elif lot.sensitivity == TurnoverSensitivity.NEUTRAL:
                            source_sensitivity_codes.append(1)
                        else:
                            source_sensitivity_codes.append(2)

        free_float = state.free_float_shares
        latent_supply = state.latent_supply_shares
        for event in inventory_events:
            free_float, latent_supply = self._apply_inventory_event(
                lots=lots,
                free_float=free_float,
                latent_supply=latent_supply,
                event=event,
            )
        if abs(free_float - expected_free_float_shares) > tolerance(expected_free_float_shares):
            raise ChipStateContractError("inventory events do not bridge expected free float")
        if inventory_events:
            for index, lot in enumerate(lots):
                if lot.shares <= 0:
                    continue
                pre_total_parts.append(lot.shares)
                if lot.cost_bucket_id is None:
                    pre_unknown_parts.append(lot.shares)
                else:
                    pre_known_parts.append(lot.shares)
                if lot.source_cell_id is not None:
                    source_indices.append(index)
                    source_shares.append(lot.shares)
                    if needs_costs:
                        source_costs.append(
                            np.nan if lot.acquisition_cost is None else lot.acquisition_cost
                        )
                    if needs_sensitivity_codes:
                        if lot.sensitivity == TurnoverSensitivity.ACTIVE:
                            source_sensitivity_codes.append(0)
                        elif lot.sensitivity == TurnoverSensitivity.NEUTRAL:
                            source_sensitivity_codes.append(1)
                        else:
                            source_sensitivity_codes.append(2)
        pre_unknown = math.fsum(pre_unknown_parts)
        # Hash the same aggregate that SparseChipInventory will recompute when the
        # transient state is materialized.  Summing the two subtotals can differ
        # by a few ulps from summing the cells directly, which used to make an
        # otherwise identical POST snapshot fail its identity check.
        pre_total = math.fsum(pre_total_parts)
        pre_known = math.fsum(pre_known_parts)
        if abs(pre_total - free_float) > tolerance(free_float):
            raise ChipStateContractError("PRE inventory lost mass before migration")
        pre_input_ids = tuple(
            sorted(
                {
                    state.snapshot_id,
                    *(event.snapshot_id for event in inventory_events),
                    *additional_input_snapshot_ids,
                }
            )
        )
        pre_effective_at = max(
            (state.effective_at, *(event.effective_at for event in inventory_events))
        )
        pre_snapshot_id = ""
        if build_transition:
            pre_codes, pre_hard_valid = self._quality_state_from_mass(
                previous_post=state,
                total_shares=pre_total,
                unknown_cost_shares=pre_unknown,
                input_hard_valid=input_hard_valid,
                input_quality_reason_codes=input_quality_reason_codes,
            )
            pre_snapshot_id = _snapshot_id(
                symbol=state.symbol,
                trading_date=decision_at.date(),
                decision_at=decision_at,
                effective_at=pre_effective_at,
                available_at=available_at,
                phase=SnapshotPhase.PRE,
                model_version=self.model_version,
                grid_version=self.grid.grid_version,
                seller_model=self.seller_model,
                free_float_shares=free_float,
                latent_supply_shares=latent_supply,
                input_snapshot_ids=pre_input_ids,
                hard_valid=pre_hard_valid,
                quality_reason_codes=pre_codes,
                inventory_cell_count=len({lot.cell_id for lot in lots if lot.shares > 0}),
                inventory_total_shares=pre_total,
                known_cost_shares=pre_known,
                unknown_cost_shares=pre_unknown,
            )
        fixed_pre_eligible = math.fsum(source_shares)
        if prepared_minute_path.total_volume > fixed_pre_eligible + tolerance(fixed_pre_eligible):
            raise ChipStateContractError(
                "daily minute volume exceeds fixed PRE seller pool under T+1"
            )
        prepared_source = _PreparedSourceState(
            indices=np.asarray(source_indices, dtype=np.int64),
            shares=np.asarray(source_shares, dtype=float),
            costs=np.asarray(source_costs, dtype=float),
            sensitivity_codes=np.asarray(source_sensitivity_codes, dtype=np.int8),
        )
        purchases, exhausted_source = self._migrate_minute_path(
            lots, prepared_source, prepared_minute_path
        )
        arcs: list[tuple[int, int, float]] = []
        if build_transition:
            arcs_in_order = True
            previous_arc: tuple[int, int] | None = None
            for lot in lots:
                if lot.source_cell_id is None:
                    continue
                if lot.lineage_denominator_shares <= 0:
                    raise ChipStateContractError("source lineage denominator is non-positive")
                retained = lot.shares / lot.lineage_denominator_shares
                if retained < 0 and abs(retained) <= tolerance(1.0):
                    retained = 0.0
                if retained > 1 and retained - 1 <= tolerance(1.0):
                    retained = 1.0
                if not 0.0 <= retained <= 1.0:
                    raise ChipStateContractError(
                        "daily source lineage retained fraction is outside [0, 1]"
                    )
                arc_key = (lot.source_cell_id, lot.cell_id)
                if previous_arc is not None and arc_key <= previous_arc:
                    arcs_in_order = False
                previous_arc = arc_key
                arcs.append((*arc_key, retained))
            if not arcs_in_order:
                arcs.sort()
            for previous, current in pairwise(arcs):
                if previous[:2] == current[:2]:
                    raise ChipStateContractError("daily source lineage produced duplicate arcs")
        lots.extend(purchases)
        # Previous EOD state is canonical, aging preserves uniqueness except at
        # the holding-age cap, and today's purchases are already grouped by
        # (bucket, sensitivity).  Avoid rebuilding a full-inventory dict on the
        # common path; retain exact aggregation for the three real collision
        # cases detected above and for a fully depleted source cell.
        if inventory_events:
            lots = _canonicalize_working_lots(lots)
        elif capped_collision_cell_ids or exhausted_source:
            lots = _compact_working_lots_at_cap(lots, capped_collision_cell_ids)
        post_known_parts: list[float] = []
        post_unknown_parts: list[float] = []
        post_total_parts: list[float] = []
        for lot in lots:
            if lot.shares <= 0:
                continue
            post_total_parts.append(lot.shares)
            if lot.cost_bucket_id is None:
                post_unknown_parts.append(lot.shares)
            else:
                post_known_parts.append(lot.shares)
        post_unknown = math.fsum(post_unknown_parts)
        post_total = math.fsum(post_total_parts)
        post_known = math.fsum(post_known_parts)
        if abs(post_total - free_float) > tolerance(free_float):
            raise ChipStateContractError("POST inventory migration failed mass conservation")
        post_input_ids = _merge_sorted_unique(pre_input_ids, prepared_minute_path.snapshot_ids)
        post_codes, post_hard_valid = self._quality_state_from_mass(
            previous_post=state,
            total_shares=post_total,
            unknown_cost_shares=post_unknown,
            input_hard_valid=input_hard_valid,
            input_quality_reason_codes=input_quality_reason_codes,
        )
        post_effective_at = (
            pre_effective_at
            if prepared_minute_path.latest_timestamp is None
            else max(pre_effective_at, prepared_minute_path.latest_timestamp)
        )
        snapshot_id = _snapshot_id(
            symbol=state.symbol,
            trading_date=decision_at.date(),
            decision_at=decision_at,
            effective_at=post_effective_at,
            available_at=available_at,
            phase=SnapshotPhase.POST,
            model_version=self.model_version,
            grid_version=self.grid.grid_version,
            seller_model=self.seller_model,
            free_float_shares=free_float,
            latent_supply_shares=latent_supply,
            input_snapshot_ids=post_input_ids,
            hard_valid=post_hard_valid,
            quality_reason_codes=post_codes,
            inventory_cell_count=len(lots),
            inventory_total_shares=post_total,
            known_cost_shares=post_known,
            unknown_cost_shares=post_unknown,
        )
        transition = None
        if build_transition:
            transition_inputs = post_input_ids
            payload: dict[str, object] = {
                "symbol": state.symbol,
                "trading_date": decision_at.date().isoformat(),
                "source_snapshot_id": previous_snapshot_id,
                "pre_snapshot_id": pre_snapshot_id,
                "destination_snapshot_id": snapshot_id,
                "model_version": self.model_version,
                "grid_version": self.grid.grid_version,
                "arc_count": len(arcs),
                "fixed_pre_eligible_shares": fixed_pre_eligible,
                "executed_sell_shares": prepared_minute_path.total_volume,
                "input_snapshot_ids": transition_inputs,
            }
            transition = _WorkingTransition(
                transition_id=stable_id("origin_survival_transition", payload),
                source_cell_ids=tuple(source for source, _, _ in arcs),
                destination_cell_ids=tuple(destination for _, destination, _ in arcs),
                retained_fractions=tuple(retained for _, _, retained in arcs),
                fixed_pre_eligible_shares=fixed_pre_eligible,
                executed_sell_shares=prepared_minute_path.total_volume,
                same_day_resale_shares=0.0,
            )
        return MutableChipState(
            symbol=state.symbol,
            trading_date=decision_at.date(),
            decision_at=decision_at,
            effective_at=post_effective_at,
            available_at=available_at,
            snapshot_id=snapshot_id,
            model_version=self.model_version,
            grid_version=self.grid.grid_version,
            seller_model=self.seller_model,
            lots=lots,
            free_float_shares=free_float,
            latent_supply_shares=latent_supply,
            input_snapshot_ids=post_input_ids,
            hard_valid=post_hard_valid,
            quality_reason_codes=post_codes,
            last_transition=transition,
        )

    def _validate_daily_inputs(
        self,
        *,
        previous_post: ChipSnapshotV2 | MutableChipState,
        decision_at: datetime,
        available_at: datetime,
        inventory_events: tuple[InventoryEvent, ...],
    ) -> None:
        if previous_post.phase != SnapshotPhase.POST:
            raise ChipStateContractError("daily migration requires previous POST snapshot")
        if previous_post.model_version != self.model_version:
            raise ChipStateContractError("previous snapshot model_version mismatch")
        if previous_post.grid_version != self.grid.grid_version:
            raise ChipStateContractError("previous snapshot grid_version mismatch")
        if previous_post.seller_model != self.seller_model:
            raise ChipStateContractError("previous snapshot seller_model mismatch")
        if decision_at.date() <= previous_post.trading_date:
            raise ChipStateContractError("daily migration must advance the trading date")
        if available_at > decision_at:
            raise ChipStateContractError("daily output is unavailable at decision_at")
        event_keys = tuple((event.effective_at, event.event_id) for event in inventory_events)
        if event_keys != tuple(sorted(event_keys)):
            raise ChipStateContractError("inventory events must be effective-time sorted")
        if len({event.event_id for event in inventory_events}) != len(inventory_events):
            raise ChipStateContractError("inventory event ids must be unique")
        for event in inventory_events:
            if not previous_post.decision_at < event.effective_at <= decision_at:
                raise ChipStateContractError("inventory event is outside the daily bridge")
            if event.available_at > decision_at:
                raise ChipStateContractError("inventory event uses future information")

    def _age_previous_inventory(self, previous_post: ChipSnapshotV2) -> list[_WorkingLot]:
        lots: list[_WorkingLot] = []
        for cell in previous_post.inventory.cells:
            holding_days = cell.holding_days
            if holding_days >= 0:
                holding_days = min(holding_days + 1, self.max_holding_days)
            lots.append(
                _WorkingLot(
                    source_cell_id=cell.cell_id,
                    cost_bucket_id=cell.cost_bucket_id,
                    holding_days=holding_days,
                    sensitivity=cell.sensitivity,
                    acquisition_cost=cell.acquisition_cost,
                    economic_break_even=cell.economic_break_even,
                    shares=cell.shares,
                    initialization_prior_units=cell.initialization_prior_units,
                    lineage_denominator_shares=cell.shares,
                )
            )
        return lots

    def _apply_inventory_event(
        self,
        *,
        lots: list[_WorkingLot],
        free_float: float,
        latent_supply: float,
        event: InventoryEvent,
    ) -> tuple[float, float]:
        if event.kind == InventoryEventKind.CASH_DIVIDEND:
            for lot in lots:
                if lot.economic_break_even is not None:
                    lot.economic_break_even = rebase_economic_price(
                        lot.economic_break_even,
                        cash_per_share=event.cash_per_share,
                    )
                    lot.refresh_cell_id()
        elif event.kind == InventoryEventKind.SPLIT:
            ratio = event.share_ratio
            for lot in lots:
                lot.shares *= ratio
                lot.lineage_denominator_shares *= ratio
                if lot.acquisition_cost is not None:
                    lot.acquisition_cost = rebase_economic_price(
                        lot.acquisition_cost, share_multiplier=ratio
                    )
                    if lot.economic_break_even is None:
                        raise ChipStateContractError(
                            "known-cost lot contains a missing break-even price"
                        )
                    lot.economic_break_even = rebase_economic_price(
                        lot.economic_break_even, share_multiplier=ratio
                    )
                    lot.cost_bucket_id = self.grid.bucket_for_price(lot.acquisition_cost)
                    lot.refresh_cell_id()
            free_float *= ratio
            latent_supply *= ratio
        elif event.kind == InventoryEventKind.FLOAT_ADD_KNOWN:
            assert event.issue_price is not None
            lots.append(
                _WorkingLot(
                    source_cell_id=None,
                    cost_bucket_id=self.grid.bucket_for_price(event.issue_price),
                    holding_days=0,
                    sensitivity=event.sensitivity,
                    acquisition_cost=event.issue_price,
                    economic_break_even=event.issue_price,
                    shares=event.shares,
                    initialization_prior_units=0.0,
                    lineage_denominator_shares=0.0,
                )
            )
            free_float += event.shares
        elif event.kind == InventoryEventKind.FLOAT_ADD_UNKNOWN:
            lots.append(
                _WorkingLot(
                    source_cell_id=None,
                    cost_bucket_id=None,
                    holding_days=-1,
                    sensitivity=event.sensitivity,
                    acquisition_cost=None,
                    economic_break_even=None,
                    shares=event.shares,
                    initialization_prior_units=0.0,
                    lineage_denominator_shares=0.0,
                )
            )
            free_float += event.shares
        elif event.kind == InventoryEventKind.FLOAT_REMOVE_EXPLICIT:
            by_source = {lot.source_cell_id: lot for lot in lots if lot.source_cell_id is not None}
            for source_id, amount in event.source_removals:
                source_lot = by_source.get(source_id)
                if source_lot is None:
                    raise ChipStateContractError(
                        f"float removal source cell is unavailable: {source_id}"
                    )
                if amount > source_lot.shares + tolerance(source_lot.shares):
                    raise ChipStateContractError("float removal exceeds its source lot")
                before = source_lot.shares
                source_lot.shares -= amount
                if source_lot.shares < 0:
                    raise ChipStateContractError("float removal made a source lot negative")
                source_lot.initialization_prior_units *= source_lot.shares / before
            free_float -= event.shares
            if free_float <= 0:
                raise ChipStateContractError("float removal made free float non-positive")
        elif event.kind == InventoryEventKind.LATENT_SUPPLY_CHANGE:
            pass
        latent_supply += event.latent_supply_delta
        if latent_supply < 0:
            raise ChipStateContractError("inventory event made latent supply negative")
        return free_float, latent_supply

    def _seller_hazard(self, lot: _WorkingLot, price: float) -> float:
        if self.seller_model == SellerModel.UNIFORM:
            return 1.0
        if self.seller_model == SellerModel.DISPOSITION:
            if lot.acquisition_cost is None:
                return 1.0
            pnl = (price - lot.acquisition_cost) / lot.acquisition_cost
            return math.exp(max(-2.0, min(2.0, 1.5 * pnl)))
        sensitivity_weight = {
            TurnoverSensitivity.ACTIVE: 2.0,
            TurnoverSensitivity.NEUTRAL: 1.0,
            TurnoverSensitivity.STICKY: 0.25,
        }
        return sensitivity_weight[lot.sensitivity]

    @staticmethod
    def _bridge_residual_with_bounds(
        values: FloatArray,
        *,
        target: float,
        upper_bounds: FloatArray,
    ) -> None:
        """Bridge floating-point residuals without creating source inventory."""

        upper_total = float(upper_bounds.sum())
        allowed_error = tolerance(max(upper_total, 1.0))
        if target < -allowed_error or target > upper_total + allowed_error:
            raise ChipStateContractError("seller allocation target is outside source bounds")
        target = min(upper_total, max(0.0, target))
        np.clip(values, 0.0, upper_bounds, out=values)

        current = float(values.sum())
        if current > target:
            if target == 0:
                values[:] = 0.0
            else:
                values *= target / current
        elif current < target:
            capacity = upper_bounds - values
            capacity_total = float(capacity.sum())
            needed = target - current
            if needed > capacity_total + allowed_error:
                raise ChipStateContractError("seller allocation has no residual capacity")
            if capacity_total > 0:
                values += capacity * (needed / capacity_total)

        # One bounded correction removes the final summation-rounding residue.
        residual = target - float(values.sum())
        if residual > 0:
            capacity = upper_bounds - values
            index = int(np.argmax(capacity))
            if residual > capacity[index] + allowed_error:
                raise ChipStateContractError("seller allocation residual exceeds capacity")
            values[index] += min(residual, capacity[index])
        elif residual < 0:
            index = int(np.argmax(values))
            if -residual > values[index] + allowed_error:
                raise ChipStateContractError("seller allocation residual exceeds inventory")
            values[index] -= min(-residual, values[index])

        np.clip(values, 0.0, upper_bounds, out=values)

    @staticmethod
    def _deplete_vector(
        shares: FloatArray,
        requested: float,
        hazards: FloatArray,
    ) -> None:
        """Apply the existing water-fill allocation in vector form."""

        if requested == 0:
            return
        upper_bounds = shares.copy()
        before_total = float(shares.sum())
        if requested > before_total + tolerance(before_total):
            raise ChipStateContractError("minute sale exceeds remaining PRE inventory")
        remaining = requested
        while remaining > 0:
            active = shares > 0
            if not bool(active.any()):
                raise ChipStateContractError("seller allocation exhausted PRE inventory")
            indices = np.flatnonzero(active)
            capacities = shares[indices]
            weights = capacities * hazards[indices]
            total_weight = float(weights.sum())
            if total_weight <= 0:
                raise ChipStateContractError("seller model assigned zero hazard to all PRE lots")
            proposals = remaining * weights / total_weight
            saturated = proposals >= capacities
            if not bool(saturated.any()):
                shares[indices] -= proposals
                remaining = 0.0
                break
            saturated_indices = indices[saturated]
            removed = float(shares[saturated_indices].sum())
            shares[saturated_indices] = 0.0
            remaining -= removed
            if remaining < 0 and abs(remaining) <= tolerance(requested):
                remaining = 0.0

        target = before_total - requested
        DailyMigrationEngine._bridge_residual_with_bounds(
            shares,
            target=target,
            upper_bounds=upper_bounds,
        )
        if float(shares.min(initial=0.0)) < -tolerance(before_total):
            raise ChipStateContractError("seller allocation made PRE inventory negative")

    @staticmethod
    def _deplete_vector_fast(
        shares: FloatArray,
        requested: float,
        hazards: FloatArray,
    ) -> None:
        """Apply one minute without an unnecessary per-minute residual bridge.

        The common case has no exhausted source cell, so the water-fill result
        is one proportional vector subtraction.  The caller performs the exact
        bounded conservation bridge once after the complete minute path.  If a
        cell would be exhausted, retain the original exact water-fill fallback.
        """

        if requested == 0:
            return
        before_total = float(shares.sum())
        if requested > before_total + tolerance(before_total):
            raise ChipStateContractError("minute sale exceeds remaining PRE inventory")
        weights = shares * hazards
        total_weight = float(weights.sum())
        if total_weight <= 0:
            raise ChipStateContractError("seller model assigned zero hazard to all PRE lots")
        proposals = requested * weights / total_weight
        if bool(np.all(proposals <= shares)):
            shares -= proposals
            return
        DailyMigrationEngine._deplete_vector(shares, requested, hazards)

    def _source_remaining_after_path(
        self,
        source: _PreparedSourceState,
        minute_path: PreparedMinutePath,
    ) -> tuple[Int64Array, FloatArray]:
        source_indices = source.indices
        original = source.shares
        if original.size == 0:
            return source_indices, original
        total_volume = minute_path.total_volume

        if self.seller_model == SellerModel.UNIFORM:
            target = float(original.sum()) - total_volume
            remaining = original * (target / float(original.sum()))
            self._bridge_residual_with_bounds(
                remaining,
                target=target,
                upper_bounds=original,
            )
            return source_indices, remaining

        if self.seller_model == SellerModel.ACTIVE_STICKY:
            weights_by_sensitivity = {
                TurnoverSensitivity.ACTIVE: 2.0,
                TurnoverSensitivity.NEUTRAL: 1.0,
                TurnoverSensitivity.STICKY: 0.25,
            }
            sensitivity_order = tuple(TurnoverSensitivity)
            group_of = source.sensitivity_codes
            grouped_original = np.asarray(
                [float(original[group_of == group].sum()) for group in range(3)]
            )
            grouped_remaining, completed = _active_sticky_path_no_saturation(
                grouped_original,
                minute_path.volumes,
            )
            if not completed:
                grouped_remaining = grouped_original.copy()
                hazards = np.asarray(
                    [weights_by_sensitivity[sensitivity] for sensitivity in sensitivity_order]
                )
                for volume in minute_path.volumes:
                    self._deplete_vector_fast(
                        grouped_remaining,
                        float(volume),
                        hazards,
                    )
            self._bridge_residual_with_bounds(
                grouped_remaining,
                target=float(grouped_original.sum()) - total_volume,
                upper_bounds=grouped_original,
            )
            remaining = np.zeros_like(original)
            for group in range(3):
                members = np.flatnonzero(group_of == group)
                if members.size == 0:
                    continue
                target = grouped_remaining[group]
                remaining[members] = original[members] * (target / grouped_original[group])
                group_remaining = remaining[members].copy()
                self._bridge_residual_with_bounds(
                    group_remaining,
                    target=target,
                    upper_bounds=original[members],
                )
                remaining[members] = group_remaining
            return source_indices, remaining

        costs = source.costs
        known = np.isfinite(costs)

        # The disposition hazard depends on acquisition cost, not holding age or
        # lineage.  Collapse exact-equal costs before walking the minute path,
        # then distribute each cost group's surviving mass back pro rata.  This
        # preserves the existing model exactly while avoiding repeated work for
        # cells that differ only in non-hazard dimensions.
        known_indices = np.flatnonzero(known)
        unknown_indices = np.flatnonzero(~known)
        if known_indices.size:
            group_costs, known_group_of = np.unique(costs[known_indices], return_inverse=True)
        else:
            group_costs = np.empty(0, dtype=np.float64)
            known_group_of = np.empty(0, dtype=np.int64)
        group_of = np.empty(original.size, dtype=np.int64)
        group_of[known_indices] = known_group_of
        group_known: BoolArray = np.ones(group_costs.size, dtype=np.bool_)
        if unknown_indices.size:
            unknown_group = group_costs.size
            group_of[unknown_indices] = unknown_group
            group_costs = np.append(group_costs, np.nan)
            group_known = np.append(group_known, False)
        grouped_original = np.bincount(
            group_of,
            weights=original,
            minlength=group_costs.size,
        ).astype(np.float64, copy=False)
        grouped_remaining, completed = disposition_path_no_saturation(
            grouped_original,
            group_costs,
            group_known,
            minute_path.prices,
            minute_path.volumes,
        )
        if completed:
            fractions = np.divide(
                grouped_remaining,
                grouped_original,
                out=np.zeros_like(grouped_remaining),
                where=grouped_original > 0,
            )
            remaining = original * fractions[group_of]
        if not completed:
            # Exhaustion is uncommon, but it needs the exact bounded
            # water-fill semantics rather than an approximation.
            remaining = original.copy()
            hazards = np.ones_like(remaining)
            for price, volume in zip(
                minute_path.prices, minute_path.volumes, strict=True
            ):
                pnl = (float(price) - costs[known]) / costs[known]
                hazards[known] = np.exp(np.clip(1.5 * pnl, -2.0, 2.0))
                self._deplete_vector_fast(remaining, float(volume), hazards)
        self._bridge_residual_with_bounds(
            remaining,
            target=float(original.sum()) - total_volume,
            upper_bounds=original,
        )
        return source_indices, remaining

    def _purchase_lots(
        self,
        minute_path: PreparedMinutePath,
    ) -> tuple[_WorkingLot, ...]:
        """Build same-day buyer lots once from the already bucketed minute path."""
        if self.seller_model != SellerModel.ACTIVE_STICKY:
            return tuple(
                _WorkingLot(
                    source_cell_id=None,
                    cost_bucket_id=bucket_id,
                    holding_days=0,
                    sensitivity=TurnoverSensitivity.NEUTRAL,
                    acquisition_cost=price,
                    economic_break_even=price,
                    shares=volume_shares,
                    initialization_prior_units=0.0,
                    lineage_denominator_shares=0.0,
                )
                for bucket_id, price, volume_shares in minute_path.bucket_purchases
            )

        result: list[_WorkingLot] = []
        allocations = (
            (TurnoverSensitivity.ACTIVE, self.active_purchase_fraction),
            (TurnoverSensitivity.STICKY, 1 - self.active_purchase_fraction),
        )
        for bucket_id, price, volume_shares in minute_path.bucket_purchases:
            for sensitivity, fraction in allocations:
                if fraction <= 0:
                    continue
                result.append(
                    _WorkingLot(
                        source_cell_id=None,
                        cost_bucket_id=bucket_id,
                        holding_days=0,
                        sensitivity=sensitivity,
                        acquisition_cost=price,
                        economic_break_even=price,
                        shares=volume_shares * fraction,
                        initialization_prior_units=0.0,
                        lineage_denominator_shares=0.0,
                    )
                )
        return tuple(result)

    def _migrate_minute_path(
        self,
        lots: list[_WorkingLot],
        source: _PreparedSourceState,
        minute_path: PreparedMinutePath,
    ) -> tuple[tuple[_WorkingLot, ...], bool]:
        """Migrate a day once, aggregating identical same-day purchase cells."""

        source_indices, remaining = self._source_remaining_after_path(source, minute_path)
        exhausted_source = False
        for index, shares in zip(source_indices, remaining, strict=True):
            lot = lots[int(index)]
            before = lot.shares
            lot.shares = max(0.0, float(shares))
            exhausted_source = exhausted_source or lot.shares == 0.0
            lot.initialization_prior_units *= lot.shares / before

        return self._purchase_lots(minute_path), exhausted_source

    def _allocate_sellers(
        self, lots: list[_WorkingLot], requested: float, price: float
    ) -> tuple[float, ...]:
        if requested == 0:
            return tuple(0.0 for _ in lots)
        total_available = math.fsum(lot.shares for lot in lots if lot.source_cell_id is not None)
        if requested > total_available + tolerance(total_available):
            raise ChipStateContractError("minute sale exceeds remaining PRE inventory")
        allocations = [0.0] * len(lots)
        unresolved = {
            index
            for index, lot in enumerate(lots)
            if lot.source_cell_id is not None and lot.shares > 0
        }
        remaining = requested
        while remaining > 0 and unresolved:
            weights = {
                index: (lots[index].shares - allocations[index])
                * self._seller_hazard(lots[index], price)
                for index in unresolved
            }
            total_weight = math.fsum(weights.values())
            if total_weight <= 0:
                raise ChipStateContractError("seller model assigned zero hazard to all PRE lots")
            proposals = {
                index: remaining * weight / total_weight for index, weight in weights.items()
            }
            saturated = tuple(
                sorted(
                    index
                    for index, proposed in proposals.items()
                    if proposed >= lots[index].shares - allocations[index]
                )
            )
            if not saturated:
                for index in sorted(unresolved):
                    allocations[index] += proposals[index]
                remaining = 0.0
                break
            removed = 0.0
            for index in saturated:
                capacity = lots[index].shares - allocations[index]
                allocations[index] += capacity
                removed += capacity
                unresolved.remove(index)
            remaining -= removed
            if remaining < 0 and abs(remaining) <= tolerance(requested):
                remaining = 0.0
        allocated = math.fsum(allocations)
        residual = requested - allocated
        if residual != 0:
            if abs(residual) > tolerance(requested):
                raise ChipStateContractError("seller allocation failed exact volume bridge")
            if residual > 0:
                candidates = tuple(
                    index
                    for index, lot in enumerate(lots)
                    if lot.source_cell_id is not None
                    and lot.shares - allocations[index] >= residual
                )
                if not candidates:
                    raise ChipStateContractError("seller allocation has no residual capacity")
                allocations[candidates[0]] += residual
            else:
                candidates = tuple(
                    index for index, amount in enumerate(allocations) if amount >= -residual
                )
                if not candidates:
                    raise ChipStateContractError("seller allocation cannot remove residual")
                allocations[candidates[0]] += residual
        if any(
            amount < 0 or amount > lot.shares + tolerance(lot.shares)
            for lot, amount in zip(lots, allocations, strict=True)
        ):
            raise ChipStateContractError("seller allocation exceeded a PRE source lot")
        if abs(math.fsum(allocations) - requested) > tolerance(requested):
            raise ChipStateContractError("seller allocation does not bridge minute volume")
        return tuple(allocations)

    def _purchase_cells(self, *, price: float, shares: float) -> tuple[InventoryCell, ...]:
        bucket_id = self.grid.bucket_for_price(price)
        allocations: tuple[tuple[TurnoverSensitivity, float], ...]
        if self.seller_model == SellerModel.ACTIVE_STICKY:
            allocations = (
                (TurnoverSensitivity.ACTIVE, self.active_purchase_fraction),
                (TurnoverSensitivity.STICKY, 1 - self.active_purchase_fraction),
            )
        else:
            allocations = ((TurnoverSensitivity.NEUTRAL, 1.0),)
        return tuple(
            InventoryCell.create(
                cost_bucket_id=bucket_id,
                holding_days=0,
                sensitivity=sensitivity,
                acquisition_cost=price,
                economic_break_even=price,
                shares=shares * fraction,
            )
            for sensitivity, fraction in allocations
            if fraction > 0
        )

    def _quality_state(
        self,
        *,
        previous_post: ChipSnapshotV2 | MutableChipState,
        inventory: SparseChipInventory,
        input_hard_valid: bool,
        input_quality_reason_codes: tuple[str, ...],
    ) -> tuple[tuple[str, ...], bool]:
        return self._quality_state_from_mass(
            previous_post=previous_post,
            total_shares=inventory.total_shares,
            unknown_cost_shares=inventory.unknown_cost_shares,
            input_hard_valid=input_hard_valid,
            input_quality_reason_codes=input_quality_reason_codes,
        )

    def _quality_state_from_mass(
        self,
        *,
        previous_post: ChipSnapshotV2 | MutableChipState,
        total_shares: float,
        unknown_cost_shares: float,
        input_hard_valid: bool,
        input_quality_reason_codes: tuple[str, ...],
    ) -> tuple[tuple[str, ...], bool]:
        recoverable = {"UNKNOWN_COST_INITIALIZATION", "UNKNOWN_COST_PRESENT"}
        reasons = {
            reason for reason in previous_post.quality_reason_codes if reason not in recoverable
        }
        reasons.update(input_quality_reason_codes)
        if not previous_post.hard_valid and not previous_post.quality_reason_codes:
            reasons.add("PREVIOUS_HARD_INVALID")
        if unknown_cost_shares > tolerance(total_shares):
            reasons.add("UNKNOWN_COST_PRESENT")
        hard_valid = input_hard_valid and not reasons
        return tuple(sorted(reasons)), hard_valid

    def _build_transition(
        self,
        *,
        previous_post: ChipSnapshotV2,
        pre_snapshot_id: str,
        post_snapshot: ChipSnapshotV2,
        source_lots: list[_WorkingLot],
        decision_at: datetime,
        available_at: datetime,
        effective_at: datetime,
        fixed_pre_eligible_shares: float,
        executed_sell_shares: float,
        input_snapshot_ids: tuple[str, ...],
    ) -> OriginSurvivalTransition:
        arcs: list[tuple[int, int, float]] = []
        arcs_in_order = True
        previous_arc: tuple[int, int] | None = None
        for lot in source_lots:
            if lot.source_cell_id is None:
                continue
            if lot.lineage_denominator_shares <= 0:
                raise ChipStateContractError("source lineage denominator is non-positive")
            retained = lot.shares / lot.lineage_denominator_shares
            if retained < 0 and abs(retained) <= tolerance(1.0):
                retained = 0.0
            if retained > 1 and retained - 1 <= tolerance(1.0):
                retained = 1.0
            arc_key = (lot.source_cell_id, lot.cell_id)
            if previous_arc is not None and arc_key <= previous_arc:
                arcs_in_order = False
            previous_arc = arc_key
            arcs.append((*arc_key, retained))
        if not arcs_in_order:
            arcs.sort()
        for previous, current in pairwise(arcs):
            if previous[:2] == current[:2]:
                raise ChipStateContractError("daily source lineage produced duplicate arcs")
        payload: dict[str, object] = {
            "symbol": previous_post.symbol,
            "trading_date": decision_at.date().isoformat(),
            "source_snapshot_id": previous_post.snapshot_id,
            "pre_snapshot_id": pre_snapshot_id,
            "destination_snapshot_id": post_snapshot.snapshot_id,
            "model_version": self.model_version,
            "grid_version": self.grid.grid_version,
            "arc_count": len(arcs),
            "fixed_pre_eligible_shares": fixed_pre_eligible_shares,
            "executed_sell_shares": executed_sell_shares,
            "input_snapshot_ids": input_snapshot_ids,
        }
        return OriginSurvivalTransition(
            transition_id=stable_id("origin_survival_transition", payload),
            symbol=previous_post.symbol,
            trading_date=decision_at.date(),
            decision_at=decision_at,
            effective_at=effective_at,
            available_at=available_at,
            source_snapshot_id=previous_post.snapshot_id,
            pre_snapshot_id=pre_snapshot_id,
            destination_snapshot_id=post_snapshot.snapshot_id,
            model_version=self.model_version,
            grid_version=self.grid.grid_version,
            source_cell_ids=tuple(source for source, _, _ in arcs),
            destination_cell_ids=tuple(destination for _, destination, _ in arcs),
            retained_fractions=tuple(retained for _, _, retained in arcs),
            fixed_pre_eligible_shares=fixed_pre_eligible_shares,
            executed_sell_shares=executed_sell_shares,
            same_day_resale_shares=0.0,
            input_snapshot_ids=input_snapshot_ids,
        )
