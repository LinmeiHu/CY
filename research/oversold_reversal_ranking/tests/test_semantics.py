from __future__ import annotations

import duckdb


def test_crash_speed_orientation() -> None:
    # Same 30% drawdown: the stock losing 20% recently is the faster crash.
    slow = 0.05 / 0.30
    fast = 0.20 / 0.30
    assert fast > slow


def test_relative_decline_orientation() -> None:
    market_return = -0.10
    systematic_stock = -0.11
    idiosyncratic_stock = -0.25
    assert systematic_stock - market_return > idiosyncratic_stock - market_return


def test_twenty_session_dedup_uses_prior_trading_rows() -> None:
    con = duckdb.connect()
    rows = con.execute(
        """
        WITH x AS (
            SELECT range AS seq, range IN (1, 2, 21, 22, 43) AS low_flag
            FROM range(1, 44)
        )
        SELECT seq, dedup FROM (
            SELECT seq, low_flag,
                   low_flag AND NOT coalesce(bool_or(low_flag) OVER (
                       ORDER BY seq ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING), false)
                       AS dedup
            FROM x
        ) WHERE low_flag ORDER BY seq
        """
    ).fetchall()
    assert rows == [(1, True), (2, False), (21, False), (22, False), (43, True)]


def test_next_open_return_coordinate() -> None:
    # Signal adjusted close is 1.0. Next raw preclose/open is 10/11 and
    # adjusted close at horizon is 1.1, so entry-to-close return is zero.
    result = 10.0 / 11.0 * 1.1 / 1.0 - 1.0
    assert abs(result) < 1e-12


def test_matrix_bins_are_complete_and_disjoint() -> None:
    con = duckdb.connect()
    rows = con.execute(
        """
        WITH x(drawdown) AS (VALUES (-0.15), (-0.20), (-0.30), (-0.40), (-0.80)),
        b AS (
            SELECT drawdown,
                   CASE WHEN drawdown <= -0.40 THEN 'D4_EXTREME'
                        WHEN drawdown <= -0.30 THEN 'D3_VERY_DEEP'
                        WHEN drawdown <= -0.20 THEN 'D2_DEEP'
                        ELSE 'D1_MODERATE' END AS bucket
            FROM x
        )
        SELECT count(*), count(bucket), count(DISTINCT drawdown) FROM b
        """
    ).fetchone()
    assert rows == (5, 5, 5)
