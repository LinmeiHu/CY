#!/usr/bin/env python3
"""Attach fixed H20 chart labels to the frozen reopening mother events."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


EXPERIMENT = "ASHARE-LONG-SUSPENSION-REOPENING-PRICE-DISCOVERY-MOTHER-V1"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
STAGE_A_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_long_suspension_reopening_price_discovery_mother_v1_stage_a.py"
)
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
DAILY = DATA_ROOT / (
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
OUTPUT_ROOT = DATA_ROOT / "ashare_long_suspension_reopening_price_discovery_mother_v1"
STAGE_A_FREEZE = OUTPUT_ROOT / "stage_a/stage_a_freeze.json"
CANDIDATES = OUTPUT_ROOT / "stage_a/candidates_frozen.parquet"
PATHS = OUTPUT_ROOT / "stage_b/future_paths.parquet"
OUTCOMES = OUTPUT_ROOT / "stage_b/outcomes.parquet"
MANIFEST = OUTPUT_ROOT / "stage_b/manifest.json"
EXPECTED_HASHES = {
    SPEC: "25f9ea72762bb092df739c7ca4bba7bfca2d7d68083f420ee12c0756200d8365",
    STAGE_A_RUNNER: "3183213e9249a48d9c6aed0d291498d8ee890e2e0d9e1cc374f5361ef16ad9cc",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    STAGE_A_FREEZE: "8df2281f1f6f1761043e4e58a390501503d044d32ac0b44e265c9a8b6b33f1b7",
    CANDIDATES: "0f29af9f2b747a9650c9593da15a6f49c82a2a5984ec6d9c2f3da0610ecdae35",
}
ROUND_TRIP_COST = 0.004
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
       AND d.cal_idx<=c.signal_cal_idx+60
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
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    if not frame.empty and frame.trade_date.max() > pd.Timestamp("2021-06-30"):
        raise ResearchError("future path crossed frozen context cap")
    return frame


def legal(row: Any) -> bool:
    required = (
        row.trade_status,
        row.current_day_data_tradable,
        row.current_valid,
        row.market_rule_valid,
        row.corporate_action_count,
        row.corporate_action_valid,
        row.corporate_action_blocking,
        row.hard_valid,
        row.open,
        row.coord_open,
        row.invalid_step_cum,
        row.coordinate_factor,
    )
    return bool(
        not any(pd.isna(value) for value in required)
        and int(row.trade_status) == 1
        and row.current_day_data_tradable
        and row.current_valid
        and row.market_rule_valid
        and int(row.corporate_action_count) == 0
        and row.corporate_action_valid
        and not row.corporate_action_blocking
        and row.hard_valid
        and float(row.open) > 0
        and np.isfinite(float(row.coord_open))
        and float(row.coord_open) > 0
    )


def buyable(row: Any) -> bool:
    return bool(
        legal(row)
        and not pd.isna(row.up_limit_price)
        and np.isfinite(float(row.up_limit_price))
        and round(float(row.open) * 100) < round(float(row.up_limit_price) * 100)
    )


def sellable_open(row: Any) -> bool:
    return bool(
        legal(row)
        and not pd.isna(row.down_limit_price)
        and np.isfinite(float(row.down_limit_price))
        and round(float(row.open) * 100) > round(float(row.down_limit_price) * 100)
    )


def replay_one(candidate: Any, path: pd.DataFrame) -> dict[str, Any]:
    common = {
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "causal_industry": str(candidate.causal_industry),
        "pre_suspension_trade_date": pd.Timestamp(candidate.pre_suspension_trade_date),
        "pre_suspension_close": float(candidate.pre_suspension_close),
        "suspension_market_sessions": int(candidate.suspension_market_sessions),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_cal_idx": int(candidate.signal_cal_idx),
        "reopening_open_return": float(candidate.reopening_open_return),
        "reopening_close_return": float(candidate.reopening_close_return),
        "close_location": float(candidate.close_location)
        if not pd.isna(candidate.close_location)
        else np.nan,
        "market_regime": str(candidate.market_regime),
        "market_median_ret20": float(candidate.market_median_ret20),
        "market_median_ret60": float(candidate.market_median_ret60),
        "market_positive_ret20_share": float(candidate.market_positive_ret20_share),
        "market_positive_ret60_share": float(candidate.market_positive_ret60_share),
        "horizon_sessions": HORIZON,
    }
    lineage = float(candidate.invalid_step_cum)
    if path.empty:
        return {**common, "status": "NO_FUTURE_PATH"}
    entry = None
    entry_pool = path.loc[
        path.cal_idx.gt(candidate.signal_cal_idx)
        & path.cal_idx.le(candidate.signal_cal_idx + 3)
    ]
    for row in entry_pool.itertuples(index=False):
        if pd.isna(row.invalid_step_cum) or float(row.invalid_step_cum) != lineage:
            return {**common, "status": "INVALID_COORDINATE_LINEAGE_BEFORE_ENTRY"}
        if buyable(row):
            entry = row
            break
    if entry is None:
        return {**common, "status": "NO_LEGAL_ENTRY"}
    entry_idx = int(entry.cal_idx)
    entry_price = float(entry.coord_open)
    entry_fields = {
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": entry_idx,
        "entry_price": entry_price,
    }
    exit_row = None
    for row in path.loc[path.cal_idx.gt(entry_idx)].itertuples(index=False):
        if pd.isna(row.invalid_step_cum) or float(row.invalid_step_cum) != lineage:
            return {
                **common,
                **entry_fields,
                "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
            }
        if int(row.cal_idx) >= entry_idx + HORIZON and sellable_open(row):
            exit_row = row
            break
    if exit_row is None:
        return {**common, **entry_fields, "status": "INCOMPLETE_PATH"}
    exit_price = float(exit_row.coord_open)
    gross = exit_price / entry_price - 1
    return {
        **common,
        **entry_fields,
        "status": "COMPLETED",
        "exit_date": pd.Timestamp(exit_row.trade_date),
        "exit_cal_idx": int(exit_row.cal_idx),
        "exit_price": exit_price,
        "exit_reason": "H20_NEXT_LEGAL_OPEN",
        "holding_sessions": int(exit_row.cal_idx) - entry_idx,
        "gross_return": gross,
        "net_return": gross - ROUND_TRIP_COST,
    }


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    candidates = pd.read_parquet(CANDIDATES)
    for column in ("pre_suspension_trade_date", "signal_date"):
        candidates[column] = pd.to_datetime(candidates[column])
    if len(candidates) != 4459 or candidates.event_id.duplicated().any():
        raise ResearchError("candidate identity drift")
    if candidates.signal_date.max() > pd.Timestamp("2020-12-31"):
        raise ResearchError("post-2020 signal entered chart labeling")
    paths = build_paths()
    path_groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    rows = [
        replay_one(candidate, path_groups.get(str(candidate.event_id), pd.DataFrame()))
        for candidate in candidates.itertuples(index=False)
    ]
    outcomes = pd.DataFrame(rows).sort_values(
        ["signal_date", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    if len(outcomes) != 4459 or outcomes.event_id.duplicated().any():
        raise ResearchError("outcome-label identity drift")
    completed = outcomes.loc[outcomes.status.eq("COMPLETED")]
    if completed.entry_date.le(completed.signal_date).any():
        raise ResearchError("entry is not strictly after signal")
    if completed.exit_date.le(completed.entry_date).any():
        raise ResearchError("exit violates T+1")
    write_parquet(outcomes, OUTCOMES)
    payload = {
        "experiment": EXPERIMENT,
        "stage": "FROZEN_H20_CHART_LABEL_ATTACHMENT_NO_RETURN_AGGREGATE",
        "source_hashes": source_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "paths_sha256": sha256(PATHS),
        "outcomes_sha256": sha256(OUTCOMES),
        "events": int(len(outcomes)),
        "status_counts": {
            str(key): int(value) for key, value in outcomes.status.value_counts().items()
        },
        "annual_or_pooled_return_aggregate_opened": "NO",
        "maximum_signal_date": str(candidates.signal_date.max().date()),
        "maximum_outcome_path_date": str(paths.trade_date.max().date()),
        "2022_2024_signal_feature_or_outcome_read": "NO",
        "cy011_read": "NO",
        "next_step": "Render and review every event chart before freezing any directional or market-state rule.",
    }
    write_json(MANIFEST, payload)
    payload["manifest_sha256"] = sha256(MANIFEST)
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
