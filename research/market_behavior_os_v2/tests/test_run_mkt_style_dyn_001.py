from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_style_dyn_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_style_dyn_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
dynamics = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(dynamics)


def test_frozen_spec_and_source_identities() -> None:
    spec = dynamics._load_spec()
    assert dynamics.sha256_file(dynamics.SPEC_PATH) == dynamics.EXPECTED_SPEC_SHA256
    paths = dynamics._input_paths(spec)
    dynamics._validate_results(paths)


def test_future_states_are_exact_later_group_shifts() -> None:
    spec = dynamics._load_spec()
    source, _ = dynamics.load_bound_inputs(spec)
    panel = dynamics.construct_future_states(source, spec)
    primary = dynamics._primary_fields(spec)["raw"]
    for _, group in panel.sort_values(dynamics.GROUP_KEYS + ["trade_date"]).groupby(
        dynamics.GROUP_KEYS, sort=True
    ):
        assert group[dynamics._future_date_name(5)].equals(group["trade_date"].shift(-5))
        assert group[dynamics._response_name(primary, 5)].equals(group[primary].shift(-5))
    observed = panel[dynamics._future_date_name(5)].notna()
    assert (
        panel.loc[observed, dynamics._future_date_name(5)]
        > panel.loc[observed, "trade_date"]
    ).all()


def test_partial_rank_correlation_removes_fixed_control() -> None:
    rng = np.random.default_rng(7)
    control = np.linspace(-2.0, 2.0, 500)
    predictor = control + rng.normal(0.0, 0.05, len(control))
    response = control + rng.normal(0.0, 0.05, len(control))
    frame = pd.DataFrame({"predictor": predictor, "response": response, "control": control})
    unadjusted, partial, observations = dynamics.partial_rank_correlation(
        frame, "predictor", "response", ["control"]
    )
    assert observations == 500
    assert unadjusted > 0.95
    assert abs(partial) < 0.15


def test_within_date_partial_correlation_removes_date_levels() -> None:
    rows = []
    views = {"ALL_A", "SH_A", "SZ_A", "CHINEXT_BOARD"}
    for position, date in enumerate(pd.date_range("2021-01-01", periods=200, freq="D")):
        for view_position, view in enumerate(sorted(views)):
            x = float(view_position)
            control = float((view_position * 3 + position) % 4)
            rows.append(
                {
                    "trade_date": date,
                    "market_view": view,
                    "predictor": position * 100.0 + x,
                    "response": -position * 50.0 + 2.0 * x + 0.2 * control,
                    "control": position * 25.0 + control,
                }
            )
    _, partial, observations, dates = dynamics.partial_within_date_correlation(
        pd.DataFrame(rows), "predictor", "response", ["control"], views
    )
    assert observations == 800
    assert dates == 200
    assert partial > 0.99


def test_completed_artifact_boundaries_when_present() -> None:
    if not dynamics.RESULT_PATH.exists() or not dynamics.PANEL_PATH.exists():
        return
    result = json.loads(dynamics.RESULT_PATH.read_text(encoding="utf-8"))
    assert result["usefulness_claim"] == "NONE"
    assert result["size_premium_claim"] == "NONE"
    assert result["strategy_or_habitat_claim"] == "NONE"
    assert result["future_market_payoff_fields_read"] == []
    assert result["future_stock_selection_fields_read"] == []
    assert result["strategy_or_outcome_fields_read"] == []
    assert result["failed_or_redundant_size_predictors_read"] == []
    assert result["post_2023_data_read"] is False
    assert result["cy011_read"] is False
    assert dynamics.sha256_file(dynamics.PANEL_PATH) == result["hashes"]["panel_sha256"]
