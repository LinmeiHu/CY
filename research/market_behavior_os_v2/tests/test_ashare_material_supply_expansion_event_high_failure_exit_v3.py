import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_material_supply_expansion_event_high_failure_exit_v3 as v3,
)


def test_frozen_exit_constants() -> None:
    assert v3.TIME_EXIT_SESSIONS == 120
    assert v3.MINIMUM_ANNUAL_COMPLETED_STRICT == 50
    assert v3.ROUND_TRIP_COST == 0.004


def test_two_below_high_closes_schedule_next_open_exit(monkeypatch) -> None:
    selected = pd.DataFrame(
        [
            {
                "event_id": "E", "symbol": "S", "sleeve": "MAIN",
                "pit_industry": "I", "signal_date": pd.Timestamp("2020-01-01"),
                "signal_year": 2020, "signal_cal_idx": 0, "event_high": 10.0,
                "entry_date": pd.Timestamp("2020-01-03"), "entry_cal_idx": 2,
                "status": "COMPLETED", "exit_date": pd.NaT, "exit_cal_idx": None,
                "exit_reason": None, "holding_market_sessions": None,
            }
        ]
    ).itertuples(index=False).__next__()
    rows = []
    for idx, close in enumerate([10.2, 9.9, 9.8, 9.7], start=1):
        rows.append(
            {
                "cal_idx": idx,
                "trade_date": pd.Timestamp("2020-01-01") + pd.Timedelta(days=idx),
                "coord_open": close,
                "coord_high": close + 0.1,
                "coord_low": close - 0.1,
                "coord_close": close,
                "invalid_step_cum": 0.0,
                "available_at": pd.Timestamp("2020-01-01 15:00") + pd.Timedelta(days=idx),
                "decision_at": pd.Timestamp("2020-01-01 15:00") + pd.Timedelta(days=idx),
                "current_day_data_tradable": True, "current_valid": True,
                "market_rule_valid": True, "corporate_action_valid": True,
                "corporate_action_blocking": False, "hard_valid": True,
                "trade_status": 1,
            }
        )
    monkeypatch.setattr(v3.execution, "sellable_open", lambda row: True)
    result = v3.apply_event_high_exit_without_returns(selected, pd.DataFrame(rows))
    assert result["exit_cal_idx"] == 4
    assert result["exit_reason"] == "EVENT_HIGH_ACCEPTANCE_FAILURE"


def test_below_high_streak_resets(monkeypatch) -> None:
    selected = pd.DataFrame(
        [{
            "event_id": "E", "signal_cal_idx": 0, "event_high": 10.0,
            "entry_cal_idx": 2, "status": "COMPLETED", "exit_date": pd.NaT,
            "exit_cal_idx": None, "exit_reason": None, "holding_market_sessions": None,
        }]
    ).itertuples(index=False).__next__()
    rows = []
    for idx, close in enumerate([10.2, 9.9, 10.1, 9.8, 9.7, 9.6], start=1):
        rows.append(
            {
                "cal_idx": idx, "trade_date": pd.Timestamp("2020-01-01") + pd.Timedelta(days=idx),
                "coord_open": close, "coord_high": close + 0.1, "coord_low": close - 0.1,
                "coord_close": close, "invalid_step_cum": 0.0,
                "available_at": pd.Timestamp("2020-01-01 15:00") + pd.Timedelta(days=idx),
                "decision_at": pd.Timestamp("2020-01-01 15:00") + pd.Timedelta(days=idx),
                "current_day_data_tradable": True, "current_valid": True,
                "market_rule_valid": True, "corporate_action_valid": True,
                "corporate_action_blocking": False, "hard_valid": True, "trade_status": 1,
            }
        )
    monkeypatch.setattr(v3.execution, "sellable_open", lambda row: True)
    result = v3.apply_event_high_exit_without_returns(selected, pd.DataFrame(rows))
    assert result["exit_cal_idx"] == 6
