"""Fail-closed primitives for the ChinNext V1 Phase 1 data foundation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite

CHINEXT_BOARD = "CHINEXT"
TURNOVER20_DAYS = 20
TURNOVER20_MIN_CNY = 100_000_000.0
MIN_LISTED_TRADING_DAYS = 180
MARKET_ANCHOR = "399102.SZ"


class MissingMarketAnchorError(LookupError):
    """Raised when the exact configured anchor is absent."""


@dataclass(frozen=True)
class SecurityFact:
    """Normalized static/date-effective identity fact.

    ``membership_end_exclusive`` is the first date on which the security is no
    longer a member. A source whose raw delist field means "last listed date"
    must normalize it explicitly; this module never guesses that conversion.
    """

    symbol: str
    board: str | None
    list_date: date | None
    membership_start: date | None
    membership_end_exclusive: date | None
    available_at: datetime | None
    source: str | None
    source_version: str | None
    current_state_only: bool = False
    current_state_asof: date | None = None


@dataclass(frozen=True)
class DailyPITFact:
    """Normalized date-varying fact visible no later than ``available_at``."""

    symbol: str
    trade_date: date
    risk_warning: bool | None
    suspended: bool | None
    tradable_buy: bool | None
    tradable_sell: bool | None
    amount_cny: float | None
    amount_unit: str | None
    available_at: datetime | None
    source: str | None
    source_version: str | None
    hard_valid: bool | None


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    reasons: tuple[str, ...]
    listed_trading_days: int | None
    turnover20_mean_cny: float | None


def _has_lineage(source: str | None, source_version: str | None) -> bool:
    return bool(source and source.strip() and source_version and source_version.strip())


def _is_visible(available_at: datetime | None, decision_at: datetime) -> bool:
    if available_at is None:
        return False
    if available_at.tzinfo is None or decision_at.tzinfo is None:
        return False
    return available_at <= decision_at


def listed_trading_days_inclusive(
    *, list_date: date, signal_date: date, trading_calendar: Sequence[date]
) -> int:
    """Count exchange sessions from first session on/after listing through t.

    The signal date is included. Therefore the 180th observable exchange session
    has count 180 and passes the Phase 1 age threshold.
    """

    sessions = sorted(set(trading_calendar))
    if signal_date not in sessions:
        raise ValueError("signal date is not an explicit exchange session")
    eligible_sessions = [day for day in sessions if list_date <= day <= signal_date]
    return len(eligible_sessions)


def _turnover20(
    *,
    symbol: str,
    signal_date: date,
    decision_at: datetime,
    trading_calendar: Sequence[date],
    daily_facts: Mapping[date, DailyPITFact],
) -> tuple[float | None, list[str]]:
    sessions = [day for day in sorted(set(trading_calendar)) if day <= signal_date]
    if signal_date not in sessions or len(sessions) < TURNOVER20_DAYS:
        return None, ["TURNOVER_HISTORY_INSUFFICIENT"]
    required_days = sessions[-TURNOVER20_DAYS:]
    values: list[float] = []
    reasons: list[str] = []
    for day in required_days:
        fact = daily_facts.get(day)
        if fact is None or fact.symbol != symbol or fact.trade_date != day:
            reasons.append("TURNOVER_HISTORY_INSUFFICIENT")
            continue
        if fact.hard_valid is not True:
            reasons.append("HARD_INVALID_DAILY_FACT")
        if not _has_lineage(fact.source, fact.source_version):
            reasons.append("UNKNOWN_DAILY_LINEAGE")
        if not _is_visible(fact.available_at, decision_at):
            reasons.append("DAILY_FACT_NOT_AVAILABLE")
        if fact.amount_unit != "CNY":
            reasons.append("TURNOVER_UNIT_UNKNOWN")
        value = fact.amount_cny
        if value is None or not isfinite(float(value)) or float(value) < 0:
            reasons.append("TURNOVER_AMOUNT_INVALID")
        else:
            values.append(float(value))
    if reasons or len(values) != TURNOVER20_DAYS:
        return None, reasons or ["TURNOVER_HISTORY_INSUFFICIENT"]
    mean = sum(values) / float(TURNOVER20_DAYS)
    if mean < TURNOVER20_MIN_CNY:
        return mean, ["TURNOVER20_BELOW_THRESHOLD"]
    return mean, []


def evaluate_entry_universe_eligibility(
    *,
    security: SecurityFact,
    signal_date: date,
    decision_at: datetime,
    trading_calendar: Sequence[date],
    daily_facts: Mapping[date, DailyPITFact],
) -> EligibilityResult:
    """Evaluate only the Phase 1 data gates; no strategy signal is computed."""

    reasons: list[str] = []
    listed_days: int | None = None

    if security.current_state_only and security.current_state_asof != signal_date:
        reasons.append("CURRENT_SURVIVOR_HISTORICAL_BACKFILL")
    if not _has_lineage(security.source, security.source_version):
        reasons.append("UNKNOWN_SECURITY_LINEAGE")
    if not _is_visible(security.available_at, decision_at):
        reasons.append("SECURITY_FACT_NOT_AVAILABLE")
    if security.board is None:
        reasons.append("UNKNOWN_BOARD")
    elif security.board != CHINEXT_BOARD:
        reasons.append("NOT_CHINEXT")
    if security.membership_start is None:
        reasons.append("UNKNOWN_MEMBERSHIP_START")
    elif signal_date < security.membership_start:
        reasons.append("SECURITY_NOT_YET_MEMBER")
    if (
        security.membership_end_exclusive is not None
        and signal_date >= security.membership_end_exclusive
    ):
        reasons.append("SECURITY_MEMBERSHIP_ENDED")
    if security.list_date is None:
        reasons.append("UNKNOWN_LIST_DATE")
    else:
        try:
            listed_days = listed_trading_days_inclusive(
                list_date=security.list_date,
                signal_date=signal_date,
                trading_calendar=trading_calendar,
            )
            if listed_days < MIN_LISTED_TRADING_DAYS:
                reasons.append("LISTED_TRADING_DAYS_LT_180")
        except ValueError:
            reasons.append("INVALID_TRADING_CALENDAR_SCOPE")

    signal_fact = daily_facts.get(signal_date)
    if signal_fact is None or signal_fact.symbol != security.symbol:
        reasons.append("MISSING_SIGNAL_DATE_FACT")
    else:
        if signal_fact.hard_valid is not True:
            reasons.append("HARD_INVALID_SIGNAL_FACT")
        if not _has_lineage(signal_fact.source, signal_fact.source_version):
            reasons.append("UNKNOWN_SIGNAL_LINEAGE")
        if not _is_visible(signal_fact.available_at, decision_at):
            reasons.append("SIGNAL_FACT_NOT_AVAILABLE")
        if signal_fact.risk_warning is None:
            reasons.append("UNKNOWN_RISK_WARNING")
        elif signal_fact.risk_warning:
            reasons.append("RISK_WARNING")
        if signal_fact.suspended is None:
            reasons.append("UNKNOWN_SUSPENSION")
        elif signal_fact.suspended:
            reasons.append("SUSPENDED")
        if signal_fact.tradable_buy is None:
            reasons.append("UNKNOWN_BUY_TRADABILITY")
        elif not signal_fact.tradable_buy:
            reasons.append("BUY_NOT_TRADABLE")

    turnover_mean, turnover_reasons = _turnover20(
        symbol=security.symbol,
        signal_date=signal_date,
        decision_at=decision_at,
        trading_calendar=trading_calendar,
        daily_facts=daily_facts,
    )
    reasons.extend(turnover_reasons)
    unique_reasons = tuple(dict.fromkeys(reasons))
    return EligibilityResult(
        eligible=not unique_reasons,
        reasons=unique_reasons,
        listed_trading_days=listed_days,
        turnover20_mean_cny=turnover_mean,
    )


def require_exact_market_anchor(histories: Mapping[str, object]) -> object:
    """Return only 399102.SZ; never substitute another available index."""

    if MARKET_ANCHOR not in histories:
        raise MissingMarketAnchorError(
            f"required market anchor {MARKET_ANCHOR} is missing; fallback is forbidden"
        )
    return histories[MARKET_ANCHOR]
