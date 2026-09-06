#!/usr/bin/env python3
"""Render every pre-2021 stale-resistance event for V26-style chart discovery."""

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


EXPERIMENT = "ASHARE-STALE-ANNUAL-RESISTANCE-12M-CHART-RULE-DISCOVERY-V3"
REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
EXPECTED_FREEZE_SHA256 = "3e859c6c14be5c394974317222b8d616133be7f5b3ca2c3c478bbb754985e2a3"
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
SOURCE_ROOT = DATA_ROOT / "ashare_stale_annual_resistance_absorption_breakout_v1"
CANDIDATES = SOURCE_ROOT / "stage_a/candidates_frozen.parquet"
DISCOVERY_OUTCOMES = SOURCE_ROOT / "stage_b/development/discovery_outcomes.parquet"
CONFIRMATION_OUTCOMES = SOURCE_ROOT / "stage_b/development/confirmation_outcomes.parquet"
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
EXT_ROOT = (
    DATA_ROOT
    / "ashare_stale_annual_resistance_12m_chart_rule_discovery_v3"
    / "development_2014_2020"
)
WINDOW_PANEL = EXT_ROOT / "chart_window_panel.parquet"
REVIEW_LEDGER = EXT_ROOT / "review_ledger.parquet"
REVIEW_CSV = EXT_ROOT / "review_ledger.csv"
CHART_DIR = EXT_ROOT / "individual_charts"
CHART_INDEX = EXT_ROOT / "chart_index.csv"
SHEET_ROOT = EXT_ROOT / "review_sheets_by_outcome"
MANIFEST = EXT_ROOT / "manifest.json"

EXPECTED_CANDIDATES_SHA256 = "4518bd47845d068d36f85016786d3743276364410a5bec6c434f10c82b27e455"
EXPECTED_DISCOVERY_OUTCOMES_SHA256 = "8e86ef65b0f0f6bfaf82e5424165dfd4c5d6768a67fe7f6a584bd09ba6d0c711"
EXPECTED_CONFIRMATION_OUTCOMES_SHA256 = "f05ac84340f65839ae1ef8f45b4b2a861644e5e0da067d8c0c5fd281ae587981"
EXPECTED_ANNUAL = {2014: 237, 2015: 172, 2016: 55, 2017: 134, 2018: 72, 2019: 157, 2020: 220}
PRE = 126
POST = 126


class ResearchError(RuntimeError):
    """Fail closed on source identity, chronology, or PIT drift."""


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


def safe_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    return number if math.isfinite(number) else math.nan


def outcome_bucket(status: str, net_return: float) -> str:
    if status != "COMPLETED" or not math.isfinite(net_return):
        return "NO_COMPLETED_TRADE"
    if net_return >= 0.04:
        return "PROFIT_GE_4PCT"
    if net_return >= 0.0:
        return "PROFIT_0_TO_4PCT"
    if net_return > -0.10:
        return "LOSS_0_TO_10PCT"
    return "SEVERE_LOSS"


def load_sources() -> tuple[pd.DataFrame, pd.DataFrame]:
    expected = {
        CANDIDATES: EXPECTED_CANDIDATES_SHA256,
        DISCOVERY_OUTCOMES: EXPECTED_DISCOVERY_OUTCOMES_SHA256,
        CONFIRMATION_OUTCOMES: EXPECTED_CONFIRMATION_OUTCOMES_SHA256,
    }
    if sha256(FREEZE) != EXPECTED_FREEZE_SHA256:
        raise ResearchError("chart-rule freeze drift")
    for path, digest in expected.items():
        if sha256(path) != digest:
            raise ResearchError(f"source identity drift: {path}")

    connection = duckdb.connect()
    candidates = connection.execute(
        f"""
        SELECT c.*,r.market_regime,r.market_median_ret20,r.market_positive_ret20_share,
          r.market_median_ret60,r.market_positive_ret60_share,
          r.market_median_ret20-r.market_median_ret60 AS market_return_acceleration,
          r.market_positive_ret20_share-r.market_positive_ret60_share AS market_breadth_acceleration,
          r.latest_source_timestamp AS market_latest_source_timestamp
        FROM read_parquet('{CANDIDATES.as_posix()}') c
        JOIN read_parquet('{REGIME.as_posix()}') r ON c.signal_date=r.trade_date
        WHERE c.signal_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
        ORDER BY c.signal_date,c.sleeve,c.symbol,c.event_id
        """
    ).fetch_df()
    outcomes = connection.execute(
        f"""
        SELECT * FROM (
          SELECT * FROM read_parquet('{DISCOVERY_OUTCOMES.as_posix()}')
          UNION ALL BY NAME
          SELECT * FROM read_parquet('{CONFIRMATION_OUTCOMES.as_posix()}')
        )
        WHERE signal_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
        ORDER BY signal_date,symbol,event_id
        """
    ).fetch_df()
    connection.close()

    for column in ("signal_date", "available_at", "decision_at", "market_latest_source_timestamp"):
        candidates[column] = pd.to_datetime(candidates[column])
    for column in ("signal_date", "entry_date", "exit_date"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    annual = candidates.groupby(candidates.signal_date.dt.year).size().to_dict()
    if annual != EXPECTED_ANNUAL or len(candidates) != sum(EXPECTED_ANNUAL.values()):
        raise ResearchError(f"candidate count drift: {annual}")
    if candidates.event_id.duplicated().any() or outcomes.event_id.duplicated().any():
        raise ResearchError("duplicate event identity")
    if set(outcomes.event_id) != set(candidates.event_id):
        raise ResearchError("outcome identity differs from frozen candidate identity")
    if candidates.available_at.gt(candidates.decision_at).any():
        raise ResearchError("candidate availability exceeds decision_at")
    if candidates.market_latest_source_timestamp.gt(candidates.decision_at).any():
        raise ResearchError("market state uses information after decision_at")
    return candidates, outcomes


def load_windows(candidates: pd.DataFrame) -> pd.DataFrame:
    connection = duckdb.connect()
    connection.register("events", candidates[["event_id", "symbol", "cal_idx", "signal_date"]])
    windows = connection.execute(
        f"""
        SELECT e.event_id,e.signal_date,d.symbol,d.trade_date,d.cal_idx,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.turnover_fraction,
          d.current_valid,d.hard_valid,d.current_day_data_tradable,d.available_at,d.decision_at
        FROM events e
        JOIN read_parquet('{DAILY.as_posix()}') d
          ON e.symbol=d.symbol
         AND d.cal_idx BETWEEN e.cal_idx-{PRE} AND e.cal_idx+{POST}
        ORDER BY e.event_id,d.cal_idx
        """
    ).fetch_df()
    connection.close()
    windows["trade_date"] = pd.to_datetime(windows.trade_date)
    windows["signal_date"] = pd.to_datetime(windows.signal_date)
    if windows.event_id.nunique() != len(candidates):
        raise ResearchError("chart window misses a candidate")
    if windows.trade_date.max() >= pd.Timestamp("2022-01-01"):
        raise ResearchError("chart window opened 2022 or later")
    return windows


def event_features(event: pd.Series, frame: pd.DataFrame, outcome: pd.Series, same_date_n: int) -> dict[str, Any]:
    valid = frame.loc[
        frame.current_valid.fillna(False)
        & frame[["coord_open", "coord_high", "coord_low", "coord_close"]].notna().all(axis=1)
    ].sort_values("cal_idx", kind="mergesort")
    signal = valid.loc[valid.cal_idx.eq(int(event.cal_idx))]
    if len(signal) != 1:
        raise ResearchError(f"{event.event_id}: non-unique signal bar")
    before = valid.loc[valid.cal_idx.lt(int(event.cal_idx))].tail(PRE)
    peak = float(event.prior250_peak_high)
    last20 = before.tail(20)
    last60 = before.tail(60)
    close20 = last20.coord_close.astype(float)
    close60 = last60.coord_close.astype(float)
    recent_peak_tests = int(((last60.coord_high >= 0.98 * peak) & (last60.coord_low <= 1.02 * peak)).sum())
    recent_peak_closes = int((last60.coord_close >= 0.98 * peak).sum())
    pre20_return = float(close20.iloc[-1] / close20.iloc[0] - 1.0) if len(close20) >= 2 else math.nan
    pre60_return = float(close60.iloc[-1] / close60.iloc[0] - 1.0) if len(close60) >= 2 else math.nan
    pre20_width = float(last20.coord_high.max() / last20.coord_low.min() - 1.0) if not last20.empty else math.nan
    pre60_width = float(last60.coord_high.max() / last60.coord_low.min() - 1.0) if not last60.empty else math.nan
    pre20_path = float(abs(pre20_return) / close20.pct_change().abs().sum()) if len(close20) >= 2 and close20.pct_change().abs().sum() > 0 else math.nan
    last_close_to_peak = float(close20.iloc[-1] / peak - 1.0) if not close20.empty else math.nan
    turnover_mean = float(last20.turnover_fraction.mean()) if not last20.empty else math.nan
    pre5_turnover = float(last20.turnover_fraction.tail(5).mean() / turnover_mean) if math.isfinite(turnover_mean) and turnover_mean > 0 else math.nan
    status = str(outcome.status)
    net_return = safe_float(outcome.net_return)
    return {
        **event.to_dict(),
        "signal_year": int(pd.Timestamp(event.signal_date).year),
        "same_date_signals": int(same_date_n),
        "pre_chart_valid_sessions": int(len(before)),
        "pre20_return": pre20_return,
        "pre60_return": pre60_return,
        "pre20_range_width": pre20_width,
        "pre60_range_width": pre60_width,
        "pre20_close_efficiency": pre20_path,
        "last_close_to_stale_high": last_close_to_peak,
        "pre60_stale_high_touch_sessions": recent_peak_tests,
        "pre60_near_stale_high_close_sessions": recent_peak_closes,
        "pre5_turnover_vs_pre20": pre5_turnover,
        "status": status,
        "entry_date": outcome.entry_date,
        "entry_price": safe_float(outcome.entry_price),
        "exit_date": outcome.exit_date,
        "exit_price": safe_float(outcome.exit_price),
        "exit_reason": str(outcome.exit_reason),
        "holding_sessions": safe_float(outcome.holding_sessions),
        "net_return": net_return,
        "outcome_bucket": outcome_bucket(status, net_return),
    }


def build_ledger(candidates: pd.DataFrame, outcomes: pd.DataFrame, windows: pd.DataFrame) -> pd.DataFrame:
    outcome_map = {str(row.event_id): row for _, row in outcomes.iterrows()}
    window_map = {key: part for key, part in windows.groupby("event_id", sort=False)}
    same_date = candidates.groupby("signal_date").size().to_dict()
    rows = [
        event_features(
            event,
            window_map[str(event.event_id)],
            outcome_map[str(event.event_id)],
            int(same_date[pd.Timestamp(event.signal_date)]),
        )
        for _, event in candidates.iterrows()
    ]
    ledger = pd.DataFrame(rows).sort_values(
        ["signal_date", "sleeve", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    ledger["chart_number"] = np.arange(1, len(ledger) + 1, dtype=int)
    return ledger


def render_chart(event: pd.Series, frame: pd.DataFrame, output: Path) -> None:
    signal_date = pd.Timestamp(event.signal_date)
    signal = frame.loc[frame.trade_date.eq(signal_date)]
    if len(signal) != 1:
        raise ResearchError(f"{event.event_id}: chart signal bar missing")
    signal_close = float(signal.iloc[0].coord_close)
    figure, (price_ax, volume_ax) = charts.plt.subplots(
        2, 1, figsize=(13.2, 7.4), gridspec_kw={"height_ratios": [4.4, 1.0], "hspace": 0.05}, sharex=True
    )
    charts.draw_candles(price_ax, frame, signal_close)
    signal_x = charts.mdates.date2num(signal_date.to_pydatetime())
    stale_y = float(event.prior250_peak_high) * 100.0 / signal_close
    price_ax.axvline(signal_x, color="#b45309", linewidth=1.3, label="stale-high breakout")
    price_ax.axhline(stale_y, color="#1f77b4", linewidth=1.0, linestyle="--", label="pre-existing stale high")
    if pd.notna(event.entry_date) and math.isfinite(float(event.entry_price)):
        entry_x = charts.mdates.date2num(pd.Timestamp(event.entry_date).to_pydatetime())
        entry_y = float(event.entry_price) * 100.0 / signal_close
        price_ax.scatter(entry_x, entry_y, marker="^", s=65, color="#7b2cbf", zorder=8, label="entry")
        price_ax.axhline(entry_y * 1.20, color="#ff7f0e", linewidth=0.8, linestyle=":", label="+20% target")
    if pd.notna(event.exit_date) and math.isfinite(float(event.exit_price)):
        exit_x = charts.mdates.date2num(pd.Timestamp(event.exit_date).to_pydatetime())
        exit_y = float(event.exit_price) * 100.0 / signal_close
        price_ax.scatter(exit_x, exit_y, marker="v", s=65, color="#111111", zorder=8, label="exit")
    regime = str(event.market_regime)
    result = str(event.outcome_bucket)
    if math.isfinite(float(event.net_return)):
        result += f" | net {float(event.net_return):+.2%} | {event.exit_reason}"
    price_ax.set_title(
        f"{int(event.chart_number):04d} | {event.symbol} | {signal_date.date()} | causal {regime} | {result}\n"
        f"old-high age {int(event.peak_age_sessions)} | prior20/60 {float(event.pre20_return):+.1%}/{float(event.pre60_return):+.1%} | "
        f"signal {float(event.step_return):+.1%} | turnover {float(event.turnover_expansion):.1f}x | "
        f"market r20/r60 {float(event.market_median_ret20):+.1%}/{float(event.market_median_ret60):+.1%} | same-date {int(event.same_date_signals)}",
        fontsize=9.7,
    )
    price_ax.set_ylabel("Coordinate price (signal close=100)")
    price_ax.grid(alpha=0.17, linewidth=0.5)
    handles, labels = price_ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles, strict=False))
    price_ax.legend(by_label.values(), by_label.keys(), loc="upper left", ncol=5, fontsize=7.0)
    valid_turn = frame.loc[frame.turnover_fraction.notna()].copy()
    turn_dates = charts.mdates.date2num(pd.to_datetime(valid_turn.trade_date).to_numpy())
    volume_ax.bar(turn_dates, valid_turn.turnover_fraction * 100.0, width=0.75, color="#888888", alpha=0.55)
    volume_ax.axvline(signal_x, color="#b45309", linewidth=1.0)
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
        "net_return": safe_float(event.net_return),
        "chart_path": str(output),
    }


def build_nine_up(index: pd.DataFrame) -> list[Path]:
    output_paths: list[Path] = []
    bucket_order = ["SEVERE_LOSS", "LOSS_0_TO_10PCT", "PROFIT_0_TO_4PCT", "PROFIT_GE_4PCT", "NO_COMPLETED_TRADE"]
    for bucket in bucket_order:
        rows = index.loc[index.outcome_bucket.eq(bucket)].sort_values(
            ["signal_date", "symbol", "event_id"], kind="mergesort"
        ).to_dict("records")
        target = SHEET_ROOT / bucket.lower()
        target.mkdir(parents=True, exist_ok=True)
        for start in range(0, len(rows), 9):
            group = rows[start : start + 9]
            canvas = Image.new("RGB", (3600, 2130), "white")
            draw = ImageDraw.Draw(canvas)
            for offset, row in enumerate(group):
                source = Image.open(row["chart_path"]).convert("RGB")
                source.thumbnail((1180, 680), Image.Resampling.LANCZOS)
                canvas.paste(source, (10 + (offset % 3) * 1195, 35 + (offset // 3) * 695))
                source.close()
            sheet_no = start // 9 + 1
            draw.text((15, 8), f"{bucket} | sheet {sheet_no:03d} | events {start + 1}-{start + len(group)}", fill="black")
            path = target / f"sheet_{sheet_no:03d}.jpg"
            canvas.save(path, "JPEG", quality=90, optimize=True)
            output_paths.append(path)
    return output_paths


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    complete = frame.loc[frame.status.eq("COMPLETED")].copy()
    return {
        "signals": int(len(frame)),
        "completed": int(len(complete)),
        "dates": int(frame.signal_date.nunique()),
        "mean_net": float(complete.net_return.mean()),
        "median_net": float(complete.net_return.median()),
        "positive_rate": float(complete.net_return.gt(0).mean()),
        "ge_4pct_rate": float(complete.net_return.ge(0.04).mean()),
        "severe_loss_rate": float(complete.net_return.le(-0.10).mean()),
        "target_hit_rate": float(complete.exit_reason.eq("TARGET_10").mean()),
    }


def run(workers: int, skip_render: bool) -> dict[str, Any]:
    for path in (FREEZE, CANDIDATES, DISCOVERY_OUTCOMES, CONFIRMATION_OUTCOMES, DAILY, REGIME):
        if not path.is_file():
            raise ResearchError(f"missing required input: {path}")
    candidates, outcomes = load_sources()
    windows = load_windows(candidates)
    ledger = build_ledger(candidates, outcomes, windows)
    write_parquet(windows, WINDOW_PANEL)
    write_parquet(ledger, REVIEW_LEDGER)
    REVIEW_CSV.parent.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(REVIEW_CSV, index=False, float_format="%.10g")

    window_map = {key: part for key, part in windows.groupby("event_id", sort=False)}
    if not skip_render:
        tasks = []
        for _, event in ledger.iterrows():
            path = CHART_DIR / f"{int(event.chart_number):04d}_{event.symbol.replace('.', '_')}_{pd.Timestamp(event.signal_date):%Y%m%d}.png"
            tasks.append((event.to_dict(), window_map[str(event.event_id)], str(path)))
        with ProcessPoolExecutor(max_workers=max(1, workers)) as executor:
            index_rows = list(executor.map(render_worker, tasks, chunksize=1))
        index = pd.DataFrame(index_rows)
        index.to_csv(CHART_INDEX, index=False, float_format="%.10g")
        sheets = build_nine_up(index)
    else:
        if not CHART_INDEX.is_file():
            raise ResearchError("--skip-render requires existing chart_index.csv")
        index = pd.read_csv(CHART_INDEX, parse_dates=["signal_date"])
        sheets = sorted(SHEET_ROOT.glob("*/*.jpg"))

    annual = {
        str(year): metrics(part)
        for year, part in ledger.groupby(ledger.signal_date.dt.year, sort=True)
    }
    manifest = {
        "experiment": EXPERIMENT,
        "freeze_sha256": sha256(FREEZE),
        "source_candidate_sha256": sha256(CANDIDATES),
        "source_discovery_outcome_sha256": sha256(DISCOVERY_OUTCOMES),
        "source_confirmation_outcome_sha256": sha256(CONFIRMATION_OUTCOMES),
        "candidate_count": int(len(candidates)),
        "chart_count": int(len(index)),
        "outcome_sheet_count": int(len(sheets)),
        "outcome_bucket_counts": ledger.outcome_bucket.value_counts().sort_index().to_dict(),
        "annual": annual,
        "pooled": metrics(ledger),
        "max_signal_date": str(candidates.signal_date.max().date()),
        "max_chart_bar_date": str(windows.trade_date.max().date()),
        "market_state_source_after_decision_count": int(candidates.market_latest_source_timestamp.gt(candidates.decision_at).sum()),
        "post_2021_signal_or_outcome_read": False,
        "post_2021_chart_bar_read": False,
        "window_panel_sha256": sha256(WINDOW_PANEL),
        "review_ledger_sha256": sha256(REVIEW_LEDGER),
        "review_csv_sha256": sha256(REVIEW_CSV),
        "chart_index_sha256": sha256(CHART_INDEX),
    }
    write_json(MANIFEST, manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--skip-render", action="store_true")
    parser.add_argument("--print-result", action="store_true")
    args = parser.parse_args()
    result = run(args.workers, args.skip_render)
    if args.print_result:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
