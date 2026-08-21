"""Fail-closed point-in-time joins for strategy-state prerequisites.

This module joins only metadata that was observable at ``decision_at``.  It is
deliberately independent from the backtest and decision engines so data
eligibility can be proved before either engine is allowed to run.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from itertools import islice
from types import MappingProxyType

from .validity import ValidityAssessment, ValidityReason

type PITScalar = str | int | float | bool | None


class PITDomain(StrEnum):
    """Canonical domains required before a stock state may be strict."""

    SECURITY_IDENTITY = "security_identity"
    SECTOR_MEMBERSHIP = "sector_membership"
    FLOAT_SHARES = "float_shares"
    CORPORATE_ACTION_STATUS = "corporate_action_status"
    TRADING_STATUS = "trading_status"
    MARKET_RULE = "market_rule"


REQUIRED_STRATEGY_DOMAINS: tuple[PITDomain, ...] = tuple(PITDomain)

_MISSING_REASON: Mapping[PITDomain, ValidityReason] = MappingProxyType(
    {
        PITDomain.SECURITY_IDENTITY: ValidityReason.MISSING_SECURITY_IDENTITY,
        PITDomain.SECTOR_MEMBERSHIP: ValidityReason.MISSING_SECTOR_MEMBERSHIP,
        PITDomain.FLOAT_SHARES: ValidityReason.MISSING_FLOAT_SHARES,
        PITDomain.CORPORATE_ACTION_STATUS: ValidityReason.MISSING_CORPORATE_ACTION_STATUS,
        PITDomain.TRADING_STATUS: ValidityReason.MISSING_TRADING_STATUS,
        PITDomain.MARKET_RULE: ValidityReason.MISSING_MARKET_RULE,
    }
)


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def _canonical_symbol(value: str) -> str:
    symbol = value.strip().upper()
    if not symbol:
        raise ValueError("symbol must not be empty")
    return symbol


def _canonical_coordinate(value: str | None) -> str | None:
    if value is None:
        return None
    coordinate = value.strip().upper()
    if not coordinate:
        raise ValueError("price_coordinate must not be empty")
    return coordinate


def _require_text(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _validate_scalar(value: PITScalar, field: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{field} must be finite")


def _json_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class PITDomainRecord:
    """One versioned effective-time record from a canonical PIT table.

    ``record_id`` identifies one logical record across revisions, while
    ``revision_id`` identifies the exact published version.  Effective ranges
    are half-open: ``[valid_from, valid_to)``.
    """

    domain: PITDomain
    symbol: str
    record_id: str
    revision_id: str
    valid_from: datetime
    valid_to: datetime | None
    available_at: datetime
    source: str
    snapshot_id: str
    values: Mapping[str, PITScalar]
    strict_pit_eligible: bool = True
    available_at_observed: bool = True
    price_coordinate: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _canonical_symbol(self.symbol))
        object.__setattr__(self, "record_id", _require_text(self.record_id, "record_id"))
        object.__setattr__(self, "revision_id", _require_text(self.revision_id, "revision_id"))
        object.__setattr__(self, "source", _require_text(self.source, "source"))
        object.__setattr__(self, "snapshot_id", _require_text(self.snapshot_id, "snapshot_id"))
        object.__setattr__(
            self,
            "price_coordinate",
            _canonical_coordinate(self.price_coordinate),
        )
        _require_aware(self.valid_from, "valid_from")
        _require_aware(self.available_at, "available_at")
        if self.valid_to is not None:
            _require_aware(self.valid_to, "valid_to")
            if self.valid_to <= self.valid_from:
                raise ValueError("valid_to must be later than valid_from")
        frozen_values = dict(self.values)
        if not frozen_values:
            raise ValueError("values must not be empty")
        for key, value in frozen_values.items():
            _require_text(key, "values key")
            _validate_scalar(value, f"values[{key!r}]")
        object.__setattr__(self, "values", MappingProxyType(frozen_values))

    def is_effective_at(self, decision_at: datetime) -> bool:
        _require_aware(decision_at, "decision_at")
        return self.valid_from <= decision_at and (
            self.valid_to is None or decision_at < self.valid_to
        )

    @property
    def record_sha256(self) -> str:
        """Content address of the normalized record version."""

        return _json_sha256(
            {
                "available_at": self.available_at.isoformat(),
                "available_at_observed": self.available_at_observed,
                "domain": self.domain.value,
                "price_coordinate": self.price_coordinate,
                "record_id": self.record_id,
                "revision_id": self.revision_id,
                "snapshot_id": self.snapshot_id,
                "source": self.source,
                "strict_pit_eligible": self.strict_pit_eligible,
                "symbol": self.symbol,
                "valid_from": self.valid_from.isoformat(),
                "valid_to": self.valid_to.isoformat() if self.valid_to else None,
                "values": dict(self.values),
            }
        )


@dataclass(frozen=True)
class PITJoinRequest:
    """A bounded, explicit request for one decision-time metadata state."""

    symbol: str
    decision_at: datetime
    price_coordinate: str = "UNADJUSTED"
    required_domains: tuple[PITDomain, ...] = REQUIRED_STRATEGY_DOMAINS
    observability: float | None = None
    strict_archival: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _canonical_symbol(self.symbol))
        _require_aware(self.decision_at, "decision_at")
        coordinate = _canonical_coordinate(self.price_coordinate)
        if coordinate is None:
            raise ValueError("price_coordinate must not be empty")
        object.__setattr__(self, "price_coordinate", coordinate)
        canonical_domains = tuple(dict.fromkeys(self.required_domains))
        if not canonical_domains:
            raise ValueError("required_domains must not be empty")
        object.__setattr__(self, "required_domains", canonical_domains)
        if self.observability is not None and not 0.0 <= self.observability <= 1.0:
            raise ValueError("observability must be between 0 and 1")


@dataclass(frozen=True)
class PITJoinResult:
    """Reason-coded result of a single strict as-of join."""

    request: PITJoinRequest
    selected: Mapping[PITDomain, PITDomainRecord]
    domain_flags: Mapping[PITDomain, bool]
    validity: ValidityAssessment
    snapshot_ids: tuple[str, ...]
    max_available_at: datetime | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "selected", MappingProxyType(dict(self.selected)))
        object.__setattr__(self, "domain_flags", MappingProxyType(dict(self.domain_flags)))
        if set(self.domain_flags) != set(self.request.required_domains):
            raise ValueError("domain_flags must cover every required domain exactly")
        if not set(self.selected).issubset(self.domain_flags):
            raise ValueError("selected contains a domain outside domain_flags")
        object.__setattr__(self, "snapshot_ids", tuple(sorted(set(self.snapshot_ids))))
        if self.max_available_at is not None:
            _require_aware(self.max_available_at, "max_available_at")
            if self.max_available_at > self.request.decision_at:
                raise ValueError("max_available_at cannot exceed decision_at")

    @property
    def hard_valid(self) -> bool:
        return self.validity.hard_valid and all(self.domain_flags.values())

    @property
    def data_quality(self) -> float:
        return sum(self.domain_flags.values()) / len(self.domain_flags)

    @property
    def observability(self) -> float | None:
        """Independent evidence score; it is never inferred from data quality."""

        return self.request.observability

    @property
    def join_id(self) -> str:
        return _json_sha256(self.as_dict())

    def as_dict(self) -> dict[str, object]:
        return {
            "data_quality": self.data_quality,
            "decision_at": self.request.decision_at.isoformat(),
            "domain_flags": {
                domain.value: self.domain_flags[domain]
                for domain in self.request.required_domains
            },
            "hard_valid": self.hard_valid,
            "max_available_at": (
                self.max_available_at.isoformat() if self.max_available_at else None
            ),
            "observability": self.observability,
            "pit_mode": (
                "A_STRICT_ARCHIVAL"
                if self.request.strict_archival
                else "B_CAUSAL_RESEARCH"
            ),
            "price_coordinate": self.request.price_coordinate,
            "reasons": [reason.value for reason in self.validity.reasons],
            "selected_record_hashes": {
                domain.value: self.selected[domain].record_sha256
                for domain in self.request.required_domains
                if domain in self.selected
            },
            "snapshot_ids": list(self.snapshot_ids),
            "symbol": self.request.symbol,
        }


def _value_is_complete(record: PITDomainRecord) -> bool:
    values = record.values
    if record.domain is PITDomain.SECURITY_IDENTITY:
        return isinstance(values.get("security_type"), str) and isinstance(
            values.get("listed"), bool
        )
    if record.domain is PITDomain.SECTOR_MEMBERSHIP:
        return isinstance(values.get("sector_id"), str) and bool(values["sector_id"])
    if record.domain is PITDomain.FLOAT_SHARES:
        float_shares = values.get("float_shares")
        return (
            isinstance(float_shares, (int, float))
            and not isinstance(float_shares, bool)
            and float_shares > 0
        )
    if record.domain is PITDomain.CORPORATE_ACTION_STATUS:
        return values.get("coverage_complete") is True
    if record.domain is PITDomain.TRADING_STATUS:
        return isinstance(values.get("trade_status"), str) and isinstance(
            values.get("is_st"), bool
        )
    if record.domain is PITDomain.MARKET_RULE:
        lot_size = values.get("lot_size")
        return (
            isinstance(values.get("board"), str)
            and isinstance(lot_size, int)
            and not isinstance(lot_size, bool)
            and lot_size > 0
            and isinstance(values.get("t_plus_one"), bool)
        )
    return False


def _latest_logical_versions(
    records: list[PITDomainRecord],
) -> tuple[list[PITDomainRecord], bool]:
    """Resolve revisions and report an ambiguous same-time publication."""

    by_record_id: dict[str, list[PITDomainRecord]] = defaultdict(list)
    for record in records:
        by_record_id[record.record_id].append(record)
    latest: list[PITDomainRecord] = []
    for versions in by_record_id.values():
        latest_available_at = max(record.available_at for record in versions)
        same_time = [
            record for record in versions if record.available_at == latest_available_at
        ]
        if len(same_time) != 1:
            return [], True
        latest.append(same_time[0])
    return latest, False


def join_strategy_inputs(
    records: Iterable[PITDomainRecord],
    request: PITJoinRequest,
    *,
    max_records: int = 100_000,
) -> PITJoinResult:
    """Join mandatory domains as known at ``decision_at`` and fail closed.

    A newer revision may replace an older revision only when both share the
    same logical ``record_id``.  Multiple active logical records in one domain
    are treated as an unresolved overlap, never silently tie-broken.
    """

    if max_records <= 0:
        raise ValueError("max_records must be positive")
    bounded = tuple(islice(records, max_records + 1))
    if len(bounded) > max_records:
        raise ValueError(f"records exceeds max_records={max_records}")

    selected: dict[PITDomain, PITDomainRecord] = {}
    flags = {domain: False for domain in request.required_domains}
    reasons: list[ValidityReason] = []

    for domain in request.required_domains:
        visible = [
            record
            for record in bounded
            if record.domain is domain
            and record.symbol == request.symbol
            and record.is_effective_at(request.decision_at)
            and record.available_at <= request.decision_at
        ]
        if not visible:
            reasons.append(_MISSING_REASON[domain])
            continue
        if request.strict_archival and any(
            not record.available_at_observed for record in visible
        ):
            reasons.extend((ValidityReason.MODELED_AVAILABLE_AT, _MISSING_REASON[domain]))
            continue
        if request.strict_archival and any(
            not record.strict_pit_eligible for record in visible
        ):
            reasons.extend(
                (ValidityReason.MISSING_RECORD_VERSION_LINEAGE, _MISSING_REASON[domain])
            )
            continue

        latest, ambiguous_revision = _latest_logical_versions(visible)
        if ambiguous_revision or len(latest) != 1:
            reasons.append(ValidityReason.CROSS_TABLE_INCONSISTENT)
            continue
        record = latest[0]
        if not _value_is_complete(record):
            reasons.append(ValidityReason.NULL_REQUIRED_FIELD)
            continue
        if (
            record.price_coordinate is not None
            and record.price_coordinate != request.price_coordinate
        ):
            reasons.append(ValidityReason.PRICE_COORDINATE_MISMATCH)
            continue
        selected[domain] = record
        flags[domain] = True

    selected_records = tuple(selected.values())
    max_available_at = (
        max(record.available_at for record in selected_records)
        if selected_records
        else None
    )
    return PITJoinResult(
        request=request,
        selected=selected,
        domain_flags=flags,
        validity=ValidityAssessment(tuple(reasons)),
        snapshot_ids=tuple(record.snapshot_id for record in selected_records),
        max_available_at=max_available_at,
    )
