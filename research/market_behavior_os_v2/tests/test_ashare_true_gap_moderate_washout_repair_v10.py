from __future__ import annotations

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_moderate_washout_repair_v10 as runner,
)


def test_contract_preserves_low_occupancy_direct_population() -> None:
    contract = runner.contract_value()
    assert contract["source_population"]["daily_low_occupancy"] == {
        "inside_gap_touch_sessions_max": 12,
        "gap_corridor_touch_sessions_max": 20,
    }
    assert contract["execution"]["target"] == "entry + 0.80*(L-entry), strictly below L"
    assert "pre_gap_inside_touch_sessions / 120" in contract["execution"][
        "collision_low_occupancy_rank"
    ]
    assert contract["selector"]["eligibility"][
        "portfolio_accepted_trades_per_year_min"
    ] == 50.0


def test_rule_masks_are_bounded_and_fail_closed() -> None:
    frame = pd.DataFrame(
        {
            "max_depth": [0.1499, 0.15, 0.25, 0.30, 0.3001, None],
            "recovery_from_low20": [0.10, 0.049, 0.05, 0.15, 0.10, None],
        }
    )
    assert runner.rule_mask(frame, "DEPTH_15_25").tolist() == [
        False, True, True, False, False, False
    ]
    assert runner.rule_mask(frame, "DEPTH_15_30").tolist() == [
        False, True, True, True, False, False
    ]
    assert runner.rule_mask(frame, "DEPTH_15_30_RECOVERY_05_15").tolist() == [
        False, False, True, True, False, False
    ]


def _candidate(rule: str, frequency: float, mean: float, conditions: int) -> dict:
    return {
        "rule": rule,
        "conditions": conditions,
        "portfolio_accepted_trades_per_year": frequency,
        "portfolio_mean_net": mean,
        "portfolio_median_net": 0.04,
        "portfolio_severe10": 0.10,
        "positive_calendar_years": 5,
        "attack_date_equal_mean": 0.01,
    }


def test_selector_prefers_more_frequency_after_all_hard_gates() -> None:
    assert not runner.candidate_eligible(
        _candidate("DEPTH_15_25", 49.9, 0.05, 1)
    )
    candidates = {
        "DEPTH_15_25": _candidate("DEPTH_15_25", 100.0, 0.05, 1),
        "DEPTH_15_30": _candidate("DEPTH_15_30", 130.0, 0.031, 1),
        "DEPTH_15_30_RECOVERY_05_15": _candidate(
            "DEPTH_15_30_RECOVERY_05_15", 90.0, 0.06, 2
        ),
    }
    assert runner.select_candidate(candidates)["rule"] == "DEPTH_15_30"
