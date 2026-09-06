#!/usr/bin/env python3
"""Fetch a bounded unadjusted native-5m market delta from Sina.

BaoStock date-effective universe/trading-state snapshots are treated as a
separate immutable input.  Sina responses provide only real completed 5-minute
bars; daily rows are exact aggregates of those bars, with suspended rows kept
explicit.  A partial BaoStock capture can be supplied for an independent
cross-provider audit before registration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import urllib.parse
import urllib.request
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq


SINA_URL = (
    "https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_cyq=/"
    "CN_MarketDataService.getKLineData"
)
DAILY_SCHEMA = pa.schema(
    [
        ("date", pa.string()), ("code", pa.string()), ("open", pa.string()),
        ("high", pa.string()), ("low", pa.string()), ("close", pa.string()),
        ("preclose", pa.string()), ("volume", pa.string()),
        ("amount", pa.string()), ("adjustflag", pa.string()),
        ("turn", pa.string()), ("pctChg", pa.string()),
        ("tradestatus", pa.string()), ("isST", pa.string()),
        ("minute_session_valid", pa.bool_()),
        ("source", pa.string()),
    ]
)
MINUTE_SCHEMA = pa.schema(
    [
        ("date", pa.string()), ("time", pa.string()), ("code", pa.string()),
        ("open", pa.string()), ("high", pa.string()), ("low", pa.string()),
        ("close", pa.string()), ("volume", pa.string()),
        ("amount", pa.string()), ("adjustflag", pa.string()),
        ("source", pa.string()),
    ]
)


@dataclass(frozen=True)
class Result:
    code: str
    status: str
    daily_rows: int = 0
    minute_rows: int = 0
    attempts: int = 0
    error: str | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _atomic_parquet(path: Path, rows: list[dict[str, str]], schema: pa.Schema) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".parquet", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), temporary, compression="zstd")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _response_rows(symbol: str, retries: int, retry_wait: float) -> tuple[list[dict[str, str]], int, str]:
    query = urllib.parse.urlencode(
        {"symbol": symbol.replace(".", ""), "scale": 5, "ma": "no", "datalen": 1023}
    )
    request = urllib.request.Request(
        f"{SINA_URL}?{query}",
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"},
    )
    last_error = ""
    for attempt in range(1, retries + 2):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
            text = raw.decode("utf-8")
            matched = re.search(r"=\((.*)\);?\s*$", text, flags=re.S)
            if matched is None:
                raise ValueError("unexpected Sina JSONP envelope")
            rows = json.loads(matched.group(1))
            if not isinstance(rows, list):
                raise ValueError("unexpected Sina row payload")
            return rows, attempt, hashlib.sha256(raw).hexdigest()
        except Exception as exc:  # the bounded retry evidence records the final cause
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt <= retries:
                time.sleep(retry_wait * attempt)
    raise RuntimeError(last_error)


def _normalize_code(code: str) -> str:
    return code.lower() if "." in code else code[:2].lower() + "." + code[2:]


def _download(task: tuple[str, dict[str, dict[str, str]], Path, int, float]) -> Result:
    symbol, universe_by_date, parts, retries, retry_wait = task
    stem = symbol.replace(".", "_")
    daily_path = parts / "daily" / f"{stem}.parquet"
    minute_path = parts / "minute_5m" / f"{stem}.parquet"
    receipt_path = parts / "receipts" / f"{stem}.json"
    if receipt_path.is_file() and daily_path.is_file() and minute_path.is_file():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if (
            receipt.get("status") == "ok"
            and receipt.get("schema_version") == 2
            and receipt.get("daily_sha256") == _sha256(daily_path)
            and receipt.get("minute_sha256") == _sha256(minute_path)
        ):
            return Result(symbol, "skipped", int(receipt["daily_rows"]), int(receipt["minute_rows"]))
    try:
        response_rows, attempts, response_sha = _response_rows(symbol, retries, retry_wait)
        grouped: dict[str, list[dict[str, str]]] = {}
        all_closes: dict[str, str] = {}
        for item in response_rows:
            stamp = str(item["day"])
            day = stamp[:10]
            all_closes[day] = str(item["close"])
            if day in universe_by_date:
                grouped.setdefault(day, []).append(item)
        daily_rows: list[dict[str, str]] = []
        minute_rows: list[dict[str, str]] = []
        ordered_response_dates = sorted(all_closes)
        code = _normalize_code(symbol)
        for day, state in sorted(universe_by_date.items()):
            active = state["trade_status"] == "1"
            bars = sorted(grouped.get(day, []), key=lambda item: item["day"])
            times = [item["day"][11:] for item in bars]
            minute_session_valid = (
                not active
                or (
                    len(bars) == 48
                    and times[0] == "09:35:00"
                    and times[-1] == "15:00:00"
                    and all(
                        float(item[field]) > 0
                        for item in bars
                        for field in ("open", "high", "low", "close")
                    )
                )
            )
            previous_dates = [value for value in ordered_response_dates if value < day]
            preclose = all_closes[previous_dates[-1]] if previous_dates else ""
            if bars:
                open_value = bars[0]["open"]
                high_value = str(max(float(item["high"]) for item in bars))
                low_value = str(min(float(item["low"]) for item in bars))
                close_value = bars[-1]["close"]
                volume_value = sum(float(item["volume"]) for item in bars)
                amount_value = sum(float(item["amount"]) for item in bars)
                pct = (
                    (float(close_value) / float(preclose) - 1.0) * 100.0
                    if preclose and float(preclose) > 0
                    else None
                )
                for item in bars:
                    minute_rows.append(
                        {
                            "date": day,
                            "time": item["day"].replace("-", "").replace(" ", "").replace(":", "") + "000",
                            "code": code,
                            "open": item["open"], "high": item["high"],
                            "low": item["low"], "close": item["close"],
                            "volume": item["volume"], "amount": item["amount"],
                            "adjustflag": "3", "source": "sina-none-5m",
                        }
                    )
            else:
                open_value = high_value = low_value = close_value = "0"
                volume_value = amount_value = 0.0
                pct = None
            daily_rows.append(
                {
                    "date": day, "code": code, "open": str(open_value),
                    "high": str(high_value), "low": str(low_value),
                    "close": str(close_value), "preclose": str(preclose),
                    "volume": format(volume_value, ".10g"),
                    "amount": format(amount_value, ".17g"), "adjustflag": "3",
                    "turn": "", "pctChg": "" if pct is None else format(pct, ".12g"),
                    "tradestatus": state["trade_status"],
                    "isST": "1" if "ST" in state["code_name"].upper() else "0",
                    "minute_session_valid": minute_session_valid,
                    "source": "sina-none-5m-aggregate+baostock-universe",
                }
            )
        _atomic_parquet(daily_path, daily_rows, DAILY_SCHEMA)
        _atomic_parquet(minute_path, minute_rows, MINUTE_SCHEMA)
        receipt = {
            "schema_version": 2, "status": "ok", "code": code, "attempts": attempts,
            "response_sha256": response_sha, "daily_rows": len(daily_rows),
            "minute_rows": len(minute_rows), "daily_sha256": _sha256(daily_path),
            "minute_sha256": _sha256(minute_path),
        }
        _atomic_json(receipt_path, receipt)
        return Result(symbol, "ok", len(daily_rows), len(minute_rows), attempts)
    except Exception as exc:
        return Result(symbol, "error", error=f"{type(exc).__name__}: {exc}")


def _load_universe(root: Path, start: date, end: date) -> tuple[dict[str, dict[str, dict[str, str]]], list[str]]:
    by_symbol: dict[str, dict[str, dict[str, str]]] = {}
    dates: list[str] = []
    for path in sorted((root / "universe").glob("snapshot_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        day = str(payload["trade_date"])
        parsed = date.fromisoformat(day)
        if not start <= parsed <= end:
            continue
        dates.append(day)
        for row in payload["rows"]:
            code = str(row["code"])
            by_symbol.setdefault(code, {})[day] = {
                "trade_status": str(row["trade_status"]),
                "code_name": str(row["code_name"]),
            }
    if not dates:
        raise ValueError("no bounded universe snapshots")
    return by_symbol, sorted(dates)


def _copy_reference_inputs(source: Path, output: Path, dates: list[str]) -> list[Path]:
    copied: list[Path] = []
    for day in dates:
        original = source / "universe" / f"snapshot_{day}.json"
        destination = output / "universe" / original.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, destination)
        copied.append(destination)
    for original in sorted((source / "index_daily").glob("*.parquet")):
        destination = output / "index_daily" / original.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, destination)
        copied.append(destination)
    return copied


def _assemble(parts: Path, output: Path) -> tuple[Path, Path]:
    daily = output / "raw_daily.parquet"
    minute = output / "raw_5m.parquet"
    connection = duckdb.connect()
    try:
        connection.execute("SET threads=4")
        connection.execute("SET preserve_insertion_order=false")
        for source, destination, order in (
            (parts / "daily" / "*.parquet", daily, "date, code"),
            (parts / "minute_5m" / "*.parquet", minute, "date, code, time"),
        ):
            source_sql = str(source).replace("'", "''")
            destination_sql = str(destination).replace("'", "''")
            connection.execute(
                f"COPY (SELECT * FROM read_parquet('{source_sql}', union_by_name=true) "
                f"ORDER BY {order}) TO '{destination_sql}' "
                "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 262144)"
            )
    finally:
        connection.close()
    return daily, minute


def _cross_provider_audit(parts: Path, baostock_parts: Path | None) -> dict[str, Any]:
    if baostock_parts is None:
        return {"status": "NOT_RUN", "reason": "no partial BaoStock capture supplied"}
    bao_glob = baostock_parts / "minute_5m" / "*.parquet"
    sina_glob = parts / "minute_5m" / "*.parquet"
    connection = duckdb.connect()
    try:
        row = connection.execute(
            """
            WITH b AS (
              SELECT code,date,time,TRY_CAST(open AS DOUBLE) open_value,
                     TRY_CAST(high AS DOUBLE) high_value,TRY_CAST(low AS DOUBLE) low_value,
                     TRY_CAST(close AS DOUBLE) close_value,
                     TRY_CAST(volume AS DOUBLE) volume_value,
                     TRY_CAST(amount AS DOUBLE) amount_value FROM read_parquet(?)
            ), s AS (
              SELECT code,date,time,TRY_CAST(open AS DOUBLE) open_value,
                     TRY_CAST(high AS DOUBLE) high_value,TRY_CAST(low AS DOUBLE) low_value,
                     TRY_CAST(close AS DOUBLE) close_value,
                     TRY_CAST(volume AS DOUBLE) volume_value,
                     TRY_CAST(amount AS DOUBLE) amount_value FROM read_parquet(?)
            ), joined AS (
              SELECT b.code,b.date,b.time,
                     GREATEST(ABS(b.open_value-s.open_value),
                              ABS(b.high_value-s.high_value),
                              ABS(b.low_value-s.low_value),
                              ABS(b.close_value-s.close_value)) price_error,
                     GREATEST(ABS(b.open_value-s.open_value),
                              ABS(b.high_value-s.high_value),
                              ABS(b.low_value-s.low_value),
                              ABS(b.close_value-s.close_value))
                       / NULLIF(ABS(b.close_value), 0) relative_price_error,
                     b.volume_value bv,s.volume_value sv,
                     b.amount_value ba,s.amount_value sa
              FROM b JOIN s USING(code,date,time)
            ), days AS (
              SELECT code,date,SUM(bv) bv,SUM(sv) sv,SUM(ba) ba,SUM(sa) sa
              FROM joined GROUP BY code,date
            )
            SELECT (SELECT COUNT(*) FROM joined),
                   (SELECT COUNT(DISTINCT code) FROM joined),
                   (SELECT QUANTILE_CONT(relative_price_error, 0.5) FROM joined),
                   (SELECT QUANTILE_CONT(relative_price_error, 0.95) FROM joined),
                   (SELECT MAX(relative_price_error) FROM joined),
                   COUNT(*),
                   COUNT(*) FILTER(WHERE ABS(bv-sv)/NULLIF(ABS(bv),0)<=0.01),
                   COUNT(*) FILTER(WHERE ABS(ba-sa)/NULLIF(ABS(ba),0)<=0.01),
                   MAX(ABS(bv-sv)/NULLIF(ABS(bv),0)),
                   MAX(ABS(ba-sa)/NULLIF(ABS(ba),0))
            FROM days
            """,
            [str(bao_glob), str(sina_glob)],
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    median_relative_price_error = float(row[2])
    p95_relative_price_error = float(row[3])
    volume_ratio = int(row[6]) / int(row[5]) if row[5] else 0.0
    amount_ratio = int(row[7]) / int(row[5]) if row[5] else 0.0
    checks = {
        "overlap_symbols_at_least_1000": int(row[1]) >= 1000,
        "median_relative_bar_price_error_at_most_0_05pct": (
            median_relative_price_error <= 0.0005
        ),
        "p95_relative_bar_price_error_at_most_0_3pct": (
            p95_relative_price_error <= 0.003
        ),
        "symbol_day_volume_within_1pct_at_least_95pct": volume_ratio >= 0.95,
        "symbol_day_amount_within_1pct_at_least_95pct": amount_ratio >= 0.95,
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "overlap_rows": int(row[0]), "overlap_symbols": int(row[1]),
        "overlap_symbol_days": int(row[5]),
        "median_relative_bar_price_error": median_relative_price_error,
        "p95_relative_bar_price_error": p95_relative_price_error,
        "volume_within_1pct_ratio": volume_ratio,
        "amount_within_1pct_ratio": amount_ratio,
        "maximum_relative_bar_price_error": row[4],
        "maximum_volume_relative_error": row[8],
        "maximum_amount_relative_error": row[9], "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--decision-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--baostock-parts", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--retry-wait", type=float, default=1.0)
    parser.add_argument("--minimum-coverage", type=float, default=0.95)
    parser.add_argument("--keep-parts", action="store_true")
    args = parser.parse_args()
    if args.end < args.start or not 0 < args.minimum_coverage <= 1:
        raise ValueError("invalid bounded coverage contract")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    universe, dates = _load_universe(args.reference_root, args.start, args.end)
    contract = {
        "schema_version": 1, "source": "Sina CN_MarketDataService.getKLineData",
        "universe_source": str(args.reference_root.resolve()),
        "start": args.start, "end": args.end, "decision_at": args.decision_at,
        "minute_resolution": "native 5m", "adjustment": "none",
        "minimum_coverage": args.minimum_coverage,
    }
    contract_path = output / "run_contract.json"
    if contract_path.exists():
        existing = json.loads(contract_path.read_text(encoding="utf-8"))
        if existing != json.loads(json.dumps(contract, default=str)):
            raise FileExistsError("existing run contract differs")
    else:
        _atomic_json(contract_path, contract)
    reference_files = _copy_reference_inputs(args.reference_root, output, dates)
    parts = output / "_parts"
    tasks = [
        (symbol, states, parts, args.retries, args.retry_wait)
        for symbol, states in sorted(universe.items())
    ]
    results: list[Result] = []
    with ProcessPoolExecutor(max_workers=min(args.workers, len(tasks))) as pool:
        futures = [pool.submit(_download, task) for task in tasks]
        for future in as_completed(futures):
            results.append(future.result())
            if len(results) % 100 == 0 or len(results) == len(tasks):
                good = sum(item.status in {"ok", "skipped"} for item in results)
                print(f"sina_delta_progress={len(results)}/{len(tasks)} ok={good} errors={len(results)-good}", flush=True)
    good = [item for item in results if item.status in {"ok", "skipped"}]
    coverage = len(good) / len(tasks)
    _atomic_json(output / "download_status.json", {
        "symbols": len(tasks), "succeeded": len(good), "coverage": coverage,
        "errors": [asdict(item) for item in results if item.status == "error"],
    })
    if coverage < args.minimum_coverage:
        print(json.dumps({"status": "FAIL", "coverage": coverage}), flush=True)
        return 1
    daily, minute = _assemble(parts, output)
    cross = _cross_provider_audit(parts, args.baostock_parts)
    if cross["status"] != "PASS":
        print(json.dumps({"status": "FAIL", "cross_provider": cross}, default=str), flush=True)
        return 1
    connection = duckdb.connect()
    try:
        daily_row = connection.execute(
            "SELECT COUNT(*),COUNT(DISTINCT code),COUNT(*)-COUNT(DISTINCT(code,date)) FROM read_parquet(?)",
            [str(daily)],
        ).fetchone()
        minute_row = connection.execute(
            "SELECT COUNT(*),COUNT(DISTINCT code),COUNT(*)-COUNT(DISTINCT(code,date,time)) FROM read_parquet(?)",
            [str(minute)],
        ).fetchone()
    finally:
        connection.close()
    assert daily_row is not None and minute_row is not None
    final_files = [contract_path, output / "download_status.json", daily, minute, *reference_files]
    inventory = [
        {"path": path.relative_to(output).as_posix(), "bytes": path.stat().st_size, "sha256": _sha256(path)}
        for path in sorted(final_files)
    ]
    manifest = {
        "schema_version": 1, "status": "PASS", "kind": "sina_unadjusted_market_delta",
        "created_at": datetime.now(UTC).isoformat(),
        "coverage": {
            "requested_start": args.start, "requested_end": args.end,
            "trade_dates": dates, "symbols_requested": len(tasks),
            "symbols_succeeded": len(good), "symbol_coverage": coverage,
            "daily_rows": int(daily_row[0]), "daily_symbols": int(daily_row[1]),
            "minute_5m_rows": int(minute_row[0]), "minute_5m_symbols": int(minute_row[1]),
        },
        "checks": {
            "coverage_at_least_threshold": coverage >= args.minimum_coverage,
            "daily_unique": int(daily_row[2]) == 0,
            "minute_5m_unique": int(minute_row[2]) == 0,
            "cross_provider_audit": cross["status"] == "PASS",
        },
        "cross_provider_evidence": cross,
        "units": {"price_basis": "unadjusted", "volume": "shares", "amount": "CNY", "minute_resolution": "5m"},
        "inventory": inventory,
        "blocked_uses": ["strict PIT-A claims", "fabricating 1-minute bars", "use without hard-valid row gates"],
    }
    _atomic_json(output / "manifest.json", manifest)
    if not args.keep_parts:
        shutil.rmtree(parts)
    print(json.dumps({"status": "PASS", "coverage": coverage, "manifest": str(output / 'manifest.json')}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
