from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_trnd_001.py"
SPEC = ROOT / "research/market_behavior_os_v2/experiments/MKT-TRND-001_spec.json"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_trnd_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
trend = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(trend)


def test_percentiles_are_prefix_invariant() -> None:
    prefix = pd.Series(np.sin(np.arange(900) / 17.0) + np.arange(900) / 1000.0)
    extended = pd.concat([prefix, pd.Series([1000.0, -1000.0, 42.0])], ignore_index=True)
    for function in (trend.causal_expanding_percentile, trend.causal_rolling_percentile):
        left = function(prefix, min_history=20)
        right = function(extended, min_history=20).iloc[: len(prefix)]
        pd.testing.assert_series_equal(left.reset_index(drop=True), right.reset_index(drop=True))


def test_same_side_age_resets_on_side_change_and_unknown() -> None:
    close = pd.Series([np.nan, 2.0, 3.0, 0.5, 0.4, 2.0])
    moving_average = pd.Series([np.nan, 1.0, 1.0, 1.0, 1.0, 1.0])
    actual = trend.same_side_age(close, moving_average)
    expected = pd.Series([np.nan, 1.0, 2.0, 1.0, 2.0, 1.0])
    pd.testing.assert_series_equal(actual, expected)


def test_raw_features_do_not_change_when_future_is_appended() -> None:
    dates = pd.bdate_range("2018-01-01", periods=260)
    close = pd.Series(100.0 * np.exp(np.arange(260) * 0.001 + np.sin(np.arange(260) / 13.0) * 0.01))
    base = pd.DataFrame(
        {
            "trade_date": dates,
            "close": close,
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "volume": 1.0,
            "amount": 1.0,
            "index_symbol": "TEST",
            "index_name": "TEST",
        }
    )
    prefix = trend.build_raw_features(base.iloc[:220])
    extended = trend.build_raw_features(base)
    columns = [definition[0] for definition in trend.ROLE_MAP.values()]
    pd.testing.assert_frame_equal(prefix[columns], extended.iloc[:220][columns])


def test_spec_prohibits_all_outcomes_and_fixes_no_rescue() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    assert all(value == "PROHIBITED" for key, value in spec["outcome_policy"].items() if key != "selection_rule")
    assert spec["construction_gates"]["no_rescue"].startswith("a failed primary role")
    assert spec["input"]["research_end"] == "2023-12-31"
    assert spec["pit_semantics"]["unknown_or_invalid"] == "missing and fail closed"
