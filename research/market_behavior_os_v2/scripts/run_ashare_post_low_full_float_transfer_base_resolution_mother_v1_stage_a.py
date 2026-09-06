#!/usr/bin/env python3
"""Freeze outcome-blind post-low full-float-transfer mother events."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


EXPERIMENT = "ASHARE-POST-LOW-FULL-FLOAT-TRANSFER-BASE-RESOLUTION-MOTHER-V1"
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
OUTPUT_ROOT = DATA_ROOT / "ashare_post_low_full_float_transfer_base_resolution_mother_v1"
CANDIDATES = OUTPUT_ROOT / "stage_a/candidates_frozen.parquet"
FREEZE = OUTPUT_ROOT / "stage_a/stage_a_freeze.json"
EXPECTED_HASHES = {
    SPEC: "26d0237a191dda0afb9ef48a440d66315241cb0a80d79069299803987de56f58",
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
      WITH raw AS (
        SELECT *,
          min(coord_low) OVER (
            PARTITION BY symbol ORDER BY cal_idx
            ROWS BETWEEN 120 PRECEDING AND 1 PRECEDING
          ) AS prior120_low,
          max(coord_high) OVER (
            PARTITION BY symbol ORDER BY cal_idx
            ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING
          ) AS prior60_high,
          max(coord_high) OVER (
            PARTITION BY symbol ORDER BY cal_idx
            ROWS BETWEEN CURRENT ROW AND 9 FOLLOWING
          ) AS anchor10_ceiling,
          count(*) OVER (
            PARTITION BY symbol ORDER BY cal_idx
            ROWS BETWEEN CURRENT ROW AND 9 FOLLOWING
          ) AS anchor10_rows,
          max(cal_idx) OVER (
            PARTITION BY symbol ORDER BY cal_idx
            ROWS BETWEEN CURRENT ROW AND 9 FOLLOWING
          ) AS anchor10_last_cal_idx,
          min(CASE WHEN hard_valid AND history_valid AND current_valid
                         AND current_day_data_tradable AND market_rule_valid
                         AND corporate_action_valid AND NOT corporate_action_blocking
                         AND NOT is_st THEN 1 ELSE 0 END) OVER (
            PARTITION BY symbol ORDER BY cal_idx
            ROWS BETWEEN CURRENT ROW AND 9 FOLLOWING
          ) AS anchor10_all_valid,
          min(invalid_step_cum) OVER (
            PARTITION BY symbol ORDER BY cal_idx
            ROWS BETWEEN CURRENT ROW AND 9 FOLLOWING
          ) AS anchor10_min_invalid,
          max(invalid_step_cum) OVER (
            PARTITION BY symbol ORDER BY cal_idx
            ROWS BETWEEN CURRENT ROW AND 9 FOLLOWING
          ) AS anchor10_max_invalid,
          max(available_at) OVER (
            PARTITION BY symbol ORDER BY cal_idx
            ROWS BETWEEN CURRENT ROW AND 9 FOLLOWING
          ) AS anchor10_latest_available_at,
          lag(cal_idx,120) OVER (
            PARTITION BY symbol ORDER BY cal_idx
          ) AS lag120_idx,
          lag(invalid_step_cum,120) OVER (
            PARTITION BY symbol ORDER BY cal_idx
          ) AS lag120_invalid_step_cum,
          sum(turnover_fraction) OVER (
            PARTITION BY symbol ORDER BY cal_idx ROWS UNBOUNDED PRECEDING
          ) AS cumulative_turnover,
          median(turnover_fraction) OVER (
            PARTITION BY symbol ORDER BY cal_idx
            ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
          ) AS prior20_median_turnover,
          lag(coord_close) OVER (
            PARTITION BY symbol ORDER BY cal_idx
          ) AS lag1_close
        FROM read_parquet('{DAILY.as_posix()}')
        WHERE trade_date<=DATE '2020-12-31'
      ),
      marked AS (
        SELECT *,
          CASE WHEN lag120_idx=cal_idx-120
                     AND invalid_step_cum=lag120_invalid_step_cum
                     AND coord_low<prior120_low
                     AND hard_valid AND history_valid AND current_valid
                     AND current_day_data_tradable AND market_rule_valid
                     AND corporate_action_valid AND NOT corporate_action_blocking
                     AND NOT is_st
               THEN cal_idx END AS anchor_flag
        FROM raw
      ),
      carried AS (
        SELECT *,
          max(anchor_flag) OVER (
            PARTITION BY symbol ORDER BY cal_idx
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
          ) AS anchor_idx
        FROM marked
      ),
      anchors AS (
        SELECT
          symbol,cal_idx AS anchor_idx,trade_date AS anchor_date,
          decision_at AS anchor_decision_at,available_at AS anchor_available_at,
          coord_low AS anchor_low,prior60_high AS old_high,
          cumulative_turnover AS anchor_cumulative_turnover,
          invalid_step_cum AS anchor_invalid_step_cum,
          anchor10_ceiling AS base_ceiling,
          anchor10_latest_available_at AS base_latest_available_at
        FROM marked
        WHERE anchor_flag IS NOT NULL
          AND anchor10_rows=10
          AND anchor10_last_cal_idx=cal_idx+9
          AND anchor10_all_valid=1
          AND anchor10_min_invalid=invalid_step_cum
          AND anchor10_max_invalid=invalid_step_cum
      ),
      eligible_crosses AS (
        SELECT
          concat(s.symbol,'|',cast(a.anchor_date AS VARCHAR),'|',cast(s.trade_date AS VARCHAR))
            AS event_id,
          s.symbol,s.sleeve,s.causal_industry,s.industry_snapshot_id,
          a.anchor_date,a.anchor_idx,a.anchor_decision_at,a.anchor_available_at,
          a.anchor_low,a.base_ceiling,a.base_latest_available_at,a.old_high,
          s.trade_date AS signal_date,s.cal_idx AS signal_cal_idx,
          s.decision_at,s.available_at,s.invalid_step_cum,s.coordinate_factor,
          s.open,s.high,s.low,s.close,s.coord_open,s.coord_high,s.coord_low,
          s.coord_close,s.lag1_close,s.step_return,s.ret20,s.ret60,
          s.amount,s.turnover_fraction,s.prior20_median_turnover,
          s.cumulative_turnover-s.turnover_fraction-a.anchor_cumulative_turnover
            AS turnover_before_signal,
          (s.coord_close-s.coord_low)/nullif(s.coord_high-s.coord_low,0)
            AS close_location,
          s.cal_idx-a.anchor_idx AS anchor_age_sessions,
          a.old_high/a.anchor_low-1 AS old_high_over_anchor_low,
          a.old_high/s.coord_close-1 AS target_headroom,
          row_number() OVER (
            PARTITION BY s.symbol,s.anchor_idx ORDER BY s.cal_idx
          ) AS eligible_cross_number
        FROM carried s
        JOIN anchors a USING(symbol,anchor_idx)
        WHERE s.cal_idx BETWEEN a.anchor_idx+10 AND a.anchor_idx+90
          AND s.coord_close>a.base_ceiling
          AND s.lag1_close<=a.base_ceiling
          AND s.coord_close>s.coord_open
          AND (s.coord_close-s.coord_low)/nullif(s.coord_high-s.coord_low,0)>=0.70
          AND s.turnover_fraction>=s.prior20_median_turnover
          AND a.old_high/a.anchor_low-1>=0.20
          AND a.old_high/s.coord_close-1>=0.10
          AND s.invalid_step_cum=a.anchor_invalid_step_cum
          AND s.hard_valid AND s.history_valid AND s.current_valid
          AND s.current_day_data_tradable AND s.market_rule_valid
          AND s.corporate_action_valid AND NOT s.corporate_action_blocking
          AND NOT s.is_st
          AND s.sleeve IN ('MAIN','CHINEXT')
          AND round(s.close*100)<round(s.up_limit_price*100)
      )
      SELECT
        c.*,r.market_regime,r.market_median_ret20,r.market_median_ret60,
        r.market_positive_ret20_share,r.market_positive_ret60_share,
        r.latest_source_timestamp AS market_latest_source_timestamp
      FROM eligible_crosses c
      JOIN read_parquet('{REGIME.as_posix()}') r ON r.trade_date=c.signal_date
      WHERE c.eligible_cross_number=1
        AND c.turnover_before_signal>=1.0
        AND c.signal_date BETWEEN DATE '2015-01-01' AND DATE '2020-12-31'
      ORDER BY c.signal_date,c.symbol,c.event_id
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
        "anchor_date",
        "anchor_decision_at",
        "anchor_available_at",
        "base_latest_available_at",
        "signal_date",
        "decision_at",
        "available_at",
        "market_latest_source_timestamp",
    ):
        frame[column] = pd.to_datetime(frame[column])
    return frame


def audit(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        raise ResearchError("outcome-blind mother produced no candidates")
    if frame.event_id.duplicated().any():
        raise ResearchError("duplicate frozen event identity")
    predictor_latest = frame[
        ["available_at", "base_latest_available_at", "market_latest_source_timestamp"]
    ].max(axis=1)
    if predictor_latest.gt(frame.decision_at).any():
        raise ResearchError("a predictor source arrived after decision_at")
    if frame.signal_date.min() < pd.Timestamp("2015-01-01"):
        raise ResearchError("pre-development signal entered mother")
    if frame.signal_date.max() > pd.Timestamp("2020-12-31"):
        raise ResearchError("post-2020 signal entered mother")
    if frame.market_regime.isna().any():
        raise ResearchError("missing causal market state")
    if frame.turnover_before_signal.lt(1.0).any():
        raise ResearchError("full-float transfer contract drift")
    if frame.anchor_age_sessions.lt(10).any() or frame.anchor_age_sessions.gt(90).any():
        raise ResearchError("anchor-age contract drift")
    if frame.coord_close.le(frame.base_ceiling).any():
        raise ResearchError("base-resolution contract drift")
    if frame.lag1_close.gt(frame.base_ceiling).any():
        raise ResearchError("previous close already above base ceiling")
    if frame.old_high_over_anchor_low.lt(0.20).any():
        raise ResearchError("prior-breakdown opportunity contract drift")
    if frame.target_headroom.lt(0.10).any():
        raise ResearchError("target-headroom contract drift")
    annual_counts = {
        str(int(year)): int(value)
        for year, value in frame.groupby(frame.signal_date.dt.year).size().items()
    }
    expected_years = {str(year) for year in range(2015, 2021)}
    if set(annual_counts) != expected_years:
        raise ResearchError(f"development year coverage drift: {annual_counts}")
    state_counts = {
        str(state): int(value)
        for state, value in frame.groupby("market_regime", sort=True).size().items()
    }
    return {
        "signals": int(len(frame)),
        "symbols": int(frame.symbol.nunique()),
        "signal_dates": int(frame.signal_date.nunique()),
        "annual_counts": annual_counts,
        "minimum_annual_count": int(min(annual_counts.values())),
        "market_state_counts": state_counts,
        "minimum_turnover_before_signal": float(frame.turnover_before_signal.min()),
        "median_turnover_before_signal": float(frame.turnover_before_signal.median()),
        "median_anchor_age_sessions": float(frame.anchor_age_sessions.median()),
        "predictor_after_decision_count": int(predictor_latest.gt(frame.decision_at).sum()),
        "maximum_signal_date": str(frame.signal_date.max().date()),
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
        "cy011_read": "NO",
        "future_market_function": False,
        "future_anchor_or_target_function": False,
        "next_step": (
            "Attach the frozen old-high/H40 label, render every +/-126-session chart, "
            "and review the full chronological book before compressing rules."
        ),
    }
    write_json(FREEZE, payload)
    payload["freeze_sha256"] = sha256(FREEZE)
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
