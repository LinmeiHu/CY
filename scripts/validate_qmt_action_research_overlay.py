#!/usr/bin/env python3
"""Gate the QMT corporate-action corroboration as a research-only artifact.

This deliberately does not promote rows to strict PIT validity: the QMT
capital snapshot was collected after the historical sample dates.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

REQUIRED = {
    "symbol", "trade_date", "decision_at", "available_at", "snapshot_id",
    "hard_valid", "qmt_action_factor_match", "qmt_action_execution_confirmed",
    "qmt_action_research_resolvable", "qmt_action_available_at",
    "qmt_action_snapshot_id", "research_corporate_action_resolved",
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    con = duckdb.connect()
    try:
        path = str(args.input.resolve()).replace("'", "''")
        cols = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{path}')").fetchall()}
        missing = sorted(REQUIRED - cols)
        q = f"SELECT * FROM read_parquet('{path}')"
        rows, symbols, dupes, resolved, implication_violations, future_snapshot = con.execute(
            f"""
            SELECT count(*), count(DISTINCT symbol),
              count(*) - count(DISTINCT (symbol, trade_date)),
              count(*) FILTER (WHERE research_corporate_action_resolved),
              count(*) FILTER (WHERE research_corporate_action_resolved AND
                NOT (qmt_action_factor_match AND qmt_action_execution_confirmed AND
                     qmt_action_research_resolvable)),
              count(*) FILTER (WHERE research_corporate_action_resolved AND
                qmt_action_available_at > trade_date)
            FROM ({q})
            """
        ).fetchone()
        result = {
            "artifact": str(args.input.resolve()),
            "research_gate_pass": not missing and dupes == 0 and implication_violations == 0,
            "strict_pit_gate_pass": False,
            "strict_pit_reason": "QMT corroboration snapshot is after historical decision dates; research-only evidence.",
            "rows": rows, "symbols": symbols, "duplicate_keys": dupes,
            "research_resolved_rows": resolved,
            "implication_violations": implication_violations,
            "resolved_rows_with_post_decision_snapshot": future_snapshot,
            "missing_columns": missing,
        }
    finally:
        con.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["research_gate_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
