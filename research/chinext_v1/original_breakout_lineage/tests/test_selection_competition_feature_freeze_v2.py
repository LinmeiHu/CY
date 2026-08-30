from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_selection_competition_feature_freeze_v2 as module


def test_fresh_identity_and_paths() -> None:
    assert module.SPEC.name == "EXP-OBL-009_spec.json"
    assert module.OUTPUT_AUDIT.name == "EXP-OBL-009_audit.json"
    assert module.LINEAGE_FREEZE.name == "LINEAGE-OBL-009.json"
    assert module.OUTPUT_TABLE.name == "selection_competition_features_v2.csv"


def test_no_outcome_input_path() -> None:
    values = {
        str(value)
        for value in vars(module).values()
        if isinstance(value, Path)
    }
    assert not any("trade_mechanism_attribution" in value for value in values)
    assert not any("pre_entry_transitions" in value for value in values)
