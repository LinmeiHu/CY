#!/usr/bin/env python3
"""Diagnostic cross-table PIT join coverage; never activates research inputs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--bars", nargs="+", required=True)
    p.add_argument("--capital", required=True)
    p.add_argument("--industry", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--output", required=True)
    n = p.parse_args()
    c = duckdb.connect()
    paths = [str(Path(x).resolve()) for x in n.bars]
    rel = "read_parquet([" + ",".join("'" + x.replace("'", "''") + "'" for x in paths) + "])"
    q = f"""
    WITH bars AS (
      SELECT trade_date, symbol, max(close) AS close
      FROM {rel}
      WHERE trade_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
      GROUP BY trade_date, symbol
    ), cap AS (
      SELECT symbol, try_strptime(cast(m_timetag as varchar), '%Y%m%d') AS effective_date,
             try_strptime(cast(m_anntime as varchar), '%Y%m%d') AS available_date,
             circulating_capital
      FROM read_parquet(?)
    ), cap_latest AS (
      SELECT b.trade_date, b.symbol,
             arg_max(c.circulating_capital, c.effective_date) AS circulating_capital
      FROM bars b LEFT JOIN cap c ON c.symbol=b.symbol
        AND c.effective_date <= b.trade_date AND c.available_date <= b.trade_date
      GROUP BY b.trade_date, b.symbol
    ), ind AS (
      SELECT symbol, try_cast(report_date AS DATE) AS report_date,
             try_cast(notice_date AS DATE) AS available_date, industry
      FROM read_parquet(?)
    ), ind_latest AS (
      SELECT b.trade_date, b.symbol,
             arg_max(i.industry, i.report_date) AS industry
      FROM bars b LEFT JOIN ind i ON i.symbol=b.symbol
        AND i.available_date <= b.trade_date
      GROUP BY b.trade_date, b.symbol
    )
    SELECT year(trade_date) AS year, count(*) AS symbol_days,
      count(*) FILTER (WHERE c.circulating_capital > 0) AS capital_ok,
      count(*) FILTER (WHERE i.industry IS NOT NULL AND i.industry <> '') AS industry_ok,
      count(*) FILTER (WHERE c.circulating_capital > 0 AND i.industry IS NOT NULL AND i.industry <> '') AS both_ok
    FROM cap_latest c JOIN ind_latest i USING (trade_date, symbol)
    GROUP BY year ORDER BY year
    """
    rows = c.execute(q, [n.start, n.end, n.capital, n.industry]).fetchall()
    annual = [dict(zip(["year", "symbol_days", "capital_ok", "industry_ok", "both_ok"], r)) for r in rows]
    report = {
        "scope": {"start": n.start, "end": n.end}, "annual": annual,
        "research_gate": False,
        "gate_reasons": [
            "diagnostic joins do not prove date-effective historical universe completeness",
            "bar records lack available_at and snapshot_id",
            "capital and industry sources lack authorized revision-vintage lineage",
            "QD-007 historical security-universe activation is still unavailable",
        ],
        "inputs": [*paths, str(Path(n.capital).resolve()), str(Path(n.industry).resolve())],
    }
    out = Path(n.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
