#!/usr/bin/env python3
"""Re-test the same B1-B6 entry universe with book-faithful S1-S6 semantics.

The first grid is intentionally reused as an immutable entry source.  This
isolates the question raised by the research: did the poor result come from
the buy conditions, or from treating warnings and same-bar exit signals as
full, immediately executable sells?  S2/S3 are warnings by default.  All
structural flags use the future row's own lagged chip fields, never the entry
row's lagged fields.  A detected exit is filled at the next tradable open.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from research_full_book_b_s_grid_2020_2023_v01 import (  # noqa: E402
    DEFAULT_CONFIG,
    load_yaml,
    make_grid,
    sha256_file,
    sql_path,
    values_sql,
    write_ledger,
)

SCRIPT_VERSION = "exit-semantics-v0.2-s5-confirmation"


def batch_query(
    events_path: Path,
    base_path: Path,
    params: list[dict[str, Any]],
    output: Path,
    max_hold: int,
    commission: float,
    stamp: float,
    slippage: float,
    impact: float,
    warnings_exit: bool,
    threads: int,
) -> None:
    if not params:
        return
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={max(1, threads)}")
    con.execute("PRAGMA enable_progress_bar=false")
    costs_in = 1.0 + (commission + slippage + impact) / 10000.0
    costs_out = 1.0 - (commission + stamp + slippage + impact) / 10000.0
    psql = values_sql(params)
    events = sql_path(str(events_path))
    base = sql_path(str(base_path))
    warning_priority = "WHEN s2_warning THEN 'S2' WHEN s3_warning THEN 'S3'" if warnings_exit else ""
    query = f"""
    COPY (
      WITH params AS (
        SELECT * FROM (VALUES {psql}) AS p(
          param_id, contraction, pullback, breakout, market_gate,
          sector_gate, confirmation, cooldown, grace)
      ),
      e AS (
        SELECT e.*, p.grace
        FROM read_parquet('{events}') e
        JOIN params p USING (param_id)
      ),
      b AS (SELECT * FROM read_parquet('{base}')),
      future0 AS (
        SELECT e.param_id, e.symbol, e.board, e.industry, e.signal,
               e.signal_date, e.entry_date, e.entry_open, e.grace,
               x.trade_date AS exit_signal_date, x.open AS future_open,
               x.close AS future_close, x.low AS future_low, x.high AS future_high,
               x.volume AS future_volume, x.vmed20 AS future_vmed20,
               x.prev_close AS future_prev_close, x.prev2_close AS future_prev2_close,
               x.prev_p10 AS future_prev_p10, x.prev2_p90 AS future_prev2_p90,
               x.prev_p50 AS future_prev_p50, x.prev2_p50 AS future_prev2_p50,
               x.prev_p90 AS future_prev_p90, x.prev_avg AS future_prev_avg,
               x.prev_conc AS future_prev_conc, x.prev_ret AS future_prev_ret,
               x.prev_space AS future_prev_space,
               x.prev_peak1_center AS future_prev_peak1_center,
               x.prev_peak1_prominence AS future_prev_peak1_prominence,
               x.p10 AS future_p10, x.p50 AS future_p50, x.p90 AS future_p90,
               x.average_cost AS future_avg, x.space20 AS future_space,
               x.concentration_20 AS future_conc, x.base_retention AS future_ret,
               x.peak_count AS future_peak_count,
               x.peak1_center AS future_peak1_center,
               x.peak1_prominence AS future_peak1_prominence,
               x.market_close AS future_market,
               row_number() OVER (PARTITION BY e.param_id, e.symbol, e.signal, e.signal_date
                                  ORDER BY x.trade_date) AS bar_no
        FROM e JOIN b x ON x.symbol=e.symbol AND x.trade_date>e.entry_date
          AND x.trade_date<=e.entry_date + INTERVAL {max_hold + 30} DAY
          AND x.hard_valid
      ),
      raw_flags AS (
        SELECT *,
          (exit_signal_date >= entry_date + grace*INTERVAL 1 DAY
           AND future_close < coalesce(future_prev_peak1_center, future_prev_p90)
           AND future_prev_close < coalesce(future_prev2_p90, future_prev_p90)
           AND future_close < future_prev_close
           AND future_volume > future_vmed20) AS s1_structural,
          (exit_signal_date >= entry_date + grace*INTERVAL 1 DAY
           AND future_conc > future_prev_conc
           AND future_close <= future_prev_close
           AND future_peak1_prominence < future_prev_peak1_prominence) AS s2_warning,
          (exit_signal_date >= entry_date + grace*INTERVAL 1 DAY
           AND future_ret < future_prev_ret
           AND future_close < future_p50
           AND future_prev_close < future_prev2_p50
           AND future_peak1_center < future_prev_peak1_center) AS s3_warning,
          (exit_signal_date >= entry_date + grace*INTERVAL 1 DAY
           AND future_peak_count >= 2
           AND future_close < future_p50
           AND future_prev_close >= future_prev_p50) AS s4_structural,
          (exit_signal_date >= entry_date + grace*INTERVAL 1 DAY
           AND future_close < future_prev_p90
           AND future_prev_close >= future_prev2_p90
           AND future_close < future_open
           AND (future_open > future_prev_p90
                OR future_open >= future_prev_close*1.02
                OR future_close <= future_open*0.97)) AS s5_break,
          (exit_signal_date >= entry_date + grace*INTERVAL 1 DAY
           AND future_space < future_prev_space
           AND future_close < future_prev_avg
           AND future_close < coalesce(future_peak1_center, future_avg)) AS s6_structural,
          (future_close <= entry_open*0.92) AS stop_hit,
          (bar_no >= {max_hold}) AS time_hit
        FROM future0
      ),
      flags AS (
        SELECT *,
          -- Confirm S5 on the next observed bar: the prior bar broke the
          -- active band and the current close still failed to recapture it.
          -- Execution remains the following tradable open.
          (lag(s5_break) OVER w
           AND future_close < lag(future_prev_p90) OVER w) AS s5_confirmed,
          (s3_warning AND lag(s3_warning) OVER w) AS s3_confirmed,
          lead(exit_signal_date) OVER w AS exit_exec_date,
          lead(future_open) OVER w AS exit_exec_open
        FROM raw_flags
        WINDOW w AS (PARTITION BY param_id, symbol, signal, signal_date ORDER BY bar_no)
      ),
      ranked AS (
        SELECT *, CASE WHEN stop_hit THEN 'STOP'
          WHEN s5_confirmed THEN 'S5'
          WHEN s1_structural THEN 'S1'
          WHEN s4_structural THEN 'S4'
          WHEN s6_structural THEN 'S6'
          {warning_priority}
          WHEN time_hit THEN 'TIME' END AS exit_reason,
          row_number() OVER (
            PARTITION BY param_id, symbol, signal, signal_date
            ORDER BY bar_no,
              CASE WHEN stop_hit THEN 0 WHEN s5_confirmed THEN 1
                   WHEN s1_structural THEN 2 WHEN s4_structural THEN 3
                   WHEN s6_structural THEN 4 {('WHEN s2_warning THEN 5 WHEN s3_warning THEN 6' if warnings_exit else '')}
                   WHEN time_hit THEN 7 ELSE 8 END
          ) AS exit_rank
        FROM flags
        WHERE stop_hit OR s5_confirmed OR s1_structural OR s4_structural
           OR s6_structural {('OR s2_warning OR s3_warning' if warnings_exit else '')} OR time_hit
      ),
      chosen AS (SELECT * FROM ranked WHERE exit_rank=1 AND exit_exec_open IS NOT NULL),
      fwd AS (
        SELECT param_id, symbol, signal, signal_date,
          max(future_close) FILTER (WHERE bar_no=5) AS close5,
          max(future_close) FILTER (WHERE bar_no=10) AS close10,
          max(future_close) FILTER (WHERE bar_no=20) AS close20,
          max(future_close) FILTER (WHERE bar_no={max_hold}) AS close60
        FROM future0 GROUP BY ALL
      )
      SELECT c.param_id, c.symbol, c.board, c.industry, c.signal, c.signal_date,
             c.entry_date, c.entry_open, c.exit_signal_date,
             c.exit_exec_date, c.exit_exec_open, c.future_close AS exit_signal_close,
             c.exit_reason, c.s1_structural AS s1, c.s2_warning AS s2_warning,
             c.s3_warning AS s3_warning, c.s4_structural AS s4,
             c.s5_confirmed AS s5, c.s6_structural AS s6, c.stop_hit,
             c.s5_break, c.s3_confirmed,
             f.close5/c.entry_open*{costs_in:.12f}*{costs_out:.12f}-1 AS net_r5,
             f.close10/c.entry_open*{costs_in:.12f}*{costs_out:.12f}-1 AS net_r10,
             f.close20/c.entry_open*{costs_in:.12f}*{costs_out:.12f}-1 AS net_r20,
             f.close60/c.entry_open*{costs_in:.12f}*{costs_out:.12f}-1 AS net_r60,
             c.exit_exec_open/c.entry_open*{costs_in:.12f}*{costs_out:.12f}-1 AS selected_net_return,
             CASE WHEN c.signal_date <= DATE '2022-12-30' THEN 'DISCOVERY_2020_2022'
                  ELSE 'TIMEOUT_2023' END AS sample_group
      FROM chosen c LEFT JOIN fwd f USING (param_id, symbol, signal, signal_date)
    ) TO '{sql_path(str(output))}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """
    try:
        con.execute(query)
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--input-run", type=Path,
                    default=ROOT / "data/audit/full_book_b_s_grid_2020_2023_v02_boundaryfix_20260822")
    ap.add_argument("--output", type=Path,
                    default=ROOT / "data/audit/exit_semantics_2020_2023_v01")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--threads-per-worker", type=int, default=2)
    ap.add_argument("--batch-size", type=int, default=24)
    ap.add_argument("--param-ids", type=str, default=None,
                    help="comma-separated parameter ids for a smoke or focused run")
    ap.add_argument("--warnings-exit", action="store_true",
                    help="comparison arm: treat S2/S3 warnings as full exits")
    args = ap.parse_args()
    config = load_yaml(args.config)
    run_manifest = json.loads((args.input_run / "run_manifest.json").read_text(encoding="utf-8"))
    events = args.input_run / "events.parquet"
    base = Path(run_manifest["base_cache"])
    if not events.exists() or not base.exists():
        raise FileNotFoundError(f"missing immutable inputs: {events}, {base}")
    grid = make_grid(config)
    if args.param_ids:
        wanted = {int(x) for x in args.param_ids.split(",") if x.strip()}
        grid = [p for p in grid if p["param_id"] in wanted]
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "research_id": "CYQ-EXIT-SEMANTICS-2020-2023-V01",
        "script_version": SCRIPT_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "config": str(args.config.resolve()),
        "config_sha256": sha256_file(args.config),
        "input_entries": str(events.resolve()),
        "input_base": str(base.resolve()),
        "input_run_manifest": str((args.input_run / "run_manifest.json").resolve()),
        "parameter_count": len(grid),
        "warnings_exit": args.warnings_exit,
        "execution": "exit signal on future bar, fill next future tradable open",
        "dynamic_reference": "future row's own lagged chip fields; entry lag fields are not reused",
        "parallel": {"workers": args.workers, "threads_per_worker": args.threads_per_worker,
                     "batch_size": args.batch_size},
        "holdout_accessed": False,
    }
    (args.output / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    batches = [grid[i:i + args.batch_size] for i in range(0, len(grid), args.batch_size)]
    costs = config["costs"]
    jobs: list[tuple[int, list[dict[str, Any]], Path]] = []
    for i, batch in enumerate(batches):
        path = args.output / f"batch_{i:04d}.parquet"
        if not path.exists():
            jobs.append((i, batch, path))
    print(json.dumps({"phase": "parallel_semantic_exit_scan", "batches": len(batches), "pending": len(jobs), "parameters": len(grid)}))
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(
                batch_query, events, base, batch, path, int(config["max_hold_days"]),
                float(costs["commission_bps_each_side"]), float(costs["stamp_duty_bps_sell"]),
                float(costs["slippage_bps_each_side"]), float(costs["impact_bps_each_side"]),
                args.warnings_exit, args.threads_per_worker,
            ): i for i, batch, path in jobs
        }
        for future in as_completed(futures):
            idx = futures[future]
            future.result()
            print(json.dumps({"completed_batch": idx + 1, "total_batches": len(batches)}))

    con = duckdb.connect()
    con.execute(f"PRAGMA threads={max(1, args.workers * args.threads_per_worker)}")
    glob = sql_path(str(args.output / "batch_*.parquet"))
    con.execute(f"CREATE OR REPLACE TEMP VIEW events AS SELECT * FROM read_parquet('{glob}')")
    con.execute(f"COPY (SELECT * FROM events ORDER BY param_id, signal_date, symbol, signal) TO '{sql_path(str(args.output / 'events.parquet'))}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.execute(f"""COPY (SELECT param_id, sample_group, board, signal, count(*) AS n,
        avg(selected_net_return) AS mean_selected_return, median(selected_net_return) AS median_selected_return,
        avg(CASE WHEN selected_net_return>0 THEN 1.0 ELSE 0.0 END) AS win_rate,
        count(*) / max(CASE WHEN sample_group='DISCOVERY_2020_2022' THEN 3.0 WHEN sample_group='TIMEOUT_2023' THEN 1.0 END) AS signals_per_year
      FROM events GROUP BY ALL ORDER BY param_id, sample_group, board, signal) TO '{sql_path(str(args.output / 'summary.csv'))}' (HEADER, DELIMITER ',')""")
    con.execute(f"""COPY (SELECT param_id, sample_group, signal, exit_reason, count(*) AS n,
        avg(selected_net_return) AS mean_return FROM events GROUP BY ALL ORDER BY param_id, sample_group, signal, exit_reason)
      TO '{sql_path(str(args.output / 'exit_attribution.csv'))}' (HEADER, DELIMITER ',')""")
    con.execute(f"""COPY (SELECT param_id, sample_group, signal,
        count(*) FILTER (WHERE s2_warning) AS s2_warning_n,
        count(*) FILTER (WHERE s3_warning) AS s3_warning_n,
        count(*) FILTER (WHERE s3_confirmed) AS s3_confirmed_n,
        count(*) FILTER (WHERE s5_break) AS s5_break_n,
        count(*) FILTER (WHERE s5) AS s5_confirmed_n
      FROM events GROUP BY ALL ORDER BY param_id, sample_group, signal)
      TO '{sql_path(str(args.output / 'warning_attribution.csv'))}' (HEADER, DELIMITER ',')""")
    best = con.execute("""
      SELECT param_id, sample_group, count(*) AS n,
             avg(selected_net_return) AS mean_return,
             median(selected_net_return) AS median_return,
             avg(CASE WHEN selected_net_return>0 THEN 1.0 ELSE 0.0 END) AS win_rate
      FROM events WHERE sample_group='DISCOVERY_2020_2022'
      GROUP BY param_id, sample_group ORDER BY mean_return DESC, median_return DESC LIMIT 20
    """).fetchall()
    cols = [x[0] for x in con.description]
    best_rows = [dict(zip(cols, row, strict=True)) for row in best]
    con.close()
    result = {**manifest, "status": "COMPLETE", "best_by_discovery_mean": best_rows,
              "outputs": [str((args.output / name).resolve()) for name in
                          ("events.parquet", "summary.csv", "exit_attribution.csv", "warning_attribution.csv")]}
    (args.output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    write_ledger(ROOT / "data/audit/experiment_ledger.jsonl", {
        "event_id": f"CYQ-EXIT-SEMANTICS-2020-2023-V01-{sha256_file(args.config)[:12]}-{len(grid)}",
        "event_type": "EXIT_SEMANTICS_COMPLETE",
        "at": datetime.now(UTC).isoformat(), "status": "COMPLETE", "research_only": True,
        "parameter_count": len(grid), "warnings_exit": args.warnings_exit,
        "holdout_accessed": False, "outputs": str(args.output.resolve()),
    })
    print(json.dumps({"phase": "complete", "output": str(args.output), "best": best_rows[:5]}, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
