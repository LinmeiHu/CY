"""Regression locks for minimal ChinNext V2 mechanism candidates."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"
CANDIDATE = ROOT / "research/chinext_v1/strategy/chinext_v2_candidate.py"
ENGINE = ROOT / "research/chinext_v1/scripts/run_chinext_v1_smoke.py"
RUNNER = ROOT / "research/chinext_v1/scripts/run_chinext_v2_research.py"
PREREG = ROOT / "research/chinext_v1/specs/chinext_v2_attempt_preregistration.json"
LOSS_BUDGET_PREREG = (
    ROOT
    / "research/chinext_v1/specs/chinext_v2_loss_budget_attempt_preregistration.json"
)
ATTEMPT_LEDGER = ROOT / "research/chinext_v1/reports/chinext_v2_attempt_ledger.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def committed_sha256(commit: str, relative_path: str) -> str:
    payload = subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return hashlib.sha256(payload).hexdigest()


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_v1_remains_immutable_and_candidate_policies_are_exact() -> None:
    candidate = load_module(CANDIDATE, "chinext_v2_candidate_test")
    assert sha256(STRATEGY) == candidate.PARENT_V1_STRATEGY_SHA256
    assert set(candidate.POLICIES) == {
        "V2_R120_MEDIAN",
        "V2_ALL_HORIZON_MEDIAN",
        "V2_LOSS_BUDGET_10",
    }
    assert candidate.POLICIES["V2_R120_MEDIAN"].required_rs_horizons == ("r120",)
    assert candidate.POLICIES[
        "V2_ALL_HORIZON_MEDIAN"
    ].required_rs_horizons == ("r20", "r60", "r120")
    assert candidate.POLICIES["V2_R120_MEDIAN"].rs_floor == 0.5
    assert candidate.POLICIES["V2_ALL_HORIZON_MEDIAN"].rs_floor == 0.5
    loss_budget = candidate.POLICIES["V2_LOSS_BUDGET_10"]
    assert loss_budget.required_rs_horizons == ()
    assert loss_budget.rs_floor is None
    assert loss_budget.close_loss_budget == -0.10


def test_v2_rs_admission_uses_median_and_fails_closed() -> None:
    candidate = load_module(CANDIDATE, "chinext_v2_candidate_admission_test")
    r120 = candidate.policy_for("V2_R120_MEDIAN")
    all_horizon = candidate.policy_for("V2_ALL_HORIZON_MEDIAN")
    assert candidate.evaluate_rs_admission({"r120": 0.5}, r120)["passed"] is True
    assert candidate.evaluate_rs_admission({"r120": 0.499999}, r120)["passed"] is False
    assert candidate.evaluate_rs_admission(None, r120)["valid"] is False
    assert candidate.evaluate_rs_admission({"r120": float("nan")}, r120)[
        "valid"
    ] is False
    assert candidate.evaluate_rs_admission(
        {"r20": 0.5, "r60": 0.6, "r120": 0.7}, all_horizon
    )["passed"] is True
    assert candidate.evaluate_rs_admission(
        {"r20": 0.49, "r60": 0.6, "r120": 0.7}, all_horizon
    )["passed"] is False


def test_loss_budget_uses_existing_whole_cycle_cash_flows_and_exact_boundary() -> None:
    candidate = load_module(CANDIDATE, "chinext_v2_loss_budget_test")
    policy = candidate.policy_for("V2_LOSS_BUDGET_10")
    boundary = candidate.evaluate_loss_budget(
        shares=100,
        remaining_cost_basis=1_000,
        remaining_dividends=0,
        cycle_buy_cost=1_000,
        cycle_realized_pnl=0,
        close=9,
        policy=policy,
    )
    assert boundary["valid"] is True
    assert boundary["cycle_mark_return"] == pytest.approx(-0.10)
    assert boundary["triggered"] is True
    partial_cycle = candidate.evaluate_loss_budget(
        shares=100,
        remaining_cost_basis=1_000,
        remaining_dividends=20,
        cycle_buy_cost=2_000,
        cycle_realized_pnl=100,
        close=7,
        policy=policy,
    )
    assert partial_cycle["cycle_mark_return"] == pytest.approx(-0.09)
    assert partial_cycle["triggered"] is False
    invalid = candidate.evaluate_loss_budget(
        shares=100,
        remaining_cost_basis=1_000,
        remaining_dividends=0,
        cycle_buy_cost=0,
        cycle_realized_pnl=0,
        close=9,
        policy=policy,
    )
    assert invalid["valid"] is False
    assert invalid["triggered"] is False


def test_attempts_are_preregistered_hash_bound_and_within_budget() -> None:
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    implementation_commit = "e21b04b6604ef186af05e92553900dddae4627bc"
    assert prereg["status"] == "FROZEN_BEFORE_ANY_V2_CANDIDATE_RESULT"
    assert prereg["research_period"] == ["2018-01-02", "2021-12-31"]
    assert prereg["recent_period_firewall"]["used_for_candidate_selection"] == "NO"
    assert prereg["attempt_budget"]["material_candidate_evaluations_preregistered"] == 2
    assert prereg["attempt_budget"]["maximum_variants_for_hypothesis"] == 2
    assert prereg["frozen_bindings"]["candidate_module_sha256"] == committed_sha256(
        implementation_commit,
        "research/chinext_v1/strategy/chinext_v2_candidate.py",
    )
    assert prereg["frozen_bindings"]["engine_sha256"] == committed_sha256(
        implementation_commit,
        "research/chinext_v1/scripts/run_chinext_v1_smoke.py",
    )
    assert prereg["frozen_bindings"]["runner_sha256"] == committed_sha256(
        implementation_commit,
        "research/chinext_v1/scripts/run_chinext_v2_research.py",
    )
    assert {row["RESULT_STATUS"] for row in prereg["attempts"]} == {
        "PREREGISTERED_NOT_RUN"
    }
    assert {row["HYPOTHESIS_ID"] for row in prereg["attempts"]} == {
        "HYP-001-LONG-HORIZON-RS-ADMISSION"
    }
    assert all(row["COMPLEXITY_DELTA"]["special_case_count"] == 0 for row in prereg["attempts"])
    assert all(row["COMPLEXITY_DELTA"]["new_parameter_count"] == 1 for row in prereg["attempts"])


def test_candidate_identities_match_preregistration() -> None:
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    completed = json.loads(ATTEMPT_LEDGER.read_text(encoding="utf-8"))
    result_ids = {row["ATTEMPT_ID"]: row["STRATEGY_SHA"] for row in completed["attempts"]}
    prereg_ids = {
        row["ATTEMPT_ID"]: row["STRATEGY_SHA"] for row in prereg["attempts"]
    }
    assert {attempt_id: result_ids[attempt_id] for attempt_id in prereg_ids} == prereg_ids
    assert completed["frozen_bindings"]["candidate_implementation_commit"] == (
        "e21b04b6604ef186af05e92553900dddae4627bc"
    )
    runner = load_module(RUNNER, "chinext_v2_runner_test")
    with pytest.raises(ValueError, match="unregistered ChinNext V2 candidate"):
        runner.policy_for("V2_NOT_REGISTERED")


def test_loss_budget_attempt_is_frozen_hash_bound_and_single_variant() -> None:
    prereg = json.loads(LOSS_BUDGET_PREREG.read_text(encoding="utf-8"))
    implementation_commit = "5e046bded74abaaddeb953e2be22d7190d44251d"
    assert prereg["status"] == "FROZEN_BEFORE_V2_A003_RESULT"
    assert prereg["research_period"] == ["2018-01-02", "2021-12-31"]
    assert prereg["recent_period_firewall"]["used_for_candidate_selection"] == "NO"
    assert prereg["attempt_budget"]["material_candidate_evaluations_before_this_spec"] == 2
    assert prereg["attempt_budget"]["material_candidate_evaluations_preregistered_here"] == 1
    assert prereg["attempt_budget"]["material_candidate_evaluations_total_if_completed"] == 3
    assert prereg["attempt_budget"]["maximum_variants_for_hypothesis"] == 1
    assert prereg["attempt_budget"]["parameter_grid"] == "NONE"
    assert len(prereg["attempts"]) == 1
    attempt = prereg["attempts"][0]
    assert attempt["ATTEMPT_ID"] == "V2-A003"
    assert attempt["HYPOTHESIS_ID"] == "HYP-002-CAUSAL-SEVERE-LOSS-BUDGET"
    assert attempt["CANDIDATE_POLICY"] == "V2_LOSS_BUDGET_10"
    assert attempt["RESULT_STATUS"] == "PREREGISTERED_NOT_RUN"
    assert attempt["PARAMETERS_IF_ANY"]["close_loss_budget"] == -0.10
    assert attempt["PARAMETERS_IF_ANY"]["threshold_variants"] == "NONE"
    assert attempt["COMPLEXITY_DELTA"] == {
        "new_condition_count": 1,
        "new_parameter_count": 1,
        "new_state_variable_count": 0,
        "special_case_count": 0,
    }
    assert attempt["STRATEGY_SHA"] == (
        "20a531dfe434aae5cbf581649897229c7680af556703766f78bc6992b907dee2"
    )
    bindings = prereg["frozen_bindings"]
    assert bindings["candidate_module_sha256"] == committed_sha256(
        implementation_commit,
        "research/chinext_v1/strategy/chinext_v2_candidate.py",
    )
    assert bindings["engine_sha256"] == committed_sha256(
        implementation_commit,
        "research/chinext_v1/scripts/run_chinext_v1_smoke.py",
    )
    assert bindings["runner_sha256"] == committed_sha256(
        implementation_commit,
        "research/chinext_v1/scripts/run_chinext_v2_research.py",
    )
    assert bindings["prior_attempt_ledger_sha256"] == committed_sha256(
        "e7f304d7c2f4352c79e9dca39c41f919986a1d45",
        "research/chinext_v1/reports/chinext_v2_attempt_ledger.json",
    )
    assert prereg["causal_contract"]["same_bar_fill"] == "FORBIDDEN"
    assert prereg["causal_contract"]["stale_or_synthetic_signal_price"] == "FORBIDDEN"


def test_completed_attempts_are_all_auditable_and_rejected() -> None:
    ledger = json.loads(ATTEMPT_LEDGER.read_text(encoding="utf-8"))
    assert ledger["candidate_attempts"] == 3
    assert ledger["accepted_attempts"] == 0
    assert ledger["rejected_attempts"] == 3
    assert ledger["technical_failed_attempts"] == 0
    assert ledger["primary_v2_status"] == "NO_DEFENSIBLE_V2_CANDIDATE"
    assert ledger["recent_period_firewall"]["used_2022_2025_for_v2_selection"] == "NO"
    assert {row["ATTEMPT_ID"] for row in ledger["attempts"]} == {
        "V2-A001",
        "V2-A002",
        "V2-A003",
    }
    for row in ledger["attempts"]:
        assert row["DECISION"] == "REJECTED_PRIMARY"
        assert row["acceptance_checks"]["used_2022_2025"] is False
        raw = ROOT / row["RESULT_ARTIFACT"]["path"]
        if raw.is_file():
            assert sha256(raw) == row["RESULT_ARTIFACT"]["sha256"]
    first_two = ledger["attempts"][:2]
    assert all(
        row["acceptance_checks"]["top20_concentration_no_higher"] is False
        for row in first_two
    )
    loss_budget = ledger["attempts"][2]
    assert loss_budget["ATTEMPT_ID"] == "V2-A003"
    for failed in (
        "max_drawdown_no_worse",
        "median_trade_improves",
        "negative_realized_pnl_improves",
        "return_ex_best20_improves",
        "severe_loss_count_reduces",
        "severe_loss_pnl_improves",
    ):
        assert loss_budget["acceptance_checks"][failed] is False
    assert loss_budget["causal_audit"] == {
        "after_2021_execution_count": 0,
        "loss_signal_to_later_full_exit_matches": 13,
        "same_day_fill_count": 0,
        "stale_held_valuation_count": 0,
    }
    assert ledger["research_stop"]["brute_force_search_used"] == "NO"
    assert ledger["research_stop"]["revision_holdback_run"] == "NO"
