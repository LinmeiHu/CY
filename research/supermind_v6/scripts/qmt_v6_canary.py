from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from xtquant import xtdata

CANARY_SYMBOLS = ["510300.SH", "159915.SZ", "588000.SH"]
CANARY_PERIODS = ["1d", "1m"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bounded QMT market-data canary for V6")
    parser.add_argument("--start", default="20260817", help="YYYYMMDD")
    parser.add_argument("--end", default="20260821", help="YYYYMMDD")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--symbols", nargs="+", default=CANARY_SYMBOLS)
    parser.add_argument("--periods", nargs="+", choices=["1d", "1m"], default=CANARY_PERIODS)
    return parser.parse_args()


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return str(value)


def summarize_frame(frame: pd.DataFrame) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "rows": len(frame),
        "columns": list(frame.columns),
        "index_name": frame.index.name,
        "first_index": str(frame.index[0]) if len(frame) else None,
        "last_index": str(frame.index[-1]) if len(frame) else None,
    }
    if "time" in frame and len(frame):
        times = pd.to_numeric(frame["time"], errors="coerce").dropna()
        if not times.empty:
            converted = pd.to_datetime(times, unit="ms", utc=True).dt.tz_convert("Asia/Shanghai")
            summary["first_time_ms"] = int(times.iloc[0])
            summary["last_time_ms"] = int(times.iloc[-1])
            summary["first_time_shanghai"] = converted.iloc[0].isoformat()
            summary["last_time_shanghai"] = converted.iloc[-1].isoformat()
    return summary


def main() -> int:
    args = parse_args()
    datetime.strptime(args.start, "%Y%m%d")
    datetime.strptime(args.end, "%Y%m%d")
    args.output.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {
        "started_at": datetime.now().astimezone().isoformat(),
        "symbols": args.symbols,
        "periods": args.periods,
        "start": args.start,
        "end": args.end,
        "xtdata_path": str(Path(xtdata.__file__).resolve()),
        "results": {},
    }
    failures = 0
    for period in args.periods:
        period_result: dict[str, Any] = {}
        period_dir = args.output / period
        period_dir.mkdir(parents=True, exist_ok=True)
        for symbol in args.symbols:
            print(f"DOWNLOAD {period} {symbol} {args.start}..{args.end}", flush=True)
            started = time.monotonic()
            try:
                download_result = xtdata.download_history_data(
                    symbol,
                    period=period,
                    start_time=args.start,
                    end_time=args.end,
                )
                data = xtdata.get_market_data_ex(
                    field_list=[],
                    stock_list=[symbol],
                    period=period,
                    start_time=args.start,
                    end_time=args.end,
                    count=-1,
                    dividend_type="none",
                    fill_data=False,
                )
                frame = data.get(symbol, pd.DataFrame())
                if not isinstance(frame, pd.DataFrame):
                    raise TypeError(f"unexpected frame type: {type(frame).__name__}")
                output_path = period_dir / f"{symbol}.csv"
                frame.to_csv(output_path, index=True)
                item = summarize_frame(frame)
                item.update(
                    {
                        "download_result": json_safe(download_result),
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                        "output": str(output_path),
                        "output_bytes": output_path.stat().st_size,
                        "status": "PASS" if len(frame) else "EMPTY",
                    }
                )
                if frame.empty:
                    failures += 1
                period_result[symbol] = item
                print(
                    f"RESULT {period} {symbol} rows={len(frame)} status={item['status']}",
                    flush=True,
                )
            except Exception as exc:
                failures += 1
                period_result[symbol] = {
                    "status": "ERROR",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                }
                print(
                    f"ERROR {period} {symbol}: {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
        result["results"][period] = period_result

    result["completed_at"] = datetime.now().astimezone().isoformat()
    result["failures"] = failures
    result["status"] = "PASS" if failures == 0 else "FAIL"
    summary_path = args.output / "summary.json"
    summary_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"SUMMARY {summary_path}", flush=True)
    print(f"CANARY_STATUS {result['status']}", flush=True)
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
