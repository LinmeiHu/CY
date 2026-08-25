"""Freeze a point-in-time BaoStock daily snapshot for a single A-share.

This collector deliberately separates acquisition from research activation.  It
writes the exact string response plus an immutable manifest; callers must then
register the snapshot before it can feed state generation.
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

FIELDS = (
    "date,code,open,high,low,close,preclose,volume,amount,adjustflag,"
    "turn,pctChg,tradestatus,isST"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", required=True, help="BaoStock code, e.g. sz.000820")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD; never after decision date")
    parser.add_argument("--decision-at", required=True, help="ISO-8601 timestamp")
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    shanghai = ZoneInfo("Asia/Shanghai")
    decision_at = datetime.fromisoformat(args.decision_at).astimezone(shanghai)
    end_date = datetime.strptime(args.end, "%Y-%m-%d").date()
    if end_date > decision_at.date():
        raise ValueError("end date exceeds decision_at")
    if end_date == decision_at.date() and decision_at.hour < 15:
        raise ValueError("same-day daily bar is unavailable before 15:00 Asia/Shanghai")

    ensure_login(bs)
    try:
        result = query_with_relogin(
            bs,
            lambda: bs.query_history_k_data_plus(
                args.code,
                FIELDS,
                start_date=args.start,
                end_date=args.end,
                frequency="d",
                adjustflag="3",
            ),
            description="baostock.query_history_k_data_plus",
        )
        if result.error_code != "0":
            raise RuntimeError(
                f"BaoStock query failed: {result.error_code} {result.error_msg}"
            )
        rows: list[list[str]] = []
        while result.error_code == "0" and result.next():
            rows.append(result.get_row_data())
    finally:
        bs.logout()

    frame = pd.DataFrame(rows, columns=FIELDS.split(","))
    if frame.empty:
        raise RuntimeError("empty BaoStock response")
    if frame["date"].duplicated().any():
        raise RuntimeError("duplicate dates in BaoStock response")
    if frame["adjustflag"].ne("3").any():
        raise RuntimeError("response is not unadjusted")
    if frame["date"].max() > args.end:
        raise RuntimeError("response contains a row after requested end date")

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    csv_path = output_dir / "response.csv"
    # UTF-8/LF and stable quoting make the content hash reproducible.
    frame.to_csv(csv_path, index=False, lineterminator="\n")
    collected_at = datetime.now(shanghai).isoformat(timespec="seconds")
    csv_hash = sha256(csv_path)
    snapshot_id = (
        f"BAOSTOCK-{args.code.upper()}-{args.end.replace('-', '')}-"
        f"{csv_hash[:16].upper()}"
    )
    manifest = {
        "schema_version": "1.0",
        "snapshot_id": snapshot_id,
        "collected_at": collected_at,
        "decision_at": decision_at.isoformat(timespec="seconds"),
        "source": "BaoStock query_history_k_data_plus",
        "request": {
            "code": args.code,
            "fields": FIELDS,
            "start_date": args.start,
            "end_date": args.end,
            "frequency": "d",
            "adjustflag": "3",
        },
        "response": {
            "path": str(csv_path),
            "sha256": csv_hash,
            "rows": len(frame),
            "start": str(frame["date"].min()),
            "end": str(frame["date"].max()),
            "columns": list(frame.columns),
        },
        "availability_policy": (
            "daily records become available at 15:00:00+08:00 on trade_date; "
            "suspended rows carry tradestatus=0 and do not update chip mass"
        ),
        "quality_checks": {
            "nonempty": True,
            "duplicate_dates": 0,
            "unadjusted_only": True,
            "no_rows_after_end": True,
        },
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({**manifest, "manifest_sha256": sha256(manifest_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
