from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "research/market_behavior_os_v2/scripts"
sys.path.insert(0, str(SCRIPTS))

import run_ashare_bull_quiet_platform_dual_demand_v24 as v24  # noqa: E402


def test_stage_a_identity_and_hashes_are_frozen() -> None:
    freeze = json.loads(v24.FREEZE.read_text())
    assert freeze["contract_sha256"] == v24.v1.sha256(v24.CONTRACT)
    assert freeze["spec_sha256"] == v24.v1.sha256(v24.SPEC)
    assert freeze["runner_sha256"] == v24.v1.sha256(Path(v24.__file__))
    assert freeze["state_sha256"] == v24.v1.sha256(v24.STATE)
    assert freeze["candidate_sha256"] == v24.v1.sha256(v24.CANDIDATES)
    assert freeze["blind_pdf_sha256"] == v24.v1.sha256(v24.BLIND_PDF)
    assert freeze["source_sha256"] == v24.v1.sha256(v24.SOURCE)
    assert freeze["candidate_count"] == 751
    assert not any(freeze["audit"].values())


def test_candidate_clock_and_lane_semantics_are_causal_and_exclusive() -> None:
    frame = pd.read_parquet(v24.CANDIDATES)
    for column in (
        "signal_date",
        "decision_at",
        "available_at",
        "formation_known_at",
        "feature_latest_timestamp",
    ):
        frame[column] = pd.to_datetime(frame[column])
    assert not frame.event_id.duplicated().any()
    assert frame.signal_date.max() <= pd.Timestamp("2023-12-31")
    assert frame.available_at.le(frame.decision_at).all()
    assert frame.formation_known_at.le(frame.decision_at).all()
    assert frame.feature_latest_timestamp.le(frame.decision_at).all()
    lane_count = (
        frame.pass_SYNCHRONIZED_MAJORITY_DEMAND.astype(int)
        + frame.pass_IDIOSYNCRATIC_INFORMATION_JUMP.astype(int)
    )
    assert lane_count.eq(1).all()
    sync = frame.loc[frame.pass_SYNCHRONIZED_MAJORITY_DEMAND]
    assert sync.market_median_ret1.gt(0).all()
    assert sync.market_positive_ret1_share.gt(0.50).all()
    assert sync.industry_median_ret1.gt(0).all()
    assert sync.industry_positive_ret1_share.gt(0.50).all()
    idio = frame.loc[frame.pass_IDIOSYNCRATIC_INFORMATION_JUMP]
    assert idio.open_gap.ge(0.02).all()
    assert not idio.pass_SYNCHRONIZED_MAJORITY_DEMAND.any()


def test_frozen_result_meets_every_goal_gate_without_execution_violations() -> None:
    result = json.loads(v24.RESULT.read_text())
    assert result["verdict"] == "BULL_QUIET_PLATFORM_DUAL_DEMAND_TARGET_MET"
    assert all(result["gate"].values())
    assert result["capacity_accepted_completed_trades"] > 500
    assert result["average_trades_per_year"] > 50
    assert result["full_2014_2023"]["mean_net"] > 0.03
    assert result["full_2014_2023"]["mean_holding_sessions"] <= 15
    assert all(result["annual"][str(year)]["mean_net"] > 0 for year in range(2019, 2024))
    assert not any(result["audit"].values())
    assert result["repository_2024_plus_rows_used_for_signal_or_feature"] == 0


def test_accepted_trade_execution_and_cost_identity() -> None:
    accepted = pd.read_parquet(v24.ACCEPTED)
    accepted["signal_date"] = pd.to_datetime(accepted.signal_date)
    accepted["entry_date"] = pd.to_datetime(accepted.entry_date)
    accepted["exit_date"] = pd.to_datetime(accepted.exit_date)
    assert len(accepted) == 547
    assert accepted.entry_date.gt(accepted.signal_date).all()
    assert accepted.exit_date.gt(accepted.entry_date).all()
    assert accepted.exit_cal_idx.gt(accepted.entry_cal_idx).all()
    assert (accepted.net_return - (accepted.gross_return - 0.004)).abs().max() < 1e-12
    assert accepted.event_id.isin(pd.read_parquet(v24.CANDIDATES, columns=["event_id"]).event_id).all()
