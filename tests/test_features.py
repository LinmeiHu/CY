from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from cyq_game.chip.core import CohortChipEngine, LogPriceGrid
from cyq_game.chip.features import (
    _maximum_window_mass,
    compute_cyqk,
    compute_features,
    earth_mover_distance,
)


def test_chip_feature_invariants_and_cohort_costs() -> None:
    grid = LogPriceGrid.around(8.0, 12.0, step_pct=0.01)
    q = grid.volume_at_price(9.0, 11.0, 10.0)
    state = CohortChipEngine(max_age=40).initialize(grid, q, date(2024, 1, 2))
    features = compute_features(
        state,
        open_price=9.9,
        high=10.4,
        low=9.6,
        close=10.1,
        history_low_2y=6.0,
        history_high_2y=14.0,
    )
    assert features.p01 <= features.p10 <= features.p50 <= features.p90 <= features.p99
    assert features.pr + features.tr == pytest.approx(1.0)
    assert features.cyc5 is not None and features.cyc13 is not None
    assert 0.0 <= features.rpy2 <= 100.0  # type: ignore[operator]
    assert 0.0 <= features.concentration_20 <= 1.0
    assert earth_mover_distance(state, state) == pytest.approx(0.0)
    assert compute_cyqk(
        state,
        open_price=9.9,
        high=10.4,
        low=9.6,
        close=10.1,
    ) == features.cyqk_pre


def test_vectorized_maximum_window_mass_matches_reference_scan() -> None:
    rng = np.random.default_rng(20260821)
    grid = LogPriceGrid.around(4.0, 32.0, step_pct=0.01)
    q = rng.random(len(grid.prices))
    q /= q.sum()
    state = CohortChipEngine(max_age=40).initialize(grid, q, date(2024, 1, 2))

    expected = max(
        float(
            state.mass[
                (state.grid.prices >= price)
                & (state.grid.prices <= price * 1.20)
            ].sum()
        )
        for price in state.grid.prices
    )

    assert _maximum_window_mass(state, 0.20) == pytest.approx(expected, abs=1e-14)
