from __future__ import annotations

# ruff: noqa: E501
import argparse
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from v6_data_common import (
    QMT_DATA_ROOT,
    RESEARCH_ROOT,
    atomic_write_json,
    atomic_write_parquet,
    canonical_symbol,
    parse_strategy_pool,
    sha256_file,
    strategy_sha256,
)

HYBRID_ROOT = RESEARCH_ROOT / "data" / "market_data_hybrid_etf_longest_v1"
EVENTS_PATH = RESEARCH_ROOT / "output" / "v6_hybrid_longest_replay_events.parquet"
SIGNALS_PATH = RESEARCH_ROOT / "output" / "v6_hybrid_longest_single_signal_metrics.parquet"
SUMMARY_PATH = RESEARCH_ROOT / "manifests" / "v6_hybrid_longest_single_signal_summary.json"
REPORT_PATH = RESEARCH_ROOT / "reports" / "v6_hybrid_longest_single_signal_quality.md"
START = date(2010, 1, 1)
END = date(2026, 8, 28)
HORIZONS = (0, 1, 5, 10, 20, 60)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=date.fromisoformat, default=START)
    parser.add_argument("--end", type=date.fromisoformat, default=END)
    parser.add_argument("--qmt-root", type=Path, default=QMT_DATA_ROOT)
    parser.add_argument("--hybrid-root", type=Path, default=HYBRID_ROOT)
    parser.add_argument("--events", type=Path, default=EVENTS_PATH)
    parser.add_argument("--signals", type=Path, default=SIGNALS_PATH)
    parser.add_argument("--summary", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    return parser.parse_args()


def daily_path(root: Path, symbol: str) -> Path:
    return root / "daily" / f"symbol={symbol}" / "daily.parquet"


def minute_path(root: Path, symbol: str) -> Path:
    return root / "minute_critical" / f"symbol={symbol}" / "critical.parquet"


def load_daily(root: Path, symbol: str) -> pd.DataFrame:
    frame = pd.read_parquet(daily_path(root, symbol))
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    frame = frame.set_index("trade_date").sort_index()
    invalid = ~frame["row_status"].eq("VALID")
    columns = ["pre_adj_high", "pre_adj_low", "pre_adj_close"]
    frame.loc[invalid, columns] = np.nan
    return frame


def load_open_prices(root: Path, symbols: list[str]) -> dict[tuple[date, str], float]:
    result: dict[tuple[date, str], float] = {}
    for symbol in symbols:
        frame = pd.read_parquet(minute_path(root, symbol))
        frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
        selected = frame[
            frame["bar_role"].eq("OPEN_BAR_09_30")
            & frame["row_status"].eq("VALID")
        ]
        for row in selected.itertuples(index=False):
            price = float(row.pre_adj_close)
            if np.isfinite(price) and price > 0:
                result[(row.trade_date, symbol)] = price
    return result


def forward_quality(
    daily: pd.DataFrame,
    action_date: date,
    reference_price: float,
    *,
    direction: int,
) -> dict[str, float]:
    if not np.isfinite(reference_price) or reference_price <= 0:
        return {}
    timestamp = pd.Timestamp(action_date)
    if timestamp not in daily.index:
        return {}
    location = daily.index.get_loc(timestamp)
    if not isinstance(location, (int, np.integer)):
        return {}
    result: dict[str, float] = {}
    for horizon in HORIZONS:
        target = int(location) + horizon
        if target >= len(daily):
            continue
        close = float(daily.iloc[target]["pre_adj_close"])
        if np.isfinite(close) and close > 0:
            underlying_return = close / reference_price - 1.0
            result[f"quality_{horizon}d"] = direction * underlying_return
    window = daily.iloc[int(location) + 1 : int(location) + 21]
    if not window.empty:
        high = float(window["pre_adj_high"].max())
        low = float(window["pre_adj_low"].min())
        if direction == 1:
            if np.isfinite(high):
                result["favorable_20d"] = high / reference_price - 1.0
            if np.isfinite(low):
                result["adverse_20d"] = low / reference_price - 1.0
        else:
            if np.isfinite(low):
                result["favorable_20d"] = 1.0 - low / reference_price
            if np.isfinite(high):
                result["adverse_20d"] = 1.0 - high / reference_price
    return result


def signal_rows(
    events: pd.DataFrame,
    daily: dict[str, pd.DataFrame],
    open_prices: dict[tuple[date, str], float],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    buys = events[events["event_type"].eq("BUY_SIGNAL")]
    for event in buys.itertuples(index=False):
        signal_date = pd.Timestamp(event.signal_date).date()
        action_date = event.trade_date
        price = open_prices.get((action_date, event.symbol))
        item: dict[str, Any] = {
            "signal_type": "BUY",
            "symbol": event.symbol,
            "signal_date": signal_date,
            "action_date": action_date,
            "reference_price": price,
            "quality_status": "EVALUABLE" if price is not None else "UNAVAILABLE_09_30",
            "reason": event.reason,
        }
        if price is not None:
            item.update(
                forward_quality(
                    daily[event.symbol],
                    action_date,
                    price,
                    direction=1,
                )
            )
        rows.append(item)

    sells = events[events["event_type"].eq("TAIL_SELL_SIGNAL")]
    for event in sells.itertuples(index=False):
        price = float(event.price_pre_adj)
        evaluable = np.isfinite(price) and price > 0
        item = {
            "signal_type": "SELL",
            "symbol": event.symbol,
            "signal_date": event.trade_date,
            "action_date": event.trade_date,
            "reference_price": price if evaluable else None,
            "quality_status": "EVALUABLE" if evaluable else "UNAVAILABLE_14_57",
            "reason": event.reason,
        }
        if evaluable:
            item.update(
                forward_quality(
                    daily[event.symbol],
                    event.trade_date,
                    price,
                    direction=-1,
                )
            )
        rows.append(item)

    result = pd.DataFrame(rows)
    result["signal_year"] = pd.to_datetime(result["signal_date"]).dt.year
    return result.sort_values(["signal_date", "signal_type", "symbol"]).reset_index(drop=True)


def distribution(values: pd.Series) -> dict[str, float | int | None]:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "win_rate": None,
            "p10": None,
            "p90": None,
        }
    return {
        "n": len(clean),
        "mean": float(clean.mean()),
        "median": float(clean.median()),
        "win_rate": float(clean.gt(0).mean()),
        "p10": float(clean.quantile(0.1)),
        "p90": float(clean.quantile(0.9)),
    }


def annual_summary(
    signals: pd.DataFrame,
    start_year: int,
    end_year: int,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for year in range(start_year, end_year + 1):
        year_data = signals[signals["signal_year"].eq(year)]
        result[str(year)] = {}
        for signal_type in ["BUY", "SELL"]:
            selected = year_data[year_data["signal_type"].eq(signal_type)]
            result[str(year)][signal_type.lower()] = {
                "signals": len(selected),
                "evaluable": int(selected["quality_status"].eq("EVALUABLE").sum()),
                "quality": {
                    f"{horizon}d": distribution(selected[f"quality_{horizon}d"])
                    if f"quality_{horizon}d" in selected
                    else distribution(pd.Series(dtype="float64"))
                    for horizon in HORIZONS
                },
                "favorable_20d": distribution(selected["favorable_20d"])
                if "favorable_20d" in selected
                else distribution(pd.Series(dtype="float64")),
                "adverse_20d": distribution(selected["adverse_20d"])
                if "adverse_20d" in selected
                else distribution(pd.Series(dtype="float64")),
            }
    return result


def percent(value: object) -> str:
    if value is None or pd.isna(value):
        return "NA"
    return f"{float(value):+.2%}"


def rate(value: object) -> str:
    if value is None or pd.isna(value):
        return "NA"
    return f"{float(value):.2%}"


def write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# SuperMind V6 longest single-signal quality",
        "",
        "Every BUY_SIGNAL and TAIL_SELL_SIGNAL is equally weighted; portfolio sizing and holding P&L are ignored.",
        "Positive SELL quality means the underlying fell after the sell signal.",
        "",
        "## Buy signals",
        "",
        "| Year | Signals | Evaluable | 1d mean | 5d mean | 20d mean | 60d mean | 20d win |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for year, item in summary["annual"].items():
        buy = item["buy"]
        lines.append(
            f"| {year} | {buy['signals']} | {buy['evaluable']} | "
            f"{percent(buy['quality']['1d']['mean'])} | {percent(buy['quality']['5d']['mean'])} | "
            f"{percent(buy['quality']['20d']['mean'])} | {percent(buy['quality']['60d']['mean'])} | "
            f"{rate(buy['quality']['20d']['win_rate'])} |"
        )
    lines.extend(
        [
            "",
            "## Sell signals",
            "",
            "| Year | Signals | Evaluable | 1d avoided | 5d avoided | 20d avoided | 60d avoided | 20d correct |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for year, item in summary["annual"].items():
        sell = item["sell"]
        lines.append(
            f"| {year} | {sell['signals']} | {sell['evaluable']} | "
            f"{percent(sell['quality']['1d']['mean'])} | {percent(sell['quality']['5d']['mean'])} | "
            f"{percent(sell['quality']['20d']['mean'])} | {percent(sell['quality']['60d']['mean'])} | "
            f"{rate(sell['quality']['20d']['win_rate'])} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- BUY is evaluated from the exact next 09:30 critical-bar reference price.",
            "- SELL is evaluated from the exact 14:57 signal reference price; positive quality means avoided loss.",
            "- Missing or invalid critical prices are UNAVAILABLE and excluded from averages, never replaced by daily prices.",
            "- No portfolio weight, cash, position count, rebalance weight, or holding-period exit pairing is used.",
            "- Signals still come from the frozen strategy state machine; this does not invent daily signals while a name is already held.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    symbols = [canonical_symbol(symbol) for symbol in parse_strategy_pool()]
    daily = {symbol: load_daily(args.qmt_root, symbol) for symbol in symbols}
    open_prices = load_open_prices(args.hybrid_root, symbols)
    events = pd.read_parquet(args.events)
    events["trade_date"] = pd.to_datetime(events["trade_date"]).dt.date
    events = events[events["trade_date"].between(args.start, args.end)].copy()
    signals = signal_rows(events, daily, open_prices)
    atomic_write_parquet(signals, args.signals)
    summary = {
        "analysis_version": "v6-longest-single-signal-quality-1",
        "status": "EXPLORATORY_HYBRID_SINGLE_SIGNAL",
        "generated_at": datetime.now().astimezone().isoformat(),
        "window_start": args.start.isoformat(),
        "window_end": args.end.isoformat(),
        "strategy_source_sha256": strategy_sha256(),
        "events_path": str(args.events),
        "events_sha256": sha256_file(args.events),
        "signals_path": str(args.signals),
        "signals_sha256": sha256_file(args.signals),
        "signal_counts": {
            str(key): int(value)
            for key, value in signals["signal_type"].value_counts().items()
        },
        "quality_status_counts": {
            str(key): int(value)
            for key, value in signals["quality_status"].value_counts().items()
        },
        "annual": annual_summary(signals, args.start.year, args.end.year),
        "definitions": {
            "buy_quality": "future close / exact next-open reference - 1",
            "sell_quality": "1 - future close / exact 14:57 signal reference",
            "positive": "correct directional signal",
        },
    }
    atomic_write_json(args.summary, summary)
    write_report(args.report, summary)
    print(f"SIGNALS {len(signals)} {args.signals}")
    print(f"SUMMARY {args.summary}")
    print(f"REPORT {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
