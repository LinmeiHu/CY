from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT / "research/market_behavior_os_v2/scripts/run_ashare_price_limit_liquidity_cycle_014.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location("cycle014_test", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
cycle = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = cycle
MODULE_SPEC.loader.exec_module(cycle)


def _bars() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    minutes = cycle.ADAPTER.EXPECTED_MINUTES.copy()
    high = np.full(241, 10.8)
    close = np.full(241, 10.7)
    volume = np.full(241, 100.0)
    return minutes, high, close, volume


def test_early_stable_acceptance_uses_completed_minutes() -> None:
    minutes, high, close, volume = _bars()
    start = int(np.flatnonzero(minutes == 10 * 60)[0])
    high[start:] = 11.0
    close[start:] = 11.0
    result = cycle.classify_lifecycle(minutes, high, close, volume, 10.0, 11.0)
    assert result["lifecycle"] == "EARLY_STABLE_ACCEPTANCE"
    assert result["proxy_1400"] is True


def test_reopen_then_reseal_is_separate_from_stable() -> None:
    minutes, high, close, volume = _bars()
    start = int(np.flatnonzero(minutes == 10 * 60)[0])
    reopen = int(np.flatnonzero(minutes == 13 * 60 + 30)[0])
    high[start:] = 11.0
    close[start:] = 11.0
    close[reopen : reopen + 2] = 10.95
    result = cycle.classify_lifecycle(minutes, high, close, volume, 10.0, 11.0)
    assert result["lifecycle"] == "REOPEN_SUCCESSFUL_RESEAL"
    assert result["reopen_episodes"] == 1


def test_touch_without_accepted_close_is_failed_acceptance() -> None:
    minutes, high, close, volume = _bars()
    high[50] = 11.0
    result = cycle.classify_lifecycle(minutes, high, close, volume, 10.0, 11.0)
    assert result["lifecycle"] == "FAILED_ACCEPTANCE"
    assert result["first_accept_minute"] is None


def test_nearest_match_never_uses_future_outcomes() -> None:
    events = pd.DataFrame(
        [
            {
                "uid": "e",
                "trade_date": "2020-01-02",
                "industry": "I",
                "symbol": "E",
                "block": "early",
                "x": 0.0,
            }
        ]
    )
    controls = pd.DataFrame(
        [
            {
                "uid": "c1",
                "trade_date": "2020-01-02",
                "industry": "I",
                "symbol": "A",
                "block": "early",
                "x": 0.1,
            },
            {
                "uid": "c2",
                "trade_date": "2020-01-02",
                "industry": "I",
                "symbol": "B",
                "block": "early",
                "x": 2.0,
            },
        ]
    )
    pairs = cycle.nearest_pairs(events, controls, ["x"], np.array([1.0]), ["trade_date"], "T")
    assert pairs.iloc[0].control_uid == "c1"
