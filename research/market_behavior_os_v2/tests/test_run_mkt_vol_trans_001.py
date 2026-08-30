from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_vol_trans_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_vol_trans_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
transition = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(transition)


def test_frozen_spec_and_input_identities() -> None:
    spec = transition._load_spec()
    assert transition.sha256_file(transition.SPEC_PATH) == transition.EXPECTED_SPEC_SHA256
    paths = transition._input_paths(spec)
    for name, path in paths.items():
        assert transition.sha256_file(path) == spec["inputs"][name]["sha256"]
    assert spec["population"]["future_shift_sessions"] == 25
    assert list(spec["habitat_modifiers"]) == ["direction", "discovery"]
    assert spec["temporal_blocks"]["evidence_label"] == (
        "REUSED_PRE2024_EXPLORATORY_REPLICATION_NOT_CONFIRMATION"
    )


def test_bound_populations_and_availability() -> None:
    spec = transition._load_spec()
    base, trend = transition.load_bound_inputs(spec)
    assert len(base) == spec["population"]["base_rows"]
    assert len(trend) == 6 * spec["population"]["rows_per_base_group"]
    assert base.groupby(["market_view", "denominator"]).size().eq(1337).all()
    assert trend.groupby("index_symbol").size().eq(1337).all()
    assert base["volatility_decision_at"].str.endswith("T15:00:00+08:00").all()


def test_future_state_is_exact_twenty_five_session_shift() -> None:
    spec = transition._load_spec()
    base, _ = transition.load_bound_inputs(spec)
    panel = transition.construct_future_state(base, spec)
    group = panel.loc[
        (panel["market_view"] == "ALL_A") & (panel["denominator"] == "ALL_STATUS")
    ].sort_values("trade_date").reset_index(drop=True)
    raw = spec["fields"]["volatility_change"]
    assert group.loc[0, "future_trade_date"] == group.loc[25, "trade_date"]
    assert group.loc[0, transition._response_name("raw")] == group.loc[25, raw]
    assert group["future_trade_date"].tail(25).isna().all()
    assert group["response_available_at"].dropna().str.endswith("T15:00:00+08:00").all()


def test_partial_rank_correlation_exact_residual_relation() -> None:
    control = np.arange(1.0, 101.0)
    predictor = np.asarray([(position * 37) % 101 for position in range(100)], dtype=float)
    response = predictor * 2.0 + control * 5.0
    frame = pd.DataFrame({"predictor": predictor, "response": response, "control": control})
    rho, observations = transition.partial_rank_correlation(
        frame, "predictor", "response", ["control"]
    )
    assert observations == 100
    assert rho > 0.90


def test_frozen_habitat_masks() -> None:
    spec = transition._load_spec()
    frame = pd.DataFrame({"habitat": [0.40, 0.50, 0.55, 0.60]})
    low, high, minimum = transition._split_masks(frame, "habitat", spec, "primary")
    assert low.tolist() == [True, True, False, False]
    assert high.tolist() == [False, False, True, True]
    assert minimum == 150
    low, high, minimum = transition._split_masks(
        frame, "habitat", spec, "shape_neighbor"
    )
    assert low.tolist() == [True, False, False, False]
    assert high.tolist() == [False, False, False, True]
    assert minimum == 120


def test_completed_artifact_boundaries_when_present() -> None:
    if not transition.RESULT_PATH.exists() or not transition.PANEL_PATH.exists():
        return
    result = json.loads(transition.RESULT_PATH.read_text(encoding="utf-8"))
    assert result["evidence_label"] == (
        "REUSED_PRE2024_EXPLORATORY_REPLICATION_NOT_CONFIRMATION"
    )
    assert result["confirmation_status"] == "INDEPENDENT_FUTURE_TIME_REQUIRED"
    for name in (
        "future_price_return_fields_read",
        "strategy_or_outcome_fields_read",
        "failed_volatility_roles_read",
        "failed_breadth_roles_read",
        "failed_trend_roles_read",
    ):
        assert result[name] == []
    assert result["post_2023_data_read"] is False
    assert result["cy011_read"] is False
    assert result["usefulness_claim"] == "NONE"
    assert transition.sha256_file(transition.PANEL_PATH) == result["hashes"]["panel_sha256"]
