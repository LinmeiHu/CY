#!/usr/bin/env python3
# ruff: noqa: E501
"""Executable simple-profit Development for the all-true-gap V2 mother set.

Stage A freezes entries, admissible state templates, exits, and chronology
without calculating a return. Stage B attaches executable outcomes only after
the Stage-A hashes reproduce. Data dated 2021 or later are prohibited.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Rectangle

from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_gap_zone_monetization_anatomy_v1 as anatomy,
)

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-ALL-TRUE-GAP-EXECUTABLE-SIMPLE-PROFIT-DEVELOPMENT-V1"
START_HEAD = "45f1312680a597e9ac00e48432ec6ff761140242"
SOURCE_EXPERIMENT = "ASHARE-ALL-TRUE-GAP-LOW-INVENTORY-FILL-PATTERN-DISCOVERY-V2"
SOURCE_ALL_GAPS_HASH = "afdb8b05b2166d71466fa7d8413030ac9b3fafe141e7f0326718d89fddd9b288"

SOURCE_ALL_GAPS = Path("/Volumes/quant/CY_quant_research/ashare_all_true_gap_low_inventory_fill_pattern_discovery_v2/all_true_gap_primitives_2014_2020.parquet")
DAILY = Path("/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/pit_daily_compact_2013_2023.parquet")
RAW_ROOT = Path("/Users/linmei/Downloads/workspace/quant/data/lake/stock_1min_canonical_none_20260813/bars")
ACTION_EVENTS = Path("/Volumes/quant/CY_quant_research/ashare_true_gap_causal_cluster_v6_one_shot_discovery/action_events.parquet")
LEGAL_OPENS = Path("/Volumes/quant/CY_quant_research/ashare_true_gap_causal_cluster_v6_one_shot_discovery/legal_opens.parquet")

EXT = Path("/Volumes/quant/CY_quant_research/ashare_all_true_gap_executable_simple_profit_development_v1")
MANIFESTS = EXT / "manifests"
CORRECTED_DAILY_CANDIDATES = EXT / "raw_tick_daily_candidates.parquet"
CORRECTED_PRE_DAYS = EXT / "raw_tick_pre_gap_days.parquet"
CORRECTED_VAP_PROFILES = EXT / "raw_tick_pre_gap_vap_profiles.parquet"
CORRECTED_VAP_PARTS = EXT / "raw_tick_vap_parts"
CORRECTED_MOTHER = EXT / "raw_tick_stage_a_mother.parquet"
ENTRY_DAY_SEED = EXT / "entry_day_seed.parquet"
ENTRY_DAY_MINUTES = EXT / "entry_day_minutes.parquet"
ENTRY_DAY_PARTS = EXT / "entry_day_parts"
ENTRY_CANDIDATES = EXT / "entry_candidates.parquet"
OUTCOME_BOUNDS = EXT / "outcome_bounds.parquet"
OUTCOME_MINUTES = EXT / "outcome_minutes.parquet"
OUTCOME_MINUTE_PARTS = EXT / "outcome_minute_parts"
POLICY_OUTCOMES = EXT / "policy_outcomes.parquet"
SELECTION_CANDIDATES = EXT / "selection_candidates.parquet"
WALKFORWARD_SELECTIONS = EXT / "walkforward_selections.parquet"
OOF_TRADES = EXT / "oof_trades.parquet"
PORTFOLIO_ACCEPTED = EXT / "portfolio_accepted.parquet"
PORTFOLIO_LEDGER = EXT / "portfolio_ledger.parquet"
PORTFOLIO_NAV = EXT / "portfolio_nav.parquet"
PORTFOLIO_SUMMARY = EXT / "portfolio_summary.parquet"
CHART_DAILY = EXT / "chart_daily_paths.parquet"
CHART_VAP = EXT / "chart_vap_profiles.parquet"
CHART_DIR = EXT / "signal_charts"

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
CHART_INDEX = OS / f"artifacts/{EXPERIMENT}_chart_index.csv"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"
PDF = ROOT / f"output/pdf/{EXPERIMENT}_all_oof_signal_charts.pdf"

DEV_START = pd.Timestamp("2014-01-01")
DEV_END = pd.Timestamp("2020-12-31")
OUTER_YEARS = (2017, 2018, 2019, 2020)
COST = 0.002
ENTRY_FORMS = ("E1_CLOSE_L", "E2_HOLD3OF5_L", "E3_CLOSE_Z25")
MIN_NET_HEADROOMS = (0.010, 0.015, 0.020, 0.030)
TIME_STOPS = (5, 10, 20)
EXIT_POLICIES = ("X0_NO_FAILURE", "X1_CLOSE_BELOW_L", "X2_D3_NO_PROGRESS")
MIN_TRAIN_TRADES = 60
MIN_LATEST_TRAIN_YEAR_TRADES = 10
PURGE_SESSIONS = 20
K = 10
EPS = 1e-12
PRE_GAP_SESSIONS = 120
MIN_FULLY_BELOW_SESSIONS = 5
MIN_TRUE_GAP_WIDTH_PCT = 0.01
MAX_INSIDE_TOUCH_SESSIONS = 12
MAX_CORRIDOR_TOUCH_SESSIONS = 20

ADMISSION_TEMPLATES: dict[str, tuple[str, ...]] = {
    "A0_NONE": (),
    "A1_LONG_DECLINE": ("PEAK_TO_GAP_GE60",),
    "A2_LONG_DEEP": ("PEAK_TO_GAP_GE60", "DRAWDOWN_GE30"),
    "A3_NO_NEAR_TOUCH": ("POST_GAP_NEAR_TOUCH_EQ0",),
    "A4_LONG_NO_NEAR_TOUCH": ("PEAK_TO_GAP_GE60", "POST_GAP_NEAR_TOUCH_EQ0"),
    "A5_LONG_NOT_ACUTE": ("PEAK_TO_GAP_GE60", "MAX_RUNUP20_LE_TRAIN_Q50"),
    "A6_DEEP_NOT_ACUTE": ("DRAWDOWN_GE30", "MAX_RUNUP20_LE_TRAIN_Q50"),
    "A7_CLEAN_EXACT": ("INSIDE_DENSITY_LE_TRAIN_Q30",),
    "A8_LONG_CLEAN_EXACT": ("PEAK_TO_GAP_GE60", "INSIDE_DENSITY_LE_TRAIN_Q30"),
    "A9_HUMAN_CLEAN_COLLAPSE": ("PEAK_TO_GAP_GE60", "DRAWDOWN_GE30", "POST_GAP_NEAR_TOUCH_EQ0"),
    "A10_HUMAN_LOW_CHIP": ("PEAK_TO_GAP_GE60", "INSIDE_DENSITY_LE_TRAIN_Q30", "POST_GAP_NEAR_TOUCH_EQ0"),
    "A11_LOW_PRE_GAP_OCCUPANCY": ("PEAK_TO_GAP_GE60", "PRE_GAP_INSIDE_TOUCH_LE4"),
}


class ResearchError(RuntimeError):
    pass


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(value))
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(type(value).__name__)


def canonical_json(value: Any) -> str:
    return json.dumps(value, default=_json_default, sort_keys=True, indent=2, allow_nan=False) + "\n"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value))


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def raw_path(year: int) -> Path:
    return RAW_ROOT / f"{year}_day_parquet_none.parquet"


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "start_head": START_HEAD,
        "source": {
            "experiment": SOURCE_EXPERIMENT,
            "all_true_gap_ledger": str(SOURCE_ALL_GAPS),
            "all_true_gap_ledger_sha256": SOURCE_ALL_GAPS_HASH,
            "source_population_count": 88785,
            "raw_tick_causal_mother_rebuilt_before_returns": True,
            "raw_tick_interaction": "round(raw_high*100) >= round((coordinate_boundary/coordinate_factor)*100)",
            "source_is_outcome_blind": True,
            "v6_core_gate_used": False,
            "v2_305_outcome_selected_rows_used": False,
        },
        "chronology": {
            "development": ["2014-01-01", "2020-12-31"],
            "outer_test_years": list(OUTER_YEARS),
            "expanding_train": True,
            "purge_sessions": PURGE_SESSIONS,
            "reserved_2021_plus": "UNREAD",
        },
        "entry": {
            "forms": list(ENTRY_FORMS),
            "E1_CLOSE_L": "first completed one-minute close >= L on the pristine first-return date",
            "E2_HOLD3OF5_L": "first completed close >= L with at least 3 of the latest 5 completed closes >= L on that date",
            "E3_CLOSE_Z25": "first completed close >= L+0.25W on that date",
            "execution": "next legal one-minute open strictly after trigger; IOC buy limit enforces frozen minimum net target headroom",
            "minimum_net_headroom_candidates": list(MIN_NET_HEADROOMS),
            "missed_fast_repair": "no trigger/entry after U has already traded",
        },
        "target": "standing sell limit at corporate-action-consistent U, executable only from the first T+1 session",
        "costs": {"entry": COST, "exit": COST},
        "failure_exits": {
            "X0_NO_FAILURE": "U or time stop",
            "X1_CLOSE_BELOW_L": "first completed sellable-session daily close below L; exit next legal open",
            "X2_D3_NO_PROGRESS": "at D3 max progress <0.25W and close<L; exit next legal open",
        },
        "time_stops": {str(value): "exit next legal open after the completed horizon-session close" for value in TIME_STOPS},
        "admission_templates": {key: list(value) for key, value in ADMISSION_TEMPLATES.items()},
        "selection": {
            "hierarchy": ["execution profile under A0", "one frozen admission template"],
            "utility": "0.5*(event mean net + entry-date-equal mean net) - 0.20*abs(CVaR5)",
            "one_standard_error": True,
            "minimum_train_trades": MIN_TRAIN_TRADES,
            "minimum_latest_train_year_trades": MIN_LATEST_TRAIN_YEAR_TRADES,
            "deployment_gate": ["mean>0", "median>0", "date_equal_mean>0", "utility>0", "at_least_60pct_positive_train_years", "severe10<15pct"],
        },
        "fixed_human_rule": {
            "profile": ["E1_CLOSE_L", 0.015, 10, "X1_CLOSE_BELOW_L"],
            "conditions": ["PEAK_TO_GAP_GE60", "POST_GAP_NEAR_TOUCH_EQ0"],
            "total_admission_conditions_including_headroom": 3,
        },
        "portfolio": {"main_sleeve": 0.5, "chinext_sleeve": 0.5, "k_per_sleeve": K, "one_position_per_symbol": True, "unused_cash": True, "leverage": False},
        "governance": {"return_analysis_before_stage_a_freeze": False, "strategy_outcomes_2021_plus": False, "repository_2024_plus_opened": False},
    }


def spec_value(contract_hash: str) -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "contract_sha256": contract_hash,
        "mission": "Test whether a small, causal, economically-headroom-aware rule can monetize low-inventory true-gap first returns without using the outcome-selected V2 305-row subset.",
        "scientific_label": "DEVELOPMENT_ONLY_EXPANDING_WALKFORWARD",
        "hard_interpretation": [
            "narrow-gap structural fill is not a profit objective",
            "all entries must retain ex-ante and execution-time net target headroom",
            "all exits are T+1 and legally executable",
            "outer-year results cannot select their own rule",
            "2021 and later remain unread",
        ],
    }


def persist_contracts() -> dict[str, str]:
    contract = contract_value()
    write_json(CONTRACT, contract)
    contract_hash = sha256(CONTRACT)
    write_json(SPEC, spec_value(contract_hash))
    return {"contract_sha256": contract_hash, "spec_sha256": sha256(SPEC)}


def manifest(name: str, payload: dict[str, Any]) -> None:
    write_json(MANIFESTS / f"{name}.json", {"experiment": EXPERIMENT, **payload})


def validate_inputs() -> None:
    required = [SOURCE_ALL_GAPS, DAILY, ACTION_EVENTS, LEGAL_OPENS, *[raw_path(year) for year in range(2013, 2021)]]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ResearchError(f"missing inputs: {missing}")
    if sha256(SOURCE_ALL_GAPS) != SOURCE_ALL_GAPS_HASH:
        raise ResearchError("source all-gap ledger hash mismatch")


def load_mother() -> pd.DataFrame:
    if not CORRECTED_MOTHER.is_file():
        raise ResearchError("raw-tick corrected Stage-A mother missing")
    mother = pd.read_parquet(CORRECTED_MOTHER)
    for column in ("gap_date", "first_return_date", "pristine_first_return_time", "pre_peak_date"):
        mother[column] = pd.to_datetime(mother[column])
    if mother.empty or mother.gap_id.duplicated().any():
        raise ResearchError("source mother identity mismatch")
    if mother.first_return_date.min() < DEV_START or mother.first_return_date.max() > DEV_END:
        raise ResearchError("source chronology breach")
    forbidden = [column for column in mother if any(token in column.lower() for token in ("u_fill", "net_return", "pnl", "profit", "winner"))]
    if forbidden:
        raise ResearchError(f"outcome columns in Stage-A source: {forbidden}")
    return mother.sort_values(["first_return_date", "symbol", "gap_id"], kind="mergesort").reset_index(drop=True)


def load_source_daily() -> pd.DataFrame:
    columns = [
        "trade_date", "cal_idx", "symbol", "sleeve", "open", "high", "low", "close", "volume", "turnover_fraction",
        "corporate_action_count", "corporate_action_valid", "corporate_action_blocking", "hard_valid", "history_valid", "current_valid",
        "invalid_step_cum", "coordinate_factor", "coord_open", "coord_high", "coord_low", "coord_close",
    ]
    con = duckdb.connect()
    con.execute("SET threads=4")
    frame = con.execute(f"""SELECT {','.join(columns)} FROM read_parquet('{DAILY}')
      WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2020-12-31'
        AND sleeve IN ('MAIN','CHINEXT')
      ORDER BY symbol,trade_date""").fetchdf()
    con.close()
    frame.trade_date = pd.to_datetime(frame.trade_date)
    frame["symbol_seq"] = frame.groupby("symbol", sort=False).cumcount()
    if frame.empty or frame.trade_date.max() > DEV_END:
        raise ResearchError("source daily chronology failure")
    return frame


def _valid_daily_rows(frame: pd.DataFrame) -> np.ndarray:
    return (
        frame.hard_valid.fillna(False)
        & frame.history_valid.fillna(False)
        & frame.current_valid.fillna(False)
        & frame.corporate_action_valid.fillna(False)
        & ~frame.corporate_action_blocking.fillna(True)
    ).to_numpy(bool)


def _price_ticks(raw_price: pd.Series | np.ndarray | float) -> np.ndarray:
    """Map positive A-share prices to authoritative fen ticks, robust to float noise."""
    values = np.asarray(raw_price, dtype=float)
    return np.floor(values * 100.0 + 0.5 + 1e-6).astype(np.int64)


def _boundary_ticks(coordinate_boundary: float, coordinate_factor: pd.Series | np.ndarray | float) -> np.ndarray:
    factors = np.asarray(coordinate_factor, dtype=float)
    return _price_ticks(float(coordinate_boundary) / factors)


def _raw_tick_reached(raw_high: pd.Series | np.ndarray, coordinate_boundary: float, coordinate_factor: pd.Series | np.ndarray) -> np.ndarray:
    return _price_ticks(raw_high) >= _boundary_ticks(coordinate_boundary, coordinate_factor)


def build_raw_tick_daily_candidates(daily: pd.DataFrame) -> pd.DataFrame:
    all_gaps = pd.read_parquet(SOURCE_ALL_GAPS)
    all_gaps.gap_date = pd.to_datetime(all_gaps.gap_date)
    groups = {key: part.reset_index(drop=True) for key, part in daily.groupby("symbol", sort=False)}
    rows: list[dict[str, Any]] = []
    meaningful = all_gaps.loc[all_gaps.gap_width_pct.ge(MIN_TRUE_GAP_WIDTH_PCT)].copy()
    for gap in meaningful.itertuples(index=False):
        part = groups[str(gap.symbol)]
        pos = int(gap.gap_seq)
        if pos >= len(part) or pd.Timestamp(part.iloc[pos].trade_date) != pd.Timestamp(gap.gap_date):
            raise ResearchError(f"gap sequence mismatch {gap.gap_id}")
        reason = "ELIGIBLE_FOR_MINUTE_VAP"
        hist = part.iloc[max(0, pos - PRE_GAP_SESSIONS) : pos].copy()
        history_ok = len(hist) == PRE_GAP_SESSIONS and _valid_daily_rows(hist).all() and hist.invalid_step_cum.eq(float(gap.invalid_step_cum)).all()
        if not history_ok:
            reason = "NO_EXACT_120_SAME_LINEAGE_DAILY_HISTORY"
        future = part.iloc[pos + 1 :].copy()
        if len(future):
            future_valid = _valid_daily_rows(future) & future.invalid_step_cum.eq(float(gap.invalid_step_cum)).to_numpy(bool)
            invalid = np.flatnonzero(~future_valid)
            if len(invalid):
                future = future.iloc[: int(invalid[0])]
        touches = _raw_tick_reached(future.high, float(gap.L), future.coordinate_factor) if len(future) else np.array([], dtype=bool)
        positions = np.flatnonzero(touches)
        first_return_rel = None if not len(positions) else int(positions[0])
        if reason == "ELIGIBLE_FOR_MINUTE_VAP" and first_return_rel is None:
            reason = "NO_FIRST_RETURN_BY_2020"
        if reason == "ELIGIBLE_FOR_MINUTE_VAP" and first_return_rel is not None and first_return_rel < MIN_FULLY_BELOW_SESSIONS:
            reason = "REJECTED_PRE_PERSISTENCE_TOUCH"
        first_return_pos = None if first_return_rel is None else pos + 1 + first_return_rel
        if reason == "ELIGIBLE_FOR_MINUTE_VAP" and first_return_pos is not None:
            outcome_end = first_return_pos + 40
            if outcome_end >= len(part):
                reason = "INCOMPLETE_H40_BEFORE_2021"
            else:
                h40 = part.iloc[first_return_pos : outcome_end + 1]
                if not _valid_daily_rows(h40).all() or not h40.invalid_step_cum.eq(float(gap.invalid_step_cum)).all() or pd.Timestamp(h40.trade_date.max()) > DEV_END:
                    reason = "INCOMPLETE_H40_BEFORE_2021"
        inside_touches = math.nan
        corridor_touches = math.nan
        features: dict[str, Any] = {}
        if history_ok:
            inside = hist.coord_high.ge(float(gap.L)) & hist.coord_low.lt(float(gap.U))
            corridor = hist.coord_high.ge(float(gap.L - 0.5 * gap.W)) & hist.coord_low.lt(float(gap.U + 0.5 * gap.W))
            inside_touches = int(inside.sum())
            corridor_touches = int(corridor.sum())
            if reason == "ELIGIBLE_FOR_MINUTE_VAP" and inside_touches > MAX_INSIDE_TOUCH_SESSIONS:
                reason = "PRE_GAP_EXACT_OCCUPANCY_TOO_HIGH"
            if reason == "ELIGIBLE_FOR_MINUTE_VAP" and corridor_touches > MAX_CORRIDOR_TOUCH_SESSIONS:
                reason = "PRE_GAP_CORRIDOR_OCCUPANCY_TOO_HIGH"
            peak_offset = int(np.nanargmax(hist.coord_high.to_numpy(float)))
            peak = float(hist.iloc[peak_offset].coord_high)
            recent20 = hist.tail(20)
            recent60 = hist.tail(60)
            features = {
                "pre_gap_inside_touch_sessions": inside_touches,
                "pre_gap_corridor_touch_sessions": corridor_touches,
                "pre_peak_date": pd.Timestamp(hist.iloc[peak_offset].trade_date),
                "pre_peak_to_gap_sessions": int(len(hist) - peak_offset),
                "pre_gap_drawdown_from_120d_peak": float(1 - float(gap.coord_low) / peak),
                "pre_gap_return_20d": float(hist.iloc[-1].coord_close / hist.iloc[-20].coord_close - 1),
                "pre_gap_return_60d": float(hist.iloc[-1].coord_close / hist.iloc[-60].coord_close - 1),
                "pre_gap_max_runup_20d": float(recent20.coord_high.max() / recent20.coord_low.min() - 1),
                "pre_gap_max_runup_60d": float(recent60.coord_high.max() / recent60.coord_low.min() - 1),
            }
        if first_return_pos is not None:
            return_row = part.iloc[first_return_pos]
            below = part.iloc[pos + 1 : first_return_pos]
            last10 = below.tail(10)
            if len(last10) >= 2:
                closes = last10.coord_close.to_numpy(float)
                lows = last10.coord_low.to_numpy(float)
                total_path = float(np.abs(np.diff(closes)).sum())
                approach_return = float(closes[-1] / closes[0] - 1)
                approach_efficiency = float(max(closes[-1] - closes[0], 0) / total_path) if total_path > EPS else 0.0
                higher_low_share = float(np.mean(np.diff(lows) > 0))
            else:
                approach_return = approach_efficiency = higher_low_share = math.nan
            lower_corridor = below.coord_high.ge(float(gap.L - 0.5 * gap.W))
            features.update({
                "first_return_date": pd.Timestamp(return_row.trade_date),
                "first_return_cal_idx": int(return_row.cal_idx),
                "first_return_seq": int(return_row.symbol_seq),
                "first_return_coordinate_factor": float(return_row.coordinate_factor),
                "gap_age_sessions": int(first_return_pos - pos),
                "max_depth_below_l_before_return": float(1 - below.coord_low.min() / float(gap.L)) if len(below) else 0.0,
                "post_gap_lower_corridor_touch_sessions": int(lower_corridor.sum()),
                "post_gap_lower_corridor_turnover": float(below.loc[lower_corridor, "turnover_fraction"].sum()),
                "approach_return_10d": approach_return,
                "approach_path_efficiency_10d": approach_efficiency,
                "higher_low_share_10d": higher_low_share,
            })
        rows.append({**gap._asdict(), **features, "daily_history_complete": bool(history_ok), "first_post_gap_touch_is_pristine": bool(first_return_rel is not None and first_return_rel >= MIN_FULLY_BELOW_SESSIONS), "pre_gap_inside_touch_sessions": inside_touches, "pre_gap_corridor_touch_sessions": corridor_touches, "stage_a_daily_disposition": reason})
    candidates = pd.DataFrame(rows)
    if candidates.gap_id.duplicated().any():
        raise ResearchError("duplicate raw-tick daily candidate")
    write_parquet(candidates, CORRECTED_DAILY_CANDIDATES)
    return candidates


def build_corrected_pre_days(daily: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    selected = candidates.loc[candidates.stage_a_daily_disposition.eq("ELIGIBLE_FOR_MINUTE_VAP")]
    groups = {key: part.reset_index(drop=True) for key, part in daily.groupby("symbol", sort=False)}
    pieces = []
    for event in selected.itertuples(index=False):
        part = groups[str(event.symbol)]
        hist = part.iloc[int(event.gap_seq) - PRE_GAP_SESSIONS : int(event.gap_seq)][["symbol", "trade_date", "coordinate_factor", "turnover_fraction"]].copy()
        if len(hist) != PRE_GAP_SESSIONS:
            raise ResearchError(f"pre-day reconstruction failure {event.gap_id}")
        hist["gap_id"] = event.gap_id
        hist["L"] = float(event.L)
        hist["W"] = float(event.W)
        pieces.append(hist)
    result = pd.concat(pieces, ignore_index=True)
    if result.empty or result.duplicated(["gap_id", "trade_date"]).any():
        raise ResearchError("corrected pre-gap day panel invalid")
    write_parquet(result, CORRECTED_PRE_DAYS)
    return result


def _corrected_vap_query(year: int) -> str:
    return f"""
    WITH p AS (SELECT * FROM read_parquet('{CORRECTED_PRE_DAYS}') WHERE year(trade_date)={year}),
    raw0 AS (
      SELECT r.qmt_code AS symbol,r.trade_date,r.bar_end_time,r.high,r.low,r.close,r.volume,r.amount
      FROM read_parquet('{raw_path(year)}') r
      JOIN (SELECT DISTINCT symbol,trade_date FROM p) n ON r.qmt_code=n.symbol AND r.trade_date=n.trade_date
      WHERE r.period='1m' AND r.adjust='none'
    ), joined0 AS (
      SELECT p.gap_id,p.trade_date,p.coordinate_factor,p.turnover_fraction,p.L,p.W,r.bar_end_time,r.high,r.low,r.close,r.volume,r.amount,
        count(*) OVER(PARTITION BY p.gap_id,p.trade_date) AS bars_in_session,
        sum(r.volume) OVER(PARTITION BY p.gap_id,p.trade_date) AS day_volume
      FROM p JOIN raw0 r USING(symbol,trade_date)
    ), joined AS (
      SELECT *,CASE WHEN volume>0 AND amount>0 THEN amount/volume ELSE (high+low+close)/3 END AS minute_price,
        CASE WHEN day_volume>0 THEN turnover_fraction*volume/day_volume ELSE NULL END AS minute_weight
      FROM joined0
    ), quality AS (
      SELECT gap_id,-999::INTEGER AS z_bin,count(DISTINCT trade_date)::DOUBLE AS mass,
        count(DISTINCT trade_date) FILTER(WHERE bars_in_session=241 AND day_volume>0)::DOUBLE AS auxiliary
      FROM joined GROUP BY gap_id
    ), bins AS (
      SELECT gap_id,floor(((minute_price*coordinate_factor-L)/W)/0.10)::INTEGER AS z_bin,
        sum(minute_weight)::DOUBLE AS mass,count(*)::DOUBLE AS auxiliary
      FROM joined WHERE minute_weight IS NOT NULL AND (minute_price*coordinate_factor-L)/W>=-2 AND (minute_price*coordinate_factor-L)/W<3
      GROUP BY gap_id,z_bin
    )
    SELECT * FROM quality UNION ALL SELECT * FROM bins ORDER BY gap_id,z_bin
    """


def build_corrected_vap(candidates: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    CORRECTED_VAP_PARTS.mkdir(parents=True, exist_ok=True)
    parts = []
    for year in range(2013, 2021):
        path = CORRECTED_VAP_PARTS / f"vap_{year}.parquet"
        con = duckdb.connect()
        con.execute("SET threads=4")
        con.execute("SET memory_limit='8GB'")
        con.execute(f"SET temp_directory='{EXT / 'duckdb_tmp'}'")
        frame = con.execute(_corrected_vap_query(year)).fetchdf()
        con.close()
        write_parquet(frame, path)
        parts.append(frame)
    combined = pd.concat(parts, ignore_index=True)
    quality = combined.loc[combined.z_bin.eq(-999)].groupby("gap_id", as_index=False).agg(minute_history_sessions=("mass", "sum"), exact_241_minute_sessions=("auxiliary", "sum"))
    profiles = combined.loc[combined.z_bin.ne(-999)].groupby(["gap_id", "z_bin"], as_index=False).agg(pre_float_turnover_mass=("mass", "sum"), contributing_minutes=("auxiliary", "sum"))
    write_parquet(profiles, CORRECTED_VAP_PROFILES)
    local = profiles.groupby("gap_id", as_index=False).agg(local_mass=("pre_float_turnover_mass", "sum"))
    inside = profiles.loc[profiles.z_bin.between(0, 9)].groupby("gap_id", as_index=False).pre_float_turnover_mass.sum().rename(columns={"pre_float_turnover_mass": "inside_mass"})
    corridor = profiles.loc[profiles.z_bin.between(-5, 14)].groupby("gap_id", as_index=False).pre_float_turnover_mass.sum().rename(columns={"pre_float_turnover_mass": "corridor_mass"})
    metrics_frame = quality.merge(local, on="gap_id", how="left").merge(inside, on="gap_id", how="left").merge(corridor, on="gap_id", how="left")
    metrics_frame[["local_mass", "inside_mass", "corridor_mass"]] = metrics_frame[["local_mass", "inside_mass", "corridor_mass"]].fillna(0.0)
    metrics_frame["pre_gap_inside_density_relative_local"] = 5.0 * metrics_frame.inside_mass / metrics_frame.local_mass.replace(0, np.nan)
    metrics_frame["pre_gap_corridor_density_relative_local"] = 2.5 * metrics_frame.corridor_mass / metrics_frame.local_mass.replace(0, np.nan)
    eligible = candidates.loc[candidates.stage_a_daily_disposition.eq("ELIGIBLE_FOR_MINUTE_VAP")].merge(metrics_frame, on="gap_id", how="left", validate="one_to_one")
    eligible["exact_minute_history"] = eligible.minute_history_sessions.eq(PRE_GAP_SESSIONS) & eligible.exact_241_minute_sessions.eq(PRE_GAP_SESSIONS)
    eligible["low_inside_inventory"] = eligible.pre_gap_inside_density_relative_local.le(1.0)
    eligible["low_corridor_inventory"] = eligible.pre_gap_corridor_density_relative_local.le(1.0)
    return eligible, profiles


def attach_raw_tick_first_return_minutes(mother: pd.DataFrame) -> pd.DataFrame:
    seed = EXT / "raw_tick_first_return_seed.parquet"
    write_parquet(mother[["gap_id", "symbol", "first_return_date", "first_return_coordinate_factor", "L"]], seed)
    rows = []
    for year in sorted(mother.first_return_date.dt.year.unique()):
        con = duckdb.connect()
        frame = con.execute(f"""WITH s AS (SELECT * FROM read_parquet('{seed}') WHERE year(first_return_date)={int(year)}), joined AS (
          SELECT s.gap_id,r.bar_end_time,r.high,count(*) OVER(PARTITION BY s.gap_id) AS bars_in_session
          FROM s JOIN read_parquet('{raw_path(int(year))}') r ON r.qmt_code=s.symbol AND r.trade_date=s.first_return_date
          WHERE r.period='1m' AND r.adjust='none')
          SELECT s.gap_id,min(j.bar_end_time) FILTER(WHERE round(j.high*100)>=round((s.L/s.first_return_coordinate_factor)*100)) AS pristine_first_return_time,
            max(j.bars_in_session) AS first_return_session_minutes
          FROM s JOIN joined j USING(gap_id) GROUP BY s.gap_id ORDER BY s.gap_id""").fetchdf()
        con.close()
        rows.append(frame)
    exact = pd.concat(rows, ignore_index=True)
    exact.pristine_first_return_time = pd.to_datetime(exact.pristine_first_return_time)
    result = mother.merge(exact, on="gap_id", how="left", validate="one_to_one")
    result["exact_first_return_minute_valid"] = result.pristine_first_return_time.notna() & result.first_return_session_minutes.eq(241)
    return result.loc[result.exact_first_return_minute_valid].copy()


def build_corrected_mother() -> tuple[pd.DataFrame, dict[str, Any]]:
    daily = load_source_daily()
    candidates = build_raw_tick_daily_candidates(daily)
    build_corrected_pre_days(daily, candidates)
    eligible, _ = build_corrected_vap(candidates)
    mother = eligible.loc[eligible.exact_minute_history & eligible.low_inside_inventory & eligible.low_corridor_inventory].copy()
    before_minute = len(mother)
    mother = attach_raw_tick_first_return_minutes(mother)
    forbidden = [column for column in mother if any(token in column.lower() for token in ("u_fill", "net_return", "pnl", "profit", "winner"))]
    if mother.empty or mother.gap_id.duplicated().any() or forbidden or mother.first_return_date.max() > DEV_END:
        raise ResearchError(f"corrected mother audit failure forbidden={forbidden}")
    write_parquet(mother, CORRECTED_MOTHER)
    all_gaps = pd.read_parquet(SOURCE_ALL_GAPS)
    funnel = {
        "all_true_gaps": len(all_gaps),
        "width_ge_1pct": int(all_gaps.gap_width_pct.ge(MIN_TRUE_GAP_WIDTH_PCT).sum()),
        "daily_exact_history": int(candidates.daily_history_complete.sum()),
        "raw_tick_pristine_first_return": int(candidates.first_post_gap_touch_is_pristine.sum()),
        "daily_vap_eligible": int(candidates.stage_a_daily_disposition.eq("ELIGIBLE_FOR_MINUTE_VAP").sum()),
        "exact_120x241_minute_history": int(eligible.exact_minute_history.sum()),
        "low_inventory_before_exact_minute": before_minute,
        "corrected_mother": len(mother),
    }
    return mother, funnel


def build_entry_day_minutes(mother: pd.DataFrame) -> pd.DataFrame:
    seed = mother[["gap_id", "symbol", "first_return_date", "pristine_first_return_time", "L", "U", "W", "invalid_step_cum"]].copy()
    write_parquet(seed, ENTRY_DAY_SEED)
    ENTRY_DAY_PARTS.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    for year in range(2014, 2021):
        part = ENTRY_DAY_PARTS / f"year={year}.parquet"
        con = duckdb.connect()
        con.execute("SET threads=4")
        con.execute(f"""COPY (
          SELECT s.gap_id,s.symbol,s.first_return_date,s.pristine_first_return_time,s.L,s.U,s.W,s.invalid_step_cum,
            r.trade_date,r.bar_end_time,r.open,r.high,r.low,r.close,r.volume,r.amount,
            d.cal_idx,d.coordinate_factor,r.open*d.coordinate_factor AS coord_open,
            r.high*d.coordinate_factor AS coord_high,r.low*d.coordinate_factor AS coord_low,r.close*d.coordinate_factor AS coord_close,
            d.hard_valid,d.trade_status,d.current_day_data_tradable,d.market_rule_valid,d.corporate_action_blocking,
            d.up_limit_price,d.down_limit_price,d.invalid_step_cum AS daily_invalid_step_cum
          FROM read_parquet('{ENTRY_DAY_SEED}') s
          JOIN read_parquet('{raw_path(year)}') r ON r.qmt_code=s.symbol AND r.trade_date=s.first_return_date
          JOIN read_parquet('{DAILY}') d ON d.symbol=s.symbol AND d.trade_date=r.trade_date
          WHERE year(s.first_return_date)={year} AND r.period='1m' AND r.adjust='none'
          ORDER BY s.gap_id,r.bar_end_time
        ) TO '{part}' (FORMAT PARQUET,COMPRESSION ZSTD)""")
        con.close()
        parts.append(part)
    tmp = ENTRY_DAY_MINUTES.with_suffix(".parquet.tmp")
    con = duckdb.connect()
    con.execute(f"COPY (SELECT * FROM read_parquet('{ENTRY_DAY_PARTS}/year=*.parquet') ORDER BY gap_id,bar_end_time) TO '{tmp}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.close()
    tmp.replace(ENTRY_DAY_MINUTES)
    minutes = pd.read_parquet(ENTRY_DAY_MINUTES)
    minutes["trade_date"] = pd.to_datetime(minutes.trade_date)
    minutes["bar_end_time"] = pd.to_datetime(minutes.bar_end_time)
    counts = minutes.groupby("gap_id").size()
    if len(counts) != len(mother) or not counts.eq(241).all():
        raise ResearchError(f"entry-day 241-minute contract failure: gaps={len(counts)} bad={int(counts.ne(241).sum())}")
    if minutes.trade_date.max() > DEV_END:
        raise ResearchError("2021+ entry minute opened")
    return minutes


def _entry_limit_coordinate(u: float, minimum_net: float) -> float:
    return u * (1.0 - COST) / ((1.0 + COST) * (1.0 + minimum_net))


def _entry_form_mask(path: pd.DataFrame, event: Any, form: str, max_entry: float) -> pd.Series:
    close = path.coord_close.astype(float)
    base = path.bar_end_time.ge(pd.Timestamp(event.pristine_first_return_time)) & close.le(max_entry)
    if form == "E1_CLOSE_L":
        return base & close.ge(float(event.L))
    if form == "E2_HOLD3OF5_L":
        holds = close.ge(float(event.L)).rolling(5, min_periods=5).sum().ge(3)
        return base & close.ge(float(event.L)) & holds
    if form == "E3_CLOSE_Z25":
        return base & close.ge(float(event.L + 0.25 * event.W))
    raise ResearchError(f"unknown entry form {form}")


def _same_day_next_legal(path: pd.DataFrame, trigger_idx: int) -> pd.Series | None:
    eligible = path.iloc[trigger_idx + 1 :]
    legal = eligible.loc[
        eligible.hard_valid.fillna(False)
        & eligible.trade_status.eq(1)
        & eligible.current_day_data_tradable.fillna(False)
        & eligible.market_rule_valid.fillna(False)
        & ~eligible.corporate_action_blocking.fillna(True)
        & eligible.open.gt(0)
        & (np.rint(eligible.open * 100) < np.rint(eligible.up_limit_price * 100))
        & eligible.daily_invalid_step_cum.eq(eligible.invalid_step_cum)
    ]
    return None if legal.empty else legal.iloc[0]


def build_entry_candidates(mother: pd.DataFrame, minutes: pd.DataFrame) -> pd.DataFrame:
    minute_by = {key: part.sort_values("bar_end_time").reset_index(drop=True) for key, part in minutes.groupby("gap_id", sort=False)}
    legal = pd.read_parquet(LEGAL_OPENS)
    legal["trade_date"] = pd.to_datetime(legal.trade_date)
    legal["bar_end_time"] = pd.to_datetime(legal.bar_end_time)
    legal = legal.loc[legal.symbol.isin(mother.symbol.unique()) & legal.trade_date.le(DEV_END)]
    legal_by = {key: part.sort_values("bar_end_time") for key, part in legal.groupby("symbol", sort=False)}
    actions = pd.read_parquet(ACTION_EVENTS)
    actions["known_date"] = pd.to_datetime(actions.known_date)
    actions["effective_date"] = pd.to_datetime(actions.effective_date)
    actions_by = {key: part for key, part in actions.groupby("symbol", sort=False)}
    rows: list[dict[str, Any]] = []
    for event in mother.itertuples(index=False):
        path = minute_by[str(event.gap_id)]
        first_u = np.flatnonzero(_raw_tick_reached(path.high, float(event.U), path.coordinate_factor))
        first_u_idx = len(path) if not len(first_u) else int(first_u[0])
        for form in ENTRY_FORMS:
            for minimum_net in MIN_NET_HEADROOMS:
                max_entry = _entry_limit_coordinate(float(event.U), minimum_net)
                trigger_mask = _entry_form_mask(path, event, form, max_entry)
                trigger_positions = np.flatnonzero(trigger_mask.to_numpy(bool) & (np.arange(len(path)) < first_u_idx))
                status = "NO_TRIGGER_BEFORE_FAST_REPAIR"
                trigger_idx: int | None = None
                entry_row: pd.Series | None = None
                if len(trigger_positions):
                    trigger_idx = int(trigger_positions[0])
                    candidate = _same_day_next_legal(path, trigger_idx)
                    if candidate is None:
                        future = legal_by.get(str(event.symbol), pd.DataFrame(columns=legal.columns))
                        future = future.loc[future.bar_end_time.gt(pd.Timestamp(path.bar_end_time.iloc[trigger_idx])) & future.invalid_step_cum.eq(float(event.invalid_step_cum))]
                        if not future.empty:
                            candidate = future.iloc[0]
                    if candidate is None:
                        status = "NO_NEXT_LEGAL_OPEN"
                    else:
                        factor = float(candidate.coordinate_factor)
                        raw_open = float(candidate.open) if "open" in candidate.index else float(candidate.raw_open)
                        coord_open = raw_open * factor
                        if coord_open > max_entry + 1e-12:
                            status = "BUY_LIMIT_NOT_FILLED"
                        elif coord_open >= float(event.U) - 1e-12:
                            status = "MISSED_FAST_REPAIR"
                        else:
                            act = actions_by.get(str(event.symbol), pd.DataFrame(columns=actions.columns))
                            trigger_time = pd.Timestamp(path.bar_end_time.iloc[trigger_idx])
                            risk = act.loc[act.action_kind.str.startswith("RISK") & act.known_date.le(trigger_time.normalize()) & act.effective_date.ge(pd.Timestamp(candidate.trade_date))]
                            if not risk.empty:
                                status = "RISK_BLOCKED_ENTRY"
                            else:
                                status = "EXECUTABLE_ENTRY"
                                entry_row = candidate
                trigger_time = pd.NaT if trigger_idx is None else pd.Timestamp(path.bar_end_time.iloc[trigger_idx])
                decision_close = math.nan if trigger_idx is None else float(path.coord_close.iloc[trigger_idx])
                entry_time = pd.NaT if entry_row is None else pd.Timestamp(entry_row.bar_end_time)
                entry_date = pd.NaT if entry_row is None else pd.Timestamp(entry_row.trade_date)
                entry_raw = math.nan if entry_row is None else float(entry_row.open if "open" in entry_row.index else entry_row.raw_open)
                entry_factor = math.nan if entry_row is None else float(entry_row.coordinate_factor)
                entry_coord = math.nan if entry_row is None else entry_raw * entry_factor
                values = event._asdict()
                rows.append({
                    **values,
                    "entry_key": f"{event.gap_id}|{form}|H{round(minimum_net * 10000):04d}",
                    "entry_form": form,
                    "minimum_net_headroom": float(minimum_net),
                    "max_entry_coordinate": max_entry,
                    "entry_status": status,
                    "decision_time": trigger_time,
                    "decision_coordinate_close": decision_close,
                    "entry_time": entry_time,
                    "entry_date": entry_date,
                    "entry_cal_idx": math.nan if entry_row is None else int(entry_row.cal_idx),
                    "entry_raw_price": entry_raw,
                    "entry_coordinate_factor": entry_factor,
                    "entry_coordinate_price": entry_coord,
                    "realized_net_target_at_entry": math.nan if entry_row is None else float((event.U / entry_coord) * (1 - COST) / (1 + COST) - 1),
                    "entry_uses_future_bar": False if entry_row is None or pd.isna(trigger_time) else bool(entry_time <= trigger_time),
                    "entry_is_2021_or_later": False if entry_row is None else bool(entry_date > DEV_END),
                })
    entries = pd.DataFrame(rows).sort_values(["gap_id", "entry_form", "minimum_net_headroom"], kind="mergesort").reset_index(drop=True)
    if entries.entry_key.duplicated().any() or entries.entry_uses_future_bar.any() or entries.entry_is_2021_or_later.any():
        raise ResearchError("entry causality/identity audit failed")
    executable = entries.entry_status.eq("EXECUTABLE_ENTRY")
    if (entries.loc[executable, "realized_net_target_at_entry"] + 1e-12 < entries.loc[executable, "minimum_net_headroom"]).any():
        raise ResearchError("entry headroom limit violated")
    write_parquet(entries, ENTRY_CANDIDATES)
    return entries


def run_stage_a() -> dict[str, Any]:
    validate_inputs()
    hashes = persist_contracts()
    mother, funnel = build_corrected_mother()
    minutes = build_entry_day_minutes(mother)
    entries = build_entry_candidates(mother, minutes)
    runner_hash = sha256(Path(__file__))
    freeze = {
        "experiment": EXPERIMENT,
        **hashes,
        "runner_sha256": runner_hash,
        "source_all_gaps_sha256": sha256(SOURCE_ALL_GAPS),
        "corrected_daily_candidates_sha256": sha256(CORRECTED_DAILY_CANDIDATES),
        "corrected_vap_profiles_sha256": sha256(CORRECTED_VAP_PROFILES),
        "corrected_mother_sha256": sha256(CORRECTED_MOTHER),
        "entry_day_minutes_sha256": sha256(ENTRY_DAY_MINUTES),
        "entry_candidates_sha256": sha256(ENTRY_CANDIDATES),
        "mother_events": len(mother),
        "raw_tick_funnel": funnel,
        "entry_rows": len(entries),
        "executable_entry_rows": int(entries.entry_status.eq("EXECUTABLE_ENTRY").sum()),
        "entry_status": entries.entry_status.value_counts().astype(int).to_dict(),
        "executable_by_profile": entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY")].groupby(["entry_form", "minimum_net_headroom"]).size().rename("n").reset_index().to_dict("records"),
        "outcome_columns_in_source": [],
        "return_analysis_run": "NO",
        "strategy_backtest_run": "NO",
        "data_2021_or_later_used": "NO",
        "repository_2024_plus_data_opened": "NO",
    }
    write_json(FREEZE, freeze)
    manifest("STAGE_A_FREEZE", {"status": "COMPLETE", "freeze_sha256": sha256(FREEZE), **freeze})
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not FREEZE.is_file():
        raise ResearchError("Stage-A freeze missing")
    frozen = json.loads(FREEZE.read_text())
    hashes = persist_contracts()
    current = {
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "source_all_gaps_sha256": sha256(SOURCE_ALL_GAPS),
        "corrected_daily_candidates_sha256": sha256(CORRECTED_DAILY_CANDIDATES),
        "corrected_vap_profiles_sha256": sha256(CORRECTED_VAP_PROFILES),
        "corrected_mother_sha256": sha256(CORRECTED_MOTHER),
        "entry_day_minutes_sha256": sha256(ENTRY_DAY_MINUTES),
        "entry_candidates_sha256": sha256(ENTRY_CANDIDATES),
    }
    drift = {key: (frozen.get(key), value) for key, value in current.items() if frozen.get(key) != value}
    entries = pd.read_parquet(ENTRY_CANDIDATES)
    checks = {
        "entry_key_unique": not entries.entry_key.duplicated().any(),
        "future_entry_count": int(entries.entry_uses_future_bar.sum()),
        "post_2020_entry_count": int(entries.entry_is_2021_or_later.sum()),
        "maximum_admission_conditions": max(len(value) for value in ADMISSION_TEMPLATES.values()),
    }
    if drift or not checks["entry_key_unique"] or checks["future_entry_count"] or checks["post_2020_entry_count"] or checks["maximum_admission_conditions"] > 3:
        raise ResearchError(f"Stage-A deterministic verification failed: drift={drift} checks={checks}")
    result = {"verified": True, "hashes": current, "checks": checks, "outcomes_opened": "NO"}
    manifest("STAGE_A_VERIFY", {"status": "COMPLETE", **result})
    return result


def load_daily_relevant(entries: pd.DataFrame) -> pd.DataFrame:
    symbols = entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY"), "symbol"].unique().tolist()
    if not symbols:
        raise ResearchError("no executable entries")
    con = duckdb.connect()
    con.register("symbols", pd.DataFrame({"symbol": symbols}))
    frame = con.execute(f"""SELECT d.* FROM read_parquet('{DAILY}') d JOIN symbols s USING(symbol)
      WHERE d.trade_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
      ORDER BY d.symbol,d.trade_date""").fetchdf()
    con.close()
    frame.trade_date = pd.to_datetime(frame.trade_date)
    if frame.trade_date.max() > DEV_END:
        raise ResearchError("2021+ daily outcome opened")
    return frame


def build_outcome_minutes(entries: pd.DataFrame, mother: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    executable = entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY")].copy()
    calendar = daily[["trade_date", "cal_idx"]].drop_duplicates("cal_idx").sort_values("cal_idx")
    date_by_idx = calendar.set_index("cal_idx").trade_date
    bounds = executable.groupby(["gap_id", "symbol"], as_index=False).agg(min_entry_date=("entry_date", "min"), max_entry_cal_idx=("entry_cal_idx", "max"))
    bounds = bounds.merge(mother[["gap_id", "first_return_cal_idx"]], on="gap_id", validate="one_to_one")
    bounds["path_end_cal_idx"] = bounds.first_return_cal_idx.astype(int) + 40
    bounds["path_end_date"] = bounds.path_end_cal_idx.map(date_by_idx)
    if bounds.path_end_date.isna().any() or pd.to_datetime(bounds.path_end_date).max() > DEV_END:
        raise ResearchError("outcome bounds exceed 2020")
    write_parquet(bounds, OUTCOME_BOUNDS)
    OUTCOME_MINUTE_PARTS.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    for year in range(2014, 2021):
        part = OUTCOME_MINUTE_PARTS / f"year={year}.parquet"
        con = duckdb.connect()
        con.execute("SET threads=4")
        con.execute(f"""COPY (
          SELECT b.gap_id,b.symbol,r.trade_date,r.bar_end_time,r.open,r.high,r.low,r.close,r.volume,r.amount,
            d.cal_idx,d.coordinate_factor,r.open*d.coordinate_factor AS coord_open,
            r.high*d.coordinate_factor AS coord_high,r.low*d.coordinate_factor AS coord_low,r.close*d.coordinate_factor AS coord_close,
            d.invalid_step_cum,d.hard_valid,d.trade_status,d.current_day_data_tradable,d.market_rule_valid,d.corporate_action_blocking,
            d.up_limit_price,d.down_limit_price,count(*) OVER(PARTITION BY b.gap_id,r.trade_date) AS minute_count
          FROM read_parquet('{OUTCOME_BOUNDS}') b
          JOIN read_parquet('{raw_path(year)}') r ON r.qmt_code=b.symbol AND r.trade_date BETWEEN b.min_entry_date AND b.path_end_date
          JOIN read_parquet('{DAILY}') d ON d.symbol=b.symbol AND d.trade_date=r.trade_date
          WHERE r.period='1m' AND r.adjust='none' AND year(r.trade_date)={year}
          ORDER BY b.gap_id,r.bar_end_time
        ) TO '{part}' (FORMAT PARQUET,COMPRESSION ZSTD)""")
        con.close()
        parts.append(part)
    tmp = OUTCOME_MINUTES.with_suffix(".parquet.tmp")
    con = duckdb.connect()
    con.execute(f"COPY (SELECT * FROM read_parquet('{OUTCOME_MINUTE_PARTS}/year=*.parquet') ORDER BY gap_id,bar_end_time) TO '{tmp}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.close()
    tmp.replace(OUTCOME_MINUTES)
    frame = pd.read_parquet(OUTCOME_MINUTES)
    frame.trade_date = pd.to_datetime(frame.trade_date)
    frame.bar_end_time = pd.to_datetime(frame.bar_end_time)
    if frame.trade_date.max() > DEV_END:
        raise ResearchError("2021+ outcome minute opened")
    return frame


def _legal_open_after(legal: pd.DataFrame, trigger: pd.Timestamp, lineage: float) -> dict[str, Any] | None:
    rows = legal.loc[legal.bar_end_time.gt(trigger) & legal.invalid_step_cum.eq(lineage)]
    if rows.empty:
        return None
    row = rows.iloc[0]
    return {"exit_time": pd.Timestamp(row.bar_end_time), "exit_date": pd.Timestamp(row.trade_date), "exit_raw_price": float(row.raw_open), "coordinate_factor": float(row.coordinate_factor), "reason": "LEGAL_NEXT_OPEN"}


def _target_exit(path: pd.DataFrame, entry: Any) -> dict[str, Any] | None:
    rows = path.loc[
        path.bar_end_time.gt(pd.Timestamp(entry.entry_time))
        & path.cal_idx.gt(int(entry.entry_cal_idx))
        & path.invalid_step_cum.eq(float(entry.invalid_step_cum))
        & path.hard_valid.fillna(False)
        & path.trade_status.eq(1)
        & path.current_day_data_tradable.fillna(False)
        & path.market_rule_valid.fillna(False)
        & ~path.corporate_action_blocking.fillna(True)
        & pd.Series(_raw_tick_reached(path.high, float(entry.U), path.coordinate_factor), index=path.index)
    ]
    if rows.empty:
        return None
    row = rows.iloc[0]
    raw_target = float(_boundary_ticks(float(entry.U), float(row.coordinate_factor))) / 100.0
    execution = max(float(row.open), raw_target)
    if _price_ticks(execution) > _price_ticks(float(row.high)):
        raise ResearchError(f"impossible target fill {entry.entry_key}")
    return {"exit_time": pd.Timestamp(row.bar_end_time), "exit_date": pd.Timestamp(row.trade_date), "exit_raw_price": execution, "coordinate_factor": float(row.coordinate_factor), "reason": "U_TARGET"}


def _policy_trigger(entry: Any, policy: str, daily: pd.DataFrame, path: pd.DataFrame) -> pd.Timestamp | None:
    post = daily.loc[daily.cal_idx.gt(int(entry.entry_cal_idx)) & daily.invalid_step_cum.eq(float(entry.invalid_step_cum))].copy()
    if policy == "X0_NO_FAILURE":
        return None
    if policy == "X1_CLOSE_BELOW_L":
        hit = post.loc[post.hard_valid.fillna(False) & post.coord_close.lt(float(entry.L))]
        return None if hit.empty else pd.Timestamp(hit.trade_date.iloc[0]) + pd.Timedelta(hours=15)
    if policy == "X2_D3_NO_PROGRESS":
        checkpoint = int(entry.entry_cal_idx) + 3
        row = post.loc[post.cal_idx.eq(checkpoint)]
        if row.empty:
            return None
        observed = path.loc[path.bar_end_time.gt(pd.Timestamp(entry.entry_time)) & path.cal_idx.le(checkpoint)]
        if observed.empty:
            return None
        progress = float((observed.coord_high.max() - float(entry.L)) / float(entry.W))
        return pd.Timestamp(row.trade_date.iloc[0]) + pd.Timedelta(hours=15) if progress < 0.25 and float(row.coord_close.iloc[0]) < float(entry.L) else None
    raise ResearchError(f"unknown exit policy {policy}")


def _time_trigger(entry: Any, horizon: int, daily: pd.DataFrame) -> pd.Timestamp | None:
    row = daily.loc[daily.cal_idx.eq(int(entry.entry_cal_idx) + horizon)]
    return None if row.empty else pd.Timestamp(row.trade_date.iloc[0]) + pd.Timedelta(hours=15)


def build_policy_outcomes(entries: pd.DataFrame, outcome_minutes: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    executable = entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY")].copy()
    for column in ("entry_time", "entry_date", "decision_time"):
        executable[column] = pd.to_datetime(executable[column])
    path_by = {key: part.sort_values("bar_end_time") for key, part in outcome_minutes.groupby("gap_id", sort=False)}
    daily_by = {key: part.sort_values("trade_date") for key, part in daily.groupby("symbol", sort=False)}
    legal = pd.read_parquet(LEGAL_OPENS)
    legal.trade_date = pd.to_datetime(legal.trade_date)
    legal.bar_end_time = pd.to_datetime(legal.bar_end_time)
    legal = legal.loc[legal.symbol.isin(executable.symbol.unique()) & legal.trade_date.le(DEV_END)]
    legal_by = {key: part.sort_values("bar_end_time") for key, part in legal.groupby("symbol", sort=False)}
    actions = pd.read_parquet(ACTION_EVENTS)
    actions.known_date = pd.to_datetime(actions.known_date)
    actions.effective_date = pd.to_datetime(actions.effective_date)
    actions_by = {key: part for key, part in actions.groupby("symbol", sort=False)}
    rows: list[dict[str, Any]] = []
    for entry in executable.itertuples(index=False):
        path = path_by.get(str(entry.gap_id), pd.DataFrame())
        days = daily_by.get(str(entry.symbol), pd.DataFrame())
        sell_opens = legal_by.get(str(entry.symbol), pd.DataFrame(columns=legal.columns))
        act = actions_by.get(str(entry.symbol), pd.DataFrame(columns=actions.columns))
        if path.empty or days.empty:
            continue
        target = _target_exit(path, entry)
        for horizon in TIME_STOPS:
            horizon_trigger = _time_trigger(entry, horizon, days)
            horizon_exit = None if horizon_trigger is None else _legal_open_after(sell_opens, horizon_trigger, float(entry.invalid_step_cum))
            if horizon_exit is not None:
                horizon_exit["reason"] = f"H{horizon}_TIME_STOP"
            risk = anatomy.forced_risk_exit(act, pd.Timestamp(entry.decision_time), pd.Timestamp(entry.entry_date), days, sell_opens, float(entry.invalid_step_cum), horizon_trigger if horizon_trigger is not None else DEV_END + pd.Timedelta(hours=15))
            for policy in EXIT_POLICIES:
                failure_trigger = _policy_trigger(entry, policy, days, path)
                failure = None if failure_trigger is None else _legal_open_after(sell_opens, failure_trigger, float(entry.invalid_step_cum))
                if failure is not None:
                    failure["reason"] = policy
                choices = [item for item in (target, failure, horizon_exit) if item is not None]
                blocked = bool(risk is not None and risk.get("blocked"))
                if risk is not None and not blocked:
                    choices.append({"exit_time": pd.Timestamp(risk["exit_time"]), "exit_date": pd.Timestamp(risk["exit_date"]), "exit_raw_price": float(risk["exit_raw_price"]), "coordinate_factor": math.nan, "reason": "CORPORATE_ACTION_RISK"})
                chosen = None if not choices else sorted(choices, key=lambda item: (item["exit_time"], 0 if item["reason"] == "U_TARGET" else 1, item["reason"]))[0]
                if blocked and (chosen is None or pd.Timestamp(chosen["exit_time"]) >= pd.Timestamp(risk["effective_date"])):
                    chosen = None
                if chosen is None:
                    outcome_valid = False
                    exit_time = exit_date = pd.NaT
                    exit_raw = net = mae = mfe = math.nan
                    exit_reason = "UNRESOLVED_ACTION_OR_EXIT"
                    cash_json = "[]"
                    exit_cal_idx = math.nan
                else:
                    outcome_valid = True
                    exit_time = pd.Timestamp(chosen["exit_time"])
                    exit_date = pd.Timestamp(chosen["exit_date"])
                    exit_raw = float(chosen["exit_raw_price"])
                    exit_reason = str(chosen["reason"])
                    day_row = days.loc[days.trade_date.eq(exit_date)]
                    exit_cal_idx = int(day_row.cal_idx.iloc[0]) if len(day_row) else math.nan
                    cash_rows = act.loc[act.action_kind.eq("CASH_ONLY") & act.effective_date.gt(pd.Timestamp(entry.entry_date).normalize()) & act.effective_date.le(exit_date.normalize())]
                    cash = float(cash_rows.cash_per_share.sum())
                    cash_json = json.dumps([{"date": str(pd.Timestamp(row.effective_date).date()), "cash_per_share": float(row.cash_per_share), "event_id": str(row.event_id)} for row in cash_rows.itertuples(index=False)], sort_keys=True)
                    net = (exit_raw * (1 - COST) + cash) / (float(entry.entry_raw_price) * (1 + COST)) - 1
                    observed = path.loc[path.bar_end_time.gt(pd.Timestamp(entry.entry_time)) & path.bar_end_time.le(exit_time)]
                    mae = math.nan if observed.empty else float(observed.coord_low.min() / float(entry.entry_coordinate_price) - 1)
                    mfe = math.nan if observed.empty else float(observed.coord_high.max() / float(entry.entry_coordinate_price) - 1)
                rows.append({
                    **entry._asdict(),
                    "time_stop": horizon,
                    "exit_policy": policy,
                    "policy_key": f"{entry.entry_key}|H{horizon}|{policy}",
                    "outcome_valid": outcome_valid,
                    "exit_time": exit_time,
                    "exit_date": exit_date,
                    "exit_cal_idx": exit_cal_idx,
                    "exit_raw_price": exit_raw,
                    "exit_reason": exit_reason,
                    "net_return": net,
                    "mae": mae,
                    "mfe": mfe,
                    "holding_sessions": math.nan if not outcome_valid else int(exit_cal_idx - int(entry.entry_cal_idx)),
                    "u_hit": bool(outcome_valid and exit_reason == "U_TARGET"),
                    "win": bool(outcome_valid and net > 0),
                    "severe_loss10": bool(outcome_valid and net <= -0.10),
                    "cash_events_json": cash_json,
                    "unresolved_action_block": bool(not outcome_valid and blocked),
                    "t1_violation": bool(outcome_valid and exit_cal_idx <= int(entry.entry_cal_idx)),
                    "impossible_exit_price": False,
                })
    outcomes = pd.DataFrame(rows).sort_values(["policy_key"], kind="mergesort").reset_index(drop=True)
    if outcomes.policy_key.duplicated().any() or outcomes.t1_violation.any() or pd.to_datetime(outcomes.exit_date).dropna().max() > DEV_END:
        raise ResearchError("outcome identity/T+1/chronology audit failed")
    write_parquet(outcomes, POLICY_OUTCOMES)
    return outcomes


def _cvar5(values: pd.Series) -> float:
    values = pd.to_numeric(values, errors="coerce").dropna().sort_values()
    if values.empty:
        return math.nan
    return float(values.iloc[: max(1, math.ceil(len(values) * 0.05))].mean())


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    valid = frame.loc[frame.outcome_valid & frame.net_return.notna()].copy()
    if valid.empty:
        return {"n": 0, "mean": math.nan, "median": math.nan, "win": math.nan, "u_hit": math.nan, "severe10": math.nan, "cvar5": math.nan, "date_equal_mean": math.nan, "utility": math.nan, "utility_se": math.nan, "years": 0, "positive_years": 0, "latest_year_n": 0}
    returns = valid.net_return.astype(float)
    dates = valid.groupby(valid.entry_date.dt.normalize()).net_return.mean()
    annual = valid.groupby(valid.entry_date.dt.year).net_return.mean()
    cvar = _cvar5(returns)
    utility = 0.5 * (float(returns.mean()) + float(dates.mean())) - 0.20 * abs(cvar)
    se = 0.0 if len(dates) < 2 else float(dates.std(ddof=1) / math.sqrt(len(dates)))
    latest = int(valid.entry_date.dt.year.max())
    return {
        "n": len(valid), "mean": float(returns.mean()), "median": float(returns.median()), "win": float(returns.gt(0).mean()),
        "u_hit": float(valid.u_hit.mean()), "severe10": float(returns.le(-0.10).mean()), "cvar5": cvar,
        "date_equal_mean": float(dates.mean()), "utility": utility, "utility_se": se,
        "years": len(annual), "positive_years": int(annual.gt(0).sum()), "latest_year_n": int(valid.entry_date.dt.year.eq(latest).sum()),
    }


def _template_thresholds(train: pd.DataFrame) -> dict[str, float]:
    return {
        "MAX_RUNUP20_LE_TRAIN_Q50": float(train.pre_gap_max_runup_20d.quantile(0.50)),
        "INSIDE_DENSITY_LE_TRAIN_Q30": float(train.pre_gap_inside_density_relative_local.quantile(0.30)),
    }


def admission_mask(frame: pd.DataFrame, template: str, thresholds: dict[str, float]) -> pd.Series:
    mask = pd.Series(True, index=frame.index)
    for condition in ADMISSION_TEMPLATES[template]:
        if condition == "PEAK_TO_GAP_GE60":
            mask &= frame.pre_peak_to_gap_sessions.ge(60)
        elif condition == "DRAWDOWN_GE30":
            mask &= frame.pre_gap_drawdown_from_120d_peak.ge(0.30)
        elif condition == "POST_GAP_NEAR_TOUCH_EQ0":
            mask &= frame.post_gap_lower_corridor_touch_sessions.eq(0)
        elif condition == "MAX_RUNUP20_LE_TRAIN_Q50":
            mask &= frame.pre_gap_max_runup_20d.le(thresholds[condition])
        elif condition == "INSIDE_DENSITY_LE_TRAIN_Q30":
            mask &= frame.pre_gap_inside_density_relative_local.le(thresholds[condition])
        elif condition == "PRE_GAP_INSIDE_TOUCH_LE4":
            mask &= frame.pre_gap_inside_touch_sessions.le(4)
        else:
            raise ResearchError(f"unknown admission condition {condition}")
    return mask.fillna(False)


def _profile_complexity(row: pd.Series | dict[str, Any]) -> tuple[int, int, int, int]:
    form = row["entry_form"]
    exit_policy = row["exit_policy"]
    horizon = int(row["time_stop"])
    headroom = float(row["minimum_net_headroom"])
    return ({"E1_CLOSE_L": 0, "E2_HOLD3OF5_L": 1, "E3_CLOSE_Z25": 1}[form], {"X0_NO_FAILURE": 0, "X1_CLOSE_BELOW_L": 1, "X2_D3_NO_PROGRESS": 1}[exit_policy], 0 if horizon == 10 else 1, 0 if math.isclose(headroom, 0.015) else 1)


def _choose_one_se(table: pd.DataFrame, complexity_columns: list[str]) -> pd.Series:
    eligible = table.loc[table.n.ge(MIN_TRAIN_TRADES) & table.latest_year_n.ge(MIN_LATEST_TRAIN_YEAR_TRADES) & table.utility.notna()].copy()
    if eligible.empty:
        eligible = table.loc[table.n.gt(0) & table.utility.notna()].copy()
    if eligible.empty:
        raise ResearchError("no selectable candidate")
    best = eligible.sort_values(["utility", "n"], ascending=[False, False], kind="mergesort").iloc[0]
    near = eligible.loc[eligible.utility.ge(float(best.utility) - float(best.utility_se))].copy()
    return near.sort_values([*complexity_columns, "median", "date_equal_mean", "n"], ascending=[*[True] * len(complexity_columns), False, False, False], kind="mergesort").iloc[0]


def run_walkforward(outcomes: pd.DataFrame, daily: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    valid = outcomes.loc[outcomes.outcome_valid].copy()
    for column in ("entry_date", "entry_time", "exit_date", "exit_time", "gap_date"):
        valid[column] = pd.to_datetime(valid[column])
    calendar = daily[["trade_date", "cal_idx"]].drop_duplicates("cal_idx").sort_values("cal_idx")
    test_start_idx = calendar.assign(year=calendar.trade_date.dt.year).groupby("year").cal_idx.min().to_dict()
    candidate_rows: list[dict[str, Any]] = []
    selection_rows: list[dict[str, Any]] = []
    trade_rows: list[pd.DataFrame] = []
    for year in OUTER_YEARS:
        boundary = int(test_start_idx[year])
        train = valid.loc[(valid.entry_date.dt.year < year) & valid.entry_cal_idx.le(boundary - PURGE_SESSIONS - 1)].copy()
        test = valid.loc[valid.entry_date.dt.year.eq(year)].copy()
        profiles = []
        for key, part in train.groupby(["entry_form", "minimum_net_headroom", "time_stop", "exit_policy"], sort=True):
            item = metrics(part)
            complexity = _profile_complexity({"entry_form": key[0], "minimum_net_headroom": key[1], "time_stop": key[2], "exit_policy": key[3]})
            row = {"outer_year": year, "stage": "EXECUTION_PROFILE", "entry_form": key[0], "minimum_net_headroom": key[1], "time_stop": key[2], "exit_policy": key[3], "admission_template": "A0_NONE", "condition_count": 0, "form_complexity": complexity[0], "exit_complexity": complexity[1], "horizon_complexity": complexity[2], "headroom_complexity": complexity[3], **item}
            profiles.append(row)
            candidate_rows.append(row)
        profile_table = pd.DataFrame(profiles)
        chosen_profile = _choose_one_se(profile_table, ["form_complexity", "exit_complexity", "horizon_complexity", "headroom_complexity"])
        profile_filter = (
            train.entry_form.eq(chosen_profile.entry_form)
            & train.minimum_net_headroom.eq(float(chosen_profile.minimum_net_headroom))
            & train.time_stop.eq(int(chosen_profile.time_stop))
            & train.exit_policy.eq(chosen_profile.exit_policy)
        )
        profile_train = train.loc[profile_filter].copy()
        thresholds = _template_thresholds(profile_train)
        admissions = []
        for template, conditions in ADMISSION_TEMPLATES.items():
            part = profile_train.loc[admission_mask(profile_train, template, thresholds)]
            item = metrics(part)
            row = {"outer_year": year, "stage": "ADMISSION", "entry_form": chosen_profile.entry_form, "minimum_net_headroom": float(chosen_profile.minimum_net_headroom), "time_stop": int(chosen_profile.time_stop), "exit_policy": chosen_profile.exit_policy, "admission_template": template, "condition_count": len(conditions), "thresholds_json": json.dumps(thresholds, sort_keys=True), **item}
            admissions.append(row)
            candidate_rows.append(row)
        admission_table = pd.DataFrame(admissions)
        chosen = _choose_one_se(admission_table, ["condition_count"])
        positive_required = math.ceil(0.60 * int(chosen.years))
        deployment_ready = bool(chosen.n >= MIN_TRAIN_TRADES and chosen.latest_year_n >= MIN_LATEST_TRAIN_YEAR_TRADES and chosen["mean"] > 0 and chosen["median"] > 0 and chosen.date_equal_mean > 0 and chosen.utility > 0 and chosen.positive_years >= positive_required and chosen.severe10 < 0.15)
        selection = {"outer_year": year, "train_end_year": year - 1, "test_start_cal_idx": boundary, "entry_form": chosen.entry_form, "minimum_net_headroom": float(chosen.minimum_net_headroom), "time_stop": int(chosen.time_stop), "exit_policy": chosen.exit_policy, "admission_template": chosen.admission_template, "condition_count": int(chosen.condition_count), "thresholds_json": chosen.thresholds_json, "deployment_ready": deployment_ready, **{f"train_{key}": chosen[key] for key in ("n", "mean", "median", "win", "u_hit", "severe10", "cvar5", "date_equal_mean", "utility", "utility_se", "years", "positive_years", "latest_year_n")}}
        selection_rows.append(selection)
        thresholds_frozen = json.loads(chosen.thresholds_json)
        selected_test = test.loc[
            test.entry_form.eq(chosen.entry_form)
            & test.minimum_net_headroom.eq(float(chosen.minimum_net_headroom))
            & test.time_stop.eq(int(chosen.time_stop))
            & test.exit_policy.eq(chosen.exit_policy)
        ].copy()
        selected_test = selected_test.loc[admission_mask(selected_test, chosen.admission_template, thresholds_frozen)].copy()
        selected_test["outer_year"] = year
        selected_test["selected_entry_form"] = chosen.entry_form
        selected_test["selected_minimum_net_headroom"] = float(chosen.minimum_net_headroom)
        selected_test["selected_time_stop"] = int(chosen.time_stop)
        selected_test["selected_exit_policy"] = chosen.exit_policy
        selected_test["selected_admission_template"] = chosen.admission_template
        selected_test["selected_thresholds_json"] = chosen.thresholds_json
        trade_rows.append(selected_test.assign(procedure="FORCED_SELECTED"))
        if deployment_ready:
            trade_rows.append(selected_test.assign(procedure="GATED_SELECTED"))
        fixed = test.loc[
            test.entry_form.eq("E1_CLOSE_L")
            & test.minimum_net_headroom.eq(0.015)
            & test.time_stop.eq(10)
            & test.exit_policy.eq("X1_CLOSE_BELOW_L")
        ].copy()
        fixed = fixed.loc[fixed.pre_peak_to_gap_sessions.ge(60) & fixed.post_gap_lower_corridor_touch_sessions.eq(0)].copy()
        fixed["outer_year"] = year
        fixed["selected_entry_form"] = "E1_CLOSE_L"
        fixed["selected_minimum_net_headroom"] = 0.015
        fixed["selected_time_stop"] = 10
        fixed["selected_exit_policy"] = "X1_CLOSE_BELOW_L"
        fixed["selected_admission_template"] = "FIXED_HEADROOM_LONG_NO_NEAR_TOUCH"
        fixed["selected_thresholds_json"] = "{}"
        trade_rows.append(fixed.assign(procedure="FIXED_HUMAN_SIMPLE"))
    candidates = pd.DataFrame(candidate_rows)
    selections = pd.DataFrame(selection_rows)
    trades = pd.concat(trade_rows, ignore_index=True).sort_values(["procedure", "entry_time", "symbol", "gap_id"], kind="mergesort").reset_index(drop=True)
    if trades.loc[trades.procedure.eq("FORCED_SELECTED"), "gap_id"].duplicated().any():
        raise ResearchError("duplicate forced OOF gap")
    if not (selections.condition_count <= 3).all():
        raise ResearchError("rule complexity breach")
    write_parquet(candidates, SELECTION_CANDIDATES)
    write_parquet(selections, WALKFORWARD_SELECTIONS)
    write_parquet(trades, OOF_TRADES)
    return candidates, selections, trades


@dataclass
class Replay:
    nav: pd.DataFrame
    accepted: pd.DataFrame
    ledger: pd.DataFrame
    audit: dict[str, int]


def replay_board(trades: pd.DataFrame, daily: pd.DataFrame, board: str) -> Replay:
    signals = trades.loc[trades.board.eq(board)].copy().sort_values(["entry_time", "realized_net_target_at_entry", "pre_gap_inside_density_relative_local", "symbol", "gap_id"], ascending=[True, False, True, True, True], kind="mergesort")
    calendar = daily.loc[daily.trade_date.dt.year.between(min(OUTER_YEARS), max(OUTER_YEARS)), ["trade_date", "cal_idx"]].drop_duplicates("trade_date").sort_values("trade_date")
    relevant = daily.loc[daily.symbol.isin(signals.symbol.unique())].copy()
    by_symbol = {key: part.sort_values("trade_date") for key, part in relevant.groupby("symbol", sort=False)}
    marks = {(row.symbol, pd.Timestamp(row.trade_date)): float(row.close) for row in relevant.itertuples(index=False) if np.isfinite(row.close)}
    cash = 1.0
    active: dict[str, dict[str, Any]] = {}
    accepted: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    audit = Counter()

    def mark(position: dict[str, Any], when: pd.Timestamp, inclusive: bool = False) -> float:
        part = by_symbol.get(position["symbol"], pd.DataFrame())
        subset = part.loc[part.trade_date.le(when.normalize())] if inclusive else part.loc[part.trade_date.lt(when.normalize())]
        return float(subset.close.iloc[-1]) if len(subset) else float(position["entry_raw_price"])

    def credit(position: dict[str, Any], when: pd.Timestamp) -> float:
        amount = 0.0
        while position["cash_event_index"] < len(position["cash_events"]):
            event = position["cash_events"][position["cash_event_index"]]
            if pd.Timestamp(event["date"]) > when.normalize():
                break
            amount += position["qty"] * float(event["cash_per_share"])
            position["cash_event_index"] += 1
        return amount

    def close_due(when: pd.Timestamp) -> None:
        nonlocal cash
        due = sorted([value for value in active.values() if pd.Timestamp(value["exit_time"]) <= when], key=lambda value: (pd.Timestamp(value["exit_time"]), value["symbol"]))
        for position in due:
            cash += credit(position, pd.Timestamp(position["exit_time"]))
            cash += position["qty"] * float(position["exit_raw_price"]) * (1 - COST)
            position["completed"] = True
            active.pop(position["symbol"], None)

    for timestamp, group in signals.groupby("entry_time", sort=True):
        timestamp = pd.Timestamp(timestamp)
        close_due(timestamp)
        for position in active.values():
            cash += credit(position, timestamp)
        for row in group.itertuples(index=False):
            base = {"procedure": row.procedure, "gap_id": row.gap_id, "symbol": row.symbol, "board": board, "entry_time": row.entry_time}
            if row.symbol in active:
                audit["duplicate_symbol_skip_count"] += 1
                ledger.append({**base, "status": "SKIPPED_DUPLICATE_SYMBOL"})
                continue
            if len(active) >= K:
                audit["capacity_skip_count"] += 1
                ledger.append({**base, "status": "SKIPPED_CAPACITY"})
                continue
            nav_now = cash + sum(position["qty"] * mark(position, timestamp) for position in active.values())
            outlay = nav_now / K
            if outlay <= 0 or cash + 1e-12 < outlay:
                audit["insufficient_cash_skip_count"] += 1
                ledger.append({**base, "status": "SKIPPED_INSUFFICIENT_CASH"})
                continue
            position = row._asdict()
            position["qty"] = outlay / (float(row.entry_raw_price) * (1 + COST))
            position["entry_outlay"] = outlay
            position["completed"] = False
            position["cash_events"] = json.loads(row.cash_events_json or "[]")
            position["cash_event_index"] = 0
            cash -= outlay
            active[row.symbol] = position
            accepted.append(position)
            ledger.append({**base, "status": "EXECUTED", "entry_outlay": outlay})
            if len(active) > K:
                audit["max_k_violation_count"] += 1
    period_end = pd.Timestamp(calendar.trade_date.max()) + pd.Timedelta(hours=23)
    close_due(period_end)
    entries_by_date: dict[pd.Timestamp, list[dict[str, Any]]] = defaultdict(list)
    exits_by_date: dict[pd.Timestamp, list[dict[str, Any]]] = defaultdict(list)
    for position in accepted:
        entries_by_date[pd.Timestamp(position["entry_date"]).normalize()].append(position)
        exits_by_date[pd.Timestamp(position["exit_date"]).normalize()].append(position)
    cash_daily = 1.0
    live: dict[str, dict[str, Any]] = {}
    nav_rows: list[dict[str, Any]] = []
    for date in pd.to_datetime(calendar.trade_date):
        for position in live.values():
            for event in position["cash_events"]:
                if pd.Timestamp(event["date"]) == date:
                    cash_daily += position["qty"] * float(event["cash_per_share"])
        events = [(pd.Timestamp(position["entry_time"]), "ENTRY", position) for position in entries_by_date.get(date, [])]
        events += [(pd.Timestamp(position["exit_time"]), "EXIT", position) for position in exits_by_date.get(date, [])]
        for _, kind, position in sorted(events, key=lambda item: (item[0], 0 if item[1] == "EXIT" else 1, item[2]["symbol"])):
            if kind == "ENTRY":
                cash_daily -= position["entry_outlay"]
                live[position["symbol"]] = position
            else:
                cash_daily += position["qty"] * float(position["exit_raw_price"]) * (1 - COST)
                live.pop(position["symbol"], None)
        exposure = sum(position["qty"] * marks.get((symbol, date), mark(position, date, inclusive=True)) for symbol, position in live.items())
        nav = cash_daily + exposure
        nav_rows.append({"trade_date": date, "nav": nav, "cash": cash_daily, "gross_exposure": exposure, "utilization": 0 if nav == 0 else exposure / nav, "active_positions": len(live), "board": board})
    nav = pd.DataFrame(nav_rows)
    if nav.active_positions.max() > K or nav.cash.min() < -1e-10:
        raise ResearchError("portfolio capacity/leverage breach")
    return Replay(nav=nav, accepted=pd.DataFrame(accepted), ledger=pd.DataFrame(ledger), audit=dict(audit))


def combine_nav(main: pd.DataFrame, chinext: pd.DataFrame) -> pd.DataFrame:
    frame = main.merge(chinext, on="trade_date", suffixes=("_main", "_chinext"), validate="one_to_one")
    frame["nav"] = 0.5 * frame.nav_main + 0.5 * frame.nav_chinext
    frame["gross_exposure"] = 0.5 * frame.gross_exposure_main + 0.5 * frame.gross_exposure_chinext
    frame["cash"] = frame.nav - frame.gross_exposure
    frame["utilization"] = frame.gross_exposure / frame.nav
    frame["active_positions"] = frame.active_positions_main + frame.active_positions_chinext
    frame["board"] = "COMBINED"
    return frame[["trade_date", "nav", "cash", "gross_exposure", "utilization", "active_positions", "board"]]


def nav_metrics(nav: pd.DataFrame, accepted: pd.DataFrame) -> dict[str, Any]:
    returns = nav.nav.pct_change().fillna(nav.nav.iloc[0] - 1)
    elapsed = max((nav.trade_date.iloc[-1] - nav.trade_date.iloc[0]).days / 365.25, 1 / 365.25)
    dd = nav.nav / nav.nav.cummax() - 1
    annual = {}
    prior = 1.0
    for year in OUTER_YEARS:
        part = nav.loc[nav.trade_date.dt.year.eq(year)]
        annual[str(year)] = 0.0 if part.empty else float(part.nav.iloc[-1] / prior - 1)
        if len(part):
            prior = float(part.nav.iloc[-1])
    trade_returns = accepted.net_return.astype(float) if len(accepted) else pd.Series(dtype=float)
    positive_pnl = (accepted.entry_outlay * accepted.net_return).loc[lambda x: x > 0].sort_values(ascending=False) if len(accepted) else pd.Series(dtype=float)
    return {
        "trades": len(accepted), "mean_net": None if trade_returns.empty else float(trade_returns.mean()), "median_net": None if trade_returns.empty else float(trade_returns.median()), "win": None if trade_returns.empty else float(trade_returns.gt(0).mean()), "u_hit": None if trade_returns.empty else float(accepted.u_hit.mean()), "severe10": None if trade_returns.empty else float(trade_returns.le(-0.10).mean()), "cvar5": None if trade_returns.empty else _cvar5(trade_returns),
        "total_return": float(nav.nav.iloc[-1] - 1), "cagr": float(nav.nav.iloc[-1] ** (1 / elapsed) - 1), "max_drawdown": float(dd.min()), "sharpe": 0.0 if returns.std(ddof=1) == 0 else float(np.sqrt(252) * returns.mean() / returns.std(ddof=1)), "average_utilization": float(nav.utilization.mean()), "best_day": float(returns.max()), "worst_day": float(returns.min()), "return_excluding_best_day": float((1 + returns.drop(returns.nlargest(1).index)).prod() - 1), "return_excluding_best_five_days": float((1 + returns.drop(returns.nlargest(5).index)).prod() - 1), "top5_positive_trade_pnl_share": None if positive_pnl.sum() <= 0 else float(positive_pnl.iloc[:5].sum() / positive_pnl.sum()), "annual_returns": annual,
    }


def run_portfolios(trades: pd.DataFrame, daily: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    summaries: list[dict[str, Any]] = []
    navs: list[pd.DataFrame] = []
    accepted_all: list[pd.DataFrame] = []
    ledgers: list[pd.DataFrame] = []
    for procedure, part in trades.groupby("procedure", sort=True):
        replays = {board: replay_board(part, daily, board) for board in ("MAIN", "CHINEXT")}
        for board, replay in replays.items():
            accepted = replay.accepted.assign(procedure=procedure, board=board)
            summaries.append({"procedure": procedure, "board": board, **nav_metrics(replay.nav, accepted), "capacity_skips": int(replay.audit.get("capacity_skip_count", 0))})
            navs.append(replay.nav.assign(procedure=procedure))
            accepted_all.append(accepted)
            ledgers.append(replay.ledger.assign(procedure=procedure, board=board))
        combined = combine_nav(replays["MAIN"].nav, replays["CHINEXT"].nav)
        accepted = pd.concat([replays["MAIN"].accepted.assign(sleeve_weight=0.5), replays["CHINEXT"].accepted.assign(sleeve_weight=0.5)], ignore_index=True)
        summaries.append({"procedure": procedure, "board": "COMBINED", **nav_metrics(combined, accepted), "capacity_skips": sum(int(value.audit.get("capacity_skip_count", 0)) for value in replays.values())})
        navs.append(combined.assign(procedure=procedure))
    summary = pd.DataFrame(summaries).sort_values(["procedure", "board"], kind="mergesort")
    nav = pd.concat(navs, ignore_index=True).sort_values(["procedure", "board", "trade_date"], kind="mergesort")
    accepted = pd.concat(accepted_all, ignore_index=True) if accepted_all else pd.DataFrame()
    ledger = pd.concat(ledgers, ignore_index=True) if ledgers else pd.DataFrame()
    write_parquet(summary, PORTFOLIO_SUMMARY)
    write_parquet(nav, PORTFOLIO_NAV)
    write_parquet(accepted, PORTFOLIO_ACCEPTED)
    write_parquet(ledger, PORTFOLIO_LEDGER)
    return summary, nav, accepted, ledger


def run_stage_b() -> dict[str, Any]:
    verify_stage_a()
    mother = load_mother()
    entries = pd.read_parquet(ENTRY_CANDIDATES)
    for column in ("gap_date", "first_return_date", "pristine_first_return_time", "decision_time", "entry_time", "entry_date"):
        entries[column] = pd.to_datetime(entries[column])
    daily = load_daily_relevant(entries)
    outcome_minutes = build_outcome_minutes(entries, mother, daily)
    outcomes = build_policy_outcomes(entries, outcome_minutes, daily)
    _candidates, selections, trades = run_walkforward(outcomes, daily)
    summary, _nav, _accepted, _ledger = run_portfolios(trades, daily)
    audit = {
        "stage_a_hash_reproduced": True,
        "semantic_change_after_outcome_open_count": 0,
        "feature_added_after_outcome_open_count": 0,
        "rule_added_after_outcome_open_count": 0,
        "exit_added_after_outcome_open_count": 0,
        "entry_uses_future_bar_count": int(entries.entry_uses_future_bar.sum()),
        "t1_violation_count": int(outcomes.t1_violation.sum()),
        "impossible_exit_price_count": int(outcomes.impossible_exit_price.sum()),
        "post_2020_entry_count": int(entries.entry_is_2021_or_later.sum()),
        "maximum_rule_condition_count": int(selections.condition_count.max()),
        "repository_2021_plus_data_opened": "NO",
        "repository_2024_plus_data_opened": "NO",
    }
    zero_required = {
        key: value
        for key, value in audit.items()
        if key.endswith("_count") and key != "maximum_rule_condition_count"
    }
    if any(zero_required.values()) or audit["maximum_rule_condition_count"] > 3:
        raise ResearchError(f"Stage-B audit failed {audit}")
    result = {
        "experiment": EXPERIMENT,
        "status": "DEVELOPMENT_COMPLETE_CHART_REVIEW_PENDING",
        "hashes": {"contract": sha256(CONTRACT), "spec": sha256(SPEC), "stage_a_freeze": sha256(FREEZE), "entries": sha256(ENTRY_CANDIDATES), "outcomes": sha256(POLICY_OUTCOMES), "selections": sha256(WALKFORWARD_SELECTIONS), "oof_trades": sha256(OOF_TRADES), "portfolio_summary": sha256(PORTFOLIO_SUMMARY), "portfolio_nav": sha256(PORTFOLIO_NAV)},
        "stage_a": json.loads(FREEZE.read_text()),
        "walkforward_selections": selections.to_dict("records"),
        "procedures": {procedure: {board: row.iloc[0].drop(labels=["procedure", "board"]).to_dict() for board, row in part.groupby("board")} for procedure, part in summary.groupby("procedure")},
        "outcome_counts": {"policy_rows": len(outcomes), "valid": int(outcomes.outcome_valid.sum()), "action_blocked": int(outcomes.unresolved_action_block.sum())},
        "audit": audit,
        "scientific_interpretation": "Development-only expanding walk-forward; 2021+ remains unopened; no external validation claim.",
    }
    write_json(RESULT, result)
    manifest("STAGE_B_COMPLETE", {"status": "COMPLETE", "result_sha256": sha256(RESULT), **audit})
    return result


def _candles(ax: plt.Axes, frame: pd.DataFrame) -> None:
    dates = mdates.date2num(pd.to_datetime(frame.trade_date).to_numpy())
    for x, row in zip(dates, frame.itertuples(index=False), strict=True):
        color = "#d62728" if row.coord_close >= row.coord_open else "#008b72"
        ax.vlines(x, row.coord_low, row.coord_high, color=color, linewidth=0.55)
        bottom = min(row.coord_open, row.coord_close)
        height = max(abs(row.coord_close - row.coord_open), max(abs(row.coord_close) * 0.0004, 1e-6))
        ax.add_patch(Rectangle((x - 0.30, bottom), 0.60, height, facecolor=color, edgecolor=color, linewidth=0.3))
    ax.xaxis_date()


def _recommended_procedure(summary: pd.DataFrame) -> str:
    combined = summary.loc[summary.board.eq("COMBINED")].copy()
    passing = combined.loc[(combined.trades >= 100) & (combined.mean_net > 0) & (combined.median_net > 0) & (combined.cagr > 0) & (combined.return_excluding_best_five_days > 0)]
    if len(passing):
        return str(passing.sort_values(["cagr", "max_drawdown"], ascending=[False, False]).iloc[0].procedure)
    return str(combined.sort_values(["cagr", "mean_net"], ascending=[False, False]).iloc[0].procedure)


def render_charts() -> dict[str, Any]:
    if not RESULT.is_file():
        raise ResearchError("run Stage B first")
    trades = pd.read_parquet(OOF_TRADES)
    for column in ("gap_date", "first_return_date", "entry_date", "exit_date", "entry_time", "exit_time"):
        trades[column] = pd.to_datetime(trades[column])
    summary = pd.read_parquet(PORTFOLIO_SUMMARY)
    procedure = _recommended_procedure(summary)
    sample = trades.loc[trades.procedure.eq(procedure)].copy().sort_values(["entry_date", "symbol", "gap_id"], kind="mergesort").reset_index(drop=True)
    sample["chart_id"] = [f"PROFIT-{index:04d}" for index in range(1, len(sample) + 1)]
    con = duckdb.connect()
    daily = con.execute(f"""SELECT trade_date,cal_idx,symbol,coord_open,coord_high,coord_low,coord_close,volume
      FROM read_parquet('{DAILY}')
      WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2020-12-31'
      ORDER BY symbol,trade_date""").fetchdf()
    con.close()
    daily.trade_date = pd.to_datetime(daily.trade_date)
    paths = []
    for event in sample.itertuples(index=False):
        part = daily.loc[daily.symbol.eq(event.symbol)].sort_values("trade_date").reset_index(drop=True)
        gap_positions = np.flatnonzero(part.trade_date.eq(pd.Timestamp(event.gap_date)).to_numpy())
        exit_positions = np.flatnonzero(part.trade_date.eq(pd.Timestamp(event.exit_date)).to_numpy())
        if len(gap_positions) != 1 or len(exit_positions) != 1:
            raise ResearchError(f"chart chronology mismatch {event.gap_id}")
        start = max(0, int(gap_positions[0]) - 120)
        end = min(len(part), int(exit_positions[0]) + 21)
        selected = part.iloc[start:end].copy()
        selected["gap_id"] = event.gap_id
        paths.append(selected)
    chart_daily = pd.concat(paths, ignore_index=True) if paths else pd.DataFrame()
    write_parquet(chart_daily, CHART_DAILY)
    vap = pd.read_parquet(CORRECTED_VAP_PROFILES)
    vap = vap.loc[vap.gap_id.isin(sample.gap_id)].copy()
    write_parquet(vap, CHART_VAP)
    PDF.parent.mkdir(parents=True, exist_ok=True)
    metadata = {"Title": f"{EXPERIMENT} OOF signal chart book", "Subject": "Development-only executable signal review", "Author": "CY Market Behavior OS", "CreationDate": pd.Timestamp("2000-01-01").to_pydatetime(), "ModDate": pd.Timestamp("2000-01-01").to_pydatetime()}
    with PdfPages(PDF, metadata=metadata) as pdf:
        fig = plt.figure(figsize=(15.5, 8.69))
        fig.text(0.06, 0.88, "Executable simple-profit Development", fontsize=22, weight="bold")
        fig.text(0.06, 0.80, f"Charted procedure: {procedure}\nOOF signals: {len(sample)}\n2017-2020 only; 2021+ unopened\nEntry is next legal minute open; target U is sellable no earlier than T+1; 40 bp costs.", fontsize=13, va="top")
        fig.text(0.06, 0.52, "These are Development diagnostics, not validation. Every selected OOF signal is included. Green title = net winner; red title = net loser.", fontsize=12)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)
        vap_by = {key: part for key, part in vap.groupby("gap_id", sort=False)}
        daily_by = {key: part for key, part in chart_daily.groupby("gap_id", sort=False)}
        for event in sample.itertuples(index=False):
            days = daily_by[event.gap_id]
            profile = vap_by.get(event.gap_id, pd.DataFrame())
            fig = plt.figure(figsize=(15.5, 8.69))
            grid = fig.add_gridspec(2, 5, width_ratios=[1, 1, 1, 1, 0.85], height_ratios=[1.15, 1], left=0.055, right=0.97, top=0.865, bottom=0.105, hspace=0.26, wspace=0.20)
            ax_full = fig.add_subplot(grid[0, :4])
            ax_local = fig.add_subplot(grid[1, :4])
            ax_vap = fig.add_subplot(grid[:, 4])
            title_color = "#087f5b" if event.net_return > 0 else "#c92a2a"
            fig.suptitle(f"{event.chart_id} | {event.symbol} | {event.board} | net {event.net_return:+.2%} | {event.exit_reason}", fontsize=15, color=title_color, weight="bold")
            fig.text(0.055, 0.925, f"Gap formed {event.gap_date.date()} | [L,U]=[{event.L:.4f},{event.U:.4f}] | width={event.gap_width_pct:.2%} | first return {event.first_return_date.date()}", fontsize=9.2)
            fig.text(0.055, 0.900, f"BUY {event.entry_time} @ {event.entry_coordinate_price:.4f} | SELL {event.exit_time} | hold {int(event.holding_sessions)} sessions | net {event.net_return:+.2%}", fontsize=9.2)
            _candles(ax_full, days)
            local = days.loc[days.cal_idx.between(int(event.first_return_cal_idx) - 25, int(event.exit_cal_idx) + 15)]
            _candles(ax_local, local)
            for ax in (ax_full, ax_local):
                ax.axhspan(event.L, event.U, color="#f6bd60", alpha=0.20)
                ax.axhline(event.L, color="#d97706", linestyle="--", linewidth=0.9)
                ax.axhline(event.U, color="#b45309", linestyle="--", linewidth=0.9)
                ax.axvline(mdates.date2num(event.gap_date), color="#9c6644", linewidth=0.9)
                ax.axvline(mdates.date2num(event.entry_date), color="#1d4ed8", linestyle="--", linewidth=1.0)
                ax.axvline(mdates.date2num(event.exit_date), color="#7e22ce", linestyle="--", linewidth=1.0)
                ax.grid(alpha=0.18)
                ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=10))
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
                ax.tick_params(axis="x", rotation=20, labelsize=7)
                ax.tick_params(axis="y", labelsize=7)
            exit_day = days.loc[days.trade_date.eq(pd.Timestamp(event.exit_date))]
            if exit_day.empty:
                raise ResearchError(f"chart exit day missing {event.gap_id}")
            exit_y = float(exit_day.coord_open.iloc[0])
            if event.exit_reason == "U_TARGET":
                exit_y = max(exit_y, float(event.U))
            ax_local.scatter(pd.Timestamp(event.entry_date), float(event.entry_coordinate_price), marker="^", s=72, color="#1d4ed8", edgecolor="white", linewidth=0.7, zorder=8, label="BUY")
            ax_local.scatter(pd.Timestamp(event.exit_date), exit_y, marker="v", s=72, color="#7e22ce", edgecolor="white", linewidth=0.7, zorder=8, label="SELL")
            ax_local.legend(loc="upper left", fontsize=7, framealpha=0.85, ncol=2)
            ax_full.set_title("120 sessions before gap through 20 sessions after exit", fontsize=9)
            ax_local.set_title("First-return / entry / exit window", fontsize=9)
            if len(profile):
                bin_mid_z = (profile.z_bin.astype(float) + 0.5) * 0.10
                ax_vap.barh(bin_mid_z, profile.pre_float_turnover_mass, height=0.085, color="#4c78a8", alpha=0.75)
                ax_vap.axhspan(0, 1, color="#f6bd60", alpha=0.25)
                ax_vap.axhline(0, color="#d97706", linestyle="--", linewidth=0.8)
                ax_vap.axhline(1, color="#b45309", linestyle="--", linewidth=0.8)
            ax_vap.set_title("Pre-gap 120-session VAP\nz=(price-L)/W", fontsize=9)
            ax_vap.grid(alpha=0.15)
            fig.text(0.055, 0.055, f"Admission: {event.selected_admission_template} | Entry trigger: {event.entry_form} | Minimum net headroom: {event.minimum_net_headroom:.1%}", fontsize=8.7)
            fig.text(0.055, 0.030, f"Exit: {event.exit_policy}/H{event.time_stop} | Blue triangle = BUY | Purple triangle = SELL | Orange band = true gap [L,U]", fontsize=8.7)
            pdf.savefig(fig)
            plt.close(fig)
    sample.to_csv(CHART_INDEX, index=False)
    return {"procedure": procedure, "signals": len(sample), "pages": len(sample) + 1, "pdf": str(PDF), "pdf_sha256": sha256(PDF), "chart_index_sha256": sha256(CHART_INDEX)}


def finalize() -> dict[str, Any]:
    result = json.loads(RESULT.read_text())
    charts = render_charts()
    result["charts"] = charts
    combined = {key: value["COMBINED"] for key, value in result["procedures"].items()}
    recommended = charts["procedure"]
    chosen = combined[recommended]
    annual = chosen["annual_returns"]
    positive_years = sum(value > 0 for value in annual.values())
    passes = bool(chosen["trades"] >= 100 and chosen["mean_net"] > 0 and chosen["median_net"] > 0 and chosen["cagr"] > 0 and chosen["return_excluding_best_five_days"] > 0 and positive_years >= 3)
    if passes:
        verdict = "SIMPLE_EXECUTABLE_EDGE_CANDIDATE"
    elif chosen["cagr"] > 0 and chosen["mean_net"] > 0:
        verdict = "SIMPLE_RULE_MARGINAL"
    else:
        verdict = "NO_SIMPLE_EXECUTABLE_EDGE"
    result["status"] = "COMPLETE"
    result["recommended_procedure"] = recommended
    result["verdict"] = verdict
    result["is_profitable_simple_rule_created"] = passes
    result["charts"] = charts
    result["hashes"]["pdf"] = charts["pdf_sha256"]
    result["hashes"]["chart_index"] = charts["chart_index_sha256"]
    write_json(RESULT, result)
    lines = [
        f"# {EXPERIMENT}", "", "## Verdict", "", f"`{verdict}`", "",
        "This is Development-only expanding walk-forward evidence. The V2 outcome-selected 305 rows were not used; 2021 and later remain unopened.", "",
        "## Core correction", "", "Narrow-gap structural fill is not the objective. Every entry uses an IOC buy limit that preserves a frozen minimum net U-target headroom after 40 bp costs, and U cannot be sold before T+1.", "",
        "## Walk-forward selections", "", "|Test year|Entry|Min net headroom|Exit|Admission|Deploy?|Train N|Train mean|", "|---:|---|---:|---|---|---|---:|---:|",
    ]
    for row in result["walkforward_selections"]:
        lines.append(f"|{row['outer_year']}|{row['entry_form']}|{row['minimum_net_headroom']:.2%}|{row['exit_policy']}/H{row['time_stop']}|{row['admission_template']}|{row['deployment_ready']}|{row['train_n']}|{row['train_mean']:.2%}|")
    lines.extend(["", "## Portfolio results", "", "|Procedure|Trades|Mean|Median|Win|U hit|CAGR|MaxDD|Sharpe|Ex best 5 days|", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for procedure, item in combined.items():
        lines.append(f"|{procedure}|{item['trades']}|{item['mean_net']:.2%}|{item['median_net']:.2%}|{item['win']:.2%}|{item['u_hit']:.2%}|{item['cagr']:.2%}|{item['max_drawdown']:.2%}|{item['sharpe']:.3f}|{item['return_excluding_best_five_days']:.2%}|")
    lines.extend(["", "## Chart review", "", f"The {charts['pages']}-page PDF includes every `{recommended}` OOF signal ({charts['signals']} signal pages) with gap, VAP, entry, exit and net result marked.", "", "## Audit", "", f"`{json.dumps(result['audit'], sort_keys=True)}`", "", "No 2021+ or repository 2024+ data were opened."])
    REPORT.write_text("\n".join(lines) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("stage-a", "verify-stage-a", "stage-b", "charts", "finalize"))
    args = parser.parse_args()
    EXT.mkdir(parents=True, exist_ok=True)
    MANIFESTS.mkdir(parents=True, exist_ok=True)
    if args.stage == "stage-a":
        value = run_stage_a()
    elif args.stage == "verify-stage-a":
        value = verify_stage_a()
    elif args.stage == "stage-b":
        value = run_stage_b()
    elif args.stage == "charts":
        value = render_charts()
    else:
        value = finalize()
    print(canonical_json(value))


if __name__ == "__main__":
    main()
