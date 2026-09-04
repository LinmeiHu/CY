from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
RUNNER = SCRIPTS / "run_ashare_bull_leader_pullback_reacceleration_v2.py"
SPEC = importlib.util.spec_from_file_location("bull_pullback_v2", RUNNER)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_contract_is_bull_industry_pullback_not_gap_repair() -> None:
    contract = MODULE.contract_value()
    assert contract["governance"]["downward_gap_identity_used"] is False
    assert "positive-ret20 share > 0.50" in contract["industry_gate"]
    assert contract["shared_semantics"]["pullback"].startswith("previous coordinate close")
    assert contract["selection"]["mean_holding_max"] == 15


def test_rule_and_profile_spaces_are_bounded() -> None:
    assert len(MODULE.RULES) == 4
    assert len(MODULE.PROFILES) == 3
    assert set(MODULE.PROFILES) == {
        "H10_NEXT_OPEN",
        "T10_H15_NO_STOP",
        "T15_H15_NO_STOP",
    }
    for rule in MODULE.RULES.values():
        assert rule["drawdown_low"] < rule["drawdown_high"] < 0
        assert rule["runup"] > 0
        assert rule["step"] > 0
