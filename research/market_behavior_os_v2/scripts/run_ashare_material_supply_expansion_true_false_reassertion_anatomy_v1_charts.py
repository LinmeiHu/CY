#!/usr/bin/env python3
"""Render the fixed true-vs-false supply-reassertion anatomy corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
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


EXPERIMENT = "ASHARE-MATERIAL-SUPPLY-EXPANSION-TRUE-VS-FALSE-REASSERTION-ANATOMY-V1"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
PARENT_ROOT = DATA_ROOT / "ashare_material_supply_expansion_demand_reassertion_v1"
MOTHER_ROOT = DATA_ROOT / "ashare_material_circulating_supply_expansion_mother_v1"
PARENT_RESULT = PARENT_ROOT / "stage_2/result.json"
TRADES = PARENT_ROOT / "stage_2/trade_ledger.parquet"
WINDOWS = MOTHER_ROOT / "stage_c_charts/chart_window_panel.parquet"
OUTPUT_ROOT = PARENT_ROOT / "stage_3_true_false_anatomy"
REVIEW_LEDGER = OUTPUT_ROOT / "review_ledger.parquet"
REVIEW_CSV = OUTPUT_ROOT / "review_ledger.csv"
CHART_DIR = OUTPUT_ROOT / "individual_charts"
CHART_INDEX = OUTPUT_ROOT / "chart_index.csv"
SHEET_DIR = OUTPUT_ROOT / "contact_sheets_chronological"
MANIFEST = OUTPUT_ROOT / "manifest.json"
EXPECTED_TRADES = 525
EXPECTED_FAILURES = 385
EXPECTED_SURVIVORS = 140
MAXIMUM_CONTEXT_DATE = pd.Timestamp("2021-06-30")
EXPECTED_HASHES = {
    SPEC: "26b622ed41353d8d4b31faf00fe535fa17a934090e5c34408625a95dc0f6db6c",
    PARENT_RESULT: "76ac109c1bf7875f7d0da313df439f9eeb92430e41f9a8b9f73ee91884bd5339",
    TRADES: "b397d0208ae1de6b05f00dc42bbc70677bf1d88023c97d5ec1583c24f2116f85",
    WINDOWS: "edb7cd140cf50460f97afe8d4c0808fd915a06c512f5f2642ee9dc4ad4037e3c",
}


class ResearchError(RuntimeError):
    """Fail closed on corpus identity or chronology drift."""


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
        value = sha256(path)
        actual[str(path)] = value
        if value != expected:
            raise ResearchError(f"frozen input drift: {path}: {value} != {expected}")
    result = json.loads(PARENT_RESULT.read_text(encoding="utf-8"))
    if result.get("classification") != "DEVELOPMENT_GATE_FAIL_EXACT_RULE_CLOSED":
        raise ResearchError("parent result is not the frozen failed development result")
    if result.get("validation_2022_2024_outcome_read"):
        raise ResearchError("validation quarantine already violated")
    return actual


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.register("frame", frame)
    con.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()


def prior_return(frame: pd.DataFrame, signal_idx: int, sessions: int, signal_close: float) -> float:
    row = frame.loc[frame.cal_idx.eq(signal_idx - sessions)]
    if len(row) != 1 or pd.isna(row.iloc[0].coord_close) or float(row.iloc[0].coord_close) <= 0:
        return math.nan
    return signal_close / float(row.iloc[0].coord_close) - 1.0


def build_review_ledger(trades: pd.DataFrame, windows: pd.DataFrame) -> pd.DataFrame:
    groups = {key: part.sort_values("cal_idx", kind="mergesort") for key, part in windows.groupby("event_id", sort=False)}
    rows: list[dict[str, Any]] = []
    ordered = trades.sort_values(["signal_date", "pit_industry", "symbol"], kind="mergesort")
    for trade in ordered.itertuples(index=False):
        frame = groups[str(trade.event_id)]
        signal_idx = int(trade.signal_cal_idx)
        trigger_idx = int(trade.trigger_cal_idx)
        signal = frame.loc[frame.cal_idx.eq(signal_idx)]
        trigger = frame.loc[frame.cal_idx.eq(trigger_idx)]
        if len(signal) != 1 or len(trigger) != 1:
            raise ResearchError(f"{trade.event_id}: event or trigger row is not unique")
        signal_close = float(signal.iloc[0].coord_close)
        event_turn = charts.safe_float(signal.iloc[0].turnover_fraction)
        trigger_turn = charts.safe_float(trigger.iloc[0].turnover_fraction)
        absorption = frame.loc[frame.cal_idx.between(signal_idx + 1, signal_idx + 5)]
        absorption_turn = float(absorption.turnover_fraction.median()) if absorption.turnover_fraction.notna().any() else math.nan
        rows.append(
            {
                "chart_number": 0,
                "event_id": str(trade.event_id),
                "symbol": str(trade.symbol),
                "pit_industry": str(trade.pit_industry),
                "signal_date": pd.Timestamp(trade.signal_date),
                "signal_year": int(trade.signal_year),
                "signal_cal_idx": signal_idx,
                "trigger_date": pd.Timestamp(trade.trigger_date),
                "trigger_cal_idx": trigger_idx,
                "entry_date": pd.Timestamp(trade.entry_date),
                "entry_cal_idx": int(trade.entry_cal_idx),
                "exit_date": pd.Timestamp(trade.exit_date),
                "exit_cal_idx": int(trade.exit_cal_idx),
                "exit_reason": str(trade.exit_reason),
                "net_return": float(trade.net_return),
                "holding_market_sessions": int(trade.holding_market_sessions),
                "event_low": float(trade.event_low),
                "event_high": float(trade.event_high),
                "event_close": float(trade.event_close),
                "event_to_trigger_sessions": trigger_idx - signal_idx,
                "trigger_margin_over_event_high": float(trigger.iloc[0].coord_close) / float(trade.event_high) - 1.0,
                "trigger_stock_minus_industry_return": float(trade.trigger_stock_return_from_event) - float(trade.trigger_industry_return_from_event),
                "trigger_market_regime": str(trade.trigger_market_regime),
                "event_turnover": event_turn,
                "absorption_median_turnover": absorption_turn,
                "trigger_turnover": trigger_turn,
                "trigger_to_absorption_turnover_ratio": trigger_turn / absorption_turn if math.isfinite(trigger_turn) and math.isfinite(absorption_turn) and absorption_turn > 0 else math.nan,
                "pre20_return": prior_return(frame, signal_idx, 20, signal_close),
                "pre60_return": prior_return(frame, signal_idx, 60, signal_close),
                "reviewed": False,
                "pre_entry_visual_note": "",
                "post_entry_descriptive_note": "",
            }
        )
    ledger = pd.DataFrame(rows)
    ledger["chart_number"] = np.arange(1, len(ledger) + 1, dtype=int)
    return ledger


def render_chart(event: pd.Series, frame: pd.DataFrame, output: Path) -> None:
    signal_date = pd.Timestamp(event.signal_date)
    signal_close = float(event.event_close)
    figure, (price_ax, volume_ax) = charts.plt.subplots(
        2,
        1,
        figsize=(13.2, 7.4),
        gridspec_kw={"height_ratios": [4.4, 1.0], "hspace": 0.05},
        sharex=True,
    )
    charts.draw_candles(price_ax, frame, signal_close)
    marker_specs = (
        (signal_date, "#b45309", "supply event"),
        (pd.Timestamp(event.trigger_date), "#dc2626", "trigger close"),
        (pd.Timestamp(event.entry_date), "#7b2cbf", "entry open"),
        (pd.Timestamp(event.exit_date), "#111111", "exit open"),
    )
    for date, color, label in marker_specs:
        price_ax.axvline(charts.mdates.date2num(date.to_pydatetime()), color=color, linewidth=1.15, label=label)
    price_ax.axhline(float(event.event_high) * 100 / signal_close, color="#b45309", linewidth=0.8, linestyle="--", label="event high")
    price_ax.axhline(float(event.event_low) * 100 / signal_close, color="#2563eb", linewidth=0.8, linestyle="--", label="event low")
    title_class = "DURABLE_TO_H120" if str(event.exit_reason) == "TIME_EXIT_H120" else "EVENT_LOW_FAILURE"
    price_ax.set_title(
        f"{int(event.chart_number):04d} | {event.symbol} | {signal_date.date()} | {event.pit_industry} | {event.trigger_market_regime} | {title_class} | net {float(event.net_return):+.1%}\n"
        f"event->trigger {int(event.event_to_trigger_sessions)}d | trigger high margin {float(event.trigger_margin_over_event_high):+.1%} | "
        f"stock-industry edge {float(event.trigger_stock_minus_industry_return):+.1%} | turnover event/absorb/trigger "
        f"{float(event.event_turnover):.1%}/{float(event.absorption_median_turnover):.1%}/{float(event.trigger_turnover):.1%} | "
        f"pre20/pre60 {float(event.pre20_return):+.1%}/{float(event.pre60_return):+.1%}",
        fontsize=8.5,
    )
    price_ax.set_ylabel("Coordinate price (event close=100)")
    price_ax.grid(alpha=0.17, linewidth=0.5)
    handles, labels = price_ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles, strict=False))
    price_ax.legend(by_label.values(), by_label.keys(), loc="upper left", ncol=6, fontsize=6.5)

    valid_turn = frame.loc[frame.turnover_fraction.notna()].copy()
    turn_dates = charts.mdates.date2num(pd.to_datetime(valid_turn.trade_date).to_numpy())
    volume_ax.bar(turn_dates, valid_turn.turnover_fraction * 100, width=0.75, color="#8b8b8b", alpha=0.60)
    for date, color, _ in marker_specs:
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
    figure.savefig(output, dpi=105, bbox_inches="tight", facecolor="white", metadata={"Creator": EXPERIMENT, "Title": str(event.event_id)})
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
        "exit_reason": str(event.exit_reason),
        "net_return": float(event.net_return),
        "chart_path": str(output),
    }


def build_nine_up(index: pd.DataFrame) -> list[Path]:
    SHEET_DIR.mkdir(parents=True, exist_ok=True)
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
        draw.text((15, 8), f"{EXPERIMENT} | sheet {number:03d} | trades {start + 1}-{start + len(group)}", fill="black")
        target = SHEET_DIR / f"sheet_{number:03d}.jpg"
        canvas.save(target, "JPEG", quality=90, optimize=True)
        paths.append(target)
    return paths


def run(workers: int) -> dict[str, Any]:
    source_hashes = verify_inputs()
    trades = pd.read_parquet(TRADES)
    windows = pd.read_parquet(WINDOWS)
    for column in ("signal_date", "trigger_date", "entry_date", "exit_date"):
        trades[column] = pd.to_datetime(trades[column])
    for column in ("signal_date", "trade_date", "available_at", "decision_at"):
        windows[column] = pd.to_datetime(windows[column])
    if len(trades) != EXPECTED_TRADES or trades.event_id.duplicated().any():
        raise ResearchError("fixed trade corpus identity drift")
    counts = trades.exit_reason.value_counts()
    if int(counts.get("EVENT_LOW_FAILURE", 0)) != EXPECTED_FAILURES or int(counts.get("TIME_EXIT_H120", 0)) != EXPECTED_SURVIVORS:
        raise ResearchError("true-vs-false label counts drifted")
    if trades.signal_year.gt(2020).any() or windows.trade_date.max() > MAXIMUM_CONTEXT_DATE:
        raise ResearchError("development chronology cap violated")
    windows = windows.loc[windows.event_id.isin(trades.event_id)].copy()
    if windows.event_id.nunique() != EXPECTED_TRADES:
        raise ResearchError("chart window misses a fixed completed trade")

    ledger = build_review_ledger(trades, windows)
    write_parquet(ledger, REVIEW_LEDGER)
    REVIEW_CSV.parent.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(REVIEW_CSV, index=False, float_format="%.10g")
    groups = {key: part for key, part in windows.groupby("event_id", sort=False)}
    tasks = []
    for _, event in ledger.iterrows():
        target = CHART_DIR / f"{int(event.chart_number):05d}_{event.symbol.replace('.', '_')}_{pd.Timestamp(event.signal_date):%Y%m%d}.png"
        tasks.append((event.to_dict(), groups[str(event.event_id)], str(target)))
    with ProcessPoolExecutor(max_workers=max(1, workers)) as executor:
        index = pd.DataFrame(list(executor.map(render_worker, tasks, chunksize=2)))
    index = index.sort_values("chart_number", kind="mergesort")
    index.to_csv(CHART_INDEX, index=False, float_format="%.10g")
    sheets = build_nine_up(index)
    manifest = {
        "experiment": EXPERIMENT,
        "stage": "FIXED_POST_HOC_VISUAL_ANATOMY_CORPUS",
        "source_hashes": source_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "review_ledger": str(REVIEW_LEDGER),
        "review_ledger_sha256": sha256(REVIEW_LEDGER),
        "charts": int(len(index)),
        "chronological_contact_sheets": int(len(sheets)),
        "event_low_failures": int(index.exit_reason.eq("EVENT_LOW_FAILURE").sum()),
        "durable_to_h120": int(index.exit_reason.eq("TIME_EXIT_H120").sum()),
        "annual_or_pooled_return_aggregate_produced": False,
        "post_2021_signal_identity_read": False,
        "validation_2022_2024_outcome_read": False,
        "maximum_context_date": str(windows.trade_date.max().date()),
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
