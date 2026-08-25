"""Outcome-blind semantic measurements from bucketized replay inventory."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any

from cyq_game.chip.migration_v2 import economic_break_even_for_bucket
from cyq_game.chip.peaks import detect_canonical_peaks
from cyq_game.strategy.chip_lineage import (
    _OPERATOR_GRID,
    PersistedChipLineageResolver,
)


@dataclass(frozen=True)
class SemanticDistributionMetrics:
    """Book-aligned bands and price-ordered peak measurements for one model."""

    cost_p05: float
    cost_p15: float
    cost_p85: float
    cost_p95: float
    i70_lower: float
    i70_upper: float
    i70_width_fraction: float
    i90_lower: float
    i90_upper: float
    i90_width_fraction: float
    profit_ratio: float
    overhang_mass: float
    lower_peak_center: float | None
    lower_peak_strength: float | None
    upper_peak_center: float | None
    upper_peak_strength: float | None
    valley_center: float | None
    valley_strength: float | None
    valley_depth: float | None
    price_ordered_peak_count: int
    known_cost_mass: float


def semantic_distribution_metrics_from_bucket_mass(
    bucket_mass: tuple[tuple[int, float], ...],
    close: float,
) -> SemanticDistributionMetrics:
    """Compute fixed semantic metrics without using labels or normalizing state."""
    if not math.isfinite(close) or close <= 0:
        raise ValueError("semantic chip metrics require a finite positive close")
    combined: dict[int, float] = {}
    for raw_bucket, raw_mass in bucket_mass:
        bucket = int(raw_bucket)
        mass = float(raw_mass)
        if not math.isfinite(mass) or mass < 0:
            raise ValueError("semantic chip bucket mass must be finite and non-negative")
        combined[bucket] = combined.get(bucket, 0.0) + mass
    combined = {bucket: mass for bucket, mass in combined.items() if mass > 0}
    if not combined:
        raise ValueError("semantic chip metrics require positive known-cost mass")
    total = math.fsum(combined.values())
    if not math.isfinite(total) or total <= 0:
        raise ValueError("semantic chip known-cost mass must be finite and positive")
    buckets = tuple(sorted(combined))

    def price(bucket: int) -> float:
        return economic_break_even_for_bucket(_OPERATOR_GRID, bucket)

    def quantile(probability: float) -> float:
        threshold = probability * total
        cumulative = 0.0
        for bucket in buckets:
            cumulative += combined[bucket]
            if cumulative >= threshold:
                return price(bucket)
        return price(buckets[-1])

    p05, p15, p85, p95 = (
        quantile(probability) for probability in (0.05, 0.15, 0.85, 0.95)
    )

    canonical_peaks = detect_canonical_peaks(
        combined,
        price_for_bucket=price,
        as_of=date.min,
    )
    lower_candidates = tuple(
        peak for peak in canonical_peaks if peak.center_price <= close
    )
    upper_candidates = tuple(
        peak for peak in canonical_peaks if peak.center_price > close
    )
    lower_peak = (
        max(lower_candidates, key=lambda peak: (peak.prominence, peak.center_price))
        if lower_candidates
        else None
    )
    upper_peak = (
        max(upper_candidates, key=lambda peak: (peak.prominence, -peak.center_price))
        if upper_candidates
        else None
    )
    valley_bucket: int | None = None
    valley_strength: float | None = None
    valley_depth: float | None = None
    if (
        lower_peak is not None
        and upper_peak is not None
        and upper_peak.center_bucket - lower_peak.center_bucket >= 2
    ):
        valley_bucket = min(
            range(lower_peak.center_bucket + 1, upper_peak.center_bucket),
            key=lambda bucket: (
                combined.get(bucket, 0.0) / total,
                bucket,
            ),
        )
        valley_strength = combined.get(valley_bucket, 0.0) / total
        weaker_peak = min(lower_peak.prominence, upper_peak.prominence)
        if weaker_peak > 0:
            valley_depth = max(0.0, min(1.0, 1.0 - valley_strength / weaker_peak))

    profit_ratio = math.fsum(
        mass for bucket, mass in combined.items() if price(bucket) <= close
    ) / total
    return SemanticDistributionMetrics(
        cost_p05=p05,
        cost_p15=p15,
        cost_p85=p85,
        cost_p95=p95,
        i70_lower=p15,
        i70_upper=p85,
        i70_width_fraction=(p85 - p15) / close,
        i90_lower=p05,
        i90_upper=p95,
        i90_width_fraction=(p95 - p05) / close,
        profit_ratio=profit_ratio,
        overhang_mass=1.0 - profit_ratio,
        lower_peak_center=None if lower_peak is None else lower_peak.center_price,
        lower_peak_strength=None if lower_peak is None else lower_peak.prominence,
        upper_peak_center=None if upper_peak is None else upper_peak.center_price,
        upper_peak_strength=None if upper_peak is None else upper_peak.prominence,
        valley_center=None if valley_bucket is None else price(valley_bucket),
        valley_strength=valley_strength,
        valley_depth=valley_depth,
        price_ordered_peak_count=len(canonical_peaks),
        known_cost_mass=total,
    )


def build_semantic_ensemble_features(
    root: str | Path,
    symbol: str,
    close_by_date: dict[date, float],
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Build the physically capped 2020-2022 development overlay."""
    if end.year >= 2023:
        raise ValueError("semantic development overlay is physically locked before 2023")
    return _build_semantic_ensemble_features(root, symbol, close_by_date, start, end)


def build_current_semantic_ensemble_features(
    root: str | Path,
    symbol: str,
    close_by_date: dict[date, float],
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Build current-state measurements without weakening the development lock."""
    if start < date(2026, 6, 17) or end < start:
        raise ValueError("current semantic overlay requires a valid 2026-06-17+ range")
    return _build_semantic_ensemble_features(root, symbol, close_by_date, start, end)


def _build_semantic_ensemble_features(
    root: str | Path,
    symbol: str,
    close_by_date: dict[date, float],
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Build median/min/max measurements for an explicitly authorized horizon."""
    if not close_by_date:
        return []
    resolver = PersistedChipLineageResolver(root)
    by_date: dict[date, list[dict[str, Any]]] = {}
    for item in resolver.iter_daily_bucket_mass(symbol, start, end):
        close = close_by_date.get(item.trade_date)
        if close is None:
            continue
        model = asdict(
            semantic_distribution_metrics_from_bucket_mass(item.bucket_mass, close)
        )
        by_date.setdefault(item.trade_date, []).append(
            {
                **model,
                "seller_model": item.seller_model.value,
                "source_research_valid": item.research_valid,
                "known_cost_fraction": 1.0
                - item.unknown_mass / item.free_float_shares,
                "available_at": item.available_at,
                "snapshot_id": item.snapshot_id,
            }
        )

    result: list[dict[str, Any]] = []
    fields = tuple(SemanticDistributionMetrics.__dataclass_fields__)
    optional_fields = {
        "lower_peak_center",
        "lower_peak_strength",
        "upper_peak_center",
        "upper_peak_strength",
        "valley_center",
        "valley_strength",
        "valley_depth",
    }
    for trade_date, models in sorted(by_date.items()):
        if len(models) != 3 or len({model["seller_model"] for model in models}) != 3:
            continue
        aggregate: dict[str, float | int | None] = {}
        for field in fields:
            values = [model[field] for model in models]
            if field in optional_fields and any(value is None for value in values):
                aggregate[field] = None
            elif field == "price_ordered_peak_count":
                aggregate[field] = round(median(int(value) for value in values))
            else:
                aggregate[field] = median(float(value) for value in values)
        for field in (
            "i70_width_fraction",
            "i90_width_fraction",
            "profit_ratio",
            "overhang_mass",
            "valley_depth",
        ):
            values = [model[field] for model in models]
            known = [float(value) for value in values if value is not None]
            aggregate[f"model_min_{field}"] = min(known) if len(known) == 3 else None
            aggregate[f"model_max_{field}"] = max(known) if len(known) == 3 else None
            aggregate[f"model_spread_{field}"] = (
                max(known) - min(known) if len(known) == 3 else None
            )
        research_valid = all(bool(model["source_research_valid"]) for model in models)
        result.append(
            {
                "symbol": symbol,
                "trade_date": trade_date,
                **aggregate,
                "known_cost_fraction_min": min(
                    float(model["known_cost_fraction"]) for model in models
                ),
                "available_at": max(model["available_at"] for model in models),
                "snapshot_id": "|".join(
                    str(model["snapshot_id"])
                    for model in sorted(models, key=lambda value: value["seller_model"])
                ),
                "research_valid": research_valid,
                "invalid_reason": None if research_valid else "SOURCE_RESEARCH_INVALID",
            }
        )
    return result
