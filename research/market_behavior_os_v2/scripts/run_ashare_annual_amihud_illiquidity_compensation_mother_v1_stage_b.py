#!/usr/bin/env python3
"""Attach frozen H120 chart labels to annual Amihud mother candidates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


EXPERIMENT = "ASHARE-ANNUAL-AMIHUD-ILLIQUIDITY-COMPENSATION-MOTHER-V1"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
STAGE_A_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_annual_amihud_illiquidity_compensation_mother_v1_stage_a.py"
)
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
DAILY = DATA_ROOT / (
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
OUTPUT_ROOT = DATA_ROOT / "ashare_annual_amihud_illiquidity_compensation_mother_v1"
STAGE_A_FREEZE = OUTPUT_ROOT / "stage_a/stage_a_freeze.json"
CANDIDATES = OUTPUT_ROOT / "stage_a/candidates_frozen.parquet"
PATHS = OUTPUT_ROOT / "stage_b/future_paths.parquet"
OUTCOMES = OUTPUT_ROOT / "stage_b/outcomes.parquet"
MANIFEST = OUTPUT_ROOT / "stage_b/manifest.json"
EXPECTED_HASHES = {
    SPEC: "91acf13d0cb0dd1995ed119ca65eba59f1e652b90ab93eaa5328eb47cb13969d",
    STAGE_A_RUNNER: "7e8b78b8a0b19a6eaa91fa900b2dd655cbe525f201668826abf9619bedd6a617",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    STAGE_A_FREEZE: "a41649bbe985b075b9e76e485b84b736408596de6ffa79102a394ebeba028a5c",
    CANDIDATES: "575f0b7ebd22947b9b61729f91ef7182d492c2261c713bb1681c76aebe8e457e",
}
ROUND_TRIP_COST = 0.004
HORIZON = 120
EXPECTED_CANDIDATES = 2286


class ResearchError(RuntimeError):
    """Fail closed on frozen identity, chronology, or execution semantics."""


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
                f"frozen input drift: {path}: {actual[str(path)]} != {expected}"
            )
    return actual


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.register("frame", frame)
    con.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )


def build_paths() -> pd.DataFrame:
    PATHS.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_ROOT / "duckdb_tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='10GB'")
    con.execute(f"SET temp_directory='{temporary.as_posix()}'")
    query = f"""
      SELECT c.event_id,d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
        d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.invalid_step_cum,
        d.coordinate_factor,d.trade_status,d.current_day_data_tradable,
        d.current_valid,d.history_valid,d.market_rule_valid,
        d.corporate_action_count,d.corporate_action_valid,
        d.corporate_action_blocking,d.hard_valid,d.up_limit_price,
        d.down_limit_price,d.available_at,d.decision_at
      FROM read_parquet('{CANDIDATES.as_posix()}') c
      JOIN read_parquet('{DAILY.as_posix()}') d
        ON c.symbol=d.symbol AND d.cal_idx>c.signal_cal_idx
       AND d.cal_idx<=c.signal_cal_idx+180
      WHERE d.trade_date<=DATE '2021-09-30'
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
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    if not frame.empty and frame.trade_date.max() > pd.Timestamp("2021-09-30"):
        raise ResearchError("future path crossed frozen context cap")
    return frame


def legal(row: Any) -> bool:
    required = (
        row.trade_status,row.current_day_data_tradable,row.current_valid,
        row.history_valid,row.market_rule_valid,row.corporate_action_count,
        row.corporate_action_valid,row.corporate_action_blocking,row.hard_valid,
        row.open,row.coord_open,row.invalid_step_cum,row.coordinate_factor,
    )
    return bool(
        not any(pd.isna(value) for value in required)
        and int(row.trade_status)==1
        and bool(row.current_day_data_tradable)
        and bool(row.current_valid) and bool(row.history_valid)
        and bool(row.market_rule_valid)
        and int(row.corporate_action_count)==0
        and bool(row.corporate_action_valid)
        and not bool(row.corporate_action_blocking)
        and bool(row.hard_valid)
        and float(row.open)>0 and np.isfinite(float(row.coord_open))
        and float(row.coord_open)>0
    )


def buyable(row: Any) -> bool:
    return bool(
        legal(row) and not pd.isna(row.up_limit_price)
        and np.isfinite(float(row.up_limit_price))
        and round(float(row.open)*100)<round(float(row.up_limit_price)*100)
    )


def sellable(row: Any) -> bool:
    return bool(
        legal(row) and not pd.isna(row.down_limit_price)
        and np.isfinite(float(row.down_limit_price))
        and round(float(row.open)*100)>round(float(row.down_limit_price)*100)
    )


def replay_one(candidate: Any, path: pd.DataFrame) -> dict[str, Any]:
    common = {
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "causal_industry": str(candidate.causal_industry),
        "portfolio_year": int(candidate.portfolio_year),
        "formation_year": int(candidate.formation_year),
        "valid_daily_observations": int(candidate.valid_daily_observations),
        "annual_amihud": float(candidate.annual_amihud),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_cal_idx": int(candidate.signal_cal_idx),
        "market_regime": str(candidate.market_regime),
        "market_median_ret20": float(candidate.market_median_ret20),
        "market_median_ret60": float(candidate.market_median_ret60),
        "horizon_sessions": HORIZON,
    }
    lineage = float(candidate.invalid_step_cum)
    if path.empty:
        return {**common,"status": "NO_FUTURE_PATH"}
    entry = None
    for row in path.loc[
        path.cal_idx.gt(int(candidate.signal_cal_idx))
        & path.cal_idx.le(int(candidate.signal_cal_idx)+3)
    ].itertuples(index=False):
        if pd.isna(row.invalid_step_cum) or float(row.invalid_step_cum)!=lineage:
            return {**common,"status": "INVALID_COORDINATE_LINEAGE_BEFORE_ENTRY"}
        if buyable(row):
            entry = row
            break
    if entry is None:
        return {**common,"status": "NO_LEGAL_ENTRY"}
    entry_fields = {
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": int(entry.cal_idx),
        "entry_price": float(entry.coord_open),
    }
    exit_row = None
    for row in path.loc[path.cal_idx.gt(int(entry.cal_idx))].itertuples(index=False):
        if pd.isna(row.invalid_step_cum) or float(row.invalid_step_cum)!=lineage:
            return {
                **common,**entry_fields,
                "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
            }
        if int(row.cal_idx)>=int(entry.cal_idx)+HORIZON and sellable(row):
            exit_row = row
            break
    if exit_row is None:
        return {**common,**entry_fields,"status": "INCOMPLETE_PATH"}
    gross = float(exit_row.coord_open)/float(entry.coord_open)-1
    return {
        **common,**entry_fields,"status": "COMPLETED",
        "exit_date": pd.Timestamp(exit_row.trade_date),
        "exit_cal_idx": int(exit_row.cal_idx),
        "exit_price": float(exit_row.coord_open),
        "exit_reason": "H120_NEXT_LEGAL_OPEN",
        "holding_sessions": int(exit_row.cal_idx)-int(entry.cal_idx),
        "gross_return": gross,"net_return": gross-ROUND_TRIP_COST,
    }


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    candidates = pd.read_parquet(CANDIDATES)
    candidates["signal_date"] = pd.to_datetime(candidates.signal_date)
    if len(candidates)!=EXPECTED_CANDIDATES or candidates.event_id.duplicated().any():
        raise ResearchError("candidate identity drift")
    if candidates.portfolio_year.max()>2020:
        raise ResearchError("post-2020 portfolio year entered labeling")
    paths = build_paths()
    groups = {key: part for key,part in paths.groupby("event_id",sort=False)}
    outcomes = pd.DataFrame([
        replay_one(candidate,groups.get(str(candidate.event_id),pd.DataFrame()))
        for candidate in candidates.itertuples(index=False)
    ]).sort_values(["portfolio_year","symbol","event_id"],kind="mergesort")
    if len(outcomes)!=EXPECTED_CANDIDATES or outcomes.event_id.duplicated().any():
        raise ResearchError("outcome-label identity drift")
    completed = outcomes.loc[outcomes.status.eq("COMPLETED")]
    if completed.entry_date.le(completed.signal_date).any():
        raise ResearchError("entry is not strictly after signal")
    if completed.exit_date.le(completed.entry_date).any():
        raise ResearchError("exit violates T+1")
    write_parquet(outcomes,OUTCOMES)
    payload = {
        "experiment": EXPERIMENT,
        "stage": "FROZEN_H120_CHART_LABEL_ATTACHMENT_NO_RETURN_AGGREGATE",
        "source_hashes": source_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "paths_sha256": sha256(PATHS),
        "outcomes_sha256": sha256(OUTCOMES),
        "events": int(len(outcomes)),
        "status_counts": {
            str(key): int(value) for key,value in outcomes.status.value_counts().items()
        },
        "annual_or_pooled_return_aggregate_opened": "NO",
        "maximum_signal_date": str(candidates.signal_date.max().date()),
        "maximum_outcome_path_date": str(paths.trade_date.max().date()),
        "2022_2024_signal_feature_or_outcome_read": "NO",
        "cy011_read": "NO",
        "next_step": "Render and review every event chart before freezing rules.",
    }
    write_json(MANIFEST,payload)
    payload["manifest_sha256"] = sha256(MANIFEST)
    return payload


if __name__ == "__main__":
    print(json.dumps(run(),ensure_ascii=False,indent=2))
