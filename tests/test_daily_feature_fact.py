from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from cyq_game.chip.daily_feature_fact import (
    FACT_SCHEMA,
    PROJECTED_COLUMNS,
    build_daily_feature_fact,
)
from cyq_game.chip.peak_versions import PEAK_DEFINITION_VERSION


def test_daily_fact_uses_scalar_operator_columns_without_inventory_replay(
    tmp_path: Path,
) -> None:
    timestamp = datetime(2020, 1, 2, 15, tzinfo=ZoneInfo("Asia/Shanghai"))
    rows = []
    for index, model in enumerate(("uniform", "disposition", "active_sticky")):
        values = {
            "symbol": "000001.SZ", "trade_date": date(2020, 1, 2),
            "seller_model": model, "snapshot_id": f"s{index}", "available_at": timestamp,
            "average_cost": 10.0 + index * 0.1, "cost_p01": 8.0, "cost_p10": 9.0,
            "cost_p50": 10.0 + index * 0.1, "cost_p90": 11.0, "cost_p99": 12.0,
            "profit_ratio": 0.5, "asr": 0.8, "cbw": 50.0,
            "concentration_20": 0.9, "dominant_peak_today": 10.0 + index * 0.1,
            "dominant_band_lower": 9.5, "dominant_band_upper": 10.5,
            "dominant_band_mass": 0.7, "peak_count": 1,
            "canonical_peaks_json": json.dumps(
                [{
                    "center_bucket": 100, "center_price": 10.0 + index * 0.1,
                    "lower_bucket": 99, "lower_price": 9.5,
                    "upper_bucket": 101, "upper_price": 10.5,
                    "mass": 0.7, "prominence": 0.1, "width_pct": 10.5 / 9.5 - 1.0,
                    "age_mean": None, "formation_date": "2020-01-02",
                    "definition_version": PEAK_DEFINITION_VERSION,
                }]
            ),
            "cash_dividend_per_share": 0.0,
            "share_multiplier": 1.0,
            "action_provenance_ids": [],
            "known_cost_fraction": 0.99, "model_quality": 1.0,
            "hard_valid": True, "research_valid": True, "quality_reason_codes": [],
        }
        rows.append(values)
    source = tmp_path / "operator.parquet"
    pq.write_table(pa.Table.from_pylist(rows), source)
    target = tmp_path / "fact.parquet"
    assert build_daily_feature_fact(source, target) == 1
    table = pq.read_table(target)
    assert table.schema == FACT_SCHEMA
    assert table.num_rows == 1
    assert table["peak_track_id"][0].as_py()
    assert set(PROJECTED_COLUMNS).isdisjoint(
        {"checkpoint_shares", "retention_values", "inventory_adjustment_shares"}
    )


def test_daily_fact_rejects_stale_scalar_only_peak_artifact(tmp_path: Path) -> None:
    source = tmp_path / "operator.parquet"
    pq.write_table(pa.Table.from_pylist([]), source)
    with pytest.raises(ValueError, match="canonical_peaks_json"):
        build_daily_feature_fact(source, tmp_path / "fact.parquet")
import json
