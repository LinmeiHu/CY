from __future__ import annotations

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_hard_loss_boundary_v15 as runner,
)


def _candidate(rule: str, mean: float, frequency: float = 100.0) -> dict:
    return {
        "rule": rule,
        "portfolio_accepted_trades_per_year": frequency,
        "portfolio_mean_net": mean,
        "portfolio_median_net": 0.03,
        "portfolio_severe10": 0.10,
        "positive_trade_mean_years": 5,
        "positive_portfolio_years": 5,
        "attack_date_equal_mean": 0.01,
        "post_2023_signal_count": 0,
    }


def test_contract_freezes_three_daily_loss_boundaries() -> None:
    contract = runner.contract_value()
    assert tuple(contract["fixed_rule_family"]) == runner.RULES
    assert contract["selector"]["eligibility"]["frequency_has_no_upper_cap"] is True


def test_first_stop_trigger_uses_completed_close() -> None:
    entry = type(
        "Entry",
        (),
        {
            "symbol": "000001.SZ",
            "entry_cal_idx": 10,
            "entry_coordinate_price": 100.0,
            "entry_invalid_step_cum": 0.0,
        },
    )()
    days = pd.DataFrame(
        {
            "symbol": ["000001.SZ"] * 3,
            "trade_date": pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"]),
            "cal_idx": [10, 11, 12],
            "hard_valid": [True] * 3,
            "current_day_data_tradable": [True] * 3,
            "market_rule_valid": [True] * 3,
            "corporate_action_blocking": [False] * 3,
            "coord_close": [95.0, 91.0, 89.0],
            "invalid_step_cum": [0.0] * 3,
        }
    )
    assert runner.first_stop_trigger(entry, days, 0.10) == pd.Timestamp(
        "2020-01-06 15:00:00"
    )


def test_frequency_is_floor_and_selector_prefers_mean() -> None:
    assert not runner.candidate_eligible(
        _candidate("S10_DAILY_CLOSE", 0.04, 49.9)
    )
    assert runner.candidate_eligible(
        _candidate("S10_DAILY_CLOSE", 0.04, 250.0)
    )
    candidates = {
        "S0_NO_STOP": _candidate("S0_NO_STOP", 0.031),
        "S10_DAILY_CLOSE": _candidate("S10_DAILY_CLOSE", 0.04),
    }
    assert runner.select_candidate(candidates)["rule"] == "S10_DAILY_CLOSE"
