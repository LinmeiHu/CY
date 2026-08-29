from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd
from export_v6_from_qmt import (
    TZ,
    assign_row_status,
    atomic_json,
    atomic_parquet,
    combine_bases,
    qmt_frame,
    sha256_file,
)
from xtquant import xtdata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    return parser.parse_args()


def normalize_fallback(symbol: str, raw: pd.DataFrame, front: pd.DataFrame) -> pd.DataFrame:
    raw = raw[raw.index.str[-6:].isin(["093500", "150000"])].copy()
    front = front.reindex(raw.index).copy()
    combined = combine_bases(raw, front)
    if combined.empty:
        return combined
    parsed = pd.to_datetime(combined["qmt_index"], format="%Y%m%d%H%M%S")
    combined.insert(0, "trade_date", parsed.dt.date)
    combined.insert(
        1,
        "datetime",
        parsed.map(lambda value: value.replace(tzinfo=TZ).isoformat()),
    )
    combined.insert(2, "symbol", symbol)
    combined.insert(3, "raw_code", symbol.split(".")[0])
    combined.insert(4, "exchange", symbol.split(".")[1])
    combined.insert(5, "source_5m_time", combined["qmt_index"].str[-6:])
    combined.insert(6, "row_status", assign_row_status(combined))

    rows = []
    open_rows = combined[combined["source_5m_time"].eq("093500")].copy()
    open_rows["bar_role"] = "OPEN_BAR_09_30"
    open_rows["raw_close"] = open_rows["raw_open"]
    open_rows["pre_adj_close"] = open_rows["pre_adj_open"]
    open_rows["fallback_semantics"] = "09:35 5m bar open used as session-open proxy"
    rows.append(open_rows)

    final_rows = combined[combined["source_5m_time"].eq("150000")].copy()
    signal_rows = final_rows.copy()
    signal_rows["bar_role"] = "PSEUDO_CLOSE_14_57_OPEN"
    signal_rows["fallback_semantics"] = (
        "15:00 5m bar open approximates unavailable exact 14:57 1m bar open"
    )
    rows.append(signal_rows)
    final_rows["bar_role"] = "FINAL_CLOSE_BAR"
    final_rows["fallback_semantics"] = "15:00 5m bar close used as final close"
    rows.append(final_rows)

    output = pd.concat(rows, ignore_index=True)
    output["volume_unit"] = "lot_100_shares"
    output["volume_shares"] = output["volume_raw"] * 100.0
    output["timezone"] = "Asia/Shanghai"
    output["source"] = "QMT XtData 5m fallback via running Guojin MiniQmt"
    output["adjustment_status"] = "qmt_front_supermind_pre_equivalence_unverified"
    output["opening_auction_status"] = "5m_fallback_not_exact_1m"
    output["available_at"] = output["datetime"]
    output["capture_at"] = datetime.now(TZ).isoformat()
    output["snapshot_id"] = f"qmt-5m-fallback-{datetime.now(TZ).strftime('%Y%m%dT%H%M%S%z')}"
    output["source_endpoint"] = "MiniQmt local RPC on dynamic loopback port"
    return output.sort_values(["trade_date", "bar_role"]).reset_index(drop=True)


def main() -> int:
    args = parse_args()
    summary = {
        "status": "PASS",
        "request": {
            "start": args.start,
            "end": args.end,
            "symbols": args.symbols,
            "period": "5m",
        },
        "limitations": [
            "exact QMT 1m history was unavailable for these symbols",
            "14:57 is approximated by the open of the QMT 5m bar timestamped 15:00",
        ],
        "results": {},
    }
    for symbol in args.symbols:
        xtdata.download_history_data(
            symbol,
            period="5m",
            start_time=args.start,
            end_time=args.end,
            incrementally=True,
        )
        raw = qmt_frame(symbol, "5m", args.start, args.end, "none")
        front = qmt_frame(symbol, "5m", args.start, args.end, "front")
        frame = normalize_fallback(symbol, raw, front)
        if frame.empty:
            raise ValueError(f"QMT returned no 5m fallback rows for {symbol}")
        path = args.output / "minute_critical" / f"symbol={symbol}" / "critical.parquet"
        atomic_parquet(path, frame)
        summary["results"][symbol] = {
            "rows": len(frame),
            "first_date": str(frame["trade_date"].min()),
            "last_date": str(frame["trade_date"].max()),
            "sha256": sha256_file(path),
        }
        print(f"FALLBACK {symbol} rows={len(frame)}")
    summary_path = args.output / "qmt_5m_critical_fallback_summary.json"
    atomic_json(summary_path, summary)
    print(f"SUMMARY {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
