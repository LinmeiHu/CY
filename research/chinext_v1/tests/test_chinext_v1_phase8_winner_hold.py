import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def test_phase8_spec_is_frozen_and_thresholds_are_exact() -> None:
    spec = json.loads((REPORTS / "chinext_v1_phase8_winner_hold_spec.json").read_text())
    assert spec["status"] == "FROZEN_BEFORE_ANY_REPLAY_RESULT"
    assert spec["formal_run_order"] == ["W1_WINNER_HOLD_THROUGH_MARKET_EXIT"]
    assert spec["winner_qualification"]["min_holding_sessions"] == 20
    assert spec["winner_qualification"]["min_current_return"] == 0.2
    assert spec["winner_qualification"]["future_mfe_or_top20_used"] is False


def test_phase8_result_and_frozen_inputs() -> None:
    result = json.loads((REPORTS / "chinext_v1_phase8_winner_hold_summary.json").read_text())
    assert result["formal_replay_executions"] == 1
    assert result["formal_run_order"] == ["W1_WINNER_HOLD_THROUGH_MARKET_EXIT"]
    assert result["W1_WINNER_HOLD_THROUGH_MARKET_EXIT"]["trade_count"] == 109
    assert result["W1_WINNER_HOLD_THROUGH_MARKET_EXIT"]["total_return"] == 1.1475334803500004
    assert result["W1_WINNER_HOLD_THROUGH_MARKET_EXIT"]["baseline_top20_captured_count"] == 20
    assert result["winner_qualified_at_market_exit_count"] == 12
    assert result["deferred_winner_eventually_loser_count"] == 0
    assert result["identity"]["strategy_sha256"] == "dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a"
    assert result["identity"]["pit_manifest_sha256"] == "8b4519ff6cf74aa0ca13b15bd3954cce3a37f6dd19d25f3f77743e9a974e75f7"
