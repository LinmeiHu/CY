from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_support_data_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_support_data_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
support = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(support)


def test_frozen_spec_and_inventory_entries() -> None:
    spec = support._load_spec()
    assert support.sha256_file(support.SPEC_PATH) == support.EXPECTED_SPEC_SHA256
    support._verify_registry_assets(spec)
    paths = support.bind_partitions(spec, verify_content=False)
    assert len(paths["qd004"]) == 6
    assert len(paths["cy006"]) == 6
    assert len(paths["cy008_daily"]) == 6


def test_action_bridge_formulas_are_exact_and_rights_fail_closed() -> None:
    previous_close = 10.0
    cash = 1.0
    multiplier = 2.0
    bridge = (previous_close - cash) / multiplier
    assert bridge == 4.5
    assert np.log(5.0 / bridge) == np.log(5.0 / 4.5)
    spec = support._load_spec()
    assert spec["action_coordinate"]["rights_ratio_required"] == 0
    assert spec["action_coordinate"]["chain_repair_or_fill"] is False


def test_action_selection_hash_is_stable_and_date_sensitive() -> None:
    import pandas as pd

    one = support._hash_order(2021, "000001.SZ", pd.Timestamp("2021-06-01"))
    two = support._hash_order(2021, "000001.SZ", pd.Timestamp("2021-06-02"))
    assert one == support._hash_order(2021, "000001.SZ", pd.Timestamp("2021-06-01"))
    assert one != two


def test_expected_minute_grid_has_auction_break_and_close() -> None:
    minutes = support.adapter.EXPECTED_MINUTES.tolist()
    assert len(minutes) == 241
    assert minutes[0] == 9 * 60 + 30
    assert 11 * 60 + 30 in minutes
    assert 12 * 60 not in minutes
    assert 13 * 60 + 1 in minutes
    assert minutes[-1] == 15 * 60


def test_completed_artifact_boundaries_when_present() -> None:
    if not support.RESULT_PATH.exists():
        return
    result = json.loads(support.RESULT_PATH.read_text(encoding="utf-8"))
    assert result["representation_claim"] == "NONE"
    assert result["support_defense_claim"] == "NONE"
    assert result["recovery_claim"] == "NONE"
    assert result["accumulation_claim"] == "NONE"
    assert result["usefulness_claim"] == "NONE"
    assert result["strategy_or_outcome_fields_read"] == []
    assert result["future_fields_read"] == []
    assert result["post_2023_data_read"] is False
    assert result["cy011_read"] is False
    assert support.sha256_file(support.SAMPLE_PATH) == result["hashes"]["sample_sha256"]
    assert (
        support.sha256_file(support.COORDINATE_AUDIT_PATH)
        == result["hashes"]["coordinate_audit_sha256"]
    )
