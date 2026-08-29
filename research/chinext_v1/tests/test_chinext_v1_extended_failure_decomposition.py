"""Integrity and research-firewall locks for V1 failure decomposition."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / "research/chinext_v1/reports"
SPECS = ROOT / "research/chinext_v1/specs"
DECOMPOSITION = REPORTS / "chinext_v1_extended_failure_decomposition.json"
SUMMARY = REPORTS / "chinext_v1_extended_replay_summary.json"
HYPOTHESES = SPECS / "chinext_v2_failure_hypothesis_ledger.json"
STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_failure_decomposition_is_offline_and_hash_bound() -> None:
    result = json.loads(DECOMPOSITION.read_text(encoding="utf-8"))
    authorization = result["authorization"]
    assert authorization == {
        "formal_replay_executions": 0,
        "new_nav": 0,
        "new_trades": 0,
        "pit_rebuilt": "TRANSIENT_INPUT_RECONSTRUCTION_ONLY",
        "sample_status": "IN_SAMPLE_MECHANISM_RESEARCH_AFTER_FROZEN_V1_FIRST_VIEW",
        "strategy_modified": "NO",
        "used_2022_2025_for_v2_selection": "NO",
    }
    assert result["frozen_bindings"]["summary_sha256"] == sha256(SUMMARY)
    assert result["frozen_bindings"]["strategy_sha256"] == sha256(STRATEGY)
    assert result["holding_path"]["return_method"].startswith(
        "cycle cash-on-cash mark including filled rebalance legs"
    )
    assert result["overall"]["count"] == 194
    assert result["v1_extended_history_generalization"]["label"] == "MIXED"


def test_hypothesis_ledger_is_frozen_before_candidates_and_within_budget() -> None:
    ledger = json.loads(HYPOTHESES.read_text(encoding="utf-8"))
    hypotheses = ledger["hypotheses"]
    assert ledger["authorization"]["frozen_before_candidate_evaluation"] is True
    assert ledger["authorization"]["used_2022_2025_for_v2_selection"] == "NO"
    assert ledger["frozen_bindings"]["failure_decomposition_sha256"] == sha256(
        DECOMPOSITION
    )
    assert ledger["frozen_bindings"]["v1_strategy_sha256"] == sha256(STRATEGY)
    assert len(hypotheses) == ledger["ranked_hypothesis_count"] <= 12
    assert ledger["attempt_budget"]["maximum_meaningful_variants_per_mechanism"] == 2
    assert ledger["attempt_budget"]["maximum_material_candidate_evaluations"] == 24
    assert [row["RANK"] for row in hypotheses] == list(range(1, len(hypotheses) + 1))


def test_every_hypothesis_is_complete_and_no_special_case_is_allowed() -> None:
    ledger = json.loads(HYPOTHESES.read_text(encoding="utf-8"))
    required = {
        "HYPOTHESIS_ID",
        "OBSERVED_V1_FAILURE",
        "MECHANISM",
        "EVIDENCE",
        "WHY_V1_MAY_CAUSE_IT",
        "PROPOSED_MINIMAL_CHANGE",
        "EXPECTED_BENEFIT",
        "EXPECTED_COST",
        "FALSIFICATION_RESULT",
        "COMPLEXITY_DELTA",
    }
    for hypothesis in ledger["hypotheses"]:
        assert required <= hypothesis.keys()
        assert hypothesis["COMPLEXITY_DELTA"]["special_case_count"] == 0
    firewall = ledger["selection_firewall"]
    assert firewall["candidate_period_end"] == "2021-12-31"
    assert firewall["forbidden_selection_dates"] == "2022-01-01..2025-12-31"
    assert firewall["recent_period_status"] == (
        "REVISION_HOLDBACK_NOT_USED_FOR_V2_SELECTION"
    )
    assert firewall["total_return_alone_is_sufficient"] is False
