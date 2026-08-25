#!/usr/bin/env python3
"""Validate the registered latest-data chain and its NO_TRADE shadow contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import runpy
from pathlib import Path
from typing import Any

import duckdb

from cyq_game.data.registry import DataAssetRegistry, DataOperation, InputSnapshotManifest

ROOT = Path(__file__).resolve().parents[1]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-snapshot", type=Path, required=True)
    parser.add_argument("--shadow-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--registry", type=Path, default=ROOT / "configs/data_asset_registry.json"
    )
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
    registry_path = args.registry.resolve()
    validator = runpy.run_path(str(ROOT / "scripts/validate_data_registry.py"))
    registry_payload = validator["load_registry"](registry_path)
    registry_errors = validator["validate_registry"](
        registry_payload, verify_paths=True, verify_hashes=True
    )
    if registry_errors:
        raise ValueError("registry validation failed: " + "; ".join(registry_errors))
    registry = DataAssetRegistry.load(registry_path)
    snapshot = InputSnapshotManifest.load(args.input_snapshot.resolve(), registry=registry)
    authorization = snapshot.authorize(DataOperation.STATE_GENERATION, registry=registry)
    if (snapshot.scope_start.isoformat(), snapshot.scope_end.isoformat()) != (
        "2026-08-13",
        "2026-08-24",
    ):
        raise ValueError("current input snapshot scope differs")
    daily = snapshot.binding("daily_pit_b").verify_file(
        snapshot.binding("daily_pit_b").path / "daily/partition_year=2026/data_0.parquet"
    )
    execution = snapshot.binding("minute_pit_b").verify_file(
        snapshot.binding("minute_pit_b").path
        / "execution_5m/partition_year=2026/data_0.parquet"
    )
    minute_daily = snapshot.binding("minute_pit_b").verify_file(
        snapshot.binding("minute_pit_b").path / "daily/partition_year=2026/data_0.parquet"
    )
    semantic = snapshot.binding("semantic_chip_current").verify_file(
        snapshot.binding("semantic_chip_current").path / "semantic_features.parquet"
    )
    chip_binding = snapshot.binding("chip_current")
    chip_part = next(chip_binding.path.glob("year=2026/parts/bucket=*/*.parquet"), None)
    if chip_part is None:
        raise ValueError("current chip part inventory is empty")
    chip_binding.verify_file(chip_part)

    connection = duckdb.connect()
    daily_row = connection.execute(
        f"""
        SELECT count(*), count(*) FILTER (WHERE hard_valid), min(trade_date), max(trade_date)
        FROM read_parquet({_sql(daily)})
        WHERE trade_date BETWEEN DATE '2026-08-13' AND DATE '2026-08-24'
        """
    ).fetchone()
    execution_row = connection.execute(
        f"""
        SELECT count(*), count(DISTINCT (symbol, trade_date, window_index))
        FROM read_parquet({_sql(execution)})
        WHERE trade_date BETWEEN DATE '2026-08-13' AND DATE '2026-08-24'
        """
    ).fetchone()
    minute_daily_row = connection.execute(
        f"""
        SELECT count(*)
        FROM read_parquet({_sql(minute_daily)})
        WHERE trade_date BETWEEN DATE '2026-08-13' AND DATE '2026-08-24'
        """
    ).fetchone()
    semantic_row = connection.execute(
        f"""
        SELECT count(*), count(*) FILTER (WHERE research_valid AND exact_research_valid),
               min(trade_date), max(trade_date),
               count(*) - count(DISTINCT (symbol, trade_date)),
               count(*) FILTER (WHERE available_at IS NULL OR snapshot_id IS NULL)
        FROM read_parquet({_sql(semantic)})
        """
    ).fetchone()
    connection.close()
    assert (
        daily_row is not None
        and execution_row is not None
        and minute_daily_row is not None
        and semantic_row is not None
    )
    chip_manifest = _read(chip_binding.inventory_manifest)  # type: ignore[arg-type]
    annual = chip_manifest["coverage"]["annual"]
    training = _read(
        ROOT / "output/chip_mechanism_interaction_v1/training_v1/manifest.json"
    )
    shadow = _read(args.shadow_config.resolve())
    checks = {
        "registry_and_inventory_hashes": True,
        "state_generation_authorized": authorization.operation is DataOperation.STATE_GENERATION,
        "daily_current_coverage": (
            daily_row[0] > 0
            and daily_row[1] / daily_row[0] >= 0.95
            and str(daily_row[2]) == "2026-08-13"
            and str(daily_row[3]) == "2026-08-24"
        ),
        "minute_current_unique_and_six_windows": execution_row[0] == execution_row[1]
        and execution_row[0] == minute_daily_row[0] * 6,
        "chip_annual_coverage": min(
            float(item["coverage"]) for item in annual
        ) >= 0.95,
        "semantic_measurement_coverage": (
            semantic_row[0] > 0
            and semantic_row[1] / semantic_row[0] >= 0.95
            and str(semantic_row[2]) == "2026-06-17"
            and str(semantic_row[3]) == "2026-08-24"
            and semantic_row[4] == 0
            and semantic_row[5] == 0
        ),
        "training_result_is_no_trade": training.get("decision") == "NO_TRADE"
        and training.get("promotion_authorized") is False,
        "shadow_is_no_trade": shadow.get("active_order_action") == "NO_TRADE"
        and shadow.get("risk_contract", {}).get("live_orders_enabled") is False
        and shadow.get("risk_contract", {}).get("kelly_enabled") is False,
    }
    result = {
        "schema_version": 1,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "registry_sha256": _sha256(registry_path),
        "input_snapshot_sha256": snapshot.sha256,
        "daily": {
            "rows": daily_row[0],
            "hard_valid_rows": daily_row[1],
            "start": str(daily_row[2]),
            "end": str(daily_row[3]),
        },
        "execution": {
            "rows": execution_row[0],
            "unique_rows": execution_row[1],
            "minute_daily_rows": minute_daily_row[0],
        },
        "semantic": {
            "rows": semantic_row[0],
            "measurement_valid_rows": semantic_row[1],
            "start": str(semantic_row[2]),
            "end": str(semantic_row[3]),
        },
        "chip_annual_coverage": {
            str(item["year"]): item["coverage"] for item in annual
        },
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if result["status"] != "PASS":
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
