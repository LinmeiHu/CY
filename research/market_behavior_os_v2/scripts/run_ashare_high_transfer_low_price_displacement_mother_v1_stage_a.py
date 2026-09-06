#!/usr/bin/env python3
"""Freeze outcome-blind high-transfer/low-price-displacement mother events."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


EXPERIMENT = "ASHARE-HIGH-TRANSFER-LOW-PRICE-DISPLACEMENT-MOTHER-V1"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
DAILY = DATA_ROOT / (
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
REGIME = DATA_ROOT / (
    "ashare_causal_market_regime_routed_simple_strategy_v1/"
    "stage_a/causal_market_regime_2014_2023.parquet"
)
OUTPUT_ROOT = DATA_ROOT / "ashare_high_transfer_low_price_displacement_mother_v1"
CANDIDATES = OUTPUT_ROOT / "stage_a/candidates_frozen.parquet"
FREEZE = OUTPUT_ROOT / "stage_a/stage_a_freeze.json"
EXPECTED_HASHES = {
    SPEC: "b719e13f77109cfd3f46ed1c8bc4ac312e190ef9c75d7e1b6e257dba5cbc4630",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    REGIME: "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
}


class ResearchError(RuntimeError):
    """Fail closed on frozen identity, PIT timing, or lineage drift."""


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


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.register("frame", frame)
    con.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()


def causal_cooldown(raw: pd.DataFrame) -> pd.DataFrame:
    """Keep the first event, then require >20 global market-session indices."""
    kept: list[int] = []
    for _, group in raw.groupby("symbol", sort=False):
        last_admitted: int | None = None
        for row in group.sort_values("signal_cal_idx", kind="mergesort").itertuples():
            current = int(row.signal_cal_idx)
            if last_admitted is None or current - last_admitted > 20:
                kept.append(int(row.Index))
                last_admitted = current
    return raw.loc[kept].sort_values(
        ["signal_date", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)


def build_candidates() -> tuple[pd.DataFrame, int]:
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_ROOT / "duckdb_tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='12GB'")
    con.execute(f"SET temp_directory='{temporary.as_posix()}'")
    raw = con.execute(
        f"""
        WITH eligible AS (
          SELECT
            trade_date,cal_idx,symbol,sleeve,causal_industry,industry_snapshot_id,
            decision_at,available_at,invalid_step_cum,coordinate_factor,
            open,high,low,close,coord_open,coord_high,coord_low,coord_close,
            step_return,ret20,ret60,ret120,amount,volume,turnover_fraction,
            up_limit_price,down_limit_price,
            CASE WHEN coord_high>coord_low
              THEN (coord_close-coord_low)/(coord_high-coord_low)
              ELSE NULL END AS close_location,
            count(turnover_fraction) OVER (
              PARTITION BY symbol,invalid_step_cum ORDER BY cal_idx
              ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING
            ) AS prior60_valid_count,
            median(turnover_fraction) OVER (
              PARTITION BY symbol,invalid_step_cum ORDER BY cal_idx
              ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING
            ) AS prior60_median_turnover
          FROM read_parquet('{DAILY.as_posix()}')
          WHERE trade_date<=DATE '2019-12-31'
            AND sleeve IN ('MAIN','CHINEXT')
            AND NOT is_st
            AND hard_valid AND current_valid AND history_valid
            AND current_day_data_tradable AND market_rule_valid
            AND corporate_action_valid AND NOT corporate_action_blocking
            AND historical_identity_valid
            AND turnover_fraction IS NOT NULL AND turnover_fraction>0
            AND step_return IS NOT NULL
            AND invalid_step_cum IS NOT NULL
        ), raw_event AS (
          SELECT
            concat(symbol,'|',cast(trade_date AS VARCHAR)) AS event_id,
            symbol,sleeve,causal_industry,industry_snapshot_id,
            trade_date AS signal_date,cal_idx AS signal_cal_idx,
            decision_at,available_at,invalid_step_cum,coordinate_factor,
            open,high,low,close,coord_open,coord_high,coord_low,coord_close,
            step_return,ret20,ret60,ret120,amount,volume,turnover_fraction,
            close_location,prior60_valid_count,prior60_median_turnover,
            turnover_fraction/prior60_median_turnover AS turnover_ratio,
            coord_high/coord_low-1 AS intraday_range
          FROM eligible
          WHERE trade_date BETWEEN DATE '2015-01-01' AND DATE '2019-12-31'
            AND prior60_valid_count=60
            AND prior60_median_turnover>0
            AND turnover_fraction>=0.05
            AND turnover_fraction>=3.0*prior60_median_turnover
            AND abs(step_return)<=0.01
        )
        SELECT e.*,
          r.market_regime,r.market_median_ret20,r.market_median_ret60,
          r.market_positive_ret20_share,r.market_positive_ret60_share,
          r.latest_source_timestamp AS market_latest_source_timestamp
        FROM raw_event e
        JOIN read_parquet('{REGIME.as_posix()}') r ON r.trade_date=e.signal_date
        ORDER BY e.symbol,e.signal_cal_idx,e.event_id
        """
    ).fetch_df()
    con.close()
    for column in (
        "signal_date", "decision_at", "available_at", "market_latest_source_timestamp"
    ):
        raw[column] = pd.to_datetime(raw[column])
    frozen = causal_cooldown(raw)
    write_parquet(frozen, CANDIDATES)
    return frozen, int(len(raw))


def audit(frame: pd.DataFrame, raw_count: int) -> dict[str, Any]:
    if frame.empty or frame.event_id.duplicated().any():
        raise ResearchError("empty or duplicate frozen mother identity")
    latest = frame[["available_at", "market_latest_source_timestamp"]].max(axis=1)
    if latest.gt(frame.decision_at).any():
        raise ResearchError("a predictor source arrived after decision_at")
    if frame.signal_date.min() < pd.Timestamp("2015-01-01"):
        raise ResearchError("pre-2015 signal entered Stage A")
    if frame.signal_date.max() > pd.Timestamp("2019-12-31"):
        raise ResearchError("post-2019 signal entered Stage A")
    if not frame.prior60_valid_count.eq(60).all():
        raise ResearchError("strict prior-60 reference drift")
    if frame.turnover_fraction.lt(0.05).any():
        raise ResearchError("absolute float-transfer threshold drift")
    if frame.turnover_ratio.lt(3.0).any():
        raise ResearchError("relative float-transfer threshold drift")
    if frame.step_return.abs().gt(0.01 + 1e-12).any():
        raise ResearchError("low price-displacement threshold drift")
    for _, group in frame.groupby("symbol"):
        gaps = np.diff(group.sort_values("signal_cal_idx").signal_cal_idx.to_numpy())
        if len(gaps) and int(gaps.min()) <= 20:
            raise ResearchError("causal cooldown drift")
    counts = {
        str(int(year)): int(value)
        for year, value in frame.groupby(frame.signal_date.dt.year).size().items()
    }
    return {
        "raw_qualifying_events_before_cooldown": raw_count,
        "frozen_signals": int(len(frame)),
        "symbols": int(frame.symbol.nunique()),
        "signal_dates": int(frame.signal_date.nunique()),
        "annual_counts": counts,
        "minimum_turnover_fraction": float(frame.turnover_fraction.min()),
        "minimum_turnover_ratio": float(frame.turnover_ratio.min()),
        "maximum_absolute_step_return": float(frame.step_return.abs().max()),
        "maximum_signal_date": str(frame.signal_date.max().date()),
        "predictor_after_decision_count": int(latest.gt(frame.decision_at).sum()),
    }


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    frame, raw_count = build_candidates()
    payload = {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_MOTHER_IDENTITY_FREEZE",
        "source_hashes": source_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "candidate_sha256": sha256(CANDIDATES),
        "audit": audit(frame, raw_count),
        "return_or_exit_outcome_read": "NO",
        "2020_2024_signal_feature_or_outcome_read": "NO",
        "future_market_or_event_function": False,
        "next_step": "Attach only frozen chart labels, render every event, then review all charts before rule compression.",
    }
    write_json(FREEZE, payload)
    payload["freeze_sha256"] = sha256(FREEZE)
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
