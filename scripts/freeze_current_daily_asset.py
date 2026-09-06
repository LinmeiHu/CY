#!/usr/bin/env python3
"""Freeze a passed current daily PIT-B extension as an immutable asset."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-id", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--registry", type=Path, default=Path("configs/data_asset_registry.json"))
    args = parser.parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(output)
    audit_path = source / "audit.json"
    audit = _read(audit_path)
    if audit.get("status") != "PASS" or not all(audit.get("checks", {}).values()):
        raise ValueError("daily PIT-B audit did not pass")
    registry = _read(args.registry.resolve())
    by_id = {str(item["asset_id"]): item for item in registry["assets"]}
    components = []
    for asset_id, expected in audit["component_manifest_sha256"].items():
        asset = by_id.get(asset_id)
        if asset is None or asset.get("lineage", {}).get("manifest_sha256") != expected:
            raise ValueError(f"registered component identity differs: {asset_id}")
        manifest_path = Path(asset["lineage"]["manifest_path"])
        if not manifest_path.is_file() or _sha256(manifest_path) != expected:
            raise ValueError(f"component manifest changed: {asset_id}")
        components.append(
            {"asset_id": asset_id, "path": str(manifest_path.resolve()), "sha256": expected}
        )
    files = []
    for item in audit["files"]:
        path = source / item["path"]
        if (
            not path.is_file()
            or path.stat().st_size != int(item["size"])
            or _sha256(path) != item["sha256"]
        ):
            raise ValueError(f"daily partition inventory mismatch: {path}")
        files.append(dict(item))
    files.append(
        {"path": "audit.json", "size": audit_path.stat().st_size, "sha256": _sha256(audit_path)}
    )
    daily_glob = source / "daily" / "partition_year=*" / "data_0.parquet"
    connection = duckdb.connect()
    try:
        row = connection.execute(
            "SELECT COUNT(*),COUNT(*) FILTER(WHERE hard_valid),MIN(trade_date),"
            "MAX(trade_date),COUNT(DISTINCT trade_date),COUNT(DISTINCT symbol),"
            "COUNT(*) FILTER(WHERE available_at>decision_at) FROM read_parquet(?)",
            [str(daily_glob)],
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    if int(row[6]) != 0:
        raise ValueError("daily PIT-B contains time-travel rows")
    identity = hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    coverage = {
        "start": row[2], "end": row[3], "trade_dates": int(row[4]),
        "symbols": int(row[5]), "rows": int(row[0]), "hard_valid_rows": int(row[1]),
        **{key: value for key, value in audit["coverage"].items() if key.startswith("delta_")},
    }
    manifest = {
        "schema_version": 1, "status": "PASS", "asset_id": args.asset_id,
        "kind": "daily_pit_b_research_table", "pit_grade": "B_RESEARCH_ONLY",
        "snapshot_id": audit["build_id"], "location": str(output), "root": str(output),
        "created_at": datetime.now(UTC).isoformat(), "coverage": coverage,
        "hashes": {"audit_sha256": _sha256(audit_path), "inventory_identity_sha256": identity},
        "component_assets": components, "files": files,
        "quality_evidence": {
            "gate": audit["gate"], "gate_pass": True, **audit["checks"],
            "diagnostics": audit["diagnostics"],
        },
        "lineage": {
            "component_assets": [item["asset_id"] for item in components],
            "pipeline_version": audit["pipeline_version"],
            "builder": str((Path(__file__).parent / "build_current_daily_pit_b.py").resolve()),
            "record_available_at": True, "record_snapshot_id": True,
        },
        "allowed_uses": [
            f"daily causal state generation through {coverage['end']} with row-level hard_valid enforcement",
            "research-only exact-chip state preparation under a separately frozen protocol",
        ],
        "blocked_uses": [
            "strict PIT-A, live trading, sizing, execution release or performance claims",
            "state generation or added risk from hard_valid=false rows",
            "silent replacement of any component asset",
        ],
        "activation_gates": [
            "asset manifest, audit and all listed partition hashes remain exact",
            "available_at is no later than decision_at and hard_valid is enforced",
            "incomplete native-5m sessions remain hard-invalid",
            "industry joins remain causal and action/reference-price checks fail closed",
            "delta hard-valid coverage remains at least 95 percent",
        ],
    }
    manifest_path = source / "asset_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, output)
    final_manifest = output / "asset_manifest.json"
    print(
        json.dumps(
            {"status": "PASS", "manifest": str(final_manifest),
             "manifest_sha256": _sha256(final_manifest), "coverage": coverage},
            ensure_ascii=False, default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
