"""Probe QMT's vectorized market-data API without touching trading APIs."""

import argparse
import json
import traceback
from pathlib import Path

from xtquant import xtdata


def load_codes(path):
    values = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        token = line.strip().split(",", 1)[0].upper()
        if token and token not in {"QMT_CODE", "SYMBOL", "CODE"}:
            values.append(token)
    return list(dict.fromkeys(values))


def value(item):
    try:
        return item.item()
    except Exception:
        return str(item)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--codes-file", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = {"ok": False}
    try:
        codes = load_codes(args.codes_file)
        payload = xtdata.get_market_data(
            field_list=["open", "high", "low", "close", "volume", "amount"],
            stock_list=codes,
            period="1m",
            start_time=args.start,
            end_time=args.end,
            count=-1,
            dividend_type="none",
            fill_data=False,
        )
        result = {"ok": True, "codes": len(codes), "fields": {}}
        for name, frame in (payload or {}).items():
            result["fields"][str(name)] = {
                "shape": list(frame.shape),
                "index": [str(item) for item in list(frame.index[:3])],
                "columns_head": [str(item) for item in list(frame.columns[:3])],
                "columns_tail": [str(item) for item in list(frame.columns[-3:])],
                "sample": [
                    [value(item) for item in row]
                    for row in frame.iloc[:2, :3].to_numpy()
                ],
            }
    except Exception:
        result = {"ok": False, "error": traceback.format_exc()}
    Path(args.out).write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
