from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_reference_age_outcome_reveal as module


def test_fresh_experiment_identity_and_outputs() -> None:
    assert module.SPEC.name == "EXP-OBL-007_spec.json"
    assert module.OUTPUT_JSON.name == "EXP-OBL-007_result.json"
    assert module.PREDICTOR == "sessions_since_reference"


def test_fixed_formation_controls_do_not_include_predictor() -> None:
    assert module.PREDICTOR not in module.CONTROL_COLUMNS
    assert set(module.FORMATION_CONTROLS) == {
        "prebreakout_distance",
        "breakout_margin",
    }
