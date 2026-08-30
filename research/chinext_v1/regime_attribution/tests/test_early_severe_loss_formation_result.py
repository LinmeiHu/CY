from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

WORK = Path(__file__).resolve().parents[1]


def test_exp_slf_001_passes_all_frozen_gates() -> None:
    result = json.loads(
        (WORK / "artifacts/early_severe_loss_formation.json").read_text()
    )
    primary = result["primary"]
    assert result["experiment_id"] == "EXP-SLF-001"
    assert result["decision"] == "DEEPEN"
    assert result["mechanism_verdict"] == (
        "SEVERE_LOSS_PATH_SEPARATES_BY_DAY3_WITH_QUALIFICATION"
    )
    assert all(
        primary[name]
        for name in (
            "raw_gate",
            "controlled_gate",
            "neighbor_gate",
            "temporal_gate",
            "falsification_gate",
        )
    )
    assert result["audit"]["post_exit_prices_read"] == 0
    assert result["strategy_modification"] == "NONE"


def test_exp_slf_001_table_preserves_fixed_availability() -> None:
    frame = pd.read_csv(WORK / "artifacts/early_severe_loss_formation.csv")
    assert len(frame) == 399
    assert frame.trade_id.nunique() == 399
    assert frame.return_2d.notna().sum() == 399
    assert frame.return_3d.notna().sum() == 356
    assert frame.return_5d_rebuilt.notna().sum() == 295
    assert int(frame.severe_loss.sum()) == 44
