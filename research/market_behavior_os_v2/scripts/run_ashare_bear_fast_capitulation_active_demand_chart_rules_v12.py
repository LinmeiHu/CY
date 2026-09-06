#!/usr/bin/env python3
"""Render every 2014-2020 V10 mother-event chart for V26-style rule discovery.

The rule-discovery population is the raw V10 signal set before portfolio
capacity selection.  Later signal cohorts are never joined to outcomes here.
"""

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
from PIL import Image, ImageDraw

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402


ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-BEAR-FAST-CAPITULATION-ACTIVE-DEMAND-CHART-RULES-V12"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
FREEZE_SHA256 = "6c90f6d967d4ff8c3a478d639148c2564594d7173edc1892db4c18747ab3af67"

CANDIDATE_SOURCE = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_oversold_stabilized_demand_reversal_v2/stage_a/"
    "candidates_2014_2023_outcome_blind.parquet"
)
REGIME_SOURCE = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_causal_market_regime_routed_simple_strategy_v1/stage_a/"
    "causal_market_regime_2014_2023.parquet"
)
OUTCOME_SOURCE = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_bear_regime_failure_exit_v9/stage_b/policy_outcomes.parquet"
)
DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_bear_fast_capitulation_active_demand_chart_rules_v12"
)
POPULATION = EXT_ROOT / "development_2014_2020/raw_signal_population.parquet"
WINDOW_PANEL = EXT_ROOT / "development_2014_2020/chart_window_panel.parquet"
REVIEW_LEDGER = EXT_ROOT / "development_2014_2020/review_ledger.parquet"
REVIEW_CSV = EXT_ROOT / "development_2014_2020/review_ledger.csv"
CHART_INDEX = EXT_ROOT / "development_2014_2020/chart_index.csv"
CHART_DIR = EXT_ROOT / "development_2014_2020/individual_charts"
SHEET_DIR = EXT_ROOT / "development_2014_2020/contact_sheets"
OUTCOME_SHEET_ROOT = EXT_ROOT / "development_2014_2020/review_sheets_by_outcome"
MANIFEST = EXT_ROOT / "development_2014_2020/manifest.json"

EXPECTED_COUNTS = {
    2014: 2,
    2015: 90,
    2016: 59,
    2017: 32,
    2018: 214,
    2019: 5,
    2020: 45,
}


class ExperimentError(RuntimeError):
    """Fail-closed chart-discovery error."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
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


def load_population() -> pd.DataFrame:
    candidates = pd.read_parquet(CANDIDATE_SOURCE)
    candidates["trade_date"] = pd.to_datetime(candidates.trade_date)
    candidates = candidates.loc[
        candidates.trade_date.between("2014-01-01", "2020-12-31")
    ].copy()

    regime = pd.read_parquet(REGIME_SOURCE)
    regime["trade_date"] = pd.to_datetime(regime.trade_date)
    regime = regime.sort_values("trade_date", kind="mergesort").reset_index(drop=True)
    regime["breadth20_lag5"] = regime.market_positive_ret20_share.shift(5)
    regime["breadth20_change5"] = (
        regime.market_positive_ret20_share - regime.breadth20_lag5
    )
    regime = regime.loc[
        regime.trade_date.between("2014-01-01", "2020-12-31")
    ].copy()

    frame = candidates.merge(
        regime[
            [
                "trade_date",
                "market_median_ret20",
                "market_positive_ret20_share",
                "market_median_ret60",
                "market_positive_ret60_share",
                "latest_source_timestamp",
                "market_regime",
                "breadth20_lag5",
                "breadth20_change5",
            ]
        ],
        on="trade_date",
        how="left",
        validate="many_to_one",
    )
    frame = frame.loc[
        frame.market_regime.eq("BEAR")
        & frame.market_positive_ret20_share.gt(frame.breadth20_lag5)
        & frame.prior10_return.le(-0.08)
    ].copy()
    frame = frame.sort_values(
        ["trade_date", "sleeve", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    actual = frame.groupby(frame.trade_date.dt.year).size().to_dict()
    if actual != EXPECTED_COUNTS:
        raise ExperimentError(f"raw V10 identity drift: {actual}")
    if frame.event_id.duplicated().any():
        raise ExperimentError("duplicate V10 raw event_id")
    if (
        pd.to_datetime(frame.latest_source_timestamp)
        > pd.to_datetime(frame.decision_at)
    ).any():
        raise ExperimentError("market state uses a future source timestamp")

    connection = duckdb.connect()
    outcomes = connection.execute(
        f"""
        SELECT *
        FROM read_parquet('{OUTCOME_SOURCE.as_posix()}')
        WHERE policy='X0_NO_FAILURE'
          AND signal_date<=DATE '2020-12-31'
        """
    ).fetch_df()
    connection.close()
    outcomes["signal_date"] = pd.to_datetime(outcomes.signal_date)
    outcomes = outcomes.rename(
        columns={
            "signal_date": "outcome_signal_date",
            "step_return": "outcome_step_return",
        }
    )
    frame = frame.merge(
        outcomes,
        on=["event_id", "symbol", "sleeve"],
        how="left",
        validate="one_to_one",
        suffixes=("", "_outcome"),
    )
    if int(frame.net_return.notna().sum()) != 446:
        raise ExperimentError("completed outcome coverage drift")
    if pd.to_datetime(frame.outcome_signal_date).dropna().max() > pd.Timestamp(
        "2020-12-31"
    ):
        raise ExperimentError("post-2020 signal outcome entered discovery")
    frame = frame.rename(columns={"trade_date": "signal_date"})
    frame["signal_cal_idx"] = frame.cal_idx.astype(int)
    return frame


def load_windows(population: pd.DataFrame) -> pd.DataFrame:
    ids = population[["event_id", "symbol", "signal_date", "signal_cal_idx"]].copy()
    connection = duckdb.connect()
    connection.register("ids", ids)
    windows = connection.execute(
        f"""
        SELECT i.event_id,i.symbol,i.signal_date,i.signal_cal_idx,
          d.trade_date,d.cal_idx,d.coord_open,d.coord_high,d.coord_low,
          d.coord_close,d.turnover_fraction,d.step_return,d.hard_valid,
          d.current_valid,d.history_valid,d.invalid_step_cum
        FROM ids i
        JOIN read_parquet('{DAILY.as_posix()}') d
          ON i.symbol=d.symbol
         AND d.cal_idx BETWEEN i.signal_cal_idx-120 AND i.signal_cal_idx+120
        ORDER BY i.event_id,d.cal_idx
        """
    ).fetch_df()
    connection.close()
    windows["trade_date"] = pd.to_datetime(windows.trade_date)
    if windows.empty:
        raise ExperimentError("empty chart windows")
    return windows


def classify_outcome(value: Any) -> str:
    if pd.isna(value):
        return "NO_COMPLETED_TRADE"
    net = float(value)
    if net >= 0.04:
        return "TARGET_OR_PROFIT_GE_4PCT"
    if net >= 0.0:
        return "PROFIT_0_TO_4PCT"
    if net > -0.10:
        return "LOSS_0_TO_10PCT"
    return "SEVERE_LOSS"


def build_ledger(population: pd.DataFrame, windows: pd.DataFrame) -> pd.DataFrame:
    groups = {key: part for key, part in windows.groupby("event_id", sort=False)}
    rows: list[dict[str, Any]] = []
    same_date = population.groupby("signal_date").size().to_dict()
    for chart_number, event in enumerate(population.itertuples(index=False), start=1):
        path = groups.get(str(event.event_id))
        if path is None or path.empty:
            raise ExperimentError(f"missing chart path: {event.event_id}")
        before = path.loc[path.cal_idx.lt(int(event.signal_cal_idx))].tail(120)
        if before.empty:
            raise ExperimentError(f"missing pre-signal history: {event.event_id}")
        peak = before.loc[before.coord_high.idxmax()]
        low = before.loc[before.coord_low.idxmin()]
        entry_gap = math.nan
        if pd.notna(event.entry_price):
            entry_gap = float(event.entry_price) / float(event.coord_close) - 1.0
        rows.append(
            {
                **event._asdict(),
                "chart_number": chart_number,
                "outcome_bucket": classify_outcome(event.net_return),
                "same_date_signal_count": int(same_date[pd.Timestamp(event.signal_date)]),
                "pre120_peak_age": int(event.signal_cal_idx) - int(peak.cal_idx),
                "pre120_peak_drawdown": float(event.coord_close) / float(peak.coord_high)
                - 1.0,
                "pre120_low_age": int(event.signal_cal_idx) - int(low.cal_idx),
                "signal_above_pre120_low": float(event.coord_close) / float(low.coord_low)
                - 1.0,
                "entry_gap_from_signal_close": entry_gap,
            }
        )
    ledger = pd.DataFrame(rows)
    return ledger.sort_values("chart_number", kind="mergesort").reset_index(drop=True)


def draw_candles(axis: Any, frame: pd.DataFrame, signal_close: float) -> None:
    dates = mdates.date2num(pd.to_datetime(frame.trade_date).to_numpy())
    scale = 100.0 / signal_close
    for x, row in zip(dates, frame.itertuples(index=False), strict=False):
        opening = float(row.coord_open) * scale
        high = float(row.coord_high) * scale
        low = float(row.coord_low) * scale
        close = float(row.coord_close) * scale
        color = "#d62728" if close >= opening else "#159447"
        axis.vlines(x, low, high, color=color, linewidth=0.5, alpha=0.9)
        bottom = min(opening, close)
        height = max(abs(close - opening), 0.06)
        axis.add_patch(
            Rectangle(
                (x - 0.34, bottom),
                0.68,
                height,
                facecolor=color,
                edgecolor=color,
                linewidth=0.2,
            )
        )
    axis.set_xlim(dates.min() - 3, dates.max() + 3)
    axis.xaxis_date()


def render_chart(event_dict: dict[str, Any], frame: pd.DataFrame, output: str) -> dict[str, Any]:
    event = pd.Series(event_dict)
    signal_date = pd.Timestamp(event.signal_date)
    signal_rows = frame.loc[frame.trade_date.eq(signal_date)]
    if len(signal_rows) != 1:
        raise ExperimentError(f"missing signal candle: {event.event_id}")
    signal_close = float(signal_rows.iloc[0].coord_close)
    figure, (price_ax, volume_ax) = plt.subplots(
        2,
        1,
        figsize=(13.6, 7.6),
        gridspec_kw={"height_ratios": [4.4, 1.0], "hspace": 0.05},
        sharex=True,
    )
    draw_candles(price_ax, frame, signal_close)
    signal_x = mdates.date2num(signal_date.to_pydatetime())
    price_ax.axvspan(
        mdates.date2num((signal_date - pd.Timedelta(days=16)).to_pydatetime()),
        signal_x,
        color="#f2b134",
        alpha=0.08,
        label="fast-liquidation window",
    )
    price_ax.axvline(signal_x, color="#1f77b4", linewidth=1.2, label="signal close")
    price_ax.axhline(100.0, color="#1f77b4", linewidth=0.7, linestyle=":")
    if pd.notna(event.entry_date) and math.isfinite(float(event.entry_price)):
        entry_x = mdates.date2num(pd.Timestamp(event.entry_date).to_pydatetime())
        entry_y = float(event.entry_price) * 100.0 / signal_close
        price_ax.scatter(
            entry_x,
            entry_y,
            marker="^",
            s=65,
            color="#7b2cbf",
            zorder=8,
            label="entry",
        )
        price_ax.axhline(
            float(event.entry_price) * 1.20 * 100.0 / signal_close,
            color="#ff7f0e",
            linewidth=0.75,
            linestyle="--",
            label="+20% target",
        )
    if pd.notna(event.exit_date) and math.isfinite(float(event.exit_price)):
        exit_x = mdates.date2num(pd.Timestamp(event.exit_date).to_pydatetime())
        exit_y = float(event.exit_price) * 100.0 / signal_close
        price_ax.scatter(
            exit_x,
            exit_y,
            marker="v",
            s=65,
            color="#111111",
            zorder=8,
            label="exit",
        )

    net_text = "no completed trade"
    if pd.notna(event.net_return):
        net_text = f"net {float(event.net_return):+.1%} | {event.exit_reason}"
    price_ax.set_title(
        f"{int(event.chart_number):04d} | {event.symbol} | {signal_date.date()} | "
        f"{event.outcome_bucket} | {net_text}\n"
        f"r10 {float(event.prior10_return):+.1%} | r20 {float(event.ret20):+.1%} | "
        f"r60 {float(event.ret60):+.1%} | stock-ind20 {float(event.stock_minus_industry_ret20):+.1%} | "
        f"turn {float(event.turnover_ratio_x):.1f}x | breadth20 "
        f"{float(event.market_positive_ret20_share):.1%} ({float(event.breadth20_change5):+.1%}/5d) | "
        f"same-date {int(event.same_date_signal_count)}",
        fontsize=9.5,
    )
    price_ax.set_ylabel("Coordinate price (signal close=100)")
    price_ax.grid(alpha=0.16, linewidth=0.45)
    handles, labels = price_ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles, strict=False))
    price_ax.legend(
        by_label.values(), by_label.keys(), loc="upper left", ncol=5, fontsize=7.2
    )

    valid_turn = frame.loc[frame.turnover_fraction.notna()].copy()
    turn_dates = mdates.date2num(pd.to_datetime(valid_turn.trade_date).to_numpy())
    volume_ax.bar(
        turn_dates,
        valid_turn.turnover_fraction * 100.0,
        width=0.75,
        color="#888888",
        alpha=0.55,
    )
    volume_ax.axvline(signal_x, color="#1f77b4", linewidth=1.0)
    volume_ax.set_ylabel("Turnover %")
    volume_ax.grid(alpha=0.12, linewidth=0.4)
    volume_ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    volume_ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    for label in volume_ax.get_xticklabels():
        label.set_rotation(25)
        label.set_horizontalalignment("right")
    figure.subplots_adjust(left=0.065, right=0.985, top=0.88, bottom=0.10)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=120, bbox_inches="tight", facecolor="white")
    plt.close(figure)
    return {
        "chart_number": int(event.chart_number),
        "event_id": str(event.event_id),
        "symbol": str(event.symbol),
        "signal_date": signal_date,
        "outcome_bucket": str(event.outcome_bucket),
        "net_return": None if pd.isna(event.net_return) else float(event.net_return),
        "chart_path": str(path),
    }


def render_worker(payload: tuple[dict[str, Any], pd.DataFrame, str]) -> dict[str, Any]:
    return render_chart(*payload)


def make_sheets(index: pd.DataFrame, target: Path, label: str) -> list[Path]:
    target.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    rows = index.to_dict("records")
    for start in range(0, len(rows), 4):
        group = rows[start : start + 4]
        canvas = Image.new("RGB", (2500, 1480), "white")
        draw = ImageDraw.Draw(canvas)
        for offset, row in enumerate(group):
            source = Image.open(row["chart_path"]).convert("RGB")
            source.thumbnail((1230, 700), Image.Resampling.LANCZOS)
            x = 10 + (offset % 2) * 1240
            y = 35 + (offset // 2) * 715
            canvas.paste(source, (x, y))
            source.close()
        sheet_number = start // 4 + 1
        draw.text(
            (15, 8),
            f"{label} | sheet {sheet_number:03d} | events {start + 1}-{start + len(group)}",
            fill="black",
        )
        path = target / f"sheet_{sheet_number:03d}.jpg"
        canvas.save(path, "JPEG", quality=90, optimize=True)
        paths.append(path)
    return paths


def run(workers: int) -> dict[str, Any]:
    required = (FREEZE, CANDIDATE_SOURCE, REGIME_SOURCE, OUTCOME_SOURCE, DAILY)
    if any(not path.exists() for path in required):
        missing = [str(path) for path in required if not path.exists()]
        raise ExperimentError(f"missing frozen inputs: {missing}")
    if sha256(FREEZE) != FREEZE_SHA256:
        raise ExperimentError("chart-rule freeze hash drift")

    population = load_population()
    windows = load_windows(population)
    ledger = build_ledger(population, windows)
    write_parquet(population, POPULATION)
    write_parquet(windows, WINDOW_PANEL)
    write_parquet(ledger, REVIEW_LEDGER)
    REVIEW_CSV.parent.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(REVIEW_CSV, index=False, float_format="%.10g")

    groups = {key: part for key, part in windows.groupby("event_id", sort=False)}
    tasks: list[tuple[dict[str, Any], pd.DataFrame, str]] = []
    for event in ledger.itertuples(index=False):
        output = CHART_DIR / (
            f"{int(event.chart_number):04d}_{event.symbol.replace('.', '_')}_"
            f"{pd.Timestamp(event.signal_date):%Y%m%d}.png"
        )
        tasks.append((event._asdict(), groups[str(event.event_id)], str(output)))
    with ProcessPoolExecutor(max_workers=max(1, workers)) as executor:
        index_rows = list(executor.map(render_worker, tasks, chunksize=1))
    index = pd.DataFrame(index_rows).sort_values("chart_number", kind="mergesort")
    index.to_csv(CHART_INDEX, index=False, float_format="%.10g")
    chronological_sheets = make_sheets(index, SHEET_DIR, EXPERIMENT)
    outcome_sheets: list[Path] = []
    for bucket in (
        "SEVERE_LOSS",
        "LOSS_0_TO_10PCT",
        "PROFIT_0_TO_4PCT",
        "TARGET_OR_PROFIT_GE_4PCT",
        "NO_COMPLETED_TRADE",
    ):
        subset = index.loc[index.outcome_bucket.eq(bucket)].sort_values(
            ["signal_date", "symbol"], kind="mergesort"
        )
        outcome_sheets.extend(
            make_sheets(
                subset,
                OUTCOME_SHEET_ROOT / bucket.lower(),
                bucket,
            )
        )

    completed = ledger.loc[ledger.net_return.notna()].copy()
    annual = (
        completed.assign(year=pd.to_datetime(completed.signal_date).dt.year)
        .groupby("year")
        .agg(
            completed=("event_id", "size"),
            mean_net=("net_return", "mean"),
            median_net=("net_return", "median"),
            severe_loss10=("net_return", lambda value: float((value <= -0.10).mean())),
            profit_ge_4=("net_return", lambda value: float((value >= 0.04).mean())),
        )
        .reset_index()
    )
    manifest = {
        "experiment": EXPERIMENT,
        "freeze_sha256": sha256(FREEZE),
        "population_sha256": sha256(POPULATION),
        "window_panel_sha256": sha256(WINDOW_PANEL),
        "review_ledger_sha256": sha256(REVIEW_LEDGER),
        "chart_index_sha256": sha256(CHART_INDEX),
        "raw_signal_count": int(len(population)),
        "completed_trade_count": int(completed.shape[0]),
        "chart_count": int(index.shape[0]),
        "chronological_sheet_count": int(len(chronological_sheets)),
        "outcome_sheet_count": int(len(outcome_sheets)),
        "annual": annual.to_dict("records"),
        "maximum_signal_outcome_date_read": "2020-12-31",
        "maximum_chart_bar_date": str(pd.to_datetime(windows.trade_date).max().date()),
        "2021_plus_signal_outcomes_read": False,
        "2022_plus_signal_outcomes_read": False,
        "2024_plus_outcomes_opened": False,
    }
    canonical_json(MANIFEST, manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    print(json.dumps(run(args.workers), indent=2, default=str))


if __name__ == "__main__":
    main()
