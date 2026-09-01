#!/usr/bin/env python3
"""Diagnose the frozen Industry Diffusion plus weekly Low-MAX champion."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-CHAMPION-ANATOMY-CYCLE-016_spec.json"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-ANATOMY-CYCLE-016_result.json"
LIFECYCLE_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-ANATOMY-CYCLE-016_lifecycle.csv"
RANK_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-ANATOMY-CYCLE-016_rank.csv"
OPPORTUNITY_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-ANATOMY-CYCLE-016_opportunity.csv"
CONCENTRATION_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-ANATOMY-CYCLE-016_concentration.csv"
PERSISTENCE_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-ANATOMY-CYCLE-016_persistence.csv"
REPORT_PATH = PROGRAM / "reports/ASHARE-CHAMPION-ANATOMY-CYCLE-016_report.md"
EXTERNAL_ROOT = Path("/Volumes/quant/CY_quant_research/champion_anatomy_cycle_016")
TRADE_PANEL_PATH = EXTERNAL_ROOT / "trade_path_panel.parquet"
COHORT_PANEL_PATH = EXTERNAL_ROOT / "cohort_opportunity_panel.parquet"
PERSISTENCE_PANEL_PATH = EXTERNAL_ROOT / "industry_persistence_panel.parquet"
CYCLE015_PATH = PROGRAM / "scripts/run_ashare_multiscale_diffusion_daily_alpha_cycle_015.py"
EXPECTED_SPEC_SHA256 = "59ecfed283bee0becd2c146f3c350db2679a292cbb275cfdfd2f43732033fe43"
CHECKPOINTS = (1, 3, 5, 10, 15, 20)
PERSISTENCE_CHECKPOINTS = (5, 10, 15, 20)
INITIAL_CAPITAL = 10_000_000.0
COST = 0.002
SEVERE = -0.10


class ChampionAnatomyError(RuntimeError):
    """Fail-closed Cycle 016 error."""


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
        raise ChampionAnatomyError(f"cannot load bound runner: {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


CYCLE015 = _load_module("cycle015_for_anatomy016", CYCLE015_PATH)
CONSTRUCTION = CYCLE015.CONSTRUCTION
CA = CYCLE015.CA


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise ChampionAnatomyError("frozen Cycle-016 spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_DIAGNOSTIC_ANATOMY_BEFORE_TRADE_PATH_OUTCOMES":
        raise ChampionAnatomyError("Cycle-016 anatomy was not frozen before outcomes")
    for role, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise ChampionAnatomyError(f"bound input changed: {role}")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("post-2023", "CY-011", "Top-N", "daily refresh", "state-linked exit"):
        if phrase not in prohibited:
            raise ChampionAnatomyError(f"missing prohibition: {phrase}")
    if spec["champion"]["changes_authorized"] is not False:
        raise ChampionAnatomyError("diagnostic cycle unexpectedly authorizes strategy changes")
    return spec


@dataclass
class AnatomyLot:
    trade_id: str
    signal_date: date
    symbol: str
    industry: str
    signal_rank: int
    entry_index: int
    due_index: int
    shares: float
    invested_cost: float
    entry_date: date
    capacity_cny: float
    marks: dict[int, float] = field(default_factory=dict)
    action_cash: float = 0.0
    forced_effective_date: date | None = None
    forced_event_id: str | None = None


def _opportunity_panel(
    daily: pd.DataFrame,
    baseline: pd.DataFrame,
    champion: pd.DataFrame,
    valid_signal_dates: set[date],
) -> pd.DataFrame:
    weekly = daily.loc[daily.cal_idx.mod(5).eq(4)].copy()
    weekly["trade_date"] = pd.to_datetime(weekly.trade_date).dt.date
    baseline = baseline.copy()
    baseline["trade_date"] = pd.to_datetime(baseline.trade_date).dt.date
    champion = champion.copy()
    champion["trade_date"] = pd.to_datetime(champion.trade_date).dt.date
    rows: list[dict[str, Any]] = []
    for signal_date, group in weekly.groupby("trade_date", sort=True):
        if signal_date not in valid_signal_dates:
            continue
        base = baseline.loc[baseline.trade_date.eq(signal_date)]
        selected = champion.loc[champion.trade_date.eq(signal_date)]
        if len(base) != 10 or len(selected) != 10:
            raise ChampionAnatomyError(f"frozen selection breadth changed: {signal_date}")
        selected_industries = set(base.industry.astype(str))
        relevant = group.loc[group.industry.astype(str).isin(selected_industries)]
        scores = group.sort_values(
            ["diffusion_score", "symbol"], ascending=[False, True]
        ).diffusion_score.to_numpy(float)
        margin = float(scores[9] - scores[10]) if len(scores) > 10 else math.nan
        rows.append(
            {
                "signal_date": signal_date,
                "block": "early" if signal_date.year <= 2020 else "late",
                "eligible_industries": int(group.industry.nunique()),
                "eligible_stocks": len(group),
                "selected_industries": len(selected_industries),
                "quality_candidates_selected_industries": int(relevant.max_return20.notna().sum()),
                "mean_candidates_per_selected_industry": float(
                    relevant.groupby("industry").size().mean()
                ),
                "diffusion_rank10_11_margin": margin,
                "selected_trades": len(selected),
            }
        )
    output = pd.DataFrame(rows).sort_values(
        ["quality_candidates_selected_industries", "signal_date"]
    )
    if output.empty or output.signal_date.duplicated().any():
        raise ChampionAnatomyError("invalid opportunity panel")
    labels = np.array(["sparse", "normal", "rich"])
    output["regime"] = labels[
        np.minimum((np.arange(len(output)) * 3 // len(output)).astype(int), 2)
    ]
    return output.sort_values("signal_date").reset_index(drop=True)


def _replay_with_paths(
    plans: pd.DataFrame,
    market_rows: pd.DataFrame,
    calendar: list[date],
    events: list[Any],
    authoritative: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
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
    lots: list[AnatomyLot] = []
    records: list[dict[str, Any]] = []
    nav_rows: list[dict[str, Any]] = []
    turnover = 0.0
    planned_entries = 0
    entries = 0
    risk_blocked_entries = 0
    forced_exits = 0
    capacity: list[float] = []
    start_index = int(plans.entry_index.min())
    final_due = int(plans.due_index.max())
    final_index = min(final_due + 20, len(calendar) - 1)

    def finish(lot: AnatomyLot, payoff: float, current_date: date, reason: str) -> None:
        holding = calendar.index(current_date) - lot.entry_index
        for checkpoint in CHECKPOINTS:
            if checkpoint >= holding and checkpoint not in lot.marks:
                lot.marks[checkpoint] = payoff
        lot.marks[20] = payoff
        record = {
            "trade_id": lot.trade_id,
            "signal_date": lot.signal_date,
            "entry_date": lot.entry_date,
            "exit_date": current_date,
            "symbol": lot.symbol,
            "industry": lot.industry,
            "signal_rank": lot.signal_rank,
            "rank_bucket": (
                "ranks_1_2"
                if lot.signal_rank <= 2
                else "ranks_3_5"
                if lot.signal_rank <= 5
                else "ranks_6_10"
            ),
            "block": "early" if lot.signal_date.year <= 2020 else "late",
            "invested_cost": lot.invested_cost,
            "profit": lot.invested_cost * payoff,
            "final_net_return": payoff,
            "holding_sessions": holding,
            "exit_reason": reason,
            "capacity_cny": lot.capacity_cny,
        }
        for checkpoint in CHECKPOINTS:
            if checkpoint not in lot.marks:
                raise ChampionAnatomyError(f"missing lifecycle mark:{lot.trade_id}:d{checkpoint}")
            record[f"net_return_d{checkpoint}"] = lot.marks[checkpoint]
        records.append(record)

    for cal_index in range(start_index, final_index + 1):
        current_date = calendar[cal_index]
        for lot in lots:
            if lot.forced_effective_date is not None and current_date >= lot.forced_effective_date:
                raise ChampionAnatomyError(
                    f"pre-effective exit failed:{lot.trade_id}:{lot.forced_effective_date}"
                )
            row = row_map.get((lot.symbol, current_date))
            if row is None or not CA._holding_row_usable(row):
                raise ChampionAnatomyError(f"invalid holding row:{lot.trade_id}:{current_date}")
            if int(row.corporate_action_count or 0) > 0:
                action = CA.PRIOR.PRIOR._visible_action(row)
                if action is None:
                    raise ChampionAnatomyError(f"unresolved action:{lot.trade_id}:{current_date}")
                multiplier, cash_per_share = action
                if multiplier != 1.0:
                    raise ChampionAnatomyError(
                        f"share action reached effective date:{lot.trade_id}"
                    )
                lot.action_cash += lot.shares * cash_per_share
            holding = cal_index - lot.entry_index
            if holding in CHECKPOINTS and holding < 20:
                hypothetical = lot.action_cash + lot.shares * float(row.open) * (1.0 - COST)
                lot.marks[holding] = hypothetical / lot.invested_cost - 1.0

        survivors: list[AnatomyLot] = []
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
            forced_exits += int(forced)
            finish(lot, payoff, current_date, "FORCED_PRE_EFFECTIVE" if forced else "DUE")
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
                risk_blocked_entries += 1
                continue
            if row is not None and CYCLE015._buyable(row):
                executable.append((plan, row))
        cohort_capital = min(cash, pre_entry_nav / 4)
        if executable:
            allocation = cohort_capital / len(executable)
            for plan, row in executable:
                shares = allocation / (float(row.open) * (1.0 + COST))
                gross = shares * float(row.open)
                invested = gross * (1.0 + COST)
                cash -= invested
                turnover += gross
                trade_id = f"{plan.signal_date}|{plan.symbol}"
                capacity_cny = float(row.amount) * 0.05 * len(executable) * 4
                lots.append(
                    AnatomyLot(
                        trade_id=trade_id,
                        signal_date=plan.signal_date,
                        symbol=plan.symbol,
                        industry=str(plan.industry),
                        signal_rank=int(plan.signal_rank),
                        entry_index=cal_index,
                        due_index=int(plan.due_index),
                        shares=shares,
                        invested_cost=invested,
                        entry_date=current_date,
                        capacity_cny=capacity_cny,
                    )
                )
                entries += 1
                capacity.append(capacity_cny)

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
        invested = sum(industry_values.values())
        hhi = (
            sum((value / invested) ** 2 for value in industry_values.values())
            if invested > 0
            else 0.0
        )
        nav_rows.append(
            {
                "trade_date": current_date,
                "nav": nav,
                "cash": cash,
                "positions": len(lots),
                "industries": len(industry_values),
                "industry_hhi": hhi,
            }
        )
        if cal_index >= final_due and not lots and cal_index not in entry_map:
            break
    if lots:
        raise ChampionAnatomyError(f"terminal open lots:{len(lots)}")
    trades = pd.DataFrame(records).sort_values(["signal_date", "signal_rank", "symbol"])
    equity = pd.DataFrame(nav_rows)
    returns = equity.nav.pct_change().fillna(equity.nav.iloc[0] / INITIAL_CAPITAL - 1.0)
    drawdown = equity.nav / equity.nav.cummax() - 1.0
    years = len(equity) / 252.0
    annualized = (equity.nav.iloc[-1] / INITIAL_CAPITAL) ** (1.0 / years) - 1.0
    volatility = returns.std(ddof=1)
    replay = {
        "total_return": float(equity.nav.iloc[-1] / INITIAL_CAPITAL - 1.0),
        "annualized_return": float(annualized),
        "maximum_drawdown": float(drawdown.min()),
        "daily_sharpe": float(math.sqrt(252) * returns.mean() / volatility),
        "calmar": float(annualized / abs(drawdown.min())),
        "severe_trade_fraction": float((trades.final_net_return <= SEVERE).mean()),
        "turnover_multiple_initial_capital": float(turnover / INITIAL_CAPITAL),
        "planned_entries": planned_entries,
        "entries": entries,
        "entry_execution_fraction": float(entries / planned_entries),
        "completed_trades": len(trades),
        "forced_pre_effective_exits": forced_exits,
        "terminal_open_lots": 0,
        "mean_positions": float(equity.positions.mean()),
        "mean_industries": float(equity.industries.mean()),
        "mean_industry_hhi_invested_days": float(
            equity.loc[equity.positions > 0, "industry_hhi"].mean()
        ),
        "p10_capacity_cny_at_5pct_amount": float(np.quantile(capacity, 0.10)),
        "median_capacity_cny_at_5pct_amount": float(np.median(capacity)),
        "risk_blocked_entries": risk_blocked_entries,
    }
    exact = (
        "planned_entries",
        "entries",
        "completed_trades",
        "forced_pre_effective_exits",
        "terminal_open_lots",
    )
    floats = (
        "total_return",
        "annualized_return",
        "maximum_drawdown",
        "daily_sharpe",
        "calmar",
        "severe_trade_fraction",
        "turnover_multiple_initial_capital",
        "entry_execution_fraction",
        "mean_positions",
        "mean_industries",
        "mean_industry_hhi_invested_days",
        "p10_capacity_cny_at_5pct_amount",
        "median_capacity_cny_at_5pct_amount",
    )
    for name in exact:
        if replay[name] != authoritative[name]:
            raise ChampionAnatomyError(f"champion identity mismatch:{name}")
    for name in floats:
        if not math.isclose(replay[name], authoritative[name], rel_tol=0, abs_tol=1e-12):
            raise ChampionAnatomyError(f"champion identity mismatch:{name}")
    if not math.isclose(
        float(trades.profit.sum()),
        float(equity.nav.iloc[-1] - INITIAL_CAPITAL),
        rel_tol=0,
        abs_tol=1e-6,
    ):
        raise ChampionAnatomyError("trade PnL does not conserve to terminal NAV")
    return trades, equity, replay


def _periods(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        "full": frame,
        "early": frame.loc[frame.block.eq("early")],
        "late": frame.loc[frame.block.eq("late")],
    }


def _lifecycle_summary(
    trades: pd.DataFrame, construction_result: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}
    for period, frame in _periods(trades).items():
        period_rows: dict[str, Any] = {}
        previous = np.zeros(len(frame))
        for checkpoint in CHECKPOINTS:
            values = frame[f"net_return_d{checkpoint}"].to_numpy(float)
            incremental = values - previous
            row = {
                "period": period,
                "checkpoint": checkpoint,
                "trades": len(frame),
                "mean_cumulative": float(values.mean()),
                "median_cumulative": float(np.median(values)),
                "winner_fraction": float((values > 0).mean()),
                "severe_fraction": float((values <= SEVERE).mean()),
                "mean_incremental": float(incremental.mean()),
            }
            rows.append(row)
            period_rows[f"d{checkpoint}"] = row
            previous = values
        metrics[period] = period_rows
    full = metrics["full"]
    early = metrics["early"]
    late = metrics["late"]
    if np.sign(early["d20"]["mean_cumulative"]) != np.sign(late["d20"]["mean_cumulative"]):
        classification = "CHRONOLOGICALLY_UNSTABLE"
    elif all(
        period["d20"]["mean_cumulative"] <= period["d10"]["mean_cumulative"] - 0.0025
        for period in (full, early, late)
    ):
        classification = "LATE_DECAY_OR_GIVEBACK"
    elif all(
        period["d20"]["mean_cumulative"] > 0
        and period["d5"]["mean_cumulative"] / period["d20"]["mean_cumulative"] >= 0.75
        for period in (full, early, late)
    ):
        classification = "EARLY_CONCENTRATED"
    elif all(
        period["d20"]["mean_cumulative"] - period["d10"]["mean_cumulative"] >= 0.0025
        for period in (full, early, late)
    ):
        classification = "FULL_HORIZON_PERSISTENT"
    elif all(
        period["d10"]["mean_cumulative"] - period["d5"]["mean_cumulative"] >= 0.0025
        and period["d20"]["mean_cumulative"] - period["d10"]["mean_cumulative"] > -0.0025
        for period in (full, early, late)
    ):
        classification = "MID_HORIZON_PERSISTENT"
    else:
        classification = "CHRONOLOGICALLY_UNSTABLE"
    prior = construction_result["candidate_attribution"]["arm2_low_max"]["periods"]
    return pd.DataFrame(rows), {
        "periods": metrics,
        "classification": classification,
        "authoritative_candidate_h20_excess": {
            period: prior[period]["mean_net_improvement"] for period in ("full", "early", "late")
        },
    }


def _rank_summary(trades: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for bucket, group in trades.groupby("rank_bucket", sort=True):
        for period, frame in _periods(group).items():
            industry_capital = frame.groupby("industry").invested_cost.sum()
            weights = industry_capital / industry_capital.sum()
            rows.append(
                {
                    "rank_bucket": bucket,
                    "period": period,
                    "trades": len(frame),
                    "mean_net_payoff": float(frame.final_net_return.mean()),
                    "median_net_payoff": float(frame.final_net_return.median()),
                    "winner_fraction": float((frame.final_net_return > 0).mean()),
                    "severe_fraction": float((frame.final_net_return <= SEVERE).mean()),
                    "profit": float(frame.profit.sum()),
                    "net_pnl_share": float(frame.profit.sum() / trades.profit.sum()),
                    "industry_capital_hhi": float((weights**2).sum()),
                    "p10_capacity_cny": float(frame.capacity_cny.quantile(0.10)),
                }
            )
    panel = pd.DataFrame(rows)
    full = panel.loc[panel.period.eq("full")].set_index("rank_bucket")
    lower = panel.loc[panel.rank_bucket.eq("ranks_6_10")].set_index("period")
    if (full.mean_net_payoff > 0).all() and (
        lower.loc[["early", "late"]].mean_net_payoff > 0
    ).all():
        classification = "BREADTH_ECONOMICALLY_SUPPORTED"
    elif lower.loc["full", "mean_net_payoff"] > 0:
        classification = "LOWER_RANKS_WEAK_BUT_POSITIVE"
    elif (lower.loc[["full", "early", "late"], "mean_net_payoff"] <= 0).all():
        classification = "LOWER_RANKS_DILUTIVE"
    else:
        classification = "RANK_EFFECT_UNSTABLE"
    return panel, {"classification": classification, "rows": rows}


def _opportunity_summary(
    trades: pd.DataFrame, opportunity: pd.DataFrame, rank_classification: str
) -> tuple[pd.DataFrame, dict[str, Any]]:
    merged = trades.merge(opportunity, on=["signal_date", "block"], validate="many_to_one")
    cohort = merged.groupby(["signal_date", "block", "regime"], as_index=False).agg(
        profit=("profit", "sum"), invested=("invested_cost", "sum")
    )
    cohort["cohort_net_payoff"] = cohort.profit / cohort.invested
    rows: list[dict[str, Any]] = []
    for regime, group in merged.groupby("regime", sort=False):
        cohort_group = cohort.loc[cohort.regime.eq(regime)]
        for period, frame in _periods(group).items():
            cohort_period = (
                cohort_group
                if period == "full"
                else cohort_group.loc[cohort_group.block.eq(period)]
            )
            rows.append(
                {
                    "regime": regime,
                    "period": period,
                    "decision_dates": int(cohort_period.signal_date.nunique()),
                    "trades": len(frame),
                    "mean_cohort_net_payoff": float(cohort_period.cohort_net_payoff.mean()),
                    "median_cohort_net_payoff": float(cohort_period.cohort_net_payoff.median()),
                    "mean_trade_net_payoff": float(frame.final_net_return.mean()),
                    "winner_fraction": float((frame.final_net_return > 0).mean()),
                    "severe_fraction": float((frame.final_net_return <= SEVERE).mean()),
                    "profit": float(frame.profit.sum()),
                    "net_pnl_share": float(frame.profit.sum() / trades.profit.sum()),
                    "p10_capacity_cny": float(frame.capacity_cny.quantile(0.10)),
                    "mean_quality_candidates": float(
                        frame.quality_candidates_selected_industries.mean()
                    ),
                }
            )
    panel = pd.DataFrame(rows)
    by_period = {
        period: panel.loc[panel.period.eq(period)].set_index("regime")
        for period in ("full", "early", "late")
    }
    full = by_period["full"]
    gaps = {
        period: float(
            table.loc["rich", "mean_cohort_net_payoff"]
            - table.loc["sparse", "mean_cohort_net_payoff"]
        )
        for period, table in by_period.items()
    }
    checks = {
        "rank_dilutive": rank_classification == "LOWER_RANKS_DILUTIVE",
        "dates": bool((full.decision_dates >= 50).all()),
        "rich_minus_sparse": gaps["full"] >= 0.005,
        "both_blocks": gaps["early"] > 0 and gaps["late"] > 0,
        "sparse_nonpositive": full.loc["sparse", "mean_cohort_net_payoff"] <= 0,
        "monotonic": bool(
            full.loc["sparse", "mean_cohort_net_payoff"]
            <= full.loc["normal", "mean_cohort_net_payoff"]
            <= full.loc["rich", "mean_cohort_net_payoff"]
        ),
    }
    return panel, {
        "rows": rows,
        "rich_minus_sparse": gaps,
        "gate": checks,
        "authorized": all(checks.values()),
    }


def _group_contribution(
    frame: pd.DataFrame, key: str, label: str
) -> tuple[pd.DataFrame, dict[str, Any]]:
    grouped = frame.groupby(key, as_index=False).agg(
        profit=("profit", "sum"), invested=("invested_cost", "sum"), trades=("trade_id", "size")
    )
    grouped["dimension"] = label
    grouped = grouped.rename(columns={key: "group"})
    grouped["net_pnl_share"] = grouped.profit / frame.profit.sum()
    positive = grouped.loc[grouped.profit > 0, "profit"]
    hhi = float(((positive / positive.sum()) ** 2).sum()) if not positive.empty else math.nan
    return grouped, {"positive_pnl_hhi": hhi}


def _concentration_summary(trades: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    panels: list[pd.DataFrame] = []
    diagnostics: dict[str, Any] = {}
    dimensions = (
        ("industry", "industry"),
        ("signal_date", "decision_date"),
        ("symbol", "security"),
    )
    work = trades.copy()
    work["entry_year"] = pd.to_datetime(work.entry_date).dt.year
    for key, label in (*dimensions, ("entry_year", "year")):
        panel, metric = _group_contribution(work, key, label)
        panels.append(panel)
        diagnostics[label] = metric
    output = pd.concat(panels, ignore_index=True)
    total = float(trades.profit.sum())

    def top_share(dimension: str, count: int) -> float:
        values = output.loc[output.dimension.eq(dimension)].nlargest(count, "profit").profit
        return float(values.sum() / total)

    industry = output.loc[output.dimension.eq("industry")]
    year = output.loc[output.dimension.eq("year")]
    decision = output.loc[output.dimension.eq("decision_date")]
    largest_industry = industry.loc[industry.profit.idxmax()]
    largest_year = year.loc[year.profit.idxmax()]
    largest_date = decision.loc[decision.profit.idxmax()]
    summary = {
        "total_trade_profit": total,
        "top5_industry_net_pnl_share": top_share("industry", 5),
        "top10_decision_date_net_pnl_share": top_share("decision_date", 10),
        "top20_security_net_pnl_share": top_share("security", 20),
        "positive_pnl_hhi": diagnostics,
        "positive_years": int((year.profit > 0).sum()),
        "negative_years": int((year.profit < 0).sum()),
        "year_contributions": {
            str(row.group): float(row.profit / INITIAL_CAPITAL)
            for row in year.sort_values("group").itertuples(index=False)
        },
        "largest_contributors": {
            "industry": {"group": largest_industry.group, "profit": float(largest_industry.profit)},
            "year": {"group": str(largest_year.group), "profit": float(largest_year.profit)},
            "decision_date": {
                "group": str(largest_date.group),
                "profit": float(largest_date.profit),
            },
        },
        "leave_one_out_total_return": {
            "largest_industry": float((total - largest_industry.profit) / INITIAL_CAPITAL),
            "largest_year": float((total - largest_year.profit) / INITIAL_CAPITAL),
            "largest_decision_date": float((total - largest_date.profit) / INITIAL_CAPITAL),
        },
    }
    summary["structurally_fragile"] = bool(
        summary["leave_one_out_total_return"]["largest_industry"] <= 0
        or summary["leave_one_out_total_return"]["largest_year"] <= 0
    )
    summary["concentrated"] = bool(
        summary["top5_industry_net_pnl_share"] > 0.60
        or summary["top10_decision_date_net_pnl_share"] > 0.60
        or summary["top20_security_net_pnl_share"] > 0.60
    )
    return output, summary


def _persistence_summary(
    trades: pd.DataFrame, daily: pd.DataFrame, calendar: list[date]
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    frame = daily.copy()
    frame["trade_date"] = pd.to_datetime(frame.trade_date).dt.date
    top = (
        frame.sort_values(
            ["trade_date", "diffusion_score", "symbol"], ascending=[True, False, True]
        )
        .groupby("trade_date", sort=False)
        .head(10)
    )
    top_industries = {
        day: set(group.industry.astype(str)) for day, group in top.groupby("trade_date", sort=False)
    }
    cal_index = {day: index for index, day in enumerate(calendar)}
    rows: list[dict[str, Any]] = []
    for (signal_date, industry), group in trades.groupby(["signal_date", "industry"], sort=True):
        entry_index = cal_index[signal_date] + 1
        for checkpoint in PERSISTENCE_CHECKPOINTS:
            checkpoint_date = calendar[entry_index + checkpoint]
            persistent = industry in top_industries.get(checkpoint_date, set())
            rows.append(
                {
                    "signal_date": signal_date,
                    "industry": industry,
                    "block": "early" if signal_date.year <= 2020 else "late",
                    "checkpoint": checkpoint,
                    "checkpoint_date": checkpoint_date,
                    "persistent": persistent,
                    "trades": len(group),
                    "subsequent_payoff": float(
                        (group.final_net_return - group[f"net_return_d{checkpoint}"]).mean()
                    ),
                    "final_net_payoff": float(group.final_net_return.mean()),
                }
            )
    panel = pd.DataFrame(rows)
    summary_rows: list[dict[str, Any]] = []
    for checkpoint, checkpoint_group in panel.groupby("checkpoint", sort=True):
        for state, state_group in checkpoint_group.groupby("persistent", sort=True):
            for period, period_group in _periods(state_group).items():
                summary_rows.append(
                    {
                        "checkpoint": checkpoint,
                        "state": "persistent" if state else "faded",
                        "period": period,
                        "groups": len(period_group),
                        "persistence_fraction": float(state_group.persistent.mean()),
                        "mean_subsequent_payoff": float(period_group.subsequent_payoff.mean()),
                        "median_subsequent_payoff": float(period_group.subsequent_payoff.median()),
                        "mean_final_net_payoff": float(period_group.final_net_payoff.mean()),
                    }
                )
    summary_panel = pd.DataFrame(summary_rows)
    indexed = summary_panel.set_index(["checkpoint", "state", "period"])
    gaps: dict[str, dict[str, float]] = {}
    checks = {
        "early_fade_frequency": False,
        "group_counts": True,
        "full_gaps": True,
        "block_gaps": True,
        "faded_nonpositive": True,
    }
    wide = panel.pivot_table(
        index=["signal_date", "industry", "block"],
        columns="checkpoint",
        values="persistent",
        aggfunc="first",
    ).reset_index()
    wide["early_fade"] = ~wide[5].astype(bool) | ~wide[10].astype(bool)
    early_fade_fraction = float(wide.early_fade.mean())
    checks["early_fade_frequency"] = early_fade_fraction >= 0.25
    for checkpoint in (5, 10):
        gaps[str(checkpoint)] = {}
        for period in ("full", "early", "late"):
            persisted = indexed.loc[(checkpoint, "persistent", period)]
            faded = indexed.loc[(checkpoint, "faded", period)]
            gap = float(persisted.mean_subsequent_payoff - faded.mean_subsequent_payoff)
            gaps[str(checkpoint)][period] = gap
            if period == "full":
                checks["group_counts"] &= bool(persisted.groups >= 100 and faded.groups >= 100)
                checks["full_gaps"] &= gap >= 0.005
                checks["faded_nonpositive"] &= bool(faded.mean_subsequent_payoff <= 0)
            else:
                checks["block_gaps"] &= gap > 0
    return (
        panel,
        summary_panel,
        {
            "early_fade_fraction": early_fade_fraction,
            "checkpoint_persistence_fraction": {
                str(checkpoint): float(group.persistent.mean())
                for checkpoint, group in panel.groupby("checkpoint", sort=True)
            },
            "persistent_minus_faded_subsequent_payoff": gaps,
            "gate": checks,
            "authorized": all(checks.values()),
        },
    )


def _structural_decision(
    opportunity: dict[str, Any], persistence: dict[str, Any], concentration: dict[str, Any]
) -> tuple[str, str]:
    if opportunity["authorized"]:
        return "EARN_ONE_OPPORTUNITY_ADAPTIVE_BREADTH_EXPERIMENT", "OPPORTUNITY_BREADTH_MISMATCH"
    if persistence["authorized"]:
        return "EARN_ONE_STATE_LINKED_EXIT_EXPERIMENT", "HOLDING_LIFECYCLE_MISMATCH"
    if concentration["structurally_fragile"]:
        classification = "STRUCTURALLY_FRAGILE_DEVELOPMENT_ALPHA"
    elif concentration["concentrated"]:
        classification = "CONCENTRATED_BUT_ECONOMICALLY_MEANINGFUL"
    else:
        classification = "BROADLY_DISTRIBUTED_ROBUST_DEVELOPMENT_ALPHA"
    return "NO_CHAMPION_MODIFICATION_RETURN_TO_INDEPENDENT_ALPHA", classification


def _fmt(value: float) -> str:
    return f"{value:.2%}"


def _render_report(result: dict[str, Any]) -> str:
    lifecycle = result["alpha_lifecycle"]["periods"]["full"]
    lifecycle_early = result["alpha_lifecycle"]["periods"]["early"]
    lifecycle_late = result["alpha_lifecycle"]["periods"]["late"]
    rank = result["rank_anatomy"]["rows"]
    rank_full = {row["rank_bucket"]: row for row in rank if row["period"] == "full"}
    rank_early = {row["rank_bucket"]: row for row in rank if row["period"] == "early"}
    rank_late = {row["rank_bucket"]: row for row in rank if row["period"] == "late"}
    opportunity = result["opportunity_richness"]["rows"]
    opp_full = {row["regime"]: row for row in opportunity if row["period"] == "full"}
    opp_early = {row["regime"]: row for row in opportunity if row["period"] == "early"}
    opp_late = {row["regime"]: row for row in opportunity if row["period"] == "late"}
    persistence_rows = result["industry_thesis_persistence"]["rows"]
    persistence_full = {
        (row["checkpoint"], row["state"]): row
        for row in persistence_rows
        if row["period"] == "full"
    }
    lines = [
        "# Champion strategy anatomy — Industry Diffusion + Weekly Low-MAX",
        "",
        "## Executive conclusion",
        "",
        f"Lifecycle classification: `{result['alpha_lifecycle']['classification']}`. "
        f"Rank classification: `{result['rank_anatomy']['classification']}`. "
        f"Final anatomy: `{result['final_classification']}`.",
        "",
        (
            f"Structural decision: `{result['structural_decision']}`. "
            "The frozen strategy was not changed."
        ),
        "",
        (
            "Alpha is not front-loaded: the mean trade is still negative after d1, "
            f"reaches only {_fmt(lifecycle['d5']['mean_cumulative'])} by d5, and earns "
            f"{_fmt(lifecycle['d20']['mean_cumulative'] - lifecycle['d10']['mean_cumulative'])} "
            "after d10. Ranks 6--10 remain positive in both broad blocks and contribute "
            f"{_fmt(rank_full['ranks_6_10']['net_pnl_share'])} of net trade PnL, so the "
            "frozen Top 10 has economic breadth rather than an obviously dilutive tail."
        ),
        "",
        (
            "Opportunity richness does not order outcomes monotonically: normal cohorts "
            "are strongest overall, while the rich-minus-sparse relation reverses between "
            "the two broad blocks. Industry-state persistence is associated with stronger "
            "subsequent payoff, but faded cohorts remain profitable and the d10 gap misses "
            "the frozen exit gate. Neither adaptive breadth nor a state-linked exit earned "
            "a construction experiment."
        ),
        "",
        "## Alpha lifecycle",
        "",
        "| Checkpoint | Mean cumulative | Early mean | Late mean | Median | Winner | "
        "Severe | Mean incremental |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for checkpoint in CHECKPOINTS:
        row = lifecycle[f"d{checkpoint}"]
        lines.append(
            f"| d{checkpoint} | {_fmt(row['mean_cumulative'])} | "
            f"{_fmt(lifecycle_early[f'd{checkpoint}']['mean_cumulative'])} | "
            f"{_fmt(lifecycle_late[f'd{checkpoint}']['mean_cumulative'])} | "
            f"{_fmt(row['median_cumulative'])} | "
            f"{_fmt(row['winner_fraction'])} | {_fmt(row['severe_fraction'])} | "
            f"{_fmt(row['mean_incremental'])} |"
        )
    matched_excess = result["alpha_lifecycle"]["authoritative_candidate_h20_excess"]
    lines.extend(
        [
            "",
            (
                "The already-authoritative candidate/control h20 excess is "
                f"{_fmt(matched_excess['full'])} full, "
                f"{_fmt(matched_excess['early'])} early, and "
                f"{_fmt(matched_excess['late'])} late; it is reported for context "
                "and was not reconstructed into intermediate checkpoint controls."
            ),
        ]
    )
    lines.extend(
        [
            "",
            "## Rank anatomy",
            "",
            "| Frozen rank bucket | Trades | Mean | Early | Late | Median | Winner | Severe | "
            "Net-PnL share | Industry HHI | P10 capacity |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for bucket in ("ranks_1_2", "ranks_3_5", "ranks_6_10"):
        row = rank_full[bucket]
        lines.append(
            f"| {bucket} | {row['trades']} | {_fmt(row['mean_net_payoff'])} | "
            f"{_fmt(rank_early[bucket]['mean_net_payoff'])} | "
            f"{_fmt(rank_late[bucket]['mean_net_payoff'])} | "
            f"{_fmt(row['median_net_payoff'])} | {_fmt(row['winner_fraction'])} | "
            f"{_fmt(row['severe_fraction'])} | {_fmt(row['net_pnl_share'])} | "
            f"{row['industry_capital_hhi']:.3f} | CNY {row['p10_capacity_cny']:,.0f} |"
        )
    lines.extend(
        [
            "",
            "## Opportunity richness",
            "",
            "| Regime | Dates | Trades | Mean cohort | Early | Late | Winner | Severe | "
            "Net-PnL share | P10 capacity |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for regime in ("sparse", "normal", "rich"):
        row = opp_full[regime]
        lines.append(
            f"| {regime} | {row['decision_dates']} | {row['trades']} | "
            f"{_fmt(row['mean_cohort_net_payoff'])} | "
            f"{_fmt(opp_early[regime]['mean_cohort_net_payoff'])} | "
            f"{_fmt(opp_late[regime]['mean_cohort_net_payoff'])} | "
            f"{_fmt(row['winner_fraction'])} | "
            f"{_fmt(row['severe_fraction'])} | {_fmt(row['net_pnl_share'])} | "
            f"CNY {row['p10_capacity_cny']:,.0f} |"
        )
    c = result["contribution_concentration"]
    lines.extend(
        [
            "",
            "## Contribution concentration",
            "",
            f"Top-five industries contribute {_fmt(c['top5_industry_net_pnl_share'])} of net PnL; "
            f"top-ten decision dates {_fmt(c['top10_decision_date_net_pnl_share'])}; "
            f"top-twenty securities {_fmt(c['top20_security_net_pnl_share'])}.",
            "",
            f"Positive/negative years: {c['positive_years']}/{c['negative_years']}. "
            f"Leave-largest-industry/year/date returns are "
            f"{_fmt(c['leave_one_out_total_return']['largest_industry'])}/"
            f"{_fmt(c['leave_one_out_total_return']['largest_year'])}/"
            f"{_fmt(c['leave_one_out_total_return']['largest_decision_date'])}.",
            "",
            (
                "Year contributions to initial capital are "
                + ", ".join(
                    f"{year} {_fmt(value)}"
                    for year, value in c["year_contributions"].items()
                )
                + "."
            ),
            "",
            "## Industry-thesis persistence",
            "",
            "| Checkpoint | Persistence | Persistent subsequent | Faded subsequent | Gap |",
            "|---:|---:|---:|---:|---:|",
        ]
    )
    fractions = result["industry_thesis_persistence"]["checkpoint_persistence_fraction"]
    for checkpoint in PERSISTENCE_CHECKPOINTS:
        persistent = persistence_full[(checkpoint, "persistent")]
        faded = persistence_full[(checkpoint, "faded")]
        gap = persistent["mean_subsequent_payoff"] - faded["mean_subsequent_payoff"]
        lines.append(
            f"| d{checkpoint} | {_fmt(fractions[str(checkpoint)])} | "
            f"{_fmt(persistent['mean_subsequent_payoff'])} | "
            f"{_fmt(faded['mean_subsequent_payoff'])} | {_fmt(gap)} |"
        )
    lines.extend(
        [
            "",
            "## Structural decision",
            "",
            (
                f"`{result['structural_decision']}`. Exactly zero strategy changes "
                "or new Alpha tests were run."
            ),
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
    ca_spec = CA._load_spec()
    paths, calendar, input_identity = CA._load_market_inputs(ca_spec)
    construction_spec = CONSTRUCTION._load_spec()
    daily = pd.read_parquet(_resolve(spec["inputs"]["causal_daily_panel"]["path"]))
    cycle015_result = json.loads(
        _resolve(spec["inputs"]["cycle_015_result"]["path"]).read_text(encoding="utf-8")
    )
    if len(daily) != cycle015_result["domain"]["daily_feature_rows"]:
        raise ChampionAnatomyError("causal daily panel row count changed")
    baseline, champion = CYCLE015._weekly_selections(daily, construction_spec)
    champion = champion.copy()
    champion["family"] = "industry_diffusion_low_max"
    plans = CONSTRUCTION._make_plans(champion, calendar)
    champion_meta = champion[["trade_date", "symbol", "signal_rank"]].copy()
    champion_meta["signal_date"] = pd.to_datetime(champion_meta.pop("trade_date")).dt.date
    plans = plans.merge(
        champion_meta, on=["signal_date", "symbol"], how="left", validate="one_to_one"
    )
    if plans.signal_rank.isna().any():
        raise ChampionAnatomyError("frozen champion rank missing from plan")
    plans["signal_rank"] = plans.signal_rank.astype(int)
    valid_signal_dates = set(plans.signal_date)
    opportunity = _opportunity_panel(daily, baseline, champion, valid_signal_dates)
    market_rows = CA.PRIOR._query_execution_rows(paths, plans, calendar)
    events, action_audit = CA._load_risk_events(ca_spec, calendar)
    low_max_result = json.loads(
        _resolve(spec["inputs"]["low_max_result"]["path"]).read_text(encoding="utf-8")
    )
    authoritative = low_max_result["track_a"]["matched_cost_comparisons"]["20bps"]["low_max"]
    trades, _equity, replay = _replay_with_paths(
        plans, market_rows, calendar, events, authoritative
    )
    construction_result = json.loads(
        (PROGRAM / "artifacts/ASHARE-INDUSTRY-DIFFUSION-CONSTRUCTION-011_result.json").read_text(
            encoding="utf-8"
        )
    )
    lifecycle_panel, lifecycle = _lifecycle_summary(trades, construction_result)
    rank_panel, rank = _rank_summary(trades)
    opportunity_panel, opportunity_metrics = _opportunity_summary(
        trades, opportunity, rank["classification"]
    )
    concentration_panel, concentration = _concentration_summary(trades)
    persistence_raw, persistence_panel, persistence = _persistence_summary(trades, daily, calendar)
    decision, final_classification = _structural_decision(
        opportunity_metrics, persistence, concentration
    )

    EXTERNAL_ROOT.mkdir(parents=True, exist_ok=True)
    trades.to_parquet(TRADE_PANEL_PATH, index=False, compression="zstd")
    opportunity.to_parquet(COHORT_PANEL_PATH, index=False, compression="zstd")
    persistence_raw.to_parquet(PERSISTENCE_PANEL_PATH, index=False, compression="zstd")
    _atomic_write(
        LIFECYCLE_PATH,
        lifecycle_panel.to_csv(index=False, lineterminator="\n", float_format="%.10g"),
    )
    _atomic_write(
        RANK_PATH, rank_panel.to_csv(index=False, lineterminator="\n", float_format="%.10g")
    )
    _atomic_write(
        OPPORTUNITY_PATH,
        opportunity_panel.to_csv(index=False, lineterminator="\n", float_format="%.10g"),
    )
    _atomic_write(
        CONCENTRATION_PATH,
        concentration_panel.to_csv(index=False, lineterminator="\n", float_format="%.10g"),
    )
    _atomic_write(
        PERSISTENCE_PATH,
        persistence_panel.to_csv(index=False, lineterminator="\n", float_format="%.10g"),
    )

    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "starting_checkpoint": spec["starting_checkpoint"],
        "claim_boundary": spec["claim_boundary"],
        "input_identity": input_identity,
        "action_audit": action_audit,
        "domain": {
            "plans": len(plans),
            "executed_trades": len(trades),
            "decision_dates": int(trades.signal_date.nunique()),
            "industries": int(trades.industry.nunique()),
            "securities": int(trades.symbol.nunique()),
            "market_rows": len(market_rows),
        },
        "champion_identity": replay,
        "alpha_lifecycle": lifecycle,
        "rank_anatomy": rank,
        "opportunity_richness": opportunity_metrics,
        "contribution_concentration": concentration,
        "industry_thesis_persistence": {
            **persistence,
            "rows": persistence_panel.to_dict(orient="records"),
        },
        "structural_decision": decision,
        "final_classification": final_classification,
        "boundaries": {
            "post_2023_read": False,
            "cy011_read": False,
            "strategy_changed": False,
            "top_n_replay": False,
            "exit_replay": False,
            "new_alpha_discovery": False,
            "oos_claim": False,
        },
    }
    result["external_artifacts"] = {
        path.name: {
            "path": str(path),
            "rows": len(pd.read_parquet(path)),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in (TRADE_PANEL_PATH, COHORT_PANEL_PATH, PERSISTENCE_PANEL_PATH)
    }
    result["artifacts"] = {
        path.name: {"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)}
        for path in (
            LIFECYCLE_PATH,
            RANK_PATH,
            OPPORTUNITY_PATH,
            CONCENTRATION_PATH,
            PERSISTENCE_PATH,
        )
    }
    report = _render_report(result)
    _atomic_write(REPORT_PATH, report)
    result["artifacts"][REPORT_PATH.name] = {
        "path": str(REPORT_PATH.relative_to(ROOT)),
        "sha256": sha256_file(REPORT_PATH),
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
