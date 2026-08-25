#!/usr/bin/env python3
"""Build the current outcome-blind semantic chip delta from exact operators."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from cyq_game.strategy.current_chip_features import (
    build_current_chip_measurement_features,
)

_REQUIRED_COLUMNS = frozenset(
    {
        "symbol",
        "trade_date",
        "cost_p05",
        "cost_p15",
        "cost_p85",
        "cost_p95",
        "exact_p50",
        "dominant_band_mass",
        "i70_width_fraction",
        "i90_width_fraction",
        "model_spread_i90_width_fraction",
        "available_at",
        "snapshot_id",
        "research_valid",
        "exact_research_valid",
    }
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lineage-root", type=Path, required=True)
    parser.add_argument("--daily-root", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--symbols-per-task", type=int, default=24)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _symbol_from_path(path: Path) -> str:
    return path.stem.replace("_SH", ".SH").replace("_SZ", ".SZ")


def _symbols(lineage_root: Path, year: int) -> tuple[str, ...]:
    values = {
        _symbol_from_path(path)
        for path in lineage_root.glob(f"year={year}/parts/bucket=*/*.parquet")
    }
    return tuple(sorted(values))


def _build_chunk(
    task: tuple[
        Path,
        tuple[tuple[str, dict[date, float]], ...],
        date,
        date,
        Path,
    ],
) -> dict[str, Any]:
    lineage_root, symbols_and_closes, start, end, output = task
    expected = {symbol for symbol, _ in symbols_and_closes}
    if output.is_file() and _REQUIRED_COLUMNS.issubset(
        pq.ParquetFile(output).schema_arrow.names
    ):
        table = pq.read_table(output, columns=["symbol"])
        actual = set(table.column("symbol").to_pylist())
        if actual == expected:
            return {
                "symbols": len(expected),
                "rows": table.num_rows,
                "failures": [],
                "reused": True,
            }
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for symbol, closes in symbols_and_closes:
        try:
            semantic = build_current_chip_measurement_features(
                lineage_root, symbol, closes, start, end
            )
            if not semantic:
                raise RuntimeError("no semantic rows")
            rows.extend(semantic)
        except Exception as error:
            failures.append(
                {"symbol": symbol, "error": f"{type(error).__name__}: {error}"}
            )
    if not rows:
        raise RuntimeError(f"chunk produced no rows: {failures[:3]}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp.parquet")
    temporary.unlink(missing_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), temporary, compression="zstd")
    temporary.replace(output)
    return {
        "symbols": len(expected),
        "rows": len(rows),
        "failures": failures,
        "reused": False,
    }


def _sql(path: Path) -> str:
    return "'" + str(path.resolve()).replace("'", "''") + "'"


def main() -> int:
    args = _parse_args()
    if args.start < date(2026, 6, 17) or args.end < args.start:
        raise ValueError("current semantic range must begin on/after 2026-06-17")
    if args.start.year != args.end.year:
        raise ValueError("current semantic build must stay inside one year")
    if args.workers < 1 or args.symbols_per_task < 1:
        raise ValueError("worker and task sizes must be positive")
    lineage_root = args.lineage_root.resolve()
    daily_file = (
        args.daily_root.resolve()
        / f"partition_year={args.start.year}"
        / "data_0.parquet"
    )
    if not daily_file.is_file():
        raise FileNotFoundError(daily_file)
    symbols = _symbols(lineage_root, args.start.year)
    if not symbols:
        raise ValueError("no current operator parts found")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    symbols_text = "".join(f"{symbol}\n" for symbol in symbols)
    symbols_path = output / "symbols.txt"
    if symbols_path.exists() and symbols_path.read_text(encoding="utf-8") != symbols_text:
        raise FileExistsError("existing symbol inventory differs")
    symbols_path.write_text(symbols_text, encoding="utf-8")

    connection = duckdb.connect()
    connection.execute("SET threads=4")
    connection.execute("SET memory_limit='6GiB'")
    symbol_sql = ",".join("'" + value.replace("'", "''") + "'" for value in symbols)
    rows = connection.execute(
        f"""
        SELECT symbol, trade_date, close
        FROM read_parquet({_sql(daily_file)})
        WHERE symbol IN ({symbol_sql}) AND trade_date BETWEEN ? AND ?
        ORDER BY symbol, trade_date
        """,
        [args.start, args.end],
    ).fetchall()
    closes: dict[str, dict[date, float]] = {symbol: {} for symbol in symbols}
    for symbol, trade_date, close in rows:
        closes[str(symbol)][trade_date] = float(close)
    connection.close()

    chunks = [
        symbols[start : start + args.symbols_per_task]
        for start in range(0, len(symbols), args.symbols_per_task)
    ]
    parts = output / "_parts"
    tasks = [
        (
            lineage_root,
            tuple((symbol, closes[symbol]) for symbol in chunk),
            args.start,
            args.end,
            parts / f"part-{index:05d}.parquet",
        )
        for index, chunk in enumerate(chunks)
    ]
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=min(args.workers, len(tasks))) as executor:
        futures = [executor.submit(_build_chunk, task) for task in tasks]
        for position, future in enumerate(as_completed(futures), start=1):
            results.append(future.result())
            if position % 10 == 0 or position == len(futures):
                print(
                    json.dumps(
                        {
                            "completed_tasks": position,
                            "total_tasks": len(futures),
                            "rows": sum(item["rows"] for item in results),
                            "failures": sum(
                                len(item["failures"]) for item in results
                            ),
                        }
                    ),
                    flush=True,
                )

    final = output / "semantic_features.parquet"
    temporary = final.with_suffix(".tmp.parquet")
    temporary.unlink(missing_ok=True)
    connection = duckdb.connect()
    connection.execute("SET threads=4")
    connection.execute("SET memory_limit='6GiB'")
    connection.execute("SET preserve_insertion_order=false")
    connection.execute(
        f"""
        COPY (
          SELECT * FROM read_parquet({_sql(parts / '*.parquet')}, union_by_name=true)
          ORDER BY symbol, trade_date
        ) TO {_sql(temporary)} (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    metrics = connection.execute(
        f"""
        SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(trade_date), MAX(trade_date),
               COUNT(*) - COUNT(DISTINCT (symbol, trade_date)),
               COUNT(*) FILTER (WHERE research_valid AND exact_research_valid),
               COUNT(*) FILTER (
                   WHERE cost_p05 > cost_p15 OR cost_p15 > cost_p85
                      OR cost_p85 > cost_p95 OR i70_width_fraction < 0
                      OR i90_width_fraction < i70_width_fraction
                      OR snapshot_id IS NULL OR available_at IS NULL
               )
        FROM read_parquet({_sql(temporary)})
        """
    ).fetchone()
    connection.close()
    assert metrics is not None
    failures = [failure for item in results for failure in item["failures"]]
    checks = {
        "date_range_exact": metrics[2] == args.start and metrics[3] == args.end,
        "unique_symbol_date": metrics[4] == 0,
        "measurement_valid_at_least_95pct": metrics[5] / max(metrics[0], 1) >= 0.95,
        "semantic_invariants": metrics[6] == 0,
        "symbol_success_at_least_95pct": (
            (len(symbols) - len(failures)) / len(symbols) >= 0.95
        ),
    }
    manifest = {
        "schema_version": 1,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "pipeline_version": "current-semantic-chip-delta-v1",
        "start": args.start.isoformat(),
        "end": args.end.isoformat(),
        "lineage_root": str(lineage_root),
        "daily_file": str(daily_file),
        "daily_file_sha256": _sha256(daily_file),
        "symbols": len(symbols),
        "rows": metrics[0],
        "output_symbols": metrics[1],
        "measurement_valid_rows": metrics[5],
        "failures": failures,
        "checks": checks,
        "data_sha256": _sha256(temporary),
        "symbols_sha256": _sha256(symbols_path),
    }
    manifest_path = output / "build_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if manifest["status"] != "PASS":
        raise RuntimeError(json.dumps(manifest, ensure_ascii=False))
    temporary.replace(final)
    shutil.rmtree(parts)
    print(json.dumps(manifest, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
