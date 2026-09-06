#!/usr/bin/env python3
"""Freeze the complete main-board + ChiNext exact-chip history asset.

Materialized v13 years are kept in this asset.  The already frozen CY-020 v11
years are referenced through absolute year-directory symlinks and an exact
component-manifest binding; no registered history is copied or silently
rewritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq


MATERIAL_YEARS = (2018, 2019, 2024, 2025, 2026)
LINKED_YEARS = (2020, 2021, 2022, 2023)
SELLER_MODELS = ("UNIFORM", "DISPOSITION", "ACTIVE_STICKY")


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


def _verify_material_year(root: Path, year: int, end_date: str) -> dict[str, Any]:
    year_root = root / f"year={year}"
    summary_path = year_root / "summary.json"
    summary = _read(summary_path)
    if summary.get("status") != "PASS" or float(summary.get("coverage", 0)) < 0.95:
        raise ValueError(f"year {year} coverage gate failed")
    if summary.get("terminal_only") is not False:
        raise ValueError(f"year {year} does not contain full daily operators")
    if year == 2026 and summary.get("end_date") != end_date:
        raise ValueError("2026 end date differs from the freeze contract")
    if float(summary.get("max_mass_error", 1)) != 0.0:
        raise ValueError(f"year {year} mass conservation is not exact zero")
    if float(summary.get("max_same_day_resale", 1)) != 0.0:
        raise ValueError(f"year {year} contains same-day resale")
    passed = int(summary["passed_symbols"])
    temporary_files = sorted(year_root.rglob("*.tmp.parquet"))
    if temporary_files:
        raise ValueError(
            f"year {year} contains unfinished atomic writes: {temporary_files[:3]}"
        )
    parts = sorted(year_root.glob("parts/bucket=*/*.parquet"))
    terminals = sorted(year_root.glob("terminal/bucket=*/*.parquet"))
    features = sorted(year_root.glob("daily_feature_fact/symbol_bucket=*/*.parquet"))
    if len(parts) != passed or len(terminals) != passed or len(features) != passed:
        raise ValueError(
            f"year {year} file sets differ from passed symbols: "
            f"parts={len(parts)} terminal={len(terminals)} features={len(features)} passed={passed}"
        )
    if int(summary["rows"]) != int(summary["emitted_days"]) * len(SELLER_MODELS):
        raise ValueError(f"year {year} does not contain all three seller-model rows")
    first_schema = pq.read_schema(parts[0])
    terminal_model_version = str(
        pq.read_table(terminals[0], columns=["model_version"])
        .column("model_version")[0]
        .as_py()
    )
    required = {
        "available_at", "decision_at", "snapshot_id", "seller_model",
        "conservation_error_shares", "same_day_resale_shares",
        "known_cost_fraction", "unknown_cost_fraction",
    }
    if not required.issubset(first_schema.names):
        raise ValueError(f"year {year} operator schema is incomplete")
    operator_glob = year_root / "parts" / "bucket=*" / "*.parquet"
    connection = duckdb.connect()
    try:
        scalar = connection.execute(
            """
            SELECT COUNT(*),
                   COUNT(*) FILTER(WHERE available_at > decision_at),
                   COUNT(*) FILTER(WHERE conservation_error_shares != 0),
                   COUNT(*) FILTER(WHERE same_day_resale_shares != 0),
                   COUNT(*) FILTER(WHERE ABS(
                     known_cost_fraction + unknown_cost_fraction - 1.0) > 1e-12),
                   COUNT(*) FILTER(WHERE known_cost_fraction < 0
                                      OR unknown_cost_fraction < 0
                                      OR known_cost_fraction > 1
                                      OR unknown_cost_fraction > 1),
                   COUNT(*) FILTER(WHERE minute_fallback),
                   COUNT(*) FILTER(WHERE hard_valid),
                   COUNT(*) FILTER(WHERE research_valid)
            FROM read_parquet(?)
            """,
            [str(operator_glob)],
        ).fetchone()
        bad_groups = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM (
                  SELECT symbol,trade_date,COUNT(*) row_count,
                         COUNT(DISTINCT seller_model) model_count
                  FROM read_parquet(?) GROUP BY symbol,trade_date
                  HAVING row_count != 3 OR model_count != 3
                )
                """,
                [str(operator_glob)],
            ).fetchone()[0]
        )
    finally:
        connection.close()
    assert scalar is not None
    violations = {
        "available_after_decision": int(scalar[1]),
        "nonzero_conservation_error": int(scalar[2]),
        "nonzero_same_day_resale": int(scalar[3]),
        "known_unknown_sum_error": int(scalar[4]),
        "known_unknown_out_of_bounds": int(scalar[5]),
        "incomplete_three_model_groups": bad_groups,
    }
    if any(violations.values()):
        raise ValueError(f"year {year} scalar invariant failure: {violations}")
    return {
        "year": year, "storage_version": summary["operator_log_version"],
        "model_version": terminal_model_version, "coverage": float(summary["coverage"]),
        "symbols": int(summary["symbols"]), "passed_symbols": passed,
        "failed_symbols": int(summary["symbols"]) - passed,
        "rows": int(summary["rows"]), "emitted_days": int(summary["emitted_days"]),
        "fallback_days": int(summary.get("fallback_days", 0)),
        "minute_fallback_rows": int(scalar[6]),
        "hard_valid_rows": int(scalar[7]),
        "research_valid_rows": int(scalar[8]),
        "scalar_invariant_violations": violations,
        "summary_sha256": _sha256(summary_path),
    }


def _component(registry: dict[str, Any], asset_id: str) -> dict[str, str]:
    matches = [item for item in registry["assets"] if item.get("asset_id") == asset_id]
    if len(matches) != 1:
        raise ValueError(f"registry must contain one {asset_id}")
    lineage = matches[0].get("lineage", {})
    path = Path(str(lineage.get("manifest_path", "")))
    expected = str(lineage.get("manifest_sha256", ""))
    if not path.is_file() or not expected or _sha256(path) != expected:
        raise ValueError(f"component identity differs: {asset_id}")
    return {"asset_id": asset_id, "path": str(path.resolve()), "sha256": expected}


def _inventory(root: Path) -> list[dict[str, Any]]:
    paths = []
    for year in MATERIAL_YEARS:
        paths.extend(
            path
            for path in (root / f"year={year}").rglob("*")
            if path.is_file() and path.name != "asset_manifest.json"
        )
    items = []
    for position, path in enumerate(sorted(paths), start=1):
        items.append(
            {"path": path.relative_to(root).as_posix(), "size": path.stat().st_size,
             "sha256": _sha256(path)}
        )
        if position % 1000 == 0:
            print(f"chip_freeze_hash_progress={position}/{len(paths)}", flush=True)
    return items


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-id", default="CY-035")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cy020-root", type=Path, required=True)
    parser.add_argument("--end-date", default="2026-09-04")
    parser.add_argument("--registry", type=Path, default=Path("configs/data_asset_registry.json"))
    args = parser.parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    cy020_root = args.cy020_root.resolve()
    if output.exists():
        raise FileExistsError(output)
    annual = [_verify_material_year(source, year, args.end_date) for year in MATERIAL_YEARS]
    registry = _read(args.registry.resolve())
    components = [
        _component(registry, asset_id)
        for asset_id in (
            "CY-020", "CY-022", "CY-026", "CY-031", "CY-033", "QD-004"
        )
    ]
    cy020_manifest = _read(Path(components[0]["path"]))
    if cy020_manifest.get("model_version") != "real-chip-inventory-v2.1":
        raise ValueError("CY-020 model version differs")
    for year in LINKED_YEARS:
        target = cy020_root / f"year={year}"
        link = source / f"year={year}"
        if not target.is_dir():
            raise FileNotFoundError(target)
        if link.exists() or link.is_symlink():
            if not link.is_symlink() or link.resolve() != target:
                raise FileExistsError(link)
        else:
            link.symlink_to(target, target_is_directory=True)
    inventory = _inventory(source)
    inventory_identity = hashlib.sha256(
        json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    snapshot_id = f"cy035-full-chip-{inventory_identity}"
    manifest = {
        "schema_version": 1, "status": "PASS", "asset_id": args.asset_id,
        "kind": "full_market_exact_chip_lineage_composite", "pit_grade": "B_RESEARCH_ONLY",
        "created_at": datetime.now(UTC).isoformat(), "snapshot_id": snapshot_id,
        "location": str(output), "root": str(output),
        "coverage": {
            "start": "2018-01-02", "end": args.end_date,
            "universe": "date-varying Shanghai/Shenzhen main-board and ChiNext",
            "materialized_v13_years": list(MATERIAL_YEARS),
            "linked_registered_v11_years": list(LINKED_YEARS), "annual": annual,
        },
        "component_assets": components,
        "linked_history_policy": {
            "asset_id": "CY-020", "years": list(LINKED_YEARS),
            "root": str(cy020_root), "manifest_sha256": components[0]["sha256"],
            "storage_version": "chip-operator-log-v11",
        },
        "continuation_bootstrap": {
            "asset_id": "CY-026",
            "terminal_year": 2023,
            "manifest_sha256": next(
                item["sha256"] for item in components if item["asset_id"] == "CY-026"
            ),
        },
        "files": inventory, "inventory_files": len(inventory),
        "inventory_bytes": sum(int(item["size"]) for item in inventory),
        "inventory_identity_sha256": inventory_identity,
        "measurement_contract": {
            "model_version": "real-chip-inventory-v2.1",
            "storage_versions": ["chip-operator-log-v11", "chip-operator-log-v13"],
            "seller_models": list(SELLER_MODELS), "same_day_resale": "FORBIDDEN",
            "mass_conservation": "EXACT_ZERO", "unknown_cost": "PRESERVED_NOT_NORMALIZED",
            "price_basis": "unadjusted with explicit company-action economic coordinates",
        },
        "quality_evidence": {
            "gate": "FULL_MAIN_CHINEXT_EXACT_CHIP_2018_20260904_V1",
            "gate_pass": True, "minimum_materialized_annual_coverage": min(item["coverage"] for item in annual),
            "mass_conservation": "EXACT_ZERO", "same_day_resale": "EXACT_ZERO",
            "three_seller_models": "PASS", "linked_cy020_manifest_exact": True,
        },
        "allowed_uses": [
            "research-only replay of exact three-model chip state for main-board and ChiNext",
            "causal scalar cost-distribution measurement with hard-valid row enforcement",
        ],
        "blocked_uses": [
            "strict PIT-A, true-holder identity, live trading, sizing or performance claims",
            "use of failed symbols or hard_valid=false rows without explicit exclusion",
            "merging the three seller models into one pseudo-precise answer",
            "normalizing, filling or hiding unknown-cost mass",
        ],
        "activation_gates": [
            "CY-035 manifest and every materialized file hash remain exact",
            "linked CY-020 manifest and absolute year targets remain exact",
            "all three seller models are present and available_at never exceeds decision_at",
            "mass conservation and same-day resale remain exact zero",
            "annual successful-symbol coverage remains at least 95 percent",
        ],
    }
    manifest_path = source / "asset_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, output)
    final_manifest = output / "asset_manifest.json"
    print(
        json.dumps(
            {"status": "PASS", "manifest": str(final_manifest),
             "manifest_sha256": _sha256(final_manifest), "snapshot_id": snapshot_id,
             "inventory_files": len(inventory), "inventory_bytes": manifest["inventory_bytes"]},
            ensure_ascii=False,
        ), flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
