from __future__ import annotations

import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_intraday_acceptance_repair_v7 as runner,
)


def test_contract_requires_at_least_fifty_without_an_upper_cap() -> None:
    contract = runner.contract_value()
    assert contract["entry_family"]["windows_completed_minutes"] == [5, 15, 30]
    assert contract["selector"]["eligibility"][
        "executable_entries_per_year_min"
    ] == 50.0
    assert "executable_entries_per_year" not in contract["selector"]["eligibility"]
    assert contract["unchanged_v4r1"]["target"] == (
        "delayed_entry + 0.80*(L-delayed_entry)"
    )


def test_acceptance_uses_only_completed_window_and_fails_closed() -> None:
    closes = pd.Series([9.9, 10.1, 10.2, 10.0, 10.3])
    assert runner.acceptance_passes(closes, 10.0, 10.25, 5)
    assert not runner.acceptance_passes(closes.iloc[:4], 10.0, 10.25, 5)
    assert not runner.acceptance_passes(
        pd.Series([10.1, 10.2, 10.3, 10.4, np.nan]), 10.0, 10.25, 5
    )


def test_next_minute_buyability_fails_closed() -> None:
    row = pd.Series(
        {
            "hard_valid": True,
            "current_day_data_tradable": True,
            "market_rule_valid": True,
            "corporate_action_blocking": False,
            "open": 10.0,
            "up_limit_price": 11.0,
        }
    )
    assert runner.next_minute_is_buyable(row)
    row["hard_valid"] = np.nan
    assert not runner.next_minute_is_buyable(row)


def _candidate(frequency: float, mean: float, window: int) -> dict:
    return {
        "window_minutes": window,
        "executable_entries_per_year": frequency,
        "portfolio_mean_net": mean,
        "portfolio_median_net": 0.04,
        "portfolio_severe10": 0.08,
        "positive_calendar_years": 5,
    }


def test_selector_has_no_frequency_ceiling_and_prefers_economics() -> None:
    assert not runner.candidate_eligible(_candidate(49.9, 0.05, 5))
    assert runner.candidate_eligible(_candidate(150.0, 0.05, 5))
    candidates = {
        "5": _candidate(58.0, 0.031, 5),
        "15": _candidate(65.0, 0.045, 15),
        "30": _candidate(120.0, 0.040, 30),
    }
    assert runner.select_candidate(candidates)["window_minutes"] == 15
