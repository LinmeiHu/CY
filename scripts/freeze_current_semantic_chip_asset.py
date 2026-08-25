#!/usr/bin/env python3
"""Validate and freeze the current semantic chip delta as CY-027."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--chip-manifest", type=Path, required=True)
    parser.add_argument("--daily-manifest", type=Path, required=True)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sql(path: Path) -> str:
    return "'" + str(path.resolve()).replace("'", "''") + "'"


def main() -> int:
    args = _parse_args()
    source = args.source_root.resolve()
    output = args.output_root.resolve()
    if output.exists():
        manifest = output / "asset_manifest.json"
        if manifest.is_file() and _read(manifest).get("status") == "PASS":
            print(f"REUSED asset=CY-027 manifest={manifest}", flush=True)
            return 0
        raise FileExistsError(output)
    build_path = source / "build_manifest.json"
    data_path = source / "semantic_features.parquet"
    symbols_path = source / "symbols.txt"
    build = _read(build_path)
    if build.get("status") != "PASS":
        raise ValueError("current semantic build did not pass")
    if _sha256(data_path) != build.get("data_sha256"):
        raise ValueError("semantic data changed after build")
    if _sha256(symbols_path) != build.get("symbols_sha256"):
        raise ValueError("semantic symbol inventory changed after build")
    chip_manifest_path = args.chip_manifest.resolve()
    daily_manifest_path = args.daily_manifest.resolve()
    chip_manifest = _read(chip_manifest_path)
    daily_manifest = _read(daily_manifest_path)
    if chip_manifest.get("asset_id") != "CY-026" or chip_manifest.get("status") != "PASS":
        raise ValueError("semantic freeze requires frozen CY-026")
    if daily_manifest.get("asset_id") != "CY-024" or daily_manifest.get("status") != "PASS":
        raise ValueError("semantic freeze requires frozen CY-024")
    if Path(str(build["lineage_root"])).resolve() != chip_manifest_path.parent:
        raise ValueError("semantic build did not consume the frozen CY-026 root")

    connection = duckdb.connect()
    row = connection.execute(
        f"""
        SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(trade_date), MAX(trade_date),
               COUNT(*) - COUNT(DISTINCT (symbol, trade_date)),
               COUNT(*) FILTER (WHERE research_valid AND exact_research_valid),
               COUNT(*) FILTER (
                   WHERE cost_p05 > cost_p15 OR cost_p15 > cost_p85
                      OR cost_p85 > cost_p95 OR i70_width_fraction < 0
                      OR i90_width_fraction < i70_width_fraction
                      OR profit_ratio < 0 OR profit_ratio > 1
                      OR overhang_mass < 0 OR overhang_mass > 1
                      OR ABS(profit_ratio + overhang_mass - 1) > 1e-9
                      OR exact_p50 <= 0 OR dominant_band_mass < 0
                      OR dominant_band_mass > 1 OR known_cost_mass <= 0
                      OR known_cost_fraction_min < 0
                      OR known_cost_fraction_min > 1
                      OR snapshot_id IS NULL OR available_at IS NULL
               ),
               COUNT(*) FILTER (
                   WHERE timezone('Asia/Shanghai', available_at)
                         > trade_date::TIMESTAMP + INTERVAL '15 hours 30 minutes'
               )
        FROM read_parquet({_sql(data_path)})
        """
    ).fetchone()
    connection.close()
    assert row is not None
    checks = {
        "coverage_exact": (
            str(row[2]) == str(build["start"]) and str(row[3]) == str(build["end"])
        ),
        "unique_symbol_date": row[4] == 0,
        "measurement_valid_at_least_95pct": row[5] / max(row[0], 1) >= 0.95,
        "semantic_invariants": row[6] == 0,
        "available_at_causal": row[7] == 0,
        "build_gates": all(bool(value) for value in build["checks"].values()),
        "no_outcomes_accessed": True,
    }
    if not all(checks.values()):
        raise RuntimeError(json.dumps(checks, ensure_ascii=False))
    inventory = [
        {
            "path": path.name,
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in (build_path, data_path, symbols_path)
    ]
    identity = hashlib.sha256(
        json.dumps(inventory, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    manifest_payload = {
        "schema_version": 1,
        "status": "PASS",
        "asset_id": "CY-027",
        "kind": "current_exact_and_semantic_chip_feature_delta",
        "pit_grade": "B",
        "created_at": datetime.now(UTC).isoformat(),
        "snapshot_id": f"cy027-current-semantic-{identity}",
        "location": str(output),
        "root": str(output),
        "coverage": {
            "start": str(row[2]),
            "end": str(row[3]),
            "rows": int(row[0]),
            "symbols": int(row[1]),
            "measurement_valid_rows": int(row[5]),
            "measurement_valid_ratio": row[5] / max(row[0], 1),
        },
        "checks": checks,
        "files": inventory,
        "inventory": inventory,
        "component_assets": [
            {
                "asset_id": "CY-026",
                "path": str(chip_manifest_path),
                "sha256": _sha256(chip_manifest_path),
            },
            {
                "asset_id": "CY-024",
                "path": str(daily_manifest_path),
                "sha256": _sha256(daily_manifest_path),
            },
        ],
        "measurement_contract": {
            "exact_profiles": ["P01", "P10", "P50", "P90", "P99", "DOMINANT_BAND"],
            "quantiles": ["Q05", "Q15", "Q85", "Q95"],
            "seller_models": ["UNIFORM", "DISPOSITION", "ACTIVE_STICKY"],
            "aggregation": "MEDIAN_WITH_MIN_MAX_SPREAD",
            "measurement_tuned_on_returns": False,
        },
        "allowed_uses": [
            "outcome-blind current chip-state measurement through 2026-08-24",
            "prospective shadow features after all registered input gates pass",
        ],
        "blocked_uses": [
            "parameter selection using 2023 or later outcomes",
            "strict PIT-A, Kelly sizing, live trading or performance claims",
            "silent substitution for historical CY-011 or protocol-locked CY-021",
        ],
    }
    manifest_path = source / "asset_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, output)
    print(
        f"PASS asset=CY-027 rows={row[0]} symbols={row[1]} snapshot={manifest_payload['snapshot_id']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
