"""Build future outcome labels outside the causal predictor namespace."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from cyq_game.strategy.markup_retest import (
    MarkupRetestConfig,
    StrategyStage,
    load_passing_frozen_parameters,
)
from cyq_game.strategy.panel import PanelBuildResult, _verify_inventory
from cyq_game.strategy.semantic_contract import (
    LABEL_SCHEMA_VERSION,
    require_active_semantic_epoch,
    semantic_fingerprint_fields,
)


@dataclass(frozen=True)
class LabelBuildResult:
    stage: str
    status: str
    path: Path
    manifest_path: Path
    rows: int
    valid_rows: int
    config_sha256: str
    panel_snapshot_id: str
    label_snapshot_id: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["path"] = str(self.path)
        payload["manifest_path"] = str(self.manifest_path)
        return payload


def label_path(config: MarkupRetestConfig, stage: StrategyStage | str) -> Path:
    boundary = config.stage(stage)
    return config.outputs.label_root / boundary.name.value / config.sha256[:12]


def build_future_labels(
    config: MarkupRetestConfig,
    panel: PanelBuildResult,
    stage: StrategyStage | str,
    *,
    reuse: bool = True,
    threads: int | None = None,
) -> LabelBuildResult:
    """Build 5/10/20-day outcomes; this output is never a signal input."""

    boundary = config.stage(stage)
    if panel.stage != boundary.name.value:
        raise ValueError("label stage does not match causal panel stage")
    if panel.config_sha256 != config.sha256:
        raise ValueError("label panel config hash mismatch")
    if boundary.name == StrategyStage.RESEALED:
        load_passing_frozen_parameters(config)

    builder_sha256 = _sha256(Path(__file__))
    target = label_path(config, boundary.name)
    manifest_path = target / "manifest.json"
    if reuse and manifest_path.is_file():
        return _load_manifest(
            manifest_path,
            expected_config_sha=config.sha256,
            expected_panel_snapshot=panel.panel_snapshot_id,
            expected_builder_sha=builder_sha256,
        )
    if target.exists():
        raise FileExistsError(
            f"label target exists without a reusable matching manifest: {target}"
        )

    panel_files = tuple(sorted(panel.path.rglob("*.parquet")))
    if not panel_files:
        raise FileNotFoundError(f"causal panel has no parquet files: {panel.path}")
    temp = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    if temp.exists():
        shutil.rmtree(temp)
    temp.mkdir(parents=True)
    db_path = temp / "labels.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        con.execute(f"PRAGMA threads={threads or max(1, (os.cpu_count() or 2) - 1)}")
        con.execute("PRAGMA memory_limit='24GB'")
        con.execute("PRAGMA preserve_insertion_order=false")
        _create_labels(con, config, panel_files, panel.panel_snapshot_id)
        rows, valid_rows = _metrics(con)
        data_root = temp / "data"
        data_root.mkdir()
        con.execute(
            f"""
            COPY (
                SELECT * FROM future_labels ORDER BY trade_date, symbol
            ) TO {_sql_text(str(data_root))} (
                FORMAT PARQUET,
                COMPRESSION ZSTD,
                PARTITION_BY (partition_year, symbol_bucket)
            )
            """
        )
    finally:
        con.close()
        db_path.unlink(missing_ok=True)

    parquet_files = sorted((temp / "data").rglob("*.parquet"))
    if not parquet_files:
        shutil.rmtree(temp)
        raise RuntimeError("future label build produced no parquet files")
    inventory = [
        {
            "path": str(path.relative_to(temp)),
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in parquet_files
    ]
    snapshot_payload = {
        **semantic_fingerprint_fields(),
        "schema_version": LABEL_SCHEMA_VERSION,
        "strategy_version": config.strategy_version,
        "stage": boundary.name.value,
        "config_sha256": config.sha256,
        "builder_sha256": builder_sha256,
        "panel_snapshot_id": panel.panel_snapshot_id,
        "inventory": inventory,
        "rows": rows,
        "valid_rows": valid_rows,
    }
    label_snapshot_id = "labels-" + hashlib.sha256(
        json.dumps(snapshot_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    payload = {
        **snapshot_payload,
        "status": "COMPLETE",
        "created_at": datetime.now(UTC).isoformat(),
        "label_snapshot_id": label_snapshot_id,
        "physical_isolation": True,
        "authorized_signal_input": False,
        "maximum_source_date": boundary.max_input_date.isoformat(),
    }
    (temp / "manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    temp.rename(target)
    return _load_manifest(
        target / "manifest.json",
        expected_config_sha=config.sha256,
        expected_panel_snapshot=panel.panel_snapshot_id,
        expected_builder_sha=builder_sha256,
    )


def _create_labels(
    con: duckdb.DuckDBPyConnection,
    config: MarkupRetestConfig,
    panel_files: tuple[Path, ...],
    panel_snapshot_id: str,
) -> None:
    horizon = config.windows.label_horizon
    if horizon != 20:
        raise ValueError("v1 label horizon must remain fixed at 20 trading rows")
    round_trip_cost = 2.0 * config.execution.one_way_cost_fraction
    con.execute(
        f"""
        CREATE TABLE future_labels AS
        WITH forward AS (
            SELECT
                symbol,
                trade_date,
                decision_at,
                board,
                industry,
                sector_fallback,
                amount_mean20,
                realized_volatility,
                momentum_20,
                daily_snapshot_id,
                feature_daily_snapshot_id,
                feature_minute_snapshot_id,
                strategy_config_sha256,
                is_evaluation_row,
                lead(trade_date, 1) OVER symbol_window AS entry_date,
                lead(open, 1) OVER symbol_window AS entry_price,
                lead(close, 5) OVER symbol_window AS close_5d,
                lead(close, 10) OVER symbol_window AS close_10d,
                lead(close, 20) OVER symbol_window AS close_20d,
                lead(decision_at, 20) OVER symbol_window AS label_available_at,
                max(high) OVER horizon_window AS maximum_future_high,
                min(low) OVER horizon_window AS minimum_future_low,
                sum(coalesce(corporate_action_count, 0)) OVER horizon_window
                    AS corporate_actions_in_horizon
            FROM read_parquet({_sql_list(panel_files)}, union_by_name=true)
            WINDOW
                symbol_window AS (PARTITION BY symbol ORDER BY trade_date),
                horizon_window AS (
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN 1 FOLLOWING AND {horizon} FOLLOWING
                )
        )
        SELECT
            symbol,
            trade_date,
            decision_at,
            board,
            industry,
            sector_fallback,
            amount_mean20,
            realized_volatility,
            momentum_20,
            daily_snapshot_id,
            feature_daily_snapshot_id,
            feature_minute_snapshot_id,
            strategy_config_sha256,
            '{panel_snapshot_id}' AS panel_snapshot_id,
            entry_date,
            entry_price,
            close_5d / entry_price - 1.0 AS gross_return_5d,
            close_10d / entry_price - 1.0 AS gross_return_10d,
            close_20d / entry_price - 1.0 AS gross_return_20d,
            close_5d / entry_price - 1.0 - {round_trip_cost} AS net_return_5d,
            close_10d / entry_price - 1.0 - {round_trip_cost} AS net_return_10d,
            close_20d / entry_price - 1.0 - {round_trip_cost} AS net_return_20d,
            maximum_future_high / entry_price - 1.0 AS mfe_20d,
            minimum_future_low / entry_price - 1.0 AS mae_20d,
            label_available_at,
            corporate_actions_in_horizon,
            entry_price > 0 AND close_20d > 0 AND label_available_at IS NOT NULL
                AND corporate_actions_in_horizon = 0 AS label_valid,
            CASE
                WHEN label_available_at IS NULL THEN 'HORIZON_NOT_OBSERVED'
                WHEN entry_price IS NULL OR entry_price <= 0 THEN 'ENTRY_PRICE_INVALID'
                WHEN close_20d IS NULL OR close_20d <= 0 THEN 'EXIT_PRICE_INVALID'
                WHEN corporate_actions_in_horizon > 0 THEN 'CORPORATE_ACTION_IN_HORIZON'
                ELSE 'VALID'
            END AS label_reason,
            year(trade_date)::INTEGER AS partition_year,
            abs(hash(symbol) % 32)::INTEGER AS symbol_bucket
        FROM forward
        WHERE is_evaluation_row
        """
    )


def _metrics(con: duckdb.DuckDBPyConnection) -> tuple[int, int]:
    row = con.execute(
        "SELECT count(*), count(*) FILTER (WHERE label_valid) FROM future_labels"
    ).fetchone()
    if row is None:
        raise RuntimeError("future label metrics returned no row")
    return int(row[0]), int(row[1])


def _load_manifest(
    path: Path,
    *,
    expected_config_sha: str,
    expected_panel_snapshot: str,
    expected_builder_sha: str,
) -> LabelBuildResult:
    payload = json.loads(path.read_text())
    require_active_semantic_epoch(payload, artifact_name="labels")
    if payload.get("status") != "COMPLETE":
        raise ValueError(f"label manifest is not complete: {path}")
    if payload.get("config_sha256") != expected_config_sha:
        raise ValueError(f"label config hash mismatch: {path}")
    if payload.get("panel_snapshot_id") != expected_panel_snapshot:
        raise ValueError(f"label panel snapshot mismatch: {path}")
    if payload.get("builder_sha256") != expected_builder_sha:
        raise ValueError(f"label builder hash mismatch: {path}")
    _verify_inventory(path.parent, payload)
    snapshot_payload = {
        **semantic_fingerprint_fields(),
        "schema_version": payload.get("schema_version"),
        "strategy_version": payload.get("strategy_version"),
        "stage": payload.get("stage"),
        "config_sha256": payload.get("config_sha256"),
        "builder_sha256": payload.get("builder_sha256"),
        "panel_snapshot_id": payload.get("panel_snapshot_id"),
        "inventory": payload.get("inventory"),
        "rows": payload.get("rows"),
        "valid_rows": payload.get("valid_rows"),
    }
    expected_snapshot = "labels-" + hashlib.sha256(
        json.dumps(snapshot_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if payload.get("label_snapshot_id") != expected_snapshot:
        raise ValueError(f"label snapshot hash mismatch: {path}")
    return LabelBuildResult(
        stage=str(payload["stage"]),
        status=str(payload["status"]),
        path=path.parent / "data",
        manifest_path=path,
        rows=int(payload["rows"]),
        valid_rows=int(payload["valid_rows"]),
        config_sha256=str(payload["config_sha256"]),
        panel_snapshot_id=str(payload["panel_snapshot_id"]),
        label_snapshot_id=str(payload["label_snapshot_id"]),
    )


def _sql_list(paths: tuple[Path, ...]) -> str:
    return "[" + ",".join(_sql_text(str(path)) for path in paths) + "]"


def _sql_text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
