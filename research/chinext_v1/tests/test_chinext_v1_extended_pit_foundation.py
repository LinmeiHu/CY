"""Regression locks for the outcome-blind extended PIT foundation decision."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / "research/chinext_v1/reports"
SUMMARY = REPORTS / "chinext_v1_extended_pit_foundation_summary.json"
REPORT = REPORTS / "chinext_v1_extended_pit_foundation.md"
STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"

EXPECTED_STRATEGY_SHA256 = (
    "dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a"
)


def load_summary() -> dict:
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def test_blocked_prerequisites_stop_pilot_materialization_and_replay() -> None:
    summary = load_summary()

    assert summary["gate_a"]["decision"] == "BLOCKED_EXTERNAL_DATA"
    assert summary["gate_b"]["decision"] == "BLOCKED_EXTERNAL_DATA"
    assert summary["gate_c"]["decision"] == "NOT_AUTHORIZED"
    assert summary["gate_c"]["pilot_spec"] == "NOT_CREATED"
    assert summary["gate_c"]["pilot_result"] == "NOT_RUN"
    assert summary["gate_d"]["decision"] == "NOT_AUTHORIZED"
    assert set(summary["gate_d"]["metrics"].values()) == {"NOT_RUN"}
    assert (
        summary["final_decision"]["safe_to_run_extended_history_strategy_replay"]
        == "NO"
    )


def test_warmup_and_frozen_strategy_are_exact_and_outcome_blind() -> None:
    summary = load_summary()
    gate_b = summary["gate_b"]
    scope = summary["scope"]

    assert gate_b["earliest_formal_decision_date"] == "2018-01-02"
    assert gate_b["max_lookback_required"] == 180
    assert gate_b["calendar_sessions_required"] == 180
    assert gate_b["actual_warmup_start_required"] == "2017-04-12"
    assert gate_b["actual_warmup_end"] == "2017-12-29"
    assert "PASS" in gate_b["warmup_calendar_status"]
    assert "PASS_BOUNDED_PIT_AUTHORIZED" in gate_b[
        "warmup_corporate_action_status"
    ]
    assert gate_b["prefix_diagnostic"]["qd001"]["volume_or_amount_null_rows"] == 5
    assert gate_b["prefix_diagnostic"]["warning"] == (
        "300/301/302 prefix is not a membership rule"
    )

    assert hashlib.sha256(STRATEGY.read_bytes()).hexdigest() == EXPECTED_STRATEGY_SHA256
    assert summary["frozen_strategy"]["sha256"] == EXPECTED_STRATEGY_SHA256
    assert summary["frozen_strategy"]["modified"] is False
    assert scope["formal_strategy_replay_executions"] == 0
    assert scope["new_strategy_trades"] == 0
    assert scope["new_strategy_nav"] == 0
    assert scope["no_strategy_performance_computed"] is True


def test_source_boundaries_prevent_current_master_backfill() -> None:
    summary = load_summary()
    sources = summary["gate_a"]["source_adjudication"]
    alias = summary["gate_a"]["representative_state_evidence"][
        "identity_alias_counterexample"
    ]

    assert sources["QD-002"]["CURRENT_AUTHORIZATION"] == "RESEARCH_CONDITIONAL_PIT_B"
    assert "standalone historical universe" in sources["QD-002"]["FORBIDDEN_USE"]
    assert sources["QD-007"]["CURRENT_AUTHORIZATION"] == "DISCOVERY_ONLY"
    assert "no 2018-2021 materialization" in sources["QD-007"]["DATE_RANGE"]
    assert sources["CY-027"]["DATE_RANGE"] == ["2024-01-02", "2025-12-31"]
    assert "other date ranges" in sources["CY-027"]["FORBIDDEN_USE"]
    assert alias["symbols_in_current_master"] == ["300132", "302132"]
    assert alias["repository_fail_closed_boundary"] == (
        "302132.SZ is historically invalid before 2025-02-17"
    )
    assert summary["gate_a"]["star_st_status"] == "BLOCKED_NOT_DISTINGUISHED"


def test_missing_data_contracts_are_actionable_and_fail_closed() -> None:
    summary = load_summary()
    contracts = {
        item["CONTRACT_ID"]: item for item in summary["exact_missing_data_contract"]
    }
    required_keys = {
        "MISSING_STATE_DIMENSION",
        "REQUIRED_DATASET_CLASS",
        "REQUIRED_FIELDS",
        "DATE_RANGE",
        "SYMBOL_SCOPE",
        "EFFECTIVE_DATE_SEMANTICS",
        "KNOWN_AT_SEMANTICS",
        "REVISION_LINEAGE_REQUIREMENT",
        "NON_SURVIVOR_REQUIREMENT",
        "IMMUTABILITY_REQUIREMENT",
        "WHY_EXISTING_ASSETS_FAIL",
        "WHAT_EXACTLY_MUST_BE_ACQUIRED",
        "ACCEPTANCE_TEST",
    }

    assert set(contracts) == {
        "CHINEXT-V1-MISSING-HISTORICAL-IDENTITY-LISTOUT-ALIAS-V1",
        "CHINEXT-V1-MISSING-RISK-WARNING-SUSPENSION-SEMANTICS-V1",
    }
    for contract in contracts.values():
        assert required_keys <= contract.keys()
        assert contract["DATE_RANGE"] == ["2017-04-12", "2021-12-31"]
        assert contract["REQUIRED_FIELDS"]
        assert contract["WHY_EXISTING_ASSETS_FAIL"]
        assert contract["ACCEPTANCE_TEST"]

    identity_tests = " ".join(
        contracts[
            "CHINEXT-V1-MISSING-HISTORICAL-IDENTITY-LISTOUT-ALIAS-V1"
        ]["ACCEPTANCE_TEST"]
    )
    state_tests = " ".join(
        contracts[
            "CHINEXT-V1-MISSING-RISK-WARNING-SUSPENSION-SEMANTICS-V1"
        ]["ACCEPTANCE_TEST"]
    )
    assert "302132.SZ" in identity_tests
    assert "current-survivor and ticker-prefix fallbacks remain disabled" in identity_tests
    assert "ST and *ST remain distinct" in state_tests
    assert "missing bar and zero volume never create a suspension fact" in state_tests


def test_superseding_report_preserves_corporate_action_closure() -> None:
    summary = load_summary()
    report = REPORT.read_text(encoding="utf-8")
    adjudication = (
        REPORTS / "chinext_v1_corporate_action_adjudication.md"
    ).read_text(encoding="utf-8")

    assert "635/635" in summary["reconciliation"]["latest_authoritative_result"]
    assert "635/635" in report
    assert "635 exact CY-006 event-ID matches and 0 unmatched events" in adjudication
    assert summary["reconciliation"]["stale_artifacts"][0]["current_fact"] == (
        "635/635 exact event-ID matches and 0 unmatched"
    )
    assert "No external provider is selected or implicitly authorized" in report
