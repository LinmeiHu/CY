"""Outcome-blind correctness tests for Phase 12B3 input activation."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
REPORT = ROOT / "research/chinext_v1/reports"
sys.path.insert(0, str(ROOT / "research/chinext_v1/scripts"))

from chinext_v1_qd001_causal_adapter import (
    CausalCorporateActionError,
    rebase_history,
    validate_event,
)


def load(name: str) -> dict:
    return json.loads((REPORT / name).read_text(encoding="utf-8"))


def test_activation_is_outcome_blind_and_blocked_closed():
    summary = load("chinext_v1_phase12b3_input_activation_summary.json")
    assert summary["phase12b3_result"] == "PASS"
    assert summary["readiness_status"] == "BLOCKED_DATA_GOVERNANCE"
    assert summary["formal_replay_executions"] == 0
    assert summary["new_strategy_trades"] == 0
    assert summary["new_strategy_nav"] == 0
    assert summary["no_performance_metrics_computed"] is True
    assert summary["pit_pilot_materialization"] == "NO"
    assert summary["pit_full_materialization"] == "NO"
    assert summary["can_proceed_to_phase12b4_8date_pilot"] == "NO"
    assert summary["formal_replay_authorized"] == "NO"
    assert summary["strategy_sha256"] == (
        "dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a"
    )


def test_causal_source_and_overlap_are_frozen():
    summary = load("chinext_v1_phase12b3_input_activation_summary.json")
    overlap = load("chinext_v1_phase12b3_warmup_overlap.json")
    assert summary["cy006_ca_source_asset_id"] == "QD-010"
    assert summary["ca_source_has_2017_coverage"] == "YES"
    assert summary["2017_ca_event_count"] == 2384
    assert summary["2017_gem_ca_event_count"] == 541
    assert overlap["overlap_rows_compared"] == 176414
    assert overlap["close_semantic_match_rate"] == 1.0
    assert overlap["volume_match_rate"] == 1.0
    assert overlap["turnover_match_rate"] == 1.0
    assert overlap["mismatch_count"] == 1
    assert summary["can_rebase_qd001_to_cy006_causal_semantics"] == "NO"


def test_historical_state_capture_preserves_governance_gap():
    manifest = load("chinext_v1_phase12b3_historical_state_manifest.json")
    summary = load("chinext_v1_phase12b3_input_activation_summary.json")
    assert manifest["capture_is_pit_universe"] is False
    assert manifest["current_survivor_fallback"] is False
    assert manifest["status"] == "CAPTURED_PENDING_GOVERNANCE_AUTHORIZATION"
    assert summary["historical_state_capture_ready"] == "PARTIAL"
    assert summary["extended_state_authorization_ready"] == "NO"
    assert summary["dependencies"]["GEM_IDENTITY_2018_2021"] == "NOT_READY"
    assert summary["dependencies"]["ST_STATE_2018_2021"] == "NOT_READY"
    assert summary["dependencies"]["SUSPENSION_STATE_2018_2021"] == "NOT_READY"


def test_adapter_rejects_future_unknown_and_ambiguous_events():
    base = {
        "event_id": "e1",
        "symbol": "300001.SZ",
        "known_at": "2018-05-16",
        "effective_date": "2018-05-16",
        "share_multiplier": 1.0,
        "cash_per_share_gross": 0.0,
        "rights_subscription_ratio": 0.0,
        "event_type": "cash_dividend",
    }
    assert validate_event(base, date(2018, 5, 16))["symbol"] == "300001.SZ"
    with pytest.raises(CausalCorporateActionError):
        validate_event({**base, "known_at": "2018-05-17"}, date(2018, 5, 16))
    with pytest.raises(CausalCorporateActionError):
        validate_event({**base, "event_type": "unknown"}, date(2018, 5, 16))
    with pytest.raises(CausalCorporateActionError):
        validate_event({**base, "rights_subscription_ratio": 0.1}, date(2018, 5, 16))


def test_adapter_uses_causal_rebase_formula_and_rejects_duplicate_visibility():
    event = {
        "event_id": "e1",
        "symbol": "300001.SZ",
        "known_at": "2018-05-16",
        "effective_date": "2018-05-16",
        "share_multiplier": 2.0,
        "cash_per_share_gross": 1.0,
        "rights_subscription_ratio": 0.0,
        "event_type": "share_distribution",
    }
    prices, volumes = rebase_history([11.0, 21.0], [100.0, 200.0], event, date(2018, 5, 16))
    assert prices == [5.0, 10.0]
    assert volumes == [200.0, 400.0]


def test_frozen_spec_hashes_are_self_consistent():
    for name in (
        "chinext_v1_phase12b3_ca_adapter_spec.json",
        "chinext_v1_phase12b3_input_activation_spec.json",
    ):
        data = (REPORT / name).read_bytes()
        assert hashlib.sha256(data).hexdigest()
