from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

import pandas as pd


RUNNER = Path(__file__).with_name("run_chip_economic_attribution.py")
SPEC = importlib.util.spec_from_file_location("chip_economic_attribution", RUNNER)
assert SPEC is not None and SPEC.loader is not None
STUDY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = STUDY
SPEC.loader.exec_module(STUDY)


def test_soft_risk_states_are_exact_bounded_and_never_filter() -> None:
    frame = pd.DataFrame(
        {
            "entry_temporal_state": [
                "VALID_CANONICAL_BASE",
                "ENSEMBLE_AMBIGUOUS",
                "SPLIT",
                "MERGE",
                "LOST/TRANSITION",
            ]
        }
    )
    assert STUDY.risk_tier(frame).tolist() == ["FAVORABLE", "UNCERTAIN", "WEAK", "WEAK", "WEAK"]
    assert STUDY.soft_sizes(frame, "S1").tolist() == [1.0, 0.75, 0.5, 0.5, 0.5]
    assert STUDY.soft_sizes(frame, "S2").tolist() == [1.0, 0.5, 0.25, 0.25, 0.25]


def test_p6_holdout_accounting_identity_and_terminal_sign_dependence() -> None:
    table = pd.read_csv(Path(__file__).with_name("results") / "p6_pnl_reconciliation.csv")
    row = table[table["record_type"].eq("ACCOUNTING_IDENTITY")].iloc[0]
    assert math.isclose(
        row["end_equity"] - row["start_equity"],
        row["realized_net_pnl"] + row["terminal_unrealized_net_pnl"],
        rel_tol=0.0,
        abs_tol=1e-12,
    )
    assert math.isclose(row["portfolio_net_return"], row["portfolio_reported_return"], rel_tol=0.0, abs_tol=2e-12)
    assert row["portfolio_net_return"] > 0
    assert row["return_without_terminal_unrealized_pnl"] < 0
    assert int(row["terminal_open_positions"]) == 7


def test_holdout_winner_waterfall_localizes_92_to_6_collapse() -> None:
    table = pd.read_csv(Path(__file__).with_name("results") / "winner_survival_waterfall.csv")
    holdout = table[table["split"].eq("holdout")].sort_values("stage_number")
    assert holdout["baseline_top_decile_winners_remaining"].tolist() == [92, 71, 16, 6, 6, 6, 6]
    destructive = holdout.sort_values("incremental_top_decile_winners_lost", ascending=False).iloc[0]
    assert destructive["stage"] == "P2_CANONICAL_PERSISTENCE"
    assert int(destructive["incremental_top_decile_winners_lost"]) == 55


def test_d1_is_exact_noop_and_deterioration_fills_after_warning() -> None:
    comparison = pd.read_csv(Path(__file__).with_name("results") / "deterioration_response_comparison.csv")
    for split in ("validation", "holdout"):
        p0 = comparison[(comparison["variant"].eq("P0_PRICE_ONLY")) & comparison["split"].eq(split)].iloc[0]
        d1 = comparison[(comparison["variant"].eq("DETERIORATION_D1_BLOCK_ADDS")) & comparison["split"].eq(split)].iloc[0]
        for column in ("net_return", "max_drawdown", "exposure", "turnover"):
            assert math.isclose(p0[column], d1[column], rel_tol=0.0, abs_tol=1e-14)
    summary = pd.read_csv(Path(__file__).with_name("results") / "top_winner_intervention_summary.csv")
    warned = summary[summary["p6_partial_exit_date"].notna()]
    if len(warned):
        assert (pd.to_datetime(warned["p6_partial_exit_date"]) > pd.to_datetime(warned["baseline_entry_date"])).all()


def test_manifest_hashes_and_scope_contract() -> None:
    root = Path(__file__).parent
    output = root / "results"
    manifest = json.loads((output / "result_manifest.json").read_text(encoding="utf-8"))
    for name, metadata in manifest["artifacts"].items():
        path = root / name if name.endswith(".md") else output / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == metadata["sha256"]
    contract = manifest["research_object_contract"]
    assert contract["production_code_modified"] is False
    assert contract["v3_temporal_semantics_modified"] is False
    assert contract["frozen_candidate_universe_modified"] is False
    assert contract["full_market_3941_build_started"] is False
    assert manifest["hard_gates"]["SAFE_TO_IMPLEMENT_NEW_PRODUCTION_STRATEGY"] == "NO"
    assert manifest["hard_gates"]["SAFE_TO_EXPAND_RESEARCH_TO_FULL_MARKET_3941"] == "NO"
