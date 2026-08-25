"""Measure whether targeted minute rows add keys or strict coverage."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    con = duckdb.connect()
    b = args.base.replace("'", "''")
    t = args.target.replace("'", "''")
    q = f"""
    WITH base AS (SELECT symbol, trade_date, hard_valid FROM read_parquet('{b}', union_by_name=true)),
         target AS (SELECT symbol, trade_date, hard_valid FROM read_parquet('{t}', union_by_name=true)),
         overlap AS (
           SELECT base.hard_valid AS base_valid, target.hard_valid AS target_valid
           FROM base JOIN target USING (symbol, trade_date)
         )
    SELECT base_valid, target_valid, count(*) AS rows FROM overlap
    GROUP BY 1, 2 ORDER BY 1, 2
    """
    cursor = con.execute(q)
    columns = [d[0] for d in cursor.description]
    matrix = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    result = {
        "base": args.base,
        "target": args.target,
        "target_rows": con.execute(
            f"SELECT count(*) FROM read_parquet('{t}', union_by_name=true)"
        ).fetchone()[0],
        "overlap_rows": con.execute(
            f"SELECT count(*) FROM (SELECT symbol, trade_date FROM read_parquet('{t}', union_by_name=true) INTERSECT SELECT symbol, trade_date FROM read_parquet('{b}', union_by_name=true))"
        ).fetchone()[0],
        "new_key_rows": con.execute(
            f"SELECT count(*) FROM (SELECT symbol, trade_date FROM read_parquet('{t}', union_by_name=true) EXCEPT SELECT symbol, trade_date FROM read_parquet('{b}', union_by_name=true))"
        ).fetchone()[0],
        "validity_matrix": matrix,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
