"""Create a small research-only daily overlay from an observed status cross-check."""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--daily", required=True)
    p.add_argument("--crosscheck", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    daily = a.daily.replace("'", "''")
    cross = a.crosscheck.replace("'", "''")
    target = str((a.output / "data.parquet").resolve()).replace("'", "''")
    con = duckdb.connect()
    try:
        con.execute("PRAGMA threads=10")
        con.execute(f"""
          COPY (
            WITH c AS (
              SELECT symbol, CAST(date AS DATE) AS trade_date,
                     CAST(isST AS INTEGER) = 1 AS observed_is_st,
                     CAST(tradestatus AS INTEGER) AS observed_trade_status,
                     snapshot_id AS observed_snapshot_id
              FROM read_csv_auto('{cross}', union_by_name=true)
            ), base AS (SELECT * FROM read_parquet('{daily}', union_by_name=true))
            SELECT * REPLACE(
              CASE WHEN c.symbol IS NOT NULL AND c.observed_trade_status = 0
                        AND open IS NOT NULL AND high IS NOT NULL AND low IS NOT NULL
                        AND close IS NOT NULL AND preclose IS NOT NULL
                        AND open >= 0 AND high >= 0 AND low >= 0 AND close >= 0 AND preclose >= 0
                   THEN TRUE ELSE bar_valid END AS bar_valid,
              CASE WHEN c.symbol IS NOT NULL THEN c.observed_is_st ELSE is_st END AS is_st,
              CASE WHEN c.symbol IS NOT NULL THEN c.observed_trade_status ELSE trade_status END AS trade_status,
              CASE WHEN c.symbol IS NOT NULL THEN TRUE ELSE trading_state_valid END AS trading_state_valid,
              CASE WHEN c.symbol IS NOT NULL THEN 'baostock_crosscheck' ELSE state_source END AS state_source,
              CASE WHEN c.symbol IS NOT NULL THEN c.observed_snapshot_id ELSE trading_state_snapshot_id END AS trading_state_snapshot_id,
              CASE WHEN c.symbol IS NOT NULL THEN (
                (CASE WHEN c.observed_trade_status = 0
                            AND open IS NOT NULL AND high IS NOT NULL AND low IS NOT NULL
                            AND close IS NOT NULL AND preclose IS NOT NULL
                            AND open >= 0 AND high >= 0 AND low >= 0 AND close >= 0 AND preclose >= 0
                       THEN TRUE ELSE bar_valid END)
                AND industry_valid AND float_valid AND corporate_action_valid
                AND market_valid AND market_rule_valid AND historical_identity_valid
              ) ELSE hard_valid END AS hard_valid,
              CASE WHEN c.symbol IS NOT NULL AND c.observed_trade_status = 0
                   THEN regexp_replace(invalid_reasons, '(^|\\|)invalid_daily_bar(\\||$)', '\\1')
                   WHEN c.symbol IS NOT NULL
                   THEN regexp_replace(regexp_replace(invalid_reasons, '(^|\\|)invalid_or_unverified_trading_state(\\||$)', '\\1'), '(^|\\|)historical_st_status_unverified(\\||$)', '\\1')
                   ELSE invalid_reasons END AS invalid_reasons
            )
            FROM base LEFT JOIN c USING (symbol, trade_date)
            WHERE trade_date BETWEEN DATE '{a.start}' AND DATE '{a.end}'
          ) TO '{target}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)
    finally:
        con.close()
    print(target)


if __name__ == "__main__":
    main()
