#!/usr/bin/env python3
"""Run the frozen own-history-relative speculative-turnover experiment."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
EXPERIMENT_ID = "ASHARE-SPECULATIVE-TURNOVER-RATIO-V1"
SPEC_PATH = PROGRAM / f"experiments/{EXPERIMENT_ID}_spec.json"
SCREEN_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_screen.csv"
EQUITY_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_equity.csv"
RESULT_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_result.json"
REPORT_PATH = PROGRAM / f"reports/{EXPERIMENT_ID}_report.md"
CA_PATH = PROGRAM / "scripts/run_ashare_ca_replay_003.py"
ELIGIBILITY_PATH = Path(
    "/Volumes/quant/CY_quant_research/"
    "multiscale_diffusion_daily_alpha_cycle_015/daily_feature_panel.parquet"
)
EXPECTED_SPEC_SHA256 = "db216f35c2e175c7c42ed8671f4499fdfa5f825b659b94982ae99217a4c72ac6"
COST = 0.002
INITIAL_CAPITAL = 10_000_000.0
GENERATION_YEARS = {2019, 2020}
VALIDATION_YEARS = {2021, 2022, 2023}


class SpeculativeTurnoverError(RuntimeError):
    """Fail-closed speculative-turnover experiment error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise SpeculativeTurnoverError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


CA = _load_module("ashare_ca_for_speculative_turnover", CA_PATH)


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


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise SpeculativeTurnoverError("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_ANY_FORWARD_RETURN_OR_PORTFOLIO_OUTCOME":
        raise SpeculativeTurnoverError("experiment spec was not frozen")
    for role, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise SpeculativeTurnoverError(f"bound input changed: {role}")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("alternative turnover", "same-session", "post-2023", "CY-011"):
        if phrase not in prohibited:
            raise SpeculativeTurnoverError(f"missing prohibition: {phrase}")
    CA._load_spec()
    return spec


def _feature_panel(
    daily_paths: list[Path],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    connection = duckdb.connect()
    connection.execute("SET threads=2")
    connection.execute("SET memory_limit='6GB'")
    connection.execute("SET preserve_insertion_order=false")
    connection.from_parquet(
        [str(path) for path in daily_paths], union_by_name=True
    ).create_view("source")
    connection.from_parquet(str(ELIGIBILITY_PATH)).create_view("eligibility")
    audit_row = connection.execute(
        """
        SELECT count(*),count(DISTINCT symbol),min(trade_date),max(trade_date),
          sum((available_at>decision_at)::INTEGER),
          sum((hard_valid AND (available_at IS NULL OR snapshot_id IS NULL))::INTEGER),
          max(abs(turnover_fraction-turnover_pct/100.0))
        FROM source
        """
    ).fetchone()
    audit = {
        "rows": int(audit_row[0]),
        "symbols": int(audit_row[1]),
        "first": str(audit_row[2]),
        "last": str(audit_row[3]),
        "time_travel": int(audit_row[4]),
        "lineage_failures": int(audit_row[5]),
        "turnover_unit_max_error": float(audit_row[6]),
    }
    expected = {
        "rows": 6_155_390,
        "symbols": 5_262,
        "first": "2018-01-02",
        "last": "2023-12-29",
        "time_travel": 0,
        "lineage_failures": 0,
    }
    if {key: audit[key] for key in expected} != expected:
        raise SpeculativeTurnoverError(f"daily source audit changed: {audit}")
    if audit["turnover_unit_max_error"] > 1e-12:
        raise SpeculativeTurnoverError(f"turnover unit mismatch: {audit}")
    connection.execute(
        """
        CREATE TEMP TABLE exchange_months AS
        SELECT date_trunc('month',trade_date)::DATE month_key,
          max(trade_date) month_end
        FROM (SELECT DISTINCT trade_date FROM source)
        GROUP BY 1 ORDER BY 1
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE monthly AS
        SELECT symbol,date_trunc('month',trade_date)::DATE month_key,
          sum(CASE WHEN hard_valid AND bar_valid AND trading_state_valid
                    AND available_at<=decision_at
                    AND turnover_fraction>=0 AND isfinite(turnover_fraction)
              THEN turnover_fraction ELSE 0 END) month_turnover,
          count(*) FILTER (WHERE hard_valid AND bar_valid AND trading_state_valid
                    AND available_at<=decision_at AND trade_status=1
                    AND current_day_data_tradable AND turnover_fraction>=0
                    AND isfinite(turnover_fraction)) valid_days
        FROM source
        GROUP BY 1,2
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE normalized AS
        SELECT m.*,x.month_end,
          count(*) OVER prior12 prior_months,
          avg(month_turnover) OVER prior12 prior12_average,
          min(valid_days) OVER prior12 prior12_minimum_days,
          lag(m.month_key,12) OVER stock_time month_lag12
        FROM monthly m JOIN exchange_months x USING(month_key)
        WINDOW
          prior12 AS (PARTITION BY symbol ORDER BY m.month_key
            ROWS BETWEEN 12 PRECEDING AND 1 PRECEDING),
          stock_time AS (PARTITION BY symbol ORDER BY m.month_key)
        """
    )
    frame = connection.execute(
        """
        SELECT e.trade_date,e.cal_idx,e.decision_at,e.available_at,e.symbol,
          e.industry,e.avg_amount20,e.max_return20,
          n.month_turnover/n.prior12_average turnover_surge_ratio
        FROM eligibility e JOIN normalized n
          ON e.symbol=n.symbol AND CAST(e.trade_date AS DATE)=n.month_end
        WHERE n.valid_days>=15 AND n.prior_months=12
          AND n.prior12_minimum_days>=15
          AND date_diff('month',n.month_lag12,n.month_key)=12
          AND n.prior12_average>0
          AND isfinite(n.month_turnover/n.prior12_average)
          AND year(e.trade_date)>=2019
        ORDER BY e.trade_date,e.turnover_surge_ratio,e.symbol
        """.replace("e.turnover_surge_ratio", "n.month_turnover/n.prior12_average")
    ).fetchdf()
    connection.close()
    if frame.empty or frame.duplicated(["trade_date", "symbol"]).any():
        raise SpeculativeTurnoverError("invalid feature panel")
    dates = sorted(pd.to_datetime(frame.trade_date).dt.date.unique())
    if (
        len(frame) != 131_769
        or len(dates) != 60
        or dates[0] != date(2019, 1, 31)
        or dates[-1] != date(2023, 12, 29)
    ):
        raise SpeculativeTurnoverError(
            f"feature coverage changed: rows={len(frame)} dates={len(dates)} "
            f"first={dates[0]} last={dates[-1]}"
        )
    audit["feature_rows"] = len(frame)
    audit["feature_dates"] = len(dates)
    audit["feature_symbols"] = int(frame.symbol.nunique())
    audit["minimum_monthly_candidates"] = int(frame.groupby("trade_date").size().min())
    audit["median_monthly_candidates"] = float(frame.groupby("trade_date").size().median())
    return frame, audit


def _hash_order(symbol: str, signal_date: date, seed: str) -> str:
    return hashlib.sha256(f"{symbol}|{signal_date}|{seed}".encode()).hexdigest()


def _sample_plans(frame: pd.DataFrame, calendar: list[date]) -> pd.DataFrame:
    cal_index = {day: index for index, day in enumerate(calendar)}
    work = frame.copy()
    work["trade_date"] = pd.to_datetime(work.trade_date).dt.date
    all_signal_dates = sorted(work.trade_date.unique())
    next_signal = {
        current: following
        for current, following in pairwise(all_signal_dates)
    }
    rows: list[dict[str, Any]] = []

    def add(arm: str, selected: pd.DataFrame, signal_date: date) -> None:
        for rank, item in enumerate(selected.itertuples(index=False), start=1):
            rows.append(
                {
                    "arm": arm,
                    "signal_date": signal_date,
                    "symbol": item.symbol,
                    "industry": str(item.industry),
                    "score": float(item.turnover_surge_ratio),
                    "signal_rank": rank,
                    "candidate_count": len(group),
                    "avg_amount20": float(item.avg_amount20),
                    "entry_index": cal_index[signal_date] + 1,
                    "due_index": cal_index[next_signal[signal_date]] + 1,
                }
            )

    for signal_date, raw_group in work.groupby("trade_date", sort=True):
        if signal_date not in next_signal or signal_date > date(2023, 10, 31):
            continue
        group = raw_group.sort_values(
            ["turnover_surge_ratio", "symbol"], ascending=[True, True]
        ).reset_index(drop=True)
        if len(group) < 100:
            raise SpeculativeTurnoverError(f"insufficient candidates: {signal_date}")
        group["quintile"] = np.minimum(
            np.arange(len(group), dtype=int) * 5 // len(group) + 1, 5
        )
        add("LOWEST20", group.head(20), signal_date)
        add(
            "HIGHEST20",
            group.sort_values(
                ["turnover_surge_ratio", "symbol"], ascending=[False, True]
            ).head(20),
            signal_date,
        )
        control = group.copy()
        control["hash_order"] = control.symbol.map(
            lambda symbol, current=signal_date: _hash_order(
                symbol, current, "STR-CONTROL-V1"
            )
        )
        add("DATE_CONTROL20", control.sort_values(["hash_order", "symbol"]).head(20), signal_date)
        for quintile in range(1, 6):
            sampled = group.loc[group.quintile.eq(quintile)].copy()
            sampled["hash_order"] = sampled.symbol.map(
                lambda symbol, current=signal_date: _hash_order(
                    symbol, current, "STR-V1"
                )
            )
            add(
                f"Q{quintile}_SAMPLE20",
                sampled.sort_values(["hash_order", "symbol"]).head(20),
                signal_date,
            )
    plans = pd.DataFrame(rows).sort_values(
        ["signal_date", "arm", "signal_rank", "symbol"]
    )
    if plans.empty or plans.duplicated(["arm", "signal_date", "symbol"]).any():
        raise SpeculativeTurnoverError("invalid sampled plans")
    counts = plans.groupby(["signal_date", "arm"]).size()
    if not counts.eq(20).all() or plans.signal_date.nunique() != 58:
        raise SpeculativeTurnoverError("sample arm breadth changed")
    return plans.reset_index(drop=True)


def _evaluate_one(
    plan: Any,
    row_map: dict[tuple[str, date], Any],
    calendar: list[date],
    event_decisions: dict[tuple[str, date], list[Any]],
    symbol_events: dict[str, list[Any]],
) -> dict[str, Any]:
    entry_date = calendar[int(plan.entry_index)]
    if CA._entry_blocked(plan.symbol, plan.signal_date, entry_date, symbol_events):
        return {"status": "RISK_BLOCKED_ENTRY"}
    entry = row_map.get((plan.symbol, entry_date))
    if not (
        entry is not None
        and CA.PRIOR._valid_market_row(entry)
        and int(entry.trade_status) == 1
        and bool(entry.current_day_data_tradable)
        and not bool(entry.buy_blocked_open)
    ):
        return {"status": "ENTRY_NOT_EXECUTABLE"}
    shares = 1.0 / (float(entry.open) * (1.0 + COST))
    action_cash = 0.0
    forced_effective: date | None = None
    forced_event_id: str | None = None
    final_index = min(int(plan.due_index) + 20, len(calendar) - 1)
    for cal_index in range(int(plan.entry_index), final_index + 1):
        current = calendar[cal_index]
        if forced_effective is not None and current >= forced_effective:
            raise SpeculativeTurnoverError(
                f"pre-effective exit failed:{plan.symbol}:{forced_event_id}:{forced_effective}"
            )
        row = row_map.get((plan.symbol, current))
        if row is None or not CA._holding_row_usable(row):
            raise SpeculativeTurnoverError(f"invalid holding row:{plan.symbol}:{current}")
        if (
            cal_index > int(plan.entry_index)
            and int(row.corporate_action_count or 0) > 0
        ):
            action = CA.PRIOR.PRIOR._visible_action(row)
            if action is None:
                raise SpeculativeTurnoverError(f"unresolved action:{plan.symbol}:{current}")
            multiplier, cash_per_share = action
            if multiplier != 1.0:
                raise SpeculativeTurnoverError(
                    f"share action reached effective date:{plan.symbol}:{current}"
                )
            action_cash += shares * cash_per_share
        forced = forced_effective is not None
        due = cal_index >= int(plan.due_index)
        if (forced or due) and CA._sellable(row):
            proceeds = action_cash + shares * float(row.open) * (1.0 - COST)
            return {
                "status": "COMPLETE",
                "entry_date": entry_date,
                "exit_date": current,
                "holding_sessions": cal_index - int(plan.entry_index),
                "net_return": proceeds - 1.0,
                "severe_loss": proceeds - 1.0 <= -0.10,
                "forced_exit": forced,
                "entry_amount": float(entry.amount),
            }
        for event in event_decisions.get((plan.symbol, current), ()): 
            if forced_effective is None or event.effective_date < forced_effective:
                forced_effective = event.effective_date
                forced_event_id = event.event_id
    return {"status": "EXIT_INCOMPLETE"}


def _evaluate_plans(
    plans: pd.DataFrame,
    daily_paths: list[Path],
    calendar: list[date],
    events: list[Any],
) -> pd.DataFrame:
    market_rows = CA.PRIOR._query_execution_rows(daily_paths, plans, calendar)
    row_map = {
        (row.symbol, pd.Timestamp(row.trade_date).date()): row
        for row in market_rows.itertuples(index=False)
    }
    event_decisions, symbol_events = CA._event_maps(events)
    outcomes = [
        _evaluate_one(plan, row_map, calendar, event_decisions, symbol_events)
        for plan in plans.itertuples(index=False)
    ]
    evaluated = pd.concat(
        [plans.reset_index(drop=True), pd.DataFrame(outcomes)], axis=1
    )
    evaluated["year"] = evaluated.signal_date.map(lambda value: value.year)
    return evaluated


def _period_summary(frame: pd.DataFrame, years: set[int]) -> dict[str, Any]:
    subset = frame.loc[frame.year.isin(years)].copy()
    complete = subset.loc[subset.status.eq("COMPLETE")]
    arms: dict[str, Any] = {}
    for arm, group in complete.groupby("arm", sort=True):
        returns = group.net_return.astype(float)
        arms[arm] = {
            "trades": len(group),
            "decision_dates": int(group.signal_date.nunique()),
            "mean_return": float(returns.mean()),
            "median_return": float(returns.median()),
            "winner_fraction": float((returns > 0).mean()),
            "severe_loss_fraction": float((returns <= -0.10).mean()),
        }
    required = {
        "LOWEST20",
        "HIGHEST20",
        "DATE_CONTROL20",
        "Q1_SAMPLE20",
        "Q2_SAMPLE20",
        "Q3_SAMPLE20",
        "Q4_SAMPLE20",
        "Q5_SAMPLE20",
    }
    if set(arms) != required:
        raise SpeculativeTurnoverError(f"incomplete screen arms: {set(arms)}")
    quintile_means = [arms[f"Q{index}_SAMPLE20"]["mean_return"] for index in range(1, 6)]
    lowest = arms["LOWEST20"]
    highest = arms["HIGHEST20"]
    control = arms["DATE_CONTROL20"]
    yearly_excess: dict[str, float] = {}
    for year, year_group in complete.groupby("year", sort=True):
        means = year_group.groupby("arm").net_return.mean()
        yearly_excess[str(int(year))] = float(means.LOWEST20 - means.DATE_CONTROL20)
    return {
        "years": sorted(years),
        "planned_trades": len(subset),
        "complete_trades": len(complete),
        "entry_execution_fraction": float(
            subset.status.isin(["COMPLETE", "EXIT_INCOMPLETE"]).mean()
        ),
        "arms": arms,
        "lowest20_excess_vs_control": float(
            lowest["mean_return"] - control["mean_return"]
        ),
        "lowest20_minus_highest20": float(
            lowest["mean_return"] - highest["mean_return"]
        ),
        "favorable_quintile_steps": int(
            sum(left > right for left, right in pairwise(quintile_means))
        ),
        "quintile_means": quintile_means,
        "yearly_lowest20_excess": yearly_excess,
    }


def _gate(summary: dict[str, Any], spec_gate: dict[str, Any], validation: bool) -> dict[str, bool]:
    lowest = summary["arms"]["LOWEST20"]
    control = summary["arms"]["DATE_CONTROL20"]
    prefix = "validation" if validation else "generation"
    excess_floor = spec_gate["lowest20_mean_excess_vs_date_control_minimum"]
    spread_key = (
        "lowest20_minus_highest20_positive"
        if validation
        else "lowest20_minus_highest20_minimum"
    )
    spread_threshold = 0.0 if validation else spec_gate[spread_key]
    return {
        "entry_execution": summary["entry_execution_fraction"] >= 0.90,
        "excess_floor": summary["lowest20_excess_vs_control"] >= excess_floor,
        "absolute_mean_positive": lowest["mean_return"] > 0,
        "low_minus_high": summary["lowest20_minus_highest20"] > spread_threshold,
        f"each_{prefix}_year_nonnegative": min(summary["yearly_lowest20_excess"].values()) >= 0,
        "quintile_ordering": summary["favorable_quintile_steps"] >= 3,
        "severe_not_worse": (
            lowest["severe_loss_fraction"] <= control["severe_loss_fraction"]
        ),
    }


@dataclass
class PortfolioLot:
    symbol: str
    industry: str
    due_index: int
    shares: float
    invested_cost: float
    action_cash: float = 0.0
    forced_effective_date: date | None = None
    forced_event_id: str | None = None


def _portfolio_plans(
    feature: pd.DataFrame, sampled: pd.DataFrame
) -> pd.DataFrame:
    keys = sampled[["signal_date", "entry_index", "due_index"]].drop_duplicates()
    work = feature.copy()
    work["signal_date"] = pd.to_datetime(work.trade_date).dt.date
    work = work.merge(keys, on="signal_date", how="inner", validate="many_to_one")
    work = work.sort_values(
        ["signal_date", "turnover_surge_ratio", "symbol"], ascending=[True, True, True]
    )
    selected = work.groupby("signal_date", sort=True).head(10).copy()
    selected["signal_rank"] = selected.groupby("signal_date").cumcount() + 1
    if selected.groupby("signal_date").size().ne(10).any():
        raise SpeculativeTurnoverError("portfolio Top-10 breadth changed")
    return selected[
        [
            "signal_date",
            "symbol",
            "industry",
            "signal_rank",
            "entry_index",
            "due_index",
        ]
    ].reset_index(drop=True)


def _replay(
    plans: pd.DataFrame,
    market_rows: pd.DataFrame,
    calendar: list[date],
    events: list[Any],
) -> tuple[dict[str, Any], pd.DataFrame]:
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
    lots: list[PortfolioLot] = []
    turnover = 0.0
    planned_entries = entries = risk_blocked = completed = severe = 0
    forced_exits = forced_pending = 0
    capacity: list[float] = []
    nav_rows: list[dict[str, Any]] = []
    for cal_index, current in enumerate(calendar):
        for lot in lots:
            if lot.forced_effective_date is not None and current >= lot.forced_effective_date:
                raise SpeculativeTurnoverError(
                    f"pre-effective portfolio exit failed:{lot.symbol}:"
                    f"{lot.forced_event_id}:{lot.forced_effective_date}"
                )
            row = row_map.get((lot.symbol, current))
            if row is None or not CA._holding_row_usable(row):
                raise SpeculativeTurnoverError(
                    f"invalid portfolio holding row:{lot.symbol}:{current}"
                )
            if int(row.corporate_action_count or 0) > 0:
                action = CA.PRIOR.PRIOR._visible_action(row)
                if action is None:
                    raise SpeculativeTurnoverError(
                        f"unresolved portfolio action:{lot.symbol}:{current}"
                    )
                multiplier, cash_per_share = action
                if multiplier != 1.0:
                    raise SpeculativeTurnoverError(
                        f"share action reached portfolio effective date:{lot.symbol}:{current}"
                    )
                lot.action_cash += lot.shares * cash_per_share
        survivors: list[PortfolioLot] = []
        for lot in lots:
            row = row_map[(lot.symbol, current)]
            forced = lot.forced_effective_date is not None
            due = cal_index >= lot.due_index
            if not forced and not due:
                survivors.append(lot)
                continue
            if not CA._sellable(row):
                forced_pending += int(forced)
                survivors.append(lot)
                continue
            gross = lot.shares * float(row.open)
            proceeds = lot.action_cash + gross * (1.0 - COST)
            cash += proceeds
            turnover += gross
            completed += 1
            severe += int(proceeds / lot.invested_cost - 1.0 <= -0.10)
            forced_exits += int(forced)
        lots = survivors
        planned = entry_map.get(cal_index, [])
        planned_entries += len(planned)
        executable: list[tuple[Any, Any]] = []
        for plan in planned:
            row = row_map.get((plan.symbol, current))
            if CA._entry_blocked(plan.symbol, plan.signal_date, current, symbol_events):
                risk_blocked += 1
                continue
            if (
                row is not None
                and CA.PRIOR._valid_market_row(row)
                and int(row.trade_status) == 1
                and bool(row.current_day_data_tradable)
                and not bool(row.buy_blocked_open)
            ):
                executable.append((plan, row))
        if executable and cash > 0:
            allocation = cash / len(executable)
            for plan, row in executable:
                shares = allocation / (float(row.open) * (1.0 + COST))
                gross = shares * float(row.open)
                invested = gross * (1.0 + COST)
                cash -= invested
                turnover += gross
                lots.append(
                    PortfolioLot(
                        plan.symbol,
                        str(plan.industry),
                        int(plan.due_index),
                        shares,
                        invested,
                    )
                )
                entries += 1
                capacity.append(float(row.amount) * 0.05 * len(executable))
        for lot in lots:
            for event in event_decisions.get((lot.symbol, current), ()): 
                if (
                    lot.forced_effective_date is None
                    or event.effective_date < lot.forced_effective_date
                ):
                    lot.forced_effective_date = event.effective_date
                    lot.forced_event_id = event.event_id
        nav = cash
        industries: dict[str, float] = {}
        for lot in lots:
            row = row_map[(lot.symbol, current)]
            value = lot.action_cash + lot.shares * float(row.close)
            nav += value
            industries[lot.industry] = industries.get(lot.industry, 0.0) + value
        invested_value = sum(industries.values())
        hhi = (
            sum((value / invested_value) ** 2 for value in industries.values())
            if invested_value > 0
            else 0.0
        )
        nav_rows.append(
            {
                "trade_date": current,
                "nav": nav,
                "cash": cash,
                "positions": len(lots),
                "industries": len(industries),
                "industry_hhi": hhi,
            }
        )
    if lots:
        raise SpeculativeTurnoverError(f"terminal portfolio lots:{len(lots)}")
    equity = pd.DataFrame(nav_rows)
    daily_returns = equity.nav.pct_change().fillna(
        equity.nav.iloc[0] / INITIAL_CAPITAL - 1.0
    )
    drawdown = equity.nav / equity.nav.cummax() - 1.0
    years = len(equity) / 252.0
    annualized = (equity.nav.iloc[-1] / INITIAL_CAPITAL) ** (1.0 / years) - 1.0
    volatility = daily_returns.std(ddof=1)
    sharpe = (
        math.sqrt(252.0) * daily_returns.mean() / volatility if volatility > 0 else 0.0
    )
    maximum_drawdown = float(drawdown.min())
    result = {
        "status": "COMPLETE",
        "start_date": str(equity.trade_date.iloc[0]),
        "end_date": str(equity.trade_date.iloc[-1]),
        "total_return": float(equity.nav.iloc[-1] / INITIAL_CAPITAL - 1.0),
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
        "risk_blocked_entries": risk_blocked,
        "completed_trades": completed,
        "severe_trade_fraction": float(severe / completed),
        "forced_pre_effective_exits": forced_exits,
        "forced_exit_pending_days": forced_pending,
        "terminal_open_lots": len(lots),
        "mean_positions": float(equity.positions.mean()),
        "mean_industries": float(equity.industries.mean()),
        "mean_industry_hhi_invested_days": float(
            equity.loc[equity.positions > 0, "industry_hhi"].mean()
        ),
        "p10_capacity_cny_at_5pct_amount": float(np.quantile(capacity, 0.10)),
        "median_capacity_cny_at_5pct_amount": float(np.median(capacity)),
    }
    return result, equity


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# Speculative turnover ratio V1",
        "",
        f"Status: `{result['status']}`.",
        "",
        "The frozen score is completed-calendar-month turnover divided by the "
        "stock's own preceding twelve complete monthly turnover totals. Lower is "
        "preferred. This is a simple turnover-surge hypothesis, not a claim to "
        "replicate Pan et al.'s event-dummy residual ATR.",
        "",
    ]
    generation = result["generation"]
    lines += [
        "## Generation 2019-2020",
        "",
        f"Lowest-20 mean {generation['arms']['LOWEST20']['mean_return']:.3%}; "
        f"excess versus control {generation['lowest20_excess_vs_control']:+.3%}; "
        f"low-minus-high {generation['lowest20_minus_highest20']:+.3%}; "
        f"favorable quintile steps {generation['favorable_quintile_steps']}/4; "
        f"passed `{result['generation_passed']}`.",
        "",
    ]
    if result["validation_opened"]:
        validation = result["validation"]
        lines += [
            "## Fixed validation 2021-2023",
            "",
            f"Lowest-20 mean {validation['arms']['LOWEST20']['mean_return']:.3%}; "
            f"excess versus control {validation['lowest20_excess_vs_control']:+.3%}; "
            f"low-minus-high {validation['lowest20_minus_highest20']:+.3%}; "
            f"favorable quintile steps {validation['favorable_quintile_steps']}/4; "
            f"passed `{result['validation_passed']}`.",
            "",
        ]
    else:
        lines += ["Fixed validation remained unopened.", ""]
    if result["replay"] is not None:
        replay = result["replay"]
        lines += [
            "## Executable Top-10 replay",
            "",
            f"Annualized {replay['annualized_return']:.2%}; total "
            f"{replay['total_return']:.2%}; maximum drawdown "
            f"{replay['maximum_drawdown']:.2%}; Sharpe "
            f"{replay['daily_sharpe']:.3f}; target met "
            f"`{result['target_met']}`.",
            "",
        ]
    lines += [
        "No neighboring turnover window, normalizer, Top-N, holding rule, habitat, "
        "or Champion combination was tested. Post-2023 outcomes and CY-011 were not read.",
        "",
    ]
    return "\n".join(lines)


def run() -> dict[str, Any]:
    spec = _load_spec()
    ca_spec = CA._load_spec()
    daily_paths, calendar, input_identity = CA._load_market_inputs(ca_spec)
    feature, audit = _feature_panel(daily_paths)
    sampled = _sample_plans(feature, calendar)
    events, action_audit = CA._load_risk_events(ca_spec, calendar)
    generation_plans = sampled.loc[
        sampled.signal_date.map(lambda value: value.year).isin(GENERATION_YEARS)
    ]
    generation_evaluated = _evaluate_plans(
        generation_plans, daily_paths, calendar, events
    )
    generation = _period_summary(generation_evaluated, GENERATION_YEARS)
    generation_gates = _gate(
        generation, spec["cheap_screen"]["generation_gate_all_required"], False
    )
    generation_passed = all(generation_gates.values())
    evaluated_frames = [generation_evaluated]
    validation_opened = generation_passed
    validation: dict[str, Any] | None = None
    validation_gates: dict[str, bool] | None = None
    validation_passed = False
    if validation_opened:
        validation_plans = sampled.loc[
            sampled.signal_date.map(lambda value: value.year).isin(VALIDATION_YEARS)
        ]
        validation_evaluated = _evaluate_plans(
            validation_plans, daily_paths, calendar, events
        )
        evaluated_frames.append(validation_evaluated)
        validation = _period_summary(validation_evaluated, VALIDATION_YEARS)
        validation_gates = _gate(
            validation, spec["cheap_screen"]["validation_gate_all_required"], True
        )
        validation_passed = all(validation_gates.values())
    screen = pd.concat(evaluated_frames, ignore_index=True)
    replay: dict[str, Any] | None = None
    equity = pd.DataFrame()
    target_met = False
    if generation_passed and validation_passed:
        portfolio_plans = _portfolio_plans(feature, sampled)
        market_rows = CA.PRIOR._query_execution_rows(
            daily_paths, portfolio_plans, calendar
        )
        replay, equity = _replay(portfolio_plans, market_rows, calendar, events)
        target = spec["success_target"]
        target_met = bool(
            replay["annualized_return"] >= target["minimum_annualized_return"]
            and replay["maximum_drawdown"]
            > target["maximum_drawdown_must_be_greater_than"]
        )
    status = (
        "TARGET_ACHIEVED"
        if target_met
        else "REPLAY_TARGET_NOT_MET"
        if replay is not None
        else "VALIDATION_REJECTED"
        if validation_opened
        else "GENERATION_REJECTED_VALIDATION_UNOPENED"
    )
    _atomic_write(
        SCREEN_PATH,
        screen.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )
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
        "maximum_outcome_date": "2023-12-29",
        "input_identity": input_identity,
        "input_audit": audit,
        "action_audit": action_audit,
        "sampled_signal_dates": int(sampled.signal_date.nunique()),
        "generation": generation,
        "generation_gates": generation_gates,
        "generation_passed": generation_passed,
        "validation_opened": validation_opened,
        "validation": validation,
        "validation_gates": validation_gates,
        "validation_passed": validation_passed,
        "replay": replay,
        "target": spec["success_target"],
        "target_met": target_met,
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "screen_sha256": sha256_file(SCREEN_PATH),
            "equity_sha256": sha256_file(EQUITY_PATH),
        },
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    _atomic_write(REPORT_PATH, _render(result))
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
