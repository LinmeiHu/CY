from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_progress_protection_v21 as v21,
)


def _entry(entry_time: str = "2020-01-01 09:30:00") -> SimpleNamespace:
    return SimpleNamespace(
        gap_id="G1",
        symbol="000001.SZ",
        entry_cal_idx=100,
        entry_time=pd.Timestamp(entry_time),
        entry_coordinate_price=80.0,
        entry_invalid_step_cum=0.0,
        L=100.0,
    )


def _days() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": "000001.SZ",
            "cal_idx": range(100, 121),
            "trade_date": pd.bdate_range("2020-01-01", periods=21),
            "hard_valid": True,
            "current_day_data_tradable": True,
            "market_rule_valid": True,
            "corporate_action_blocking": False,
            "coord_high": 84.0,
            "coord_close": 82.0,
            "invalid_step_cum": 0.0,
        }
    )


def test_progress_protection_requires_arm_then_close_back_to_entry() -> None:
    # A67 is 93.4; the fixed halfway arm is 86.7.
    days = _days()
    days.loc[2, ["coord_high", "coord_close"]] = [87.0, 85.0]
    days.loc[4, ["coord_high", "coord_close"]] = [85.0, 80.0]
    state = v21.progress_protection_state(_entry(), days)
    assert state["state_available"]
    assert state["armed"]
    assert state["armed_time"] == pd.Timestamp(days.loc[2, "trade_date"]) + pd.Timedelta(
        hours=15
    )
    assert state["trigger_time"] == pd.Timestamp(
        days.loc[4, "trade_date"]
    ) + pd.Timedelta(hours=15)


def test_unarmed_or_close_above_entry_does_not_trigger() -> None:
    unarmed = v21.progress_protection_state(_entry(), _days())
    assert not unarmed["armed"]
    assert pd.isna(unarmed["trigger_time"])

    days = _days()
    days.loc[2, ["coord_high", "coord_close"]] = [87.0, 84.0]
    armed = v21.progress_protection_state(_entry(), days)
    assert armed["armed"]
    assert pd.isna(armed["trigger_time"])


def test_incomplete_or_invalid_path_fails_closed() -> None:
    incomplete = v21.progress_protection_state(_entry(), _days().iloc[:-1])
    assert not incomplete["state_available"]
    assert pd.isna(incomplete["trigger_time"])

    days = _days()
    days.loc[3, "hard_valid"] = False
    invalid = v21.progress_protection_state(_entry(), days)
    assert not invalid["state_available"]
    assert pd.isna(invalid["trigger_time"])


def test_later_entry_does_not_use_entry_day_high_to_arm() -> None:
    days = _days()
    days.loc[0, ["coord_high", "coord_close"]] = [90.0, 79.0]
    state = v21.progress_protection_state(
        _entry("2020-01-01 09:31:00"), days
    )
    assert not state["armed"]
    assert pd.isna(state["trigger_time"])


def _development_item(frequency: float) -> dict[str, object]:
    return {
        "portfolio_accepted_trades_per_year": frequency,
        "portfolio_mean_net": 0.031,
        "portfolio_median_net": 0.01,
        "portfolio_severe10": 0.10,
        "positive_trade_mean_years": 4,
        "positive_portfolio_years": 4,
        "attack_date_equal_mean": 0.01,
        "post_2023_signal_count": 0,
    }


def test_development_frequency_is_strict_floor_without_upper_cap() -> None:
    assert all(v21.development_checks(_development_item(500.0)).values())
    assert not v21.development_checks(_development_item(50.0))[
        "accepted_trades_per_year_gt_50"
    ]


def _diagnostic_item(mean_2023: float = 0.01) -> dict[str, object]:
    return {
        "portfolio_accepted_trades_per_year": 51.0,
        "portfolio_mean_net": 0.03,
        "portfolio_median_net": 0.01,
        "portfolio_severe10": 0.10,
        "accepted_trade_yearly": {
            "2022": {"mean_net": 0.04, "median_net": 0.03, "win": 0.70},
            "2023": {"mean_net": mean_2023, "median_net": 0.0, "win": 0.50},
        },
        "portfolio": {
            "COMBINED": {"annual_returns": {"2022": 0.05, "2023": 0.01}}
        },
        "post_2023_signal_count": 0,
    }


def test_diagnostic_requires_fixed_2023_mean_median_and_win() -> None:
    assert all(v21.diagnostic_checks(_diagnostic_item()).values())
    assert not v21.diagnostic_checks(_diagnostic_item(0.0099))[
        "year_2023_trade_mean_ge_1pct"
    ]
