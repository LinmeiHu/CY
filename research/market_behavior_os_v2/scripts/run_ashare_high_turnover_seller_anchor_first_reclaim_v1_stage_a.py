#!/usr/bin/env python3
"""Freeze the outcome-blind high-turnover seller-anchor reclaim identities."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


EXPERIMENT = "ASHARE-HIGH-TURNOVER-SELLER-ANCHOR-FIRST-RECLAIM-V1"
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
OUTPUT_ROOT = DATA_ROOT / "ashare_high_turnover_seller_anchor_first_reclaim_v1"
CANDIDATES = OUTPUT_ROOT / "stage_a/candidates_frozen.parquet"
FREEZE = OUTPUT_ROOT / "stage_a/stage_a_freeze.json"
EXPECTED_HASHES = {
    SPEC: "5e363f0b58552f6dc017b63481d37d0afe8f6d48357e5eb2a52ac8bc5cefbaca",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    REGIME: "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
}
EXPECTED_COUNTS = {2014: 73, 2015: 68, 2016: 55, 2017: 64, 2018: 140, 2019: 133, 2020: 122}


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
          ) AS prior20_median_turnover
        FROM read_parquet('{DAILY.as_posix()}')
        WHERE trade_date<=DATE '2020-12-31'
      ),
      potential AS (
        SELECT * FROM base s
        WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
          AND sleeve IN ('MAIN','CHINEXT')
          AND NOT is_st
          AND hard_valid AND current_valid AND current_day_data_tradable
          AND market_rule_valid AND corporate_action_valid
          AND NOT corporate_action_blocking
          AND step_return>=0.03
          AND close_location>=0.70
          AND turnover_fraction>=1.50*prior20_median_turnover
          AND round(close*100)<round(up_limit_price*100)
      ),
      ranked AS (
        SELECT
          s.symbol,s.sleeve,s.causal_industry,s.industry_snapshot_id,
          s.trade_date AS signal_date,s.cal_idx AS signal_cal_idx,
          s.decision_at,s.available_at,s.invalid_step_cum,s.coordinate_factor,
          s.open,s.high,s.low,s.close,s.coord_open,s.coord_high,s.coord_low,
          s.coord_close,s.step_return,s.ret20,s.ret60,s.amount,
          s.turnover_fraction,s.close_location,
          s.turnover_fraction/s.prior20_median_turnover AS signal_turnover_ratio,
          a.trade_date AS anchor_date,a.cal_idx AS anchor_cal_idx,
          a.decision_at AS anchor_decision_at,a.available_at AS anchor_available_at,
          a.coord_open AS anchor_open,a.coord_high AS anchor_high,
          a.coord_low AS anchor_low,a.coord_close AS anchor_close,
          a.step_return AS anchor_return,a.close_location AS anchor_close_location,
          a.turnover_fraction AS anchor_turnover_fraction,
          (a.amount/nullif(a.volume,0))*a.coordinate_factor AS anchor_vwap,
          row_number() OVER (
            PARTITION BY s.symbol,s.cal_idx
            ORDER BY a.turnover_fraction DESC,a.cal_idx ASC
          ) AS anchor_turnover_rank
        FROM potential s
        JOIN base a ON a.symbol=s.symbol
          AND a.cal_idx BETWEEN s.cal_idx-60 AND s.cal_idx-10
          AND a.invalid_step_cum=s.invalid_step_cum
        WHERE a.hard_valid AND a.current_valid AND a.current_day_data_tradable
          AND a.market_rule_valid AND a.corporate_action_valid
          AND NOT a.corporate_action_blocking
      ),
      mother AS (
        SELECT * FROM ranked r
        WHERE anchor_turnover_rank=1
          AND anchor_return<=-0.03
          AND anchor_close_location<=0.50
          AND coord_close>anchor_high
          AND (
            SELECT count(*) FROM base m
            WHERE m.symbol=r.symbol
              AND m.cal_idx BETWEEN r.anchor_cal_idx+1 AND r.signal_cal_idx
              AND (
                m.invalid_step_cum<>r.invalid_step_cum
                OR NOT m.hard_valid OR NOT m.current_valid
                OR NOT m.market_rule_valid OR NOT m.corporate_action_valid
                OR m.corporate_action_blocking
              )
          )=0
          AND (
            SELECT count(*) FROM base m
            WHERE m.symbol=r.symbol
              AND m.cal_idx BETWEEN r.anchor_cal_idx+1 AND r.signal_cal_idx-1
              AND m.invalid_step_cum=r.invalid_step_cum
              AND m.current_day_data_tradable
              AND m.coord_close>r.anchor_high
          )=0
          AND (
            SELECT count(*) FROM base m
            WHERE m.symbol=r.symbol
              AND m.cal_idx BETWEEN r.anchor_cal_idx+1 AND r.signal_cal_idx-1
              AND m.invalid_step_cum=r.invalid_step_cum
              AND m.current_day_data_tradable
              AND m.coord_close<r.anchor_vwap
          )>=5
      ),
      target AS (
        SELECT m.*,
          (
            SELECT max(h.coord_high) FROM base h
            WHERE h.symbol=m.symbol
              AND h.cal_idx BETWEEN m.anchor_cal_idx-60 AND m.anchor_cal_idx-1
              AND h.invalid_step_cum=m.invalid_step_cum
              AND h.current_day_data_tradable AND h.hard_valid
              AND h.corporate_action_valid AND NOT h.corporate_action_blocking
          ) AS pre_anchor60_target_high,
          (
            SELECT count(*) FROM base h
            WHERE h.symbol=m.symbol
              AND h.cal_idx BETWEEN m.anchor_cal_idx+1 AND m.signal_cal_idx-1
              AND h.invalid_step_cum=m.invalid_step_cum
              AND h.current_day_data_tradable
              AND h.coord_close<m.anchor_vwap
          ) AS below_anchor_vwap_sessions
        FROM mother m
      )
      SELECT
        concat(symbol,'|',cast(anchor_date AS VARCHAR),'|',cast(signal_date AS VARCHAR))
          AS event_id,
        t.*,
        signal_cal_idx-anchor_cal_idx AS anchor_age_sessions,
        pre_anchor60_target_high/coord_close-1 AS signal_target_headroom,
        r.market_regime,r.market_median_ret20,r.market_median_ret60,
        r.market_positive_ret20_share,r.market_positive_ret60_share,
        r.latest_source_timestamp AS market_latest_source_timestamp
      FROM target t
      JOIN read_parquet('{REGIME.as_posix()}') r ON r.trade_date=t.signal_date
      WHERE pre_anchor60_target_high/coord_close-1>=0.05
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
        "signal_date", "decision_at", "available_at", "anchor_date",
        "anchor_decision_at", "anchor_available_at", "market_latest_source_timestamp",
    ):
        frame[column] = pd.to_datetime(frame[column])
    return frame


def audit(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.event_id.duplicated().any():
        raise ResearchError("duplicate frozen event identity")
    actual_counts = {
        int(year): int(value)
        for year, value in frame.groupby(frame.signal_date.dt.year).size().items()
    }
    if actual_counts != EXPECTED_COUNTS:
        raise ResearchError(f"outcome-blind coverage drift: {actual_counts}")
    later_source = frame[
        ["available_at", "anchor_available_at", "market_latest_source_timestamp"]
    ].max(axis=1)
    if later_source.gt(frame.decision_at).any():
        raise ResearchError("a predictor source arrived after decision_at")
    if frame.signal_date.max() > pd.Timestamp("2020-12-31"):
        raise ResearchError("post-2020 signal entered Stage A")
    if frame.anchor_age_sessions.lt(10).any() or frame.anchor_age_sessions.gt(60).any():
        raise ResearchError("anchor-age contract drift")
    if frame.anchor_return.gt(-0.03).any():
        raise ResearchError("seller-transfer direction drift")
    if frame.anchor_close_location.gt(0.50).any():
        raise ResearchError("anchor close-location drift")
    if frame.coord_close.le(frame.anchor_high).any():
        raise ResearchError("anchor-high reclaim drift")
    if frame.below_anchor_vwap_sessions.lt(5).any():
        raise ResearchError("trapped-inventory path drift")
    if frame.signal_target_headroom.lt(0.05).any():
        raise ResearchError("structural target headroom drift")
    return {
        "signals": int(len(frame)),
        "symbols": int(frame.symbol.nunique()),
        "signal_dates": int(frame.signal_date.nunique()),
        "annual_counts": {str(key): value for key, value in actual_counts.items()},
        "minimum_anchor_age": int(frame.anchor_age_sessions.min()),
        "maximum_anchor_age": int(frame.anchor_age_sessions.max()),
        "minimum_signal_target_headroom": float(frame.signal_target_headroom.min()),
        "maximum_signal_date": str(frame.signal_date.max().date()),
        "predictor_after_decision_count": int(later_source.gt(frame.decision_at).sum()),
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
        "2022_2024_signal_feature_or_outcome_read": "NO",
        "future_market_function": False,
        "future_anchor_or_target_function": False,
        "next_step": "Attach only the frozen A67/H20 labels, render every chart, then review all charts before any rule compression.",
    }
    write_json(FREEZE, payload)
    payload["freeze_sha256"] = sha256(FREEZE)
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
