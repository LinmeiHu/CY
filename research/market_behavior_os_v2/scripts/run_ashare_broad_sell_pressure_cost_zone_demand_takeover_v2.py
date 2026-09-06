#!/usr/bin/env python3
"""Run the frozen broad seller-cost-zone demand-takeover rule."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

import run_ashare_sell_pressure_cost_zone_volume_reclaim_v1 as mother


REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-BROAD-SELL-PRESSURE-COST-ZONE-DEMAND-TAKEOVER-V2"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
EXPECTED_FREEZE_SHA256 = "ea2fb085ebfbedc1a1d531407475193d1eefd2fa7990d5fe4ce8bb7e51601925"
OUTPUT_ROOT = Path("/Volumes/quant/CY_quant_research") / EXPERIMENT.lower()
DEV_ROOT = mother.OUTPUT_ROOT / "development"
EXPECTED = {
    "mother_freeze": "a8225c15d5b57faebed547002e82658ad3ad7d24827ad247f76efa6c815c8cb4",
    "development_candidates": "ff72c1ff499acc3df5226e03d03bf029b9545f554102b444d8a087265d960cae",
    "development_outcomes": "b9d0706ceef892aa7c0270d6978484633973bc6dd98837de57215440c88e8474",
    "development_result": "07620a3931188044cbf47ecd35b9fc197a71c80a4997eb416634dbc2f17af9e8",
}


class ResearchError(RuntimeError):
    """Fail closed on frozen-input or selection drift."""


def attach_prior_high(candidates: pd.DataFrame, daily: Path) -> pd.DataFrame:
    con = duckdb.connect()
    con.register("candidate_ids", candidates[["event_id", "symbol", "signal_cal_idx"]])
    prior = con.execute(
        f"""
        SELECT c.event_id,p.coord_high AS prior_high
        FROM candidate_ids c
        JOIN read_parquet('{daily.as_posix()}') p
          ON c.symbol=p.symbol AND p.cal_idx=c.signal_cal_idx-1
        """
    ).fetchdf()
    con.close()
    if prior.event_id.duplicated().any():
        raise ResearchError("duplicate prior-high join")
    result = candidates.merge(prior, on="event_id", how="left", validate="one_to_one")
    if result.prior_high.isna().any():
        raise ResearchError("missing strictly prior high")
    return result


def select(candidates: pd.DataFrame, daily: Path) -> pd.DataFrame:
    work = attach_prior_high(candidates, daily)
    work = work.loc[
        work.signal_close.ge(work.prior_high)
        & work.signal_turnover.ge(1.5 * work.signal_prior20_turnover)
    ].copy()
    work["same_date_takeover_count"] = work.groupby("signal_date")[
        "event_id"
    ].transform("size")
    work = work.loc[work.same_date_takeover_count.ge(20)].copy()
    work = work.sort_values(
        ["signal_date", "sleeve", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    if work.event_id.duplicated().any():
        raise ResearchError("duplicate selected event")
    return work


def verify() -> None:
    if mother.execution.sha256(FREEZE) != EXPECTED_FREEZE_SHA256:
        raise ResearchError("V2 freeze hash drift")
    paths = {
        "mother_freeze": mother.FREEZE,
        "development_candidates": DEV_ROOT / "candidates.parquet",
        "development_outcomes": DEV_ROOT / "outcomes.parquet",
        "development_result": DEV_ROOT / "result.json",
    }
    for name, path in paths.items():
        if mother.execution.sha256(path) != EXPECTED[name]:
            raise ResearchError(f"frozen source drift: {name}")


def summarize(selected: pd.DataFrame, outcomes: pd.DataFrame, years: list[int]) -> dict[str, Any]:
    result = mother.summarize(selected, outcomes, years)
    result["all_user_gates_pass"] = all(
        result["gates"][key]
        for key in (
            "completed_trades_per_year_gt_50",
            "pooled_mean_net_ge_4pct",
            "pooled_mean_holding_lt_15",
        )
    )
    complete = outcomes.loc[outcomes.status.eq("COMPLETED")].copy()
    result["by_signal_date"] = (
        complete.groupby("signal_date", as_index=False)
        .agg(
            completed=("event_id", "size"),
            mean_net=("net_return", "mean"),
            mean_holding=("holding_sessions", "mean"),
        )
        .to_dict("records")
    )
    return result


def capacity_diagnostics(
    selected: pd.DataFrame, outcomes: pd.DataFrame, daily: Path
) -> dict[str, Any]:
    con = duckdb.connect()
    con.register("candidate_ids", selected[["event_id", "symbol", "signal_cal_idx"]])
    amounts = con.execute(
        f"""
        SELECT c.event_id,d.amount AS signal_amount
        FROM candidate_ids c
        JOIN read_parquet('{daily.as_posix()}') d
          ON c.symbol=d.symbol AND c.signal_cal_idx=d.cal_idx
        """
    ).fetchdf()
    con.close()
    frame = selected[["event_id", "signal_date"]].merge(
        amounts, on="event_id", validate="one_to_one"
    ).merge(
        outcomes[
            ["event_id", "status", "net_return", "holding_sessions", "exit_reason"]
        ],
        on="event_id",
        validate="one_to_one",
    )
    frame = frame.loc[frame.status.eq("COMPLETED")].copy()
    frame["amount_rank"] = frame.groupby("signal_date").signal_amount.rank(
        method="first", ascending=False
    )
    frame["signal_year"] = pd.to_datetime(frame.signal_date).dt.year
    result: dict[str, Any] = {}
    for limit in (1, 3, 5, 10, 20):
        part = frame.loc[frame.amount_rank.le(limit)].copy()
        result[f"top_{limit}_amount_per_date"] = {
            "completed": int(len(part)),
            "completed_per_year": float(len(part) / 4),
            "mean_net": float(part.net_return.mean()),
            "median_net": float(part.net_return.median()),
            "mean_holding": float(part.holding_sessions.mean()),
            "severe10": float(part.net_return.le(-0.10).mean()),
            "target_hit": float(part.exit_reason.eq("TARGET_10").mean()),
            "by_year": {
                str(year): {
                    "completed": int(len(year_part)),
                    "mean_net": None
                    if year_part.empty
                    else float(year_part.net_return.mean()),
                    "mean_holding": None
                    if year_part.empty
                    else float(year_part.holding_sessions.mean()),
                }
                for year, year_part in (
                    (year, part.loc[part.signal_year.eq(year)])
                    for year in range(2022, 2026)
                )
            },
        }
    return result


def run() -> dict[str, Any]:
    verify()
    dev_candidates = pd.read_parquet(DEV_ROOT / "candidates.parquet")
    dev_outcomes = pd.read_parquet(DEV_ROOT / "outcomes.parquet")
    development_selected = select(dev_candidates, mother.OLD_DAILY)
    development_outcomes = dev_outcomes.loc[
        dev_outcomes.event_id.isin(set(development_selected.event_id))
    ].copy()
    development = summarize(
        development_selected, development_outcomes, list(range(2014, 2022))
    )
    expected = json.loads(FREEZE.read_text(encoding="utf-8"))["development_evidence_2014_2021"]
    checks = {
        "selected_signals": len(development_selected) == expected["selected_signals"],
        "completed": development["pooled"]["completed"] == expected["completed"],
        "mean_net_return": abs(development["pooled"]["mean_net"] - expected["mean_net_return"]) < 1e-15,
        "mean_holding_sessions": abs(development["pooled"]["mean_holding"] - expected["mean_holding_sessions"]) < 1e-15,
    }
    if not all(checks.values()) or not development["all_user_gates_pass"]:
        raise ResearchError(f"development reproduction failed: {checks}")

    challenge_candidates = mother.build_candidates(
        mother.CURRENT_DAILY, "2022-01-01", "2025-12-31"
    )
    challenge_selected = select(challenge_candidates, mother.CURRENT_DAILY)
    paths = mother.build_paths(
        mother.CURRENT_DAILY, challenge_selected, "2026-03-31"
    )
    outcomes = mother.replay(challenge_selected, paths)
    challenge = summarize(challenge_selected, outcomes, list(range(2022, 2026)))

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    mother.execution.write_parquet(challenge_candidates, OUTPUT_ROOT / "mother_candidates.parquet")
    mother.execution.write_parquet(challenge_selected, OUTPUT_ROOT / "selected_candidates.parquet")
    mother.execution.write_parquet(paths, OUTPUT_ROOT / "future_paths.parquet")
    mother.execution.write_parquet(outcomes, OUTPUT_ROOT / "outcomes.parquet")
    result = {
        "experiment": EXPERIMENT,
        "freeze_sha256": EXPECTED_FREEZE_SHA256,
        "development_reproduction_checks": checks,
        "development": development,
        "challenge_2022_2025": challenge,
        "post_challenge_capacity_diagnostic": capacity_diagnostics(
            challenge_selected, outcomes, mother.CURRENT_DAILY
        ),
        "challenge_status_counts": outcomes.status.value_counts().sort_index().to_dict(),
        "future_market_function": False,
        "same_bar_fill": False,
        "no_rescue": True,
    }
    mother.execution.write_json(OUTPUT_ROOT / "result.json", result)
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True, default=str))
