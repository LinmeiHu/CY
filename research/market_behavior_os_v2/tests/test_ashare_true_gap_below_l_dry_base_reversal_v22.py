from __future__ import annotations

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_dry_base_reversal_v22 as v22,
)


def test_dry_base_uses_natural_no_expansion_boundary_and_fails_closed() -> None:
    frame = pd.DataFrame({"dry3": [0.99, 1.0, 1.01, None]})
    assert v22.dry_base_mask(frame).tolist() == [True, True, False, False]


def _development_item(frequency: float) -> dict[str, object]:
    return {
        "portfolio_accepted_trades_per_year": frequency,
        "portfolio_mean_net": 0.031,
        "portfolio_median_net": 0.01,
        "portfolio_severe10": 0.10,
        "positive_trade_mean_years": 5,
        "positive_portfolio_years": 4,
        "attack_date_equal_mean": 0.01,
        "post_2023_signal_count": 0,
    }


def test_frequency_is_strict_floor_without_upper_cap() -> None:
    assert all(v22.development_checks(_development_item(500.0)).values())
    assert not v22.development_checks(_development_item(50.0))[
        "accepted_trades_per_year_gt_50"
    ]


def _diagnostic_item() -> dict[str, object]:
    return {
        "portfolio_accepted_trades_per_year": 50.5,
        "portfolio_mean_net": 0.03,
        "portfolio_median_net": 0.01,
        "portfolio_severe10": 0.10,
        "accepted_trade_yearly": {
            "2022": {"mean_net": 0.04, "median_net": 0.03, "win": 0.70},
            "2023": {"mean_net": 0.01, "median_net": 0.0, "win": 0.50},
        },
        "portfolio": {
            "COMBINED": {"annual_returns": {"2022": 0.05, "2023": 0.01}}
        },
        "post_2023_signal_count": 0,
    }


def test_diagnostic_requires_2023_mean_median_and_win() -> None:
    item = _diagnostic_item()
    assert all(v22.diagnostic_checks(item).values())
    item["accepted_trade_yearly"]["2023"]["win"] = 0.49  # type: ignore[index]
    assert not v22.diagnostic_checks(item)["year_2023_win_ge_50pct"]
