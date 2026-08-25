"""Evaluate causal buy signals with simple stop/take/time exits."""
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DAILY = ROOT / "data/processed/pit_b_daily_2018_2026_v2/daily/partition_year=*/data_0.parquet"
FEATURES = ROOT / "data/processed/chip_state_features_2018_2026_v2/bucket=*/data.parquet"
OUT = ROOT / "data/audit/chip_barrier_research_2020_2023.csv"


def main() -> None:
    con = duckdb.connect()
    q = f"""
    COPY (WITH b AS (
      SELECT d.symbol,d.trade_date,d.close,d.open,d.high,d.low,d.hard_valid,d.buy_blocked_open,
        f.p90,f.average_cost,f.asr,f.concentration_20,
        lag(d.close) OVER w pc,lag(f.p90) OVER w pp90,lag(f.average_cost) OVER w pavg,
        lag(f.asr) OVER w pasr,lag(f.concentration_20) OVER w pconc,
        lead(d.open) OVER w entry_open,lead(d.trade_date) OVER w entry_date,
        lead(d.hard_valid) OVER w ev,lead(d.buy_blocked_open) OVER w eb,
        lead(d.high) OVER w h1,lead(d.low) OVER w l1,
        max(d.high) OVER (PARTITION BY d.symbol ORDER BY d.trade_date ROWS BETWEEN 1 FOLLOWING AND 20 FOLLOWING) max_h20,
        min(d.low) OVER (PARTITION BY d.symbol ORDER BY d.trade_date ROWS BETWEEN 1 FOLLOWING AND 20 FOLLOWING) min_l20,
        lead(d.close,21) OVER w c20
      FROM read_parquet('{DAILY}', union_by_name=true) d
      JOIN read_parquet('{FEATURES}', union_by_name=true) f USING(symbol,trade_date)
      WHERE d.trade_date BETWEEN DATE '2018-01-02' AND DATE '2023-12-29'
        AND d.hard_valid AND f.strict_sample AND f.state_chain_valid
      WINDOW w AS (PARTITION BY d.symbol ORDER BY d.trade_date)
    ), s AS (
      SELECT *, CASE WHEN close>p90 AND pc<=pp90 AND asr>=coalesce(pasr,asr)
                           THEN 'BREAKOUT' WHEN close>average_cost AND pc<=pavg
                           AND concentration_20<=coalesce(pconc,concentration_20)
                           THEN 'RECLAIM' END signal_type
      FROM b
    ), e AS (
      SELECT * FROM s
      WHERE signal_type IS NOT NULL AND entry_date>trade_date AND entry_open>0 AND ev AND NOT eb
    ), future AS (
      SELECT e.symbol,e.trade_date,e.signal_type,e.entry_open,e.c20,
        d.trade_date future_date,d.high future_high,d.low future_low,
        row_number() OVER (PARTITION BY e.symbol,e.trade_date ORDER BY d.trade_date) future_seq
      FROM e JOIN read_parquet('{DAILY}', union_by_name=true) d
        ON d.symbol=e.symbol AND d.trade_date>e.trade_date
       AND d.trade_date<=e.trade_date+INTERVAL 40 DAY
       AND d.hard_valid
      QUALIFY future_seq<=20
    ), first_hit AS (
      SELECT e.*,
        min(CASE WHEN f.future_low<=e.entry_open*0.92 THEN f.future_date END) stop_date,
        min(CASE WHEN f.future_high>=e.entry_open*1.12 THEN f.future_date END) take_date
      FROM e LEFT JOIN future f USING(symbol,trade_date,signal_type,entry_open,c20)
      GROUP BY ALL
    ), v AS (
      SELECT *,CASE WHEN stop_date IS NOT NULL AND (take_date IS NULL OR stop_date<=take_date) THEN 'STOP_8'
                    WHEN take_date IS NOT NULL THEN 'TAKE_12'
                    ELSE 'TIME_20' END exit_type,
          CASE WHEN stop_date IS NOT NULL AND (take_date IS NULL OR stop_date<=take_date) THEN -0.08
               WHEN take_date IS NOT NULL THEN 0.12
               ELSE c20/entry_open-1 END realized_return
      FROM first_hit
    ) SELECT signal_type,CASE WHEN trade_date<DATE '2023-01-01' THEN 'FIT_2020_2022' ELSE 'HOLDOUT_2023' END sample_group,
      exit_type,count(*) n,avg(realized_return) mean_return,median(realized_return) median_return,
      avg(c20/entry_open-1) mean_hold20,median(c20/entry_open-1) median_hold20
      FROM v GROUP BY signal_type,sample_group,exit_type ORDER BY signal_type,sample_group,exit_type
    ) TO '{OUT}' (HEADER,DELIMITER ',');
    """
    con.execute(q)
    print(con.execute(f"SELECT * FROM read_csv_auto('{OUT}')").fetchall())


if __name__ == "__main__":
    main()
