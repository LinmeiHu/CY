from __future__ import annotations

# ruff: noqa: E501
import argparse
import json
import textwrap
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from run_v6_shadow_chartbook import (
    ShadowPlatform,
    candle,
    chart_events,
    frozen_namespace,
    record_pending_signals,
)
from v6_data_common import (
    MANIFEST_DIR,
    QMT_DATA_ROOT,
    RESEARCH_ROOT,
    atomic_write_json,
    atomic_write_parquet,
    canonical_symbol,
    parse_strategy_pool,
    sha256_file,
    strategy_sha256,
)

HYBRID_ROOT = RESEARCH_ROOT / "data" / "market_data_hybrid_etf_v1"
HYBRID_BUILD_SUMMARY = MANIFEST_DIR / "v6_hybrid_critical_history_summary.json"
EVENTS_PATH = RESEARCH_ROOT / "output" / "v6_hybrid_annual_replay_events.parquet"
METRICS_PATH = RESEARCH_ROOT / "output" / "v6_hybrid_annual_trade_metrics.parquet"
SUMMARY_PATH = MANIFEST_DIR / "v6_hybrid_annual_replay_summary.json"
REPORT_PATH = RESEARCH_ROOT / "reports" / "v6_hybrid_annual_signal_quality.md"
PDF_ROOT = RESEARCH_ROOT / "output" / "pdf"
START = date(2020, 1, 1)
END = date(2026, 8, 28)


class FastShadowPlatform(ShadowPlatform):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.history_frames = {
            symbol: pd.DataFrame(
                {
                    "close": frame["pre_adj_close"],
                    "volume": frame["volume_raw"],
                    "turnover": frame["amount_cny"],
                },
                index=frame.index,
            )
            for symbol, frame in self.daily.items()
        }

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
        cutoff = pd.Timestamp(self.current_date)
        result = {}
        for symbol in symbols:
            frame = self.history_frames.get(symbol)
            if frame is None:
                continue
            end = int(frame.index.searchsorted(cutoff, side="left"))
            if end == 0:
                continue
            result[symbol] = frame.iloc[max(0, end - count) : end][fields]
        return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=date.fromisoformat, default=START)
    parser.add_argument("--end", type=date.fromisoformat, default=END)
    parser.add_argument("--hybrid-root", type=Path, default=HYBRID_ROOT)
    parser.add_argument("--qmt-root", type=Path, default=QMT_DATA_ROOT)
    parser.add_argument("--hybrid-summary", type=Path, default=HYBRID_BUILD_SUMMARY)
    parser.add_argument("--events", type=Path, default=EVENTS_PATH)
    parser.add_argument("--metrics", type=Path, default=METRICS_PATH)
    parser.add_argument("--summary", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--pdf-root", type=Path, default=PDF_ROOT)
    parser.add_argument("--skip-pdf", action="store_true")
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
    columns = [
        "pre_adj_open",
        "pre_adj_high",
        "pre_adj_low",
        "pre_adj_close",
        "volume_raw",
        "amount_cny",
    ]
    frame.loc[invalid, columns] = np.nan
    return frame


def load_minute(root: Path, symbol: str) -> pd.DataFrame:
    frame = pd.read_parquet(minute_path(root, symbol))
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    return frame


def run_replay(
    args: argparse.Namespace,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, dict[str, Any]]:
    pool_symbols = [canonical_symbol(code) for code in parse_strategy_pool()]
    all_symbols = [*pool_symbols, "000852.SH"]
    daily = {symbol: load_daily(args.qmt_root, symbol) for symbol in all_symbols}
    minute = {symbol: load_minute(args.hybrid_root, symbol) for symbol in all_symbols}
    availability = pd.read_parquet(
        args.hybrid_root / "execution_availability" / "critical_execution.parquet"
    )
    availability["trade_date"] = pd.to_datetime(availability["trade_date"]).dt.date
    availability = availability[availability["trade_date"].between(args.start, args.end)]
    calendar = [
        timestamp
        for timestamp in daily["000852.SH"].index
        if args.start <= timestamp.date() <= args.end
        and np.isfinite(daily["000852.SH"].loc[timestamp, "pre_adj_close"])
    ]
    platform = FastShadowPlatform(daily, minute, availability, calendar)
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
        namespace["execute_pending_open"](context, platform.bar_dict(), "HYBRID_HISTORY_09_30")
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
        raise ValueError("hybrid replay produced no events")
    events["trade_date"] = pd.to_datetime(events["trade_date"]).dt.date
    events = events.sort_values(["trade_date", "symbol", "event_type"]).reset_index(drop=True)
    run_meta = {
        "calendar_sessions": len(calendar),
        "open_positions_end": sorted(platform.positions),
        "event_counts": {
            str(key): int(value) for key, value in events["event_type"].value_counts().items()
        },
    }
    return daily, events, run_meta


def forward_metrics(frame: pd.DataFrame, trade_date: date, entry_price: float) -> dict[str, float]:
    timestamp = pd.Timestamp(trade_date)
    if timestamp not in frame.index or not np.isfinite(entry_price) or entry_price <= 0:
        return {}
    location = frame.index.get_loc(timestamp)
    if not isinstance(location, (int, np.integer)):
        return {}
    result: dict[str, float] = {}
    for horizon in (5, 10, 20, 60):
        target = int(location) + horizon
        if target < len(frame):
            close = float(frame.iloc[target]["pre_adj_close"])
            if np.isfinite(close):
                result[f"fwd_{horizon}d"] = close / entry_price - 1.0
    window = frame.iloc[int(location) + 1 : int(location) + 21]
    if not window.empty:
        high = float(window["pre_adj_high"].max())
        low = float(window["pre_adj_low"].min())
        if np.isfinite(high):
            result["mfe_20d"] = high / entry_price - 1.0
        if np.isfinite(low):
            result["mae_20d"] = low / entry_price - 1.0
    return result


def trade_metrics(events: pd.DataFrame, daily: dict[str, pd.DataFrame]) -> pd.DataFrame:
    exits = events[events["event_type"].eq("SELL_FILLED")].copy()
    exit_lookup = {
        (row.symbol, row.entry_date): row
        for row in exits.itertuples(index=False)
    }
    rows = []
    for buy in events[events["event_type"].eq("BUY_FILLED")].itertuples(index=False):
        item: dict[str, Any] = {
            "symbol": buy.symbol,
            "entry_date": buy.trade_date,
            "entry_year": buy.trade_date.year,
            "entry_price": float(buy.price_pre_adj),
        }
        item.update(forward_metrics(daily[buy.symbol], buy.trade_date, float(buy.price_pre_adj)))
        exit_row = exit_lookup.get((buy.symbol, buy.trade_date))
        if exit_row is not None:
            item.update(
                {
                    "exit_date": exit_row.trade_date,
                    "exit_price": float(exit_row.price_pre_adj),
                    "holding_pnl_pct": float(exit_row.holding_pnl_pct),
                }
            )
        rows.append(item)
    return pd.DataFrame(rows).sort_values(["entry_date", "symbol"]).reset_index(drop=True)


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
        "p10": float(clean.quantile(0.10)),
        "p90": float(clean.quantile(0.90)),
    }


def annual_summaries(
    events: pd.DataFrame,
    metrics: pd.DataFrame,
    start_year: int,
    end_year: int,
) -> dict[str, Any]:
    annual: dict[str, Any] = {}
    event_years = pd.to_datetime(events["trade_date"]).dt.year
    for year in range(start_year, end_year + 1):
        year_events = events[event_years.eq(year)]
        year_metrics = metrics[metrics["entry_year"].eq(year)]
        annual[str(year)] = {
            "event_counts": {
                str(key): int(value)
                for key, value in year_events["event_type"].value_counts().items()
            },
            "unique_bought_symbols": int(
                year_events.loc[year_events["event_type"].eq("BUY_FILLED"), "symbol"].nunique()
            ),
            "entry_trades": len(year_metrics),
            "completed_entry_trades": int(year_metrics["holding_pnl_pct"].notna().sum()),
            "unclosed_entry_trades": int(year_metrics["holding_pnl_pct"].isna().sum()),
            "roundtrip_holding_pnl": distribution(year_metrics["holding_pnl_pct"]),
            "forward_quality": {
                column: distribution(year_metrics[column])
                for column in ["fwd_5d", "fwd_10d", "fwd_20d", "fwd_60d", "mfe_20d", "mae_20d"]
            },
        }
    return annual


def metric_text(metric: dict[str, Any]) -> str:
    if metric["n"] == 0:
        return "n=0"
    return (
        f"n={metric['n']}, mean={metric['mean']:.2%}, median={metric['median']:.2%}, "
        f"win={metric['win_rate']:.1%}, p10={metric['p10']:.2%}, p90={metric['p90']:.2%}"
    )


def format_percent(value: float | None) -> str:
    return "NA" if value is None else f"{value:.2%}"


def draw_cover(
    pdf: PdfPages,
    *,
    year: int,
    annual: dict[str, Any],
    strategy_sha: str,
) -> None:
    fig = plt.figure(figsize=(11.69, 8.27))
    fig.patch.set_facecolor("white")
    fig.text(0.06, 0.91, f"SuperMind V6 frozen strategy - {year} annual chartbook", fontsize=20, weight="bold")
    fig.text(0.06, 0.86, "Continuous 2020-2026 hybrid shadow replay; 152 frozen-pool ETF candle pages", fontsize=10.5)
    lines = [
        f"Entry trades: {annual['entry_trades']} | Completed: {annual['completed_entry_trades']} | Unclosed: {annual['unclosed_entry_trades']}",
        f"Unique bought ETFs: {annual['unique_bought_symbols']}",
        f"Completed holding P&L: {metric_text(annual['roundtrip_holding_pnl'])}",
        f"Forward 5 sessions: {metric_text(annual['forward_quality']['fwd_5d'])}",
        f"Forward 10 sessions: {metric_text(annual['forward_quality']['fwd_10d'])}",
        f"Forward 20 sessions: {metric_text(annual['forward_quality']['fwd_20d'])}",
        f"Forward 60 sessions: {metric_text(annual['forward_quality']['fwd_60d'])}",
        f"20-session MFE: {metric_text(annual['forward_quality']['mfe_20d'])}",
        f"20-session MAE: {metric_text(annual['forward_quality']['mae_20d'])}",
    ]
    y = 0.76
    for line in lines:
        fig.text(0.08, y, line, fontsize=10.5)
        y -= 0.047
    caveat = (
        "Data priority: QMT exact 1m overrides local ETF ZIP exact 1m by symbol/date/role. Local raw prices\n"
        "are converted with the QMT daily front-adjustment factor. Missing or zero-volume critical bars fail\n"
        "closed. Exact SuperMind matching, QMT-front vs SuperMind-pre equivalence, opening-auction semantics,\n"
        "fees, slippage, partial fills, and cash constraints remain unverified/not simulated."
    )
    fig.text(0.08, 0.25, caveat, fontsize=9, color="#4a4a4a", linespacing=1.45)
    fig.text(0.08, 0.11, f"Frozen strategy SHA-256: {strategy_sha}", fontsize=7.6, color="#666666")
    fig.text(0.94, 0.04, "Page 1", fontsize=8, ha="right", color="#666666")
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def draw_symbol_page(
    pdf: PdfPages,
    *,
    symbol: str,
    frame: pd.DataFrame,
    events: pd.DataFrame,
    page: int,
) -> pd.DataFrame:
    fig, ax = plt.subplots(figsize=(11.69, 8.27))
    fig.subplots_adjust(left=0.07, right=0.97, top=0.88, bottom=0.12)
    candle(ax, frame)
    symbol_events = events[events["symbol"].eq(symbol)]
    plotted = chart_events(symbol_events)
    styles = {
        "BUY_FILLED": ("^", "#147d46", "Buy filled"),
        "SELL_FILLED": ("v", "#c92828", "Sell filled"),
        "BUY_OR_REBALANCE_NO_FILL": ("x", "#d98a00", "Open no-fill"),
        "SELL_NO_FILL": ("x", "#7b2cbf", "Sell no-fill"),
        "TAIL_SELL_SIGNAL": ("D", "#3e5fa8", "14:57 sell signal"),
    }
    for event_type, (marker, color, label) in styles.items():
        selected = plotted[plotted["event_type"].eq(event_type)]
        if selected.empty:
            continue
        ax.scatter(
            pd.to_datetime(selected["trade_date"]),
            selected["price_pre_adj"].astype(float),
            marker=marker,
            s=52,
            c=color,
            edgecolors="white" if marker != "x" else color,
            linewidths=0.45,
            label=label,
            zorder=5,
        )
        for ordinal, row in enumerate(selected.itertuples(index=False)):
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
    if not plotted.empty:
        ax.legend(loc="upper left", fontsize=6.5, ncol=3, frameon=False)
    year = int(pd.Timestamp(frame.index.min()).year) if not frame.empty else "no listed data"
    ax.set_title(
        f"{symbol} | {year} QMT pre-adjusted daily candles | frozen V6 hybrid events",
        loc="left",
        fontsize=12,
        weight="bold",
    )
    ax.set_ylabel("Price (QMT pre-adjusted)")
    ax.tick_params(axis="x", labelsize=8)
    summary = (
        f"buy={int((symbol_events.event_type == 'BUY_FILLED').sum())}  "
        f"sell={int((symbol_events.event_type == 'SELL_FILLED').sum())}  "
        f"open_no_fill={int((symbol_events.event_type == 'BUY_OR_REBALANCE_NO_FILL').sum())}  "
        f"sell_no_fill={int((symbol_events.event_type == 'SELL_NO_FILL').sum())}  "
        f"tail_signals={int((symbol_events.event_type == 'TAIL_SELL_SIGNAL').sum())}"
    )
    fig.text(0.07, 0.055, summary, fontsize=7.5, color="#555555")
    fig.text(0.97, 0.035, f"Page {page}", fontsize=8, ha="right", color="#666666")
    pdf.savefig(fig)
    plt.close(fig)
    return plotted


def display_text(value: object) -> str:
    if value is None or pd.isna(value):
        return "-"
    if isinstance(value, (float, np.floating)):
        return f"{value:.4f}"
    return str(value)


def wrapped_reason(value: object) -> str:
    text = display_text(value)
    return text if text == "-" else textwrap.fill(text, width=24, break_long_words=True)


def draw_event_ledger_pages(
    pdf: PdfPages,
    symbol: str,
    events: pd.DataFrame,
    page: int,
) -> int:
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
    ledger["entry_date_display"] = ledger.get(
        "entry_date", pd.Series(index=ledger.index, dtype=object)
    ).map(display_text)
    ledger["entry_price_display"] = ledger.get(
        "entry_price", pd.Series(index=ledger.index, dtype=float)
    ).map(display_text)
    ledger["pnl"] = ledger.get(
        "holding_pnl_pct", pd.Series(index=ledger.index, dtype=float)
    ).map(lambda value: "-" if pd.isna(value) else f"{float(value):+.2%}")
    ledger["reason_display"] = ledger.get(
        "reason", pd.Series(index=ledger.index, dtype=object)
    ).map(wrapped_reason)
    for start in range(0, len(ledger), 10):
        part = ledger.iloc[start : start + 10]
        fig, ax = plt.subplots(figsize=(11.69, 8.27))
        ax.axis("off")
        ax.set_title(
            f"{symbol} | frozen V6 hybrid event ledger",
            loc="left",
            fontsize=15,
            weight="bold",
            pad=20,
        )
        headers = [
            "ID",
            "Event",
            "Date",
            "Strategy time",
            "Reference px",
            "Entry date",
            "Entry px",
            "Holding P&L",
            "Reason",
        ]
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
            colWidths=[0.05, 0.12, 0.10, 0.14, 0.085, 0.10, 0.075, 0.09, 0.24],
        )
        table.auto_set_font_size(False)
        table.set_fontsize(6.7)
        table.scale(1, 2.05)
        for (row_index, _), cell in table.get_celld().items():
            cell.set_edgecolor("#d0d0d0")
            if row_index == 0:
                cell.set_facecolor("#eaf0f7")
                cell.set_text_props(weight="bold")
            elif row_index % 2 == 0:
                cell.set_facecolor("#fafafa")
        fig.text(
            0.07,
            0.115,
            "Reference px uses the pre-adjusted basis. For fills it is the shadow execution price; for no-fill rows it is a daily marker/reference only, not an execution.",
            fontsize=7.8,
            color="#4a4a4a",
        )
        fig.text(
            0.07,
            0.082,
            "Holding P&L = exit price / initial buy-fill price - 1; excludes fees, slippage, sizing, and rebalance effects. Research-only; not an exact SuperMind backtest.",
            fontsize=7.8,
            color="#4a4a4a",
        )
        fig.text(0.97, 0.035, f"Page {page}", fontsize=8, ha="right", color="#666666")
        pdf.savefig(fig)
        plt.close(fig)
        page += 1
    return page


def render_year_pdf(
    *,
    path: Path,
    year: int,
    daily: dict[str, pd.DataFrame],
    events: pd.DataFrame,
    annual: dict[str, Any],
    strategy_sha: str,
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    pool_symbols = [canonical_symbol(code) for code in parse_strategy_pool()]
    year_events = events[pd.Series(events["trade_date"]).map(lambda value: value.year == year)]
    with PdfPages(path) as pdf:
        draw_cover(pdf, year=year, annual=annual, strategy_sha=strategy_sha)
        page = 2
        for symbol in pool_symbols:
            frame = daily[symbol]
            frame = frame[frame.index.year == year]
            symbol_events = year_events[year_events["symbol"].eq(symbol)]
            draw_symbol_page(
                pdf,
                symbol=symbol,
                frame=frame,
                events=symbol_events,
                page=page,
            )
            page += 1
            page = draw_event_ledger_pages(pdf, symbol, symbol_events, page)
    return page - 1


def write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# SuperMind V6 frozen ETF strategy - annual hybrid signal quality",
        "",
        f"Continuous replay: {summary['window_start']}..{summary['window_end']}",
        "",
        "| Year | Entry trades | Completed | Mean P&L | Median P&L | Win rate | 5d mean | 20d mean | 60d mean |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for year, item in summary["annual"].items():
        pnl = item["roundtrip_holding_pnl"]
        quality = item["forward_quality"]
        lines.append(
            f"| {year} | {item['entry_trades']} | {item['completed_entry_trades']} | "
            f"{format_percent(pnl['mean'])} | {format_percent(pnl['median'])} | "
            f"{format_percent(pnl['win_rate'])} | {format_percent(quality['fwd_5d']['mean'])} | "
            f"{format_percent(quality['fwd_20d']['mean'])} | "
            f"{format_percent(quality['fwd_60d']['mean'])} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            *[f"- {item}" for item in summary["limitations"]],
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    daily, events, run_meta = run_replay(args)
    metrics = trade_metrics(events, daily)
    annual = annual_summaries(events, metrics, args.start.year, args.end.year)
    atomic_write_parquet(events, args.events)
    atomic_write_parquet(metrics, args.metrics)
    hybrid_build = json.loads(args.hybrid_summary.read_text(encoding="utf-8"))
    summary: dict[str, Any] = {
        "replay_version": "v6-hybrid-annual-replay-1",
        "status": "EXPLORATORY_HYBRID_SHADOW",
        "generated_at": datetime.now().astimezone().isoformat(),
        "window_start": args.start.isoformat(),
        "window_end": args.end.isoformat(),
        "strategy_source_sha256": strategy_sha256(),
        "frozen_pool_count": len(parse_strategy_pool()),
        "continuous_replay": True,
        "calendar_sessions": run_meta["calendar_sessions"],
        "event_counts": run_meta["event_counts"],
        "open_positions_end": run_meta["open_positions_end"],
        "events_path": str(args.events),
        "events_sha256": sha256_file(args.events),
        "metrics_path": str(args.metrics),
        "metrics_sha256": sha256_file(args.metrics),
        "hybrid_build_summary_path": str(args.hybrid_summary),
        "hybrid_build_summary_sha256": sha256_file(args.hybrid_summary),
        "hybrid_source_counts": hybrid_build["totals"]["source_counts"],
        "annual": annual,
        "pdfs": {},
        "limitations": [
            "frozen V6 functions and 152-ETF pool are unchanged, but this is a local shadow replay rather than a native SuperMind backtest",
            "QMT exact 1m overrides local exact 1m; local raw prices use QMT daily front-adjustment factors",
            "QMT front adjustment is not proven equivalent to SuperMind fq=pre",
            "opening-auction and set_execution(close) matching semantics remain unverified",
            "fees, slippage, cash, partial fills, and exact order return semantics are simplified/not simulated",
            "missing or nonpositive-volume critical bars fail closed",
            "000852.SH 14:57 intraday history before 2025-08-27 is unavailable; this entry anchor snapshot fails closed, while the 510300 exit anchor remains exact-1m",
        ],
    }
    if not args.skip_pdf:
        for year in range(args.start.year, args.end.year + 1):
            pdf_path = args.pdf_root / f"v6_original_strategy_candles_{year}.pdf"
            pages = render_year_pdf(
                path=pdf_path,
                year=year,
                daily=daily,
                events=events,
                annual=annual[str(year)],
                strategy_sha=summary["strategy_source_sha256"],
            )
            summary["pdfs"][str(year)] = {
                "path": str(pdf_path),
                "pages": pages,
                "sha256": sha256_file(pdf_path),
            }
            print(f"PDF {year} {pages} {pdf_path}", flush=True)
    atomic_write_json(args.summary, summary)
    write_report(args.report, summary)
    print(f"EVENTS {len(events)}")
    print(f"TRADES {len(metrics)}")
    print(f"SUMMARY {args.summary}")
    print(f"REPORT {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
