#!/usr/bin/env python3
"""Inventory repairable non-strict rows for symbols with at least one strict row."""
import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ROOT / "data/processed/chip_state_features_2018_2026_v1/bucket=*/data.parquet"
OUT = ROOT / "data/audit/5205_gap_repair_inventory.json"

def main() -> int:
    con = duckdb.connect()
    q = f"""
    WITH f AS (SELECT * FROM read_parquet('{FEATURES}')),
    s AS (SELECT DISTINCT symbol FROM f WHERE strict_sample),
    x AS (SELECT f.* FROM f JOIN s USING(symbol) WHERE NOT strict_sample)
    SELECT invalid_reason, count(*) AS rows, count(DISTINCT symbol) AS symbols,
           min(trade_date) AS first_date, max(trade_date) AS last_date
    FROM x GROUP BY invalid_reason ORDER BY rows DESC
    """
    rows = [dict(zip(["invalid_reason","rows","symbols","first_date","last_date"], r))
            for r in con.execute(q).fetchall()]
    summary = con.execute(f"""
      WITH f AS (SELECT * FROM read_parquet('{FEATURES}')),
      s AS (SELECT DISTINCT symbol FROM f WHERE strict_sample),
      x AS (SELECT f.* FROM f JOIN s USING(symbol) WHERE NOT strict_sample)
      SELECT count(*) AS nonstrict_rows, count(DISTINCT symbol) AS symbols,
             count(*) FILTER (WHERE invalid_reason='WARMUP_OR_STRICT_INPUT_INVALID') AS warmup_rows
      FROM x
    """).fetchone()
    result = {
        "scope": "symbols_with_at_least_one_strict_row",
        "symbol_count": 5205,
        "summary": {"nonstrict_rows": summary[0], "symbols": summary[1], "warmup_rows": summary[2]},
        "reason_breakdown": rows,
        "repair_policy": {
            "warmup": "retain as warmup; do not fabricate missing history",
            "status_st": "bounded source cross-check, then rebuild only affected slices",
            "daily_bar": "source-level duplicate/zero/OHLC audit and targeted replacement only",
            "corporate_action": "use only PIT action records; unresolved rows remain blocked",
            "alias_float_industry": "repair only with registered PIT evidence"
        },
        "backtest_run": False
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
