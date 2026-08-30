from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_early_path_reversal as reversal


def test_feature_contract_is_one_fixed_day5_reversal() -> None:
    assert reversal.OUTPUT_TABLE.name == "early_path_reversal.csv"
    assert "return_5d" not in reversal.BASE_CONTROLS
    assert len(reversal.BASE_CONTROLS) == 10


def test_action_defaults_fail_closed_without_silent_nan() -> None:
    assert reversal.finite_or_default(float("nan"), 0.0) == 0.0
    assert reversal.finite_or_default(None, 1.0) == 1.0


def test_frozen_result_rejects_future_failure_mechanism() -> None:
    result = json.loads(reversal.OUTPUT_JSON.read_text())
    primary = result["primary"]
    assert result["decision"] == "REJECT"
    assert result["audit"]["survivor_cycles"] == 295
    assert result["audit"]["return5_max_abs_reconstruction_error"] <= 1e-12
    assert primary["raw"]["rho"] < 0.10
    assert primary["controlled_beyond_day5"]["partial_rank_rho"] < 0.10
    assert primary["false_breakout"]["rho"] >= 0.10
    assert primary["h016_topology"]["rho"] >= 0.10
    assert primary["raw_gate"] is False
    assert primary["controlled_gate"] is False
