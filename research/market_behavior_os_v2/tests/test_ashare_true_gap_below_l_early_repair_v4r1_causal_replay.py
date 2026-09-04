from __future__ import annotations

import inspect
from types import SimpleNamespace

import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_early_repair_v4r1_causal_replay as replay,
)


def test_contract_preserves_v4_alpha_and_restricts_later_data_to_trade_resolution() -> None:
    contract = replay.contract_value()
    rule = contract["frozen_rule"]
    assert rule["minimum_recovery"] == 0.03
    assert rule["target"] == "entry + 0.80*(L-entry)"
    assert rule["time_stop"].startswith("H20")
    assert rule["failure_stop"] == "NONE"
    assert contract["repository_2024_plus"] == (
        "SIGNAL_AND_SELECTION_SEALED; AUTHORIZED_OUTCOME_TAIL_ONLY"
    )
    assert any("no 2024+ signal" in item for item in contract["non_changes"])


def test_periods_separate_signal_end_from_outcome_tail() -> None:
    development = replay.PERIODS["DEVELOPMENT"]
    diagnostic = replay.PERIODS["POST_OBSERVATION_DIAGNOSTIC"]
    assert development[0] == pd.Timestamp("2021-12-31")
    assert development[1] > development[0]
    assert diagnostic[0] == pd.Timestamp("2023-12-31")
    assert diagnostic[1] > diagnostic[0]
    assert max(diagnostic[2]) == 2023


def test_fixed_signal_mask_is_fail_closed_on_missing_inventory() -> None:
    frame = pd.DataFrame(
        {
            "exact_minute_history": [True, True, False],
            "pre_gap_inside_density_relative_local": [1.0, np.nan, 0.1],
            "pre_gap_corridor_density_relative_local": [1.0, 0.1, 0.1],
            "pre_gap_return_20d": [0.0, -0.1, -0.1],
            "recovery_from_low20": [0.03, 0.10, 0.10],
        }
    )
    assert replay.fixed_signal_mask(frame).tolist() == [True, False, False]


def _target_path() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "bar_end_time": pd.to_datetime(
                ["2023-01-02 14:59", "2023-01-03 09:31", "2023-01-04 09:31"]
            ),
            "trade_date": pd.to_datetime(["2023-01-02", "2023-01-03", "2023-01-04"]),
            "cal_idx": [10, 11, 12],
            "invalid_step_cum": [7.0, 7.0, 7.0],
            "hard_valid": [True, True, True],
            "trade_status": [1, 1, 1],
            "current_day_data_tradable": [True, True, True],
            "market_rule_valid": [True, True, True],
            "corporate_action_blocking": [False, False, False],
            "open": [9.90, 9.95, 10.05],
            "high": [10.20, 10.10, 10.20],
            "coordinate_factor": [1.0, 1.0, 1.0],
        }
    )


def test_target_is_t1_and_first_post_entry_session() -> None:
    entry = SimpleNamespace(
        entry_time=pd.Timestamp("2023-01-02 09:31"),
        entry_cal_idx=10,
        entry_invalid_step_cum=7.0,
        gap_id="G1",
    )
    fill = replay.first_target(_target_path(), entry, 10.0)
    assert fill is not None
    assert fill["exit_date"] == pd.Timestamp("2023-01-03")
    assert fill["exit_raw_price"] == 10.0


def test_target_is_disabled_on_and_after_corporate_action_effective_date() -> None:
    entry = SimpleNamespace(
        entry_time=pd.Timestamp("2023-01-02 09:31"),
        entry_cal_idx=10,
        entry_invalid_step_cum=7.0,
        gap_id="G1",
    )
    assert (
        replay.first_target(
            _target_path(),
            entry,
            10.0,
            first_action_effective=pd.Timestamp("2023-01-03"),
        )
        is None
    )


def test_missing_corporate_action_state_fails_closed() -> None:
    entry = SimpleNamespace(
        entry_time=pd.Timestamp("2023-01-02 09:31"),
        entry_cal_idx=10,
        entry_invalid_step_cum=7.0,
        gap_id="G1",
    )
    path = _target_path()
    path["corporate_action_blocking"] = path.corporate_action_blocking.astype(object)
    path.loc[1, "corporate_action_blocking"] = np.nan
    fill = replay.first_target(path, entry, 10.0)
    assert fill is not None
    assert fill["exit_date"] == pd.Timestamp("2023-01-04")


def test_repair_source_has_no_terminal_completeness_filter() -> None:
    source_text = inspect.getsource(replay.build_buy_entries)
    assert "RIGHT_CENSORED" not in source_text
    assert "entry_cal_idx + TIME_STOP" not in source_text
    stage_a_text = inspect.getsource(replay.prepare_period_stage_a)
    assert "build_ma5_signal_candidates" in stage_a_text
    assert "signal_end" in stage_a_text
    assert "tail_end" in stage_a_text
