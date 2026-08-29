"""Small, deterministic helpers for the bounded ChinNext PIT-B universe build."""

from __future__ import annotations

from bisect import bisect_left
from datetime import date
from typing import Sequence


def is_date_effective_member(day: date, list_date: date, out_date: date | None) -> bool:
    """Return membership from effective listing/out dates without future backfill."""

    return list_date <= day and (out_date is None or day <= out_date)


def listed_session_age(day: date, list_date: date, sessions: Sequence[date]) -> int:
    """Count exchange sessions from the first session on/after listing, inclusive."""

    if day < list_date:
        return 0
    first = bisect_left(sessions, list_date)
    if first == len(sessions):
        return 0
    current = bisect_left(sessions, day)
    if current == len(sessions) or sessions[current] != day or current < first:
        return 0
    return current - first + 1


def listing_age_eligible(age: int, minimum: int = 180) -> bool:
    """The frozen gate is inclusive: exactly 180 completed sessions passes."""

    return age >= minimum
