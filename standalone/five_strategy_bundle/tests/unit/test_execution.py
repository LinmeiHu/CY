import pandas as pd

from five_strategy_bundle.execution.daily import replay_sleeves


def test_replay_has_no_negative_cash_and_t1_trade():
    trades = pd.DataFrame([{
        "event_id": "E", "symbol": "600001.SH", "sleeve": "MAIN",
        "signal_date": pd.Timestamp("2020-01-01"), "signal_cal_idx": 1,
        "profile": "T15_H15_NO_STOP", "status": "COMPLETED",
        "entry_date": pd.Timestamp("2020-01-02"), "entry_cal_idx": 2, "entry_price": 10.0,
        "exit_date": pd.Timestamp("2020-01-03"), "exit_cal_idx": 3, "exit_price": 11.0,
        "exit_reason": "TARGET_15", "exit_decision_cal_idx": 2, "holding_sessions": 1,
        "gross_return": 0.1, "net_return": 0.096,
        "r1": 1.0, "r2": 1.0, "r3": 1.0,
    }])
    daily = pd.DataFrame([
        {"symbol": "600001.SH", "trade_date": pd.Timestamp("2020-01-02"), "coord_open": 10.0, "coord_close": 10.0},
        {"symbol": "600001.SH", "trade_date": pd.Timestamp("2020-01-03"), "coord_open": 11.0, "coord_close": 11.0},
    ])
    accepted, _, nav, _ = replay_sleeves(trades, daily, rank_columns=("r1", "r2", "r3"), k_per_sleeve=30, daily_cap=10)
    assert len(accepted) == 1
    assert accepted.entry_date.iloc[0] > accepted.signal_date.iloc[0]
    assert nav.combined_nav.min() >= 0
