#!/usr/bin/env python3
"""Test one PIT positive-industry-breadth risk overlay for the frozen champion."""

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

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-OPPORTUNITY-HEALTH-OVERLAY-CYCLE-018_spec.json"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-OPPORTUNITY-HEALTH-OVERLAY-CYCLE-018_result.json"
STATE_PATH = PROGRAM / "artifacts/ASHARE-OPPORTUNITY-HEALTH-OVERLAY-CYCLE-018_states.csv"
PHASE_A_PATH = PROGRAM / "artifacts/ASHARE-OPPORTUNITY-HEALTH-OVERLAY-CYCLE-018_phase_a.csv"
ANNUAL_PATH = PROGRAM / "artifacts/ASHARE-OPPORTUNITY-HEALTH-OVERLAY-CYCLE-018_annual.csv"
REPORT_PATH = PROGRAM / "reports/ASHARE-OPPORTUNITY-HEALTH-OVERLAY-CYCLE-018_report.md"
EXTERNAL_ROOT = Path("/Volumes/quant/CY_quant_research/opportunity_health_overlay_cycle_018")
OVERLAY_EQUITY_PATH = EXTERNAL_ROOT / "overlay_equity.parquet"
OVERLAY_TRADES_PATH = EXTERNAL_ROOT / "overlay_trades.parquet"
EXPECTED_SPEC_SHA256 = "a26a8be426c8cc9bb270170ec231b14c0ffb8554b0e932960c0df5b4c57b2aa7"
INITIAL_CAPITAL = 10_000_000.0
COST = 0.002
SEVERE = -0.10
EXPOSURE = {"LOW": 0.50, "MEDIUM": 0.75, "HIGH": 1.00}
YEARS = tuple(range(2018, 2024))
LOSING_YEARS = (2018, 2022)
PROFITABLE_YEARS = (2019, 2020, 2021, 2023)


class OpportunityOverlayError(RuntimeError):
    """Fail-closed Cycle 018 error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


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


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise OpportunityOverlayError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


FAILURE = _load_module(
    "cycle017_for_overlay018",
    PROGRAM / "scripts/run_ashare_champion_failure_anatomy_cycle_017.py",
)
ANATOMY = FAILURE.ANATOMY
CA = ANATOMY.CA
CYCLE015 = ANATOMY.CYCLE015
CONSTRUCTION = ANATOMY.CONSTRUCTION


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise OpportunityOverlayError("frozen Cycle-018 spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_OPPORTUNITY_STATE_OR_OVERLAY_OUTCOMES":
        raise OpportunityOverlayError("Cycle-018 contract was not frozen before outcomes")
    for role, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise OpportunityOverlayError(f"bound input changed: {role}")
    if spec["champion"]["selection_changes_authorized"] is not False:
        raise OpportunityOverlayError("overlay contract changes the Alpha engine")
    if spec["overlay"]["exposure_mapping"] != {"LOW": 0.5, "MEDIUM": 0.75, "HIGH": 1.0}:
        raise OpportunityOverlayError("exposure mapping changed")
    return spec


def _state(value: float) -> str:
    if value < 1.0 / 3.0:
        return "LOW"
    if value < 2.0 / 3.0:
        return "MEDIUM"
    return "HIGH"


def _opportunity_states(daily_paths: list[Path], signal_dates: set[date]) -> pd.DataFrame:
    frame = pd.concat(
        [
            pd.read_parquet(
                path,
                columns=[
                    "trade_date",
                    "industry",
                    "close",
                    "preclose",
                    "hard_valid",
                    "industry_valid",
                ],
            )
            for path in daily_paths
        ],
        ignore_index=True,
    )
    frame = frame.loc[
        frame.hard_valid.astype(bool)
        & frame.industry_valid.astype(bool)
        & frame.industry.notna()
        & frame.close.gt(0)
        & frame.preclose.gt(0)
    ].copy()
    frame["step_return"] = frame.close / frame.preclose - 1.0
    frame = frame[["trade_date", "industry", "step_return"]]
    frame["trade_date"] = pd.to_datetime(frame.trade_date).dt.date
    industry_daily = frame.groupby(["industry", "trade_date"], as_index=False).agg(
        industry_return=("step_return", "mean")
    )
    industry_daily = industry_daily.sort_values(["industry", "trade_date"])
    industry_daily["log_return"] = np.log1p(industry_daily.industry_return)
    industry_daily["industry_return20"] = (
        industry_daily.groupby("industry", sort=False).log_return.rolling(20, min_periods=20).sum()
        .reset_index(level=0, drop=True)
        .pipe(np.expm1)
    )
    weekly = industry_daily.loc[industry_daily.trade_date.isin(signal_dates)]
    rows: list[dict[str, Any]] = []
    for signal_date, group in weekly.groupby("trade_date", sort=True):
        complete = group.loc[np.isfinite(group.industry_return20)]
        if len(complete) < 50:
            raise OpportunityOverlayError(
                f"fewer than 50 complete industries at decision: {signal_date}"
            )
        breadth = float((complete.industry_return20 > 0).mean())
        rows.append(
            {
                "signal_date": signal_date,
                "year": signal_date.year,
                "block": "early" if signal_date.year <= 2020 else "late",
                "complete_industries": len(complete),
                "positive_industries": int((complete.industry_return20 > 0).sum()),
                "positive_industry_breadth": breadth,
                "state": _state(breadth),
                "exposure_scale": EXPOSURE[_state(breadth)],
            }
        )
    output = pd.DataFrame(rows).sort_values("signal_date").reset_index(drop=True)
    if set(output.signal_date) != signal_dates:
        raise OpportunityOverlayError("opportunity state does not cover every frozen decision")
    return output


def _phase_a(
    states: pd.DataFrame,
    trades: pd.DataFrame,
    industry_paths: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    merged = trades.drop(columns=["block"], errors="ignore").merge(
        states, on="signal_date", validate="many_to_one"
    )
    cohorts = merged.groupby(["signal_date", "year", "block", "state"], as_index=False).agg(
        profit=("profit", "sum"), invested=("invested_cost", "sum")
    )
    cohorts["cohort_payoff"] = cohorts.profit / cohorts.invested
    paths = industry_paths.loc[industry_paths.checkpoint.eq(20)].copy()
    paths["signal_date"] = pd.to_datetime(paths.signal_date).dt.date
    path_by_date = paths.groupby("signal_date", as_index=False).agg(
        selected_industry_return=("industry_return", "mean"),
        broad_proxy_return=("market_return", "mean"),
    )
    cohorts = cohorts.merge(path_by_date, on="signal_date", how="left", validate="one_to_one")
    rows: list[dict[str, Any]] = []
    for state, state_trades in merged.groupby("state", sort=True):
        state_cohorts = cohorts.loc[cohorts.state.eq(state)]
        for period in ("full", "early", "late"):
            trade_group = (
                state_trades
                if period == "full"
                else state_trades.loc[state_trades.block.eq(period)]
            )
            cohort_group = (
                state_cohorts
                if period == "full"
                else state_cohorts.loc[state_cohorts.block.eq(period)]
            )
            rows.append(
                {
                    "state": state,
                    "period": period,
                    "decision_dates": int(cohort_group.signal_date.nunique()),
                    "cohorts": len(cohort_group),
                    "trades": len(trade_group),
                    "mean_cohort_payoff": float(cohort_group.cohort_payoff.mean()),
                    "pooled_absolute_return": float(
                        trade_group.profit.sum() / trade_group.invested_cost.sum()
                    ),
                    "winner_fraction": float((trade_group.final_net_return > 0).mean()),
                    "severe_fraction": float((trade_group.final_net_return <= SEVERE).mean()),
                    "selected_industry_return": float(
                        cohort_group.selected_industry_return.mean()
                    ),
                    "broad_proxy_return": float(cohort_group.broad_proxy_return.mean()),
                }
            )
    panel = pd.DataFrame(rows)
    indexed = panel.set_index(["state", "period"])
    full = panel.loc[panel.period.eq("full")].set_index("state")
    yearly = cohorts.groupby(["year", "state"], as_index=False).agg(
        decision_dates=("signal_date", "nunique"),
        mean_cohort_payoff=("cohort_payoff", "mean"),
    )
    comparisons = 0
    yearly_rows: list[dict[str, Any]] = []
    for year, group in cohorts.groupby("year", sort=True):
        low = group.loc[group.state.eq("LOW"), "cohort_payoff"]
        nonlow = group.loc[~group.state.eq("LOW"), "cohort_payoff"]
        comparison = bool(not low.empty and not nonlow.empty and low.mean() < nonlow.mean())
        comparisons += int(comparison)
        yearly_rows.append(
            {
                "year": int(year),
                "low_dates": int(group.loc[group.state.eq("LOW"), "signal_date"].nunique()),
                "medium_dates": int(
                    group.loc[group.state.eq("MEDIUM"), "signal_date"].nunique()
                ),
                "high_dates": int(group.loc[group.state.eq("HIGH"), "signal_date"].nunique()),
                "low_mean_payoff": float(low.mean()) if not low.empty else math.nan,
                "nonlow_mean_payoff": float(nonlow.mean()) if not nonlow.empty else math.nan,
                "low_worse": comparison,
            }
        )
    state_2023 = states.loc[states.year.eq(2023)]
    checks = {
        "minimum_dates": bool((full.decision_dates >= 20).all()),
        "high_minus_low": bool(
            full.loc["HIGH", "mean_cohort_payoff"]
            - full.loc["LOW", "mean_cohort_payoff"]
            >= 0.005
        ),
        "monotonic_full": bool(
            full.loc["LOW", "mean_cohort_payoff"]
            < full.loc["MEDIUM", "mean_cohort_payoff"]
            < full.loc["HIGH", "mean_cohort_payoff"]
        ),
        "both_blocks": all(
            indexed.loc[("LOW", period), "mean_cohort_payoff"]
            < indexed.loc[("HIGH", period), "mean_cohort_payoff"]
            for period in ("early", "late")
        ),
        "high_positive": all(
            indexed.loc[("HIGH", period), "mean_cohort_payoff"] > 0
            for period in ("full", "early", "late")
        ),
        "four_years": comparisons >= 4,
        "2023_not_mechanically_low": bool((state_2023.state != "LOW").mean() >= 0.25),
    }
    return panel, {
        "authorized": all(checks.values()),
        "gate": checks,
        "high_minus_low_cohort_payoff": float(
            full.loc["HIGH", "mean_cohort_payoff"] - full.loc["LOW", "mean_cohort_payoff"]
        ),
        "yearly_state_distribution": yearly_rows,
        "year_state_rows": yearly.to_dict(orient="records"),
        "rows": rows,
    }


@dataclass
class OverlayLot:
    trade_id: str
    signal_date: date
    symbol: str
    industry: str
    entry_index: int
    due_index: int
    shares: float
    invested_cost: float
    entry_date: date
    exposure_scale: float
    capacity_cny: float
    action_cash: float = 0.0
    forced_effective_date: date | None = None


def _replay_overlay(
    plans: pd.DataFrame,
    market_rows: pd.DataFrame,
    calendar: list[date],
    events: list[Any],
    states: pd.DataFrame,
    authoritative_ids: set[str],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    row_map = {
        (row.symbol, pd.Timestamp(row.trade_date).date()): row
        for row in market_rows.itertuples(index=False)
    }
    entry_map = {
        int(index): list(group.itertuples(index=False))
        for index, group in plans.groupby("entry_index", sort=True)
    }
    scale_map = states.set_index("signal_date").exposure_scale.to_dict()
    event_decisions, symbol_events = CA._event_maps(events)
    cash = INITIAL_CAPITAL
    lots: list[OverlayLot] = []
    records: list[dict[str, Any]] = []
    nav_rows: list[dict[str, Any]] = []
    turnover = 0.0
    entries = 0
    planned_entries = 0
    forced_exits = 0
    risk_blocked = 0
    capacity: list[float] = []
    start_index = int(plans.entry_index.min())
    final_due = int(plans.due_index.max())
    final_index = min(final_due + 20, len(calendar) - 1)

    for cal_index in range(start_index, final_index + 1):
        current_date = calendar[cal_index]
        for lot in lots:
            if lot.forced_effective_date is not None and current_date >= lot.forced_effective_date:
                raise OpportunityOverlayError(f"pre-effective exit failed: {lot.trade_id}")
            row = row_map.get((lot.symbol, current_date))
            if row is None or not CA._holding_row_usable(row):
                raise OpportunityOverlayError(f"invalid holding row: {lot.trade_id}:{current_date}")
            if int(row.corporate_action_count or 0) > 0:
                action = CA.PRIOR.PRIOR._visible_action(row)
                if action is None:
                    raise OpportunityOverlayError(f"unresolved action: {lot.trade_id}")
                multiplier, cash_per_share = action
                if multiplier != 1.0:
                    raise OpportunityOverlayError(
                        f"share action reached effective date: {lot.trade_id}"
                    )
                lot.action_cash += lot.shares * cash_per_share

        survivors: list[OverlayLot] = []
        for lot in lots:
            row = row_map[(lot.symbol, current_date)]
            forced = lot.forced_effective_date is not None
            due = cal_index >= lot.due_index
            if not forced and not due:
                survivors.append(lot)
                continue
            if not CA._sellable(row):
                survivors.append(lot)
                continue
            gross = lot.shares * float(row.open)
            proceeds = lot.action_cash + gross * (1.0 - COST)
            cash += proceeds
            turnover += gross
            payoff = proceeds / lot.invested_cost - 1.0
            records.append(
                {
                    "trade_id": lot.trade_id,
                    "signal_date": lot.signal_date,
                    "entry_date": lot.entry_date,
                    "exit_date": current_date,
                    "symbol": lot.symbol,
                    "industry": lot.industry,
                    "exposure_scale": lot.exposure_scale,
                    "invested_cost": lot.invested_cost,
                    "profit": lot.invested_cost * payoff,
                    "final_net_return": payoff,
                    "holding_sessions": cal_index - lot.entry_index,
                    "exit_reason": "FORCED_PRE_EFFECTIVE" if forced else "DUE",
                    "capacity_cny": lot.capacity_cny,
                }
            )
            forced_exits += int(forced)
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
            if CA._entry_blocked(plan.symbol, plan.signal_date, current_date, symbol_events):
                risk_blocked += 1
                continue
            if row is not None and CYCLE015._buyable(row):
                executable.append((plan, row))
        if planned:
            scale = float(scale_map[planned[0].signal_date])
            if any(scale_map[item.signal_date] != scale for item in planned):
                raise OpportunityOverlayError("mixed exposure scale inside cohort")
        else:
            scale = 1.0
        cohort_capital = min(cash, pre_entry_nav / 4.0 * scale)
        if executable:
            allocation = cohort_capital / len(executable)
            for plan, row in executable:
                shares = allocation / (float(row.open) * (1.0 + COST))
                gross = shares * float(row.open)
                invested = gross * (1.0 + COST)
                cash -= invested
                turnover += gross
                capacity_cny = float(row.amount) * 0.05 * len(executable) * 4 / scale
                lot = OverlayLot(
                    trade_id=f"{plan.signal_date}|{plan.symbol}",
                    signal_date=plan.signal_date,
                    symbol=plan.symbol,
                    industry=str(plan.industry),
                    entry_index=cal_index,
                    due_index=int(plan.due_index),
                    shares=shares,
                    invested_cost=invested,
                    entry_date=current_date,
                    exposure_scale=scale,
                    capacity_cny=capacity_cny,
                )
                lots.append(lot)
                entries += 1
                capacity.append(capacity_cny)

        for lot in lots:
            for event in event_decisions.get((lot.symbol, current_date), ()):
                if (
                    lot.forced_effective_date is None
                    or event.effective_date < lot.forced_effective_date
                ):
                    lot.forced_effective_date = event.effective_date

        nav = cash
        gross_value = 0.0
        for lot in lots:
            row = row_map[(lot.symbol, current_date)]
            value = lot.action_cash + lot.shares * float(row.close)
            nav += value
            gross_value += value
        nav_rows.append(
            {
                "trade_date": current_date,
                "nav": nav,
                "cash": cash,
                "gross_value": gross_value,
                "gross_exposure": gross_value / nav,
                "cash_fraction": cash / nav,
                "positions": len(lots),
            }
        )
        if cal_index >= final_due and not lots and cal_index not in entry_map:
            break
    if lots:
        raise OpportunityOverlayError(f"terminal open lots: {len(lots)}")
    trades = pd.DataFrame(records).sort_values(["signal_date", "symbol"])
    equity = pd.DataFrame(nav_rows)
    if set(trades.trade_id) != authoritative_ids:
        raise OpportunityOverlayError("overlay changed frozen executed stock identities")
    returns = equity.nav.pct_change().fillna(equity.nav.iloc[0] / INITIAL_CAPITAL - 1.0)
    drawdown = equity.nav / equity.nav.cummax() - 1.0
    years = len(equity) / 252.0
    annualized = (equity.nav.iloc[-1] / INITIAL_CAPITAL) ** (1.0 / years) - 1.0
    replay = {
        "total_return": float(equity.nav.iloc[-1] / INITIAL_CAPITAL - 1.0),
        "annualized_return": float(annualized),
        "maximum_drawdown": float(drawdown.min()),
        "daily_sharpe": float(math.sqrt(252) * returns.mean() / returns.std(ddof=1)),
        "calmar": float(annualized / abs(drawdown.min())),
        "severe_trade_fraction": float((trades.final_net_return <= SEVERE).mean()),
        "average_gross_exposure": float(equity.gross_exposure.mean()),
        "average_cash_fraction": float(equity.cash_fraction.mean()),
        "turnover_multiple_initial_capital": float(turnover / INITIAL_CAPITAL),
        "alpha_per_unit_gross": float(annualized / equity.gross_exposure.mean()),
        "alpha_per_turnover": float(
            (equity.nav.iloc[-1] / INITIAL_CAPITAL - 1.0) / (turnover / INITIAL_CAPITAL)
        ),
        "planned_entries": planned_entries,
        "entries": entries,
        "entry_execution_fraction": float(entries / planned_entries),
        "completed_trades": len(trades),
        "forced_pre_effective_exits": forced_exits,
        "risk_blocked_entries": risk_blocked,
        "p10_capacity_cny_at_5pct_amount": float(np.quantile(capacity, 0.10)),
        "terminal_open_lots": 0,
    }
    return trades, equity, replay


def _equity_metrics(equity: pd.DataFrame) -> dict[str, Any]:
    frame = equity.copy()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    previous = frame.nav.shift(1).fillna(INITIAL_CAPITAL)
    frame["daily_return"] = frame.nav / previous - 1.0
    returns = frame.daily_return
    drawdown = frame.nav / frame.nav.cummax() - 1.0
    years = len(frame) / 252.0
    annualized = (frame.nav.iloc[-1] / INITIAL_CAPITAL) ** (1.0 / years) - 1.0
    gross = (
        frame.gross_exposure
        if "gross_exposure" in frame
        else (frame.nav - frame.cash) / frame.nav
    )
    return {
        "total_return": float(frame.nav.iloc[-1] / INITIAL_CAPITAL - 1.0),
        "annualized_return": float(annualized),
        "maximum_drawdown": float(drawdown.min()),
        "daily_sharpe": float(math.sqrt(252) * returns.mean() / returns.std(ddof=1)),
        "calmar": float(annualized / abs(drawdown.min())),
        "average_gross_exposure": float(gross.mean()),
        "average_cash_fraction": float(1.0 - gross.mean()),
    }


def _annual_comparison(
    champion_equity: pd.DataFrame,
    overlay_equity: pd.DataFrame,
    states: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    frames: dict[str, pd.DataFrame] = {}
    for name, source in (("champion", champion_equity), ("overlay", overlay_equity)):
        frame = source.copy()
        frame["trade_date"] = pd.to_datetime(frame.trade_date)
        frame = frame.sort_values("trade_date")
        frame["daily_return"] = frame.nav / frame.nav.shift(1).fillna(INITIAL_CAPITAL) - 1.0
        frame["year"] = frame.trade_date.dt.year
        if "gross_exposure" not in frame:
            frame["gross_exposure"] = (frame.nav - frame.cash) / frame.nav
        frames[name] = frame
    for year in YEARS:
        champion = frames["champion"].loc[frames["champion"].year.eq(year)]
        overlay = frames["overlay"].loc[frames["overlay"].year.eq(year)]
        state = states.loc[states.year.eq(year)]
        champion_return = float(np.prod(1.0 + champion.daily_return) - 1.0)
        overlay_return = float(np.prod(1.0 + overlay.daily_return) - 1.0)
        rows.append(
            {
                "year": year,
                "champion_return": champion_return,
                "overlay_return": overlay_return,
                "return_difference": overlay_return - champion_return,
                "champion_maximum_drawdown": FAILURE._drawdown(champion.daily_return),
                "overlay_maximum_drawdown": FAILURE._drawdown(overlay.daily_return),
                "champion_average_gross": float(champion.gross_exposure.mean()),
                "overlay_average_gross": float(overlay.gross_exposure.mean()),
                "low_fraction": float(state.state.eq("LOW").mean()),
                "medium_fraction": float(state.state.eq("MEDIUM").mean()),
                "high_fraction": float(state.state.eq("HIGH").mean()),
                "mean_new_cohort_scale": float(state.exposure_scale.mean()),
            }
        )
    return pd.DataFrame(rows)


def _classify(
    phase_a: dict[str, Any],
    champion: dict[str, Any],
    overlay: dict[str, Any] | None,
    annual: pd.DataFrame | None,
) -> tuple[str, dict[str, Any]]:
    if not phase_a["authorized"]:
        return "OPPORTUNITY_HEALTH_NOT_USEFUL", {"overlay_run": False}
    if overlay is None or annual is None:
        raise OpportunityOverlayError("authorized overlay is missing")
    losing_improvement = float(
        annual.loc[annual.year.isin(LOSING_YEARS), "return_difference"].sum()
    )
    profitable_sacrifice = float(
        -annual.loc[annual.year.isin(PROFITABLE_YEARS), "return_difference"].sum()
    )
    ratio = (
        profitable_sacrifice / losing_improvement
        if losing_improvement > 0
        else math.inf
    )
    drawdown_improvement = overlay["maximum_drawdown"] - champion["maximum_drawdown"]
    sharpe_improvement = overlay["daily_sharpe"] - champion["daily_sharpe"]
    calmar_improvement = overlay["calmar"] - champion["calmar"]
    diagnostics = {
        "overlay_run": True,
        "losing_year_return_improvement": losing_improvement,
        "profitable_year_return_sacrifice": profitable_sacrifice,
        "sacrifice_per_loss_avoided": ratio,
        "drawdown_improvement": drawdown_improvement,
        "sharpe_improvement": sharpe_improvement,
        "calmar_improvement": calmar_improvement,
    }
    if losing_improvement <= 0 or drawdown_improvement <= 0:
        classification = "OVERLAY_DEGRADES_CHAMPION"
    elif (
        losing_improvement >= 0.03
        and drawdown_improvement >= 0.02
        and (sharpe_improvement >= 0.05 or calmar_improvement >= 0.05)
        and ratio <= 1.5
    ):
        classification = "OPPORTUNITY_HEALTH_OVERLAY_EARNS_COMPLEXITY"
    else:
        classification = "USEFUL_BUT_TOO_COSTLY_IN_UPSIDE"
    return classification, diagnostics


def _fmt(value: float) -> str:
    return f"{value:.2%}"


def _render_report(result: dict[str, Any]) -> str:
    phase_rows = {
        (row["state"], row["period"]): row for row in result["phase_a"]["rows"]
    }
    lines = [
        "# Cycle 018 — opportunity-health risk overlay",
        "",
        "## Executive conclusion",
        "",
        result["executive_conclusion"],
        "",
        f"Classification: `{result['classification']}`.",
        "",
        (
            "The frozen champion's stock selection, weekly clock, Top-10 construction, "
            "weighting within invested cohorts, 20-session lifecycle, and execution "
            "semantics were not changed."
        ),
        "",
        "## Phase A — opportunity-health diagnosis",
        "",
        (
            "`POSITIVE_INDUSTRY_BREADTH` is the fraction of PIT industries with a "
            "positive equal-weight 20-session absolute return at the completed weekly "
            "decision close. Fixed states are LOW below 1/3, MEDIUM from 1/3 to below "
            "2/3, and HIGH at least 2/3."
        ),
        "",
        (
            "| State | Dates | Cohort payoff | Absolute trade return | Winner | Severe | "
            "Selected-industry d20 | Broad d20 | Early/late cohort |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for state in ("LOW", "MEDIUM", "HIGH"):
        full = phase_rows[(state, "full")]
        early = phase_rows[(state, "early")]
        late = phase_rows[(state, "late")]
        lines.append(
            f"| {state} | {full['decision_dates']} | {_fmt(full['mean_cohort_payoff'])} | "
            f"{_fmt(full['pooled_absolute_return'])} | {_fmt(full['winner_fraction'])} | "
            f"{_fmt(full['severe_fraction'])} | {_fmt(full['selected_industry_return'])} | "
            f"{_fmt(full['broad_proxy_return'])} | {_fmt(early['mean_cohort_payoff'])}/"
            f"{_fmt(late['mean_cohort_payoff'])} |"
        )
    lines.extend(
        [
            "",
            f"Phase-A gate: `{result['phase_a']['authorized']}` — "
            f"{result['phase_a']['gate']}.",
        ]
    )
    lines.extend(["", "## 2022 versus 2023", ""])
    yearly = {row["year"]: row for row in result["phase_a"]["yearly_state_distribution"]}
    for year in (2022, 2023):
        row = yearly[year]
        path = result["year_contrast"][str(year)]
        suffix = (
            f"mean frozen new-cohort exposure {_fmt(path['mean_new_cohort_scale'])}."
            if result["overlay"] is not None
            else "the Phase-A failure prohibited exposure scaling."
        )
        lines.append(
            f"- {year}: LOW/MEDIUM/HIGH dates {row['low_dates']}/{row['medium_dates']}/"
            f"{row['high_dates']}; selected-industry d20 "
            f"{_fmt(path['selected_industry_d20'])}; {suffix}"
        )
    if result["overlay"] is not None:
        mapping = result["overlay"]["mapping"]
        lines.extend(
            [
                "",
                "## Phase B — exposure overlay",
                "",
                f"Frozen mapping: LOW {mapping['LOW']:.0%}, MEDIUM {mapping['MEDIUM']:.0%}, "
                f"HIGH {mapping['HIGH']:.0%}. Only new cohort capital is scaled; existing "
                "cohorts are untouched and unused capital remains cash.",
                "",
                "| Metric | Champion | Overlay | Delta |",
                "|---|---:|---:|---:|",
            ]
        )
        champion = result["champion"]
        overlay = result["overlay"]["metrics"]
        for name, label in (
            ("total_return", "Total return"),
            ("annualized_return", "Annualized return"),
            ("maximum_drawdown", "Maximum drawdown"),
            ("daily_sharpe", "Sharpe"),
            ("calmar", "Calmar"),
            ("average_gross_exposure", "Average gross exposure"),
            ("turnover_multiple_initial_capital", "Turnover"),
        ):
            base = champion[name]
            value = overlay[name]
            lines.append(f"| {label} | {_fmt(base)} | {_fmt(value)} | {_fmt(value - base)} |")
        lines.extend(["", "## Annual attribution", ""])
        lines.extend(
            [
                (
                    "| Year | Champion | Overlay | Difference | Champion/overlay DD | "
                    "Overlay gross | LOW/MEDIUM/HIGH |"
                ),
                "|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in result["annual_attribution"]:
            lines.append(
                f"| {row['year']} | {_fmt(row['champion_return'])} | "
                f"{_fmt(row['overlay_return'])} | {_fmt(row['return_difference'])} | "
                f"{_fmt(row['champion_maximum_drawdown'])}/"
                f"{_fmt(row['overlay_maximum_drawdown'])} | "
                f"{_fmt(row['overlay_average_gross'])} | {_fmt(row['low_fraction'])}/"
                f"{_fmt(row['medium_fraction'])}/{_fmt(row['high_fraction'])} |"
            )
        efficiency = result["overlay"]["efficiency"]
        lines.extend(
            [
                "",
                "## Risk / reward tradeoff",
                "",
                f"Losing-year arithmetic return improvement: "
                f"{_fmt(efficiency['losing_year_return_improvement'])}. "
                f"Profitable-year arithmetic sacrifice: "
                f"{_fmt(efficiency['profitable_year_return_sacrifice'])}. "
                f"Sacrifice per unit loss avoided: {efficiency['sacrifice_per_loss_avoided']:.3f}.",
                "",
                f"Negative-payoff cohorts de-risked: {efficiency['bad_cohorts_derisked']}; "
                f"positive-payoff cohorts falsely de-risked: "
                f"{efficiency['profitable_cohorts_derisked']}.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "## Phase B — exposure overlay",
                "",
                (
                    "Not authorized. Phase A failed before any new-cohort exposure was "
                    "scaled, so the frozen mapping was not replayed."
                ),
                "",
                "## Annual attribution",
                "",
                (
                    "Not applicable: no overlay portfolio exists. Champion returns for "
                    "2018--2023 remain the frozen Cycle-016 results."
                ),
                "",
                "## Risk / reward tradeoff",
                "",
                (
                    "Not measured. No claim is made about 2018/2022 loss reduction, "
                    "2019/2020/2021/2023 upside sacrifice, or risk-adjusted improvement."
                ),
            ]
        )
    lines.extend(
        [
            "",
            "## Classification",
            "",
            f"`{result['classification']}`.",
            "",
            "## Research implication",
            "",
            result["research_implication"],
            "",
            (
                "All evidence is consumed 2018--2023 development history. Post-2023 "
                "outcomes and CY-011 remained unread. No independent-validation, OOS, "
                "live, or production claim is made."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    daily = pd.read_parquet(_resolve(spec["inputs"]["causal_daily_panel"]["path"]))
    trades = pd.read_parquet(_resolve(spec["inputs"]["cycle_016_trade_panel"]["path"]))
    for column in ("signal_date", "entry_date", "exit_date"):
        trades[column] = pd.to_datetime(trades[column]).dt.date
    industry_paths = pd.read_parquet(
        _resolve(spec["inputs"]["cycle_017_industry_path"]["path"])
    )
    construction_spec = CONSTRUCTION._load_spec()
    _baseline, champion_selection = CYCLE015._weekly_selections(daily, construction_spec)
    ca_spec = CA._load_spec()
    paths, calendar, input_identity = CA._load_market_inputs(ca_spec)
    plans = CONSTRUCTION._make_plans(champion_selection, calendar)
    states = _opportunity_states(paths, set(plans.signal_date))
    phase_panel, phase_a = _phase_a(states, trades, industry_paths)
    construction_equity = pd.read_csv(
        _resolve(spec["inputs"]["construction_equity"]["path"])
    )
    champion_equity = construction_equity.loc[
        construction_equity.family.eq("arm2_low_max")
    ].copy()
    champion_metrics = _equity_metrics(champion_equity)
    champion_result = json.loads(
        _resolve(spec["inputs"]["cycle_017_result"]["path"]).read_text(encoding="utf-8")
    )
    exact_champion = json.loads(
        (PROGRAM / "artifacts/ASHARE-CHAMPION-ANATOMY-CYCLE-016_result.json").read_text(
            encoding="utf-8"
        )
    )["champion_identity"]
    champion_metrics.update(
        {
            "turnover_multiple_initial_capital": exact_champion[
                "turnover_multiple_initial_capital"
            ],
            "severe_trade_fraction": exact_champion["severe_trade_fraction"],
            "entry_execution_fraction": exact_champion["entry_execution_fraction"],
            "p10_capacity_cny_at_5pct_amount": exact_champion[
                "p10_capacity_cny_at_5pct_amount"
            ],
        }
    )
    overlay_metrics: dict[str, Any] | None = None
    overlay_equity: pd.DataFrame | None = None
    overlay_trades: pd.DataFrame | None = None
    annual: pd.DataFrame | None = None
    if phase_a["authorized"]:
        market_rows = CA.PRIOR._query_execution_rows(paths, plans, calendar)
        events, _action_audit = CA._load_risk_events(ca_spec, calendar)
        overlay_trades, overlay_equity, overlay_metrics = _replay_overlay(
            plans,
            market_rows,
            calendar,
            events,
            states,
            set(trades.trade_id),
        )
        annual = _annual_comparison(champion_equity, overlay_equity, states)
    classification, efficiency = _classify(
        phase_a, champion_metrics, overlay_metrics, annual
    )
    cohorts = trades.merge(states, on="signal_date", validate="many_to_one").groupby(
        ["signal_date", "exposure_scale"], as_index=False
    ).agg(profit=("profit", "sum"))
    efficiency["bad_cohorts_derisked"] = int(
        ((cohorts.profit < 0) & (cohorts.exposure_scale < 1)).sum()
    )
    efficiency["profitable_cohorts_derisked"] = int(
        ((cohorts.profit > 0) & (cohorts.exposure_scale < 1)).sum()
    )
    path20 = pd.DataFrame(industry_paths).loc[lambda frame: frame.checkpoint.eq(20)].copy()
    path20["signal_date"] = pd.to_datetime(path20.signal_date).dt.date
    path_year = path20.groupby(
        path20.signal_date.map(lambda value: value.year)
    ).industry_return.mean()
    year_contrast = {
        str(year): {
            "selected_industry_d20": float(path_year.loc[year]),
            "mean_new_cohort_scale": float(
                states.loc[states.year.eq(year), "exposure_scale"].mean()
            ),
            "low_fraction": float(states.loc[states.year.eq(year), "state"].eq("LOW").mean()),
            "medium_fraction": float(
                states.loc[states.year.eq(year), "state"].eq("MEDIUM").mean()
            ),
            "high_fraction": float(states.loc[states.year.eq(year), "state"].eq("HIGH").mean()),
        }
        for year in (2022, 2023)
    }
    if classification == "OPPORTUNITY_HEALTH_NOT_USEFUL":
        executive = (
            "Positive Industry Breadth does not pass the preregistered repeated-state "
            "diagnostic, so exposure scaling was not run. The frozen champion remains "
            "unchanged and research capital returns to independent Alpha discovery."
        )
        implication = (
            "Reject this exact opportunity-health overlay. Do not rescue it with new "
            "thresholds or regime features; prioritize a second independent Alpha engine."
        )
    elif classification == "OPPORTUNITY_HEALTH_OVERLAY_EARNS_COMPLEXITY":
        executive = (
            "Positive Industry Breadth repeatedly identifies weak absolute long opportunity, "
            "and the single frozen new-cohort exposure mapping improves portfolio risk-adjusted "
            "quality at an acceptable profitable-period cost."
        )
        implication = (
            "Retain `CHAMPION + OPPORTUNITY HEALTH OVERLAY` as a separate development risk-"
            "component candidate. Preserve the underlying champion independently and do not "
            "open a second overlay experiment automatically."
        )
    elif classification == "USEFUL_BUT_TOO_COSTLY_IN_UPSIDE":
        executive = (
            "Positive Industry Breadth identifies weaker opportunity and reduces bad-period "
            "exposure, but the frozen mapping sacrifices too much productive exposure for the "
            "portfolio-quality improvement delivered."
        )
        implication = (
            "Park the exact overlay without threshold rescue and prioritize a second independent "
            "Alpha engine."
        )
    else:
        executive = (
            "The Phase-A relationship earned one replay, but the frozen overlay does not improve "
            "the champion's portfolio economics."
        )
        implication = (
            "Reject the exact overlay without rescue and redirect capital to independent Alpha."
        )
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "starting_checkpoint": spec["starting_checkpoint"],
        "claim_boundary": spec["claim_boundary"],
        "input_identity": input_identity,
        "domain": {
            "daily_rows": len(daily),
            "decision_dates": len(states),
            "trades": len(trades),
            "phase_a_rows": len(phase_panel),
        },
        "positive_industry_breadth": spec["positive_industry_breadth"],
        "state_definition": spec["states"],
        "phase_a": phase_a,
        "year_contrast": year_contrast,
        "champion": champion_metrics,
        "overlay": (
            None
            if overlay_metrics is None
            else {
                "mapping": EXPOSURE,
                "scope": spec["overlay"]["scope"],
                "metrics": overlay_metrics,
                "efficiency": efficiency,
            }
        ),
        "annual_attribution": [] if annual is None else annual.to_dict(orient="records"),
        "classification": classification,
        "executive_conclusion": executive,
        "research_implication": implication,
        "cycle_017_context": {
            "common_failure": champion_result["common_failure_conclusion"],
            "used_in_feature_construction": False,
        },
        "boundaries": {
            "post_2023_read": False,
            "cy011_read": False,
            "champion_selection_changed": False,
            "existing_cohorts_rescaled": False,
            "threshold_search": False,
            "exposure_grid_search": False,
            "second_overlay_tested": False,
            "oos_claim": False,
        },
    }
    _atomic_write(
        STATE_PATH, states.to_csv(index=False, lineterminator="\n", float_format="%.10g")
    )
    _atomic_write(
        PHASE_A_PATH,
        phase_panel.to_csv(index=False, lineterminator="\n", float_format="%.10g"),
    )
    if annual is not None:
        _atomic_write(
            ANNUAL_PATH, annual.to_csv(index=False, lineterminator="\n", float_format="%.10g")
        )
    if overlay_equity is not None and overlay_trades is not None:
        EXTERNAL_ROOT.mkdir(parents=True, exist_ok=True)
        overlay_equity.to_parquet(OVERLAY_EQUITY_PATH, index=False, compression="zstd")
        overlay_trades.to_parquet(OVERLAY_TRADES_PATH, index=False, compression="zstd")
        result["external_artifacts"] = {
            path.name: {
                "path": str(path),
                "rows": len(pd.read_parquet(path)),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in (OVERLAY_EQUITY_PATH, OVERLAY_TRADES_PATH)
        }
    else:
        result["external_artifacts"] = {}
    report = _render_report(result)
    _atomic_write(REPORT_PATH, report)
    compact = [STATE_PATH, PHASE_A_PATH, REPORT_PATH]
    if annual is not None:
        compact.append(ANNUAL_PATH)
    result["artifacts"] = {
        path.name: {"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)}
        for path in compact
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
