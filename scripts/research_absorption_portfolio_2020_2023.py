"""Capacity-aware research portfolio for the absorption candidate.

Research only: no broker access. Signals are formed at close t and filled at
the next valid open; signals are cooldown-limited per symbol and capped per
entry date. This screen does not yet enforce portfolio position non-overlap;
the final execution engine must do that. Costs are deliberately explicit and
conservative.
"""
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DAILY = ROOT / "data/processed/pit_b_daily_2018_2026_v2/daily/partition_year=*/data_0.parquet"
FEATURES = ROOT / "data/processed/chip_state_features_2018_2026_v2/bucket=*/data.parquet"
OUT = ROOT / "data/audit/chip_absorption_portfolio_2020_2023.csv"


def main() -> None:
    con = duckdb.connect()
    q = f"""
    COPY (WITH market_daily AS (
      SELECT trade_date,avg(market_close) market_close
      FROM read_parquet('{DAILY}',union_by_name=true)
      WHERE trade_date BETWEEN DATE '2018-01-02' AND DATE '2023-12-29'
      GROUP BY trade_date
    ), market AS (
      SELECT *,avg(market_close) OVER (ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) avg20,
        lag(market_close,20) OVER (ORDER BY trade_date) close20
      FROM market_daily
    ), x AS (
      SELECT d.symbol,d.trade_date,d.close,f.average_cost,f.asr,f.concentration_20,
        m.market_close,m.avg20,m.close20,lag(d.close) OVER w prev_close,
        lag(f.asr) OVER w prev_asr,lag(f.concentration_20) OVER w prev_conc,
        lead(d.open) OVER w entry_open,lead(d.trade_date) OVER w entry_date,
        lead(d.hard_valid) OVER w entry_valid,lead(d.buy_blocked_open) OVER w entry_blocked
      FROM read_parquet('{DAILY}',union_by_name=true) d
      JOIN read_parquet('{FEATURES}',union_by_name=true) f USING(symbol,trade_date)
      JOIN market m USING(trade_date)
      WHERE d.trade_date BETWEEN DATE '2018-01-02' AND DATE '2023-12-29'
        AND d.hard_valid AND f.strict_sample AND f.state_chain_valid
      WINDOW w AS (PARTITION BY d.symbol ORDER BY d.trade_date)
    ), raw AS (
      SELECT *,CASE WHEN close<=average_cost AND close>prev_close
        AND asr>=coalesce(prev_asr,asr)
        AND concentration_20<=coalesce(prev_conc,concentration_20)
        THEN 1 ELSE 0 END signal_flag
      FROM x
    ), s AS (
      SELECT *,lag(CASE WHEN signal_flag=1 THEN trade_date END IGNORE NULLS)
        OVER(PARTITION BY symbol ORDER BY trade_date) prev_signal_date
      FROM raw
    ), e AS (
      SELECT *,CASE WHEN market_close>avg20 AND close20 IS NOT NULL AND market_close>=close20
        THEN 'BULL' WHEN market_close<avg20 AND close20 IS NOT NULL AND market_close<close20
        THEN 'BEAR' ELSE 'RANGE' END regime
      FROM s WHERE signal_flag=1 AND entry_date>trade_date AND entry_open>0 AND entry_valid
        AND NOT entry_blocked AND trade_date>=DATE '2020-01-02'
        AND trade_date>coalesce(prev_signal_date+INTERVAL 20 DAY,DATE '1900-01-01')
    ), future AS (
      SELECT e.symbol,e.trade_date,d.trade_date future_date,d.high,d.low,d.close,
        row_number() OVER(PARTITION BY e.symbol,e.trade_date ORDER BY d.trade_date) seq
      FROM e JOIN read_parquet('{DAILY}',union_by_name=true) d
        ON d.symbol=e.symbol AND d.trade_date>e.trade_date
        AND d.trade_date<=e.trade_date+INTERVAL 40 DAY AND d.hard_valid
      QUALIFY seq<=20
    ), h AS (
      SELECT e.*,min(CASE WHEN f.low<=e.entry_open*.92 THEN f.future_date END) stop_date,
        min(CASE WHEN f.high>=e.entry_open*1.12 THEN f.future_date END) take_date,
        min(f.future_date) last_date
      FROM e LEFT JOIN future f USING(symbol,trade_date) GROUP BY ALL
    ), v AS (
      SELECT *,CASE WHEN stop_date IS NOT NULL AND (take_date IS NULL OR stop_date<=take_date)
        THEN stop_date WHEN take_date IS NOT NULL THEN take_date ELSE last_date END exit_date,
        CASE WHEN stop_date IS NOT NULL AND (take_date IS NULL OR stop_date<=take_date)
        THEN -.08 WHEN take_date IS NOT NULL THEN .12
        ELSE (SELECT close FROM future z WHERE z.symbol=h.symbol AND z.trade_date=h.trade_date AND z.future_date=h.last_date)-entry_open END / entry_open gross_return
      FROM h
    ), ranked AS (
      SELECT *,row_number() OVER(PARTITION BY entry_date ORDER BY CASE regime WHEN 'BEAR' THEN 0 WHEN 'RANGE' THEN 1 ELSE 2 END,symbol) day_rank
      FROM v
    ), chosen AS (
      -- 31 bps round trip: 6 bps commission, 10 bps slippage,
      -- 5 bps stamp duty, and 10 bps fixed impact allowance.
      SELECT *,gross_return-0.0031 net_return
      FROM ranked WHERE day_rank<=20
    ) SELECT CASE WHEN trade_date<DATE '2023-01-01' THEN 'FIT_2020_2022' ELSE 'HOLDOUT_2023' END sample_group,
      regime,count(*) trades,avg(gross_return) mean_gross,avg(net_return) mean_net,
      median(net_return) median_net,avg(CASE WHEN net_return>0 THEN 1 ELSE 0 END) win_rate
      FROM chosen GROUP BY 1,2 ORDER BY 1,2
    ) TO '{OUT}' (HEADER,DELIMITER ',');
    """
    con.execute(q)
    print(con.execute(f"SELECT * FROM read_csv_auto('{OUT}')").fetchall())


if __name__ == "__main__":
    main()
