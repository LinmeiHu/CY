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
    / "research/market_behavior_os_v2/scripts"
    / "run_ashare_shock_absorption_recovery_discovery_v1_1.py"
)
SPEC = (
    ROOT
    / "research/market_behavior_os_v2/experiments"
    / "ASHARE-SHOCK-ABSORPTION-RECOVERY-DISCOVERY-V1-1_spec.json"
)


def _module():
    module_spec = importlib.util.spec_from_file_location("shock_absorption_v1_1_test", SCRIPT)
    assert module_spec is not None and module_spec.loader is not None
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    return module


def test_frozen_contract_has_exact_grid_and_causal_time_boundary() -> None:
    frozen = json.loads(SPEC.read_text(encoding="utf-8"))
    assert frozen["status"] == "FROZEN_BEFORE_V1_1_GRID_OUTCOME_ACCESS_AFTER_V1_RESULT_KNOWN"
    assert frozen["parameter_grid"]["absolute_simple_return_thresholds"] == [
        -0.04,
        -0.06,
        -0.08,
    ]
    assert frozen["parameter_grid"]["industry_relative_simple_return_thresholds"] == [
        -0.02,
        -0.04,
    ]
    assert frozen["parameter_grid"]["absorption_windows_sessions"] == [2, 3, 5]
    assert frozen["parameter_grid"]["total_cells"] == 18
    assert frozen["event"]["same_close_fill"] is False
    assert frozen["outcomes"]["maximum_outcome_date"] == "2023-12-31"
    assert frozen["classification"]["portfolio_replay"] is False
    assert any("post-2023" in item for item in frozen["prohibited"])
    assert any("CY-011" in item for item in frozen["prohibited"])


def test_all_six_shock_definitions_and_eighteen_cells_are_exact() -> None:
    module = _module()
    cells = module.grid_cells()
    assert len(cells) == 18
    assert len({item["cell_id"] for item in cells}) == 18
    definitions = {(item["absolute_threshold"], item["relative_threshold"]) for item in cells}
    assert definitions == {
        (-0.04, -0.02),
        (-0.04, -0.04),
        (-0.06, -0.02),
        (-0.06, -0.04),
        (-0.08, -0.02),
        (-0.08, -0.04),
    }
    assert module.qualifies_shock(math.log1p(-0.061), math.log1p(-0.020), -0.06, -0.04)
    assert not module.qualifies_shock(math.log1p(-0.059), math.log1p(-0.010), -0.06, -0.04)
    assert not module.qualifies_shock(math.log1p(-0.061), math.log1p(-0.030), -0.06, -0.04)


def test_shock_uses_leave_one_out_industry_return_not_self_contaminated_proxy() -> None:
    module = _module()
    stock = math.log1p(-0.061)
    pit_leave_one_out_industry = math.log1p(-0.010)
    self_contaminated_proxy = math.log1p(-0.030)
    assert module.qualifies_shock(stock, pit_leave_one_out_industry, -0.06, -0.04)
    assert not module.qualifies_shock(stock, self_contaminated_proxy, -0.06, -0.04)


@pytest.mark.parametrize(
    ("closes", "expected_recovery", "expected_drawdown"),
    [
        ([88.0, 92.0], 0.2, 0.2),
        ([88.0, 91.0, 95.0], 0.5, 0.2),
        ([88.0, 91.0, 95.0, 96.0, 98.0], 0.8, 0.2),
    ],
)
def test_exact_absorption_windows_and_metrics(
    closes: list[float], expected_recovery: float, expected_drawdown: float
) -> None:
    module = _module()
    recovery, drawdown = module.absorption_metrics(100.0, 90.0, closes)
    assert recovery == pytest.approx(expected_recovery)
    assert drawdown == pytest.approx(expected_drawdown)


def test_overlap_suppression_uses_each_cells_exact_window() -> None:
    module = _module()
    frame = pd.DataFrame(
        {
            "symbol": ["A"] * 7,
            "shock_cal_idx": [10, 12, 13, 14, 15, 16, 17],
            "shock_date": pd.date_range("2020-01-01", periods=7).date,
        }
    )
    assert module.suppress_overlapping_events(frame, 2).shock_cal_idx.tolist() == [10, 13, 16]
    assert module.suppress_overlapping_events(frame, 3).shock_cal_idx.tolist() == [10, 14]
    assert module.suppress_overlapping_events(frame, 5).shock_cal_idx.tolist() == [10, 16]


def test_complete_path_materialization_preserves_w2_w3_w5_without_lookahead() -> None:
    module = _module()
    connection = duckdb.connect()
    closes = [100.0, 90.0, 88.0, 92.0, 95.0, 96.0, 98.0]
    panel = {
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
    }
    for offset in range(1, 6):
        panel[f"next_cal_idx_{offset}"] = [10 + offset]
        panel[f"next_step_return_{offset}"] = [math.log(closes[offset + 1] / closes[offset])]
        panel[f"next_industry_return_{offset}"] = [0.0]
    for window in (2, 3, 5):
        panel[f"signal_date_{window}"] = [pd.Timestamp("2020-01-02") + pd.offsets.BDay(window)]
        panel[f"signal_max_return20_{window}"] = [0.03]
        panel[f"signal_diffusion_score_{window}"] = [0.4]
    geometry = pd.DataFrame(
        {
            "symbol": ["A"] * 7,
            "cal_idx": list(range(9, 16)),
            "history_valid": [True] * 7,
            "coordinate_close": closes,
        }
    )
    connection.register("panel_input", pd.DataFrame(panel))
    connection.register("geometry_input", geometry)
    connection.execute("CREATE TEMP TABLE panel_features AS SELECT * FROM panel_input")
    connection.execute("CREATE TEMP TABLE raw_geometry AS SELECT * FROM geometry_input")
    module._build_complete_paths(connection)
    row = connection.execute(
        """SELECT recovery_fraction_w2,recovery_fraction_w3,recovery_fraction_w5,
          further_drawdown_ratio_w2,further_drawdown_ratio_w3,further_drawdown_ratio_w5
        FROM complete_paths"""
    ).fetchone()
    connection.close()
    assert row == pytest.approx((0.2, 0.5, 0.8, 0.2, 0.2, 0.2))


def test_window_projection_has_fixed_schema_and_hides_post_signal_closes() -> None:
    module = _module()
    w2 = module._path_projection(2)
    w5 = module._path_projection(5)
    assert "CAST(NULL AS DOUBLE) observation_close_3" in w2
    assert "CAST(NULL AS DOUBLE) observation_close_5" in w2
    assert "p.observation_close_5 observation_close_5" in w5


def test_quintiles_are_within_cell_and_confirmation_date() -> None:
    module = _module()
    day = pd.Timestamp("2020-01-03").date()
    frame = pd.DataFrame(
        {
            "cell_id": ["A"] * 5 + ["B"] * 5,
            "signal_date": [day] * 10,
            "score": [1, 2, 3, 4, 5, 101, 102, 103, 104, 105],
        }
    )
    assert module.assign_quintiles(frame, "score").tolist() == [1, 2, 3, 4, 5] * 2


def test_region_topology_and_center_selection_are_deterministic() -> None:
    module = _module()
    component = [
        "ABS_m04_REL_m02_W2",
        "ABS_m06_REL_m02_W2",
        "ABS_m06_REL_m04_W2",
        "ABS_m06_REL_m04_W3",
    ]
    assert module.region_spans(component)
    assert module.choose_region(module.connected_components(set(component))) == sorted(component)
    assert module.region_center(component) == "ABS_m06_REL_m04_W2"
    assert module.region_center(list(reversed(component))) == "ABS_m06_REL_m04_W2"


def test_walk_forward_training_ignores_post_cutoff_outcomes() -> None:
    module = _module()
    rows = []
    anchor = module.ANCHOR
    for index in range(10):
        quintile = 1 if index < 5 else 5
        row = {
            "cell_id": anchor,
            "sample_type": "SHOCK",
            "signal_date": pd.Timestamp("2020-06-01").date(),
            "outcome_date_h20": pd.Timestamp("2020-12-01" if index < 8 else "2021-02-01"),
            "recovery_quintile": quintile,
            "symbol": f"S{index}",
            "industry": "I",
        }
        for horizon in (5, 10, 20):
            value = 0.01 if quintile == 5 else 0.0
            row[f"net_return_h{horizon}"] = value
            row[f"industry_relative_h{horizon}"] = value
            row["mae_h20"] = -0.01
        rows.append(row)
    panel = pd.DataFrame(rows)
    before = module._training_selection(panel, "2020-12-31")["cell_summaries"][anchor]
    panel.loc[pd.to_datetime(panel.outcome_date_h20).dt.year.eq(2021), "net_return_h20"] = 99.0
    panel.loc[pd.to_datetime(panel.outcome_date_h20).dt.year.eq(2021), "industry_relative_h20"] = (
        99.0
    )
    after = module._training_selection(panel, "2020-12-31")["cell_summaries"][anchor]
    assert before == after


def test_walk_forward_application_excludes_outcomes_after_year_end() -> None:
    module = _module()
    panel = pd.DataFrame(
        {
            "cell_id": [module.ANCHOR, module.ANCHOR],
            "signal_date": [pd.Timestamp("2021-12-01").date()] * 2,
            "outcome_date_h20": [
                pd.Timestamp("2021-12-29").date(),
                pd.Timestamp("2022-01-03").date(),
            ],
        }
    )
    eligible = module._application_subset(panel, module.ANCHOR, 2021, 20)
    assert eligible.index.tolist() == [0]


def test_post_2023_outcome_boundary_fails_closed() -> None:
    module = _module()
    row = {"signal_date": pd.Timestamp("2023-11-01").date()}
    for horizon in module.HORIZONS:
        row[f"outcome_date_h{horizon}"] = pd.Timestamp("2023-12-29").date()
    assert module.validate_outcome_boundary(pd.DataFrame([row])).isoformat() == "2023-12-29"
    row["outcome_date_h20"] = pd.Timestamp("2024-01-02").date()
    with pytest.raises(module.ShockNeighborhoodError, match="post-2023 outcome"):
        module.validate_outcome_boundary(pd.DataFrame([row]))


def test_next_open_delay_and_horizon_alignment() -> None:
    module = _module()
    connection = duckdb.connect()
    dates = pd.bdate_range("2020-01-02", periods=25)
    geometry = pd.DataFrame(
        [
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
            for index, day in enumerate(dates, start=1)
        ]
    )
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
    attached, action = module.EXECUTION._attach_outcomes(connection, signals)
    connection.close()
    assert attached.entry_status.iloc[0] == "DELAYED"
    assert attached.entry_cal_idx.iloc[0] == 2
    expected = (103.0 * (1 - module.EXECUTION.COST)) / (102.0 * (1 + module.EXECUTION.COST)) - 1
    assert attached.net_return_h1.iloc[0] == pytest.approx(expected)
    assert action["delayed"] == 1


def test_clean_serialization_is_deterministic_and_nonfinite_safe() -> None:
    module = _module()
    value = {"z": np.float64(np.nan), "a": np.int64(3)}
    first = json.dumps(module._clean(value), sort_keys=True)
    second = json.dumps(module._clean(value), sort_keys=True)
    assert first == second == '{"a": 3, "z": null}'
