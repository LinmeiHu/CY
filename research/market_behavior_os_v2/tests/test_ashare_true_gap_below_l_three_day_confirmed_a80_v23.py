from __future__ import annotations

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_three_day_confirmed_a80_v23 as v23,
)


def test_three_day_trigger_contract_is_stricter_than_prior_high() -> None:
    flags = v23.first_reversal.trigger_flags(
        current_close=10.5,
        previous_close=10.0,
        previous2_close=9.8,
        previous_high=10.2,
        previous3_highs=[11.0, 10.4, 10.2],
    )
    assert flags["PRIOR_HIGH_REVERSAL"]
    assert not flags["THREE_DAY_HIGH_BREAK"]


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
    assert all(v23.development_checks(_development_item(500.0)).values())
    assert not v23.development_checks(_development_item(50.0))[
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
    assert all(v23.diagnostic_checks(item).values())
    item["accepted_trade_yearly"]["2023"]["mean_net"] = 0.009  # type: ignore[index]
    assert not v23.diagnostic_checks(item)["year_2023_trade_mean_ge_1pct"]
