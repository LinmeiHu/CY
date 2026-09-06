#!/usr/bin/env python3
"""Render information-dense structural charts for every V2 mother candidate."""

from __future__ import annotations

import hashlib
import json
import math
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import duckdb
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from matplotlib.font_manager import FontProperties
from matplotlib.patches import Rectangle
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT = "ASHARE-QUIET-INVENTORY-STRUCTURAL-ACCEPTANCE-V2-CHART-REVIEW"
SOURCE = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_quiet_inventory_structural_acceptance_v2/development_2014_2021"
)
CANDIDATES = SOURCE / "mother_candidates.parquet"
ACCEPTANCE = SOURCE / "acceptance_ledger.parquet"
MOTHER_OUTCOMES = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_quiet_inventory_information_gap_breakout_v1/stage_b/outcomes.parquet"
)
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
INDUSTRY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_bull_quiet_inventory_industry_acceptance_v1/stage_a/industry_state.parquet"
)
CHIP_PATHS = [
    Path(
        "/Users/linmei/Documents/CY/data/processed/"
        f"chip_state_features_by_year_2018_2026_v2/year={year}/data.parquet"
    )
    for year in (2018, 2019, 2020, 2021, 2022)
]

EXPECTED_HASHES = {
    "candidates": "cc2326b2568f02490b6f78f4c731c75ca06449949738e2b47486521d29ffba6f",
    "acceptance": "3fa5057d0f56d147871134d8b24ee157a70128a4fee978bcc2f37c6306e4a219",
    "mother_outcomes": "790f94ed4cb5ac96cabe22ad112d1ee1ed8fa54d02b7c6e5c841f815a40c91e4",
    "daily": "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    "regime": "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
    "industry": "909f851461cd6d1162849aac6bdd2078ed4530ce7c59e61c42e8fed36e4df975",
}

OUTPUT = SOURCE / "structural_chart_review_120x120"
CHART_DIR = OUTPUT / "individual_charts"
SHEET_DIR = OUTPUT / "contact_sheets"
OUTCOME_DIR = OUTPUT / "review_sheets_by_outcome"
WINDOW_PANEL = OUTPUT / "chart_window_panel.parquet"
REVIEW_LEDGER = OUTPUT / "review_ledger.parquet"
CHART_INDEX = OUTPUT / "chart_index.csv"
SUMMARY = OUTPUT / "structural_summary.json"
MANIFEST = OUTPUT / "manifest.json"

CJK_FONT = FontProperties(fname="/System/Library/Fonts/STHeiti Light.ttc")
PRE_LOAD = 180
PRE_DISPLAY = 120
POST_DISPLAY = 120


class ChartError(RuntimeError):
    """Fail closed when a chart input or causal feature is invalid."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    pq.write_table(
        pa.Table.from_pandas(frame, preserve_index=False), temporary, compression="zstd"
    )
    os.replace(temporary, path)


def verify_inputs() -> dict[str, str]:
    paths = {
        "candidates": CANDIDATES,
        "acceptance": ACCEPTANCE,
        "mother_outcomes": MOTHER_OUTCOMES,
        "daily": DAILY,
        "regime": REGIME,
        "industry": INDUSTRY,
    }
    missing = [str(path) for path in [*paths.values(), *CHIP_PATHS] if not path.is_file()]
    if missing:
        raise ChartError(f"missing required input: {missing}")
    actual = {name: sha256(path) for name, path in paths.items()}
    drift = {
        name: {"expected": EXPECTED_HASHES[name], "actual": digest}
        for name, digest in actual.items()
        if digest != EXPECTED_HASHES[name]
    }
    if drift:
        raise ChartError(f"frozen input drift: {drift}")
    return actual


def chip_paths_sql() -> str:
    return "[" + ",".join(f"'{path.as_posix()}'" for path in CHIP_PATHS) + "]"


def load_ledger(connection: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    frame = connection.execute(
        f"""
        SELECT c.*,
          a.accepted,a.status,a.confirmation_date,a.confirmation_cal_idx,
          a.confirmation_coord_close,a.confirmation_close_to_platform,
          a.entry_date,a.entry_cal_idx,a.entry_price,a.exit_date,a.exit_cal_idx,
          a.exit_price,a.exit_reason,a.holding_sessions,a.net_return,
          mo.status AS mother_status,mo.net_return AS mother_net_return,
          mo.holding_sessions AS mother_holding_sessions
        FROM read_parquet('{CANDIDATES.as_posix()}') c
        JOIN read_parquet('{ACCEPTANCE.as_posix()}') a USING(event_id)
        LEFT JOIN read_parquet('{MOTHER_OUTCOMES.as_posix()}') mo
          ON c.event_id=mo.event_id AND mo.profile='T10_H20_NO_STOP'
        ORDER BY c.signal_date,c.symbol,c.event_id
        """
    ).fetchdf()
    if len(frame) != 496 or frame.event_id.nunique() != 496:
        raise ChartError(f"expected 496 unique mother candidates, got {len(frame)}")
    for column in ("signal_date", "confirmation_date", "entry_date", "exit_date"):
        frame[column] = pd.to_datetime(frame[column])
    if frame.available_at.gt(frame.decision_at).any():
        raise ChartError("candidate availability exceeds decision_at")
    frame["same_mother_date_signals"] = frame.signal_date.map(
        frame.groupby("signal_date").size()
    ).astype(int)
    frame["same_confirmation_date_signals"] = 0
    accepted = frame.accepted.fillna(False)
    confirmation_counts = frame.loc[accepted].groupby("confirmation_date").size()
    frame.loc[accepted, "same_confirmation_date_signals"] = (
        frame.loc[accepted, "confirmation_date"].map(confirmation_counts).astype(int)
    )
    frame["outcome_bucket"] = [outcome_bucket(row) for _, row in frame.iterrows()]
    frame["chart_number"] = np.arange(1, len(frame) + 1, dtype=int)
    return frame


def load_windows(
    connection: duckdb.DuckDBPyConnection, ledger: pd.DataFrame
) -> pd.DataFrame:
    ids = ledger[
        [
            "event_id",
            "symbol",
            "signal_cal_idx",
            "signal_invalid_step_cum",
            "causal_industry",
        ]
    ].copy()
    connection.register("chart_ids", ids)
    frame = connection.execute(
        f"""
        SELECT c.event_id,c.signal_cal_idx,c.signal_invalid_step_cum,
          d.symbol,d.trade_date,d.cal_idx,d.coord_open,d.coord_high,d.coord_low,
          d.coord_close,d.turnover_fraction,d.ret20,d.ret60,d.coordinate_factor,
          d.invalid_step_cum,d.available_at,d.decision_at,d.hard_valid,d.current_valid,
          r.market_median_ret20,r.market_median_ret60,
          r.market_positive_ret20_share,r.market_positive_ret60_share,
          i.industry_median_ret20,i.industry_median_ret60,
          i.industry_positive_ret20_share
        FROM chart_ids c
        JOIN read_parquet('{DAILY.as_posix()}') d
          ON c.symbol=d.symbol
         AND d.cal_idx BETWEEN c.signal_cal_idx-{PRE_LOAD}
                           AND c.signal_cal_idx+{POST_DISPLAY}
        LEFT JOIN read_parquet('{REGIME.as_posix()}') r
          ON d.trade_date=r.trade_date
        LEFT JOIN read_parquet('{INDUSTRY.as_posix()}') i
          ON d.trade_date=i.trade_date AND c.causal_industry=i.causal_industry
        ORDER BY c.event_id,d.cal_idx
        """
    ).fetchdf()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    if frame.event_id.nunique() != len(ledger):
        raise ChartError("one or more chart windows are missing")
    known = frame.available_at.notna() & frame.decision_at.notna()
    if frame.loc[known, "available_at"].gt(frame.loc[known, "decision_at"]).any():
        raise ChartError("daily row availability exceeds its decision_at")

    window_keys = frame[["event_id", "symbol", "trade_date", "coordinate_factor"]].copy()
    connection.register("window_keys", window_keys)
    chip = connection.execute(
        f"""
        SELECT w.event_id,w.symbol,w.trade_date,
          ch.p10* w.coordinate_factor AS chip_p10_coord,
          ch.p50* w.coordinate_factor AS chip_p50_coord,
          ch.p90* w.coordinate_factor AS chip_p90_coord,
          ch.profit_ratio,ch.trapped_ratio,ch.asr,ch.space20,
          ch.concentration_20,ch.base_retention,ch.mass_sum,ch.strict_sample
        FROM window_keys w
        JOIN read_parquet({chip_paths_sql()}) ch
          ON w.symbol=ch.symbol AND CAST(w.trade_date AS DATE)=ch.trade_date
        WHERE ch.strict_sample
          AND ch.chip_input_valid
          AND ch.daily_hard_valid
          AND ch.minute_hard_valid
          AND ch.state_chain_valid
          AND ch.mass_sum=1.0
          AND ch.available_at<=CAST(w.trade_date AS TIMESTAMP)+INTERVAL 16 HOUR
        """
    ).fetchdf()
    chip["trade_date"] = pd.to_datetime(chip.trade_date)
    frame = frame.merge(chip, on=["event_id", "symbol", "trade_date"], how="left")
    return frame


def safe_float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return math.nan
    return parsed if math.isfinite(parsed) else math.nan


def outcome_bucket(row: pd.Series) -> str:
    if not bool(row.accepted):
        if str(row.status) == "REJECTED_FIRST_LEGAL_CLOSE_BELOW_PLATFORM":
            return "REJECTED_SUPPORT_FAILURE"
        return "REJECTED_OR_INVALID"
    if str(row.status) != "COMPLETED":
        return "ACCEPTED_INCOMPLETE_OR_INVALID"
    value = safe_float(row.net_return)
    if value <= -0.10:
        return "ACCEPTED_SEVERE_LOSS"
    if value <= 0:
        return "ACCEPTED_MILD_LOSS"
    if str(row.exit_reason) == "TARGET_10":
        return "ACCEPTED_TARGET"
    return "ACCEPTED_NON_TARGET_WIN"


def structural_features(event: pd.Series, frame: pd.DataFrame) -> dict[str, Any]:
    signal_idx = int(event.signal_cal_idx)
    lineage = float(event.signal_invalid_step_cum)
    prior = frame.loc[
        frame.cal_idx.between(signal_idx - PRE_DISPLAY, signal_idx - 1)
        & frame.invalid_step_cum.eq(lineage)
        & frame.hard_valid.fillna(False)
    ].sort_values("cal_idx")
    signal = frame.loc[frame.cal_idx.eq(signal_idx)]
    if len(signal) != 1:
        raise ChartError(f"{event.event_id}: expected one signal row, got {len(signal)}")
    signal_close = float(signal.iloc[0].coord_close)
    values: dict[str, Any] = {
        "event_id": event.event_id,
        "prior120_comparable_rows": int(len(prior)),
        "signal_close": signal_close,
    }
    if len(prior) < 120:
        values.update(
            {
                "prior120_high": math.nan,
                "prior120_low": math.nan,
                "resistance_clearance120": math.nan,
                "resistance_touch_days120": math.nan,
                "overhead_turnover_share120": math.nan,
                "turnover_weighted_price120": math.nan,
                "atr20_pct": math.nan,
                "quiet10_to_prior50": math.nan,
                "pre45_trend_return": math.nan,
                "pre45_trend_r2": math.nan,
            }
        )
        return values

    high120 = float(prior.coord_high.max())
    low120 = float(prior.coord_low.min())
    platform = float(event.platform_high)
    turnover = pd.to_numeric(prior.turnover_fraction, errors="coerce")
    turnover_sum = float(turnover.sum())
    weighted_price = (
        math.nan
        if turnover_sum <= 0
        else float((prior.coord_close * turnover).sum() / turnover_sum)
    )
    overhead = (
        math.nan
        if turnover_sum <= 0
        else float(turnover.loc[prior.coord_close.gt(signal_close)].sum() / turnover_sum)
    )
    previous_close = prior.coord_close.shift(1)
    true_range = pd.concat(
        [
            prior.coord_high - prior.coord_low,
            (prior.coord_high - previous_close).abs(),
            (prior.coord_low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    recent10 = float(turnover.iloc[-10:].mean())
    prior50 = float(turnover.iloc[-60:-10].mean())
    last45 = prior.coord_close.iloc[-45:].astype(float)
    log_price = np.log(last45.to_numpy())
    x = np.arange(len(log_price), dtype=float)
    slope, intercept = np.polyfit(x, log_price, 1)
    fitted = intercept + slope * x
    residual = float(np.square(log_price - fitted).sum())
    total = float(np.square(log_price - log_price.mean()).sum())
    r2 = math.nan if total == 0 else 1.0 - residual / total
    values.update(
        {
            "prior120_high": high120,
            "prior120_low": low120,
            "resistance_clearance120": signal_close / high120 - 1.0,
            "resistance_touch_days120": int(
                ((prior.coord_high / platform - 1.0).abs() <= 0.01).sum()
            ),
            "overhead_turnover_share120": overhead,
            "turnover_weighted_price120": weighted_price,
            "atr20_pct": float(true_range.iloc[-20:].mean() / signal_close),
            "quiet10_to_prior50": math.nan if prior50 <= 0 else recent10 / prior50,
            "pre45_trend_return": float(np.exp(slope * 44.0) - 1.0),
            "pre45_trend_r2": r2,
        }
    )
    chip_signal = signal.iloc[0]
    for name in (
        "chip_p10_coord",
        "chip_p50_coord",
        "chip_p90_coord",
        "profit_ratio",
        "asr",
        "space20",
        "concentration_20",
        "base_retention",
    ):
        values[f"signal_{name}"] = safe_float(chip_signal.get(name))
    return values


def add_features(ledger: pd.DataFrame, windows: pd.DataFrame) -> pd.DataFrame:
    groups = {event_id: part for event_id, part in windows.groupby("event_id", sort=False)}
    rows = [
        structural_features(event, groups[event.event_id])
        for _, event in ledger.iterrows()
    ]
    features = pd.DataFrame(rows)
    merged = ledger.merge(features, on="event_id", how="left", validate="one_to_one")
    if len(merged) != len(ledger):
        raise ChartError("structural feature merge changed candidate count")
    merged["stock_minus_industry_ret20"] = (
        merged.ret20 - merged.industry_median_ret20
        if "ret20" in merged and "industry_median_ret20" in merged
        else np.nan
    )
    return merged


def draw_candles(axis: Any, frame: pd.DataFrame, signal_close: float) -> None:
    for row in frame.itertuples(index=False):
        x = mdates.date2num(pd.Timestamp(row.trade_date).to_pydatetime())
        open_y = float(row.coord_open) / signal_close * 100.0
        high_y = float(row.coord_high) / signal_close * 100.0
        low_y = float(row.coord_low) / signal_close * 100.0
        close_y = float(row.coord_close) / signal_close * 100.0
        color = "#d62728" if close_y >= open_y else "#2ca02c"
        axis.vlines(x, low_y, high_y, color=color, linewidth=0.65, alpha=0.9)
        bottom = min(open_y, close_y)
        height = max(abs(close_y - open_y), 0.08)
        axis.add_patch(
            Rectangle(
                (x - 0.34, bottom), 0.68, height,
                facecolor=color, edgecolor=color, linewidth=0.35, alpha=0.72,
            )
        )


def render(event: pd.Series, raw_frame: pd.DataFrame, output: Path) -> None:
    signal_idx = int(event.signal_cal_idx)
    frame = raw_frame.loc[
        raw_frame.cal_idx.between(signal_idx - PRE_DISPLAY, signal_idx + POST_DISPLAY)
    ].sort_values("cal_idx").copy()
    signal_row = frame.loc[frame.cal_idx.eq(signal_idx)]
    if len(signal_row) != 1:
        raise ChartError(f"{event.event_id}: missing signal row")
    signal_close = float(signal_row.iloc[0].coord_close)
    dates = pd.to_datetime(frame.trade_date)
    signal_date = pd.Timestamp(event.signal_date)
    signal_x = mdates.date2num(signal_date.to_pydatetime())

    figure, (price_ax, turn_ax, context_ax) = plt.subplots(
        3,
        1,
        figsize=(15.4, 10.1),
        gridspec_kw={"height_ratios": [5.0, 1.25, 1.55], "hspace": 0.07},
        sharex=True,
    )
    draw_candles(price_ax, frame, signal_close)
    normalized_close = frame.coord_close / signal_close * 100.0
    ma45 = frame.coord_close.rolling(45, min_periods=45).mean() / signal_close * 100.0
    price_ax.plot(dates, ma45, color="#7b2cbf", linewidth=1.15, label="45日均线")

    platform_high_y = float(event.platform_high) / signal_close * 100.0
    platform_low_y = float(event.platform_low) / signal_close * 100.0
    price_ax.axhspan(platform_low_y, platform_high_y, color="#f2c14e", alpha=0.08)
    price_ax.axhline(
        platform_high_y, color="#c17d11", linewidth=1.2, linestyle="--",
        label="40日旧压力→支撑",
    )
    price_ax.axhline(
        platform_low_y, color="#c17d11", linewidth=0.65, linestyle=":",
        label="40日平台下沿",
    )
    for value, color, label in (
        (event.prior120_high, "#555555", "120日前高"),
        (event.prior120_low, "#9a9a9a", "120日前低"),
        (event.turnover_weighted_price120, "#136f63", "120日换手成本锚"),
    ):
        parsed = safe_float(value)
        if math.isfinite(parsed):
            price_ax.axhline(
                parsed / signal_close * 100.0,
                color=color,
                linewidth=0.8,
                linestyle=":" if "120" in label else "-.",
                label=label,
            )

    prior45 = raw_frame.loc[
        raw_frame.cal_idx.between(signal_idx - 45, signal_idx - 1)
        & raw_frame.invalid_step_cum.eq(float(event.signal_invalid_step_cum))
    ].sort_values("cal_idx")
    if len(prior45) == 45:
        x_reg = np.arange(45, dtype=float)
        slope, intercept = np.polyfit(x_reg, np.log(prior45.coord_close.astype(float)), 1)
        projected = np.exp(intercept + slope * np.arange(46, dtype=float)) / signal_close * 100.0
        reg_dates = [*pd.to_datetime(prior45.trade_date), signal_date]
        price_ax.plot(
            reg_dates, projected, color="#005f99", linewidth=1.1,
            linestyle="-.", label="信号前45日对数趋势",
        )

    chip_valid = frame.mass_sum.eq(1.0) & frame.strict_sample.eq(True)
    for column, color, label in (
        ("chip_p10_coord", "#80b918", "筹码P10"),
        ("chip_p50_coord", "#4361ee", "筹码P50"),
        ("chip_p90_coord", "#f72585", "筹码P90"),
    ):
        values = frame[column].where(chip_valid) / signal_close * 100.0
        if values.notna().any():
            price_ax.plot(dates, values, color=color, linewidth=0.75, alpha=0.78, label=label)

    price_ax.axvline(signal_x, color="#1f77b4", linewidth=1.35, label="母信号收盘")
    if pd.notna(event.confirmation_date):
        confirm_x = mdates.date2num(pd.Timestamp(event.confirmation_date).to_pydatetime())
        price_ax.axvline(confirm_x, color="#ff8c00", linewidth=1.2, label="首个合法确认收盘")
        confirm_y = safe_float(event.confirmation_coord_close) / signal_close * 100.0
        if math.isfinite(confirm_y):
            marker = "o" if bool(event.accepted) else "X"
            color = "#ff8c00" if bool(event.accepted) else "#111111"
            price_ax.scatter(confirm_x, confirm_y, marker=marker, s=72, color=color, zorder=9)
    if pd.notna(event.entry_date) and math.isfinite(safe_float(event.entry_price)):
        entry_x = mdates.date2num(pd.Timestamp(event.entry_date).to_pydatetime())
        entry_y = float(event.entry_price) / signal_close * 100.0
        price_ax.scatter(entry_x, entry_y, marker="^", s=82, color="#6a00f4", zorder=9, label="次日后合法开盘入场")
        price_ax.axhline(entry_y * 1.10, color="#e76f51", linewidth=0.75, linestyle="--", label="+10%目标")
    if pd.notna(event.exit_date) and math.isfinite(safe_float(event.exit_price)):
        exit_x = mdates.date2num(pd.Timestamp(event.exit_date).to_pydatetime())
        exit_y = float(event.exit_price) / signal_close * 100.0
        price_ax.scatter(exit_x, exit_y, marker="v", s=78, color="#111111", zorder=9, label="退出")

    accepted_text = "站稳" if bool(event.accepted) else "跌回平台"
    result_text = str(event.outcome_bucket)
    if str(event.status) == "COMPLETED":
        result_text += f" {float(event.net_return):+.2%}/{int(event.holding_sessions)}日"
    mother_text = "NA" if not math.isfinite(safe_float(event.mother_net_return)) else f"{float(event.mother_net_return):+.2%}"
    chip_text = "筹码不可用"
    if math.isfinite(safe_float(event.signal_profit_ratio)):
        chip_text = (
            f"筹码盈利{float(event.signal_profit_ratio):.0%} "
            f"ASR {float(event.signal_asr):.2f} P90距价"
            f"{float(event.signal_chip_p90_coord) / signal_close - 1:+.1%}"
        )
    title = (
        f"{int(event.chart_number):04d} | {event.symbol} | {event.causal_industry} | "
        f"母信号 {signal_date.date()} | 首日{accepted_text} | {result_text}\n"
        f"供给：平台宽{float(event.platform_width):.1%} 20/40换手{float(event.turnover_contraction):.2f}x "
        f"近10/前50 {safe_float(event.quiet10_to_prior50):.2f}x 压力触碰{safe_float(event.resistance_touch_days120):.0f}次 "
        f"上方换手{safe_float(event.overhead_turnover_share120):.1%} | "
        f"结构：前45趋势{safe_float(event.pre45_trend_return):+.1%} R² {safe_float(event.pre45_trend_r2):.2f} "
        f"距120前高{safe_float(event.resistance_clearance120):+.1%} ATR20 {safe_float(event.atr20_pct):.1%}\n"
        f"环境：市场60 {float(event.market_median_ret60):+.1%} 市场20 {float(event.market_median_ret20):+.1%} "
        f"行业60 {safe_float(event.industry_median_ret60):+.1%} 个股-行业20 {safe_float(event.stock_minus_industry_ret20):+.1%} | "
        f"同确认日{int(event.same_confirmation_date_signals)}只 | 原母信号收益{mother_text} | {chip_text}"
    )
    price_ax.set_title(title, fontsize=9.2, fontproperties=CJK_FONT)
    price_ax.set_ylabel("坐标价（母信号收盘=100）", fontproperties=CJK_FONT)
    price_ax.grid(alpha=0.15, linewidth=0.45)
    handles, labels = price_ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles, strict=False))
    price_ax.legend(
        by_label.values(), by_label.keys(), loc="upper left", ncol=5,
        fontsize=6.8, prop=CJK_FONT,
    )

    colors = np.where(frame.coord_close.ge(frame.coord_open), "#d62728", "#2ca02c")
    turn_ax.bar(dates, frame.turnover_fraction * 100.0, width=0.75, color=colors, alpha=0.45)
    turn_ax.plot(
        dates,
        frame.turnover_fraction.rolling(20, min_periods=20).mean() * 100.0,
        color="#1f77b4",
        linewidth=0.9,
        label="20日平均换手",
    )
    turn_ax.axvline(signal_x, color="#1f77b4", linewidth=1.0)
    turn_ax.set_ylabel("换手%", fontproperties=CJK_FONT)
    turn_ax.grid(alpha=0.12, linewidth=0.4)
    turn_ax.legend(loc="upper left", fontsize=6.8, prop=CJK_FONT)

    for column, color, label, width in (
        ("ret20", "#111111", "个股20日", 1.05),
        ("industry_median_ret20", "#ff8c00", "行业20日中位", 0.95),
        ("market_median_ret20", "#2a9d8f", "市场20日中位", 0.95),
        ("industry_median_ret60", "#f4a261", "行业60日中位", 0.7),
        ("market_median_ret60", "#264653", "市场60日中位", 0.7),
    ):
        context_ax.plot(dates, frame[column] * 100.0, color=color, linewidth=width, label=label)
    context_ax.axhline(0.0, color="#777777", linewidth=0.65)
    context_ax.axvline(signal_x, color="#1f77b4", linewidth=1.0)
    context_ax.set_ylabel("滚动收益%", fontproperties=CJK_FONT)
    context_ax.grid(alpha=0.14, linewidth=0.4)
    context_ax.legend(loc="upper left", ncol=5, fontsize=6.8, prop=CJK_FONT)
    context_ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    context_ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    for label in context_ax.get_xticklabels():
        label.set_rotation(25)
        label.set_horizontalalignment("right")
    figure.subplots_adjust(left=0.065, right=0.988, top=0.86, bottom=0.085)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=118, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def worker(payload: tuple[dict[str, Any], pd.DataFrame, str]) -> dict[str, Any]:
    event_dict, frame, output_text = payload
    event = pd.Series(event_dict)
    output = Path(output_text)
    render(event, frame, output)
    return {
        "chart_number": int(event.chart_number),
        "event_id": str(event.event_id),
        "symbol": str(event.symbol),
        "signal_date": pd.Timestamp(event.signal_date),
        "confirmation_date": event.confirmation_date,
        "outcome_bucket": str(event.outcome_bucket),
        "net_return": safe_float(event.net_return),
        "mother_net_return": safe_float(event.mother_net_return),
        "same_confirmation_date_signals": int(event.same_confirmation_date_signals),
        "chart_path": str(output),
    }


def make_sheets(index: pd.DataFrame, root: Path, prefix: str) -> list[Path]:
    root.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    ordered = index.sort_values(["signal_date", "chart_number"], kind="mergesort")
    for sheet_number, start in enumerate(range(0, len(ordered), 4), start=1):
        page = ordered.iloc[start : start + 4]
        images = [Image.open(path).convert("RGB") for path in page.chart_path]
        thumb_width = 1180
        resized = []
        for image in images:
            height = round(image.height * thumb_width / image.width)
            resized.append(image.resize((thumb_width, height), Image.Resampling.LANCZOS))
        cell_height = max(image.height for image in resized) + 36
        canvas = Image.new("RGB", (thumb_width * 2, cell_height * 2), "white")
        draw = ImageDraw.Draw(canvas)
        for offset, (record, image) in enumerate(zip(page.itertuples(), resized, strict=True)):
            x = (offset % 2) * thumb_width
            y = (offset // 2) * cell_height
            canvas.paste(image, (x, y + 26))
            draw.text((x + 8, y + 5), f"#{record.chart_number} {record.outcome_bucket}", fill="black")
        output = root / f"{prefix}_{sheet_number:03d}.jpg"
        canvas.save(output, quality=88, optimize=True)
        paths.append(output)
        for image in images:
            image.close()
    return paths


def summarize(ledger: pd.DataFrame) -> dict[str, Any]:
    accepted = ledger.loc[ledger.accepted.fillna(False)]
    rejected = ledger.loc[ledger.status.eq("REJECTED_FIRST_LEGAL_CLOSE_BELOW_PLATFORM")]
    complete = accepted.loc[accepted.status.eq("COMPLETED")]
    rows: dict[str, Any] = {
        "mother_candidates": int(len(ledger)),
        "accepted": int(len(accepted)),
        "support_failures": int(len(rejected)),
        "accepted_v2_mean_net_return": float(complete.net_return.mean()),
        "accepted_v2_mean_holding_sessions": float(complete.holding_sessions.mean()),
        "accepted_mother_counterfactual_mean": float(accepted.mother_net_return.mean()),
        "support_failure_mother_counterfactual_mean": float(rejected.mother_net_return.mean()),
        "feature_group_means": {},
    }
    feature_names = (
        "pre45_trend_return",
        "pre45_trend_r2",
        "resistance_clearance120",
        "resistance_touch_days120",
        "overhead_turnover_share120",
        "quiet10_to_prior50",
        "atr20_pct",
    )
    for feature in feature_names:
        rows["feature_group_means"][feature] = (
            ledger.groupby("outcome_bucket")[feature].mean().dropna().to_dict()
        )
    return rows


def run(workers: int = 8) -> dict[str, Any]:
    input_hashes = verify_inputs()
    connection = duckdb.connect()
    connection.execute("SET threads=8")
    connection.execute("SET memory_limit='16GB'")
    ledger = load_ledger(connection)
    windows = load_windows(connection, ledger)
    connection.close()
    ledger = add_features(ledger, windows)
    # Pull signal-date context from the event window after features are joined.
    signal_context = windows.loc[
        windows.cal_idx.eq(windows.signal_cal_idx),
        [
            "event_id",
            "ret20",
            "industry_median_ret20",
            "industry_median_ret60",
            "industry_positive_ret20_share",
        ],
    ].drop_duplicates("event_id")
    ledger = ledger.merge(signal_context, on="event_id", how="left", validate="one_to_one")
    ledger["stock_minus_industry_ret20"] = ledger.ret20 - ledger.industry_median_ret20

    OUTPUT.mkdir(parents=True, exist_ok=True)
    atomic_parquet(windows, WINDOW_PANEL)
    atomic_parquet(ledger, REVIEW_LEDGER)
    groups = {event_id: part for event_id, part in windows.groupby("event_id", sort=False)}
    tasks = []
    for _, event in ledger.iterrows():
        filename = (
            f"{int(event.chart_number):04d}_{str(event.symbol).replace('.', '_')}_"
            f"{pd.Timestamp(event.signal_date):%Y%m%d}.png"
        )
        tasks.append((event.to_dict(), groups[event.event_id], str(CHART_DIR / filename)))
    with ProcessPoolExecutor(max_workers=max(1, workers)) as pool:
        rows = list(pool.map(worker, tasks, chunksize=1))
    index = pd.DataFrame(rows).sort_values("chart_number")
    index.to_csv(CHART_INDEX, index=False)
    contact_sheets = make_sheets(index, SHEET_DIR, "all")
    outcome_sheets: list[Path] = []
    for bucket, part in index.groupby("outcome_bucket", sort=True):
        outcome_sheets.extend(
            make_sheets(part, OUTCOME_DIR / bucket, bucket.lower())
        )
    summary = summarize(ledger)
    atomic_json(SUMMARY, summary)
    manifest = {
        "experiment": EXPERIMENT,
        "charts": int(len(index)),
        "contact_sheets": len(contact_sheets),
        "outcome_sheets": len(outcome_sheets),
        "window": {"pre_sessions": PRE_DISPLAY, "post_sessions": POST_DISPLAY},
        "causal_annotations": [
            "frozen prior-40 platform high/low",
            "prior-120 high/low and turnover-weighted cost anchor",
            "pre-signal 45-session log-price trend",
            "causal 45-session moving average",
            "exact-mass strict chip P10/P50/P90 bands where available",
            "turnover contraction and resistance-touch count",
            "stock, industry and market rolling return context",
            "separate mother, confirmation, entry and exit markers",
        ],
        "input_hashes_sha256": input_hashes,
        "output_hashes_sha256": {
            "window_panel": sha256(WINDOW_PANEL),
            "review_ledger": sha256(REVIEW_LEDGER),
            "chart_index": sha256(CHART_INDEX),
            "structural_summary": sha256(SUMMARY),
        },
    }
    atomic_json(MANIFEST, manifest)
    return manifest


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
