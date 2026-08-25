"""Post-entry path diagnostics for fixed parameter 231; never feeds signal selection."""
from pathlib import Path

import duckdb

ROOT = Path('/Users/linmei/Documents/CY')
OUT = ROOT / 'data/audit/chapter8_9_attribution_v02'
DAILY = ROOT / 'data/processed/pit_b_daily_2018_2026_v2/daily/partition_year=*/data_0.parquet'
CASES = OUT / 'fixed231_cases.csv'


def main() -> None:
    con = duckdb.connect()
    con.execute('PRAGMA threads=8')
    con.execute(f"CREATE OR REPLACE TABLE c AS SELECT * FROM read_csv_auto('{CASES}', header=true)")
    con.execute(f"""
        CREATE OR REPLACE TABLE p AS
        WITH d AS (SELECT * FROM read_parquet('{DAILY}', union_by_name=true)),
        x AS (
          SELECT c.symbol, c.signal_date, c.entry_date, c.signal, c.board,
                 c.exit_date, c.exit_reason, c.net_return,
                 d.trade_date, d.close, d.open,
                 d.close / NULLIF(first_value(d.close) OVER
                   (PARTITION BY c.symbol,c.signal_date,c.signal ORDER BY d.trade_date),0)-1 AS ret_from_entry,
                 row_number() OVER (PARTITION BY c.symbol,c.signal_date,c.signal ORDER BY d.trade_date)-1 AS days_after
          FROM c JOIN d ON d.symbol=c.symbol
            AND d.trade_date >= CAST(c.entry_date AS DATE)
            AND d.trade_date <= CAST(c.entry_date AS DATE) + INTERVAL 60 DAY
        )
        SELECT symbol, signal_date, entry_date, signal, board, exit_date, exit_reason,
               net_return, max(ret_from_entry) AS mfe, min(ret_from_entry) AS mae,
               max(CASE WHEN trade_date > CAST(exit_date AS DATE) THEN ret_from_entry END) AS recovery_after_exit,
               count(*) AS path_bars
        FROM x GROUP BY ALL
    """)
    con.execute(f"COPY p TO '{OUT / 'fixed231_path_metrics.csv'}' (HEADER, DELIMITER ',')")
    con.execute(f"""COPY (SELECT board, signal, exit_reason, count(*) n, avg(mfe) mean_mfe,
                 median(mfe) median_mfe, avg(mae) mean_mae, median(mae) median_mae,
                 avg(recovery_after_exit) mean_recovery_after_exit
                 FROM p GROUP BY ALL ORDER BY signal, board, exit_reason)
                 TO '{OUT / 'fixed231_path_summary.csv'}' (HEADER, DELIMITER ',')""")


if __name__ == '__main__':
    main()
