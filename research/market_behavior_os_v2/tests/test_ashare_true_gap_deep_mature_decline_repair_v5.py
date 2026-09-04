from __future__ import annotations

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_deep_mature_decline_repair_v5 as runner,
)


def test_contract_has_one_added_state_condition_and_three_levels() -> None:
    contract = runner.contract_value()
    assert contract["candidate_family"]["thresholds"] == [0.40, 0.45, 0.50]
    assert contract["candidate_family"]["only_added_condition"] == (
        "pre_gap_drawdown_from_120d_peak >= threshold"
    )
    assert contract["unchanged_v4r1"]["target"] == "entry + 0.80*(L-entry)"
    assert contract["unchanged_v4r1"]["time_stop"] == "H20"


def test_threshold_mask_fails_closed() -> None:
    frame = pd.DataFrame(
        {"pre_gap_drawdown_from_120d_peak": [0.4499, 0.45, 0.60, None]}
    )
    assert runner.threshold_mask(frame, 0.45).tolist() == [False, True, True, False]


def _candidate(threshold: float, frequency: float, severe: float = 0.08) -> dict:
    return {
        "threshold": threshold,
        "selected_signals_per_year": frequency,
        "portfolio_mean_net": 0.04,
        "portfolio_median_net": 0.05,
        "portfolio_severe10": severe,
        "positive_calendar_years": 5,
    }


def test_selector_prefers_frequency_closest_to_fifty() -> None:
    candidates = {
        "D40": _candidate(0.40, 74.6),
        "D45": _candidate(0.45, 46.2),
        "D50": _candidate(0.50, 25.2),
    }
    assert runner.select_candidate(candidates)["threshold"] == 0.45


def test_selector_rejects_candidate_outside_economic_gate() -> None:
    bad = _candidate(0.45, 50.0)
    bad["portfolio_mean_net"] = 0.0299
    assert not runner.eligible_candidate(bad)
