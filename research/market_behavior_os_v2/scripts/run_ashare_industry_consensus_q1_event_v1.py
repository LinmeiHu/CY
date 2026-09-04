#!/usr/bin/env python3
"""Replay the single frozen same-industry diffusion-Q1 event strategy."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
EXPERIMENT_ID = "ASHARE-INDUSTRY-CONSENSUS-Q1-EVENT-V1"
SPEC_PATH = PROGRAM / f"experiments/{EXPERIMENT_ID}_spec.json"
EQUITY_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_equity.csv"
TRADE_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_trades.csv"
RESULT_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_result.json"
REPORT_PATH = PROGRAM / f"reports/{EXPERIMENT_ID}_report.md"
EXPECTED_SPEC_SHA256 = "717c1b8bf5dfacbe9bbe6d5a549143ddd1e52b31396624904b185e36b3c900d5"
FAMILY = "industry_consensus_q1_event"
INITIAL_CAPITAL = 10_000_000.0
COHORT_DIVISOR = 2
EVALUATION_END = date(2023, 12, 28)


class IndustryConsensusError(RuntimeError):
    """Fail-closed same-industry Q1 event error."""


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
        raise IndustryConsensusError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise IndustryConsensusError("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_SINGLE_DATA_GENERATED_EVENT_TRANSLATION_BEFORE_REPLAY":
        raise IndustryConsensusError("spec is not frozen")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise IndustryConsensusError(f"bound input changed: {name}")
    return spec


def _plans(selection: pd.DataFrame, calendar: list[date]) -> pd.DataFrame:
    selection = selection.copy()
    same = selection.groupby("trade_date").industry.transform("nunique").eq(1)
    selection = selection.loc[same]
    calendar_index = {day: index for index, day in enumerate(calendar)}
    rows: list[dict[str, Any]] = []
    for item in selection.itertuples(index=False):
        signal_date = pd.Timestamp(item.trade_date).date()
        entry_index = calendar_index[signal_date] + 1
        due_index = entry_index + 20
        if due_index >= len(calendar):
            continue
        rows.append(
            {
                "family": FAMILY,
                "signal_date": signal_date,
                "symbol": item.symbol,
                "industry": str(item.industry),
                "entry_index": entry_index,
                "due_index": due_index,
                "horizon": 20,
            }
        )
    plans = pd.DataFrame(rows)
    if plans.empty or not plans.groupby("signal_date").size().eq(2).all():
        raise IndustryConsensusError("same-industry Q1 event breadth changed")
    return plans


def _replay(
    plans: pd.DataFrame,
    market_rows: pd.DataFrame,
    calendar: list[date],
    events: list[Any],
    ca: Any,
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
    lots: list[Any] = []
    turnover = 0.0
    planned_entries = 0
    entries = 0
    risk_blocked_entries = 0
    market_unexecutable_entries = 0
    capital_skipped_entries = 0
    completed = 0
    severe = 0
    forced_exits = 0
    forced_pending_days = 0
    cash_constrained_events = 0
    allocation_fractions: list[float] = []
    capacity: list[float] = []
    nav_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    start_index = int(plans.entry_index.min())
    if EVALUATION_END not in calendar:
        raise IndustryConsensusError("fixed evaluation end absent from market calendar")
    final_index = calendar.index(EVALUATION_END)

    for cal_index in range(start_index, final_index + 1):
        current_date = calendar[cal_index]
        for lot in lots:
            if lot.forced_effective_date is not None and current_date >= lot.forced_effective_date:
                raise IndustryConsensusError(
                    f"pre-effective exit failed:{lot.symbol}:{lot.forced_event_id}:"
                    f"{lot.forced_effective_date}"
                )
            row = row_map.get((lot.symbol, current_date))
            if row is None or not ca._holding_row_usable(row):
                raise IndustryConsensusError(
                    f"invalid holding row:{lot.symbol}:{current_date}"
                )
            if int(row.corporate_action_count or 0) > 0:
                action = ca.PRIOR.PRIOR._visible_action(row)
                if action is None:
                    raise IndustryConsensusError(
                        f"unresolved effective action:{lot.symbol}:{current_date}"
                    )
                multiplier, cash_per_share = action
                if multiplier != 1.0:
                    raise IndustryConsensusError(
                        f"share risk event reached effective date:{lot.symbol}:{current_date}"
                    )
                lot.action_cash += lot.shares * cash_per_share

        survivors: list[Any] = []
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
            proceeds = lot.action_cash + gross * (1.0 - ca.COST)
            cash += proceeds
            turnover += gross
            completed += 1
            payoff = float(proceeds / lot.invested_cost - 1.0)
            severe += int(payoff <= -0.10)
            forced_exits += int(forced)
            trade_rows.append(
                {
                    "symbol": lot.symbol,
                    "industry": lot.industry,
                    "exit_date": current_date,
                    "exit_reason": "FORCED" if forced else "DUE",
                    "invested_cost": lot.invested_cost,
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
        executable: list[tuple[Any, Any]] = []
        for plan in planned:
            row = row_map.get((plan.symbol, current_date))
            if ca._entry_blocked(plan.symbol, plan.signal_date, current_date, symbol_events):
                risk_blocked_entries += 1
                continue
            if (
                row is not None
                and ca.PRIOR._valid_market_row(row)
                and int(row.trade_status) == 1
                and bool(row.current_day_data_tradable)
                and not bool(row.buy_blocked_open)
            ):
                executable.append((plan, row))
        market_unexecutable_entries += len(planned) - len(executable)
        if planned:
            target_capital = pre_entry_nav / COHORT_DIVISOR
            cohort_capital = min(cash, target_capital) if cash > 0 else 0.0
            fraction = float(cohort_capital / target_capital)
            allocation_fractions.append(fraction)
            cash_constrained_events += int(fraction < 1.0 - 1e-10)
        else:
            cohort_capital = 0.0
        if executable and cohort_capital <= 0:
            capital_skipped_entries += len(executable)
        if executable and cohort_capital > 1e-8:
            allocation = cohort_capital / len(executable)
            for plan, row in executable:
                shares = allocation / (float(row.open) * (1.0 + ca.COST))
                gross = shares * float(row.open)
                invested = allocation
                cash -= invested
                turnover += gross
                lots.append(
                    ca.Lot(
                        plan.symbol,
                        str(plan.industry),
                        int(plan.due_index),
                        shares,
                        invested,
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
        raise IndustryConsensusError(
            f"trade conservation failed:open={len(lots)} entries={entries} exits={completed}"
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
        "turnover_multiple_initial_capital": float(turnover / INITIAL_CAPITAL),
        "event_dates": int(plans.signal_date.nunique()),
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
        "minimum_event_allocation_fraction": float(np.min(allocation_fractions)),
        "minimum_cash": float(equity.cash.min()),
        "mean_positions": float(equity.positions.mean()),
        "mean_industries": float(equity.industries.mean()),
        "mean_industry_hhi_invested_days": float(
            equity.loc[equity.positions > 0, "industry_hhi"].mean()
        ),
        "p10_capacity_cny_at_5pct_amount": float(np.quantile(capacity, 0.10)),
        "median_capacity_cny_at_5pct_amount": float(np.median(capacity)),
    }
    return result, equity, trades


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


def _comparison(candidate: dict[str, Any], reference: dict[str, Any]) -> dict[str, float]:
    return {
        "annualized_return_delta": float(
            candidate["annualized_return"] - reference["annualized_return"]
        ),
        "total_return_delta": float(candidate["total_return"] - reference["total_return"]),
        "maximum_drawdown_improvement": float(
            candidate["maximum_drawdown"] - reference["maximum_drawdown"]
        ),
        "daily_sharpe_delta": float(candidate["daily_sharpe"] - reference["daily_sharpe"]),
        "severe_trade_fraction_improvement": float(
            reference["severe_trade_fraction"] - candidate["severe_trade_fraction"]
        ),
    }


def _render(result: dict[str, Any]) -> str:
    candidate = result["candidate"]
    years = " | ".join(
        f"{year} {value:+.2%}" for year, value in result["calendar_year_returns"].items()
    )
    return "\n".join(
        [
            "# Industry-consensus diffusion-Q1 event V1",
            "",
            f"Status: `{result['status']}`.",
            "",
            (
                "On an unchanged weekly Champion signal, trade only when the two highest "
                "diffusion-intensity names share the same PIT industry. Allocate at most "
                "one-half NAV to that two-name cohort, enter next legal open, and exit at "
                "the unchanged h20 due open."
            ),
            "",
            (
                f"Annualized {candidate['annualized_return']:.2%}; total "
                f"{candidate['total_return']:.2%}; max drawdown "
                f"{candidate['maximum_drawdown']:.2%}; Sharpe "
                f"{candidate['daily_sharpe']:.3f}; Calmar {candidate['calmar']:.3f}."
            ),
            (
                f"Events {candidate['event_dates']}; trades {candidate['completed_trades']}; "
                f"cash-constrained events {candidate['cash_constrained_events']}; mean "
                f"event funding {candidate['mean_event_allocation_fraction']:.1%}."
            ),
            (
                f"Planned entries {candidate['planned_entries']}; capital-skipped entries "
                f"{candidate['capital_skipped_entries']}; market-unexecutable entries "
                f"{candidate['market_unexecutable_entries']}; severe trades "
                f"{candidate['severe_trade_fraction']:.2%}."
            ),
            (
                f"Mean invested-day industry HHI "
                f"{candidate['mean_industry_hhi_invested_days']:.3f}; p10/median capacity "
                f"at 5% of daily amount CNY "
                f"{candidate['p10_capacity_cny_at_5pct_amount'] / 1_000_000:.2f}m/"
                f"{candidate['median_capacity_cny_at_5pct_amount'] / 1_000_000:.2f}m."
            ),
            f"Calendar years: {years}.",
            "",
            (
                "This binary event and its capital translation were generated from consumed "
                "history. The result is development optimization, not independent validation. "
                "Post-2023 outcomes and CY-011 were not read."
            ),
            "",
        ]
    )


def run() -> dict[str, Any]:
    spec = _load_spec()
    q1 = _load_module("q1_for_industry_consensus", _resolve(spec["inputs"]["q1_runner"]["path"]))
    q1_spec = q1._load_spec()
    cycle016 = q1._load_module(
        "cycle016_for_industry_consensus",
        q1._resolve(q1_spec["inputs"]["champion_anatomy_runner"]["path"]),
    )
    selection = q1._selection(q1_spec, cycle016)
    ca = cycle016.CA
    ca_spec = ca._load_spec()
    paths, calendar, input_identity = ca._load_market_inputs(ca_spec)
    plans = _plans(selection, calendar)
    market_rows = ca.PRIOR._query_execution_rows(paths, plans, calendar)
    events, action_audit = ca._load_risk_events(ca_spec, calendar)
    candidate, equity, trades = _replay(plans, market_rows, calendar, events, ca)
    q1_result = json.loads(
        _resolve(spec["inputs"]["q1_result"]["path"]).read_text(encoding="utf-8")
    )
    champion = q1_result["baseline"]
    top2 = q1_result["candidate"]
    target = spec["success_target"]
    target_checks = {
        "annualized": candidate["annualized_return"] >= target["minimum_annualized_return"],
        "drawdown": candidate["maximum_drawdown"]
        > target["maximum_drawdown_must_be_greater_than"],
    }
    target_met = all(target_checks.values())
    status = "USER_TARGET_ACHIEVED" if target_met else "EVENT_TRANSLATION_TARGET_NOT_MET"
    _atomic_write(
        EQUITY_PATH,
        equity.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )
    _atomic_write(
        TRADE_PATH,
        trades.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )
    result = {
        "experiment_id": EXPERIMENT_ID,
        "status": status,
        "claim_boundary": spec["claim_boundary"],
        "post_2023_outcome_read": "NO",
        "cy011_read": "NO",
        "candidate": candidate,
        "comparison_vs_champion": _comparison(candidate, champion),
        "comparison_vs_q1_top2": _comparison(candidate, top2),
        "calendar_year_returns": _year_returns(equity),
        "target": target,
        "target_checks": target_checks,
        "target_met": target_met,
        "input_identity": input_identity,
        "action_audit": action_audit,
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "equity_sha256": sha256_file(EQUITY_PATH),
            "trades_sha256": sha256_file(TRADE_PATH),
        },
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    _atomic_write(REPORT_PATH, _render(result))
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
