from __future__ import annotations

# ruff: noqa: E501
import argparse
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
from run_v6_hybrid_annual_replay import FastShadowPlatform, load_daily, load_minute
from run_v6_shadow_chartbook import frozen_namespace
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

HYBRID_ROOT = RESEARCH_ROOT / "data" / "market_data_hybrid_etf_longest_v1"
TRADES_PATH = RESEARCH_ROOT / "output" / "v6_unlimited_independent_trades.parquet"
EVENTS_PATH = RESEARCH_ROOT / "output" / "v6_unlimited_independent_trade_events.parquet"
SUMMARY_PATH = MANIFEST_DIR / "v6_unlimited_independent_trade_summary.json"
REPORT_PATH = RESEARCH_ROOT / "reports" / "v6_unlimited_independent_trade_quality.md"
START = date(2010, 1, 1)
END = date(2026, 8, 28)


@dataclass
class IndependentTrade:
    trade_id: int
    symbol: str
    entry_signal_date: date
    entry_date: date
    entry_price: float
    entry_reason: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=date.fromisoformat, default=START)
    parser.add_argument("--end", type=date.fromisoformat, default=END)
    parser.add_argument("--qmt-root", type=Path, default=QMT_DATA_ROOT)
    parser.add_argument("--hybrid-root", type=Path, default=HYBRID_ROOT)
    parser.add_argument("--trades", type=Path, default=TRADES_PATH)
    parser.add_argument("--events", type=Path, default=EVENTS_PATH)
    parser.add_argument("--summary", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    return parser.parse_args()


def exact_price(
    platform: FastShadowPlatform,
    symbol: str,
    role: str,
    field: str,
) -> float | None:
    price = platform._minute_price(symbol, role, field)
    return float(price) if np.isfinite(price) and price > 0 else None


def executable(
    platform: FastShadowPlatform,
    symbol: str,
    column: str,
) -> bool:
    row = platform._current_row(symbol)
    return bool(row is not None and row[column])


def distribution(values: pd.Series) -> dict[str, int | float | None]:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "win_rate": None,
            "p10": None,
            "p25": None,
            "p75": None,
            "p90": None,
            "minimum": None,
            "maximum": None,
        }
    return {
        "n": len(clean),
        "mean": float(clean.mean()),
        "median": float(clean.median()),
        "win_rate": float(clean.gt(0).mean()),
        "p10": float(clean.quantile(0.10)),
        "p25": float(clean.quantile(0.25)),
        "p75": float(clean.quantile(0.75)),
        "p90": float(clean.quantile(0.90)),
        "minimum": float(clean.min()),
        "maximum": float(clean.max()),
    }


def scan_unlimited_candidates(
    namespace: dict[str, Any],
    context: SimpleNamespace,
    open_symbols: set[str],
) -> tuple[list[str], dict[str, Any]]:
    active = namespace["get_active_pool"](context)
    history_map = namespace["load_pool_history"](context, active)
    eligible = [
        symbol
        for symbol in active
        if symbol in history_map and namespace["is_eligible"](context, history_map[symbol])
    ]
    rs = namespace["build_rs_table"](history_map, eligible)
    if rs.empty:
        return [], {
            "active": len(active),
            "eligible": len(eligible),
            "price_signals": 0,
            "minvol_pass": 0,
        }
    score_map = {
        row.code: (float(row.score), float(row.mom60))
        for row in rs.itertuples(index=False)
    }
    candidates: list[tuple[str, float, float]] = []
    price_signals = 0
    minvol_passed = 0
    for symbol in eligible:
        if symbol in open_symbols or symbol not in score_map:
            continue
        close = namespace["clean_close"](history_map[symbol])
        if not namespace["entry_signal"](context, close):
            continue
        price_signals += 1
        passed, _ = namespace["minvol_location_signal"](context, history_map[symbol])
        if not passed:
            continue
        minvol_passed += 1
        score, mom60 = score_map[symbol]
        candidates.append((symbol, score, mom60))
    candidates.sort(key=lambda item: (-item[1], -item[2], item[0]))
    return [item[0] for item in candidates], {
        "active": len(active),
        "eligible": len(eligible),
        "price_signals": price_signals,
        "minvol_pass": minvol_passed,
    }


def own_exit_at_open(
    namespace: dict[str, Any],
    context: SimpleNamespace,
    symbols: list[str],
) -> set[str]:
    if not symbols:
        return set()
    history_map = namespace["load_pool_history"](context, symbols)
    return {
        symbol
        for symbol in symbols
        if symbol in history_map
        and namespace["own_exit_signal"](
            context,
            namespace["clean_close"](history_map[symbol]),
        )
    }


def own_exit_at_1457(
    namespace: dict[str, Any],
    context: SimpleNamespace,
    platform: FastShadowPlatform,
    symbols: list[str],
    bar_dict: dict[str, Any],
) -> set[str]:
    if not symbols:
        return set()
    history_map = namespace["load_history_recursive"](
        symbols,
        ["close"],
        max(65, int(context.exit_ma) + 5),
    )
    exits: set[str] = set()
    for symbol in symbols:
        if symbol not in history_map:
            continue
        completed = namespace["completed_daily_data"](
            history_map[symbol],
            pd.Timestamp(platform.current_date),
        )
        close = namespace["clean_close"](completed)
        snapshot = namespace["snapshot_price_1457"](bar_dict, symbol)
        combined = namespace["append_snapshot"](close, snapshot)
        if namespace["own_exit_signal"](context, combined):
            exits.add(symbol)
    return exits


def run_replay(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    pool = [canonical_symbol(symbol) for symbol in parse_strategy_pool()]
    all_symbols = [*pool, "000852.SH"]
    daily = {symbol: load_daily(args.qmt_root, symbol) for symbol in all_symbols}
    minute = {symbol: load_minute(args.hybrid_root, symbol) for symbol in all_symbols}
    availability = pd.read_parquet(
        args.hybrid_root / "execution_availability" / "critical_execution.parquet"
    )
    availability["trade_date"] = pd.to_datetime(availability["trade_date"]).dt.date
    availability = availability[availability["trade_date"].between(args.start, args.end)]
    hs300_index = load_daily(args.qmt_root, "000300.SH")
    calendar = [
        timestamp
        for timestamp in hs300_index.index
        if args.start <= timestamp.date() <= args.end
        and np.isfinite(hs300_index.loc[timestamp, "pre_adj_close"])
    ]
    platform = FastShadowPlatform(daily, minute, availability, calendar)
    namespace = frozen_namespace(platform)
    context = SimpleNamespace()
    context.portfolio = SimpleNamespace(stock_account=SimpleNamespace(positions={}))
    namespace["init"](context)

    open_trades: dict[str, IndependentTrade] = {}
    completed: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    retry_open: set[str] = set()
    next_trade_id = 1
    calendar_location = {timestamp.date(): index for index, timestamp in enumerate(calendar)}
    total_candidates = 0
    entry_no_fills = 0
    exit_no_fills = 0

    def record(event_type: str, symbol: str, **extra: object) -> None:
        events.append(
            {
                "trade_date": platform.current_date,
                "symbol": symbol,
                "event_type": event_type,
                **extra,
            }
        )

    def close_trade(symbol: str, price: float, stage: str, reason: str) -> None:
        trade = open_trades.pop(symbol)
        holding_sessions = (
            calendar_location[platform.current_date]
            - calendar_location[trade.entry_date]
        )
        completed.append(
            {
                **asdict(trade),
                "exit_signal_date": platform.current_date,
                "exit_date": platform.current_date,
                "exit_price": price,
                "exit_stage": stage,
                "exit_reason": reason,
                "holding_sessions": holding_sessions,
                "return_pct": price / trade.entry_price - 1.0,
            }
        )
        retry_open.discard(symbol)
        record(
            "SELL_FILLED",
            symbol,
            trade_id=trade.trade_id,
            price_pre_adj=price,
            stage=stage,
            reason=reason,
        )

    for timestamp in calendar:
        platform.current_date = timestamp.date()
        platform.event_stage = "before_trading"
        pre_open_symbols = set(open_trades)
        market = namespace["market_state"](context, timestamp)
        signal_date = market.get("signal_date")
        signal_date_value = (
            pd.Timestamp(signal_date).date()
            if signal_date is not None
            else platform.current_date
        )
        context.prev_trade_date = pd.Timestamp(timestamp).normalize()

        open_exit_reasons: dict[str, str] = {}
        if market["system_exit"]:
            for symbol in open_trades:
                open_exit_reasons[symbol] = "MARKET_EXIT_AT_NEXT_OPEN"
        else:
            for symbol in own_exit_at_open(
                namespace,
                context,
                list(open_trades),
            ):
                open_exit_reasons[symbol] = "OWN_EXIT_MA40_C2_AT_NEXT_OPEN"
        for symbol in retry_open:
            if symbol in open_trades:
                open_exit_reasons.setdefault(symbol, "RETRY_PRIOR_EXIT_AT_OPEN")

        platform.event_stage = "open"
        for symbol, reason in sorted(open_exit_reasons.items()):
            if not executable(platform, symbol, "executable_09_30"):
                retry_open.add(symbol)
                exit_no_fills += 1
                record("SELL_NO_FILL", symbol, stage="open", reason=reason)
                continue
            price = exact_price(platform, symbol, "OPEN_BAR_09_30", "pre_adj_close")
            if price is None:
                raise ValueError(f"missing executable open exit price: {platform.current_date} {symbol}")
            close_trade(symbol, price, "open", reason)

        if market["entry_permission"]:
            candidates, scan_meta = scan_unlimited_candidates(
                namespace,
                context,
                pre_open_symbols,
            )
        else:
            candidates, scan_meta = [], {
                "active": 0,
                "eligible": 0,
                "price_signals": 0,
                "minvol_pass": 0,
            }
        total_candidates += len(candidates)
        record(
            "DAILY_SCAN",
            "",
            stage="before_trading",
            market_entry_permission=bool(market["entry_permission"]),
            candidates=len(candidates),
            **scan_meta,
        )
        for symbol in candidates:
            record(
                "BUY_SIGNAL",
                symbol,
                stage="before_trading",
                signal_date=signal_date_value,
                reason="ENTRY_B60_FULL40_MINVOLLOC30_RS_UNLIMITED",
            )
            if not executable(platform, symbol, "executable_09_30"):
                entry_no_fills += 1
                record(
                    "BUY_NO_FILL",
                    symbol,
                    stage="open",
                    signal_date=signal_date_value,
                )
                continue
            price = exact_price(platform, symbol, "OPEN_BAR_09_30", "pre_adj_close")
            if price is None:
                raise ValueError(f"missing executable entry price: {platform.current_date} {symbol}")
            trade = IndependentTrade(
                trade_id=next_trade_id,
                symbol=symbol,
                entry_signal_date=signal_date_value,
                entry_date=platform.current_date,
                entry_price=price,
                entry_reason="ENTRY_B60_FULL40_MINVOLLOC30_RS_UNLIMITED",
            )
            next_trade_id += 1
            open_trades[symbol] = trade
            record(
                "BUY_FILLED",
                symbol,
                trade_id=trade.trade_id,
                stage="open",
                signal_date=signal_date_value,
                price_pre_adj=price,
            )

        platform.event_stage = "signal"
        signal_bars = platform.bar_dict(include_signal=True)
        tail_market = namespace["market_state_1457"](
            context,
            timestamp,
            signal_bars,
        )
        tail_exit_reasons: dict[str, str] = {}
        if tail_market["system_exit"]:
            for symbol in open_trades:
                tail_exit_reasons[symbol] = "MARKET_EXIT_AT_1457"
        else:
            for symbol in own_exit_at_1457(
                namespace,
                context,
                platform,
                list(open_trades),
                signal_bars,
            ):
                tail_exit_reasons[symbol] = "OWN_EXIT_MA40_C2_AT_1457"
        for symbol in retry_open:
            if symbol in open_trades:
                tail_exit_reasons.setdefault(symbol, "RETRY_PRIOR_EXIT_AT_1457")

        platform.event_stage = "close"
        for symbol, reason in sorted(tail_exit_reasons.items()):
            record(
                "SELL_SIGNAL",
                symbol,
                trade_id=open_trades[symbol].trade_id,
                stage="signal_1457",
                reason=reason,
                price_pre_adj=exact_price(
                    platform,
                    symbol,
                    "PSEUDO_CLOSE_14_57_OPEN",
                    "pre_adj_open",
                ),
            )
            if not executable(platform, symbol, "executable_15_00"):
                retry_open.add(symbol)
                exit_no_fills += 1
                record("SELL_NO_FILL", symbol, stage="close", reason=reason)
                continue
            price = exact_price(platform, symbol, "FINAL_CLOSE_BAR", "pre_adj_close")
            if price is None:
                raise ValueError(f"missing executable close exit price: {platform.current_date} {symbol}")
            close_trade(symbol, price, "close", reason)

    trade_rows = list(completed)
    for trade in open_trades.values():
        trade_rows.append(
            {
                **asdict(trade),
                "exit_signal_date": None,
                "exit_date": None,
                "exit_price": None,
                "exit_stage": None,
                "exit_reason": None,
                "holding_sessions": None,
                "return_pct": None,
            }
        )
    trades = pd.DataFrame(trade_rows).sort_values(["entry_date", "symbol"]).reset_index(drop=True)
    event_frame = pd.DataFrame(events).sort_values(["trade_date", "event_type", "symbol"]).reset_index(drop=True)
    return trades, event_frame, {
        "calendar_start": str(calendar[0].date()),
        "calendar_end": str(calendar[-1].date()),
        "calendar_sessions": len(calendar),
        "candidate_signals": total_candidates,
        "entry_no_fills": entry_no_fills,
        "exit_no_fills": exit_no_fills,
        "completed_trades": len(completed),
        "open_trades_end": len(open_trades),
        "open_symbols_end": sorted(open_trades),
    }


def annual_summary(
    trades: pd.DataFrame,
    start_year: int,
    end_year: int,
) -> dict[str, dict[str, Any]]:
    entry_dates = pd.to_datetime(trades["entry_date"])
    result: dict[str, dict[str, Any]] = {}
    for year in range(start_year, end_year + 1):
        selected = trades[entry_dates.dt.year.eq(year)]
        completed = selected[selected["return_pct"].notna()]
        pnl = distribution(completed["return_pct"])
        holding = distribution(completed["holding_sessions"])
        wins = completed.loc[completed["return_pct"].gt(0), "return_pct"]
        losses = completed.loc[completed["return_pct"].le(0), "return_pct"]
        result[str(year)] = {
            "entry_trades": len(selected),
            "completed_trades": len(completed),
            "open_trades": int(selected["return_pct"].isna().sum()),
            "return": pnl,
            "holding_sessions": holding,
            "average_win": float(wins.mean()) if not wins.empty else None,
            "average_loss": float(losses.mean()) if not losses.empty else None,
            "profit_factor": (
                float(wins.sum() / -losses.sum())
                if not wins.empty and losses.sum() < 0
                else None
            ),
        }
    return result


def percent(value: object) -> str:
    if value is None or pd.isna(value):
        return "NA"
    return f"{float(value):+.2%}"


def rate(value: object) -> str:
    if value is None or pd.isna(value):
        return "NA"
    return f"{float(value):.1%}"


def number(value: object) -> str:
    if value is None or pd.isna(value):
        return "NA"
    return f"{float(value):.2f}"


def write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# SuperMind V6 unlimited-capital independent trade quality",
        "",
        "Each ETF can carry one independent trade. There is no portfolio holding limit, capital budget, position weight, or cross-symbol cash competition.",
        "Entry and exit conditions, signal timing, and fail-closed execution references are inherited from the frozen V6 strategy.",
        "",
        "| Entry year | Trades | Completed | Open | Win rate | Mean | Median | P10 | P90 | Avg win | Avg loss | Profit factor | Mean hold | Median hold |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for year, item in summary["annual"].items():
        pnl = item["return"]
        holding = item["holding_sessions"]
        lines.append(
            f"| {year} | {item['entry_trades']} | {item['completed_trades']} | {item['open_trades']} | "
            f"{rate(pnl['win_rate'])} | {percent(pnl['mean'])} | {percent(pnl['median'])} | "
            f"{percent(pnl['p10'])} | {percent(pnl['p90'])} | {percent(item['average_win'])} | "
            f"{percent(item['average_loss'])} | {number(item['profit_factor'])} | "
            f"{number(holding['mean'])} | {number(holding['median'])} |"
        )
    lines.extend(
        [
            "",
            "## Semantics",
            "",
            "- Unlimited capital removes max_holdings=5, full-portfolio scan suppression, CAP50_SET weights, and cross-symbol cash competition.",
            "- All ETFs passing the frozen CSI1000 gate, eligibility, B60, FULL40, MINVOLLOC30, and RS-availability checks are bought at the exact next 09:30 executable reference.",
            "- One independent trade per ETF may be open at a time; after exit, the ETF may generate another trade.",
            "- Exits preserve the frozen next-open and 14:57/final-close market and own-MA40x2 rules.",
            "- Missing/invalid critical bars produce no-fill and are retried only through the original continuing signal state; no daily-price substitution is used.",
            "- Fees, slippage, lot rounding, and native SuperMind order-return semantics remain unverified/not simulated.",
            "- The frozen 152-ETF pool creates survivor bias in early years.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    trades, events, replay_meta = run_replay(args)
    atomic_write_parquet(trades, args.trades)
    atomic_write_parquet(events, args.events)
    annual = annual_summary(trades, args.start.year, args.end.year)
    completed = trades[trades["return_pct"].notna()]
    overall_returns = distribution(completed["return_pct"])
    overall_holding = distribution(completed["holding_sessions"])
    wins = completed.loc[completed["return_pct"].gt(0), "return_pct"]
    losses = completed.loc[completed["return_pct"].le(0), "return_pct"]
    summary = {
        "replay_version": "v6-unlimited-independent-trades-1",
        "status": "EXPLORATORY_HYBRID_UNLIMITED_CAPITAL",
        "generated_at": datetime.now().astimezone().isoformat(),
        "window_start": args.start.isoformat(),
        "window_end": args.end.isoformat(),
        "strategy_source_sha256": strategy_sha256(),
        "trades_path": str(args.trades),
        "trades_sha256": sha256_file(args.trades),
        "events_path": str(args.events),
        "events_sha256": sha256_file(args.events),
        "replay": replay_meta,
        "overall": {
            "return": overall_returns,
            "holding_sessions": overall_holding,
            "average_win": float(wins.mean()) if not wins.empty else None,
            "average_loss": float(losses.mean()) if not losses.empty else None,
            "profit_factor": (
                float(wins.sum() / -losses.sum())
                if not wins.empty and losses.sum() < 0
                else None
            ),
        },
        "annual": annual,
        "semantics": [
            "unlimited cross-symbol capital and no portfolio holding limit",
            "one open independent trade per ETF at a time",
            "all frozen-rule candidates are entered rather than only filling up to five portfolio slots",
            "frozen next-open and 14:57/final-close exit rules are preserved",
            "missing critical execution bars fail closed",
        ],
    }
    atomic_write_json(args.summary, summary)
    write_report(args.report, summary)
    print(f"TRADES {len(trades)}")
    print(f"COMPLETED {len(completed)}")
    print(f"EVENTS {len(events)}")
    print(f"SUMMARY {args.summary}")
    print(f"REPORT {args.report}")
    print(json.dumps(replay_meta, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
