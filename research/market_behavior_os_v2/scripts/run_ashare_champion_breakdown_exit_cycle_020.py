#!/usr/bin/env python3
# ruff: noqa: E501
"""Test the frozen confirmed-L20-breakdown exit inside the frozen champion."""

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
SPEC_PATH = PROGRAM / "experiments/ASHARE-CHAMPION-BREAKDOWN-EXIT-CYCLE-020_spec.json"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-BREAKDOWN-EXIT-CYCLE-020_result.json"
INCIDENCE_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-BREAKDOWN-EXIT-CYCLE-020_incidence.csv"
PATH_SUMMARY_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-BREAKDOWN-EXIT-CYCLE-020_path.csv"
YEAR_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-BREAKDOWN-EXIT-CYCLE-020_year.csv"
REPORT_PATH = PROGRAM / "reports/ASHARE-CHAMPION-BREAKDOWN-EXIT-CYCLE-020_report.md"
EXTERNAL_ROOT = Path("/Volumes/quant/CY_quant_research/champion_breakdown_exit_cycle_020")
EVENT_PANEL_PATH = EXTERNAL_ROOT / "breakdown_event_panel.parquet"
EQUITY_PATH = EXTERNAL_ROOT / "breakdown_exit_equity.parquet"
TRADE_PATH = EXTERNAL_ROOT / "breakdown_exit_trades.parquet"
ANATOMY_PATH = PROGRAM / "scripts/run_ashare_champion_anatomy_cycle_016.py"
EXPECTED_SPEC_SHA256 = "e94970fd8e788778953c308d6a0d579a917c668cbbb97ed1212586444298cc90"
INITIAL_CAPITAL = 10_000_000.0
SEVERE = -0.10


class Cycle020Error(RuntimeError):
    """Fail-closed Cycle 020 error."""


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
        raise Cycle020Error(f"cannot load bound runner: {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


ANATOMY = _load_module("champion_anatomy_for_cycle020", ANATOMY_PATH)


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise Cycle020Error("frozen Cycle-020 spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_CHAMPION_CONDITIONAL_BREAKDOWN_OUTCOMES":
        raise Cycle020Error("Cycle-020 semantics were not frozen before outcomes")
    for role, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise Cycle020Error(f"bound input changed: {role}")
    recovered = spec["recovered_confirmed_breakdown"]
    if recovered["breakdown_condition"] != (
        "event-date causal-coordinate close strictly below the frozen prior-L20 support"
    ):
        raise Cycle020Error("confirmed-breakdown definition changed")
    if spec["event_and_execution"]["event_day_intraday_fill"] is not False:
        raise Cycle020Error("close-confirmed signal cannot fill intraday on the event date")
    return spec


def _build_support_rows(paths: list[Path], symbols: list[str], temp_path: Path) -> pd.DataFrame:
    connection = duckdb.connect()
    connection.execute("SET memory_limit='6GB'")
    connection.execute("SET threads=1")
    connection.execute(f"SET temp_directory='{temp_path.as_posix()}'")
    connection.register("selected_symbols", pd.DataFrame({"symbol": symbols}))
    connection.from_parquet([str(path) for path in paths], union_by_name=True).create_view(
        "source"
    )
    connection.execute("""
      CREATE TEMP TABLE calendar AS
      SELECT trade_date,row_number() OVER(ORDER BY trade_date)-1 cal_idx
      FROM (SELECT DISTINCT trade_date FROM source WHERE trade_date<=DATE '2023-12-29')
    """)
    connection.execute("""
      CREATE TEMP TABLE base0 AS SELECT s.*,c.cal_idx,
        (s.hard_valid IS TRUE AND s.bar_valid IS TRUE AND s.trading_state_valid IS TRUE
         AND s.industry_valid IS TRUE AND s.float_valid IS TRUE
         AND s.corporate_action_valid IS TRUE AND s.market_valid IS TRUE
         AND s.market_rule_valid IS TRUE AND s.historical_identity_valid IS TRUE
         AND s.corporate_action_blocking IS FALSE AND coalesce(s.rights_ratio,0)=0
         AND s.available_at IS NOT NULL AND s.available_at<=s.decision_at
         AND s.open>0 AND s.high>=greatest(s.open,s.close)
         AND s.low<=least(s.open,s.close) AND s.close>0 AND s.volume>=0 AND s.amount>=0)
          history_valid,
        (s.hard_valid IS TRUE AND s.trade_status=1
         AND s.current_day_data_tradable IS TRUE AND s.is_st IS FALSE) current_valid
      FROM source s JOIN selected_symbols x USING(symbol) JOIN calendar c USING(trade_date)
      WHERE s.trade_date<=DATE '2023-12-29'
    """)
    connection.execute("""
      CREATE TEMP TABLE base AS SELECT *,
        lag(close) OVER w previous_close,lag(cal_idx) OVER w previous_cal_idx,
        lag(history_valid) OVER w previous_history_valid
      FROM base0 WINDOW w AS(PARTITION BY symbol ORDER BY trade_date)
    """)
    connection.execute("""
      CREATE TEMP TABLE steps AS SELECT *,CASE
        WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
         AND coalesce(corporate_action_count,0)=0 THEN ln(close/previous_close)
        WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
         AND corporate_action_count>0 AND corporate_action_available_date IS NOT NULL
         AND corporate_action_available_date<=trade_date AND coalesce(rights_ratio,0)=0
         AND coalesce(share_multiplier,1)>0 AND previous_close-coalesce(cash_per_share,0)>0
        THEN ln(close/((previous_close-coalesce(cash_per_share,0))/coalesce(share_multiplier,1)))
        ELSE NULL END step_return
      FROM base
    """)
    connection.execute("""
      CREATE TEMP TABLE coordinates AS SELECT *,
        exp(sum(coalesce(step_return,0)) OVER(PARTITION BY symbol ORDER BY trade_date)) coordinate_close,
        exp(sum(coalesce(step_return,0)) OVER(PARTITION BY symbol ORDER BY trade_date))*low/close coordinate_low
      FROM steps
    """)
    output = connection.execute("""
      SELECT *,min(coordinate_low) OVER p20 support_l20,
        count(*) OVER p20 prior20_count,
        count(step_return) OVER p20 prior20_valid,
        lag(cal_idx,20) OVER(PARTITION BY symbol ORDER BY trade_date) cal_idx_lag20
      FROM coordinates
      WINDOW p20 AS(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)
      ORDER BY trade_date,symbol
    """).fetchdf()
    connection.close()
    output["trade_date"] = pd.to_datetime(output.trade_date).dt.date
    output["breakdown_representable"] = (
        output.history_valid.fillna(False)
        & output.current_valid.fillna(False)
        & output.prior20_count.eq(20)
        & output.prior20_valid.eq(20)
        & output.cal_idx.sub(output.cal_idx_lag20).eq(20)
    )
    output["confirmed_breakdown"] = output.breakdown_representable & output.coordinate_close.lt(
        output.support_l20
    )
    if output.duplicated(["symbol", "trade_date"]).any():
        raise Cycle020Error("duplicate support rows")
    return output


def _visible_action(row: Any) -> tuple[float, float] | None:
    return ANATOMY.CA.PRIOR.PRIOR._visible_action(row)


def _lot_path(
    trade: Any,
    row_map: dict[tuple[str, date], Any],
    calendar: list[date],
    cost: float,
) -> dict[date, dict[str, float]]:
    cal_index = {day: index for index, day in enumerate(calendar)}
    entry_index = cal_index[trade.entry_date]
    exit_index = cal_index[trade.exit_date]
    entry_row = row_map[(trade.symbol, trade.entry_date)]
    shares = float(trade.invested_cost) / (float(entry_row.open) * (1.0 + cost))
    action_cash = 0.0
    output: dict[date, dict[str, float]] = {}
    for index in range(entry_index, exit_index + 1):
        day = calendar[index]
        row = row_map[(trade.symbol, day)]
        if not ANATOMY.CA._holding_row_usable(row):
            raise Cycle020Error(f"unusable holding row:{trade.trade_id}:{day}")
        if int(row.corporate_action_count or 0) > 0:
            action = _visible_action(row)
            if action is None:
                raise Cycle020Error(f"unresolved action:{trade.trade_id}:{day}")
            multiplier, cash_per_share = action
            if multiplier != 1.0:
                raise Cycle020Error(f"share action reached active lot:{trade.trade_id}:{day}")
            action_cash += shares * cash_per_share
        output[day] = {
            "open_proceeds": action_cash + shares * float(row.open) * (1.0 - cost),
            "close_proceeds": action_cash + shares * float(row.close) * (1.0 - cost),
            "low_proceeds": action_cash + shares * float(row.low) * (1.0 - cost),
            "shares": shares,
            "action_cash": action_cash,
        }
    return output


def _holding_age_bucket(age: int) -> str:
    if age == 0:
        return "day_0"
    if age <= 5:
        return "days_1_5"
    if age <= 10:
        return "days_6_10"
    if age <= 15:
        return "days_11_15"
    return "days_16_20"


def _build_incidence_and_paths(
    trades: pd.DataFrame,
    support: pd.DataFrame,
    market_rows: pd.DataFrame,
    calendar: list[date],
    cost: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    cal_index = {day: index for index, day in enumerate(calendar)}
    market_rows = market_rows.copy()
    market_rows["trade_date"] = pd.to_datetime(market_rows.trade_date).dt.date
    market_rows = market_rows.merge(
        support[["symbol", "trade_date", "low"]],
        on=["symbol", "trade_date"],
        how="left",
        validate="one_to_one",
    )
    if market_rows.low.isna().any():
        raise Cycle020Error("missing low for a champion holding row")
    support_map = {
        (row.symbol, row.trade_date): row for row in support.itertuples(index=False)
    }
    row_map = {
        (row.symbol, row.trade_date): row
        for row in market_rows.itertuples(index=False)
    }
    trade_rows = list(trades.itertuples(index=False))
    first_breakdown: dict[str, date | None] = {}
    active_by_date: dict[date, list[Any]] = {}
    paths: dict[str, dict[date, dict[str, float]]] = {}
    for trade in trade_rows:
        paths[trade.trade_id] = _lot_path(trade, row_map, calendar, cost)
        entry_i = cal_index[trade.entry_date]
        exit_i = cal_index[trade.exit_date]
        found = None
        for index in range(entry_i, exit_i):
            day = calendar[index]
            active_by_date.setdefault(day, []).append(trade)
            state = support_map.get((trade.symbol, day))
            if found is None and state is not None and bool(state.confirmed_breakdown):
                found = day
        first_breakdown[trade.trade_id] = found

    incidence_rows: list[dict[str, Any]] = []
    for trade in trade_rows:
        event_date = first_breakdown[trade.trade_id]
        if event_date is None:
            continue
        event_index = cal_index[event_date]
        fill_date = None
        for index in range(event_index + 1, cal_index[trade.exit_date] + 1):
            day = calendar[index]
            row = row_map.get((trade.symbol, day))
            if row is not None and ANATOMY.CA._sellable(row):
                fill_date = day
                break
        age = event_index - cal_index[trade.entry_date]
        at_breakdown_sellable = trade.entry_date < event_date
        actionable = fill_date is not None and fill_date < trade.exit_date
        incidence_rows.append(
            {
                "trade_id": trade.trade_id,
                "symbol": trade.symbol,
                "industry": trade.industry,
                "signal_date": trade.signal_date,
                "entry_date": trade.entry_date,
                "frozen_exit_date": trade.exit_date,
                "event_date": event_date,
                "fill_date": fill_date,
                "holding_age": age,
                "holding_age_bucket": _holding_age_bucket(age),
                "block": "early" if event_date.year <= 2021 else "late",
                "event_year": event_date.year,
                "sellable_at_breakdown": at_breakdown_sellable,
                "fill_delayed": fill_date is not None and cal_index[fill_date] > event_index + 1,
                "actionable_before_frozen_exit": actionable,
                "no_incremental_headroom": fill_date == trade.exit_date,
                "unexecuted_before_frozen_exit": fill_date is None,
                "original_net_return": float(trade.final_net_return),
                "invested_cost": float(trade.invested_cost),
            }
        )
    incidence = pd.DataFrame(incidence_rows)
    if incidence.empty:
        return incidence, pd.DataFrame()

    # Group-level T+1 state at confirmation, before next-session execution.
    group_stats = incidence.groupby(["symbol", "event_date"], sort=True).sellable_at_breakdown.agg(
        ["sum", "count"]
    )
    group_state = {
        key: "fully_sellable" if row["sum"] == row["count"] else "fully_locked" if row["sum"] == 0 else "partially_sellable"
        for key, row in group_stats.iterrows()
    }
    incidence["inventory_state_at_breakdown"] = [
        group_state[(row.symbol, row.event_date)] for row in incidence.itertuples(index=False)
    ]

    path_rows: list[dict[str, Any]] = []
    for event in incidence.loc[incidence.actionable_before_frozen_exit].itertuples(index=False):
        trade = next(item for item in trade_rows if item.trade_id == event.trade_id)
        lot_path = paths[event.trade_id]
        anchor = lot_path[event.fill_date]["open_proceeds"]
        frozen = float(trade.invested_cost) * (1.0 + float(trade.final_net_return))
        result: dict[str, Any] = {
            **event._asdict(),
            "anchor_net_pnl": anchor / float(trade.invested_cost) - 1.0,
            "remaining_payoff": frozen / anchor - 1.0,
            "winner_recovery": frozen > anchor,
            "failure_mode": "loser_continuation" if anchor <= float(trade.invested_cost) else "winner_giveback",
        }
        fill_index = cal_index[event.fill_date]
        exit_index = cal_index[event.frozen_exit_date]
        for horizon in (1, 3, 5):
            target_index = min(fill_index + horizon, exit_index)
            target_day = calendar[target_index]
            result[f"h{horizon}"] = lot_path[target_day]["open_proceeds"] / anchor - 1.0
        lows = [
            lot_path[calendar[index]]["low_proceeds"] / anchor - 1.0
            for index in range(fill_index, exit_index + 1)
        ]
        result["subsequent_mae"] = min(lows)
        path_rows.append(result)
    event_paths = pd.DataFrame(path_rows)

    # One causal, deterministic no-prior-breakdown control at the same date and age.
    trade_by_id = {row.trade_id: row for row in trade_rows}
    matches: list[dict[str, Any]] = []
    for event in event_paths.itertuples(index=False):
        candidates = []
        for candidate in active_by_date[event.event_date]:
            if candidate.trade_id == event.trade_id:
                continue
            candidate_age = cal_index[event.event_date] - cal_index[candidate.entry_date]
            if candidate_age != event.holding_age:
                continue
            prior_break = first_breakdown[candidate.trade_id]
            if prior_break is not None and prior_break <= event.event_date:
                continue
            if cal_index[candidate.exit_date] <= cal_index[event.fill_date]:
                continue
            candidates.append(candidate)
        if not candidates:
            continue
        candidates.sort(
            key=lambda item: (
                item.industry != event.industry,
                item.signal_date != event.signal_date,
                abs(int(item.signal_rank) - int(trade_by_id[event.trade_id].signal_rank)),
                item.trade_id,
            )
        )
        control = candidates[0]
        control_path = paths[control.trade_id]
        control_fill = event.fill_date
        if control_fill not in control_path:
            continue
        anchor = control_path[control_fill]["open_proceeds"]
        frozen = float(control.invested_cost) * (1.0 + float(control.final_net_return))
        row: dict[str, Any] = {
            "trade_id": event.trade_id,
            "control_trade_id": control.trade_id,
            "control_same_industry": control.industry == event.industry,
            "control_same_cohort": control.signal_date == event.signal_date,
            "control_remaining_payoff": frozen / anchor - 1.0,
        }
        fill_index = cal_index[control_fill]
        exit_index = cal_index[control.exit_date]
        for horizon in (1, 3, 5):
            target_day = calendar[min(fill_index + horizon, exit_index)]
            row[f"control_h{horizon}"] = control_path[target_day]["open_proceeds"] / anchor - 1.0
        matches.append(row)
    if matches:
        event_paths = event_paths.merge(pd.DataFrame(matches), on="trade_id", how="left", validate="one_to_one")
        for name in ("h1", "h3", "h5", "remaining_payoff"):
            event_paths[f"matched_diff_{name}"] = event_paths[name] - event_paths[f"control_{name}"]
    return incidence.sort_values(["event_date", "symbol", "trade_id"]), event_paths.sort_values(
        ["event_date", "symbol", "trade_id"]
    )


def _summarize_incidence(
    trades: pd.DataFrame, incidence: pd.DataFrame, spec: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, bool]]:
    if incidence.empty:
        summary = {
            "champion_positions": len(trades),
            "affected_lots": 0,
            "event_frequency": 0.0,
            "unique_securities": 0,
            "cohort_dates": 0,
            "years": 0,
            "industries": 0,
            "actionable_fill_fraction": 0.0,
        }
    else:
        group_states = incidence.drop_duplicates(["symbol", "event_date"])
        summary = {
            "champion_positions": len(trades),
            "affected_lots": len(incidence),
            "event_frequency": float(len(incidence) / len(trades)),
            "unique_securities": int(incidence.symbol.nunique()),
            "cohort_dates": int(incidence.signal_date.nunique()),
            "event_dates": int(incidence.event_date.nunique()),
            "years": int(incidence.event_year.nunique()),
            "industries": int(incidence.industry.nunique()),
            "holding_age_counts": incidence.holding_age_bucket.value_counts().sort_index().to_dict(),
            "sellable_inventory_fraction_at_breakdown": float(incidence.sellable_at_breakdown.mean()),
            "fully_sellable_events": int(group_states.inventory_state_at_breakdown.eq("fully_sellable").sum()),
            "partially_sellable_events": int(group_states.inventory_state_at_breakdown.eq("partially_sellable").sum()),
            "fully_locked_events": int(group_states.inventory_state_at_breakdown.eq("fully_locked").sum()),
            "delayed_fill_lots": int(incidence.fill_delayed.sum()),
            "no_incremental_headroom_lots": int(incidence.no_incremental_headroom.sum()),
            "unexecuted_before_frozen_exit_lots": int(incidence.unexecuted_before_frozen_exit.sum()),
            "actionable_fill_fraction": float(incidence.actionable_before_frozen_exit.mean()),
            "early_events": int(incidence.block.eq("early").sum()),
            "late_events": int(incidence.block.eq("late").sum()),
            "year_counts": {str(key): int(value) for key, value in incidence.event_year.value_counts().sort_index().items()},
            "industry_counts": {str(key): int(value) for key, value in incidence.industry.value_counts().sort_values(ascending=False).items()},
            "overlapping_symbol_event_groups": int(
                incidence.groupby(["symbol", "event_date"]).size().gt(1).sum()
            ),
        }
    gate = spec["phase_a_incidence_gate"]
    checks = {
        "affected_lots": summary["affected_lots"] >= gate["affected_lots_min"],
        "unique_securities": summary["unique_securities"] >= gate["unique_securities_min"],
        "cohort_dates": summary["cohort_dates"] >= gate["cohort_dates_min"],
        "calendar_years": summary["years"] >= gate["calendar_years_min"],
        "industries": summary["industries"] >= gate["industries_min"],
        "events_each_block": summary.get("early_events", 0) >= gate["events_each_block_min"]
        and summary.get("late_events", 0) >= gate["events_each_block_min"],
        "actionable_fill_fraction": summary["actionable_fill_fraction"]
        >= gate["actionable_fill_fraction_min"],
    }
    return summary, checks


def _period_summary(frame: pd.DataFrame) -> dict[str, Any]:
    output: dict[str, Any] = {"count": len(frame)}
    for name in ("h1", "h3", "h5", "remaining_payoff", "subsequent_mae"):
        values = frame[name].dropna().astype(float)
        output[name] = {
            "mean": float(values.mean()) if len(values) else math.nan,
            "median": float(values.median()) if len(values) else math.nan,
            "winner_rate": float(values.gt(0).mean()) if len(values) else math.nan,
            "severe_loss_fraction": float(values.le(SEVERE).mean()) if len(values) else math.nan,
        }
    matched = frame.dropna(subset=["control_remaining_payoff"])
    output["matched_count"] = len(matched)
    output["matched_same_industry_fraction"] = (
        float(matched.control_same_industry.mean()) if len(matched) else math.nan
    )
    output["matched_same_cohort_fraction"] = (
        float(matched.control_same_cohort.mean()) if len(matched) else math.nan
    )
    for name in ("h1", "h3", "h5", "remaining_payoff"):
        values = matched[f"matched_diff_{name}"].dropna().astype(float)
        output[f"matched_diff_{name}"] = {
            "mean": float(values.mean()) if len(values) else math.nan,
            "median": float(values.median()) if len(values) else math.nan,
        }
    return output


def _diagnose_paths(
    event_paths: pd.DataFrame, incidence: pd.DataFrame, spec: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, bool]]:
    periods = {
        "full": event_paths,
        "early_2018_2021": event_paths.loc[event_paths.block.eq("early")],
        "late_2022_2023": event_paths.loc[event_paths.block.eq("late")],
        "loser_continuation": event_paths.loc[event_paths.failure_mode.eq("loser_continuation")],
        "winner_giveback": event_paths.loc[event_paths.failure_mode.eq("winner_giveback")],
    }
    summary = {name: _period_summary(frame) for name, frame in periods.items()}
    summary["by_year"] = {
        str(year): _period_summary(group)
        for year, group in event_paths.groupby("event_year", sort=True)
    }
    summary["by_industry"] = {
        str(industry): {
            "count": len(group),
            "remaining_mean": float(group.remaining_payoff.mean()),
            "matched_remaining_gap": float(group.matched_diff_remaining_payoff.mean()),
        }
        for industry, group in event_paths.groupby("industry", sort=True)
    }
    summary["recovery_fraction"] = float(event_paths.winner_recovery.mean())
    summary["matched_coverage"] = float(event_paths.control_remaining_payoff.notna().mean())
    gate = spec["phase_b_diagnosis"]["promotion_all_required"]
    full = summary["full"]
    early = summary["early_2018_2021"]
    late = summary["late_2022_2023"]
    year_share = float(incidence.event_year.value_counts(normalize=True).max())
    industry_share = float(incidence.industry.value_counts(normalize=True).max())
    checks = {
        "remaining_payoff_materially_adverse": full["remaining_payoff"]["mean"]
        <= gate["remaining_payoff_mean_max"],
        "matched_holdings_materially_better": full["matched_diff_remaining_payoff"]["mean"]
        <= gate["matched_remaining_difference_mean_max"],
        "remaining_payoff_same_orientation_blocks": early["remaining_payoff"]["mean"]
        < gate["remaining_payoff_mean_both_blocks_below"]
        and late["remaining_payoff"]["mean"] < gate["remaining_payoff_mean_both_blocks_below"],
        "matched_difference_same_orientation_blocks": early["matched_diff_remaining_payoff"]["mean"]
        < gate["matched_difference_both_blocks_below"]
        and late["matched_diff_remaining_payoff"]["mean"]
        < gate["matched_difference_both_blocks_below"],
        "not_one_year": year_share <= gate["largest_year_share_max"],
        "not_one_industry": industry_share <= gate["largest_industry_share_max"],
        "unique_securities": int(incidence.symbol.nunique()) >= gate["unique_securities_min"],
        "actionable_fill_fraction": float(incidence.actionable_before_frozen_exit.mean())
        >= gate["actionable_fill_fraction_min"],
    }
    summary["largest_year_share"] = year_share
    summary["largest_industry_share"] = industry_share
    return summary, checks


@dataclass
class ExitLot:
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
    action_cash: float = 0.0
    forced_effective_date: date | None = None
    pending_breakdown_date: date | None = None


def _dynamic_replay(
    plans: pd.DataFrame,
    market_rows: pd.DataFrame,
    support: pd.DataFrame,
    calendar: list[date],
    events: list[Any],
    cost: float,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    row_map = {
        (row.symbol, pd.Timestamp(row.trade_date).date()): row
        for row in market_rows.itertuples(index=False)
    }
    support_map = {
        (row.symbol, row.trade_date): bool(row.confirmed_breakdown)
        for row in support.itertuples(index=False)
    }
    entry_map = {
        int(index): list(group.itertuples(index=False))
        for index, group in plans.groupby("entry_index", sort=True)
    }
    event_decisions, symbol_events = ANATOMY.CA._event_maps(events)
    cash = INITIAL_CAPITAL
    lots: list[ExitLot] = []
    records: list[dict[str, Any]] = []
    nav_rows: list[dict[str, Any]] = []
    turnover = 0.0
    planned_entries = 0
    entries = 0
    risk_blocked_entries = 0
    forced_exits = 0
    breakdown_exits = 0
    delayed_breakdown_exits = 0
    capacity: list[float] = []
    start_index = int(plans.entry_index.min())
    final_due = int(plans.due_index.max())
    final_index = min(final_due + 20, len(calendar) - 1)

    def finish(lot: ExitLot, proceeds: float, current_date: date, reason: str) -> None:
        records.append(
            {
                "trade_id": lot.trade_id,
                "signal_date": lot.signal_date,
                "entry_date": lot.entry_date,
                "exit_date": current_date,
                "symbol": lot.symbol,
                "industry": lot.industry,
                "signal_rank": lot.signal_rank,
                "invested_cost": lot.invested_cost,
                "profit": proceeds - lot.invested_cost,
                "final_net_return": proceeds / lot.invested_cost - 1.0,
                "holding_sessions": calendar.index(current_date) - lot.entry_index,
                "exit_reason": reason,
                "breakdown_signal_date": lot.pending_breakdown_date,
                "capacity_cny": lot.capacity_cny,
            }
        )

    for cal_index in range(start_index, final_index + 1):
        current_date = calendar[cal_index]
        survivors: list[ExitLot] = []
        for lot in lots:
            if lot.forced_effective_date is not None and current_date >= lot.forced_effective_date:
                raise Cycle020Error(f"pre-effective exit failed:{lot.trade_id}:{current_date}")
            row = row_map.get((lot.symbol, current_date))
            if row is None or not ANATOMY.CA._holding_row_usable(row):
                raise Cycle020Error(f"invalid holding row:{lot.trade_id}:{current_date}")
            if int(row.corporate_action_count or 0) > 0:
                action = _visible_action(row)
                if action is None:
                    raise Cycle020Error(f"unresolved action:{lot.trade_id}:{current_date}")
                multiplier, cash_per_share = action
                if multiplier != 1.0:
                    raise Cycle020Error(f"share action reached effective date:{lot.trade_id}")
                lot.action_cash += lot.shares * cash_per_share
            forced = lot.forced_effective_date is not None
            due = cal_index >= lot.due_index
            breakdown_due = (
                lot.pending_breakdown_date is not None and current_date > lot.pending_breakdown_date
            )
            if not forced and not due and not breakdown_due:
                survivors.append(lot)
                continue
            if not ANATOMY.CA._sellable(row):
                survivors.append(lot)
                continue
            gross = lot.shares * float(row.open)
            proceeds = lot.action_cash + gross * (1.0 - cost)
            cash += proceeds
            turnover += gross
            if forced:
                reason = "FORCED_PRE_EFFECTIVE"
                forced_exits += 1
            elif breakdown_due and cal_index < lot.due_index:
                reason = "CONFIRMED_BREAKDOWN"
                breakdown_exits += 1
                delayed_breakdown_exits += int(
                    cal_index > calendar.index(lot.pending_breakdown_date) + 1
                )
            else:
                reason = "DUE"
            finish(lot, proceeds, current_date, reason)
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
            if ANATOMY.CA._entry_blocked(
                plan.symbol, plan.signal_date, current_date, symbol_events
            ):
                risk_blocked_entries += 1
                continue
            if row is not None and ANATOMY.CYCLE015._buyable(row):
                executable.append((plan, row))
        cohort_capital = min(cash, pre_entry_nav / 4)
        if executable:
            allocation = cohort_capital / len(executable)
            for plan, row in executable:
                shares = allocation / (float(row.open) * (1.0 + cost))
                gross = shares * float(row.open)
                invested = gross * (1.0 + cost)
                cash -= invested
                turnover += gross
                capacity_cny = float(row.amount) * 0.05 * len(executable) * 4
                lots.append(
                    ExitLot(
                        trade_id=f"{plan.signal_date}|{plan.symbol}",
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
                if lot.forced_effective_date is None or event.effective_date < lot.forced_effective_date:
                    lot.forced_effective_date = event.effective_date
            if (
                lot.pending_breakdown_date is None
                and support_map.get((lot.symbol, current_date), False)
            ):
                lot.pending_breakdown_date = current_date

        nav = cash
        industry_values: dict[str, float] = {}
        for lot in lots:
            row = row_map[(lot.symbol, current_date)]
            value = lot.action_cash + lot.shares * float(row.close)
            nav += value
            industry_values[lot.industry] = industry_values.get(lot.industry, 0.0) + value
        invested = sum(industry_values.values())
        nav_rows.append(
            {
                "trade_date": current_date,
                "nav": nav,
                "cash": cash,
                "positions": len(lots),
                "industries": len(industry_values),
                "industry_hhi": sum((value / invested) ** 2 for value in industry_values.values())
                if invested > 0
                else 0.0,
            }
        )
        if cal_index >= final_due and not lots and cal_index not in entry_map:
            break
    if lots:
        raise Cycle020Error(f"terminal open lots:{len(lots)}")
    trades = pd.DataFrame(records).sort_values(["signal_date", "signal_rank", "symbol"])
    equity = pd.DataFrame(nav_rows)
    returns = equity.nav.pct_change().fillna(equity.nav.iloc[0] / INITIAL_CAPITAL - 1.0)
    drawdown = equity.nav / equity.nav.cummax() - 1.0
    years = len(equity) / 252.0
    annualized = (equity.nav.iloc[-1] / INITIAL_CAPITAL) ** (1.0 / years) - 1.0
    volatility = returns.std(ddof=1)
    metrics = {
        "total_return": float(equity.nav.iloc[-1] / INITIAL_CAPITAL - 1.0),
        "annualized_return": float(annualized),
        "maximum_drawdown": float(drawdown.min()),
        "daily_sharpe": float(math.sqrt(252) * returns.mean() / volatility),
        "calmar": float(annualized / abs(drawdown.min())),
        "severe_trade_fraction": float(trades.final_net_return.le(SEVERE).mean()),
        "turnover_multiple_initial_capital": float(turnover / INITIAL_CAPITAL),
        "planned_entries": planned_entries,
        "entries": entries,
        "entry_execution_fraction": float(entries / planned_entries),
        "completed_trades": len(trades),
        "forced_pre_effective_exits": forced_exits,
        "breakdown_exits": breakdown_exits,
        "delayed_breakdown_exits": delayed_breakdown_exits,
        "average_holding_sessions": float(trades.holding_sessions.mean()),
        "median_holding_sessions": float(trades.holding_sessions.median()),
        "mean_cash_fraction": float((equity.cash / equity.nav).mean()),
        "mean_positions": float(equity.positions.mean()),
        "mean_industries": float(equity.industries.mean()),
        "mean_industry_hhi_invested_days": float(
            equity.loc[equity.positions > 0, "industry_hhi"].mean()
        ),
        "p10_capacity_cny_at_5pct_amount": float(np.quantile(capacity, 0.10)),
        "median_capacity_cny_at_5pct_amount": float(np.median(capacity)),
        "risk_blocked_entries": risk_blocked_entries,
    }
    if not math.isclose(
        float(trades.profit.sum()), float(equity.nav.iloc[-1] - INITIAL_CAPITAL), rel_tol=0, abs_tol=1e-6
    ):
        raise Cycle020Error("dynamic trade PnL does not conserve to terminal NAV")
    return trades, equity, metrics


def _annual_returns(equity: pd.DataFrame) -> dict[str, float]:
    frame = equity.copy()
    frame["year"] = pd.to_datetime(frame.trade_date).dt.year
    output: dict[str, float] = {}
    prior = INITIAL_CAPITAL
    for year, group in frame.groupby("year", sort=True):
        terminal = float(group.nav.iloc[-1])
        output[str(year)] = terminal / prior - 1.0
        prior = terminal
    return output


def _attribution(
    baseline_trades: pd.DataFrame,
    dynamic_trades: pd.DataFrame,
    baseline_equity: pd.DataFrame,
    dynamic_equity: pd.DataFrame,
    baseline_metrics: dict[str, Any],
    dynamic_metrics: dict[str, Any],
) -> tuple[dict[str, Any], pd.DataFrame]:
    left = baseline_trades[
        ["trade_id", "signal_date", "symbol", "industry", "invested_cost", "final_net_return"]
    ].rename(
        columns={
            "invested_cost": "baseline_invested_cost",
            "final_net_return": "baseline_net_return",
        }
    )
    right = dynamic_trades[
        [
            "trade_id",
            "exit_date",
            "exit_reason",
            "breakdown_signal_date",
            "final_net_return",
            "holding_sessions",
        ]
    ].rename(columns={"final_net_return": "dynamic_net_return"})
    paired = left.merge(right, on="trade_id", how="inner", validate="one_to_one")
    affected = paired.loc[paired.exit_reason.eq("CONFIRMED_BREAKDOWN")].copy()
    affected["return_delta"] = affected.dynamic_net_return - affected.baseline_net_return
    affected["counterfactual_pnl_delta"] = (
        affected.return_delta * affected.baseline_invested_cost
    )
    losses_avoided = affected.counterfactual_pnl_delta.clip(lower=0)
    upside_sacrificed = (-affected.counterfactual_pnl_delta.clip(upper=0))
    additional_turnover = (
        dynamic_metrics["turnover_multiple_initial_capital"]
        - baseline_metrics["turnover_multiple_initial_capital"]
    )
    baseline_cash = baseline_equity.set_index("trade_date").cash
    dynamic_cash = dynamic_equity.set_index("trade_date").cash
    aligned = pd.concat([baseline_cash, dynamic_cash], axis=1, keys=["baseline", "dynamic"]).dropna()
    summary = {
        "affected_breakdown_exits": len(affected),
        "losses_avoided_cny": float(losses_avoided.sum()),
        "upside_sacrificed_cny": float(upside_sacrificed.sum()),
        "net_counterfactual_pnl_delta_cny": float(affected.counterfactual_pnl_delta.sum()),
        "winners_prematurely_exited": int(affected.counterfactual_pnl_delta.lt(0).sum()),
        "improved_exits": int(affected.counterfactual_pnl_delta.gt(0).sum()),
        "severe_losers_avoided": int(
            (affected.baseline_net_return.le(SEVERE) & affected.dynamic_net_return.gt(SEVERE)).sum()
        ),
        "severe_losers_not_avoided": int(
            (affected.baseline_net_return.le(SEVERE) & affected.dynamic_net_return.le(SEVERE)).sum()
        ),
        "average_exit_pnl_at_breakdown": float(affected.dynamic_net_return.mean()),
        "average_original_frozen_exit_pnl": float(affected.baseline_net_return.mean()),
        "incremental_return_per_breakdown_exit": float(affected.return_delta.mean()),
        "additional_turnover_multiple": float(additional_turnover),
        "incremental_total_return_per_additional_turnover": (
            float(
                (dynamic_metrics["total_return"] - baseline_metrics["total_return"])
                / additional_turnover
            )
            if abs(additional_turnover) > 1e-12
            else math.nan
        ),
        "mean_additional_cash_cny": float((aligned.dynamic - aligned.baseline).mean()),
        "mean_additional_cash_fraction_of_initial": float(
            (aligned.dynamic - aligned.baseline).mean() / INITIAL_CAPITAL
        ),
    }
    years = []
    baseline_returns = _annual_returns(baseline_equity)
    dynamic_returns = _annual_returns(dynamic_equity)
    for year in range(2018, 2024):
        group = affected.loc[pd.to_datetime(affected.breakdown_signal_date).dt.year.eq(year)]
        years.append(
            {
                "year": year,
                "frozen_return": baseline_returns.get(str(year), math.nan),
                "exit_return": dynamic_returns.get(str(year), math.nan),
                "return_delta": dynamic_returns.get(str(year), math.nan)
                - baseline_returns.get(str(year), math.nan),
                "breakdown_exits": len(group),
                "gross_losses_avoided_cny": float(group.counterfactual_pnl_delta.clip(lower=0).sum()),
                "upside_sacrificed_cny": float((-group.counterfactual_pnl_delta.clip(upper=0)).sum()),
                "baseline_severe": int(group.baseline_net_return.le(SEVERE).sum()),
                "exit_severe": int(group.dynamic_net_return.le(SEVERE).sum()),
                "severe_loss_change": int(group.dynamic_net_return.le(SEVERE).sum())
                - int(group.baseline_net_return.le(SEVERE).sum()),
            }
        )
    return summary, pd.DataFrame(years)


def _render_report(result: dict[str, Any]) -> str:
    incidence = result["phase_a"]["summary"]
    paths = result.get("phase_b", {}).get("summary", {})
    lines = [
        "# Champion confirmed-breakdown dynamic exit",
        "",
        f"Status: `{result['status']}`. Final classification: `{result['final_classification']}`.",
        "",
        "## Recovered support definition",
        "",
        "The exact repository-authoritative event is a completed daily causal-coordinate close strictly below the minimum causal-coordinate low of the previous 20 completed hard-valid sessions. The support is known before the event day, updates daily, and the close-confirmed signal is recorded at 15:30. It does not use a minute low, an intraday crossing, a reclaim rule, or a penetration threshold. Because confirmation occurs only at the completed close, the earliest faithful fill is the next legal session open; an event-day intraday fill would be a different signal.",
        "",
        "## Breakdown incidence",
        "",
        f"{incidence['affected_lots']:,} of {incidence['champion_positions']:,} frozen champion positions had a first confirmed breakdown ({incidence['event_frequency']:.2%}); {incidence['unique_securities']} securities, {incidence['cohort_dates']} cohorts, {incidence['years']} years, and {incidence['industries']} industries were represented.",
        f"Actionable fill coverage was {incidence['actionable_fill_fraction']:.2%}; sellable inventory at confirmation was {incidence.get('sellable_inventory_fraction_at_breakdown', math.nan):.2%}. Full/partial/locked event groups were {incidence.get('fully_sellable_events', 0)}/{incidence.get('partially_sellable_events', 0)}/{incidence.get('fully_locked_events', 0)}. Delayed/no-headroom/unexecuted lots were {incidence.get('delayed_fill_lots', 0)}/{incidence.get('no_incremental_headroom_lots', 0)}/{incidence.get('unexecuted_before_frozen_exit_lots', 0)}.",
        "Holding-age counts were "
        + ", ".join(
            f"{key} {value}"
            for key, value in incidence.get("holding_age_counts", {}).items()
        )
        + ".",
        f"There were {incidence.get('overlapping_symbol_event_groups', 0)} symbol-event groups with multiple active cohorts. Exit-before-entry ordering means older lots would be sold before any same-open frozen new cohort; the two partial confirmation states and 34 fully locked confirmation states are reported without illegal same-day sale assumptions.",
        "",
    ]
    if paths:
        lines += [
            "## Post-breakdown path",
            "",
            "| Period | N | h1 mean | h3 mean | h5 mean | Remaining mean | Remaining median | Matched remaining gap | MAE |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for key in ("full", "early_2018_2021", "late_2022_2023", "loser_continuation", "winner_giveback"):
            row = paths[key]
            lines.append(
                f"| {key} | {row['count']:,} | {row['h1']['mean']:.3%} | {row['h3']['mean']:.3%} | {row['h5']['mean']:.3%} | {row['remaining_payoff']['mean']:.3%} | {row['remaining_payoff']['median']:.3%} | {row['matched_diff_remaining_payoff']['mean']:.3%} | {row['subsequent_mae']['mean']:.3%} |"
            )
        lines += [
            "",
            f"Matched-control coverage was {paths['matched_coverage']:.2%}; the fraction recovering to a positive remaining payoff was {paths['recovery_fraction']:.2%}.",
            "",
            "## Year-by-year original path",
            "",
            "| Year | N | h1 | h3 | h5 | Remaining | Matched remaining gap |",
            "|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for year, row in paths["by_year"].items():
            lines.append(
                f"| {year} | {row['count']:,} | {row['h1']['mean']:.3%} | {row['h3']['mean']:.3%} | {row['h5']['mean']:.3%} | {row['remaining_payoff']['mean']:.3%} | {row['matched_diff_remaining_payoff']['mean']:.3%} |"
            )
        lines.append("")
    if result.get("phase_c", {}).get("authorized"):
        baseline = result["phase_c"]["baseline"]
        dynamic = result["phase_c"]["dynamic"]
        attribution = result["phase_c"]["attribution"]
        lines += [
            "## Executable replay",
            "",
            "| Portfolio | Total | Annualized | Max DD | Sharpe | Calmar | Severe | Turnover | Mean/median hold |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            f"| Frozen Champion | {baseline['total_return']:.2%} | {baseline['annualized_return']:.2%} | {baseline['maximum_drawdown']:.2%} | {baseline['daily_sharpe']:.3f} | {baseline['calmar']:.3f} | {baseline['severe_trade_fraction']:.2%} | {baseline['turnover_multiple_initial_capital']:.2f}x | {result['phase_c']['baseline_average_holding_sessions']:.2f}/{result['phase_c']['baseline_median_holding_sessions']:.1f} |",
            f"| Breakdown Exit | {dynamic['total_return']:.2%} | {dynamic['annualized_return']:.2%} | {dynamic['maximum_drawdown']:.2%} | {dynamic['daily_sharpe']:.3f} | {dynamic['calmar']:.3f} | {dynamic['severe_trade_fraction']:.2%} | {dynamic['turnover_multiple_initial_capital']:.2f}x | {dynamic['average_holding_sessions']:.2f}/{dynamic['median_holding_sessions']:.1f} |",
            "",
            f"The exit produced {dynamic['breakdown_exits']} breakdown exits. Counterfactual losses avoided were CNY {attribution['losses_avoided_cny']:,.0f}; upside sacrificed was CNY {attribution['upside_sacrificed_cny']:,.0f}; severe losers avoided/not avoided were {attribution['severe_losers_avoided']}/{attribution['severe_losers_not_avoided']}. Mean added cash was {attribution['mean_additional_cash_fraction_of_initial']:.2%} of initial capital.",
            "",
            "## Annual results",
            "",
            "| Year | Frozen | Exit | Delta | Exits | Losses avoided | Upside sacrificed | Severe delta |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for row in result["phase_c"]["annual"]:
            lines.append(
                f"| {row['year']} | {row['frozen_return']:.2%} | {row['exit_return']:.2%} | {row['return_delta']:.2%} | {row['breakdown_exits']} | {row['gross_losses_avoided_cny']:,.0f} | {row['upside_sacrificed_cny']:,.0f} | {row['severe_loss_change']} |"
            )
        lines.append("")
    else:
        lines += [
            "## Executable replay",
            "",
            "Not authorized. The original position path did not show adverse remaining economics, so the predeclared Phase-B gate stopped the experiment before any modified champion replay.",
            "",
        ]
    lines += [
        "## Boundary",
        "",
        "All evidence uses consumed 2018--2023 development history. Post-2023 outcomes and CY-011 were not read. No OOS, independent-validation, live, or production claim is made. No support variant, stop grid, re-entry rule, regime filter, or champion entry change was tested.",
        "",
    ]
    return "\n".join(lines)


def run() -> dict[str, Any]:
    spec = _load_spec()
    ca_spec = ANATOMY.CA._load_spec()
    paths, calendar, input_identity = ANATOMY.CA._load_market_inputs(ca_spec)
    daily = pd.read_parquet(_resolve(spec["inputs"]["causal_daily_panel"]["path"]))
    construction_spec = ANATOMY.CONSTRUCTION._load_spec()
    _baseline_selection, champion = ANATOMY.CYCLE015._weekly_selections(daily, construction_spec)
    champion = champion.copy()
    champion["family"] = "industry_diffusion_low_max"
    plans = ANATOMY.CONSTRUCTION._make_plans(champion, calendar)
    champion_meta = champion[["trade_date", "symbol", "signal_rank"]].copy()
    champion_meta["signal_date"] = pd.to_datetime(champion_meta.pop("trade_date")).dt.date
    plans = plans.merge(
        champion_meta, on=["signal_date", "symbol"], how="left", validate="one_to_one"
    )
    if plans.signal_rank.isna().any():
        raise Cycle020Error("frozen champion rank missing")
    plans["signal_rank"] = plans.signal_rank.astype(int)
    market_rows = ANATOMY.CA.PRIOR._query_execution_rows(paths, plans, calendar)
    events, action_audit = ANATOMY.CA._load_risk_events(ca_spec, calendar)
    champion_result = json.loads(
        _resolve(spec["inputs"]["champion_result"]["path"]).read_text(encoding="utf-8")
    )
    authoritative = champion_result["champion_identity"]
    baseline_trades, baseline_equity, baseline_metrics = ANATOMY._replay_with_paths(
        plans, market_rows, calendar, events, authoritative
    )
    bound_trade_panel = pd.read_parquet(
        _resolve(spec["inputs"]["champion_trade_panel"]["path"])
    )
    if sha256_file(_resolve(spec["inputs"]["champion_trade_panel"]["path"])) != spec["inputs"]["champion_trade_panel"]["sha256"]:
        raise Cycle020Error("champion trade panel changed during run")
    pd.testing.assert_frame_equal(
        baseline_trades.reset_index(drop=True), bound_trade_panel.reset_index(drop=True), check_dtype=False
    )

    EXTERNAL_ROOT.mkdir(parents=True, exist_ok=True)
    temp_path = EXTERNAL_ROOT / "duckdb_tmp"
    temp_path.mkdir(parents=True, exist_ok=True)
    support = _build_support_rows(paths, sorted(plans.symbol.unique()), temp_path)
    incidence, event_paths = _build_incidence_and_paths(
        baseline_trades, support, market_rows, calendar, spec["frozen_champion"]["cost_per_side"]
    )
    phase_a_summary, phase_a_checks = _summarize_incidence(baseline_trades, incidence, spec)
    phase_a_passes = all(phase_a_checks.values())

    phase_b_summary: dict[str, Any] = {}
    phase_b_checks: dict[str, bool] = {}
    phase_b_passes = False
    if phase_a_passes:
        phase_b_summary, phase_b_checks = _diagnose_paths(event_paths, incidence, spec)
        phase_b_passes = all(phase_b_checks.values())

    phase_c: dict[str, Any] = {"authorized": False}
    year_frame = pd.DataFrame()
    if phase_a_passes and phase_b_passes:
        dynamic_trades, dynamic_equity, dynamic_metrics = _dynamic_replay(
            plans,
            market_rows,
            support,
            calendar,
            events,
            spec["frozen_champion"]["cost_per_side"],
        )
        attribution, year_frame = _attribution(
            baseline_trades,
            dynamic_trades,
            baseline_equity,
            dynamic_equity,
            baseline_metrics,
            dynamic_metrics,
        )
        phase_c = {
            "authorized": True,
            "baseline": baseline_metrics,
            "dynamic": dynamic_metrics,
            "baseline_average_holding_sessions": float(baseline_trades.holding_sessions.mean()),
            "baseline_median_holding_sessions": float(baseline_trades.holding_sessions.median()),
            "attribution": attribution,
            "annual": year_frame.to_dict(orient="records"),
            "higher_cost_stress_run": False,
        }
        earns = (
            dynamic_metrics["total_return"] > baseline_metrics["total_return"]
            and dynamic_metrics["maximum_drawdown"] >= baseline_metrics["maximum_drawdown"]
            and dynamic_metrics["daily_sharpe"] > baseline_metrics["daily_sharpe"]
            and dynamic_metrics["severe_trade_fraction"] <= baseline_metrics["severe_trade_fraction"]
        )
        final_classification = (
            "BREAKDOWN_EXIT_EARNS_COMPLEXITY"
            if earns
            else "DOWNSIDE_INFORMATION_BUT_EXIT_NOT_ECONOMIC"
        )
        dynamic_trades.to_parquet(TRADE_PATH, index=False, compression="zstd")
        dynamic_equity.to_parquet(EQUITY_PATH, index=False, compression="zstd")
    elif not phase_a_passes:
        final_classification = "BREAKDOWN_EXIT_INSUFFICIENT_COVERAGE"
    elif (
        phase_b_checks.get("remaining_payoff_materially_adverse", False)
        and (
            phase_b_summary["early_2018_2021"]["remaining_payoff"]["mean"]
            * phase_b_summary["late_2022_2023"]["remaining_payoff"]["mean"]
            < 0
            or phase_b_summary["early_2018_2021"]["matched_diff_remaining_payoff"]["mean"]
            * phase_b_summary["late_2022_2023"]["matched_diff_remaining_payoff"]["mean"]
            < 0
        )
    ):
        final_classification = "CHRONOLOGICALLY_UNSTABLE_EXIT_INFORMATION"
    else:
        final_classification = "BREAKDOWN_NOT_USEFUL_AS_EXIT"

    incidence.to_parquet(EVENT_PANEL_PATH, index=False, compression="zstd")
    incidence_summary = (
        incidence.groupby(
            ["event_year", "block", "holding_age_bucket", "inventory_state_at_breakdown"],
            dropna=False,
        )
        .agg(lots=("trade_id", "size"), securities=("symbol", "nunique"), actionable=("actionable_before_frozen_exit", "sum"))
        .reset_index()
        if not incidence.empty
        else pd.DataFrame()
    )
    path_summary = []
    if phase_b_summary:
        for name in (
            "full",
            "early_2018_2021",
            "late_2022_2023",
            "loser_continuation",
            "winner_giveback",
        ):
            row = phase_b_summary[name]
            path_summary.append(
                {
                    "period": name,
                    "count": row["count"],
                    "h1_mean": row["h1"]["mean"],
                    "h3_mean": row["h3"]["mean"],
                    "h5_mean": row["h5"]["mean"],
                    "remaining_mean": row["remaining_payoff"]["mean"],
                    "remaining_median": row["remaining_payoff"]["median"],
                    "remaining_winner_rate": row["remaining_payoff"]["winner_rate"],
                    "remaining_severe_fraction": row["remaining_payoff"]["severe_loss_fraction"],
                    "matched_remaining_gap": row["matched_diff_remaining_payoff"]["mean"],
                    "mae_mean": row["subsequent_mae"]["mean"],
                }
            )
    year_output = year_frame
    if year_output.empty and phase_b_summary:
        year_output = pd.DataFrame(
            [
                {
                    "year": int(year),
                    "count": row["count"],
                    "h1_mean": row["h1"]["mean"],
                    "h3_mean": row["h3"]["mean"],
                    "h5_mean": row["h5"]["mean"],
                    "remaining_mean": row["remaining_payoff"]["mean"],
                    "matched_remaining_gap": row["matched_diff_remaining_payoff"]["mean"],
                }
                for year, row in phase_b_summary["by_year"].items()
            ]
        )
    _atomic_write(INCIDENCE_PATH, incidence_summary.to_csv(index=False, lineterminator="\n", float_format="%.10g"))
    _atomic_write(PATH_SUMMARY_PATH, pd.DataFrame(path_summary).to_csv(index=False, lineterminator="\n", float_format="%.10g"))
    _atomic_write(YEAR_PATH, year_output.to_csv(index=False, lineterminator="\n", float_format="%.10g"))

    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "starting_checkpoint": spec["starting_checkpoint"],
        "status": (
            "COMPLETE_EXECUTABLE_EXIT_REPLAY"
            if phase_c["authorized"]
            else "COMPLETE_PHASE_B_STOP_NO_REPLAY"
        ),
        "claim_boundary": spec["claim_boundary"],
        "recovered_confirmed_breakdown": spec["recovered_confirmed_breakdown"],
        "input_identity": input_identity,
        "action_audit": action_audit,
        "phase_a": {"summary": phase_a_summary, "checks": phase_a_checks, "passes": phase_a_passes},
        "phase_b": {"summary": phase_b_summary, "checks": phase_b_checks, "passes": phase_b_passes},
        "phase_c": phase_c,
        "final_classification": final_classification,
        "next_action": (
            "MARKET_HEDGE_FEASIBILITY"
            if final_classification == "BREAKDOWN_EXIT_EARNS_COMPLEXITY"
            else "SECOND_INDEPENDENT_ALPHA_DISCOVERY"
        ),
        "boundaries": {
            "post_2023_read": False,
            "cy011_read": False,
            "support_definition_changed": False,
            "event_day_intraday_fill": False,
            "minute_crossing_used": False,
            "entry_engine_changed": False,
            "reentry_rule_added": False,
            "cost_grid_run": False,
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
        for path in (EVENT_PANEL_PATH,)
    }
    if phase_c["authorized"]:
        for path in (TRADE_PATH, EQUITY_PATH):
            result["external_artifacts"][path.name] = {
                "path": str(path),
                "rows": len(pd.read_parquet(path)),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
    report = _render_report(result)
    _atomic_write(REPORT_PATH, report)
    result["artifacts"] = {
        path.name: {"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)}
        for path in (INCIDENCE_PATH, PATH_SUMMARY_PATH, YEAR_PATH, REPORT_PATH)
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    return result


def main() -> int:
    result = run()
    print(json.dumps(_clean(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
