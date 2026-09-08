import pandas as pd
import pytest

from five_strategy_bundle.execution.daily import replay_sleeves
from five_strategy_bundle.strategies.atrdr import select_fast_capacity


@pytest.mark.parametrize('strict', [False, True])
@pytest.mark.parametrize('sessions', [0, 1, 2])
def test_outcome_schema_survives_empty_no_entry_and_unfinished_paths(strict, sessions):
    from five_strategy_bundle.execution.daily import fixed_target_outcomes, strict_fixed_target_outcomes
    candidate = pd.DataFrame([dict(event_id='E', symbol='A', sleeve='MAIN', signal_date=pd.Timestamp('2020-01-02'), cal_idx=0, invalid_step_cum=0.)])
    daily = pd.DataFrame([dict(symbol='A', trade_date=pd.Timestamp('2020-01-02')+pd.Timedelta(days=i), cal_idx=i,
        open=10., coord_open=10., coord_close=10., coord_high=10., up_limit_price=11., down_limit_price=9.,
        invalid_step_cum=0., hard_valid=True, history_valid=True, current_valid=True, corporate_action_valid=True,
        current_day_data_tradable=True, market_rule_valid=True, corporate_action_blocking=False,
        trade_status=1, corporate_action_count=0) for i in range(max(sessions, 1))])
    producer = strict_fixed_target_outcomes if strict else fixed_target_outcomes
    result = producer(candidate if sessions else candidate.iloc[:0], daily, target=.15, horizon=15, profile='TEST')
    assert {'event_id', 'status', 'entry_date', 'exit_date', 'exit_price', 'exit_reason'} <= set(result)
    if sessions == 2:
        assert result.entry_date.notna().all() and result.exit_date.isna().all()


@pytest.mark.parametrize('router', [False, True])
def test_cash_only_replay_keeps_exportable_empty_trade_schema(tmp_path, router):
    from five_strategy_bundle.execution.daily import replay_shared_router
    from five_strategy_bundle.io import write_parquet
    trades = pd.DataFrame([dict(_trade('E', 'A', '2020-01-02', '2020-01-03', exit_reason='TIME'), source_rank_order=0)]).iloc[:0]
    daily = pd.DataFrame([dict(symbol='A', trade_date=pd.Timestamp('2020-01-02'), coord_open=10., coord_close=10.)])
    if router:
        accepted, skipped, nav = replay_shared_router(trades, daily)
    else:
        accepted, skipped, nav, _ = replay_sleeves(trades, daily, rank_columns=('r1', 'r2', 'r3'), k_per_sleeve=30, daily_cap=10)
    assert {'event_id', 'qty', 'entry_outlay'} <= set(accepted)
    assert {'event_id', 'skip_reason'} <= set(skipped)
    assert nav.combined_nav.tolist() == [1.]
    write_parquet(accepted, tmp_path/'empty.parquet')


def test_router_marks_unfinished_position_through_available_tail():
    from five_strategy_bundle.execution.daily import replay_shared_router
    trades = pd.DataFrame([
        dict(_trade('OLD', 'A', '2020-01-02', '2020-01-03', exit_reason='TIME'), source_rank_order=0),
        dict(_trade('OPEN', 'B', '2020-01-03', None, exit_reason=None, status='INCOMPLETE_OUTCOME_TAIL'), source_rank_order=0),
    ])
    daily = pd.DataFrame([dict(symbol=s, trade_date=d, coord_open=10., coord_close=11. if d.day == 6 else 10.)
                          for s in ('A', 'B') for d in pd.to_datetime(['2020-01-02', '2020-01-03', '2020-01-06'])])
    accepted, _, nav = replay_shared_router(trades, daily)
    assert accepted.event_id.tolist() == ['OLD', 'OPEN']
    assert nav.trade_date.iloc[-1] == pd.Timestamp('2020-01-06')
    assert nav.combined_nav.iloc[-1] > nav.combined_nav.iloc[-2]


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
