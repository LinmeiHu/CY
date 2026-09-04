from __future__ import annotations

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_target_translation_v11 as runner,
)


def test_contract_freezes_only_three_pre_l_targets() -> None:
    contract = runner.contract_value()
    assert tuple(contract["target_family"]) == ("A50", "A67", "A80")
    assert all("strictly below L" in value for value in contract["target_family"].values())
    assert contract["selector"]["eligibility"][
        "portfolio_accepted_trades_per_year_min"
    ] == 50.0


def _candidate(alpha: float, mean: float, frequency: float = 100.0) -> dict:
    return {
        "target_fraction": alpha,
        "portfolio_accepted_trades_per_year": frequency,
        "portfolio_mean_net": mean,
        "portfolio_median_net": 0.04,
        "portfolio_severe10": 0.10,
        "positive_calendar_years": 5,
        "attack_date_equal_mean": 0.01,
    }


def test_selector_has_no_frequency_ceiling_and_prefers_mean() -> None:
    assert not runner.candidate_eligible(_candidate(0.50, 0.04, 49.9))
    assert runner.candidate_eligible(_candidate(0.50, 0.04, 200.0))
    candidates = {
        "A50": _candidate(0.50, 0.031),
        "A67": _candidate(0.67, 0.045),
        "A80": _candidate(0.80, 0.040),
    }
    assert runner.select_candidate(candidates)["target_fraction"] == 0.67


def test_alpha_keys_are_deterministic() -> None:
    assert [runner.alpha_key(x) for x in runner.TARGET_FRACTIONS] == [
        "A50",
        "A67",
        "A80",
    ]
