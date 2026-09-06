#!/usr/bin/env python3
"""Run the frozen SMV6 callbacks with explicit local cash and lot constraints."""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "research/supermind_v6/scripts"
sys.path.insert(0, str(SCRIPTS))

from run_v6_hybrid_annual_replay import FastShadowPlatform, load_daily, load_minute  # noqa: E402
from run_v6_shadow_chartbook import Position, frozen_namespace, record_pending_signals  # noqa: E402
from v6_data_common import (  # noqa: E402
    atomic_write_json,
    atomic_write_parquet,
    canonical_symbol,
    parse_strategy_pool,
    strategy_sha256,
)


class CashPlatform(FastShadowPlatform):
    """Minimal LOCAL_SEMANTICS_REPLAY; no claim of native SuperMind equivalence."""

    def __init__(
        self, *args: object, initial_cash: float, lot_size: int, fee_bps: float, **kwargs: object
    ) -> None:
        super().__init__(*args, **kwargs)
        self.cash = initial_cash
        self.initial_cash = initial_cash
        self.lot_size = lot_size
        self.fee_rate = fee_bps / 10_000
        self.shares: dict[str, int] = {}
        self.accounts: list[dict[str, object]] = []

    def _mark(self, symbol: str, stage: str) -> float:
        if stage == "open":
            value = self._minute_price(symbol, "OPEN_BAR_09_30", "pre_adj_close")
        elif stage == "close":
            value = self._minute_price(symbol, "FINAL_CLOSE_BAR", "pre_adj_close")
        else:
            value = self._daily_marker_price(symbol)
        return value

    def nav(self, stage: str) -> float:
        value = self.cash
        for symbol, qty in self.shares.items():
            mark = self._mark(symbol, stage)
            if not np.isfinite(mark):
                mark = self._daily_marker_price(symbol)
            value += qty * mark
        return value

    def order_target_percent(self, symbol: str, target_weight: float) -> object | None:
        row = self._current_row(symbol)
        if self.event_stage != "open" or row is None or not bool(row["executable_09_30"]):
            self._record(
                "BUY_OR_REBALANCE_NO_FILL",
                symbol,
                price=self._daily_marker_price(symbol),
                target_weight=float(target_weight),
                reject_reason="NOT_EXECUTABLE",
            )
            return None
        price = self._mark(symbol, "open")
        current = self.shares.get(symbol, 0)
        desired = (
            math.floor((self.nav("open") * target_weight / price) / self.lot_size) * self.lot_size
        )
        delta = desired - current
        if delta > 0:
            affordable = (
                math.floor((self.cash / (price * (1 + self.fee_rate))) / self.lot_size)
                * self.lot_size
            )
            delta = min(delta, affordable)
        if delta == 0 and current == 0:
            self._record(
                "BUY_OR_REBALANCE_NO_FILL",
                symbol,
                price=price,
                target_weight=float(target_weight),
                reject_reason="INSUFFICIENT_CASH_OR_LOT",
            )
            return None
        notional = abs(delta) * price
        fee = notional * self.fee_rate
        self.cash -= delta * price + fee
        if self.cash < -1e-8:
            raise RuntimeError(f"cash invariant violated: {self.cash}")
        new_qty = current + delta
        event_type = "BUY_FILLED" if current == 0 else "REBALANCE_FILLED"
        if current == 0:
            self.positions[symbol] = Position(
                symbol, float(target_weight), self.current_date, price
            )
        else:
            self.positions[symbol].target_weight = float(target_weight)
        self.shares[symbol] = new_qty
        self._record(
            event_type,
            symbol,
            price=price,
            target_weight=float(target_weight),
            requested_qty=desired,
            filled_delta_qty=delta,
            position_qty=new_qty,
            fee=fee,
            cash_after=self.cash,
        )
        return f"local-cash-open-{symbol}-{self.current_date.isoformat()}"

    def order_target(self, symbol: str, target: float) -> object | None:
        if target != 0:
            raise ValueError("only liquidation is supported")
        row = self._current_row(symbol)
        if row is None:
            self._record(
                "SELL_NO_FILL",
                symbol,
                price=self._daily_marker_price(symbol),
                reject_reason="NO_ROW",
            )
            return None
        if self.event_stage == "open":
            executable, stage = bool(row["executable_09_30"]), "open"
        elif self.event_stage == "close":
            executable, stage = bool(row["executable_15_00"]), "close"
        else:
            raise ValueError(f"unexpected liquidation stage: {self.event_stage}")
        if not executable:
            self._record(
                "SELL_NO_FILL",
                symbol,
                price=self._daily_marker_price(symbol),
                reject_reason="NOT_EXECUTABLE",
            )
            return None
        price = self._mark(symbol, stage)
        position = self.positions.pop(symbol)
        qty = self.shares.pop(symbol)
        fee = qty * price * self.fee_rate
        self.cash += qty * price - fee
        self._record(
            "SELL_FILLED",
            symbol,
            price=price,
            entry_date=position.entry_date,
            entry_price=position.entry_price,
            holding_pnl_pct=price / position.entry_price - 1,
            filled_delta_qty=-qty,
            position_qty=0,
            fee=fee,
            cash_after=self.cash,
        )
        return f"local-cash-{stage}-{symbol}-{self.current_date.isoformat()}"

    def record_account(self) -> None:
        nav = self.nav("eod")
        exposure = nav - self.cash
        self.accounts.append(
            {
                "trade_date": self.current_date,
                "nav": nav,
                "cash": self.cash,
                "gross_exposure": exposure,
                "cash_weight": self.cash / nav,
                "gross_exposure_ratio": exposure / nav,
                "position_count": len(self.positions),
            }
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--qmt-root", type=Path, required=True)
    parser.add_argument("--hybrid-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--initial-cash", type=float, default=1_000_000)
    parser.add_argument("--lot-size", type=int, default=100)
    parser.add_argument("--fee-bps", type=float, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pool = [canonical_symbol(code) for code in parse_strategy_pool()]
    symbols = [*pool, "000852.SH"]
    daily = {symbol: load_daily(args.qmt_root, symbol) for symbol in symbols}
    minute = {symbol: load_minute(args.hybrid_root, symbol) for symbol in symbols}
    availability = pd.read_parquet(
        args.hybrid_root / "execution_availability/critical_execution.parquet"
    )
    availability["trade_date"] = pd.to_datetime(availability.trade_date).dt.date
    availability = availability[availability.trade_date.between(args.start, args.end)]
    calendar = [
        ts
        for ts in daily["000852.SH"].index
        if args.start <= ts.date() <= args.end
        and np.isfinite(daily["000852.SH"].loc[ts, "pre_adj_close"])
    ]
    platform = CashPlatform(
        daily,
        minute,
        availability,
        calendar,
        initial_cash=args.initial_cash,
        lot_size=args.lot_size,
        fee_bps=args.fee_bps,
    )
    namespace = frozen_namespace(platform)
    context = SimpleNamespace(
        portfolio=SimpleNamespace(stock_account=SimpleNamespace(positions=platform.positions))
    )
    namespace["init"](context)
    for timestamp in calendar:
        platform.current_date = timestamp.date()
        platform.event_stage = "before_trading"
        prior = set(platform.positions)
        namespace["before_trading"](context)
        record_pending_signals(platform, context, prior)
        platform.event_stage = "open"
        namespace["execute_pending_open"](context, platform.bar_dict(), "LOCAL_CASH_09_30")
        platform.event_stage = "signal"
        namespace["run_1457_exit_signal"](context, platform.bar_dict(include_signal=True))
        for symbol in context.pending_close_sells:
            platform._record(
                "TAIL_SELL_SIGNAL",
                symbol,
                price=platform._minute_price(symbol, "PSEUDO_CLOSE_14_57_OPEN", "pre_adj_open"),
                reason=context.pending_close_reason,
            )
        platform.event_stage = "close"
        namespace["execute_pending_close_sells"](context, platform.bar_dict(include_close=True))
        platform.record_account()
    events = (
        pd.DataFrame(platform.events)
        .sort_values(["trade_date", "symbol", "event_type"])
        .reset_index(drop=True)
    )
    accounts = pd.DataFrame(platform.accounts)
    args.output_root.mkdir(parents=True, exist_ok=True)
    atomic_write_parquet(events, args.output_root / "events.parquet")
    atomic_write_parquet(accounts, args.output_root / "daily_account.parquet")
    summary = {
        "status": "LOCAL_SEMANTICS_REPLAY",
        "strategy_sha256": strategy_sha256(),
        "start": args.start.isoformat(),
        "end": args.end.isoformat(),
        "initial_cash": args.initial_cash,
        "lot_size": args.lot_size,
        "fee_bps": args.fee_bps,
        "event_counts": events.event_type.value_counts().astype(int).to_dict(),
        "ending_nav": float(accounts.nav.iloc[-1]),
        "minimum_cash": float(accounts.cash.min()),
        "maximum_gross_exposure_ratio": float(accounts.gross_exposure_ratio.max()),
        "open_positions_end": sorted(platform.positions),
        "native_equivalence": "NOT_RUN",
    }
    atomic_write_json(args.output_root / "summary.json", summary)
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
