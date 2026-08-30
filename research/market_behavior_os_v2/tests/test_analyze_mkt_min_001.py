from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/analyze_mkt_min_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("analyze_mkt_min_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
minute = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(minute)


def test_linear_five_day_trajectory_semantics() -> None:
    values = np.arange(8, dtype=float)[:, None]
    result = minute.trajectory_arrays(values)
    assert result["day_m5"].ravel().tolist() == [0.0, 1.0, 2.0, 3.0]
    assert result["day_m1"].ravel().tolist() == [4.0, 5.0, 6.0, 7.0]
    assert np.all(result["endpoint_change5"] == 4.0)
    assert np.all(result["endpoint_slope5"] == 1.0)
    assert np.all(result["ols_slope5"] == 1.0)
    assert np.all(result["ols_slope3"] == 1.0)
    assert np.all(result["signed_monotonic_fraction"] == 1.0)
    assert np.all(result["slope_acceleration"] == 0.0)
    assert np.all(result["reversal_shape"] == 0.0)


def test_reversal_shape_is_labeled_by_final_direction() -> None:
    values = np.array([[0.0], [1.0], [2.0], [1.0], [0.0]])
    result = minute.trajectory_arrays(values)
    assert result["reversal_shape"].item() == -1.0


def test_family_map_and_priority_cover_each_descriptor_once() -> None:
    spec = minute.adapter.load_frozen_spec()
    priority = spec["representation_gates"]["minimal_panel_priority"]
    assert priority == list(minute.adapter.DESCRIPTOR_COLUMNS)
    assert set(minute.FAMILY_BY_DESCRIPTOR) == set(minute.adapter.DESCRIPTOR_COLUMNS)
    assert spec["outcome_access"] is False
