from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT / "research/market_behavior_os_v2/scripts/run_ashare_downside_resilience_discovery_v1.py"
)
SPEC = (
    ROOT
    / "research/market_behavior_os_v2/experiments/ASHARE-DOWNSIDE-RESILIENCE-DISCOVERY-V1_spec.json"
)


def _module():
    spec = importlib.util.spec_from_file_location("downside_resilience_v1_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_frozen_contract_is_causal_and_pre_2024() -> None:
    frozen = json.loads(SPEC.read_text(encoding="utf-8"))
    assert frozen["status"] == "FROZEN_BEFORE_FORWARD_OUTCOME_ACCESS"
    assert frozen["representations"]["primary"]["minimum_industry_down_observations"] == 5
    assert frozen["timing"]["same_bar_fill"] is False
    assert frozen["timing"]["earliest_entry"].startswith("first accepted legal open strictly after")
    assert frozen["chronology"]["evaluation_outcomes_end_no_later_than"] == "2023-12-31"
    assert frozen["classification_gate"]["parameter_rescue"] is False
    assert any("CY-011" in item for item in frozen["prohibited"])


def test_prior_window_resilience_asymmetry_and_no_current_future_leakage() -> None:
    module = _module()
    rows = []
    for index in range(21):
        industry_return = -0.01 if index % 2 == 0 else 0.01
        residual = 0.02 if industry_return < 0 else -0.005
        rows.append(
            {
                "symbol": "000001.SZ",
                "cal_idx": index,
                "step_return": industry_return + residual,
                "industry_return_loo": industry_return,
            }
        )
    frame = pd.DataFrame(rows)
    result = module.compute_window_features(frame)
    row19 = result.loc[result.cal_idx.eq(19)].iloc[0]
    assert row19.down_count20 == 10
    assert row19.nondown_count20 == 10
    assert row19.ind_down_resilience_20 == pytest.approx(0.02)
    assert row19.ind_downside_asymmetry_20 == pytest.approx(0.025)
    assert row19.ind_relative_strength_20 == pytest.approx(0.15)
    assert bool(row19.window_is_consecutive)
    # Mutating session 20 must not rewrite the feature already formed at session 19.
    frame.loc[frame.cal_idx.eq(20), "step_return"] = 99.0
    changed = module.compute_window_features(frame)
    changed19 = changed.loc[changed.cal_idx.eq(19)].iloc[0]
    assert changed19.ind_down_resilience_20 == pytest.approx(row19.ind_down_resilience_20)


def test_window_fails_closed_across_missing_market_session() -> None:
    module = _module()
    frame = pd.DataFrame(
        {
            "symbol": ["A"] * 20,
            "cal_idx": [*range(10), *range(11, 21)],
            "step_return": [0.01] * 20,
            "industry_return_loo": [-0.01] * 20,
        }
    )
    row = module.compute_window_features(frame).iloc[-1]
    assert not bool(row.window_is_consecutive)


def test_quintiles_are_within_date_and_pressure_context() -> None:
    module = _module()
    frame = pd.DataFrame(
        {
            "trade_date": [pd.Timestamp("2020-01-03").date()] * 10,
            "industry_pressure": [True] * 5 + [False] * 5,
            "score": [1, 2, 3, 4, 5, 101, 102, 103, 104, 105],
        }
    )
    assert module.assign_quintiles(frame, "score").tolist() == [1, 2, 3, 4, 5] * 2


def test_next_open_delay_and_horizon_alignment() -> None:
    module = _module()
    connection = duckdb.connect()
    dates = pd.bdate_range("2020-01-02", periods=25)
    rows = []
    for index, day in enumerate(dates, start=1):
        blocked = index == 1
        rows.append(
            {
                "trade_date": day.date(),
                "symbol": "A",
                "cal_idx": index,
                "history_valid": True,
                "current_valid": True,
                "buy_blocked_open": blocked,
                "coordinate_open": float(100 + index),
                "coordinate_close": float(101 + index),
                "coordinate_low": float(99 + index),
                "bad_prefix": 0,
                "hard_valid": True,
                "trade_status": 1,
                "current_day_data_tradable": True,
                "open": float(100 + index),
                "available_at": day,
            }
        )
    geometry = pd.DataFrame(rows)
    connection.register("geometry_input", geometry)
    connection.execute("CREATE TEMP TABLE raw_geometry AS SELECT * FROM geometry_input")
    signals = pd.DataFrame(
        {
            "signal_id": [0],
            "symbol": ["A"],
            "cal_idx": [0],
            "trade_date": [pd.Timestamp("2020-01-01").date()],
            "industry": ["I"],
        }
    )
    attached, action = module._attach_outcomes(connection, signals)
    connection.close()
    assert attached.entry_status.iloc[0] == "DELAYED"
    assert attached.entry_cal_idx.iloc[0] == 2
    expected_h1 = (103.0 * (1 - module.COST)) / (102.0 * (1 + module.COST)) - 1
    assert attached.net_return_h1.iloc[0] == pytest.approx(expected_h1)
    assert action["delayed"] == 1
    assert action["immediate_block_reasons"] == {"PRICE_LIMIT": 1}


def test_clean_serialization_is_deterministic_and_nonfinite_safe() -> None:
    module = _module()
    value = {"z": np.float64(np.nan), "a": np.int64(3)}
    first = json.dumps(module._clean(value), sort_keys=True)
    second = json.dumps(module._clean(value), sort_keys=True)
    assert first == second == '{"a": 3, "z": null}'
