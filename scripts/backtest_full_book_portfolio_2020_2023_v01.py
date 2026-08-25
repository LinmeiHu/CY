#!/usr/bin/env python3
"""Portfolio stress test for the partial-reduction event study.

This consumes immutable entry/exit events only.  It deliberately does not
recompute signals.  Same-symbol entries are deduplicated by entry date, exits
are processed before entries on the same open, and positions are capped by a
fixed maximum count.  The result is a portfolio-level diagnostic, not a
promotion decision.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from research_full_book_b_s_grid_2020_2023_v01 import (  # noqa: E402
    DEFAULT_CONFIG,
    load_yaml,
    sha256_file,
    sql_path,
)


@dataclass
class Position:
    symbol: str
    shares: float
    entry_date: date
    entry_price: float
    warning_date: date | None
    warning_price: float | None
    final_date: date
    final_price: float
    warning_done: bool = False


def parse_ints(value: str) -> list[int]:
    return [int(x.strip()) for x in value.split(",") if x.strip()]


def parse_floats(value: str) -> list[float]:
    return [float(x.strip()) for x in value.split(",") if x.strip()]


def load_closes(base_path: Path, symbols: list[str], start: date, end: date) -> dict[date, list[tuple[str, float]]]:
    if not symbols:
        return {}
    con = duckdb.connect()
    values = ", ".join("('" + s.replace("'", "''") + "')" for s in symbols)
    con.execute(
        f"CREATE TEMP TABLE symbols AS "
        f"SELECT col0::VARCHAR AS symbol FROM (VALUES {values})"
    )
    base_sql_path = sql_path(str(base_path))
    rows = con.execute(
        f"""SELECT b.trade_date, b.symbol, b.close
        FROM read_parquet('{base_sql_path}') b JOIN symbols s USING (symbol)
        WHERE b.hard_valid AND b.trade_date BETWEEN ? AND ?
        ORDER BY b.trade_date, b.symbol""",
        [start, end],
    ).fetchall()
    con.close()
    closes_by_date: dict[date, list[tuple[str, float]]] = {}
    for trade_date, symbol, close in rows:
        closes_by_date.setdefault(trade_date, []).append((symbol, float(close)))
    return closes_by_date


def simulate(rows: list[tuple], max_positions: int, fraction: float,
             cost_in: float, cost_out: float, initial_capital: float,
             closes_by_date: dict[date, list[tuple[str, float]]]) -> dict:
    # Fixed priority makes simultaneous B4/B5 detections reproducible.
    priority = {"B1": 1, "B2": 2, "B3": 3, "B4": 4, "B5": 5, "B6": 6}
    unique: dict[tuple[str, date], tuple] = {}
    for row in rows:
        key = (row[1], row[6])
        old = unique.get(key)
        if old is None or priority.get(row[4], 99) < priority.get(old[4], 99):
            unique[key] = row
    entries = sorted(unique.values(), key=lambda x: (x[6], x[1], priority.get(x[4], 99)))

    actions: dict[date, list[tuple[str, tuple]]] = {}
    for row in entries:
        # row indexes follow the SELECT in main().
        entry = Position(
            symbol=row[1], shares=0.0, entry_date=row[6], entry_price=row[7],
            warning_date=row[20], warning_price=row[21], final_date=row[9],
            final_price=row[10],
        )
        actions.setdefault(entry.entry_date, []).append(("entry", (entry, row)))
        if entry.warning_date is not None:
            actions.setdefault(entry.warning_date, []).append(("warning", entry))
        actions.setdefault(entry.final_date, []).append(("final", entry))

    cash = initial_capital
    allocation = initial_capital / max_positions
    positions: dict[str, Position] = {}
    skipped_overlap = 0
    skipped_capacity = 0
    equity_points: list[tuple[date, float]] = []
    last_close: dict[str, float] = {}

    # We need all dates on which an action or a valid close is available.
    all_dates = sorted(set(actions) | set(closes_by_date))
    for d in all_dates:
        # Exits release capacity before entries at the same next-open price.
        for kind, payload in sorted(actions.get(d, []), key=lambda x: (0 if x[0] in ("warning", "final") else 1, x[0])):
            if kind == "warning":
                position = payload
                active = positions.get(position.symbol)
                if active is not position or active.warning_done or active.shares <= 0:
                    continue
                sold = active.shares * fraction
                cash += sold * float(active.warning_price) * cost_out
                active.shares -= sold
                active.warning_done = True
            elif kind == "final":
                position = payload
                active = positions.get(position.symbol)
                if active is not position or active.shares <= 0:
                    continue
                cash += active.shares * active.final_price * cost_out
                del positions[active.symbol]
            else:
                position, row = payload
                if position.symbol in positions:
                    skipped_overlap += 1
                    continue
                if len(positions) >= max_positions or cash < allocation * cost_in:
                    skipped_capacity += 1
                    continue
                cash -= allocation * cost_in
                position.shares = allocation / position.entry_price
                positions[position.symbol] = position
        for symbol, close in closes_by_date.get(d, []):
            last_close[symbol] = close
        marked = cash + sum(p.shares * last_close.get(symbol, p.entry_price) for symbol, p in positions.items())
        equity_points.append((d, marked))

    peak = initial_capital
    max_drawdown = 0.0
    for _, equity in equity_points:
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity / peak - 1.0)
    terminal = equity_points[-1][1] if equity_points else initial_capital
    return {
        "unique_entry_count": len(entries),
        "accepted_entry_count": len(entries) - skipped_overlap - skipped_capacity,
        "skipped_overlap": skipped_overlap,
        "skipped_capacity": skipped_capacity,
        "terminal_equity": terminal,
        "total_return": terminal / initial_capital - 1.0,
        "max_drawdown": max_drawdown,
        "open_positions_at_end": len(positions),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument(
        "--input", type=Path,
        default=ROOT / "data/audit/partial_reduction_2020_2023_v02_s5confirm/trade_level.parquet",
    )
    ap.add_argument(
        "--base", type=Path,
        default=ROOT / "data/audit/full_book_b_s_grid_2020_2023_v02_boundaryfix_20260822/base_a6f4b61557c0d358.parquet",
    )
    ap.add_argument("--output", type=Path, default=ROOT / "data/audit/portfolio_2020_2023_v01")
    ap.add_argument("--param-ids", default="1392,1395,1404,1466,1467")
    ap.add_argument("--fractions", default="0.25,0.50,0.75")
    ap.add_argument("--max-positions", default="10,20,30")
    ap.add_argument("--initial-capital", type=float, default=1_000_000.0)
    args = ap.parse_args()
    config = load_yaml(args.config)
    params = parse_ints(args.param_ids)
    fractions = parse_floats(args.fractions)
    max_positions = parse_ints(args.max_positions)
    if not args.input.exists():
        raise FileNotFoundError(args.input)
    if not args.base.exists():
        raise FileNotFoundError(args.base)
    args.output.mkdir(parents=True, exist_ok=True)
    costs = config["costs"]
    cost_in = 1.0 + sum(float(costs[k]) for k in (
        "commission_bps_each_side", "slippage_bps_each_side", "impact_bps_each_side")) / 10000.0
    cost_out = 1.0 - sum(float(costs[k]) for k in (
        "commission_bps_each_side", "stamp_duty_bps_sell", "slippage_bps_each_side", "impact_bps_each_side")) / 10000.0
    con = duckdb.connect()
    rows = con.execute(
        """SELECT param_id, symbol, board, industry, signal, signal_date,
          entry_date, entry_open, final_bar_no, final_exec_date, final_exec_open,
          exit_reason, s1, s2, s3, s4, s5, s6, stop_hit,
          warning_signal_date, warning_exec_date, warning_exec_open,
          warning_s2, warning_s3, warning_seen, sample_group,
          reduction_fraction
        FROM read_parquet(?)
        WHERE param_id IN (SELECT * FROM UNNEST(?))
          AND reduction_fraction IN (SELECT * FROM UNNEST(?))""",
        [str(args.input), params, fractions],
    ).fetchall()
    con.close()
    by_key: dict[tuple[int, float], list[tuple]] = {}
    for row in rows:
        by_key.setdefault((int(row[0]), float(row[26])), []).append(row)
    result_rows: list[dict] = []
    for param_id in params:
        param_rows = [
            row for row in rows if int(row[0]) == param_id
        ]
        param_entries = {(row[1], row[6]) for row in param_rows}
        if param_rows:
            close_start = min(row[6] for row in param_rows)
            close_end = max(row[9] for row in param_rows)
            closes_by_date = load_closes(
                args.base, sorted(symbol for symbol, _ in param_entries),
                close_start, close_end,
            )
        else:
            closes_by_date = {}
        for fraction in fractions:
            candidate_rows = by_key.get((param_id, fraction), [])
            for cap in max_positions:
                metrics = simulate(
                    candidate_rows, cap, fraction, cost_in, cost_out,
                    args.initial_capital, closes_by_date,
                )
                result_rows.append({
                    "param_id": param_id, "reduction_fraction": fraction,
                    "max_positions": cap, **metrics,
                })
    with (args.output / "portfolio_summary.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(result_rows[0]) if result_rows else ["param_id"])
        writer.writeheader()
        writer.writerows(result_rows)
    manifest = {
        "research_id": "CYQ-PORTFOLIO-DIAGNOSTIC-2020-2023-V01",
        "config": str(args.config.resolve()), "config_sha256": sha256_file(args.config),
        "input": str(args.input.resolve()), "base": str(args.base.resolve()),
        "param_ids": params, "fractions": fractions,
        "max_positions": max_positions, "initial_capital": args.initial_capital,
        "entry_dedup": "one per symbol and entry_date; B1..B6 priority",
        "execution": "next-open events; exits before entries on same date",
        "portfolio_level": True, "holdout_accessed": False,
        "note": "diagnostic only; no promotion or live execution",
    }
    (args.output / "result.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"phase": "complete", "output": str(args.output), "rows": len(result_rows)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
