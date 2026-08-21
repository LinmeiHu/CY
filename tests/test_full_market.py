from __future__ import annotations

import duckdb

from cyq_game.data.full_market import _historical_identity_valid_sql


def test_historical_symbol_aliases_fail_closed_before_effective_date() -> None:
    connection = duckdb.connect()
    rows = connection.execute(
        f"""
        WITH samples(symbol, trade_date) AS (
          VALUES
            ('001872.SZ', DATE '2018-12-25'),
            ('001872.SZ', DATE '2018-12-26'),
            ('001914.SZ', DATE '2019-12-15'),
            ('001914.SZ', DATE '2019-12-16'),
            ('302132.SZ', DATE '2025-02-16'),
            ('302132.SZ', DATE '2025-02-17'),
            ('601360.SH', DATE '2018-02-27'),
            ('601360.SH', DATE '2018-02-28'),
            ('600000.SH', DATE '2018-01-01')
        )
        SELECT {_historical_identity_valid_sql()} FROM samples
        """
    ).fetchall()
    connection.close()

    assert rows == [
        (False,),
        (True,),
        (False,),
        (True,),
        (False,),
        (True,),
        (False,),
        (True,),
        (True,),
    ]
