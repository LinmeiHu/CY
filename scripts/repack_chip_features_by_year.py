#!/usr/bin/env python3
"""Repack frozen chip features for fast day-oriented causal reads."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import duckdb


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--start-year", type=int, default=2018)
    parser.add_argument("--end-year", type=int, default=2026)
    parser.add_argument("--threads", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    parser.add_argument("--memory-limit", default="24GB")
    return parser.parse_args()


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def main() -> int:
    args = _arguments()
    source_files = sorted(args.source.glob("bucket=*/data.parquet"))
    if not source_files:
        raise SystemExit(f"no source files under {args.source}")
    if args.output.exists():
        raise SystemExit(f"output already exists: {args.output}")

    temporary_root = args.output.with_name(f".{args.output.name}.tmp")
    if temporary_root.exists():
        shutil.rmtree(temporary_root)
    temporary_root.mkdir(parents=True)

    connection = duckdb.connect()
    connection.execute(f"SET threads={args.threads}")
    connection.execute(f"SET memory_limit='{args.memory_limit}'")
    connection.from_parquet(
        [str(path) for path in source_files], hive_partitioning=False
    ).create_view("source_features")

    years: list[dict[str, object]] = []
    try:
        for year in range(args.start_year, args.end_year + 1):
            destination = temporary_root / f"year={year}" / "data.parquet"
            destination.parent.mkdir(parents=True)
            destination_sql = str(destination).replace("'", "''")
            connection.execute(
                "COPY (SELECT * FROM source_features "
                "WHERE trade_date >= ? AND trade_date < ? "
                f"ORDER BY trade_date, symbol) TO '{destination_sql}' "
                "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 122880)",
                [f"{year}-01-01", f"{year + 1}-01-01"],
            )
            source_stats = connection.execute(
                "SELECT count(*), count(DISTINCT (symbol, trade_date)), "
                "min(trade_date), max(trade_date), "
                "sum(CASE WHEN strict_sample THEN 1 ELSE 0 END) "
                "FROM source_features WHERE trade_date >= ? AND trade_date < ?",
                [f"{year}-01-01", f"{year + 1}-01-01"],
            ).fetchone()
            target_stats = connection.execute(
                "SELECT count(*), count(DISTINCT (symbol, trade_date)), "
                "min(trade_date), max(trade_date), "
                "sum(CASE WHEN strict_sample THEN 1 ELSE 0 END) "
                "FROM read_parquet(?, hive_partitioning=false)",
                [str(destination)],
            ).fetchone()
            passed = source_stats == target_stats and source_stats[0] == source_stats[1]
            years.append(
                {
                    "year": year,
                    "rows": source_stats[0],
                    "unique_keys": source_stats[1],
                    "min_date": str(source_stats[2]),
                    "max_date": str(source_stats[3]),
                    "strict_rows": source_stats[4],
                    "bytes": destination.stat().st_size,
                    "pass": passed,
                }
            )
            print(f"year={year} rows={source_stats[0]} pass={passed}", flush=True)
            if not passed:
                raise RuntimeError(f"repack validation failed for {year}")

        os.replace(temporary_root, args.output)
    except BaseException:
        shutil.rmtree(temporary_root, ignore_errors=True)
        raise
    finally:
        connection.close()

    payload = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "source": str(args.source.resolve()),
        "output": str(args.output.resolve()),
        "transformation": "SELECT * partitioned by year ORDER BY trade_date,symbol",
        "content_changed": False,
        "checks": [
            "source and target per-year row counts equal",
            "source and target per-year key counts equal",
            "source and target per-year date bounds equal",
            "source and target per-year strict row counts equal",
            "symbol/trade_date keys unique",
        ],
        "years": years,
        "total_rows": sum(int(item["rows"]) for item in years),
        "total_bytes": sum(int(item["bytes"]) for item in years),
        "status": "PASS" if all(bool(item["pass"]) for item in years) else "FAIL",
    }
    _atomic_json(args.audit, payload)
    _atomic_json(args.output / "_COMPLETE.json", payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
