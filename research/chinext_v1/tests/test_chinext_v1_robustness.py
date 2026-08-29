from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from analyze_chinext_v1_robustness import (  # noqa: E402
    cost_adjusted_nav,
    exposure_diagnostic,
    path_metrics,
    reconstruct_round_trips,
    winner_bucket,
)


def test_cost_adjustment_uses_same_fills_and_only_incremental_cost() -> None:
    nav = [
        {"trade_date": "2024-01-02", "nav": 1000.0},
        {"trade_date": "2024-01-03", "nav": 1100.0},
    ]
    executions = [
        {
            "execution_date": "2024-01-02",
            "status": "FILLED",
            "side": "BUY",
            "notional": 1000.0,
        },
        {
            "execution_date": "2024-01-03",
            "status": "FILLED",
            "side": "SELL",
            "notional": 1200.0,
        },
    ]
    adjusted = cost_adjusted_nav(nav, executions, side_bps=20.0)
    assert adjusted[0]["nav"] == 999.0
    assert adjusted[1]["nav"] == pytest.approx(1097.8)
    stamped = cost_adjusted_nav(nav, executions, side_bps=10.0, sell_stamp_bps=5.0)
    assert stamped[0]["nav"] == 1000.0
    assert stamped[1]["nav"] == pytest.approx(1099.4)


def test_round_trip_reconstruction_keeps_rebalance_legs_in_cycle() -> None:
    rows = [
        {"status": "FILLED", "side": "BUY", "symbol": "A", "new_position": True, "notional": 100.0, "execution_date": "2024-01-02"},
        {"status": "FILLED", "side": "BUY", "symbol": "A", "new_position": False, "notional": 20.0, "execution_date": "2024-01-03"},
        {"status": "FILLED", "side": "SELL", "symbol": "A", "notional": 30.0, "realized_pnl": 5.0, "completed_round_trip": False, "execution_date": "2024-01-04"},
        {"status": "FILLED", "side": "SELL", "symbol": "A", "notional": 110.0, "realized_pnl": 15.0, "completed_round_trip": True, "round_trip_return": 0.1, "execution_date": "2024-01-05"},
    ]
    result = reconstruct_round_trips(rows)
    assert result[0]["buy_notional"] == 120.0
    assert result[0]["sell_notional"] == 140.0
    assert result[0]["baseline_pnl"] == 20.0
    assert result[0]["round_trip_return"] == 0.1


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.51, "> +50%"),
        (0.50, "+20% ~ +50%"),
        (0.20, "+20% ~ +50%"),
        (0.10, "+10% ~ +20%"),
        (0.0, "0 ~ +10%"),
        (-0.10, "-10% ~ 0"),
        (-0.20, "-20% ~ -10%"),
        (-0.21, "< -20%"),
    ],
)
def test_winner_distribution_boundaries(value: float, expected: str) -> None:
    assert winner_bucket(value) == expected


def test_benchmark_metrics_are_close_to_close() -> None:
    result = path_metrics([100.0, 110.0, 121.0])
    assert result["total_return"] == pytest.approx(0.21)
    assert result["max_drawdown"] == 0.0


def test_exposure_diagnostic_does_not_reassign_flat_exit_day() -> None:
    nav = [
        {"nav": 100.0, "holdings": 1, "invested_ratio": 0.1},
        {"nav": 110.0, "holdings": 0, "invested_ratio": 0.0},
        {"nav": 121.0, "holdings": 1, "invested_ratio": 0.1},
    ]
    market = {"closes": [100.0, 90.0, 99.0]}
    result = exposure_diagnostic(nav, market)
    assert result["return_while_flat"] == pytest.approx(0.10)
    assert result["return_while_invested"] == pytest.approx(0.10)
    assert result["market_return_during_strategy_flat_days"] == pytest.approx(-0.10)
