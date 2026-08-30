from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_industry_context_decomposition as industry


def test_primary_components_form_exact_stock_market_decomposition() -> None:
    frame = pd.DataFrame(
        {
            "stock_ret20": [0.20],
            "peer20_mean": [0.12],
            "index_return_20d": [0.05],
        }
    )
    industry_component = frame.peer20_mean - frame.index_return_20d
    stock_component = frame.stock_ret20 - frame.peer20_mean
    assert (industry_component + stock_component).iloc[0] == (
        frame.stock_ret20 - frame.index_return_20d
    ).iloc[0]


def test_competing_primary_components_and_neighbors_are_fixed() -> None:
    assert industry.PRIMARY == (
        "industry_market_relative20",
        "stock_industry_residual20",
    )
    assert industry.COMPANION["industry_market_relative20"] == "stock_industry_residual20"
    assert industry.MEAN_MEDIAN_NEIGHBOR["stock_industry_residual20"] == (
        "stock_industry_residual20_median"
    )
