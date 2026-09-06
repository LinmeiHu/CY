#!/usr/bin/env python3
"""Render every frozen causal-BEAR slow-exhaustion development candidate."""

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
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import run_ashare_panic_absorption_12m_chart_rule_discovery_v1 as charts

EXPERIMENT = "ASHARE-BEAR-SLOW-SUPPLY-EXHAUSTION-12M-CHART-DISCOVERY-V2"
REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
EXPECTED_FREEZE_SHA256 = "9ad639a78415811ec12d551c145cbd62edce2d66c126bd1ba96f7923f0269cce"

DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
MOTHER_ROOT = DATA_ROOT / "ashare_distributed_accumulation_slow_exhaustion_mother_screen_v1"
CANDIDATES = MOTHER_ROOT / "development_2014_2020_candidates.parquet"
OUTCOMES = MOTHER_ROOT / "development_2014_2020_outcomes.parquet"
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
EXPECTED_HASHES = {
    "candidates": "7c08a9ed2090fd1b9b27ee0068ed2c438b8583fc876872bc0523d5e00f5ab364",
    "outcomes": "8e410688aba5f07f1a36c87bd0e061c8d052fe6d2b051656b59970589320285d",
    "daily": "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    "regime": "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
}

OUTPUT_ROOT = DATA_ROOT / "ashare_bear_slow_supply_exhaustion_12m_chart_discovery_v2"
LEDGER = OUTPUT_ROOT / "frozen_candidate_ledger.parquet"
WINDOWS = OUTPUT_ROOT / "chart_window_panel.parquet"
CHART_DIR = OUTPUT_ROOT / "individual_charts"
SHEET_DIR = OUTPUT_ROOT / "review_sheets"
CHART_INDEX = OUTPUT_ROOT / "chart_index.csv"
RESULT = OUTPUT_ROOT / "result.json"

SIGNAL_START = pd.Timestamp("2014-01-01")
SIGNAL_END = pd.Timestamp("2020-12-31")
MAX_BAR_DATE = pd.Timestamp("2021-12-31")
PRE = 126
POST = 126


class ResearchError(RuntimeError):
    """Fail closed on source identity, chronology, PIT state, or chart completeness."""


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
    connection.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    connection.close()


def verify_sources() -> dict[str, str]:
    paths = {
        "freeze": FREEZE,
        "candidates": CANDIDATES,
        "outcomes": OUTCOMES,
        "daily": DAILY,
        "regime": REGIME,
    }
    expected = {"freeze": EXPECTED_FREEZE_SHA256, **EXPECTED_HASHES}
    actual: dict[str, str] = {}
    for name, path in paths.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen source: {path}")
        actual[name] = sha256(path)
        if actual[name] != expected[name]:
            raise ResearchError(f"{name} identity drift: {actual[name]} != {expected[name]}")
    return actual


def load_ledger() -> pd.DataFrame:
    connection = duckdb.connect()
    ledger = connection.execute(
        f"""
        SELECT c.event_id AS chart_event_id,c.symbol,c.sleeve,c.signal_date,c.signal_cal_idx,
          c.decision_at,c.available_at,c.market_regime,c.market_latest_source_timestamp,
          c.invalid_step_cum,c.coordinate_factor,c.coord_open,c.coord_high,c.coord_low,c.coord_close,
          c.prior5_high,c.last5_low,c.previous5_low,c.exact_prior20_return,
          c.last5_downside_turnover,c.previous5_downside_turnover,c.turnover_expansion,
          c.close_location,c.step_return,c.causal_industry,
          o.status,o.entry_date,o.entry_cal_idx,o.entry_price,o.exit_date,o.exit_cal_idx,o.exit_price,
          o.exit_reason,o.holding_sessions,o.gross_return,o.net_return,
          r.market_median_ret20,r.market_positive_ret20_share,
          r.market_median_ret60,r.market_positive_ret60_share
        FROM read_parquet('{CANDIDATES.as_posix()}') c
        LEFT JOIN read_parquet('{OUTCOMES.as_posix()}') o USING(event_id)
        JOIN read_parquet('{REGIME.as_posix()}') r ON c.signal_date=r.trade_date
        WHERE c.mechanism='SLOW_SUPPLY_EXHAUSTION_TAKEOVER'
          AND c.market_regime='BEAR'
          AND c.signal_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
        ORDER BY c.signal_date,c.symbol,c.event_id
        """
    ).fetch_df()
    connection.close()
    for column in (
        "signal_date",
        "decision_at",
        "available_at",
        "market_latest_source_timestamp",
        "entry_date",
        "exit_date",
    ):
        ledger[column] = pd.to_datetime(ledger[column])
    if len(ledger) != 1765 or ledger.chart_event_id.nunique() != 1765:
        raise ResearchError(f"frozen candidate identity drift: {len(ledger)}")
    if ledger.signal_date.min() < SIGNAL_START or ledger.signal_date.max() > SIGNAL_END:
        raise ResearchError("signal outside frozen development period")
    if not ledger.market_regime.eq("BEAR").all():
        raise ResearchError("candidate outside exact causal BEAR state")
    if ledger.available_at.gt(ledger.decision_at).any():
        raise ResearchError("stock source after decision")
    if ledger.market_latest_source_timestamp.gt(ledger.decision_at).any():
        raise ResearchError("market state source after decision")
    completed = ledger.status.eq("COMPLETED")
    if ledger.loc[completed, "entry_date"].le(ledger.loc[completed, "signal_date"]).any():
        raise ResearchError("same/prior-bar entry in frozen source")
    if ledger.loc[completed, "exit_cal_idx"].le(ledger.loc[completed, "entry_cal_idx"]).any():
        raise ResearchError("T+1/source exit violation")
    ledger["outcome_bucket"] = np.select(
        [
            completed & ledger.net_return.ge(0.04),
            completed & ledger.net_return.ge(0.0),
            completed & ledger.net_return.gt(-0.10),
            completed,
        ],
        ["PROFIT_GE_4PCT", "PROFIT_0_TO_4PCT", "LOSS_0_TO_10PCT", "SEVERE_LOSS"],
        default="NO_COMPLETED_TRADE",
    )
    ledger["chart_number"] = np.arange(1, len(ledger) + 1)
    return ledger


def load_windows(ledger: pd.DataFrame) -> pd.DataFrame:
    connection = duckdb.connect()
    connection.register("events", ledger[["chart_event_id", "symbol", "signal_cal_idx"]])
    windows = connection.execute(
        f"""
        SELECT e.chart_event_id,d.*
        FROM events e
        JOIN read_parquet('{DAILY.as_posix()}') d
          ON e.symbol=d.symbol
         AND d.cal_idx BETWEEN e.signal_cal_idx-{PRE} AND e.signal_cal_idx+{POST}
        WHERE d.trade_date<=DATE '2021-12-31'
        ORDER BY e.chart_event_id,d.cal_idx
        """
    ).fetch_df()
    connection.close()
    for column in ("trade_date", "available_at", "decision_at"):
        windows[column] = pd.to_datetime(windows[column])
    if windows.trade_date.max() > MAX_BAR_DATE:
        raise ResearchError("chart source exceeds frozen tail")
    if windows.chart_event_id.nunique() != len(ledger):
        raise ResearchError("missing chart window identity")
    return windows


def render_chart(event: dict[str, Any], frame: pd.DataFrame, output: str) -> dict[str, Any]:
    signal_date = pd.Timestamp(event["signal_date"])
    signal = frame.loc[frame.trade_date.eq(signal_date)]
    if len(signal) != 1:
        raise ResearchError(f"{event['chart_event_id']}: missing signal bar")
    signal_close = float(signal.iloc[0].coord_close)
    fig = plt.figure(figsize=(14.5, 8.2), constrained_layout=True)
    grid = fig.add_gridspec(4, 1, height_ratios=[3.2, 0.85, 0.8, 0.8])
    price_ax = fig.add_subplot(grid[:2, 0])
    volume_ax = fig.add_subplot(grid[2, 0], sharex=price_ax)
    state_ax = fig.add_subplot(grid[3, 0], sharex=price_ax)
    charts.draw_candles(price_ax, frame, signal_close)

    def to_x(value: object) -> float:
        if pd.isna(value):
            return math.nan
        return float(mdates.date2num(pd.Timestamp(value).to_pydatetime()))

    def to_y(value: object) -> float:
        return float(value) * 100.0 / signal_close

    price_ax.axvline(to_x(signal_date), color="#059669", linewidth=1.3, label="signal")
    price_ax.axhline(
        to_y(event["prior5_high"]),
        color="#2563eb",
        linewidth=1.0,
        linestyle="--",
        label="causal prior-5 high",
    )
    price_ax.axhline(
        to_y(event["previous5_low"]),
        color="#9ca3af",
        linewidth=0.9,
        linestyle=":",
        label="causal preceding-5 low",
    )
    if event["status"] == "COMPLETED":
        price_ax.scatter(
            to_x(event["entry_date"]),
            to_y(event["entry_price"]),
            marker="^",
            s=58,
            color="#7c3aed",
            zorder=8,
            label="entry",
        )
        price_ax.scatter(
            to_x(event["exit_date"]),
            to_y(event["exit_price"]),
            marker="v",
            s=58,
            color="#111827",
            zorder=8,
            label="exit",
        )
        price_ax.axhline(
            to_y(float(event["entry_price"]) * 1.10),
            color="#f59e0b",
            linewidth=1.0,
            linestyle=":",
            label="frozen +10% target",
        )
    price_ax.legend(loc="upper left", ncol=6, fontsize=7)
    price_ax.set_ylabel("Coordinate price (signal close=100)")
    net_text = "NA" if pd.isna(event["net_return"]) else f"{float(event['net_return']):+.2%}"
    exit_text = "NA" if pd.isna(event["exit_reason"]) else str(event["exit_reason"])
    turnover_decay = float(event["last5_downside_turnover"]) / max(
        float(event["previous5_downside_turnover"]), 1e-12
    )
    price_ax.set_title(
        f"{int(event['chart_number']):04d} | {event['symbol']} | {signal_date.date()} | "
        f"causal BEAR | {event['outcome_bucket']} | net {net_text} | {exit_text}\n"
        f"prior20={float(event['exact_prior20_return']):+.1%} | downside-turnover 5/prev5="
        f"{turnover_decay:.2f} | signal turnover={float(event['turnover_expansion']):.2f}x | "
        f"market r20/r60={float(event['market_median_ret20']):+.1%}/"
        f"{float(event['market_median_ret60']):+.1%}",
        fontsize=9,
    )

    x = mdates.date2num(pd.to_datetime(frame.trade_date).to_numpy())
    volume_ax.bar(x, frame.turnover_fraction.fillna(0.0) * 100.0, color="#9ca3af", width=0.8)
    volume_ax.axvline(to_x(signal_date), color="#059669", linewidth=1.0)
    volume_ax.set_ylabel("Turnover %")
    state_ax.plot(
        x,
        frame.ret20.fillna(np.nan) * 100.0,
        color="#2563eb",
        linewidth=0.8,
        label="stock ret20",
    )
    state_ax.axhline(0.0, color="#9ca3af", linewidth=0.7)
    state_ax.axvline(to_x(signal_date), color="#059669", linewidth=1.0)
    state_ax.set_ylabel("ret20 %")
    state_ax.legend(loc="upper left", fontsize=7)
    tick_indices = np.linspace(0, max(len(frame) - 1, 0), min(7, len(frame)), dtype=int)
    state_ax.set_xticks(x[tick_indices])
    state_ax.set_xticklabels(
        [pd.Timestamp(frame.iloc[index].trade_date).strftime("%Y-%m") for index in tick_indices],
        rotation=25,
        ha="right",
        fontsize=8,
    )
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120)
    plt.close(fig)
    return {
        "chart_event_id": event["chart_event_id"],
        "chart_number": int(event["chart_number"]),
        "outcome_bucket": event["outcome_bucket"],
        "signal_date": signal_date,
        "signal_year": int(signal_date.year),
        "symbol": event["symbol"],
        "chart_path": str(output_path),
    }


def render_worker(payload: tuple[dict[str, Any], pd.DataFrame, str]) -> dict[str, Any]:
    return render_chart(*payload)


def build_sheets(index: pd.DataFrame) -> list[Path]:
    output_paths: list[Path] = []
    for (year, bucket), part in index.groupby(["signal_year", "outcome_bucket"], sort=True):
        part = part.sort_values(["signal_date", "symbol"], kind="mergesort")
        target_dir = SHEET_DIR / str(year) / str(bucket).lower()
        target_dir.mkdir(parents=True, exist_ok=True)
        for sheet_no, start in enumerate(range(0, len(part), 9), 1):
            page = part.iloc[start : start + 9]
            canvas = Image.new("RGB", (3600, 2130), "white")
            draw = ImageDraw.Draw(canvas)
            draw.text(
                (20, 8),
                f"{year} | {bucket} | sheet {sheet_no:03d} | "
                f"events {start + 1}-{start + len(page)}",
                fill="black",
            )
            for position, row in enumerate(page.itertuples(index=False)):
                image = Image.open(row.chart_path).convert("RGB")
                image.thumbnail((1180, 675))
                x = (position % 3) * 1200 + 10
                y = (position // 3) * 700 + 30
                canvas.paste(image, (x, y))
            output = target_dir / f"sheet_{sheet_no:03d}.jpg"
            canvas.save(output, quality=88, optimize=True)
            output_paths.append(output)
    return output_paths


def summary(frame: pd.DataFrame) -> dict[str, Any]:
    completed = frame.loc[frame.status.eq("COMPLETED")]
    return {
        "signals": len(frame),
        "completed": len(completed),
        "mean_net": float(completed.net_return.mean()) if len(completed) else None,
        "median_net": float(completed.net_return.median()) if len(completed) else None,
        "positive_rate": float(completed.net_return.gt(0).mean()) if len(completed) else None,
        "severe_loss_rate": (
            float(completed.net_return.le(-0.10).mean()) if len(completed) else None
        ),
        "signal_dates": int(frame.signal_date.nunique()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--skip-render", action="store_true")
    args = parser.parse_args()
    source_hashes = verify_sources()
    ledger = load_ledger()
    windows = load_windows(ledger)
    write_parquet(ledger, LEDGER)
    write_parquet(windows, WINDOWS)
    by_event = {
        event_id: part.sort_values("cal_idx", kind="mergesort").reset_index(drop=True)
        for event_id, part in windows.groupby("chart_event_id", sort=False)
    }
    payloads = []
    for event in ledger.to_dict("records"):
        filename = (
            f"{int(event['chart_number']):04d}_bear_slow_exhaustion_"
            f"{event['symbol']}_{pd.Timestamp(event['signal_date']):%Y%m%d}.png"
        )
        payloads.append((event, by_event[event["chart_event_id"]], str(CHART_DIR / filename)))
    if not args.skip_render:
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            rendered = list(executor.map(render_worker, payloads, chunksize=4))
        index = pd.DataFrame(rendered).sort_values("chart_number", kind="mergesort")
        index.to_csv(CHART_INDEX, index=False)
        sheets = build_sheets(index)
    else:
        if not CHART_INDEX.is_file():
            raise ResearchError("cannot skip a missing render")
        index = pd.read_csv(CHART_INDEX, parse_dates=["signal_date"])
        sheets = sorted(SHEET_DIR.rglob("sheet_*.jpg"))
    if len(index) != len(ledger) or len(list(CHART_DIR.glob("*.png"))) != len(ledger):
        raise ResearchError("incomplete individual chart render")
    if sum(len(Image.open(path).getbands()) > 0 for path in sheets) != len(sheets):
        raise ResearchError("unreadable review sheet")
    result = {
        "experiment": EXPERIMENT,
        "scientific_status": "ALL_FROZEN_DEVELOPMENT_CHARTS_RENDERED_FOR_MANUAL_REVIEW",
        "source_hashes": source_hashes,
        "summary": summary(ledger),
        "annual": {
            str(year): summary(part)
            for year, part in ledger.groupby(ledger.signal_date.dt.year, sort=True)
        },
        "bucket_counts": {
            str(bucket): len(part) for bucket, part in ledger.groupby("outcome_bucket", sort=True)
        },
        "individual_charts": len(index),
        "review_sheets": len(sheets),
        "max_chart_bar_date": str(windows.trade_date.max().date()),
        "2021_signal_read": False,
        "2022_2024_signal_or_outcome_read_for_chart_rules": False,
        "future_market_function": False,
        "ledger_sha256": sha256(LEDGER),
        "window_sha256": sha256(WINDOWS),
        "chart_index_sha256": sha256(CHART_INDEX),
    }
    write_json(RESULT, result)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
