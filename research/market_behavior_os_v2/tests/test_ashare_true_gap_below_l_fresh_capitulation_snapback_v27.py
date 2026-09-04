from __future__ import annotations

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_fresh_capitulation_snapback_v27 as subject,
)


def _frame(**overrides: float) -> pd.DataFrame:
    row = {
        "gap_age": 14.0,
        "max_depth": 0.16,
        "current_depth": 0.11,
        "pre_peak_to_gap_sessions": 20.0,
    }
    row.update(overrides)
    return pd.DataFrame([row])


def test_frozen_three_condition_boundary_passes() -> None:
    frame = _frame()
    assert subject.fresh_snapback_mask(frame).iloc[0]
    assert abs(subject.rebound_from_post_gap_low_over_l(frame).iloc[0] - 0.05) < 1e-12


def test_each_condition_fails_closed_outside_boundary() -> None:
    assert not subject.fresh_snapback_mask(_frame(gap_age=15)).iloc[0]
    assert not subject.fresh_snapback_mask(
        _frame(max_depth=0.159, current_depth=0.11)
    ).iloc[0]
    assert not subject.fresh_snapback_mask(
        _frame(pre_peak_to_gap_sessions=19)
    ).iloc[0]


def test_missing_required_feature_fails_closed() -> None:
    assert not subject.fresh_snapback_mask(_frame(max_depth=float("nan"))).iloc[0]


def test_contract_preserves_v13_trade_semantics() -> None:
    contract = subject.contract_value()
    unchanged = contract["unchanged_v13"]
    assert unchanged["target"] == "A67 below L"
    assert unchanged["time_stop"] == "H20"
    assert unchanged["round_trip_cost"] == 0.004
    assert unchanged["portfolio"] == "Main/ChiNext 50/50; K80 per sleeve"
