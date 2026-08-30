from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_outcome_blind_lineage_freeze.py"
SPEC = importlib.util.spec_from_file_location("obl_freeze", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_longest_true_run() -> None:
    assert MODULE.longest_true_run(np.array([False, True, True, False, True])) == 2
    assert MODULE.longest_true_run(np.array([False, False])) == 0


def test_reference_path_features_persistent_path() -> None:
    rows = pd.DataFrame(
        {
            "open": [9.9, 10.1, 10.2, 10.3],
            "high": [10.1, 10.2, 10.3, 10.4],
            "low": [9.8, 10.0, 10.1, 10.2],
            "close": [10.05, 10.15, 10.25, 10.35],
            "volume": [100.0, 100.0, 100.0, 100.0],
            "amount": [1000.0, 1010.0, 1020.0, 1030.0],
        }
    )
    result = MODULE.reference_path_features(rows, 10.0)
    assert result["first_cross_index"] == 0.0
    assert result["time_above_reference"] == 1.0
    assert result["reference_loss_count"] == 0.0
    assert result["below_reference_resilience"] == 1.0
    assert 0 < result["close_reference_retention"] <= 1


def test_lineage_names_are_neutral_quadrants() -> None:
    base = pd.Series([False, False, True, True])
    acceptance = pd.Series([False, True, False, True])
    assert MODULE.lineage_id(base, acceptance).tolist() == [
        "L00_BASE_LOW_ACCEPTANCE_LOW",
        "L01_BASE_LOW_ACCEPTANCE_HIGH",
        "L10_BASE_HIGH_ACCEPTANCE_LOW",
        "L11_BASE_HIGH_ACCEPTANCE_HIGH",
    ]


def test_forbidden_outcomes_are_explicit() -> None:
    assert {"mfe", "mae", "false_breakout", "round_trip_return"}.issubset(
        MODULE.FORBIDDEN_COLUMNS
    )
