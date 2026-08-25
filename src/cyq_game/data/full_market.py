"""One-pass construction of the all-market daily PIT-B research dataset."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .registry import (
    DataActivationError,
    DataAssetRegistry,
    DataOperation,
    InputBinding,
    InputSnapshotManifest,
)

PIPELINE_VERSION = "daily-pit-b-v2"
KNOWN_LIMITS = (0.05, 0.10, 0.20, 0.30)
HISTORICAL_SYMBOL_EFFECTIVE_DATES = {
    "001872.SZ": date(2018, 12, 26),
    "001914.SZ": date(2019, 12, 16),
    "302132.SZ": date(2025, 2, 17),
    "601360.SH": date(2018, 2, 28),
}


def build_daily_pit_b_dataset(
    *,
    registry_path: str | Path,
    input_manifest_path: str | Path,
    output_dir: str | Path,
    start: date | None = None,
    end: date | None = None,
    benchmark: str = "csi000300",
) -> dict[str, Any]:
    """Build the frozen daily PIT-B input table and its five necessary audits.

    This function performs data preparation only. It does not calculate chip
    states, signals, orders, performance, or reports.
    """

    registry = DataAssetRegistry.load(registry_path)
    manifest = InputSnapshotManifest.load(input_manifest_path, registry=registry)
    scope_start = start or manifest.scope_start
    scope_end = end or manifest.scope_end
    manifest.require_range(scope_start, scope_end)
    manifest.authorize(DataOperation.INGEST, registry=registry)
    if scope_end < scope_start:
        raise DataActivationError("daily PIT-B scope end precedes start")
    if not benchmark.strip():
        raise DataActivationError("benchmark must be non-empty")

    output = Path(output_dir).expanduser().resolve()
    build_id = _build_id(manifest.sha256, scope_start, scope_end, benchmark)
    reused = _reuse_completed_output(output, build_id)
    if reused is not None:
        reused["reused"] = True
        return reused
    if output.exists():
        raise DataActivationError(
            f"output exists without matching completed build evidence: {output}"
        )

    inputs = _resolve_inputs(manifest, benchmark)
    temp_root = output.parent / f".{output.name}.tmp-{uuid.uuid4().hex}"
    temp_root.mkdir(parents=True)
    (temp_root / "duckdb_tmp").mkdir()
    connection: Any | None = None
    try:
        duckdb = importlib.import_module("duckdb")
        connection = duckdb.connect(database=str(temp_root / "build.duckdb"))
        connection.execute(f"PRAGMA threads={max(1, os.cpu_count() or 1)}")
        connection.execute(f"PRAGMA temp_directory={_sql_literal(str(temp_root / 'duckdb_tmp'))}")
        _create_sources(connection, inputs, scope_start, scope_end, benchmark)
        _create_float_timeline(connection, scope_end)
        _create_action_events(connection, scope_start, scope_end)
        _create_enriched(connection, manifest, build_id)
        audit = _audit_build(
            connection,
            manifest=manifest,
            build_id=build_id,
            start=scope_start,
            end=scope_end,
            benchmark=benchmark,
            inputs=inputs,
        )
        data_dir = temp_root / "daily"
        connection.execute(
            "COPY (SELECT * FROM enriched "
            "ORDER BY trade_date, symbol) TO "
            f"{_sql_literal(str(data_dir))} "
            "(FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY (partition_year), "
            "ROW_GROUP_SIZE 100000)"
        )
        audit["output"] = {
            "root": str(output),
            "dataset": str(output / "daily"),
            "partitioning": "partition_year",
            "format": "parquet/zstd",
        }
        audit["completed_at"] = datetime.now().astimezone().isoformat()
        (temp_root / "audit.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        connection.close()
        connection = None
        for transient in (temp_root / "build.duckdb", temp_root / "duckdb_tmp"):
            if transient.is_dir():
                shutil.rmtree(transient)
            elif transient.exists():
                transient.unlink()
        output.parent.mkdir(parents=True, exist_ok=True)
        temp_root.replace(output)
        audit["reused"] = False
        return audit
    except Exception:
        if connection is not None:
            connection.close()
        shutil.rmtree(temp_root, ignore_errors=True)
        raise


def _resolve_inputs(manifest: InputSnapshotManifest, benchmark: str) -> dict[str, Path | str]:
    daily = manifest.binding("daily_bars")
    state = manifest.binding("trading_state")
    index = manifest.binding("index_daily")
    industry = manifest.binding("industry_membership")
    capital = manifest.binding("circulating_shares")
    actions = manifest.binding("corporate_actions")

    _require_inventory_matches(daily, suffix=".none.parquet")
    _require_inventory_matches(state, suffix=".parquet")
    _require_inventory_file(index, f"{benchmark}.parquet")
    _require_inventory_file(industry, "industry_daily.parquet")
    _require_inventory_file(capital, "qmt_capital.parquet")
    _require_inventory_file(actions, "normalized/distributions.parquet")
    _require_inventory_file(actions, "normalized/rights_issues.parquet")
    return {
        "daily": str(daily.path / "*.none.parquet"),
        "state": str(state.path / "*.parquet"),
        "index": index.path / f"{benchmark}.parquet",
        "industry": industry.path / "industry_daily.parquet",
        "capital": capital.path / "qmt_capital.parquet",
        "distributions": actions.path / "normalized/distributions.parquet",
        "rights": actions.path / "normalized/rights_issues.parquet",
    }


def _require_inventory_matches(binding: InputBinding, *, suffix: str) -> None:
    entries = _inventory_entries(binding)
    expected = {name for name in entries if name.endswith(suffix)}
    actual = {
        path.relative_to(binding.path).as_posix()
        for path in binding.path.glob(f"*{suffix}")
        if path.is_file()
    }
    if not expected or actual != expected:
        raise DataActivationError(
            f"physical file set differs from frozen inventory for {binding.role}"
        )
    for name in expected:
        size = entries[name]
        if (binding.path / name).stat().st_size != size:
            raise DataActivationError(f"physical file size changed: {binding.path / name}")


def _require_inventory_file(binding: InputBinding, relative: str) -> None:
    entries = _inventory_entries(binding)
    try:
        size = entries[relative]
    except KeyError as exc:
        raise DataActivationError(
            f"selected input is absent from frozen inventory: {binding.role}/{relative}"
        ) from exc
    path = binding.path / relative
    if not path.is_file() or path.stat().st_size != size:
        raise DataActivationError(f"selected input changed or is missing: {path}")


def _inventory_entries(binding: InputBinding) -> dict[str, int]:
    if binding.inventory_manifest is None:
        raise DataActivationError(f"binding has no frozen inventory: {binding.role}")
    payload = json.loads(binding.inventory_manifest.read_text(encoding="utf-8"))
    raw_files = payload.get("files")
    if not isinstance(raw_files, list):
        raise DataActivationError(f"invalid frozen inventory: {binding.inventory_manifest}")
    result: dict[str, int] = {}
    for item in raw_files:
        if not isinstance(item, dict):
            raise DataActivationError(f"invalid frozen inventory: {binding.inventory_manifest}")
        name = item.get("path")
        size = item.get("size")
        if not isinstance(name, str) or not isinstance(size, int):
            raise DataActivationError(f"invalid frozen inventory: {binding.inventory_manifest}")
        result[name] = size
    return result


def _create_sources(
    connection: Any,
    inputs: dict[str, Path | str],
    start: date,
    end: date,
    benchmark: str,
) -> None:
    start_sql = _sql_literal(start.isoformat())
    end_sql = _sql_literal(end.isoformat())
    symbol_sql = _canonical_symbol_sql("symbol")
    qmt_symbol_sql = _canonical_symbol_sql("qmt_code")
    connection.execute(
        f"""
        CREATE TEMP TABLE daily AS
        SELECT CAST(trade_date AS DATE) AS trade_date,
               {symbol_sql} AS symbol,
               CAST(adjust AS VARCHAR) AS adjust,
               CAST(open AS DOUBLE) AS open,
               CAST(high AS DOUBLE) AS high,
               CAST(low AS DOUBLE) AS low,
               CAST(close AS DOUBLE) AS close,
               CAST(preclose AS DOUBLE) AS preclose,
               CAST(volume AS DOUBLE) AS volume,
               CAST(amount AS DOUBLE) AS amount,
               CAST(turnover_rate AS DOUBLE) AS source_turnover_rate
        FROM read_parquet({_sql_literal(str(inputs["daily"]))}, union_by_name=true)
        WHERE CAST(trade_date AS DATE) BETWEEN {start_sql} AND {end_sql}
        """
    )
    connection.execute(
        f"""
        CREATE TEMP TABLE state AS
        SELECT CAST(trade_date AS DATE) AS trade_date,
               {symbol_sql} AS symbol,
               CAST(trade_status AS INTEGER) AS trade_status,
               CAST(is_st AS BOOLEAN) AS is_st,
               CAST(limit_pct AS DOUBLE) AS limit_pct,
               CAST(up_limit_price AS DOUBLE) AS up_limit_price,
               CAST(down_limit_price AS DOUBLE) AS down_limit_price,
               CAST(buy_blocked_open AS BOOLEAN) AS buy_blocked_open,
               CAST(sell_blocked_open AS BOOLEAN) AS sell_blocked_open,
               CAST(state_source AS VARCHAR) AS state_source
        FROM read_parquet({_sql_literal(str(inputs["state"]))}, union_by_name=true)
        WHERE CAST(trade_date AS DATE) BETWEEN {start_sql} AND {end_sql}
        """
    )
    connection.execute(
        f"""
        CREATE TEMP TABLE industry AS
        SELECT CAST(trade_date AS DATE) AS trade_date,
               {symbol_sql} AS symbol,
               CAST(industry AS VARCHAR) AS industry,
               CAST(source_notice_date AS DATE) AS source_notice_date,
               CAST(source_report_date AS DATE) AS source_report_date,
               CAST(source AS VARCHAR) AS industry_source
        FROM read_parquet({_sql_literal(str(inputs["industry"]))})
        WHERE COALESCE(CAST(industry AS VARCHAR), '') <> ''
          AND CAST(industry AS VARCHAR) <> 'UNKNOWN'
          AND CAST(source_notice_date AS DATE) < CAST(trade_date AS DATE)
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY CAST(trade_date AS DATE), {symbol_sql}
          ORDER BY CAST(source_notice_date AS DATE) DESC,
                   CAST(source_report_date AS DATE) DESC NULLS LAST
        ) = 1
        """
    )
    connection.execute(
        f"""
        CREATE TEMP TABLE market AS
        SELECT CAST(trade_date AS DATE) AS trade_date,
               CAST(index_symbol AS VARCHAR) AS index_symbol,
               CAST(index_name AS VARCHAR) AS index_name,
               CAST(open AS DOUBLE) AS market_open,
               CAST(high AS DOUBLE) AS market_high,
               CAST(low AS DOUBLE) AS market_low,
               CAST(close AS DOUBLE) AS market_close,
               CAST(volume AS DOUBLE) AS market_volume,
               CAST(amount AS DOUBLE) AS market_amount
        FROM read_parquet({_sql_literal(str(inputs["index"]))})
        WHERE CAST(trade_date AS DATE) BETWEEN {start_sql} AND {end_sql}
          AND index_symbol = {_sql_literal(benchmark)}
        """
    )
    connection.execute(
        f"""
        CREATE TEMP TABLE float_facts AS
        WITH parsed AS (
          SELECT {qmt_symbol_sql} AS symbol,
                 TRY_STRPTIME(CAST(m_timetag AS VARCHAR), '%Y%m%d')::DATE
                   AS float_effective_date,
                 TRY_STRPTIME(CAST(m_anntime AS VARCHAR), '%Y%m%d')::DATE
                   AS float_announced_date,
                 CAST(circulating_capital AS DOUBLE) AS circulating_shares,
                 CAST(source AS VARCHAR) AS float_source
          FROM read_parquet({_sql_literal(str(inputs["capital"]))})
        )
        SELECT *,
               CASE WHEN float_effective_date IS NOT NULL
                          AND float_announced_date IS NOT NULL
                    THEN GREATEST(float_effective_date, float_announced_date)
               END AS float_available_date
        FROM parsed
        """
    )
    _create_raw_actions(connection, inputs)


def _create_raw_actions(connection: Any, inputs: dict[str, Path | str]) -> None:
    symbol_sql = _canonical_symbol_sql("symbol")
    connection.execute(
        f"""
        CREATE TEMP VIEW distributions_raw AS
        SELECT {symbol_sql} AS symbol,
               CAST(event_id AS VARCHAR) AS event_id,
               CAST(announcement_date AS DATE) AS announcement_date,
               CAST(known_at AS DATE) AS known_date,
               CAST(effective_date AS DATE) AS effective_date,
               CAST(share_multiplier AS DOUBLE) AS share_multiplier,
               CAST(cash_per_share_gross AS DOUBLE) AS cash_per_share_gross,
               CAST(source_terms_complete AS BOOLEAN) AS source_terms_complete,
               CAST(execution_timing_resolved AS BOOLEAN) AS execution_timing_resolved,
               CAST(source AS VARCHAR) AS action_source
        FROM read_parquet({_sql_literal(str(inputs["distributions"]))})
        """
    )
    connection.execute(
        f"""
        CREATE TEMP VIEW rights_raw AS
        SELECT {symbol_sql} AS symbol,
               CAST(event_id AS VARCHAR) AS event_id,
               CAST(announcement_date AS DATE) AS announcement_date,
               CAST(known_at AS DATE) AS known_date,
               CAST(effective_date AS DATE) AS effective_date,
               CAST(rights_subscription_ratio AS DOUBLE) AS rights_ratio,
               CAST(rights_subscription_price AS DOUBLE) AS rights_price,
               CAST(source_terms_complete AS BOOLEAN) AS source_terms_complete,
               CAST(source AS VARCHAR) AS action_source
        FROM read_parquet({_sql_literal(str(inputs["rights"]))})
        """
    )


def _create_float_timeline(connection: Any, end: date) -> None:
    end_sql = _sql_literal(end.isoformat())
    connection.execute(
        f"""
        CREATE TEMP TABLE float_timeline AS
        WITH usable AS (
          SELECT * FROM float_facts
          WHERE float_available_date <= {end_sql}
        ), event_dates AS (
          SELECT DISTINCT symbol, float_available_date FROM usable
        ), ranked AS (
          SELECT e.symbol,
                 e.float_available_date AS timeline_date,
                 f.float_effective_date,
                 f.float_announced_date,
                 f.float_available_date,
                 f.circulating_shares,
                 f.float_source,
                 ROW_NUMBER() OVER (
                   PARTITION BY e.symbol, e.float_available_date
                   ORDER BY f.float_effective_date DESC,
                            f.float_announced_date DESC,
                            f.float_source DESC
                 ) AS choice_rank
          FROM event_dates e
          JOIN usable f
            ON f.symbol = e.symbol
           AND f.float_available_date <= e.float_available_date
        )
        SELECT * EXCLUDE (choice_rank) FROM ranked WHERE choice_rank = 1
        """
    )


def _create_action_events(connection: Any, start: date, end: date) -> None:
    start_sql = _sql_literal(start.isoformat())
    end_sql = _sql_literal(end.isoformat())
    connection.execute(
        f"""
        CREATE TEMP TABLE action_events AS
        WITH distributions AS (
          SELECT *,
                 CASE WHEN effective_date IS NULL THEN known_date
                      ELSE GREATEST(known_date, effective_date)
                 END AS processing_date,
                 CASE
                   WHEN announcement_date > known_date THEN 'announcement_after_known'
                   WHEN effective_date IS NULL THEN 'missing_effective_date'
                   WHEN known_date > effective_date THEN 'known_after_effective'
                   WHEN source_terms_complete IS DISTINCT FROM TRUE THEN 'incomplete_terms'
                   WHEN share_multiplier IS NOT NULL
                        AND (NOT ISFINITE(share_multiplier)
                             OR share_multiplier <= 0 OR share_multiplier > 100)
                     THEN 'share_multiplier_unit'
                   WHEN cash_per_share_gross IS NOT NULL
                        AND (NOT ISFINITE(cash_per_share_gross)
                             OR cash_per_share_gross < 0
                             OR cash_per_share_gross > 100000)
                     THEN 'cash_per_share_unit'
                   WHEN COALESCE(share_multiplier, 1) > 1
                        AND execution_timing_resolved IS DISTINCT FROM TRUE
                     THEN 'share_timing_unresolved'
                   WHEN COALESCE(share_multiplier, 1) <= 1
                        AND COALESCE(cash_per_share_gross, 0) <= 0
                     THEN 'no_positive_terms'
                 END AS problem
          FROM distributions_raw
        ), rights AS (
          SELECT *,
                 CASE WHEN effective_date IS NULL THEN known_date
                      ELSE GREATEST(known_date, effective_date)
                 END AS processing_date,
                 CASE
                   WHEN announcement_date > known_date THEN 'announcement_after_known'
                   WHEN effective_date IS NULL THEN 'missing_effective_date'
                   WHEN known_date > effective_date THEN 'known_after_effective'
                   WHEN source_terms_complete IS DISTINCT FROM TRUE THEN 'incomplete_terms'
                   WHEN rights_ratio IS NULL OR NOT ISFINITE(rights_ratio)
                        OR rights_ratio <= 0 OR rights_ratio > 100
                     THEN 'rights_ratio_unit'
                   WHEN rights_price IS NULL OR NOT ISFINITE(rights_price)
                        OR rights_price < 0 OR rights_price > 1000000
                     THEN 'rights_price_unit'
                 END AS problem
          FROM rights_raw
        ), events AS (
          SELECT symbol, event_id, processing_date, known_date, effective_date,
                 action_source, problem,
                 COALESCE(share_multiplier, 1.0) AS share_multiplier,
                 COALESCE(cash_per_share_gross, 0.0) AS cash_per_share,
                 NULL::DOUBLE AS rights_ratio,
                 NULL::DOUBLE AS rights_price,
                 problem IS NOT NULL AS blocking,
                 'DISTRIBUTION' AS action_type
          FROM distributions
          UNION ALL
          SELECT symbol, event_id, processing_date, known_date, effective_date,
                 action_source, problem,
                 1.0 AS share_multiplier,
                 0.0 AS cash_per_share,
                 rights_ratio,
                 rights_price,
                 TRUE AS blocking,
                 'RIGHTS_ISSUE' AS action_type
          FROM rights
        )
        SELECT * FROM events
        WHERE processing_date BETWEEN {start_sql} AND {end_sql}
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE action_daily AS
        SELECT symbol, processing_date AS trade_date,
               COUNT(*) AS corporate_action_count,
               STRING_AGG(event_id, '|' ORDER BY event_id) AS corporate_action_ids,
               STRING_AGG(DISTINCT action_source, '|' ORDER BY action_source)
                 AS corporate_action_source,
               MAX(known_date) AS corporate_action_available_date,
               BOOL_OR(blocking) AS corporate_action_blocking,
               STRING_AGG(problem, '|' ORDER BY event_id)
                 FILTER (WHERE problem IS NOT NULL) AS corporate_action_problems,
               PRODUCT(CASE WHEN action_type = 'DISTRIBUTION' AND NOT blocking
                            THEN share_multiplier ELSE 1.0 END)
                 AS share_multiplier,
               SUM(CASE WHEN action_type = 'DISTRIBUTION' AND NOT blocking
                        THEN cash_per_share ELSE 0.0 END) AS cash_per_share,
               MAX(rights_ratio) AS rights_ratio,
               MAX(rights_price) AS rights_price
        FROM action_events
        GROUP BY symbol, processing_date
        """
    )


def _create_enriched(connection: Any, manifest: InputSnapshotManifest, build_id: str) -> None:
    snapshots = {
        role: _sql_literal(manifest.binding(role).snapshot_id)
        for role in (
            "daily_bars",
            "trading_state",
            "index_daily",
            "industry_membership",
            "circulating_shares",
            "corporate_actions",
        )
    }
    limits = ", ".join(str(item) for item in KNOWN_LIMITS)
    historical_identity_valid_sql = _historical_identity_valid_sql()
    connection.execute(
        f"""
        CREATE TEMP TABLE enriched AS
        WITH joined AS (
          SELECT d.*,
                 s.trade_status, s.is_st, s.limit_pct,
                 s.up_limit_price, s.down_limit_price,
                 s.buy_blocked_open, s.sell_blocked_open, s.state_source,
                 i.industry, i.source_notice_date, i.source_report_date,
                 i.industry_source,
                 f.float_effective_date, f.float_announced_date,
                 f.float_available_date, f.circulating_shares, f.float_source,
                 m.index_symbol, m.index_name, m.market_open, m.market_high,
                 m.market_low, m.market_close, m.market_volume, m.market_amount,
                 a.corporate_action_count, a.corporate_action_ids,
                 a.corporate_action_source, a.corporate_action_available_date,
                 a.corporate_action_blocking, a.corporate_action_problems,
                 a.share_multiplier, a.cash_per_share, a.rights_ratio, a.rights_price
          FROM daily d
          LEFT JOIN state s USING (trade_date, symbol)
          ASOF LEFT JOIN industry i
            ON d.symbol = i.symbol AND d.trade_date >= i.trade_date
          ASOF LEFT JOIN float_timeline f
            ON d.symbol = f.symbol AND d.trade_date >= f.timeline_date
          LEFT JOIN market m USING (trade_date)
          LEFT JOIN action_daily a USING (trade_date, symbol)
        ), flags AS (
          SELECT *,
            symbol IS NOT NULL
              AND adjust = 'none'
              AND open IS NOT NULL AND ISFINITE(open) AND open > 0
              AND high IS NOT NULL AND ISFINITE(high) AND high > 0
              AND low IS NOT NULL AND ISFINITE(low) AND low > 0
              AND close IS NOT NULL AND ISFINITE(close) AND close > 0
              AND preclose IS NOT NULL AND ISFINITE(preclose) AND preclose > 0
              AND high >= GREATEST(open, close, low)
              AND low <= LEAST(open, close, high)
              AND volume IS NOT NULL AND ISFINITE(volume) AND volume >= 0
              AND amount IS NOT NULL AND ISFINITE(amount) AND amount >= 0
              AS bar_valid,
            trade_status IN (0, 1)
              AND is_st IS NOT NULL
              AND limit_pct IN ({limits})
              AND up_limit_price IS NOT NULL AND ISFINITE(up_limit_price)
              AND down_limit_price IS NOT NULL AND ISFINITE(down_limit_price)
              AND up_limit_price > 0 AND down_limit_price > 0
              AND up_limit_price >= down_limit_price
              AND buy_blocked_open IS NOT NULL AND sell_blocked_open IS NOT NULL
              AND COALESCE(state_source, '') <> ''
              AND (trade_status <> 0 OR (buy_blocked_open AND sell_blocked_open))
              AND NOT (is_st AND state_source <> 'baostock_none_daily')
              AS trading_state_valid,
            COALESCE(industry, '') <> ''
              AND COALESCE(industry, '') <> 'UNKNOWN'
              AND source_notice_date IS NOT NULL
              AND source_notice_date < trade_date
              AND COALESCE(industry_source, '') <> ''
              AS industry_valid,
            float_effective_date IS NOT NULL
              AND float_announced_date IS NOT NULL
              AND float_available_date <= trade_date
              AND float_effective_date <= trade_date
              AND float_announced_date <= trade_date
              AND circulating_shares IS NOT NULL
              AND ISFINITE(circulating_shares) AND circulating_shares > 0
              AND COALESCE(float_source, '') <> ''
              AS float_valid,
            NOT COALESCE(corporate_action_blocking, FALSE)
              AND COALESCE(corporate_action_available_date, trade_date) <= trade_date
              AS corporate_action_valid,
            index_symbol IS NOT NULL
              AND market_open IS NOT NULL AND ISFINITE(market_open) AND market_open > 0
              AND market_high IS NOT NULL AND ISFINITE(market_high) AND market_high > 0
              AND market_low IS NOT NULL AND ISFINITE(market_low) AND market_low > 0
              AND market_close IS NOT NULL AND ISFINITE(market_close) AND market_close > 0
              AND market_high >= GREATEST(market_open, market_close, market_low)
              AND market_low <= LEAST(market_open, market_close, market_high)
              AND market_volume IS NOT NULL AND ISFINITE(market_volume)
              AND market_volume >= 0
              AND market_amount IS NOT NULL AND ISFINITE(market_amount)
              AND market_amount >= 0
              AS market_valid,
            limit_pct IN ({limits}) AS market_rule_valid,
            {historical_identity_valid_sql} AS historical_identity_valid
          FROM joined
        ), assessed AS (
          SELECT *,
                 bar_valid AND trading_state_valid AND industry_valid
                   AND float_valid AND corporate_action_valid
                   AND market_valid AND market_rule_valid
                   AND historical_identity_valid AS hard_valid,
                 CONCAT_WS('|',
                   CASE WHEN NOT bar_valid THEN 'invalid_daily_bar' END,
                   CASE WHEN trade_status IS NULL THEN 'missing_trading_state' END,
                   CASE WHEN trade_status IS NOT NULL AND NOT trading_state_valid
                        THEN 'invalid_or_unverified_trading_state' END,
                   CASE WHEN is_st AND state_source <> 'baostock_none_daily'
                        THEN 'historical_st_status_unverified' END,
                   CASE WHEN industry IS NULL THEN 'missing_industry' END,
                   CASE WHEN industry IS NOT NULL AND NOT industry_valid
                        THEN 'invalid_or_noncausal_industry' END,
                   CASE WHEN float_effective_date IS NULL THEN 'missing_historical_float' END,
                   CASE WHEN float_effective_date IS NOT NULL AND NOT float_valid
                        THEN 'invalid_or_noncausal_float' END,
                   CASE WHEN NOT corporate_action_valid
                        THEN 'blocking_corporate_action' END,
                   CASE WHEN index_symbol IS NULL THEN 'missing_market_bar' END,
                   CASE WHEN index_symbol IS NOT NULL AND NOT market_valid
                        THEN 'invalid_market_bar' END,
                   CASE WHEN NOT market_rule_valid THEN 'unknown_market_rule' END,
                   CASE WHEN NOT historical_identity_valid
                        THEN 'HISTORICAL_SYMBOL_ALIAS_NOT_PIT_SAFE' END
                 ) AS invalid_reasons
          FROM flags
        )
        SELECT trade_date,
               CAST(trade_date AS TIMESTAMP) + INTERVAL '15 hours' AS decision_at,
               'Asia/Shanghai' AS decision_timezone,
               symbol,
               open, high, low, close, preclose, volume, amount,
               source_turnover_rate,
               CASE WHEN circulating_shares > 0 THEN volume / circulating_shares END
                 AS turnover_fraction,
               CASE WHEN circulating_shares > 0 THEN volume / circulating_shares * 100 END
                 AS turnover_pct,
               trade_status, is_st, limit_pct, up_limit_price, down_limit_price,
               buy_blocked_open, sell_blocked_open, state_source,
               industry, source_notice_date, source_report_date, industry_source,
               float_effective_date, float_announced_date, float_available_date,
               circulating_shares, float_source,
               index_symbol, index_name, market_open, market_high, market_low,
               market_close, market_volume, market_amount,
               COALESCE(corporate_action_count, 0) AS corporate_action_count,
               corporate_action_ids,
               COALESCE(corporate_action_source,
                        'frozen_cninfo_no_known_event_as_of_decision')
                 AS corporate_action_source,
               COALESCE(corporate_action_available_date, trade_date)
                 AS corporate_action_available_date,
               COALESCE(corporate_action_blocking, FALSE)
                 AS corporate_action_blocking,
               corporate_action_problems,
               COALESCE(share_multiplier, 1.0) AS share_multiplier,
               COALESCE(cash_per_share, 0.0) AS cash_per_share,
               rights_ratio, rights_price,
               CASE
                 WHEN limit_pct = 0.05 THEN 'CN_A_SHARE_ST_5_T1_LOT100_V1'
                 WHEN limit_pct = 0.10 THEN 'CN_A_SHARE_MAIN_10_T1_LOT100_V1'
                 WHEN limit_pct = 0.20 THEN 'CN_A_SHARE_REG_20_T1_LOT100_V1'
                 WHEN limit_pct = 0.30 THEN 'CN_A_SHARE_BSE_30_T1_LOT100_V1'
               END AS market_rule_id,
               'DERIVED_FROM_FROZEN_DAILY_STATE_V1' AS market_rule_source,
               bar_valid, trading_state_valid, industry_valid, float_valid,
               corporate_action_valid, market_valid, market_rule_valid,
               historical_identity_valid,
               hard_valid, invalid_reasons,
               trade_status = 1 AND hard_valid AS current_day_data_tradable,
               CAST(trade_date AS TIMESTAMP) + INTERVAL '15 hours' AS available_at,
               {_sql_literal(build_id)} AS snapshot_id,
               'B_CAUSAL_RESEARCH' AS pit_grade,
               FALSE AS strict_archive_ready,
               {snapshots["daily_bars"]} AS daily_snapshot_id,
               {snapshots["trading_state"]} AS trading_state_snapshot_id,
               {snapshots["industry_membership"]} AS industry_snapshot_id,
               {snapshots["circulating_shares"]} AS float_snapshot_id,
               {snapshots["corporate_actions"]} AS corporate_action_snapshot_id,
               {snapshots["index_daily"]} AS market_snapshot_id,
               YEAR(trade_date) AS partition_year
        FROM assessed
        """
    )


def _audit_build(
    connection: Any,
    *,
    manifest: InputSnapshotManifest,
    build_id: str,
    start: date,
    end: date,
    benchmark: str,
    inputs: dict[str, Path | str],
) -> dict[str, Any]:
    def scalar(sql: str) -> int:
        return int(connection.execute(sql).fetchone()[0])

    daily_rows = scalar("SELECT COUNT(*) FROM daily")
    output_rows = scalar("SELECT COUNT(*) FROM enriched")
    hard_valid_rows = scalar("SELECT COUNT(*) FROM enriched WHERE hard_valid")
    per_year = [
        {"year": int(year), "rows": int(rows), "hard_valid_rows": int(valid)}
        for year, rows, valid in connection.execute(
            "SELECT partition_year, COUNT(*), COUNT(*) FILTER (WHERE hard_valid) "
            "FROM enriched GROUP BY partition_year ORDER BY partition_year"
        ).fetchall()
    ]
    coverage_counts = {
        name: scalar(f"SELECT COUNT(*) FROM enriched WHERE {column}")
        for name, column in (
            ("daily_bar", "bar_valid"),
            ("trading_state", "trading_state_valid"),
            ("industry", "industry_valid"),
            ("historical_float", "float_valid"),
            ("corporate_action", "corporate_action_valid"),
            ("market", "market_valid"),
            ("market_rule", "market_rule_valid"),
            ("historical_identity", "historical_identity_valid"),
        )
    }
    coverage_issues = int(daily_rows == 0 or output_rows != daily_rows or hard_valid_rows == 0)
    coverage_issues += sum(value == 0 for value in coverage_counts.values())

    duplicate_counts = {
        "daily_keys": scalar(
            "SELECT COUNT(*) FROM (SELECT trade_date,symbol FROM daily "
            "GROUP BY ALL HAVING COUNT(*)>1)"
        ),
        "state_keys": scalar(
            "SELECT COUNT(*) FROM (SELECT trade_date,symbol FROM state "
            "GROUP BY ALL HAVING COUNT(*)>1)"
        ),
        "industry_keys": scalar(
            "SELECT COUNT(*) FROM (SELECT trade_date,symbol FROM industry "
            "GROUP BY ALL HAVING COUNT(*)>1)"
        ),
        "market_keys": scalar(
            "SELECT COUNT(*) FROM (SELECT trade_date FROM market GROUP BY ALL HAVING COUNT(*)>1)"
        ),
        "float_fact_keys": scalar(
            "SELECT COUNT(*) FROM (SELECT symbol,float_effective_date,float_announced_date "
            "FROM float_facts GROUP BY ALL HAVING COUNT(*)>1)"
        ),
        "distribution_event_ids": scalar(
            "SELECT COUNT(*) FROM (SELECT event_id FROM distributions_raw "
            "GROUP BY ALL HAVING COUNT(*)>1)"
        ),
        "rights_event_ids": scalar(
            "SELECT COUNT(*) FROM (SELECT event_id FROM rights_raw GROUP BY ALL HAVING COUNT(*)>1)"
        ),
        "output_keys": scalar(
            "SELECT COUNT(*) FROM (SELECT trade_date,symbol FROM enriched "
            "GROUP BY ALL HAVING COUNT(*)>1)"
        ),
    }
    duplicate_issues = sum(duplicate_counts.values())

    temporal_counts = {
        "float_after_decision": scalar(
            "SELECT COUNT(*) FROM enriched WHERE float_available_date > trade_date "
            "OR float_effective_date > trade_date OR float_announced_date > trade_date"
        ),
        "industry_not_prior": scalar(
            "SELECT COUNT(*) FROM enriched WHERE source_notice_date >= trade_date"
        ),
        "action_after_decision": scalar(
            "SELECT COUNT(*) FROM enriched WHERE corporate_action_available_date > trade_date"
        ),
        "aggregate_available_after_decision": scalar(
            "SELECT COUNT(*) FROM enriched WHERE available_at > decision_at"
        ),
    }
    temporal_issues = sum(temporal_counts.values())

    consistency_counts = {
        "hard_valid_with_invalid_domain": scalar(
            "SELECT COUNT(*) FROM enriched WHERE hard_valid AND NOT "
            "(bar_valid AND trading_state_valid AND industry_valid AND float_valid "
            "AND corporate_action_valid AND market_valid AND market_rule_valid "
            "AND historical_identity_valid)"
        ),
        "invalid_without_reason": scalar(
            "SELECT COUNT(*) FROM enriched WHERE NOT hard_valid "
            "AND COALESCE(invalid_reasons, '') = ''"
        ),
        "valid_with_reason": scalar(
            "SELECT COUNT(*) FROM enriched WHERE hard_valid AND COALESCE(invalid_reasons, '') <> ''"
        ),
        "positive_float_marked_valid": scalar(
            "SELECT COUNT(*) FROM enriched WHERE float_valid "
            "AND (circulating_shares IS NULL OR circulating_shares <= 0)"
        ),
        "unblocked_action_marked_valid": scalar(
            "SELECT COUNT(*) FROM enriched WHERE corporate_action_blocking "
            "AND corporate_action_valid"
        ),
        "suspended_without_bilateral_block": scalar(
            "SELECT COUNT(*) FROM enriched WHERE trading_state_valid AND trade_status=0 "
            "AND NOT (buy_blocked_open AND sell_blocked_open)"
        ),
        "turnover_unit_mismatch": scalar(
            "SELECT COUNT(*) FROM enriched WHERE float_valid AND volume IS NOT NULL "
            "AND ABS(turnover_fraction - volume/circulating_shares) > 1e-12"
        ),
    }
    consistency_issues = sum(consistency_counts.values())

    cross_counts = {
        "join_amplification": abs(output_rows - daily_rows),
        "missing_state_not_failed_closed": scalar(
            "SELECT COUNT(*) FROM enriched WHERE trade_status IS NULL AND hard_valid"
        ),
        "missing_industry_not_failed_closed": scalar(
            "SELECT COUNT(*) FROM enriched WHERE industry IS NULL AND hard_valid"
        ),
        "missing_float_not_failed_closed": scalar(
            "SELECT COUNT(*) FROM enriched WHERE float_effective_date IS NULL AND hard_valid"
        ),
        "missing_market_not_failed_closed": scalar(
            "SELECT COUNT(*) FROM enriched WHERE index_symbol IS NULL AND hard_valid"
        ),
        "blocking_action_not_failed_closed": scalar(
            "SELECT COUNT(*) FROM enriched WHERE corporate_action_blocking AND hard_valid"
        ),
        "historical_symbol_alias_not_failed_closed": scalar(
            "SELECT COUNT(*) FROM enriched WHERE NOT historical_identity_valid AND hard_valid"
        ),
    }
    cross_issues = sum(cross_counts.values())

    checks = {
        "coverage": _audit_check(coverage_issues, {"valid_rows": coverage_counts}),
        "duplicates": _audit_check(duplicate_issues, duplicate_counts),
        "time_travel": _audit_check(temporal_issues, temporal_counts),
        "consistency": _audit_check(consistency_issues, consistency_counts),
        "cross_table": _audit_check(cross_issues, cross_counts),
    }
    return {
        "gate": "PIT_B_ALL_MARKET_DAILY_DATA",
        "gate_pass": all(item["status"] == "PASS" for item in checks.values()),
        "build_id": build_id,
        "pipeline_version": PIPELINE_VERSION,
        "pit_grade": "B_CAUSAL_RESEARCH",
        "strict_pit_archive_ready": False,
        "scope": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "benchmark": benchmark,
            "daily_only": True,
        },
        "authorization": {
            "operation": DataOperation.INGEST.value,
            "manifest_id": manifest.manifest_id,
            "manifest_sha256": manifest.sha256,
            "purpose": manifest.purpose.value,
        },
        "counts": {
            "daily_rows": daily_rows,
            "output_rows": output_rows,
            "hard_valid_rows": hard_valid_rows,
            "hard_invalid_rows": output_rows - hard_valid_rows,
            "hard_valid_ratio": hard_valid_rows / output_rows if output_rows else 0.0,
            "per_year": per_year,
        },
        "checks": checks,
        "sources": {
            role: {
                "asset_id": binding.asset.asset_id,
                "snapshot_id": binding.snapshot_id,
                "source": binding.source,
            }
            for role, binding in manifest.bindings.items()
            if role
            in {
                "daily_bars",
                "trading_state",
                "index_daily",
                "industry_membership",
                "circulating_shares",
                "corporate_actions",
            }
        },
        "input_paths": {name: str(path) for name, path in inputs.items()},
        "limitations": [
            "Frozen CNINFO history has no complete revision-vintage chain; "
            "no-event days are PIT-B only.",
            "Historical ST status outside BaoStock daily history fails closed.",
            "Known current-code history before the verified code effective date fails closed; "
            "old-code identity joins are not inferred.",
            "Industry is a mandatory PIT label only; no complex sector model is used.",
            "Minute/Tick, chip states, strategies, orders, reports, and backtests "
            "are not run here.",
        ],
    }


def _audit_check(issue_count: int, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "PASS" if issue_count == 0 else "FAIL",
        "issue_count": issue_count,
        "evidence": evidence,
    }


def _build_id(manifest_hash: str, start: date, end: date, benchmark: str) -> str:
    payload = f"{PIPELINE_VERSION}|{manifest_hash}|{start}|{end}|{benchmark}"
    return "PITB-" + hashlib.sha256(payload.encode()).hexdigest()[:20].upper()


def _reuse_completed_output(output: Path, build_id: str) -> dict[str, Any] | None:
    audit_path = output / "audit.json"
    data_path = output / "daily"
    if not audit_path.is_file() or not data_path.is_dir():
        return None
    try:
        payload = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("build_id") != build_id:
        return None
    if payload.get("gate_pass") is not True:
        return None
    return payload


def _canonical_symbol_sql(column: str) -> str:
    return f"""CASE
      WHEN UPPER(CAST({column} AS VARCHAR)) LIKE '%.SH'
        OR UPPER(CAST({column} AS VARCHAR)) LIKE '%.SZ'
        OR UPPER(CAST({column} AS VARCHAR)) LIKE '%.BJ'
        THEN UPPER(CAST({column} AS VARCHAR))
      WHEN LENGTH(CAST({column} AS VARCHAR)) = 6
        AND SUBSTR(CAST({column} AS VARCHAR), 1, 2) = '92'
        THEN CAST({column} AS VARCHAR) || '.BJ'
      WHEN LENGTH(CAST({column} AS VARCHAR)) = 6
        AND SUBSTR(CAST({column} AS VARCHAR), 1, 1) IN ('4', '8')
        THEN CAST({column} AS VARCHAR) || '.BJ'
      WHEN LENGTH(CAST({column} AS VARCHAR)) = 6
        AND SUBSTR(CAST({column} AS VARCHAR), 1, 1) IN ('5', '6', '9')
        THEN CAST({column} AS VARCHAR) || '.SH'
      WHEN LENGTH(CAST({column} AS VARCHAR)) = 6
        THEN CAST({column} AS VARCHAR) || '.SZ'
    END"""


def _historical_identity_valid_sql() -> str:
    invalid_terms = [
        f"(symbol = {_sql_literal(symbol)} AND trade_date < DATE "
        f"{_sql_literal(effective_date.isoformat())})"
        for symbol, effective_date in HISTORICAL_SYMBOL_EFFECTIVE_DATES.items()
    ]
    return "NOT (" + " OR ".join(invalid_terms) + ")"


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
