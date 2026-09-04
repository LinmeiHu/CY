from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_failure_exit_v8 as runner,
)


def _entry() -> SimpleNamespace:
    return SimpleNamespace(
        entry_cal_idx=100,
        entry_coordinate_price=8.0,
        entry_invalid_step_cum=0.0,
        entry_time=pd.Timestamp("2020-01-02 09:31"),
        L=10.0,
        swing_low=7.5,
    )


def _days() -> pd.DataFrame:
    dates = pd.bdate_range("2020-01-02", periods=7)
    return pd.DataFrame(
        {
            "trade_date": dates,
            "cal_idx": np.arange(100, 107),
            "hard_valid": True,
            "current_day_data_tradable": True,
            "market_rule_valid": True,
            "corporate_action_blocking": False,
            "invalid_step_cum": 0.0,
            "coord_high": [8.1, 8.2, 8.3, 8.35, 8.4, 8.45, 8.5],
            "coord_close": [8.0, 7.9, 7.8, 7.7, 7.6, 7.4, 7.8],
        }
    )


def test_contract_has_no_frequency_ceiling() -> None:
    eligibility = runner.contract_value()["selector"]["eligibility"]
    assert eligibility["executable_entries_per_year_min"] == 50.0
    assert "executable_entries_per_year_max" not in eligibility
    assert runner.contract_value()["unchanged_v4r1"]["target"] == (
        "entry + 0.80*(L-entry)"
    )


def test_swing_low_break_uses_completed_close() -> None:
    trigger, reason = runner.failure_trigger_for_rule(
        _entry(), _days(), "X1_SWING_LOW_BREAK"
    )
    assert reason == "SWING_LOW_BREAK"
    assert trigger == pd.Timestamp("2020-01-09 15:00")


def test_no_progress_d3_uses_exact_causal_checkpoint() -> None:
    trigger, reason = runner.failure_trigger_for_rule(
        _entry(), _days(), "X2_NO_PROGRESS_D3"
    )
    assert reason == "NO_PROGRESS_D3"
    assert trigger == pd.Timestamp("2020-01-07 15:00")


def test_lineage_break_fails_closed() -> None:
    days = _days()
    days.loc[days.cal_idx.ge(103), "invalid_step_cum"] = 1.0
    trigger, reason = runner.failure_trigger_for_rule(
        _entry(), days, "X2_NO_PROGRESS_D3"
    )
    assert trigger is None
    assert reason is None


def _candidate(frequency: float, mean: float, rule: str) -> dict:
    return {
        "rule": rule,
        "executable_entries_per_year": frequency,
        "portfolio_mean_net": mean,
        "portfolio_median_net": 0.04,
        "portfolio_severe10": 0.08,
        "positive_calendar_years": 5,
    }


def test_selector_accepts_more_than_fifty_and_prefers_economics() -> None:
    assert not runner.candidate_eligible(
        _candidate(49.9, 0.05, "X1_SWING_LOW_BREAK")
    )
    assert runner.candidate_eligible(
        _candidate(150.0, 0.05, "X1_SWING_LOW_BREAK")
    )
    candidates = {
        "X0_H20_BASELINE": _candidate(160.0, 0.10, "X0_H20_BASELINE"),
        "X1_SWING_LOW_BREAK": _candidate(160.0, 0.031, "X1_SWING_LOW_BREAK"),
        "X2_NO_PROGRESS_D3": _candidate(160.0, 0.045, "X2_NO_PROGRESS_D3"),
    }
    assert runner.select_candidate(candidates)["rule"] == "X2_NO_PROGRESS_D3"
