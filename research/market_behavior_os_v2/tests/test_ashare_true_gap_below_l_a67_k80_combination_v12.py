from __future__ import annotations

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_a67_k80_combination_v12 as runner,
)


def _candidate(frequency: float = 100.0, mean: float = 0.04) -> dict:
    return {
        "portfolio_accepted_trades_per_year": frequency,
        "portfolio_mean_net": mean,
        "portfolio_median_net": 0.04,
        "portfolio_severe10": 0.10,
        "positive_trade_mean_years": 5,
        "positive_portfolio_years": 5,
        "attack_date_equal_mean": 0.02,
        "max_k_violation_count": 0,
        "negative_cash_or_leverage_count": 0,
        "post_2023_signal_count": 0,
    }


def test_contract_is_single_fixed_a67_k80_combination() -> None:
    contract = runner.contract_value()
    fixed = contract["single_fixed_translation"]
    assert fixed["target"] == "entry + 0.67*(L-entry), strictly below L"
    assert fixed["k_per_board_sleeve"] == 80
    assert contract["development_gate"]["frequency_has_no_upper_cap"] is True
    assert runner.outcomes_path("DEVELOPMENT").name == "outcomes.parquet"
    assert runner.outcomes_path("DEVELOPMENT").parent.name == "a67"


def test_development_frequency_is_minimum_without_upper_cap() -> None:
    assert not all(runner.development_checks(_candidate(frequency=49.9)).values())
    assert all(runner.development_checks(_candidate(frequency=250.0)).values())
    assert not all(runner.development_checks(_candidate(mean=0.0299)).values())


def test_diagnostic_requires_both_years_without_frequency_ceiling() -> None:
    candidate = _candidate(frequency=250.0)
    candidate.update(
        {
            "accepted_trade_yearly": {
                "2022": {"mean_net": 0.04},
                "2023": {"mean_net": 0.01},
            },
            "annual_returns": {"2022": 0.05, "2023": 0.02},
        }
    )
    assert all(runner.diagnostic_checks(candidate).values())
    candidate["accepted_trade_yearly"]["2023"]["mean_net"] = -0.001
    assert not all(runner.diagnostic_checks(candidate).values())
