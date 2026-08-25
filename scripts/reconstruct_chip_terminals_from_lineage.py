#!/usr/bin/env python3
"""Reconstruct exact terminal chip inventories from v11 operator checkpoints."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_real_chip_year as builder  # noqa: E402

from cyq_game.chip.ensemble_v2 import SELLER_MODEL_ORDER  # noqa: E402
from cyq_game.chip.migration_v2 import (  # noqa: E402
    StableLogPriceGrid,
    economic_break_even_for_bucket,
)
from cyq_game.chip.state_v2 import (  # noqa: E402
    ChipSnapshotV2,
    InventoryCell,
    SellerModel,
    SnapshotPhase,
    SparseChipInventory,
    TurnoverSensitivity,
    stable_cell_id,
    tolerance,
)
from cyq_game.strategy.chip_lineage import (  # noqa: E402
    PersistedChipLineageResolver,
    _unpack_local_id,
)

GRID = StableLogPriceGrid(1.0, 0.0025, builder.GRID_VERSION)
SENSITIVITIES = (
    TurnoverSensitivity.ACTIVE,
    TurnoverSensitivity.NEUTRAL,
    TurnoverSensitivity.STICKY,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lineage-year-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--symbols", nargs="*", default=[])
    parser.add_argument("--lineage-asset-id", default="CY-020")
    parser.add_argument("--lineage-manifest-sha256", required=True)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _model_rows(rows: list[dict[str, Any]], model: SellerModel) -> list[dict[str, Any]]:
    selected = sorted(
        (row for row in rows if row["seller_model"] == model.value),
        key=lambda row: row["trade_date"],
    )
    if not selected:
        raise ValueError(f"missing model {model.value}")
    return selected


def _replay_terminal(
    rows: list[dict[str, Any]],
    model: SellerModel,
    *,
    symbol: str,
    lineage_asset_id: str,
    lineage_manifest_sha256: str,
) -> ChipSnapshotV2:
    selected = _model_rows(rows, model)
    checkpoint_index = max(
        index
        for index, row in enumerate(selected)
        if row.get("checkpoint_local_ids")
    )
    checkpoint = selected[checkpoint_index]
    local_ids = tuple(int(value) for value in checkpoint["checkpoint_local_ids"])
    shares = tuple(float(value) for value in checkpoint["checkpoint_shares"])
    raw_economic = checkpoint.get("checkpoint_economic_bucket_ids")
    if raw_economic is None:
        raise ValueError("v11 economic checkpoint coordinates are required")
    if len(local_ids) != len(shares) or len(local_ids) != len(raw_economic):
        raise ValueError("checkpoint columns differ in length")
    inventory = dict(zip(local_ids, shares, strict=True))
    economic = {
        local_id: None if bucket is None else int(bucket)
        for local_id, bucket in zip(local_ids, raw_economic, strict=True)
    }
    for row in selected[checkpoint_index + 1 :]:
        inventory, _, economic = PersistedChipLineageResolver._advance(
            inventory, None, economic, row
        )
    final = selected[-1]
    expected_mass = float(final["free_float_shares"])
    actual_mass = math.fsum(inventory.values())
    if abs(actual_mass - expected_mass) > tolerance(expected_mass):
        raise ValueError(f"reconstructed mass differs: {actual_mass} != {expected_mass}")
    cells: list[InventoryCell] = []
    by_economic_bucket: dict[int, float] = {}
    for local_id, cell_shares in inventory.items():
        cost_bucket, holding_days, sensitivity_code = _unpack_local_id(local_id)
        sensitivity = SENSITIVITIES[sensitivity_code]
        if builder._pack_cell_dimensions(  # type: ignore[attr-defined]
            cost_bucket, holding_days, sensitivity_code
        ) != local_id:
            raise ValueError("local cell id is not reversible")
        economic_bucket = economic.get(local_id)
        economic_break_even = (
            None
            if economic_bucket is None
            else economic_break_even_for_bucket(GRID, economic_bucket)
        )
        if economic_bucket is not None:
            by_economic_bucket[economic_bucket] = (
                by_economic_bucket.get(economic_bucket, 0.0) + cell_shares
            )
        cells.append(
            InventoryCell(
                cell_id=stable_cell_id(
                    cost_bucket_id=cost_bucket,
                    holding_days=holding_days,
                    sensitivity=sensitivity,
                ),
                cost_bucket_id=cost_bucket,
                holding_days=holding_days,
                sensitivity=sensitivity,
                acquisition_cost=(
                    None if cost_bucket is None else GRID.price_for_bucket(cost_bucket)
                ),
                economic_break_even=economic_break_even,
                shares=cell_shares,
                # This diagnostic weight does not enter any seller decision or
                # mass equation and is not persisted in compact v11 operators.
                initialization_prior_units=0.0,
            )
        )
    profile = builder._profile_from_bucket_mass(by_economic_bucket, GRID)  # type: ignore[attr-defined]
    for key, column in (
        ("p10", "cost_p10"),
        ("p50", "cost_p50"),
        ("p90", "cost_p90"),
        ("peak", "main_peak"),
    ):
        expected = final.get(column)
        actual = None if profile is None else profile[key]
        if expected is None and actual is None:
            continue
        if expected is None or actual is None or not math.isclose(
            float(expected), float(actual), rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError(f"profile mismatch for {model.value}/{column}")
    expected_average = final.get("average_cost")
    actual_average = None if profile is None else profile["average"]
    if expected_average is None and actual_average is None:
        pass
    elif (
        expected_average is None
        or actual_average is None
        or abs(float(expected_average) - float(actual_average))
        > max(1e-12, abs(float(expected_average)) * GRID.step_pct)
    ):
        # Economic coordinates in v11 are intentionally stored on the same
        # 25bp decision grid as the model.  A collision can move a weighted
        # floating average within one grid step while every quantile, peak and
        # profit/loss boundary remains exactly reconstructible.
        raise ValueError(f"profile mismatch for {model.value}/average_cost")
    final_day = final["trade_date"]
    if not isinstance(final_day, date):
        final_day = date.fromisoformat(str(final_day))
    reanchor_id = hashlib.sha256(
        (
            f"{lineage_asset_id}|{lineage_manifest_sha256}|{symbol}|"
            f"{model.value}|{final_day}|{final['snapshot_id']}"
        ).encode()
    ).hexdigest()
    return ChipSnapshotV2(
        symbol=symbol,
        trading_date=final_day,
        decision_at=builder._timestamp(final["decision_at"]),  # type: ignore[attr-defined]
        effective_at=builder._timestamp(final["decision_at"]),  # type: ignore[attr-defined]
        available_at=builder._timestamp(final["available_at"]),  # type: ignore[attr-defined]
        phase=SnapshotPhase.POST,
        snapshot_id=f"chip_terminal_reanchor_{reanchor_id}",
        model_version=builder.MODEL_VERSION,
        grid_version=builder.GRID_VERSION,
        seller_model=model,
        inventory=SparseChipInventory.canonical(cells),
        free_float_shares=expected_mass,
        latent_supply_shares=0.0,
        input_snapshot_ids=(
            f"asset:{lineage_asset_id}:{lineage_manifest_sha256}",
            f"source_snapshot:{final['snapshot_id']}",
        ),
        pit_grade="B",
        hard_valid=bool(final["hard_valid"]),
        quality_reason_codes=tuple(final.get("quality_reason_codes") or ()),
    )


def _destination(output_root: Path, source: Path) -> Path:
    return output_root / "terminal" / source.parent.name / source.name


def _reconstruct_one(
    payload: tuple[Path, Path, str, str],
) -> dict[str, Any]:
    source, output_root, lineage_asset_id, lineage_manifest_sha256 = payload
    started = time.perf_counter()
    symbol = source.stem.replace("_SH", ".SH").replace("_SZ", ".SZ")
    destination = _destination(output_root, source)
    if destination.exists():
        snapshots = builder._read_terminal_snapshots(  # type: ignore[attr-defined]
            destination, symbol
        )
        return {
            "symbol": symbol,
            "resumed": True,
            "date": next(iter(snapshots.values())).trading_date.isoformat(),
            "seconds": 0.0,
        }
    rows = pq.read_table(source).to_pylist()
    snapshots = {
        model: _replay_terminal(
            rows,
            model,
            symbol=symbol,
            lineage_asset_id=lineage_asset_id,
            lineage_manifest_sha256=lineage_manifest_sha256,
        )
        for model in SELLER_MODEL_ORDER
    }
    temporary = destination.with_suffix(".tmp.parquet")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary.unlink(missing_ok=True)
    builder._write_terminal_snapshots(temporary, snapshots)  # type: ignore[attr-defined]
    builder._read_terminal_snapshots(temporary, symbol)  # type: ignore[attr-defined]
    temporary.replace(destination)
    return {
        "symbol": symbol,
        "resumed": False,
        "date": next(iter(snapshots.values())).trading_date.isoformat(),
        "seconds": round(time.perf_counter() - started, 3),
    }


def main() -> int:
    args = _parse_args()
    lineage_root = args.lineage_year_root.resolve()
    output_root = args.output_root.resolve()
    requested = set(args.symbols)
    sources = sorted(lineage_root.glob("parts/bucket=*/*.parquet"))
    if requested:
        sources = [
            path
            for path in sources
            if path.stem.replace("_SH", ".SH").replace("_SZ", ".SZ") in requested
        ]
    if not sources:
        raise ValueError("no lineage files matched")
    payloads = [
        (path, output_root, args.lineage_asset_id, args.lineage_manifest_sha256)
        for path in sources
    ]
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    with ProcessPoolExecutor(max_workers=min(args.workers, len(payloads))) as executor:
        futures = {executor.submit(_reconstruct_one, payload): payload[0] for payload in payloads}
        for position, future in enumerate(as_completed(futures), start=1):
            source = futures[future]
            try:
                results.append(future.result())
            except Exception as error:
                failures.append(
                    {"source": str(source), "error": f"{type(error).__name__}: {error}"}
                )
            if position % 250 == 0:
                print(
                    json.dumps(
                        {"completed": position, "total": len(payloads), "failed": len(failures)}
                    ),
                    flush=True,
                )
    coverage = len(results) / len(payloads)
    summary = {
        "status": "PASS" if coverage >= 0.95 else "FAIL",
        "lineage_asset_id": args.lineage_asset_id,
        "lineage_manifest_sha256": args.lineage_manifest_sha256,
        "source_root": str(lineage_root),
        "sources": len(payloads),
        "passed": len(results),
        "coverage": coverage,
        "dates": sorted({result["date"] for result in results}),
        "resumed": sum(result["resumed"] for result in results),
        "failures": failures,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
