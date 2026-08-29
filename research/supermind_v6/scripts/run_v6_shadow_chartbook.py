from __future__ import annotations

# ruff: noqa: E501
import argparse
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Rectangle
from v6_data_common import (
    MANIFEST_DIR,
    QMT_DATA_ROOT,
    RESEARCH_ROOT,
    STRATEGY_PATH,
    atomic_write_json,
    atomic_write_parquet,
    canonical_symbol,
    parse_strategy_pool,
    sha256_file,
    strategy_sha256,
)

DEFAULT_START = date(2025, 8, 28)
DEFAULT_END = date(2026, 8, 28)
AVAILABILITY_PATH = QMT_DATA_ROOT / "execution_availability" / "critical_execution.parquet"
OUTPUT_DIR = RESEARCH_ROOT / "output" / "pdf"
DEFAULT_PDF = OUTPUT_DIR / "v6_shadow_replay_candles_20250828_20260828.pdf"
DEFAULT_EVENTS = RESEARCH_ROOT / "output" / "v6_shadow_replay_events.parquet"
DEFAULT_SUMMARY = MANIFEST_DIR / "v6_shadow_replay_summary.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a bounded, fail-closed shadow replay and render one V6 ETF candle page each"
    )
    parser.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    parser.add_argument("--end", type=date.fromisoformat, default=DEFAULT_END)
    parser.add_argument("--availability", type=Path, default=AVAILABILITY_PATH)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    return parser.parse_args()


class QuietLog:
    def info(self, *_: object) -> None:
        return None

    def warn(self, *_: object) -> None:
        return None


@dataclass
class Position:
    symbol: str
    target_weight: float
    entry_date: date
    entry_price: float


class ShadowPlatform:
    def __init__(
        self,
        daily: dict[str, pd.DataFrame],
        minute: dict[str, pd.DataFrame],
        availability: pd.DataFrame,
        calendar: list[pd.Timestamp],
    ) -> None:
        self.daily = daily
        self.minute = minute
        self.availability = availability.set_index(["trade_date", "symbol"])
        self.calendar = calendar
        self.current_date = calendar[0].date()
        self.event_stage = ""
        self.positions: dict[str, Position] = {}
        self.events: list[dict[str, Any]] = []
        self.list_dates = {
            symbol: frame.index.min().date() for symbol, frame in daily.items() if not frame.empty
        }

    def _current_row(self, symbol: str) -> pd.Series | None:
        key = (self.current_date, symbol)
        if key not in self.availability.index:
            return None
        value = self.availability.loc[key]
        if isinstance(value, pd.DataFrame):
            raise ValueError(f"duplicate availability row: {key}")
        return value

    def _minute_price(self, symbol: str, role: str, field: str) -> float:
        frame = self.minute[symbol]
        selected = frame[
            (frame["trade_date"].eq(self.current_date)) & frame["bar_role"].eq(role)
        ]
        if len(selected) != 1:
            return float("nan")
        value = float(selected.iloc[0][field])
        return value if np.isfinite(value) and value > 0 else float("nan")

    def _daily_marker_price(self, symbol: str) -> float:
        frame = self.daily[symbol]
        timestamp = pd.Timestamp(self.current_date)
        if timestamp not in frame.index:
            return float("nan")
        value = float(frame.loc[timestamp, "pre_adj_close"])
        return value if np.isfinite(value) and value > 0 else float("nan")

    def _record(self, event_type: str, symbol: str, *, price: float = np.nan, **extra: object) -> None:
        self.events.append(
            {
                "trade_date": self.current_date,
                "symbol": symbol,
                "event_type": event_type,
                "stage": self.event_stage,
                "price_pre_adj": price,
                **extra,
            }
        )

    def history(
        self,
        symbols: list[str],
        fields: list[str],
        count: int,
        period: str,
        *_: object,
    ) -> dict[str, pd.DataFrame]:
        if period != "1d":
            return {}
        result: dict[str, pd.DataFrame] = {}
        cutoff = pd.Timestamp(self.current_date)
        for symbol in symbols:
            if symbol not in self.daily:
                continue
            frame = self.daily[symbol]
            selected = frame[frame.index < cutoff].tail(count).copy()
            if selected.empty:
                continue
            data = pd.DataFrame(index=selected.index)
            for field in fields:
                if field == "close":
                    data[field] = selected["pre_adj_close"]
                elif field == "volume":
                    data[field] = selected["volume_raw"]
                elif field == "turnover":
                    data[field] = selected["amount_cny"]
                else:
                    raise ValueError(f"unsupported shadow history field: {field}")
            result[symbol] = data
        return result

    def get_all_securities(self, security_type: str) -> pd.DataFrame:
        if security_type != "etf":
            return pd.DataFrame()
        active = [
            symbol
            for symbol, list_date in self.list_dates.items()
            if list_date <= self.current_date
        ]
        return pd.DataFrame(index=active)

    def get_trade_days(self, start: str, end: str) -> list[pd.Timestamp]:
        lower = pd.Timestamp(start)
        upper = pd.Timestamp(end)
        return [day for day in self.calendar if lower <= day <= upper]

    def bar_dict(self, *, include_signal: bool = False, include_close: bool = False) -> dict[str, Any]:
        bars: dict[str, Any] = {}
        for symbol in self.daily:
            row = self._current_row(symbol)
            if row is None:
                continue
            if include_signal and bool(row["tail_signal_available_14_57"]):
                price = self._minute_price(symbol, "PSEUDO_CLOSE_14_57_OPEN", "pre_adj_open")
                if np.isfinite(price):
                    bars[symbol] = SimpleNamespace(open=price, close=price)
            elif include_close and bool(row["executable_15_00"]):
                price = self._minute_price(symbol, "FINAL_CLOSE_BAR", "pre_adj_close")
                if np.isfinite(price):
                    bars[symbol] = SimpleNamespace(open=price, close=price)
            elif self.event_stage == "open" and bool(row["executable_09_30"]):
                price = self._minute_price(symbol, "OPEN_BAR_09_30", "pre_adj_close")
                if np.isfinite(price):
                    bars[symbol] = SimpleNamespace(open=price, close=price)
        return bars

    def order_target_percent(self, symbol: str, target_weight: float) -> object | None:
        row = self._current_row(symbol)
        if self.event_stage != "open" or row is None or not bool(row["executable_09_30"]):
            self._record(
                "BUY_OR_REBALANCE_NO_FILL",
                symbol,
                price=self._daily_marker_price(symbol),
                target_weight=float(target_weight),
            )
            return None
        price = self._minute_price(symbol, "OPEN_BAR_09_30", "pre_adj_close")
        event_type = "BUY_FILLED" if symbol not in self.positions else "REBALANCE_FILLED"
        if event_type == "BUY_FILLED":
            self.positions[symbol] = Position(
                symbol=symbol,
                target_weight=float(target_weight),
                entry_date=self.current_date,
                entry_price=price,
            )
        else:
            position = self.positions[symbol]
            position.target_weight = float(target_weight)
        self._record(event_type, symbol, price=price, target_weight=float(target_weight))
        return f"shadow-open-{symbol}-{self.current_date.isoformat()}"

    def order_target(self, symbol: str, target: float) -> object | None:
        if target != 0:
            raise ValueError("shadow only supports liquidation order_target(code, 0)")
        row = self._current_row(symbol)
        if row is None:
            self._record("SELL_NO_FILL", symbol, price=self._daily_marker_price(symbol))
            return None
        if self.event_stage == "open":
            executable = bool(row["executable_09_30"])
            role, field = "OPEN_BAR_09_30", "pre_adj_close"
        elif self.event_stage == "close":
            executable = bool(row["executable_15_00"])
            role, field = "FINAL_CLOSE_BAR", "pre_adj_close"
        else:
            raise ValueError(f"unexpected liquidation stage: {self.event_stage}")
        if not executable:
            self._record("SELL_NO_FILL", symbol, price=self._daily_marker_price(symbol))
            return None
        price = self._minute_price(symbol, role, field)
        position = self.positions.pop(symbol, None)
        if position is None:
            raise ValueError(f"sell fill without shadow position: {symbol}")
        self._record(
            "SELL_FILLED",
            symbol,
            price=price,
            entry_date=position.entry_date,
            entry_price=position.entry_price,
            holding_pnl_pct=price / position.entry_price - 1.0,
        )
        return f"shadow-{self.event_stage}-{symbol}-{self.current_date.isoformat()}"


def daily_path(symbol: str) -> Path:
    return QMT_DATA_ROOT / "daily" / f"symbol={symbol}" / "daily.parquet"


def minute_path(symbol: str) -> Path:
    return QMT_DATA_ROOT / "minute_critical" / f"symbol={symbol}" / "critical.parquet"


def load_daily(symbol: str) -> pd.DataFrame:
    frame = pd.read_parquet(daily_path(symbol))
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    frame = frame.set_index("trade_date").sort_index()
    invalid = ~frame["row_status"].eq("VALID")
    for column in ["pre_adj_open", "pre_adj_high", "pre_adj_low", "pre_adj_close", "volume_raw", "amount_cny"]:
        frame.loc[invalid, column] = np.nan
    return frame


def load_minute(symbol: str) -> pd.DataFrame:
    frame = pd.read_parquet(minute_path(symbol))
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    return frame


def frozen_namespace(platform: ShadowPlatform) -> dict[str, Any]:
    namespace: dict[str, Any] = {
        "np": np,
        "pd": pd,
        "log": QuietLog(),
        "set_benchmark": lambda *_: None,
        "set_commission": lambda *_: None,
        "set_slippage": lambda *_: None,
        "set_volume_limit": lambda *_: None,
        "set_execution": lambda *_: None,
        "enable_open_bar": lambda *_: None,
        "PerShare": lambda **kwargs: kwargs,
        "PriceSlippage": lambda *_: None,
        "history": platform.history,
        "get_all_securities": platform.get_all_securities,
        "get_trade_days": platform.get_trade_days,
        "get_datetime": lambda: pd.Timestamp(platform.current_date).to_pydatetime(),
        "order_target_percent": platform.order_target_percent,
        "order_target": platform.order_target,
    }
    source = STRATEGY_PATH.read_text(encoding="utf-8")
    exec(compile(source, str(STRATEGY_PATH), "exec"), namespace)
    return namespace


def record_pending_signals(
    platform: ShadowPlatform,
    context: SimpleNamespace,
    prior_holdings: set[str],
) -> None:
    if context.pending_desired is None:
        return
    for symbol in context.pending_desired:
        if symbol not in prior_holdings:
            platform._record(
                "BUY_SIGNAL",
                symbol,
                reason=context.pending_reason,
                signal_date=(pd.Timestamp(platform.current_date) - pd.Timedelta(days=1)).date(),
            )


def run_shadow(
    start: date,
    end: date,
    availability: pd.DataFrame,
) -> tuple[dict[str, pd.DataFrame], list[pd.Timestamp], pd.DataFrame, dict[str, Any]]:
    symbols = [canonical_symbol(code) for code in parse_strategy_pool()]
    all_daily_symbols = [*symbols, "000852.SH"]
    daily = {symbol: load_daily(symbol) for symbol in all_daily_symbols}
    minute = {symbol: load_minute(symbol) for symbol in all_daily_symbols}
    calendar = [
        day
        for day in daily["000852.SH"].index
        if start <= day.date() <= end and np.isfinite(daily["000852.SH"].loc[day, "pre_adj_close"])
    ]
    if not calendar:
        raise ValueError("no calendar sessions in requested shadow window")
    platform = ShadowPlatform(daily, minute, availability, calendar)
    namespace = frozen_namespace(platform)
    context = SimpleNamespace()
    context.portfolio = SimpleNamespace(stock_account=SimpleNamespace(positions=platform.positions))
    namespace["init"](context)

    for timestamp in calendar:
        platform.current_date = timestamp.date()
        platform.event_stage = "before_trading"
        prior_holdings = set(platform.positions)
        namespace["before_trading"](context)
        record_pending_signals(platform, context, prior_holdings)

        platform.event_stage = "open"
        namespace["execute_pending_open"](context, platform.bar_dict(), "SHADOW_09_30")

        platform.event_stage = "signal"
        namespace["run_1457_exit_signal"](context, platform.bar_dict(include_signal=True))
        for symbol in context.pending_close_sells:
            price = platform._minute_price(symbol, "PSEUDO_CLOSE_14_57_OPEN", "pre_adj_open")
            platform._record(
                "TAIL_SELL_SIGNAL",
                symbol,
                price=price,
                reason=context.pending_close_reason,
            )

        platform.event_stage = "close"
        namespace["execute_pending_close_sells"](context, platform.bar_dict(include_close=True))

    events = pd.DataFrame(platform.events)
    if events.empty:
        events = pd.DataFrame(
            columns=["trade_date", "symbol", "event_type", "stage", "price_pre_adj"]
        )
    else:
        events["trade_date"] = pd.to_datetime(events["trade_date"]).dt.date
        events = events.sort_values(["trade_date", "symbol", "event_type"]).reset_index(drop=True)
    summary = {
        "shadow_replay_version": "v6-shadow-replay-1",
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "strategy_source_sha256": strategy_sha256(),
        "price_basis": "QMT pre_adj; SuperMind fq=pre equivalence remains unverified",
        "execution_assumption": (
            "09:30/15:00 shadow fills use QMT critical-minute close only when execution availability is valid"
        ),
        "no_fill_policy": "unavailable 09:30 or 15:00 bar => no fill; frozen retry state is retained",
        "tail_policy": "unavailable 14:57 bar => no intraday tail signal",
        "exact_supermind_replication": False,
        "calendar_sessions": len(calendar),
        "event_counts": {str(key): int(value) for key, value in events["event_type"].value_counts().items()},
    }
    return daily, calendar, events, summary


def candle(ax: plt.Axes, frame: pd.DataFrame) -> None:
    valid = frame.dropna(subset=["pre_adj_open", "pre_adj_high", "pre_adj_low", "pre_adj_close"])
    x = mdates.date2num(valid.index.to_pydatetime())
    width = 0.58
    for xpos, (_, row) in zip(x, valid.iterrows(), strict=True):
        opening = float(row.pre_adj_open)
        closing = float(row.pre_adj_close)
        color = "#d04a4a" if closing >= opening else "#207f4d"
        ax.vlines(xpos, float(row.pre_adj_low), float(row.pre_adj_high), color=color, linewidth=0.55)
        low = min(opening, closing)
        height = max(abs(closing - opening), max(opening, closing) * 0.00035)
        ax.add_patch(Rectangle((xpos - width / 2, low), width, height, color=color, alpha=0.75))
    ax.xaxis_date()
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.grid(alpha=0.18, linewidth=0.5)


PLOTTED_EVENT_TYPES = [
    "BUY_FILLED",
    "SELL_FILLED",
    "BUY_OR_REBALANCE_NO_FILL",
    "SELL_NO_FILL",
    "TAIL_SELL_SIGNAL",
]


def chart_events(events: pd.DataFrame) -> pd.DataFrame:
    plotted = events[events["event_type"].isin(PLOTTED_EVENT_TYPES)].copy()
    plotted = plotted.sort_values(["trade_date", "event_type"]).reset_index(drop=True)
    prefixes = {
        "BUY_FILLED": "B",
        "SELL_FILLED": "S",
        "BUY_OR_REBALANCE_NO_FILL": "N",
        "SELL_NO_FILL": "N",
        "TAIL_SELL_SIGNAL": "T",
    }
    counters: dict[str, int] = {}
    labels = []
    for row in plotted.itertuples(index=False):
        prefix = prefixes[row.event_type]
        counters[prefix] = counters.get(prefix, 0) + 1
        labels.append(f"{prefix}{counters[prefix]:02d}")
    plotted["marker_id"] = labels
    return plotted


def add_markers(ax: plt.Axes, events: pd.DataFrame) -> pd.DataFrame:
    styles = {
        "BUY_FILLED": ("^", "#147d46", "Buy filled"),
        "SELL_FILLED": ("v", "#c92828", "Sell filled"),
        "BUY_OR_REBALANCE_NO_FILL": ("x", "#d98a00", "Open no-fill"),
        "SELL_NO_FILL": ("x", "#7b2cbf", "Sell no-fill"),
        "TAIL_SELL_SIGNAL": ("D", "#3e5fa8", "14:57 sell signal"),
    }
    used: set[str] = set()
    plotted = chart_events(events)
    for event_type, (marker, color, label) in styles.items():
        rows = plotted[plotted["event_type"].eq(event_type)]
        if rows.empty:
            continue
        dates = pd.to_datetime(rows["trade_date"])
        prices = rows["price_pre_adj"].astype(float)
        fallback = np.full(len(rows), np.nan)
        values = np.where(np.isfinite(prices), prices, fallback)
        ax.scatter(
            dates,
            values,
            marker=marker,
            s=52,
            c=color,
            edgecolors="white" if marker not in {"x"} else color,
            linewidths=0.45,
            label=label if label not in used else None,
            zorder=5,
        )
        for ordinal, row in enumerate(rows.itertuples(index=False)):
            offset = 8 if ordinal % 2 == 0 else -15
            ax.annotate(
                row.marker_id,
                (pd.Timestamp(row.trade_date), float(row.price_pre_adj)),
                xytext=(0, offset),
                textcoords="offset points",
                ha="center",
                va="bottom" if offset > 0 else "top",
                fontsize=6.2,
                color=color,
                weight="bold",
                zorder=6,
            )
        used.add(label)
    if used:
        ax.legend(loc="upper left", fontsize=6.5, ncol=3, frameon=False)
    return plotted


def forward_return(frame: pd.DataFrame, event_date: date, days: int = 20) -> float | None:
    index = frame.index
    timestamp = pd.Timestamp(event_date)
    if timestamp not in index:
        return None
    position = int(index.get_loc(timestamp))
    if position + days >= len(frame):
        return None
    entry = float(frame.iloc[position]["pre_adj_close"])
    later = float(frame.iloc[position + days]["pre_adj_close"])
    if not np.isfinite(entry) or not np.isfinite(later) or entry <= 0:
        return None
    return later / entry - 1.0


def draw_cover(pdf: PdfPages, summary: dict[str, Any], events: pd.DataFrame, daily: dict[str, pd.DataFrame]) -> None:
    fills = events[events["event_type"].eq("BUY_FILLED")]
    returns = [
        value
        for row in fills.itertuples(index=False)
        if (value := forward_return(daily[row.symbol], row.trade_date)) is not None
    ]
    fig = plt.figure(figsize=(11.69, 8.27))
    fig.patch.set_facecolor("white")
    fig.text(0.06, 0.91, "SuperMind V6 - one-year shadow replay chartbook", fontsize=20, weight="bold")
    fig.text(0.06, 0.865, f"Window: {summary['window_start']} to {summary['window_end']}", fontsize=11)
    fig.text(0.06, 0.825, "152 ETF daily candlesticks; filled and fail-closed order events overlaid.", fontsize=10)
    lines = [
        f"Calendar sessions: {summary['calendar_sessions']}",
        f"Buy fills: {summary['event_counts'].get('BUY_FILLED', 0)} | Sell fills: {summary['event_counts'].get('SELL_FILLED', 0)}",
        f"Open no-fills: {summary['event_counts'].get('BUY_OR_REBALANCE_NO_FILL', 0)} | Sell no-fills: {summary['event_counts'].get('SELL_NO_FILL', 0)}",
        f"20-session forward return after buy fills: n={len(returns)}; median={np.median(returns):.2%}" if returns else "20-session forward return after buy fills: no eligible sample",
        f"20-session forward return win rate: {np.mean(np.asarray(returns) > 0):.1%}" if returns else "",
    ]
    y = 0.73
    for line in lines:
        if line:
            fig.text(0.08, y, line, fontsize=11)
            y -= 0.048
    caveat = (
        "Method: frozen V6 functions run against a local API sandbox. Daily signals are T+1; 09:30 and 15:00\n"
        "orders fill only when the critical bar is VALID. Missing/zero-volume bars are no-fill; unavailable 14:57\n"
        "bars suppress that tail signal. Both strategy market anchors have the required 14:57 shadow input in this\n"
        "window. Price basis is QMT pre-adjusted; this is not an exact SuperMind result."
    )
    fig.text(0.08, 0.38, caveat, fontsize=9.5, color="#4a4a4a", linespacing=1.5)
    fig.text(0.08, 0.20, f"Frozen strategy SHA-256: {summary['strategy_source_sha256']}", fontsize=8, color="#666666")
    fig.text(0.08, 0.16, "Marker key: green up = buy fill; red down = sell fill; orange x = open no-fill; purple x = sell no-fill; blue diamond = 14:57 sell signal.", fontsize=8)
    fig.text(0.92, 0.04, "Page 1", fontsize=8, ha="right", color="#666666")
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def draw_symbol_page(pdf: PdfPages, symbol: str, frame: pd.DataFrame, events: pd.DataFrame, page: int) -> pd.DataFrame:
    fig, ax = plt.subplots(figsize=(11.69, 8.27))
    fig.subplots_adjust(left=0.07, right=0.97, top=0.88, bottom=0.12)
    candle(ax, frame)
    symbol_events = events[events["symbol"].eq(symbol)]
    plotted_events = add_markers(ax, symbol_events)
    fills = symbol_events[symbol_events["event_type"].isin(["BUY_FILLED", "SELL_FILLED"])]
    ax.set_title(f"{symbol} | QMT pre-adjusted daily candles | shadow replay events", loc="left", fontsize=12, weight="bold")
    ax.set_ylabel("Price (QMT pre-adjusted)")
    ax.tick_params(axis="x", labelrotation=0, labelsize=8)
    summary = (
        f"buy={int((symbol_events.event_type == 'BUY_FILLED').sum())}  "
        f"sell={int((symbol_events.event_type == 'SELL_FILLED').sum())}  "
        f"open_no_fill={int((symbol_events.event_type == 'BUY_OR_REBALANCE_NO_FILL').sum())}  "
        f"sell_no_fill={int((symbol_events.event_type == 'SELL_NO_FILL').sum())}  "
        f"tail_signals={int((symbol_events.event_type == 'TAIL_SELL_SIGNAL').sum())}  "
        f"filled_events={len(fills)}"
    )
    fig.text(0.07, 0.055, summary, fontsize=7.5, color="#555555")
    if not plotted_events.empty:
        fig.text(
            0.07,
            0.032,
            "Marker IDs map to the following event-ledger page(s): date, strategy time, QMT price, and holding P&L.",
            fontsize=7.2,
            color="#555555",
        )
    fig.text(0.97, 0.035, f"Page {page}", fontsize=8, ha="right", color="#666666")
    pdf.savefig(fig)
    plt.close(fig)
    return plotted_events


def display_text(value: object) -> str:
    if value is None or pd.isna(value):
        return "-"
    if isinstance(value, (float, np.floating)):
        return f"{value:.4f}"
    return str(value)


def draw_event_ledger_pages(pdf: PdfPages, symbol: str, events: pd.DataFrame, page: int) -> int:
    if events.empty:
        return page
    type_names = {
        "BUY_FILLED": "Buy filled",
        "SELL_FILLED": "Sell filled",
        "BUY_OR_REBALANCE_NO_FILL": "Open no-fill",
        "SELL_NO_FILL": "Sell no-fill",
        "TAIL_SELL_SIGNAL": "14:57 sell signal",
    }
    stages = {
        "open": "09:30 shadow open",
        "close": "15:00 shadow close",
        "signal": "14:57 callback",
    }
    ledger = chart_events(events)
    ledger["event"] = ledger["event_type"].map(type_names)
    ledger["time"] = ledger["stage"].map(stages).fillna("-")
    ledger["date"] = ledger["trade_date"].map(lambda value: value.isoformat())
    ledger["price"] = ledger["price_pre_adj"].map(display_text)
    ledger["entry_date_display"] = ledger.get("entry_date", pd.Series(index=ledger.index, dtype=object)).map(display_text)
    ledger["entry_price_display"] = ledger.get("entry_price", pd.Series(index=ledger.index, dtype=float)).map(display_text)
    ledger["pnl"] = ledger.get("holding_pnl_pct", pd.Series(index=ledger.index, dtype=float)).map(
        lambda value: "-" if pd.isna(value) else f"{float(value):+.2%}"
    )
    ledger["reason_display"] = ledger.get("reason", pd.Series(index=ledger.index, dtype=object)).map(display_text)
    for start in range(0, len(ledger), 12):
        part = ledger.iloc[start : start + 12]
        fig, ax = plt.subplots(figsize=(11.69, 8.27))
        ax.axis("off")
        ax.set_title(f"{symbol} | shadow replay event ledger", loc="left", fontsize=15, weight="bold", pad=20)
        headers = ["ID", "Event", "Date", "Strategy time", "QMT px", "Entry date", "Entry px", "Holding P&L", "Reason"]
        rows = [
            [
                row.marker_id,
                row.event,
                row.date,
                row.time,
                row.price,
                row.entry_date_display,
                row.entry_price_display,
                row.pnl,
                row.reason_display,
            ]
            for row in part.itertuples(index=False)
        ]
        table = ax.table(
            cellText=rows,
            colLabels=headers,
            loc="center",
            cellLoc="left",
            colLoc="left",
            colWidths=[0.06, 0.14, 0.11, 0.16, 0.09, 0.11, 0.09, 0.10, 0.14],
        )
        table.auto_set_font_size(False)
        table.set_fontsize(7.3)
        table.scale(1, 1.65)
        for (row_idx, _), cell in table.get_celld().items():
            cell.set_edgecolor("#d0d0d0")
            if row_idx == 0:
                cell.set_facecolor("#eaf0f7")
                cell.set_text_props(weight="bold")
            elif row_idx % 2 == 0:
                cell.set_facecolor("#fafafa")
        fig.text(
            0.07,
            0.12,
            "QMT px is the shadow execution/signal price on the pre-adjusted basis. Holding P&L is exit price / initial buy-fill price - 1; it excludes fees, slippage, position sizing, and rebalance effects.",
            fontsize=8,
            color="#4a4a4a",
        )
        fig.text(
            0.07,
            0.085,
            "No-fill rows have no execution price. This is research-only and not an exact SuperMind backtest.",
            fontsize=8,
            color="#4a4a4a",
        )
        fig.text(0.97, 0.035, f"Page {page}", fontsize=8, ha="right", color="#666666")
        pdf.savefig(fig)
        plt.close(fig)
        page += 1
    return page


def render_chartbook(pdf_path: Path, daily: dict[str, pd.DataFrame], events: pd.DataFrame, summary: dict[str, Any]) -> int:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pool_symbols = [canonical_symbol(code) for code in parse_strategy_pool()]
    with PdfPages(pdf_path) as pdf:
        draw_cover(pdf, summary, events, daily)
        page = 2
        for symbol in pool_symbols:
            frame = daily[symbol]
            frame = frame[(frame.index.date >= date.fromisoformat(summary["window_start"])) & (frame.index.date <= date.fromisoformat(summary["window_end"]))]
            symbol_events = events[events["symbol"].eq(symbol)]
            draw_symbol_page(pdf, symbol, frame, symbol_events, page)
            page += 1
            page = draw_event_ledger_pages(pdf, symbol, symbol_events, page)
    return page - 1


def portable_path(path: Path) -> str:
    return path.resolve().relative_to(RESEARCH_ROOT.parent.parent.resolve()).as_posix()


def main() -> int:
    args = parse_args()
    availability = pd.read_parquet(args.availability)
    availability["trade_date"] = pd.to_datetime(availability["trade_date"]).dt.date
    availability = availability[
        availability["trade_date"].between(args.start, args.end)
    ].copy()
    daily, _calendar, events, summary = run_shadow(args.start, args.end, availability)
    args.events.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_parquet(events, args.events)
    pdf_pages = render_chartbook(args.pdf, daily, events, summary)
    summary.update(
        {
            "availability_path": portable_path(args.availability),
            "availability_sha256": sha256_file(args.availability),
            "events_path": portable_path(args.events),
            "events_sha256": sha256_file(args.events),
            "pdf_path": portable_path(args.pdf),
            "pdf_sha256": sha256_file(args.pdf),
            "pdf_pages": pdf_pages,
            "generated_at": datetime.now().astimezone().isoformat(),
        }
    )
    atomic_write_json(args.summary, summary)
    print(f"SHADOW_EVENTS {len(events)}")
    print(f"SHADOW_BUY_FILLS {summary['event_counts'].get('BUY_FILLED', 0)}")
    print(f"SHADOW_SELL_FILLS {summary['event_counts'].get('SELL_FILLED', 0)}")
    print(f"PDF {args.pdf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
