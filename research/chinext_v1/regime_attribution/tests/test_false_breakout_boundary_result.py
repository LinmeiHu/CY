from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

WORK = Path(__file__).resolve().parents[1]


def test_exp_fbb_001_survives_all_boundary_gates() -> None:
    result = json.loads(
        (WORK / "artifacts/false_breakout_boundary_falsification.json").read_text()
    )
    assert result["experiment_id"] == "EXP-FBB-001"
    assert result["decision"] == "DEEPEN"
    assert result["mechanism_verdict"] == (
        "FALSE_BREAKOUT_ORDER_SURVIVES_ENTRY_EXIT_BOUNDARY_FALSIFICATION"
    )
    assert all(result["gates"].values())
    assert result["audit"]["boundary_clean_false_breakouts"] >= 60
    assert result["full_sample_boundary_controlled"]["loyo_positive_count"] == 8
    assert result["strategy_modification"] == "NONE"


def test_exp_fbb_001_boundary_clean_flags_are_exact() -> None:
    frame = pd.read_csv(WORK / "artifacts/false_breakout_boundary_attribution.csv")
    assert len(frame) == 399
    expected_clean = ~frame.mfe_at_entry.astype(bool) & ~frame.mae_at_exit.astype(bool)
    assert (frame.boundary_clean.astype(bool) == expected_clean).all()
    assert int(frame.boundary_clean.sum()) == 265
