"""Condition-by-condition coverage audit for B3 and B6.

Research-only. Counts are deliberately staged and are not performance claims.
All source rows use the registered PIT daily/chip join and strict validity flags.
"""
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ROOT / "data/processed/chip_state_features_by_year_2018_2026_v2/year=*/data.parquet"
DAILY = ROOT / "data/processed/pit_b_daily_2018_2026_v2/daily/partition_year=*/data_0.parquet"
OUTPUT = ROOT / "data/audit/chapter8_9_b3_b6_coverage.csv"


def main() -> None:
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    query = f"""
    WITH x AS (
      SELECT d.symbol, d.trade_date, d.close, d.volume, d.market_close,
             d.buy_blocked_open, d.hard_valid,
             lead(d.buy_blocked_open) OVER w next_buy_blocked,
             lead(d.hard_valid) OVER w next_hard_valid,
             f.p50, f.p90, f.peak_count,
             f.base_retention, f.concentration_20,
             try_cast(json_extract_string(f.peaks_json, '$[0].center_price') AS DOUBLE) peak,
             lag(d.close) OVER w prev_close, lag(f.p50) OVER w prev_p50,
             lag(try_cast(json_extract_string(f.peaks_json, '$[0].center_price') AS DOUBLE)) OVER w prev_peak,
             lag(f.base_retention) OVER w prev_ret,
             lag(f.concentration_20) OVER w prev_conc,
             avg(d.market_close) OVER (
               PARTITION BY d.symbol ORDER BY d.trade_date
               ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) market_avg,
             median(d.volume) OVER (
               PARTITION BY d.symbol ORDER BY d.trade_date
               ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) vmed,
             sum(CASE WHEN d.close > f.p90 THEN 1 ELSE 0 END) OVER (
               PARTITION BY d.symbol ORDER BY d.trade_date
               ROWS BETWEEN 15 PRECEDING AND 1 PRECEDING) prior_break
      FROM read_parquet('{DAILY}', union_by_name=true) d
      JOIN read_parquet('{FEATURES}', union_by_name=true) f USING (symbol, trade_date)
      WHERE d.trade_date BETWEEN DATE '2020-01-02' AND DATE '2023-12-29'
        AND d.hard_valid AND f.strict_sample AND f.chip_input_valid
        AND f.daily_hard_valid AND f.minute_hard_valid
        AND f.daily_snapshot_id = d.snapshot_id
        AND NOT regexp_matches(d.symbol, '^(688|689)')
      WINDOW w AS (PARTITION BY d.symbol ORDER BY d.trade_date)
    ), flags AS (
      SELECT *,
        peak_count = 2 AND p50 > prev_p50 AND close > p50
          AND peak > prev_peak AND close > prev_close b3_core,
        close > p50 AND prev_close <= prev_p50 b6_reclaim,
        base_retention >= prev_ret retention_ok,
        concentration_20 >= prev_conc concentration_ok,
        market_close > market_avg market_ok,
        volume >= vmed volume_ok,
        next_hard_valid AND next_buy_blocked IS FALSE executable_ok,
        prior_break BETWEEN 1 AND 4 prior_break_ok
      FROM x
    ), staged AS (
      SELECT 'B3' rule_name, 1 stage, 'core' condition, count(*) n FROM flags WHERE b3_core
      UNION ALL SELECT 'B3', 2, 'retention', count(*) FROM flags WHERE b3_core AND retention_ok
      UNION ALL SELECT 'B3', 3, 'prior_break_1_4', count(*) FROM flags WHERE b3_core AND retention_ok AND prior_break_ok
      UNION ALL SELECT 'B3', 4, 'market', count(*) FROM flags WHERE b3_core AND retention_ok AND prior_break_ok AND market_ok
      UNION ALL SELECT 'B3', 5, 'executable', count(*) FROM flags WHERE b3_core AND retention_ok AND prior_break_ok AND market_ok AND executable_ok
      UNION ALL SELECT 'B6', 1, 'reclaim_core', count(*) FROM flags WHERE b6_reclaim
      UNION ALL SELECT 'B6', 2, 'retention', count(*) FROM flags WHERE b6_reclaim AND retention_ok
      UNION ALL SELECT 'B6', 3, 'volume', count(*) FROM flags WHERE b6_reclaim AND retention_ok AND volume_ok
      UNION ALL SELECT 'B6', 4, 'market', count(*) FROM flags WHERE b6_reclaim AND retention_ok AND volume_ok AND market_ok
      UNION ALL SELECT 'B6', 5, 'executable', count(*) FROM flags WHERE b6_reclaim AND retention_ok AND volume_ok AND market_ok AND executable_ok
    )
    SELECT * FROM staged ORDER BY rule_name, stage
    """
    result = con.execute(query).fetchdf()
    result.to_csv(OUTPUT, index=False)
    print(OUTPUT)
    print(result.to_string(index=False))


if __name__ == "__main__":
    main()
