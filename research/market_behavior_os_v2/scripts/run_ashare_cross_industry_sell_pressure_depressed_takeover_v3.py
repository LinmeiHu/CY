#!/usr/bin/env python3
"""Evaluate the cross-industry depressed seller-cost takeover V3.

Development is quarantined to signals through 2021-11-30 and market/outcome
bars through 2021-12-31.  Challenge mode remains fail-closed until a final
freeze records a passing development result.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

import run_ashare_sell_pressure_cost_zone_volume_reclaim_v1 as mother


REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-CROSS-INDUSTRY-SELL-PRESSURE-DEPRESSED-TAKEOVER-V3"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
EXPECTED_FREEZE_SHA256 = "865d4895a7cd30bf95ec906b45321b6d5d7d0cf82f66f7ea9cd684e82528fabf"
OUTPUT_ROOT = Path("/Volumes/quant/CY_quant_research") / EXPERIMENT.lower()
DEV_SOURCE = mother.OUTPUT_ROOT / "development/candidates.parquet"
EXPECTED = {
    "mother_freeze": "a8225c15d5b57faebed547002e82658ad3ad7d24827ad247f76efa6c815c8cb4",
    "development_candidates": "ff72c1ff499acc3df5226e03d03bf029b9545f554102b444d8a087265d960cae",
    "development_daily": "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    "challenge_daily": "95ba886707811da9a0514d1d3a9b2ddf9df5debe69eed4e904502f8f3e1cfca9",
}

MIN_TAKEOVER_STOCKS = 12
MIN_TAKEOVER_INDUSTRIES = 8
DEPRESSED_KEEP_FRACTION = 0.60
MARKET_FAILURE_FLOOR = 0.90
ROUND_TRIP_COST = 0.004


class ResearchError(RuntimeError):
    """Fail closed on chronology, identity, selection, or execution drift."""


def verify_common(daily: Path, expected_daily: str) -> None:
    if mother.execution.sha256(mother.FREEZE) != EXPECTED["mother_freeze"]:
        raise ResearchError("mother freeze drift")
    if mother.execution.sha256(daily) != expected_daily:
        raise ResearchError("daily input drift")


def attach_features(candidates: pd.DataFrame, daily: Path) -> pd.DataFrame:
    max_signal_date = pd.to_datetime(candidates.signal_date).max().date().isoformat()
    con = duckdb.connect()
    con.register(
        "candidate_ids",
        candidates[["event_id", "symbol", "signal_cal_idx"]],
    )
    features = con.execute(
        f"""
        WITH daily AS (
          SELECT *,adjusted_close/nullif(
            lag(adjusted_close,60) OVER (PARTITION BY symbol ORDER BY cal_idx),0.0
          )-1.0 AS derived_ret60
          FROM read_parquet('{daily.as_posix()}')
          WHERE trade_date<=DATE '{max_signal_date}'
        )
        SELECT c.event_id,p.coord_high AS prior_high,
          s.derived_ret60 AS signal_ret60,s.amount AS signal_amount
        FROM candidate_ids c
        JOIN daily p
          ON p.symbol=c.symbol AND p.cal_idx=c.signal_cal_idx-1
        JOIN daily s
          ON s.symbol=c.symbol AND s.cal_idx=c.signal_cal_idx
        """
    ).fetchdf()
    con.close()
    if features.event_id.duplicated().any():
        raise ResearchError("duplicate feature join")
    result = candidates.merge(features, on="event_id", how="left", validate="one_to_one")
    required = ["prior_high", "signal_amount", "causal_industry"]
    if result[required].isna().any().any():
        raise ResearchError("missing required selection feature")
    return result


def select(candidates: pd.DataFrame, daily: Path) -> pd.DataFrame:
    work = attach_features(candidates, daily)
    work = work.loc[
        work.signal_ret60.notna()
        & work.signal_close.ge(work.prior_high)
        & work.signal_turnover.ge(1.5 * work.signal_prior20_turnover)
    ].copy()
    work["same_date_takeover_count"] = work.groupby("signal_date")[
        "event_id"
    ].transform("size")
    work["same_date_industry_count"] = work.groupby("signal_date")[
        "causal_industry"
    ].transform("nunique")
    work = work.loc[
        work.same_date_takeover_count.ge(MIN_TAKEOVER_STOCKS)
        & work.same_date_industry_count.ge(MIN_TAKEOVER_INDUSTRIES)
    ].copy()
    work = work.sort_values(
        ["signal_date", "signal_ret60", "symbol", "event_id"], kind="mergesort"
    )
    work["depressed_rank"] = work.groupby("signal_date").cumcount() + 1
    work["depressed_keep_count"] = np.floor(
        DEPRESSED_KEEP_FRACTION * work.same_date_takeover_count
    ).astype(int)
    work = work.loc[work.depressed_rank.le(work.depressed_keep_count)].copy()
    work = work.sort_values(
        ["signal_date", "depressed_rank", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    if work.event_id.duplicated().any():
        raise ResearchError("duplicate selected event")
    return work


def attach_market_returns(paths: pd.DataFrame, daily: Path, end: str) -> pd.DataFrame:
    con = duckdb.connect()
    market = con.execute(
        f"""
        WITH daily AS (
          SELECT *,adjusted_close/nullif(
            lag(adjusted_close) OVER (PARTITION BY symbol ORDER BY cal_idx),0.0
          )-1.0 AS derived_step_return
          FROM read_parquet('{daily.as_posix()}')
          WHERE trade_date<=DATE '{end}'
        )
        SELECT trade_date,
          median(derived_step_return) FILTER (WHERE
            hard_valid AND history_valid AND current_valid
            AND current_day_data_tradable AND market_rule_valid
            AND corporate_action_valid AND NOT corporate_action_blocking
            AND NOT is_st
          ) AS market_median_return
        FROM daily
        GROUP BY trade_date
        ORDER BY trade_date
        """
    ).fetchdf()
    con.close()
    market["trade_date"] = pd.to_datetime(market.trade_date)
    market = market.loc[market.market_median_return.notna()].copy()
    result = paths.merge(market, on="trade_date", how="left", validate="many_to_one")
    if result.market_median_return.isna().any():
        raise ResearchError("future path missing market return")
    return result


def replay_one(candidate: Any, path: pd.DataFrame) -> dict[str, Any]:
    signal_idx = int(candidate.signal_cal_idx)
    lineage = float(candidate.invalid_step_cum)
    base = {
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_cal_idx": signal_idx,
        "depressed_rank": int(candidate.depressed_rank),
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
    pre_entry = path.loc[
        path.cal_idx.gt(signal_idx) & path.cal_idx.le(entry_idx)
    ]
    if pre_entry.empty or not np.isfinite(pre_entry.market_median_return).all():
        return {**base, "status": "MISSING_MARKET_STATE_BEFORE_ENTRY"}
    market_curve = float((1.0 + pre_entry.market_median_return).prod())
    pending: str | None = (
        "MARKET_TAKEOVER_FAILED" if market_curve <= MARKET_FAILURE_FLOOR else None
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
            if market_curve <= MARKET_FAILURE_FLOOR:
                pending = "MARKET_TAKEOVER_FAILED"
                decision_idx = int(row.cal_idx)
            elif int(row.cal_idx) >= entry_idx + 20:
                pending = "H20_TIME_STOP"
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
        "net_return": gross - ROUND_TRIP_COST,
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


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    complete = frame.loc[frame.status.eq("COMPLETED")].copy()
    return {
        "signals": int(len(frame)),
        "completed": int(len(complete)),
        "mean_net": None if complete.empty else float(complete.net_return.mean()),
        "median_net": None if complete.empty else float(complete.net_return.median()),
        "mean_holding": None if complete.empty else float(complete.holding_sessions.mean()),
        "win": None if complete.empty else float(complete.net_return.gt(0).mean()),
        "severe10": None if complete.empty else float(complete.net_return.le(-0.10).mean()),
        "target_hit": None if complete.empty else float(complete.exit_reason.eq("TARGET_10").mean()),
        "market_failure_exit": None
        if complete.empty
        else float(complete.exit_reason.eq("MARKET_TAKEOVER_FAILED").mean()),
    }


def summarize(selected: pd.DataFrame, outcomes: pd.DataFrame, years: list[int]) -> dict[str, Any]:
    pooled = metrics(outcomes)
    yearly = {
        str(year): metrics(
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
        selected.loc[selected.depressed_rank.le(10), "event_id"].astype(str)
    )
    top10 = metrics(outcomes.loc[outcomes.event_id.astype(str).isin(top10_ids)])
    completed_per_year = pooled["completed"] / len(years)
    date_equal_mean = None if by_date.empty else float(by_date.mean_net.mean())
    largest_date_share = None if by_date.empty else float(by_date.completed.max() / len(complete))
    gates = {
        "completed_per_year_gt_50": completed_per_year > 50,
        "pooled_mean_net_ge_4pct": pooled["mean_net"] is not None and pooled["mean_net"] >= 0.04,
        "pooled_mean_holding_lt_15": pooled["mean_holding"] is not None and pooled["mean_holding"] < 15,
        "signal_date_equal_mean_ge_4pct": date_equal_mean is not None and date_equal_mean >= 0.04,
        "top10_depressed_mean_net_ge_4pct": top10["mean_net"] is not None and top10["mean_net"] >= 0.04,
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
        "positive_signal_date_share": None
        if by_date.empty
        else float(by_date.mean_net.gt(0).mean()),
        "top10_depressed_per_date": top10,
        "by_signal_date": by_date.to_dict("records"),
        "gates": gates,
        "all_gates_pass": bool(all(gates.values())),
    }


def verify_challenge_authorization() -> dict[str, Any]:
    if not FREEZE.is_file():
        raise ResearchError("final V3 freeze missing; challenge remains closed")
    if mother.execution.sha256(FREEZE) != EXPECTED_FREEZE_SHA256:
        raise ResearchError("final V3 freeze drift")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    result_path = OUTPUT_ROOT / "development/result.json"
    if not result_path.is_file():
        raise ResearchError("development result missing; challenge remains closed")
    if mother.execution.sha256(result_path) != freeze.get("development_artifacts", {}).get(
        "development_result_sha256"
    ):
        raise ResearchError("frozen development result drift")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if not result.get("summary", {}).get("all_gates_pass"):
        raise ResearchError("development gates failed; challenge remains closed")
    return freeze


def run(mode: str) -> dict[str, Any]:
    if mode == "development":
        daily = mother.OLD_DAILY
        verify_common(daily, EXPECTED["development_daily"])
        if mother.execution.sha256(DEV_SOURCE) != EXPECTED["development_candidates"]:
            raise ResearchError("frozen development candidate drift")
        candidates = pd.read_parquet(DEV_SOURCE)
        candidates = candidates.loc[
            pd.to_datetime(candidates.signal_date).between("2014-01-01", "2021-11-30")
        ].copy()
        outcome_end = "2021-12-31"
        years = list(range(2014, 2022))
    else:
        verify_challenge_authorization()
        daily = mother.CURRENT_DAILY
        verify_common(daily, EXPECTED["challenge_daily"])
        candidates = mother.build_candidates(daily, "2022-01-01", "2025-12-31")
        outcome_end = "2026-03-31"
        years = list(range(2022, 2026))

    selected = select(candidates, daily)
    paths = mother.build_paths(daily, selected, outcome_end)
    paths = attach_market_returns(paths, daily, outcome_end)
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
        "round_trip_cost": ROUND_TRIP_COST,
        "date_quarantine": {
            "signal_end": "2021-11-30" if mode == "development" else "2025-12-31",
            "outcome_end": outcome_end,
        },
    }
    mother.execution.write_json(output / "result.json", result)
    result["output_hashes"] = {
        name: mother.execution.sha256(output / name)
        for name in (
            "selected_candidates.parquet",
            "future_paths.parquet",
            "outcomes.parquet",
            "result.json",
        )
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("development", "challenge"), required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.mode), ensure_ascii=False, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
