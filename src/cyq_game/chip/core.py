from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from math import ceil, exp, floor, log
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from cyq_game.chip.price_coordinate import (
    PRICE_COORDINATE_NAME,
    rebase_economic_price,
)

FloatArray = NDArray[np.float64]
MASS_TOLERANCE = 1e-8


@dataclass(frozen=True)
class LogPriceGrid:
    prices: FloatArray
    step_pct: float
    _log_prices: FloatArray = field(init=False, repr=False, compare=False)
    _regular_log_step: float | None = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.prices.ndim != 1 or len(self.prices) == 0:
            raise ValueError("log price grid must be a non-empty vector")
        if np.any(~np.isfinite(self.prices)):
            raise ValueError("log price grid prices must be finite")
        if np.any(self.prices <= 0.0):
            raise ValueError("log price grid prices must be positive")
        if not np.isfinite(self.step_pct) or not 0.0 < self.step_pct < 1.0:
            raise ValueError("log price grid step_pct must be finite and in (0, 1)")
        if len(self.prices) > 1 and np.any(np.diff(self.prices) <= 0.0):
            raise ValueError("log price grid prices must be strictly increasing")
        log_prices = np.log(self.prices)
        object.__setattr__(self, "_log_prices", log_prices)
        expected_step = log(1.0 + self.step_pct)
        is_regular = len(log_prices) < 2 or bool(
            np.allclose(np.diff(log_prices), expected_step, rtol=1e-12, atol=1e-14)
        )
        object.__setattr__(self, "_regular_log_step", expected_step if is_regular else None)

    @classmethod
    def around(
        cls,
        low: float,
        high: float,
        step_pct: float = 0.01,
        padding: float = 0.30,
    ) -> LogPriceGrid:
        if low <= 0 or high < low or not 0 < step_pct < 1:
            raise ValueError("invalid price range or grid step")
        log_step = log(1.0 + step_pct)
        lower = log(low * (1.0 - padding))
        upper = log(high * (1.0 + padding))
        start = floor(lower / log_step) * log_step
        count = ceil((upper - start) / log_step) + 1
        return cls(np.exp(start + np.arange(count, dtype=np.float64) * log_step), step_pct)

    def bucket(self, price: float) -> int:
        if price < self.prices[0] or price > self.prices[-1]:
            raise ValueError("price lies outside grid; expand before updating")
        log_price = log(price)
        insertion = int(np.searchsorted(self._log_prices, log_price))
        if insertion <= 0:
            return 0
        if insertion >= len(self._log_prices):
            return len(self._log_prices) - 1
        left = insertion - 1
        return (
            left
            if log_price - self._log_prices[left]
            <= self._log_prices[insertion] - log_price
            else insertion
        )

    def volume_at_price(self, low: float, high: float, close: float) -> FloatArray:
        """Daily fallback: a low-typical-high triangle with a small close emphasis."""
        if not self.prices[0] <= low <= high <= self.prices[-1]:
            raise ValueError("bar lies outside price grid")
        typical = (low + high + close) / 3.0
        width = max(high - low, typical * self.step_pct)
        triangle = np.maximum(0.0, 1.0 - np.abs(self.prices - typical) / width)
        close_width = max(width * 0.25, close * self.step_pct)
        close_weight = np.maximum(0.0, 1.0 - np.abs(self.prices - close) / close_width)
        weights = triangle + 0.25 * close_weight
        if float(weights.sum()) <= 0:
            weights[self.bucket(close)] = 1.0
        return np.array(weights / float(weights.sum()), dtype=np.float64)

    def observed_volume_at_price(
        self,
        prices: Sequence[float],
        volumes: Sequence[float],
    ) -> FloatArray:
        """Aggregate observed intraday volume onto this log-price grid."""

        price_array = np.asarray(prices, dtype=np.float64)
        volume_array = np.asarray(volumes, dtype=np.float64)
        if price_array.ndim != 1 or volume_array.ndim != 1:
            raise ValueError("observed prices and volumes must be one-dimensional")
        if price_array.size == 0 or price_array.shape != volume_array.shape:
            raise ValueError("observed prices and volumes must be non-empty and aligned")
        if np.any(~np.isfinite(price_array)) or np.any(price_array <= 0):
            raise ValueError("observed prices must be finite and positive")
        if np.any(~np.isfinite(volume_array)) or np.any(volume_array < 0):
            raise ValueError("observed volumes must be finite and non-negative")
        total = float(volume_array.sum())
        if total <= 0:
            raise ValueError("observed volume must be positive")
        if price_array.min() < self.prices[0] or price_array.max() > self.prices[-1]:
            raise ValueError("observed price lies outside grid; expand before updating")
        log_prices = np.log(price_array)
        if self._regular_log_step is None:
            insertion = np.searchsorted(self._log_prices, log_prices)
            left = np.clip(insertion - 1, 0, len(self._log_prices) - 1)
            right = np.clip(insertion, 0, len(self._log_prices) - 1)
        else:
            positions = (log_prices - self._log_prices[0]) / self._regular_log_step
            left = np.clip(
                np.floor(positions).astype(np.intp),
                0,
                len(self._log_prices) - 1,
            )
            right = np.minimum(left + 1, len(self._log_prices) - 1)
        indexes = np.where(
            np.abs(self._log_prices[left] - log_prices)
            <= np.abs(self._log_prices[right] - log_prices),
            left,
            right,
        )
        weights = np.bincount(
            indexes,
            weights=volume_array,
            minlength=len(self.prices),
        )
        return weights / total


@dataclass(frozen=True)
class ChipState:
    grid: LogPriceGrid
    mass: FloatArray
    as_of: date
    engine: str
    quality: float
    age_mass: FloatArray | None = None
    degraded_mode: str | None = None
    price_basis: str = PRICE_COORDINATE_NAME
    cash_distributions_per_share: float = 0.0
    applied_action_ids: tuple[str, ...] = ()
    action_ledger_version: str = "chip-action-ledger-v2"
    action_blocking: bool = False
    _mass_sum: float = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.mass.shape != self.grid.prices.shape:
            raise ValueError("chip mass shape does not match grid")
        if np.any(~np.isfinite(self.mass)):
            raise MassConservationError("chip mass must be finite")
        if not np.isfinite(self.quality):
            raise ValueError("chip state quality must be finite")
        if not 0.0 <= self.quality <= 1.0:
            raise ValueError("chip state quality must be in [0, 1]")
        if self.price_basis != PRICE_COORDINATE_NAME:
            raise ValueError("chip state must use the canonical economic price basis")
        if (
            not np.isfinite(self.cash_distributions_per_share)
            or self.cash_distributions_per_share < 0
        ):
            raise ValueError("cash distribution ledger must be finite and non-negative")
        if len(set(self.applied_action_ids)) != len(self.applied_action_ids):
            raise ValueError("applied corporate action ids must be unique")
        if np.any(self.mass < -1e-12):
            raise MassConservationError("negative chip mass")
        mass_sum = float(self.mass.sum())
        object.__setattr__(self, "_mass_sum", mass_sum)
        if abs(mass_sum - 1.0) > MASS_TOLERANCE:
            raise MassConservationError("chip mass must sum to one")
        if self.age_mass is not None:
            if np.any(~np.isfinite(self.age_mass)):
                raise MassConservationError("cohort mass must be finite")
            if self.age_mass.shape[0] != self.mass.shape[0]:
                raise ValueError("cohort price dimension mismatch")
            if np.max(np.abs(self.age_mass.sum(axis=1) - self.mass)) > MASS_TOLERANCE:
                raise MassConservationError("cohort and marginal masses disagree")

    def cdf(self, price: float) -> float:
        return float(self.mass[self.grid.prices <= price].sum())

    def quantile(self, probability: float) -> float:
        if not 0 <= probability <= 1:
            raise ValueError("probability must be in [0,1]")
        index = int(np.searchsorted(np.cumsum(self.mass), probability, side="left"))
        return float(self.grid.prices[min(index, len(self.grid.prices) - 1)])

    @property
    def average_cost(self) -> float:
        return float(np.dot(self.grid.prices, self.mass))

    @property
    def economic_average_cost(self) -> float:
        """Average cost in the canonical economic break-even coordinate."""

        return self.average_cost

    @property
    def mass_sum(self) -> float:
        return self._mass_sum


class MassConservationError(RuntimeError):
    pass


def ensure_grid(state: ChipState, low: float, high: float) -> ChipState:
    """Expand a chip grid without changing its economic mass.

    Daily prices can leave the initial padded range after a long trend. Existing
    price and age cohorts are assigned to their nearest bucket on the new log grid;
    no normalization or synthetic holdings are introduced.
    """

    if state.grid.prices[0] <= low and high <= state.grid.prices[-1]:
        return state
    new_grid = LogPriceGrid.around(
        min(low, float(state.grid.prices[0])),
        max(high, float(state.grid.prices[-1])),
        state.grid.step_pct,
    )
    new_mass = np.zeros_like(new_grid.prices)
    indexes = np.array(
        [new_grid.bucket(float(price)) for price in state.grid.prices],
        dtype=np.int64,
    )
    np.add.at(new_mass, indexes, state.mass)
    new_age: FloatArray | None = None
    if state.age_mass is not None:
        new_age = np.zeros((len(new_grid.prices), state.age_mass.shape[1]), dtype=np.float64)
        np.add.at(new_age, indexes, state.age_mass)
    return ChipState(
        grid=new_grid,
        mass=new_mass,
        as_of=state.as_of,
        engine=state.engine,
        quality=state.quality,
        age_mass=new_age,
        degraded_mode=state.degraded_mode,
        price_basis=state.price_basis,
        cash_distributions_per_share=state.cash_distributions_per_share,
        applied_action_ids=state.applied_action_ids,
        action_ledger_version=state.action_ledger_version,
        action_blocking=state.action_blocking,
    )


def _reprice_state(
    state: ChipState,
    adjusted_prices: FloatArray,
    *,
    as_of: date,
    action_name: str,
) -> ChipState:
    """Move every cost bucket onto an exact post-action price coordinate."""

    if adjusted_prices.shape != state.grid.prices.shape:
        raise ValueError(f"{action_name} price coordinate shape mismatch")
    if np.any(~np.isfinite(adjusted_prices)) or np.any(adjusted_prices <= 0):
        raise ValueError(f"{action_name} creates a non-positive price coordinate")
    if len(adjusted_prices) > 1 and np.any(np.diff(adjusted_prices) <= 0):
        raise ValueError(f"{action_name} price coordinate must remain increasing")
    return ChipState(
        grid=LogPriceGrid(adjusted_prices.copy(), state.grid.step_pct),
        mass=state.mass.copy(),
        as_of=as_of,
        engine=state.engine,
        quality=state.quality,
        age_mass=None if state.age_mass is None else state.age_mass.copy(),
        degraded_mode=state.degraded_mode,
        price_basis=state.price_basis,
        cash_distributions_per_share=state.cash_distributions_per_share,
        applied_action_ids=state.applied_action_ids,
        action_ledger_version=state.action_ledger_version,
        action_blocking=state.action_blocking,
    )


def apply_split_to_state(
    state: ChipState,
    ratio: float,
    as_of: date,
    *,
    action_id: str | None = None,
    blocking: bool = False,
) -> ChipState:
    """Rebase costs for a split/bonus issue with no rebucketing or mass loss."""

    if not np.isfinite(ratio) or ratio <= 0:
        raise ValueError("split ratio must be positive")
    if action_id is not None and action_id in state.applied_action_ids:
        return state
    rebased_prices = np.asarray(
        [
            rebase_economic_price(value, share_multiplier=ratio)
            for value in state.grid.prices
        ],
        dtype=np.float64,
    )
    rebased = _reprice_state(
        state,
        rebased_prices,
        as_of=as_of,
        action_name="split",
    )
    return ChipState(
        grid=rebased.grid,
        mass=rebased.mass,
        as_of=rebased.as_of,
        engine=rebased.engine,
        quality=rebased.quality,
        age_mass=rebased.age_mass,
        degraded_mode=rebased.degraded_mode,
        price_basis=rebased.price_basis,
        cash_distributions_per_share=rebased.cash_distributions_per_share / ratio,
        action_ledger_version=rebased.action_ledger_version,
        action_blocking=blocking,
        applied_action_ids=(
            (*rebased.applied_action_ids, action_id)
            if action_id is not None
            else rebased.applied_action_ids
        ),
    )


def apply_cash_dividend_to_state(
    state: ChipState,
    cash_per_share: float,
    as_of: date,
    *,
    action_id: str | None = None,
    blocking: bool = False,
) -> ChipState:
    """Rebase every pre-existing chip to its ex-date economic break-even."""

    if not np.isfinite(cash_per_share) or cash_per_share < 0:
        raise ValueError("cash dividend must be finite and non-negative")
    if action_id is not None and action_id in state.applied_action_ids:
        return state
    action_ids = state.applied_action_ids
    if action_id is not None:
        action_ids = (*action_ids, action_id)
    rebased_prices = np.asarray(
        [
            rebase_economic_price(value, cash_per_share=cash_per_share)
            for value in state.grid.prices
        ],
        dtype=np.float64,
    )
    rebased = _reprice_state(
        state,
        rebased_prices,
        as_of=as_of,
        action_name="cash_dividend",
    )
    return ChipState(
        grid=rebased.grid,
        mass=rebased.mass,
        as_of=rebased.as_of,
        engine=rebased.engine,
        quality=rebased.quality,
        age_mass=rebased.age_mass,
        degraded_mode=rebased.degraded_mode,
        price_basis=rebased.price_basis,
        cash_distributions_per_share=(
            rebased.cash_distributions_per_share + cash_per_share
        ),
        applied_action_ids=action_ids,
        action_ledger_version=rebased.action_ledger_version,
        action_blocking=blocking,
    )


def apply_corporate_actions_to_state(
    state: ChipState,
    *,
    as_of: date,
    share_multiplier: float = 1.0,
    cash_per_share: float = 0.0,
    action_id_prefix: str | None = None,
    blocking: bool = False,
) -> ChipState:
    """Apply the canonical causal action order to one chip state.

    The normalized daily source aggregates actions by symbol/date.  This
    helper is therefore the single adapter for that aggregate: cash is recorded
    first in the current-share ledger, then share-count actions rebase both raw
    cost coordinates and the ledger.  Replaying the same aggregate is a no-op
    when an action id prefix is supplied.
    """

    if not np.isfinite(share_multiplier) or share_multiplier <= 0:
        raise ValueError("share multiplier must be finite and positive")
    if not np.isfinite(cash_per_share) or cash_per_share < 0:
        raise ValueError("cash dividend must be finite and non-negative")
    updated = state
    if cash_per_share > 0:
        updated = apply_cash_dividend_to_state(
            updated,
            cash_per_share,
            as_of,
            action_id=None if action_id_prefix is None else f"{action_id_prefix}:cash",
            blocking=blocking,
        )
    if share_multiplier != 1.0:
        updated = apply_split_to_state(
            updated,
            share_multiplier,
            as_of,
            action_id=None if action_id_prefix is None else f"{action_id_prefix}:split",
            blocking=blocking,
        )
    return updated


class ChipEngine(Protocol):
    def initialize(self, grid: LogPriceGrid, q: FloatArray, as_of: date) -> ChipState: ...

    def update(
        self,
        previous: ChipState,
        q: FloatArray,
        turnover: float,
        close: float,
        as_of: date,
        *,
        suspended: bool = False,
    ) -> ChipState: ...


def replacement_fraction(turnover: float, lambda_turnover: float) -> float:
    if turnover < 0 or not 0.5 <= lambda_turnover <= 1.5:
        raise ValueError("invalid turnover or lambda")
    return min(1.0, 1.0 - exp(-lambda_turnover * turnover))


def validate_q(q: FloatArray, expected_shape: tuple[int, ...]) -> None:
    if q.shape != expected_shape or np.any(q < 0):
        raise ValueError("invalid new-chip distribution")
    if abs(float(q.sum()) - 1.0) > 1e-10:
        raise ValueError("new-chip distribution must be normalized independently")


class UniformChipEngine:
    def __init__(self, lambda_turnover: float = 1.0) -> None:
        self.lambda_turnover = lambda_turnover

    def initialize(self, grid: LogPriceGrid, q: FloatArray, as_of: date) -> ChipState:
        validate_q(q, grid.prices.shape)
        return ChipState(grid, q.copy(), as_of, "uniform", quality=0.60)

    def update(
        self,
        previous: ChipState,
        q: FloatArray,
        turnover: float,
        close: float,
        as_of: date,
        *,
        suspended: bool = False,
    ) -> ChipState:
        del close
        validate_q(q, previous.mass.shape)
        replace = 0.0 if suspended else replacement_fraction(turnover, self.lambda_turnover)
        mass = previous.mass * (1.0 - replace) + q * replace
        return ChipState(
            previous.grid,
            mass,
            as_of,
            "uniform",
            quality=0.60,
            price_basis=previous.price_basis,
            cash_distributions_per_share=previous.cash_distributions_per_share,
            applied_action_ids=previous.applied_action_ids,
            action_ledger_version=previous.action_ledger_version,
        )


class CohortChipEngine:
    """Price-age model with exact turnover solved via a bounded hazard and bisection."""

    def __init__(self, lambda_turnover: float = 1.0, max_age: int = 120) -> None:
        self.lambda_turnover = lambda_turnover
        self.max_age = max_age
        ages = np.arange(max_age + 1, dtype=np.float64)
        self._age_score = 0.65 + 0.35 * np.minimum(ages, 120.0) / 120.0

    def initialize(self, grid: LogPriceGrid, q: FloatArray, as_of: date) -> ChipState:
        validate_q(q, grid.prices.shape)
        cohorts = np.zeros((len(q), self.max_age + 1), dtype=np.float64)
        cohorts[:, 0] = q
        return ChipState(grid, q.copy(), as_of, "cohort", quality=0.70, age_mass=cohorts)

    def update(
        self,
        previous: ChipState,
        q: FloatArray,
        turnover: float,
        close: float,
        as_of: date,
        *,
        suspended: bool = False,
    ) -> ChipState:
        validate_q(q, previous.mass.shape)
        cohorts = previous.age_mass
        if cohorts is None:
            raise ValueError("cohort engine requires an age-mass state")
        if suspended:
            aged = _age_survivors(cohorts)
            return ChipState(
                previous.grid,
                aged.sum(axis=1),
                as_of,
                "cohort",
                0.55,
                aged,
                price_basis=previous.price_basis,
                cash_distributions_per_share=previous.cash_distributions_per_share,
                applied_action_ids=previous.applied_action_ids,
                action_ledger_version=previous.action_ledger_version,
            )
        replace = replacement_fraction(turnover, self.lambda_turnover)
        sold = self._sell_exact(previous.grid.prices, close, cohorts, replace)
        survivors = cohorts - sold
        if np.any(survivors < -1e-12):
            raise MassConservationError("sold mass exceeds holdings")
        aged = _age_survivors(survivors)
        aged[:, 0] += replace * q
        marginal = aged.sum(axis=1)
        if abs(float(sold.sum()) - replace) > 1e-8:
            raise MassConservationError("cohort sold mass differs from replacement")
        return ChipState(
            previous.grid,
            marginal,
            as_of,
            "cohort",
            0.75,
            aged,
            price_basis=previous.price_basis,
            cash_distributions_per_share=previous.cash_distributions_per_share,
            applied_action_ids=previous.applied_action_ids,
            action_ledger_version=previous.action_ledger_version,
        )

    def _sell_exact(
        self,
        prices: FloatArray,
        close: float,
        cohorts: FloatArray,
        target: float,
    ) -> FloatArray:
        """Solve turnover without constructing hazards for empty cohort cells."""

        active_indexes = np.flatnonzero(cohorts)
        if active_indexes.size * 2 >= cohorts.size:
            return _solve_exact_sold(
                cohorts,
                self._hazards(prices, close, cohorts.shape[1]),
                target,
            )
        price_indexes, age_indexes = np.divmod(active_indexes, cohorts.shape[1])
        price_score = self._price_scores(prices, close)
        age_score = self._age_scores(cohorts.shape[1])
        active_hazards = np.maximum(
            1e-9,
            price_score[price_indexes] * age_score[age_indexes],
        )
        active_mass = cohorts.ravel()[active_indexes]
        # active_mass is already compacted to strictly positive cells. Avoid a
        # second full nonzero scan inside the scalar solver on every symbol-day.
        active_sold = _solve_exact_sold(
            active_mass,
            active_hazards,
            target,
            compact_zeros=False,
        )
        sold = np.zeros_like(cohorts)
        sold.ravel()[active_indexes] = active_sold
        return sold

    def _hazards(self, prices: FloatArray, close: float, age_count: int) -> FloatArray:
        return np.maximum(
            1e-9,
            self._price_scores(prices, close)[:, None]
            * self._age_scores(age_count)[None, :],
        )

    @staticmethod
    def _price_scores(prices: FloatArray, close: float) -> FloatArray:
        profit = close / prices - 1.0
        # Directional, bounded prior; coefficients require OOS calibration before promotion.
        profit_score = 0.60 + 0.65 * np.minimum(np.abs(profit), 0.50) / 0.50
        loss_aversion = np.where(profit < 0, 0.85, 1.0)
        return np.array(profit_score * loss_aversion, dtype=np.float64)

    def _age_scores(self, age_count: int) -> FloatArray:
        if age_count == len(self._age_score):
            return self._age_score
        ages = np.arange(age_count, dtype=np.float64)
        return 0.65 + 0.35 * np.minimum(ages, 120.0) / 120.0


def _solve_exact_sold(
    mass: FloatArray,
    hazard: FloatArray,
    target: float,
    *,
    compact_zeros: bool = True,
) -> FloatArray:
    total = float(mass.sum())
    if target <= 0:
        return np.zeros_like(mass)
    if target >= total - 1e-14:
        return mass.copy()
    # Daily observations populate only a small fraction of price-age cells.
    # Zero-mass cells can never affect turnover, so skip their exponentials when
    # compaction removes at least half the work, then scatter back exactly.
    active_indexes: NDArray[np.intp] | None
    nonzero_indexes = np.flatnonzero(mass) if compact_zeros else None
    if nonzero_indexes is not None and nonzero_indexes.size * 2 < mass.size:
        active_indexes = nonzero_indexes
        work_mass = mass.ravel()[active_indexes]
        work_hazard = hazard.ravel()[active_indexes]
    else:
        active_indexes = None
        work_mass = mass
        work_hazard = hazard
    low = 0.0
    high = 1.0
    while float((work_mass * (1.0 - np.exp(-high * work_hazard))).sum()) < target:
        high *= 2.0
        if high > 1e12:
            raise MassConservationError("hazard solver failed to bracket turnover")
    # Solve the monotone scalar equation with safeguarded Newton steps.  The old
    # implementation performed 100 full-matrix exponentiations per update even
    # though the final residual is corrected exactly below.  Newton normally
    # converges in a handful of iterations; the bracketed midpoint fallback keeps
    # the same fail-closed behaviour for poorly conditioned inputs.
    weighted_hazard = float((work_mass * work_hazard).sum())
    first_order = target / max(weighted_hazard, 1e-300)
    # F(s) = E[m(1-exp(-s*h))].  The quadratic correction is a materially
    # better starting point than target/E[m*h] for ordinary A-share turnover,
    # and costs only a multiply/reduction rather than another full-matrix exp.
    weighted_hazard_sq = float((work_mass * work_hazard * work_hazard).sum())
    strength = first_order + (
        weighted_hazard_sq * target * target
        / max(2.0 * weighted_hazard * weighted_hazard * weighted_hazard, 1e-300)
    )
    strength = min(high, max(low, strength))
    survival: FloatArray | None = None
    converged = False
    for _ in range(32):
        current_survival = np.exp(-strength * work_hazard)
        survival = current_survival
        amount = float((work_mass * (1.0 - current_survival)).sum())
        residual = amount - target
        if abs(residual) <= 1e-14:
            converged = True
            break
        if residual < 0:
            low = strength
        else:
            high = strength
        derivative = float((work_mass * work_hazard * survival).sum())
        candidate = strength - residual / max(derivative, 1e-300)
        if not low < candidate < high:
            candidate = (low + high) / 2.0
        strength = candidate
    if survival is None:
        raise MassConservationError("hazard solver did not evaluate a candidate")
    if not converged:
        survival_array = np.asarray(
            np.exp(-strength * work_hazard), dtype=np.float64
        )
    else:
        survival_array = survival
    work_sold = work_mass * (1.0 - survival_array)
    residual = target - float(work_sold.sum())
    if abs(residual) > 1e-13:
        if residual > 0:
            correction_source = work_mass - work_sold
        else:
            correction_source = work_sold
        work_sold.flat[int(np.argmax(correction_source))] += residual
    if active_indexes is None:
        return work_sold
    sold = np.zeros_like(mass)
    sold.ravel()[active_indexes] = work_sold
    return sold


def _age_survivors(survivors: FloatArray) -> FloatArray:
    aged = np.zeros_like(survivors)
    aged[:, 1:] = survivors[:, :-1]
    aged[:, -1] += survivors[:, -1]
    return aged
