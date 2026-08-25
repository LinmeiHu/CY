"""Stratify causal chip events by broad market regime."""
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DAILY = ROOT / "data/processed/pit_b_daily_2018_2026_v2/daily/partition_year=*/data_0.parquet"
FEATURES = ROOT / "data/processed/chip_state_features_2018_2026_v2/bucket=*/data.parquet"
OUT = ROOT / "data/audit/chip_market_regime_study_2020_2023.csv"


def main() -> None:
    con = duckdb.connect()
    query = f"""
    COPY (
      WITH market_daily AS (
        SELECT trade_date, avg(market_close) AS market_close
        FROM read_parquet('{DAILY}', union_by_name=true)
        WHERE trade_date BETWEEN DATE '2018-01-02' AND DATE '2023-12-29'
        GROUP BY trade_date
      ), market AS (
        SELECT *,
          avg(market_close) OVER (ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) AS avg20,
          lag(market_close, 20) OVER (ORDER BY trade_date) AS close20
        FROM market_daily
      ), b AS (
        SELECT d.symbol,d.trade_date,d.close,d.open,d.volume,d.hard_valid,d.buy_blocked_open,
          m.market_close,m.avg20,m.close20,
          f.p90,f.p50,f.average_cost,f.asr,f.concentration_20,f.space20,
          lag(d.close) OVER w pc,lag(f.p90) OVER w pp90,
          lag(f.p50) OVER w pp50,lag(f.average_cost) OVER w pavg,
          lag(f.asr) OVER w pasr,lag(f.concentration_20) OVER w pconc,
          lag(f.space20) OVER w pspace,
          lead(d.open) OVER w entry_open,lead(d.hard_valid) OVER w ev,
          lead(d.buy_blocked_open) OVER w eb,lead(d.close) OVER w close_next,
          lead(d.close,6) OVER w c5,lead(d.close,11) OVER w c10,
          lead(d.close,21) OVER w c20
        FROM read_parquet('{DAILY}', union_by_name=true) d
        JOIN read_parquet('{FEATURES}', union_by_name=true) f USING(symbol,trade_date)
        JOIN market m USING(trade_date)
        WHERE d.trade_date BETWEEN DATE '2018-01-02' AND DATE '2023-12-29'
          AND d.hard_valid AND f.strict_sample AND f.state_chain_valid
        WINDOW w AS (PARTITION BY d.symbol ORDER BY d.trade_date)
      ), e AS (
        SELECT *,
          CASE WHEN market_close > avg20 AND close20 IS NOT NULL AND market_close >= close20 THEN 'BULL'
               WHEN market_close < avg20 AND close20 IS NOT NULL AND market_close < close20 THEN 'BEAR'
               ELSE 'RANGE' END AS regime,
          CASE WHEN close > p90 AND pc <= pp90 AND market_close > avg20 THEN 'ACCUMULATION_BREAKOUT'
               WHEN close > average_cost AND pc <= pavg AND asr >= coalesce(pasr,asr) AND market_close > avg20 THEN 'COST_RECLAIM'
               WHEN close < p50 AND pc >= pp50 AND concentration_20 > coalesce(pconc,concentration_20) AND asr < coalesce(pasr,asr) THEN 'DISTRIBUTION_EXIT'
               WHEN close < average_cost AND pc >= pavg AND space20 < coalesce(pspace,space20) THEN 'COST_FAILURE_EXIT'
          END AS event_type
        FROM b
      )
      SELECT CASE WHEN trade_date < DATE '2023-01-01' THEN 'FIT_2020_2022' ELSE 'HOLDOUT_2023' END sample_group,
        event_type,regime,count(*) n,
        avg(c5/entry_open-1) FILTER (WHERE event_type NOT LIKE '%EXIT' AND ev AND NOT eb AND entry_open>0) ret5,
        avg(c10/entry_open-1) FILTER (WHERE event_type NOT LIKE '%EXIT' AND ev AND NOT eb AND entry_open>0) ret10,
        avg(c20/entry_open-1) FILTER (WHERE event_type NOT LIKE '%EXIT' AND ev AND NOT eb AND entry_open>0) ret20,
        median(c20/entry_open-1) FILTER (WHERE event_type NOT LIKE '%EXIT' AND ev AND NOT eb AND entry_open>0) med20,
        avg(c10/close_next-1) FILTER (WHERE event_type LIKE '%EXIT' AND ev AND NOT eb AND entry_open>0 AND close_next>0) exit_avoided10
      FROM e WHERE event_type IS NOT NULL
      GROUP BY sample_group,event_type,regime ORDER BY sample_group,event_type,regime
    ) TO '{OUT}' (HEADER, DELIMITER ',');
    """
    con.execute(query)
    print(con.execute(f"SELECT * FROM read_csv_auto('{OUT}')").fetchall())


if __name__ == "__main__":
    main()
