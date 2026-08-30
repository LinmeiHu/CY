from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

WORK = Path(__file__).resolve().parents[1]


def test_exp_wla_001_result_is_complete_and_rejected() -> None:
    result = json.loads(
        (WORK / "artifacts/winner_loser_trajectory_archaeology.json").read_text()
    )
    assert result["experiment_id"] == "EXP-WLA-001"
    assert result["decision"] == "REJECT"
    assert result["passing_components"] == []
    assert result["audit"]["complete_trade_anchor_pairs"] == 399
    assert result["audit"]["trajectory_rows"] == 2793
    assert result["audit"]["post_entry_price_rows_read"] == 0
    assert result["strategy_modification"] == "NONE"
    assert all(not item["passes"] for item in result["primary"].values())


def test_exp_wla_001_outputs_preserve_fixed_sample_and_anchors() -> None:
    trajectories = pd.read_csv(WORK / "artifacts/pre_entry_trajectories.csv")
    transitions = pd.read_csv(WORK / "artifacts/pre_entry_transitions.csv")
    assert len(trajectories) == 2793
    assert len(transitions) == 399
    assert trajectories.trade_id.nunique() == 399
    assert sorted(trajectories.sessions_before_entry.unique()) == [1, 3, 5, 10, 20, 40, 60]
    assert not trajectories.duplicated(["trade_id", "sessions_before_entry"]).any()
