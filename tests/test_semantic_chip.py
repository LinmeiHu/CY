from __future__ import annotations

import math
from datetime import date

import pytest

from cyq_game.chip.migration_v2 import economic_break_even_for_bucket
from cyq_game.strategy.chip_lineage import _OPERATOR_GRID
from cyq_game.strategy.current_chip_features import (
    build_current_chip_measurement_features,
)
from cyq_game.strategy.semantic_chip import (
    build_current_semantic_ensemble_features,
    build_semantic_ensemble_features,
    semantic_distribution_metrics_from_bucket_mass,
)


def _price(bucket: int) -> float:
    return economic_break_even_for_bucket(_OPERATOR_GRID, bucket)


def test_semantic_quantile_bands_use_book_probabilities() -> None:
    masses = tuple((bucket, 1.0) for bucket in range(100, 200))
    metrics = semantic_distribution_metrics_from_bucket_mass(masses, _price(150))

    assert metrics.cost_p05 == pytest.approx(_price(104))
    assert metrics.cost_p15 == pytest.approx(_price(114))
    assert metrics.cost_p85 == pytest.approx(_price(184))
    assert metrics.cost_p95 == pytest.approx(_price(194))
    assert metrics.i70_lower == metrics.cost_p15
    assert metrics.i90_upper == metrics.cost_p95
    assert metrics.known_cost_mass == pytest.approx(100.0)
    assert metrics.i70_width_fraction < metrics.i90_width_fraction


def test_semantic_peaks_are_ordered_by_price_not_mass_rank() -> None:
    masses = (
        (100, 30.0),
        (101, 60.0),
        (102, 30.0),
        (108, 20.0),
        (109, 40.0),
        (110, 20.0),
    )
    close = _price(105)
    metrics = semantic_distribution_metrics_from_bucket_mass(masses, close)

    assert metrics.lower_peak_center == pytest.approx(_price(101))
    assert metrics.upper_peak_center == pytest.approx(_price(109))
    assert metrics.valley_center is not None
    assert metrics.valley_depth is not None
    assert 0.0 <= metrics.valley_depth <= 1.0
    assert metrics.lower_peak_strength > metrics.upper_peak_strength


def test_semantic_ratios_are_invariant_to_common_log_grid_rebase() -> None:
    original = ((100, 1.0), (101, 2.0), (102, 4.0), (103, 2.0), (104, 1.0))
    shifted = tuple((bucket + 80, mass) for bucket, mass in original)
    first = semantic_distribution_metrics_from_bucket_mass(original, _price(102))
    second = semantic_distribution_metrics_from_bucket_mass(shifted, _price(182))

    assert second.profit_ratio == pytest.approx(first.profit_ratio)
    assert second.overhang_mass == pytest.approx(first.overhang_mass)
    assert second.i70_width_fraction == pytest.approx(first.i70_width_fraction)
    assert second.i90_width_fraction == pytest.approx(first.i90_width_fraction)
    assert second.lower_peak_strength == pytest.approx(first.lower_peak_strength)


def test_semantic_metrics_reject_invalid_mass_without_hiding_it() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        semantic_distribution_metrics_from_bucket_mass(((100, -1.0),), _price(100))
    with pytest.raises(ValueError, match="positive known-cost mass"):
        semantic_distribution_metrics_from_bucket_mass(((100, 0.0),), _price(100))
    with pytest.raises(ValueError, match="positive close"):
        semantic_distribution_metrics_from_bucket_mass(((100, 1.0),), math.nan)


def test_current_semantic_entry_point_does_not_weaken_development_lock(
    tmp_path,
) -> None:
    with pytest.raises(ValueError, match="physically locked before 2023"):
        build_semantic_ensemble_features(
            tmp_path, "000001.SZ", {}, date(2023, 1, 1), date(2023, 1, 3)
        )
    with pytest.raises(ValueError, match="2026-06-17"):
        build_current_semantic_ensemble_features(
            tmp_path, "000001.SZ", {}, date(2026, 6, 16), date(2026, 6, 17)
        )
    assert (
        build_current_semantic_ensemble_features(
            tmp_path, "000001.SZ", {}, date(2026, 6, 17), date(2026, 8, 24)
        )
        == []
    )
    assert (
        build_current_chip_measurement_features(
            tmp_path, "000001.SZ", {}, date(2026, 6, 17), date(2026, 8, 24)
        )
        == []
    )
