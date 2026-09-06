from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import run_ashare_causal_bear_strong_bull_dual_engine_v17_challenge as challenge  # noqa: E402


def valid_path(closes: list[float]) -> pd.DataFrame:
    rows = []
    for offset, close in enumerate(closes, start=1):
        rows.append(
            {
                "trade_date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=offset),
                "cal_idx": 100 + offset,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "coord_open": close,
                "coord_high": close,
                "coord_low": close,
                "coord_close": close,
                "coordinate_factor": 1.0,
                "invalid_step_cum": 0.0,
                "trade_status": 1,
                "current_day_data_tradable": True,
                "current_valid": True,
                "market_rule_valid": True,
                "corporate_action_valid": True,
                "corporate_action_blocking": False,
                "hard_valid": True,
                "up_limit_price": close * 1.10,
                "down_limit_price": close * 0.90,
            }
        )
    return pd.DataFrame(rows)


def test_market_labels_use_current_and_prior_rows_only() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": pd.date_range("2024-01-01", periods=7),
            "market_median_ret20": [0.01] * 7,
            "market_positive_ret20_share": [0.70] * 7,
            "market_median_ret60": [0.06] * 7,
            "market_positive_ret60_share": [0.70] * 7,
        }
    )
    labeled = challenge.label_market(frame)
    assert labeled.strong_bull.all()
    assert pd.isna(labeled.iloc[4].positive_ret20_share_lag5)
    assert labeled.iloc[5].positive_ret20_share_lag5 == 0.70


def test_cooldown_is_applied_before_v10_routing() -> None:
    frame = pd.DataFrame(
        {
            "symbol": ["000001.SZ"] * 3,
            "signal_date": pd.to_datetime(["2024-01-01", "2024-01-10", "2024-02-15"]),
            "cal_idx": [100, 110, 122],
        }
    )
    selected = challenge.apply_cooldown(frame)
    assert selected.cal_idx.tolist() == [100, 122]


def test_third_session_acceptance_is_not_a_same_bar_fill() -> None:
    candidate = SimpleNamespace(
        event_id="QIG-20240101-000001.SZ",
        symbol="000001.SZ",
        sleeve="MAIN",
        signal_date=pd.Timestamp("2024-01-01"),
        signal_cal_idx=100,
        signal_invalid_step_cum=0.0,
        platform_high=10.0,
        state_source_timestamp=pd.Timestamp("2024-01-01 15:00:00"),
        candidate_source="TEST",
    )
    accepted = challenge.freeze_acceptance_one(
        candidate, valid_path([9.8, 9.9, 10.1, 10.2])
    )
    assert accepted["acceptance_status"] == "ACCEPTED"
    assert accepted["acceptance_decision_cal_idx"] == 103

    rejected = challenge.freeze_acceptance_one(
        candidate, valid_path([10.2, 10.1, 9.9, 11.0])
    )
    assert rejected["acceptance_status"] == "REJECTED_NOT_ACCEPTED"


def test_replay_entry_is_strictly_after_decision() -> None:
    candidate = SimpleNamespace(
        event_id="QIG-20240101-000001.SZ",
        symbol="000001.SZ",
        sleeve="MAIN",
        signal_date=pd.Timestamp("2024-01-01"),
        signal_cal_idx=100,
        signal_invalid_step_cum=0.0,
        acceptance_decision_cal_idx=103,
    )
    outcome = challenge.replay_after_decision(
        candidate, valid_path([10.0] * 64 + [12.0]), bear=False
    )
    assert outcome["entry_cal_idx"] == 104
    assert outcome["entry_cal_idx"] > outcome["decision_cal_idx"]
