"""Build future outcome labels outside the causal predictor namespace."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from bisect import bisect_right
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from itertools import groupby
from pathlib import Path
from typing import Any

import duckdb

from cyq_game.strategy.markup_retest import (
    MarkupRetestConfig,
    StrategyStage,
    load_passing_frozen_parameters,
)
from cyq_game.strategy.execution import (
    EntryExecutionStatus,
    ExecutionWindow,
    resolve_next_legal_fill,
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
    execution_files = tuple(
        config.assets.execution_file(year) for year in boundary.years()
    )
    config.assert_input_files(boundary.name, execution_files)
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
        _materialize_legal_entry_fills(
            con,
            config=config,
            panel_files=panel_files,
            execution_files=execution_files,
        )
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
        WITH base AS (
            SELECT
                p.symbol,
                p.trade_date,
                p.decision_at,
                p.board,
                p.industry,
                p.sector_fallback,
                p.amount_mean20,
                p.realized_volatility,
                p.momentum_20,
                p.daily_snapshot_id,
                p.feature_daily_snapshot_id,
                p.feature_minute_snapshot_id,
                p.strategy_config_sha256,
                p.is_evaluation_row,
                f.entry_date,
                f.entry_price,
                f.entry_available_at,
                f.entry_snapshot_id,
                f.execution_status,
                f.execution_reason
            FROM read_parquet({_sql_list(panel_files)}, union_by_name=true) p
            LEFT JOIN label_entry_fills f USING (symbol, trade_date)
            WHERE p.is_evaluation_row
        ), outcomes AS (
            SELECT
                b.*,
                o.close_5d,
                o.close_10d,
                o.close_20d,
                o.label_available_at,
                o.maximum_future_high,
                o.minimum_future_low,
                o.corporate_actions_in_horizon
            FROM base b
            LEFT JOIN LATERAL (
                SELECT
                    max(close) FILTER (WHERE rn = 5) AS close_5d,
                    max(close) FILTER (WHERE rn = 10) AS close_10d,
                    max(close) FILTER (WHERE rn = 20) AS close_20d,
                    max(decision_at) FILTER (WHERE rn = 20) AS label_available_at,
                    max(high) AS maximum_future_high,
                    min(low) AS minimum_future_low,
                    sum(coalesce(corporate_action_count, 0))
                        AS corporate_actions_in_horizon
                FROM (
                    SELECT
                        x.close, x.high, x.low, x.decision_at,
                        x.corporate_action_count,
                        row_number() OVER (ORDER BY x.trade_date) AS rn
                    FROM read_parquet({_sql_list(panel_files)}, union_by_name=true) x
                    WHERE x.symbol = b.symbol AND x.trade_date > b.entry_date
                    ORDER BY x.trade_date
                    LIMIT {horizon}
                ) future_rows
            ) o ON true
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
            entry_available_at,
            entry_snapshot_id,
            execution_status,
            execution_reason,
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
            execution_status = 'FILLED' AND entry_price > 0
                AND close_20d > 0 AND label_available_at IS NOT NULL
                AND corporate_actions_in_horizon = 0 AS label_valid,
            CASE
                WHEN execution_status <> 'FILLED' THEN execution_reason
                WHEN label_available_at IS NULL THEN 'HORIZON_NOT_OBSERVED'
                WHEN entry_price IS NULL OR entry_price <= 0 THEN 'ENTRY_PRICE_INVALID'
                WHEN close_20d IS NULL OR close_20d <= 0 THEN 'EXIT_PRICE_INVALID'
                WHEN corporate_actions_in_horizon > 0 THEN 'CORPORATE_ACTION_IN_HORIZON'
                ELSE 'VALID'
            END AS label_reason,
            year(trade_date)::INTEGER AS partition_year,
            abs(hash(symbol) % 32)::INTEGER AS symbol_bucket
        FROM outcomes
        WHERE is_evaluation_row
        """
    )


def _materialize_legal_entry_fills(
    con: duckdb.DuckDBPyConnection,
    *,
    config: MarkupRetestConfig,
    panel_files: tuple[Path, ...],
    execution_files: tuple[Path, ...],
) -> None:
    """Resolve every label entry through the live execution resolver."""

    con.execute(
        """
        CREATE TABLE label_entry_fills (
            symbol VARCHAR,
            trade_date DATE,
            entry_date DATE,
            entry_price DOUBLE,
            entry_available_at TIMESTAMP,
            entry_snapshot_id VARCHAR,
            execution_status VARCHAR,
            execution_reason VARCHAR,
            PRIMARY KEY (symbol, trade_date)
        )
        """
    )
    calendar_reader = duckdb.connect()
    decision_reader = duckdb.connect()
    window_reader = duckdb.connect()
    try:
        market_dates = tuple(
            row[0]
            for row in calendar_reader.execute(
                f"SELECT DISTINCT trade_date FROM read_parquet({_sql_list(panel_files)}, "
                "union_by_name=true) ORDER BY trade_date"
            ).fetchall()
        )
        decision_cursor = decision_reader.execute(
            f"""
            SELECT symbol, trade_date, decision_at
            FROM read_parquet({_sql_list(panel_files)}, union_by_name=true)
            WHERE is_evaluation_row
            ORDER BY symbol, trade_date
            """
        )
        window_cursor = window_reader.execute(
            f"""
            SELECT symbol, trade_date, window_index, available_at,
                   open, high, low, close, volume, amount, trade_status,
                   up_limit_price, down_limit_price, market_rule_valid,
                   hard_valid, invalid_reasons, snapshot_id, daily_snapshot_id
            FROM read_parquet({_sql_list(execution_files)}, union_by_name=true)
            ORDER BY symbol, trade_date, window_index, available_at
            """
        )
        decisions = _iter_cursor_rows(decision_cursor)
        windows = _iter_cursor_rows(window_cursor)

        decision_groups = groupby(decisions, key=lambda row: str(row[0]))
        window_groups = iter(groupby(windows, key=lambda row: str(row[0])))
        _insert_resolved_fills(
            con,
            config=config,
            market_dates=market_dates,
            decision_groups=decision_groups,
            window_groups=window_groups,
        )
    finally:
        calendar_reader.close()
        decision_reader.close()
        window_reader.close()


def _iter_cursor_rows(cursor: duckdb.DuckDBPyConnection) -> Any:
    while True:
        rows = cursor.fetchmany(65_536)
        if not rows:
            return
        yield from rows


def _insert_resolved_fills(
    con: duckdb.DuckDBPyConnection,
    *,
    config: MarkupRetestConfig,
    market_dates: tuple[object, ...],
    decision_groups: Any,
    window_groups: Any,
) -> None:
    current_window_group = next(window_groups, None)
    output: list[tuple[object, ...]] = []
    markup = (config.execution.slippage_bps + config.execution.impact_bps) / 10_000.0
    for symbol, raw_decisions in decision_groups:
        while current_window_group is not None and current_window_group[0] < symbol:
            current_window_group = next(window_groups, None)
        symbol_windows: tuple[ExecutionWindow, ...] = ()
        if current_window_group is not None and current_window_group[0] == symbol:
            symbol_windows = tuple(
                _execution_window_from_row(row) for row in current_window_group[1]
            )
            current_window_group = next(window_groups, None)
        windows_by_date: dict[object, list[ExecutionWindow]] = {}
        for window in symbol_windows:
            windows_by_date.setdefault(window.trade_date, []).append(window)
        for _, trade_date, decision_at in raw_decisions:
            date_index = bisect_right(market_dates, trade_date)
            candidate_dates = market_dates[
                date_index : date_index + config.execution.max_entry_wait_trading_days
            ]
            relevant_windows = tuple(windows_by_date.get(trade_date, ())) + tuple(
                window
                for candidate_date in candidate_dates
                for window in windows_by_date.get(candidate_date, ())
            )
            resolution = resolve_next_legal_fill(
                symbol=symbol,
                decision_at=decision_at,
                windows=relevant_windows,
                market_trading_dates=market_dates,
                settings=config.execution,
            )
            window = resolution.window
            output.append(
                (
                    symbol,
                    trade_date,
                    None if window is None else window.trade_date,
                    None if window is None else window.vwap * (1.0 + markup),
                    None if window is None else window.available_at,
                    None if window is None else window.snapshot_id,
                    resolution.status.value,
                    "|".join(resolution.reason_codes),
                )
            )
            if len(output) >= 10_000:
                con.executemany(
                    "INSERT INTO label_entry_fills VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    output,
                )
                output.clear()
    if output:
        con.executemany(
            "INSERT INTO label_entry_fills VALUES (?, ?, ?, ?, ?, ?, ?, ?)", output
        )


def _execution_window_from_row(row: tuple[object, ...]) -> ExecutionWindow:
    reasons = tuple(
        item for item in str(row[15] or "").replace(",", "|").split("|") if item
    )
    return ExecutionWindow(
        symbol=str(row[0]),
        trade_date=row[1],
        window_index=int(row[2]),
        available_at=row[3],
        open=float(row[4]),
        high=float(row[5]),
        low=float(row[6]),
        close=float(row[7]),
        volume=float(row[8]),
        amount=float(row[9]),
        trade_status=None if row[10] is None else int(row[10]),
        up_limit_price=None if row[11] is None else float(row[11]),
        down_limit_price=None if row[12] is None else float(row[12]),
        market_rule_valid=bool(row[13]),
        hard_valid=bool(row[14]),
        invalid_reasons=reasons,
        snapshot_id=str(row[16]),
        daily_snapshot_id=None if row[17] is None else str(row[17]),
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
