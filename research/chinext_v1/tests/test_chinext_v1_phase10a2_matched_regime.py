import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / "research/chinext_v1/reports"


def test_phase10a2_zero_replay_and_frozen_inputs():
    d = json.loads((REPORTS / "chinext_v1_phase10a2_matched_regime_summary.json").read_text())
    assert d["phase10a2_result"] == "PASS"
    assert d["formal_replay_executions"] == 0
    assert d["new_trades"] == 0
    assert d["new_nav"] == 0
    assert d["pit_rebuilt"] == "NO"
    assert d["strategy_modified"] == "NO"
    assert d["phase10a_input_spec_sha256"] == "eef08f1af256d8908658cf5d7c518b1871cf16dddbf73f5c85c253a02617461e"
    assert d["strategy_sha256"] == "dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a"


def test_phase10a2_spec_and_match_constraints():
    spec_path = REPORTS / "chinext_v1_phase10a2_matched_regime_spec.json"
    spec = json.loads(spec_path.read_text())
    d = json.loads((REPORTS / "chinext_v1_phase10a2_matched_regime_summary.json").read_text())
    assert spec["status"] == "FROZEN_BEFORE_RESULTS"
    assert d["phase10a2_spec_sha256"] == hashlib.sha256(spec_path.read_bytes()).hexdigest()
    assert d["temporal_matching"]["matched_right_tail_20_episodes"] == 33
    assert d["temporal_matching"]["max_date_distance_days"] <= 30
    pairs = d["matched_pairs"]
    assert len(pairs) == len({p["control_episode_id"] for p in pairs})
    assert all(p["date_distance_days"] <= 30 for p in pairs)
    assert all(p["right_tail_date"][:4] == p["control_date"][:4] for p in pairs)


def test_phase10a2_outcome_boundaries_and_direction():
    d = json.loads((REPORTS / "chinext_v1_phase10a2_matched_regime_summary.json").read_text())
    for year in ("2022", "2023", "2024", "2025"):
        c = d["within_year"][year]["counts"]
        assert c["right_tail_20"] + c["non_right_tail_20"] == d["within_year"][year]["right_tail_20"]["close"]["right_tail"]["count"] + d["within_year"][year]["right_tail_20"]["close"]["control"]["count"]
    assert d["classification"]["does_regime_signal_survive_within_period_controls"] in {"YES", "PARTIALLY", "NO", "INCONCLUSIVE"}
    assert d["classification"]["next_research_direction"] != "PRE_REGISTER_SIMPLE_REGIME_ADMISSION_EXPERIMENT"
