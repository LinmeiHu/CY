#!/usr/bin/env python3
"""Classify strict chip-feature coverage gaps without running a backtest."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=date.fromisoformat, default=date(2020, 1, 2))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 8, 12))
    parser.add_argument(
        "--features",
        default=str(ROOT / "data/processed/chip_state_features_by_year_2018_2026_v2/**/*.parquet"),
    )
    parser.add_argument(
        "--supplement",
        default=str(
            ROOT / "data/processed/minute_source_supplement_v2/partition_year=*/data_0.parquet"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data/audit/chip_feature_coverage_gap_report.json",
    )
    args = parser.parse_args()
    con = duckdb.connect()
    params = [args.start, args.end]
    feature = args.features.replace("'", "''")
    supplement = args.supplement.replace("'", "''")
    summary = con.execute(
        f"""
        WITH f AS (
          SELECT * FROM read_parquet('{feature}', union_by_name=true)
          WHERE trade_date BETWEEN ? AND ?
        ), by_symbol AS (
          SELECT symbol, count(*) AS rows,
            count(*) FILTER (WHERE strict_sample) AS strict_rows,
            count(*) FILTER (
              WHERE minute_hard_valid OR COALESCE(minute_requirement_waived, FALSE)
            ) AS minute_valid_rows,
            count(*) FILTER (WHERE daily_hard_valid) AS daily_valid_rows,
            count(*) FILTER (WHERE invalid_reason LIKE 'WARMUP%') AS warmup_rows,
            count(*) FILTER (WHERE invalid_reason LIKE '%missing_historical_float%') AS float_rows,
            count(*) FILTER (WHERE invalid_reason LIKE '%trading_state%') AS status_rows,
            count(*) FILTER (WHERE invalid_reason LIKE '%corporate_action%') AS action_rows
          FROM f GROUP BY symbol
        ), categories AS (
          SELECT CASE
            WHEN strict_rows = rows THEN 'complete'
            WHEN strict_rows = 0 AND minute_valid_rows = 0 THEN 'no_minute_valid'
            WHEN strict_rows = 0 THEN 'no_strict_daily_or_warmup'
            ELSE 'partial_strict'
          END AS category, count(*) AS symbols, sum(rows) AS rows,
            sum(strict_rows) AS strict_rows, sum(warmup_rows) AS warmup_rows,
            sum(float_rows) AS float_rows, sum(status_rows) AS status_rows,
            sum(action_rows) AS action_rows
          FROM by_symbol GROUP BY 1
        ), supplement_days AS (
          SELECT count(*) AS rows, count(DISTINCT symbol) AS symbols
          FROM read_parquet('{supplement}', union_by_name=true)
          WHERE trade_date BETWEEN ? AND ?
        )
        SELECT json_object(
          'categories', (SELECT json_group_array(to_json(c)) FROM categories c),
          'supplement_rows', (SELECT rows FROM supplement_days),
          'supplement_symbols', (SELECT symbols FROM supplement_days),
          'feature_rows', (SELECT sum(rows) FROM by_symbol),
          'feature_symbols', (SELECT count(*) FROM by_symbol),
          'strict_rows', (SELECT sum(strict_rows) FROM by_symbol),
          'strict_symbols', (SELECT count(*) FROM by_symbol WHERE strict_rows = rows)
        )
        """,
        params + params,
    ).fetchone()[0]
    payload = json.loads(summary)
    payload.update(
        {
            "generated_at": datetime.now(UTC).isoformat(),
            "start": args.start.isoformat(),
            "end": args.end.isoformat(),
            "strict_definition": (
                "daily_hard_valid AND (minute_hard_valid OR minute_requirement_waived) "
                "AND state_chain_valid AND warmup"
            ),
            "backtest_run": False,
        }
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
