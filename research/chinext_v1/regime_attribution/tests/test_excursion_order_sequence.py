from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_excursion_order_sequence as excursion


def test_normalized_order_is_positive_when_mae_occurs_first() -> None:
    observed = excursion.normalized_excursion_order(
        pd.Series([8, 2]), pd.Series([2, 8]), pd.Series([10, 10])
    )
    assert np.allclose(observed, [0.6, -0.6])


def test_zero_duration_uses_unit_denominator() -> None:
    observed = excursion.normalized_excursion_order(
        pd.Series([0]), pd.Series([0]), pd.Series([0])
    )
    assert observed.iloc[0] == 0.0


def test_endpoint_directions_are_fixed_and_opposite() -> None:
    assert excursion.ENDPOINT_DIRECTIONS == {
        "extreme_winner": 1,
        "false_breakout": -1,
    }
