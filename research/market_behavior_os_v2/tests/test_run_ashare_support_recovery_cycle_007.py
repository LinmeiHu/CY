import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts/run_ashare_support_recovery_cycle_007.py"


def _module():
    spec = importlib.util.spec_from_file_location("cycle007_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_frozen_contract_is_prior_and_fail_closed():
    module = _module()
    spec = module._load_spec()
    assert spec["starting_checkpoint"] == "95d465131e"
    assert spec["level_contract"]["level_availability"].startswith("previous session")
    assert spec["level_contract"]["earliest_entry"].startswith("next executable")
    assert "future extrema defining levels" in spec["prohibited"]
    assert spec["fundamental_reconnaissance"]["status"] == "DATA_BLOCKED_PARKED"


def test_hypotheses_are_bounded_and_predeclare_breakdown_direction():
    module = _module()
    spec = module._load_spec()
    support = {row["id"]: row for row in spec["support_hypotheses"]}
    assert 5 <= len(support) <= 7
    assert support["confirmed_breakdown"]["direction"] == "negative_downside_predictor"
    assert spec["screen"]["maximum_bundle"] == 1
    assert spec["screen"]["maximum_support_replays"] == 2


def test_durable_result_preserves_downside_role_without_sign_inversion():
    module = _module()
    result = __import__("json").loads(module.RESULT_PATH.read_text())
    decisions = {row["family"]: row for row in result["decisions"]}
    breakdown = decisions["confirmed_breakdown"]
    assert breakdown["classification"] == "DOWNSIDE_PREDICTOR"
    assert breakdown["net_excess"] < 0
    assert breakdown["early_excess"] < 0 and breakdown["late_excess"] < 0
    assert breakdown["replay_decision"] == "NO_REPLAY"
    assert result["support_bundle"] is None
