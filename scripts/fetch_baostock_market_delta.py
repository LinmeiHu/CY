#!/usr/bin/env python3
"""Freeze a resumable BaoStock market-data delta without mutating old assets.

The collector stores exact string-valued API rows per symbol while a run is in
progress, then assembles immutable daily and 5-minute Parquet snapshots.  The
5-minute response remains explicitly 5-minute data and is never expanded into
fabricated 1-minute bars.
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import os
import shutil
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

DAILY_FIELDS = (
    "date,code,open,high,low,close,preclose,volume,amount,adjustflag,"
    "turn,pctChg,tradestatus,isST"
)
MINUTE_FIELDS = "date,time,code,open,high,low,close,volume,amount,adjustflag"
INDEX_CODES = {
    "csi000300": "sh.000300",
    "csi000852": "sh.000852",
    "csi000905": "sh.000905",
    "sh000001": "sh.000001",
    "sz399001": "sz.399001",
    "sz399006": "sz.399006",
}
_STRING_SCHEMA_DAILY = pa.schema(
    [(field, pa.string()) for field in DAILY_FIELDS.split(",")]
)
_STRING_SCHEMA_MINUTE = pa.schema(
    [(field, pa.string()) for field in MINUTE_FIELDS.split(",")]
)
_WORKER_BS: Any = None
_WORKER_LOGGED_IN = False


@dataclass(frozen=True)
class SymbolResult:
    code: str
    status: str
    daily_rows: int
    minute_rows: int
    attempts: int
    elapsed_seconds: float
    error: str | None = None


def _canonical_json(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_a_share_code(code: str) -> bool:
    if code.startswith("sh."):
        return code[3:].startswith(("600", "601", "603", "605", "688", "689"))
    if code.startswith("sz."):
        return code[3:].startswith(("000", "001", "002", "003", "300", "301"))
    return False


def _validate_decision_cutoff(end: date, decision_at: datetime) -> None:
    local = decision_at.astimezone(ZoneInfo("Asia/Shanghai"))
    if end > local.date():
        raise ValueError("end date exceeds decision_at")
    if end == local.date() and local.hour < 15:
        raise ValueError("same-day market data is unavailable before 15:00 Asia/Shanghai")


def _existing_parent(path: Path) -> Path:
    candidate = path.resolve()
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            raise FileNotFoundError(path)
        candidate = parent
    return candidate


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".building")
    temporary.write_bytes(_canonical_json(payload))
    os.replace(temporary, path)


def _atomic_parquet(path: Path, rows: list[list[str]], schema: pa.Schema) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = {
        field.name: [row[index] for row in rows]
        for index, field in enumerate(schema)
    }
    table = pa.Table.from_pydict(columns, schema=schema)
    temporary = path.with_suffix(".building.parquet")
    temporary.unlink(missing_ok=True)
    pq.write_table(table, temporary, compression="zstd")
    os.replace(temporary, path)


def _worker_logout() -> None:
    global _WORKER_LOGGED_IN
    if _WORKER_BS is not None and _WORKER_LOGGED_IN:
        try:
            _WORKER_BS.logout()
        except Exception:
            pass
    _WORKER_LOGGED_IN = False


def _worker_login(max_attempts: int = 3) -> bool:
    global _WORKER_LOGGED_IN
    if _WORKER_BS is None:
        return False
    if _WORKER_LOGGED_IN:
        return True
    for attempt in range(1, max_attempts + 1):
        try:
            login = _WORKER_BS.login()
            if login.error_code == "0":
                _WORKER_LOGGED_IN = True
                return True
        except Exception:
            pass
        if attempt < max_attempts:
            time.sleep(min(4.0, 0.5 * attempt))
    return False


def _worker_init() -> None:
    global _WORKER_BS
    import baostock as bs  # type: ignore[import-not-found]

    _WORKER_BS = bs
    # Avoid a simultaneous login burst when the process pool starts.
    time.sleep((os.getpid() % 8) * 0.15)
    _worker_login()
    atexit.register(_worker_logout)


def _query_rows(
    code: str,
    fields: str,
    start: str,
    end: str,
    frequency: str,
) -> list[list[str]]:
    if not _worker_login():
        raise RuntimeError("BaoStock worker login retries exhausted")
    result = _WORKER_BS.query_history_k_data_plus(
        code,
        fields,
        start_date=start,
        end_date=end,
        frequency=frequency,
        adjustflag="3",
    )
    if result.error_code != "0":
        raise RuntimeError(
            f"{frequency} query failed: {result.error_code} {result.error_msg}"
        )
    rows: list[list[str]] = []
    while result.next():
        rows.append(result.get_row_data())
    return rows


def _download_symbol(
    task: tuple[str, str, str, Path, int, float],
) -> SymbolResult:
    code, start, end, parts, retries, retry_wait = task
    safe = code.replace(".", "_")
    receipt = parts / "receipts" / f"{safe}.json"
    daily_path = parts / "daily" / f"{safe}.parquet"
    minute_path = parts / "minute_5m" / f"{safe}.parquet"
    if receipt.is_file() and daily_path.is_file() and minute_path.is_file():
        payload = json.loads(receipt.read_text(encoding="utf-8"))
        if payload.get("status") == "ok":
            return SymbolResult(
                code=code,
                status="skipped",
                daily_rows=int(payload["daily_rows"]),
                minute_rows=int(payload["minute_rows"]),
                attempts=0,
                elapsed_seconds=0.0,
            )

    started = time.monotonic()
    error: str | None = None
    for attempt in range(1, retries + 2):
        try:
            daily_rows = _query_rows(code, DAILY_FIELDS, start, end, "d")
            minute_rows = _query_rows(code, MINUTE_FIELDS, start, end, "5")
            if not daily_rows:
                raise RuntimeError("daily response is empty for an in-universe symbol")
            if any(row[1] != code for row in daily_rows):
                raise RuntimeError("daily response code mismatch")
            if any(row[2] != code for row in minute_rows):
                raise RuntimeError("5-minute response code mismatch")
            if any(row[9] != "3" for row in daily_rows + minute_rows):
                raise RuntimeError("adjustflag is not unadjusted")
            _atomic_parquet(daily_path, daily_rows, _STRING_SCHEMA_DAILY)
            _atomic_parquet(minute_path, minute_rows, _STRING_SCHEMA_MINUTE)
            payload = {
                "code": code,
                "status": "ok",
                "daily_rows": len(daily_rows),
                "minute_rows": len(minute_rows),
                "attempts": attempt,
                "daily_sha256": _sha256(daily_path),
                "minute_5m_sha256": _sha256(minute_path),
            }
            _atomic_json(receipt, payload)
            return SymbolResult(
                code=code,
                status="ok",
                daily_rows=len(daily_rows),
                minute_rows=len(minute_rows),
                attempts=attempt,
                elapsed_seconds=time.monotonic() - started,
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            if attempt <= retries:
                _worker_logout()
                time.sleep(retry_wait * attempt)
    return SymbolResult(
        code=code,
        status="error",
        daily_rows=0,
        minute_rows=0,
        attempts=retries + 1,
        elapsed_seconds=time.monotonic() - started,
        error=error,
    )


def _login() -> Any:
    import baostock as bs  # type: ignore[import-not-found]

    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"BaoStock login failed: {login.error_code} {login.error_msg}")
    return bs


def _trade_dates(bs: Any, start: date, end: date) -> list[str]:
    response = bs.query_trade_dates(
        start_date=start.isoformat(), end_date=end.isoformat()
    )
    if response.error_code != "0":
        raise RuntimeError(
            f"trade-date query failed: {response.error_code} {response.error_msg}"
        )
    dates: list[str] = []
    while response.next():
        row = response.get_row_data()
        if row[1] == "1":
            dates.append(row[0])
    if not dates:
        raise RuntimeError("requested interval contains no trading dates")
    return dates


def _universe_snapshots(bs: Any, dates: list[str], output: Path) -> tuple[str, ...]:
    selected: set[str] = set()
    for day in dates:
        response = bs.query_all_stock(day=day)
        if response.error_code != "0":
            raise RuntimeError(
                f"universe query failed for {day}: "
                f"{response.error_code} {response.error_msg}"
            )
        rows: list[dict[str, str]] = []
        while response.next():
            code, trade_status, code_name = response.get_row_data()
            if not _is_a_share_code(code):
                continue
            rows.append(
                {
                    "code": code,
                    "trade_status": trade_status,
                    "code_name": code_name,
                }
            )
            selected.add(code)
        _atomic_json(
            output / "universe" / f"snapshot_{day}.json",
            {
                "trade_date": day,
                "captured_at": datetime.now(UTC).isoformat(),
                "source": "baostock.query_all_stock",
                "fields": list(response.fields),
                "rows": rows,
            },
        )
    return tuple(sorted(selected))


def _fetch_indices(bs: Any, start: date, end: date, output: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    fields = "date,code,open,high,low,close,preclose,volume,amount,pctChg"
    for name, code in INDEX_CODES.items():
        response = bs.query_history_k_data_plus(
            code,
            fields,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            frequency="d",
            adjustflag="3",
        )
        if response.error_code != "0":
            raise RuntimeError(
                f"index query failed for {code}: {response.error_code} {response.error_msg}"
            )
        rows: list[list[str]] = []
        while response.next():
            rows.append(response.get_row_data())
        schema = pa.schema([(field, pa.string()) for field in fields.split(",")])
        path = output / "index_daily" / f"{name}.parquet"
        _atomic_parquet(path, rows, schema)
        result.append(
            {"index_symbol": name, "code": code, "rows": len(rows), "sha256": _sha256(path)}
        )
    return result


def _resume_reference_data(
    output: Path, start: date, end: date
) -> tuple[list[str], tuple[str, ...], list[dict[str, Any]]] | None:
    universe_files = sorted((output / "universe").glob("snapshot_*.json"))
    index_files = [output / "index_daily" / f"{name}.parquet" for name in INDEX_CODES]
    if not universe_files or not all(path.is_file() for path in index_files):
        return None
    dates: list[str] = []
    symbols: set[str] = set()
    for path in universe_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        day = str(payload.get("trade_date", ""))
        if not day or not start.isoformat() <= day <= end.isoformat():
            return None
        rows = payload.get("rows")
        if not isinstance(rows, list):
            return None
        dates.append(day)
        symbols.update(
            str(row["code"])
            for row in rows
            if isinstance(row, dict) and _is_a_share_code(str(row.get("code", "")))
        )
    if dates != sorted(set(dates)) or not symbols:
        return None
    index_evidence = [
        {
            "index_symbol": name,
            "code": INDEX_CODES[name],
            "rows": pq.ParquetFile(path).metadata.num_rows,
            "sha256": _sha256(path),
        }
        for name, path in zip(INDEX_CODES, index_files, strict=True)
    ]
    return dates, tuple(sorted(symbols)), index_evidence


def _sql_path_list(paths: list[Path]) -> str:
    return "[" + ",".join("'" + str(path).replace("'", "''") + "'" for path in paths) + "]"


def _assemble(parts: Path, output: Path) -> tuple[Path, Path]:
    daily_parts = sorted((parts / "daily").glob("*.parquet"))
    minute_parts = sorted((parts / "minute_5m").glob("*.parquet"))
    if not daily_parts or len(daily_parts) != len(minute_parts):
        raise RuntimeError("completed part inventories are incomplete")
    daily_output = output / "raw_daily.parquet"
    minute_output = output / "raw_5m.parquet"
    connection = duckdb.connect()
    connection.execute("SET threads=4")
    connection.execute("SET memory_limit='4GiB'")
    try:
        for paths, destination, order in (
            (daily_parts, daily_output, "code, date"),
            (minute_parts, minute_output, "code, date, time"),
        ):
            temporary = destination.with_suffix(".building.parquet")
            temporary.unlink(missing_ok=True)
            escaped = str(temporary).replace("'", "''")
            connection.execute(
                f"COPY (SELECT * FROM read_parquet({_sql_path_list(paths)}, "
                f"union_by_name=true) ORDER BY {order}) TO '{escaped}' "
                "(FORMAT PARQUET, COMPRESSION ZSTD)"
            )
            os.replace(temporary, destination)
    finally:
        connection.close()
    return daily_output, minute_output


def _inventory(output: Path, files: list[Path]) -> list[dict[str, Any]]:
    return [
        {
            "path": path.relative_to(output).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(files)
    ]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--decision-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument("--symbols-file", type=Path)
    parser.add_argument("--max-symbols", type=int, default=0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--retry-wait", type=float, default=0.5)
    parser.add_argument("--minimum-coverage", type=float, default=0.95)
    parser.add_argument("--min-free-gib", type=float, default=100.0)
    parser.add_argument("--keep-parts", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.end < args.start:
        raise ValueError("end must not precede start")
    _validate_decision_cutoff(args.end, args.decision_at)
    if args.workers < 1 or args.retries < 0:
        raise ValueError("workers must be positive and retries non-negative")
    if not 0 < args.minimum_coverage <= 1:
        raise ValueError("minimum coverage must be in (0, 1]")
    free_gib = shutil.disk_usage(_existing_parent(args.output.parent)).free / 1024**3
    if free_gib < args.min_free_gib:
        raise RuntimeError(
            f"disk guard failed: free={free_gib:.1f}GiB < {args.min_free_gib:.1f}GiB"
        )

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    contract_path = output / "run_contract.json"
    contract = {
        "schema_version": 1,
        "source": "BaoStock 00.9.30 query_history_k_data_plus",
        "start": args.start.isoformat(),
        "end": args.end.isoformat(),
        "decision_at": args.decision_at.astimezone(
            ZoneInfo("Asia/Shanghai")
        ).isoformat(),
        "daily_fields": DAILY_FIELDS,
        "minute_5m_fields": MINUTE_FIELDS,
        "adjustflag": "3",
        "minimum_coverage": args.minimum_coverage,
    }
    if contract_path.exists():
        if json.loads(contract_path.read_text(encoding="utf-8")) != contract:
            raise FileExistsError("existing run contract differs")
    else:
        _atomic_json(contract_path, contract)

    resumed_reference = _resume_reference_data(output, args.start, args.end)
    if resumed_reference is None:
        bs = _login()
        try:
            dates = _trade_dates(bs, args.start, args.end)
            universe = _universe_snapshots(bs, dates, output)
            index_evidence = _fetch_indices(bs, args.start, args.end, output)
        finally:
            bs.logout()
    else:
        dates, universe, index_evidence = resumed_reference
    if args.symbols_file:
        requested = {
            line.strip().lower()
            for line in args.symbols_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
        universe = tuple(code for code in universe if code.lower() in requested)
    if args.max_symbols:
        universe = universe[: args.max_symbols]
    if not universe:
        raise RuntimeError("selected universe is empty")

    parts = output / "_parts"
    tasks = [
        (
            code,
            args.start.isoformat(),
            args.end.isoformat(),
            parts,
            args.retries,
            args.retry_wait,
        )
        for code in universe
    ]
    results: list[SymbolResult] = []
    started = time.monotonic()
    with ProcessPoolExecutor(
        max_workers=min(args.workers, len(tasks)), initializer=_worker_init
    ) as pool:
        futures = [pool.submit(_download_symbol, task) for task in tasks]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            completed = len(results)
            if completed % 50 == 0 or completed == len(tasks):
                ok = sum(item.status in {"ok", "skipped"} for item in results)
                errors = completed - ok
                print(
                    f"baostock_delta_progress={completed}/{len(tasks)} "
                    f"ok={ok} errors={errors}",
                    flush=True,
                )
    good = [result for result in results if result.status in {"ok", "skipped"}]
    coverage = len(good) / len(universe)
    errors = [asdict(result) for result in results if result.status == "error"]
    _atomic_json(
        output / "download_status.json",
        {
            "symbols": len(universe),
            "ok": sum(result.status == "ok" for result in results),
            "skipped": sum(result.status == "skipped" for result in results),
            "error": len(errors),
            "coverage": coverage,
            "errors": errors,
        },
    )
    if coverage < args.minimum_coverage:
        print(
            json.dumps(
                {"status": "FAIL", "coverage": coverage, "errors": len(errors)},
                ensure_ascii=False,
            )
        )
        return 1

    daily_output, minute_output = _assemble(parts, output)
    final_files = [
        contract_path,
        output / "download_status.json",
        daily_output,
        minute_output,
        *sorted((output / "universe").glob("*.json")),
        *sorted((output / "index_daily").glob("*.parquet")),
    ]
    con = duckdb.connect()
    try:
        daily_metrics = con.execute(
            "SELECT count(*), count(distinct code), min(date), max(date), "
            "count(*) - count(distinct (code, date)) FROM read_parquet(?)",
            [str(daily_output)],
        ).fetchone()
        minute_metrics = con.execute(
            "SELECT count(*), count(distinct code), min(date), max(date), "
            "count(*) - count(distinct (code, date, time)) FROM read_parquet(?)",
            [str(minute_output)],
        ).fetchone()
    finally:
        con.close()
    assert daily_metrics is not None and minute_metrics is not None
    checks = {
        "coverage_at_least_threshold": coverage >= args.minimum_coverage,
        "daily_unique": int(daily_metrics[4]) == 0,
        "minute_5m_unique": int(minute_metrics[4]) == 0,
        "daily_not_after_end": str(daily_metrics[3]) <= args.end.isoformat(),
        "minute_not_after_end": str(minute_metrics[3]) <= args.end.isoformat(),
    }
    manifest = {
        "schema_version": 1,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "kind": "baostock_unadjusted_market_delta",
        "created_at": datetime.now(UTC).isoformat(),
        "coverage": {
            "requested_start": args.start.isoformat(),
            "requested_end": args.end.isoformat(),
            "trade_dates": dates,
            "symbols_requested": len(universe),
            "symbols_succeeded": len(good),
            "symbol_coverage": coverage,
            "daily_rows": int(daily_metrics[0]),
            "daily_symbols": int(daily_metrics[1]),
            "daily_start": daily_metrics[2],
            "daily_end": daily_metrics[3],
            "minute_5m_rows": int(minute_metrics[0]),
            "minute_5m_symbols": int(minute_metrics[1]),
            "minute_5m_start": minute_metrics[2],
            "minute_5m_end": minute_metrics[3],
        },
        "units": {
            "price_basis": "unadjusted",
            "volume": "shares",
            "amount": "CNY",
            "minute_resolution": "5m",
        },
        "index_evidence": index_evidence,
        "checks": checks,
        "finalization_resume_elapsed_seconds": time.monotonic() - started,
        "inventory": _inventory(output, final_files),
        "allowed_uses": [
            "normalization and quality review after registry admission",
            "5-minute execution and volume-at-price only at actual bar completion",
        ],
        "blocked_uses": [
            "research before registry admission and cross-table gates",
            "fabricating 1-minute bars from 5-minute responses",
            "strict PIT-A claims",
        ],
    }
    manifest_path = output / "manifest.json"
    _atomic_json(manifest_path, manifest)
    if not args.keep_parts:
        shutil.rmtree(parts)
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "coverage": coverage,
                "daily_rows": daily_metrics[0],
                "minute_5m_rows": minute_metrics[0],
                "manifest": str(manifest_path),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0 if manifest["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
