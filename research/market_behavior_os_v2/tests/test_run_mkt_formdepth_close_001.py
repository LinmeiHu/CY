from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
RUNNER = PROGRAM / "scripts/run_mkt_formdepth_close_001.py"


def _module():
    spec = importlib.util.spec_from_file_location(
        "run_mkt_formdepth_close_001_test", RUNNER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_closing_state_boundary() -> None:
    module = _module()
    spec = module._load_spec()
    assert module.sha256_file(module.SPEC_PATH) == module.EXPECTED_SPEC_SHA256
    assert spec["response"]["adverse_only_for_classification"] is True
    assert spec["response"]["terminal_cannot_rescue"] is True
    assert spec["response"]["equality_economically_estimated"] is False
    assert spec["activation"]["expected_complete_five_control_rows"] == 6627
    assert "CY-011" in "|".join(spec["prohibited_computations"])


def test_closing_arm_domain_is_exact_and_outcome_blind() -> None:
    result = json.loads(
        (PROGRAM / "artifacts/MKT-FORMDEPTH-CLOSE-DATA-001_result.json").read_text()
    )
    assert result["status"] == "COMPLETE_CLOSING_ARM_RESPONSE_DOMAIN_ADEQUACY"
    assert result["response_domain"]["closing_topology_complete_cells"] == 11272
    assert result["response_domain"]["minimum_closing_complete_dates_per_cell_year"] == 196
    assert result["response_domain"]["exact_anchor_and_response_conservation"] is True
    assert result["scalar_reconstruction"]["cases_per_arm"] == {
        "accepted": 5,
        "equal": 5,
        "rejected": 5,
    }
    assert result["scalar_reconstruction"]["fields"] == 17
    assert result["state_outcome_estimates_computed"] is False
    assert result["closing_classification_computed"] is False


def test_downside_survives_acceptance_without_rejection_localization() -> None:
    result = json.loads(
        (PROGRAM / "artifacts/MKT-FORMDEPTH-CLOSE-001_result.json").read_text()
    )
    channels = result["evaluation"]["channels"]
    assert result["classification"] == "ACCEPTED_AND_REJECTED_CROSSER_DOWNSIDE"
    assert channels["ACCEPTED_CROSSER_DOWNSIDE"]["pass"] is True
    assert channels["REJECTED_CROSSER_DOWNSIDE"]["pass"] is True
    assert channels["REJECTED_MINUS_ACCEPTED"]["pass"] is False
    assert channels["REJECTED_MINUS_ACCEPTED"]["checks"]["primary"] is False
    assert result["terminal_can_promote"] is False
    assert result["equality_economically_estimated"] is False
    assert result["habitat_action"] == "NONE"
    assert result["strategy_fields_read"] is False
    assert result["post_2023_read"] is False
    assert result["cy011_read"] is False
