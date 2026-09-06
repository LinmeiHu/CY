from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts/run_ashare_quiet_inventory_structural_acceptance_research_v2.py"
)
SPEC = importlib.util.spec_from_file_location("quiet_inventory_v2", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def candidate() -> pd.Series:
    return pd.Series(
        {
            "event_id": "e1",
            "symbol": "000001.SZ",
            "sleeve": "MAIN",
            "signal_date": pd.Timestamp("2020-01-02"),
            "signal_cal_idx": 100,
            "signal_invalid_step_cum": 0.0,
            "platform_high": 10.0,
            "platform_low": 8.0,
        }
    )


def row(cal_idx: int, close: float, high: float | None = None) -> dict[str, object]:
    price_high = close if high is None else high
    return {
        "trade_date": pd.Timestamp("2020-01-02") + pd.offsets.BDay(cal_idx - 100),
        "cal_idx": cal_idx,
        "open": close,
        "high": price_high,
        "low": close,
        "close": close,
        "coord_open": close,
        "coord_high": price_high,
        "coord_low": close,
        "coord_close": close,
        "coordinate_factor": 1.0,
        "invalid_step_cum": 0.0,
        "trade_status": 1,
        "current_day_data_tradable": True,
        "current_valid": True,
        "market_rule_valid": True,
        "corporate_action_valid": True,
        "corporate_action_blocking": False,
        "hard_valid": True,
        "up_limit_price": close * 1.1,
        "down_limit_price": close * 0.9,
    }


def test_first_legal_close_failure_cannot_be_repaired_by_later_recovery() -> None:
    path = pd.DataFrame([row(101, 9.9), row(102, 10.5), row(103, 10.6)])
    result = MODULE.replay_one(candidate(), path)
    assert result["status"] == "REJECTED_FIRST_LEGAL_CLOSE_BELOW_PLATFORM"
    assert result["confirmation_cal_idx"] == 101
    assert not result["accepted"]


def test_confirmation_bar_never_fills_and_entry_is_strictly_later() -> None:
    path = pd.DataFrame(
        [row(101, 10.2, 11.5), row(102, 10.3), row(103, 11.4, 11.4)]
    )
    result = MODULE.replay_one(candidate(), path)
    assert result["accepted"]
    assert result["confirmation_cal_idx"] == 101
    assert result["entry_cal_idx"] == 102
    assert result["exit_cal_idx"] == 103
    assert result["exit_reason"] == "TARGET_10"


def test_entry_day_high_cannot_hit_target() -> None:
    entry = row(102, 10.0, 12.0)
    path = pd.DataFrame([row(101, 10.2), entry, row(103, 11.0, 11.0)])
    result = MODULE.replay_one(candidate(), path)
    assert result["entry_cal_idx"] == 102
    assert result["exit_cal_idx"] == 103
    assert result["holding_sessions"] == 1
