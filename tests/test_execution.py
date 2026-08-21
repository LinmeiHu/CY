from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from conftest import make_bar

from cyq_game.config import ExecutionConfig
from cyq_game.domain import OrderSide, OrderStatus
from cyq_game.execution.simulator import (
    MarketRule,
    SimBroker,
    SimOrder,
    TaxLot,
    apply_split_to_order,
)

UTC = UTC


def _rule() -> MarketRule:
    return MarketRule("MAIN", date(2020, 1, 1), None, 0.10, True, 100)


def _order(side: OrderSide, trade_date: date, *, quantity: int = 500) -> SimOrder:
    return SimOrder(
        symbol="000001.SZ",
        side=side,
        quantity=quantity,
        signal_time=datetime(2024, 1, 1, 15, 30, tzinfo=UTC),
        earliest_fill_date=trade_date,
        max_participation=1.0,
        plan_id="p1",
    )


def test_t_plus_one_blocks_same_day_sale_and_allows_next_day() -> None:
    day1, day2 = date(2024, 1, 2), date(2024, 1, 3)
    broker = SimBroker(ExecutionConfig(), initial_cash=100_000.0)
    buy = broker.submit(_order(OrderSide.BUY, day1), _rule())
    assert broker.process_bar(buy, make_bar(day1), _rule()) is not None
    assert broker.position("000001.SZ") == 500

    same_day_sell = broker.submit(_order(OrderSide.SELL, day1), _rule())
    assert broker.process_bar(same_day_sell, make_bar(day1), _rule()) is None
    assert same_day_sell.status == OrderStatus.BLOCKED
    assert same_day_sell.reason == "NO_CAPACITY_OR_SETTLED_INVENTORY"

    next_day_sell = broker.submit(_order(OrderSide.SELL, day2), _rule())
    assert broker.process_bar(next_day_sell, make_bar(day2), _rule()) is not None
    assert next_day_sell.status == OrderStatus.FILLED
    assert broker.position("000001.SZ") == 0


def test_suspension_limit_and_partial_fill_are_explicit() -> None:
    day = date(2024, 1, 2)
    broker = SimBroker(ExecutionConfig(), initial_cash=100_000.0)
    suspended = broker.submit(_order(OrderSide.BUY, day), _rule())
    assert broker.process_bar(suspended, make_bar(day, suspended=True), _rule()) is None
    assert suspended.status == OrderStatus.BLOCKED and suspended.reason == "SUSPENDED"

    limit = broker.submit(_order(OrderSide.BUY, day), _rule())
    limit_bar = make_bar(day, price=11.0, limit_up=10.78)
    # Force all tradable prices to the upper limit: buy liquidity is one-way blocked.
    limit_bar = type(limit_bar)(
        **{
            **limit_bar.__dict__,
            "open": 10.78,
            "high": 10.78,
            "low": 10.78,
            "close": 10.78,
        }
    )
    assert broker.process_bar(limit, limit_bar, _rule()) is None
    assert limit.reason == "ONE_WAY_PRICE_LIMIT"

    partial = broker.submit(_order(OrderSide.BUY, day, quantity=500), _rule())
    partial.max_participation = 0.10
    fill = broker.process_bar(partial, make_bar(day, amount=20_000.0), _rule())
    assert fill is not None and fill.quantity == 200
    assert fill.participation == pytest.approx(0.10)
    assert partial.status == OrderStatus.PARTIAL


def test_unknown_rule_rejects_order() -> None:
    day = date(2024, 1, 2)
    unknown = MarketRule("UNKNOWN", day, day, None, True, 0, known=False)
    broker = SimBroker(ExecutionConfig(), initial_cash=100_000.0)
    order = broker.submit(_order(OrderSide.BUY, day), unknown)
    assert order.status == OrderStatus.REJECTED
    assert order.reason == "UNKNOWN_MARKET_RULE"


def test_fractional_split_uses_account_floor_and_preserves_cost_basis() -> None:
    broker = SimBroker(ExecutionConfig(), initial_cash=100_000.0)
    broker.lots["000001.SZ"] = [
        TaxLot(300, date(2022, 3, 1), 20.0),
        TaxLot(300, date(2022, 3, 2), 30.0),
    ]

    adjustment = broker.apply_split("000001.SZ", 1.1984546)

    assert adjustment.quantity_before == 600
    assert adjustment.theoretical_quantity_after == pytest.approx(719.07276)
    assert adjustment.quantity_after == 719
    assert adjustment.fractional_entitlement == pytest.approx(0.07276)
    assert adjustment.approximate is True
    assert broker.position("000001.SZ") == 719
    assert adjustment.cost_basis_after == pytest.approx(adjustment.cost_basis_before)
    assert adjustment.unresolved_cost_basis == 0.0


def test_full_odd_lot_position_can_be_liquidated() -> None:
    day = date(2024, 1, 3)
    broker = SimBroker(ExecutionConfig(), initial_cash=100_000.0)
    broker.lots["000001.SZ"] = [TaxLot(719, date(2024, 1, 2), 10.0)]

    sell = broker.submit(_order(OrderSide.SELL, day, quantity=719), _rule())
    fill = broker.process_bar(sell, make_bar(day, amount=1_000_000.0), _rule())

    assert fill is not None and fill.quantity == 719
    assert sell.status == OrderStatus.FILLED
    assert broker.position("000001.SZ") == 0


def test_split_rebases_pending_order_once_without_changing_status() -> None:
    day = date(2026, 5, 29)
    order = _order(OrderSide.BUY, day, quantity=500)
    order.status = OrderStatus.PARTIAL
    order.filled_quantity = 100

    adjustment = apply_split_to_order(order, 1.4)

    assert adjustment.quantity_before == 500
    assert adjustment.filled_quantity_before == 100
    assert order.quantity == 700
    assert order.filled_quantity == 140
    assert order.remaining == 560
    assert order.status == OrderStatus.PARTIAL
