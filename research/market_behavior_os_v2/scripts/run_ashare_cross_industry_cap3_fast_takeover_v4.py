#!/usr/bin/env python3
"""Evaluate V4: capped industry exposure and an H18 time decision."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import run_ashare_cross_industry_sell_pressure_depressed_takeover_v3 as v3


mother = v3.mother
REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-CROSS-INDUSTRY-CAP3-FAST-TAKEOVER-V4"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
OUTPUT_ROOT = Path("/Volumes/quant/CY_quant_research") / EXPERIMENT.lower()
MAX_PER_INDUSTRY = 3
TIME_HORIZON = 18
EXPECTED_FREEZE_SHA256 = "2f7290d1c8ff0c080f8019aa88050813388cfb56f97a857a350c8b2764aa5864"


class ResearchError(RuntimeError):
    """Fail closed on frozen authorization or execution-state drift."""


def select(candidates: pd.DataFrame, daily: Path) -> pd.DataFrame:
    work = v3.select(candidates, daily)
    work = work.sort_values(
        ["signal_date", "causal_industry", "signal_ret60", "symbol", "event_id"],
        kind="mergesort",
    )
    work["industry_rank"] = work.groupby(
        ["signal_date", "causal_industry"], sort=False
    ).cumcount() + 1
    work = work.loc[work.industry_rank.le(MAX_PER_INDUSTRY)].copy()
    work = work.sort_values(
        ["signal_date", "industry_rank", "signal_ret60", "symbol", "event_id"],
        kind="mergesort",
    )
    work["diversified_rank"] = work.groupby("signal_date", sort=False).cumcount() + 1
    work = work.reset_index(drop=True)
    if work.event_id.duplicated().any():
        raise ResearchError("duplicate selected event")
    return work


def replay_one(candidate: Any, path: pd.DataFrame) -> dict[str, Any]:
    signal_idx = int(candidate.signal_cal_idx)
    lineage = float(candidate.invalid_step_cum)
    base = {
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_cal_idx": signal_idx,
        "industry_rank": int(candidate.industry_rank),
        "diversified_rank": int(candidate.diversified_rank),
        "signal_ret60": float(candidate.signal_ret60),
    }
    entry_pool = path.loc[
        path.cal_idx.le(signal_idx + 3) & path.invalid_step_cum.eq(lineage)
    ]
    entry = next(
        (row for _, row in entry_pool.iterrows() if mother.execution.buyable_open(row)),
        None,
    )
    if entry is None:
        return {**base, "status": "NO_LEGAL_ENTRY"}
    entry_idx = int(entry.cal_idx)
    entry_price = float(entry.coord_open)
    target = entry_price * 1.10
    pre_entry = path.loc[path.cal_idx.gt(signal_idx) & path.cal_idx.le(entry_idx)]
    if pre_entry.empty or not np.isfinite(pre_entry.market_median_return).all():
        return {**base, "status": "MISSING_MARKET_STATE_BEFORE_ENTRY"}
    market_curve = float((1.0 + pre_entry.market_median_return).prod())
    pending: str | None = (
        "MARKET_TAKEOVER_FAILED" if market_curve <= v3.MARKET_FAILURE_FLOOR else None
    )
    exit_row: pd.Series | None = None
    exit_price = math.nan
    exit_reason: str | None = None
    decision_idx: int | None = entry_idx if pending else None
    invalid = False

    for _, row in path.loc[path.cal_idx.gt(entry_idx)].iterrows():
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != lineage:
            invalid = True
            break
        if pending is not None and mother.execution.sellable_open(row):
            exit_row = row
            exit_price = float(row.coord_open)
            exit_reason = pending
            break
        if (
            mother.execution.legal_state(row)
            and np.isfinite(float(row.coord_high))
            and float(row.coord_high) >= target
        ):
            exit_row = row
            exit_price = target
            exit_reason = "TARGET_10"
            decision_idx = entry_idx
            break
        if mother.execution.legal_state(row):
            market_return = float(row.market_median_return)
            if not np.isfinite(market_return):
                invalid = True
                break
            market_curve *= 1.0 + market_return
            if market_curve <= v3.MARKET_FAILURE_FLOOR:
                pending = "MARKET_TAKEOVER_FAILED"
                decision_idx = int(row.cal_idx)
            elif int(row.cal_idx) >= entry_idx + TIME_HORIZON:
                pending = "H18_TIME_STOP"
                decision_idx = int(row.cal_idx)

    entry_payload = {
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": entry_idx,
        "entry_price": entry_price,
    }
    if invalid:
        return {**base, "status": "INVALID_REQUIRED_STATE_AFTER_ENTRY", **entry_payload}
    if exit_row is None:
        return {**base, "status": "INCOMPLETE_BY_OUTCOME_END", **entry_payload}
    gross = float(exit_price) / entry_price - 1.0
    return {
        **base,
        "status": "COMPLETED",
        **entry_payload,
        "exit_date": pd.Timestamp(exit_row.trade_date),
        "exit_cal_idx": int(exit_row.cal_idx),
        "exit_price": float(exit_price),
        "exit_reason": exit_reason,
        "exit_decision_cal_idx": decision_idx,
        "holding_sessions": int(exit_row.cal_idx) - entry_idx,
        "gross_return": gross,
        "net_return": gross - v3.ROUND_TRIP_COST,
    }


def replay(candidates: pd.DataFrame, paths: pd.DataFrame) -> pd.DataFrame:
    grouped = {key: part for key, part in paths.groupby("event_id", sort=False)}
    rows = [
        replay_one(candidate, grouped.get(candidate.event_id, pd.DataFrame()))
        for candidate in candidates.itertuples(index=False)
    ]
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    for column in ("signal_date", "entry_date", "exit_date"):
        if column in result:
            result[column] = pd.to_datetime(result[column])
    complete = result.loc[result.status.eq("COMPLETED")]
    if complete.entry_cal_idx.le(complete.signal_cal_idx).any():
        raise ResearchError("entry at or before signal")
    if complete.exit_cal_idx.le(complete.entry_cal_idx).any():
        raise ResearchError("exit at or before entry")
    return result


def summarize(selected: pd.DataFrame, outcomes: pd.DataFrame, years: list[int]) -> dict[str, Any]:
    pooled = v3.metrics(outcomes)
    yearly = {
        str(year): v3.metrics(
            outcomes.loc[pd.to_datetime(outcomes.signal_date).dt.year.eq(year)]
        )
        for year in years
    }
    complete = outcomes.loc[outcomes.status.eq("COMPLETED")].copy()
    by_date = (
        complete.groupby("signal_date", as_index=False)
        .agg(
            completed=("event_id", "size"),
            mean_net=("net_return", "mean"),
            mean_holding=("holding_sessions", "mean"),
        )
        if not complete.empty
        else pd.DataFrame()
    )
    top10_ids = set(
        selected.loc[selected.diversified_rank.le(10), "event_id"].astype(str)
    )
    top10 = v3.metrics(outcomes.loc[outcomes.event_id.astype(str).isin(top10_ids)])
    completed_per_year = pooled["completed"] / len(years)
    date_equal_mean = None if by_date.empty else float(by_date.mean_net.mean())
    largest_date_share = None if by_date.empty else float(by_date.completed.max() / len(complete))
    gates = {
        "completed_per_year_gt_50": completed_per_year > 50,
        "pooled_mean_net_ge_4pct": pooled["mean_net"] is not None and pooled["mean_net"] >= 0.04,
        "pooled_mean_holding_lt_15": pooled["mean_holding"] is not None and pooled["mean_holding"] < 15,
        "signal_date_equal_mean_ge_4pct": date_equal_mean is not None and date_equal_mean >= 0.04,
        "diversified_top10_mean_net_ge_4pct": top10["mean_net"] is not None and top10["mean_net"] >= 0.04,
        "at_least_24_signal_dates": len(by_date) >= 24,
        "largest_date_share_le_20pct": largest_date_share is not None and largest_date_share <= 0.20,
        "every_year_with_trades_positive": all(
            row["completed"] == 0 or row["mean_net"] > 0 for row in yearly.values()
        ),
    }
    return {
        "selected_signals": int(len(selected)),
        "completed_per_year": float(completed_per_year),
        "pooled": pooled,
        "yearly": yearly,
        "distinct_signal_dates": int(len(by_date)),
        "signal_date_equal_weight_mean_net": date_equal_mean,
        "largest_date_share": largest_date_share,
        "positive_signal_date_share": None if by_date.empty else float(by_date.mean_net.gt(0).mean()),
        "diversified_top10_per_date": top10,
        "by_signal_date": by_date.to_dict("records"),
        "gates": gates,
        "all_gates_pass": bool(all(gates.values())),
    }


def verify_challenge_authorization() -> dict[str, Any]:
    if not FREEZE.is_file():
        raise ResearchError("final V4 freeze missing; challenge remains closed")
    if mother.execution.sha256(FREEZE) != EXPECTED_FREEZE_SHA256:
        raise ResearchError("final V4 freeze drift")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    result_path = OUTPUT_ROOT / "development/result.json"
    if not result_path.is_file():
        raise ResearchError("development result missing; challenge remains closed")
    expected_result = freeze.get("development_artifacts", {}).get("result_sha256")
    if mother.execution.sha256(result_path) != expected_result:
        raise ResearchError("frozen V4 development result drift")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if not result.get("summary", {}).get("all_gates_pass"):
        raise ResearchError("V4 development gates failed; challenge remains closed")
    return freeze


def run(mode: str) -> dict[str, Any]:
    if mode == "development":
        daily = mother.OLD_DAILY
        v3.verify_common(daily, v3.EXPECTED["development_daily"])
        if mother.execution.sha256(v3.DEV_SOURCE) != v3.EXPECTED["development_candidates"]:
            raise ResearchError("frozen development candidate drift")
        candidates = pd.read_parquet(v3.DEV_SOURCE)
        candidates = candidates.loc[
            pd.to_datetime(candidates.signal_date).between("2014-01-01", "2021-11-30")
        ].copy()
        outcome_end = "2021-12-31"
        years = list(range(2014, 2022))
    else:
        verify_challenge_authorization()
        daily = mother.CURRENT_DAILY
        v3.verify_common(daily, v3.EXPECTED["challenge_daily"])
        candidates = mother.build_candidates(daily, "2022-01-01", "2025-12-31")
        outcome_end = "2026-03-31"
        years = list(range(2022, 2026))

    selected = select(candidates, daily)
    paths = mother.build_paths(daily, selected, outcome_end)
    paths = v3.attach_market_returns(paths, daily, outcome_end)
    outcomes = replay(selected, paths)
    summary = summarize(selected, outcomes, years)
    output = OUTPUT_ROOT / mode
    output.mkdir(parents=True, exist_ok=True)
    mother.execution.write_parquet(selected, output / "selected_candidates.parquet")
    mother.execution.write_parquet(paths, output / "future_paths.parquet")
    mother.execution.write_parquet(outcomes, output / "outcomes.parquet")
    result = {
        "experiment": EXPERIMENT,
        "mode": mode,
        "summary": summary,
        "status_counts": outcomes.status.value_counts().sort_index().to_dict(),
        "future_market_function": False,
        "same_bar_fill": False,
        "round_trip_cost": v3.ROUND_TRIP_COST,
        "date_quarantine": {
            "signal_end": "2021-11-30" if mode == "development" else "2025-12-31",
            "outcome_end": outcome_end,
        },
    }
    mother.execution.write_json(output / "result.json", result)
    result["output_hashes"] = {
        name: mother.execution.sha256(output / name)
        for name in ("selected_candidates.parquet", "future_paths.parquet", "outcomes.parquet", "result.json")
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("development", "challenge"), required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.mode), ensure_ascii=False, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
