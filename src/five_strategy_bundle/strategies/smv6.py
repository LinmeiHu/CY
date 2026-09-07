"""Minimal local callback runtime for the exact registered SMV6 source."""

from __future__ import annotations

import ast
import hashlib
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

from ..errors import ReproductionError

FROZEN_SOURCE = Path(__file__).with_name("smv6_frozen.py")
FROZEN_SHA256 = "7fa9d715bdf4c352526d556132f8ec8502e9f355876100f357c8bdc5fdc91f33"


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


def source_sha256() -> str:
    return hashlib.sha256(FROZEN_SOURCE.read_bytes()).hexdigest()


def raw_pool() -> list[str]:
    tree = ast.parse(FROZEN_SOURCE.read_text(encoding="utf-8"))
    values: list[list[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Attribute) and target.attr == "pool_raw" for target in node.targets):
            pool = ast.literal_eval(node.value)
            if isinstance(pool, list) and all(isinstance(item, str) for item in pool):
                values.append(pool)
    if len(values) != 1:
        raise ReproductionError(f"SMV6 frozen pool assignment count: {len(values)}")
    return values[0]


def canonical_symbol(raw: str) -> str:
    if len(raw) != 6 or not raw.isdigit() or not raw.startswith(("1", "5")):
        raise ReproductionError(f"unsupported SMV6 ETF code: {raw}")
    return f"{raw}.{'SZ' if raw.startswith('1') else 'SH'}"


def load_daily(root: Path, symbol: str) -> pd.DataFrame:
    path = root / "daily" / f"symbol={symbol}" / "daily.parquet"
    frame = pd.read_parquet(path)
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    frame = frame.set_index("trade_date").sort_index()
    invalid = ~frame.row_status.eq("VALID")
    columns = ["pre_adj_open", "pre_adj_high", "pre_adj_low", "pre_adj_close", "volume_raw", "amount_cny"]
    frame.loc[invalid, columns] = np.nan
    return frame


def load_minute(root: Path, symbol: str) -> pd.DataFrame:
    path = root / "minute_critical" / f"symbol={symbol}" / "critical.parquet"
    frame = pd.read_parquet(path)
    frame["trade_date"] = pd.to_datetime(frame.trade_date).dt.date
    return frame


class ShadowPlatform:
    """Compatibility API actually reached by the frozen callbacks."""

    def __init__(
        self,
        daily: dict[str, pd.DataFrame],
        minute: dict[str, pd.DataFrame],
        availability: pd.DataFrame,
        calendar: list[pd.Timestamp],
    ) -> None:
        self.daily = daily
        if availability.duplicated(["trade_date", "symbol"]).any():
            raise ReproductionError("duplicate SMV6 availability rows")
        for symbol, frame in minute.items():
            if frame.duplicated(["trade_date", "bar_role"]).any():
                raise ReproductionError(f"duplicate SMV6 minute role: {symbol}")
        self.minute_rows = {
            symbol: {
                (row.trade_date, row.bar_role): (
                    float(row.pre_adj_open),
                    float(row.pre_adj_close),
                    float(row.volume_shares),
                )
                for row in frame.itertuples(index=False)
            }
            for symbol, frame in minute.items()
        }
        self.availability = {
            (row.trade_date, row.symbol): row
            for row in availability.itertuples(index=False)
        }
        self.calendar = calendar
        self.current_date = calendar[0].date()
        self.event_stage = ""
        self.commission_rate = 0.0
        self.slippage_total = 0.0
        self.daily_volume_limit = 1.0
        self.minute_volume_limit = 1.0
        self.positions: dict[str, Position] = {}
        self.events: list[dict[str, Any]] = []
        self.list_dates = {
            symbol: frame.index.min().date()
            for symbol, frame in daily.items()
            if not frame.empty
        }
        self.history_frames = {
            symbol: pd.DataFrame(
                {
                    "close": frame.pre_adj_close,
                    "volume": frame.volume_raw,
                    "turnover": frame.amount_cny,
                },
                index=frame.index,
            )
            for symbol, frame in daily.items()
        }

    def _current_row(self, symbol: str) -> Any | None:
        return self.availability.get((self.current_date, symbol))

    def _minute_price(self, symbol: str, role: str, field: str) -> float:
        row = self.minute_rows[symbol].get((self.current_date, role))
        if row is None:
            return float("nan")
        value = row[0 if field == "pre_adj_open" else 1]
        return value if np.isfinite(value) and value > 0 else float("nan")

    def _minute_volume(self, symbol: str, role: str) -> float:
        row = self.minute_rows[symbol].get((self.current_date, role))
        if row is None:
            return 0.0
        value = row[2]
        return value if np.isfinite(value) and value > 0 else 0.0

    def _daily_marker_price(self, symbol: str) -> float:
        timestamp = pd.Timestamp(self.current_date)
        if timestamp not in self.daily[symbol].index:
            return float("nan")
        value = float(self.daily[symbol].loc[timestamp, "pre_adj_close"])
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

    def history(self, symbols: list[str], fields: list[str], count: int, period: str, *_: object) -> dict[str, pd.DataFrame]:
        if period != "1d":
            return {}
        cutoff = pd.Timestamp(self.current_date)
        result: dict[str, pd.DataFrame] = {}
        for symbol in symbols:
            frame = self.history_frames.get(symbol)
            if frame is None:
                continue
            end = int(frame.index.searchsorted(cutoff, side="left"))
            if end:
                result[symbol] = frame.iloc[max(0, end - count) : end][fields]
        return result

    def get_all_securities(self, security_type: str) -> pd.DataFrame:
        if security_type != "etf":
            return pd.DataFrame()
        return pd.DataFrame(
            index=[symbol for symbol, listed in self.list_dates.items() if listed <= self.current_date]
        )

    def get_trade_days(self, start: str, end: str) -> list[pd.Timestamp]:
        return [day for day in self.calendar if pd.Timestamp(start) <= day <= pd.Timestamp(end)]

    def bar_dict(self, *, include_signal: bool = False, include_close: bool = False) -> dict[str, Any]:
        bars: dict[str, Any] = {}
        for symbol in self.daily:
            row = self._current_row(symbol)
            if row is None:
                continue
            if include_signal and bool(row.tail_signal_available_14_57):
                price = self._minute_price(symbol, "PSEUDO_CLOSE_14_57_OPEN", "pre_adj_open")
            elif include_close and bool(row.executable_15_00):
                price = self._minute_price(symbol, "FINAL_CLOSE_BAR", "pre_adj_close")
            elif self.event_stage == "open" and bool(row.executable_09_30):
                price = self._minute_price(symbol, "OPEN_BAR_09_30", "pre_adj_close")
            else:
                continue
            if np.isfinite(price):
                bars[symbol] = SimpleNamespace(open=price, close=price)
        return bars

    def order_target_percent(self, symbol: str, target_weight: float) -> object | None:
        row = self._current_row(symbol)
        if self.event_stage != "open" or row is None or not bool(row.executable_09_30):
            self._record("BUY_OR_REBALANCE_NO_FILL", symbol, price=self._daily_marker_price(symbol), target_weight=float(target_weight))
            return None
        price = self._minute_price(symbol, "OPEN_BAR_09_30", "pre_adj_close")
        kind = "BUY_FILLED" if symbol not in self.positions else "REBALANCE_FILLED"
        if kind == "BUY_FILLED":
            self.positions[symbol] = Position(symbol, float(target_weight), self.current_date, price)
        else:
            self.positions[symbol].target_weight = float(target_weight)
        self._record(kind, symbol, price=price, target_weight=float(target_weight))
        return f"shadow-open-{symbol}-{self.current_date.isoformat()}"

    def order_target(self, symbol: str, target: float) -> object | None:
        if target != 0:
            raise ReproductionError("SMV6 local runtime supports liquidation target only")
        row = self._current_row(symbol)
        executable = False
        if row is not None and self.event_stage == "open":
            executable, role = bool(row.executable_09_30), "OPEN_BAR_09_30"
        elif row is not None and self.event_stage == "close":
            executable, role = bool(row.executable_15_00), "FINAL_CLOSE_BAR"
        else:
            role = ""
        if not executable:
            self._record("SELL_NO_FILL", symbol, price=self._daily_marker_price(symbol))
            return None
        price = self._minute_price(symbol, role, "pre_adj_close")
        position = self.positions.pop(symbol, None)
        if position is None:
            raise ReproductionError(f"SMV6 sell without position: {symbol}")
        self._record("SELL_FILLED", symbol, price=price, entry_date=position.entry_date, entry_price=position.entry_price, holding_pnl_pct=price / position.entry_price - 1)
        return f"shadow-{self.event_stage}-{symbol}-{self.current_date.isoformat()}"


def affordable_lot_quantity(
    cash: float, fill_price: float, commission_rate: float, lot_size: int
) -> int:
    """Maximum long quantity whose price plus commission fits available cash."""
    if fill_price <= 0 or commission_rate < 0 or lot_size <= 0:
        raise ValueError("invalid long-only affordability contract")
    if cash <= 0:
        return 0
    unit_cost = fill_price * (1 + commission_rate)
    return max(0, math.floor((cash / unit_cost) / lot_size) * lot_size)


class CashPlatform(ShadowPlatform):
    """The same callbacks with deterministic cash, fee, and round-lot fills."""

    def __init__(self, *args: object, initial_cash: float, lot_size: int, fee_bps: float, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.cash = initial_cash
        self.initial_cash = initial_cash
        self.lot_size = lot_size
        self.commission_rate = fee_bps / 10_000
        self.shares: dict[str, int] = {}
        self.accounts: list[dict[str, object]] = []

    def _mark(self, symbol: str, stage: str) -> float:
        role = "OPEN_BAR_09_30" if stage == "open" else "FINAL_CLOSE_BAR"
        value = self._minute_price(symbol, role, "pre_adj_close")
        return value if np.isfinite(value) else self._daily_marker_price(symbol)

    def nav(self, stage: str) -> float:
        return self.cash + sum(qty * self._mark(symbol, stage) for symbol, qty in self.shares.items())

    def _fill_price(self, raw_price: float, side: int) -> float:
        return raw_price * (1 + side * self.slippage_total / 2)

    def _volume_cap(self, symbol: str, role: str) -> int:
        shares = self._minute_volume(symbol, role) * self.minute_volume_limit
        return math.floor(shares / self.lot_size) * self.lot_size

    def order_target_percent(self, symbol: str, target_weight: float) -> object | None:
        row = self._current_row(symbol)
        if self.event_stage != "open" or row is None or not bool(row.executable_09_30):
            self._record("BUY_OR_REBALANCE_NO_FILL", symbol, price=self._daily_marker_price(symbol), target_weight=float(target_weight), reject_reason="NOT_EXECUTABLE")
            return None
        mark_price = self._mark(symbol, "open")
        current = self.shares.get(symbol, 0)
        desired = math.floor((self.nav("open") * target_weight / mark_price) / self.lot_size) * self.lot_size
        delta = desired - current
        volume_cap = self._volume_cap(symbol, "OPEN_BAR_09_30")
        delta = max(-volume_cap, min(delta, volume_cap))
        side = 1 if delta >= 0 else -1
        price = self._fill_price(mark_price, side)
        cash_limited = False
        affordable = 0
        if delta > 0:
            affordable = affordable_lot_quantity(
                self.cash, price, self.commission_rate, self.lot_size
            )
            cash_limited = delta > affordable
            delta = min(delta, affordable)
        if delta == 0 and current == 0:
            self._record(
                "BUY_OR_REBALANCE_NO_FILL", symbol, price=mark_price,
                target_weight=float(target_weight),
                reject_reason="INSUFFICIENT_CASH_LOT_OR_VOLUME",
                requested_qty=desired, cash_affordable_qty=affordable,
                cash_limited=cash_limited,
            )
            return None
        fee = abs(delta) * price * self.commission_rate
        self.cash -= delta * price + fee
        if self.cash < -1e-8:
            raise ReproductionError(f"SMV6 cash invariant violated: {self.cash}")
        new_qty = current + delta
        kind = "BUY_FILLED" if current == 0 else "REBALANCE_FILLED"
        if current == 0:
            self.positions[symbol] = Position(symbol, float(target_weight), self.current_date, price)
        else:
            self.positions[symbol].target_weight = float(target_weight)
        self.shares[symbol] = new_qty
        self._record(kind, symbol, price=price, market_price=mark_price, target_weight=float(target_weight), requested_qty=desired, filled_delta_qty=delta, position_qty=new_qty, volume_cap_qty=volume_cap, cash_affordable_qty=affordable, cash_limited=cash_limited, fee=fee, cash_after=self.cash)
        return f"local-cash-open-{symbol}-{self.current_date.isoformat()}"

    def order_target(self, symbol: str, target: float) -> object | None:
        if target != 0:
            raise ReproductionError("SMV6 local runtime supports liquidation target only")
        row = self._current_row(symbol)
        if row is None:
            self._record("SELL_NO_FILL", symbol, price=self._daily_marker_price(symbol), reject_reason="NO_ROW")
            return None
        executable = bool(row.executable_09_30) if self.event_stage == "open" else bool(row.executable_15_00)
        if not executable:
            self._record("SELL_NO_FILL", symbol, price=self._daily_marker_price(symbol), reject_reason="NOT_EXECUTABLE")
            return None
        role = "OPEN_BAR_09_30" if self.event_stage == "open" else "FINAL_CLOSE_BAR"
        mark_price = self._mark(symbol, self.event_stage)
        price = self._fill_price(mark_price, -1)
        position = self.positions[symbol]
        current = self.shares[symbol]
        volume_cap = self._volume_cap(symbol, role)
        qty = min(current, volume_cap)
        if qty == 0:
            self._record("SELL_NO_FILL", symbol, price=mark_price, reject_reason="ZERO_EXECUTABLE_VOLUME")
            return None
        fee = qty * price * self.commission_rate
        self.cash += qty * price - fee
        remaining = current - qty
        if remaining:
            self.shares[symbol] = remaining
            event_type = "SELL_PARTIAL"
        else:
            self.positions.pop(symbol)
            self.shares.pop(symbol)
            event_type = "SELL_FILLED"
        self._record(event_type, symbol, price=price, market_price=mark_price, entry_date=position.entry_date, entry_price=position.entry_price, holding_pnl_pct=price / position.entry_price - 1, filled_delta_qty=-qty, position_qty=remaining, volume_cap_qty=volume_cap, fee=fee, cash_after=self.cash)
        return f"local-cash-{self.event_stage}-{symbol}-{self.current_date.isoformat()}"

    def record_account(self) -> None:
        nav = self.nav("eod")
        exposure = nav - self.cash
        if self.cash < -1e-10 or exposure > nav + 1e-10:
            raise ReproductionError("SMV6 financing invariant violated")
        self.accounts.append({"trade_date": self.current_date, "nav": nav, "cash": self.cash, "gross_exposure": exposure, "cash_weight": self.cash / nav, "gross_exposure_ratio": exposure / nav, "position_count": len(self.positions)})


def frozen_namespace(platform: ShadowPlatform) -> dict[str, Any]:
    if source_sha256() != FROZEN_SHA256:
        raise ReproductionError("SMV6 frozen source SHA256 drift")
    namespace: dict[str, Any] = {
        "np": np,
        "pd": pd,
        "log": QuietLog(),
        "set_benchmark": lambda *_: None,
        "set_commission": lambda value: setattr(platform, "commission_rate", float(value["cost"])),
        "set_slippage": lambda value: setattr(platform, "slippage_total", float(value)),
        "set_volume_limit": lambda daily, minute: (
            setattr(platform, "daily_volume_limit", float(daily)),
            setattr(platform, "minute_volume_limit", float(minute)),
        ),
        "set_execution": lambda *_: None,
        "enable_open_bar": lambda *_: None,
        "PerShare": lambda **kwargs: kwargs,
        "PriceSlippage": float,
        "history": platform.history,
        "get_all_securities": platform.get_all_securities,
        "get_trade_days": platform.get_trade_days,
        "get_datetime": lambda: pd.Timestamp(platform.current_date).to_pydatetime(),
        "order_target_percent": platform.order_target_percent,
        "order_target": platform.order_target,
    }
    source = FROZEN_SOURCE.read_text(encoding="utf-8")
    exec(compile(source, str(FROZEN_SOURCE), "exec"), namespace)
    return namespace


def record_pending_signals(platform: ShadowPlatform, context: SimpleNamespace, prior_holdings: set[str]) -> None:
    if context.pending_desired is None:
        return
    for symbol in context.pending_desired:
        if symbol not in prior_holdings:
            platform._record("BUY_SIGNAL", symbol, reason=context.pending_reason, signal_date=(pd.Timestamp(platform.current_date) - pd.Timedelta(days=1)).date())


def _run_callbacks(platform: ShadowPlatform, calendar: list[pd.Timestamp], *, account: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    namespace = frozen_namespace(platform)
    context = SimpleNamespace(portfolio=SimpleNamespace(stock_account=SimpleNamespace(positions=platform.positions)))
    namespace["init"](context)
    for timestamp in calendar:
        platform.current_date = timestamp.date()
        platform.event_stage = "before_trading"
        prior = set(platform.positions)
        namespace["before_trading"](context)
        record_pending_signals(platform, context, prior)
        platform.event_stage = "open"
        namespace["execute_pending_open"](context, platform.bar_dict(), "LOCAL_09_30")
        platform.event_stage = "signal"
        namespace["run_1457_exit_signal"](context, platform.bar_dict(include_signal=True))
        for symbol in context.pending_close_sells:
            platform._record("TAIL_SELL_SIGNAL", symbol, price=platform._minute_price(symbol, "PSEUDO_CLOSE_14_57_OPEN", "pre_adj_open"), reason=context.pending_close_reason)
        platform.event_stage = "close"
        namespace["execute_pending_close_sells"](context, platform.bar_dict(include_close=True))
        if account:
            assert isinstance(platform, CashPlatform)
            platform.record_account()
    events = pd.DataFrame(platform.events).sort_values(["trade_date", "symbol", "event_type"]).reset_index(drop=True)
    accounts = pd.DataFrame(platform.accounts) if isinstance(platform, CashPlatform) else pd.DataFrame()
    return events, accounts


def run_local(
    qmt_root: Path,
    hybrid_root: Path,
    *,
    start: date,
    end: date,
    initial_cash: float = 1_000_000,
    lot_size: int = 100,
    fee_bps: float = 0,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    symbols = [canonical_symbol(code) for code in raw_pool()] + ["000852.SH"]
    daily = {symbol: load_daily(qmt_root, symbol) for symbol in symbols}
    minute = {symbol: load_minute(hybrid_root, symbol) for symbol in symbols}
    availability = pd.read_parquet(hybrid_root / "execution_availability" / "critical_execution.parquet")
    availability["trade_date"] = pd.to_datetime(availability.trade_date).dt.date
    availability = availability.loc[availability.trade_date.between(start, end)].copy()
    calendar = [ts for ts in daily["000852.SH"].index if start <= ts.date() <= end and np.isfinite(daily["000852.SH"].loc[ts, "pre_adj_close"])]
    if not calendar:
        raise ReproductionError("SMV6 has no valid sessions in requested interval")
    shadow = ShadowPlatform(daily, minute, availability, calendar)
    strategy_events, _ = _run_callbacks(shadow, calendar, account=False)
    cash = CashPlatform(daily, minute, availability, calendar, initial_cash=initial_cash, lot_size=lot_size, fee_bps=fee_bps)
    local_events, accounts = _run_callbacks(cash, calendar, account=True)
    if (cash.commission_rate, cash.slippage_total, cash.minute_volume_limit) != (0.0002, 0.0016, 0.5):
        raise ReproductionError("SMV6 frozen execution settings were not applied")
    if accounts.cash.min() < -1e-8:
        raise ReproductionError("SMV6 negative cash")
    return strategy_events, local_events, accounts
