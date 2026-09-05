from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pandas as pd
import pytest


RUNNER = (
    Path(__file__).resolve().parents[1]
    / "scripts/run_ashare_morning_demand_overnight_supply_acceptance_v6.py"
)
SPEC = importlib.util.spec_from_file_location("morning_demand_v6", RUNNER)
assert SPEC is not None and SPEC.loader is not None
V6 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = V6
SPEC.loader.exec_module(V6)


def _event() -> dict[str, object]:
    return {
        "event_id_v6": "TEST",
        "symbol": "600000.SH",
        "d0_cutoff_close": 10.0,
        "d1_entry_open1001": 10.0,
        "d1_entry_at": pd.Timestamp("2020-01-02 10:01:00"),
    }


def _state(session: int, down: float = 9.0) -> dict[str, object]:
    return {
        "event_id_v6": "TEST",
        "symbol": "600000.SH",
        "holding_session": session,
        "outcome_date": pd.Timestamp("2020-01-03") + pd.offsets.BDay(session - 2),
        "trade_status": 1,
        "is_st": False,
        "down_limit_price": down,
        "up_limit_price": 11.0,
        "corporate_action_count": 0,
        "corporate_action_blocking": False,
        "corporate_action_available_date": pd.NaT,
        "bar_valid": True,
        "trading_state_valid": True,
        "corporate_action_valid": True,
        "market_rule_valid": True,
        "hard_valid": True,
        "snapshot_id": "S",
    }


def _bar(session: int, clock: str, open_: float, high: float, close: float) -> dict[str, object]:
    date = pd.Timestamp("2020-01-03") + pd.offsets.BDay(session - 2)
    return {
        "event_id_v6": "TEST",
        "symbol": "600000.SH",
        "holding_session": session,
        "outcome_date": date,
        "bar_end_time": pd.Timestamp(f"{date.date()} {clock}"),
        "open": open_,
        "high": high,
        "low": min(open_, close),
        "close": close,
        "volume": 100.0,
    }


def test_target_on_first_sellable_day_precedes_failure() -> None:
    bars = pd.DataFrame(
        [
            _bar(2, "09:31:00", 10.1, 10.2, 10.1),
            _bar(2, "09:32:00", 10.2, 10.8, 10.7),
            _bar(2, "10:00:00", 9.8, 9.9, 9.8),
        ]
    )
    result = V6._simulate_event(_event(), bars, pd.DataFrame([_state(2)]))
    assert result["status"] == "COMPLETE"
    assert result["exit_reason"] == "TARGET_08"
    assert result["holding_sessions"] == 1
    assert result["net_return"] == pytest.approx(0.076)


def test_d2_completed_failure_exits_at_next_minute_open() -> None:
    bars = pd.DataFrame(
        [
            _bar(2, "10:00:00", 9.9, 10.0, 9.8),
            _bar(2, "10:01:00", 9.7, 9.8, 9.75),
        ]
    )
    result = V6._simulate_event(_event(), bars, pd.DataFrame([_state(2)]))
    assert result["exit_reason"] == "D2_ACCEPTANCE_FAILURE"
    assert result["exit_at"] == pd.Timestamp("2020-01-03 10:01:00")
    assert result["net_return"] == pytest.approx(-0.034)


def test_locked_down_failure_waits_for_first_legal_open() -> None:
    bars = pd.DataFrame(
        [
            _bar(2, "10:00:00", 9.0, 9.0, 9.0),
            _bar(2, "10:01:00", 9.0, 9.0, 9.0),
            _bar(2, "10:02:00", 9.1, 9.2, 9.1),
        ]
    )
    result = V6._simulate_event(_event(), bars, pd.DataFrame([_state(2)]))
    assert result["exit_reason"] == "D2_ACCEPTANCE_FAILURE"
    assert result["exit_at"] == pd.Timestamp("2020-01-03 10:02:00")
    assert result["exit_price"] == pytest.approx(9.1)


def test_h3_time_stop_uses_first_legal_d4_open() -> None:
    bars = pd.DataFrame(
        [
            _bar(2, "10:00:00", 10.1, 10.2, 10.1),
            _bar(3, "10:00:00", 10.2, 10.3, 10.2),
            _bar(4, "09:31:00", 10.4, 10.5, 10.4),
        ]
    )
    states = pd.DataFrame([_state(2), _state(3), _state(4)])
    result = V6._simulate_event(_event(), bars, states)
    assert result["exit_reason"] == "H3_TIME_STOP"
    assert result["holding_sessions"] == 3
    assert result["net_return"] == pytest.approx(0.036)


def test_corporate_action_fails_closed_before_return() -> None:
    state = _state(2)
    state["corporate_action_count"] = 1
    bars = pd.DataFrame([_bar(2, "09:31:00", 10.8, 10.9, 10.8)])
    result = V6._simulate_event(_event(), bars, pd.DataFrame([state]))
    assert result["status"] == "ACTION_LINEAGE_FAIL_CLOSED"
    assert pd.isna(result["net_return"])


def test_spec_is_exactly_frozen() -> None:
    spec = V6.load_spec()
    assert spec["execution"]["profit_target"] == 0.08
    assert spec["simple_rule"]["condition_count"] == 3
