from __future__ import annotations

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_meaningful_prior_decline_v16 as v16,
)


def _development_item(trades_per_year: float) -> dict[str, object]:
    return {
        "portfolio_accepted_trades_per_year": trades_per_year,
        "portfolio_mean_net": 0.031,
        "portfolio_median_net": 0.02,
        "portfolio_severe10": 0.10,
        "positive_trade_mean_years": 4,
        "positive_portfolio_years": 4,
        "attack_date_equal_mean": 0.01,
        "post_2023_signal_count": 0,
    }


def test_prior_decline_gate_is_inclusive_and_missing_fails_closed() -> None:
    frame = pd.DataFrame(
        {"pre_gap_drawdown_from_120d_peak": [0.2999, 0.30, 0.45, None]}
    )
    assert v16.prior_decline_mask(frame).tolist() == [False, True, True, False]


def test_frequency_is_a_floor_without_upper_cap() -> None:
    assert all(v16.development_checks(_development_item(250.0)).values())
    assert not v16.development_checks(_development_item(49.9))[
        "accepted_trades_per_year_ge_50"
    ]


def test_diagnostic_requires_both_years_without_penalizing_high_frequency() -> None:
    item = _development_item(120.0)
    item.update(
        {
            "accepted_trade_yearly": {
                "2022": {"mean_net": 0.04},
                "2023": {"mean_net": 0.01},
            },
            "portfolio": {
                "COMBINED": {"annual_returns": {"2022": 0.03, "2023": 0.01}}
            },
        }
    )
    assert all(v16.diagnostic_checks(item).values())
    item["accepted_trade_yearly"]["2023"]["mean_net"] = -0.01
    assert not v16.diagnostic_checks(item)["both_year_trade_means_positive"]
