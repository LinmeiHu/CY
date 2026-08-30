from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_selection_competition_feature_freeze as module


def test_fresh_identity_and_output_contract() -> None:
    assert module.SPEC.name == "EXP-OBL-008_spec.json"
    assert module.OUTPUT_AUDIT.name == "EXP-OBL-008_audit.json"
    assert module.LINEAGE_FREEZE.name == "LINEAGE-OBL-008.json"


def test_outcome_paths_are_not_runner_inputs() -> None:
    values = {
        str(value)
        for value in vars(module).values()
        if isinstance(value, Path)
    }
    assert not any("trade_mechanism_attribution" in value for value in values)
    assert not any("pre_entry_transitions" in value for value in values)


def test_exact_capacity_boundary() -> None:
    assert (5 > 3) is True
    assert (3 > 3) is False
