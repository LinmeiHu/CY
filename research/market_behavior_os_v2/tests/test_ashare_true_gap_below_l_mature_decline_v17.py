from __future__ import annotations

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_mature_decline_v17 as v17,
)


def test_mature_decline_gate_is_inclusive_and_missing_fails_closed() -> None:
    frame = pd.DataFrame(
        {
            "pre_gap_drawdown_from_120d_peak": [0.30, 0.30, 0.299, 0.40, None],
            "pre_peak_to_gap_sessions": [20, 19, 30, 60, 80],
        }
    )
    assert v17.mature_decline_mask(frame).tolist() == [
        True,
        False,
        False,
        True,
        False,
    ]


def test_frequency_contract_is_floor_only() -> None:
    item = {
        "portfolio_accepted_trades_per_year": 250.0,
        "portfolio_mean_net": 0.031,
        "portfolio_median_net": 0.02,
        "portfolio_severe10": 0.10,
        "positive_trade_mean_years": 4,
        "positive_portfolio_years": 4,
        "attack_date_equal_mean": 0.01,
        "post_2023_signal_count": 0,
    }
    assert all(v17.development_checks(item).values())
    item["portfolio_accepted_trades_per_year"] = 49.9
    assert not v17.development_checks(item)["accepted_trades_per_year_ge_50"]


def test_runtime_restores_v16_external_root() -> None:
    original = v17.prior_decline.EXT_ROOT
    with v17.v17_runtime():
        assert v17.prior_decline.EXT_ROOT == v17.EXT_ROOT
    assert v17.prior_decline.EXT_ROOT == original
