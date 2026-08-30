from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_support_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_support_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
support = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(support)


def test_frozen_representation_spec_and_inputs() -> None:
    spec = support._load_spec()
    assert support.sha256_file(support.SPEC_PATH) == support.EXPECTED_SPEC_SHA256
    assert spec["outcome_access"] is False
    assert spec["level_definitions"]["near_touch_threshold"] is None
    assert spec["trajectory"]["conditional_recovery_minimum_sequences"] == 30
    assert spec["trajectory"]["known_prefreeze_primary_sequences_with_at_least_two_tests"] == 29


def _toy_rows() -> pd.DataFrame:
    rows = pd.DataFrame({
        "mapped_low": np.full(241, 11.0),
        "mapped_close": np.full(241, 11.0),
        "volume": np.ones(241),
    })
    rows.loc[[1, 239], "mapped_low"] = 9.0
    rows.loc[1, "mapped_close"] = 10.0
    rows.loc[240, "mapped_close"] = 9.5
    return rows


def test_session_descriptor_separates_test_recurrence_and_recovery() -> None:
    values = support._session_descriptor(_toy_rows(), 10.0, include_auction=True)
    assert values["tested"] is True
    assert values["test_recurrence"] == 2
    assert values["recovery_completion"] is True
    assert values["recovery_speed"] == 0
    assert values["recovery_volume_intensity"] == 1.0
    assert values["closing_level_state"] == 9.5 / 10.0 - 1.0


def test_unrecovered_speed_remains_missing() -> None:
    rows = _toy_rows()
    rows.loc[1:, "mapped_close"] = 9.7
    values = support._session_descriptor(rows, 10.0, include_auction=True)
    assert values["recovery_completion"] is False
    assert np.isnan(values["recovery_speed"])
    assert np.isnan(values["recovery_volume_intensity"])


def test_constant_ordinal_trajectory_remains_undefined() -> None:
    slope, endpoint, ordinal = support._trajectory_values(np.zeros(5))
    assert slope == 0.0
    assert endpoint == 0.0
    assert np.isnan(ordinal)


def test_completed_artifact_boundaries_when_present() -> None:
    if not support.RESULT_PATH.exists():
        return
    result = json.loads(support.RESULT_PATH.read_text(encoding="utf-8"))
    assert result["support_defense_claim"] == "NONE"
    assert result["accumulation_or_distribution_claim"] == "NONE"
    assert result["usefulness_claim"] == "NONE"
    assert result["pit_historical_coordinate"] == "UNAVAILABLE_NOT_FABRICATED"
    assert result["future_fields_read"] == []
    assert result["strategy_or_outcome_fields_read"] == []
    assert result["post_2023_data_read"] is False
    assert result["cy011_read"] is False
    assert result["partition_content_hashes_verified"] is True
    manual_ids = [case["audit_id"] for case in result["manual_case_audit"]["cases"].values()]
    assert len(manual_ids) == 5
    assert len(set(manual_ids)) == 5
    assert support.sha256_file(support.SESSION_PATH) == result["hashes"]["session_panel_sha256"]
    assert support.sha256_file(support.TRAJECTORY_PATH) == result["hashes"]["trajectory_panel_sha256"]
