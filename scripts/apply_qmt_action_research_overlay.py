#!/usr/bin/env python3
"""Attach QMT corporate-action corroboration without changing strict validity."""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--daily", required=True)
    p.add_argument("--supplement", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    def esc(value: object) -> str:
        return str(value).replace("'", "''")
    target = esc((a.output / "data.parquet").resolve())
    con = duckdb.connect()
    try:
        con.execute("PRAGMA threads=10")
        con.execute(f"""
          COPY (
            WITH s AS (
              SELECT symbol, CAST(effective_date AS DATE) AS trade_date,
                     CAST(capital_factor_matches_action AS BOOLEAN) AS qmt_action_factor_match,
                     CAST(qmt_execution_date_confirmed AS BOOLEAN) AS qmt_action_execution_confirmed,
                     CAST(research_resolvable AS BOOLEAN) AS qmt_action_research_resolvable,
                     available_at AS qmt_action_available_at,
                     snapshot_id AS qmt_action_snapshot_id
              FROM read_csv_auto('{esc(a.supplement)}', union_by_name=true)
            ), base AS (SELECT * FROM read_parquet('{esc(a.daily)}', union_by_name=true))
            SELECT base.*,
              COALESCE(s.qmt_action_factor_match, FALSE) AS qmt_action_factor_match,
              COALESCE(s.qmt_action_execution_confirmed, FALSE) AS qmt_action_execution_confirmed,
              COALESCE(s.qmt_action_research_resolvable, FALSE) AS qmt_action_research_resolvable,
              s.qmt_action_available_at, s.qmt_action_snapshot_id,
              CASE WHEN s.qmt_action_research_resolvable THEN TRUE ELSE FALSE END
                AS research_corporate_action_resolved
            FROM base LEFT JOIN s USING (symbol, trade_date)
            WHERE trade_date BETWEEN DATE '{esc(a.start)}' AND DATE '{esc(a.end)}'
          ) TO '{target}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)
    finally:
        con.close()
    print(target)


if __name__ == "__main__":
    main()
