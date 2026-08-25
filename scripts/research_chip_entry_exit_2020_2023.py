"""Causal chip entry/exit event study for the 2020-2023 research goal.

This is deliberately not a portfolio backtest.  Each signal is an independent
research event.  A signal on close t is filled only at the next valid day's
open, and all features used for the signal are from t or earlier.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DAILY = ROOT / "data/processed/pit_b_daily_2018_2026_v2/daily/partition_year=*/data_0.parquet"
FEATURES = ROOT / "data/processed/chip_state_features_2018_2026_v2/bucket=*/data.parquet"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-01-02")
    ap.add_argument("--end", default="2020-06-30")
    ap.add_argument("--out", default="data/audit/chip_entry_exit_probe_2020_short.csv")
    ap.add_argument("--cooldown-days", type=int, default=20)
    args = ap.parse_args()
    out = (ROOT / args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    q = f"""
    COPY (
      WITH market_daily AS (
        SELECT trade_date, avg(market_close) AS market_close
        FROM read_parquet('{DAILY}', union_by_name=true)
        WHERE trade_date BETWEEN DATE '2018-01-02' AND DATE '{args.end}'
        GROUP BY trade_date
      ), market AS (
        SELECT *, avg(market_close) OVER (ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) AS market_avg20
        FROM market_daily
      ), base AS (
        SELECT d.symbol, d.trade_date, d.open, d.high, d.low, d.close,
               d.volume, d.industry, m.market_close, m.market_avg20, d.hard_valid,
               d.buy_blocked_open, d.sell_blocked_open, d.available_at AS d_available,
               d.snapshot_id AS d_snapshot, f.* EXCLUDE(symbol, trade_date),
               lag(d.close) OVER w AS prev_close,
               lag(f.p90) OVER w AS prev_p90,
               lag(f.p50) OVER w AS prev_p50,
               lag(f.average_cost) OVER w AS prev_avg,
               lag(f.asr) OVER w AS prev_asr,
               lag(f.space20) OVER w AS prev_space,
               lag(f.concentration_20) OVER w AS prev_conc,
               lag(f.peak_count) OVER w AS prev_peak_count,
               lead(d.trade_date) OVER w AS entry_date,
               lead(d.open) OVER w AS entry_open,
               lead(d.hard_valid) OVER w AS entry_hard_valid,
               lead(d.buy_blocked_open) OVER w AS entry_buy_blocked,
               lead(d.close, 6) OVER w AS c5,
               lead(d.close, 11) OVER w AS c10,
               lead(d.close, 21) OVER w AS c20,
               lead(d.close, 1) OVER w AS close_next
        FROM read_parquet('{DAILY}', union_by_name=true) d
        JOIN read_parquet('{FEATURES}', union_by_name=true) f
          USING (symbol, trade_date)
        JOIN market m USING (trade_date)
        WHERE d.trade_date BETWEEN DATE '2018-01-02' AND DATE '{args.end}'
          AND f.strict_sample AND f.state_chain_valid
          AND d.hard_valid AND d.available_at <= d.decision_at
        WINDOW w AS (PARTITION BY d.symbol ORDER BY d.trade_date)
      ), signals AS (
        SELECT *,
          CASE
            WHEN close > p90 AND prev_close <= prev_p90 AND volume >=
                 median(volume) OVER (PARTITION BY symbol ORDER BY trade_date
                   ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)
                 AND prev_conc IS NOT NULL AND concentration_20 <= prev_conc
                 AND market_close > market_avg20 THEN 'ACCUMULATION_BREAKOUT'
            WHEN close > average_cost AND prev_close <= prev_avg
                 AND asr >= coalesce(prev_asr, asr)
                 AND market_close > market_avg20 THEN 'COST_RECLAIM'
            WHEN close < p50 AND prev_close >= prev_p50
                 AND concentration_20 > coalesce(prev_conc, concentration_20)
                 AND asr < coalesce(prev_asr, asr) THEN 'DISTRIBUTION_EXIT'
            WHEN close < average_cost AND prev_close >= prev_avg
                 AND space20 < coalesce(prev_space, space20) THEN 'COST_FAILURE_EXIT'
            ELSE NULL
          END AS event_type
        FROM base
      ), events AS (
        SELECT *, row_number() OVER (
          PARTITION BY symbol, event_type ORDER BY trade_date
        ) AS event_seq,
        lag(trade_date) OVER (PARTITION BY symbol, event_type ORDER BY trade_date) AS prev_event_date
        FROM signals
        WHERE event_type IS NOT NULL
      ), dedup AS (
        SELECT * FROM events
        WHERE trade_date >= DATE '{args.start}'
          AND entry_date IS NOT NULL AND entry_open > 0
          AND entry_hard_valid AND NOT entry_buy_blocked
          AND entry_date > trade_date
          AND (prev_event_date IS NULL OR trade_date > prev_event_date + INTERVAL '{args.cooldown_days} days')
      )
      SELECT symbol, trade_date AS signal_date, entry_date, entry_open,
             event_type, event_seq, close AS signal_close, asr, space20,
             concentration_20, average_cost, p10, p50, p90, market_close,
             market_avg20, d_available, d_snapshot,
             CASE WHEN event_type LIKE '%EXIT' THEN NULL ELSE c5/entry_open-1 END AS ret_5d,
             CASE WHEN event_type LIKE '%EXIT' THEN NULL ELSE c10/entry_open-1 END AS ret_10d,
             CASE WHEN event_type LIKE '%EXIT' THEN NULL ELSE c20/entry_open-1 END AS ret_20d,
             CASE WHEN event_type LIKE '%EXIT' THEN close_next/entry_open-1 END AS exit_next_return,
             CASE WHEN event_type LIKE '%EXIT' THEN c10/entry_open-1 END AS exit_hold10_return,
             CASE WHEN event_type LIKE '%EXIT' AND close_next > 0
                  THEN c10/close_next-1 END AS exit_avoided_hold10_return
      FROM dedup
    ) TO '{out}' (HEADER, DELIMITER ',');
    """
    con.execute(q)
    summary = con.execute(
        f"""SELECT event_type, count(*) AS n,
                   avg(ret_5d) AS mean_5d, median(ret_5d) AS median_5d,
                   avg(ret_10d) AS mean_10d, median(ret_10d) AS median_10d,
                   avg(ret_20d) AS mean_20d, median(ret_20d) AS median_20d
            FROM read_csv_auto('{out}') GROUP BY event_type ORDER BY event_type"""
    ).fetchall()
    print(f"output={out}")
    for row in summary:
        print(row)


if __name__ == "__main__":
    main()
