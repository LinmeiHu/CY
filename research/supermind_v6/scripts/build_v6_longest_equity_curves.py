from __future__ import annotations

# ruff: noqa: E501
import argparse
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
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
EQUITY_PATH = RESEARCH_ROOT / "output" / "v6_hybrid_longest_daily_equity.parquet"
ANNUAL_PATH = RESEARCH_ROOT / "output" / "v6_hybrid_longest_annual_equity.parquet"
SUMMARY_PATH = RESEARCH_ROOT / "manifests" / "v6_hybrid_longest_equity_summary.json"
REPORT_PATH = RESEARCH_ROOT / "reports" / "v6_hybrid_longest_annual_equity.md"
PDF_PATH = RESEARCH_ROOT / "output" / "pdf" / "v6_hybrid_longest_annual_equity_curves.pdf"
START = date(2010, 1, 1)
END = date(2026, 8, 28)
BENCHMARKS = {
    "hs300": "000300.SH",
    "csi1000": "000852.SH",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=date.fromisoformat, default=START)
    parser.add_argument("--end", type=date.fromisoformat, default=END)
    parser.add_argument("--qmt-root", type=Path, default=QMT_DATA_ROOT)
    parser.add_argument("--hybrid-root", type=Path, default=HYBRID_ROOT)
    parser.add_argument("--events", type=Path, default=EVENTS_PATH)
    parser.add_argument("--equity", type=Path, default=EQUITY_PATH)
    parser.add_argument("--annual", type=Path, default=ANNUAL_PATH)
    parser.add_argument("--summary", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--pdf", type=Path, default=PDF_PATH)
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
    for column in ["pre_adj_open", "pre_adj_close"]:
        frame.loc[invalid, column] = np.nan
    return frame


def load_open_marks(root: Path, symbols: list[str]) -> dict[tuple[date, str], float]:
    marks: dict[tuple[date, str], float] = {}
    for symbol in symbols:
        frame = pd.read_parquet(minute_path(root, symbol))
        selected = frame[
            frame["bar_role"].eq("OPEN_BAR_09_30")
            & frame["row_status"].eq("VALID")
        ]
        for row in selected.itertuples(index=False):
            value = float(row.pre_adj_close)
            if np.isfinite(value) and value > 0:
                marks[(pd.Timestamp(row.trade_date).date(), symbol)] = value
    return marks


def valid_price(value: object) -> float | None:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if np.isfinite(price) and price > 0 else None


def daily_value(frame: pd.DataFrame, timestamp: pd.Timestamp, column: str) -> float | None:
    if timestamp not in frame.index:
        return None
    return valid_price(frame.loc[timestamp, column])


def benchmark_nav(
    frame: pd.DataFrame,
    calendar: pd.DatetimeIndex,
) -> pd.Series:
    close = frame["pre_adj_close"].reindex(calendar).ffill()
    first = close.first_valid_index()
    result = pd.Series(np.nan, index=calendar, dtype="float64")
    if first is not None:
        result.loc[first:] = close.loc[first:] / float(close.loc[first])
    return result


def simulate_equity(
    *,
    start: date,
    end: date,
    daily: dict[str, pd.DataFrame],
    open_marks: dict[tuple[date, str], float],
    events: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    calendar = daily[BENCHMARKS["hs300"]].index
    calendar = calendar[(calendar.date >= start) & (calendar.date <= end)]
    event_groups = {
        key: value.copy()
        for key, value in events.groupby("trade_date", sort=False)
    }
    shares: dict[str, float] = {}
    last_mark: dict[str, float] = {}
    cash = 1.0
    rows: list[dict[str, Any]] = []
    trade_notional_total = 0.0
    negative_cash_days = 0

    for timestamp in calendar:
        trade_date = timestamp.date()
        day_events = event_groups.get(trade_date, events.iloc[0:0])

        open_prices: dict[str, float] = {}
        for symbol in set(shares) | set(day_events["symbol"].tolist()):
            price = open_marks.get((trade_date, symbol))
            if price is None:
                price = last_mark.get(symbol)
            if price is None:
                price = daily_value(daily[symbol], timestamp, "pre_adj_open")
            if price is not None:
                open_prices[symbol] = price

        nav_open = cash + sum(
            quantity * open_prices.get(symbol, last_mark.get(symbol, 0.0))
            for symbol, quantity in shares.items()
        )
        if not np.isfinite(nav_open) or nav_open <= 0:
            raise ValueError(f"nonpositive open NAV on {trade_date}: {nav_open}")

        day_notional = 0.0
        open_sells = day_events[
            day_events["stage"].eq("open")
            & day_events["event_type"].eq("SELL_FILLED")
        ]
        for event in open_sells.itertuples(index=False):
            price = valid_price(event.price_pre_adj)
            quantity = shares.pop(event.symbol, 0.0)
            if price is None or quantity <= 0:
                raise ValueError(f"invalid filled open sell on {trade_date}: {event.symbol}")
            notional = quantity * price
            cash += notional
            day_notional += abs(notional)

        targets = day_events[
            day_events["stage"].eq("open")
            & day_events["event_type"].isin(["BUY_FILLED", "REBALANCE_FILLED"])
        ]
        for event in targets.itertuples(index=False):
            price = valid_price(event.price_pre_adj)
            weight = float(event.target_weight)
            if price is None or not np.isfinite(weight) or not 0 <= weight <= 1:
                raise ValueError(f"invalid filled target on {trade_date}: {event.symbol}")
            old_quantity = shares.get(event.symbol, 0.0)
            old_value = old_quantity * price
            target_value = nav_open * weight
            cash += old_value - target_value
            shares[event.symbol] = target_value / price
            day_notional += abs(target_value - old_value)

        close_sells = day_events[
            day_events["stage"].eq("close")
            & day_events["event_type"].eq("SELL_FILLED")
        ]
        for event in close_sells.itertuples(index=False):
            price = valid_price(event.price_pre_adj)
            quantity = shares.pop(event.symbol, 0.0)
            if price is None or quantity <= 0:
                raise ValueError(f"invalid filled close sell on {trade_date}: {event.symbol}")
            notional = quantity * price
            cash += notional
            day_notional += abs(notional)

        close_values: dict[str, float] = {}
        for symbol in shares:
            price = daily_value(daily[symbol], timestamp, "pre_adj_close")
            if price is None:
                price = last_mark.get(symbol)
            if price is None:
                raise ValueError(f"missing valuation mark on {trade_date}: {symbol}")
            close_values[symbol] = price
            last_mark[symbol] = price

        holdings_value = sum(
            shares[symbol] * close_values[symbol] for symbol in shares
        )
        nav = cash + holdings_value
        if not np.isfinite(nav) or nav <= 0:
            raise ValueError(f"nonpositive close NAV on {trade_date}: {nav}")
        if cash < -1e-10:
            negative_cash_days += 1
        trade_notional_total += day_notional
        rows.append(
            {
                "trade_date": timestamp,
                "nav": nav,
                "cash": cash,
                "cash_weight": cash / nav,
                "gross_exposure": holdings_value / nav,
                "position_count": len(shares),
                "trade_notional": day_notional,
                "turnover": day_notional / nav_open,
                "buy_fills": int(day_events["event_type"].eq("BUY_FILLED").sum()),
                "rebalance_fills": int(
                    day_events["event_type"].eq("REBALANCE_FILLED").sum()
                ),
                "sell_fills": int(day_events["event_type"].eq("SELL_FILLED").sum()),
                "no_fills": int(
                    day_events["event_type"].isin(
                        ["BUY_OR_REBALANCE_NO_FILL", "SELL_NO_FILL"]
                    ).sum()
                ),
            }
        )

    equity = pd.DataFrame(rows).set_index("trade_date")
    equity["daily_return"] = equity["nav"].pct_change().fillna(0.0)
    equity["drawdown"] = equity["nav"] / equity["nav"].cummax() - 1.0
    for label, symbol in BENCHMARKS.items():
        equity[f"{label}_nav"] = benchmark_nav(daily[symbol], equity.index)
    return equity, {
        "end_positions": sorted(shares),
        "negative_cash_days": negative_cash_days,
        "minimum_cash_weight": float(equity["cash_weight"].min()),
        "maximum_gross_exposure": float(equity["gross_exposure"].max()),
        "trade_notional_total": trade_notional_total,
    }


def annual_metrics(equity: pd.DataFrame, start_year: int, end_year: int) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    previous_nav = 1.0
    benchmark_previous = {label: 1.0 for label in BENCHMARKS}
    for year in range(start_year, end_year + 1):
        frame = equity[equity.index.year == year]
        if frame.empty:
            continue
        normalized = pd.concat(
            [pd.Series([1.0]), frame["nav"].reset_index(drop=True) / previous_nav],
            ignore_index=True,
        )
        drawdown = normalized / normalized.cummax() - 1.0
        returns = frame["daily_return"]
        volatility = float(returns.std(ddof=1) * np.sqrt(244)) if len(returns) > 1 else 0.0
        sharpe = (
            float(returns.mean() / returns.std(ddof=1) * np.sqrt(244))
            if len(returns) > 1 and returns.std(ddof=1) > 0
            else None
        )
        item: dict[str, Any] = {
            "year": year,
            "sessions": len(frame),
            "start_nav": previous_nav,
            "end_nav": float(frame["nav"].iloc[-1]),
            "return": float(frame["nav"].iloc[-1] / previous_nav - 1.0),
            "max_drawdown": float(drawdown.min()),
            "annualized_volatility": volatility,
            "sharpe_zero_rf": sharpe,
            "average_gross_exposure": float(frame["gross_exposure"].mean()),
            "maximum_gross_exposure": float(frame["gross_exposure"].max()),
            "maximum_positions": int(frame["position_count"].max()),
            "turnover": float(frame["turnover"].sum()),
            "buy_fills": int(frame["buy_fills"].sum()),
            "rebalance_fills": int(frame["rebalance_fills"].sum()),
            "sell_fills": int(frame["sell_fills"].sum()),
            "no_fills": int(frame["no_fills"].sum()),
        }
        for label in BENCHMARKS:
            series = frame[f"{label}_nav"].dropna()
            if series.empty:
                item[f"{label}_return"] = None
            else:
                item[f"{label}_return"] = float(
                    series.iloc[-1] / benchmark_previous[label] - 1.0
                )
                benchmark_previous[label] = float(series.iloc[-1])
        rows.append(item)
        previous_nav = float(frame["nav"].iloc[-1])
    return pd.DataFrame(rows)


def percent(value: object) -> str:
    if value is None or pd.isna(value):
        return "NA"
    return f"{float(value):+.2%}"


def decimal(value: object) -> str:
    if value is None or pd.isna(value):
        return "NA"
    return f"{float(value):.2f}"


def annual_normalized(
    equity: pd.DataFrame,
    year: int,
    column: str,
) -> pd.Series:
    frame = equity[equity.index.year == year][column].dropna()
    if frame.empty:
        return frame
    prior = equity[equity.index < frame.index[0]][column].dropna()
    base = float(prior.iloc[-1]) if not prior.empty else float(frame.iloc[0])
    return frame / base


def render_pdf(
    path: Path,
    equity: pd.DataFrame,
    annual: pd.DataFrame,
    *,
    strategy_sha: str,
    anchor_start: date,
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    page_count = 0
    with PdfPages(path) as pdf:
        fig = plt.figure(figsize=(11, 8.5))
        grid = fig.add_gridspec(2, 1, height_ratios=[2.2, 1.0], hspace=0.25)
        ax = fig.add_subplot(grid[0])
        ax.plot(equity.index, equity["nav"], color="#1769aa", lw=1.6, label="Frozen V6 shadow NAV")
        ax.plot(equity.index, equity["hs300_nav"], color="#777777", lw=1.0, label="CSI300 buy-and-hold")
        ax.plot(equity.index, equity["csi1000_nav"], color="#d97904", lw=1.0, label="CSI1000 buy-and-hold")
        ax.axvline(pd.Timestamp(anchor_start), color="#b3261e", ls="--", lw=1.0, label="CSI1000 anchor starts")
        ax.set_title("SuperMind V6 frozen strategy | longest hybrid shadow equity", loc="left", fontsize=16, weight="bold")
        ax.set_ylabel("Continuous NAV (start = 1.0)")
        ax.grid(alpha=0.2)
        ax.legend(loc="upper left", ncol=2, fontsize=8)
        dd = fig.add_subplot(grid[1], sharex=ax)
        dd.fill_between(equity.index, equity["drawdown"], 0, color="#c92828", alpha=0.35)
        dd.set_ylabel("Drawdown")
        dd.yaxis.set_major_formatter(lambda value, _: f"{value:.0%}")
        dd.grid(alpha=0.2)
        fig.text(
            0.08,
            0.020,
            "Research-only reconstruction: recorded shadow fills, fractional target weights, zero fees/slippage,\n"
            "and daily QMT pre-adjusted close valuation. 2010-2012 remain cash because the CSI1000 anchor is unavailable.",
            fontsize=7.5,
            color="#444444",
        )
        fig.text(
            0.08,
            0.004,
            f"Frozen strategy SHA-256: {strategy_sha}",
            fontsize=6.5,
            color="#666666",
        )
        fig.text(0.95, 0.020, "Page 1", ha="right", fontsize=8, color="#555555")
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)
        page_count += 1

        annual_by_year = annual.set_index("year")
        for year in annual["year"].astype(int):
            item = annual_by_year.loc[year]
            strategy = annual_normalized(equity, year, "nav")
            hs300 = annual_normalized(equity, year, "hs300_nav")
            csi1000 = annual_normalized(equity, year, "csi1000_nav")
            annual_drawdown = strategy / pd.concat(
                [pd.Series([1.0]), strategy.reset_index(drop=True)], ignore_index=True
            ).cummax().iloc[1:].to_numpy() - 1.0

            fig = plt.figure(figsize=(11, 8.5))
            grid = fig.add_gridspec(2, 1, height_ratios=[2.4, 1.0], hspace=0.22)
            ax = fig.add_subplot(grid[0])
            ax.plot(strategy.index, strategy, color="#1769aa", lw=2.0, label="Frozen V6 shadow")
            ax.plot(hs300.index, hs300, color="#777777", lw=1.1, label="CSI300")
            if not csi1000.empty:
                ax.plot(csi1000.index, csi1000, color="#d97904", lw=1.1, label="CSI1000")
            ax.axhline(1.0, color="#222222", lw=0.7, alpha=0.6)
            ax.set_title(f"Frozen V6 hybrid shadow equity - {year}", loc="left", fontsize=16, weight="bold")
            ax.set_ylabel("Annual normalized NAV")
            ax.grid(alpha=0.2)
            ax.legend(loc="upper left", ncol=3, fontsize=9)
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
            ax.tick_params(axis="x", rotation=30)
            stats = (
                f"V6 return {percent(item['return'])}   |   max DD {percent(item['max_drawdown'])}   |   "
                f"vol {percent(item['annualized_volatility'])}   |   Sharpe {decimal(item['sharpe_zero_rf'])}\n"
                f"CSI300 {percent(item['hs300_return'])}   |   CSI1000 {percent(item['csi1000_return'])}   |   "
                f"avg exposure {item['average_gross_exposure']:.1%}   |   max positions {int(item['maximum_positions'])}\n"
                f"buy {int(item['buy_fills'])}   rebalance {int(item['rebalance_fills'])}   "
                f"sell {int(item['sell_fills'])}   no-fill {int(item['no_fills'])}   turnover {item['turnover']:.2f}x"
            )
            ax.text(
                0.01,
                0.02,
                stats,
                transform=ax.transAxes,
                fontsize=8.5,
                va="bottom",
                bbox={"facecolor": "white", "edgecolor": "#cccccc", "alpha": 0.9},
            )

            dd = fig.add_subplot(grid[1], sharex=ax)
            dd.fill_between(annual_drawdown.index, annual_drawdown, 0, color="#c92828", alpha=0.38)
            dd.set_ylabel("Within-year drawdown")
            dd.yaxis.set_major_formatter(lambda value, _: f"{value:.0%}")
            dd.grid(alpha=0.2)
            if year < anchor_start.year:
                dd.text(
                    0.5,
                    0.45,
                    "FAIL-CLOSED CASH: CSI1000 entry anchor history unavailable",
                    transform=dd.transAxes,
                    ha="center",
                    va="center",
                    fontsize=10,
                    color="#b3261e",
                    weight="bold",
                )
            fig.text(
                0.08,
                0.020,
                "Shadow accounting: fractional target weights at recorded fill prices; zero fees/slippage;\n"
                "failed orders leave holdings unchanged. This is not a native SuperMind account curve.",
                fontsize=7.5,
                color="#444444",
            )
            page_count += 1
            fig.text(0.95, 0.020, f"Page {page_count}", ha="right", fontsize=8, color="#555555")
            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)
    return page_count


def write_report(path: Path, annual: pd.DataFrame, summary: dict[str, Any]) -> None:
    lines = [
        "# SuperMind V6 longest hybrid shadow equity",
        "",
        f"Window: {summary['window_start']}..{summary['window_end']}",
        "",
        "| Year | V6 return | Max DD | Volatility | Sharpe | CSI300 | CSI1000 | Avg exposure | Buy | Rebalance | Sell | No-fill |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row in annual.iterrows():
        sharpe = decimal(row["sharpe_zero_rf"])
        lines.append(
            f"| {int(row['year'])} | {percent(row['return'])} | {percent(row['max_drawdown'])} | "
            f"{percent(row['annualized_volatility'])} | {sharpe} | {percent(row['hs300_return'])} | "
            f"{percent(row['csi1000_return'])} | {row['average_gross_exposure']:.1%} | "
            f"{int(row['buy_fills'])} | {int(row['rebalance_fills'])} | "
            f"{int(row['sell_fills'])} | {int(row['no_fills'])} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- 2010-2012 are cash-only because the frozen strategy requires CSI1000 entry-anchor history, which starts on 2013-04-01 in the registered QMT daily data.",
            "- This reconstruction applies recorded shadow fills using fractional target weights and zero fees/slippage.",
            "- Failed orders leave holdings unchanged. Cash constraints and native SuperMind order semantics remain unverified.",
            "- Daily valuation uses QMT pre-adjusted closes; QMT-front versus SuperMind-fq=pre equivalence remains unverified.",
            "- The frozen 152-ETF pool creates survivor bias in early years.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    pool = [canonical_symbol(symbol) for symbol in parse_strategy_pool()]
    symbols = [*pool, *BENCHMARKS.values()]
    symbols = list(dict.fromkeys(symbols))
    daily = {symbol: load_daily(args.qmt_root, symbol) for symbol in symbols}
    open_marks = load_open_marks(args.hybrid_root, pool)
    events = pd.read_parquet(args.events)
    events["trade_date"] = pd.to_datetime(events["trade_date"]).dt.date
    events = events[events["trade_date"].between(args.start, args.end)].copy()
    equity, simulation_meta = simulate_equity(
        start=args.start,
        end=args.end,
        daily=daily,
        open_marks=open_marks,
        events=events,
    )
    annual = annual_metrics(equity, args.start.year, args.end.year)
    anchor_start = daily[BENCHMARKS["csi1000"]]["pre_adj_close"].first_valid_index().date()

    if simulation_meta["end_positions"]:
        raise ValueError(f"unexpected end positions: {simulation_meta['end_positions']}")
    atomic_write_parquet(equity.reset_index(), args.equity)
    atomic_write_parquet(annual, args.annual)
    pages = render_pdf(
        args.pdf,
        equity,
        annual,
        strategy_sha=strategy_sha256(),
        anchor_start=anchor_start,
    )
    summary = {
        "equity_version": "v6-hybrid-longest-equity-1",
        "status": "EXPLORATORY_HYBRID_SHADOW_ACCOUNTING",
        "generated_at": datetime.now().astimezone().isoformat(),
        "window_start": args.start.isoformat(),
        "window_end": args.end.isoformat(),
        "strategy_source_sha256": strategy_sha256(),
        "csi1000_anchor_start": anchor_start.isoformat(),
        "events_path": str(args.events),
        "events_sha256": sha256_file(args.events),
        "equity_path": str(args.equity),
        "equity_sha256": sha256_file(args.equity),
        "annual_path": str(args.annual),
        "annual_sha256": sha256_file(args.annual),
        "pdf_path": str(args.pdf),
        "pdf_pages": pages,
        "pdf_sha256": sha256_file(args.pdf),
        "simulation": simulation_meta,
        "annual": {
            str(int(row["year"])): {
                key: (None if pd.isna(value) else value.item() if hasattr(value, "item") else value)
                for key, value in row.items()
                if key != "year"
            }
            for row in annual.to_dict(orient="records")
        },
        "assumptions": [
            "recorded shadow fill prices and target weights are applied with fractional shares",
            "zero fees and zero slippage",
            "failed orders leave holdings unchanged",
            "daily valuation uses QMT pre-adjusted close; a missing held-symbol close carries the last valid valuation mark only",
            "2010-2012 are cash-only because required CSI1000 entry-anchor history is unavailable",
            "cash constraints and native SuperMind order semantics remain unverified",
        ],
    }
    atomic_write_json(args.summary, summary)
    write_report(args.report, annual, summary)
    print(f"EQUITY {args.equity}")
    print(f"ANNUAL {args.annual}")
    print(f"PDF {pages} {args.pdf}")
    print(f"SUMMARY {args.summary}")
    print(f"REPORT {args.report}")
    print(json.dumps(simulation_meta, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
