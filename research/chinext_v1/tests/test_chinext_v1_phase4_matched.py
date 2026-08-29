from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "research/chinext_v1/scripts"
sys.path.insert(0, str(SCRIPTS))

from chinext_v1_phase4 import (  # noqa: E402
    MATCHED_ARM_ORDER,
    canonical_envelope,
    select_with_capacity_envelope,
)
from run_chinext_v1_phase4_matched import validate_frozen_inputs  # noqa: E402
from run_chinext_v1_smoke import sha256_file  # noqa: E402
from strategy.chinext_v1_exploratory import (  # noqa: E402
    ChinNextV1Config,
    select_no_replacement_members,
)

REPORTS = ROOT / "research/chinext_v1/reports"
SPEC = REPORTS / "chinext_v1_phase4_matched_spec.json"
CROWDOUT = REPORTS / "chinext_v1_phase4_winner_crowdout.csv"
PHASE3_OUTPUT = ROOT / "research/chinext_v1/output/chinext_v1_phase3_ablation"
PHASE4_OUTPUT = ROOT / "research/chinext_v1/output/chinext_v1_phase4_matched"
SUMMARY = REPORTS / "chinext_v1_phase4_exposure_matched_summary.json"
SPEC_SHA256 = "6823ac96d9f93922e64f71e2b7dd0048ca522f7c280b9d4388534e8c77563509"


def test_phase4_spec_was_frozen_before_matched_results() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    assert sha256_file(SPEC) == SPEC_SHA256
    assert spec["status"] == "FROZEN_BEFORE_ANY_MATCHED_RESULT"
    assert spec["matched_results_observed_before_freeze"] is False
    assert spec["new_formal_replay_executions_expected"] == 2
    assert tuple(spec["formal_run_order"]) == MATCHED_ARM_ORDER
    assert spec["frozen_identity"]["current_survivor_fallback"] is False
    assert spec["frozen_identity"]["pit_rebuilt"] is False


def test_offline_crowdout_covers_all_frozen_top20_episodes_with_evidence() -> None:
    with CROWDOUT.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 40
    keys = [(row["raw_arm"], row["baseline_rank"], row["symbol"], row["entry_signal_date"]) for row in rows]
    assert len(keys) == len(set(keys))
    counts = Counter((row["raw_arm"], row["classification"]) for row in rows)
    assert counts[("A2_MINUS_B60", "CAPTURED_SAME_EPISODE")] == 7
    assert counts[("A2_MINUS_B60", "ELIGIBLE_BUT_OUTRANKED")] == 5
    assert counts[("A2_MINUS_B60", "NO_VACANCY_FROM_EARLIER_EXTRA_ENTRIES")] == 7
    assert counts[("A2_MINUS_B60", "PORTFOLIO_PATH_ALREADY_DIVERGED")] == 1
    assert counts[("A3_MINUS_FULL40", "CAPTURED_SAME_EPISODE")] == 1
    assert counts[("A3_MINUS_FULL40", "ELIGIBLE_BUT_OUTRANKED")] == 10
    assert counts[("A3_MINUS_FULL40", "NO_VACANCY_FROM_EARLIER_EXTRA_ENTRIES")] == 9
    assert all(row["evidence"] or row["classification"] == "CAPTURED_SAME_EPISODE" for row in rows)


def test_capacity_envelope_is_the_exact_frozen_A0_planned_member_schedule() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    nav = [
        json.loads(line)
        for line in (PHASE3_OUTPUT / "a0_baseline/daily_nav.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    expected = canonical_envelope(nav)
    frozen = spec["baseline_capacity_envelope"]
    assert frozen["schedule"] == expected
    assert frozen["row_count"] == 485
    assert frozen["source_daily_nav_sha256"] == (
        "a1b8399c7f199a76ae6e891bbd690de16a3312d2cc548c77d552f2531adcc071"
    )


def test_capacity_selector_only_changes_vacancies_and_never_copies_A0_symbols() -> None:
    config = ChinNextV1Config()
    current = ("300001.SZ", "300002.SZ")
    ranked = ["300003.SZ", "300004.SZ", "300005.SZ"]
    assert select_with_capacity_envelope(current, (), ranked, 3) == (
        "300001.SZ",
        "300002.SZ",
        "300003.SZ",
    )
    assert select_with_capacity_envelope(current, (), ranked, 1) == current
    assert select_with_capacity_envelope(current, ("300001.SZ",), ranked, 2) == (
        "300002.SZ",
        "300003.SZ",
    )
    assert select_with_capacity_envelope(current, (), ranked, 10) == (
        select_no_replacement_members(current, (), ranked, config)
    )


def test_matched_arms_differ_from_raw_parent_only_by_frozen_capacity_contract() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    arms = spec["arms"]
    assert arms["M2_MINUS_B60_BASELINE_CAPACITY"]["raw_parent"] == "A2_MINUS_B60"
    assert arms["M3_MINUS_FULL40_BASELINE_CAPACITY"]["raw_parent"] == "A3_MINUS_FULL40"
    for arm in MATCHED_ARM_ORDER:
        assert arms[arm]["only_difference_from_raw_parent"] == (
            "frozen A0 daily capacity envelope"
        )
    common = spec["common_frozen_contract"]
    assert common["transaction_cost_bps_per_filled_side"] == 10.0
    assert common["target_weight"] == 0.1
    assert common["market_and_individual_exit_semantics"] == "EXACT_BASELINE"
    assert common["rs_ordering"] == "20/60/120 = 0.20/0.50/0.30 with frozen tie-break"


def test_phase3_inputs_and_central_authorization_remain_valid() -> None:
    spec, authorization = validate_frozen_inputs()
    assert spec["frozen_identity"]["input_sha256"]["phase3_summary"] == (
        "9762426dc2787c6d34a1b6ba6caf44863863ab1f185c85ab799f37aa4b6891b2"
    )
    assert authorization.authorization_id == "CYQ-AUTH-CHINEXT-V1-PIT-B-2024-2025-V1"
    assert authorization.dependency_status == "DISCOVERY_ONLY"


def test_phase4_formal_outputs_are_exactly_the_two_frozen_matched_arms() -> None:
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    assert summary["new_formal_replay_executions"] == 2
    assert tuple(summary["formal_run_order"]) == MATCHED_ARM_ORDER
    assert summary["identity"]["phase4_spec_sha256"] == SPEC_SHA256
    assert summary["identity"]["spec_frozen_before_results"] is True
    assert summary["identity"]["pit_rebuilt"] is False
    assert summary["identity"]["current_survivor_fallback"] is False
    assert sorted(path.name for path in PHASE4_OUTPUT.iterdir() if path.is_dir()) == sorted(
        arm.lower() for arm in MATCHED_ARM_ORDER
    )
    expected = {
        "M2_MINUS_B60_BASELINE_CAPACITY": (0.47697613530000105, 129, 7),
        "M3_MINUS_FULL40_BASELINE_CAPACITY": (0.8756416039500012, 110, 0),
    }
    for arm, (total_return, trades, captured) in expected.items():
        result = summary["arms"][arm]
        assert result["total_return"] == total_return
        assert result["trade_count"] == trades
        assert result["baseline_top20_captured_count"] == captured
        assert result["same_day_fill_count"] == 0
        assert result["stale_held_valuation_count"] == 0


def test_each_matched_engine_changes_raw_parent_only_by_capacity_envelope() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    pairs = (
        ("M2_MINUS_B60_BASELINE_CAPACITY", "a2_minus_b60"),
        ("M3_MINUS_FULL40_BASELINE_CAPACITY", "a3_minus_full40"),
    )
    for matched_arm, raw_directory in pairs:
        matched = json.loads(
            (PHASE4_OUTPUT / matched_arm.lower() / "engine_summary.json").read_text(
                encoding="utf-8"
            )
        )
        raw = json.loads(
            (PHASE3_OUTPUT / raw_directory / "engine_summary.json").read_text(encoding="utf-8")
        )
        assert matched["configuration"] == raw["configuration"]
        assert matched["phase3_ablation"] == raw["phase3_ablation"]
        assert matched["research_mode"] == raw["research_mode"]
        assert matched["data"] == raw["data"]
        assert matched["sample"]["date_range"] == raw["sample"]["date_range"]
        assert matched["sample"]["pit_membership_mode"] is True
        assert matched["data"]["current_survivor_fallback"] is False
        assert matched["execution"]["transaction_cost_bps_per_side"] == 10.0
        assert matched["execution"]["board_lot"] == 100
        assert matched["execution"]["rank_replacement"] == "OFF"
        assert matched["phase4_capacity_envelope"]["identity"] == {
            "phase4_spec_sha256": SPEC_SHA256,
            "envelope_sha256": spec["baseline_capacity_envelope"]["canonical_sha256"],
            "source_A0_daily_nav_sha256": spec["baseline_capacity_envelope"][
                "source_daily_nav_sha256"
            ],
        }
        assert matched["audit"]["stale_held_valuation_count"] == 0


def test_each_matched_daily_ledger_uses_the_exact_frozen_capacity_schedule() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    envelope = {
        row["trade_date"]: row["allowed_target_member_count"]
        for row in spec["baseline_capacity_envelope"]["schedule"]
    }
    expected_overflow = {
        "M2_MINUS_B60_BASELINE_CAPACITY": (4, 1),
        "M3_MINUS_FULL40_BASELINE_CAPACITY": (28, 2),
    }
    for arm, (overflow_days, max_overflow) in expected_overflow.items():
        nav = [
            json.loads(line)
            for line in (PHASE4_OUTPUT / arm.lower() / "daily_nav.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert len(nav) == len(envelope) == 485
        assert all(
            row["allowed_target_member_count"] == envelope[row["trade_date"]]
            for row in nav
        )
        actual_overflow = [row["target_member_overflow"] for row in nav]
        assert sum(value > 0 for value in actual_overflow) == overflow_days
        assert max(actual_overflow) == max_overflow
