#!/usr/bin/env python3
"""Materialize explicit lower-fidelity fills for canonical symbol-day gaps.

The canonical QMT/archive lake remains immutable and authoritative.  A TDX day
is admitted only when an active daily PIT-B row exists and the canonical lake
has no row for that symbol-day. TDX 1-minute bars are preferred; BaoStock raw
5-minute bars are used only when TDX has no complete day. Resolution is kept
explicit and no 5-minute bar is expanded into fabricated 1-minute bars.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb

DEFAULT_CANONICAL_ROOT = Path(
    "/Users/linmei/Downloads/workspace/quant/data/lake/"
    "stock_1min_canonical_none_20260813/bars"
)
DEFAULT_TDX_ROOT = Path(
    "/Users/linmei/Downloads/workspace/quant/data/lake/stock_1min_tdx_none"
)
DEFAULT_BAOSTOCK_5M_ROOT = Path(
    "/Users/linmei/Downloads/workspace/quant/data/lake/stock_5min_baostock_none"
)
DEFAULT_DAILY_ROOT = Path(
    "/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily"
)
DEFAULT_OUTPUT_ROOT = Path(
    "/Users/linmei/Documents/CY/data/processed/minute_source_supplement_v2"
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--canonical-root", type=Path, default=DEFAULT_CANONICAL_ROOT)
    parser.add_argument("--tdx-root", type=Path, default=DEFAULT_TDX_ROOT)
    parser.add_argument(
        "--baostock-5m-root", type=Path, default=DEFAULT_BAOSTOCK_5M_ROOT
    )
    parser.add_argument("--daily-root", type=Path, default=DEFAULT_DAILY_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory-limit", default="24GB")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def _sql_list(paths: list[Path]) -> str:
    return "[" + ", ".join("'" + str(p).replace("'", "''") + "'" for p in paths) + "]"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".building")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    args = _args()
    canonical_files = sorted(args.canonical_root.glob(f"{args.year}_*.parquet"))
    if not canonical_files:
        raise FileNotFoundError(f"no canonical files for {args.year}")
    daily_file = args.daily_root / f"partition_year={args.year}" / "data_0.parquet"
    if not daily_file.exists():
        raise FileNotFoundError(daily_file)

    output = args.output_root / f"partition_year={args.year}" / "data_0.parquet"
    gap_output = args.output_root / "audits" / f"year={args.year}_remaining_gaps.parquet"
    audit_output = args.output_root / "audits" / f"year={args.year}.json"
    for path in (output, gap_output, audit_output):
        if path.exists() and not args.overwrite:
            raise FileExistsError(f"refusing to overwrite {path}")
    output.parent.mkdir(parents=True, exist_ok=True)
    gap_output.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(database=":memory:")
    con.execute(f"SET threads={args.threads}")
    con.execute(f"SET memory_limit='{args.memory_limit}'")
    con.execute("SET preserve_insertion_order=false")
    con.execute(
        f"""
        CREATE VIEW canonical AS
        SELECT * FROM read_parquet({_sql_list(canonical_files)}, union_by_name=TRUE);
        CREATE VIEW daily AS SELECT * FROM read_parquet('{str(daily_file).replace("'", "''")}');
        CREATE TEMP TABLE expected AS
        SELECT symbol, trade_date, hard_valid AS daily_hard_valid, volume AS daily_volume,
               amount AS daily_amount
        FROM daily
        WHERE trade_status = 1 AND volume > 0;
        CREATE TEMP TABLE canonical_days AS
        SELECT symbol || '.' || exchange AS symbol, trade_date
        FROM canonical GROUP BY 1, 2;
        CREATE TEMP TABLE gaps_before AS
        SELECT e.* FROM expected e ANTI JOIN canonical_days c USING (symbol, trade_date);
        """
    )
    symbols = [row[0].split(".", 1)[0] for row in con.execute(
        "SELECT DISTINCT symbol FROM gaps_before ORDER BY symbol"
    ).fetchall()]
    tdx_files = [args.tdx_root / f"{symbol}.parquet" for symbol in symbols]
    tdx_files = [path for path in tdx_files if path.exists()]
    baostock_files = [args.baostock_5m_root / f"{symbol}.parquet" for symbol in symbols]
    baostock_files = [path for path in baostock_files if path.exists()]

    output_tmp = output.with_suffix(".building.parquet")
    gap_tmp = gap_output.with_suffix(".building.parquet")
    for path in (output_tmp, gap_tmp):
        if path.exists():
            path.unlink()
    con.execute(
        """
        CREATE TEMP TABLE admitted (
          qmt_code VARCHAR, symbol VARCHAR, exchange VARCHAR, period VARCHAR, adjust VARCHAR,
          trade_date DATE, bar_end_time TIMESTAMP_NS, open DOUBLE, high DOUBLE, low DOUBLE,
          close DOUBLE, volume DOUBLE, amount DOUBLE, source VARCHAR,
          source_resolution_minutes INTEGER
        );
        CREATE TEMP TABLE tdx_valid_days (
          symbol VARCHAR, exchange VARCHAR, trade_date DATE
        )
        """
    )
    if tdx_files:
        con.execute(
            f"""
            CREATE VIEW tdx AS
            SELECT * FROM read_parquet({_sql_list(tdx_files)}, union_by_name=TRUE);
            CREATE TEMP TABLE tdx_rows AS
              SELECT
                CAST(t.tdx_code AS VARCHAR) AS qmt_code,
                CAST(t.symbol AS VARCHAR) AS symbol,
                CAST(t.exchange AS VARCHAR) AS exchange,
                '1m' AS period,
                'none' AS adjust,
                CAST(t.trade_date AS DATE) AS trade_date,
                CAST(t.bar_end_time AS TIMESTAMP_NS) AS bar_end_time,
                CAST(t.open AS DOUBLE) AS open,
                CAST(t.high AS DOUBLE) AS high,
                CAST(t.low AS DOUBLE) AS low,
                CAST(t.close AS DOUBLE) AS close,
                CAST(t.volume AS DOUBLE) AS volume,
                CAST(t.amount AS DOUBLE) AS amount,
                'tdx_pytdx_public_gap_fill' AS source,
                1 AS source_resolution_minutes
              FROM tdx t
              JOIN gaps_before g
                ON g.symbol = t.symbol || '.' || t.exchange
               AND g.trade_date = CAST(t.trade_date AS DATE)
              WHERE t.adjust = 'none'
                AND t.open > 0 AND t.high >= GREATEST(t.open, t.close)
                AND t.low > 0 AND t.low <= LEAST(t.open, t.close)
                AND t.volume >= 0 AND t.amount >= 0
                AND CAST(t.bar_end_time AS DATE) = CAST(t.trade_date AS DATE)
            ;
            INSERT INTO tdx_valid_days
              SELECT symbol, exchange, trade_date
              FROM tdx_rows
              GROUP BY 1, 2, 3
              HAVING COUNT(*) = 240 AND COUNT(DISTINCT bar_end_time) = 240
                 AND MIN(CAST(bar_end_time AS TIME)) = TIME '09:31:00'
                 AND MAX(CAST(bar_end_time AS TIME)) = TIME '15:00:00';
            INSERT INTO admitted
              SELECT r.* FROM tdx_rows r JOIN tdx_valid_days d USING(symbol, exchange, trade_date);
            """
        )
    if baostock_files:
        con.execute(
            f"""
            CREATE VIEW baostock AS
            SELECT * FROM read_parquet({_sql_list(baostock_files)}, union_by_name=TRUE);
            CREATE TEMP TABLE baostock_rows AS
              SELECT
                CAST(NULL AS VARCHAR) AS qmt_code,
                CAST(b.symbol AS VARCHAR) AS symbol,
                CAST(b.exchange AS VARCHAR) AS exchange,
                '5m' AS period,
                'none' AS adjust,
                CAST(b.trade_date AS DATE) AS trade_date,
                CAST(b.bar_end_time AS TIMESTAMP_NS) AS bar_end_time,
                CAST(b.open AS DOUBLE) AS open,
                CAST(b.high AS DOUBLE) AS high,
                CAST(b.low AS DOUBLE) AS low,
                CAST(b.close AS DOUBLE) AS close,
                CAST(b.volume AS DOUBLE) AS volume,
                CAST(b.amount AS DOUBLE) AS amount,
                'baostock_5min_gap_fill' AS source,
                5 AS source_resolution_minutes
              FROM baostock b
              JOIN gaps_before g
                ON g.symbol = b.symbol || '.' || b.exchange
               AND g.trade_date = CAST(b.trade_date AS DATE)
              ANTI JOIN tdx_valid_days t
                ON t.symbol = b.symbol AND t.exchange = b.exchange
               AND t.trade_date = CAST(b.trade_date AS DATE)
              WHERE b.adjust = 'none'
                AND b.open > 0 AND b.high >= GREATEST(b.open, b.close)
                AND b.low > 0 AND b.low <= LEAST(b.open, b.close)
                AND b.volume >= 0 AND b.amount >= 0
                AND CAST(b.bar_end_time AS DATE) = CAST(b.trade_date AS DATE);
            CREATE TEMP TABLE baostock_valid_days AS
              SELECT symbol, exchange, trade_date
              FROM baostock_rows
              GROUP BY 1, 2, 3
              HAVING COUNT(*) = 48 AND COUNT(DISTINCT bar_end_time) = 48
                 AND MIN(CAST(bar_end_time AS TIME)) = TIME '09:35:00'
                 AND MAX(CAST(bar_end_time AS TIME)) = TIME '15:00:00';
            INSERT INTO admitted
              SELECT r.* FROM baostock_rows r
              JOIN baostock_valid_days d USING(symbol, exchange, trade_date);
            """
        )
    con.execute(
        f"""
        COPY (SELECT * FROM admitted ORDER BY trade_date, symbol, bar_end_time)
        TO '{str(output_tmp).replace("'", "''")}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    os.replace(output_tmp, output)

    con.execute(
        f"""
        CREATE VIEW supplement AS SELECT * FROM read_parquet('{str(output).replace("'", "''")}');
        CREATE TEMP TABLE supplement_days AS
        SELECT symbol || '.' || exchange AS symbol, trade_date, COUNT(*) AS bar_count,
               ANY_VALUE(source_resolution_minutes) AS source_resolution_minutes,
               MIN(CAST(bar_end_time AS TIME)) AS first_time,
               MAX(CAST(bar_end_time AS TIME)) AS last_time
        FROM supplement GROUP BY 1, 2;
        COPY (
          SELECT g.symbol, g.trade_date, g.daily_hard_valid,
                 CASE WHEN s.symbol IS NULL THEN 'NO_VALID_INTRADAY_SYMBOL_DAY'
                      WHEN s.source_resolution_minutes = 1 AND s.bar_count <> 240
                        THEN 'TDX_SESSION_INCOMPLETE'
                      WHEN s.source_resolution_minutes = 5 AND s.bar_count <> 48
                        THEN 'BAOSTOCK_SESSION_INCOMPLETE'
                      ELSE 'UNKNOWN' END AS reason
          FROM gaps_before g
          LEFT JOIN supplement_days s USING (symbol, trade_date)
          WHERE s.symbol IS NULL
          ORDER BY g.trade_date, g.symbol
        ) TO '{str(gap_tmp).replace("'", "''")}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    os.replace(gap_tmp, gap_output)

    counts = con.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM expected),
          (SELECT COUNT(*) FROM gaps_before),
          (SELECT COUNT(*) FROM supplement),
          (SELECT COUNT(*) FROM supplement_days),
          (SELECT COUNT(*) FROM read_parquet(?)),
          (SELECT COUNT(*) FROM read_parquet(?) WHERE daily_hard_valid)
        """,
        [str(gap_output), str(gap_output)],
    ).fetchone()
    duplicate_rows = con.execute(
        """SELECT COUNT(*) - COUNT(DISTINCT (symbol, trade_date, bar_end_time))
           FROM supplement"""
    ).fetchone()[0]
    assert counts is not None
    checks = {
        "supplement_unique": duplicate_rows == 0,
        "supplement_only_fills_canonical_gaps": con.execute(
            """SELECT COUNT(*) = 0 FROM supplement s JOIN canonical c
               ON s.symbol=c.symbol AND s.exchange=c.exchange
              AND s.trade_date=c.trade_date AND s.bar_end_time=c.bar_end_time"""
        ).fetchone()[0],
        "remaining_hard_valid_gaps_zero": counts[5] == 0,
    }
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "year": args.year,
        "source_cutoff": date(args.year, 12, 31).isoformat(),
        "canonical_files": [str(path) for path in canonical_files],
        "tdx_files_considered": len(tdx_files),
        "baostock_5m_files_considered": len(baostock_files),
        "expected_active_symbol_days": counts[0],
        "canonical_gap_symbol_days_before": counts[1],
        "supplement_rows": counts[2],
        "supplement_symbol_days": counts[3],
        "remaining_gap_symbol_days": counts[4],
        "remaining_hard_valid_gap_symbol_days": counts[5],
        "remaining_gap_path": str(gap_output),
        "supplement_path": str(output),
        "checks": checks,
        "pass": all(checks.values()),
    }
    _write_json(audit_output, payload)
    print(json.dumps({"audit_path": str(audit_output), **payload}, ensure_ascii=False))
    return 0 if payload["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
