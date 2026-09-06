from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / (
    "scripts/run_ashare_long_suspension_reopening_price_discovery_rules_v1.py"
)
SPEC = importlib.util.spec_from_file_location("reopening_rules_v1", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def row(cal_idx: int, *, open_: float = 100.0, close: float = 100.0) -> dict:
    return {
        "trade_date": pd.Timestamp("2020-01-01") + pd.Timedelta(days=cal_idx),
        "cal_idx": cal_idx,
        "open": open_,
        "close": close,
        "coord_open": open_,
        "coord_close": close,
        "invalid_step_cum": 0.0,
        "coordinate_factor": 1.0,
        "trade_status": 1,
        "current_day_data_tradable": True,
        "current_valid": True,
        "market_rule_valid": True,
        "corporate_action_count": 0,
        "corporate_action_valid": True,
        "corporate_action_blocking": False,
        "hard_valid": True,
        "up_limit_price": open_ + 10.0,
        "down_limit_price": open_ - 10.0,
    }


def test_anchor_skips_limit_up_and_counts_anchor_as_observation_one() -> None:
    rows = [row(101, open_=110.0, close=110.0)]
    rows[0]["up_limit_price"] = 110.0
    rows.extend(row(idx, open_=100.0 + idx - 102, close=101.0 + idx - 102) for idx in range(102, 107))
    candidate = SimpleNamespace(signal_cal_idx=100, invalid_step_cum=0.0)

    result = MODULE.locate_anchor_and_observation(candidate, pd.DataFrame(rows))

    assert result["pre_status"] == "OBSERVATION_COMPLETE"
    assert result["anchor_cal_idx"] == 102
    assert result["observation_cal_idx"] == 106
    assert result["anchor_price"] == 100.0
    assert result["observation_close"] == 105.0


def test_no_anchor_after_frozen_three_session_window() -> None:
    rows = [row(idx, open_=110.0, close=110.0) for idx in range(101, 105)]
    for item in rows[:3]:
        item["up_limit_price"] = 110.0
    candidate = SimpleNamespace(signal_cal_idx=100, invalid_step_cum=0.0)

    result = MODULE.locate_anchor_and_observation(candidate, pd.DataFrame(rows))

    assert result == {"pre_status": "NO_LEGAL_ANCHOR"}


def test_phase_is_strictly_direction_by_speed() -> None:
    assert MODULE.phase(0.10, 0.12) == "UP_ACCELERATING"
    assert MODULE.phase(0.01, 0.12) == "UP_DECELERATING"
    assert MODULE.phase(-0.01, -0.18) == "DOWN_RECOVERING"
    assert MODULE.phase(-0.10, -0.18) == "DOWN_DETERIORATING"


def test_two_consecutive_anchor_failures_exit_next_legal_open() -> None:
    rows = [row(201, open_=105.0, close=104.0)]
    rows.extend(
        [
            row(202, open_=103.0, close=99.0),
            row(203, open_=99.0, close=101.0),
            row(204, open_=101.0, close=98.0),
            row(205, open_=98.0, close=97.0),
            row(206, open_=96.0, close=96.0),
        ]
    )
    candidate = SimpleNamespace(invalid_step_cum=0.0)
    feature = SimpleNamespace(observation_cal_idx=200, anchor_price=100.0)

    result = MODULE.replay_accepted(candidate, feature, pd.DataFrame(rows))

    assert result["status"] == "COMPLETED"
    assert result["entry_cal_idx"] == 201
    assert result["exit_cal_idx"] == 206
    assert result["exit_reason"] == "TWO_CLOSES_BELOW_ANCHOR"


def test_h20_exit_when_anchor_failure_never_confirms() -> None:
    rows = [row(idx, open_=100.0, close=101.0) for idx in range(201, 223)]
    candidate = SimpleNamespace(invalid_step_cum=0.0)
    feature = SimpleNamespace(observation_cal_idx=200, anchor_price=100.0)

    result = MODULE.replay_accepted(candidate, feature, pd.DataFrame(rows))

    assert result["status"] == "COMPLETED"
    assert result["entry_cal_idx"] == 201
    assert result["exit_cal_idx"] == 221
    assert result["exit_reason"] == "H20_NEXT_LEGAL_OPEN"
