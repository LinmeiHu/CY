from __future__ import annotations

import hashlib
import json
import runpy
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "materialize_single_stock_chip_sample.py"
MODULE = runpy.run_path(str(SCRIPT))
MODELS = ("UNIFORM", "DISPOSITION", "ACTIVE_STICKY")
ARTIFACT_ROOT = (
    ROOT
    / "data/registered_inputs/CY-030-000001-CHIP-20200612-20200619-V1"
)


def _table(*, common_checkpoint: bool = True) -> pa.Table:
    timezone = ZoneInfo("Asia/Shanghai")
    rows: list[dict[str, object]] = []
    days = (date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 4), date(2020, 1, 5))
    for day_index, day in enumerate(days):
        for model_index, model in enumerate(MODELS):
            checkpoint = day_index == 0 and (common_checkpoint or model_index != 2)
            rows.append(
                {
                    "storage_version": "chip-operator-log-v11",
                    "model_version": "real-chip-inventory-v2.1",
                    "symbol": "000001.SZ",
                    "trade_date": day,
                    "seller_model": model,
                    "snapshot_id": f"snapshot-{day}-{model}",
                    "decision_at": datetime.combine(day, datetime.min.time(), timezone),
                    "available_at": datetime.combine(day, datetime.min.time(), timezone),
                    "free_float_shares": 100.0,
                    "known_cost_fraction": 0.9,
                    "unknown_cost_fraction": 0.1,
                    "average_cost": 10.0,
                    "cost_p10": 9.0,
                    "cost_p50": 10.0,
                    "cost_p90": 11.0,
                    "checkpoint_local_ids": [1] if checkpoint else [],
                    "checkpoint_shares": [100.0] if checkpoint else [],
                    "checkpoint_economic_bucket_ids": [100] if checkpoint else [],
                    "conservation_error_shares": 0.0,
                    "same_day_resale_shares": 0.0,
                    "minute_fallback": False,
                    "hard_valid": False,
                    "research_valid": True,
                }
            )
    return pa.Table.from_pylist(rows)


def test_selection_includes_nearest_common_checkpoint_without_changing_schema() -> None:
    source = _table()

    selected = MODULE["select_bounded_rows"](
        source,
        symbol="000001.SZ",
        start=date(2020, 1, 4),
        end=date(2020, 1, 5),
    )

    assert selected.bootstrap_start == date(2020, 1, 2)
    assert selected.target_dates == (date(2020, 1, 4), date(2020, 1, 5))
    assert selected.table.num_rows == 12
    assert selected.target_rows == 6
    assert selected.table.schema == source.schema
    assert selected.table["seller_model"].to_pylist()[:3] == list(MODELS)


def test_selection_fails_closed_without_a_common_checkpoint() -> None:
    source = _table(common_checkpoint=False)

    with pytest.raises(ValueError, match="common checkpoint"):
        MODULE["select_bounded_rows"](
            source,
            symbol="000001.SZ",
            start=date(2020, 1, 4),
            end=date(2020, 1, 5),
        )


def test_cy030_frozen_sample_is_registered_and_replayable() -> None:
    if not ARTIFACT_ROOT.is_dir():
        pytest.skip("local registered CY-030 data asset is not materialized")
    registry = json.loads(
        (ROOT / "configs/data_asset_registry.json").read_text(encoding="utf-8")
    )
    asset = next(item for item in registry["assets"] if item["asset_id"] == "CY-030")
    manifest_path = ARTIFACT_ROOT / "asset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    data_path = ARTIFACT_ROOT / "parts/bucket=0/000001_SZ.parquet"
    table = pq.read_table(data_path)

    assert Path(asset["location"]).resolve() == ARTIFACT_ROOT.resolve()
    assert asset["lineage"]["manifest_sha256"] == hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    assert manifest["status"] == "PASS"
    assert manifest["asset_id"] == "CY-030"
    assert manifest["coverage"]["bootstrap_start"] == "2020-06-04"
    assert manifest["coverage"]["target_start"] == "2020-06-12"
    assert manifest["coverage"]["target_end"] == "2020-06-19"
    assert manifest["coverage"]["rows"] == 36
    assert manifest["coverage"]["target_rows"] == 18
    assert table.num_rows == 36
    assert set(table["seller_model"].to_pylist()) == set(MODELS)
    assert manifest["schema"]["arrow_schema_sha256"] == hashlib.sha256(
        table.schema.serialize().to_pybytes()
    ).hexdigest()

    rows = table.to_pylist()
    target = [row for row in rows if date(2020, 6, 12) <= row["trade_date"] <= date(2020, 6, 19)]
    assert len(target) == 18
    assert sum(bool(row["hard_valid"]) for row in target) == 0
    assert sum(bool(row["research_valid"]) for row in target) == 18
    assert all(row["available_at"] <= row["decision_at"] for row in rows)
    assert all(float(row["conservation_error_shares"]) == 0.0 for row in rows)
    assert all(float(row["same_day_resale_shares"]) == 0.0 for row in rows)
    assert not any(bool(row["minute_fallback"]) for row in rows)
    assert all(
        abs(
            float(row["known_cost_fraction"])
            + float(row["unknown_cost_fraction"])
            - 1.0
        )
        <= 1e-12
        for row in rows
    )

    replay = MODULE["replay_lineage"](
        ARTIFACT_ROOT,
        table,
        symbol="000001.SZ",
        anchor_date=date(2020, 6, 15),
        current_date=date(2020, 6, 19),
    )
    assert 0.0 <= replay["lower"] <= replay["central"] <= replay["upper"] <= 1.0
    assert tuple(item["model"] for item in replay["models"]) == MODELS
