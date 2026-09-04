from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import run_ashare_causal_market_substrategy_router_v18 as subject  # noqa: E402


def test_bull_acceleration_gate_fails_closed_and_is_inclusive() -> None:
    frame = pd.DataFrame(
        {
            "market_median_ret20": [0.05, 0.04, np.nan, np.inf],
            "market_median_ret60": [0.05, 0.05, 0.02, 0.01],
        }
    )
    assert subject.bull_acceleration_mask(frame).tolist() == [True, False, False, False]


def test_router_keeps_bear_and_only_accelerating_bull() -> None:
    frame = pd.DataFrame(
        {
            "event_id": ["bear", "bull_fast", "bull_slow"],
            "market_route": ["BEAR", "BULL", "BULL"],
            "market_median_ret20": [-0.02, 0.08, 0.02],
            "market_median_ret60": [-0.06, 0.05, 0.07],
        }
    )
    routed, cash = subject.route_lanes(frame)
    assert routed.event_id.tolist() == ["bear", "bull_fast"]
    assert routed.router_state.tolist() == ["BEAR_REPAIR", "BULL_ACCELERATING"]
    assert cash.event_id.tolist() == ["bull_slow"]
    assert cash.router_state.tolist() == ["BULL_DECELERATING_CASH"]


def test_candidate_selection_ignores_challenge_returns() -> None:
    rows = []
    for year, ret20, ret60, outcome in (
        (2020, 0.08, 0.04, 0.10),
        (2020, 0.02, 0.06, -0.10),
        (2021, 0.08, 0.04, -10.0),
        (2021, 0.02, 0.06, 10.0),
    ):
        rows.append(
            {
                "signal_date": pd.Timestamp(f"{year}-06-01"),
                "market_median_ret20": ret20,
                "market_median_ret60": ret60,
                "market_positive_ret20_share": 0.70,
                "market_positive_ret60_share": 0.70,
                "net_return": outcome,
                "exit_reason": "TARGET_10" if outcome > 0 else "H20_TIME_STOP",
                "holding_sessions": 10,
            }
        )
    table = subject.evaluate_bull_candidates(pd.DataFrame(rows))
    acceleration = table.loc[table.candidate.eq("RETURN_ACCELERATION")].iloc[0]
    assert acceleration.selection_rows == 1
    assert acceleration.mean_net == 0.10
    assert pd.Timestamp(acceleration.latest_selection_signal_date).year == 2020
