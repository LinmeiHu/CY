#!/usr/bin/env python3
"""Materialize an explicit, fail-closed PIT bridge for 2010--2017 inputs.

This is a deterministic adapter, not a historical-vintage reconstruction.  It
adds the common lineage contract to source rows and preserves source limitations
as hard_valid=false.  The output is not activated by this script; registration
and the annual gate remain separate steps.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

import duckdb


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_parquet(con: duckdb.DuckDBPyConnection, query: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    target = str(output).replace("'", "''")
    con.execute("COPY (" + query + f") TO '{target}' (FORMAT PARQUET, COMPRESSION ZSTD)")


def sql_path(path: str | Path) -> str:
    return str(path).replace("'", "''")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--industry", type=Path, required=True)
    parser.add_argument("--capital", type=Path, required=True)
    parser.add_argument("--actions", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--allow-late-announcement", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--asset-id", default="CYQ-PIT-B-HISTORICAL-BRIDGE-2010-2017")
    args = parser.parse_args()

    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    start = args.start
    end = args.end
    capital_available_expr = (
        "GREATEST(strptime(CAST(m_timetag AS VARCHAR), '%Y%m%d'), "
        "strptime(CAST(m_anntime AS VARCHAR), '%Y%m%d'))"
        if args.allow_late_announcement
        else "strptime(CAST(m_anntime AS VARCHAR), '%Y%m%d')"
    )
    capital_valid_expr = (
        "m_timetag > 0 AND m_anntime > 0 AND circulating_capital > 0"
        if args.allow_late_announcement
        else "m_timetag > 0 AND m_anntime > 0 AND circulating_capital > 0 AND m_anntime <= m_timetag"
    )
    capital_invalid_expr = (
        "CASE WHEN m_timetag <= 0 OR m_anntime <= 0 THEN 'MISSING_EFFECTIVE_OR_ANNOUNCEMENT' "
        "WHEN circulating_capital <= 0 THEN 'NONPOSITIVE_CIRCULATING_CAPITAL' ELSE NULL END"
        if args.allow_late_announcement
        else "CASE WHEN m_timetag <= 0 OR m_anntime <= 0 THEN 'MISSING_EFFECTIVE_OR_ANNOUNCEMENT' "
        "WHEN circulating_capital <= 0 THEN 'NONPOSITIVE_CIRCULATING_CAPITAL' "
        "WHEN m_anntime > m_timetag THEN 'ANNOUNCEMENT_AFTER_EFFECTIVE' ELSE NULL END"
    )

    copy_parquet(
        con,
        f"""
        SELECT *,
          CAST(notice_date AS TIMESTAMP) + INTERVAL 15 HOUR AS available_at,
          'QD-008-HISTORICAL-SOURCE-' || '{start}_{end}' AS snapshot_id,
          'industry-event:' || md5(concat_ws('|', CAST(symbol AS VARCHAR), CAST(report_date AS VARCHAR), CAST(notice_date AS VARCHAR), CAST(industry AS VARCHAR))) AS revision_id,
          CAST(notice_date IS NOT NULL AND report_date IS NOT NULL
               AND report_date <= notice_date AS BOOLEAN) AS hard_valid,
          CASE WHEN notice_date IS NULL THEN 'MISSING_NOTICE_DATE'
               WHEN report_date IS NULL THEN 'MISSING_REPORT_DATE'
               WHEN report_date > notice_date THEN 'REPORT_AFTER_NOTICE'
               ELSE NULL END AS invalid_reason
        FROM read_parquet('{sql_path(args.industry)}')
        WHERE CAST(notice_date AS DATE) <= DATE '{end}'
          AND (notice_date IS NULL OR CAST(notice_date AS DATE) >= DATE '{start}')
        """,
        out / "industry_events_pit.parquet",
    )
    copy_parquet(
        con,
        f"""
        SELECT *,
          {capital_available_expr} + INTERVAL 15 HOUR AS available_at,
          strptime(CAST(m_timetag AS VARCHAR), '%Y%m%d') + INTERVAL 15 HOUR AS source_effective_at,
          'QD-009-HISTORICAL-SOURCE-' || '{start}_{end}' AS snapshot_id,
          'capital:' || qmt_code || ':' || CAST(m_timetag AS VARCHAR) || ':' ||
            CAST(m_anntime AS VARCHAR) AS revision_id,
          CAST({capital_valid_expr} AS BOOLEAN) AS hard_valid,
          {capital_invalid_expr} AS invalid_reason
        FROM read_parquet('{sql_path(args.capital)}')
        WHERE m_timetag BETWEEN CAST(replace('{start}', '-', '') AS BIGINT)
                            AND CAST(replace('{end}', '-', '') AS BIGINT)
        """,
        out / "qmt_capital_pit.parquet",
    )
    copy_parquet(
        con,
        f"""
        SELECT *,
          COALESCE(known_at, announcement_date) AS available_at,
          'QD-010-HISTORICAL-CURRENT-SNAPSHOT-' || '{start}_{end}' AS snapshot_id,
          CAST(revision_id AS VARCHAR) AS normalized_revision_id,
          CAST(COALESCE(known_at, announcement_date) IS NOT NULL
               AND effective_date IS NOT NULL AS BOOLEAN) AS hard_valid,
          CASE WHEN COALESCE(known_at, announcement_date) IS NULL THEN 'MISSING_KNOWN_AT'
               WHEN effective_date IS NULL THEN 'MISSING_EFFECTIVE_DATE'
               ELSE NULL END AS invalid_reason
        FROM read_parquet('{sql_path(args.actions)}')
        WHERE effective_date >= DATE '{start}' AND effective_date <= DATE '{end}'
        """,
        out / "corporate_actions_pit.parquet",
    )

    files = sorted(out.glob("*.parquet"))
    manifest = {
        "asset_id": args.asset_id,
        "generated_at": date.today().isoformat(),
        "source_range": {"start": start, "end": end},
        "adapter": "materialize_historical_pit_bridge.py",
        "research_activation": "NOT_ACTIVATED",
        "capital_availability_policy": (
            "available_at=max(source_effective_at, announcement_at)"
            if args.allow_late_announcement
            else "available_at=announcement_at; late announcements are hard_invalid"
        ),
        "policy": "PIT-B uses known/announcement and effective timing; revision completeness remains a strict-PIT diagnostic",
        "files": [{"path": str(p), "sha256": sha256(p), "bytes": p.stat().st_size} for p in files],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
