"""Build a research-only industry fallback overlay.

The canonical PIT-B data is never modified.  The overlay is intentionally
research-only: it may use the latest visible industry when no earlier industry
record exists, and records that fact explicitly.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--daily", required=True)
    p.add_argument("--industry", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--recent-days", type=int, default=180)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    daily = a.daily.replace("'", "''")
    industry = a.industry.replace("'", "''")
    target = str((a.output / "data.parquet").resolve()).replace("'", "''")
    con = duckdb.connect()
    try:
        con.execute("PRAGMA threads=10")
        con.execute(f"""
          COPY (
            WITH d AS (
              SELECT * FROM read_parquet('{daily}', union_by_name=true)
              WHERE trade_date BETWEEN DATE '{a.start}' AND DATE '{a.end}'
            ),
            latest AS (
              SELECT symbol, max(trade_date) AS latest_trade_date
              FROM read_parquet('{daily}', union_by_name=true)
              WHERE trade_date >= DATE '{a.end}' - INTERVAL '{a.recent_days}' DAY
                AND volume > 0
              GROUP BY symbol
            ),
            i AS (
              SELECT symbol, trade_date, industry, source_notice_date,
                     source_report_date, source
              FROM read_parquet('{industry}', union_by_name=true)
              WHERE industry IS NOT NULL AND trim(industry) <> ''
            ),
            joined AS (
              SELECT d.*, l.latest_trade_date,
                     hist.industry AS hist_industry,
                     hist.source_notice_date AS hist_notice_date,
                     hist.source_report_date AS hist_report_date,
                     hist.source AS hist_source,
                     current.industry AS current_industry,
                     current.source_notice_date AS current_notice_date,
                     current.source_report_date AS current_report_date,
                     current.source AS current_source
              FROM d
              JOIN latest l USING (symbol)
              LEFT JOIN LATERAL (
                SELECT * FROM i
                WHERE i.symbol = d.symbol AND i.trade_date <= d.trade_date
                ORDER BY i.trade_date DESC LIMIT 1
              ) hist ON TRUE
              LEFT JOIN LATERAL (
                SELECT * FROM i
                WHERE i.symbol = d.symbol
                ORDER BY i.trade_date DESC LIMIT 1
              ) current ON TRUE
            )
            SELECT * EXCLUDE (latest_trade_date, hist_industry, hist_notice_date,
                              hist_report_date, hist_source, current_industry,
                              current_notice_date, current_report_date,
                              current_source),
              CASE WHEN industry_valid THEN industry
                   WHEN hist_industry IS NOT NULL THEN hist_industry
                   ELSE current_industry END AS research_industry,
              CASE WHEN industry_valid THEN 'canonical_pit'
                   WHEN hist_industry IS NOT NULL THEN 'prior_visible_industry'
                   WHEN current_industry IS NOT NULL THEN 'latest_visible_fallback'
                   ELSE 'unresolved' END AS research_industry_source,
              CASE WHEN industry_valid THEN TRUE
                   WHEN hist_industry IS NOT NULL OR current_industry IS NOT NULL
                   THEN TRUE ELSE FALSE END AS research_industry_valid,
              CASE WHEN industry_valid THEN FALSE
                   WHEN hist_industry IS NOT NULL OR current_industry IS NOT NULL
                   THEN TRUE ELSE FALSE END AS industry_research_fallback,
              CASE WHEN industry_valid THEN industry_snapshot_id ELSE NULL END
                AS research_industry_snapshot_id,
              CASE WHEN industry_valid THEN NULL
                   WHEN hist_industry IS NOT NULL THEN hist_notice_date
                   ELSE current_notice_date END AS research_source_notice_date,
              CASE WHEN industry_valid THEN NULL
                   WHEN hist_industry IS NOT NULL THEN hist_report_date
                   ELSE current_report_date END AS research_source_report_date,
              CASE WHEN industry_valid THEN NULL
                   WHEN hist_industry IS NOT NULL THEN hist_source
                   ELSE current_source END AS research_source
            FROM joined
          ) TO '{target}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)
        counts = con.execute(f"""
          SELECT count(*) AS rows, count(DISTINCT symbol) AS symbols,
                 count(*) FILTER (WHERE research_industry_valid) AS covered_rows,
                 count(DISTINCT symbol) FILTER (WHERE research_industry_valid) AS covered_symbols,
                 count(*) FILTER (WHERE industry_research_fallback) AS fallback_rows,
                 count(DISTINCT symbol) FILTER (WHERE industry_research_fallback) AS fallback_symbols,
                 count(*) FILTER (WHERE NOT research_industry_valid) AS unresolved_rows
          FROM read_parquet('{target}')
        """).fetchone()
    finally:
        con.close()
    audit = {
        "kind": "research_industry_fallback",
        "pit_grade": "B_RESEARCH_ONLY",
        "strict_usable": False,
        "source": {"daily": a.daily, "industry": a.industry},
        "scope": {"start": a.start, "end": a.end, "recent_days": a.recent_days},
        "counts": dict(zip(
            ["rows", "symbols", "covered_rows", "covered_symbols", "fallback_rows",
             "fallback_symbols", "unresolved_rows"],
            (int(value) for value in counts), strict=True
        )),
        "fallback_policy": "canonical PIT, then prior visible industry, then latest visible industry",
        "active_proxy": "symbol must have a recent volume>0 row within recent_days; this is a research proxy, not a delisting proof",
    }
    (a.output / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == "__main__":
    main()
