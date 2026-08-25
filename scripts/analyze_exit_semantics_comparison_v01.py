#!/usr/bin/env python3
"""Compare strict and warning-aware S1-S6 exit semantics on the same entries.

This is a read-only diagnostic.  It deliberately separates:
  * entry counts (the signal-rate gate), from
  * selected exits (which are conditional on an exit being observed).

It therefore cannot be used as a portfolio performance report.  Its purpose
is to quantify whether the exit-semantic change is robust before implementing
partial reductions and position-level accounting.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT / "scripts"))
from research_full_book_b_s_grid_2020_2023_v01 import (  # noqa: E402
    DEFAULT_CONFIG,
    load_yaml,
    make_grid,
    sql_path,
    values_sql,
)


def write_csv(con: duckdb.DuckDBPyConnection, query: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY ({query}) TO '{sql_path(str(path))}' (HEADER, DELIMITER ',')")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--strict",
        type=Path,
        default=ROOT / "data/audit/exit_semantics_2020_2023_v01",
    )
    ap.add_argument(
        "--warning",
        type=Path,
        default=ROOT / "data/audit/exit_semantics_warning_2020_2023_v01",
    )
    ap.add_argument(
        "--input-run",
        type=Path,
        default=ROOT / "data/audit/full_book_b_s_grid_2020_2023_v02_boundaryfix_20260822",
    )
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data/audit/exit_semantics_comparison_2020_2023_v01",
    )
    ap.add_argument("--lower", type=int, default=130)
    ap.add_argument("--upper", type=int, default=270)
    args = ap.parse_args()

    config = load_yaml(args.config)
    grid = make_grid(config)
    psql = values_sql(grid)
    entries = args.input_run / "events.parquet"
    strict = args.strict / "batch_*.parquet"
    warning = args.warning / "batch_*.parquet"
    if not entries.exists() or not args.strict.exists() or not args.warning.exists():
        raise FileNotFoundError("missing entry or semantic output directory")

    args.output.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    con.execute("PRAGMA enable_progress_bar=false")
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE params AS
        SELECT * FROM (VALUES {psql}) AS p(
          param_id, contraction, pullback, breakout, market_gate,
          sector_gate, confirmation, cooldown, grace)
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW entries AS
        SELECT e.*, p.contraction, p.pullback, p.breakout, p.market_gate,
               p.sector_gate, p.confirmation, p.cooldown, p.grace,
               EXTRACT(year FROM e.signal_date)::INTEGER AS signal_year
        FROM read_parquet('{sql_path(str(entries))}') e
        JOIN params p USING (param_id)
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW strict AS
        SELECT *, 'STRICT' AS exit_arm
        FROM read_parquet('{sql_path(str(strict))}')
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW warning AS
        SELECT *, 'WARNING_AWARE' AS exit_arm
        FROM read_parquet('{sql_path(str(warning))}')
        """
    )
    con.execute("CREATE OR REPLACE TEMP VIEW selected AS SELECT * FROM strict UNION ALL SELECT * FROM warning")

    entry_q = """
    SELECT param_id, signal_year, sample_group, count(*)::BIGINT AS entry_n,
           count(*) FILTER (WHERE signal='B1')::BIGINT AS b1_n,
           count(*) FILTER (WHERE signal='B2')::BIGINT AS b2_n,
           count(*) FILTER (WHERE signal='B3')::BIGINT AS b3_n,
           count(*) FILTER (WHERE signal='B4')::BIGINT AS b4_n,
           count(*) FILTER (WHERE signal='B5')::BIGINT AS b5_n,
           count(*) FILTER (WHERE signal='B6')::BIGINT AS b6_n
    FROM entries
    GROUP BY ALL
    ORDER BY param_id, signal_year
    """
    write_csv(con, entry_q, args.output / "annual_entry_counts.csv")

    stats_q = """
    SELECT exit_arm, param_id, sample_group,
           count(*)::BIGINT AS selected_n,
           avg(selected_net_return) AS mean_return,
           median(selected_net_return) AS median_return,
           avg(CASE WHEN selected_net_return > 0 THEN 1.0 ELSE 0.0 END) AS win_rate,
           count(*) FILTER (WHERE exit_reason='STOP')::BIGINT AS stop_n,
           count(*) FILTER (WHERE exit_reason='S1')::BIGINT AS s1_n,
           count(*) FILTER (WHERE exit_reason='S2')::BIGINT AS s2_n,
           count(*) FILTER (WHERE exit_reason='S3')::BIGINT AS s3_n,
           count(*) FILTER (WHERE exit_reason='S4')::BIGINT AS s4_n,
           count(*) FILTER (WHERE exit_reason='S5')::BIGINT AS s5_n,
           count(*) FILTER (WHERE exit_reason='S6')::BIGINT AS s6_n,
           count(*) FILTER (WHERE exit_reason='TIME')::BIGINT AS time_n
    FROM selected
    GROUP BY ALL
    ORDER BY exit_arm, param_id, sample_group
    """
    write_csv(con, stats_q, args.output / "selected_exit_stats.csv")

    attribution_q = """
    SELECT exit_arm, sample_group, exit_reason,
           count(*)::BIGINT AS n,
           avg(selected_net_return) AS mean_return,
           median(selected_net_return) AS median_return,
           avg(CASE WHEN selected_net_return > 0 THEN 1.0 ELSE 0.0 END) AS win_rate
    FROM selected
    GROUP BY ALL
    ORDER BY exit_arm, sample_group, exit_reason
    """
    write_csv(con, attribution_q, args.output / "exit_attribution.csv")

    candidate_q = f"""
    WITH entry AS (
      SELECT param_id,
             sum(entry_n) FILTER (WHERE sample_group='DISCOVERY_2020_2022') AS discovery_entries,
             avg(entry_n) FILTER (WHERE sample_group='DISCOVERY_2020_2022') AS avg_annual_entries,
             min(entry_n) FILTER (WHERE sample_group='DISCOVERY_2020_2022') AS min_annual_entries,
             max(entry_n) FILTER (WHERE sample_group='DISCOVERY_2020_2022') AS max_annual_entries,
             sum(entry_n) FILTER (WHERE sample_group='TIMEOUT_2023') AS timeout_entries
      FROM (
        SELECT param_id, signal_year, sample_group, count(*)::BIGINT AS entry_n
        FROM entries GROUP BY ALL
      ) x
      GROUP BY param_id
    ), stats AS (
      SELECT exit_arm, param_id,
             max(mean_return) FILTER (WHERE sample_group='DISCOVERY_2020_2022') AS discovery_mean,
             max(median_return) FILTER (WHERE sample_group='DISCOVERY_2020_2022') AS discovery_median,
             max(win_rate) FILTER (WHERE sample_group='DISCOVERY_2020_2022') AS discovery_win,
             max(selected_n) FILTER (WHERE sample_group='DISCOVERY_2020_2022') AS discovery_selected,
             max(mean_return) FILTER (WHERE sample_group='TIMEOUT_2023') AS timeout_mean,
             max(median_return) FILTER (WHERE sample_group='TIMEOUT_2023') AS timeout_median,
             max(win_rate) FILTER (WHERE sample_group='TIMEOUT_2023') AS timeout_win,
             max(selected_n) FILTER (WHERE sample_group='TIMEOUT_2023') AS timeout_selected
      FROM (
        SELECT exit_arm, param_id, sample_group, count(*)::BIGINT AS selected_n,
               avg(selected_net_return) AS mean_return,
               median(selected_net_return) AS median_return,
               avg(CASE WHEN selected_net_return > 0 THEN 1.0 ELSE 0.0 END) AS win_rate
        FROM selected GROUP BY ALL
      ) y
      GROUP BY exit_arm, param_id
    )
    SELECT s.exit_arm, s.param_id, p.contraction, p.pullback, p.breakout,
           p.market_gate, p.sector_gate, p.confirmation, p.cooldown, p.grace,
           e.discovery_entries, e.avg_annual_entries, e.min_annual_entries,
           e.max_annual_entries, e.timeout_entries,
           s.discovery_selected / NULLIF(e.discovery_entries, 0) AS discovery_exit_coverage,
           s.timeout_selected / NULLIF(e.timeout_entries, 0) AS timeout_exit_coverage,
           s.discovery_mean, s.discovery_median, s.discovery_win,
           s.timeout_mean, s.timeout_median, s.timeout_win,
           (e.avg_annual_entries BETWEEN {args.lower} AND {args.upper}) AS avg_rate_eligible,
           (e.min_annual_entries >= {args.lower} AND e.max_annual_entries <= {args.upper}) AS every_year_rate_eligible
    FROM stats s JOIN entry e USING (param_id)
    JOIN params p USING (param_id)
    WHERE e.avg_annual_entries BETWEEN {args.lower} AND {args.upper}
    ORDER BY s.exit_arm, s.discovery_mean DESC NULLS LAST
    """
    write_csv(con, candidate_q, args.output / "candidate_comparison.csv")

    paired_q = """
    WITH x AS (
      SELECT exit_arm, param_id, sample_group, mean_return, median_return, win_rate, selected_n
      FROM (
        SELECT 'STRICT' AS exit_arm, param_id, sample_group,
               avg(selected_net_return) AS mean_return,
               median(selected_net_return) AS median_return,
               avg(CASE WHEN selected_net_return > 0 THEN 1.0 ELSE 0.0 END) AS win_rate,
               count(*)::BIGINT AS selected_n
        FROM strict GROUP BY ALL
        UNION ALL
        SELECT 'WARNING_AWARE', param_id, sample_group,
               avg(selected_net_return), median(selected_net_return),
               avg(CASE WHEN selected_net_return > 0 THEN 1.0 ELSE 0.0 END), count(*)::BIGINT
        FROM warning GROUP BY ALL
      )
    )
    SELECT a.param_id, a.sample_group,
           a.mean_return AS strict_mean, b.mean_return AS warning_mean,
           b.mean_return-a.mean_return AS mean_delta,
           a.median_return AS strict_median, b.median_return AS warning_median,
           b.median_return-a.median_return AS median_delta,
           a.win_rate AS strict_win, b.win_rate AS warning_win,
           b.win_rate-a.win_rate AS win_delta,
           a.selected_n AS strict_n, b.selected_n AS warning_n
    FROM (SELECT * FROM x WHERE exit_arm='STRICT') a
    JOIN (SELECT * FROM x WHERE exit_arm='WARNING_AWARE') b
      USING (param_id, sample_group)
    ORDER BY sample_group, mean_delta DESC
    """
    write_csv(con, paired_q, args.output / "paired_semantic_delta.csv")

    meta = {
        "generated_at": datetime.now(UTC).isoformat(),
        "strict": str(args.strict.resolve()),
        "warning": str(args.warning.resolve()),
        "input_entries": str(entries.resolve()),
        "config": str(args.config.resolve()),
        "signal_rate_band": [args.lower, args.upper],
        "ranking_sample": "DISCOVERY_2020_2022",
        "validation_sample": "TIMEOUT_2023",
        "holdout_accessed": False,
        "interpretation": "selected exits are conditional on an exit before max holding period; not portfolio PnL",
    }
    # Small aggregate facts are kept in JSON so downstream reports need not
    # infer them from CSV row ordering.
    facts = con.execute(
        """
        SELECT exit_arm, sample_group, count(*)::BIGINT AS n,
               avg(selected_net_return) AS mean_return,
               median(selected_net_return) AS median_return
        FROM selected GROUP BY ALL ORDER BY exit_arm, sample_group
        """
    ).fetchall()
    meta["selected_exit_facts"] = [
        {"exit_arm": a, "sample_group": b, "n": n, "mean_return": m, "median_return": md}
        for a, b, n, m, md in facts
    ]
    (args.output / "result.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    con.close()
    print(json.dumps(meta, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
