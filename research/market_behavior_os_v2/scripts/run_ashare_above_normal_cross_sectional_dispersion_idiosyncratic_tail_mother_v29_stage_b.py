#!/usr/bin/env python3
"""Attach governed development outcomes to frozen V29 candidate identities."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


EXPERIMENT = (
    "ASHARE-ABOVE-NORMAL-CROSS-SECTIONAL-DISPERSION-"
    "IDIOSYNCRATIC-TAIL-MOTHER-V29"
)
REPO = Path(__file__).resolve().parents[3]
PARENT_SPEC = REPO / (
    f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
)
STAGE_B_SPEC = REPO / (
    f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_stage_b_freeze.json"
)
STAGE_A_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_above_normal_cross_sectional_dispersion_"
    "idiosyncratic_tail_mother_v29_stage_a.py"
)
DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_above_normal_cross_sectional_dispersion_"
    "idiosyncratic_tail_mother_v29"
)
STAGE_A_RESULT = OUTPUT_ROOT / "stage_a/stage_a_freeze.json"
CANDIDATES = OUTPUT_ROOT / "stage_a/candidates_frozen.parquet"
PATHS = OUTPUT_ROOT / "stage_b/future_paths.parquet"
OUTCOMES = OUTPUT_ROOT / "stage_b/outcomes.parquet"
RESULT = OUTPUT_ROOT / "stage_b/result.json"
EXPECTED_HASHES = {
    PARENT_SPEC: "c0be8faf50ff4b01efefa914f5631b648df2c79ca91d9a2da437a77326238dc4",
    STAGE_B_SPEC: "daec10613c7fd1289527cd33082217134106ff5a3c7e4c981e2e47f716c77dc6",
    STAGE_A_RUNNER: "c2a6c7c061f1fbca5122a1cab71396e02b85721b9092128a081842b50ded5155",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    STAGE_A_RESULT: "4d4240be667dd9e33a32f7f6d9b14252d177e4650ecc8b3b73e203f0f2455bbe",
    CANDIDATES: "5c5d70e96ae65552bc5f53a008c50fcba34392b252a666f43386b9d1b6bde6ef",
}
ROUND_TRIP_COST = 0.004
MAX_PATH_DATE = pd.Timestamp("2021-06-30")


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
    stage_a = json.loads(STAGE_A_RESULT.read_text(encoding="utf-8"))
    if not stage_a.get("stage_a_gate_passed") or stage_a.get("outcomes_read"):
        raise ResearchError("stage A did not authorize outcome attachment")
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
        d.coord_open,d.coord_high,d.coord_low,d.coord_close,
        d.prior_coord_close,d.step_return,d.turnover_fraction,
        d.invalid_step_cum,d.coordinate_factor,d.trade_status,
        d.current_day_data_tradable,d.current_valid,d.market_rule_valid,
        d.corporate_action_count,d.corporate_action_valid,
        d.corporate_action_blocking,d.hard_valid,
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
        f"SELECT * FROM read_parquet('{PATHS.as_posix()}') "
        "ORDER BY event_id,cal_idx"
    ).fetch_df()
    con.close()
    for column in ("trade_date", "available_at", "decision_at"):
        frame[column] = pd.to_datetime(frame[column])
    if frame.trade_date.max() > MAX_PATH_DATE:
        raise ResearchError("future path crossed the frozen maximum date")
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
        "target_return": 0.10,
        "horizon_sessions": 20,
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
    target_price = entry_price * 1.10
    exit_row = None
    exit_price = math.nan
    exit_reason = None
    for row in path.loc[path.cal_idx.gt(entry_idx)].itertuples(index=False):
        if (
            not np.isfinite(float(row.invalid_step_cum))
            or float(row.invalid_step_cum) != lineage
        ):
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
        if int(row.cal_idx) > entry_idx + 20 and sellable_open(row):
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
    gross_return = exit_price / entry_price - 1
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
        "gross_return": gross_return,
        "net_return": gross_return - ROUND_TRIP_COST,
    }


def write_parquet(con: duckdb.DuckDBPyConnection, frame: pd.DataFrame) -> None:
    con.register("outcomes", frame)
    con.execute(
        f"COPY outcomes TO '{OUTCOMES.as_posix()}' "
        "(FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    con.unregister("outcomes")


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    completed = frame.loc[frame.status.eq("COMPLETED")]
    values = pd.to_numeric(completed.net_return, errors="coerce")
    return {
        "signals": int(len(frame)),
        "completed": int(len(completed)),
        "decision_dates": int(completed.signal_date.nunique()),
        "symbols": int(completed.symbol.nunique()),
        "mean_net": None if completed.empty else float(values.mean()),
        "median_net": None if completed.empty else float(values.median()),
        "positive_rate": None if completed.empty else float(values.gt(0).mean()),
        "ge_4pct_rate": None if completed.empty else float(values.ge(0.04).mean()),
        "severe10": None if completed.empty else float(values.le(-0.10).mean()),
        "target_hit_rate": None
        if completed.empty
        else float(completed.exit_reason.eq("TARGET_10").mean()),
        "mean_holding_sessions": None
        if completed.empty
        else float(completed.holding_sessions.mean()),
    }


def summarize(outcomes: pd.DataFrame, source_hashes: dict[str, str]) -> dict[str, Any]:
    for column in ("signal_date", "entry_date", "exit_date"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    completed = outcomes.loc[outcomes.status.eq("COMPLETED")]
    audit = {
        "rows": int(len(outcomes)),
        "duplicate_events": int(outcomes.event_id.duplicated().sum()),
        "post_2020_signals": int(outcomes.signal_date.dt.year.gt(2020).sum()),
        "post_max_path_exits": int(completed.exit_date.gt(MAX_PATH_DATE).sum()),
        "entry_at_or_before_signal": int(
            completed.entry_cal_idx.le(completed.signal_cal_idx).sum()
        ),
        "same_session_exit": int(
            completed.exit_cal_idx.le(completed.entry_cal_idx).sum()
        ),
        "nonfinite_completed_return": int(
            (~np.isfinite(pd.to_numeric(completed.net_return, errors="coerce"))).sum()
        ),
    }
    if len(outcomes) != 9368 or any(
        value for key, value in audit.items() if key != "rows"
    ):
        raise ResearchError(f"outcome audit failed: {audit}")

    annual: dict[str, Any] = {}
    for year in range(2014, 2021):
        annual[str(year)] = metrics(
            outcomes.loc[outcomes.signal_date.dt.year.eq(year)]
        )
    lanes = {
        lane: metrics(outcomes.loc[outcomes.direction_lane.eq(lane)])
        for lane in ("IDIOSYNCRATIC_UP_SHOCK", "IDIOSYNCRATIC_DOWN_SHOCK")
    }
    status_counts = {
        str(key): int(value)
        for key, value in outcomes.status.value_counts(dropna=False).sort_index().items()
    }
    return {
        "experiment": EXPERIMENT,
        "stage": "DEVELOPMENT_OUTCOME_ATTACHMENT_BEFORE_CHART_REVIEW",
        "source_hashes": source_hashes,
        "future_paths_sha256": sha256(PATHS),
        "outcomes_sha256": sha256(OUTCOMES),
        "audit": audit,
        "status_counts": status_counts,
        "overall": metrics(outcomes),
        "annual": annual,
        "direction_lanes": lanes,
        "post_2020_signal_outcomes_read": False,
        "maximum_evaluation_path_date": str(MAX_PATH_DATE.date()),
        "next_action": "RENDER_AND_REVIEW_ALL_FROZEN_CANDIDATE_CHARTS",
    }


def main() -> None:
    source_hashes = verify_inputs()
    candidates = pd.read_parquet(CANDIDATES)
    for column in ("signal_date", "decision_at", "available_at"):
        candidates[column] = pd.to_datetime(candidates[column])
    if len(candidates) != 9368 or candidates.event_id.duplicated().any():
        raise ResearchError("candidate identity drift")
    paths = build_paths()
    path_lookup = {key: part for key, part in paths.groupby("event_id", sort=False)}
    rows = []
    for candidate in candidates.sort_values(
        ["signal_cal_idx", "direction_lane", "causal_industry", "symbol"],
        kind="mergesort",
    ).itertuples(index=False):
        path = path_lookup.get(candidate.event_id, paths.iloc[0:0])
        rows.append(replay_one(candidate, path))
    outcomes = pd.DataFrame(rows)
    for column in ("entry_date", "exit_date"):
        if column not in outcomes:
            outcomes[column] = pd.NaT
    con = connection()
    write_parquet(con, outcomes)
    con.close()
    result = summarize(outcomes, source_hashes)
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
