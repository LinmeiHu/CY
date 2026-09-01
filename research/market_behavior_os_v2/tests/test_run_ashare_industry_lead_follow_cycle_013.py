from __future__ import annotations

import importlib.util
import sys
from collections import deque
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT
    / "research/market_behavior_os_v2/scripts/"
    "run_ashare_industry_lead_follow_cycle_013.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location("lead_follow_cycle_013_test", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
cycle = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = cycle
MODULE_SPEC.loader.exec_module(cycle)


def _view() -> dict[str, object]:
    returns = np.zeros((6, 240), dtype=float)
    abnormal = np.zeros_like(returns)
    return {
        "returns": returns,
        "abnormal": abnormal,
        "closes": np.full_like(returns, 10.0),
        "up_limits": np.full(6, 11.0),
        "symbols": np.array([f"00000{i}.SZ" for i in range(6)]),
        "prior_amount": np.full(6, 100_000_000.0),
        "market_returns": np.zeros(240, dtype=float),
    }


def test_same_minute_cluster_is_not_strict_leadership() -> None:
    view = _view()
    minute = int(cycle.EVENT_INDICES[0])
    view["returns"][0, minute] = 0.02
    view["returns"][1, minute] = 0.015
    view["abnormal"][0, minute] = 0.02
    view["abnormal"][1, minute] = 0.015
    assert cycle.detect_first_event(view) is None


def test_outcomes_begin_after_completed_event_minute() -> None:
    view = _view()
    minute = int(cycle.EVENT_INDICES[0])
    view["returns"][1:, minute] = 0.50
    view["returns"][1:, minute + 1 : minute + 4] = 0.001
    outcome = cycle.calculate_outcomes(view, 0, minute)
    assert np.isclose(outcome["w1_3_median_abnormal"], 0.003)
    assert np.isclose(outcome["w1_3_positive_fraction"], 1.0)


def test_control_matching_is_strictly_prior_and_requires_twenty() -> None:
    candidates = deque(maxlen=60)
    for index in range(20):
        candidates.append((index, f"2018-01-{index + 1:02d}", f"S{index}", (0.0, 0.0, 0.5, 18.0)))
    assert cycle.match_control(candidates, np.array([0.0, 0.0, 0.5, 18.0]), 19) is None
    selected = cycle.match_control(candidates, np.array([0.0, 0.0, 0.5, 18.0]), 20)
    assert selected is not None
    assert selected[0] == 19


def test_unbuyable_first_trigger_is_rejected() -> None:
    view = _view()
    minute = int(cycle.EVENT_INDICES[0])
    view["returns"][0, minute] = 0.02
    view["abnormal"][0, minute] = 0.02
    view["closes"][0, minute] = 10.995
    assert cycle.detect_first_event(view) is None


def test_trigger_before_eligible_window_disqualifies_later_event() -> None:
    view = _view()
    minute = int(cycle.EVENT_INDICES[0])
    view["returns"][0, minute - 2] = 0.02
    view["abnormal"][0, minute - 2] = 0.02
    view["returns"][1, minute] = 0.02
    view["abnormal"][1, minute] = 0.02
    assert cycle.detect_first_event(view) is None
