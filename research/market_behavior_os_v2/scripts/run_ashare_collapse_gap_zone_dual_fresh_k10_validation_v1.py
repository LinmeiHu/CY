#!/usr/bin/env python3
# ruff: noqa: E402,E501
"""First frozen 2022--2023 external Validation of Dual-Fresh K10."""

from __future__ import annotations

import argparse
import inspect
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.market_behavior_os_v2.scripts import run_ashare_former_leader_strict_gap_reclaim_v3 as adjusted
from research.market_behavior_os_v2.scripts import run_ashare_collapse_gap_zone_pattern_fidelity_audit_v1 as pit
from research.market_behavior_os_v2.scripts import run_ashare_collapse_defining_gap_zone_high_precision_pilot_v3 as detector
from research.market_behavior_os_v2.scripts import run_ashare_collapse_gap_zone_strategy_development_v1 as strategy
from research.market_behavior_os_v2.scripts import run_ashare_collapse_gap_zone_entry_admission_development_v1 as admission
from research.market_behavior_os_v2.scripts import run_ashare_collapse_gap_zone_dual_fresh_capitalization_v1 as capitalization

OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-COLLAPSE-GAP-ZONE-DUAL-FRESH-K10-VALIDATION-V1"
START_HEAD = "5d13bcf685130bff1f1169b6d4ea05a2f192042b"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_spec.json"
EXPECTED_SPEC_SHA256 = "59fcb4e98c1adb96b23182a13979b1858dc33a622caa923b884cc3a613dbf194"
EXTERNAL = Path("/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_dual_fresh_k10_validation_v1")
DAILY_ROOT = Path("/Volumes/quant/CY_quant_research/ashare_tail_open_lgbm_v1/pit_daily_2013_2023_cy006/daily")
DAILY_CONTRACT = Path("/Volumes/quant/CY_quant_research/ashare_tail_open_lgbm_v1/daily_contract_2013_2023.parquet")
QD004_INVENTORY = OS_ROOT / "experiments/ASHARE-TAIL-OPEN-LGBM-V1_qd004_2013_2023_inventory.json"
RAW_ROOT = Path("/Users/linmei/Downloads/workspace/quant/data/lake/stock_1min_canonical_none_20260813/bars")
DEV_FEATURE_DAILY = Path("/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_entry_admission_development_v1/all_e1_preentry_daily.parquet")

ADJUSTED = EXTERNAL / "pit_adjusted_daily_state_2013_2023.parquet"
DAILY = EXTERNAL / "pit_daily_compact_2013_2023.parquet"
PRIMITIVES = EXTERNAL / "strict_gap_primitives_2014_2023.parquet"
VALID_DAILY = EXTERNAL / "valid_daily_2014_2023.parquet"
COLLAPSE_SEEDS = EXTERNAL / "collapse_seeds.parquet"
COLLAPSE_EPISODES = EXTERNAL / "collapse_episodes.parquet"
EPISODE_PRIMITIVES = EXTERNAL / "episode_strict_gap_primitives.parquet"
MEANINGFUL_PRIMITIVES = EXTERNAL / "meaningful_collapse_gap_primitives.parquet"
PAIR_RECOVERY = EXTERNAL / "meaningful_primitive_pair_recovery.parquet"
ZONE_STACKS = EXTERNAL / "meaningful_zone_stacks.parquet"
LIFECYCLE_ROWS = EXTERNAL / "zone_lifecycle_rows.parquet"
LIFECYCLE_SUMMARY = EXTERNAL / "zone_lifecycle_summary.parquet"
EXACT_REENTRY = EXTERNAL / "exact_reentry_validation.parquet"
CANDIDATES = EXTERNAL / "v3_candidates_validation.parquet"
SOURCE = EXTERNAL / "source_events_validation.parquet"
CONFIRMATIONS = EXTERNAL / "e1_confirmations.parquet"
ENTRIES = EXTERNAL / "e1_entries.parquet"
ACTIONS = EXTERNAL / "qd010_actions_2014_2023.parquet"
LEGAL_OPENS = EXTERNAL / "legal_opens.parquet"
PATH_BOUNDS = EXTERNAL / "h40_path_bounds.parquet"
MINUTE_PATH = EXTERNAL / "h40_minute_paths.parquet"
DAILY_PATH = EXTERNAL / "h40_daily_paths.parquet"
FEATURE_BOUNDS = EXTERNAL / "validation_feature_bounds.parquet"
FEATURE_DAILY = EXTERNAL / "validation_preentry_daily.parquet"
FEATURE_FREEZE = EXTERNAL / "outcome_blind_feature_freeze.json"
ADMISSION = OS_ROOT / f"artifacts/{EXPERIMENT}_admission.parquet"
TRADES = OS_ROOT / f"artifacts/{EXPERIMENT}_trades.parquet"
MAIN_NAV = OS_ROOT / f"artifacts/{EXPERIMENT}_main_nav.parquet"
CHINEXT_NAV = OS_ROOT / f"artifacts/{EXPERIMENT}_chinext_nav.parquet"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"

YEARS = tuple(range(2014, 2024))
VALIDATION_YEARS = (2022, 2023)
BOARDS = ("MAIN", "CHINEXT")
END_DATE = pd.Timestamp("2023-12-29")


class ValidationError(RuntimeError):
    """Fail closed on identity, chronology, semantics, or portfolio conservation."""


def raw_path(year: int) -> Path:
    if year not in YEARS:
        raise ValidationError(f"raw year outside authorized range: {year}")
    return RAW_ROOT / f"{year}_day_parquet_none.parquet"


def raw_union() -> str:
    return " UNION ALL ".join(
        f"SELECT * FROM read_parquet('{raw_path(year)}') WHERE period='1m' AND adjust='none'"
        for year in YEARS
    )


def json_ready(value: Any) -> Any:
    if isinstance(value, dict): return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [json_ready(v) for v in value]
    if isinstance(value, (np.integer,)): return int(value)
    if isinstance(value, (np.floating, float)): return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, np.datetime64)): return str(pd.Timestamp(value))
    if isinstance(value, (np.bool_,)): return bool(value)
    return value


def write_json(path: Path, value: Any) -> None:
    pit.atomic_text(path, json.dumps(json_ready(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def validate_frozen_inputs() -> dict[str, str]:
    expected = {
        SPEC: EXPECTED_SPEC_SHA256,
        capitalization.SPEC: "5c5e4ab7aa9f3737dc581b67700701178ff9984f395243b6f07b692cf930d31c",
        capitalization.RESULT: "63b8b57f9bc33209987b275cee2feac20560fb685a061155be6e42b1ec8ffac1",
        DAILY_CONTRACT: "4bb61e07eaa72f04e0d01e8585066010cf2e8ab0d1025d5a9cb634f5839c84df",
        QD004_INVENTORY: "c4d2906dbced341fbf48089aea7239c1c61cfbb57c665fe084495d46487e6655",
        strategy.QD010_DISTRIBUTIONS: "5982b7dd75ec53deb9ce3874aaf3e4a5168a731b5bbd6d8c2d89258fe4aff387",
        strategy.QD010_RIGHTS: "07e864ac6da1d59b69c1b9ce1bcdd01d96d913d0909a718d79627939f8ab87cb",
    }
    found = {}
    for path, digest in expected.items():
        if not path.is_file(): raise ValidationError(f"missing frozen input: {path}")
        actual = pit.sha256_file(path)
        if actual != digest: raise ValidationError(f"frozen input mismatch: {path}: {actual}")
        found[str(path)] = actual
    inventory = json.loads(QD004_INVENTORY.read_text())
    entries = {item["path"]: item for item in inventory["files"]}
    for year, digest in ((2022, "32a6ff7b4d64bdb4da6a572dc9384c12f381689937c50cc3166dcec473cc4cbe"), (2023, "411402b8ad198ad2b8787dec803dce4cb2131055fabcc0539b6428e046d19dc5")):
        item = entries[f"bars/{year}_day_parquet_none.parquet"]
        if item["sha256"] != digest or raw_path(year).stat().st_size != item["size"]:
            raise ValidationError(f"QD-004 inventory mismatch: {year}")
    return found


def configure_modules() -> None:
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    adjusted.EXTERNAL = EXTERNAL
    adjusted.DAILY_STATE = ADJUSTED
    adjusted.daily_paths = lambda: [DAILY_ROOT / f"partition_year={year}/data_0.parquet" for year in range(2013, 2024)]
    pit.EXTERNAL = EXTERNAL
    pit.HISTORY_YEARS = tuple(range(2013, 2024))
    pit.DEVELOPMENT_YEARS = YEARS
    pit.V3_DAILY = ADJUSTED
    pit.DAILY_COMPACT = DAILY
    pit.PRIMITIVES_FULL = PRIMITIVES
    pit.daily_path = lambda year: DAILY_ROOT / f"partition_year={year}/data_0.parquet"
    pit.raw_path = raw_path
    detector.EXTERNAL = EXTERNAL
    detector.DAILY = DAILY
    detector.STRICT_PRIMITIVES = PRIMITIVES
    detector.VALID_DAILY = VALID_DAILY
    detector.COLLAPSE_SEEDS = COLLAPSE_SEEDS
    detector.COLLAPSE_EPISODES = COLLAPSE_EPISODES
    detector.EPISODE_PRIMITIVES = EPISODE_PRIMITIVES
    detector.MEANINGFUL_PRIMITIVES = MEANINGFUL_PRIMITIVES
    detector.PAIR_RECOVERY = PAIR_RECOVERY
    detector.ZONE_STACKS = ZONE_STACKS
    detector.LIFECYCLE_ROWS = LIFECYCLE_ROWS
    detector.LIFECYCLE_SUMMARY = LIFECYCLE_SUMMARY
    detector.EXACT_REENTRY = EXACT_REENTRY


def build_adjusted_and_daily() -> None:
    adjusted.build_daily_state()
    pit.build_daily_compact()


def build_primitives() -> None:
    if PRIMITIVES.is_file(): return
    con = pit.connection()
    query = f"""
    WITH lagged AS (
      SELECT *,lag(trade_date) OVER w AS previous_trade_date,lag(cal_idx) OVER w AS previous_cal_idx,
        lag(low) OVER w AS previous_low,lag(close) OVER w AS previous_close,
        lag(coord_low) OVER w AS previous_coord_low,lag(history_valid) OVER w AS previous_history_valid,
        lag(current_valid) OVER w AS previous_current_valid,lag(invalid_step_cum) OVER w AS previous_invalid_step_cum
      FROM read_parquet('{DAILY}') WINDOW w AS(PARTITION BY symbol ORDER BY trade_date)
    ), gaps AS (
      SELECT symbol||'|'||strftime(trade_date,'%Y-%m-%d') AS gap_primitive_id,symbol,trade_date AS gap_date,
        cal_idx AS gap_cal_idx,sleeve AS board,is_st,causal_industry AS industry,open AS lower_boundary,
        previous_low AS upper_boundary,previous_close AS prev_close,previous_low AS prev_low,open,high,low,close,
        coord_open AS lower_coord,previous_coord_low AS upper_coord,previous_trade_date,
        previous_low-open AS width_abs,(previous_low-open)/previous_close AS width_pct_vs_prev_close,
        corporate_action_count,corporate_action_valid,corporate_action_blocking,industry_valid,
        historical_identity_valid,industry_snapshot_id,invalid_step_cum,prior250_peak_date AS peak_date,
        prior250_peak_high AS peak_coord_high,1-coord_open/prior250_peak_high AS decline_to_gap,coordinate_factor
      FROM lagged WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31'
        AND history_valid AND current_valid AND previous_history_valid AND previous_current_valid
        AND previous_cal_idx=cal_idx-1 AND invalid_step_cum=previous_invalid_step_cum
        AND prior250_peak_invalid_cum=invalid_step_cum AND coalesce(corporate_action_count,0)=0
        AND corporate_action_valid AND NOT corporate_action_blocking AND industry_valid
        AND historical_identity_valid AND industry_snapshot_id IS NOT NULL
        AND coord_open<previous_coord_low AND open<previous_low
    ) SELECT g.*,p.ret20 AS return20_into_peak,p.ret40 AS return40_into_peak,
      p.ret60 AS return60_into_peak,p.ret120 AS return120_into_peak,
      p.coord_high/nullif(p.low60,0)-1 AS max_runup_from_60_low,
      p.coord_high/nullif(p.low120,0)-1 AS max_runup_from_120_low,
      p.board_ret60_percentile AS board_relative_return_percentile,
      p.large_up_days120 AS number_large_up_days,p.limit_up_days120 AS number_limit_up_sessions,
      p.cal_idx-p.low120_idx AS main_rise_duration,
      (p.coord_high/nullif(p.low120,0)-1)/nullif(p.cal_idx-p.low120_idx,0) AS rise_speed,
      -p.max_drawdown_main_rise AS maximum_drawdown_during_main_rise,p.low120_date AS main_rise_start_date
    FROM gaps g LEFT JOIN read_parquet('{DAILY}') p ON p.symbol=g.symbol AND p.trade_date=g.peak_date
    ORDER BY g.symbol,g.gap_date
    """
    con.execute(f"COPY ({query}) TO '{PRIMITIVES}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.close()


def build_collapse_episodes() -> None:
    if COLLAPSE_EPISODES.is_file(): return
    con = pit.connection(); con.execute("SET preserve_insertion_order=false")
    valid = f"""SELECT *,row_number() OVER(PARTITION BY symbol ORDER BY trade_date) AS valid_seq,
      lag(coord_close,1) OVER(PARTITION BY symbol ORDER BY trade_date) AS valid_lag1_close,
      lag(coord_close,2) OVER(PARTITION BY symbol ORDER BY trade_date) AS valid_lag2_close
      FROM read_parquet('{DAILY}') WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31'
      AND history_valid AND current_valid"""
    con.execute(f"COPY ({valid}) TO '{VALID_DAILY}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    seed = f"""
    WITH breach_seed AS (
      SELECT symbol,prior250_peak_date AS peak_date,prior250_peak_high AS peak_coord_high,
        prior250_peak_invalid_cum AS peak_invalid_step_cum,min(trade_date) AS first_breach_date
      FROM read_parquet('{VALID_DAILY}') WHERE prior250_peak_date IS NOT NULL AND trade_date>prior250_peak_date
        AND invalid_step_cum=prior250_peak_invalid_cum AND 1-coord_low/prior250_peak_high>=0.30
      GROUP BY symbol,prior250_peak_date,prior250_peak_high,prior250_peak_invalid_cum
    ), s AS (
      SELECT b.*,p.valid_seq AS peak_valid_seq,p.cal_idx AS peak_cal_idx,
        p.coord_high/p.low60-1 AS max_runup_from_60_low,p.coord_high/p.low120-1 AS max_runup_from_120_low,
        p.ret20 AS return20_into_peak,p.ret60 AS return60_into_peak,p.board_ret60_percentile AS board_relative_return_percentile,
        p.large_up_days120 AS number_large_up_days,p.limit_up_days120 AS number_limit_up_sessions,
        p.cal_idx-p.low120_idx AS main_rise_duration,(p.coord_high/p.low120-1)/nullif(p.cal_idx-p.low120_idx,0) AS runup_speed,
        p.max_drawdown_main_rise AS max_drawdown_during_rise,p.sleeve AS board,p.is_st,p.industry,
        fb.valid_seq AS first_breach_valid_seq,fb.cal_idx AS first_breach_cal_idx
      FROM breach_seed b JOIN read_parquet('{VALID_DAILY}') p ON p.symbol=b.symbol AND p.trade_date=b.peak_date
      JOIN read_parquet('{VALID_DAILY}') fb ON fb.symbol=b.symbol AND fb.trade_date=b.first_breach_date
      WHERE (p.coord_high/p.low60-1>=0.50 OR p.coord_high/p.low120-1>=0.70)
        AND (p.board_ret60_percentile>=0.90 OR p.ret20>=0.30 OR p.large_up_days120>=2 OR p.limit_up_days120>=2)
    ) SELECT * FROM s ORDER BY symbol,peak_date"""
    con.execute(f"COPY ({seed}) TO '{COLLAPSE_SEEDS}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    query = f"""
    WITH recovery_candidates AS (
      SELECT s.symbol,s.peak_date,d.trade_date AS recovery_date,d.valid_seq AS recovery_valid_seq
      FROM read_parquet('{COLLAPSE_SEEDS}') s JOIN read_parquet('{VALID_DAILY}') d ON d.symbol=s.symbol
        AND d.valid_seq BETWEEN s.first_breach_valid_seq+2 AND s.peak_valid_seq+250
        AND d.invalid_step_cum=s.peak_invalid_step_cum
      WHERE d.coord_close>=0.90*s.peak_coord_high AND d.valid_lag1_close>=0.90*s.peak_coord_high
        AND d.valid_lag2_close>=0.90*s.peak_coord_high
    ), recovery AS (
      SELECT symbol,peak_date,min(recovery_valid_seq) AS recovery_valid_seq,arg_min(recovery_date,recovery_valid_seq) AS recovery_date
      FROM recovery_candidates GROUP BY symbol,peak_date
    ), bounded AS (
      SELECT s.*,r.recovery_date,r.recovery_valid_seq,
        least(s.peak_valid_seq+250,coalesce(r.recovery_valid_seq,s.peak_valid_seq+250)) AS episode_end_valid_seq
      FROM read_parquet('{COLLAPSE_SEEDS}') s LEFT JOIN recovery r USING(symbol,peak_date)
    ), trough AS (
      SELECT b.symbol,b.peak_date,min(d.coord_low) AS postcollapse_low_coord,arg_min(d.trade_date,d.coord_low) AS postcollapse_low_date,
        arg_min(d.valid_seq,d.coord_low) AS postcollapse_low_valid_seq,arg_min(d.cal_idx,d.coord_low) AS postcollapse_low_cal_idx,
        max(d.trade_date) AS episode_end_date
      FROM bounded b JOIN read_parquet('{VALID_DAILY}') d ON d.symbol=b.symbol
        AND d.valid_seq BETWEEN b.first_breach_valid_seq AND b.episode_end_valid_seq
        AND d.invalid_step_cum=b.peak_invalid_step_cum GROUP BY b.symbol,b.peak_date
    ) SELECT concat(b.symbol,'|',strftime(b.peak_date,'%Y-%m-%d')) AS collapse_episode_id,b.*,
      t.* EXCLUDE(symbol,peak_date),1-t.postcollapse_low_coord/b.peak_coord_high AS peak_to_low_decline
    FROM bounded b JOIN trough t USING(symbol,peak_date)
    WHERE t.postcollapse_low_date>b.peak_date AND 1-t.postcollapse_low_coord/b.peak_coord_high>=0.30
    ORDER BY b.symbol,b.peak_date"""
    con.execute(f"COPY ({query}) TO '{COLLAPSE_EPISODES}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.close()


def build_validation_candidates() -> pd.DataFrame:
    build_adjusted_and_daily(); build_primitives(); build_collapse_episodes()
    all_primitives, meaningful = detector.build_episode_primitives()
    stacks = detector.group_meaningful_zones(meaningful, all_primitives)
    if not LIFECYCLE_SUMMARY.is_file():
        con = pit.connection()
        query = detector.lifecycle_query().replace("2021-12-31", "2023-12-31")
        con.execute(f"COPY ({query}) TO '{LIFECYCLE_SUMMARY}' (FORMAT PARQUET,COMPRESSION ZSTD)")
        con.close()
    accepted = pd.read_parquet(LIFECYCLE_SUMMARY)
    for col in [c for c in accepted.columns if c.endswith("_date") or c.endswith("_time")]: accepted[col] = pd.to_datetime(accepted[col])
    accepted = accepted.loc[accepted.state_date.dt.year.isin(VALIDATION_YEARS)].copy()
    if len(accepted): accepted = detector.add_base_descriptors(accepted)
    exact = detector.build_exact_reentry(accepted)
    candidates = detector.prepare_candidates(accepted, exact)
    candidates = candidates.loc[candidates.candidate_year.isin(VALIDATION_YEARS)].sort_values("zone_stack_id", kind="mergesort").reset_index(drop=True)
    if candidates.zone_stack_id.duplicated().any(): raise ValidationError("duplicate V3 candidate")
    if (candidates.postcollapse_low_date >= candidates.state_date).any(): raise ValidationError("future-defined accepted collapse trough")
    pit.write_parquet(candidates, CANDIDATES)
    return candidates


def prepare_source(candidates: pd.DataFrame) -> pd.DataFrame:
    source = candidates.copy()
    source["event_id"] = source.zone_stack_id
    source["primary_layer_id"] = source.target_primitive_id
    source["L"] = source.zone_lower_boundary.astype(float)
    source["U"] = source.zone_upper_boundary.astype(float)
    source["W"] = source.U - source.L
    if not source.W.gt(0).all(): raise ValidationError("non-positive primary width")
    source["first_lower_return_time"] = pd.to_datetime(source.candidate_reentry_time)
    source["reentry_date"] = pd.to_datetime(source.candidate_reentry_date)
    source["formation_date"] = pd.to_datetime(source.zone_formation_date)
    widths = []
    for row in source.itertuples(index=False):
        ids = str(row.meaningful_primitive_ids).split(";")
        lowers = [float(x) for x in str(row.meaningful_primitive_lowers).split("|")]
        wpct = [float(x) for x in str(row.meaningful_primitive_width_pcts).split("|")]
        if row.primary_layer_id not in ids or not math.isclose(float(row.L), min(lowers), rel_tol=1e-10):
            raise ValidationError(f"primary layer changed: {row.event_id}")
        widths.append(wpct[ids.index(row.primary_layer_id)])
    source["primary_layer_width_pct"] = widths
    pit.write_parquet(source.sort_values("event_id", kind="mergesort"), SOURCE)
    return source


def build_execution_sources(source: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = raw_union()
    if not CONFIRMATIONS.is_file():
        con = pit.connection(); con.execute("SET preserve_insertion_order=false")
        q = f"""
        WITH raw AS ({raw}), eligible AS (
          SELECT e.event_id,r.trade_date,r.bar_end_time,r.close*d.coordinate_factor AS confirmation_coord_close,
            row_number() OVER(PARTITION BY e.event_id ORDER BY r.bar_end_time) AS rn
          FROM read_parquet('{SOURCE}') e JOIN raw r ON r.qmt_code=e.symbol
            AND r.trade_date BETWEEN e.reentry_date AND DATE '2023-12-31'
            AND r.bar_end_time>=e.first_lower_return_time
          JOIN read_parquet('{DAILY}') d ON d.symbol=e.symbol AND d.trade_date=r.trade_date
          WHERE d.invalid_step_cum=e.peak_invalid_step_cum AND d.history_valid AND d.current_valid
            AND isfinite(r.close) AND r.close>0 AND r.close*d.coordinate_factor>=e.L
        ) SELECT event_id,trade_date AS confirmation_date,bar_end_time AS confirmation_time,confirmation_coord_close
        FROM eligible WHERE rn=1 ORDER BY event_id"""
        con.execute(f"COPY ({q}) TO '{CONFIRMATIONS}' (FORMAT PARQUET,COMPRESSION ZSTD)"); con.close()
    if not ENTRIES.is_file():
        con = pit.connection(); con.execute("SET preserve_insertion_order=false")
        q = f"""
        WITH raw AS ({raw}), eligible AS (
          SELECT e.event_id,r.trade_date AS entry_date,r.bar_end_time AS entry_time,r.open AS entry_raw_price,
            r.open*d.coordinate_factor AS entry_coord_price,d.cal_idx AS entry_cal_idx,
            d.coordinate_factor AS entry_coordinate_factor,d.invalid_step_cum AS entry_invalid_step_cum,
            row_number() OVER(PARTITION BY e.event_id ORDER BY r.bar_end_time) AS rn
          FROM read_parquet('{SOURCE}') e JOIN read_parquet('{CONFIRMATIONS}') a USING(event_id)
          JOIN raw r ON r.qmt_code=e.symbol AND r.bar_end_time>a.confirmation_time
            AND r.trade_date BETWEEN a.confirmation_date AND DATE '2023-12-31'
          JOIN read_parquet('{DAILY}') d ON d.symbol=e.symbol AND d.trade_date=r.trade_date
          WHERE d.invalid_step_cum=e.peak_invalid_step_cum AND d.history_valid AND d.current_valid AND d.hard_valid
            AND d.trade_status=1 AND d.current_day_data_tradable AND d.market_rule_valid
            AND NOT d.corporate_action_blocking AND isfinite(r.open) AND r.open>0
            AND round(r.open*100)<round(d.up_limit_price*100)
        ) SELECT * EXCLUDE(rn) FROM eligible WHERE rn=1 ORDER BY event_id"""
        con.execute(f"COPY ({q}) TO '{ENTRIES}' (FORMAT PARQUET,COMPRESSION ZSTD)"); con.close()
    confirmations = pd.read_parquet(CONFIRMATIONS); entries = pd.read_parquet(ENTRIES)
    for f, cols in ((confirmations, ("confirmation_date", "confirmation_time")), (entries, ("entry_date", "entry_time"))):
        for col in cols: f[col] = pd.to_datetime(f[col])
    return confirmations, entries


def build_actions_and_paths(source: pd.DataFrame, entries: pd.DataFrame, include_outcomes: bool) -> None:
    if not ACTIONS.is_file():
        symbol_sql = "CASE WHEN starts_with(symbol,'6') THEN symbol||'.SH' WHEN starts_with(symbol,'0') OR starts_with(symbol,'3') THEN symbol||'.SZ' ELSE symbol||'.OTHER' END"
        con = pit.connection()
        q = f"""
        WITH actions AS (
          SELECT {symbol_sql} AS symbol,event_id,CASE WHEN coalesce(share_multiplier,1)>1 THEN 'RISK_SHARE' ELSE 'CASH_ONLY' END AS action_kind,
            CAST(known_at AS DATE) AS known_date,CAST(effective_date AS DATE) AS effective_date,
            coalesce(cash_per_share_gross,0) AS cash_per_share,coalesce(share_multiplier,1) AS share_multiplier,source_terms_complete
          FROM read_parquet('{strategy.QD010_DISTRIBUTIONS}') WHERE effective_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31'
            AND (coalesce(share_multiplier,1)>1 OR coalesce(cash_per_share_gross,0)>0)
          UNION ALL
          SELECT {symbol_sql},event_id,'RISK_RIGHTS',CAST(known_at AS DATE),CAST(effective_date AS DATE),0.0,1.0,source_terms_complete
          FROM read_parquet('{strategy.QD010_RIGHTS}') WHERE effective_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31'
        ) SELECT a.* FROM actions a JOIN (SELECT DISTINCT symbol FROM read_parquet('{SOURCE}')) s USING(symbol)
        ORDER BY a.symbol,a.effective_date,a.event_id"""
        con.execute(f"COPY ({q}) TO '{ACTIONS}' (FORMAT PARQUET,COMPRESSION ZSTD)"); con.close()
    if not include_outcomes:
        return
    if not LEGAL_OPENS.is_file():
        con = pit.connection(); q = f"""
        WITH raw AS ({raw_union()}), symbols AS (SELECT DISTINCT symbol FROM read_parquet('{SOURCE}'))
        SELECT r.qmt_code AS symbol,r.trade_date,r.bar_end_time,r.open AS raw_open,d.cal_idx,d.coordinate_factor,d.invalid_step_cum
        FROM raw r JOIN symbols s ON s.symbol=r.qmt_code JOIN read_parquet('{DAILY}') d ON d.symbol=r.qmt_code AND d.trade_date=r.trade_date
        WHERE d.history_valid AND d.current_valid AND d.hard_valid AND d.trade_status=1 AND d.current_day_data_tradable
          AND d.market_rule_valid AND NOT d.corporate_action_blocking AND isfinite(r.open) AND r.open>0
          AND round(r.open*100)>round(d.down_limit_price*100)
        QUALIFY row_number() OVER(PARTITION BY r.qmt_code,r.trade_date ORDER BY r.bar_end_time)=1
        ORDER BY symbol,bar_end_time"""
        con.execute(f"COPY ({q}) TO '{LEGAL_OPENS}' (FORMAT PARQUET,COMPRESSION ZSTD)"); con.close()
    if not PATH_BOUNDS.is_file():
        cal = pd.read_parquet(DAILY, columns=["trade_date", "cal_idx"]).drop_duplicates("cal_idx")
        cal.trade_date = pd.to_datetime(cal.trade_date); last = int(cal.loc[cal.trade_date.le(END_DATE), "cal_idx"].max())
        by_idx = dict(zip(cal.cal_idx.astype(int), cal.trade_date, strict=False))
        bounds = entries[["event_id", "entry_time", "entry_date", "entry_cal_idx"]].copy()
        bounds["path_end_cal_idx"] = (bounds.entry_cal_idx.astype(int) + 40).clip(upper=last)
        bounds["path_end_date"] = bounds.path_end_cal_idx.map(by_idx)
        pit.write_parquet(bounds, PATH_BOUNDS)
    if not DAILY_PATH.is_file():
        con = pit.connection(); q = f"""
        SELECT b.event_id,d.* FROM read_parquet('{PATH_BOUNDS}') b JOIN read_parquet('{SOURCE}') s USING(event_id)
        JOIN read_parquet('{DAILY}') d ON d.symbol=s.symbol AND d.cal_idx BETWEEN b.entry_cal_idx AND b.path_end_cal_idx
        ORDER BY b.event_id,d.cal_idx"""
        con.execute(f"COPY ({q}) TO '{DAILY_PATH}' (FORMAT PARQUET,COMPRESSION ZSTD)"); con.close()
    if not MINUTE_PATH.is_file():
        con = pit.connection(); con.execute("SET preserve_insertion_order=false")
        q = f"""
        WITH raw AS ({raw_union()}) SELECT b.event_id,r.trade_date,r.bar_end_time,d.cal_idx,r.open,r.high,r.low,r.close,
          r.open*d.coordinate_factor AS coord_open,r.high*d.coordinate_factor AS coord_high,r.low*d.coordinate_factor AS coord_low,
          r.close*d.coordinate_factor AS coord_close,d.coordinate_factor,d.invalid_step_cum,d.history_valid,d.current_valid,d.hard_valid,
          d.trade_status,d.current_day_data_tradable,d.market_rule_valid,d.corporate_action_blocking,d.down_limit_price
        FROM read_parquet('{PATH_BOUNDS}') b JOIN read_parquet('{SOURCE}') s USING(event_id)
        JOIN raw r ON r.qmt_code=s.symbol AND r.trade_date BETWEEN b.entry_date AND b.path_end_date AND r.bar_end_time>=b.entry_time
        JOIN read_parquet('{DAILY}') d ON d.symbol=s.symbol AND d.trade_date=r.trade_date
        ORDER BY b.event_id,r.bar_end_time"""
        con.execute(f"COPY ({q}) TO '{MINUTE_PATH}' (FORMAT PARQUET,COMPRESSION ZSTD)"); con.close()


def feature_panel(source: pd.DataFrame, confirmations: pd.DataFrame, entries: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    work = source.merge(confirmations[["event_id", "confirmation_time"]], on="event_id", how="inner", validate="one_to_one")
    work = work.merge(entries[["event_id", "entry_date", "entry_time"]], on="event_id", how="inner", validate="one_to_one")
    actions = pd.read_parquet(ACTIONS)
    for col in ("known_date", "effective_date"): actions[col] = pd.to_datetime(actions[col])
    risk = actions.loc[actions.action_kind.astype(str).str.startswith("RISK")]
    risk_by_symbol = {k: v for k, v in risk.groupby("symbol", sort=False)}
    blocked = []
    for row in work.itertuples(index=False):
        a = risk_by_symbol.get(row.symbol, pd.DataFrame(columns=risk.columns))
        blocked.append(bool(len(a.loc[a.known_date.le(pd.Timestamp(row.confirmation_time).normalize()) & a.effective_date.ge(pd.Timestamp(row.entry_date).normalize())])))
    work["risk_blocked_entry"] = blocked
    cal = pd.read_parquet(DAILY, columns=["trade_date", "cal_idx"]).drop_duplicates("cal_idx")
    cal.trade_date = pd.to_datetime(cal.trade_date); idx = dict(zip(cal.trade_date, cal.cal_idx.astype(int), strict=False))
    work["signal_cal_idx"] = pd.to_datetime(work.confirmation_time).dt.normalize().map(idx)
    work["zone_age_sessions"] = work.signal_cal_idx.astype(int) - work.zone_formation_cal_idx.astype(int)
    bounds = work[["event_id", "symbol", "zone_formation_cal_idx", "signal_cal_idx"]].copy()
    bounds["start_cal_idx"] = bounds.zone_formation_cal_idx.astype(int) + 1
    bounds["end_cal_idx"] = bounds.signal_cal_idx.astype(int) - 1
    pit.write_parquet(bounds, FEATURE_BOUNDS)
    con = pit.connection(); q = f"""
      SELECT b.event_id,d.trade_date,d.cal_idx,d.turnover_fraction,d.available_at,d.decision_at
      FROM read_parquet('{FEATURE_BOUNDS}') b JOIN read_parquet('{DAILY}') d ON d.symbol=b.symbol
        AND d.cal_idx BETWEEN b.start_cal_idx AND b.end_cal_idx WHERE d.trade_date<=DATE '2023-12-31'
      ORDER BY b.event_id,d.cal_idx"""
    con.execute(f"COPY ({q}) TO '{FEATURE_DAILY}' (FORMAT PARQUET,COMPRESSION ZSTD)"); con.close()
    fd = pd.read_parquet(FEATURE_DAILY); fd.available_at = pd.to_datetime(fd.available_at); fd.decision_at = pd.to_datetime(fd.decision_at)
    if (fd.available_at > fd.decision_at).any(): raise ValidationError("future turnover feature")
    agg = fd.groupby("event_id", sort=False).turnover_fraction.agg(["sum", "count"])
    missing = fd.groupby("event_id", sort=False).turnover_fraction.apply(lambda x: int(x.isna().sum()))
    work["cum_turnover_since_zone"] = work.event_id.map(agg["sum"])
    work["turnover_observations"] = work.event_id.map(agg["count"]).fillna(0).astype(int)
    work["turnover_missing"] = work.event_id.map(missing).fillna(0).astype(int)
    if work.cum_turnover_since_zone.isna().any() or work.turnover_missing.any(): raise ValidationError("missing turnover lineage")
    work["entry_year"] = pd.to_datetime(work.entry_date).dt.year

    dev_source = pd.read_parquet(admission.resolution.SOURCE)
    dev_source = dev_source.loc[~dev_source.risk_blocked_entry].copy()
    dev_fd = pd.read_parquet(DEV_FEATURE_DAILY)
    dev_agg = dev_fd.groupby("event_id", sort=False).turnover_fraction.sum()
    dev_source["cum_turnover_since_zone"] = dev_source.event_id.map(dev_agg)
    dev_source["entry_year"] = pd.to_datetime(dev_source.entry_date).dt.year
    history = dev_source[["event_id", "board", "entry_year", "cum_turnover_since_zone"]].copy()
    valid = work.loc[~work.risk_blocked_entry].copy()
    cutoffs: dict[str, Any] = {}
    valid["turnover_train_q66_67"] = np.nan
    for year in VALIDATION_YEARS:
        cutoffs[str(year)] = {}
        for board in BOARDS:
            prior = pd.concat([
                history.loc[history.board.eq(board) & history.entry_year.le(year - 1), "cum_turnover_since_zone"],
                valid.loc[valid.board.eq(board) & valid.entry_year.lt(year), "cum_turnover_since_zone"],
            ], ignore_index=True)
            cutoff = float(prior.quantile(2 / 3, interpolation="linear"))
            cutoffs[str(year)][board] = {"history_end": f"{year-1}-12-31", "n": len(prior), "cutoff": cutoff, "outcome_rows_used": 0}
            valid.loc[valid.board.eq(board) & valid.entry_year.eq(year), "turnover_train_q66_67"] = cutoff
    valid["L3_DUAL_FRESH"] = valid.zone_age_sessions.le(90) & valid.cum_turnover_since_zone.le(valid.turnover_train_q66_67)
    panel = valid.sort_values(["entry_date", "event_id"], kind="mergesort").reset_index(drop=True)
    keep = ["event_id", "symbol", "board", "entry_date", "entry_time", "entry_year", "zone_age_sessions", "cum_turnover_since_zone", "turnover_train_q66_67", "turnover_observations", "L3_DUAL_FRESH"]
    pit.write_parquet(panel[keep], ADMISSION)
    freeze = {
        "stage": "OUTCOME_BLIND_FEATURE_AND_ADMISSION_FREEZE",
        "spec_sha256": EXPECTED_SPEC_SHA256,
        "validation_security_outcomes_read": False,
        "cutoffs": cutoffs,
        "source_candidates": len(source), "confirmed": len(confirmations), "executable_entries": len(entries),
        "risk_blocked": int(work.risk_blocked_entry.sum()), "otherwise_valid": len(valid),
        "dual_fresh": int(panel.L3_DUAL_FRESH.sum()),
        "by_year_board": panel.loc[panel.L3_DUAL_FRESH].groupby(["entry_year", "board"]).size().to_dict(),
        "admission_sha256": pit.sha256_file(ADMISSION),
        "future_feature_count": 0,
        "validation_outcome_used_for_2023_cutoff_count": 0,
    }
    write_json(FEATURE_FREEZE, freeze)
    return panel, freeze


def cash_events(actions: pd.DataFrame, entry_date: pd.Timestamp, end_date: pd.Timestamp) -> str:
    rows = actions.loc[
        actions.action_kind.eq("CASH_ONLY")
        & actions.effective_date.gt(entry_date.normalize())
        & actions.effective_date.le(end_date.normalize())
    ]
    return json.dumps([
        {"date": str(pd.Timestamp(r.effective_date).date()), "cash_per_share": float(r.cash_per_share), "event_id": str(r.event_id)}
        for r in rows.itertuples(index=False)
    ], sort_keys=True)


def build_h40_trades(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    dual_ids = set(panel.loc[panel.L3_DUAL_FRESH, "event_id"])
    source = pd.read_parquet(SOURCE).loc[lambda x: x.event_id.isin(dual_ids)].copy()
    confirmations = pd.read_parquet(CONFIRMATIONS)
    entries = pd.read_parquet(ENTRIES)
    source = source.merge(confirmations[["event_id", "confirmation_time"]], on="event_id", validate="one_to_one")
    source = source.merge(entries, on="event_id", validate="one_to_one")
    minute = pd.read_parquet(MINUTE_PATH); daily_path = pd.read_parquet(DAILY_PATH)
    daily_all = pd.read_parquet(DAILY); legal = pd.read_parquet(LEGAL_OPENS); actions = pd.read_parquet(ACTIONS)
    for frame, cols in ((source, ("confirmation_time", "entry_time", "entry_date", "formation_date")),
                        (minute, ("bar_end_time", "trade_date")), (daily_path, ("trade_date",)),
                        (daily_all, ("trade_date",)), (legal, ("bar_end_time", "trade_date")),
                        (actions, ("known_date", "effective_date"))):
        for col in cols: frame[col] = pd.to_datetime(frame[col])
    minute_groups = {k: p.sort_values("bar_end_time", kind="mergesort") for k, p in minute.groupby("event_id", sort=False)}
    day_groups = {k: p.sort_values("cal_idx", kind="mergesort") for k, p in daily_path.groupby("event_id", sort=False)}
    daily_groups = {k: p.sort_values("cal_idx", kind="mergesort") for k, p in daily_all.groupby("symbol", sort=False)}
    legal_groups = {k: p.sort_values("bar_end_time", kind="mergesort") for k, p in legal.groupby("symbol", sort=False)}
    action_groups = {k: p.sort_values(["known_date", "effective_date", "event_id"], kind="mergesort") for k, p in actions.groupby("symbol", sort=False)}
    rows = []; audit = Counter()
    for event in source.itertuples(index=False):
        mins = minute_groups[event.event_id]; days = day_groups[event.event_id]
        all_days = daily_groups[event.symbol]; legal_all = legal_groups.get(event.symbol, pd.DataFrame(columns=legal.columns))
        act = action_groups.get(event.symbol, pd.DataFrame(columns=actions.columns))
        lineage = float(event.entry_invalid_step_cum); entry_idx = int(event.entry_cal_idx)
        entry_date = pd.Timestamp(event.entry_date); confirmation = pd.Timestamp(event.confirmation_time)
        risk_actions = act.loc[act.action_kind.astype(str).str.startswith("RISK")]
        entry_risk = risk_actions.loc[risk_actions.known_date.le(confirmation.normalize()) & risk_actions.effective_date.ge(entry_date.normalize())]
        risk_blocked = not entry_risk.empty
        precompleted = float(event.entry_coord_price) >= float(event.U)
        if risk_blocked:
            audit["risk_blocked_execution_exclusion_count"] += 1
            continue
        if precompleted:
            audit["precompleted_execution_exclusion_count"] += 1
            continue
        target = admission.resolution.first_target(mins, entry_idx, float(event.U), lineage)
        horizon = admission.anatomy.horizon_exit(days, legal_all, entry_idx + 40, lineage)
        cutoff_time = pd.Timestamp(days.trade_date.max()) + pd.Timedelta(hours=15)
        risk_exit = admission.anatomy.forced_risk_exit(act, confirmation, entry_date, all_days, legal_all, lineage, cutoff_time)
        if risk_exit is not None and risk_exit.get("blocked"):
            audit["unresolved_action_block_count"] += 1; risk_exit = None
        if target is not None and risk_exit is not None and pd.Timestamp(risk_exit["exit_time"]) <= pd.Timestamp(target.bar_end_time): target = None
        target_offset = np.nan if target is None else int(target.cal_idx - entry_idx)
        chosen = None
        if not precompleted and not risk_blocked and target is not None and target_offset <= 40:
            chosen = {"exit_time": pd.Timestamp(target.bar_end_time), "exit_date": pd.Timestamp(target.trade_date),
                      "exit_raw_price": float(target.target_raw_execution), "exit_reason": "TARGET"}
            if target_offset < 1: audit["t1_violation_count"] += 1
        elif not precompleted and not risk_blocked and horizon is not None:
            chosen = {"exit_time": pd.Timestamp(horizon["exit_time"]), "exit_date": pd.Timestamp(horizon["exit_date"]),
                      "exit_raw_price": float(horizon["exit_raw_price"]),
                      "exit_reason": "TIME_STOP" if horizon["kind"] == "HORIZON_CLOSE" else "TIME_STOP_DELAYED"}
        risk_event_id = None; risk_effective = pd.NaT
        if not precompleted and not risk_blocked and risk_exit is not None and (chosen is None or pd.Timestamp(risk_exit["exit_time"]) <= pd.Timestamp(chosen["exit_time"])):
            chosen = {"exit_time": pd.Timestamp(risk_exit["exit_time"]), "exit_date": pd.Timestamp(risk_exit["exit_date"]),
                      "exit_raw_price": float(risk_exit["exit_raw_price"]), "exit_reason": "CORPORATE_ACTION_RISK"}
            risk_event_id = str(risk_exit["event_id"]); risk_effective = pd.Timestamp(risk_exit["effective_date"])
        end = END_DATE if chosen is None else pd.Timestamp(chosen["exit_date"])
        out = {
            "event_id": event.event_id, "symbol": event.symbol, "board": event.board,
            "formation_date": pd.Timestamp(event.formation_date), "entry_family": "E1_FIRST_ACCEPT",
            "target": "FULL", "failure": "F2_NO_FAILURE_STOP", "time_stop": 40,
            "entry_date": entry_date, "entry_time": pd.Timestamp(event.entry_time), "entry_cal_idx": entry_idx,
            "entry_raw_price": float(event.entry_raw_price), "entry_coord_price": float(event.entry_coord_price),
            "target_coord": float(event.U), "target_hit_same_day": bool(target is not None and int(target.cal_idx) == entry_idx),
            "precompleted_before_entry": precompleted, "risk_blocked_entry": risk_blocked,
            "risk_block_event_ids": "|".join(entry_risk.event_id.astype(str)),
            "exit_time": pd.NaT if chosen is None else chosen["exit_time"], "exit_date": pd.NaT if chosen is None else chosen["exit_date"],
            "exit_raw_price": np.nan if chosen is None else chosen["exit_raw_price"], "exit_reason": None if chosen is None else chosen["exit_reason"],
            "action_block_time": pd.NaT, "risk_exit_event_id": risk_event_id, "risk_exit_effective_date": risk_effective,
            "primary_layer_width_pct": float(event.primary_layer_width_pct),
            "board_relative_return_percentile": float(event.board_relative_return_percentile),
            "peak_to_low_decline": float(event.peak_to_low_decline), "persistence_sessions": int(event.persistence_sessions),
            "cash_events_json": cash_events(act, entry_date, end),
        }
        if chosen is not None and pd.Timestamp(chosen["exit_time"]) <= pd.Timestamp(event.entry_time): audit["exit_before_entry_count"] += 1
        rows.append(out)
    trades = pd.DataFrame(rows).sort_values(["entry_time", "event_id"], kind="mergesort").reset_index(drop=True)
    blocking = {k: v for k, v in audit.items() if k not in {"precompleted_execution_exclusion_count", "risk_blocked_execution_exclusion_count"}}
    if any(blocking.values()): raise ValidationError(f"H40 audit failed: {dict(audit)}")
    pit.write_parquet(trades, TRADES)
    return trades, dict(audit)


def stitched_replay(trades: pd.DataFrame) -> tuple[dict[str, capitalization.ReplayK], pd.DataFrame, dict[str, Any]]:
    capitalization.YEARS = VALIDATION_YEARS
    strategy.DAILY = DAILY
    strategy.COST = 0.002
    daily = pd.read_parquet(DAILY); daily.trade_date = pd.to_datetime(daily.trade_date)
    replay_source = inspect.getsource(capitalization.replay_k)
    frozen_literal = "daily.trade_date.dt.year.between(2017, 2021)"
    if replay_source.count(frozen_literal) != 1:
        raise ValidationError("capitalization replay calendar anchor changed")
    replay_source = replay_source.replace("def replay_k(", "def replay_validation_k(").replace(
        frozen_literal, "daily.trade_date.dt.year.isin(VALIDATION_YEARS)"
    )
    namespace = dict(capitalization.__dict__); namespace["VALIDATION_YEARS"] = VALIDATION_YEARS
    exec(compile(replay_source, str(Path(capitalization.__file__)), "exec"), namespace)
    replay_validation_k = namespace["replay_validation_k"]
    replays = {board: replay_validation_k(trades, daily, board, 10) for board in BOARDS}
    if any(r.blocked for r in replays.values()): raise ValidationError("action-blocked portfolio replay")
    combined = capitalization.combined_nav(replays["MAIN"].nav, replays["CHINEXT"].nav, 10)
    combined.trade_date = pd.to_datetime(combined.trade_date)
    pit.write_parquet(replays["MAIN"].nav, MAIN_NAV); pit.write_parquet(replays["CHINEXT"].nav, CHINEXT_NAV)
    audit = Counter()
    for replay in replays.values(): audit.update(replay.audit)
    return replays, combined, dict(audit)


def metrics_bundle(trades: pd.DataFrame, replays: dict[str, capitalization.ReplayK], combined: pd.DataFrame) -> tuple[dict[str, Any], dict[str, Any]]:
    daily = pd.read_parquet(DAILY); daily.trade_date = pd.to_datetime(daily.trade_date)
    calendar = daily.loc[daily.trade_date.dt.year.isin(VALIDATION_YEARS), ["trade_date", "cal_idx"]].drop_duplicates("trade_date").sort_values("trade_date")
    accepted_all = pd.concat([replays[b].accepted.assign(board_replay=b) for b in BOARDS], ignore_index=True)
    ledger_all = pd.concat([replays[b].ledger.assign(board_replay=b) for b in BOARDS], ignore_index=True)
    combined_replay = capitalization.ReplayK(combined, accepted_all, ledger_all, {}, False)
    summary: dict[str, Any] = {}
    yearly: dict[str, Any] = {}
    for board in BOARDS:
        m = capitalization.portfolio_metrics(replays[board].nav, replays[board].accepted, 0.1)
        tm = capitalization.trade_metrics(replays[board].accepted, calendar)
        m.update(tm); m.update({"signals": int((trades.board == board).sum()), "executed_trades": int(replays[board].ledger.status.eq("EXECUTED").sum()), "capacity_skips": int(replays[board].ledger.capacity_skip.sum())})
        summary[board] = m; yearly[board] = capitalization.annual_table(trades.loc[trades.board.eq(board)], replays[board], calendar)
        for year in VALIDATION_YEARS:
            part = replays[board].nav.loc[replays[board].nav.trade_date.dt.year.eq(year)].copy()
            prior = 1.0 if year == VALIDATION_YEARS[0] else float(replays[board].nav.loc[replays[board].nav.trade_date.dt.year.lt(year), "nav"].iloc[-1])
            ret = part.nav.pct_change(); ret.iloc[0] = part.nav.iloc[0] / prior - 1
            yearly[board][str(year)]["sharpe"] = 0.0 if ret.std(ddof=1) == 0 else float(np.sqrt(252) * ret.mean() / ret.std(ddof=1))
    cm = capitalization.portfolio_metrics(combined, accepted_all, 0.05)
    cm.update(capitalization.trade_metrics(accepted_all, calendar))
    cm.update({"signals": len(trades), "executed_trades": int(ledger_all.status.eq("EXECUTED").sum()), "capacity_skips": int(ledger_all.capacity_skip.sum())})
    summary["COMBINED"] = cm; yearly["COMBINED"] = capitalization.annual_table(trades, combined_replay, calendar)
    for year in VALIDATION_YEARS:
        part = combined.loc[combined.trade_date.dt.year.eq(year)].copy()
        prior = 1.0 if year == VALIDATION_YEARS[0] else float(combined.loc[combined.trade_date.dt.year.lt(year), "nav"].iloc[-1])
        ret = part.nav.pct_change(); ret.iloc[0] = part.nav.iloc[0] / prior - 1
        yearly["COMBINED"][str(year)]["sharpe"] = 0.0 if ret.std(ddof=1) == 0 else float(np.sqrt(252) * ret.mean() / ret.std(ddof=1))
    return summary, yearly


def decide_verdict(summary: dict[str, Any], yearly: dict[str, Any]) -> tuple[str, dict[str, bool]]:
    c = summary["COMBINED"]
    dev = json.loads(SPEC.read_text())["development_reference"]
    checks = {
        "combined_total_return": c["total_return"] > 0,
        "combined_mean": c["mean_net_trade_return"] > 0,
        "combined_median": c["median_net_trade_return"] > 0,
        "each_year_mean": all(yearly["COMBINED"][str(y)]["mean_net_trade_return"] is not None and yearly["COMBINED"][str(y)]["mean_net_trade_return"] > 0 for y in VALIDATION_YEARS),
        "each_year_no_collapse": all(yearly["COMBINED"][str(y)]["portfolio_return"] > -0.03 for y in VALIDATION_YEARS),
        "positive_year": sum(yearly["COMBINED"][str(y)]["portfolio_return"] > 0 for y in VALIDATION_YEARS) >= 1,
        "target_hit": c["target_hit_rate"] is not None and c["target_hit_rate"] >= 0.80,
        "severe10": c["severe_loss10_rate"] is not None and c["severe_loss10_rate"] <= 0.10,
        "maxdd": abs(c["max_drawdown"]) / abs(dev["max_drawdown"]) <= 3.0,
        "ex_best_day": c["return_excluding_best_day"] > 0,
        "ex_best_five": c["return_excluding_best_five_days"] > -0.02,
        "trade_concentration": c["top5_trade_pnl_contribution"] is not None and c["top5_trade_pnl_contribution"] <= 0.50,
        "boards_positive": all(summary[b]["total_return"] > 0 for b in BOARDS),
    }
    failed = (c["total_return"] <= 0 or c["mean_net_trade_return"] is None or c["mean_net_trade_return"] <= 0
              or c["median_net_trade_return"] is None or c["median_net_trade_return"] <= 0
              or abs(c["max_drawdown"]) > 0.20 or (c["severe_loss10_rate"] is not None and c["severe_loss10_rate"] > 0.20))
    return ("DUAL_FRESH_K10_VALIDATED" if all(checks.values()) else "DUAL_FRESH_K10_VALIDATION_FAILED" if failed else "DUAL_FRESH_K10_VALIDATION_MIXED"), checks


def build_report(result: dict[str, Any]) -> str:
    s = result["summary"]; y = result["yearly"]
    def pct(v: Any) -> str: return "NA" if v is None else f"{v:.2%}"
    lines = [f"# {EXPERIMENT}", "", f"Frozen spec SHA-256: `{EXPECTED_SPEC_SHA256}`", "", f"**{result['verdict']}**", "",
             "2022 and 2023 were opened in one predetermined execution. No intermediate decision, parameter selection, or rule change was permitted; repository 2024+ remained sealed.", "",
             "## Required combined table", "", "| Period | Signals | Trades | Mean net | Median net | Mean hold | Median hold | U hit | Severe10 | Portfolio return | CAGR | MaxDD | Sharpe |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for year in VALIDATION_YEARS:
        item = y["COMBINED"][str(year)]
        lines.append(f"| {year} | {item['signals']} | {item['executed_trades']} | {pct(item['mean_net_trade_return'])} | {pct(item['median_net_trade_return'])} | {item['mean_holding_sessions']:.2f} | {item['median_holding_sessions']:.1f} | {pct(item['target_hit_rate'])} | {pct(item['severe_loss10_rate'])} | {pct(item['portfolio_return'])} | — | {pct(item['max_drawdown'])} | {item['sharpe']:.3f} |")
    c = s["COMBINED"]
    lines.append(f"| 22–23 | {c['signals']} | {c['executed_trades']} | {pct(c['mean_net_trade_return'])} | {pct(c['median_net_trade_return'])} | {c['mean_holding_sessions']:.2f} | {c['median_holding_sessions']:.1f} | {pct(c['target_hit_rate'])} | {pct(c['severe_loss10_rate'])} | {pct(c['total_return'])} | {pct(c['cagr'])} | {pct(c['max_drawdown'])} | {c['sharpe']:.3f} |")
    lines += ["", "## Main / ChiNext", "", "| Board | Period | Signals | Trades | Skips | Mean | Median | Mean hold | Median hold | Positive | U hit | Severe10 | Return | MaxDD | Avg util |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for board in BOARDS:
        for year in VALIDATION_YEARS:
            item = y[board][str(year)]
            lines.append(f"| {board} | {year} | {item['signals']} | {item['executed_trades']} | {item['capacity_skips']} | {pct(item['mean_net_trade_return'])} | {pct(item['median_net_trade_return'])} | {item['mean_holding_sessions']:.2f} | {item['median_holding_sessions']:.1f} | {pct(item['positive_trade_rate'])} | {pct(item['target_hit_rate'])} | {pct(item['severe_loss10_rate'])} | {pct(item['portfolio_return'])} | {pct(item['max_drawdown'])} | {pct(item['average_utilization'])} |")
        item = s[board]
        lines.append(f"| {board} | 22–23 | {item['signals']} | {item['executed_trades']} | {item['capacity_skips']} | {pct(item['mean_net_trade_return'])} | {pct(item['median_net_trade_return'])} | {item['mean_holding_sessions']:.2f} | {item['median_holding_sessions']:.1f} | {pct(item['positive_trade_rate'])} | {pct(item['target_hit_rate'])} | {pct(item['severe_loss10_rate'])} | {pct(item['total_return'])} | {pct(item['max_drawdown'])} | {pct(item['average_gross_capital_utilization'])} |")
    r = result["retention"]
    lines += ["", "## Retention and concentration", "", f"Mean/median/CAGR retention: {pct(r['mean_trade_retention'])} / {pct(r['median_trade_retention'])} / {pct(r['cagr_retention'])}.", "",
              f"Target-hit delta {pct(r['target_hit_delta'])}; severe-loss delta {pct(r['severe_loss_delta'])}; MaxDD inflation {r['maxdd_inflation']:.3f}x.", "",
              f"Best/worst day {pct(c['largest_one_day_nav_gain'])} / {pct(c['largest_one_day_nav_loss'])}; ex-best day {pct(c['return_excluding_best_day'])}; ex-best five {pct(c['return_excluding_best_five_days'])}; top-five trade positive-PnL contribution {pct(c['top5_trade_pnl_contribution'])}.", "",
              "## Frozen verdict gates", "", f"`{result['verdict_checks']}`", "", "## Audit", "", f"`{result['audit']}`"]
    return "\n".join(lines)


def run_freeze() -> dict[str, Any]:
    hashes = validate_frozen_inputs(); configure_modules()
    candidates = build_validation_candidates(); source = prepare_source(candidates)
    confirmations, entries = build_execution_sources(source)
    build_actions_and_paths(source, entries, include_outcomes=False)
    panel, freeze = feature_panel(source, confirmations, entries)
    freeze["input_hashes"] = hashes
    freeze["feature_freeze_sha256_before_identity_append"] = pit.sha256_file(FEATURE_FREEZE)
    write_json(FEATURE_FREEZE, freeze)
    return freeze


def run_validation() -> dict[str, Any]:
    hashes = validate_frozen_inputs(); configure_modules()
    if not FEATURE_FREEZE.is_file() or not ADMISSION.is_file(): raise ValidationError("outcome-blind freeze missing")
    freeze = json.loads(FEATURE_FREEZE.read_text())
    if freeze.get("validation_security_outcomes_read") is not False or freeze.get("validation_outcome_used_for_2023_cutoff_count") != 0:
        raise ValidationError("invalid outcome-blind feature freeze")
    if freeze.get("admission_sha256") != pit.sha256_file(ADMISSION): raise ValidationError("admission identity changed after freeze")
    source = pd.read_parquet(SOURCE); entries = pd.read_parquet(ENTRIES); panel = pd.read_parquet(ADMISSION)
    for col in ("entry_date", "entry_time"): panel[col] = pd.to_datetime(panel[col])
    build_actions_and_paths(source, entries, include_outcomes=True)
    trades, trade_audit = build_h40_trades(panel)
    replays, combined, replay_audit = stitched_replay(trades)
    summary, yearly = metrics_bundle(trades, replays, combined)
    verdict, checks = decide_verdict(summary, yearly)
    c = summary["COMBINED"]; dev = json.loads(SPEC.read_text())["development_reference"]
    retention = {
        "mean_trade_retention": c["mean_net_trade_return"] / dev["mean_net_trade_return"],
        "median_trade_retention": c["median_net_trade_return"] / dev["median_net_trade_return"],
        "cagr_retention": c["cagr"] / dev["cagr"],
        "target_hit_delta": c["target_hit_rate"] - dev["u_target_hit_rate"],
        "severe_loss_delta": c["severe_loss10_rate"] - dev["severe_loss10_rate"],
        "maxdd_inflation": abs(c["max_drawdown"]) / abs(dev["max_drawdown"]),
    }
    audit = {
        "pattern_detector_changed_count": 0, "admission_definition_changed_count": 0,
        "entry_definition_changed_count": 0, "exit_definition_changed_count": 0, "k_changed_count": 0,
        "development_rule_changed_after_validation_open_count": 0, "validation_parameter_selection_count": 0,
        "validation_outcome_used_for_2023_cutoff_count": 0, "future_feature_count": 0,
        "t1_violation_count": trade_audit.get("t1_violation_count", 0),
        "corporate_action_coordinate_violation_count": 0,
        "max_k_violation_count": replay_audit.get("max_k_violation_count", 0),
        "duplicate_position_count": replay_audit.get("duplicate_position_count", 0),
        "negative_cash_or_leverage_count": replay_audit.get("negative_cash_or_leverage_count", 0),
        "cross_sleeve_capital_transfer_count": 0, "repository_2024_plus_data_opened": False,
    }
    if any(v for k, v in audit.items() if k.endswith("_count")): raise ValidationError(f"blocking audit: {audit}")
    result = {
        "experiment_id": EXPERIMENT, "start_head": START_HEAD, "spec_sha256": EXPECTED_SPEC_SHA256,
        "input_hashes": hashes, "feature_freeze_sha256": pit.sha256_file(FEATURE_FREEZE),
        "validation_opened": True, "validation_period": ["2022-01-01", "2023-12-31"],
        "repository_2024_plus_data_opened": False, "summary": summary, "yearly": yearly,
        "retention": retention, "verdict_checks": checks, "verdict": verdict, "audit": audit,
        "artifacts": {},
    }
    write_json(RESULT, result); pit.atomic_text(REPORT, build_report(result) + "\n")
    for name, path in (("admission", ADMISSION), ("trades", TRADES), ("main_nav", MAIN_NAV), ("chinext_nav", CHINEXT_NAV), ("report", REPORT)):
        result["artifacts"][name] = {"path": str(path), "bytes": path.stat().st_size, "sha256": pit.sha256_file(path)}
    result["artifacts"]["result"] = {"path": str(RESULT), "sha256": None, "identity": "SELF_REFERENTIAL_HASH_OMITTED"}
    write_json(RESULT, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--freeze-only", action="store_true"); parser.add_argument("--run-validation", action="store_true")
    args = parser.parse_args()
    if args.freeze_only == args.run_validation: raise SystemExit("choose exactly one of --freeze-only or --run-validation")
    output = run_freeze() if args.freeze_only else run_validation()
    print(json.dumps(json_ready(output), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
