from __future__ import annotations

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_board_supported_reversal_v24 as v24,
)


def test_board_support_uses_natural_zero_and_fails_closed() -> None:
    frame = pd.DataFrame({"signal_board_return": [-0.0001, 0.0, 0.01, None]})
    assert v24.board_support_mask(frame).tolist() == [False, True, True, False]


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


def test_frequency_is_strict_floor_without_upper_cap() -> None:
    assert all(v24.development_checks(_development_item(500.0)).values())
    assert not v24.development_checks(_development_item(50.0))[
        "accepted_trades_per_year_gt_50"
    ]


def test_diagnostic_requires_fixed_2023_quality() -> None:
    item = {
        "portfolio_accepted_trades_per_year": 60.0,
        "portfolio_mean_net": 0.03,
        "portfolio_median_net": 0.01,
        "portfolio_severe10": 0.10,
        "accepted_trade_yearly": {
            "2022": {"mean_net": 0.04},
            "2023": {"mean_net": 0.01, "median_net": 0.0, "win": 0.50},
        },
        "portfolio": {
            "COMBINED": {"annual_returns": {"2022": 0.05, "2023": 0.01}}
        },
        "post_2023_signal_count": 0,
    }
    assert all(v24.diagnostic_checks(item).values())
    item["accepted_trade_yearly"]["2023"]["median_net"] = -0.001  # type: ignore[index]
    assert not v24.diagnostic_checks(item)[
        "year_2023_trade_median_nonnegative"
    ]
