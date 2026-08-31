from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
RUNNER = PROGRAM / "scripts/run_hab_chx_downrev_strat_001.py"


def _module():
    spec = importlib.util.spec_from_file_location("downrev_strategy_test", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_contract_is_post_discovery_and_t_plus_one_only() -> None:
    module = _module()
    spec = module._load_spec()
    assert module.sha256_file(module.SPEC_PATH) == module.EXPECTED_SPEC_SHA256
    assert "inspected before" in spec["honesty_boundary"]
    assert spec["state_rule"]["threshold_search"] is False
    assert spec["state_rule"]["block_new_admissions_when"] == "coordinate <= 0.20"
    assert spec["execution_contract"]["same_bar_fill"] is False
    assert spec["execution_contract"]["earliest_entry"].startswith("existing CHINEXT V1 next")


def test_state_has_exact_active_session_coverage_and_missing_fails_closed() -> None:
    module = _module()
    state = module._load_state(module._load_spec())
    assert min(state) == date(2020, 7, 28)
    assert max(state) == date(2023, 12, 29)
    assert len(state) == 834
    assert sum(value is None for value in state.values()) == 1


def test_admission_veto_changes_ranking_only_on_low_or_missing_state() -> None:
    module = _module()
    original = module.engine_module.rank_candidates_for_arm
    module.engine_module.rank_candidates_for_arm = lambda symbols, rs, day, policy: list(symbols)
    audit = module._new_audit()
    state = {
        date(2020, 7, 28): 0.20,
        date(2020, 7, 29): 0.21,
        date(2020, 7, 30): None,
    }
    try:
        with module._admission_veto(state, audit):
            ranker = module.engine_module.rank_candidates_for_arm
            assert ranker(["A"], {}, date(2020, 7, 28), None) == []
            assert ranker(["A"], {}, date(2020, 7, 29), None) == ["A"]
            assert ranker(["A"], {}, date(2020, 7, 30), None) == []
            assert ranker(["A"], {}, date(2020, 7, 27), None) == ["A"]
        assert audit["vetoed_ranked_candidates"] == 2
        assert len(audit["missing_state_sessions"]) == 1
    finally:
        module.engine_module.rank_candidates_for_arm = original
