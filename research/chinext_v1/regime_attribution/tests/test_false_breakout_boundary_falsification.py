from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_false_breakout_boundary_falsification as boundary


def test_boundary_clean_excludes_entry_mfe_and_exit_mae() -> None:
    frame = pd.DataFrame(
        {
            "days_to_mfe": [0, 2, 2],
            "days_to_mae": [2, 5, 3],
            "holding_trading_days": [5, 5, 5],
        }
    )
    flags = boundary.boundary_flags(frame)
    assert flags.boundary_clean.tolist() == [False, False, True]


def test_strict_interior_excludes_every_endpoint_boundary() -> None:
    frame = pd.DataFrame(
        {
            "days_to_mfe": [1, 0, 1, 5],
            "days_to_mae": [4, 4, 5, 1],
            "holding_trading_days": [5, 5, 5, 5],
        }
    )
    flags = boundary.boundary_flags(frame)
    assert flags.strict_interior.tolist() == [True, False, False, False]
