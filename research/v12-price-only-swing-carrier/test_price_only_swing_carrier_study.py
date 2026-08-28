from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

import pandas as pd


RUNNER = Path(__file__).with_name("run_price_only_swing_carrier_study.py")
SPEC = importlib.util.spec_from_file_location("price_only_carrier_study", RUNNER)
assert SPEC is not None and SPEC.loader is not None
STUDY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = STUDY
SPEC.loader.exec_module(STUDY)


def test_carrier_family_is_small_price_only_and_preregistered() -> None:
    assert tuple(STUDY.CARRIER_DEFINITIONS) == (
        "A_PULLBACK_RECLAIM",
        "B_LOCAL_BREAKOUT",
        "C_TREND_RESUMPTION",
    )
    assert STUDY.RISK_CONTRACT["same_bar_fill"] is False
    assert STUDY.PORTFOLIO_CONTRACT["maximum_concurrent_positions"] == 10


def test_next_legal_position_starts_after_signal_and_respects_deadline() -> None:
    frame = pd.DataFrame({"legal_buy_open": [True, False, False, True, True]})
    assert STUDY.next_legal_position(frame, 1, "legal_buy_open", 3) == 3
    assert STUDY.next_legal_position(frame, 1, "legal_buy_open", 2) is None


def test_costs_reduce_completed_trade_return() -> None:
    gross, net, cost = STUDY.trade_return(100.0, 110.0, True, STUDY.CostModel.named("BASE"))
    assert math.isclose(gross, 0.10)
    assert net < gross
    assert math.isclose(cost, gross - net)


def test_frozen_candidate_identity_and_episode_ids() -> None:
    candidate = pd.read_parquet(STUDY.SOURCE_CANDIDATES)
    assert hashlib.sha256(STUDY.SOURCE_CANDIDATES.read_bytes()).hexdigest() == STUDY.EXPECTED_CANDIDATE_SHA256
    assert len(candidate) == STUDY.EXPECTED_CANDIDATE_ROWS
    assert candidate["candidate_episode_id"].nunique() == STUDY.EXPECTED_EPISODES


def test_delivered_funnel_and_t_plus_one_invariants() -> None:
    output = RUNNER.with_name("results")
    trades = pd.read_parquet(output / "carrier_trade_results.parquet")
    funnels = pd.read_csv(output / "entry_conversion_funnel.csv")
    assert len(trades) == STUDY.EXPECTED_EPISODES * len(STUDY.CARRIER_DEFINITIONS)
    assert funnels.groupby("carrier")["candidate_episodes"].sum().eq(STUDY.EXPECTED_EPISODES).all()
    filled = trades[trades["actual_fill"]]
    completed = trades[trades["completed"]]
    assert (pd.to_datetime(filled["actual_entry_at"]) > pd.to_datetime(filled["entry_signal_at"])).all()
    assert (pd.to_datetime(filled["actual_entry_at"]) >= pd.to_datetime(filled["next_legal_execution_at"])).all()
    assert (pd.to_datetime(completed["actual_exit_at"]) > pd.to_datetime(completed["exit_signal_at"])).all()
    assert filled["legal_fill_wait_sessions"].le(STUDY.RISK_CONTRACT["legal_fill_wait_source_sessions"]).all()


def test_outputs_preserve_split_isolation_and_manifest_hashes() -> None:
    output = RUNNER.with_name("results")
    trades = pd.read_parquet(output / "carrier_trade_results.parquet")
    for split, (_, end) in STUDY.SPLIT_BOUNDS.items():
        subset = trades[trades["split"].eq(split)]
        timestamps = pd.concat([pd.to_datetime(subset["actual_entry_at"]), pd.to_datetime(subset["actual_exit_at"])]).dropna()
        assert timestamps.dt.normalize().le(end).all()
    manifest = json.loads((output / "result_manifest.json").read_text(encoding="utf-8"))
    assert manifest["hard_gates"]["CHIP_DATA_USED_IN_CARRIER_SELECTION"] == "NO"
    assert manifest["hard_gates"]["SAFE_TO_DESIGN_PRODUCTION_SWING_STRATEGY"] == "NO"
    for name, metadata in manifest["artifacts"].items():
        path = RUNNER.parent / name if name.endswith(".md") else output / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == metadata["sha256"]
