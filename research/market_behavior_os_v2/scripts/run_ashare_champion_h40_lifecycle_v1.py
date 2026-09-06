#!/usr/bin/env python3
"""Replay the single frozen Champion h40 lifecycle with eight cohorts."""

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
EXPERIMENT_ID = "ASHARE-CHAMPION-H40-LIFECYCLE-V1"
SPEC_PATH = PROGRAM / f"experiments/{EXPERIMENT_ID}_spec.json"
EQUITY_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_equity.csv"
RESULT_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_result.json"
REPORT_PATH = PROGRAM / f"reports/{EXPERIMENT_ID}_report.md"
CYCLE016_PATH = PROGRAM / "scripts/run_ashare_champion_anatomy_cycle_016.py"
EXPECTED_SPEC_SHA256 = "8b37672470e12a729c029e648ee625736892924bb9655df4a8f81d3f2663f3d9"
FAMILY = "industry_diffusion_low_max_h40_eight_cohorts"
INITIAL_CAPITAL = 10_000_000.0
COHORT_DIVISOR = 8
HORIZON = 40


class H40LifecycleError(RuntimeError):
    """Fail-closed h40 lifecycle error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise H40LifecycleError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


CYCLE016 = _load_module("ashare_cycle016_for_h40", CYCLE016_PATH)
CONSTRUCTION = CYCLE016.CONSTRUCTION
CA = CYCLE016.CA


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise H40LifecycleError("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_SINGLE_NATURAL_HORIZON_EXTENSION_BEFORE_REPLAY":
        raise H40LifecycleError("spec is not frozen")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise H40LifecycleError(f"bound input changed: {name}")
    CYCLE016._load_spec()
    CA._load_spec()
    return spec


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


def _make_h40_plans(selections: pd.DataFrame, calendar: list[date]) -> pd.DataFrame:
    index = {day: position for position, day in enumerate(calendar)}
    rows: list[dict[str, Any]] = []
    for item in selections.itertuples(index=False):
        signal_date = pd.Timestamp(item.trade_date).date()
        entry_index = index[signal_date] + 1
        due_index = entry_index + HORIZON
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
                "horizon": HORIZON,
            }
        )
    plans = pd.DataFrame(rows)
    counts = plans.groupby(["family", "signal_date"]).size()
    if plans.empty or not counts.eq(10).all():
        raise H40LifecycleError("h40 plan breadth changed")
    return plans


def _replay_h40(
    plans: pd.DataFrame,
    market_rows: pd.DataFrame,
    calendar: list[date],
    events: list[Any],
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    row_map = {
        (row.symbol, pd.Timestamp(row.trade_date).date()): row
        for row in market_rows.itertuples(index=False)
    }
    entry_map = {
        int(index): list(group.itertuples(index=False))
        for index, group in plans.groupby("entry_index", sort=True)
    }
    event_decisions, symbol_events = CA._event_maps(events)
    cash = INITIAL_CAPITAL
    lots: list[Any] = []
    turnover = 0.0
    planned_entries = 0
    entries = 0
    risk_blocked_entries = 0
    completed = 0
    severe = 0
    forced_exits = 0
    forced_pending_days = 0
    capacity: list[float] = []
    nav_rows: list[dict[str, Any]] = []
    exit_rows: list[dict[str, Any]] = []
    start_index = int(plans.entry_index.min())
    final_due = int(plans.due_index.max())
    final_index = min(final_due + 20, len(calendar) - 1)

    for cal_index in range(start_index, final_index + 1):
        current_date = calendar[cal_index]
        for lot in lots:
            if lot.forced_effective_date is not None and current_date >= lot.forced_effective_date:
                raise H40LifecycleError(
                    f"pre-effective exit failed:{lot.symbol}:{lot.forced_event_id}:"
                    f"{lot.forced_effective_date}"
                )
            row = row_map.get((lot.symbol, current_date))
            if row is None or not CA._holding_row_usable(row):
                raise H40LifecycleError(
                    f"invalid holding row:{lot.symbol}:{current_date}"
                )
            if int(row.corporate_action_count or 0) > 0:
                action = CA.PRIOR.PRIOR._visible_action(row)
                if action is None:
                    raise H40LifecycleError(
                        f"unresolved effective action:{lot.symbol}:{current_date}"
                    )
                multiplier, cash_per_share = action
                if multiplier != 1.0:
                    raise H40LifecycleError(
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
            if not CA._sellable(row):
                forced_pending_days += int(forced)
                survivors.append(lot)
                continue
            gross = lot.shares * float(row.open)
            proceeds = lot.action_cash + gross * (1.0 - CA.COST)
            cash += proceeds
            turnover += gross
            completed += 1
            severe += int(proceeds / lot.invested_cost - 1.0 <= -0.10)
            forced_exits += int(forced)
            if forced:
                exit_rows.append(
                    {
                        "family": FAMILY,
                        "symbol": lot.symbol,
                        "event_id": lot.forced_event_id,
                        "effective_date": lot.forced_effective_date,
                        "fill_date": current_date,
                        "fill_price": float(row.open),
                        "shares": lot.shares,
                    }
                )
        lots = survivors

        pre_entry_nav = cash + sum(
            lot.action_cash
            + lot.shares * float(row_map[(lot.symbol, current_date)].open)
            for lot in lots
        )
        planned = entry_map.get(cal_index, [])
        planned_entries += len(planned)
        executable: list[tuple[Any, Any]] = []
        for plan in planned:
            row = row_map.get((plan.symbol, current_date))
            if CA._entry_blocked(
                plan.symbol, plan.signal_date, current_date, symbol_events
            ):
                risk_blocked_entries += 1
                continue
            if (
                row is not None
                and CA.PRIOR._valid_market_row(row)
                and int(row.trade_status) == 1
                and bool(row.current_day_data_tradable)
                and not bool(row.buy_blocked_open)
            ):
                executable.append((plan, row))
        cohort_capital = min(cash, pre_entry_nav / COHORT_DIVISOR)
        if executable:
            allocation = cohort_capital / len(executable)
            for plan, row in executable:
                shares = allocation / (float(row.open) * (1.0 + CA.COST))
                gross = shares * float(row.open)
                invested = gross * (1.0 + CA.COST)
                cash -= invested
                turnover += gross
                lots.append(
                    CA.Lot(
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
        if cal_index >= final_due and not lots and cal_index not in entry_map:
            break

    equity = pd.DataFrame(nav_rows)
    if lots:
        raise H40LifecycleError(f"terminal open lots:{len(lots)}")
    returns = equity.nav.pct_change().fillna(
        equity.nav.iloc[0] / INITIAL_CAPITAL - 1.0
    )
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
        "excess_return_vs_cash": float(equity.nav.iloc[-1] / INITIAL_CAPITAL - 1.0),
        "annualized_return": float(annualized),
        "maximum_drawdown": maximum_drawdown,
        "daily_sharpe": float(sharpe),
        "calmar": float(annualized / abs(maximum_drawdown))
        if maximum_drawdown < 0
        else None,
        "turnover_multiple_initial_capital": float(turnover / INITIAL_CAPITAL),
        "planned_entries": planned_entries,
        "entries": entries,
        "entry_execution_fraction": float(entries / planned_entries),
        "risk_blocked_entries": risk_blocked_entries,
        "completed_trades": completed,
        "severe_trade_fraction": float(severe / completed),
        "forced_pre_effective_exits": forced_exits,
        "forced_exit_pending_days": forced_pending_days,
        "terminal_open_lots": len(lots),
        "mean_positions": float(equity.positions.mean()),
        "mean_industries": float(equity.industries.mean()),
        "mean_industry_hhi_invested_days": float(
            equity.loc[equity.positions > 0, "industry_hhi"].mean()
        ),
        "p10_capacity_cny_at_5pct_amount": float(np.quantile(capacity, 0.10)),
        "median_capacity_cny_at_5pct_amount": float(np.median(capacity)),
    }
    return result, equity, pd.DataFrame(exit_rows)


def _baseline(spec: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(
        _resolve(spec["inputs"]["champion_authoritative_result"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    return result["track_a"]["matched_cost_comparisons"]["20bps"]["low_max"]


def _comparison(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, float]:
    return {
        "total_return_delta": float(candidate["total_return"] - baseline["total_return"]),
        "annualized_return_delta": float(
            candidate["annualized_return"] - baseline["annualized_return"]
        ),
        "maximum_drawdown_improvement": float(
            candidate["maximum_drawdown"] - baseline["maximum_drawdown"]
        ),
        "daily_sharpe_delta": float(candidate["daily_sharpe"] - baseline["daily_sharpe"]),
        "severe_trade_fraction_improvement": float(
            baseline["severe_trade_fraction"] - candidate["severe_trade_fraction"]
        ),
    }


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


def _render(result: dict[str, Any]) -> str:
    baseline = result["baseline"]
    candidate = result["candidate"]
    delta = result["comparison"]
    return "\n".join(
        [
            "# Champion h40 lifecycle V1",
            "",
            f"Status: `{result['status']}`.",
            "",
            (
                "The exact weekly Industry Diffusion plus Low-MAX Top-10 is entered "
                "at the next legal open, held 40 sessions, and funded as eight equal "
                "overlapping cohort budgets without borrowing."
            ),
            "",
            (
                f"Baseline h20: annualized {baseline['annualized_return']:.2%}, max "
                f"drawdown {baseline['maximum_drawdown']:.2%}, Sharpe "
                f"{baseline['daily_sharpe']:.3f}."
            ),
            (
                f"Candidate h40: annualized {candidate['annualized_return']:.2%}, max "
                f"drawdown {candidate['maximum_drawdown']:.2%}, Sharpe "
                f"{candidate['daily_sharpe']:.3f}."
            ),
            (
                f"Annualized delta {delta['annualized_return_delta']:+.2%}; drawdown "
                f"quality delta {delta['maximum_drawdown_improvement']:+.2%}; target "
                f"met `{result['target_met']}`."
            ),
            "",
            (
                "No neighboring horizon, entry rule, stop, market state, rank change, "
                "or rescue was tested. This is consumed-history development evidence, "
                "not independent confirmation. Post-2023 outcomes and CY-011 were not read."
            ),
            "",
        ]
    )


def run() -> dict[str, Any]:
    spec = _load_spec()
    ca_spec = CA._load_spec()
    paths, calendar, input_identity = CA._load_market_inputs(ca_spec)
    anatomy_spec = json.loads(
        _resolve(spec["inputs"]["champion_anatomy_spec"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    daily = pd.read_parquet(
        _resolve(anatomy_spec["inputs"]["causal_daily_panel"]["path"])
    )
    construction_spec = CONSTRUCTION._load_spec()
    _, champion = CYCLE016.CYCLE015._weekly_selections(daily, construction_spec)
    plans = _make_h40_plans(champion, calendar)
    market_rows = CA.PRIOR._query_execution_rows(paths, plans, calendar)
    events, action_audit = CA._load_risk_events(ca_spec, calendar)
    candidate, equity, exits = _replay_h40(plans, market_rows, calendar, events)
    baseline = _baseline(spec)
    comparison = _comparison(candidate, baseline)
    target = spec["success_target"]
    target_met = bool(
        candidate["annualized_return"] >= target["minimum_annualized_return"]
        and candidate["maximum_drawdown"]
        > target["maximum_drawdown_must_be_greater_than"]
    )
    status = "TARGET_ACHIEVED" if target_met else "H40_TARGET_NOT_MET"
    _atomic_write(
        EQUITY_PATH,
        equity.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )
    result = {
        "experiment_id": EXPERIMENT_ID,
        "status": status,
        "claim_boundary": spec["claim_boundary"],
        "post_2023_outcome_read": "NO",
        "cy011_read": "NO",
        "frozen_horizon": HORIZON,
        "cohort_divisor": COHORT_DIVISOR,
        "baseline": baseline,
        "candidate": candidate,
        "comparison": comparison,
        "calendar_year_returns": _year_returns(equity),
        "forced_exit_rows": len(exits),
        "input_identity": input_identity,
        "action_audit": action_audit,
        "target": target,
        "target_met": target_met,
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "equity_sha256": sha256_file(EQUITY_PATH),
        },
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    _atomic_write(REPORT_PATH, _render(result))
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
