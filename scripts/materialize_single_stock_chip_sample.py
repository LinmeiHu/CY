#!/usr/bin/env python3
"""Freeze one bounded, self-contained exact-chip lineage sample."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cyq_game.chip.ensemble_v2 import SELLER_MODEL_ORDER  # noqa: E402
from cyq_game.chip.operator_index import build_operator_symbol_index  # noqa: E402
from cyq_game.strategy.chip_lineage import PersistedChipLineageResolver  # noqa: E402
from cyq_game.strategy.markup_retest import (  # noqa: E402
    ChipMassMethod,
    ChipMassProfile,
    LifecycleAnchor,
    LifecycleObservation,
)

ASSET_ID = "CY-030"
EXPECTED_SOURCE_ASSET = "CY-020"
EXPECTED_SYMBOL = "000001.SZ"
EXPECTED_START = date(2020, 6, 12)
EXPECTED_END = date(2020, 6, 19)
EXPECTED_BOOTSTRAP_START = date(2020, 6, 4)
EXPECTED_ANCHOR_DATE = date(2020, 6, 15)
EXPECTED_MODELS = tuple(model.value for model in SELLER_MODEL_ORDER)
MODEL_ORDER = {model: index for index, model in enumerate(EXPECTED_MODELS)}
REQUIRED_COLUMNS = {
    "storage_version",
    "model_version",
    "symbol",
    "trade_date",
    "seller_model",
    "snapshot_id",
    "decision_at",
    "available_at",
    "free_float_shares",
    "known_cost_fraction",
    "unknown_cost_fraction",
    "average_cost",
    "cost_p10",
    "cost_p50",
    "cost_p90",
    "checkpoint_local_ids",
    "checkpoint_shares",
    "checkpoint_economic_bucket_ids",
    "conservation_error_shares",
    "same_day_resale_shares",
    "minute_fallback",
    "hard_valid",
    "research_valid",
}


@dataclass(frozen=True)
class SourceBinding:
    asset_id: str
    registry_id: str
    root: Path
    manifest_path: Path
    manifest_sha256: str
    file_path: Path
    file_relative_path: str
    file_size: int
    file_sha256: str
    storage_version: str
    model_version: str
    pit_grade: str


@dataclass(frozen=True)
class BoundedSelection:
    table: pa.Table
    bootstrap_start: date
    all_dates: tuple[date, ...]
    target_dates: tuple[date, ...]
    target_rows: int


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _symbol_filename(symbol: str) -> str:
    if not symbol or any(character not in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ." for character in symbol):
        raise ValueError(f"unsupported symbol: {symbol!r}")
    return f"{symbol.replace('.', '_')}.parquet"


def bind_registered_source(
    registry_path: Path,
    *,
    source_asset: str,
    symbol: str,
    year: int,
) -> SourceBinding:
    registry = _read_json(registry_path.resolve())
    assets = registry.get("assets")
    if not isinstance(assets, list):
        raise ValueError("registry assets are invalid")
    matches = [item for item in assets if item.get("asset_id") == source_asset]
    if len(matches) != 1:
        raise ValueError(f"expected one registered source asset {source_asset}, found {len(matches)}")
    asset = matches[0]
    if asset.get("status") != "RESEARCH_CONDITIONAL":
        raise ValueError(f"source asset {source_asset} is not research-conditional")
    if asset.get("physical_state") != "MATERIALIZED":
        raise ValueError(f"source asset {source_asset} is not materialized")
    lineage = asset.get("lineage")
    if not isinstance(lineage, dict) or lineage.get("immutable_manifest") is not True:
        raise ValueError(f"source asset {source_asset} lacks an immutable manifest")
    manifest_path = Path(str(lineage.get("manifest_path", ""))).resolve()
    declared_manifest_hash = str(lineage.get("manifest_sha256", ""))
    if not manifest_path.is_file() or not declared_manifest_hash:
        raise ValueError(f"source asset {source_asset} manifest binding is incomplete")
    actual_manifest_hash = sha256_file(manifest_path)
    if actual_manifest_hash != declared_manifest_hash:
        raise ValueError(f"source asset {source_asset} manifest hash changed")

    manifest = _read_json(manifest_path)
    if manifest.get("status") != "PASS" or manifest.get("kind") != "chip_operator_lineage":
        raise ValueError(f"source asset {source_asset} manifest is not PASS chip lineage")
    root = Path(str(asset["location"])).resolve()
    if Path(str(manifest.get("location", ""))).resolve() != root:
        raise ValueError(f"source asset {source_asset} manifest location differs")
    patterns = tuple(root.glob(f"year={year}/parts/bucket=*/{_symbol_filename(symbol)}"))
    if len(patterns) != 1:
        raise FileNotFoundError(
            f"expected one source operator file for {symbol}/{year}, found {len(patterns)}"
        )
    file_path = patterns[0]
    relative_path = str(file_path.relative_to(root))
    inventory = manifest.get("inventory")
    if not isinstance(inventory, list):
        raise ValueError(f"source asset {source_asset} inventory is missing")
    entries = [item for item in inventory if item.get("path") == relative_path]
    if len(entries) != 1:
        raise ValueError(f"source operator file is not uniquely frozen: {relative_path}")
    entry = entries[0]
    file_size = file_path.stat().st_size
    file_hash = sha256_file(file_path)
    if file_size != int(entry.get("size", -1)) or file_hash != entry.get("sha256"):
        raise ValueError(f"source operator file changed after freeze: {relative_path}")
    seller_models = tuple(str(value) for value in manifest.get("seller_models", ()))
    if seller_models != EXPECTED_MODELS:
        raise ValueError("source manifest does not contain the three seller models in order")
    return SourceBinding(
        asset_id=source_asset,
        registry_id=str(registry["registry_id"]),
        root=root,
        manifest_path=manifest_path,
        manifest_sha256=actual_manifest_hash,
        file_path=file_path,
        file_relative_path=relative_path,
        file_size=file_size,
        file_sha256=file_hash,
        storage_version=str(manifest["storage_version"]),
        model_version=str(manifest["model_version"]),
        pit_grade=str(manifest["pit_grade"]),
    )


def select_bounded_rows(
    source: pa.Table,
    *,
    symbol: str,
    start: date,
    end: date,
) -> BoundedSelection:
    missing = sorted(REQUIRED_COLUMNS - set(source.column_names))
    if missing:
        raise ValueError(f"source operator schema is missing: {', '.join(missing)}")
    if end < start:
        raise ValueError("target end precedes target start")
    symbols = source["symbol"].to_pylist()
    if set(symbols) != {symbol}:
        raise ValueError("source operator file contains an unexpected symbol")
    dates = tuple(source["trade_date"].to_pylist())
    models = tuple(str(value) for value in source["seller_model"].to_pylist())
    checkpoints = source["checkpoint_local_ids"].to_pylist()
    if set(models) != set(EXPECTED_MODELS):
        raise ValueError("source rows do not contain exactly the three seller models")

    key_counts: dict[tuple[date, str], int] = {}
    checkpoint_dates = {model: set() for model in EXPECTED_MODELS}
    for day, model, checkpoint in zip(dates, models, checkpoints, strict=True):
        key = (day, model)
        key_counts[key] = key_counts.get(key, 0) + 1
        if day <= start and checkpoint:
            checkpoint_dates[model].add(day)
    duplicates = sorted(key for key, count in key_counts.items() if count != 1)
    if duplicates:
        raise ValueError(f"duplicate source date/model rows: {duplicates[:3]}")
    common_checkpoints = set.intersection(*(checkpoint_dates[model] for model in EXPECTED_MODELS))
    if not common_checkpoints:
        raise ValueError("no common checkpoint exists at or before the target start")
    bootstrap_start = max(common_checkpoints)

    target_dates = tuple(sorted({day for day in dates if start <= day <= end}))
    if not target_dates or target_dates[0] != start or target_dates[-1] != end:
        raise ValueError("target endpoints are not both present trading dates")
    selected_dates = tuple(sorted({day for day in dates if bootstrap_start <= day <= end}))
    for day in selected_dates:
        present = {model for row_day, model in key_counts if row_day == day}
        if present != set(EXPECTED_MODELS):
            raise ValueError(f"seller-model coverage differs on {day}")

    selected_indices = sorted(
        (
            index
            for index, day in enumerate(dates)
            if bootstrap_start <= day <= end
        ),
        key=lambda index: (dates[index], MODEL_ORDER[models[index]]),
    )
    selected = source.take(pa.array(selected_indices, type=pa.int64()))
    target_rows = sum(start <= dates[index] <= end for index in selected_indices)
    return BoundedSelection(
        table=selected,
        bootstrap_start=bootstrap_start,
        all_dates=selected_dates,
        target_dates=target_dates,
        target_rows=target_rows,
    )


def validate_quality(
    selection: BoundedSelection,
    *,
    start: date,
    end: date,
) -> dict[str, Any]:
    rows = selection.table.to_pylist()
    failures: list[str] = []
    if any(row["available_at"] > row["decision_at"] for row in rows):
        failures.append("available_at_after_decision_at")
    if any(not str(row["snapshot_id"]) for row in rows):
        failures.append("missing_snapshot_id")
    if any(float(row["conservation_error_shares"]) != 0.0 for row in rows):
        failures.append("nonzero_conservation_error")
    if any(float(row["same_day_resale_shares"]) != 0.0 for row in rows):
        failures.append("same_day_resale")
    if any(bool(row["minute_fallback"]) for row in rows):
        failures.append("minute_fallback")
    fraction_errors = tuple(
        abs(
            math.fsum(
                (
                    float(row["known_cost_fraction"]),
                    float(row["unknown_cost_fraction"]),
                )
            )
            - 1.0
        )
        for row in rows
    )
    max_fraction_error = max(fraction_errors, default=0.0)
    if max_fraction_error > 1e-12:
        failures.append("known_unknown_fraction_not_conserved")
    target = [row for row in rows if start <= row["trade_date"] <= end]
    if len(target) != selection.target_rows:
        failures.append("target_row_count_changed")
    if failures:
        raise ValueError("quality gates failed: " + ", ".join(failures))
    return {
        "status": "PASS",
        "available_at_lte_decision_at": True,
        "snapshot_ids_present": True,
        "mass_conservation": "EXACT_ZERO",
        "max_abs_conservation_error_shares": max(
            (abs(float(row["conservation_error_shares"])) for row in rows),
            default=0.0,
        ),
        "same_day_resale": "EXACT_ZERO",
        "max_abs_same_day_resale_shares": max(
            (abs(float(row["same_day_resale_shares"])) for row in rows),
            default=0.0,
        ),
        "minute_fallback_rows": 0,
        "max_known_unknown_fraction_error": max_fraction_error,
        "target_hard_valid_rows": sum(bool(row["hard_valid"]) for row in target),
        "target_research_valid_rows": sum(bool(row["research_valid"]) for row in target),
        "target_rows": len(target),
    }


def replay_lineage(
    root: Path,
    table: pa.Table,
    *,
    symbol: str,
    anchor_date: date,
    current_date: date,
) -> dict[str, Any]:
    rows = table.to_pylist()
    by_key = {(row["trade_date"], row["seller_model"]): row for row in rows}
    try:
        anchor_row = by_key[(anchor_date, "UNIFORM")]
        current_row = by_key[(current_date, "UNIFORM")]
    except KeyError as error:
        raise ValueError("lineage replay endpoints are missing") from error
    anchor_id = f"{ASSET_ID}:{symbol}:{anchor_date.isoformat()}"
    anchor = LifecycleAnchor(
        anchor_id=anchor_id,
        symbol=symbol,
        source_snapshot_id=str(anchor_row["snapshot_id"]),
        root_anchor_id=anchor_id,
        parent_anchor_id=None,
        role="ROOT",
        created_at=anchor_date,
        lower=float(anchor_row["cost_p10"]),
        upper=float(anchor_row["cost_p90"]),
        reference_mass=float(anchor_row["known_cost_fraction"]),
        average_cost=float(anchor_row["average_cost"]),
        cost_p50=float(anchor_row["cost_p50"]),
        band_width=float(anchor_row["cost_p90"] - anchor_row["cost_p10"]),
        peak_count=1,
        mass_method=ChipMassMethod.HISTOGRAM_EXACT,
    )
    price = float(current_row["cost_p50"])
    observation = LifecycleObservation(
        symbol=symbol,
        decision_at=current_row["decision_at"],
        available_at=current_row["available_at"],
        snapshot_ids=(str(current_row["snapshot_id"]),),
        hard_valid=bool(current_row["research_valid"]),
        tradable=True,
        pit_grade="B_RESEARCH_ONLY",
        setup_score=0.0,
        breakout_excess_atr=0.0,
        support_regained=False,
        downside_absorption=False,
        chip_profile=ChipMassProfile.from_histogram(
            (price,),
            (1.0,),
            mass_tolerance=1e-12,
        ),
        cost_p10=float(current_row["cost_p10"]),
        cost_p90=float(current_row["cost_p90"]),
        peak_count=1,
        recent_band_overlap=0.0,
        distribution_score=0.0,
        structure_support=float(current_row["cost_p10"]),
        close=price,
        close_vs_vwap=0.0,
        low=price,
        volume=0.0,
        turnover=0.0,
        average_cost=float(current_row["average_cost"]),
        cost_p50=price,
        prior_average_cost=float(current_row["average_cost"]),
        prior_cost_p50=price,
        atr=max(price * 0.01, 0.01),
    )
    estimate = PersistedChipLineageResolver(root)(anchor, observation)
    if estimate is None:
        raise ValueError("persisted three-model lineage replay returned no estimate")
    if not 0.0 <= estimate.lower <= estimate.central <= estimate.upper <= 1.0:
        raise ValueError("persisted lineage replay is outside [0, 1]")
    return {
        "status": "PASS",
        "anchor_date": anchor_date.isoformat(),
        "current_date": current_date.isoformat(),
        "central": estimate.central,
        "lower": estimate.lower,
        "upper": estimate.upper,
        "disagreement": estimate.disagreement,
        "models": [
            {"model": model.value, "retention": retention}
            for model, retention in estimate.model_retentions
        ],
    }


def _file_inventory(root: Path, paths: tuple[Path, ...]) -> list[dict[str, Any]]:
    return [
        {
            "path": str(path.relative_to(root)),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(paths)
    ]


def materialize(
    *,
    registry_path: Path,
    source_asset: str,
    symbol: str,
    start: date,
    end: date,
    anchor_date: date,
    output: Path,
) -> Path:
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"immutable output already exists: {output}")
    binding = bind_registered_source(
        registry_path,
        source_asset=source_asset,
        symbol=symbol,
        year=start.year,
    )
    source_table = pq.read_table(binding.file_path)
    if set(source_table["storage_version"].to_pylist()) != {binding.storage_version}:
        raise ValueError("source row storage version differs from its manifest")
    if set(source_table["model_version"].to_pylist()) != {binding.model_version}:
        raise ValueError("source row model version differs from its manifest")
    selection = select_bounded_rows(source_table, symbol=symbol, start=start, end=end)
    quality = validate_quality(selection, start=start, end=end)
    if (
        (source_asset, symbol, start, end)
        == (EXPECTED_SOURCE_ASSET, EXPECTED_SYMBOL, EXPECTED_START, EXPECTED_END)
        and (
            selection.bootstrap_start != EXPECTED_BOOTSTRAP_START
            or selection.table.num_rows != 36
            or selection.target_rows != 18
            or quality["target_hard_valid_rows"] != 0
            or quality["target_research_valid_rows"] != 18
        )
    ):
        raise ValueError("CY-030 fixed acceptance profile changed")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        data_path = temporary / f"parts/bucket=0/{_symbol_filename(symbol)}"
        data_path.parent.mkdir(parents=True)
        pq.write_table(
            selection.table,
            data_path,
            compression="zstd",
            compression_level=3,
            use_dictionary=True,
            row_group_size=4096,
        )
        written_table = pq.read_table(data_path)
        if written_table.schema != selection.table.schema or not written_table.equals(
            selection.table
        ):
            raise ValueError("materialized Parquet differs from the selected source rows")
        index_path = build_operator_symbol_index(temporary)
        replay = replay_lineage(
            temporary,
            selection.table,
            symbol=symbol,
            anchor_date=anchor_date,
            current_date=end,
        )
        files = _file_inventory(temporary, (data_path, index_path))
        inventory_identity = hashlib.sha256(_canonical_json(files)).hexdigest()
        identity = {
            "source_asset": binding.asset_id,
            "source_manifest_sha256": binding.manifest_sha256,
            "source_file_sha256": binding.file_sha256,
            "symbol": symbol,
            "bootstrap_start": selection.bootstrap_start.isoformat(),
            "target_start": start.isoformat(),
            "target_end": end.isoformat(),
            "inventory_identity_sha256": inventory_identity,
        }
        snapshot_id = f"cy030-{hashlib.sha256(_canonical_json(identity)).hexdigest()}"
        manifest = {
            "schema_version": 1,
            "status": "PASS",
            "asset_id": ASSET_ID,
            "kind": "bounded_single_stock_exact_chip_lineage",
            "pit_grade": "B",
            "created_at": datetime.now(UTC).isoformat(),
            "snapshot_id": snapshot_id,
            "location": str(output),
            "coverage": {
                "symbol": symbol,
                "bootstrap_start": selection.bootstrap_start.isoformat(),
                "target_start": start.isoformat(),
                "target_end": end.isoformat(),
                "dates": [day.isoformat() for day in selection.all_dates],
                "target_dates": [day.isoformat() for day in selection.target_dates],
                "seller_models": list(EXPECTED_MODELS),
                "rows": selection.table.num_rows,
                "target_rows": selection.target_rows,
            },
            "source": {
                "registry_id": binding.registry_id,
                "asset_id": binding.asset_id,
                "manifest_path": str(binding.manifest_path),
                "manifest_sha256": binding.manifest_sha256,
                "file_path": str(binding.file_path),
                "file_relative_path": binding.file_relative_path,
                "file_size": binding.file_size,
                "file_sha256": binding.file_sha256,
                "storage_version": binding.storage_version,
                "model_version": binding.model_version,
                "pit_grade": binding.pit_grade,
            },
            "schema": {
                "arrow_schema_sha256": hashlib.sha256(
                    selection.table.schema.serialize().to_pybytes()
                ).hexdigest(),
                "fields": selection.table.schema.names,
                "preserved_without_value_rewrite": True,
            },
            "quality_evidence": {**quality, "lineage_replay": replay},
            "files": files,
            "inventory": files,
            "inventory_files": len(files),
            "inventory_bytes": sum(int(item["size"]) for item in files),
            "inventory_identity_sha256": inventory_identity,
            "measurement_contract": {
                "seller_models": list(EXPECTED_MODELS),
                "same_day_resale": "FORBIDDEN_T_PLUS_ONE",
                "mass_conservation": "EXACT_ZERO_IN_SAMPLE",
                "unknown_cost": "PRESERVED_EXPLICITLY",
                "strict_validity_relabeling": "FORBIDDEN",
            },
            "allowed_uses": [
                "bounded 000001.SZ exact-chip lineage replay for 2020-06-12 through 2020-06-19",
                "research-only inspection of the three seller-model inventories and features",
            ],
            "blocked_uses": [
                "strict PIT-A or real-holder truth claims",
                "live trading, sizing, performance claims or same-bar execution",
                "use outside the frozen symbol and target interval",
                "replacement of CY-020 or its registered raw components",
            ],
            "activation_gates": [
                "the CY-020 source manifest and selected source file remain hash-identical",
                "the complete CY-030 inventory and manifest remain hash-identical",
                "runtime preserves research_valid separately from hard_valid",
                "runtime uses all three seller models and available_at <= decision_at",
            ],
        }
        manifest_path = temporary / "asset_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, output)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return output / "asset_manifest.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-asset", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--registry",
        type=Path,
        default=ROOT / "configs/data_asset_registry.json",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    expected = (EXPECTED_SOURCE_ASSET, EXPECTED_SYMBOL, EXPECTED_START, EXPECTED_END)
    requested = (args.source_asset, args.symbol, args.start, args.end)
    if requested != expected:
        raise ValueError(
            "CY-030 is bounded to CY-020 / 000001.SZ / 2020-06-12..2020-06-19"
        )
    manifest = materialize(
        registry_path=args.registry,
        source_asset=args.source_asset,
        symbol=args.symbol,
        start=args.start,
        end=args.end,
        anchor_date=EXPECTED_ANCHOR_DATE,
        output=args.output,
    )
    payload = _read_json(manifest)
    coverage = payload["coverage"]
    quality = payload["quality_evidence"]
    if (
        coverage["bootstrap_start"] != EXPECTED_BOOTSTRAP_START.isoformat()
        or coverage["rows"] != 36
        or coverage["target_rows"] != 18
        or quality["target_hard_valid_rows"] != 0
        or quality["target_research_valid_rows"] != 18
    ):
        raise ValueError("CY-030 fixed acceptance profile changed")
    print(
        json.dumps(
            {
                "status": "PASS",
                "asset_id": ASSET_ID,
                "rows": coverage["rows"],
                "target_rows": coverage["target_rows"],
                "manifest": str(manifest),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
