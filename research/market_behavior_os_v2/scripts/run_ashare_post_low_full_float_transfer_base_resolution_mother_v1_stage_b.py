#!/usr/bin/env python3
"""Attach frozen old-high/H40 chart labels without rule aggregation."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


EXPERIMENT = "ASHARE-POST-LOW-FULL-FLOAT-TRANSFER-BASE-RESOLUTION-MOTHER-V1"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
STAGE_A_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_post_low_full_float_transfer_base_resolution_mother_v1_stage_a.py"
)
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
DAILY = DATA_ROOT / (
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
OUTPUT_ROOT = DATA_ROOT / "ashare_post_low_full_float_transfer_base_resolution_mother_v1"
STAGE_A_FREEZE = OUTPUT_ROOT / "stage_a/stage_a_freeze.json"
CANDIDATES = OUTPUT_ROOT / "stage_a/candidates_frozen.parquet"
PATHS = OUTPUT_ROOT / "stage_b/future_paths.parquet"
OUTCOMES = OUTPUT_ROOT / "stage_b/outcomes.parquet"
MANIFEST = OUTPUT_ROOT / "stage_b/manifest.json"
EXPECTED_HASHES = {
    SPEC: "26d0237a191dda0afb9ef48a440d66315241cb0a80d79069299803987de56f58",
    STAGE_A_RUNNER: "674463440cae236502133efb1cd36eee28bda8448cb3aaf7d6ddd53d3258caea",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    STAGE_A_FREEZE: "ceb6f2ca84d91d2001ed8baefc29fb80f25ec9a914d97f3ee0c2de370a92e3bb",
    CANDIDATES: "a681269172910f0b1fc05864c4cf8a53889cc3c5e591ceb9a169c102989a4338",
}
ROUND_TRIP_COST = 0.004
HORIZON = 40


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
        d.current_valid,d.market_rule_valid,d.corporate_action_count,
        d.corporate_action_valid,d.corporate_action_blocking,d.hard_valid,
        d.up_limit_price,d.down_limit_price,d.available_at,d.decision_at
      FROM read_parquet('{CANDIDATES.as_posix()}') c
      JOIN read_parquet('{DAILY.as_posix()}') d
        ON c.symbol=d.symbol AND d.cal_idx>c.signal_cal_idx
       AND d.cal_idx<=c.signal_cal_idx+120
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
    if not frame.empty and frame.trade_date.max() > pd.Timestamp("2021-06-30"):
        raise ResearchError("future path crossed chart/outcome cap")
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
    target_price = float(candidate.old_high)
    common = {
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "causal_industry": str(candidate.causal_industry),
        "anchor_date": pd.Timestamp(candidate.anchor_date),
        "anchor_idx": int(candidate.anchor_idx),
        "anchor_low": float(candidate.anchor_low),
        "base_ceiling": float(candidate.base_ceiling),
        "old_high_target": target_price,
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_cal_idx": int(candidate.signal_cal_idx),
        "market_regime": str(candidate.market_regime),
        "turnover_before_signal": float(candidate.turnover_before_signal),
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
    if entry_price >= target_price:
        return {
            **common,
            "status": "TARGET_REACHED_BEFORE_ENTRY",
            "entry_date": pd.Timestamp(entry.trade_date),
            "entry_cal_idx": entry_idx,
            "entry_price": entry_price,
        }
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
        if sellable_open(row) and float(row.coord_open) >= target_price:
            exit_row = row
            exit_price = float(row.coord_open)
            exit_reason = "OLD_HIGH_TARGET_GAP_OPEN"
            break
        if legal(row) and np.isfinite(float(row.coord_high)) and float(row.coord_high) >= target_price:
            exit_row = row
            exit_price = target_price
            exit_reason = "OLD_HIGH_TARGET_INTRADAY"
            break
        if int(row.cal_idx) >= entry_idx + HORIZON and sellable_open(row):
            exit_row = row
            exit_price = float(row.coord_open)
            exit_reason = "H40_TIME_STOP"
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


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    candidates = pd.read_parquet(CANDIDATES)
    for column in (
        "anchor_date",
        "signal_date",
        "decision_at",
        "available_at",
        "market_latest_source_timestamp",
    ):
        candidates[column] = pd.to_datetime(candidates[column])
    if len(candidates) != 910 or candidates.event_id.duplicated().any():
        raise ResearchError("candidate identity drift")
    if candidates.signal_date.max() > pd.Timestamp("2020-12-31"):
        raise ResearchError("post-2020 signal entered Stage B")
    paths = build_paths()
    path_groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    rows = [
        replay_one(candidate, path_groups.get(str(candidate.event_id), pd.DataFrame()))
        for candidate in candidates.itertuples(index=False)
    ]
    outcomes = pd.DataFrame(rows).sort_values(
        ["signal_date", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    if len(outcomes) != 910 or outcomes.event_id.duplicated().any():
        raise ResearchError("outcome-label identity drift")
    completed = outcomes.loc[outcomes.status.eq("COMPLETED")]
    if completed.empty:
        raise ResearchError("no completed labels")
    if completed.entry_date.le(completed.signal_date).any():
        raise ResearchError("entry is not strictly after signal")
    if completed.exit_date.le(completed.entry_date).any():
        raise ResearchError("exit violates T+1 ordering")
    write_parquet(outcomes, OUTCOMES)
    payload = {
        "experiment": EXPERIMENT,
        "stage": "FROZEN_OLD_HIGH_H40_LABEL_ATTACHMENT_NO_RULE_AGGREGATE",
        "source_hashes": source_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "paths_sha256": sha256(PATHS),
        "outcomes_sha256": sha256(OUTCOMES),
        "signals": int(len(outcomes)),
        "status_counts": {
            str(key): int(value) for key, value in outcomes.status.value_counts().items()
        },
        "completed_labels": int(len(completed)),
        "annual_or_pooled_return_aggregate_opened": "NO",
        "maximum_signal_date": str(candidates.signal_date.max().date()),
        "maximum_outcome_path_date": str(paths.trade_date.max().date()),
        "2022_2024_signal_feature_or_outcome_read": "NO",
        "cy011_read": "NO",
        "next_step": (
            "Render all 910 event charts and review every chronological sheet "
            "before freezing rules or aggregating returns."
        ),
    }
    write_json(MANIFEST, payload)
    payload["manifest_sha256"] = sha256(MANIFEST)
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
