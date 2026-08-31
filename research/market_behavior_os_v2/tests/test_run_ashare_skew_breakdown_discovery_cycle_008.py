import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts/run_ashare_skew_breakdown_discovery_cycle_008.py"


def _module():
    spec = importlib.util.spec_from_file_location("cycle008_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_frozen_contract_has_one_breakdown_role_and_bounded_track_c():
    module = _module()
    spec = module._load_spec()
    assert spec["starting_checkpoint"] == "15215df615"
    assert spec["track_b"]["role"] == "CHINEXT_V1_NEW_ADMISSION_AVOIDANCE"
    assert spec["track_b"]["alternative_exit_role"] == "PROHIBITED_UNOPENED"
    assert "previous 20 completed sessions" in spec["track_b"]["condition"]
    assert 4 <= len(spec["track_c"]) <= 6
    assert spec["track_c_screen"]["maximum_replays"] == 2


def test_result_preserves_incremental_and_no_opportunity_decisions():
    module = _module()
    result = json.loads(module.RESULT_PATH.read_text())
    assert result["track_a"]["classification"] == "COMPLEMENTARY_DEFENSIVE_INFORMATION"
    assert result["track_a"]["replay"] is None
    assert result["track_b"]["classification"] == "PARKED_NO_AFFECTED_DECISIONS"
    comparisons = result["track_b"]["comparisons"].values()
    assert sum(row["audit"]["vetoed_candidate_count"] for row in comparisons) == 0
    assert result["track_b"]["alternative_exit_role_opened"] is False


def test_only_frozen_track_c_survivor_replayed():
    module = _module()
    result = json.loads(module.RESULT_PATH.read_text())
    replays = result["track_c"]["replays"]
    assert [row["family"] for row in replays] == ["low_volatility_of_volatility_60"]
    assert replays[0]["classification"] == "PROMISING_BUT_MIXED"
    assert replays[0]["terminal_open_lots"] == 0
    assert replays[0]["entry_execution_fraction"] >= 0.90
