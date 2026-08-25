from __future__ import annotations

from datetime import date, timedelta

import pytest

from cyq_game.strategy.chip_incremental_evaluation import (
    ForwardFold,
    apply_holm,
    fit_module_transform,
    module_evidence,
    score_evaluation_rows,
)


def _feature(day: date, value: float) -> dict[str, object]:
    return {
        "candidate_id": f"candidate-{day}-{value}",
        "trade_date": day,
        "chip_measurement_valid": True,
        "seller_model_disagreement_atr": 0.1,
        "i70_width_atr": value,
        "i90_width_atr": value * 2,
        "dominant_band_mass": 1.0 - value / 10,
        "stale_i70_width_atr": value + 0.1,
        "stale_i90_width_atr": value * 2 + 0.1,
        "stale_dominant_band_mass": 0.8 - value / 10,
        "momentum_20": value / 10,
        "close": 10.0,
        "atr14": 1.0,
        "turnover_fraction": value / 100,
        "amount_mean20": value * 1_000_000,
        "prior_breakout_excess_atr": 0.25 + value / 10,
        "industry": "TEST",
        "market_state": "NEUTRAL",
        "sector_state": "NEUTRAL",
    }


def test_module_transform_uses_fit_distribution_and_expected_directions() -> None:
    start = date(2020, 1, 2)
    fit_rows = [_feature(start + timedelta(days=index), float(index + 1)) for index in range(10)]
    evaluation = _feature(date(2021, 1, 4), 1.0)
    fold = ForwardFold(
        "TEST", start, start + timedelta(days=20), date(2021, 1, 1), date(2021, 12, 31)
    )
    transform = fit_module_transform(
        [*fit_rows, _feature(date(2021, 1, 5), 1_000.0)],
        "concentrated_support",
        fold,
    )
    scored = score_evaluation_rows([evaluation], transform)

    assert len(scored) == 1
    assert scored[0]["module_quintile"] == 5
    assert scored[0]["goodness_i70_width_atr"] == pytest.approx(0.9)
    assert transform.primitive_training_values["i70_width_atr"][-1] == 10.0


def test_holm_stops_after_first_failed_ordered_hypothesis() -> None:
    evidence = [
        {"module": "a", "placebo_empirical_p": 0.01},
        {"module": "b", "placebo_empirical_p": 0.03},
        {"module": "c", "placebo_empirical_p": 0.04},
    ]
    assert apply_holm(evidence) == {"a": True, "b": False, "c": False}


def test_module_evidence_fails_closed_when_placebo_support_is_too_small() -> None:
    rows: list[dict[str, object]] = []
    folds = (
        ("FIT_2020_EVALUATE_2021", date(2021, 2, 1)),
        ("FIT_2020_2021_EVALUATE_2022", date(2022, 2, 7)),
    )
    cutpoints = (0.2, 0.4, 0.6, 0.8)
    for fold_id, day in folds:
        for quintile, score in enumerate((0.1, 0.3, 0.5, 0.7, 0.9), start=1):
            rows.append(
                {
                    "candidate_id": f"{fold_id}-{quintile}",
                    "trade_date": day,
                    "fold_id": fold_id,
                    "module": "concentrated_support",
                    "module_score": score,
                    "module_quintile": quintile,
                    "module_quintile_cutpoints": cutpoints,
                    "stale_module_quintile": quintile,
                    "outcome_status": "FILLED",
                    "return_fraction": score / 10,
                    "industry": "TEST",
                    "market_state": "NEUTRAL",
                    "sector_state": "NEUTRAL",
                    "goodness_i70_width_atr": score,
                    "goodness_i90_width_atr": score,
                    "goodness_dominant_band_mass": score,
                    "covariate_percentile_momentum_20": 0.5,
                    "covariate_percentile_atr_fraction": 0.5,
                    "covariate_percentile_turnover_fraction": 0.5,
                    "covariate_percentile_amount_mean20": 0.5,
                    "covariate_percentile_prior_breakout_excess_atr": 0.5,
                }
            )

    evidence = module_evidence(
        rows,
        "concentrated_support",
        protocol_event_id="blind-test",
        bootstrap_resamples=20,
        placebo_permutations=5,
    )

    assert evidence["status_before_holm"] == "INSUFFICIENT_EVIDENCE"
    assert evidence["placebo_informative_rows"] < 396
    assert evidence["gates"]["informative_swappable_rows_at_least_396"] is False
