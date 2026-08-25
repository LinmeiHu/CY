#!/usr/bin/env python3
"""Audit the fail-closed PIT bridge for the 2010-2017 extension.

This is deliberately an audit, not a materializer.  It evaluates the row-level
selection rules we will use once authorized vintages exist, while refusing to
turn diagnostic coverage into research eligibility.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb

REQUIRED_LINEAGE = ("available_at", "snapshot_id", "revision_id")


def schema(con: duckdb.DuckDBPyConnection, path: str) -> set[str]:
    rows = con.execute("describe select * from read_parquet(?)", [path]).fetchall()
    return {str(row[0]) for row in rows}


def asset_result(
    con: duckdb.DuckDBPyConnection,
    name: str,
    path: str,
    scope_sql: str,
    scope_params: list[str],
    rules: list[str],
) -> dict[str, object]:
    try:
        columns = schema(con, path)
        count = int(con.execute(scope_sql, [path, *scope_params]).fetchone()[0])
        missing = [field for field in REQUIRED_LINEAGE if field not in columns]
        hard_invalid = 0
        invalid_reasons: list[dict[str, object]] = []
        if "hard_valid" in columns:
            hard_invalid = int(con.execute(
                "select count(*) from read_parquet(?) where not hard_valid", [path]
            ).fetchone()[0])
            invalid_reasons = [
                {"reason": str(row[0]), "rows": int(row[1])}
                for row in con.execute(
                    "select coalesce(invalid_reason, 'UNSPECIFIED') as reason, count(*) "
                    "from read_parquet(?) where not hard_valid group by 1 order by 2 desc",
                    [path],
                ).fetchall()
            ]
        revision_incomplete = 0
        if name == "QD-010-corporate-actions" and "revision_history_complete" in columns:
            revision_incomplete = int(con.execute(
                "select count(*) from read_parquet(?) "
                "where not coalesce(revision_history_complete, false)", [path]
            ).fetchone()[0])
        # PIT-B admits causally timed final facts.  Complete revision history is
        # required for strict archival PIT, not for this research tier.
        source_research_ready = not missing
        return {
            "asset": name,
            "path": path,
            "rows_in_scope": count,
            "columns": sorted(columns),
            "lineage_missing": missing,
            "hard_invalid_rows": hard_invalid,
            "invalid_reason_counts": invalid_reasons,
            "revision_history_incomplete_rows": revision_incomplete,
            "bridge_rules": rules,
            "hard_valid": not missing and hard_invalid == 0,
            "research_ready": source_research_ready,
            "failure_reasons": (
                [f"missing record-level lineage field: {field}" for field in missing]
                + ([] if not missing else ["source snapshot cannot be causally replayed"])
                + ([f"{hard_invalid} rows are explicitly hard_valid=false; they must be excluded"] if hard_invalid else [])
            ),
        }
    except Exception as exc:  # audit must fail closed
        return {
            "asset": name,
            "path": path,
            "rows_in_scope": None,
            "hard_valid": False,
            "research_ready": False,
            "failure_reasons": [f"unreadable or unqueryable source: {exc}"],
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--industry", required=True)
    parser.add_argument("--capital", required=True)
    parser.add_argument("--actions", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-late-announcement", action="store_true")
    args = parser.parse_args()

    con = duckdb.connect()
    # The SQL below documents the intended bridge: decisions may only see
    # already-announced/effective observations.  Missing lineage still blocks
    # the result even when these date predicates have excellent coverage.
    start, end = args.start, args.end
    industry = asset_result(
        con,
        "QD-008-industry",
        args.industry,
        "select count(*) from read_parquet(?) where notice_date >= ?::DATE and notice_date <= ?::DATE",
        [start, end],
        ["industry selected only when notice_date < decision_at", "unknown industry is hard_invalid"],
    )
    capital = asset_result(
        con,
        "QD-009-circulating-capital",
        args.capital,
        "select count(*) from read_parquet(?) where try_cast(m_timetag as BIGINT) between strftime(?::DATE, '%Y%m%d')::BIGINT and strftime(?::DATE, '%Y%m%d')::BIGINT",
        [start, end],
        (["available_at=max(source_effective_at, announcement_at)", "nonpositive or ambiguous float is hard_invalid"]
         if args.allow_late_announcement else
         ["select latest effective observation with announcement_at <= decision_at", "nonpositive or ambiguous float is hard_invalid"]),
    )
    actions = asset_result(
        con,
        "QD-010-corporate-actions",
        args.actions,
        "select count(*) from read_parquet(?) where coalesce(effective_date, record_date, announcement_date) >= ?::DATE and coalesce(effective_date, record_date, announcement_date) <= ?::DATE",
        [start, end],
        ["apply only after known_at/announcement timing is available", "unresolved execution timing is hard_invalid"],
    )
    assets = [industry, capital, actions]
    report = {
        "audit": "HISTORICAL_PIT_BRIDGE",
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": {"start": start, "end": end},
        "bridge_contract": {
            "decision_at_strict": True,
            "required_lineage": list(REQUIRED_LINEAGE),
            "missing_lineage_policy": "hard_invalid_and_block_new_risk",
            "diagnostic_coverage_is_not_activation": True,
            "capital_availability_policy": (
                "max(source_effective_at, announcement_at)"
                if args.allow_late_announcement else "announcement_at; late announcements invalid"
            ),
        },
        "assets": assets,
        "research_gate": bool(assets) and all(bool(asset.get("research_ready")) for asset in assets),
        "failure_reasons": [
            reason
            for asset in assets
            for reason in asset.get("failure_reasons", [])
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
