from pathlib import Path
import sys

import numpy as np
import pandas as pd


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_minvol_anchor_lineage_freeze_v2 as module


def test_null_optional_rights_coalesces_to_zero() -> None:
    assert module.canonical_optional_zero(np.nan) == 0.0
    assert module.canonical_optional_zero(None) == 0.0
    assert module.canonical_optional_zero(0.0) == 0.0


def test_null_rights_action_rebases_prior_volume() -> None:
    rows = pd.DataFrame(
        {
            "trade_id": ["x", "x"],
            "volume": [10.0, 20.0],
            "corporate_action_count": [0, 1],
            "share_multiplier": [1.0, 2.0],
            "rights_ratio": [np.nan, np.nan],
            "corporate_action_available_date": [pd.NaT, "2024-01-02"],
            "corporate_action_valid": [True, True],
            "corporate_action_blocking": [False, False],
            "trade_date": ["2024-01-01", "2024-01-02"],
        }
    )
    assert np.array_equal(
        module.volumes_in_signal_coordinate(rows), np.array([20.0, 20.0])
    )


def test_fresh_identity_and_outputs() -> None:
    assert module.SPEC.name == "EXP-OBL-014_spec.json"
    assert module.FEATURES.name == "minvol_anchor_features_v2.csv"
    assert module.FREEZE.name == "LINEAGE-OBL-014.json"
