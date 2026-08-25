from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from cyq_game.strategy.economic_selection import (
    CandidateAssessment,
    assess_candidate,
    cluster_bootstrap_trimmed_interval,
    select_robust_region,
    weekly_cluster_evidence,
)
from cyq_game.strategy.markup_retest import (
    StrategyParameters,
    load_markup_retest_config,
)
from cyq_game.strategy.research import entry_parameter_grid


def _passing_metrics(**updates: Any) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "distinct_signal_weeks": 130,
        "effective_sample": 450.0,
        "bootstrap_half_width": 0.005,
        "entry_fill_rate": 0.99,
        "closed_trade_rate": 0.99,
        "bootstrap_lower_95": 0.001,
        "baseline_difference_lower_95": 0.001,
        "profit_factor": 1.1,
        "portfolio_max_drawdown_fraction": -0.10,
        "blocked_tail_loss_ratio": 0.005,
        "trade_cvar_1pct": -0.20,
        "first_5m_participation_p95": 0.08,
        "first_5m_participation_max": 0.20,
        "maximum_concurrent_positions": 40,
        "maximum_concurrent_same_industry_positions": 8,
        "maximum_same_day_new_entries": 8,
    }
    metrics.update(updates)
    return metrics


def _grid_values(
    parameters: tuple[StrategyParameters, ...],
) -> dict[str, tuple[float, ...]]:
    return {
        name: tuple(sorted({float(getattr(item, name)) for item in parameters}))
        for name in (
            "setup_score_min",
            "breakout_buffer_atr",
            "max_retest_depth_atr",
            "min_cost_migration_atr",
        )
    }


def test_isolated_economic_pass_cannot_enter_formal_selection() -> None:
    parameters = entry_parameter_grid(load_markup_retest_config())
    isolated = parameters[0].parameter_id
    assessments = tuple(
        assess_candidate(
            item.parameter_id,
            _passing_metrics()
            if item.parameter_id == isolated
            else _passing_metrics(bootstrap_lower_95=-0.001),
        )
        for item in parameters
    )
    metrics = {item.parameter_id: _passing_metrics() for item in parameters}

    decision = select_robust_region(
        parameters,
        assessments,
        metrics,
        _grid_values(parameters),
    )

    assert decision.decision == "NO_TRADE"
    assert decision.reason_codes == ("NO_ROBUST_ENTRY_REGION",)
    isolated_assessment = next(
        item for item in decision.assessments if item.parameter_id == isolated
    )
    assert isolated_assessment.base_gate_pass is True
    assert isolated_assessment.adjacent_economic_passes == 0
    assert isolated_assessment.robust_region_eligible is False


def test_annual_counts_are_diagnostics_only_for_economic_gate() -> None:
    metrics = _passing_metrics(
        annual_signal_counts={2020: 1, 2021: 2_000, 2022: 4},
        mean_annual_signals=668.333,
    )

    assessment = assess_candidate("parameter", metrics)

    assert assessment.status == "PASS"
    assert assessment.reason_codes == ()


def test_high_signal_count_fails_only_when_capacity_metric_fails() -> None:
    high_count = _passing_metrics(raw_signal_count=100_000)

    passing = assess_candidate("capacity-pass", high_count)
    failing = assess_candidate(
        "capacity-fail",
        {**high_count, "maximum_concurrent_positions": 51},
    )

    assert passing.status == "PASS"
    assert failing.status == "FAIL"
    assert failing.reason_codes == ("MAXIMUM_CONCURRENT_POSITIONS_EXCEEDED",)


def test_every_entry_grid_point_requires_an_assessment() -> None:
    parameters = entry_parameter_grid(load_markup_retest_config())
    assessments = tuple(
        CandidateAssessment(
            parameter_id=item.parameter_id,
            status="INSUFFICIENT_EVIDENCE",
            base_gate_pass=False,
            reason_codes=("EFFECTIVE_SAMPLE_BELOW_MINIMUM",),
        )
        for item in parameters
    )
    metrics = {item.parameter_id: _passing_metrics() for item in parameters}

    decision = select_robust_region(
        parameters,
        assessments,
        metrics,
        _grid_values(parameters),
    )

    assert len(decision.assessments) == 81
    assert decision.decision == "NO_TRADE"
    assert decision.reason_codes == ("INSUFFICIENT_EVIDENCE",)
    with pytest.raises(ValueError, match="every parameter"):
        select_robust_region(
            parameters,
            assessments[:-1],
            metrics,
            _grid_values(parameters),
        )


def test_three_point_economic_platform_selects_grid_medoid() -> None:
    parameters = entry_parameter_grid(load_markup_retest_config())
    origin = parameters[0]
    platform = tuple(
        item
        for item in parameters
        if item.setup_score_min == origin.setup_score_min
        and item.max_retest_depth_atr == origin.max_retest_depth_atr
        and item.min_cost_migration_atr == origin.min_cost_migration_atr
    )
    assert len(platform) == 3
    platform_ids = {item.parameter_id for item in platform}
    assessments = tuple(
        assess_candidate(
            item.parameter_id,
            _passing_metrics()
            if item.parameter_id in platform_ids
            else _passing_metrics(bootstrap_lower_95=-0.001),
        )
        for item in parameters
    )
    metrics = {item.parameter_id: _passing_metrics() for item in parameters}

    decision = select_robust_region(
        parameters,
        assessments,
        metrics,
        _grid_values(parameters),
    )

    expected_medoid = sorted(platform, key=lambda item: item.breakout_buffer_atr)[1]
    assert decision.decision == "PASS"
    assert set(decision.selected_component) == platform_ids
    assert decision.selected_parameter_id == expected_medoid.parameter_id
    assert all(
        item.robust_region_eligible
        for item in decision.assessments
        if item.parameter_id in platform_ids
    )


def test_weekly_cluster_bootstrap_is_deterministic_and_uses_trimmed_return() -> None:
    weekly = {
        f"2020-W{week:02d}": (0.01, 0.02, -0.01) for week in range(1, 11)
    }

    first = weekly_cluster_evidence(weekly, parameter_id="stable", resamples=100)
    second = weekly_cluster_evidence(weekly, parameter_id="stable", resamples=100)

    assert first == second
    assert first["trade_count"] == 30
    assert first["distinct_signal_weeks"] == 10


def test_vector_cluster_bootstrap_matches_scalar_multiset_reference() -> None:
    clusters = (
        (-0.30, 0.01, 0.02),
        (0.03,),
        (-0.02, 0.04, 0.05, 0.80),
        (0.0, 0.01),
    )
    resamples = 997
    seed = 123456
    generator = np.random.default_rng(seed)
    scalar = np.empty(resamples, dtype=np.float64)
    for index in range(resamples):
        sampled = generator.integers(0, len(clusters), size=len(clusters))
        values = [
            value
            for cluster_index in sampled
            for value in clusters[int(cluster_index)]
        ]
        ordered = sorted(values)
        trim = len(ordered) * 5 // 100
        kept = ordered[trim : len(ordered) - trim] if trim else ordered
        scalar[index] = sum(kept) / len(kept)
    expected = np.quantile(scalar, (0.025, 0.975))

    batched = cluster_bootstrap_trimmed_interval(
        clusters,
        resamples=resamples,
        seed=seed,
        batch_size=17,
    )
    full = cluster_bootstrap_trimmed_interval(
        clusters,
        resamples=resamples,
        seed=seed,
        batch_size=resamples,
    )

    assert batched == pytest.approx(expected, abs=1.0e-15)
    assert full == pytest.approx(expected, abs=1.0e-15)
