from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_ashare_ca_replay_003.py"
MODULE_SPEC = importlib.util.spec_from_file_location("ashare_ca_replay", SCRIPT)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
MODULE = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = MODULE
MODULE_SPEC.loader.exec_module(MODULE)


def _calendar() -> list[date]:
    start = date(2020, 1, 6)
    return [start + timedelta(days=index) for index in range(9)]


def _plans(calendar: list[date]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "family": "industry_diffusion_20",
                "signal_date": calendar[0],
                "symbol": "000001.SZ",
                "industry": "TEST",
                "entry_index": 1,
                "due_index": 5,
                "horizon": 20,
            }
        ]
    )


def _market(
    calendar: list[date],
    *,
    blocked_dates: set[date] | None = None,
    suspended_dates: set[date] | None = None,
) -> pd.DataFrame:
    blocked = blocked_dates or set()
    suspended = suspended_dates or set()
    return pd.DataFrame(
        [
            {
                "trade_date": day,
                "symbol": "000001.SZ",
                "open": 10.0,
                "close": 10.0,
                "amount": 100_000_000.0,
                "hard_valid": day not in suspended,
                "trade_status": 0 if day in suspended else 1,
                "current_day_data_tradable": day not in suspended,
                "buy_blocked_open": False,
                "sell_blocked_open": day in blocked,
                "corporate_action_count": 0,
                "corporate_action_valid": True,
                "corporate_action_blocking": False,
                "corporate_action_available_date": pd.NaT,
                "share_multiplier": 1.0,
                "cash_per_share": 0.0,
                "rights_ratio": 0.0,
                "available_at": pd.Timestamp(day) + pd.Timedelta(hours=15),
                "invalid_reasons": "invalid_daily_bar" if day in suspended else None,
                "corporate_action_problems": None,
                "corporate_action_ids": None,
                "corporate_action_snapshot_id": None,
            }
            for day in calendar[1:]
        ]
    )


def _event(calendar: list[date], effective_index: int = 4) -> object:
    return MODULE.RiskEvent(
        symbol="000001.SZ",
        event_id="event-1",
        event_kind="SHARE_DISTRIBUTION",
        known_date=calendar[1],
        decision_date=calendar[1],
        effective_date=calendar[effective_index],
    )


def test_contract_is_frozen_and_prior_blockers_have_pre_effective_decisions() -> None:
    spec = MODULE._load_spec()
    _, calendar, _ = MODULE._load_market_inputs(spec)
    events, _ = MODULE._load_risk_events(spec, calendar)
    by_id = {item.event_id: item for item in events}
    expected = {
        "cninfo:distribution:b0fce666c5eaf676819fce517fb8684b": date(2019, 4, 23),
        "cninfo:rights:b233a60edc861cd67637ee391b4499c1": date(2019, 2, 28),
        "cninfo:distribution:d0eee38e477dd3beb15f52cef370a094": date(2019, 6, 3),
        "cninfo:distribution:0e3773103683385e9f8bc0814ca35ed0": date(2019, 5, 6),
    }
    for event_id, effective in expected.items():
        event = by_id[event_id]
        assert event.decision_date is not None
        assert event.known_date <= event.decision_date < effective


def test_pre_effective_exit_obeys_t_plus_one_and_pending_sell_block() -> None:
    calendar = _calendar()
    args = (
        "industry_diffusion_20",
        _plans(calendar),
        _market(calendar, blocked_dates={calendar[2]}),
        calendar,
        [_event(calendar)],
    )
    first = MODULE._replay(*args)
    second = MODULE._replay(*args)
    assert first[0] == second[0]
    pd.testing.assert_frame_equal(first[1], second[1])
    pd.testing.assert_frame_equal(first[2], second[2])
    result, _, exits = first
    assert result["forced_pre_effective_exits"] == 1
    assert result["forced_exit_pending_days"] == 1
    assert exits.iloc[0].fill_date == calendar[3]
    assert exits.iloc[0].fill_date < exits.iloc[0].effective_date


def test_known_event_blocks_new_risk_without_using_effective_result() -> None:
    calendar = _calendar()
    events = [_event(calendar)]
    assert MODULE._entry_blocked("000001.SZ", calendar[1], calendar[2], {"000001.SZ": events})
    assert not MODULE._entry_blocked(
        "000001.SZ", calendar[0], calendar[1], {"000001.SZ": events}
    )


def test_no_legal_pre_effective_fill_fails_closed() -> None:
    calendar = _calendar()
    with pytest.raises(MODULE.CorporateActionReplayError, match="pre-effective exit failed"):
        MODULE._replay(
            "industry_diffusion_20",
            _plans(calendar),
            _market(calendar, blocked_dates={calendar[2]}),
            calendar,
            [_event(calendar, effective_index=3)],
        )


def test_known_suspension_carries_value_and_forbids_fill() -> None:
    calendar = _calendar()
    result, _, exits = MODULE._replay(
        "industry_diffusion_20",
        _plans(calendar),
        _market(calendar, suspended_dates={calendar[2]}),
        calendar,
        [_event(calendar)],
    )
    assert result["forced_exit_pending_days"] == 1
    assert exits.iloc[0].fill_date == calendar[3]


def test_full_replays_are_complete_and_all_risk_exits_pre_effective() -> None:
    result_path = (
        ROOT / "research/market_behavior_os_v2/artifacts/ASHARE-CA-REPLAY-003_result.json"
    )
    exits_path = (
        ROOT / "research/market_behavior_os_v2/artifacts/ASHARE-CA-REPLAY-003_risk_exits.csv"
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert [row["classification"] for row in result["replays"]] == [
        "PROMISING_BUT_MIXED",
        "PROMISING_BUT_MIXED",
    ]
    assert all(row["terminal_open_lots"] == 0 for row in result["replays"])
    exits = pd.read_csv(exits_path, parse_dates=["fill_date", "effective_date"])
    assert len(exits) == 26
    assert (exits.fill_date < exits.effective_date).all()
