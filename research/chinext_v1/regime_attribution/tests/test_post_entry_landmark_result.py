from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

WORK = Path(__file__).resolve().parents[1]


def test_exp_pel_001_passes_with_qualification() -> None:
    result = json.loads((WORK / "artifacts/post_entry_landmark_emergence.json").read_text())
    assert result["experiment_id"] == "EXP-PEL-001"
    assert result["decision"] == "DEEPEN"
    assert result["mechanism_verdict"] == (
        "RIGHT_TAIL_SEPARATES_BY_LANDMARK5_WITH_QUALIFICATION"
    )
    assert result["audit"]["landmark5_cycles"] == 295
    assert result["audit"]["post_exit_price_rows_read"] == 0
    assert all(result["primary"][gate] for gate in (
        "raw_gate", "controlled_gate", "neighbor_gate", "falsification_gate"
    ))
    assert result["strategy_modification"] == "NONE"


def test_exp_pel_001_table_is_fixed_landmark_sample() -> None:
    frame = pd.read_csv(WORK / "artifacts/post_entry_landmark_attribution.csv")
    assert len(frame) == 295
    assert frame.trade_id.nunique() == 295
    assert frame.return_5d.notna().all()
