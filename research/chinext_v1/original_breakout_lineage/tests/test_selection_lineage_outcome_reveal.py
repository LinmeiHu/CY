from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_selection_lineage_outcome_reveal as module


def test_fresh_reveal_identity() -> None:
    assert module.SPEC.name == "EXP-OBL-010_spec.json"
    assert module.OUTPUT_JSON.name == "EXP-OBL-010_result.json"
    assert module.PREDICTOR == "contested_selection"


def test_predictor_not_in_fixed_controls() -> None:
    assert module.PREDICTOR not in module.CONTROL_COLUMNS
    assert "entry_rs_score" in module.CONTROL_COLUMNS
    assert "candidate_count" in module.CONTEXT_CONTROLS
    assert "vacancies_before_selection" in module.CONTEXT_CONTROLS
