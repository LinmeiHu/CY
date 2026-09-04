from __future__ import annotations

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_first_reversal_v13 as runner,
)


def _candidate(mean: float, frequency: float = 100.0) -> dict:
    return {
        "trigger": "PRIOR_HIGH_REVERSAL",
        "portfolio_accepted_trades_per_year": frequency,
        "portfolio_mean_net": mean,
        "portfolio_median_net": 0.04,
        "portfolio_severe10": 0.10,
        "positive_trade_mean_years": 5,
        "positive_portfolio_years": 5,
        "attack_date_equal_mean": 0.01,
    }


def test_trigger_flags_are_exact() -> None:
    flags = runner.trigger_flags(10.5, 10.2, 10.0, 10.4, [10.1, 10.3, 10.4])
    assert flags == {
        "PRIOR_HIGH_REVERSAL": True,
        "TWO_HIGHER_CLOSES": True,
        "THREE_DAY_HIGH_BREAK": True,
    }
    flags = runner.trigger_flags(10.1, 10.2, 10.0, 10.4, [10.1, 10.3, 10.4])
    assert not flags["PRIOR_HIGH_REVERSAL"]
    assert not flags["TWO_HIGHER_CLOSES"]
    assert not flags["THREE_DAY_HIGH_BREAK"]


def test_contract_has_bounded_family_and_no_frequency_ceiling() -> None:
    contract = runner.contract_value()
    assert tuple(contract["bounded_trigger_family"]) == runner.TRIGGERS
    assert contract["development_selector"]["eligibility"][
        "accepted_trades_per_year_min"
    ] == 50.0
    assert contract["development_selector"]["eligibility"][
        "frequency_has_no_upper_cap"
    ] is True


def test_selector_frequency_is_floor_and_economics_lead() -> None:
    assert not runner.candidate_eligible(_candidate(0.04, frequency=49.9))
    assert runner.candidate_eligible(_candidate(0.04, frequency=250.0))
    candidates = {
        "PRIOR_HIGH_REVERSAL": _candidate(0.031),
        "TWO_HIGHER_CLOSES": {
            **_candidate(0.045),
            "trigger": "TWO_HIGHER_CLOSES",
        },
    }
    assert runner.select_candidate(candidates)["trigger"] == "TWO_HIGHER_CLOSES"
