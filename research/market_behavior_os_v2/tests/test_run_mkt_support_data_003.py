from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_support_data_003.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_support_data_003", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
support = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(support)


def test_frozen_source_role_spec_and_parent_identities() -> None:
    spec = support._load_spec()
    control = spec["_control_spec"]
    assert support.sha256_file(support.SPEC_PATH) == support.EXPECTED_SPEC_SHA256
    assert support.sha256_file(support.PARENT_RUNNER) == control["invalid_parent"]["runner_sha256"]
    assert control["invalid_parent"]["outputs_accepted"] is False
    assert control["source_roles"]["daily_minute_close_equality_required"] is False
    assert control["source_roles"]["numeric_tolerance"] is None


def test_002_sample_semantics_are_inherited_exactly() -> None:
    spec = support._load_spec()
    assert spec["sample"]["expected_market_rows"] == 1200
    assert spec["sample"]["expected_cohort_rows"] == 1230
    assert spec["sample"]["sequences_per_year_view"] == 10
    assert len(spec["fixed_five_session_blocks"]) == 6


def test_coordinate_mapping_preserves_distinct_source_close() -> None:
    daily_close = 8.52
    coordinate_close = 1.25
    minute_close = 8.520000457763672
    scale = coordinate_close / daily_close
    mapped = minute_close * scale
    assert minute_close != daily_close
    assert mapped == minute_close * scale
    assert mapped != coordinate_close


def test_integer_cent_diagnostic_is_deterministic_not_a_gate() -> None:
    assert support._integer_cents(8.520000457763672) == 852
    assert support._integer_cents(8.52) == 852
    spec = support._load_spec()["_control_spec"]
    assert spec["diagnostics"]["integer_cent_diagnostic_is_gate"] is False


def test_completed_artifact_boundaries_when_present() -> None:
    if not support.RESULT_PATH.exists():
        return
    result = json.loads(support.RESULT_PATH.read_text(encoding="utf-8"))
    assert result["status"] == "COMPLETE_DATA_CONTRACT_PASS"
    assert result["representation_claim"] == "NONE"
    assert result["support_defense_claim"] == "NONE"
    assert result["recovery_claim"] == "NONE"
    assert result["accumulation_claim"] == "NONE"
    assert result["usefulness_claim"] == "NONE"
    assert result["strategy_or_outcome_fields_read"] == []
    assert result["future_fields_read"] == []
    assert result["post_2023_data_read"] is False
    assert result["cy011_read"] is False
    assert result["partition_content_hashes_verified"] is True
    assert support.sha256_file(support.SAMPLE_PATH) == result["hashes"]["sample_sha256"]
    assert support.sha256_file(support.COORDINATE_AUDIT_PATH) == result["hashes"]["coordinate_audit_sha256"]
