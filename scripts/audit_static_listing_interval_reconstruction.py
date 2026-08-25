#!/usr/bin/env python3
"""Audit a static listing/delisting interval as a non-PIT cross-check.

The result is deliberately diagnostic: a current listing-date snapshot cannot
authorize a historical security universe without vintage and availability
lineage.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listing-csv", type=Path, required=True)
    parser.add_argument("--bars", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    con = duckdb.connect()
    con.execute("CREATE OR REPLACE TABLE listings AS SELECT * FROM read_csv_auto(?)", [str(args.listing_csv)])
    con.execute("CREATE OR REPLACE TABLE bars AS SELECT * FROM read_parquet(?)", [[str(p) for p in args.bars]])
    cols = [r[0] for r in con.execute("DESCRIBE bars").fetchall()]
    symbol = next(c for c in ("symbol", "code", "ts_code") if c in cols)
    date_col = next(c for c in ("trade_date", "datetime", "date", "timestamp") if c in cols)
    # The identifiers above are column names, not values; reconstruct safely.
    con.execute(f"CREATE OR REPLACE TABLE b AS SELECT CAST(\"{symbol}\" AS VARCHAR) AS _symbol, CAST(\"{date_col}\" AS DATE) AS _date FROM bars")
    result = con.execute(
        """
        WITH x AS (
          SELECT EXTRACT(YEAR FROM _date)::INTEGER AS year, COUNT(*) AS symbol_days,
                 SUM(CASE WHEN l.symbol IS NOT NULL THEN 1 ELSE 0 END) AS interval_ok
          FROM b
          LEFT JOIN listings l
            ON LPAD(CAST(l.symbol AS VARCHAR), 6, '0') = LPAD(b._symbol, 6, '0')
           AND TRY_CAST(l.list_date AS DATE) <= b._date
           AND (l.delist_date IS NULL OR TRY_CAST(l.delist_date AS DATE) >= b._date)
          WHERE _date BETWEEN DATE '2010-01-01' AND DATE '2017-12-31'
          GROUP BY 1 ORDER BY 1
        ) SELECT year, symbol_days, interval_ok,
                 symbol_days - interval_ok AS interval_missing,
                 interval_ok::DOUBLE / NULLIF(symbol_days, 0) AS interval_coverage
        FROM x
        """
    ).fetchdf()
    report = {
        "listing_source": str(args.listing_csv),
        "bar_sources": [str(p) for p in args.bars],
        "status": "DIAGNOSTIC_ONLY",
        "research_ready": False,
        "reason": [
            "listing/delisting file is a current snapshot without historical source revision",
            "records lack authorized available_at and snapshot_id lineage",
            "static intervals do not prove the exchange's date-effective universe or trading status",
        ],
        "annual": result.to_dict(orient="records"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")


if __name__ == "__main__":
    main()
