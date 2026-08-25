#!/usr/bin/env python3
"""Evaluate S2/S3 as partial reductions on a fixed B1-B6 entry set.

This is deliberately a position-level event study, not a portfolio simulator:
each immutable entry is followed independently.  A first S2/S3 warning sells
a fixed fraction at the next open; the remaining fraction exits on the first
structural/disaster/time exit.  The fraction is a stress parameter, not a
post-hoc selected production setting.  S5 uses the same next-bar confirmation
semantics as the corrected exit scan.
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
    sha256_file,
    sql_path,
    values_sql,
    write_ledger,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument(
        "--input-run", type=Path,
        default=ROOT / "data/audit/full_book_b_s_grid_2020_2023_v02_boundaryfix_20260822",
    )
    ap.add_argument(
        "--output", type=Path,
        default=ROOT / "data/audit/partial_reduction_2020_2023_v01",
    )
    ap.add_argument("--param-ids", default="1392,1395,1404,1466,1467")
    ap.add_argument("--fractions", default="0.25,0.50,0.75")
    ap.add_argument("--threads", type=int, default=8)
    args = ap.parse_args()

    config = load_yaml(args.config)
    run_manifest = json.loads((args.input_run / "run_manifest.json").read_text(encoding="utf-8"))
    events = args.input_run / "events.parquet"
    base = Path(run_manifest["base_cache"])
    if not events.exists() or not base.exists():
        raise FileNotFoundError(f"missing immutable inputs: {events}, {base}")
    wanted = {int(x) for x in args.param_ids.split(",") if x.strip()}
    grid = [p for p in make_grid(config) if p["param_id"] in wanted]
    if not grid:
        raise ValueError("no requested parameter ids exist in the configured grid")
    fractions = [float(x) for x in args.fractions.split(",") if x.strip()]
    if any(x <= 0 or x >= 1 for x in fractions):
        raise ValueError("partial reduction fractions must be strictly between 0 and 1")
    args.output.mkdir(parents=True, exist_ok=True)

    costs = config["costs"]
    commission = float(costs["commission_bps_each_side"])
    stamp = float(costs["stamp_duty_bps_sell"])
    slippage = float(costs["slippage_bps_each_side"])
    impact = float(costs["impact_bps_each_side"])
    cost_in = 1.0 + (commission + slippage + impact) / 10000.0
    cost_out = 1.0 - (commission + stamp + slippage + impact) / 10000.0
    psql = values_sql(grid)
    fsql = ", ".join(f"({x:.8f})" for x in fractions)
    event_sql = sql_path(str(events))
    base_sql = sql_path(str(base))
    max_hold = int(config["max_hold_days"])
    threads = max(1, args.threads)

    con = duckdb.connect()
    con.execute(f"PRAGMA threads={threads}")
    con.execute("PRAGMA enable_progress_bar=false")
    query = f"""
    WITH params AS (
      SELECT * FROM (VALUES {psql}) AS p(
        param_id, contraction, pullback, breakout, market_gate,
        sector_gate, confirmation, cooldown, grace)
    ),
    fractions AS (SELECT * FROM (VALUES {fsql}) AS f(reduction_fraction)),
    e AS (
      SELECT e.*, p.grace
      FROM read_parquet('{event_sql}') e JOIN params p USING (param_id)
    ),
    b AS (SELECT * FROM read_parquet('{base_sql}')),
    future0 AS (
      SELECT e.param_id, e.symbol, e.board, e.industry, e.signal,
             e.signal_date, e.entry_date, e.entry_open, e.grace,
             x.trade_date AS signal_exit_date, x.open AS future_open,
             x.close AS future_close, x.volume AS future_volume,
             x.vmed20 AS future_vmed20,
             x.prev_close AS future_prev_close, x.prev2_close AS future_prev2_close,
             x.prev_p50 AS future_prev_p50, x.prev2_p50 AS future_prev2_p50,
             x.prev_p90 AS future_prev_p90, x.prev2_p90 AS future_prev2_p90,
             x.prev_avg AS future_prev_avg, x.prev_conc AS future_prev_conc,
             x.prev_ret AS future_prev_ret, x.prev_space AS future_prev_space,
             x.prev_peak1_center AS future_prev_peak1_center,
             x.prev_peak1_prominence AS future_prev_peak1_prominence,
             x.p50 AS future_p50, x.average_cost AS future_avg,
             x.space20 AS future_space, x.concentration_20 AS future_conc,
             x.base_retention AS future_ret, x.peak_count AS future_peak_count,
             x.peak1_center AS future_peak1_center,
             x.peak1_prominence AS future_peak1_prominence,
             row_number() OVER (
               PARTITION BY e.param_id, e.symbol, e.signal, e.signal_date
               ORDER BY x.trade_date) AS bar_no
      FROM e JOIN b x ON x.symbol=e.symbol AND x.trade_date>e.entry_date
        AND x.trade_date<=e.entry_date + INTERVAL {max_hold + 30} DAY
        AND x.hard_valid
    ),
    raw AS (
      SELECT *,
        (signal_exit_date >= entry_date + grace*INTERVAL 1 DAY
         AND future_close < coalesce(future_prev_peak1_center, future_prev_p90)
         AND future_prev_close < coalesce(future_prev2_p90, future_prev_p90)
         AND future_close < future_prev_close
         AND future_volume > future_vmed20) AS s1,
        (signal_exit_date >= entry_date + grace*INTERVAL 1 DAY
         AND future_conc > future_prev_conc
         AND future_close <= future_prev_close
         AND future_peak1_prominence < future_prev_peak1_prominence) AS s2,
        (signal_exit_date >= entry_date + grace*INTERVAL 1 DAY
         AND future_ret < future_prev_ret
         AND future_close < future_p50
         AND future_prev_close < future_prev2_p50
         AND future_peak1_center < future_prev_peak1_center) AS s3,
        (signal_exit_date >= entry_date + grace*INTERVAL 1 DAY
         AND future_peak_count >= 2
         AND future_close < future_p50
         AND future_prev_close >= future_prev_p50) AS s4,
        (signal_exit_date >= entry_date + grace*INTERVAL 1 DAY
         AND future_close < future_prev_p90
         AND future_prev_close >= future_prev2_p90
         AND future_close < future_open
         AND (future_open > future_prev_p90
              OR future_open >= future_prev_close*1.02
              OR future_close <= future_open*0.97)) AS s5_break,
        (signal_exit_date >= entry_date + grace*INTERVAL 1 DAY
         AND future_space < future_prev_space
         AND future_close < future_prev_avg
         AND future_close < coalesce(future_peak1_center, future_avg)) AS s6,
        (future_close <= entry_open*0.92) AS stop_hit,
        (bar_no >= {max_hold}) AS time_hit
      FROM future0
    ),
    flags AS (
      SELECT *,
        (lag(s5_break) OVER w
         AND future_close < lag(future_prev_p90) OVER w) AS s5,
        lead(signal_exit_date) OVER w AS exec_date,
        lead(future_open) OVER w AS exec_open
      FROM raw
      WINDOW w AS (PARTITION BY param_id, symbol, signal, signal_date ORDER BY bar_no)
    ),
    finals AS (
      SELECT *, CASE WHEN stop_hit THEN 'STOP' WHEN s5 THEN 'S5'
        WHEN s1 THEN 'S1' WHEN s4 THEN 'S4' WHEN s6 THEN 'S6'
        WHEN time_hit THEN 'TIME' END AS exit_reason,
        row_number() OVER (
          PARTITION BY param_id, symbol, signal, signal_date
          ORDER BY bar_no,
            CASE WHEN stop_hit THEN 0 WHEN s5 THEN 1 WHEN s1 THEN 2
                 WHEN s4 THEN 3 WHEN s6 THEN 4 WHEN time_hit THEN 5 ELSE 6 END
        ) AS rn
      FROM flags
      WHERE stop_hit OR s5 OR s1 OR s4 OR s6 OR time_hit
    ),
    final_one AS (
      SELECT * FROM finals WHERE rn=1 AND exec_open IS NOT NULL
    ),
    warning_rows AS (
      SELECT *, row_number() OVER (
        PARTITION BY param_id, symbol, signal, signal_date ORDER BY bar_no
      ) AS wrn
      FROM flags
      WHERE (s2 OR s3) AND exec_open IS NOT NULL
    ),
    first_warning AS (
      SELECT w.*
      FROM warning_rows w JOIN final_one f USING (param_id, symbol, signal, signal_date)
      WHERE w.wrn=1 AND w.bar_no < f.bar_no
    ),
    chosen AS (
      SELECT f.param_id, f.symbol, f.board, f.industry, f.signal, f.signal_date,
             f.entry_date, f.entry_open, f.bar_no AS final_bar_no,
             f.exec_date AS final_exec_date, f.exec_open AS final_exec_open,
             f.exit_reason, f.s1, f.s2, f.s3, f.s4, f.s5, f.s6, f.stop_hit,
             w.signal_exit_date AS warning_signal_date,
             w.exec_date AS warning_exec_date, w.exec_open AS warning_exec_open,
             w.s2 AS warning_s2, w.s3 AS warning_s3,
             CASE WHEN w.param_id IS NULL THEN FALSE ELSE TRUE END AS warning_seen,
             CASE WHEN f.signal_date <= DATE '2022-12-30'
                  THEN 'DISCOVERY_2020_2022' ELSE 'TIMEOUT_2023' END AS sample_group
      FROM final_one f LEFT JOIN first_warning w
        USING (param_id, symbol, signal, signal_date)
    )
    SELECT c.*, fr.reduction_fraction,
      (CASE WHEN c.warning_seen THEN
          fr.reduction_fraction*c.warning_exec_open*{cost_out:.12f}
        ELSE 0 END
       + (CASE WHEN c.warning_seen THEN 1-fr.reduction_fraction ELSE 1 END)
          *c.final_exec_open*{cost_out:.12f})
        /(c.entry_open*{cost_in:.12f}) - 1 AS partial_net_return,
      c.final_exec_open/c.entry_open*{cost_in:.12f}*{cost_out:.12f}-1 AS full_exit_net_return
    FROM chosen c CROSS JOIN fractions fr
    """
    args.output.joinpath("trade_level.parquet").unlink(missing_ok=True)
    con.execute(
        f"COPY ({query}) TO '{sql_path(str(args.output / 'trade_level.parquet'))}' "
        "(FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    out = args.output / "summary.csv"
    con.execute(
        f"""COPY (SELECT reduction_fraction, param_id, sample_group, count(*) AS n,
          count(*) FILTER (WHERE warning_seen) AS warning_n,
          avg(partial_net_return) AS mean_partial_return,
          median(partial_net_return) AS median_partial_return,
          avg(CASE WHEN partial_net_return>0 THEN 1.0 ELSE 0.0 END) AS win_rate,
          avg(full_exit_net_return) AS mean_full_exit_return,
          avg(CASE WHEN exit_reason='STOP' THEN 1.0 ELSE 0.0 END) AS stop_rate
        FROM read_parquet('{sql_path(str(args.output / 'trade_level.parquet'))}')
        GROUP BY ALL ORDER BY reduction_fraction, param_id, sample_group) """
        f"TO '{sql_path(str(out))}' (HEADER, DELIMITER ',')"
    )
    con.execute(
        f"""COPY (SELECT reduction_fraction, sample_group, warning_s2, warning_s3,
          count(*) AS n, avg(partial_net_return) AS mean_return,
          median(partial_net_return) AS median_return
        FROM read_parquet('{sql_path(str(args.output / 'trade_level.parquet'))}')
        WHERE warning_seen GROUP BY ALL ORDER BY reduction_fraction, sample_group,
          warning_s2, warning_s3) TO '{sql_path(str(args.output / 'warning_attribution.csv'))}' """
        "(HEADER, DELIMITER ',')"
    )
    con.close()

    manifest = {
        "research_id": "CYQ-PARTIAL-REDUCTION-2020-2023-V01",
        "generated_at": datetime.now(UTC).isoformat(),
        "config": str(args.config.resolve()),
        "config_sha256": sha256_file(args.config),
        "input_entries": str(events.resolve()),
        "input_base": str(base.resolve()),
        "parameter_ids": sorted(wanted),
        "reduction_fractions": fractions,
        "execution": "warning and final signals execute at next tradable open",
        "s5": "prior-bar break plus current close fails to recapture prior active p90",
        "portfolio_level": False,
        "holdout_accessed": False,
        "outputs": [str((args.output / x).resolve()) for x in
                     ("trade_level.parquet", "summary.csv", "warning_attribution.csv")],
    }
    (args.output / "result.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_ledger(ROOT / "data/audit/experiment_ledger.jsonl", {
        "event_id": f"CYQ-PARTIAL-REDUCTION-2020-2023-V01-{sha256_file(args.config)[:12]}-{len(grid)}",
        "event_type": "PARTIAL_REDUCTION_EVENT_STUDY_COMPLETE",
        "at": datetime.now(UTC).isoformat(), "status": "COMPLETE", "research_only": True,
        "parameter_ids": sorted(wanted), "reduction_fractions": fractions,
        "holdout_accessed": False, "outputs": str(args.output.resolve()),
    })
    print(json.dumps({"phase": "complete", "output": str(args.output),
                      "parameters": sorted(wanted), "fractions": fractions}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
