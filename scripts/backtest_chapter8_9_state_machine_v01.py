"""Chapter 8/9 state-machine probe and locked holdout backtest.

Research only. B2 requires breakout -> low-volume pullback -> reclaim/hold.
The parameter grid is evaluated in one DuckDB plan with parallel threads.
"""
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ROOT / "data/processed/chip_state_features_by_year_2018_2026_v2/year=*/data.parquet"
DAILY = ROOT / "data/processed/pit_b_daily_2018_2026_v2/daily/partition_year=*/data_0.parquet"
OUT = ROOT / "data/audit/chapter8_9_state_machine_v01.csv"


def main() -> None:
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    con.execute("PRAGMA enable_progress_bar=false")
    # Preserve the original probe definitions as a reproducible baseline.
    grid = [
        (1, 20, 1.00, 0.70, 0.000, 3, 1.15, 0),
        (2, 40, 1.00, 0.70, 0.000, 3, 1.15, 0),
        (3, 60, 1.00, 0.70, 0.000, 3, 1.08, 0),
        (4, 80, 1.00, 0.70, 0.000, 3, 1.08, 0),
        (5, 20, 1.50, 0.75, 0.010, 5, 1.15, 0),
        (6, 40, 1.50, 0.75, 0.010, 5, 1.15, 0),
        (7, 60, 1.50, 0.75, 0.010, 5, 1.08, 0),
        (8, 80, 1.50, 0.75, 0.010, 5, 1.08, 0),
        (101, 20, 1.00, 0.70, 0.000, 3, 1.15, 1),
        (102, 40, 1.00, 0.70, 0.000, 3, 1.15, 1),
        (103, 60, 1.00, 0.70, 0.000, 3, 1.08, 1),
        (104, 80, 1.00, 0.70, 0.000, 3, 1.08, 1),
        (105, 20, 1.50, 0.75, 0.010, 5, 1.15, 1),
        (106, 40, 1.50, 0.75, 0.010, 5, 1.15, 1),
        (107, 60, 1.50, 0.75, 0.010, 5, 1.08, 1),
        (108, 80, 1.50, 0.75, 0.010, 5, 1.08, 1),
    ]
    grid_id = 201
    for sector_gate in (0, 1):
        for narrow_pct in (20, 40, 60, 80):
            for breakout_mult, pullback_mult, confirm_days in (
                (1.00, 0.70, 3),
                (1.50, 0.75, 5),
                (2.00, 0.80, 7),
                (2.50, 0.85, 10),
            ):
                grid.append(
                    (
                        grid_id,
                        narrow_pct,
                        breakout_mult,
                        pullback_mult,
                        0.000 if breakout_mult == 1.00 else 0.010,
                        confirm_days,
                        1.15 if narrow_pct <= 40 else 1.08,
                        sector_gate,
                    )
                )
                grid_id += 1
    grid_values = ", ".join(
        f"({row[0]}, {row[1]}, {row[2]:.2f}, {row[3]:.2f}, {row[4]:.3f}, "
        f"{row[5]}, {row[6]:.2f}, {row[7]})"
        for row in grid
    )
    q = f"""
    CREATE OR REPLACE TEMP TABLE base AS
    SELECT d.symbol, d.trade_date, d.open, d.close, d.high, d.low, d.volume,
           d.industry,
           d.market_close,
           f.p10, f.p50, f.p90, f.average_cost, f.space20,
           f.concentration_20, f.base_retention, f.peak_count,
           try_cast(json_extract_string(f.peaks_json, '$[0].center_price') AS DOUBLE) peak1_center,
           try_cast(json_extract_string(f.peaks_json, '$[0].mass') AS DOUBLE) peak1_mass,
           try_cast(json_extract_string(f.peaks_json, '$[0].width_pct') AS DOUBLE) peak1_width,
           try_cast(json_extract_string(f.peaks_json, '$[0].prominence') AS DOUBLE) peak1_prominence,
           lag(d.close) OVER w prev_close,
           lag(f.p90) OVER w prev_p90,
           lag(f.p90, 2) OVER w prev2_p90,
           lag(f.p10) OVER w prev_p10,
           lag(f.average_cost) OVER w prev_avg,
           lag(f.concentration_20) OVER w prev_conc,
           lag(f.base_retention) OVER w prev_ret,
           lag(f.space20) OVER w prev_space,
           lag(f.p50) OVER w prev_p50,
           lag(f.p50, 2) OVER w prev2_p50,
           lag(d.volume) OVER w prev_volume,
           max(d.high) OVER (PARTITION BY d.symbol ORDER BY d.trade_date
             ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING) high60,
           min(d.low) OVER (PARTITION BY d.symbol ORDER BY d.trade_date
             ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING) low60,
           avg(d.close) OVER (PARTITION BY d.symbol ORDER BY d.trade_date
             ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) avgclose20,
           lag(d.close, 5) OVER w close5,
           lag(f.p50, 5) OVER w p505,
           lag(try_cast(json_extract_string(f.peaks_json, '$[0].center_price') AS DOUBLE)) OVER w prev_peak1_center,
           lag(try_cast(json_extract_string(f.peaks_json, '$[0].prominence') AS DOUBLE)) OVER w prev_peak1_prominence,
           lag(try_cast(json_extract_string(f.peaks_json, '$[0].prominence') AS DOUBLE), 2) OVER w prev2_peak1_prominence,
           avg(d.market_close) OVER (PARTITION BY d.symbol ORDER BY d.trade_date
             ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) market_avg20,
           sum(CASE WHEN d.close > f.p90 THEN 1 ELSE 0 END) OVER
             (PARTITION BY d.symbol ORDER BY d.trade_date
              ROWS BETWEEN 15 PRECEDING AND 1 PRECEDING) prior_break_count,
           median(d.volume) OVER (PARTITION BY d.symbol ORDER BY d.trade_date
             ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) vmed20,
           median(d.volume) OVER (PARTITION BY d.symbol ORDER BY d.trade_date
             ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING) vmed60,
           min(d.close) OVER (PARTITION BY d.symbol ORDER BY d.trade_date
             ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) low20,
           lag(f.p90-f.p10, 60) OVER w old_width,
           lead(d.trade_date) OVER w next_date,
           lead(d.open) OVER w next_open,
           lead(d.hard_valid) OVER w next_hard_valid,
           lead(d.buy_blocked_open) OVER w next_buy_blocked
    FROM read_parquet('{DAILY}', union_by_name=true) d
    JOIN read_parquet('{FEATURES}', union_by_name=true) f USING (symbol, trade_date)
    WHERE d.trade_date BETWEEN DATE '2019-01-02' AND DATE '2026-08-12'
      AND d.hard_valid AND f.strict_sample AND f.chip_input_valid
      AND f.daily_hard_valid AND f.minute_hard_valid
      AND f.daily_snapshot_id = d.snapshot_id
      AND NOT regexp_matches(d.symbol, '^(688|689)')
    WINDOW w AS (PARTITION BY d.symbol ORDER BY d.trade_date);
    CREATE OR REPLACE TEMP TABLE base_ctx AS
    SELECT r.*,
           CASE WHEN r.industry_n > 1
                THEN (r.industry_ret_sum-r.stock_ret)/(r.industry_n-1)
           END industry_loo_ret
    FROM (
      SELECT b.*,
             CASE WHEN b.prev_close > 0 THEN b.close/b.prev_close-1 END stock_ret,
             sum(CASE WHEN b.prev_close > 0 THEN b.close/b.prev_close-1 END)
               OVER (PARTITION BY b.trade_date, b.industry) industry_ret_sum,
             count(CASE WHEN b.prev_close > 0 THEN 1 END)
               OVER (PARTITION BY b.trade_date, b.industry) industry_n
      FROM base b
    ) r;
    COPY (
      WITH params AS (
        SELECT * FROM (VALUES {grid_values}
        ) AS t(param_id, narrow_pct, breakout_mult, pullback_mult,
               breakout_buffer, confirm_days, b5_low_mult, sector_gate)
      ), breakouts AS (
        SELECT b.*, p.*, row_number() OVER (
          PARTITION BY b.symbol, p.param_id ORDER BY b.trade_date) AS event_no
        FROM base_ctx b CROSS JOIN params p
        WHERE b.prev_p90 IS NOT NULL AND b.vmed20 IS NOT NULL
          AND b.close > b.prev_p90 * (1 + p.breakout_buffer)
          AND b.volume >= p.breakout_mult * b.vmed20
          AND b.close > b.prev_close
          AND b.prior_break_count >= p.confirm_days
          AND (b.prev_p90-b.prev_p10) <= b.old_width * (1-p.narrow_pct/100.0)
          AND (p.sector_gate=0 OR b.industry_loo_ret > 0)
      ), pullbacks AS (
        SELECT br.*, pb.trade_date pullback_date, pb.low pullback_low,
               pb.close pullback_close, pb.volume pullback_volume,
               rec.trade_date reclaim_date, rec.next_date entry_date,
               rec.next_open entry_open,
               row_number() OVER (PARTITION BY br.symbol, br.trade_date,
                 br.param_id ORDER BY rec.trade_date) rn
        FROM breakouts br
        JOIN base_ctx pb ON pb.symbol=br.symbol
          AND pb.trade_date>br.trade_date
          AND pb.trade_date<=br.trade_date + INTERVAL 10 DAY
          AND pb.volume <= pb.vmed20 * br.pullback_mult
          AND pb.low <= br.close
        JOIN base_ctx rec ON rec.symbol=br.symbol
          AND rec.trade_date>pb.trade_date
          AND rec.trade_date<=pb.trade_date + INTERVAL 3 DAY
          AND rec.close > rec.prev_p90 * (1+br.breakout_buffer)
          AND rec.close > pb.low
          AND rec.close >= rec.prev_close
          AND rec.market_close > rec.market_avg20
          AND (br.sector_gate=0 OR rec.industry_loo_ret > 0)
      ), raw_entries AS (
        SELECT symbol, param_id, reclaim_date, entry_date, entry_open,
               'B2_SM' signal
        FROM pullbacks
        WHERE rn=1 AND next_hard_valid AND NOT next_buy_blocked
        UNION ALL
        SELECT b.symbol, p.param_id, b.trade_date reclaim_date,
               b.next_date entry_date, b.next_open entry_open, 'B5_SM' signal
        FROM base_ctx b CROSS JOIN params p
        WHERE b.prev_avg IS NOT NULL AND b.close > b.prev_avg
          AND b.prev_close <= b.prev_avg AND b.volume < b.vmed20 * p.pullback_mult
          AND b.close >= b.prev_close
          AND b.close <= b.low20 * p.b5_low_mult
          AND b.prior_break_count = 0
          AND b.base_retention >= b.prev_ret
          AND b.concentration_20 >= b.prev_conc
          AND b.next_hard_valid AND NOT b.next_buy_blocked
          AND b.market_close > b.market_avg20
          AND (p.sector_gate=0 OR b.industry_loo_ret > 0)
          AND b.trade_date BETWEEN DATE '2020-01-02' AND DATE '2026-08-12'
        UNION ALL
        SELECT b.symbol, p.param_id, b.trade_date reclaim_date,
               b.next_date entry_date, b.next_open entry_open, 'B1' signal
        FROM base_ctx b CROSS JOIN params p
        WHERE b.old_width IS NOT NULL
          AND b.peak_count = 1
          AND b.p90-b.p10 <= b.old_width * (1-p.narrow_pct/100.0)
          AND b.close > b.p90 AND b.prev_close <= b.prev_p90
          AND b.volume >= b.vmed20 AND b.close >= b.low20
          AND b.next_hard_valid AND NOT b.next_buy_blocked
          AND b.market_close > b.market_avg20
          AND (p.sector_gate=0 OR b.industry_loo_ret > 0)
        UNION ALL
        SELECT b.symbol, p.param_id, b.trade_date reclaim_date,
               b.next_date entry_date, b.next_open entry_open, 'B3' signal
        FROM base_ctx b CROSS JOIN params p
        WHERE b.peak_count = 2 AND b.p50 > b.prev_p50 AND b.close > b.p50
          AND b.peak1_center > b.prev_peak1_center
          AND b.peak1_prominence >= b.prev_peak1_prominence
          AND b.prev_close <= b.prev_p50 AND b.close > b.prev_close
          AND b.prior_break_count BETWEEN 1 AND 4
          AND b.base_retention >= b.prev_ret
          AND b.next_hard_valid AND NOT b.next_buy_blocked
          AND b.market_close > b.market_avg20
          AND (p.sector_gate=0 OR b.industry_loo_ret > 0)
        UNION ALL
        SELECT b.symbol, p.param_id, b.trade_date reclaim_date,
               b.next_date entry_date, b.next_open entry_open, 'B4' signal
        FROM base_ctx b CROSS JOIN params p
        WHERE b.close > b.avgclose20 AND b.prev_close <= b.avgclose20
          AND b.close > b.p50
          AND b.volume <= b.vmed20 * p.pullback_mult
          AND b.base_retention >= b.prev_ret
          AND b.concentration_20 >= b.prev_conc
          AND b.next_hard_valid AND NOT b.next_buy_blocked
          AND b.market_close > b.market_avg20
          AND (p.sector_gate=0 OR b.industry_loo_ret > 0)
        UNION ALL
        SELECT b.symbol, p.param_id, b.trade_date reclaim_date,
               b.next_date entry_date, b.next_open entry_open, 'B6' signal
        FROM base_ctx b CROSS JOIN params p
        -- B6 starts from the audited cost-support reclaim candidate.  The
        -- executable rule adds p90, prior-break, concentration and volume
        -- confirmation to control false reclaims and signal frequency.
        WHERE b.close > b.p50 AND b.prev_close <= b.prev_p50
          AND b.close > b.p90
          AND b.volume >= b.vmed20 * 1.5
          AND b.prior_break_count BETWEEN 1 AND 4
          AND b.base_retention >= b.prev_ret
          AND b.concentration_20 >= b.prev_conc
          AND b.next_hard_valid AND NOT b.next_buy_blocked
          AND b.market_close > b.market_avg20
          AND (p.sector_gate=0 OR b.industry_loo_ret > 0)
      ), entries AS (
        SELECT * EXCLUDE(prev_signal_date, rn_cooldown)
        FROM (
          SELECT r.*,
                 lag(reclaim_date) OVER
                   (PARTITION BY symbol, param_id, signal ORDER BY reclaim_date) prev_signal_date,
                 row_number() OVER
                   (PARTITION BY symbol, param_id, reclaim_date, signal ORDER BY signal) rn_cooldown
          FROM raw_entries r
        ) z
        WHERE rn_cooldown=1
          AND (prev_signal_date IS NULL OR reclaim_date > prev_signal_date + INTERVAL 40 DAY)
      ), future AS (
        SELECT e.*, x.trade_date exit_date, x.close exit_close,
          x.close <= e.entry_open*0.92 AS stop_hit,
          x.close < x.p10 AND x.prev_close >= x.prev_p10
            AND x.volume > x.vmed20 AND x.close < x.open AS s5_hit,
          x.close < x.prev_p90 AND x.prev_close < x.prev2_p90
            AND x.close < x.prev_close AND x.volume > x.vmed20 AS s1_hit,
          x.concentration_20 > x.prev_conc AND x.close < x.prev_close
            AND x.peak1_prominence < x.prev_peak1_prominence
            AND x.prev_peak1_prominence < x.prev2_peak1_prominence AS s2_hit,
          x.base_retention < x.prev_ret AND x.close < x.p50
            AND x.prev_close < x.prev2_p50
            AND x.peak1_center < x.prev_peak1_center AS s3_hit,
          x.space20 < x.prev_space AND x.close < x.prev_avg
            AND x.close < x.peak1_center AS s6_hit,
          x.peak_count >= 2 AND x.close < x.p50
            AND x.prev_close >= x.prev_p50 AS s4_hit,
          x.trade_date >= e.entry_date + INTERVAL 60 DAY AS time60_hit,
          CASE WHEN x.close <= e.entry_open*0.92 THEN 'STOP'
            WHEN x.close < x.p10 AND x.prev_close >= x.prev_p10
                 AND x.volume > x.vmed20 AND x.close < x.open
                 THEN 'S5_GAP_MAIN_PEAK'
            WHEN x.close < x.prev_p90 AND x.prev_close < x.prev2_p90
                 AND x.close < x.prev_close AND x.volume > x.vmed20
                 THEN 'S1_STRUCT'
            WHEN x.concentration_20 > x.prev_conc AND x.close < x.prev_close
                 AND x.peak1_prominence < x.prev_peak1_prominence
                 AND x.prev_peak1_prominence < x.prev2_peak1_prominence
                THEN 'S2_CONC'
            WHEN x.base_retention < x.prev_ret AND x.close < x.p50
                 AND x.prev_close < x.prev2_p50
                 AND x.peak1_center < x.prev_peak1_center
                THEN 'S3_RETENTION'
            WHEN x.space20 < x.prev_space AND x.close < x.prev_avg
                 AND x.close < x.peak1_center
                THEN 'S6_SPACE'
            WHEN x.peak_count >= 2 AND x.close < x.p50 AND x.prev_close >= x.prev_p50
                 THEN 'S4_DOUBLE_PEAK_FAILURE'
            WHEN x.trade_date >= e.entry_date + INTERVAL 60 DAY THEN 'TIME60'
          END exit_reason
        FROM entries e JOIN base_ctx x ON x.symbol=e.symbol
          AND x.trade_date>e.entry_date
          AND x.trade_date<=e.entry_date + INTERVAL 60 DAY
      ), first_exit AS (
        SELECT * EXCLUDE(rn_exit) FROM (
          SELECT *, row_number() OVER (PARTITION BY symbol, reclaim_date,
            param_id, signal ORDER BY exit_date) rn_exit
          FROM future WHERE exit_reason IS NOT NULL
        ) WHERE rn_exit=1
      )
      SELECT e.param_id, e.symbol, e.reclaim_date signal_date, e.entry_date,
             e.entry_open, e.signal, f.exit_date, f.exit_close,
             f.exit_reason, f.stop_hit, f.s1_hit, f.s2_hit, f.s3_hit,
             f.s4_hit, f.s5_hit, f.s6_hit, f.time60_hit,
             f.exit_close/e.entry_open-1.0 gross_return,
             (f.exit_close/e.entry_open)*(1-0.001)*(1-0.0003)
               *(1-0.0003-0.0005)-1.0 net_return,
             CASE WHEN e.reclaim_date < DATE '2024-01-01' THEN 'PROBE_2020_2023'
                  ELSE 'HOLDOUT_2024_2026' END sample_group
      FROM entries e
      LEFT JOIN first_exit f USING (param_id, symbol, reclaim_date, signal)
      WHERE e.reclaim_date BETWEEN DATE '2020-01-02' AND DATE '2026-08-12'
    ) TO '{OUT}' (HEADER, DELIMITER ',');
    """
    con.execute(q)
    print(OUT)
    print(con.execute(f"""
      SELECT param_id, sample_group, count(*) n, count(*)/4.0 avg_year,
             avg(TRY_CAST(net_return AS DOUBLE)) mean,
             median(TRY_CAST(net_return AS DOUBLE)) median,
             avg(CAST(TRY_CAST(net_return AS DOUBLE)>0 AS INTEGER)) win
      FROM read_csv_auto('{OUT}') GROUP BY ALL ORDER BY param_id, sample_group
    """).fetchdf().to_string(index=False))


if __name__ == "__main__":
    main()
