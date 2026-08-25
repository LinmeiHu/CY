"""Audit BaoStock-no-return symbols against the local quant QMT minute lake."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", required=True, type=Path)
    p.add_argument("--qmt-root", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()
    symbols = sorted({x.strip().upper() for x in a.symbols.read_text().splitlines() if x.strip()})
    rows: list[dict[str, object]] = []
    for symbol in symbols:
        code = symbol.split(".")[0]
        path = a.qmt_root / f"{code}.parquet"
        rec: dict[str, object] = {"symbol": symbol, "path": str(path), "exists": path.exists()}
        if path.exists():
            frame = pd.read_parquet(path)
            frame["bar_end_time"] = pd.to_datetime(frame["bar_end_time"], errors="coerce")
            prices = pd.to_numeric(frame["close"], errors="coerce")
            rec.update({
                "rows": len(frame),
                "min_trade_date": str(frame["trade_date"].min()),
                "max_trade_date": str(frame["trade_date"].max()),
                "nonzero_price_rows": int((prices > 0).sum()),
                "suspend_rows": int((frame["suspendFlag"] == 1).sum()),
                "nonzero_days": int(frame.loc[prices > 0, "trade_date"].nunique()),
                "source": sorted(frame["source"].dropna().astype(str).unique().tolist()),
                "usable_for_daily_reconstruction": bool((prices > 0).any()),
            })
        else:
            rec.update({"rows": 0, "usable_for_daily_reconstruction": False})
        rows.append(rec)
    report = {"scope": "13 BaoStock-no-return symbols", "source_policy": "QMT minute data is evidence for reconstruction only; no automatic strict promotion", "rows": rows}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(a.output), "symbols": len(rows), "usable": sum(bool(x.get("usable_for_daily_reconstruction")) for x in rows)}))


if __name__ == "__main__":
    main()
