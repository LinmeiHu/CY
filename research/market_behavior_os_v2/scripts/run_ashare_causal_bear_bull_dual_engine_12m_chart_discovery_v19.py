#!/usr/bin/env python3
"""Render every frozen V19 dual-engine development signal for chart anatomy."""

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

EXPERIMENT = "ASHARE-CAUSAL-BEAR-BULL-DUAL-ENGINE-12M-CHART-DISCOVERY-V19"
REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
EXPECTED_FREEZE_SHA256 = "9f7d140a1e40765d99ba65a179710cfa59d57f134a7d9eab91033781a4559e92"

DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
BEAR = (
    DATA_ROOT
    / "ashare_bear_fast_capitulation_active_demand_short_ranking_v13r1"
    / "selected_accepted_trades.parquet"
)
BULL_CANDIDATES = (
    DATA_ROOT / "ashare_bull_quiet_platform_dual_demand_v24" / "stage_a/candidates.parquet"
)
BULL_OUTCOMES = (
    DATA_ROOT / "ashare_bull_quiet_platform_dual_demand_v24" / "stage_b/outcomes.parquet"
)
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
    "bear": "8e62f4b3a9552cac769e95eb6e172ec65e8d53af207cccb06a60c6ad21ca8140",
    "bull_candidates": "ad25518cb1e04ca58db6cd4d49e1e00dc65da049b7e089c489d83c6464819cab",
    "bull_outcomes": "dc97ef0f459c1a5e4e6832b48762076a342c752df4a7321d0d388be0cd87c9ed",
    "daily": "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    "regime": "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
}

OUTPUT_ROOT = DATA_ROOT / "ashare_causal_bear_bull_dual_engine_12m_chart_discovery_v19"
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
    """Fail closed on source identity, chronology, or chart completeness."""


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
        "bear": BEAR,
        "bull_candidates": BULL_CANDIDATES,
        "bull_outcomes": BULL_OUTCOMES,
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
        WITH bear AS (
          SELECT 'BEAR_REPAIR' AS engine,'BEAR|' || event_id AS chart_event_id,
            event_id AS source_event_id,symbol,sleeve,signal_date,signal_cal_idx,
            entry_date,entry_cal_idx,entry_price,exit_date,exit_cal_idx,exit_price,
            exit_reason,holding_sessions,gross_return,net_return,
            prior5_high_x AS structural_level,
            prior10_return AS feature_1,turnover_ratio_x AS feature_2,
            'prior10_return' AS feature_1_name,'turnover_ratio' AS feature_2_name,
            'FAST_CAPITULATION_ACTIVE_DEMAND' AS admission_lane
          FROM read_parquet('{BEAR.as_posix()}')
          WHERE signal_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
            AND status='COMPLETED'
        ), bull AS (
          SELECT 'BULL_CONTINUATION' AS engine,'BULL|' || o.event_id AS chart_event_id,
            o.event_id AS source_event_id,o.symbol,o.sleeve,o.signal_date,o.signal_cal_idx,
            o.entry_date,o.entry_cal_idx,o.entry_price,o.exit_date,o.exit_cal_idx,o.exit_price,
            o.exit_reason,o.holding_sessions,o.gross_return,o.net_return,
            c.platform_high AS structural_level,
            c.platform_width AS feature_1,c.turnover_contraction AS feature_2,
            'platform_width' AS feature_1_name,'turnover_contraction' AS feature_2_name,
            c.admission_lane
          FROM read_parquet('{BULL_OUTCOMES.as_posix()}') o
          JOIN read_parquet('{BULL_CANDIDATES.as_posix()}') c USING(event_id)
          WHERE o.signal_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
            AND o.status='COMPLETED' AND o.profile='T15_H15_NO_STOP'
        ), combined AS (
          SELECT * FROM bear UNION ALL SELECT * FROM bull
        )
        SELECT c.*,r.market_regime,r.market_median_ret20,
          r.market_positive_ret20_share,r.market_median_ret60,
          r.market_positive_ret60_share,
          r.latest_source_timestamp AS market_latest_source_timestamp
        FROM combined c
        JOIN read_parquet('{REGIME.as_posix()}') r ON c.signal_date=r.trade_date
        ORDER BY c.signal_date,c.engine,c.sleeve,c.symbol,c.chart_event_id
        """
    ).fetch_df()
    connection.close()
    for column in (
        "signal_date",
        "entry_date",
        "exit_date",
        "market_latest_source_timestamp",
    ):
        ledger[column] = pd.to_datetime(ledger[column])
    if len(ledger) != 840 or ledger.chart_event_id.nunique() != 840:
        raise ResearchError(f"frozen union identity drift: {len(ledger)}")
    if ledger.signal_date.min() < SIGNAL_START or ledger.signal_date.max() > SIGNAL_END:
        raise ResearchError("signal outside frozen development period")
    if ledger.entry_date.le(ledger.signal_date).any():
        raise ResearchError("same/prior-bar entry in frozen source")
    if ledger.exit_cal_idx.le(ledger.entry_cal_idx).any():
        raise ResearchError("T+1/source exit violation")
    if ledger.market_latest_source_timestamp.gt(ledger.signal_date + pd.Timedelta(hours=15)).any():
        raise ResearchError("market state timestamp after signal close")
    if not ledger.loc[ledger.engine.eq("BEAR_REPAIR"), "market_regime"].eq("BEAR").all():
        raise ResearchError("bear engine outside causal BEAR")
    if not ledger.loc[ledger.engine.eq("BULL_CONTINUATION"), "market_regime"].eq("BULL").all():
        raise ResearchError("bull engine outside causal BULL")
    ledger["outcome_bucket"] = np.select(
        [
            ledger.net_return.ge(0.04),
            ledger.net_return.ge(0.0),
            ledger.net_return.gt(-0.10),
        ],
        ["PROFIT_GE_4PCT", "PROFIT_0_TO_4PCT", "LOSS_0_TO_10PCT"],
        default="SEVERE_LOSS",
    )
    ledger["chart_number"] = np.arange(1, len(ledger) + 1)
    return ledger


def load_windows(ledger: pd.DataFrame) -> pd.DataFrame:
    connection = duckdb.connect()
    connection.register(
        "events",
        ledger[["chart_event_id", "symbol", "signal_cal_idx"]],
    )
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
        to_y(event["structural_level"]),
        color="#2563eb",
        linewidth=1.0,
        linestyle="--",
        label="causal structural level",
    )
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
    target_multiple = 1.10 if event["engine"] == "BEAR_REPAIR" else 1.15
    price_ax.axhline(
        to_y(float(event["entry_price"]) * target_multiple),
        color="#f59e0b",
        linewidth=1.0,
        linestyle=":",
        label="frozen target",
    )
    price_ax.legend(loc="upper left", ncol=6, fontsize=7)
    price_ax.set_ylabel("Coordinate price (signal close=100)")
    price_ax.set_title(
        f"{int(event['chart_number']):04d} | {event['symbol']} | {signal_date.date()} | "
        f"{event['engine']} | causal {event['market_regime']} | {event['outcome_bucket']} | "
        f"net {float(event['net_return']):+.2%} | {event['exit_reason']}\n"
        f"{event['feature_1_name']}={float(event['feature_1']):+.2%} | "
        f"{event['feature_2_name']}={float(event['feature_2']):.2f} | "
        f"lane={event['admission_lane']} | market r20/r60 "
        f"{float(event['market_median_ret20']):+.1%}/{float(event['market_median_ret60']):+.1%}",
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
        "engine": event["engine"],
        "outcome_bucket": event["outcome_bucket"],
        "signal_date": signal_date,
        "symbol": event["symbol"],
        "chart_path": str(output_path),
    }


def render_worker(payload: tuple[dict[str, Any], pd.DataFrame, str]) -> dict[str, Any]:
    return render_chart(*payload)


def build_sheets(index: pd.DataFrame) -> list[Path]:
    output_paths: list[Path] = []
    for (engine, bucket), part in index.groupby(["engine", "outcome_bucket"], sort=True):
        part = part.sort_values(["signal_date", "symbol"], kind="mergesort")
        target_dir = SHEET_DIR / engine.lower() / bucket.lower()
        target_dir.mkdir(parents=True, exist_ok=True)
        for sheet_no, start in enumerate(range(0, len(part), 9), 1):
            page = part.iloc[start : start + 9]
            canvas = Image.new("RGB", (3600, 2130), "white")
            draw = ImageDraw.Draw(canvas)
            draw.text(
                (20, 8),
                f"{engine} | {bucket} | sheet {sheet_no:03d} | "
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
    return {
        "trades": len(frame),
        "mean_net": float(frame.net_return.mean()),
        "median_net": float(frame.net_return.median()),
        "positive_rate": float(frame.net_return.gt(0).mean()),
        "severe_loss_rate": float(frame.net_return.le(-0.10).mean()),
        "signal_dates": int(frame.signal_date.nunique()),
        "mean_holding_sessions": float(frame.holding_sessions.mean()),
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
            f"{int(event['chart_number']):04d}_{event['engine'].lower()}_"
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
    result = {
        "experiment": EXPERIMENT,
        "scientific_status": "ALL_FROZEN_DEVELOPMENT_CHARTS_RENDERED_FOR_MANUAL_REVIEW",
        "source_hashes": source_hashes,
        "summary": summary(ledger),
        "annual": {
            str(year): summary(part)
            for year, part in ledger.groupby(ledger.signal_date.dt.year, sort=True)
        },
        "by_engine": {
            str(engine): summary(part) for engine, part in ledger.groupby("engine", sort=True)
        },
        "bucket_counts": {
            f"{engine}|{bucket}": len(part)
            for (engine, bucket), part in ledger.groupby(["engine", "outcome_bucket"], sort=True)
        },
        "individual_charts": len(index),
        "review_sheets": len(sheets),
        "max_chart_bar_date": str(windows.trade_date.max().date()),
        "post_2021_bar_read": False,
        "2022_2024_outcome_read_for_chart_rules": False,
        "ledger_sha256": sha256(LEDGER),
        "window_sha256": sha256(WINDOWS),
        "chart_index_sha256": sha256(CHART_INDEX),
    }
    write_json(RESULT, result)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
