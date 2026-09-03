from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_capitulation_repair_v3 as runner,
)


def test_contract_is_simple_below_gap_capitulation_repair() -> None:
    contract = runner.contract_value()
    assert contract["source_population"]["true_gap"] == "High_t < Low_t_minus_1"
    assert contract["formation_gate"] == "20-session pre-gap coordinate return <= 0"
    assert contract["reversal_gate"]["minimum_recovery_from_20_session_low"] == 0.05
    assert contract["reversal_gate"]["trigger"] == "first completed daily MA5 reclaim"
    assert contract["exit"]["profit_target"] == "entry + 0.80*(L-entry)"
    assert contract["exit"]["failure_stop"] == "NONE"
    assert contract["portfolio"]["K_per_board"] == 20


def test_fixed_signal_mask_fails_closed() -> None:
    frame = pd.DataFrame(
        {
            "exact_minute_history": [True, True, True, False, True, True],
            "pre_gap_inside_density_relative_local": [0.8, None, 1.1, 0.8, 0.8, 0.8],
            "pre_gap_corridor_density_relative_local": [0.9, 0.9, 0.9, 0.9, 0.9, 0.9],
            "pre_gap_return_20d": [-0.01, -0.01, -0.01, -0.01, 0.01, -0.01],
            "recovery_from_low20": [0.05, 0.05, 0.05, 0.05, 0.05, 0.049],
        }
    )
    assert runner.fixed_signal_mask(frame).tolist() == [
        True,
        False,
        False,
        False,
        False,
        False,
    ]


def test_target_is_strictly_below_l_and_t_plus_one() -> None:
    path = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2020-01-02", "2020-01-03"]),
            "bar_end_time": pd.to_datetime(
                ["2020-01-02 10:00", "2020-01-03 10:00"]
            ),
            "cal_idx": [10, 11],
            "invalid_step_cum": [0.0, 0.0],
            "hard_valid": [True, True],
            "trade_status": [1, 1],
            "current_day_data_tradable": [True, True],
            "market_rule_valid": [True, True],
            "corporate_action_blocking": [False, False],
            "high": [9.9, 9.9],
            "open": [9.2, 9.2],
            "coordinate_factor": [1.0, 1.0],
        }
    )
    entry = SimpleNamespace(
        entry_time=pd.Timestamp("2020-01-02 09:30"),
        entry_cal_idx=10,
        invalid_step_cum=0.0,
        gap_id="000001.SZ|2020-01-01",
    )
    target = 9.0 + runner.TARGET_FRACTION * (10.0 - 9.0)
    assert target < 10.0
    result = runner.v1.target_exit(path, entry, target)
    assert result is not None
    assert result["exit_date"] == pd.Timestamp("2020-01-03")
    assert result["exit_raw_price"] == pytest.approx(target)


def test_2024_daily_access_is_rejected_before_io() -> None:
    with pytest.raises(RuntimeError, match="2024"):
        runner.v1.load_daily(pd.Timestamp("2024-01-01"))


def test_development_checkpoint_meets_preregistered_targets() -> None:
    payload = json.loads(runner.DEVELOPMENT_RESULT.read_text(encoding="utf-8"))
    combined = payload["portfolio"]["COMBINED"]
    assert 40 <= combined["trades"] / 5 <= 70
    assert combined["mean_net"] >= 0.03
    assert combined["median_net"] > 0
    assert all(value > 0 for value in combined["annual_returns"].values())
    assert payload["audit"]["feature_uses_post_signal_information_count"] == 0
    assert payload["audit"]["entry_at_or_before_signal_count"] == 0
    assert payload["audit"]["target_at_or_above_L_count"] == 0
    assert payload["audit"]["t1_violation_count"] == 0
    assert payload["audit"]["repository_2024_plus_data_opened"] == "NO"
