from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from cyq_game.chip.core import ChipState

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class ChipPeak:
    center_price: float
    mass: float
    width_pct: float
    prominence: float
    age_mean: float | None
    formation_date: str


@dataclass(frozen=True)
class CYQK:
    open: float
    high: float
    low: float
    close: float

    @property
    def length(self) -> float:
        return self.close - self.open


@dataclass(frozen=True)
class ChipFeatures:
    profit_ratio: float
    trapped_ratio: float
    average_cost: float
    p01: float
    p10: float
    p50: float
    p90: float
    p99: float
    asr: float
    space20: float
    ckdp: float
    ckdw: float
    cbw: float
    cyqk_pre: CYQK
    cyc5: float | None
    cyc13: float | None
    cyc34: float | None
    cys13: float | None
    cys34: float | None
    rpy2: float | None
    concentration_20: float
    peaks: tuple[ChipPeak, ...]
    priors: tuple[str, ...]
    quality: float

    @property
    def pr(self) -> float:
        return self.profit_ratio

    @property
    def tr(self) -> float:
        return self.trapped_ratio

    @property
    def ac(self) -> float:
        return self.average_cost


def compute_cyqk(
    state: ChipState,
    *,
    open_price: float,
    high: float,
    low: float,
    close: float,
) -> CYQK:
    """Compute pre-trade CYQK without deriving unrelated chip features."""

    cumulative = np.cumsum(state.mass)
    values = _cdf_values(
        state,
        cumulative,
        (open_price, high, low, close),
    )
    return CYQK(
        100.0 * values[0],
        100.0 * values[1],
        100.0 * values[2],
        100.0 * values[3],
    )


def compute_features(
    state: ChipState,
    *,
    open_price: float,
    high: float,
    low: float,
    close: float,
    history_low_2y: float | None = None,
    history_high_2y: float | None = None,
    smoothing_sigma: float = 1.5,
    peak_prominence: float = 0.03,
) -> ChipFeatures:
    cumulative = np.cumsum(state.mass)
    quantile_indexes = np.searchsorted(
        cumulative,
        np.array((0.01, 0.10, 0.50, 0.90, 0.99)),
        side="left",
    )
    quantile_indexes = np.minimum(quantile_indexes, len(state.grid.prices) - 1)
    p01, p10, p50, p90, p99 = (
        float(value) for value in state.grid.prices[quantile_indexes]
    )
    span = max(p99 - p01, p01 * 1e-9)
    cdf_open, cdf_high, cdf_low, pr, cdf_110, cdf_090, cdf_120 = _cdf_values(
        state,
        cumulative,
        (open_price, high, low, close, 1.1 * close, 0.9 * close, 1.2 * close),
    )
    # The three windows intentionally stay separate: each reduction touches only
    # its short prefix. A fused full-age reduction benchmarks slower at this size.
    cyc5 = _cohort_cost(state, 5)
    cyc13 = _cohort_cost(state, 13)
    cyc34 = _cohort_cost(state, 34)
    rpy2 = None
    if (
        history_low_2y is not None
        and history_high_2y is not None
        and history_high_2y > history_low_2y
    ):
        rpy2 = 100.0 * (close - history_low_2y) / (history_high_2y - history_low_2y)
    priors: list[str] = []
    cys13 = 100.0 * (close / cyc13 - 1.0) if cyc13 else None
    cys34 = 100.0 * (close / cyc34 - 1.0) if cyc34 else None
    if cys13 is not None and cys13 < -16:
        priors.append("BOOK_PRIOR:CYS13_OVERSOLD_CALIBRATION_REQUIRED")
    if cys34 is not None and cys34 < -20:
        priors.append("BOOK_PRIOR:CYS34_OVERSOLD_CALIBRATION_REQUIRED")
    average_cost = state.average_cost
    return ChipFeatures(
        profit_ratio=pr,
        trapped_ratio=1.0 - pr,
        average_cost=average_cost,
        p01=p01,
        p10=p10,
        p50=p50,
        p90=p90,
        p99=p99,
        asr=max(0.0, cdf_110 - cdf_090),
        space20=max(0.0, cdf_120 - pr),
        ckdp=100.0 * (close - p01) / span,
        ckdw=100.0 * (average_cost - p01) / span,
        cbw=100.0 * (p99 - p01) / p01,
        cyqk_pre=CYQK(
            100.0 * cdf_open,
            100.0 * cdf_high,
            100.0 * cdf_low,
            100.0 * pr,
        ),
        cyc5=cyc5,
        cyc13=cyc13,
        cyc34=cyc34,
        cys13=cys13,
        cys34=cys34,
        rpy2=rpy2,
        concentration_20=_maximum_window_mass(state, 0.20, cumulative),
        peaks=tuple(
            detect_peaks(
                state,
                smoothing_sigma,
                peak_prominence,
                cumulative=cumulative,
            )
        ),
        priors=tuple(priors),
        quality=state.quality,
    )


def detect_peaks(
    state: ChipState,
    sigma: float = 1.5,
    min_prominence: float = 0.03,
    *,
    cumulative: FloatArray | None = None,
) -> list[ChipPeak]:
    smooth = _gaussian_smooth(state.mass, sigma)
    # Peaks commonly overlap, so repeatedly summing every peak slice turns the
    # same price-age cells into duplicated work.  Prefix the marginal mass and
    # age-weighted mass once, then answer every peak interval in O(1).
    mass_prefix = np.empty(len(state.mass) + 1, dtype=np.float64)
    mass_prefix[0] = 0.0
    mass_prefix[1:] = np.cumsum(state.mass) if cumulative is None else cumulative
    age_weight_prefix: FloatArray | None = None
    if state.age_mass is not None:
        ages = np.arange(state.age_mass.shape[1], dtype=np.float64)
        age_weight_prefix = np.empty(len(state.mass) + 1, dtype=np.float64)
        age_weight_prefix[0] = 0.0
        age_weight_prefix[1:] = np.cumsum(state.age_mass @ ages)
    left_minima = np.minimum.accumulate(smooth)
    right_minima = np.minimum.accumulate(smooth[::-1])[::-1]
    peaks: list[ChipPeak] = []
    candidate_indexes = np.flatnonzero(
        (smooth[1:-1] > smooth[:-2]) & (smooth[1:-1] >= smooth[2:])
    ) + 1
    positions = np.arange(len(smooth))
    half_heights = smooth[candidate_indexes] / 2.0
    below_half_height = smooth[None, :] < half_heights[:, None]
    left_bounds = (
        np.where(
            below_half_height & (positions[None, :] < candidate_indexes[:, None]),
            positions[None, :],
            -1,
        ).max(axis=1)
        + 1
    )
    right_bounds = (
        np.where(
            below_half_height & (positions[None, :] > candidate_indexes[:, None]),
            positions[None, :],
            len(smooth),
        ).min(axis=1)
        - 1
    )
    for index_value, left_value, right_value in zip(
        candidate_indexes, left_bounds, right_bounds, strict=True
    ):
        index = int(index_value)
        left_min = float(left_minima[index])
        right_min = float(right_minima[index])
        prominence = float(smooth[index] - max(left_min, right_min))
        left = int(left_value)
        right = int(right_value)
        peak_mass = float(mass_prefix[right + 1] - mass_prefix[left])
        if peak_mass < min_prominence and prominence < min_prominence:
            continue
        age_mean: float | None = None
        if age_weight_prefix is not None:
            local_age_weight = age_weight_prefix[right + 1] - age_weight_prefix[left]
            age_mean = float(local_age_weight / max(peak_mass, 1e-12))
        peaks.append(
            ChipPeak(
                center_price=float(state.grid.prices[index]),
                mass=peak_mass,
                width_pct=float(state.grid.prices[right] / state.grid.prices[left] - 1.0),
                prominence=prominence,
                age_mean=age_mean,
                formation_date=state.as_of.isoformat(),
            )
        )
    return sorted(peaks, key=lambda peak: peak.mass, reverse=True)


def _cdf_values(
    state: ChipState,
    cumulative: FloatArray,
    prices: tuple[float, ...],
) -> FloatArray:
    indexes = np.searchsorted(state.grid.prices, np.asarray(prices), side="right")
    values = np.zeros(len(indexes), dtype=np.float64)
    populated = indexes > 0
    values[populated] = cumulative[indexes[populated] - 1]
    return values


def earth_mover_distance(left: ChipState, right: ChipState) -> float:
    if not np.array_equal(left.grid.prices, right.grid.prices):
        raise ValueError("EMD states must share a price grid")
    return float(np.abs(np.cumsum(left.mass) - np.cumsum(right.mass)).sum() * left.grid.step_pct)


def base_retention(current: ChipState, original: ChipState, lower: float, upper: float) -> float:
    current_mask = (current.grid.prices >= lower) & (current.grid.prices <= upper)
    original_mask = (original.grid.prices >= lower) & (original.grid.prices <= upper)
    current_mass = float(current.mass[current_mask].sum())
    original_mass = float(original.mass[original_mask].sum())
    return current_mass / max(original_mass, 1e-12)


def _cohort_cost(state: ChipState, max_age: int) -> float | None:
    if state.age_mass is None:
        return None
    mass = state.age_mass[:, : max_age + 1].sum(axis=1)
    total = float(mass.sum())
    return float(np.dot(state.grid.prices, mass) / total) if total > 1e-12 else None


def _maximum_window_mass(
    state: ChipState,
    width_pct: float,
    cumulative: FloatArray | None = None,
) -> float:
    cumulative = np.cumsum(state.mass) if cumulative is None else cumulative
    prefix = np.empty(len(cumulative) + 1, dtype=np.float64)
    prefix[0] = 0.0
    prefix[1:] = cumulative
    right = np.searchsorted(
        state.grid.prices,
        state.grid.prices * (1.0 + width_pct),
        side="right",
    )
    windows = prefix[right] - prefix[:-1]
    return float(np.max(windows, initial=0.0))


def _gaussian_smooth(values: FloatArray, sigma: float) -> FloatArray:
    if sigma <= 0:
        return values.copy()
    radius = max(1, int(3 * sigma))
    x = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-0.5 * (x / sigma) ** 2)
    kernel /= kernel.sum()
    return np.convolve(values, kernel, mode="same")
