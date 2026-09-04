from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import run_ashare_bear_fast_capitulation_causal_failure_exit_v14 as subject  # noqa: E402


def test_signal_low_failure_uses_completed_close() -> None:
    assert (
        subject.failure_reason(
            "F1_SIGNAL_LOW_BREAK",
            coord_close=8.9,
            signal_coord_low=9.0,
            entry_price=10.0,
            breadth20=0.3,
            breadth20_lag5=0.2,
        )
        == "FAIL_SIGNAL_LOW_BREAK"
    )
    assert (
        subject.failure_reason(
            "F1_SIGNAL_LOW_BREAK",
            coord_close=9.0,
            signal_coord_low=9.0,
            entry_price=10.0,
            breadth20=0.3,
            breadth20_lag5=0.2,
        )
        is None
    )


def test_breadth_failure_requires_repair_loss_and_underwater_stock() -> None:
    profile = "F2_BREADTH_REPAIR_LOST_UNDERWATER"
    assert (
        subject.failure_reason(
            profile,
            coord_close=9.9,
            signal_coord_low=9.0,
            entry_price=10.0,
            breadth20=0.20,
            breadth20_lag5=0.25,
        )
        == "FAIL_BREADTH_REPAIR_LOST_UNDERWATER"
    )
    assert (
        subject.failure_reason(
            profile,
            coord_close=10.1,
            signal_coord_low=9.0,
            entry_price=10.0,
            breadth20=0.20,
            breadth20_lag5=0.25,
        )
        is None
    )
    assert (
        subject.failure_reason(
            profile,
            coord_close=9.9,
            signal_coord_low=9.0,
            entry_price=10.0,
            breadth20=0.30,
            breadth20_lag5=0.25,
        )
        is None
    )
