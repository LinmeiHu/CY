#!/usr/bin/env python3
"""Read-only DuckDB audit for historical industry and capital PIT inputs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--industry", required=True)
    p.add_argument("--capital", required=True)
    p.add_argument("--start", default="2010-01-01")
    p.add_argument("--end", default="2017-12-31")
    p.add_argument("--output", required=True)
    ns = p.parse_args()
    c = duckdb.connect()
    ind = c.execute("""
        select count(*) as rows,
               count(distinct symbol) as symbols,
               count(distinct notice_date) as notice_dates,
               sum(case when notice_date is null then 1 else 0 end) as null_notice,
               sum(case when report_date is null then 1 else 0 end) as null_report,
               sum(case when notice_date > report_date then 1 else 0 end) as notice_after_report
        from read_parquet(?)
        where report_date between ? and ? or notice_date between ? and ?
    """, [ns.industry, ns.start, ns.end, ns.start, ns.end]).fetchone()
    cap = c.execute("""
        select count(*) as rows,
               count(distinct symbol) as symbols,
               sum(case when m_timetag is null or m_timetag <= 0 then 1 else 0 end) as bad_effective,
               sum(case when m_anntime is null or m_anntime <= 0 then 1 else 0 end) as bad_announcement,
               sum(case when m_anntime > m_timetag then 1 else 0 end) as announcement_after_effective,
               sum(case when circulating_capital is null or circulating_capital <= 0 then 1 else 0 end) as bad_circulating,
               min(m_timetag) as min_effective,
               max(m_timetag) as max_effective
        from read_parquet(?)
        where try_strptime(cast(m_timetag as varchar), '%Y%m%d') between ? and ?
    """, [ns.capital, ns.start, ns.end]).fetchone()
    report = {
        "asset_scope": {"start": ns.start, "end": ns.end},
        "industry_events": dict(zip(["rows", "symbols", "notice_dates", "null_notice", "null_report", "notice_after_report"], ind)),
        "qmt_capital": dict(zip(["rows", "symbols", "bad_effective", "bad_announcement", "announcement_after_effective", "bad_circulating", "min_effective", "max_effective"], cap)),
        "research_gate": False,
        "gate_reasons": [
            "industry and capital require row-level causal joins to the exact decision calendar",
            "capital source has no revision-history lineage for latest-causal selection",
            "research activation also requires QD-007 historical universe and input snapshot authorization",
        ],
    }
    out = Path(ns.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
