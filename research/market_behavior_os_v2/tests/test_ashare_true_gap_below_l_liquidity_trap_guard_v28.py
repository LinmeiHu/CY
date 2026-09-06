from __future__ import annotations

import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_liquidity_trap_guard_v28 as subject,
)


def test_prior_one_price_limit_down_count_excludes_signal_day() -> None:
    dates = pd.bdate_range("2021-01-04", periods=22)
    daily = pd.DataFrame(
        {
            "symbol": "000001.SZ",
            "trade_date": dates,
            "open": 10.0,
            "high": 10.2,
            "low": 9.8,
            "close": 10.0,
            "down_limit_price": 9.0,
        }
    )
    for offset in (0, 10, 21):
        daily.loc[offset, ["open", "high", "low", "close", "down_limit_price"]] = 9.0
    entries = pd.DataFrame(
        {
            "gap_id": ["early", "late"],
            "symbol": ["000001.SZ", "000001.SZ"],
            "signal_date": [dates[20], dates[21]],
        }
    )

    result = subject.attach_prior_limit_down_feature(entries, daily)

    assert result.prior20_one_price_limit_down_count.tolist() == [2.0, 1.0]
    assert result.liquidity_trap_guard.tolist() == [False, True]


def test_admission_fails_closed_on_missing_or_st_state() -> None:
    frame = pd.DataFrame(
        {
            "prior20_one_price_limit_down_count": [1.0, 1.0, np.nan, 2.0],
            "signal_state_hard_valid": [True, True, True, True],
            "signal_is_st": [False, True, False, False],
        }
    )

    assert subject.v28_admission_mask(frame).tolist() == [True, False, False, False]
