#!/usr/bin/env python3
"""Test one frozen causal winner-only extension of the Strategy-A lifecycle."""

from __future__ import annotations

import argparse
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
EXPERIMENT_ID = "ASHARE-CHAMPION-WINNER-EXTENSION-V1"
SPEC_PATH = PROGRAM / f"experiments/{EXPERIMENT_ID}_spec.json"
REPORT_PATH = PROGRAM / f"reports/{EXPERIMENT_ID}_report.md"
CYCLE016_PATH = PROGRAM / "scripts/run_ashare_champion_anatomy_cycle_016.py"
CA_PATH = PROGRAM / "scripts/run_ashare_ca_replay_003.py"
EXPECTED_SPEC_SHA256 = "a56703f3b2dbd72e250ec18e22cdd22a10da471b639387a2abcc7bfa14b5b5a9"
FAMILY = "industry_diffusion_low_max"
INITIAL_CAPITAL = 10_000_000.0
BASE_HORIZON = 20
EXTENDED_HORIZON = 40
COHORT_DIVISOR = 4


class WinnerExtensionError(RuntimeError):
    """Fail-closed winner-extension experiment error."""


@dataclass
class ExtensionLot:
    symbol: str
    industry: str
    base_due_index: int
    max_due_index: int
    due_index: int
    shares: float
    invested_cost: float
    action_cash: float = 0.0
    extension_checked: bool = False
    extended: bool = False
    base_net_mark: float | None = None
    forced_effective_date: date | None = None
    forced_event_id: str | None = None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise WinnerExtensionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


CYCLE016 = _load_module("ashare_cycle016_for_winner_extension", CYCLE016_PATH)
CONSTRUCTION = CYCLE016.CONSTRUCTION
CA = _load_module("ashare_ca_for_winner_extension", CA_PATH)


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
        raise WinnerExtensionError("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_GENERATION_OUTCOMES":
        raise WinnerExtensionError("spec is not frozen")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise WinnerExtensionError(f"bound input changed: {name}")
    CYCLE016._load_spec()
    CA._load_spec()
    return spec


def _stage_paths(stage: str) -> tuple[Path, Path, Path]:
    prefix = PROGRAM / f"artifacts/{EXPERIMENT_ID}_{stage}"
    return (
        prefix.with_name(prefix.name + "_equity.csv"),
        prefix.with_name(prefix.name + "_exits.csv"),
        prefix.with_name(prefix.name + "_result.json"),
    )


def _make_plans(
    selections: pd.DataFrame,
    calendar: list[date],
    years: set[int],
    cutoff: date,
) -> pd.DataFrame:
    index = {day: position for position, day in enumerate(calendar)}
    cutoff_index = max(position for position, day in enumerate(calendar) if day <= cutoff)
    rows: list[dict[str, Any]] = []
    for item in selections.itertuples(index=False):
        signal_date = pd.Timestamp(item.trade_date).date()
        if signal_date.year not in years:
            continue
        entry_index = index[signal_date] + 1
        base_due_index = entry_index + BASE_HORIZON
        max_due_index = entry_index + EXTENDED_HORIZON
        if max_due_index > cutoff_index:
            continue
        rows.append(
            {
                "family": FAMILY,
                "signal_date": signal_date,
                "symbol": item.symbol,
                "industry": str(item.industry),
                "entry_index": entry_index,
                "base_due_index": base_due_index,
                "max_due_index": max_due_index,
                "due_index": base_due_index,
                "horizon": BASE_HORIZON,
            }
        )
    plans = pd.DataFrame(rows)
    if plans.empty:
        raise WinnerExtensionError("no stage plans")
    counts = plans.groupby("signal_date").size()
    if not counts.eq(10).all():
        raise WinnerExtensionError("stage plan breadth changed")
    return plans


def _query_execution_rows(
    paths: list[Path], plans: pd.DataFrame, calendar: list[date], cutoff: date
) -> pd.DataFrame:
    cutoff_index = max(position for position, day in enumerate(calendar) if day <= cutoff)
    keys: set[tuple[str, date]] = set()
    for row in plans.itertuples(index=False):
        stop = min(int(row.max_due_index) + 21, cutoff_index + 1)
        for index in range(int(row.entry_index), stop):
            keys.add((row.symbol, calendar[index]))
    key_frame = pd.DataFrame(sorted(keys), columns=["symbol", "trade_date"])
    connection = duckdb.connect(database=":memory:")
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
    if rows.empty or rows.duplicated(["symbol", "trade_date"]).any():
        raise WinnerExtensionError("invalid execution rows")
    if pd.to_datetime(rows.trade_date).dt.date.max() > cutoff:
        raise WinnerExtensionError("stage queried an outcome beyond its cutoff")
    return rows


def _metrics(
    equity: pd.DataFrame,
    turnover: float,
    planned_entries: int,
    entries: int,
    completed: int,
    severe: int,
    risk_blocked_entries: int,
    forced_exits: int,
    forced_pending_days: int,
    capacity: list[float],
) -> dict[str, Any]:
    returns = equity.nav.pct_change().fillna(equity.nav.iloc[0] / INITIAL_CAPITAL - 1.0)
    drawdown = equity.nav / equity.nav.cummax() - 1.0
    years = len(equity) / 252.0
    annualized = (equity.nav.iloc[-1] / INITIAL_CAPITAL) ** (1.0 / years) - 1.0
    volatility = returns.std(ddof=1)
    sharpe = math.sqrt(252.0) * returns.mean() / volatility if volatility > 0 else 0.0
    maximum_drawdown = float(drawdown.min())
    return {
        "start_date": str(equity.trade_date.iloc[0]),
        "end_date": str(equity.trade_date.iloc[-1]),
        "total_return": float(equity.nav.iloc[-1] / INITIAL_CAPITAL - 1.0),
        "annualized_return": float(annualized),
        "maximum_drawdown": maximum_drawdown,
        "daily_sharpe": float(sharpe),
        "calmar": float(annualized / abs(maximum_drawdown)) if maximum_drawdown < 0 else None,
        "turnover_multiple_initial_capital": float(turnover / INITIAL_CAPITAL),
        "planned_entries": planned_entries,
        "entries": entries,
        "entry_execution_fraction": float(entries / planned_entries),
        "risk_blocked_entries": risk_blocked_entries,
        "completed_trades": completed,
        "severe_trade_fraction": float(severe / completed),
        "forced_pre_effective_exits": forced_exits,
        "forced_exit_pending_days": forced_pending_days,
        "p10_capacity_cny_at_5pct_amount": float(np.quantile(capacity, 0.10)),
        "median_capacity_cny_at_5pct_amount": float(np.median(capacity)),
    }


def _replay_extension(
    plans: pd.DataFrame,
    market_rows: pd.DataFrame,
    calendar: list[date],
    events: list[Any],
    cutoff: date,
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
    cutoff_index = max(position for position, day in enumerate(calendar) if day <= cutoff)
    cash = INITIAL_CAPITAL
    lots: list[ExtensionLot] = []
    turnover = 0.0
    planned_entries = 0
    entries = 0
    risk_blocked_entries = 0
    completed = 0
    severe = 0
    forced_exits = 0
    forced_pending_days = 0
    extension_decisions = 0
    extensions = 0
    capital_constrained_cohorts = 0
    allocation_fractions: list[float] = []
    capacity: list[float] = []
    nav_rows: list[dict[str, Any]] = []
    exit_rows: list[dict[str, Any]] = []
    start_index = int(plans.entry_index.min())
    final_index = min(int(plans.max_due_index.max()) + 20, cutoff_index)

    for cal_index in range(start_index, final_index + 1):
        current_date = calendar[cal_index]
        for lot in lots:
            if lot.forced_effective_date is not None and current_date >= lot.forced_effective_date:
                raise WinnerExtensionError(
                    f"pre-effective exit failed:{lot.symbol}:{lot.forced_event_id}:"
                    f"{lot.forced_effective_date}"
                )
            row = row_map.get((lot.symbol, current_date))
            if row is None or not CA._holding_row_usable(row):
                raise WinnerExtensionError(f"invalid holding row:{lot.symbol}:{current_date}")
            if int(row.corporate_action_count or 0) > 0:
                action = CA.PRIOR.PRIOR._visible_action(row)
                if action is None:
                    raise WinnerExtensionError(
                        f"unresolved effective action:{lot.symbol}:{current_date}"
                    )
                multiplier, cash_per_share = action
                if multiplier != 1.0:
                    raise WinnerExtensionError(
                        f"share risk event reached effective date:{lot.symbol}:{current_date}"
                    )
                lot.action_cash += lot.shares * cash_per_share

        survivors: list[ExtensionLot] = []
        for lot in lots:
            row = row_map[(lot.symbol, current_date)]
            forced = lot.forced_effective_date is not None
            if not forced and cal_index >= lot.base_due_index and not lot.extension_checked:
                prior_date = calendar[cal_index - 1]
                prior = row_map.get((lot.symbol, prior_date))
                if prior is None or not CA._holding_row_usable(prior):
                    raise WinnerExtensionError(
                        f"invalid causal extension row:{lot.symbol}:{prior_date}"
                    )
                hypothetical = lot.action_cash + lot.shares * float(prior.close) * (1.0 - CA.COST)
                lot.base_net_mark = float(hypothetical / lot.invested_cost - 1.0)
                lot.extension_checked = True
                extension_decisions += 1
                if hypothetical > lot.invested_cost:
                    lot.extended = True
                    lot.due_index = lot.max_due_index
                    extensions += 1
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
            payoff = float(proceeds / lot.invested_cost - 1.0)
            severe += int(payoff <= -0.10)
            forced_exits += int(forced)
            exit_rows.append(
                {
                    "symbol": lot.symbol,
                    "industry": lot.industry,
                    "fill_date": current_date,
                    "exit_reason": "FORCED" if forced else ("H40" if lot.extended else "H20"),
                    "extended": lot.extended,
                    "base_net_mark": lot.base_net_mark,
                    "final_net_return": payoff,
                    "second_leg_delta": (
                        payoff - lot.base_net_mark
                        if lot.extended and lot.base_net_mark is not None
                        else None
                    ),
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
            if CA._entry_blocked(plan.symbol, plan.signal_date, current_date, symbol_events):
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
        target_capital = pre_entry_nav / COHORT_DIVISOR
        cohort_capital = min(cash, target_capital)
        if planned and cohort_capital + 1e-8 < target_capital:
            capital_constrained_cohorts += 1
        if planned:
            allocation_fractions.append(float(cohort_capital / target_capital))
        if executable and cohort_capital > 1e-8:
            allocation = cohort_capital / len(executable)
            for plan, row in executable:
                shares = allocation / (float(row.open) * (1.0 + CA.COST))
                gross = shares * float(row.open)
                invested = gross * (1.0 + CA.COST)
                cash -= invested
                turnover += gross
                lots.append(
                    ExtensionLot(
                        symbol=plan.symbol,
                        industry=str(plan.industry),
                        base_due_index=int(plan.base_due_index),
                        max_due_index=int(plan.max_due_index),
                        due_index=int(plan.base_due_index),
                        shares=shares,
                        invested_cost=invested,
                    )
                )
                entries += 1
                capacity.append(float(row.amount) * 0.05 * len(executable) * COHORT_DIVISOR)

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
                "family": "winner_extension",
                "nav": nav,
                "cash": cash,
                "positions": len(lots),
                "industries": len(industry_values),
                "industry_hhi": hhi,
            }
        )
        if cal_index >= int(plans.max_due_index.max()) and not lots and cal_index not in entry_map:
            break

    equity = pd.DataFrame(nav_rows)
    if lots:
        raise WinnerExtensionError(f"terminal open lots at stage cutoff:{len(lots)}")
    result = _metrics(
        equity,
        turnover,
        planned_entries,
        entries,
        completed,
        severe,
        risk_blocked_entries,
        forced_exits,
        forced_pending_days,
        capacity,
    )
    exits = pd.DataFrame(exit_rows)
    extended = exits.loc[exits.extended.eq(True)]
    result.update(
        {
            "extension_decisions": extension_decisions,
            "extended_positions": extensions,
            "extension_fraction": float(extensions / extension_decisions),
            "extended_mean_base_net_mark": float(extended.base_net_mark.mean()),
            "extended_mean_final_net_return": float(extended.final_net_return.mean()),
            "extended_mean_second_leg_delta": float(extended.second_leg_delta.mean()),
            "extended_median_second_leg_delta": float(extended.second_leg_delta.median()),
            "extended_positive_second_leg_fraction": float(extended.second_leg_delta.gt(0).mean()),
            "capital_constrained_cohorts": capital_constrained_cohorts,
            "mean_cohort_allocation_fraction": float(np.mean(allocation_fractions)),
            "minimum_cohort_allocation_fraction": float(np.min(allocation_fractions)),
            "mean_positions": float(equity.positions.mean()),
            "mean_industries": float(equity.industries.mean()),
            "mean_industry_hhi_invested_days": float(
                equity.loc[equity.positions > 0, "industry_hhi"].mean()
            ),
        }
    )
    return result, equity, exits


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


def _generation_gate(spec: dict[str, Any], result: dict[str, Any]) -> dict[str, bool]:
    gate = spec["chronological_protocol"]["generation"]["all_required_to_open_validation"]
    candidate = result["candidate"]
    comparison = result["comparison"]
    return {
        "extended_positions": candidate["extended_positions"] >= gate["minimum_extended_positions"],
        "candidate_annualized": candidate["annualized_return"]
        >= gate["minimum_candidate_annualized_return"],
        "annualized_delta": comparison["annualized_return_delta"]
        >= gate["minimum_annualized_delta_vs_same-plan_h20"],
        "drawdown_not_worse": comparison["maximum_drawdown_improvement"] >= 0,
        "sharpe_not_worse": comparison["daily_sharpe_delta"] >= 0,
    }


def _render(result: dict[str, Any]) -> str:
    baseline = result["baseline"]
    candidate = result["candidate"]
    comparison = result["comparison"]
    lines = [
        "# Champion winner-only extension V1",
        "",
        f"Stage: `{result['stage']}`. Status: `{result['status']}`.",
        "",
        (
            "At the unchanged h20 due open, retain only a position whose hypothetical "
            "net liquidation value using the preceding completed close is already above "
            "its invested cost; retain it to h40. All others keep the frozen h20 exit."
        ),
        "",
        (
            f"Same-plan h20 baseline: annualized {baseline['annualized_return']:.2%}, "
            f"max drawdown {baseline['maximum_drawdown']:.2%}, Sharpe "
            f"{baseline['daily_sharpe']:.3f}."
        ),
        (
            f"Winner extension: annualized {candidate['annualized_return']:.2%}, max "
            f"drawdown {candidate['maximum_drawdown']:.2%}, Sharpe "
            f"{candidate['daily_sharpe']:.3f}."
        ),
        (
            f"Delta: annualized {comparison['annualized_return_delta']:+.2%}, drawdown "
            f"quality {comparison['maximum_drawdown_improvement']:+.2%}, Sharpe "
            f"{comparison['daily_sharpe_delta']:+.3f}."
        ),
        (
            f"Extended {candidate['extended_positions']}/{candidate['extension_decisions']} "
            f"positions. Their mean h20-to-h40 payoff delta was "
            f"{candidate['extended_mean_second_leg_delta']:+.2%}; mean cohort funding "
            f"was {candidate['mean_cohort_allocation_fraction']:.1%}."
        ),
        "",
    ]
    if result["stage"] == "generation":
        lines.extend(
            [
                f"Generation gates: `{json.dumps(result['generation_gates'], sort_keys=True)}`.",
                (
                    "Validation remains unopened." if not result["generation_gate_passed"]
                    else "The frozen validation stage is authorized without any rule change."
                ),
                "",
            ]
        )
    lines.extend(
        [
            "This is consumed-history development optimization, not independent confirmation. "
            "Post-2023 outcomes and CY-011 were not read.",
            "",
        ]
    )
    return "\n".join(lines)


def _run_stage(stage: str, spec: dict[str, Any]) -> dict[str, Any]:
    stage_spec = spec["chronological_protocol"][stage]
    cutoff = date.fromisoformat(stage_spec["maximum_outcome_date"])
    paths, calendar, input_identity = CA._load_market_inputs(CA._load_spec())
    anatomy_spec = json.loads(
        _resolve(spec["inputs"]["champion_anatomy_spec"]["path"]).read_text(encoding="utf-8")
    )
    daily = pd.read_parquet(_resolve(anatomy_spec["inputs"]["causal_daily_panel"]["path"]))
    construction_spec = CONSTRUCTION._load_spec()
    _, champion = CYCLE016.CYCLE015._weekly_selections(daily, construction_spec)
    plans = _make_plans(champion, calendar, set(stage_spec["signal_years"]), cutoff)
    market_rows = _query_execution_rows(paths, plans, calendar, cutoff)
    events, action_audit = CA._load_risk_events(CA._load_spec(), calendar)

    baseline_plans = plans[
        ["family", "signal_date", "symbol", "industry", "entry_index", "due_index", "horizon"]
    ].copy()
    baseline, baseline_equity, baseline_exits = CA._replay(
        FAMILY, baseline_plans, market_rows, calendar, events
    )
    candidate, candidate_equity, candidate_exits = _replay_extension(
        plans, market_rows, calendar, events, cutoff
    )
    comparison = _comparison(candidate, baseline)
    equity = pd.concat(
        [
            baseline_equity.assign(replay="same_plan_h20"),
            candidate_equity.assign(replay="winner_extension"),
        ],
        ignore_index=True,
    )
    exits = candidate_exits.copy()
    result: dict[str, Any] = {
        "experiment_id": EXPERIMENT_ID,
        "stage": stage,
        "status": "STAGE_COMPLETE",
        "claim_boundary": spec["claim_boundary"],
        "post_2023_outcome_read": "NO",
        "cy011_read": "NO",
        "maximum_outcome_date": cutoff.isoformat(),
        "signal_years": stage_spec["signal_years"],
        "decision_dates": int(plans.signal_date.nunique()),
        "plans": len(plans),
        "baseline": baseline,
        "candidate": candidate,
        "comparison": comparison,
        "baseline_calendar_year_returns": _year_returns(baseline_equity),
        "candidate_calendar_year_returns": _year_returns(candidate_equity),
        "baseline_forced_exit_rows": len(baseline_exits),
        "candidate_exit_rows": len(candidate_exits),
        "input_identity": input_identity,
        "action_audit": action_audit,
    }
    if stage == "generation":
        gates = _generation_gate(spec, result)
        result["generation_gates"] = gates
        result["generation_gate_passed"] = all(gates.values())
        result["status"] = (
            "GENERATION_GATE_PASSED_VALIDATION_AUTHORIZED"
            if result["generation_gate_passed"]
            else "GENERATION_REJECTED_VALIDATION_UNOPENED"
        )
    equity_path, exits_path, result_path = _stage_paths(stage)
    _atomic_write(
        equity_path,
        equity.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )
    _atomic_write(
        exits_path,
        exits.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )
    result["hashes"] = {
        "spec_sha256": sha256_file(SPEC_PATH),
        "equity_sha256": sha256_file(equity_path),
        "exits_sha256": sha256_file(exits_path),
    }
    _atomic_write(result_path, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    _atomic_write(REPORT_PATH, _render(result))
    return result


def run(stage: str) -> dict[str, Any]:
    spec = _load_spec()
    generation_result_path = _stage_paths("generation")[2]
    if stage == "validation":
        if not generation_result_path.is_file():
            raise WinnerExtensionError("generation result missing")
        generation = json.loads(generation_result_path.read_text(encoding="utf-8"))
        if (
            generation.get("status") != "GENERATION_GATE_PASSED_VALIDATION_AUTHORIZED"
            or generation.get("hashes", {}).get("spec_sha256") != EXPECTED_SPEC_SHA256
        ):
            raise WinnerExtensionError("validation is not authorized")
    return _run_stage(stage, spec)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("generation", "validation"), default="generation")
    arguments = parser.parse_args()
    print(json.dumps(_clean(run(arguments.stage)), indent=2, sort_keys=True))
