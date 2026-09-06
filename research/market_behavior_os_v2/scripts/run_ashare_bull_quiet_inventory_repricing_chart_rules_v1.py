#!/usr/bin/env python3
"""Render every 2014-2020 causal-BULL quiet-inventory repricing chart."""

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

import run_ashare_panic_absorption_12m_chart_rule_discovery_v1 as charts


ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-BULL-QUIET-INVENTORY-REPRICING-CHART-RULES-V1"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
SOURCE_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_quiet_inventory_information_repricing_long_translation_v2"
)
FEATURES = SOURCE_ROOT / "stage_a/candidates_features_2014_2023_frozen.parquet"
DISCOVERY_OUTCOMES = SOURCE_ROOT / "stage_b/development/discovery_outcomes.parquet"
CONFIRMATION_OUTCOMES = SOURCE_ROOT / "stage_b/development/confirmation_outcomes.parquet"
REGIME = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_causal_market_regime_routed_simple_strategy_v1/"
    "stage_a/causal_market_regime_2014_2023.parquet"
)
DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_bull_quiet_inventory_repricing_chart_rules_v1/"
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

EXPECTED_FREEZE_SHA256 = "dcfb59be52ddd0b74d47beb7f0a7f7da3a1de2f93cf4f1e141d5a4c5148e51d1"
EXPECTED_SIGNALS = 606
PROFILE = "T20_H60_QUIET_INFORMATION_REPRICING"


class ExperimentError(RuntimeError):
    """Fail-closed chart discovery error."""


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


def load_source() -> tuple[pd.DataFrame, pd.DataFrame]:
    if sha256(FREEZE) != EXPECTED_FREEZE_SHA256:
        raise ExperimentError(
            f"chart freeze hash drift: expected {EXPECTED_FREEZE_SHA256}, got {sha256(FREEZE)}"
        )
    connection = duckdb.connect()
    candidates = connection.execute(
        f"""
        SELECT f.*,r.market_regime,r.market_median_ret20,
          r.market_positive_ret20_share,r.market_median_ret60,
          r.market_positive_ret60_share
        FROM read_parquet('{FEATURES.as_posix()}') f
        JOIN read_parquet('{REGIME.as_posix()}') r
          ON f.signal_date=r.trade_date
        WHERE f.signal_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
          AND r.market_regime='BULL'
        ORDER BY f.signal_date,f.sleeve,f.symbol,f.event_id
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
    candidates["signal_date"] = pd.to_datetime(candidates.signal_date)
    outcomes["signal_date"] = pd.to_datetime(outcomes.signal_date)
    if len(candidates) != EXPECTED_SIGNALS or candidates.event_id.nunique() != EXPECTED_SIGNALS:
        raise ExperimentError(
            f"expected {EXPECTED_SIGNALS} frozen BULL signals, got {len(candidates)}"
        )
    annual = candidates.groupby(candidates.signal_date.dt.year).size().to_dict()
    expected_annual = {2014: 81, 2015: 88, 2016: 41, 2017: 29, 2018: 2, 2019: 160, 2020: 205}
    if annual != expected_annual:
        raise ExperimentError(f"annual BULL identity drift: {annual}")
    if candidates.available_at.gt(candidates.decision_at).any():
        raise ExperimentError("candidate availability exceeds decision time")
    # Reuse the chart helper's economic descriptors without changing the
    # frozen mother signal: avg_to20 is exactly the prior-20 turnover mean.
    candidates["turn20"] = candidates.avg_to20
    return candidates, outcomes


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


def render_chart(event: pd.Series, frame: pd.DataFrame, output: Path) -> None:
    signal_date = pd.Timestamp(event.signal_date)
    signal_rows = frame.loc[frame.trade_date == signal_date]
    if len(signal_rows) != 1:
        raise ExperimentError(f"{event.event_id}: missing chart signal row")
    signal_close = float(signal_rows.iloc[0].coord_close)
    figure, (price_ax, volume_ax) = charts.plt.subplots(
        2,
        1,
        figsize=(13.2, 7.4),
        gridspec_kw={"height_ratios": [4.4, 1.0], "hspace": 0.05},
        sharex=True,
    )
    charts.draw_candles(price_ax, frame, signal_close)
    signal_x = charts.mdates.date2num(signal_date.to_pydatetime())
    price_ax.axvline(signal_x, color="#1f77b4", linewidth=1.25, label="signal close")
    price_ax.axhline(100.0, color="#1f77b4", linewidth=0.8, linestyle=":")
    platform_y = (
        100.0 / (1.0 + float(event.signal_close_vs_prior5_high))
        if math.isfinite(float(event.signal_close_vs_prior5_high))
        else math.nan
    )
    if math.isfinite(platform_y):
        price_ax.axhline(platform_y, color="#777777", linewidth=0.7, linestyle="--", label="pre-breakout reference")
    if pd.notna(event.entry_date) and math.isfinite(float(event.entry_price)):
        entry_x = charts.mdates.date2num(pd.Timestamp(event.entry_date).to_pydatetime())
        entry_y = float(event.entry_price) * 100.0 / signal_close
        price_ax.scatter(entry_x, entry_y, marker="^", s=70, color="#7b2cbf", zorder=8, label="entry")
        target_y = float(event.entry_price) * 1.20 * 100.0 / signal_close
        price_ax.axhline(target_y, color="#ff7f0e", linewidth=0.8, linestyle="--", label="+20% target")
    if pd.notna(event.exit_date) and math.isfinite(float(event.exit_price)):
        exit_x = charts.mdates.date2num(pd.Timestamp(event.exit_date).to_pydatetime())
        exit_y = float(event.exit_price) * 100.0 / signal_close
        price_ax.scatter(exit_x, exit_y, marker="v", s=70, color="#111111", zorder=8, label="exit")
    status = str(event.outcome_bucket)
    if math.isfinite(float(event.net_return)):
        status += f" | net {float(event.net_return):+.2%} | {event.exit_reason}"
    title = (
        f"{int(event.chart_number):04d} | {event.symbol} | {event.sleeve} | "
        f"signal {signal_date.date()} | BULL | {status}\n"
        f"platform {float(event.platform_width):.1%} | contraction {float(event.turnover_contraction):.2f}x | "
        f"gap {float(event.open_gap):+.1%} | signal {float(event.signal_step_return):+.1%} | "
        f"turn {float(event.turnover_expansion):.1f}x | r20/r60 {float(event.ret20):+.1%}/{float(event.ret60):+.1%}"
    )
    price_ax.set_title(title, fontsize=10.2)
    price_ax.set_ylabel("Coordinate price (signal close=100)")
    price_ax.grid(alpha=0.17, linewidth=0.5)
    handles, labels = price_ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles, strict=False))
    price_ax.legend(by_label.values(), by_label.keys(), loc="upper left", ncol=5, fontsize=7.5)
    valid_turn = frame.loc[frame.turnover_fraction.notna()].copy()
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
        "outcome_bucket": str(event.outcome_bucket),
        "net_return": charts.safe_float(event.net_return),
        "chart_path": str(output),
    }


def run(workers: int) -> dict[str, Any]:
    for path in (FREEZE, FEATURES, DISCOVERY_OUTCOMES, CONFIRMATION_OUTCOMES, REGIME, DAILY):
        if not path.is_file():
            raise ExperimentError(f"missing required input {path}")
    configure_chart_module()
    candidates, outcomes = load_source()
    windows = charts.load_windows(candidates)
    ledger = charts.build_ledger(candidates, outcomes, windows)
    extras = candidates[
        [
            "event_id",
            "platform_width",
            "turnover_contraction",
            "turnover_expansion",
            "market_median_ret20",
            "market_positive_ret20_share",
            "market_median_ret60",
            "market_positive_ret60_share",
        ]
    ]
    ledger = ledger.merge(extras, on="event_id", how="left", validate="one_to_one")
    write_parquet(windows, WINDOW_PANEL)
    write_parquet(ledger, REVIEW_LEDGER)
    REVIEW_CSV.parent.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(REVIEW_CSV, index=False, float_format="%.10g")

    window_groups = {key: part for key, part in windows.groupby("event_id", sort=False)}
    tasks: list[tuple[dict[str, Any], pd.DataFrame, str]] = []
    for _, event in ledger.iterrows():
        path = CHART_DIR / (
            f"{int(event.chart_number):04d}_{event.symbol.replace('.', '_')}_"
            f"{pd.Timestamp(event.signal_date):%Y%m%d}.png"
        )
        tasks.append((event.to_dict(), window_groups[str(event.event_id)], str(path)))
    with ProcessPoolExecutor(max_workers=max(1, workers)) as executor:
        index_rows = list(executor.map(render_worker, tasks, chunksize=1))
    index = pd.DataFrame(index_rows)
    index.to_csv(CHART_INDEX, index=False, float_format="%.10g")
    sheets = charts.build_contact_sheets(index)
    outcome_sheets = charts.build_outcome_review_sheets(index)

    complete = ledger.loc[ledger.status.eq("COMPLETED")].copy()
    manifest = {
        "experiment": EXPERIMENT,
        "freeze_sha256": sha256(FREEZE),
        "source_features_sha256": sha256(FEATURES),
        "discovery_outcomes_sha256": sha256(DISCOVERY_OUTCOMES),
        "confirmation_outcomes_sha256": sha256(CONFIRMATION_OUTCOMES),
        "regime_sha256": sha256(REGIME),
        "signals": int(len(ledger)),
        "completed": int(len(complete)),
        "charts": int(len(index)),
        "contact_sheets": int(len(sheets)),
        "outcome_sheets": int(len(outcome_sheets)),
        "signal_dates": int(ledger.signal_date.nunique()),
        "symbols": int(ledger.symbol.nunique()),
        "max_signal_date": str(ledger.signal_date.max().date()),
        "max_chart_bar_date": str(pd.to_datetime(windows.trade_date).max().date()),
        "2021_plus_signal_outcome_read": "NO",
        "2022_plus_read": "NO",
        "pooled_mean_net": float(complete.net_return.mean()),
        "pooled_median_net": float(complete.net_return.median()),
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
