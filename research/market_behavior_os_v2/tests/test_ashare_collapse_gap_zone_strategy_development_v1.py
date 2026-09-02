from __future__ import annotations

import json

import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_gap_zone_strategy_development_v1 as strategy,
)


def test_parameter_space_and_stability_are_frozen() -> None:
    assert len(strategy.CONFIGS) == 48
    assert len({item[4] for item in strategy.CONFIGS}) == 48
    assert strategy.stability(["a", "a", "a", "b", "b"]) == "STABLE"
    assert strategy.stability(["a", "a", "b", "b", "c"]) == "MODERATELY_ADAPTIVE"
    assert strategy.stability(["a", "b", "c", "d", "e"]) == "HIGHLY_UNSTABLE"


def test_selector_ties_prefer_simpler_entry_then_shorter_stop() -> None:
    common = {
        "train_calmar": 1.0,
        "train_sharpe": 1.0,
        "median_year_return": 0.1,
        "train_cagr": 0.1,
        "top5_pnl_day_concentration": 0.2,
    }
    rows = pd.DataFrame(
        [
            {**common, "entry": "E4_SECOND_RECLAIM", "time_stop": 5, "config_key": "later"},
            {**common, "entry": "E1_FIRST_ACCEPT", "time_stop": 20, "config_key": "simple_long"},
            {**common, "entry": "E1_FIRST_ACCEPT", "time_stop": 5, "config_key": "simple_short"},
        ]
    )
    assert strategy.rank_rows(rows).config_key.tolist() == ["simple_short", "simple_long", "later"]


def test_cash_only_action_is_credited_exactly_and_t1_is_preserved() -> None:
    strategy._DAILY_MARK_CACHE = None
    strategy._DAILY_SYMBOL_CACHE = None
    trade = pd.DataFrame(
        [
            {
                "board": "MAIN",
                "entry_family": "E1_FIRST_ACCEPT",
                "target": "P75",
                "failure": "F2_NO_FAILURE_STOP",
                "time_stop": 5,
                "precompleted_before_entry": False,
                "risk_blocked_entry": False,
                "entry_date": pd.Timestamp("2018-01-02"),
                "entry_time": pd.Timestamp("2018-01-02 10:00"),
                "exit_date": pd.Timestamp("2018-01-03"),
                "exit_time": pd.Timestamp("2018-01-03 09:31"),
                "entry_raw_price": 10.0,
                "exit_raw_price": 10.0,
                "exit_reason": "TARGET",
                "action_block_time": pd.NaT,
                "cash_events_json": json.dumps(
                    [{"date": "2018-01-03", "cash_per_share": 0.1, "event_id": "cash"}]
                ),
                "symbol": "600000.SH",
                "primary_layer_width_pct": 0.1,
                "board_relative_return_percentile": 0.9,
                "peak_to_low_decline": 0.5,
                "persistence_sessions": 30,
            }
        ]
    )
    daily = pd.DataFrame(
        [
            {
                "trade_date": pd.Timestamp("2018-01-02"),
                "cal_idx": 0,
                "symbol": "600000.SH",
                "close": 10.0,
            },
            {
                "trade_date": pd.Timestamp("2018-01-03"),
                "cal_idx": 1,
                "symbol": "600000.SH",
                "close": 10.0,
            },
        ]
    )
    config = next(
        item
        for item in strategy.CONFIGS
        if item[:4] == ("E1_FIRST_ACCEPT", "P75", "F2_NO_FAILURE_STOP", 5)
    )
    replay = strategy.replay(trade, daily, "MAIN", config, 2018, 2018)
    expected_trade = (10.0 * (1 - strategy.COST) + 0.1) / (10.0 * (1 + strategy.COST)) - 1
    assert replay.metrics["trades"] == 1
    assert replay.metrics["mean_trade"] == pytest.approx(expected_trade)
    assert replay.audit["t1_same_day_sell_violation_count"] == 0
    assert replay.nav.nav.iloc[-1] == pytest.approx(1.0 + 0.05 * expected_trade)


def test_generated_forced_risk_exits_are_strictly_pre_effective() -> None:
    if not strategy.TRADE_CANDIDATES.is_file():
        pytest.skip("generated Development artifact not built")
    frame = pd.read_parquet(strategy.TRADE_CANDIDATES)
    forced = frame.loc[frame.exit_reason.eq("CORPORATE_ACTION_RISK")]
    assert not forced.empty
    assert (
        pd.to_datetime(forced.exit_date) < pd.to_datetime(forced.risk_exit_effective_date)
    ).all()
    assert forced.action_block_time.isna().all()
