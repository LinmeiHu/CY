from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
RUNNER = (
    ROOT
    / "research/market_behavior_os_v2/scripts/"
    "run_ashare_bull_breadth_rotation_bounded_ceiling_v26.py"
)
sys.path.insert(0, str(RUNNER.parent))
SPEC = importlib.util.spec_from_file_location("bull_breadth80_v26", RUNNER)
assert SPEC and SPEC.loader
v26 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v26)


def passing_row() -> dict[str, object]:
    return {
        "market_regime": "BULL",
        "market_positive_ret20_share": 0.80,
        "industry_n20": 10,
        "industry_median_ret20": 0.01,
        "industry_positive_ret20_share": 0.51,
        "industry_ret20_percentile": 0.50,
        "history_n120": 120,
        "coord_close": 10.01,
        "prior120_high": 10.00,
        "previous_close": 9.90,
        "previous_prior120_high": 10.00,
        "signal_close_location": 0.70,
        "turnover_expansion": 1.50,
        "prior_ret20": 0.00,
        "prior120_range": 0.60,
        "step_return": 0.02,
    }


def test_rule_boundaries_are_frozen_and_inclusive() -> None:
    row = passing_row()
    assert bool(v26.rule_mask(pd.DataFrame([row])).iloc[0])
    failures = {
        "market_positive_ret20_share": 0.799999,
        "industry_ret20_percentile": 0.500001,
        "prior120_range": 0.600001,
        "step_return": 0.070001,
        "signal_close_location": 0.699999,
        "turnover_expansion": 1.499999,
    }
    for field, value in failures.items():
        changed = {**row, field: value}
        assert not bool(v26.rule_mask(pd.DataFrame([changed])).iloc[0]), field


def test_contract_is_complementary_and_uses_strict_target() -> None:
    contract = v26.contract_value()
    assert contract["required_gate"]["mean_net_return_gt"] == 0.05
    assert contract["required_gate"]["mean_holding_sessions_lt"] == 15
    assert "uses no information-gap identity" in contract["complementarity_to_v24"]
    assert set(contract["four_simple_rules"]) == {
        "BREADTH80_BULL",
        "HEALTHY_NONCROWDED_INDUSTRY",
        "FIRST_CAUSAL_CEILING_RELAY",
        "BOUNDED_MODERATE_DEMAND",
    }


def test_frozen_candidate_and_result_audits_are_zero() -> None:
    frame = v26.v1.read_parquet_duckdb(v26.CANDIDATES)
    for column in (
        "signal_date",
        "decision_at",
        "available_at",
        "market_latest_source",
        "industry_latest_source",
        "feature_latest_timestamp_v26",
    ):
        frame[column] = pd.to_datetime(frame[column])
    assert len(frame) == 881
    assert all(value == 0 for value in v26.candidate_audit(frame).values())
    result = json.loads(v26.RESULT.read_text())
    assert result["capacity_accepted_completed_trades"] == 533
    assert result["average_trades_per_year"] > 50
    assert result["full_2014_2023"]["mean_net"] > 0.05
    assert result["full_2014_2023"]["mean_holding_sessions"] < 15
    assert all(result["gate"].values())
    assert all(value == 0 for value in result["audit"].values())
    assert result["repository_2024_plus_rows_used_for_signal_or_feature"] == 0
