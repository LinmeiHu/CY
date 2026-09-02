from __future__ import annotations

import json

import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts.run_ashare_market_panic_repair_transition_v1 import (
    GRID,
    NAV,
    RESULT,
    SEARCH,
    SPEC,
    STATES,
    Params,
    score_fold,
    simulate,
)


def calibration() -> dict:
    return {
        "panic_q75": 0.5,
        "panic_q90": 0.8,
        "repair": {"0|0945": {"q67": 0.5, "q80": 0.8}},
    }


def synthetic_states(calendar: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_date": calendar,
            "checkpoint": "0945",
            "open_panic_score": 0.9,
            "repair_score": [0.9, 0.1, 0.9, 0.9],
            "same_close_gross": 0.0,
            "t1_open_gross": 0.0,
            "t1_close_gross": 0.0,
            "same_close_exit_date": calendar,
            "t1_open_exit_date": calendar + pd.offsets.BDay(1),
            "t1_close_exit_date": calendar + pd.offsets.BDay(1),
            "entry_day_close_gross": 0.0,
        }
    )


def test_frozen_grid_is_exactly_36_unique_configs() -> None:
    assert len(GRID) == 36
    assert len({item.key for item in GRID}) == 36


def test_portfolio_cost_overlap_and_year_boundary_are_fail_closed() -> None:
    calendar = pd.bdate_range("2020-01-06", periods=4)
    states = synthetic_states(calendar)
    params = Params(0, "0945", 0, 2)
    nav, trades, _ = simulate(states, calendar, params, calibration(), calendar[0], calendar[-1])
    expected_net = (1 - 0.002) / (1 + 0.002) - 1
    assert len(trades) == 2
    assert np.allclose(trades.net_return, expected_net)
    assert nav.positions.max() == 1
    assert nav.cash.min() >= 0
    assert trades.signal_date.max() == calendar[2]


def test_panic_only_removes_only_repair_confirmation() -> None:
    calendar = pd.bdate_range("2020-01-06", periods=4)
    states = synthetic_states(calendar)
    params = Params(0, "0945", 0, 0)
    _, full, _ = simulate(
        states, calendar, params, calibration(), calendar[0], calendar[-1], mode="FULL"
    )
    _, panic, _ = simulate(
        states, calendar, params, calibration(), calendar[0], calendar[-1], mode="PANIC_ONLY"
    )
    assert len(full) == 3
    assert len(panic) == 4
    assert set(full.signal_date) == set(calendar[[0, 2, 3]])


def test_train_calibration_is_unchanged_by_future_rows() -> None:
    if not STATES.is_file():
        return
    states = pd.read_parquet(STATES)
    states["trade_date"] = pd.to_datetime(states.trade_date)
    base, base_calibration = score_fold(states, "MAIN", 2016)
    changed = states.copy()
    future = changed.trade_date.dt.year.ge(2017) & changed.sleeve.eq("MAIN")
    changed.loc[future, "down_gap_breadth_5"] = 1.0
    changed.loc[future, "median_price_repair"] = 100.0
    rescored, changed_calibration = score_fold(changed, "MAIN", 2016)
    train = base.trade_date.dt.year.le(2016)
    assert base_calibration == changed_calibration
    assert np.allclose(base.loc[train, "open_panic_score"], rescored.loc[train, "open_panic_score"])
    assert np.allclose(base.loc[train, "repair_score"], rescored.loc[train, "repair_score"])


def test_completed_artifacts_are_sealed_and_complete() -> None:
    if not RESULT.is_file():
        return
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    assert SPEC.is_file() and STATES.is_file() and SEARCH.is_file() and NAV.is_file()
    assert result["audit"]["search_rows"] == 360
    assert result["audit"]["opening_state_checkpoint_mismatch_count"] == 0
    for key in (
        "open_panic_uses_post_open_data_count",
        "repair_score_uses_post_checkpoint_data_count",
        "test_year_used_in_own_parameter_selection_count",
        "test_year_used_to_calibrate_own_panic_count",
        "test_year_used_to_calibrate_own_repair_threshold_count",
        "cross_board_state_contamination_count",
        "pit_industry_identity_failure_count",
        "post_2021_outcome_read_count",
        "duplicate_board_position_count",
        "negative_cash_or_leverage_count",
    ):
        assert result["audit"][key] == 0
    assert result["audit"]["validation_opened"] is False
    assert result["audit"]["final_oos_opened"] is False
    assert result["verdict"] in {
        "PANIC_REPAIR_TRANSITION_EDGE_READY_FOR_VALIDATION",
        "BOARD_SPECIFIC_PANIC_REPAIR_EDGE",
        "PANIC_REPAIR_EDGE_BUT_EPISODE_CONCENTRATED",
        "MARGINAL_PANIC_REPAIR_EDGE",
        "NO_PANIC_REPAIR_TRANSITION_EDGE",
        "IMPLEMENTATION_BLOCKED",
    }
