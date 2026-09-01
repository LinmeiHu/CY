#!/usr/bin/env python3
"""V7: finite-capital realization of causal deep-oversold cluster episodes."""

# Explicit chronology and state are intentional: episode and cash invariants must be auditable.
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
from research.oversold_reversal_ranking import v6_cluster_capital as v6

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "reports"
STARTING_HEAD = "5219e5bf7b592be0c4b2fcf868e8779e71e64140"
EXPECTED_EVENTS = 22_357
EPISODE_SESSIONS = v5.HOLDING_SESSIONS
EPISODE_ENVELOPE_FRACTION = 1.0
BASE_REQUEST_FRACTION = v6.BASE_BUDGET_FRACTION

# Set after the single frozen broad run; no experimental rule branches on these labels.
VERDICT = "EPISODE_STRUCTURE_EXISTS_BUT_NOT_INVESTABLE"
SINGLE_NEXT_STEP = "Close the deep-oversold capitalization lane and preserve V1-V7 as frozen evidence; do not run further architecture, threshold, leverage, holding-period, factor, or machine-learning rescue tests."


def assign_episode_schedule(
    cluster_reference: list[dict[str, Any]],
    events: list[dict[str, Any]],
    calendar: list[date],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Assign causal, nonoverlapping 20-session episodes to active entry dates."""
    calendar_index = {trade_date: index for index, trade_date in enumerate(calendar)}
    signal_dates: dict[date, list[date]] = defaultdict(list)
    for event in events:
        signal_dates[event["entry_date"]].append(event["signal_date"])
    episodes: list[dict[str, Any]] = []
    schedule: list[dict[str, Any]] = []
    active_episode: dict[str, Any] | None = None
    for original in sorted(cluster_reference, key=lambda row: row["entry_date"]):
        row = dict(original)
        trade_date = row["entry_date"]
        index = calendar_index[trade_date]
        if active_episode is not None and index > active_episode["end_calendar_index"]:
            active_episode = None
        high = bool(not row["warmup"] and row["count_ratio"] > 1.0)
        if active_episode is None and high:
            end_index = index + EPISODE_SESSIONS - 1
            if end_index >= len(calendar):
                raise RuntimeError(f"insufficient episode calendar after {trade_date}")
            active_episode = {
                "episode_id": len(episodes) + 1,
                "episode_start_signal_date": max(signal_dates[trade_date]),
                "episode_start_entry_date": trade_date,
                "episode_end_date": calendar[end_index],
                "start_calendar_index": index,
                "end_calendar_index": end_index,
                "episode_sessions": EPISODE_SESSIONS,
            }
            episodes.append(dict(active_episode))
        episode_id = active_episode["episode_id"] if active_episode is not None else None
        episode_session = (
            index - active_episode["start_calendar_index"] + 1
            if active_episode is not None
            else None
        )
        row.update(
            {
                "high_intensity": high,
                "episode_id": episode_id,
                "episode_session": episode_session,
            }
        )
        schedule.append(row)
    return schedule, episodes


def simulate_episode_portfolio(
    *,
    events: list[dict[str, Any]],
    prices: dict[tuple[str, date], dict[str, Any]],
    calendar: list[date],
    schedule: list[dict[str, Any]],
    episode_specs: list[dict[str, Any]],
    initial_nav: float = v5.INITIAL_NAV,
) -> dict[str, Any]:
    """Replay V5 gross mechanics under the one-envelope episode architecture."""
    schedule_by_date = {row["entry_date"]: row for row in schedule}
    spec_by_start = {row["episode_start_entry_date"]: row for row in episode_specs}
    signals: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        signals[event["entry_date"]].append(event)
    for rows in signals.values():
        rows.sort(key=lambda row: (row["symbol"], row["event_id"]))

    cash = float(initial_nav)
    positions: dict[str, dict[str, Any]] = {}
    last_marks: dict[str, float] = {}
    runtime_episodes: dict[int, dict[str, Any]] = {}
    daily: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    allocations: list[dict[str, Any]] = []
    flow = {
        "signals": 0,
        "high_intensity_signals": 0,
        "low_intensity_skips": 0,
        "entered": 0,
        "missed_for_zero_cash": 0,
        "missed_for_exhausted_envelope": 0,
        "overlapping_security_skips": 0,
        "invalid_entry_price": 0,
        "cash_constrained_dates": 0,
        "envelope_limited_dates": 0,
        "active_signal_dates": 0,
        "deployed_entry_dates": 0,
        "full_intended_signals": 0,
        "partial_intended_signals": 0,
    }

    for trade_date in calendar:
        opening_market_value = 0.0
        for symbol, lot in positions.items():
            price = v5._price(prices, symbol, trade_date)
            mark = v5._finite_float(price["adjusted_open"]) if price is not None else last_marks[symbol]
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

        if trade_date in spec_by_start:
            spec = spec_by_start[trade_date]
            runtime_episodes[spec["episode_id"]] = {
                **spec,
                "episode_start_nav": opening_nav,
                "episode_start_cash": cash,
                "episode_envelope": EPISODE_ENVELOPE_FRACTION * opening_nav,
                "cumulative_deployed": 0.0,
            }

        today_signals = signals.get(trade_date, [])
        flow["signals"] += len(today_signals)
        entry_notional = 0.0
        if today_signals:
            flow["active_signal_dates"] += 1
            state = schedule_by_date[trade_date]
            if state["signal_count"] != len(today_signals):
                raise RuntimeError(f"signal count mismatch on {trade_date}")
            high = state["high_intensity"]
            if high:
                flow["high_intensity_signals"] += len(today_signals)
            else:
                flow["low_intensity_skips"] += len(today_signals)

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

            raw_request = 0.0
            remaining_envelope = 0.0
            episode_request = 0.0
            available_cash = cash
            deployed = 0.0
            cash_blocked = 0.0
            envelope_limited = 0.0
            if high:
                episode_id = state["episode_id"]
                if episode_id is None:
                    raise RuntimeError(f"high-intensity date outside episode: {trade_date}")
                episode = runtime_episodes[episode_id]
                raw_request = BASE_REQUEST_FRACTION * episode["episode_start_nav"] * state["count_ratio"]
                remaining_envelope = max(episode["episode_envelope"] - episode["cumulative_deployed"], 0.0)
                episode_request = min(raw_request, remaining_envelope)
                envelope_limited = raw_request - episode_request
                deployed = min(episode_request, available_cash)
                cash_blocked = episode_request - deployed
                if envelope_limited > 1e-15:
                    flow["envelope_limited_dates"] += 1
                if cash_blocked > 1e-15:
                    flow["cash_constrained_dates"] += 1
                if episode_request <= 1e-15:
                    flow["missed_for_exhausted_envelope"] += len(executable)
                elif deployed <= 1e-15:
                    flow["missed_for_zero_cash"] += len(executable)
                elif deployed + 1e-15 < episode_request:
                    flow["partial_intended_signals"] += len(executable)
                else:
                    flow["full_intended_signals"] += len(executable)
                if deployed > 1e-15:
                    per_event = deployed / len(executable)
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
                            "policy": "EPISODE_EQUAL",
                            "cost_mode": "GROSS",
                            "episode_id": episode_id,
                            "episode_session": state["episode_session"],
                            "entry_adjusted_open": entry_price,
                            "initial_notional": per_event,
                            "units": per_event / entry_price,
                            "entry_cost": 0.0,
                            "signal_day_n": len(today_signals),
                            "entry_weight_of_opening_nav": per_event / opening_nav,
                            "exit_delay_sessions": int(event["expected_exit_delay_sessions"] or 0),
                        }
                        positions[event["symbol"]] = lot
                        entry_notional += per_event
                        flow["entered"] += 1
                    episode["cumulative_deployed"] += deployed
                    flow["deployed_entry_dates"] += 1
            allocations.append(
                {
                    **state,
                    "opening_nav": opening_nav,
                    "available_cash": available_cash,
                    "raw_request": raw_request,
                    "remaining_envelope_before": remaining_envelope,
                    "episode_request": episode_request,
                    "deployed_capital": deployed,
                    "cash_blocked_capital": cash_blocked,
                    "envelope_limited_capital": envelope_limited,
                    "qualifying_signals": len(today_signals),
                    "entered_signals": len(executable) if deployed > 1e-15 else 0,
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
        if close_nav <= 0:
            raise RuntimeError(f"nonpositive close NAV on {trade_date}")
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
                "entries": len(today_signals) if entry_notional > 0 else 0,
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
        "policy": "EPISODE_EQUAL",
        "cost_mode": "GROSS",
        "initial_nav": initial_nav,
        "daily": daily,
        "trades": trades,
        "flow": flow,
        "daily_allocations": allocations,
        "episodes": [runtime_episodes[key] for key in sorted(runtime_episodes)],
    }


def reproduce_controls(
    v5_control: dict[str, Any], v6_control: dict[str, Any]
) -> dict[str, Any]:
    expected_v5 = json.loads((DEFAULT_OUTPUT / "v5_portfolio_results.json").read_text())["portfolio_metrics"]["EQUAL_SIZE:GROSS"]
    expected_v6 = json.loads((DEFAULT_OUTPUT / "v6_cluster_results.json").read_text())["portfolio_metrics"]["V6_COUNT_AWARE_EQUAL_GROSS"]
    fields = ("ending_nav", "cumulative_return", "cagr", "annualized_volatility", "max_drawdown", "average_exposure", "entries")
    output: dict[str, Any] = {}
    for name, simulation, expected in (("V5_EQUAL_GROSS", v5_control, expected_v5), ("V6_COUNT_AWARE_GROSS", v6_control, expected_v6)):
        actual = v5.portfolio_metrics(simulation)
        differences = {field: actual[field] - expected[field] for field in fields}
        output[name] = {
            "expected": {field: expected[field] for field in fields},
            "reproduced": {field: actual[field] for field in fields},
            "differences": differences,
            "maximum_absolute_difference": max(abs(value) for value in differences.values()),
        }
    return output


def _episode_drawdown(rows: list[dict[str, Any]], start_nav: float) -> float:
    values = np.asarray([start_nav, *[row["nav"] for row in rows]], dtype=float)
    return float(np.min(values / np.maximum.accumulate(values) - 1.0))


def episode_diagnostics(
    treatment: dict[str, Any],
    schedule: list[dict[str, Any]],
    control: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    allocations_by_episode: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in treatment["daily_allocations"]:
        if row["episode_id"] is not None:
            allocations_by_episode[row["episode_id"]].append(row)
    trades_by_episode: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for trade in treatment["trades"]:
        trades_by_episode[trade["episode_id"]].append(trade)
    control_return_by_id = {trade["event_id"]: trade["gross_trade_return"] for trade in control["trades"]}
    events_by_date: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for trade in control["trades"]:
        events_by_date[trade["entry_date"]].append(trade)
    daily = treatment["daily"]

    output = []
    for episode in treatment["episodes"]:
        episode_id = episode["episode_id"]
        rows = allocations_by_episode[episode_id]
        high_rows = [row for row in rows if row["high_intensity"]]
        low_rows = [row for row in rows if not row["high_intensity"]]
        entered = trades_by_episode[episode_id]
        lifecycle = [row for row in daily if episode["episode_start_entry_date"] <= row["trade_date"] <= episode["episode_end_date"]]
        high_events = [event for row in high_rows for event in events_by_date[row["entry_date"]]]
        all_events = [event for row in rows for event in events_by_date[row["entry_date"]]]
        pnl = sum(trade["realized_pnl"] for trade in entered)
        cash_blocked = sum(row["cash_blocked_capital"] for row in high_rows)
        request = sum(row["episode_request"] for row in high_rows)
        deployed = sum(row["deployed_capital"] for row in high_rows)
        output.append(
            {
                "episode_id": episode_id,
                "episode_start_signal_date": episode["episode_start_signal_date"],
                "episode_start_entry_date": episode["episode_start_entry_date"],
                "episode_end_date": episode["episode_end_date"],
                "episode_start_nav": episode["episode_start_nav"],
                "episode_start_cash": episode["episode_start_cash"],
                "episode_envelope": episode["episode_envelope"],
                "high_intensity_dates": len(high_rows),
                "low_intensity_active_dates": len(low_rows),
                "total_qualifying_events": sum(row["qualifying_signals"] for row in rows),
                "high_intensity_events": sum(row["qualifying_signals"] for row in high_rows),
                "maximum_n": max(row["signal_count"] for row in high_rows),
                "median_n": float(median(row["signal_count"] for row in high_rows)),
                "mean_intensity": float(np.mean([row["count_ratio"] for row in high_rows])),
                "maximum_intensity": max(row["count_ratio"] for row in high_rows),
                "cumulative_raw_request": sum(row["raw_request"] for row in high_rows),
                "cumulative_requested_capital": request,
                "cumulative_deployed_capital": deployed,
                "cumulative_cash_blocked_capital": cash_blocked,
                "cumulative_envelope_limited_capital": sum(row["envelope_limited_capital"] for row in high_rows),
                "envelope_utilization": deployed / episode["episode_envelope"],
                "cash_blocked_fraction": cash_blocked / request if request else 0.0,
                "signals_zero_by_low_intensity_rule": sum(row["qualifying_signals"] for row in low_rows),
                "high_intensity_signals_zero_for_cash": sum(row["qualifying_signals"] for row in high_rows if row["episode_request"] > 1e-15 and row["deployed_capital"] <= 1e-15),
                "high_intensity_signals_zero_for_envelope": sum(row["qualifying_signals"] for row in high_rows if row["episode_request"] <= 1e-15),
                "entered_signals": len(entered),
                "average_exposure": float(np.mean([row["exposure"] for row in lifecycle])),
                "maximum_exposure": max(row["exposure"] for row in lifecycle),
                "episode_gross_pnl": pnl,
                "episode_gross_return": pnl / episode["episode_start_nav"],
                "maximum_episode_drawdown": _episode_drawdown(lifecycle, episode["episode_start_nav"]),
                "high_intensity_equal_weight_forward_return": float(np.mean([control_return_by_id[event["event_id"]] for event in high_events])),
                "all_active_date_equal_weight_forward_return": float(np.mean([control_return_by_id[event["event_id"]] for event in all_events])),
            }
        )
    pnls = np.asarray([row["episode_gross_pnl"] for row in output], dtype=float)
    positive = sorted((value for value in pnls if value > 0), reverse=True)
    positive_total = sum(positive)
    top_ten_n = max(1, math.ceil(len(output) * 0.10))
    total_deployed = sum(row["cumulative_deployed_capital"] for row in output)
    total_pnl = float(np.sum(pnls))
    for row in output:
        row["capital_allocation_share"] = (
            row["cumulative_deployed_capital"] / total_deployed
            if total_deployed
            else None
        )
        row["pnl_contribution_share"] = (
            row["episode_gross_pnl"] / total_pnl if total_pnl else None
        )
        row["positive_pnl_contribution_share"] = (
            max(row["episode_gross_pnl"], 0.0) / positive_total
            if positive_total
            else None
        )
    high_date_counts = np.asarray(
        [row["high_intensity_dates"] for row in output], dtype=float
    )
    event_counts = np.asarray(
        [row["total_qualifying_events"] for row in output], dtype=float
    )
    utilizations = np.asarray(
        [row["envelope_utilization"] for row in output], dtype=float
    )
    blocked_fractions = np.asarray(
        [row["cash_blocked_fraction"] for row in output], dtype=float
    )
    summary = {
        "episodes": len(output),
        "profitable_episodes": int(np.sum(pnls > 0)),
        "episode_win_rate": float(np.mean(pnls > 0)),
        "mean_episode_pnl": float(np.mean(pnls)),
        "median_episode_pnl": float(np.median(pnls)),
        "mean_episode_gross_return": float(np.mean([row["episode_gross_return"] for row in output])),
        "mean_high_intensity_basket_forward_return": float(np.mean([row["high_intensity_equal_weight_forward_return"] for row in output])),
        "total_episode_pnl": total_pnl,
        "positive_episode_pnl": positive_total,
        "fraction_total_pnl_from_profitable_episodes": positive_total / float(np.sum(pnls)) if float(np.sum(pnls)) else None,
        "positive_pnl_share_top_episode": positive[0] / positive_total if positive_total else None,
        "positive_pnl_share_top_five": sum(positive[:5]) / positive_total if positive_total else None,
        "positive_pnl_share_top_ten_percent": sum(positive[:top_ten_n]) / positive_total if positive_total else None,
        "mean_high_intensity_dates": float(np.mean([row["high_intensity_dates"] for row in output])),
        "mean_total_qualifying_events": float(np.mean([row["total_qualifying_events"] for row in output])),
        "mean_envelope_utilization": float(np.mean([row["envelope_utilization"] for row in output])),
        "median_envelope_utilization": float(np.median([row["envelope_utilization"] for row in output])),
        "mean_cash_blocked_fraction": float(np.mean([row["cash_blocked_fraction"] for row in output])),
        "cross_episode_distribution": {
            "high_intensity_dates": {
                "mean": float(np.mean(high_date_counts)),
                "median": float(np.median(high_date_counts)),
                "p90": float(np.quantile(high_date_counts, 0.90)),
                "maximum": int(np.max(high_date_counts)),
            },
            "total_qualifying_events": {
                "mean": float(np.mean(event_counts)),
                "median": float(np.median(event_counts)),
                "p90": float(np.quantile(event_counts, 0.90)),
                "maximum": int(np.max(event_counts)),
            },
            "envelope_utilization": {
                "mean": float(np.mean(utilizations)),
                "median": float(np.median(utilizations)),
                "p90": float(np.quantile(utilizations, 0.90)),
                "maximum": float(np.max(utilizations)),
            },
            "cash_blocked_fraction": {
                "mean": float(np.mean(blocked_fractions)),
                "median": float(np.median(blocked_fractions)),
                "p90": float(np.quantile(blocked_fractions, 0.90)),
                "maximum": float(np.max(blocked_fractions)),
            },
        },
    }
    return output, summary


def saturation_diagnostics(
    treatment: dict[str, Any], schedule: list[dict[str, Any]]
) -> dict[str, Any]:
    high = [row for row in treatment["daily_allocations"] if row["high_intensity"]]
    ordered = sorted(high, key=lambda row: (row["count_ratio"], row["entry_date"]))
    top_indexes = np.array_split(np.arange(len(ordered)), 5)[-1]
    top = [ordered[int(index)] for index in top_indexes]

    def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
        requested = sum(row["episode_request"] for row in rows)
        blocked = sum(row["cash_blocked_capital"] for row in rows)
        signals = sum(row["qualifying_signals"] for row in rows)
        any_alloc = sum(row["qualifying_signals"] for row in rows if row["deployed_capital"] > 1e-15)
        full_alloc = sum(row["qualifying_signals"] for row in rows if row["episode_request"] > 1e-15 and math.isclose(row["deployed_capital"], row["episode_request"], abs_tol=1e-15))
        return {
            "dates": len(rows),
            "signals": signals,
            "total_raw_request": sum(row["raw_request"] for row in rows),
            "total_requested_episode_capital": requested,
            "total_deployed_capital": sum(row["deployed_capital"] for row in rows),
            "total_cash_blocked_capital": blocked,
            "total_envelope_limited_capital": sum(row["envelope_limited_capital"] for row in rows),
            "cash_blocked_percentage": blocked / requested if requested else 0.0,
            "raw_request_not_deployed_percentage": (
                (sum(row["raw_request"] for row in rows) - sum(row["deployed_capital"] for row in rows))
                / sum(row["raw_request"] for row in rows)
                if sum(row["raw_request"] for row in rows)
                else 0.0
            ),
            "zero_allocation_signals_cash": sum(row["qualifying_signals"] for row in rows if row["episode_request"] > 1e-15 and row["deployed_capital"] <= 1e-15),
            "zero_allocation_signals_envelope": sum(row["qualifying_signals"] for row in rows if row["episode_request"] <= 1e-15),
            "fraction_high_intensity_signals_any_allocation": any_alloc / signals,
            "fraction_high_intensity_signals_full_intended_allocation": full_alloc / signals,
        }

    low_signals = sum(row["signal_count"] for row in schedule if not row["high_intensity"])
    return {
        "all_high_intensity_dates": summarize(high),
        "highest_intensity_rank_fifth": summarize(top),
        "low_intensity_signals_zero_by_rule": low_signals,
    }


def capital_timing(
    treatment: dict[str, Any], control: dict[str, Any]
) -> list[dict[str, Any]]:
    basket: dict[date, float] = defaultdict(float)
    grouped: dict[date, list[float]] = defaultdict(list)
    for trade in control["trades"]:
        grouped[trade["entry_date"]].append(trade["gross_trade_return"])
    for trade_date, values in grouped.items():
        basket[trade_date] = float(np.mean(values))
    output = []
    high = [row for row in treatment["daily_allocations"] if row["high_intensity"]]
    for session in range(1, EPISODE_SESSIONS + 1):
        rows = [row for row in high if row["episode_session"] == session]
        output.append(
            {
                "episode_session": session,
                "high_intensity_dates": len(rows),
                "signals": sum(row["qualifying_signals"] for row in rows),
                "requested_capital": sum(row["episode_request"] for row in rows),
                "deployed_capital": sum(row["deployed_capital"] for row in rows),
                "cash_blocked_capital": sum(row["cash_blocked_capital"] for row in rows),
                "average_intensity": float(np.mean([row["count_ratio"] for row in rows])) if rows else None,
                "average_subsequent_basket_return": float(np.mean([basket[row["entry_date"]] for row in rows])) if rows else None,
            }
        )
    return output


def extended_metrics(simulation: dict[str, Any], active_entry_dates: int) -> dict[str, Any]:
    return v6.extended_metrics(simulation, active_entry_dates)


def stability(
    v5_control: dict[str, Any],
    v6_control: dict[str, Any],
    v7_treatment: dict[str, Any],
    episode_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    output = []
    for label, start, end in (
        ("2018-2020", date(2018, 1, 1), date(2020, 12, 31)),
        ("2021-2023", date(2021, 1, 1), date(2023, 12, 31)),
        ("2024-2026", date(2024, 1, 1), date(2026, 12, 31)),
    ):
        episodes = [row for row in episode_rows if start <= row["episode_start_entry_date"] <= end]
        requested = sum(row["cumulative_requested_capital"] for row in episodes)
        blocked = sum(row["cumulative_cash_blocked_capital"] for row in episodes)
        metrics5 = v5._slice_metrics(v5_control, start, end)
        metrics6 = v5._slice_metrics(v6_control, start, end)
        metrics7 = v5._slice_metrics(v7_treatment, start, end)
        output.append(
            {
                "time_block": label,
                "episodes": len(episodes),
                "event_count": sum(row["total_qualifying_events"] for row in episodes),
                "high_intensity_event_count": sum(row["high_intensity_events"] for row in episodes),
                "average_episode_intensity": float(np.mean([row["mean_intensity"] for row in episodes])),
                "v5_gross_return": metrics5["cumulative_return"],
                "v6_gross_return": metrics6["cumulative_return"],
                "v7_gross_return": metrics7["cumulative_return"],
                "v7_minus_v5": metrics7["cumulative_return"] - metrics5["cumulative_return"],
                "v7_minus_v6": metrics7["cumulative_return"] - metrics6["cumulative_return"],
                "v7_max_drawdown": metrics7["max_drawdown"],
                "v7_average_exposure": metrics7["average_exposure"],
                "cash_blocked_percentage": blocked / requested if requested else 0.0,
                "episode_win_rate": float(np.mean([row["episode_gross_pnl"] > 0 for row in episodes])),
                "average_episode_pnl": float(np.mean([row["episode_gross_pnl"] for row in episodes])),
            }
        )
    return output


def hierarchy_bridge(
    v5_control: dict[str, Any], episode_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    v6_results = json.loads((DEFAULT_OUTPUT / "v6_cluster_results.json").read_text())
    positive = [row for row in episode_rows if row["episode_gross_pnl"] > 0]
    total_pnl = sum(row["episode_gross_pnl"] for row in episode_rows)
    positive_pnl = sum(row["episode_gross_pnl"] for row in positive)
    total_deployed = sum(row["cumulative_deployed_capital"] for row in episode_rows)
    return {
        "event_level_mean_executable_return": float(
            np.mean([trade["gross_trade_return"] for trade in v5_control["trades"]])
        ),
        "date_level_equal_weight_basket_return": v6_results["count_forward_return"]["overall"]["mean_basket_return"],
        "v6_highest_count_fifth_basket_return": v6_results["count_forward_return"]["count_rank_quintiles"][-1]["mean_basket_return"],
        "episode_equal_weight_mean_high_intensity_basket_return": float(np.mean([row["high_intensity_equal_weight_forward_return"] for row in episode_rows])),
        "episode_equal_weight_median_high_intensity_basket_return": float(np.median([row["high_intensity_equal_weight_forward_return"] for row in episode_rows])),
        "total_episode_pnl": total_pnl,
        "capital_weighted_episode_return": total_pnl / total_deployed if total_deployed else None,
        "profitable_episode_share": len(positive) / len(episode_rows),
        "fraction_total_pnl_from_profitable_episodes": positive_pnl / total_pnl if total_pnl else None,
    }


def result_checks(
    events: list[dict[str, Any]],
    calendar: list[date],
    schedule: list[dict[str, Any]],
    episode_specs: list[dict[str, Any]],
    controls: dict[str, Any],
    simulations: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    checks: dict[str, Any] = {
        "event_count_difference": len(events) - EXPECTED_EVENTS,
        "active_count_sum_difference": sum(row["signal_count"] for row in schedule) - len(events),
        "v5_reproduction_violation": int(controls["V5_EQUAL_GROSS"]["maximum_absolute_difference"] > 1e-14),
        "v6_reproduction_violation": int(controls["V6_COUNT_AWARE_GROSS"]["maximum_absolute_difference"] > 1e-14),
        "warmup_high_intensity_violations": sum(row["warmup"] and row["high_intensity"] for row in schedule),
        "high_intensity_formula_violations": sum(row["high_intensity"] != (not row["warmup"] and row["count_ratio"] > 1.0) for row in schedule),
        "high_intensity_outside_episode": sum(row["high_intensity"] and row["episode_id"] is None for row in schedule),
        "episode_start_not_high_intensity": 0,
        "episode_length_violations": 0,
        "overlapping_episode_violations": 0,
    }
    calendar_index = {trade_date: index for index, trade_date in enumerate(calendar)}
    schedule_by_date = {row["entry_date"]: row for row in schedule}
    prior_end = -1
    for spec in episode_specs:
        start = calendar_index[spec["episode_start_entry_date"]]
        end = calendar_index[spec["episode_end_date"]]
        if not schedule_by_date[spec["episode_start_entry_date"]]["high_intensity"]:
            checks["episode_start_not_high_intensity"] += 1
        if end - start + 1 != EPISODE_SESSIONS:
            checks["episode_length_violations"] += 1
        if start <= prior_end:
            checks["overlapping_episode_violations"] += 1
        prior_end = end

    for name, simulation in simulations.items():
        flow = simulation["flow"]
        if name == "V7_EPISODE_GROSS":
            classified = (
                flow["entered"]
                + flow["low_intensity_skips"]
                + flow["missed_for_zero_cash"]
                + flow["missed_for_exhausted_envelope"]
                + flow["overlapping_security_skips"]
                + flow["invalid_entry_price"]
            )
            checks[f"{name}_signal_reconciliation_difference"] = classified - len(events)
        checks[f"{name}_entry_exit_difference"] = flow["entered"] - len(simulation["trades"])
        checks[f"{name}_negative_cash_days"] = sum(row["cash"] < -1e-12 for row in simulation["daily"])
        checks[f"{name}_leverage_days"] = sum(row["exposure"] > 1.0 + 1e-12 for row in simulation["daily"])
        checks[f"{name}_nav_identity_violations"] = sum(abs(row["nav"] - row["cash"] - row["market_value"]) > 1e-12 for row in simulation["daily"])
        checks[f"{name}_entry_chronology_violations"] = sum(trade["entry_date"] <= trade["signal_date"] for trade in simulation["trades"])
        checks[f"{name}_holding_violations"] = sum(trade["holding_sessions"] != v5.HOLDING_SESSIONS + trade["exit_delay_sessions"] for trade in simulation["trades"])

    v7_simulation = simulations["V7_EPISODE_GROSS"]
    runtime = {row["episode_id"]: row for row in v7_simulation["episodes"]}
    checks["episode_runtime_count_difference"] = len(runtime) - len(episode_specs)
    checks["envelope_definition_violations"] = sum(not math.isclose(row["episode_envelope"], row["episode_start_nav"], abs_tol=1e-14) for row in runtime.values())
    checks["envelope_deployment_violations"] = sum(row["cumulative_deployed"] > row["episode_envelope"] + 1e-12 for row in runtime.values())
    checks["low_intensity_deployment_violations"] = sum(not row["high_intensity"] and row["deployed_capital"] != 0.0 for row in v7_simulation["daily_allocations"])
    checks["request_identity_violations"] = 0
    for row in v7_simulation["daily_allocations"]:
        if not row["high_intensity"]:
            continue
        episode = runtime[row["episode_id"]]
        expected_raw = BASE_REQUEST_FRACTION * episode["episode_start_nav"] * row["count_ratio"]
        expected_request = min(expected_raw, row["remaining_envelope_before"])
        if not math.isclose(row["raw_request"], expected_raw, abs_tol=1e-12) or not math.isclose(row["episode_request"], expected_request, abs_tol=1e-12) or row["deployed_capital"] > row["available_cash"] + 1e-12:
            checks["request_identity_violations"] += 1
    failures = {key: value for key, value in checks.items() if value != 0}
    if failures:
        raise RuntimeError(f"V7 result invariants failed: {failures}")
    return checks


def collect_results(
    events: list[dict[str, Any]],
    prices: dict[tuple[str, date], dict[str, Any]],
    calendar: list[date],
) -> tuple[dict[str, Any], dict[str, Any]]:
    cluster_reference = v6.assign_causal_cluster_reference(events)
    schedule, episode_specs = assign_episode_schedule(cluster_reference, events, calendar)
    v5_control = v5.simulate_portfolio(policy="EQUAL_SIZE", cost_mode="GROSS", events=events, prices=prices, calendar=calendar)
    v6_control = v6.simulate_count_aware(events=events, prices=prices, calendar=calendar, cluster_reference=cluster_reference)
    v7_treatment = simulate_episode_portfolio(events=events, prices=prices, calendar=calendar, schedule=schedule, episode_specs=episode_specs)
    controls = reproduce_controls(v5_control, v6_control)
    episode_rows, episode_summary = episode_diagnostics(v7_treatment, schedule, v5_control)
    actual_entry_dates = sum(row["entry_notional"] > 0 for row in v7_treatment["daily"])
    simulations = {
        "V5_EQUAL_GROSS": v5_control,
        "V6_COUNT_AWARE_GROSS": v6_control,
        "V7_EPISODE_GROSS": v7_treatment,
    }
    metrics = {
        "V5_EQUAL_GROSS": extended_metrics(v5_control, len(cluster_reference)),
        "V6_COUNT_AWARE_GROSS": extended_metrics(v6_control, len(cluster_reference)),
        "V7_EPISODE_GROSS": extended_metrics(v7_treatment, actual_entry_dates),
    }
    saturation = saturation_diagnostics(v7_treatment, schedule)
    v6_authoritative = json.loads(
        (DEFAULT_OUTPUT / "v6_cluster_results.json").read_text()
    )
    v6_budget = v6_authoritative["budget_diagnostics"]
    v7_high = saturation["all_high_intensity_dates"]
    comparisons: dict[str, Any] = {}
    for baseline in ("V5_EQUAL_GROSS", "V6_COUNT_AWARE_GROSS"):
        label = f"V7_MINUS_{baseline.split('_')[0]}"
        comparisons[label] = {}
        for field in ("ending_nav", "cumulative_return", "cagr", "annualized_volatility", "max_drawdown", "sharpe_like", "calmar", "average_exposure", "median_exposure", "maximum_exposure", "average_cash_weight", "minimum_cash_ratio", "annualized_turnover", "average_concurrent_positions", "maximum_concurrent_positions", "average_largest_position_weight", "average_top5_concentration"):
            left = metrics["V7_EPISODE_GROSS"][field]
            right = metrics[baseline][field]
            comparisons[label][field] = left - right if left is not None and right is not None else None
    payload = {
        "research_version": "oversold-reversal-ranking-v7-episode-portfolio",
        "verdict": VERDICT,
        "single_next_step": SINGLE_NEXT_STEP,
        "definitions": {
            "predecessor_verdicts": {"v1": "DEPTH_ONLY", "v2": "RISK_FILTER_ONLY", "v3": "SIZING_SIGNAL_ONLY", "v4": "SIZING_SURVIVES", "v5": "EVENT_ALPHA_COLLAPSES", "v6": "CLUSTER_SIGNAL_EXISTS_BUT_CAPITAL_TRANSLATION_FAILS"},
            "carrier": "exact V1 LOW plus causal drawdown_60 <= -30%; exact V5/V6 event stream",
            "intensity": "I_t=N_t/M_t using V6 prior-active-date median; high intensity iff post-warmup I_t>1",
            "episode": "starts on causal high-intensity legal entry date; exactly 20 market sessions inclusive; no overlap",
            "envelope": "100% of episode-start opening NAV; cumulative deployed-capital cap",
            "request": "min(5% episode-start NAV * I_t, remaining envelope), then capped by true cash",
            "within_date": "equal weight; V3/V4 stock score inactive",
            "cost_basis": "gross; zero transaction costs",
        },
        "sample_profile": {
            "events": len(events),
            "securities": len({row["symbol"] for row in events}),
            "active_signal_dates": len(cluster_reference),
            "episodes": len(episode_specs),
            "first_signal_date": min(row["signal_date"] for row in events),
            "last_signal_date": max(row["signal_date"] for row in events),
            "first_entry_date": min(row["entry_date"] for row in events),
            "last_legal_exit_date": max(row["first_legal_exit_date"] for row in events),
        },
        "control_reproduction": controls,
        "portfolio_metrics": metrics,
        "portfolio_deltas": comparisons,
        "signal_flow": {key: simulation["flow"] for key, simulation in simulations.items()},
        "annual_returns": {key: v5.annual_returns(simulation) for key, simulation in simulations.items()},
        "episode_summary": episode_summary,
        "episode_diagnostics": episode_rows,
        "capital_saturation": saturation,
        "capital_saturation_comparison": {
            "V6_DATE_BUDGET": {
                "requested_capital": v6_budget["total_desired_budget"],
                "deployed_capital": v6_budget["total_actual_budget"],
                "cash_blocked_capital": v6_budget["total_budget_shortfall"],
                "cash_blocked_percentage": v6_budget[
                    "fraction_requested_budget_blocked"
                ],
                "highest_intensity_cash_blocked_percentage": v6_budget[
                    "highest_count_q5"
                ]["fraction_requested_budget_blocked"],
                "zero_allocation_signals_cash": v6_control["flow"][
                    "missed_for_zero_cash"
                ],
            },
            "V7_EPISODE_BUDGET": {
                "raw_requested_capital": v7_high["total_raw_request"],
                "envelope_capped_requested_capital": v7_high[
                    "total_requested_episode_capital"
                ],
                "deployed_capital": v7_high["total_deployed_capital"],
                "cash_blocked_capital": v7_high["total_cash_blocked_capital"],
                "cash_blocked_percentage": v7_high["cash_blocked_percentage"],
                "highest_intensity_cash_blocked_percentage": saturation[
                    "highest_intensity_rank_fifth"
                ]["cash_blocked_percentage"],
                "zero_allocation_signals_cash": v7_high[
                    "zero_allocation_signals_cash"
                ],
                "zero_allocation_signals_envelope": v7_high[
                    "zero_allocation_signals_envelope"
                ],
                "fraction_high_intensity_signals_any_allocation": v7_high[
                    "fraction_high_intensity_signals_any_allocation"
                ],
                "fraction_high_intensity_signals_full_intended_allocation": v7_high[
                    "fraction_high_intensity_signals_full_intended_allocation"
                ],
            },
        },
        "capital_timing_by_episode_session": capital_timing(v7_treatment, v5_control),
        "hierarchy_bridge": hierarchy_bridge(v5_control, episode_rows),
        "time_stability": stability(v5_control, v6_control, v7_treatment, episode_rows),
        "major_drawdown_episodes": {
            "V7_VS_V5": v6.major_drawdowns(v5_control, v7_treatment),
            "V7_VS_V6": v6.major_drawdowns(v6_control, v7_treatment),
        },
        "active_date_diagnostics": v7_treatment["daily_allocations"],
    }
    payload["checks"] = result_checks(events, calendar, schedule, episode_specs, controls, simulations)
    return payload, {"events": events, "schedule": schedule, "simulations": simulations}


def run(*, output_dir: Path = DEFAULT_OUTPUT, hash_data_files: bool = True, write_output: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
    config = json.loads(v5.PREDECESSOR_CONFIG.read_text())
    config["research_version"] = "oversold-reversal-ranking-v7-episode-portfolio"
    identities = v5.validate_inputs(config, hash_data_files=hash_data_files)
    with tempfile.TemporaryDirectory(prefix="oversold-episode-v7-") as temp_dir:
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
        (output_dir / "v7_episode_results.json").write_text(json.dumps(payload, indent=2, default=v5.json_default) + "\n")
    return payload, internals


def preview(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "control_reproduction": payload["control_reproduction"],
        "sample_profile": payload["sample_profile"],
        "portfolio_metrics": payload["portfolio_metrics"],
        "portfolio_deltas": payload["portfolio_deltas"],
        "signal_flow": payload["signal_flow"],
        "episode_summary": payload["episode_summary"],
        "capital_saturation": payload["capital_saturation"],
        "capital_saturation_comparison": payload[
            "capital_saturation_comparison"
        ],
        "hierarchy_bridge": payload["hierarchy_bridge"],
        "capital_timing": payload["capital_timing_by_episode_session"],
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
