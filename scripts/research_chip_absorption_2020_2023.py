"""Test a causal below-cost absorption hypothesis on 2020-2023 data."""
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DAILY = ROOT / "data/processed/pit_b_daily_2018_2026_v2/daily/partition_year=*/data_0.parquet"
FEATURES = ROOT / "data/processed/chip_state_features_2018_2026_v2/bucket=*/data.parquet"
OUT = ROOT / "data/audit/chip_absorption_research_2020_2023.csv"


def main() -> None:
    con = duckdb.connect()
    q = f"""
    COPY (WITH x AS (
      SELECT d.symbol,d.trade_date,d.close,d.hard_valid,d.buy_blocked_open,
        f.average_cost,f.asr,f.concentration_20,
        lag(d.close) OVER w prev_close,
        lag(f.asr) OVER w prev_asr,
        lag(f.concentration_20) OVER w prev_conc,
        lead(d.open) OVER w entry_open, lead(d.trade_date) OVER w entry_date,
        lead(d.hard_valid) OVER w entry_valid,
        lead(d.buy_blocked_open) OVER w entry_blocked,
        lead(d.close,6) OVER w close5, lead(d.close,11) OVER w close10,
        lead(d.close,21) OVER w close20,
      FROM read_parquet('{DAILY}', union_by_name=true) d
      JOIN read_parquet('{FEATURES}', union_by_name=true) f USING(symbol,trade_date)
      WHERE d.trade_date BETWEEN DATE '2018-01-02' AND DATE '2023-12-29'
        AND d.hard_valid AND f.strict_sample AND f.state_chain_valid
      WINDOW w AS (PARTITION BY d.symbol ORDER BY d.trade_date)
    ), raw AS (
      SELECT *, CASE
        WHEN close <= average_cost
         AND close > prev_close
         AND asr >= coalesce(prev_asr, asr)
         AND concentration_20 <= coalesce(prev_conc, concentration_20)
        THEN 'BELOW_COST_ABSORPTION' END signal_type
      FROM x
    ), s AS (
      SELECT *, lag(CASE WHEN signal_type IS NOT NULL THEN trade_date END IGNORE NULLS)
        OVER (PARTITION BY symbol ORDER BY trade_date) prev_signal_date
      FROM raw
    ), v AS (
      SELECT * FROM s
      WHERE signal_type IS NOT NULL AND entry_date > trade_date AND entry_open > 0
        AND entry_valid AND NOT entry_blocked
        AND trade_date >= DATE '2020-01-02'
        AND trade_date > coalesce(prev_signal_date + INTERVAL 20 DAY, DATE '1900-01-01')
    ) SELECT CASE WHEN trade_date < DATE '2023-01-01' THEN 'FIT_2020_2022' ELSE 'HOLDOUT_2023' END sample_group,
      count(*) n, avg(close5/entry_open-1) mean_ret5, median(close5/entry_open-1) median_ret5,
      avg(close10/entry_open-1) mean_ret10, median(close10/entry_open-1) median_ret10,
      avg(close20/entry_open-1) mean_ret20, median(close20/entry_open-1) median_ret20
      FROM v GROUP BY 1 ORDER BY 1
    ) TO '{OUT}' (HEADER, DELIMITER ',');
    """
    con.execute(q)
    print(con.execute(f"SELECT * FROM read_csv_auto('{OUT}')").fetchall())


if __name__ == "__main__":
    main()
