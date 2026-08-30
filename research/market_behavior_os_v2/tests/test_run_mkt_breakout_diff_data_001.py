from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_breakout_diff_data_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location(
    "run_mkt_breakout_diff_data_001_tested", RUNNER
)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
module = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(module)


def _nested_frame() -> pd.DataFrame:
    records = []
    values = {
        "ALL_A": (30, 12, 6, 1, 5),
        "SH_A": (10, 4, 2, 0, 2),
        "SZ_A": (20, 8, 4, 1, 3),
        "CHINEXT_BOARD": (5, 2, 1, 0, 1),
    }
    for lookback in (10, 20, 40):
        for denominator, scale in (("ALL_STATUS", 1), ("NON_ST", 1)):
            for market_view, counts in values.items():
                eligible, crossing, above, equal, below = [int(value * scale) for value in counts]
                records.append(
                    {
                        "lookback": lookback,
                        "trade_date": pd.Timestamp("2023-01-03"),
                        "market_view": market_view,
                        "denominator": denominator,
                        "eligible_count": eligible,
                        "crossing_count": crossing,
                        "close_above_count": above,
                        "close_equal_count": equal,
                        "close_below_count": below,
                    }
                )
    return pd.DataFrame(records)


def test_frozen_spec_identity_loads() -> None:
    spec = module._load_spec()
    assert spec["experiment_id"] == "MKT-BREAKOUT-DIFF-DATA-001"
    assert spec["outcome_access"] is False


def test_view_and_denominator_nesting_accepts_exact_partition() -> None:
    result = module.verify_view_and_denominator_nesting(_nested_frame())
    assert all(result.values())


def test_view_nesting_fails_closed_on_first_difference() -> None:
    frame = _nested_frame()
    mask = (
        frame["lookback"].eq(20)
        & frame["denominator"].eq("ALL_STATUS")
        & frame["market_view"].eq("SZ_A")
    )
    frame.loc[mask, "crossing_count"] += 1
    with pytest.raises(module.BreakoutDiffusionDataError, match="nesting failed"):
        module.verify_view_and_denominator_nesting(frame)
