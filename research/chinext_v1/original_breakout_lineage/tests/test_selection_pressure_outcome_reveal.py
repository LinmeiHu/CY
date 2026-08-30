from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_selection_pressure_outcome_reveal as module


def test_fresh_followup_identity() -> None:
    assert module.SPEC.name == "EXP-OBL-011_spec.json"
    assert module.OUTPUT_JSON.name == "EXP-OBL-011_result.json"
    assert module.PREDICTOR == "selection_pressure"


def test_binary_lineage_is_a_control() -> None:
    assert "contested_selection" in module.CONTROL_COLUMNS
    assert module.PREDICTOR not in module.CONTROL_COLUMNS
