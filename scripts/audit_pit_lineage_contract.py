#!/usr/bin/env python3
"""Fail-closed audit of PIT lineage fields and frozen manifests.

This audit does not promote data.  It verifies whether the physical inputs
can satisfy the CYQ-GAME PIT-B contract for a requested historical window.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parquet_columns(conn: duckdb.DuckDBPyConnection, path: str) -> set[str]:
    rows = conn.execute("describe select * from read_parquet(?)", [path]).fetchall()
    return {str(row[0]) for row in rows}


def manifest_check(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {"path": None, "exists": False, "hash_matches": False}
    path = Path(raw).expanduser().resolve()
    result: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
    if not path.is_file():
        result["hash_matches"] = False
        return result
    result["sha256"] = sha256_file(path)
    result["hash_matches"] = True
    return result


def audit_asset(
    conn: duckdb.DuckDBPyConnection,
    name: str,
    path: str,
    required: set[str],
    manifest: str | None,
    start: str,
    end: str,
    date_expr: str,
) -> dict[str, Any]:
    columns = parquet_columns(conn, path)
    missing = sorted(required - columns)
    manifest_result = manifest_check(manifest)
    row_count = int(
        conn.execute(
            f"select count(*) from read_parquet(?) where {date_expr} between ? and ?",
            [path, start, end],
        ).fetchone()[0]
    )
    reasons: list[str] = []
    if missing:
        reasons.append("missing required record-level PIT fields: " + ", ".join(missing))
    if not manifest_result["exists"]:
        reasons.append("frozen manifest is missing")
    return {
        "asset": name,
        "path": str(Path(path).expanduser().resolve()),
        "columns": sorted(columns),
        "missing_required_fields": missing,
        "manifest": manifest_result,
        "rows_in_scope": row_count,
        "research_ready": not reasons,
        "gate_reasons": reasons,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--industry", required=True)
    parser.add_argument("--capital", required=True)
    parser.add_argument("--actions", required=True)
    parser.add_argument("--industry-manifest")
    parser.add_argument("--capital-manifest")
    parser.add_argument("--actions-manifest")
    parser.add_argument("--start", default="2010-01-01")
    parser.add_argument("--end", default="2017-12-31")
    parser.add_argument("--output", required=True)
    ns = parser.parse_args()
    conn = duckdb.connect()
    assets = [
        audit_asset(
            conn,
            "QD-008",
            ns.industry,
            {"available_at", "snapshot_id", "revision_id"},
            ns.industry_manifest,
            ns.start,
            ns.end,
            "coalesce(try_cast(notice_date as date), try_cast(report_date as date))",
        ),
        audit_asset(
            conn,
            "QD-009",
            ns.capital,
            {"available_at", "snapshot_id", "revision_id"},
            ns.capital_manifest,
            ns.start,
            ns.end,
            "try_strptime(cast(m_timetag as varchar), '%Y%m%d')::date",
        ),
        audit_asset(
            conn,
            "QD-010",
            ns.actions,
            {"available_at", "snapshot_id", "revision_id"},
            ns.actions_manifest,
            ns.start,
            ns.end,
            "coalesce(try_cast(effective_date as date), try_cast(announcement_date as date))",
        ),
    ]
    reasons = [reason for asset in assets for reason in asset["gate_reasons"]]
    report = {
        "asset_scope": {"start": ns.start, "end": ns.end},
        "research_gate": not reasons,
        "gate_reasons": reasons,
        "assets": assets,
        "policy": "Missing record lineage or manifest evidence fails closed; this audit never activates inputs.",
    }
    output = Path(ns.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
