#!/usr/bin/env python3
"""Create a bounded metadata/capability probe for registered local ChinNext facts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow.parquet as pq

DEFAULT_MASTER = Path(
    "/Users/linmei/Downloads/workspace/quant/data/lake/meta/security_master.parquet"
)
DEFAULT_CALENDAR = Path(
    "/Users/linmei/Downloads/workspace/quant/data/lake/meta/trade_calendar.parquet"
)
DEFAULT_CY006_2020 = Path(
    "/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/"
    "daily/partition_year=2020/data_0.parquet"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=Path("configs/data_asset_registry.json"))
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--calendar", type=Path, default=DEFAULT_CALENDAR)
    parser.add_argument("--cy006-2020", type=Path, default=DEFAULT_CY006_2020)
    parser.add_argument("--current-survivor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    assets = {item["asset_id"]: item for item in registry["assets"]}
    master = pd.read_parquet(args.master)
    gem = master[(master["exchange"] == "SZ") & (master["board"] == "GEM")]
    calendar = pd.read_parquet(args.calendar)
    survivor = json.loads(args.current_survivor.read_text(encoding="utf-8"))
    connection = duckdb.connect()
    aggregate = connection.execute(
        """
        SELECT
          count(*) AS rows,
          count(DISTINCT symbol) AS symbols,
          sum(CASE WHEN is_st THEN 1 ELSE 0 END) AS is_st_rows,
          sum(CASE WHEN trade_status <> 1 THEN 1 ELSE 0 END) AS nontrading_rows,
          sum(CASE WHEN buy_blocked_open THEN 1 ELSE 0 END) AS buy_blocked_rows,
          sum(CASE WHEN sell_blocked_open THEN 1 ELSE 0 END) AS sell_blocked_rows,
          sum(CASE WHEN NOT historical_identity_valid THEN 1 ELSE 0 END)
            AS historical_identity_invalid_rows,
          sum(CASE WHEN NOT hard_valid THEN 1 ELSE 0 END) AS hard_invalid_rows,
          sum(CASE WHEN available_at IS NULL THEN 1 ELSE 0 END) AS missing_available_at_rows,
          count(DISTINCT snapshot_id) AS snapshot_ids,
          min(trade_date) AS first_date,
          max(trade_date) AS last_date,
          median(amount / nullif(close * volume, 0))
            FILTER (WHERE volume > 0 AND amount > 0 AND close > 0 AND hard_valid)
            AS amount_close_volume_ratio_median
        FROM read_parquet(?)
        WHERE symbol LIKE '300%.SZ' OR symbol LIKE '301%.SZ'
        """,
        [str(args.cy006_2020)],
    ).fetchone()
    keys = [item[0] for item in connection.description]
    cy006_summary = dict(zip(keys, aggregate, strict=True))
    for key, value in list(cy006_summary.items()):
        if hasattr(value, "isoformat"):
            cy006_summary[key] = value.isoformat()
    known_list_dates = sum(
        item.get("master_list_date") is not None for item in survivor.get("records", [])
    )
    payload = {
        "probe_version": "chinext-v1-local-data-capability-probe-1",
        "generated_at": datetime.now(UTC).isoformat(),
        "registry": {
            "path": str(args.registry.resolve()),
            "sha256": sha256_file(args.registry),
            "qd002": {
                "status": assets["QD-002"]["status"],
                "schema_and_units": assets["QD-002"]["schema_and_units"],
                "manifest_sha256": assets["QD-002"]["lineage"]["manifest_sha256"],
            },
            "qd003": {
                "status": assets["QD-003"]["status"],
                "indices": assets["QD-003"]["coverage"]["indices"],
                "contains_399102": "sz399102" in assets["QD-003"]["coverage"]["indices"],
            },
            "qd007": {
                "status": assets["QD-007"]["status"],
                "physical_state": assets["QD-007"]["physical_state"],
                "blocked_uses": assets["QD-007"]["blocked_uses"],
            },
            "cy006": {
                "status": assets["CY-006"]["status"],
                "coverage": assets["CY-006"]["coverage"],
                "manifest_sha256": assets["CY-006"]["lineage"]["manifest_sha256"],
            },
        },
        "current_master": {
            "path": str(args.master.resolve()),
            "sha256": sha256_file(args.master),
            "schema": [field.name for field in pq.read_schema(args.master)],
            "rows": len(master),
            "gem_rows": len(gem),
            "gem_listed_rows": int(gem["status"].eq("listed").sum()),
            "gem_list_date_known_rows": int(gem["list_date"].notna().sum()),
            "gem_delist_date_known_rows": int(gem["delist_date"].notna().sum()),
            "point_in_time_accepted": False,
        },
        "current_survivor": {
            "path": str(args.current_survivor.resolve()),
            "point_in_time_status": survivor.get("point_in_time_status"),
            "symbol_count": survivor.get("symbol_count"),
            "list_date_known_rows": int(known_list_dates),
            "historical_universe_use_allowed": False,
        },
        "calendar": {
            "path": str(args.calendar.resolve()),
            "sha256": sha256_file(args.calendar),
            "rows": len(calendar),
            "unique_dates": int(calendar["trade_date"].nunique()),
            "first_date": str(calendar["trade_date"].min()),
            "last_date": str(calendar["trade_date"].max()),
        },
        "cy006_2020_chinext_prefix_bounded": cy006_summary,
        "interpretation": {
            "prefix_is_membership_fact": False,
            "amount_unit_evidence": (
                "median amount/(close*volume) near 1 supports amount CNY with volume shares"
            ),
            "risk_warning_mapping_complete": False,
            "suspension_and_daily_state_available": True,
            "universe_construction_authorized": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, args.output)
    print(json.dumps({"output": str(args.output), "cy006_rows": cy006_summary["rows"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
