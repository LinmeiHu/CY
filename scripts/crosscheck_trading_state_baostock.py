"""Cross-check a small set of historical trading states against BaoStock.

The output is an audit/supplement candidate only.  Estimated states are never
promoted to strict PIT validity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import baostock as bs
import pandas as pd
from baostock_session import ensure_login, query_with_relogin

FIELDS = "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,pctChg,tradestatus,isST"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", nargs="+", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--decision-at", required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    decision = datetime.fromisoformat(a.decision_at).astimezone(ZoneInfo("Asia/Shanghai"))
    if pd.Timestamp(a.end).date() > decision.date():
        raise ValueError("end exceeds decision_at")
    ensure_login(bs)
    records: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    try:
        for symbol in a.symbols:
            code = symbol.lower().replace(".sz", "").replace(".sh", "")
            market = "sz" if symbol.upper().endswith(".SZ") else "sh"
            code = f"{market}.{code}"
            result = query_with_relogin(
                bs,
                lambda: bs.query_history_k_data_plus(
                    code, FIELDS, start_date=a.start, end_date=a.end, frequency="d", adjustflag="3"
                ),
                description="baostock.query_history_k_data_plus",
            )
            if result.error_code != "0":
                errors.append({"symbol": symbol, "error": f"{result.error_code} {result.error_msg}"})
                continue
            while result.next():
                row = dict(zip(FIELDS.split(","), result.get_row_data()))
                row["symbol"] = symbol.upper()
                records.append(row)
    finally:
        bs.logout()
    frame = pd.DataFrame(records)
    if not frame.empty:
        for col in ("open", "high", "low", "close", "preclose", "volume", "amount", "turn", "pctChg", "tradestatus"):
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        frame["date"] = pd.to_datetime(frame["date"])
        frame["available_at"] = frame["date"].dt.strftime("%Y-%m-%d") + "T15:00:00+08:00"
        frame["status_source"] = "baostock_history_k_data_plus"
        frame["status_confidence"] = "observed_interface"
        frame["snapshot_id"] = "BAOSTOCK-CROSSCHECK-" + hashlib.sha256(frame.to_csv(index=False).encode()).hexdigest()[:16].upper()
    a.output.parent.mkdir(parents=True, exist_ok=True)
    csv_path = a.output.with_suffix(".csv")
    frame.to_csv(csv_path, index=False)
    summary = []
    for symbol, group in frame.groupby("symbol") if not frame.empty else []:
        summary.append({"symbol": symbol, "rows": len(group), "active_rows": int(group["tradestatus"].eq(1).sum()), "suspended_rows": int(group["tradestatus"].eq(0).sum()), "st_rows": int(group["isST"].eq("1").sum()), "duplicate_dates": int(group["date"].duplicated().sum())})
    report = {"source": "BaoStock query_history_k_data_plus", "decision_at": decision.isoformat(), "request": {"symbols": a.symbols, "start": a.start, "end": a.end, "fields": FIELDS}, "rows": len(frame), "summary": summary, "errors": errors, "csv": str(csv_path.resolve()), "strict_policy": "observed BaoStock status is a candidate for PIT review; estimates and QMT-only values remain non-strict"}
    a.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
