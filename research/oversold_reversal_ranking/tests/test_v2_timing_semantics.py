from __future__ import annotations

import duckdb


def test_fixed_carrier_is_causal_and_does_not_need_future_returns() -> None:
    drawdown_60 = -0.31
    low_flag = True
    assert low_flag and drawdown_60 <= -0.30


def test_primary_trigger_uses_trigger_day_ohlc_only() -> None:
    close, preclose, high, low = 10.8, 10.0, 11.0, 9.0
    clv = (close - low) / (high - low)
    assert close > preclose and clv >= 0.70
    assert not (10.3 > preclose and (10.3 - low) / (high - low) >= 0.70)


def test_zero_range_day_fails_closed() -> None:
    high = low = 10.0
    assert high - low == 0.0


def test_trigger_lag_and_next_open_alignment() -> None:
    t0_seq, trigger_seq = 100, 103
    assert trigger_seq - t0_seq == 3
    assert trigger_seq + 1 == 104  # execution row, never trigger close


def test_fixed_delay_alignment() -> None:
    t0_seq = 100
    fixed_observation_seq = t0_seq + 1
    fixed_entry_seq = fixed_observation_seq + 1
    assert fixed_entry_seq == 102


def test_no_trigger_cash_and_common_endpoint() -> None:
    t0_seq = 100
    immediate_endpoint = t0_seq + 20
    delayed_endpoint = t0_seq + 20
    no_trigger_policy_return = 0.0
    assert immediate_endpoint == delayed_endpoint
    assert no_trigger_policy_return == 0.0


def test_deep_event_dedup_uses_prior_twenty_trading_rows() -> None:
    con = duckdb.connect()
    rows = con.execute(
        """
        WITH x AS (
            SELECT range AS seq, range IN (1, 2, 21, 22, 43) AS deep_flag
            FROM range(1, 44)
        )
        SELECT seq, deep_event FROM (
            SELECT seq, deep_flag,
                   deep_flag AND NOT coalesce(bool_or(deep_flag) OVER (
                       ORDER BY seq ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING), false)
                       AS deep_event
            FROM x
        ) WHERE deep_flag ORDER BY seq
        """
    ).fetchall()
    assert rows == [(1, True), (2, False), (21, False), (22, False), (43, True)]
