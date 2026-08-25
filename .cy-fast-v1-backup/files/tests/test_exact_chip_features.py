from __future__ import annotations

import math

from cyq_game.chip.migration_v2 import NONPOSITIVE_ECONOMIC_BUCKET
from cyq_game.strategy.chip_lineage import _OPERATOR_GRID
from cyq_game.strategy.exact_chip_features import (
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
    assert metrics.dominant_peak_today is not None
    assert metrics.dominant_band_lower is not None
    assert metrics.dominant_band_upper is not None
    assert (
        metrics.dominant_band_lower
        <= metrics.dominant_peak_today
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
    try:
        distribution_metrics_from_bucket_mass(
            ((NONPOSITIVE_ECONOMIC_BUCKET, 10.0), (high, 90.0)),
            close=1.0,
        )
    except ValueError as exc:
        assert "sentinel" in str(exc)
    else:
        raise AssertionError("nonpositive economic bucket must fail closed")


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
