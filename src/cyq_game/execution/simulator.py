from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_FLOOR, Decimal
from math import floor, sqrt
from uuid import uuid4

from cyq_game.config import ExecutionConfig
from cyq_game.domain import Bar, OrderSide, OrderStatus


@dataclass(frozen=True)
class MarketRule:
    rule_id: str
    effective_from: date
    effective_to: date | None
    price_limit_pct: float | None
    t_plus_one: bool
    lot_size: int
    known: bool = True

    def applies(self, trade_date: date) -> bool:
        return self.effective_from <= trade_date and (
            self.effective_to is None or trade_date <= self.effective_to
        )


@dataclass(frozen=True)
class Fill:
    order_id: str
    symbol: str
    trade_date: date
    side: OrderSide
    quantity: int
    price: float
    commission: float
    stamp_duty: float
    slippage: float
    impact: float
    participation: float

    @property
    def cash_delta(self) -> float:
        gross = self.quantity * self.price
        if self.side == OrderSide.BUY:
            return -(gross + self.commission + self.stamp_duty)
        return gross - self.commission - self.stamp_duty


@dataclass
class SimOrder:
    symbol: str
    side: OrderSide
    quantity: int
    signal_time: datetime
    earliest_fill_date: date
    max_participation: float
    plan_id: str
    order_id: str = field(default_factory=lambda: str(uuid4()))
    status: OrderStatus = OrderStatus.CREATED
    filled_quantity: int = 0
    reason: str | None = None

    @property
    def remaining(self) -> int:
        return self.quantity - self.filled_quantity


@dataclass
class TaxLot:
    quantity: int
    acquired_on: date
    cost: float


@dataclass(frozen=True)
class SplitAdjustment:
    symbol: str
    ratio: float
    quantity_before: int
    theoretical_quantity_after: float
    quantity_after: int
    fractional_entitlement: float
    cost_basis_before: float
    cost_basis_after: float
    unresolved_cost_basis: float
    allocation_method: str
    approximate: bool


@dataclass(frozen=True)
class SplitOrderAdjustment:
    order_id: str
    ratio: float
    quantity_before: int
    filled_quantity_before: int
    quantity_after: int
    filled_quantity_after: int


def apply_split_to_order(order: SimOrder, ratio: float) -> SplitOrderAdjustment:
    """Rebase a pending exchange order without changing its lifecycle state."""

    if ratio <= 0:
        raise ValueError("split ratio must be positive")
    ratio_decimal = Decimal(str(ratio))
    quantity_before = order.quantity
    filled_before = order.filled_quantity
    quantity_after = int(
        (Decimal(quantity_before) * ratio_decimal).to_integral_value(rounding=ROUND_FLOOR)
    )
    filled_after = int(
        (Decimal(filled_before) * ratio_decimal).to_integral_value(rounding=ROUND_FLOOR)
    )
    order.quantity = quantity_after
    order.filled_quantity = min(filled_after, quantity_after)
    return SplitOrderAdjustment(
        order_id=order.order_id,
        ratio=ratio,
        quantity_before=quantity_before,
        filled_quantity_before=filled_before,
        quantity_after=order.quantity,
        filled_quantity_after=order.filled_quantity,
    )


_ALLOWED_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.CREATED: frozenset({OrderStatus.VALIDATED, OrderStatus.REJECTED}),
    OrderStatus.VALIDATED: frozenset({OrderStatus.SCHEDULED, OrderStatus.REJECTED}),
    OrderStatus.SCHEDULED: frozenset(
        {OrderStatus.SUBMITTED, OrderStatus.EXPIRED, OrderStatus.BLOCKED}
    ),
    OrderStatus.SUBMITTED: frozenset({OrderStatus.ACKNOWLEDGED, OrderStatus.REJECTED}),
    OrderStatus.ACKNOWLEDGED: frozenset(
        {OrderStatus.PARTIAL, OrderStatus.FILLED, OrderStatus.BLOCKED}
    ),
    OrderStatus.PARTIAL: frozenset(
        {
            OrderStatus.PARTIAL,
            OrderStatus.FILLED,
            OrderStatus.CANCEL_PENDING,
            OrderStatus.BLOCKED,
        }
    ),
    OrderStatus.CANCEL_PENDING: frozenset({OrderStatus.CANCELLED}),
}


class SimBroker:
    """Deterministic next-bar broker with A-share settlement constraints."""

    def __init__(self, config: ExecutionConfig, initial_cash: float) -> None:
        self.config = config
        self.cash = initial_cash
        self.orders: dict[str, SimOrder] = {}
        self.fills: list[Fill] = []
        self.lots: dict[str, list[TaxLot]] = {}

    def position(self, symbol: str) -> int:
        return sum(lot.quantity for lot in self.lots.get(symbol, []))

    def apply_split(self, symbol: str, ratio: float) -> SplitAdjustment:
        """Apply a split at account level and allocate integer shares to tax lots."""

        if ratio <= 0:
            raise ValueError("split ratio must be positive")
        lots = self.lots.get(symbol, [])
        ratio_decimal = Decimal(str(ratio))
        quantity_before = sum(lot.quantity for lot in lots)
        theoretical = Decimal(quantity_before) * ratio_decimal
        quantity_after = int(theoretical.to_integral_value(rounding=ROUND_FLOOR))
        fractional = theoretical - Decimal(quantity_after)
        cost_bases = [Decimal(lot.quantity) * Decimal(str(lot.cost)) for lot in lots]
        cost_basis_before = sum(cost_bases, Decimal(0))

        raw_quantities = [Decimal(lot.quantity) * ratio_decimal for lot in lots]
        allocated = [int(value.to_integral_value(rounding=ROUND_FLOOR)) for value in raw_quantities]
        remaining = quantity_after - sum(allocated)
        ranked = sorted(
            range(len(lots)),
            key=lambda index: (
                -(raw_quantities[index] - Decimal(allocated[index])),
                lots[index].acquired_on,
                index,
            ),
        )
        for index in ranked[:remaining]:
            allocated[index] += 1

        orphan_basis = sum(
            (
                basis
                for basis, new_quantity in zip(cost_bases, allocated, strict=True)
                if not new_quantity
            ),
            Decimal(0),
        )
        positive_indices = [index for index, new_quantity in enumerate(allocated) if new_quantity]
        if positive_indices and orphan_basis:
            cost_bases[positive_indices[0]] += orphan_basis

        adjusted_lots: list[TaxLot] = []
        for lot, new_quantity, cost_basis in zip(lots, allocated, cost_bases, strict=True):
            if new_quantity <= 0:
                continue
            adjusted_lots.append(
                TaxLot(
                    quantity=new_quantity,
                    acquired_on=lot.acquired_on,
                    cost=float(cost_basis / Decimal(new_quantity)),
                )
            )
        self.lots[symbol] = adjusted_lots
        cost_basis_after = sum(
            (Decimal(lot.quantity) * Decimal(str(lot.cost)) for lot in adjusted_lots),
            Decimal(0),
        )
        unresolved = (
            cost_basis_before
            if quantity_before > 0 and quantity_after == 0
            else Decimal(0)
        )
        return SplitAdjustment(
            symbol=symbol,
            ratio=ratio,
            quantity_before=quantity_before,
            theoretical_quantity_after=float(theoretical),
            quantity_after=quantity_after,
            fractional_entitlement=float(fractional),
            cost_basis_before=float(cost_basis_before),
            cost_basis_after=float(cost_basis_after),
            unresolved_cost_basis=float(unresolved),
            allocation_method="ACCOUNT_FLOOR_LARGEST_REMAINDER_NO_CASH_IN_LIEU",
            approximate=fractional != 0,
        )

    def apply_cash_dividend(self, symbol: str, cash_per_share: float) -> float:
        if cash_per_share < 0:
            raise ValueError("cash dividend cannot be negative")
        amount = self.position(symbol) * cash_per_share
        self.cash += amount
        return amount

    def sellable(self, symbol: str, on_date: date, rule: MarketRule) -> int:
        return sum(
            lot.quantity
            for lot in self.lots.get(symbol, [])
            if not rule.t_plus_one or lot.acquired_on < on_date
        )

    def submit(self, order: SimOrder, rule: MarketRule) -> SimOrder:
        self.orders[order.order_id] = order
        if not rule.known or rule.lot_size <= 0:
            order.reason = "UNKNOWN_MARKET_RULE"
            self._transition(order, OrderStatus.REJECTED)
            return order
        full_position_sale = (
            order.side == OrderSide.SELL
            and order.quantity == self.position(order.symbol)
        )
        if order.quantity <= 0 or (
            order.quantity % rule.lot_size != 0 and not full_position_sale
        ):
            order.reason = "INVALID_LOT_QUANTITY"
            self._transition(order, OrderStatus.REJECTED)
            return order
        if not 0.0 < order.max_participation <= 1.0:
            order.reason = "INVALID_PARTICIPATION"
            self._transition(order, OrderStatus.REJECTED)
            return order
        self._transition(order, OrderStatus.VALIDATED)
        self._transition(order, OrderStatus.SCHEDULED)
        return order

    def block(self, order: SimOrder, reason: str) -> SimOrder:
        """Fail-close a pending order before it reaches an execution bar."""

        if order.status not in {OrderStatus.SCHEDULED, OrderStatus.PARTIAL}:
            raise ValueError("only pending orders can be blocked")
        if not reason:
            raise ValueError("block reason must be non-empty")
        order.reason = reason
        self._transition(order, OrderStatus.BLOCKED)
        return order

    def process_bar(self, order: SimOrder, bar: Bar, rule: MarketRule) -> Fill | None:
        if order.status not in {OrderStatus.SCHEDULED, OrderStatus.PARTIAL}:
            return None
        if bar.trade_date < order.earliest_fill_date:
            return None
        if not rule.known or not rule.applies(bar.trade_date):
            order.reason = "UNKNOWN_OR_INEFFECTIVE_MARKET_RULE"
            self._transition(order, OrderStatus.BLOCKED)
            return None
        if bar.suspended:
            order.reason = "SUSPENDED"
            self._transition(order, OrderStatus.BLOCKED)
            return None
        if order.status == OrderStatus.SCHEDULED:
            self._transition(order, OrderStatus.SUBMITTED)
            self._transition(order, OrderStatus.ACKNOWLEDGED)
        if self._at_blocking_limit(order.side, bar):
            order.reason = "ONE_WAY_PRICE_LIMIT"
            self._transition(order, OrderStatus.BLOCKED)
            return None

        max_value = max(0.0, order.max_participation * bar.amount)
        reference = bar.open
        max_quantity = floor(max_value / max(reference, 1e-12) / rule.lot_size) * rule.lot_size
        quantity = min(order.remaining, max_quantity)
        if order.side == OrderSide.BUY:
            affordable = (
                floor(
                    self.cash
                    / max(reference * (1.0 + self.config.slippage_bps / 10_000.0), 1e-12)
                    / rule.lot_size
                )
                * rule.lot_size
            )
            quantity = min(quantity, affordable)
        else:
            quantity = min(quantity, self.sellable(order.symbol, bar.trade_date, rule))
        if quantity <= 0:
            order.reason = "NO_CAPACITY_OR_SETTLED_INVENTORY"
            self._transition(order, OrderStatus.BLOCKED)
            return None

        participation = quantity * reference / max(bar.amount, 1e-12)
        impact_pct = self.config.impact_coefficient * sqrt(participation) / 100.0
        slippage_pct = self.config.slippage_bps / 10_000.0
        direction = 1.0 if order.side == OrderSide.BUY else -1.0
        raw_price = reference * (1.0 + direction * (slippage_pct + impact_pct))
        price = min(bar.high, max(bar.low, raw_price))
        if bar.limit_up is not None:
            price = min(price, bar.limit_up)
        if bar.limit_down is not None:
            price = max(price, bar.limit_down)
        gross = quantity * price
        commission = gross * self.config.commission_bps / 10_000.0
        stamp = (
            gross * self.config.stamp_duty_sell_bps / 10_000.0
            if order.side == OrderSide.SELL
            else 0.0
        )
        fill = Fill(
            order_id=order.order_id,
            symbol=order.symbol,
            trade_date=bar.trade_date,
            side=order.side,
            quantity=quantity,
            price=price,
            commission=commission,
            stamp_duty=stamp,
            slippage=quantity * reference * slippage_pct,
            impact=quantity * reference * impact_pct,
            participation=participation,
        )
        self.cash += fill.cash_delta
        self._apply_inventory(fill)
        self.fills.append(fill)
        order.filled_quantity += quantity
        self._transition(
            order,
            OrderStatus.FILLED if order.remaining == 0 else OrderStatus.PARTIAL,
        )
        return fill

    @staticmethod
    def _at_blocking_limit(side: OrderSide, bar: Bar) -> bool:
        if side == OrderSide.BUY and bar.limit_up is not None:
            return bar.low >= bar.limit_up - 1e-10
        if side == OrderSide.SELL and bar.limit_down is not None:
            return bar.high <= bar.limit_down + 1e-10
        return False

    def _apply_inventory(self, fill: Fill) -> None:
        lots = self.lots.setdefault(fill.symbol, [])
        if fill.side == OrderSide.BUY:
            lots.append(TaxLot(fill.quantity, fill.trade_date, fill.price))
            return
        remaining = fill.quantity
        for lot in lots:
            take = min(lot.quantity, remaining)
            lot.quantity -= take
            remaining -= take
            if remaining == 0:
                break
        self.lots[fill.symbol] = [lot for lot in lots if lot.quantity > 0]
        if remaining:
            raise AssertionError("fill sold more inventory than available")

    @staticmethod
    def _transition(order: SimOrder, new_status: OrderStatus) -> None:
        allowed = _ALLOWED_TRANSITIONS.get(order.status, frozenset())
        if new_status not in allowed:
            raise ValueError(f"invalid order transition {order.status}->{new_status}")
        order.status = new_status
