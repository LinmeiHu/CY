#!/usr/bin/env python3
"""Audit historical corporate-action source coverage without activating it.

Coverage is evidence only: an action row is not research-usable unless its
point-in-time visibility and complete revision lineage are available.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--actions", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    con = duckdb.connect()
    columns = [row[0] for row in con.execute(
        "describe select * from read_parquet(?)", [args.actions]
    ).fetchall()]
    annual = [
        {"year": int(row[0]), "rows": int(row[1]),
         "revision_history_complete_rows": int(row[2]),
         "known_at_rows": int(row[3]), "updated_at_rows": int(row[4])}
        for row in con.execute(
            """select year(coalesce(effective_date, record_date, announcement_date)),
                      count(*),
                      count(*) filter (where coalesce(revision_history_complete, false)),
                      count(*) filter (where known_at is not null),
                      count(*) filter (where source_updated_at is not null)
               from read_parquet(?)
              where coalesce(effective_date, record_date, announcement_date)
                    between ?::DATE and ?::DATE
              group by 1 order by 1""",
            [args.actions, args.start, args.end],
        ).fetchall()
    ]
    required = {"known_at", "revision_id", "revision_history_complete"}
    missing = sorted(required - set(columns))
    report = {
        "audit": "HISTORICAL_ACTION_SOURCE_COVERAGE",
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": {"start": args.start, "end": args.end},
        "source": args.actions,
        "columns": sorted(columns),
        "annual": annual,
        "gate": {
            "research_ready": bool(annual) and not missing and all(
                row["revision_history_complete_rows"] == row["rows"]
                and row["known_at_rows"] == row["rows"] for row in annual
            ),
            "missing_required_columns": missing,
            "failure_reasons": ([f"missing required field: {field}" for field in missing]
                                + (["historical revision history is incomplete"]
                                   if any(row["revision_history_complete_rows"] < row["rows"]
                                          for row in annual) else [])
                                + (["historical source lacks known_at coverage"]
                                   if any(row["known_at_rows"] < row["rows"] for row in annual)
                                   else [])),
            "activation_policy": "coverage is diagnostic; incomplete PIT revision lineage fails closed",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
