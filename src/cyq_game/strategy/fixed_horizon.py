"""Exact fixed-session attribution with the canonical five-minute executor."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from cyq_game.domain import ChipLifecycleState, ExitReason, StrategyFamily
from cyq_game.strategy.execution import (
    EntryExecutionStatus,
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


@dataclass(frozen=True)
class PanelSession:
    symbol: str
    trade_date: date
    decision_at: datetime
    available_at: datetime
    close: float
    share_multiplier: float
    cash_per_share: float
    snapshot_ids: tuple[str, ...]


@dataclass(frozen=True)
class FixedHorizonTrade:
    signal_id: str
    symbol: str
    signal_date: date
    status: str
    entry_at: datetime | None = None
    entry_price: float | None = None
    entry_cash: float = 0.0
    entry_quantity: int = 0
    entry_participation: float | None = None
    scheduled_exit_date: date | None = None
    exit_at: datetime | None = None
    exit_price: float | None = None
    exit_quantity: int = 0
    dividends: float = 0.0
    net_pnl: float | None = None
    return_fraction: float | None = None
    blocked_tail_loss: float = 0.0
    reason_codes: tuple[str, ...] = ()
    snapshot_ids: tuple[str, ...] = ()


def evaluate_fixed_horizon_trade(
    *,
    signal_id: str,
    symbol: str,
    signal_date: date,
    signal_decision_at: datetime,
    signal_available_at: datetime,
    signal_snapshot_ids: Sequence[str],
    sessions: Sequence[PanelSession],
    windows: Sequence[ExecutionWindow],
    market_trading_dates: Sequence[date],
    settings: ExecutionSettings,
    strategy_version: str,
    parameter_id: str,
    horizon_sessions: int = 20,
) -> FixedHorizonTrade:
    """Enter after the signal and target the 20th market session after entry.

    The exit intent is formed after the close immediately before the target
    session. The canonical exit executor then keeps the sell pending if the
    target 09:35 window is not legally executable.
    """

    if horizon_sessions < 1:
        raise ValueError("fixed horizon must contain at least one session")
    ordered_dates = tuple(sorted(dict.fromkeys(market_trading_dates)))
    ordered_sessions = tuple(sorted(sessions, key=lambda item: item.trade_date))
    if any(item.symbol != symbol for item in ordered_sessions):
        raise ValueError("fixed-horizon sessions must contain exactly one symbol")
    by_date = {item.trade_date: item for item in ordered_sessions}
    if len(by_date) != len(ordered_sessions):
        raise ValueError("fixed-horizon sessions contain duplicate symbol dates")
    signal = _research_signal(
        signal_id=signal_id,
        symbol=symbol,
        signal_date=signal_date,
        decision_at=signal_decision_at,
        available_at=signal_available_at,
        snapshot_ids=signal_snapshot_ids,
        strategy_version=strategy_version,
        parameter_id=parameter_id,
    )
    entry = execute_entry(
        signal,
        windows,
        market_trading_dates=ordered_dates,
        settings=settings,
        scope=ExecutionScope.RESEARCH_EVENT_STUDY,
    )
    if entry.status != EntryExecutionStatus.FILLED:
        return FixedHorizonTrade(
            signal_id=signal_id,
            symbol=symbol,
            signal_date=signal_date,
            status=f"ENTRY_{entry.status.value}",
            reason_codes=entry.reason_codes,
            snapshot_ids=entry.snapshot_ids,
        )
    if entry.fill_at is None or entry.fill_price is None:
        raise RuntimeError("canonical filled entry omitted fill fields")
    entry_date = entry.fill_at.date()
    future_dates = tuple(item for item in ordered_dates if item > entry_date)
    if len(future_dates) < horizon_sessions:
        return _pending_after_entry(
            signal_id=signal_id,
            symbol=symbol,
            signal_date=signal_date,
            entry=entry,
            participation=_entry_participation(entry.fill_at, entry.quantity, windows),
            status="EXIT_HORIZON_NOT_OBSERVED",
        )
    target_date = future_dates[horizon_sessions - 1]
    intent_date = entry_date if horizon_sessions == 1 else future_dates[horizon_sessions - 2]
    intent_session = by_date.get(intent_date)
    if intent_session is None:
        return _pending_after_entry(
            signal_id=signal_id,
            symbol=symbol,
            signal_date=signal_date,
            entry=entry,
            participation=_entry_participation(entry.fill_at, entry.quantity, windows),
            status="EXIT_INTENT_SESSION_MISSING",
            scheduled_exit_date=target_date,
        )
    quantity, dividends, action_snapshots = _apply_actions(
        entry.quantity,
        ordered_sessions,
        after=entry_date,
        through=intent_date,
    )
    intent = ExitIntent(
        intent_id=_digest(
            f"FIXED_HORIZON|{signal_id}|{intent_session.decision_at.isoformat()}|"
            f"{horizon_sessions}"
        ),
        signal_id=signal_id,
        symbol=symbol,
        decision_at=intent_session.decision_at,
        reason=ExitReason.MAX_HOLDING_PERIOD,
        quantity=quantity,
        reference_price=intent_session.close,
        available_at=intent_session.available_at,
        snapshot_ids=intent_session.snapshot_ids,
        hard_valid=True,
    )
    exit_execution = execute_exit(
        intent,
        windows,
        market_trading_dates=ordered_dates,
        settings=settings,
    )
    participation = _entry_participation(entry.fill_at, entry.quantity, windows)
    if exit_execution.status != ExitExecutionStatus.FILLED:
        return FixedHorizonTrade(
            signal_id=signal_id,
            symbol=symbol,
            signal_date=signal_date,
            status=f"EXIT_{exit_execution.status.value}",
            entry_at=entry.fill_at,
            entry_price=entry.fill_price,
            entry_cash=entry.total_cash,
            entry_quantity=entry.quantity,
            entry_participation=participation,
            scheduled_exit_date=target_date,
            exit_quantity=quantity,
            dividends=dividends,
            blocked_tail_loss=exit_execution.blocked_tail_loss,
            reason_codes=exit_execution.reason_codes,
            snapshot_ids=_unique(
                (*entry.snapshot_ids, *action_snapshots, *exit_execution.snapshot_ids)
            ),
        )
    if exit_execution.fill_at is None:
        raise RuntimeError("canonical filled exit omitted fill_at")
    adjusted_quantity, later_dividends, later_snapshots = _apply_actions(
        quantity,
        ordered_sessions,
        after=intent_date,
        through=exit_execution.fill_at.date(),
    )
    adjusted_intent = ExitIntent(
        intent_id=intent.intent_id,
        signal_id=intent.signal_id,
        symbol=intent.symbol,
        decision_at=intent.decision_at,
        reason=intent.reason,
        quantity=adjusted_quantity,
        reference_price=intent.reference_price,
        available_at=intent.available_at,
        snapshot_ids=intent.snapshot_ids,
        hard_valid=intent.hard_valid,
    )
    exact_exit = execute_exit(
        adjusted_intent,
        windows,
        market_trading_dates=ordered_dates,
        settings=settings,
    )
    if (
        exact_exit.status != ExitExecutionStatus.FILLED
        or exact_exit.fill_at != exit_execution.fill_at
        or exact_exit.fill_price is None
    ):
        raise RuntimeError("corporate-action reconciliation changed fixed exit timing")
    total_dividends = dividends + later_dividends
    net_pnl = exact_exit.net_proceeds + total_dividends - entry.total_cash
    return FixedHorizonTrade(
        signal_id=signal_id,
        symbol=symbol,
        signal_date=signal_date,
        status="FILLED",
        entry_at=entry.fill_at,
        entry_price=entry.fill_price,
        entry_cash=entry.total_cash,
        entry_quantity=entry.quantity,
        entry_participation=participation,
        scheduled_exit_date=target_date,
        exit_at=exact_exit.fill_at,
        exit_price=exact_exit.fill_price,
        exit_quantity=exact_exit.quantity,
        dividends=total_dividends,
        net_pnl=net_pnl,
        return_fraction=net_pnl / entry.total_cash,
        blocked_tail_loss=exact_exit.blocked_tail_loss,
        reason_codes=exact_exit.reason_codes,
        snapshot_ids=_unique(
            (
                *entry.snapshot_ids,
                *action_snapshots,
                *later_snapshots,
                *exact_exit.snapshot_ids,
            )
        ),
    )


def panel_session_from_record(record: Mapping[str, Any]) -> PanelSession:
    return PanelSession(
        symbol=str(record["symbol"]),
        trade_date=_date(record["trade_date"]),
        decision_at=_datetime(record["decision_at"]),
        available_at=_datetime(record["available_at"]),
        close=float(record["close"]),
        share_multiplier=float(record.get("share_multiplier") or 1.0),
        cash_per_share=float(record.get("cash_per_share") or 0.0),
        snapshot_ids=_unique(
            str(record[name])
            for name in (
                "daily_snapshot_id",
                "feature_daily_snapshot_id",
                "feature_minute_snapshot_id",
                "corporate_action_snapshot_id",
            )
            if record.get(name)
        ),
    )


def _research_signal(
    *,
    signal_id: str,
    symbol: str,
    signal_date: date,
    decision_at: datetime,
    available_at: datetime,
    snapshot_ids: Sequence[str],
    strategy_version: str,
    parameter_id: str,
) -> StrategySignal:
    return StrategySignal(
        signal_id=signal_id,
        symbol=symbol,
        decision_at=decision_at,
        strategy_version=strategy_version,
        strategy_family=StrategyFamily.MARKUP_RETEST,
        lifecycle_state=ChipLifecycleState.RETEST_READY,
        accumulation_started_at=signal_date,
        breakout_at=signal_date,
        retest_confirmed_at=signal_date,
        anchor_created_at=signal_date,
        anchor_lower=1.0,
        anchor_upper=1.0,
        anchor_reference_mass=1.0,
        anchor_retention=1.0,
        anchor_mass_method=ChipMassMethod.HISTOGRAM_EXACT,
        evidence_for=("ELIGIBLE_FIXED_HORIZON_EVENT",),
        evidence_against=(),
        market_state="MATCHED",
        sector_state="MATCHED",
        alternative_explanations=(),
        available_at=available_at,
        snapshot_ids=tuple(snapshot_ids),
        hard_valid=True,
        pit_grade="B_RESEARCH_ONLY",
        industry_pit_grade="B_RESEARCH_ONLY",
        parameter_id=parameter_id,
        edge_card=None,
        execution_status="BLOCKED_UNCALIBRATED",
        unfilled_reason="RESEARCH_EVENT_STUDY_ONLY",
    )


def _apply_actions(
    quantity: int,
    sessions: Sequence[PanelSession],
    *,
    after: date,
    through: date,
) -> tuple[int, float, tuple[str, ...]]:
    current = quantity
    dividends = 0.0
    snapshots: list[str] = []
    for session in sessions:
        if session.trade_date <= after or session.trade_date > through:
            continue
        if session.share_multiplier == 1.0 and session.cash_per_share == 0.0:
            continue
        dividends += current * session.cash_per_share
        current = round(current * session.share_multiplier)
        snapshots.extend(session.snapshot_ids)
    return current, dividends, _unique(snapshots)


def _entry_participation(
    fill_at: datetime,
    quantity: int,
    windows: Sequence[ExecutionWindow],
) -> float:
    matched = [item for item in windows if item.available_at == fill_at]
    if len(matched) != 1 or matched[0].volume <= 0:
        raise ValueError("fixed entry fill must match exactly one positive-volume window")
    return quantity / matched[0].volume


def _pending_after_entry(
    *,
    signal_id: str,
    symbol: str,
    signal_date: date,
    entry: Any,
    participation: float,
    status: str,
    scheduled_exit_date: date | None = None,
) -> FixedHorizonTrade:
    return FixedHorizonTrade(
        signal_id=signal_id,
        symbol=symbol,
        signal_date=signal_date,
        status=status,
        entry_at=entry.fill_at,
        entry_price=entry.fill_price,
        entry_cash=entry.total_cash,
        entry_quantity=entry.quantity,
        entry_participation=participation,
        scheduled_exit_date=scheduled_exit_date,
        reason_codes=(status,),
        snapshot_ids=entry.snapshot_ids,
    )


def _unique(values: Sequence[str] | Any) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if value))


def _date(value: object) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _datetime(value: object) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
