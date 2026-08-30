from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_breakout_diff_dyn_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_breakout_diff_dyn_001", SCRIPT)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
runner = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(runner)


def test_temporal_operators_linear_and_quadratic() -> None:
    linear = runner.temporal_operators(pd.Series(np.arange(31, dtype=float)))
    assert linear["change"].iloc[10] == 1.0
    assert linear["change_neighbor_ols5"].iloc[10] == 1.0
    assert linear["change_neighbor_theilsen5"].iloc[10] == 1.0
    assert linear["acceleration"].iloc[10] == 0.0

    time = np.arange(31, dtype=float)
    quadratic = runner.temporal_operators(pd.Series(time**2))
    assert quadratic["acceleration"].iloc[20] == 10.0
    assert quadratic["acceleration_neighbor_h3"].iloc[20] == 6.0
    assert quadratic["acceleration_neighbor_h10"].iloc[20] == 20.0
    assert quadratic["acceleration_neighbor_ols5"].iloc[20] == 10.0
    assert quadratic["acceleration_neighbor_theilsen5"].iloc[20] == 10.0


def test_missing_session_is_not_compressed() -> None:
    values = pd.Series(np.arange(20, dtype=float))
    values.iloc[5] = np.nan
    operators = runner.temporal_operators(values)
    assert np.isnan(operators["change"].iloc[10])
    assert operators["change"].iloc[11] == 1.0
    assert np.isnan(operators["change_neighbor_ols5"].iloc[10])


def test_bound_panel_uses_only_completed_historical_levels() -> None:
    spec = runner._load_spec()
    levels, breadth = runner._load_inputs(spec)
    panel = runner.construct_panel(levels, breadth, spec)
    group = panel.loc[
        panel["market_view"].eq("ALL_A") & panel["denominator"].eq("ALL_STATUS")
    ].sort_values("trade_date")
    position = 20
    source = group["formation_participation__level"].to_numpy(float)
    expected = (source[position] - source[position - 5]) / 5.0
    assert group["formation_participation__change"].iloc[position] == expected
    assert group["dynamic_available_at"].iloc[position].endswith("15:00:00+08:00")
    assert panel["trade_date"].max() <= pd.Timestamp("2023-12-31")


def test_complete_run_has_exact_scalar_cases_and_no_forbidden_reads() -> None:
    result = runner.run()
    assert result["population"]["rows"] == 11336
    assert result["population"]["roles_attempted"] == 14
    assert len(result["scalar_cases"]) == 5
    assert all(case["exact_match"] for case in result["scalar_cases"])
    assert not result["future_values_read"]
    assert result["strategy_or_outcome_fields_read"] == []
    assert result["raw_security_rows_read"] == 0
    assert result["raw_minute_rows_read"] == 0
    assert not result["cy011_read"]
