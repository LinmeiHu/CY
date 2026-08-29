from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from xtquant import xtdata

TZ = ZoneInfo("Asia/Shanghai")
INDEX_SYMBOLS = ["000852.SH", "000300.SH"]
# 510300.SH is already in the frozen ETF pool. 000852.SH is the only
# strategy market anchor omitted by the ETF-only critical-minute export.
CRITICAL_MINUTE_ANCHORS = ["000852.SH"]
CRITICAL_TIMES = {
    "093000": "OPEN_BAR_09_30",
    "145700": "PSEUDO_CLOSE_14_57_OPEN",
    "150000": "FINAL_CLOSE_BAR",
}
PRICE_FIELDS = ["open", "high", "low", "close"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export the isolated frozen-V6 universe from a running QMT MiniQmt"
    )
    parser.add_argument("--strategy", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--start", default="19900101", help="YYYYMMDD")
    parser.add_argument("--end", required=True, help="YYYYMMDD")
    parser.add_argument(
        "--mode",
        choices=["daily", "critical-minute", "all"],
        default="all",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--extract-only",
        action="store_true",
        help="read the existing MiniQmt cache without requesting another download",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        help="explicit bounded QMT symbols to export for the selected mode",
    )
    parser.add_argument(
        "--symbols-file",
        type=Path,
        help="JSON universe manifest containing a canonical symbols list",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        help="optional export-summary path; defaults to <output>/qmt_export_summary.json",
    )
    return parser.parse_args()


def parse_strategy_pool(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assignments: list[list[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Attribute) and target.attr == "pool_raw"
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise TypeError("context.pool_raw must be a literal list[str]")
            assignments.append(value)
    if len(assignments) != 1:
        raise ValueError(f"expected one context.pool_raw assignment; found {len(assignments)}")
    pool = assignments[0]
    if len(pool) != 152 or len(set(pool)) != 152:
        raise ValueError("frozen strategy pool must contain 152 unique codes")
    return pool


def canonical_symbol(raw_code: str) -> str:
    if raw_code.startswith("5"):
        return f"{raw_code}.SH"
    if raw_code.startswith("1"):
        return f"{raw_code}.SZ"
    raise ValueError(f"unsupported ETF code: {raw_code}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    os.replace(temporary, path)


def export_trade_calendar(output_root: Path, start: str, end: str) -> None:
    source = "QMT XtData get_trading_calendar(SH)"
    try:
        values = xtdata.get_trading_calendar("SH", start_time=start, end_time=end)
        dates = pd.to_datetime(values, format="%Y%m%d").date
    except RuntimeError:
        values = xtdata.get_trading_dates("SH", start_time=start, end_time=end, count=-1)
        dates = pd.to_datetime(values, unit="ms", utc=True).tz_convert("Asia/Shanghai").date
        source = "QMT XtData get_trading_dates(SH) legacy fallback"
    frame = pd.DataFrame({"trade_date": dates})
    frame = frame.drop_duplicates().sort_values("trade_date").reset_index(drop=True)
    frame["is_trading_day"] = True
    frame["calendar_source"] = source
    path = output_root / "metadata" / "trade_calendar_qmt.parquet"
    atomic_parquet(path, frame)
    print(
        f"QMT_CALENDAR rows={len(frame)} first={frame['trade_date'].min()} "
        f"last={frame['trade_date'].max()}",
        flush=True,
    )


def request_key(mode: str, symbol: str, start: str, end: str) -> dict[str, str]:
    return {
        "mode": mode,
        "symbol": symbol,
        "start": start,
        "end": end,
        "raw_dividend_type": "none",
        "adjusted_dividend_type": "front",
        "fill_data": "false",
    }


def valid_cached_partition(path: Path, metadata_path: Path, request: dict[str, str]) -> bool:
    if not path.exists() or not metadata_path.exists():
        return False
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return metadata.get("request") == request and metadata.get("sha256") == sha256_file(path)


def qmt_frame(symbol: str, period: str, start: str, end: str, basis: str) -> pd.DataFrame:
    result = xtdata.get_market_data_ex(
        field_list=[],
        stock_list=[symbol],
        period=period,
        start_time=start,
        end_time=end,
        count=-1,
        dividend_type=basis,
        fill_data=False,
    )
    frame = result.get(symbol, pd.DataFrame())
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"QMT returned {type(frame).__name__} for {symbol} {period}")
    frame = frame.copy()
    frame.index = frame.index.astype(str)
    if frame.index.duplicated().any():
        raise ValueError(f"QMT returned duplicate indices for {symbol} {period}")
    return frame


def combine_bases(raw: pd.DataFrame, front: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame()
    missing_front = raw.index.difference(front.index)
    if len(missing_front):
        raise ValueError(f"adjusted data missing {len(missing_front)} raw indices")
    front = front.reindex(raw.index)
    required = ["time", *PRICE_FIELDS, "volume", "amount", "preClose", "suspendFlag"]
    missing = [column for column in required if column not in raw.columns]
    if missing:
        raise ValueError(f"QMT raw frame missing columns: {missing}")
    missing_adjusted = [column for column in PRICE_FIELDS if column not in front.columns]
    if missing_adjusted:
        raise ValueError(f"QMT front frame missing columns: {missing_adjusted}")

    output = pd.DataFrame(index=raw.index)
    output["qmt_time_ms"] = pd.to_numeric(raw["time"], errors="coerce")
    for field in PRICE_FIELDS:
        output[f"raw_{field}"] = pd.to_numeric(raw[field], errors="coerce")
        output[f"pre_adj_{field}"] = pd.to_numeric(front[field], errors="coerce")
    output["adj_factor_close_ratio"] = output["pre_adj_close"] / output["raw_close"]
    output["volume_raw"] = pd.to_numeric(raw["volume"], errors="coerce")
    output["amount_cny"] = pd.to_numeric(raw["amount"], errors="coerce")
    output["raw_pre_close"] = pd.to_numeric(raw["preClose"], errors="coerce")
    output["qmt_suspend_flag"] = pd.to_numeric(raw["suspendFlag"], errors="coerce")
    output["qmt_index"] = output.index
    return output.reset_index(drop=True)


def assign_row_status(frame: pd.DataFrame) -> pd.Series:
    prices = frame[
        [f"raw_{field}" for field in PRICE_FIELDS] + [f"pre_adj_{field}" for field in PRICE_FIELDS]
    ]
    finite = np.isfinite(prices).all(axis=1)
    positive_prices = (prices > 0).all(axis=1)
    finite_flow = np.isfinite(frame[["volume_raw", "amount_cny"]]).all(axis=1)
    status = pd.Series("VALID", index=frame.index, dtype="object")
    status.loc[frame["qmt_suspend_flag"].eq(1)] = "SUSPENDED"
    status.loc[~finite | ~positive_prices | ~finite_flow] = "NONFINITE"
    nonpositive = frame["volume_raw"].le(0) | frame["amount_cny"].le(0)
    status.loc[finite & positive_prices & finite_flow & nonpositive] = "NONPOSITIVE_VOLUME"
    return status


def normalize_daily(symbol: str, raw: pd.DataFrame, front: pd.DataFrame) -> pd.DataFrame:
    frame = combine_bases(raw, front)
    if frame.empty:
        return frame
    frame.insert(0, "trade_date", pd.to_datetime(frame["qmt_index"], format="%Y%m%d").dt.date)
    frame.insert(1, "symbol", symbol)
    frame.insert(2, "raw_code", symbol.split(".")[0])
    frame.insert(3, "exchange", symbol.split(".")[1])
    frame.insert(4, "row_status", assign_row_status(frame))
    frame["volume_unit"] = "lot_100_shares" if symbol not in INDEX_SYMBOLS else "qmt_native"
    frame["volume_shares"] = frame["volume_raw"] * 100.0 if symbol not in INDEX_SYMBOLS else np.nan
    frame["available_at"] = frame["trade_date"].map(
        lambda value: datetime.combine(
            value + timedelta(days=1), datetime.min.time(), tzinfo=TZ
        ).isoformat()
    )
    frame["source"] = "QMT XtData via running Guojin MiniQmt"
    frame["adjustment_status"] = "qmt_front_supermind_pre_equivalence_unverified"
    return frame


def normalize_critical(symbol: str, raw: pd.DataFrame, front: pd.DataFrame) -> pd.DataFrame:
    critical_raw = raw[raw.index.str[-6:].isin(CRITICAL_TIMES)].copy()
    critical_front = front.reindex(critical_raw.index).copy()
    frame = combine_bases(critical_raw, critical_front)
    if frame.empty:
        return frame
    parsed = pd.to_datetime(frame["qmt_index"], format="%Y%m%d%H%M%S")
    frame.insert(0, "trade_date", parsed.dt.date)
    frame.insert(1, "datetime", parsed.map(lambda value: value.replace(tzinfo=TZ).isoformat()))
    frame.insert(2, "symbol", symbol)
    frame.insert(3, "raw_code", symbol.split(".")[0])
    frame.insert(4, "exchange", symbol.split(".")[1])
    frame.insert(5, "bar_role", frame["qmt_index"].str[-6:].map(CRITICAL_TIMES))
    frame.insert(6, "row_status", assign_row_status(frame))
    frame["volume_unit"] = "lot_100_shares"
    frame["volume_shares"] = frame["volume_raw"] * 100.0
    frame["timezone"] = "Asia/Shanghai"
    frame["source"] = "QMT XtData 1m via running Guojin MiniQmt"
    frame["adjustment_status"] = "qmt_front_supermind_pre_equivalence_unverified"
    frame["opening_auction_status"] = "qmt_09_30_bar_not_proven_exact_opening_auction"
    return frame


def coverage(frame: pd.DataFrame, path: Path, elapsed: float) -> dict[str, Any]:
    valid = frame[frame["row_status"] == "VALID"] if "row_status" in frame else frame
    result: dict[str, Any] = {
        "rows": len(frame),
        "valid_rows": len(valid),
        "first_date": str(frame["trade_date"].min()) if len(frame) else None,
        "last_date": str(frame["trade_date"].max()) if len(frame) else None,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "elapsed_seconds": round(elapsed, 3),
    }
    if "bar_role" in frame:
        counts = frame["bar_role"].value_counts().to_dict()
        result["bar_role_counts"] = {str(key): int(value) for key, value in counts.items()}
    return result


def export_partition(
    *,
    mode: str,
    symbol: str,
    start: str,
    end: str,
    output_root: Path,
    force: bool,
    download: bool,
) -> dict[str, Any]:
    if mode == "daily":
        period = "1d"
        path = output_root / "daily" / f"symbol={symbol}" / "daily.parquet"
    else:
        period = "1m"
        path = output_root / "minute_critical" / f"symbol={symbol}" / "critical.parquet"
    metadata_path = path.with_suffix(path.suffix + ".qmt.json")
    request = request_key(mode, symbol, start, end)
    if not force and valid_cached_partition(path, metadata_path, request):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        print(f"CACHE {mode} {symbol} rows={metadata['coverage']['rows']}", flush=True)
        return metadata["coverage"] | {"cache_hit": True}

    started = time.monotonic()
    print(f"DOWNLOAD {mode} {symbol} {start}..{end}", flush=True)
    if download:
        xtdata.download_history_data(
            symbol,
            period=period,
            start_time=start,
            end_time=end,
            incrementally=True,
        )
    raw = qmt_frame(symbol, period, start, end, "none")
    front = qmt_frame(symbol, period, start, end, "front")
    frame = (
        normalize_daily(symbol, raw, front)
        if mode == "daily"
        else normalize_critical(symbol, raw, front)
    )
    if frame.empty:
        raise ValueError(f"QMT returned no {mode} rows")
    capture_at = datetime.now(TZ).isoformat()
    frame["capture_at"] = capture_at
    frame["snapshot_id"] = f"qmt-{mode}-{end}-{datetime.now(TZ).strftime('%Y%m%dT%H%M%S%z')}"
    frame["source_endpoint"] = "MiniQmt local RPC on dynamic loopback port"
    if mode == "critical-minute":
        frame["available_at"] = frame["datetime"]
    atomic_parquet(path, frame)
    item = coverage(frame, path, time.monotonic() - started)
    metadata = {
        "request": request,
        "coverage": item,
        "sha256": item["sha256"],
        "created_at": datetime.now(TZ).isoformat(),
        "xtdata_path": str(Path(xtdata.__file__).resolve()),
    }
    atomic_json(metadata_path, metadata)
    print(f"RESULT {mode} {symbol} rows={len(frame)}", flush=True)
    return item | {"cache_hit": False}


def main() -> int:
    args = parse_args()
    datetime.strptime(args.start, "%Y%m%d")
    datetime.strptime(args.end, "%Y%m%d")
    pool_raw = parse_strategy_pool(args.strategy)
    pool_symbols = [canonical_symbol(code) for code in pool_raw]
    explicit_symbols = list(args.symbols or [])
    if args.symbols_file:
        universe = json.loads(args.symbols_file.read_text(encoding="utf-8"))
        explicit_symbols.extend(universe.get("symbols", []))
    explicit_symbols = list(dict.fromkeys(explicit_symbols))
    modes = ["daily", "critical-minute"] if args.mode == "all" else [args.mode]
    args.output.mkdir(parents=True, exist_ok=True)
    export_trade_calendar(args.output, args.start, args.end)

    summary_path = args.summary or args.output / "qmt_export_summary.json"
    summary: dict[str, Any] = {
        "started_at": datetime.now(TZ).isoformat(),
        "request": {"start": args.start, "end": args.end, "modes": modes},
        "strategy_path": str(args.strategy),
        "universe_count": len(pool_symbols),
        "daily_symbols_expected": pool_symbols + INDEX_SYMBOLS,
        "critical_minute_symbols_expected": pool_symbols + CRITICAL_MINUTE_ANCHORS,
        "results": {"daily": {}, "critical-minute": {}},
        "errors": [],
    }
    failures = 0
    for mode in modes:
        symbols = (
            pool_symbols + INDEX_SYMBOLS
            if mode == "daily"
            else pool_symbols + CRITICAL_MINUTE_ANCHORS
        )
        if explicit_symbols:
            symbols = explicit_symbols
            allowed = set(pool_symbols + INDEX_SYMBOLS)
            unsupported = sorted(
                symbol
                for symbol in set(symbols) - allowed
                if not re.fullmatch(
                    r"(?:(?:000|001|002|003|300|301)\d{3}\.SZ|"
                    r"(?:600|601|603|605)\d{3}\.SH)",
                    symbol,
                )
            )
            if unsupported:
                raise ValueError(f"unsupported explicit symbols: {unsupported}")
        for index, symbol in enumerate(symbols, start=1):
            print(f"PROGRESS {mode} {index}/{len(symbols)} {symbol}", flush=True)
            try:
                summary["results"][mode][symbol] = export_partition(
                    mode=mode,
                    symbol=symbol,
                    start=args.start,
                    end=args.end,
                    output_root=args.output,
                    force=args.force,
                    download=not args.extract_only,
                )
            except Exception as exc:
                failures += 1
                error = {
                    "mode": mode,
                    "symbol": symbol,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
                summary["errors"].append(error)
                summary["results"][mode][symbol] = {"rows": 0, "error": error}
                print(
                    f"ERROR {mode} {symbol}: {type(exc).__name__}: {exc}",
                    flush=True,
                )
            summary["completed_at"] = datetime.now(TZ).isoformat()
            summary["failures"] = failures
            summary["status"] = "PASS" if failures == 0 else "FAIL"
            atomic_json(summary_path, summary)

    print(f"QMT_EXPORT_STATUS {summary['status']}", flush=True)
    print(f"QMT_EXPORT_SUMMARY {summary_path}", flush=True)
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
