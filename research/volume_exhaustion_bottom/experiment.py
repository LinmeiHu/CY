#!/usr/bin/env python3
"""Run the lightweight, PIT-safe Volume Exhaustion Bottom V1 study."""

# SQL window specifications are kept on one line so their frame semantics stay scannable.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from cyq_game.data.registry import (  # noqa: E402
    DataAssetRegistry,
    DataOperation,
    InputSnapshotManifest,
)

DEFAULT_CONFIG = Path(__file__).resolve().parent / "configs" / "v1.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "reports"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def validate_inputs(config: dict[str, Any], *, hash_data_files: bool) -> dict[str, Any]:
    data = config["data"]
    identities: dict[str, Any] = {}
    for key in ("registry", "activation_manifest", "inventory"):
        path = resolve_path(data[f"{key}_path"])
        actual = sha256(path)
        expected = data[f"{key}_sha256"]
        if actual != expected:
            raise RuntimeError(f"{key} hash mismatch: expected {expected}, got {actual}")
        identities[key] = {"path": str(path), "sha256": actual}

    registry = DataAssetRegistry.load(resolve_path(data["registry_path"]))
    activation = InputSnapshotManifest.load(
        resolve_path(data["activation_manifest_path"]), registry=registry
    )
    authorization = activation.authorize(DataOperation.BACKTEST, registry=registry)
    activation.require_range(
        date.fromisoformat(config["sample"]["warmup_start"]),
        date.fromisoformat(config["sample"]["signal_end"]),
    )
    binding = activation.binding("daily_pit_b")
    if binding.asset.asset_id != data["asset_id"]:
        raise RuntimeError("activation asset_id mismatch")
    if binding.snapshot_id != data["snapshot_id"]:
        raise RuntimeError("activation snapshot_id mismatch")
    if binding.inventory_sha256 != data["inventory_sha256"]:
        raise RuntimeError("activation inventory hash mismatch")

    inventory_path = resolve_path(data["inventory_path"])
    inventory = json.loads(inventory_path.read_text())
    inventory_root = Path(inventory["root"])
    verified_files = []
    for item in inventory["files"]:
        path = inventory_root / item["path"]
        if path.stat().st_size != item["size"]:
            raise RuntimeError(f"inventory size mismatch: {path}")
        if hash_data_files:
            binding.verify_file(path)
        actual_hash = item["sha256"]
        verified_files.append(
            {
                "path": str(path),
                "size": item["size"],
                "sha256": actual_hash,
                "content_hash_verified": hash_data_files,
            }
        )
    identities["data_files"] = verified_files
    identities["snapshot_id"] = data["snapshot_id"]
    identities["pit_grade"] = binding.asset.pit_grade
    identities["strict_archive_ready"] = registry.global_gate["strict_archival_pit_ready"]
    identities["authorization"] = {
        "operation": authorization.operation.value,
        "registry_id": authorization.registry_id,
        "registry_sha256": authorization.registry_sha256,
        "manifest_id": authorization.input_manifest_id,
        "manifest_sha256": authorization.input_manifest_sha256,
        "purpose": authorization.purpose.value,
        "hard_valid": authorization.hard_valid,
        "scope_start": authorization.scope_start.isoformat(),
        "scope_end": authorization.scope_end.isoformat(),
    }
    return identities


def create_analysis_tables(con: duckdb.DuckDBPyConnection, config: dict[str, Any]) -> None:
    data_glob = config["data"]["parquet_glob"].replace("'", "''")
    sample = config["sample"]
    defs = config["definitions"]
    warmup_start = sample["warmup_start"]
    signal_start = sample["signal_start"]
    signal_end = sample["signal_end"]
    symbols = config.get("runtime", {}).get("symbol_filter", [])
    symbol_filter = ""
    if symbols:
        quoted = ", ".join("'" + item.replace("'", "''") + "'" for item in symbols)
        symbol_filter = f" AND symbol IN ({quoted})"

    con.execute(
        f"""
        CREATE TEMP TABLE raw_ordered AS
        SELECT
            trade_date, symbol, open, high, low, close, preclose, volume, amount,
            turnover_fraction, trade_status, is_st, industry, buy_blocked_open,
            current_day_data_tradable, hard_valid, bar_valid, trading_state_valid,
            corporate_action_valid, available_at, decision_at, snapshot_id,
            sum(CASE WHEN NOT hard_valid THEN 1 ELSE 0 END) OVER w AS bad_cum,
            lead(trade_date) OVER w AS raw_next_date,
            lead(open) OVER w AS raw_next_open,
            lead(preclose) OVER w AS raw_next_preclose,
            lead(hard_valid) OVER w AS raw_next_hard_valid,
            lead(trade_status) OVER w AS raw_next_trade_status,
            lead(is_st) OVER w AS raw_next_is_st,
            lead(buy_blocked_open) OVER w AS raw_next_buy_blocked_open,
            lead(current_day_data_tradable) OVER w AS raw_next_data_tradable
        FROM read_parquet('{data_glob}', hive_partitioning=true)
        WHERE trade_date >= DATE '{warmup_start}' AND trade_date <= DATE '{signal_end}'
          {symbol_filter}
        WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE indexed AS
        SELECT
            *,
            row_number() OVER w AS trade_seq,
            close / preclose - 1.0 AS bar_return,
            exp(sum(ln(close / preclose)) OVER w) AS adjusted_close
        FROM raw_ordered
        WHERE hard_valid
          AND trade_status = 1
          AND current_day_data_tradable
          AND bar_valid
          AND trading_state_valid
          AND corporate_action_valid
          AND open > 0 AND high > 0 AND low > 0 AND close > 0 AND preclose > 0
          AND amount > 0 AND volume > 0 AND turnover_fraction IS NOT NULL
        WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE activity AS
        SELECT
            *,
            adjusted_close * high / close AS adjusted_high,
            adjusted_close * low / close AS adjusted_low,
            avg(amount) OVER w3 AS amount_mean_3,
            avg(amount) OVER w5 AS amount_mean_5,
            median(amount) OVER w20 AS amount_median_20,
            sum(turnover_fraction) OVER w3 AS turnover_sum_3,
            sum(turnover_fraction) OVER w20 AS turnover_sum_20,
            sum(greatest(-bar_return, 0.0)) OVER w3 AS downside_return_3,
            sum(greatest(-bar_return, 0.0)) OVER w20 AS downside_return_20
        FROM indexed
        WINDOW
            w3 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 2 PRECEDING AND CURRENT ROW),
            w5 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),
            w20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE features AS
        SELECT
            *,
            adjusted_close / max(adjusted_close) OVER w60 - 1.0 AS drawdown_60,
            adjusted_close / min(adjusted_low) OVER w60 - 1.0 AS distance_from_low_60,
            amount_mean_5 / amount_median_20 AS dryup_ratio,
            adjusted_close / lag(adjusted_close, 3) OVER w - 1.0 AS return_3,
            adjusted_close / lag(adjusted_close, 20) OVER w - 1.0 AS return_20,
            stddev_samp(bar_return) OVER w20 AS volatility_20,
            min(adjusted_low) OVER w3 AS low_3,
            min(adjusted_low) OVER wprev3 AS prior_low_3,
            downside_return_3 / nullif(turnover_sum_3, 0.0) AS downside_impact_3,
            downside_return_20 / nullif(turnover_sum_20, 0.0) AS downside_impact_20,
            max(adjusted_close) OVER wprev5 AS prior_close_high_5,
            lag(bad_cum, 59) OVER w AS bad_cum_at_60_start,
            min(adjusted_low) OVER wfirst AS first_low,
            arg_min(amount_mean_3, adjusted_low) OVER wfirst AS first_low_amount_3,
            arg_min(trade_seq, adjusted_low) OVER wfirst AS first_low_seq,
            lead(trade_date, 1) OVER w AS next_trade_date,
            lead(adjusted_close, 5) OVER w AS close_h5,
            lead(adjusted_close, 10) OVER w AS close_h10,
            lead(adjusted_close, 20) OVER w AS close_h20,
            lead(bad_cum, 5) OVER w AS bad_cum_h5,
            lead(bad_cum, 10) OVER w AS bad_cum_h10,
            lead(bad_cum, 20) OVER w AS bad_cum_h20,
            max(adjusted_high) OVER wf5 AS high_h5,
            max(adjusted_high) OVER wf10 AS high_h10,
            max(adjusted_high) OVER wf20 AS high_h20,
            min(adjusted_low) OVER wf5 AS low_h5,
            min(adjusted_low) OVER wf10 AS low_h10,
            min(adjusted_low) OVER wf20 AS low_h20
        FROM activity
        WINDOW
            w AS (PARTITION BY symbol ORDER BY trade_date),
            w60 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW),
            w3 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 2 PRECEDING AND CURRENT ROW),
            wprev3 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 5 PRECEDING AND 3 PRECEDING),
            wprev5 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING),
            w20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
            wfirst AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 40 PRECEDING AND 10 PRECEDING),
            wf5 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 1 FOLLOWING AND 5 FOLLOWING),
            wf10 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 1 FOLLOWING AND 10 FOLLOWING),
            wf20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 1 FOLLOWING AND 20 FOLLOWING)
        """
    )

    common_hygiene = f"""
        trade_date >= DATE '{signal_start}' AND trade_date <= DATE '{signal_end}'
        AND trade_seq >= {int(sample["minimum_listing_sessions"])}
        AND bad_cum = bad_cum_at_60_start
        AND NOT is_st
        AND amount_median_20 >= {float(sample["minimum_median_amount_20"])}
    """
    con.execute(
        f"""
        CREATE TEMP TABLE signal_flags AS
        SELECT
            *,
            ({common_hygiene}
             AND drawdown_60 <= {float(defs["drawdown_60_max"])}
             AND distance_from_low_60 <= {float(defs["distance_from_low_60_max"])}
            ) AS a_flag,
            ({common_hygiene}
             AND drawdown_60 <= {float(defs["drawdown_60_max"])}
             AND distance_from_low_60 <= {float(defs["distance_from_low_60_max"])}
             AND dryup_ratio <= {float(defs["amount_5_to_median_20_max"])}
            ) AS b_flag,
            ({common_hygiene}
             AND drawdown_60 <= {float(defs["drawdown_60_max"])}
             AND distance_from_low_60 <= {float(defs["distance_from_low_60_max"])}
             AND dryup_ratio <= {float(defs["amount_5_to_median_20_max"])}
             AND return_3 >= {float(defs["stabilization_return_3_min"])}
             AND low_3 / prior_low_3 - 1.0 >= {float(defs["stabilization_low_tolerance"])}
             AND downside_impact_3 <= downside_impact_20
            ) AS c_flag,
            ({common_hygiene}
             AND adjusted_close > prior_close_high_5
            ) AS confirm_flag,
            ({common_hygiene}) AS eligible_flag
        FROM features
        """
    )
    cooldown = int(defs["event_cooldown_sessions"])
    recent = int(defs["recent_setup_sessions"])
    con.execute(
        f"""
        CREATE TEMP TABLE staged_events AS
        SELECT
            *,
            (a_flag AND NOT coalesce(bool_or(a_flag) OVER wa, false)) AS a_event,
            (b_flag AND NOT coalesce(bool_or(b_flag) OVER wa, false)) AS b_event,
            (c_flag AND NOT coalesce(bool_or(c_flag) OVER wa, false)) AS c_event,
            (confirm_flag AND coalesce(bool_or(c_flag) OVER wc, false)) AS d_candidate
        FROM signal_flags
        WINDOW
            wa AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN {cooldown} PRECEDING AND 1 PRECEDING),
            wc AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN {recent} PRECEDING AND 1 PRECEDING)
        """
    )
    con.execute(
        f"""
        CREATE TEMP TABLE analysis_rows AS
        SELECT
            *,
            (d_candidate AND NOT coalesce(bool_or(d_candidate) OVER wd, false)) AS d_event,
            (raw_next_date = next_trade_date
             AND raw_next_hard_valid
             AND raw_next_trade_status = 1
             AND raw_next_data_tradable
             AND NOT raw_next_is_st
             AND NOT raw_next_buy_blocked_open
             AND raw_next_open > 0 AND raw_next_preclose > 0
            ) AS entry_valid,
            raw_next_preclose / raw_next_open / adjusted_close AS entry_scale,
            (bad_cum_h5 = bad_cum) AS path_valid_5,
            (bad_cum_h10 = bad_cum) AS path_valid_10,
            (bad_cum_h20 = bad_cum) AS path_valid_20,
            raw_next_preclose / raw_next_open * close_h5 / adjusted_close - 1.0 AS ret_5,
            raw_next_preclose / raw_next_open * close_h10 / adjusted_close - 1.0 AS ret_10,
            raw_next_preclose / raw_next_open * close_h20 / adjusted_close - 1.0 AS ret_20,
            raw_next_preclose / raw_next_open * high_h5 / adjusted_close - 1.0 AS mfe_5,
            raw_next_preclose / raw_next_open * high_h10 / adjusted_close - 1.0 AS mfe_10,
            raw_next_preclose / raw_next_open * high_h20 / adjusted_close - 1.0 AS mfe_20,
            raw_next_preclose / raw_next_open * low_h5 / adjusted_close - 1.0 AS mae_5,
            raw_next_preclose / raw_next_open * low_h10 / adjusted_close - 1.0 AS mae_10,
            raw_next_preclose / raw_next_open * low_h20 / adjusted_close - 1.0 AS mae_20,
            CASE
                WHEN trade_date < DATE '2023-01-01' THEN '2020-2022'
                WHEN trade_date < DATE '2025-01-01' THEN '2023-2024'
                ELSE '2025-2026'
            END AS time_block,
            CASE
                WHEN symbol LIKE '300%' THEN 'CHINEXT'
                WHEN symbol LIKE '688%' THEN 'STAR'
                WHEN symbol LIKE '8%' OR symbol LIKE '4%' THEN 'BSE'
                ELSE 'MAIN'
            END AS segment
        FROM staged_events
        WINDOW wd AS (
            PARTITION BY symbol ORDER BY trade_date
            ROWS BETWEEN {cooldown} PRECEDING AND 1 PRECEDING
        )
        """
    )


METRIC_COLUMNS = [
    "stage",
    "n",
    "mean_ret_5",
    "median_ret_5",
    "positive_rate_5",
    "mean_ret_10",
    "median_ret_10",
    "positive_rate_10",
    "mean_ret_20",
    "median_ret_20",
    "positive_rate_20",
    "mean_mfe_5",
    "mean_mae_5",
    "mean_mfe_10",
    "mean_mae_10",
    "mean_mfe_20",
    "mean_mae_20",
]


def metric_select(stage_expr: str, where: str, extra: str = "") -> str:
    return f"""
        SELECT {stage_expr} AS stage{extra}, count(*) AS n,
               avg(ret_5) AS mean_ret_5, median(ret_5) AS median_ret_5,
               avg((ret_5 > 0)::INTEGER) AS positive_rate_5,
               avg(ret_10) AS mean_ret_10, median(ret_10) AS median_ret_10,
               avg((ret_10 > 0)::INTEGER) AS positive_rate_10,
               avg(ret_20) AS mean_ret_20, median(ret_20) AS median_ret_20,
               avg((ret_20 > 0)::INTEGER) AS positive_rate_20,
               avg(mfe_5) AS mean_mfe_5, avg(mae_5) AS mean_mae_5,
               avg(mfe_10) AS mean_mfe_10, avg(mae_10) AS mean_mae_10,
               avg(mfe_20) AS mean_mfe_20, avg(mae_20) AS mean_mae_20
        FROM analysis_rows
        WHERE entry_valid AND path_valid_20 AND close_h20 IS NOT NULL AND ({where})
    """


def core_metrics(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    parts = [metric_select(f"'{stage}'", f"{stage.lower()}_event") for stage in "ABCD"]
    cursor = con.execute(" UNION ALL ".join(parts))
    return rows_as_dicts(cursor)


def qualifying_observation_metrics(
    con: duckdb.DuckDBPyConnection,
) -> list[dict[str, Any]]:
    conditions = {
        "A": "a_flag",
        "B": "b_flag",
        "C": "c_flag",
        "D": "d_candidate",
    }
    parts = [metric_select(f"'{stage}'", condition) for stage, condition in conditions.items()]
    return rows_as_dicts(con.execute(" UNION ALL ".join(parts)))


def grouped_metrics(con: duckdb.DuckDBPyConnection, group_column: str) -> list[dict[str, Any]]:
    parts = []
    for stage in "ABCD":
        sql = metric_select(f"'{stage}'", f"{stage.lower()}_event", extra=f", {group_column}")
        parts.append(sql + f" GROUP BY {group_column}")
    return rows_as_dicts(con.execute(" UNION ALL ".join(parts)))


def continuous_metrics(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    variables = {
        "drawdown_60": "drawdown_60",
        "dryup_ratio": "dryup_ratio",
        "distance_from_low_60": "distance_from_low_60",
        "downside_impact_ratio": "downside_impact_3 / nullif(downside_impact_20, 0.0)",
    }
    output: list[dict[str, Any]] = []
    for name, expression in variables.items():
        cursor = con.execute(
            f"""
            WITH bucketed AS (
                SELECT *, {expression} AS value,
                       ntile(5) OVER (ORDER BY {expression}) AS quintile
                FROM analysis_rows
                WHERE a_event AND entry_valid AND path_valid_20 AND close_h20 IS NOT NULL
                  AND {expression} IS NOT NULL AND isfinite({expression})
            )
            SELECT '{name}' AS variable, quintile, count(*) AS n,
                   min(value) AS value_min, max(value) AS value_max,
                   avg(ret_5) AS mean_ret_5, avg(ret_10) AS mean_ret_10,
                   avg(ret_20) AS mean_ret_20,
                   avg((ret_20 > 0)::INTEGER) AS positive_rate_20,
                   avg(mfe_20) AS mean_mfe_20, avg(mae_20) AS mean_mae_20
            FROM bucketed GROUP BY quintile ORDER BY quintile
            """
        )
        output.extend(rows_as_dicts(cursor))
    return output


def controlled_dryup_metrics(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    return rows_as_dicts(
        con.execute(
            """
            WITH drawdown_strata AS (
                SELECT *, ntile(5) OVER (
                    PARTITION BY time_block ORDER BY drawdown_60
                ) AS drawdown_quintile
                FROM analysis_rows
                WHERE a_event AND entry_valid AND path_valid_20 AND close_h20 IS NOT NULL
                  AND dryup_ratio IS NOT NULL AND isfinite(dryup_ratio)
            ), dryup_buckets AS (
                SELECT *, ntile(5) OVER (
                    PARTITION BY time_block, drawdown_quintile ORDER BY dryup_ratio
                ) AS controlled_dryup_quintile
                FROM drawdown_strata
            )
            SELECT controlled_dryup_quintile AS quintile, count(*) AS n,
                   min(dryup_ratio) AS value_min, max(dryup_ratio) AS value_max,
                   avg(ret_5) AS mean_ret_5, avg(ret_10) AS mean_ret_10,
                   avg(ret_20) AS mean_ret_20,
                   avg((ret_20 > 0)::INTEGER) AS positive_rate_20,
                   avg(mfe_20) AS mean_mfe_20, avg(mae_20) AS mean_mae_20
            FROM dryup_buckets
            GROUP BY controlled_dryup_quintile
            ORDER BY controlled_dryup_quintile
            """
        )
    )


def second_low_metrics(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    defs = config["definitions"]
    con.execute(
        f"""
        CREATE TEMP TABLE second_low_events AS
        WITH candidates AS (
            SELECT s.symbol, s.trade_date, s.trade_seq, s.first_low_seq,
                   s.adjusted_low / s.first_low AS price_ratio,
                   s.amount_mean_3 / s.first_low_amount_3 AS activity_ratio,
                   max(m.adjusted_high) AS rebound_high,
                   any_value(s.first_low) AS first_low,
                   any_value(s.entry_valid) AS entry_valid,
                   any_value(s.path_valid_20) AS path_valid_20,
                   any_value(s.close_h20) AS close_h20,
                   any_value(s.ret_5) AS ret_5, any_value(s.ret_10) AS ret_10,
                   any_value(s.ret_20) AS ret_20,
                   any_value(s.mfe_5) AS mfe_5, any_value(s.mfe_10) AS mfe_10,
                   any_value(s.mfe_20) AS mfe_20,
                   any_value(s.mae_5) AS mae_5, any_value(s.mae_10) AS mae_10,
                   any_value(s.mae_20) AS mae_20
            FROM analysis_rows s
            JOIN activity m
              ON m.symbol = s.symbol
             AND m.trade_seq > s.first_low_seq
             AND m.trade_seq < s.trade_seq
            WHERE s.eligible_flag
              AND s.first_low IS NOT NULL AND s.first_low_amount_3 > 0
              AND s.trade_seq - s.first_low_seq BETWEEN
                  {int(defs["second_low_lookback_min"])}
                  AND {int(defs["second_low_lookback_max"])}
              AND s.adjusted_low / s.first_low BETWEEN
                  {float(defs["second_low_price_ratio_min"])}
                  AND {float(defs["second_low_price_ratio_max"])}
              AND s.adjusted_low <= s.low_3
            GROUP BY s.symbol, s.trade_date, s.trade_seq, s.first_low_seq,
                     s.adjusted_low, s.first_low, s.amount_mean_3, s.first_low_amount_3
        ), qualified AS (
            SELECT *, rebound_high / first_low - 1.0 AS rebound_return
            FROM candidates
            WHERE rebound_high / first_low - 1.0 >= {float(defs["second_low_rebound_min"])}
        )
        SELECT * EXCLUDE (rn)
        FROM (
            SELECT *, row_number() OVER (
                PARTITION BY symbol, first_low_seq ORDER BY trade_seq
            ) AS rn
            FROM qualified
        )
        WHERE rn = 1
        """
    )
    categories = {
        "ALL_RETESTS": "true",
        "CONTRACTED": f"activity_ratio <= {float(defs['second_low_contraction_max'])}",
        "NOT_CONTRACTED": f"activity_ratio >= {float(defs['second_low_no_contraction_min'])}",
    }
    parts = []
    for label, condition in categories.items():
        parts.append(
            f"""
            SELECT '{label}' AS category, count(*) AS n,
                   avg(ret_5) AS mean_ret_5, median(ret_5) AS median_ret_5,
                   avg((ret_5 > 0)::INTEGER) AS positive_rate_5,
                   avg(ret_10) AS mean_ret_10, median(ret_10) AS median_ret_10,
                   avg((ret_10 > 0)::INTEGER) AS positive_rate_10,
                   avg(ret_20) AS mean_ret_20, median(ret_20) AS median_ret_20,
                   avg((ret_20 > 0)::INTEGER) AS positive_rate_20,
                   avg(mfe_20) AS mean_mfe_20, avg(mae_20) AS mean_mae_20,
                   avg(activity_ratio) AS mean_activity_ratio
            FROM second_low_events
            WHERE entry_valid AND path_valid_20 AND close_h20 IS NOT NULL AND {condition}
            """
        )
    metrics = rows_as_dicts(con.execute(" UNION ALL ".join(parts)))
    profile_cursor = con.execute(
        """
        SELECT count(*) AS raw_events, count(DISTINCT symbol) AS symbols,
               min(trade_date) AS first_date, max(trade_date) AS last_date,
               median(activity_ratio) AS median_activity_ratio,
               median(rebound_return) AS median_rebound_return
        FROM second_low_events
        """
    )
    profile = rows_as_dicts(profile_cursor)[0]
    return metrics, profile


def rows_as_dicts(cursor: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"refusing to write empty result: {path.name}")
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def json_default(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"cannot serialize {type(value).__name__}")


def build_profiles(con: duckdb.DuckDBPyConnection) -> tuple[dict[str, Any], dict[str, Any]]:
    data_profile = rows_as_dicts(
        con.execute(
            """
            SELECT min(trade_date) AS first_date, max(trade_date) AS last_date,
                   count(*) AS rows, count(DISTINCT symbol) AS symbols,
                   sum(hard_valid::INTEGER) AS hard_valid_rows,
                   sum((available_at > decision_at)::INTEGER) AS time_travel_rows,
                   sum((hard_valid AND trade_status = 1 AND NOT is_st)::INTEGER)
                       AS valid_non_st_trading_rows
            FROM raw_ordered
            """
        )
    )[0]
    sample_profile = rows_as_dicts(
        con.execute(
            """
            SELECT sum(eligible_flag::INTEGER) AS eligible_observations,
                   count(DISTINCT symbol) FILTER (WHERE eligible_flag) AS eligible_symbols,
                   min(trade_date) FILTER (WHERE eligible_flag) AS first_signal_date,
                   max(trade_date) FILTER (WHERE eligible_flag) AS last_signal_date,
                   sum(a_flag::INTEGER) AS a_observations,
                   sum(b_flag::INTEGER) AS b_observations,
                   sum(c_flag::INTEGER) AS c_observations,
                   sum(a_event::INTEGER) AS a_events,
                   sum(b_event::INTEGER) AS b_events,
                   sum(c_event::INTEGER) AS c_events,
                   sum(d_event::INTEGER) AS d_events,
                   sum((entry_valid AND path_valid_20)::INTEGER) AS outcome_eligible_rows
            FROM analysis_rows
            WHERE trade_date >= DATE '2020-01-02'
            """
        )
    )[0]
    return data_profile, sample_profile


def run(config_path: Path, output_dir: Path, *, hash_data_files: bool) -> None:
    config = json.loads(config_path.read_text())
    identities = validate_inputs(config, hash_data_files=hash_data_files)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="volume-exhaustion-v1-") as temp_dir:
        con = duckdb.connect()
        con.execute(f"SET threads={int(config['runtime']['threads'])}")
        con.execute(f"SET memory_limit='{config['runtime']['memory_limit']}'")
        con.execute(f"SET temp_directory='{temp_dir}'")
        con.execute("SET preserve_insertion_order=false")
        create_analysis_tables(con, config)

        checks = rows_as_dicts(
            con.execute(
                """
                SELECT
                    count(*) FILTER (WHERE available_at > decision_at) AS time_travel,
                    count(*) FILTER (WHERE entry_valid AND raw_next_date <= trade_date)
                        AS non_t_plus_one_entries,
                    count(*) FILTER (WHERE b_flag AND NOT a_flag) AS b_without_a,
                    count(*) FILTER (WHERE c_flag AND NOT b_flag) AS c_without_b,
                    count(*) FILTER (WHERE a_flag AND bad_cum != bad_cum_at_60_start)
                        AS invalid_history_signals
                FROM analysis_rows
                """
            )
        )[0]
        if any(value != 0 for value in checks.values()):
            raise RuntimeError(f"research invariants failed: {checks}")

        core = core_metrics(con)
        qualifying = qualifying_observation_metrics(con)
        time_splits = grouped_metrics(con, "time_block")
        segments = grouped_metrics(con, "segment")
        continuous = continuous_metrics(con)
        controlled_dryup = controlled_dryup_metrics(con)
        second_low, second_low_profile = second_low_metrics(con, config)
        data_profile, sample_profile = build_profiles(con)
        con.close()

    write_csv(output_dir / "core_results.csv", core)
    write_csv(output_dir / "qualifying_observation_results.csv", qualifying)
    write_csv(output_dir / "time_splits.csv", time_splits)
    write_csv(output_dir / "segment_results.csv", segments)
    write_csv(output_dir / "continuous_results.csv", continuous)
    write_csv(output_dir / "controlled_dryup_results.csv", controlled_dryup)
    write_csv(output_dir / "second_low_results.csv", second_low)
    payload = {
        "config": config,
        "input_identities": identities,
        "checks": checks,
        "data_profile": data_profile,
        "sample_profile": sample_profile,
        "second_low_profile": second_low_profile,
        "core_results": core,
        "qualifying_observation_results": qualifying,
        "time_splits": time_splits,
        "segment_results": segments,
        "continuous_results": continuous,
        "controlled_dryup_results": controlled_dryup,
        "second_low_results": second_low,
    }
    (output_dir / "results.json").write_text(
        json.dumps(payload, indent=2, default=json_default) + "\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--skip-data-file-hashes",
        action="store_true",
        help="Skip content hashing for fast local semantics tests; final runs must not use this.",
    )
    args = parser.parse_args()
    run(args.config, args.output, hash_data_files=not args.skip_data_file_hashes)


if __name__ == "__main__":
    main()
