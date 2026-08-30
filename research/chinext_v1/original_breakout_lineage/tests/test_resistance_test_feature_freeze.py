from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_resistance_test_feature_freeze.py"
SPEC = importlib.util.spec_from_file_location("resistance_freeze", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_episode_count_distinguishes_stays_from_retests() -> None:
    assert MODULE.episode_count(np.array([True, True, False, True, True])) == 2
    assert MODULE.episode_count(np.array([False, True, True, True])) == 1
    assert MODULE.episode_count(np.array([False, False])) == 0


def test_maximum_zone_run() -> None:
    assert MODULE.maximum_run(np.array([True, True, False, True])) == 2
    assert MODULE.maximum_run(np.array([False, False])) == 0


def test_fixed_neighbor_widths() -> None:
    assert MODULE.ZONE_WIDTHS == (0.01, 0.02, 0.03)


def test_outcome_columns_forbidden() -> None:
    assert {"mfe", "mae", "false_breakout", "round_trip_return"}.issubset(
        MODULE.FORBIDDEN_COLUMNS
    )
