from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT / "research/market_behavior_os_v2/scripts/"
    "run_ashare_champion_applicability_map_cycle_019_reconciliation.py"
)
RESULT = (
    ROOT / "research/market_behavior_os_v2/artifacts/"
    "ASHARE-CHAMPION-APPLICABILITY-MAP-CYCLE-019_reconciliation_result.json"
)


def _module():
    spec = importlib.util.spec_from_file_location("cycle019_reconciliation_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_reconciliation_is_explicitly_post_outcome_and_non_mutating() -> None:
    spec = _module()._load_spec()
    assert spec["status"] == "POST_OUTCOME_SCOPE_RECONCILIATION_NOT_PREREGISTRATION"
    assert spec["actual_reconciliation_checkpoint"] == "a113a1bb9d"
    assert spec["scientific_boundary"] == {
        "original_outcomes_already_inspected": True,
        "new_feature_or_outcome_computation": False,
        "new_threshold_or_map_search": False,
        "original_frozen_spec_modified": False,
        "original_evidence_modified": False,
        "deployment_rule_authorized": False,
        "champion_change_authorized": False,
    }


def test_revised_scope_keeps_only_absolute_state_by_synchronization() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    assert result["classification"] == "PARTIALLY_IDENTIFIABLE_HABITAT"
    assert result["authorized_map"] == "ABSOLUTE_MARKET_STATE_X_SYNCHRONIZATION"
    assert len(result["authorized_map_rows"]) == 9
    assert {row["map"] for row in result["authorized_map_rows"]} == {
        "ABSOLUTE_MARKET_STATE_X_SYNCHRONIZATION"
    }
    assert result["conditional_map_not_authorized"] == [
        "ABSOLUTE_MARKET_STATE",
        "CROSS_SECTIONAL_DISPERSION",
    ]


def test_revised_taxonomy_and_no_deployment_are_preserved() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    classifications = {
        row["dimension"]: row["classification"] for row in result["single_dimensions"]
    }
    assert classifications == {
        "ABSOLUTE_MARKET_STATE": "STRONG_APPLICABILITY_INFORMATION",
        "CROSS_SECTIONAL_DISPERSION": "CHRONOLOGICALLY_UNSTABLE",
        "SYNCHRONIZATION": "WEAK_APPLICABILITY_INFORMATION",
        "INDUSTRY_PERSISTENCE": "NULL",
    }
    assert result["champion_changed"] is False
    assert result["deployment_replayed"] is False
    assert result["post_2023_read"] is False
    assert result["cy011_read"] is False
