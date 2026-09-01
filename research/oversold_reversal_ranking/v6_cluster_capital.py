#!/usr/bin/env python3
"""V6: causal cluster-intensity translation into a total daily capital budget."""

# The portfolio loop remains explicit so chronology, cash, and causal count history are auditable.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
import math
import tempfile
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any

import duckdb
import numpy as np

from research.oversold_reversal_ranking import v5_portfolio as v5

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "reports"
STARTING_HEAD = "0850fbc8cc3bdcdb0fdd5acc1abe23117084185b"
BASE_BUDGET_FRACTION = 0.05
WARMUP_PRIOR_ACTIVE_DATES = 60
EXPECTED_EVENTS = 22_357
COUNT_REGIMES = ("1", "2-5", "6-10", "11-20", ">20")

# Set after inspection of the single frozen broad run; the experiment never branches on it.
VERDICT = "CLUSTER_SIGNAL_EXISTS_BUT_CAPITAL_TRANSLATION_FAILS"
SINGLE_NEXT_STEP = "Run one preregistered cluster-episode portfolio study that aggregates consecutive high-count entry dates into a single stress episode with one fixed finite-capital envelope, without leverage, stock selection, or parameter search."


def count_regime(n: int) -> str:
    if n == 1:
        return "1"
    if n <= 5:
        return "2-5"
    if n <= 10:
        return "6-10"
    if n <= 20:
        return "11-20"
    return ">20"


def assign_causal_cluster_reference(
    events: list[dict[str, Any]],
    *,
    minimum_history: int = WARMUP_PRIOR_ACTIVE_DATES,
) -> list[dict[str, Any]]:
    """Assign N_t and an expanding prior-active-date median without same-date leakage."""
    counts: dict[date, int] = defaultdict(int)
    for event in events:
        entry_date = event.get("entry_date")
        if entry_date is not None:
            counts[entry_date] += 1
    history: list[int] = []
    output: list[dict[str, Any]] = []
    for entry_date in sorted(counts):
        n = counts[entry_date]
        warmup = len(history) < minimum_history
        prior_median = None if warmup else float(median(history))
        ratio = 1.0 if warmup else n / prior_median
        output.append(
            {
                "entry_date": entry_date,
                "signal_count": n,
                "prior_active_dates": len(history),
                "prior_median_positive_count": prior_median,
                "count_ratio": ratio,
                "warmup": warmup,
            }
        )
        history.append(n)
    return output


def simulate_count_aware(
    *,
    events: list[dict[str, Any]],
    prices: dict[tuple[str, date], dict[str, Any]],
    calendar: list[date],
    cluster_reference: list[dict[str, Any]],
    initial_nav: float = v5.INITIAL_NAV,
) -> dict[str, Any]:
    """Replay V5 gross mechanics with only the preregistered total budget changed."""
    reference = {row["entry_date"]: row for row in cluster_reference}
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
    allocations: list[dict[str, Any]] = []
    flow = {
        "signals": 0,
        "entered": 0,
        "overlapping_security_skips": 0,
        "invalid_entry_price": 0,
        "missed_for_zero_cash": 0,
        "entry_days": 0,
        "cash_constrained_days": 0,
    }

    for trade_date in calendar:
        opening_market_value = 0.0
        for symbol, lot in positions.items():
            price = v5._price(prices, symbol, trade_date)
            mark = (
                v5._finite_float(price["adjusted_open"])
                if price is not None
                else last_marks[symbol]
            )
            opening_market_value += lot["units"] * mark
        opening_nav = cash + opening_market_value
        if opening_nav <= 0:
            raise RuntimeError(f"nonpositive opening NAV on {trade_date}: {opening_nav}")

        exit_notional = 0.0
        exits_today = 0
        for symbol in sorted(list(positions)):
            lot = positions[symbol]
            if trade_date < lot["scheduled_exit_date"]:
                continue
            price = v5._price(prices, symbol, trade_date)
            if price is None or not price["sellable_open"]:
                continue
            exit_price = v5._finite_float(price["adjusted_open"])
            proceeds = lot["units"] * exit_price
            cash += proceeds
            exit_notional += proceeds
            exits_today += 1
            lot.update(
                {
                    "actual_exit_date": trade_date,
                    "exit_adjusted_open": exit_price,
                    "exit_notional": proceeds,
                    "exit_cost": 0.0,
                    "gross_trade_return": exit_price / lot["entry_adjusted_open"] - 1.0,
                    "net_trade_return": proceeds / lot["initial_notional"] - 1.0,
                    "realized_pnl": proceeds - lot["initial_notional"],
                    "holding_sessions": v5.HOLDING_SESSIONS + lot["exit_delay_sessions"],
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
            price = v5._price(prices, event["symbol"], trade_date)
            if price is None or v5._finite_float(price["adjusted_open"]) <= 0:
                flow["invalid_entry_price"] += 1
                continue
            executable.append(event)

        entry_notional = 0.0
        if executable:
            flow["entry_days"] += 1
            state = reference[trade_date]
            if state["signal_count"] != len(today_signals):
                raise RuntimeError(f"cluster count mismatch on {trade_date}")
            desired = BASE_BUDGET_FRACTION * opening_nav * state["count_ratio"]
            available_cash = cash
            actual = min(desired, available_cash)
            shortfall = desired - actual
            if shortfall > 1e-15:
                flow["cash_constrained_days"] += 1
            if actual <= 1e-15:
                flow["missed_for_zero_cash"] += len(executable)
            else:
                per_event = actual / len(executable)
                for event in executable:
                    price = v5._price(prices, event["symbol"], trade_date)
                    assert price is not None
                    entry_price = v5._finite_float(price["adjusted_open"])
                    cash -= per_event
                    if cash < -1e-12:
                        raise RuntimeError(f"negative cash on {trade_date}: {cash}")
                    cash = max(cash, 0.0)
                    scheduled = event["scheduled_exit_date"]
                    if scheduled is None:
                        raise RuntimeError(f"missing scheduled exit: {event['event_id']}")
                    lot = {
                        **event,
                        "policy": "COUNT_AWARE_EQUAL",
                        "cost_mode": "GROSS",
                        "entry_adjusted_open": entry_price,
                        "initial_notional": per_event,
                        "units": per_event / entry_price,
                        "entry_cost": 0.0,
                        "signal_day_n": len(today_signals),
                        "signal_day_bucket": count_regime(len(today_signals)),
                        "entry_weight_of_opening_nav": per_event / opening_nav,
                        "exit_delay_sessions": int(event["expected_exit_delay_sessions"] or 0),
                    }
                    positions[event["symbol"]] = lot
                    entry_notional += per_event
                    flow["entered"] += 1
            allocations.append(
                {
                    **state,
                    "opening_nav": opening_nav,
                    "control_desired_budget": BASE_BUDGET_FRACTION * opening_nav,
                    "desired_budget": desired,
                    "available_cash": available_cash,
                    "actual_entry_notional": actual,
                    "budget_shortfall": shortfall,
                    "blocked_fraction": shortfall / desired if desired > 0 else 0.0,
                    "cash_constrained": shortfall > 1e-15,
                }
            )

        close_values: list[float] = []
        for symbol, lot in positions.items():
            price = v5._price(prices, symbol, trade_date)
            if price is not None:
                last_marks[symbol] = v5._finite_float(price["adjusted_close"])
            if symbol not in last_marks:
                raise RuntimeError(f"missing close mark for {symbol} on {trade_date}")
            close_values.append(lot["units"] * last_marks[symbol])
        market_value = sum(close_values)
        close_nav = cash + market_value
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
                "entry_cost": 0.0,
                "exit_cost": 0.0,
                "total_cost": 0.0,
            }
        )

    if positions:
        raise RuntimeError(f"open positions remain at final date: {sorted(positions)[:5]}")
    if flow["entered"] != len(trades):
        raise RuntimeError(f"entry/exit mismatch: {flow}, exits={len(trades)}")
    return {
        "policy": "COUNT_AWARE_EQUAL",
        "cost_mode": "GROSS",
        "initial_nav": initial_nav,
        "daily": daily,
        "trades": trades,
        "flow": flow,
        "daily_allocations": allocations,
    }


def _average_ranks(values: list[float]) -> np.ndarray:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = np.empty(len(values), dtype=float)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        rank = (start + 1 + end) / 2.0
        for index in order[start:end]:
            ranks[index] = rank
        start = end
    return ranks


def _correlations(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if len(rows) < 2:
        return {"n": len(rows), "spearman": None, "pearson": None}
    counts = [float(row["signal_count"]) for row in rows]
    returns = [float(row["basket_gross_return"]) for row in rows]
    return {
        "n": len(rows),
        "spearman": float(np.corrcoef(_average_ranks(counts), _average_ranks(returns))[0, 1]),
        "pearson": float(np.corrcoef(counts, returns)[0, 1]),
    }


def _count_quintiles(active_dates: list[dict[str, Any]]) -> dict[date, int]:
    ordered = sorted(active_dates, key=lambda row: (row["signal_count"], row["entry_date"]))
    output: dict[date, int] = {}
    for q, indexes in enumerate(np.array_split(np.arange(len(ordered)), 5), start=1):
        for index in indexes:
            output[ordered[int(index)]["entry_date"]] = q
    return output


def count_distribution(cluster_reference: list[dict[str, Any]]) -> dict[str, Any]:
    counts = np.asarray([row["signal_count"] for row in cluster_reference], dtype=float)
    regimes = {key: 0 for key in COUNT_REGIMES}
    for value in counts:
        regimes[count_regime(int(value))] += 1
    total_events = int(np.sum(counts))
    return {
        "active_entry_dates": len(counts),
        "total_events": total_events,
        "mean": float(np.mean(counts)),
        "median": float(np.median(counts)),
        "p75": float(np.quantile(counts, 0.75)),
        "p90": float(np.quantile(counts, 0.90)),
        "p95": float(np.quantile(counts, 0.95)),
        "p99": float(np.quantile(counts, 0.99)),
        "maximum": int(np.max(counts)),
        "fraction_events_on_dates_above_20": float(np.sum(counts[counts > 20]) / total_events),
        "active_date_regime_counts": regimes,
        "active_date_regime_fractions": {key: value / len(counts) for key, value in regimes.items()},
    }


def count_return_bridge(
    control: dict[str, Any], cluster_reference: list[dict[str, Any]]
) -> dict[str, Any]:
    grouped: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for trade in control["trades"]:
        grouped[trade["entry_date"]].append(trade)
    count_by_date = {row["entry_date"]: row["signal_count"] for row in cluster_reference}
    records = []
    for entry_date in sorted(grouped):
        trades = grouped[entry_date]
        records.append(
            {
                "entry_date": entry_date,
                "signal_count": count_by_date[entry_date],
                "basket_gross_return": float(np.mean([row["gross_trade_return"] for row in trades])),
                "basket_median_gross_return": float(np.median([row["gross_trade_return"] for row in trades])),
                "basket_positive_event_rate": float(np.mean([row["gross_trade_return"] > 0 for row in trades])),
                "basket_mean_v4_mae20": float(np.mean([row["v4_mae_20"] for row in trades])),
                "total_event_return_contribution": float(sum(row["gross_trade_return"] for row in trades)),
            }
        )
    quintiles = _count_quintiles(cluster_reference)
    for row in records:
        row["count_rank_q"] = quintiles[row["entry_date"]]
    values = np.asarray([row["basket_gross_return"] for row in records], dtype=float)
    quantile_rows = []
    for q in range(1, 6):
        selected = [row for row in records if row["count_rank_q"] == q]
        quantile_rows.append(
            {
                "count_rank_q": q,
                "active_dates": len(selected),
                "events": sum(row["signal_count"] for row in selected),
                "minimum_count": min(row["signal_count"] for row in selected),
                "maximum_count": max(row["signal_count"] for row in selected),
                "mean_basket_return": float(np.mean([row["basket_gross_return"] for row in selected])),
                "median_basket_return": float(np.median([row["basket_gross_return"] for row in selected])),
                "positive_basket_rate": float(np.mean([row["basket_gross_return"] > 0 for row in selected])),
                "mean_basket_mae20": float(np.mean([row["basket_mean_v4_mae20"] for row in selected])),
            }
        )
    periods = []
    for label, start, end in (
        ("2018-2020", date(2018, 1, 1), date(2020, 12, 31)),
        ("2021-2023", date(2021, 1, 1), date(2023, 12, 31)),
        ("2024-2026", date(2024, 1, 1), date(2026, 12, 31)),
    ):
        selected = [row for row in records if start <= row["entry_date"] <= end]
        periods.append(
            {
                "time_block": label,
                "active_dates": len(selected),
                "signals": sum(row["signal_count"] for row in selected),
                **_correlations(selected),
                "mean_basket_return": float(np.mean([row["basket_gross_return"] for row in selected])),
                "positive_basket_rate": float(np.mean([row["basket_gross_return"] > 0 for row in selected])),
            }
        )
    return {
        "overall": {
            **_correlations(records),
            "mean_basket_return": float(np.mean(values)),
            "median_basket_return": float(np.median(values)),
            "positive_basket_rate": float(np.mean(values > 0)),
            "mean_basket_mae20": float(np.mean([row["basket_mean_v4_mae20"] for row in records])),
        },
        "count_rank_quintiles": quantile_rows,
        "time_blocks": periods,
        "active_date_records": records,
    }


def event_contribution_bridge(
    control: dict[str, Any], bridge: dict[str, Any]
) -> dict[str, Any]:
    q_by_date = {row["entry_date"]: row["count_rank_q"] for row in bridge["active_date_records"]}
    rows = []
    total_positive = sum(max(trade["gross_trade_return"], 0.0) for trade in control["trades"])
    total_event_return = sum(trade["gross_trade_return"] for trade in control["trades"])
    for q in range(1, 6):
        trades = [trade for trade in control["trades"] if q_by_date[trade["entry_date"]] == q]
        positive = sum(max(trade["gross_trade_return"], 0.0) for trade in trades)
        contribution = sum(trade["gross_trade_return"] for trade in trades)
        rows.append(
            {
                "count_rank_q": q,
                "events": len(trades),
                "event_share": len(trades) / len(control["trades"]),
                "sum_event_returns": contribution,
                "share_of_total_event_return": contribution / total_event_return if total_event_return else None,
                "positive_event_return_contribution": positive,
                "share_of_positive_event_return": positive / total_positive if total_positive else None,
            }
        )
    high = rows[-1]
    return {
        "event_weighted_mean_gross_return": float(
            np.mean([trade["gross_trade_return"] for trade in control["trades"]])
        ),
        "date_weighted_mean_basket_return": bridge["overall"]["mean_basket_return"],
        "total_event_return": total_event_return,
        "total_positive_event_return": total_positive,
        "count_rank_quintiles": rows,
        "highest_count_dates": high,
        "remaining_dates": {
            "events": len(control["trades"]) - high["events"],
            "sum_event_returns": total_event_return - high["sum_event_returns"],
            "positive_event_return_contribution": total_positive - high["positive_event_return_contribution"],
            "share_of_positive_event_return": 1.0 - high["share_of_positive_event_return"],
        },
    }


def extended_metrics(simulation: dict[str, Any], active_dates: int) -> dict[str, Any]:
    output = v5.portfolio_metrics(simulation)
    daily = simulation["daily"]
    output.update(
        {
            "median_exposure": float(np.median([row["exposure"] for row in daily])),
            "maximum_exposure": max(row["exposure"] for row in daily),
            "minimum_cash_ratio": min(row["cash_weight"] for row in daily),
            "active_entry_dates": active_dates,
        }
    )
    return output


def budget_diagnostics(
    treatment: dict[str, Any], bridge: dict[str, Any]
) -> dict[str, Any]:
    allocations = treatment["daily_allocations"]
    q_by_date = {row["entry_date"]: row["count_rank_q"] for row in bridge["active_date_records"]}
    daily_by_date = {row["trade_date"]: row for row in treatment["daily"]}
    desired = sum(row["desired_budget"] for row in allocations)
    blocked = sum(row["budget_shortfall"] for row in allocations)
    for row in allocations:
        daily = daily_by_date[row["entry_date"]]
        row["resulting_close_exposure"] = daily["exposure"]
        row["resulting_close_cash_weight"] = daily["cash_weight"]
        row["count_rank_q"] = q_by_date[row["entry_date"]]
    high = [row for row in allocations if row["count_rank_q"] == 5]
    high_desired = sum(row["desired_budget"] for row in high)
    high_blocked = sum(row["budget_shortfall"] for row in high)

    pnl_by_regime: dict[str, float] = defaultdict(float)
    notionals_by_regime: dict[str, list[float]] = defaultdict(list)
    weights_by_regime: dict[str, list[float]] = defaultdict(list)
    for trade in treatment["trades"]:
        regime = count_regime(trade["signal_day_n"])
        pnl_by_regime[regime] += trade["realized_pnl"]
        notionals_by_regime[regime].append(trade["initial_notional"])
        weights_by_regime[regime].append(trade["entry_weight_of_opening_nav"])
    total_pnl = sum(trade["realized_pnl"] for trade in treatment["trades"])
    high_pnl = sum(trade["realized_pnl"] for trade in treatment["trades"] if q_by_date[trade["entry_date"]] == 5)
    return {
        "active_dates": len(allocations),
        "desired_above_control_fraction": float(np.mean([row["desired_budget"] > row["control_desired_budget"] + 1e-15 for row in allocations])),
        "desired_below_control_fraction": float(np.mean([row["desired_budget"] + 1e-15 < row["control_desired_budget"] for row in allocations])),
        "cash_constraint_frequency": float(np.mean([row["cash_constrained"] for row in allocations])),
        "total_desired_budget": desired,
        "total_actual_budget": sum(row["actual_entry_notional"] for row in allocations),
        "total_budget_shortfall": blocked,
        "fraction_requested_budget_blocked": blocked / desired,
        "highest_count_q5": {
            "active_dates": len(high),
            "total_desired_budget": high_desired,
            "total_budget_shortfall": high_blocked,
            "fraction_requested_budget_blocked": high_blocked / high_desired,
            "cash_constraint_frequency": float(np.mean([row["cash_constrained"] for row in high])),
        },
        "gross_realized_pnl": total_pnl,
        "highest_count_q5_gross_realized_pnl": high_pnl,
        "highest_count_q5_pnl_share": high_pnl / total_pnl if total_pnl else None,
        "pnl_by_count_regime": dict(pnl_by_regime),
        "average_per_position_allocation_by_count_regime": {
            regime: {
                "trades": len(notionals_by_regime[regime]),
                "average_notional": float(np.mean(notionals_by_regime[regime])) if notionals_by_regime[regime] else None,
                "average_opening_nav_weight": float(np.mean(weights_by_regime[regime])) if weights_by_regime[regime] else None,
            }
            for regime in COUNT_REGIMES
        },
        "active_date_records": allocations,
    }


def stability(
    control: dict[str, Any], treatment: dict[str, Any], bridge: dict[str, Any]
) -> list[dict[str, Any]]:
    basket_by_block = {row["time_block"]: row for row in bridge["time_blocks"]}
    output = []
    for label, start, end in (
        ("2018-2020", date(2018, 1, 1), date(2020, 12, 31)),
        ("2021-2023", date(2021, 1, 1), date(2023, 12, 31)),
        ("2024-2026", date(2024, 1, 1), date(2026, 12, 31)),
    ):
        control_metrics = v5._slice_metrics(control, start, end)
        treatment_metrics = v5._slice_metrics(treatment, start, end)
        allocations = [row for row in treatment["daily_allocations"] if start <= row["entry_date"] <= end]
        basket = basket_by_block[label]
        output.append(
            {
                "time_block": label,
                "active_dates": basket["active_dates"],
                "signals": basket["signals"],
                "count_return_spearman": basket["spearman"],
                "count_return_pearson": basket["pearson"],
                "control_gross_return": control_metrics["cumulative_return"],
                "treatment_gross_return": treatment_metrics["cumulative_return"],
                "treatment_minus_control": treatment_metrics["cumulative_return"] - control_metrics["cumulative_return"],
                "control_average_exposure": control_metrics["average_exposure"],
                "treatment_average_exposure": treatment_metrics["average_exposure"],
                "treatment_cash_constraint_frequency": float(np.mean([row["cash_constrained"] for row in allocations])),
            }
        )
    return output


def major_drawdowns(control: dict[str, Any], treatment: dict[str, Any], limit: int = 3) -> list[dict[str, Any]]:
    rows = control["daily"]
    treatment_nav = {row["trade_date"]: row["nav"] for row in treatment["daily"]}
    nav = np.asarray([row["nav"] for row in rows], dtype=float)
    peak_index = 0
    episodes: dict[int, tuple[int, float]] = {}
    for index, value in enumerate(nav):
        if value >= nav[peak_index]:
            peak_index = index
        dd = value / nav[peak_index] - 1.0
        if peak_index not in episodes or dd < episodes[peak_index][1]:
            episodes[peak_index] = (index, dd)
    output = []
    for peak, (trough, dd) in sorted(episodes.items(), key=lambda item: item[1][1])[:limit]:
        peak_date = rows[peak]["trade_date"]
        trough_date = rows[trough]["trade_date"]
        treatment_peak = treatment_nav[peak_date]
        treatment_dd = min(treatment_nav[row["trade_date"]] / treatment_peak - 1.0 for row in rows[peak : trough + 1])
        output.append(
            {
                "control_peak_date": peak_date,
                "control_trough_date": trough_date,
                "control_drawdown": dd,
                "treatment_same_period_drawdown": treatment_dd,
            }
        )
    return output


def control_reproduction(control: dict[str, Any]) -> dict[str, Any]:
    authoritative = json.loads((DEFAULT_OUTPUT / "v5_portfolio_results.json").read_text())
    expected = authoritative["portfolio_metrics"]["EQUAL_SIZE:GROSS"]
    actual = v5.portfolio_metrics(control)
    fields = ("ending_nav", "cumulative_return", "cagr", "annualized_volatility", "max_drawdown", "average_exposure", "entries")
    differences = {field: actual[field] - expected[field] for field in fields}
    return {
        "authoritative_v5_commit": STARTING_HEAD,
        "expected": {field: expected[field] for field in fields},
        "reproduced": {field: actual[field] for field in fields},
        "differences": differences,
        "maximum_absolute_difference": max(abs(value) for value in differences.values()),
    }


def result_checks(
    events: list[dict[str, Any]],
    cluster_reference: list[dict[str, Any]],
    control: dict[str, Any],
    treatment: dict[str, Any],
    reproduction: dict[str, Any],
) -> dict[str, Any]:
    checks: dict[str, Any] = {
        "event_count_difference": len(events) - EXPECTED_EVENTS,
        "active_count_sum_difference": sum(row["signal_count"] for row in cluster_reference) - len(events),
        "duplicate_active_dates": len(cluster_reference) - len({row["entry_date"] for row in cluster_reference}),
        "nonpositive_counts": sum(row["signal_count"] <= 0 for row in cluster_reference),
        "same_day_median_inclusions": 0,
        "warmup_rule_violations": 0,
        "post_warmup_median_violations": 0,
        "control_reproduction_violation": int(reproduction["maximum_absolute_difference"] > 1e-14),
    }
    history: list[int] = []
    for row in cluster_reference:
        if row["prior_active_dates"] != len(history):
            checks["same_day_median_inclusions"] += 1
        if len(history) < WARMUP_PRIOR_ACTIVE_DATES:
            if not row["warmup"] or row["prior_median_positive_count"] is not None or row["count_ratio"] != 1.0:
                checks["warmup_rule_violations"] += 1
        else:
            expected = float(median(history))
            if row["warmup"] or row["prior_median_positive_count"] != expected or not math.isclose(row["count_ratio"], row["signal_count"] / expected):
                checks["post_warmup_median_violations"] += 1
        history.append(row["signal_count"])
    for name, simulation in (("control", control), ("treatment", treatment)):
        checks[f"{name}_signal_reconciliation_difference"] = (
            simulation["flow"]["entered"]
            + simulation["flow"]["missed_for_zero_cash"]
            + simulation["flow"].get("overlapping_security_skips", 0)
            + simulation["flow"].get("invalid_entry_price", 0)
            - len(events)
        )
        checks[f"{name}_entry_exit_difference"] = (
            simulation["flow"]["entered"] - len(simulation["trades"])
        )
        checks[f"{name}_negative_cash_days"] = sum(row["cash"] < -1e-12 for row in simulation["daily"])
        checks[f"{name}_leverage_days"] = sum(row["exposure"] > 1.0 + 1e-12 for row in simulation["daily"])
        checks[f"{name}_nav_identity_violations"] = sum(abs(row["nav"] - row["cash"] - row["market_value"]) > 1e-12 for row in simulation["daily"])
        checks[f"{name}_entry_chronology_violations"] = sum(trade["entry_date"] <= trade["signal_date"] for trade in simulation["trades"])
        checks[f"{name}_exit_chronology_violations"] = sum(trade["actual_exit_date"] < trade["scheduled_exit_date"] for trade in simulation["trades"])
        checks[f"{name}_holding_contract_violations"] = sum(trade["holding_sessions"] != v5.HOLDING_SESSIONS + trade["exit_delay_sessions"] for trade in simulation["trades"])
    checks["treatment_allocation_date_difference"] = len(treatment["daily_allocations"]) - len(cluster_reference)
    checks["treatment_budget_identity_violations"] = sum(
        not math.isclose(row["desired_budget"] - row["actual_entry_notional"], row["budget_shortfall"], abs_tol=1e-12)
        or row["actual_entry_notional"] > row["available_cash"] + 1e-12
        for row in treatment["daily_allocations"]
    )
    failures = {key: value for key, value in checks.items() if value != 0}
    if failures:
        raise RuntimeError(f"V6 result invariants failed: {failures}")
    return checks


def collect_results(
    events: list[dict[str, Any]],
    prices: dict[tuple[str, date], dict[str, Any]],
    calendar: list[date],
) -> tuple[dict[str, Any], dict[str, Any]]:
    cluster_reference = assign_causal_cluster_reference(events)
    control = v5.simulate_portfolio(policy="EQUAL_SIZE", cost_mode="GROSS", events=events, prices=prices, calendar=calendar)
    treatment = simulate_count_aware(events=events, prices=prices, calendar=calendar, cluster_reference=cluster_reference)
    reproduction = control_reproduction(control)
    bridge = count_return_bridge(control, cluster_reference)
    contribution = event_contribution_bridge(control, bridge)
    active_dates = len(cluster_reference)
    payload = {
        "research_version": "oversold-reversal-ranking-v6-cluster-capital",
        "verdict": VERDICT,
        "single_next_step": SINGLE_NEXT_STEP,
        "definitions": {
            "predecessor_verdicts": {"v1": "DEPTH_ONLY", "v2": "RISK_FILTER_ONLY", "v3": "SIZING_SIGNAL_ONLY", "v4": "SIZING_SURVIVES", "v5": "EVENT_ALPHA_COLLAPSES"},
            "carrier": "exact V1 LOW plus causal drawdown_60 <= -30%; exact valid V5 event stream",
            "control": "authoritative V5 EQUAL_SIZE:GROSS; 5% opening NAV desired per active entry date; equal within-date split",
            "treatment": "5% opening NAV * (N_t / M_t), capped by available cash; equal within-date split",
            "N_t": "number of frozen qualifying events scheduled for entry date t, known before that legal entry open",
            "M_t": "median positive N across strictly prior active entry dates; current date excluded",
            "warmup": "fewer than 60 prior active entry dates: neutral N_t/M_t multiplier 1.0",
            "cost_basis": "gross; zero transaction costs",
            "holding_exit": "hold t0+1 through t0+20, then sell first legal open on/after t0+21",
        },
        "sample_profile": {
            "events": len(events),
            "securities": len({row["symbol"] for row in events}),
            "active_entry_dates": active_dates,
            "first_signal_date": min(row["signal_date"] for row in events),
            "last_signal_date": max(row["signal_date"] for row in events),
            "first_entry_date": min(row["entry_date"] for row in events),
            "last_legal_exit_date": max(row["first_legal_exit_date"] for row in events),
        },
        "control_reproduction": reproduction,
        "signal_count_distribution": count_distribution(cluster_reference),
        "count_forward_return": bridge,
        "event_alpha_contribution": contribution,
        "portfolio_metrics": {
            "V5_EQUAL_GROSS_CONTROL": extended_metrics(control, active_dates),
            "V6_COUNT_AWARE_EQUAL_GROSS": extended_metrics(treatment, active_dates),
        },
        "signal_flow": {
            "V5_EQUAL_GROSS_CONTROL": control["flow"],
            "V6_COUNT_AWARE_EQUAL_GROSS": treatment["flow"],
        },
        "portfolio_comparison": {},
        "annual_returns": {
            "V5_EQUAL_GROSS_CONTROL": v5.annual_returns(control),
            "V6_COUNT_AWARE_EQUAL_GROSS": v5.annual_returns(treatment),
        },
        "budget_diagnostics": budget_diagnostics(treatment, bridge),
        "time_stability": stability(control, treatment, bridge),
        "major_drawdown_episodes": major_drawdowns(control, treatment),
    }
    control_metrics = payload["portfolio_metrics"]["V5_EQUAL_GROSS_CONTROL"]
    treatment_metrics = payload["portfolio_metrics"]["V6_COUNT_AWARE_EQUAL_GROSS"]
    for field in ("ending_nav", "cumulative_return", "cagr", "annualized_volatility", "max_drawdown", "sharpe_like", "calmar", "average_exposure", "median_exposure", "maximum_exposure", "average_cash_weight", "minimum_cash_ratio", "annualized_turnover", "average_concurrent_positions", "maximum_concurrent_positions", "average_largest_position_weight", "maximum_largest_position_weight", "average_top5_concentration", "maximum_top5_concentration"):
        payload["portfolio_comparison"][field] = {
            "control": control_metrics[field],
            "treatment": treatment_metrics[field],
            "difference": treatment_metrics[field] - control_metrics[field] if treatment_metrics[field] is not None and control_metrics[field] is not None else None,
        }
    payload["checks"] = result_checks(events, cluster_reference, control, treatment, reproduction)
    return payload, {"events": events, "cluster_reference": cluster_reference, "control": control, "treatment": treatment}


def run(*, output_dir: Path = DEFAULT_OUTPUT, hash_data_files: bool = True, write_output: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
    config = json.loads(v5.PREDECESSOR_CONFIG.read_text())
    config["research_version"] = "oversold-reversal-ranking-v6-cluster-capital"
    identities = v5.validate_inputs(config, hash_data_files=hash_data_files)
    with tempfile.TemporaryDirectory(prefix="oversold-cluster-v6-") as temp_dir:
        con = duckdb.connect()
        con.execute(f"SET threads={int(config['runtime']['threads'])}")
        con.execute(f"SET memory_limit='{config['runtime']['memory_limit']}'")
        con.execute(f"SET temp_directory='{temp_dir}'")
        con.execute("SET preserve_insertion_order=false")
        v5.create_analysis_tables(con, config)
        v5.create_timing_tables(con)
        v5.create_risk_tables(con)
        v5.create_portfolio_tables(con, config)
        events, prices, calendar = v5._load_inputs(con)
        payload, internals = collect_results(events, prices, calendar)
        payload["input_identities"] = identities
        con.close()
    if write_output:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "v6_cluster_results.json").write_text(json.dumps(payload, indent=2, default=v5.json_default) + "\n")
    return payload, internals


def preview(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "control_reproduction": payload["control_reproduction"],
        "count_distribution": payload["signal_count_distribution"],
        "count_forward_overall": payload["count_forward_return"]["overall"],
        "count_quintiles": payload["count_forward_return"]["count_rank_quintiles"],
        "event_contribution": payload["event_alpha_contribution"],
        "portfolio_metrics": payload["portfolio_metrics"],
        "budget_diagnostics": {key: value for key, value in payload["budget_diagnostics"].items() if key != "active_date_records"},
        "time_stability": payload["time_stability"],
        "checks": payload["checks"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-hash", action="store_true")
    parser.add_argument("--preview-only", action="store_true")
    args = parser.parse_args()
    payload, _ = run(output_dir=args.output_dir, hash_data_files=not args.skip_hash, write_output=not args.preview_only)
    print(json.dumps(preview(payload), indent=2, default=v5.json_default))


if __name__ == "__main__":
    main()
