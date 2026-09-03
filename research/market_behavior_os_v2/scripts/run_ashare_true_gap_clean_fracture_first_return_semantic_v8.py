#!/usr/bin/env python3
# ruff: noqa: E501
"""Outcome-blind V8 semantic audit for the clean-fracture first-return pattern.

This runner intentionally has no outcome, trade, PnL, or portfolio input.  It
starts from the frozen V6 causal true-gap candidate population, applies a
predeclared semantic-retrieval contract, and emits a blinded 30-chart pilot.
The numerical gates are chart-retrieval rules only; they are not a strategy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-CLEAN-FRACTURE-FIRST-RETURN-SEMANTIC-V8"
SOURCE_EXPERIMENT = "ASHARE-TRUE-GAP-CAUSAL-CLUSTER-V6-ONE-SHOT-DISCOVERY"
SOURCE_SPEC_HASH = "2705011d21792acfea34c6fe07819aa1a9e6dd91247bc27e66616749cc3ee162"
START_HEAD = "865bfa9ffb9e281438e10a60ca7f57dd3945658e"

SOURCE_SPEC = OS / f"experiments/{SOURCE_EXPERIMENT}_spec.json"
SOURCE_CANDIDATES = OS / f"artifacts/{SOURCE_EXPERIMENT}_candidate_ledger.parquet"
SOURCE_GAPS = Path("/Volumes/quant/CY_quant_research/ashare_true_gap_causal_cluster_v6_one_shot_discovery/causal_true_gap_ledger.parquet")
DAILY = Path("/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/pit_daily_compact_2013_2023.parquet")
VAP_BINS = Path("/Volumes/quant/CY_quant_research/ashare_true_gap_v7_overhang_attack_episode_simple_rule_development_v1/vap_session_bins.parquet")

EXT = Path("/Volumes/quant/CY_quant_research/ashare_true_gap_clean_fracture_first_return_semantic_v8")
SEMANTIC_LEDGER = EXT / "semantic_ledger.parquet"
SEALED_KEY = EXT / "blind_sample_sealed_key.parquet"
CHART_DIR = EXT / "blind_charts"

SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
CONTRACT = OS / f"experiments/{EXPERIMENT}_semantic_contract.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
BLIND_INDEX = OS / f"artifacts/{EXPERIMENT}_blind_chart_index.csv"
REVIEW = OS / f"artifacts/{EXPERIMENT}_review.csv"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"
PDF = ROOT / f"output/pdf/{EXPERIMENT}_blind_pilot_30.pdf"

DEV_START = pd.Timestamp("2014-01-01")
DEV_END = pd.Timestamp("2021-12-31 23:59:59")
EPS = 1e-12

# Outcome-blind semantic-retrieval constants.  These are not strategy values.
PRE_GAP_SESSIONS = 120
MIN_LEG_SESSIONS = 60
MAX_LEG_SESSIONS = 120
MIN_PEAK_TO_GAP_SESSIONS = 60
MIN_COLLAPSE_DRAWDOWN = 0.30
MIN_DECLINE_PATH_EFFICIENCY = 0.30
MAX_INTERIM_REBOUND_FRACTION = 0.50
MIN_DEPTH_BELOW_L = 0.125
MAX_PRE_GAP_INSIDE_DENSITY = 0.65
MAX_PRE_GAP_CORRIDOR_DENSITY = 0.80
MAX_PRE_GAP_INSIDE_TOUCH_SESSIONS = 4
MAX_PRE_GAP_CORRIDOR_TOUCH_SESSIONS = 8
MAX_POST_GAP_FREEZE_CORRIDOR_FLOAT_TURNOVER = 0.01
NEAR_TOUCH_DISTANCE_W = 0.25

SAMPLE_QUOTAS = {
    "RETAINED_CLEAN_FRACTURE": {"MAIN": 13, "CHINEXT": 4},
    "REJECTED_PRIOR_NEAR_TOUCH": {"MAIN": 4, "CHINEXT": 0},
    "REJECTED_ACUTE_RISE_FALL": {"MAIN": 1, "CHINEXT": 3},
    "REJECTED_CROWDED_CORRIDOR": {"MAIN": 2, "CHINEXT": 3},
}


class SemanticAuditError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_rank(value: str) -> str:
    return hashlib.sha256(f"{EXPERIMENT}|{value}".encode()).hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(path)


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "scientific_status": "OUTCOME_BLIND_SEMANTIC_RETRIEVAL_PILOT_NOT_A_STRATEGY",
        "source": {
            "experiment": SOURCE_EXPERIMENT,
            "spec_sha256": SOURCE_SPEC_HASH,
            "population": "V6 CORE causal first-return candidates",
            "true_gap_primitive": "High_t < Low_t_minus_1",
            "true_gap_interval": "[High_t, Low_t_minus_1]",
            "source_identity_changed": False,
        },
        "period": {"start": "2014-01-01", "end": "2021-12-31"},
        "causal_clock": {
            "gap_and_daily": "completed PIT daily sessions only",
            "primary_freeze": "unchanged V6 cluster_freeze_time",
            "event": "unchanged V6 causal_first_return",
            "post_event_bars": 0,
        },
        "retrieval_contract": {
            "memory": "CORE",
            "pre_gap_history": f"exactly {PRE_GAP_SESSIONS} same-lineage hard-valid 241-minute sessions",
            "main_collapse_leg": {
                "peak": "the frozen primary gap's own causal 120-session reference_high/reference_high_date",
                "trough": "earliest minimum QD-010 coordinate Low from that peak through V6 cluster freeze",
                "gap_must_form_no_later_than_trough": True,
                "duration_sessions_inclusive_bounds": [MIN_LEG_SESSIONS, MAX_LEG_SESSIONS],
                "minimum_peak_to_gap_sessions": MIN_PEAK_TO_GAP_SESSIONS,
                "minimum_peak_to_trough_drawdown": MIN_COLLAPSE_DRAWDOWN,
                "minimum_close_path_efficiency": MIN_DECLINE_PATH_EFFICIENCY,
                "maximum_interim_close_rebound_fraction_of_peak_trough_drop": MAX_INTERIM_REBOUND_FRACTION,
            },
            "subsequent_displacement": {
                "minimum_depth_below_L_before_event": MIN_DEPTH_BELOW_L,
                "signal_day_daily_low_excluded": True,
            },
            "raw_inventory": {
                "price_source": "frozen V7 outcome-blind QD-010 minute VAP bins",
                "bin_width": "0.10W",
                "local_normalizer": "raw volume in z=[-2,+3), normalized per price bin",
                "inside_gap": "z=[0,1), maximum relative per-bin density 0.65",
                "corridor": "z=[-0.5,1.5), maximum relative per-bin density 0.80",
                "inside_gap_session_occupancy": "no more than 4 of 120 pre-gap completed sessions have a daily range intersecting [L,U]",
                "corridor_session_occupancy": "no more than 8 of 120 pre-gap completed sessions have a daily range intersecting [L-0.5W,U+0.5W)",
                "post_gap_through_freeze_corridor": "allocated PIT free-float turnover <= 1.0%",
                "turnover_decay_used": False,
                "missing_policy": "FAIL_CLOSED",
            },
            "pristine_return": {
                "prior_completed_session_near_touch": f"High >= L - {NEAR_TOUCH_DISTANCE_W:.2f}W on any completed session strictly after gap formation and before event day",
                "allowed_prior_near_touch_count": 0,
                "post_gap_corridor_approach": "zero completed sessions strictly after gap formation and before event day with High >= L-0.5W",
                "clock_reset": False,
                "attack_2": "NOT_PART_OF_THIS_SEMANTIC_PILOT",
            },
        },
        "blind_sample": {
            "pages": 30,
            "quotas": SAMPLE_QUOTAS,
            "randomization": "deterministic SHA256 order; category and identity sealed outside Git",
            "chart_window": "120 completed sessions before gap through causal first return; no post-event bar",
            "outcomes_shown": False,
        },
        "governance": {
            "numeric_thresholds_are_strategy_parameters": False,
            "return_analysis_run": False,
            "strategy_backtest_run": False,
            "repository_2024_plus_data_opened": False,
            "human_review_required_before_outcome_research": True,
        },
    }


def spec_value(contract_hash: str) -> dict[str, Any]:
    return {
        "experiment_id": EXPERIMENT,
        "authoritative_start_head": START_HEAD,
        "source_spec_sha256": SOURCE_SPEC_HASH,
        "semantic_contract_sha256": contract_hash,
        "mission": "Test visual/semantic fidelity of a clean, low-inventory true-gap formed inside a coherent main collapse leg and approached for the first time only later.",
        "stage_order": ["FREEZE_OUTCOME_BLIND_CONTRACT", "BUILD_SEMANTIC_LEDGER", "GENERATE_30_BLIND_CHARTS", "STOP_FOR_HUMAN_REVIEW"],
        "prohibited": ["returns", "PnL", "trade replay", "model fitting", "2022+ data", "2024+ data", "post-event chart bars"],
        "contract": contract_value(),
    }


def validate_inputs() -> None:
    required = [SOURCE_SPEC, SOURCE_CANDIDATES, SOURCE_GAPS, DAILY, VAP_BINS]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SemanticAuditError(f"missing required input(s): {missing}")
    if sha256(SOURCE_SPEC) != SOURCE_SPEC_HASH:
        raise SemanticAuditError("frozen V6 source spec hash mismatch")
    forbidden_tokens = ("outcome", "return", "trade", "pnl", "nav", "model")
    for path in (SOURCE_CANDIDATES, SOURCE_GAPS, DAILY, VAP_BINS):
        lower = path.name.lower()
        if any(token in lower for token in forbidden_tokens):
            raise SemanticAuditError(f"forbidden scientific input name: {path}")


def freeze_contracts() -> dict[str, str]:
    write_json(CONTRACT, contract_value())
    contract_hash = sha256(CONTRACT)
    write_json(SPEC, spec_value(contract_hash))
    return {"semantic_contract_sha256": contract_hash, "spec_sha256": sha256(SPEC)}


def load_population() -> pd.DataFrame:
    con = duckdb.connect()
    query = f"""
      SELECT c.candidate_id,c.cluster_id,c.symbol,c.board,c.memory_state,
        c.causal_first_return,c.first_return_date,c.first_return_cal_idx,
        c.frozen_primary_gap_id AS gap_id,c.frozen_primary_gap_date AS gap_date,
        c.frozen_primary_lower AS L,c.frozen_primary_upper AS U,
        c.cluster_freeze_time,c.invalid_step_cum,c.gap_age_sessions,
        g.gap_cal_idx,g.reference_high_date AS gap_reference_high_date,
        g.reference_high AS gap_reference_high,g.reference_ret20,
        g.reference_large_up_days120,g.reference_limit_up_days120,
        g.true_gap_width AS W,g.true_gap_width_pct,g.importance
      FROM read_parquet('{SOURCE_CANDIDATES}') c
      JOIN read_parquet('{SOURCE_GAPS}') g
        ON g.true_gap_id=c.frozen_primary_gap_id
      WHERE c.memory_state='CORE'
        AND c.causal_first_return>=TIMESTAMP '2014-01-01'
        AND c.causal_first_return<TIMESTAMP '2022-01-01'
      ORDER BY c.causal_first_return,c.candidate_id
    """
    frame = con.execute(query).fetchdf()
    con.close()
    if frame.empty:
        raise SemanticAuditError("empty Development CORE source population")
    if frame.candidate_id.duplicated().any():
        raise SemanticAuditError("candidate_id is not unique after primary-gap join")
    for column in ("causal_first_return", "first_return_date", "gap_date", "cluster_freeze_time", "gap_reference_high_date"):
        frame[column] = pd.to_datetime(frame[column])
    frame["W"] = frame.U - frame.L
    if (frame.W <= 0).any():
        raise SemanticAuditError("non-positive true-gap width")
    if frame.causal_first_return.max() > DEV_END:
        raise SemanticAuditError("post-2021 candidate entered Development population")
    return frame


def load_daily_paths(population: pd.DataFrame) -> pd.DataFrame:
    seed = EXT / "population_seed.parquet"
    write_parquet(population[["candidate_id", "symbol", "gap_cal_idx", "first_return_cal_idx", "invalid_step_cum"]], seed)
    con = duckdb.connect()
    con.execute("SET threads=1")
    frame = con.execute(f"""
      SELECT s.candidate_id,d.trade_date,d.cal_idx,d.symbol,d.sleeve AS board,
        d.open,d.high,d.low,d.close,d.volume,d.amount,d.turnover_fraction,
        d.hard_valid,d.history_valid,d.current_valid,d.available_at,d.decision_at,
        d.invalid_step_cum,d.coordinate_factor,d.coord_open,d.coord_high,d.coord_low,d.coord_close
      FROM read_parquet('{seed}') s
      JOIN read_parquet('{DAILY}') d
        ON d.symbol=s.symbol
       AND d.cal_idx BETWEEN s.gap_cal_idx-{PRE_GAP_SESSIONS} AND s.first_return_cal_idx
       AND d.invalid_step_cum=s.invalid_step_cum
      WHERE d.trade_date>=DATE '2013-01-01'
        AND d.trade_date<=DATE '2021-12-31'
      ORDER BY s.candidate_id,d.cal_idx
    """).fetchdf()
    con.close()
    for column in ("trade_date", "available_at", "decision_at"):
        frame[column] = pd.to_datetime(frame[column])
    if frame.empty or frame.trade_date.max() > DEV_END:
        raise SemanticAuditError("daily path boundary failure")
    return frame


def load_vap_aggregates(population: pd.DataFrame) -> pd.DataFrame:
    seed = EXT / "population_vap_seed.parquet"
    write_parquet(population[["candidate_id", "cluster_freeze_time"]], seed)
    con = duckdb.connect()
    con.execute("SET threads=1")
    frame = con.execute(f"""
      WITH selected AS (
        SELECT v.*
        FROM read_parquet('{VAP_BINS}') v
        JOIN read_parquet('{seed}') s USING(candidate_id)
        WHERE v.trade_date<=DATE '2021-12-31'
      ), sessions AS (
        SELECT candidate_id,trade_date,session_offset,
          max(minute_count) AS minute_count,
          max(hard_valid::INT) AS hard_valid,
          max(history_valid::INT) AS history_valid,
          max(current_valid::INT) AS current_valid,
          max(proxy_minute_count) AS proxy_minute_count
        FROM selected GROUP BY 1,2,3
      ), coverage AS (
        SELECT candidate_id,
          count_if(session_offset BETWEEN -{PRE_GAP_SESSIONS} AND -1
                   AND minute_count=241 AND hard_valid=1 AND history_valid=1 AND current_valid=1) AS valid_pre_sessions,
          sum(CASE WHEN session_offset BETWEEN -{PRE_GAP_SESSIONS} AND -1 THEN proxy_minute_count ELSE 0 END) AS pre_proxy_minutes
        FROM sessions GROUP BY 1
      ), volume AS (
        SELECT v.candidate_id,
          sum(CASE WHEN v.session_offset BETWEEN -{PRE_GAP_SESSIONS} AND -1 AND v.z_bin BETWEEN -20 AND 29 THEN v.raw_volume ELSE 0 END) AS pre_local_raw_volume,
          sum(CASE WHEN v.session_offset BETWEEN -{PRE_GAP_SESSIONS} AND -1 AND v.z_bin BETWEEN 0 AND 9 THEN v.raw_volume ELSE 0 END) AS pre_inside_raw_volume,
          sum(CASE WHEN v.session_offset BETWEEN -{PRE_GAP_SESSIONS} AND -1 AND v.z_bin BETWEEN -5 AND 14 THEN v.raw_volume ELSE 0 END) AS pre_corridor_raw_volume,
          sum(CASE WHEN v.session_offset>=0 AND v.trade_date<=CAST(s.cluster_freeze_time AS DATE)
                    AND v.z_bin BETWEEN -5 AND 14 THEN v.allocated_float_turnover ELSE 0 END) AS post_gap_freeze_corridor_float_turnover
        FROM selected v JOIN read_parquet('{seed}') s USING(candidate_id)
        GROUP BY 1
      )
      SELECT c.*,v.* EXCLUDE(candidate_id)
      FROM coverage c JOIN volume v USING(candidate_id)
      ORDER BY candidate_id
    """).fetchdf()
    con.close()
    local = frame.pre_local_raw_volume.astype(float)
    frame["pre_gap_inside_density_relative_local"] = np.where(
        local > 0,
        (frame.pre_inside_raw_volume.astype(float) / 10.0) / (local / 50.0),
        np.nan,
    )
    frame["pre_gap_corridor_density_relative_local"] = np.where(
        local > 0,
        (frame.pre_corridor_raw_volume.astype(float) / 20.0) / (local / 50.0),
        np.nan,
    )
    return frame


def _safe_float(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    return result if np.isfinite(result) else math.nan


def _path_features(event: Any, days: pd.DataFrame) -> dict[str, Any]:
    days = days.sort_values("cal_idx", kind="mergesort").copy()
    valid = days.loc[days.hard_valid.fillna(False) & days.history_valid.fillna(False) & days.current_valid.fillna(False)]
    peak_date = pd.Timestamp(event.gap_reference_high_date).normalize()
    freeze_date = pd.Timestamp(event.cluster_freeze_time).normalize()
    signal_date = pd.Timestamp(event.causal_first_return).normalize()
    peak_rows = valid.loc[valid.trade_date.eq(peak_date)]
    leg = valid.loc[valid.trade_date.between(peak_date, freeze_date)]
    output: dict[str, Any] = {
        "peak_row_available": not peak_rows.empty,
        "leg_path_available": not leg.empty,
        "local_peak_time": peak_date,
        "local_peak_price": _safe_float(event.gap_reference_high),
        "local_trough_time": pd.NaT,
        "local_trough_price": math.nan,
        "collapse_leg_duration_sessions": math.nan,
        "peak_to_gap_sessions": math.nan,
        "collapse_drawdown": math.nan,
        "decline_path_efficiency": math.nan,
        "max_interim_rebound_fraction": math.nan,
        "gap_formed_in_main_collapse_leg": False,
        "max_depth_below_l_before_event": math.nan,
        "prior_completed_session_near_touch_count": 0,
        "prior_completed_session_exact_touch_count": 0,
        "pre_gap_inside_touch_sessions": 0,
        "pre_gap_corridor_touch_sessions": 0,
        "post_gap_corridor_approach_sessions": 0,
        "near_touch_dates_json": "[]",
    }
    if peak_rows.empty or leg.empty:
        return output
    trough = leg.sort_values(["coord_low", "trade_date"], kind="mergesort").iloc[0]
    trough_date = pd.Timestamp(trough.trade_date)
    peak = peak_rows.iloc[0]
    path = leg.loc[leg.cal_idx.between(int(peak.cal_idx), int(trough.cal_idx))].sort_values("cal_idx")
    closes = path.coord_close.astype(float).to_numpy()
    total_motion = float(np.abs(np.diff(closes)).sum()) if len(closes) > 1 else 0.0
    net_decline = max(float(closes[0] - closes[-1]), 0.0) if len(closes) else math.nan
    efficiency = net_decline / total_motion if total_motion > EPS else math.nan
    peak_to_trough = _safe_float(event.gap_reference_high) - float(trough.coord_low)
    max_rebound = 0.0
    if len(closes) > 1 and peak_to_trough > EPS:
        running_min = np.minimum.accumulate(closes)
        rebound = closes - np.r_[closes[0], running_min[:-1]]
        max_rebound = max(float(np.nanmax(rebound)), 0.0) / peak_to_trough
    prior = valid.loc[(valid.cal_idx > int(event.gap_cal_idx)) & (valid.trade_date < signal_date)]
    pre_gap = valid.loc[valid.cal_idx.between(int(event.gap_cal_idx) - PRE_GAP_SESSIONS, int(event.gap_cal_idx) - 1)]
    depth = math.nan
    if not prior.empty:
        depth = max(1.0 - float(prior.coord_low.min()) / float(event.L), 0.0)
    near_level = float(event.L) - NEAR_TOUCH_DISTANCE_W * float(event.W)
    corridor_lower = float(event.L) - 0.5 * float(event.W)
    corridor_upper = float(event.U) + 0.5 * float(event.W)
    near = prior.loc[prior.coord_high >= near_level]
    exact = prior.loc[prior.coord_high >= float(event.L)]
    pre_inside = pre_gap.loc[(pre_gap.coord_high >= float(event.L)) & (pre_gap.coord_low <= float(event.U))]
    pre_corridor = pre_gap.loc[(pre_gap.coord_high >= corridor_lower) & (pre_gap.coord_low <= corridor_upper)]
    post_corridor = prior.loc[prior.coord_high >= corridor_lower]
    return {
        **output,
        "local_trough_time": trough_date,
        "local_trough_price": float(trough.coord_low),
        "collapse_leg_duration_sessions": int(trough.cal_idx - peak.cal_idx),
        "peak_to_gap_sessions": int(event.gap_cal_idx - peak.cal_idx),
        "collapse_drawdown": 1.0 - float(trough.coord_low) / float(event.gap_reference_high),
        "decline_path_efficiency": efficiency,
        "max_interim_rebound_fraction": max_rebound,
        "gap_formed_in_main_collapse_leg": int(event.gap_cal_idx) <= int(trough.cal_idx),
        "max_depth_below_l_before_event": depth,
        "prior_completed_session_near_touch_count": len(near),
        "prior_completed_session_exact_touch_count": len(exact),
        "pre_gap_inside_touch_sessions": len(pre_inside),
        "pre_gap_corridor_touch_sessions": len(pre_corridor),
        "post_gap_corridor_approach_sessions": len(post_corridor),
        "near_touch_dates_json": json.dumps([pd.Timestamp(value).date().isoformat() for value in near.trade_date], separators=(",", ":")),
    }


def build_semantic_ledger(population: pd.DataFrame, daily: pd.DataFrame, vap: pd.DataFrame) -> pd.DataFrame:
    grouped = {key: part for key, part in daily.groupby("candidate_id", sort=False)}
    rows = []
    for event in population.itertuples(index=False):
        days = grouped.get(event.candidate_id, daily.iloc[0:0])
        rows.append({"candidate_id": event.candidate_id, **_path_features(event, days)})
    path = pd.DataFrame(rows)
    ledger = population.merge(path, on="candidate_id", validate="one_to_one").merge(vap, on="candidate_id", validate="one_to_one")

    ledger["gate_exact_120_session_history"] = ledger.valid_pre_sessions.eq(PRE_GAP_SESSIONS)
    ledger["gate_peak_and_leg_available"] = ledger.peak_row_available & ledger.leg_path_available
    ledger["gate_duration"] = ledger.collapse_leg_duration_sessions.between(MIN_LEG_SESSIONS, MAX_LEG_SESSIONS, inclusive="both")
    ledger["gate_long_decline_before_gap"] = ledger.peak_to_gap_sessions.ge(MIN_PEAK_TO_GAP_SESSIONS)
    ledger["gate_gap_inside_main_leg"] = ledger.gap_formed_in_main_collapse_leg
    ledger["gate_drawdown"] = ledger.collapse_drawdown.ge(MIN_COLLAPSE_DRAWDOWN)
    ledger["gate_path_efficiency"] = ledger.decline_path_efficiency.ge(MIN_DECLINE_PATH_EFFICIENCY)
    ledger["gate_interim_rebound"] = ledger.max_interim_rebound_fraction.le(MAX_INTERIM_REBOUND_FRACTION)
    ledger["gate_depth_below_l"] = ledger.max_depth_below_l_before_event.ge(MIN_DEPTH_BELOW_L)
    ledger["gate_raw_inside_clean"] = ledger.pre_gap_inside_density_relative_local.le(MAX_PRE_GAP_INSIDE_DENSITY)
    ledger["gate_raw_corridor_clean"] = ledger.pre_gap_corridor_density_relative_local.le(MAX_PRE_GAP_CORRIDOR_DENSITY)
    ledger["gate_pre_gap_inside_session_occupancy"] = ledger.pre_gap_inside_touch_sessions.le(MAX_PRE_GAP_INSIDE_TOUCH_SESSIONS)
    ledger["gate_pre_gap_corridor_session_occupancy"] = ledger.pre_gap_corridor_touch_sessions.le(MAX_PRE_GAP_CORRIDOR_TOUCH_SESSIONS)
    ledger["gate_post_gap_corridor_clean"] = ledger.post_gap_freeze_corridor_float_turnover.le(MAX_POST_GAP_FREEZE_CORRIDOR_FLOAT_TURNOVER)
    ledger["gate_no_prior_near_touch"] = ledger.prior_completed_session_near_touch_count.eq(0)
    ledger["gate_no_post_gap_corridor_approach"] = ledger.post_gap_corridor_approach_sessions.eq(0)
    ledger["gate_event_after_freeze"] = ledger.causal_first_return.gt(ledger.cluster_freeze_time)
    gate_columns = [column for column in ledger.columns if column.startswith("gate_")]
    ledger["retained_clean_fracture"] = ledger[gate_columns].fillna(False).all(axis=1)

    common = (
        ledger.gate_exact_120_session_history
        & ledger.gate_peak_and_leg_available
        & ledger.gate_gap_inside_main_leg
        & ledger.gate_drawdown
        & ledger.gate_path_efficiency
        & ledger.gate_interim_rebound
        & ledger.gate_depth_below_l
        & ledger.gate_post_gap_corridor_clean
        & ledger.gate_event_after_freeze
    )
    inventory_clean = (
        ledger.gate_raw_inside_clean
        & ledger.gate_raw_corridor_clean
        & ledger.gate_pre_gap_inside_session_occupancy
        & ledger.gate_pre_gap_corridor_session_occupancy
    )
    long_form = ledger.gate_duration & ledger.gate_long_decline_before_gap
    pristine = ledger.gate_no_prior_near_touch & ledger.gate_no_post_gap_corridor_approach
    acute = (ledger.collapse_leg_duration_sessions < 20) | (ledger.peak_to_gap_sessions < 20)
    crowded = (ledger.pre_gap_corridor_density_relative_local >= 1.20) | (ledger.pre_gap_inside_density_relative_local >= 1.20)

    ledger["control_prior_near_touch"] = common & long_form & inventory_clean & ~pristine & ~ledger.retained_clean_fracture
    ledger["control_acute_rise_fall"] = common & acute & inventory_clean & pristine & ~ledger.retained_clean_fracture
    ledger["control_crowded_corridor"] = common & long_form & crowded & pristine & ~ledger.retained_clean_fracture
    ledger["blind_pool"] = np.select(
        [ledger.retained_clean_fracture, ledger.control_prior_near_touch, ledger.control_acute_rise_fall, ledger.control_crowded_corridor],
        ["RETAINED_CLEAN_FRACTURE", "REJECTED_PRIOR_NEAR_TOUCH", "REJECTED_ACUTE_RISE_FALL", "REJECTED_CROWDED_CORRIDOR"],
        default="NOT_SAMPLED",
    )

    forbidden = [column for column in ledger.columns if any(token in column.lower() for token in ("return", "pnl", "win", "loss", "target_hit", "mae", "mfe")) and column not in {"causal_first_return", "first_return_date", "first_return_cal_idx", "reference_ret20"}]
    if forbidden:
        raise SemanticAuditError(f"outcome-like columns entered semantic ledger: {forbidden}")
    write_parquet(ledger, SEMANTIC_LEDGER)
    return ledger


def select_blind_sample(ledger: pd.DataFrame) -> pd.DataFrame:
    selected: list[pd.DataFrame] = []
    used_candidates: set[str] = set()
    used_symbols: set[str] = set()
    for category, boards in SAMPLE_QUOTAS.items():
        for board, count in boards.items():
            if count == 0:
                continue
            pool = ledger.loc[(ledger.blind_pool == category) & (ledger.board == board)].copy()
            pool["_rank"] = pool.candidate_id.map(stable_rank)
            pool = pool.sort_values("_rank", kind="mergesort")
            unique = pool.loc[~pool.symbol.isin(used_symbols)].head(count)
            if len(unique) < count:
                remainder = pool.loc[~pool.candidate_id.isin(set(unique.candidate_id) | used_candidates)].head(count - len(unique))
                unique = pd.concat([unique, remainder], ignore_index=True)
            if len(unique) != count:
                raise SemanticAuditError(f"insufficient blind pool for {category}/{board}: need {count}, have {len(unique)}")
            selected.append(unique)
            used_candidates.update(unique.candidate_id.astype(str))
            used_symbols.update(unique.symbol.astype(str))
    sample = pd.concat(selected, ignore_index=True)
    if len(sample) != 30 or sample.candidate_id.duplicated().any():
        raise SemanticAuditError("blind sample identity failure")
    sample["_blind_rank"] = sample.candidate_id.map(lambda value: stable_rank(f"BLIND|{value}"))
    sample = sample.sort_values("_blind_rank", kind="mergesort").reset_index(drop=True)
    sample["chart_id"] = [f"V8-BLIND-{index:03d}" for index in range(1, len(sample) + 1)]
    sample["post_event_bars"] = 0
    write_parquet(sample.drop(columns=["_rank", "_blind_rank"], errors="ignore"), SEALED_KEY)

    blind = sample[["chart_id", "post_event_bars"]].copy()
    blind["chart_file"] = blind.chart_id.map(lambda value: f"{value}.png")
    blind.to_csv(BLIND_INDEX, index=False)
    review = pd.DataFrame(
        {
            "chart_id": sample.chart_id,
            "PATTERN_MATCH_A_B_C": "",
            "LONG_COHERENT_COLLAPSE_YES_NO": "",
            "RAPID_RISE_FALL_EXCLUDED_YES_NO": "",
            "PRIMARY_GAP_IN_MAIN_COLLAPSE_YES_NO": "",
            "EXACT_GAP_AND_CORRIDOR_CLEAN_YES_NO": "",
            "FIRST_APPROACH_PRISTINE_YES_NO": "",
            "DEPTH_BELOW_ZONE_MEANINGFUL_YES_NO": "",
            "FIRST_RETURN_CORRECT_YES_NO": "",
            "COMMENTS": "",
        }
    )
    review.to_csv(REVIEW, index=False)
    return sample


def load_vap_profiles(sample: pd.DataFrame) -> pd.DataFrame:
    seed = EXT / "blind_sample_seed.parquet"
    write_parquet(sample[["candidate_id", "cluster_freeze_time"]], seed)
    con = duckdb.connect()
    con.execute("SET threads=1")
    frame = con.execute(f"""
      SELECT v.candidate_id,v.z_bin,
        sum(CASE WHEN v.session_offset BETWEEN -{PRE_GAP_SESSIONS} AND -1 THEN v.raw_volume ELSE 0 END) AS pre_raw_volume,
        sum(CASE WHEN v.session_offset>=0 AND v.trade_date<=CAST(s.cluster_freeze_time AS DATE) THEN v.allocated_float_turnover ELSE 0 END) AS post_freeze_float_turnover
      FROM read_parquet('{VAP_BINS}') v
      JOIN read_parquet('{seed}') s USING(candidate_id)
      WHERE v.trade_date<=DATE '2021-12-31' AND v.z_bin BETWEEN -20 AND 29
      GROUP BY 1,2 ORDER BY 1,2
    """).fetchdf()
    con.close()
    return frame


def _candles(ax: Any, frame: pd.DataFrame) -> None:
    width = 0.55
    for row in frame.itertuples(index=False):
        x = mdates.date2num(pd.Timestamp(row.trade_date).to_pydatetime())
        color = "#d62728" if row.coord_close >= row.coord_open else "#138a5b"
        ax.vlines(x, row.coord_low, row.coord_high, color=color, linewidth=0.55, alpha=0.92, zorder=3)
        bottom = min(row.coord_open, row.coord_close)
        height = abs(row.coord_close - row.coord_open)
        if height <= EPS:
            ax.hlines(row.coord_close, x - width / 2, x + width / 2, color=color, linewidth=0.8, zorder=4)
        else:
            ax.add_patch(Rectangle((x - width / 2, bottom), width, height, facecolor=color, edgecolor=color, linewidth=0.35, zorder=4))


def _shade_levels(ax: Any, L: float, U: float, W: float) -> None:
    ax.axhspan(L - 0.5 * W, U + 0.5 * W, color="#9e9e9e", alpha=0.10, zorder=0)
    ax.axhspan(L, U, color="#ff9800", alpha=0.22, zorder=1)
    ax.axhline(L, color="#d95f02", linestyle="--", linewidth=1.0)
    ax.axhline(U, color="#d95f02", linestyle="--", linewidth=1.0)


def render_charts(sample: pd.DataFrame, daily: pd.DataFrame, profiles: pd.DataFrame) -> None:
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    PDF.parent.mkdir(parents=True, exist_ok=True)
    daily_groups = {key: part for key, part in daily.groupby("candidate_id", sort=False)}
    profile_groups = {key: part for key, part in profiles.groupby("candidate_id", sort=False)}
    metadata = {
        "Title": f"{EXPERIMENT} — 30-chart blinded semantic pilot",
        "Author": "CY Market Behavior OS",
        "Subject": "Outcome-blind true-gap semantic review; no post-event bars",
        "Keywords": "A-share,true-gap,semantic-audit,blind-review",
        "CreationDate": datetime(2000, 1, 1, tzinfo=UTC),
        "ModDate": datetime(2000, 1, 1, tzinfo=UTC),
    }
    with PdfPages(PDF, metadata=metadata) as pdf:
        for event in sample.itertuples(index=False):
            days = daily_groups[event.candidate_id].sort_values("cal_idx", kind="mergesort")
            # A full daily bar on the event day contains observations after the intraday event.
            plot_days = days.loc[days.trade_date < pd.Timestamp(event.causal_first_return).normalize()].copy()
            profile = profile_groups.get(event.candidate_id, profiles.iloc[0:0]).copy()
            if plot_days.empty:
                raise SemanticAuditError(f"no pre-event plot path for {event.chart_id}")

            fig = plt.figure(figsize=(15.5, 8.7), constrained_layout=True)
            grid = fig.add_gridspec(2, 3, width_ratios=[5.8, 1.25, 1.25], height_ratios=[4.6, 1.15])
            ax = fig.add_subplot(grid[0, 0])
            vol = fig.add_subplot(grid[1, 0], sharex=ax)
            pre_ax = fig.add_subplot(grid[:, 1], sharey=ax)
            post_ax = fig.add_subplot(grid[:, 2], sharey=ax)

            _candles(ax, plot_days)
            _shade_levels(ax, event.L, event.U, event.W)
            for axis in (pre_ax, post_ax):
                _shade_levels(axis, event.L, event.U, event.W)

            peak_time = pd.Timestamp(event.local_peak_time)
            trough_time = pd.Timestamp(event.local_trough_time)
            gap_time = pd.Timestamp(event.gap_date)
            freeze_time = pd.Timestamp(event.cluster_freeze_time)
            return_time = pd.Timestamp(event.causal_first_return)
            ax.scatter(peak_time, event.local_peak_price, marker="*", s=100, color="#b8860b", zorder=8)
            ax.annotate("local peak", (peak_time, event.local_peak_price), xytext=(4, 8), textcoords="offset points", fontsize=8)
            ax.scatter(trough_time, event.local_trough_price, marker="v", s=48, color="#6a3d9a", zorder=8)
            ax.annotate("local trough", (trough_time, event.local_trough_price), xytext=(4, -14), textcoords="offset points", fontsize=8)
            ax.axvline(gap_time, color="#e31a1c", linewidth=1.1, linestyle="-")
            ax.axvline(freeze_time, color="#1f78b4", linewidth=1.0, linestyle="--")
            ax.axvline(return_time, color="#6a3d9a", linewidth=1.2, linestyle=":")
            ax.text(gap_time, 0.98, f"gap formation\n{gap_time.date().isoformat()}", transform=ax.get_xaxis_transform(), rotation=90, va="top", ha="right", fontsize=7, color="#b2182b")
            ax.text(freeze_time, 0.98, f"V6 freeze\n{freeze_time.date().isoformat()}", transform=ax.get_xaxis_transform(), rotation=90, va="top", ha="right", fontsize=7, color="#2166ac")
            ax.scatter(return_time, event.L, marker="^", s=70, color="#6a3d9a", zorder=9, clip_on=False)
            ax.annotate("causal first return\n(intraday; no event-day candle)", (return_time, event.L), xytext=(-4, 10), textcoords="offset points", ha="right", fontsize=8, color="#54278f")

            near_dates = json.loads(event.near_touch_dates_json)
            if near_dates:
                near_rows = plot_days.loc[plot_days.trade_date.isin(pd.to_datetime(near_dates))]
                ax.scatter(near_rows.trade_date, near_rows.coord_high, marker="x", s=36, color="#111111", linewidths=1.0, label="prior completed-session near-touch")

            volume = plot_days.volume.astype(float)
            colors = np.where(plot_days.coord_close >= plot_days.coord_open, "#d62728", "#138a5b")
            vol.bar(plot_days.trade_date, volume / 1e6, width=0.7, color=colors, alpha=0.55)
            vol.set_ylabel("Volume (m)", fontsize=8)
            vol.grid(axis="y", alpha=0.18)

            if not profile.empty:
                y = event.L + (profile.z_bin.astype(float) + 0.5) * 0.10 * event.W
                pre = profile.pre_raw_volume.astype(float)
                post = profile.post_freeze_float_turnover.astype(float)
                pre_ax.barh(y, pre / max(float(pre.max()), EPS), height=0.085 * event.W, color="#4c78a8", alpha=0.72)
                post_ax.barh(y, post / max(float(post.max()), EPS), height=0.085 * event.W, color="#f58518", alpha=0.72)
            pre_ax.set_title("Raw VAP\n120 sessions pre-gap", fontsize=9)
            post_ax.set_title("PIT float-turnover VAP\ngap → freeze", fontsize=9)
            for axis in (pre_ax, post_ax):
                axis.set_xlim(left=0)
                axis.tick_params(axis="x", labelsize=7)
                axis.tick_params(axis="y", labelleft=False)
                axis.grid(axis="x", alpha=0.18)

            start_time = pd.Timestamp(plot_days.trade_date.min())
            ax.set_xlim(start_time - pd.Timedelta(days=3), return_time + pd.Timedelta(days=3))
            lows = [float(plot_days.coord_low.min()), float(event.L - 2.0 * event.W)]
            highs = [float(plot_days.coord_high.max()), float(event.U + 2.0 * event.W)]
            pad = max((max(highs) - min(lows)) * 0.06, event.W)
            ax.set_ylim(min(lows) - pad, max(highs) + pad)
            ax.annotate(f"U = {event.U:.4f}", (start_time, event.U), xytext=(3, 2), textcoords="offset points", fontsize=7, color="#a63603")
            ax.annotate(f"L = {event.L:.4f}", (start_time, event.L), xytext=(3, -10), textcoords="offset points", fontsize=7, color="#a63603")
            ax.set_ylabel("QD-010 comparable price")
            ax.grid(alpha=0.18)
            ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=6, maxticks=12))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
            plt.setp(ax.get_xticklabels(), visible=False)
            vol.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=6, maxticks=12))
            vol.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
            plt.setp(vol.get_xticklabels(), rotation=28, ha="right", fontsize=8)

            handles = [
                Rectangle((0, 0), 1, 1, facecolor="#ff9800", alpha=0.22, label="true primary gap [L,U]"),
                Rectangle((0, 0), 1, 1, facecolor="#9e9e9e", alpha=0.10, label="inventory corridor [L−0.5W,U+0.5W)"),
            ]
            if near_dates:
                handles.append(plt.Line2D([0], [0], marker="x", color="#111111", linestyle="None", label="prior completed-session near-touch"))
            ax.legend(handles=handles, loc="best", fontsize=8, frameon=True)
            fig.suptitle(f"{event.chart_id}  |  Outcome-blind semantic review", fontsize=15, fontweight="bold")
            fig.text(0.015, 0.948, "Marks: local peak • main-leg trough • gap formation • V6 freeze • exact causal first return", fontsize=9)

            png = CHART_DIR / f"{event.chart_id}.png"
            fig.savefig(png, dpi=150, bbox_inches="tight", facecolor="white")
            pdf.savefig(fig, dpi=150, bbox_inches="tight", facecolor="white")
            plt.close(fig)


def summarize(ledger: pd.DataFrame, sample: pd.DataFrame, hashes: dict[str, str]) -> dict[str, Any]:
    pool_counts = ledger.blind_pool.value_counts().to_dict()
    sample_counts = sample.groupby(["blind_pool", "board"]).size().rename("count").reset_index().to_dict("records")
    result = {
        "experiment": EXPERIMENT,
        "status": "STOPPED_FOR_HUMAN_BLIND_REVIEW",
        "source": SOURCE_EXPERIMENT,
        "source_spec_sha256": SOURCE_SPEC_HASH,
        "hashes": hashes,
        "coverage": {
            "start": str(ledger.causal_first_return.min()),
            "end": str(ledger.causal_first_return.max()),
            "source_core_candidates": len(ledger),
            "symbols": int(ledger.symbol.nunique()),
            "retained_clean_fracture": int(ledger.retained_clean_fracture.sum()),
            "blind_pool_counts": {str(k): int(v) for k, v in pool_counts.items()},
        },
        "blind_pilot": {
            "chart_count": len(sample),
            "board_counts": {str(k): int(v) for k, v in sample.board.value_counts().to_dict().items()},
            "category_board_counts": sample_counts,
            "duplicate_symbol_count": int(len(sample) - sample.symbol.nunique()),
            "pdf": str(PDF),
            "sealed_key": str(SEALED_KEY),
            "chart_directory": str(CHART_DIR),
            "review_csv": str(REVIEW),
        },
        "audit": {
            "V6_EVENT_IDENTITY_CHANGED_COUNT": 0,
            "TURNOVER_DECAY_USED_FOR_CLEAN_FRACTURE_COUNT": 0,
            "MISSING_REQUIRED_HISTORY_PASSED_COUNT": int((ledger.retained_clean_fracture & ~ledger.gate_exact_120_session_history).sum()),
            "PRIOR_NEAR_TOUCH_PASSED_COUNT": int((ledger.retained_clean_fracture & ~ledger.gate_no_prior_near_touch).sum()),
            "EVENT_AT_OR_BEFORE_FREEZE_RETAINED_COUNT": int((ledger.retained_clean_fracture & ~ledger.gate_event_after_freeze).sum()),
            "POST_EVENT_CHART_BAR_COUNT": int(sample.post_event_bars.sum()),
            "RETURN_ANALYSIS_RUN": "NO",
            "STRATEGY_BACKTEST_RUN": "NO",
            "REPOSITORY_2024_PLUS_DATA_OPENED": "NO",
            "POST_2021_DATA_USED": "NO",
        },
        "verdict": "HUMAN_SEMANTIC_REVIEW_REQUIRED",
    }
    result["hashes"].update(
        {
            "semantic_ledger_sha256": sha256(SEMANTIC_LEDGER),
            "sealed_key_sha256": sha256(SEALED_KEY),
            "blind_index_sha256": sha256(BLIND_INDEX),
            "review_csv_sha256": sha256(REVIEW),
            "pdf_sha256": sha256(PDF),
        }
    )
    return result


def write_report(result: dict[str, Any]) -> None:
    coverage = result["coverage"]
    blind = result["blind_pilot"]
    audit = result["audit"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        "## Status",
        "",
        "`STOPPED_FOR_HUMAN_BLIND_REVIEW`",
        "",
        "This is an outcome-blind semantic retrieval audit, not a strategy or profitability result. The frozen V6 true-gap identity and causal first-return clock were not changed.",
        "",
        "## Frozen semantic repair",
        "",
        "- A candidate must place its primary gap only after at least 60 completed sessions of decline from the gap's own causal reference high; the peak-to-trough leg must span 60–120 sessions.",
        "- Peak-to-trough drawdown must be at least 30%, close-path efficiency at least 0.30, and the largest interim rebound no more than half of the peak-to-trough decline.",
        "- The stock must complete a later displacement of at least 12.5% below L before the event day.",
        "- Raw 120-session pre-gap occupancy must be low both inside the exact gap and across `[L−0.5W,U+0.5W)`; turnover-decayed inventory is not used for this semantic gate.",
        "- At most 4 pre-gap sessions may intersect `[L,U]`, and at most 8 may intersect the wider corridor; this prevents low relative volume from hiding prolonged sideways occupancy.",
        "- Any prior completed-session approach to the corridor after gap formation rejects pristine first-return status. The clock is never reset.",
        "- All numeric values are audit-retrieval rules only and have not been tested against outcomes.",
        "",
        "## Population and pilot",
        "",
        f"- Source CORE Development candidates: {coverage['source_core_candidates']:,} across {coverage['symbols']:,} symbols.",
        f"- Candidates satisfying all retrieval gates: {coverage['retained_clean_fracture']}.",
        f"- Blind charts: {blind['chart_count']} ({blind['board_counts']}).",
        "- The pilot mixes retained cases with isolated near-touch, acute-rise/fall, and crowded-corridor controls. Identity and category remain in the external sealed key, not in the chart index or PDF.",
        "- Each chart spans the full 120 completed sessions before gap formation through the exact intraday first-return marker. The full event-day candle is omitted because it contains post-event observations.",
        "",
        "## Governance audit",
        "",
        f"- V6 event identity changed: {audit['V6_EVENT_IDENTITY_CHANGED_COUNT']}",
        f"- Missing required history passed: {audit['MISSING_REQUIRED_HISTORY_PASSED_COUNT']}",
        f"- Prior near-touch passed: {audit['PRIOR_NEAR_TOUCH_PASSED_COUNT']}",
        f"- Post-event chart bars: {audit['POST_EVENT_CHART_BAR_COUNT']}",
        f"- Return analysis: {audit['RETURN_ANALYSIS_RUN']}",
        f"- Strategy backtest: {audit['STRATEGY_BACKTEST_RUN']}",
        f"- Repository 2024+ opened: {audit['REPOSITORY_2024_PLUS_DATA_OPENED']}",
        "",
        "## Next decision",
        "",
        "A human must score all 30 blind pages before any outcome attachment. If the retained cases do not visibly match the requested clean-fracture pattern, this contract must be rejected semantically rather than rescued with returns.",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> dict[str, Any]:
    validate_inputs()
    hashes = freeze_contracts()
    population = load_population()
    daily = load_daily_paths(population)
    vap = load_vap_aggregates(population)
    ledger = build_semantic_ledger(population, daily, vap)
    sample = select_blind_sample(ledger)
    profiles = load_vap_profiles(sample)
    render_charts(sample, daily, profiles)
    result = summarize(ledger, sample, hashes)
    write_json(RESULT, result)
    write_report(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="run", choices=("run", "contract"))
    args = parser.parse_args()
    if args.command == "contract":
        validate_inputs()
        print(json.dumps(freeze_contracts(), indent=2, sort_keys=True))
        return
    print(json.dumps(run(), indent=2, sort_keys=True, default=_json_default))


if __name__ == "__main__":
    main()
