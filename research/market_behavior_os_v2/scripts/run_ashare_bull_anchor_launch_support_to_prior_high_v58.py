#!/usr/bin/env python3
"""Evaluate the frozen V58 launch-support to prior-high strategy."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import run_ashare_bull_board_rotation_low_overhang_pressure_release_v54 as core  # noqa: E402
import run_ashare_bull_anchor_cost_first_dry_pullback_v56 as gate  # noqa: E402


EXPERIMENT = "ASHARE-BULL-ANCHOR-LAUNCH-SUPPORT-TO-PRIOR-HIGH-V58"
ROOT = Path("/Volumes/quant/CY_quant_research/bull_anchor_launch_support_to_prior_high_v58")
CANDIDATES = ROOT / "stage_a/candidates.parquet"
DEV_OUTCOMES = ROOT / "stage_b/development_outcomes.parquet"
PROFILE_TABLE = ROOT / "stage_b/development_profile_table.parquet"
PROFILE_FREEZE = ROOT / "stage_b/profile_freeze.json"
FORWARD_OUTCOMES = ROOT / "stage_b/forward_outcomes.parquet"
ACCEPTED = ROOT / "stage_b/portfolio_accepted.parquet"
SKIPPED = ROOT / "stage_b/portfolio_skipped.parquet"
NAV = ROOT / "stage_b/portfolio_nav.parquet"
RESULT = HERE.parent / "artifacts" / f"{EXPERIMENT}_result.json"
CONTRACT = HERE.parent / "experiments" / f"{EXPERIMENT}_contract.json"
SPEC = HERE.parent / "experiments" / f"{EXPERIMENT}_spec.json"
FREEZE = HERE.parent / "artifacts" / f"{EXPERIMENT}_stage_a_freeze.json"
DEV_YEARS = list(range(2014, 2021))
MEANINGFUL_DEV_YEARS = [2014, 2015, 2016, 2019, 2020]
FORWARD_YEARS = [2021, 2022, 2023]
ENTRY_COST = EXIT_COST = 0.002
PROFILES = {
    "U_H5_X0": {"horizon": 5, "failure": False},
    "U_H8_X0": {"horizon": 8, "failure": False},
    "U_H12_X0": {"horizon": 12, "failure": False},
    "U_H5_X1": {"horizon": 5, "failure": True},
    "U_H8_X1": {"horizon": 8, "failure": True},
    "U_H12_X1": {"horizon": 12, "failure": True},
}


class ResearchError(RuntimeError):
    pass


def configure() -> None:
    core.EXPERIMENT = EXPERIMENT
    core.ROOT = ROOT
    core.CANDIDATES = CANDIDATES
    core.DEV_OUTCOMES = DEV_OUTCOMES
    core.PROFILE_TABLE = PROFILE_TABLE
    core.PROFILE_FREEZE = PROFILE_FREEZE
    core.FORWARD_OUTCOMES = FORWARD_OUTCOMES
    core.ACCEPTED = ACCEPTED
    core.SKIPPED = SKIPPED
    core.NAV = NAV
    core.RESULT = RESULT
    core.CONTRACT = CONTRACT
    core.SPEC = SPEC
    core.FREEZE = FREEZE


def build_outcomes(
    candidates: pd.DataFrame, include_resolution_tail: bool, output: Path
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    daily = core.load_daily(candidates.symbol.astype(str).unique().tolist(), include_resolution_tail)
    groups = {
        symbol: part.sort_values("trade_date").reset_index(drop=True)
        for symbol, part in daily.groupby("symbol", sort=False)
    }
    rows: list[dict[str, Any]] = []
    for event in candidates.itertuples(index=False):
        stock = groups[str(event.symbol)]
        positions = np.flatnonzero(stock.trade_date.eq(event.signal_date).to_numpy())
        if len(positions) != 1:
            raise ResearchError(f"Missing signal row: {event.event_id}")
        signal_pos = int(positions[0])
        lineage = float(event.invalid_step_cum)
        entry_pos = None
        for pos in range(signal_pos + 1, len(stock)):
            if int(stock.iloc[pos].cal_idx) > int(event.cal_idx) + 3:
                break
            if core.v1.legal_buy(stock.iloc[pos], lineage):
                entry_pos = pos
                break
        common = {
            "event_id": event.event_id,
            "symbol": event.symbol,
            "sleeve": event.sleeve,
            "signal_date": event.signal_date,
            "signal_cal_idx": int(event.cal_idx),
            "overhead_share": float(event.signal_vs_anchor_turnover),
            "industry_positive_ret20_share": float(event.industry_breadth20),
            "stock_minus_industry_ret20": float(event.industry_minus_market20),
            "turnover_expansion": float(event.anchor_turnover_ratio),
            "frozen_floor": float(event.anchor_base),
            "frozen_target": float(event.anchor_high),
        }
        for profile, setting in PROFILES.items():
            base = {**common, "profile": profile}
            if entry_pos is None:
                rows.append({**base, "status": "NO_LEGAL_ENTRY"})
                continue
            entry = stock.iloc[entry_pos]
            entry_price = float(entry.coord_open)
            target = float(event.anchor_high)
            net_room = target / entry_price - 1 - ENTRY_COST - EXIT_COST
            if net_room < 0.03:
                rows.append(
                    {
                        **base,
                        "status": "INSUFFICIENT_ENTRY_NET_TARGET_ROOM",
                        "entry_date": entry.trade_date,
                        "entry_cal_idx": int(entry.cal_idx),
                        "entry_price": entry_price,
                        "entry_net_target_room": net_room,
                    }
                )
                continue
            horizon = int(entry.cal_idx) + int(setting["horizon"])
            exit_pos = None
            exit_price = None
            exit_reason = None
            exit_at_open = None
            decision_cal_idx = None
            invalid = False
            for pos in range(entry_pos + 1, len(stock)):
                row = stock.iloc[pos]
                if float(row.invalid_step_cum) != lineage:
                    invalid = True
                    break
                if core.v1.legal_state(row, lineage) and float(row.coord_high) >= target:
                    exit_pos = pos
                    exit_price = target
                    exit_reason = "ANCHOR_HIGH_TARGET"
                    exit_at_open = False
                    decision_cal_idx = int(row.cal_idx)
                    break
                failure = bool(setting["failure"]) and core.v1.legal_state(row, lineage) and float(row.coord_close) < float(event.anchor_base)
                timed_out = core.v1.legal_state(row, lineage) and int(row.cal_idx) >= horizon
                if failure or timed_out:
                    decision_cal_idx = int(row.cal_idx)
                    for later in range(pos + 1, len(stock)):
                        later_row = stock.iloc[later]
                        if float(later_row.invalid_step_cum) != lineage:
                            invalid = True
                            break
                        if core.v1.legal_sell_open(later_row, lineage):
                            exit_pos = later
                            exit_price = float(later_row.coord_open)
                            exit_reason = "LAUNCH_SUPPORT_FAILURE" if failure else f"H{setting['horizon']}_TIME_STOP"
                            exit_at_open = True
                            break
                    break
            if invalid:
                rows.append({**base, "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY", "entry_date": entry.trade_date, "entry_cal_idx": int(entry.cal_idx), "entry_price": entry_price})
                continue
            if exit_pos is None:
                rows.append({**base, "status": "INCOMPLETE_OUTCOME_TAIL", "entry_date": entry.trade_date, "entry_cal_idx": int(entry.cal_idx), "entry_price": entry_price})
                continue
            exit_row = stock.iloc[exit_pos]
            gross = float(exit_price) / entry_price - 1
            rows.append(
                {
                    **base,
                    "status": "COMPLETED",
                    "entry_date": entry.trade_date,
                    "entry_cal_idx": int(entry.cal_idx),
                    "entry_price": entry_price,
                    "entry_net_target_room": net_room,
                    "exit_date": exit_row.trade_date,
                    "exit_cal_idx": int(exit_row.cal_idx),
                    "exit_price": float(exit_price),
                    "exit_reason": exit_reason,
                    "exit_at_open": exit_at_open,
                    "exit_decision_cal_idx": decision_cal_idx,
                    "holding_sessions": int(exit_row.cal_idx) - int(entry.cal_idx),
                    "gross_return": gross,
                    "net_return": gross - ENTRY_COST - EXIT_COST,
                }
            )
    outcomes = pd.DataFrame(rows)
    for column in ("signal_date", "entry_date", "exit_date"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    core.v1.write_parquet(outcomes, output)
    audit = {
        "signal_bar_fill_count": int((outcomes.entry_date.notna() & outcomes.entry_date.le(outcomes.signal_date)).sum()),
        "t1_same_day_exit_count": int((outcomes.status.eq("COMPLETED") & outcomes.exit_cal_idx.le(outcomes.entry_cal_idx)).sum()),
        "target_at_or_before_entry_count": int((outcomes.status.eq("COMPLETED") & outcomes.frozen_target.le(outcomes.entry_price)).sum()),
    }
    if any(audit.values()):
        raise ResearchError(str(audit))
    return outcomes, daily, audit


def summarize(frame: pd.DataFrame) -> dict[str, Any]:
    done = frame.loc[frame.status.eq("COMPLETED")]
    if done.empty:
        return {"completed_trades": 0, "mean_net": None, "median_net": None, "win_rate": None, "target_hit_rate": None, "severe_loss10": None, "mean_holding_sessions": None, "median_holding_sessions": None}
    return {
        "completed_trades": len(done),
        "mean_net": float(done.net_return.mean()),
        "median_net": float(done.net_return.median()),
        "win_rate": float(done.net_return.gt(0).mean()),
        "target_hit_rate": float(done.exit_reason.eq("ANCHOR_HIGH_TARGET").mean()),
        "severe_loss10": float(done.net_return.le(-0.10).mean()),
        "mean_holding_sessions": float(done.holding_sessions.mean()),
        "median_holding_sessions": float(done.holding_sessions.median()),
    }


def run() -> dict[str, Any]:
    configure()
    stage_a = core.verify_stage_a()
    candidates = core.v1.read_parquet_duckdb(CANDIDATES)
    candidates.signal_date = pd.to_datetime(candidates.signal_date)
    dev_candidates = candidates.loc[candidates.signal_date.dt.year.isin(DEV_YEARS)]
    outcomes, daily, audit = build_outcomes(dev_candidates, False, DEV_OUTCOMES)
    rows = []
    for profile, setting in PROFILES.items():
        part = outcomes.loc[outcomes.profile.eq(profile)]
        accepted, skipped, _nav, portfolio = core.replay(part, daily)
        accepted = accepted.assign(status="COMPLETED")
        annual = {str(year): summarize(accepted.loc[accepted.signal_date.dt.year.eq(year)]) for year in DEV_YEARS}
        meaningful = [annual[str(year)]["mean_net"] for year in MEANINGFUL_DEV_YEARS]
        rows.append({
            "profile": profile,
            **summarize(accepted),
            "all_meaningful_years_positive": bool(all(value is not None and value > 0 for value in meaningful)),
            "median_meaningful_year_mean_net": float(np.median(meaningful)) if all(value is not None for value in meaningful) else math.nan,
            "annual_json": json.dumps(annual, sort_keys=True),
            "capacity_skips": len(skipped),
            "portfolio_json": json.dumps(portfolio, sort_keys=True),
        })
    table = pd.DataFrame(rows)
    core.v1.write_parquet(table, PROFILE_TABLE)
    eligible = table.loc[(table.completed_trades >= 450) & (table.mean_net > 0.03) & (table.mean_holding_sessions < 15) & table.all_meaningful_years_positive]
    if eligible.empty:
        result = {"experiment": EXPERIMENT, "verdict": "ANCHOR_LAUNCH_SUPPORT_TO_PRIOR_HIGH_DEVELOPMENT_FAILED", "stage_a": stage_a, "development_profile_table": gate.finite_records(table), "development_audit": audit, "forward_2021_2023_opened": False, "repository_2024_plus_signal_or_feature_opened": False}
        core.write_json(RESULT, result)
        return result
    selected = eligible.assign(no_failure=eligible.profile.str.endswith("X0"), horizon=eligible.profile.str.extract(r"H(\d+)")[0].astype(int)).sort_values(["median_meaningful_year_mean_net", "mean_net", "severe_loss10", "mean_holding_sessions", "no_failure", "horizon"], ascending=[False, False, True, True, False, True]).iloc[0]
    profile = str(selected.profile)
    core.write_json(PROFILE_FREEZE, {"experiment": EXPERIMENT, "selected_profile": profile, "candidate_sha256": core.sha256(CANDIDATES), "development_outcomes_sha256": core.sha256(DEV_OUTCOMES), "profile_table_sha256": core.sha256(PROFILE_TABLE), "forward_opened": False})
    forward_candidates = candidates.loc[candidates.signal_date.dt.year.isin(FORWARD_YEARS)]
    forward_outcomes, forward_daily, forward_audit = build_outcomes(forward_candidates, True, FORWARD_OUTCOMES)
    chosen = pd.concat([outcomes, forward_outcomes], ignore_index=True).loc[lambda frame: frame.profile.eq(profile)]
    combined_daily = pd.concat([daily, forward_daily], ignore_index=True).drop_duplicates(["trade_date", "symbol"], keep="last")
    accepted, skipped, nav, portfolio = core.replay(chosen, combined_daily)
    core.v1.write_parquet(accepted, ACCEPTED); core.v1.write_parquet(skipped, SKIPPED); core.v1.write_parquet(nav, NAV)
    overall = summarize(accepted.assign(status="COMPLETED"))
    annual = {str(year): summarize(accepted.loc[accepted.signal_date.dt.year.eq(year)].assign(status="COMPLETED")) for year in DEV_YEARS + FORWARD_YEARS}
    conc = gate.concentration(accepted)
    forward_positive = all(annual[str(year)]["mean_net"] is not None and annual[str(year)]["mean_net"] > 0 for year in FORWARD_YEARS)
    passed = len(accepted) > 500 and overall["mean_net"] > 0.03 and overall["mean_holding_sessions"] < 15 and forward_positive and conc["mean_excluding_best_five_signal_dates"] > 0 and conc["top_five_positive_date_pnl_share"] <= 0.25
    result = {"experiment": EXPERIMENT, "verdict": "ANCHOR_LAUNCH_SUPPORT_TO_PRIOR_HIGH_EDGE" if passed else "ANCHOR_LAUNCH_SUPPORT_TO_PRIOR_HIGH_FAILED_FORWARD_OR_TARGET", "selected_profile": profile, "capacity_accepted_completed_trades": len(accepted), "average_completed_trades_per_2014_2023_year": len(accepted)/10, "overall_2014_2023": overall, "annual": annual, "concentration": conc, "portfolio": portfolio, "development_profile_table": gate.finite_records(table), "audit": {**audit, **{f"forward_{key}": value for key, value in forward_audit.items()}, "profile_frozen_before_forward_open": True, "feature_after_decision_count": 0, "repository_2024_plus_signal_or_feature_opened": False, "post_2023_rows_used_only_to_resolve_pre_2024_trades": True}}
    core.write_json(RESULT, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--run", action="store_true"); args = parser.parse_args()
    if not args.run: parser.error("choose --run")
    print(json.dumps(run(), indent=2, default=str))


if __name__ == "__main__":
    main()
