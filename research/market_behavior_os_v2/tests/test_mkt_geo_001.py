from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_geo_001.py"
SPEC = ROOT / "research/market_behavior_os_v2/experiments/MKT-GEO-001_spec.json"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_geo_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
geometry = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(geometry)


def test_state_boundaries_are_fixed_and_economic() -> None:
    assert [geometry.direction_state(value) for value in (-1.0, 0.0, 1.0)] == ["NEGATIVE", "NEUTRAL", "POSITIVE"]
    assert [geometry.discovery_state(value) for value in (-0.1, 0.0, 0.1)] == ["BREAKDOWN", "BALANCED", "EXPANSION"]
    assert [geometry.concentration_state(value) for value in (0.1, 0.5, 0.9)] == ["DIFFUSE", "MIDDLE", "CONCENTRATED"]


def test_partial_rank_removes_shared_linear_rank_control() -> None:
    control = np.arange(20, dtype=float)
    frame = pd.DataFrame({"left": control + np.tile([0.0, 1.0], 10), "right": control + np.tile([1.0, 0.0], 10), "control": control})
    value = geometry.partial_rank_correlation(frame, "left", "right", "control")
    assert np.isfinite(value)
    assert abs(value) < 1.0


def test_spec_forbids_usefulness_and_invalid_breadth_panel() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    assert "trading signal" in spec["forbidden_claims"]
    assert "future-return prediction" in spec["forbidden_claims"]
    assert "MKT-BRTH-001 invalid panels" in spec["forbidden_inputs"]
    assert spec["inputs"]["breadth_panel"]["sha256"].startswith("60ca6bf5")
