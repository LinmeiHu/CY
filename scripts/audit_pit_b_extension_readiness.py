#!/usr/bin/env python3
"""Read-only readiness audit for extending PIT-B research before 2018."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import duckdb

YEARS = range(2010, 2018)


def parquet_count(con: duckdb.DuckDBPyConnection, path: Path) -> dict[str, object]:
    try:
        rows = con.execute("select count(*) from read_parquet(?)", [str(path)]).fetchone()
        return {"path": str(path), "readable_by_duckdb": True, "rows": int(rows[0]) if rows else None}
    except Exception as exc:  # fail closed; this is an audit, not a repair
        return {"path": str(path), "readable_by_duckdb": False, "error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lake", type=Path, default=Path("/Users/linmei/Downloads/workspace/quant/data/lake"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    canonical = args.lake / "stock_1min_canonical_none_20260813"
    coverage_path = canonical / "daily_coverage.csv"
    coverage: list[dict[str, object]] = []
    if coverage_path.exists():
        import csv

        with coverage_path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                if int(row["trade_date"][:4]) in YEARS:
                    coverage.append(row)

    con = duckdb.connect()
    meta = args.lake / "meta"
    readable = [
        parquet_count(con, meta / "industry_events.parquet"),
        parquet_count(con, meta / "qmt_capital.parquet"),
    ]
    report = {
        "audit": "PIT_B_EXTENSION_READINESS",
        "generated_at": date.today().isoformat(),
        "requested_years": [f"{year}-01-01/{year}-12-31" for year in YEARS],
        "minute_coverage": coverage,
        "required_assets": {
            "daily_bars": str(args.lake / "stock_daily"),
            "trading_state": str(args.lake / "stock_state_daily"),
            "index_daily": str(args.lake / "index_daily"),
            "security_master_pit": "BLOCKED: QD-007 is not materialized or activated",
            "industry_events": readable[0],
            "qmt_capital": readable[1],
        },
        "gate": {
            "research_eligible": False,
            "reasons": [
                "historical security universe is not an immutable date-effective PIT asset",
                "industry/capital parquet requires independent footer/schema and row-level audit before activation",
                "no 2010-2017 input snapshot or registry authorization exists",
            ],
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
