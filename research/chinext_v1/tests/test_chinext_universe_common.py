from __future__ import annotations

import sys
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from chinext_universe_common import (
    DailyPITFact,
    MissingMarketAnchorError,
    SecurityFact,
    evaluate_entry_universe_eligibility,
    listed_trading_days_inclusive,
    require_exact_market_anchor,
)

TZ = timezone(timedelta(hours=8))
SYMBOL = "300001.SZ"


def _sessions(start: date, count: int) -> list[date]:
    out: list[date] = []
    current = start
    while len(out) < count:
        if current.weekday() < 5:
            out.append(current)
        current += timedelta(days=1)
    return out


CALENDAR = _sessions(date(2019, 1, 2), 260)
SIGNAL_DATE = CALENDAR[219]
LIST_DATE = CALENDAR[40]  # Inclusive count through SIGNAL_DATE is exactly 180.
DECISION_AT = datetime.combine(SIGNAL_DATE, time(15, 30), tzinfo=TZ)


def _security(**changes: object) -> SecurityFact:
    base = SecurityFact(
        symbol=SYMBOL,
        board="CHINEXT",
        list_date=LIST_DATE,
        membership_start=LIST_DATE,
        membership_end_exclusive=None,
        available_at=datetime.combine(LIST_DATE, time(0), tzinfo=TZ),
        source="fixture-security-master",
        source_version="fixture-security-v1",
    )
    return replace(base, **changes)


def _daily_fact(day: date, **changes: object) -> DailyPITFact:
    base = DailyPITFact(
        symbol=SYMBOL,
        trade_date=day,
        risk_warning=False,
        suspended=False,
        tradable_buy=True,
        tradable_sell=True,
        amount_cny=100_000_000.0,
        amount_unit="CNY",
        available_at=datetime.combine(day, time(15), tzinfo=TZ),
        source="fixture-daily",
        source_version="fixture-daily-v1",
        hard_valid=True,
    )
    return replace(base, **changes)


def _facts(amount: float = 100_000_000.0) -> dict[date, DailyPITFact]:
    days = [day for day in CALENDAR if day <= SIGNAL_DATE][-20:]
    return {day: _daily_fact(day, amount_cny=amount) for day in days}


def _evaluate(
    security: SecurityFact | None = None,
    facts: dict[date, DailyPITFact] | None = None,
):
    return evaluate_entry_universe_eligibility(
        security=security or _security(),
        signal_date=SIGNAL_DATE,
        decision_at=DECISION_AT,
        trading_calendar=CALENDAR,
        daily_facts=facts if facts is not None else _facts(),
    )


def test_future_listed_security_cannot_enter() -> None:
    future = CALENDAR[230]
    result = _evaluate(
        _security(list_date=future, membership_start=future),
    )
    assert not result.eligible
    assert "SECURITY_NOT_YET_MEMBER" in result.reasons


def test_listed_trading_days_179_fails() -> None:
    list_date = CALENDAR[41]
    result = _evaluate(_security(list_date=list_date, membership_start=list_date))
    assert result.listed_trading_days == 179
    assert "LISTED_TRADING_DAYS_LT_180" in result.reasons


def test_exactly_180_listed_trading_days_passes() -> None:
    assert listed_trading_days_inclusive(
        list_date=LIST_DATE,
        signal_date=SIGNAL_DATE,
        trading_calendar=CALENDAR,
    ) == 180
    result = _evaluate()
    assert result.eligible
    assert result.listed_trading_days == 180


def test_membership_end_is_exclusive() -> None:
    result = _evaluate(_security(membership_end_exclusive=SIGNAL_DATE))
    assert not result.eligible
    assert "SECURITY_MEMBERSHIP_ENDED" in result.reasons


def test_risk_warning_true_fails() -> None:
    facts = _facts()
    facts[SIGNAL_DATE] = replace(facts[SIGNAL_DATE], risk_warning=True)
    result = _evaluate(facts=facts)
    assert not result.eligible
    assert "RISK_WARNING" in result.reasons


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"suspended": True}, "SUSPENDED"),
        ({"tradable_buy": False}, "BUY_NOT_TRADABLE"),
    ],
)
def test_suspended_or_nontradable_fails(changes: dict[str, object], reason: str) -> None:
    facts = _facts()
    facts[SIGNAL_DATE] = replace(facts[SIGNAL_DATE], **changes)
    result = _evaluate(facts=facts)
    assert not result.eligible
    assert reason in result.reasons


def test_turnover20_exactly_100m_passes() -> None:
    result = _evaluate(facts=_facts(100_000_000.0))
    assert result.eligible
    assert result.turnover20_mean_cny == 100_000_000.0


def test_turnover20_below_100m_fails() -> None:
    result = _evaluate(facts=_facts(99_999_999.0))
    assert not result.eligible
    assert "TURNOVER20_BELOW_THRESHOLD" in result.reasons


def test_turnover20_nan_fails() -> None:
    facts = _facts()
    first = min(facts)
    facts[first] = replace(facts[first], amount_cny=float("nan"))
    result = _evaluate(facts=facts)
    assert not result.eligible
    assert "TURNOVER_AMOUNT_INVALID" in result.reasons


def test_turnover20_insufficient_history_fails() -> None:
    facts = _facts()
    facts.pop(min(facts))
    result = _evaluate(facts=facts)
    assert not result.eligible
    assert "TURNOVER_HISTORY_INSUFFICIENT" in result.reasons


def test_unknown_critical_pit_fact_fails_closed() -> None:
    facts = _facts()
    facts[SIGNAL_DATE] = replace(
        facts[SIGNAL_DATE],
        risk_warning=None,
        suspended=None,
        tradable_buy=None,
    )
    result = _evaluate(facts=facts)
    assert not result.eligible
    assert {
        "UNKNOWN_RISK_WARNING",
        "UNKNOWN_SUSPENSION",
        "UNKNOWN_BUY_TRADABILITY",
    }.issubset(result.reasons)


def test_current_survivor_cannot_backfill_history() -> None:
    result = _evaluate(
        _security(
            current_state_only=True,
            current_state_asof=CALENDAR[-1],
        )
    )
    assert not result.eligible
    assert "CURRENT_SURVIVOR_HISTORICAL_BACKFILL" in result.reasons


def test_missing_399102_never_falls_back_to_other_index() -> None:
    with pytest.raises(MissingMarketAnchorError, match="fallback is forbidden"):
        require_exact_market_anchor(
            {
                "399006.SZ": object(),
                "000852.SH": object(),
            }
        )


def test_exact_399102_is_returned() -> None:
    expected = object()
    assert require_exact_market_anchor({"399102.SZ": expected}) is expected
