from __future__ import annotations

import math

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_economic_headroom_v20 as v20,
)


def _item(frequency: float) -> dict[str, object]:
    return {
        "portfolio_accepted_trades_per_year": frequency,
        "portfolio_mean_net": 0.031,
        "portfolio_median_net": 0.02,
        "portfolio_severe10": 0.10,
        "positive_trade_mean_years": 4,
        "positive_portfolio_years": 4,
        "attack_date_equal_mean": 0.01,
        "post_2023_signal_count": 0,
    }


def test_headroom_gate_is_inclusive_and_missing_fails_closed() -> None:
    frame = pd.DataFrame({"realized_net_l_headroom": [0.0599, 0.06, 0.20, None]})
    assert v20.economic_headroom_mask(frame).tolist() == [False, True, True, False]


def test_frequency_must_be_strictly_above_50_without_upper_cap() -> None:
    assert all(v20.development_checks(_item(500.0)).values())
    assert not v20.development_checks(_item(50.0))[
        "accepted_trades_per_year_gt_50"
    ]
    assert v20.development_checks(_item(50.5))["accepted_trades_per_year_gt_50"]


def test_six_percent_headroom_implies_about_3_9_percent_a67_net() -> None:
    value = v20.implied_a67_net_target_return(0.06)
    assert math.isclose(value, 0.03888, rel_tol=0.0, abs_tol=0.0001)
