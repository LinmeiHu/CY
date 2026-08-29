from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from run_chinext_v1_full_survivor import (  # noqa: E402
    monthly_metrics,
    performance_extensions,
    round_trip_rows,
    year_metrics,
)


def test_round_trip_aggregates_rebalance_and_full_exit_pnl() -> None:
    executions = [
        {
            "status": "FILLED",
            "side": "SELL",
            "symbol": "A",
            "realized_pnl": 10.0,
            "completed_round_trip": False,
            "execution_date": "2024-01-03",
        },
        {
            "status": "FILLED",
            "side": "SELL",
            "symbol": "A",
            "realized_pnl": -2.0,
            "completed_round_trip": True,
            "round_trip_return": 0.08,
            "execution_date": "2024-01-04",
        },
    ]
    assert round_trip_rows(executions) == [
        {
            "symbol": "A",
            "execution_date": "2024-01-04",
            "return": 0.08,
            "pnl": 8.0,
        }
    ]


def test_monthly_metrics_count_only_new_position_buys() -> None:
    nav = [
        {"trade_date": "2024-01-02", "holdings": 1, "invested_ratio": 0.1},
        {"trade_date": "2024-01-03", "holdings": 2, "invested_ratio": 0.2},
    ]
    executions = [
        {
            "status": "FILLED",
            "side": "BUY",
            "new_position": True,
            "execution_date": "2024-01-03",
        },
        {
            "status": "FILLED",
            "side": "BUY",
            "new_position": False,
            "execution_date": "2024-01-03",
        },
    ]
    result = monthly_metrics(nav, executions)
    assert result[0]["month"] == "2024-01"
    assert result[0]["average_holdings"] == 1.5
    assert result[0]["average_invested_ratio"] == pytest.approx(0.15)
    assert result[0]["new_entry_count"] == 1


def test_year_metrics_uses_prior_close_as_year_baseline() -> None:
    nav = [
        {"trade_date": "2025-01-02", "nav": 110.0, "holdings": 1, "invested_ratio": 0.1},
        {"trade_date": "2025-12-31", "nav": 121.0, "holdings": 2, "invested_ratio": 0.2},
    ]
    trips = [{"execution_date": "2025-06-01", "return": 0.1, "pnl": 10.0}]
    result = year_metrics(nav, trips, 2025, 100.0)
    assert result["return"] == pytest.approx(0.21)
    assert result["completed_round_trip_count"] == 1
    assert result["win_rate"] == 1.0


def test_sharpe_extension_is_deterministic_and_zero_rate_defined() -> None:
    nav = [
        {"nav": 1_000_000.0},
        {"nav": 1_010_000.0},
        {"nav": 1_005_000.0},
    ]
    first = performance_extensions(nav)
    second = performance_extensions(nav)
    assert first == second
    assert first["volatility"] > 0
    assert first["sharpe_zero_risk_free"] is not None
