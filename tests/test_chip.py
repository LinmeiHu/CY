from __future__ import annotations

from datetime import date
from math import exp

import numpy as np
import pytest

from cyq_game.chip.core import (
    CohortChipEngine,
    LogPriceGrid,
    UniformChipEngine,
    _solve_exact_sold,
    apply_cash_dividend_to_state,
    apply_split_to_state,
)


def _distribution(grid: LogPriceGrid, close: float = 10.0) -> np.ndarray:
    return grid.volume_at_price(9.5, 10.5, close)


def test_uniform_replacement_and_mass_conservation() -> None:
    grid = LogPriceGrid.around(9.0, 11.0, step_pct=0.01)
    q0 = _distribution(grid)
    q1 = grid.volume_at_price(10.0, 11.0, 10.8)
    engine = UniformChipEngine(lambda_turnover=1.0)
    initial = engine.initialize(grid, q0, date(2024, 1, 2))
    updated = engine.update(initial, q1, 0.20, 10.8, date(2024, 1, 3))
    replacement = 1.0 - exp(-0.20)
    np.testing.assert_allclose(
        updated.mass,
        q0 * (1.0 - replacement) + q1 * replacement,
        atol=1e-12,
    )
    assert float(updated.mass.sum()) == pytest.approx(1.0)


def test_cohort_exact_turnover_and_suspension_ages_only() -> None:
    grid = LogPriceGrid.around(9.0, 11.0, step_pct=0.01)
    q = _distribution(grid)
    engine = CohortChipEngine(lambda_turnover=1.0, max_age=10)
    initial = engine.initialize(grid, q, date(2024, 1, 2))
    suspended = engine.update(
        initial,
        q,
        turnover=0.50,
        close=10.0,
        as_of=date(2024, 1, 3),
        suspended=True,
    )
    assert suspended.age_mass is not None
    assert float(suspended.age_mass[:, 0].sum()) == pytest.approx(0.0)
    assert float(suspended.age_mass[:, 1].sum()) == pytest.approx(1.0)
    assert suspended.quality == 0.55

    updated = engine.update(
        suspended,
        grid.volume_at_price(10.2, 11.0, 10.8),
        turnover=0.25,
        close=10.8,
        as_of=date(2024, 1, 4),
    )
    assert float(updated.mass.sum()) == pytest.approx(1.0, abs=1e-10)
    assert updated.age_mass is not None
    np.testing.assert_allclose(updated.age_mass.sum(axis=1), updated.mass, atol=1e-10)


def test_split_remaps_cost_without_creating_mass() -> None:
    grid = LogPriceGrid.around(9.0, 11.0, step_pct=0.005)
    state = UniformChipEngine().initialize(grid, _distribution(grid), date(2024, 1, 2))
    split = apply_split_to_state(state, ratio=2.0, as_of=date(2024, 1, 3))
    assert float(split.mass.sum()) == pytest.approx(1.0)
    assert split.average_cost == pytest.approx(state.average_cost / 2.0, abs=1e-12)
    np.testing.assert_array_equal(split.mass, state.mass)


def test_cash_dividend_rebases_the_canonical_economic_cost_coordinate() -> None:
    grid = LogPriceGrid.around(9.0, 11.0, step_pct=0.005)
    state = CohortChipEngine(max_age=10).initialize(
        grid, _distribution(grid), date(2024, 1, 2)
    )

    adjusted = apply_cash_dividend_to_state(
        state, cash_per_share=0.35, as_of=date(2024, 1, 3)
    )

    assert adjusted.average_cost == pytest.approx(
        state.average_cost - 0.35, abs=1e-12
    )
    assert adjusted.economic_average_cost == pytest.approx(
        state.average_cost - 0.35, abs=1e-12
    )
    assert adjusted.cash_distributions_per_share == pytest.approx(0.35, abs=1e-12)
    assert adjusted.price_basis == "CAUSAL_ECONOMIC_BREAK_EVEN"
    np.testing.assert_array_equal(adjusted.mass, state.mass)
    np.testing.assert_array_equal(adjusted.age_mass, state.age_mass)
    assert adjusted.mass_sum == pytest.approx(1.0, abs=1e-12)


def test_cash_dividend_fails_closed_on_nonpositive_economic_cost_coordinate() -> None:
    grid = LogPriceGrid.around(0.1, 0.2, step_pct=0.01, padding=0.0)
    state = UniformChipEngine().initialize(
        grid, grid.volume_at_price(0.1, 0.2, 0.15), date(2024, 1, 2)
    )

    with pytest.raises(ValueError, match="non-positive"):
        apply_cash_dividend_to_state(state, 0.2, date(2024, 1, 3))


def test_cash_then_split_matches_causal_combined_action_order() -> None:
    grid = LogPriceGrid.around(9.0, 11.0, step_pct=0.005)
    state = UniformChipEngine().initialize(grid, _distribution(grid), date(2024, 1, 2))

    cash_then_split = apply_split_to_state(
        apply_cash_dividend_to_state(state, 0.35, date(2024, 1, 3)),
        ratio=2.0,
        as_of=date(2024, 1, 3),
    )

    assert cash_then_split.average_cost == pytest.approx(
        (state.average_cost - 0.35) / 2.0, abs=1e-12
    )
    assert cash_then_split.cash_distributions_per_share == pytest.approx(
        0.35 / 2.0, abs=1e-12
    )
    assert cash_then_split.economic_average_cost == pytest.approx(
        (state.average_cost - 0.35) / 2.0, abs=1e-12
    )
    np.testing.assert_array_equal(cash_then_split.mass, state.mass)
    assert cash_then_split.mass_sum == pytest.approx(1.0, abs=1e-12)


def test_corporate_action_replay_is_idempotent_and_conserves_mass() -> None:
    grid = LogPriceGrid.around(9.0, 11.0, step_pct=0.005)
    state = UniformChipEngine().initialize(grid, _distribution(grid), date(2024, 1, 2))

    from cyq_game.chip.core import apply_corporate_actions_to_state

    applied = apply_corporate_actions_to_state(
        state,
        as_of=date(2024, 1, 3),
        share_multiplier=2.0,
        cash_per_share=0.35,
        action_id_prefix="AAA:2024-01-03:evt-1",
    )
    replayed = apply_corporate_actions_to_state(
        applied,
        as_of=date(2024, 1, 3),
        share_multiplier=2.0,
        cash_per_share=0.35,
        action_id_prefix="AAA:2024-01-03:evt-1",
    )

    np.testing.assert_array_equal(replayed.grid.prices, applied.grid.prices)
    np.testing.assert_array_equal(replayed.mass, applied.mass)
    assert replayed.cash_distributions_per_share == pytest.approx(
        applied.cash_distributions_per_share
    )
    assert replayed.applied_action_ids == applied.applied_action_ids
    assert replayed.mass_sum == pytest.approx(1.0)


def test_observed_volume_maps_exact_minute_mass_to_nearest_log_buckets() -> None:
    grid = LogPriceGrid.around(9.0, 11.0, step_pct=0.01)
    observed = grid.observed_volume_at_price(
        prices=[9.91, 10.08, 10.08],
        volumes=[200.0, 300.0, 500.0],
    )

    assert float(observed.sum()) == pytest.approx(1.0)
    assert np.count_nonzero(observed) == 2
    assert observed[int(np.argmax(observed))] == pytest.approx(0.8)


def test_observed_volume_fast_grid_matches_reference_nearest_bucket() -> None:
    rng = np.random.default_rng(20260821)
    grid = LogPriceGrid.around(2.0, 80.0, step_pct=0.005)
    prices = np.round(
        np.exp(rng.uniform(np.log(2.01), np.log(79.9), 4000)),
        2,
    )
    volumes = rng.integers(1, 100_000, len(prices)).astype(np.float64)
    expected_indexes = np.array(
        [grid.bucket(float(price)) for price in prices],
        dtype=np.intp,
    )
    expected = np.bincount(
        expected_indexes,
        weights=volumes,
        minlength=len(grid.prices),
    )
    expected /= float(volumes.sum())

    actual = grid.observed_volume_at_price(prices, volumes)

    np.testing.assert_array_equal(actual, expected)


def test_observed_volume_irregular_grid_uses_equivalent_fallback() -> None:
    grid = LogPriceGrid(np.array([9.0, 9.7, 10.2, 12.0]), step_pct=0.01)
    prices = np.array([9.1, 9.8, 9.8, 11.9])
    volumes = np.array([1.0, 2.0, 3.0, 4.0])
    expected_indexes = np.array([grid.bucket(float(price)) for price in prices])
    expected = np.bincount(
        expected_indexes,
        weights=volumes,
        minlength=len(grid.prices),
    )
    expected /= float(volumes.sum())

    actual = grid.observed_volume_at_price(prices, volumes)

    np.testing.assert_array_equal(actual, expected)


def test_binary_bucket_lookup_matches_reference_full_grid_scan() -> None:
    grid = LogPriceGrid.around(2.0, 80.0, step_pct=0.005)
    probes = np.geomspace(grid.prices[0], grid.prices[-1], 2000)

    expected = [
        int(np.argmin(np.abs(np.log(grid.prices / float(price)))))
        for price in probes
    ]
    actual = [grid.bucket(float(price)) for price in probes]

    assert actual == expected


def test_observed_volume_rejects_invalid_or_empty_mass() -> None:
    grid = LogPriceGrid.around(9.0, 11.0, step_pct=0.01)

    with pytest.raises(ValueError, match="aligned"):
        grid.observed_volume_at_price([10.0], [1.0, 2.0])
    with pytest.raises(ValueError, match="positive"):
        grid.observed_volume_at_price([10.0], [0.0])


def _reference_bisection_sold(
    mass: np.ndarray, hazard: np.ndarray, target: float
) -> np.ndarray:
    low = 0.0
    high = 1.0
    while float((mass * (1.0 - np.exp(-high * hazard))).sum()) < target:
        high *= 2.0
    for _ in range(100):
        middle = (low + high) / 2.0
        amount = float((mass * (1.0 - np.exp(-middle * hazard))).sum())
        if amount < target:
            low = middle
        else:
            high = middle
    sold = mass * (1.0 - np.exp(-((low + high) / 2.0) * hazard))
    residual = target - float(sold.sum())
    if abs(residual) > 1e-13:
        source = mass - sold if residual > 0 else sold
        sold[np.unravel_index(int(np.argmax(source)), source.shape)] += residual
    return sold


@pytest.mark.parametrize("target", [1e-8, 0.01, 0.20, 0.75, 0.999999])
def test_safeguarded_newton_matches_reference_bisection(target: float) -> None:
    rng = np.random.default_rng(20260821)
    mass = rng.random((73, 121))
    mass /= mass.sum()
    hazard = np.exp(rng.uniform(-3.0, 2.0, mass.shape))

    expected = _reference_bisection_sold(mass, hazard, target)
    actual = _solve_exact_sold(mass, hazard, target)

    assert float(actual.sum()) == pytest.approx(target, abs=1e-13)
    assert np.all(actual >= 0.0)
    assert np.all(actual <= mass)
    np.testing.assert_allclose(actual, expected, rtol=1e-11, atol=1e-14)


@pytest.mark.parametrize("target", [0.01, 0.20, 0.75])
def test_sparse_exact_solver_matches_dense_reference(target: float) -> None:
    rng = np.random.default_rng(20260821)
    mass = np.zeros((350, 121), dtype=np.float64)
    active = rng.choice(mass.size, size=3000, replace=False)
    mass.flat[active] = rng.random(len(active))
    mass /= mass.sum()
    hazard = np.exp(rng.uniform(-3.0, 2.0, mass.shape))

    expected = _reference_bisection_sold(mass, hazard, target)
    actual = _solve_exact_sold(mass, hazard, target)

    assert float(actual.sum()) == pytest.approx(target, abs=1e-13)
    assert np.count_nonzero(actual[~(mass > 0.0)]) == 0
    np.testing.assert_allclose(actual, expected, rtol=1e-11, atol=1e-14)


@pytest.mark.parametrize("occupancy", [0.02, 0.75])
def test_fused_sell_path_matches_full_hazard_reference(occupancy: float) -> None:
    rng = np.random.default_rng(20260821)
    grid = LogPriceGrid.around(4.0, 40.0, step_pct=0.01)
    engine = CohortChipEngine(max_age=120)
    mass = np.zeros((len(grid.prices), 121), dtype=np.float64)
    active = rng.choice(
        mass.size,
        size=max(1, int(mass.size * occupancy)),
        replace=False,
    )
    mass.flat[active] = rng.random(len(active))
    mass /= mass.sum()
    close = 12.37
    target = 0.18

    expected = _solve_exact_sold(
        mass,
        engine._hazards(grid.prices, close, mass.shape[1]),
        target,
    )
    actual = engine._sell_exact(grid.prices, close, mass, target)

    assert float(actual.sum()) == pytest.approx(target, abs=1e-13)
    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-14)
