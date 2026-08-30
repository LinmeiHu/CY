from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_entry_gap_premium_attribution as gap


def test_excess_log_gap_removes_market_component() -> None:
    stock = pd.Series([0.03, -0.01])
    market = pd.Series([0.01, -0.02])
    observed = gap.excess_log_gap(stock, market)
    assert np.allclose(observed, [0.02, 0.01])


def test_primary_output_is_entry_gap_not_fill_slippage() -> None:
    assert gap.OUTPUT_TABLE.name == "entry_gap_premium_attribution.csv"
    assert set(gap.LEDGERS) == {
        "EXTENDED_2018_2021",
        "HOLDOUT_O0_2022_2023",
        "DEVELOPMENT_2024_2025",
    }
