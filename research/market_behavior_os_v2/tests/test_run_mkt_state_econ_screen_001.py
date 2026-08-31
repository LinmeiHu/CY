from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
RUNNER = PROGRAM / "scripts/run_mkt_state_econ_screen_001.py"


def _module():
    spec = importlib.util.spec_from_file_location("market_state_screen_test", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_contract_is_disclosed_explore_and_has_no_execution_claim() -> None:
    module = _module()
    spec = module._load_spec()
    assert module.sha256_file(module.SPEC_PATH) == module.EXPECTED_SPEC_SHA256
    assert spec["research_level"] == "EXPLORE"
    assert "inspected" in spec["honesty_boundary"]
    assert len(spec["fixed_candidates"]) == 6
    assert spec["decision_semantics"]["earliest_hypothetical_fill"].startswith("t+1")
    prohibited = "|".join(spec["prohibited_computations"])
    assert "same-bar execution" in prohibited
    assert "post-2023" in prohibited
    assert "CY-011" in prohibited


def test_analysis_uses_only_fixed_state_predictors() -> None:
    module = _module()
    source = inspect.getsource(module._analyze_candidate)
    assert "candidate[\"primary\"]" in source
    assert "candidate[\"response\"]" in source
    assert "_pit_3y_pct" in source
    assert "threshold" not in source
    assert module._same_sign(0.1, 1)
    assert module._same_sign(-0.1, -1)
    assert not module._same_sign(0.1, -1)


def test_completed_result_preserves_claim_boundaries_when_present() -> None:
    result_path = PROGRAM / "artifacts/MKT-STATE-ECON-SCREEN-001_result.json"
    if not result_path.exists():
        return
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["research_level"] == "EXPLORE"
    assert result["status"] == "COMPLETE_DISCLOSED_CHEAP_MARKET_STATE_ECONOMIC_SCREEN"
    assert result["ranked_candidates"][0]["candidate_id"] == (
        "LIQUIDITY_TURNOVER__OPPORTUNITY_WIDTH"
    )
    assert result["ranked_candidates"][1]["funnel_status"] == "PARKED"
    assert result["claim_boundary"]["strategy_supported"] is False
    assert result["claim_boundary"]["pnl_estimated"] is False
    assert result["claim_boundary"]["future_response_used_as_predictor"] is False
    assert result["claim_boundary"]["same_bar_fill_assumed"] is False
    assert result["claim_boundary"]["post_2023_read"] is False
    assert result["claim_boundary"]["cy011_read"] is False
