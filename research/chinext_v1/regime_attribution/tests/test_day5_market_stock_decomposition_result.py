from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

WORK = Path(__file__).resolve().parents[1]


def test_exp_d5d_003_refines_without_full_falsification() -> None:
    result = json.loads(
        (WORK / "artifacts/day5_market_stock_decomposition_v3.json").read_text()
    )
    primary = result["primary"]
    assert result["experiment_id"] == "EXP-D5D-003"
    assert result["decision"] == "REFINE"
    assert result["mechanism_verdict"] == (
        "STOCK_SPECIFIC_COMPONENT_SURVIVES_CORE_BUT_NOT_FULL_FALSIFICATION"
    )
    assert primary["stock_raw_gate"] is True
    assert primary["stock_controlled_gate"] is True
    assert primary["market_gate"] is True
    assert primary["neighbor_gate"] is False
    assert primary["temporal_gate"] is False
    assert primary["falsification_gate"] is True
    assert primary["blocks"]["HOLDOUT_O0_2022_2023"]["rho"] is None
    assert result["strategy_modification"] == "NONE"


def test_exp_d5d_003_components_reconstruct_accepted_return() -> None:
    frame = pd.read_csv(WORK / "artifacts/day5_market_stock_decomposition_v3.csv")
    assert len(frame) == 295
    assert frame.trade_id.nunique() == 295
    reconstructed = np.expm1(
        frame.stock_specific_day5_excess + frame.market_day5_log_return
    )
    assert np.max(np.abs(reconstructed - frame.return_5d)) <= 1e-12
