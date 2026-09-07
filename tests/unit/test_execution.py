import pandas as pd

from five_strategy_bundle.execution.daily import replay_sleeves
from five_strategy_bundle.strategies.atrdr import select_fast_capacity


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


def _trade(event_id, symbol, entry_date, exit_date, *, exit_reason, status="COMPLETED", sleeve="MAIN", entry_price=10.0, exit_price=10.0, rank=1.0):
    return {
        "event_id": event_id, "symbol": symbol, "sleeve": sleeve,
        "signal_date": pd.Timestamp(entry_date) - pd.Timedelta(days=1), "status": status,
        "entry_date": pd.Timestamp(entry_date), "entry_price": entry_price,
        "exit_date": pd.Timestamp(exit_date) if exit_date else pd.NaT,
        "exit_price": exit_price if exit_date else float("nan"),
        "exit_reason": exit_reason, "r1": rank, "r2": rank, "r3": rank,
    }


def test_intraday_target_exit_cannot_release_slot_for_same_open_entry():
    trades = pd.DataFrame([
        _trade("OLD", "600001.SH", "2020-01-02", "2020-01-03", exit_reason="TARGET_10", exit_price=11.0, rank=2.0),
        _trade("NEW", "600002.SH", "2020-01-03", "2020-01-06", exit_reason="H1_TIME_STOP"),
    ])
    daily = pd.DataFrame([
        {"symbol": symbol, "trade_date": pd.Timestamp(date), "coord_open": price, "coord_close": price}
        for symbol, date, price in [
            ("600001.SH", "2020-01-02", 10.0), ("600001.SH", "2020-01-03", 11.0),
            ("600002.SH", "2020-01-03", 10.0), ("600002.SH", "2020-01-06", 10.0),
        ]
    ])
    accepted, skipped, _, _ = replay_sleeves(
        trades, daily, rank_columns=("r1", "r2", "r3"), k_per_sleeve=1, daily_cap=1,
    )
    assert accepted.event_id.tolist() == ["OLD"]
    assert skipped.set_index("event_id").loc["NEW", "skip_reason"] == "MAX_K"


def test_intraday_target_exit_proceeds_cannot_fund_same_open_entry():
    trades = pd.DataFrame([
        _trade("OLD", "600001.SH", "2020-01-02", "2020-01-03", exit_reason="TARGET_100", exit_price=20.0, rank=2.0),
        _trade("NEW", "600002.SH", "2020-01-03", "2020-01-06", exit_reason="H1_TIME_STOP"),
    ])
    daily = pd.DataFrame([
        {"symbol": symbol, "trade_date": pd.Timestamp(date), "coord_open": price, "coord_close": price}
        for symbol, date, price in [
            ("600001.SH", "2020-01-02", 10.0), ("600001.SH", "2020-01-03", 20.0),
            ("600002.SH", "2020-01-03", 10.0), ("600002.SH", "2020-01-06", 10.0),
        ]
    ])
    accepted, skipped, _, _ = replay_sleeves(
        trades, daily, rank_columns=("r1", "r2", "r3"), k_per_sleeve=2, daily_cap=2,
    )
    assert accepted.event_id.tolist() == ["OLD"]
    assert skipped.set_index("event_id").loc["NEW", "skip_reason"] == "INSUFFICIENT_CASH"


def test_entered_incomplete_tail_remains_an_open_position():
    trades = pd.DataFrame([_trade(
        "OPEN", "600001.SH", "2020-01-02", None,
        exit_reason=None, status="INCOMPLETE_OUTCOME_TAIL",
    )])
    daily = pd.DataFrame([
        {"symbol": "600001.SH", "trade_date": pd.Timestamp("2020-01-02"), "coord_open": 10.0, "coord_close": 10.0},
        {"symbol": "600001.SH", "trade_date": pd.Timestamp("2020-01-03"), "coord_open": 11.0, "coord_close": 11.0},
    ])
    accepted, _, nav, _ = replay_sleeves(
        trades, daily, rank_columns=("r1", "r2", "r3"), k_per_sleeve=30, daily_cap=10,
    )
    assert accepted.event_id.tolist() == ["OPEN"]
    assert nav.loc[nav.trade_date.eq(pd.Timestamp("2020-01-03")), "combined_nav"].iloc[0] > 1.0


def test_one_sleeve_cannot_borrow_from_the_other():
    trades = pd.DataFrame([
        _trade("MAIN_OLD", "600001.SH", "2020-01-02", "2020-01-06", exit_reason="H2_TIME_STOP", exit_price=20.0, rank=2.0),
        _trade("MAIN_NEW", "600002.SH", "2020-01-03", "2020-01-06", exit_reason="H1_TIME_STOP"),
    ])
    daily = pd.DataFrame([
        {"symbol": symbol, "trade_date": pd.Timestamp(date), "coord_open": price, "coord_close": price}
        for symbol, date, price in [
            ("600001.SH", "2020-01-02", 10.0), ("600001.SH", "2020-01-03", 20.0), ("600001.SH", "2020-01-06", 20.0),
            ("600002.SH", "2020-01-03", 10.0), ("600002.SH", "2020-01-06", 10.0),
        ]
    ])
    accepted, skipped, _, _ = replay_sleeves(
        trades, daily, rank_columns=("r1", "r2", "r3"), k_per_sleeve=2, daily_cap=2,
    )
    assert accepted.event_id.tolist() == ["MAIN_OLD"]
    assert skipped.set_index("event_id").loc["MAIN_NEW", "skip_reason"] == "INSUFFICIENT_CASH"


def test_fast_capacity_does_not_depend_on_future_outcome_maturity(tmp_path):
    base = {
        "event_id": "FAST", "symbol": "600001.SH", "sleeve": "MAIN",
        "signal_date": pd.Timestamp("2020-01-01"), "entry_date": pd.Timestamp("2020-01-02"),
        "stock_minus_industry_ret20": 1.0, "close_vs_prior10_high": 1.0,
        "close_location_x": 1.0,
    }
    incomplete = pd.DataFrame([{**base, "status": "INCOMPLETE_OUTCOME_TAIL", "exit_date": pd.NaT, "exit_reason": None}])
    completed = pd.DataFrame([{**base, "status": "COMPLETED", "exit_date": pd.Timestamp("2020-01-30"), "exit_reason": "H20_TIME_STOP"}])
    before = select_fast_capacity(incomplete, tmp_path / "before.parquet")
    after = select_fast_capacity(completed, tmp_path / "after.parquet")
    assert before.event_id.tolist() == after.event_id.tolist() == ["FAST"]
