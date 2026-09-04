from __future__ import annotations

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_fast_follow_through_v14 as runner,
)


def _candidate(horizon: int, mean: float, frequency: float = 100.0) -> dict:
    return {
        "horizon": horizon,
        "portfolio_accepted_trades_per_year": frequency,
        "portfolio_mean_net": mean,
        "portfolio_median_net": 0.03,
        "portfolio_severe10": 0.10,
        "positive_trade_mean_years": 5,
        "positive_portfolio_years": 5,
        "attack_date_equal_mean": 0.01,
        "post_2023_signal_count": 0,
    }


def test_contract_freezes_natural_horizon_family() -> None:
    contract = runner.contract_value()
    assert tuple(contract["fixed_horizon_family"]) == (5, 10, 15, 20)
    assert contract["selector"]["eligibility"]["frequency_has_no_upper_cap"] is True
    assert contract["unchanged"]["target"] == "entry + 0.67*(L-entry), strictly below L"


def test_frequency_is_floor_without_upper_cap() -> None:
    assert not runner.candidate_eligible(_candidate(5, 0.04, 49.9))
    assert runner.candidate_eligible(_candidate(5, 0.04, 250.0))


def test_selector_prefers_economics_then_shorter_horizon() -> None:
    candidates = {
        "H5": _candidate(5, 0.031),
        "H10": _candidate(10, 0.04),
        "H15": _candidate(15, 0.04),
    }
    assert runner.select_candidate(candidates)["horizon"] == 10
