"""Fail-closed QD-001 -> CY-006 causal corporate-action adapter primitives.

The adapter consumes explicitly supplied, causally visible normalized event
records. It never derives a factor from future prices or a current qfq/hfq
series. Missing/ambiguous events raise rather than silently passing through.
"""

from __future__ import annotations

from datetime import date, datetime
from math import isfinite
from typing import Mapping, Sequence


class CausalCorporateActionError(ValueError):
    """Raised when an event cannot be used under the frozen causal contract."""


def normalize_symbol(raw: str) -> str:
    value = str(raw).strip().upper()
    if value.endswith(".SZ"):
        digits = value[:-3]
    elif value.startswith("SZ."):
        digits = value[3:]
    else:
        digits = value
    if len(digits) != 6 or not digits.isdigit() or not digits.startswith("3"):
        raise CausalCorporateActionError(f"ambiguous/non-GEM symbol: {raw!r}")
    return f"{digits}.SZ"


def _as_date(value: object, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError as exc:
            raise CausalCorporateActionError(f"invalid {field}: {value!r}") from exc
    raise CausalCorporateActionError(f"missing {field}")


def validate_event(event: Mapping[str, object], decision_date: date) -> dict[str, object]:
    """Validate one normalized QD-010 event visible by ``decision_date``."""

    symbol = normalize_symbol(str(event.get("symbol", "")))
    known_at = _as_date(event.get("known_at"), "known_at")
    effective = _as_date(event.get("effective_date"), "effective_date")
    if known_at > decision_date or effective > decision_date:
        raise CausalCorporateActionError("future corporate-action fact")
    event_type = str(event.get("event_type", "")).strip().lower()
    if event_type not in {"cash_dividend", "share_distribution", "rights", "bonus_share"}:
        raise CausalCorporateActionError(f"unknown event type: {event_type!r}")
    multiplier = float(event.get("share_multiplier") or 1.0)
    cash = float(event.get("cash_per_share_gross") or 0.0)
    rights = float(event.get("rights_subscription_ratio") or 0.0)
    if not all(isfinite(x) for x in (multiplier, cash, rights)) or multiplier <= 0:
        raise CausalCorporateActionError("ambiguous/non-positive corporate-action terms")
    if rights != 0.0:
        raise CausalCorporateActionError("rights participation is execution-unresolved")
    return {
        "symbol": symbol,
        "effective_date": effective,
        "known_at": known_at,
        "event_type": event_type,
        "share_multiplier": multiplier,
        "cash_per_share": cash,
        "event_id": str(event.get("event_id") or ""),
    }


def rebase_history(
    prices: Sequence[float], volumes: Sequence[float], event: Mapping[str, object], decision_date: date
) -> tuple[list[float], list[float]]:
    """Apply CY-006's causal past-history coordinate transform."""

    normalized = validate_event(event, decision_date)
    multiplier = float(normalized["share_multiplier"])
    cash = float(normalized["cash_per_share"])
    rebased_prices = [(float(value) - cash) / multiplier for value in prices]
    rebased_volumes = [float(value) * multiplier for value in volumes]
    if any(not isfinite(x) for x in (*rebased_prices, *rebased_volumes)):
        raise CausalCorporateActionError("non-finite rebased history")
    return rebased_prices, rebased_volumes


def visible_events(events: Sequence[Mapping[str, object]], decision_date: date) -> list[dict[str, object]]:
    """Return deterministically ordered causal events; duplicates fail closed."""

    normalized = [validate_event(event, decision_date) for event in events]
    keys = [(x["symbol"], x["effective_date"], x["event_id"]) for x in normalized]
    if len(set(keys)) != len(keys):
        raise CausalCorporateActionError("duplicate corporate-action identity")
    return sorted(normalized, key=lambda x: (str(x["symbol"]), x["effective_date"], str(x["event_id"])))
