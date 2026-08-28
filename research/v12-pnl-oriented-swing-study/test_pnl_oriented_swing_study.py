from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

import pandas as pd

RUNNER = Path(__file__).with_name("run_pnl_oriented_swing_study.py")
SPEC = importlib.util.spec_from_file_location("pnl_study", RUNNER)
assert SPEC is not None and SPEC.loader is not None
STUDY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = STUDY
SPEC.loader.exec_module(STUDY)


def test_next_legal_position_never_uses_signal_bar() -> None:
    frame = pd.DataFrame({"legal_buy_open": [True, False, True, True]})
    assert STUDY.next_legal_position(frame, 1, "legal_buy_open", maximum_wait=3) == 2
    assert STUDY.next_legal_position(frame, 3, "legal_buy_open", maximum_wait=1) == 3


def test_cost_model_reduces_return_without_changing_gross() -> None:
    gross, net, transaction_cost = STUDY._fill_return(100.0, [(1.0, 110.0)], STUDY.CostModel())
    assert math.isclose(gross, 0.10)
    assert net < gross
    assert math.isclose(transaction_cost, gross - net)


def test_temporal_filters_are_nested_and_missing_fails_closed() -> None:
    trades = pd.DataFrame(
        {
            "entry_temporal_state": ["VALID_CANONICAL_BASE", "ENSEMBLE_AMBIGUOUS", "SPLIT"],
            "entry_peak_track_age": [30, math.nan, 40],
            "entry_peak_track_mass": [0.8, math.nan, 0.9],
            "entry_peak_track_prominence": [0.7, math.nan, 0.9],
        }
    )
    thresholds = {"entry_peak_track_mass_median": 0.5, "entry_peak_track_prominence_median": 0.5}
    p1 = STUDY.overlay_acceptance(trades, "P1", thresholds)
    p2 = STUDY.overlay_acceptance(trades, "P2", thresholds)
    p3 = STUDY.overlay_acceptance(trades, "P3", thresholds)
    assert p1.tolist() == [True, True, False]
    assert p2.tolist() == [True, False, False]
    assert p3.tolist() == [True, False, False]


def test_candidate_and_trade_ids_are_deterministic() -> None:
    first = STUDY.stable_id("cpe", "fingerprint", "000001.SZ", "2020-04-01")
    second = STUDY.stable_id("cpe", "fingerprint", "000001.SZ", "2020-04-01")
    changed = STUDY.stable_id("cpe", "fingerprint", "000001.SZ", "2020-04-02")
    assert first == second
    assert first != changed


def test_frozen_outputs_preserve_candidate_and_t_plus_one_invariants() -> None:
    output = Path(__file__).with_name("results")
    candidates = pd.read_parquet(output / "candidate_universe.parquet")
    trades = pd.read_parquet(output / "price_baseline_trades.parquet")
    assert len(candidates) == STUDY.EXPECTED_CANDIDATE_ROWS
    assert candidates["candidate_episode_id"].nunique() == STUDY.EXPECTED_CANDIDATE_EPISODES
    filled = trades[trades["actual_entry_timestamp"].notna()]
    completed = trades[trades["completed"]]
    assert (
        pd.to_datetime(filled["actual_entry_timestamp"])
        > pd.to_datetime(filled["entry_signal_timestamp"])
    ).all()
    assert filled["entry_wait_sessions"].le(5).all()
    assert (
        pd.to_datetime(completed["actual_exit_timestamp"])
        > pd.to_datetime(completed["exit_trigger_timestamp"])
    ).all()


def test_result_manifest_hashes_match_delivered_artifacts() -> None:
    root = Path(__file__).parent
    output = root / "results"
    manifest = json.loads((output / "result_manifest.json").read_text(encoding="utf-8"))
    for name, metadata in manifest["artifacts"].items():
        path = root / name if name.endswith(".md") else output / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == metadata["sha256"]
