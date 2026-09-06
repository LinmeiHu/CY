#!/usr/bin/env python3
"""Attach fixed chart labels to the frozen circulating-size mother events."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_high_transfer_low_price_displacement_mother_v1_stage_b as execution,
)


EXPERIMENT = "ASHARE-INDUSTRY-NEUTRAL-CIRCULATING-SIZE-EXTREMES-MOTHER-V1"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
STAGE_A_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_industry_neutral_circulating_size_extremes_mother_v1_stage_a.py"
)
EXECUTION_HELPER = Path(execution.__file__)
DAILY = Path("/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/pit_daily_compact_2013_2023.parquet")
OUTPUT_ROOT = Path("/Volumes/quant/CY_quant_research/ashare_industry_neutral_circulating_size_extremes_mother_v1")
STAGE_A_FREEZE = OUTPUT_ROOT / "stage_a/stage_a_freeze.json"
CANDIDATES = OUTPUT_ROOT / "stage_a/candidates_frozen.parquet"
PATHS = OUTPUT_ROOT / "stage_b/future_paths_through_2021h1.parquet"
OUTCOMES = OUTPUT_ROOT / "stage_b/outcome_labels.parquet"
MANIFEST = OUTPUT_ROOT / "stage_b/manifest.json"
EXPECTED_EVENTS = 1975
HORIZONS = (20, 60, 120)
ROUND_TRIP_COST = 0.004
MAXIMUM_CONTEXT_DATE = pd.Timestamp("2021-06-30")
EXPECTED_HASHES = {
    SPEC: "a221169d8ab7295283dfeafe34ec0cead9deb73c3232cfbbbaf74189dea2793d",
    STAGE_A_RUNNER: "30bb78d1af491a6657e675882531aebe165813531c1b55018b44fa1b5951f63b",
    EXECUTION_HELPER: "73a0882b6ff99e736eba6f66566c0df1598e38d11b112aba4e2d098e101cb803",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    STAGE_A_FREEZE: "c64c47171f1b92bcf83b6391ab6342964c108d59da14c728be42b16fd47cd94f",
    CANDIDATES: "5d05b6a0d3bc4b812484d3513cb3f67f60f05982c56fb2930d18c6b892614dfc",
}


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
        value = sha256(path)
        actual[str(path)] = value
        if value != expected:
            raise ResearchError(f"frozen input drift: {path}: {value} != {expected}")
    return actual


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
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
      WHERE d.trade_date<=DATE '2021-06-30'
      ORDER BY c.event_id,d.cal_idx
    """
    con.execute(f"COPY ({query}) TO '{PATHS.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    frame = con.execute(
        f"SELECT * FROM read_parquet('{PATHS.as_posix()}') ORDER BY event_id,cal_idx"
    ).fetch_df()
    con.close()
    for column in ("trade_date", "available_at", "decision_at"):
        frame[column] = pd.to_datetime(frame[column])
    if frame.empty or frame.trade_date.max() > MAXIMUM_CONTEXT_DATE:
        raise ResearchError("future path escaped the frozen context cap")
    return frame


def industry_lookup() -> dict[tuple[str, int], float]:
    con = duckdb.connect()
    frame = con.execute(
        f"""
        SELECT causal_industry,cal_idx,median(step_return) AS median_step_return
        FROM read_parquet('{DAILY.as_posix()}')
        WHERE trade_date<=DATE '2021-06-30'
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


def replay_one(
    candidate: Any,
    path: pd.DataFrame,
    industry_returns: dict[tuple[str, int], float],
) -> dict[str, Any]:
    common = {
        "event_id": str(candidate.event_id),
        "size_lane": str(candidate.size_lane),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "pit_industry": str(candidate.pit_industry),
        "causal_industry": str(candidate.causal_industry),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_cal_idx": int(candidate.signal_cal_idx),
        "circulating_market_value_cny": float(candidate.circulating_market_value_cny),
        "market_regime": str(candidate.market_regime),
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
            if not pd.isna(row.invalid_step_cum)
            and float(row.invalid_step_cum) == lineage
            and execution.buyable(row)
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
    after_entry = path.loc[path.cal_idx.gt(entry_idx)].sort_values("cal_idx", kind="mergesort")
    invalid = after_entry.loc[
        after_entry.invalid_step_cum.isna() | after_entry.invalid_step_cum.ne(lineage)
    ]
    first_invalid_idx = int(invalid.cal_idx.min()) if not invalid.empty else None
    for horizon in HORIZONS:
        target_idx = entry_idx + horizon
        exit_row = next(
            (
                row
                for row in after_entry.loc[after_entry.cal_idx.ge(target_idx)].itertuples(index=False)
                if (first_invalid_idx is None or int(row.cal_idx) < first_invalid_idx)
                and execution.sellable_open(row)
            ),
            None,
        )
        prefix = f"h{horizon}"
        if exit_row is None:
            result[f"{prefix}_status"] = (
                "INVALID_COORDINATE_LINEAGE"
                if first_invalid_idx is not None and first_invalid_idx <= target_idx
                else "INCOMPLETE_PATH"
            )
            continue
        exit_idx = int(exit_row.cal_idx)
        if first_invalid_idx is not None and first_invalid_idx <= exit_idx:
            result[f"{prefix}_status"] = "INVALID_COORDINATE_LINEAGE"
            continue
        held = after_entry.loc[
            after_entry.cal_idx.le(exit_idx)
            & after_entry.invalid_step_cum.eq(lineage)
            & after_entry.coord_high.notna()
            & after_entry.coord_low.notna()
        ]
        ind_values = [
            industry_returns.get((str(candidate.causal_industry), idx), math.nan)
            for idx in range(int(candidate.signal_cal_idx) + 1, int(candidate.signal_cal_idx) + horizon + 1)
        ]
        finite = np.asarray([value for value in ind_values if math.isfinite(value)], dtype=float)
        industry_return = (
            float(np.expm1(np.log1p(finite).sum()))
            if len(finite) >= int(0.8 * horizon)
            else math.nan
        )
        exit_price = float(exit_row.coord_open)
        result.update(
            {
                f"{prefix}_status": "COMPLETED",
                f"{prefix}_exit_date": pd.Timestamp(exit_row.trade_date),
                f"{prefix}_exit_cal_idx": exit_idx,
                f"{prefix}_exit_price": exit_price,
                f"{prefix}_holding_market_sessions": exit_idx - entry_idx,
                f"{prefix}_gross_return": exit_price / entry_price - 1.0,
                f"{prefix}_net_return": exit_price / entry_price - 1.0 - ROUND_TRIP_COST,
                f"{prefix}_mfe": (
                    float(held.coord_high.max() / entry_price - 1.0)
                    if not held.empty
                    else math.nan
                ),
                f"{prefix}_mae": (
                    float(held.coord_low.min() / entry_price - 1.0)
                    if not held.empty
                    else math.nan
                ),
                f"{prefix}_industry_median_compound_from_signal": industry_return,
            }
        )
    if result.get("h120_status") != "COMPLETED":
        result["status"] = str(result.get("h120_status", "INCOMPLETE_PATH"))
    return result


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    candidates = pd.read_parquet(CANDIDATES)
    for column in ("signal_date", "decision_at", "available_at"):
        candidates[column] = pd.to_datetime(candidates[column])
    if len(candidates) != EXPECTED_EVENTS or candidates.event_id.duplicated().any():
        raise ResearchError("candidate identity drift")
    paths = build_paths()
    groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    ind = industry_lookup()
    outcomes = pd.DataFrame(
        [
            replay_one(candidate, groups.get(str(candidate.event_id), pd.DataFrame()), ind)
            for candidate in candidates.itertuples(index=False)
        ]
    ).sort_values(["signal_date", "size_lane", "pit_industry", "symbol"], kind="mergesort")
    if len(outcomes) != EXPECTED_EVENTS or outcomes.event_id.duplicated().any():
        raise ResearchError("outcome identity drift")
    completed = outcomes.loc[outcomes.status.eq("COMPLETED")]
    if completed.empty or completed.entry_date.le(completed.signal_date).any():
        raise ResearchError("entry chronology failure")
    if completed.h120_exit_date.le(completed.entry_date).any():
        raise ResearchError("exit chronology failure")
    execution.write_parquet(outcomes, OUTCOMES)
    payload = {
        "experiment": EXPERIMENT,
        "stage": "FROZEN_CHART_LABEL_ATTACHMENT_NO_RULE_AGGREGATE",
        "source_hashes": source_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "paths_sha256": sha256(PATHS),
        "outcomes_sha256": sha256(OUTCOMES),
        "signals": int(len(outcomes)),
        "status_counts": {str(key): int(value) for key, value in outcomes.status.value_counts().items()},
        "completed_h120_labels": int(len(completed)),
        "annual_or_pooled_return_aggregate_opened": "NO",
        "maximum_signal_date": str(candidates.signal_date.max().date()),
        "maximum_outcome_path_date": str(paths.trade_date.max().date()),
        "2021_signal_identity_read": "NO",
        "2022_2024_signal_feature_or_outcome_read": "NO",
    }
    write_json(MANIFEST, payload)
    payload["manifest_sha256"] = sha256(MANIFEST)
    return payload


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
