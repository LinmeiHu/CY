from __future__ import annotations

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_capacity_diversification_v9 as runner,
)


def test_contract_freezes_three_k_values_and_no_frequency_cap() -> None:
    contract = runner.contract_value()
    assert contract["fixed_k_family_per_board_sleeve"] == [20, 40, 80]
    assert contract["selector"]["eligibility"][
        "portfolio_accepted_trades_per_year_min"
    ] == 50.0
    assert contract["governance"]["frequency_has_no_upper_cap"] is True


def _candidate(k: int, frequency: float, mean: float) -> dict:
    return {
        "k_per_board_sleeve": k,
        "portfolio_accepted_trades_per_year": frequency,
        "portfolio_mean_net": mean,
        "portfolio_median_net": 0.04,
        "portfolio_severe10": 0.10,
        "positive_calendar_years": 5,
        "portfolio_total_return": 0.10,
    }


def test_selector_uses_no_frequency_ceiling_and_takes_smallest_passing_k() -> None:
    assert not runner.candidate_eligible(_candidate(20, 49.9, 0.04))
    assert runner.candidate_eligible(_candidate(20, 200.0, 0.04))
    candidates = {
        "20": _candidate(20, 60.0, 0.029),
        "40": _candidate(40, 100.0, 0.031),
        "80": _candidate(80, 150.0, 0.05),
    }
    assert runner.select_candidate(candidates)["k_per_board_sleeve"] == 40


def test_selector_rejects_nonpositive_total_return() -> None:
    item = _candidate(40, 100.0, 0.04)
    item["portfolio_total_return"] = 0.0
    assert not runner.candidate_eligible(item)
