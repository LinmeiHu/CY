"""Strategy features derived directly from persisted exact chip inventories."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any

from cyq_game.chip.migration_v2 import economic_break_even_for_bucket
from cyq_game.chip.peaks import (
    CanonicalPeak,
    PeakTrackingResult,
    TemporalPeakTracker,
    detect_canonical_peaks,
)
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
    dominant_peak_today: float | None
    dominant_band_lower: float | None
    dominant_band_upper: float | None
    dominant_band_mass: float | None
    profit_ratio: float
    asr: float
    cbw: float | None
    concentration_20: float
    peak_count: int
    canonical_peaks: tuple[CanonicalPeak, ...]


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
    canonical_peaks = detect_canonical_peaks(
        mass_by_bucket,
        price_for_bucket=lambda bucket: economic_break_even_for_bucket(
            _OPERATOR_GRID, bucket
        ),
        as_of=date.min,
    )
    dominant = max(canonical_peaks, key=lambda peak: peak.mass, default=None)

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
        dominant_peak_today=None if dominant is None else dominant.center_price,
        dominant_band_lower=None if dominant is None else dominant.lower_price,
        dominant_band_upper=None if dominant is None else dominant.upper_price,
        dominant_band_mass=None if dominant is None else dominant.mass,
        profit_ratio=math.fsum(mass for price, mass, _ in pairs if price <= close) / total,
        asr=math.fsum(mass for price, mass, _ in pairs if close * 0.9 <= price <= close * 1.1)
        / total,
        cbw=None if p01 <= 0 else 100.0 * (p99 - p01) / p01,
        concentration_20=max_window_mass / total,
        peak_count=len(canonical_peaks),
        canonical_peaks=canonical_peaks,
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
    trackers: dict[str, TemporalPeakTracker] = {}
    for item in resolver.iter_daily_bucket_mass(symbol, start, end):
        close = close_by_date.get(item.trade_date)
        if close is None:
            continue
        raw_metrics = distribution_metrics_from_bucket_mass(item.bucket_mass, close)
        seller_model = item.seller_model.value
        tracking = trackers.setdefault(
            seller_model, TemporalPeakTracker(symbol=symbol, model=seller_model)
        ).update(as_of=item.trade_date, candidates=raw_metrics.canonical_peaks)
        metrics = asdict(raw_metrics)
        metrics.pop("canonical_peaks")
        metrics.update(
            average_cost=item.average_cost,
            cost_p10=item.cost_p10,
            cost_p50=item.cost_p50,
            cost_p90=item.cost_p90,
        )
        by_date.setdefault(item.trade_date, []).append(
            {
                **metrics,
                "seller_model": seller_model,
                "peak_tracking": tracking,
                "snapshot_id": item.snapshot_id,
                "available_at": item.available_at,
                "known_cost_fraction": 1.0 - item.unknown_mass / item.free_float_shares,
                "research_valid": item.research_valid,
            }
        )

    result: list[dict[str, Any]] = []
    metric_names = tuple(
        name
        for name in DistributionMetrics.__dataclass_fields__
        if name != "canonical_peaks"
    )
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
                **_ensemble_peak_tracking(models),
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


def _ensemble_peak_tracking(models: list[dict[str, Any]]) -> dict[str, Any]:
    tracking = [model["peak_tracking"] for model in models]
    if not all(isinstance(value, PeakTrackingResult) for value in tracking):
        raise TypeError("exact ensemble peak tracking result is invalid")
    bases = [value.tracked_base_peak for value in tracking]
    dominants = [value.dominant_peak_today for value in tracking]
    base_valid = all(base is not None and not base.ambiguity for base in bases)
    dominant_valid = all(peak is not None for peak in dominants)
    base_values = [base for base in bases if base is not None]
    dominant_values = [peak for peak in dominants if peak is not None]
    return {
        "dominant_peak_today": (
            median(peak.center_price for peak in dominant_values)
            if dominant_valid
            else None
        ),
        "dominant_peak_ambiguous": (
            True
            if not dominant_valid
            else any(peak.ambiguity for peak in dominant_values)
        ),
        "tracked_base_peak": (
            median(peak.center_price for peak in base_values) if base_valid else None
        ),
        "peak_track_id": (
            "|".join(peak.peak_track_id for peak in base_values)
            if base_valid
            else None
        ),
        "peak_track_age": min(peak.age for peak in base_values) if base_valid else None,
        "peak_track_ambiguous": not base_valid,
        "peak_track_split": any(peak.split for peak in base_values),
        "peak_track_merge": any(peak.merge for peak in base_values),
        "peak_track_lost": not base_valid,
        "peak_fail_closed_reason": (
            None
            if base_valid
            else "|".join(
                sorted(
                    {
                        value.fail_closed_reason or "PEAK_TRACK_AMBIGUOUS"
                        for value in tracking
                        if value.tracked_base_peak is None
                    }
                )
            )
        ),
    }
