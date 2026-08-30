from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_support_dyn_data_003.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_support_dyn_data_003", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
retry = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(retry)


def test_exact_block_retry_inherits_sample_and_gates() -> None:
    spec = retry._load_spec()
    control = spec["_retry3_control"]
    assert retry.sha256_file(retry.SPEC_PATH) == retry.EXPECTED_SPEC_SHA256
    assert retry.sha256_file(retry.PARENT_RUNNER) == control["inputs"]["parent_runner"]["sha256"]
    assert control["invalid_parent"]["outputs_accepted"] is False
    assert control["invalid_parent"]["adequacy_counts_inspected_or_accepted"] is False
    assert spec["sample"]["expected_sequences"] == 1920
    assert spec["sample_adequacy_gates"]["minimum_recovered_sequences"] == 100
    assert control["only_change"]["exact_expected_complete_raw_rows"] == 2307575


def test_batch_spec_changes_only_expected_population() -> None:
    spec = retry._load_spec()
    frame = pd.DataFrame(
        {
            "symbol": ["000001.SZ", "000001.SZ", "000002.SZ"],
            "trade_date": pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-01"]),
        }
    )
    batch = retry._batch_spec(spec, frame)
    assert batch["sample"]["expected_cohort_rows"] == 3
    assert batch["sample"]["expected_unique_security_sessions"] == 3
    assert batch["sample_adequacy_gates"] == spec["sample_adequacy_gates"]


def test_canonical_frame_hash_is_order_invariant_after_audit_sort() -> None:
    frame = pd.DataFrame({"audit_id": ["b", "a"], "value": [2.0, 1.0]})
    assert retry._canonical_frame_hash(frame) == retry._canonical_frame_hash(frame.iloc[::-1])


def test_completed_artifact_boundaries_when_present() -> None:
    if not retry.RESULT_PATH.exists():
        return
    result = json.loads(retry.RESULT_PATH.read_text(encoding="utf-8"))
    assert result["experiment_id"] == "MKT-SUPPORT-DYN-DATA-003"
    assert result["reference_equivalence"]["exact_equal"] is True
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
