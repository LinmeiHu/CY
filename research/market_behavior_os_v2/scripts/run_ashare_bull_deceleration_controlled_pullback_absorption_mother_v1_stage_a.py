#!/usr/bin/env python3
"""Freeze outcome-blind bull-deceleration pullback-absorption identities."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


EXPERIMENT = "ASHARE-BULL-DECELERATION-CONTROLLED-PULLBACK-ABSORPTION-MOTHER-V1"
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
OUTPUT_ROOT = DATA_ROOT / "ashare_bull_deceleration_controlled_pullback_absorption_mother_v1"
CANDIDATES = OUTPUT_ROOT / "stage_a/candidates_frozen.parquet"
FREEZE = OUTPUT_ROOT / "stage_a/stage_a_freeze.json"
EXPECTED_HASHES = {
    SPEC: "f24f8921700a19dca81243fe2408ea7fa786c8366c6fa0bba4b3198a222c4af9",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    REGIME: "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
}


class ResearchError(RuntimeError):
    """Fail closed on PIT, lineage, or frozen-input drift."""


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


def build_candidates() -> pd.DataFrame:
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_ROOT / "duckdb_tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='12GB'")
    con.execute(f"SET temp_directory='{temporary.as_posix()}'")
    query = f"""
      WITH base AS (
        SELECT *,
          CASE WHEN coord_high>coord_low
            THEN (coord_close-coord_low)/(coord_high-coord_low)
            ELSE NULL END AS close_location,
          median(turnover_fraction) OVER (
            PARTITION BY symbol ORDER BY cal_idx
            ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
          ) AS prior20_median_turnover,
          max(coord_high) OVER (
            PARTITION BY symbol ORDER BY cal_idx
            ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
          ) AS prior10_high,
          min(coord_low) OVER (
            PARTITION BY symbol ORDER BY cal_idx
            ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
          ) AS prior5_low,
          lag(coord_close,1) OVER (PARTITION BY symbol ORDER BY cal_idx) AS lag1_close,
          lag(ret60,1) OVER (PARTITION BY symbol ORDER BY cal_idx) AS lag1_ret60,
          lag(cal_idx,20) OVER (PARTITION BY symbol ORDER BY cal_idx) AS lag20_symbol_cal_idx,
          lag(invalid_step_cum,20) OVER (
            PARTITION BY symbol ORDER BY cal_idx
          ) AS lag20_invalid_step_cum
        FROM read_parquet('{DAILY.as_posix()}')
        WHERE trade_date<=DATE '2020-12-31'
      ),
      raw AS (
        SELECT
          concat(s.symbol,'|',cast(s.trade_date AS VARCHAR)) AS event_id,
          s.symbol,s.sleeve,s.causal_industry,s.industry_snapshot_id,
          s.trade_date AS signal_date,s.cal_idx AS signal_cal_idx,
          s.decision_at,s.available_at,s.invalid_step_cum,s.coordinate_factor,
          s.open,s.high,s.low,s.close,s.coord_open,s.coord_high,s.coord_low,
          s.coord_close,s.lag1_close,s.step_return,s.ret20,s.ret60,s.lag1_ret60,
          s.amount,s.turnover_fraction,s.prior20_median_turnover,
          s.close_location,s.prior10_high,s.prior5_low,
          s.prior10_high/s.coord_low-1 AS pullback_depth,
          s.coord_low/s.lag1_close-1 AS intraday_excursion,
          s.turnover_fraction/nullif(s.prior20_median_turnover,0) AS turnover_ratio,
          r.market_regime,r.market_median_ret20,r.market_median_ret60,
          r.market_positive_ret20_share,r.market_positive_ret60_share,
          r.latest_source_timestamp AS market_latest_source_timestamp
        FROM base s
        JOIN read_parquet('{REGIME.as_posix()}') r ON r.trade_date=s.trade_date
        WHERE s.trade_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
          AND s.sleeve IN ('MAIN','CHINEXT')
          AND NOT s.is_st
          AND s.hard_valid AND s.history_valid AND s.current_valid
          AND s.current_day_data_tradable AND s.market_rule_valid
          AND s.corporate_action_valid AND NOT s.corporate_action_blocking
          AND s.lag20_symbol_cal_idx IS NOT NULL
          AND s.cal_idx-s.lag20_symbol_cal_idx=20
          AND s.lag20_invalid_step_cum=s.invalid_step_cum
          AND s.lag1_ret60 BETWEEN 0.05 AND 0.60
          AND s.prior10_high/s.coord_low-1 BETWEEN 0.05 AND 0.15
          AND s.coord_low<=s.prior5_low
          AND s.coord_open<s.lag1_close
          AND s.coord_low/s.lag1_close-1<=-0.02
          AND s.coord_close>=s.lag1_close
          AND s.close_location>=0.70
          AND s.turnover_fraction>=s.prior20_median_turnover
          AND round(s.close*100)<round(s.up_limit_price*100)
          AND round(s.close*100)>round(s.down_limit_price*100)
          AND r.market_regime='BULL'
          AND r.market_median_ret20<r.market_median_ret60
      ),
      dedup AS (
        SELECT *,
          lag(signal_cal_idx) OVER (
            PARTITION BY symbol ORDER BY signal_cal_idx
          ) AS previous_raw_signal_cal_idx
        FROM raw
      )
      SELECT * EXCLUDE(previous_raw_signal_cal_idx)
      FROM dedup
      WHERE previous_raw_signal_cal_idx IS NULL
         OR signal_cal_idx-previous_raw_signal_cal_idx>20
      ORDER BY signal_date,symbol,event_id
    """
    con.execute(
        f"COPY ({query}) TO '{CANDIDATES.as_posix()}' "
        "(FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    frame = con.execute(
        f"SELECT * FROM read_parquet('{CANDIDATES.as_posix()}') "
        "ORDER BY signal_date,symbol,event_id"
    ).fetch_df()
    con.close()
    for column in (
        "signal_date", "decision_at", "available_at", "market_latest_source_timestamp"
    ):
        frame[column] = pd.to_datetime(frame[column])
    return frame


def audit(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        raise ResearchError("outcome-blind mother produced no candidates")
    if frame.event_id.duplicated().any():
        raise ResearchError("duplicate frozen event identity")
    latest_source = frame[["available_at", "market_latest_source_timestamp"]].max(axis=1)
    if latest_source.gt(frame.decision_at).any():
        raise ResearchError("a predictor source arrived after decision_at")
    if frame.signal_date.max() > pd.Timestamp("2020-12-31"):
        raise ResearchError("post-2020 signal entered Stage A")
    if frame.market_regime.ne("BULL").any():
        raise ResearchError("non-BULL row entered mother")
    if frame.market_median_ret20.ge(frame.market_median_ret60).any():
        raise ResearchError("non-decelerating market row entered mother")
    if frame.lag1_ret60.lt(0.05).any() or frame.lag1_ret60.gt(0.60).any():
        raise ResearchError("leader-history contract drift")
    if frame.pullback_depth.lt(0.05).any() or frame.pullback_depth.gt(0.15).any():
        raise ResearchError("controlled-pullback contract drift")
    if frame.coord_low.gt(frame.prior5_low).any():
        raise ResearchError("fresh-undercut contract drift")
    if frame.coord_open.ge(frame.lag1_close).any():
        raise ResearchError("down-open contract drift")
    if frame.intraday_excursion.gt(-0.02).any():
        raise ResearchError("intraday-excursion contract drift")
    if frame.coord_close.lt(frame.lag1_close).any() or frame.close_location.lt(0.70).any():
        raise ResearchError("same-session absorption contract drift")
    annual = {
        str(int(year)): int(value)
        for year, value in frame.groupby(frame.signal_date.dt.year).size().items()
    }
    return {
        "signals": int(len(frame)),
        "symbols": int(frame.symbol.nunique()),
        "signal_dates": int(frame.signal_date.nunique()),
        "annual_counts": annual,
        "minimum_annual_count": int(min(annual.values())),
        "maximum_signal_date": str(frame.signal_date.max().date()),
        "predictor_after_decision_count": int(latest_source.gt(frame.decision_at).sum()),
        "minimum_pullback_depth": float(frame.pullback_depth.min()),
        "maximum_pullback_depth": float(frame.pullback_depth.max()),
        "minimum_intraday_excursion": float(frame.intraday_excursion.min()),
    }


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    frame = build_candidates()
    audit_result = audit(frame)
    payload = {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_MOTHER_IDENTITY_FREEZE",
        "source_hashes": source_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "candidate_sha256": sha256(CANDIDATES),
        "audit": audit_result,
        "return_or_exit_outcome_read": "NO",
        "post_2020_signal_read": "NO",
        "2021_2024_signal_feature_or_outcome_read": "NO",
        "future_market_function": False,
        "future_trough_or_recovery_function": False,
        "next_step": (
            "If coverage merits review, attach one frozen +10/H20 label set, render "
            "every chart, and inspect the full chronological book before rules."
        ),
    }
    write_json(FREEZE, payload)
    payload["freeze_sha256"] = sha256(FREEZE)
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
