from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

RUNNER = Path(__file__).resolve().parents[1] / "scripts/run_mkt_breakout_data_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_breakout_data_001_tested", RUNNER)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
module = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(module)


def test_strict_equality_is_not_a_crossing() -> None:
    highs = np.full(241, 10.0)
    closes = np.full(241, 10.0)
    result = module.event_summary(highs, closes, 10.0, include_auction=False)
    assert result == {
        "cross": False,
        "first_cross_index": None,
        "remaining_bars": None,
        "closing_state": "NO_CROSS",
        "close_loss": False,
        "reacquired": False,
    }


def test_continuous_clock_excludes_auction_and_counts_censoring() -> None:
    highs = np.full(241, 9.0)
    closes = np.full(241, 9.0)
    highs[0] = 11.0
    highs[240] = 11.0
    closes[240] = 10.5
    continuous = module.event_summary(highs, closes, 10.0, include_auction=False)
    auction = module.event_summary(highs, closes, 10.0, include_auction=True)
    assert continuous["first_cross_index"] == 239
    assert continuous["remaining_bars"] == 0
    assert auction["first_cross_index"] == 0
    assert auction["remaining_bars"] == 240


def test_reacquisition_requires_a_later_strict_close_above() -> None:
    highs = np.full(241, 9.0)
    closes = np.full(241, 9.0)
    highs[1] = 10.5
    closes[1] = 10.2
    closes[2] = 9.8
    closes[3] = 10.0
    closes[4] = 10.1
    closes[-1] = 10.2
    result = module.event_summary(highs, closes, 10.0, include_auction=False)
    assert result["cross"] is True
    assert result["first_cross_index"] == 0
    assert result["close_loss"] is True
    assert result["reacquired"] is True
    assert result["closing_state"] == "CROSS_CLOSE_ABOVE"
