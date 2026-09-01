# ruff: noqa: E501
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT
    / "research/market_behavior_os_v2/scripts/run_ashare_champion_breakdown_exit_cycle_020.py"
)
SPEC = (
    ROOT
    / "research/market_behavior_os_v2/experiments/ASHARE-CHAMPION-BREAKDOWN-EXIT-CYCLE-020_spec.json"
)
RESULT = (
    ROOT
    / "research/market_behavior_os_v2/artifacts/ASHARE-CHAMPION-BREAKDOWN-EXIT-CYCLE-020_result.json"
)


def _module():
    module_spec = importlib.util.spec_from_file_location("cycle020_test_module", SCRIPT)
    assert module_spec is not None and module_spec.loader is not None
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    return module


def test_frozen_signal_is_close_confirmed_and_cannot_fill_same_day():
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    signal = spec["recovered_confirmed_breakdown"]
    execution = spec["event_and_execution"]
    assert signal["support_level"].startswith("minimum causal-coordinate low")
    assert signal["breakdown_condition"] == (
        "event-date causal-coordinate close strictly below the frozen prior-L20 support"
    )
    assert signal["confirmation"].startswith("the completed event-session close")
    assert execution["event_day_intraday_fill"] is False
    assert execution["same_bar_fill"] is False
    assert execution["earliest_fill"].startswith("next session open")


def test_phase_b_stops_replay_when_remaining_payoff_is_positive():
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    assert result["status"] == "COMPLETE_PHASE_B_STOP_NO_REPLAY"
    assert result["phase_a"]["passes"] is True
    assert result["phase_b"]["passes"] is False
    assert result["phase_c"]["authorized"] is False
    assert result["final_classification"] == "BREAKDOWN_NOT_USEFUL_AS_EXIT"
    summary = result["phase_b"]["summary"]
    assert summary["full"]["remaining_payoff"]["mean"] > 0
    assert summary["early_2018_2021"]["remaining_payoff"]["mean"] > 0
    assert summary["late_2022_2023"]["remaining_payoff"]["mean"] > 0
    assert summary["early_2018_2021"]["matched_diff_remaining_payoff"]["mean"] < 0
    assert summary["late_2022_2023"]["matched_diff_remaining_payoff"]["mean"] > 0


def test_result_artifact_hashes_and_boundaries():
    module = _module()
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    for binding in result["artifacts"].values():
        path = ROOT / binding["path"]
        assert path.is_file()
        assert module.sha256_file(path) == binding["sha256"]
    external = result["external_artifacts"]["breakdown_event_panel.parquet"]
    assert module.sha256_file(Path(external["path"])) == external["sha256"]
    assert external["rows"] == result["phase_a"]["summary"]["affected_lots"]
    assert result["boundaries"] == {
        "cost_grid_run": False,
        "cy011_read": False,
        "entry_engine_changed": False,
        "event_day_intraday_fill": False,
        "minute_crossing_used": False,
        "oos_claim": False,
        "post_2023_read": False,
        "reentry_rule_added": False,
        "support_definition_changed": False,
    }
