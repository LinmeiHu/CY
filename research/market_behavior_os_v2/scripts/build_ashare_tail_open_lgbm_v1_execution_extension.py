#!/usr/bin/env python3
"""Build only the canonical CY-008 execution projection for 2013--2017."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import resource
import sys
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import psutil
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
INVENTORY = PROGRAM / "experiments/ASHARE-TAIL-OPEN-LGBM-V1_qd004_2013_2023_inventory.json"
MINUTE_ROOT = Path(
    "/Users/linmei/Downloads/workspace/quant/data/lake/stock_1min_canonical_none_20260813/bars"
)
DAILY_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_tail_open_lgbm_v1/pit_daily_2013_2023_cy006/daily"
)
OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_tail_open_lgbm_v1/pit_execution_2013_2017_cy006"
)
YEARS = tuple(range(2013, 2018))
RAM_FLOOR_BYTES = 8 * (1 << 30)
RSS_CEILING_BYTES = 8 * (1 << 30)


def _load_canonical_builder() -> Any:
    path = ROOT / "scripts/build_minute_pit_b.py"
    module_spec = importlib.util.spec_from_file_location("canonical_minute_pit_b", path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    return module


CANONICAL = _load_canonical_builder()


class ExtensionError(RuntimeError):
    """Fail-closed execution-extension error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _max_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _resource_gate() -> None:
    available = psutil.virtual_memory().available
    if available < RAM_FLOOR_BYTES:
        raise ExtensionError(f"system RAM below 8-GiB floor: {available}")
    rss = _max_rss_bytes()
    if rss > RSS_CEILING_BYTES:
        raise ExtensionError(f"process RSS above 8-GiB ceiling: {rss}")


def verify_inventory(years: tuple[int, ...] = YEARS) -> dict[str, str]:
    payload = json.loads(INVENTORY.read_text(encoding="utf-8"))
    root = Path(payload["root"])
    entries = {item["path"]: item for item in payload["files"]}
    hashes: dict[str, str] = {}
    for year in years:
        relative = f"bars/{year}_day_parquet_none.parquet"
        item = entries.get(relative)
        if item is None:
            raise ExtensionError(f"inventory is missing {relative}")
        path = root / relative
        if not path.is_file() or path.stat().st_size != item["size"]:
            raise ExtensionError(f"input size changed: {path}")
        observed = sha256_file(path)
        if observed != item["sha256"]:
            raise ExtensionError(f"input hash changed: {path}")
        hashes[str(year)] = observed
    return hashes


def _calendar(daily_file: Path, year: int) -> list[date]:
    connection = duckdb.connect()
    try:
        rows = connection.execute(
            "SELECT DISTINCT trade_date FROM read_parquet(?) "
            "WHERE year(trade_date)=? ORDER BY trade_date",
            [str(daily_file), year],
        ).fetchall()
    finally:
        connection.close()
    return [row[0] for row in rows]


def _verify_date_shard(path: Path, expected_date: date) -> dict[str, int]:
    table = pq.read_table(path, columns=["trade_date", "symbol", "window_index"])
    dates = {
        value.date() if hasattr(value, "date") else value
        for value in table["trade_date"].to_pylist()
    }
    if dates != {expected_date}:
        raise ExtensionError(f"date shard identity changed: {path}")
    windows = table["window_index"].to_pylist()
    if not windows or min(windows) != 0 or max(windows) != 5:
        raise ExtensionError(f"date shard window range changed: {path}")
    symbols = table["symbol"].to_pylist()
    if len(set(zip(symbols, windows, strict=True))) != table.num_rows:
        raise ExtensionError(f"duplicate execution key: {path}")
    return {"rows": table.num_rows, "symbols": len(set(symbols))}


def _connection(year: int) -> duckdb.DuckDBPyConnection:
    temporary = OUTPUT_ROOT / "tmp" / f"year={year}-pid={os.getpid()}"
    temporary.mkdir(parents=True, exist_ok=False)
    connection = duckdb.connect()
    connection.execute("SET threads=1")
    connection.execute("SET memory_limit='3GB'")
    connection.execute("SET preserve_insertion_order=false")
    connection.execute(f"SET temp_directory='{temporary.as_posix()}'")
    return connection


def build_year(year: int) -> dict[str, Any]:
    _resource_gate()
    raw_file = MINUTE_ROOT / f"{year}_day_parquet_none.parquet"
    daily_file = DAILY_ROOT / f"partition_year={year}" / "data_0.parquet"
    if not raw_file.is_file() or not daily_file.is_file():
        raise ExtensionError(f"missing year input: {year}")
    dates = _calendar(daily_file, year)
    date_root = OUTPUT_ROOT / "date_shards" / f"year={year}"
    date_root.mkdir(parents=True, exist_ok=True)
    rows = 0
    symbols: set[str] = set()
    for index, trade_date in enumerate(dates):
        _resource_gate()
        destination = date_root / f"date={trade_date.isoformat()}.parquet"
        if not destination.is_file():
            connection = _connection(year)
            try:
                CANONICAL._create_source_views(connection, [raw_file], daily_file, None, None)
                CANONICAL._write_product(
                    connection,
                    CANONICAL._execution_sql("m.trade_date = ?"),
                    [trade_date],
                    destination,
                    False,
                )
            finally:
                temporary = Path(
                    connection.execute("SELECT current_setting('temp_directory')").fetchone()[0]
                )
                connection.close()
                if temporary.is_dir():
                    import shutil

                    shutil.rmtree(temporary)
        audit = _verify_date_shard(destination, trade_date)
        rows += audit["rows"]
        table = pq.read_table(destination, columns=["symbol"])
        symbols.update(table["symbol"].to_pylist())
        if index % 25 == 0:
            print(
                json.dumps(
                    {
                        "stage": "execution_extension",
                        "year": year,
                        "date": trade_date.isoformat(),
                        "dates_complete": index + 1,
                        "rows": rows,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
    annual = OUTPUT_ROOT / "execution_5m" / f"partition_year={year}" / "data_0.parquet"
    annual.parent.mkdir(parents=True, exist_ok=True)
    temporary_annual = annual.with_name(f".{annual.name}.{os.getpid()}.tmp")
    connection = duckdb.connect()
    connection.execute("SET threads=1")
    connection.execute("SET memory_limit='3GB'")
    connection.execute("SET preserve_insertion_order=false")
    paths = [str(path) for path in sorted(date_root.glob("date=*.parquet"))]
    quoted = temporary_annual.as_posix().replace("'", "''")
    connection.execute(
        f"COPY (SELECT * EXCLUDE(year) FROM read_parquet($paths,union_by_name=true) "
        f"ORDER BY trade_date,symbol,window_index) TO '{quoted}' "
        "(FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 100000)",
        {"paths": paths},
    )
    aggregate = connection.execute(
        """SELECT count(*),count(DISTINCT (trade_date,symbol,window_index)),
        count(DISTINCT trade_date),count(DISTINCT symbol),
        sum((window_index=0)::INTEGER),sum((window_index NOT BETWEEN 0 AND 5)::INTEGER),
        sum((available_at <> CAST(trade_date AS TIMESTAMP)+INTERVAL '9 hours 35 minutes'
          +window_index*INTERVAL '5 minutes')::INTEGER)
        FROM read_parquet(?)""",
        [str(temporary_annual)],
    ).fetchone()
    connection.close()
    if aggregate[0] != aggregate[1] or aggregate[5] != 0 or aggregate[6] != 0:
        raise ExtensionError(f"annual execution audit failed: {year} {aggregate}")
    os.replace(temporary_annual, annual)
    return {
        "year": year,
        "rows": int(aggregate[0]),
        "dates": int(aggregate[2]),
        "symbols": int(aggregate[3]),
        "window0_rows": int(aggregate[4]),
        "sha256": sha256_file(annual),
        "bytes": annual.stat().st_size,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, choices=YEARS)
    parser.add_argument("--verify-inputs", action="store_true")
    args = parser.parse_args()
    years = (args.year,) if args.year else YEARS
    hashes = verify_inventory(years) if args.verify_inputs else {"verified": False}
    results = [build_year(year) for year in years]
    print(json.dumps({"input_hashes": hashes, "years": results}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
