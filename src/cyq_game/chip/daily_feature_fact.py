"""Build the hot daily feature fact from build-time operator scalar columns.

This path never decodes inventory or lineage.  The legacy exact feature builder
remains a small-sample numerical oracle only.
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from cyq_game.chip.peak_versions import PEAK_DEFINITION_VERSION
from cyq_game.chip.peaks import CanonicalPeak, TemporalPeakTracker

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
        ("peak_definition_version", pa.string()),
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
    tracker: TemporalPeakTracker | None = None
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
                    tracker = TemporalPeakTracker(symbol=pending_key[0], model="ENSEMBLE")
                rows.append(_ensemble_row(pending, tracker))
                pending = []
            pending_key = key
            pending.append({name: columns[name][index].as_py() for name in PROJECTED_COLUMNS})
    if pending:
        if pending_key is None:
            raise AssertionError("pending feature rows have no key")
        if tracker is None:
            tracker = TemporalPeakTracker(symbol=pending_key[0], model="ENSEMBLE")
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
    models: list[dict[str, Any]], tracker: TemporalPeakTracker
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
    values = {name: median(float(row[name]) for row in models) for name in scalar_names}
    candidate = CanonicalPeak(
        center_bucket=0,
        center_price=values["dominant_peak_today"],
        lower_bucket=0,
        lower_price=values["dominant_band_lower"],
        upper_bucket=0,
        upper_price=values["dominant_band_upper"],
        mass=values["dominant_band_mass"],
        prominence=values["dominant_band_mass"],
        width_pct=values["dominant_band_upper"] / values["dominant_band_lower"] - 1.0,
        age_mean=None,
        formation_date=day.isoformat(),
    )
    tracking = tracker.update(as_of=day, candidates=(candidate,))
    tracked = tracking.tracked_base_peak
    reasons = sorted({reason for row in models for reason in (row["quality_reason_codes"] or [])})
    snapshot_id = "feature-fact-" + hashlib.sha256(
        "|".join(sorted(str(row["snapshot_id"]) for row in models)).encode()
    ).hexdigest()
    peak_state = tracking.fail_closed_reason or (
        "TRACKED" if tracked is not None else "LOST"
    )
    p50s = [float(row["cost_p50"]) for row in models]
    p90s = [float(row["cost_p90"]) for row in models]
    peaks = [float(row["dominant_peak_today"]) for row in models]
    return (
        symbol, day, snapshot_id, max(row["available_at"] for row in models),
        values["average_cost"], values["cost_p01"], values["cost_p10"], values["cost_p50"],
        values["cost_p90"], values["cost_p99"], values["profit_ratio"], values["asr"],
        values["cbw"], values["concentration_20"], values["dominant_peak_today"],
        values["dominant_band_lower"], values["dominant_band_upper"],
        values["dominant_band_mass"], round(median(int(row["peak_count"]) for row in models)),
        min(float(row["known_cost_fraction"]) for row in models),
        min(float(row["model_quality"]) for row in models), max(p50s)-min(p50s),
        max(p90s)-min(p90s), max(peaks)-min(peaks),
        None if tracked is None else tracked.center_price,
        None if tracked is None else tracked.peak_track_id,
        None if tracked is None else tracked.band[0], None if tracked is None else tracked.band[1],
        peak_state, tracked is None or tracked.ambiguity, PEAK_DEFINITION_VERSION,
        all(bool(row["hard_valid"]) for row in models),
        all(bool(row["research_valid"]) for row in models), reasons,
    )
