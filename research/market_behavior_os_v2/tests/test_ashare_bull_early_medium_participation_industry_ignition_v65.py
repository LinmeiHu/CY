from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
RUNNER = (
    ROOT / "research/market_behavior_os_v2/scripts/"
    "run_ashare_bull_early_medium_participation_industry_ignition_v65.py"
)
sys.path.insert(0, str(RUNNER.parent))
SPEC = importlib.util.spec_from_file_location("v65_runner", RUNNER)
assert SPEC and SPEC.loader
v65 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v65)


def row(**overrides: object) -> pd.DataFrame:
    values: dict[str, object] = {
        "signal_date": pd.Timestamp("2020-06-01"),
        "prior250_peak_date": pd.Timestamp("2019-12-01"),
        "market_breadth20": 0.70,
        "market_breadth60": 0.50,
        "industry_breadth20_delta5": 0.30,
        "ret60": 0.10,
        "step_return": 0.04,
        "turnover_ratio": 2.0,
        "prior250_peak_invalid_cum": 4.0,
        "invalid_step_cum": 4.0,
    }
    values.update(overrides)
    return pd.DataFrame([values])


def test_medium_lane_is_exact_v64_partition() -> None:
    frame = row(market_breadth60=0.45)
    assert bool(v65.medium_mask(frame).iloc[0])
    assert not bool(v65.early_mask(frame).iloc[0])


def test_early_lane_is_mutually_exclusive_and_requires_old_pressure() -> None:
    eligible = row(market_breadth60=0.449, industry_breadth20_delta5=0.60)
    assert bool(v65.early_mask(eligible).iloc[0])
    assert not bool(v65.medium_mask(eligible).iloc[0])
    recent = row(
        market_breadth60=0.449,
        prior250_peak_date=pd.Timestamp("2020-03-01"),
    )
    assert not bool(v65.early_mask(recent).iloc[0])


def test_early_lane_rejects_saturated_industry_acceleration() -> None:
    frame = row(market_breadth60=0.30, industry_breadth20_delta5=0.601)
    assert not bool(v65.early_mask(frame).iloc[0])


def test_early_lane_rejects_prior_peak_from_another_lineage() -> None:
    frame = row(market_breadth60=0.30, prior250_peak_invalid_cum=3.0, invalid_step_cum=4.0)
    assert not bool(v65.early_mask(frame).iloc[0])


def test_common_contract_boundaries_fail_closed() -> None:
    assert bool(v65.common_mask(row()).iloc[0])
    assert not bool(v65.common_mask(row(market_breadth20=0.649)).iloc[0])
    assert not bool(v65.common_mask(row(industry_breadth20_delta5=0.249)).iloc[0])
    assert not bool(v65.common_mask(row(ret60=0.151)).iloc[0])
    assert not bool(v65.common_mask(row(step_return=0.061)).iloc[0])
    assert not bool(v65.common_mask(row(turnover_ratio=1.499)).iloc[0])


def test_peak_age_uses_only_prior_timestamp() -> None:
    frame = row(
        signal_date=pd.Timestamp("2020-06-01"),
        prior250_peak_date=pd.Timestamp("2020-02-02"),
    )
    assert int(v65.peak_age_calendar_days(frame).iloc[0]) == 120
