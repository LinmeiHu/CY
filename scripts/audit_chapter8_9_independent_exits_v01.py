"""Independent S1-S6 candidate-exit audit for strict v2 entry events.

This deliberately does not use the selected exit_reason from the state-machine
output.  It rescans every post-entry bar and retains every individual exit flag,
so early shake-outs and competing exit rules remain observable.
"""
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ROOT / "data/processed/chip_state_features_by_year_2018_2026_v2/year=*/data.parquet"
DAILY = ROOT / "data/processed/pit_b_daily_2018_2026_v2/daily/partition_year=*/data_0.parquet"
TRADES = ROOT / "data/audit/chapter8_9_state_machine_v01.csv"
OUT = ROOT / "data/audit/chapter8_9_independent_exit_candidates_v01.csv"


def main() -> None:
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    con.execute("PRAGMA enable_progress_bar=false")
    query = f"""
    COPY (
      WITH e AS (
        SELECT DISTINCT param_id, symbol, signal_date, entry_date, entry_open,
               signal, exit_date AS selected_exit_date, exit_reason AS selected_exit_reason
        FROM read_csv_auto('{TRADES}')
        WHERE sample_group='PROBE_2020_2023'
      ), x AS (
        SELECT d.symbol, d.trade_date, d.open, d.close, d.volume, d.hard_valid,
               d.buy_blocked_open, d.market_close,
               f.p10, f.p50, f.p90, f.average_cost, f.space20,
               f.concentration_20, f.base_retention, f.peak_count,
               try_cast(json_extract_string(f.peaks_json, '$[0].center_price') AS DOUBLE) peak1_center,
               try_cast(json_extract_string(f.peaks_json, '$[0].prominence') AS DOUBLE) peak1_prominence,
               lag(d.close) OVER w prev_close, lag(f.p10) OVER w prev_p10,
               lag(f.p90) OVER w prev_p90, lag(f.p90, 2) OVER w prev2_p90,
               lag(f.p50) OVER w prev_p50, lag(f.p50, 2) OVER w prev2_p50,
               lag(f.concentration_20) OVER w prev_conc,
               lag(f.base_retention) OVER w prev_ret,
               lag(f.average_cost) OVER w prev_avg,
               lag(f.space20) OVER w prev_space,
               lag(try_cast(json_extract_string(f.peaks_json, '$[0].center_price') AS DOUBLE)) OVER w prev_peak,
               lag(try_cast(json_extract_string(f.peaks_json, '$[0].prominence') AS DOUBLE)) OVER w prev_prom,
               lag(try_cast(json_extract_string(f.peaks_json, '$[0].prominence') AS DOUBLE), 2) OVER w prev2_prom,
               lead(d.close, 5) OVER w fwd5_close,
               lead(d.close, 10) OVER w fwd10_close,
               lead(d.close, 20) OVER w fwd20_close,
               median(d.volume) OVER (PARTITION BY d.symbol ORDER BY d.trade_date
                 ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) vmed20
        FROM read_parquet('{DAILY}', union_by_name=true) d
        JOIN read_parquet('{FEATURES}', union_by_name=true) f USING (symbol, trade_date)
        WHERE d.trade_date BETWEEN DATE '2019-01-02' AND DATE '2026-08-12'
          AND d.hard_valid AND f.strict_sample AND f.chip_input_valid
          AND f.daily_hard_valid AND f.minute_hard_valid
          AND f.daily_snapshot_id=d.snapshot_id
          AND NOT regexp_matches(d.symbol, '^(688|689)')
        WINDOW w AS (PARTITION BY d.symbol ORDER BY d.trade_date)
      ), flags AS (
        SELECT e.*, x.trade_date exit_candidate_date, x.close exit_candidate_close,
          x.close/e.entry_open-1.0 gross_return_at_candidate,
          x.fwd5_close/x.close-1.0 forward5_return,
          x.fwd10_close/x.close-1.0 forward10_return,
          x.fwd20_close/x.close-1.0 forward20_return,
          x.close <= e.entry_open*0.92 stop_hit,
          x.close < x.p10 AND x.prev_close >= x.prev_p10
            AND x.volume > x.vmed20 AND x.close < x.open s5_hit,
          x.close < x.prev_p90 AND x.prev_close < x.prev2_p90
            AND x.close < x.prev_close AND x.volume > x.vmed20 s1_hit,
          x.concentration_20 > x.prev_conc AND x.close < x.prev_close
            AND x.peak1_prominence < x.prev_prom
            AND x.prev_prom < x.prev2_prom s2_hit,
          x.base_retention < x.prev_ret AND x.close < x.p50
            AND x.prev_close < x.prev2_p50 AND x.peak1_center < x.prev_peak s3_hit,
          x.space20 < x.prev_space AND x.close < x.prev_avg
            AND x.close < x.peak1_center s6_hit,
          x.peak_count >= 2 AND x.close < x.p50
            AND x.prev_close >= x.prev_p50 s4_hit,
          x.trade_date >= e.entry_date + INTERVAL 60 DAY time60_hit
        FROM e JOIN x ON x.symbol=e.symbol
          AND x.trade_date>e.entry_date
          AND x.trade_date<=e.entry_date+INTERVAL 60 DAY
      ), candidates AS (
        SELECT *, unnest(list_filter([
          CASE WHEN stop_hit THEN 'STOP' END,
          CASE WHEN s1_hit THEN 'S1_STRUCT' END,
          CASE WHEN s2_hit THEN 'S2_CONC' END,
          CASE WHEN s3_hit THEN 'S3_RETENTION' END,
          CASE WHEN s4_hit THEN 'S4_DOUBLE_PEAK_FAILURE' END,
          CASE WHEN s5_hit THEN 'S5_GAP_MAIN_PEAK' END,
          CASE WHEN s6_hit THEN 'S6_SPACE' END,
          CASE WHEN time60_hit THEN 'TIME60' END
        ], x -> x IS NOT NULL)) candidate_exit_reason
        FROM flags
      )
      SELECT *,
        exit_candidate_date=selected_exit_date selected_by_current_priority,
        exit_candidate_date<selected_exit_date candidate_precedes_selected,
        CASE WHEN candidate_exit_reason LIKE 'S%' THEN candidate_exit_reason ELSE NULL END sell_rule
      FROM candidates
      WHERE exit_candidate_date BETWEEN DATE '2020-01-02' AND DATE '2023-12-29'
    ) TO '{OUT}' (HEADER, DELIMITER ',');
    """
    con.execute(query)
    print(OUT)
    print(con.execute(f"""
      SELECT candidate_exit_reason, count(*) n,
             avg(gross_return_at_candidate) mean_return,
             median(gross_return_at_candidate) median_return,
             avg(forward5_return) forward5_mean,
             avg(forward10_return) forward10_mean,
             avg(forward20_return) forward20_mean,
             avg(CAST(forward5_return > 0 AS INTEGER)) forward5_positive,
             avg(CAST(candidate_precedes_selected AS INTEGER)) precedes_rate
      FROM read_csv_auto('{OUT}') GROUP BY ALL
      ORDER BY candidate_exit_reason
    """).fetchdf().to_string(index=False))


if __name__ == '__main__':
    main()
