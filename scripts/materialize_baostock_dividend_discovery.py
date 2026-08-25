"""Materialize BaoStock historical dividend/bonus responses as discovery evidence.

This output is never a research input by itself: BaoStock does not provide a
historical revision-vintage chain.  The raw response and request metadata are
kept so the limitation is explicit and auditable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import date
from pathlib import Path

import baostock as bs
from baostock_session import ensure_login, query_with_relogin


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--start-year", type=int, default=2010)
    ap.add_argument("--end-year", type=int, default=2017)
    ap.add_argument("--sleep", type=float, default=0.05)
    ap.add_argument("--limit-codes", type=int)
    args = ap.parse_args()
    if args.codes.suffix == ".json":
        payload = json.loads(args.codes.read_text())
        codes = sorted({str(row.get("code", "")) for row in payload.get("rows", []) if row.get("code")})
    else:
        codes = sorted({x.strip() for x in args.codes.read_text().splitlines() if x.strip()})
    if args.limit_codes is not None:
        codes = codes[: args.limit_codes]
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "manifest.json"
    records: list[dict[str, object]] = []
    ensure_login(bs)
    try:
        for code in codes:
            for year in range(args.start_year, args.end_year + 1):
                key = f"{code.replace('.', '_')}_{year}"
                path = out / f"dividend_{key}.json"
                if path.exists():
                    continue
                try:
                    rs = query_with_relogin(
                        bs,
                        lambda: bs.query_dividend_data(code=code, year=str(year), yearType="report"),
                        description="baostock.query_dividend_data",
                    )
                    rows = rs.get_data().to_dict(orient="records") if rs.error_code == "0" else []
                    payload = {
                        "request": {"code": code, "year": year, "year_type": "report"},
                        "captured_at": date.today().isoformat(),
                        "source": "baostock.query_dividend_data",
                        "error_code": str(rs.error_code),
                        "error_msg": str(rs.error_msg),
                        "fields": list(rs.fields or []),
                        "rows": rows,
                    }
                except Exception as exc:  # preserve failed request evidence
                    payload = {
                        "request": {"code": code, "year": year, "year_type": "report"},
                        "captured_at": date.today().isoformat(),
                        "source": "baostock.query_dividend_data",
                        "error_code": "exception",
                        "error_msg": repr(exc),
                        "fields": [],
                        "rows": [],
                    }
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
                records.append({"path": str(path), "sha256": sha256(path), "code": code, "year": year,
                                "error_code": payload["error_code"], "rows": len(payload["rows"])})
                time.sleep(args.sleep)
    finally:
        bs.logout()
    manifest = {
        "asset_id": "QD-011-BAOSTOCK-DIVIDEND-DISCOVERY-2010-2017",
        "status": "DISCOVERY_ONLY",
        "pit_grade": "B",
        "revision_history_complete": False,
        "captured_at": date.today().isoformat(),
        "source": "BaoStock query_dividend_data",
        "request_count": len(records),
        "records": records,
        "blocked_uses": ["state_generation", "signals", "sizing", "execution", "backtests", "performance_claims"],
        "limitation": "BaoStock response is a current query result without historical supplier revision vintages.",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"requests": len(records), "output": str(out), "status": manifest["status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
