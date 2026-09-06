#!/usr/bin/env python3
"""Capacity and cash audit for the frozen V5 seller-cost takeover rule.

V6 does not alter V5 signal or execution semantics. It limits each event to
25 causally ranked names, limits the whole portfolio to 50 concurrent names,
and audits a two-percent-per-slot cash ledger. The later-period mode is called
a diagnostic, not a new validation, because V5's 2022-2025 results are known.
"""

from __future__ import annotations

import argparse
import heapq
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import run_ashare_regime_routed_cross_industry_takeover_v5 as v5


mother = v5.mother
REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-REGIME-TAKEOVER-CAPACITY-PORTFOLIO-V6"
CONTRACT = OS_ROOT / f"experiments/{EXPERIMENT}_contract.json"
OUTPUT_ROOT = Path("/Volumes/quant/CY_quant_research") / EXPERIMENT.lower()
EXPECTED_CONTRACT_SHA256 = "038edc58d3bbdeace87bd527bc7868d360da52c2a0f900ffccd7d826a2056c47"

MAX_NAMES_PER_EVENT = 25
MAX_CONCURRENT_POSITIONS = 50
SLOT_WEIGHT = 1.0 / MAX_CONCURRENT_POSITIONS

SOURCE_ROOT = v5.OUTPUT_ROOT
EXPECTED = {
    "v5_freeze": "b173048b185841695762a7ffd316ba8d7995974c88c40063daeb31a1f63190b3",
    "development_result": "7d90ee5924dc0f257145cf486f2963fe88bce6651cd7dd28bd14da802f89aadd",
    "development_selected": "d00c6dedb430bc58e3200e6471219a44bb424e748ba8b6ad8d98821e5fee3f24",
    "development_outcomes": "67fcdcb11be336c9aed013b6de9bb09bfefc18cb554cedc85ef62a63a04b4188",
    "diagnostic_result": "8a81ee4710161298596823884d268764521be5a8d18b78761f6f7ed8da4dedc3",
    "diagnostic_selected": "9a5e53d073f5214e765736b6d2e34689c3387b4219d069367c6d7e4c30197217",
    "diagnostic_outcomes": "eb0049738751e71347641781af38e78135f27fca621c39d588c58daa15b72a17",
}


class ResearchError(RuntimeError):
    """Fail closed on frozen inputs, capacity chronology, or cash conservation."""


def verify_sources(mode: str) -> tuple[Path, Path]:
    if mother.execution.sha256(v5.FREEZE) != EXPECTED["v5_freeze"]:
        raise ResearchError("V5 freeze drift")
    if mode != "development":
        if mother.execution.sha256(CONTRACT) != EXPECTED_CONTRACT_SHA256:
            raise ResearchError("V6 capacity contract drift")
    source_mode = "development" if mode == "development" else "challenge"
    root = SOURCE_ROOT / source_mode
    prefix = "development" if mode == "development" else "diagnostic"
    paths = {
        "result": root / "result.json",
        "selected": root / "selected_candidates.parquet",
        "outcomes": root / "outcomes.parquet",
    }
    for name, path in paths.items():
        if mother.execution.sha256(path) != EXPECTED[f"{prefix}_{name}"]:
            raise ResearchError(f"V5 {prefix} {name} drift")
    return paths["selected"], paths["outcomes"]


def admit_capacity(
    selected: pd.DataFrame,
    outcomes: pd.DataFrame,
    max_names_per_event: int = MAX_NAMES_PER_EVENT,
    max_concurrent: int = MAX_CONCURRENT_POSITIONS,
) -> pd.DataFrame:
    """Admit entries without reusing a slot until after its exit date.

    Treating an exit date as occupied through that close is conservative for
    same-day open exits and prevents intraday target proceeds from funding an
    opening-auction entry that occurred earlier that day.
    """
    candidates = selected.loc[
        selected.diversified_rank.le(max_names_per_event)
    ].copy()
    outcome_columns = [
        "event_id",
        "status",
        "entry_date",
        "entry_cal_idx",
        "exit_date",
        "exit_cal_idx",
        "exit_reason",
        "holding_sessions",
        "gross_return",
        "net_return",
    ]
    outcome_columns = [column for column in outcome_columns if column in outcomes]
    frame = candidates.merge(
        outcomes[outcome_columns], on="event_id", how="left", validate="one_to_one"
    )
    frame["capacity_status"] = "NO_LEGAL_ENTRY"
    has_entry = frame.entry_date.notna()
    frame.loc[has_entry, "capacity_status"] = "CAPACITY_REJECTED"
    ordered = frame.loc[has_entry].sort_values(
        ["entry_date", "signal_date", "diversified_rank", "symbol", "event_id"],
        kind="mergesort",
    )
    active: list[tuple[pd.Timestamp, str]] = []
    admitted: list[int] = []
    for index, row in ordered.iterrows():
        entry_date = pd.Timestamp(row.entry_date)
        while active and active[0][0] < entry_date:
            heapq.heappop(active)
        if len(active) >= max_concurrent:
            continue
        release_date = (
            pd.Timestamp.max.normalize()
            if pd.isna(row.exit_date)
            else pd.Timestamp(row.exit_date)
        )
        heapq.heappush(active, (release_date, str(row.event_id)))
        admitted.append(index)
    frame.loc[admitted, "capacity_status"] = "ADMITTED"
    return frame.sort_values(
        ["signal_date", "diversified_rank", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    complete = frame.loc[
        frame.capacity_status.eq("ADMITTED") & frame.status.eq("COMPLETED")
    ].copy()
    if complete.empty:
        return {
            "completed": 0,
            "mean_net": None,
            "mean_holding": None,
            "win": None,
            "severe10": None,
            "target_hit": None,
        }
    return {
        "completed": int(len(complete)),
        "mean_net": float(complete.net_return.mean()),
        "mean_holding": float(complete.holding_sessions.mean()),
        "win": float(complete.net_return.gt(0).mean()),
        "severe10": float(complete.net_return.le(-0.10).mean()),
        "target_hit": float(complete.exit_reason.eq("TARGET_10").mean()),
    }


def cash_ledger(frame: pd.DataFrame, years: list[int]) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Run a conserved cash/cost-basis ledger for every admitted entry.

    Unknown terminal outcomes remain in the ledger at entry cost. Consequently
    the output is explicitly an open-cost accounting view, not a claimed
    mark-to-market return series.
    """
    admitted = frame.loc[
        frame.capacity_status.eq("ADMITTED") & frame.entry_date.notna()
    ].copy()
    if admitted.empty:
        return pd.DataFrame(), {
            "ending_nav_at_open_cost": 1.0,
            "annualized_return_at_open_cost": 0.0,
            "unresolved_positions_at_end": 0,
        }
    admitted["entry_date"] = pd.to_datetime(admitted.entry_date)
    admitted["exit_date"] = pd.to_datetime(admitted.exit_date)
    completed = admitted.loc[admitted.status.eq("COMPLETED")].copy()
    entries = {date: part for date, part in admitted.groupby("entry_date", sort=True)}
    exits = {date: part for date, part in completed.groupby("exit_date", sort=True)}
    dates = sorted(set(entries) | set(exits))
    cash = 1.0
    positions: dict[str, float] = {}
    ledger_rows: list[dict[str, Any]] = []
    nav_points: list[float] = [1.0]
    year_end_nav: dict[int, float] = {}
    previous_year = dates[0].year

    for date in dates:
        if date.year != previous_year:
            year_end_nav[previous_year] = cash + sum(positions.values())
            previous_year = date.year
        equity_before = cash + sum(positions.values())
        entry_part = entries.get(date)
        ordered_entries = (
            []
            if entry_part is None
            else entry_part.sort_values(
                ["signal_date", "diversified_rank", "symbol", "event_id"],
                kind="mergesort",
            ).itertuples(index=False)
        )
        for row in ordered_entries:
            notional = min(equity_before * SLOT_WEIGHT, cash)
            if notional <= 0:
                raise ResearchError("cash exhausted despite bounded capacity")
            event_id = str(row.event_id)
            if event_id in positions:
                raise ResearchError("duplicate portfolio entry")
            positions[event_id] = notional
            cash -= notional
        for row in exits.get(date, pd.DataFrame()).itertuples(index=False):
            event_id = str(row.event_id)
            if event_id not in positions:
                raise ResearchError("portfolio exit without conserved position")
            notional = positions.pop(event_id)
            cash += notional * (1.0 + float(row.net_return))
        nav = cash + sum(positions.values())
        if not np.isfinite(nav) or cash < -1e-12:
            raise ResearchError("non-finite or negative conserved cash state")
        nav_points.append(nav)
        ledger_rows.append(
            {
                "date": date,
                "cash": cash,
                "open_cost_basis": float(sum(positions.values())),
                "nav_at_open_cost": nav,
                "open_positions": len(positions),
            }
        )
    year_end_nav[previous_year] = cash + sum(positions.values())
    ledger = pd.DataFrame(ledger_rows)
    nav_array = np.asarray(nav_points, dtype=float)
    peaks = np.maximum.accumulate(nav_array)
    drawdown = nav_array / peaks - 1.0
    annual_returns: dict[str, float] = {}
    prior = 1.0
    for year in years:
        nav = year_end_nav.get(year, prior)
        annual_returns[str(year)] = float(nav / prior - 1.0)
        prior = nav
    ending_nav = float(nav_array[-1])
    return ledger, {
        "ending_nav_at_open_cost": ending_nav,
        "annualized_return_at_open_cost": float(ending_nav ** (1.0 / len(years)) - 1.0),
        "realized_closed_trade_max_drawdown": float(drawdown.min()),
        "maximum_open_positions": int(ledger.open_positions.max()),
        "minimum_cash_fraction_of_initial": float(ledger.cash.min()),
        "annual_returns_at_open_cost": annual_returns,
        "unresolved_positions_at_end": int(len(positions)),
        "unresolved_entry_cost_at_end": float(sum(positions.values())),
        "cash_plus_open_cost_basis_conserved": True,
    }


def summarize(frame: pd.DataFrame, years: list[int]) -> dict[str, Any]:
    pooled = metrics(frame)
    complete = frame.loc[
        frame.capacity_status.eq("ADMITTED") & frame.status.eq("COMPLETED")
    ].copy()
    yearly = {
        str(year): metrics(
            frame.loc[pd.to_datetime(frame.signal_date).dt.year.eq(year)]
        )
        for year in years
    }
    by_date = complete.groupby("signal_date", as_index=False).agg(
        completed=("event_id", "size"),
        mean_net=("net_return", "mean"),
        mean_holding=("holding_sessions", "mean"),
    )
    lanes = {
        route: metrics(frame.loc[frame.market_route.eq(route)])
        for route in sorted(frame.market_route.dropna().unique())
    }
    completed_per_year = pooled["completed"] / len(years)
    event_equal = None if by_date.empty else float(by_date.mean_net.mean())
    gates = {
        "completed_per_year_gt_50": completed_per_year > 50,
        "mean_net_ge_4pct": pooled["mean_net"] is not None and pooled["mean_net"] >= 0.04,
        "mean_holding_lt_15": pooled["mean_holding"] is not None and pooled["mean_holding"] < 15,
        "event_equal_mean_ge_4pct": event_equal is not None and event_equal >= 0.04,
        "each_lane_mean_ge_4pct": all(
            row["completed"] > 0 and row["mean_net"] is not None and row["mean_net"] >= 0.04
            for row in lanes.values()
        ),
    }
    return {
        "event_capped_candidates": int(len(frame)),
        "admitted_entries": int(frame.capacity_status.eq("ADMITTED").sum()),
        "capacity_rejected": int(frame.capacity_status.eq("CAPACITY_REJECTED").sum()),
        "no_legal_entry": int(frame.capacity_status.eq("NO_LEGAL_ENTRY").sum()),
        "completed_per_year": float(completed_per_year),
        "pooled": pooled,
        "yearly": yearly,
        "lanes": lanes,
        "distinct_signal_dates": int(len(by_date)),
        "event_equal_mean_net": event_equal,
        "largest_event_share": None
        if complete.empty
        else float(by_date.completed.max() / len(complete)),
        "gates": gates,
        "all_gates_pass": bool(all(gates.values())),
        "by_signal_date": by_date.to_dict("records"),
    }


def run(mode: str) -> dict[str, Any]:
    selected_path, outcomes_path = verify_sources(mode)
    selected = pd.read_parquet(selected_path)
    outcomes = pd.read_parquet(outcomes_path)
    years = list(range(2014, 2022)) if mode == "development" else list(range(2022, 2026))
    capacity = admit_capacity(selected, outcomes)
    ledger, portfolio = cash_ledger(capacity, years)
    summary = summarize(capacity, years)
    output = OUTPUT_ROOT / mode
    output.mkdir(parents=True, exist_ok=True)
    mother.execution.write_parquet(capacity, output / "capacity_decisions.parquet")
    mother.execution.write_parquet(ledger, output / "cash_ledger.parquet")
    result = {
        "experiment": EXPERIMENT,
        "mode": mode,
        "scientific_role": (
            "pre_2022_capacity_development"
            if mode == "development"
            else "post_challenge_diagnostic_not_independent_validation"
        ),
        "capacity_rules": {
            "max_names_per_event": MAX_NAMES_PER_EVENT,
            "max_concurrent_positions": MAX_CONCURRENT_POSITIONS,
            "slot_weight": SLOT_WEIGHT,
            "same_day_exit_funds_reusable_at_open": False,
        },
        "summary": summary,
        "portfolio": portfolio,
    }
    mother.execution.write_json(output / "result.json", result)
    result["output_hashes"] = {
        name: mother.execution.sha256(output / name)
        for name in ("capacity_decisions.parquet", "cash_ledger.parquet", "result.json")
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode", choices=("development", "post-challenge-diagnostic"), required=True
    )
    args = parser.parse_args()
    print(json.dumps(run(args.mode), ensure_ascii=False, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
