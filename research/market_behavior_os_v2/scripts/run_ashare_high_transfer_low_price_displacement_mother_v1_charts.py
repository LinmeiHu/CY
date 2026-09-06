#!/usr/bin/env python3
"""Render every frozen high-transfer/low-displacement event for visual review."""

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


EXPERIMENT = "ASHARE-HIGH-TRANSFER-LOW-PRICE-DISPLACEMENT-MOTHER-V1"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
STAGE_A_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_high_transfer_low_price_displacement_mother_v1_stage_a.py"
)
STAGE_B_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_high_transfer_low_price_displacement_mother_v1_stage_b.py"
)
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
DAILY = DATA_ROOT / (
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
OUTPUT_ROOT = DATA_ROOT / "ashare_high_transfer_low_price_displacement_mother_v1"
STAGE_A_FREEZE = OUTPUT_ROOT / "stage_a/stage_a_freeze.json"
CANDIDATES = OUTPUT_ROOT / "stage_a/candidates_frozen.parquet"
STAGE_B_MANIFEST = OUTPUT_ROOT / "stage_b/manifest.json"
PATHS = OUTPUT_ROOT / "stage_b/future_paths_through_2020.parquet"
OUTCOMES = OUTPUT_ROOT / "stage_b/outcome_labels.parquet"
CHART_ROOT = OUTPUT_ROOT / "stage_c_charts"
WINDOW_PANEL = CHART_ROOT / "chart_window_panel.parquet"
REVIEW_LEDGER = CHART_ROOT / "review_ledger.parquet"
REVIEW_CSV = CHART_ROOT / "review_ledger.csv"
CHART_DIR = CHART_ROOT / "individual_charts"
CHART_INDEX = CHART_ROOT / "chart_index.csv"
SHEET_DIR = CHART_ROOT / "contact_sheets_chronological"
OUTCOME_SHEET_ROOT = CHART_ROOT / "contact_sheets_by_outcome"
MANIFEST = CHART_ROOT / "manifest.json"
EXPECTED_EVENTS = 6115
EXPECTED_HASHES = {
    SPEC: "b719e13f77109cfd3f46ed1c8bc4ac312e190ef9c75d7e1b6e257dba5cbc4630",
    STAGE_A_RUNNER: "aefd4930049f14aae3cc5a35f09251a80bc08fee86b5459d8691dcccd6a37027",
    STAGE_B_RUNNER: "73a0882b6ff99e736eba6f66566c0df1598e38d11b112aba4e2d098e101cb803",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    STAGE_A_FREEZE: "3727217e6af92323efc8dc43ea1f2343fe81e7ccc13c6084c4e1ab4fa6bad8fc",
    CANDIDATES: "c2c2a61393563c7aa78fa06d2562df6f1fe6e8bd957b54ca6d97c03630aa0295",
    STAGE_B_MANIFEST: "fb49bc7c86e78b6a5c3057ded9dd22069e0402701ed7d9da392bdd80fcf6047d",
    PATHS: "e0004c8eaef11353cecba4f2269c7404ad724856b42baaa09276162976d60325",
    OUTCOMES: "7a29520435162772aa827ba6ca1a5e9121a368eddb9bbff4e37da9a8cce36514",
}


class ResearchError(RuntimeError):
    """Fail closed on frozen identity or chart chronology drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inputs() -> dict[str, str]:
    actual: dict[str, str] = {}
    for path, expected in EXPECTED_HASHES.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input: {path}")
        actual[str(path)] = sha256(path)
        if actual[str(path)] != expected:
            raise ResearchError(
                f"frozen input drift: {path}: {actual[str(path)]} != {expected}"
            )
    return actual


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.register("frame", frame)
    con.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    candidates = pd.read_parquet(CANDIDATES)
    outcomes = pd.read_parquet(OUTCOMES)
    for column in (
        "signal_date", "decision_at", "available_at", "market_latest_source_timestamp"
    ):
        candidates[column] = pd.to_datetime(candidates[column])
    date_columns = [
        "signal_date", "entry_date", "h5_exit_date", "h20_exit_date",
        "h60_exit_date", "h120_exit_date",
    ]
    for column in date_columns:
        outcomes[column] = pd.to_datetime(outcomes[column])
    if len(candidates) != EXPECTED_EVENTS or candidates.event_id.duplicated().any():
        raise ResearchError("candidate identity drift")
    if len(outcomes) != EXPECTED_EVENTS or outcomes.event_id.duplicated().any():
        raise ResearchError("outcome-label identity drift")
    con = duckdb.connect()
    con.register(
        "chart_keys",
        candidates[["event_id", "symbol", "signal_cal_idx", "signal_date"]],
    )
    windows = con.execute(
        f"""
        SELECT k.event_id,k.signal_date,d.symbol,d.trade_date,d.cal_idx,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.turnover_fraction,
          d.step_return,d.trade_status,d.current_day_data_tradable,
          d.current_valid,d.hard_valid,d.available_at,d.decision_at
        FROM read_parquet('{DAILY.as_posix()}') d
        JOIN chart_keys k ON d.symbol=k.symbol
          AND d.cal_idx BETWEEN k.signal_cal_idx-126 AND k.signal_cal_idx+126
        WHERE d.trade_date<=DATE '2020-12-31'
        ORDER BY k.event_id,d.cal_idx
        """
    ).fetch_df()
    con.close()
    for column in ("signal_date", "trade_date", "available_at", "decision_at"):
        windows[column] = pd.to_datetime(windows[column])
    if windows.event_id.nunique() != EXPECTED_EVENTS:
        raise ResearchError("chart window misses a frozen event")
    if windows.trade_date.max() > pd.Timestamp("2020-12-31"):
        raise ResearchError("chart context crossed the frozen cap")
    latest = candidates[["available_at", "market_latest_source_timestamp"]].max(axis=1)
    if latest.gt(candidates.decision_at).any():
        raise ResearchError("signal annotation arrived after decision_at")
    return candidates, outcomes, windows


def outcome_bucket(status: str, net_return: float) -> str:
    if status != "COMPLETED" or not math.isfinite(net_return):
        return "NO_COMPLETED_TRADE"
    if net_return >= 0.04:
        return "PROFIT_GE_4PCT"
    if net_return >= 0:
        return "PROFIT_0_TO_4PCT"
    if net_return > -0.10:
        return "LOSS_0_TO_10PCT"
    return "SEVERE_LOSS"


def build_ledger(
    candidates: pd.DataFrame, outcomes: pd.DataFrame, windows: pd.DataFrame
) -> pd.DataFrame:
    merged = candidates.merge(outcomes, on=["event_id", "symbol", "sleeve", "causal_industry", "signal_date", "signal_cal_idx"], how="left", validate="one_to_one")
    window_lookup = {key: part for key, part in windows.groupby("event_id", sort=False)}
    rows: list[dict[str, Any]] = []
    ordered = merged.sort_values(["signal_date", "symbol", "event_id"], kind="mergesort")
    for event in ordered.itertuples(index=False):
        frame = window_lookup[str(event.event_id)]
        valid = frame.loc[
            frame.current_valid.fillna(False)
            & frame[["coord_open", "coord_high", "coord_low", "coord_close"]]
            .notna().all(axis=1)
        ].sort_values("cal_idx", kind="mergesort")
        signal = valid.loc[valid.cal_idx.eq(int(event.signal_cal_idx))]
        if len(signal) != 1:
            raise ResearchError(f"{event.event_id}: chart signal row not unique")
        signal_close = float(signal.iloc[0].coord_close)
        pre = valid.loc[valid.cal_idx.lt(int(event.signal_cal_idx))].tail(126)
        prior_high = float(pre.coord_high.max()) if not pre.empty else math.nan
        prior_low = float(pre.coord_low.min()) if not pre.empty else math.nan
        h120_net = charts.safe_float(event.h120_net_return)
        rows.append(
            {
                "event_id": str(event.event_id),
                "symbol": str(event.symbol),
                "sleeve": str(event.sleeve),
                "causal_industry": str(event.causal_industry),
                "signal_date": pd.Timestamp(event.signal_date),
                "signal_year": int(pd.Timestamp(event.signal_date).year),
                "signal_cal_idx": int(event.signal_cal_idx),
                "chart_number": 0,
                "market_regime": str(event.market_regime),
                "market_median_ret20": float(event.market_median_ret20),
                "market_median_ret60": float(event.market_median_ret60),
                "market_positive_ret20_share": float(event.market_positive_ret20_share),
                "market_positive_ret60_share": float(event.market_positive_ret60_share),
                "signal_turnover_fraction": float(event.turnover_fraction),
                "signal_turnover_ratio": float(event.turnover_ratio),
                "signal_step_return": float(event.step_return),
                "signal_intraday_range": float(event.intraday_range),
                "signal_close_location": charts.safe_float(event.close_location),
                "ret20": charts.safe_float(event.ret20),
                "ret60": charts.safe_float(event.ret60),
                "ret120": charts.safe_float(event.ret120),
                "pre126_return": (
                    signal_close / float(pre.coord_close.iloc[0]) - 1
                    if not pre.empty else math.nan
                ),
                "pre126_position": (
                    (signal_close - prior_low) / (prior_high - prior_low)
                    if math.isfinite(prior_high) and prior_high > prior_low else math.nan
                ),
                "status": str(event.status),
                "entry_date": pd.Timestamp(event.entry_date),
                "entry_price": charts.safe_float(event.entry_price),
                "h5_net_return": charts.safe_float(event.h5_net_return),
                "h20_net_return": charts.safe_float(event.h20_net_return),
                "h60_net_return": charts.safe_float(event.h60_net_return),
                "h120_net_return": h120_net,
                "h120_mfe": charts.safe_float(event.h120_mfe),
                "h120_mae": charts.safe_float(event.h120_mae),
                "h120_exit_date": pd.Timestamp(event.h120_exit_date),
                "h120_exit_price": charts.safe_float(event.h120_exit_price),
                "h120_industry_median_compound": charts.safe_float(
                    event.h120_industry_median_compound_from_signal
                ),
                "outcome_bucket": outcome_bucket(str(event.status), h120_net),
                "reviewed": False,
                "review_sheet": "",
                "visual_note": "",
            }
        )
    ledger = pd.DataFrame(rows)
    ledger["chart_number"] = np.arange(1, len(ledger) + 1, dtype=int)
    return ledger


def render_chart(event: pd.Series, frame: pd.DataFrame, output: Path) -> None:
    signal_date = pd.Timestamp(event.signal_date)
    signal = frame.loc[frame.trade_date.eq(signal_date)]
    if len(signal) != 1:
        raise ResearchError(f"{event.event_id}: signal row not unique")
    signal_close = float(signal.iloc[0].coord_close)
    signal_high = float(signal.iloc[0].coord_high) * 100 / signal_close
    signal_low = float(signal.iloc[0].coord_low) * 100 / signal_close
    figure, (price_ax, volume_ax) = charts.plt.subplots(
        2,
        1,
        figsize=(13.2, 7.4),
        gridspec_kw={"height_ratios": [4.4, 1.0], "hspace": 0.05},
        sharex=True,
    )
    charts.draw_candles(price_ax, frame, signal_close)
    signal_x = charts.mdates.date2num(signal_date.to_pydatetime())
    price_ax.axvline(signal_x, color="#b45309", linewidth=1.4, label="transfer event")
    price_ax.axhline(signal_high, color="#b45309", linewidth=0.8, linestyle="--", label="event high")
    price_ax.axhline(signal_low, color="#2563eb", linewidth=0.8, linestyle="--", label="event low")
    if pd.notna(event.entry_date) and math.isfinite(float(event.entry_price)):
        x = charts.mdates.date2num(pd.Timestamp(event.entry_date).to_pydatetime())
        price_ax.scatter(x, float(event.entry_price) * 100 / signal_close, marker="^", s=62, color="#7b2cbf", zorder=8, label="label entry")
    if pd.notna(event.h120_exit_date) and math.isfinite(float(event.h120_exit_price)):
        x = charts.mdates.date2num(pd.Timestamp(event.h120_exit_date).to_pydatetime())
        price_ax.scatter(x, float(event.h120_exit_price) * 100 / signal_close, marker="v", s=62, color="#111111", zorder=8, label="H120 label")
    status = str(event.outcome_bucket)
    if math.isfinite(float(event.h120_net_return)):
        status += f" | H120 {float(event.h120_net_return):+.1%}"
    price_ax.set_title(
        f"{int(event.chart_number):04d} | {event.symbol} | {signal_date.date()} | {event.market_regime} | {status}\n"
        f"turn {float(event.signal_turnover_fraction):.1%} / {float(event.signal_turnover_ratio):.1f}x | "
        f"event ret {float(event.signal_step_return):+.1%} range {float(event.signal_intraday_range):.1%} close-loc {float(event.signal_close_location):.0%} | "
        f"pre r20/r60/r120 {float(event.ret20):+.1%}/{float(event.ret60):+.1%}/{float(event.ret120):+.1%} | "
        f"H5/H20/H60 {float(event.h5_net_return):+.1%}/{float(event.h20_net_return):+.1%}/{float(event.h60_net_return):+.1%} | "
        f"MFE/MAE {float(event.h120_mfe):+.1%}/{float(event.h120_mae):+.1%}",
        fontsize=8.9,
    )
    price_ax.set_ylabel("Coordinate price (signal close=100)")
    price_ax.grid(alpha=0.17, linewidth=0.5)
    handles, labels = price_ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles, strict=False))
    price_ax.legend(by_label.values(), by_label.keys(), loc="upper left", ncol=5, fontsize=6.7)
    valid_turn = frame.loc[frame.turnover_fraction.notna()].copy()
    turn_dates = charts.mdates.date2num(pd.to_datetime(valid_turn.trade_date).to_numpy())
    colors = np.where(valid_turn.trade_date.eq(signal_date), "#b45309", "#8b8b8b")
    volume_ax.bar(turn_dates, valid_turn.turnover_fraction * 100, width=0.75, color=colors, alpha=0.60)
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
    render_chart(event, frame, output)
    return {
        "chart_number": int(event.chart_number),
        "event_id": str(event.event_id),
        "symbol": str(event.symbol),
        "signal_date": pd.Timestamp(event.signal_date),
        "signal_year": int(event.signal_year),
        "market_regime": str(event.market_regime),
        "outcome_bucket": str(event.outcome_bucket),
        "h120_net_return": charts.safe_float(event.h120_net_return),
        "chart_path": str(output),
    }


def build_nine_up(index: pd.DataFrame, root: Path, prefix: str) -> list[Path]:
    root.mkdir(parents=True, exist_ok=True)
    records = index.to_dict("records")
    paths: list[Path] = []
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
            f"{prefix} | sheet {number:03d} | events {start + 1}-{start + len(group)}",
            fill="black",
        )
        target = root / f"sheet_{number:03d}.jpg"
        canvas.save(target, "JPEG", quality=90, optimize=True)
        paths.append(target)
    return paths


def run(workers: int, skip_render: bool) -> dict[str, Any]:
    source_hashes = verify_inputs()
    candidates, outcomes, windows = load_inputs()
    ledger = build_ledger(candidates, outcomes, windows)
    write_parquet(windows, WINDOW_PANEL)
    write_parquet(ledger, REVIEW_LEDGER)
    REVIEW_CSV.parent.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(REVIEW_CSV, index=False, float_format="%.10g")
    contact_sheets: list[Path] = []
    outcome_sheets: list[Path] = []
    if not skip_render:
        groups = {key: part for key, part in windows.groupby("event_id", sort=False)}
        tasks = []
        for _, event in ledger.iterrows():
            target = CHART_DIR / (
                f"{int(event.chart_number):05d}_{event.symbol.replace('.', '_')}_"
                f"{pd.Timestamp(event.signal_date):%Y%m%d}.png"
            )
            tasks.append((event.to_dict(), groups[str(event.event_id)], str(target)))
        with ProcessPoolExecutor(max_workers=max(1, workers)) as executor:
            index = pd.DataFrame(list(executor.map(render_worker, tasks, chunksize=2)))
        index = index.sort_values("chart_number", kind="mergesort")
        index.to_csv(CHART_INDEX, index=False, float_format="%.10g")
        contact_sheets = build_nine_up(index, SHEET_DIR, f"{EXPERIMENT} CHRONOLOGICAL")
        for bucket in (
            "SEVERE_LOSS", "LOSS_0_TO_10PCT", "PROFIT_0_TO_4PCT",
            "PROFIT_GE_4PCT", "NO_COMPLETED_TRADE",
        ):
            subset = index.loc[index.outcome_bucket.eq(bucket)].sort_values(
                ["signal_date", "symbol", "event_id"], kind="mergesort"
            )
            outcome_sheets.extend(
                build_nine_up(subset, OUTCOME_SHEET_ROOT / bucket.lower(), bucket)
            )
    payload = {
        "experiment": EXPERIMENT,
        "stage": "FULL_FROZEN_MOTHER_CHART_CORPUS",
        "source_hashes": source_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "window_panel_sha256": sha256(WINDOW_PANEL),
        "review_ledger_sha256": sha256(REVIEW_LEDGER),
        "signals": int(len(candidates)),
        "charts": 0 if skip_render else int(len(candidates)),
        "chronological_contact_sheets": int(len(contact_sheets)),
        "outcome_contact_sheets": int(len(outcome_sheets)),
        "outcome_buckets": {
            str(key): int(value) for key, value in ledger.outcome_bucket.value_counts().items()
        },
        "maximum_signal_date": str(candidates.signal_date.max().date()),
        "maximum_chart_bar_date": str(windows.trade_date.max().date()),
        "all_chronological_sheets_reviewed": False,
        "2021_2024_signal_feature_or_outcome_read": "NO",
        "future_market_or_structure_function": False,
        "next_step": "REVIEW_ALL_CHRONOLOGICAL_SHEETS_BEFORE_ANY_RULE_FREEZE",
    }
    write_json(MANIFEST, payload)
    payload["manifest_sha256"] = sha256(MANIFEST)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--skip-render", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.workers, args.skip_render), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
