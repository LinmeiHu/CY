"""Build the hot daily feature fact from persisted operator scalar columns.

This path never decodes inventory or lineage. Persisted V13 daily metrics are
the canonical daily chip-feature authority; bucketized replay is a separate
compatibility capability and is not an oracle for these scalar columns.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from cyq_game.chip.peak_versions import PEAK_DEFINITION_VERSION, PEAK_TRACK_VERSION
from cyq_game.chip.peaks import CanonicalPeak, EnsembleTemporalPeakTracker

FACT_SCHEMA = pa.schema(
    [
        ("symbol", pa.string()),
        ("trade_date", pa.date32()),
        ("snapshot_id", pa.string()),
        ("available_at", pa.timestamp("us", tz="Asia/Shanghai")),
        ("average_cost", pa.float64()),
        ("p01", pa.float64()),
        ("p10", pa.float64()),
        ("p50", pa.float64()),
        ("p90", pa.float64()),
        ("p99", pa.float64()),
        ("profit_ratio", pa.float64()),
        ("asr", pa.float64()),
        ("cbw", pa.float64()),
        ("concentration_20", pa.float64()),
        ("dominant_peak_today", pa.float64()),
        ("dominant_peak_ambiguous", pa.bool_()),
        ("dominant_band_lower", pa.float64()),
        ("dominant_band_upper", pa.float64()),
        ("dominant_band_mass", pa.float64()),
        ("peak_count", pa.int32()),
        ("known_cost_fraction_min", pa.float64()),
        ("model_quality_min", pa.float64()),
        ("model_spread_cost_p50", pa.float64()),
        ("model_spread_cost_p90", pa.float64()),
        ("model_spread_dominant_peak_today", pa.float64()),
        ("tracked_base_peak", pa.float64()),
        ("peak_track_id", pa.string()),
        ("peak_track_band_lower", pa.float64()),
        ("peak_track_band_upper", pa.float64()),
        ("peak_track_state", pa.string()),
        ("peak_track_ambiguous", pa.bool_()),
        ("peak_track_split", pa.bool_()),
        ("peak_track_merge", pa.bool_()),
        ("peak_track_lost", pa.bool_()),
        ("peak_definition_version", pa.string()),
        ("peak_track_version", pa.string()),
        ("hard_valid", pa.bool_()),
        ("research_valid", pa.bool_()),
        ("quality_reason_codes", pa.list_(pa.string())),
    ]
)

PROJECTED_COLUMNS = (
    "symbol", "trade_date", "seller_model", "snapshot_id", "available_at",
    "average_cost", "cost_p01", "cost_p10", "cost_p50", "cost_p90", "cost_p99",
    "profit_ratio", "asr", "cbw", "concentration_20", "dominant_peak_today",
    "dominant_band_lower", "dominant_band_upper", "dominant_band_mass", "peak_count",
    "canonical_peaks_json",
    "cash_dividend_per_share", "share_multiplier", "action_provenance_ids",
    "known_cost_fraction", "model_quality", "hard_valid", "research_valid",
    "quality_reason_codes",
)


def build_daily_feature_fact(operator_path: Path, output_path: Path) -> int:
    """Project one symbol operator part to one ensemble daily fact part."""

    parquet = pq.ParquetFile(operator_path)
    missing = set(PROJECTED_COLUMNS) - set(parquet.schema_arrow.names)
    if missing:
        raise ValueError(f"operator scalar schema is incomplete: {sorted(missing)}")
    rows: list[tuple[object, ...]] = []
    tracker: EnsembleTemporalPeakTracker | None = None
    pending: list[dict[str, Any]] = []
    pending_key: tuple[str, date] | None = None
    for batch in parquet.iter_batches(columns=list(PROJECTED_COLUMNS), batch_size=8192):
        columns = {name: batch.column(index) for index, name in enumerate(PROJECTED_COLUMNS)}
        for index in range(batch.num_rows):
            symbol = str(columns["symbol"][index].as_py())
            trade_date = columns["trade_date"][index].as_py()
            key = (symbol, trade_date)
            if pending_key is not None and key != pending_key:
                if tracker is None:
                    tracker = EnsembleTemporalPeakTracker(
                        symbol=pending_key[0], models=("uniform", "disposition", "active_sticky")
                    )
                rows.append(_ensemble_row(pending, tracker))
                pending = []
            pending_key = key
            pending.append({name: columns[name][index].as_py() for name in PROJECTED_COLUMNS})
    if pending:
        if pending_key is None:
            raise AssertionError("pending feature rows have no key")
        if tracker is None:
            tracker = EnsembleTemporalPeakTracker(
                symbol=pending_key[0], models=("uniform", "disposition", "active_sticky")
            )
        rows.append(_ensemble_row(pending, tracker))
    arrays = [
        pa.array([row[index] for row in rows], type=field.type)
        for index, field in enumerate(FACT_SCHEMA)
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_arrays(arrays, schema=FACT_SCHEMA), output_path,
                   compression="zstd", use_dictionary=True)
    return len(rows)


def _ensemble_row(
    models: list[dict[str, Any]], tracker: EnsembleTemporalPeakTracker
) -> tuple[object, ...]:
    if len(models) != 3 or len({str(row["seller_model"]) for row in models}) != 3:
        raise ValueError("daily feature fact requires exactly three seller models")
    symbol = str(models[0]["symbol"])
    day = models[0]["trade_date"]
    scalar_names = (
        "average_cost", "cost_p01", "cost_p10", "cost_p50", "cost_p90", "cost_p99",
        "profit_ratio", "asr", "cbw", "concentration_20", "dominant_peak_today",
        "dominant_band_lower", "dominant_band_upper", "dominant_band_mass",
    )
    for model in models:
        _validate_nullable_profile(model, scalar_names)
    values = {
        name: _required_model_median(models, name)
        for name in scalar_names
    }
    candidates_by_model = {
        str(model["seller_model"]): (
            ()
            if model["canonical_peaks_json"] is None
            else _canonical_peaks_from_json(
                model["canonical_peaks_json"], expected_day=day
            )
        )
        for model in models
    }
    _apply_peak_action(tracker, models, day)
    tracking = tracker.update(as_of=day, candidates_by_model=candidates_by_model).ensemble
    tracked = tracking.tracked_base_peak
    dominant = tracking.dominant_peak_today
    reasons = sorted({reason for row in models for reason in (row["quality_reason_codes"] or [])})
    snapshot_id = "feature-fact-" + hashlib.sha256(
        "|".join(sorted(str(row["snapshot_id"]) for row in models)).encode()
    ).hexdigest()
    peak_state = tracking.fail_closed_reason or (
        "TRACKED" if tracked is not None else "LOST"
    )
    p50_spread = _required_model_spread(models, "cost_p50")
    p90_spread = _required_model_spread(models, "cost_p90")
    peak_spread = _required_model_spread(models, "dominant_peak_today")
    peak_count = _required_model_median(models, "peak_count")
    return (
        symbol, day, snapshot_id, max(row["available_at"] for row in models),
        values["average_cost"], values["cost_p01"], values["cost_p10"], values["cost_p50"],
        values["cost_p90"], values["cost_p99"], values["profit_ratio"], values["asr"],
        values["cbw"], values["concentration_20"],
        None if dominant is None else dominant.center_price,
        dominant is None or dominant.ambiguity,
        values["dominant_band_lower"], values["dominant_band_upper"],
        values["dominant_band_mass"], None if peak_count is None else round(peak_count),
        min(float(row["known_cost_fraction"]) for row in models),
        min(float(row["model_quality"]) for row in models), p50_spread,
        p90_spread, peak_spread,
        None if tracked is None else tracked.center_price,
        None if tracked is None else tracked.peak_track_id,
        None if tracked is None else tracked.band[0], None if tracked is None else tracked.band[1],
        peak_state, tracked is None or tracked.ambiguity,
        any(peak.split for peak in tracking.peaks),
        any(peak.merge for peak in tracking.peaks),
        any(peak.lost for peak in tracking.peaks),
        PEAK_DEFINITION_VERSION,
        PEAK_TRACK_VERSION,
        all(bool(row["hard_valid"]) for row in models),
        all(bool(row["research_valid"]) for row in models), reasons,
    )


def _validate_nullable_profile(
    model: dict[str, Any], scalar_names: tuple[str, ...]
) -> None:
    """Accept only the writer's explicit all-unknown profile null state."""

    required_profile = tuple(name for name in scalar_names if name != "cbw")
    missing_required = tuple(
        name for name in required_profile if model[name] is None
    )
    if not missing_required:
        return
    all_profile_fields = (*scalar_names, "peak_count", "canonical_peaks_json")
    reasons = set(model["quality_reason_codes"] or ())
    if (
        len(missing_required) != len(required_profile)
        or any(model[name] is not None for name in all_profile_fields)
        or float(model["known_cost_fraction"]) != 0.0
        or bool(model["hard_valid"])
        or reasons.isdisjoint(
            {"UNKNOWN_COST_INITIALIZATION", "UNKNOWN_COST_PRESENT"}
        )
    ):
        raise ValueError(
            "operator profile has a partial or ungoverned nullable metric state"
        )


def _required_model_median(
    models: list[dict[str, Any]], field: str
) -> float | None:
    observations = [model[field] for model in models]
    if any(value is None for value in observations):
        return None
    return float(median(float(value) for value in observations))


def _required_model_spread(
    models: list[dict[str, Any]], field: str
) -> float | None:
    observations = [model[field] for model in models]
    if any(value is None for value in observations):
        return None
    values = [float(value) for value in observations]
    return max(values) - min(values)


def _canonical_peaks_from_json(value: object, *, expected_day: date) -> tuple[CanonicalPeak, ...]:
    """Decode only the active, complete canonical peak artifact."""

    if not isinstance(value, str):
        raise ValueError("canonical peak artifact is missing; rebuild from raw inputs")
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError("canonical peak artifact is invalid JSON") from error
    if not isinstance(payload, list):
        raise ValueError("canonical peak artifact must be a list")
    peaks: list[CanonicalPeak] = []
    required = set(CanonicalPeak.__dataclass_fields__)
    for item in payload:
        if not isinstance(item, dict) or set(item) != required:
            raise ValueError("canonical peak artifact schema is incompatible; rebuild from raw inputs")
        if item["definition_version"] != PEAK_DEFINITION_VERSION:
            raise ValueError("canonical peak artifact definition is stale; rebuild from raw inputs")
        if item["formation_date"] != expected_day.isoformat():
            raise ValueError("canonical peak artifact date is inconsistent")
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
            tuple(str(value) for value in (model["action_provenance_ids"] or [])),
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
