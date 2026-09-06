#!/usr/bin/env python3
"""Build deterministic twelve-month anatomy charts for the frozen panic-absorption mother.

This script is deliberately limited to source signals dated 2014-2021.  It
joins the already-frozen T10/H20 outcomes only to label the chart anatomy; it
does not construct or evaluate a new rule and it does not read 2024 data.
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
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402


ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-PANIC-ABSORPTION-12M-CHART-RULE-DISCOVERY-V1"

SOURCE_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_panic_gap_down_full_absorption_reversal_v1"
)
CANDIDATES = SOURCE_ROOT / "stage_a/freeze/frozen_candidates.parquet"
OUTCOMES = SOURCE_ROOT / "stage_b/outcomes.parquet"
DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)

EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_panic_absorption_12m_chart_rule_discovery_v1"
)
CHART_DIR = EXT_ROOT / "development_2014_2021/individual_charts"
SHEET_DIR = EXT_ROOT / "development_2014_2021/contact_sheets"
OUTCOME_SHEET_ROOT = EXT_ROOT / "development_2014_2021/review_sheets_by_outcome"
WINDOW_PANEL = EXT_ROOT / "development_2014_2021/chart_window_panel.parquet"
REVIEW_LEDGER = EXT_ROOT / "development_2014_2021/review_ledger.parquet"
REVIEW_CSV = EXT_ROOT / "development_2014_2021/review_ledger.csv"
CHART_INDEX = EXT_ROOT / "development_2014_2021/chart_index.csv"
PDF_BOOK = EXT_ROOT / "development_2014_2021/chart_book.pdf"
MANIFEST = EXT_ROOT / "development_2014_2021/chart_manifest.json"

CONTRACT = OS_ROOT / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_spec.json"

START = pd.Timestamp("2014-01-01")
END = pd.Timestamp("2021-12-31")
PRE = 126
POST = 126
PROFILE = "T10_H20_NO_STOP"


class ChartBuildError(RuntimeError):
    """Fail-closed chart-anatomy build error."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")


def read_duckdb(path: Path, where: str = "") -> pd.DataFrame:
    query = f"SELECT * FROM read_parquet('{path}')"
    if where:
        query += f" WHERE {where}"
    return duckdb.connect().execute(query).fetch_df()


def load_source() -> tuple[pd.DataFrame, pd.DataFrame]:
    candidates = read_duckdb(
        CANDIDATES,
        "signal_date >= DATE '2014-01-01' AND signal_date <= DATE '2021-12-31'",
    )
    outcomes = read_duckdb(OUTCOMES, f"profile = '{PROFILE}'")
    candidates["signal_date"] = pd.to_datetime(candidates.signal_date)
    outcomes["signal_date"] = pd.to_datetime(outcomes.signal_date)
    outcomes["entry_date"] = pd.to_datetime(outcomes.entry_date)
    outcomes["exit_date"] = pd.to_datetime(outcomes.exit_date)
    candidates = candidates.sort_values(
        ["signal_date", "sleeve", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    if len(candidates) != 625:
        raise ChartBuildError(f"expected 625 frozen candidates, got {len(candidates)}")
    if candidates.signal_date.min() < START or candidates.signal_date.max() > END:
        raise ChartBuildError("source signal date escaped frozen development period")
    if candidates.event_id.duplicated().any():
        raise ChartBuildError("duplicate frozen event_id")
    if outcomes.event_id.duplicated().any():
        raise ChartBuildError("duplicate selected-profile outcome")
    return candidates, outcomes


def load_windows(candidates: pd.DataFrame) -> pd.DataFrame:
    connection = duckdb.connect()
    connection.register(
        "candidate_ids",
        candidates[["event_id", "symbol", "cal_idx", "signal_date"]],
    )
    query = f"""
        SELECT
            c.event_id,
            c.signal_date,
            d.symbol,
            d.trade_date,
            d.cal_idx,
            d.coord_open,
            d.coord_high,
            d.coord_low,
            d.coord_close,
            d.turnover_fraction,
            d.current_day_data_tradable,
            d.current_valid,
            d.hard_valid,
            d.available_at,
            d.decision_at
        FROM read_parquet('{DAILY}') d
        INNER JOIN candidate_ids c
          ON d.symbol = c.symbol
         AND d.cal_idx BETWEEN c.cal_idx - {PRE} AND c.cal_idx + {POST}
        ORDER BY c.event_id, d.cal_idx
    """
    result = connection.execute(query).fetch_df()
    connection.close()
    result["trade_date"] = pd.to_datetime(result.trade_date)
    result["signal_date"] = pd.to_datetime(result.signal_date)
    if result.event_id.nunique() != len(candidates):
        raise ChartBuildError("daily chart window misses source event identities")
    if pd.to_datetime(result.trade_date).max() >= pd.Timestamp("2023-01-01"):
        raise ChartBuildError("chart window unexpectedly reads 2023 or later")
    return result


def safe_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    return number if math.isfinite(number) else math.nan


def outcome_bucket(status: str | None, net_return: float) -> str:
    if status != "COMPLETED" or not math.isfinite(net_return):
        return "NO_COMPLETED_TRADE"
    if net_return >= 0.04:
        return "PROFIT_GE_4PCT"
    if net_return >= 0.0:
        return "PROFIT_0_TO_4PCT"
    if net_return > -0.10:
        return "LOSS_0_TO_10PCT"
    return "SEVERE_LOSS"


def path_features(
    event: pd.Series,
    frame: pd.DataFrame,
    outcome: pd.Series | None,
    cluster_count: int,
) -> dict[str, Any]:
    ordered = frame.sort_values("cal_idx", kind="mergesort").copy()
    valid = ordered.loc[
        ordered.current_valid.fillna(False)
        & ordered[["coord_open", "coord_high", "coord_low", "coord_close"]]
        .notna()
        .all(axis=1)
    ].copy()
    signal_rows = valid.loc[valid.cal_idx == int(event.cal_idx)]
    if len(signal_rows) != 1:
        raise ChartBuildError(f"{event.event_id}: signal row not exactly one")
    signal = signal_rows.iloc[0]
    before = valid.loc[valid.cal_idx < int(event.cal_idx)].tail(PRE)
    after = valid.loc[valid.cal_idx > int(event.cal_idx)].head(POST)
    if len(before) < 20:
        raise ChartBuildError(f"{event.event_id}: fewer than 20 valid pre-signal bars")

    signal_close = float(signal.coord_close)
    prior20 = before.tail(20).copy()
    prior60 = before.tail(60).copy()
    returns20 = prior20.coord_close.pct_change().dropna()
    path_sum = float(returns20.abs().sum())
    endpoint = abs(float(prior20.coord_close.iloc[-1] / prior20.coord_close.iloc[0] - 1.0))
    efficiency = endpoint / path_sum if path_sum > 0 else math.nan
    prior_ranges = (prior20.coord_high - prior20.coord_low) / prior20.coord_close
    signal_range = float(signal.coord_high - signal.coord_low)
    body_fraction = (
        float((signal.coord_close - signal.coord_open) / signal_range)
        if signal_range > 0
        else math.nan
    )
    prior5_high = float(before.tail(5).coord_high.max())
    prior126_high = float(before.coord_high.max())
    prior126_low = float(before.coord_low.min())
    first_close = float(before.coord_close.iloc[0])
    turn_ratio = float(event.turnover_fraction / event.turn20)

    out_status = None if outcome is None else str(outcome.status)
    net_return = math.nan if outcome is None else safe_float(outcome.net_return)
    entry_date = pd.NaT if outcome is None else outcome.entry_date
    exit_date = pd.NaT if outcome is None else outcome.exit_date
    entry_price = math.nan if outcome is None else safe_float(outcome.entry_price)

    post_from_entry = after
    if pd.notna(entry_date):
        post_from_entry = valid.loc[valid.trade_date >= pd.Timestamp(entry_date)].head(20)
    max20 = math.nan
    min20 = math.nan
    ret5 = math.nan
    ret10 = math.nan
    ret20 = math.nan
    if math.isfinite(entry_price) and not post_from_entry.empty:
        max20 = float(post_from_entry.coord_high.max() / entry_price - 1.0)
        min20 = float(post_from_entry.coord_low.min() / entry_price - 1.0)
        closes = post_from_entry.coord_close.to_numpy(dtype=float)
        if len(closes) >= 5:
            ret5 = float(closes[4] / entry_price - 1.0)
        if len(closes) >= 10:
            ret10 = float(closes[9] / entry_price - 1.0)
        if len(closes) >= 20:
            ret20 = float(closes[19] / entry_price - 1.0)

    return {
        "event_id": str(event.event_id),
        "symbol": str(event.symbol),
        "sleeve": str(event.sleeve),
        "signal_date": pd.Timestamp(event.signal_date),
        "signal_year": int(pd.Timestamp(event.signal_date).year),
        "chart_number": 0,
        "cluster_signal_count": int(cluster_count),
        "ret20": float(event.ret20),
        "ret60": float(event.ret60),
        "pre126_return": float(signal_close / first_close - 1.0),
        "pre126_drawdown_from_high": float(signal_close / prior126_high - 1.0),
        "pre126_position": float(
            (signal_close - prior126_low) / (prior126_high - prior126_low)
        )
        if prior126_high > prior126_low
        else math.nan,
        "pre20_path_efficiency": efficiency,
        "pre20_down_day_fraction": float((returns20 < 0).mean()),
        "pre20_median_range_pct": float(prior_ranges.median()),
        "pre60_range_contraction": float(
            ((prior20.tail(10).coord_high - prior20.tail(10).coord_low) / prior20.tail(10).coord_close).median()
            / ((prior60.head(max(len(prior60) - 10, 1)).coord_high - prior60.head(max(len(prior60) - 10, 1)).coord_low) / prior60.head(max(len(prior60) - 10, 1)).coord_close).median()
        )
        if len(prior60) >= 20
        else math.nan,
        "open_gap": float(event.open_gap),
        "signal_step_return": float(event.step_return),
        "signal_close_location": float(event.close_location),
        "signal_body_fraction": body_fraction,
        "signal_range_to_prior20_median": float(
            (signal_range / signal_close) / prior_ranges.median()
        )
        if prior_ranges.median() > 0
        else math.nan,
        "signal_turnover_ratio": turn_ratio,
        "signal_close_vs_prior5_high": float(signal_close / prior5_high - 1.0),
        "status": out_status,
        "entry_date": entry_date,
        "entry_price": entry_price,
        "exit_date": exit_date,
        "exit_price": math.nan if outcome is None else safe_float(outcome.exit_price),
        "exit_reason": None if outcome is None else str(outcome.exit_reason),
        "net_return": net_return,
        "outcome_bucket": outcome_bucket(out_status, net_return),
        "post_entry_max20": max20,
        "post_entry_min20": min20,
        "post_entry_close5": ret5,
        "post_entry_close10": ret10,
        "post_entry_close20": ret20,
    }


def build_ledger(
    candidates: pd.DataFrame,
    outcomes: pd.DataFrame,
    windows: pd.DataFrame,
) -> pd.DataFrame:
    outcome_map = {str(row.event_id): row for _, row in outcomes.iterrows()}
    window_groups = {key: part for key, part in windows.groupby("event_id", sort=False)}
    cluster = candidates.groupby("signal_date").size().to_dict()
    records: list[dict[str, Any]] = []
    for _, event in candidates.iterrows():
        records.append(
            path_features(
                event,
                window_groups[str(event.event_id)],
                outcome_map.get(str(event.event_id)),
                int(cluster[pd.Timestamp(event.signal_date)]),
            )
        )
    ledger = pd.DataFrame(records).sort_values(
        ["signal_date", "sleeve", "symbol", "event_id"], kind="mergesort"
    )
    ledger["chart_number"] = np.arange(1, len(ledger) + 1, dtype=int)
    return ledger.reset_index(drop=True)


def draw_candles(ax: Any, frame: pd.DataFrame, signal_close: float) -> None:
    valid = frame.loc[
        frame.current_valid.fillna(False)
        & frame[["coord_open", "coord_high", "coord_low", "coord_close"]]
        .notna()
        .all(axis=1)
    ].copy()
    dates = mdates.date2num(pd.to_datetime(valid.trade_date).to_numpy())
    scale = 100.0 / signal_close
    for x, row in zip(dates, valid.itertuples(index=False), strict=True):
        opening = float(row.coord_open) * scale
        high = float(row.coord_high) * scale
        low = float(row.coord_low) * scale
        close = float(row.coord_close) * scale
        color = "#d62728" if close >= opening else "#159447"
        ax.vlines(x, low, high, color=color, linewidth=0.55, alpha=0.9)
        bottom = min(opening, close)
        height = max(abs(close - opening), 0.08)
        ax.add_patch(
            Rectangle(
                (x - 0.34, bottom),
                0.68,
                height,
                facecolor=color,
                edgecolor=color,
                linewidth=0.25,
            )
        )
    ax.set_xlim(dates.min() - 3, dates.max() + 3)
    ax.xaxis_date()


def render_chart(
    event: pd.Series,
    frame: pd.DataFrame,
    output: Path,
    pdf: PdfPages | None,
) -> None:
    signal_date = pd.Timestamp(event.signal_date)
    signal_rows = frame.loc[frame.trade_date == signal_date]
    if len(signal_rows) != 1:
        raise ChartBuildError(f"{event.event_id}: missing chart signal row")
    signal_close = float(signal_rows.iloc[0].coord_close)

    figure, (price_ax, volume_ax) = plt.subplots(
        2,
        1,
        figsize=(13.2, 7.4),
        gridspec_kw={"height_ratios": [4.4, 1.0], "hspace": 0.05},
        sharex=True,
    )
    draw_candles(price_ax, frame, signal_close)
    signal_x = mdates.date2num(signal_date.to_pydatetime())
    price_ax.axvline(signal_x, color="#1f77b4", linewidth=1.25, label="signal close")
    price_ax.axhline(100.0, color="#1f77b4", linewidth=0.8, linestyle=":")
    signal_low = float(signal_rows.iloc[0].coord_low) * 100.0 / signal_close
    price_ax.axhline(signal_low, color="#777777", linewidth=0.7, linestyle="--", label="signal low")

    if pd.notna(event.entry_date) and math.isfinite(float(event.entry_price)):
        entry_x = mdates.date2num(pd.Timestamp(event.entry_date).to_pydatetime())
        entry_y = float(event.entry_price) * 100.0 / signal_close
        price_ax.scatter(entry_x, entry_y, marker="^", s=70, color="#7b2cbf", zorder=8, label="entry")
        target_y = float(event.entry_price) * 1.10 * 100.0 / signal_close
        price_ax.axhline(target_y, color="#ff7f0e", linewidth=0.8, linestyle="--", label="+10% target")
    if pd.notna(event.exit_date) and math.isfinite(float(event.exit_price)):
        exit_x = mdates.date2num(pd.Timestamp(event.exit_date).to_pydatetime())
        exit_y = float(event.exit_price) * 100.0 / signal_close
        price_ax.scatter(exit_x, exit_y, marker="v", s=70, color="#111111", zorder=8, label="exit")

    status_text = event.outcome_bucket
    if math.isfinite(float(event.net_return)):
        status_text += f" | net {float(event.net_return):+.2%} | {event.exit_reason}"
    title = (
        f"{int(event.chart_number):04d} | {event.symbol} | {event.sleeve} | "
        f"signal {signal_date.date()} | {status_text}\n"
        f"ret20 {float(event.ret20):+.1%} | ret60 {float(event.ret60):+.1%} | "
        f"gap {float(event.open_gap):+.1%} | signal {float(event.signal_step_return):+.1%} | "
        f"turn/avg {float(event.signal_turnover_ratio):.1f}x | same-date signals {int(event.cluster_signal_count)}"
    )
    price_ax.set_title(title, fontsize=10.5)
    price_ax.set_ylabel("Coordinate price (signal close=100)")
    price_ax.grid(alpha=0.17, linewidth=0.5)
    handles, labels = price_ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles, strict=False))
    price_ax.legend(by_label.values(), by_label.keys(), loc="upper left", ncol=5, fontsize=7.5)

    valid_turn = frame.loc[frame.turnover_fraction.notna()].copy()
    turn_dates = mdates.date2num(pd.to_datetime(valid_turn.trade_date).to_numpy())
    volume_ax.bar(turn_dates, valid_turn.turnover_fraction * 100.0, width=0.75, color="#8b8b8b", alpha=0.55)
    volume_ax.axvline(signal_x, color="#1f77b4", linewidth=1.0)
    volume_ax.set_ylabel("Turnover %")
    volume_ax.grid(alpha=0.12, linewidth=0.4)
    volume_ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    volume_ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    for label in volume_ax.get_xticklabels():
        label.set_rotation(25)
        label.set_horizontalalignment("right")
    figure.subplots_adjust(left=0.065, right=0.985, top=0.88, bottom=0.10)
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata = {"Creator": EXPERIMENT, "Title": str(event.event_id)}
    figure.savefig(output, dpi=115, bbox_inches="tight", facecolor="white", metadata=metadata)
    if pdf is not None:
        pdf.savefig(figure, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def render_worker(payload: tuple[dict[str, Any], pd.DataFrame, str]) -> dict[str, Any]:
    event_dict, frame, output_text = payload
    event = pd.Series(event_dict)
    output = Path(output_text)
    render_chart(event, frame, output, None)
    return {
        "chart_number": int(event.chart_number),
        "event_id": str(event.event_id),
        "symbol": str(event.symbol),
        "signal_date": pd.Timestamp(event.signal_date),
        "outcome_bucket": str(event.outcome_bucket),
        "net_return": safe_float(event.net_return),
        "chart_path": str(output),
    }


def build_contact_sheets(index: pd.DataFrame) -> list[Path]:
    paths: list[Path] = []
    SHEET_DIR.mkdir(parents=True, exist_ok=True)
    rows = index.to_dict("records")
    for start in range(0, len(rows), 4):
        group = rows[start : start + 4]
        thumbs: list[Image.Image] = []
        for row in group:
            image = Image.open(row["chart_path"]).convert("RGB")
            image.thumbnail((1180, 680), Image.Resampling.LANCZOS)
            thumbs.append(image.copy())
            image.close()
        canvas = Image.new("RGB", (2400, 1440), "white")
        draw = ImageDraw.Draw(canvas)
        for offset, image in enumerate(thumbs):
            x = 10 + (offset % 2) * 1195
            y = 35 + (offset // 2) * 695
            canvas.paste(image, (x, y))
        sheet_no = start // 4 + 1
        draw.text((15, 8), f"{EXPERIMENT} | sheet {sheet_no:03d} | charts {start + 1}-{start + len(group)}", fill="black")
        path = SHEET_DIR / f"sheet_{sheet_no:03d}.jpg"
        canvas.save(path, "JPEG", quality=88, optimize=True)
        paths.append(path)
    return paths


def build_outcome_review_sheets(index: pd.DataFrame) -> list[Path]:
    paths: list[Path] = []
    order = [
        "SEVERE_LOSS",
        "LOSS_0_TO_10PCT",
        "PROFIT_0_TO_4PCT",
        "PROFIT_GE_4PCT",
        "NO_COMPLETED_TRADE",
    ]
    for bucket in order:
        subset = index.loc[index.outcome_bucket == bucket].sort_values(
            ["signal_date", "symbol", "event_id"], kind="mergesort"
        )
        rows = subset.to_dict("records")
        target = OUTCOME_SHEET_ROOT / bucket.lower()
        target.mkdir(parents=True, exist_ok=True)
        for start in range(0, len(rows), 4):
            group = rows[start : start + 4]
            canvas = Image.new("RGB", (2400, 1440), "white")
            draw = ImageDraw.Draw(canvas)
            for offset, row in enumerate(group):
                source = Image.open(row["chart_path"]).convert("RGB")
                source.thumbnail((1180, 680), Image.Resampling.LANCZOS)
                x = 10 + (offset % 2) * 1195
                y = 35 + (offset // 2) * 695
                canvas.paste(source, (x, y))
                source.close()
            sheet_no = start // 4 + 1
            draw.text(
                (15, 8),
                f"{bucket} | sheet {sheet_no:03d} | events {start + 1}-{start + len(group)}",
                fill="black",
            )
            path = target / f"sheet_{sheet_no:03d}.jpg"
            canvas.save(path, "JPEG", quality=88, optimize=True)
            paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-render", action="store_true")
    parser.add_argument("--with-pdf", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if not args.with_pdf:
        PDF_BOOK.unlink(missing_ok=True)

    for required in (CONTRACT, SPEC, CANDIDATES, OUTCOMES, DAILY):
        if not required.exists():
            raise ChartBuildError(f"missing required input: {required}")

    candidates, outcomes = load_source()
    windows = load_windows(candidates)
    ledger = build_ledger(candidates, outcomes, windows)
    if args.limit:
        ledger = ledger.head(args.limit).copy()

    EXT_ROOT.mkdir(parents=True, exist_ok=True)
    WINDOW_PANEL.parent.mkdir(parents=True, exist_ok=True)
    windows.to_parquet(WINDOW_PANEL, index=False)
    ledger.to_parquet(REVIEW_LEDGER, index=False)
    ledger.to_csv(REVIEW_CSV, index=False, float_format="%.10g")

    window_groups = {key: part for key, part in windows.groupby("event_id", sort=False)}
    index_rows: list[dict[str, Any]] = []
    if not args.skip_render:
        if args.with_pdf:
            pdf_context = PdfPages(
                PDF_BOOK, metadata={"Title": EXPERIMENT, "Author": "Codex"}
            )
            try:
                for _, event in ledger.iterrows():
                    path = CHART_DIR / f"{int(event.chart_number):04d}_{event.symbol.replace('.', '_')}_{pd.Timestamp(event.signal_date):%Y%m%d}.png"
                    render_chart(
                        event,
                        window_groups[str(event.event_id)],
                        path,
                        pdf_context,
                    )
                    index_rows.append(
                        {
                            "chart_number": int(event.chart_number),
                            "event_id": str(event.event_id),
                            "symbol": str(event.symbol),
                            "signal_date": pd.Timestamp(event.signal_date),
                            "outcome_bucket": str(event.outcome_bucket),
                            "net_return": safe_float(event.net_return),
                            "chart_path": str(path),
                        }
                    )
            finally:
                pdf_context.close()
        else:
            tasks: list[tuple[dict[str, Any], pd.DataFrame, str]] = []
            for _, event in ledger.iterrows():
                path = CHART_DIR / f"{int(event.chart_number):04d}_{event.symbol.replace('.', '_')}_{pd.Timestamp(event.signal_date):%Y%m%d}.png"
                tasks.append(
                    (
                        event.to_dict(),
                        window_groups[str(event.event_id)],
                        str(path),
                    )
                )
            with ProcessPoolExecutor(max_workers=max(1, args.workers)) as executor:
                index_rows = list(executor.map(render_worker, tasks, chunksize=1))
        index = pd.DataFrame(index_rows)
        index.to_csv(CHART_INDEX, index=False, float_format="%.10g")
        sheets = build_contact_sheets(index)
        outcome_sheets = build_outcome_review_sheets(index)
    else:
        if not CHART_INDEX.exists():
            raise ChartBuildError("--skip-render requires an existing chart index")
        index = pd.read_csv(CHART_INDEX, parse_dates=["signal_date"])
        index_rows = index.to_dict("records")
        sheets = sorted(SHEET_DIR.glob("sheet_*.jpg"))
        outcome_sheets = build_outcome_review_sheets(index)

    completed = ledger.loc[ledger.status == "COMPLETED"]
    annual = (
        completed.assign(year=completed.signal_date.dt.year)
        .groupby("year")
        .agg(trades=("event_id", "size"), mean_net=("net_return", "mean"))
        .reset_index()
    )
    manifest = {
        "experiment": EXPERIMENT,
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "source_candidate_sha256": sha256(CANDIDATES),
        "source_outcome_sha256": sha256(OUTCOMES),
        "source_signal_count": int(len(candidates)),
        "selected_profile_completed_trades": int(len(completed)),
        "chart_count": int(len(index_rows)),
        "contact_sheet_count": int(len(sheets)),
        "outcome_review_sheet_count": int(len(outcome_sheets)),
        "chart_window_market_sessions_each_side": PRE,
        "max_source_signal_date": str(candidates.signal_date.max().date()),
        "max_chart_bar_date": str(pd.to_datetime(windows.trade_date).max().date()),
        "repository_2024_data_read": False,
        "annual": annual.to_dict("records"),
        "pooled_mean_net": float(completed.net_return.mean()),
        "pooled_median_net": float(completed.net_return.median()),
        "average_completed_trades_per_year": float(len(completed) / 8.0),
        "severe_loss10": float((completed.net_return <= -0.10).mean()),
        "window_panel_sha256": sha256(WINDOW_PANEL),
        "review_ledger_sha256": sha256(REVIEW_LEDGER),
        "review_csv_sha256": sha256(REVIEW_CSV),
        "chart_index_sha256": sha256(CHART_INDEX) if CHART_INDEX.exists() else None,
        "pdf_sha256": sha256(PDF_BOOK) if PDF_BOOK.exists() else None,
    }
    canonical_json(MANIFEST, manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
