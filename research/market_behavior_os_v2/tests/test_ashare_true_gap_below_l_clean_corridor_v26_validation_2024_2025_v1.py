from __future__ import annotations

import math

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_clean_corridor_v26_validation_2024_2025_v1 as subject,
)


def _raw(rows: list[dict[str, object]]) -> pd.DataFrame:
    defaults: dict[str, object] = {
        "decision_at": pd.Timestamp("2024-01-01 15:00"),
        "open": 10.0,
        "high": 10.2,
        "low": 9.8,
        "close": 10.0,
        "volume": 1.0,
        "amount": 10.0,
        "turnover_fraction": 0.01,
        "trade_status": 1,
        "is_st": False,
        "up_limit_price": 11.0,
        "down_limit_price": 9.0,
        "industry": "TEST",
        "corporate_action_count": 0,
        "corporate_action_valid": True,
        "corporate_action_blocking": False,
        "share_multiplier": 1.0,
        "cash_per_share": 0.0,
        "rights_ratio": 0.0,
        "rights_price": 0.0,
        "market_rule_valid": True,
        "industry_valid": True,
        "historical_identity_valid": True,
        "hard_valid": True,
        "current_day_data_tradable": True,
        "available_at": pd.Timestamp("2024-01-01 15:00"),
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


def test_coordinate_reconstruction_action_invalid_and_recovery() -> None:
    raw = _raw(
        [
            {"trade_date": "2024-01-02", "symbol": "000001.SZ", "close": 10.0},
            {
                "trade_date": "2024-01-03",
                "symbol": "000001.SZ",
                "close": 4.5,
                "corporate_action_count": 1,
                "share_multiplier": 2.0,
                "cash_per_share": 1.0,
            },
            {
                "trade_date": "2024-01-04",
                "symbol": "000001.SZ",
                "close": 4.0,
                "hard_valid": False,
                "current_day_data_tradable": False,
            },
            {"trade_date": "2024-01-05", "symbol": "000001.SZ", "close": 5.0},
        ]
    )
    calendar = pd.DataFrame(
        {"trade_date": pd.to_datetime(raw.trade_date), "cal_idx": [1, 2, 3, 4]}
    )
    seeds = {
        "000001.SZ": {
            "factor": 1.0,
            "invalid_step_cum": 7.0,
            "previous_current_valid": True,
            "last_valid_raw_close": 10.0,
            "last_valid_coordinate_close": 10.0,
        }
    }
    result = subject.reconstruct_qd010_coordinate(raw, seeds, calendar)
    assert result.coordinate_factor.iloc[0] == 1.0
    assert math.isclose(result.coordinate_factor.iloc[1], 10 / 4.5)
    assert math.isclose(result.coord_close.iloc[1], 10.0)
    assert result.invalid_step_cum.tolist() == [7.0, 7.0, 8.0, 9.0]
    assert result.current_valid.tolist() == [True, True, False, True]
    assert math.isclose(result.coord_close.iloc[2], 10.0)
    assert math.isclose(result.coord_close.iloc[3], 10.0)


def test_new_listing_coordinate_initializes_without_future_information() -> None:
    raw = _raw(
        [{"trade_date": "2024-01-02", "symbol": "301001.SZ", "close": 20.0}]
    )
    calendar = pd.DataFrame(
        {"trade_date": pd.to_datetime(raw.trade_date), "cal_idx": [1]}
    )
    result = subject.reconstruct_qd010_coordinate(raw, {}, calendar)
    assert math.isclose(result.coordinate_factor.iloc[0], 0.05)
    assert math.isclose(result.coord_close.iloc[0], 1.0)
    assert result.invalid_step_cum.iloc[0] == 1.0


def test_validation_checks_are_frozen_and_year_specific() -> None:
    combined = {
        "mean_net": 0.031,
        "median_net": 0.01,
        "severe10": 0.10,
        "annual_returns": {"2024": 0.01, "2025": 0.02},
    }
    yearly = {
        "2024": {"trades": 51, "mean_net": 0.02},
        "2025": {"trades": 51, "mean_net": 0.01},
    }
    assert all(subject.validation_checks(combined, yearly).values())
    yearly["2025"]["mean_net"] = -0.001
    assert not subject.validation_checks(combined, yearly)[
        "each_2024_2025_trade_mean_positive"
    ]
