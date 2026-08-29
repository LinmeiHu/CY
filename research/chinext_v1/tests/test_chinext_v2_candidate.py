"""Regression locks for minimal ChinNext V2 mechanism candidates."""

from __future__ import annotations

import hashlib
import importlib.util
import json
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
ATTEMPT_LEDGER = ROOT / "research/chinext_v1/reports/chinext_v2_attempt_ledger.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    }
    assert candidate.POLICIES["V2_R120_MEDIAN"].required_rs_horizons == ("r120",)
    assert candidate.POLICIES[
        "V2_ALL_HORIZON_MEDIAN"
    ].required_rs_horizons == ("r20", "r60", "r120")
    assert {policy.rs_floor for policy in candidate.POLICIES.values()} == {0.5}


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


def test_attempts_are_preregistered_hash_bound_and_within_budget() -> None:
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    assert prereg["status"] == "FROZEN_BEFORE_ANY_V2_CANDIDATE_RESULT"
    assert prereg["research_period"] == ["2018-01-02", "2021-12-31"]
    assert prereg["recent_period_firewall"]["used_for_candidate_selection"] == "NO"
    assert prereg["attempt_budget"]["material_candidate_evaluations_preregistered"] == 2
    assert prereg["attempt_budget"]["maximum_variants_for_hypothesis"] == 2
    assert prereg["frozen_bindings"]["candidate_module_sha256"] == sha256(CANDIDATE)
    assert prereg["frozen_bindings"]["engine_sha256"] == sha256(ENGINE)
    assert prereg["frozen_bindings"]["runner_sha256"] == sha256(RUNNER)
    assert {row["RESULT_STATUS"] for row in prereg["attempts"]} == {
        "PREREGISTERED_NOT_RUN"
    }
    assert {row["HYPOTHESIS_ID"] for row in prereg["attempts"]} == {
        "HYP-001-LONG-HORIZON-RS-ADMISSION"
    }
    assert all(row["COMPLEXITY_DELTA"]["special_case_count"] == 0 for row in prereg["attempts"])
    assert all(row["COMPLEXITY_DELTA"]["new_parameter_count"] == 1 for row in prereg["attempts"])


def test_candidate_identities_match_preregistration() -> None:
    runner = load_module(RUNNER, "chinext_v2_runner_test")
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    for attempt in prereg["attempts"]:
        assert runner.candidate_identity(attempt["CANDIDATE_POLICY"]) == attempt[
            "STRATEGY_SHA"
        ]
    with pytest.raises(ValueError, match="unregistered ChinNext V2 candidate"):
        runner.policy_for("V2_NOT_REGISTERED")


def test_completed_hypothesis_one_attempts_are_all_auditable_and_rejected() -> None:
    ledger = json.loads(ATTEMPT_LEDGER.read_text(encoding="utf-8"))
    assert ledger["candidate_attempts"] == 2
    assert ledger["accepted_attempts"] == 0
    assert ledger["rejected_attempts"] == 2
    assert ledger["technical_failed_attempts"] == 0
    assert ledger["primary_v2_status"] == "NO_PRIMARY_FROM_HYP_001"
    assert ledger["recent_period_firewall"]["used_2022_2025_for_v2_selection"] == "NO"
    assert {row["ATTEMPT_ID"] for row in ledger["attempts"]} == {
        "V2-A001",
        "V2-A002",
    }
    for row in ledger["attempts"]:
        assert row["DECISION"] == "REJECTED_PRIMARY"
        assert row["acceptance_checks"]["top20_concentration_no_higher"] is False
        assert all(
            value
            for name, value in row["acceptance_checks"].items()
            if name not in {"top20_concentration_no_higher", "used_2022_2025"}
        )
        assert row["acceptance_checks"]["used_2022_2025"] is False
        raw = ROOT / row["RESULT_ARTIFACT"]["path"]
        if raw.is_file():
            assert sha256(raw) == row["RESULT_ARTIFACT"]["sha256"]
