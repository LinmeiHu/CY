#!/usr/bin/env python3
"""Freeze the exact QMT 399102.SZ daily bars used by the smoke replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from xtquant import xtdata

SYMBOL = "399102.SZ"
TZ = ZoneInfo("Asia/Shanghai")
FIELDS = ("open", "high", "low", "close", "volume", "amount", "suspendFlag")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="20100101")
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    return parser.parse_args()


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def main() -> int:
    args = parse_args()
    for value in (args.start, args.end):
        datetime.strptime(value, "%Y%m%d")
    xtdata.download_history_data(
        SYMBOL,
        period="1d",
        start_time=args.start,
        end_time=args.end,
        incrementally=True,
    )
    result = xtdata.get_market_data_ex(
        field_list=list(FIELDS),
        stock_list=[SYMBOL],
        period="1d",
        start_time=args.start,
        end_time=args.end,
        count=-1,
        dividend_type="none",
        fill_data=False,
    )
    frame = result.get(SYMBOL, pd.DataFrame()).copy()
    if frame.empty:
        raise RuntimeError(f"QMT returned no rows for exact anchor {SYMBOL}")
    frame.index = frame.index.astype(str)
    if frame.index.duplicated().any():
        raise RuntimeError("QMT returned duplicate 399102.SZ daily rows")
    frame.index.name = "trade_date"
    frame = frame.sort_index().reset_index()
    if not frame["trade_date"].str.fullmatch(r"\d{8}").all():
        raise RuntimeError("unexpected QMT daily index format")
    csv_bytes = frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
    digest = hashlib.sha256(csv_bytes).hexdigest()
    atomic_write(args.output, csv_bytes)
    manifest = {
        "artifact": str(args.output),
        "captured_at": datetime.now(TZ).isoformat(),
        "symbol": SYMBOL,
        "identity": "创业板综",
        "provider": "QMT.xtquant",
        "period": "1d",
        "dividend_type": "none",
        "fill_data": False,
        "row_available_at": "normalized to completed session close; QMT has no field",
        "rows": len(frame),
        "first_date": str(frame["trade_date"].iloc[0]),
        "last_date": str(frame["trade_date"].iloc[-1]),
        "sha256": digest,
        "silent_fallback_allowed": False,
    }
    atomic_write(
        args.manifest,
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )
    print(json.dumps({"symbol": SYMBOL, "rows": len(frame), "sha256": digest}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
