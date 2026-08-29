from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from export_v6_from_qmt import qmt_frame
from v6_data_common import (
    MANIFEST_DIR,
    QMT_DATA_ROOT,
    REPO_ROOT,
    atomic_write_json,
    atomic_write_parquet,
    sha256_file,
)

TZ = ZoneInfo("Asia/Shanghai")
AVAILABILITY_PATH = QMT_DATA_ROOT / "execution_availability" / "critical_execution.parquet"
OUTPUT_PATH = QMT_DATA_ROOT / "open_gap_audit" / "first_real_bar_after_09_30.parquet"
SUMMARY_PATH = QMT_DATA_ROOT / "open_gap_audit" / "summary.json"
AVAILABILITY_MANIFEST_PATH = MANIFEST_DIR / "v6_open_execution_availability.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit the first real QMT 1m bar after missing V6 09:30 bars"
    )
    parser.add_argument("--availability", type=Path, default=AVAILABILITY_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", type=Path, default=SUMMARY_PATH)
    parser.add_argument(
        "--availability-manifest",
        type=Path,
        default=AVAILABILITY_MANIFEST_PATH,
    )
    return parser.parse_args()


def audit_symbol(symbol: str, dates: list[str]) -> list[dict[str, object]]:
    start = min(dates).replace("-", "")
    end = max(dates).replace("-", "")
    raw = qmt_frame(symbol, "1m", start, end, "none")
    front = qmt_frame(symbol, "1m", start, end, "front")
    rows: list[dict[str, object]] = []

    for trade_date in dates:
        prefix = trade_date.replace("-", "")
        lower = f"{prefix}093000"
        upper = f"{prefix}150000"
        day = raw[(raw.index > lower) & (raw.index <= upper)].sort_index().copy()
        valid = pd.Series(True, index=day.index)
        for column in ["open", "high", "low", "close", "volume", "amount"]:
            values = pd.to_numeric(day[column], errors="coerce")
            valid &= np.isfinite(values) & values.gt(0)
        valid &= pd.to_numeric(day["suspendFlag"], errors="coerce").fillna(1).eq(0)
        real = day[valid]
        if real.empty:
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "audit_status": "NO_REAL_BAR_AFTER_09_30",
                }
            )
            continue

        key = str(real.index[0])
        raw_row = real.iloc[0]
        if key not in front.index:
            raise ValueError(f"front-adjusted QMT frame missing {symbol} {key}")
        front_row = front.loc[key]
        parsed = datetime.strptime(key, "%Y%m%d%H%M%S").replace(tzinfo=TZ)
        rows.append(
            {
                "symbol": symbol,
                "trade_date": trade_date,
                "audit_status": "FIRST_REAL_BAR_FOUND",
                "first_bar_datetime": parsed.isoformat(),
                "qmt_index": key,
                "minutes_after_09_30": int((parsed.hour * 60 + parsed.minute) - (9 * 60 + 30)),
                "raw_open": float(raw_row["open"]),
                "raw_close": float(raw_row["close"]),
                "pre_adj_open": float(front_row["open"]),
                "pre_adj_close": float(front_row["close"]),
                "volume_raw": float(raw_row["volume"]),
                "amount_cny": float(raw_row["amount"]),
                "qmt_suspend_flag": float(raw_row["suspendFlag"]),
                "available_at": parsed.isoformat(),
                "sensitivity_only": True,
                "accepted_as_exact_supermind_fill": False,
            }
        )
    return rows


def main() -> int:
    args = parse_args()
    availability = pd.read_parquet(args.availability)
    gaps = availability[~availability["executable_09_30"]].copy()
    rows: list[dict[str, object]] = []
    for symbol, frame in gaps.groupby("symbol", sort=True):
        dates = sorted(str(value) for value in frame["trade_date"])
        rows.extend(audit_symbol(str(symbol), dates))

    audit = pd.DataFrame(rows).sort_values(["trade_date", "symbol"]).reset_index(drop=True)
    capture_at = datetime.now(TZ).isoformat()
    audit["capture_at"] = capture_at
    audit["snapshot_id"] = f"qmt-open-gap-audit-{datetime.now(TZ).strftime('%Y%m%dT%H%M%S%z')}"
    audit["source"] = "QMT XtData 1m via running Guojin MiniQmt"
    audit["source_endpoint"] = "MiniQmt local RPC on dynamic loopback port"
    audit["fill_data"] = False
    atomic_write_parquet(audit, args.output)
    summary = {
        "audit_version": "v6-qmt-open-gap-audit-1",
        "capture_at": capture_at,
        "availability_path": (
            args.availability.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
        ),
        "availability_sha256": sha256_file(args.availability),
        "output_path": args.output.resolve().relative_to(REPO_ROOT.resolve()).as_posix(),
        "output_sha256": sha256_file(args.output),
        "gap_count": len(audit),
        "status_counts": {
            str(key): int(value) for key, value in audit["audit_status"].value_counts().items()
        },
        "first_bar_delay_counts": {
            str(int(key)): int(value)
            for key, value in audit["minutes_after_09_30"].dropna().value_counts().items()
        },
        "diagnostic_only": True,
        "primary_policy_unchanged": (
            "MISSING_OR_INVALID_09_30_BAR => NO_FILL_RETRY_NEXT_SESSION"
        ),
        "accepted_as_exact_supermind_fill": False,
    }
    atomic_write_json(args.summary, summary)
    availability_manifest = json.loads(args.availability_manifest.read_text(encoding="utf-8"))
    if availability_manifest["output_sha256"] != summary["availability_sha256"]:
        raise ValueError("availability manifest and audited Parquet hashes do not match")
    availability_manifest["qmt_gap_audit"] = summary
    atomic_write_json(args.availability_manifest, availability_manifest)
    print(f"QMT_OPEN_GAPS_AUDITED {len(audit)}")
    for key, value in sorted(summary["status_counts"].items()):
        print(f"{key} {value}")
    print("PRIMARY_POLICY_UNCHANGED YES")
    print("EXACT_SUPERMIND_FILL_ACCEPTED NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
