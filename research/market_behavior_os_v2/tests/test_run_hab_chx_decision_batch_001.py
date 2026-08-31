from __future__ import annotations

import importlib.util
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
RUNNER = PROGRAM / "scripts/run_hab_chx_decision_batch_001.py"


def _module():
    spec = importlib.util.spec_from_file_location("decision_batch_test", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_contract_fixes_two_distinct_decision_roles_and_next_open_only() -> None:
    module = _module()
    spec = module._load_spec()
    assert module.shared.sha256_file(module.SPEC_PATH) == module.EXPECTED_SPEC_SHA256
    assert spec["arms"][module.SELECTION_ARM]["role"] == "stock_selection_admission_veto"
    assert spec["arms"][module.EXPOSURE_ARM]["role"] == "portfolio_risk_budget"
    assert spec["arms"][module.SELECTION_ARM]["threshold_search"] is False
    assert spec["arms"][module.EXPOSURE_ARM]["exposure_search"] is False
    assert spec["execution_contract"]["same_bar_fill"] is False


def test_selection_veto_removes_only_fixed_overextension() -> None:
    module = _module()
    engine = module.shared.engine_module
    original = engine.rank_candidates_for_arm
    engine.rank_candidates_for_arm = lambda symbols, rs, day, policy: list(symbols)
    audit = module._new_selection_audit()
    rs = {
        "KEEP": {"r20": 0.69, "r120": 0.50},
        "VETO": {"r20": 0.70, "r120": 0.50},
    }
    try:
        with module._selection_veto(None, audit):
            assert engine.rank_candidates_for_arm(
                ["KEEP", "VETO"], rs, date(2023, 1, 3), None
            ) == ["KEEP"]
        assert audit["candidate_count"] == 2
        assert audit["vetoed_candidate_count"] == 1
    finally:
        engine.rank_candidates_for_arm = original


def test_exposure_budget_changes_target_only_after_state_transition() -> None:
    module = _module()
    engine = module.shared.engine_module
    original_rank = engine.rank_candidates_for_arm
    original_change = engine.set_change_required
    original_schedule = engine.schedule_target_set
    engine.rank_candidates_for_arm = lambda symbols, rs, day, policy: list(symbols)
    engine.set_change_required = lambda previous, desired: set(previous) != set(desired)
    audit = module._new_exposure_audit()
    state = {date(2020, 2, 7): 0.80, date(2020, 2, 10): 0.79}
    try:
        with module._exposure_budget(state, audit):
            engine.rank_candidates_for_arm(["A"], {}, date(2020, 2, 7), None)
            assert engine.set_change_required(("A",), ("A",)) is True
            pending = {}
            engine.schedule_target_set(
                desired=("A",),
                previous=("A",),
                positions={"A": object()},
                pending=pending,
                signal_date=date(2020, 2, 7),
                reason="RISK_BUDGET_TRANSITION",
                config=SimpleNamespace(max_holdings=10),
            )
            assert pending["A"].target_weight == 0.05
            assert engine.set_change_required(("A",), ("A",)) is False
            engine.rank_candidates_for_arm(["A"], {}, date(2020, 2, 10), None)
            assert engine.set_change_required(("A",), ("A",)) is True
        assert len(audit["exposure_transition_sessions"]) == 1
    finally:
        engine.rank_candidates_for_arm = original_rank
        engine.set_change_required = original_change
        engine.schedule_target_set = original_schedule


def test_completed_result_passes_fixed_gates_without_same_day_fills() -> None:
    result = json.loads(
        (PROGRAM / "artifacts/HAB-CHX-DECISION-BATCH-001_result.json").read_text()
    )
    assert set(result["arms"]) == {"RS_ACCEL_OVEREXTENSION_VETO", "MINVOL_HIGH_HALF_GROSS"}
    for arm in result["arms"].values():
        assert arm["passes_promotion_rule"] is True
        assert all(arm["checks"].values())
    assert result["claim_boundary"]["post_2023_rows_read_by_experiment"] is False
    assert result["claim_boundary"]["untouched_validation"] is False


def test_exposure_replay_preserves_cycle_identity_and_allowed_targets() -> None:
    module = _module()
    spec = module._load_spec()
    output = PROGRAM / "artifacts/HAB-CHX-DECISION-BATCH-001/MINVOL_HIGH_HALF_GROSS"
    blocks = {
        "development_2018_2021": "development_execution_ledger",
        "consumed_2022_2023": "holdout_execution_ledger",
    }
    for block, baseline_name in blocks.items():
        baseline_rows = module.shared.read_jsonl(
            module._resolve(spec["inputs"][baseline_name]["path"])
        )
        candidate_rows = module.shared.read_jsonl(output / block / "execution_ledger.jsonl")
        baseline_trips = module.shared.reconstruct_round_trips(baseline_rows)
        candidate_trips = module.shared.reconstruct_round_trips(candidate_rows)
        identity_fields = (
            "symbol",
            "entry_signal_date",
            "entry_execution_date",
            "exit_signal_date",
            "exit_execution_date",
            "exit_reason",
        )
        baseline_identity = [
            tuple(row[field] for field in identity_fields) for row in baseline_trips
        ]
        candidate_identity = [
            tuple(row[field] for field in identity_fields) for row in candidate_trips
        ]
        assert candidate_identity == baseline_identity
        filled = [row for row in candidate_rows if row.get("status") == "FILLED"]
        assert {float(row["target_weight"]) for row in filled} <= {0.0, 0.05, 0.1}
        assert all(row["signal_date"] < row["execution_date"] for row in filled)


def test_selection_replay_never_opens_a_vetoed_candidate() -> None:
    module = _module()
    output = PROGRAM / "artifacts/HAB-CHX-DECISION-BATCH-001/RS_ACCEL_OVEREXTENSION_VETO"
    for block in ("development_2018_2021", "consumed_2022_2023"):
        events = module.shared.read_jsonl(output / block / "event_ledger.jsonl")
        by_key = {
            (str(row["signal_date"]), str(row["symbol"])): row
            for row in events
            if row.get("event") == "ENTRY_SIGNAL_EVALUATED"
        }
        executions = module.shared.read_jsonl(output / block / "execution_ledger.jsonl")
        entries = [
            row
            for row in executions
            if row.get("status") == "FILLED"
            and row.get("side") == "BUY"
            and row.get("new_position") is True
        ]
        assert entries
        for entry in entries:
            event = by_key[(str(entry["signal_date"]), str(entry["symbol"]))]
            acceleration = Decimal(str(event["rs"]["r20"])) - Decimal(
                str(event["rs"]["r120"])
            )
            assert acceleration < Decimal("0.20")
            assert entry["signal_date"] < entry["execution_date"]
