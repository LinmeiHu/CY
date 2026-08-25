#!/usr/bin/env python3
"""Assemble a space-efficient current minute PIT-B asset.

Frozen historical partitions are referenced by symlink.  Only the current 2026
partition is materialized by appending a separately audited, non-overlapping
delta.  This avoids duplicating the multi-gigabyte CY-008 history.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-root", type=Path, required=True)
    parser.add_argument("--delta-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sql(path: Path) -> str:
    return "'" + str(path.resolve()).replace("'", "''") + "'"


def _stats(
    connection: duckdb.DuckDBPyConnection,
    path: Path,
    key: str,
) -> dict[str, Any]:
    duplicate_expression = (
        "COUNT(*) - COUNT(DISTINCT (symbol, trade_date))"
        if key == "daily"
        else "COUNT(*) - COUNT(DISTINCT (symbol, trade_date, window_index))"
    )
    row = connection.execute(
        f"""
        SELECT COUNT(*), COUNT(*) FILTER (WHERE hard_valid),
               MIN(trade_date), MAX(trade_date), {duplicate_expression},
               COUNT(*) FILTER (WHERE available_at < CAST(trade_date AS TIMESTAMP))
        FROM read_parquet({_sql(path)})
        """
    ).fetchone()
    assert row is not None
    return {
        "rows": row[0],
        "hard_valid_rows": row[1],
        "start": row[2],
        "end": row[3],
        "duplicate_keys": row[4],
        "bad_available_at": row[5],
    }


def _merge_2026(
    connection: duckdb.DuckDBPyConnection,
    base: Path,
    delta: Path,
    output: Path,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    connection.execute(
        f"""
        COPY (
          SELECT * FROM read_parquet({_sql(base)})
          UNION ALL BY NAME
          SELECT * FROM read_parquet({_sql(delta)})
        ) TO {_sql(output)} (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )


def _link_history(base_root: Path, temporary: Path) -> None:
    for product in ("daily", "execution_5m"):
        for year in range(2018, 2026):
            source = (
                base_root / product / f"partition_year={year}" / "data_0.parquet"
            ).resolve()
            if not source.is_file():
                raise FileNotFoundError(source)
            destination = (
                temporary / product / f"partition_year={year}" / "data_0.parquet"
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.symlink_to(source)


def main() -> int:
    args = _parse_args()
    base_root = args.base_root.resolve()
    delta_root = args.delta_root.resolve()
    output_root = args.output_root.resolve()
    if output_root.exists():
        raise FileExistsError(output_root)
    temporary = output_root.parent / f".{output_root.name}.building-{uuid.uuid4().hex}"
    temporary.mkdir(parents=True, exist_ok=False)
    connection = duckdb.connect()
    try:
        connection.execute("SET threads=4")
        connection.execute("SET memory_limit='8GB'")
        connection.execute("SET preserve_insertion_order=false")
        _link_history(base_root, temporary)
        product_audits: dict[str, Any] = {}
        inventory: list[dict[str, Any]] = []
        for product in ("daily", "execution_5m"):
            base_file = (
                base_root / product / "partition_year=2026" / "data_0.parquet"
            )
            delta_file = (
                delta_root / product / "partition_year=2026" / "data_0.parquet"
            )
            output_file = (
                temporary / product / "partition_year=2026" / "data_0.parquet"
            )
            base_stats = _stats(connection, base_file, product)
            delta_stats = _stats(connection, delta_file, product)
            if base_stats["end"] >= delta_stats["start"]:
                raise ValueError(f"{product} base and delta overlap")
            _merge_2026(connection, base_file, delta_file, output_file)
            merged_stats = _stats(connection, output_file, product)
            if merged_stats["rows"] != base_stats["rows"] + delta_stats["rows"]:
                raise ValueError(f"{product} row count is not conserved")
            if merged_stats["duplicate_keys"] or merged_stats["bad_available_at"]:
                raise ValueError(f"{product} merged current partition failed causal QA")
            product_audits[product] = {
                "base": base_stats,
                "delta": delta_stats,
                "merged_2026": merged_stats,
            }
            inventory.append(
                {
                    "path": str(output_file.relative_to(temporary)),
                    "size": output_file.stat().st_size,
                    "sha256": _sha256(output_file),
                }
            )
        daily_delta = product_audits["daily"]["delta"]
        checks = {
            "base_and_delta_do_not_overlap": True,
            "merged_2026_unique": True,
            "available_at_not_before_trade_date": True,
            "daily_delta_hard_valid_at_least_95pct": (
                daily_delta["hard_valid_rows"] / daily_delta["rows"] >= 0.95
            ),
            "execution_has_six_windows_per_daily_row": (
                product_audits["execution_5m"]["delta"]["rows"]
                == daily_delta["rows"] * 6
            ),
        }
        audit = {
            "schema_version": 1,
            "status": "PASS" if all(checks.values()) else "FAIL",
            "generated_at": datetime.now().astimezone().isoformat(),
            "pipeline_version": "minute-pit-b-current-composite-v1",
            "products": product_audits,
            "checks": checks,
            "inventory": inventory,
            "history_policy": "2018-2025 are symlinks to frozen CY-008; only 2026 is rematerialized",
        }
        audit_path = temporary / "audit.json"
        audit_path.write_text(
            json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True, default=str)
            + "\n",
            encoding="utf-8",
        )
        if audit["status"] != "PASS":
            raise RuntimeError(json.dumps(audit, ensure_ascii=False, default=str))
        os.replace(temporary, output_root)
        print(json.dumps(audit, ensure_ascii=False, default=str))
        return 0
    finally:
        connection.close()
        if temporary.exists():
            shutil.rmtree(temporary)


if __name__ == "__main__":
    raise SystemExit(main())
