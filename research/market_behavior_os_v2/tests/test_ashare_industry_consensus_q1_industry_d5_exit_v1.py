from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
RUNNER = (
    ROOT
    / "research/market_behavior_os_v2/scripts/"
    "run_ashare_industry_consensus_q1_industry_d5_exit_v1.py"
)


def _module():
    spec = importlib.util.spec_from_file_location("industry_d5_exit_test", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_d5_feature_uses_five_completed_industry_sessions() -> None:
    module = _module()
    calendar = [date(2020, 1, 1) + timedelta(days=index) for index in range(30)]
    corrected = pd.DataFrame(
        {
            "cal_idx": np.repeat(np.arange(1, 6), 2),
            "industry": ["A"] * 10,
            "step_return": np.log1p([-0.01] * 10),
        }
    )
    plans = pd.DataFrame(
        {
            "signal_date": [calendar[0], calendar[0]],
            "industry": ["A", "A"],
            "entry_index": [1, 1],
            "due_index": [21, 21],
        }
    )
    features = module._event_features(corrected, plans, calendar)
    assert len(features) == 1
    assert bool(features.triggered.iloc[0]) is True
    assert features.d5_decision_index.iloc[0] == 5
    assert features.early_exit_index.iloc[0] == 6


def test_candidate_due_changes_only_triggered_events() -> None:
    module = _module()
    plans = pd.DataFrame(
        {
            "signal_date": [date(2020, 1, 1), date(2020, 1, 2)],
            "industry": ["A", "B"],
            "entry_index": [1, 2],
            "due_index": [21, 22],
        }
    )
    features = pd.DataFrame(
        {
            "signal_date": plans.signal_date,
            "industry": plans.industry,
            "triggered": [True, False],
            "early_exit_index": [6, 7],
        }
    )
    candidate = module._candidate_plans(plans, features)
    assert candidate.due_index.tolist() == [6, 22]


def test_screen_requires_negative_triggered_payoff_in_both_blocks() -> None:
    module = _module()
    early = [date(2019, 1, 1) + timedelta(days=index) for index in range(15)]
    late = [date(2022, 1, 1) + timedelta(days=index) for index in range(15)]
    dates = early + late + [date(2019, 3, 1), date(2022, 3, 1)]
    features = pd.DataFrame(
        {
            "signal_date": dates,
            "industry": ["A"] * len(dates),
            "industry_d5_return": [-0.01] * 30 + [0.01, 0.01],
            "triggered": [True] * 30 + [False, False],
            "block": ["2018-2020"] * 15
            + ["2021-2023"] * 15
            + ["2018-2020", "2021-2023"],
        }
    )
    trades = pd.DataFrame(
        {
            "signal_date": features.signal_date,
            "industry": features.industry,
            "net_return": [-0.11] * 30 + [0.02, 0.02],
        }
    )
    _, gate = module._screen(trades, features)
    assert gate["passed"] is True
