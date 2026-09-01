from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT
    / "research/market_behavior_os_v2/scripts/"
    "run_ashare_opportunity_health_overlay_cycle_018.py"
)
RESULT = (
    ROOT
    / "research/market_behavior_os_v2/artifacts/"
    "ASHARE-OPPORTUNITY-HEALTH-OVERLAY-CYCLE-018_result.json"
)


def _module():
    spec = importlib.util.spec_from_file_location("opportunity_overlay_cycle_018_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_contract_freezes_one_feature_and_one_mapping_before_outcomes() -> None:
    spec = _module()._load_spec()
    assert spec["starting_checkpoint"] == "3455f5ee30"
    assert spec["positive_industry_breadth"]["horizon_sessions"] == 20
    assert spec["states"]["threshold_method"] == "fixed economic thirds frozen before outcomes"
    assert spec["overlay"]["exposure_mapping"] == {"LOW": 0.5, "MEDIUM": 0.75, "HIGH": 1.0}
    assert spec["champion"]["selection_changes_authorized"] is False


def test_phase_a_failure_stops_before_overlay_replay() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    assert result["phase_a"]["authorized"] is False
    assert result["classification"] == "OPPORTUNITY_HEALTH_NOT_USEFUL"
    assert result["overlay"] is None
    assert result["annual_attribution"] == []
    assert result["external_artifacts"] == {}
    assert result["phase_a"]["high_minus_low_cohort_payoff"] < 0


def test_failed_feature_does_not_change_champion_or_search_rescue() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    assert result["boundaries"] == {
        "champion_selection_changed": False,
        "cy011_read": False,
        "existing_cohorts_rescaled": False,
        "exposure_grid_search": False,
        "oos_claim": False,
        "post_2023_read": False,
        "second_overlay_tested": False,
        "threshold_search": False,
    }
    assert result["champion"]["total_return"] > 1.22
