import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / "research/chinext_v1/reports"


def test_phase10a_zero_replay_and_frozen_identities():
    d = json.loads((REPORTS / "chinext_v1_phase10a_regime_audit_summary.json").read_text())
    assert d["phase10a_result"] == "PASS"
    assert d["formal_replay_executions"] == 0
    assert d["new_trades"] == 0
    assert d["new_nav"] == 0
    assert d["pit_rebuilt"] == "NO"
    assert d["strategy_modified"] == "NO"
    assert d["strategy_sha256"] == "dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a"
    assert d["development_pit_manifest_sha256"] == hashlib.sha256((REPORTS / "chinext_v1_pit_master_manifest.json").read_bytes()).hexdigest()
    assert d["holdout_pit_manifest_sha256"] == hashlib.sha256((REPORTS / "chinext_v1_pit_holdout_2022_2023_master_manifest.json").read_bytes()).hexdigest()


def test_phase10a_feature_spec_and_years():
    spec = json.loads((REPORTS / "chinext_v1_phase10a_regime_feature_spec.json").read_text())
    d = json.loads((REPORTS / "chinext_v1_phase10a_regime_audit_summary.json").read_text())
    assert spec["status"] == "FROZEN_BEFORE_OUTCOME_ANALYSIS"
    assert d["feature_spec_sha256"] == hashlib.sha256((REPORTS / "chinext_v1_phase10a_regime_feature_spec.json").read_bytes()).hexdigest()
    assert set(d["yearly"]) == {"2022", "2023", "2024", "2025"}
    assert d["entry_episode_count"]["oos"] == 94
    assert d["entry_episode_count"]["development"] == 111
    assert d["breadth_status"] == "NOT_AVAILABLE_UNDER_CURRENT_GOVERNANCE"


def test_phase10a_causal_and_outcome_boundaries():
    d = json.loads((REPORTS / "chinext_v1_phase10a_regime_audit_summary.json").read_text())
    assert d["classification"]["does_causal_regime_signal_exist_descriptively"] in {"SUPPORTED", "PARTIALLY_SUPPORTED", "NOT_SUPPORTED", "INCONCLUSIVE"}
    assert d["classification"]["next_research_direction"] == "MORE_REGIME_DIAGNOSTICS_REQUIRED"
    assert d["outcome_group_counts"]["right_tail_20"] >= d["outcome_group_counts"]["right_tail_50"]
    assert d["outcome_group_counts"]["right_tail_50"] >= d["outcome_group_counts"]["right_tail_100"]
