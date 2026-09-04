from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_no_progress_exit_v18 as v18,
)


def _entry() -> SimpleNamespace:
    return SimpleNamespace(
        gap_id="G1",
        symbol="000001.SZ",
        entry_cal_idx=100,
        entry_coordinate_price=80.0,
        entry_invalid_step_cum=0.0,
        L=100.0,
    )


def _days(maximum_high: float, d10_close: float) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "symbol": "000001.SZ",
            "cal_idx": range(100, 111),
            "trade_date": pd.date_range("2020-01-01", periods=11, freq="D"),
            "hard_valid": True,
            "current_day_data_tradable": True,
            "market_rule_valid": True,
            "corporate_action_blocking": False,
            "coord_high": 82.0,
            "coord_close": 81.0,
            "invalid_step_cum": 0.0,
        }
    )
    frame.loc[5, "coord_high"] = maximum_high
    frame.loc[10, "coord_close"] = d10_close
    return frame


def test_d10_no_progress_state_triggers_only_when_both_conditions_hold() -> None:
    # A67 target is 93.4, so half-target progress ends at 86.7.
    triggered = v18.no_progress_state(_entry(), _days(86.0, 79.0))
    assert triggered["state_available"]
    assert pd.notna(triggered["trigger_time"])

    enough_progress = v18.no_progress_state(_entry(), _days(87.0, 79.0))
    assert pd.isna(enough_progress["trigger_time"])

    above_entry = v18.no_progress_state(_entry(), _days(86.0, 81.0))
    assert pd.isna(above_entry["trigger_time"])


def test_missing_d10_state_fails_closed_to_no_trigger() -> None:
    result = v18.no_progress_state(_entry(), _days(86.0, 79.0).iloc[:-1])
    assert not result["state_available"]
    assert pd.isna(result["trigger_time"])


def test_frequency_is_floor_without_upper_cap() -> None:
    item = {
        "portfolio_accepted_trades_per_year": 300.0,
        "portfolio_mean_net": 0.031,
        "portfolio_median_net": 0.02,
        "portfolio_severe10": 0.10,
        "positive_trade_mean_years": 4,
        "positive_portfolio_years": 4,
        "attack_date_equal_mean": 0.01,
        "post_2023_signal_count": 0,
    }
    assert all(v18.development_checks(item).values())
    item["portfolio_accepted_trades_per_year"] = 49.0
    assert not v18.development_checks(item)["accepted_trades_per_year_ge_50"]
