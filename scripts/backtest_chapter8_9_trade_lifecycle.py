"""Research-only trade lifecycle for the frozen chapter 8/9 probe.

This is a transaction-level bridge: B1/B2/B5 entries followed by explicit,
auditable S1-S6 proxy exits. It is not a promotion or live-trading script.
"""
import os
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ROOT / "data/processed/chip_state_features_2018_2026_v2/bucket=*/data.parquet"
DAILY = ROOT / "data/processed/pit_b_daily_2018_2026_v2/daily/partition_year=*/data_0.parquet"
PARAMS = Path(os.environ.get("CY_PARAMS", str(ROOT / "data/audit/chapter8_9_frozen_params_v01.csv")))
OUT = Path(os.environ.get("CY_OUT", str(ROOT / "data/audit/chapter8_9_trade_lifecycle_v01.csv")))
STOP_PCT = float(os.environ.get("CY_STOP_PCT", "8.0"))


def main() -> None:
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    con.execute("PRAGMA enable_progress_bar=false")
    q = f"""
    COPY (
      WITH params AS (
        SELECT * FROM read_csv_auto('{PARAMS}')
      ), x AS (
        SELECT d.symbol, d.trade_date, d.close, d.volume, d.hard_valid,
               d.available_at, d.snapshot_id, f.p10, f.p50, f.p90,
               f.average_cost, f.space20, f.concentration_20, f.base_retention,
               f.peak_count, f.realized_volatility,
               lag(d.close) OVER w pc, lag(f.p90) OVER w pp90,
               lag(f.p10) OVER w pp10, lag(f.concentration_20) OVER w pconc,
               lag(f.base_retention) OVER w pbase,
               lag(f.average_cost) OVER w pavg,
               lag(f.space20) OVER w pspace,
               lag(f.peak_count) OVER w ppeaks,
               median(d.volume) OVER (PARTITION BY d.symbol ORDER BY d.trade_date
                 ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) vmed20,
               median(d.volume) OVER (PARTITION BY d.symbol ORDER BY d.trade_date
                 ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) vmed10,
               median(d.volume) OVER (PARTITION BY d.symbol ORDER BY d.trade_date
                 ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING) vmed60,
               sum(CASE WHEN d.close > f.p90 THEN 1 ELSE 0 END) OVER
                 (PARTITION BY d.symbol ORDER BY d.trade_date
                  ROWS BETWEEN 15 PRECEDING AND 1 PRECEDING) prior_break_count,
               lag(f.p90-f.p10, 60) OVER w old_width,
               lead(d.trade_date) OVER w entry_date,
               lead(d.open) OVER w entry_open,
               lead(d.close, 5) OVER w exit_fwd5_close,
               lead(d.close, 10) OVER w exit_fwd10_close,
               lead(d.close, 20) OVER w exit_fwd20_close,
               lead(f.p10) OVER w entry_p10,
               lead(f.p90) OVER w entry_p90
        FROM read_parquet('{DAILY}', union_by_name=true) d
        JOIN read_parquet('{FEATURES}', union_by_name=true) f USING (symbol, trade_date)
        WHERE d.trade_date BETWEEN DATE '2020-01-02' AND DATE '2026-08-12'
          AND d.hard_valid AND f.chip_input_valid AND f.daily_hard_valid
        WINDOW w AS (PARTITION BY d.symbol ORDER BY d.trade_date)
      ), entries AS (
        SELECT x.*, p.narrow_pct, p.vol_window, 1.0 AS vol_mult, p.confirm_days, p.breakout_buffer,
          CASE
          WHEN p.signal='B1' AND old_width IS NOT NULL
               AND (pp90-pp10) <= old_width*(1-p.narrow_pct/100.0)
               AND close > pp90*(1+p.breakout_buffer) AND pc <= pp90
               AND prior_break_count >= p.confirm_days
               AND volume >= 1.0
                 * CASE p.vol_window WHEN 10 THEN vmed10 WHEN 60 THEN vmed60 ELSE vmed20 END THEN 'B1'
          WHEN p.signal='B2' AND close > pp90*(1+p.breakout_buffer) AND pc <= pp90
               AND prior_break_count >= p.confirm_days
               AND volume >= 1.0
                 * CASE p.vol_window WHEN 10 THEN vmed10 WHEN 60 THEN vmed60 ELSE vmed20 END THEN 'B2'
          WHEN p.signal='B5' AND close > pavg AND pc <= pavg
               AND prior_break_count >= p.confirm_days
               AND volume < 0.7 * CASE p.vol_window WHEN 10 THEN vmed10 WHEN 60 THEN vmed60 ELSE vmed20 END THEN 'B5'
          END signal
        FROM x JOIN params p ON p.board=CASE WHEN regexp_matches(x.symbol, '^(300|301)') THEN 'CHINEXT' WHEN regexp_matches(x.symbol, '^(688|689)') THEN 'STAR' ELSE 'MAIN' END
      ), bought AS (
        SELECT symbol, trade_date signal_date, entry_date, entry_open AS entry_close,
               entry_p10, entry_p90, signal,
               narrow_pct, vol_window, vol_mult, confirm_days, breakout_buffer,
               CASE WHEN regexp_matches(symbol, '^(300|301)') THEN 'CHINEXT' WHEN regexp_matches(symbol, '^(688|689)') THEN 'STAR' ELSE 'MAIN' END board
        FROM entries
        WHERE signal IS NOT NULL AND entry_open IS NOT NULL
      ), future AS (
        SELECT b.*, x.trade_date exit_date, x.close exit_close,
          x.exit_fwd5_close, x.exit_fwd10_close, x.exit_fwd20_close,
          CASE
            WHEN x.close <= b.entry_close*(1-{STOP_PCT}/100.0) THEN 'STOP'
            WHEN x.close < x.p10 AND x.close < x.pc AND x.volume > x.vmed20 THEN 'S1/S5'
            WHEN x.concentration_20 > x.pconc AND x.close <= x.pc AND x.volume > x.vmed20 THEN 'S2'
            WHEN x.base_retention < x.pbase AND x.close < x.p50 THEN 'S3'
            WHEN x.peak_count >= 2 AND x.close < x.p50 THEN 'S4'
            WHEN x.pspace > 0 AND x.space20 < x.pspace AND x.close < x.pavg THEN 'S6'
          END exit_reason
        FROM bought b JOIN x ON x.symbol=b.symbol
          AND x.trade_date > b.entry_date
          AND x.trade_date <= b.entry_date + INTERVAL 60 DAY
      ), first_exit AS (
        SELECT * EXCLUDE(rn) FROM (
          SELECT *, row_number() OVER (PARTITION BY symbol, signal_date ORDER BY exit_date) rn
          FROM future WHERE exit_reason IS NOT NULL
        ) WHERE rn=1
      )
      SELECT *, exit_close/entry_close-1.0 AS gross_return,
             exit_fwd5_close/exit_close-1.0 AS exit_fwd5_return,
             exit_fwd10_close/exit_close-1.0 AS exit_fwd10_return,
             exit_fwd20_close/exit_close-1.0 AS exit_fwd20_return,
             (exit_close/entry_close)*(1-0.0003-0.001)-1.0-0.0003 AS net_return,
             CASE WHEN signal_date < DATE '2024-01-01' THEN 'PROBE_2020_2023'
                  ELSE 'HOLDOUT_2024_2026' END sample_group
      FROM first_exit
    ) TO '{OUT}' (HEADER, DELIMITER ',');
    """
    con.execute(q)
    print(OUT)
    print(con.execute(f"SELECT sample_group, board, signal, exit_reason, count(*) n, avg(net_return), median(net_return) FROM read_csv_auto('{OUT}') GROUP BY ALL ORDER BY 1,2,3,4").fetchall())


if __name__ == '__main__':
    main()
