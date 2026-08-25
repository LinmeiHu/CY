"""Auditable next-window execution for MARKUP_RETEST signals.

Every signal is evaluated against its own equal nominal capital.  This module
contains no portfolio cash, ranking, Top-N or capacity truncation.  A signal
formed after the close may only fill on a later market trading date.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, tzinfo
from enum import StrEnum
from math import floor, isfinite

from cyq_game.domain import ChipLifecycleState, ExitReason, StrategyFamily
from cyq_game.strategy.markup_retest import (
    ExecutionSettings,
    StrategySignal,
)


class ExecutionScope(StrEnum):
    """Separate outcome research from authorization for a real order."""

    FORMAL_ORDER = "FORMAL_ORDER"
    RESEARCH_EVENT_STUDY = "RESEARCH_EVENT_STUDY"


class EntryExecutionStatus(StrEnum):
    FILLED = "FILLED"
    FAILED = "FAILED"
    PENDING = "PENDING"
    BLOCKED_SIGNAL = "BLOCKED_SIGNAL"


class ExitExecutionStatus(StrEnum):
    FILLED = "FILLED"
    PENDING = "PENDING"
    BLOCKED_INTENT = "BLOCKED_INTENT"


class ExecutionReason(StrEnum):
    SIGNAL_NOT_AUTHORIZED = "SIGNAL_NOT_AUTHORIZED"
    RESEARCH_SIGNAL_INVALID = "RESEARCH_SIGNAL_INVALID"
    EXIT_INTENT_INVALID = "EXIT_INTENT_INVALID"
    SAME_DAY_FILL_FORBIDDEN = "SAME_DAY_FILL_FORBIDDEN"
    MISSING_EXECUTION_WINDOW = "MISSING_EXECUTION_WINDOW"
    DUPLICATE_EXECUTION_WINDOW = "DUPLICATE_EXECUTION_WINDOW"
    WINDOW_AVAILABLE_AT_MISMATCH = "WINDOW_AVAILABLE_AT_MISMATCH"
    WINDOW_BEFORE_CONFIGURED_OPEN = "WINDOW_BEFORE_CONFIGURED_OPEN"
    EXECUTION_DATA_INVALID = "EXECUTION_DATA_INVALID"
    SUSPENDED_OR_NOT_TRADABLE = "SUSPENDED_OR_NOT_TRADABLE"
    UNKNOWN_MARKET_RULE = "UNKNOWN_MARKET_RULE"
    CORPORATE_ACTION_BLOCK = "CORPORATE_ACTION_BLOCK"
    INVALID_OHLC_OR_UNIT = "INVALID_OHLC_OR_UNIT"
    BUY_LIQUIDITY_BLOCKED_AT_UP_LIMIT = "BUY_LIQUIDITY_BLOCKED_AT_UP_LIMIT"
    SELL_LIQUIDITY_BLOCKED_AT_DOWN_LIMIT = "SELL_LIQUIDITY_BLOCKED_AT_DOWN_LIMIT"
    VWAP_OUTSIDE_BAR = "VWAP_OUTSIDE_BAR"
    NOMINAL_BELOW_ONE_LOT = "NOMINAL_BELOW_ONE_LOT"
    THREE_DAY_EXECUTION_FAILURE = "THREE_DAY_EXECUTION_FAILURE"
    INSUFFICIENT_MARKET_CALENDAR = "INSUFFICIENT_MARKET_CALENDAR"
    FILLED_NEXT_LEGAL_WINDOW = "FILLED_NEXT_LEGAL_WINDOW"
    FILLED_NEXT_LEGAL_EXIT_WINDOW = "FILLED_NEXT_LEGAL_EXIT_WINDOW"
    EXIT_PENDING_BLOCKED = "EXIT_PENDING_BLOCKED"


@dataclass(frozen=True)
class ExecutionWindow:
    symbol: str
    trade_date: date
    window_index: int
    available_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    trade_status: int | None
    up_limit_price: float | None
    down_limit_price: float | None
    market_rule_valid: bool
    hard_valid: bool
    snapshot_id: str
    daily_snapshot_id: str | None = None
    corporate_action_blocking: bool = False
    invalid_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("execution window requires a symbol")
        if self.window_index < 0:
            raise ValueError("window_index must be non-negative")
        if not self.snapshot_id:
            raise ValueError("execution window requires snapshot_id")

    @property
    def vwap(self) -> float:
        if self.volume <= 0:
            return float("nan")
        return self.amount / self.volume


@dataclass(frozen=True)
class ExecutionAttempt:
    trade_date: date
    window_index: int | None
    attempted_at: datetime | None
    reason_codes: tuple[str, ...]
    snapshot_id: str | None


@dataclass(frozen=True)
class EntryExecution:
    signal_id: str
    symbol: str
    signal_decision_at: datetime
    status: EntryExecutionStatus
    scope: ExecutionScope
    attempted_trading_dates: tuple[date, ...]
    attempts: tuple[ExecutionAttempt, ...]
    fill_at: datetime | None = None
    fill_price: float | None = None
    quantity: int = 0
    gross_notional: float = 0.0
    commission: float = 0.0
    total_cash: float = 0.0
    snapshot_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status == EntryExecutionStatus.FILLED:
            if self.fill_at is None or self.fill_price is None or self.quantity <= 0:
                raise ValueError("filled execution requires fill time, price and quantity")
            if _local_date(self.fill_at, self.fill_at.tzinfo) <= _local_date(
                self.signal_decision_at, self.fill_at.tzinfo
            ):
                raise ValueError("same-day or prior-day fill is forbidden")


@dataclass(frozen=True)
class LegalFillResolution:
    """Strategy-independent result of the canonical next-legal-window resolver."""

    symbol: str
    decision_at: datetime
    status: EntryExecutionStatus
    attempted_trading_dates: tuple[date, ...]
    attempts: tuple[ExecutionAttempt, ...]
    window: ExecutionWindow | None
    reason_codes: tuple[str, ...]


def resolve_next_legal_fill(
    *,
    symbol: str,
    decision_at: datetime,
    windows: Iterable[ExecutionWindow],
    market_trading_dates: Sequence[date],
    settings: ExecutionSettings,
) -> LegalFillResolution:
    """Resolve the first genuinely legal post-decision buy window.

    Labels and order simulation both call this function, so neither can invent
    a fill from the next panel row's daily open.
    """

    exchange_tz = settings.next_window_end.tzinfo
    signal_date = _local_date(decision_at, exchange_tz)
    symbol_windows = tuple(window for window in windows if window.symbol == symbol)
    attempts: list[ExecutionAttempt] = []
    for window in sorted(symbol_windows, key=_window_sort_key):
        if window.trade_date == signal_date:
            attempts.append(
                ExecutionAttempt(
                    trade_date=window.trade_date,
                    window_index=window.window_index,
                    attempted_at=window.available_at,
                    reason_codes=(ExecutionReason.SAME_DAY_FILL_FORBIDDEN.value,),
                    snapshot_id=window.snapshot_id,
                )
            )

    future_dates = tuple(
        sorted({item for item in market_trading_dates if item > signal_date})
    )
    candidate_dates = future_dates[: settings.max_entry_wait_trading_days]
    grouped: dict[date, list[ExecutionWindow]] = defaultdict(list)
    for window in symbol_windows:
        if window.trade_date in candidate_dates:
            grouped[window.trade_date].append(window)
    duplicate_keys = {
        key
        for key, count in Counter(
            (window.trade_date, window.window_index)
            for window in symbol_windows
            if window.trade_date in candidate_dates
        ).items()
        if count > 1
    }
    for trade_date in candidate_dates:
        date_windows = sorted(grouped.get(trade_date, ()), key=_window_sort_key)
        if not date_windows:
            attempts.append(
                ExecutionAttempt(
                    trade_date=trade_date,
                    window_index=None,
                    attempted_at=None,
                    reason_codes=(ExecutionReason.MISSING_EXECUTION_WINDOW.value,),
                    snapshot_id=None,
                )
            )
            continue
        for window in date_windows:
            reasons = _window_rejection_reasons(
                window,
                trade_date=trade_date,
                earliest_window_end=settings.next_window_end,
                duplicate=(trade_date, window.window_index) in duplicate_keys,
            )
            if not reasons:
                markup = (settings.slippage_bps + settings.impact_bps) / 10_000.0
                per_share_cash = window.vwap * (1.0 + markup) * (
                    1.0 + settings.fee_bps / 10_000.0
                )
                if floor(
                    settings.nominal_capital_per_signal / per_share_cash / 100.0
                ) <= 0:
                    reasons = (ExecutionReason.NOMINAL_BELOW_ONE_LOT.value,)
            if reasons:
                attempts.append(
                    ExecutionAttempt(
                        trade_date=trade_date,
                        window_index=window.window_index,
                        attempted_at=window.available_at,
                        reason_codes=reasons,
                        snapshot_id=window.snapshot_id,
                    )
                )
                continue
            return LegalFillResolution(
                symbol=symbol,
                decision_at=decision_at,
                status=EntryExecutionStatus.FILLED,
                attempted_trading_dates=tuple(
                    item for item in candidate_dates if item <= window.trade_date
                ),
                attempts=tuple(attempts),
                window=window,
                reason_codes=(ExecutionReason.FILLED_NEXT_LEGAL_WINDOW.value,),
            )

    if len(candidate_dates) < settings.max_entry_wait_trading_days:
        status = EntryExecutionStatus.PENDING
        terminal_reason = ExecutionReason.INSUFFICIENT_MARKET_CALENDAR
    else:
        status = EntryExecutionStatus.FAILED
        terminal_reason = ExecutionReason.THREE_DAY_EXECUTION_FAILURE
    return LegalFillResolution(
        symbol=symbol,
        decision_at=decision_at,
        status=status,
        attempted_trading_dates=tuple(candidate_dates),
        attempts=tuple(attempts),
        window=None,
        reason_codes=_unique(
            (
                *(reason for attempt in attempts for reason in attempt.reason_codes),
                terminal_reason.value,
            )
        ),
    )


def execute_entry(
    signal: StrategySignal,
    windows: Iterable[ExecutionWindow],
    *,
    market_trading_dates: Sequence[date],
    settings: ExecutionSettings,
    scope: ExecutionScope = ExecutionScope.FORMAL_ORDER,
) -> EntryExecution:
    """Evaluate one signal over the next three market trading dates.

    A bad first window does not discard the event: later five-minute windows on
    the same date are examined in order.  If no legal window exists for three
    market dates, the signal is explicitly failed.  An incomplete future market
    calendar is pending instead of being mislabeled as an execution failure.
    """

    if not _entry_authorized(signal, scope):
        blocked_reason = (
            ExecutionReason.SIGNAL_NOT_AUTHORIZED
            if scope == ExecutionScope.FORMAL_ORDER
            else ExecutionReason.RESEARCH_SIGNAL_INVALID
        )
        return EntryExecution(
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            signal_decision_at=signal.decision_at,
            status=EntryExecutionStatus.BLOCKED_SIGNAL,
            scope=scope,
            attempted_trading_dates=(),
            attempts=(),
            snapshot_ids=signal.snapshot_ids,
            reason_codes=(blocked_reason.value,),
        )

    resolution = resolve_next_legal_fill(
        symbol=signal.symbol,
        decision_at=signal.decision_at,
        windows=windows,
        market_trading_dates=market_trading_dates,
        settings=settings,
    )
    if resolution.window is not None:
        execution = _fill(
            signal,
            resolution.window,
            settings,
            resolution.attempted_trading_dates,
            list(resolution.attempts),
            scope=scope,
        )
        if execution is None:
            raise AssertionError("legal fill resolver returned an unaffordable window")
        return execution
    return EntryExecution(
        signal_id=signal.signal_id,
        symbol=signal.symbol,
        signal_decision_at=signal.decision_at,
        status=resolution.status,
        scope=scope,
        attempted_trading_dates=resolution.attempted_trading_dates,
        attempts=resolution.attempts,
        snapshot_ids=signal.snapshot_ids,
        reason_codes=resolution.reason_codes,
    )


def _window_rejection_reasons(
    window: ExecutionWindow,
    *,
    trade_date: date,
    earliest_window_end: time,
    duplicate: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    available_date, available_time = _local_wall_clock(
        window.available_at, earliest_window_end.tzinfo
    )
    if duplicate:
        reasons.append(ExecutionReason.DUPLICATE_EXECUTION_WINDOW.value)
    if available_date != trade_date:
        reasons.append(ExecutionReason.WINDOW_AVAILABLE_AT_MISMATCH.value)
    if available_time < earliest_window_end.replace(tzinfo=None):
        reasons.append(ExecutionReason.WINDOW_BEFORE_CONFIGURED_OPEN.value)
    if not window.hard_valid:
        reasons.append(ExecutionReason.EXECUTION_DATA_INVALID.value)
        reasons.extend(window.invalid_reasons)
    if window.trade_status != 1:
        reasons.append(ExecutionReason.SUSPENDED_OR_NOT_TRADABLE.value)
    if not window.market_rule_valid:
        reasons.append(ExecutionReason.UNKNOWN_MARKET_RULE.value)
    if window.corporate_action_blocking:
        reasons.append(ExecutionReason.CORPORATE_ACTION_BLOCK.value)
    prices = (window.open, window.high, window.low, window.close)
    if (
        any(not isfinite(value) or value <= 0 for value in prices)
        or window.high < window.low
        or window.volume <= 0
        or window.amount <= 0
    ):
        reasons.append(ExecutionReason.INVALID_OHLC_OR_UNIT.value)
    up_limit = window.up_limit_price
    if up_limit is None or not isfinite(up_limit) or up_limit <= 0:
        reasons.append(ExecutionReason.UNKNOWN_MARKET_RULE.value)
    elif isfinite(window.low):
        tolerance = max(0.001, up_limit * 1e-6)
        if window.low >= up_limit - tolerance:
            reasons.append(ExecutionReason.BUY_LIQUIDITY_BLOCKED_AT_UP_LIMIT.value)
    vwap = window.vwap
    if isfinite(vwap) and isfinite(window.low) and isfinite(window.high):
        tolerance = max(0.001, abs(vwap) * 1e-6)
        if vwap < window.low - tolerance or vwap > window.high + tolerance:
            reasons.append(ExecutionReason.VWAP_OUTSIDE_BAR.value)
    elif window.volume > 0 and window.amount > 0:
        reasons.append(ExecutionReason.VWAP_OUTSIDE_BAR.value)
    return _unique(reasons)


def _fill(
    signal: StrategySignal,
    window: ExecutionWindow,
    settings: ExecutionSettings,
    candidate_dates: tuple[date, ...],
    attempts: list[ExecutionAttempt],
    *,
    scope: ExecutionScope,
) -> EntryExecution | None:
    vwap = window.vwap
    execution_markup = (settings.slippage_bps + settings.impact_bps) / 10_000.0
    fill_price = vwap * (1.0 + execution_markup)
    commission_fraction = settings.fee_bps / 10_000.0
    per_share_cash = fill_price * (1.0 + commission_fraction)
    quantity = floor(settings.nominal_capital_per_signal / per_share_cash / 100.0) * 100
    if quantity <= 0:
        return None
    gross = quantity * fill_price
    commission = gross * commission_fraction
    snapshots = _unique(
        (
            *signal.snapshot_ids,
            window.snapshot_id,
            *((window.daily_snapshot_id,) if window.daily_snapshot_id else ()),
        )
    )
    filled_attempt = ExecutionAttempt(
        trade_date=window.trade_date,
        window_index=window.window_index,
        attempted_at=window.available_at,
        reason_codes=(ExecutionReason.FILLED_NEXT_LEGAL_WINDOW.value,),
        snapshot_id=window.snapshot_id,
    )
    return EntryExecution(
        signal_id=signal.signal_id,
        symbol=signal.symbol,
        signal_decision_at=signal.decision_at,
        status=EntryExecutionStatus.FILLED,
        scope=scope,
        attempted_trading_dates=tuple(
            item for item in candidate_dates if item <= window.trade_date
        ),
        attempts=(*attempts, filled_attempt),
        fill_at=window.available_at,
        fill_price=fill_price,
        quantity=quantity,
        gross_notional=gross,
        commission=commission,
        total_cash=gross + commission,
        snapshot_ids=snapshots,
        reason_codes=(ExecutionReason.FILLED_NEXT_LEGAL_WINDOW.value,),
    )


@dataclass(frozen=True)
class ExitIntent:
    """A persistent sell instruction created after a close, not a fill."""

    intent_id: str
    signal_id: str
    symbol: str
    decision_at: datetime
    reason: ExitReason
    quantity: int
    reference_price: float
    available_at: datetime
    snapshot_ids: tuple[str, ...]
    hard_valid: bool

    def __post_init__(self) -> None:
        if not self.intent_id or not self.signal_id or not self.symbol:
            raise ValueError("exit intent requires ids and symbol")
        if self.quantity <= 0:
            raise ValueError("exit intent quantity must be positive")
        if not isfinite(self.reference_price) or self.reference_price <= 0:
            raise ValueError("exit intent reference_price must be positive")
        if not self.snapshot_ids:
            raise ValueError("exit intent requires input snapshots")
        if self.available_at > self.decision_at:
            raise ValueError("exit intent cannot use data available after decision_at")


@dataclass(frozen=True)
class ExitExecution:
    intent_id: str
    signal_id: str
    symbol: str
    intent_decision_at: datetime
    status: ExitExecutionStatus
    attempted_trading_dates: tuple[date, ...]
    attempts: tuple[ExecutionAttempt, ...]
    fill_at: datetime | None = None
    fill_price: float | None = None
    quantity: int = 0
    gross_notional: float = 0.0
    commission: float = 0.0
    net_proceeds: float = 0.0
    blocked_tail_loss: float = 0.0
    snapshot_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.blocked_tail_loss < 0:
            raise ValueError("blocked tail loss cannot be negative")
        if self.status == ExitExecutionStatus.FILLED:
            if self.fill_at is None or self.fill_price is None or self.quantity <= 0:
                raise ValueError("filled exit requires fill time, price and quantity")
            if _local_date(self.fill_at, self.fill_at.tzinfo) <= _local_date(
                self.intent_decision_at, self.fill_at.tzinfo
            ):
                raise ValueError("same-day or prior-day exit fill is forbidden")


def execute_exit(
    intent: ExitIntent,
    windows: Iterable[ExecutionWindow],
    *,
    market_trading_dates: Sequence[date],
    settings: ExecutionSettings,
) -> ExitExecution:
    """Keep a risk-reducing exit pending until a later legal sell window.

    Unlike entry, an exit never expires after three days.  Replaying the same
    intent with a longer causal window sequence deterministically resumes it.
    Corporate-action entry blocks do not block a risk-reducing sell, while an
    unknown trading state, suspension or pinned lower limit remains explicit.
    """

    if not _exit_intent_usable(intent):
        return ExitExecution(
            intent_id=intent.intent_id,
            signal_id=intent.signal_id,
            symbol=intent.symbol,
            intent_decision_at=intent.decision_at,
            status=ExitExecutionStatus.BLOCKED_INTENT,
            attempted_trading_dates=(),
            attempts=(),
            quantity=intent.quantity,
            snapshot_ids=intent.snapshot_ids,
            reason_codes=(ExecutionReason.EXIT_INTENT_INVALID.value,),
        )

    exchange_tz = settings.next_window_end.tzinfo
    intent_date = _local_date(intent.decision_at, exchange_tz)
    symbol_windows = tuple(window for window in windows if window.symbol == intent.symbol)
    attempts: list[ExecutionAttempt] = []
    for window in sorted(symbol_windows, key=_window_sort_key):
        if window.trade_date == intent_date:
            attempts.append(
                ExecutionAttempt(
                    trade_date=window.trade_date,
                    window_index=window.window_index,
                    attempted_at=window.available_at,
                    reason_codes=(ExecutionReason.SAME_DAY_FILL_FORBIDDEN.value,),
                    snapshot_id=window.snapshot_id,
                )
            )

    future_dates = tuple(sorted({item for item in market_trading_dates if item > intent_date}))
    grouped: dict[date, list[ExecutionWindow]] = defaultdict(list)
    for window in symbol_windows:
        if window.trade_date in future_dates:
            grouped[window.trade_date].append(window)
    duplicate_keys = {
        key
        for key, count in Counter(
            (window.trade_date, window.window_index)
            for window in symbol_windows
            if window.trade_date in future_dates
        ).items()
        if count > 1
    }
    latest_observed_price: float | None = None
    observed_snapshots: list[str] = list(intent.snapshot_ids)
    for trade_date in future_dates:
        date_windows = sorted(grouped.get(trade_date, ()), key=_window_sort_key)
        if not date_windows:
            attempts.append(
                ExecutionAttempt(
                    trade_date=trade_date,
                    window_index=None,
                    attempted_at=None,
                    reason_codes=(ExecutionReason.MISSING_EXECUTION_WINDOW.value,),
                    snapshot_id=None,
                )
            )
            continue
        for window in date_windows:
            observed_snapshots.append(window.snapshot_id)
            if isfinite(window.close) and window.close > 0:
                latest_observed_price = window.close
            reasons = _exit_window_rejection_reasons(
                window,
                trade_date=trade_date,
                earliest_window_end=settings.next_window_end,
                duplicate=(trade_date, window.window_index) in duplicate_keys,
            )
            if reasons:
                attempts.append(
                    ExecutionAttempt(
                        trade_date=trade_date,
                        window_index=window.window_index,
                        attempted_at=window.available_at,
                        reason_codes=reasons,
                        snapshot_id=window.snapshot_id,
                    )
                )
                continue
            return _fill_exit(
                intent,
                window,
                settings,
                future_dates=future_dates,
                attempts=attempts,
                observed_snapshots=observed_snapshots,
            )

    tail_loss = (
        max(0.0, intent.reference_price - latest_observed_price) * intent.quantity
        if latest_observed_price is not None
        else 0.0
    )
    return ExitExecution(
        intent_id=intent.intent_id,
        signal_id=intent.signal_id,
        symbol=intent.symbol,
        intent_decision_at=intent.decision_at,
        status=ExitExecutionStatus.PENDING,
        attempted_trading_dates=future_dates,
        attempts=tuple(attempts),
        quantity=intent.quantity,
        blocked_tail_loss=tail_loss,
        snapshot_ids=_unique(observed_snapshots),
        reason_codes=_unique(
            (
                *(reason for attempt in attempts for reason in attempt.reason_codes),
                ExecutionReason.EXIT_PENDING_BLOCKED.value,
            )
        ),
    )


def _entry_authorized(signal: StrategySignal, scope: ExecutionScope) -> bool:
    if scope == ExecutionScope.FORMAL_ORDER:
        return signal.order_authorized
    return (
        signal.strategy_family == StrategyFamily.MARKUP_RETEST
        and signal.lifecycle_state == ChipLifecycleState.RETEST_READY
        and signal.hard_valid
        and bool(signal.snapshot_ids)
        and signal.available_at <= signal.decision_at
        and signal.execution_status in {
            "BLOCKED_UNCALIBRATED",
            "READY_FOR_NEXT_WINDOW",
        }
    )


def _exit_intent_usable(intent: ExitIntent) -> bool:
    # A DATA_INVALID intent may have hard_valid=False by definition.  It must
    # still attempt to reduce risk using independently validated minute data.
    return bool(intent.snapshot_ids) and intent.available_at <= intent.decision_at


def _exit_window_rejection_reasons(
    window: ExecutionWindow,
    *,
    trade_date: date,
    earliest_window_end: time,
    duplicate: bool,
) -> tuple[str, ...]:
    reasons = list(
        _window_rejection_reasons(
            window,
            trade_date=trade_date,
            earliest_window_end=earliest_window_end,
            duplicate=duplicate,
        )
    )
    # Entry-only constraints must not prevent reducing existing exposure.
    reasons = [
        reason
        for reason in reasons
        if reason
        not in {
            ExecutionReason.CORPORATE_ACTION_BLOCK.value,
            ExecutionReason.BUY_LIQUIDITY_BLOCKED_AT_UP_LIMIT.value,
        }
    ]
    down_limit = window.down_limit_price
    if down_limit is None or not isfinite(down_limit) or down_limit <= 0:
        reasons.append(ExecutionReason.UNKNOWN_MARKET_RULE.value)
    elif isfinite(window.high):
        tolerance = max(0.001, down_limit * 1e-6)
        if window.high <= down_limit + tolerance:
            reasons.append(ExecutionReason.SELL_LIQUIDITY_BLOCKED_AT_DOWN_LIMIT.value)
    return _unique(reasons)


def _fill_exit(
    intent: ExitIntent,
    window: ExecutionWindow,
    settings: ExecutionSettings,
    *,
    future_dates: tuple[date, ...],
    attempts: list[ExecutionAttempt],
    observed_snapshots: list[str],
) -> ExitExecution:
    execution_markdown = (settings.slippage_bps + settings.impact_bps) / 10_000.0
    fill_price = window.vwap * (1.0 - execution_markdown)
    gross = intent.quantity * fill_price
    commission = gross * settings.fee_bps / 10_000.0
    filled_attempt = ExecutionAttempt(
        trade_date=window.trade_date,
        window_index=window.window_index,
        attempted_at=window.available_at,
        reason_codes=(ExecutionReason.FILLED_NEXT_LEGAL_EXIT_WINDOW.value,),
        snapshot_id=window.snapshot_id,
    )
    snapshots = _unique(
        (
            *observed_snapshots,
            *((window.daily_snapshot_id,) if window.daily_snapshot_id else ()),
        )
    )
    return ExitExecution(
        intent_id=intent.intent_id,
        signal_id=intent.signal_id,
        symbol=intent.symbol,
        intent_decision_at=intent.decision_at,
        status=ExitExecutionStatus.FILLED,
        attempted_trading_dates=tuple(
            item for item in future_dates if item <= window.trade_date
        ),
        attempts=(*attempts, filled_attempt),
        fill_at=window.available_at,
        fill_price=fill_price,
        quantity=intent.quantity,
        gross_notional=gross,
        commission=commission,
        net_proceeds=gross - commission,
        blocked_tail_loss=max(
            0.0, intent.reference_price - fill_price
        ) * intent.quantity,
        snapshot_ids=snapshots,
        reason_codes=(ExecutionReason.FILLED_NEXT_LEGAL_EXIT_WINDOW.value,),
    )


def _window_sort_key(window: ExecutionWindow) -> tuple[date, int, datetime]:
    return window.trade_date, window.window_index, window.available_at


def _local_date(value: datetime, target_tz: tzinfo | None) -> date:
    if value.tzinfo is not None and target_tz is not None:
        return value.astimezone(target_tz).date()
    return value.date()


def _local_wall_clock(
    value: datetime, target_tz: tzinfo | None
) -> tuple[date, time]:
    if value.tzinfo is not None and target_tz is not None:
        value = value.astimezone(target_tz)
    return value.date(), value.time().replace(tzinfo=None)


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))
