from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

WORK = Path(__file__).resolve().parents[1]


def test_exp_eos_001_refines_to_false_breakout_only() -> None:
    result = json.loads((WORK / "artifacts/excursion_order_sequence.json").read_text())
    endpoints = result["endpoints"]
    assert result["experiment_id"] == "EXP-EOS-001"
    assert result["decision"] == "REFINE"
    assert result["passing_endpoints"] == ["false_breakout"]
    assert endpoints["false_breakout"]["passes_all"]
    assert not endpoints["extreme_winner"]["controlled_gate"]
    assert endpoints["false_breakout"]["controlled_oriented"][
        "loyo_positive_count"
    ] == 8
    assert result["audit"]["coordinate_failures"] == 0
    assert result["strategy_modification"] == "NONE"


def test_exp_eos_001_order_coordinates_are_bounded() -> None:
    frame = pd.read_csv(WORK / "artifacts/excursion_order_attribution.csv")
    assert len(frame) == 399
    assert frame.normalized_excursion_order.abs().max() <= 1.0
    assert (
        frame.excursion_order_days == frame.days_to_mfe - frame.days_to_mae
    ).all()
