"""Canonical scalar metrics for an economic-cost chip distribution.

The migration engine already has the complete daily cost-bucket distribution in
memory. Computing these metrics there avoids replaying the persisted operator
log merely to rebuild the same distribution later.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from cyq_game.chip.migration_v2 import (
    StableLogPriceGrid,
    economic_break_even_for_bucket,
)


@dataclass(frozen=True, slots=True)
class DistributionMetrics:
    average_cost: float
    cost_p01: float
    cost_p10: float
    cost_p50: float
    cost_p90: float
    cost_p99: float
    main_peak: float
    dominant_band_lower: float
    dominant_band_upper: float
    dominant_band_mass: float
    profit_ratio: float
    asr: float
    cbw: float | None
    concentration_20: float
    peak_count: int


def compute_distribution_metrics(
    bucket_mass: Mapping[int, float] | Iterable[tuple[int, float]],
    close: float,
    *,
    grid: StableLogPriceGrid,
) -> DistributionMetrics:
    """Compute the canonical daily scalar feature set from known-cost mass."""

    close = float(close)
    if not math.isfinite(close) or close <= 0:
        raise ValueError("chip distribution metrics require a finite positive close")

    raw_items = bucket_mass.items() if isinstance(bucket_mass, Mapping) else bucket_mass
    pairs: list[tuple[float, float, int]] = []
    for raw_bucket, raw_mass in raw_items:
        bucket = int(raw_bucket)
        mass = float(raw_mass)
        if not math.isfinite(mass) or mass < 0:
            raise ValueError("chip bucket mass must be finite and non-negative")
        if mass == 0:
            continue
        price = float(economic_break_even_for_bucket(grid, bucket))
        if not math.isfinite(price) or price < 0:
            raise ValueError(
                "economic break-even price must be finite and non-negative"
            )
        pairs.append((price, mass, bucket))

    if not pairs:
        raise ValueError("chip distribution metrics require positive known mass")
    pairs.sort(key=lambda item: (item[0], item[2]))

    total = math.fsum(mass for _, mass, _ in pairs)
    if not math.isfinite(total) or total <= 0:
        raise ValueError("known chip mass must be finite and positive")

    def quantile(probability: float) -> float:
        threshold = total * probability
        cumulative = 0.0
        for price, mass, _ in pairs:
            cumulative += mass
            if cumulative >= threshold:
                return price
        return pairs[-1][0]

    p01, p10, p50, p90, p99 = (
        quantile(probability)
        for probability in (0.01, 0.10, 0.50, 0.90, 0.99)
    )

    mass_by_bucket = {bucket: mass for _, mass, bucket in pairs}
    scores = {
        bucket: (
            mass_by_bucket.get(bucket - 2, 0.0)
            + 4.0 * mass_by_bucket.get(bucket - 1, 0.0)
            + 6.0 * mass
            + 4.0 * mass_by_bucket.get(bucket + 1, 0.0)
            + mass_by_bucket.get(bucket + 2, 0.0)
        )
        for _, mass, bucket in pairs
    }
    main_bucket = max(
        scores,
        key=lambda bucket: (round(scores[bucket] / total, 12), -bucket),
    )

    def smoothed_score(bucket: int) -> float:
        return (
            mass_by_bucket.get(bucket - 2, 0.0)
            + 4.0 * mass_by_bucket.get(bucket - 1, 0.0)
            + 6.0 * mass_by_bucket.get(bucket, 0.0)
            + 4.0 * mass_by_bucket.get(bucket + 1, 0.0)
            + mass_by_bucket.get(bucket + 2, 0.0)
        )

    half_height = smoothed_score(main_bucket) * 0.5
    dominant_left = main_bucket
    while smoothed_score(dominant_left - 1) >= half_height:
        dominant_left -= 1
    dominant_right = main_bucket
    while smoothed_score(dominant_right + 1) >= half_height:
        dominant_right += 1

    dominant_mass = math.fsum(
        mass
        for _, mass, bucket in pairs
        if dominant_left <= bucket <= dominant_right
    ) / total
    structural_peaks = [
        bucket
        for bucket, score in scores.items()
        if score >= total * 0.12
        and score >= scores.get(bucket - 1, -math.inf)
        and score > scores.get(bucket + 1, -math.inf)
    ]

    right = 0
    window_mass = 0.0
    max_window_mass = 0.0
    for left, (left_price, _, _) in enumerate(pairs):
        if right < left:
            right = left
        while right < len(pairs) and pairs[right][0] <= left_price * 1.20:
            window_mass += pairs[right][1]
            right += 1
        max_window_mass = max(max_window_mass, window_mass)
        window_mass -= pairs[left][1]

    return DistributionMetrics(
        average_cost=math.fsum(price * mass for price, mass, _ in pairs) / total,
        cost_p01=p01,
        cost_p10=p10,
        cost_p50=p50,
        cost_p90=p90,
        cost_p99=p99,
        main_peak=economic_break_even_for_bucket(grid, main_bucket),
        dominant_band_lower=economic_break_even_for_bucket(grid, dominant_left),
        dominant_band_upper=economic_break_even_for_bucket(grid, dominant_right),
        dominant_band_mass=dominant_mass,
        profit_ratio=math.fsum(
            mass for price, mass, _ in pairs if price <= close
        )
        / total,
        asr=math.fsum(
            mass
            for price, mass, _ in pairs
            if close * 0.9 <= price <= close * 1.1
        )
        / total,
        cbw=None if p01 <= 0 else 100.0 * (p99 - p01) / p01,
        concentration_20=max_window_mass / total,
        peak_count=max(1, len(structural_peaks)),
    )
