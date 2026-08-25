#!/usr/bin/env python3
"""Build the corrected, chip-free 2020-2022 candidate cohort."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from cyq_game.data.registry import DataAssetRegistry
from cyq_game.strategy.chip_incremental import (
    assert_price_volume_candidate_schema,
    select_price_volume_candidates,
)

REGISTRY_PATH = Path("configs/data_asset_registry.json")
PROTOCOL_MANIFEST = Path(
    "output/chip_incremental_validation_v1/protocol_manifest.json"
)
ADDENDUM_MANIFEST = Path(
    "output/chip_incremental_validation_v1/addenda/addendum_01_manifest.json"
)
DEFAULT_OUTPUT = Path("output/chip_incremental_validation_v1/candidates")
SEMANTIC_MODULE = Path("src/cyq_game/strategy/chip_incremental.py")
_YEARS = tuple(range(2018, 2023))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--threads", type=int, default=2)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.threads < 1 or args.threads > 4:
        raise ValueError("--threads must be between 1 and 4")
    target = args.output.resolve()
    existing_manifest = target / "manifest.json"
    existing_data = target / "candidate_events.parquet"
    if existing_manifest.is_file() and existing_data.is_file():
        payload = _read_object(existing_manifest)
        if payload.get("candidate_events_sha256") != _sha256(existing_data):
            raise ValueError("existing price-volume cohort hash changed")
        print(
            f"REUSED candidates={payload['candidates']} symbols={payload['symbols']} "
            f"output={existing_data}",
            flush=True,
        )
        return 0
    if target.exists():
        raise FileExistsError(f"incomplete candidate cohort target exists: {target}")

    protocol_path = PROTOCOL_MANIFEST.resolve()
    addendum_path = ADDENDUM_MANIFEST.resolve()
    protocol = _read_object(protocol_path)
    addendum = _read_object(addendum_path)
    _verify_protocol(protocol_path, protocol, addendum_path, addendum)
    registry, source_manifest_path, source_inventory = _verify_daily_inputs()
    input_files = tuple(Path(item["absolute_path"]) for item in source_inventory)

    temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    data_path = temporary / "candidate_events.parquet"

    con = duckdb.connect()
    try:
        con.execute(f"SET threads={args.threads}")
        con.execute("SET memory_limit='8GiB'")
        con.execute("SET preserve_insertion_order=false")
        query = _candidate_query(input_files)
        result = con.execute(query)
        description = result.description
        if description is None:
            raise RuntimeError("candidate query returned no schema")
        columns = tuple(item[0] for item in description)
        assert_price_volume_candidate_schema(columns)
        raw_rows = [
            dict(zip(columns, values, strict=True)) for values in result.fetchall()
        ]
    finally:
        con.close()

    candidates = select_price_volume_candidates(raw_rows)
    if not candidates:
        shutil.rmtree(temporary)
        raise RuntimeError("corrected price-volume definition produced no candidates")
    pq.write_table(pa.Table.from_pylist(candidates), data_path, compression="zstd")
    metrics = _validate_output(data_path)
    output_sha256 = _sha256(data_path)
    identity = {
        "protocol_event_id": protocol["event_id"],
        "addendum_event_id": addendum["event_id"],
        "registry_sha256": registry.sha256,
        "source_manifest_sha256": _sha256(source_manifest_path),
        "source_inventory": source_inventory,
        "builder_sha256": _sha256(Path(__file__).resolve()),
        "selector_sha256": _sha256(SEMANTIC_MODULE.resolve()),
        "candidate_events_sha256": output_sha256,
        "metrics": metrics,
    }
    snapshot_id = "price-volume-candidates-" + hashlib.sha256(
        _canonical(identity).encode()
    ).hexdigest()
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "status": "COMPLETE_OUTCOME_BLIND",
        "created_at": datetime.now(UTC).isoformat(),
        "candidate_snapshot_id": snapshot_id,
        **identity,
        "protocol_manifest": str(protocol_path),
        "protocol_manifest_sha256": _sha256(protocol_path),
        "addendum_manifest": str(addendum_path),
        "addendum_manifest_sha256": _sha256(addendum_path),
        "registry_path": str(registry.path),
        "source_asset_id": "CY-006",
        "source_manifest": str(source_manifest_path),
        "candidate_events": "candidate_events.parquet",
        "candidate_events_sha256": output_sha256,
        "candidates": metrics["rows"],
        "symbols": metrics["symbols"],
        "years": metrics["annual_rows"],
        "maximum_input_date": "2022-12-30",
        "future_partition_data_opened": False,
        "chip_fields_used": False,
        "outcome_fields_used": False,
        "holdout_outcomes_observed": False,
    }
    _write_json(temporary / "manifest.json", manifest)
    temporary.replace(target)
    print(
        f"PASS candidates={metrics['rows']} symbols={metrics['symbols']} "
        f"output={target / 'candidate_events.parquet'}",
        flush=True,
    )
    return 0


def _verify_protocol(
    protocol_path: Path,
    protocol: dict[str, Any],
    addendum_path: Path,
    addendum: dict[str, Any],
) -> None:
    if (
        protocol.get("status") != "PREREGISTERED"
        or protocol.get("holdout_accessed") is not False
        or protocol.get("holdout_outcomes_observed") is not False
    ):
        raise ValueError("candidate cohort requires the outcome-blind protocol")
    if (
        addendum.get("status") != "PREREGISTERED_CORRECTION_BEFORE_OUTCOMES"
        or addendum.get("protocol_event_id") != protocol.get("event_id")
        or addendum.get("protocol_manifest_sha256") != _sha256(protocol_path)
        or addendum.get("holdout_outcomes_observed") is not False
        or addendum.get("maximum_input_date") != "2022-12-30"
    ):
        raise ValueError(f"candidate cohort addendum identity changed: {addendum_path}")


def _verify_daily_inputs() -> tuple[DataAssetRegistry, Path, list[dict[str, Any]]]:
    registry = DataAssetRegistry.load(REGISTRY_PATH.resolve())
    try:
        asset = registry.assets["CY-006"]
    except KeyError as error:
        raise ValueError("CY-006 is not registered") from error
    if (
        asset.status != "RESEARCH_CONDITIONAL"
        or asset.pit_grade != "B"
        or asset.physical_state != "MATERIALIZED"
        or asset.location is None
    ):
        raise ValueError("CY-006 is not activated for bounded causal research")
    raw_manifest = asset.lineage.get("manifest_path")
    registered_sha256 = asset.lineage.get("manifest_sha256")
    if not isinstance(raw_manifest, str) or not isinstance(registered_sha256, str):
        raise ValueError("CY-006 lacks an immutable manifest identity")
    manifest_path = Path(raw_manifest).expanduser().resolve()
    if _sha256(manifest_path) != registered_sha256:
        raise ValueError("CY-006 registered manifest hash changed")
    manifest = _read_object(manifest_path)
    root = Path(str(manifest.get("root"))).expanduser().resolve()
    if root != asset.location.resolve():
        raise ValueError("CY-006 manifest root differs from registry location")
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list):
        raise ValueError("CY-006 manifest inventory is missing")
    inventory_by_year: dict[int, dict[str, Any]] = {}
    for raw in raw_files:
        if not isinstance(raw, dict):
            raise ValueError("CY-006 manifest inventory entry is invalid")
        relative = Path(str(raw.get("path", "")))
        year = _path_year(relative)
        if year not in _YEARS:
            continue
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("CY-006 selected inventory path is unsafe")
        path = root / relative
        if not path.is_file() or path.stat().st_size != raw.get("size"):
            raise ValueError(f"CY-006 selected partition size changed: {path}")
        if _sha256(path) != raw.get("sha256"):
            raise ValueError(f"CY-006 selected partition hash changed: {path}")
        inventory_by_year[year] = {
            "year": year,
            "path": str(relative),
            "absolute_path": str(path),
            "size": path.stat().st_size,
            "sha256": raw["sha256"],
        }
    if tuple(sorted(inventory_by_year)) != _YEARS:
        raise ValueError("CY-006 lacks the exact 2018-2022 partitions")
    return registry, manifest_path, [inventory_by_year[year] for year in _YEARS]


def _candidate_query(paths: tuple[Path, ...]) -> str:
    sources = "[" + ",".join(_sql_text(str(path)) for path in paths) + "]"
    scope = """
        (symbol LIKE '000___.SZ' OR symbol LIKE '001___.SZ'
         OR symbol LIKE '002___.SZ' OR symbol LIKE '003___.SZ'
         OR symbol LIKE '300___.SZ' OR symbol LIKE '301___.SZ'
         OR symbol LIKE '302___.SZ' OR symbol LIKE '600___.SH'
         OR symbol LIKE '601___.SH' OR symbol LIKE '603___.SH'
         OR symbol LIKE '605___.SH')
    """
    return f"""
        WITH raw_source AS (
            SELECT *
            FROM read_parquet({sources}, union_by_name=true)
            WHERE trade_date BETWEEN DATE '2018-01-01' AND DATE '2022-12-30'
              AND {scope}
        ), prior_close AS (
            SELECT *,
                   lag(close) OVER (PARTITION BY symbol ORDER BY trade_date)
                       AS previous_raw_close
            FROM raw_source
        ), coordinate_step AS (
            SELECT *,
                   CASE
                       WHEN coalesce(corporate_action_count, 0) > 0
                        AND previous_raw_close > 0 AND preclose > 0
                       THEN preclose / previous_raw_close
                       ELSE 1.0
                   END AS coordinate_step
            FROM prior_close
        ), coordinate AS (
            SELECT *,
                   exp(sum(ln(coordinate_step)) OVER (
                       PARTITION BY symbol ORDER BY trade_date
                       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                   )) AS price_coordinate_factor
            FROM coordinate_step
        ), normalized AS (
            SELECT *,
                   open / price_coordinate_factor AS analysis_open,
                   high / price_coordinate_factor AS analysis_high,
                   low / price_coordinate_factor AS analysis_low,
                   close / price_coordinate_factor AS analysis_close,
                   greatest(high - low, abs(high - preclose), abs(low - preclose))
                       / price_coordinate_factor AS analysis_true_range,
                   CASE WHEN preclose > 0 THEN close / preclose - 1.0 END
                       AS stock_return,
                   last_value(
                       CASE
                           WHEN industry_valid
                           THEN nullif(nullif(trim(industry), ''), 'UNKNOWN')
                       END IGNORE NULLS
                   ) OVER (
                       PARTITION BY symbol ORDER BY trade_date
                       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                   ) AS effective_industry,
                   last_value(
                       CASE WHEN industry_valid THEN industry_source END IGNORE NULLS
                   ) OVER (
                       PARTITION BY symbol ORDER BY trade_date
                       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                   ) AS effective_industry_source,
                   row_number() OVER (PARTITION BY symbol ORDER BY trade_date)
                       AS symbol_session_index,
                   trading_state_valid AND trade_status = 1
                       AND current_day_data_tradable AS tradable_state
            FROM coordinate
        ), technical AS (
            SELECT *,
                   max(analysis_high) OVER (
                       PARTITION BY symbol ORDER BY trade_date
                       ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING
                   ) AS price_resistance_norm,
                   avg(analysis_true_range) OVER (
                       PARTITION BY symbol ORDER BY trade_date
                       ROWS BETWEEN 13 PRECEDING AND CURRENT ROW
                   ) AS atr14_norm,
                   lag(analysis_close, 20) OVER (
                       PARTITION BY symbol ORDER BY trade_date
                   ) AS close_lag20_norm,
                   avg(turnover_fraction) OVER (
                       PARTITION BY symbol ORDER BY trade_date
                       ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                   ) AS turnover_mean20,
                   avg(amount) OVER (
                       PARTITION BY symbol ORDER BY trade_date
                       ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                   ) AS amount_mean20
            FROM normalized
        ), market_series AS (
            SELECT DISTINCT trade_date, index_symbol, market_close
            FROM technical
            WHERE index_symbol IS NOT NULL AND market_close IS NOT NULL
        ), market_daily AS (
            SELECT trade_date, index_symbol,
                   CASE WHEN lag(market_close) OVER (
                       PARTITION BY index_symbol ORDER BY trade_date
                   ) > 0 THEN market_close / lag(market_close) OVER (
                       PARTITION BY index_symbol ORDER BY trade_date
                   ) - 1.0 END AS market_return
            FROM market_series
        ), with_market AS (
            SELECT t.*, m.market_return
            FROM technical t
            LEFT JOIN market_daily m USING (trade_date, index_symbol)
        ), peer_sums AS (
            SELECT *,
                   sum(stock_return) OVER (
                       PARTITION BY trade_date, effective_industry
                   ) AS industry_return_sum,
                   count(stock_return) OVER (
                       PARTITION BY trade_date, effective_industry
                   ) AS industry_return_count
            FROM with_market
        ), evidence AS (
            SELECT *,
                   CASE
                       WHEN effective_industry IS NOT NULL
                        AND industry_return_count > 1
                       THEN (industry_return_sum - stock_return)
                            / (industry_return_count - 1)
                   END AS sector_return_loo,
                   CASE
                       WHEN price_resistance_norm IS NOT NULL AND atr14_norm > 0
                       THEN (analysis_close - price_resistance_norm) / atr14_norm
                   END AS daily_breakout_excess_atr,
                   available_at <= decision_at AND hard_valid
                       AND NOT corporate_action_blocking
                       AND tradable_state
                       AND effective_industry IS NOT NULL
                       AS row_research_valid
            FROM peer_sums
        ), regime AS (
            SELECT *,
                   exp(sum(ln(greatest(1.0 + market_return, 1e-8))) OVER (
                       PARTITION BY symbol ORDER BY trade_date
                       ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                   )) - 1.0 AS market_return_20,
                   count(market_return) OVER (
                       PARTITION BY symbol ORDER BY trade_date
                       ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                   ) AS market_return_count20,
                   exp(sum(ln(greatest(1.0 + sector_return_loo, 1e-8))) OVER (
                       PARTITION BY symbol ORDER BY trade_date
                       ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                   )) - 1.0 AS sector_return_20,
                   count(sector_return_loo) OVER (
                       PARTITION BY symbol ORDER BY trade_date
                       ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                   ) AS sector_return_count20
            FROM evidence
        ), breakout_history AS (
            SELECT *,
                   max(CASE WHEN row_research_valid
                            THEN daily_breakout_excess_atr END) OVER (
                       PARTITION BY symbol ORDER BY trade_date
                       ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
                   ) AS prior_breakout_excess_atr,
                   arg_max(
                       CASE WHEN row_research_valid THEN price_resistance_norm END,
                       CASE WHEN row_research_valid
                            THEN daily_breakout_excess_atr END
                   ) OVER (
                       PARTITION BY symbol ORDER BY trade_date
                       ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
                   ) AS breakout_anchor_resistance_norm,
                   arg_max(
                       CASE WHEN row_research_valid THEN trade_date END,
                       CASE WHEN row_research_valid
                            THEN daily_breakout_excess_atr END
                   ) OVER (
                       PARTITION BY symbol ORDER BY trade_date
                       ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
                   ) AS breakout_trade_date
            FROM regime
        ), classified AS (
            SELECT *,
                   CASE WHEN market_return_20 > 0.02 THEN 'RISK_ON'
                        WHEN market_return_20 < -0.02 THEN 'RISK_OFF'
                        ELSE 'NEUTRAL' END AS market_state,
                   CASE WHEN sector_return_20 > 0.02 THEN 'STRONG'
                        WHEN sector_return_20 < -0.02 THEN 'WEAK'
                        ELSE 'NEUTRAL' END AS sector_state,
                   analysis_low <= breakout_anchor_resistance_norm
                                       + 0.25 * atr14_norm
                       AND analysis_close >= breakout_anchor_resistance_norm
                                             - 0.25 * atr14_norm
                       AS support_regained_price,
                   row_research_valid
                       AND symbol_session_index >= 60
                       AND market_return_count20 = 20
                       AND sector_return_count20 = 20
                       AND atr14_norm > 0
                       AS research_hard_valid
            FROM breakout_history
        )
        SELECT
            symbol, trade_date, decision_at, available_at, daily_snapshot_id,
            symbol_session_index, effective_industry AS industry,
            effective_industry_source AS industry_source, pit_grade AS industry_pit_grade,
            tradable_state, research_hard_valid, support_regained_price,
            prior_breakout_excess_atr, breakout_trade_date,
            breakout_anchor_resistance_norm * price_coordinate_factor
                AS breakout_anchor_resistance,
            price_resistance_norm * price_coordinate_factor AS price_resistance,
            atr14_norm * price_coordinate_factor AS atr14,
            CASE WHEN close_lag20_norm > 0
                 THEN analysis_close / close_lag20_norm - 1.0 END AS momentum_20,
            market_state, sector_state, market_return_20, sector_return_20,
            turnover_fraction, turnover_mean20, volume, amount, amount_mean20,
            open, high, low, close, preclose, stock_return,
            price_coordinate_factor, index_symbol, snapshot_id AS source_snapshot_id
        FROM classified
        WHERE trade_date BETWEEN DATE '2020-01-02' AND DATE '2022-12-30'
          AND research_hard_valid
          AND support_regained_price
          AND prior_breakout_excess_atr >= 0.25
          AND market_state IN ('RISK_ON', 'NEUTRAL')
          AND sector_state IN ('STRONG', 'NEUTRAL')
        ORDER BY symbol, trade_date
    """


def _validate_output(path: Path) -> dict[str, Any]:
    con = duckdb.connect()
    try:
        columns = tuple(
            str(row[0])
            for row in con.execute(
                f"DESCRIBE SELECT * FROM read_parquet({_sql_text(str(path))})"
            ).fetchall()
        )
        assert_price_volume_candidate_schema(columns)
        row = con.execute(
            f"""
            SELECT count(*) AS rows,
                   count(DISTINCT symbol) AS symbols,
                   min(trade_date), max(trade_date),
                   count(*) - count(DISTINCT candidate_id) AS duplicate_ids,
                   count(*) FILTER (WHERE available_at > decision_at) AS future_rows,
                   count(*) FILTER (WHERE candidate_uses_chip_fields) AS chip_rows
            FROM read_parquet({_sql_text(str(path))})
            """
        ).fetchone()
        annual = con.execute(
            f"""
            SELECT year(trade_date)::INTEGER, count(*)
            FROM read_parquet({_sql_text(str(path))})
            GROUP BY 1 ORDER BY 1
            """
        ).fetchall()
    finally:
        con.close()
    if row is None:
        raise RuntimeError("candidate output validation returned no metrics")
    if row[2] < datetime(2020, 1, 2).date() or row[3] > datetime(2022, 12, 30).date():
        raise RuntimeError("candidate output escaped the preregistered date range")
    if any(int(row[index]) != 0 for index in (4, 5, 6)):
        raise RuntimeError(f"candidate output integrity failure: {row}")
    return {
        "rows": int(row[0]),
        "symbols": int(row[1]),
        "minimum_date": row[2].isoformat(),
        "maximum_date": row[3].isoformat(),
        "duplicate_candidate_ids": int(row[4]),
        "future_available_rows": int(row[5]),
        "chip_field_rows": int(row[6]),
        "annual_rows": {str(year): int(count) for year, count in annual},
    }


def _path_year(path: Path) -> int | None:
    for part in path.parts:
        if part.startswith("partition_year="):
            value = part.removeprefix("partition_year=")
            if value.isdigit() and len(value) == 4:
                return int(value)
    return None


def _sql_text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


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
