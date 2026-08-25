from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

from cyq_game.domain import ChipLifecycleState, ExitReason, StrategyFamily
from cyq_game.game.decision import EdgeCard
from cyq_game.strategy.execution import (
    EntryExecutionStatus,
    ExecutionReason,
    ExecutionScope,
    ExecutionWindow,
    ExitExecutionStatus,
    ExitIntent,
    execute_entry,
    execute_exit,
)
from cyq_game.strategy.markup_retest import (
    ChipMassMethod,
    ExecutionSettings,
    StrategySignal,
)

CN_TZ = timezone(timedelta(hours=8))


def _settings(*, nominal: float = 100_000.0) -> ExecutionSettings:
    return ExecutionSettings(
        decision_time=time(15, 30, tzinfo=CN_TZ),
        next_window_end=time(9, 35, tzinfo=CN_TZ),
        max_entry_wait_trading_days=3,
        nominal_capital_per_signal=nominal,
        fee_bps=5.0,
        slippage_bps=10.0,
        impact_bps=5.0,
    )


def _edge_card() -> EdgeCard:
    return EdgeCard(
        edge_source="oos evidence",
        counterparty_state="latent sticky-capital hypothesis",
        why_they_act_now="retest support",
        why_edge_persists="cost migration is slow",
        expected_payoff_r=1.2,
        capacity_fraction_adv=0.01,
        adversarial_response="false breakout",
        expiry_rule="twenty trading days",
        invalidation="support breaks",
        falsifiable_explanations=("passive flow alternative",),
        evidence_for=("oos calibration",),
        evidence_against=("crowding risk",),
    )


def _signal(
    *,
    symbol: str = "000001.SZ",
    signal_date: date = date(2020, 6, 15),
    authorized: bool = True,
) -> StrategySignal:
    decision_at = datetime.combine(signal_date, time(15, 30), CN_TZ)
    return StrategySignal(
        signal_id=f"signal-{symbol}-{signal_date.isoformat()}",
        symbol=symbol,
        decision_at=decision_at,
        strategy_version="v1",
        strategy_family=StrategyFamily.MARKUP_RETEST,
        lifecycle_state=ChipLifecycleState.RETEST_READY,
        accumulation_started_at=signal_date - timedelta(days=20),
        breakout_at=signal_date - timedelta(days=2),
        retest_confirmed_at=signal_date,
        anchor_created_at=signal_date - timedelta(days=20),
        anchor_lower=9.5,
        anchor_upper=10.5,
        anchor_reference_mass=1.0,
        anchor_retention=0.8,
        anchor_mass_method=ChipMassMethod.HISTOGRAM_EXACT,
        evidence_for=("cost center moved up",),
        evidence_against=("market risk",),
        market_state="RISK_ON",
        sector_state="STRONG",
        alternative_explanations=("passive flow",),
        available_at=decision_at,
        snapshot_ids=("daily-snapshot", "chip-snapshot"),
        hard_valid=True,
        pit_grade="B_RESEARCH_ONLY",
        industry_pit_grade="B_RESEARCH_ONLY",
        parameter_id="parameters-v1",
        edge_card=_edge_card() if authorized else None,
        execution_status=("READY_FOR_NEXT_WINDOW" if authorized else "BLOCKED_UNCALIBRATED"),
        unfilled_reason=None if authorized else "OOS_CALIBRATION_REQUIRED",
    )


def _window(
    trade_date: date,
    *,
    index: int = 0,
    symbol: str = "000001.SZ",
    price: float = 10.0,
    up_limit: float = 11.0,
    hard_valid: bool = True,
    down_limit: float = 9.0,
    corporate_action_blocking: bool = False,
) -> ExecutionWindow:
    available_at = datetime.combine(
        trade_date, time(9, 35 + index * 5), CN_TZ
    )
    volume = 10_000.0
    return ExecutionWindow(
        symbol=symbol,
        trade_date=trade_date,
        window_index=index,
        available_at=available_at,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=volume,
        amount=price * volume,
        trade_status=1,
        up_limit_price=up_limit,
        down_limit_price=down_limit,
        market_rule_valid=True,
        hard_valid=hard_valid,
        snapshot_id=f"minute-{symbol}-{trade_date}-{index}",
        daily_snapshot_id=f"daily-{symbol}-{trade_date}",
        corporate_action_blocking=corporate_action_blocking,
    )


def _exit_intent(
    *,
    intent_date: date = date(2020, 6, 15),
    quantity: int = 10_000,
    reference_price: float = 10.0,
) -> ExitIntent:
    decision_at = datetime.combine(intent_date, time(15, 30), CN_TZ)
    return ExitIntent(
        intent_id=f"exit-000001.SZ-{intent_date.isoformat()}",
        signal_id="signal-000001.SZ-2020-06-01",
        symbol="000001.SZ",
        decision_at=decision_at,
        reason=ExitReason.DISTRIBUTION_CONFIRMED,
        quantity=quantity,
        reference_price=reference_price,
        available_at=decision_at,
        snapshot_ids=("exit-daily", "exit-chip"),
        hard_valid=True,
    )


def test_signal_never_fills_same_day_and_fills_next_legal_window() -> None:
    signal = _signal()
    same_day = _window(date(2020, 6, 15))
    next_day = _window(date(2020, 6, 16))

    result = execute_entry(
        signal,
        (same_day, next_day),
        market_trading_dates=(date(2020, 6, 15), date(2020, 6, 16)),
        settings=_settings(),
    )

    assert result.status == EntryExecutionStatus.FILLED
    assert result.fill_at == next_day.available_at
    assert result.attempted_trading_dates == (date(2020, 6, 16),)
    assert result.attempts[0].reason_codes == (
        ExecutionReason.SAME_DAY_FILL_FORBIDDEN.value,
    )
    assert result.attempts[-1].reason_codes == (
        ExecutionReason.FILLED_NEXT_LEGAL_WINDOW.value,
    )


def test_pinned_up_limit_moves_to_later_legal_five_minute_window() -> None:
    first = _window(date(2020, 6, 16), price=11.0, up_limit=11.0)
    second = _window(date(2020, 6, 16), index=1)

    result = execute_entry(
        _signal(),
        (first, second),
        market_trading_dates=(date(2020, 6, 16),),
        settings=_settings(),
    )

    assert result.status == EntryExecutionStatus.FILLED
    assert result.fill_at == second.available_at
    assert ExecutionReason.BUY_LIQUIDITY_BLOCKED_AT_UP_LIMIT.value in (
        result.attempts[0].reason_codes
    )


def test_three_complete_market_days_fail_explicitly() -> None:
    trading_dates = (date(2020, 6, 16), date(2020, 6, 17), date(2020, 6, 18))

    result = execute_entry(
        _signal(),
        (),
        market_trading_dates=trading_dates,
        settings=_settings(),
    )

    assert result.status == EntryExecutionStatus.FAILED
    assert result.attempted_trading_dates == trading_dates
    assert len(result.attempts) == 3
    assert all(
        attempt.reason_codes == (ExecutionReason.MISSING_EXECUTION_WINDOW.value,)
        for attempt in result.attempts
    )
    assert ExecutionReason.THREE_DAY_EXECUTION_FAILURE.value in result.reason_codes


def test_incomplete_future_calendar_remains_pending() -> None:
    result = execute_entry(
        _signal(),
        (),
        market_trading_dates=(date(2020, 6, 16), date(2020, 6, 17)),
        settings=_settings(),
    )

    assert result.status == EntryExecutionStatus.PENDING
    assert result.reason_codes[-1] == ExecutionReason.INSUFFICIENT_MARKET_CALENDAR.value


def test_uncalibrated_signal_is_never_sent_to_execution() -> None:
    result = execute_entry(
        _signal(authorized=False),
        (_window(date(2020, 6, 16)),),
        market_trading_dates=(date(2020, 6, 16),),
        settings=_settings(),
    )

    assert result.status == EntryExecutionStatus.BLOCKED_SIGNAL
    assert result.reason_codes == (ExecutionReason.SIGNAL_NOT_AUTHORIZED.value,)


def test_uncalibrated_signal_is_filled_only_in_research_event_scope() -> None:
    result = execute_entry(
        _signal(authorized=False),
        (_window(date(2020, 6, 16)),),
        market_trading_dates=(date(2020, 6, 16),),
        settings=_settings(),
        scope=ExecutionScope.RESEARCH_EVENT_STUDY,
    )

    assert result.status == EntryExecutionStatus.FILLED
    assert result.scope == ExecutionScope.RESEARCH_EVENT_STUDY
    assert result.fill_at is not None


def test_research_scope_still_rejects_invalid_signal() -> None:
    invalid = StrategySignal(**{**_signal(authorized=False).__dict__, "hard_valid": False})

    result = execute_entry(
        invalid,
        (_window(date(2020, 6, 16)),),
        market_trading_dates=(date(2020, 6, 16),),
        settings=_settings(),
        scope=ExecutionScope.RESEARCH_EVENT_STUDY,
    )

    assert result.status == EntryExecutionStatus.BLOCKED_SIGNAL
    assert result.reason_codes == (ExecutionReason.RESEARCH_SIGNAL_INVALID.value,)


def test_every_signal_is_evaluated_at_equal_nominal_without_capacity_truncation() -> None:
    first = execute_entry(
        _signal(symbol="000001.SZ"),
        (_window(date(2020, 6, 16), symbol="000001.SZ"),),
        market_trading_dates=(date(2020, 6, 16),),
        settings=_settings(),
    )
    second = execute_entry(
        _signal(symbol="600000.SH"),
        (_window(date(2020, 6, 16), symbol="600000.SH"),),
        market_trading_dates=(date(2020, 6, 16),),
        settings=_settings(),
    )

    assert first.status == second.status == EntryExecutionStatus.FILLED
    assert first.quantity == second.quantity
    assert first.total_cash == pytest.approx(second.total_cash)


def test_invalid_price_units_are_rejected_instead_of_repaired() -> None:
    bad = _window(date(2020, 6, 16))
    bad = ExecutionWindow(
        **{
            **bad.__dict__,
            "amount": bad.amount * 100.0,
        }
    )

    result = execute_entry(
        _signal(),
        (bad,),
        market_trading_dates=(date(2020, 6, 16),),
        settings=_settings(),
    )

    assert result.status == EntryExecutionStatus.PENDING
    assert ExecutionReason.VWAP_OUTSIDE_BAR.value in result.reason_codes


def test_nominal_below_one_board_lot_is_a_recorded_failure() -> None:
    result = execute_entry(
        _signal(),
        (_window(date(2020, 6, 16), price=1000.0, up_limit=1100.0),),
        market_trading_dates=(
            date(2020, 6, 16),
            date(2020, 6, 17),
            date(2020, 6, 18),
        ),
        settings=_settings(nominal=10_000.0),
    )

    assert result.status == EntryExecutionStatus.FAILED
    assert ExecutionReason.NOMINAL_BELOW_ONE_LOT.value in result.reason_codes


def test_exit_waits_through_lower_limit_and_fills_later_window() -> None:
    pinned = _window(
        date(2020, 6, 16), price=9.0, up_limit=11.0, down_limit=9.0
    )
    legal = _window(date(2020, 6, 17), price=9.4, down_limit=8.1)

    result = execute_exit(
        _exit_intent(),
        (pinned, legal),
        market_trading_dates=(date(2020, 6, 16), date(2020, 6, 17)),
        settings=_settings(),
    )

    assert result.status == ExitExecutionStatus.FILLED
    assert result.fill_at == legal.available_at
    assert ExecutionReason.SELL_LIQUIDITY_BLOCKED_AT_DOWN_LIMIT.value in (
        result.attempts[0].reason_codes
    )
    assert result.blocked_tail_loss > 0


def test_unfilled_exit_remains_pending_and_records_tail_loss() -> None:
    pinned = _window(
        date(2020, 6, 16), price=8.0, up_limit=11.0, down_limit=8.0
    )

    result = execute_exit(
        _exit_intent(reference_price=10.0),
        (pinned,),
        market_trading_dates=(date(2020, 6, 16),),
        settings=_settings(),
    )

    assert result.status == ExitExecutionStatus.PENDING
    assert result.blocked_tail_loss == pytest.approx(20_000.0)
    assert result.reason_codes[-1] == ExecutionReason.EXIT_PENDING_BLOCKED.value


def test_corporate_action_block_does_not_prevent_risk_reducing_exit() -> None:
    legal = _window(
        date(2020, 6, 16),
        corporate_action_blocking=True,
    )

    result = execute_exit(
        _exit_intent(),
        (legal,),
        market_trading_dates=(date(2020, 6, 16),),
        settings=_settings(),
    )

    assert result.status == ExitExecutionStatus.FILLED


def test_exit_cannot_fill_inside_signal_day() -> None:
    same_day = _window(date(2020, 6, 15))
    next_day = _window(date(2020, 6, 16))

    result = execute_exit(
        _exit_intent(),
        (same_day, next_day),
        market_trading_dates=(date(2020, 6, 15), date(2020, 6, 16)),
        settings=_settings(),
    )

    assert result.status == ExitExecutionStatus.FILLED
    assert result.fill_at == next_day.available_at
    assert result.attempts[0].reason_codes == (
        ExecutionReason.SAME_DAY_FILL_FORBIDDEN.value,
    )
