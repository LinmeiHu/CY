"""Canonical causal price-coordinate and corporate-action identity contract."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from datetime import date
from hashlib import sha256

PRICE_COORDINATE_VERSION = "causal-economic-price-v2"
PRICE_COORDINATE_NAME = "CAUSAL_ECONOMIC_BREAK_EVEN"


def rebase_economic_price(
    value: float,
    *,
    cash_per_share: float = 0.0,
    share_multiplier: float = 1.0,
) -> float:
    """Apply the repository-wide ex-date coordinate: ``(C - D) / R``."""

    price = float(value)
    cash = float(cash_per_share)
    ratio = float(share_multiplier)
    if not all(math.isfinite(item) for item in (price, cash, ratio)):
        raise ValueError("corporate-action price inputs must be finite")
    if price <= 0.0:
        raise ValueError("pre-action economic price must be positive")
    if cash < 0.0:
        raise ValueError("cash per share must be non-negative")
    if ratio <= 0.0:
        raise ValueError("share multiplier must be positive")
    result = (price - cash) / ratio
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError("corporate action produced a non-positive price coordinate")
    return result


def canonical_action_component_id(
    *,
    symbol: str,
    effective_date: date,
    kind: str,
    source_action_ids: Iterable[str],
    snapshot_id: str,
    cash_per_share: float = 0.0,
    share_multiplier: float = 1.0,
    shares: float = 0.0,
) -> str:
    """Return an idempotent ID committed to source provenance and economics."""

    sources = tuple(sorted({str(value) for value in source_action_ids if str(value)}))
    if not symbol or not kind or not snapshot_id:
        raise ValueError("corporate-action identity fields cannot be empty")
    cash = float(cash_per_share)
    ratio = float(share_multiplier)
    quantity = float(shares)
    if not all(math.isfinite(value) for value in (cash, ratio, quantity)):
        raise ValueError("corporate-action identity numerics must be finite")
    payload = {
        "coordinate_version": PRICE_COORDINATE_VERSION,
        "symbol": symbol,
        "effective_date": effective_date.isoformat(),
        "kind": kind,
        "source_action_ids": sources,
        "snapshot_id": snapshot_id,
        "cash_per_share": cash.hex(),
        "share_multiplier": ratio.hex(),
        "shares": quantity.hex(),
    }
    digest = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"chip-action-{digest}"


def parse_action_ids(value: object) -> tuple[str, ...]:
    """Parse a normalized action-id aggregate without inventing provenance."""

    if value is None:
        return ()
    values: Iterable[object]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ()
        if text.startswith("["):
            decoded = json.loads(text)
            if not isinstance(decoded, list):
                raise ValueError("corporate_action_ids JSON must be a list")
            values = decoded
        else:
            values = text.split("|")
    elif isinstance(value, (tuple, list)):
        values = value
    else:
        raise ValueError("corporate_action_ids has an unsupported type")
    return tuple(sorted({str(item) for item in values if str(item)}))
