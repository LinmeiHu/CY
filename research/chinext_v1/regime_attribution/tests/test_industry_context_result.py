from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

WORK = Path(__file__).resolve().parents[1]


def test_exp_icd_001_is_complete_and_rejected() -> None:
    result = json.loads((WORK / "artifacts/industry_context_attribution.json").read_text())
    assert result["experiment_id"] == "EXP-ICD-001"
    assert result["decision"] == "REJECT"
    assert result["mechanism_verdict"] == "NEITHER_COMPONENT_SURVIVES"
    assert result["passing_components"] == []
    assert result["audit"]["eligible_cycles"] == 296
    assert result["audit"]["pit_or_causal_failures"] == 0
    assert result["strategy_modification"] == "NONE"


def test_exp_icd_001_table_preserves_frozen_peer_sample() -> None:
    frame = pd.read_csv(WORK / "artifacts/industry_context_decomposition.csv")
    assert len(frame) == 296
    assert frame.trade_id.nunique() == 296
    assert (frame.peer20_count >= 5).all()
    assert (frame.peer60_count >= 5).all()
    assert frame.industry.notna().all()
