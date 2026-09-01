from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT / "research/market_behavior_os_v2/scripts/"
    "run_ashare_champion_applicability_map_cycle_019.py"
)
RESULT = (
    ROOT / "research/market_behavior_os_v2/artifacts/"
    "ASHARE-CHAMPION-APPLICABILITY-MAP-CYCLE-019_result.json"
)
PANEL = (
    ROOT / "research/market_behavior_os_v2/artifacts/"
    "ASHARE-CHAMPION-APPLICABILITY-MAP-CYCLE-019_panel.csv"
)


def _module():
    spec = importlib.util.spec_from_file_location("applicability_map_cycle_019_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_contract_freezes_four_dimensions_three_maps_and_no_strategy_change() -> None:
    spec = _module()._load_spec()
    assert spec["starting_checkpoint"] == "3e28f50b68"
    assert len(spec["dimensions"]) == 4
    assert len(spec["maps"]) == 3
    assert spec["champion"]["changes_authorized"] is False
    assert "Positive Industry Breadth rescue or active use" in spec["prohibited"]


def test_expanding_states_exclude_current_observation() -> None:
    module = _module()
    values = pd.Series([0.0, 1.0, 2.0, 100.0])
    states, q1, q2 = module._causal_states(values, 3)
    assert states[:3] == [None, None, None]
    assert states[3] == "HIGH"
    assert math.isclose(q1[3], 2.0 / 3.0)
    assert math.isclose(q2[3], 4.0 / 3.0)


def test_result_is_partial_habitat_without_replay_or_cycle018_rescue() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    assert result["classification"] == "PARTIAL_HABITAT_INFORMATION"
    assert result["champion_changed"] is False
    assert result["overlay_or_filter_replayed"] is False
    assert result["cycle_018_context"] == {
        "classification": "OPPORTUNITY_HEALTH_NOT_USEFUL",
        "used_as_active_dimension": False,
    }
    assert result["final_diagnostics"]["losing_period_coverage_for_clear_habitat"] is False


def test_dimension_decisions_and_panel_support_are_preserved() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    decisions = result["single_dimension_decisions"]
    assert decisions["ABSOLUTE_MARKET_STATE"]["classification"] == (
        "STRONG_APPLICABILITY_INFORMATION"
    )
    assert decisions["CROSS_SECTIONAL_DISPERSION"]["classification"] == ("CHRONOLOGICALLY_UNSTABLE")
    assert decisions["SYNCHRONIZATION"]["classification"] == ("WEAK_APPLICABILITY_INFORMATION")
    assert decisions["INDUSTRY_PERSISTENCE"]["classification"] == ("NO_USEFUL_INFORMATION")
    panel = pd.read_csv(PANEL)
    assert len(panel) == 263
    assert not panel.filter(regex="_state$").isna().any().any()
    assert sum(item["supported_cells"] for item in result["map_diagnostics"]) == 25
