#!/usr/bin/env python3
"""Build and render the frozen upward-gap rejection/reacceptance mother."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

import run_ashare_panic_absorption_12m_chart_rule_discovery_v1 as charts


EXPERIMENT = "ASHARE-UPWARD-INFORMATION-GAP-REJECTION-REACCEPTANCE-12M-CHART-DISCOVERY-V1"
REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
EXPECTED_FREEZE_SHA256 = "ddbab569d84e978f6606545729983b0015be691eaaee48fd1fa3779c910f2fd0"
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
DAILY = (
    DATA_ROOT
    / "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1"
    / "pit_daily_compact_2013_2023.parquet"
)
REGIME = (
    DATA_ROOT
    / "ashare_causal_market_regime_routed_simple_strategy_v1"
    / "stage_a/causal_market_regime_2014_2023.parquet"
)
EXPECTED_DAILY_SHA256 = "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00"
EXPECTED_REGIME_SHA256 = "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a"

OUTPUT_ROOT = DATA_ROOT / "ashare_upward_information_gap_rejection_reacceptance_chart_discovery_v1"
CANDIDATES = OUTPUT_ROOT / "stage_a/frozen_candidates.parquet"
PATHS = OUTPUT_ROOT / "stage_a/candidate_paths.parquet"
STAGE_A = OUTPUT_ROOT / "stage_a/freeze.json"
OUTCOMES = OUTPUT_ROOT / "stage_b/baseline_outcomes.parquet"
WINDOWS = OUTPUT_ROOT / "stage_b/chart_window_panel.parquet"
LEDGER = OUTPUT_ROOT / "stage_b/review_ledger.parquet"
LEDGER_CSV = OUTPUT_ROOT / "stage_b/review_ledger.csv"
CHART_DIR = OUTPUT_ROOT / "stage_b/individual_charts"
CHART_INDEX = OUTPUT_ROOT / "stage_b/chart_index.csv"
SHEET_DIR = OUTPUT_ROOT / "stage_b/review_sheets"
RESULT = OUTPUT_ROOT / "stage_b/result.json"

SIGNAL_START = pd.Timestamp("2014-01-01")
SIGNAL_END = pd.Timestamp("2020-12-31")
SOURCE_END = pd.Timestamp("2021-12-31")
MIN_GAP_WIDTH = 0.01
REJECTION_HORIZON = 60
REACCEPTANCE_HORIZON = 60
COOLDOWN = 40
PRE = 126
POST = 126
TARGET_FRACTION = 0.67
MIN_NET_HEADROOM = 0.04
HORIZON = 60
COST = 0.004


class ResearchError(RuntimeError):
    """Fail closed on source, chronology, lineage, or execution drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.register("frame", frame)
    connection.execute(
        f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    connection.close()


def verify_sources() -> dict[str, str]:
    expected = {
        "freeze": (FREEZE, EXPECTED_FREEZE_SHA256),
        "daily": (DAILY, EXPECTED_DAILY_SHA256),
        "regime": (REGIME, EXPECTED_REGIME_SHA256),
    }
    actual: dict[str, str] = {}
    for name, (path, digest) in expected.items():
        if not path.is_file():
            raise ResearchError(f"missing required source: {path}")
        actual[name] = sha256(path)
        if actual[name] != digest:
            raise ResearchError(f"{name} identity drift: {actual[name]} != {digest}")
    return actual


def valid_row(row: Any) -> bool:
    required = (
        row.trade_status,
        row.current_day_data_tradable,
        row.current_valid,
        row.hard_valid,
        row.market_rule_valid,
        row.corporate_action_valid,
        row.corporate_action_blocking,
        row.is_st,
    )
    if any(pd.isna(value) for value in required):
        return False
    prices = (row.coord_open, row.coord_high, row.coord_low, row.coord_close)
    return bool(
        int(row.trade_status) == 1
        and row.current_day_data_tradable
        and row.current_valid
        and row.hard_valid
        and row.market_rule_valid
        and row.corporate_action_valid
        and not row.corporate_action_blocking
        and not row.is_st
        and all(np.isfinite(float(value)) and float(value) > 0 for value in prices)
    )


def buyable_open(row: Any) -> bool:
    return bool(
        valid_row(row)
        and np.isfinite(float(row.open))
        and np.isfinite(float(row.up_limit_price))
        and round(float(row.open) * 100) < round(float(row.up_limit_price) * 100)
    )


def sellable_open(row: Any) -> bool:
    return bool(
        valid_row(row)
        and np.isfinite(float(row.open))
        and np.isfinite(float(row.down_limit_price))
        and round(float(row.open) * 100) > round(float(row.down_limit_price) * 100)
    )


def load_gap_paths() -> pd.DataFrame:
    connection = duckdb.connect()
    connection.execute("PRAGMA threads=4")
    connection.execute("PRAGMA memory_limit='8GB'")
    paths = connection.execute(
        f"""
        WITH base AS (
          SELECT trade_date,cal_idx,symbol,sleeve,open,high,low,close,
            coord_open,coord_high,coord_low,coord_close,turnover_fraction,is_st,
            trade_status,current_day_data_tradable,up_limit_price,down_limit_price,
            market_rule_valid,corporate_action_valid,corporate_action_blocking,
            hard_valid,current_valid,available_at,decision_at,invalid_step_cum,
            coordinate_factor,
            lag(trade_date) OVER w AS prev_trade_date,
            lag(cal_idx) OVER w AS prev_cal_idx,
            lag(high) OVER w AS prev_high,
            lag(coord_high) OVER w AS prev_coord_high,
            lag(invalid_step_cum) OVER w AS prev_invalid_step_cum
          FROM read_parquet('{DAILY.as_posix()}')
          WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2021-12-31'
          WINDOW w AS (PARTITION BY symbol ORDER BY cal_idx)
        ), gaps AS (
          SELECT *,
            prev_coord_high AS gap_L,
            coord_low AS gap_U,
            coord_low/prev_coord_high-1 AS gap_width,
            symbol || '|' || strftime(trade_date,'%Y%m%d') AS gap_id
          FROM base
          WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2020-12-31'
            AND sleeve IN ('MAIN','CHINEXT')
            AND cal_idx=prev_cal_idx+1
            AND round(low*100)>round(prev_high*100)
            AND invalid_step_cum=prev_invalid_step_cum
            AND coord_low/prev_coord_high-1>={MIN_GAP_WIDTH}
            AND trade_status=1 AND current_day_data_tradable
            AND current_valid AND hard_valid AND market_rule_valid
            AND corporate_action_valid AND NOT corporate_action_blocking AND NOT is_st
            AND round(close*100)<round(up_limit_price*100)
        )
        SELECT g.gap_id,g.trade_date AS gap_date,g.cal_idx AS gap_cal_idx,
          g.symbol,g.sleeve,g.gap_L,g.gap_U,g.gap_width,
          g.invalid_step_cum AS gap_invalid_step_cum,
          d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.turnover_fraction,
          d.is_st,d.trade_status,d.current_day_data_tradable,d.up_limit_price,
          d.down_limit_price,d.market_rule_valid,d.corporate_action_valid,
          d.corporate_action_blocking,d.hard_valid,d.current_valid,
          d.available_at,d.decision_at,d.invalid_step_cum,d.coordinate_factor
        FROM gaps g
        JOIN read_parquet('{DAILY.as_posix()}') d
          ON g.symbol=d.symbol
         AND d.cal_idx BETWEEN g.cal_idx AND g.cal_idx+{REJECTION_HORIZON + REACCEPTANCE_HORIZON}
        ORDER BY g.gap_id,d.cal_idx
        """
    ).fetch_df()
    connection.close()
    for column in ("gap_date", "trade_date", "available_at", "decision_at"):
        paths[column] = pd.to_datetime(paths[column])
    if paths.empty:
        raise ResearchError("no strict upward-gap path was found")
    if paths.available_at.dt.date.gt(paths.trade_date.dt.date).any():
        raise ResearchError("a daily row was unavailable on its own trade date")
    return paths


def candidate_from_gap(path: pd.DataFrame) -> dict[str, Any] | None:
    path = path.sort_values("cal_idx", kind="mergesort").reset_index(drop=True)
    gap = path.iloc[0]
    lineage = float(gap.gap_invalid_step_cum)
    gap_idx = int(gap.gap_cal_idx)
    gap_l = float(gap.gap_L)
    gap_u = float(gap.gap_U)
    pre_rejection_peak = float(gap.coord_high)
    rejection: Any | None = None
    prior_valid: Any | None = gap
    for row in path.iloc[1:].itertuples(index=False):
        if int(row.cal_idx) > gap_idx + REJECTION_HORIZON:
            break
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != lineage:
            return None
        if not valid_row(row):
            continue
        if float(row.coord_close) < gap_l:
            rejection = row
            break
        pre_rejection_peak = max(pre_rejection_peak, float(row.coord_high))
        prior_valid = row
    if rejection is None or prior_valid is None:
        return None

    rejection_idx = int(rejection.cal_idx)
    previous_valid = rejection
    acceptance: Any | None = None
    for row in path.loc[path.cal_idx.gt(rejection_idx)].itertuples(index=False):
        if int(row.cal_idx) > rejection_idx + REACCEPTANCE_HORIZON:
            break
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != lineage:
            return None
        if not valid_row(row):
            continue
        daily_range = float(row.coord_high) - float(row.coord_low)
        close_location = (
            1.0
            if daily_range <= 0
            else (float(row.coord_close) - float(row.coord_low)) / daily_range
        )
        if (
            float(row.coord_close) > gap_u
            and float(row.coord_close) > float(previous_valid.coord_high)
            and close_location >= 0.60
            and round(float(row.close) * 100) < round(float(row.up_limit_price) * 100)
        ):
            acceptance = row
            break
        previous_valid = row
    if acceptance is None:
        return None
    signal_date = pd.Timestamp(acceptance.trade_date)
    if signal_date < SIGNAL_START or signal_date > SIGNAL_END:
        return None
    signal_range = float(acceptance.coord_high) - float(acceptance.coord_low)
    return {
        "gap_id": str(gap.gap_id),
        "symbol": str(gap.symbol),
        "sleeve": str(gap.sleeve),
        "gap_date": pd.Timestamp(gap.gap_date),
        "gap_cal_idx": gap_idx,
        "gap_L": gap_l,
        "gap_U": gap_u,
        "gap_width": float(gap.gap_width),
        "lineage": lineage,
        "rejection_date": pd.Timestamp(rejection.trade_date),
        "rejection_cal_idx": rejection_idx,
        "rejection_close": float(rejection.coord_close),
        "pre_rejection_peak_P": pre_rejection_peak,
        "peak_headroom_from_U": pre_rejection_peak / gap_u - 1.0,
        "gap_to_rejection_sessions": rejection_idx - gap_idx,
        "signal_date": signal_date,
        "signal_cal_idx": int(acceptance.cal_idx),
        "rejection_to_signal_sessions": int(acceptance.cal_idx) - rejection_idx,
        "signal_coord_open": float(acceptance.coord_open),
        "signal_coord_high": float(acceptance.coord_high),
        "signal_coord_low": float(acceptance.coord_low),
        "signal_coord_close": float(acceptance.coord_close),
        "signal_close_location": 1.0 if signal_range <= 0 else (
            float(acceptance.coord_close) - float(acceptance.coord_low)
        ) / signal_range,
        "signal_step_return": float(acceptance.coord_close) / float(previous_valid.coord_close) - 1.0,
        "signal_turnover_fraction": float(acceptance.turnover_fraction),
        "available_at": pd.Timestamp(acceptance.available_at),
        "decision_at": pd.Timestamp(acceptance.decision_at),
    }


def deduplicate(candidates: pd.DataFrame) -> pd.DataFrame:
    candidates = candidates.sort_values(
        ["signal_date", "symbol", "gap_date"],
        ascending=[True, True, False],
        kind="mergesort",
    ).drop_duplicates(["symbol", "signal_date"], keep="first")
    retained: list[int] = []
    for _, part in candidates.groupby("symbol", sort=False):
        last_idx = -10**9
        for index, row in part.sort_values("signal_cal_idx", kind="mergesort").iterrows():
            if int(row.signal_cal_idx) > last_idx + COOLDOWN:
                retained.append(index)
                last_idx = int(row.signal_cal_idx)
    result = candidates.loc[retained].copy()
    result["event_id"] = result.apply(
        lambda row: f"{row.symbol}|{pd.Timestamp(row.signal_date):%Y%m%d}|UIGRR1",
        axis=1,
    )
    result["signal_time"] = pd.to_datetime(result.signal_date) + pd.Timedelta(hours=15)
    return result.sort_values(
        ["signal_date", "sleeve", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)


def run_stage_a() -> dict[str, Any]:
    source_hashes = verify_sources()
    gap_paths = load_gap_paths()
    rows = []
    for _, path in gap_paths.groupby("gap_id", sort=False):
        candidate = candidate_from_gap(path)
        if candidate is not None:
            rows.append(candidate)
    if not rows:
        raise ResearchError("mother structure produced no candidate")
    candidates = deduplicate(pd.DataFrame(rows))
    connection = duckdb.connect()
    connection.register("candidates", candidates)
    candidates = connection.execute(
        f"""
        SELECT c.*,r.market_regime,r.market_median_ret20,r.market_positive_ret20_share,
          r.market_median_ret60,r.market_positive_ret60_share,
          r.latest_source_timestamp AS market_latest_source_timestamp
        FROM candidates c
        LEFT JOIN read_parquet('{REGIME.as_posix()}') r
          ON c.signal_date=r.trade_date
        ORDER BY c.signal_date,c.sleeve,c.symbol,c.event_id
        """
    ).fetch_df()
    connection.close()
    for column in (
        "gap_date",
        "rejection_date",
        "signal_date",
        "signal_time",
        "available_at",
        "decision_at",
        "market_latest_source_timestamp",
    ):
        candidates[column] = pd.to_datetime(candidates[column])
    if candidates.event_id.duplicated().any():
        raise ResearchError("duplicate retained event identity")
    if candidates.available_at.gt(candidates.decision_at).any():
        raise ResearchError("signal feature is unavailable at decision_at")
    if candidates.market_regime.isna().any():
        raise ResearchError("missing causal market state")
    if candidates.market_latest_source_timestamp.gt(candidates.signal_time).any():
        raise ResearchError("market state uses information after signal")
    if not candidates.market_regime.isin(["BULL", "BEAR", "TRANSITION"]).all():
        raise ResearchError("unknown causal market state")
    write_parquet(candidates, CANDIDATES)
    write_parquet(gap_paths, PATHS)
    annual = candidates.groupby(candidates.signal_date.dt.year).size().astype(int).to_dict()
    freeze = {
        "experiment": EXPERIMENT,
        "scientific_status": "OUTCOME_BLIND_CANDIDATE_IDENTITY_FROZEN",
        "source_hashes": source_hashes,
        "gap_paths": int(len(gap_paths)),
        "raw_gap_count": int(gap_paths.gap_id.nunique()),
        "candidate_count": int(len(candidates)),
        "security_count": int(candidates.symbol.nunique()),
        "decision_date_count": int(candidates.signal_date.nunique()),
        "annual_signal_counts": {str(key): value for key, value in annual.items()},
        "signal_count_gate_each_year_gt_50": bool(
            set(annual) == set(range(2014, 2021)) and min(annual.values()) > 50
        ),
        "market_state_after_signal_count": int(
            candidates.market_latest_source_timestamp.gt(candidates.signal_time).sum()
        ),
        "max_signal_date": str(candidates.signal_date.max().date()),
        "post_signal_outcome_or_chart_read": False,
        "2022_2024_read": False,
        "candidate_sha256": sha256(CANDIDATES),
        "path_sha256": sha256(PATHS),
    }
    write_json(STAGE_A, freeze)
    return freeze


def replay_one(candidate: Any, daily: pd.DataFrame) -> dict[str, Any]:
    base = {
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_year": int(pd.Timestamp(candidate.signal_date).year),
        "signal_cal_idx": int(candidate.signal_cal_idx),
        "market_regime": str(candidate.market_regime),
        "gap_L": float(candidate.gap_L),
        "gap_U": float(candidate.gap_U),
        "pre_rejection_peak_P": float(candidate.pre_rejection_peak_P),
    }
    lineage = float(candidate.lineage)
    signal_idx = int(candidate.signal_cal_idx)
    path = daily.loc[daily.cal_idx.gt(signal_idx)].copy()
    entry = next(
        (
            row
            for row in path.loc[path.cal_idx.le(signal_idx + 3)].itertuples(index=False)
            if np.isfinite(float(row.invalid_step_cum))
            and float(row.invalid_step_cum) == lineage
            and buyable_open(row)
        ),
        None,
    )
    if entry is None:
        return {**base, "status": "NO_LEGAL_ENTRY"}
    entry_price = float(entry.coord_open)
    target = entry_price + TARGET_FRACTION * (
        float(candidate.pre_rejection_peak_P) - entry_price
    )
    net_target_headroom = target / entry_price - 1.0 - COST
    entry_payload = {
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": int(entry.cal_idx),
        "entry_price": entry_price,
        "target_price": target,
        "net_target_headroom": net_target_headroom,
    }
    if not target > entry_price or not target < float(candidate.pre_rejection_peak_P):
        return {**base, **entry_payload, "status": "NO_POSITIVE_STRUCTURAL_TARGET"}
    if net_target_headroom < MIN_NET_HEADROOM:
        return {**base, **entry_payload, "status": "INSUFFICIENT_TARGET_HEADROOM"}

    pending_time = False
    entry_idx = int(entry.cal_idx)
    for row in path.loc[path.cal_idx.gt(entry_idx)].itertuples(index=False):
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != lineage:
            return {**base, **entry_payload, "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY"}
        if pending_time and sellable_open(row):
            gross = float(row.coord_open) / entry_price - 1.0
            return {
                **base,
                **entry_payload,
                "status": "COMPLETED",
                "exit_date": pd.Timestamp(row.trade_date),
                "exit_cal_idx": int(row.cal_idx),
                "exit_price": float(row.coord_open),
                "exit_reason": "H60_TIME_STOP",
                "holding_sessions": int(row.cal_idx) - entry_idx,
                "gross_return": gross,
                "net_return": gross - COST,
            }
        if valid_row(row) and float(row.coord_high) >= target:
            gross = target / entry_price - 1.0
            return {
                **base,
                **entry_payload,
                "status": "COMPLETED",
                "exit_date": pd.Timestamp(row.trade_date),
                "exit_cal_idx": int(row.cal_idx),
                "exit_price": target,
                "exit_reason": "A67_PRE_REJECTION_PEAK",
                "holding_sessions": int(row.cal_idx) - entry_idx,
                "gross_return": gross,
                "net_return": gross - COST,
            }
        if valid_row(row) and int(row.cal_idx) >= entry_idx + HORIZON:
            pending_time = True
    return {**base, **entry_payload, "status": "INCOMPLETE_BY_2021_END"}


def load_stage_b_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not STAGE_A.is_file():
        raise ResearchError("stage A must be frozen before outcome access")
    stage_a = json.loads(STAGE_A.read_text(encoding="utf-8"))
    if stage_a.get("post_signal_outcome_or_chart_read") is not False:
        raise ResearchError("invalid Stage-A outcome governance")
    if sha256(CANDIDATES) != stage_a.get("candidate_sha256"):
        raise ResearchError("candidate freeze drift")
    connection = duckdb.connect()
    candidates = connection.execute(
        f"SELECT * FROM read_parquet('{CANDIDATES.as_posix()}') ORDER BY signal_date,symbol,event_id"
    ).fetch_df()
    connection.register(
        "events",
        candidates[["event_id", "symbol", "signal_cal_idx"]],
    )
    daily = connection.execute(
        f"""
        SELECT e.event_id,d.*
        FROM events e
        JOIN read_parquet('{DAILY.as_posix()}') d
          ON e.symbol=d.symbol
         AND d.cal_idx BETWEEN e.signal_cal_idx-{PRE} AND e.signal_cal_idx+{POST}
        WHERE d.trade_date<=DATE '2021-12-31'
        ORDER BY e.event_id,d.cal_idx
        """
    ).fetch_df()
    connection.close()
    for frame, columns in (
        (
            candidates,
            [
                "gap_date",
                "rejection_date",
                "signal_date",
                "signal_time",
                "available_at",
                "decision_at",
                "market_latest_source_timestamp",
            ],
        ),
        (daily, ["trade_date", "available_at", "decision_at"]),
    ):
        for column in columns:
            frame[column] = pd.to_datetime(frame[column])
    if daily.trade_date.max() > SOURCE_END:
        raise ResearchError("chart/outcome source exceeds frozen tail")
    return candidates, daily


def outcome_bucket(status: str, value: Any) -> str:
    try:
        net = float(value)
    except (TypeError, ValueError):
        net = math.nan
    if status != "COMPLETED" or not math.isfinite(net):
        return "NOT_COMPLETED"
    if net >= 0.04:
        return "PROFIT_GE_4PCT"
    if net >= 0:
        return "PROFIT_0_TO_4PCT"
    if net > -0.10:
        return "LOSS_0_TO_10PCT"
    return "SEVERE_LOSS"


def render_chart(event: pd.Series, frame: pd.DataFrame, output: Path) -> None:
    frame = frame.sort_values("cal_idx", kind="mergesort")
    signal_date = pd.Timestamp(event.signal_date)
    signal = frame.loc[frame.trade_date.eq(signal_date)]
    if len(signal) != 1:
        raise ResearchError(f"{event.event_id}: missing signal bar")
    signal_close = float(signal.iloc[0].coord_close)
    figure, (price_ax, volume_ax) = charts.plt.subplots(
        2,
        1,
        figsize=(13.2, 7.4),
        gridspec_kw={"height_ratios": [4.4, 1.0], "hspace": 0.05},
        sharex=True,
    )
    charts.draw_candles(price_ax, frame, signal_close)
    to_x = lambda value: charts.mdates.date2num(pd.Timestamp(value).to_pydatetime())
    to_y = lambda value: float(value) * 100.0 / signal_close
    price_ax.axvline(to_x(event.gap_date), color="#2563eb", linewidth=1.0, label="up-gap")
    price_ax.axvline(to_x(event.rejection_date), color="#dc2626", linewidth=1.0, label="full rejection")
    price_ax.axvline(to_x(event.signal_date), color="#059669", linewidth=1.4, label="second acceptance")
    price_ax.axhspan(to_y(event.gap_L), to_y(event.gap_U), color="#60a5fa", alpha=0.16, label="untraded gap [L,U]")
    price_ax.axhline(to_y(event.pre_rejection_peak_P), color="#7c3aed", linestyle="--", linewidth=1.0, label="pre-rejection peak P")
    if pd.notna(event.get("entry_date")) and np.isfinite(float(event.get("entry_price", math.nan))):
        price_ax.scatter(to_x(event.entry_date), to_y(event.entry_price), marker="^", s=58, color="#7c3aed", zorder=8, label="entry")
    if pd.notna(event.get("target_price")) and np.isfinite(float(event.get("target_price", math.nan))):
        price_ax.axhline(to_y(event.target_price), color="#f59e0b", linestyle=":", linewidth=1.0, label="A67 target")
    if pd.notna(event.get("exit_date")) and np.isfinite(float(event.get("exit_price", math.nan))):
        price_ax.scatter(to_x(event.exit_date), to_y(event.exit_price), marker="v", s=58, color="#111827", zorder=8, label="exit")
    title_result = str(event.outcome_bucket)
    if np.isfinite(float(event.get("net_return", math.nan))):
        title_result += f" | net {float(event.net_return):+.2%} | {event.exit_reason}"
    price_ax.set_title(
        f"{int(event.chart_number):04d} | {event.symbol} | {signal_date.date()} | causal {event.market_regime} | {title_result}\n"
        f"gap {float(event.gap_width):.1%} | gap->reject {int(event.gap_to_rejection_sessions)} | reject->signal {int(event.rejection_to_signal_sessions)} | "
        f"P headroom {float(event.peak_headroom_from_U):.1%} | signal {float(event.signal_step_return):+.1%} | market r20/r60 {float(event.market_median_ret20):+.1%}/{float(event.market_median_ret60):+.1%}",
        fontsize=9.5,
    )
    price_ax.set_ylabel("Coordinate price (signal close=100)")
    price_ax.grid(alpha=0.17, linewidth=0.5)
    handles, labels = price_ax.get_legend_handles_labels()
    unique = dict(zip(labels, handles, strict=False))
    price_ax.legend(unique.values(), unique.keys(), loc="upper left", ncol=5, fontsize=7.0)
    turn = frame.loc[frame.turnover_fraction.notna()]
    volume_ax.bar(
        charts.mdates.date2num(pd.to_datetime(turn.trade_date).to_numpy()),
        turn.turnover_fraction.astype(float) * 100.0,
        width=0.75,
        color="#888888",
        alpha=0.55,
    )
    volume_ax.axvline(to_x(event.signal_date), color="#059669", linewidth=1.0)
    volume_ax.set_ylabel("Turnover %")
    volume_ax.grid(alpha=0.12, linewidth=0.4)
    volume_ax.xaxis.set_major_locator(charts.mdates.MonthLocator(interval=2))
    volume_ax.xaxis.set_major_formatter(charts.mdates.DateFormatter("%Y-%m"))
    for label in volume_ax.get_xticklabels():
        label.set_rotation(25)
        label.set_horizontalalignment("right")
    figure.subplots_adjust(left=0.065, right=0.985, top=0.88, bottom=0.10)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(
        output,
        dpi=115,
        bbox_inches="tight",
        facecolor="white",
        metadata={"Creator": EXPERIMENT, "Title": str(event.event_id)},
    )
    charts.plt.close(figure)


def render_worker(payload: tuple[dict[str, Any], pd.DataFrame, str]) -> dict[str, Any]:
    event_dict, frame, output_text = payload
    event = pd.Series(event_dict)
    output = Path(output_text)
    render_chart(event, frame, output)
    return {
        "chart_number": int(event.chart_number),
        "event_id": str(event.event_id),
        "symbol": str(event.symbol),
        "signal_date": pd.Timestamp(event.signal_date),
        "market_regime": str(event.market_regime),
        "outcome_bucket": str(event.outcome_bucket),
        "net_return": event.get("net_return"),
        "chart_path": str(output),
    }


def build_sheets(index: pd.DataFrame) -> list[Path]:
    outputs: list[Path] = []
    order = [
        "SEVERE_LOSS",
        "LOSS_0_TO_10PCT",
        "PROFIT_0_TO_4PCT",
        "PROFIT_GE_4PCT",
        "NOT_COMPLETED",
    ]
    for bucket in order:
        rows = index.loc[index.outcome_bucket.eq(bucket)].sort_values(
            ["signal_date", "symbol", "event_id"], kind="mergesort"
        ).to_dict("records")
        target = SHEET_DIR / bucket.lower()
        target.mkdir(parents=True, exist_ok=True)
        for start in range(0, len(rows), 9):
            group = rows[start : start + 9]
            canvas = Image.new("RGB", (3600, 2130), "white")
            draw = ImageDraw.Draw(canvas)
            for offset, row in enumerate(group):
                source = Image.open(row["chart_path"]).convert("RGB")
                source.thumbnail((1180, 680), Image.Resampling.LANCZOS)
                canvas.paste(
                    source,
                    (10 + (offset % 3) * 1195, 35 + (offset // 3) * 695),
                )
                source.close()
            sheet_no = start // 9 + 1
            draw.text(
                (15, 8),
                f"{bucket} | sheet {sheet_no:03d} | events {start + 1}-{start + len(group)}",
                fill="black",
            )
            output = target / f"sheet_{sheet_no:03d}.jpg"
            canvas.save(output, "JPEG", quality=90, optimize=True)
            outputs.append(output)
    return outputs


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    complete = frame.loc[frame.status.eq("COMPLETED")].copy()
    returns = complete.net_return.astype(float)
    return {
        "signals": int(len(frame)),
        "completed": int(len(complete)),
        "accepted_entry_and_headroom": int(
            frame.status.isin(["COMPLETED", "INCOMPLETE_BY_2021_END", "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY"]).sum()
        ),
        "mean_net": None if complete.empty else float(returns.mean()),
        "median_net": None if complete.empty else float(returns.median()),
        "positive_rate": None if complete.empty else float(returns.gt(0).mean()),
        "ge_4pct_rate": None if complete.empty else float(returns.ge(0.04).mean()),
        "severe_loss_rate": None if complete.empty else float(returns.le(-0.10).mean()),
        "target_hit_rate": None if complete.empty else float(complete.exit_reason.eq("A67_PRE_REJECTION_PEAK").mean()),
        "mean_holding_sessions": None if complete.empty else float(complete.holding_sessions.mean()),
        "status_counts": frame.status.value_counts().sort_index().to_dict(),
    }


def run_stage_b(workers: int, skip_render: bool) -> dict[str, Any]:
    verify_sources()
    candidates, daily = load_stage_b_inputs()
    daily_map = {key: part for key, part in daily.groupby("event_id", sort=False)}
    outcomes = pd.DataFrame(
        [
            replay_one(candidate, daily_map.get(str(candidate.event_id), pd.DataFrame()))
            for candidate in candidates.itertuples(index=False)
        ]
    ).sort_values(["signal_date", "sleeve", "symbol", "event_id"], kind="mergesort")
    write_parquet(outcomes, OUTCOMES)
    outcome_only = outcomes.drop(
        columns=[
            "signal_year",
            "signal_cal_idx",
            "market_regime",
            "gap_L",
            "gap_U",
            "pre_rejection_peak_P",
        ]
    )
    ledger = candidates.merge(
        outcome_only,
        on=["event_id", "symbol", "sleeve", "signal_date"],
        how="left",
        validate="one_to_one",
    )
    ledger["outcome_bucket"] = [
        outcome_bucket(str(status), value)
        for status, value in zip(ledger.status, ledger.net_return, strict=True)
    ]
    ledger["chart_number"] = np.arange(1, len(ledger) + 1, dtype=int)
    write_parquet(daily, WINDOWS)
    write_parquet(ledger, LEDGER)
    LEDGER_CSV.parent.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(LEDGER_CSV, index=False, float_format="%.10g")

    if not skip_render:
        tasks = []
        for event in ledger.itertuples(index=False):
            output = CHART_DIR / (
                f"{int(event.chart_number):04d}_{str(event.symbol).replace('.', '_')}_"
                f"{pd.Timestamp(event.signal_date):%Y%m%d}.png"
            )
            tasks.append((event._asdict(), daily_map[str(event.event_id)], str(output)))
        with ProcessPoolExecutor(max_workers=max(1, workers)) as executor:
            index_rows = list(executor.map(render_worker, tasks, chunksize=1))
        index = pd.DataFrame(index_rows)
        index.to_csv(CHART_INDEX, index=False, float_format="%.10g")
        sheets = build_sheets(index)
    else:
        if not CHART_INDEX.is_file():
            raise ResearchError("--skip-render requires an existing chart index")
        index = pd.read_csv(CHART_INDEX, parse_dates=["signal_date"])
        sheets = sorted(SHEET_DIR.glob("*/*.jpg"))

    annual = {
        str(year): metrics(part)
        for year, part in outcomes.groupby(outcomes.signal_date.dt.year, sort=True)
    }
    pooled = metrics(outcomes)
    by_state = {
        state: metrics(outcomes.loc[outcomes.market_regime.eq(state)])
        for state in ("BEAR", "BULL", "TRANSITION")
    }
    annual_counts = {int(year): int(value["signals"]) for year, value in annual.items()}
    result = {
        "experiment": EXPERIMENT,
        "scientific_status": "DEVELOPMENT_CHART_ANATOMY_OUTCOMES_OPENED_AFTER_MOTHER_FREEZE",
        "freeze_sha256": sha256(FREEZE),
        "stage_a_sha256": sha256(STAGE_A),
        "candidate_sha256": sha256(CANDIDATES),
        "baseline_outcome_sha256": sha256(OUTCOMES),
        "review_ledger_sha256": sha256(LEDGER),
        "chart_index_sha256": sha256(CHART_INDEX),
        "candidate_count": int(len(candidates)),
        "chart_count": int(len(index)),
        "sheet_count": int(len(sheets)),
        "pooled": pooled,
        "annual": annual,
        "by_causal_market_state": by_state,
        "promotion_gate": {
            "signals_each_2014_2020_year_gt_50": bool(
                set(annual_counts) == set(range(2014, 2021))
                and min(annual_counts.values()) > 50
            ),
            "pooled_completed_mean_net_gt_4pct": bool(
                pooled["mean_net"] is not None and float(pooled["mean_net"]) > 0.04
            ),
            "pooled_completed_median_positive": bool(
                pooled["median_net"] is not None and float(pooled["median_net"]) > 0
            ),
        },
        "causality_audit": {
            "entry_on_or_before_signal": int(
                outcomes.loc[outcomes.entry_date.notna(), "entry_date"].le(
                    outcomes.loc[outcomes.entry_date.notna(), "signal_date"]
                ).sum()
            ),
            "market_state_after_signal": int(
                candidates.market_latest_source_timestamp.gt(candidates.signal_time).sum()
            ),
            "max_signal_date": str(candidates.signal_date.max().date()),
            "max_chart_or_outcome_source_date": str(daily.trade_date.max().date()),
            "2022_2024_read": False,
            "2025_plus_read": False,
        },
    }
    result["promotion_gate"]["pass"] = bool(all(result["promotion_gate"].values()))
    write_json(RESULT, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["a", "b", "all"], default="all")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--skip-render", action="store_true")
    parser.add_argument("--print-result", action="store_true")
    args = parser.parse_args()
    output: dict[str, Any] = {}
    if args.stage in {"a", "all"}:
        output["stage_a"] = run_stage_a()
    if args.stage in {"b", "all"}:
        output["stage_b"] = run_stage_b(args.workers, args.skip_render)
    if args.print_result:
        print(json.dumps(output, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
