from pathlib import Path
import sys

import numpy as np


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_pivot_topology_lineage_freeze as module


def test_strict_extrema_reject_ties() -> None:
    values = np.array([3.0, 1.0, 2.0, 1.0, 1.0, 4.0])
    assert module.strict_extrema(values, 1, "min") == [1]
    assert module.strict_extrema(values, 1, "max") == [2]


def test_higher_low_lower_high_topology() -> None:
    lows = np.array([5.0, 2.0, 4.0, 3.0, 5.0, 4.0, 6.0])
    highs = np.array([6.0, 5.0, 9.0, 6.0, 8.0, 7.0, 9.0])
    result = module.topology(lows, highs, radius=1)
    assert result["higher_low"] is True
    assert result["lower_high"] is True
    assert result["lineage_id"] == "L11_HIGHER_LOW_LOWER_HIGH"


def test_outputs_are_fresh_and_outcome_blind() -> None:
    assert module.SPEC.name == "EXP-OBL-012_spec.json"
    assert module.FREEZE.name == "LINEAGE-OBL-012.json"
    assert not module.FORBIDDEN_COLUMNS.intersection(
        {"lineage_id", "neighbor_lineage_id", "trough_log_change"}
    )
