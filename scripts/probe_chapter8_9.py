"""Research-only probe for the frozen chapter 8/9 specification.

This is deliberately an event-study probe, not a portfolio backtest: it measures
forward returns after causal B1/B2/B5-like triggers and never fills on signal day.
"""
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ROOT / "data/processed/chip_state_features_2018_2026_v2/bucket=*/data.parquet"
DAILY = ROOT / "data/processed/pit_b_daily_2018_2026_v2/daily/partition_year=*/data_0.parquet"
OUT = ROOT / "data/audit/chapter8_9_probe_v01.csv"


def main() -> None:
    con = duckdb.connect()
    q = f"""
    COPY (
      WITH d AS (
        SELECT x.symbol, x.trade_date, x.close, x.volume, x.hard_valid, x.available_at, x.snapshot_id,
               f.p10, f.p90, f.average_cost,
               lead(close, 1) OVER w AS c1, lead(close, 5) OVER w AS c5,
               lead(close, 10) OVER w AS c10, lead(close, 20) OVER w AS c20,
               median(volume) OVER (PARTITION BY symbol ORDER BY trade_date
                 ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) AS vmed20,
               lag(close, 1) OVER w AS pc,
               lag(p90-p10, 20) OVER w AS old_width,
               lag(p90, 1) OVER w AS pp90
        FROM read_parquet('{DAILY}', union_by_name=true) x
        JOIN read_parquet('{FEATURES}', union_by_name=true) f USING (symbol, trade_date)
        WHERE trade_date BETWEEN DATE '2020-01-02' AND DATE '2026-08-12'
          AND f.chip_input_valid AND f.daily_hard_valid AND x.hard_valid
        WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
      ), s AS (
        SELECT *,
          CASE
            WHEN old_width IS NOT NULL AND (p90-p10) <= old_width*0.80
                 AND close > p90 AND pc <= pp90 AND volume >= vmed20 THEN 'B1'
            WHEN close > p90 AND pc <= pp90 AND volume >= vmed20 THEN 'B2'
            WHEN close > average_cost AND pc <= average_cost AND volume < vmed20 THEN 'B5'
            ELSE NULL END AS signal,
          CASE WHEN regexp_matches(symbol, '^(300|301)') THEN 'CHINEXT' ELSE 'MAIN' END AS board
        FROM d
      )
      SELECT symbol, trade_date, board, signal, close, c1, c5, c10, c20,
             c1/close-1 AS fwd_1d, c5/close-1 AS fwd_5d,
             c10/close-1 AS fwd_10d, c20/close-1 AS fwd_20d,
             available_at, snapshot_id
      FROM s WHERE signal IS NOT NULL
    ) TO '{OUT}' (HEADER, DELIMITER ',');
    """
    con.execute(q)
    print(OUT)
    print(con.execute(f"SELECT CASE WHEN trade_date < DATE '2024-01-01' THEN 'PROBE_2020_2023' ELSE 'HOLDOUT_2024_2026' END sample_group, board, signal, count(*) n, avg(fwd_5d) fwd5, avg(fwd_20d) fwd20, median(fwd_20d) med20 FROM read_csv_auto('{OUT}') GROUP BY 1,2,3 ORDER BY 1,2,3").fetchall())


if __name__ == "__main__":
    main()
