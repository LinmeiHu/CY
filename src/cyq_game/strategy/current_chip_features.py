"""Single-pass exact and semantic measurements for the current chip state."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any

from cyq_game.chip.peaks import TemporalPeakTracker
from cyq_game.strategy.chip_lineage import PersistedChipLineageResolver
from cyq_game.strategy.exact_chip_features import (
    DistributionMetrics,
    _ensemble_peak_tracking,
    distribution_metrics_from_bucket_mass,
    exact_research_invalid_reason,
)
from cyq_game.strategy.semantic_chip import (
    SemanticDistributionMetrics,
    semantic_distribution_metrics_from_bucket_mass,
)

_SEMANTIC_OPTIONAL = frozenset(
    {
        "lower_peak_center",
        "lower_peak_strength",
        "upper_peak_center",
        "upper_peak_strength",
        "valley_center",
        "valley_strength",
        "valley_depth",
    }
)
_EXACT_FIELDS = tuple(
    name
    for name in DistributionMetrics.__dataclass_fields__
    if name not in {"profit_ratio", "peak_count", "canonical_peaks"}
)


def build_current_chip_measurement_features(
    root: str | Path,
    symbol: str,
    close_by_date: dict[date, float],
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Replay each seller model once and return all current strategy primitives."""
    if start < date(2026, 6, 17) or end < start:
        raise ValueError("current chip measurements require a valid 2026-06-17+ range")
    resolver = PersistedChipLineageResolver(root)
    by_date: dict[date, list[dict[str, Any]]] = {}
    trackers: dict[str, TemporalPeakTracker] = {}
    for item in resolver.iter_daily_bucket_mass(symbol, start, end):
        close = close_by_date.get(item.trade_date)
        if close is None:
            continue
        semantic = asdict(
            semantic_distribution_metrics_from_bucket_mass(item.bucket_mass, close)
        )
        exact_metrics = distribution_metrics_from_bucket_mass(item.bucket_mass, close)
        seller_model = item.seller_model.value
        tracker = trackers.setdefault(
            seller_model, TemporalPeakTracker(symbol=symbol, model=seller_model)
        )
        if item.cash_dividend_per_share > 0.0 or item.share_multiplier != 1.0:
            tracker.apply_corporate_action(
                action_id="|".join(
                    (
                        item.snapshot_id,
                        *item.action_provenance,
                        item.trade_date.isoformat(),
                    )
                ),
                cash_per_share=item.cash_dividend_per_share,
                share_multiplier=item.share_multiplier,
            )
        peak_tracking = tracker.update(
            as_of=item.trade_date, candidates=exact_metrics.canonical_peaks
        )
        exact = asdict(exact_metrics)
        exact.pop("canonical_peaks")
        exact.update(
            average_cost=item.average_cost,
            cost_p10=item.cost_p10,
            cost_p50=item.cost_p50,
            cost_p90=item.cost_p90,
        )
        by_date.setdefault(item.trade_date, []).append(
            {
                **semantic,
                **{f"exact_{key}": value for key, value in exact.items()},
                "seller_model": seller_model,
                "peak_tracking": peak_tracking,
                "source_research_valid": item.research_valid,
                "known_cost_fraction": (
                    1.0 - item.unknown_mass / item.free_float_shares
                ),
                "available_at": item.available_at,
                "snapshot_id": item.snapshot_id,
            }
        )

    result: list[dict[str, Any]] = []
    semantic_fields = tuple(SemanticDistributionMetrics.__dataclass_fields__)
    for trade_date, models in sorted(by_date.items()):
        if len(models) != 3 or len({model["seller_model"] for model in models}) != 3:
            continue
        aggregate: dict[str, float | int | None] = {}
        for field in semantic_fields:
            values = [model[field] for model in models]
            if field in _SEMANTIC_OPTIONAL and any(value is None for value in values):
                aggregate[field] = None
            elif field == "price_ordered_peak_count":
                aggregate[field] = round(median(int(value) for value in values))
            else:
                aggregate[field] = median(float(value) for value in values)
        for field in _EXACT_FIELDS:
            values = [model[f"exact_{field}"] for model in models]
            aggregate[field] = (
                None
                if any(value is None for value in values)
                else median(float(value) for value in values)
            )
        aggregate["peak_count"] = round(
            median(int(model["exact_peak_count"]) for model in models)
        )
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
        for field in ("average_cost", "cost_p50", "cost_p90", "dominant_peak_today"):
            raw_values = [model[f"exact_{field}"] for model in models]
            values = [float(value) for value in raw_values if value is not None]
            complete = len(values) == 3
            aggregate[f"model_min_{field}"] = min(values) if complete else None
            aggregate[f"model_max_{field}"] = max(values) if complete else None
            aggregate[f"model_spread_{field}"] = (
                max(values) - min(values) if complete else None
            )
        aggregate.update(_ensemble_peak_tracking(models))
        source_valid = all(bool(model["source_research_valid"]) for model in models)
        cbw_valid = aggregate["cbw"] is not None
        exact_invalid = exact_research_invalid_reason(
            cbw_valid=cbw_valid, source_valid=source_valid
        )
        result.append(
            {
                "symbol": symbol,
                "trade_date": trade_date,
                **aggregate,
                "exact_p50": aggregate["cost_p50"],
                "known_cost_fraction_min": min(
                    float(model["known_cost_fraction"]) for model in models
                ),
                "available_at": max(model["available_at"] for model in models),
                "snapshot_id": "|".join(
                    str(model["snapshot_id"])
                    for model in sorted(
                        models, key=lambda value: value["seller_model"]
                    )
                ),
                "research_valid": source_valid,
                "exact_research_valid": exact_invalid is None,
                "invalid_reason": (
                    None if source_valid else "SOURCE_RESEARCH_INVALID"
                ),
                "exact_invalid_reason": exact_invalid,
            }
        )
    return result
