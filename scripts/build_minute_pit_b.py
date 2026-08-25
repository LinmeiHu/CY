#!/usr/bin/env python3
"""Build the causal minute-derived PIT-B products used by CYQ-GAME.

The daily product supplies volume-at-price observations to the chip engine after
the close.  The execution product contains only the first six completed 5-minute
windows after 09:30, so an order never sees the rest of its execution day.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb

DEFAULT_MINUTE_ROOT = Path(
    "/Users/linmei/Downloads/workspace/quant/data/lake/"
    "stock_1min_canonical_none_20260813/bars"
)
DEFAULT_DAILY_ROOT = Path(
    "/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily"
)
DEFAULT_OUTPUT_ROOT = Path(
    "/Users/linmei/Documents/CY/data/processed/pit_b_minute_2018_2026_v2"
)
DEFAULT_SUPPLEMENT_ROOT = Path(
    "/Users/linmei/Documents/CY/data/processed/minute_source_supplement_v2"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--minute-root", type=Path, default=DEFAULT_MINUTE_ROOT)
    parser.add_argument("--daily-root", type=Path, default=DEFAULT_DAILY_ROOT)
    parser.add_argument("--supplement-root", type=Path, default=DEFAULT_SUPPLEMENT_ROOT)
    parser.add_argument(
        "--baostock-delta-file",
        type=Path,
        help="Optional registered raw BaoStock native-5m Parquet delta.",
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--threads", type=int, default=min(10, os.cpu_count() or 1))
    parser.add_argument("--memory-limit", default="24GB")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def _source_files(root: Path, year: int) -> list[Path]:
    files = sorted(root.glob(f"{year}_*.parquet"))
    if not files:
        raise FileNotFoundError(f"no minute files for {year} under {root}")
    return files


def _sql_list(paths: list[Path]) -> str:
    values = ", ".join("'" + str(path).replace("'", "''") + "'" for path in paths)
    return f"[{values}]"


def _filters(args: argparse.Namespace) -> tuple[str, list[Any]]:
    clauses = ["m.trade_date >= ?", "m.trade_date <= ?"]
    parameters: list[Any] = [
        args.start or date(args.year, 1, 1),
        args.end or date(args.year, 12, 31),
    ]
    if args.symbols:
        normalized = [item.split(".", 1)[0] for item in args.symbols]
        clauses.append("m.symbol IN (" + ",".join("?" for _ in normalized) + ")")
        parameters.extend(normalized)
    return " AND ".join(clauses), parameters


def _create_source_views(
    connection: duckdb.DuckDBPyConnection,
    minute_files: list[Path],
    daily_file: Path,
    supplement_file: Path | None,
    baostock_delta_file: Path | None = None,
) -> None:
    columns = """symbol, exchange, trade_date, bar_end_time, open, high, low, close,
                 volume, amount, source"""
    source_sql = f"""SELECT {columns}, 1 AS source_resolution_minutes
                     FROM read_parquet({_sql_list(minute_files)}, union_by_name=TRUE)"""
    if supplement_file is not None:
        escaped = str(supplement_file).replace("'", "''")
        source_sql += f""" UNION ALL SELECT {columns}, source_resolution_minutes
                           FROM read_parquet('{escaped}')"""
    if baostock_delta_file is not None:
        escaped = str(baostock_delta_file).replace("'", "''")
        source_sql += f"""
          UNION ALL
          SELECT SUBSTR(code, 4) AS symbol,
                 UPPER(SUBSTR(code, 1, 2)) AS exchange,
                 CAST(date AS DATE) AS trade_date,
                 STRPTIME(SUBSTR(time, 1, 14), '%Y%m%d%H%M%S') AS bar_end_time,
                 TRY_CAST(open AS DOUBLE) AS open,
                 TRY_CAST(high AS DOUBLE) AS high,
                 TRY_CAST(low AS DOUBLE) AS low,
                 TRY_CAST(close AS DOUBLE) AS close,
                 TRY_CAST(volume AS DOUBLE) AS volume,
                 TRY_CAST(amount AS DOUBLE) AS amount,
                 'baostock_none_5m' AS source,
                 5 AS source_resolution_minutes
          FROM read_parquet('{escaped}')
        """
    connection.execute(
        f"""
        CREATE VIEW minute_source AS
        {source_sql};
        CREATE VIEW daily_source AS
        SELECT * FROM read_parquet('{str(daily_file).replace("'", "''")}');
        """
    )


def _selected_cte(where_sql: str) -> str:
    return f"""
    WITH raw AS NOT MATERIALIZED (
      SELECT
        m.symbol || '.' || m.exchange AS symbol,
        m.trade_date,
        m.bar_end_time,
        CAST(m.bar_end_time AS TIME) AS bar_time,
        m.open, m.high, m.low, m.close, m.volume, m.amount,
        m.open > 0 AND m.high >= GREATEST(m.open, m.close)
          AND m.low <= LEAST(m.open, m.close) AND m.low > 0 AS row_ohlc_valid,
        m.volume >= 0 AND m.amount >= 0
          AND NOT (m.volume > 0 AND m.amount <= 0) AS row_unit_valid,
        CASE WHEN m.volume > 0 AND m.amount > 0
             THEN m.amount / m.volume ELSE m.close END AS minute_price,
        m.source AS minute_source,
        m.source_resolution_minutes,
        d.low AS daily_low,
        d.high AS daily_high,
        d.close AS daily_close,
        d.volume AS daily_volume,
        d.amount AS daily_amount,
        d.circulating_shares,
        d.trade_status,
        d.is_st,
        d.up_limit_price,
        d.down_limit_price,
        d.market_rule_id,
        d.market_rule_valid,
        d.limit_pct,
        d.bar_valid,
        d.trading_state_valid,
        d.float_valid,
        d.corporate_action_valid,
        d.industry_valid,
        d.hard_valid AS daily_hard_valid,
        d.snapshot_id AS daily_snapshot_id
      FROM minute_source m
      JOIN daily_source d
        ON d.symbol = m.symbol || '.' || m.exchange
       AND d.trade_date = m.trade_date
      WHERE {where_sql}
    )
    """


def _daily_sql(where_sql: str) -> str:
    return _selected_cte(where_sql) + """
    , priced AS NOT MATERIALIZED (
      SELECT *, CASE
        WHEN daily_high <= daily_low THEN 0
        ELSE LEAST(31, GREATEST(0, CAST(FLOOR(
          (LEAST(daily_high, GREATEST(daily_low, minute_price)) - daily_low)
          / (daily_high - daily_low) * 32
        ) AS INTEGER)))
      END AS price_bin
      FROM raw
    ), bins AS (
      SELECT symbol, trade_date, price_bin,
        CASE
          WHEN ANY_VALUE(daily_high) <= ANY_VALUE(daily_low) THEN ANY_VALUE(daily_close)
          ELSE ANY_VALUE(daily_low)
               + (price_bin + 0.5) * (ANY_VALUE(daily_high) - ANY_VALUE(daily_low)) / 32.0
        END AS chip_price,
        SUM(volume) AS chip_volume
      FROM priced
      WHERE volume > 0
      GROUP BY symbol, trade_date, price_bin
    ), bin_arrays AS (
      SELECT symbol, trade_date,
        LIST(chip_price ORDER BY price_bin) AS chip_prices,
        LIST(chip_volume ORDER BY price_bin) AS chip_volumes,
        COUNT(*) AS occupied_bins
      FROM bins
      GROUP BY symbol, trade_date
    ), aggregate_base AS (
      SELECT symbol, trade_date,
        ARG_MAX(close, bar_end_time)
          FILTER (WHERE bar_time BETWEEN TIME '09:31:00' AND TIME '10:00:00')
          / NULLIF(
              ARG_MIN(open, bar_end_time)
                FILTER (WHERE bar_time BETWEEN TIME '09:31:00' AND TIME '10:00:00'),
              0
            ) - 1
          AS opening_30m_return,
        ARG_MAX(close, bar_end_time)
          FILTER (WHERE bar_time BETWEEN TIME '14:31:00' AND TIME '15:00:00')
          / NULLIF(
              ARG_MIN(open, bar_end_time)
                FILTER (WHERE bar_time BETWEEN TIME '14:31:00' AND TIME '15:00:00'),
              0
            ) - 1
          AS closing_30m_return,
        ANY_VALUE(daily_close) / NULLIF(SUM(amount) / NULLIF(SUM(volume), 0), 0) - 1
          AS close_vs_vwap,
        SUM(volume) FILTER (WHERE bar_time BETWEEN TIME '14:01:00' AND TIME '15:00:00')
          / NULLIF(SUM(volume), 0) AS last_hour_volume_share,
        LIST(close ORDER BY bar_end_time) AS ordered_closes,
        COUNT(*) AS minute_count,
        COUNT(DISTINCT bar_end_time) AS distinct_minute_count,
        SUM(volume) AS minute_volume,
        SUM(amount) AS minute_amount,
        MIN(bar_end_time) AS first_bar_end,
        MAX(bar_end_time) AS last_bar_end,
        BOOL_AND(row_ohlc_valid) AS ohlc_valid,
        BOOL_AND(row_unit_valid) AS unit_valid,
        ANY_VALUE(daily_volume) AS daily_volume,
        ANY_VALUE(daily_amount) AS daily_amount,
        ANY_VALUE(daily_hard_valid) AS daily_hard_valid,
        ANY_VALUE(minute_source) AS source,
        ANY_VALUE(source_resolution_minutes) AS source_resolution_minutes,
        ANY_VALUE(daily_snapshot_id) AS daily_snapshot_id
      FROM priced
      GROUP BY symbol, trade_date
    ), aggregates AS (
      SELECT * EXCLUDE (ordered_closes),
        SQRT(LIST_SUM(LIST_TRANSFORM(
          LIST_ZIP(
            LIST_SLICE(ordered_closes, 2, LENGTH(ordered_closes)),
            LIST_SLICE(ordered_closes, 1, LENGTH(ordered_closes) - 1)
          ),
          x -> CASE
            WHEN x[1] > 0 AND x[2] > 0 THEN POWER(LN(x[1] / x[2]), 2)
            ELSE NULL
          END
        ))) AS realized_volatility
      FROM aggregate_base
    ), features AS (
      SELECT *,
        ABS(minute_volume - daily_volume)
          <= GREATEST(1.0, ABS(daily_volume) * 0.001) AS volume_reconciled,
        ABS(minute_amount - daily_amount)
          <= GREATEST(1.0, ABS(daily_amount) * 0.001) AS amount_reconciled,
        CASE
          WHEN source_resolution_minutes = 1 THEN
            minute_count IN (240, 241) AND distinct_minute_count = minute_count
            AND CAST(first_bar_end AS TIME) IN (TIME '09:30:00', TIME '09:31:00')
            AND CAST(last_bar_end AS TIME) = TIME '15:00:00'
          WHEN source_resolution_minutes = 5 THEN
            minute_count = 48 AND distinct_minute_count = 48
            AND CAST(first_bar_end AS TIME) = TIME '09:35:00'
            AND CAST(last_bar_end AS TIME) = TIME '15:00:00'
          ELSE FALSE
        END AS session_complete
      FROM aggregates
    )
    SELECT
      f.symbol, f.trade_date,
      CAST(f.trade_date AS TIMESTAMP) + INTERVAL 15 HOUR + INTERVAL 30 MINUTE AS available_at,
      b.chip_prices, b.chip_volumes, b.occupied_bins,
      f.opening_30m_return, f.closing_30m_return, f.close_vs_vwap,
      f.last_hour_volume_share, f.realized_volatility,
      f.minute_count, f.distinct_minute_count, f.minute_volume, f.minute_amount,
      f.source_resolution_minutes,
      f.session_complete, f.ohlc_valid, f.unit_valid,
      f.volume_reconciled, f.amount_reconciled,
      f.daily_hard_valid,
      COALESCE(b.occupied_bins > 0, FALSE) AND f.session_complete AND f.ohlc_valid
        AND f.unit_valid AND f.volume_reconciled AND f.amount_reconciled
        AND f.daily_hard_valid AS hard_valid,
      CONCAT_WS('|',
        CASE WHEN NOT f.daily_hard_valid THEN 'DAILY_HARD_INVALID' END,
        CASE WHEN NOT f.session_complete THEN 'MINUTE_SESSION_INCOMPLETE' END,
        CASE WHEN NOT f.ohlc_valid THEN 'MINUTE_OHLC_INVALID' END,
        CASE WHEN NOT f.unit_valid THEN 'MINUTE_UNIT_INVALID' END,
        CASE WHEN NOT f.volume_reconciled THEN 'MINUTE_DAILY_VOLUME_MISMATCH' END,
        CASE WHEN NOT f.amount_reconciled THEN 'MINUTE_DAILY_AMOUNT_MISMATCH' END,
        CASE WHEN COALESCE(b.occupied_bins, 0) = 0 THEN 'NO_POSITIVE_VOLUME_BINS' END
      ) AS invalid_reasons,
      f.source || '+PIT_B_DAILY' AS source,
      'MINUTE-PIT-B-v1:' || f.symbol || ':' || CAST(f.trade_date AS VARCHAR) AS snapshot_id,
      f.daily_snapshot_id
    FROM features f
    LEFT JOIN bin_arrays b USING (symbol, trade_date)
    """


def _execution_sql(where_sql: str) -> str:
    return _selected_cte(where_sql) + """
    , first_30 AS (
      SELECT *, CAST(FLOOR((EXTRACT(HOUR FROM bar_time) * 60
                     + EXTRACT(MINUTE FROM bar_time) - 571) / 5) AS INTEGER) AS window_index
      FROM raw
      WHERE bar_time BETWEEN TIME '09:31:00' AND TIME '10:00:00'
    )
    SELECT
      symbol, trade_date, window_index,
      CAST(trade_date AS TIMESTAMP) + INTERVAL 9 HOUR + INTERVAL 35 MINUTE
        + window_index * INTERVAL 5 MINUTE AS available_at,
      ARG_MIN(open, bar_end_time) AS open,
      MAX(high) AS high,
      MIN(low) AS low,
      ARG_MAX(close, bar_end_time) AS close,
      SUM(volume) AS volume,
      SUM(amount) AS amount,
      ANY_VALUE(circulating_shares) AS circulating_shares,
      ANY_VALUE(trade_status) AS trade_status,
      ANY_VALUE(is_st) AS is_st,
      ANY_VALUE(up_limit_price) AS up_limit_price,
      ANY_VALUE(down_limit_price) AS down_limit_price,
      ANY_VALUE(market_rule_id) AS market_rule_id,
      ANY_VALUE(market_rule_valid) AS market_rule_valid,
      ANY_VALUE(limit_pct) AS limit_pct,
      ANY_VALUE(source_resolution_minutes) AS source_resolution_minutes,
      COUNT(*) AS minute_count,
      COUNT(DISTINCT bar_end_time) AS distinct_minute_count,
      BOOL_AND(row_ohlc_valid) AS ohlc_valid,
      BOOL_AND(row_unit_valid) AS unit_valid,
      BOOL_AND(bar_valid AND trading_state_valid AND float_valid
               AND corporate_action_valid AND market_rule_valid) AS causal_inputs_valid,
      ((ANY_VALUE(source_resolution_minutes) = 1
          AND COUNT(*) = 5 AND COUNT(DISTINCT bar_end_time) = 5)
       OR (ANY_VALUE(source_resolution_minutes) = 5
          AND COUNT(*) = 1 AND COUNT(DISTINCT bar_end_time) = 1))
        AND BOOL_AND(row_ohlc_valid) AND BOOL_AND(row_unit_valid)
        AND BOOL_AND(bar_valid AND trading_state_valid AND float_valid
                     AND corporate_action_valid AND market_rule_valid)
        AND ANY_VALUE(trade_status) IS NOT NULL AS hard_valid,
      CONCAT_WS('|',
        CASE WHEN NOT ((ANY_VALUE(source_resolution_minutes) = 1
                         AND COUNT(*) = 5 AND COUNT(DISTINCT bar_end_time) = 5)
                        OR (ANY_VALUE(source_resolution_minutes) = 5
                         AND COUNT(*) = 1 AND COUNT(DISTINCT bar_end_time) = 1))
          THEN 'EXECUTION_WINDOW_INCOMPLETE' END,
        CASE WHEN NOT BOOL_AND(row_ohlc_valid) THEN 'MINUTE_OHLC_INVALID' END,
        CASE WHEN NOT BOOL_AND(row_unit_valid) THEN 'MINUTE_UNIT_INVALID' END,
        CASE WHEN NOT BOOL_AND(bar_valid AND trading_state_valid AND float_valid
                               AND corporate_action_valid AND market_rule_valid)
          THEN 'EXECUTION_INPUT_INVALID' END,
        CASE WHEN ANY_VALUE(trade_status) IS NULL THEN 'UNKNOWN_TRADE_STATUS' END
      ) AS invalid_reasons,
      ANY_VALUE(minute_source) || '+PIT_B_DAILY' AS source,
      'MINUTE-EXEC-v1:' || symbol || ':' || CAST(trade_date AS VARCHAR)
        || ':' || CAST(window_index AS VARCHAR) AS snapshot_id,
      ANY_VALUE(daily_snapshot_id) AS daily_snapshot_id
    FROM first_30
    GROUP BY symbol, trade_date, window_index
    """


def _write_product(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
    parameters: list[Any],
    destination: Path,
    overwrite: bool,
    compression: str = "ZSTD",
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite {destination}")
    temporary = destination.with_suffix(".building.parquet")
    if temporary.exists():
        temporary.unlink()
    escaped_temporary = str(temporary).replace("'", "''")
    connection.execute(
        f"COPY ({sql}) TO '{escaped_temporary}' "
        f"(FORMAT PARQUET, COMPRESSION {compression})",
        parameters,
    )
    os.replace(temporary, destination)


def _audit(connection: duckdb.DuckDBPyConnection, daily: Path, execution: Path) -> dict[str, Any]:
    daily_rows = connection.execute(
        """
        SELECT COUNT(*), COUNT(*) FILTER (WHERE hard_valid),
               COUNT(*) - COUNT(DISTINCT (symbol, trade_date)),
               COUNT(*) FILTER (WHERE available_at < CAST(trade_date AS TIMESTAMP)),
               COUNT(*) FILTER (WHERE occupied_bins > 32),
               COUNT(*) FILTER (WHERE ABS(list_sum(chip_volumes) - minute_volume)
                                      > GREATEST(1.0, minute_volume * 0.001))
        FROM read_parquet(?)
        """,
        [str(daily)],
    ).fetchone()
    execution_rows = connection.execute(
        """
        SELECT COUNT(*), COUNT(*) FILTER (WHERE hard_valid),
               COUNT(*) - COUNT(DISTINCT (symbol, trade_date, window_index)),
               COUNT(*) FILTER (WHERE window_index NOT BETWEEN 0 AND 5),
               COUNT(*) FILTER (WHERE available_at > CAST(trade_date AS TIMESTAMP)
                                                     + INTERVAL 10 HOUR),
               COUNT(*) FILTER (
                 WHERE NOT ((source_resolution_minutes = 1 AND minute_count = 5)
                         OR (source_resolution_minutes = 5 AND minute_count = 1)))
        FROM read_parquet(?)
        """,
        [str(execution)],
    ).fetchone()
    assert daily_rows is not None and execution_rows is not None
    checks = {
        "daily_unique": daily_rows[2] == 0,
        "daily_no_time_travel": daily_rows[3] == 0,
        "daily_max_32_bins": daily_rows[4] == 0,
        "daily_chip_mass_matches_minute_volume": daily_rows[5] == 0,
        "execution_unique": execution_rows[2] == 0,
        "execution_windows_in_range": execution_rows[3] == 0,
        "execution_available_by_1000": execution_rows[4] == 0,
        "execution_windows_complete": execution_rows[5] == 0,
    }
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "daily": {"rows": daily_rows[0], "hard_valid_rows": daily_rows[1]},
        "execution_5m": {"rows": execution_rows[0], "hard_valid_rows": execution_rows[1]},
        "checks": checks,
        "pass": all(checks.values()),
    }


def main() -> int:
    args = _parse_args()
    if args.start and args.start.year != args.year:
        raise ValueError("--start must belong to --year")
    if args.end and args.end.year != args.year:
        raise ValueError("--end must belong to --year")
    minute_files = _source_files(args.minute_root, args.year)
    supplement_file = (
        args.supplement_root / f"partition_year={args.year}" / "data_0.parquet"
    )
    if not supplement_file.exists():
        supplement_file = None
    daily_file = args.daily_root / f"partition_year={args.year}" / "data_0.parquet"
    if not daily_file.exists():
        raise FileNotFoundError(daily_file)
    if args.baostock_delta_file is not None and not args.baostock_delta_file.is_file():
        raise FileNotFoundError(args.baostock_delta_file)
    where_sql, parameters = _filters(args)
    temporary_root = (
        args.output_root / ".duckdb_tmp" / f"year={args.year}-pid={os.getpid()}"
    )
    temporary_root.mkdir(parents=True, exist_ok=False)
    connection = duckdb.connect(database=":memory:")
    try:
        escaped_temporary_root = str(temporary_root).replace("'", "''")
        connection.execute(f"SET temp_directory='{escaped_temporary_root}'")
        connection.execute(f"SET threads={args.threads}")
        connection.execute(f"SET memory_limit='{args.memory_limit}'")
        connection.execute("SET preserve_insertion_order=false")
        _create_source_views(
            connection,
            minute_files,
            daily_file,
            supplement_file,
            args.baostock_delta_file,
        )
        partition = f"partition_year={args.year}"
        daily_output = args.output_root / "daily" / partition / "data_0.parquet"
        execution_output = (
            args.output_root / "execution_5m" / partition / "data_0.parquet"
        )
        _write_product(
            connection,
            _daily_sql(where_sql),
            parameters,
            daily_output,
            args.overwrite,
        )
        _write_product(
            connection,
            _execution_sql(where_sql),
            parameters,
            execution_output,
            args.overwrite,
        )
        audit = _audit(connection, daily_output, execution_output)
        audit_path = args.output_root / "audits" / f"year={args.year}.json"
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(
            json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({"audit_path": str(audit_path), **audit}, ensure_ascii=False))
        return 0 if audit["pass"] else 1
    finally:
        connection.close()
        shutil.rmtree(temporary_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
