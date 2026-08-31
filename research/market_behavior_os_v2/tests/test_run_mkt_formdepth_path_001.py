from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
RUNNER = PROGRAM / "scripts/run_mkt_formdepth_path_001.py"


def _module():
    spec = importlib.util.spec_from_file_location(
        "run_mkt_formdepth_path_001_test", RUNNER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_path_timing_boundary() -> None:
    module = _module()
    spec = module._load_spec()
    assert module.sha256_file(module.SPEC_PATH) == module.EXPECTED_SPEC_SHA256
    assert spec["response"]["classifying_channels"] == [
        "PREOPEN_PATH_DOWNSIDE",
        "TROUGH_SESSION_INTRADAY_DOWNSIDE",
    ]
    assert spec["response"]["diagnostics_cannot_rescue"] is True
    assert spec["activation"]["expected_complete_five_control_rows"] == 6627
    assert "CY-011" in "|".join(spec["prohibited_computations"])


def test_path_component_domain_is_exact_and_outcome_blind() -> None:
    result = json.loads(
        (PROGRAM / "artifacts/MKT-FORMDEPTH-PATH-DATA-001_result.json").read_text()
    )
    assert result["status"] == "COMPLETE_ADVERSE_PATH_COMPONENT_DOMAIN_ADEQUACY"
    assert result["response_domain"]["path_topology_complete_cells"] == 11272
    assert result["response_domain"]["minimum_path_complete_dates_per_cell_year"] == 196
    assert result["response_domain"]["exact_bound_arm_counts_and_exhaustion"] is True
    assert result["scalar_reconstruction"]["cases_per_arm"] == {
        "accepted": 5,
        "equal": 5,
        "rejected": 5,
    }
    assert result["scalar_reconstruction"]["fields"] == 37
    assert result["component_association_computed"] is False
    assert result["timing_classification_computed"] is False
    assert result["future_components_used_as_predictors"] is False


def test_mixed_timing_classification_keeps_recovery_diagnostic() -> None:
    result = json.loads(
        (PROGRAM / "artifacts/MKT-FORMDEPTH-PATH-001_result.json").read_text()
    )
    channels = result["evaluation"]["channels"]
    assert result["classification"] == "MIXED_PREOPEN_AND_INTRADAY_DOWNSIDE_PATH"
    assert channels["PREOPEN_PATH_DOWNSIDE"]["pass"] is True
    assert channels["TROUGH_SESSION_INTRADAY_DOWNSIDE"]["pass"] is True
    assert channels["POST_TROUGH_RECOVERY_DIAGNOSTIC"]["pass"] is None
    assert channels["PREOPEN_PATH_DOWNSIDE"]["checks"]["closing_arms"] is True
    assert channels["TROUGH_SESSION_INTRADAY_DOWNSIDE"]["checks"]["closing_arms"] is True
    assert result["recovery_can_promote"] is False
    assert result["terminal_can_promote"] is False
    assert result["future_components_used_as_predictors"] is False
    assert result["strategy_fields_read"] is False
    assert result["post_2023_read"] is False
    assert result["cy011_read"] is False
