from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_min_ad_geo_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_min_ad_geo_001", SCRIPT)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
runner = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(runner)


def test_join_uses_later_availability_and_exact_return_relative() -> None:
    spec = runner._load_spec()
    panel = runner.load_panel(spec)
    assert len(panel) == 11336
    assert panel["joint_available_at"].str.endswith("15:30:00").all()
    cell = panel.groupby(["trade_date", "denominator"], sort=True).get_group(
        (panel["trade_date"].iloc[0], panel["denominator"].iloc[0])
    )
    raw = spec["fixed_alternatives"]["open_close_return"]["raw"]
    all_a = float(cell.loc[cell["market_view"].eq("ALL_A"), raw].iloc[0])
    assert np.allclose(
        cell["open_close_return__relative_to_all"], cell[raw] - all_a, atol=0.0, rtol=0.0
    )


def test_coordinate_groups_preserve_fixed_estimands() -> None:
    spec = runner._load_spec()
    panel = runner.load_panel(spec)
    assert len(runner._analysis_groups(panel, "pit")) == 8
    assert len(runner._analysis_groups(panel, "relative_to_all")) == 6
    assert len(runner._analysis_groups(panel, "relative_rank")) == 2


def test_complete_run_preserves_no_future_claim_boundary() -> None:
    result = runner.run()
    assert result["population"]["rows"] == 11336
    assert result["population"]["joint_available_at"] == "15:30 Asia/Shanghai"
    assert not result["future_values_read"]
    assert result["strategy_or_outcome_fields_read"] == []
    assert result["raw_security_rows_read"] == 0
    assert result["raw_minute_rows_read"] == 0
    assert not result["cy011_read"]
