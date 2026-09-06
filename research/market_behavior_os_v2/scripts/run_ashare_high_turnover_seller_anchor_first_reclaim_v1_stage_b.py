#!/usr/bin/env python3
"""Attach frozen A67/H20 labels to seller-anchor reclaim identities."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


EXPERIMENT = "ASHARE-HIGH-TURNOVER-SELLER-ANCHOR-FIRST-RECLAIM-V1"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
STAGE_A_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_high_turnover_seller_anchor_first_reclaim_v1_stage_a.py"
)
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
DAILY = DATA_ROOT / (
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
OUTPUT_ROOT = DATA_ROOT / "ashare_high_turnover_seller_anchor_first_reclaim_v1"
STAGE_A_FREEZE = OUTPUT_ROOT / "stage_a/stage_a_freeze.json"
CANDIDATES = OUTPUT_ROOT / "stage_a/candidates_frozen.parquet"
PATHS = OUTPUT_ROOT / "stage_b/future_paths.parquet"
OUTCOMES = OUTPUT_ROOT / "stage_b/outcomes.parquet"
MANIFEST = OUTPUT_ROOT / "stage_b/manifest.json"
EXPECTED_HASHES = {
    SPEC: "5e363f0b58552f6dc017b63481d37d0afe8f6d48357e5eb2a52ac8bc5cefbaca",
    STAGE_A_RUNNER: "8dce9885a8d61f20db8032312ddba5e259ac2cd7199938d297afd2d1fb2ba8bc",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    STAGE_A_FREEZE: "03b139164e0819dc13c4bfb089613ebbefc954f9de0677ae207b521aa36df366",
    CANDIDATES: "b3100747074b5e8c8437b78f7002cbfb53ab066e1dc88918e0f6531f8cc88974",
}
ROUND_TRIP_COST = 0.004
TARGET_FRACTION = 0.67
MINIMUM_NET_TARGET = 0.04
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
        raise ResearchError("future path crossed chart/outcome cap")
    return frame


def legal(row: Any) -> bool:
    required = (
        row.trade_status, row.current_day_data_tradable, row.current_valid,
        row.market_rule_valid, row.corporate_action_valid,
        row.corporate_action_blocking, row.hard_valid, row.open,
        row.coord_open, row.coordinate_factor,
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
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "causal_industry": str(candidate.causal_industry),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_cal_idx": int(candidate.signal_cal_idx),
        "anchor_date": pd.Timestamp(candidate.anchor_date),
        "anchor_cal_idx": int(candidate.anchor_cal_idx),
        "anchor_high": float(candidate.anchor_high),
        "anchor_vwap": float(candidate.anchor_vwap),
        "pre_anchor60_target_high": float(candidate.pre_anchor60_target_high),
        "target_fraction": TARGET_FRACTION,
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
    target_price = entry_price + TARGET_FRACTION * (
        float(candidate.pre_anchor60_target_high) - entry_price
    )
    target_gross_return = target_price / entry_price - 1
    if (
        not math.isfinite(target_price)
        or target_price <= entry_price
        or target_gross_return - ROUND_TRIP_COST < MINIMUM_NET_TARGET
    ):
        return {
            **common,
            "status": "INSUFFICIENT_ENTRY_HEADROOM",
            "entry_date": pd.Timestamp(entry.trade_date),
            "entry_cal_idx": entry_idx,
            "entry_price": entry_price,
            "target_price": target_price,
            "target_gross_return": target_gross_return,
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
                "target_price": target_price,
                "target_gross_return": target_gross_return,
            }
        if legal(row) and np.isfinite(float(row.coord_high)) and float(row.coord_high) >= target_price:
            exit_row = row
            exit_price = target_price
            exit_reason = "A67_PRE_ANCHOR60_TARGET"
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
            "target_price": target_price,
            "target_gross_return": target_gross_return,
        }
    gross = exit_price / entry_price - 1
    return {
        **common,
        "status": "COMPLETED",
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": entry_idx,
        "entry_price": entry_price,
        "target_price": target_price,
        "target_gross_return": target_gross_return,
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
    for column in ("signal_date", "anchor_date", "decision_at", "available_at"):
        candidates[column] = pd.to_datetime(candidates[column])
    if len(candidates) != 655 or candidates.event_id.duplicated().any():
        raise ResearchError("candidate identity drift")
    paths = build_paths()
    path_groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    rows = [
        replay_one(candidate, path_groups.get(str(candidate.event_id), pd.DataFrame()))
        for candidate in candidates.itertuples(index=False)
    ]
    outcomes = pd.DataFrame(rows).sort_values(
        ["signal_date", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    if len(outcomes) != 655 or outcomes.event_id.duplicated().any():
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
        "stage": "FROZEN_TRANSLATION_LABEL_ATTACHMENT_NO_RULE_AGGREGATE",
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
        "next_step": "Render all 655 event charts and review every chronological sheet before freezing rules or aggregating returns.",
    }
    write_json(MANIFEST, payload)
    payload["manifest_sha256"] = sha256(MANIFEST)
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
