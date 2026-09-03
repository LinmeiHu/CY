#!/usr/bin/env python3
"""Generate PIT-safe candlestick atlases and causal chart descriptors for Strategy A."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-CHAMPION-CANDLESTICK-RULE-DISCOVERY-V1_spec.json"
EXPECTED_SPEC_SHA256 = "0ea60b648d19b9e81efa894752561c7d2cafe63f2e689ad3493948af7d3557d7"
STAGE_YEARS = {
    "round1": (2018, 2019),
    "round2": (2020,),
    "round3": (2021, 2022, 2023),
}
STRATA = (
    ("severe_loss", -math.inf, -0.10),
    ("normal_loss", -0.10, 0.0),
    ("normal_win", 0.0, 0.10),
    ("extreme_win", 0.10, math.inf),
)
OUTPUT_ROOT = Path("/Volumes/quant/CY_quant_research/champion_candlestick_rule_discovery_v1")


class CandlestickDiscoveryError(RuntimeError):
    """Fail-closed chart-discovery error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise CandlestickDiscoveryError("frozen candlestick specification identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_CANDLESTICK_REVIEW_OR_NEW_RULE_OUTCOMES":
        raise CandlestickDiscoveryError("candlestick specification is not frozen")
    bindings = [
        spec["inputs"]["trade_panel"],
        spec["inputs"]["champion_result"],
        spec["inputs"]["low_max_result"],
    ]
    bindings.extend(spec["inputs"]["daily_partitions"])
    for binding in bindings:
        path = resolve_path(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise CandlestickDiscoveryError(f"bound input changed: {path}")
    return spec


def load_daily(spec: dict[str, Any], symbols: list[str]) -> pd.DataFrame:
    paths = [binding["path"] for binding in spec["inputs"]["daily_partitions"]]
    symbol_frame = pd.DataFrame({"symbol": symbols})
    con = duckdb.connect(database=":memory:")
    con.register("selected_symbols", symbol_frame)
    columns = """
      d.trade_date,d.symbol,d.open,d.high,d.low,d.close,d.preclose,d.amount,
      d.turnover_fraction,d.trade_status,d.current_day_data_tradable,
      d.buy_blocked_open,d.sell_blocked_open,d.invalid_reasons,
      d.hard_valid,d.bar_valid,d.trading_state_valid,d.industry_valid,
      d.float_valid,d.corporate_action_valid,d.market_valid,d.market_rule_valid,
      d.historical_identity_valid,d.corporate_action_blocking,
      d.corporate_action_count,d.corporate_action_available_date,
      d.rights_ratio,d.share_multiplier,d.cash_per_share,d.available_at,d.decision_at
    """
    frame = con.execute(
        f"""SELECT {columns}
        FROM read_parquet({json.dumps(paths)}) d
        INNER JOIN selected_symbols s USING(symbol)
        WHERE d.trade_date <= DATE '2023-12-31'
        ORDER BY d.symbol,d.trade_date"""
    ).fetchdf()
    con.close()
    if frame.empty or frame.duplicated(["symbol", "trade_date"]).any():
        raise CandlestickDiscoveryError("invalid daily chart input")
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    history_valid = (
        frame.hard_valid.eq(True)
        & frame.bar_valid.eq(True)
        & frame.trading_state_valid.eq(True)
        & frame.industry_valid.eq(True)
        & frame.float_valid.eq(True)
        & frame.corporate_action_valid.eq(True)
        & frame.market_valid.eq(True)
        & frame.market_rule_valid.eq(True)
        & frame.historical_identity_valid.eq(True)
        & frame.corporate_action_blocking.eq(False)
        & frame.rights_ratio.fillna(0).eq(0)
        & frame.available_at.notna()
        & frame.decision_at.notna()
        & frame.available_at.le(frame.decision_at)
        & frame.open.gt(0)
        & frame.close.gt(0)
        & frame.high.ge(frame[["open", "close"]].max(axis=1))
        & frame.low.le(frame[["open", "close"]].min(axis=1))
        & frame.amount.ge(0)
    )
    frame["history_valid"] = history_valid
    frame["previous_close"] = frame.groupby("symbol", sort=False).close.shift()
    frame["previous_valid"] = frame.groupby("symbol", sort=False).history_valid.shift(
        fill_value=False
    )
    frame["previous_date"] = frame.groupby("symbol", sort=False).trade_date.shift()
    ordinary = frame.corporate_action_count.fillna(0).eq(0)
    visible_action = (
        frame.corporate_action_count.fillna(0).gt(0)
        & frame.corporate_action_available_date.notna()
        & pd.to_datetime(frame.corporate_action_available_date).le(frame.trade_date)
        & frame.share_multiplier.fillna(1).gt(0)
        & frame.previous_close.sub(frame.cash_per_share.fillna(0)).gt(0)
    )
    valid_step = frame.history_valid & frame.previous_valid & frame.previous_close.gt(0)
    frame["step_log_return"] = np.nan
    mask = valid_step & ordinary
    frame.loc[mask, "step_log_return"] = np.log(
        frame.loc[mask, "close"] / frame.loc[mask, "previous_close"]
    )
    mask = valid_step & visible_action
    adjusted_previous = (
        frame.loc[mask, "previous_close"] - frame.loc[mask, "cash_per_share"].fillna(0)
    ) / frame.loc[mask, "share_multiplier"].fillna(1)
    frame.loc[mask, "step_log_return"] = np.log(frame.loc[mask, "close"] / adjusted_previous)
    if (
        frame.loc[frame.history_valid & frame.previous_valid, "step_log_return"].isna().mean()
        > 0.005
    ):
        raise CandlestickDiscoveryError("too many unresolved chart-coordinate steps")
    frame["log_coordinate"] = (
        frame.step_log_return.fillna(0).groupby(frame.symbol, sort=False).cumsum()
    )
    frame["coordinate_close"] = np.exp(frame.log_coordinate)
    for column in ("open", "high", "low"):
        frame[f"coordinate_{column}"] = frame.coordinate_close * frame[column] / frame.close
    return frame


def _safe_return(values: pd.Series, periods: int) -> float:
    if len(values) <= periods or values.iloc[-periods - 1] <= 0:
        return math.nan
    return float(values.iloc[-1] / values.iloc[-periods - 1] - 1.0)


def _streak(step: pd.Series) -> int:
    signs = np.sign(step.dropna().to_numpy(float))
    if len(signs) == 0 or signs[-1] == 0:
        return 0
    target = signs[-1]
    count = 0
    for value in signs[::-1]:
        if value != target:
            break
        count += 1
    return int(count * target)


def build_feature_panel(
    trades: pd.DataFrame,
    daily: pd.DataFrame,
    checkpoints: tuple[int, ...] = (3, 5),
) -> pd.DataFrame:
    grouped = {
        symbol: group.reset_index(drop=True)
        for symbol, group in daily.groupby("symbol", sort=False)
    }
    rows: list[dict[str, Any]] = []
    for trade in trades.itertuples(index=False):
        history = grouped.get(trade.symbol)
        if history is None:
            raise CandlestickDiscoveryError(f"missing symbol history: {trade.symbol}")
        signal_date = pd.Timestamp(trade.signal_date)
        hits = history.index[history.trade_date.eq(signal_date)]
        if len(hits) != 1:
            raise CandlestickDiscoveryError(f"missing signal row: {trade.trade_id}")
        index = int(hits[0])
        prior = history.iloc[max(0, index - 40) : index + 1]
        if len(prior) < 21 or not bool(prior.history_valid.iloc[-1]):
            raise CandlestickDiscoveryError(f"insufficient chart history: {trade.trade_id}")
        close = prior.coordinate_close
        high20 = float(prior.coordinate_high.tail(20).max())
        low20 = float(prior.coordinate_low.tail(20).min())
        last = prior.iloc[-1]
        range_value = float(last.coordinate_high - last.coordinate_low)
        close_location = (
            (last.coordinate_close - last.coordinate_low) / range_value if range_value > 0 else 0.5
        )
        upper_wick = (
            (last.coordinate_high - max(last.coordinate_open, last.coordinate_close)) / range_value
            if range_value > 0
            else 0.0
        )
        lower_wick = (
            (min(last.coordinate_open, last.coordinate_close) - last.coordinate_low) / range_value
            if range_value > 0
            else 0.0
        )
        prior_close = prior.coordinate_close.shift()
        true_range = pd.concat(
            [
                prior.coordinate_high - prior.coordinate_low,
                (prior.coordinate_high - prior_close).abs(),
                (prior.coordinate_low - prior_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        step20 = prior.step_log_return.tail(20)
        path_length = float(step20.abs().sum())
        r20_log = float(step20.sum())
        amount_prior20 = prior.amount.iloc[-21:-1]
        amount5 = prior.amount.tail(5)
        row = {
            "trade_id": trade.trade_id,
            "signal_date": signal_date.date().isoformat(),
            "entry_date": str(trade.entry_date),
            "exit_date": str(trade.exit_date),
            "symbol": trade.symbol,
            "industry": trade.industry,
            "signal_rank": int(trade.signal_rank),
            "block": trade.block,
            "entry_year": pd.Timestamp(trade.entry_date).year,
            "final_net_return": float(trade.final_net_return),
            "severe_loss": bool(trade.final_net_return <= -0.10),
            "winner": bool(trade.final_net_return > 0),
            "r3": _safe_return(close, 3),
            "r5": _safe_return(close, 5),
            "r10": _safe_return(close, 10),
            "r20": _safe_return(close, 20),
            "signal_body_return": float(last.coordinate_close / last.coordinate_open - 1.0),
            "signal_close_location": float(close_location),
            "signal_upper_wick_fraction": float(upper_wick),
            "signal_lower_wick_fraction": float(lower_wick),
            "distance_ma5": float(last.coordinate_close / close.tail(5).mean() - 1.0),
            "distance_ma10": float(last.coordinate_close / close.tail(10).mean() - 1.0),
            "distance_ma20": float(last.coordinate_close / close.tail(20).mean() - 1.0),
            "distance_high20": float(last.coordinate_close / high20 - 1.0),
            "distance_low20": float(last.coordinate_close / low20 - 1.0),
            "atr20_fraction": float(true_range.tail(20).mean() / close.iloc[-2]),
            "signed_efficiency20": float(r20_log / path_length) if path_length > 0 else 0.0,
            "signal_amount_ratio20": float(last.amount / amount_prior20.median())
            if amount_prior20.median() > 0
            else math.nan,
            "amount5_to_prior20": float(amount5.mean() / amount_prior20.mean())
            if amount_prior20.mean() > 0
            else math.nan,
            "signed_streak": _streak(prior.step_log_return),
        }
        for checkpoint in checkpoints:
            checkpoint_index = index + checkpoint + 1
            if checkpoint_index >= len(history):
                continue
            observed = history.iloc[index + 1 : checkpoint_index + 1]
            current = observed.iloc[-1]
            entry_open = float(observed.coordinate_open.iloc[0])
            row[f"d{checkpoint}_close_from_entry"] = float(
                current.coordinate_close / entry_open - 1.0
            )
            row[f"d{checkpoint}_close_below_signal_low"] = bool(
                current.coordinate_close < last.coordinate_low
            )
            row[f"d{checkpoint}_close_below_ma10"] = bool(
                current.coordinate_close
                < history.coordinate_close.iloc[
                    max(0, checkpoint_index - 9) : checkpoint_index + 1
                ].mean()
            )
            row[f"d{checkpoint}_max_drawdown"] = float(
                observed.coordinate_low.min() / entry_open - 1.0
            )
            row[f"d{checkpoint}_max_runup"] = float(
                observed.coordinate_high.max() / entry_open - 1.0
            )
        rows.append(row)
    output = (
        pd.DataFrame(rows)
        .sort_values(["signal_date", "signal_rank", "symbol"])
        .reset_index(drop=True)
    )
    if len(output) != len(trades) or output.trade_id.duplicated().any():
        raise CandlestickDiscoveryError("feature panel does not conserve trades")
    return output


def _plot_trade(axis: Any, trade: Any, history: pd.DataFrame, show_outcome: bool) -> None:
    signal_date = pd.Timestamp(trade.signal_date)
    entry_date = pd.Timestamp(trade.entry_date)
    exit_date = pd.Timestamp(trade.exit_date)
    hits = history.index[history.trade_date.eq(signal_date)]
    index = int(hits[0])
    entry_hits = history.index[history.trade_date.eq(entry_date)]
    entry_index = int(entry_hits[0])
    start = max(0, index - 39)
    stop = min(len(history), entry_index + 26)
    window = history.iloc[start:stop].copy().reset_index(drop=True)
    entry_local = int(window.index[window.trade_date.eq(entry_date)][0])
    signal_local = int(window.index[window.trade_date.eq(signal_date)][0])
    exit_matches = window.index[window.trade_date.eq(exit_date)]
    exit_local = int(exit_matches[0]) if len(exit_matches) else len(window) - 1
    scale = float(window.coordinate_open.iloc[entry_local])
    for column in ("open", "high", "low", "close"):
        window[f"p_{column}"] = window[f"coordinate_{column}"] / scale
    x = np.arange(len(window))
    for pos, row in enumerate(window.itertuples(index=False)):
        up = row.p_close >= row.p_open
        color = "#d62728" if up else "#159447"
        axis.vlines(pos, row.p_low, row.p_high, color=color, linewidth=0.55, alpha=0.9)
        bottom = min(row.p_open, row.p_close)
        height = max(abs(row.p_close - row.p_open), 0.00035)
        axis.add_patch(
            plt.Rectangle(
                (pos - 0.32, bottom), 0.64, height, facecolor=color, edgecolor=color, linewidth=0.4
            )
        )
    ma5 = window.p_close.rolling(5).mean()
    ma20 = window.p_close.rolling(20).mean()
    axis.plot(x, ma5, color="#f0a202", linewidth=0.6, alpha=0.8)
    axis.plot(x, ma20, color="#5065a8", linewidth=0.7, alpha=0.8)
    axis.axvline(signal_local, color="#1f77b4", linestyle="--", linewidth=0.8)
    axis.axvline(entry_local, color="#0066ff", linewidth=0.9)
    axis.axvline(exit_local, color="#8a2be2", linewidth=0.8)
    axis.axhline(1.0, color="#777777", linewidth=0.45, alpha=0.6)
    activity = window.amount / window.amount.rolling(20, min_periods=5).median()
    finite = activity.replace([np.inf, -np.inf], np.nan).fillna(0).clip(0, 4)
    low, high = axis.get_ylim()
    span = high - low
    axis.bar(x, finite / 4 * span * 0.16, bottom=low, color="#9aa0a6", alpha=0.22, width=0.7)
    title = f"{trade.symbol} {trade.signal_date} r{trade.signal_rank}"
    if show_outcome:
        title += f"  R={trade.final_net_return:+.1%}"
    axis.set_title(title, fontsize=6.2, pad=1.5)
    axis.tick_params(axis="both", labelsize=4.5, length=1.5, pad=1)
    axis.set_xticks([signal_local, entry_local, exit_local])
    axis.set_xticklabels(["S", "E", "X"])
    axis.grid(alpha=0.12, linewidth=0.3)


def render_atlas(
    trades: pd.DataFrame, daily: pd.DataFrame, stage: str, show_outcomes: bool
) -> pd.DataFrame:
    grouped = {
        symbol: group.reset_index(drop=True)
        for symbol, group in daily.groupby("symbol", sort=False)
    }
    stage_root = OUTPUT_ROOT / "atlases" / stage
    stage_root.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    per_page = 20
    for stratum, lower, upper in STRATA:
        selected = trades.loc[
            trades.final_net_return.gt(lower) & trades.final_net_return.le(upper)
        ].copy()
        selected = selected.sort_values(["signal_date", "signal_rank", "symbol"])
        stratum_root = stage_root / stratum
        stratum_root.mkdir(parents=True, exist_ok=True)
        for page_number, offset in enumerate(range(0, len(selected), per_page), 1):
            page = selected.iloc[offset : offset + per_page]
            figure, axes = plt.subplots(4, 5, figsize=(19, 12), dpi=130)
            flat = axes.ravel()
            for panel_index, (_, trade) in enumerate(page.iterrows()):
                _plot_trade(flat[panel_index], trade, grouped[trade.symbol], show_outcomes)
                manifest.append(
                    {
                        "stage": stage,
                        "stratum": stratum,
                        "page": page_number,
                        "panel": panel_index + 1,
                        "trade_id": trade.trade_id,
                        "symbol": trade.symbol,
                        "signal_date": str(trade.signal_date),
                        "final_net_return": float(trade.final_net_return)
                        if show_outcomes
                        else math.nan,
                    }
                )
            for axis in flat[len(page) :]:
                axis.axis("off")
            title = (
                f"Strategy A candlestick atlas | {stage} | {stratum} | "
                f"page {page_number} | red=up green=down | S signal E entry X exit"
            )
            figure.suptitle(title, fontsize=10)
            figure.tight_layout(rect=(0, 0, 1, 0.975))
            figure.savefig(stratum_root / f"sheet_{page_number:03d}.png", bbox_inches="tight")
            plt.close(figure)
    output = pd.DataFrame(manifest)
    output.to_csv(OUTPUT_ROOT / f"{stage}_atlas_manifest.csv", index=False)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=tuple(STAGE_YEARS), required=True)
    parser.add_argument("--show-outcomes", action="store_true")
    args = parser.parse_args()
    spec = load_spec()
    trades = pd.read_parquet(resolve_path(spec["inputs"]["trade_panel"]["path"]))
    trades["entry_year"] = pd.to_datetime(trades.entry_date).dt.year
    if trades.entry_year.max() > 2023:
        raise CandlestickDiscoveryError("post-2023 trade encountered")
    daily = load_daily(spec, sorted(trades.symbol.unique()))
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    feature_path = OUTPUT_ROOT / "causal_chart_feature_panel.parquet"
    if not feature_path.exists():
        features = build_feature_panel(trades, daily)
        features.to_parquet(feature_path, index=False, compression="zstd")
    stage_trades = trades.loc[trades.entry_year.isin(STAGE_YEARS[args.stage])].copy()
    manifest = render_atlas(stage_trades, daily, args.stage, args.show_outcomes)
    summary = {
        "experiment_id": "ASHARE-CHAMPION-CANDLESTICK-RULE-DISCOVERY-V1",
        "spec_sha256": EXPECTED_SPEC_SHA256,
        "stage": args.stage,
        "years": list(STAGE_YEARS[args.stage]),
        "trades": len(stage_trades),
        "sheets": int(manifest[["stratum", "page"]].drop_duplicates().shape[0]),
        "show_outcomes": bool(args.show_outcomes),
        "feature_panel_sha256": sha256_file(feature_path),
        "manifest_sha256": sha256_file(OUTPUT_ROOT / f"{args.stage}_atlas_manifest.csv"),
        "post_2023_outcome_read": False,
        "cy011_read": False,
    }
    (OUTPUT_ROOT / f"{args.stage}_chart_build.json").write_text(
        json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
