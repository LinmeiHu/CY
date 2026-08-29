#!/usr/bin/env python3
"""Bounded QMT identity and daily-history probe for 399102.SZ only."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from xtquant import xtdata

SYMBOL = "399102.SZ"
TZ = ZoneInfo("Asia/Shanghai")
PRICE_FIELDS = ("open", "high", "low", "close")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="19900101")
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--extract-only", action="store_true")
    return parser.parse_args()


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return str(value)


def get_frame(start: str, end: str, basis: str) -> pd.DataFrame:
    result = xtdata.get_market_data_ex(
        field_list=[],
        stock_list=[SYMBOL],
        period="1d",
        start_time=start,
        end_time=end,
        count=-1,
        dividend_type=basis,
        fill_data=False,
    )
    frame = result.get(SYMBOL, pd.DataFrame())
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"QMT returned {type(frame).__name__}, expected DataFrame")
    frame = frame.copy()
    frame.index = frame.index.astype(str)
    if frame.index.duplicated().any():
        raise ValueError("QMT returned duplicate daily indices")
    return frame


def canonical_hash(frame: pd.DataFrame) -> str:
    ordered = frame.sort_index().copy()
    payload = ordered.to_csv(index=True, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sample_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    columns = [
        column
        for column in ("time", *PRICE_FIELDS, "volume", "amount", "preClose", "suspendFlag")
        if column in frame.columns
    ]
    selected = pd.concat([frame.head(2), frame.tail(2)]).loc[:, columns]
    selected = selected[~selected.index.duplicated(keep="first")]
    rows: list[dict[str, Any]] = []
    for index, row in selected.iterrows():
        item: dict[str, Any] = {"qmt_index": str(index)}
        for column, value in row.items():
            item[str(column)] = None if pd.isna(value) else json_safe(value)
        rows.append(item)
    return rows


def main() -> int:
    args = parse_args()
    datetime.strptime(args.start, "%Y%m%d")
    datetime.strptime(args.end, "%Y%m%d")
    if not args.extract_only:
        xtdata.download_history_data(
            SYMBOL,
            period="1d",
            start_time=args.start,
            end_time=args.end,
            incrementally=True,
        )

    detail = xtdata.get_instrument_detail(SYMBOL, iscomplete=True)
    raw = get_frame(args.start, args.end, "none")
    front = get_frame(args.start, args.end, "front")
    missing_front = raw.index.difference(front.index)
    common = raw.index.intersection(front.index)
    price_mismatches: dict[str, int] = {}
    for field in PRICE_FIELDS:
        if field not in raw.columns or field not in front.columns:
            price_mismatches[field] = -1
            continue
        left = pd.to_numeric(raw.loc[common, field], errors="coerce").to_numpy()
        right = pd.to_numeric(front.loc[common, field], errors="coerce").to_numpy()
        price_mismatches[field] = int(
            np.sum(~np.isclose(left, right, rtol=0.0, atol=0.0, equal_nan=True))
        )

    payload = {
        "probe_version": "chinext-v1-qmt-399102-probe-1",
        "captured_at": datetime.now(TZ).isoformat(),
        "request": {
            "symbol": SYMBOL,
            "period": "1d",
            "start": args.start,
            "end": args.end,
            "fill_data": False,
            "raw_dividend_type": "none",
            "comparison_dividend_type": "front",
            "bounded_single_symbol": True,
        },
        "xtdata_path": str(Path(xtdata.__file__).resolve()),
        "instrument_detail": json_safe(detail),
        "daily": {
            "rows": len(raw),
            "columns": [str(column) for column in raw.columns],
            "first_index": str(raw.index.min()) if len(raw) else None,
            "last_index": str(raw.index.max()) if len(raw) else None,
            "duplicate_indices": int(raw.index.duplicated().sum()),
            "canonical_csv_sha256": canonical_hash(raw),
            "front_missing_indices": len(missing_front),
            "raw_front_price_mismatches": price_mismatches,
            "sample_rows": sample_rows(raw),
            "provider_row_available_at_field": "available_at" in raw.columns,
        },
        "policy": {
            "expected_symbol": SYMBOL,
            "silent_fallback_allowed": False,
            "index_adjustment_interpretation": (
                "raw/front equality is probe evidence only; the canonical contract uses "
                "unadjusted index levels and never substitutes another index"
            ),
            "availability_interpretation": (
                "QMT response has no row-level available_at; a completed daily bar may be "
                "normalized no earlier than after that session close"
            ),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, args.output)
    print(json.dumps({"symbol": SYMBOL, "rows": len(raw), "output": str(args.output)}))
    return 0 if len(raw) else 2


if __name__ == "__main__":
    raise SystemExit(main())
