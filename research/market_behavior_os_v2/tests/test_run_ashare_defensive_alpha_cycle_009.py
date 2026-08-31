import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts/run_ashare_defensive_alpha_cycle_009.py"


def _module():
    spec = importlib.util.spec_from_file_location("cycle009_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_frozen_contract_is_bounded_and_requires_both_track_a_gates():
    module = _module()
    spec = module._load_spec()
    assert spec["starting_checkpoint"] == "a04fd0da98"
    assert len(spec["track_b"]) == 6
    assert spec["track_b_screen"]["maximum_replays"] == 3
    translation = spec["track_a"]["authorized_translation_only_if_both_gates_pass"]
    assert translation["role"] == "DEFENSIVE_RANKING_REFINEMENT"
    assert translation["rule"].startswith("choose the 10 highest")


def test_track_a_failed_independence_and_did_not_replay():
    module = _module()
    result = json.loads(module.RESULT_PATH.read_text())
    track_a = result["track_a"]
    assert track_a["classification"] == "COMPLEMENTARY_LOW_RISK_INFORMATION"
    assert track_a["industry_gate"] is True
    assert track_a["independence_gate"] is False
    assert track_a["translation_authorized"] is False
    assert track_a["replay"] is None
    assert track_a["final_status"] == "PARKED_AUDIT_GATE"


def test_no_track_b_family_was_promoted_or_replayed():
    module = _module()
    result = json.loads(module.RESULT_PATH.read_text())
    decisions = result["track_b"]["decisions"]
    assert len(decisions) == 6
    assert all(row["replay_decision"] == "NO_REPLAY" for row in decisions)
    assert result["replays"] == []
    assert result["input_audit"]["time_travel"] == 0
    assert result["input_audit"]["lineage_failures"] == 0
