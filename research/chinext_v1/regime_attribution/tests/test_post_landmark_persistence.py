from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_post_landmark_persistence as persistence


def test_multiplicative_residual_reconstructs_terminal_return() -> None:
    landmark = pd.Series([0.10, -0.05, 0.25])
    future = pd.Series([0.20, -0.10, 0.00])
    terminal = (1.0 + landmark) * (1.0 + future) - 1.0
    observed = persistence.residual_return(terminal, landmark)
    assert np.allclose(observed, future, rtol=0.0, atol=1e-14)


def test_day5_is_frozen_primary_and_no_strategy_output_exists() -> None:
    assert persistence.PRIMARY_LANDMARK == 5
    assert persistence.LANDMARKS == (5, 10, 20)
    assert persistence.OUTPUT_TABLE.name == "post_landmark_persistence.csv"


def test_non_positive_wealth_denominator_fails_closed() -> None:
    try:
        persistence.residual_return(pd.Series([0.0]), pd.Series([-1.0]))
    except persistence.PersistenceError:
        return
    raise AssertionError("non-positive landmark wealth denominator did not fail closed")
