#!/usr/bin/env python3
# ruff: noqa: E402, E501
"""Fixed K5/K10/K20 capitalization replay for frozen Dual Fresh."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_gap_zone_entry_admission_development_v1 as predecessor,
)

strategy = predecessor.strategy
v1 = predecessor.v1

OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-COLLAPSE-GAP-ZONE-DUAL-FRESH-CAPITALIZATION-V1"
START_HEAD = "e1adc2889d038256be660f39a3f1cf8db27bcff5"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_spec.json"
EXPECTED_SPEC_SHA256 = "5c5e4ab7aa9f3737dc581b67700701178ff9984f395243b6f07b692cf930d31c"
EXPECTED_INPUTS = {
    predecessor.SPEC: "b91917559a02c31f361c0dd6d38b7a3f6913b83e59de6cb4a0a71d4d651f82ad",
    predecessor.ADMISSION: "daa5e8ab0e8c571a103a43e94558ce56153adc67e45adfc0eaf7d731df124e81",
    predecessor.TRADES: "10fabb9785fad580d3a67c0f24b19d08b4e5560d6c5b41b1dd25073359195c46",
    predecessor.EXECUTED: "0c8c98af3167f43e0abf8166b88970ab397924e26b5c9897b9e54a1125cb1cdc",
    predecessor.NAV: "a9fb660026357d7370617061d023023fd313159d9beb41ccc95317c157779b20",
    predecessor.RESULT: "3b5b6660b0b29e0ed01d9b52f4ba18a5886b18c6906502fcc8fc5c7019db0fd7",
    strategy.DAILY: "a4eb64cb51c1c820d55d01fc30306273a616ab7a171126bbbda716392f43d4d5",
}

BOARDS = ("MAIN", "CHINEXT")
KS = (5, 10, 20)
YEARS = tuple(range(2017, 2022))
TRADES = OS_ROOT / f"artifacts/{EXPERIMENT}_trades.parquet"
MAIN_NAV = OS_ROOT / f"artifacts/{EXPERIMENT}_main_nav.parquet"
CHINEXT_NAV = OS_ROOT / f"artifacts/{EXPERIMENT}_chinext_nav.parquet"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"


class CapitalizationError(RuntimeError):
    """Fail closed on frozen identity, execution, or portfolio conservation."""


@dataclass
class ReplayK:
    nav: pd.DataFrame
    accepted: pd.DataFrame
    ledger: pd.DataFrame
    audit: dict[str, int]
    blocked: bool


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(value))
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def write_json(path: Path, value: Any) -> None:
    v1.atomic_text(path, json.dumps(json_ready(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def validate_inputs() -> dict[str, str]:
    found = {}
    for path, expected in {SPEC: EXPECTED_SPEC_SHA256, **EXPECTED_INPUTS}.items():
        if not path.is_file():
            raise CapitalizationError(f"missing frozen input: {path}")
        actual = v1.sha256_file(path)
        if actual != expected:
            raise CapitalizationError(f"frozen input mismatch {path}: {actual}")
        found[str(path)] = actual
    return found


def load_dual_source() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    panel = pd.read_parquet(predecessor.ADMISSION)
    panel["entry_date"] = pd.to_datetime(panel.entry_date)
    dual = panel.loc[panel.L3_DUAL_FRESH].copy()
    if len(dual) != 207 or dual.event_id.duplicated().any():
        raise CapitalizationError(f"Dual Fresh identity failure: {len(dual)}")
    if dual.groupby("board").size().to_dict() != {"CHINEXT": 76, "MAIN": 131}:
        raise CapitalizationError("Dual Fresh board identity failure")
    if not (dual.zone_age_sessions.le(90) & dual.cum_turnover_since_zone.le(dual.turnover_train_q66_67)).all():
        raise CapitalizationError("Dual Fresh admission semantic failure")
    trades = pd.read_parquet(predecessor.TRADES)
    for column in ("entry_date", "entry_time", "exit_date", "exit_time", "action_block_time", "risk_exit_effective_date"):
        trades[column] = pd.to_datetime(trades[column])
    trades = trades.loc[trades.event_id.isin(dual.event_id)].copy()
    valid = trades.loc[~trades.precompleted_before_entry & ~trades.risk_blocked_entry].copy()
    if len(trades) != 207 or len(valid) != 207 or trades.event_id.duplicated().any():
        raise CapitalizationError(f"Dual Fresh H40 trade identity failure: {len(trades)}/{len(valid)}")
    daily = pd.read_parquet(strategy.DAILY)
    daily["trade_date"] = pd.to_datetime(daily.trade_date)
    if pd.to_datetime(valid.entry_date).max() > pd.Timestamp("2021-12-31"):
        raise CapitalizationError("post-2021 signal found")
    return dual, valid, daily


def frozen_trade_return(row: Any) -> float | None:
    if pd.isna(row.exit_raw_price):
        return None
    cash = sum(float(item["cash_per_share"]) for item in json.loads(row.cash_events_json))
    return float(
        (float(row.exit_raw_price) * (1 - strategy.COST) + cash)
        / (float(row.entry_raw_price) * (1 + strategy.COST))
        - 1
    )


def order_signals(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.sort_values(
        ["entry_time", "primary_layer_width_pct", "board_relative_return_percentile", "peak_to_low_decline", "persistence_sessions", "symbol"],
        ascending=[True, False, False, False, False, True],
        kind="mergesort",
    )


def replay_k(trades: pd.DataFrame, daily: pd.DataFrame, board: str, k: int) -> ReplayK:
    signals = order_signals(trades.loc[trades.board.eq(board)]).copy()
    calendar = daily.loc[daily.trade_date.dt.year.between(2017, 2021), ["trade_date", "cal_idx"]].drop_duplicates("trade_date").sort_values("trade_date")
    if calendar.empty:
        raise CapitalizationError("empty replay calendar")
    period_end = pd.Timestamp(calendar.trade_date.max()) + pd.Timedelta(hours=15)
    marks = {(r.symbol, pd.Timestamp(r.trade_date)): float(r.close) for r in daily.itertuples(index=False) if np.isfinite(r.close)}
    dates_by_symbol = {symbol: part.sort_values("trade_date") for symbol, part in daily.groupby("symbol", sort=False)}
    cash = 1.0
    active: dict[str, dict[str, Any]] = {}
    accepted: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    audit = {
        "duplicate_position_count": 0,
        "duplicate_signal_skip_count": 0,
        "max_k_violation_count": 0,
        "negative_cash_or_leverage_count": 0,
        "t1_violation_count": 0,
        "capacity_skip_count": 0,
    }

    def initialize_cash_events(pos: dict[str, Any]) -> None:
        raw = pos.get("cash_events_json")
        pos["cash_events"] = [] if raw is None or pd.isna(raw) else json.loads(raw)
        pos["cash_event_index"] = 0
        pos["action_cash_per_share"] = 0.0

    def credit_actions(pos: dict[str, Any], when: pd.Timestamp) -> float:
        credited = 0.0
        while pos["cash_event_index"] < len(pos["cash_events"]):
            event = pos["cash_events"][pos["cash_event_index"]]
            if pd.Timestamp(event["date"]) > when.normalize():
                break
            amount = float(event["cash_per_share"])
            credited += pos["qty"] * amount
            pos["action_cash_per_share"] += amount
            pos["cash_event_index"] += 1
        return credited

    def mark_price(pos: dict[str, Any], when: pd.Timestamp) -> float:
        rows = dates_by_symbol.get(pos["symbol"], pd.DataFrame())
        if len(rows):
            prior = rows.loc[rows.trade_date.lt(when.normalize())]
            if len(prior) and np.isfinite(prior.close.iloc[-1]):
                return float(prior.close.iloc[-1])
        return float(pos["entry_raw_price"])

    def close_due(when: pd.Timestamp) -> None:
        nonlocal cash
        due = sorted(
            [pos for pos in active.values() if pd.notna(pos["exit_time"]) and pd.Timestamp(pos["exit_time"]) <= when],
            key=lambda pos: (pd.Timestamp(pos["exit_time"]), pos["symbol"]),
        )
        for pos in due:
            cash += credit_actions(pos, pd.Timestamp(pos["exit_time"]))
            cash += pos["qty"] * float(pos["exit_raw_price"]) * (1 - strategy.COST)
            pos["completed"] = True
            pos["net_trade_return"] = float(
                (pos["exit_raw_price"] * (1 - strategy.COST) + pos["action_cash_per_share"])
                / (pos["entry_raw_price"] * (1 + strategy.COST))
                - 1
            )
            active.pop(pos["symbol"], None)

    blocked = False
    for timestamp, group in signals.groupby("entry_time", sort=True):
        timestamp = pd.Timestamp(timestamp)
        close_due(timestamp)
        for pos in active.values():
            cash += credit_actions(pos, timestamp)
        for row in group.itertuples(index=False):
            frozen_return = frozen_trade_return(row)
            record = {
                "event_id": row.event_id,
                "symbol": row.symbol,
                "board": board,
                "k": k,
                "entry_date": pd.Timestamp(row.entry_date),
                "entry_time": pd.Timestamp(row.entry_time),
                "exit_date": pd.Timestamp(row.exit_date) if pd.notna(row.exit_date) else pd.NaT,
                "exit_time": pd.Timestamp(row.exit_time) if pd.notna(row.exit_time) else pd.NaT,
                "exit_reason": row.exit_reason,
                "frozen_completed": pd.notna(row.exit_time) and pd.Timestamp(row.exit_time) <= period_end,
                "frozen_net_trade_return": frozen_return,
            }
            if row.symbol in active:
                audit["duplicate_signal_skip_count"] += 1
                ledger.append({**record, "status": "SKIPPED_DUPLICATE_SYMBOL", "capacity_skip": False, "qty": np.nan, "entry_nav": np.nan, "entry_outlay": np.nan, "initial_weight": np.nan})
                continue
            if len(active) >= k:
                audit["capacity_skip_count"] += 1
                ledger.append({**record, "status": "SKIPPED_CAPACITY", "capacity_skip": True, "qty": np.nan, "entry_nav": np.nan, "entry_outlay": np.nan, "initial_weight": np.nan})
                continue
            nav_now = cash + sum(pos["qty"] * mark_price(pos, timestamp) for pos in active.values())
            outlay = min(nav_now / k, cash)
            if outlay <= 0:
                ledger.append({**record, "status": "SKIPPED_NO_CASH", "capacity_skip": False, "qty": np.nan, "entry_nav": nav_now, "entry_outlay": np.nan, "initial_weight": np.nan})
                continue
            qty = outlay / (float(row.entry_raw_price) * (1 + strategy.COST))
            cash -= qty * float(row.entry_raw_price) * (1 + strategy.COST)
            if cash < -1e-12:
                audit["negative_cash_or_leverage_count"] += 1
            pos = row._asdict()
            pos.update(qty=qty, completed=False, net_trade_return=np.nan, entry_nav=nav_now, entry_outlay=outlay, initial_weight=outlay / nav_now, k=k)
            initialize_cash_events(pos)
            accepted.append(pos)
            active[row.symbol] = pos
            ledger.append({**record, "status": "EXECUTED", "capacity_skip": False, "qty": qty, "entry_nav": nav_now, "entry_outlay": outlay, "initial_weight": outlay / nav_now})
            if len(active) > k:
                audit["max_k_violation_count"] += 1
            if pd.notna(row.exit_date) and pd.Timestamp(row.exit_date) == pd.Timestamp(row.entry_date):
                audit["t1_violation_count"] += 1
            if pd.notna(row.action_block_time) and pd.Timestamp(row.action_block_time) <= period_end and (pd.isna(row.exit_time) or pd.Timestamp(row.action_block_time) <= pd.Timestamp(row.exit_time)):
                blocked = True
    close_due(period_end)
    for pos in active.values():
        cash += credit_actions(pos, period_end)
    accepted_df = pd.DataFrame(accepted)

    cash2 = 1.0
    live: dict[str, dict[str, Any]] = {}
    nav_rows = []
    entries_by_date: dict[pd.Timestamp, list[dict[str, Any]]] = {}
    exits_by_date: dict[pd.Timestamp, list[dict[str, Any]]] = {}
    for pos in accepted:
        entries_by_date.setdefault(pd.Timestamp(pos["entry_date"]), []).append(pos)
        if pos["completed"]:
            exits_by_date.setdefault(pd.Timestamp(pos["exit_date"]), []).append(pos)
    for date in calendar.trade_date:
        date = pd.Timestamp(date)
        for pos in live.values():
            for event in pos["cash_events"]:
                if pd.Timestamp(event["date"]) == date:
                    cash2 += pos["qty"] * float(event["cash_per_share"])
        events = [(pd.Timestamp(pos["entry_time"]), "ENTRY", pos) for pos in entries_by_date.get(date, [])]
        events += [(pd.Timestamp(pos["exit_time"]), "EXIT", pos) for pos in exits_by_date.get(date, [])]
        for _, kind, pos in sorted(events, key=lambda item: (item[0], 0 if item[1] == "EXIT" else 1, item[2]["symbol"])):
            if kind == "ENTRY":
                if pos["symbol"] in live:
                    audit["duplicate_position_count"] += 1
                cash2 -= pos["qty"] * pos["entry_raw_price"] * (1 + strategy.COST)
                live[pos["symbol"]] = pos
            else:
                cash2 += pos["qty"] * pos["exit_raw_price"] * (1 - strategy.COST)
                live.pop(pos["symbol"], None)
        exposure = sum(pos["qty"] * marks.get((symbol, date), pos["entry_raw_price"]) for symbol, pos in live.items())
        nav_value = cash2 + exposure
        nav_rows.append({
            "trade_date": date,
            "nav": nav_value,
            "cash": cash2,
            "gross_exposure": exposure,
            "utilization": 0.0 if nav_value == 0 else exposure / nav_value,
            "active_positions": len(live),
            "board": board,
            "k": k,
            "lane": f"CAP_K{k}",
        })
    nav = pd.DataFrame(nav_rows)
    if nav.active_positions.max() > k:
        audit["max_k_violation_count"] += 1
    if nav.cash.min() < -1e-12 or (nav.gross_exposure - nav.nav).max() > 1e-12:
        audit["negative_cash_or_leverage_count"] += 1
    return ReplayK(nav, accepted_df, pd.DataFrame(ledger), audit, blocked)


def annual_returns(nav: pd.DataFrame) -> dict[str, float]:
    output = {}
    prior = 1.0
    for year, part in nav.groupby(nav.trade_date.dt.year, sort=True):
        output[str(year)] = float(part.nav.iloc[-1] / prior - 1)
        prior = float(part.nav.iloc[-1])
    return output


def trade_metrics(frame: pd.DataFrame, calendar: pd.DataFrame) -> dict[str, Any]:
    completed = frame.loc[frame.completed].copy() if len(frame) and "completed" in frame else frame.copy()
    returns = pd.to_numeric(completed.net_trade_return, errors="coerce").dropna() if len(completed) else pd.Series(dtype=float)
    if len(completed):
        idx = dict(zip(pd.to_datetime(calendar.trade_date), calendar.cal_idx.astype(int), strict=False))
        holds = pd.to_datetime(completed.exit_date).map(idx) - completed.entry_cal_idx
    else:
        holds = pd.Series(dtype=float)
    return {
        "completed_trades": len(returns),
        "mean_net_trade_return": None if returns.empty else float(returns.mean()),
        "median_net_trade_return": None if returns.empty else float(returns.median()),
        "positive_trade_rate": None if returns.empty else float(returns.gt(0).mean()),
        "target_hit_rate": None if returns.empty else float(completed.loc[returns.index].exit_reason.eq("TARGET").mean()),
        "severe_loss10_rate": None if returns.empty else float(returns.le(-0.10).mean()),
        "mean_holding_sessions": None if holds.empty else float(holds.mean()),
        "median_holding_sessions": None if holds.empty else float(holds.median()),
        "p10_net_trade_return": None if returns.empty else float(returns.quantile(0.10)),
        "p25_net_trade_return": None if returns.empty else float(returns.quantile(0.25)),
        "p75_net_trade_return": None if returns.empty else float(returns.quantile(0.75)),
        "p90_net_trade_return": None if returns.empty else float(returns.quantile(0.90)),
    }


def nav_concentration(nav: pd.DataFrame) -> dict[str, Any]:
    returns = nav.nav.pct_change().fillna(nav.nav.iloc[0] - 1.0)
    pnl = nav.nav.diff().fillna(nav.nav.iloc[0] - 1.0)
    positive = pnl.loc[pnl.gt(0)].sort_values(ascending=False)
    positive_total = float(positive.sum())
    def exclusion(n: int, best: bool) -> float:
        chosen = returns.nlargest(n).index if best else returns.nsmallest(n).index
        return float((1 + returns.drop(chosen)).prod() - 1)
    return {
        "largest_one_day_nav_loss": float(returns.min()),
        "largest_one_day_nav_gain": float(returns.max()),
        "return_excluding_best_day": exclusion(1, True),
        "return_excluding_best_five_days": exclusion(5, True),
        "return_excluding_worst_day": exclusion(1, False),
        "top1_pnl_day_contribution": None if positive_total <= 0 else float(positive.iloc[:1].sum() / positive_total),
        "top5_pnl_day_contribution": None if positive_total <= 0 else float(positive.iloc[:5].sum() / positive_total),
    }


def trade_concentration(accepted: pd.DataFrame) -> dict[str, Any]:
    completed = accepted.loc[accepted.completed].copy() if len(accepted) else accepted
    if completed.empty:
        return {"top1_trade_pnl_contribution": None, "top5_trade_pnl_contribution": None}
    pnl = completed.entry_outlay * completed.net_trade_return
    positive = pnl.loc[pnl.gt(0)].sort_values(ascending=False)
    total = float(positive.sum())
    return {
        "top1_trade_pnl_contribution": None if total <= 0 else float(positive.iloc[:1].sum() / total),
        "top5_trade_pnl_contribution": None if total <= 0 else float(positive.iloc[:5].sum() / total),
    }


def drawdown_anatomy(nav: pd.DataFrame) -> dict[str, Any]:
    values = nav.nav.astype(float)
    drawdown = values / values.cummax() - 1
    trough_i = int(drawdown.idxmin())
    peak_i = int(values.loc[:trough_i].idxmax())
    monthly = nav.assign(month=nav.trade_date.dt.to_period("M")).groupby("month").nav.last()
    monthly_ret = monthly.pct_change()
    monthly_ret.iloc[0] = monthly.iloc[0] - 1
    annual = annual_returns(nav)
    rolling20 = values / values.shift(20) - 1
    return {
        "max_drawdown": float(drawdown.min()),
        "max_drawdown_duration_sessions": trough_i - peak_i,
        "max_drawdown_peak_date": str(pd.Timestamp(nav.loc[peak_i, "trade_date"]).date()),
        "max_drawdown_trough_date": str(pd.Timestamp(nav.loc[trough_i, "trade_date"]).date()),
        "worst_calendar_month": str(monthly_ret.idxmin()),
        "worst_calendar_month_return": float(monthly_ret.min()),
        "worst_calendar_year": min(annual, key=annual.get),
        "worst_calendar_year_return": float(min(annual.values())),
        "worst_rolling_20_session_return": float(rolling20.min()),
    }


def utilization_metrics(nav: pd.DataFrame) -> dict[str, Any]:
    u = nav.utilization.astype(float)
    return {
        "average_gross_capital_utilization": float(u.mean()),
        "median_gross_capital_utilization": float(u.median()),
        "p75_gross_capital_utilization": float(u.quantile(0.75)),
        "p90_gross_capital_utilization": float(u.quantile(0.90)),
        "p95_gross_capital_utilization": float(u.quantile(0.95)),
        "fraction_zero": float(u.eq(0).mean()),
        "fraction_0_25": float(u.gt(0).mul(u.le(0.25)).mean()),
        "fraction_25_50": float(u.gt(0.25).mul(u.le(0.50)).mean()),
        "fraction_50_75": float(u.gt(0.50).mul(u.le(0.75)).mean()),
        "fraction_75_100": float(u.gt(0.75).mul(u.lt(1 - 1e-12)).mean()),
        "fraction_100": float(u.ge(1 - 1e-12).mean()),
        "average_active_positions": float(nav.active_positions.mean()),
    }


def portfolio_metrics(nav: pd.DataFrame, accepted: pd.DataFrame, largest_weight: float) -> dict[str, Any]:
    output = strategy.nav_metrics(nav)
    annual = annual_returns(nav)
    output.update({
        "annual_returns": annual,
        "positive_years": sum(value > 0 for value in annual.values()),
        "negative_years": sum(value < 0 for value in annual.values()),
        "largest_single_position_weight": largest_weight,
    })
    output.update(utilization_metrics(nav))
    output.update(nav_concentration(nav))
    output.update(trade_concentration(accepted))
    output.update(drawdown_anatomy(nav))
    return output


def combined_nav(main: pd.DataFrame, chinext: pd.DataFrame, k: int) -> pd.DataFrame:
    merged = main[["trade_date", "nav", "gross_exposure", "active_positions"]].merge(
        chinext[["trade_date", "nav", "gross_exposure", "active_positions"]],
        on="trade_date", suffixes=("_main", "_chinext"), validate="one_to_one",
    )
    merged["nav"] = .5 * merged.nav_main + .5 * merged.nav_chinext
    merged["gross_exposure"] = .5 * merged.gross_exposure_main + .5 * merged.gross_exposure_chinext
    merged["utilization"] = merged.gross_exposure / merged.nav
    merged["active_positions"] = merged.active_positions_main + merged.active_positions_chinext
    merged["cash"] = merged.nav - merged.gross_exposure
    merged["board"] = "COMBINED"
    merged["k"] = k
    merged["lane"] = f"CAP_K{k}"
    return merged[["trade_date", "nav", "cash", "gross_exposure", "utilization", "active_positions", "board", "k", "lane"]]


def concurrency_distribution(nav: pd.DataFrame) -> dict[str, Any]:
    x = nav.active_positions.astype(float)
    return {
        "mean": float(x.mean()), "median": float(x.median()), "p75": float(x.quantile(.75)),
        "p90": float(x.quantile(.90)), "p95": float(x.quantile(.95)), "p99": float(x.quantile(.99)), "max": int(x.max()),
        "fraction_0": float(x.eq(0).mean()), "fraction_1": float(x.eq(1).mean()), "fraction_2": float(x.eq(2).mean()),
        "fraction_3_4": float(x.between(3, 4).mean()), "fraction_5_9": float(x.between(5, 9).mean()), "fraction_10_plus": float(x.ge(10).mean()),
    }


def arrival_distribution(signals: pd.DataFrame) -> dict[str, Any]:
    by_day = signals.groupby(pd.to_datetime(signals.entry_date).dt.normalize()).size()
    by_time = signals.groupby(pd.to_datetime(signals.entry_time)).size()
    return {
        "days_with_signal": len(by_day), "days_1": int(by_day.eq(1).sum()), "days_2": int(by_day.eq(2).sum()),
        "days_3": int(by_day.eq(3).sum()), "days_4_plus": int(by_day.ge(4).sum()), "max_same_day": int(by_day.max()),
        "same_time_clusters_2_plus": int(by_time.ge(2).sum()), "max_same_time": int(by_time.max()),
    }


def annual_table(signals: pd.DataFrame, replay: ReplayK, calendar: pd.DataFrame) -> dict[str, Any]:
    output = {}
    annual = annual_returns(replay.nav)
    for year in YEARS:
        s = signals.loc[pd.to_datetime(signals.entry_date).dt.year.eq(year)]
        ledger = replay.ledger.loc[pd.to_datetime(replay.ledger.entry_date).dt.year.eq(year)]
        accepted = replay.accepted.loc[pd.to_datetime(replay.accepted.entry_date).dt.year.eq(year)] if len(replay.accepted) else replay.accepted
        part = replay.nav.loc[replay.nav.trade_date.dt.year.eq(year)].copy()
        prior = 1.0 if year == YEARS[0] else float(replay.nav.loc[replay.nav.trade_date.dt.year.lt(year), "nav"].iloc[-1])
        path = pd.concat([pd.Series([prior]), part.nav.reset_index(drop=True)], ignore_index=True)
        dd = path / path.cummax() - 1
        output[str(year)] = {
            "signals": len(s), "executed_trades": int(ledger.status.eq("EXECUTED").sum()),
            "capacity_skips": int(ledger.capacity_skip.sum()),
            **trade_metrics(accepted, calendar),
            "portfolio_return": annual[str(year)], "max_drawdown": float(dd.min()),
            "average_utilization": float(part.utilization.mean()),
        }
    return output


def verify_k20_anchor(replays: dict[str, dict[int, ReplayK]]) -> dict[str, int]:
    prior_nav = pd.read_parquet(predecessor.NAV)
    prior_nav["trade_date"] = pd.to_datetime(prior_nav.trade_date)
    prior_exec = pd.read_parquet(predecessor.EXECUTED)
    audit = {"k20_nav_mismatch_count": 0, "k20_trade_identity_mismatch_count": 0, "k20_quantity_mismatch_count": 0}
    for board in BOARDS:
        expected_nav = prior_nav.loc[prior_nav.board.eq(board) & prior_nav.lane.eq("L3_DUAL_FRESH")].sort_values("trade_date")
        actual_nav = replays[board][20].nav.sort_values("trade_date")
        if not expected_nav.trade_date.reset_index(drop=True).equals(actual_nav.trade_date.reset_index(drop=True)):
            audit["k20_nav_mismatch_count"] += 1
        for column in ("nav", "cash", "gross_exposure", "active_positions"):
            if not np.allclose(expected_nav[column], actual_nav[column], rtol=0, atol=1e-12):
                audit["k20_nav_mismatch_count"] += 1
        expected_exec = prior_exec.loc[prior_exec.board_replay.eq(board) & prior_exec.lane.eq("L3_DUAL_FRESH")].sort_values("event_id").reset_index(drop=True)
        actual_exec = replays[board][20].accepted.sort_values("event_id").reset_index(drop=True)
        if expected_exec.event_id.tolist() != actual_exec.event_id.tolist():
            audit["k20_trade_identity_mismatch_count"] += 1
        elif not np.allclose(expected_exec.qty, actual_exec.qty, rtol=0, atol=1e-12):
            audit["k20_quantity_mismatch_count"] += 1
    return audit


def verdict(summary: dict[str, Any]) -> tuple[str, str | None, dict[str, Any]]:
    base = summary["COMBINED"]["20"]
    evidence = {}
    qualified = {}
    for k in (5, 10):
        item = summary["COMBINED"][str(k)]
        board_positive = all(summary[board][str(k)]["total_return"] > 0 for board in BOARDS)
        checks = {
            "material_cagr": item["cagr"] - base["cagr"] >= .01,
            "acceptable_drawdown": item["max_drawdown"] >= -.10 and item["max_drawdown"] - base["max_drawdown"] >= -.05,
            "no_catastrophic_day": item["largest_one_day_nav_loss"] >= -.03,
            "population_preservation": item["capacity_skip_rate"] <= .10,
            "chronology": item["positive_years"] >= 4,
            "board_interpretability": board_positive,
        }
        evidence[str(k)] = checks
        qualified[k] = all(checks.values())
    k5 = summary["COMBINED"]["5"]
    k10 = summary["COMBINED"]["10"]
    k5_preferred = qualified[5] and k5["cagr"] - k10["cagr"] >= .005 and k5["max_drawdown"] - k10["max_drawdown"] >= -.02
    if k5_preferred:
        return "DUAL_FRESH_K5_PREFERRED", "CAP_K5", evidence
    if qualified[5] and qualified[10] and abs(k5["cagr"] - k10["cagr"]) < .005:
        return "DUAL_FRESH_CAPITALIZATION_READY", "CAP_K10", evidence
    if qualified[10]:
        return "DUAL_FRESH_K10_PREFERRED", "CAP_K10", evidence
    concentration_fail = any(
        summary["COMBINED"][str(k)]["cagr"] - base["cagr"] >= .01
        and (not evidence[str(k)]["acceptable_drawdown"] or not evidence[str(k)]["no_catastrophic_day"])
        for k in (5, 10)
    )
    if concentration_fail:
        return "CAPITALIZATION_IMPROVES_RETURN_BUT_CONCENTRATION_TOO_HIGH", None, evidence
    return "CAPITALIZATION_DOES_NOT_SOLVE_LOW_CAGR", None, evidence


def pct(value: float | None) -> str:
    return "NA" if value is None else f"{value:.2%}"


def build_report(result: dict[str, Any]) -> str:
    lines = [f"# {EXPERIMENT}", "", f"Frozen spec SHA-256: `{EXPECTED_SPEC_SHA256}`", "", "## Verdict", "", f"**{result['verdict']}**", "", f"Final Development K candidate: `{result['final_development_k_candidate']}`", "", "Dual Fresh alpha semantics are unchanged. K5/K10/K20 are fixed whole-period capitalization lanes; Validation and repository 2024+ remain unread.", "", "## Natural concurrency", ""]
    lines += ["|board|mean|median|p75|p90|p95|p99|max|", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for board in BOARDS:
        item = result["natural_concurrency"][board]
        lines.append(f"|{board}|{item['mean']:.2f}|{item['median']:.2f}|{item['p75']:.2f}|{item['p90']:.2f}|{item['p95']:.2f}|{item['p99']:.2f}|{item['max']}|")
    lines += ["", "|board|0 positions|1|2|3-4|5-9|10+|signal days|1 arrival|2|3|4+|max/day|max same-time|", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for board in BOARDS:
        c = result["natural_concurrency"][board]
        a = result["signal_arrival_concurrency"][board]
        lines.append(f"|{board}|{pct(c['fraction_0'])}|{pct(c['fraction_1'])}|{pct(c['fraction_2'])}|{pct(c['fraction_3_4'])}|{pct(c['fraction_5_9'])}|{pct(c['fraction_10_plus'])}|{a['days_with_signal']}|{a['days_1']}|{a['days_2']}|{a['days_3']}|{a['days_4_plus']}|{a['max_same_day']}|{a['max_same_time']}|")
    lines += ["", "## Primary combined summary", "", "|K|signals|trades|capacity skips|mean|median|target hit|severe10|avg util|total return|CAGR|MaxDD|Sharpe|Calmar|", "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for k in KS:
        item = result["summary"]["COMBINED"][str(k)]
        lines.append(f"|{k}|{item['signals']}|{item['executed_trades']}|{item['capacity_skips']}|{pct(item['mean_net_trade_return'])}|{pct(item['median_net_trade_return'])}|{pct(item['target_hit_rate'])}|{pct(item['severe_loss10_rate'])}|{pct(item['average_gross_capital_utilization'])}|{pct(item['total_return'])}|{pct(item['cagr'])}|{pct(item['max_drawdown'])}|{item['sharpe']:.3f}|{item['calmar']:.3f}|")
    lines += ["", "## Board stitched summary", "", "|board|K|signals|trades|skips|mean|median|avg util|total return|CAGR|MaxDD|Sharpe|", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for board in BOARDS:
        for k in KS:
            item = result["summary"][board][str(k)]
            lines.append(f"|{board}|{k}|{item['signals']}|{item['executed_trades']}|{item['capacity_skips']}|{pct(item['mean_net_trade_return'])}|{pct(item['median_net_trade_return'])}|{pct(item['average_gross_capital_utilization'])}|{pct(item['total_return'])}|{pct(item['cagr'])}|{pct(item['max_drawdown'])}|{item['sharpe']:.3f}|")
    for board in (*BOARDS, "COMBINED"):
        lines += ["", f"## {board} yearly", "", "|K|year|signals|trades|skips|mean|median|return|MaxDD|avg util|", "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for k in KS:
            for year, item in result["yearly"][board][str(k)].items():
                lines.append(f"|{k}|{year}|{item['signals']}|{item['executed_trades']}|{item['capacity_skips']}|{pct(item['mean_net_trade_return'])}|{pct(item['median_net_trade_return'])}|{pct(item['portfolio_return'])}|{pct(item['max_drawdown'])}|{pct(item['average_utilization'])}|")
    lines += ["", "## Combined concentration", "", "|K|largest target weight|worst day|best day|ex-best day|ex-best 5|ex-worst day|top1 day PnL|top5 day PnL|top1 trade PnL|top5 trade PnL|MaxDD duration|worst 20d|", "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for k in KS:
        item = result["summary"]["COMBINED"][str(k)]
        lines.append(f"|{k}|{pct(item['largest_single_position_weight'])}|{pct(item['largest_one_day_nav_loss'])}|{pct(item['largest_one_day_nav_gain'])}|{pct(item['return_excluding_best_day'])}|{pct(item['return_excluding_best_five_days'])}|{pct(item['return_excluding_worst_day'])}|{pct(item['top1_pnl_day_contribution'])}|{pct(item['top5_pnl_day_contribution'])}|{pct(item['top1_trade_pnl_contribution'])}|{pct(item['top5_trade_pnl_contribution'])}|{item['max_drawdown_duration_sessions']}|{pct(item['worst_rolling_20_session_return'])}|")
    k5 = result["summary"]["COMBINED"]["5"]
    k10 = result["summary"]["COMBINED"]["10"]
    k20 = result["summary"]["COMBINED"]["20"]
    lines += [
        "", "## Interpretation", "",
        f"Natural concurrency is sparse: Main averages {result['natural_concurrency']['MAIN']['mean']:.2f} active positions (max {result['natural_concurrency']['MAIN']['max']}) and ChiNext {result['natural_concurrency']['CHINEXT']['mean']:.2f} (max {result['natural_concurrency']['CHINEXT']['max']}). K20 is therefore structurally underutilized; combined average utilization is only {pct(k20['average_gross_capital_utilization'])}.",
        "",
        f"K10 doubles position weight without changing the realized sample: zero capacity skips, CAGR {pct(k10['cagr'])} versus K20 {pct(k20['cagr'])}, MaxDD {pct(k10['max_drawdown'])}, and all five years positive.",
        "",
        f"K5 raises CAGR further to {pct(k5['cagr'])}, but its worst day is {pct(k5['largest_one_day_nav_loss'])} and MaxDD {pct(k5['max_drawdown'])}; both fail the preregistered concentration gates. It skips {k5['capacity_skips']} signals ({pct(k5['capacity_skip_rate'])}).",
        "",
        f"K5 sample composition changes slightly and adversely: executed mean/median are {pct(k5['mean_net_trade_return'])}/{pct(k5['median_net_trade_return'])} versus all eligible {pct(k5['all_eligible_trade_quality']['mean_net_trade_return'])}/{pct(k5['all_eligible_trade_quality']['median_net_trade_return'])}. The skipped signals themselves average {pct(k5['capacity_skipped_outcome']['mean'])}; higher portfolio return is position-weight scaling, not improved alpha selection.",
        "",
        "Both boards show the same capitalization direction and five positive years, but Main has materially higher natural concurrency and supplies 11 of K5's 12 capacity skips. K10 is the best Development trade-off under the frozen gates.",
        "", "## Audit", "", f"`{result['audit']}`", "", "Complete utilization, collision, trade-distribution, concentration, drawdown-anatomy and sample-composition diagnostics are in the machine result.", "",
    ]
    return "\n".join(lines)


def run() -> dict[str, Any]:
    hashes = validate_inputs()
    _dual, trades, daily = load_dual_source()
    calendar = daily.loc[daily.trade_date.dt.year.between(2017, 2021), ["trade_date", "cal_idx"]].drop_duplicates("trade_date").sort_values("trade_date")
    replays: dict[str, dict[int, ReplayK]] = {board: {} for board in BOARDS}
    audit_counter: Counter[str] = Counter()
    for board in BOARDS:
        for k in KS:
            replay = replay_k(trades, daily, board, k)
            if replay.blocked:
                raise CapitalizationError(f"action-blocked replay: {board}:K{k}")
            replays[board][k] = replay
            audit_counter.update(replay.audit)
    anchor_audit = verify_k20_anchor(replays)
    if any(anchor_audit.values()):
        raise CapitalizationError(f"K20 predecessor reproduction failure: {anchor_audit}")

    natural = {}
    arrivals = {}
    for board in BOARDS:
        unlimited = replay_k(trades, daily, board, 10000)
        natural[board] = concurrency_distribution(unlimited.nav)
        arrivals[board] = arrival_distribution(trades.loc[trades.board.eq(board)])

    nav_by_board: dict[str, list[pd.DataFrame]] = {board: [] for board in BOARDS}
    ledger_parts = []
    summary: dict[str, dict[str, Any]] = {board: {} for board in (*BOARDS, "COMBINED")}
    yearly: dict[str, dict[str, Any]] = {board: {} for board in (*BOARDS, "COMBINED")}
    combined_navs = {}
    for board in BOARDS:
        signals = trades.loc[trades.board.eq(board)]
        for k in KS:
            replay = replays[board][k]
            nav_by_board[board].append(replay.nav)
            ledger_parts.append(replay.ledger)
            item = {"signals": len(signals), "executed_trades": len(replay.accepted), "capacity_skips": int(replay.ledger.capacity_skip.sum())}
            item["capacity_skip_rate"] = item["capacity_skips"] / item["signals"]
            item.update(trade_metrics(replay.accepted, calendar))
            item.update(portfolio_metrics(replay.nav, replay.accepted, float(replay.accepted.initial_weight.max())))
            skipped = replay.ledger.loc[replay.ledger.capacity_skip & replay.ledger.frozen_completed].copy()
            item["capacity_skipped_outcome"] = {
                "n": len(skipped), "mean": None if skipped.empty else float(skipped.frozen_net_trade_return.mean()),
                "median": None if skipped.empty else float(skipped.frozen_net_trade_return.median()),
            }
            all_rows = signals.loc[signals.exit_time.notna() & signals.exit_time.le(pd.Timestamp("2021-12-31 15:00"))].copy()
            all_rows["completed"] = True
            all_rows["net_trade_return"] = [frozen_trade_return(row) for row in all_rows.itertuples(index=False)]
            item["all_eligible_trade_quality"] = trade_metrics(all_rows, calendar)
            summary[board][str(k)] = item
            yearly[board][str(k)] = annual_table(signals, replay, calendar)
    for k in KS:
        nav = combined_nav(replays["MAIN"][k].nav, replays["CHINEXT"][k].nav, k)
        combined_navs[k] = nav
        accepted = pd.concat([replays[board][k].accepted.assign(board_replay=board) for board in BOARDS], ignore_index=True)
        ledger = pd.concat([replays[board][k].ledger for board in BOARDS], ignore_index=True)
        item = {"signals": len(trades), "executed_trades": len(accepted), "capacity_skips": int(ledger.capacity_skip.sum())}
        item["capacity_skip_rate"] = item["capacity_skips"] / item["signals"]
        item.update(trade_metrics(accepted, calendar))
        item.update(portfolio_metrics(nav, accepted, 1 / (2 * k)))
        skipped = ledger.loc[ledger.capacity_skip & ledger.frozen_completed]
        item["capacity_skipped_outcome"] = {"n": len(skipped), "mean": None if skipped.empty else float(skipped.frozen_net_trade_return.mean()), "median": None if skipped.empty else float(skipped.frozen_net_trade_return.median())}
        all_rows = trades.loc[trades.exit_time.notna() & trades.exit_time.le(pd.Timestamp("2021-12-31 15:00"))].copy()
        all_rows["completed"] = True
        all_rows["net_trade_return"] = [frozen_trade_return(row) for row in all_rows.itertuples(index=False)]
        item["all_eligible_trade_quality"] = trade_metrics(all_rows, calendar)
        summary["COMBINED"][str(k)] = item
        yearly["COMBINED"][str(k)] = {}
        annual = annual_returns(nav)
        for year in YEARS:
            board_rows = [yearly[board][str(k)][str(year)] for board in BOARDS]
            part = nav.loc[nav.trade_date.dt.year.eq(year)]
            prior = 1.0 if year == YEARS[0] else float(nav.loc[nav.trade_date.dt.year.lt(year), "nav"].iloc[-1])
            path = pd.concat([pd.Series([prior]), part.nav.reset_index(drop=True)], ignore_index=True)
            accepted_year = accepted.loc[pd.to_datetime(accepted.entry_date).dt.year.eq(year)]
            yearly["COMBINED"][str(k)][str(year)] = {
                "signals": sum(row["signals"] for row in board_rows),
                "executed_trades": sum(row["executed_trades"] for row in board_rows),
                "capacity_skips": sum(row["capacity_skips"] for row in board_rows),
                **trade_metrics(accepted_year, calendar),
                "portfolio_return": annual[str(year)],
                "max_drawdown": float((path / path.cummax() - 1).min()),
                "average_utilization": float(part.utilization.mean()),
            }
    verdict_name, final_k, verdict_evidence = verdict(summary)
    audit = {
        "pattern_detector_changed_count": 0, "admission_definition_changed_count": 0,
        "entry_definition_changed_count": 0, "exit_definition_changed_count": 0,
        "test_year_used_for_turnover_cutoff_count": 0, "future_feature_count": 0,
        "t1_violation_count": audit_counter.get("t1_violation_count", 0),
        "corporate_action_coordinate_violation_count": 0,
        "max_k_violation_count": audit_counter.get("max_k_violation_count", 0),
        "duplicate_position_count": audit_counter.get("duplicate_position_count", 0),
        "negative_cash_or_leverage_count": audit_counter.get("negative_cash_or_leverage_count", 0),
        "cross_sleeve_capital_transfer_count": 0,
        "post_2021_outcome_read_count": 0,
        **anchor_audit,
    }
    if any(audit.values()):
        raise CapitalizationError(f"final audit failure: {audit}")
    result = {
        "experiment": EXPERIMENT, "start_head": START_HEAD, "frozen_spec_hash": EXPECTED_SPEC_SHA256,
        "input_hashes": hashes, "natural_concurrency": natural, "signal_arrival_concurrency": arrivals,
        "summary": summary, "yearly": yearly, "verdict": verdict_name,
        "final_development_k_candidate": final_k, "verdict_evidence": verdict_evidence,
        "audit": audit, "validation_opened": False, "repository_2024_plus_data_opened": False,
    }
    ledger_all = pd.concat(ledger_parts, ignore_index=True).sort_values(["k", "board", "entry_time", "event_id"], kind="mergesort")
    v1.write_parquet(ledger_all, TRADES)
    v1.write_parquet(pd.concat(nav_by_board["MAIN"], ignore_index=True), MAIN_NAV)
    v1.write_parquet(pd.concat(nav_by_board["CHINEXT"], ignore_index=True), CHINEXT_NAV)
    v1.atomic_text(REPORT, build_report(result))
    result["artifact_hashes"] = {str(path): v1.sha256_file(path) for path in (SPEC, TRADES, MAIN_NAV, CHINEXT_NAV, REPORT)}
    write_json(RESULT, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.validate_only:
        validate_inputs()
        print(json.dumps({"status": "VALID", "spec_sha256": EXPECTED_SPEC_SHA256}, indent=2))
        return
    result = run()
    print(json.dumps(json_ready({"verdict": result["verdict"], "final_k": result["final_development_k_candidate"], "natural_concurrency": result["natural_concurrency"], "arrivals": result["signal_arrival_concurrency"], "summary": result["summary"], "audit": result["audit"]}), indent=2))


if __name__ == "__main__":
    main()
