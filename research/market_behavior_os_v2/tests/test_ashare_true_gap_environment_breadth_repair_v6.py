from __future__ import annotations

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_environment_breadth_repair_v6 as runner,
)


def test_contract_has_only_three_two_condition_environment_rules() -> None:
    contract = runner.contract_value()
    assert tuple(contract["candidate_rules"]) == runner.RULES
    assert all(len(conditions) == 2 for conditions in contract["candidate_rules"].values())
    assert contract["unchanged_v4r1"]["target"] == "entry + 0.80*(L-entry)"
    assert contract["unchanged_v4r1"]["time_stop"] == "H20"


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "board_median_ret5": [0.01, -0.01, 0.01, None],
            "board_breadth_above_ma5": [0.60, 0.60, 0.40, None],
            "board_breadth_ma5_change5": [0.10, 0.10, -0.10, None],
            "industry_median_ret5": [0.01, 0.01, 0.01, None],
        }
    )


def test_rule_masks_are_natural_and_fail_closed() -> None:
    frame = _frame()
    assert runner.rule_mask(frame, runner.RULES[0]).tolist() == [True, False, True, False]
    assert runner.rule_mask(frame, runner.RULES[1]).tolist() == [True, True, False, False]
    assert runner.rule_mask(frame, runner.RULES[2]).tolist() == [True, True, False, False]


def _candidate(rule: str, frequency: float, mean: float = 0.04) -> dict:
    return {
        "rule": rule,
        "selected_signals_per_year": frequency,
        "portfolio_mean_net": mean,
        "portfolio_median_net": 0.05,
        "portfolio_severe10": 0.08,
        "positive_calendar_years": 5,
    }


def test_selector_prefers_rule_closest_to_fifty_signals() -> None:
    candidates = {
        runner.RULES[0]: _candidate(runner.RULES[0], 80.2),
        runner.RULES[1]: _candidate(runner.RULES[1], 69.8),
        runner.RULES[2]: _candidate(runner.RULES[2], 58.0),
    }
    assert runner.select_rule(candidates)["rule"] == runner.RULES[2]


def test_economic_gate_rejects_sub_three_percent_portfolio_mean() -> None:
    item = _candidate(runner.RULES[2], 50.0, mean=0.0299)
    assert not runner.candidate_eligible(item)
