#!/usr/bin/env python3
"""Apply a verified daily-status overlay to derived minute-day records.

The immutable QMT minute lake is not changed.  Only rows present in the
BaoStock/QMT cross-check are updated; minute completeness and reconciliation
flags remain authoritative.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--minute", required=True)
    p.add_argument("--crosscheck", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    out = args.output / "data.parquet"
    con = duckdb.connect()
    minute = args.minute.replace("'", "''")
    cross = args.crosscheck.replace("'", "''")
    out_s = str(out).replace("'", "''")
    con.execute(
        f"""
        COPY (
          SELECT m.* EXCLUDE (daily_hard_valid, hard_valid, invalid_reasons),
            CASE WHEN c.symbol IS NOT NULL THEN TRUE ELSE m.daily_hard_valid END
              AS daily_hard_valid,
            CASE WHEN c.symbol IS NOT NULL THEN
              m.session_complete AND m.ohlc_valid AND m.unit_valid
              AND m.volume_reconciled AND m.amount_reconciled
              ELSE m.hard_valid END AS hard_valid,
            CASE WHEN c.symbol IS NOT NULL THEN
              regexp_replace(
                regexp_replace(coalesce(m.invalid_reasons, ''),
                  '(^|\\|)DAILY_HARD_INVALID(\\||$)', '\\1', 'g'),
                '^\\||\\|$', '', 'g')
              ELSE m.invalid_reasons END AS invalid_reasons
          FROM read_parquet('{minute}') m
          LEFT JOIN read_csv_auto('{cross}', header=true) c
            ON c.symbol = m.symbol AND CAST(c.date AS DATE) = m.trade_date
        ) TO '{out_s}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
