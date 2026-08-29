from __future__ import annotations

# ruff: noqa: E501
import argparse
import json
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
from run_v6_shadow_chartbook import (
    ShadowPlatform,
    frozen_namespace,
    record_pending_signals,
)
from v6_data_common import RESEARCH_ROOT, atomic_write_json, atomic_write_parquet, strategy_sha256

DATA_ROOT = RESEARCH_ROOT / "data" / "market_data_qmt_chinext_v1"
ETF_ROOT = RESEARCH_ROOT / "data" / "market_data_qmt_v1"
UNIVERSE_PATH = RESEARCH_ROOT / "manifests" / "chinext_current_survivor_universe.json"
EVENTS_PATH = RESEARCH_ROOT / "output" / "v6_chinext_shadow_events.parquet"
SUMMARY_PATH = RESEARCH_ROOT / "manifests" / "v6_chinext_shadow_summary.json"
REPORT_PATH = RESEARCH_ROOT / "reports" / "v6_chinext_signal_quality.md"
CANDIDATES_PATH = RESEARCH_ROOT / "manifests" / "v6_chinext_candidate_symbols.json"
START = date(2025, 8, 28)
END = date(2026, 8, 28)
ANCHORS = ["000852.SH", "510300.SH"]


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
            selected = frame.iloc[max(0, end - count) : end]
            result[symbol] = selected[fields]
        return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=date.fromisoformat, default=START)
    parser.add_argument("--end", type=date.fromisoformat, default=END)
    parser.add_argument("--universe", type=Path, default=UNIVERSE_PATH)
    parser.add_argument("--events", type=Path, default=EVENTS_PATH)
    parser.add_argument("--summary", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--daily-proxy", action="store_true")
    parser.add_argument("--candidates", type=Path, default=CANDIDATES_PATH)
    return parser.parse_args()


def daily_path(symbol: str) -> Path:
    root = ETF_ROOT if symbol in ANCHORS else DATA_ROOT
    return root / "daily" / f"symbol={symbol}" / "daily.parquet"


def minute_path(symbol: str) -> Path:
    root = ETF_ROOT if symbol in ANCHORS else DATA_ROOT
    return root / "minute_critical" / f"symbol={symbol}" / "critical.parquet"


def load_daily(symbol: str) -> pd.DataFrame:
    frame = pd.read_parquet(daily_path(symbol))
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


def load_minute(symbol: str) -> pd.DataFrame:
    path = minute_path(symbol)
    if not path.exists():
        return pd.DataFrame(columns=["trade_date", "bar_role", "row_status"])
    frame = pd.read_parquet(path)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    return frame


def daily_proxy_minute(symbol: str, daily: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    selected = daily[(daily.index.date >= start) & (daily.index.date <= end)].copy()
    rows = []
    for role, raw_field, adjusted_field in [
        ("OPEN_BAR_09_30", "raw_open", "pre_adj_open"),
        ("PSEUDO_CLOSE_14_57_OPEN", "raw_close", "pre_adj_close"),
        ("FINAL_CLOSE_BAR", "raw_close", "pre_adj_close"),
    ]:
        frame = pd.DataFrame(
            {
                "trade_date": selected.index.date,
                "bar_role": role,
                "row_status": selected["row_status"].to_numpy(),
                "raw_open": selected[raw_field].to_numpy(),
                "pre_adj_open": selected[adjusted_field].to_numpy(),
                "raw_close": selected[raw_field].to_numpy(),
                "pre_adj_close": selected[adjusted_field].to_numpy(),
            }
        )
        rows.append(frame)
    return pd.concat(rows, ignore_index=True)


def availability_for_symbol(
    symbol: str,
    daily: pd.DataFrame,
    minute: pd.DataFrame,
    start: date,
    end: date,
) -> pd.DataFrame:
    expected = daily[
        (daily.index.date >= start)
        & (daily.index.date <= end)
        & daily["row_status"].eq("VALID")
    ].copy()
    output = pd.DataFrame({"trade_date": expected.index.date})
    output["symbol"] = symbol
    roles = {
        "OPEN_BAR_09_30": "executable_09_30",
        "PSEUDO_CLOSE_14_57_OPEN": "tail_signal_available_14_57",
        "FINAL_CLOSE_BAR": "executable_15_00",
    }
    for role, column in roles.items():
        rows = minute[minute["bar_role"].eq(role)][["trade_date", "row_status"]].copy()
        if rows["trade_date"].duplicated().any():
            raise ValueError(f"duplicate {role}: {symbol}")
        rows[column] = rows["row_status"].eq("VALID")
        output = output.merge(rows[["trade_date", column]], on="trade_date", how="left")
        output[column] = output[column].eq(True)
    return output


def override_universe(context: SimpleNamespace, symbols: list[str]) -> None:
    context.pool_raw = [symbol.split(".")[0] for symbol in symbols]
    context.pool_raw_set = set(context.pool_raw)
    context.static_symbols = symbols.copy()
    context.security = [*symbols, *[symbol for symbol in ANCHORS if symbol not in symbols]]


def stock_aware_expected_symbol(value: object) -> str:
    digits = "".join(character for character in str(value) if character.isdigit())[:6].zfill(6)
    if digits.startswith(("5", "6")):
        return f"{digits}.SH"
    if digits.startswith(("0", "1", "2", "3")):
        return f"{digits}.SZ"
    return digits


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


def distribution(values: pd.Series) -> dict[str, float | int | None]:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return {"n": 0, "mean": None, "median": None, "win_rate": None}
    return {
        "n": len(clean),
        "mean": float(clean.mean()),
        "median": float(clean.median()),
        "win_rate": float(clean.gt(0).mean()),
        "p10": float(clean.quantile(0.10)),
        "p90": float(clean.quantile(0.90)),
    }


def run(args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any]]:
    universe = json.loads(args.universe.read_text(encoding="utf-8"))
    symbols = list(universe["symbols"])
    all_symbols = [*symbols, *ANCHORS]
    daily = {symbol: load_daily(symbol) for symbol in all_symbols}
    minute = {
        symbol: (
            daily_proxy_minute(symbol, daily[symbol], args.start, args.end)
            if args.daily_proxy and symbol not in ANCHORS
            else load_minute(symbol)
        )
        for symbol in all_symbols
    }
    calendar = [
        timestamp
        for timestamp in daily["000852.SH"].index
        if args.start <= timestamp.date() <= args.end
        and np.isfinite(daily["000852.SH"].loc[timestamp, "pre_adj_close"])
    ]
    availability = pd.concat(
        [
            availability_for_symbol(symbol, daily[symbol], minute[symbol], args.start, args.end)
            for symbol in all_symbols
        ],
        ignore_index=True,
    )
    platform = FastShadowPlatform(daily, minute, availability, calendar)
    namespace = frozen_namespace(platform)
    namespace["expected_sm_symbol"] = stock_aware_expected_symbol
    context = SimpleNamespace()
    context.portfolio = SimpleNamespace(stock_account=SimpleNamespace(positions=platform.positions))
    namespace["init"](context)
    override_universe(context, symbols)

    for timestamp in calendar:
        platform.current_date = timestamp.date()
        platform.event_stage = "before_trading"
        prior_holdings = set(platform.positions)
        namespace["before_trading"](context)
        record_pending_signals(platform, context, prior_holdings)
        platform.event_stage = "open"
        execution_label = getattr(args, "execution_label", "CHINEXT_SHADOW_09_30")
        namespace["execute_pending_open"](context, platform.bar_dict(), execution_label)
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
        raise ValueError("ChiNext shadow produced no events")
    events["trade_date"] = pd.to_datetime(events["trade_date"]).dt.date
    metrics = []
    for row in events[events["event_type"].eq("BUY_FILLED")].itertuples(index=False):
        item: dict[str, Any] = {
            "trade_date": row.trade_date,
            "symbol": row.symbol,
            "metric_entry_price": float(row.price_pre_adj),
        }
        item.update(forward_metrics(daily[row.symbol], row.trade_date, float(row.price_pre_adj)))
        metrics.append(item)
    metric_frame = pd.DataFrame(metrics)
    events = events.merge(metric_frame, on=["trade_date", "symbol"], how="left")
    exits = events[events["event_type"].eq("SELL_FILLED")]
    summary: dict[str, Any] = {
        "experiment": "V6_CHINEXT_CURRENT_SURVIVOR_COUNTERFACTUAL",
        "status": "EXPLORATORY_NON_PIT",
        "generated_at": datetime.now().astimezone().isoformat(),
        "window_start": args.start.isoformat(),
        "window_end": args.end.isoformat(),
        "calendar_sessions": len(calendar),
        "universe_count": len(symbols),
        "universe_point_in_time": False,
        "strategy_source_sha256": strategy_sha256(),
        "price_basis": "QMT front-adjusted; SuperMind fq=pre equivalence unverified",
        "execution": "QMT critical bars with fail-closed availability; exact SuperMind matching unverified",
        "candidate_pass_daily_proxy": bool(args.daily_proxy),
        "event_counts": {str(key): int(value) for key, value in events["event_type"].value_counts().items()},
        "unique_bought_symbols": int(events.loc[events["event_type"].eq("BUY_FILLED"), "symbol"].nunique()),
        "roundtrip_holding_pnl": distribution(exits.get("holding_pnl_pct", pd.Series(dtype=float))),
        "forward_quality": {
            column: distribution(metric_frame.get(column, pd.Series(dtype=float)))
            for column in ["fwd_5d", "fwd_10d", "fwd_20d", "fwd_60d", "mfe_20d", "mae_20d"]
        },
        "limitations": [
            "current-survivor universe is not historical point-in-time and has survivorship bias",
            "stock limit-up/down, lot size, fees, slippage, partial fills, and cash are not simulated",
            "QMT front adjustment is not proven equivalent to SuperMind fq=pre",
            "order_target return semantics are simplified to full fill or fail-closed no-fill",
        ],
    }
    return events.sort_values(["trade_date", "symbol", "event_type"]), summary


def fmt_metric(metric: dict[str, Any]) -> str:
    if not metric or metric.get("n", 0) == 0:
        return "n=0"
    return (
        f"n={metric['n']}, mean={metric['mean']:.2%}, median={metric['median']:.2%}, "
        f"win={metric['win_rate']:.1%}, p10={metric['p10']:.2%}, p90={metric['p90']:.2%}"
    )


def write_report(path: Path, summary: dict[str, Any]) -> None:
    forward = summary["forward_quality"]
    lines = [
        "# SuperMind V6 on ChiNext stocks - exploratory signal quality",
        "",
        f"Window: {summary['window_start']}..{summary['window_end']} ({summary['calendar_sessions']} sessions)",
        f"Universe: {summary['universe_count']} current-listed 300/301 ChiNext stocks (NON-PIT survivor universe)",
        "",
        "## Result",
        "",
        f"- Event counts: `{json.dumps(summary['event_counts'], ensure_ascii=False, sort_keys=True)}`",
        f"- Unique bought symbols: {summary['unique_bought_symbols']}",
        f"- Completed holding P&L: {fmt_metric(summary['roundtrip_holding_pnl'])}",
        f"- Forward 5 sessions: {fmt_metric(forward['fwd_5d'])}",
        f"- Forward 10 sessions: {fmt_metric(forward['fwd_10d'])}",
        f"- Forward 20 sessions: {fmt_metric(forward['fwd_20d'])}",
        f"- Forward 60 sessions: {fmt_metric(forward['fwd_60d'])}",
        f"- 20-session MFE: {fmt_metric(forward['mfe_20d'])}",
        f"- 20-session MAE: {fmt_metric(forward['mae_20d'])}",
        "",
        "## Interpretation boundary",
        "",
        *[f"- {item}" for item in summary["limitations"]],
        "",
        "This experiment does not modify the frozen strategy. It replaces only the static ETF pool after init inside a research sandbox.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    events, summary = run(args)
    atomic_write_parquet(events, args.events)
    atomic_write_json(args.summary, summary)
    write_report(args.report, summary)
    candidate_symbols = sorted(
        events.loc[
            events["event_type"].isin(["BUY_SIGNAL", "BUY_FILLED", "REBALANCE_FILLED"]),
            "symbol",
        ].unique()
    )
    atomic_write_json(
        args.candidates,
        {
            "candidate_source": "V6 ChiNext daily-proxy pass" if args.daily_proxy else "V6 ChiNext final shadow",
            "symbol_count": len(candidate_symbols),
            "symbols": candidate_symbols,
        },
    )
    print(f"EVENTS {len(events)}")
    print(f"BUYS {summary['event_counts'].get('BUY_FILLED', 0)}")
    print(f"SELLS {summary['event_counts'].get('SELL_FILLED', 0)}")
    print(f"REPORT {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
