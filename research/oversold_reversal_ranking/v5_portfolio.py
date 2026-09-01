#!/usr/bin/env python3
"""V5: finite-capital overlapping portfolio realization of the frozen V1-V4 lane."""

# SQL and accounting are intentionally explicit so chronology and cash flows remain auditable.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import sys
import tempfile
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any

import duckdb
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from research.oversold_reversal_ranking.v2_timing import (  # noqa: E402
    create_timing_tables,
)
from research.oversold_reversal_ranking.v3_risk_filter import (  # noqa: E402
    SEVERE_MAE_MAX,
    create_risk_tables,
    rows_as_dicts,
)
from research.oversold_reversal_ranking.v3_risk_filter import (  # noqa: E402
    semantic_checks as v3_semantic_checks,
)
from research.volume_exhaustion_bottom.experiment import (  # noqa: E402
    DEFAULT_CONFIG as PREDECESSOR_CONFIG,
)
from research.volume_exhaustion_bottom.experiment import (  # noqa: E402
    create_analysis_tables,
    json_default,
    validate_inputs,
)

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "reports"
INITIAL_NAV = 1.0
DAILY_TRANCHE_FRACTION = 1.0 / 20.0
HOLDING_SESSIONS = 20
SCHEDULED_EXIT_OFFSET = 21
# Execution-only scan; the run fails closed if any first legal sell open is not found.
# This is deliberately beyond the predecessor's +25 outcome window because a locked-limit
# position must be carried rather than silently dropped.
EXIT_SEARCH_END_OFFSET = 60
WARMUP_PRIOR_EVENTS = 250
STAMP_CHANGE_DATE = date(2023, 8, 28)

RAW_RISK_WEIGHTS = {1: 1.25, 2: 1.125, 3: 1.0, 4: 0.875, 5: 0.75}
POLICIES = ("EQUAL_SIZE", "RISK_AWARE_SIZE")
COST_MODES = ("GROSS", "BASE", "HIGH_COST")

# Set after the first frozen full run. No portfolio rule changed in response to this label.
VERDICT = "EVENT_ALPHA_COLLAPSES"
SINGLE_NEXT_STEP = "Run one outcome-blind clustered-signal capital-allocation study that preserves the frozen carrier and score, and tests whether a preregistered event-count-aware risk budget can overcome the entry-date dilution identified by V5 before transaction costs."


def _finite_float(value: Any) -> float:
    output = float(value)
    if not math.isfinite(output):
        raise RuntimeError(f"nonfinite portfolio value: {value!r}")
    return output


def create_portfolio_tables(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> None:
    """Build frozen event, execution-control, path, and calendar tables."""
    data_glob = config["data"]["parquet_glob"].replace("'", "''")
    con.execute(
        """
        CREATE TEMP TABLE v5_event_base AS
        SELECT row_number() OVER (ORDER BY e.trade_date, e.symbol) AS event_id,
               e.symbol, e.trade_date AS signal_date, e.trade_seq AS signal_seq,
               e.raw_next_date AS entry_date,
               1.0 / e.entry_scale AS entry_adjusted_open,
               e.risk_score, e.risk_q AS descriptive_risk_q,
               e.ret_20 AS v4_ret_20, e.mae_20 AS v4_mae_20,
               e.mfe_20 AS v4_mfe_20, e.trigger_signal,
               e.drawdown_60, e.industry, e.liquidity_tercile,
               e.market_segment
        FROM v3_events e
        ORDER BY e.trade_date, e.symbol
        """
    )
    con.execute(
        f"""
        CREATE TEMP TABLE v5_controls AS
        SELECT r.symbol, r.trade_date, r.sell_blocked_open
        FROM read_parquet('{data_glob}', hive_partitioning=true) r
        JOIN (
          SELECT DISTINCT p.symbol, p.trade_date
          FROM v5_event_base e
          JOIN analysis_rows p
            ON p.symbol=e.symbol
           AND p.trade_seq BETWEEN e.signal_seq+1 AND e.signal_seq+{EXIT_SEARCH_END_OFFSET}
        ) needed USING (symbol, trade_date)
        """
    )
    con.execute(
        f"""
        CREATE TEMP TABLE v5_exit_candidates AS
        SELECT e.event_id, p.trade_seq, p.trade_date,
               p.adjusted_close * p.open / p.close AS adjusted_open,
               NOT coalesce(c.sell_blocked_open, true) AS sellable_open,
               count(*) FILTER (
                 WHERE NOT coalesce(c.sell_blocked_open, true)
               ) OVER (
                 PARTITION BY e.event_id ORDER BY p.trade_seq
                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
               ) AS legal_rn
        FROM v5_event_base e
        JOIN analysis_rows p
          ON p.symbol=e.symbol
         AND p.trade_seq BETWEEN e.signal_seq+{SCHEDULED_EXIT_OFFSET}
                             AND e.signal_seq+{EXIT_SEARCH_END_OFFSET}
        LEFT JOIN v5_controls c
          ON c.symbol=p.symbol AND c.trade_date=p.trade_date
        """
    )
    con.execute(
        f"""
        CREATE TEMP TABLE v5_events AS
        SELECT e.*,
               scheduled.trade_date AS scheduled_exit_date,
               first_legal.trade_date AS first_legal_exit_date,
               first_legal.trade_seq-e.signal_seq-{SCHEDULED_EXIT_OFFSET}
                 AS expected_exit_delay_sessions,
               first_legal.adjusted_open AS executable_exit_adjusted_open
        FROM v5_event_base e
        LEFT JOIN v5_exit_candidates scheduled
          ON scheduled.event_id=e.event_id
         AND scheduled.trade_seq=e.signal_seq+{SCHEDULED_EXIT_OFFSET}
        LEFT JOIN v5_exit_candidates first_legal
          ON first_legal.event_id=e.event_id AND first_legal.legal_rn=1
         AND first_legal.sellable_open
        """
    )
    con.execute(
        f"""
        CREATE TEMP TABLE v5_prices AS
        SELECT DISTINCT p.symbol, p.trade_date,
               p.adjusted_close * p.open / p.close AS adjusted_open,
               p.adjusted_close,
               NOT coalesce(c.sell_blocked_open, true) AS sellable_open
        FROM v5_events e
        JOIN analysis_rows p
          ON p.symbol=e.symbol
         AND p.trade_seq BETWEEN e.signal_seq+1
                             AND e.signal_seq+{EXIT_SEARCH_END_OFFSET}
        LEFT JOIN v5_controls c
          ON c.symbol=p.symbol AND c.trade_date=p.trade_date
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE v5_calendar AS
        SELECT DISTINCT a.trade_date
        FROM analysis_rows a
        WHERE a.trade_date BETWEEN
          (SELECT min(entry_date) FROM v5_events)
          AND (SELECT max(first_legal_exit_date) FROM v5_events)
        ORDER BY a.trade_date
        """
    )


def assign_causal_buckets(
    events: list[dict[str, Any]], *, minimum_history: int = WARMUP_PRIOR_EVENTS
) -> list[dict[str, Any]]:
    """Assign prior-date-only empirical score buckets and frozen V4 raw weights."""
    ordered = sorted(events, key=lambda row: (row["signal_date"], row["symbol"]))
    history: list[float] = []
    output: list[dict[str, Any]] = []
    index = 0
    while index < len(ordered):
        signal_date = ordered[index]["signal_date"]
        end = index
        while end < len(ordered) and ordered[end]["signal_date"] == signal_date:
            end += 1
        same_date = ordered[index:end]
        prior_n = len(history)
        for original in same_date:
            row = dict(original)
            score = _finite_float(row["risk_score"])
            if prior_n < minimum_history:
                percentile = None
                risk_q = 3
                warmup = True
            else:
                percentile = bisect.bisect_right(history, score) / prior_n
                risk_q = min(5, max(1, math.ceil(percentile * 5.0)))
                warmup = False
            row.update(
                {
                    "causal_prior_event_n": prior_n,
                    "causal_percentile": percentile,
                    "causal_risk_q": risk_q,
                    "causal_raw_weight": RAW_RISK_WEIGHTS[risk_q],
                    "causal_warmup": warmup,
                }
            )
            output.append(row)
        for row in same_date:
            bisect.insort(history, _finite_float(row["risk_score"]))
        index = end
    return output


def buy_cost_rate(mode: str) -> float:
    if mode == "GROSS":
        return 0.0
    multiplier = 2.0 if mode == "HIGH_COST" else 1.0
    return multiplier * (3.0 + 5.0) / 10_000.0


def sell_cost_rate(trade_date: date, mode: str) -> float:
    if mode == "GROSS":
        return 0.0
    multiplier = 2.0 if mode == "HIGH_COST" else 1.0
    stamp_bps = 10.0 if trade_date < STAMP_CHANGE_DATE else 5.0
    return (multiplier * (3.0 + 5.0) + stamp_bps) / 10_000.0


def signal_count_bucket(n: int) -> str:
    if n == 0:
        return "0"
    if n == 1:
        return "1"
    if n <= 5:
        return "2-5"
    if n <= 20:
        return "6-20"
    return ">20"


def _price(
    prices: dict[tuple[str, date], dict[str, Any]], symbol: str, trade_date: date
) -> dict[str, Any] | None:
    return prices.get((symbol, trade_date))


def simulate_portfolio(
    *,
    policy: str,
    cost_mode: str,
    events: list[dict[str, Any]],
    prices: dict[tuple[str, date], dict[str, Any]],
    calendar: list[date],
    initial_nav: float = INITIAL_NAV,
) -> dict[str, Any]:
    """Replay one long-only policy with open executions and close NAV marks."""
    if policy not in POLICIES:
        raise ValueError(policy)
    if cost_mode not in COST_MODES:
        raise ValueError(cost_mode)

    signals: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event["entry_date"] is not None:
            signals[event["entry_date"]].append(event)
    for rows in signals.values():
        rows.sort(key=lambda row: (row["symbol"], row["event_id"]))

    cash = float(initial_nav)
    positions: dict[str, dict[str, Any]] = {}
    last_marks: dict[str, float] = {}
    daily: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    flow = {
        "signals": 0,
        "entered": 0,
        "overlapping_security_skips": 0,
        "missed_for_zero_cash": 0,
        "invalid_entry_price": 0,
        "cash_constrained_days": 0,
        "tranche_constrained_days": 0,
        "entry_days": 0,
        "one_signal_entry_days": 0,
        "multi_signal_entry_days": 0,
        "cost_scaled_days": 0,
    }
    daily_allocations: list[dict[str, Any]] = []

    for trade_date in calendar:
        opening_market_value = 0.0
        for symbol, lot in positions.items():
            price = _price(prices, symbol, trade_date)
            mark = (
                _finite_float(price["adjusted_open"])
                if price is not None
                else last_marks[symbol]
            )
            opening_market_value += lot["units"] * mark
        opening_nav = cash + opening_market_value
        if opening_nav <= 0:
            raise RuntimeError(f"nonpositive opening NAV on {trade_date}: {opening_nav}")

        exit_notional = 0.0
        exit_cost = 0.0
        exits_today = 0
        for symbol in sorted(list(positions)):
            lot = positions[symbol]
            if trade_date < lot["scheduled_exit_date"]:
                continue
            price = _price(prices, symbol, trade_date)
            if price is None or not price["sellable_open"]:
                continue
            exit_price = _finite_float(price["adjusted_open"])
            gross_proceeds = lot["units"] * exit_price
            cost = gross_proceeds * sell_cost_rate(trade_date, cost_mode)
            cash += gross_proceeds - cost
            exit_notional += gross_proceeds
            exit_cost += cost
            exits_today += 1
            lot.update(
                {
                    "actual_exit_date": trade_date,
                    "exit_adjusted_open": exit_price,
                    "exit_notional": gross_proceeds,
                    "exit_cost": cost,
                    "gross_trade_return": exit_price / lot["entry_adjusted_open"] - 1.0,
                    "net_trade_return": (gross_proceeds - cost)
                    / (lot["initial_notional"] + lot["entry_cost"])
                    - 1.0,
                    "realized_pnl": gross_proceeds
                    - cost
                    - lot["initial_notional"]
                    - lot["entry_cost"],
                    "holding_sessions": HOLDING_SESSIONS
                    + lot["exit_delay_sessions"],
                }
            )
            trades.append(lot)
            del positions[symbol]

        today_signals = signals.get(trade_date, [])
        flow["signals"] += len(today_signals)
        executable: list[dict[str, Any]] = []
        for event in today_signals:
            if event["symbol"] in positions:
                flow["overlapping_security_skips"] += 1
                continue
            price = _price(prices, event["symbol"], trade_date)
            if price is None or _finite_float(price["adjusted_open"]) <= 0:
                flow["invalid_entry_price"] += 1
                continue
            executable.append(event)

        requested_budget = DAILY_TRANCHE_FRACTION * opening_nav
        entry_notional = 0.0
        entry_cost = 0.0
        if executable:
            flow["entry_days"] += 1
            if len(executable) == 1:
                flow["one_signal_entry_days"] += 1
            else:
                flow["multi_signal_entry_days"] += 1
            if cash + 1e-15 < requested_budget:
                flow["cash_constrained_days"] += 1
            else:
                flow["tranche_constrained_days"] += 1
            cost_rate = buy_cost_rate(cost_mode)
            cash_notional_limit = cash / (1.0 + cost_rate)
            actual_budget = min(requested_budget, cash_notional_limit)
            pre_cost_cap = min(requested_budget, cash)
            if actual_budget + 1e-15 < pre_cost_cap:
                flow["cost_scaled_days"] += 1
            if actual_budget <= 1e-15:
                flow["missed_for_zero_cash"] += len(executable)
            else:
                if policy == "EQUAL_SIZE":
                    raw_weights = [1.0] * len(executable)
                else:
                    raw_weights = [
                        _finite_float(event["causal_raw_weight"])
                        for event in executable
                    ]
                weight_sum = sum(raw_weights)
                if weight_sum <= 0:
                    raise RuntimeError("nonpositive within-day risk weight sum")
                for event, raw_weight in zip(executable, raw_weights, strict=True):
                    notional = actual_budget * raw_weight / weight_sum
                    price = _price(prices, event["symbol"], trade_date)
                    assert price is not None
                    entry_price = _finite_float(price["adjusted_open"])
                    cost = notional * cost_rate
                    cash -= notional + cost
                    if cash < -1e-12:
                        raise RuntimeError(f"negative cash on {trade_date}: {cash}")
                    cash = max(cash, 0.0)
                    scheduled = event["scheduled_exit_date"]
                    if scheduled is None:
                        raise RuntimeError(f"missing scheduled exit: {event['event_id']}")
                    lot = {
                        **event,
                        "policy": policy,
                        "cost_mode": cost_mode,
                        "entry_adjusted_open": entry_price,
                        "initial_notional": notional,
                        "units": notional / entry_price,
                        "entry_cost": cost,
                        "signal_day_n": len(today_signals),
                        "signal_day_bucket": signal_count_bucket(len(today_signals)),
                        "entry_weight_of_opening_nav": notional / opening_nav,
                        "exit_delay_sessions": int(
                            event["expected_exit_delay_sessions"] or 0
                        ),
                    }
                    positions[event["symbol"]] = lot
                    entry_notional += notional
                    entry_cost += cost
                    flow["entered"] += 1
                daily_allocations.append(
                    {
                        "trade_date": trade_date,
                        "signals": len(today_signals),
                        "executable_signals": len(executable),
                        "opening_nav": opening_nav,
                        "requested_budget": requested_budget,
                        "actual_entry_notional": actual_budget,
                        "actual_budget_fraction_of_nav": actual_budget / opening_nav,
                        "cash_constrained": actual_budget + 1e-15 < requested_budget,
                    }
                )

        close_values = []
        for symbol, lot in positions.items():
            price = _price(prices, symbol, trade_date)
            if price is not None:
                last_marks[symbol] = _finite_float(price["adjusted_close"])
            if symbol not in last_marks:
                raise RuntimeError(f"missing close mark for {symbol} on {trade_date}")
            close_values.append(lot["units"] * last_marks[symbol])
        market_value = sum(close_values)
        close_nav = cash + market_value
        if close_nav <= 0 or cash < -1e-12:
            raise RuntimeError(f"invalid close accounting on {trade_date}")
        weights = sorted((value / close_nav for value in close_values), reverse=True)
        daily.append(
            {
                "trade_date": trade_date,
                "opening_nav": opening_nav,
                "cash": cash,
                "market_value": market_value,
                "nav": close_nav,
                "exposure": market_value / close_nav,
                "cash_weight": cash / close_nav,
                "concurrent_positions": len(positions),
                "largest_position_weight": weights[0] if weights else 0.0,
                "top5_concentration": sum(weights[:5]),
                "signals": len(today_signals),
                "entries": len(executable) if entry_notional > 0 else 0,
                "exits": exits_today,
                "entry_notional": entry_notional,
                "exit_notional": exit_notional,
                "entry_cost": entry_cost,
                "exit_cost": exit_cost,
                "total_cost": entry_cost + exit_cost,
            }
        )

    if positions:
        raise RuntimeError(f"open positions remain at final date: {sorted(positions)[:5]}")
    if flow["entered"] != len(trades):
        raise RuntimeError(f"entry/exit mismatch: {flow}, exits={len(trades)}")
    return {
        "policy": policy,
        "cost_mode": cost_mode,
        "initial_nav": initial_nav,
        "daily": daily,
        "trades": trades,
        "flow": flow,
        "daily_allocations": daily_allocations,
    }


def _daily_returns(daily: list[dict[str, Any]], starting_nav: float) -> np.ndarray:
    nav = np.asarray([starting_nav, *[row["nav"] for row in daily]], dtype=float)
    return nav[1:] / nav[:-1] - 1.0


def _drawdown(nav: np.ndarray) -> tuple[float, np.ndarray]:
    peaks = np.maximum.accumulate(nav)
    values = nav / peaks - 1.0
    return float(np.min(values)), values


def portfolio_metrics(simulation: dict[str, Any]) -> dict[str, Any]:
    daily = simulation["daily"]
    if not daily:
        raise RuntimeError("empty NAV series")
    start = _finite_float(simulation["initial_nav"])
    ending = _finite_float(daily[-1]["nav"])
    returns = _daily_returns(daily, start)
    years = len(daily) / 252.0
    cagr = ending ** (1.0 / years) - 1.0 if ending > 0 else -1.0
    volatility = float(np.std(returns, ddof=1) * math.sqrt(252.0))
    daily_std = float(np.std(returns, ddof=1))
    sharpe = (
        float(np.mean(returns) / daily_std * math.sqrt(252.0))
        if daily_std > 0
        else 0.0
    )
    max_drawdown, _ = _drawdown(
        np.asarray([start, *[row["nav"] for row in daily]], dtype=float)
    )
    total_traded = sum(
        row["entry_notional"] + row["exit_notional"] for row in daily
    )
    average_nav = float(np.mean([row["nav"] for row in daily]))
    total_cost = sum(row["total_cost"] for row in daily)
    gross_profit_before_cost = sum(
        trade["exit_notional"] - trade["initial_notional"]
        for trade in simulation["trades"]
    )
    return {
        "starting_nav": start,
        "ending_nav": ending,
        "cumulative_return": ending / start - 1.0,
        "cagr": cagr,
        "annualized_volatility": volatility,
        "max_drawdown": max_drawdown,
        "sharpe_like": sharpe,
        "calmar": cagr / abs(max_drawdown) if max_drawdown < 0 else None,
        "years": years,
        "trading_days": len(daily),
        "average_exposure": float(np.mean([row["exposure"] for row in daily])),
        "average_cash_weight": float(np.mean([row["cash_weight"] for row in daily])),
        "average_concurrent_positions": float(
            np.mean([row["concurrent_positions"] for row in daily])
        ),
        "maximum_concurrent_positions": max(
            row["concurrent_positions"] for row in daily
        ),
        "average_largest_position_weight": float(
            np.mean([row["largest_position_weight"] for row in daily])
        ),
        "maximum_largest_position_weight": max(
            row["largest_position_weight"] for row in daily
        ),
        "average_top5_concentration": float(
            np.mean([row["top5_concentration"] for row in daily])
        ),
        "maximum_top5_concentration": max(row["top5_concentration"] for row in daily),
        "entries": len(simulation["trades"]),
        "exits": len(simulation["trades"]),
        "average_holding_sessions": float(
            np.mean([trade["holding_sessions"] for trade in simulation["trades"]])
        ),
        "median_holding_sessions": float(
            median(trade["holding_sessions"] for trade in simulation["trades"])
        ),
        "total_turnover": total_traded / average_nav,
        "annualized_turnover": total_traded / average_nav / years,
        "total_cost": total_cost,
        "cost_as_fraction_of_gross_profit": (
            total_cost / gross_profit_before_cost if gross_profit_before_cost > 0 else None
        ),
        "minimum_cash": min(row["cash"] for row in daily),
        "maximum_nav_accounting_error": max(
            abs(row["nav"] - row["cash"] - row["market_value"]) for row in daily
        ),
    }


def annual_returns(simulation: dict[str, Any]) -> list[dict[str, Any]]:
    output = []
    prior_nav = _finite_float(simulation["initial_nav"])
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in simulation["daily"]:
        grouped[row["trade_date"].year].append(row)
    for year in sorted(grouped):
        rows = grouped[year]
        end_nav = rows[-1]["nav"]
        output.append(
            {
                "year": year,
                "start_nav": prior_nav,
                "end_nav": end_nav,
                "return": end_nav / prior_nav - 1.0,
            }
        )
        prior_nav = end_nav
    return output


def trade_diagnostics(simulation: dict[str, Any]) -> dict[str, Any]:
    trades = simulation["trades"]
    returns = np.asarray([trade["net_trade_return"] for trade in trades], dtype=float)
    costs = np.asarray(
        [
            (trade["entry_cost"] + trade["exit_cost"])
            / trade["initial_notional"]
            for trade in trades
        ],
        dtype=float,
    )
    delays = [trade["exit_delay_sessions"] for trade in trades]
    return {
        "n": len(trades),
        "mean_net_trade_return": float(np.mean(returns)),
        "median_net_trade_return": float(np.median(returns)),
        "positive_trade_rate": float(np.mean(returns > 0)),
        "q10_net_trade_return": float(np.quantile(returns, 0.10)),
        "q90_net_trade_return": float(np.quantile(returns, 0.90)),
        "average_cost_fraction_of_entry_notional": float(np.mean(costs)),
        "delayed_exits": sum(delay > 0 for delay in delays),
        "median_exit_delay_sessions": float(median(delays)),
        "maximum_exit_delay_sessions": max(delays),
    }


def causal_deployment_bridge(events: list[dict[str, Any]]) -> dict[str, Any]:
    def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {
                "n": 0,
                "exact_bucket_agreement": None,
                "mean_absolute_bucket_difference": None,
                "shifted_two_or_more_rate": None,
                "raw_weight_correlation": None,
            }
        causal = np.asarray([row["causal_risk_q"] for row in rows], dtype=float)
        descriptive = np.asarray(
            [row["descriptive_risk_q"] for row in rows], dtype=float
        )
        causal_weights = np.asarray(
            [row["causal_raw_weight"] for row in rows], dtype=float
        )
        descriptive_weights = np.asarray(
            [RAW_RISK_WEIGHTS[int(value)] for value in descriptive], dtype=float
        )
        corr = (
            float(np.corrcoef(causal_weights, descriptive_weights)[0, 1])
            if len(rows) > 1
            and float(np.std(causal_weights)) > 0
            and float(np.std(descriptive_weights)) > 0
            else None
        )
        return {
            "n": len(rows),
            "exact_bucket_agreement": float(np.mean(causal == descriptive)),
            "mean_absolute_bucket_difference": float(
                np.mean(np.abs(causal - descriptive))
            ),
            "shifted_two_or_more_rate": float(
                np.mean(np.abs(causal - descriptive) >= 2)
            ),
            "raw_weight_correlation": corr,
        }

    post = [row for row in events if not row["causal_warmup"]]
    bucket_counts = {str(q): 0 for q in range(1, 6)}
    for row in events:
        bucket_counts[str(row["causal_risk_q"])] += 1
    return {
        "warmup_events": sum(row["causal_warmup"] for row in events),
        "first_post_warmup_signal_date": min(
            row["signal_date"] for row in post
        ) if post else None,
        "causal_bucket_counts": bucket_counts,
        "all_events": summarize(events),
        "post_warmup": summarize(post),
    }


def signal_distribution(
    events: list[dict[str, Any]], calendar: list[date], simulations: dict[str, Any]
) -> dict[str, Any]:
    counts: dict[date, int] = defaultdict(int)
    for event in events:
        counts[event["entry_date"]] += 1
    distribution = {key: 0 for key in ("0", "1", "2-5", "6-20", ">20")}
    for trade_date in calendar:
        distribution[signal_count_bucket(counts[trade_date])] += 1

    sizes: dict[str, dict[str, Any]] = {}
    for policy in POLICIES:
        trades = simulations[f"{policy}:BASE"]["trades"]
        grouped: dict[str, list[float]] = defaultdict(list)
        for trade in trades:
            grouped[trade["signal_day_bucket"]].append(
                trade["entry_weight_of_opening_nav"]
            )
        sizes[policy] = {
            bucket: {
                "entries": len(values),
                "average_position_weight": float(np.mean(values)),
            }
            for bucket, values in sorted(grouped.items())
        }
    return {
        "trading_day_signal_count_buckets": distribution,
        "signal_days": sum(n > 0 for n in counts.values()),
        "maximum_signals_on_one_entry_date": max(counts.values()),
        "average_position_size_by_signal_count_bucket": sizes,
    }


def executable_bridge(simulation: dict[str, Any]) -> dict[str, Any]:
    trades = simulation["trades"]
    v4 = np.asarray([trade["v4_ret_20"] for trade in trades], dtype=float)
    v5 = np.asarray([trade["gross_trade_return"] for trade in trades], dtype=float)
    difference = v5 - v4
    return {
        "entered_events": len(trades),
        "mean_v4_ret_20": float(np.mean(v4)),
        "mean_v5_executable_gross_return": float(np.mean(v5)),
        "mean_return_difference": float(np.mean(difference)),
        "median_return_difference": float(np.median(difference)),
        "mean_absolute_return_difference": float(np.mean(np.abs(difference))),
        "return_correlation": float(np.corrcoef(v4, v5)[0, 1]),
        "positive_endpoint_gap_rate": float(np.mean(difference > 0)),
    }


def risk_bucket_attribution(simulation: dict[str, Any]) -> list[dict[str, Any]]:
    trades = simulation["trades"]
    total_notional = sum(trade["initial_notional"] for trade in trades)
    output = []
    for risk_q in range(1, 6):
        rows = [trade for trade in trades if trade["causal_risk_q"] == risk_q]
        notional = sum(trade["initial_notional"] for trade in rows)
        output.append(
            {
                "causal_risk_q": risk_q,
                "entries": len(rows),
                "entry_notional": notional,
                "allocation_share": notional / total_notional,
                "gross_realized_pnl": sum(
                    trade["exit_notional"] - trade["initial_notional"]
                    for trade in rows
                ),
                "net_realized_pnl": sum(trade["realized_pnl"] for trade in rows),
                "v4_mae_capital": sum(
                    trade["initial_notional"] * trade["v4_mae_20"]
                    for trade in rows
                ),
                "severe_event_capital": sum(
                    trade["initial_notional"]
                    for trade in rows
                    if trade["v4_mae_20"] <= SEVERE_MAE_MAX
                ),
                "no_trigger_capital": sum(
                    trade["initial_notional"]
                    for trade in rows
                    if not trade["trigger_signal"]
                ),
                "mean_gross_trade_return": (
                    float(np.mean([trade["gross_trade_return"] for trade in rows]))
                    if rows
                    else None
                ),
                "mean_net_trade_return": (
                    float(np.mean([trade["net_trade_return"] for trade in rows]))
                    if rows
                    else None
                ),
            }
        )
    severe_total = sum(row["severe_event_capital"] for row in output)
    no_trigger_total = sum(row["no_trigger_capital"] for row in output)
    for row in output:
        row["share_of_severe_event_capital"] = (
            row["severe_event_capital"] / severe_total if severe_total else 0.0
        )
        row["share_of_no_trigger_capital"] = (
            row["no_trigger_capital"] / no_trigger_total if no_trigger_total else 0.0
        )
    return output


def bucket_attribution_comparison(
    equal_rows: list[dict[str, Any]], risk_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    equal_by_q = {row["causal_risk_q"]: row for row in equal_rows}
    risk_by_q = {row["causal_risk_q"]: row for row in risk_rows}
    output = []
    for risk_q in range(1, 6):
        equal = equal_by_q[risk_q]
        risk = risk_by_q[risk_q]
        output.append(
            {
                "causal_risk_q": risk_q,
                "equal_allocation_share": equal["allocation_share"],
                "risk_aware_allocation_share": risk["allocation_share"],
                "allocation_share_difference": risk["allocation_share"]
                - equal["allocation_share"],
                "equal_net_realized_pnl": equal["net_realized_pnl"],
                "risk_aware_net_realized_pnl": risk["net_realized_pnl"],
                "net_realized_pnl_difference": risk["net_realized_pnl"]
                - equal["net_realized_pnl"],
                "equal_share_of_severe_event_capital": equal[
                    "share_of_severe_event_capital"
                ],
                "risk_aware_share_of_severe_event_capital": risk[
                    "share_of_severe_event_capital"
                ],
                "equal_share_of_no_trigger_capital": equal[
                    "share_of_no_trigger_capital"
                ],
                "risk_aware_share_of_no_trigger_capital": risk[
                    "share_of_no_trigger_capital"
                ],
            }
        )
    return output


def alpha_collapse_decomposition(
    equal_gross: dict[str, Any], equal_net: dict[str, Any]
) -> dict[str, Any]:
    gross_trades = equal_gross["trades"]
    returns_by_date: dict[date, list[float]] = defaultdict(list)
    for trade in gross_trades:
        returns_by_date[trade["entry_date"]].append(trade["gross_trade_return"])
    date_equal_means = [
        float(np.mean(values)) for _, values in sorted(returns_by_date.items())
    ]
    event_returns = np.asarray(
        [trade["gross_trade_return"] for trade in gross_trades], dtype=float
    )
    total_entry_notional = sum(trade["initial_notional"] for trade in gross_trades)
    capital_weighted_return = sum(
        trade["initial_notional"] * trade["gross_trade_return"]
        for trade in gross_trades
    ) / total_entry_notional
    clustered_events = sum(
        len(values) for values in returns_by_date.values() if len(values) > 20
    )
    gross_metrics = portfolio_metrics(equal_gross)
    net_metrics = portfolio_metrics(equal_net)
    return {
        "v5_executable_event_equal_mean_return": float(np.mean(event_returns)),
        "entry_date_equal_mean_cross_sectional_return": float(
            np.mean(date_equal_means)
        ),
        "actual_entry_capital_weighted_mean_gross_trade_return": capital_weighted_return,
        "event_to_date_equal_change": float(np.mean(date_equal_means))
        - float(np.mean(event_returns)),
        "date_equal_to_actual_capital_weighted_change": capital_weighted_return
        - float(np.mean(date_equal_means)),
        "events_on_days_with_more_than_20_signals": clustered_events,
        "events_on_days_with_more_than_20_signals_rate": clustered_events
        / len(gross_trades),
        "total_gross_entry_notional": total_entry_notional,
        "gross_portfolio_profit": gross_metrics["ending_nav"] - INITIAL_NAV,
        "gross_portfolio_cumulative_return": gross_metrics["cumulative_return"],
        "average_gross_exposure": gross_metrics["average_exposure"],
        "average_idle_cash": gross_metrics["average_cash_weight"],
        "overlapping_security_skips": equal_gross["flow"][
            "overlapping_security_skips"
        ],
        "missed_for_zero_cash": equal_gross["flow"]["missed_for_zero_cash"],
        "gross_cash_constrained_days": equal_gross["flow"]["cash_constrained_days"],
        "base_cost_total": net_metrics["total_cost"],
        "base_cost_ending_nav_drag": net_metrics["ending_nav"]
        - gross_metrics["ending_nav"],
        "executable_endpoint_mean_change_vs_v4": float(
            np.mean(
                [
                    trade["gross_trade_return"] - trade["v4_ret_20"]
                    for trade in gross_trades
                ]
            )
        ),
    }


def _slice_metrics(
    simulation: dict[str, Any], start_date: date, end_date: date
) -> dict[str, Any]:
    all_daily = simulation["daily"]
    selected = [
        row for row in all_daily if start_date <= row["trade_date"] <= end_date
    ]
    if not selected:
        return {"trading_days": 0}
    first_index = all_daily.index(selected[0])
    start_nav = (
        simulation["initial_nav"] if first_index == 0 else all_daily[first_index - 1]["nav"]
    )
    returns = _daily_returns(selected, start_nav)
    years = len(selected) / 252.0
    ending = selected[-1]["nav"]
    period_return = ending / start_nav - 1.0
    cagr = (ending / start_nav) ** (1.0 / years) - 1.0
    vol = float(np.std(returns, ddof=1) * math.sqrt(252.0))
    std = float(np.std(returns, ddof=1))
    max_dd, _ = _drawdown(
        np.asarray([start_nav, *[row["nav"] for row in selected]], dtype=float)
    )
    return {
        "trading_days": len(selected),
        "start_date": selected[0]["trade_date"],
        "end_date": selected[-1]["trade_date"],
        "cumulative_return": period_return,
        "cagr": cagr,
        "annualized_volatility": vol,
        "max_drawdown": max_dd,
        "sharpe_like": float(np.mean(returns) / std * math.sqrt(252.0)) if std else 0.0,
        "average_exposure": float(np.mean([row["exposure"] for row in selected])),
        "total_cost": sum(row["total_cost"] for row in selected),
    }


def time_blocks(simulation: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = (
        ("2018-2020", date(2018, 1, 1), date(2020, 12, 31)),
        ("2021-2023", date(2021, 1, 1), date(2023, 12, 31)),
        ("2024-2026", date(2024, 1, 1), date(2026, 12, 31)),
    )
    return [
        {"time_block": label, **_slice_metrics(simulation, start, end)}
        for label, start, end in blocks
    ]


def drawdown_episodes(
    equal_simulation: dict[str, Any], risk_simulation: dict[str, Any], *, limit: int = 3
) -> list[dict[str, Any]]:
    equal = equal_simulation["daily"]
    risk_by_date = {row["trade_date"]: row["nav"] for row in risk_simulation["daily"]}
    nav = np.asarray([row["nav"] for row in equal], dtype=float)
    running_peak_index = 0
    episodes: dict[int, tuple[int, float]] = {}
    for index, value in enumerate(nav):
        if value >= nav[running_peak_index]:
            running_peak_index = index
        drawdown = value / nav[running_peak_index] - 1.0
        prior = episodes.get(running_peak_index)
        if prior is None or drawdown < prior[1]:
            episodes[running_peak_index] = (index, drawdown)
    ranked = sorted(episodes.items(), key=lambda item: item[1][1])[:limit]
    output = []
    for peak_index, (trough_index, dd) in ranked:
        peak_date = equal[peak_index]["trade_date"]
        trough_date = equal[trough_index]["trade_date"]
        recovery_date = None
        peak_nav = equal[peak_index]["nav"]
        for row in equal[trough_index + 1 :]:
            if row["nav"] >= peak_nav:
                recovery_date = row["trade_date"]
                break
        risk_peak = risk_by_date[peak_date]
        risk_period = [
            risk_by_date[row["trade_date"]]
            for row in equal[peak_index : trough_index + 1]
        ]
        risk_dd = min(value / risk_peak - 1.0 for value in risk_period)
        output.append(
            {
                "equal_peak_date": peak_date,
                "equal_trough_date": trough_date,
                "equal_recovery_date": recovery_date,
                "equal_drawdown": dd,
                "risk_aware_same_period_drawdown": risk_dd,
            }
        )
    return output


def crash_cluster_days(
    events: list[dict[str, Any]], simulations: dict[str, Any], *, limit: int = 5
) -> list[dict[str, Any]]:
    counts: dict[date, int] = defaultdict(int)
    for event in events:
        counts[event["entry_date"]] += 1
    top_dates = sorted(counts, key=lambda d: (-counts[d], d))[:limit]
    output = []
    for trade_date in top_dates:
        row: dict[str, Any] = {"entry_date": trade_date, "signals": counts[trade_date]}
        for policy in POLICIES:
            simulation = simulations[f"{policy}:BASE"]
            allocation = next(
                (
                    item
                    for item in simulation["daily_allocations"]
                    if item["trade_date"] == trade_date
                ),
                None,
            )
            row[f"{policy.lower()}_actual_entry_notional"] = (
                allocation["actual_entry_notional"] if allocation else 0.0
            )
            row[f"{policy.lower()}_average_position_weight"] = (
                allocation["actual_budget_fraction_of_nav"] / counts[trade_date]
                if allocation
                else 0.0
            )
        output.append(row)
    return output


def result_checks(
    events: list[dict[str, Any]],
    simulations: dict[str, Any],
    payload: dict[str, Any],
    *,
    expected_event_count: int | None,
) -> dict[str, Any]:
    checks: dict[str, Any] = {
        "event_count_difference_vs_v4": (
            len(events) - expected_event_count if expected_event_count is not None else 0
        ),
        "duplicate_event_keys": len(events)
        - len({(row["symbol"], row["signal_date"]) for row in events}),
        "missing_scheduled_exits": sum(
            row["scheduled_exit_date"] is None for row in events
        ),
        "missing_legal_exits": sum(
            row["first_legal_exit_date"] is None for row in events
        ),
        "causal_current_date_reference_violations": 0,
        "warmup_non_neutral_weights": sum(
            row["causal_warmup"] and row["causal_raw_weight"] != 1.0
            for row in events
        ),
        "nonpositive_risk_weights": sum(
            row["causal_raw_weight"] <= 0 for row in events
        ),
        "weight_map_mismatch": sum(
            row["causal_raw_weight"] != RAW_RISK_WEIGHTS[row["causal_risk_q"]]
            for row in events
        ),
    }
    by_date: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for row in events:
        by_date[row["signal_date"]].append(row)
    prior = 0
    for signal_date in sorted(by_date):
        if any(row["causal_prior_event_n"] != prior for row in by_date[signal_date]):
            checks["causal_current_date_reference_violations"] += 1
        prior += len(by_date[signal_date])

    for key, simulation in simulations.items():
        metrics = payload["portfolio_metrics"][key]
        checks[f"{key}_negative_cash"] = int(metrics["minimum_cash"] < -1e-12)
        checks[f"{key}_nav_accounting_error"] = metrics[
            "maximum_nav_accounting_error"
        ]
        checks[f"{key}_entry_exit_difference"] = (
            simulation["flow"]["entered"] - len(simulation["trades"])
        )
        checks[f"{key}_final_nav_difference"] = (
            simulation["daily"][-1]["nav"] - simulation["daily"][-1]["cash"]
        )
        checks[f"{key}_leverage_days"] = sum(
            row["exposure"] > 1.0 + 1e-12 for row in simulation["daily"]
        )
        checks[f"{key}_wrong_entry_chronology"] = sum(
            trade["entry_date"] <= trade["signal_date"]
            for trade in simulation["trades"]
        )
        checks[f"{key}_wrong_exit_chronology"] = sum(
            trade["actual_exit_date"] < trade["scheduled_exit_date"]
            for trade in simulation["trades"]
        )
        checks[f"{key}_daily_nav_count_difference"] = (
            len(simulation["daily"]) - metrics["trading_days"]
        )
    tolerance_keys = [key for key in checks if key.endswith("accounting_error") or key.endswith("nav_difference")]
    failures = {
        key: value
        for key, value in checks.items()
        if (key in tolerance_keys and abs(value) > 1e-12)
        or (key not in tolerance_keys and value != 0)
    }
    if failures:
        raise RuntimeError(f"V5 result invariants failed: {failures}")
    return checks


def _load_inputs(
    con: duckdb.DuckDBPyConnection,
) -> tuple[list[dict[str, Any]], dict[tuple[str, date], dict[str, Any]], list[date]]:
    events = rows_as_dicts(con.execute("SELECT * FROM v5_events ORDER BY signal_date, symbol"))
    events = assign_causal_buckets(events)
    prices = {
        (row["symbol"], row["trade_date"]): row
        for row in rows_as_dicts(
            con.execute("SELECT * FROM v5_prices ORDER BY trade_date, symbol")
        )
    }
    calendar = [row[0] for row in con.execute("SELECT trade_date FROM v5_calendar").fetchall()]
    return events, prices, calendar


def collect_results(
    con: duckdb.DuckDBPyConnection,
    *,
    expected_event_count: int | None = 22_357,
) -> tuple[dict[str, Any], dict[str, Any]]:
    v3_checks = v3_semantic_checks(con)
    events, prices, calendar = _load_inputs(con)
    simulations: dict[str, Any] = {}
    for policy in POLICIES:
        for cost_mode in COST_MODES:
            key = f"{policy}:{cost_mode}"
            simulations[key] = simulate_portfolio(
                policy=policy,
                cost_mode=cost_mode,
                events=events,
                prices=prices,
                calendar=calendar,
            )
    metrics = {key: portfolio_metrics(sim) for key, sim in simulations.items()}
    annual = {
        policy: annual_returns(simulations[f"{policy}:BASE"]) for policy in POLICIES
    }
    annual_compare = []
    for equal, risk in zip(annual["EQUAL_SIZE"], annual["RISK_AWARE_SIZE"], strict=True):
        annual_compare.append(
            {
                "year": equal["year"],
                "equal_net_return": equal["return"],
                "risk_aware_net_return": risk["return"],
                "risk_minus_equal": risk["return"] - equal["return"],
            }
        )
    primary_comparison = {}
    equal_net = metrics["EQUAL_SIZE:BASE"]
    risk_net = metrics["RISK_AWARE_SIZE:BASE"]
    for field in (
        "ending_nav",
        "cumulative_return",
        "cagr",
        "annualized_volatility",
        "max_drawdown",
        "sharpe_like",
        "calmar",
        "average_exposure",
        "average_cash_weight",
        "average_concurrent_positions",
        "maximum_concurrent_positions",
        "average_largest_position_weight",
        "maximum_largest_position_weight",
        "average_top5_concentration",
        "maximum_top5_concentration",
        "annualized_turnover",
        "total_cost",
    ):
        primary_comparison[field] = {
            "equal_net": equal_net[field],
            "risk_aware_net": risk_net[field],
            "risk_minus_equal": risk_net[field] - equal_net[field],
        }
    cost_attribution = {}
    for policy in POLICIES:
        gross = metrics[f"{policy}:GROSS"]
        base = metrics[f"{policy}:BASE"]
        stress = metrics[f"{policy}:HIGH_COST"]
        cost_attribution[policy] = {
            "gross_ending_nav": gross["ending_nav"],
            "gross_cumulative_return": gross["cumulative_return"],
            "gross_cagr": gross["cagr"],
            "net_ending_nav": base["ending_nav"],
            "net_cumulative_return": base["cumulative_return"],
            "net_cagr": base["cagr"],
            "ending_nav_drag": base["ending_nav"] - gross["ending_nav"],
            "cagr_drag": base["cagr"] - gross["cagr"],
            "total_base_cost": base["total_cost"],
            "base_cost_as_fraction_of_gross_profit": (
                base["total_cost"] / (gross["ending_nav"] - INITIAL_NAV)
                if gross["ending_nav"] > INITIAL_NAV
                else None
            ),
            "stress_ending_nav": stress["ending_nav"],
            "stress_cagr": stress["cagr"],
        }
    equal_bucket = risk_bucket_attribution(simulations["EQUAL_SIZE:BASE"])
    risk_bucket = risk_bucket_attribution(simulations["RISK_AWARE_SIZE:BASE"])
    payload: dict[str, Any] = {
        "research_version": "oversold-reversal-ranking-v5-portfolio",
        "verdict": VERDICT,
        "single_next_step": SINGLE_NEXT_STEP,
        "definitions": {
            "predecessor_verdicts": {
                "v1": "DEPTH_ONLY",
                "v2": "RISK_FILTER_ONLY",
                "v3": "SIZING_SIGNAL_ONLY",
                "v4": "SIZING_SURVIVES",
            },
            "carrier": "exact V1 LOW plus causal drawdown_60 <= -30%; exact valid V3/V4 event stream",
            "event_deduplication": "first deep-carrier observation after no deep-carrier observation in prior 20 security trading rows",
            "entry": "t0 close signal; inherited next listed legal open",
            "holding_exit": "hold t0+1 through t0+20, then sell first legal open on/after t0+21",
            "adjusted_price": "adjusted_open=adjusted_close*open/close; adjusted units and close/preclose total-return marks",
            "causal_bucket": "empirical CDF among valid event scores from strictly prior dates; <=20/40/60/80/>80 to Q1-Q5",
            "warmup": f"prior event count < {WARMUP_PRIOR_EVENTS}: neutral Q3 raw weight 1.0",
            "raw_weight_map": {str(key): value for key, value in RAW_RISK_WEIGHTS.items()},
            "daily_tranche": DAILY_TRANCHE_FRACTION,
            "costs": {
                "buy_base_bps": 8.0,
                "sell_base_bps_before_2023_08_28": 18.0,
                "sell_base_bps_on_after_2023_08_28": 13.0,
                "high_cost": "double commission and slippage; retain 10/5 bps historical sell stamp duty",
            },
        },
        "sample_profile": {
            "events": len(events),
            "securities": len({row["symbol"] for row in events}),
            "signal_dates": len({row["signal_date"] for row in events}),
            "first_signal_date": min(row["signal_date"] for row in events),
            "last_signal_date": max(row["signal_date"] for row in events),
            "first_entry_date": min(row["entry_date"] for row in events),
            "last_legal_exit_date": max(row["first_legal_exit_date"] for row in events),
            "missing_scheduled_exit": sum(
                row["scheduled_exit_date"] is None for row in events
            ),
            "missing_legal_exit": sum(
                row["first_legal_exit_date"] is None for row in events
            ),
        },
        "v3_checks": v3_checks,
        "causal_sizing_deployment": causal_deployment_bridge(events),
        "portfolio_metrics": metrics,
        "primary_net_comparison": primary_comparison,
        "signal_flow": {
            key: simulation["flow"] for key, simulation in simulations.items()
        },
        "signal_distribution": signal_distribution(events, calendar, simulations),
        "trade_diagnostics": {
            key: trade_diagnostics(simulations[key])
            for key in ("EQUAL_SIZE:BASE", "RISK_AWARE_SIZE:BASE")
        },
        "transaction_cost_attribution": cost_attribution,
        "yearly_net_returns": annual_compare,
        "time_blocks": {
            policy: time_blocks(simulations[f"{policy}:BASE"])
            for policy in POLICIES
        },
        "drawdown_episodes": drawdown_episodes(
            simulations["EQUAL_SIZE:BASE"], simulations["RISK_AWARE_SIZE:BASE"]
        ),
        "crash_cluster_days": crash_cluster_days(events, simulations),
        "alpha_collapse_decomposition": alpha_collapse_decomposition(
            simulations["EQUAL_SIZE:GROSS"], simulations["EQUAL_SIZE:BASE"]
        ),
        "equal_bucket_attribution": equal_bucket,
        "risk_aware_bucket_attribution": risk_bucket,
        "bucket_attribution_comparison": bucket_attribution_comparison(
            equal_bucket, risk_bucket
        ),
        "v4_executable_bridge": executable_bridge(simulations["EQUAL_SIZE:BASE"]),
    }
    payload["checks"] = result_checks(
        events,
        simulations,
        payload,
        expected_event_count=expected_event_count,
    )
    internals = {"events": events, "simulations": simulations, "calendar": calendar}
    return payload, internals


def write_daily_nav(output_dir: Path, simulations: dict[str, Any]) -> None:
    path = output_dir / "v5_daily_nav.csv"
    rows = []
    keys = (
        "EQUAL_SIZE:GROSS",
        "EQUAL_SIZE:BASE",
        "RISK_AWARE_SIZE:GROSS",
        "RISK_AWARE_SIZE:BASE",
    )
    by_key = {key: simulations[key]["daily"] for key in keys}
    for indexed in zip(*(by_key[key] for key in keys), strict=True):
        trade_date = indexed[0]["trade_date"]
        if any(row["trade_date"] != trade_date for row in indexed):
            raise RuntimeError("daily NAV date mismatch")
        rows.append(
            {
                "trade_date": trade_date.isoformat(),
                "equal_gross_nav": indexed[0]["nav"],
                "equal_net_nav": indexed[1]["nav"],
                "risk_aware_gross_nav": indexed[2]["nav"],
                "risk_aware_net_nav": indexed[3]["nav"],
                "equal_net_exposure": indexed[1]["exposure"],
                "risk_aware_net_exposure": indexed[3]["exposure"],
                "equal_net_positions": indexed[1]["concurrent_positions"],
                "risk_aware_net_positions": indexed[3]["concurrent_positions"],
            }
        )
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run(
    output_dir: Path,
    *,
    hash_data_files: bool = True,
    symbol_filter: list[str] | None = None,
    write_outputs: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    config = json.loads(PREDECESSOR_CONFIG.read_text())
    config["research_version"] = "oversold-reversal-ranking-v5-portfolio"
    if symbol_filter:
        config.setdefault("runtime", {})["symbol_filter"] = symbol_filter
    identities = validate_inputs(config, hash_data_files=hash_data_files)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="oversold-portfolio-v5-") as temp_dir:
        con = duckdb.connect()
        con.execute(f"SET threads={int(config['runtime']['threads'])}")
        con.execute(f"SET memory_limit='{config['runtime']['memory_limit']}'")
        con.execute(f"SET temp_directory='{temp_dir}'")
        con.execute("SET preserve_insertion_order=false")
        create_analysis_tables(con, config)
        create_timing_tables(con)
        create_risk_tables(con)
        create_portfolio_tables(con, config)
        payload, internals = collect_results(
            con,
            expected_event_count=None if symbol_filter else 22_357,
        )
        payload["input_identities"] = identities
        con.close()
    if write_outputs:
        (output_dir / "v5_portfolio_results.json").write_text(
            json.dumps(payload, indent=2, default=json_default) + "\n"
        )
        write_daily_nav(output_dir, internals["simulations"])
    return payload, internals


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-data-file-hashes", action="store_true")
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    run(
        args.output,
        hash_data_files=not args.skip_data_file_hashes,
        symbol_filter=args.symbols,
        write_outputs=not args.no_write,
    )


if __name__ == "__main__":
    main()
