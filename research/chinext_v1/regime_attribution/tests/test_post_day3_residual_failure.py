from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_post_day3_residual_failure as persistence


def test_multiplicative_residual_identity() -> None:
    terminal = pd.Series([0.20])
    landmark = pd.Series([0.10])
    residual = persistence.multiplicative_residual(terminal, landmark)
    assert (1 + landmark.iloc[0]) * (1 + residual.iloc[0]) == pytest.approx(1.20)


def test_contract_uses_frozen_day3_feature_and_fresh_outputs() -> None:
    source = Path(persistence.__file__).read_text(encoding="utf-8")
    assert "adverse_stock_specific_3d" in source
    assert persistence.OUTPUT_JSON.name == "post_day3_residual_failure.json"
    assert persistence.ACCEPTED_DAY5_PERSISTENCE.name == "post_landmark_persistence.json"
    assert "return_3d" not in persistence.BASE_CONTROLS
