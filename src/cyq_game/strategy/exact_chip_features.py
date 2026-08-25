"""Strategy features from persisted V13 daily metrics.

Operator-log v13 persists the canonical daily scalar feature set. Older
operator versions retain a bucketized lineage replay compatibility path; that
replay is not a numerical oracle for persisted V13 daily metrics.
"""

from __future__ import annotations

import math
import json
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any

import pyarrow.parquet as pq

from cyq_game.chip.ensemble_v2 import SELLER_MODEL_ORDER
from cyq_game.chip.peak_versions import PEAK_DEFINITION_VERSION
from cyq_game.chip.profile_metrics import (
    DistributionMetrics,
    compute_distribution_metrics,
)
from cyq_game.chip.peaks import (
    CanonicalPeak,
    EnsembleTemporalPeakTracker,
)
from cyq_game.strategy.chip_lineage import (
    _OPERATOR_GRID,
    PersistedChipLineageResolver,
)

_FAST_OPERATOR_STORAGE_VERSION = "chip-operator-log-v13"
PERSISTED_DAILY_FEATURE_AUTHORITY = "PERSISTED_DAILY_METRICS_V13"
REPLAYED_LEGACY_OPERATOR_LOG = "REPLAYED_LEGACY_OPERATOR_LOG"
_METRIC_NAMES = tuple(
    name for name in DistributionMetrics.__dataclass_fields__ if name != "canonical_peaks"
)
_FAST_OPERATOR_COLUMNS = (
    "storage_version",
    "symbol",
    "trade_date",
    "seller_model",
    "snapshot_id",
    "available_at",
    "profile_close",
    "known_cost_fraction",
    "research_valid",
    *_METRIC_NAMES,
    "canonical_peaks_json",
    "cash_dividend_per_share",
    "share_multiplier",
    "action_provenance_ids",
)
_EXPECTED_MODELS = frozenset(model.value for model in SELLER_MODEL_ORDER)


def distribution_metrics_from_bucket_mass(
    bucket_mass: tuple[tuple[int, float], ...], close: float, *, as_of: date = date.min
) -> DistributionMetrics:
    """Backward-compatible public wrapper around the canonical implementation."""

    return compute_distribution_metrics(bucket_mass, close, grid=_OPERATOR_GRID, as_of=as_of)


def _ensemble_peak_tracking(
    models: list[dict[str, Any]],
    *,
    tracker: EnsembleTemporalPeakTracker,
    as_of: date,
) -> dict[str, Any]:
    tracking = tracker.update(
        as_of=as_of,
        candidates_by_model={
            str(model["seller_model"]): tuple(model["canonical_peaks"])
            for model in models
        },
    )
    ensemble = tracking.ensemble
    base = ensemble.tracked_base_peak
    dominants = [value.dominant_peak_today for value in tracking.by_model.values()]
    base_valid = base is not None and not base.ambiguity
    dominant_valid = all(peak is not None for peak in dominants)
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
        "model_spread_dominant_peak_today": (
            max(peak.center_price for peak in dominant_values)
            - min(peak.center_price for peak in dominant_values)
            if dominant_valid
            else None
        ),
        "tracked_base_peak": (
            base.center_price if base_valid else None
        ),
        "peak_track_band_lower": (
            base.band[0] if base_valid else None
        ),
        "peak_track_band_upper": (
            base.band[1] if base_valid else None
        ),
        "peak_track_mass": (
            base.mass if base_valid else None
        ),
        "peak_track_prominence": (
            base.prominence if base_valid else None
        ),
        "peak_track_id": (
            base.peak_track_id if base_valid else None
        ),
        "peak_track_age": base.age if base_valid else None,
        "peak_track_ambiguous": not base_valid,
        "peak_track_split": any(peak.split for peak in ensemble.peaks),
        "peak_track_merge": any(peak.merge for peak in ensemble.peaks),
        "peak_track_lost": any(peak.lost for peak in ensemble.peaks),
        "peak_definition_version": (
            base.definition_version if base_valid else None
        ),
        "peak_fail_closed_reason": (
            None if base_valid else (ensemble.fail_closed_reason or "PEAK_TRACK_AMBIGUOUS")
        ),
    }


def exact_research_invalid_reason(
    *, cbw_valid: bool, source_valid: bool
) -> str | None:
    if not cbw_valid:
        return "NONPOSITIVE_ECONOMIC_P01_UNDEFINED_CBW"
    if not source_valid:
        return "SOURCE_RESEARCH_INVALID"
    return None


def _operator_paths(
    root: str | Path,
    symbol: str,
    start: date,
    end: date,
) -> tuple[Path, ...]:
    root_path = Path(root)
    filename = f"{symbol.replace('.', '_')}.parquet"
    paths = set(root_path.glob(f"parts/bucket=*/{filename}"))
    for year in range(start.year, end.year + 1):
        paths.update(root_path.glob(f"year={year}/parts/bucket=*/{filename}"))
    if root_path.is_file() and root_path.name == filename:
        paths.add(root_path)
    return tuple(sorted(paths))


def _close_matches(persisted: object, expected: float) -> bool:
    if persisted is None:
        return False
    persisted_value = float(persisted)
    expected_value = float(expected)
    if not math.isfinite(persisted_value) or not math.isfinite(expected_value):
        return False
    scale = max(1.0, abs(persisted_value), abs(expected_value))
    return math.isclose(
        persisted_value,
        expected_value,
        rel_tol=1e-12,
        abs_tol=1e-12 * scale,
    )


def _fast_daily_models(
    root: str | Path,
    symbol: str,
    close_by_date: dict[date, float],
    start: date,
    end: date,
) -> dict[date, list[dict[str, Any]]] | None:
    """Read v13 scalar facts without decoding or replaying inventory operators."""

    paths = _operator_paths(root, symbol, start, end)
    if not paths:
        return None

    required = set(_FAST_OPERATOR_COLUMNS)
    by_date_and_model: dict[date, dict[str, dict[str, Any]]] = {}
    for path in paths:
        parquet = pq.ParquetFile(path)
        if not required.issubset(parquet.schema_arrow.names):
            return None
        for batch in parquet.iter_batches(
            batch_size=65_536,
            columns=list(_FAST_OPERATOR_COLUMNS),
        ):
            columns = {
                name: batch.column(batch.schema.get_field_index(name))
                for name in _FAST_OPERATOR_COLUMNS
            }
            for row_index in range(batch.num_rows):
                if (
                    columns["storage_version"][row_index].as_py()
                    != _FAST_OPERATOR_STORAGE_VERSION
                ):
                    return None
                row_symbol = str(columns["symbol"][row_index].as_py())
                if row_symbol != symbol:
                    raise ValueError(f"symbol mismatch in {path}: {row_symbol}")
                trade_date = columns["trade_date"][row_index].as_py()
                if not start <= trade_date <= end:
                    continue
                expected_close = close_by_date.get(trade_date)
                if expected_close is None:
                    continue
                if not _close_matches(
                    columns["profile_close"][row_index].as_py(),
                    expected_close,
                ):
                    # The caller supplied a different daily-price snapshot. Fall
                    # back to exact replay instead of mixing price coordinates.
                    return None
                average_cost = columns["average_cost"][row_index].as_py()
                if average_cost is None:
                    # Fully UNKNOWN_COST rows intentionally have no cost feature.
                    continue

                seller_model = str(columns["seller_model"][row_index].as_py())
                if seller_model not in _EXPECTED_MODELS:
                    raise ValueError(f"unknown seller model in {path}: {seller_model}")
                model_row: dict[str, Any] = {
                    name: columns[name][row_index].as_py()
                    for name in _METRIC_NAMES
                }
                model_row.update(
                    seller_model=seller_model,
                    snapshot_id=str(columns["snapshot_id"][row_index].as_py()),
                    available_at=columns["available_at"][row_index].as_py(),
                    known_cost_fraction=float(
                        columns["known_cost_fraction"][row_index].as_py()
                    ),
                    research_valid=bool(
                        columns["research_valid"][row_index].as_py()
                    ),
                    canonical_peaks=_canonical_peaks_from_json(
                        columns["canonical_peaks_json"][row_index].as_py(),
                        expected_day=trade_date,
                    ),
                    cash_dividend_per_share=float(
                        columns["cash_dividend_per_share"][row_index].as_py()
                    ),
                    share_multiplier=float(columns["share_multiplier"][row_index].as_py()),
                    action_provenance_ids=tuple(
                        str(value)
                        for value in (columns["action_provenance_ids"][row_index].as_py() or [])
                    ),
                )
                models = by_date_and_model.setdefault(trade_date, {})
                previous = models.get(seller_model)
                if previous is not None and previous != model_row:
                    raise ValueError(
                        "conflicting persisted feature rows for symbol/date/model"
                    )
                models[seller_model] = model_row

    return {
        trade_date: list(models.values())
        for trade_date, models in by_date_and_model.items()
    }


def _replayed_daily_models(
    root: str | Path,
    symbol: str,
    close_by_date: dict[date, float],
    start: date,
    end: date,
) -> dict[date, list[dict[str, Any]]]:
    """Replay bucketized lineage for compatibility, not V13 feature authority.

    Inventory shares and transition lineage are replayed under the persisted
    conservation contract. Economic-cost coordinates are reconstructed on the
    canonical 25bp bucket grid, so this path must not be used as a bitwise or
    numerical oracle for persisted V13 daily metrics.
    """

    resolver = PersistedChipLineageResolver(root)
    by_date: dict[date, list[dict[str, Any]]] = {}
    for item in resolver.iter_daily_bucket_mass(symbol, start, end):
        close = close_by_date.get(item.trade_date)
        if close is None:
            continue
        calculated = distribution_metrics_from_bucket_mass(
            item.bucket_mass, close, as_of=item.trade_date
        )
        metrics = {name: getattr(calculated, name) for name in _METRIC_NAMES}
        # Preserve the exact persisted legacy scalars as the old implementation did.
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
                "known_cost_fraction": (
                    1.0 - item.unknown_mass / item.free_float_shares
                ),
                "research_valid": item.research_valid,
                "canonical_peaks": calculated.canonical_peaks,
                "cash_dividend_per_share": item.cash_dividend_per_share,
                "share_multiplier": item.share_multiplier,
                "action_provenance_ids": item.action_provenance,
            }
        )
    return by_date


def _ensemble_rows(
    symbol: str,
    by_date: dict[date, list[dict[str, Any]]],
    *,
    feature_source: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    tracker = EnsembleTemporalPeakTracker(symbol=symbol, models=_EXPECTED_MODELS)
    for day, models in sorted(by_date.items()):
        model_names = [str(model["seller_model"]) for model in models]
        if (
            len(model_names) != len(_EXPECTED_MODELS)
            or set(model_names) != _EXPECTED_MODELS
        ):
            continue
        metric_values = {
            name: (
                None
                if any(model[name] is None for model in models)
                else median(float(model[name]) for model in models)
            )
            for name in _METRIC_NAMES
        }
        cbw_valid = metric_values["cbw"] is not None
        source_valid = all(bool(model["research_valid"]) for model in models)
        _apply_peak_action(tracker, models, day)
        peak_tracking = _ensemble_peak_tracking(models, tracker=tracker, as_of=day)
        result.append(
            {
                "symbol": symbol,
                "trade_date": day,
                **metric_values,
                **peak_tracking,
                "peak_count": round(
                    median(int(model["peak_count"]) for model in models)
                ),
                "known_cost_fraction_min": min(
                    float(model["known_cost_fraction"]) for model in models
                ),
                "model_spread_average_cost": max(
                    float(model["average_cost"]) for model in models
                )
                - min(float(model["average_cost"]) for model in models),
                "model_min_cost_p50": min(
                    float(model["cost_p50"]) for model in models
                ),
                "model_max_cost_p50": max(
                    float(model["cost_p50"]) for model in models
                ),
                "model_spread_cost_p50": max(
                    float(model["cost_p50"]) for model in models
                )
                - min(float(model["cost_p50"]) for model in models),
                "model_min_cost_p90": min(
                    float(model["cost_p90"]) for model in models
                ),
                "model_max_cost_p90": max(
                    float(model["cost_p90"]) for model in models
                ),
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
                    for model in sorted(
                        models,
                        key=lambda item: item["seller_model"],
                    )
                ),
                "research_valid": cbw_valid and source_valid,
                "invalid_reason": exact_research_invalid_reason(
                    cbw_valid=cbw_valid,
                    source_valid=source_valid,
                ),
                "feature_source": feature_source,
            }
        )
    return result


def _canonical_peaks_from_json(value: object, *, expected_day: date) -> tuple[CanonicalPeak, ...]:
    if not isinstance(value, str):
        raise ValueError("canonical peak artifact is missing; rebuild from raw inputs")
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError("canonical peak artifact is invalid JSON") from error
    if not isinstance(payload, list):
        raise ValueError("canonical peak artifact must be a list")
    fields = set(CanonicalPeak.__dataclass_fields__)
    peaks: list[CanonicalPeak] = []
    for item in payload:
        if not isinstance(item, dict) or set(item) != fields:
            raise ValueError("canonical peak artifact schema is incompatible; rebuild from raw inputs")
        if item["formation_date"] != expected_day.isoformat():
            raise ValueError("canonical peak artifact date is inconsistent")
        if item["definition_version"] != PEAK_DEFINITION_VERSION:
            raise ValueError("canonical peak artifact definition is stale; rebuild from raw inputs")
        try:
            peaks.append(CanonicalPeak(**item))
        except (TypeError, ValueError) as error:
            raise ValueError("canonical peak artifact values are invalid") from error
    return tuple(sorted(peaks, key=lambda peak: peak.center_price))


def _apply_peak_action(
    tracker: EnsembleTemporalPeakTracker, models: list[dict[str, Any]], day: date
) -> None:
    actions = {
        (
            float(model["cash_dividend_per_share"]),
            float(model["share_multiplier"]),
            tuple(str(value) for value in model["action_provenance_ids"]),
        )
        for model in models
    }
    if len(actions) != 1:
        raise ValueError("seller models disagree on peak corporate-action coordinates")
    cash_per_share, share_multiplier, provenance = actions.pop()
    if cash_per_share != 0.0 or share_multiplier != 1.0:
        tracker.apply_corporate_action(
            action_id="|".join((day.isoformat(), *sorted(provenance))),
            cash_per_share=cash_per_share,
            share_multiplier=share_multiplier,
        )


def build_exact_ensemble_features(
    root: str | Path,
    symbol: str,
    close_by_date: dict[date, float],
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Build ensemble features using the persisted V13 daily authority.

    The legacy fallback is a bucketized lineage replay for compatibility and
    is not expected to reproduce persisted V13 economic-cost metrics exactly.
    """
    fast_models = _fast_daily_models(root, symbol, close_by_date, start, end)
    if fast_models is not None:
        return _ensemble_rows(
            symbol,
            fast_models,
            feature_source=PERSISTED_DAILY_FEATURE_AUTHORITY,
        )
    return _ensemble_rows(
        symbol,
        _replayed_daily_models(root, symbol, close_by_date, start, end),
        feature_source=REPLAYED_LEGACY_OPERATOR_LOG,
    )
