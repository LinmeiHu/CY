from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT
    / "research/market_behavior_os_v2/scripts/run_ashare_shock_absorption_recovery_discovery_v1.py"
)
SPEC = (
    ROOT
    / "research/market_behavior_os_v2/experiments"
    / "ASHARE-SHOCK-ABSORPTION-RECOVERY-DISCOVERY-V1_spec.json"
)


def _module():
    module_spec = importlib.util.spec_from_file_location("shock_absorption_v1_test", SCRIPT)
    assert module_spec is not None and module_spec.loader is not None
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    return module


def test_frozen_contract_is_causal_pre_2024_and_has_no_replay() -> None:
    frozen = json.loads(SPEC.read_text(encoding="utf-8"))
    assert frozen["status"] == "FROZEN_BEFORE_FORWARD_OUTCOME_ACCESS"
    assert frozen["shock"]["both_required"] is True
    assert frozen["observation"]["window"].startswith("exactly three")
    assert frozen["observation"]["earliest_entry"].startswith(
        "first accepted legal open strictly after s+3"
    )
    assert frozen["chronology"]["evaluation_outcomes_end_no_later_than"] == "2023-12-31"
    assert frozen["classification"]["portfolio_replay_in_this_run"] is False
    assert any("post-2023" in item for item in frozen["prohibited"])
    assert any("CY-011" in item for item in frozen["prohibited"])


def test_joint_shock_requires_absolute_and_industry_relative_thresholds() -> None:
    module = _module()
    assert module.qualifies_shock(math.log1p(-0.051), math.log1p(-0.020))
    assert not module.qualifies_shock(math.log1p(-0.049), math.log1p(-0.010))
    assert not module.qualifies_shock(math.log1p(-0.051), math.log1p(-0.030))


def test_duckdb_simple_return_expression_matches_python_expm1() -> None:
    log_return = math.log1p(-0.051)
    sql_return = duckdb.execute("SELECT exp(?)-1", [log_return]).fetchone()[0]
    assert sql_return == pytest.approx(math.expm1(log_return))


def test_exact_three_session_absorption_metrics() -> None:
    module = _module()
    recovery, further_drawdown = module.absorption_metrics(100.0, 90.0, [88.0, 91.0, 95.0])
    assert recovery == pytest.approx(0.5)
    assert further_drawdown == pytest.approx(0.2)
    with pytest.raises(module.ShockAbsorptionError):
        module.absorption_metrics(100.0, 90.0, [88.0, 91.0])


def test_complete_path_materialization_preserves_exact_three_session_sequence() -> None:
    module = _module()
    connection = duckdb.connect()
    panel_row = pd.DataFrame(
        {
            "trade_date": [pd.Timestamp("2020-01-02").date()],
            "cal_idx": [10],
            "symbol": ["A"],
            "industry": ["I"],
            "step_return": [math.log(0.9)],
            "industry_return_loo": [math.log(0.98)],
            "prior_count20": [20],
            "prior_start_cal_idx": [-10],
            "pre_shock_trend20": [0.1],
            "pre_shock_volatility20": [0.02],
            "avg_amount20": [1e8],
            "signal_date_3": [pd.Timestamp("2020-01-07").date()],
            "next_cal_idx_1": [11],
            "next_cal_idx_2": [12],
            "next_cal_idx_3": [13],
            "next_step_return_1": [math.log(88 / 90)],
            "next_step_return_2": [math.log(91 / 88)],
            "next_step_return_3": [math.log(95 / 91)],
            "next_industry_return_1": [0.0],
            "next_industry_return_2": [0.0],
            "next_industry_return_3": [0.0],
            "signal_max_return20": [0.03],
            "signal_diffusion_score": [0.4],
        }
    )
    geometry = pd.DataFrame(
        {
            "symbol": ["A"] * 5,
            "cal_idx": [9, 10, 11, 12, 13],
            "history_valid": [True] * 5,
            "coordinate_close": [100.0, 90.0, 88.0, 91.0, 95.0],
        }
    )
    connection.register("panel_input", panel_row)
    connection.register("geometry_input", geometry)
    connection.execute("CREATE TEMP TABLE panel_features AS SELECT * FROM panel_input")
    connection.execute("CREATE TEMP TABLE raw_geometry AS SELECT * FROM geometry_input")
    module._build_complete_paths(connection)
    row = connection.execute(
        "SELECT recovery_fraction_3,further_drawdown_ratio_3 FROM complete_paths"
    ).fetchone()
    connection.close()
    assert row == pytest.approx((0.5, 0.2))


def test_overlap_suppression_allows_s_plus_four_and_is_symbol_specific() -> None:
    module = _module()
    frame = pd.DataFrame(
        {
            "symbol": ["A", "A", "A", "A", "B"],
            "shock_cal_idx": [10, 12, 13, 14, 12],
            "shock_date": pd.date_range("2020-01-01", periods=5).date,
        }
    )
    accepted = module.suppress_overlapping_events(frame)
    assert accepted.loc[accepted.symbol.eq("A"), "shock_cal_idx"].tolist() == [10, 14]
    assert accepted.loc[accepted.symbol.eq("B"), "shock_cal_idx"].tolist() == [12]


def test_quintiles_are_assigned_within_sample_and_confirmation_date() -> None:
    module = _module()
    day = pd.Timestamp("2020-01-03").date()
    frame = pd.DataFrame(
        {
            "sample_type": ["SHOCK"] * 5 + ["NONSHOCK"] * 5,
            "signal_date": [day] * 10,
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
        rows.append(
            {
                "trade_date": day.date(),
                "symbol": "A",
                "cal_idx": index,
                "history_valid": True,
                "current_valid": True,
                "buy_blocked_open": index == 1,
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
    connection.register("geometry_input", pd.DataFrame(rows))
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
    attached, action = module.EXECUTION._attach_outcomes(connection, signals)
    connection.close()
    assert attached.entry_status.iloc[0] == "DELAYED"
    assert attached.entry_cal_idx.iloc[0] == 2
    expected_h1 = (103.0 * (1 - module.EXECUTION.COST)) / (102.0 * (1 + module.EXECUTION.COST)) - 1
    assert attached.net_return_h1.iloc[0] == pytest.approx(expected_h1)
    assert action["delayed"] == 1
    assert action["immediate_block_reasons"] == {"PRICE_LIMIT": 1}


def test_clean_serialization_is_deterministic_and_nonfinite_safe() -> None:
    module = _module()
    value = {"z": np.float64(np.nan), "a": np.int64(3)}
    first = json.dumps(module._clean(value), sort_keys=True)
    second = json.dumps(module._clean(value), sort_keys=True)
    assert first == second == '{"a": 3, "z": null}'
