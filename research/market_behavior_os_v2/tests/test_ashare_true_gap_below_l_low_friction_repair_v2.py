from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_low_friction_repair_v2 as runner,
)


def test_contract_replaces_formation_gate_with_one_low_friction_gate() -> None:
    contract = runner.contract_value()
    assert "formation_gate" not in contract
    assert contract["inventory_gate"]["missing_policy"] == "FAIL_CLOSED"
    assert contract["low_friction_gate"]["missing_policy"] == "FAIL_CLOSED"
    assert "all prior Stage-A clean candidate signals" in contract[
        "low_friction_gate"
    ]["development_rule"]
    assert contract["exit"]["profit_target"] == "entry + 0.67*(L-entry)"
    assert contract["portfolio"]["K_per_board"] == 20
    assert "secondary forward replication" in contract[
        "validation_status_disclosure"
    ]


def test_clean_inventory_gate_fails_closed_on_missing() -> None:
    frame = pd.DataFrame(
        {
            "exact_minute_history": [True, True, False, True],
            "pre_gap_inside_density_relative_local": [0.9, None, 0.8, 1.1],
            "pre_gap_corridor_density_relative_local": [1.0, 0.7, 0.8, 0.7],
        }
    )
    assert runner.clean_inventory_mask(frame).tolist() == [
        True,
        False,
        False,
        False,
    ]


def test_low_friction_feature_uses_gap_plus_one_through_signal_only() -> None:
    dates = pd.date_range("2020-01-02", periods=4, freq="B")
    daily = pd.DataFrame(
        {
            "symbol": ["000001.SZ"] * 4,
            "trade_date": dates,
            "cal_idx": [1, 2, 3, 4],
            "turnover_fraction": [99.0, 0.20, 0.30, 0.40],
            "invalid_step_cum": [0.0] * 4,
            "hard_valid": [True] * 4,
            "history_valid": [True] * 4,
            "current_valid": [True] * 4,
            "corporate_action_valid": [True] * 4,
            "corporate_action_blocking": [False] * 4,
        }
    )
    signal_time = dates[-1] + pd.Timedelta(hours=15)
    signals = pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "gap_id": "000001.SZ|2020-01-02",
                "gap_date": dates[0],
                "signal_date": dates[-1],
                "signal_time": signal_time,
                "signal_cal_idx": 4,
                "invalid_step_cum": 0.0,
                "recovery_from_low20": 0.18,
            }
        ]
    )
    result = runner.attach_low_friction_features(signals, daily)
    assert len(result) == 1
    assert result.iloc[0].post_gap_turnover == pytest.approx(0.90)
    assert result.iloc[0].recovery_per_turnover == pytest.approx(0.20)
    assert result.iloc[0].feature_latest_timestamp == signal_time
    assert not bool(result.iloc[0].feature_uses_post_signal_information)


def test_low_friction_feature_fails_closed_on_invalid_lineage() -> None:
    dates = pd.date_range("2020-01-02", periods=3, freq="B")
    daily = pd.DataFrame(
        {
            "symbol": ["000001.SZ"] * 3,
            "trade_date": dates,
            "cal_idx": [1, 2, 3],
            "turnover_fraction": [0.1, 0.2, 0.3],
            "invalid_step_cum": [0.0, 1.0, 0.0],
            "hard_valid": [True] * 3,
            "history_valid": [True] * 3,
            "current_valid": [True] * 3,
            "corporate_action_valid": [True] * 3,
            "corporate_action_blocking": [False] * 3,
        }
    )
    event = SimpleNamespace(
        symbol="000001.SZ",
        gap_id="000001.SZ|2020-01-02",
        gap_date=dates[0],
        signal_date=dates[-1],
        signal_time=dates[-1] + pd.Timedelta(hours=15),
        signal_cal_idx=3,
        invalid_step_cum=0.0,
        recovery_from_low20=0.12,
    )
    with pytest.raises(RuntimeError, match="feature construction failure"):
        runner.attach_low_friction_features(pd.DataFrame([event.__dict__]), daily)


def test_2024_daily_access_is_rejected_before_io() -> None:
    with pytest.raises(RuntimeError, match="2024"):
        runner.v1.load_daily(pd.Timestamp("2024-01-01"))


def test_development_checkpoint_meets_frozen_design_targets() -> None:
    payload = json.loads(runner.DEVELOPMENT_RESULT.read_text(encoding="utf-8"))
    combined = payload["portfolio"]["COMBINED"]
    assert 70 <= payload["selected_stage_a_signals"] / 5 <= 100
    assert 40 <= combined["trades"] / 5 <= 50
    assert combined["mean_net"] >= 0.03
    assert combined["median_net"] > 0
    assert all(value > 0 for value in combined["annual_returns"].values())
    assert payload["audit"]["feature_uses_post_signal_information_count"] == 0
    assert payload["audit"]["threshold_uses_outcome_eligible_only_count"] == 0
    assert payload["audit"]["entry_at_or_before_signal_count"] == 0
    assert payload["audit"]["t1_violation_count"] == 0
    assert payload["audit"]["repository_2024_plus_data_opened"] == "NO"


def test_secondary_replication_preserves_freeze_and_records_failure() -> None:
    freeze = json.loads(runner.VALIDATION_FREEZE.read_text(encoding="utf-8"))
    result = json.loads(runner.VALIDATION_RESULT.read_text(encoding="utf-8"))
    assert result["fixed_threshold"] == freeze[
        "fixed_recovery_per_turnover_threshold"
    ]
    assert result["label"] == "SECONDARY_FORWARD_REPLICATION_2022_2023"
    assert result["verdict"] == "LOW_FRICTION_REPAIR_SECONDARY_REPLICATION_FAILED"
    assert result["validation_checks"]["mean_net"]
    assert not result["validation_checks"]["both_years_positive"]
    assert not result["validation_checks"]["both_boards_positive"]
    assert result["audit"]["validation_rule_changed_count"] == 0
    assert result["audit"]["repository_2024_plus_data_opened"] == "NO"
