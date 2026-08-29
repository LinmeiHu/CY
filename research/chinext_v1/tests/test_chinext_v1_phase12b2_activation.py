import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REPORT = ROOT / "research/chinext_v1/reports"


def load(name):
    return json.loads((REPORT / name).read_text(encoding="utf-8"))


def test_outcome_blind_fail_closed():
    s = load("chinext_v1_phase12b2_activation_summary.json")
    assert s["formal_replay_executions"] == 0
    assert s["new_strategy_trades"] == 0
    assert s["new_strategy_nav"] == 0
    assert s["no_performance_metrics_computed"] is True
    assert s["pit_full_materialization"] == "NO"
    assert s["formal_replay_authorized"] == "NO"


def test_qd001_coverage_and_overlap_are_frozen():
    s = load("chinext_v1_phase12b2_activation_summary.json")
    assert s["qd001_has_2017_warmup"] == "YES"
    assert s["qd001_has_2018_overlap"] == "YES"
    assert s["overlap_rows_compared"] == 176414
    assert s["price_within_tolerance_rate"] == 1.0
    assert s["volume_exact_match_rate"] == 1.0
    assert s["turnover_exact_match_rate"] == 1.0
    assert s["corporate_action_event_alignment_rate"] == "UNAVAILABLE"
    assert s["can_rebase_qd001_to_cy006_causal_semantics"] == "NO"


def test_authorization_and_pilot_fail_closed():
    s = load("chinext_v1_phase12b2_activation_summary.json")
    assert s["universe_technically_ready"] == "NO"
    assert s["warmup_data_technically_ready"] == "NO"
    assert s["universe_authorization_valid"] == "NO"
    assert s["warmup_authorization_valid"] == "NO"
    p = load("chinext_v1_phase12b2_validation_pilot.json")
    assert p["materialized"] is False
    assert len(p["dates"]) == 8
    assert all(x["symbol_count"] is None and x["symbol_set_digest"] is None for x in p["dates"])


def test_strategy_and_qd007_identity():
    s = load("chinext_v1_phase12b2_activation_summary.json")
    strategy = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"
    assert hashlib.sha256(strategy.read_bytes()).hexdigest() == "dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a"
    assert s["strategy_modified"] == "NO"
