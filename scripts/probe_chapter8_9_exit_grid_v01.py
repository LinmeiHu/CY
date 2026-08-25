"""Parallel exit-rule sensitivity probe on the frozen 231 entry cohort."""
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
ENTRIES = ROOT / "data/audit/chapter8_9_state_machine_v01.csv"
DAILY = ROOT / "data/processed/pit_b_daily_2018_2026_v2/daily/partition_year=*/data_0.parquet"
FEATURES = ROOT / "data/processed/chip_state_features_by_year_2018_2026_v2/year=*/data.parquet"
OUT = ROOT / "data/audit/chapter8_9_exit_grid_v01.csv"


def main() -> None:
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    variants = []
    variant_id = 1
    for stop in (0.08, 0.10, 0.12):
        for confirm in (0, 1, 2):
            for priority in ("STOP_FIRST", "STRUCT_FIRST"):
                variants.append((variant_id, stop, confirm, priority, "ALL"))
                variant_id += 1
        # Pre-registered recovery variant: hard failures remain immediate;
        # only S1/S2 require the selected persistence window.
        variants.append((variant_id, stop, 2, "STOP_FIRST", "S1S2_GRACE"))
        variant_id += 1
    values = ", ".join(
        f"({i}, {stop:.3f}, {confirm}, '{priority}', '{mode}')"
        for i, stop, confirm, priority, mode in variants
    )
    query = f"""
    CREATE OR REPLACE TEMP TABLE b AS
    SELECT d.symbol, d.trade_date, d.open, d.close, d.low, d.volume,
           f.p10, f.p50, f.p90, f.space20, f.concentration_20,
           f.base_retention, f.peak_count,
           try_cast(json_extract_string(f.peaks_json, '$[0].center_price') AS DOUBLE) peak1_center,
           try_cast(json_extract_string(f.peaks_json, '$[0].prominence') AS DOUBLE) peak1_prominence,
           lag(d.close) OVER w prev_close, lag(d.close, 2) OVER w prev2_close,
           lag(f.p90) OVER w prev_p90, lag(f.p90, 2) OVER w prev2_p90,
           lag(f.p10) OVER w prev_p10,
           lag(f.p50) OVER w prev_p50, lag(f.p50, 2) OVER w prev2_p50,
           lag(f.concentration_20) OVER w prev_conc,
           lag(f.base_retention) OVER w prev_ret, lag(f.space20) OVER w prev_space,
           lag(f.p50, 2) OVER w prev2_p50,
           lag(try_cast(json_extract_string(f.peaks_json, '$[0].center_price') AS DOUBLE)) OVER w prev_peak,
           lag(try_cast(json_extract_string(f.peaks_json, '$[0].prominence') AS DOUBLE)) OVER w prev_prom,
           lag(try_cast(json_extract_string(f.peaks_json, '$[0].prominence') AS DOUBLE), 2) OVER w prev2_prom
    FROM read_parquet('{DAILY}', union_by_name=true) d
    JOIN read_parquet('{FEATURES}', union_by_name=true) f USING (symbol, trade_date)
    WHERE d.hard_valid AND f.strict_sample AND f.chip_input_valid
      AND f.daily_hard_valid AND f.minute_hard_valid
      AND f.daily_snapshot_id=d.snapshot_id
    WINDOW w AS (PARTITION BY d.symbol ORDER BY d.trade_date);
    CREATE OR REPLACE TEMP TABLE e AS
    SELECT param_id, symbol, signal_date, entry_date, entry_open, signal, sample_group
    FROM read_csv_auto('{ENTRIES}', header=true)
    WHERE param_id=231 AND sample_group='PROBE_2020_2023';
    COPY (
      WITH v AS (SELECT * FROM (VALUES {values}) AS x(variant_id, stop_pct, confirm_days, priority, mode)),
      paths AS (
        SELECT e.*, v.*, b.trade_date exit_date, b.close,
          CASE WHEN b.close <= e.entry_open*(1-v.stop_pct) THEN 1 ELSE 0 END stop_hit,
          CASE WHEN b.close < b.prev_p90 AND b.prev_close < b.prev2_p90
                    AND b.close < b.prev_close AND b.volume > median(b.volume) OVER wv
               THEN 1 ELSE 0 END s1_hit,
          CASE WHEN b.concentration_20 > b.prev_conc AND b.close < b.prev_close
                    AND b.peak1_prominence < b.prev_prom
                    AND b.prev_prom < b.prev2_prom
               THEN 1 ELSE 0 END s2_hit,
          CASE WHEN b.base_retention < b.prev_ret AND b.close < b.p50
                    AND b.prev_close < b.prev2_p50 AND b.peak1_center < b.prev_peak
               THEN 1 ELSE 0 END s3_hit,
          CASE WHEN b.space20 < b.prev_space AND b.close < b.p50
                    AND b.close < b.peak1_center
               THEN 1 ELSE 0 END s6_hit,
          CASE WHEN b.peak_count >= 2 AND b.close < b.p50 AND b.prev_close >= b.prev_p50
               THEN 1 ELSE 0 END s4_hit,
          CASE WHEN b.close < b.p10 AND b.prev_close >= b.prev_p10
                    AND b.volume > median(b.volume) OVER wv AND b.close < b.open
               THEN 1 ELSE 0 END s5_hit
        FROM e CROSS JOIN v JOIN b ON b.symbol=e.symbol
          AND b.trade_date>CAST(e.entry_date AS DATE)
          AND b.trade_date<=CAST(e.entry_date AS DATE)+INTERVAL 60 DAY
        WINDOW wv AS (PARTITION BY e.symbol,e.signal_date,e.signal,v.variant_id ORDER BY b.trade_date
                      ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)
      ), lagged AS (
        SELECT paths.*,
          lag(s1_hit, 1) OVER wx s1_prev1, lag(s1_hit, 2) OVER wx s1_prev2,
          lag(s2_hit, 1) OVER wx s2_prev1, lag(s2_hit, 2) OVER wx s2_prev2,
          lag(s3_hit, 1) OVER wx s3_prev1, lag(s3_hit, 2) OVER wx s3_prev2,
          lag(s4_hit, 1) OVER wx s4_prev1, lag(s4_hit, 2) OVER wx s4_prev2,
          lag(s5_hit, 1) OVER wx s5_prev1, lag(s5_hit, 2) OVER wx s5_prev2,
          lag(s6_hit, 1) OVER wx s6_prev1, lag(s6_hit, 2) OVER wx s6_prev2
        FROM paths
        WINDOW wx AS (PARTITION BY symbol,signal_date,signal,variant_id ORDER BY exit_date)
      ), marked AS (
        SELECT *, CASE
          WHEN priority='STOP_FIRST' AND stop_hit=1 THEN 'STOP'
          WHEN mode='ALL' AND priority='STRUCT_FIRST' AND
            (confirm_days=0 AND s5_hit=1 OR confirm_days=1 AND s5_hit+s5_prev1=2 OR confirm_days=2 AND s5_hit+s5_prev1+s5_prev2=3)
            THEN 'S5_GAP_MAIN_PEAK'
          WHEN mode='S1S2_GRACE' AND s5_hit=1 THEN 'S5_GAP_MAIN_PEAK'
          WHEN mode='S1S2_GRACE' AND stop_hit=1 THEN 'STOP'
          WHEN mode='S1S2_GRACE' AND s1_hit+s1_prev1+s1_prev2=3
            THEN 'S1_STRUCT'
          WHEN mode='S1S2_GRACE' AND s2_hit+s2_prev1+s2_prev2=3
            THEN 'S2_CONC'
          WHEN priority='STRUCT_FIRST' AND
            (confirm_days=0 AND s1_hit=1 OR confirm_days=1 AND s1_hit+s1_prev1=2 OR confirm_days=2 AND s1_hit+s1_prev1+s1_prev2=3)
            THEN 'S1_STRUCT'
          WHEN mode='ALL' AND (confirm_days=0 AND s2_hit=1 OR confirm_days=1 AND s2_hit+s2_prev1=2 OR confirm_days=2 AND s2_hit+s2_prev1+s2_prev2=3)
            THEN 'S2_CONC'
          WHEN mode='S1S2_GRACE' AND s3_hit=1 THEN 'S3_RETENTION'
          WHEN mode='ALL' AND (confirm_days=0 AND s3_hit=1 OR confirm_days=1 AND s3_hit+s3_prev1=2 OR confirm_days=2 AND s3_hit+s3_prev1+s3_prev2=3)
            THEN 'S3_RETENTION'
          WHEN mode='S1S2_GRACE' AND s6_hit=1 THEN 'S6_SPACE'
          WHEN mode='ALL' AND (confirm_days=0 AND s6_hit=1 OR confirm_days=1 AND s6_hit+s6_prev1=2 OR confirm_days=2 AND s6_hit+s6_prev1+s6_prev2=3)
            THEN 'S6_SPACE'
          WHEN mode='S1S2_GRACE' AND s4_hit=1 THEN 'S4_DOUBLE_PEAK_FAILURE'
          WHEN mode='ALL' AND (confirm_days=0 AND s4_hit=1 OR confirm_days=1 AND s4_hit+s4_prev1=2 OR confirm_days=2 AND s4_hit+s4_prev1+s4_prev2=3)
            THEN 'S4_DOUBLE_PEAK_FAILURE'
          WHEN mode='ALL' AND (confirm_days=0 AND s5_hit=1 OR confirm_days=1 AND s5_hit+s5_prev1=2 OR confirm_days=2 AND s5_hit+s5_prev1+s5_prev2=3)
            THEN 'S5_GAP_MAIN_PEAK'
          WHEN mode='ALL' AND (confirm_days=0 AND s1_hit=1 OR confirm_days=1 AND s1_hit+s1_prev1=2 OR confirm_days=2 AND s1_hit+s1_prev1+s1_prev2=3)
            THEN 'S1_STRUCT'
          WHEN stop_hit=1 THEN 'STOP'
          WHEN exit_date>=CAST(entry_date AS DATE)+INTERVAL 60 DAY THEN 'TIME60'
        END exit_reason
        FROM lagged
      ), first_exit AS (
        SELECT * FROM marked WHERE exit_reason IS NOT NULL QUALIFY
          row_number() OVER (PARTITION BY variant_id,symbol,signal_date,signal ORDER BY exit_date)=1
      )
      SELECT variant_id, stop_pct, confirm_days, priority, mode, signal, count(*) n,
             avg((b.close/e.entry_open)*(1-0.001)*(1-0.0003)*(1-0.0003-0.0005)-1) mean_net_return,
             median((b.close/e.entry_open)*(1-0.001)*(1-0.0003)*(1-0.0003-0.0005)-1) median_net_return,
             avg(CASE WHEN b.close>e.entry_open THEN 1 ELSE 0 END) win_rate
      FROM first_exit b JOIN e USING (symbol,signal_date,signal)
      GROUP BY ALL ORDER BY variant_id, signal
    ) TO '{OUT}' (HEADER, DELIMITER ',');
    """
    con.execute(query)
    print(OUT)


if __name__ == "__main__":
    main()
