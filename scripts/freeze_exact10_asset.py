#!/usr/bin/env python3
"""Freeze the already-built ten-stock exact feature and lineage inventories."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

SYMBOLS = (
    "000001.SZ",
    "000333.SZ",
    "000858.SZ",
    "002415.SZ",
    "300015.SZ",
    "300750.SZ",
    "600000.SH",
    "600519.SH",
    "601318.SH",
    "603259.SH",
)
YEARS = tuple(range(2020, 2024))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inventory(root: Path, paths: list[Path]) -> list[dict[str, Any]]:
    return [
        {
            "path": str(path.relative_to(root)),
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(paths)
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--symbols", nargs="+")
    parser.add_argument("--symbols-file", type=Path)
    parser.add_argument("--feature-years", nargs="+", type=int, default=list(range(2018, 2024)))
    parser.add_argument("--lineage-years", nargs="+", type=int, default=list(YEARS))
    parser.add_argument(
        "--dynamic-lineage",
        action="store_true",
        help="Inventory the declared symbols actually present in each year partition",
    )
    parser.add_argument(
        "--feature-manifest-id",
        default="CY-013-EXACT10-FEATURES-V11-20260823",
    )
    parser.add_argument(
        "--lineage-manifest-id",
        default="CY-014-EXACT10-LINEAGE-V11-20260823",
    )
    parser.add_argument("--coverage-start", default="2018-01-02")
    parser.add_argument("--coverage-end", default="2023-12-29")
    parser.add_argument(
        "--component-assets",
        nargs="+",
        default=["QD-004", "CY-006", "CY-008", "QD-010", "CY-012"],
    )
    parser.add_argument("--feature-component-assets", nargs="+")
    parser.add_argument("--lineage-component-assets", nargs="+")
    args = parser.parse_args()
    if args.symbols and args.symbols_file:
        parser.error("provide only one of --symbols or --symbols-file")
    if args.symbols_file:
        symbols = tuple(
            line.strip()
            for line in args.symbols_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    else:
        symbols = tuple(args.symbols or SYMBOLS)
    feature_years = tuple(sorted(set(args.feature_years)))
    lineage_years = tuple(sorted(set(args.lineage_years)))
    if not symbols or not feature_years or not lineage_years:
        parser.error("symbols, feature years and lineage years must be non-empty")
    if len(set(symbols)) != len(symbols):
        parser.error("symbols must be unique")
    root = args.root.resolve()
    feature_root = root / "features"
    lineage_root = root / "lineage"

    feature_files = [feature_root / f"year={year}" / "data.parquet" for year in feature_years]
    exact_file = feature_root / "exact_features.parquet"
    missing_features = [path for path in feature_files if not path.is_file()]
    if not exact_file.is_file() or missing_features:
        raise RuntimeError(
            f"expected exact_features and declared feature partitions; missing={missing_features}"
        )

    lineage_files: list[Path] = []
    symbols_by_year: dict[str, list[str]] = {}
    if args.dynamic_lineage:
        declared_symbols = set(symbols)
        lineage_union: set[str] = set()
        for year in lineage_years:
            paths = sorted(lineage_root.glob(f"year={year}/parts/bucket=*/*.parquet"))
            actual: dict[str, Path] = {}
            for path in paths:
                code, exchange = path.stem.rsplit("_", 1)
                symbol = f"{code}.{exchange}"
                if symbol not in declared_symbols:
                    raise RuntimeError(f"undeclared lineage symbol for {year}: {symbol}")
                if symbol in actual:
                    raise RuntimeError(f"duplicate lineage symbol for {year}: {symbol}")
                actual[symbol] = path
            if not actual:
                raise RuntimeError(f"no lineage files for {year}")
            symbols_by_year[str(year)] = sorted(actual)
            lineage_union.update(actual)
            lineage_files.extend(actual.values())
        if lineage_union != declared_symbols:
            missing = sorted(declared_symbols - lineage_union)
            raise RuntimeError(f"declared symbols have no lineage in any year: {missing}")
    else:
        for year in lineage_years:
            symbols_by_year[str(year)] = list(symbols)
            for symbol in symbols:
                matches = list(
                    lineage_root.glob(
                        f"year={year}/parts/bucket=*/{symbol.replace('.', '_')}.parquet"
                    )
                )
                if len(matches) != 1:
                    raise RuntimeError(
                        f"expected one lineage file for {symbol}/{year}, found {len(matches)}"
                    )
                lineage_files.append(matches[0])

    con = duckdb.connect()
    metrics = con.execute(
        f"""
        SELECT
            count(*) AS rows,
            count(DISTINCT symbol) AS symbols,
            min(trade_date) AS start_date,
            max(trade_date) AS end_date,
            count(*) FILTER (WHERE chip_input_valid) AS valid_rows,
            count(*) FILTER (
                WHERE year >= {min(lineage_years)} AND chip_input_valid AND (
                    model_spread_cost_p50 IS NULL OR
                    model_spread_cost_p90 IS NULL OR
                    model_spread_main_peak IS NULL
                )
            ) AS missing_spread_rows
        FROM read_parquet(
            '{feature_root}/year=*/data.parquet',
            hive_partitioning=true,
            union_by_name=true
        )
        """
    ).fetchone()
    con.close()
    if metrics is None or int(metrics[1]) != len(symbols) or int(metrics[5]) != 0:
        raise RuntimeError(f"exact feature gate failed: {metrics}")

    common = {
        "status": "PASS",
        "created_at": datetime.now(UTC).isoformat(),
        "pit_grade": "B_RESEARCH_ONLY",
        "symbols": list(symbols),
        "coverage": {"start": args.coverage_start, "end": args.coverage_end},
        "calculation_price_basis": "raw_unadjusted_with_causal_corporate_action_events",
        "same_day_resale": "FORBIDDEN_T_PLUS_ONE",
    }
    feature_manifest = {
        **common,
        "manifest_id": args.feature_manifest_id,
        "kind": "exact_chip_ensemble_features",
        "location": str(feature_root),
        "component_assets": args.feature_component_assets or args.component_assets,
        "metrics": {
            "rows": int(metrics[0]),
            "symbols": int(metrics[1]),
            "start": str(metrics[2]),
            "end": str(metrics[3]),
            "valid_rows": int(metrics[4]),
            "missing_spread_rows": int(metrics[5]),
        },
        "inventory": _inventory(feature_root, [exact_file, *feature_files]),
    }
    lineage_manifest = {
        **common,
        "manifest_id": args.lineage_manifest_id,
        "kind": "chip_operator_lineage",
        "location": str(lineage_root),
        "component_assets": args.lineage_component_assets or args.component_assets,
        "storage_version": "chip-operator-log-v11",
        "model_version": "real-chip-inventory-v2.1",
        "seller_models": ["UNIFORM", "DISPOSITION", "ACTIVE_STICKY"],
        "symbols_by_year": symbols_by_year,
        "inventory": _inventory(lineage_root, lineage_files),
    }
    (root / "feature_manifest.json").write_text(
        json.dumps(feature_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "lineage_manifest.json").write_text(
        json.dumps(lineage_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "feature_manifest_sha256": _sha256(root / "feature_manifest.json"),
                "lineage_manifest_sha256": _sha256(root / "lineage_manifest.json"),
                "feature_rows": int(metrics[0]),
                "lineage_files": len(lineage_files),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
