"""Strategy features derived directly from persisted exact chip inventories."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any

from cyq_game.chip.migration_v2 import economic_break_even_for_bucket
from cyq_game.strategy.chip_lineage import (
    _OPERATOR_GRID,
    PersistedChipLineageResolver,
)


@dataclass(frozen=True)
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


def exact_research_invalid_reason(
    *, cbw_valid: bool, source_valid: bool
) -> str | None:
    if not cbw_valid:
        return "NONPOSITIVE_ECONOMIC_P01_UNDEFINED_CBW"
    if not source_valid:
        return "SOURCE_RESEARCH_INVALID"
    return None


def distribution_metrics_from_bucket_mass(
    bucket_mass: tuple[tuple[int, float], ...], close: float
) -> DistributionMetrics:
    if close <= 0 or not bucket_mass:
        raise ValueError("exact chip features require a positive close and known mass")
    pairs = tuple(sorted(
        (
            economic_break_even_for_bucket(_OPERATOR_GRID, bucket),
            float(mass),
            bucket,
        )
        for bucket, mass in bucket_mass
        if mass > 0
    ))
    total = math.fsum(mass for _, mass, _ in pairs)
    if total <= 0:
        raise ValueError("known chip mass must be positive")

    def quantile(probability: float) -> float:
        threshold = total * probability
        cumulative = 0.0
        for price, mass, _ in pairs:
            cumulative += mass
            if cumulative >= threshold:
                return price
        return pairs[-1][0]

    p01, p10, p50, p90, p99 = (quantile(p) for p in (0.01, 0.10, 0.50, 0.90, 0.99))
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
    main_bucket = max(scores, key=lambda bucket: (round(scores[bucket] / total, 12), -bucket))

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
        main_peak=economic_break_even_for_bucket(_OPERATOR_GRID, main_bucket),
        dominant_band_lower=economic_break_even_for_bucket(
            _OPERATOR_GRID, dominant_left
        ),
        dominant_band_upper=economic_break_even_for_bucket(
            _OPERATOR_GRID, dominant_right
        ),
        dominant_band_mass=dominant_mass,
        profit_ratio=math.fsum(mass for price, mass, _ in pairs if price <= close) / total,
        asr=math.fsum(mass for price, mass, _ in pairs if close * 0.9 <= price <= close * 1.1)
        / total,
        cbw=None if p01 <= 0 else 100.0 * (p99 - p01) / p01,
        concentration_20=max_window_mass / total,
        peak_count=max(1, len(structural_peaks)),
    )


def build_exact_ensemble_features(
    root: str | Path,
    symbol: str,
    close_by_date: dict[date, float],
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    resolver = PersistedChipLineageResolver(root)
    by_date: dict[date, list[dict[str, Any]]] = {}
    for item in resolver.iter_daily_bucket_mass(symbol, start, end):
        close = close_by_date.get(item.trade_date)
        if close is None:
            continue
        metrics = asdict(distribution_metrics_from_bucket_mass(item.bucket_mass, close))
        metrics.update(
            average_cost=item.average_cost,
            cost_p10=item.cost_p10,
            cost_p50=item.cost_p50,
            cost_p90=item.cost_p90,
            main_peak=item.main_peak,
        )
        by_date.setdefault(item.trade_date, []).append(
            {
                **metrics,
                "seller_model": item.seller_model.value,
                "snapshot_id": item.snapshot_id,
                "available_at": item.available_at,
                "known_cost_fraction": 1.0 - item.unknown_mass / item.free_float_shares,
                "research_valid": item.research_valid,
            }
        )

    result: list[dict[str, Any]] = []
    metric_names = tuple(DistributionMetrics.__dataclass_fields__)
    for day, models in sorted(by_date.items()):
        if len(models) != 3:
            continue
        metric_values = {
            name: (
                None
                if any(model[name] is None for model in models)
                else median(float(model[name]) for model in models)
            )
            for name in metric_names
        }
        cbw_valid = metric_values["cbw"] is not None
        source_valid = all(bool(model["research_valid"]) for model in models)
        result.append(
            {
                "symbol": symbol,
                "trade_date": day,
                **metric_values,
                "peak_count": round(median(int(model["peak_count"]) for model in models)),
                "known_cost_fraction_min": min(
                    float(model["known_cost_fraction"]) for model in models
                ),
                "model_spread_average_cost": max(
                    float(model["average_cost"]) for model in models
                )
                - min(float(model["average_cost"]) for model in models),
                "model_min_cost_p50": min(float(model["cost_p50"]) for model in models),
                "model_max_cost_p50": max(float(model["cost_p50"]) for model in models),
                "model_spread_cost_p50": max(
                    float(model["cost_p50"]) for model in models
                )
                - min(float(model["cost_p50"]) for model in models),
                "model_min_cost_p90": min(float(model["cost_p90"]) for model in models),
                "model_max_cost_p90": max(float(model["cost_p90"]) for model in models),
                "model_spread_cost_p90": max(
                    float(model["cost_p90"]) for model in models
                )
                - min(float(model["cost_p90"]) for model in models),
                "model_min_main_peak": min(
                    float(model["main_peak"]) for model in models
                ),
                "model_max_main_peak": max(
                    float(model["main_peak"]) for model in models
                ),
                "model_spread_main_peak": max(
                    float(model["main_peak"]) for model in models
                )
                - min(float(model["main_peak"]) for model in models),
                "available_at": max(model["available_at"] for model in models),
                "snapshot_id": "|".join(
                    str(model["snapshot_id"])
                    for model in sorted(models, key=lambda x: x["seller_model"])
                ),
                "research_valid": cbw_valid and source_valid,
                "invalid_reason": exact_research_invalid_reason(
                    cbw_valid=cbw_valid,
                    source_valid=source_valid,
                ),
            }
        )
    return result
