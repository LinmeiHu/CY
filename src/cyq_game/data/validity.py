"""Reason-coded validity for data joins and strategy-state eligibility."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ValidityReason(StrEnum):
    """Stable reason codes explaining why a record or joined sample is not strict."""

    MODELED_AVAILABLE_AT = "MODELED_AVAILABLE_AT"
    MISSING_RECORD_VERSION_LINEAGE = "MISSING_RECORD_VERSION_LINEAGE"
    MISSING_SECURITY_IDENTITY = "MISSING_SECURITY_IDENTITY"
    MISSING_SECTOR_MEMBERSHIP = "MISSING_SECTOR_MEMBERSHIP"
    MISSING_FLOAT_SHARES = "MISSING_FLOAT_SHARES"
    MISSING_CORPORATE_ACTION_STATUS = "MISSING_CORPORATE_ACTION_STATUS"
    MISSING_TRADING_STATUS = "MISSING_TRADING_STATUS"
    MISSING_MARKET_RULE = "MISSING_MARKET_RULE"
    CROSS_TABLE_INCONSISTENT = "CROSS_TABLE_INCONSISTENT"
    NULL_REQUIRED_FIELD = "NULL_REQUIRED_FIELD"
    PRICE_COORDINATE_MISMATCH = "PRICE_COORDINATE_MISMATCH"


@dataclass(frozen=True)
class ValidityAssessment:
    """An immutable, composable validity result.

    ``hard_valid`` is derived from reason codes so callers cannot accidentally
    label an invalid sample as valid while retaining unresolved failures.
    """

    reasons: tuple[ValidityReason, ...] = ()

    def __post_init__(self) -> None:
        canonical = tuple(sorted(set(self.reasons), key=str))
        object.__setattr__(self, "reasons", canonical)

    @property
    def hard_valid(self) -> bool:
        return not self.reasons

    def merge(self, *others: ValidityAssessment) -> ValidityAssessment:
        reasons = list(self.reasons)
        for other in others:
            reasons.extend(other.reasons)
        return ValidityAssessment(tuple(reasons))

    @classmethod
    def from_reasons(cls, *reasons: ValidityReason) -> ValidityAssessment:
        return cls(tuple(reasons))


def assess_strategy_inputs(
    *,
    observed_available_at: bool,
    record_version_lineage: bool,
    security_identity: bool,
    sector_membership: bool,
    float_shares: bool,
    corporate_actions: bool,
    trading_status: bool,
    market_rules: bool,
    cross_table_consistency: bool,
    raw_price_coordinate: bool,
) -> ValidityAssessment:
    """Evaluate the mandatory inputs for a strict CYQ strategy state."""

    checks = (
        (observed_available_at, ValidityReason.MODELED_AVAILABLE_AT),
        (record_version_lineage, ValidityReason.MISSING_RECORD_VERSION_LINEAGE),
        (security_identity, ValidityReason.MISSING_SECURITY_IDENTITY),
        (sector_membership, ValidityReason.MISSING_SECTOR_MEMBERSHIP),
        (float_shares, ValidityReason.MISSING_FLOAT_SHARES),
        (corporate_actions, ValidityReason.MISSING_CORPORATE_ACTION_STATUS),
        (trading_status, ValidityReason.MISSING_TRADING_STATUS),
        (market_rules, ValidityReason.MISSING_MARKET_RULE),
        (cross_table_consistency, ValidityReason.CROSS_TABLE_INCONSISTENT),
        (raw_price_coordinate, ValidityReason.PRICE_COORDINATE_MISMATCH),
    )
    return ValidityAssessment(tuple(reason for passed, reason in checks if not passed))
