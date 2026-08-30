from pathlib import Path
import sys

import pandas as pd


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_minvol_support_lineage_freeze as module


def test_binary_support_assignment_drops_recovery_axis() -> None:
    frame = pd.DataFrame(
        {
            "low_support_held": [False, True],
            "close_support_held_neighbor": [True, False],
            "recovered_above_anchor_close": [True, False],
        }
    )
    result = module.refine_assignments(frame)
    assert result.support_lineage_id.tolist() == ["L_SUPPORT_BROKEN", "L_SUPPORT_HELD"]
    assert result.neighbor_support_lineage_id.tolist() == ["L_SUPPORT_HELD", "L_SUPPORT_BROKEN"]


def test_fresh_binary_freeze_identity() -> None:
    assert module.SPEC.name == "EXP-OBL-015_spec.json"
    assert module.FREEZE.name == "LINEAGE-OBL-015.json"
    assert set(module.PRIMARY_NAMES.values()) == {"L_SUPPORT_BROKEN", "L_SUPPORT_HELD"}
