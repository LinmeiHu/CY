from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "research/chinext_v1/scripts"
sys.path.insert(0, str(SCRIPTS))

from chinext_v1_ablation import (  # noqa: E402
    ARM_ORDER,
    NO_RS_DOMAIN,
    POLICIES,
    market_entry_allowed_for_arm,
    no_rs_priority_key,
    policy_for,
    price_structure_for_arm,
    rank_candidates_for_arm,
)
from run_chinext_v1_smoke import sha256_file  # noqa: E402
from strategy.chinext_v1_exploratory import (  # noqa: E402
    ChinNextV1Config,
    entry_price_structure,
)

SPEC = ROOT / "research/chinext_v1/reports/chinext_v1_phase3_ablation_spec.json"
SPEC_SHA256 = "530a5cabddf5afbef86f3fd433a6be35a36973bf3f7662944267a3bec97f160c"
SUMMARY = ROOT / "research/chinext_v1/reports/chinext_v1_phase3_ablation_summary.json"
OUTPUT_ROOT = ROOT / "research/chinext_v1/output/chinext_v1_phase3_ablation"
EXPECTED_A0_EXECUTION = "f3a83a9e974776f34477c952b1bf4c26f22a5ef00879adfc77cd6188f9eec9d5"
EXPECTED_A0_NAV = "a1b8399c7f199a76ae6e891bbd690de16a3312d2cc548c77d552f2531adcc071"


def test_spec_was_frozen_and_matches_registered_arm_order() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    assert sha256_file(SPEC) == SPEC_SHA256
    assert spec["status"] == "FROZEN_BEFORE_ANY_ABLATION_RESULT"
    assert spec["results_observed_before_freeze"] is False
    assert tuple(spec["formal_run_order"]) == ARM_ORDER
    assert set(spec["arms"]) == set(ARM_ORDER) == set(POLICIES)
    assert spec["common_contract"]["transaction_cost_bps_per_filled_side"] == 10.0
    assert spec["common_contract"]["max_holdings"] == 10
    assert spec["common_contract"]["target_weight"] == 0.1
    assert spec["frozen_inputs"]["current_survivor_fallback"] is False


def test_each_nonbaseline_policy_changes_exactly_one_registered_entry_module() -> None:
    baseline = asdict(policy_for("A0_BASELINE"))
    expected = {
        "A1_MINUS_MINVOL": "minvol_hard_filter",
        "A2_MINUS_B60": "b60_hard_filter",
        "A3_MINUS_FULL40": "full40_hard_filter",
        "A4_NO_RS_SELECTION_CONTROL": "rs_selection",
        "A5_MINUS_MARKET_ENTRY_GATE": "market_entry_gate",
    }
    for arm, field in expected.items():
        candidate = asdict(policy_for(arm))
        differences = {
            key for key in baseline if key != "name" and baseline[key] != candidate[key]
        }
        assert differences == {field}
        assert candidate[field] is False
    assert set(baseline) == {
        "name",
        "minvol_hard_filter",
        "b60_hard_filter",
        "full40_hard_filter",
        "rs_selection",
        "market_entry_gate",
    }


def test_A0_price_structure_is_the_frozen_baseline_function() -> None:
    config = ChinNextV1Config()
    closes = [100.0 + (index % 5) * 0.1 for index in range(121)] + [102.0]
    expected_pass, expected_full = entry_price_structure(closes, config)
    actual_pass, actual_full, diagnostics = price_structure_for_arm(
        closes, config, policy_for("A0_BASELINE")
    )
    assert actual_pass == expected_pass
    assert actual_full == expected_full
    assert diagnostics["b60_hard_filter_active"] is True
    assert diagnostics["full40_hard_filter_active"] is True


def test_no_rs_priority_is_exact_deterministic_domain_hash() -> None:
    assert NO_RS_DOMAIN == "CHINEXT_V1_PHASE3_NO_RS_V1"
    expected = "91a8c9fdca3de6ded9c0a295677bf50bf0a7895a1aad2c4f60b44b34aad34985"
    assert no_rs_priority_key(date(2024, 9, 24), "300377.SZ") == expected
    assert expected == hashlib.sha256(
        b"CHINEXT_V1_PHASE3_NO_RS_V1|2024-09-24|300377.SZ"
    ).hexdigest()
    candidates = ["300001.SZ", "300002.SZ", "300003.SZ"]
    rs = {
        symbol: {"score": value, "mom60": value}
        for symbol, value in zip(candidates, (0.9, 0.1, 0.5), strict=True)
    }
    first = rank_candidates_for_arm(
        candidates, rs, date(2024, 9, 24), policy_for("A4_NO_RS_SELECTION_CONTROL")
    )
    second = rank_candidates_for_arm(
        reversed(candidates), rs, date(2024, 9, 24), policy_for("A4_NO_RS_SELECTION_CONTROL")
    )
    assert first == second
    assert first == sorted(
        candidates, key=lambda symbol: no_rs_priority_key(date(2024, 9, 24), symbol)
    )


def test_market_gate_ablation_changes_entry_permission_only() -> None:
    blocked = {"valid": True, "entry_permission": False}
    allowed = {"valid": True, "entry_permission": True}
    assert not market_entry_allowed_for_arm(blocked, policy_for("A0_BASELINE"))
    assert market_entry_allowed_for_arm(allowed, policy_for("A0_BASELINE"))
    assert market_entry_allowed_for_arm(blocked, policy_for("A5_MINUS_MARKET_ENTRY_GATE"))


def test_formal_ablation_outputs_reproduce_the_frozen_baseline_and_arm_matrix() -> None:
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    assert summary["formal_replay_executions"] == 6
    assert tuple(summary["formal_run_order"]) == ARM_ORDER
    assert set(summary["arms"]) == set(ARM_ORDER)
    assert summary["identity"]["spec_sha256"] == SPEC_SHA256
    assert summary["identity"]["spec_frozen_before_results"] is True
    assert summary["identity"]["pit_rebuilt"] is False
    assert summary["identity"]["current_survivor_fallback"] is False
    assert summary["identity"]["authorization_valid"] is True

    baseline = summary["arms"]["A0_BASELINE"]
    assert baseline["execution_ledger_sha256"] == EXPECTED_A0_EXECUTION
    assert baseline["daily_nav_sha256"] == EXPECTED_A0_NAV
    assert baseline["total_return"] == 1.0524221580500002
    assert baseline["trade_count"] == 111
    assert baseline["concentration"]["top1_positive_pnl_concentration"] == 0.13276317884259606
    assert baseline["concentration"]["top5_positive_pnl_concentration"] == 0.4096434064997181
    assert baseline["concentration"]["top10_positive_pnl_concentration"] == 0.6230487574354671
    assert baseline["concentration"]["top20_positive_pnl_concentration"] == 0.8425435214865872

    for arm in ARM_ORDER:
        assert summary["arms"][arm]["policy"] == policy_for(arm).to_dict()
        assert summary["arms"][arm]["same_day_fill_count"] == 0
        assert summary["arms"][arm]["stale_held_valuation_count"] == 0


def test_all_formal_arms_share_the_frozen_data_execution_and_strategy_contract() -> None:
    arm_directories = sorted(path.name for path in OUTPUT_ROOT.iterdir() if path.is_dir())
    assert arm_directories == sorted(arm.lower() for arm in ARM_ORDER)

    engine_summaries = {}
    for arm in ARM_ORDER:
        path = OUTPUT_ROOT / arm.lower() / "engine_summary.json"
        engine_summaries[arm] = json.loads(path.read_text(encoding="utf-8"))

    baseline = engine_summaries["A0_BASELINE"]
    for arm, engine in engine_summaries.items():
        assert engine["configuration"] == baseline["configuration"]
        assert engine["configuration"]["transaction_cost_bps"] == 10.0
        assert engine["configuration"]["max_holdings"] == 10
        assert engine["configuration"]["target_weight"] == 0.1
        assert engine["execution"]["transaction_cost_bps_per_side"] == 10.0
        assert engine["execution"]["board_lot"] == 100
        assert engine["execution"]["rank_replacement"] == "OFF"
        assert engine["sample"]["date_range"] == ["2024-01-02", "2025-12-31"]
        assert engine["sample"]["pit_membership_mode"] is True
        assert engine["sample"]["selection_rule"] == (
            "authorized frozen daily PIT membership with listing age >=180; no survivor fallback"
        )
        assert engine["data"]["current_survivor_fallback"] is False
        assert engine["data"]["pit_membership"] == baseline["data"]["pit_membership"]
        assert engine["data"]["daily_root"] == baseline["data"]["daily_root"]
        assert engine["phase3_ablation"] == policy_for(arm).to_dict()
        assert engine["audit"]["stale_held_valuation_count"] == 0
