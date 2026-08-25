"""Parallel/vectorized parameter probe for chapter 8/9 research signals.

The causal base table is materialized once; parameter combinations are evaluated
inside one DuckDB query with multiple threads. This is an event-study probe, not
the final portfolio backtest.
"""
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ROOT / "data/processed/chip_state_features_2018_2026_v2/bucket=*/data.parquet"
DAILY = ROOT / "data/processed/pit_b_daily_2018_2026_v2/daily/partition_year=*/data_0.parquet"
OUT = ROOT / "data/audit/chapter8_9_grid_probe_v01.csv"


def main() -> None:
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    con.execute("PRAGMA enable_progress_bar=false")
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE base AS
      SELECT x.symbol, x.trade_date, x.close, x.volume,
             x.available_at, x.snapshot_id,
             f.p10, f.p90, f.average_cost,
             lag(x.close) OVER w AS prev_close,
             lag(f.p90) OVER w AS prev_p90,
             lag(f.p90-f.p10, 20) OVER w AS old_width,
             median(x.volume) OVER (PARTITION BY x.symbol ORDER BY x.trade_date
               ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) AS vmed20,
             median(x.volume) OVER (PARTITION BY x.symbol ORDER BY x.trade_date
               ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) AS vmed10,
             median(x.volume) OVER (PARTITION BY x.symbol ORDER BY x.trade_date
               ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING) AS vmed30,
             lead(x.close, 1) OVER w AS c1,
             lead(x.close, 2) OVER w AS c2,
             lead(x.close, 3) OVER w AS c3,
             lead(x.trade_date, 1) OVER w AS d1,
             lead(x.trade_date, 2) OVER w AS d2,
             lead(x.trade_date, 3) OVER w AS d3,
             lead(x.close, 4) OVER w AS c4,
             lead(x.close, 6) OVER w AS c6,
             lead(x.close, 7) OVER w AS c7,
             lead(x.close, 8) OVER w AS c8,
             lead(x.close, 21) OVER w AS c21,
             lead(x.close, 22) OVER w AS c22,
             lead(x.close, 23) OVER w AS c23,
             CASE WHEN regexp_matches(x.symbol, '^(300|301)') THEN 'CHINEXT' ELSE 'MAIN' END board
      FROM read_parquet('{DAILY}', union_by_name=true) x
      JOIN read_parquet('{FEATURES}', union_by_name=true) f USING (symbol, trade_date)
      WHERE x.trade_date BETWEEN DATE '2020-01-02' AND DATE '2026-08-12'
        AND x.hard_valid AND f.chip_input_valid AND f.daily_hard_valid
      WINDOW w AS (PARTITION BY x.symbol ORDER BY x.trade_date)
    """)
    con.execute(f"""
      COPY (
        WITH params AS (
          SELECT * FROM (VALUES
            (10, 10, 1, 0.000), (10, 20, 2, 0.005), (10, 30, 3, 0.010), (10, 60, 5, 0.020),
            (20, 10, 1, 0.000), (20, 20, 2, 0.005), (20, 30, 3, 0.010), (20, 60, 5, 0.020),
            (30, 10, 1, 0.000), (30, 20, 2, 0.005), (30, 30, 3, 0.010), (30, 60, 5, 0.020),
            (40, 10, 1, 0.000), (40, 20, 2, 0.005), (40, 30, 3, 0.010), (40, 60, 5, 0.020)
          ) AS t(narrow_pct, vol_window, confirm_days, breakout_buffer)
        ), signals AS (
          SELECT p.*, b.*,
            CASE
              WHEN old_width IS NOT NULL
               AND (p90-p10) <= old_width*(1-p.narrow_pct/100.0)
               AND close > p90*(1+p.breakout_buffer) AND prev_close <= prev_p90
               AND volume >= CASE p.vol_window WHEN 10 THEN vmed10 WHEN 30 THEN vmed30 ELSE vmed20 END
               AND CASE p.confirm_days WHEN 1 THEN c1 WHEN 2 THEN c2 ELSE c3 END > p90 THEN 'B1'
              WHEN close > p90*(1+p.breakout_buffer) AND prev_close <= prev_p90
               AND volume >= CASE p.vol_window WHEN 10 THEN vmed10 WHEN 30 THEN vmed30 ELSE vmed20 END
               AND CASE p.confirm_days WHEN 1 THEN c1 WHEN 2 THEN c2 ELSE c3 END > p90 THEN 'B2'
              WHEN close > average_cost AND prev_close <= average_cost
               AND volume < CASE p.vol_window WHEN 10 THEN vmed10 WHEN 30 THEN vmed30 ELSE vmed20 END THEN 'B5'
              ELSE NULL END signal
          FROM base b CROSS JOIN params p
        )
        SELECT narrow_pct, vol_window, confirm_days, breakout_buffer,
               CASE WHEN trade_date < DATE '2024-01-01' THEN 'PROBE_2020_2023'
                    ELSE 'HOLDOUT_2024_2026' END sample_group,
               board, signal, count(*) n,
               avg((CASE confirm_days WHEN 1 THEN c2 WHEN 2 THEN c3 ELSE c4 END /
                    CASE confirm_days WHEN 1 THEN c1 WHEN 2 THEN c2 ELSE c3 END)-1) fwd1_mean,
               avg((CASE confirm_days WHEN 1 THEN c6 WHEN 2 THEN c7 ELSE c8 END /
                    CASE confirm_days WHEN 1 THEN c1 WHEN 2 THEN c2 ELSE c3 END)-1) fwd5_mean,
               avg((CASE confirm_days WHEN 1 THEN c21 WHEN 2 THEN c22 ELSE c23 END /
                    CASE confirm_days WHEN 1 THEN c1 WHEN 2 THEN c2 ELSE c3 END)-1) fwd20_mean,
               median((CASE confirm_days WHEN 1 THEN c21 WHEN 2 THEN c22 ELSE c23 END /
                       CASE confirm_days WHEN 1 THEN c1 WHEN 2 THEN c2 ELSE c3 END)-1) fwd20_median
        FROM signals
        WHERE signal IS NOT NULL
          AND c23 IS NOT NULL
        GROUP BY ALL
      ) TO '{OUT}' (HEADER, DELIMITER ',');
    """)
    print(OUT)
    print(con.execute(f"SELECT * FROM read_csv_auto('{OUT}') WHERE sample_group='PROBE_2020_2023' ORDER BY fwd20_mean DESC LIMIT 12").fetchall())


if __name__ == "__main__":
    main()
