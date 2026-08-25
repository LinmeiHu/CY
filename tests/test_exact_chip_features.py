from __future__ import annotations

import math
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from cyq_game.chip.ensemble_v2 import SELLER_MODEL_ORDER
from cyq_game.chip.migration_v2 import NONPOSITIVE_ECONOMIC_BUCKET
from cyq_game.chip.peak_versions import PEAK_DEFINITION_VERSION
from cyq_game.strategy.chip_lineage import (
    _OPERATOR_GRID,
    PersistedChipLineageResolver,
)
import cyq_game.strategy.exact_chip_features as exact_chip_features
from cyq_game.strategy.exact_chip_features import (
    PERSISTED_DAILY_FEATURE_AUTHORITY,
    REPLAYED_LEGACY_OPERATOR_LOG,
    build_exact_ensemble_features,
    distribution_metrics_from_bucket_mass,
    exact_research_invalid_reason,
)


def test_exact_distribution_features_use_known_economic_cost_mass() -> None:
    low = _OPERATOR_GRID.bucket_for_price(10.0)
    high = _OPERATOR_GRID.bucket_for_price(12.0)
    metrics = distribution_metrics_from_bucket_mass(
        ((low, 80.0), (high, 20.0)), close=11.0
    )
    assert math.isclose(metrics.profit_ratio, 0.8)
    assert metrics.cost_p50 == _OPERATOR_GRID.price_for_bucket(low)
    assert metrics.cost_p90 == _OPERATOR_GRID.price_for_bucket(high)
    assert metrics.dominant_band_upper < metrics.cost_p90
    assert (
        metrics.dominant_band_lower
        <= metrics.main_peak
        <= metrics.dominant_band_upper
    )
    assert math.isclose(metrics.dominant_band_mass, 0.8)
    assert 0.0 <= metrics.asr <= 1.0
    assert 0.0 < metrics.concentration_20 <= 1.0
    assert metrics.peak_count >= 1


def test_exact_distribution_rejects_empty_known_mass() -> None:
    try:
        distribution_metrics_from_bucket_mass((), close=10.0)
    except ValueError as exc:
        assert "known mass" in str(exc)
    else:
        raise AssertionError("empty known mass must fail")


def test_exact_distribution_blocks_undefined_cbw_at_nonpositive_p01() -> None:
    high = _OPERATOR_GRID.bucket_for_price(2.0)
    metrics = distribution_metrics_from_bucket_mass(
        ((NONPOSITIVE_ECONOMIC_BUCKET, 10.0), (high, 90.0)),
        close=1.0,
    )

    assert metrics.cost_p01 == 0.0
    assert metrics.profit_ratio == 0.1
    assert metrics.cbw is None


def test_exact_research_invalid_reason_preserves_source_failure() -> None:
    assert (
        exact_research_invalid_reason(cbw_valid=True, source_valid=False)
        == "SOURCE_RESEARCH_INVALID"
    )
    assert (
        exact_research_invalid_reason(cbw_valid=False, source_valid=False)
        == "NONPOSITIVE_ECONOMIC_P01_UNDEFINED_CBW"
    )
    assert exact_research_invalid_reason(cbw_valid=True, source_valid=True) is None


def test_v13_feature_builder_uses_persisted_metrics_without_replay(
    tmp_path: Path,
    monkeypatch,
) -> None:
    symbol = "000001.SZ"
    trade_date = date(2020, 1, 2)
    available_at = datetime(2020, 1, 2, 15, tzinfo=UTC)
    rows: list[dict[str, object]] = []
    for offset, model in enumerate(SELLER_MODEL_ORDER):
        rows.append(
            {
                "storage_version": "chip-operator-log-v13",
                "symbol": symbol,
                "trade_date": trade_date,
                "seller_model": model.value,
                "snapshot_id": f"snapshot:{model.value}",
                "available_at": available_at,
                "profile_close": 11.0,
                "known_cost_fraction": 0.90 + 0.01 * offset,
                "research_valid": True,
                "average_cost": 10.0 + offset,
                "cost_p01": 8.0 + offset,
                "cost_p10": 9.0 + offset,
                "cost_p50": 10.0 + offset,
                "cost_p90": 12.0 + offset,
                "cost_p99": 13.0 + offset,
                "main_peak": 10.0 + offset,
                "dominant_band_lower": 9.5 + offset,
                "dominant_band_upper": 10.5 + offset,
                "dominant_band_mass": 0.70 + 0.01 * offset,
                "profit_ratio": 0.60 + 0.01 * offset,
                "asr": 0.50 + 0.01 * offset,
                "cbw": 50.0 + offset,
                "concentration_20": 0.80 + 0.01 * offset,
                "peak_count": 1 + offset,
                "canonical_peaks_json": json.dumps(
                    [{
                        "center_bucket": 100 + offset,
                        "center_price": 10.0 + offset,
                        "lower_bucket": 99 + offset,
                        "lower_price": 9.5 + offset,
                        "upper_bucket": 101 + offset,
                        "upper_price": 10.5 + offset,
                        "mass": 0.70 + 0.01 * offset,
                        "prominence": 0.1,
                        "width_pct": (10.5 + offset) / (9.5 + offset) - 1.0,
                        "age_mean": None,
                        "formation_date": "2020-01-02",
                        "definition_version": PEAK_DEFINITION_VERSION,
                    }]
                ),
                "cash_dividend_per_share": 0.0,
                "share_multiplier": 1.0,
                "action_provenance_ids": [],
            }
        )
    path = tmp_path / "parts" / "bucket=0" / "000001_SZ.parquet"
    path.parent.mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist(rows), path)

    def fail_replay(*_args, **_kwargs):
        raise AssertionError("v13 daily metrics must not replay inventory")

    monkeypatch.setattr(
        PersistedChipLineageResolver,
        "iter_daily_bucket_mass",
        fail_replay,
    )
    result = build_exact_ensemble_features(
        tmp_path,
        symbol,
        {trade_date: 11.0},
        trade_date,
        trade_date,
    )

    assert len(result) == 1
    assert result[0]["feature_source"] == PERSISTED_DAILY_FEATURE_AUTHORITY
    assert result[0]["average_cost"] == 11.0
    assert result[0]["peak_count"] == 2
    assert result[0]["known_cost_fraction_min"] == 0.90


def test_v13_feature_builder_falls_back_to_legacy_replay_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    symbol = "000001.SZ"
    trade_date = date(2020, 1, 3)

    available_at = datetime(2020, 1, 3, 15, tzinfo=UTC)

    def replay_rows(*_args, **_kwargs):
        return {
            trade_date: [
                {
                    "average_cost": 10.0 + offset,
                    "cost_p01": 8.0 + offset,
                    "cost_p10": 9.0 + offset,
                    "cost_p50": 10.0 + offset,
                    "cost_p90": 11.0 + offset,
                    "cost_p99": 12.0 + offset,
                    "main_peak": 10.0 + offset,
                    "dominant_band_lower": 9.5 + offset,
                    "dominant_band_upper": 10.5 + offset,
                    "dominant_band_mass": 0.7 + 0.1 * offset,
                    "profit_ratio": 0.6 + 0.05 * offset,
                    "asr": 0.5 + 0.05 * offset,
                    "cbw": 50.0 + offset,
                    "concentration_20": 0.8 + 0.05 * offset,
                    "peak_count": 1 + offset,
                    "seller_model": model.value,
                    "snapshot_id": f"snapshot:{model.value}",
                    "available_at": available_at,
                    "known_cost_fraction": 0.9,
                    "research_valid": True,
                    "canonical_peaks": (
                        exact_chip_features.CanonicalPeak(
                            center_bucket=100,
                            center_price=10.0,
                            lower_bucket=99,
                            lower_price=9.5,
                            upper_bucket=101,
                            upper_price=10.5,
                            mass=0.7,
                            prominence=0.1,
                            width_pct=10.5 / 9.5 - 1.0,
                            age_mean=None,
                            formation_date="2020-01-03",
                        ),
                    ),
                    "cash_dividend_per_share": 0.0,
                    "share_multiplier": 1.0,
                    "action_provenance_ids": (),
                }
                for offset, model in enumerate(SELLER_MODEL_ORDER)
            ]
        }

    monkeypatch.setattr(
        exact_chip_features,
        "_fast_daily_models",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        exact_chip_features,
        "_replayed_daily_models",
        replay_rows,
    )
    result = build_exact_ensemble_features(
        tmp_path,
        symbol,
        {trade_date: 10.0},
        trade_date,
        trade_date,
    )
    assert len(result) == 1
    assert result[0]["feature_source"] == REPLAYED_LEGACY_OPERATOR_LOG
