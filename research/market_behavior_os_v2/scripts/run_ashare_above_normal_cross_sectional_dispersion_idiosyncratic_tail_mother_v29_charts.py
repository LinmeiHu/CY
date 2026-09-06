#!/usr/bin/env python3
"""Render every frozen V29 event as a compact six-month candlestick chart."""

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
from PIL import Image, ImageDraw, ImageFont


EXPERIMENT = (
    "ASHARE-ABOVE-NORMAL-CROSS-SECTIONAL-DISPERSION-"
    "IDIOSYNCRATIC-TAIL-MOTHER-V29"
)
REPO = Path(__file__).resolve().parents[3]
PARENT_SPEC = REPO / (
    f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
)
STAGE_B_SPEC = REPO / (
    f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_stage_b_freeze.json"
)
STAGE_A_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_above_normal_cross_sectional_dispersion_"
    "idiosyncratic_tail_mother_v29_stage_a.py"
)
STAGE_B_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_above_normal_cross_sectional_dispersion_"
    "idiosyncratic_tail_mother_v29_stage_b.py"
)
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
DAILY = DATA_ROOT / (
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
REGIME = DATA_ROOT / (
    "ashare_causal_market_regime_routed_simple_strategy_v1/"
    "stage_a/causal_market_regime_2014_2023.parquet"
)
OUTPUT_ROOT = DATA_ROOT / (
    "ashare_above_normal_cross_sectional_dispersion_"
    "idiosyncratic_tail_mother_v29"
)
STAGE_A_RESULT = OUTPUT_ROOT / "stage_a/stage_a_freeze.json"
CANDIDATES = OUTPUT_ROOT / "stage_a/candidates_frozen.parquet"
STAGE_B_RESULT = OUTPUT_ROOT / "stage_b/result.json"
PATHS = OUTPUT_ROOT / "stage_b/future_paths.parquet"
OUTCOMES = OUTPUT_ROOT / "stage_b/outcomes.parquet"
CHART_ROOT = OUTPUT_ROOT / "stage_c_charts"
WINDOW_PANEL = CHART_ROOT / "chart_window_panel.parquet"
REVIEW_LEDGER = CHART_ROOT / "review_ledger.parquet"
REVIEW_CSV = CHART_ROOT / "review_ledger.csv"
CHART_DIR = CHART_ROOT / "individual_charts"
CHART_INDEX = CHART_ROOT / "chart_index.csv"
SHEET_DIR = CHART_ROOT / "contact_sheets"
OUTCOME_SHEET_ROOT = CHART_ROOT / "review_sheets_by_outcome"
MANIFEST = CHART_ROOT / "manifest.json"
EXPECTED_HASHES = {
    PARENT_SPEC: "c0be8faf50ff4b01efefa914f5631b648df2c79ca91d9a2da437a77326238dc4",
    STAGE_B_SPEC: "daec10613c7fd1289527cd33082217134106ff5a3c7e4c981e2e47f716c77dc6",
    STAGE_A_RUNNER: "c2a6c7c061f1fbca5122a1cab71396e02b85721b9092128a081842b50ded5155",
    STAGE_B_RUNNER: "8919c32af80c1316464c902e3b3d3f69405397cc14d5f98e8031c3e1e38d69f9",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    REGIME: "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
    STAGE_A_RESULT: "4d4240be667dd9e33a32f7f6d9b14252d177e4650ecc8b3b73e203f0f2455bbe",
    CANDIDATES: "5c5d70e96ae65552bc5f53a008c50fcba34392b252a666f43386b9d1b6bde6ef",
    STAGE_B_RESULT: "3cc46939893d923897cb18f79f3896da236915aca639db90b4da0e6d0e1c1747",
    PATHS: "68c735dc63ea4f4a6f0a22c7998f7059070f18ea1a39cf0ebf4aae6f8c9917c0",
    OUTCOMES: "0eddb2310189c7008995e262ea5c06bb3066bb813795b68ee2aba39077abb55f",
}
EXPECTED_EVENTS = 9368
CHART_SIZE = (720, 380)
GRID_COLUMNS = 5
GRID_ROWS = 5


class ResearchError(RuntimeError):
    """Fail closed on frozen input, chronology, or chart identity drift."""


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
                f"input identity drift: {path}: {actual[str(path)]} != {expected}"
            )
    return actual


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.register("frame", frame)
    con.execute(
        f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    con.close()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )


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


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    candidates = pd.read_parquet(CANDIDATES)
    outcomes = pd.read_parquet(OUTCOMES)
    for column in ("signal_date", "decision_at", "available_at"):
        candidates[column] = pd.to_datetime(candidates[column])
    for column in ("signal_date", "entry_date", "exit_date"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    if len(candidates) != EXPECTED_EVENTS or candidates.event_id.duplicated().any():
        raise ResearchError("candidate identity drift")
    if len(outcomes) != EXPECTED_EVENTS or outcomes.event_id.duplicated().any():
        raise ResearchError("outcome identity drift")

    regime = pd.read_parquet(
        REGIME,
        columns=[
            "trade_date",
            "market_regime",
            "market_median_ret20",
            "market_positive_ret20_share",
            "market_median_ret60",
            "market_positive_ret60_share",
            "latest_source_timestamp",
        ],
    )
    regime["trade_date"] = pd.to_datetime(regime.trade_date)
    regime["latest_source_timestamp"] = pd.to_datetime(
        regime.latest_source_timestamp
    )
    candidates = candidates.merge(
        regime,
        left_on="signal_date",
        right_on="trade_date",
        how="left",
        validate="many_to_one",
    ).drop(columns="trade_date")

    con = duckdb.connect()
    con.register("keys", candidates[["event_id", "symbol", "signal_cal_idx"]])
    descriptors = con.execute(
        f"""
        SELECT k.event_id,d.ret20,d.ret60,
          CASE WHEN d.coord_high>d.coord_low
            THEN (d.coord_close-d.coord_low)/(d.coord_high-d.coord_low)
            ELSE NULL END AS close_location,
          d.coord_open/nullif(d.prior_coord_close,0)-1 AS open_gap
        FROM keys k JOIN read_parquet('{DAILY.as_posix()}') d
          ON d.symbol=k.symbol AND d.cal_idx=k.signal_cal_idx
        """
    ).fetch_df()
    con.register(
        "chart_keys",
        candidates[["event_id", "symbol", "signal_cal_idx", "signal_date"]],
    )
    windows = con.execute(
        f"""
        SELECT k.event_id,k.signal_date,d.symbol,d.trade_date,d.cal_idx,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,
          d.turnover_fraction,d.current_day_data_tradable,d.current_valid,
          d.hard_valid,d.available_at,d.decision_at
        FROM read_parquet('{DAILY.as_posix()}') d
        JOIN chart_keys k ON d.symbol=k.symbol
          AND d.cal_idx BETWEEN k.signal_cal_idx-126 AND k.signal_cal_idx+126
        WHERE d.trade_date<=DATE '2021-06-30'
        ORDER BY k.event_id,d.cal_idx
        """
    ).fetch_df()
    con.close()
    candidates = candidates.merge(descriptors, on="event_id", validate="one_to_one")
    for column in ("signal_date", "trade_date", "available_at", "decision_at"):
        if column in windows:
            windows[column] = pd.to_datetime(windows[column])
    if windows.event_id.nunique() != EXPECTED_EVENTS:
        raise ResearchError("chart windows miss an event")
    if windows.trade_date.max() > pd.Timestamp("2021-06-30"):
        raise ResearchError("chart window crossed maximum context date")
    if candidates.latest_source_timestamp.gt(candidates.decision_at).any():
        raise ResearchError("causal market state arrived after signal decision")
    required = [
        "market_regime",
        "market_median_ret20",
        "market_median_ret60",
        "ret20",
        "ret60",
    ]
    if candidates[required].isna().any().any():
        raise ResearchError("missing chart annotation")
    return candidates, outcomes, windows


def build_ledger(
    candidates: pd.DataFrame, outcomes: pd.DataFrame, windows: pd.DataFrame
) -> pd.DataFrame:
    outcome_lookup = {str(row.event_id): row for row in outcomes.itertuples(index=False)}
    window_lookup = {key: part for key, part in windows.groupby("event_id", sort=False)}
    rows: list[dict[str, Any]] = []
    ordered = candidates.sort_values(
        ["signal_date", "direction_lane", "causal_industry", "symbol"],
        kind="mergesort",
    )
    for chart_number, event in enumerate(ordered.itertuples(index=False), start=1):
        frame = window_lookup[str(event.event_id)]
        valid = frame.loc[
            frame.current_valid.fillna(False)
            & frame[["coord_open", "coord_high", "coord_low", "coord_close"]]
            .notna()
            .all(axis=1)
        ].sort_values("cal_idx", kind="mergesort")
        signal = valid.loc[valid.cal_idx.eq(int(event.signal_cal_idx))]
        if len(signal) != 1:
            raise ResearchError(f"{event.event_id}: signal chart bar not unique")
        signal = signal.iloc[0]
        before = valid.loc[valid.cal_idx.lt(int(event.signal_cal_idx))].tail(126)
        prior20 = before.tail(20)
        if len(prior20) < 20:
            raise ResearchError(f"{event.event_id}: incomplete chart history")
        prior126_high = float(before.coord_high.max())
        prior126_low = float(before.coord_low.min())
        signal_close = float(signal.coord_close)
        prior20_turn = float(prior20.turnover_fraction.median())
        outcome = outcome_lookup[str(event.event_id)]
        net_return = float(outcome.net_return) if pd.notna(outcome.net_return) else math.nan
        rows.append(
            {
                "event_id": str(event.event_id),
                "chart_number": chart_number,
                "symbol": str(event.symbol),
                "sleeve": str(event.sleeve),
                "causal_industry": str(event.causal_industry),
                "direction_lane": str(event.direction_lane),
                "signal_date": pd.Timestamp(event.signal_date),
                "signal_year": int(pd.Timestamp(event.signal_date).year),
                "signal_cal_idx": int(event.signal_cal_idx),
                "market_regime": str(event.market_regime),
                "market_median_ret20": float(event.market_median_ret20),
                "market_median_ret60": float(event.market_median_ret60),
                "dispersion_iqr": float(event.stock_specific_dispersion_iqr),
                "dispersion_prior252_median": float(event.prior252_dispersion_p50),
                "dispersion_ratio": float(event.stock_specific_dispersion_iqr)
                / float(event.prior252_dispersion_p50),
                "stock_step_return": float(event.step_return),
                "stock_specific_step_return": float(event.stock_specific_step_return),
                "industry_step_return": float(event.industry_step_return),
                "ret20": float(event.ret20),
                "ret60": float(event.ret60),
                "open_gap": float(event.open_gap),
                "close_location": float(event.close_location),
                "signal_turnover_ratio": (
                    float(event.turnover_fraction) / prior20_turn
                    if prior20_turn > 0
                    else math.nan
                ),
                "pre126_return": signal_close / float(before.coord_close.iloc[0]) - 1,
                "pre126_drawdown_from_high": signal_close / prior126_high - 1,
                "pre126_position": (
                    (signal_close - prior126_low) / (prior126_high - prior126_low)
                    if prior126_high > prior126_low
                    else math.nan
                ),
                "status": str(outcome.status),
                "entry_date": pd.Timestamp(outcome.entry_date)
                if pd.notna(outcome.entry_date)
                else pd.NaT,
                "entry_price": float(outcome.entry_price)
                if pd.notna(outcome.entry_price)
                else math.nan,
                "exit_date": pd.Timestamp(outcome.exit_date)
                if pd.notna(outcome.exit_date)
                else pd.NaT,
                "exit_price": float(outcome.exit_price)
                if pd.notna(outcome.exit_price)
                else math.nan,
                "exit_reason": str(outcome.exit_reason),
                "holding_sessions": float(outcome.holding_sessions)
                if pd.notna(outcome.holding_sessions)
                else math.nan,
                "net_return": net_return,
                "outcome_bucket": outcome_bucket(str(outcome.status), net_return),
            }
        )
    return pd.DataFrame(rows)


def _font(size: int) -> ImageFont.ImageFont:
    candidates = (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_triangle(
    draw: ImageDraw.ImageDraw, x: int, y: int, up: bool, color: str
) -> None:
    points = (
        [(x, y - 7), (x - 6, y + 5), (x + 6, y + 5)]
        if up
        else [(x, y + 7), (x - 6, y - 5), (x + 6, y - 5)]
    )
    draw.polygon(points, fill=color)


def render_chart(event: pd.Series, frame: pd.DataFrame, output: Path) -> None:
    width, height = CHART_SIZE
    image = Image.new("RGB", CHART_SIZE, "white")
    draw = ImageDraw.Draw(image)
    font = _font(12)
    small = _font(10)
    signal_date = pd.Timestamp(event.signal_date)
    valid = frame.loc[
        frame.current_valid.fillna(False)
        & frame[["coord_open", "coord_high", "coord_low", "coord_close"]]
        .notna()
        .all(axis=1)
    ].sort_values("cal_idx", kind="mergesort")
    signal_rows = valid.loc[valid.trade_date.eq(signal_date)]
    if len(signal_rows) != 1:
        raise ResearchError(f"{event.event_id}: chart signal row not unique")
    signal_close = float(signal_rows.iloc[0].coord_close)
    prices = valid[["coord_low", "coord_high"]].to_numpy(dtype=float)
    low = float(np.nanmin(prices[:, 0]))
    high = float(np.nanmax(prices[:, 1]))
    if not high > low:
        high = low * 1.01
    pad = (high - low) * 0.04
    low -= pad
    high += pad
    left, right = 34, width - 8
    price_top, price_bottom = 42, 292
    volume_top, volume_bottom = 306, height - 8

    def x_at(index: int) -> int:
        return int(left + index * (right - left) / max(1, len(valid) - 1))

    def y_at(value: float) -> int:
        return int(
            price_bottom
            - (value - low) * (price_bottom - price_top) / (high - low)
        )

    draw.rectangle((left, price_top, right, price_bottom), outline="#d1d5db")
    draw.rectangle((left, volume_top, right, volume_bottom), outline="#e5e7eb")
    max_turn = float(valid.turnover_fraction.fillna(0).max())
    max_turn = max(max_turn, 1e-9)
    signal_index = None
    date_to_index: dict[pd.Timestamp, int] = {}
    candle_width = max(1, int((right - left) / max(1, len(valid)) * 0.7))
    for index, row in enumerate(valid.itertuples(index=False)):
        x = x_at(index)
        date = pd.Timestamp(row.trade_date)
        date_to_index[date] = index
        if date == signal_date:
            signal_index = index
        open_y = y_at(float(row.coord_open))
        close_y = y_at(float(row.coord_close))
        high_y = y_at(float(row.coord_high))
        low_y = y_at(float(row.coord_low))
        color = "#dc2626" if float(row.coord_close) >= float(row.coord_open) else "#16803c"
        draw.line((x, high_y, x, low_y), fill=color, width=1)
        body_top, body_bottom = sorted((open_y, close_y))
        if body_bottom == body_top:
            draw.line((x - candle_width, body_top, x + candle_width, body_top), fill=color)
        else:
            draw.rectangle(
                (x - candle_width, body_top, x + candle_width, body_bottom),
                fill=color,
            )
        if pd.notna(row.turnover_fraction):
            bar_height = int(
                float(row.turnover_fraction)
                / max_turn
                * (volume_bottom - volume_top - 2)
            )
            draw.rectangle(
                (x - candle_width, volume_bottom - bar_height, x + candle_width, volume_bottom),
                fill="#9ca3af",
            )
    if signal_index is None:
        raise ResearchError(f"{event.event_id}: no signal in valid chart frame")
    signal_x = x_at(signal_index)
    draw.line((signal_x, price_top, signal_x, volume_bottom), fill="#b45309", width=2)
    signal_y = y_at(signal_close)
    for x in range(left, right, 8):
        draw.line((x, signal_y, min(x + 4, right), signal_y), fill="#b45309")

    if pd.notna(event.entry_date) and math.isfinite(float(event.entry_price)):
        entry_index = date_to_index.get(pd.Timestamp(event.entry_date))
        if entry_index is not None:
            _draw_triangle(
                draw,
                x_at(entry_index),
                y_at(float(event.entry_price)),
                True,
                "#7c3aed",
            )
            target_y = y_at(float(event.entry_price) * 1.10)
            for x in range(left, right, 10):
                draw.line((x, target_y, min(x + 5, right), target_y), fill="#f97316")
    if pd.notna(event.exit_date) and math.isfinite(float(event.exit_price)):
        exit_index = date_to_index.get(pd.Timestamp(event.exit_date))
        if exit_index is not None:
            _draw_triangle(
                draw,
                x_at(exit_index),
                y_at(float(event.exit_price)),
                False,
                "#111827",
            )

    lane = "UP" if event.direction_lane == "IDIOSYNCRATIC_UP_SHOCK" else "DOWN"
    net = "NA" if not math.isfinite(float(event.net_return)) else f"{float(event.net_return):+.1%}"
    title = (
        f"{int(event.chart_number):05d} {lane} {event.symbol} {signal_date:%Y-%m-%d} "
        f"{event.market_regime} {event.outcome_bucket} net={net}"
    )
    subtitle = (
        f"step={float(event.stock_step_return):+.1%} idio={float(event.stock_specific_step_return):+.1%} "
        f"disp={float(event.dispersion_ratio):.2f}x r20/60={float(event.ret20):+.1%}/{float(event.ret60):+.1%} "
        f"turn={float(event.signal_turnover_ratio):.1f}x pos6m={float(event.pre126_position):.0%}"
    )
    draw.text((6, 4), title, fill="#111827", font=font)
    draw.text((6, 21), subtitle, fill="#374151", font=small)
    draw.text((2, price_top), f"{high / signal_close:.1f}x", fill="#6b7280", font=small)
    draw.text((2, price_bottom - 10), f"{low / signal_close:.1f}x", fill="#6b7280", font=small)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=False)


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
        "direction_lane": str(event.direction_lane),
        "market_regime": str(event.market_regime),
        "outcome_bucket": str(event.outcome_bucket),
        "net_return": float(event.net_return)
        if math.isfinite(float(event.net_return))
        else math.nan,
        "chart_path": str(output),
    }


def build_grids(frame: pd.DataFrame, output_dir: Path, label: str) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    page_size = GRID_COLUMNS * GRID_ROWS
    ordered = frame.reset_index(drop=True)
    for page, start in enumerate(range(0, len(ordered), page_size), start=1):
        part = ordered.iloc[start : start + page_size]
        sheet = Image.new(
            "RGB",
            (CHART_SIZE[0] * GRID_COLUMNS, CHART_SIZE[1] * GRID_ROWS + 28),
            "#e5e7eb",
        )
        draw = ImageDraw.Draw(sheet)
        draw.text(
            (8, 7),
            f"{label} page {page:04d} charts {start + 1}-{start + len(part)}",
            fill="#111827",
            font=_font(13),
        )
        for offset, row in enumerate(part.itertuples(index=False)):
            with Image.open(str(row.chart_path)) as chart:
                x = (offset % GRID_COLUMNS) * CHART_SIZE[0]
                y = (offset // GRID_COLUMNS) * CHART_SIZE[1] + 28
                sheet.paste(chart.convert("RGB"), (x, y))
        target = output_dir / f"sheet_{page:04d}.jpg"
        sheet.save(target, format="JPEG", quality=87, optimize=False)
        paths.append(target)
    return paths


def run(workers: int, skip_render: bool) -> dict[str, Any]:
    source_hashes = verify_inputs()
    candidates, outcomes, windows = load_inputs()
    ledger = build_ledger(candidates, outcomes, windows)
    write_parquet(windows, WINDOW_PANEL)
    write_parquet(ledger, REVIEW_LEDGER)
    ledger.to_csv(REVIEW_CSV, index=False, float_format="%.10g")
    chronological_sheets: list[Path] = []
    outcome_sheets: list[Path] = []
    if not skip_render:
        groups = {key: part for key, part in windows.groupby("event_id", sort=False)}
        tasks = []
        for event in ledger.itertuples(index=False):
            target = CHART_DIR / (
                f"{int(event.chart_number):05d}_{event.direction_lane.lower()}_"
                f"{event.symbol.replace('.', '_')}_"
                f"{pd.Timestamp(event.signal_date):%Y%m%d}.png"
            )
            tasks.append((event._asdict(), groups[str(event.event_id)], str(target)))
        with ProcessPoolExecutor(max_workers=max(1, workers)) as executor:
            chart_index = pd.DataFrame(
                list(executor.map(render_worker, tasks, chunksize=8))
            )
        chart_index = chart_index.sort_values("chart_number", kind="mergesort")
        chart_index.to_csv(CHART_INDEX, index=False, float_format="%.10g")
        chronological_sheets = build_grids(
            chart_index, SHEET_DIR, f"{EXPERIMENT} chronological"
        )
        for lane in ("IDIOSYNCRATIC_DOWN_SHOCK", "IDIOSYNCRATIC_UP_SHOCK"):
            for bucket in (
                "SEVERE_LOSS",
                "LOSS_0_TO_10PCT",
                "PROFIT_0_TO_4PCT",
                "PROFIT_GE_4PCT",
                "NO_COMPLETED_TRADE",
            ):
                subset = chart_index.loc[
                    chart_index.direction_lane.eq(lane)
                    & chart_index.outcome_bucket.eq(bucket)
                ].sort_values(
                    ["signal_date", "symbol", "event_id"], kind="mergesort"
                )
                if subset.empty:
                    continue
                outcome_sheets.extend(
                    build_grids(
                        subset,
                        OUTCOME_SHEET_ROOT / lane.lower() / bucket.lower(),
                        f"{lane} {bucket}",
                    )
                )
    payload = {
        "experiment": EXPERIMENT,
        "stage": "FULL_FROZEN_CANDIDATE_CHART_CORPUS",
        "source_hashes": source_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "window_panel_sha256": sha256(WINDOW_PANEL),
        "review_ledger_sha256": sha256(REVIEW_LEDGER),
        "signals": int(len(candidates)),
        "charts": 0 if skip_render else int(len(candidates)),
        "chronological_contact_sheets": len(chronological_sheets),
        "outcome_contact_sheets": len(outcome_sheets),
        "charts_per_sheet": GRID_COLUMNS * GRID_ROWS,
        "outcome_buckets": {
            str(key): int(value)
            for key, value in ledger.outcome_bucket.value_counts().sort_index().items()
        },
        "direction_lanes": {
            str(key): int(value)
            for key, value in ledger.direction_lane.value_counts().sort_index().items()
        },
        "maximum_signal_date": str(candidates.signal_date.max().date()),
        "maximum_chart_bar_date": str(windows.trade_date.max().date()),
        "all_chronological_sheets_reviewed": False,
        "all_outcome_sheets_reviewed": False,
        "2022_2024_signal_or_outcome_read": "NO",
        "future_market_or_industry_function": False,
        "next_step": "REVIEW_ALL_SHEETS_BEFORE_ANY_RULE_FREEZE",
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
