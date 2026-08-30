from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

WORK = Path(__file__).resolve().parents[1]


def test_exp_plp_001_rejects_incremental_day5_persistence() -> None:
    result = json.loads((WORK / "artifacts/post_landmark_persistence.json").read_text())
    primary = result["primary"]
    assert result["experiment_id"] == "EXP-PLP-001"
    assert result["decision"] == "REJECT"
    assert result["mechanism_verdict"] == (
        "DAY5_SEPARATION_DOES_NOT_IMPLY_INCREMENTAL_POST_DAY5_PERSISTENCE"
    )
    assert not any(
        primary[name]
        for name in ("raw_gate", "controlled_gate", "mechanical_gate", "neighbor_gate")
    )
    assert primary["raw"]["rho"] < 0.0
    assert primary["controlled_preentry"]["loyo_positive_count"] == 0
    assert max(result["audit"]["maximum_reconstruction_error"].values()) <= 1e-12
    assert result["strategy_modification"] == "NONE"


def test_exp_plp_001_residuals_reconstruct_terminal_returns() -> None:
    frame = pd.read_csv(WORK / "artifacts/post_landmark_persistence.csv")
    assert len(frame) == 295
    for day in (5, 10, 20):
        landmark = frame[f"return_{day}d"]
        residual = frame[f"residual_return_after_{day}d"]
        mask = landmark.notna()
        reconstructed = (1.0 + landmark[mask]) * (1.0 + residual[mask]) - 1.0
        assert np.allclose(
            reconstructed, frame.loc[mask, "round_trip_return"], rtol=0.0, atol=1e-12
        )
