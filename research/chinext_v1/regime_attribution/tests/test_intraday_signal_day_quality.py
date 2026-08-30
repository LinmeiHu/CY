from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts/run_intraday_signal_day_quality.py"
)
SPEC = importlib.util.spec_from_file_location("run_intraday_signal_day_quality", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def synthetic_session(kind: str) -> pd.DataFrame:
    date = pd.Timestamp("2024-01-02")
    times = [pd.Timestamp.combine(date.date(), item) for item in MODULE.EXPECTED_TIMES]
    if kind == "persistent":
        close = np.linspace(10.0, 11.0, len(times))
    elif kind == "spike_fade":
        close = np.r_[
            np.linspace(10.0, 11.0, 10),
            np.linspace(10.95, 10.4, 21),
            np.linspace(10.39, 10.1, 210),
        ]
    else:
        raise ValueError(kind)
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + 0.01
    low = np.minimum(open_, close) - 0.01
    volume = np.full(len(times), 1000.0)
    amount = volume * (open_ + close) / 2.0
    return pd.DataFrame(
        {
            "bar_end_time": times,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "amount": amount,
        }
    )


def test_exact_session_grid_and_five_minute_aggregation() -> None:
    rows = synthetic_session("persistent")
    continuous = MODULE.continuous_rows(rows)
    five = MODULE.aggregate_5m(continuous)
    assert len(continuous) == 240
    assert len(five) == 48
    assert five.bar_end_time.iloc[0].time().isoformat() == "09:35:00"
    assert five.bar_end_time.iloc[-1].time().isoformat() == "15:00:00"


def test_path_features_rank_persistent_above_spike_fade() -> None:
    persistent = MODULE.compute_session_features(synthetic_session("persistent"))
    faded = MODULE.compute_session_features(synthetic_session("spike_fade"))
    assert persistent["path_efficiency_1m"] > faded["path_efficiency_1m"]
    assert persistent["time_above_session_vwap"] > faded["time_above_session_vwap"]
    assert persistent["opening_peak_retention"] > faded["opening_peak_retention"]


def test_partial_rank_removes_exact_linear_rank_relation() -> None:
    frame = pd.DataFrame(
        {
            "x": np.arange(1.0, 101.0),
            "y": np.arange(1.0, 101.0) + np.tile([-0.01, 0.01], 50),
            "control": np.arange(1.0, 101.0),
        }
    )
    estimate = MODULE.partial_rank(frame, "x", "y", ("control",))
    assert np.isnan(estimate)


def test_flat_session_receives_neutral_mathematical_values() -> None:
    rows = synthetic_session("persistent")
    rows[["open", "high", "low", "close"]] = 10.0
    rows["amount"] = rows.volume * 10.0
    result = MODULE.compute_session_features(rows)
    assert result["path_efficiency_1m"] == 0.0
    assert result["time_above_session_vwap"] == 0.5
    assert result["signal_day_close_location"] == 0.5
    assert result["flat_signal_session"]
