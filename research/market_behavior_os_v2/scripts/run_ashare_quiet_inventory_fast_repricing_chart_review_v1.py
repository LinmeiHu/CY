#!/usr/bin/env python3
"""Render all frozen validation signals with 120 sessions before and after."""

from __future__ import annotations

import hashlib
import json
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from matplotlib.font_manager import FontProperties

import run_ashare_panic_absorption_12m_chart_rule_discovery_v1 as charts


ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT = "ASHARE-QUIET-INVENTORY-FAST-REPRICING-V1-VALIDATION-CHART-REVIEW"
SOURCE = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_quiet_inventory_fast_repricing_v1/validation_2022_2024"
)
CANDIDATES = SOURCE / "frozen_validation_candidates.parquet"
OUTCOMES = SOURCE / "frozen_validation_outcomes.parquet"
EXPECTED_CANDIDATES_SHA256 = "5c2f37453e385275c6e0b294ff9acd035d70aa9aab1df1a5183295e1059f3a86"
EXPECTED_OUTCOMES_SHA256 = "d5c56f99481f57d62dd61a4d017319a47e38e879f6b30d2f34b427f9da953685"
OLD_DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
EXACT_DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_clean_corridor_v26_validation_2024_2025_v1/"
    "pit_daily_qd010_exact_2022_2026q1.parquet"
)
CHIP_PATHS = [
    Path(
        "/Users/linmei/Documents/CY/data/processed/"
        f"chip_state_features_by_year_2018_2026_v2/year={year}/data.parquet"
    )
    for year in (2022, 2023, 2024)
]

OUTPUT = SOURCE / "chart_review_120x120"
CHART_DIR = OUTPUT / "individual_charts"
SHEET_DIR = OUTPUT / "contact_sheets"
OUTCOME_SHEET_ROOT = OUTPUT / "review_sheets_by_outcome"
WINDOW_PANEL = OUTPUT / "chart_window_panel.parquet"
REVIEW_LEDGER = OUTPUT / "review_ledger.parquet"
CHART_INDEX = OUTPUT / "chart_index.csv"
MANIFEST = OUTPUT / "manifest.json"
CJK_FONT = FontProperties(fname="/System/Library/Fonts/STHeiti Light.ttc")


class ReviewError(RuntimeError):
    """Fail-closed validation chart error."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def chip_sql_paths() -> str:
    return "[" + ",".join("'" + path.as_posix() + "'" for path in CHIP_PATHS) + "]"


def configure_helper() -> None:
    charts.EXPERIMENT = EXPERIMENT
    charts.CHART_DIR = CHART_DIR
    charts.SHEET_DIR = SHEET_DIR
    charts.OUTCOME_SHEET_ROOT = OUTCOME_SHEET_ROOT


def load_ledger() -> pd.DataFrame:
    if sha256(CANDIDATES) != EXPECTED_CANDIDATES_SHA256:
        raise ReviewError("candidate hash drift")
    if sha256(OUTCOMES) != EXPECTED_OUTCOMES_SHA256:
        raise ReviewError("outcome hash drift")
    con = duckdb.connect()
    query = f"""
    SELECT c.*,o.status,o.entry_date,o.entry_cal_idx,o.entry_price,
      o.exit_date,o.exit_cal_idx,o.exit_price,o.exit_reason,
      o.holding_sessions,o.net_return,
      ch.profit_ratio,ch.trapped_ratio,ch.asr,ch.space20,
      ch.concentration_20,ch.base_retention,ch.p50,ch.p90,ch.mass_sum,
      ch.strict_sample
    FROM read_parquet('{CANDIDATES.as_posix()}') c
    JOIN read_parquet('{OUTCOMES.as_posix()}') o USING(event_id)
    LEFT JOIN read_parquet({chip_sql_paths()}) ch
      ON c.symbol=ch.symbol AND CAST(c.signal_date AS DATE)=ch.trade_date
    ORDER BY c.signal_date,c.symbol,c.event_id
    """
    frame = con.execute(query).fetchdf()
    con.close()
    if len(frame) != 384 or frame.event_id.nunique() != 384:
        raise ReviewError(f"expected 384 frozen signals, got {len(frame)}")
    frame["signal_date"] = pd.to_datetime(frame.signal_date)
    frame["entry_date"] = pd.to_datetime(frame.entry_date)
    frame["exit_date"] = pd.to_datetime(frame.exit_date)
    cluster = frame.groupby("signal_date").size()
    frame["same_date_signals"] = frame.signal_date.map(cluster).astype(int)
    frame["outcome_bucket"] = [
        charts.outcome_bucket(status, charts.safe_float(value))
        for status, value in zip(frame.status, frame.net_return, strict=True)
    ]
    frame["chart_number"] = np.arange(1, len(frame) + 1, dtype=int)
    return frame


def load_windows(ledger: pd.DataFrame) -> pd.DataFrame:
    con = duckdb.connect()
    con.execute("SET threads=8")
    con.register(
        "candidate_ids",
        ledger[["event_id", "symbol", "signal_cal_idx", "signal_date"]],
    )
    query = f"""
    WITH daily AS (
      SELECT symbol,trade_date,cal_idx,coord_open,coord_high,coord_low,coord_close,
        turnover_fraction,current_day_data_tradable,current_valid,hard_valid,
        available_at,decision_at
      FROM read_parquet('{OLD_DAILY.as_posix()}')
      WHERE trade_date<DATE '2022-01-04'
      UNION ALL
      SELECT symbol,CAST(trade_date AS DATE),cal_idx,coord_open,coord_high,coord_low,coord_close,
        turnover_fraction,current_day_data_tradable,current_valid,hard_valid,
        available_at,decision_at
      FROM read_parquet('{EXACT_DAILY.as_posix()}')
      WHERE trade_date BETWEEN DATE '2022-01-04' AND DATE '2025-03-31'
    )
    SELECT c.event_id,c.signal_date,d.*
    FROM candidate_ids c
    JOIN daily d
      ON c.symbol=d.symbol
     AND d.cal_idx BETWEEN c.signal_cal_idx-120 AND c.signal_cal_idx+120
    ORDER BY c.event_id,d.cal_idx
    """
    frame = con.execute(query).fetchdf()
    con.close()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    frame["signal_date"] = pd.to_datetime(frame.signal_date)
    if frame.event_id.nunique() != len(ledger):
        raise ReviewError("chart windows miss event identities")
    return frame


def render(event: pd.Series, frame: pd.DataFrame, output: Path) -> None:
    signal_date = pd.Timestamp(event.signal_date)
    signal_rows = frame.loc[frame.trade_date.eq(signal_date)]
    if len(signal_rows) != 1:
        raise ReviewError(f"{event.event_id}: signal row count {len(signal_rows)}")
    signal_close = float(signal_rows.iloc[0].coord_close)
    figure, (price_ax, volume_ax) = charts.plt.subplots(
        2,
        1,
        figsize=(13.4, 7.6),
        gridspec_kw={"height_ratios": [4.5, 1.0], "hspace": 0.05},
        sharex=True,
    )
    charts.draw_candles(price_ax, frame, signal_close)
    signal_x = charts.mdates.date2num(signal_date.to_pydatetime())
    price_ax.axvline(signal_x, color="#1f77b4", linewidth=1.25, label="signal close")
    price_ax.axhline(100.0, color="#1f77b4", linewidth=0.8, linestyle=":")
    platform_y = float(event.platform_width)
    if math.isfinite(platform_y):
        price_ax.axhline(100.0 / (1.0 + platform_y), color="#777777", linewidth=0.7, linestyle="--", label="platform width guide")
    if pd.notna(event.entry_date) and math.isfinite(float(event.entry_price)):
        entry_x = charts.mdates.date2num(pd.Timestamp(event.entry_date).to_pydatetime())
        entry_y = float(event.entry_price) * 100.0 / signal_close
        price_ax.scatter(entry_x, entry_y, marker="^", s=70, color="#7b2cbf", zorder=8, label="entry")
        price_ax.axhline(entry_y * 1.10, color="#ff7f0e", linewidth=0.8, linestyle="--", label="+10% target")
    if pd.notna(event.exit_date) and math.isfinite(float(event.exit_price)):
        exit_x = charts.mdates.date2num(pd.Timestamp(event.exit_date).to_pydatetime())
        exit_y = float(event.exit_price) * 100.0 / signal_close
        price_ax.scatter(exit_x, exit_y, marker="v", s=70, color="#111111", zorder=8, label="exit")

    status = str(event.outcome_bucket)
    if math.isfinite(charts.safe_float(event.net_return)):
        status += f" | net {float(event.net_return):+.2%} | hold {int(event.holding_sessions)} | {event.exit_reason}"
    chip = (
        f"chip profit {float(event.profit_ratio):.0%} | ASR {float(event.asr):.2f} | space20 {float(event.space20):.2f}"
        if pd.notna(event.profit_ratio) and pd.notna(event.asr) and pd.notna(event.space20)
        else "chip unavailable"
    )
    title = (
        f"{int(event.chart_number):04d} | {event.symbol} | {event.causal_industry} | "
        f"signal {signal_date.date()} | {status}\n"
        f"platform {float(event.platform_width):.1%} | contraction {float(event.turnover_contraction):.2f}x | "
        f"gap {float(event.open_gap):+.1%} | turn {float(event.turnover_expansion):.1f}x | "
        f"large-up120 {int(event.large_up_days120)} | market60 {float(event.market_median_ret60):+.1%} | "
        f"same-date {int(event.same_date_signals)} | {chip}"
    )
    price_ax.set_title(title, fontsize=9.7, fontproperties=CJK_FONT)
    price_ax.set_ylabel("Coordinate price (signal close=100)")
    price_ax.grid(alpha=0.17, linewidth=0.5)
    handles, labels = price_ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles, strict=False))
    price_ax.legend(by_label.values(), by_label.keys(), loc="upper left", ncol=5, fontsize=7.2)

    valid_turn = frame.loc[frame.turnover_fraction.notna()]
    turn_dates = charts.mdates.date2num(pd.to_datetime(valid_turn.trade_date).to_numpy())
    volume_ax.bar(turn_dates, valid_turn.turnover_fraction * 100.0, width=0.75, color="#8b8b8b", alpha=0.55)
    volume_ax.axvline(signal_x, color="#1f77b4", linewidth=1.0)
    volume_ax.set_ylabel("Turnover %")
    volume_ax.grid(alpha=0.12, linewidth=0.4)
    volume_ax.xaxis.set_major_locator(charts.mdates.MonthLocator(interval=2))
    volume_ax.xaxis.set_major_formatter(charts.mdates.DateFormatter("%Y-%m"))
    for label in volume_ax.get_xticklabels():
        label.set_rotation(25)
        label.set_horizontalalignment("right")
    figure.subplots_adjust(left=0.065, right=0.985, top=0.87, bottom=0.10)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=115, bbox_inches="tight", facecolor="white")
    charts.plt.close(figure)


def worker(payload: tuple[dict[str, Any], pd.DataFrame, str]) -> dict[str, Any]:
    event_dict, frame, output_text = payload
    event = pd.Series(event_dict)
    output = Path(output_text)
    render(event, frame, output)
    return {
        "chart_number": int(event.chart_number),
        "event_id": str(event.event_id),
        "symbol": str(event.symbol),
        "signal_date": pd.Timestamp(event.signal_date),
        "outcome_bucket": str(event.outcome_bucket),
        "net_return": charts.safe_float(event.net_return),
        "same_date_signals": int(event.same_date_signals),
        "chart_path": str(output),
    }


def run(workers: int = 8) -> dict[str, Any]:
    for path in (CANDIDATES, OUTCOMES, OLD_DAILY, EXACT_DAILY, *CHIP_PATHS):
        if not path.is_file():
            raise ReviewError(f"missing input {path}")
    configure_helper()
    ledger = load_ledger()
    windows = load_windows(ledger)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.register("window_frame", windows)
    con.register("ledger_frame", ledger)
    con.execute(f"COPY window_frame TO '{WINDOW_PANEL.as_posix()}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.execute(f"COPY ledger_frame TO '{REVIEW_LEDGER.as_posix()}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.close()
    groups = {event_id: part for event_id, part in windows.groupby("event_id", sort=False)}
    tasks = []
    for _, event in ledger.iterrows():
        path = CHART_DIR / f"{int(event.chart_number):04d}_{event.symbol.replace('.', '_')}_{event.signal_date:%Y%m%d}.png"
        tasks.append((event.to_dict(), groups[str(event.event_id)], str(path)))
    with ProcessPoolExecutor(max_workers=max(1, workers)) as pool:
        rows = list(pool.map(worker, tasks, chunksize=1))
    index = pd.DataFrame(rows)
    index.to_csv(CHART_INDEX, index=False)
    sheets = charts.build_contact_sheets(index)
    outcome_sheets = charts.build_outcome_review_sheets(index)
    manifest = {
        "experiment": EXPERIMENT,
        "signals": len(ledger),
        "completed": int(ledger.status.eq("COMPLETED").sum()),
        "charts": len(index),
        "contact_sheets": len(sheets),
        "outcome_sheets": len(outcome_sheets),
        "window": {"pre_sessions": 120, "post_sessions": 120},
        "signal_dates": int(ledger.signal_date.nunique()),
        "maximum_same_date_signals": int(ledger.same_date_signals.max()),
        "candidate_sha256": sha256(CANDIDATES),
        "outcome_sha256": sha256(OUTCOMES),
        "window_panel_sha256": sha256(WINDOW_PANEL),
        "review_ledger_sha256": sha256(REVIEW_LEDGER),
        "chart_index_sha256": sha256(CHART_INDEX),
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
