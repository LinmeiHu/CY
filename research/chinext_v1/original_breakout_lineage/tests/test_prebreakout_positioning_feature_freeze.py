from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_prebreakout_positioning_feature_freeze.py"
SPEC = importlib.util.spec_from_file_location("positioning_freeze", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_forbidden_outcomes_are_explicit() -> None:
    assert {"mfe", "mae", "false_breakout", "round_trip_return"}.issubset(
        MODULE.FORBIDDEN_COLUMNS
    )


def test_output_identity_is_fresh() -> None:
    assert MODULE.OUTPUT_TABLE.name == "prebreakout_positioning_features.csv"
    assert MODULE.FEATURE_FREEZE.name == "FEATURE-OBL-006.json"
