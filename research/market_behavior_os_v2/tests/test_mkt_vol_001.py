from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_vol_001.py"
SPEC = ROOT / "research/market_behavior_os_v2/experiments/MKT-VOL-001_spec.json"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_vol_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
vol = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(vol)


def test_spec_is_outcome_blind_and_no_rescue() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    forbidden = " ".join(spec["forbidden_inputs"])
    assert "future return" in forbidden
    assert "CY-011" in forbidden
    assert spec["universe"]["no_strategy_membership"] is True
    assert spec["gates"]["no_rescue"].startswith("A failed primary")


def test_map_has_distinct_volatility_roles() -> None:
    assert set(vol.ROLE_MAP) == {
        "realized_volatility", "downside_volatility", "intraday_range",
        "term_structure", "dispersion", "downside_mass_share",
        "volatility_concentration", "volatility_change",
    }


def test_components_use_absolute_correlation() -> None:
    corr = pd.DataFrame([[1, -0.9, 0.1], [-0.9, 1, 0.2], [0.1, 0.2, 1]], index=["realized_volatility", "downside_volatility", "intraday_range"], columns=["realized_volatility", "downside_volatility", "intraday_range"])
    assert vol.connected_components(corr) == [["downside_volatility", "realized_volatility"], ["intraday_range"]]
