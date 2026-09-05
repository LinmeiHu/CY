from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "research/market_behavior_os_v2/scripts"
sys.path.insert(0, str(SCRIPTS))

import run_ashare_bull_medium_participation_industry_ignition_v64 as v64  # noqa: E402


def test_v64_contract_mask_is_exact_at_frozen_boundaries() -> None:
    frame = pd.DataFrame(
        {
            "market_breadth20": [0.65],
            "market_breadth60": [0.45],
            "industry_breadth20_delta5": [0.25],
            "ret60": [0.15],
            "step_return": [0.06],
            "turnover_ratio": [1.50],
        }
    )
    assert v64.v64_contract_mask(frame).iloc[0]
    for column, invalid in {
        "market_breadth20": 0.6499,
        "market_breadth60": 0.4499,
        "industry_breadth20_delta5": 0.2499,
        "ret60": 0.1501,
        "step_return": 0.0601,
        "turnover_ratio": 1.4999,
    }.items():
        changed = frame.copy()
        changed.loc[0, column] = invalid
        assert not v64.v64_contract_mask(changed).iloc[0]


def test_stage_a_hashes_and_candidate_clocks_are_frozen() -> None:
    freeze = json.loads(v64.FREEZE.read_text(encoding="utf-8"))
    assert freeze["contract_sha256"] == v64.sha(v64.CONTRACT)
    assert freeze["spec_sha256"] == v64.sha(v64.SPEC)
    assert freeze["runner_sha256"] == v64.sha(Path(v64.__file__))
    assert freeze["source_candidate_sha256"] == v64.sha(v64.SOURCE_CANDIDATES)
    assert freeze["candidate_sha256"] == v64.sha(v64.CANDIDATES)
    assert freeze["candidate_count"] == 2112
    assert freeze["blind_chart_count"] == 30
    assert not any(freeze["audit"].values())

    frame = pd.read_parquet(v64.CANDIDATES)
    for column in (
        "signal_date",
        "trade_date",
        "available_at",
        "decision_at",
        "feature_latest_timestamp",
    ):
        frame[column] = pd.to_datetime(frame[column])
    assert not frame.event_id.duplicated().any()
    assert frame.signal_date.max() <= pd.Timestamp("2023-12-31")
    assert frame.trade_date.dt.normalize().eq(frame.signal_date.dt.normalize()).all()
    assert frame.available_at.le(frame.decision_at).all()
    assert frame.feature_latest_timestamp.le(frame.decision_at).all()
    assert v64.parent.source_contract_mask(frame).all()
    assert v64.v64_contract_mask(frame).all()


def test_frozen_result_meets_all_revised_goal_gates() -> None:
    result = json.loads(v64.RESULT.read_text(encoding="utf-8"))
    assert result["verdict"] == "BULL_MEDIUM_PARTICIPATION_INDUSTRY_IGNITION_TARGET_MET"
    assert all(result["development_gate"].values())
    assert all(result["gate"].values())
    assert result["capacity_accepted_completed_trades"] == 1086
    assert result["average_trades_per_year"] > 50
    assert result["full"]["mean_net"] > 0.03
    assert result["full"]["mean_holding_sessions"] < 15
    assert all(result["annual"][str(year)]["mean_net"] > 0 for year in (2021, 2022, 2023))
    assert all(
        result["signal_date_equal_mean_by_year"][str(year)] > 0 for year in (2021, 2022, 2023)
    )
    assert not any(result["audit"].values())


def test_accepted_execution_is_next_session_and_cost_identity_is_exact() -> None:
    accepted = pd.read_parquet(v64.ACCEPTED)
    accepted["signal_date"] = pd.to_datetime(accepted.signal_date)
    accepted["entry_date"] = pd.to_datetime(accepted.entry_date)
    accepted["exit_date"] = pd.to_datetime(accepted.exit_date)
    assert len(accepted) == 1086
    assert accepted.entry_date.gt(accepted.signal_date).all()
    assert accepted.entry_cal_idx.gt(accepted.signal_cal_idx).all()
    assert accepted.exit_date.gt(accepted.entry_date).all()
    assert accepted.exit_cal_idx.gt(accepted.entry_cal_idx).all()
    assert (accepted.net_return - (accepted.gross_return - 0.004)).abs().max() < 1e-12
    assert accepted.event_id.isin(
        pd.read_parquet(v64.CANDIDATES, columns=["event_id"]).event_id
    ).all()
