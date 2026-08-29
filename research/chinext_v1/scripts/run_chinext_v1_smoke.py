#!/usr/bin/env python3
"""Run the deterministic 50-stock ChinNext V1 exploratory smoke replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from statistics import fmean
from typing import Any

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strategy.chinext_v1_exploratory import (  # noqa: E402
    BREAKOUT_VOLUME_MODE,
    EXECUTION_LIMIT_MODEL,
    MARKET_ANCHOR,
    RANK_REPLACEMENT,
    RESEARCH_MODE,
    ChinNextV1Config,
    breakout_volume_diagnostic,
    build_rs_table,
    decide_next_open_fill,
    desired_target_weights,
    deterministic_equidistant_sample,
    entry_price_structure,
    market_gate_state,
    minvol_diagnostic,
    own_exit_signal,
    performance_summary,
    select_no_replacement_members,
    set_change_required,
    sort_candidates,
    trade_return_summary,
)

SURVIVOR_WARNING = (
    "CURRENT SURVIVOR UNIVERSE / NOT POINT-IN-TIME / SURVIVORSHIP BIASED / "
    "NOT VALID FOR FINAL PERFORMANCE CLAIMS"
)
DEFAULT_SURVIVOR = Path(
    "research/supermind_v6/manifests/chinext_current_survivor_universe.json"
)
DEFAULT_DAILY_ROOT = Path(
    "/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily"
)
DEFAULT_MARKET = Path("research/chinext_v1/data/smoke/399102_daily.csv")
DEFAULT_CALENDAR = Path(
    "/Users/linmei/Downloads/workspace/quant/data/lake/meta/trade_calendar.parquet"
)


@dataclass
class Position:
    shares: float
    cost_basis: float
    acquisition_date: date
    entry_signal_date: date
    dividends: float = 0.0
    cycle_buy_cost: float = 0.0
    cycle_realized_pnl: float = 0.0


@dataclass
class PendingOrder:
    symbol: str
    target_weight: float
    signal_date: date
    signal_reason: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2024, 1, 2))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2025, 12, 31))
    parser.add_argument("--sample-size", type=int, default=50)
    parser.add_argument(
        "--full-survivor",
        action="store_true",
        help="replay every manifest survivor; intended for the dedicated full wrapper",
    )
    parser.add_argument("--initial-cash", type=float, default=1_000_000.0)
    parser.add_argument("--survivor", type=Path, default=DEFAULT_SURVIVOR)
    parser.add_argument("--daily-root", type=Path, default=DEFAULT_DAILY_ROOT)
    parser.add_argument("--market", type=Path, default=DEFAULT_MARKET)
    parser.add_argument("--calendar", type=Path, default=DEFAULT_CALENDAR)
    parser.add_argument(
        "--summary", type=Path, default=Path("research/chinext_v1/reports/chinext_v1_smoke_summary.json")
    )
    parser.add_argument(
        "--report", type=Path, default=Path("research/chinext_v1/reports/chinext_v1_smoke.md")
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("research/chinext_v1/output/chinext_v1_smoke")
    )
    return parser.parse_args()


def finite_positive(value: Any) -> bool:
    try:
        return math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False


def finite_or_default(value: Any, default: float) -> float:
    """Normalize provider null/NaN to its explicit neutral action value."""

    try:
        converted = float(value)
    except (TypeError, ValueError):
        return default
    return converted if math.isfinite(converted) else default


def json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def write_json(path: Path, payload: Any) -> None:
    atomic_text(path, json.dumps(json_value(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def daily_glob(root: Path, start: date, end: date) -> list[str]:
    paths = [root / f"partition_year={year}" / "data_0.parquet" for year in range(start.year, end.year + 1)]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing CY-006 partitions: {missing}")
    return [str(path) for path in paths]


def load_survivors(path: Path) -> tuple[list[str], dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "NON_PIT_CURRENT_SURVIVOR" not in str(payload.get("point_in_time_status")):
        raise ValueError("exploratory input is not explicitly labeled NON_PIT_CURRENT_SURVIVOR")
    names = {str(item["symbol"]): str(item.get("name") or "") for item in payload["records"]}
    symbols = sorted(names)
    if payload.get("symbol_count") != len(symbols) or len(symbols) != len(set(symbols)):
        raise ValueError("current-survivor manifest count/uniqueness mismatch")
    if any(not (symbol.startswith(("300", "301")) and symbol.endswith(".SZ")) for symbol in symbols):
        raise ValueError("current-survivor manifest contains a non-ChiNext-prefix symbol")
    return symbols, names


def load_pit_membership(
    path: Path,
    start: date,
    end: date,
) -> tuple[list[str], dict[date, dict[str, int]], dict[str, Any]]:
    """Load the frozen daily PIT universe without any survivor fallback."""

    frame = pd.read_parquet(
        path,
        columns=["trade_date", "symbol", "listed_trading_days", "pit_grade"],
    )
    required = {"trade_date", "symbol", "listed_trading_days", "pit_grade"}
    if set(frame.columns) != required:
        raise ValueError("PIT membership schema mismatch")
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    if frame.empty or frame.duplicated(["trade_date", "symbol"]).any():
        raise ValueError("PIT membership is empty or contains duplicate security-date rows")
    if frame["trade_date"].min() != start or frame["trade_date"].max() != end:
        raise ValueError("PIT membership date range does not exactly match replay scope")
    if not frame["trade_date"].between(start, end).all():
        raise ValueError("PIT membership contains out-of-scope dates")
    if set(frame["pit_grade"].astype(str).unique()) != {"B_RECONSTRUCTED"}:
        raise ValueError("PIT membership grade mismatch")
    ages = pd.to_numeric(frame["listed_trading_days"], errors="coerce")
    if ages.isna().any() or (ages < 1).any() or (ages % 1 != 0).any():
        raise ValueError("PIT membership contains invalid listing ages")
    symbols = sorted(frame["symbol"].astype(str).unique())
    if any(not (symbol.startswith(("300", "301", "302")) and symbol.endswith(".SZ")) for symbol in symbols):
        raise ValueError("PIT membership contains a non-ChiNext identity")
    by_date: dict[date, dict[str, int]] = {}
    for trade_date, rows in frame.groupby("trade_date", sort=True):
        by_date[trade_date] = dict(
            zip(rows["symbol"].astype(str), rows["listed_trading_days"].astype(int), strict=True)
        )
    metadata = {
        "path": str(path),
        "sha256": sha256_file(path),
        "rows": len(frame),
        "date_count": len(by_date),
        "unique_symbols": len(symbols),
        "pit_grade": "B_RECONSTRUCTED",
    }
    return symbols, by_date, metadata


def history_candidates(
    connection: duckdb.DuckDBPyConnection,
    paths: list[str],
    survivors: list[str],
    start: date,
    config: ChinNextV1Config,
) -> pd.DataFrame:
    connection.register("survivors", pd.DataFrame({"symbol": survivors}))
    return connection.execute(
        """
        SELECT d.symbol,
               count(*) FILTER (
                 WHERE d.hard_valid
                   AND d.bar_valid
                   AND d.historical_identity_valid
                   AND isfinite(d.close) AND d.close > 0
                   AND isfinite(d.volume) AND d.volume > 0
                   AND isfinite(d.amount) AND d.amount >= 0
               ) AS completed_observations,
               min(d.trade_date) AS first_date,
               max(d.trade_date) AS last_date
        FROM read_parquet(?) d
        INNER JOIN survivors s USING(symbol)
        WHERE d.trade_date < ?
        GROUP BY d.symbol
        HAVING completed_observations >= ?
           AND last_date >= ? - INTERVAL 10 DAY
        ORDER BY d.symbol
        """,
        [paths, start, config.min_completed_observations, start],
    ).fetchdf()


def load_sample_panel(
    connection: duckdb.DuckDBPyConnection,
    paths: list[str],
    sample: tuple[str, ...],
    warmup_start: date,
    end: date,
) -> pd.DataFrame:
    connection.register("sample_symbols", pd.DataFrame({"symbol": list(sample)}))
    columns = """
        trade_date, symbol, open, high, low, close, preclose, volume, amount,
        trade_status, is_st, up_limit_price, down_limit_price,
        buy_blocked_open, sell_blocked_open, bar_valid, trading_state_valid,
        corporate_action_valid, market_rule_valid, historical_identity_valid,
        hard_valid, current_day_data_tradable, available_at, snapshot_id,
        corporate_action_count, corporate_action_ids, corporate_action_blocking,
        corporate_action_problems, corporate_action_available_date,
        share_multiplier, cash_per_share,
        rights_ratio, rights_price
    """
    frame = connection.execute(
        f"""
        SELECT {columns}
        FROM read_parquet(?) d
        INNER JOIN sample_symbols s USING(symbol)
        WHERE trade_date BETWEEN ? AND ?
        ORDER BY trade_date, symbol
        """,
        [paths, warmup_start, end],
    ).fetchdf()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    if frame.duplicated(["trade_date", "symbol"]).any():
        raise ValueError("CY-006 sample contains duplicate security-date rows")
    return frame


def load_market(path: Path) -> tuple[dict[date, dict[str, Any]], dict[str, Any]]:
    frame = pd.read_csv(path, dtype={"trade_date": str})
    required = {"trade_date", "open", "high", "low", "close"}
    if not required.issubset(frame.columns):
        raise ValueError(f"399102 input missing columns: {sorted(required - set(frame.columns))}")
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], format="%Y%m%d").dt.date
    if frame["trade_date"].duplicated().any():
        raise ValueError("399102 input contains duplicate dates")
    rows = {row["trade_date"]: row for row in frame.to_dict("records")}
    metadata = {
        "symbol": MARKET_ANCHOR,
        "rows": len(frame),
        "first_date": min(rows).isoformat(),
        "last_date": max(rows).isoformat(),
        "sha256": sha256_file(path),
    }
    return rows, metadata


def load_sessions(path: Path, start: date, end: date) -> list[date]:
    frame = pd.read_parquet(path, columns=["trade_date"])
    dates = pd.to_datetime(frame["trade_date"]).dt.date
    return sorted(set(day for day in dates if start <= day <= end))


def row_map(panel: pd.DataFrame) -> dict[date, dict[str, dict[str, Any]]]:
    result: dict[date, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in panel.to_dict("records"):
        result[row["trade_date"]][row["symbol"]] = row
    return dict(result)


def critical_row_valid(row: dict[str, Any] | None) -> bool:
    if row is None:
        return False
    trade_date = row.get("trade_date")
    available_at = row.get("available_at")
    causally_available = False
    if isinstance(trade_date, date) and available_at is not None and not pd.isna(available_at):
        completed_close = pd.Timestamp.combine(trade_date, datetime.min.time()).replace(
            hour=15
        )
        causally_available = pd.Timestamp(available_at) <= completed_close
    flags = (
        row.get("hard_valid") is True,
        row.get("bar_valid") is True,
        row.get("trading_state_valid") is True,
        row.get("corporate_action_valid") is True,
        row.get("market_rule_valid") is True,
        row.get("historical_identity_valid") is True,
        row.get("trade_status") == 1,
        row.get("current_day_data_tradable") is True,
        row.get("is_st") is False,
        row.get("corporate_action_blocking") is False,
        causally_available,
        finite_positive(row.get("close")),
        finite_positive(row.get("volume")),
        row.get("amount") is not None and math.isfinite(float(row["amount"])) and float(row["amount"]) >= 0,
    )
    return all(flags)


def contiguous_tail(dates: list[date], sessions: list[date], session_index: int, length: int) -> bool:
    if session_index + 1 < length or len(dates) < length:
        return False
    return dates[-length:] == sessions[session_index - length + 1 : session_index + 1]


def schedule_target_set(
    *,
    desired: tuple[str, ...],
    previous: tuple[str, ...],
    positions: dict[str, Position],
    pending: dict[str, PendingOrder],
    signal_date: date,
    reason: str,
    config: ChinNextV1Config,
) -> None:
    weights = desired_target_weights(desired, config)
    relevant = set(previous) | set(desired) | set(positions) | set(pending)
    for symbol in sorted(relevant):
        target = weights.get(symbol, 0.0)
        if target == 0.0 and symbol not in positions:
            pending.pop(symbol, None)
            continue
        existing = pending.get(symbol)
        if existing is not None and existing.target_weight == target:
            # A failed order is sticky in both intent and audit lineage. An
            # unrelated later set change must not relabel its original signal.
            continue
        pending[symbol] = PendingOrder(symbol, target, signal_date, reason)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    text = "".join(json.dumps(json_value(row), ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    atomic_text(path, text)


def fmt_pct(value: float | None) -> str:
    return "NA" if value is None else f"{value:.4%}"


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.start >= args.end:
        raise ValueError("smoke start must precede end")
    config = ChinNextV1Config()
    pit_membership_path = getattr(args, "pit_membership", None)
    pit_mode = pit_membership_path is not None
    if pit_mode:
        survivors, pit_membership, pit_metadata = load_pit_membership(
            Path(pit_membership_path), args.start, args.end
        )
        survivor_names: dict[str, str] = {}
    else:
        survivors, survivor_names = load_survivors(args.survivor)
        pit_membership = {}
        pit_metadata = None
    market_rows, market_metadata = load_market(args.market)
    if min(market_rows) > args.start or max(market_rows) < args.end:
        raise ValueError("exact 399102.SZ input does not cover smoke range")
    paths = daily_glob(args.daily_root, date(2018, 1, 1), args.end)
    connection = duckdb.connect()
    candidates = history_candidates(connection, paths, survivors, args.start, config)
    full_survivor = bool(getattr(args, "full_survivor", False))
    sample = (
        tuple(survivors)
        if full_survivor
        else deterministic_equidistant_sample(candidates["symbol"].tolist(), args.sample_size)
    )
    warmup_start = date(args.start.year - 1, 1, 1)
    panel = load_sample_panel(connection, paths, sample, warmup_start, args.end)
    sessions = load_sessions(args.calendar, warmup_start, args.end)
    simulation_sessions = [day for day in sessions if args.start <= day <= args.end]
    if not simulation_sessions:
        raise ValueError("explicit trade calendar has no sessions in smoke range")
    if pit_mode and set(pit_membership) != set(simulation_sessions):
        missing = sorted(set(simulation_sessions) - set(pit_membership))
        extra = sorted(set(pit_membership) - set(simulation_sessions))
        raise ValueError(
            f"PIT membership/session coverage mismatch; missing={missing[:5]}, extra={extra[:5]}"
        )
    rows_by_date = row_map(panel)

    histories_close: dict[str, list[float]] = {symbol: [] for symbol in sample}
    histories_volume: dict[str, list[float]] = {symbol: [] for symbol in sample}
    histories_amount: dict[str, list[float]] = {symbol: [] for symbol in sample}
    histories_dates: dict[str, list[date]] = {symbol: [] for symbol in sample}
    market_closes: list[float] = []
    market_dates: list[date] = []
    positions: dict[str, Position] = {}
    pending: dict[str, PendingOrder] = {}
    forced_exits: set[str] = set()
    planned_members: tuple[str, ...] = ()
    last_prices: dict[str, float] = {}
    cash = float(args.initial_cash)
    transaction_cost_rate = config.transaction_cost_bps / 10_000.0

    counts: Counter[str] = Counter()
    eligibility_counts: Counter[str] = Counter()
    daily_failure_counts: Counter[str] = Counter()
    events: list[dict[str, Any]] = []
    executions: list[dict[str, Any]] = []
    sell_leg_returns: list[float] = []
    completed_round_trip_returns: list[float] = []
    realized_pnl_by_symbol: dict[str, float] = defaultdict(float)
    daily_nav: list[dict[str, Any]] = []
    total_traded_notional = 0.0
    action_blocked_held: list[dict[str, Any]] = []
    usable_symbols: set[str] = set()
    history_valid_symbols: set[str] = set()
    liquidity_valid_symbols: set[str] = set()

    all_sessions_index = {day: index for index, day in enumerate(sessions)}

    for day in sessions:
        day_rows = rows_by_date.get(day, {})

        # Corporate actions are effective in the new price/share coordinate at
        # this session.  Rebase only past history; today's raw bar is appended later.
        for symbol, row in sorted(day_rows.items()):
            action_count = int(row.get("corporate_action_count") or 0)
            if action_count <= 0:
                continue
            multiplier = finite_or_default(row.get("share_multiplier"), 1.0)
            cash_per_share = finite_or_default(row.get("cash_per_share"), 0.0)
            blocking = row.get("corporate_action_blocking") is not False or row.get("corporate_action_valid") is not True
            rights = finite_or_default(row.get("rights_ratio"), 0.0)
            action_available = row.get("corporate_action_available_date")
            action_visible = (
                action_available is not None
                and not pd.isna(action_available)
                and pd.Timestamp(action_available).date() <= day
            )
            if blocking or not action_visible or rights != 0.0 or multiplier <= 0 or not all(
                math.isfinite(value) for value in (multiplier, cash_per_share, rights)
            ):
                counts["corporate_action_blocked"] += 1
                if symbol in positions:
                    action_blocked_held.append(
                        {"trade_date": day, "symbol": symbol, "problems": row.get("corporate_action_problems")}
                    )
                continue
            if multiplier != 1.0 or cash_per_share != 0.0:
                histories_close[symbol] = [
                    (value - cash_per_share) / multiplier for value in histories_close[symbol]
                ]
                histories_volume[symbol] = [value * multiplier for value in histories_volume[symbol]]
                if symbol in positions:
                    position = positions[symbol]
                    dividend = position.shares * cash_per_share
                    cash += dividend
                    position.dividends += dividend
                    position.shares = round(position.shares * multiplier)
                counts["corporate_actions_applied"] += 1
                events.append(
                    {
                        "event": "CORPORATE_ACTION_APPLIED",
                        "trade_date": day,
                        "symbol": symbol,
                        "share_multiplier": multiplier,
                        "cash_per_share": cash_per_share,
                    }
                )

        if args.start <= day <= args.end:
            # Open execution: exits/reductions before entries/top-ups. Failed
            # attempts remain in pending and are retried on the next session.
            def open_nav() -> float:
                value = cash
                for held_symbol, position in positions.items():
                    row = day_rows.get(held_symbol)
                    price = float(row["open"]) if row is not None and finite_positive(row.get("open")) else last_prices.get(held_symbol)
                    if price is None:
                        raise RuntimeError(f"no causal valuation price for held {held_symbol} on {day}")
                    value += position.shares * price
                return value

            ordered_pending = sorted(
                pending,
                key=lambda symbol: (0 if pending[symbol].target_weight == 0 else 1, symbol),
            )
            for symbol in ordered_pending:
                order = pending.get(symbol)
                if order is None:
                    continue
                position = positions.get(symbol)
                nav_before = open_nav()
                row = day_rows.get(symbol)
                current_value = 0.0
                if position is not None:
                    reference = float(row["open"]) if row is not None and finite_positive(row.get("open")) else last_prices.get(symbol)
                    if reference is None:
                        counts["failed_open_execution"] += 1
                        continue
                    current_value = position.shares * reference
                target_value = order.target_weight * nav_before
                difference = target_value - current_value
                if order.target_weight == 0.0 and position is None:
                    pending.pop(symbol, None)
                    forced_exits.discard(symbol)
                    continue
                if abs(difference) < 1e-8:
                    pending.pop(symbol, None)
                    continue
                side = "BUY" if difference > 0 else "SELL"
                if pit_mode and side == "BUY":
                    listing_age = pit_membership[day].get(symbol)
                    if listing_age is None or listing_age < config.min_completed_observations:
                        raise RuntimeError(
                            f"pending buy is outside authorized PIT membership/age on {day}: {symbol}"
                        )
                decision = decide_next_open_fill(
                    signal_date=order.signal_date,
                    execution_date=day,
                    side=side,
                    row=row,
                    acquisition_date=position.acquisition_date if position is not None else None,
                )
                base_execution = {
                    "signal_date": order.signal_date,
                    "execution_date": day,
                    "signal_reason": order.signal_reason,
                    "execution_open": None if row is None else row.get("open"),
                    "symbol": symbol,
                    "side": side,
                    "target_weight": order.target_weight,
                    "t1_status": decision.t1_status,
                    "status": decision.reason,
                    "snapshot_id": None if row is None else row.get("snapshot_id"),
                }
                if not decision.filled or decision.price is None:
                    counts["failed_open_execution"] += 1
                    if decision.reason == "T1_BLOCKED":
                        counts["t1_execution_blocked"] += 1
                    executions.append(base_execution)
                    continue
                price = decision.price
                if side == "BUY":
                    new_position = position is None
                    budget = min(difference, cash / (1.0 + transaction_cost_rate))
                    shares = math.floor(budget / price / 100.0) * 100.0
                    if shares <= 0:
                        pending.pop(symbol, None)
                        base_execution["status"] = "BELOW_ONE_BOARD_LOT"
                        executions.append(base_execution)
                        continue
                    notional = shares * price
                    cost = notional * transaction_cost_rate
                    cash -= notional + cost
                    if position is None:
                        positions[symbol] = Position(
                            shares=shares,
                            cost_basis=notional + cost,
                            acquisition_date=day,
                            entry_signal_date=order.signal_date,
                            cycle_buy_cost=notional + cost,
                        )
                    else:
                        position.shares += shares
                        position.cost_basis += notional + cost
                        position.cycle_buy_cost += notional + cost
                        position.acquisition_date = day  # conservative minimal T+1 ledger
                    total_traded_notional += notional
                    counts["buy_fills"] += 1
                    base_execution.update(
                        {
                            "status": "FILLED",
                            "execution_price": price,
                            "shares": shares,
                            "notional": notional,
                            "cost": cost,
                            "new_position": new_position,
                            "rebalance_buy_leg": not new_position,
                        }
                    )
                else:
                    assert position is not None
                    if order.target_weight == 0.0:
                        shares = position.shares
                    else:
                        shares = min(position.shares, math.floor((-difference) / price / 100.0) * 100.0)
                    if shares <= 0:
                        pending.pop(symbol, None)
                        base_execution["status"] = "BELOW_ONE_BOARD_LOT"
                        executions.append(base_execution)
                        continue
                    before_shares = position.shares
                    proportion = shares / before_shares
                    allocated_cost = position.cost_basis * proportion
                    allocated_dividend = position.dividends * proportion
                    notional = shares * price
                    cost = notional * transaction_cost_rate
                    proceeds = notional - cost
                    cash += proceeds
                    realized_pnl = proceeds + allocated_dividend - allocated_cost
                    trade_return = realized_pnl / allocated_cost
                    sell_leg_returns.append(trade_return)
                    realized_pnl_by_symbol[symbol] += realized_pnl
                    position.cycle_realized_pnl += realized_pnl
                    position.shares -= shares
                    position.cost_basis -= allocated_cost
                    position.dividends -= allocated_dividend
                    full_exit = position.shares < 1e-9
                    if full_exit:
                        round_trip_return = (
                            position.cycle_realized_pnl / position.cycle_buy_cost
                        )
                        completed_round_trip_returns.append(round_trip_return)
                        positions.pop(symbol)
                        forced_exits.discard(symbol)
                    total_traded_notional += notional
                    counts["sell_fills"] += 1
                    base_execution.update(
                        {
                            "status": "FILLED",
                            "execution_price": price,
                            "shares": shares,
                            "notional": notional,
                            "cost": cost,
                            "trade_return": trade_return,
                            "realized_pnl": realized_pnl,
                            "full_exit": full_exit,
                            "completed_round_trip": full_exit,
                            "rebalance_sell_leg": not full_exit,
                            "round_trip_return": round_trip_return if full_exit else None,
                        }
                    )
                pending.pop(symbol, None)
                executions.append(base_execution)

        # Append only this completed session's bar after all open decisions.
        for symbol in sample:
            row = day_rows.get(symbol)
            if row is None:
                continue
            # A hard-invalid observation is a gap, not a usable history point.
            # This makes subsequent rolling windows fail closed until the gap has
            # fully left the required contiguous window.
            if critical_row_valid(row):
                histories_dates[symbol].append(day)
                histories_close[symbol].append(float(row["close"]))
                histories_volume[symbol].append(float(row["volume"]))
                histories_amount[symbol].append(float(row["amount"]))
                last_prices[symbol] = float(row["close"])

        market_row = market_rows.get(day)
        if market_row is not None and finite_positive(market_row.get("close")):
            market_closes.append(float(market_row["close"]))
            market_dates.append(day)

        if not (args.start <= day <= args.end):
            continue

        session_index = all_sessions_index[day]
        basic_eligible: list[str] = []
        history_valid_today = 0
        liquidity_valid_today = 0
        active_membership = pit_membership.get(day, {}) if pit_mode else None
        for symbol in sample:
            row = day_rows.get(symbol)
            dates = histories_dates[symbol]
            membership_ok = (
                not pit_mode
                or (
                    active_membership is not None
                    and active_membership.get(symbol, 0) >= config.min_completed_observations
                )
            )
            history_ok = (
                membership_ok
                and len(dates) >= config.min_completed_observations
                and contiguous_tail(dates, sessions, session_index, 121)
            )
            if history_ok:
                history_valid_today += 1
                history_valid_symbols.add(symbol)
            liquidity_ok = (
                history_ok
                and contiguous_tail(dates, sessions, session_index, config.turnover20_days)
                and len(histories_amount[symbol]) >= config.turnover20_days
                and fmean(histories_amount[symbol][-config.turnover20_days :]) >= config.turnover20_min_cny
            )
            if liquidity_ok:
                liquidity_valid_today += 1
                liquidity_valid_symbols.add(symbol)
            if history_ok and liquidity_ok and critical_row_valid(row):
                basic_eligible.append(symbol)
                usable_symbols.add(symbol)
            else:
                if pit_mode and active_membership is not None and symbol not in active_membership:
                    daily_failure_counts["outside_pit_membership"] += 1
                elif pit_mode and active_membership is not None and active_membership[symbol] < config.min_completed_observations:
                    daily_failure_counts["listing_age_below_180"] += 1
                elif row is None:
                    daily_failure_counts["missing_daily_row"] += 1
                elif row.get("is_st") is True:
                    daily_failure_counts["known_risk_warning"] += 1
                elif not finite_positive(row.get("close")) or not finite_positive(
                    row.get("volume")
                ):
                    daily_failure_counts["invalid_price_or_volume"] += 1
                elif row.get("trade_status") != 1 or row.get(
                    "current_day_data_tradable"
                ) is not True:
                    daily_failure_counts["suspended_or_not_tradable"] += 1
                elif not history_ok:
                    daily_failure_counts["insufficient_or_noncontiguous_history"] += 1
                elif not liquidity_ok:
                    daily_failure_counts["turnover20_below_threshold"] += 1
                else:
                    daily_failure_counts["other_hard_validity_failure"] += 1
        eligibility_counts["history_valid_daily_sum"] += history_valid_today
        eligibility_counts["liquidity_valid_daily_sum"] += liquidity_valid_today
        eligibility_counts["final_eligible_daily_sum"] += len(basic_eligible)
        eligibility_counts["daily_count"] += 1

        market_state = market_gate_state(market_closes, config)
        market_contiguous = contiguous_tail(
            market_dates,
            sessions,
            session_index,
            config.market_ma + config.market_exit_confirm - 1,
        )
        if (
            market_row is None
            or not finite_positive(market_row.get("close"))
            or not market_contiguous
        ):
            market_state = {"valid": False, "entry_permission": False, "normal_exit": False, "emergency_exit": False}
            counts["market_missing_days"] += 1

        exit_reason_parts: list[str] = []
        if market_state["normal_exit"]:
            exit_reason_parts.append("MARKET_MA20_X2")
        if market_state["emergency_exit"]:
            exit_reason_parts.append("MARKET_CLOSE_LT_MA20_X0.96")

        for symbol in sorted(positions):
            if own_exit_signal(histories_close[symbol], config):
                if symbol not in forced_exits:
                    counts["individual_exit_signals"] += 1
                    events.append({"event": "INDIVIDUAL_EXIT_SIGNAL", "signal_date": day, "symbol": symbol, "reason": "MA30_X2"})
                forced_exits.add(symbol)
                if positions[symbol].acquisition_date == day:
                    counts["t1_blocked_exit_signal"] += 1
                    events.append(
                        {
                            "event": "EXIT_SIGNAL_BLOCKED_BY_T1",
                            "signal_date": day,
                            "symbol": symbol,
                            "acquisition_date": day,
                            "execution_deferred_to": "NEXT_SELLABLE_OPEN",
                        }
                    )

        if exit_reason_parts:
            forced_exits.update(planned_members)
            desired = ()
            counts["market_exit_signal_days"] += 1
            membership_reason = "+".join(exit_reason_parts)
        else:
            rs = build_rs_table(histories_close, basic_eligible, config)
            candidate_symbols: list[str] = []
            committed = set(planned_members)
            for symbol in basic_eligible:
                if symbol in committed or symbol in forced_exits:
                    continue
                price_pass, full = entry_price_structure(histories_close[symbol], config)
                if not price_pass:
                    continue
                counts["entry_signal"] += 1
                minimum = minvol_diagnostic(histories_close[symbol], histories_volume[symbol], config)
                breakout = breakout_volume_diagnostic(histories_volume[symbol], config)
                if minimum.passed:
                    counts["minvol_pass"] += 1
                if breakout.passed:
                    counts["breakout_volume_shadow_pass"] += 1
                events.append(
                    {
                        "event": "ENTRY_SIGNAL_EVALUATED",
                        "signal_date": day,
                        "symbol": symbol,
                        "price_structure_pass": price_pass,
                        "full40": asdict(full),
                        "minvol": asdict(minimum),
                        "breakout_volume_mode": BREAKOUT_VOLUME_MODE,
                        "breakout_volume": asdict(breakout),
                        "rs": rs.get(symbol),
                    }
                )
                if minimum.passed and symbol in rs:
                    candidate_symbols.append(symbol)
            ranked = sort_candidates(candidate_symbols, rs)
            entry_allowed = market_state["valid"] and market_state["entry_permission"]
            if entry_allowed:
                desired = select_no_replacement_members(
                    planned_members, forced_exits, ranked, config
                )
            else:
                desired = select_no_replacement_members(
                    planned_members, forced_exits, [], config
                )
            membership_reason = "SET_CHANGE_ENTRY_OR_INDIVIDUAL_EXIT"

        if set_change_required(planned_members, desired):
            previous = planned_members
            schedule_target_set(
                desired=desired,
                previous=previous,
                positions=positions,
                pending=pending,
                signal_date=day,
                reason=membership_reason,
                config=config,
            )
            planned_members = desired
            counts["set_changes"] += 1
            events.append(
                {
                    "event": "DESIRED_SET_CHANGED",
                    "signal_date": day,
                    "previous": previous,
                    "desired": desired,
                    "reason": membership_reason,
                }
            )

        value = cash
        invested = 0.0
        stale = 0
        for symbol, position in positions.items():
            row = day_rows.get(symbol)
            if row is not None and finite_positive(row.get("close")):
                price = float(row["close"])
            else:
                price = last_prices.get(symbol)
                stale += 1
            if price is None:
                raise RuntimeError(f"no causal close valuation for held {symbol} on {day}")
            market_value = position.shares * price
            value += market_value
            invested += market_value
        counts["stale_held_valuations"] += stale
        daily_nav.append(
            {
                "trade_date": day,
                "nav": value,
                "cash": cash,
                "holdings": len(positions),
                "invested_ratio": 0.0 if value <= 0 else invested / value,
                "pending_orders": len(pending),
                "planned_members": len(planned_members),
                "market_entry_permission": market_state["entry_permission"],
                "market_normal_exit": market_state["normal_exit"],
                "market_emergency_exit": market_state["emergency_exit"],
                "basic_eligible": len(basic_eligible),
            }
        )

    if action_blocked_held:
        raise RuntimeError(
            "unmodeled corporate action affected a held symbol; fail closed: "
            + json.dumps(json_value(action_blocked_held[:5]), ensure_ascii=False)
        )
    if len(daily_nav) != len(simulation_sessions):
        raise RuntimeError("NAV rows do not match explicit simulation sessions")

    performance = performance_summary([row["nav"] for row in daily_nav])
    sell_leg_metrics = trade_return_summary(sell_leg_returns)
    round_trip_metrics = trade_return_summary(completed_round_trip_returns)
    daily_count = eligibility_counts["daily_count"]
    average_nav = fmean(row["nav"] for row in daily_nav)
    event_path = args.output_dir / "event_ledger.jsonl"
    execution_path = args.output_dir / "execution_ledger.jsonl"
    nav_path = args.output_dir / "daily_nav.jsonl"
    write_jsonl(event_path, events)
    write_jsonl(execution_path, executions)
    write_jsonl(nav_path, daily_nav)

    start_rows = rows_by_date.get(args.start, {})
    current_name_risk_count = (
        0
        if pit_mode
        else sum("ST" in survivor_names.get(symbol, "").upper() for symbol in sample)
    )
    data_found_symbols = set(panel["symbol"].unique())
    known_risk_symbols = set(panel.loc[panel["is_st"].eq(True), "symbol"].unique())
    missing_symbols = set(sample) - data_found_symbols
    insufficient_history_symbols = data_found_symbols - history_valid_symbols
    turnover_failure_symbols = history_valid_symbols - liquidity_valid_symbols
    final_other_failure_symbols = liquidity_valid_symbols - usable_symbols
    entry_buy_count = sum(
        row.get("status") == "FILLED"
        and row.get("side") == "BUY"
        and row.get("new_position") is True
        for row in executions
    )
    rebalance_buy_count = counts["buy_fills"] - entry_buy_count
    completed_round_trip_count = sum(
        row.get("status") == "FILLED" and row.get("completed_round_trip") is True
        for row in executions
    )
    rebalance_sell_count = counts["sell_fills"] - completed_round_trip_count
    pnl_contribution = dict(realized_pnl_by_symbol)
    for symbol, position in positions.items():
        market_value = position.shares * last_prices[symbol]
        pnl_contribution[symbol] = pnl_contribution.get(symbol, 0.0) + (
            market_value + position.dividends - position.cost_basis
        )
    summary: dict[str, Any] = {
        "warning": (
            "AUTHORIZED FROZEN PIT-B REPLAY / RECORD-LEVEL AVAILABLE_AT UNAVAILABLE"
            if pit_mode
            else SURVIVOR_WARNING
        ),
        "research_mode": RESEARCH_MODE,
        "configuration": config.to_dict(),
        "data": {
            **(
                {"pit_membership": pit_metadata, "current_survivor_fallback": False}
                if pit_mode
                else {
                    "survivor_manifest": str(args.survivor),
                    "survivor_manifest_sha256": sha256_file(args.survivor),
                }
            ),
            "daily_root": str(args.daily_root),
            "calendar": str(args.calendar),
            "market_anchor": market_metadata,
            "market_gate_active": True,
            "market_gate_reason": "exact QMT 399102.SZ daily history covers the full smoke range",
            "execution_limit_model": EXECUTION_LIMIT_MODEL,
            "risk_warning_model": (
                "known CY-006 is_st=true excluded by daily eligibility; "
                "complete historical risk-warning taxonomy is UNVERIFIED"
            ),
        },
        "sample": {
            "selection_rule": (
                "authorized frozen daily PIT membership with listing age >=180; no survivor fallback"
                if pit_mode
                else "all manifest current survivors; daily symbol-level fail closed"
                if full_survivor
                else "current-survivor symbols with >=180 pre-start valid completed observations, "
                "sorted by symbol, then 50 deterministic equidistant indices; no return outcome used"
            ),
            "full_survivor_mode": full_survivor,
            "pit_membership_mode": pit_mode,
            "symbols": sample,
            "date_range": [args.start, args.end],
            "raw_universe_count": len(survivors),
            "history_candidate_count": len(candidates),
            "raw_sample_count": len(sample),
            "usable_sample_count": len(usable_symbols),
            "data_found_count": len(data_found_symbols),
            "history_valid_count": len(history_valid_symbols),
            "liquidity_valid_count": len(liquidity_valid_symbols),
            "final_eligible_count": len(usable_symbols),
            "failure_reason_counts": {
                "missing_data": len(missing_symbols),
                "insufficient_history": len(insufficient_history_symbols),
                "turnover_failure": len(turnover_failure_symbols),
                "known_risk_warning_without_any_eligible_day": len(
                    final_other_failure_symbols & known_risk_symbols
                ),
                "other_daily_validity_failure": len(
                    final_other_failure_symbols - known_risk_symbols
                ),
            },
            "daily_failure_reason_counts": dict(sorted(daily_failure_counts.items())),
            "known_risk_warning_symbol_count": len(known_risk_symbols),
            "sample_current_name_st_count": current_name_risk_count,
            "start_row_count": len(start_rows),
            "average_history_valid": eligibility_counts["history_valid_daily_sum"] / daily_count,
            "average_liquidity_valid": eligibility_counts["liquidity_valid_daily_sum"] / daily_count,
            "average_final_eligible": eligibility_counts["final_eligible_daily_sum"] / daily_count,
        },
        "signals": {
            "entry_signal_count": counts["entry_signal"],
            "price_structure_signal_count": counts["entry_signal"],
            "minvol_pass_count": counts["minvol_pass"],
            "final_entry_candidate_count": counts["minvol_pass"],
            "breakout_volume_shadow_pass_count": counts["breakout_volume_shadow_pass"],
            "individual_exit_signal_count": counts["individual_exit_signals"],
            "market_exit_signal_days": counts["market_exit_signal_days"],
            "set_change_count": counts["set_changes"],
        },
        "execution": {
            "buy_fill_count": counts["buy_fills"],
            "entry_buy_execution_count": entry_buy_count,
            "rebalance_buy_leg_count": rebalance_buy_count,
            "sell_fill_count": counts["sell_fills"],
            "completed_round_trip_count": completed_round_trip_count,
            "rebalance_sell_leg_count": rebalance_sell_count,
            "t1_blocked_exit_count": counts["t1_blocked_exit_signal"],
            "t1_execution_blocked_count": counts["t1_execution_blocked"],
            "failed_open_execution_count": counts["failed_open_execution"],
            "turnover": total_traded_notional / average_nav,
            "transaction_cost_bps_per_side": config.transaction_cost_bps,
            "board_lot": 100,
            "rank_replacement": RANK_REPLACEMENT,
        },
        "portfolio": {
            "average_holdings": fmean(row["holdings"] for row in daily_nav),
            "max_holdings": max(row["holdings"] for row in daily_nav),
            "average_invested_ratio": fmean(row["invested_ratio"] for row in daily_nav),
            "ending_holdings": sorted(positions),
            "ending_pending_orders": sorted(pending),
            "sell_leg_return_metrics": sell_leg_metrics,
            "pnl_contribution_by_symbol": dict(sorted(pnl_contribution.items())),
            **performance,
            **round_trip_metrics,
        },
        "audit": {
            "events": len(events),
            "executions": len(executions),
            "corporate_actions_applied": counts["corporate_actions_applied"],
            "corporate_actions_blocked": counts["corporate_action_blocked"],
            "stale_held_valuation_count": counts["stale_held_valuations"],
            "event_ledger": str(event_path),
            "event_ledger_sha256": sha256_file(event_path),
            "execution_ledger": str(execution_path),
            "execution_ledger_sha256": sha256_file(execution_path),
            "daily_nav": str(nav_path),
            "daily_nav_sha256": sha256_file(nav_path),
        },
    }
    write_json(args.summary, summary)
    write_report(args.report, summary)
    return summary


def write_report(path: Path, summary: dict[str, Any]) -> None:
    sample = summary["sample"]
    signals = summary["signals"]
    execution = summary["execution"]
    portfolio = summary["portfolio"]
    data = summary["data"]
    audit = summary["audit"]
    symbol_lines = "\n".join(
        ", ".join(sample["symbols"][index : index + 10])
        for index in range(0, len(sample["symbols"]), 10)
    )
    report = f"""# ChinNext V1 exploratory smoke replay

> **{SURVIVOR_WARNING}**
>
> These are exploratory, survivor-biased, small-sample diagnostics. They are not
> an unbiased historical backtest and are not valid as final performance claims.

## Run identity

- RESEARCH_MODE: `{RESEARCH_MODE}`
- SAMPLE_SYMBOLS:

```text
{symbol_lines}
```

- DATE_RANGE: `{sample['date_range'][0]} .. {sample['date_range'][1]}`
- RAW_UNIVERSE_COUNT: `{sample['raw_universe_count']}` current survivors
- HISTORY_CANDIDATE_COUNT: `{sample['history_candidate_count']}`
- RAW_SAMPLE_COUNT: `{sample['raw_sample_count']}`
- USABLE_SAMPLE_COUNT: `{sample['usable_sample_count']}`
- SAMPLE_SELECTION: {sample['selection_rule']}

Selection is based on pre-run history availability and symbol ordering only. No
post-run return or signal outcome is used. The replay runs only this sample, not
the full current-survivor universe.

## Data and market gate

- MARKET_GATE_ACTIVE: `YES`
- MARKET_GATE_REASON: {data['market_gate_reason']}
- MARKET_ANCHOR: `{data['market_anchor']['symbol']}` (QMT exact identity, no fallback)
- MARKET_INPUT_SHA256: `{data['market_anchor']['sha256']}`
- EXECUTION_LIMIT_MODEL: `{data['execution_limit_model']}`
- RISK_WARNING_MODEL: {data['risk_warning_model']}
- AVERAGE_HISTORY_VALID: `{sample['average_history_valid']:.2f}` / day
- AVERAGE_LIQUIDITY_VALID: `{sample['average_liquidity_valid']:.2f}` / day
- AVERAGE_FINAL_ELIGIBLE: `{sample['average_final_eligible']:.2f}` / day

`PARTIAL` means CY-006's known daily trade status, exact open-limit block flags,
validity flags and missing/invalid opens are enforced, but the replay has no order
book/queue model. A blocked or invalid open is never silently filled. Historical
`is_st=true` is excluded, but the local evidence does not prove complete coverage
of every historical risk-warning subtype; this report does not claim it does.

## Signal diagnostics

- ENTRY_SIGNAL_COUNT: `{signals['entry_signal_count']}`
- MINVOL_PASS_COUNT: `{signals['minvol_pass_count']}`
- BREAKOUT_VOLUME_SHADOW_PASS_COUNT: `{signals['breakout_volume_shadow_pass_count']}`
- BREAKOUT_VOLUME_MODE: `{BREAKOUT_VOLUME_MODE}` (logged, not an entry blocker)
- INDIVIDUAL_EXIT_SIGNAL_COUNT: `{signals['individual_exit_signal_count']}`
- MARKET_EXIT_SIGNAL_DAYS: `{signals['market_exit_signal_days']}`
- SET_CHANGE_COUNT: `{signals['set_change_count']}`
- RANK_REPLACEMENT: `{RANK_REPLACEMENT}`

Signals use completed close t only. B60, FULL40, MINVOL, breakout-volume and RS
windows are causal; orders first become eligible at a later session open.

## Trading and portfolio results

> **EXPLORATORY / SURVIVOR-BIASED / SMALL SAMPLE**

- ENTRY_BUY_EXECUTION_COUNT: `{execution['entry_buy_execution_count']}`
- REBALANCE_BUY_LEG_COUNT: `{execution['rebalance_buy_leg_count']}`
- BUY_FILL_COUNT: `{execution['buy_fill_count']}`
- SELL_FILL_COUNT: `{execution['sell_fill_count']}`
- COMPLETED_ROUND_TRIP_COUNT: `{execution['completed_round_trip_count']}`
- REBALANCE_SELL_LEG_COUNT: `{execution['rebalance_sell_leg_count']}`
- WIN_RATE: `{fmt_pct(portfolio['win_rate'])}`
- AVERAGE_TRADE_RETURN: `{fmt_pct(portfolio['average_trade_return'])}`
- MEDIAN_TRADE_RETURN: `{fmt_pct(portfolio['median_trade_return'])}`
- TOTAL_RETURN: `{fmt_pct(portfolio['total_return'])}`
- ANNUALIZED_RETURN: `{fmt_pct(portfolio['annualized_return'])}`
- MAX_DRAWDOWN: `{fmt_pct(portfolio['max_drawdown'])}`
- AVERAGE_HOLDINGS: `{portfolio['average_holdings']:.3f}`
- MAX_HOLDINGS: `{portfolio['max_holdings']}`
- AVERAGE_INVESTED_RATIO: `{fmt_pct(portfolio['average_invested_ratio'])}`
- TURNOVER: `{execution['turnover']:.4f}x` (total traded notional / average NAV)
- T+1_BLOCKED_EXIT_COUNT: `{execution['t1_blocked_exit_count']}`
- T+1_EXECUTION_BLOCKED_COUNT: `{execution['t1_execution_blocked_count']}`
- FAILED_OPEN_EXECUTION_COUNT: `{execution['failed_open_execution_count']}`
- TRANSACTION_COST: `{execution['transaction_cost_bps_per_side']:.1f}` bps per side

Each desired member targets exactly 10%; with fewer than ten members the remainder
stays cash. Set-change-only prevents daily drift rebalancing. Failed executions
remain sticky pending. `acquisition_date` conservatively resets on any buy/top-up;
same-day exit signals are logged as `EXIT_SIGNAL_BLOCKED_BY_T1` and deferred.

## Corporate actions and audit trail

- CORPORATE_ACTIONS_APPLIED: `{audit['corporate_actions_applied']}`
- CORPORATE_ACTIONS_BLOCKED: `{audit['corporate_actions_blocked']}`
- STALE_HELD_VALUATIONS: `{audit['stale_held_valuation_count']}`
- EVENT_LEDGER: `{audit['event_ledger']}` (`{audit['event_ledger_sha256']}`)
- EXECUTION_LEDGER: `{audit['execution_ledger']}` (`{audit['execution_ledger_sha256']}`)
- DAILY_NAV: `{audit['daily_nav']}` (`{audit['daily_nav_sha256']}`)

Cash dividends and share multipliers use the repository's existing research replay
semantics. Past signal history is causally rebased into the post-action coordinate;
unmodeled blocking/rights actions affecting a held stock fail the run instead of
being normalized away.

## Limitations

1. The stock pool is today's survivor list projected backward. Delisted and former
   constituents are absent, so survivorship bias is structural and material.
2. The sample is only about 50 symbols; cross-sectional RS is therefore a sample RS,
   not a 1,398-stock or historical-PIT-universe RS.
3. Risk-warning coverage is incomplete, and current names are not treated as proof
   of historical state.
4. Daily open limit/tradability constraints are enforced, but there is no intraday
   queue, market-impact, or broker-level lot/sellability ledger.
5. Transaction costs are a fixed 10 bps per side; taxes, impact and borrow are not
   separately modeled. Unclosed positions remain marked at their last causal close.

The result is suitable only for deciding whether a stricter Phase 2 study is worth
doing. No parameter was optimized in this run.
"""
    atomic_text(path, report)


def main() -> int:
    args = parse_args()
    summary = run(args)
    print(
        json.dumps(
            json_value(
                {
                    "warning": SURVIVOR_WARNING,
                    "sample_size": summary["sample"]["raw_sample_count"],
                    "usable": summary["sample"]["usable_sample_count"],
                    "entry_signals": summary["signals"]["entry_signal_count"],
                    "completed_round_trips": summary["execution"]["completed_round_trip_count"],
                    "total_return": summary["portfolio"]["total_return"],
                    "report": str(args.report),
                }
            ),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
