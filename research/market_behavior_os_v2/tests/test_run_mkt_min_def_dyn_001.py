from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_min_def_dyn_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_min_def_dyn_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
dynamics = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(dynamics)


def test_frozen_spec_and_input_identities() -> None:
    spec = dynamics._load_spec()
    assert dynamics.sha256_file(dynamics.SPEC_PATH) == dynamics.EXPECTED_SPEC_SHA256
    paths = dynamics._input_paths(spec)
    for name, path in paths.items():
        assert dynamics.sha256_file(path) == spec["inputs"][name]["sha256"]
    assert spec["responses"]["primary_horizon_sessions"] == 1
    assert spec["responses"]["neighbor_horizon_sessions"] == [3, 5]


def test_bound_population_and_exact_availability() -> None:
    spec = dynamics._load_spec()
    panel = dynamics.load_bound_input(spec)
    assert len(panel) == spec["population"]["expected_complete_rows"]
    assert panel.groupby(dynamics.GROUP_KEYS).size().eq(954).all()
    assert panel["available_at"].dt.strftime("%H:%M:%S").eq("15:30:00").all()
    assert panel["hard_valid"].all()


def test_future_state_uses_exact_governed_session_shifts() -> None:
    spec = dynamics._load_spec()
    panel = dynamics.construct_future_states(dynamics.load_bound_input(spec), spec)
    group = panel.loc[
        (panel["market_view"] == "ALL_A") & (panel["denominator"] == "ALL_STATUS")
    ].sort_values("trade_date").reset_index(drop=True)
    primary = spec["fields"]["primary"]
    for horizon in (1, 3, 5):
        future_date = dynamics._future_date_name(horizon)
        response = dynamics._response_name(primary, horizon)
        assert group.loc[0, future_date] == group.loc[horizon, "trade_date"]
        assert group.loc[0, response] == group.loc[horizon, primary]
        assert group[future_date].tail(horizon).isna().all()
        available = group[dynamics._response_available_name(horizon)].dropna()
        assert available.str.endswith("T15:30:00+08:00").all()


def test_complete_support_audit_precedes_estimation() -> None:
    spec = dynamics._load_spec()
    panel = dynamics.construct_future_states(dynamics.load_bound_input(spec), spec)
    audit = dynamics.complete_support_audit(panel, spec)
    assert list(audit) == [task["name"] for task in dynamics._tasks(spec)]
    assert len(audit["absolute_primary_h1"][dynamics.BLOCK_NAMES[0]]) == 8
    assert len(audit["h1_relative_to_all"][dynamics.BLOCK_NAMES[0]]) == 6
    assert len(audit["h1_relative_rank"][dynamics.BLOCK_NAMES[0]]) == 2


def test_partial_rank_correlation_recovers_residual_relation() -> None:
    control = np.arange(1.0, 101.0)
    predictor = np.asarray([(position * 37) % 101 for position in range(100)], dtype=float)
    response = predictor * 2.0 + control * 5.0
    frame = pd.DataFrame({"predictor": predictor, "response": response, "control": control})
    unadjusted, partial, n = dynamics.partial_rank_correlation(
        frame, "predictor", "response", ["control"]
    )
    assert n == 100
    assert np.isfinite(unadjusted)
    assert partial > 0.90


def test_completed_artifact_boundaries_when_present() -> None:
    if not dynamics.RESULT_PATH.exists() or not dynamics.PANEL_PATH.exists():
        return
    result = json.loads(dynamics.RESULT_PATH.read_text(encoding="utf-8"))
    assert result["usefulness_claim"] == "NONE"
    assert result["cross_day_support_claim"] == "NONE"
    assert result["participant_accumulation_claim"] == "NONE"
    assert result["future_market_state_fields_read"] == ["vwap_defense_recovery"]
    assert result["future_price_return_fields_read"] == []
    assert result["future_volatility_fields_read"] == []
    assert result["future_industry_or_stock_state_fields_read"] == []
    assert result["strategy_or_outcome_fields_read"] == []
    assert result["failed_minute_roles_read"] == []
    assert result["raw_minute_rows_read"] is False
    assert result["post_2023_data_read"] is False
    assert result["cy011_read"] is False
    assert result["confirmation_status"] == "NO_UNTOUCHED_CONFIRMATION_REUSED_PRE2024_BLOCKS"
    assert dynamics.sha256_file(dynamics.PANEL_PATH) == result["hashes"]["panel_sha256"]
