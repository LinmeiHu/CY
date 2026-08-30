from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

WORK = Path(__file__).resolve().parents[1]


def test_exp_egp_001_rejects_entry_gap_mechanism() -> None:
    result = json.loads(
        (WORK / "artifacts/entry_gap_premium_attribution.json").read_text()
    )
    primary = result["primary"]
    assert result["experiment_id"] == "EXP-EGP-001"
    assert result["decision"] == "REJECT"
    assert not any(
        primary[name]
        for name in (
            "raw_gate",
            "controlled_gate",
            "topology_gate",
            "neighbor_gate",
            "falsification_gate",
        )
    )
    assert primary["controlled_preentry_market"]["loyo_positive_count"] == 0
    assert result["audit"]["nonzero_intraday_fill_premiums"] == 0
    assert result["strategy_modification"] == "NONE"


def test_exp_egp_001_has_exact_t1_open_fills() -> None:
    frame = pd.read_csv(WORK / "artifacts/entry_gap_premium_attribution.csv")
    assert len(frame) == 399
    assert (frame.execution_price == frame.execution_open).all()
    assert (frame.intraday_fill_premium == 0.0).all()
