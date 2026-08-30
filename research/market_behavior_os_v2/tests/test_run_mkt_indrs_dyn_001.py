from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_indrs_dyn_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_indrs_dyn_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
dynamics = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(dynamics)


def test_frozen_spec_and_input_identities() -> None:
    spec = dynamics._load_spec()
    assert dynamics.sha256_file(dynamics.SPEC_PATH) == dynamics.EXPECTED_SPEC_SHA256
    paths = dynamics._input_paths(spec)
    assert dynamics.sha256_file(paths["geometry_panel"]) == spec["inputs"]["geometry_panel"]["sha256"]
    assert dynamics.sha256_file(paths["geometry_result"]) == spec["inputs"]["geometry_result"]["sha256"]
    assert list(spec["edges"]) == [
        "rotation_persistence", "diffusion_to_rotation", "rotation_to_diffusion_change",
    ]


def test_partial_rank_correlation_exact_residual_relation() -> None:
    control = np.arange(1.0, 101.0)
    predictor = np.asarray([(position * 37) % 101 for position in range(100)], dtype=float)
    response = predictor * 2.0 + control * 5.0
    frame = pd.DataFrame({"predictor": predictor, "response": response, "control": control})
    rho, n = dynamics.partial_rank_correlation(frame, "predictor", "response", ["control"])
    assert n == 100
    assert rho > 0.90


def test_future_state_is_exact_five_session_shift() -> None:
    spec = dynamics._load_spec()
    source = dynamics.load_bound_input(spec)
    panel = dynamics.construct_future_states(source, spec)
    group = panel.loc[
        (panel["market_view"] == "ALL_A") & (panel["denominator"] == "ALL_STATUS")
    ].sort_values("trade_date").reset_index(drop=True)
    rotation = spec["fields"]["rank_rotation"]
    response = dynamics._response_name("next_block_rank_rotation5", "raw")
    assert group.loc[0, "future_trade_date"] == group.loc[5, "trade_date"]
    assert group.loc[0, response] == group.loc[5, rotation]
    assert group["future_trade_date"].tail(5).isna().all()
    assert group["response_available_at"].dropna().str.endswith("T15:00:00+08:00").all()


def test_temporal_blocks_require_predictor_and_response_inside() -> None:
    spec = dynamics._load_spec()
    panel = dynamics.construct_future_states(dynamics.load_bound_input(spec), spec)
    discovery = dynamics._block_frame(panel, spec, "discovery")
    confirmation = dynamics._block_frame(panel, spec, "confirmation_untouched_before_specification")
    assert discovery["trade_date"].dt.year.min() == 2019
    assert discovery["future_trade_date"].dt.year.max() == 2021
    assert confirmation["trade_date"].dt.year.min() == 2022
    assert confirmation["future_trade_date"].dt.year.max() == 2023


def test_completed_artifact_boundaries_when_present() -> None:
    if not dynamics.RESULT_PATH.exists() or not dynamics.PANEL_PATH.exists():
        return
    result = json.loads(dynamics.RESULT_PATH.read_text(encoding="utf-8"))
    assert result["future_market_state_fields_read"] == [
        "next_block_rank_rotation5", "future_winner_diffusion_change5",
    ]
    assert result["market_return_fields_read"] == []
    assert result["stock_selection_fields_read"] == []
    assert result["strategy_or_outcome_fields_read"] == []
    assert result["failed_industry_roles_read"] == []
    assert result["failed_ma_industry_fields_read"] == []
    assert result["cy011_read"] is False
    assert result["usefulness_claim"] == "NONE"
    assert dynamics.sha256_file(dynamics.PANEL_PATH) == result["hashes"]["panel_sha256"]
