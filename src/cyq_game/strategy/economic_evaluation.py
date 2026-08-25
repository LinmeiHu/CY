"""Comparable economic, risk and capacity metrics for exact replay outputs."""

from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from statistics import fmean, median
from typing import Any

import numpy as np

from cyq_game.strategy.economic_selection import (
    cluster_bootstrap_trimmed_interval,
    group_returns_by_iso_week,
    intracluster_correlation,
    trimmed_mean,
    weekly_cluster_evidence,
)


def capacity_industry(row: Mapping[str, Any]) -> str:
    """Resolve the causal industry or one conservative board fallback group."""

    for field in ("panel_industry", "observed_industry"):
        value = str(row.get(field) or "").strip()
        if value and value.upper() != "UNKNOWN":
            return value
    board = str(row.get("board") or "").strip()
    if row.get("sector_fallback") == "BOARD_LOO" and board:
        return f"BOARD_FALLBACK:{board}"
    raise ValueError("signal has neither causal industry nor declared BOARD_LOO fallback")


def replay_economic_metrics(
    signals: Sequence[Mapping[str, Any]],
    trades: Sequence[Mapping[str, Any]],
    *,
    industry_by_signal: Mapping[str, str],
    entry_participation_by_signal: Mapping[str, float],
    parameter_id: str,
    research_book_capital: float = 25_000_000.0,
) -> dict[str, Any]:
    evaluation_signals = tuple(item for item in signals if item["is_evaluation_row"])
    evaluation_trades = tuple(item for item in trades if item["is_evaluation_row"])
    _assert_unique(evaluation_signals, "signal_id", "signals")
    _assert_unique(evaluation_trades, "signal_id", "trades")
    signal_by_id = {str(item["signal_id"]): item for item in evaluation_signals}
    trade_by_id = {str(item["signal_id"]): item for item in evaluation_trades}
    unknown_trades = sorted(set(trade_by_id).difference(signal_by_id))
    if unknown_trades:
        raise ValueError(f"exact trades have no source signals: {unknown_trades[:3]}")
    filled = tuple(
        item for item in evaluation_signals if item.get("entry_status") == "FILLED"
    )
    filled_ids = {str(item["signal_id"]) for item in filled}
    if not set(trade_by_id).issubset(filled_ids):
        raise ValueError("closed exact trade was not preceded by a filled entry")
    missing_industries = sorted(filled_ids.difference(industry_by_signal))
    missing_participation = sorted(filled_ids.difference(entry_participation_by_signal))
    if missing_industries or missing_participation:
        raise ValueError(
            "filled signals have incomplete causal capacity joins: "
            f"industry={missing_industries[:3]}, participation={missing_participation[:3]}"
        )
    returns = [float(item["return_fraction"]) for item in evaluation_trades]
    pnl = [float(item["net_pnl"]) for item in evaluation_trades]
    positives = sum(value for value in pnl if value > 0.0)
    losses = -sum(value for value in pnl if value < 0.0)
    if losses > 0.0:
        profit_factor = positives / losses
        profit_factor_unbounded = False
    elif positives > 0.0:
        profit_factor = 1.0e12
        profit_factor_unbounded = True
    else:
        profit_factor = 0.0
        profit_factor_unbounded = False
    weekly = weekly_cluster_evidence(
        group_returns_by_iso_week(evaluation_trades),
        parameter_id=parameter_id,
    )
    exposure = _exposure_metrics(
        filled,
        trade_by_id,
        industry_by_signal=industry_by_signal,
    )
    participation = sorted(
        float(entry_participation_by_signal[str(item["signal_id"])]) for item in filled
    )
    blocked_loss = sum(float(item["blocked_tail_loss"]) for item in evaluation_trades)
    entry_cash = sum(float(item["entry_cash"]) for item in evaluation_trades)
    return {
        "parameter_id": parameter_id,
        "raw_signal_count": len(evaluation_signals),
        "filled_entry_count": len(filled),
        "closed_trade_count": len(evaluation_trades),
        "entry_fill_rate": _ratio(len(filled), len(evaluation_signals)),
        "closed_trade_rate": _ratio(len(evaluation_trades), len(filled)),
        "mean_net_return_fraction": fmean(returns) if returns else None,
        "median_net_return_fraction": median(returns) if returns else None,
        "trimmed_5pct_mean_net_return_fraction": (
            trimmed_mean(returns) if returns else None
        ),
        "win_rate": _ratio(sum(value > 0.0 for value in returns), len(returns)),
        "profit_factor": profit_factor,
        "profit_factor_unbounded": profit_factor_unbounded,
        "portfolio_max_drawdown_fraction": _event_sequence_drawdown(
            evaluation_trades, research_book_capital
        ),
        "blocked_tail_loss": blocked_loss,
        "blocked_tail_loss_ratio": blocked_loss / entry_cash if entry_cash else 0.0,
        "trade_cvar_1pct": _lower_tail_mean(returns, 0.01),
        "first_5m_participation_mean": fmean(participation) if participation else None,
        "first_5m_participation_p95": _quantile(participation, 0.95),
        "first_5m_participation_max": max(participation, default=0.0),
        **exposure,
        "annual_signal_counts": _year_counts(evaluation_signals, "decision_at"),
        "annual_trade_counts": _year_counts(evaluation_trades, "signal_at"),
        "annual_trade_returns": _annual_return_metrics(evaluation_trades),
        "market_state_trade_returns": _stratified_return_metrics(
            evaluation_trades, signal_by_id, "market_state"
        ),
        "sector_state_trade_returns": _stratified_return_metrics(
            evaluation_trades, signal_by_id, "sector_state"
        ),
        **weekly,
    }


def paired_weekly_difference_evidence(
    pairs: Sequence[Mapping[str, Any]],
    *,
    parameter_id: str,
    resamples: int = 10_000,
    icc_floor: float = 0.10,
) -> dict[str, float | int | None]:
    grouped: defaultdict[str, list[float]] = defaultdict(list)
    for pair in pairs:
        at = _datetime(pair["candidate_signal_at"])
        year, week, _ = at.date().isocalendar()
        grouped[f"{year:04d}-W{week:02d}"].append(
            float(pair["candidate_return_fraction"])
            - float(pair["baseline_return_fraction"])
        )
    clusters = {key: tuple(values) for key, values in sorted(grouped.items())}
    flat = [value for values in clusters.values() for value in values]
    if not flat:
        return {
            "baseline_pair_count": 0,
            "baseline_distinct_signal_weeks": 0,
            "baseline_observed_icc": None,
            "baseline_effective_sample": 0.0,
            "baseline_difference_trimmed_mean": None,
            "baseline_difference_lower_95": None,
            "baseline_difference_upper_95": None,
            "baseline_difference_half_width": None,
        }
    observed_icc = intracluster_correlation(tuple(clusters.values()))
    mean_cluster_size = len(flat) / len(clusters)
    effective = len(flat) / (
        1.0 + (mean_cluster_size - 1.0) * max(observed_icc, icc_floor)
    )
    weeks = tuple(clusters)
    seed = int.from_bytes(
        hashlib.sha256(
            f"{parameter_id}|MATCHED_ELIGIBLE_BASELINE_V2".encode()
        ).digest()[:8],
        "big",
    )
    lower, upper = cluster_bootstrap_trimmed_interval(
        tuple(clusters[week] for week in weeks),
        resamples=resamples,
        seed=seed,
    )
    return {
        "baseline_pair_count": len(flat),
        "baseline_distinct_signal_weeks": len(clusters),
        "baseline_observed_icc": observed_icc,
        "baseline_effective_sample": effective,
        "baseline_difference_trimmed_mean": trimmed_mean(flat),
        "baseline_difference_lower_95": float(lower),
        "baseline_difference_upper_95": float(upper),
        "baseline_difference_half_width": float((upper - lower) / 2.0),
    }


def combined_gate_metrics(
    replay_metrics: Mapping[str, Any],
    baseline_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Require the primary and matched evidence to both meet sufficiency."""

    payload = dict(replay_metrics)
    payload.update(baseline_evidence)
    payload["distinct_signal_weeks"] = min(
        int(replay_metrics["distinct_signal_weeks"]),
        int(baseline_evidence["baseline_distinct_signal_weeks"]),
    )
    payload["effective_sample"] = min(
        float(replay_metrics["effective_sample"]),
        float(baseline_evidence["baseline_effective_sample"]),
    )
    primary_half_width = replay_metrics.get("bootstrap_half_width")
    baseline_half_width = baseline_evidence.get("baseline_difference_half_width")
    payload["bootstrap_half_width"] = (
        max(float(primary_half_width), float(baseline_half_width))
        if primary_half_width is not None and baseline_half_width is not None
        else None
    )
    return payload


def _exposure_metrics(
    filled: Sequence[Mapping[str, Any]],
    trade_by_id: Mapping[str, Mapping[str, Any]],
    *,
    industry_by_signal: Mapping[str, str],
) -> dict[str, int]:
    events: list[tuple[datetime, int, str]] = []
    same_day: Counter[date] = Counter()
    for signal in filled:
        signal_id = str(signal["signal_id"])
        entry_at = _datetime(signal["entry_fill_at"])
        events.append((entry_at, 1, signal_id))
        same_day[entry_at.date()] += 1
        trade = trade_by_id.get(signal_id)
        if trade is not None:
            events.append((_datetime(trade["exit_at"]), 0, signal_id))
    active: dict[str, str] = {}
    industry_counts: Counter[str] = Counter()
    maximum_positions = 0
    maximum_industry = 0
    for _, event_type, signal_id in sorted(events):
        industry = industry_by_signal[signal_id]
        if event_type == 0:
            if signal_id not in active:
                raise ValueError("exact exposure exit has no active entry")
            del active[signal_id]
            industry_counts[industry] -= 1
            continue
        if signal_id in active:
            raise ValueError("exact exposure contains a duplicate entry")
        active[signal_id] = industry
        industry_counts[industry] += 1
        maximum_positions = max(maximum_positions, len(active))
        maximum_industry = max(maximum_industry, industry_counts[industry])
    return {
        "maximum_concurrent_positions": maximum_positions,
        "maximum_concurrent_same_industry_positions": maximum_industry,
        "maximum_same_day_new_entries": max(same_day.values(), default=0),
        "open_positions_at_end": len(active),
    }


def _event_sequence_drawdown(
    trades: Sequence[Mapping[str, Any]], capital: float
) -> float:
    if capital <= 0.0:
        raise ValueError("research book capital must be positive")
    equity = capital
    peak = capital
    maximum = 0.0
    for trade in sorted(trades, key=lambda item: (_datetime(item["exit_at"]), item["signal_id"])):
        equity += float(trade["net_pnl"])
        peak = max(peak, equity)
        maximum = min(maximum, equity / peak - 1.0)
    return maximum


def _lower_tail_mean(values: Sequence[float], fraction: float) -> float:
    if not values:
        return -1.0
    count = max(1, math.ceil(len(values) * fraction))
    return fmean(sorted(values)[:count])


def _quantile(values: Sequence[float], probability: float) -> float:
    return float(np.quantile(values, probability)) if values else 0.0


def _year_counts(rows: Sequence[Mapping[str, Any]], field: str) -> dict[int, int]:
    counts = Counter(_datetime(item[field]).year for item in rows)
    return dict(sorted(counts.items()))


def _annual_return_metrics(
    trades: Sequence[Mapping[str, Any]],
) -> dict[int, dict[str, float | int | None]]:
    grouped: defaultdict[int, list[float]] = defaultdict(list)
    for trade in trades:
        grouped[_datetime(trade["signal_at"]).year].append(
            float(trade["return_fraction"])
        )
    return {
        year: {
            "count": len(values),
            "mean": fmean(values) if values else None,
            "median": median(values) if values else None,
            "trimmed_5pct_mean": trimmed_mean(values) if values else None,
        }
        for year, values in sorted(grouped.items())
    }


def _stratified_return_metrics(
    trades: Sequence[Mapping[str, Any]],
    signal_by_id: Mapping[str, Mapping[str, Any]],
    field: str,
) -> dict[str, dict[str, float | int | None]]:
    grouped: defaultdict[str, list[float]] = defaultdict(list)
    for trade in trades:
        signal = signal_by_id[str(trade["signal_id"])]
        grouped[str(signal[field])].append(float(trade["return_fraction"]))
    return {
        key: {
            "count": len(values),
            "mean": fmean(values) if values else None,
            "trimmed_5pct_mean": trimmed_mean(values) if values else None,
        }
        for key, values in sorted(grouped.items())
    }


def _assert_unique(
    rows: Sequence[Mapping[str, Any]], field: str, description: str
) -> None:
    values = [str(item[field]) for item in rows]
    if len(values) != len(set(values)):
        raise ValueError(f"economic {description} contain duplicate {field}")


def _datetime(value: object) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0
