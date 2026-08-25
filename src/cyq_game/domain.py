from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any


class Action(StrEnum):
    BUY = "BUY"
    ADD = "ADD"
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    NO_TRADE = "NO_TRADE"


class StrategyFamily(StrEnum):
    MARKUP_RETEST = "MARKUP_RETEST"
    ACCUMULATION_TREND = "ACCUMULATION_TREND"
    PANIC_REVERSAL = "PANIC_REVERSAL"
    CAPITAL_SELF_RESCUE = "CAPITAL_SELF_RESCUE"
    LEADER_FORMATION = "LEADER_FORMATION"
    VALUE_DISCOVERY = "VALUE_DISCOVERY"
    CASH_DEFENSE = "CASH_DEFENSE"


class ChipLifecycleState(StrEnum):
    """Causal chip-migration state; states are evidence, never orders."""

    NEUTRAL = "NEUTRAL"
    ACCUMULATING = "ACCUMULATING"
    BREAKOUT = "BREAKOUT"
    RETEST_READY = "RETEST_READY"
    DISTRIBUTING = "DISTRIBUTING"
    BROKEN = "BROKEN"


class ExitReason(StrEnum):
    DISTRIBUTION_CONFIRMED = "DISTRIBUTION_CONFIRMED"
    STRUCTURE_BROKEN = "STRUCTURE_BROKEN"
    PROTECTIVE_STOP = "PROTECTIVE_STOP"
    MAX_HOLDING_PERIOD = "MAX_HOLDING_PERIOD"
    DATA_INVALID = "DATA_INVALID"
    CORPORATE_ACTION = "CORPORATE_ACTION"
    BLOCKED_EXIT = "BLOCKED_EXIT"


class StockType(StrEnum):
    T0 = "T0"
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"
    T4 = "T4"
    T5 = "T5"
    T6 = "T6"
    T7 = "T7"
    T8 = "T8"
    T9 = "T9"


class RiskFlag(StrEnum):
    HORIZONTAL_DISTRIBUTION = "HORIZONTAL_DISTRIBUTION"
    SECONDARY_HIGH_DISTRIBUTION = "SECONDARY_HIGH_DISTRIBUTION"
    SLOW_PRESSURE_EXIT = "SLOW_PRESSURE_EXIT"
    DUMP_PRESSURE_EXIT = "DUMP_PRESSURE_EXIT"
    HARD_INVALID = "HARD_INVALID"
    BLOCKED_EXIT = "BLOCKED_EXIT"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(StrEnum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    SCHEDULED = "SCHEDULED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    BLOCKED = "BLOCKED"


class PlanStatus(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    ACTIVE = "ACTIVE"
    UPDATE_REQUIRED = "UPDATE_REQUIRED"
    CLOSED = "CLOSED"
    INVALIDATED = "INVALIDATED"


@dataclass(frozen=True)
class PITMeta:
    event_time: datetime
    available_at: datetime
    effective_from: datetime
    source: str
    snapshot_id: str
    revision_id: str
    run_id: str

    def assert_available(self, decision_at: datetime) -> None:
        if self.available_at > decision_at:
            raise FutureDataError(
                f"snapshot {self.snapshot_id} was available at {self.available_at}, "
                f"after decision {decision_at}"
            )


class FutureDataError(ValueError):
    """Raised whenever data crosses the point-in-time boundary."""


@dataclass(frozen=True)
class Bar:
    symbol: str
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    free_float_shares: float
    available_at: datetime
    suspended: bool = False
    st: bool = False
    limit_up: float | None = None
    limit_down: float | None = None

    def __post_init__(self) -> None:
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("prices must be positive")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("invalid OHLC relationship")
        if self.volume < 0 or self.free_float_shares <= 0:
            raise ValueError("volume and free float must be valid")

    @property
    def turnover(self) -> float:
        return min(1.0, self.volume / self.free_float_shares)

    @property
    def typical_price(self) -> float:
        return (self.high + self.low + self.close) / 3.0


@dataclass(frozen=True)
class StateScore:
    stock_type: StockType
    score: float
    reliability: float
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class RiskState:
    flags: frozenset[RiskFlag] = frozenset()
    hard_valid: bool = True
    tail_loss_r: float = 0.0
    reasons: tuple[str, ...] = ()

    @property
    def blocks_new_risk(self) -> bool:
        return not self.hard_valid or bool(self.flags)


@dataclass(frozen=True)
class DecisionContext:
    symbol: str
    decision_at: datetime
    data_quality: float
    observability: float
    execution_probability: float
    market_confidence: float
    sector_confidence: float
    model_disagreement: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "data_quality",
            "observability",
            "execution_probability",
            "market_confidence",
            "sector_confidence",
            "model_disagreement",
        ):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
