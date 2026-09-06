#!/usr/bin/env python3
"""Evaluate an outcome-blind seller-cost-zone volume-reclaim rule.

Development is restricted to signals formed before 2022.  Challenge mode is
fail-closed unless the persisted development result passes every frozen gate.
Signals form at the completed daily close and can only fill at a later legal
open under the existing T+1, limit, suspension, corporate-action, and lineage
contracts reused from the broad panic-absorption runner.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

import run_ashare_panic_absorption_broad_capitulation_v2 as execution


REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-SELL-PRESSURE-COST-ZONE-VOLUME-RECLAIM-V1"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
OLD_DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
CURRENT_DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_clean_corridor_v26_validation_2024_2025_v1/"
    "pit_daily_qd010_exact_2022_2026q1.parquet"
)
OUTPUT_ROOT = Path("/Volumes/quant/CY_quant_research") / EXPERIMENT.lower()
EXPECTED_FREEZE_SHA256 = "a8225c15d5b57faebed547002e82658ad3ad7d24827ad247f76efa6c815c8cb4"
EXPECTED_DAILY_SHA256 = {
    "development": "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    "challenge": "95ba886707811da9a0514d1d3a9b2ddf9df5debe69eed4e904502f8f3e1cfca9",
}


class ResearchError(RuntimeError):
    """Fail closed on identity, chronology, lineage, or authorization drift."""


def candidate_query(daily: Path, start: str, end: str) -> str:
    return f"""
    WITH source AS (
      SELECT * FROM read_parquet('{daily.as_posix()}')
      WHERE trade_date <= DATE '{end}'
    ), rolling AS (
      SELECT *,
        avg(turnover_fraction) OVER (
          PARTITION BY symbol ORDER BY cal_idx
          ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS prior20_turnover,
        count(*) OVER (
          PARTITION BY symbol ORDER BY cal_idx
          ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS prior20_count,
        (coord_close-coord_low)/nullif(coord_high-coord_low,0.0) AS close_location_x,
        CASE WHEN volume>0 AND amount>0 AND coordinate_factor>0
          THEN amount/volume*coordinate_factor ELSE NULL END AS coordinate_vwap,
        CASE WHEN
          hard_valid AND history_valid AND current_valid
          AND current_day_data_tradable AND market_rule_valid
          AND corporate_action_valid AND NOT corporate_action_blocking AND NOT is_st
          AND prior20_count=20
          AND coord_close/prior_coord_close-1.0<=-0.03
          AND turnover_fraction>=1.5*prior20_turnover
          AND close_location_x<=0.35
          AND volume>0 AND amount>0 AND coordinate_factor>0
          THEN cal_idx ELSE NULL END AS seller_anchor_idx
      FROM source
    ), located AS (
      SELECT *,
        max(seller_anchor_idx) OVER (
          PARTITION BY symbol ORDER BY cal_idx
          ROWS BETWEEN 20 PRECEDING AND 3 PRECEDING
        ) AS chosen_anchor_idx
      FROM rolling
    ), pre AS (
      SELECT
        s.symbol,s.sleeve,s.causal_industry,
        CAST(s.trade_date AS DATE) AS signal_date,s.cal_idx AS signal_cal_idx,
        s.invalid_step_cum,s.available_at,s.decision_at,
        s.coord_open AS signal_open,s.coord_high AS signal_high,
        s.coord_low AS signal_low,s.coord_close AS signal_close,
        s.turnover_fraction AS signal_turnover,
        s.prior20_turnover AS signal_prior20_turnover,
        s.coord_close/s.prior_coord_close-1.0 AS signal_return,
        s.close_location_x AS signal_close_location,
        s.close,s.up_limit_price,
        CAST(a.trade_date AS DATE) AS anchor_date,a.cal_idx AS anchor_cal_idx,
        a.coord_open AS anchor_open,a.coord_high AS anchor_high,
        a.coord_low AS anchor_low,a.coord_close AS anchor_close,
        a.coordinate_vwap AS anchor_cost,
        a.turnover_fraction AS anchor_turnover,
        a.prior20_turnover AS anchor_prior20_turnover,
        a.coord_close/a.prior_coord_close-1.0 AS anchor_return,
        a.close_location_x AS anchor_close_location
      FROM located s
      JOIN rolling a ON s.symbol=a.symbol AND s.chosen_anchor_idx=a.cal_idx
      WHERE CAST(s.trade_date AS DATE) BETWEEN DATE '{start}' AND DATE '{end}'
        AND s.hard_valid AND s.history_valid AND s.current_valid
        AND s.current_day_data_tradable AND s.market_rule_valid
        AND s.corporate_action_valid AND NOT s.corporate_action_blocking AND NOT s.is_st
        AND s.prior20_count=20
        AND s.invalid_step_cum=a.invalid_step_cum
        AND s.cal_idx-a.cal_idx BETWEEN 3 AND 20
        AND s.coord_low<=a.coordinate_vwap
        AND s.coord_close>=1.005*a.coordinate_vwap
        AND s.coord_close>=a.coord_close
        AND s.coord_close/s.prior_coord_close-1.0>=0.02
        AND s.close_location_x>=0.70
        AND s.turnover_fraction>=s.prior20_turnover
        AND round(s.close*100)<round(s.up_limit_price*100)
    ), path_audit AS (
      SELECT p.*,
        count(m.cal_idx) AS intervening_rows,
        min(CASE WHEN
          m.hard_valid AND m.history_valid AND m.current_valid
          AND m.market_rule_valid AND m.corporate_action_valid
          AND NOT m.corporate_action_blocking
          AND m.invalid_step_cum=p.invalid_step_cum
          THEN 1 ELSE 0 END) AS path_valid,
        max(CASE WHEN m.coord_close>=p.anchor_cost THEN 1 ELSE 0 END) AS prior_reclaim
      FROM pre p
      LEFT JOIN source m ON p.symbol=m.symbol
        AND m.cal_idx>p.anchor_cal_idx AND m.cal_idx<p.signal_cal_idx
      GROUP BY ALL
    )
    SELECT * EXCLUDE(intervening_rows,path_valid,prior_reclaim)
    FROM path_audit
    WHERE intervening_rows=signal_cal_idx-anchor_cal_idx-1
      AND path_valid=1 AND prior_reclaim=0
    ORDER BY symbol,signal_cal_idx
    """


def apply_cooldown(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    work = frame.sort_values(["symbol", "signal_cal_idx"], kind="mergesort").copy()
    keep: list[int] = []
    for _, part in work.groupby("symbol", sort=False):
        last = -10**12
        for index, row in part.iterrows():
            if int(row.signal_cal_idx) - last > 20:
                keep.append(index)
                last = int(row.signal_cal_idx)
    frozen = work.loc[keep].copy()
    frozen["event_id"] = (
        frozen.symbol.astype(str)
        + "|"
        + pd.to_datetime(frozen.signal_date).dt.strftime("%Y-%m-%d")
    )
    frozen = frozen.sort_values(
        ["signal_date", "sleeve", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    if frozen.event_id.duplicated().any():
        raise ResearchError("duplicate event identity")
    return frozen


def build_candidates(daily: Path, start: str, end: str) -> pd.DataFrame:
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='10GB'")
    frame = con.execute(candidate_query(daily, start, end)).fetchdf()
    con.close()
    for column in ("signal_date", "anchor_date", "available_at", "decision_at"):
        frame[column] = pd.to_datetime(frame[column])
    frame = apply_cooldown(frame)
    if not frame.empty and frame.available_at.gt(frame.decision_at).any():
        raise ResearchError("feature availability after decision")
    return frame


def build_paths(daily: Path, candidates: pd.DataFrame, outcome_end: str) -> pd.DataFrame:
    con = duckdb.connect()
    con.register(
        "candidate_ids",
        candidates[
            ["event_id", "symbol", "sleeve", "signal_date", "signal_cal_idx", "invalid_step_cum"]
        ],
    )
    frame = con.execute(
        f"""
        SELECT c.event_id,c.symbol,c.sleeve,c.signal_date,
          c.signal_cal_idx,c.invalid_step_cum AS signal_invalid_step_cum,
          d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,
          d.coordinate_factor,d.invalid_step_cum,d.trade_status,
          d.current_day_data_tradable,d.current_valid,d.market_rule_valid,
          d.corporate_action_count,d.corporate_action_valid,
          d.corporate_action_blocking,d.hard_valid,
          d.up_limit_price,d.down_limit_price
        FROM candidate_ids c
        JOIN read_parquet('{daily.as_posix()}') d
          ON c.symbol=d.symbol AND d.cal_idx>c.signal_cal_idx
        WHERE CAST(d.trade_date AS DATE)<=DATE '{outcome_end}'
          AND d.cal_idx<=c.signal_cal_idx+80
        ORDER BY c.event_id,d.cal_idx
        """
    ).fetchdf()
    con.close()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    return frame


def replay(candidates: pd.DataFrame, paths: pd.DataFrame) -> pd.DataFrame:
    groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    replay_candidates = candidates.assign(cal_idx=candidates.signal_cal_idx)
    rows = [
        execution.replay_one(candidate, groups.get(candidate.event_id, pd.DataFrame()))
        for candidate in replay_candidates.itertuples(index=False)
    ]
    outcomes = pd.DataFrame(rows)
    if outcomes.empty:
        return outcomes
    for column in ("signal_date", "entry_date", "exit_date"):
        if column in outcomes:
            outcomes[column] = pd.to_datetime(outcomes[column])
    complete = outcomes.loc[outcomes.status.eq("COMPLETED")]
    if complete.entry_cal_idx.le(complete.signal_cal_idx).any():
        raise ResearchError("entry at or before signal")
    if complete.exit_cal_idx.le(complete.entry_cal_idx).any():
        raise ResearchError("exit at or before entry")
    return outcomes


def summarize(candidates: pd.DataFrame, outcomes: pd.DataFrame, years: list[int]) -> dict[str, Any]:
    metrics = execution.metrics(outcomes)
    yearly = {
        str(year): execution.metrics(
            outcomes.loc[pd.to_datetime(outcomes.signal_date).dt.year.eq(year)]
        )
        for year in years
    }
    completed_per_year = metrics["completed"] / len(years)
    gates = {
        "completed_trades_per_year_gt_50": completed_per_year > 50,
        "pooled_mean_net_ge_4pct": metrics["mean_net"] is not None
        and metrics["mean_net"] >= 0.04,
        "pooled_mean_holding_lt_15": metrics["mean_holding"] is not None
        and metrics["mean_holding"] < 15,
        "every_year_with_trades_mean_positive": all(
            row["completed"] == 0 or row["mean_net"] > 0 for row in yearly.values()
        ),
    }
    complete = outcomes.loc[outcomes.status.eq("COMPLETED")].copy()
    date_stats = (
        complete.groupby("signal_date", as_index=False)
        .agg(signals=("event_id", "size"), mean_net=("net_return", "mean"))
        if not complete.empty
        else pd.DataFrame()
    )
    return {
        "signals": int(len(candidates)),
        "completed_per_year": completed_per_year,
        "pooled": metrics,
        "yearly": yearly,
        "distinct_signal_dates": int(len(date_stats)),
        "largest_date_share": None
        if date_stats.empty
        else float(date_stats.signals.max() / len(complete)),
        "signal_date_equal_weight_mean_net": None
        if date_stats.empty
        else float(date_stats.mean_net.mean()),
        "gates": gates,
        "all_gates_pass": bool(all(gates.values())),
    }


def verify_inputs(mode: str) -> Path:
    if execution.sha256(FREEZE) != EXPECTED_FREEZE_SHA256:
        raise ResearchError("rule freeze hash drift")
    daily = OLD_DAILY if mode == "development" else CURRENT_DAILY
    if execution.sha256(daily) != EXPECTED_DAILY_SHA256[mode]:
        raise ResearchError(f"{mode} daily input hash drift")
    return daily


def run(mode: str) -> dict[str, Any]:
    daily = verify_inputs(mode)
    if mode == "development":
        start, end, tail, years = "2014-01-01", "2021-12-31", "2023-12-29", list(range(2014, 2022))
    else:
        development_result = OUTPUT_ROOT / "development/result.json"
        if not development_result.is_file():
            raise ResearchError("development result missing; challenge remains closed")
        prior = json.loads(development_result.read_text(encoding="utf-8"))
        if not prior.get("summary", {}).get("all_gates_pass"):
            raise ResearchError("development gate failed; challenge remains closed")
        start, end, tail, years = "2022-01-01", "2025-12-31", "2026-03-31", list(range(2022, 2026))
    output = OUTPUT_ROOT / mode
    candidates = build_candidates(daily, start, end)
    paths = build_paths(daily, candidates, tail)
    outcomes = replay(candidates, paths)
    summary = summarize(candidates, outcomes, years)
    output.mkdir(parents=True, exist_ok=True)
    execution.write_parquet(candidates, output / "candidates.parquet")
    execution.write_parquet(paths, output / "future_paths.parquet")
    execution.write_parquet(outcomes, output / "outcomes.parquet")
    result = {
        "experiment": EXPERIMENT,
        "mode": mode,
        "freeze_sha256": EXPECTED_FREEZE_SHA256,
        "daily_sha256": EXPECTED_DAILY_SHA256[mode],
        "summary": summary,
        "status_counts": outcomes.status.value_counts().sort_index().to_dict(),
        "future_market_function": False,
        "same_bar_fill": False,
        "no_threshold_rescue": True,
    }
    execution.write_json(output / "result.json", result)
    result["output_hashes"] = {
        name: execution.sha256(output / name)
        for name in ("candidates.parquet", "future_paths.parquet", "outcomes.parquet", "result.json")
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("development", "challenge"), required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.mode), ensure_ascii=False, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
