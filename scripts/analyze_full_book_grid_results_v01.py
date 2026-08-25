#!/usr/bin/env python3
"""Diagnose the full-book B/S grid without touching the later holdout.

This is deliberately a read-only analysis of the event-study output.  A
parameter is eligible only when its *discovery-period* signal rate is inside
the configured target band.  All rankings are made from discovery rows; the
2023 timeout period is joined afterwards as an untouched temporal check.

The scanner is an event study, not a portfolio simulation.  Consequently,
the outputs below describe conditional signal/exit behavior and do not claim
that all events could be held concurrently in one account.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import duckdb
import yaml
from research_full_book_b_s_grid_2020_2023_v01 import make_grid, sql_path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs/full_book_research_2020_2023_v01.yaml"


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"config root must be a mapping: {path}")
    return value


def write_csv(con: duckdb.DuckDBPyConnection, query: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(
        f"COPY ({query}) TO '{sql_path(str(path.resolve()))}' "
        "(FORMAT CSV, HEADER, DELIMITER ',')"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--run-dir",
        type=Path,
        default=ROOT / "data/audit/full_book_b_s_grid_2020_2023_v02_boundaryfix_20260822",
    )
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--top-k", type=int, default=12)
    ap.add_argument("--threads", type=int, default=4)
    args = ap.parse_args()
    if args.top_k < 1:
        raise ValueError("--top-k must be positive")

    run_dir = args.run_dir.resolve()
    events = run_dir / "events.parquet"
    if not events.exists():
        raise FileNotFoundError(events)
    cfg = load_yaml(args.config)
    params = make_grid(cfg)
    target = float(cfg["target_signals_per_year"])
    tolerance = float(cfg["signal_target_tolerance"])
    lower = target * (1.0 - tolerance)
    upper = target * (1.0 + tolerance)
    output = run_dir / "diagnostics_v01"
    output.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute(f"PRAGMA threads={max(1, args.threads)}")
    con.execute("PRAGMA enable_progress_bar=false")
    con.execute(
        """
        CREATE TEMP TABLE params (
          param_id INTEGER,
          contraction DOUBLE,
          pullback DOUBLE,
          breakout DOUBLE,
          market_gate INTEGER,
          sector_gate INTEGER,
          confirmation INTEGER,
          cooldown INTEGER,
          grace INTEGER
        )
        """
    )
    con.executemany(
        "INSERT INTO params VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                p["param_id"],
                p["contraction"],
                p["pullback"],
                p["breakout"],
                p["market_gate"],
                p["sector_gate"],
                p["confirmation"],
                p["cooldown"],
                p["grace"],
            )
            for p in params
        ],
    )
    event_path = sql_path(str(events))
    con.execute(
        f"CREATE OR REPLACE TEMP VIEW events AS "
        f"SELECT * FROM read_parquet('{event_path}', union_by_name=true)"
    )

    # Keep the discovery-only ranking in one view.  A signal is a scanner
    # event; overlapping B1-B6 events are intentionally not silently merged.
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW param_metrics AS
        WITH p AS (
          SELECT p.*,
                 d.n AS discovery_n,
                 d.mean_return AS discovery_mean_return,
                 d.median_return AS discovery_median_return,
                 d.win_rate AS discovery_win_rate,
                 d.mean_r5 AS discovery_mean_r5,
                 d.mean_r10 AS discovery_mean_r10,
                 d.mean_r20 AS discovery_mean_r20,
                 d.mean_r60 AS discovery_mean_r60,
                 d.signals_per_year AS discovery_signals_per_year,
                 d.mean_return * 0.5 + d.median_return * 0.5 AS discovery_robust_score,
                 t.n AS timeout_n,
                 t.mean_return AS timeout_mean_return,
                 t.median_return AS timeout_median_return,
                 t.win_rate AS timeout_win_rate,
                 t.mean_r5 AS timeout_mean_r5,
                 t.mean_r10 AS timeout_mean_r10,
                 t.mean_r20 AS timeout_mean_r20,
                 t.mean_r60 AS timeout_mean_r60,
                 t.signals_per_year AS timeout_signals_per_year
          FROM params p
          LEFT JOIN (
            SELECT param_id, count(*) AS n,
                   avg(selected_net_return) AS mean_return,
                   median(selected_net_return) AS median_return,
                   avg(CASE WHEN selected_net_return > 0 THEN 1.0 ELSE 0.0 END) AS win_rate,
                   avg(net_r5) AS mean_r5, avg(net_r10) AS mean_r10,
                   avg(net_r20) AS mean_r20, avg(net_r60) AS mean_r60,
                   count(*) / 3.0 AS signals_per_year
            FROM events
            WHERE sample_group = 'DISCOVERY_2020_2022'
            GROUP BY param_id
          ) d USING (param_id)
          LEFT JOIN (
            SELECT param_id, count(*) AS n,
                   avg(selected_net_return) AS mean_return,
                   median(selected_net_return) AS median_return,
                   avg(CASE WHEN selected_net_return > 0 THEN 1.0 ELSE 0.0 END) AS win_rate,
                   avg(net_r5) AS mean_r5, avg(net_r10) AS mean_r10,
                   avg(net_r20) AS mean_r20, avg(net_r60) AS mean_r60,
                   count(*)::DOUBLE AS signals_per_year
            FROM events
            WHERE sample_group = 'TIMEOUT_2023'
            GROUP BY param_id
          ) t USING (param_id)
        ), ranked AS (
          SELECT p.*,
                 row_number() OVER (ORDER BY discovery_mean_return DESC NULLS LAST) AS rank_discovery_mean,
                 row_number() OVER (ORDER BY discovery_robust_score DESC NULLS LAST) AS rank_discovery_robust,
                 abs(discovery_signals_per_year - {target}) AS target_distance,
                 CASE WHEN discovery_signals_per_year BETWEEN {lower} AND {upper}
                      THEN TRUE ELSE FALSE END AS target_rate_eligible
          FROM p
        )
        SELECT * FROM ranked
        """
    )
    write_csv(con, "SELECT * FROM param_metrics ORDER BY rank_discovery_mean", output / "candidate_params_all.csv")
    write_csv(
        con,
        """
        SELECT * FROM param_metrics
        WHERE target_rate_eligible
        ORDER BY discovery_mean_return DESC, discovery_median_return DESC
        """,
        output / "candidate_params_by_discovery_mean.csv",
    )
    write_csv(
        con,
        """
        SELECT * FROM param_metrics
        WHERE target_rate_eligible
        ORDER BY discovery_robust_score DESC, discovery_mean_return DESC
        """,
        output / "candidate_params_by_discovery_robust.csv",
    )

    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE top_params AS
        SELECT param_id, 'MEAN' AS ranking FROM param_metrics
        WHERE target_rate_eligible
        ORDER BY discovery_mean_return DESC, discovery_median_return DESC
        LIMIT {args.top_k}
        """
    )
    # Append robust top-k, preserving the union if it differs from mean top-k.
    con.execute(
        f"""
        INSERT INTO top_params
        SELECT param_id, 'ROBUST' AS ranking FROM param_metrics
        WHERE target_rate_eligible
        ORDER BY discovery_robust_score DESC, discovery_mean_return DESC
        LIMIT {args.top_k}
        """
    )
    con.execute("CREATE OR REPLACE TEMP VIEW top_param_ids AS SELECT DISTINCT param_id FROM top_params")

    write_csv(
        con,
        """
        SELECT e.sample_group, year(e.signal_date) AS signal_year,
               e.param_id, e.board, e.signal, count(*) AS n,
               avg(e.selected_net_return) AS mean_selected_return,
               median(e.selected_net_return) AS median_selected_return,
               avg(CASE WHEN e.selected_net_return > 0 THEN 1.0 ELSE 0.0 END) AS win_rate,
               avg(e.net_r5) AS mean_r5, avg(e.net_r10) AS mean_r10,
               avg(e.net_r20) AS mean_r20, avg(e.net_r60) AS mean_r60,
               avg(CASE WHEN e.exit_reason = 'STOP' THEN 1.0 ELSE 0.0 END) AS stop_rate,
               avg(CASE WHEN e.exit_reason = 'TIME' THEN 1.0 ELSE 0.0 END) AS time_rate
        FROM events e JOIN top_param_ids t USING (param_id)
        GROUP BY ALL
        ORDER BY param_id, sample_group, signal_year, board, signal
        """,
        output / "top_candidate_signals.csv",
    )
    write_csv(
        con,
        """
        SELECT e.sample_group, e.param_id, e.board, e.signal, e.exit_reason,
               count(*) AS n,
               avg(e.selected_net_return) AS mean_selected_return,
               median(e.selected_net_return) AS median_selected_return,
               avg(CASE WHEN e.selected_net_return > 0 THEN 1.0 ELSE 0.0 END) AS win_rate,
               avg(e.net_r5) AS mean_r5, avg(e.net_r10) AS mean_r10,
               avg(e.net_r20) AS mean_r20, avg(e.net_r60) AS mean_r60
        FROM events e JOIN top_param_ids t USING (param_id)
        GROUP BY ALL
        ORDER BY param_id, sample_group, board, signal, exit_reason
        """,
        output / "top_candidate_exits.csv",
    )
    write_csv(
        con,
        """
        SELECT e.sample_group, e.param_id, e.board, e.signal,
               coalesce(nullif(trim(e.industry), ''), 'UNKNOWN') AS industry,
               CASE
                 WHEN lower(coalesce(e.industry, '')) LIKE '%银行%' THEN 'BANK'
                 WHEN lower(coalesce(e.industry, '')) ~ '有色|钢铁|煤炭|石油|化工|采掘|房地产|建筑材料|基础化工' THEN 'CYCLICAL'
                 WHEN lower(coalesce(e.industry, '')) ~ '证券|保险|多元金融' THEN 'FINANCE_EX_BANK'
                 ELSE 'OTHER_OR_UNKNOWN'
               END AS industry_class,
               count(*) AS n,
               avg(e.selected_net_return) AS mean_selected_return,
               median(e.selected_net_return) AS median_selected_return,
               avg(CASE WHEN e.selected_net_return > 0 THEN 1.0 ELSE 0.0 END) AS win_rate,
               avg(e.net_r20) AS mean_r20,
               avg(CASE WHEN e.exit_reason = 'STOP' THEN 1.0 ELSE 0.0 END) AS stop_rate
        FROM events e JOIN top_param_ids t USING (param_id)
        GROUP BY ALL
        ORDER BY param_id, sample_group, board, signal, n DESC
        """,
        output / "top_candidate_industries.csv",
    )
    write_csv(
        con,
        """
        WITH ranked AS (
          SELECT e.sample_group, e.param_id, e.board, e.signal, e.symbol,
                 e.signal_date, e.entry_date, e.exit_date, e.exit_reason,
                 e.selected_net_return, e.net_r5, e.net_r10, e.net_r20, e.net_r60,
                 row_number() OVER (
                   PARTITION BY e.param_id, e.sample_group
                   ORDER BY e.selected_net_return DESC, e.symbol
                 ) AS win_rank,
                 row_number() OVER (
                   PARTITION BY e.param_id, e.sample_group
                   ORDER BY e.selected_net_return ASC, e.symbol
                 ) AS loss_rank
          FROM events e JOIN top_param_ids t USING (param_id)
        )
        SELECT 'WIN' AS tail, * FROM ranked WHERE win_rank <= 20
        UNION ALL
        SELECT 'LOSS' AS tail, * FROM ranked WHERE loss_rank <= 20
        ORDER BY param_id, sample_group, tail, selected_net_return
        """,
        output / "top_candidate_winners_losers.csv",
    )
    write_csv(
        con,
        """
        SELECT e.sample_group, e.param_id, e.board, e.signal,
               e.exit_reason, count(*) AS n,
               avg(e.selected_net_return) AS mean_selected_return,
               median(e.selected_net_return) AS median_selected_return,
               avg(e.net_r5) AS mean_r5, avg(e.net_r10) AS mean_r10,
               avg(e.net_r20) AS mean_r20, avg(e.net_r60) AS mean_r60
        FROM events e JOIN top_param_ids t USING (param_id)
        GROUP BY ALL
        ORDER BY param_id, sample_group, board, signal, exit_reason
        """,
        output / "top_candidate_return_horizons.csv",
    )

    manifest = {
        "analysis_version": "full-book-grid-diagnostics-v0.1",
        "run_dir": str(run_dir),
        "events": str(events),
        "config": str(args.config.resolve()),
        "parameter_count": len(params),
        "target_signals_per_year": target,
        "target_band": [lower, upper],
        "top_k_each_ranking": args.top_k,
        "ranking_source": "DISCOVERY_2020_2022 only",
        "validation_source": "TIMEOUT_2023 only; not used for ranking",
        "holdout_2024_2026_read": False,
        "outputs": sorted(str(p.resolve()) for p in output.glob("*.csv")),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
