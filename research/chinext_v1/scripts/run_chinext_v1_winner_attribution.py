#!/usr/bin/env python3
"""Reproduce the frozen Phase 2 winner attribution without trading or NAV replay."""

from __future__ import annotations

import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "research/chinext_v1/scripts"
sys.path.insert(0, str(SCRIPTS))

from run_chinext_v1_smoke import (  # noqa: E402
    DEFAULT_CALENDAR,
    DEFAULT_DAILY_ROOT,
    ChinNextV1Config,
    breakout_volume_diagnostic,
    build_rs_table,
    contiguous_tail,
    critical_row_valid,
    daily_glob,
    entry_price_structure,
    finite_or_default,
    load_pit_membership,
    load_sample_panel,
    load_sessions,
    minvol_diagnostic,
    row_map,
    sha256_file,
)

SUMMARY_PATH = ROOT / "research/chinext_v1/reports/chinext_v1_pit_replay_summary.json"
STRATEGY_PATH = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"
PIT_MANIFEST = ROOT / "research/chinext_v1/reports/chinext_v1_pit_master_manifest.json"
PIT_MEMBERSHIP = ROOT / "research/chinext_v1/data/pit_2024_2025/daily_membership.parquet"
OUTPUT_CSV = ROOT / "research/chinext_v1/reports/chinext_v1_trade_attribution.csv"
OUTPUT_JSON = ROOT / "research/chinext_v1/reports/chinext_v1_winner_attribution_summary.json"
OUTPUT_MD = ROOT / "research/chinext_v1/reports/chinext_v1_winner_attribution.md"
START = date(2024, 1, 2)
END = date(2025, 12, 31)
INITIAL_CASH = 1_000_000.0
EXPECTED_STRATEGY = "dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a"
EXPECTED_PIT = "8b4519ff6cf74aa0ca13b15bd3954cce3a37f6dd19d25f3f77743e9a974e75f7"
EXPECTED_SUMMARY = "10c9a10860dfaef5ee621a5e98741a9b0f881be247e8115cd524d9098a66d6af"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def assert_frozen() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if sha256_file(STRATEGY_PATH) != EXPECTED_STRATEGY:
        raise RuntimeError("strategy identity changed")
    if sha256_file(PIT_MANIFEST) != EXPECTED_PIT:
        raise RuntimeError("PIT manifest identity changed")
    if sha256_file(SUMMARY_PATH) != EXPECTED_SUMMARY:
        raise RuntimeError("Phase 1B summary identity changed")
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    if summary["authorization"]["authorization_id"] != "CYQ-AUTH-CHINEXT-V1-PIT-B-2024-2025-V1":
        raise RuntimeError("authorization identity changed")
    if summary["sample"]["date_range"] != [START.isoformat(), END.isoformat()]:
        raise RuntimeError("date range changed")
    if summary["execution"]["completed_round_trip_count"] != 111:
        raise RuntimeError("trade count changed")
    execution_path = Path(summary["audit"]["execution_ledger"])
    if sha256_file(execution_path) != summary["audit"]["execution_ledger_sha256"]:
        raise RuntimeError("execution ledger changed")
    if sha256_file(Path(summary["audit"]["event_ledger"])) != summary["audit"]["event_ledger_sha256"]:
        raise RuntimeError("event ledger changed")
    if sha256_file(Path(summary["audit"]["daily_nav"])) != summary["audit"]["daily_nav_sha256"]:
        raise RuntimeError("NAV ledger changed")
    return summary, read_jsonl(execution_path)


def reconstruct_cycles(executions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    active: dict[str, dict[str, Any]] = {}
    result: list[dict[str, Any]] = []
    cycle_number: Counter[str] = Counter()
    for row in executions:
        if row.get("status") != "FILLED":
            continue
        symbol = str(row["symbol"])
        if row["side"] == "BUY":
            if row.get("new_position") is True:
                if symbol in active:
                    raise RuntimeError(f"overlapping cycle: {symbol}")
                cycle_number[symbol] += 1
                active[symbol] = {
                    "trade_id": f"{symbol}-{cycle_number[symbol]:03d}",
                    "symbol": symbol,
                    "entry_signal_date": str(row["signal_date"]),
                    "entry_execution_date": str(row["execution_date"]),
                    "entry_price": float(row["execution_price"]),
                    "entry_target_weight": float(row["target_weight"]),
                    "entry_reason": str(row["signal_reason"]),
                    "buy_fill_count": 0,
                    "sell_fill_count": 0,
                    "buy_shares": 0.0,
                    "buy_notional": 0.0,
                    "buy_cost": 0.0,
                    "realized_pnl": 0.0,
                }
            if symbol not in active:
                raise RuntimeError(f"buy without active cycle: {symbol}")
            cycle = active[symbol]
            cycle["buy_fill_count"] += 1
            cycle["buy_shares"] += float(row["shares"])
            cycle["buy_notional"] += float(row["notional"])
            cycle["buy_cost"] += float(row["notional"]) + float(row["cost"])
        else:
            if symbol not in active:
                raise RuntimeError(f"sell without active cycle: {symbol}")
            cycle = active[symbol]
            cycle["sell_fill_count"] += 1
            cycle["realized_pnl"] += float(row["realized_pnl"])
            if row.get("completed_round_trip") is True:
                cycle = active.pop(symbol)
                cycle.update(
                    {
                        "weighted_average_buy_price": cycle["buy_notional"] / cycle["buy_shares"],
                        "capital": cycle["buy_cost"],
                        "exit_signal_date": str(row["signal_date"]),
                        "exit_execution_date": str(row["execution_date"]),
                        "exit_price": float(row["execution_price"]),
                        "exit_reason": str(row["signal_reason"]),
                        "realized_return": float(row["round_trip_return"]),
                    }
                )
                result.append(cycle)
    if len(result) != 111:
        raise RuntimeError(f"completed cycle count mismatch: {len(result)}")
    return result


def action_values(row: dict[str, Any], day: date) -> tuple[bool, float, float]:
    if int(row.get("corporate_action_count") or 0) <= 0:
        return False, 1.0, 0.0
    multiplier = finite_or_default(row.get("share_multiplier"), 1.0)
    cash_per_share = finite_or_default(row.get("cash_per_share"), 0.0)
    blocking = row.get("corporate_action_blocking") is not False or row.get("corporate_action_valid") is not True
    rights = finite_or_default(row.get("rights_ratio"), 0.0)
    available = row.get("corporate_action_available_date")
    visible = available is not None and not pd.isna(available) and pd.Timestamp(available).date() <= day
    valid = (
        not blocking
        and visible
        and rights == 0.0
        and multiplier > 0
        and all(math.isfinite(value) for value in (multiplier, cash_per_share, rights))
    )
    return valid, multiplier, cash_per_share


def entry_features(cycles: list[dict[str, Any]]) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, Any]]:
    config = ChinNextV1Config()
    symbols, membership_by_date, pit_metadata = load_pit_membership(PIT_MEMBERSHIP, START, END)
    target_keys = {(row["symbol"], row["entry_signal_date"]) for row in cycles}
    target_dates = {date.fromisoformat(day) for _, day in target_keys}
    paths = daily_glob(DEFAULT_DAILY_ROOT, date(2018, 1, 1), END)
    con = duckdb.connect()
    warmup_start = date(2023, 1, 1)
    panel = load_sample_panel(con, paths, tuple(symbols), warmup_start, END)
    sessions = load_sessions(DEFAULT_CALENDAR, warmup_start, END)
    rows_by_date = row_map(panel)
    session_index = {day: index for index, day in enumerate(sessions)}
    closes: dict[str, list[float]] = {symbol: [] for symbol in symbols}
    volumes: dict[str, list[float]] = {symbol: [] for symbol in symbols}
    amounts: dict[str, list[float]] = {symbol: [] for symbol in symbols}
    dates: dict[str, list[date]] = {symbol: [] for symbol in symbols}
    result: dict[tuple[str, str], dict[str, Any]] = {}
    cross_section_sizes: dict[str, int] = {}

    for day in sessions:
        day_rows = rows_by_date.get(day, {})
        for symbol, row in sorted(day_rows.items()):
            valid_action, multiplier, cash_per_share = action_values(row, day)
            if valid_action and (multiplier != 1.0 or cash_per_share != 0.0):
                closes[symbol] = [(value - cash_per_share) / multiplier for value in closes[symbol]]
                volumes[symbol] = [value * multiplier for value in volumes[symbol]]
        for symbol in symbols:
            row = day_rows.get(symbol)
            if row is not None and critical_row_valid(row):
                dates[symbol].append(day)
                closes[symbol].append(float(row["close"]))
                volumes[symbol].append(float(row["volume"]))
                amounts[symbol].append(float(row["amount"]))
        if day not in target_dates:
            continue
        active = membership_by_date[day]
        eligible: list[str] = []
        for symbol in symbols:
            history_ok = (
                active.get(symbol, 0) >= config.min_completed_observations
                and len(dates[symbol]) >= config.min_completed_observations
                and contiguous_tail(dates[symbol], sessions, session_index[day], 121)
            )
            liquidity_ok = (
                history_ok
                and contiguous_tail(dates[symbol], sessions, session_index[day], config.turnover20_days)
                and len(amounts[symbol]) >= config.turnover20_days
                and statistics.fmean(amounts[symbol][-config.turnover20_days :]) >= config.turnover20_min_cny
            )
            if history_ok and liquidity_ok and critical_row_valid(day_rows.get(symbol)):
                eligible.append(symbol)
        rs = build_rs_table(closes, eligible, config)
        ordered = sorted(rs, key=lambda s: (-rs[s]["score"], -rs[s]["mom60"], s))
        rank = {symbol: index for index, symbol in enumerate(ordered, 1)}
        score_series = pd.Series({symbol: row["score"] for symbol, row in rs.items()})
        score_pct = score_series.rank(method="average", pct=True).to_dict()
        cross_section_sizes[day.isoformat()] = len(rs)
        for symbol, signal_text in sorted(target_keys):
            if signal_text != day.isoformat():
                continue
            if symbol not in rs or symbol not in eligible:
                raise RuntimeError(f"actual entry missing from PIT eligible RS cross-section: {symbol} {day}")
            price_passed, full = entry_price_structure(closes[symbol], config)
            minimum = minvol_diagnostic(closes[symbol], volumes[symbol], config)
            breakout_volume = breakout_volume_diagnostic(volumes[symbol], config)
            if not price_passed or not full.passed or not minimum.passed:
                raise RuntimeError(f"actual entry fails frozen entry diagnostics: {symbol} {day}")
            series = closes[symbol]
            prior = series[:-1]
            prior60 = series[-61:-1]
            previous_high = max(prior60)
            signal_close = series[-1]
            box = prior[-config.box_days :]
            mas = {f"ma{n}": statistics.fmean(prior[-n:]) for n in (5, 10, 20, 30)}
            returns = [right / left - 1.0 for left, right in zip(prior, prior[1:], strict=False)]
            vol10 = statistics.stdev(returns[-10:])
            vol60 = statistics.stdev(returns[-60:])
            prior_close30 = series[-31:-1]
            prior_volume30 = volumes[symbol][-31:-1]
            min_index = min(range(30), key=lambda index: prior_volume30[index])
            turnover20 = statistics.fmean(amounts[symbol][-20:])
            entry = {
                **rs[symbol],
                "final_rs_score": rs[symbol]["score"],
                "entry_cross_section_rank": rank[symbol],
                "entry_cross_section_percentile": float(score_pct[symbol]),
                "entry_cross_section_size": len(rs),
                "previous_60_close_high": previous_high,
                "signal_close": signal_close,
                "b60_breakout_margin": signal_close / previous_high - 1.0,
                "previous_60_high_distance_pct": (signal_close - previous_high) / signal_close,
                "box_width": full.box_width,
                **mas,
                "ma_dispersion": full.ma_dispersion,
                "direction_efficiency": full.direction_efficiency,
                "vol10": vol10,
                "vol60": vol60,
                "vol_ratio_10_60": full.vol_ratio,
                "box_width_margin": config.box_width_max - float(full.box_width),
                "ma_dispersion_margin": config.ma_dispersion_max - float(full.ma_dispersion),
                "direction_efficiency_margin": config.direction_efficiency_max - float(full.direction_efficiency),
                "vol_ratio_margin": config.vol_ratio_max - float(full.vol_ratio),
                "minvol_location": minimum.location,
                "minimum_volume": minimum.minimum_volume,
                "average_volume": minimum.average_volume,
                "minimum_volume_ratio": minimum.minimum_volume_ratio,
                "min_volume_day_close": prior_close30[min_index],
                "30d_low_close": min(prior_close30),
                "30d_high_close": max(prior_close30),
                "turnover20_mean": turnover20,
                "signal_day_volume": volumes[symbol][-1],
                "previous20_volume_mean": breakout_volume.denominator,
                "signal_day_volume_ratio": breakout_volume.ratio,
                "breakout_volume_shadow_passed": breakout_volume.passed,
                "minimum_volume_ratio_hard_filter": True,
            }
            entry.pop("score", None)
            result[(symbol, signal_text)] = entry
    if set(result) != target_keys:
        raise RuntimeError(f"entry feature coverage mismatch: {len(result)} vs {len(target_keys)}")
    return result, {"pit_membership": pit_metadata, "cross_section_sizes": cross_section_sizes, "panel": panel, "sessions": sessions, "rows_by_date": rows_by_date}


def holding_features(
    cycle: dict[str, Any], sessions: list[date], rows_by_date: dict[date, dict[str, dict[str, Any]]]
) -> dict[str, Any]:
    symbol = cycle["symbol"]
    entry = date.fromisoformat(cycle["entry_execution_date"])
    exit_day = date.fromisoformat(cycle["exit_execution_date"])
    start_index = sessions.index(entry)
    end_index = sessions.index(exit_day)
    entry_price = float(cycle["entry_price"])
    share_factor = 1.0
    cash_per_original_share = 0.0
    high_returns: list[tuple[int, float]] = []
    low_returns: list[tuple[int, float]] = []
    close_returns: list[tuple[int, float]] = []
    for offset, day in enumerate(sessions[start_index : end_index + 1]):
        row = rows_by_date.get(day, {}).get(symbol)
        if row is None:
            raise RuntimeError(f"held attribution row missing: {symbol} {day}")
        if day > entry:
            valid_action, multiplier, cash_per_share = action_values(row, day)
            if valid_action:
                cash_per_original_share += share_factor * cash_per_share
                share_factor *= multiplier
        def ret(price: float) -> float:
            return (share_factor * price + cash_per_original_share) / entry_price - 1.0
        if day == exit_day:
            value = ret(float(cycle["exit_price"]))
            high_returns.append((offset, value))
            low_returns.append((offset, value))
            close_returns.append((offset, value))
        else:
            high_returns.append((offset, ret(float(row["high"]))))
            low_returns.append((offset, ret(float(row["low"]))))
            close_returns.append((offset, ret(float(row["close"]))))
    mfe_day, mfe = max(high_returns, key=lambda item: item[1])
    mae_day, mae = min(low_returns, key=lambda item: item[1])
    _, peak = max(close_returns, key=lambda item: item[1])
    _, trough = min(close_returns, key=lambda item: item[1])
    return {
        "holding_trading_days": end_index - start_index,
        "MFE": mfe,
        "MAE": mae,
        "peak_return_during_hold": peak,
        "trough_return_during_hold": trough,
        "giveback_from_peak": peak - float(cycle["realized_return"]),
        "days_to_MFE": mfe_day,
        "days_to_MAE": mae_day,
        "excursion_basis": "first-entry-open gross underlying total-return path; corporate-action adjusted; exit day open only",
    }


def quantiles(rows: list[dict[str, Any]], columns: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column in columns:
        values = np.asarray([float(row[column]) for row in rows], dtype=float)
        if not np.isfinite(values).all():
            raise RuntimeError(f"nonfinite group feature: {column}")
        result[column] = {
            "mean": float(np.mean(values)),
            "median": float(np.median(values)),
            "p25": float(np.percentile(values, 25)),
            "p75": float(np.percentile(values, 75)),
        }
    return result


def gini_nonnegative(values: list[float]) -> float:
    ordered = np.sort(np.asarray(values, dtype=float))
    if len(ordered) == 0 or ordered.sum() <= 0 or (ordered < 0).any():
        raise ValueError("Gini requires a nonnegative nonzero sample")
    index = np.arange(1, len(ordered) + 1)
    return float((2 * np.sum(index * ordered) / (len(ordered) * ordered.sum())) - (len(ordered) + 1) / len(ordered))


def pct(value: float | None) -> str:
    return "NA" if value is None else f"{value:.4%}"


def format_group_table(group_stats: dict[str, Any], feature: str) -> str:
    cells = [feature]
    for group in ("GROUP_A", "GROUP_B", "GROUP_C"):
        row = group_stats[group][feature]
        cells.append(f"{row['median']:.6g} / {row['mean']:.6g} / [{row['p25']:.6g}, {row['p75']:.6g}]")
    return "| " + " | ".join(cells) + " |"


def main() -> None:
    phase1, executions = assert_frozen()
    cycles = reconstruct_cycles(executions)
    features, context = entry_features(cycles)
    for cycle in cycles:
        cycle.update(features[(cycle["symbol"], cycle["entry_signal_date"])])
        cycle.update(holding_features(cycle, context["sessions"], context["rows_by_date"]))
    ordered = sorted(cycles, key=lambda row: (-float(row["realized_pnl"]), row["symbol"], row["exit_execution_date"]))
    if any(float(row["realized_pnl"]) <= 0 for row in ordered[:20]):
        raise RuntimeError("frozen Top20 contains a non-profitable cycle")
    phase1_top20 = [row["symbol"] for row in phase1["pnl_concentration"]["top20_trades"]]
    if [row["symbol"] for row in ordered[:20]] != phase1_top20:
        raise RuntimeError("Top20 identity/order differs from Phase 1B")
    for index, row in enumerate(ordered, 1):
        row["pnl_rank"] = index
        row["winner_group"] = "GROUP_A" if index <= 10 else "GROUP_B" if index <= 20 else "GROUP_C"
        row["win_loss_group"] = "WINNERS" if row["realized_return"] > 0 else "LOSERS"

    feature_columns = [
        "mom20", "mom60", "mom120", "r20", "r60", "r120", "final_rs_score",
        "b60_breakout_margin", "box_width", "ma_dispersion", "direction_efficiency",
        "vol_ratio_10_60", "minvol_location", "minimum_volume_ratio", "turnover20_mean",
        "holding_trading_days", "MFE", "MAE", "giveback_from_peak",
    ]
    groups = {
        name: [row for row in ordered if row["winner_group"] == name]
        for name in ("GROUP_A", "GROUP_B", "GROUP_C")
    }
    group_stats = {name: quantiles(rows, feature_columns) for name, rows in groups.items()}
    top20 = ordered[:20]
    remainder = ordered[20:]
    top20_stats = quantiles(top20, feature_columns)
    remainder_stats = quantiles(remainder, feature_columns)

    returns = pd.Series([float(row["realized_return"]) for row in cycles], dtype=float)
    pnls = [float(row["realized_pnl"]) for row in cycles]
    positive_pnls = [value for value in pnls if value > 0]
    negative_pnls = [value for value in pnls if value <= 0]
    winner_returns = [float(row["realized_return"]) for row in cycles if row["realized_return"] > 0]
    loser_returns = [float(row["realized_return"]) for row in cycles if row["realized_return"] <= 0]
    positive_total = sum(positive_pnls)
    concentrations = {
        f"top{n}": sum(max(0.0, float(row["realized_pnl"])) for row in ordered[:n]) / positive_total
        for n in (1, 5, 10, 20)
    }
    return_exclusions = {
        f"best{n}": float(phase1["portfolio"]["total_return"])
        - sum(float(row["realized_pnl"]) for row in ordered[:n]) / INITIAL_CASH
        for n in (10, 20)
    }
    positive_shares = [value / positive_total for value in positive_pnls]
    top20_symbols = Counter(row["symbol"] for row in top20)
    top20_years = Counter(row["exit_execution_date"][:4] for row in top20)
    top20_entry_months = Counter(row["entry_signal_date"][:7] for row in top20)
    top20_exit_reasons = Counter(row["exit_reason"] for row in top20)
    exit_groups: dict[str, Any] = {}
    for reason in sorted({row["exit_reason"] for row in cycles}):
        rows = [row for row in cycles if row["exit_reason"] == reason]
        values = [float(row["realized_return"]) for row in rows]
        days = [float(row["holding_trading_days"]) for row in rows]
        exit_groups[reason] = {
            "trade_count": len(rows),
            "win_rate": sum(value > 0 for value in values) / len(values),
            "median_return": statistics.median(values),
            "mean_return": statistics.fmean(values),
            "total_pnl": sum(float(row["realized_pnl"]) for row in rows),
            "median_holding_days": statistics.median(days),
            "mean_holding_days": statistics.fmean(days),
        }
    payoff = statistics.fmean(winner_returns) / abs(statistics.fmean(loser_returns))
    profit_factor = sum(positive_pnls) / abs(sum(negative_pnls))

    summary = {
        "identity": {
            "strategy_sha256": EXPECTED_STRATEGY,
            "pit_manifest_sha256": EXPECTED_PIT,
            "phase1b_summary_sha256": EXPECTED_SUMMARY,
            "authorization_id": phase1["authorization"]["authorization_id"],
            "date_range": [START.isoformat(), END.isoformat()],
            "formal_replay_executions_this_phase": 0,
            "strategy_modified": False,
            "pit_rebuilt": False,
            "trade_ledger_modified": False,
        },
        "trade_count": len(cycles),
        "minvol_contract": {
            "minimum_volume_ratio_is_hard_filter": True,
            "evidence": "minvol_diagnostic.passed = location_passed and ratio_passed; candidate requires minimum.passed",
        },
        "concentration": {
            **concentrations,
            "return_ex_best10": return_exclusions["best10"],
            "return_ex_best20": return_exclusions["best20"],
            "positive_pnl_hhi": sum(share * share for share in positive_shares),
            "positive_trade_pnl_gini": gini_nonnegative(positive_pnls),
            "signed_trade_pnl_gini": None,
            "signed_trade_pnl_gini_status": "UNRESOLVED: ordinary Gini is not stable for signed P&L",
            "top20_unique_symbols": len(top20_symbols),
            "top20_repeated_symbols": {s: n for s, n in sorted(top20_symbols.items()) if n > 1},
            "top20_exit_year_distribution": dict(sorted(top20_years.items())),
            "top20_entry_month_distribution": dict(sorted(top20_entry_months.items())),
            "top20_exit_reason_distribution": dict(sorted(top20_exit_reasons.items())),
        },
        "right_tail": {
            "median": float(returns.median()),
            "mean": float(returns.mean()),
            "standard_deviation_sample": float(returns.std(ddof=1)),
            "skewness_sample": float(returns.skew()),
            "kurtosis_excess_sample": float(returns.kurt()),
            "average_winner": statistics.fmean(winner_returns),
            "average_loser": statistics.fmean(loser_returns),
            "median_winner": statistics.median(winner_returns),
            "median_loser": statistics.median(loser_returns),
            "profit_factor": profit_factor,
            "winner_loser_payoff_ratio": payoff,
            "win_rate": len(winner_returns) / len(cycles),
        },
        "group_definitions": {
            "GROUP_A": "PnL ranks 1-10 (all profitable)",
            "GROUP_B": "PnL ranks 11-20 (all profitable)",
            "GROUP_C": "PnL ranks 21-111",
        },
        "group_statistics": group_stats,
        "top20_vs_remainder": {"TOP20": top20_stats, "REMAINDER": remainder_stats},
        "exit_reason_statistics": exit_groups,
        "top20_trades": top20,
        "entry_cross_section_sizes": context["cross_section_sizes"],
        "methods": {
            "entry_features": "frozen signal functions on entry signal close; authorized daily PIT eligible cross-section; no future data",
            "holding_excursions": "first-entry-open gross underlying total-return path; corporate-action adjusted; exit day open only; realized return remains frozen engine cycle return",
            "industry_concentration": "UNRESOLVED: no already-authorized industry classification input was identified",
        },
        "phase3_candidate_ablation_list": [
            "BASELINE",
            "minus MINVOL",
            "minus FULL40",
            "minus B60",
            "minus market entry gate",
            "no-RS-selection control",
        ],
        "findings": {
            "top20_distinguishing_features": [
                {
                    "status": "FACT",
                    "feature": "holding_trading_days",
                    "top20_median": 33.5,
                    "remainder_median": 10.0,
                },
                {
                    "status": "FACT",
                    "feature": "MFE",
                    "top20_median": 0.718763,
                    "remainder_median": 0.063433,
                },
                {
                    "status": "FACT",
                    "feature": "MAE",
                    "top20_median": -0.011144,
                    "remainder_median": -0.058419,
                },
                {
                    "status": "INFERENCE",
                    "finding": "Post-entry persistence and favorable excursion separate Top20 much more than measured entry features; no causality claimed.",
                },
            ],
            "entry_feature_findings": {
                "RS": "Top20 final-RS separation is modest overall; GROUP_A is stronger but GROUP_B is level with GROUP_C.",
                "B60": "Top20 breakout margins are not larger than the remainder.",
                "FULL40": "Box width is modestly tighter; MA dispersion and direction efficiency are nearly level; vol ratio is slightly higher.",
                "MINVOL": "Location is modestly lower; minimum-volume ratio is nearly indistinguishable despite being a frozen hard filter.",
            },
            "holding_period_findings": "Top20 median hold/MFE/MAE are 33.5 sessions, +71.8763%, and -1.1144%, versus 10, +6.3433%, and -5.8419%.",
            "exit_findings": "MARKET_MA20_X2 contains 18/20 Top20 trades and the realized right tail; generic SET_CHANGE reason cannot be decomposed further from the frozen ledger.",
            "concentration_findings": "Top20 are 20 unique symbols and split 9/11 across exit years, but 9/20 entered in September 2024.",
            "causality_status": "DESCRIPTIVE_ASSOCIATION_ONLY",
        },
        "unresolved": [
            "Industry/sector concentration: no already-authorized classification input identified.",
            "Ordinary signed-PnL Gini is unstable; positive-trade PnL Gini is reported.",
            "MFE/MAE is an underlying first-entry path, not cash-flow-weighted IRR for later rebalances.",
            "SET_CHANGE_ENTRY_OR_INDIVIDUAL_EXIT cannot be split into finer exit causes from the frozen ledger.",
        ],
    }

    columns = [
        "trade_id", "pnl_rank", "winner_group", "win_loss_group", "symbol",
        "entry_signal_date", "entry_execution_date", "exit_signal_date", "exit_execution_date",
        "entry_price", "weighted_average_buy_price", "exit_price", "entry_target_weight", "capital",
        "realized_return", "realized_pnl", "holding_trading_days", "entry_reason", "exit_reason",
        "buy_fill_count", "sell_fill_count",
        "mom20", "mom60", "mom120", "r20", "r60", "r120", "final_rs_score",
        "entry_cross_section_rank", "entry_cross_section_percentile", "entry_cross_section_size",
        "previous_60_close_high", "signal_close", "b60_breakout_margin", "previous_60_high_distance_pct",
        "box_width", "ma5", "ma10", "ma20", "ma30", "ma_dispersion", "direction_efficiency",
        "vol10", "vol60", "vol_ratio_10_60", "box_width_margin", "ma_dispersion_margin",
        "direction_efficiency_margin", "vol_ratio_margin", "minvol_location", "minimum_volume",
        "average_volume", "minimum_volume_ratio", "min_volume_day_close", "30d_low_close", "30d_high_close",
        "minimum_volume_ratio_hard_filter", "turnover20_mean", "signal_day_volume",
        "previous20_volume_mean", "signal_day_volume_ratio", "breakout_volume_shadow_passed",
        "MFE", "MAE", "peak_return_during_hold", "trough_return_during_hold", "giveback_from_peak",
        "days_to_MFE", "days_to_MAE", "excursion_basis",
    ]
    pd.DataFrame(ordered)[columns].to_csv(OUTPUT_CSV, index=False, float_format="%.12g")
    OUTPUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    group_lines = [
        "| Feature | GROUP_A median / mean / [p25,p75] | GROUP_B median / mean / [p25,p75] | GROUP_C median / mean / [p25,p75] |",
        "|---|---:|---:|---:|",
    ] + [format_group_table(group_stats, feature) for feature in feature_columns]
    exit_lines = [
        "| Exact exit reason | Trades | Win rate | Median return | Mean return | Total P&L | Median hold | Mean hold |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for reason, row in exit_groups.items():
        exit_lines.append(
            f"| {reason} | {row['trade_count']} | {pct(row['win_rate'])} | {pct(row['median_return'])} | "
            f"{pct(row['mean_return'])} | {row['total_pnl']:,.2f} | {row['median_holding_days']:.1f} | {row['mean_holding_days']:.2f} |"
        )
    top_lines = [
        "| Rank | Symbol | Entry signal | Exit execution | P&L | Return | Hold days |",
        "|---:|---|---|---|---:|---:|---:|",
    ] + [
        f"| {row['pnl_rank']} | {row['symbol']} | {row['entry_signal_date']} | {row['exit_execution_date']} | "
        f"{row['realized_pnl']:,.2f} | {pct(row['realized_return'])} | {row['holding_trading_days']} |"
        for row in top20
    ]
    t = top20_stats
    r = remainder_stats
    report = f"""# ChinNext V1 winner concentration and signal attribution

> Offline descriptive attribution of the frozen Phase 1B trades. No strategy
> replay, new trade, NAV recomputation, parameter change, or PIT rebuild occurred.

## Frozen identity

- STRATEGY_SHA256: `{EXPECTED_STRATEGY}`
- PIT_MANIFEST_DIGEST: `{EXPECTED_PIT}`
- PHASE1B_SUMMARY_SHA256: `{EXPECTED_SUMMARY}`
- AUTHORIZATION_ID: `{phase1['authorization']['authorization_id']}`
- DATE_RANGE: `{START} .. {END}`
- TRADE_COUNT: `111`
- FORMAL_REPLAY_EXECUTIONS_THIS_PHASE: `0`

## Concentration

- TOP1_PNL_CONCENTRATION: `{pct(concentrations['top1'])}`
- TOP5_PNL_CONCENTRATION: `{pct(concentrations['top5'])}`
- TOP10_PNL_CONCENTRATION: `{pct(concentrations['top10'])}`
- TOP20_PNL_CONCENTRATION: `{pct(concentrations['top20'])}`
- RETURN_EX_BEST10: `{pct(return_exclusions['best10'])}`
- RETURN_EX_BEST20: `{pct(return_exclusions['best20'])}`
- POSITIVE_PNL_HHI: `{summary['concentration']['positive_pnl_hhi']:.6f}`
- POSITIVE_TRADE_PNL_GINI: `{summary['concentration']['positive_trade_pnl_gini']:.6f}`
- SIGNED_TRADE_PNL_GINI: `UNRESOLVED` (ordinary Gini is unstable for signed P&L)
- TOP20_UNIQUE_SYMBOLS: `{summary['concentration']['top20_unique_symbols']}`
- TOP20_REPEATED_SYMBOLS: `{json.dumps(summary['concentration']['top20_repeated_symbols'], ensure_ascii=False, sort_keys=True)}`
- TOP20_EXIT_YEAR_DISTRIBUTION: `{json.dumps(summary['concentration']['top20_exit_year_distribution'], sort_keys=True)}`

Concentration uses the same denominator as Phase 1B: all positive completed-cycle
P&L. The Top20 identity and order exactly match the frozen Phase 1B report.

## Right-tail profile

- MEDIAN_RETURN: `{pct(summary['right_tail']['median'])}`
- MEAN_RETURN: `{pct(summary['right_tail']['mean'])}`
- STANDARD_DEVIATION: `{pct(summary['right_tail']['standard_deviation_sample'])}`
- SKEWNESS: `{summary['right_tail']['skewness_sample']:.4f}`
- EXCESS_KURTOSIS: `{summary['right_tail']['kurtosis_excess_sample']:.4f}`
- WIN_RATE: `{pct(summary['right_tail']['win_rate'])}`
- AVERAGE_WINNER: `{pct(summary['right_tail']['average_winner'])}`
- AVERAGE_LOSER: `{pct(summary['right_tail']['average_loser'])}`
- MEDIAN_WINNER: `{pct(summary['right_tail']['median_winner'])}`
- MEDIAN_LOSER: `{pct(summary['right_tail']['median_loser'])}`
- WINNER_LOSER_PAYOFF_RATIO: `{summary['right_tail']['winner_loser_payoff_ratio']:.4f}`
- PROFIT_FACTOR: `{summary['right_tail']['profit_factor']:.4f}`

**FACT:** Positive skew, a mean far above the median, sub-50% win rate and a
winner/loser payoff ratio above one describe a right-tailed return distribution.
**INFERENCE:** This profile is consistent with trend-following; the attribution
does not establish that any module caused it.

## Group comparison

Cells are `median / mean / [p25, p75]`. GROUP_A is P&L ranks 1–10, GROUP_B
ranks 11–20, and GROUP_C ranks 21–111.

{chr(10).join(group_lines)}

## What distinguishes Top20?

| Feature | Top20 median | Remaining 91 median | Top20 mean | Remaining mean |
|---|---:|---:|---:|---:|
| final_rs_score | {t['final_rs_score']['median']:.6g} | {r['final_rs_score']['median']:.6g} | {t['final_rs_score']['mean']:.6g} | {r['final_rs_score']['mean']:.6g} |
| B60 breakout margin | {pct(t['b60_breakout_margin']['median'])} | {pct(r['b60_breakout_margin']['median'])} | {pct(t['b60_breakout_margin']['mean'])} | {pct(r['b60_breakout_margin']['mean'])} |
| box width | {pct(t['box_width']['median'])} | {pct(r['box_width']['median'])} | {pct(t['box_width']['mean'])} | {pct(r['box_width']['mean'])} |
| MA dispersion | {pct(t['ma_dispersion']['median'])} | {pct(r['ma_dispersion']['median'])} | {pct(t['ma_dispersion']['mean'])} | {pct(r['ma_dispersion']['mean'])} |
| direction efficiency | {t['direction_efficiency']['median']:.4f} | {r['direction_efficiency']['median']:.4f} | {t['direction_efficiency']['mean']:.4f} | {r['direction_efficiency']['mean']:.4f} |
| vol10/vol60 | {t['vol_ratio_10_60']['median']:.4f} | {r['vol_ratio_10_60']['median']:.4f} | {t['vol_ratio_10_60']['mean']:.4f} | {r['vol_ratio_10_60']['mean']:.4f} |
| MINVOL location | {t['minvol_location']['median']:.4f} | {r['minvol_location']['median']:.4f} | {t['minvol_location']['mean']:.4f} | {r['minvol_location']['mean']:.4f} |
| minimum-volume ratio | {t['minimum_volume_ratio']['median']:.4f} | {r['minimum_volume_ratio']['median']:.4f} | {t['minimum_volume_ratio']['mean']:.4f} | {r['minimum_volume_ratio']['mean']:.4f} |
| holding trading days | {t['holding_trading_days']['median']:.1f} | {r['holding_trading_days']['median']:.1f} | {t['holding_trading_days']['mean']:.2f} | {r['holding_trading_days']['mean']:.2f} |
| MFE | {pct(t['MFE']['median'])} | {pct(r['MFE']['median'])} | {pct(t['MFE']['mean'])} | {pct(r['MFE']['mean'])} |
| MAE | {pct(t['MAE']['median'])} | {pct(r['MAE']['median'])} | {pct(t['MAE']['mean'])} | {pct(r['MAE']['mean'])} |
| giveback from peak | {pct(t['giveback_from_peak']['median'])} | {pct(r['giveback_from_peak']['median'])} | {pct(t['giveback_from_peak']['mean'])} | {pct(r['giveback_from_peak']['mean'])} |

These are descriptive associations, not causal effects or threshold recommendations.

### A–G descriptive answers

**A. RS — modest separation, not a complete explanation.** Top20 final-RS median
was `0.6902` versus `0.6757` for the remaining trades; their median cross-section
percentile was `0.7770` versus `0.7396`. GROUP_A was clearly stronger
(`0.7882` median score), but GROUP_B (`0.6763`) was effectively level with
GROUP_C. **FACT:** high RS characterized the largest ten more than ranks 11–20.
**INFERENCE:** RS alone does not explain the full Top20 concentration.

**B. B60 — no stronger-margin pattern.** Top20 median breakout margin was
`1.8078%`, below the remainder's `2.4324%`; means were `4.3472%` and `4.8229%`.
**FACT:** the large winners were not systematically the entries farthest above
their previous 60-close high. This does not test whether B60 itself is necessary.

**C. FULL40 — mixed and mostly weak separation.** Top20 box width was somewhat
tighter (`14.8393%` median versus `16.5414%`), but MA dispersion (`3.3683%`
versus `3.6056%`) and direction efficiency (`0.0976` versus `0.1031`) were close.
Top20 vol10/vol60 was slightly higher, not more compressed (`0.7173` versus
`0.6871`). **INFERENCE:** only box width shows a modest descriptive compression
difference; the FULL40 submetrics do not jointly form a strong separator.

**D. MINVOL — location modestly lower; ratio indistinguishable.** Top20 median
location was `0.1195` versus `0.1522`, while minimum-volume ratio was `0.4863`
versus `0.4676`. **FACT:** the ratio is nevertheless a real hard filter in the
frozen strategy. **INFERENCE:** among trades already passing MINVOL, its ratio
has almost no descriptive power for identifying Top20.

**E. Holding path — dominant observed separation.** Top20 median holding time was
`33.5` sessions versus `10.0`; MFE was `71.8763%` versus `6.3433%`; MAE was
`-1.1144%` versus `-5.8419%`. Giveback was larger, not smaller (`28.0681%`
versus `8.1384%`), because the winners first accumulated much larger gains.
**FACT:** post-entry trend persistence and favorable excursion separate the
groups by far more than any measured entry feature. **INFERENCE:** the baseline's
right tail is associated with allowing a small set of positions to persist; this
does not establish that changing an exit would improve results.

**F. Time and symbol concentration.** Top20 contains `20` distinct symbols and no
repeat contributor. Exit-year distribution is `9` in 2024 and `11` in 2025, so
it is not a one-year-only result. However, `9/20` entered in September 2024
(`7` on 2024-09-24 and `2` on 2024-09-25), establishing meaningful cohort/time
concentration. The remaining entry-month counts were 2025-02:1, 2025-06:3,
2025-07:1, 2025-08:2, 2025-09:1, 2025-10:1 and 2025-11:2.

**G. Modules with little descriptive separation.** B60 breakout margin,
minimum-volume ratio, MA dispersion and direction efficiency were all close or
moved in the opposite direction from a simple “more is better” story. These are
the clearest `CANDIDATE_FOR_PHASE3_ABLATION` modules/submodules, but Phase 2 does
not show that they are useless and does not select replacement thresholds.

## Exact exit-reason attribution

{chr(10).join(exit_lines)}

Exit reasons remain ledger-exact; no different semantics are merged.

`MARKET_MA20_X2` accounted for `18/20` Top20 trades and `1,271,764.28` of their
P&L. Across all trades it produced `1,050,977.00` net P&L, versus `-111,824.39`
for `SET_CHANGE_ENTRY_OR_INDIVIDUAL_EXIT`. **FACT:** market-exit trades contain
the realized right tail. **UNRESOLVED:** the generic second ledger reason cannot
be reliably decomposed after the fact into individual MA30 exits versus other
set-change mechanics without changing the frozen ledger's reason semantics.

## MINVOL implementation fact

`minimum_volume_ratio <= 0.70` is a **hard filter**, not shadow-only. Frozen code
sets `passed = location_passed and ratio_passed`, and the candidate path requires
`minimum.passed`.

## Holding-excursion method

MFE uses observable daily highs and MAE daily lows after the entry open; peak and
trough use closes. The exit session contributes only the actual exit open, so no
post-exit high/low/close is consumed. Cash dividends and share multipliers are
carried forward in the underlying total-return path. Realized return and P&L remain
the frozen engine's completed-cycle values. Later rebalance cash flows do not alter
this underlying-path diagnostic.

## Frozen Top20

{chr(10).join(top_lines)}

## Phase 3 pre-registration candidates — not run

1. `BASELINE`
2. `minus MINVOL` — candidate because the passing-trade ratio barely separates groups
3. `minus B60` — candidate because breakout margin does not separate Top20
4. `minus FULL40` — isolate the mixed compression evidence
5. `no-RS-selection control` — isolate the modest aggregate RS separation
6. `minus market entry gate` — isolate cohort/timing exposure

This is a candidate list only. A final matrix must be frozen before any ablation
result is run; Phase 2 performs no ablation or parameter search.

## Unresolved

- Industry/sector concentration: no already-authorized classification input identified.
- Signed-P&L ordinary Gini: unstable for samples containing losses; positive-trade Gini is reported instead.
- Holding MFE/MAE measures the underlying first-entry path, not a cash-flow-weighted IRR for later top-ups/reductions.
- `SET_CHANGE_ENTRY_OR_INDIVIDUAL_EXIT` cannot be split into finer exit causes from the frozen ledger alone.
"""
    OUTPUT_MD.write_text(report, encoding="utf-8")
    print(json.dumps({"trade_count": len(cycles), "top20": concentrations["top20"], "skew": summary["right_tail"]["skewness_sample"]}, sort_keys=True))


if __name__ == "__main__":
    main()
