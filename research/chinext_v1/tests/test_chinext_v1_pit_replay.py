from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from run_chinext_v1_pit_replay import concentration, reconstruct_round_trips  # noqa: E402
from run_chinext_v1_smoke import load_pit_membership  # noqa: E402


def test_pit_membership_loader_preserves_daily_age_and_has_no_fallback(tmp_path: Path) -> None:
    path = tmp_path / "membership.parquet"
    pd.DataFrame(
        [
            {
                "trade_date": "2024-01-02",
                "symbol": "300001.SZ",
                "listed_trading_days": 179,
                "pit_grade": "B_RECONSTRUCTED",
            },
            {
                "trade_date": "2024-01-03",
                "symbol": "300001.SZ",
                "listed_trading_days": 180,
                "pit_grade": "B_RECONSTRUCTED",
            },
        ]
    ).to_parquet(path, index=False)
    symbols, by_date, metadata = load_pit_membership(
        path, date(2024, 1, 2), date(2024, 1, 3)
    )
    assert symbols == ["300001.SZ"]
    assert by_date[date(2024, 1, 2)]["300001.SZ"] == 179
    assert by_date[date(2024, 1, 3)]["300001.SZ"] == 180
    assert metadata["rows"] == 2


def test_pit_membership_loader_fails_closed_on_date_gap(tmp_path: Path) -> None:
    path = tmp_path / "membership.parquet"
    pd.DataFrame(
        [
            {
                "trade_date": "2024-01-02",
                "symbol": "300001.SZ",
                "listed_trading_days": 180,
                "pit_grade": "B_RECONSTRUCTED",
            }
        ]
    ).to_parquet(path, index=False)
    with pytest.raises(ValueError, match="date range"):
        load_pit_membership(path, date(2024, 1, 2), date(2024, 1, 3))


def test_round_trip_audit_and_concentration_include_rebalance_sell_pnl() -> None:
    executions = [
        {
            "status": "FILLED",
            "side": "BUY",
            "symbol": "300001.SZ",
            "new_position": True,
            "signal_date": "2024-01-02",
            "execution_date": "2024-01-03",
            "signal_reason": "ENTRY",
            "shares": 100.0,
            "notional": 1000.0,
            "cost": 1.0,
        },
        {
            "status": "FILLED",
            "side": "SELL",
            "symbol": "300001.SZ",
            "signal_date": "2024-02-01",
            "execution_date": "2024-02-02",
            "signal_reason": "RESIZE",
            "execution_price": 11.0,
            "realized_pnl": 10.0,
            "completed_round_trip": False,
        },
        {
            "status": "FILLED",
            "side": "SELL",
            "symbol": "300001.SZ",
            "signal_date": "2024-03-01",
            "execution_date": "2024-03-04",
            "signal_reason": "MA30_X2",
            "execution_price": 12.0,
            "realized_pnl": 90.0,
            "completed_round_trip": True,
            "round_trip_return": 0.10,
        },
    ]
    trips = reconstruct_round_trips(executions)
    assert trips[0]["realized_pnl"] == 100.0
    assert trips[0]["entry_execution_date"] == "2024-01-03"
    assert trips[0]["exit_execution_date"] == "2024-03-04"
    result = concentration(trips, total_return=0.25)
    assert result["top10_positive_pnl_concentration"] == 1.0
    assert result["return_ex_best10"] == pytest.approx(0.2499)
