"""Rule-isolated counterfactual exits using the independent candidate table."""
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "data/audit/chapter8_9_independent_exit_candidates_v01.csv"
OUT = ROOT / "data/audit/chapter8_9_exit_counterfactual_v01.csv"


def main() -> None:
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    query = f"""
    COPY (
      WITH c AS (
        SELECT *,
          CASE candidate_exit_reason
            WHEN 'S1_STRUCT' THEN 'S1'
            WHEN 'S2_CONC' THEN 'S2'
            WHEN 'S3_RETENTION' THEN 'S3'
            WHEN 'S4_DOUBLE_PEAK_FAILURE' THEN 'S4'
            WHEN 'S5_GAP_MAIN_PEAK' THEN 'S5'
            WHEN 'S6_SPACE' THEN 'S6'
            WHEN 'STOP' THEN 'STOP'
            WHEN 'TIME60' THEN 'TIME60'
          END exit_rule
        FROM read_csv_auto('{CANDIDATES}')
      ), first_rule AS (
        SELECT * EXCLUDE(rn) FROM (
          SELECT c.*, row_number() OVER (
            PARTITION BY param_id, symbol, signal_date, signal, exit_rule
            ORDER BY exit_candidate_date
          ) rn
          FROM c
        ) WHERE rn=1
      ), rules AS (
        SELECT DISTINCT exit_rule FROM c
        WHERE exit_rule IN ('S1','S2','S3','S4','S5','S6')
      ), selected AS (
        SELECT r.exit_rule AS isolated_rule, f.*
        FROM rules r
        JOIN first_rule f ON f.exit_rule IN (r.exit_rule, 'STOP', 'TIME60')
        QUALIFY row_number() OVER (
          PARTITION BY r.exit_rule, f.param_id, f.symbol, f.signal_date, f.signal
          ORDER BY f.exit_candidate_date
        )=1
      ), result AS (
        SELECT *,
          exit_candidate_close/entry_open-1.0 gross_return,
          (exit_candidate_close/entry_open)*(1-0.001)*(1-0.0003)*(1-0.0003-0.0005)-1.0 net_return,
          exit_candidate_date>=signal_date+INTERVAL 1 DAY AS next_day_or_later,
          exit_candidate_date=selected_exit_date selected_by_current_priority
        FROM selected
      )
      SELECT * FROM result
    ) TO '{OUT}' (HEADER, DELIMITER ',');
    """
    con.execute(query)
    print(OUT)
    print(con.execute(f"""
      SELECT isolated_rule, count(*) n,
             avg(net_return) mean_net, median(net_return) median_net,
             avg(CAST(net_return>0 AS INTEGER)) win_rate,
             avg(CAST(selected_by_current_priority AS INTEGER)) current_same_rate
      FROM read_csv_auto('{OUT}')
      GROUP BY ALL ORDER BY isolated_rule
    """).fetchdf().to_string(index=False))


if __name__ == '__main__':
    main()
