from pathlib import Path
import sys

import numpy as np
import pandas as pd


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_minvol_anchor_lineage_freeze as module


def test_volume_rebase_applies_only_to_prior_rows() -> None:
    rows = pd.DataFrame(
        {
            "volume": [10.0, 20.0, 30.0],
            "corporate_action_count": [0, 1, 0],
            "share_multiplier": [1.0, 2.0, 1.0],
            "rights_ratio": [0.0, 0.0, 0.0],
            "corporate_action_available_date": [pd.NaT, "2024-01-02", pd.NaT],
            "corporate_action_valid": [True, True, True],
            "corporate_action_blocking": [False, False, False],
            "trade_date": ["2024-01-01", "2024-01-02", "2024-01-03"],
        }
    )
    assert np.array_equal(
        module.volumes_in_signal_coordinate(rows), np.array([20.0, 20.0, 30.0])
    )


def test_neutral_lineage_map() -> None:
    assert module.LINEAGES[(True, True)] == "L11_LOW_HELD_RECOVERED"
    assert module.LINEAGES[(False, False)] == "L00_LOW_BROKEN_NOT_RECOVERED"


def test_fresh_outcome_blind_paths() -> None:
    assert module.SPEC.name == "EXP-OBL-013_spec.json"
    assert module.FREEZE.name == "LINEAGE-OBL-013.json"
    assert "mfe" in module.FORBIDDEN_COLUMNS
