from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

from cyq_game.strategy.execution import ExecutionWindow
from cyq_game.strategy.fixed_horizon import PanelSession, evaluate_fixed_horizon_trade
from cyq_game.strategy.markup_retest import ExecutionSettings

CN_TZ = timezone(timedelta(hours=8))


def _settings() -> ExecutionSettings:
    return ExecutionSettings(
        decision_time=time(15, 30, tzinfo=CN_TZ),
        next_window_end=time(9, 35, tzinfo=CN_TZ),
        max_entry_wait_trading_days=3,
        nominal_capital_per_signal=100_000.0,
        fee_bps=0.0,
        slippage_bps=0.0,
        impact_bps=0.0,
    )


def _window(
    day: date,
    price: float,
    *,
    down_limit: float = 1.0,
    volume: float = 100_000.0,
) -> ExecutionWindow:
    at = datetime.combine(day, time(9, 35), CN_TZ)
    return ExecutionWindow(
        symbol="000001.SZ",
        trade_date=day,
        window_index=0,
        available_at=at,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=volume,
        amount=volume * price,
        trade_status=1,
        up_limit_price=price * 1.1,
        down_limit_price=down_limit,
        market_rule_valid=True,
        hard_valid=True,
        snapshot_id=f"window-{day}",
        daily_snapshot_id=f"daily-{day}",
    )


def _session(
    day: date,
    *,
    close: float = 10.0,
    multiplier: float = 1.0,
    cash: float = 0.0,
) -> PanelSession:
    return PanelSession(
        symbol="000001.SZ",
        trade_date=day,
        decision_at=datetime.combine(day, time(15, 30), CN_TZ),
        available_at=datetime.combine(day, time(15, 0), CN_TZ),
        close=close,
        share_multiplier=multiplier,
        cash_per_share=cash,
        snapshot_ids=(f"session-{day}",),
    )


def _evaluate(
    days: tuple[date, ...],
    sessions: tuple[PanelSession, ...],
    windows: tuple[ExecutionWindow, ...],
):
    return evaluate_fixed_horizon_trade(
        signal_id="signal",
        symbol="000001.SZ",
        signal_date=days[0],
        signal_decision_at=datetime.combine(days[0], time(15, 30), CN_TZ),
        signal_available_at=datetime.combine(days[0], time(15, 0), CN_TZ),
        signal_snapshot_ids=("signal-snapshot",),
        sessions=sessions,
        windows=windows,
        market_trading_dates=days,
        settings=_settings(),
        strategy_version="v1",
        parameter_id="parameter",
    )


def test_fixed_horizon_exits_in_twentieth_market_session_after_entry() -> None:
    start = date(2020, 1, 1)
    days = tuple(start + timedelta(days=index) for index in range(22))
    result = _evaluate(
        days,
        (_session(days[20]),),
        (_window(days[1], 10.0), _window(days[21], 12.0)),
    )

    assert result.status == "FILLED"
    assert result.entry_at is not None and result.entry_at.date() == days[1]
    assert result.scheduled_exit_date == days[21]
    assert result.exit_at is not None and result.exit_at.date() == days[21]
    assert result.return_fraction == pytest.approx(0.20)
    assert result.entry_participation == pytest.approx(0.10)


def test_fixed_horizon_exit_persists_after_blocked_target_window() -> None:
    start = date(2020, 1, 1)
    days = tuple(start + timedelta(days=index) for index in range(23))
    blocked = _window(days[21], 8.0, down_limit=8.0)
    result = _evaluate(
        days,
        (_session(days[20]),),
        (_window(days[1], 10.0), blocked, _window(days[22], 9.0)),
    )

    assert result.status == "FILLED"
    assert result.scheduled_exit_date == days[21]
    assert result.exit_at is not None and result.exit_at.date() == days[22]
    assert result.blocked_tail_loss == pytest.approx(10_000.0)
    assert result.return_fraction == pytest.approx(-0.10)


def test_fixed_horizon_reconciles_share_actions_and_cash_distributions() -> None:
    start = date(2020, 1, 1)
    days = tuple(start + timedelta(days=index) for index in range(22))
    result = _evaluate(
        days,
        (
            _session(days[10], close=5.0, multiplier=2.0, cash=1.0),
            _session(days[20], close=5.0),
        ),
        (_window(days[1], 10.0), _window(days[21], 6.0)),
    )

    assert result.status == "FILLED"
    assert result.entry_quantity == 10_000
    assert result.exit_quantity == 20_000
    assert result.dividends == pytest.approx(10_000.0)
    assert result.net_pnl == pytest.approx(30_000.0)
    assert result.return_fraction == pytest.approx(0.30)


def test_fixed_horizon_without_twenty_future_sessions_is_pending() -> None:
    start = date(2020, 1, 1)
    days = tuple(start + timedelta(days=index) for index in range(21))
    result = _evaluate(days, (), (_window(days[1], 10.0),))

    assert result.status == "EXIT_HORIZON_NOT_OBSERVED"
    assert result.exit_at is None
