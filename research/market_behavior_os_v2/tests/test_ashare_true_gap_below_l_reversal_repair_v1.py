from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts import (
    ashare_below_gap_rebound_v1_core as core,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_reversal_repair_v1 as runner,
)


def test_frozen_contract_is_below_l_and_simple() -> None:
    contract = runner.contract_value()
    assert contract["source_population"]["true_gap"] == "High_t < Low_t_minus_1"
    assert contract["inventory_gate"]["missing_policy"] == "FAIL_CLOSED"
    assert contract["formation_gate"] == "20-session pre-gap coordinate return <= 0"
    assert contract["exit"]["profit_target"] == "entry + 0.67*(L-entry)"
    assert contract["exit"]["failure_stop"] == "NONE"
    assert contract["portfolio"]["K_per_board"] == 20


def test_fixed_inventory_gate_fails_closed_on_missing() -> None:
    frame = pd.DataFrame(
        {
            "exact_minute_history": [True, True, False, True],
            "pre_gap_inside_density_relative_local": [0.9, None, 0.8, 1.1],
            "pre_gap_corridor_density_relative_local": [1.0, 0.7, 0.8, 0.7],
            "pre_gap_return_20d": [-0.01, -0.02, -0.03, -0.04],
        }
    )
    assert runner.fixed_signal_mask(frame).tolist() == [True, False, False, False]


def test_direct_true_gap_identity_uses_only_current_and_previous_rows() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2020-01-02", "2020-01-03"]),
            "cal_idx": [1, 2],
            "symbol": ["000001.SZ", "000001.SZ"],
            "symbol_seq": [0, 1],
            "sleeve": ["MAIN", "MAIN"],
            "high": [10.0, 8.9],
            "low": [9.5, 8.5],
            "close": [9.8, 8.7],
            "coordinate_factor": [1.0, 1.0],
            "invalid_step_cum": [0.0, 0.0],
            "hard_valid": [True, True],
            "history_valid": [True, True],
            "current_valid": [True, True],
            "corporate_action_valid": [True, True],
            "corporate_action_blocking": [False, False],
            "corporate_action_count": [0, 0],
        }
    )
    gaps = core.build_all_true_gaps(frame)
    assert len(gaps) == 1
    assert gaps.iloc[0].L == pytest.approx(8.9)
    assert gaps.iloc[0].U == pytest.approx(9.5)


def test_target_fill_is_strictly_t_plus_one_and_below_l() -> None:
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
            "high": [9.7, 9.6],
            "open": [9.4, 9.4],
            "coordinate_factor": [1.0, 1.0],
        }
    )
    entry = SimpleNamespace(
        entry_time=pd.Timestamp("2020-01-02 09:30"),
        entry_cal_idx=10,
        invalid_step_cum=0.0,
        gap_id="000001.SZ|2020-01-01",
    )
    target = 9.5
    assert target < 10.0
    result = runner.target_exit(path, entry, target)
    assert result is not None
    assert result["exit_date"] == pd.Timestamp("2020-01-03")
    assert result["exit_raw_price"] == pytest.approx(9.5)


def test_2024_daily_access_is_rejected_before_io() -> None:
    with pytest.raises(RuntimeError, match="2024"):
        runner.load_daily(pd.Timestamp("2024-01-01"))


def test_development_checkpoint_meets_frozen_design_targets() -> None:
    payload = json.loads(runner.DEVELOPMENT_RESULT.read_text(encoding="utf-8"))
    combined = payload["portfolio"]["COMBINED"]
    assert payload["complete_outcomes"] == 448
    assert combined["trades"] == 317
    assert combined["mean_net"] >= 0.03
    assert combined["median_net"] > 0
    assert all(value > 0 for value in combined["annual_returns"].values())
    assert payload["audit"]["entry_at_or_before_signal_count"] == 0
    assert payload["audit"]["t1_violation_count"] == 0
    assert payload["audit"]["repository_2024_plus_data_opened"] == "NO"
