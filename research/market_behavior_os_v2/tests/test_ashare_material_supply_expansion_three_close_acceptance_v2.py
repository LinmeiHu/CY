from types import SimpleNamespace

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_material_supply_expansion_three_close_acceptance_v2 as v2,
)


def test_frozen_constants() -> None:
    assert v2.CONFIRMATION_SESSIONS == 2
    assert v2.ENTRY_DELAY_MAX == 3
    assert v2.TIME_EXIT_SESSIONS == 120
    assert v2.MINIMUM_ANNUAL_COMPLETED_STRICT == 50
    assert v2.ROUND_TRIP_COST == 0.004


def test_summary_uses_net_returns_and_strict_boundaries() -> None:
    frame = pd.DataFrame(
        {
            "net_return": [0.04, 0.10, -0.10, -0.02],
            "holding_market_sessions": [5, 10, 20, 25],
        }
    )
    result = v2.summarize(frame)
    assert result["n"] == 4
    assert result["positive_rate"] == 0.5
    assert result["profit_ge_4pct_rate"] == 0.5
    assert result["severe_loss_le_minus_10pct_rate"] == 0.25


def test_confirmation_bars_are_after_trigger_and_entry_is_later(monkeypatch) -> None:
    selected = SimpleNamespace(
        _fields=(
            "event_id", "symbol", "sleeve", "pit_industry", "signal_date",
            "signal_year", "signal_cal_idx", "event_low", "event_high",
            "event_close", "trigger_date", "trigger_cal_idx", "status",
            "entry_date", "entry_cal_idx", "exit_date", "exit_cal_idx",
            "exit_reason", "holding_market_sessions",
        ),
        event_id="E", symbol="S", sleeve="MAIN", pit_industry="I",
        signal_date=pd.Timestamp("2020-01-01"), signal_year=2020,
        signal_cal_idx=0, event_low=9.0, event_high=10.0, event_close=9.5,
        trigger_date=pd.Timestamp("2020-01-02"), trigger_cal_idx=1,
        status="COMPLETED", entry_date=None, entry_cal_idx=None, exit_date=None,
        exit_cal_idx=None, exit_reason=None, holding_market_sessions=None,
    )
    rows = []
    for idx, close in enumerate([10.2, 10.3, 10.4, 10.5, 10.5, 10.5], start=1):
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
                "current_day_data_tradable": True,
                "current_valid": True,
                "market_rule_valid": True,
                "corporate_action_valid": True,
                "corporate_action_blocking": False,
                "hard_valid": True,
                "trade_status": 1,
            }
        )
    monkeypatch.setattr(v2.execution, "buyable", lambda row: True)
    monkeypatch.setattr(v2.execution, "sellable_open", lambda row: True)
    monkeypatch.setattr(v2, "TIME_EXIT_SESSIONS", 1)
    result = v2.apply_three_close_rule_without_returns(selected, pd.DataFrame(rows))
    assert result["confirmation_2_cal_idx"] == 3
    assert result["entry_cal_idx"] == 4
    assert result["exit_cal_idx"] == 5
    assert result["status"] == "COMPLETED"


def test_failed_second_confirmation_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(v2.parent, "same_coordinate_lineage", lambda row, lineage: True)
    monkeypatch.setattr(v2.parent, "valid_completed_close", lambda row, lineage: True)
    selected = SimpleNamespace(
        _fields=("event_id", "signal_cal_idx", "trigger_cal_idx", "event_high", "event_low", "status"),
        event_id="E", signal_cal_idx=0, trigger_cal_idx=1,
        event_high=10.0, event_low=9.0, status="COMPLETED",
    )
    path = pd.DataFrame(
        {
            "cal_idx": [1, 2, 3],
            "invalid_step_cum": [0.0, 0.0, 0.0],
            "coord_close": [9.5, 10.2, 9.9],
            "trade_date": pd.to_datetime(["2020-01-01", "2020-01-03", "2020-01-04"]),
        }
    )
    result = v2.apply_three_close_rule_without_returns(selected, path)
    assert result["status"] == "FAILED_THREE_CLOSE_ACCEPTANCE"
