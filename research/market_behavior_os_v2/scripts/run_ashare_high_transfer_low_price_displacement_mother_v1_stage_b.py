#!/usr/bin/env python3
"""Attach frozen observation labels to high-transfer/low-displacement events."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


EXPERIMENT = "ASHARE-HIGH-TRANSFER-LOW-PRICE-DISPLACEMENT-MOTHER-V1"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
STAGE_A_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_high_transfer_low_price_displacement_mother_v1_stage_a.py"
)
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
DAILY = DATA_ROOT / (
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
OUTPUT_ROOT = DATA_ROOT / "ashare_high_transfer_low_price_displacement_mother_v1"
STAGE_A_FREEZE = OUTPUT_ROOT / "stage_a/stage_a_freeze.json"
CANDIDATES = OUTPUT_ROOT / "stage_a/candidates_frozen.parquet"
PATHS = OUTPUT_ROOT / "stage_b/future_paths_through_2020.parquet"
OUTCOMES = OUTPUT_ROOT / "stage_b/outcome_labels.parquet"
MANIFEST = OUTPUT_ROOT / "stage_b/manifest.json"
EXPECTED_EVENTS = 6115
EXPECTED_HASHES = {
    SPEC: "b719e13f77109cfd3f46ed1c8bc4ac312e190ef9c75d7e1b6e257dba5cbc4630",
    STAGE_A_RUNNER: "aefd4930049f14aae3cc5a35f09251a80bc08fee86b5459d8691dcccd6a37027",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    STAGE_A_FREEZE: "3727217e6af92323efc8dc43ea1f2343fe81e7ccc13c6084c4e1ab4fa6bad8fc",
    CANDIDATES: "c2c2a61393563c7aa78fa06d2562df6f1fe6e8bd957b54ca6d97c03630aa0295",
}
HORIZONS = (5, 20, 60, 120)
ROUND_TRIP_COST = 0.004


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
    con.execute("SET memory_limit='12GB'")
    con.execute(f"SET temp_directory='{temporary.as_posix()}'")
    query = f"""
      SELECT c.event_id,d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
        d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.step_return,
        d.invalid_step_cum,d.coordinate_factor,d.trade_status,
        d.current_day_data_tradable,d.current_valid,d.market_rule_valid,
        d.corporate_action_count,d.corporate_action_valid,
        d.corporate_action_blocking,d.hard_valid,
        d.up_limit_price,d.down_limit_price,d.available_at,d.decision_at
      FROM read_parquet('{CANDIDATES.as_posix()}') c
      JOIN read_parquet('{DAILY.as_posix()}') d
        ON c.symbol=d.symbol AND d.cal_idx>c.signal_cal_idx
      WHERE d.trade_date<=DATE '2020-12-31'
      ORDER BY c.event_id,d.cal_idx
    """
    con.execute(
        f"COPY ({query}) TO '{PATHS.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    frame = con.execute(
        f"SELECT * FROM read_parquet('{PATHS.as_posix()}') ORDER BY event_id,cal_idx"
    ).fetch_df()
    con.close()
    for column in ("trade_date", "available_at", "decision_at"):
        frame[column] = pd.to_datetime(frame[column])
    if frame.trade_date.max() > pd.Timestamp("2020-12-31"):
        raise ResearchError("future path crossed the frozen outcome cap")
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


def industry_compound(
    lookup: dict[tuple[str, int], float], industry: str, start_idx: int, horizon: int
) -> float:
    values = [
        lookup.get((industry, idx), math.nan)
        for idx in range(start_idx + 1, start_idx + horizon + 1)
    ]
    finite = np.asarray([value for value in values if math.isfinite(value)], dtype=float)
    if len(finite) < max(1, int(0.8 * horizon)):
        return math.nan
    return float(np.expm1(np.log1p(finite).sum()))


def replay_one(
    candidate: Any,
    path: pd.DataFrame,
    industry_lookup: dict[tuple[str, int], float],
) -> dict[str, Any]:
    common: dict[str, Any] = {
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "causal_industry": str(candidate.causal_industry),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_cal_idx": int(candidate.signal_cal_idx),
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
    result: dict[str, Any] = {
        **common,
        "status": "COMPLETED",
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": entry_idx,
        "entry_price": entry_price,
    }
    after_entry = path.loc[path.cal_idx.gt(entry_idx)].sort_values(
        "cal_idx", kind="mergesort"
    )
    if after_entry.empty:
        result["status"] = "INCOMPLETE_PATH"
        return result
    invalid = after_entry.loc[
        after_entry.invalid_step_cum.isna()
        | after_entry.invalid_step_cum.ne(lineage)
    ]
    first_invalid_idx = int(invalid.cal_idx.min()) if not invalid.empty else None
    for horizon in HORIZONS:
        target_idx = entry_idx + horizon
        candidates = after_entry.loc[after_entry.cal_idx.ge(target_idx)]
        exit_row = next(
            (
                row
                for row in candidates.itertuples(index=False)
                if (first_invalid_idx is None or int(row.cal_idx) < first_invalid_idx)
                and sellable_open(row)
            ),
            None,
        )
        suffix = f"h{horizon}"
        if exit_row is None:
            result[f"{suffix}_status"] = (
                "INVALID_COORDINATE_LINEAGE"
                if first_invalid_idx is not None and first_invalid_idx <= target_idx
                else "INCOMPLETE_PATH"
            )
            continue
        exit_idx = int(exit_row.cal_idx)
        if first_invalid_idx is not None and first_invalid_idx <= exit_idx:
            result[f"{suffix}_status"] = "INVALID_COORDINATE_LINEAGE"
            continue
        exit_price = float(exit_row.coord_open)
        held = after_entry.loc[
            after_entry.cal_idx.le(exit_idx)
            & after_entry.invalid_step_cum.eq(lineage)
            & after_entry.coord_high.notna()
            & after_entry.coord_low.notna()
        ]
        result.update(
            {
                f"{suffix}_status": "COMPLETED",
                f"{suffix}_exit_date": pd.Timestamp(exit_row.trade_date),
                f"{suffix}_exit_cal_idx": exit_idx,
                f"{suffix}_exit_price": exit_price,
                f"{suffix}_holding_market_sessions": exit_idx - entry_idx,
                f"{suffix}_gross_return": exit_price / entry_price - 1,
                f"{suffix}_net_return": exit_price / entry_price - 1 - ROUND_TRIP_COST,
                f"{suffix}_mfe": (
                    float(held.coord_high.max() / entry_price - 1)
                    if not held.empty else math.nan
                ),
                f"{suffix}_mae": (
                    float(held.coord_low.min() / entry_price - 1)
                    if not held.empty else math.nan
                ),
                f"{suffix}_industry_median_compound_from_signal": industry_compound(
                    industry_lookup,
                    str(candidate.causal_industry),
                    int(candidate.signal_cal_idx),
                    horizon,
                ),
            }
        )
    if result.get("h120_status") != "COMPLETED":
        result["status"] = str(result.get("h120_status", "INCOMPLETE_PATH"))
    return result


def build_industry_lookup() -> dict[tuple[str, int], float]:
    con = duckdb.connect()
    frame = con.execute(
        f"""
        SELECT causal_industry,cal_idx,median(step_return) AS median_step_return
        FROM read_parquet('{DAILY.as_posix()}')
        WHERE trade_date<=DATE '2020-12-31'
          AND sleeve IN ('MAIN','CHINEXT') AND NOT is_st
          AND hard_valid AND current_valid AND current_day_data_tradable
          AND market_rule_valid AND corporate_action_valid
          AND NOT corporate_action_blocking AND historical_identity_valid
          AND causal_industry IS NOT NULL AND step_return IS NOT NULL
        GROUP BY causal_industry,cal_idx
        """
    ).fetch_df()
    con.close()
    return {
        (str(row.causal_industry), int(row.cal_idx)): float(row.median_step_return)
        for row in frame.itertuples(index=False)
        if np.isfinite(float(row.median_step_return))
    }


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    candidates = pd.read_parquet(CANDIDATES)
    for column in ("signal_date", "decision_at", "available_at"):
        candidates[column] = pd.to_datetime(candidates[column])
    if len(candidates) != EXPECTED_EVENTS or candidates.event_id.duplicated().any():
        raise ResearchError("candidate identity drift")
    paths = build_paths()
    path_groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    industry_lookup = build_industry_lookup()
    rows = [
        replay_one(
            candidate,
            path_groups.get(str(candidate.event_id), pd.DataFrame()),
            industry_lookup,
        )
        for candidate in candidates.itertuples(index=False)
    ]
    outcomes = pd.DataFrame(rows).sort_values(
        ["signal_date", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    if len(outcomes) != EXPECTED_EVENTS or outcomes.event_id.duplicated().any():
        raise ResearchError("outcome-label identity drift")
    completed = outcomes.loc[outcomes.status.eq("COMPLETED")]
    if completed.empty:
        raise ResearchError("no completed chart labels")
    if completed.entry_date.le(completed.signal_date).any():
        raise ResearchError("entry is not strictly after signal")
    if completed.h120_exit_date.le(completed.entry_date).any():
        raise ResearchError("H120 exit violates T+1 ordering")
    write_parquet(outcomes, OUTCOMES)
    payload = {
        "experiment": EXPERIMENT,
        "stage": "FROZEN_CHART_LABEL_ATTACHMENT_NO_RULE_AGGREGATE",
        "source_hashes": source_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "paths_sha256": sha256(PATHS),
        "outcomes_sha256": sha256(OUTCOMES),
        "signals": int(len(outcomes)),
        "status_counts": {
            str(key): int(value) for key, value in outcomes.status.value_counts().items()
        },
        "completed_h120_labels": int(len(completed)),
        "annual_or_pooled_return_aggregate_opened": "NO",
        "maximum_signal_date": str(candidates.signal_date.max().date()),
        "maximum_outcome_path_date": str(paths.trade_date.max().date()),
        "2021_2024_signal_feature_or_outcome_read": "NO",
        "next_step": "Render all event charts and review every chronological sheet before freezing rules or aggregating returns.",
    }
    write_json(MANIFEST, payload)
    payload["manifest_sha256"] = sha256(MANIFEST)
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
