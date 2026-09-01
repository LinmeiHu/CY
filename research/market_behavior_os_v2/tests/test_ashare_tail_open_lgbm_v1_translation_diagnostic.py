from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "research/market_behavior_os_v2/scripts/run_ashare_tail_open_lgbm_v1_translation_diagnostic.py"
SPEC = importlib.util.spec_from_file_location("tail_open_translation_test", PATH)
assert SPEC is not None and SPEC.loader is not None
DIAGNOSTIC = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DIAGNOSTIC
SPEC.loader.exec_module(DIAGNOSTIC)


def test_recover_cost_coordinates_preserves_cash_only_action() -> None:
    entry, exit_open, cash = 10.0, 10.1, 0.2
    gross = (exit_open + cash) / entry - 1.0
    net = (exit_open * (1 - 0.002) + cash) / (entry * (1 + 0.002)) - 1.0
    exit_ratio, cash_ratio = DIAGNOSTIC._recover_cost_coordinates(
        pd.DataFrame({"label_gross": [gross], "label_net": [net]})
    )
    np.testing.assert_allclose(exit_ratio, [exit_open / entry], rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(cash_ratio, [cash / entry], rtol=0.0, atol=1e-12)


def test_expanding_confidence_quintiles_do_not_use_the_current_date() -> None:
    frame = pd.DataFrame({"confidence": np.arange(21, dtype=float)})
    buckets = DIAGNOSTIC._expanding_quintiles(frame, "confidence")
    assert buckets.iloc[:20].eq(-1).all()
    assert buckets.iloc[20] == 5
