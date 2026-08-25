"""Evaluate first-hit barriers for the absorption candidate."""
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DAILY = ROOT / "data/processed/pit_b_daily_2018_2026_v2/daily/partition_year=*/data_0.parquet"
FEATURES = ROOT / "data/processed/chip_state_features_2018_2026_v2/bucket=*/data.parquet"
OUT = ROOT / "data/audit/chip_absorption_barriers_2020_2023.csv"


def main() -> None:
    con = duckdb.connect()
    q = f"""
    COPY (WITH x AS (
      SELECT d.symbol,d.trade_date,d.close,d.hard_valid,d.buy_blocked_open,
        f.average_cost,f.asr,f.concentration_20,lag(d.close) OVER w prev_close,
        lag(f.asr) OVER w prev_asr,lag(f.concentration_20) OVER w prev_conc,
        lead(d.open) OVER w entry_open,lead(d.trade_date) OVER w entry_date,
        lead(d.hard_valid) OVER w entry_valid,lead(d.buy_blocked_open) OVER w entry_blocked,
        lead(d.close,21) OVER w close20
      FROM read_parquet('{DAILY}',union_by_name=true) d
      JOIN read_parquet('{FEATURES}',union_by_name=true) f USING(symbol,trade_date)
      WHERE d.trade_date BETWEEN DATE '2018-01-02' AND DATE '2023-12-29'
        AND d.hard_valid AND f.strict_sample AND f.state_chain_valid
      WINDOW w AS (PARTITION BY d.symbol ORDER BY d.trade_date)
    ), raw AS (
      SELECT *,CASE WHEN close<=average_cost AND close>prev_close
        AND asr>=coalesce(prev_asr,asr)
        AND concentration_20<=coalesce(prev_conc,concentration_20)
        THEN 'ABSORPTION' END signal_type FROM x
    ), s AS (
      SELECT *,lag(CASE WHEN signal_type IS NOT NULL THEN trade_date END IGNORE NULLS)
        OVER (PARTITION BY symbol ORDER BY trade_date) prev_signal_date FROM raw
    ), e AS (
      SELECT * FROM s WHERE signal_type IS NOT NULL AND entry_date>trade_date
        AND entry_open>0 AND entry_valid AND NOT entry_blocked
        AND trade_date>=DATE '2020-01-02'
        AND trade_date>coalesce(prev_signal_date+INTERVAL 20 DAY,DATE '1900-01-01')
    ), f AS (
      SELECT e.symbol,e.trade_date,d.trade_date future_date,d.high,d.low,
        row_number() OVER (PARTITION BY e.symbol,e.trade_date ORDER BY d.trade_date) seq
      FROM e JOIN read_parquet('{DAILY}',union_by_name=true) d
        ON d.symbol=e.symbol AND d.trade_date>e.trade_date
        AND d.trade_date<=e.trade_date+INTERVAL 40 DAY AND d.hard_valid
      QUALIFY seq<=20
    ), h AS (
      SELECT e.*,min(CASE WHEN f.low<=e.entry_open*.92 THEN f.future_date END) stop_date,
        min(CASE WHEN f.high>=e.entry_open*1.12 THEN f.future_date END) take_date
      FROM e LEFT JOIN f USING(symbol,trade_date) GROUP BY ALL
    ), v AS (
      SELECT *,CASE WHEN stop_date IS NOT NULL AND (take_date IS NULL OR stop_date<=take_date)
        THEN 'STOP_8' WHEN take_date IS NOT NULL THEN 'TAKE_12' ELSE 'TIME_20' END exit_type,
        CASE WHEN stop_date IS NOT NULL AND (take_date IS NULL OR stop_date<=take_date)
        THEN -.08 WHEN take_date IS NOT NULL THEN .12 ELSE close20/entry_open-1 END realized_return
      FROM h
    ) SELECT CASE WHEN trade_date<DATE '2023-01-01' THEN 'FIT_2020_2022' ELSE 'HOLDOUT_2023' END sample_group,
      exit_type,count(*) n,avg(realized_return) mean_return,median(realized_return) median_return
      FROM v GROUP BY 1,2 ORDER BY 1,2
    ) TO '{OUT}' (HEADER,DELIMITER ',');
    """
    con.execute(q)
    print(con.execute(f"SELECT * FROM read_csv_auto('{OUT}')").fetchall())


if __name__ == "__main__":
    main()
