#!/usr/bin/env python3
"""Freeze the space-efficient current exact-chip continuation as CY-026."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--end-date", default="2026-08-24")
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


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _inventory(root: Path) -> list[dict[str, Any]]:
    paths = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.name != "asset_manifest.json"
    )
    return [
        {
            "path": str(path.relative_to(root)),
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in paths
    ]


def _component(path: Path, asset_id: str) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    payload = _read(resolved)
    declared_asset = payload.get("asset_id")
    legacy_lineage = (
        asset_id == "CY-020"
        and declared_asset is None
        and payload.get("kind") == "chip_operator_lineage"
        and payload.get("status") == "PASS"
    )
    raw_inventory = (
        asset_id == "QD-004"
        and declared_asset is None
        and payload.get("schema_version") == 1
        and isinstance(payload.get("root"), str)
        and isinstance(payload.get("files"), list)
    )
    if declared_asset != asset_id and not (legacy_lineage or raw_inventory):
        raise ValueError(f"component manifest is not {asset_id}: {resolved}")
    return {"asset_id": asset_id, "path": str(resolved), "sha256": _sha256(resolved)}


def _verify_year(root: Path, year: int, end_date: str) -> dict[str, Any]:
    year_root = root / f"year={year}"
    if (year_root / "_staging").exists():
        raise RuntimeError(f"reproducible staging remains for {year}")
    summary_path = year_root / "summary.json"
    summary = _read(summary_path)
    if summary.get("status") != "PASS" or float(summary.get("coverage", 0.0)) < 0.95:
        raise ValueError(f"{year} coverage gate failed")
    terminal_files = tuple(year_root.glob("terminal/bucket=*/*.parquet"))
    expected = int(summary["passed"] if year == 2023 else summary["passed_symbols"])
    if len(terminal_files) != expected:
        raise ValueError(f"{year} terminal count differs: {len(terminal_files)} != {expected}")
    part_files = tuple(year_root.glob("parts/bucket=*/*.parquet"))
    if year in (2023, 2024, 2025) and part_files:
        raise ValueError(f"{year} must not retain full operator parts")
    if year in (2024, 2025) and summary.get("terminal_only") is not True:
        raise ValueError(f"{year} is not terminal-only")
    if year == 2026:
        if summary.get("terminal_only") is not False:
            raise ValueError("2026 must retain the current operator delta")
        if summary.get("end_date") != end_date:
            raise ValueError("2026 end date differs")
        if summary.get("emit_start_date") != "2026-06-17":
            raise ValueError("2026 operator start differs")
        if len(part_files) != expected:
            raise ValueError("2026 part/terminal sets differ")
        if int(summary["rows"]) != int(summary["emitted_days"]) * 3:
            raise ValueError("2026 operator rows do not contain all seller models")
    if float(summary.get("max_mass_error", 0.0)) > 1e-6:
        raise ValueError(f"{year} mass conservation failed")
    if float(summary.get("max_same_day_resale", 0.0)) > 1e-12:
        raise ValueError(f"{year} same-day resale failed")
    return {
        "year": year,
        "summary_path": str(summary_path.resolve()),
        "summary_sha256": _sha256(summary_path),
        "coverage": float(summary["coverage"]),
        "symbols": int(summary["sources"] if year == 2023 else summary["symbols"]),
        "passed_symbols": expected,
        "terminal_files": len(terminal_files),
        "operator_files": len(part_files),
        "operator_rows": int(summary.get("rows", 0)),
        "fallback_days": int(summary.get("fallback_days", 0)),
    }


def main() -> int:
    args = _parse_args()
    source = args.source_root.resolve()
    output = args.output_root.resolve()
    if output.exists():
        manifest = output / "asset_manifest.json"
        if manifest.is_file() and _read(manifest).get("status") == "PASS":
            print(f"REUSED asset=CY-026 manifest={manifest}", flush=True)
            return 0
        raise FileExistsError(output)
    if not source.is_dir():
        raise FileNotFoundError(source)
    years = [_verify_year(source, year, args.end_date) for year in range(2023, 2027)]
    components = [
        _component(
            Path(
                "data/registered_inputs/"
                "CY-019-MARKUP-RETEST-MAIN-CHINEXT-2020-2023-V11/"
                "lineage_manifest.json"
            ),
            "CY-020",
        ),
        _component(
            Path(
                "data/registered_inputs/"
                "CY-022-BAOSTOCK-MARKET-DELTA-20260813-20260824-V1/"
                "asset_manifest.json"
            ),
            "CY-022",
        ),
        _component(
            Path("data/input_inventories/QD-004-2018-2026-20260820.json"),
            "QD-004",
        ),
        _component(
            Path(
                "data/registered_inputs/"
                "CY-024-PIT-B-DAILY-2018-20260824-V1/asset_manifest.json"
            ),
            "CY-024",
        ),
        _component(
            Path(
                "data/registered_inputs/"
                "CY-025-PIT-B-MINUTE-2018-20260824-V1/asset_manifest.json"
            ),
            "CY-025",
        ),
    ]
    inventory = _inventory(source)
    inventory_identity = hashlib.sha256(_canonical(inventory).encode()).hexdigest()
    snapshot_id = f"cy026-current-chip-{inventory_identity}"
    manifest_payload = {
        "schema_version": 1,
        "status": "PASS",
        "asset_id": "CY-026",
        "kind": "current_compact_chip_state_continuation",
        "pit_grade": "B",
        "created_at": datetime.now(UTC).isoformat(),
        "snapshot_id": snapshot_id,
        "location": str(output),
        "root": str(output),
        "coverage": {
            "bootstrap_terminal_year": 2023,
            "terminal_continuation_years": [2024, 2025],
            "operator_start": "2026-06-17",
            "operator_end": args.end_date,
            "annual": years,
        },
        "component_assets": components,
        "files": inventory,
        "inventory": inventory,
        "inventory_files": len(inventory),
        "inventory_bytes": sum(int(item["size"]) for item in inventory),
        "inventory_identity_sha256": inventory_identity,
        "measurement_contract": {
            "seller_models": ["UNIFORM", "DISPOSITION", "ACTIVE_STICKY"],
            "grid": "log-grid-25bp-v1",
            "same_day_resale": "FORBIDDEN",
            "mass_conservation": "EXACT_WITH_NUMERIC_TOLERANCE",
            "history_policy": (
                "CY-020 reanchored 2023 terminals; QD-004 exact 2024/2025 "
                "terminal-only continuation; 2026-06-17+ daily operators"
            ),
        },
        "allowed_uses": [
            "outcome-blind current chip-state generation through 2026-08-24",
            "current semantic measurement after registry and cross-table gates pass",
        ],
        "blocked_uses": [
            "strict PIT-A or live-trading truth",
            "parameter selection on 2023 or later outcomes",
            "historical 2024/2025 daily lineage claims from terminal-only checkpoints",
            "use for failed or missing symbols without explicit hard-invalid handling",
        ],
    }
    manifest = source / "asset_manifest.json"
    manifest.write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, output)
    print(
        f"PASS asset=CY-026 files={len(inventory)} bytes={manifest_payload['inventory_bytes']} "
        f"snapshot={snapshot_id}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
