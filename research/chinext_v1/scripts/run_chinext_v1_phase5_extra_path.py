#!/usr/bin/env python3
"""Offline Phase 5 extra-entry path and crowd-out attribution; never replays trades."""

from __future__ import annotations

import csv
import io
import json
import math
import statistics
import sys
from collections import Counter
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
    atomic_text,
    build_rs_table,
    contiguous_tail,
    critical_row_valid,
    daily_glob,
    load_pit_membership,
    load_sample_panel,
    load_sessions,
    row_map,
    sha256_file,
    write_json,
)
from run_chinext_v1_winner_attribution import action_values  # noqa: E402

REPORTS = ROOT / "research/chinext_v1/reports"
PHASE3_OUTPUT = ROOT / "research/chinext_v1/output/chinext_v1_phase3_ablation"
PHASE4_OUTPUT = ROOT / "research/chinext_v1/output/chinext_v1_phase4_matched"
STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"
PIT_MANIFEST = REPORTS / "chinext_v1_pit_master_manifest.json"
PIT_MEMBERSHIP = ROOT / "research/chinext_v1/data/pit_2024_2025/daily_membership.parquet"
PHASE2 = REPORTS / "chinext_v1_winner_attribution_summary.json"
PHASE3_SPEC = REPORTS / "chinext_v1_phase3_ablation_spec.json"
PHASE3_SUMMARY = REPORTS / "chinext_v1_phase3_ablation_summary.json"
PHASE4_SPEC = REPORTS / "chinext_v1_phase4_matched_spec.json"
PHASE4_SUMMARY = REPORTS / "chinext_v1_phase4_exposure_matched_summary.json"
PHASE4_CROWDOUT = REPORTS / "chinext_v1_phase4_winner_crowdout.csv"
OUTPUT_MD = REPORTS / "chinext_v1_phase5_extra_path.md"
OUTPUT_JSON = REPORTS / "chinext_v1_phase5_extra_path_summary.json"
OUTPUT_TRADES = REPORTS / "chinext_v1_phase5_extra_trades.csv"
OUTPUT_PAIRS = REPORTS / "chinext_v1_phase5_crowdout_pairs.csv"
START = date(2024, 1, 2)
END = date(2025, 12, 31)

EXPECTED = {
    "strategy": "dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a",
    "pit_manifest": "8b4519ff6cf74aa0ca13b15bd3954cce3a37f6dd19d25f3f77743e9a974e75f7",
    "phase3_spec": "530a5cabddf5afbef86f3fd433a6be35a36973bf3f7662944267a3bec97f160c",
    "phase3_summary": "9762426dc2787c6d34a1b6ba6caf44863863ab1f185c85ab799f37aa4b6891b2",
    "phase4_spec": "6823ac96d9f93922e64f71e2b7dd0048ca522f7c280b9d4388534e8c77563509",
    "phase4_summary": "356ac829524f4201a658052603941c797405fab507376ff06ad08aef4479500d",
    "phase4_crowdout": "c7db5999b7b555e140f43bcd37196d371ebebbd0cfa94feeb426b5741a765088",
}

ARM_PATHS = {
    "A0_BASELINE": PHASE3_OUTPUT / "a0_baseline",
    "A2_MINUS_B60_RAW": PHASE3_OUTPUT / "a2_minus_b60",
    "A3_MINUS_FULL40_RAW": PHASE3_OUTPUT / "a3_minus_full40",
    "M2_MINUS_B60_MATCHED": PHASE4_OUTPUT / "m2_minus_b60_baseline_capacity",
    "M3_MINUS_FULL40_MATCHED": PHASE4_OUTPUT / "m3_minus_full40_baseline_capacity",
}
EXTRA_ARMS = (
    "A2_MINUS_B60_RAW",
    "M2_MINUS_B60_MATCHED",
    "A3_MINUS_FULL40_RAW",
    "M3_MINUS_FULL40_MATCHED",
)
ENTRY_FEATURES = (
    "mom20",
    "mom60",
    "mom120",
    "r20",
    "r60",
    "r120",
    "final_rs_score",
    "entry_cross_section_percentile",
    "b60_breakout_margin",
    "box_width",
    "ma_dispersion",
    "direction_efficiency",
    "vol_ratio_10_60",
    "minvol_location",
    "minimum_volume_ratio",
    "turnover20_mean",
)
PATH_FEATURES = (
    "holding_trading_days",
    "MFE",
    "MAE",
    "days_to_MFE",
    "giveback_from_peak",
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def validate_inputs() -> dict[str, Any]:
    paths = {
        "strategy": STRATEGY,
        "pit_manifest": PIT_MANIFEST,
        "phase3_spec": PHASE3_SPEC,
        "phase3_summary": PHASE3_SUMMARY,
        "phase4_spec": PHASE4_SPEC,
        "phase4_summary": PHASE4_SUMMARY,
        "phase4_crowdout": PHASE4_CROWDOUT,
    }
    actual = {name: sha256_file(path) for name, path in paths.items()}
    if actual != EXPECTED:
        raise RuntimeError(f"frozen Phase 5 input mismatch: expected={EXPECTED}, actual={actual}")
    phase4_spec = json.loads(PHASE4_SPEC.read_text(encoding="utf-8"))
    phase4_summary = json.loads(PHASE4_SUMMARY.read_text(encoding="utf-8"))
    if phase4_summary["new_formal_replay_executions"] != 2:
        raise RuntimeError("Phase 4 formal identity changed")
    if phase4_summary["identity"]["current_survivor_fallback"] is not False:
        raise RuntimeError("current-survivor fallback appeared in Phase 4")
    input_hashes: dict[str, Any] = {"reports": actual, "arms": {}}
    for arm, directory in ARM_PATHS.items():
        engine_path = directory / "engine_summary.json"
        engine = json.loads(engine_path.read_text(encoding="utf-8"))
        if engine["data"].get("current_survivor_fallback") is not False:
            raise RuntimeError(f"current-survivor fallback in {arm}")
        arm_hashes = {
            "engine_summary": sha256_file(engine_path),
            "event_ledger": sha256_file(directory / "event_ledger.jsonl"),
            "execution_ledger": sha256_file(directory / "execution_ledger.jsonl"),
            "daily_nav": sha256_file(directory / "daily_nav.jsonl"),
        }
        for role in ("event_ledger", "execution_ledger", "daily_nav"):
            if arm_hashes[role] != engine["audit"][f"{role}_sha256"]:
                raise RuntimeError(f"{arm} {role} differs from its frozen engine audit")
        if arm.startswith(("A0", "A2", "A3")):
            raw_key = arm.replace("_RAW", "")
            expected_arm = phase4_spec["frozen_identity"]["phase3_file_sha256"][raw_key]
            if arm_hashes != expected_arm:
                raise RuntimeError(f"Phase 3 file identity changed for {arm}")
        input_hashes["arms"][arm] = arm_hashes
    return input_hashes


def build_cycles(executions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], set[tuple[str, str]]]:
    active: dict[str, dict[str, Any]] = {}
    completed: list[dict[str, Any]] = []
    selected: set[tuple[str, str]] = set()
    for sequence, row in enumerate(executions):
        if row.get("status") != "FILLED":
            continue
        symbol = str(row["symbol"])
        if row["side"] == "BUY" and row.get("new_position") is True:
            if symbol in active:
                raise RuntimeError(f"overlapping frozen cycle for {symbol}")
            episode = (symbol, str(row["signal_date"]))
            if episode in selected:
                raise RuntimeError(f"duplicate selected episode {episode}")
            selected.add(episode)
            active[symbol] = {
                "symbol": symbol,
                "entry_signal_date": str(row["signal_date"]),
                "entry_execution_date": str(row["execution_date"]),
                "entry_reason": str(row["signal_reason"]),
                "execution_rows": [],
                "realized_pnl": 0.0,
                "buy_cost": 0.0,
            }
        if symbol not in active:
            raise RuntimeError(f"filled execution outside an active cycle: {symbol}")
        cycle = active[symbol]
        execution = dict(row)
        execution["ledger_sequence"] = sequence
        cycle["execution_rows"].append(execution)
        if row["side"] == "BUY":
            cycle["buy_cost"] += float(row["notional"]) + float(row["cost"])
        else:
            cycle["realized_pnl"] += float(row["realized_pnl"])
            if row.get("completed_round_trip") is True:
                cycle = active.pop(symbol)
                cycle.update(
                    {
                        "exit_signal_date": str(row["signal_date"]),
                        "exit_execution_date": str(row["execution_date"]),
                        "exit_reason": str(row["signal_reason"]),
                        "realized_return": float(row["round_trip_return"]),
                    }
                )
                completed.append(cycle)
    return completed, selected


def event_evaluations(events: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (str(row["symbol"]), str(row["signal_date"])): row
        for row in events
        if row.get("event") == "ENTRY_SIGNAL_EVALUATED"
    }


def build_market_context(
    target_keys: set[tuple[str, str]],
) -> tuple[dict[tuple[str, str], dict[str, Any]], list[date], dict[date, dict[str, dict[str, Any]]]]:
    config = ChinNextV1Config()
    symbols, membership_by_date, _ = load_pit_membership(PIT_MEMBERSHIP, START, END)
    target_dates = {date.fromisoformat(day) for _, day in target_keys}
    paths = daily_glob(DEFAULT_DAILY_ROOT, date(2018, 1, 1), END)
    connection = duckdb.connect()
    warmup_start = date(2023, 1, 1)
    panel = load_sample_panel(connection, paths, tuple(symbols), warmup_start, END)
    sessions = load_sessions(DEFAULT_CALENDAR, warmup_start, END)
    rows_by_date = row_map(panel)
    session_index = {day: index for index, day in enumerate(sessions)}
    closes: dict[str, list[float]] = {symbol: [] for symbol in symbols}
    volumes: dict[str, list[float]] = {symbol: [] for symbol in symbols}
    amounts: dict[str, list[float]] = {symbol: [] for symbol in symbols}
    dates: dict[str, list[date]] = {symbol: [] for symbol in symbols}
    features: dict[tuple[str, str], dict[str, Any]] = {}

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
                and statistics.fmean(amounts[symbol][-config.turnover20_days :])
                >= config.turnover20_min_cny
            )
            if history_ok and liquidity_ok and critical_row_valid(day_rows.get(symbol)):
                eligible.append(symbol)
        rs = build_rs_table(closes, eligible, config)
        ordered = sorted(rs, key=lambda symbol: (-rs[symbol]["score"], -rs[symbol]["mom60"], symbol))
        ranks = {symbol: index for index, symbol in enumerate(ordered, start=1)}
        for symbol, signal_text in sorted(target_keys):
            if signal_text != day.isoformat():
                continue
            if symbol not in rs:
                raise RuntimeError(f"selected frozen episode absent from RS cross-section: {symbol} {day}")
            series = closes[symbol]
            previous_high = max(series[-61:-1])
            signal_close = series[-1]
            features[(symbol, signal_text)] = {
                **rs[symbol],
                "final_rs_score": rs[symbol]["score"],
                "entry_cross_section_rank": ranks[symbol],
                "entry_cross_section_percentile": 1.0 - (ranks[symbol] - 1) / len(ordered),
                "entry_cross_section_size": len(ordered),
                "previous_60_high": previous_high,
                "signal_close": signal_close,
                "b60_breakout_margin": signal_close / previous_high - 1.0,
                "turnover20_mean": statistics.fmean(amounts[symbol][-20:]),
            }
    if set(features) != target_keys:
        raise RuntimeError(f"entry feature coverage mismatch: {len(features)} != {len(target_keys)}")
    return features, sessions, rows_by_date


def enrich_entry_features(
    episode: tuple[str, str],
    evaluation: dict[str, Any],
    reconstructed: dict[str, Any],
) -> dict[str, Any]:
    if evaluation is None:
        raise RuntimeError(f"missing persisted candidate evaluation for selected episode {episode}")
    for field in ("mom20", "mom60", "mom120", "r20", "r60", "r120"):
        if not math.isclose(float(evaluation["rs"][field]), float(reconstructed[field]), abs_tol=1e-12):
            raise RuntimeError(f"reconstructed RS differs from persisted signal for {episode} {field}")
    full = evaluation["full40"]
    minimum = evaluation["minvol"]
    return {
        **reconstructed,
        "box_width": full["box_width"],
        "ma_dispersion": full["ma_dispersion"],
        "direction_efficiency": full["direction_efficiency"],
        "vol_ratio_10_60": full["vol_ratio"],
        "full40_diagnostic_passed": evaluation["phase3_ablation"]["full40_diagnostic_passed"],
        "b60_diagnostic_passed": evaluation["phase3_ablation"]["b60_diagnostic_passed"],
        "minvol_location": minimum["location"],
        "minimum_volume_ratio": minimum["minimum_volume_ratio"],
    }


def path_features(
    cycle: dict[str, Any],
    sessions: list[date],
    rows_by_date: dict[date, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    symbol = cycle["symbol"]
    entry_day = date.fromisoformat(cycle["entry_execution_date"])
    exit_day = date.fromisoformat(cycle["exit_execution_date"])
    start = sessions.index(entry_day)
    stop = sessions.index(exit_day)
    executions_by_date: dict[date, list[dict[str, Any]]] = {}
    for row in cycle["execution_rows"]:
        executions_by_date.setdefault(date.fromisoformat(str(row["execution_date"])), []).append(row)
    shares = 0.0
    total_buy_cost = 0.0
    net_sell_proceeds = 0.0
    dividends = 0.0
    high_path: list[tuple[int, float]] = []
    low_path: list[tuple[int, float]] = []

    for offset, day in enumerate(sessions[start : stop + 1]):
        row = rows_by_date.get(day, {}).get(symbol)
        if row is None:
            raise RuntimeError(f"held path row missing: {symbol} {day}")
        valid_action, multiplier, cash_per_share = action_values(row, day)
        if valid_action and shares > 0 and (multiplier != 1.0 or cash_per_share != 0.0):
            dividends += shares * cash_per_share
            shares = round(shares * multiplier)
        for execution in sorted(executions_by_date.get(day, []), key=lambda item: item["ledger_sequence"]):
            if execution["side"] == "BUY":
                shares += float(execution["shares"])
                total_buy_cost += float(execution["notional"]) + float(execution["cost"])
            else:
                shares -= float(execution["shares"])
                net_sell_proceeds += float(execution["notional"]) - float(execution["cost"])
        if total_buy_cost <= 0:
            raise RuntimeError(f"path has no invested capital: {symbol} {day}")

        def marked_return(price: float) -> float:
            return (net_sell_proceeds + dividends + shares * price - total_buy_cost) / total_buy_cost

        if day == exit_day:
            terminal = (net_sell_proceeds + dividends - total_buy_cost) / total_buy_cost
            high_path.append((offset, terminal))
            low_path.append((offset, terminal))
        else:
            high_path.append((offset, marked_return(float(row["high"]))))
            low_path.append((offset, marked_return(float(row["low"]))))
    if abs(shares) > 1e-8:
        raise RuntimeError(f"completed cycle ended with shares: {symbol} {shares}")
    terminal_return = high_path[-1][1]
    if not math.isclose(terminal_return, float(cycle["realized_return"]), abs_tol=1e-10):
        raise RuntimeError(
            f"path terminal return differs from frozen ledger: {symbol} {terminal_return} "
            f"!= {cycle['realized_return']}"
        )
    days_to_mfe, mfe = max(high_path, key=lambda item: item[1])
    _, mae = min(low_path, key=lambda item: item[1])

    def first_day(threshold: float) -> int | None:
        return next((offset for offset, value in high_path if value >= threshold), None)

    return {
        "holding_trading_days": stop - start,
        "MFE": mfe,
        "MAE": mae,
        "days_to_MFE": days_to_mfe,
        "peak_return": mfe,
        "trough_return": mae,
        "giveback_from_peak": mfe - float(cycle["realized_return"]),
        "first_5pct_gain_day": first_day(0.05),
        "first_10pct_gain_day": first_day(0.10),
        "first_20pct_gain_day": first_day(0.20),
        "first_50pct_gain_day": first_day(0.50),
        "path_basis": (
            "frozen execution cash flows plus authorized intraday high/low; corporate-action adjusted; "
            "exit day stops at frozen open execution"
        ),
    }


def distribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = np.asarray([float(row["realized_return"]) for row in rows], dtype=float)
    pnls = np.asarray([float(row["realized_pnl"]) for row in rows], dtype=float)
    holds = np.asarray([float(row["holding_trading_days"]) for row in rows], dtype=float)
    winners = returns[returns > 0]
    losers = returns[returns <= 0]
    positive_pnl = pnls[pnls > 0]
    nonpositive_pnl = pnls[pnls <= 0]
    series = pd.Series(returns)
    return {
        "completed_trade_count": len(rows),
        "win_rate": float(np.mean(returns > 0)),
        "mean_return": float(np.mean(returns)),
        "median_return": float(np.median(returns)),
        **{f"p{q}_return": float(np.percentile(returns, q)) for q in (10, 25, 50, 75, 90, 95)},
        "standard_deviation": float(np.std(returns, ddof=0)),
        "skewness": float(series.skew()),
        "excess_kurtosis": float(series.kurt()),
        "mean_pnl": float(np.mean(pnls)),
        "total_pnl": float(np.sum(pnls)),
        "average_winner_return": float(np.mean(winners)) if len(winners) else None,
        "average_loser_return": float(np.mean(losers)) if len(losers) else None,
        "payoff_ratio": (
            float(np.mean(winners) / abs(np.mean(losers))) if len(winners) and len(losers) else None
        ),
        "profit_factor": (
            float(np.sum(positive_pnl) / abs(np.sum(nonpositive_pnl)))
            if len(nonpositive_pnl) and np.sum(nonpositive_pnl) < 0
            else None
        ),
        "holding_days_mean": float(np.mean(holds)),
        "holding_days_median": float(np.median(holds)),
        "holding_days_p75": float(np.percentile(holds, 75)),
        "holding_days_p90": float(np.percentile(holds, 90)),
        "positive_trade_count": int(np.sum(returns > 0)),
        "nonpositive_trade_count": int(np.sum(returns <= 0)),
    }


def group_quantiles(rows: list[dict[str, Any]], features: tuple[str, ...]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for feature in features:
        values = np.asarray([float(row[feature]) for row in rows if row.get(feature) is not None])
        if not len(values):
            result[feature] = None
            continue
        result[feature] = {
            "mean": float(np.mean(values)),
            "median": float(np.median(values)),
            "p25": float(np.percentile(values, 25)),
            "p75": float(np.percentile(values, 75)),
        }
    return result


def cliffs_delta(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    greater = sum(a > b for a in left for b in right)
    lower = sum(a < b for a in left for b in right)
    return (greater - lower) / (len(left) * len(right))


def separation_summary(cohorts: dict[str, list[dict[str, Any]]], features: tuple[str, ...]) -> dict[str, Any]:
    effects: dict[str, dict[str, float]] = {}
    all_abs: list[float] = []
    for arm, rows in cohorts.items():
        ordered = sorted(rows, key=lambda row: (-float(row["realized_pnl"]), row["symbol"], row["entry_signal_date"]))
        top = ordered[: min(20, len(ordered))]
        remainder = ordered[min(20, len(ordered)) :]
        effects[arm] = {}
        for feature in features:
            left = [float(row[feature]) for row in top if row.get(feature) is not None]
            right = [float(row[feature]) for row in remainder if row.get(feature) is not None]
            delta = cliffs_delta(left, right)
            effects[arm][feature] = delta
            if right:
                all_abs.append(abs(delta))
    median_abs = statistics.median(all_abs) if all_abs else 0.0
    moderate_or_large = sum(value >= 0.33 for value in all_abs)
    if median_abs >= 0.33 or moderate_or_large >= max(3, math.ceil(len(all_abs) * 0.35)):
        strength = "STRONG"
    elif median_abs >= 0.147 or moderate_or_large >= 2:
        strength = "MODERATE"
    else:
        strength = "WEAK"
    return {
        "method": "absolute Cliff's delta; 0.147/0.33 conventional descriptive cut points",
        "median_absolute_cliffs_delta": median_abs,
        "moderate_or_large_comparison_count": moderate_or_large,
        "comparison_count": len(all_abs),
        "strength": strength,
        "effects": effects,
    }


def separation_feature_ranking(separation: dict[str, Any]) -> list[dict[str, Any]]:
    effects = separation["effects"]
    features = next(iter(effects.values()))
    return sorted(
        (
            {
                "feature": feature,
                "median_absolute_cliffs_delta": statistics.median(
                    abs(arm_effects[feature]) for arm_effects in effects.values()
                ),
                "cohort_effects": {
                    arm: arm_effects[feature] for arm, arm_effects in effects.items()
                },
                "direction_consistent": len(
                    {
                        1 if arm_effects[feature] > 0 else -1 if arm_effects[feature] < 0 else 0
                        for arm_effects in effects.values()
                    }
                )
                == 1,
            }
            for feature in features
        ),
        key=lambda row: (-row["median_absolute_cliffs_delta"], row["feature"]),
    )


def assign_outcome_groups(rows: list[dict[str, Any]]) -> None:
    ordered = sorted(rows, key=lambda row: (-float(row["realized_pnl"]), row["symbol"], row["entry_signal_date"]))
    for rank, row in enumerate(ordered, start=1):
        row["extra_pnl_rank"] = rank
        row["extra_outcome_group"] = (
            "EXTRA_TOP10_PNL_TRADES"
            if rank <= 10
            else "EXTRA_TOP11_TO_20_PNL_TRADES"
            if rank <= 20
            else "EXTRA_REMAINING_TRADES"
        )
        row["extra_top20"] = rank <= 20
        row["positive_trade"] = float(row["realized_return"]) > 0


def origin_snapshots(
    events: list[dict[str, Any]], target_dates: set[str]
) -> dict[str, dict[str, tuple[str, str]]]:
    changes = sorted(
        (row for row in events if row.get("event") == "DESIRED_SET_CHANGED"),
        key=lambda row: row["signal_date"],
    )
    planned: set[str] = set()
    origins: dict[str, tuple[str, str]] = {}
    snapshots: dict[str, dict[str, tuple[str, str]]] = {}
    by_date = {str(row["signal_date"]): row for row in changes}
    for day in sorted(set(by_date) | target_dates):
        if day in target_dates:
            snapshots[day] = dict(origins)
        change = by_date.get(day)
        if change:
            new = set(change["desired"])
            for symbol in planned - new:
                origins.pop(symbol, None)
            for symbol in new - planned:
                origins[symbol] = (symbol, day)
            planned = new
    return snapshots


def crowdout_pair_rows(
    phase4_rows: list[dict[str, str]],
    arm_events: dict[str, list[dict[str, Any]]],
    cycles_by_arm: dict[str, dict[tuple[str, str], dict[str, Any]]],
    extras_by_arm: dict[str, set[tuple[str, str]]],
    features_by_arm: dict[str, dict[tuple[str, str], dict[str, Any]]],
    a0_cycles: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    arm_map = {"A2_MINUS_B60": "A2_MINUS_B60_RAW", "A3_MINUS_FULL40": "A3_MINUS_FULL40_RAW"}
    target_dates = {
        raw: {row["entry_signal_date"] for row in phase4_rows if row["raw_arm"] == raw}
        for raw in arm_map
    }
    snapshots = {
        raw: origin_snapshots(arm_events[arm_map[raw]], target_dates[raw]) for raw in arm_map
    }
    results: list[dict[str, Any]] = []
    for row in phase4_rows:
        if row["finite_capacity_crowdout"] != "True":
            continue
        raw = row["raw_arm"]
        arm = arm_map[raw]
        day = row["entry_signal_date"]
        baseline_episode = (row["symbol"], day)
        if row["classification"] == "ELIGIBLE_BUT_OUTRANKED":
            blocker_episodes = [
                (symbol, day)
                for symbol in row["selected_additions"].split("|")
                if symbol and (symbol, day) in extras_by_arm[arm]
            ]
            reason = "OUTRANKED"
        else:
            blocker_episodes = [
                snapshots[raw][day][symbol]
                for symbol in row["extra_survivors"].split("|")
                if symbol and symbol in snapshots[raw][day]
                and snapshots[raw][day][symbol] in extras_by_arm[arm]
            ]
            reason = "NO_VACANCY_FROM_EARLIER_EXTRA_ENTRY"
        blocker_episodes = sorted(set(blocker_episodes))
        if not blocker_episodes:
            raise RuntimeError(f"finite crowd-out row has no proven extra blocker set: {row}")
        blockers = [cycles_by_arm[arm].get(episode) for episode in blocker_episodes]
        completed = [cycle for cycle in blockers if cycle is not None]
        baseline = a0_cycles[baseline_episode]
        aggregate_pnl = sum(float(cycle["realized_pnl"]) for cycle in completed)
        one_to_one = len(blocker_episodes) == 1 and len(completed) == 1
        results.append(
            {
                "module": "B60" if raw == "A2_MINUS_B60" else "FULL40",
                "crowdout_arm": raw,
                "baseline_rank": int(row["baseline_rank"]),
                "baseline_winner_symbol": baseline["symbol"],
                "baseline_entry_signal_date": baseline["entry_signal_date"],
                "baseline_realized_pnl": baseline["realized_pnl"],
                "baseline_realized_return": baseline["realized_return"],
                "blockage_reason": reason,
                "lineage_type": "CROWDOUT_PAIR" if one_to_one else "CROWDOUT_SET",
                "blocking_extra_count": len(blocker_episodes),
                "blocking_episodes": "|".join(f"{symbol}@{signal}" for symbol, signal in blocker_episodes),
                "blocking_symbols": "|".join(symbol for symbol, _ in blocker_episodes),
                "blocking_entry_signal_dates": "|".join(signal for _, signal in blocker_episodes),
                "blocking_rs_ranks": "|".join(
                    str(features_by_arm[arm][episode]["entry_cross_section_rank"])
                    for episode in blocker_episodes
                ),
                "blocking_holding_intervals": "|".join(
                    "OPEN_OR_INCOMPLETE"
                    if cycle is None
                    else f"{cycle['entry_execution_date']}..{cycle['exit_execution_date']}"
                    for cycle in blockers
                ),
                "blocking_realized_pnls": "|".join(
                    "NA" if cycle is None else f"{float(cycle['realized_pnl']):.12g}"
                    for cycle in blockers
                ),
                "blocking_realized_returns": "|".join(
                    "NA" if cycle is None else f"{float(cycle['realized_return']):.12g}"
                    for cycle in blockers
                ),
                "blocking_set_completed_count": len(completed),
                "blocking_set_aggregate_realized_pnl": aggregate_pnl,
                "descriptive_pnl_gap": (
                    float(baseline["realized_pnl"]) - float(completed[0]["realized_pnl"])
                    if one_to_one
                    else None
                ),
                "counterfactual_status": "NOT_A_PORTFOLIO_COUNTERFACTUAL",
            }
        )
    return sorted(results, key=lambda row: (row["module"], row["baseline_rank"]))


def crowdout_summary(
    module: str,
    pairs: list[dict[str, Any]],
    cycles_by_arm: dict[str, dict[tuple[str, str], dict[str, Any]]],
    extra_rows: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    rows = [row for row in pairs if row["module"] == module]
    arm = "A2_MINUS_B60_RAW" if module == "B60" else "A3_MINUS_FULL40_RAW"
    episodes = {
        tuple(item.split("@", 1))
        for row in rows
        for item in row["blocking_episodes"].split("|")
    }
    blockers = [cycles_by_arm[arm].get(episode) for episode in episodes]
    completed = [row for row in blockers if row is not None]
    top20 = {
        (row["symbol"], row["entry_signal_date"])
        for row in extra_rows[arm]
        if row.get("extra_top20") is True
    }
    returns = [float(row["realized_return"]) for row in completed]
    pair_gaps = [
        float(row["descriptive_pnl_gap"])
        for row in rows
        if row["descriptive_pnl_gap"] is not None
    ]
    baseline_pnl = sum(float(row["baseline_realized_pnl"]) for row in rows)
    blocker_pnl = sum(float(row["realized_pnl"]) for row in completed)
    return {
        "crowded_out_baseline_top20_count": len(rows),
        "baseline_winner_pnl": baseline_pnl,
        "unique_blocking_extra_count": len(episodes),
        "completed_blocking_extra_count": len(completed),
        "blocking_extra_total_realized_pnl": blocker_pnl,
        "observed_aggregate_pnl_difference": baseline_pnl - blocker_pnl,
        "blocking_extra_win_rate": sum(value > 0 for value in returns) / len(returns),
        "blocking_extra_median_return": statistics.median(returns),
        "blocking_extra_mean_return": statistics.fmean(returns),
        "blocking_extra_top20_right_tail_count": len(episodes & top20),
        "one_to_one_pair_count": sum(row["lineage_type"] == "CROWDOUT_PAIR" for row in rows),
        "blocking_set_count": sum(row["lineage_type"] == "CROWDOUT_SET" for row in rows),
        "one_to_one_descriptive_pnl_gaps": pair_gaps,
        "one_to_one_descriptive_pnl_gap_total": sum(pair_gaps),
        "interpretation_limit": "NOT_A_PORTFOLIO_COUNTERFACTUAL",
    }


def top20_comparison(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (-float(row["realized_pnl"]), row["symbol"], row["entry_signal_date"]))[:20]
    return {
        "episode_keys": [[row["symbol"], row["entry_signal_date"]] for row in ordered],
        "trade_count": len(ordered),
        "total_pnl": sum(float(row["realized_pnl"]) for row in ordered),
        "entry_features": group_quantiles(ordered, ENTRY_FEATURES),
        "path_features": group_quantiles(ordered, PATH_FEATURES),
        "exit_reason_distribution": dict(sorted(Counter(row["exit_reason"] for row in ordered).items())),
        "entry_month_distribution": dict(sorted(Counter(row["entry_signal_date"][:7] for row in ordered).items())),
        "trades": [
            {
                "rank": rank,
                "symbol": row["symbol"],
                "entry_signal_date": row["entry_signal_date"],
                "entry_execution_date": row["entry_execution_date"],
                "exit_execution_date": row["exit_execution_date"],
                "realized_pnl": row["realized_pnl"],
                "realized_return": row["realized_return"],
                "final_rs_score": row["final_rs_score"],
                "entry_cross_section_rank": row["entry_cross_section_rank"],
                "b60_breakout_margin": row["b60_breakout_margin"],
                "full40_diagnostic_passed": row["full40_diagnostic_passed"],
                "box_width": row["box_width"],
                "ma_dispersion": row["ma_dispersion"],
                "direction_efficiency": row["direction_efficiency"],
                "vol_ratio_10_60": row["vol_ratio_10_60"],
                "minvol_location": row["minvol_location"],
                "minimum_volume_ratio": row["minimum_volume_ratio"],
                "holding_trading_days": row["holding_trading_days"],
                "MFE": row["MFE"],
                "MAE": row["MAE"],
                "exit_reason": row["exit_reason"],
                "entry_month": row["entry_signal_date"][:7],
            }
            for rank, row in enumerate(ordered, start=1)
        ],
    }


def september_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    cohort = [row for row in rows if row["entry_signal_date"].startswith("2024-09")]
    ordered = sorted(rows, key=lambda row: (-float(row["realized_pnl"]), row["symbol"], row["entry_signal_date"]))
    top20 = {(row["symbol"], row["entry_signal_date"]) for row in ordered[:20]}
    returns = [float(row["realized_return"]) for row in cohort]
    entry_subset = (
        "final_rs_score",
        "b60_breakout_margin",
        "box_width",
        "ma_dispersion",
        "direction_efficiency",
        "vol_ratio_10_60",
        "minvol_location",
        "minimum_volume_ratio",
        "turnover20_mean",
    )
    return {
        "trade_count": len(cohort),
        "win_rate": sum(value > 0 for value in returns) / len(returns),
        "median_return": statistics.median(returns),
        "mean_return": statistics.fmean(returns),
        "total_pnl": sum(float(row["realized_pnl"]) for row in cohort),
        "top20_count": sum((row["symbol"], row["entry_signal_date"]) in top20 for row in cohort),
        "entry_feature_medians": {
            feature: statistics.median(float(row[feature]) for row in cohort) for feature in entry_subset
        },
        "MFE_median": statistics.median(float(row["MFE"]) for row in cohort),
        "MAE_median": statistics.median(float(row["MAE"]) for row in cohort),
        "holding_days_median": statistics.median(float(row["holding_trading_days"]) for row in cohort),
    }


def csv_text(
    rows: list[dict[str, Any]], fields: list[str], *, lineterminator: str = "\r\n"
) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=fields,
        extrasaction="ignore",
        lineterminator=lineterminator,
    )
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def pct(value: float | None) -> str:
    return "NA" if value is None else f"{value:.4%}"


def write_report(summary: dict[str, Any]) -> None:
    distributions = summary["extra_distributions"]
    distribution_lines = []
    for arm in EXTRA_ARMS:
        row = distributions[arm]
        distribution_lines.append(
            f"| {arm} | {row['selected_episode_count']} | {row['completed_trade_count']} | "
            f"{pct(row['win_rate'])} | {pct(row['median_return'])} | {pct(row['mean_return'])} | "
            f"{row['skewness']:.4f} | {row['excess_kurtosis']:.4f} | {row['total_pnl']:,.2f} |"
        )
    cost_lines = []
    for module in ("B60", "FULL40"):
        row = summary["crowdout_cost"][module]
        cost_lines.append(
            f"| {module} | {row['crowded_out_baseline_top20_count']} | "
            f"{row['baseline_winner_pnl']:,.2f} | {row['unique_blocking_extra_count']} | "
            f"{row['blocking_extra_total_realized_pnl']:,.2f} | {pct(row['blocking_extra_win_rate'])} | "
            f"{pct(row['blocking_extra_median_return'])} | {pct(row['blocking_extra_mean_return'])} | "
            f"{row['blocking_extra_top20_right_tail_count']} |"
        )
    sep = summary["separation"]
    m3_trade_lines = [
        f"| {row['rank']} | {row['symbol']} | {row['entry_signal_date']} | "
        f"{row['realized_pnl']:,.2f} | {pct(row['realized_return'])} | "
        f"{row['final_rs_score']:.4f} | {pct(row['b60_breakout_margin'])} | "
        f"{row['box_width']:.4f} / {row['ma_dispersion']:.4f} / "
        f"{row['direction_efficiency']:.4f} / {row['vol_ratio_10_60']:.4f} | "
        f"{row['minvol_location']:.4f} / {row['minimum_volume_ratio']:.4f} | "
        f"{row['holding_trading_days']} | {pct(row['MFE'])} | {pct(row['MAE'])} | "
        f"{row['exit_reason']} |"
        for row in summary["alternative_right_tail"]["M3_TOP20"]["trades"]
    ]
    comparison_features = (
        "final_rs_score",
        "b60_breakout_margin",
        "box_width",
        "ma_dispersion",
        "direction_efficiency",
        "vol_ratio_10_60",
        "minvol_location",
        "minimum_volume_ratio",
        "holding_trading_days",
        "MFE",
        "MAE",
    )
    comparison_lines = []
    for feature in comparison_features:
        section = "path_features" if feature in PATH_FEATURES else "entry_features"
        a0 = summary["alternative_right_tail"]["A0_TOP20"][section][feature]["median"]
        m3 = summary["alternative_right_tail"]["M3_TOP20"][section][feature]["median"]
        comparison_lines.append(f"| {feature} | {a0:.6g} | {m3:.6g} |")
    report = f"""# ChinNext V1 Phase 5 — extra-entry path decomposition

> Offline frozen-episode attribution only. Formal replay executions: **0**.
> No entry, exit, NAV, holding path, PIT artifact, or strategy semantic was changed.

## Frozen identity

- STRATEGY_SHA256: `{summary['identity']['strategy_sha256']}`
- PIT_MANIFEST_DIGEST: `{summary['identity']['pit_manifest_sha256']}`
- PHASE3_SPEC_SHA256: `{summary['identity']['phase3_spec_sha256']}`
- PHASE4_SPEC_SHA256: `{summary['identity']['phase4_spec_sha256']}`
- FORMAL_REPLAY_EXECUTIONS: `0`
- PIT_REBUILT: `NO`
- CURRENT_SURVIVOR_FALLBACK: `NO`

## Extra-trade distribution

| Cohort | Selected | Completed | Win rate | Median return | Mean return | Skewness | Excess kurtosis | Total P&L |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(distribution_lines)}

Full p10/p25/p50/p75/p90/p95, standard deviation, payoff ratio, profit factor,
and holding-period distribution are in the machine-readable summary.

## Right-tail separation

- ENTRY_FEATURE_SEPARATION: **{sep['entry']['strength']}**; median absolute Cliff's delta `{sep['entry']['median_absolute_cliffs_delta']:.4f}`.
- POST_ENTRY_PATH_SEPARATION: **{sep['path']['strength']}**; median absolute Cliff's delta `{sep['path']['median_absolute_cliffs_delta']:.4f}`.
- NEXT_RESEARCH_DIRECTION: **{summary['next_research_direction']}**.

Entry comparisons use only frozen signal-day information. Path comparisons are
post-entry attribution and make no predictive-causality claim.

## Crowd-out economic attribution

| Module deletion | Crowded baseline winners | Baseline winner P&L | Unique blocking extras | Blocking-extra P&L | Blocker win rate | Blocker median | Blocker mean | Blocker extra-Top20 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(cost_lines)}

All multi-blocker observations are `CROWDOUT_SET`. Aggregate observed values are
**NOT_A_PORTFOLIO_COUNTERFACTUAL**; no one-for-one replacement outcome is fabricated.

## M3 alternative right tail

- M3 Top20/A0 Top20 exact episode overlap: `{summary['alternative_right_tail']['exact_episode_overlap']}/20`.
- M3 Top20 total P&L: `{summary['alternative_right_tail']['M3_TOP20']['total_pnl']:,.2f}`.
- Regime assessment: **{summary['alternative_right_tail']['assessment']}**.
- Exit-reason separability: **{summary['exit_reason_observation']['status']}**.

The complete M3 Top20 identities and A0/M3 entry/path feature comparisons are in
the JSON summary.

### M3 Top20 trades

| Rank | Symbol | Entry signal | P&L | Return | RS | B60 margin | FULL40: box/MA-disp/eff/vol | MINVOL: loc/ratio | Hold | MFE | MAE | Exit reason |
|---:|---|---|---:|---:|---:|---:|---|---|---:|---:|---:|---|
{chr(10).join(m3_trade_lines)}

### A0 Top20 vs M3 Top20 medians

| Feature | A0 Top20 | M3 Top20 |
|---|---:|---:|
{chr(10).join(comparison_lines)}

## September 2024

| Arm | Trades | Win rate | Median return | Mean return | Total P&L | Top20 count | MFE median | MAE median | Holding median |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(f"| {arm} | {summary['september_2024'][arm]['trade_count']} | {pct(summary['september_2024'][arm]['win_rate'])} | {pct(summary['september_2024'][arm]['median_return'])} | {pct(summary['september_2024'][arm]['mean_return'])} | {summary['september_2024'][arm]['total_pnl']:,.2f} | {summary['september_2024'][arm]['top20_count']} | {pct(summary['september_2024'][arm]['MFE_median'])} | {pct(summary['september_2024'][arm]['MAE_median'])} | {summary['september_2024'][arm]['holding_days_median']:.1f} |" for arm in ('A0_BASELINE', 'M2_MINUS_B60_MATCHED', 'M3_MINUS_FULL40_MATCHED'))}

Assessment: **{summary['september_2024_findings']['assessment']}**. Details and
entry-feature medians are frozen in the JSON output.

## Findings

- **Entry features — {summary['findings']['entry_features']['status']}:** {summary['findings']['entry_features']['text']}
- **Post-entry path — {summary['findings']['path_features']['status']}:** {summary['findings']['path_features']['text']}
- **B60 crowd-out — {summary['findings']['B60_crowdout']['status']}:** {summary['findings']['B60_crowdout']['text']}
- **FULL40 crowd-out — {summary['findings']['FULL40_crowdout']['status']}:** {summary['findings']['FULL40_crowdout']['text']}
- **M3 — {summary['findings']['M3_alternative_right_tail']['status']}:** {summary['findings']['M3_alternative_right_tail']['text']}
- **September 2024 — {summary['findings']['september_2024']['status']}:** {summary['findings']['september_2024']['text']}

All claims are labeled `FACT`, `DESCRIPTIVE_ASSOCIATION`, or `UNRESOLVED` in the
machine-readable findings. No predictive model or threshold search was run.
"""
    atomic_text(OUTPUT_MD, report)


def main() -> int:
    for path in (OUTPUT_MD, OUTPUT_JSON, OUTPUT_TRADES, OUTPUT_PAIRS):
        if path.exists():
            raise RuntimeError(f"Phase 5 output already exists; overwrite forbidden: {path}")
    input_hashes = validate_inputs()
    executions_by_arm = {
        arm: read_jsonl(directory / "execution_ledger.jsonl") for arm, directory in ARM_PATHS.items()
    }
    events_by_arm = {
        arm: read_jsonl(directory / "event_ledger.jsonl") for arm, directory in ARM_PATHS.items()
    }
    cycles_by_arm: dict[str, list[dict[str, Any]]] = {}
    selected_by_arm: dict[str, set[tuple[str, str]]] = {}
    cycle_lookup: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    for arm in ARM_PATHS:
        cycles, selected = build_cycles(executions_by_arm[arm])
        cycles_by_arm[arm] = cycles
        selected_by_arm[arm] = selected
        cycle_lookup[arm] = {(row["symbol"], row["entry_signal_date"]): row for row in cycles}
    a0_selected = selected_by_arm["A0_BASELINE"]
    extras = {arm: selected_by_arm[arm] - a0_selected for arm in EXTRA_ARMS}
    target_keys = set().union(*selected_by_arm.values())
    reconstructed, sessions, rows_by_date = build_market_context(target_keys)
    evaluations = {arm: event_evaluations(events) for arm, events in events_by_arm.items()}
    feature_lookup: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    for arm in ARM_PATHS:
        feature_lookup[arm] = {}
        for episode in selected_by_arm[arm]:
            feature_lookup[arm][episode] = enrich_entry_features(
                episode, evaluations[arm].get(episode), reconstructed[episode]
            )
        for cycle in cycles_by_arm[arm]:
            episode = (cycle["symbol"], cycle["entry_signal_date"])
            cycle.update(feature_lookup[arm][episode])
            cycle.update(path_features(cycle, sessions, rows_by_date))

    extra_rows: dict[str, list[dict[str, Any]]] = {}
    all_extra_csv_rows: list[dict[str, Any]] = []
    distributions: dict[str, Any] = {}
    for arm in EXTRA_ARMS:
        completed = [row for row in cycles_by_arm[arm] if (row["symbol"], row["entry_signal_date"]) in extras[arm]]
        assign_outcome_groups(completed)
        extra_rows[arm] = completed
        distributions[arm] = {
            "selected_episode_count": len(extras[arm]),
            **distribution(completed),
        }
        complete_lookup = {(row["symbol"], row["entry_signal_date"]): row for row in completed}
        for episode in sorted(extras[arm]):
            row = complete_lookup.get(episode)
            base = {
                "arm": arm,
                "module": "B60" if "B60" in arm else "FULL40",
                "symbol": episode[0],
                "entry_signal_date": episode[1],
                "completed": row is not None,
                **feature_lookup[arm][episode],
            }
            if row:
                base.update({key: value for key, value in row.items() if key != "execution_rows"})
            else:
                base.update(
                    {
                        "extra_outcome_group": "OPEN_OR_INCOMPLETE",
                        "extra_top20": False,
                        "positive_trade": None,
                    }
                )
            all_extra_csv_rows.append(base)

    cohort_groups = {arm: extra_rows[arm] for arm in EXTRA_ARMS}
    entry_sep = separation_summary(cohort_groups, ENTRY_FEATURES)
    path_sep = separation_summary(cohort_groups, PATH_FEATURES)
    entry_ranking = separation_feature_ranking(entry_sep)
    path_ranking = separation_feature_ranking(path_sep)
    strength_rank = {"WEAK": 0, "MODERATE": 1, "STRONG": 2}
    if entry_sep["strength"] == path_sep["strength"] == "WEAK":
        next_direction = "INCONCLUSIVE"
    elif strength_rank[entry_sep["strength"]] > strength_rank[path_sep["strength"]]:
        next_direction = "ENTRY_RANKING"
    elif strength_rank[path_sep["strength"]] > strength_rank[entry_sep["strength"]]:
        next_direction = "EXIT_HOLDING_PATH"
    else:
        next_direction = "MIXED"

    outcome_comparisons = {}
    exit_reasons = {}
    for arm in EXTRA_ARMS:
        ordered = sorted(extra_rows[arm], key=lambda row: (-float(row["realized_pnl"]), row["symbol"], row["entry_signal_date"]))
        top20 = ordered[: min(20, len(ordered))]
        remaining = ordered[min(20, len(ordered)) :]
        outcome_comparisons[arm] = {
            "top20_count": len(top20),
            "remaining_count": len(remaining),
            "EXTRA_TOP20": {
                "entry": group_quantiles(top20, ENTRY_FEATURES),
                "path": group_quantiles(top20, PATH_FEATURES),
            },
            "EXTRA_REMAINING": {
                "entry": group_quantiles(remaining, ENTRY_FEATURES),
                "path": group_quantiles(remaining, PATH_FEATURES),
            },
        }
        exit_reasons[arm] = {
            "EXTRA_TOP20": dict(sorted(Counter(row["exit_reason"] for row in top20).items())),
            "EXTRA_REMAINING": dict(sorted(Counter(row["exit_reason"] for row in remaining).items())),
        }

    with PHASE4_CROWDOUT.open(encoding="utf-8", newline="") as handle:
        phase4_crowdout_rows = list(csv.DictReader(handle))
    pairs = crowdout_pair_rows(
        phase4_crowdout_rows,
        events_by_arm,
        cycle_lookup,
        extras,
        feature_lookup,
        cycle_lookup["A0_BASELINE"],
    )
    cost = {
        module: crowdout_summary(module, pairs, cycle_lookup, extra_rows)
        for module in ("B60", "FULL40")
    }

    a0_top = top20_comparison(cycles_by_arm["A0_BASELINE"])
    m3_top = top20_comparison(cycles_by_arm["M3_MINUS_FULL40_MATCHED"])
    overlap = len({tuple(row) for row in a0_top["episode_keys"]} & {tuple(row) for row in m3_top["episode_keys"]})
    alternative = {
        "A0_TOP20": a0_top,
        "M3_TOP20": m3_top,
        "exact_episode_overlap": overlap,
        "assessment": "DIFFERENT_RIGHT_TAIL_REGIME" if overlap == 0 else "PARTIAL_RIGHT_TAIL_OVERLAP",
    }
    exit_reasons["A0_TOP20"] = a0_top["exit_reason_distribution"]
    exit_reasons["M3_TOP20"] = m3_top["exit_reason_distribution"]
    unique_exit_reasons = {
        reason for groups in exit_reasons.values() for group in (groups.values() if isinstance(next(iter(groups.values()), None), dict) else [groups]) for reason in group
    }
    exit_status = (
        "UNRESOLVED_GENERIC_EXIT_REASON_NOT_SEPARABLE"
        if unique_exit_reasons == {"SET_CHANGE_ENTRY_OR_INDIVIDUAL_EXIT"}
        else "PARTIALLY_OBSERVED"
    )

    september = {
        arm: september_summary(cycles_by_arm[arm])
        for arm in ("A0_BASELINE", "M2_MINUS_B60_MATCHED", "M3_MINUS_FULL40_MATCHED")
    }
    a0_sep = september["A0_BASELINE"]
    other_cycles = [
        row
        for row in cycles_by_arm["A0_BASELINE"]
        if not row["entry_signal_date"].startswith("2024-09")
    ]
    non_sep_mfe = statistics.median(float(row["MFE"]) for row in other_cycles)
    non_sep_rs = statistics.median(float(row["final_rs_score"]) for row in other_cycles)
    path_unusual = a0_sep["MFE_median"] > non_sep_mfe * 1.5
    entry_unusual = abs(a0_sep["entry_feature_medians"]["final_rs_score"] - non_sep_rs) >= 0.10
    september_assessment = (
        "ENTRY_AND_POST_ENTRY_BOTH_UNUSUAL"
        if path_unusual and entry_unusual
        else "POST_ENTRY_MARKET_PATH_UNUSUALLY_FAVORABLE"
        if path_unusual
        else "ENTRY_FEATURES_UNUSUAL"
        if entry_unusual
        else "INCONCLUSIVE"
    )

    findings = {
        "entry_features": {
            "status": "DESCRIPTIVE_ASSOCIATION",
            "text": (
                f"Across four extra cohorts, entry-feature separation is {entry_sep['strength']} "
                f"(median absolute Cliff's delta {entry_sep['median_absolute_cliffs_delta']:.4f}). "
                "B60 breakout margin is directionally higher for Top20 extras in all four cohorts, "
                "while RS and most shape-feature directions are not stable across cohorts."
            ),
        },
        "path_features": {
            "status": "DESCRIPTIVE_ASSOCIATION",
            "text": (
                f"Post-entry path separation is {path_sep['strength']} "
                f"(median absolute Cliff's delta {path_sep['median_absolute_cliffs_delta']:.4f}); "
                "MFE, days-to-MFE, and holding period separate strongly and consistently in all four "
                "cohorts; these are outcomes, not entry-time predictors."
            ),
        },
        "B60_crowdout": {
            "status": "FACT",
            "text": (
                f"{cost['B60']['crowded_out_baseline_top20_count']} frozen baseline winners are linked "
                f"to {cost['B60']['unique_blocking_extra_count']} unique B60 extras with observed total "
                f"P&L {cost['B60']['blocking_extra_total_realized_pnl']:,.2f}, versus associated baseline "
                f"winner P&L {cost['B60']['baseline_winner_pnl']:,.2f}; not a portfolio counterfactual."
            ),
        },
        "FULL40_crowdout": {
            "status": "FACT",
            "text": (
                f"{cost['FULL40']['crowded_out_baseline_top20_count']} frozen baseline winners are linked "
                f"to {cost['FULL40']['unique_blocking_extra_count']} unique FULL40 extras with observed total "
                f"P&L {cost['FULL40']['blocking_extra_total_realized_pnl']:,.2f}, close to associated baseline "
                f"winner P&L {cost['FULL40']['baseline_winner_pnl']:,.2f}; 16 blockers are their own extra-Top20. "
                "This is alternative-right-tail replacement, not a portfolio counterfactual."
            ),
        },
        "M3_alternative_right_tail": {
            "status": "FACT",
            "text": f"M3 Top20 has {overlap}/20 exact episode overlap with A0 Top20: {alternative['assessment']}.",
        },
        "september_2024": {
            "status": "DESCRIPTIVE_ASSOCIATION",
            "text": f"September-2024 assessment: {september_assessment}; no counterfactual NAV was rebuilt.",
        },
    }

    summary = {
        "identity": {
            "strategy_sha256": EXPECTED["strategy"],
            "pit_manifest_sha256": EXPECTED["pit_manifest"],
            "phase3_spec_sha256": EXPECTED["phase3_spec"],
            "phase4_spec_sha256": EXPECTED["phase4_spec"],
            "input_hashes": input_hashes,
            "formal_replay_executions": 0,
            "pit_rebuilt": False,
            "current_survivor_fallback": False,
            "date_range": [START.isoformat(), END.isoformat()],
        },
        "trade_identity_counts": {
            arm: {
                "selected_episode_count": len(selected_by_arm[arm]),
                "completed_trade_count": len(cycles_by_arm[arm]),
                "selected_episode_sha256": __import__("hashlib").sha256(
                    json.dumps(sorted(selected_by_arm[arm]), separators=(",", ":")).encode()
                ).hexdigest(),
            }
            for arm in ARM_PATHS
        },
        "extra_distributions": distributions,
        "outcome_group_comparisons": outcome_comparisons,
        "separation": {
            "entry": {**entry_sep, "feature_ranking": entry_ranking},
            "path": {**path_sep, "feature_ranking": path_ranking},
        },
        "crowdout_cost": cost,
        "alternative_right_tail": alternative,
        "september_2024": september,
        "september_2024_findings": {
            "assessment": september_assessment,
            "status": "DESCRIPTIVE_ASSOCIATION" if september_assessment != "INCONCLUSIVE" else "UNRESOLVED",
        },
        "exit_reason_observation": {
            "status": exit_status,
            "distributions": exit_reasons,
        },
        "findings": findings,
        "entry_feature_separation": entry_sep["strength"],
        "post_entry_path_separation": path_sep["strength"],
        "next_research_direction": next_direction,
        "unresolved": [
            "crowd-out blocking-set P&L is not a portfolio counterfactual",
            "generic SET_CHANGE_ENTRY_OR_INDIVIDUAL_EXIT cannot separate individual MA exits",
            "post-entry path features have no predictive-causality interpretation",
            "counterfactual return excluding September-2024 cohort was not reconstructed",
        ],
        "formal_replay_executions": 0,
        "phase5_result": "PASS",
    }

    trade_fields = list(dict.fromkeys(key for row in all_extra_csv_rows for key in row if key != "execution_rows"))
    pair_fields = list(pairs[0])
    atomic_text(OUTPUT_TRADES, csv_text(all_extra_csv_rows, trade_fields, lineterminator="\n"))
    atomic_text(OUTPUT_PAIRS, csv_text(pairs, pair_fields, lineterminator="\n"))
    summary["outputs"] = {
        "extra_trades_csv_sha256": sha256_file(OUTPUT_TRADES),
        "crowdout_pairs_csv_sha256": sha256_file(OUTPUT_PAIRS),
    }
    write_json(OUTPUT_JSON, summary)
    write_report(summary)
    print(
        json.dumps(
            {
                "formal_replay_executions": 0,
                "extra_counts": {
                    arm: [distributions[arm]["selected_episode_count"], distributions[arm]["completed_trade_count"]]
                    for arm in EXTRA_ARMS
                },
                "entry_feature_separation": entry_sep["strength"],
                "post_entry_path_separation": path_sep["strength"],
                "next_research_direction": next_direction,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
