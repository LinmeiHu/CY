from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
RUNNER = PROGRAM / "scripts/run_mkt_state_robust_001.py"


def _module():
    spec = importlib.util.spec_from_file_location("market_state_robust_test", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_candidates_exactly_match_screen_survivors() -> None:
    module = _module()
    spec = module._load_spec()
    screen = json.loads(
        (PROGRAM / "artifacts/MKT-STATE-ECON-SCREEN-001_result.json").read_text()
    )
    assert {item["candidate_id"] for item in spec["fixed_candidates"]} == set(
        screen["passing_candidate_ids"]
    )
    assert spec["estimator"]["no_variable_selection"] is True
    assert spec["decision_semantics"]["earliest_hypothetical_fill"].startswith("t+1")


def test_partial_estimator_removes_fixed_rank_control_channel() -> None:
    module = _module()
    size = 1000
    random = np.random.default_rng(12)
    control = np.arange(size, dtype=float)
    frame = pd.DataFrame(
        {
            "predictor": control + random.normal(0, 100, size),
            "response": control + random.normal(0, 100, size),
            "control": control,
        }
    )
    estimate, observations = module._partial(
        frame, "predictor", "response", ["control"]
    )
    assert observations == size
    assert abs(estimate) < 0.2


def test_completed_result_has_no_strategy_claim_when_present() -> None:
    result_path = PROGRAM / "artifacts/MKT-STATE-ROBUST-001_result.json"
    if not result_path.exists():
        return
    result = json.loads(result_path.read_text())
    assert result["status"] == "COMPLETE_CHEAP_INCREMENTAL_ROBUSTNESS"
    assert result["ranked_candidates"][0]["candidate_id"] == (
        "LIQUIDITY_TURNOVER__OPPORTUNITY_WIDTH"
    )
    assert result["claim_boundary"]["independent_confirmation"] is False
    assert result["claim_boundary"]["strategy_supported"] is False
    assert result["claim_boundary"]["pnl_estimated"] is False
    assert result["claim_boundary"]["same_bar_fill_assumed"] is False
    assert result["claim_boundary"]["post_2023_read"] is False
    assert result["claim_boundary"]["cy011_read"] is False
