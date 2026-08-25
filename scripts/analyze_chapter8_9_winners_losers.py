"""Diagnostic decomposition for the Chapter 8/9 lifecycle bridge.

Research-only: this is not a portfolio backtest and does not promote data.
Industry is exploratory unless a PIT sector asset is registered and activated.
"""
import duckdb

LIFECYCLE = "data/audit/chapter8_9_trade_lifecycle_v01.csv"
OUT = "data/audit/chapter8_9_winners_losers_diagnostic_v01.csv"


def main() -> None:
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    con.execute(
        """
        CREATE OR REPLACE TABLE t AS
        SELECT *,
          CASE
            WHEN symbol LIKE '300%' OR symbol LIKE '301%' THEN 'CHINEXT'
            WHEN symbol LIKE '600%' OR symbol LIKE '601%' OR symbol LIKE '603%'
              OR symbol LIKE '605%' OR symbol LIKE '000%' OR symbol LIKE '001%'
              OR symbol LIKE '002%' OR symbol LIKE '003%' THEN 'MAIN_STRICT'
            ELSE 'EXCLUDED_688_OR_OTHER'
          END AS strict_board
        FROM read_csv_auto(?)
        """,
        [LIFECYCLE],
    )
    con.execute(
        """
        COPY (
          SELECT sample_group, strict_board, signal, exit_reason,
                 COUNT(*) AS n, AVG(net_return) AS mean_return,
                 MEDIAN(net_return) AS median_return,
                 AVG(CASE WHEN net_return > 0 THEN 1 ELSE 0 END) AS win_rate,
                 SUM(net_return) AS sum_return
          FROM t
          GROUP BY ALL
          ORDER BY sample_group, strict_board, signal, exit_reason
        ) TO ? (HEADER, DELIMITER ',')
        """,
        [OUT],
    )
    print(con.execute("""
      SELECT sample_group, strict_board, COUNT(*) n,
             AVG(net_return) mean_return, MEDIAN(net_return) median_return,
             AVG(CASE WHEN net_return > 0 THEN 1 ELSE 0 END) win_rate,
             SUM(net_return) sum_return
      FROM t GROUP BY ALL ORDER BY sample_group, strict_board
    """).fetchdf().to_string(index=False))
    print("\\nTop/bottom repeated symbols (at least 5 trades):")
    print(con.execute("""
      WITH s AS (
        SELECT sample_group, strict_board, symbol, COUNT(*) n,
               AVG(net_return) mean_return, MEDIAN(net_return) median_return,
               SUM(net_return) sum_return
        FROM t GROUP BY ALL
      )
      SELECT * FROM s WHERE n >= 5 ORDER BY sum_return DESC LIMIT 10
    """).fetchdf().to_string(index=False))
    print("\\nLargest repeated-symbol losses:")
    print(con.execute("""
      WITH s AS (
        SELECT sample_group, strict_board, symbol, COUNT(*) n,
               AVG(net_return) mean_return, MEDIAN(net_return) median_return,
               SUM(net_return) sum_return
        FROM t GROUP BY ALL
      )
      SELECT * FROM s WHERE n >= 5 ORDER BY sum_return LIMIT 10
    """).fetchdf().to_string(index=False))


if __name__ == "__main__":
    main()
