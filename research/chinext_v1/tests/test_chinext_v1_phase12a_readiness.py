import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3] / "research/chinext_v1"
REPORTS = ROOT / "reports"


def test_readiness_is_outcome_blind_and_blocked_before_replay():
    d = json.loads((REPORTS / "chinext_v1_phase12a_extended_history_readiness_summary.json").read_text())
    assert d["phase12a_result"] == "PASS"
    assert d["formal_replay_executions"] == 0
    assert d["no_performance_metrics_computed"] == "YES"
    assert d["can_proceed_to_2018_2021_frozen_replay"] == "NO"
    assert d["pit_rebuilt"] if "pit_rebuilt" in d else True


def test_target_dates_and_warmup_are_calendar_derived():
    d = json.loads((REPORTS / "chinext_v1_phase12a_extended_history_readiness_summary.json").read_text())
    assert d["target_date_range"] == ["2018-01-02", "2021-12-31"]
    assert d["target_trade_date_count"] == 973
    assert d["required_price_warmup_trading_days"] == 180
    assert d["required_warmup_start_date"] == "2017-04-12"
    v = json.loads((REPORTS / "chinext_v1_phase12a_validation_dates.json").read_text())
    assert len(v["dates"]) == 8
    assert v["derived_target_date_count"] == 973
    assert all(x["status"] == "BLOCKED_NO_PIT_ARTIFACT" for x in v["dates"])


def test_governance_and_readiness_gates_fail_closed():
    d = json.loads((REPORTS / "chinext_v1_phase12a_extended_history_readiness_summary.json").read_text())
    assert d["qd007_status"] == "DISCOVERY_ONLY"
    assert d["can_build_2018_2021_pit_universe"] == "NO"
    assert d["extended_history_governance_status"] == "DATA_ASSET_REGISTRATION_REQUIRED"
    assert d["readiness_gates"]["universe_ready"] == "NO"
    assert d["readiness_gates"]["governance_ready"] == "NO"
    assert d["readiness_gates"]["market_anchor_ready"] == "YES"


def test_frozen_strategy_and_existing_manifests_unchanged():
    d = json.loads((REPORTS / "chinext_v1_phase12a_extended_history_readiness_summary.json").read_text())
    assert d["strategy_sha256"] == "dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a"
    assert d["strategy_modified"] == "NO"
    assert d["existing_pit_artifacts_unchanged"] == "YES"
    assert d["current_survivor_fallback"] if "current_survivor_fallback" in d else True


def test_source_partitions_and_semantics():
    d = json.loads((REPORTS / "chinext_v1_phase12a_extended_history_readiness_summary.json").read_text())
    assert d["price_adjustment_semantics"].startswith("raw/unadjusted")
    assert d["semantics_match_existing_baseline"] == "YES"
    assert d["volume_semantics_match"].startswith("YES")
    assert d["turnover_semantics_match"].startswith("YES")
    assert d["source_daily_coverage_by_year"]["2017"]["partition_exists"] is False
    for y in ("2018", "2019", "2020", "2021"):
        assert d["source_daily_coverage_by_year"][y]["partition_exists"] is True
