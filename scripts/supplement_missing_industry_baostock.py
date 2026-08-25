#!/usr/bin/env python3
"""Supplement missing historical industry rows from dated BaoStock snapshots.

This is a bounded data-ingest step only.  It never backfills a current
classification into history: BaoStock's update_date must be before the
decision date, and every accepted row carries capture metadata.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from baostock_session import ensure_login, query_with_relogin


def args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    symbols = p.add_mutually_exclusive_group(required=True)
    symbols.add_argument("--symbols", nargs="+")
    symbols.add_argument("--all-a-shares", action="store_true")
    p.add_argument("--dates", nargs="+", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--snapshot-id", required=True)
    return p.parse_args()


def digest(fields: list[str], rows: list[list[str]]) -> str:
    body = json.dumps({"fields": fields, "rows": rows}, ensure_ascii=False,
                      separators=(",", ":")).encode()
    return hashlib.sha256(body).hexdigest()


def main() -> int:
    a = args()
    wanted = None if a.all_a_shares else {s.split(".")[0] for s in a.symbols}
    try:
        import baostock as bs
    except ImportError as exc:
        raise RuntimeError("baostock is required") from exc

    captured = datetime.now(UTC).isoformat()
    records: list[dict[str, object]] = []
    requests: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []
    try:
        ensure_login(bs)
    except RuntimeError as exc:
        failures.append({"request": "login", "error": str(exc)})
    else:
        try:
            for asof in a.dates:
                try:
                    rs = query_with_relogin(
                        bs,
                        lambda: bs.query_stock_industry(date=asof),
                        description="baostock.query_stock_industry",
                    )
                    fields = list(rs.fields)
                    rows: list[list[str]] = []
                    while rs.error_code == "0" and rs.next():
                        rows.append(rs.get_row_data())
                    response = {"asof_date": asof, "row_count": len(rows),
                                "response_sha256": digest(fields, rows)}
                    requests.append(response)
                    if rs.error_code != "0":
                        failures.append({"request": asof, "error": rs.error_msg})
                        continue
                    indexes = {name: fields.index(name) for name in
                               ("updateDate", "code", "industry", "industryClassification")}
                    for row in rows:
                        # BaoStock returns ``sh.600000``/``sz.000001``; the
                        # target list uses the numeric security code.
                        symbol = row[indexes["code"]].split(".")[-1]
                        update = row[indexes["updateDate"]]
                        industry = row[indexes["industry"]].strip()
                        code = row[indexes["code"]]
                        is_a_share = (
                            code.startswith("sh.")
                            and symbol.startswith(("600", "601", "603", "605", "688", "689"))
                        ) or (
                            code.startswith("sz.")
                            and symbol.startswith(("000", "001", "002", "003", "300", "301"))
                        )
                        if (
                            (wanted is not None and symbol not in wanted)
                            or (wanted is None and not is_a_share)
                            or not industry
                            or not update
                        ):
                            continue
                        if update >= asof:
                            continue
                        records.append({
                            "symbol": symbol,
                            "decision_date": asof,
                            "industry": industry,
                            "source_update_date": update,
                            "available_at": captured,
                            "snapshot_id": a.snapshot_id,
                            "source": "baostock_query_stock_industry",
                            "industry_classification": row[indexes["industryClassification"]],
                            "response_sha256": response["response_sha256"],
                        })
                except Exception as exc:
                    failures.append({"request": asof, "error": f"{type(exc).__name__}: {exc}"})
        finally:
            bs.logout()

    a.output.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(records)
    if not frame.empty:
        frame = frame.drop_duplicates(["symbol", "decision_date"])
        frame.to_parquet(a.output, index=False, compression="zstd")
    payload = {
        "status": "pass" if records else "fail",
        "asset_id": "QD-008-BS-SUPPLEMENT",
        "captured_at": captured,
        "snapshot_id": a.snapshot_id,
        "requested_symbols": (
            "ALL_SH_SZ_A_SHARES" if wanted is None else sorted(wanted)
        ),
        "requested_dates": a.dates,
        "accepted_rows": len(records),
        "accepted_symbols": sorted({str(r["symbol"]) for r in records}),
        "request_evidence": requests,
        "failures": failures,
        "output": str(a.output.resolve()),
        "pit_rule": "source_update_date < decision_date",
        "grade": "B_RESEARCH_ONLY",
        "current_snapshot_backfill": False,
    }
    a.output.with_suffix(".manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if records else 1


if __name__ == "__main__":
    raise SystemExit(main())
