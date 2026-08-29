from __future__ import annotations

import ast
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "research/chinext_v1/scripts"
sys.path.insert(0, str(SCRIPTS))

from run_chinext_v1_phase5_extra_path import (  # noqa: E402
    ARM_PATHS,
    EXPECTED,
    PHASE4_CROWDOUT,
    OUTPUT_JSON,
    OUTPUT_PAIRS,
    OUTPUT_TRADES,
    build_cycles,
    read_jsonl,
    validate_inputs,
)
from run_chinext_v1_smoke import sha256_file  # noqa: E402

SCRIPT = SCRIPTS / "run_chinext_v1_phase5_extra_path.py"


def test_phase5_script_has_no_formal_replay_call_or_strategy_mutation() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "run" not in imported_names
    assert "run" not in called_names
    assert "FORMAL_REPLAY_EXECUTIONS: `0`" in SCRIPT.read_text(encoding="utf-8")


def test_all_frozen_phase5_inputs_validate_without_survivor_fallback() -> None:
    hashes = validate_inputs()
    assert hashes["reports"]["strategy"] == EXPECTED["strategy"]
    assert hashes["reports"]["pit_manifest"] == EXPECTED["pit_manifest"]
    for arm, directory in ARM_PATHS.items():
        engine = json.loads((directory / "engine_summary.json").read_text(encoding="utf-8"))
        assert engine["data"]["current_survivor_fallback"] is False, arm
        assert engine["sample"]["date_range"] == ["2024-01-02", "2025-12-31"]


def test_frozen_arm_trade_episode_identities_have_expected_counts() -> None:
    expected_counts = {
        "A0_BASELINE": (121, 111),
        "A2_MINUS_B60_RAW": (249, 239),
        "A3_MINUS_FULL40_RAW": (217, 207),
        "M2_MINUS_B60_MATCHED": (139, 129),
        "M3_MINUS_FULL40_MATCHED": (120, 110),
    }
    selected_by_arm = {}
    for arm, directory in ARM_PATHS.items():
        cycles, selected = build_cycles(read_jsonl(directory / "execution_ledger.jsonl"))
        assert (len(selected), len(cycles)) == expected_counts[arm]
        assert len({(row["symbol"], row["entry_signal_date"]) for row in cycles}) == len(cycles)
        selected_by_arm[arm] = selected
    baseline = selected_by_arm["A0_BASELINE"]
    assert len(selected_by_arm["A2_MINUS_B60_RAW"] - baseline) > 0
    assert len(selected_by_arm["A3_MINUS_FULL40_RAW"] - baseline) > 0
    assert len(selected_by_arm["M2_MINUS_B60_MATCHED"] - baseline) > 0
    assert len(selected_by_arm["M3_MINUS_FULL40_MATCHED"] - baseline) > 0


def test_phase4_crowdout_episode_identities_remain_exact() -> None:
    assert sha256_file(PHASE4_CROWDOUT) == EXPECTED["phase4_crowdout"]
    with PHASE4_CROWDOUT.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 40
    keys = {
        (row["raw_arm"], row["baseline_rank"], row["symbol"], row["entry_signal_date"])
        for row in rows
    }
    assert len(keys) == 40
    assert sum(row["finite_capacity_crowdout"] == "True" for row in rows) == 31


def test_phase5_outputs_are_offline_only_and_cover_exact_extra_episode_sets() -> None:
    summary = json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
    assert summary["formal_replay_executions"] == 0
    assert summary["identity"]["formal_replay_executions"] == 0
    assert summary["identity"]["pit_rebuilt"] is False
    assert summary["identity"]["current_survivor_fallback"] is False
    assert summary["phase5_result"] == "PASS"
    with OUTPUT_TRADES.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 632
    assert len({(row["arm"], row["symbol"], row["entry_signal_date"]) for row in rows}) == 632

    selected = {}
    completed = {}
    for arm, directory in ARM_PATHS.items():
        cycles, selected_episodes = build_cycles(read_jsonl(directory / "execution_ledger.jsonl"))
        selected[arm] = selected_episodes
        completed[arm] = {
            (row["symbol"], row["entry_signal_date"]): row for row in cycles
        }
    baseline = selected["A0_BASELINE"]
    for row in rows:
        episode = (row["symbol"], row["entry_signal_date"])
        assert episode in selected[row["arm"]]
        assert episode not in baseline
        frozen = completed[row["arm"]].get(episode)
        if row["completed"] == "True":
            assert frozen is not None
            assert row["entry_execution_date"] == frozen["entry_execution_date"]
            assert row["exit_execution_date"] == frozen["exit_execution_date"]
            assert float(row["realized_return"]) == frozen["realized_return"]
        else:
            assert frozen is None


def test_phase5_path_metrics_are_known_completed_episodes_and_terminal_checked() -> None:
    with OUTPUT_TRADES.open(encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row["completed"] == "True"]
    assert len(rows) == 598
    for row in rows:
        assert float(row["MFE"]) + 1e-12 >= float(row["realized_return"])
        assert float(row["MAE"]) - 1e-12 <= float(row["realized_return"])
        assert int(float(row["days_to_MFE"])) <= int(float(row["holding_trading_days"]))
        assert float(row["giveback_from_peak"]) >= -1e-12
        assert row["path_basis"].startswith("frozen execution cash flows")


def test_phase5_crowdout_pairs_preserve_all_phase4_finite_capacity_identities() -> None:
    with PHASE4_CROWDOUT.open(encoding="utf-8", newline="") as handle:
        frozen = [row for row in csv.DictReader(handle) if row["finite_capacity_crowdout"] == "True"]
    with OUTPUT_PAIRS.open(encoding="utf-8", newline="") as handle:
        pairs = list(csv.DictReader(handle))
    assert len(pairs) == len(frozen) == 31
    frozen_keys = {
        (row["raw_arm"], row["baseline_rank"], row["symbol"], row["entry_signal_date"])
        for row in frozen
    }
    pair_keys = {
        (
            row["crowdout_arm"],
            row["baseline_rank"],
            row["baseline_winner_symbol"],
            row["baseline_entry_signal_date"],
        )
        for row in pairs
    }
    assert pair_keys == frozen_keys
    assert all(row["counterfactual_status"] == "NOT_A_PORTFOLIO_COUNTERFACTUAL" for row in pairs)
    assert all(row["blocking_extra_count"] != "0" for row in pairs)


def test_m3_alternative_top20_is_a_complete_different_frozen_right_tail() -> None:
    summary = json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
    alternative = summary["alternative_right_tail"]
    a0 = alternative["A0_TOP20"]["trades"]
    m3 = alternative["M3_TOP20"]["trades"]
    assert len(a0) == len(m3) == 20
    assert [row["rank"] for row in a0] == list(range(1, 21))
    assert [row["rank"] for row in m3] == list(range(1, 21))
    a0_keys = {(row["symbol"], row["entry_signal_date"]) for row in a0}
    m3_keys = {(row["symbol"], row["entry_signal_date"]) for row in m3}
    assert not a0_keys & m3_keys
    assert alternative["exact_episode_overlap"] == 0
    assert alternative["assessment"] == "DIFFERENT_RIGHT_TAIL_REGIME"
