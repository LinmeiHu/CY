from __future__ import annotations

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_fresh_mature_decline_v19 as v19,
)


def test_fresh_memory_gate_is_inclusive_and_missing_fails_closed() -> None:
    frame = pd.DataFrame({"gap_age": [10, 30, 31, None]})
    assert v19.fresh_memory_mask(frame).tolist() == [True, True, False, False]


def test_frequency_contract_has_no_upper_cap() -> None:
    item = {
        "portfolio_accepted_trades_per_year": 500.0,
        "portfolio_mean_net": 0.031,
        "portfolio_median_net": 0.02,
        "portfolio_severe10": 0.10,
        "positive_trade_mean_years": 4,
        "positive_portfolio_years": 4,
        "attack_date_equal_mean": 0.01,
        "post_2023_signal_count": 0,
    }
    assert all(v19.development_checks(item).values())
    item["portfolio_accepted_trades_per_year"] = 49.0
    assert not v19.development_checks(item)["accepted_trades_per_year_ge_50"]


def test_runtime_restores_shared_replay_root() -> None:
    replay = v19.mature_decline.prior_decline
    original = replay.EXT_ROOT
    with v19.v19_runtime():
        assert replay.EXT_ROOT == v19.EXT_ROOT
    assert replay.EXT_ROOT == original
