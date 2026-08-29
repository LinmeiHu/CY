import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / "research/chinext_v1/reports"


def test_phase9c_is_zero_replay_and_consumes_frozen_inputs():
    d = json.loads((REPORTS / "chinext_v1_phase9c_oos_failure_attribution_summary.json").read_text())
    assert d["phase9c_result"] == "PASS"
    assert d["formal_replay_executions"] == 0
    assert d["new_trades"] == 0
    assert d["new_nav"] == 0
    assert d["pit_rebuilt"] == "NO"
    assert d["oos_status_after_phase9b"] == "CONSUMED_FOR_DIAGNOSTIC_ANALYSIS"
    assert d["identity"]["strategy_sha256"] == "dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a"
    assert d["identity"]["development_pit_manifest_sha256"] == hashlib.sha256((REPORTS / "chinext_v1_pit_master_manifest.json").read_bytes()).hexdigest()
    assert d["identity"]["holdout_manifest_sha256"] == hashlib.sha256((REPORTS / "chinext_v1_pit_holdout_2022_2023_master_manifest.json").read_bytes()).hexdigest()


def test_phase9c_year_assignment_and_classification():
    d = json.loads((REPORTS / "chinext_v1_phase9c_oos_failure_attribution_summary.json").read_text())
    assert set(d["yearly"]) == {"2022", "2023", "2024", "2025"}
    assert d["yearly"]["2022"]["trade_count"] == 37
    assert d["yearly"]["2023"]["trade_count"] == 57
    assert d["yearly"]["2024"]["trade_count"] == 38
    assert d["yearly"]["2025"]["trade_count"] == 73
    assert d["failure_classification"]["primary"] in {"RIGHT_TAIL_SCARCITY", "BREAKOUT_CONTINUATION_FAILURE", "EARLY_LOSER_SEVERITY", "MARKET_REGIME_DEPENDENCE", "EXIT_PATH_MISMATCH", "OPPORTUNITY_SCARCITY", "MIXED", "INCONCLUSIVE"}
    assert d["failure_classification"]["cross_regime_generalization"] == "NOT_SUPPORTED"


def test_phase9c_path_diagnostics_are_descriptive_only():
    d = json.loads((REPORTS / "chinext_v1_phase9c_oos_failure_attribution_summary.json").read_text())
    assert d["exit_path"]["status"] == "PARTIAL_DESCRIPTIVE"
    assert d["feature_stability"]["turnover20_mean_status"].startswith("UNRESOLVED")
