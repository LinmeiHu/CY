#!/usr/bin/env python3
"""Freeze the outcome-blind CY-021 semantic chip overlay after QA."""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from cyq_game.data.registry import DataAssetRegistry  # type: ignore[import-untyped]

ASSET_ID = "CY-021"
ROOT = Path("data/registered_inputs/CY-021-SEMANTIC-CHIP-2020-2022-V1")
REGISTRY = Path("configs/data_asset_registry.json")
PROTOCOL = Path("output/chip_incremental_validation_v1/protocol_manifest.json")
ADDENDUM = Path(
    "output/chip_incremental_validation_v1/addenda/addendum_01_manifest.json"
)
FEATURE_ADDENDUM = Path(
    "output/chip_incremental_validation_v1/addenda/addendum_02_manifest.json"
)
PLACEBO_ADDENDUM = Path(
    "output/chip_incremental_validation_v1/addenda/addendum_03_manifest.json"
)
WEEK_ADDENDUM = Path(
    "output/chip_incremental_validation_v1/addenda/addendum_04_manifest.json"
)
IDENTIFIABILITY_ADDENDUM = Path(
    "output/chip_incremental_validation_v1/addenda/addendum_05_manifest.json"
)
QA_FILE = Path(
    "data/audit/CY-021-SEMANTIC-CHIP-QA-24-V1/semantic_features.parquet"
)
ACTION_QA_FILE = Path(
    "data/audit/CY-021-SEMANTIC-CHIP-ACTION-QA-V1/semantic_features.parquet"
)
DAILY_2020 = Path(
    "data/processed/pit_b_daily_2018_2026_v2/daily/partition_year=2020/data_0.parquet"
)
SEMANTIC_CODE = Path("src/cyq_game/strategy/semantic_chip.py")
BUILDER_CODE = Path("scripts/build_semantic_chip_overlay.py")


def main() -> int:
    root = ROOT.resolve()
    data_path = root / "semantic_features.parquet"
    symbols_path = root / "symbols.txt"
    manifest_path = root / "semantic_manifest.json"
    if manifest_path.is_file():
        payload = _read_object(manifest_path)
        if payload.get("data_sha256") != _sha256(data_path):
            raise ValueError("existing CY-021 data hash changed")
        print(
            f"REUSED asset={ASSET_ID} rows={payload['coverage']['rows']} "
            f"symbols={payload['coverage']['symbols']}",
            flush=True,
        )
        return 0
    if not data_path.is_file() or not symbols_path.is_file():
        raise FileNotFoundError("CY-021 build is incomplete")
    if (root / "_parts").exists():
        raise RuntimeError("CY-021 cannot freeze while resumable parts remain")

    symbols = tuple(
        line.strip()
        for line in symbols_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    if len(symbols) != 4481 or len(symbols) != len(set(symbols)):
        raise ValueError(f"CY-021 expected 4481 unique symbols, found {len(symbols)}")
    protocol_path = PROTOCOL.resolve()
    addendum_path = ADDENDUM.resolve()
    feature_addendum_path = FEATURE_ADDENDUM.resolve()
    placebo_addendum_path = PLACEBO_ADDENDUM.resolve()
    week_addendum_path = WEEK_ADDENDUM.resolve()
    identifiability_addendum_path = IDENTIFIABILITY_ADDENDUM.resolve()
    protocol = _read_object(protocol_path)
    addendum = _read_object(addendum_path)
    feature_addendum = _read_object(feature_addendum_path)
    placebo_addendum = _read_object(placebo_addendum_path)
    week_addendum = _read_object(week_addendum_path)
    identifiability_addendum = _read_object(identifiability_addendum_path)
    if (
        protocol.get("status") != "PREREGISTERED"
        or protocol.get("holdout_outcomes_observed") is not False
        or addendum.get("protocol_event_id") != protocol.get("event_id")
        or addendum.get("holdout_outcomes_observed") is not False
        or feature_addendum.get("protocol_event_id") != protocol.get("event_id")
        or feature_addendum.get("prior_addendum_event_id")
        != addendum.get("event_id")
        or feature_addendum.get("holdout_outcomes_observed") is not False
        or placebo_addendum.get("protocol_event_id") != protocol.get("event_id")
        or placebo_addendum.get("prior_addendum_event_id")
        != feature_addendum.get("event_id")
        or placebo_addendum.get("holdout_outcomes_observed") is not False
        or week_addendum.get("protocol_event_id") != protocol.get("event_id")
        or week_addendum.get("prior_addendum_event_id")
        != placebo_addendum.get("event_id")
        or week_addendum.get("holdout_outcomes_observed") is not False
        or identifiability_addendum.get("protocol_event_id")
        != protocol.get("event_id")
        or identifiability_addendum.get("prior_addendum_event_id")
        != week_addendum.get("event_id")
        or identifiability_addendum.get("holdout_outcomes_observed") is not False
    ):
        raise ValueError("CY-021 freeze requires the locked outcome-blind protocol")
    registry = DataAssetRegistry.load(REGISTRY.resolve())
    source_assets = _source_asset_identities(registry)
    development_source_gate = _verify_development_source_files(registry, symbols)
    metrics = _validate_semantic(data_path, symbols)
    action_qa = _validate_action_golden(ACTION_QA_FILE.resolve(), DAILY_2020.resolve())
    qa_metrics = _validate_semantic(QA_FILE.resolve(), _qa_symbols())
    data_sha256 = _sha256(data_path)
    symbols_sha256 = _sha256(symbols_path)
    frozen_identity: dict[str, Any] = {
        "asset_id": ASSET_ID,
        "data_sha256": data_sha256,
        "symbols_sha256": symbols_sha256,
        "protocol_event_id": protocol["event_id"],
        "addendum_event_id": addendum["event_id"],
        "feature_addendum_event_id": feature_addendum["event_id"],
        "placebo_addendum_event_id": placebo_addendum["event_id"],
        "week_addendum_event_id": week_addendum["event_id"],
        "identifiability_addendum_event_id": identifiability_addendum["event_id"],
        "source_assets": source_assets,
        "development_source_gate": development_source_gate,
        "semantic_code_sha256": _sha256(SEMANTIC_CODE.resolve()),
        "builder_code_sha256": _sha256(BUILDER_CODE.resolve()),
        "coverage": metrics,
        "action_golden": action_qa,
    }
    snapshot_id = "semantic-chip-overlay-" + hashlib.sha256(
        _canonical(frozen_identity).encode()
    ).hexdigest()
    manifest_payload: dict[str, Any] = {
        "schema_version": 1,
        "status": "PASS",
        "asset_id": ASSET_ID,
        "kind": "semantic_exact_chip_feature_overlay",
        "pit_grade": "B_RESEARCH_ONLY",
        "created_at": datetime.now(UTC).isoformat(),
        "snapshot_id": snapshot_id,
        "location": str(root),
        "data_path": str(data_path),
        "data_sha256": data_sha256,
        "data_size": data_path.stat().st_size,
        "symbols_path": str(symbols_path),
        "symbols_sha256": symbols_sha256,
        "protocol_manifest": str(protocol_path),
        "protocol_manifest_sha256": _sha256(protocol_path),
        "addendum_manifest": str(addendum_path),
        "addendum_manifest_sha256": _sha256(addendum_path),
        "feature_addendum_manifest": str(feature_addendum_path),
        "feature_addendum_manifest_sha256": _sha256(feature_addendum_path),
        "placebo_addendum_manifest": str(placebo_addendum_path),
        "placebo_addendum_manifest_sha256": _sha256(placebo_addendum_path),
        "week_addendum_manifest": str(week_addendum_path),
        "week_addendum_manifest_sha256": _sha256(week_addendum_path),
        "identifiability_addendum_manifest": str(identifiability_addendum_path),
        "identifiability_addendum_manifest_sha256": _sha256(
            identifiability_addendum_path
        ),
        "semantic_code": str(SEMANTIC_CODE.resolve()),
        "semantic_code_sha256": frozen_identity["semantic_code_sha256"],
        "builder_code": str(BUILDER_CODE.resolve()),
        "builder_code_sha256": frozen_identity["builder_code_sha256"],
        "component_assets": ["CY-006", "CY-019", "CY-020"],
        "source_assets": source_assets,
        "development_source_gate": development_source_gate,
        "coverage": metrics,
        "qa_24": {
            "path": str(QA_FILE.resolve()),
            "sha256": _sha256(QA_FILE.resolve()),
            "metrics": qa_metrics,
        },
        "action_golden": {
            "path": str(ACTION_QA_FILE.resolve()),
            "sha256": _sha256(ACTION_QA_FILE.resolve()),
            **action_qa,
        },
        "measurement_contract": {
            "i70": "Q15_Q85",
            "i90": "Q05_Q95",
            "peak_kernel": [1.0, 4.0, 6.0, 4.0, 1.0],
            "peak_order": "STRONGEST_BELOW_CLOSE_AND_STRONGEST_ABOVE_CLOSE",
            "seller_models": ["UNIFORM", "DISPOSITION", "ACTIVE_STICKY"],
            "aggregation": "MEDIAN_WITH_MIN_MAX_SPREAD",
            "measurement_tuned_on_returns": False,
        },
        "allowed_uses": [
            "CHIP_INCREMENTAL_VALIDATION_PROTOCOL_V1 stage-1 research for 2020-2022",
            "outcome-blind semantic chip measurement and QA",
        ],
        "blocked_uses": [
            "2023 or later outcome access",
            "strict PIT-A, live trading, sizing, or production release",
            "use outside CHIP_INCREMENTAL_VALIDATION_PROTOCOL_V1",
            "seller-model disagreement used as alpha",
        ],
        "activation_gates": [
            "manifest and data hashes remain exact",
            "bind registered CY-006, CY-019, and CY-020 identities",
            "available_at never exceeds the same-day 15:30 decision",
            "all semantic invariants and company-action golden checks pass",
            "use is physically capped at 2022-12-30",
        ],
        "holdout_outcomes_observed": False,
    }
    _write_immutable(manifest_path, manifest_payload)
    print(
        f"PASS asset={ASSET_ID} rows={metrics['rows']} symbols={metrics['symbols']} "
        f"snapshot={snapshot_id}",
        flush=True,
    )
    return 0


def _validate_semantic(path: Path, expected_symbols: tuple[str, ...]) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    expected = set(expected_symbols)
    con = duckdb.connect()
    try:
        columns = {
            str(row[0])
            for row in con.execute(
                f"DESCRIBE SELECT * FROM read_parquet({_sql_text(str(path))})"
            ).fetchall()
        }
        required = {
            "symbol", "trade_date", "cost_p05", "cost_p15", "cost_p85",
            "cost_p95", "i70_width_fraction", "i90_width_fraction",
            "profit_ratio", "overhang_mass", "lower_peak_center",
            "lower_peak_strength", "upper_peak_center", "upper_peak_strength",
            "valley_center", "valley_strength", "valley_depth",
            "known_cost_mass", "known_cost_fraction_min", "available_at",
            "snapshot_id", "research_valid", "invalid_reason",
        }
        missing = sorted(required - columns)
        if missing:
            raise ValueError("semantic overlay missing fields: " + ", ".join(missing))
        row = con.execute(
            f"""
            SELECT count(*), count(DISTINCT symbol), min(trade_date), max(trade_date),
                   count(*) - count(DISTINCT (symbol, trade_date)) AS duplicate_keys,
                   count(*) FILTER (
                       WHERE cost_p05 > cost_p15 OR cost_p15 > cost_p85
                          OR cost_p85 > cost_p95
                   ) AS quantile_errors,
                   count(*) FILTER (
                       WHERE i70_width_fraction < 0 OR i90_width_fraction < 0
                          OR i70_width_fraction > i90_width_fraction + 1e-12
                   ) AS width_errors,
                   count(*) FILTER (
                       WHERE profit_ratio < 0 OR profit_ratio > 1
                          OR overhang_mass < 0 OR overhang_mass > 1
                          OR abs(profit_ratio + overhang_mass - 1) > 1e-9
                   ) AS ratio_errors,
                   count(*) FILTER (
                       WHERE known_cost_mass <= 0 OR known_cost_fraction_min < 0
                          OR known_cost_fraction_min > 1
                   ) AS mass_errors,
                   count(*) FILTER (
                       WHERE lower_peak_center IS NOT NULL
                         AND upper_peak_center IS NOT NULL
                         AND lower_peak_center >= upper_peak_center
                   ) AS peak_order_errors,
                   count(*) FILTER (
                       WHERE valley_depth IS NOT NULL
                         AND (valley_depth < 0 OR valley_depth > 1)
                   ) AS valley_errors,
                   count(*) FILTER (
                       WHERE snapshot_id IS NULL OR trim(snapshot_id) = ''
                   ) AS snapshot_errors,
                   count(*) FILTER (
                       WHERE timezone('Asia/Shanghai', available_at)
                             > trade_date::TIMESTAMP + INTERVAL '15 hours 30 minutes'
                   ) AS future_rows,
                   count(*) FILTER (
                       WHERE cost_p05 IS NULL OR cost_p15 IS NULL
                          OR cost_p85 IS NULL OR cost_p95 IS NULL
                          OR i70_width_fraction IS NULL OR i90_width_fraction IS NULL
                   ) AS missing_required_measurements,
                   count(*) FILTER (WHERE research_valid) AS research_valid_rows
            FROM read_parquet({_sql_text(str(path))})
            """
        ).fetchone()
        actual_symbols = {
            str(value[0])
            for value in con.execute(
                f"SELECT DISTINCT symbol FROM read_parquet({_sql_text(str(path))})"
            ).fetchall()
        }
        annual = con.execute(
            f"""
            SELECT year(trade_date)::INTEGER, count(*),
                   count(*) FILTER (WHERE research_valid)
            FROM read_parquet({_sql_text(str(path))})
            GROUP BY 1 ORDER BY 1
            """
        ).fetchall()
    finally:
        con.close()
    if row is None:
        raise RuntimeError("semantic overlay validation returned no result")
    if actual_symbols != expected:
        raise ValueError(
            f"semantic symbol inventory mismatch: missing={len(expected-actual_symbols)} "
            f"extra={len(actual_symbols-expected)}"
        )
    if row[2] < datetime(2020, 1, 2).date() or row[3] > datetime(2022, 12, 30).date():
        raise ValueError("semantic overlay escaped the 2020-2022 date lock")
    if any(int(row[index]) != 0 for index in range(4, 14)):
        raise ValueError(f"semantic overlay invariant failure: {row}")
    annual_rows = {
        str(year): {
            "rows": int(rows),
            "research_valid_rows": int(valid),
            "research_valid_ratio": int(valid) / int(rows),
        }
        for year, rows, valid in annual
    }
    return {
        "start": row[2].isoformat(),
        "end": row[3].isoformat(),
        "rows": int(row[0]),
        "symbols": int(row[1]),
        "research_valid_rows": int(row[14]),
        "research_valid_ratio": int(row[14]) / int(row[0]),
        "annual": annual_rows,
        "duplicate_symbol_trade_date_keys": int(row[4]),
        "semantic_invariant_errors": sum(int(row[index]) for index in range(5, 14)),
    }


def _validate_action_golden(action_path: Path, daily_path: Path) -> dict[str, Any]:
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"""
            SELECT s.trade_date, d.close, d.share_multiplier,
                   s.cost_p05, s.cost_p15, s.cost_p85, s.cost_p95
            FROM read_parquet({_sql_text(str(action_path))}) s
            JOIN read_parquet({_sql_text(str(daily_path))}) d
              USING (symbol, trade_date)
            WHERE s.symbol = '300438.SZ'
              AND s.trade_date IN (DATE '2020-06-02', DATE '2020-06-03')
            ORDER BY s.trade_date
            """
        ).fetchall()
    finally:
        con.close()
    if len(rows) != 2 or float(rows[1][2]) != 1.5:
        raise ValueError(f"company-action golden fixture changed: {rows}")
    expected_ratio = 1.0 / float(rows[1][2])
    close_ratio = float(rows[1][1]) / float(rows[0][1])
    quantile_ratios = [
        float(rows[1][index]) / float(rows[0][index]) for index in range(3, 7)
    ]
    deviations = [
        abs(math.log(ratio / expected_ratio)) for ratio in quantile_ratios
    ]
    maximum = max(deviations)
    if maximum > 0.01:
        raise ValueError(f"company-action semantic rebase failed: {maximum}")
    return {
        "symbol": "300438.SZ",
        "effective_date": "2020-06-03",
        "share_multiplier": 1.5,
        "mechanical_price_ratio": expected_ratio,
        "observed_raw_close_ratio": close_ratio,
        "observed_semantic_quantile_ratios": quantile_ratios,
        "maximum_absolute_log_deviation": maximum,
        "gate": "PASS",
    }


def _source_asset_identities(registry: DataAssetRegistry) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for asset_id in ("CY-006", "CY-019", "CY-020"):
        asset = registry.assets[asset_id]
        raw_path = asset.lineage.get("manifest_path")
        raw_sha256 = asset.lineage.get("manifest_sha256")
        if (
            asset.status != "RESEARCH_CONDITIONAL"
            or not isinstance(raw_path, str)
            or not isinstance(raw_sha256, str)
        ):
            raise ValueError(f"source asset {asset_id} is not research-registered")
        path = Path(raw_path).expanduser().resolve()
        if _sha256(path) != raw_sha256:
            raise ValueError(f"source asset {asset_id} manifest changed")
        result.append(
            {
                "asset_id": asset_id,
                "manifest_path": str(path),
                "manifest_sha256": raw_sha256,
            }
        )
    return result


def _verify_development_source_files(
    registry: DataAssetRegistry, symbols: tuple[str, ...]
) -> dict[str, Any]:
    """Hash the exact pre-2023 physical inputs consumed by the overlay."""
    daily = registry.assets["CY-006"]
    lineage = registry.assets["CY-020"]
    daily_manifest = _read_object(
        Path(str(daily.lineage["manifest_path"])).expanduser().resolve()
    )
    lineage_manifest = _read_object(
        Path(str(lineage.lineage["manifest_path"])).expanduser().resolve()
    )
    daily_root = Path(str(daily_manifest["root"])).resolve()
    lineage_root = Path(str(lineage_manifest["location"])).resolve()
    selected: list[tuple[Path, dict[str, Any]]] = []
    for raw in daily_manifest["files"]:
        if not isinstance(raw, dict):
            raise ValueError("CY-006 inventory entry is invalid")
        relative = Path(str(raw["path"]))
        if any(part in {f"partition_year={year}" for year in (2020, 2021, 2022)} for part in relative.parts):
            selected.append((daily_root / relative, raw))
    for raw in lineage_manifest["inventory"]:
        if not isinstance(raw, dict):
            raise ValueError("CY-020 inventory entry is invalid")
        relative = Path(str(raw["path"]))
        if relative.parts and relative.parts[0] in {"year=2020", "year=2021", "year=2022"}:
            selected.append((lineage_root / relative, raw))
    expected_symbols = {
        str(symbol)
        for year in ("2020", "2021", "2022")
        for symbol in lineage_manifest["symbols_by_year"][year]
    }
    if expected_symbols != set(symbols):
        raise ValueError("CY-021 symbols differ from CY-020 development universe")
    if len(selected) != 12_632:
        raise ValueError(f"unexpected CY-021 development source file count: {len(selected)}")
    total_size = 0
    inventory_identity: list[dict[str, Any]] = []
    for path, raw in selected:
        if (
            not path.is_file()
            or path.stat().st_size != raw["size"]
            or _sha256(path) != raw["sha256"]
        ):
            raise ValueError(f"CY-021 development source changed: {path}")
        total_size += path.stat().st_size
        inventory_identity.append(
            {"path": str(path), "size": path.stat().st_size, "sha256": raw["sha256"]}
        )
    return {
        "status": "PASS",
        "maximum_physical_data_year": 2022,
        "files_verified": len(selected),
        "bytes_verified": total_size,
        "symbols_verified": len(symbols),
        "inventory_identity_sha256": hashlib.sha256(
            _canonical({"files": inventory_identity}).encode()
        ).hexdigest(),
        "future_partition_data_opened": False,
    }


def _qa_symbols() -> tuple[str, ...]:
    return tuple(
        line.strip()
        for line in Path("configs/semantic_chip_qa_24_symbols_v1.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    )


def _sql_text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return value


def _write_immutable(path: Path, value: dict[str, Any]) -> None:
    raw = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != raw:
            raise FileExistsError(f"immutable semantic manifest differs: {path}")
        return
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(raw, encoding="utf-8")
    temporary.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


if __name__ == "__main__":
    raise SystemExit(main())
