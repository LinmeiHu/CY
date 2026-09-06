#!/usr/bin/env python3
"""Freeze and chart the bearish-displacement overhead-supply re-entry family."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import duckdb
import matplotlib
import numpy as np
import pandas as pd
import run_ashare_deep_decline_intraday_undercut_full_absorption_v1 as execution
from PIL import Image, ImageDraw

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-BEARISH-DISPLACEMENT-SUPPLY-ZONE-REENTRY-V1"
DAILY = execution.DAILY
CONTRACT = OS_ROOT / f"experiments/{EXPERIMENT}_contract.json"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_stage_a_freeze.json"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_bearish_displacement_supply_zone_reentry_v1"
)
CANDIDATES = EXT_ROOT / "stage_a/frozen_candidates_2014_2021.parquet"
OUTCOMES = EXT_ROOT / "chart_discovery_2014_2020/outcomes.parquet"
WINDOWS = EXT_ROOT / "chart_discovery_2014_2020/chart_window_panel.parquet"
LEDGER = EXT_ROOT / "chart_discovery_2014_2020/review_ledger.parquet"
LEDGER_CSV = EXT_ROOT / "chart_discovery_2014_2020/review_ledger.csv"
CHART_DIR = EXT_ROOT / "chart_discovery_2014_2020/individual_charts"
SHEET_DIR = EXT_ROOT / "chart_discovery_2014_2020/contact_sheets"
OUTCOME_SHEET_ROOT = EXT_ROOT / "chart_discovery_2014_2020/review_sheets_by_outcome"
CHART_INDEX = EXT_ROOT / "chart_discovery_2014_2020/chart_index.csv"
MANIFEST = EXT_ROOT / "chart_discovery_2014_2020/manifest.json"

PRE = 126
POST = 126
LIFECYCLE = 120
FORMATION_BODY = -0.05
PERSISTENCE = 20
SIGNAL_HEADROOM = 0.05
ENTRY_GROSS_HEADROOM = 0.044
HORIZON = 20
COST = 0.004


class ExperimentError(RuntimeError):
    """Fail-closed displacement-zone research error."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, default=str)
        + "\n",
        encoding="utf-8",
    )


def detect_candidates() -> pd.DataFrame:
    query = f"""
    SELECT trade_date,cal_idx,symbol,sleeve,turnover_fraction,is_st,
      current_day_data_tradable,market_rule_valid,corporate_action_valid,
      corporate_action_blocking,hard_valid,history_valid,current_valid,
      invalid_step_cum,coord_open,coord_high,coord_low,coord_close,
      step_return,ret20,ret60,
      avg(turnover_fraction) OVER (
        PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
      ) AS turn20,
      min(coord_low) OVER (
        PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
      ) AS low20prev,
      lag(coord_high) OVER (PARTITION BY symbol ORDER BY cal_idx) AS prior_high,
      count(*) OVER (
        PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
      ) AS n20,
      min(current_valid::INTEGER) OVER (
        PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
      ) AS valid20,
      min(current_day_data_tradable::INTEGER) OVER (
        PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
      ) AS tradable20
    FROM read_parquet('{DAILY.as_posix()}')
    WHERE trade_date<=DATE '2021-12-31'
    ORDER BY symbol,cal_idx
    """
    connection = duckdb.connect()
    connection.execute("SET threads=4")
    connection.execute("SET memory_limit='12GB'")
    connection.execute("SET preserve_insertion_order=false")
    base = connection.execute(query).fetch_df()
    connection.close()
    raw_records: list[dict[str, Any]] = []
    for _, part in base.groupby("symbol", sort=False):
        raw_records.extend(_detect_symbol_candidates(part.reset_index(drop=True)))
    raw = pd.DataFrame.from_records(raw_records)
    if raw.empty:
        raise ExperimentError("no candidate survived the frozen state machine")
    for column in ("formation_date", "first_below_date", "signal_date"):
        raw[column] = pd.to_datetime(raw[column])
    raw = raw[
        raw.signal_date.between(pd.Timestamp("2014-01-01"), pd.Timestamp("2021-12-31"))
    ].copy()
    keep: list[int] = []
    for _, part in raw.groupby("symbol", sort=False):
        last_signal = -10**12
        for index, row in part.iterrows():
            if int(row.signal_idx) - last_signal > LIFECYCLE:
                keep.append(index)
                last_signal = int(row.signal_idx)
    frozen = raw.loc[keep].copy()
    frozen["event_id"] = (
        frozen.symbol.astype(str)
        + "|"
        + frozen.formation_date.dt.strftime("%Y-%m-%d")
        + "|"
        + frozen.signal_date.dt.strftime("%Y-%m-%d")
    )
    frozen = frozen.sort_values(
        ["signal_date", "sleeve", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    if frozen.event_id.duplicated().any():
        raise ExperimentError("duplicate frozen event identity")
    if frozen.signal_date.max() > pd.Timestamp("2021-12-31"):
        raise ExperimentError("candidate date escaped frozen formation period")
    return frozen


def _detect_symbol_candidates(part: pd.DataFrame) -> list[dict[str, Any]]:
    """Apply the frozen zone lifecycle in one causal pass for one symbol."""
    eligible = (
        part.hard_valid.fillna(False)
        & part.history_valid.fillna(False)
        & part.current_valid.fillna(False)
        & part.current_day_data_tradable.fillna(False)
        & part.market_rule_valid.fillna(False)
        & part.corporate_action_valid.fillna(False)
        & ~part.corporate_action_blocking.fillna(True)
        & ~part.is_st.fillna(True)
    ).to_numpy(dtype=bool)
    cal_idx = part.cal_idx.to_numpy(dtype=np.int64)
    lineage = part.invalid_step_cum.to_numpy(dtype=float)
    coord_open = part.coord_open.to_numpy(dtype=float)
    coord_high = part.coord_high.to_numpy(dtype=float)
    coord_low = part.coord_low.to_numpy(dtype=float)
    coord_close = part.coord_close.to_numpy(dtype=float)
    turnover = part.turnover_fraction.to_numpy(dtype=float)
    turn20 = part.turn20.to_numpy(dtype=float)
    ranges = coord_high - coord_low
    close_location = np.divide(
        coord_close - coord_low,
        ranges,
        out=np.full_like(coord_close, np.nan),
        where=ranges != 0.0,
    )
    formation = (
        eligible
        & (part.n20.to_numpy(dtype=float) == 20)
        & (part.valid20.to_numpy(dtype=float) == 1)
        & (part.tradable20.to_numpy(dtype=float) == 1)
        & (coord_close / coord_open - 1.0 <= FORMATION_BODY)
        & (turnover >= turn20)
        & (close_location <= 0.30)
        & (coord_low <= part.low20prev.to_numpy(dtype=float))
    )
    by_signal: dict[int, dict[str, Any]] = {}
    for formation_pos in np.flatnonzero(formation):
        formation_idx = int(cal_idx[formation_pos])
        zone_l = float(coord_close[formation_pos])
        zone_u = float(coord_open[formation_pos])
        formation_lineage = float(lineage[formation_pos])
        first_below_pos: int | None = None
        for position in range(formation_pos + 1, len(part)):
            if cal_idx[position] > formation_idx + 60:
                break
            if (
                eligible[position]
                and lineage[position] == formation_lineage
                and coord_high[position] < zone_l
            ):
                first_below_pos = position
                break
        if first_below_pos is None:
            continue
        signal_pos: int | None = None
        first_below_idx = int(cal_idx[first_below_pos])
        for position in range(first_below_pos + 1, len(part)):
            if cal_idx[position] > formation_idx + LIFECYCLE:
                break
            if cal_idx[position] < first_below_idx + PERSISTENCE:
                continue
            if not eligible[position] or lineage[position] != formation_lineage:
                continue
            if not (
                coord_close[position] >= zone_l
                and coord_close[position] < zone_u
                and zone_u / coord_close[position] - 1.0 >= SIGNAL_HEADROOM
                and coord_close[position] >= float(part.prior_high.iloc[position])
                and close_location[position] >= 0.70
                and turnover[position] >= turn20[position]
            ):
                continue
            intervening = eligible[formation_pos + 1 : position]
            highs = coord_high[formation_pos + 1 : position][intervening]
            if not len(highs) or float(np.max(highs)) >= zone_u:
                continue
            signal_pos = position
            break
        if signal_pos is None:
            continue
        signal_idx = int(cal_idx[signal_pos])
        record = {
            "symbol": str(part.symbol.iloc[signal_pos]),
            "sleeve": str(part.sleeve.iloc[signal_pos]),
            "formation_date": part.trade_date.iloc[formation_pos],
            "formation_idx": formation_idx,
            "zone_l": zone_l,
            "zone_u": zone_u,
            "invalid_step_cum": formation_lineage,
            "formation_ret20": float(part.ret20.iloc[formation_pos]),
            "formation_ret60": float(part.ret60.iloc[formation_pos]),
            "formation_turnover": float(turnover[formation_pos]),
            "formation_turn20": float(turn20[formation_pos]),
            "formation_body_return": float(
                coord_close[formation_pos] / coord_open[formation_pos] - 1.0
            ),
            "formation_close_location": float(close_location[formation_pos]),
            "first_below_idx": first_below_idx,
            "max_high_before_signal": float(np.max(highs)),
            "signal_idx": signal_idx,
            "signal_date": part.trade_date.iloc[signal_pos],
            "signal_open": float(coord_open[signal_pos]),
            "signal_high": float(coord_high[signal_pos]),
            "signal_low": float(coord_low[signal_pos]),
            "signal_close": float(coord_close[signal_pos]),
            "signal_turnover": float(turnover[signal_pos]),
            "signal_turn20": float(turn20[signal_pos]),
            "signal_step_return": float(part.step_return.iloc[signal_pos]),
            "signal_ret20": float(part.ret20.iloc[signal_pos]),
            "signal_ret60": float(part.ret60.iloc[signal_pos]),
            "signal_close_location": float(close_location[signal_pos]),
            "first_below_date": part.trade_date.iloc[first_below_pos],
        }
        previous = by_signal.get(signal_idx)
        if previous is None or formation_idx > int(previous["formation_idx"]):
            by_signal[signal_idx] = record
    return sorted(by_signal.values(), key=lambda row: int(row["signal_idx"]))


def freeze_stage_a() -> dict[str, Any]:
    if not CONTRACT.exists() or not DAILY.exists():
        raise ExperimentError("missing contract or PIT daily input")
    candidates = detect_candidates()
    execution.write_parquet(candidates, CANDIDATES)
    annual = candidates.groupby(candidates.signal_date.dt.year).size().to_dict()
    if set(annual) != set(range(2014, 2022)) or min(annual.values()) <= 50:
        raise ExperimentError(f"insufficient frozen candidate coverage: {annual}")
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_MOTHER_EVENT_IDENTITY_FREEZE",
        "contract_sha256": sha256(CONTRACT),
        "runner_sha256": sha256(Path(__file__)),
        "daily_input_sha256": sha256(DAILY),
        "candidate_sha256": sha256(CANDIDATES),
        "candidate_count": len(candidates),
        "annual_candidate_counts": {str(key): int(value) for key, value in annual.items()},
        "maximum_signal_date": str(candidates.signal_date.max().date()),
        "development_outcomes_read": False,
        "2021_signal_outcomes_read": False,
        "2022_plus_outcomes_read": False,
        "post_2024_outcomes_read": False,
        "cy011_read": False,
    }
    canonical_json(FREEZE, freeze)
    return freeze


def verify_freeze() -> pd.DataFrame:
    if not FREEZE.exists() or not CANDIDATES.exists():
        raise ExperimentError("Stage-A freeze is missing")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    checks = {
        "contract_sha256": sha256(CONTRACT),
        "runner_sha256": sha256(Path(__file__)),
        "daily_input_sha256": sha256(DAILY),
        "candidate_sha256": sha256(CANDIDATES),
    }
    drift = {
        key: (freeze.get(key), value)
        for key, value in checks.items()
        if freeze.get(key) != value
    }
    if drift:
        raise ExperimentError(f"Stage-A freeze drift: {drift}")
    frame = duckdb.connect().execute(
        f"SELECT * FROM read_parquet('{CANDIDATES.as_posix()}') "
        "ORDER BY signal_date,sleeve,symbol,event_id"
    ).fetch_df()
    for column in ("formation_date", "first_below_date", "signal_date"):
        frame[column] = pd.to_datetime(frame[column])
    return frame


def load_future_paths(candidates: pd.DataFrame) -> pd.DataFrame:
    connection = duckdb.connect()
    connection.register(
        "candidate_ids",
        candidates[
            ["event_id", "symbol", "signal_date", "signal_idx", "invalid_step_cum"]
        ],
    )
    frame = connection.execute(
        f"""
        SELECT c.event_id,c.signal_date,c.signal_idx,
          c.invalid_step_cum AS signal_invalid_step_cum,
          d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,
          d.coordinate_factor,d.invalid_step_cum,d.trade_status,
          d.current_day_data_tradable,d.market_rule_valid,
          d.corporate_action_valid,d.corporate_action_blocking,d.hard_valid,
          d.up_limit_price,d.down_limit_price
        FROM candidate_ids c JOIN read_parquet('{DAILY.as_posix()}') d
          ON c.symbol=d.symbol AND d.cal_idx>c.signal_idx
        WHERE d.trade_date<=DATE '2021-12-31'
        ORDER BY c.event_id,d.cal_idx
        """
    ).fetch_df()
    connection.close()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    return frame


def replay_one(candidate: Any, path: pd.DataFrame) -> dict[str, Any]:
    signal_idx = int(candidate.signal_idx)
    lineage = float(candidate.invalid_step_cum)
    base = {
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "formation_date": pd.Timestamp(candidate.formation_date),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_idx": signal_idx,
        "zone_l": float(candidate.zone_l),
        "zone_u": float(candidate.zone_u),
        "profile": "FULL_ZONE_U_H20_NO_STOP",
    }
    if path.empty:
        return {**base, "status": "NO_FUTURE_PATH_THROUGH_2021"}
    entry_pool = path.loc[
        path.cal_idx.le(signal_idx + 3) & path.invalid_step_cum.eq(lineage)
    ]
    entry = next((row for _, row in entry_pool.iterrows() if execution.buyable_open(row)), None)
    if entry is None:
        return {**base, "status": "NO_LEGAL_ENTRY"}
    entry_idx = int(entry.cal_idx)
    entry_price = float(entry.coord_open)
    entry_payload = {
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_idx": entry_idx,
        "entry_price": entry_price,
        "gross_headroom": float(candidate.zone_u) / entry_price - 1.0,
    }
    if float(candidate.zone_u) / entry_price - 1.0 < ENTRY_GROSS_HEADROOM:
        return {**base, **entry_payload, "status": "INSUFFICIENT_ENTRY_HEADROOM"}
    pending = False
    exit_row: pd.Series | None = None
    exit_price = math.nan
    exit_reason: str | None = None
    invalid = False
    for _, row in path.loc[path.cal_idx.gt(entry_idx)].iterrows():
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != lineage:
            invalid = True
            break
        if pending and execution.sellable_open(row):
            exit_row = row
            exit_price = float(row.coord_open)
            exit_reason = "H20_TIME_STOP"
            break
        if (
            execution.legal_state(row)
            and np.isfinite(float(row.coord_high))
            and float(row.coord_high) >= float(candidate.zone_u)
        ):
            exit_row = row
            exit_price = float(candidate.zone_u)
            exit_reason = "FULL_ZONE_U"
            break
        if execution.legal_state(row) and int(row.cal_idx) >= entry_idx + HORIZON:
            pending = True
    if invalid:
        return {
            **base,
            **entry_payload,
            "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
        }
    if exit_row is None:
        return {**base, **entry_payload, "status": "INCOMPLETE_BY_2021_END"}
    gross = exit_price / entry_price - 1.0
    return {
        **base,
        **entry_payload,
        "status": "COMPLETED",
        "exit_date": pd.Timestamp(exit_row.trade_date),
        "exit_idx": int(exit_row.cal_idx),
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "holding_sessions": int(exit_row.cal_idx) - entry_idx,
        "gross_return": gross,
        "net_return": gross - COST,
    }


def replay(candidates: pd.DataFrame) -> pd.DataFrame:
    paths = load_future_paths(candidates)
    groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    return pd.DataFrame(
        [
            replay_one(event, groups.get(str(event.event_id), pd.DataFrame()))
            for event in candidates.itertuples(index=False)
        ]
    )


def load_chart_windows(candidates: pd.DataFrame) -> pd.DataFrame:
    connection = duckdb.connect()
    connection.register(
        "candidate_ids",
        candidates[["event_id", "symbol", "signal_date", "signal_idx"]],
    )
    frame = connection.execute(
        f"""
        SELECT c.event_id,c.signal_date,d.symbol,d.trade_date,d.cal_idx,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.turnover_fraction,
          d.current_valid,d.hard_valid
        FROM candidate_ids c JOIN read_parquet('{DAILY.as_posix()}') d
          ON c.symbol=d.symbol
         AND d.cal_idx BETWEEN c.signal_idx-{PRE} AND c.signal_idx+{POST}
        WHERE d.trade_date<=DATE '2021-12-31'
        ORDER BY c.event_id,d.cal_idx
        """
    ).fetch_df()
    connection.close()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    frame["signal_date"] = pd.to_datetime(frame.signal_date)
    if frame.event_id.nunique() != len(candidates):
        raise ExperimentError("chart windows miss candidate identities")
    return frame


def outcome_bucket(status: str, net_return: float) -> str:
    if status != "COMPLETED" or not np.isfinite(net_return):
        return "NO_COMPLETED_TRADE"
    if net_return >= 0.04:
        return "PROFIT_GE_4PCT"
    if net_return >= 0.0:
        return "PROFIT_0_TO_4PCT"
    if net_return > -0.10:
        return "LOSS_0_TO_10PCT"
    return "SEVERE_LOSS"


def build_ledger(candidates: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    merged = candidates.merge(
        outcomes,
        on=["event_id", "symbol", "sleeve", "formation_date", "signal_date", "zone_l", "zone_u"],
        how="left",
        validate="one_to_one",
        suffixes=("", "_outcome"),
    )
    merged["zone_width_pct"] = merged.zone_u / merged.zone_l - 1.0
    merged["zone_age"] = merged.signal_idx - merged.formation_idx
    merged["complete_below_age"] = merged.signal_idx - merged.first_below_idx
    merged["signal_progress"] = (
        (merged.signal_close - merged.zone_l) / (merged.zone_u - merged.zone_l)
    )
    merged["formation_turnover_ratio"] = (
        merged.formation_turnover / merged.formation_turn20
    )
    merged["signal_turnover_ratio"] = merged.signal_turnover / merged.signal_turn20
    merged["net_return"] = pd.to_numeric(merged.net_return, errors="coerce")
    merged["outcome_bucket"] = [
        outcome_bucket(str(status), float(value) if pd.notna(value) else math.nan)
        for status, value in zip(merged.status, merged.net_return, strict=True)
    ]
    merged = merged.sort_values(
        ["signal_date", "sleeve", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    merged["chart_number"] = np.arange(1, len(merged) + 1)
    return merged


def draw_candles(ax: Any, frame: pd.DataFrame, scale: float) -> None:
    valid = frame.loc[
        frame.current_valid.fillna(False)
        & frame[["coord_open", "coord_high", "coord_low", "coord_close"]]
        .notna()
        .all(axis=1)
    ].copy()
    dates = mdates.date2num(valid.trade_date.to_numpy())
    for x, row in zip(dates, valid.itertuples(index=False), strict=True):
        opening = float(row.coord_open) * scale
        high = float(row.coord_high) * scale
        low = float(row.coord_low) * scale
        close = float(row.coord_close) * scale
        color = "#d62728" if close >= opening else "#159447"
        ax.vlines(x, low, high, color=color, linewidth=0.55)
        bottom = min(opening, close)
        ax.add_patch(
            Rectangle(
                (x - 0.34, bottom),
                0.68,
                max(abs(close - opening), 0.08),
                facecolor=color,
                edgecolor=color,
                linewidth=0.25,
            )
        )
    ax.set_xlim(dates.min() - 3, dates.max() + 3)


def render_one(event: pd.Series, frame: pd.DataFrame, output: Path) -> None:
    scale = 100.0 / float(event.signal_close)
    figure, (price_ax, volume_ax) = plt.subplots(
        2,
        1,
        figsize=(13.2, 7.4),
        gridspec_kw={"height_ratios": [4.4, 1.0], "hspace": 0.05},
        sharex=True,
    )
    draw_candles(price_ax, frame, scale)
    markers = [
        (event.formation_date, "formation", "#c25b00"),
        (event.first_below_date, "complete below", "#777777"),
        (event.signal_date, "signal", "#1f77b4"),
    ]
    for date, label, color in markers:
        price_ax.axvline(
            mdates.date2num(pd.Timestamp(date).to_pydatetime()),
            color=color,
            linewidth=1.0,
            label=label,
        )
    price_ax.axhspan(
        float(event.zone_l) * scale,
        float(event.zone_u) * scale,
        color="#ffb347",
        alpha=0.18,
        label="frozen supply zone [L,U]",
    )
    price_ax.axhline(float(event.zone_l) * scale, color="#c25b00", linestyle="--", linewidth=0.8)
    price_ax.axhline(float(event.zone_u) * scale, color="#c25b00", linestyle="--", linewidth=0.8)
    if pd.notna(event.entry_date) and pd.notna(event.entry_price):
        price_ax.scatter(
            mdates.date2num(pd.Timestamp(event.entry_date).to_pydatetime()),
            float(event.entry_price) * scale,
            marker="^",
            s=65,
            color="#7b2cbf",
            zorder=8,
            label="entry",
        )
    if pd.notna(event.exit_date) and pd.notna(event.exit_price):
        price_ax.scatter(
            mdates.date2num(pd.Timestamp(event.exit_date).to_pydatetime()),
            float(event.exit_price) * scale,
            marker="v",
            s=65,
            color="#111111",
            zorder=8,
            label="exit",
        )
    outcome = str(event.outcome_bucket)
    if pd.notna(event.net_return):
        outcome += f" | net {float(event.net_return):+.2%} | {event.exit_reason}"
    signal_date = pd.Timestamp(event.signal_date).date()
    price_ax.set_title(
        f"{int(event.chart_number):04d} | {event.symbol} | signal {signal_date} | {outcome}\n"
        f"zone {float(event.zone_width_pct):.1%} | age {int(event.zone_age)} | "
        f"below {int(event.complete_below_age)} | progress {float(event.signal_progress):.0%} | "
        f"formation r60 {float(event.formation_ret60):+.1%} | "
        f"signal r60 {float(event.signal_ret60):+.1%}",
        fontsize=10,
    )
    price_ax.set_ylabel("Coordinate price (signal close=100)")
    price_ax.grid(alpha=0.16, linewidth=0.5)
    handles, labels = price_ax.get_legend_handles_labels()
    deduped = dict(zip(labels, handles, strict=False))
    price_ax.legend(deduped.values(), deduped.keys(), loc="upper left", fontsize=7, ncol=6)
    volume_ax.bar(
        mdates.date2num(frame.trade_date.to_numpy()),
        frame.turnover_fraction.fillna(0.0) * 100.0,
        width=0.75,
        color="#888888",
        alpha=0.55,
    )
    volume_ax.set_ylabel("Turnover %")
    volume_ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    volume_ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    for label in volume_ax.get_xticklabels():
        label.set_rotation(25)
        label.set_horizontalalignment("right")
    figure.subplots_adjust(left=0.065, right=0.985, top=0.88, bottom=0.10)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=110, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def render_worker(payload: tuple[dict[str, Any], pd.DataFrame, str]) -> dict[str, Any]:
    event_dict, frame, output_text = payload
    event = pd.Series(event_dict)
    output = Path(output_text)
    render_one(event, frame, output)
    return {
        "chart_number": int(event.chart_number),
        "event_id": str(event.event_id),
        "symbol": str(event.symbol),
        "signal_date": pd.Timestamp(event.signal_date),
        "outcome_bucket": str(event.outcome_bucket),
        "net_return": float(event.net_return) if pd.notna(event.net_return) else math.nan,
        "chart_path": str(output),
    }


def build_sheets(index: pd.DataFrame, outcome_split: bool) -> list[Path]:
    paths: list[Path] = []
    groups: list[tuple[str, pd.DataFrame]]
    if outcome_split:
        groups = [
            (str(bucket).lower(), part)
            for bucket, part in index.groupby("outcome_bucket", sort=True)
        ]
    else:
        groups = [("all", index)]
    for label, subset in groups:
        target = OUTCOME_SHEET_ROOT / label if outcome_split else SHEET_DIR
        target.mkdir(parents=True, exist_ok=True)
        rows = subset.sort_values("chart_number").to_dict("records")
        for start in range(0, len(rows), 4):
            batch = rows[start : start + 4]
            canvas = Image.new("RGB", (2400, 1440), "white")
            draw = ImageDraw.Draw(canvas)
            for offset, row in enumerate(batch):
                source = Image.open(row["chart_path"]).convert("RGB")
                source.thumbnail((1180, 680), Image.Resampling.LANCZOS)
                canvas.paste(source, (10 + (offset % 2) * 1195, 35 + (offset // 2) * 695))
                source.close()
            sheet_no = start // 4 + 1
            draw.text(
                (15, 8),
                f"{EXPERIMENT} | {label} | sheet {sheet_no:04d}",
                fill="black",
            )
            path = target / f"sheet_{sheet_no:04d}.jpg"
            canvas.save(path, "JPEG", quality=88, optimize=True)
            paths.append(path)
    return paths


def chart_discovery(workers: int) -> dict[str, Any]:
    all_candidates = verify_freeze()
    candidates = all_candidates.loc[
        all_candidates.signal_date.le(pd.Timestamp("2020-12-31"))
    ].copy()
    outcomes = replay(candidates)
    execution.write_parquet(outcomes, OUTCOMES)
    windows = load_chart_windows(candidates)
    execution.write_parquet(windows, WINDOWS)
    ledger = build_ledger(candidates, outcomes)
    execution.write_parquet(ledger, LEDGER)
    LEDGER_CSV.parent.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(LEDGER_CSV, index=False, float_format="%.10g")
    window_groups = {key: part for key, part in windows.groupby("event_id", sort=False)}
    tasks = []
    for _, event in ledger.iterrows():
        path = CHART_DIR / (
            f"{int(event.chart_number):04d}_{event.symbol.replace('.', '_')}_"
            f"{pd.Timestamp(event.signal_date):%Y%m%d}.png"
        )
        tasks.append((event.to_dict(), window_groups[str(event.event_id)], str(path)))
    with ProcessPoolExecutor(max_workers=max(1, workers)) as executor_pool:
        index_rows = list(executor_pool.map(render_worker, tasks, chunksize=1))
    index = pd.DataFrame(index_rows)
    index.to_csv(CHART_INDEX, index=False, float_format="%.10g")
    sheets = build_sheets(index, outcome_split=False)
    outcome_sheets = build_sheets(index, outcome_split=True)
    completed = ledger.loc[ledger.status.eq("COMPLETED")].copy()
    annual = (
        completed.assign(year=completed.signal_date.dt.year)
        .groupby("year")
        .agg(
            completed=("event_id", "size"),
            mean_net=("net_return", "mean"),
            median_net=("net_return", "median"),
            severe_loss10=("net_return", lambda values: float((values <= -0.10).mean())),
        )
        .reset_index()
    )
    manifest = {
        "experiment": EXPERIMENT,
        "contract_sha256": sha256(CONTRACT),
        "stage_a_freeze_sha256": sha256(FREEZE),
        "candidate_sha256": sha256(CANDIDATES),
        "chart_signal_count_2014_2020": len(candidates),
        "completed_count": len(completed),
        "annual_unfiltered_mother": annual.to_dict("records"),
        "chart_count": len(index),
        "contact_sheet_count": len(sheets),
        "outcome_sheet_count": len(outcome_sheets),
        "maximum_signal_date_used_for_chart_rules": str(candidates.signal_date.max().date()),
        "maximum_chart_bar_date": str(windows.trade_date.max().date()),
        "2021_signal_outcomes_read": False,
        "2022_plus_outcomes_read": False,
        "post_2024_outcomes_read": False,
        "cy011_read": False,
        "outcomes_sha256": sha256(OUTCOMES),
        "windows_sha256": sha256(WINDOWS),
        "ledger_sha256": sha256(LEDGER),
        "chart_index_sha256": sha256(CHART_INDEX),
    }
    canonical_json(MANIFEST, manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("freeze", "charts"), required=True)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    result = freeze_stage_a() if args.stage == "freeze" else chart_discovery(args.workers)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
