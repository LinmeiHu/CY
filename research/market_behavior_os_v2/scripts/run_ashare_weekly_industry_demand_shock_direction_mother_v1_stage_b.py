#!/usr/bin/env python3
"""Attach governed development outcomes to frozen industry-shock identities."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


EXPERIMENT = "ASHARE-WEEKLY-INDUSTRY-DEMAND-SHOCK-DIRECTION-MOTHER-V1"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
STAGE_A_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_weekly_industry_demand_shock_direction_mother_v1_stage_a.py"
)
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
DAILY = DATA_ROOT / (
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
OUTPUT_ROOT = DATA_ROOT / "ashare_weekly_industry_demand_shock_direction_mother_v1"
STAGE_A_FREEZE = OUTPUT_ROOT / "stage_a/stage_a_freeze.json"
CANDIDATES = OUTPUT_ROOT / "stage_a/candidates_frozen.parquet"
PATHS = OUTPUT_ROOT / "stage_b/future_paths.parquet"
OUTCOMES = OUTPUT_ROOT / "stage_b/outcomes.parquet"
RESULT = OUTPUT_ROOT / "stage_b/result.json"
EXPECTED_HASHES = {
    SPEC: "a522af6a979572ace20c11e7fce9af05d3431c2ed54f901ea3e23b30c35f3dcb",
    STAGE_A_RUNNER: "eb453b9c1e6becac31b8da2e8fd291ef3f98ef56dc67d47707f24d8c24467362",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    STAGE_A_FREEZE: "6d1d12add87b6713481df8d3d5d6fbc7e0e095674be8f023d35f4f77948d07e4",
    CANDIDATES: "0625b6d01cadca98abf92a6586bdd167189eb52ba25ff3379fba29f036691bd5",
}
ROUND_TRIP_COST = 0.004
TARGET_RETURN = 0.10
HORIZON = 20


class ResearchError(RuntimeError):
    """Fail closed on frozen identity, chronology, or execution drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inputs() -> dict[str, str]:
    actual: dict[str, str] = {}
    for path, expected in EXPECTED_HASHES.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input: {path}")
        actual[str(path)] = sha256(path)
        if actual[str(path)] != expected:
            raise ResearchError(
                f"input identity drift: {path}: {actual[str(path)]} != {expected}"
            )
    return actual


def connection() -> duckdb.DuckDBPyConnection:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_ROOT / "duckdb_tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='10GB'")
    con.execute(f"SET temp_directory='{temporary.as_posix()}'")
    return con


def build_paths() -> pd.DataFrame:
    PATHS.parent.mkdir(parents=True, exist_ok=True)
    con = connection()
    query = f"""
      SELECT c.event_id,d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
        d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.invalid_step_cum,
        d.coordinate_factor,d.trade_status,d.current_day_data_tradable,d.current_valid,
        d.market_rule_valid,d.corporate_action_count,d.corporate_action_valid,
        d.corporate_action_blocking,d.hard_valid,d.up_limit_price,d.down_limit_price,
        d.available_at,d.decision_at
      FROM read_parquet('{CANDIDATES.as_posix()}') c
      JOIN read_parquet('{DAILY.as_posix()}') d
        ON c.symbol=d.symbol AND d.cal_idx>c.signal_cal_idx
       AND d.cal_idx<=c.signal_cal_idx+100
      WHERE d.trade_date<=DATE '2021-06-30'
      ORDER BY c.event_id,d.cal_idx
    """
    con.execute(
        f"COPY ({query}) TO '{PATHS.as_posix()}' "
        "(FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    frame = con.execute(
        f"SELECT * FROM read_parquet('{PATHS.as_posix()}') ORDER BY event_id,cal_idx"
    ).fetch_df()
    con.close()
    for column in ("trade_date", "available_at", "decision_at"):
        frame[column] = pd.to_datetime(frame[column])
    if frame.trade_date.max() > pd.Timestamp("2021-06-30"):
        raise ResearchError("path crossed the frozen maximum date")
    return frame


def legal(row: Any) -> bool:
    required = (
        row.trade_status,
        row.current_day_data_tradable,
        row.current_valid,
        row.market_rule_valid,
        row.corporate_action_valid,
        row.corporate_action_blocking,
        row.hard_valid,
        row.open,
        row.coord_open,
        row.coordinate_factor,
    )
    return bool(
        not any(pd.isna(value) for value in required)
        and int(row.trade_status) == 1
        and row.current_day_data_tradable
        and row.current_valid
        and row.market_rule_valid
        and row.corporate_action_valid
        and not row.corporate_action_blocking
        and int(row.corporate_action_count) == 0
        and row.hard_valid
        and float(row.open) > 0
        and float(row.coord_open) > 0
    )


def buyable(row: Any) -> bool:
    return bool(
        legal(row)
        and np.isfinite(float(row.up_limit_price))
        and round(float(row.open) * 100) < round(float(row.up_limit_price) * 100)
    )


def sellable_open(row: Any) -> bool:
    return bool(
        legal(row)
        and np.isfinite(float(row.down_limit_price))
        and round(float(row.open) * 100) > round(float(row.down_limit_price) * 100)
    )


def replay_one(candidate: Any, path: pd.DataFrame) -> dict[str, Any]:
    common = {
        "event_id": candidate.event_id,
        "direction_lane": candidate.direction_lane,
        "symbol": candidate.symbol,
        "sleeve": candidate.sleeve,
        "causal_industry": candidate.causal_industry,
        "signal_date": candidate.signal_date,
        "signal_cal_idx": int(candidate.signal_cal_idx),
        "target_return": TARGET_RETURN,
        "horizon_sessions": HORIZON,
    }
    lineage = float(candidate.invalid_step_cum)
    entry_pool = path.loc[
        path.cal_idx.gt(candidate.signal_cal_idx)
        & path.cal_idx.le(candidate.signal_cal_idx + 3)
    ]
    entry = next(
        (
            row
            for row in entry_pool.itertuples(index=False)
            if float(row.invalid_step_cum) == lineage and buyable(row)
        ),
        None,
    )
    if entry is None:
        return {**common, "status": "NO_LEGAL_ENTRY"}
    entry_idx = int(entry.cal_idx)
    entry_price = float(entry.coord_open)
    target_price = entry_price * (1 + TARGET_RETURN)
    exit_row = None
    exit_price = math.nan
    exit_reason = None
    for row in path.loc[path.cal_idx.gt(entry_idx)].itertuples(index=False):
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != lineage:
            return {
                **common,
                "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
                "entry_date": pd.Timestamp(entry.trade_date),
                "entry_cal_idx": entry_idx,
                "entry_price": entry_price,
            }
        if (
            legal(row)
            and np.isfinite(float(row.coord_high))
            and float(row.coord_high) >= target_price
        ):
            exit_row = row
            exit_price = target_price
            exit_reason = "TARGET_10"
            break
        if int(row.cal_idx) >= entry_idx + HORIZON and sellable_open(row):
            exit_row = row
            exit_price = float(row.coord_open)
            exit_reason = "H20_TIME_STOP"
            break
    if exit_row is None:
        return {
            **common,
            "status": "INCOMPLETE_PATH",
            "entry_date": pd.Timestamp(entry.trade_date),
            "entry_cal_idx": entry_idx,
            "entry_price": entry_price,
        }
    gross = exit_price / entry_price - 1
    return {
        **common,
        "status": "COMPLETED",
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": entry_idx,
        "entry_price": entry_price,
        "exit_date": pd.Timestamp(exit_row.trade_date),
        "exit_cal_idx": int(exit_row.cal_idx),
        "exit_price": float(exit_price),
        "exit_reason": exit_reason,
        "holding_sessions": int(exit_row.cal_idx) - entry_idx,
        "gross_return": gross,
        "net_return": gross - ROUND_TRIP_COST,
    }


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    completed = frame.loc[frame.status.eq("COMPLETED")]
    values = pd.to_numeric(completed.net_return, errors="coerce")
    return {
        "signals": len(frame),
        "completed": len(completed),
        "signal_dates": int(completed.signal_date.nunique()),
        "symbols": int(completed.symbol.nunique()),
        "mean_net": None if completed.empty else float(values.mean()),
        "median_net": None if completed.empty else float(values.median()),
        "positive_rate": None if completed.empty else float(values.gt(0).mean()),
        "ge_4pct_rate": None if completed.empty else float(values.ge(0.04).mean()),
        "severe10": None if completed.empty else float(values.le(-0.10).mean()),
        "target_hit": None if completed.empty else float(
            completed.exit_reason.eq("TARGET_10").mean()
        ),
        "mean_holding_sessions": None if completed.empty else float(
            completed.holding_sessions.mean()
        ),
    }


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = connection()
    con.register("frame", frame)
    con.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True,default=str)+"\n",
        encoding="utf-8",
    )


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    candidates = pd.read_parquet(CANDIDATES)
    for column in ("signal_date", "decision_at", "available_at"):
        candidates[column] = pd.to_datetime(candidates[column])
    paths = build_paths()
    path_groups = {key: part for key,part in paths.groupby("event_id",sort=False)}
    outcomes = pd.DataFrame([
        replay_one(candidate,path_groups.get(candidate.event_id,pd.DataFrame()))
        for candidate in candidates.itertuples(index=False)
    ])
    for column in ("signal_date", "entry_date", "exit_date"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    if len(outcomes) != len(candidates) or outcomes.event_id.duplicated().any():
        raise ResearchError("outcome identity mismatch")
    completed = outcomes.loc[outcomes.status.eq("COMPLETED")]
    chronology = {
        "entry_at_or_before_signal": int(
            completed.entry_cal_idx.le(completed.signal_cal_idx).sum()
        ),
        "exit_at_or_before_entry": int(
            completed.exit_cal_idx.le(completed.entry_cal_idx).sum()
        ),
        "post_2021_06_exit": int(
            completed.exit_date.gt(pd.Timestamp("2021-06-30")).sum()
        ),
    }
    if any(chronology.values()):
        raise ResearchError(f"chronology audit failed: {chronology}")
    write_parquet(outcomes,OUTCOMES)
    annual = {
        str(year): metrics(outcomes.loc[outcomes.signal_date.dt.year.eq(year)])
        for year in range(2014,2021)
    }
    by_lane = {
        str(name): metrics(part)
        for name,part in outcomes.groupby("direction_lane",sort=True)
    }
    result = {
        "experiment": EXPERIMENT,
        "stage": "FROZEN_IDENTITY_DEVELOPMENT_PATH_ATTACHMENT",
        "source_hashes": source_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "paths_sha256": sha256(PATHS),
        "outcomes_sha256": sha256(OUTCOMES),
        "status_counts": {
            str(key): int(value)
            for key,value in outcomes.status.value_counts(dropna=False).sort_index().items()
        },
        "pooled": metrics(outcomes),
        "annual": annual,
        "by_direction_lane": by_lane,
        "chronology_audit": chronology,
        "maximum_signal_date": str(candidates.signal_date.max().date()),
        "maximum_exit_date": str(completed.exit_date.max().date()),
        "future_market_or_industry_function": False,
        "post_2021_06_signal_or_outcome_read": "NO",
        "2022_2024_signal_or_outcome_read": "NO",
        "next_step": "RENDER_AND_REVIEW_ALL_FROZEN_CANDIDATE_CHARTS_BEFORE_RULE_COMPRESSION",
    }
    write_json(RESULT,result)
    result["result_sha256"] = sha256(RESULT)
    return result


if __name__ == "__main__":
    print(json.dumps(run(),ensure_ascii=False,indent=2,sort_keys=True,default=str))
