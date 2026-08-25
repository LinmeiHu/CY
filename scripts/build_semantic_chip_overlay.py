#!/usr/bin/env python3
"""Build the outcome-blind CY-021 semantic chip overlay for 2020-2022."""

from __future__ import annotations

import argparse
import json
import shutil
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import duckdb
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from cyq_game.strategy.semantic_chip import build_semantic_ensemble_features

_REQUIRED_COLUMNS = frozenset(
    {
        "cost_p05",
        "cost_p15",
        "cost_p85",
        "cost_p95",
        "i70_width_fraction",
        "i90_width_fraction",
        "lower_peak_center",
        "upper_peak_center",
        "valley_depth",
        "model_spread_i90_width_fraction",
    }
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    symbol_group = parser.add_mutually_exclusive_group(required=True)
    symbol_group.add_argument("--symbols-file", type=Path)
    symbol_group.add_argument("--symbols-by-year-file", type=Path)
    parser.add_argument("--lineage-root", type=Path, required=True)
    parser.add_argument(
        "--daily-root",
        type=Path,
        default=Path("data/processed/pit_b_daily_2018_2026_v2/daily"),
    )
    parser.add_argument("--start", type=date.fromisoformat, default=date(2020, 1, 2))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2022, 12, 30))
    parser.add_argument("--workers", type=int, default=4)
    return parser.parse_args()


def _build_symbol(
    task: tuple[Path, str, dict[date, float], date, date, Path],
) -> tuple[str, int, bool]:
    root, symbol, closes, start, end, output = task
    if output.is_file() and _REQUIRED_COLUMNS.issubset(
        pq.ParquetFile(output).schema_arrow.names
    ):
        return symbol, pq.ParquetFile(output).metadata.num_rows, True
    rows = build_semantic_ensemble_features(root, symbol, closes, start, end)
    if not rows:
        raise RuntimeError(f"no semantic chip rows for {symbol}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp.parquet")
    temporary.unlink(missing_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), temporary, compression="zstd")
    temporary.replace(output)
    return symbol, len(rows), False


def main() -> int:
    args = parse_args()
    if args.end < args.start:
        raise ValueError("--end must not precede --start")
    if args.end.year >= 2023:
        raise ValueError("CY-021 development overlay is physically locked before 2023")
    if args.workers < 1:
        raise ValueError("--workers must be positive")
    if args.symbols_file is not None:
        symbols = tuple(
            line.strip()
            for line in args.symbols_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    else:
        by_year = json.loads(args.symbols_by_year_file.read_text(encoding="utf-8"))
        if not isinstance(by_year, dict):
            raise ValueError("symbols-by-year file must contain an object")
        selected: set[str] = set()
        for year in range(args.start.year, args.end.year + 1):
            annual = by_year.get(str(year))
            if not isinstance(annual, list) or not all(
                isinstance(symbol, str) and symbol for symbol in annual
            ):
                raise ValueError(f"symbols-by-year has no valid {year} list")
            selected.update(annual)
        symbols = tuple(sorted(selected))
    if not symbols or len(symbols) != len(set(symbols)):
        raise ValueError("symbols file must be non-empty and unique")
    years = range(args.start.year, args.end.year + 1)
    daily_files = [
        args.daily_root / f"partition_year={year}" / "data_0.parquet"
        for year in years
    ]
    missing = [path for path in daily_files if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"daily inputs missing: {missing}")
    symbol_sql = ",".join("'" + value.replace("'", "''") + "'" for value in symbols)
    sql_files = "[" + ",".join(f"'{path}'" for path in daily_files) + "]"
    con = duckdb.connect()
    con.execute("SET memory_limit='8GiB'")
    con.execute(f"SET threads={min(args.workers, 4)}")
    close_rows = con.execute(
        f"""
        SELECT symbol, trade_date, close
        FROM read_parquet({sql_files}, union_by_name=true)
        WHERE symbol IN ({symbol_sql})
          AND trade_date BETWEEN ? AND ?
        ORDER BY symbol, trade_date
        """,
        [args.start, args.end],
    ).fetchall()
    closes: dict[str, dict[date, float]] = {symbol: {} for symbol in symbols}
    for symbol, trade_date, close in close_rows:
        closes[str(symbol)][trade_date] = float(close)
    con.close()

    args.output.mkdir(parents=True, exist_ok=True)
    frozen_symbols = "".join(f"{symbol}\n" for symbol in symbols)
    symbols_output = args.output / "symbols.txt"
    if symbols_output.exists():
        if symbols_output.read_text(encoding="utf-8") != frozen_symbols:
            raise FileExistsError("existing semantic overlay symbol inventory differs")
    else:
        symbols_output.write_text(frozen_symbols, encoding="utf-8")
    parts = args.output / "_parts"
    tasks = [
        (
            args.lineage_root,
            symbol,
            closes[symbol],
            args.start,
            args.end,
            parts / f"{symbol.replace('.', '_')}.parquet",
        )
        for symbol in symbols
    ]
    completed = 0
    rows = 0
    reused = 0
    with ProcessPoolExecutor(
        max_workers=min(args.workers, len(tasks)), max_tasks_per_child=1
    ) as pool:
        futures = [pool.submit(_build_symbol, task) for task in tasks]
        for future in as_completed(futures):
            _, count, was_reused = future.result()
            completed += 1
            rows += count
            reused += int(was_reused)
            if completed % 25 == 0 or completed == len(tasks):
                print(
                    f"semantic_progress={completed}/{len(tasks)} rows={rows} reused={reused}",
                    flush=True,
                )

    final = args.output / "semantic_features.parquet"
    temporary = final.with_suffix(".tmp.parquet")
    temporary.unlink(missing_ok=True)
    con = duckdb.connect()
    con.execute("SET memory_limit='8GiB'")
    con.execute(f"SET threads={min(args.workers, 4)}")
    con.execute("SET preserve_insertion_order=false")
    con.execute(
        f"""
        COPY (
            SELECT * FROM read_parquet('{parts}/*.parquet', union_by_name=true)
            ORDER BY symbol, trade_date
        ) TO '{temporary}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    metrics = con.execute(
        f"""
        SELECT count(*), count(DISTINCT symbol),
               count(*) FILTER (WHERE research_valid AND cost_p05 > cost_p95)
        FROM read_parquet('{temporary}')
        """
    ).fetchone()
    con.close()
    if metrics is None or int(metrics[1]) != len(symbols) or int(metrics[2]) != 0:
        raise RuntimeError(f"semantic overlay coverage failed: {metrics}")
    temporary.replace(final)
    shutil.rmtree(parts)
    print(
        f"PASS symbols={metrics[1]} rows={metrics[0]} output={final}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
