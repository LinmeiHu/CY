from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_support_data_002.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_support_data_002", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
support = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(support)


def test_frozen_retry_spec_and_parent_identities() -> None:
    spec = support._load_spec()
    assert support.sha256_file(support.SPEC_PATH) == support.EXPECTED_SPEC_SHA256
    assert support.sha256_file(support.PARENT_RUNNER) == spec["parent_invalid_attempt"]["runner_sha256"]
    assert spec["parent_invalid_attempt"]["parent_outputs_accepted"] is False
    assert spec["sample"]["selection_source"].startswith("CY-006 only")


def test_sequence_hash_is_stable_and_role_separated() -> None:
    one = support._selection_hash("MARKET", 2021, "ALL_A", "000001.SZ")
    two = support._selection_hash("MARKET", 2021, "SZ_A", "000001.SZ")
    action = support._selection_hash("ACTION", 2021, "ACTION_AUDIT", "000001.SZ", "2021-06-01")
    assert one == support._selection_hash("MARKET", 2021, "ALL_A", "000001.SZ")
    assert one != two
    assert one != action


def test_sequence_selector_conserves_toy_cells() -> None:
    spec = support._load_spec()
    toy = dict(spec)
    toy["date_range"] = {"years": [2021]}
    toy["fixed_five_session_blocks"] = {"2021": spec["fixed_five_session_blocks"]["2021"]}
    toy["sample"] = dict(spec["sample"])
    toy["sample"]["market_views"] = ["ALL_A"]
    toy["sample"]["sequences_per_year_view"] = 2
    toy["sample"]["expected_market_rows"] = 10
    dates = pd.to_datetime(toy["fixed_five_session_blocks"]["2021"])
    eligible = pd.DataFrame(
        [(date, symbol) for symbol in ["000001.SZ", "600001.SH", "600002.SH"] for date in dates],
        columns=["trade_date", "symbol"],
    )
    selected = support._select_market_sequences(eligible, toy)
    assert len(selected) == 10
    assert selected["symbol"].nunique() == 2
    assert selected.groupby("symbol")["trade_date"].nunique().eq(5).all()


def test_parent_minute_grid_contract_remains_exact() -> None:
    minutes = support.adapter.EXPECTED_MINUTES.tolist()
    assert len(minutes) == 241
    assert minutes[0] == 9 * 60 + 30
    assert 12 * 60 not in minutes
    assert minutes[-1] == 15 * 60


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
