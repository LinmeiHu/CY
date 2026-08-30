from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_support_dyn_data_002.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_support_dyn_data_002", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
retry = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(retry)


def test_exact_retry_inherits_science_and_changes_only_resource_execution() -> None:
    spec = retry._load_spec()
    control = spec["_retry_control"]
    assert retry.sha256_file(retry.SPEC_PATH) == retry.EXPECTED_SPEC_SHA256
    assert retry.sha256_file(retry.PARENT_RUNNER) == control["inputs"]["parent_runner"]["sha256"]
    assert control["invalid_parent"]["outputs_accepted"] is False
    assert control["invalid_parent"]["minute_rows_read"] == 0
    assert spec["sample"]["expected_sequences"] == 1920
    assert spec["sample_adequacy_gates"]["minimum_repeated_test_sequences"] == 120
    assert spec["resource_budget"]["peak_rss_ceiling_gib"] == 3
    assert spec["resource_budget"]["temporary_disk_ceiling_gib"] == 10


def test_parent_spec_verification_survives_output_path_rebinding() -> None:
    original = retry.parent.SPEC_PATH
    retry.parent.SPEC_PATH = retry.SPEC_PATH
    try:
        assert retry._load_spec()["sample"]["expected_cohort_rows"] == 9600
    finally:
        retry.parent.SPEC_PATH = original


def test_completed_artifact_boundaries_when_present() -> None:
    if not retry.RESULT_PATH.exists():
        return
    result = json.loads(retry.RESULT_PATH.read_text(encoding="utf-8"))
    assert result["experiment_id"] == "MKT-SUPPORT-DYN-DATA-002"
    assert result["resource_retry"]["exact_scientific_inheritance"] is True
    assert result["resource_retry"]["spill_removed_before_minute_access"] is True
    assert result["process_estimates_constructed"] is False
    assert result["support_defense_claim"] == "NONE"
    assert result["temporal_process_claim"] == "NONE"
    assert result["future_fields_read"] == []
    assert result["strategy_or_outcome_fields_read"] == []
    assert result["post_2023_data_read"] is False
    assert result["cy011_read"] is False
    assert result["partition_content_hashes_verified"] is True
    assert retry.sha256_file(retry.SAMPLE_PATH) == result["hashes"]["sample_sha256"]
    assert (
        retry.sha256_file(retry.SUPPORT_COUNT_PATH)
        == result["hashes"]["support_count_audit_sha256"]
    )
