from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_support_dyn_data_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_support_dyn_data_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
sample = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(sample)


def test_frozen_sample_spec_and_activation() -> None:
    spec = sample._load_spec()
    assert sample.sha256_file(sample.SPEC_PATH) == sample.EXPECTED_SPEC_SHA256
    assert spec["outcome_access"] is False
    assert spec["sample"]["expected_sequences"] == 1920
    assert spec["sample"]["expected_cohort_rows"] == 9600
    assert spec["resource_budget"]["planned_raw_minute_rows"] == 2307575


def test_endpoint_positions_are_exact_broad_quantiles() -> None:
    assert sample._endpoint_positions(160) == [10, 30, 50, 70, 90, 110, 130, 150]


def test_registered_calendar_constructs_exact_frozen_blocks() -> None:
    blocks = sample.construct_calendar_blocks(sample._load_spec())
    assert len(blocks) == 240
    endpoints = blocks.loc[blocks["relative_day"].eq(-1)]
    assert len(endpoints) == 48
    first = endpoints.sort_values(["target_year", "block_id"]).iloc[0]
    assert first["trade_date"] == pd.Timestamp("2018-03-16")


def test_selection_hash_includes_block_identity() -> None:
    left = sample._selection_hash(2020, 1, "ALL_A", "000001.SZ")
    right = sample._selection_hash(2020, 2, "ALL_A", "000001.SZ")
    assert left != right
    assert left == sample._selection_hash(2020, 1, "ALL_A", "000001.SZ")


def test_sample_adequacy_is_count_only_and_conjunctive() -> None:
    spec = sample._load_spec()
    rows = []
    for year in range(2018, 2024):
        for index in range(20):
            rows.append(
                {
                    "target_year": year,
                    "repeated_test_sequence": True,
                    "recovered_sequence": index < 17,
                }
            )
    result = sample.evaluate_sample_adequacy(spec, pd.DataFrame(rows))
    assert result["repeated_test_sequences"] == 120
    assert result["recovered_sequences"] == 102
    assert result["pass"] is True
    assert result["process_estimates_constructed"] is False


def test_completed_artifact_boundaries_when_present() -> None:
    if not sample.RESULT_PATH.exists():
        return
    result = json.loads(sample.RESULT_PATH.read_text(encoding="utf-8"))
    assert result["status"] in {
        "COMPLETE_SAMPLE_ADEQUACY_PASS",
        "COMPLETE_SAMPLE_INADEQUATE",
    }
    assert result["representation_claim"] == "NONE"
    assert result["support_defense_claim"] == "NONE"
    assert result["temporal_process_claim"] == "NONE"
    assert result["prediction_or_usefulness_claim"] == "NONE"
    assert result["process_estimates_constructed"] is False
    assert result["future_fields_read"] == []
    assert result["strategy_or_outcome_fields_read"] == []
    assert result["post_2023_data_read"] is False
    assert result["cy011_read"] is False
    assert result["partition_content_hashes_verified"] is True
    assert sample.sha256_file(sample.SAMPLE_PATH) == result["hashes"]["sample_sha256"]
    assert (
        sample.sha256_file(sample.SUPPORT_COUNT_PATH)
        == result["hashes"]["support_count_audit_sha256"]
    )
