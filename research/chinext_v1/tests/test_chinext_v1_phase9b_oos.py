import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / "research/chinext_v1/reports"


def test_phase9b_spec_and_results_are_frozen_and_authorized():
    spec_path = REPORTS / "chinext_v1_phase9b_oos_spec.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    assert spec["status"] == "FROZEN_BEFORE_ANY_PHASE9B_RESULT"
    assert spec["authorized_arms"] == ["O0_BASELINE", "O1_WINNER_HOLD"]
    assert spec["winner_qualification"]["min_holding_sessions"] == 20
    assert spec["winner_qualification"]["min_current_return"] == 0.2
    assert hashlib.sha256(spec_path.read_bytes()).hexdigest() == "e2265b3a3fec2e809d88b69d1884faf3b27a78df47ad617fed1fe32c07e0602d"


def test_phase9b_has_exactly_two_runs_and_frozen_inputs():
    result = json.loads((REPORTS / "chinext_v1_phase9b_oos_validation_summary.json").read_text(encoding="utf-8"))
    assert result["phase9b_result"] == "PASS"
    assert result["formal_replay_executions"] == 2
    assert result["formal_run_order"] == ["O0_BASELINE", "O1_WINNER_HOLD"]
    assert result["identity"]["strategy_sha256"] == "dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a"
    assert result["identity"]["holdout_manifest_sha256"] == "4763562dac0538961b8fa5435b7a9475d92bc6e6562faca259b6429ff86bcb43"
    assert result["winner_mechanism"] == {"min_holding_sessions": 20, "min_current_return": 0.2}
    assert result["holdout_pit_rebuilt"] == "NO"
    assert result["current_survivor_fallback"] == "NO"
    assert result["diagnostics"]["deferred_eventually_loser_count"] == 0
    assert all(item["extra_holding_sessions"] > 0 for item in result["diagnostics"]["deferred_episodes"])


def test_phase9b_execution_safety_invariants():
    result = json.loads((REPORTS / "chinext_v1_phase9b_oos_validation_summary.json").read_text(encoding="utf-8"))
    assert result["O0_BASELINE"]["same_day_fills"] == 0
    assert result["O1_WINNER_HOLD"]["same_day_fills"] == 0
    assert result["O0_BASELINE"]["stale_held_valuations"] == 0
    assert result["O1_WINNER_HOLD"]["stale_held_valuations"] == 0
    assert result["winner_hold_generalization"] in {"SUPPORTED_OOS", "PARTIALLY_SUPPORTED_OOS", "NOT_SUPPORTED_OOS", "INCONCLUSIVE"}
