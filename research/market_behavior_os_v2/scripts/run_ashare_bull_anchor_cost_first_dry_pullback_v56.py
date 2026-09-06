#!/usr/bin/env python3
"""Evaluate the outcome-blind frozen V56 demand-cost first dry-test contract."""

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


EXPERIMENT = "ASHARE-BULL-ANCHOR-COST-FIRST-DRY-PULLBACK-V56"
ROOT = Path("/Volumes/quant/CY_quant_research/bull_anchor_cost_first_dry_pullback_v56")
CANDIDATES = ROOT / "stage_a/final_candidates.parquet"
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
PROFILES = {
    "T10_H8_X0": {"target": 0.10, "horizon": 8, "failure": False},
    "T10_H12_X0": {"target": 0.10, "horizon": 12, "failure": False},
    "T15_H8_X0": {"target": 0.15, "horizon": 8, "failure": False},
    "T15_H12_X0": {"target": 0.15, "horizon": 12, "failure": False},
    "T10_H8_X1": {"target": 0.10, "horizon": 8, "failure": True},
    "T10_H12_X1": {"target": 0.10, "horizon": 12, "failure": True},
    "T15_H8_X1": {"target": 0.15, "horizon": 8, "failure": True},
    "T15_H12_X1": {"target": 0.15, "horizon": 12, "failure": True},
}


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
    core.PROFILES = PROFILES


def finite_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return frame.replace({np.nan: None}).to_dict("records")


def concentration(accepted: pd.DataFrame) -> dict[str, Any]:
    if accepted.empty:
        return {
            "mean_excluding_best_five_signal_dates": None,
            "top_five_positive_date_pnl_share": None,
            "maximum_signal_date_trade_share": None,
        }
    by_date = accepted.groupby("signal_date", as_index=False).agg(
        pnl=("net_return", "sum"), trades=("event_id", "size")
    )
    top = by_date.nlargest(5, "pnl")
    positive_total = float(by_date.pnl.clip(lower=0).sum())
    return {
        "mean_excluding_best_five_signal_dates": float(
            accepted.loc[~accepted.signal_date.isin(top.signal_date), "net_return"].mean()
        ),
        "top_five_positive_date_pnl_share": (
            float(top.pnl.clip(lower=0).sum() / positive_total) if positive_total > 0 else None
        ),
        "maximum_signal_date_trade_share": float(by_date.trades.max() / len(accepted)),
    }


def run() -> dict[str, Any]:
    configure()
    stage_a = core.verify_stage_a()
    candidates = core.v1.read_parquet_duckdb(CANDIDATES)
    candidates.signal_date = pd.to_datetime(candidates.signal_date)
    dev_candidates = candidates.loc[candidates.signal_date.dt.year.isin(DEV_YEARS)]
    outcomes, daily, audit = core.build_outcomes(dev_candidates, False, DEV_OUTCOMES)
    rows: list[dict[str, Any]] = []
    replay_cache: dict[str, tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]] = {}
    for profile, setting in PROFILES.items():
        part = outcomes.loc[outcomes.profile.eq(profile)]
        replay_cache[profile] = core.replay(part, daily)
        accepted = replay_cache[profile][0]
        accepted_status = accepted.assign(status="COMPLETED")
        annual = {
            str(year): core.summarize(
                accepted_status.loc[accepted_status.signal_date.dt.year.eq(year)],
                setting["target"],
            )
            for year in DEV_YEARS
        }
        meaningful = [annual[str(year)]["mean_net"] for year in MEANINGFUL_DEV_YEARS]
        metrics = core.summarize(accepted_status, setting["target"])
        rows.append(
            {
                "profile": profile,
                **metrics,
                "all_meaningful_years_positive": bool(
                    all(value is not None and value > 0 for value in meaningful)
                ),
                "median_meaningful_year_mean_net": float(np.median(meaningful))
                if all(value is not None for value in meaningful)
                else math.nan,
                "annual_json": json.dumps(annual, sort_keys=True),
                "capacity_skips": len(replay_cache[profile][1]),
                "portfolio_json": json.dumps(replay_cache[profile][3], sort_keys=True),
            }
        )
    table = pd.DataFrame(rows)
    PROFILE_TABLE.parent.mkdir(parents=True, exist_ok=True)
    core.v1.write_parquet(table, PROFILE_TABLE)
    eligible = table.loc[
        (table.completed_trades >= 450)
        & (table.mean_net > 0.03)
        & (table.mean_holding_sessions < 15)
        & table.all_meaningful_years_positive
    ]
    if eligible.empty:
        result = {
            "experiment": EXPERIMENT,
            "verdict": "ANCHOR_COST_FIRST_DRY_PULLBACK_DEVELOPMENT_FAILED",
            "stage_a": stage_a,
            "development_profile_table": finite_records(table),
            "development_audit": audit,
            "forward_2021_2023_opened": False,
            "repository_2024_plus_signal_or_feature_opened": False,
        }
        core.write_json(RESULT, result)
        return result
    selected = eligible.assign(
        no_failure=eligible.profile.str.endswith("X0"),
        target=eligible.profile.str.extract(r"T(\d+)")[0].astype(int),
    ).sort_values(
        ["median_meaningful_year_mean_net", "mean_net", "severe_loss10", "mean_holding_sessions", "no_failure", "target"],
        ascending=[False, False, True, True, False, True],
    ).iloc[0]
    profile = str(selected.profile)
    core.write_json(
        PROFILE_FREEZE,
        {
            "experiment": EXPERIMENT,
            "selected_profile": profile,
            "candidate_sha256": core.sha256(CANDIDATES),
            "development_outcomes_sha256": core.sha256(DEV_OUTCOMES),
            "profile_table_sha256": core.sha256(PROFILE_TABLE),
            "forward_opened": False,
        },
    )
    forward_candidates = candidates.loc[candidates.signal_date.dt.year.isin(FORWARD_YEARS)]
    forward_outcomes, forward_daily, forward_audit = core.build_outcomes(
        forward_candidates, True, FORWARD_OUTCOMES
    )
    chosen = pd.concat([outcomes, forward_outcomes], ignore_index=True).loc[
        lambda frame: frame.profile.eq(profile)
    ]
    combined_daily = pd.concat([daily, forward_daily], ignore_index=True).drop_duplicates(
        ["trade_date", "symbol"], keep="last"
    )
    accepted, skipped, nav, portfolio = core.replay(chosen, combined_daily)
    core.v1.write_parquet(accepted, ACCEPTED)
    core.v1.write_parquet(skipped, SKIPPED)
    core.v1.write_parquet(nav, NAV)
    setting = PROFILES[profile]
    overall = core.summarize(accepted.assign(status="COMPLETED"), setting["target"])
    annual = {
        str(year): core.summarize(
            accepted.loc[accepted.signal_date.dt.year.eq(year)].assign(status="COMPLETED"),
            setting["target"],
        )
        for year in DEV_YEARS + FORWARD_YEARS
    }
    conc = concentration(accepted)
    forward_positive = all(
        annual[str(year)]["mean_net"] is not None and annual[str(year)]["mean_net"] > 0
        for year in FORWARD_YEARS
    )
    passed = (
        len(accepted) > 500
        and overall["mean_net"] > 0.03
        and overall["mean_holding_sessions"] < 15
        and forward_positive
        and conc["mean_excluding_best_five_signal_dates"] > 0
        and conc["top_five_positive_date_pnl_share"] <= 0.25
    )
    result = {
        "experiment": EXPERIMENT,
        "verdict": "ANCHOR_COST_FIRST_DRY_PULLBACK_EDGE" if passed else "ANCHOR_COST_FIRST_DRY_PULLBACK_FAILED_FORWARD_OR_TARGET",
        "selected_profile": profile,
        "capacity_accepted_completed_trades": len(accepted),
        "average_completed_trades_per_2014_2023_year": len(accepted) / 10,
        "overall_2014_2023": overall,
        "annual": annual,
        "concentration": conc,
        "portfolio": portfolio,
        "development_profile_table": finite_records(table),
        "audit": {
            **audit,
            **{f"forward_{key}": value for key, value in forward_audit.items()},
            "profile_frozen_before_forward_open": True,
            "feature_after_decision_count": 0,
            "repository_2024_plus_signal_or_feature_opened": False,
            "post_2023_rows_used_only_to_resolve_pre_2024_trades": True,
        },
    }
    core.write_json(RESULT, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        parser.error("choose --run")
    print(json.dumps(run(), indent=2, default=str))


if __name__ == "__main__":
    main()
