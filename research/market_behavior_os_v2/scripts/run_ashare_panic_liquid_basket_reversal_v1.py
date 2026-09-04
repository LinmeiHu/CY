#!/usr/bin/env python3
"""Run the frozen sequential panic/liquid-basket Strategy-B experiment."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
EXPERIMENT_ID = "ASHARE-PANIC-LIQUID-BASKET-REVERSAL-V1"
SPEC_PATH = PROGRAM / f"experiments/{EXPERIMENT_ID}_spec.json"
SELECTION_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_selection.csv"
RESULT_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_result.json"
REPORT_PATH = PROGRAM / f"reports/{EXPERIMENT_ID}_report.md"
EXPECTED_SPEC_SHA256 = "ce9631f6721c4ab91fac33ee5bed48f745bf185f9f8350689b50acd704056462"
INITIAL_CAPITAL = 10_000_000.0
COHORT_DIVISOR = 5
HORIZON = 5
COST = 0.002
FAMILY = "panic_liquid_basket_reversal"


class PanicReversalError(RuntimeError):
    """Fail-closed panic-reversal experiment error."""


@dataclass
class Lot:
    symbol: str
    industry: str
    signal_date: date
    due_index: int
    shares: float
    invested_cost: float
    action_cash: float = 0.0
    forced_effective_date: date | None = None
    forced_event_id: str | None = None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (date, pd.Timestamp)):
        return value.isoformat()
    if value is None or pd.isna(value):
        return None
    return value


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise PanicReversalError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise PanicReversalError("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_SEQUENTIAL_STRATEGY_B_BEFORE_GENERATION_REPLAY":
        raise PanicReversalError("spec is not frozen before generation replay")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise PanicReversalError(f"bound input changed: {name}")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("post-2023", "CY-011", "before every generation", "combination"):
        if phrase not in prohibited:
            raise PanicReversalError(f"missing frozen prohibition: {phrase}")
    return spec


def _selection(spec: dict[str, Any]) -> pd.DataFrame:
    state_path = _resolve(spec["inputs"]["risk_state_panel"]["path"])
    state = pd.read_csv(
        state_path,
        usecols=[
            "trade_date",
            "market_view",
            "denominator",
            "decision_at",
            "available_at",
            "downside_extreme_participation_70_pit_3y_pct",
        ],
        parse_dates=["trade_date"],
    )
    state = state.loc[
        state.market_view.eq("ALL_A") & state.denominator.eq("ALL_STATUS")
    ].copy()
    if state.duplicated("trade_date").any() or state.trade_date.max() > pd.Timestamp(
        "2023-12-31"
    ):
        raise PanicReversalError("risk-state date identity failed")
    state["decision_at"] = pd.to_datetime(state.decision_at, utc=True)
    state["available_at"] = pd.to_datetime(state.available_at, utc=True)
    if (state.available_at > state.decision_at).any():
        raise PanicReversalError("risk state entered before availability")
    coordinate = "downside_extreme_participation_70_pit_3y_pct"
    first_valid = state.loc[state[coordinate].notna(), "trade_date"].min()
    if first_valid != pd.Timestamp("2020-07-28"):
        raise PanicReversalError(f"unexpected causal activation: {first_valid}")
    expected = state.trade_date.ge(first_valid)
    if state.loc[expected, coordinate].isna().any():
        raise PanicReversalError("missing risk state after causal activation")
    active = state.loc[expected & state[coordinate].ge(0.80), ["trade_date", coordinate]]

    feature_path = _resolve(spec["inputs"]["daily_feature_panel"]["path"])
    feature = pd.read_parquet(
        feature_path,
        columns=[
            "trade_date",
            "decision_at",
            "available_at",
            "symbol",
            "industry",
            "avg_amount20",
        ],
    )
    feature["trade_date"] = pd.to_datetime(feature.trade_date)
    feature["decision_at"] = pd.to_datetime(feature.decision_at)
    feature["available_at"] = pd.to_datetime(feature.available_at)
    if (
        feature.trade_date.max() > pd.Timestamp("2023-12-31")
        or (feature.available_at > feature.decision_at).any()
        or feature.duplicated(["trade_date", "symbol"]).any()
        or feature.avg_amount20.lt(50_000_000).any()
        or not np.isfinite(feature.avg_amount20).all()
    ):
        raise PanicReversalError("daily causal feature panel audit failed")
    selected = feature.merge(active, on="trade_date", how="inner", validate="many_to_one")
    selected = selected.sort_values(
        ["trade_date", "avg_amount20", "symbol"], ascending=[True, False, True]
    )
    selected["liquidity_rank"] = selected.groupby("trade_date").cumcount() + 1
    selected = selected.loc[selected.liquidity_rank.le(20)].copy()
    if selected.groupby("trade_date").size().ne(20).any():
        raise PanicReversalError("frozen top-20 basket breadth changed")
    selected["signal_date"] = selected.trade_date.dt.date
    selected["industry"] = selected.industry.astype(str)
    columns = [
        "signal_date",
        "symbol",
        "industry",
        "avg_amount20",
        "liquidity_rank",
        coordinate,
    ]
    return selected[columns].sort_values(["signal_date", "liquidity_rank", "symbol"])


def _phase_bounds(
    calendar: list[date], start_raw: str, cutoff_raw: str
) -> tuple[int, int, date, date]:
    start_target = pd.Timestamp(start_raw).date()
    cutoff_target = pd.Timestamp(cutoff_raw).date()
    start_candidates = [index for index, day in enumerate(calendar) if day >= start_target]
    cutoff_candidates = [index for index, day in enumerate(calendar) if day <= cutoff_target]
    if not start_candidates or not cutoff_candidates:
        raise PanicReversalError("phase is outside market calendar")
    start_index = start_candidates[0]
    cutoff_index = cutoff_candidates[-1]
    if start_index >= cutoff_index:
        raise PanicReversalError("invalid phase bounds")
    return start_index, cutoff_index, calendar[start_index], calendar[cutoff_index]


def _plans(
    selection: pd.DataFrame,
    calendar: list[date],
    start_raw: str,
    end_raw: str,
    cutoff_raw: str,
) -> pd.DataFrame:
    calendar_index = {day: index for index, day in enumerate(calendar)}
    start = pd.Timestamp(start_raw).date()
    end = pd.Timestamp(end_raw).date()
    cutoff = pd.Timestamp(cutoff_raw).date()
    rows: list[dict[str, Any]] = []
    phase = selection.loc[selection.signal_date.between(start, end)].copy()
    for item in phase.itertuples(index=False):
        signal_date = item.signal_date
        if signal_date not in calendar_index:
            raise PanicReversalError(f"signal date absent from calendar: {signal_date}")
        entry_index = calendar_index[signal_date] + 1
        due_index = entry_index + HORIZON
        if due_index >= len(calendar) or calendar[due_index] > cutoff:
            continue
        rows.append(
            {
                "family": FAMILY,
                "signal_date": signal_date,
                "symbol": item.symbol,
                "industry": item.industry,
                "avg_amount20": float(item.avg_amount20),
                "state_value": float(
                    item.downside_extreme_participation_70_pit_3y_pct
                ),
                "entry_index": entry_index,
                "due_index": due_index,
                "horizon": HORIZON,
            }
        )
    plans = pd.DataFrame(rows)
    if plans.empty or plans.groupby("signal_date").size().ne(20).any():
        raise PanicReversalError("phase plan breadth changed")
    return plans.sort_values(
        ["entry_index", "avg_amount20", "symbol"], ascending=[True, False, True]
    )


def _query_execution_rows(
    paths: list[Path], plans: pd.DataFrame, calendar: list[date], cutoff_index: int
) -> pd.DataFrame:
    keys: set[tuple[str, date]] = set()
    for row in plans.itertuples(index=False):
        for index in range(int(row.entry_index), cutoff_index + 1):
            keys.add((row.symbol, calendar[index]))
    key_frame = pd.DataFrame(sorted(keys), columns=["symbol", "trade_date"])
    connection = duckdb.connect()
    connection.register("needed_keys", key_frame)
    rows = connection.execute(
        """
        SELECT d.trade_date,d.symbol,d.open,d.close,d.amount,d.hard_valid,d.trade_status,
          d.current_day_data_tradable,d.buy_blocked_open,d.sell_blocked_open,
          d.corporate_action_count,d.corporate_action_valid,d.corporate_action_blocking,
          d.corporate_action_available_date,d.share_multiplier,d.cash_per_share,
          d.rights_ratio,d.available_at,d.invalid_reasons,d.corporate_action_problems,
          d.corporate_action_ids,d.corporate_action_snapshot_id
        FROM read_parquet(?) d JOIN needed_keys k USING(symbol,trade_date)
        ORDER BY d.trade_date,d.symbol
        """,
        [[str(path) for path in paths]],
    ).fetchdf()
    connection.close()
    if rows.duplicated(["symbol", "trade_date"]).any():
        raise PanicReversalError("duplicate execution row")
    if pd.to_datetime(rows.trade_date).max().date() > calendar[cutoff_index]:
        raise PanicReversalError("outcome row crossed phase boundary")
    return rows


def _year_returns(equity: pd.DataFrame) -> dict[str, float]:
    work = equity.copy()
    work["year"] = pd.to_datetime(work.trade_date).dt.year
    ending = work.groupby("year").nav.last().sort_index()
    output: dict[str, float] = {}
    prior = INITIAL_CAPITAL
    for year, nav in ending.items():
        output[str(int(year))] = float(nav / prior - 1.0)
        prior = float(nav)
    return output


def _replay(
    plans: pd.DataFrame,
    market_rows: pd.DataFrame,
    calendar: list[date],
    events: list[Any],
    ca: Any,
    start_index: int,
    cutoff_index: int,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    row_map = {
        (row.symbol, pd.Timestamp(row.trade_date).date()): row
        for row in market_rows.itertuples(index=False)
    }
    entry_map = {
        int(index): list(group.itertuples(index=False))
        for index, group in plans.groupby("entry_index", sort=True)
    }
    event_decisions, symbol_events = ca._event_maps(events)
    cash = INITIAL_CAPITAL
    lots: list[Lot] = []
    turnover = 0.0
    planned_entries = 0
    entries = 0
    completed = 0
    risk_blocked_entries = 0
    market_unexecutable_entries = 0
    capital_skipped_entries = 0
    severe = 0
    forced_exits = 0
    forced_pending_days = 0
    cash_constrained_events = 0
    allocation_fractions: list[float] = []
    capacity: list[float] = []
    nav_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []

    for cal_index in range(start_index, cutoff_index + 1):
        current_date = calendar[cal_index]
        for lot in lots:
            if lot.forced_effective_date is not None and current_date >= lot.forced_effective_date:
                raise PanicReversalError(
                    f"pre-effective exit failed:{lot.symbol}:{lot.forced_event_id}:"
                    f"{lot.forced_effective_date}"
                )
            row = row_map.get((lot.symbol, current_date))
            if row is None or not ca._holding_row_usable(row):
                raise PanicReversalError(f"invalid holding row:{lot.symbol}:{current_date}")
            if int(row.corporate_action_count or 0) > 0:
                action = ca.PRIOR.PRIOR._visible_action(row)
                if action is None:
                    raise PanicReversalError(
                        f"unresolved effective action:{lot.symbol}:{current_date}"
                    )
                multiplier, cash_per_share = action
                if multiplier != 1.0:
                    raise PanicReversalError(
                        f"share risk event reached effective date:{lot.symbol}:{current_date}"
                    )
                lot.action_cash += lot.shares * cash_per_share

        survivors: list[Lot] = []
        for lot in lots:
            row = row_map[(lot.symbol, current_date)]
            forced = lot.forced_effective_date is not None
            due = cal_index >= lot.due_index
            if not forced and not due:
                survivors.append(lot)
                continue
            if not ca._sellable(row):
                forced_pending_days += int(forced)
                survivors.append(lot)
                continue
            gross = lot.shares * float(row.open)
            proceeds = lot.action_cash + gross * (1.0 - COST)
            cash += proceeds
            turnover += gross
            payoff = float(proceeds / lot.invested_cost - 1.0)
            completed += 1
            severe += int(payoff <= -0.10)
            forced_exits += int(forced)
            trade_rows.append(
                {
                    "signal_date": lot.signal_date,
                    "symbol": lot.symbol,
                    "industry": lot.industry,
                    "exit_date": current_date,
                    "exit_reason": "FORCED" if forced else "DUE",
                    "net_return": payoff,
                }
            )
        lots = survivors

        pre_entry_nav = cash + sum(
            lot.action_cash + lot.shares * float(row_map[(lot.symbol, current_date)].open)
            for lot in lots
        )
        planned = entry_map.get(cal_index, [])
        planned_entries += len(planned)
        nonrisk: list[tuple[Any, Any | None]] = []
        for plan in planned:
            row = row_map.get((plan.symbol, current_date))
            if ca._entry_blocked(plan.symbol, plan.signal_date, current_date, symbol_events):
                risk_blocked_entries += 1
                continue
            nonrisk.append((plan, row))
        executable: list[tuple[Any, Any]] = []
        for plan, row in nonrisk:
            if (
                row is not None
                and ca.PRIOR._valid_market_row(row)
                and int(row.trade_status) == 1
                and bool(row.current_day_data_tradable)
                and not bool(row.buy_blocked_open)
            ):
                executable.append((plan, row))
        market_unexecutable_entries += len(nonrisk) - len(executable)
        if planned:
            target_capital = pre_entry_nav / COHORT_DIVISOR
            cohort_capital = min(cash, target_capital) if cash > 0 else 0.0
            allocation_fraction = float(cohort_capital / target_capital)
            allocation_fractions.append(allocation_fraction)
            cash_constrained_events += int(allocation_fraction < 1.0 - 1e-10)
        else:
            cohort_capital = 0.0
        if executable and cohort_capital <= 0:
            capital_skipped_entries += len(executable)
        if executable and cohort_capital > 1e-8:
            allocation = cohort_capital / len(executable)
            for plan, row in executable:
                shares = allocation / (float(row.open) * (1.0 + COST))
                gross = shares * float(row.open)
                cash -= allocation
                turnover += gross
                lots.append(
                    Lot(
                        symbol=plan.symbol,
                        industry=str(plan.industry),
                        signal_date=plan.signal_date,
                        due_index=int(plan.due_index),
                        shares=shares,
                        invested_cost=allocation,
                    )
                )
                entries += 1
                capacity.append(
                    float(row.amount) * 0.05 * len(executable) * COHORT_DIVISOR
                )

        for lot in lots:
            for event in event_decisions.get((lot.symbol, current_date), ()):
                if (
                    lot.forced_effective_date is None
                    or event.effective_date < lot.forced_effective_date
                ):
                    lot.forced_effective_date = event.effective_date
                    lot.forced_event_id = event.event_id

        nav = cash
        industry_values: dict[str, float] = {}
        for lot in lots:
            row = row_map[(lot.symbol, current_date)]
            value = lot.action_cash + lot.shares * float(row.close)
            nav += value
            industry_values[lot.industry] = industry_values.get(lot.industry, 0.0) + value
        invested_value = sum(industry_values.values())
        hhi = (
            sum((value / invested_value) ** 2 for value in industry_values.values())
            if invested_value > 0
            else 0.0
        )
        nav_rows.append(
            {
                "trade_date": current_date,
                "family": FAMILY,
                "nav": nav,
                "cash": cash,
                "positions": len(lots),
                "industries": len(industry_values),
                "industry_hhi": hhi,
            }
        )

    equity = pd.DataFrame(nav_rows)
    trades = pd.DataFrame(trade_rows)
    if lots or completed != entries:
        return (
            {
                "family": FAMILY,
                "status": "BLOCKED_PHASE_BOUNDARY_OPEN_LOTS",
                "terminal_open_lots": len(lots),
                "entries": entries,
                "completed_trades": completed,
            },
            equity,
            trades,
        )
    returns = equity.nav.pct_change().fillna(equity.nav.iloc[0] / INITIAL_CAPITAL - 1.0)
    drawdown = equity.nav / equity.nav.cummax() - 1.0
    years = len(equity) / 252.0
    annualized = (equity.nav.iloc[-1] / INITIAL_CAPITAL) ** (1.0 / years) - 1.0
    volatility = returns.std(ddof=1)
    sharpe = math.sqrt(252.0) * returns.mean() / volatility if volatility > 0 else 0.0
    maximum_drawdown = float(drawdown.min())
    result = {
        "family": FAMILY,
        "status": "COMPLETE",
        "start_date": str(equity.trade_date.iloc[0]),
        "end_date": str(equity.trade_date.iloc[-1]),
        "total_return": float(equity.nav.iloc[-1] / INITIAL_CAPITAL - 1.0),
        "annualized_return": float(annualized),
        "maximum_drawdown": maximum_drawdown,
        "daily_sharpe": float(sharpe),
        "calmar": float(annualized / abs(maximum_drawdown)) if maximum_drawdown < 0 else None,
        "calendar_year_returns": _year_returns(equity),
        "turnover_multiple_initial_capital": float(turnover / INITIAL_CAPITAL),
        "signal_dates": int(plans.signal_date.nunique()),
        "planned_entries": planned_entries,
        "entries": entries,
        "entry_execution_fraction": float(entries / planned_entries),
        "risk_blocked_entries": risk_blocked_entries,
        "market_unexecutable_entries": market_unexecutable_entries,
        "capital_skipped_entries": capital_skipped_entries,
        "completed_trades": completed,
        "severe_trade_fraction": float(severe / completed),
        "forced_pre_effective_exits": forced_exits,
        "forced_exit_pending_days": forced_pending_days,
        "cash_constrained_events": cash_constrained_events,
        "mean_event_allocation_fraction": float(np.mean(allocation_fractions)),
        "minimum_cash": float(equity.cash.min()),
        "mean_positions": float(equity.positions.mean()),
        "mean_industries": float(equity.industries.mean()),
        "mean_industry_hhi_invested_days": float(
            equity.loc[equity.positions > 0, "industry_hhi"].mean()
        ),
        "p10_capacity_cny_at_5pct_amount": float(np.quantile(capacity, 0.10)),
        "median_capacity_cny_at_5pct_amount": float(np.median(capacity)),
        "terminal_open_lots": len(lots),
    }
    return result, equity, trades


def _gate(metrics: dict[str, Any], required: dict[str, Any]) -> dict[str, bool]:
    if metrics.get("status") != "COMPLETE":
        return {"complete": False}
    checks = {
        "complete": True,
        "signal_dates": metrics["signal_dates"] >= required["minimum_signal_dates"],
        "entry_execution": metrics["entry_execution_fraction"]
        >= required["minimum_entry_execution_fraction"],
        "annualized_return": metrics["annualized_return"]
        >= required["minimum_annualized_return"],
        "daily_sharpe": metrics["daily_sharpe"] >= required["minimum_daily_sharpe"],
        "maximum_drawdown": metrics["maximum_drawdown"]
        > required["maximum_drawdown_must_be_greater_than"],
        "severe_trade_fraction": metrics["severe_trade_fraction"]
        <= required["maximum_severe_trade_fraction"],
    }
    year_key = (
        "positive_calendar_subperiods"
        if "positive_calendar_subperiods" in required
        else "positive_calendar_years"
    )
    for year in required[year_key]:
        checks[f"positive_{year}"] = metrics["calendar_year_returns"].get(year, -1.0) > 0
    return checks


def _write_phase(name: str, equity: pd.DataFrame, trades: pd.DataFrame) -> dict[str, str]:
    equity_path = PROGRAM / f"artifacts/{EXPERIMENT_ID}_{name}_equity.csv"
    trades_path = PROGRAM / f"artifacts/{EXPERIMENT_ID}_{name}_trades.csv"
    _atomic_write(
        equity_path,
        equity.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )
    _atomic_write(
        trades_path,
        trades.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )
    return {
        f"{name}_equity_sha256": sha256_file(equity_path),
        f"{name}_trades_sha256": sha256_file(trades_path),
    }


def _independence(
    spec: dict[str, Any], full_equity: pd.DataFrame, full_plans: pd.DataFrame
) -> dict[str, Any]:
    q1_equity = pd.read_csv(
        _resolve(spec["inputs"]["industry_consensus_q1_equity"]["path"]),
        parse_dates=["trade_date"],
    )
    candidate = full_equity.copy()
    candidate["trade_date"] = pd.to_datetime(candidate.trade_date)
    q1_equity["return_q1"] = q1_equity.nav.pct_change()
    candidate["return_b"] = candidate.nav.pct_change()
    joined = candidate[["trade_date", "return_b"]].merge(
        q1_equity[["trade_date", "return_q1"]], on="trade_date", how="inner"
    ).dropna()
    correlation = float(joined[["return_b", "return_q1"]].corr().iloc[0, 1])

    q1_panel = pd.read_csv(
        _resolve(spec["inputs"]["diffusion_q1_trade_panel"]["path"]),
        parse_dates=["signal_date"],
    )
    q1 = q1_panel.loc[q1_panel.intensity_bucket.eq(1)].copy()
    same_industry = q1.groupby("signal_date").industry.nunique().eq(1)
    q1_dates = {pd.Timestamp(day).date() for day in same_industry.index[same_industry]}
    b_dates = set(full_plans.signal_date.unique())
    overlap = len(q1_dates & b_dates)
    union = len(q1_dates | b_dates)
    return {
        "daily_return_correlation_with_industry_consensus_q1": correlation,
        "strategy_b_signal_dates": len(b_dates),
        "q1_same_industry_signal_dates": len(q1_dates),
        "signal_date_overlap": overlap,
        "signal_date_jaccard": float(overlap / union),
    }


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# Panic liquid-basket reversal V1",
        "",
        f"Status: `{result['status']}`.",
        "",
        (
            "The frozen signal is the top historical quintile of ALL-A downside-extreme "
            "participation. It buys the 20 highest prior-20-session amount stocks at the "
            "next legal open, assigns one-fifth NAV per daily event, and exits at h5."
        ),
        "",
    ]
    for name in ("generation", "validation", "full"):
        metrics = result.get(name)
        if not metrics:
            continue
        lines.extend(
            [
                f"## {name.title()}",
                "",
                f"Status `{metrics['status']}`.",
            ]
        )
        if metrics["status"] == "COMPLETE":
            lines.extend(
                [
                    (
                        f"Annualized {metrics['annualized_return']:.2%}; total "
                        f"{metrics['total_return']:.2%}; max drawdown "
                        f"{metrics['maximum_drawdown']:.2%}; Sharpe "
                        f"{metrics['daily_sharpe']:.3f}; severe trades "
                        f"{metrics['severe_trade_fraction']:.2%}."
                    ),
                    (
                        f"Signals {metrics['signal_dates']}; completed trades "
                        f"{metrics['completed_trades']}; entry coverage "
                        f"{metrics['entry_execution_fraction']:.2%}."
                    ),
                ]
            )
        lines.append("")
    if result.get("independence"):
        item = result["independence"]
        lines.extend(
            [
                "## Independence",
                "",
                (
                    f"Daily-return correlation with Industry-Consensus Q1 is "
                    f"{item['daily_return_correlation_with_industry_consensus_q1']:.3f}; "
                    f"signal-date overlap is {item['signal_date_overlap']} "
                    f"(Jaccard {item['signal_date_jaccard']:.3f})."
                ),
                "",
            ]
        )
    lines.extend(
        [
            "This is sequential research on consumed development history, not OOS or "
            "independent confirmation. Post-2023 outcomes and CY-011 were not read. No "
            "Strategy-A combination or parameter rescue was run.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> dict[str, Any]:
    spec = _load_spec()
    ca = _load_module("ca_for_panic_reversal", _resolve(spec["inputs"]["execution_runner"]["path"]))
    ca_spec = ca._load_spec()
    paths, calendar, input_identity = ca._load_market_inputs(ca_spec)
    events, action_audit = ca._load_risk_events(ca_spec, calendar)
    selection = _selection(spec)
    _atomic_write(
        SELECTION_PATH,
        selection.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )

    protocol = spec["sequential_protocol"]
    generation_spec = protocol["generation"]
    gen_start, gen_cutoff, _, _ = _phase_bounds(
        calendar,
        generation_spec["signal_period"][0],
        generation_spec["maximum_outcome_date"],
    )
    generation_plans = _plans(
        selection,
        calendar,
        generation_spec["signal_period"][0],
        generation_spec["signal_period"][1],
        generation_spec["maximum_outcome_date"],
    )
    generation_rows = _query_execution_rows(paths, generation_plans, calendar, gen_cutoff)
    generation, gen_equity, gen_trades = _replay(
        generation_plans,
        generation_rows,
        calendar,
        events,
        ca,
        gen_start,
        gen_cutoff,
    )
    generation_checks = _gate(
        generation, generation_spec["all_required_to_open_validation"]
    )
    generation_passed = all(generation_checks.values())
    hashes = {
        "spec_sha256": sha256_file(SPEC_PATH),
        "selection_sha256": sha256_file(SELECTION_PATH),
        **_write_phase("generation", gen_equity, gen_trades),
    }
    result: dict[str, Any] = {
        "experiment_id": EXPERIMENT_ID,
        "claim_boundary": spec["claim_boundary"],
        "post_2023_outcome_read": "NO",
        "cy011_read": "NO",
        "input_identity": input_identity,
        "action_audit": action_audit,
        "generation": generation,
        "generation_checks": generation_checks,
        "generation_passed": generation_passed,
        "validation_opened": False,
        "full_replay_opened": False,
        "hashes": hashes,
    }
    if not generation_passed:
        result["status"] = "GENERATION_REJECTED_VALIDATION_UNOPENED"
        _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
        _atomic_write(REPORT_PATH, _render(result))
        return result

    validation_spec = protocol["validation"]
    val_start, val_cutoff, _, _ = _phase_bounds(
        calendar,
        validation_spec["signal_period"][0],
        validation_spec["maximum_outcome_date"],
    )
    validation_plans = _plans(
        selection,
        calendar,
        validation_spec["signal_period"][0],
        validation_spec["signal_period"][1],
        validation_spec["maximum_outcome_date"],
    )
    validation_rows = _query_execution_rows(paths, validation_plans, calendar, val_cutoff)
    validation, val_equity, val_trades = _replay(
        validation_plans,
        validation_rows,
        calendar,
        events,
        ca,
        val_start,
        val_cutoff,
    )
    validation_checks = _gate(validation, validation_spec["all_required"])
    validation_passed = all(validation_checks.values())
    result.update(
        {
            "validation_opened": True,
            "validation": validation,
            "validation_checks": validation_checks,
            "validation_passed": validation_passed,
        }
    )
    result["hashes"].update(_write_phase("validation", val_equity, val_trades))
    if not validation_passed:
        result["status"] = "VALIDATION_REJECTED_NO_FULL_REPLAY"
        _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
        _atomic_write(REPORT_PATH, _render(result))
        return result

    full_start, full_cutoff, _, _ = _phase_bounds(calendar, "2020-07-28", "2023-12-31")
    full_plans = pd.concat([generation_plans, validation_plans], ignore_index=True)
    full_rows = _query_execution_rows(paths, full_plans, calendar, full_cutoff)
    full, full_equity, full_trades = _replay(
        full_plans,
        full_rows,
        calendar,
        events,
        ca,
        full_start,
        full_cutoff,
    )
    independence = _independence(spec, full_equity, full_plans)
    full_gate = protocol["final_candidate_all_required"]
    full_checks = {
        "complete": full.get("status") == "COMPLETE",
        "annualized_return": full.get("annualized_return", -1.0)
        >= full_gate["minimum_annualized_return"],
        "daily_sharpe": full.get("daily_sharpe", -1.0)
        >= full_gate["minimum_daily_sharpe"],
        "maximum_drawdown": full.get("maximum_drawdown", -1.0)
        > full_gate["maximum_drawdown_must_be_greater_than"],
        "independence": abs(
            independence["daily_return_correlation_with_industry_consensus_q1"]
        )
        <= full_gate["maximum_daily_return_correlation_with_industry_consensus_q1"],
    }
    result.update(
        {
            "full_replay_opened": True,
            "full": full,
            "independence": independence,
            "full_checks": full_checks,
            "status": (
                "STRATEGY_B_CANDIDATE"
                if all(full_checks.values())
                else "PROMISING_BUT_MIXED_NO_STRATEGY_B_CANDIDATE"
            ),
        }
    )
    result["hashes"].update(_write_phase("full", full_equity, full_trades))
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    _atomic_write(REPORT_PATH, _render(result))
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
