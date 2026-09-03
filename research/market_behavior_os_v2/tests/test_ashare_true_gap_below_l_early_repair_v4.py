from __future__ import annotations

import json

import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_early_repair_v4 as runner,
)


def test_contract_uses_early_repair_and_below_l_target() -> None:
    contract = runner.contract_value()
    assert contract["source_population"]["true_gap"] == "High_t < Low_t_minus_1"
    assert contract["formation_gate"] == "20-session pre-gap coordinate return <= 0"
    assert contract["reversal_gate"]["minimum_recovery_from_20_session_low"] == 0.03
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
            "recovery_from_low20": [0.03, 0.03, 0.03, 0.03, 0.03, 0.029],
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


def test_target_fraction_retains_strict_gap_buffer() -> None:
    entry = 8.0
    lower_gap_boundary = 10.0
    target = entry + runner.TARGET_FRACTION * (lower_gap_boundary - entry)
    assert target == pytest.approx(9.6)
    assert target < lower_gap_boundary


def test_2024_daily_access_is_rejected_before_io() -> None:
    with pytest.raises(RuntimeError, match="2024"):
        runner.v1.load_daily(pd.Timestamp("2024-01-01"))


def test_development_checkpoint_meets_preregistered_targets() -> None:
    payload = json.loads(runner.DEVELOPMENT_RESULT.read_text(encoding="utf-8"))
    combined = payload["portfolio"]["COMBINED"]
    assert 50 <= combined["trades"] / 5 <= 80
    assert combined["mean_net"] >= 0.03
    assert combined["median_net"] > 0
    assert all(value > 0 for value in combined["annual_returns"].values())
    assert payload["audit"]["feature_uses_post_signal_information_count"] == 0
    assert payload["audit"]["entry_at_or_before_signal_count"] == 0
    assert payload["audit"]["target_at_or_above_L_count"] == 0
    assert payload["audit"]["t1_violation_count"] == 0
    assert payload["audit"]["repository_2024_plus_data_opened"] == "NO"
