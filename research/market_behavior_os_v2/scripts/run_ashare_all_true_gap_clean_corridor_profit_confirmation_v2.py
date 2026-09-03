#!/usr/bin/env python3
"""One-shot 2021 confirmation of a simple clean-corridor true-gap rule.

The rule is designed on already-consumed 2014-2020 outcomes and is frozen
before any 2021 post-entry outcome is opened.  It deliberately does not claim
that the design years are new OOF evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages

from research.market_behavior_os_v2.scripts import (
    run_ashare_all_true_gap_executable_simple_profit_development_v1 as base,
)

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-ALL-TRUE-GAP-CLEAN-CORRIDOR-PROFIT-CONFIRMATION-V2"
START_HEAD = "fa3e87792a6cfd0b4ae5eef3df1cdc3f65eb2c8d"

DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
RAW_ROOT = Path(
    "/Users/linmei/Downloads/workspace/quant/data/lake/stock_1min_canonical_none_20260813/bars"
)
LEGAL_OPENS = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_causal_cluster_v6_one_shot_discovery/legal_opens.parquet"
)
ACTION_EVENTS = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_causal_cluster_v6_one_shot_discovery/action_events.parquet"
)
SOURCE_ALL_GAPS = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_all_true_gap_low_inventory_fill_pattern_discovery_v2/"
    "all_true_gap_primitives_2014_2020.parquet"
)
SOURCE_ALL_GAPS_SHA256 = "afdb8b05b2166d71466fa7d8413030ac9b3fafe141e7f0326718d89fddd9b288"

DESIGN_POLICY_OUTCOMES = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_all_true_gap_executable_simple_profit_development_v1/"
    "policy_outcomes.parquet"
)
DESIGN_VAP = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_all_true_gap_executable_simple_profit_development_v1/"
    "raw_tick_pre_gap_vap_profiles.parquet"
)
DESIGN_ENTRIES = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_all_true_gap_executable_simple_profit_development_v1/"
    "entry_candidates.parquet"
)

EXT = Path(
    "/Volumes/quant/CY_quant_research/ashare_all_true_gap_clean_corridor_profit_confirmation_v2"
)
MANIFESTS = EXT / "manifests"
ALL_GAPS_2021 = EXT / "all_true_gaps_through_2021.parquet"
DAILY_CANDIDATES_2021 = EXT / "daily_candidates_2021.parquet"
PRE_GAP_DAYS_2021 = EXT / "pre_gap_days_2021.parquet"
VAP_PARTS_2021 = EXT / "vap_parts_2021"
VAP_2021 = EXT / "vap_profiles_2021.parquet"
BROAD_MOTHER_2021 = EXT / "broad_mother_2021.parquet"
FIXED_MOTHER_2021 = EXT / "fixed_rule_mother_2021.parquet"
FIRST_RETURN_SEED_2021 = EXT / "first_return_seed_2021.parquet"
ENTRY_DAY_SEED_2021 = EXT / "entry_day_seed_2021.parquet"
ENTRY_DAY_MINUTES_2021 = EXT / "entry_day_minutes_2021.parquet"
ENTRIES_2021 = EXT / "entry_candidates_2021.parquet"
OUTCOME_BOUNDS_2021 = EXT / "outcome_bounds_2021.parquet"
OUTCOME_MINUTES_2021 = EXT / "outcome_minutes_2021.parquet"
OUTCOMES_2021 = EXT / "policy_outcomes_2021.parquet"
DESIGN_FIXED_TRADES = EXT / "design_fixed_trades.parquet"
CONFIRMATION_TRADES = EXT / "confirmation_trades.parquet"
PORTFOLIO_SUMMARY = EXT / "portfolio_summary.parquet"
PORTFOLIO_NAV = EXT / "portfolio_nav.parquet"
PORTFOLIO_ACCEPTED = EXT / "portfolio_accepted.parquet"
PORTFOLIO_LEDGER = EXT / "portfolio_ledger.parquet"

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
CHART_INDEX = OS / f"artifacts/{EXPERIMENT}_chart_index.csv"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"
PDF = ROOT / f"output/pdf/{EXPERIMENT}_all_signal_charts.pdf"

DESIGN_START = pd.Timestamp("2014-01-01")
DESIGN_END = pd.Timestamp("2020-12-31")
CONFIRM_START = pd.Timestamp("2021-01-01")
CONFIRM_END = pd.Timestamp("2021-12-31")
DESIGN_PORTFOLIO_YEARS = (2017, 2018, 2019, 2020)
CONFIRM_PORTFOLIO_YEARS = (2021,)

COST = 0.002
PRE_GAP_SESSIONS = 120
MIN_GAP_WIDTH_PCT = 0.01
MIN_FULLY_BELOW_SESSIONS = 5
MAX_INSIDE_TOUCH_SESSIONS = 12
MAX_CORRIDOR_TOUCH_SESSIONS = 20
MAX_MEAN_DENSITY_RELATIVE_LOCAL = 1.0
MAX_CORRIDOR_BIN_DENSITY_RELATIVE_LOCAL = 2.5
MIN_PEAK_TO_GAP_SESSIONS = 60
MAX_PRE_GAP_20D_RANGE = 0.20
MINIMUM_NET_HEADROOM = 0.015
TIME_STOP = 10
PRIMARY_K = 2
K_SENSITIVITY = (2, 3, 5, 10)
ENTRY_FORM = "E1_CLOSE_L"
EXIT_POLICY = "X1_CLOSE_BELOW_L"
EPS = 1e-12


class ResearchError(RuntimeError):
    pass


def raw_path(year: int) -> Path:
    return RAW_ROOT / f"{year}_day_parquet_none.parquet"


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if pd.isna(value):
        return None
    raise TypeError(type(value).__name__)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=_json_default,
        )
        + "\n",
        encoding="utf-8",
    )


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


def manifest(name: str, value: dict[str, Any]) -> None:
    write_json(MANIFESTS / f"{name}.json", value)


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "scientific_role": (
            "development-informed fixed-rule reconstruction plus one-shot "
            "previously unread 2021 outcome confirmation"
        ),
        "source": {
            "population": "all governed Main/ChiNext downward true gaps",
            "true_gap": "High_t < Low_t_minus_1",
            "interval": "[High_t, Low_t_minus_1] = [L,U]",
            "v6_core_gate_used": False,
            "v2_selected_305_used": False,
            "historical_all_gap_ledger_sha256": SOURCE_ALL_GAPS_SHA256,
            "confirmation_gap_cohort": (
                "all governed 2014-2021 gaps whose first exact raw-fen return occurs in 2021"
            ),
            "raw_tick_interaction": (
                "floor(raw_price*100+0.5+1e-6) compared with the mapped "
                "QD-010 coordinate boundary in raw fen"
            ),
        },
        "chronology": {
            "design_outcomes_already_consumed": ["2014-01-01", "2020-12-31"],
            "design_portfolio_reference": ["2017-01-01", "2020-12-31"],
            "one_shot_confirmation": ["2021-01-01", "2021-12-31"],
            "2021_post_entry_outcomes_known_before_freeze": False,
            "2022_and_later_used": False,
            "repository_2024_plus_opened": False,
        },
        "stage_a_mother": {
            "minimum_gap_width_pct_retrieval_only": MIN_GAP_WIDTH_PCT,
            "exact_pre_gap_sessions": PRE_GAP_SESSIONS,
            "exact_minutes_per_session": 241,
            "minimum_fully_below_sessions": MIN_FULLY_BELOW_SESSIONS,
            "prior_exact_touch_resets_clock": False,
            "maximum_pre_gap_inside_touch_sessions": MAX_INSIDE_TOUCH_SESSIONS,
            "maximum_pre_gap_corridor_touch_sessions": MAX_CORRIDOR_TOUCH_SESSIONS,
            "mean_inside_density_relative_local_max": MAX_MEAN_DENSITY_RELATIVE_LOCAL,
            "mean_corridor_density_relative_local_max": MAX_MEAN_DENSITY_RELATIVE_LOCAL,
            "local_vap_window_z": [-2.0, 3.0],
            "corridor_z": [-0.5, 1.5],
            "vap_bin_width_w": 0.10,
        },
        "fixed_simple_rule": {
            "condition_1": (
                "maximum pre-gap VAP mass in any 0.10W bin of z=[-0.5,1.5) "
                "<=2.5 times mean bin mass in z=[-2,3)"
            ),
            "condition_2": "120-session reference peak is at least 60 sessions before gap",
            "condition_3": (
                "pre-gap 20-session coordinate high-low range <=20%; this is "
                "a range/non-acute condition, not a chronological run-up statistic"
            ),
            "condition_4": "entry retains at least 1.5% net target headroom after 40 bp",
            "threshold_origin": (
                "chosen after already-consumed 2014-2020 Development and chart review; "
                "frozen before 2021 outcomes; no retrospective OOF claim"
            ),
        },
        "entry": {
            "trigger": "first completed one-minute close >= L on exact first-return day",
            "fill": "next legal one-minute open strictly after trigger",
            "buy_limit": "IOC limit preserving minimum net U headroom",
        },
        "exit": {
            "target": "legal U realization, no earlier than T+1",
            "failure": (
                "first completed sellable-session daily close below L; exit next legal open"
            ),
            "time_stop": "H10 close information; exit next legal open",
        },
        "portfolio": {
            "primary_k_per_board_sleeve": PRIMARY_K,
            "sensitivity_k": list(K_SENSITIVITY),
            "main_weight": 0.5,
            "chinext_weight": 0.5,
            "one_position_per_symbol": True,
            "no_leverage": True,
            "unused_cash": True,
            "collision_rank": [
                "earlier entry timestamp",
                "higher realized net U headroom",
                "lower pre-gap inside density",
                "symbol",
                "gap_id",
            ],
        },
        "validation_gate": {
            "minimum_completed_trades": 15,
            "required": [
                "mean_net>0",
                "median_net>0",
                "combined_return>0",
                "return_excluding_best_day>0",
                "severe_loss10<=5%",
                "max_drawdown>-10%",
            ],
            "interpretation": "one-year confirmation only, never final external validation",
        },
    }


def spec_value(contract_hash: str) -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "start_head": START_HEAD,
        "contract_sha256": contract_hash,
        "mission": (
            "Freeze the simplest development-informed clean-corridor/non-acute "
            "true-gap rule, then test it once on previously unread 2021 outcomes."
        ),
        "stage_order": [
            "FREEZE_RULE_AND_2021_SIGNAL_CONTRACT",
            "BUILD_2021_OUTCOME_BLIND_CANDIDATES",
            "VERIFY_STAGE_A_HASHES",
            "OPEN_2021_OUTCOMES_ONCE",
            "REPLAY_FIXED_K2_AND_K_SENSITIVITY",
            "RENDER_ALL_DESIGN_AND_CONFIRMATION_SIGNALS",
            "STOP",
        ],
        "prohibited": [
            "rule change after 2021 outcome opening",
            "new threshold after 2021 outcome opening",
            "2022+ data",
            "2024+ data",
            "V6 CORE gate",
            "model fitting",
            "leverage",
        ],
    }


def persist_contracts() -> dict[str, str]:
    write_json(CONTRACT, contract_value())
    contract_hash = sha256(CONTRACT)
    write_json(SPEC, spec_value(contract_hash))
    return {"contract_sha256": contract_hash, "spec_sha256": sha256(SPEC)}


def validate_inputs() -> None:
    paths = [
        DAILY,
        LEGAL_OPENS,
        ACTION_EVENTS,
        SOURCE_ALL_GAPS,
        DESIGN_POLICY_OUTCOMES,
        DESIGN_VAP,
        DESIGN_ENTRIES,
        *[raw_path(year) for year in range(2013, 2022)],
    ]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise ResearchError(f"missing input(s): {missing}")
    if sha256(SOURCE_ALL_GAPS) != SOURCE_ALL_GAPS_SHA256:
        raise ResearchError("source all-gap ledger hash mismatch")


def load_daily_through_2021() -> pd.DataFrame:
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
        "trade_status",
        "current_day_data_tradable",
        "market_rule_valid",
        "up_limit_price",
        "down_limit_price",
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
        SELECT {",".join(columns)}
        FROM read_parquet('{DAILY}')
        WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2021-12-31'
          AND sleeve IN ('MAIN','CHINEXT')
        ORDER BY symbol,trade_date
        """
    ).fetchdf()
    con.close()
    frame.trade_date = pd.to_datetime(frame.trade_date)
    if frame.empty or frame.trade_date.max() != CONFIRM_END:
        raise ResearchError("daily 2021 coverage failure")
    frame["symbol_seq"] = frame.groupby("symbol", sort=False).cumcount()
    return frame


def _valid_daily_rows(frame: pd.DataFrame) -> np.ndarray:
    return (
        frame.hard_valid.fillna(False)
        & frame.history_valid.fillna(False)
        & frame.current_valid.fillna(False)
        & frame.corporate_action_valid.fillna(False)
        & ~frame.corporate_action_blocking.fillna(True)
    ).to_numpy(bool)


def _price_ticks(value: pd.Series | np.ndarray | float) -> np.ndarray:
    return np.floor(np.asarray(value, dtype=float) * 100.0 + 0.5 + 1e-6).astype(np.int64)


def _boundary_ticks(
    coordinate_boundary: float,
    coordinate_factor: pd.Series | np.ndarray | float,
) -> np.ndarray:
    return _price_ticks(float(coordinate_boundary) / np.asarray(coordinate_factor, float))


def _raw_tick_reached(
    raw_high: pd.Series | np.ndarray,
    coordinate_boundary: float,
    coordinate_factor: pd.Series | np.ndarray,
) -> np.ndarray:
    return _price_ticks(raw_high) >= _boundary_ticks(coordinate_boundary, coordinate_factor)


def build_all_true_gaps_2021(daily: pd.DataFrame) -> pd.DataFrame:
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
        frame.trade_date.between(CONFIRM_START, CONFIRM_END)
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
    new_gaps = frame.loc[mask].copy()
    new_gaps["gap_id"] = (
        new_gaps.symbol.astype(str) + "|" + new_gaps.trade_date.dt.strftime("%Y-%m-%d")
    )
    new_gaps["gap_date"] = new_gaps.trade_date
    new_gaps["gap_seq"] = new_gaps.symbol_seq.astype(int)
    new_gaps["board"] = new_gaps.sleeve.astype(str)
    new_gaps["L"] = new_gaps.high.astype(float) * new_gaps.coordinate_factor.astype(float)
    new_gaps["U"] = new_gaps.previous_low.astype(float) * new_gaps.coordinate_factor.astype(float)
    new_gaps["W"] = new_gaps.U - new_gaps.L
    new_gaps["gap_width_pct"] = (new_gaps.previous_low - new_gaps.high) / new_gaps.previous_close
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
    historical = pd.read_parquet(SOURCE_ALL_GAPS)
    historical["gap_date"] = pd.to_datetime(historical.gap_date)
    historical["previous_trade_date"] = pd.to_datetime(historical.previous_trade_date)
    gaps = pd.concat([historical[keep], new_gaps[keep]], ignore_index=True)
    gaps = gaps.sort_values(["gap_date", "symbol"], kind="mergesort")
    gaps = gaps.reset_index(drop=True)
    if gaps.gap_id.duplicated().any() or not gaps.W.gt(0).all():
        raise ResearchError("2021 true-gap identity failure")
    write_parquet(gaps, ALL_GAPS_2021)
    return gaps


def build_daily_candidates_2021(daily: pd.DataFrame, gaps: pd.DataFrame) -> pd.DataFrame:
    groups = {
        symbol: part.reset_index(drop=True) for symbol, part in daily.groupby("symbol", sort=False)
    }
    last_cal_idx = int(daily.loc[daily.trade_date.eq(CONFIRM_END), "cal_idx"].max())
    rows: list[dict[str, Any]] = []
    for gap in gaps.loc[gaps.gap_width_pct.ge(MIN_GAP_WIDTH_PCT)].itertuples(index=False):
        part = groups[str(gap.symbol)]
        pos = int(gap.gap_seq)
        if pos >= len(part) or pd.Timestamp(part.iloc[pos].trade_date) != pd.Timestamp(
            gap.gap_date
        ):
            raise ResearchError(f"gap sequence mismatch {gap.gap_id}")
        reason = "ELIGIBLE_FOR_MINUTE_VAP"
        hist = part.iloc[pos - PRE_GAP_SESSIONS : pos].copy()
        history_ok = (
            len(hist) == PRE_GAP_SESSIONS
            and _valid_daily_rows(hist).all()
            and hist.invalid_step_cum.eq(float(gap.invalid_step_cum)).all()
        )
        if not history_ok:
            reason = "NO_EXACT_120_SAME_LINEAGE_DAILY_HISTORY"
        future = part.iloc[pos + 1 :].copy()
        if len(future):
            future_valid = _valid_daily_rows(future) & future.invalid_step_cum.eq(
                float(gap.invalid_step_cum)
            ).to_numpy(bool)
            invalid = np.flatnonzero(~future_valid)
            if len(invalid):
                future = future.iloc[: int(invalid[0])]
        touches = (
            _raw_tick_reached(future.high, float(gap.L), future.coordinate_factor)
            if len(future)
            else np.array([], dtype=bool)
        )
        positions = np.flatnonzero(touches)
        first_rel = None if not len(positions) else int(positions[0])
        if reason == "ELIGIBLE_FOR_MINUTE_VAP" and first_rel is None:
            reason = "NO_FIRST_RETURN_IN_2021"
        if (
            reason == "ELIGIBLE_FOR_MINUTE_VAP"
            and first_rel is not None
            and first_rel < MIN_FULLY_BELOW_SESSIONS
        ):
            reason = "REJECTED_PRE_PERSISTENCE_TOUCH"
        first_pos = None if first_rel is None else pos + 1 + first_rel
        if reason == "ELIGIBLE_FOR_MINUTE_VAP" and first_pos is not None:
            first_return_date = pd.Timestamp(part.iloc[first_pos].trade_date)
            if first_return_date < CONFIRM_START:
                reason = "FIRST_RETURN_BEFORE_CONFIRMATION"
        if reason == "ELIGIBLE_FOR_MINUTE_VAP" and first_pos is not None:
            first_cal_idx = int(part.iloc[first_pos].cal_idx)
            if first_cal_idx + TIME_STOP + 1 > last_cal_idx:
                reason = "INCOMPLETE_H10_AND_NEXT_OPEN_IN_2021"
        inside_touches = math.nan
        corridor_touches = math.nan
        features: dict[str, Any] = {}
        if history_ok:
            inside = hist.coord_high.ge(float(gap.L)) & hist.coord_low.lt(float(gap.U))
            corridor = hist.coord_high.ge(float(gap.L - 0.5 * gap.W)) & hist.coord_low.lt(
                float(gap.U + 0.5 * gap.W)
            )
            inside_touches = int(inside.sum())
            corridor_touches = int(corridor.sum())
            if reason == "ELIGIBLE_FOR_MINUTE_VAP" and inside_touches > MAX_INSIDE_TOUCH_SESSIONS:
                reason = "PRE_GAP_EXACT_OCCUPANCY_TOO_HIGH"
            if (
                reason == "ELIGIBLE_FOR_MINUTE_VAP"
                and corridor_touches > MAX_CORRIDOR_TOUCH_SESSIONS
            ):
                reason = "PRE_GAP_CORRIDOR_OCCUPANCY_TOO_HIGH"
            peak_offset = int(np.nanargmax(hist.coord_high.to_numpy(float)))
            peak = float(hist.iloc[peak_offset].coord_high)
            recent20 = hist.tail(20)
            features = {
                "pre_gap_inside_touch_sessions": inside_touches,
                "pre_gap_corridor_touch_sessions": corridor_touches,
                "pre_peak_date": pd.Timestamp(hist.iloc[peak_offset].trade_date),
                "pre_peak_to_gap_sessions": int(len(hist) - peak_offset),
                "pre_gap_drawdown_from_120d_peak": float(1 - float(gap.coord_low) / peak),
                "pre_gap_return_20d": float(
                    hist.iloc[-1].coord_close / hist.iloc[-20].coord_close - 1
                ),
                "pre_gap_range_20d": float(
                    recent20.coord_high.max() / recent20.coord_low.min() - 1
                ),
            }
        if first_pos is not None:
            return_row = part.iloc[first_pos]
            below = part.iloc[pos + 1 : first_pos]
            lower_corridor = below.coord_high.ge(float(gap.L - 0.5 * gap.W))
            features.update(
                {
                    "first_return_date": pd.Timestamp(return_row.trade_date),
                    "first_return_cal_idx": int(return_row.cal_idx),
                    "first_return_seq": int(return_row.symbol_seq),
                    "first_return_coordinate_factor": float(return_row.coordinate_factor),
                    "gap_age_sessions": int(first_pos - pos),
                    "max_depth_below_l_before_return": (
                        float(1 - below.coord_low.min() / float(gap.L)) if len(below) else 0.0
                    ),
                    "post_gap_lower_corridor_touch_sessions": int(lower_corridor.sum()),
                    "post_gap_lower_corridor_turnover": float(
                        below.loc[lower_corridor, "turnover_fraction"].sum()
                    ),
                }
            )
        rows.append(
            {
                **gap._asdict(),
                **features,
                "daily_history_complete": bool(history_ok),
                "first_post_gap_touch_is_pristine": bool(
                    first_rel is not None and first_rel >= MIN_FULLY_BELOW_SESSIONS
                ),
                "pre_gap_inside_touch_sessions": inside_touches,
                "pre_gap_corridor_touch_sessions": corridor_touches,
                "stage_a_daily_disposition": reason,
            }
        )
    result = pd.DataFrame(rows)
    if result.gap_id.duplicated().any():
        raise ResearchError("duplicate daily candidate")
    write_parquet(result, DAILY_CANDIDATES_2021)
    return result


def build_pre_gap_days_2021(daily: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    selected = candidates.loc[candidates.stage_a_daily_disposition.eq("ELIGIBLE_FOR_MINUTE_VAP")]
    groups = {
        symbol: part.reset_index(drop=True) for symbol, part in daily.groupby("symbol", sort=False)
    }
    pieces: list[pd.DataFrame] = []
    for event in selected.itertuples(index=False):
        hist = (
            groups[str(event.symbol)]
            .iloc[int(event.gap_seq) - PRE_GAP_SESSIONS : int(event.gap_seq)][
                [
                    "symbol",
                    "trade_date",
                    "coordinate_factor",
                    "turnover_fraction",
                ]
            ]
            .copy()
        )
        if len(hist) != PRE_GAP_SESSIONS:
            raise ResearchError(f"pre-gap history failure {event.gap_id}")
        hist["gap_id"] = event.gap_id
        hist["L"] = float(event.L)
        hist["W"] = float(event.W)
        pieces.append(hist)
    result = pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()
    if result.empty or result.duplicated(["gap_id", "trade_date"]).any():
        raise ResearchError("pre-gap day panel failure")
    write_parquet(result, PRE_GAP_DAYS_2021)
    return result


def _vap_query(year: int) -> str:
    return f"""
    WITH p AS (
      SELECT * FROM read_parquet('{PRE_GAP_DAYS_2021}')
      WHERE year(trade_date)={year}
    ), raw0 AS (
      SELECT r.qmt_code AS symbol,r.trade_date,r.bar_end_time,
             r.high,r.low,r.close,r.volume,r.amount
      FROM read_parquet('{raw_path(year)}') r
      JOIN (SELECT DISTINCT symbol,trade_date FROM p) n
        ON r.qmt_code=n.symbol AND r.trade_date=n.trade_date
      WHERE r.period='1m' AND r.adjust='none'
    ), joined0 AS (
      SELECT p.gap_id,p.trade_date,p.coordinate_factor,p.turnover_fraction,
             p.L,p.W,r.bar_end_time,r.high,r.low,r.close,r.volume,r.amount,
             count(*) OVER(PARTITION BY p.gap_id,p.trade_date) AS bars_in_session,
             sum(r.volume) OVER(PARTITION BY p.gap_id,p.trade_date) AS day_volume
      FROM p JOIN raw0 r USING(symbol,trade_date)
    ), joined AS (
      SELECT *,
        CASE WHEN volume>0 AND amount>0 THEN amount/volume
             ELSE (high+low+close)/3 END AS minute_price,
        CASE WHEN day_volume>0 THEN turnover_fraction*volume/day_volume
             ELSE NULL END AS minute_weight
      FROM joined0
    ), quality AS (
      SELECT gap_id,-999::INTEGER AS z_bin,
             count(DISTINCT trade_date)::DOUBLE AS mass,
             count(DISTINCT trade_date) FILTER(
               WHERE bars_in_session=241 AND day_volume>0
             )::DOUBLE AS auxiliary
      FROM joined GROUP BY gap_id
    ), bins AS (
      SELECT gap_id,
             floor(((minute_price*coordinate_factor-L)/W)/0.10)::INTEGER AS z_bin,
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


def build_vap_2021(
    candidates: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    VAP_PARTS_2021.mkdir(parents=True, exist_ok=True)
    pre_days = pd.read_parquet(PRE_GAP_DAYS_2021)
    years = sorted(pd.to_datetime(pre_days.trade_date).dt.year.unique())
    parts: list[pd.DataFrame] = []
    for year in years:
        path = VAP_PARTS_2021 / f"year={int(year)}.parquet"
        con = duckdb.connect()
        con.execute("SET threads=4")
        con.execute("SET memory_limit='8GB'")
        con.execute(f"SET temp_directory='{EXT / 'duckdb_tmp'}'")
        frame = con.execute(_vap_query(int(year))).fetchdf()
        con.close()
        write_parquet(frame, path)
        parts.append(frame)
    combined = pd.concat(parts, ignore_index=True)
    quality = (
        combined.loc[combined.z_bin.eq(-999)]
        .groupby("gap_id", as_index=False)
        .agg(
            minute_history_sessions=("mass", "sum"),
            exact_241_minute_sessions=("auxiliary", "sum"),
        )
    )
    profiles = (
        combined.loc[combined.z_bin.ne(-999)]
        .groupby(["gap_id", "z_bin"], as_index=False)
        .agg(
            pre_float_turnover_mass=("mass", "sum"),
            contributing_minutes=("auxiliary", "sum"),
        )
    )
    write_parquet(profiles, VAP_2021)
    local = profiles.groupby("gap_id", as_index=False).agg(
        local_mass=("pre_float_turnover_mass", "sum")
    )
    inside = (
        profiles.loc[profiles.z_bin.between(0, 9)]
        .groupby("gap_id", as_index=False)
        .pre_float_turnover_mass.sum()
        .rename(columns={"pre_float_turnover_mass": "inside_mass"})
    )
    corridor = (
        profiles.loc[profiles.z_bin.between(-5, 14)]
        .groupby("gap_id", as_index=False)
        .pre_float_turnover_mass.sum()
        .rename(columns={"pre_float_turnover_mass": "corridor_mass"})
    )
    corridor_max = (
        profiles.loc[profiles.z_bin.between(-5, 14)]
        .groupby("gap_id", as_index=False)
        .pre_float_turnover_mass.max()
        .rename(columns={"pre_float_turnover_mass": "corridor_max_bin_mass"})
    )
    metrics = quality.merge(local, on="gap_id", how="left")
    metrics = metrics.merge(inside, on="gap_id", how="left")
    metrics = metrics.merge(corridor, on="gap_id", how="left")
    metrics = metrics.merge(corridor_max, on="gap_id", how="left")
    mass_columns = [
        "local_mass",
        "inside_mass",
        "corridor_mass",
        "corridor_max_bin_mass",
    ]
    metrics[mass_columns] = metrics[mass_columns].fillna(0.0)
    local = metrics.local_mass.replace(0, np.nan)
    metrics["pre_gap_inside_density_relative_local"] = 5.0 * metrics.inside_mass / local
    metrics["pre_gap_corridor_density_relative_local"] = 2.5 * metrics.corridor_mass / local
    metrics["pre_gap_corridor_max_bin_density_relative_local"] = (
        50.0 * metrics.corridor_max_bin_mass / local
    )
    selected = candidates.loc[
        candidates.stage_a_daily_disposition.eq("ELIGIBLE_FOR_MINUTE_VAP")
    ].merge(metrics, on="gap_id", how="left", validate="one_to_one")
    selected["exact_minute_history"] = selected.minute_history_sessions.eq(
        PRE_GAP_SESSIONS
    ) & selected.exact_241_minute_sessions.eq(PRE_GAP_SESSIONS)
    return selected, profiles


def attach_first_return_minutes_2021(mother: pd.DataFrame) -> pd.DataFrame:
    seed = mother[
        [
            "gap_id",
            "symbol",
            "first_return_date",
            "first_return_coordinate_factor",
            "L",
        ]
    ].copy()
    write_parquet(seed, FIRST_RETURN_SEED_2021)
    con = duckdb.connect()
    frame = con.execute(
        f"""
        WITH s AS (SELECT * FROM read_parquet('{FIRST_RETURN_SEED_2021}')),
        joined AS (
          SELECT s.gap_id,r.bar_end_time,r.high,
                 count(*) OVER(PARTITION BY s.gap_id) AS bars_in_session
          FROM s
          JOIN read_parquet('{raw_path(2021)}') r
            ON r.qmt_code=s.symbol AND r.trade_date=s.first_return_date
          WHERE r.period='1m' AND r.adjust='none'
        )
        SELECT s.gap_id,
               min(j.bar_end_time) FILTER(
                 WHERE floor(j.high*100+0.5+1e-6) >=
                       floor((s.L/s.first_return_coordinate_factor)*100+0.5+1e-6)
               ) AS pristine_first_return_time,
               max(j.bars_in_session) AS first_return_session_minutes
        FROM s JOIN joined j USING(gap_id)
        GROUP BY s.gap_id
        ORDER BY s.gap_id
        """
    ).fetchdf()
    con.close()
    frame.pristine_first_return_time = pd.to_datetime(frame.pristine_first_return_time)
    result = mother.merge(frame, on="gap_id", how="left", validate="one_to_one")
    result["exact_first_return_minute_valid"] = (
        result.pristine_first_return_time.notna() & result.first_return_session_minutes.eq(241)
    )
    return result.loc[result.exact_first_return_minute_valid].copy()


def build_mothers_2021(
    candidates: pd.DataFrame, vap_metrics: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    broad = vap_metrics.loc[
        vap_metrics.exact_minute_history
        & vap_metrics.pre_gap_inside_density_relative_local.le(MAX_MEAN_DENSITY_RELATIVE_LOCAL)
        & vap_metrics.pre_gap_corridor_density_relative_local.le(MAX_MEAN_DENSITY_RELATIVE_LOCAL)
    ].copy()
    broad = attach_first_return_minutes_2021(broad)
    fixed = broad.loc[
        broad.pre_gap_corridor_max_bin_density_relative_local.le(
            MAX_CORRIDOR_BIN_DENSITY_RELATIVE_LOCAL
        )
        & broad.pre_peak_to_gap_sessions.ge(MIN_PEAK_TO_GAP_SESSIONS)
        & broad.pre_gap_range_20d.le(MAX_PRE_GAP_20D_RANGE)
    ].copy()
    forbidden = [
        column
        for column in fixed.columns
        if any(
            token in column.lower() for token in ("net_return", "pnl", "profit", "winner", "u_fill")
        )
    ]
    if forbidden or fixed.gap_id.duplicated().any():
        raise ResearchError(f"Stage-A mother audit failure: {forbidden}")
    write_parquet(broad, BROAD_MOTHER_2021)
    write_parquet(fixed, FIXED_MOTHER_2021)
    return broad, fixed


def build_entry_day_minutes_2021(mother: pd.DataFrame) -> pd.DataFrame:
    seed = mother[
        [
            "gap_id",
            "symbol",
            "first_return_date",
            "pristine_first_return_time",
            "L",
            "U",
            "W",
            "invalid_step_cum",
        ]
    ].copy()
    write_parquet(seed, ENTRY_DAY_SEED_2021)
    con = duckdb.connect()
    con.execute("SET threads=4")
    tmp = ENTRY_DAY_MINUTES_2021.with_suffix(".parquet.tmp")
    con.execute(
        f"""COPY (
          SELECT s.gap_id,s.symbol,s.first_return_date,
                 s.pristine_first_return_time,s.L,s.U,s.W,s.invalid_step_cum,
                 r.trade_date,r.bar_end_time,r.open,r.high,r.low,r.close,
                 r.volume,r.amount,d.cal_idx,d.coordinate_factor,
                 r.open*d.coordinate_factor AS coord_open,
                 r.high*d.coordinate_factor AS coord_high,
                 r.low*d.coordinate_factor AS coord_low,
                 r.close*d.coordinate_factor AS coord_close,
                 d.hard_valid,d.trade_status,d.current_day_data_tradable,
                 d.market_rule_valid,d.corporate_action_blocking,
                 d.up_limit_price,d.down_limit_price,
                 d.invalid_step_cum AS daily_invalid_step_cum
          FROM read_parquet('{ENTRY_DAY_SEED_2021}') s
          JOIN read_parquet('{raw_path(2021)}') r
            ON r.qmt_code=s.symbol AND r.trade_date=s.first_return_date
          JOIN read_parquet('{DAILY}') d
            ON d.symbol=s.symbol AND d.trade_date=r.trade_date
          WHERE r.period='1m' AND r.adjust='none'
          ORDER BY s.gap_id,r.bar_end_time
        ) TO '{tmp}' (FORMAT PARQUET,COMPRESSION ZSTD)"""
    )
    con.close()
    tmp.replace(ENTRY_DAY_MINUTES_2021)
    frame = pd.read_parquet(ENTRY_DAY_MINUTES_2021)
    frame.trade_date = pd.to_datetime(frame.trade_date)
    frame.bar_end_time = pd.to_datetime(frame.bar_end_time)
    counts = frame.groupby("gap_id").size()
    if len(counts) != len(mother) or not counts.eq(241).all():
        raise ResearchError("entry-day exact 241-minute failure")
    return frame


def configure_base_for_2021() -> None:
    base.DEV_END = CONFIRM_END
    base.ENTRY_FORMS = (ENTRY_FORM,)
    base.MIN_NET_HEADROOMS = (MINIMUM_NET_HEADROOM,)
    base.TIME_STOPS = (TIME_STOP,)
    base.EXIT_POLICIES = (EXIT_POLICY,)
    base.EXT = EXT
    base.DAILY = DAILY
    base.RAW_ROOT = RAW_ROOT
    base.LEGAL_OPENS = LEGAL_OPENS
    base.ACTION_EVENTS = ACTION_EVENTS
    base.ENTRY_CANDIDATES = ENTRIES_2021
    base.OUTCOME_BOUNDS = OUTCOME_BOUNDS_2021
    base.OUTCOME_MINUTES = OUTCOME_MINUTES_2021
    base.POLICY_OUTCOMES = OUTCOMES_2021


def run_stage_a() -> dict[str, Any]:
    validate_inputs()
    hashes = persist_contracts()
    daily = load_daily_through_2021()
    gaps = build_all_true_gaps_2021(daily)
    candidates = build_daily_candidates_2021(daily, gaps)
    build_pre_gap_days_2021(daily, candidates)
    vap_metrics, _profiles = build_vap_2021(candidates)
    broad, fixed = build_mothers_2021(candidates, vap_metrics)
    entry_minutes = build_entry_day_minutes_2021(fixed)
    configure_base_for_2021()
    entries = base.build_entry_candidates(fixed, entry_minutes)
    entries["entry_is_2022_or_later"] = (
        pd.to_datetime(entries.entry_date).gt(CONFIRM_END).fillna(False)
    )
    write_parquet(entries, ENTRIES_2021)
    funnel = {
        "all_true_gaps_2014_2021": len(gaps),
        "new_true_gaps_2021": int(gaps.gap_date.between(CONFIRM_START, CONFIRM_END).sum()),
        "width_ge_1pct": int(gaps.gap_width_pct.ge(MIN_GAP_WIDTH_PCT).sum()),
        "daily_exact_history": int(candidates.daily_history_complete.sum()),
        "pristine_raw_tick_return": int(candidates.first_post_gap_touch_is_pristine.sum()),
        "daily_vap_eligible_with_h10_room": int(
            candidates.stage_a_daily_disposition.eq("ELIGIBLE_FOR_MINUTE_VAP").sum()
        ),
        "exact_120x241_history": int(vap_metrics.exact_minute_history.sum()),
        "broad_low_inventory": len(broad),
        "fixed_clean_corridor_nonacute": len(fixed),
        "executable_entries": int(entries.entry_status.eq("EXECUTABLE_ENTRY").sum()),
    }
    freeze = {
        "experiment": EXPERIMENT,
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "all_gaps_sha256": sha256(ALL_GAPS_2021),
        "daily_candidates_sha256": sha256(DAILY_CANDIDATES_2021),
        "pre_gap_days_sha256": sha256(PRE_GAP_DAYS_2021),
        "vap_sha256": sha256(VAP_2021),
        "broad_mother_sha256": sha256(BROAD_MOTHER_2021),
        "fixed_mother_sha256": sha256(FIXED_MOTHER_2021),
        "entry_minutes_sha256": sha256(ENTRY_DAY_MINUTES_2021),
        "entries_sha256": sha256(ENTRIES_2021),
        "funnel": funnel,
        "entry_status": entries.entry_status.value_counts().astype(int).to_dict(),
        "outcome_columns_in_fixed_mother": [],
        "design_outcomes_opened_in_stage_a": "NO",
        "confirmation_outcomes_opened_in_stage_a": "NO",
        "data_2022_or_later_opened": "NO",
        "repository_2024_plus_data_opened": "NO",
    }
    write_json(FREEZE, freeze)
    manifest(
        "STAGE_A_FREEZE",
        {"status": "COMPLETE", "freeze_sha256": sha256(FREEZE), **freeze},
    )
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not FREEZE.is_file():
        raise ResearchError("Stage-A freeze missing")
    frozen = json.loads(FREEZE.read_text(encoding="utf-8"))
    hashes = persist_contracts()
    current = {
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "all_gaps_sha256": sha256(ALL_GAPS_2021),
        "daily_candidates_sha256": sha256(DAILY_CANDIDATES_2021),
        "pre_gap_days_sha256": sha256(PRE_GAP_DAYS_2021),
        "vap_sha256": sha256(VAP_2021),
        "broad_mother_sha256": sha256(BROAD_MOTHER_2021),
        "fixed_mother_sha256": sha256(FIXED_MOTHER_2021),
        "entry_minutes_sha256": sha256(ENTRY_DAY_MINUTES_2021),
        "entries_sha256": sha256(ENTRIES_2021),
    }
    drift = {
        key: [frozen.get(key), value] for key, value in current.items() if frozen.get(key) != value
    }
    fixed = pd.read_parquet(FIXED_MOTHER_2021)
    entries = pd.read_parquet(ENTRIES_2021)
    checks = {
        "fixed_gap_id_unique": not fixed.gap_id.duplicated().any(),
        "entry_key_unique": not entries.entry_key.duplicated().any(),
        "post_2021_entry_count": int(
            pd.to_datetime(entries.entry_date).gt(CONFIRM_END).fillna(False).sum()
        ),
        "future_entry_count": int(entries.entry_uses_future_bar.sum()),
        "fixed_rule_violation_count": int(
            (
                fixed.pre_gap_corridor_max_bin_density_relative_local.gt(
                    MAX_CORRIDOR_BIN_DENSITY_RELATIVE_LOCAL
                )
                | fixed.pre_peak_to_gap_sessions.lt(MIN_PEAK_TO_GAP_SESSIONS)
                | fixed.pre_gap_range_20d.gt(MAX_PRE_GAP_20D_RANGE)
            ).sum()
        ),
    }
    if (
        drift
        or any(value for key, value in checks.items() if key.endswith("_count"))
        or not checks["fixed_gap_id_unique"]
        or not checks["entry_key_unique"]
    ):
        raise ResearchError(f"Stage-A verification failed {drift=} {checks=}")
    value = {
        "verified": True,
        "hashes": current,
        "checks": checks,
        "2021_outcomes_opened": "NO",
    }
    manifest("STAGE_A_VERIFY", {"status": "COMPLETE", **value})
    return value


def development_corridor_max() -> pd.DataFrame:
    profile = pd.read_parquet(DESIGN_VAP)
    local = profile.groupby("gap_id", as_index=False).agg(
        local_mass_check=("pre_float_turnover_mass", "sum")
    )
    near = (
        profile.loc[profile.z_bin.between(-5, 14)]
        .groupby("gap_id", as_index=False)
        .pre_float_turnover_mass.max()
        .rename(columns={"pre_float_turnover_mass": "corridor_max_bin_mass"})
    )
    result = local.merge(near, on="gap_id", how="left")
    result["corridor_max_bin_mass"] = result.corridor_max_bin_mass.fillna(0.0)
    result["pre_gap_corridor_max_bin_density_relative_local"] = (
        50.0 * result.corridor_max_bin_mass / result.local_mass_check.replace(0, np.nan)
    )
    return result[["gap_id", "pre_gap_corridor_max_bin_density_relative_local"]]


def build_design_fixed_trades() -> pd.DataFrame:
    outcomes = pd.read_parquet(DESIGN_POLICY_OUTCOMES)
    for column in ("gap_date", "entry_date", "entry_time", "exit_date", "exit_time"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    outcomes = outcomes.merge(
        development_corridor_max(), on="gap_id", how="left", validate="many_to_one"
    )
    # The predecessor field is a high/low range despite its historical name.
    outcomes["pre_gap_range_20d"] = outcomes.pre_gap_max_runup_20d.astype(float)
    fixed = outcomes.loc[
        outcomes.outcome_valid
        & outcomes.entry_form.eq(ENTRY_FORM)
        & outcomes.minimum_net_headroom.eq(MINIMUM_NET_HEADROOM)
        & outcomes.time_stop.eq(TIME_STOP)
        & outcomes.exit_policy.eq(EXIT_POLICY)
        & outcomes.entry_date.dt.year.isin(DESIGN_PORTFOLIO_YEARS)
        & outcomes.pre_gap_corridor_max_bin_density_relative_local.le(
            MAX_CORRIDOR_BIN_DENSITY_RELATIVE_LOCAL
        )
        & outcomes.pre_peak_to_gap_sessions.ge(MIN_PEAK_TO_GAP_SESSIONS)
        & outcomes.pre_gap_range_20d.le(MAX_PRE_GAP_20D_RANGE)
    ].copy()
    fixed["sample"] = "DEVELOPMENT_DESIGN_ALREADY_CONSUMED"
    fixed["procedure"] = "FIXED_CLEAN_CORRIDOR"
    fixed = fixed.sort_values(["entry_time", "symbol", "gap_id"], kind="mergesort")
    if fixed.gap_id.duplicated().any():
        raise ResearchError("duplicate design fixed gap")
    write_parquet(fixed, DESIGN_FIXED_TRADES)
    return fixed


def build_outcome_minutes_2021(entries: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    executable = entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY")].copy()
    calendar = daily[["trade_date", "cal_idx"]].drop_duplicates("cal_idx").sort_values("cal_idx")
    date_by_idx = calendar.set_index("cal_idx").trade_date
    bounds = executable[["gap_id", "symbol", "entry_date", "entry_cal_idx"]].copy()
    bounds["path_end_cal_idx"] = bounds.entry_cal_idx.astype(int) + TIME_STOP + 1
    bounds["path_end_date"] = bounds.path_end_cal_idx.map(date_by_idx)
    if (
        bounds.path_end_date.isna().any()
        or pd.to_datetime(bounds.path_end_date).gt(CONFIRM_END).any()
    ):
        raise ResearchError("2021 outcome bounds failure")
    write_parquet(bounds, OUTCOME_BOUNDS_2021)
    tmp = OUTCOME_MINUTES_2021.with_suffix(".parquet.tmp")
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute(
        f"""COPY (
          SELECT b.gap_id,b.symbol,r.trade_date,r.bar_end_time,
                 r.open,r.high,r.low,r.close,r.volume,r.amount,
                 d.cal_idx,d.coordinate_factor,
                 r.open*d.coordinate_factor AS coord_open,
                 r.high*d.coordinate_factor AS coord_high,
                 r.low*d.coordinate_factor AS coord_low,
                 r.close*d.coordinate_factor AS coord_close,
                 d.invalid_step_cum,d.hard_valid,d.trade_status,
                 d.current_day_data_tradable,d.market_rule_valid,
                 d.corporate_action_blocking,d.up_limit_price,d.down_limit_price,
                 count(*) OVER(PARTITION BY b.gap_id,r.trade_date) AS minute_count
          FROM read_parquet('{OUTCOME_BOUNDS_2021}') b
          JOIN read_parquet('{raw_path(2021)}') r
            ON r.qmt_code=b.symbol
           AND r.trade_date BETWEEN b.entry_date AND b.path_end_date
          JOIN read_parquet('{DAILY}') d
            ON d.symbol=b.symbol AND d.trade_date=r.trade_date
          WHERE r.period='1m' AND r.adjust='none'
          ORDER BY b.gap_id,r.bar_end_time
        ) TO '{tmp}' (FORMAT PARQUET,COMPRESSION ZSTD)"""
    )
    con.close()
    tmp.replace(OUTCOME_MINUTES_2021)
    frame = pd.read_parquet(OUTCOME_MINUTES_2021)
    frame.trade_date = pd.to_datetime(frame.trade_date)
    frame.bar_end_time = pd.to_datetime(frame.bar_end_time)
    if frame.trade_date.gt(CONFIRM_END).any():
        raise ResearchError("post-2021 outcome minute opened")
    return frame


def build_confirmation_trades() -> pd.DataFrame:
    daily = load_daily_through_2021()
    entries = pd.read_parquet(ENTRIES_2021)
    for column in (
        "gap_date",
        "first_return_date",
        "pristine_first_return_time",
        "decision_time",
        "entry_time",
        "entry_date",
    ):
        entries[column] = pd.to_datetime(entries[column])
    outcome_minutes = build_outcome_minutes_2021(entries, daily)
    configure_base_for_2021()
    outcomes = base.build_policy_outcomes(entries, outcome_minutes, daily)
    fixed = outcomes.loc[
        outcomes.outcome_valid
        & outcomes.entry_form.eq(ENTRY_FORM)
        & outcomes.minimum_net_headroom.eq(MINIMUM_NET_HEADROOM)
        & outcomes.time_stop.eq(TIME_STOP)
        & outcomes.exit_policy.eq(EXIT_POLICY)
    ].copy()
    fixed["sample"] = "ONE_SHOT_2021_CONFIRMATION"
    fixed["procedure"] = "FIXED_CLEAN_CORRIDOR"
    fixed = fixed.sort_values(["entry_time", "symbol", "gap_id"], kind="mergesort")
    write_parquet(fixed, CONFIRMATION_TRADES)
    return fixed


def _cvar5(values: pd.Series) -> float | None:
    values = pd.to_numeric(values, errors="coerce").dropna().sort_values()
    if values.empty:
        return None
    return float(values.iloc[: max(1, math.ceil(len(values) * 0.05))].mean())


def trade_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {
            "signals": 0,
            "mean_net": None,
            "median_net": None,
            "win": None,
            "u_hit": None,
            "severe10": None,
            "cvar5": None,
            "mean_holding_sessions": None,
            "median_holding_sessions": None,
        }
    return {
        "signals": len(frame),
        "mean_net": float(frame.net_return.mean()),
        "median_net": float(frame.net_return.median()),
        "win": float(frame.net_return.gt(0).mean()),
        "u_hit": float(frame.u_hit.mean()),
        "severe10": float(frame.net_return.le(-0.10).mean()),
        "cvar5": _cvar5(frame.net_return),
        "mean_holding_sessions": float(frame.holding_sessions.mean()),
        "median_holding_sessions": float(frame.holding_sessions.median()),
    }


def replay_sample(
    trades: pd.DataFrame,
    daily: pd.DataFrame,
    years: tuple[int, ...],
    sample: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    summaries: list[dict[str, Any]] = []
    navs: list[pd.DataFrame] = []
    accepteds: list[pd.DataFrame] = []
    ledgers: list[pd.DataFrame] = []
    base.OUTER_YEARS = years
    for k in K_SENSITIVITY:
        base.K = k
        replays = {board: base.replay_board(trades, daily, board) for board in ("MAIN", "CHINEXT")}
        for board, replay in replays.items():
            accepted = replay.accepted.assign(sample=sample, k=k, board=board)
            metric = base.nav_metrics(replay.nav, accepted)
            summaries.append(
                {
                    "sample": sample,
                    "k": k,
                    "board": board,
                    "signals": int(trades.board.eq(board).sum()),
                    **metric,
                    "capacity_skips": int(replay.audit.get("capacity_skip_count", 0)),
                }
            )
            navs.append(replay.nav.assign(sample=sample, k=k))
            if len(accepted):
                accepteds.append(accepted)
            if len(replay.ledger):
                ledgers.append(replay.ledger.assign(sample=sample, k=k))
        combined = base.combine_nav(replays["MAIN"].nav, replays["CHINEXT"].nav)
        accepted = pd.concat(
            [
                replays["MAIN"].accepted.assign(sleeve_weight=0.5),
                replays["CHINEXT"].accepted.assign(sleeve_weight=0.5),
            ],
            ignore_index=True,
        )
        summaries.append(
            {
                "sample": sample,
                "k": k,
                "board": "COMBINED",
                "signals": len(trades),
                **base.nav_metrics(combined, accepted),
                "capacity_skips": sum(
                    int(value.audit.get("capacity_skip_count", 0)) for value in replays.values()
                ),
            }
        )
        navs.append(combined.assign(sample=sample, k=k))
    return (
        pd.DataFrame(summaries),
        pd.concat(navs, ignore_index=True),
        pd.concat(accepteds, ignore_index=True) if accepteds else pd.DataFrame(),
        pd.concat(ledgers, ignore_index=True) if ledgers else pd.DataFrame(),
    )


def run_stage_b() -> dict[str, Any]:
    verify_stage_a()
    design = build_design_fixed_trades()
    confirmation = build_confirmation_trades()
    design_daily = base.load_source_daily()
    confirmation_daily = load_daily_through_2021()
    design_bundle = replay_sample(
        design,
        design_daily,
        DESIGN_PORTFOLIO_YEARS,
        "DEVELOPMENT_DESIGN_ALREADY_CONSUMED",
    )
    confirmation_bundle = replay_sample(
        confirmation,
        confirmation_daily,
        CONFIRM_PORTFOLIO_YEARS,
        "ONE_SHOT_2021_CONFIRMATION",
    )
    summary = pd.concat([design_bundle[0], confirmation_bundle[0]], ignore_index=True)
    nav = pd.concat([design_bundle[1], confirmation_bundle[1]], ignore_index=True)
    accepted = pd.concat([design_bundle[2], confirmation_bundle[2]], ignore_index=True)
    ledger = pd.concat([design_bundle[3], confirmation_bundle[3]], ignore_index=True)
    write_parquet(summary, PORTFOLIO_SUMMARY)
    write_parquet(nav, PORTFOLIO_NAV)
    write_parquet(accepted, PORTFOLIO_ACCEPTED)
    write_parquet(ledger, PORTFOLIO_LEDGER)
    primary = summary.loc[
        summary["sample"].eq("ONE_SHOT_2021_CONFIRMATION")
        & summary.k.eq(PRIMARY_K)
        & summary.board.eq("COMBINED")
    ].iloc[0]
    gate = {
        "minimum_completed_trades": bool(primary.trades >= 15),
        "positive_mean": bool(primary.mean_net is not None and primary.mean_net > 0),
        "positive_median": bool(primary.median_net is not None and primary.median_net > 0),
        "positive_portfolio_return": bool(primary.total_return > 0),
        "positive_ex_best_day": bool(primary.return_excluding_best_day > 0),
        "severe10_controlled": bool(primary.severe10 is not None and primary.severe10 <= 0.05),
        "maxdd_controlled": bool(primary.max_drawdown > -0.10),
    }
    if all(gate.values()):
        verdict = "ONE_YEAR_CLEAN_CORRIDOR_EDGE_CONFIRMED"
    elif (
        primary.trades > 0
        and primary.mean_net is not None
        and primary.mean_net > 0
        and primary.total_return > 0
    ):
        verdict = "ONE_YEAR_CLEAN_CORRIDOR_EDGE_MIXED"
    else:
        verdict = "ONE_YEAR_CLEAN_CORRIDOR_EDGE_FAILED"
    audits = {
        "stage_a_hash_reproduced": True,
        "rule_changed_after_2021_outcome_open_count": 0,
        "threshold_changed_after_2021_outcome_open_count": 0,
        "entry_uses_future_bar_count": int(
            pd.read_parquet(ENTRIES_2021).entry_uses_future_bar.sum()
        ),
        "t1_violation_count": int(pd.read_parquet(OUTCOMES_2021).t1_violation.sum()),
        "impossible_exit_price_count": int(
            pd.read_parquet(OUTCOMES_2021).impossible_exit_price.sum()
        ),
        "data_2022_or_later_opened": "NO",
        "repository_2024_plus_data_opened": "NO",
    }
    if any(value for key, value in audits.items() if key.endswith("_count")):
        raise ResearchError(f"Stage-B audit failed {audits}")
    result = {
        "experiment": EXPERIMENT,
        "status": "STAGE_B_COMPLETE_CHARTS_PENDING",
        "verdict": verdict,
        "scientific_interpretation": (
            "2014-2020 is design evidence already consumed before this freeze; "
            "2021 is the sole one-shot previously unread outcome confirmation."
        ),
        "fixed_rule": contract_value()["fixed_simple_rule"],
        "design_trade_metrics": trade_metrics(design),
        "confirmation_trade_metrics": trade_metrics(confirmation),
        "portfolio": {},
        "validation_gate": gate,
        "audit": audits,
        "hashes": {
            "contract": sha256(CONTRACT),
            "spec": sha256(SPEC),
            "stage_a_freeze": sha256(FREEZE),
            "design_fixed_trades": sha256(DESIGN_FIXED_TRADES),
            "confirmation_trades": sha256(CONFIRMATION_TRADES),
            "confirmation_outcomes": sha256(OUTCOMES_2021),
            "portfolio_summary": sha256(PORTFOLIO_SUMMARY),
            "portfolio_nav": sha256(PORTFOLIO_NAV),
        },
    }
    # Build the nested portfolio dictionary explicitly for JSON clarity.
    result["portfolio"] = {}
    for sample, sample_part in summary.groupby("sample", sort=True):
        result["portfolio"][sample] = {}
        for k, k_part in sample_part.groupby("k", sort=True):
            result["portfolio"][sample][f"K{int(k)}"] = {}
            for board, row in k_part.groupby("board", sort=True):
                result["portfolio"][sample][f"K{int(k)}"][board] = (
                    row.iloc[0].drop(labels=["sample", "k", "board"]).to_dict()
                )
    write_json(RESULT, result)
    manifest(
        "STAGE_B_COMPLETE",
        {
            "status": "COMPLETE",
            "result_sha256": sha256(RESULT),
            "verdict": verdict,
            **audits,
        },
    )
    return result


def _daily_for_charts() -> pd.DataFrame:
    return load_daily_through_2021()


def _candles(ax: plt.Axes, frame: pd.DataFrame) -> None:
    dates = mdates.date2num(pd.to_datetime(frame.trade_date).to_numpy())
    for x, row in zip(dates, frame.itertuples(index=False), strict=True):
        color = "#d62728" if row.coord_close >= row.coord_open else "#008b72"
        ax.vlines(x, row.coord_low, row.coord_high, color=color, linewidth=0.65)
        lower = min(row.coord_open, row.coord_close)
        height = max(abs(row.coord_close - row.coord_open), 1e-6)
        ax.add_patch(
            plt.Rectangle(
                (x - 0.28, lower),
                0.56,
                height,
                facecolor=color,
                edgecolor=color,
                linewidth=0.4,
            )
        )
    ax.xaxis_date()
    ax.grid(alpha=0.16)


def _chart_profiles() -> pd.DataFrame:
    development = pd.read_parquet(DESIGN_VAP)
    confirmation = pd.read_parquet(VAP_2021)
    return pd.concat([development, confirmation], ignore_index=True)


def render_charts() -> dict[str, Any]:
    if not RESULT.is_file():
        raise ResearchError("Stage B result missing")
    design = pd.read_parquet(DESIGN_FIXED_TRADES)
    confirmation = pd.read_parquet(CONFIRMATION_TRADES)
    sample = pd.concat([design, confirmation], ignore_index=True)
    sample = sample.sort_values(
        ["sample", "entry_time", "symbol", "gap_id"], kind="mergesort"
    ).reset_index(drop=True)
    sample["chart_id"] = [f"CLEAN-{index:04d}" for index in range(1, len(sample) + 1)]
    daily = _daily_for_charts()
    groups = {
        symbol: part.reset_index(drop=True) for symbol, part in daily.groupby("symbol", sort=False)
    }
    profiles = _chart_profiles()
    profile_by = {
        key: part.sort_values("z_bin") for key, part in profiles.groupby("gap_id", sort=False)
    }
    accepted = pd.read_parquet(PORTFOLIO_ACCEPTED)
    accepted_primary = set(
        accepted.loc[accepted.k.eq(PRIMARY_K), ["sample", "gap_id"]]
        .astype(str)
        .itertuples(index=False, name=None)
    )
    PDF.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "Title": f"{EXPERIMENT} all fixed-rule signal charts",
        "Author": "CY Market Behavior OS",
        "Subject": "Design reconstruction and one-shot 2021 confirmation",
        "CreationDate": pd.Timestamp("2000-01-01").to_pydatetime(),
        "ModDate": pd.Timestamp("2000-01-01").to_pydatetime(),
    }
    with PdfPages(PDF, metadata=metadata) as pdf:
        fig = plt.figure(figsize=(15.5, 8.69))
        fig.patch.set_facecolor("white")
        fig.text(
            0.06, 0.88, "Clean-corridor true-gap simple-profit review", fontsize=24, weight="bold"
        )
        fig.text(
            0.06,
            0.80,
            f"{len(design)} consumed-design signals + "
            f"{len(confirmation)} one-shot 2021 confirmation signals",
            fontsize=14,
        )
        fig.text(
            0.06, 0.70, "Fixed before 2021 outcomes", fontsize=13, weight="bold", color="#9a3412"
        )
        rules = [
            "1. Broad low-inventory true gap with exact raw-fen first return",
            "2. Maximum 0.10W corridor-bin density <= 2.5x local average",
            "3. Prior 120-session peak at least 60 sessions before gap",
            "4. Pre-gap 20-session high-low range <= 20%",
            "5. First close >= L; next legal minute open with >=1.5% net U headroom",
            "6. U target; X1 next-open failure; H10; T+1; 40 bp round trip",
            "7. K2 per 50/50 Main/ChiNext sleeve; no leverage",
        ]
        fig.text(0.08, 0.60, "\n".join(rules), fontsize=12.5, linespacing=1.55, va="top")
        fig.text(
            0.06,
            0.08,
            "2022 and later were not opened. Design pages are not new OOF evidence.",
            fontsize=11,
        )
        pdf.savefig(fig)
        plt.close(fig)
        for event in sample.itertuples(index=False):
            part = groups[str(event.symbol)]
            gap_rows = part.index[part.trade_date.eq(pd.Timestamp(event.gap_date))]
            exit_rows = part.index[part.trade_date.eq(pd.Timestamp(event.exit_date))]
            if not len(gap_rows) or not len(exit_rows):
                raise ResearchError(f"chart path missing {event.gap_id}")
            start = max(0, int(gap_rows[0]) - PRE_GAP_SESSIONS)
            end = min(len(part), int(exit_rows[0]) + 21)
            view = part.iloc[start:end].copy()
            local = part.loc[
                part.trade_date.between(
                    pd.Timestamp(event.first_return_date) - pd.Timedelta(days=35),
                    pd.Timestamp(event.exit_date) + pd.Timedelta(days=20),
                )
            ].copy()
            profile = profile_by.get(str(event.gap_id), profiles.iloc[0:0])
            fig = plt.figure(figsize=(15.5, 8.69))
            grid = fig.add_gridspec(
                2, 4, height_ratios=[1.1, 1], width_ratios=[2, 2, 2, 1], hspace=0.32, wspace=0.28
            )
            ax_full = fig.add_subplot(grid[0, :3])
            ax_vap = fig.add_subplot(grid[0, 3])
            ax_local = fig.add_subplot(grid[1, :])
            _candles(ax_full, view)
            _candles(ax_local, local)
            for ax in (ax_full, ax_local):
                ax.axhspan(float(event.L), float(event.U), color="#f59e0b", alpha=0.22)
                ax.axhline(float(event.L), color="#d97706", linestyle="--", linewidth=0.9)
                ax.axhline(float(event.U), color="#b45309", linestyle="--", linewidth=0.9)
                ax.axvline(
                    pd.Timestamp(event.gap_date), color="#ef4444", linestyle=":", linewidth=1.0
                )
                ax.tick_params(axis="x", labelrotation=20, labelsize=7.5)
            ax_local.scatter(
                pd.Timestamp(event.entry_date),
                float(event.entry_coordinate_price),
                marker="^",
                s=78,
                color="#1d4ed8",
                edgecolor="white",
                linewidth=0.7,
                zorder=8,
                label="BUY",
            )
            exit_day = part.loc[part.trade_date.eq(pd.Timestamp(event.exit_date))]
            exit_y = float(exit_day.coord_open.iloc[0])
            if str(event.exit_reason) == "U_TARGET":
                exit_y = max(exit_y, float(event.U))
            ax_local.scatter(
                pd.Timestamp(event.exit_date),
                exit_y,
                marker="v",
                s=78,
                color="#7e22ce",
                edgecolor="white",
                linewidth=0.7,
                zorder=8,
                label="SELL",
            )
            ax_local.legend(loc="upper left", fontsize=8, ncol=2, framealpha=0.85)
            if len(profile):
                z_mid = (profile.z_bin.astype(float) + 0.5) * 0.10
                ax_vap.barh(
                    z_mid,
                    profile.pre_float_turnover_mass,
                    height=0.085,
                    color="#4c78a8",
                    alpha=0.75,
                )
                ax_vap.axhspan(-0.5, 1.5, color="#f6bd60", alpha=0.20)
                ax_vap.axhspan(0, 1, color="#ef4444", alpha=0.10)
                ax_vap.axhline(0, color="#d97706", linestyle="--", linewidth=0.8)
                ax_vap.axhline(1, color="#b45309", linestyle="--", linewidth=0.8)
            ax_vap.set_title("Pre-gap 120-session VAP\nz=(price-L)/W", fontsize=9)
            ax_vap.grid(alpha=0.15)
            portfolio_status = (
                "K2 EXECUTED"
                if (str(event.sample), str(event.gap_id)) in accepted_primary
                else "K2 CAPACITY SKIP"
            )
            fig.suptitle(
                f"{event.chart_id} | {event.symbol} | {event.board} | {event.sample}",
                x=0.055,
                ha="left",
                fontsize=15,
                weight="bold",
            )
            fig.text(
                0.055,
                0.925,
                f"Gap {pd.Timestamp(event.gap_date).date()}  "
                f"[L={event.L:.4f}, U={event.U:.4f}] | "
                f"return {pd.Timestamp(event.first_return_date).date()} | "
                f"buy {pd.Timestamp(event.entry_time)} | "
                f"sell {pd.Timestamp(event.exit_time)}",
                fontsize=9.2,
            )
            fig.text(
                0.055,
                0.895,
                f"Net {event.net_return:+.2%} | exit {event.exit_reason} | "
                f"hold {int(event.holding_sessions)} sessions | {portfolio_status}",
                fontsize=10.5,
                color="#b91c1c" if event.net_return < 0 else "#166534",
                weight="bold",
            )
            fig.text(
                0.055,
                0.052,
                "Corridor max-bin/local "
                f"{event.pre_gap_corridor_max_bin_density_relative_local:.2f}x "
                "<=2.50x | "
                f"peak-to-gap {int(event.pre_peak_to_gap_sessions)} >=60 | "
                f"pre-gap 20D range {event.pre_gap_range_20d:.2%} <=20%",
                fontsize=9,
            )
            fig.text(
                0.055,
                0.026,
                f"Entry net U headroom {event.realized_net_target_at_entry:.2%} "
                ">=1.50% | Blue BUY / purple SELL / orange true gap | 40 bp cost",
                fontsize=9,
            )
            pdf.savefig(fig)
            plt.close(fig)
    sample.to_csv(CHART_INDEX, index=False)
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    result["charts"] = {
        "signals": len(sample),
        "design_signals": len(design),
        "confirmation_signals": len(confirmation),
        "pages": len(sample) + 1,
        "pdf": str(PDF),
        "pdf_sha256": sha256(PDF),
        "chart_index_sha256": sha256(CHART_INDEX),
    }
    result["status"] = "COMPLETE"
    result["hashes"]["pdf"] = sha256(PDF)
    result["hashes"]["chart_index"] = sha256(CHART_INDEX)
    write_json(RESULT, result)
    return result["charts"]


def finalize_report() -> dict[str, Any]:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    design = result["portfolio"]["DEVELOPMENT_DESIGN_ALREADY_CONSUMED"][f"K{PRIMARY_K}"]["COMBINED"]
    confirm = result["portfolio"]["ONE_SHOT_2021_CONFIRMATION"][f"K{PRIMARY_K}"]["COMBINED"]
    design_row = (
        f"|Consumed 2017-2020 design|{design['signals']}|{design['trades']}|"
        f"{design['mean_net']:.2%}|{design['median_net']:.2%}|{design['win']:.2%}|"
        f"{design['u_hit']:.2%}|{design['total_return']:.2%}|"
        f"{design['max_drawdown']:.2%}|{design['sharpe']:.3f}|"
        f"{design['return_excluding_best_day']:.2%}|"
    )
    confirm_values = {
        key: confirm[key] if confirm[key] is not None else float("nan")
        for key in ("mean_net", "median_net", "win", "u_hit")
    }
    confirmation_row = (
        f"|One-shot 2021|{confirm['signals']}|{confirm['trades']}|"
        f"{confirm_values['mean_net']:.2%}|{confirm_values['median_net']:.2%}|"
        f"{confirm_values['win']:.2%}|{confirm_values['u_hit']:.2%}|"
        f"{confirm['total_return']:.2%}|{confirm['max_drawdown']:.2%}|"
        f"{confirm['sharpe']:.3f}|{confirm['return_excluding_best_day']:.2%}|"
    )
    lines = [
        f"# {EXPERIMENT}",
        "",
        "## Verdict",
        "",
        f"`{result['verdict']}`",
        "",
        "The rule was designed after 2014-2020 outcomes were already consumed and "
        "was frozen before one-shot 2021 outcome access. The design years are not "
        "relabeled as new OOF evidence.",
        "",
        "## Fixed simple rule",
        "",
        "1. Direct raw-tick true gap with broad low mean inventory.",
        "2. Maximum 0.10W corridor-bin density <=2.5x local average.",
        "3. 120-session reference peak at least 60 sessions before the gap.",
        "4. Pre-gap 20-session high-low range <=20%.",
        "5. E1 next-minute entry with >=1.5% net U headroom; U/X1/H10; T+1; 40 bp.",
        "",
        "## Primary K2 portfolio",
        "",
        "|Sample|Signals|Trades|Mean|Median|Win|U hit|Return|MaxDD|Sharpe|Ex best day|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        design_row,
        confirmation_row,
        "",
        "## Audit",
        "",
        f"`{json.dumps(result['audit'], sort_keys=True)}`",
        "",
        f"Chart book: {result.get('charts', {}).get('pages', 0)} pages covering "
        "every fixed-rule signal.",
        "",
        "No 2022+ or repository 2024+ row was opened.",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result["hashes"]["report"] = sha256(REPORT)
    write_json(RESULT, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage",
        choices=("stage-a", "verify-stage-a", "stage-b", "charts", "finalize"),
    )
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
        value = finalize_report()
    print(canonical_json(value))


if __name__ == "__main__":
    main()
