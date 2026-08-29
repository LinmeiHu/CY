#!/usr/bin/env python3
"""Summarize ignored QD-007 probe payloads without promoting them to PIT input."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

PREFIX = re.compile(r"^sz\.(?:300|301)\d{3}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    samples: list[dict[str, object]] = []
    for manifest_path in sorted(args.input_root.glob("*/manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("requested_dates") != 1 or len(manifest.get("snapshots", [])) != 1:
            raise ValueError(f"expected one-date probe: {manifest_path}")
        metadata = manifest["snapshots"][0]
        day = str(metadata["trade_date"])
        snapshot_path = manifest_path.parent / f"snapshot_{day}.json"
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        rows = snapshot.get("rows", [])
        prefix_rows = [row for row in rows if PREFIX.fullmatch(str(row.get("code", "")))]
        counts: dict[str, int] = {}
        for row in prefix_rows:
            key = str(row.get("trade_status"))
            counts[key] = counts.get(key, 0) + 1
        samples.append(
            {
                "trade_date": day,
                "status": manifest.get("status"),
                "error_code": metadata.get("error_code"),
                "fields": metadata.get("request", {}).get("fields"),
                "all_market_rows": len(rows),
                "chinext_prefix_sanity_rows": len(prefix_rows),
                "prefix_trade_status_counts": counts,
                "metadata_payload_sha256": metadata.get("sha256"),
                "raw_snapshot_file_sha256": sha256_file(snapshot_path),
                "raw_snapshot_path": str(snapshot_path.resolve()),
            }
        )
    if not samples:
        raise ValueError("no BaoStock probe manifests found")
    payload = {
        "summary_version": "chinext-v1-baostock-qd007-probe-summary-1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "baostock.query_all_stock(day)",
        "registry_status": "DISCOVERY_ONLY",
        "samples": samples,
        "policy": {
            "current_survivor_used_for_historical_universe": False,
            "prefix_is_membership_fact": False,
            "activated_for_universe_construction": False,
            "limitations": [
                "three bounded dates do not establish complete historical coverage",
                "code prefix is a sanity count only, not board membership",
                "response has no list_date or delist_date",
                "code_name is not used to infer ST or risk-warning history",
                "tradeStatus is observed data but does not prove side-specific tradability",
            ],
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, args.output)
    print(json.dumps({"samples": len(samples), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
