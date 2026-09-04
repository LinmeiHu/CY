from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RUNNER = (
    ROOT
    / "research/market_behavior_os_v2/scripts"
    / "run_ashare_dispersion_stock_relative_reversal_v1.py"
)


def _load_runner():
    spec = importlib.util.spec_from_file_location("dispersion_stock_reversal", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_exact_h3_requires_consecutive_calendar_rows() -> None:
    runner = _load_runner()
    frame = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(
                ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-02", "2020-01-06"]
            ),
            "cal_idx": [10, 11, 12, 13, 10, 12],
            "symbol": ["A", "A", "A", "A", "B", "B"],
            "industry": ["I", "I", "I", "I", "I", "I"],
            "step_return": [0.0, 0.01, 0.02, 0.03, 0.0, 0.02],
        }
    )
    result = runner._attach_exact_h3(frame).set_index(["symbol", "cal_idx"])
    assert bool(result.loc[("A", 10), "response_complete"])
    assert result.loc[("A", 10), "gross_h3"] > 0.06
    assert not bool(result.loc[("B", 10), "response_complete"])


def test_arm_selection_uses_signal_then_symbol_only() -> None:
    runner = _load_runner()
    frame = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2020-01-02"] * 4),
            "industry": ["I", "I", "I", "I"],
            "symbol": ["D", "B", "A", "C"],
            "signal": [-0.03, -0.03, 0.02, 0.04],
            "gross_h3": [1.0, -1.0, 2.0, -2.0],
        }
    )
    selected = runner._select_arms(frame)
    candidate = selected.loc[selected.arm.eq("CANDIDATE"), "symbol"].item()
    opposite = selected.loc[selected.arm.eq("OPPOSITE"), "symbol"].item()
    assert candidate == "B"
    assert opposite == "C"


def test_generation_gate_is_conjunctive() -> None:
    runner = _load_runner()
    spec = {
        "generation_gate_all_required": {
            "minimum_high_state_dates": 80,
            "candidate_minus_event_mean_minimum": 0.002,
            "candidate_minus_opposite_arm_minimum": 0.003,
            "candidate_severe_loss_not_more_than_event_by_pp": 0.01,
            "minimum_candidate_response_retention": 0.8,
        }
    }
    summary = {
        "dates": 100,
        "candidate_mean_net": 0.01,
        "candidate_minus_control": 0.004,
        "candidate_minus_opposite": 0.005,
        "candidate_median_event_net": -0.001,
        "candidate_severe_rate": 0.02,
        "control_severe_rate": 0.02,
        "candidate_response_retention": 0.95,
    }
    yearly = {
        "2020": {"candidate_minus_control": 0.001},
        "2021": {"candidate_minus_control": 0.001},
    }
    checks = runner._generation_checks(summary, yearly, spec)
    assert not checks["candidate_median_event_net_positive"]
    assert not all(checks.values())
