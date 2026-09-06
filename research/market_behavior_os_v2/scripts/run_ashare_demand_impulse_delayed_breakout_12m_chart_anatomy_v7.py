#!/usr/bin/env python3
"""Render every 2014-2020 frozen demand-impulse delayed-breakout chart."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
from PIL import Image, ImageDraw

import run_ashare_panic_absorption_12m_chart_rule_discovery_v1 as charts


ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-DEMAND-IMPULSE-DELAYED-BREAKOUT-12M-CHART-ANATOMY-V7"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
EXPECTED_FREEZE_SHA256 = "483684bf8c0c0501974e3f245e336cda8f0a65729af0daa99e3265326a15d3c8"

SOURCE_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_demand_impulse_inside_day_delayed_breakout_v5"
)
CANDIDATES = SOURCE_ROOT / "stage_a/candidates_development_2014_2021_frozen.parquet"
DISCOVERY_OUTCOMES = SOURCE_ROOT / "stage_b/discovery_outcomes.parquet"
CONFIRMATION_OUTCOMES = SOURCE_ROOT / "stage_b/confirmation_outcomes.parquet"
DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
REGIME = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_causal_market_regime_routed_simple_strategy_v1/"
    "stage_a/causal_market_regime_2014_2023.parquet"
)
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_demand_impulse_delayed_breakout_12m_chart_anatomy_v7/"
    "development_2014_2020"
)
CHART_DIR = EXT_ROOT / "individual_charts"
SHEET_DIR = EXT_ROOT / "contact_sheets"
OUTCOME_SHEET_ROOT = EXT_ROOT / "review_sheets_by_outcome"
WINDOW_PANEL = EXT_ROOT / "chart_window_panel.parquet"
REVIEW_LEDGER = EXT_ROOT / "review_ledger.parquet"
REVIEW_CSV = EXT_ROOT / "review_ledger.csv"
CHART_INDEX = EXT_ROOT / "chart_index.csv"
MANIFEST = EXT_ROOT / "manifest.json"

PROFILE = "T15_H30_DELAYED_BREAKOUT"
EXPECTED_SIGNALS = 421
EXPECTED_ANNUAL = {2014: 61, 2015: 144, 2016: 42, 2017: 18, 2018: 29, 2019: 47, 2020: 80}


class ExperimentError(RuntimeError):
    """Fail closed when a frozen identity or chronology contract drifts."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.register("frame", frame)
    connection.execute(
        f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    connection.close()


def configure_chart_module() -> None:
    charts.EXPERIMENT = EXPERIMENT
    charts.DAILY = DAILY
    charts.EXT_ROOT = EXT_ROOT
    charts.CHART_DIR = CHART_DIR
    charts.SHEET_DIR = SHEET_DIR
    charts.OUTCOME_SHEET_ROOT = OUTCOME_SHEET_ROOT
    charts.WINDOW_PANEL = WINDOW_PANEL
    charts.REVIEW_LEDGER = REVIEW_LEDGER
    charts.REVIEW_CSV = REVIEW_CSV
    charts.CHART_INDEX = CHART_INDEX


def load_source() -> tuple[pd.DataFrame, pd.DataFrame]:
    if sha256(FREEZE) != EXPECTED_FREEZE_SHA256:
        raise ExperimentError("frozen chart-anatomy specification drift")
    connection = duckdb.connect()
    candidates = connection.execute(
        f"""
        WITH source AS (
          SELECT * FROM read_parquet('{CANDIDATES.as_posix()}')
          WHERE signal_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
        ), enriched AS (
          SELECT s.*,d.turnover_fraction,d.step_return,d.ret20,d.ret60,
            d.coord_open/d.prior_coord_close-1 AS open_gap,
            CASE WHEN d.coord_high>d.coord_low
              THEN (d.coord_close-d.coord_low)/(d.coord_high-d.coord_low)
              ELSE NULL END AS close_location,
            (SELECT avg(p.turnover_fraction)
             FROM read_parquet('{DAILY.as_posix()}') p
             WHERE p.symbol=s.symbol
               AND p.cal_idx BETWEEN s.cal_idx-20 AND s.cal_idx-1
               AND p.current_valid) AS turn20
          FROM source s
          JOIN read_parquet('{DAILY.as_posix()}') d
            ON d.symbol=s.symbol AND d.cal_idx=s.cal_idx
        )
        SELECT e.*,r.market_regime,r.market_median_ret20,
          r.market_positive_ret20_share,r.market_median_ret60,
          r.market_positive_ret60_share,
          r.market_median_ret20-r.market_median_ret60 AS market_return_acceleration,
          r.market_positive_ret20_share-r.market_positive_ret60_share
            AS market_breadth_acceleration
        FROM enriched e
        JOIN read_parquet('{REGIME.as_posix()}') r
          ON CAST(e.signal_date AS DATE)=r.trade_date
        ORDER BY e.signal_date,e.sleeve,e.symbol,e.event_id
        """
    ).fetch_df()
    outcomes = connection.execute(
        f"""
        SELECT * FROM read_parquet([
          '{DISCOVERY_OUTCOMES.as_posix()}',
          '{CONFIRMATION_OUTCOMES.as_posix()}'
        ])
        WHERE profile='{PROFILE}' AND signal_date<=DATE '2020-12-31'
        ORDER BY signal_date,sleeve,symbol,event_id
        """
    ).fetch_df()
    connection.close()
    for frame in (candidates, outcomes):
        for column in ("signal_date", "entry_date", "exit_date", "setup_date"):
            if column in frame:
                frame[column] = pd.to_datetime(frame[column])
    if len(candidates) != EXPECTED_SIGNALS or candidates.event_id.nunique() != EXPECTED_SIGNALS:
        raise ExperimentError(f"expected {EXPECTED_SIGNALS} identities, got {len(candidates)}")
    annual = candidates.groupby(candidates.signal_date.dt.year).size().to_dict()
    if annual != EXPECTED_ANNUAL:
        raise ExperimentError(f"annual identity drift: {annual}")
    if candidates.available_at.gt(candidates.decision_at).any():
        raise ExperimentError("candidate availability exceeds decision time")
    if candidates[["turnover_fraction", "turn20", "ret20", "ret60"]].isna().any().any():
        raise ExperimentError("required causal chart descriptor missing")
    if outcomes.signal_date.max() > pd.Timestamp("2020-12-31"):
        raise ExperimentError("post-2020 outcome entered visual discovery")
    return candidates, outcomes


def render_chart(event: pd.Series, frame: pd.DataFrame, output: Path) -> None:
    signal_date = pd.Timestamp(event.signal_date)
    signal = frame.loc[frame.trade_date.eq(signal_date)]
    if len(signal) != 1:
        raise ExperimentError(f"{event.event_id}: signal row not unique")
    signal_close = float(signal.iloc[0].coord_close)
    figure, (price_ax, volume_ax) = charts.plt.subplots(
        2,
        1,
        figsize=(13.2, 7.4),
        gridspec_kw={"height_ratios": [4.4, 1.0], "hspace": 0.05},
        sharex=True,
    )
    charts.draw_candles(price_ax, frame, signal_close)
    signal_x = charts.mdates.date2num(signal_date.to_pydatetime())
    setup_date = pd.Timestamp(event.setup_date)
    setup_x = charts.mdates.date2num(setup_date.to_pydatetime())
    price_ax.axvline(setup_x, color="#d97706", linewidth=1.0, linestyle="--", label="inside-day setup")
    price_ax.axvline(signal_x, color="#1f77b4", linewidth=1.25, label="delayed breakout")
    price_ax.axhline(100.0, color="#1f77b4", linewidth=0.7, linestyle=":")
    for level, color, label in (
        (event.setup_high_coord, "#777777", "frozen inside high"),
        (event.setup_low_coord, "#aaaaaa", "frozen inside low"),
    ):
        if math.isfinite(float(level)):
            price_ax.axhline(float(level) * 100.0 / signal_close, color=color, linewidth=0.65, linestyle="--", label=label)
    if pd.notna(event.entry_date) and math.isfinite(float(event.entry_price)):
        entry_x = charts.mdates.date2num(pd.Timestamp(event.entry_date).to_pydatetime())
        price_ax.scatter(entry_x, float(event.entry_price) * 100.0 / signal_close, marker="^", s=65, color="#7b2cbf", zorder=8, label="entry")
        price_ax.axhline(float(event.entry_price) * 1.15 * 100.0 / signal_close, color="#ff7f0e", linewidth=0.75, linestyle="--", label="+15% target")
    if pd.notna(event.exit_date) and math.isfinite(float(event.exit_price)):
        exit_x = charts.mdates.date2num(pd.Timestamp(event.exit_date).to_pydatetime())
        price_ax.scatter(exit_x, float(event.exit_price) * 100.0 / signal_close, marker="v", s=65, color="#111111", zorder=8, label="exit")
    state = str(event.market_regime)
    if state == "BULL":
        state += "_ACCEL" if float(event.market_return_acceleration) >= 0 else "_DECEL"
    status = str(event.outcome_bucket)
    if math.isfinite(float(event.net_return)):
        status += f" | net {float(event.net_return):+.2%} | {event.exit_reason}"
    price_ax.set_title(
        f"{int(event.chart_number):04d} | {event.symbol} | {signal_date.date()} | {state} | {status}\n"
        f"impulse3 {float(event.impulse3):+.1%} | pre-impulse r60 {float(event.pre_impulse_ret60):+.1%} | "
        f"setup→break {int(event.cal_idx-event.setup_cal_idx)}d | market r20/r60 "
        f"{float(event.market_median_ret20):+.1%}/{float(event.market_median_ret60):+.1%} | "
        f"same-date {int(event.cluster_signal_count)}",
        fontsize=10.0,
    )
    price_ax.set_ylabel("Coordinate price (signal close=100)")
    price_ax.grid(alpha=0.17, linewidth=0.5)
    handles, labels = price_ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles, strict=False))
    price_ax.legend(by_label.values(), by_label.keys(), loc="upper left", ncol=6, fontsize=7.0)
    valid_turn = frame.loc[frame.turnover_fraction.notna()].copy()
    turn_dates = charts.mdates.date2num(pd.to_datetime(valid_turn.trade_date).to_numpy())
    volume_ax.bar(turn_dates, valid_turn.turnover_fraction * 100.0, width=0.75, color="#8b8b8b", alpha=0.55)
    volume_ax.axvline(setup_x, color="#d97706", linewidth=0.9, linestyle="--")
    volume_ax.axvline(signal_x, color="#1f77b4", linewidth=1.0)
    volume_ax.set_ylabel("Turnover %")
    volume_ax.grid(alpha=0.12, linewidth=0.4)
    volume_ax.xaxis.set_major_locator(charts.mdates.MonthLocator(interval=2))
    volume_ax.xaxis.set_major_formatter(charts.mdates.DateFormatter("%Y-%m"))
    for label in volume_ax.get_xticklabels():
        label.set_rotation(25)
        label.set_horizontalalignment("right")
    figure.subplots_adjust(left=0.065, right=0.985, top=0.88, bottom=0.10)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=115, bbox_inches="tight", facecolor="white", metadata={"Creator": EXPERIMENT, "Title": str(event.event_id)})
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
        "outcome_bucket": str(event.outcome_bucket),
        "net_return": charts.safe_float(event.net_return),
        "chart_path": str(output),
    }


def build_nine_up_sheets(index: pd.DataFrame, root: Path, prefix: str) -> list[Path]:
    root.mkdir(parents=True, exist_ok=True)
    rows = index.to_dict("records")
    paths: list[Path] = []
    for start in range(0, len(rows), 9):
        group = rows[start : start + 9]
        canvas = Image.new("RGB", (3600, 2130), "white")
        draw = ImageDraw.Draw(canvas)
        for offset, row in enumerate(group):
            source = Image.open(row["chart_path"]).convert("RGB")
            source.thumbnail((1180, 680), Image.Resampling.LANCZOS)
            x = 10 + (offset % 3) * 1195
            y = 35 + (offset // 3) * 695
            canvas.paste(source, (x, y))
            source.close()
        sheet_no = start // 9 + 1
        draw.text((15, 8), f"{prefix} | sheet {sheet_no:03d} | events {start+1}-{start+len(group)}", fill="black")
        target = root / f"sheet_{sheet_no:03d}.jpg"
        canvas.save(target, "JPEG", quality=90, optimize=True)
        paths.append(target)
    return paths


def run(workers: int) -> dict[str, Any]:
    for path in (FREEZE, CANDIDATES, DISCOVERY_OUTCOMES, CONFIRMATION_OUTCOMES, DAILY, REGIME):
        if not path.is_file():
            raise ExperimentError(f"missing required input {path}")
    configure_chart_module()
    candidates, outcomes = load_source()
    windows = charts.load_windows(candidates)
    ledger = charts.build_ledger(candidates, outcomes, windows)
    extras = candidates[[
        "event_id", "cal_idx", "setup_date", "setup_cal_idx", "setup_high_coord", "setup_low_coord",
        "impulse3", "pre_impulse_ret60", "market_regime", "market_median_ret20",
        "market_positive_ret20_share", "market_median_ret60", "market_positive_ret60_share",
        "market_return_acceleration", "market_breadth_acceleration",
    ]]
    ledger = ledger.merge(extras, on="event_id", how="left", validate="one_to_one")
    write_parquet(windows, WINDOW_PANEL)
    write_parquet(ledger, REVIEW_LEDGER)
    REVIEW_CSV.parent.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(REVIEW_CSV, index=False, float_format="%.10g")
    groups = {key: part for key, part in windows.groupby("event_id", sort=False)}
    tasks: list[tuple[dict[str, Any], pd.DataFrame, str]] = []
    for _, event in ledger.iterrows():
        target = CHART_DIR / f"{int(event.chart_number):04d}_{event.symbol.replace('.', '_')}_{pd.Timestamp(event.signal_date):%Y%m%d}.png"
        tasks.append((event.to_dict(), groups[str(event.event_id)], str(target)))
    with ProcessPoolExecutor(max_workers=max(1, workers)) as executor:
        index = pd.DataFrame(list(executor.map(render_worker, tasks, chunksize=1)))
    index.to_csv(CHART_INDEX, index=False, float_format="%.10g")
    contact = build_nine_up_sheets(index, SHEET_DIR, EXPERIMENT)
    outcome_paths: list[Path] = []
    for bucket in ("SEVERE_LOSS", "LOSS_0_TO_10PCT", "PROFIT_0_TO_4PCT", "PROFIT_GE_4PCT", "NO_COMPLETED_TRADE"):
        subset = index.loc[index.outcome_bucket.eq(bucket)].sort_values(["signal_date", "symbol", "event_id"], kind="mergesort")
        outcome_paths.extend(build_nine_up_sheets(subset, OUTCOME_SHEET_ROOT / bucket.lower(), bucket))
    complete = ledger.loc[ledger.status.eq("COMPLETED")].copy()
    manifest = {
        "experiment": EXPERIMENT,
        "freeze_sha256": sha256(FREEZE),
        "signals": len(ledger),
        "completed": len(complete),
        "charts": len(index),
        "contact_sheets": len(contact),
        "outcome_sheets": len(outcome_paths),
        "signal_dates": int(ledger.signal_date.nunique()),
        "symbols": int(ledger.symbol.nunique()),
        "annual_signals": {str(year): int(value) for year, value in ledger.groupby(ledger.signal_date.dt.year).size().items()},
        "outcome_buckets": {str(key): int(value) for key, value in ledger.outcome_bucket.value_counts().items()},
        "pooled_mean_net": float(complete.net_return.mean()),
        "pooled_median_net": float(complete.net_return.median()),
        "max_signal_date": str(ledger.signal_date.max().date()),
        "max_chart_bar_date": str(pd.to_datetime(windows.trade_date).max().date()),
        "2021_plus_signal_or_outcome_read": "NO",
        "2022_plus_read": "NO",
        "review_ledger_sha256": sha256(REVIEW_LEDGER),
        "chart_index_sha256": sha256(CHART_INDEX),
    }
    charts.canonical_json(MANIFEST, manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    print(json.dumps(run(args.workers), ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
