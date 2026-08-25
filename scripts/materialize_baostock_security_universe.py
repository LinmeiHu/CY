#!/usr/bin/env python3
"""Materialize date-effective BaoStock security snapshots for PIT-B review.

This is a discovery/materialization step only.  It deliberately does not alter
the authoritative registry or activate the result as a research input.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import duckdb
from baostock_session import ensure_login, query_with_relogin


def args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2010-01-01")
    p.add_argument("--end", default="2017-12-31")
    p.add_argument("--calendar", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--sleep", type=float, default=0.05)
    p.add_argument("--max-dates", type=int, default=0)
    p.add_argument("--timeout", type=int, default=20)
    p.add_argument("--failed-audit", help="retry only dates listed in an existing audit JSON")
    return p.parse_args()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    ns = args()
    out = Path(ns.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    db = duckdb.connect()
    dates = [
        row[0].strftime("%Y-%m-%d")
        for row in db.execute(
            "select trade_date from read_parquet(?) where trade_date between ? and ? order by trade_date",
            [ns.calendar, ns.start, ns.end],
        ).fetchall()
    ]
    if ns.failed_audit:
        failed = json.loads(Path(ns.failed_audit).read_text(encoding="utf-8")).get("errors", [])
        requested = {str(item["date"]) for item in failed if item.get("reason")}
        dates = [day for day in dates if day in requested]
    if ns.max_dates:
        dates = dates[: ns.max_dates]
    if not dates:
        raise SystemExit("no calendar dates in requested interval")

    import baostock as bs  # type: ignore[import-not-found]

    captured_at = datetime.now(UTC).isoformat()
    class LoginTimeout(Exception):
        pass

    def login_alarm(_signum: int, _frame: object) -> None:
        raise LoginTimeout(f"login timeout after {ns.timeout}s")

    old_login_handler = signal.signal(signal.SIGALRM, login_alarm)
    signal.alarm(ns.timeout)
    try:
        ensure_login(bs)
    except LoginTimeout as exc:
        raise SystemExit(str(exc)) from exc
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_login_handler)

    try:
        manifest = {
            "asset_id": "QD-007",
            "source": "baostock.query_all_stock",
            "requested_start": dates[0],
            "requested_end": dates[-1],
            "requested_dates": len(dates),
            "captured_at": captured_at,
            "python": sys.version,
            "status": "DISCOVERY_ONLY",
            "snapshots": [],
        }
        for i, day in enumerate(dates, 1):
            target = out / f"snapshot_{day}.json"
            if target.exists():
                raw = target.read_bytes()
                payload = json.loads(raw)
                if payload.get("metadata", {}).get("sha256") and payload.get("metadata", {}).get("error_code") == "0":
                    manifest["snapshots"].append(payload["metadata"])
                    continue
            class QueryTimeout(Exception):
                pass

            def alarm_handler(_signum: int, _frame: object) -> None:
                raise QueryTimeout(f"query timeout after {ns.timeout}s")

            old_handler = signal.signal(signal.SIGALRM, alarm_handler)
            signal.alarm(ns.timeout)
            try:
                rs = query_with_relogin(
                    bs,
                    lambda: bs.query_all_stock(day=day),
                    description="baostock.query_all_stock",
                )
            except QueryTimeout as exc:
                metadata = {
                    "trade_date": day,
                    "request": {"day": day, "fields": ["code", "tradeStatus", "code_name"]},
                    "captured_at": datetime.now(UTC).isoformat(),
                    "error_code": "TIMEOUT",
                    "error_msg": str(exc),
                    "row_count": 0,
                }
                body = {"metadata": metadata, "rows": []}
                canonical = (json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
                metadata["sha256"] = sha256_bytes(canonical)
                encoded = (json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
                target.with_suffix(".json.tmp").write_bytes(encoded)
                os.replace(target.with_suffix(".json.tmp"), target)
                manifest["snapshots"].append(metadata)
                continue
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)
            rows = []
            if rs.error_code == "0":
                while rs.next():
                    code, trade_status, name = rs.get_row_data()
                    rows.append({"code": code, "trade_status": trade_status, "code_name": name})
            metadata = {
                "trade_date": day,
                "request": {"day": day, "fields": list(rs.fields)},
                "captured_at": datetime.now(UTC).isoformat(),
                "error_code": rs.error_code,
                "error_msg": rs.error_msg,
                "row_count": len(rows),
            }
            body = {"metadata": metadata, "rows": rows}
            canonical = (json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
            metadata["sha256"] = sha256_bytes(canonical)
            encoded = (json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
            tmp = target.with_suffix(".json.tmp")
            tmp.write_bytes(encoded)
            os.replace(tmp, target)
            manifest["snapshots"].append(metadata)
            if i % 100 == 0:
                print(f"materialized {i}/{len(dates)}", flush=True)
            time.sleep(ns.sleep)
        manifest["completed_at"] = datetime.now(UTC).isoformat()
        manifest["success_dates"] = sum(x["error_code"] == "0" for x in manifest["snapshots"])
        manifest["failed_dates"] = len(manifest["snapshots"]) - manifest["success_dates"]
        manifest_raw = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        (out / "manifest.json").write_bytes(manifest_raw)
        print(json.dumps({k: manifest[k] for k in ("requested_dates", "success_dates", "failed_dates")}, ensure_ascii=False))
    finally:
        bs.logout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
