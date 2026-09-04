from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RUNNER = (
    ROOT
    / "research/market_behavior_os_v2/scripts"
    / "run_ashare_medium_term_overnight_strength_v1.py"
)


def _load_runner():
    spec = importlib.util.spec_from_file_location("medium_overnight", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_exact_formation_and_future_response_alignment() -> None:
    runner = _load_runner()
    frame = pd.DataFrame(
        {
            "trade_date": pd.date_range("2020-01-01", periods=41),
            "cal_idx": np.arange(41),
            "symbol": ["A"] * 41,
            "gap_return": [0.01] * 41,
            "intraday_return": [0.02] * 41,
            "step_return": [0.03] * 41,
        }
    )
    result = runner._attach_formation_and_response(frame).set_index("cal_idx")
    assert np.isclose(result.loc[19, "overnight20"], 0.20)
    assert np.isclose(result.loc[19, "intraday20"], 0.40)
    assert bool(result.loc[19, "response_complete"])
    assert np.isclose(result.loc[19, "gross_h20"], np.expm1(0.60))


def test_missing_calendar_row_fails_exact_windows() -> None:
    runner = _load_runner()
    frame = pd.DataFrame(
        {
            "trade_date": pd.date_range("2020-01-01", periods=40),
            "cal_idx": list(range(20)) + list(range(21, 41)),
            "symbol": ["A"] * 40,
            "gap_return": [0.01] * 40,
            "intraday_return": [0.02] * 40,
            "step_return": [0.03] * 40,
        }
    )
    result = runner._attach_formation_and_response(frame).set_index("cal_idx")
    assert not bool(result.loc[0, "response_complete"])
    assert np.isnan(result.loc[21, "overnight20"])


def test_top_selection_uses_signal_then_symbol_only() -> None:
    runner = _load_runner()
    frame = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2020-01-31"] * 50),
            "symbol": [f"S{i:02d}" for i in range(50)],
            "overnight20": [1.0, 1.0, *list(np.linspace(0.9, -0.9, 48))],
            "gross_h20": list(reversed(range(50))),
        }
    )
    selected = runner._select_arms(frame)
    top = selected.loc[selected.arm.eq("TOP20"), "symbol"].tolist()
    assert "S00" in top and "S01" in top
    assert len(top) == 20
