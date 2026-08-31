from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
RUNNER = PROGRAM / "scripts/run_hab_chx_minvolpath_strat_001.py"


def _module():
    spec = importlib.util.spec_from_file_location("minvolpath_strategy_test", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_contract_uses_true_1530_availability_and_no_same_bar_fill() -> None:
    module = _module()
    spec = module._load_spec()
    assert module.shared.sha256_file(module.SPEC_PATH) == module.EXPECTED_SPEC_SHA256
    assert "inspected before" in spec["honesty_boundary"]
    assert spec["state_rule"]["threshold_search"] is False
    assert spec["state_rule"]["block_new_admissions_when"] == "coordinate >= 0.80"
    assert spec["state_rule"]["market_gate_decision_timestamp"] == "15:30 Asia/Shanghai"
    assert spec["execution_contract"]["same_bar_fill"] is False
    assert spec["execution_contract"]["earliest_entry"].startswith("existing CHINEXT V1 next")


def test_state_has_exact_active_session_coverage_at_1530() -> None:
    module = _module()
    state = module._load_state(module._load_spec())
    assert min(state) == date(2020, 2, 7)
    assert max(state) == date(2023, 12, 29)
    assert len(state) == 950
    assert all(value is not None for value in state.values())


def test_admission_veto_changes_ranking_only_on_high_state() -> None:
    module = _module()
    original = module.shared.engine_module.rank_candidates_for_arm
    module.shared.engine_module.rank_candidates_for_arm = (
        lambda symbols, rs, day, policy: list(symbols)
    )
    audit = module.shared._new_audit()
    state = {
        date(2020, 2, 7): 0.80,
        date(2020, 2, 10): 0.79,
    }
    try:
        with module._admission_veto(state, audit):
            ranker = module.shared.engine_module.rank_candidates_for_arm
            assert ranker(["A"], {}, date(2020, 2, 7), None) == []
            assert ranker(["A"], {}, date(2020, 2, 10), None) == ["A"]
            assert ranker(["A"], {}, date(2020, 2, 6), None) == ["A"]
        assert audit["vetoed_ranked_candidates"] == 1
        assert len(audit["missing_state_sessions"]) == 0
    finally:
        module.shared.engine_module.rank_candidates_for_arm = original
