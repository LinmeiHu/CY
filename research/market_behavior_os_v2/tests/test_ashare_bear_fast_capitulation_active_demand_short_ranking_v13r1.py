from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import run_ashare_bear_fast_capitulation_active_demand_short_ranking_v13r1 as subject  # noqa: E402


def test_open_time_stop_is_released_before_same_open_entry() -> None:
    active = {
        "600000.SH": SimpleNamespace(
            exit_date=pd.Timestamp("2020-01-10"), exit_reason="H20_TIME_STOP"
        )
    }
    released = subject.release_before_open(active, pd.Timestamp("2020-01-10"))
    assert released == ["600000.SH"]
    assert active == {}


def test_intraday_target_is_not_released_before_same_open_entry() -> None:
    active = {
        "600000.SH": SimpleNamespace(
            exit_date=pd.Timestamp("2020-01-10"), exit_reason="TARGET_10"
        )
    }
    released = subject.release_before_open(active, pd.Timestamp("2020-01-10"))
    assert released == []
    assert "600000.SH" in active


def test_overlap_audit_respects_open_exit_event_order() -> None:
    legal = pd.DataFrame(
        [
            {
                "event_id": "old",
                "symbol": "600000.SH",
                "entry_date": pd.Timestamp("2020-01-01"),
                "exit_date": pd.Timestamp("2020-01-10"),
                "exit_reason": "H20_TIME_STOP",
            },
            {
                "event_id": "new",
                "symbol": "600000.SH",
                "entry_date": pd.Timestamp("2020-01-10"),
                "exit_date": pd.Timestamp("2020-01-20"),
                "exit_reason": "H20_TIME_STOP",
            },
        ]
    )
    illegal = legal.copy()
    illegal.loc[0, "exit_reason"] = "TARGET_10"
    assert subject.true_overlap_count(legal) == 0
    assert subject.true_overlap_count(illegal) == 1
