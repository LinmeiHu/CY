from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import run_ashare_deep_decline_intraday_undercut_market_state_exit_v2 as subject  # noqa: E402


def test_market_state_is_causal_and_ignores_future_columns() -> None:
    frame = pd.DataFrame(
        {
            "market_median_ret60": [0.01, -0.01, -0.01, -0.01],
            "market_median_prior5_return": [-0.20, -0.06, -0.01, -0.01],
            "market_positive_fraction": [0.10, 0.20, 0.95, 0.60],
            "future_market_return": [-1.0, -1.0, -1.0, -1.0],
        }
    )
    expected = ["UP", "DOWN_SYSTEMIC", "DOWN_SYSTEMIC", "DOWN_ORDINARY"]
    assert subject.classify_market_state(frame).tolist() == expected
    frame["future_market_return"] = 1.0
    assert subject.classify_market_state(frame).tolist() == expected


def test_market_state_fails_closed_when_required_history_is_missing() -> None:
    frame = pd.DataFrame(
        {
            "market_median_ret60": [-0.01],
            "market_median_prior5_return": [float("nan")],
            "market_positive_fraction": [0.95],
        }
    )
    with pytest.raises(subject.ExperimentError, match="required causal"):
        subject.classify_market_state(frame)
