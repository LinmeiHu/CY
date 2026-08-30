from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_lineage_outcome_reveal.py"
SPEC = importlib.util.spec_from_file_location("obl_reveal", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_lineage_strength_is_fixed_and_symmetric() -> None:
    assert MODULE.LINEAGE_STRENGTH == {
        "L00_BASE_LOW_ACCEPTANCE_LOW": 0.0,
        "L01_BASE_LOW_ACCEPTANCE_HIGH": 1.0,
        "L10_BASE_HIGH_ACCEPTANCE_LOW": 1.0,
        "L11_BASE_HIGH_ACCEPTANCE_HIGH": 2.0,
    }


def test_bh_is_monotone_and_bounded() -> None:
    result = MODULE.benjamini_hochberg({"a": 0.01, "b": 0.04, "c": 0.03})
    assert result["a"] <= result["c"] <= result["b"]
    assert all(0 <= value <= 1 for value in result.values())


def test_positive_association_fixture() -> None:
    frame = pd.DataFrame({"x": [0, 0, 1, 1, 2, 2, 3, 3], "y": range(8)})
    packet = MODULE.association(frame, "x", "y")
    assert packet["n"] == 8
    assert packet["rho"] is not None and packet["rho"] > 0.9


def test_primary_endpoints_are_fixed() -> None:
    assert MODULE.PRIMARY_ENDPOINTS == ("mfe", "non_false_breakout")
