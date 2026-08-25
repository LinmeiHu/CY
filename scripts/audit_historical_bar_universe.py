#!/usr/bin/env python3
"""Audit historical bar coverage as a non-PIT candidate universe.

Bar presence is useful for coverage diagnostics, but it is not a historical
security-universe source: this report deliberately fails the PIT gate because
the bars do not carry date-effective listing status, available_at, or a
date-vintage snapshot id.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bars", nargs="+", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", required=True)
    ns = parser.parse_args()
    con = duckdb.connect()
    paths = [str(Path(p).resolve()) for p in ns.bars]
    relation = "read_parquet([" + ",".join("'" + p.replace("'", "''") + "'" for p in paths) + "])"
    rows = con.execute(
        f"""
        SELECT trade_date, COUNT(DISTINCT qmt_code) AS symbols,
               COUNT(*) AS bars, COUNT(DISTINCT source) AS sources
        FROM {relation}
        WHERE trade_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
        GROUP BY trade_date ORDER BY trade_date
        """,
        [ns.start, ns.end],
    ).fetchall()
    annual = {}
    for date, symbols, bars, sources in rows:
        year = str(date.year)
        item = annual.setdefault(year, {"trading_days": 0, "min_symbols": None, "max_symbols": 0, "bars": 0, "sources": set()})
        item["trading_days"] += 1
        item["min_symbols"] = symbols if item["min_symbols"] is None else min(item["min_symbols"], symbols)
        item["max_symbols"] = max(item["max_symbols"], symbols)
        item["bars"] += bars
        item["sources"].add(sources)
    for item in annual.values():
        item["sources"] = sorted(item["sources"])
    report = {
        "scope": {"start": ns.start, "end": ns.end},
        "annual": annual,
        "research_gate": False,
        "gate_reasons": [
            "bar presence is not a date-effective historical security-universe fact",
            "bars lack record-level available_at and snapshot_id for listing/status knowledge",
            "candidate coverage may contain survivorship and ingestion omissions",
        ],
        "inputs": paths,
    }
    out = Path(ns.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
