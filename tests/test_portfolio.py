from __future__ import annotations

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
    forecast = CalibratedForecast(0.40, 0.6, 0.8, 100, True, 0.05)
    result = fractional_kelly_size(forecast, _constraints(), PortfolioConfig())
    assert result.target_fraction == 0.0
    assert result.incremental_value == 0.0
    assert result.unconstrained_kelly == 0.0
    assert result.rejected_reason == "NON_POSITIVE_KELLY"


def test_all_independent_caps_apply_after_fractional_kelly() -> None:
    forecast = CalibratedForecast(0.70, 2.0, 1.0, 100, True, 0.05)
    result = fractional_kelly_size(forecast, _constraints(), PortfolioConfig())
    assert result.target_fraction <= 0.003 + 1e-12
    assert "EDGE_CAPACITY" in result.applied_caps
    assert result.incremental_value == pytest.approx(result.target_fraction * 1_000_000.0)


def test_min_order_notional_forces_floor() -> None:
    forecast = CalibratedForecast(0.501, 1.00, 1.0, 60, True)
    cfg = PortfolioConfig(kelly_fraction=0.01, min_order_notional=2_000.0)
    result = fractional_kelly_size(forecast, _constraints(), cfg)
    assert "MIN_ORDER_NOTIONAL_FLOOR" in result.applied_caps
    assert result.incremental_value >= 2_000.0
