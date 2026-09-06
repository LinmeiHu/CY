#!/usr/bin/env python3
"""Render the frozen 2014-2020 V27 trade-anatomy chart corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

from research.market_behavior_os_v2.scripts import (
    run_ashare_panic_absorption_12m_chart_rule_discovery_v1 as charts,
)


EXPERIMENT = "ASHARE-CAUSAL-MARKET-REGIME-SUBSTRATEGY-ROUTER-V27-TRADE-CHART-ANATOMY-V1"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
V27_ROOT = Path("/Volumes/quant/CY_quant_research/ashare_causal_market_regime_substrategy_router_v27")
TRADES = V27_ROOT / "accepted_trades.parquet"
V27_RESULT = V27_ROOT / "result.json"
DAILY = Path(
    "/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
OUT = V27_ROOT / "stage_trade_chart_anatomy_v1"
WINDOWS = OUT / "chart_window_panel.parquet"
LEDGER = OUT / "review_ledger.parquet"
LEDGER_CSV = OUT / "review_ledger.csv"
CHART_DIR = OUT / "individual_charts"
CHRONO_DIR = OUT / "contact_sheets_chronological"
OUTCOME_DIR = OUT / "contact_sheets_by_outcome"
CHART_INDEX = OUT / "chart_index.csv"
MANIFEST = OUT / "manifest.json"

SIGNAL_START = pd.Timestamp("2014-01-01")
SIGNAL_END = pd.Timestamp("2020-12-31")
MAX_CONTEXT_DATE = pd.Timestamp("2021-06-30")
EXPECTED_TRADES = 809
EXPECTED_BY_YEAR = {2014: 57, 2015: 129, 2016: 102, 2017: 71, 2018: 259, 2019: 28, 2020: 163}
EXPECTED_BY_LANE = {
    "BEAR_STABILIZING_SLOW_SUPPLY_EXHAUSTION": 444,
    "BEAR_WORSENING_FAST_CAPITULATION": 100,
    "BULL_ACCELERATING_DELAYED_SUPPLY_CONTRACTION": 54,
    "BULL_DECELERATING_QUIET_INVENTORY": 211,
}
EXPECTED_HASHES = {
    SPEC: "00acf923865287b37a891f3b23eb331989f2ee81e860958f1ddcb2205ba52a14",
    TRADES: "73ed476190c29044cae79c2d0f9e38c11f0ddf2ba200e756f240131d8e9143ea",
    V27_RESULT: "d50ea992529a2a202d8d17ed7eb5dc0908291224a74948616aa84a39fcf65537",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
}


class ResearchError(RuntimeError):
    """Fail closed on frozen identity or chronology drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.register("frame", frame)
    connection.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    connection.close()


def verify_inputs() -> dict[str, str]:
    actual: dict[str, str] = {}
    for path, expected in EXPECTED_HASHES.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input: {path}")
        actual[str(path)] = sha256(path)
        if actual[str(path)] != expected:
            raise ResearchError(f"frozen input drift: {path}")
    result = json.loads(V27_RESULT.read_text(encoding="utf-8"))
    if result.get("experiment") != "ASHARE-CAUSAL-MARKET-REGIME-SUBSTRATEGY-ROUTER-V27":
        raise ResearchError("unexpected V27 result identity")
    return actual


def outcome_group(net_return: float) -> str:
    if net_return >= 0.04:
        return "PROFIT_GE_4PCT"
    if net_return >= 0:
        return "PROFIT_0_TO_4PCT"
    if net_return > -0.10:
        return "LOSS_0_TO_10PCT"
    return "SEVERE_LOSS"


def load_development_trades() -> pd.DataFrame:
    frame = duckdb.sql(
        f"""
        SELECT * FROM read_parquet('{TRADES.as_posix()}')
        WHERE signal_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
        ORDER BY signal_date,lane,symbol,event_id
        """
    ).df()
    for column in ("signal_date", "entry_date", "exit_date", "latest_source_timestamp"):
        frame[column] = pd.to_datetime(frame[column])
    if len(frame) != EXPECTED_TRADES or frame.event_id.nunique() != EXPECTED_TRADES:
        raise ResearchError("development trade identity drift")
    if frame.signal_date.min() < SIGNAL_START or frame.signal_date.max() > SIGNAL_END:
        raise ResearchError("later trade row entered development corpus")
    by_year = frame.signal_date.dt.year.value_counts().sort_index().to_dict()
    by_lane = frame.lane.value_counts().sort_index().to_dict()
    if by_year != EXPECTED_BY_YEAR or by_lane != EXPECTED_BY_LANE:
        raise ResearchError("development trade counts drift")
    if (frame.entry_date <= frame.signal_date).any() or (frame.exit_date <= frame.entry_date).any():
        raise ResearchError("same-bar or nonpositive lifecycle detected")
    return frame


def load_chart_windows() -> pd.DataFrame:
    query = f"""
    WITH trades AS (
      SELECT event_id,symbol,signal_date
      FROM read_parquet('{TRADES.as_posix()}')
      WHERE signal_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
    ), signals AS (
      SELECT t.event_id,t.symbol,t.signal_date,d.cal_idx AS signal_cal_idx,
             d.coord_close AS signal_coord_close
      FROM trades t
      JOIN read_parquet('{DAILY.as_posix()}') d
        ON d.symbol=t.symbol AND d.trade_date=t.signal_date
      WHERE d.hard_valid AND d.coord_close>0
    )
    SELECT s.event_id,s.signal_date,s.signal_cal_idx,s.signal_coord_close,
           d.trade_date,d.cal_idx,d.coord_open,d.coord_high,d.coord_low,d.coord_close,
           d.turnover_fraction,d.ret20,d.ret60,d.ret120,d.rolling_drawdown120,
           CASE WHEN d.coord_high>d.coord_low
                THEN (d.coord_close-d.coord_low)/(d.coord_high-d.coord_low)
                ELSE 0.5 END AS close_location,
           d.step_return,d.large_up_days120,d.board_ret60_percentile,
           d.hard_valid,d.current_valid,d.history_valid,
           d.available_at,d.decision_at,d.invalid_step_cum
    FROM signals s
    JOIN read_parquet('{DAILY.as_posix()}') d
      ON d.symbol=s.symbol
     AND d.cal_idx BETWEEN s.signal_cal_idx-126 AND s.signal_cal_idx+126
     AND d.trade_date<=DATE '2021-06-30'
    ORDER BY s.event_id,d.cal_idx
    """
    frame = duckdb.sql(query).df()
    for column in ("signal_date", "trade_date", "available_at", "decision_at"):
        frame[column] = pd.to_datetime(frame[column])
    if frame.event_id.nunique() != EXPECTED_TRADES:
        raise ResearchError("chart windows miss a frozen development trade")
    if frame.trade_date.max() > MAX_CONTEXT_DATE:
        raise ResearchError("chart context exceeds frozen date cap")
    if frame.loc[frame.trade_date.eq(frame.signal_date), "event_id"].nunique() != EXPECTED_TRADES:
        raise ResearchError("signal row is missing or duplicated")
    return frame


def build_review_ledger(trades: pd.DataFrame, windows: pd.DataFrame) -> pd.DataFrame:
    signal = windows.loc[windows.trade_date.eq(windows.signal_date)].copy()
    if signal.event_id.duplicated().any():
        raise ResearchError("duplicate signal feature row")
    signal = signal[
        [
            "event_id",
            "signal_cal_idx",
            "signal_coord_close",
            "ret20",
            "ret60",
            "ret120",
            "rolling_drawdown120",
            "close_location",
            "turnover_fraction",
            "large_up_days120",
            "board_ret60_percentile",
        ]
    ]
    ledger = trades.merge(signal, on="event_id", how="left", validate="one_to_one")
    ledger = ledger.sort_values(["signal_date", "lane", "symbol", "event_id"], kind="mergesort").reset_index(drop=True)
    ledger["chart_number"] = np.arange(1, len(ledger) + 1, dtype=int)
    ledger["signal_year"] = ledger.signal_date.dt.year.astype(int)
    ledger["signal_to_entry_sessions"] = ledger.entry_cal_idx.astype(int) - ledger.signal_cal_idx.astype(int)
    ledger["target_return"] = np.where(
        ledger.lane.eq("BULL_DECELERATING_QUIET_INVENTORY"), 0.15, 0.10
    )
    ledger["outcome_group"] = ledger.net_return.map(outcome_group)
    ledger["reviewed_chronologically"] = False
    ledger["pre_entry_visual_note"] = ""
    ledger["post_entry_visual_note"] = ""
    return ledger


def render_chart(event: pd.Series, frame: pd.DataFrame, output: Path) -> None:
    signal_date = pd.Timestamp(event.signal_date)
    signal_close = float(event.signal_coord_close)
    figure, (price_ax, volume_ax) = charts.plt.subplots(
        2,
        1,
        figsize=(13.2, 7.4),
        gridspec_kw={"height_ratios": [4.4, 1.0], "hspace": 0.05},
        sharex=True,
    )
    charts.draw_candles(price_ax, frame, signal_close)
    markers = (
        (signal_date, "#b45309", "signal close"),
        (pd.Timestamp(event.entry_date), "#7b2cbf", "entry open"),
        (pd.Timestamp(event.exit_date), "#111111", "exit open"),
    )
    for date, color, label in markers:
        price_ax.axvline(charts.mdates.date2num(date.to_pydatetime()), color=color, linewidth=1.1, label=label)
    entry_level = float(event.entry_price) * 100.0 / signal_close
    target_level = float(event.entry_price) * (1.0 + float(event.target_return)) * 100.0 / signal_close
    price_ax.axhline(entry_level, color="#7b2cbf", linewidth=0.8, linestyle="--", label="entry coordinate")
    price_ax.axhline(target_level, color="#dc2626", linewidth=0.8, linestyle="--", label="frozen target")
    lane_short = {
        "BEAR_STABILIZING_SLOW_SUPPLY_EXHAUSTION": "BEAR_STABLE_SLOW",
        "BEAR_WORSENING_FAST_CAPITULATION": "BEAR_WORSE_FAST",
        "BULL_ACCELERATING_DELAYED_SUPPLY_CONTRACTION": "BULL_ACCEL",
        "BULL_DECELERATING_QUIET_INVENTORY": "BULL_DECEL",
    }[str(event.lane)]
    price_ax.set_title(
        f"{int(event.chart_number):04d} | {event.symbol} | {signal_date.date()} | {lane_short} | "
        f"{event.outcome_group} | net {float(event.net_return):+.1%} | {event.exit_reason}\n"
        f"ret20/60/120 {float(event.ret20):+.1%}/{float(event.ret60):+.1%}/{float(event.ret120):+.1%} | "
        f"drawdown120 {float(event.rolling_drawdown120):+.1%} | close-loc {float(event.close_location):.2f} | "
        f"turn {float(event.turnover_fraction):.2%} | rank {float(event.rank1):+.3f}/{float(event.rank2):+.3f}/{float(event.rank3):+.3f}",
        fontsize=8.2,
    )
    price_ax.set_ylabel("Coordinate price (signal close=100)")
    price_ax.grid(alpha=0.17, linewidth=0.5)
    handles, labels = price_ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles, strict=False))
    price_ax.legend(by_label.values(), by_label.keys(), loc="upper left", ncol=5, fontsize=6.5)

    valid_turn = frame.loc[frame.turnover_fraction.notna()].copy()
    turn_dates = charts.mdates.date2num(pd.to_datetime(valid_turn.trade_date).to_numpy())
    volume_ax.bar(turn_dates, valid_turn.turnover_fraction * 100, width=0.75, color="#8b8b8b", alpha=0.60)
    for date, color, _ in markers:
        volume_ax.axvline(charts.mdates.date2num(date.to_pydatetime()), color=color, linewidth=1.0)
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
        dpi=105,
        bbox_inches="tight",
        facecolor="white",
        metadata={"Creator": EXPERIMENT, "Title": str(event.event_id)},
    )
    charts.plt.close(figure)


def render_worker(payload: tuple[dict[str, Any], pd.DataFrame, str]) -> dict[str, Any]:
    event_dict, frame, target = payload
    event = pd.Series(event_dict)
    output = Path(target)
    if not output.is_file():
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Glyph .* missing from font")
            render_chart(event, frame, output)
    return {
        "chart_number": int(event.chart_number),
        "event_id": str(event.event_id),
        "symbol": str(event.symbol),
        "signal_date": pd.Timestamp(event.signal_date),
        "lane": str(event.lane),
        "outcome_group": str(event.outcome_group),
        "net_return": float(event.net_return),
        "chart_path": str(output),
    }


def build_nine_up(index: pd.DataFrame, output_dir: Path, prefix: str) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    records = index.to_dict("records")
    for start in range(0, len(records), 9):
        group = records[start : start + 9]
        canvas = Image.new("RGB", (3600, 2130), "white")
        draw = ImageDraw.Draw(canvas)
        for offset, row in enumerate(group):
            with Image.open(row["chart_path"]) as source:
                source = source.convert("RGB")
                source.thumbnail((1180, 680), Image.Resampling.LANCZOS)
                canvas.paste(source, (10 + (offset % 3) * 1195, 35 + (offset // 3) * 695))
        number = start // 9 + 1
        draw.text(
            (15, 8),
            f"{EXPERIMENT} | {prefix} | sheet {number:03d} | charts {start + 1}-{start + len(group)}",
            fill="black",
        )
        target = output_dir / f"sheet_{number:03d}.jpg"
        canvas.save(target, "JPEG", quality=90, optimize=True)
        paths.append(target)
    return paths


def run(workers: int) -> dict[str, Any]:
    source_hashes = verify_inputs()
    trades = load_development_trades()
    windows = load_chart_windows()
    ledger = build_review_ledger(trades, windows)
    write_parquet(windows, WINDOWS)
    write_parquet(ledger, LEDGER)
    ledger.to_csv(LEDGER_CSV, index=False, float_format="%.10g")

    groups = {key: part.copy() for key, part in windows.groupby("event_id", sort=False)}
    tasks: list[tuple[dict[str, Any], pd.DataFrame, str]] = []
    for _, event in ledger.iterrows():
        target = CHART_DIR / (
            f"{int(event.chart_number):05d}_{event.symbol.replace('.', '_')}_"
            f"{pd.Timestamp(event.signal_date):%Y%m%d}.png"
        )
        tasks.append((event.to_dict(), groups[str(event.event_id)], str(target)))
    with ProcessPoolExecutor(max_workers=max(1, workers)) as executor:
        index = pd.DataFrame(list(executor.map(render_worker, tasks, chunksize=2)))
    index = index.sort_values("chart_number", kind="mergesort").reset_index(drop=True)
    index.to_csv(CHART_INDEX, index=False, float_format="%.10g")
    chronological = build_nine_up(index, CHRONO_DIR, "CHRONOLOGICAL")
    outcome_sheets: dict[str, int] = {}
    for group in ("PROFIT_GE_4PCT", "PROFIT_0_TO_4PCT", "LOSS_0_TO_10PCT", "SEVERE_LOSS"):
        subset = index.loc[index.outcome_group.eq(group)].copy()
        sheets = build_nine_up(subset, OUTCOME_DIR / group.lower(), group)
        outcome_sheets[group] = len(sheets)
    manifest = {
        "experiment": EXPERIMENT,
        "stage": "FROZEN_DEVELOPMENT_TRADE_CHART_CORPUS",
        "source_hashes": source_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "windows_sha256": sha256(WINDOWS),
        "review_ledger_sha256": sha256(LEDGER),
        "charts": len(index),
        "chronological_contact_sheets": len(chronological),
        "outcome_contact_sheets": outcome_sheets,
        "outcome_counts": index.outcome_group.value_counts().sort_index().to_dict(),
        "by_year": ledger.signal_year.value_counts().sort_index().to_dict(),
        "by_lane": ledger.lane.value_counts().sort_index().to_dict(),
        "all_charts_reviewed": False,
        "rules_frozen": False,
        "maximum_signal_date": str(ledger.signal_date.max().date()),
        "maximum_context_date": str(windows.trade_date.max().date()),
        "post_2020_trade_outcomes_used_for_rule_discovery": False,
        "2024_plus_used_for_rule_discovery": False,
    }
    write_json(MANIFEST, manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    print(json.dumps(run(args.workers), ensure_ascii=False, indent=2, sort_keys=True))
