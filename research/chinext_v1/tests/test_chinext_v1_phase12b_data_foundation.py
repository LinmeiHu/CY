import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
REPORT = ROOT / "research/chinext_v1/reports"
STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"


def load(name):
    return json.loads((REPORT / name).read_text(encoding="utf-8"))


def test_phase12b_is_outcome_blind_and_blocked_without_replay():
    s = load("chinext_v1_phase12b_data_foundation_summary.json")
    assert s["formal_replay_executions"] == 0
    assert s["new_strategy_trades"] == 0
    assert s["new_strategy_nav"] == 0
    assert s["no_performance_metrics_computed"] is True
    assert s["pit_full_materialization"] == "NO"
    assert s["formal_replay_authorized"] == "NO"
    assert s["full_materialization_authorized"] == "NO"


def test_frozen_dates_and_warmup_are_unchanged():
    s = load("chinext_v1_phase12b_data_foundation_summary.json")
    assert s["target_date_range"] == ["2018-01-02", "2021-12-31"]
    assert s["target_trade_date_count"] == 973
    assert s["required_price_warmup_trading_days"] == 180
    assert s["required_warmup_start_date"] == "2017-04-12"
    assert s["validation_dates"] == [
        "2018-01-02", "2018-06-29", "2019-01-02", "2019-06-28",
        "2020-01-02", "2020-06-30", "2021-01-04", "2021-06-30",
    ]


def test_strategy_identity_and_fail_closed_gates():
    s = load("chinext_v1_phase12b_data_foundation_summary.json")
    digest = hashlib.sha256(STRATEGY.read_bytes()).hexdigest()
    assert digest == "dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a"
    assert s["strategy_sha256"] == digest
    assert s["strategy_modified"] == "NO"
    assert s["readiness_gates"]["extended_universe_ready"] == "NO"
    assert s["readiness_gates"]["history_window_ready"] == "NO"
    assert s["readiness_gates"]["governance_ready"] == "NO"
    assert s["qd007_status"] == "DISCOVERY_ONLY"


def test_pilot_has_exact_frozen_dates_and_no_sets():
    p = load("chinext_v1_phase12b_validation_pilot.json")
    assert p["materialized"] is False
    assert len(p["dates"]) == 8
    assert all(row["symbol_count"] is None for row in p["dates"])
    assert all(row["set_digest"] is None for row in p["dates"])
    assert all(row["validation_status"] == "BLOCKED_NO_AUTHORIZED_PIT_ARTIFACT" for row in p["dates"])


def test_no_current_survivor_and_warmup_is_not_authorized():
    spec = load("chinext_v1_phase12b_data_foundation_spec.json")
    assert spec["extended_universe_source"]["current_survivor_fallback"] is False
    assert spec["authorization"]["id"] is None
    assert spec["authorization"]["status"] == "NOT_CREATED_DATA_GOVERNANCE_BLOCKED"
