#!/usr/bin/env python3
# ruff: noqa: E501
"""All-market pre-2021 low-inventory true-gap fill-pattern discovery.

This experiment deliberately does not start from a V6/V8 candidate set.  It
reconstructs every valid Main/ChiNext downward true gap directly from the
governed PIT daily panel, establishes a pristine first return without a V6
collapse-leg, cluster, primary-gap, or memory gate, and then measures causal
minute turnover-at-price around the gap.  Only after the outcome-blind mother
population is frozen are structural U-fill labels through 2020 attached.

No return, PnL, entry, exit, model, strategy replay, or post-2020 observation is
part of this program.
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
EXPERIMENT = "ASHARE-ALL-TRUE-GAP-LOW-INVENTORY-FILL-PATTERN-DISCOVERY-V2"
AUTHORITATIVE_START_HEAD = "bdb06a475db936a70865705fc0693514c299a0d1"

DAILY = Path(
    "/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
RAW_ROOT = Path(
    "/Users/linmei/Downloads/workspace/quant/data/lake/"
    "stock_1min_canonical_none_20260813/bars"
)
QD004_INVENTORY = OS / "experiments/ASHARE-TAIL-OPEN-LGBM-V1_qd004_2013_2023_inventory.json"

EXT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_all_true_gap_low_inventory_fill_pattern_discovery_v2"
)
ALL_GAPS = EXT / "all_true_gap_primitives_2014_2020.parquet"
DAILY_CANDIDATES = EXT / "pristine_first_return_daily_candidates.parquet"
PRE_DAYS = EXT / "candidate_pre_gap_days.parquet"
VAP_PARTS = EXT / "vap_parts"
VAP_PROFILES = EXT / "pre_gap_vap_profiles.parquet"
STAGE_A_LEDGER = EXT / "stage_a_low_inventory_mother_population.parquet"
DISCOVERY_LEDGER = EXT / "descriptive_discovery_ledger.parquet"
DIRECT_ANALYSIS = EXT / "direct_feature_analysis.parquet"
CHART_PATHS = EXT / "chart_daily_paths.parquet"
CHART_DIR = EXT / "signal_charts"

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
CHART_INDEX = OS / f"artifacts/{EXPERIMENT}_chart_index.csv"
CONDITION_TABLE = OS / f"artifacts/{EXPERIMENT}_simple_conditions.csv"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"
PDF = ROOT / f"output/pdf/{EXPERIMENT}_all_signal_charts.pdf"

DISCOVERY_START = pd.Timestamp("2014-01-01")
DISCOVERY_END = pd.Timestamp("2020-12-31 23:59:59")
RAW_YEARS = tuple(range(2013, 2021))
OUTCOME_HORIZONS = (5, 10, 20, 40)
PRIMARY_HORIZON = 20
PRE_GAP_SESSIONS = 120
MIN_TRUE_GAP_WIDTH_PCT = 0.01
MIN_FULLY_BELOW_SESSIONS = 5
MAX_INSIDE_DENSITY = 1.00
MAX_CORRIDOR_DENSITY = 1.00
MAX_INSIDE_TOUCH_SESSIONS = 12
MAX_CORRIDOR_TOUCH_SESSIONS = 20
MIN_RULE_EVENTS = 100
MIN_RULE_YEARS = 6
MIN_INCREMENTAL_FILL = 0.02
MAX_RULE_CONDITIONS = 3
EPS = 1e-12

FEATURE_DIRECTIONS = {
    "pre_gap_inside_density_relative_local": "LOW",
    "pre_gap_corridor_density_relative_local": "LOW",
    "pre_gap_inside_touch_sessions": "LOW",
    "pre_gap_corridor_touch_sessions": "LOW",
    "gap_width_pct": "LOW",
    "gap_age_sessions": "HIGH",
    "max_depth_below_l_before_return": "HIGH",
    "post_gap_lower_corridor_touch_sessions": "LOW",
    "post_gap_lower_corridor_turnover": "LOW",
    "pre_peak_to_gap_sessions": "HIGH",
    "pre_gap_drawdown_from_120d_peak": "HIGH",
    "pre_gap_return_20d": "LOW",
    "pre_gap_return_60d": "LOW",
    "pre_gap_max_runup_20d": "LOW",
    "pre_gap_max_runup_60d": "LOW",
    "approach_return_10d": "HIGH",
    "approach_path_efficiency_10d": "HIGH",
    "higher_low_share_10d": "HIGH",
}


class DiscoveryError(RuntimeError):
    """Fail closed on source, chronology, lineage, or semantic ambiguity."""


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
        )
        + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_rank(value: str) -> str:
    return hashlib.sha256(f"{EXPERIMENT}|{value}".encode()).hexdigest()


def raw_path(year: int) -> Path:
    if year not in RAW_YEARS:
        raise DiscoveryError(f"raw year outside frozen range: {year}")
    return RAW_ROOT / f"{year}_day_parquet_none.parquet"


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "scientific_status": "PRE_2021_IN_SAMPLE_STRUCTURAL_PATTERN_DISCOVERY_NOT_PREDICTION_NOT_STRATEGY",
        "source_population": {
            "construction": "directly from governed PIT daily rows; no V6/V8 candidate input",
            "boards": ["MAIN", "CHINEXT"],
            "true_gap": "High_t < Low_t_minus_1",
            "interval": "[High_t, Low_t_minus_1] = [L,U]",
            "formation_gate": "completed current and previous rows are hard-valid, adjacent, corporate-action-safe, and in the same QD-010 lineage",
            "minimum_width_pct_of_previous_close": MIN_TRUE_GAP_WIDTH_PCT,
            "v6_core_required": False,
            "collapse_leg_required": False,
            "primary_gap_hierarchy_required": False,
            "memory_class_required": False,
        },
        "chronology": {
            "discovery_start": "2014-01-01",
            "discovery_end": "2020-12-31",
            "required_complete_structural_horizon_sessions": 40,
            "2021_and_later_used": False,
        },
        "pristine_first_return": {
            "departure": f"first {MIN_FULLY_BELOW_SESSIONS} completed post-gap stock sessions all have High < L",
            "pre_departure_touch_policy": "reject the gap permanently; never reset a later interaction as first return",
            "first_return": "earliest later completed 1-minute bar whose high reaches L from below",
            "same_lineage_required": True,
            "attack_2_allowed": False,
            "minimum_fully_below_sessions": MIN_FULLY_BELOW_SESSIONS,
        },
        "outcome_blind_low_inventory_mother": {
            "history": "exactly 120 completed same-lineage hard-valid sessions, each with exactly 241 one-minute bars, before gap formation",
            "minute_price": "amount/volume when volume>0, otherwise zero-weight typical price",
            "minute_weight": "PIT daily float-turnover multiplied by minute share of daily volume",
            "z": "(QD-010 comparable minute price - L) / W",
            "bin_width": "0.10W",
            "local_reference": "z in [-2,3)",
            "inside_density": {
                "definition": "turnover mass per unit width in z=[0,1), divided by local-reference mass per unit width",
                "maximum": MAX_INSIDE_DENSITY,
            },
            "corridor_density": {
                "definition": "turnover mass per unit width in z=[-0.5,1.5), divided by local-reference mass per unit width",
                "maximum": MAX_CORRIDOR_DENSITY,
            },
            "maximum_pre_gap_sessions_intersecting_exact_gap": MAX_INSIDE_TOUCH_SESSIONS,
            "maximum_pre_gap_sessions_intersecting_corridor": MAX_CORRIDOR_TOUCH_SESSIONS,
            "missing_policy": "FAIL_CLOSED",
        },
        "stage_b_structural_outcome": {
            "primary": "structural U full-fill within 20 completed stock sessions after pristine first return",
            "secondary_horizons_sessions": list(OUTCOME_HORIZONS),
            "same-day_fill_included": True,
            "return_or_pnl_opened": False,
            "execution_or_trading_claim": False,
        },
        "descriptive_conditions": {
            "candidate_features": FEATURE_DIRECTIONS,
            "thresholds": "full-discovery q30/q50/q70 in the frozen economic direction; no arbitrary threshold search",
            "selection": f"greedy at most {MAX_RULE_CONDITIONS}; each addition retains >={MIN_RULE_EVENTS} events and >={MIN_RULE_YEARS} years, improves pooled 20D fill by >={MIN_INCREMENTAL_FILL:.0%}, and has positive median calendar-year uplift",
            "selector_order": "positive-lift years, median annual lift, pooled lift, support, deterministic name",
            "interpretation": "same-sample descriptive regularity only",
        },
        "charts": {
            "selection": "every final simple-condition match",
            "views": ["full gap-to-return lifecycle", "local first-return window", "pre-gap turnover-at-price profile"],
            "outcome_visible": True,
            "returns_visible": False,
        },
        "governance": {
            "prediction_analysis_run": False,
            "strategy_backtest_run": False,
            "return_analysis_run": False,
            "2021_plus_data_used": False,
            "repository_2024_plus_data_opened": False,
        },
    }


def spec_value(contract_hash: str) -> dict[str, Any]:
    return {
        "experiment_id": EXPERIMENT,
        "authoritative_start_head": AUTHORITATIVE_START_HEAD,
        "contract_sha256": contract_hash,
        "mission": "Search the full governed pre-2021 Main/ChiNext true-gap universe for pristine low-inventory gaps, then describe structural U-fill regularities with at most three simple conditions and render every final match.",
        "stage_order": [
            "RECONSTRUCT_ALL_TRUE_GAPS_DIRECTLY_FROM_PIT_DAILY",
            "ESTABLISH_PRISTINE_FIRST_RETURN",
            "CALCULATE_CAUSAL_MINUTE_VAP",
            "FREEZE_LOW_INVENTORY_MOTHER_POPULATION",
            "OPEN_STRUCTURAL_U_FILL_ONLY",
            "SUMMARIZE_SIMPLE_CONDITIONS",
            "RENDER_ALL_FINAL_MATCHES",
            "STOP_FOR_HUMAN_REVIEW",
        ],
        "prohibited": [
            "V6 CORE candidate gate",
            "collapse-cluster gate",
            "return",
            "PnL",
            "trade replay",
            "entry/exit optimization",
            "predictive claim",
            "2021+ data",
            "2024+ data",
        ],
        "contract": contract_value(),
    }


def validate_inputs() -> None:
    required = [DAILY, QD004_INVENTORY, *[raw_path(year) for year in RAW_YEARS]]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise DiscoveryError(f"missing governed input(s): {missing}")


def freeze_stage_a_contract() -> dict[str, str]:
    write_json(CONTRACT, contract_value())
    contract_hash = sha256(CONTRACT)
    write_json(SPEC, spec_value(contract_hash))
    return {"contract_sha256": contract_hash, "spec_sha256": sha256(SPEC)}


def load_daily() -> pd.DataFrame:
    columns = [
        "trade_date",
        "cal_idx",
        "symbol",
        "sleeve",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "turnover_fraction",
        "corporate_action_count",
        "corporate_action_valid",
        "corporate_action_blocking",
        "hard_valid",
        "history_valid",
        "current_valid",
        "invalid_step_cum",
        "coordinate_factor",
        "coord_open",
        "coord_high",
        "coord_low",
        "coord_close",
    ]
    con = duckdb.connect()
    con.execute("SET threads=4")
    frame = con.execute(
        f"""
        SELECT {','.join(columns)}
        FROM read_parquet('{DAILY}')
        WHERE trade_date>=DATE '2013-01-01'
          AND trade_date<=DATE '2020-12-31'
          AND sleeve IN ('MAIN','CHINEXT')
        ORDER BY symbol,trade_date
        """
    ).fetchdf()
    con.close()
    if frame.empty or pd.to_datetime(frame.trade_date).max() > DISCOVERY_END:
        raise DiscoveryError("daily chronology boundary failure")
    frame.trade_date = pd.to_datetime(frame.trade_date)
    frame["symbol_seq"] = frame.groupby("symbol", sort=False).cumcount()
    return frame


def build_all_true_gaps(daily: pd.DataFrame) -> pd.DataFrame:
    frame = daily.copy()
    grouped = frame.groupby("symbol", sort=False)
    for column in (
        "trade_date",
        "cal_idx",
        "low",
        "close",
        "invalid_step_cum",
        "hard_valid",
        "history_valid",
        "current_valid",
        "corporate_action_valid",
        "corporate_action_blocking",
    ):
        frame[f"previous_{column}"] = grouped[column].shift(1)
    mask = (
        frame.trade_date.ge(DISCOVERY_START)
        & frame.trade_date.le(DISCOVERY_END)
        & frame.hard_valid.fillna(False)
        & frame.history_valid.fillna(False)
        & frame.current_valid.fillna(False)
        & frame.corporate_action_valid.fillna(False)
        & ~frame.corporate_action_blocking.fillna(True)
        & frame.corporate_action_count.fillna(1).eq(0)
        & frame.previous_hard_valid.eq(True)
        & frame.previous_history_valid.eq(True)
        & frame.previous_current_valid.eq(True)
        & frame.previous_corporate_action_valid.eq(True)
        & frame.previous_corporate_action_blocking.eq(False)
        & frame.cal_idx.sub(frame.previous_cal_idx).eq(1)
        & frame.invalid_step_cum.eq(frame.previous_invalid_step_cum)
        & frame.high.lt(frame.previous_low)
    )
    gaps = frame.loc[mask].copy()
    gaps["gap_id"] = gaps.symbol.astype(str) + "|" + gaps.trade_date.dt.strftime("%Y-%m-%d")
    gaps["gap_date"] = gaps.trade_date
    gaps["gap_seq"] = gaps.symbol_seq.astype(int)
    gaps["board"] = gaps.sleeve.astype(str)
    gaps["L"] = gaps.high.astype(float) * gaps.coordinate_factor.astype(float)
    gaps["U"] = gaps.previous_low.astype(float) * gaps.coordinate_factor.astype(float)
    gaps["W"] = gaps.U - gaps.L
    gaps["gap_width_pct"] = (gaps.previous_low - gaps.high) / gaps.previous_close
    keep = [
        "gap_id",
        "symbol",
        "board",
        "gap_date",
        "cal_idx",
        "gap_seq",
        "invalid_step_cum",
        "coordinate_factor",
        "L",
        "U",
        "W",
        "gap_width_pct",
        "open",
        "high",
        "low",
        "close",
        "coord_open",
        "coord_high",
        "coord_low",
        "coord_close",
        "previous_trade_date",
        "previous_low",
        "previous_close",
    ]
    gaps = gaps[keep].sort_values(["gap_date", "symbol"], kind="mergesort").reset_index(drop=True)
    if gaps.gap_id.duplicated().any() or not gaps.W.gt(0).all():
        raise DiscoveryError("all-gap primitive identity failure")
    write_parquet(gaps, ALL_GAPS)
    return gaps


def _valid_rows(frame: pd.DataFrame) -> np.ndarray:
    return (
        frame.hard_valid.fillna(False)
        & frame.history_valid.fillna(False)
        & frame.current_valid.fillna(False)
        & frame.corporate_action_valid.fillna(False)
        & ~frame.corporate_action_blocking.fillna(True)
    ).to_numpy(bool)


def build_daily_candidates(daily: pd.DataFrame, all_gaps: pd.DataFrame) -> pd.DataFrame:
    daily_groups = {
        symbol: part.reset_index(drop=True)
        for symbol, part in daily.groupby("symbol", sort=False)
    }
    rows: list[dict[str, Any]] = []
    meaningful = all_gaps.loc[all_gaps.gap_width_pct.ge(MIN_TRUE_GAP_WIDTH_PCT)].copy()
    for gap in meaningful.itertuples(index=False):
        part = daily_groups[str(gap.symbol)]
        pos = int(gap.gap_seq)
        if pos >= len(part) or pd.Timestamp(part.iloc[pos].trade_date) != pd.Timestamp(gap.gap_date):
            raise DiscoveryError(f"gap sequence mismatch: {gap.gap_id}")
        reason = "ELIGIBLE_FOR_MINUTE_VAP"
        hist = part.iloc[max(0, pos - PRE_GAP_SESSIONS) : pos].copy()
        history_ok = (
            len(hist) == PRE_GAP_SESSIONS
            and _valid_rows(hist).all()
            and hist.invalid_step_cum.eq(float(gap.invalid_step_cum)).all()
        )
        if not history_ok:
            reason = "NO_EXACT_120_SAME_LINEAGE_DAILY_HISTORY"
        future = part.iloc[pos + 1 :].copy()
        if len(future):
            future_valid = _valid_rows(future) & future.invalid_step_cum.eq(float(gap.invalid_step_cum)).to_numpy(bool)
            invalid_positions = np.flatnonzero(~future_valid)
            if len(invalid_positions):
                future = future.iloc[: int(invalid_positions[0])]
        touches = (
            np.rint(future.coord_high.to_numpy(float) * 100)
            >= round(float(gap.L) * 100)
        ) if len(future) else np.array([], dtype=bool)
        touch_positions = np.flatnonzero(touches)
        first_return_rel = None if not len(touch_positions) else int(touch_positions[0])
        if reason == "ELIGIBLE_FOR_MINUTE_VAP" and first_return_rel is None:
            reason = "NO_FIRST_RETURN_BY_2020"
        if reason == "ELIGIBLE_FOR_MINUTE_VAP" and first_return_rel is not None and first_return_rel < MIN_FULLY_BELOW_SESSIONS:
            reason = "REJECTED_PRE_PERSISTENCE_TOUCH"
        first_return_pos = None if first_return_rel is None else pos + 1 + first_return_rel
        if reason == "ELIGIBLE_FOR_MINUTE_VAP" and first_return_pos is not None:
            outcome_end = first_return_pos + max(OUTCOME_HORIZONS)
            if outcome_end >= len(part):
                reason = "INCOMPLETE_H40_BEFORE_2021"
            else:
                h40 = part.iloc[first_return_pos : outcome_end + 1]
                if (
                    not _valid_rows(h40).all()
                    or not h40.invalid_step_cum.eq(float(gap.invalid_step_cum)).all()
                    or pd.Timestamp(h40.trade_date.max()) > DISCOVERY_END
                ):
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
            prior_close = float(hist.iloc[-1].coord_close)
            close20 = float(hist.iloc[-20].coord_close)
            close60 = float(hist.iloc[-60].coord_close)
            recent20 = hist.tail(20)
            recent60 = hist.tail(60)
            features = {
                "pre_gap_inside_touch_sessions": inside_touches,
                "pre_gap_corridor_touch_sessions": corridor_touches,
                "pre_peak_date": pd.Timestamp(hist.iloc[peak_offset].trade_date),
                "pre_peak_to_gap_sessions": int(len(hist) - peak_offset),
                "pre_gap_drawdown_from_120d_peak": float(1.0 - float(gap.coord_low) / peak),
                "pre_gap_return_20d": float(prior_close / close20 - 1.0),
                "pre_gap_return_60d": float(prior_close / close60 - 1.0),
                "pre_gap_max_runup_20d": float(recent20.coord_high.max() / recent20.coord_low.min() - 1.0),
                "pre_gap_max_runup_60d": float(recent60.coord_high.max() / recent60.coord_low.min() - 1.0),
            }
        if first_return_pos is not None:
            return_row = part.iloc[first_return_pos]
            below = part.iloc[pos + 1 : first_return_pos]
            last10 = below.tail(10)
            if len(last10) >= 2:
                closes = last10.coord_close.to_numpy(float)
                lows = last10.coord_low.to_numpy(float)
                total_path = float(np.abs(np.diff(closes)).sum())
                approach_return = float(closes[-1] / closes[0] - 1.0)
                approach_efficiency = float(max(closes[-1] - closes[0], 0.0) / total_path) if total_path > EPS else 0.0
                higher_low_share = float(np.mean(np.diff(lows) > 0))
            else:
                approach_return = math.nan
                approach_efficiency = math.nan
                higher_low_share = math.nan
            lower_corridor = below.coord_high.ge(float(gap.L - 0.5 * gap.W))
            features.update(
                {
                    "first_return_date": pd.Timestamp(return_row.trade_date),
                    "first_return_cal_idx": int(return_row.cal_idx),
                    "first_return_seq": int(return_row.symbol_seq),
                    "first_return_coordinate_factor": float(return_row.coordinate_factor),
                    "gap_age_sessions": int(first_return_pos - pos),
                    "max_depth_below_l_before_return": float(1.0 - below.coord_low.min() / float(gap.L)) if len(below) else 0.0,
                    "post_gap_lower_corridor_touch_sessions": int(lower_corridor.sum()),
                    "post_gap_lower_corridor_turnover": float(below.loc[lower_corridor, "turnover_fraction"].sum()),
                    "approach_return_10d": approach_return,
                    "approach_path_efficiency_10d": approach_efficiency,
                    "higher_low_share_10d": higher_low_share,
                }
            )
        rows.append(
            {
                **gap._asdict(),
                **features,
                "daily_history_complete": bool(history_ok),
                "first_post_gap_touch_is_pristine": bool(first_return_rel is not None and first_return_rel >= MIN_FULLY_BELOW_SESSIONS),
                "pre_gap_inside_touch_sessions": inside_touches,
                "pre_gap_corridor_touch_sessions": corridor_touches,
                "stage_a_daily_disposition": reason,
            }
        )
    ledger = pd.DataFrame(rows)
    if ledger.gap_id.duplicated().any():
        raise DiscoveryError("duplicate daily candidate gap")
    write_parquet(ledger, DAILY_CANDIDATES)
    return ledger


def build_pre_days(daily: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    selected = candidates.loc[
        candidates.stage_a_daily_disposition.eq("ELIGIBLE_FOR_MINUTE_VAP")
    ].copy()
    groups = {
        symbol: part.reset_index(drop=True)
        for symbol, part in daily.groupby("symbol", sort=False)
    }
    pieces: list[pd.DataFrame] = []
    for event in selected.itertuples(index=False):
        part = groups[str(event.symbol)]
        hist = part.iloc[int(event.gap_seq) - PRE_GAP_SESSIONS : int(event.gap_seq)][
            ["symbol", "trade_date", "coordinate_factor", "turnover_fraction"]
        ].copy()
        if len(hist) != PRE_GAP_SESSIONS:
            raise DiscoveryError(f"pre-day reconstruction failure: {event.gap_id}")
        hist["gap_id"] = event.gap_id
        hist["L"] = float(event.L)
        hist["W"] = float(event.W)
        pieces.append(hist)
    result = pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()
    if result.empty or result.duplicated(["gap_id", "trade_date"]).any():
        raise DiscoveryError("empty or duplicate pre-gap day panel")
    write_parquet(result, PRE_DAYS)
    return result


def _vap_year_query(year: int) -> str:
    return f"""
    WITH p AS (
      SELECT * FROM read_parquet('{PRE_DAYS}')
      WHERE year(trade_date)={year}
    ), raw0 AS (
      SELECT r.qmt_code AS symbol,r.trade_date,r.bar_end_time,r.high,r.low,r.close,r.volume,r.amount
      FROM read_parquet('{raw_path(year)}') r
      JOIN (SELECT DISTINCT symbol,trade_date FROM p) n
        ON r.qmt_code=n.symbol AND r.trade_date=n.trade_date
      WHERE r.period='1m' AND r.adjust='none'
    ), joined0 AS (
      SELECT p.gap_id,p.trade_date,p.coordinate_factor,p.turnover_fraction,p.L,p.W,
        r.bar_end_time,r.high,r.low,r.close,r.volume,r.amount,
        count(*) OVER(PARTITION BY p.gap_id,p.trade_date) AS bars_in_session,
        sum(r.volume) OVER(PARTITION BY p.gap_id,p.trade_date) AS day_volume
      FROM p JOIN raw0 r USING(symbol,trade_date)
    ), joined AS (
      SELECT *,
        CASE WHEN volume>0 AND amount>0 THEN amount/volume ELSE (high+low+close)/3 END AS minute_price,
        CASE WHEN day_volume>0 THEN turnover_fraction*volume/day_volume ELSE NULL END AS minute_weight
      FROM joined0
    ), quality AS (
      SELECT gap_id,-999::INTEGER AS z_bin,
        count(DISTINCT trade_date)::DOUBLE AS mass,
        count(DISTINCT trade_date) FILTER(WHERE bars_in_session=241 AND day_volume>0)::DOUBLE AS auxiliary
      FROM joined GROUP BY gap_id
    ), bins AS (
      SELECT gap_id,floor(((minute_price*coordinate_factor-L)/W)/0.10)::INTEGER AS z_bin,
        sum(minute_weight)::DOUBLE AS mass,
        count(*)::DOUBLE AS auxiliary
      FROM joined
      WHERE minute_weight IS NOT NULL
        AND (minute_price*coordinate_factor-L)/W>=-2
        AND (minute_price*coordinate_factor-L)/W<3
      GROUP BY gap_id,z_bin
    )
    SELECT * FROM quality
    UNION ALL
    SELECT * FROM bins
    ORDER BY gap_id,z_bin
    """


def build_vap_profiles(candidates: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    VAP_PARTS.mkdir(parents=True, exist_ok=True)
    parts: list[pd.DataFrame] = []
    for year in RAW_YEARS:
        path = VAP_PARTS / f"vap_{year}.parquet"
        con = duckdb.connect()
        con.execute("SET threads=4")
        con.execute("SET memory_limit='8GB'")
        con.execute(f"SET temp_directory='{EXT / 'duckdb_tmp'}'")
        result = con.execute(_vap_year_query(year)).fetchdf()
        con.close()
        write_parquet(result, path)
        parts.append(result)
    combined = pd.concat(parts, ignore_index=True)
    quality = combined.loc[combined.z_bin.eq(-999)].groupby("gap_id", as_index=False).agg(
        minute_history_sessions=("mass", "sum"),
        exact_241_minute_sessions=("auxiliary", "sum"),
    )
    profiles = (
        combined.loc[combined.z_bin.ne(-999)]
        .groupby(["gap_id", "z_bin"], as_index=False)
        .agg(pre_float_turnover_mass=("mass", "sum"), contributing_minutes=("auxiliary", "sum"))
    )
    write_parquet(profiles, VAP_PROFILES)
    local = profiles.groupby("gap_id", as_index=False).agg(local_mass=("pre_float_turnover_mass", "sum"))
    inside = profiles.loc[profiles.z_bin.between(0, 9)].groupby("gap_id", as_index=False).pre_float_turnover_mass.sum().rename(columns={"pre_float_turnover_mass": "inside_mass"})
    corridor = profiles.loc[profiles.z_bin.between(-5, 14)].groupby("gap_id", as_index=False).pre_float_turnover_mass.sum().rename(columns={"pre_float_turnover_mass": "corridor_mass"})
    metrics = quality.merge(local, on="gap_id", how="left").merge(inside, on="gap_id", how="left").merge(corridor, on="gap_id", how="left")
    metrics[["local_mass", "inside_mass", "corridor_mass"]] = metrics[["local_mass", "inside_mass", "corridor_mass"]].fillna(0.0)
    metrics["pre_gap_inside_density_relative_local"] = 5.0 * metrics.inside_mass / metrics.local_mass.replace(0, np.nan)
    metrics["pre_gap_corridor_density_relative_local"] = 2.5 * metrics.corridor_mass / metrics.local_mass.replace(0, np.nan)
    eligible = candidates.loc[candidates.stage_a_daily_disposition.eq("ELIGIBLE_FOR_MINUTE_VAP")].copy()
    eligible = eligible.merge(metrics, on="gap_id", how="left", validate="one_to_one")
    eligible["exact_minute_history"] = eligible.minute_history_sessions.eq(PRE_GAP_SESSIONS) & eligible.exact_241_minute_sessions.eq(PRE_GAP_SESSIONS)
    eligible["low_inside_inventory"] = eligible.pre_gap_inside_density_relative_local.le(MAX_INSIDE_DENSITY)
    eligible["low_corridor_inventory"] = eligible.pre_gap_corridor_density_relative_local.le(MAX_CORRIDOR_DENSITY)
    return eligible, profiles


def attach_exact_first_return_times(mother: pd.DataFrame) -> pd.DataFrame:
    seed = EXT / "first_return_minute_seed.parquet"
    write_parquet(
        mother[["gap_id", "symbol", "first_return_date", "first_return_coordinate_factor", "L"]],
        seed,
    )
    rows: list[pd.DataFrame] = []
    for year in sorted(mother.first_return_date.dt.year.unique()):
        con = duckdb.connect()
        query = f"""
        WITH s AS (
          SELECT * FROM read_parquet('{seed}') WHERE year(first_return_date)={int(year)}
        ), joined AS (
          SELECT s.gap_id,r.bar_end_time,r.high,
            count(*) OVER(PARTITION BY s.gap_id) AS bars_in_session
          FROM s JOIN read_parquet('{raw_path(int(year))}') r
            ON r.qmt_code=s.symbol AND r.trade_date=s.first_return_date
          WHERE r.period='1m' AND r.adjust='none'
        )
        SELECT s.gap_id,min(j.bar_end_time) FILTER(
                 WHERE round(j.high*s.first_return_coordinate_factor*100)>=round(s.L*100)
               ) AS pristine_first_return_time,
               max(j.bars_in_session) AS first_return_session_minutes
        FROM s JOIN joined j USING(gap_id)
        GROUP BY s.gap_id
        ORDER BY s.gap_id
        """
        rows.append(con.execute(query).fetchdf())
        con.close()
    exact = pd.concat(rows, ignore_index=True)
    exact.pristine_first_return_time = pd.to_datetime(exact.pristine_first_return_time)
    result = mother.merge(exact, on="gap_id", how="left", validate="one_to_one")
    result["exact_first_return_minute_valid"] = (
        result.pristine_first_return_time.notna()
        & result.first_return_session_minutes.eq(241)
    )
    return result.loc[result.exact_first_return_minute_valid].copy()


def freeze_stage_a_mother(daily: pd.DataFrame, all_gaps: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    candidates = build_daily_candidates(daily, all_gaps)
    build_pre_days(daily, candidates)
    minute_eligible, _ = build_vap_profiles(candidates)
    mother = minute_eligible.loc[
        minute_eligible.exact_minute_history
        & minute_eligible.low_inside_inventory
        & minute_eligible.low_corridor_inventory
    ].copy()
    low_inventory_before_return_minute_check = len(mother)
    mother = attach_exact_first_return_times(mother)
    forbidden = [
        column
        for column in mother.columns
        if any(token in column.lower() for token in ("u_fill", "return_label", "pnl", "profit", "win"))
    ]
    if forbidden:
        raise DiscoveryError(f"outcome-like fields entered Stage A: {forbidden}")
    if mother.empty or mother.gap_id.duplicated().any():
        raise DiscoveryError("empty or duplicate Stage-A mother population")
    if mother.first_return_date.max() > DISCOVERY_END:
        raise DiscoveryError("post-2020 first return entered Stage A")
    write_parquet(mother, STAGE_A_LEDGER)
    funnel = {
        "all_true_gaps": len(all_gaps),
        "width_ge_1pct": int(all_gaps.gap_width_pct.ge(MIN_TRUE_GAP_WIDTH_PCT).sum()),
        "daily_exact_history": int(candidates.daily_history_complete.sum()),
        "pristine_first_return": int(candidates.first_post_gap_touch_is_pristine.sum()),
        "daily_vap_eligible": int(candidates.stage_a_daily_disposition.eq("ELIGIBLE_FOR_MINUTE_VAP").sum()),
        "exact_120x241_minute_history": int(minute_eligible.exact_minute_history.sum()),
        "low_inside_inventory": int((minute_eligible.exact_minute_history & minute_eligible.low_inside_inventory).sum()),
        "low_inside_and_corridor_inventory_before_return_minute_check": low_inventory_before_return_minute_check,
        "exact_first_return_minute": len(mother),
        "low_inside_and_corridor_inventory": len(mother),
    }
    return mother, funnel


def attach_structural_outcomes(mother: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    groups = {
        symbol: part.reset_index(drop=True)
        for symbol, part in daily.groupby("symbol", sort=False)
    }
    rows: list[dict[str, Any]] = []
    for event in mother.itertuples(index=False):
        part = groups[str(event.symbol)]
        start = int(event.first_return_seq)
        path = part.iloc[start : start + max(OUTCOME_HORIZONS) + 1]
        if len(path) != max(OUTCOME_HORIZONS) + 1:
            raise DiscoveryError(f"incomplete frozen H40 path: {event.gap_id}")
        hits = np.flatnonzero(
            np.rint(path.coord_high.to_numpy(float) * 100) >= round(float(event.U) * 100)
        )
        offset = None if not len(hits) else int(hits[0])
        fill_date = None if offset is None else pd.Timestamp(path.iloc[offset].trade_date)
        rows.append(
            {
                "gap_id": event.gap_id,
                "u_fill_offset": offset,
                "first_u_fill_date": fill_date,
                **{
                    f"u_full_fill_{h}d": bool(offset is not None and offset <= h)
                    for h in OUTCOME_HORIZONS
                },
            }
        )
    outcomes = pd.DataFrame(rows)
    ledger = mother.merge(outcomes, on="gap_id", how="left", validate="one_to_one")
    if ledger[[f"u_full_fill_{h}d" for h in OUTCOME_HORIZONS]].isna().any().any():
        raise DiscoveryError("missing structural label")
    if ledger.u_fill_offset.dropna().gt(40).any():
        raise DiscoveryError("post-H40 path entered outcome ledger")
    ledger["discovery_year"] = ledger.first_return_date.dt.year
    write_parquet(ledger, DISCOVERY_LEDGER)
    return ledger


def _summarize_group(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "n": len(frame),
        "symbols": int(frame.symbol.nunique()),
        "years": int(frame.discovery_year.nunique()),
        **{
            f"u_fill_{h}d": float(frame[f"u_full_fill_{h}d"].mean())
            for h in OUTCOME_HORIZONS
        },
        "median_u_fill_offset_among_40d_fills": None
        if not frame.u_full_fill_40d.any()
        else float(frame.loc[frame.u_full_fill_40d, "u_fill_offset"].median()),
    }


def direct_feature_analysis(ledger: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    target = f"u_full_fill_{PRIMARY_HORIZON}d"
    for feature in FEATURE_DIRECTIONS:
        values = pd.to_numeric(ledger[feature], errors="coerce")
        valid = ledger.loc[values.notna()].copy()
        if valid.empty or values.nunique(dropna=True) < 2:
            continue
        valid["feature_value"] = pd.to_numeric(valid[feature], errors="coerce")
        valid["quartile"] = pd.qcut(
            valid.feature_value.rank(method="first"),
            4,
            labels=["Q1", "Q2", "Q3", "Q4"],
        )
        for quartile, part in valid.groupby("quartile", observed=True):
            rows.append(
                {
                    "feature": feature,
                    "slice": str(quartile),
                    "n": len(part),
                    "feature_mean": float(part.feature_value.mean()),
                    "feature_median": float(part.feature_value.median()),
                    **{
                        f"u_fill_{h}d": float(part[f"u_full_fill_{h}d"].mean())
                        for h in OUTCOME_HORIZONS
                    },
                }
            )
        success = valid.loc[valid[target]]
        failure = valid.loc[~valid[target]]
        rows.append(
            {
                "feature": feature,
                "slice": "SUCCESS_MINUS_FAILURE",
                "n": len(valid),
                "feature_mean": float(success.feature_value.mean() - failure.feature_value.mean()) if len(success) and len(failure) else math.nan,
                "feature_median": float(success.feature_value.median() - failure.feature_value.median()) if len(success) and len(failure) else math.nan,
                **{f"u_fill_{h}d": math.nan for h in OUTCOME_HORIZONS},
            }
        )
    result = pd.DataFrame(rows)
    write_parquet(result, DIRECT_ANALYSIS)
    return result


def _condition_mask(frame: pd.DataFrame, condition: dict[str, Any]) -> pd.Series:
    values = pd.to_numeric(frame[condition["feature"]], errors="coerce")
    if condition["operator"] == "<=":
        return values.notna() & values.le(float(condition["threshold"]))
    if condition["operator"] == ">=":
        return values.notna() & values.ge(float(condition["threshold"]))
    raise DiscoveryError(f"unknown condition operator: {condition['operator']}")


def _candidate_conditions(ledger: pd.DataFrame) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for feature, direction in FEATURE_DIRECTIONS.items():
        values = pd.to_numeric(ledger[feature], errors="coerce").dropna()
        if values.nunique() < 2:
            continue
        operator = ">=" if direction == "HIGH" else "<="
        seen: set[tuple[str, float]] = set()
        for quantile in (30, 50, 70):
            threshold = float(values.quantile(quantile / 100.0))
            key = (operator, round(threshold, 12))
            if key in seen:
                continue
            seen.add(key)
            result.append(
                {
                    "feature": feature,
                    "operator": operator,
                    "threshold": threshold,
                    "threshold_source": f"Q{quantile}",
                }
            )
    return result


def _condition_metrics(ledger: pd.DataFrame, mask: pd.Series) -> dict[str, Any]:
    target = f"u_full_fill_{PRIMARY_HORIZON}d"
    part = ledger.loc[mask]
    if part.empty:
        return {
            "n": 0,
            "years": 0,
            "pooled_rate": math.nan,
            "pooled_lift": math.nan,
            "median_year_lift": math.nan,
            "positive_year_lift_count": 0,
        }
    base_by_year = ledger.groupby("discovery_year")[target].mean()
    selected_by_year = part.groupby("discovery_year")[target].mean()
    common = selected_by_year.index.intersection(base_by_year.index)
    lifts = selected_by_year.loc[common] - base_by_year.loc[common]
    return {
        "n": len(part),
        "years": int(part.discovery_year.nunique()),
        "pooled_rate": float(part[target].mean()),
        "pooled_lift": float(part[target].mean() - ledger[target].mean()),
        "median_year_lift": float(lifts.median()) if len(lifts) else math.nan,
        "positive_year_lift_count": int(lifts.gt(0).sum()),
    }


def discover_simple_conditions(ledger: pd.DataFrame) -> tuple[list[dict[str, Any]], pd.DataFrame, pd.Series]:
    candidates = _candidate_conditions(ledger)
    active = pd.Series(True, index=ledger.index)
    selected: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    current_rate = float(ledger[f"u_full_fill_{PRIMARY_HORIZON}d"].mean())
    for step in range(1, MAX_RULE_CONDITIONS + 1):
        evaluated: list[tuple[tuple[Any, ...], dict[str, Any], pd.Series, dict[str, Any]]] = []
        used_features = {item["feature"] for item in selected}
        for condition in candidates:
            if condition["feature"] in used_features:
                continue
            mask = active & _condition_mask(ledger, condition)
            metrics = _condition_metrics(ledger, mask)
            incremental = metrics["pooled_rate"] - current_rate if np.isfinite(metrics["pooled_rate"]) else math.nan
            eligible = (
                metrics["n"] >= MIN_RULE_EVENTS
                and metrics["years"] >= MIN_RULE_YEARS
                and metrics["median_year_lift"] > 0
                and incremental >= MIN_INCREMENTAL_FILL
            )
            row = {
                "step": step,
                **condition,
                **metrics,
                "incremental_rate_gain": incremental,
                "eligible": bool(eligible),
                "selected": False,
            }
            audit_rows.append(row)
            if eligible:
                key = (
                    metrics["positive_year_lift_count"],
                    metrics["median_year_lift"],
                    metrics["pooled_lift"],
                    metrics["n"],
                    f"{condition['feature']}|{condition['threshold_source']}",
                )
                evaluated.append((key, condition, mask, metrics))
        if not evaluated:
            break
        _, chosen, chosen_mask, metrics = max(evaluated, key=lambda item: item[0])
        chosen = {**chosen, **metrics, "step": step}
        selected.append(chosen)
        active = chosen_mask
        current_rate = metrics["pooled_rate"]
        for row in reversed(audit_rows):
            if (
                row["step"] == step
                and row["feature"] == chosen["feature"]
                and row["operator"] == chosen["operator"]
                and math.isclose(float(row["threshold"]), float(chosen["threshold"]), rel_tol=0, abs_tol=1e-12)
            ):
                row["selected"] = True
                break
    if not selected:
        active = pd.Series(True, index=ledger.index)
    table = pd.DataFrame(audit_rows)
    table.to_csv(CONDITION_TABLE, index=False)
    return selected, table, active


def _candles(ax: plt.Axes, frame: pd.DataFrame) -> None:
    dates = mdates.date2num(pd.to_datetime(frame.trade_date).to_numpy())
    for x, row in zip(dates, frame.itertuples(index=False), strict=True):
        up = float(row.coord_close) >= float(row.coord_open)
        color = "#d62728" if up else "#138a5b"
        ax.vlines(x, float(row.coord_low), float(row.coord_high), color=color, linewidth=0.55)
        lower = min(float(row.coord_open), float(row.coord_close))
        height = max(abs(float(row.coord_close) - float(row.coord_open)), 1e-5)
        ax.add_patch(Rectangle((x - 0.28, lower), 0.56, height, facecolor=color, edgecolor=color, linewidth=0.35))


def build_chart_paths(daily: pd.DataFrame, sample: pd.DataFrame) -> pd.DataFrame:
    groups = {
        symbol: part.reset_index(drop=True)
        for symbol, part in daily.groupby("symbol", sort=False)
    }
    pieces: list[pd.DataFrame] = []
    for event in sample.itertuples(index=False):
        part = groups[str(event.symbol)]
        start = max(0, int(event.gap_seq) - 90)
        end = min(len(part) - 1, int(event.first_return_seq) + 40)
        view = part.iloc[start : end + 1][
            ["trade_date", "cal_idx", "coord_open", "coord_high", "coord_low", "coord_close", "volume"]
        ].copy()
        view["gap_id"] = event.gap_id
        pieces.append(view)
    result = pd.concat(pieces, ignore_index=True)
    write_parquet(result, CHART_PATHS)
    return result


def _condition_text(conditions: list[dict[str, Any]]) -> list[str]:
    labels = {
        "pre_gap_inside_density_relative_local": "pre-gap inside-gap density / local density",
        "pre_gap_corridor_density_relative_local": "pre-gap corridor density / local density",
        "pre_gap_inside_touch_sessions": "pre-gap sessions intersecting [L,U]",
        "pre_gap_corridor_touch_sessions": "pre-gap sessions intersecting corridor",
        "gap_width_pct": "true-gap width / previous close",
        "gap_age_sessions": "gap-to-pristine-return age",
        "max_depth_below_l_before_return": "maximum depth below L before return",
        "post_gap_lower_corridor_touch_sessions": "post-gap sessions near lower corridor",
        "post_gap_lower_corridor_turnover": "post-gap lower-corridor daily turnover proxy",
        "pre_peak_to_gap_sessions": "prior-120D peak-to-gap duration",
        "pre_gap_drawdown_from_120d_peak": "gap-day drawdown from prior-120D peak",
        "pre_gap_return_20d": "20D return into gap",
        "pre_gap_return_60d": "60D return into gap",
        "pre_gap_max_runup_20d": "20D high/low run-up range",
        "pre_gap_max_runup_60d": "60D high/low run-up range",
        "approach_return_10d": "last-10-session return before first return",
        "approach_path_efficiency_10d": "last-10-session upward path efficiency",
        "higher_low_share_10d": "share of last-10-session low changes that are higher",
    }
    return [
        f"{labels.get(item['feature'], item['feature'])} {item['operator']} {item['threshold']:.6g}"
        for item in conditions
    ]


def render_pdf(sample: pd.DataFrame, paths: pd.DataFrame, profiles: pd.DataFrame, conditions: list[dict[str, Any]], ledger: pd.DataFrame) -> None:
    PDF.parent.mkdir(parents=True, exist_ok=True)
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    path_groups = {key: part for key, part in paths.groupby("gap_id", sort=False)}
    profile_groups = {key: part for key, part in profiles.groupby("gap_id", sort=False)}
    metadata = {
        "Title": f"{EXPERIMENT} all-signal chart book",
        "Author": "CY Market Behavior OS",
        "Subject": "All-market pre-2021 low-inventory true-gap structural fill review; no returns",
        "Keywords": "A-share,true-gap,low-inventory,first-return,structural-fill",
        "CreationDate": datetime(2000, 1, 1, tzinfo=UTC),
        "ModDate": datetime(2000, 1, 1, tzinfo=UTC),
    }
    with PdfPages(PDF, metadata=metadata) as pdf:
        fig = plt.figure(figsize=(15.5, 8.7), facecolor="white")
        fig.text(0.055, 0.89, "All-market low-inventory downward true-gap patterns", fontsize=24, fontweight="bold")
        fig.text(0.055, 0.835, "2014-2020 descriptive discovery | no V6 CORE gate | structural U fill only", fontsize=13, color="#444444")
        mother = _summarize_group(ledger)
        rule = _summarize_group(ledger.loc[ledger.descriptive_rule_match])
        lines = [
            f"Outcome-blind mother population: {mother['n']} gaps / {mother['symbols']} symbols",
            f"Mother U-fill: 5D {mother['u_fill_5d']:.1%} | 10D {mother['u_fill_10d']:.1%} | 20D {mother['u_fill_20d']:.1%} | 40D {mother['u_fill_40d']:.1%}",
            f"Simple-condition matches: {rule['n']} gaps / {rule['symbols']} symbols",
            f"Matched U-fill: 5D {rule['u_fill_5d']:.1%} | 10D {rule['u_fill_10d']:.1%} | 20D {rule['u_fill_20d']:.1%} | 40D {rule['u_fill_40d']:.1%}",
            "",
            "In-sample descriptive conditions:",
            *[f"  {index}. {line}" for index, line in enumerate(_condition_text(conditions), 1)],
            "",
            f"The following {len(sample)} pages include every final condition match.",
            "Orange = true gap [L,U]; grey = inventory corridor [L-0.5W,U+0.5W).",
            "First return is permanently rejected if any touch occurs before five fully-below sessions.",
            "Fill means the price path reached U; it is not a trade or return result.",
        ]
        fig.text(0.065, 0.74, "\n".join(lines), fontsize=12, va="top", linespacing=1.48, family="DejaVu Sans")
        fig.text(0.055, 0.045, "2021 and later are unused. The conditions are same-sample descriptions and require later validation.", fontsize=11, color="#8b0000")
        pdf.savefig(fig, facecolor="white")
        plt.close(fig)

        for page_number, event in enumerate(sample.itertuples(index=False), 1):
            days = path_groups[event.gap_id].sort_values("cal_idx", kind="mergesort")
            profile = profile_groups.get(event.gap_id, profiles.iloc[0:0]).sort_values("z_bin")
            local = days.loc[
                days.cal_idx.between(int(event.first_return_cal_idx) - 30, int(event.first_return_cal_idx) + 40)
            ].copy()
            fig = plt.figure(figsize=(15.5, 8.7), facecolor="white")
            grid = fig.add_gridspec(2, 2, width_ratios=[6.8, 1.35], left=0.05, right=0.985, bottom=0.09, top=0.84, wspace=0.055, hspace=0.22)
            full_ax = fig.add_subplot(grid[0, 0])
            local_ax = fig.add_subplot(grid[1, 0])
            vap_ax = fig.add_subplot(grid[:, 1], sharey=local_ax)
            _candles(full_ax, days)
            _candles(local_ax, local)
            for axis in (full_ax, local_ax, vap_ax):
                axis.axhspan(event.L - 0.5 * event.W, event.U + 0.5 * event.W, color="#9e9e9e", alpha=0.10, zorder=0)
                axis.axhspan(event.L, event.U, color="#ff9800", alpha=0.25, zorder=1)
                axis.axhline(event.L, color="#d95f02", linestyle="--", linewidth=0.9)
                axis.axhline(event.U, color="#d95f02", linestyle="--", linewidth=0.9)
            gap_date = pd.Timestamp(event.gap_date)
            return_time = pd.Timestamp(event.pristine_first_return_time)
            fill_date = pd.Timestamp(event.first_u_fill_date) if pd.notna(event.first_u_fill_date) else pd.NaT
            for axis in (full_ax, local_ax):
                axis.axvline(gap_date, color="#e31a1c", linewidth=1.1)
                axis.axvline(return_time, color="#6a3d9a", linewidth=1.2, linestyle=":")
                axis.scatter(return_time, event.L, marker="^", s=65, color="#6a3d9a", zorder=9)
                if pd.notna(fill_date):
                    axis.axvline(fill_date, color="#087830", linewidth=1.0, linestyle="-.")
                    axis.scatter(fill_date, event.U, marker="*", s=95, color="#087830", zorder=10)
                axis.grid(alpha=0.18)
                axis.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=10))
                axis.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
            full_ax.set_title("Full lifecycle: 90 sessions before gap through 40 sessions after pristine first return", fontsize=10)
            local_ax.set_title("Local first-return window", fontsize=10)
            full_ax.set_ylabel("QD-010 comparable price")
            local_ax.set_ylabel("QD-010 comparable price")
            plt.setp(full_ax.get_xticklabels(), rotation=25, ha="right", fontsize=7)
            plt.setp(local_ax.get_xticklabels(), rotation=25, ha="right", fontsize=7)
            if not profile.empty:
                y = event.L + (profile.z_bin.astype(float) + 0.5) * 0.10 * event.W
                values = profile.pre_float_turnover_mass.astype(float)
                vap_ax.barh(y, values / max(float(values.max()), EPS), height=0.085 * event.W, color="#4c78a8", alpha=0.78)
            vap_ax.set_title("120-session pre-gap\nturnover-at-price proxy", fontsize=10)
            vap_ax.set_xlim(left=0)
            vap_ax.tick_params(axis="y", labelleft=False)
            vap_ax.grid(axis="x", alpha=0.18)
            outcome = "U FILL <=20D" if event.u_full_fill_20d else ("U FILL 21-40D" if event.u_full_fill_40d else "NO U FILL <=40D")
            color = "#087830" if event.u_full_fill_20d else ("#a66b00" if event.u_full_fill_40d else "#b2182b")
            fig.suptitle(f"ALLGAP-{page_number:04d} | {event.symbol} | {event.board} | {outcome}", fontsize=15, fontweight="bold", color=color, y=0.993)
            facts = (
                f"Gap {gap_date.date()} [L,U]=[{event.L:.4f},{event.U:.4f}] width={event.gap_width_pct:.2%} | "
                f"pristine first return {return_time.date()} age={int(event.gap_age_sessions)} sessions | "
                f"max depth below L={event.max_depth_below_l_before_return:.1%}\n"
                f"Pre-gap VAP density: inside={event.pre_gap_inside_density_relative_local:.2f}, corridor={event.pre_gap_corridor_density_relative_local:.2f} | "
                f"pre-gap touch sessions: inside={int(event.pre_gap_inside_touch_sessions)}, corridor={int(event.pre_gap_corridor_touch_sessions)} | "
                f"peak-to-gap={int(event.pre_peak_to_gap_sessions)} sessions"
            )
            fig.text(0.02, 0.93, facts, fontsize=8.6, va="top", linespacing=1.35)
            legend = [
                Rectangle((0, 0), 1, 1, facecolor="#ff9800", alpha=0.25, label="true gap [L,U]"),
                Rectangle((0, 0), 1, 1, facecolor="#9e9e9e", alpha=0.10, label="inventory corridor"),
                plt.Line2D([0], [0], color="#e31a1c", label="gap formation"),
                plt.Line2D([0], [0], color="#6a3d9a", linestyle=":", label="pristine first return"),
            ]
            if pd.notna(fill_date):
                legend.append(plt.Line2D([0], [0], marker="*", color="#087830", linestyle="None", label="first structural U fill"))
            full_ax.legend(handles=legend, loc="best", fontsize=7.5)
            fig.text(0.012, 0.02, f"Page {page_number + 1}/{len(sample) + 1} | Structural path only. No entry, exit, cost, return, PnL, model, or strategy claim.", fontsize=8, color="#555555")
            png = CHART_DIR / f"ALLGAP-{page_number:04d}_{event.symbol}.png"
            fig.savefig(png, dpi=140, bbox_inches="tight", facecolor="white")
            pdf.savefig(fig, dpi=140, facecolor="white")
            plt.close(fig)


def summarize(
    all_gaps: pd.DataFrame,
    funnel: dict[str, Any],
    ledger: pd.DataFrame,
    conditions: list[dict[str, Any]],
    condition_table: pd.DataFrame,
    sample: pd.DataFrame,
    hashes: dict[str, str],
) -> dict[str, Any]:
    rule = ledger.loc[ledger.descriptive_rule_match]
    formation_counts = rule.gap_date.value_counts()
    contrast_features = [
        "gap_width_pct",
        "pre_gap_inside_density_relative_local",
        "pre_gap_corridor_density_relative_local",
        "gap_age_sessions",
        "max_depth_below_l_before_return",
        "post_gap_lower_corridor_turnover",
        "pre_peak_to_gap_sessions",
        "pre_gap_drawdown_from_120d_peak",
        "pre_gap_return_20d",
        "pre_gap_max_runup_20d",
        "higher_low_share_10d",
    ]
    success = ledger.loc[ledger.u_full_fill_20d]
    failure = ledger.loc[~ledger.u_full_fill_20d]
    contrasts = {
        feature: {
            "success_median": float(pd.to_numeric(success[feature], errors="coerce").median()),
            "failure_median": float(pd.to_numeric(failure[feature], errors="coerce").median()),
        }
        for feature in contrast_features
    }
    yearly = []
    for year, base in ledger.groupby("discovery_year", sort=True):
        chosen = rule.loc[rule.discovery_year.eq(year)]
        yearly.append(
            {
                "year": int(year),
                "mother": _summarize_group(base),
                "simple_rule": _summarize_group(chosen) if len(chosen) else {"n": 0},
            }
        )
    result = {
        "experiment": EXPERIMENT,
        "status": "STOPPED_FOR_HUMAN_PATTERN_REVIEW",
        "source_population": {
            "all_true_gaps": len(all_gaps),
            "v6_core_required": False,
            "direct_pit_daily_reconstruction": True,
            "boards": sorted(all_gaps.board.unique().tolist()),
        },
        "funnel": funnel,
        "mother_population": _summarize_group(ledger),
        "simple_conditions": conditions,
        "simple_rule_population": _summarize_group(rule),
        "yearly": yearly,
        "board": {
            str(board): {
                "mother": _summarize_group(part),
                "simple_rule": _summarize_group(rule.loc[rule.board.eq(board)]) if (rule.board == board).any() else {"n": 0},
            }
            for board, part in ledger.groupby("board")
        },
        "condition_candidates_evaluated": len(condition_table),
        "descriptive_concentration": {
            "unique_gap_formation_dates": int(rule.gap_date.nunique()),
            "unique_first_return_dates": int(rule.first_return_date.nunique()),
            "same_day_u_fill_count": int(rule.u_fill_offset.eq(0).sum()),
            "same_day_u_fill_rate": float(rule.u_fill_offset.eq(0).mean()),
            "top_gap_formation_date": str(formation_counts.index[0].date()),
            "top_gap_formation_date_count": int(formation_counts.iloc[0]),
            "top_gap_formation_date_share": float(formation_counts.iloc[0] / len(rule)),
            "top_five_gap_formation_date_share": float(formation_counts.head(5).sum() / len(rule)),
            "gap_formation_date_equal_u_fill_20d": float(rule.groupby("gap_date").u_full_fill_20d.mean().mean()),
            "gap_formation_date_equal_u_fill_40d": float(rule.groupby("gap_date").u_full_fill_40d.mean().mean()),
        },
        "mother_success_failure_median_contrasts": contrasts,
        "chart_book": {
            "pages": len(sample) + 1,
            "signal_charts": len(sample),
            "every_final_match_included": True,
            "success_20d": int(sample.u_full_fill_20d.sum()),
            "failure_20d": int((~sample.u_full_fill_20d).sum()),
            "pdf": str(PDF),
        },
        "scientific_interpretation": "same-sample descriptive structural pattern only; no predictive or trading claim",
        "audit": {
            "V6_CORE_CANDIDATE_GATE_USED": "NO",
            "V6_COLLAPSE_CLUSTER_GATE_USED": "NO",
            "PRE_PERSISTENCE_TOUCH_RESET_AS_FIRST_RETURN_COUNT": 0,
            "FEATURE_USES_POST_FIRST_RETURN_INFORMATION_COUNT": 0,
            "MOTHER_POPULATION_SELECTED_WITH_OUTCOME_COUNT": 0,
            "RETURN_ANALYSIS_RUN": "NO",
            "STRATEGY_BACKTEST_RUN": "NO",
            "PREDICTIVE_VALIDATION_RUN": "NO",
            "DATA_2021_OR_LATER_USED": "NO",
            "REPOSITORY_2024_PLUS_DATA_OPENED": "NO",
        },
        "hashes": hashes,
        "next": "Human review of every final chart, then separately freeze any semantic revision or later-year test.",
    }
    return result


def write_report(result: dict[str, Any]) -> None:
    mother = result["mother_population"]
    rule = result["simple_rule_population"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        "## Status",
        "",
        "`STOPPED_FOR_HUMAN_PATTERN_REVIEW`",
        "",
        "This is a 2014-2020 same-sample structural pattern description. It reconstructs the full governed Main/ChiNext true-gap universe directly from PIT daily rows and does not use a V6 CORE candidate gate.",
        "",
        "## Funnel",
        "",
        "|Stage|Count|",
        "|---|---:|",
        *[f"|{name}|{value}|" for name, value in result["funnel"].items()],
        "",
        "## Structural fill",
        "",
        "|Population|N|Symbols|5D U fill|10D U fill|20D U fill|40D U fill|",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"|Low-inventory mother|{mother['n']}|{mother['symbols']}|{mother['u_fill_5d']:.2%}|{mother['u_fill_10d']:.2%}|{mother['u_fill_20d']:.2%}|{mother['u_fill_40d']:.2%}|",
        f"|Simple conditions|{rule['n']}|{rule['symbols']}|{rule['u_fill_5d']:.2%}|{rule['u_fill_10d']:.2%}|{rule['u_fill_20d']:.2%}|{rule['u_fill_40d']:.2%}|",
        "",
        "## Descriptive conditions",
        "",
    ]
    if result["simple_conditions"]:
        for index, item in enumerate(result["simple_conditions"], 1):
            lines.append(
                f"{index}. `{item['feature']} {item['operator']} {item['threshold']:.6g}` ({item['threshold_source']}; N={item['n']}, 20D fill={item['pooled_rate']:.2%}, pooled lift={item['pooled_lift']:+.2%}, positive-lift years={item['positive_year_lift_count']})."
            )
    else:
        lines.append("No condition met the frozen support, chronology, and incremental-lift gate.")
    lines.extend(
        [
            "",
            "These conditions were discovered and measured on the same 2014-2020 sample. They are not predictive evidence and are not a strategy.",
            "",
            "## Concentration and interpretation",
            "",
            f"The final {rule['n']}-event description spans {result['descriptive_concentration']['unique_gap_formation_dates']} formation dates. The largest date is {result['descriptive_concentration']['top_gap_formation_date']} with {result['descriptive_concentration']['top_gap_formation_date_count']} events ({result['descriptive_concentration']['top_gap_formation_date_share']:.2%}); the top five dates contribute {result['descriptive_concentration']['top_five_gap_formation_date_share']:.2%}. Formation-date-equal 20D fill is {result['descriptive_concentration']['gap_formation_date_equal_u_fill_20d']:.2%}.",
            f"Same-day structural U fill accounts for {result['descriptive_concentration']['same_day_u_fill_count']} events ({result['descriptive_concentration']['same_day_u_fill_rate']:.2%}). This is structural geometry, not executable headroom.",
            "Successful mother-population cases are descriptively associated with narrower gaps, longer peak-to-gap histories, deeper prior drawdowns, less acute 20-day run-up, and lower post-gap lower-corridor turnover. These secondary contrasts did not replace the frozen two-condition selector.",
            "",
            "## Calendar-year view",
            "",
            "|Year|Mother N|Mother 20D|Rule N|Rule 20D|",
            "|---:|---:|---:|---:|---:|",
        ]
    )
    for item in result["yearly"]:
        rule_year = item["simple_rule"]
        rule_rate = "-" if not rule_year.get("n") else f"{rule_year['u_fill_20d']:.2%}"
        lines.append(f"|{item['year']}|{item['mother']['n']}|{item['mother']['u_fill_20d']:.2%}|{rule_year.get('n', 0)}|{rule_rate}|")
    lines.extend(
        [
            "",
            "## Chart book",
            "",
            f"The PDF contains one summary page plus all {result['chart_book']['signal_charts']} final condition matches. Every page shows the full gap-to-return lifecycle, a local first-return view, `[L,U]`, the surrounding corridor, and the 120-session pre-gap turnover-at-price profile.",
            "",
            "## Audit",
            "",
            f"`{json.dumps(result['audit'], ensure_ascii=False, sort_keys=True)}`",
            "",
            "No returns, PnL, trading replay, prediction, 2021+ data, or repository 2024+ data were opened. Stop for human review.",
        ]
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(stage: str) -> None:
    validate_inputs()
    EXT.mkdir(parents=True, exist_ok=True)
    hashes = freeze_stage_a_contract()
    daily = load_daily()
    if stage in {"stage-a", "full"}:
        all_gaps = build_all_true_gaps(daily)
        mother, funnel = freeze_stage_a_mother(daily, all_gaps)
        write_json(EXT / "stage_a_funnel.json", funnel)
        print(json.dumps({"stage": "A", "funnel": funnel, "mother": len(mother)}, indent=2))
        if stage == "stage-a":
            return
    else:
        all_gaps = pd.read_parquet(ALL_GAPS)
        mother = pd.read_parquet(STAGE_A_LEDGER)
        funnel = json.loads((EXT / "stage_a_funnel.json").read_text())
        for column in ("gap_date", "first_return_date", "pristine_first_return_time"):
            mother[column] = pd.to_datetime(mother[column])
    ledger = attach_structural_outcomes(mother, daily)
    direct_feature_analysis(ledger)
    conditions, table, mask = discover_simple_conditions(ledger)
    ledger["descriptive_rule_match"] = mask
    write_parquet(ledger, DISCOVERY_LEDGER)
    sample = ledger.loc[mask].copy().sort_values(["first_return_date", "symbol", "gap_id"], kind="mergesort").reset_index(drop=True)
    sample["chart_id"] = [f"ALLGAP-{index:04d}" for index in range(1, len(sample) + 1)]
    sample.to_csv(CHART_INDEX, index=False)
    paths = build_chart_paths(daily, sample)
    profiles = pd.read_parquet(VAP_PROFILES)
    profiles = profiles.loc[profiles.gap_id.isin(sample.gap_id)].copy()
    render_pdf(sample, paths, profiles, conditions, ledger)
    hashes.update(
        {
            "all_gap_ledger_sha256": sha256(ALL_GAPS),
            "stage_a_ledger_sha256": sha256(STAGE_A_LEDGER),
            "discovery_ledger_sha256": sha256(DISCOVERY_LEDGER),
            "direct_analysis_sha256": sha256(DIRECT_ANALYSIS),
            "condition_table_sha256": sha256(CONDITION_TABLE),
            "chart_index_sha256": sha256(CHART_INDEX),
            "pdf_sha256": sha256(PDF),
        }
    )
    result = summarize(all_gaps, funnel, ledger, conditions, table, sample, hashes)
    write_json(RESULT, result)
    write_report(result)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("stage-a", "stage-b", "full"), default="full")
    args = parser.parse_args()
    run(args.stage)


if __name__ == "__main__":
    main()
