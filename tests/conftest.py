from __future__ import annotations

from datetime import UTC, date, datetime, time

from cyq_game.domain import Bar

UTC = UTC


def make_bar(
    trade_date: date,
    *,
    symbol: str = "000001.SZ",
    price: float = 10.0,
    amount: float = 1_000_000.0,
    volume: float = 100_000.0,
    suspended: bool = False,
    limit_up: float | None = None,
    limit_down: float | None = None,
    available_at: datetime | None = None,
) -> Bar:
    return Bar(
        symbol=symbol,
        trade_date=trade_date,
        open=price,
        high=price * 1.02,
        low=price * 0.98,
        close=price * 1.01,
        volume=volume,
        amount=amount,
        free_float_shares=10_000_000.0,
        available_at=available_at
        or datetime.combine(trade_date, time(15, 30), tzinfo=UTC),
        suspended=suspended,
        limit_up=limit_up,
        limit_down=limit_down,
    )
