from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts/run_phase1_yearly_decomposition.py"
)
SPEC = importlib.util.spec_from_file_location("phase1_yearly", SCRIPT)
assert SPEC and SPEC.loader
phase1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(phase1)


def test_completed_cycle_includes_intermediate_realized_pnl() -> None:
    executions = [
        {
            "status": "FILLED",
            "side": "BUY",
            "symbol": "300001.SZ",
            "new_position": True,
            "signal_date": "2024-01-02",
            "execution_date": "2024-01-03",
            "execution_price": 10.0,
            "signal_reason": "ENTRY",
            "shares": 100.0,
            "notional": 1000.0,
            "cost": 1.0,
        },
        {
            "status": "FILLED",
            "side": "SELL",
            "symbol": "300001.SZ",
            "signal_date": "2024-01-10",
            "execution_date": "2024-01-11",
            "execution_price": 11.0,
            "signal_reason": "RESIZE",
            "shares": 50.0,
            "notional": 550.0,
            "cost": 0.55,
            "realized_pnl": 49.45,
            "completed_round_trip": False,
        },
        {
            "status": "FILLED",
            "side": "SELL",
            "symbol": "300001.SZ",
            "signal_date": "2024-01-20",
            "execution_date": "2024-01-22",
            "execution_price": 12.0,
            "signal_reason": "MARKET_MA20_X2",
            "shares": 50.0,
            "notional": 600.0,
            "cost": 0.6,
            "realized_pnl": 99.4,
            "completed_round_trip": True,
            "round_trip_return": 0.1487,
        },
    ]
    cycles = phase1.build_cycles(executions, "TEST")
    assert len(cycles) == 1
    assert cycles[0]["realized_pnl"] == pytest.approx(148.85)
    assert cycles[0]["entry_price"] == 10.0


def test_predeclared_loss_and_winner_buckets_are_boundary_exact() -> None:
    assert phase1.pnl_bucket(0.50) == "SUPER_WINNER_GE_50"
    assert phase1.pnl_bucket(0.20) == "TOP_WINNER_20_TO_50"
    assert phase1.pnl_bucket(0.0) == "SMALL_LOSS_0_TO_NEG10"
    assert phase1.pnl_bucket(-0.10) == "SEVERE_LOSS_NEG10_TO_NEG20"
    assert phase1.pnl_bucket(-0.20) == "EXTREME_LOSS_LE_NEG20"


def test_maximum_drawdown_includes_year_start_nav() -> None:
    rows = [
        {"trade_date": "2024-01-02", "nav": 90.0},
        {"trade_date": "2024-01-03", "nav": 95.0},
        {"trade_date": "2024-01-04", "nav": 80.0},
    ]
    result = phase1.maximum_drawdown(rows, 100.0)
    assert result["max_drawdown"] == pytest.approx(-0.20)
    assert result["peak_date"] == "BLOCK_OR_YEAR_START"
    assert result["trough_date"] == "2024-01-04"


def test_holding_path_uses_exit_open_and_visible_corporate_action() -> None:
    trade = {
        "trade_id": "T",
        "symbol": "300001.SZ",
        "entry_execution_date": "2024-01-02",
        "exit_execution_date": "2024-01-04",
        "entry_price": 10.0,
        "exit_price": 6.0,
        "round_trip_return": 0.20,
    }
    sessions = ["2024-01-02", "2024-01-03", "2024-01-04"]
    rows = {
        ("300001.SZ", "2024-01-02"): {
            "high": 11.0,
            "low": 9.0,
            "close": 10.0,
            "corporate_action_count": 0,
        },
        ("300001.SZ", "2024-01-03"): {
            "high": 6.0,
            "low": 4.5,
            "close": 5.5,
            "corporate_action_count": 1,
            "corporate_action_available_date": "2024-01-03",
            "corporate_action_blocking": False,
            "corporate_action_valid": True,
            "share_multiplier": 2.0,
            "cash_per_share": 0.0,
            "rights_ratio": 0.0,
        },
        ("300001.SZ", "2024-01-04"): {
            "high": 99.0,
            "low": 0.1,
            "close": 99.0,
            "corporate_action_count": 0,
        },
    }
    result = phase1.holding_features(
        trade, sessions, {day: index for index, day in enumerate(sessions)}, rows
    )
    assert result["holding_trading_days"] == 2
    assert result["mfe"] == pytest.approx(0.20)
    assert result["mae"] == pytest.approx(-0.10)
    # Exit-day high/low are ignored; the actual exit open is used.
    assert result["peak_close_return"] == pytest.approx(0.20)


def test_generated_phase1_result_remains_bound_to_frozen_baseline() -> None:
    result = phase1.json.loads(phase1.OUTPUT_JSON.read_text(encoding="utf-8"))
    assert result["result"] == "PASS"
    assert result["formal_replay_executions"] == 0
    assert result["sample"]["completed_cycles"] == 399
    assert result["sample"]["nav_blocks_are_independent"] is True
    assert result["input_identity"]["strategy_sha256"] == phase1.EXPECTED_STRATEGY
    assert {
        int(year): row["trade_metrics"]["trade_count"]
        for year, row in result["yearly"].items()
    } == phase1.EXPECTED_YEAR_TRADES
    assert all(
        "UNRESOLVED_FAIL_CLOSED" not in row["exit_lineage"]
        for row in result["yearly"].values()
    )
