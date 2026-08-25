from __future__ import annotations

from datetime import date

import pytest

from cyq_game.config import PortfolioConfig
from cyq_game.portfolio.sizing import (
    CalibratedForecast,
    PortfolioConstraints,
    fractional_kelly_size,
)


def _constraints(**changes: float) -> PortfolioConstraints:
    values = {
        "equity": 1_000_000.0,
        "cash": 1_000_000.0,
        "current_name_fraction": 0.0,
        "current_sector_fraction": 0.0,
        "current_theme_fraction": 0.0,
        "adv_value": 100_000.0,
        "edge_capacity_fraction_adv": 0.03,
        "drawdown": 0.0,
        "reliability": 0.9,
        "observability": 0.9,
        "execution_probability": 0.9,
        "market_confidence": 0.9,
        "sector_confidence": 0.9,
    }
    values.update(changes)
    return PortfolioConstraints(**values)


def _validated_forecast(
    win_probability: float,
    average_win_r: float,
    average_loss_r: float,
    sample_size: int = 100,
) -> CalibratedForecast:
    return CalibratedForecast(
        win_probability=win_probability,
        average_win_r=average_win_r,
        average_loss_r=average_loss_r,
        sample_size=sample_size,
        out_of_sample=True,
        calibration_error=0.02,
        training_sample_size=100,
        calibration_brier=0.20,
        baseline_brier=0.25,
        calibration_train_occurrence_rate=win_probability,
        evaluation_occurrence_rate=win_probability,
        baseline_train_occurrence_rate=0.5,
        training_end=date(2020, 6, 30),
        evaluation_start=date(2020, 7, 6),
        evaluation_end=date(2020, 8, 31),
        evaluation_label_end=date(2020, 9, 7),
        purge_days=5,
        embargo_days=5,
        calibration_snapshot_id="calibration-test-snapshot",
        calibration_code_sha256="a" * 64,
    )


def test_kelly_requires_oos_calibration() -> None:
    forecast = CalibratedForecast(0.60, 1.5, 1.0, 100, False)
    result = fractional_kelly_size(forecast, _constraints(), PortfolioConfig())
    assert result.target_fraction == 0.0
    assert result.rejected_reason == "FORECAST_NOT_OOS_CALIBRATED"


def test_kelly_cannot_bypass_oos_requirement() -> None:
    forecast = CalibratedForecast(0.60, 1.5, 1.0, 10, False)
    cfg = PortfolioConfig(allow_unreliable_size=True)
    result = fractional_kelly_size(forecast, _constraints(), cfg)
    assert result.rejected_reason == "FORECAST_NOT_OOS_CALIBRATED"
    assert result.target_fraction == 0.0
    assert result.incremental_value == 0.0


def test_non_positive_kelly_is_an_explicit_no_edge_result() -> None:
    forecast = _validated_forecast(0.40, 0.6, 0.8)
    result = fractional_kelly_size(forecast, _constraints(), PortfolioConfig())
    assert result.target_fraction == 0.0
    assert result.incremental_value == 0.0
    assert result.unconstrained_kelly == 0.0
    assert result.rejected_reason == "NON_POSITIVE_KELLY"


def test_all_independent_caps_apply_after_fractional_kelly() -> None:
    forecast = _validated_forecast(0.70, 2.0, 1.0)
    result = fractional_kelly_size(forecast, _constraints(), PortfolioConfig())
    assert result.target_fraction <= 0.003 + 1e-12
    assert "EDGE_CAPACITY" in result.applied_caps
    assert result.incremental_value == pytest.approx(result.target_fraction * 1_000_000.0)


def test_min_order_notional_forces_floor() -> None:
    forecast = _validated_forecast(0.501, 1.00, 1.0, 60)
    cfg = PortfolioConfig(kelly_fraction=0.01, min_order_notional=2_000.0)
    result = fractional_kelly_size(forecast, _constraints(), cfg)
    assert "MIN_ORDER_NOTIONAL_FLOOR" in result.applied_caps
    assert result.incremental_value >= 2_000.0


def test_oos_boolean_without_actual_fold_metrics_cannot_authorize_kelly() -> None:
    forecast = CalibratedForecast(0.70, 2.0, 1.0, 100, True, 0.01)

    result = fractional_kelly_size(forecast, _constraints(), PortfolioConfig())

    assert not forecast.valid
    assert result.rejected_reason == "FORECAST_NOT_OOS_CALIBRATED"
