from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_indrs_tail_dyn_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_indrs_tail_dyn_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
dynamics = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(dynamics)


def test_frozen_spec_and_input_identities() -> None:
    spec = dynamics._load_spec()
    assert dynamics.sha256_file(dynamics.SPEC_PATH) == dynamics.EXPECTED_SPEC_SHA256
    paths = dynamics._input_paths(spec)
    for name, path in paths.items():
        assert dynamics.sha256_file(path) == spec["inputs"][name]["sha256"]
    assert list(spec["edges"]) == [
        "tail_balance_nonoverlap_persistence",
        "concentration_nonoverlap_persistence",
        "concentration_to_future_tail_balance",
        "tail_balance_to_future_concentration",
    ]
    assert spec["temporal_blocks"]["evidence_label"] == (
        "REUSED_PRE2024_EXPLORATORY_REPLICATION_NOT_CONFIRMATION"
    )


def test_partial_rank_correlation_exact_residual_relation() -> None:
    control = np.arange(1.0, 101.0)
    predictor = np.asarray([(position * 37) % 101 for position in range(100)], dtype=float)
    response = predictor * 2.0 + control * 5.0
    frame = pd.DataFrame({"predictor": predictor, "response": response, "control": control})
    rho, observations = dynamics.partial_rank_correlation(
        frame, "predictor", "response", ["control"]
    )
    assert observations == 100
    assert rho > 0.90


def test_future_state_is_exact_twenty_session_shift() -> None:
    spec = dynamics._load_spec()
    source = dynamics.load_bound_input(spec)
    panel = dynamics.construct_future_states(source, spec)
    group = panel.loc[
        (panel["market_view"] == "ALL_A") & (panel["denominator"] == "ALL_STATUS")
    ].sort_values("trade_date").reset_index(drop=True)
    tail = spec["fields"]["tail_balance"]
    concentration = spec["fields"]["residual_concentration"]
    assert group.loc[0, "future_trade_date"] == group.loc[20, "trade_date"]
    assert group.loc[0, dynamics._response_name("future_tail_balance20", "raw")] == group.loc[
        20, tail
    ]
    assert group.loc[
        0, dynamics._response_name("future_residual_concentration20", "raw")
    ] == group.loc[20, concentration]
    assert group["future_trade_date"].tail(20).isna().all()
    assert group["response_available_at"].dropna().str.endswith("T15:00:00+08:00").all()


def test_temporal_blocks_require_predictor_and_response_inside() -> None:
    spec = dynamics._load_spec()
    panel = dynamics.construct_future_states(dynamics.load_bound_input(spec), spec)
    block_a = dynamics._block_frame(panel, spec, "block_a_reused")
    block_b = dynamics._block_frame(panel, spec, "block_b_reused")
    assert block_a["trade_date"].dt.year.min() == 2019
    assert block_a["future_trade_date"].dt.year.max() == 2021
    assert block_b["trade_date"].dt.year.min() == 2022
    assert block_b["future_trade_date"].dt.year.max() == 2023


def test_cross_edges_control_current_response_state() -> None:
    spec = dynamics._load_spec()
    assert spec["edges"]["concentration_to_future_tail_balance"]["controls"][0] == (
        "tail_balance"
    )
    assert spec["edges"]["tail_balance_to_future_concentration"]["controls"][0] == (
        "residual_concentration"
    )
    assert spec["estimation"]["coupled_process_rule"].startswith("both cross-edges")


def test_completed_artifact_boundaries_when_present() -> None:
    if not dynamics.RESULT_PATH.exists() or not dynamics.PANEL_PATH.exists():
        return
    result = json.loads(dynamics.RESULT_PATH.read_text(encoding="utf-8"))
    assert result["evidence_label"] == (
        "REUSED_PRE2024_EXPLORATORY_REPLICATION_NOT_CONFIRMATION"
    )
    assert result["confirmation_status"] == "INDEPENDENT_FUTURE_TIME_REQUIRED"
    for name in (
        "market_return_fields_read",
        "industry_return_fields_read",
        "stock_return_fields_read",
        "future_security_identity_fields_read",
        "stock_selection_fields_read",
        "strategy_or_outcome_fields_read",
        "failed_industry_roles_read",
        "failed_temporal_edges_read",
        "failed_ma_industry_fields_read",
    ):
        assert result[name] == []
    assert result["post_2023_data_read"] is False
    assert result["cy011_read"] is False
    assert result["usefulness_claim"] == "NONE"
    assert dynamics.sha256_file(dynamics.PANEL_PATH) == result["hashes"]["panel_sha256"]
