from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_support_dyn_data_004.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_support_dyn_data_004", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
retry = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(retry)


def test_final_retry_changes_only_measured_memory_limit() -> None:
    spec = retry._load_spec()
    control = spec["_retry4_control"]
    assert retry.sha256_file(retry.SPEC_PATH) == retry.EXPECTED_SPEC_SHA256
    assert retry.sha256_file(retry.PARENT_RUNNER) == control["inputs"]["parent_runner"]["sha256"]
    assert control["invalid_parent"]["outputs_accepted"] is False
    assert control["invalid_parent"]["adequacy_counts_inspected_or_accepted"] is False
    assert control["only_change"]["duckdb_daily_coordinate_memory_limit_gib_to"] == 1.5
    assert spec["sample"]["expected_cohort_rows"] == 9600
    assert spec["_retry3_control"]["only_change"]["exact_expected_complete_raw_rows"] == 2307575


def test_completed_artifact_boundaries_when_present() -> None:
    if not retry.RESULT_PATH.exists():
        return
    result = json.loads(retry.RESULT_PATH.read_text(encoding="utf-8"))
    assert result["experiment_id"] == "MKT-SUPPORT-DYN-DATA-004"
    assert result["reference_equivalence"]["exact_equal"] is True
    assert result["resource_retry"]["duckdb_memory_limit_gib"] == 1.5
    assert result["resource_retry"]["complete_raw_minute_rows"] == 2307575
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
