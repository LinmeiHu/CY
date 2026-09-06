#!/usr/bin/env python3
"""Pure, fail-closed Stage-B replay logic for V30.

This module deliberately has no data-loading or publication code.  A separately
frozen builder must project the accepted Stage-A cohort, the bounded CY-033
daily rows, direct QD-004 minute rows, QD-010 action envelopes and the market
calendar into the narrow mappings consumed here.

The implementation is intentionally conservative.  A completed minute bar is
an execution *proxy*, never a real fill claim.  Any missing prefix, ambiguous
action clock, noncanonical cent, broken lineage or incomplete terminal ledger
produces UNKNOWN and prevents aggregate publication.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import time
from decimal import (
    ROUND_CEILING,
    ROUND_FLOOR,
    ROUND_HALF_UP,
    Decimal,
    InvalidOperation,
    localcontext,
)
from fractions import Fraction
from typing import Any, Literal

import numpy as np
import pandas as pd

EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-CAUSAL-DEMAND-RECAPTURE-V30"
PROTOCOL_VERSION = "V30_CAUSAL_STAGE_B_PURE_LOGIC_DRAFT_V1"
DEVELOPMENT_START = pd.Timestamp("2018-01-01")
DEVELOPMENT_END = pd.Timestamp("2021-12-31")
DEVELOPMENT_YEARS = (2018, 2019, 2020, 2021)
FROZEN_CALENDAR_ROW_COUNT = 973
FROZEN_CALENDAR_MIN_DATE = pd.Timestamp("2018-01-02")
FROZEN_CALENDAR_MAX_DATE = pd.Timestamp("2021-12-31")
FROZEN_CALENDAR_DERIVATION = "CY033_DISTINCT_TRADE_DATE_SORT_ASC_ZERO_BASED"
FROZEN_CALENDAR_CANONICAL_SHA256 = (
    "bf5da2b2e1436758b59086d3a6cb29952ed9b3385309c7e445876f8b18490e8a"
)
FROZEN_CALENDAR_NEWLINE_SHA256 = "220988be72d36581dfbf279730116ae34427df21f192fca2cd7972f1c67b3676"

TARGET_LAST_OFFSET = 10
FAILURE_LAST_OFFSET = 9
TIME_FIRST_OFFSET = 11
TERMINAL_OFFSET = 30
ORDER_SIZE_SHARES = 100
ENTRY_MIN_PROXY_VOLUME_SHARES = 10_000
MIN_PROXY_VOLUME_SHARES = 10_000
PER_SIDE_FEE = Decimal("0.002")
MIN_ACCEPTED = 201
MIN_MEAN_RETURN = Decimal("0.04")
MIN_MEAN_RETURN_FRACTION = Fraction(1, 25)
MAX_MEAN_HOLDING_EXCLUSIVE = Decimal("15")
MAX_MEAN_HOLDING_EXCLUSIVE_FRACTION = Fraction(15, 1)
RATIO_DISPLAY_DECIMAL_PLACES = 18
EXECUTION_PROXY_NAME = "CONSERVATIVE_1M_BAR_EXECUTION_PROXY"
REAL_FILL_CLAIMED = False
QD004_SOURCE = "day_parquet_none"
QD004_PERIOD = "1m"
QD004_ADJUST = "none"
QD004_SOURCE_MANIFEST_SHA256 = "b1a6c88996e5015a23544d63398b49d5dd269d50c71567dc03344fbb83e69e8e"
QD004_DEVELOPMENT_PARTITION_SHA256 = {
    2018: "83fbb3e0fda4b278e1072836a9695b7d9a6dfa396a07248e40f85db0d2ba0812",
    2019: "b31fccebb8f2319099b412233263dbc99f965a091b0995e62d275997b411130c",
    2020: "67d6b958f2b4113750df8f1a98d6e48d93ef00e04cab0fbf0cf0661b1600d45e",
    2021: "efd3b1a4bf60c47ba36b83792c97fc08d600aa8cde58014ff44e3c005eebac61",
}
CY033_DEVELOPMENT_PARTITION_SHA256 = {
    2018: "b906d2c21fd35128b8f65f1b00fa12ae6e5bd9ee476a368a63881304f38ceed4",
    2019: "c69a464e4a04efdca0177a8a09a13a34646531afa37a2b35b4892fd40ec3ebfd",
    2020: "1b0a00c6d2cfbce0ae4f907e1ee9dc5006f59677d556cc10f8f34a9893937c62",
    2021: "cbd4b2d2ccdff32b09ed1a2e9347f8045cde89ff7e4e1b189577bc353e4d9311",
}
QD010_SOURCE_SHA256 = {
    "distributions": "5982b7dd75ec53deb9ce3874aaf3e4a5168a731b5bbd6d8c2d89258fe4aff387",
    "rights_issues": "07e864ac6da1d59b69c1b9ce1bcdd01d96d913d0909a718d79627939f8ab87cb",
}
QD010_CANONICAL_SYMBOL_REFERENCE_SHA256 = (
    "8ea136aa024120bea2b175f50bab5e6c416e27a276e9be390f16ae7b31cc3962"
)
ACTION_ENVELOPE_TYPE = "V30_QD010_CANDIDATE_QUERY_ENVELOPE_V1"
ACTION_QUERY_PREDICATE = (
    "canonical_symbol=:candidate_symbol AND effective_date>:entry_date "
    "AND effective_date<=:terminal_date AND known_at<=:knowledge_cutoff"
)
SESSION_ORDER_FREEZE_CLOCK = time(9, 14, 59)
SESSION_ORDER_SUBMIT_CLOCK = time(9, 15)
AMOUNT_ARM = "V30_AMOUNT_1X_TO_2X_CAP25"
SHARE_VOLUME_ARM = "V30_SHARE_VOLUME_1X_AMOUNT_LE_2X_CAP25"
SIGNAL_ARMS = frozenset({AMOUNT_ARM, SHARE_VOLUME_ARM})

EXPECTED_BAR_END_TIMES = (
    time(9, 30),
    *(time(9, minute) for minute in range(31, 60)),
    *(time(10, minute) for minute in range(0, 60)),
    *(time(11, minute) for minute in range(0, 31)),
    *(time(13, minute) for minute in range(1, 60)),
    *(time(14, minute) for minute in range(0, 60)),
    time(15, 0),
)
if len(EXPECTED_BAR_END_TIMES) != 241:  # pragma: no cover - import invariant
    raise RuntimeError("V30 Stage-B minute grid is not 241 bars")

SUPPORTED_ACTION_KINDS = frozenset({"CASH_ONLY", "RISK_SHARE", "RISK_RIGHTS"})
RISK_ACTION_KINDS = frozenset({"RISK_SHARE", "RISK_RIGHTS"})
KNOWN_AT_PRECISIONS = frozenset({"EXACT_TIMESTAMP", "DAY_ONLY"})
EXIT_REASONS = frozenset({"A67_TARGET", "PIVOT_FAILURE", "H10_TIME", "PRE_ACTION_RISK"})
COMPLETE_OUTCOME = "COMPLETE_EXIT"
UNKNOWN_OUTCOME = "UNKNOWN"
UNEXITED_OUTCOME = "UNEXITED_H30"
NOT_OPENED_OUTCOME = "UNKNOWN_NOT_OPENED_AFTER_PRIOR_UNRESOLVED"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CANONICAL_DECIMAL_RE = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?$")
CALENDAR_FIELDS = ("trade_date", "calendar_index")
ACCEPTED_ENTRY_FIELDS = (
    "stage_a_cohort_frozen",
    "entry_evidence_accepted",
    "entry_settlement_status",
    "entry_evidence_status",
    "entry_execution_proxy_label",
    "real_fill_claimed",
    "entry_hard_valid",
    "protocol_arm",
    "gap_id",
    "symbol",
    "signal_date",
    "entry_date",
    "entry_calendar_index",
    "entry_decision_at",
    "order_effective_at",
    "proxy_interval_start_time",
    "proxy_bar_end_time",
    "proxy_worst_buy_tick",
    "proxy_bar_volume_exact",
    "proxy_bar_amount_exact",
    "confirmation_volume_exact",
    "confirmation_amount_exact",
    "signal_close_tick",
    "raw_l_tick",
    "reclaimed_pivot_tick",
    "cap25_rank",
    "universal_minimum_up_cap_tick",
    "max_headroom_buy_tick",
    "frozen_buy_limit_tick",
    "confirmation_row_sha256",
    "cooldown_row_sha256",
    "execution_proxy_row_sha256",
    "signal_snapshot_id",
    "signal_daily_snapshot_id",
    "signal_corporate_action_snapshot_id",
)
DAILY_PROJECTION_FIELDS = (
    "protocol_arm",
    "gap_id",
    "symbol",
    "session_offset",
    "trade_date",
    "source_match_count",
    "decision_at",
    "available_at",
    "decision_timezone",
    "close_tick",
    "snapshot_id",
    "daily_snapshot_id",
    "trading_state_snapshot_id",
    "corporate_action_snapshot_id",
    "bar_valid",
    "trading_state_valid",
    "corporate_action_valid",
    "market_rule_valid",
    "hard_valid",
    "corporate_action_blocking",
    "corporate_action_count",
    "corporate_action_ids",
    "cash_cents_per_original_share",
    "share_multiplier",
    "rights_ratio",
    "rights_price_cents",
    "trade_status",
    "current_day_data_tradable",
    "daily_volume",
    "daily_amount",
    "source_locator",
    "partition_sha256",
    "row_sha256",
)
MINUTE_SCAFFOLD_FIELDS = (
    "protocol_arm",
    "gap_id",
    "candidate_symbol",
    "session_offset",
    "qmt_code",
    "symbol",
    "exchange",
    "period",
    "adjust",
    "source",
    "trade_date",
    "bar_end_time",
    "available_at",
    "source_match_count",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "query_locator",
    "query_partition_sha256",
    "physical_source_locator",
    "source_snapshot_id",
    "row_sha256",
)
ACTION_PROJECTION_FIELDS = (
    "protocol_arm",
    "gap_id",
    "candidate_symbol",
    "event_id",
    "raw_event_id",
    "raw_revision_id",
    "vintage_id",
    "source_row_hash",
    "permitted_projection_sha256",
    "raw_symbol",
    "canonical_symbol",
    "action_kind",
    "effective_date",
    "known_at",
    "available_at",
    "known_at_precision",
    "cash_cents_per_original_share",
    "share_multiplier",
    "rights_ratio",
    "rights_price_cents",
    "source_terms_complete",
    "snapshot_id",
    "source_table",
    "source_locator",
    "source_partition_sha256",
)
ACTION_ENVELOPE_FIELDS = (
    "envelope_type",
    "protocol_arm",
    "gap_id",
    "candidate_symbol",
    "query_predicate",
    "effective_date_min_exclusive",
    "effective_date_max_inclusive",
    "knowledge_cutoff",
    "expected_source_partitions",
    "canonical_symbol_reference_sha256",
    "source_match_count_by_partition",
    "raw_source_match_count",
    "projected_row_count",
    "query_complete",
    "snapshot_id",
    "vintage_id",
    "normalized_ledger_sha256",
    "query_scope_sha256",
    "completeness_sha256",
    "rows",
)

MINUTE_SCAFFOLD_ONLY_FIELDS = (
    "protocol_arm",
    "gap_id",
    "candidate_symbol",
    "session_offset",
    "trade_date",
    "bar_end_time",
    "source_match_count",
    "query_locator",
    "query_partition_sha256",
)
MINUTE_PHYSICAL_FIELDS = tuple(
    field for field in MINUTE_SCAFFOLD_FIELDS if field not in MINUTE_SCAFFOLD_ONLY_FIELDS
)
DAILY_SCAFFOLD_ONLY_FIELDS = (
    "protocol_arm",
    "gap_id",
    "symbol",
    "session_offset",
    "trade_date",
    "source_match_count",
)
DAILY_PHYSICAL_FIELDS = tuple(
    field for field in DAILY_PROJECTION_FIELDS if field not in DAILY_SCAFFOLD_ONLY_FIELDS
)


class V30StageBError(RuntimeError):
    """Base error for a frozen-contract or programmer invariant violation."""


class UnknownEvidence(V30StageBError):
    """Required evidence is absent, ambiguous, late or noncanonical."""


@dataclass(frozen=True)
class CalendarSession:
    trade_date: pd.Timestamp
    calendar_index: int


@dataclass(frozen=True)
class AcceptedEntry:
    stage_a_cohort_frozen: bool
    entry_evidence_accepted: bool
    entry_hard_valid: bool
    entry_settlement_status: str
    entry_evidence_status: str
    entry_execution_proxy_label: str
    real_fill_claimed: bool
    protocol_arm: str
    gap_id: str
    symbol: str
    signal_date: pd.Timestamp
    entry_date: pd.Timestamp
    entry_calendar_index: int
    entry_decision_at: pd.Timestamp
    entry_tick: int
    proxy_bar_volume: int
    proxy_bar_amount: Decimal
    confirmation_volume: int
    confirmation_amount: Decimal
    signal_close_tick: int
    raw_l_tick: int
    persisted_reclaimed_pivot_tick: int
    cap25_rank: int
    order_effective_at: pd.Timestamp
    proxy_interval_start_at: pd.Timestamp
    proxy_bar_end_at: pd.Timestamp
    universal_minimum_up_cap_tick: int
    max_headroom_buy_tick: int
    frozen_buy_limit_tick: int
    confirmation_row_sha256: str
    cooldown_row_sha256: str
    execution_proxy_row_sha256: str
    signal_snapshot_id: str
    signal_daily_snapshot_id: str
    signal_corporate_action_snapshot_id: str


@dataclass(frozen=True)
class ActionEvent:
    protocol_arm: str
    gap_id: str
    candidate_symbol: str
    event_id: str
    raw_event_id: str
    raw_revision_id: str
    vintage_id: str
    source_row_hash: str
    permitted_projection_sha256: str
    raw_symbol: str
    canonical_symbol: str
    action_kind: str
    effective_date: pd.Timestamp
    known_at: pd.Timestamp
    available_at: pd.Timestamp
    known_at_precision: str
    cash_cents_per_original_share: Any
    share_multiplier: Any
    rights_ratio: Any
    rights_price_cents: Any
    source_terms_complete: Any
    snapshot_id: str
    source_table: str
    source_locator: str
    source_partition_sha256: str


@dataclass(frozen=True)
class ActionQueryEnvelope:
    envelope_type: str
    protocol_arm: str
    gap_id: str
    candidate_symbol: str
    query_predicate: str
    effective_date_min_exclusive: pd.Timestamp
    effective_date_max_inclusive: pd.Timestamp
    knowledge_cutoff: pd.Timestamp
    expected_source_partitions: tuple[tuple[str, str], ...]
    canonical_symbol_reference_sha256: str
    snapshot_id: str
    vintage_id: str
    source_match_count_by_partition: tuple[tuple[str, int], ...]
    raw_source_match_count: int
    projected_row_count: int
    query_complete: bool
    normalized_ledger_sha256: str
    query_scope_sha256: str
    completeness_sha256: str
    events: tuple[ActionEvent, ...]


@dataclass(frozen=True)
class StageBReplayEvidence:
    daily_projection: Any
    minute_projection: Any
    action_envelope: ActionQueryEnvelope | Mapping[str, Any]


@dataclass(frozen=True)
class ActionTerms:
    cash_cents_per_original_share: Decimal
    share_multiplier: Decimal
    rights_ratio: Decimal
    rights_price_cents: Decimal


@dataclass(frozen=True)
class RiskSpec:
    event: ActionEvent
    cancellation_index: int
    earliest_order_index: int
    effective_index: int


@dataclass(frozen=True)
class ValidDaily:
    offset: int
    trade_date: pd.Timestamp
    close_tick: int
    trade_status: int
    current_day_data_tradable: bool
    daily_volume: int
    daily_amount: Decimal
    row_sha256: str


@dataclass(frozen=True)
class ValidMinute:
    offset: int
    trade_date: pd.Timestamp
    bar_end_time: pd.Timestamp
    open_tick: int
    high_tick: int
    low_tick: int
    close_tick: int
    volume: int
    amount: Decimal
    row_sha256: str


@dataclass(frozen=True)
class SellExecutionQuantityBound:
    source_ohlcva_conditional_lower_bound_shares: int
    raw_amount_cents: Decimal
    conservative_amount_cents: int
    outward_adjustment_cents: Decimal
    classification: Literal[
        "FULL_PROXY",
        "POSSIBLE_PARTIAL_OR_FULL",
        "SAFE_NO_FILL",
        "NO_TRADES",
    ]
    evidence_sha256: str


@dataclass(frozen=True)
class SessionScan:
    status: Literal[
        "FILLED",
        "NO_FILL",
        "TARGET_CANCELLED_FOR_RISK",
        "POSSIBLE_PARTIAL_UNKNOWN",
    ]
    exit_tick: int | None = None
    exit_at: pd.Timestamp | None = None
    complete_physical_session: bool = False
    all_physical_rows_zero_volume: bool = False
    reached_evidence_sha256: tuple[str, ...] = ()
    blocker: str | None = None


@dataclass(frozen=True)
class StageBOutcome:
    protocol_arm: str
    gap_id: str
    symbol: str
    signal_date: pd.Timestamp
    entry_date: pd.Timestamp
    entry_calendar_index: int
    entry_tick: int
    outcome_status: str
    exit_reason: str | None = None
    exit_date: pd.Timestamp | None = None
    exit_at: pd.Timestamp | None = None
    exit_calendar_index: int | None = None
    exit_tick: int | None = None
    holding_sessions: int | None = None
    gross_coordinate_cash_cents_per_original_share: str | None = None
    entry_cash_out_cents: str | None = None
    exit_cash_in_cents: str | None = None
    cash_distribution_performance_credit_cents: str | None = None
    net_return_numerator: int | None = None
    net_return_denominator: int | None = None
    net_return: str | None = None
    blocker: str | None = None
    reached_evidence_sha256: tuple[str, ...] = ()
    outcome_evidence_sha256: str | None = None
    execution_proxy_name: str = EXECUTION_PROXY_NAME
    real_fill_claimed: bool = REAL_FILL_CLAIMED


@dataclass(frozen=True)
class AcceptedEntrySealRow:
    protocol_arm: str
    gap_id: str
    symbol: str
    signal_date: pd.Timestamp
    entry_date: pd.Timestamp
    entry_evidence_sha256: str


@dataclass(frozen=True)
class StageACohortSeal:
    protocol_arm: str
    accepted_count: int
    accepted_cohort_sha256: str
    accepted_key_evidence_sha256: str


@dataclass(frozen=True)
class StageBReplaySeal:
    selected_arm: str
    accepted_count: int
    stage_a_accepted_cohort_sha256: str
    stage_a_accepted_key_evidence_sha256: str
    accepted_rows: tuple[AcceptedEntrySealRow, ...]
    outcomes: tuple[StageBOutcome, ...]
    outcome_evidence_sha256: tuple[str, ...]
    terminal_ledger_sha256: str
    replay_seal_sha256: str


def _records(
    value: Any,
    label: str,
    *,
    expected_fields: tuple[str, ...] | None = None,
) -> list[Mapping[str, Any]]:
    if isinstance(value, pd.DataFrame):
        if expected_fields is None:
            raise V30StageBError(f"{label} DataFrame boundary lacks an exact projection")
        if tuple(value.columns) != expected_fields:
            raise UnknownEvidence(
                f"{label} DataFrame columns do not match the exact ordered projection"
            )
        return list(value.to_dict(orient="records"))
    if value is None:
        return []
    if isinstance(value, Mapping):
        raise V30StageBError(f"{label} must be a sequence, not one mapping")
    try:
        rows = list(value)
    except TypeError as exc:
        raise V30StageBError(f"{label} is not iterable") from exc
    if any(not isinstance(row, Mapping) for row in rows):
        raise V30StageBError(f"{label} contains a non-mapping row")
    return rows


def _required(row: Mapping[str, Any], field: str, label: str) -> Any:
    try:
        return row[field]
    except (KeyError, TypeError) as exc:
        raise UnknownEvidence(f"{label} lacks {field}") from exc


def _require_exact_fields(
    row: Mapping[str, Any], expected: tuple[str, ...], label: str
) -> None:
    actual = tuple(row)
    if any(not isinstance(field, str) for field in actual):
        raise UnknownEvidence(f"{label} projection contains a non-string field name")
    if actual != expected:
        expected_set = set(expected)
        actual_set = set(actual)
        missing = sorted(expected_set - actual_set)
        extras = sorted(actual_set - expected_set)
        raise UnknownEvidence(
            f"{label} projection schema drift or reordered fields; "
            f"missing={missing}, extras={extras}"
        )


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise UnknownEvidence(f"{label} is not a nonempty exact string")
    return value


def _sha256(value: Any, label: str) -> str:
    text = _exact_string(value, label)
    if _SHA256_RE.fullmatch(text) is None:
        raise UnknownEvidence(f"{label} is not a lowercase SHA-256")
    return text


def _decimal(value: Any, label: str) -> Decimal:
    if value is None or isinstance(value, (bool, np.bool_)):
        raise UnknownEvidence(f"{label} is not a finite Decimal")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, (int, np.integer)):
        result = Decimal(int(value))
    elif isinstance(value, str):
        if (
            value != value.strip()
            or _CANONICAL_DECIMAL_RE.fullmatch(value) is None
            or value in {"-0", "-0.0"}
        ):
            raise UnknownEvidence(f"{label} is not a canonical decimal string")
        try:
            result = Decimal(value)
        except InvalidOperation as exc:  # pragma: no cover - regex guards syntax
            raise UnknownEvidence(f"{label} is not Decimal-compatible") from exc
    else:
        raise UnknownEvidence(f"{label} rejects binary floating-point input")
    if not result.is_finite():
        raise UnknownEvidence(f"{label} is not finite")
    return result


def _exact_decimal_sum(values: Sequence[Decimal]) -> Decimal:
    """Add finite Decimals by integer coefficients without context rounding."""
    if not values:
        return Decimal(0)
    if any(not value.is_finite() for value in values):
        raise V30StageBError("cannot exactly sum a nonfinite Decimal")
    minimum_exponent = min(value.as_tuple().exponent for value in values)
    total = 0
    for value in values:
        sign, digits, exponent = value.as_tuple()
        coefficient = int("".join(str(digit) for digit in digits)) if digits else 0
        if sign:
            coefficient = -coefficient
        total += coefficient * 10 ** (exponent - minimum_exponent)
    sign = int(total < 0)
    absolute = str(abs(total))
    return Decimal((sign, tuple(int(character) for character in absolute), minimum_exponent))


def _source_float64_projection(
    value: Any, label: str, *, require_finite: bool
) -> tuple[np.float64, str, Decimal | None]:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (float, np.float64)):
        raise UnknownEvidence(f"{label} is not a native float64 source value")
    source = np.float64(value)
    bits = int(np.asarray([source], dtype="<f8").view("<u8")[0])
    widened = float(source)
    if require_finite and not math.isfinite(widened):
        raise UnknownEvidence(f"{label} is not finite")
    decimal = Decimal.from_float(widened) if math.isfinite(widened) else None
    return source, f"{bits:016x}", decimal


def _source_float64_decimal(value: Any, label: str) -> tuple[Decimal, str]:
    _, bits, decimal = _source_float64_projection(value, label, require_finite=True)
    assert decimal is not None
    return decimal, bits


def qd004_float64_volume_shares(value: Any, label: str = "QD004 volume") -> tuple[int, str]:
    source, bits, decimal = _source_float64_projection(value, label, require_finite=True)
    assert decimal is not None
    if source < 0 or source > 2**53 or decimal != decimal.to_integral_value():
        raise UnknownEvidence(f"{label} is not an exact nonnegative <=2^53 share count")
    shares = int(source)
    if shares > np.iinfo(np.int64).max:
        raise UnknownEvidence(f"{label} is outside int64")
    return shares, bits


def _nonnegative_decimal(value: Any, label: str) -> Decimal:
    result = _decimal(value, label)
    if result < 0:
        raise UnknownEvidence(f"{label} is negative")
    return result


def _positive_decimal(value: Any, label: str) -> Decimal:
    result = _decimal(value, label)
    if result <= 0:
        raise UnknownEvidence(f"{label} is not positive")
    return result


def _exact_int(value: Any, label: str, *, minimum: int | None = None) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise UnknownEvidence(f"{label} is not an exact integer")
    result = int(value)
    int64 = np.iinfo(np.int64)
    if result < int64.min or result > int64.max:
        raise UnknownEvidence(f"{label} is outside int64")
    if minimum is not None and result < minimum:
        raise UnknownEvidence(f"{label} is below {minimum}")
    return result


def _positive_tick(value: Any, label: str) -> int:
    return _exact_int(value, label, minimum=1)


def _exact_bool(value: Any, expected: bool | None, label: str) -> bool:
    if not isinstance(value, (bool, np.bool_)):
        raise UnknownEvidence(f"{label} is not an exact boolean")
    result = bool(value)
    if expected is not None and result is not expected:
        raise UnknownEvidence(f"{label} is not exact {expected}")
    return result


def _local_timestamp(value: Any, label: str) -> pd.Timestamp:
    if isinstance(value, str) and value != value.strip():
        raise UnknownEvidence(f"{label} timestamp text has surrounding whitespace")
    try:
        result = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise UnknownEvidence(f"{label} is not a timestamp") from exc
    if pd.isna(result):
        raise UnknownEvidence(f"{label} is missing")
    if result.tzinfo is not None:
        raise UnknownEvidence(f"{label} must be local-naive Asia/Shanghai time")
    return result


def _date(value: Any, label: str) -> pd.Timestamp:
    result = _local_timestamp(value, label)
    if result != result.normalize():
        raise UnknownEvidence(f"{label} is not a midnight date")
    return result


def _exact_string(value: Any, label: str) -> str:
    return _nonempty(value, label)


def canonicalize_qd010_symbol(raw_symbol: Any) -> str:
    """Byte-for-semantics binding to ``full_market._canonical_symbol_sql``.

    This deliberately does *not* apply the accepted-candidate SH/SZ grammar.
    The SQL helper first preserves any case-insensitive SH/SZ/BJ suffix, then
    routes six-character 92/4/8 codes to BJ, 5/6/9 codes to SH, and every
    other six-character value to SZ.  Candidate validation is a separate step.
    """
    if not isinstance(raw_symbol, str) or not raw_symbol:
        raise UnknownEvidence("QD010 raw symbol is empty")
    text = raw_symbol.upper()
    if text.endswith((".SH", ".SZ", ".BJ")):
        return text
    if len(raw_symbol) != 6:
        raise UnknownEvidence("QD010 raw symbol shape is invalid")
    if raw_symbol[:2] == "92" or raw_symbol[:1] in {"4", "8"}:
        return f"{raw_symbol}.BJ"
    if raw_symbol[:1] in {"5", "6", "9"}:
        return f"{raw_symbol}.SH"
    return f"{raw_symbol}.SZ"


def canonical_candidate_symbol(value: Any, label: str = "candidate symbol") -> str:
    """Require a distinct exact six-digit Main/ChiNext CODE.EXCHANGE key."""
    text = _exact_string(value, label)
    if text != text.upper() or len(text) != 9 or text[6] != ".":
        raise UnknownEvidence(f"{label} is not exact CODE.EXCHANGE")
    code, exchange = text[:6], text[7:]
    if not code.isdigit() or exchange not in {"SH", "SZ"}:
        raise UnknownEvidence(f"{label} is outside the frozen SH/SZ scope")
    if canonicalize_qd010_symbol(code) != text:
        raise UnknownEvidence(f"{label} conflicts with the bound exchange semantics")
    return text


def qd004_float32_cent_tick(value: Any, label: str = "QD004 price") -> int:
    """Decode one cent only by exact reproduction of the source float32 bits."""
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (float, np.float64)):
        raise UnknownEvidence(f"{label} is not a native float64 source value")
    try:
        source = np.float32(value)
        widened = float(source)
        original = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise UnknownEvidence(f"{label} is not float32-compatible") from exc
    if not math.isfinite(widened) or widened <= 0 or original != widened:
        raise UnknownEvidence(f"{label} is not an exact positive float32 widening")
    source_bits = int(np.asarray([source], dtype="<f4").view("<u4")[0])
    scaled = Decimal.from_float(widened) * 100
    candidate = int(scaled.to_integral_value(rounding=ROUND_HALF_UP))
    matches = []
    for tick in range(max(1, candidate - 1), candidate + 2):
        encoded = np.float32(tick / 100.0)
        bits = int(np.asarray([encoded], dtype="<f4").view("<u4")[0])
        if bits == source_bits:
            matches.append(tick)
    if matches != [candidate]:
        raise UnknownEvidence(f"{label} is not one unique float32-encoded cent")
    return candidate


def canonical_daily_cent_tick(value: Any, label: str = "daily price") -> int:
    cents = _positive_decimal(value, label) * 100
    if cents != cents.to_integral_value():
        raise UnknownEvidence(f"{label} is not an exact whole cent")
    return _positive_tick(int(cents), label)


def ceil_decimal_to_tick(value: Decimal, label: str) -> int:
    if not value.is_finite() or value <= 0:
        raise UnknownEvidence(f"{label} is not a positive finite cent coordinate")
    result = int(value.to_integral_value(rounding=ROUND_CEILING))
    return _positive_tick(result, label)


def round_half_up_tick(value: Decimal, label: str) -> int:
    if not value.is_finite() or value <= 0:
        raise UnknownEvidence(f"{label} is not a positive finite cent coordinate")
    result = int(value.to_integral_value(rounding=ROUND_HALF_UP))
    return _positive_tick(result, label)


def a67_target_tick(entry_tick: int, raw_l_tick: int, cash_cents: Decimal) -> int:
    entry = _positive_tick(entry_tick, "entry_tick")
    raw_l = _positive_tick(raw_l_tick, "raw_l_tick")
    cash = _nonnegative_decimal(cash_cents, "cumulative cash cents")
    raw_target = Decimal(33 * entry + 67 * raw_l) / Decimal(100)
    return ceil_decimal_to_tick(_exact_decimal_sum((raw_target, -cash)), "cash-adjusted A67 target")


def adjusted_pivot_tick(persisted_pivot_tick: int, cash_cents: Decimal) -> int:
    pivot = _positive_tick(persisted_pivot_tick, "persisted pivot")
    cash = _nonnegative_decimal(cash_cents, "cumulative cash cents")
    return ceil_decimal_to_tick(_exact_decimal_sum((Decimal(pivot), -cash)), "cash-adjusted pivot")


def universal_price_band_ticks(
    previous_reference_tick: int, cash_today_cents: Decimal
) -> tuple[int, int]:
    official_ex_reference = exchange_reference_tick(previous_reference_tick, cash_today_cents)
    d5 = round_half_up_tick(
        Decimal(official_ex_reference) * Decimal(95) / Decimal(100),
        "universal D5 tick",
    )
    u5 = round_half_up_tick(
        Decimal(official_ex_reference) * Decimal(105) / Decimal(100),
        "universal U5 tick",
    )
    if d5 > u5:
        raise UnknownEvidence("universal price band is inverted")
    return d5, u5


def exchange_reference_tick(previous_reference_tick: int, cash_today_cents: Decimal) -> int:
    previous = _positive_tick(previous_reference_tick, "previous exchange-reference tick")
    cash_today = _nonnegative_decimal(cash_today_cents, "effective-session cash cents")
    return round_half_up_tick(
        _exact_decimal_sum((Decimal(previous), -cash_today)),
        "official cash ex-reference",
    )


def universal_d5_tick(previous_reference_tick: int, cash_today_cents: Decimal) -> int:
    return universal_price_band_ticks(previous_reference_tick, cash_today_cents)[0]


def target_sell_limit_tick(
    entry_tick: int,
    raw_l_tick: int,
    cumulative_cash_cents: Decimal,
    previous_reference_tick: int,
    cash_today_cents: Decimal,
) -> int | None:
    target = a67_target_tick(entry_tick, raw_l_tick, cumulative_cash_cents)
    d5, u5 = universal_price_band_ticks(previous_reference_tick, cash_today_cents)
    frozen_limit = max(target, d5)
    if frozen_limit > u5:
        return None
    return frozen_limit


def max_headroom_buy_tick(raw_l_tick: int) -> int:
    """Recompute the greatest entry cent retaining the frozen A67 4% net floor."""
    raw_l = _positive_tick(raw_l_tick, "raw L tick")

    def viable(entry: int) -> bool:
        target = a67_target_tick(entry, raw_l, Decimal(0))
        return target < raw_l and target * 998 * 100 >= entry * 1002 * 104

    lower = 1
    upper = raw_l - 1
    best = 0
    while lower <= upper:
        middle = (lower + upper) // 2
        if viable(middle):
            best = middle
            lower = middle + 1
        else:
            upper = middle - 1
    if best <= 0:
        raise UnknownEvidence("raw L has no A67 four-percent viable entry tick")
    return best


def forced_sell_limit_tick(previous_reference_tick: int, cash_today_cents: Decimal) -> int:
    d5, u5 = universal_price_band_ticks(previous_reference_tick, cash_today_cents)
    frozen_limit = d5
    if frozen_limit > u5:
        raise UnknownEvidence("forced sell limit is outside the universal legal band")
    return frozen_limit


def normalize_market_calendar(value: Any) -> tuple[CalendarSession, ...]:
    if isinstance(value, tuple) and all(isinstance(item, CalendarSession) for item in value):
        rows: list[Mapping[str, Any]] = [
            {"trade_date": item.trade_date, "calendar_index": item.calendar_index} for item in value
        ]
    else:
        rows = _records(value, "market calendar", expected_fields=CALENDAR_FIELDS)
    if len(rows) != FROZEN_CALENDAR_ROW_COUNT:
        raise V30StageBError(
            f"market calendar is not the frozen {FROZEN_CALENDAR_ROW_COUNT}-row CY033 calendar"
        )
    sessions: list[CalendarSession] = []
    for raw in rows:
        _require_exact_fields(raw, CALENDAR_FIELDS, "market calendar row")
        date = _date(_required(raw, "trade_date", "market calendar"), "calendar date")
        index = _exact_int(
            _required(raw, "calendar_index", "market calendar"),
            "calendar index",
            minimum=0,
        )
        sessions.append(CalendarSession(date, index))
    sessions.sort(key=lambda item: item.calendar_index)
    if [item.calendar_index for item in sessions] != list(range(len(sessions))):
        raise V30StageBError("market calendar indices are not unique contiguous zero-based")
    dates = [item.trade_date for item in sessions]
    if len(dates) != len(set(dates)) or dates != sorted(dates):
        raise V30StageBError("market calendar dates are duplicate or nonmonotonic")
    if dates[0] != FROZEN_CALENDAR_MIN_DATE or dates[-1] != FROZEN_CALENDAR_MAX_DATE:
        raise V30StageBError("market calendar min/max differs from frozen CY033 authority")
    iso_dates = [item.strftime("%Y-%m-%d") for item in dates]
    canonical_payload = {
        "dates": iso_dates,
        "derivation": FROZEN_CALENDAR_DERIVATION,
    }
    canonical_sha256 = normalized_json_sha256(canonical_payload)
    newline_sha256 = hashlib.sha256(("\n".join(iso_dates) + "\n").encode("utf-8")).hexdigest()
    if (
        canonical_sha256 != FROZEN_CALENDAR_CANONICAL_SHA256
        or newline_sha256 != FROZEN_CALENDAR_NEWLINE_SHA256
    ):
        raise V30StageBError("market calendar payload does not match frozen CY033 digests")
    return tuple(sessions)


def normalize_accepted_entry(
    value: AcceptedEntry | Mapping[str, Any],
    calendar: tuple[CalendarSession, ...],
) -> AcceptedEntry:
    if isinstance(value, AcceptedEntry):
        entry = value
    else:
        label = "accepted Stage-A entry"
        _require_exact_fields(value, ACCEPTED_ENTRY_FIELDS, label)
        if _exact_bool(_required(value, "stage_a_cohort_frozen", label), True, label) is not True:
            raise V30StageBError("unreachable cohort freeze state")
        _exact_bool(_required(value, "entry_evidence_accepted", label), True, label)
        _exact_bool(_required(value, "entry_hard_valid", label), True, label)
        if _nonempty(_required(value, "entry_settlement_status", label), label) != (
            "SETTLED_PROXY_ACCEPTED"
        ):
            raise V30StageBError("entry is not the frozen Stage-A accepted channel")
        if (
            _nonempty(_required(value, "entry_execution_proxy_label", label), label)
            != EXECUTION_PROXY_NAME
        ):
            raise V30StageBError("entry proxy identity drift")
        _exact_bool(_required(value, "real_fill_claimed", label), False, label)
        entry = AcceptedEntry(
            stage_a_cohort_frozen=True,
            entry_evidence_accepted=True,
            entry_hard_valid=True,
            entry_settlement_status="SETTLED_PROXY_ACCEPTED",
            entry_evidence_status="CONSERVATIVE_1M_BAR_EXECUTION_PROXY_ACCEPTED",
            entry_execution_proxy_label=EXECUTION_PROXY_NAME,
            real_fill_claimed=False,
            protocol_arm=_nonempty(_required(value, "protocol_arm", label), "protocol arm"),
            gap_id=_nonempty(_required(value, "gap_id", label), "gap id"),
            symbol=canonical_candidate_symbol(_required(value, "symbol", label)),
            signal_date=_date(_required(value, "signal_date", label), "signal date"),
            entry_date=_date(_required(value, "entry_date", label), "entry date"),
            entry_calendar_index=_exact_int(
                _required(value, "entry_calendar_index", label),
                "entry calendar index",
                minimum=0,
            ),
            entry_decision_at=_local_timestamp(
                _required(value, "entry_decision_at", label), "entry decision_at"
            ),
            entry_tick=_positive_tick(
                _required(value, "proxy_worst_buy_tick", label), "entry tick"
            ),
            proxy_bar_volume=_exact_int(
                _required(value, "proxy_bar_volume_exact", label),
                "proxy bar volume",
                minimum=0,
            ),
            proxy_bar_amount=_positive_decimal(
                _required(value, "proxy_bar_amount_exact", label),
                "proxy bar amount",
            ),
            confirmation_volume=_exact_int(
                _required(value, "confirmation_volume_exact", label),
                "confirmation volume",
                minimum=1,
            ),
            confirmation_amount=_positive_decimal(
                _required(value, "confirmation_amount_exact", label),
                "confirmation amount",
            ),
            signal_close_tick=_positive_tick(
                _required(value, "signal_close_tick", label), "signal close tick"
            ),
            raw_l_tick=_positive_tick(_required(value, "raw_l_tick", label), "raw L tick"),
            persisted_reclaimed_pivot_tick=_positive_tick(
                _required(value, "reclaimed_pivot_tick", label), "reclaimed pivot tick"
            ),
            cap25_rank=_exact_int(_required(value, "cap25_rank", label), "CAP25 rank", minimum=1),
            order_effective_at=_local_timestamp(
                _required(value, "order_effective_at", label), "order effective_at"
            ),
            proxy_interval_start_at=_local_timestamp(
                _required(value, "proxy_interval_start_time", label),
                "proxy interval start",
            ),
            proxy_bar_end_at=_local_timestamp(
                _required(value, "proxy_bar_end_time", label), "proxy bar end"
            ),
            universal_minimum_up_cap_tick=_positive_tick(
                _required(value, "universal_minimum_up_cap_tick", label),
                "universal U5 tick",
            ),
            max_headroom_buy_tick=_positive_tick(
                _required(value, "max_headroom_buy_tick", label),
                "maximum headroom buy tick",
            ),
            frozen_buy_limit_tick=_positive_tick(
                _required(value, "frozen_buy_limit_tick", label),
                "frozen buy limit tick",
            ),
            confirmation_row_sha256=_sha256(
                _required(value, "confirmation_row_sha256", label),
                "confirmation row hash",
            ),
            cooldown_row_sha256=_sha256(
                _required(value, "cooldown_row_sha256", label), "cooldown row hash"
            ),
            execution_proxy_row_sha256=_sha256(
                _required(value, "execution_proxy_row_sha256", label),
                "execution proxy row hash",
            ),
            signal_snapshot_id=_nonempty(
                _required(value, "signal_snapshot_id", label), "signal snapshot id"
            ),
            signal_daily_snapshot_id=_nonempty(
                _required(value, "signal_daily_snapshot_id", label),
                "signal daily snapshot id",
            ),
            signal_corporate_action_snapshot_id=_nonempty(
                _required(value, "signal_corporate_action_snapshot_id", label),
                "signal action snapshot id",
            ),
        )
    entry = AcceptedEntry(
        stage_a_cohort_frozen=_exact_bool(
            entry.stage_a_cohort_frozen, True, "accepted cohort freeze"
        ),
        entry_evidence_accepted=_exact_bool(
            entry.entry_evidence_accepted, True, "accepted entry evidence"
        ),
        entry_hard_valid=_exact_bool(entry.entry_hard_valid, True, "accepted entry hard_valid"),
        entry_settlement_status=_nonempty(
            entry.entry_settlement_status, "accepted settlement status"
        ),
        entry_evidence_status=_nonempty(
            entry.entry_evidence_status, "accepted entry evidence status"
        ),
        entry_execution_proxy_label=_nonempty(
            entry.entry_execution_proxy_label, "accepted execution proxy label"
        ),
        real_fill_claimed=_exact_bool(entry.real_fill_claimed, False, "accepted real-fill claim"),
        protocol_arm=_nonempty(entry.protocol_arm, "accepted protocol arm"),
        gap_id=_nonempty(entry.gap_id, "accepted gap id"),
        symbol=canonical_candidate_symbol(entry.symbol, "accepted symbol"),
        signal_date=_date(entry.signal_date, "accepted signal date"),
        entry_date=_date(entry.entry_date, "accepted entry date"),
        entry_calendar_index=_exact_int(
            entry.entry_calendar_index, "accepted entry calendar index", minimum=0
        ),
        entry_decision_at=_local_timestamp(entry.entry_decision_at, "accepted entry decision_at"),
        entry_tick=_positive_tick(entry.entry_tick, "accepted entry tick"),
        proxy_bar_volume=_exact_int(entry.proxy_bar_volume, "accepted proxy bar volume", minimum=0),
        proxy_bar_amount=_positive_decimal(entry.proxy_bar_amount, "accepted proxy bar amount"),
        confirmation_volume=_exact_int(
            entry.confirmation_volume, "accepted confirmation volume", minimum=1
        ),
        confirmation_amount=_positive_decimal(
            entry.confirmation_amount, "accepted confirmation amount"
        ),
        signal_close_tick=_positive_tick(entry.signal_close_tick, "accepted signal close tick"),
        raw_l_tick=_positive_tick(entry.raw_l_tick, "accepted raw L tick"),
        persisted_reclaimed_pivot_tick=_positive_tick(
            entry.persisted_reclaimed_pivot_tick, "accepted reclaimed pivot tick"
        ),
        cap25_rank=_exact_int(entry.cap25_rank, "accepted CAP25 rank", minimum=1),
        order_effective_at=_local_timestamp(
            entry.order_effective_at, "accepted order effective_at"
        ),
        proxy_interval_start_at=_local_timestamp(
            entry.proxy_interval_start_at, "accepted proxy interval start"
        ),
        proxy_bar_end_at=_local_timestamp(entry.proxy_bar_end_at, "accepted proxy bar end"),
        universal_minimum_up_cap_tick=_positive_tick(
            entry.universal_minimum_up_cap_tick, "accepted universal U5 tick"
        ),
        max_headroom_buy_tick=_positive_tick(
            entry.max_headroom_buy_tick, "accepted maximum headroom buy tick"
        ),
        frozen_buy_limit_tick=_positive_tick(
            entry.frozen_buy_limit_tick, "accepted frozen buy limit tick"
        ),
        confirmation_row_sha256=_sha256(
            entry.confirmation_row_sha256, "accepted confirmation row hash"
        ),
        cooldown_row_sha256=_sha256(entry.cooldown_row_sha256, "accepted cooldown row hash"),
        execution_proxy_row_sha256=_sha256(
            entry.execution_proxy_row_sha256, "accepted execution proxy row hash"
        ),
        signal_snapshot_id=_nonempty(entry.signal_snapshot_id, "accepted signal snapshot id"),
        signal_daily_snapshot_id=_nonempty(
            entry.signal_daily_snapshot_id, "accepted signal daily snapshot id"
        ),
        signal_corporate_action_snapshot_id=_nonempty(
            entry.signal_corporate_action_snapshot_id,
            "accepted signal action snapshot id",
        ),
    )
    if (
        entry.entry_settlement_status != "SETTLED_PROXY_ACCEPTED"
        or entry.entry_evidence_status != "CONSERVATIVE_1M_BAR_EXECUTION_PROXY_ACCEPTED"
        or entry.entry_execution_proxy_label != EXECUTION_PROXY_NAME
    ):
        raise V30StageBError("accepted Stage-A channel identity drift")
    if entry.proxy_bar_volume < ENTRY_MIN_PROXY_VOLUME_SHARES:
        raise V30StageBError("accepted proxy bar cannot prove one complete 100-share lot")
    if entry.protocol_arm not in SIGNAL_ARMS:
        raise V30StageBError("accepted protocol arm is not one of the two frozen V30 arms")
    if entry.cap25_rank > 25:
        raise V30StageBError("accepted CAP25 rank is outside 1:25")
    if entry.symbol != canonical_candidate_symbol(entry.symbol):
        raise V30StageBError("accepted symbol is not canonical")
    if entry.entry_calendar_index >= len(calendar):
        raise V30StageBError("entry index is outside the frozen calendar")
    if calendar[entry.entry_calendar_index].trade_date != entry.entry_date:
        raise V30StageBError("entry date/index mapping drift")
    if entry.entry_calendar_index == 0:
        raise V30StageBError("entry has no frozen signal-session predecessor")
    if calendar[entry.entry_calendar_index - 1].trade_date != entry.signal_date:
        raise V30StageBError("signal-to-entry T+1 calendar mapping drift")
    if entry.entry_decision_at != entry.entry_date + pd.Timedelta(hours=9, minutes=35):
        raise V30StageBError("entry decision clock is not exact 09:35")
    if entry.order_effective_at != entry.entry_date + pd.Timedelta(hours=9, minutes=35, seconds=1):
        raise V30StageBError("entry order acknowledgement is not exact 09:35:01")
    if entry.proxy_interval_start_at != entry.entry_date + pd.Timedelta(hours=9, minutes=36):
        raise V30StageBError("entry proxy interval does not start at exact 09:36")
    if entry.proxy_bar_end_at != entry.entry_date + pd.Timedelta(hours=9, minutes=37):
        raise V30StageBError("entry proxy bar does not end at exact 09:37")
    if not (
        entry.entry_tick < entry.frozen_buy_limit_tick
        and entry.entry_tick <= entry.max_headroom_buy_tick
        and entry.max_headroom_buy_tick < entry.raw_l_tick
        and entry.frozen_buy_limit_tick
        == min(
            entry.max_headroom_buy_tick + 1,
            entry.universal_minimum_up_cap_tick,
        )
    ):
        raise V30StageBError("accepted entry limit/headroom inequalities do not conserve")
    recomputed_max_headroom = max_headroom_buy_tick(entry.raw_l_tick)
    recomputed_u5 = round_half_up_tick(
        Decimal(entry.signal_close_tick) * Decimal(105) / Decimal(100),
        "accepted recomputed U5",
    )
    if (
        entry.max_headroom_buy_tick != recomputed_max_headroom
        or entry.universal_minimum_up_cap_tick != recomputed_u5
    ):
        raise V30StageBError("accepted max-headroom or U5 coordinate does not recompute")
    if entry.entry_tick >= entry.raw_l_tick:
        raise V30StageBError("accepted entry is not below raw L")
    target = a67_target_tick(entry.entry_tick, entry.raw_l_tick, Decimal(0))
    exact_target_net = (Decimal(target) * (Decimal(1) - PER_SIDE_FEE)) / (
        Decimal(entry.entry_tick) * (Decimal(1) + PER_SIDE_FEE)
    ) - Decimal(1)
    if target >= entry.raw_l_tick or exact_target_net < MIN_MEAN_RETURN:
        raise V30StageBError("accepted entry does not retain exact A67 four-percent headroom")
    terminal_index = entry.entry_calendar_index + TERMINAL_OFFSET
    if terminal_index >= len(calendar):
        raise V30StageBError("accepted entry lacks its complete H30 calendar horizon")
    if calendar[terminal_index].trade_date > DEVELOPMENT_END:
        raise V30StageBError("accepted entry crosses the 2021 development boundary")
    return entry


def _canonical_raw_action_float64(value: Any, label: str) -> Any:
    """Bind a nullable QD010 DOUBLE without interpreting its economic terms."""
    if value is None:
        return None
    _, bits, decimal = _source_float64_projection(value, label, require_finite=False)
    return {
        "float64_bits_le_hex": bits,
        "decimal_from_float": format(decimal, "f") if decimal is not None else None,
    }


def _canonical_raw_action_bool(value: Any, label: str) -> bool:
    if not isinstance(value, (bool, np.bool_)):
        raise UnknownEvidence(f"{label} is not a native boolean source value")
    return bool(value)


def _action_row_payload(event: ActionEvent) -> dict[str, Any]:
    return {
        "protocol_arm": event.protocol_arm,
        "gap_id": event.gap_id,
        "candidate_symbol": event.candidate_symbol,
        "event_id": event.event_id,
        "raw_event_id": event.raw_event_id,
        "raw_revision_id": event.raw_revision_id,
        "vintage_id": event.vintage_id,
        "source_row_hash": event.source_row_hash,
        "raw_symbol": event.raw_symbol,
        "canonical_symbol": event.canonical_symbol,
        "action_kind": event.action_kind,
        "effective_date": event.effective_date.strftime("%Y-%m-%d"),
        "known_at": event.known_at.isoformat(),
        "available_at": event.available_at.isoformat(),
        "known_at_precision": event.known_at_precision,
        "cash_cents_per_original_share": _canonical_raw_action_float64(
            event.cash_cents_per_original_share, "action raw cash"
        ),
        "share_multiplier": _canonical_raw_action_float64(
            event.share_multiplier, "action raw share multiplier"
        ),
        "rights_ratio": _canonical_raw_action_float64(
            event.rights_ratio, "action raw rights ratio"
        ),
        "rights_price_cents": _canonical_raw_action_float64(
            event.rights_price_cents, "action raw rights price"
        ),
        "source_terms_complete": _canonical_raw_action_bool(
            event.source_terms_complete, "action raw terms-complete state"
        ),
        "snapshot_id": event.snapshot_id,
        "source_table": event.source_table,
        "source_locator": event.source_locator,
        "source_partition_sha256": event.source_partition_sha256,
        "projection": "V30_QD010_PERMITTED_RAW_ACTION_ROW_V1",
    }


def _normalize_action(raw: Mapping[str, Any], entry: AcceptedEntry) -> ActionEvent:
    label = "QD010 action"
    _require_exact_fields(raw, ACTION_PROJECTION_FIELDS, label)
    if (
        _nonempty(_required(raw, "protocol_arm", label), "action protocol arm")
        != entry.protocol_arm
        or _nonempty(_required(raw, "gap_id", label), "action gap id") != entry.gap_id
        or canonical_candidate_symbol(
            _required(raw, "candidate_symbol", label), "action candidate symbol"
        )
        != entry.symbol
    ):
        raise UnknownEvidence("QD010 action crosses its frozen candidate boundary")
    raw_symbol = _exact_string(_required(raw, "raw_symbol", label), "QD010 raw symbol")
    canonical = canonicalize_qd010_symbol(raw_symbol)
    explicit = canonical_candidate_symbol(
        _required(raw, "canonical_symbol", label), "QD010 canonical symbol"
    )
    if canonical != explicit or explicit != entry.symbol:
        raise UnknownEvidence("QD010 canonical symbol join is not exact")
    precision = _nonempty(_required(raw, "known_at_precision", label), "known_at precision")
    if precision not in KNOWN_AT_PRECISIONS:
        raise UnknownEvidence("QD010 known_at precision is not frozen")
    known_at = _local_timestamp(_required(raw, "known_at", label), "QD010 known_at")
    available_at = _local_timestamp(_required(raw, "available_at", label), "QD010 available_at")
    if known_at != available_at:
        raise UnknownEvidence("QD010 available_at is not the transparent known_at alias")
    if precision == "DAY_ONLY" and known_at != known_at.normalize():
        raise UnknownEvidence("DAY_ONLY known_at is not a midnight source date")
    kind = _nonempty(_required(raw, "action_kind", label), "action kind")
    source_table = _exact_string(_required(raw, "source_table", label), "action source table")
    if source_table not in QD010_SOURCE_SHA256:
        raise UnknownEvidence("QD010 action source table is not registered")
    source_partition_sha256 = _sha256(
        _required(raw, "source_partition_sha256", label), "action source partition hash"
    )
    if source_partition_sha256 != QD010_SOURCE_SHA256[source_table]:
        raise UnknownEvidence("QD010 action source partition binding drift")
    # Unsupported kinds and malformed terms remain visible until causal.  The
    # raw permitted projection can be hashed without interpreting those terms.
    source_locator = _exact_string(_required(raw, "source_locator", label), "action source locator")
    if source_locator != f"normalized/{source_table}.parquet":
        raise UnknownEvidence("QD010 action source locator binding drift")
    event = ActionEvent(
        protocol_arm=entry.protocol_arm,
        gap_id=entry.gap_id,
        candidate_symbol=entry.symbol,
        event_id=_nonempty(_required(raw, "event_id", label), "action event id"),
        raw_event_id=_nonempty(_required(raw, "raw_event_id", label), "action raw event identity"),
        raw_revision_id=_nonempty(
            _required(raw, "raw_revision_id", label), "action raw revision identity"
        ),
        vintage_id=_nonempty(_required(raw, "vintage_id", label), "action raw vintage identity"),
        source_row_hash=_sha256(_required(raw, "source_row_hash", label), "action source row_hash"),
        permitted_projection_sha256=_sha256(
            _required(raw, "permitted_projection_sha256", label),
            "action permitted-projection hash",
        ),
        raw_symbol=raw_symbol,
        canonical_symbol=canonical,
        action_kind=kind,
        effective_date=_date(_required(raw, "effective_date", label), "effective date"),
        known_at=known_at,
        available_at=available_at,
        known_at_precision=precision,
        cash_cents_per_original_share=_required(raw, "cash_cents_per_original_share", label),
        share_multiplier=_required(raw, "share_multiplier", label),
        rights_ratio=_required(raw, "rights_ratio", label),
        rights_price_cents=_required(raw, "rights_price_cents", label),
        source_terms_complete=_required(raw, "source_terms_complete", label),
        snapshot_id=_nonempty(
            _required(raw, "snapshot_id", label), "action raw snapshot/vintage identity"
        ),
        source_table=source_table,
        source_locator=source_locator,
        source_partition_sha256=source_partition_sha256,
    )
    observed_hash = event.permitted_projection_sha256
    if observed_hash != normalized_json_sha256(_action_row_payload(event)):
        raise UnknownEvidence("QD010 action permitted-projection row hash mismatch")
    return event


def _validated_action_terms(event: ActionEvent) -> ActionTerms:
    _exact_bool(event.source_terms_complete, True, "QD010 source_terms_complete")
    cash, _ = _source_float64_decimal(event.cash_cents_per_original_share, "action cash cents")
    share_multiplier, _ = _source_float64_decimal(event.share_multiplier, "action share multiplier")
    rights_ratio, _ = _source_float64_decimal(event.rights_ratio, "action rights ratio")
    rights_price_cents, _ = _source_float64_decimal(
        event.rights_price_cents, "action rights price cents"
    )
    terms = ActionTerms(
        cash_cents_per_original_share=cash,
        share_multiplier=share_multiplier,
        rights_ratio=rights_ratio,
        rights_price_cents=rights_price_cents,
    )
    if (
        terms.cash_cents_per_original_share < 0
        or terms.share_multiplier <= 0
        or terms.rights_ratio < 0
        or terms.rights_price_cents < 0
    ):
        raise UnknownEvidence("QD010 raw float64 action terms are outside their exact domains")
    if event.action_kind == "CASH_ONLY":
        if terms.share_multiplier != 1 or terms.rights_ratio != 0 or terms.rights_price_cents != 0:
            raise UnknownEvidence("CASH_ONLY action changes share or rights terms")
    elif event.action_kind == "RISK_SHARE":
        if terms.share_multiplier == 1 or terms.rights_ratio != 0 or terms.rights_price_cents != 0:
            raise UnknownEvidence("RISK_SHARE terms are incomplete or conflicting")
    elif event.action_kind == "RISK_RIGHTS":
        if terms.share_multiplier != 1 or terms.rights_ratio <= 0:
            raise UnknownEvidence("RISK_RIGHTS terms are incomplete or conflicting")
    else:
        raise UnknownEvidence("unsupported action terms cannot be replayed")
    return terms


def _action_query_scope_payload(
    entry: AcceptedEntry,
    *,
    terminal_date: pd.Timestamp,
    knowledge_cutoff: pd.Timestamp,
    snapshot_id: str,
    vintage_id: str,
) -> dict[str, Any]:
    return {
        "envelope_type": ACTION_ENVELOPE_TYPE,
        "protocol_arm": entry.protocol_arm,
        "gap_id": entry.gap_id,
        "candidate_symbol": entry.symbol,
        "query_predicate": ACTION_QUERY_PREDICATE,
        "effective_date_min_exclusive": entry.entry_date.strftime("%Y-%m-%d"),
        "effective_date_max_inclusive": terminal_date.strftime("%Y-%m-%d"),
        "knowledge_cutoff": knowledge_cutoff.isoformat(),
        "expected_source_partitions": QD010_SOURCE_SHA256,
        "canonical_symbol_reference_sha256": QD010_CANONICAL_SYMBOL_REFERENCE_SHA256,
        "snapshot_id": snapshot_id,
        "vintage_id": vintage_id,
        "projection": "V30_QD010_QUERY_SCOPE_V1",
    }


def _action_ledger_payload(events: Sequence[ActionEvent]) -> dict[str, Any]:
    return {
        "rows": [
            {
                "event_id": event.event_id,
                "raw_event_id": event.raw_event_id,
                "raw_revision_id": event.raw_revision_id,
                "source_row_hash": event.source_row_hash,
                "permitted_projection_sha256": event.permitted_projection_sha256,
                "source_table": event.source_table,
            }
            for event in events
        ],
        "projection": "V30_QD010_NORMALIZED_ACTION_LEDGER_V1",
    }


def _action_completeness_payload(
    *,
    query_scope_sha256: str,
    source_counts: tuple[tuple[str, int], ...],
    raw_source_match_count: int,
    projected_row_count: int,
    normalized_ledger_sha256: str,
    snapshot_id: str,
    vintage_id: str,
) -> dict[str, Any]:
    return {
        "query_scope_sha256": query_scope_sha256,
        "source_match_count_by_partition": dict(source_counts),
        "raw_source_match_count": raw_source_match_count,
        "projected_row_count": projected_row_count,
        "normalized_ledger_sha256": normalized_ledger_sha256,
        "query_complete": True,
        "snapshot_id": snapshot_id,
        "vintage_id": vintage_id,
        "projection": "V30_QD010_COMPLETE_QUERY_EVIDENCE_V1",
    }


def normalize_action_envelope(
    value: ActionQueryEnvelope | Mapping[str, Any],
    entry: AcceptedEntry,
    calendar: tuple[CalendarSession, ...],
) -> ActionQueryEnvelope:
    if isinstance(value, ActionQueryEnvelope):
        rows: list[dict[str, Any]] = []
        for event in value.events:
            payload = _action_row_payload(event)
            payload.pop("projection")
            payload["permitted_projection_sha256"] = event.permitted_projection_sha256
            rows.append({field: payload[field] for field in ACTION_PROJECTION_FIELDS})
        # Typed envelopes still pass through the same canonical mapping gate;
        # direct dataclass construction is not an authority bypass.
        raw_envelope: Mapping[str, Any] = {
            "envelope_type": value.envelope_type,
            "protocol_arm": value.protocol_arm,
            "gap_id": value.gap_id,
            "candidate_symbol": value.candidate_symbol,
            "query_predicate": value.query_predicate,
            "effective_date_min_exclusive": value.effective_date_min_exclusive,
            "effective_date_max_inclusive": value.effective_date_max_inclusive,
            "knowledge_cutoff": value.knowledge_cutoff,
            "expected_source_partitions": dict(value.expected_source_partitions),
            "canonical_symbol_reference_sha256": value.canonical_symbol_reference_sha256,
            "source_match_count_by_partition": dict(value.source_match_count_by_partition),
            "raw_source_match_count": value.raw_source_match_count,
            "projected_row_count": value.projected_row_count,
            "query_complete": value.query_complete,
            "snapshot_id": value.snapshot_id,
            "vintage_id": value.vintage_id,
            "normalized_ledger_sha256": value.normalized_ledger_sha256,
            "query_scope_sha256": value.query_scope_sha256,
            "completeness_sha256": value.completeness_sha256,
            "rows": rows,
        }
    elif not isinstance(value, Mapping):
        raise UnknownEvidence("QD010 actions require one typed query envelope mapping")
    else:
        raw_envelope = value
    _require_exact_fields(raw_envelope, ACTION_ENVELOPE_FIELDS, "QD010 action envelope")
    if (
        _exact_string(_required(raw_envelope, "envelope_type", "action envelope"), "envelope type")
        != ACTION_ENVELOPE_TYPE
    ):
        raise UnknownEvidence("QD010 action envelope type drift")
    if (
        _exact_string(
            _required(raw_envelope, "protocol_arm", "action envelope"), "action envelope arm"
        )
        != entry.protocol_arm
        or _exact_string(
            _required(raw_envelope, "gap_id", "action envelope"), "action envelope gap"
        )
        != entry.gap_id
        or canonical_candidate_symbol(
            _required(raw_envelope, "candidate_symbol", "action envelope"),
            "action envelope candidate",
        )
        != entry.symbol
    ):
        raise UnknownEvidence("QD010 action envelope crosses its candidate boundary")
    if (
        _exact_string(
            _required(raw_envelope, "query_predicate", "action envelope"), "action query predicate"
        )
        != ACTION_QUERY_PREDICATE
    ):
        raise UnknownEvidence("QD010 action query predicate drift")
    terminal_date = calendar[entry.entry_calendar_index + TERMINAL_OFFSET].trade_date
    knowledge_cutoff = terminal_date + pd.Timedelta(hours=15)
    effective_min = _date(
        _required(raw_envelope, "effective_date_min_exclusive", "action envelope"),
        "action envelope effective minimum",
    )
    effective_max = _date(
        _required(raw_envelope, "effective_date_max_inclusive", "action envelope"),
        "action envelope effective maximum",
    )
    observed_cutoff = _local_timestamp(
        _required(raw_envelope, "knowledge_cutoff", "action envelope"),
        "action envelope knowledge cutoff",
    )
    if (
        effective_min != entry.entry_date
        or effective_max != terminal_date
        or observed_cutoff != knowledge_cutoff
    ):
        raise UnknownEvidence("QD010 action query cutoffs are not the frozen candidate horizon")
    source_bindings = _required(raw_envelope, "expected_source_partitions", "action envelope")
    if not isinstance(source_bindings, Mapping) or dict(source_bindings) != QD010_SOURCE_SHA256:
        raise UnknownEvidence("QD010 action envelope source bindings drift")
    canonicalizer_sha256 = _sha256(
        _required(
            raw_envelope,
            "canonical_symbol_reference_sha256",
            "action envelope",
        ),
        "QD010 canonical-symbol reference hash",
    )
    if canonicalizer_sha256 != QD010_CANONICAL_SYMBOL_REFERENCE_SHA256:
        raise UnknownEvidence("QD010 canonical-symbol reference binding drift")
    raw_counts = _required(raw_envelope, "source_match_count_by_partition", "action envelope")
    if not isinstance(raw_counts, Mapping) or set(raw_counts) != set(QD010_SOURCE_SHA256):
        raise UnknownEvidence("QD010 action envelope source accounting schema drift")
    source_counts = tuple(
        (source, _exact_int(raw_counts[source], f"{source} source match count", minimum=0))
        for source in sorted(QD010_SOURCE_SHA256)
    )
    raw_source_match_count = _exact_int(
        _required(raw_envelope, "raw_source_match_count", "action envelope"),
        "action envelope raw source match count",
        minimum=0,
    )
    projected_row_count = _exact_int(
        _required(raw_envelope, "projected_row_count", "action envelope"),
        "action envelope projected row count",
        minimum=0,
    )
    _exact_bool(
        _required(raw_envelope, "query_complete", "action envelope"),
        True,
        "action envelope query_complete",
    )
    snapshot_id = _exact_string(
        _required(raw_envelope, "snapshot_id", "action envelope"), "action envelope snapshot"
    )
    vintage_id = _exact_string(
        _required(raw_envelope, "vintage_id", "action envelope"), "action envelope vintage"
    )
    events = tuple(
        sorted(
            (
                _normalize_action(row, entry)
                for row in _records(
                    _required(raw_envelope, "rows", "action envelope"),
                    "actions",
                    expected_fields=ACTION_PROJECTION_FIELDS,
                )
            ),
            key=lambda event: (
                event.known_at,
                event.effective_date,
                event.event_id,
                event.raw_event_id,
            ),
        )
    )
    if any(
        not (entry.entry_date < event.effective_date <= terminal_date)
        or event.known_at > knowledge_cutoff
        for event in events
    ):
        raise UnknownEvidence("QD010 action row is outside its declared query cutoffs")
    for field, label in (
        ("event_id", "event id"),
        ("raw_event_id", "raw event id"),
        ("raw_revision_id", "raw revision id"),
        ("source_row_hash", "source row hash"),
        ("permitted_projection_sha256", "permitted-projection hash"),
    ):
        identities = [getattr(event, field) for event in events]
        if len(identities) != len(set(identities)):
            raise UnknownEvidence(f"QD010 action {label} is duplicated")
    if any(event.snapshot_id != snapshot_id or event.vintage_id != vintage_id for event in events):
        raise UnknownEvidence("QD010 action row snapshot/vintage differs from its envelope")
    observed_counts = {
        source: sum(event.source_table == source for event in events)
        for source in QD010_SOURCE_SHA256
    }
    if (
        raw_source_match_count != sum(count for _, count in source_counts)
        or projected_row_count != raw_source_match_count
        or projected_row_count != len(events)
        or observed_counts != dict(source_counts)
    ):
        raise UnknownEvidence("QD010 action source-match accounting does not conserve")
    query_scope_sha256 = normalized_json_sha256(
        _action_query_scope_payload(
            entry,
            terminal_date=terminal_date,
            knowledge_cutoff=knowledge_cutoff,
            snapshot_id=snapshot_id,
            vintage_id=vintage_id,
        )
    )
    observed_scope_sha256 = _sha256(
        _required(raw_envelope, "query_scope_sha256", "action envelope"),
        "action query-scope digest",
    )
    if observed_scope_sha256 != query_scope_sha256:
        raise UnknownEvidence("QD010 action query-scope digest mismatch")
    normalized_ledger_sha256 = normalized_json_sha256(_action_ledger_payload(events))
    observed_ledger_sha256 = _sha256(
        _required(raw_envelope, "normalized_ledger_sha256", "action envelope"),
        "action normalized-ledger digest",
    )
    if observed_ledger_sha256 != normalized_ledger_sha256:
        raise UnknownEvidence("QD010 normalized action-ledger digest mismatch")
    completeness_sha256 = normalized_json_sha256(
        _action_completeness_payload(
            query_scope_sha256=query_scope_sha256,
            source_counts=source_counts,
            raw_source_match_count=raw_source_match_count,
            projected_row_count=projected_row_count,
            normalized_ledger_sha256=normalized_ledger_sha256,
            snapshot_id=snapshot_id,
            vintage_id=vintage_id,
        )
    )
    observed_completeness_sha256 = _sha256(
        _required(raw_envelope, "completeness_sha256", "action envelope"),
        "action completeness digest",
    )
    if observed_completeness_sha256 != completeness_sha256:
        raise UnknownEvidence("QD010 action completeness digest mismatch")
    return ActionQueryEnvelope(
        envelope_type=ACTION_ENVELOPE_TYPE,
        protocol_arm=entry.protocol_arm,
        gap_id=entry.gap_id,
        candidate_symbol=entry.symbol,
        query_predicate=ACTION_QUERY_PREDICATE,
        effective_date_min_exclusive=effective_min,
        effective_date_max_inclusive=effective_max,
        knowledge_cutoff=knowledge_cutoff,
        expected_source_partitions=tuple(sorted(QD010_SOURCE_SHA256.items())),
        canonical_symbol_reference_sha256=canonicalizer_sha256,
        snapshot_id=snapshot_id,
        vintage_id=vintage_id,
        source_match_count_by_partition=source_counts,
        raw_source_match_count=raw_source_match_count,
        projected_row_count=projected_row_count,
        query_complete=True,
        normalized_ledger_sha256=normalized_ledger_sha256,
        query_scope_sha256=query_scope_sha256,
        completeness_sha256=completeness_sha256,
        events=events,
    )


def _order_freeze_at(date: pd.Timestamp) -> pd.Timestamp:
    return date + pd.Timedelta(
        hours=SESSION_ORDER_FREEZE_CLOCK.hour,
        minutes=SESSION_ORDER_FREEZE_CLOCK.minute,
        seconds=SESSION_ORDER_FREEZE_CLOCK.second,
    )


def _order_submitted_at(date: pd.Timestamp) -> pd.Timestamp:
    return date + pd.Timedelta(
        hours=SESSION_ORDER_SUBMIT_CLOCK.hour,
        minutes=SESSION_ORDER_SUBMIT_CLOCK.minute,
        seconds=SESSION_ORDER_SUBMIT_CLOCK.second,
    )


def _first_calendar_index_on_or_after(
    date: pd.Timestamp, calendar: tuple[CalendarSession, ...]
) -> int | None:
    for session in calendar:
        if session.trade_date >= date:
            return session.calendar_index
    return None


def _first_freeze_index_at_or_after(
    timestamp: pd.Timestamp, calendar: tuple[CalendarSession, ...]
) -> int | None:
    for session in calendar:
        if _order_freeze_at(session.trade_date) >= timestamp:
            return session.calendar_index
    return None


def _terms_causal_at(
    event: ActionEvent,
    asof: pd.Timestamp,
    calendar: tuple[CalendarSession, ...],
) -> bool:
    if event.known_at_precision == "EXACT_TIMESTAMP":
        return event.known_at <= asof and event.available_at <= asof
    # A date-only notice can have occurred at any point in its source day.  Its
    # terms are usable for pricing only on a strictly later calendar date.
    return event.known_at.normalize() < asof.normalize()


def _risk_spec(event: ActionEvent, calendar: tuple[CalendarSession, ...]) -> RiskSpec:
    effective_index = _first_calendar_index_on_or_after(event.effective_date, calendar)
    if effective_index is None or calendar[effective_index].trade_date != event.effective_date:
        raise UnknownEvidence("risk action effective date is not a frozen market session")
    if event.known_at_precision == "DAY_ONLY":
        cancellation = _first_calendar_index_on_or_after(event.known_at.normalize(), calendar)
        if cancellation is None:
            raise UnknownEvidence("DAY_ONLY risk notice is outside the frozen calendar")
        earliest = cancellation + 1
    else:
        earliest = _first_freeze_index_at_or_after(event.known_at, calendar)
        if earliest is None:
            raise UnknownEvidence("exact risk notice is outside the frozen calendar")
        cancellation = earliest
        notice_date_index = _first_calendar_index_on_or_after(event.known_at.normalize(), calendar)
        if (
            notice_date_index is not None
            and calendar[notice_date_index].trade_date == event.known_at.normalize()
            and event.known_at > _order_freeze_at(calendar[notice_date_index].trade_date)
        ):
            cancellation = notice_date_index
    return RiskSpec(event, cancellation, earliest, effective_index)


def _action_relevance_check(
    entry: AcceptedEntry,
    events: tuple[ActionEvent, ...],
    calendar: tuple[CalendarSession, ...],
) -> tuple[RiskSpec, ...]:
    terminal_index = entry.entry_calendar_index + TERMINAL_OFFSET
    terminal_date = calendar[terminal_index].trade_date
    risks: list[RiskSpec] = []
    for event in events:
        if event.effective_date <= entry.entry_date:
            raise UnknownEvidence(
                "action effective no later than entry invalidates raw coordinates"
            )
        if event.effective_date > terminal_date:
            continue
        if event.action_kind in RISK_ACTION_KINDS:
            spec = _risk_spec(event, calendar)
            if (
                event.known_at_precision == "DAY_ONLY"
                and event.known_at.normalize() <= entry.entry_date
            ) or (
                event.known_at_precision == "EXACT_TIMESTAMP"
                and event.known_at <= entry.entry_decision_at
            ):
                raise UnknownEvidence("accepted entry violates the Stage-A known risk gate")
            risks.append(spec)
        elif event.action_kind != "CASH_ONLY":
            # Unsupported terms are handled at their causal observation time.
            continue
    return tuple(
        sorted(
            risks,
            key=lambda item: (
                item.cancellation_index,
                item.earliest_order_index,
                item.effective_index,
                item.event.event_id,
            ),
        )
    )


def _prepare_daily_projection(
    value: Any,
    entry: AcceptedEntry,
    calendar: tuple[CalendarSession, ...],
) -> dict[int, Mapping[str, Any]]:
    if isinstance(value, pd.DataFrame):
        raise UnknownEvidence("daily scaffold must remain a lazy sequence of mappings")
    rows = _records(
        value,
        "bounded daily projection",
        expected_fields=DAILY_PROJECTION_FIELDS,
    )
    if len(rows) != TERMINAL_OFFSET:
        raise UnknownEvidence("daily projection is not exactly H0 through H29")
    by_offset: dict[int, Mapping[str, Any]] = {}
    for raw in rows:
        _require_exact_fields(raw, DAILY_PROJECTION_FIELDS, "bounded daily row")
        offset = _exact_int(
            _required(raw, "session_offset", "daily projection"),
            "daily session offset",
            minimum=0,
        )
        if offset > 29 or offset in by_offset:
            raise UnknownEvidence("daily projection offset is duplicate or outside H0:H29")
        date = _date(_required(raw, "trade_date", "daily projection"), "daily trade date")
        expected_index = entry.entry_calendar_index + offset
        if expected_index >= len(calendar) or date != calendar[expected_index].trade_date:
            raise UnknownEvidence("daily projection offset/calendar mapping drift")
        if (
            canonical_candidate_symbol(
                _required(raw, "symbol", "daily projection"), "daily candidate symbol"
            )
            != entry.symbol
        ):
            raise UnknownEvidence("daily projection crosses a symbol boundary")
        if _nonempty(_required(raw, "gap_id", "daily projection"), "daily gap id") != entry.gap_id:
            raise UnknownEvidence("daily projection crosses a gap boundary")
        if (
            _nonempty(_required(raw, "protocol_arm", "daily projection"), "daily protocol arm")
            != entry.protocol_arm
        ):
            raise UnknownEvidence("daily projection crosses an arm boundary")
        by_offset[offset] = raw
    if set(by_offset) != set(range(30)):
        raise UnknownEvidence("daily projection does not conserve H0 through H29")
    return by_offset


def _parse_action_ids(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise UnknownEvidence("daily action ids are not the frozen list representation")
    items = [_exact_string(item, "daily action id") for item in value]
    if len(items) != len(set(items)):
        raise UnknownEvidence("daily action ids contain duplicates")
    if items != sorted(items):
        raise UnknownEvidence("daily action ids are not already in canonical order")
    return tuple(items)


def _canonical_decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _fraction_display_text(value: Fraction) -> str:
    """Render a rational for display only; no decision consumes this value."""
    if not isinstance(value, Fraction):
        raise V30StageBError("ratio display requires an exact Fraction")
    quantum = Decimal((0, (1,), -RATIO_DISPLAY_DECIMAL_PLACES))
    required_precision = (
        len(str(abs(value.numerator)))
        + len(str(value.denominator))
        + RATIO_DISPLAY_DECIMAL_PLACES
        + 8
    )
    with localcontext() as context:
        context.prec = max(80, required_precision)
        rendered = (Decimal(value.numerator) / Decimal(value.denominator)).quantize(
            quantum,
            rounding=ROUND_HALF_UP,
        )
    return _canonical_decimal_text(rendered)


def _canonical_outcome_decimal(value: Any, label: str) -> Decimal:
    if not isinstance(value, str):
        raise V30StageBError(f"{label} is not a canonical serialized Decimal")
    result = _decimal(value, label)
    if _canonical_decimal_text(result) != value:
        raise V30StageBError(f"{label} is not in canonical Decimal form")
    return result


def _require_zero_match_physical_nulls(
    raw: Mapping[str, Any], physical_fields: tuple[str, ...], label: str
) -> None:
    fabricated = sorted(
        field for field in physical_fields if _required(raw, field, label) is not None
    )
    if fabricated:
        raise UnknownEvidence(
            f"{label} zero-match scaffold fabricates physical fields {fabricated}"
        )


def _validate_daily(
    raw: Mapping[str, Any],
    *,
    offset: int,
    entry: AcceptedEntry,
    events: tuple[ActionEvent, ...],
    calendar: tuple[CalendarSession, ...],
) -> ValidDaily:
    label = f"CY033 H{offset} daily evidence"
    date = calendar[entry.entry_calendar_index + offset].trade_date
    source_match_count = _exact_int(
        _required(raw, "source_match_count", label),
        f"{label} source match count",
        minimum=0,
    )
    if source_match_count == 0:
        _require_zero_match_physical_nulls(raw, DAILY_PHYSICAL_FIELDS, label)
        raise UnknownEvidence(f"{label} has no source row")
    if source_match_count != 1:
        raise UnknownEvidence(f"{label} has duplicate source rows")
    source_locator = _exact_string(
        _required(raw, "source_locator", label), f"{label} source locator"
    )
    if source_locator != f"daily/partition_year={date.year}/data_0.parquet":
        raise UnknownEvidence(f"{label} source locator binding drift")
    partition_sha256 = _sha256(_required(raw, "partition_sha256", label), f"{label} partition hash")
    expected_partition = CY033_DEVELOPMENT_PARTITION_SHA256.get(date.year)
    if partition_sha256 != expected_partition:
        raise UnknownEvidence(f"{label} partition binding drift")
    decision_at = _local_timestamp(_required(raw, "decision_at", label), f"{label} decision_at")
    available_at = _local_timestamp(_required(raw, "available_at", label), f"{label} available_at")
    if decision_at != date + pd.Timedelta(hours=15) or available_at > decision_at:
        raise UnknownEvidence(f"{label} is noncausal or not the completed 15:00 row")
    if (
        _nonempty(_required(raw, "decision_timezone", label), f"{label} decision timezone")
        != "Asia/Shanghai"
    ):
        raise UnknownEvidence(f"{label} decision timezone is not Asia/Shanghai")
    exact_flags: dict[str, bool] = {}
    for field in (
        "bar_valid",
        "trading_state_valid",
        "corporate_action_valid",
        "market_rule_valid",
        "hard_valid",
    ):
        exact_flags[field] = _exact_bool(_required(raw, field, label), True, f"{label} {field}")
    snapshot_ids: dict[str, str] = {}
    for field in (
        "snapshot_id",
        "daily_snapshot_id",
        "trading_state_snapshot_id",
        "corporate_action_snapshot_id",
    ):
        snapshot_ids[field] = _exact_string(_required(raw, field, label), f"{label} {field}")

    effective = tuple(event for event in events if event.effective_date == date)
    if any(not _terms_causal_at(event, decision_at, calendar) for event in effective):
        raise UnknownEvidence(f"{label} has an effective action not causal by close")
    if any(event.action_kind != "CASH_ONLY" for event in effective):
        raise UnknownEvidence(f"{label} reached an unhandled share/rights/unsupported action")
    expected_ids = tuple(sorted(event.event_id for event in effective))
    observed_count = _exact_int(
        _required(raw, "corporate_action_count", label),
        f"{label} action count",
        minimum=0,
    )
    observed_ids = _parse_action_ids(_required(raw, "corporate_action_ids", label))
    if observed_count != len(expected_ids) or observed_ids != expected_ids:
        raise UnknownEvidence(f"{label} QD010/CY033 action identity mismatch")
    effective_terms = [_validated_action_terms(event) for event in effective]
    expected_cash = _exact_decimal_sum(
        tuple(terms.cash_cents_per_original_share for terms in effective_terms)
    )
    observed_cash = _nonnegative_decimal(
        _required(raw, "cash_cents_per_original_share", label),
        f"{label} cash cents",
    )
    share_multiplier = _positive_decimal(
        _required(raw, "share_multiplier", label), f"{label} share multiplier"
    )
    rights_ratio = _nonnegative_decimal(
        _required(raw, "rights_ratio", label), f"{label} rights ratio"
    )
    rights_price_cents = _nonnegative_decimal(
        _required(raw, "rights_price_cents", label), f"{label} rights price"
    )
    if (
        observed_cash != expected_cash
        or share_multiplier != 1
        or rights_ratio != 0
        or rights_price_cents != 0
    ):
        raise UnknownEvidence(f"{label} action terms do not conserve")
    corporate_action_blocking = _exact_bool(
        _required(raw, "corporate_action_blocking", label),
        False,
        f"{label} corporate_action_blocking",
    )
    close_tick = _positive_tick(_required(raw, "close_tick", label), f"{label} close tick")
    trade_status = _exact_int(_required(raw, "trade_status", label), f"{label} trade status")
    if trade_status not in {0, 1}:
        raise UnknownEvidence(f"{label} trade status is outside the exact 0/1 domain")
    tradable = _exact_bool(
        _required(raw, "current_day_data_tradable", label),
        None,
        f"{label} tradable",
    )
    daily_volume = _exact_int(
        _required(raw, "daily_volume", label), f"{label} daily volume", minimum=0
    )
    daily_amount, daily_amount_bits = _source_float64_decimal(
        _required(raw, "daily_amount", label), f"{label} daily amount"
    )
    if daily_amount < 0:
        raise UnknownEvidence(f"{label} daily amount is negative")
    payload = {
        "protocol_arm": entry.protocol_arm,
        "gap_id": entry.gap_id,
        "symbol": entry.symbol,
        "session_offset": offset,
        "trade_date": date.strftime("%Y-%m-%d"),
        "source_match_count": 1,
        "decision_at": decision_at.isoformat(),
        "available_at": available_at.isoformat(),
        "decision_timezone": "Asia/Shanghai",
        "close_tick": close_tick,
        **snapshot_ids,
        **exact_flags,
        "corporate_action_blocking": corporate_action_blocking,
        "corporate_action_count": observed_count,
        "corporate_action_ids": list(observed_ids),
        "cash_cents_per_original_share": _canonical_decimal_text(observed_cash),
        "share_multiplier": _canonical_decimal_text(share_multiplier),
        "rights_ratio": _canonical_decimal_text(rights_ratio),
        "rights_price_cents": _canonical_decimal_text(rights_price_cents),
        "trade_status": trade_status,
        "current_day_data_tradable": tradable,
        "daily_volume": daily_volume,
        "daily_amount": {
            "source_float64_bits_le_hex": daily_amount_bits,
            "decimal_from_float": format(daily_amount, "f"),
        },
        "source_locator": source_locator,
        "partition_sha256": partition_sha256,
        "projection": "V30_CY033_PERMITTED_COMPLETED_DAILY_ROW_V1",
    }
    row_sha256 = _sha256(_required(raw, "row_sha256", label), f"{label} row hash")
    if row_sha256 != normalized_json_sha256(payload):
        raise UnknownEvidence(f"{label} permitted-projection row hash mismatch")
    return ValidDaily(
        offset,
        date,
        close_tick,
        trade_status,
        tradable,
        daily_volume,
        daily_amount,
        row_sha256,
    )


def _daily_market_state(daily: ValidDaily, offset: int) -> Literal["TRADED", "SUSPENDED"]:
    if (
        daily.trade_status == 1
        and daily.current_day_data_tradable is True
        and daily.daily_volume > 0
        and daily.daily_amount > 0
    ):
        return "TRADED"
    if (
        daily.trade_status == 0
        and daily.current_day_data_tradable is False
        and daily.daily_volume == 0
        and daily.daily_amount == 0
    ):
        return "SUSPENDED"
    raise UnknownEvidence(f"H{offset} CY033 market-state tuple is contradictory")


def _advance_exchange_reference(
    session_reference_tick: int,
    daily: ValidDaily,
    scan: SessionScan,
    offset: int,
) -> int:
    reference = _positive_tick(session_reference_tick, "session exchange-reference tick")
    state = _daily_market_state(daily, offset)
    if state == "TRADED":
        if scan.complete_physical_session and scan.all_physical_rows_zero_volume:
            raise UnknownEvidence(
                f"H{offset} CY033 traded state conflicts with an all-zero-volume QD004 day"
            )
        return daily.close_tick
    if daily.close_tick != reference:
        raise UnknownEvidence(
            f"H{offset} suspended CY033 close differs from the computed exchange reference"
        )
    if not (scan.complete_physical_session and scan.all_physical_rows_zero_volume):
        raise UnknownEvidence(
            f"H{offset} CY033 suspension lacks a complete flat zero-volume QD004 session"
        )
    return reference


def _minute_groups(value: Any) -> dict[int, list[Mapping[str, Any]]]:
    if isinstance(value, pd.DataFrame):
        raise UnknownEvidence("minute scaffold must remain a lazy sequence of mappings")
    if isinstance(value, Mapping):
        groups: dict[int, list[Mapping[str, Any]]] = {}
        for raw_offset, rows in value.items():
            offset = _exact_int(raw_offset, "minute group offset", minimum=1)
            if offset > TERMINAL_OFFSET or offset in groups:
                raise UnknownEvidence("minute group offset is duplicate or outside H1:H30")
            if isinstance(rows, pd.DataFrame):
                raise UnknownEvidence("minute session scaffold cannot be a materialized DataFrame")
            groups[offset] = _records(
                rows,
                f"H{offset} minute rows",
                expected_fields=MINUTE_SCAFFOLD_FIELDS,
            )
        return groups
    groups = {}
    for raw in _records(
        value,
        "minute projection",
        expected_fields=MINUTE_SCAFFOLD_FIELDS,
    ):
        offset = _exact_int(
            _required(raw, "session_offset", "minute row"),
            "minute session offset",
            minimum=1,
        )
        if offset > TERMINAL_OFFSET:
            raise UnknownEvidence("minute row is outside H1:H30")
        groups.setdefault(offset, []).append(raw)
    return groups


def _bar_timestamp(value: Any, date: pd.Timestamp, label: str) -> pd.Timestamp:
    if isinstance(value, time):
        result = date + pd.Timedelta(hours=value.hour, minutes=value.minute, seconds=value.second)
    elif isinstance(value, str) and value == value.strip() and re.fullmatch(r"\d{2}:\d{2}", value):
        hour, minute = map(int, value.split(":"))
        try:
            clock = time(hour, minute)
        except ValueError as exc:
            raise UnknownEvidence(f"{label} clock is invalid") from exc
        result = date + pd.Timedelta(hours=clock.hour, minutes=clock.minute)
    else:
        result = _local_timestamp(value, label)
    if result.normalize() != date or result.second != 0 or result.microsecond != 0:
        raise UnknownEvidence(f"{label} is not an exact minute on the expected date")
    return result


def qd004_query_locator(entry: AcceptedEntry, expected_at: pd.Timestamp) -> str:
    return (
        f"bars/{expected_at.year}_day_parquet_none.parquet"
        f"::qmt_code={entry.symbol}"
        f"::trade_date={expected_at.strftime('%Y-%m-%d')}"
        f"::bar_end_time={expected_at.isoformat()}"
    )


def qd004_source_snapshot_id(year: int) -> str:
    try:
        partition = QD004_DEVELOPMENT_PARTITION_SHA256[year]
    except KeyError as exc:
        raise UnknownEvidence("QD004 snapshot year is outside development") from exc
    return f"QD004:{QD004_SOURCE_MANIFEST_SHA256}:{partition}"


def _validate_physical_qd004_locator(value: Any, query_locator: str, label: str) -> str:
    locator = _exact_string(value, label)
    pattern = re.compile(
        rf"^{re.escape(query_locator)}::row_group=(0|[1-9][0-9]*)"
        rf"::row_index=(0|[1-9][0-9]*)$"
    )
    if pattern.fullmatch(locator) is None:
        raise UnknownEvidence(f"{label} does not precisely locate one physical source row")
    return locator


def _prepare_session_grid(
    rows: Sequence[Mapping[str, Any]],
    *,
    offset: int,
    entry: AcceptedEntry,
    calendar: tuple[CalendarSession, ...],
) -> list[tuple[pd.Timestamp, Mapping[str, Any]]]:
    if len(rows) != len(EXPECTED_BAR_END_TIMES):
        raise UnknownEvidence(f"H{offset} expected-minute scaffold is not exactly 241 rows")
    date = calendar[entry.entry_calendar_index + offset].trade_date
    by_time: dict[pd.Timestamp, Mapping[str, Any]] = {}
    for raw in rows:
        _require_exact_fields(raw, MINUTE_SCAFFOLD_FIELDS, f"H{offset} minute scaffold")
        row_offset = _exact_int(
            _required(raw, "session_offset", f"H{offset} minute row"),
            f"H{offset} row offset",
            minimum=1,
        )
        if row_offset != offset:
            raise UnknownEvidence(f"H{offset} minute row crosses an offset boundary")
        if (
            _nonempty(
                _required(raw, "protocol_arm", f"H{offset} minute row"),
                "minute protocol arm",
            )
            != entry.protocol_arm
            or _nonempty(
                _required(raw, "gap_id", f"H{offset} minute row"),
                "minute gap id",
            )
            != entry.gap_id
            or canonical_candidate_symbol(
                _required(raw, "candidate_symbol", f"H{offset} minute row"),
                "minute candidate symbol",
            )
            != entry.symbol
        ):
            raise UnknownEvidence(f"H{offset} minute scaffold crosses a candidate boundary")
        observed = _bar_timestamp(
            _required(raw, "bar_end_time", f"H{offset} minute row"),
            date,
            f"H{offset} bar_end_time",
        )
        if observed in by_time:
            raise UnknownEvidence(f"H{offset} minute grid has a duplicate key")
        query_locator = _exact_string(
            _required(raw, "query_locator", f"H{offset} minute row"),
            f"H{offset} query locator",
        )
        query_partition_sha256 = _sha256(
            _required(raw, "query_partition_sha256", f"H{offset} minute row"),
            f"H{offset} query partition hash",
        )
        if query_locator != qd004_query_locator(
            entry, observed
        ) or query_partition_sha256 != QD004_DEVELOPMENT_PARTITION_SHA256.get(observed.year):
            raise UnknownEvidence(f"H{offset} minute query identity/provenance drift")
        by_time[observed] = raw
    expected = [
        date + pd.Timedelta(hours=clock.hour, minutes=clock.minute)
        for clock in EXPECTED_BAR_END_TIMES
    ]
    if set(by_time) != set(expected):
        raise UnknownEvidence(f"H{offset} minute grid differs from the exact 241-bar grid")
    return [(timestamp, by_time[timestamp]) for timestamp in expected]


def _validate_minute(
    raw: Mapping[str, Any],
    *,
    expected_at: pd.Timestamp,
    offset: int,
    entry: AcceptedEntry,
) -> ValidMinute:
    label = f"QD004 H{offset} {expected_at.strftime('%H:%M')}"
    if (
        _exact_int(
            _required(raw, "source_match_count", label),
            f"{label} source match count",
            minimum=0,
        )
        != 1
    ):
        raise UnknownEvidence(f"{label} does not have exactly one source row")
    expected_code, expected_exchange = entry.symbol.rsplit(".", 1)
    qmt = canonical_candidate_symbol(_required(raw, "qmt_code", label), f"{label} qmt_code")
    physical = _exact_string(_required(raw, "symbol", label), f"{label} physical symbol")
    exchange = _exact_string(_required(raw, "exchange", label), f"{label} exchange")
    if qmt != entry.symbol or physical != expected_code or exchange != expected_exchange:
        raise UnknownEvidence(f"{label} physical/canonical identity mismatch")
    if (
        _exact_string(_required(raw, "period", label), f"{label} period") != QD004_PERIOD
        or _exact_string(_required(raw, "adjust", label), f"{label} adjust") != QD004_ADJUST
        or _exact_string(_required(raw, "source", label), f"{label} source") != QD004_SOURCE
    ):
        raise UnknownEvidence(f"{label} source identity mismatch")
    if _date(_required(raw, "trade_date", label), f"{label} trade_date") != expected_at.normalize():
        raise UnknownEvidence(f"{label} trade date mismatch")
    if (
        _bar_timestamp(_required(raw, "bar_end_time", label), expected_at.normalize(), label)
        != expected_at
    ):
        raise UnknownEvidence(f"{label} completed time mismatch")
    available_at = _local_timestamp(_required(raw, "available_at", label), f"{label} available_at")
    if available_at != expected_at:
        raise UnknownEvidence(f"{label} available_at is not its completed bar end")
    query_locator = _exact_string(_required(raw, "query_locator", label), f"{label} query locator")
    query_partition_sha256 = _sha256(
        _required(raw, "query_partition_sha256", label),
        f"{label} query partition hash",
    )
    if query_locator != qd004_query_locator(
        entry, expected_at
    ) or query_partition_sha256 != QD004_DEVELOPMENT_PARTITION_SHA256.get(expected_at.year):
        raise UnknownEvidence(f"{label} partition binding drift")
    physical_source_locator = _validate_physical_qd004_locator(
        _required(raw, "physical_source_locator", label),
        query_locator,
        f"{label} physical source locator",
    )
    source_snapshot_id = _exact_string(
        _required(raw, "source_snapshot_id", label), f"{label} source snapshot id"
    )
    if source_snapshot_id != qd004_source_snapshot_id(expected_at.year):
        raise UnknownEvidence(f"{label} source snapshot binding drift")
    ticks: dict[str, int] = {}
    prices: dict[str, dict[str, Any]] = {}
    for field in ("open", "high", "low", "close"):
        raw_price = _required(raw, field, label)
        _, source_float64_bits, _ = _source_float64_projection(
            raw_price, f"{label} {field}", require_finite=True
        )
        tick = qd004_float32_cent_tick(raw_price, f"{label} {field}")
        source = np.float32(raw_price)
        bits = int(np.asarray([source], dtype="<f4").view("<u4")[0])
        ticks[field] = tick
        prices[field] = {
            "source_float64_bits_le_hex": source_float64_bits,
            "float32_bits_le_hex": f"{bits:08x}",
            "tick": tick,
        }
    if not (
        ticks["low"] <= ticks["open"] <= ticks["high"]
        and ticks["low"] <= ticks["close"] <= ticks["high"]
    ):
        raise UnknownEvidence(f"{label} OHLC ordering is invalid")
    volume, volume_bits = qd004_float64_volume_shares(
        _required(raw, "volume", label), f"{label} volume"
    )
    amount, amount_bits = _source_float64_decimal(
        _required(raw, "amount", label), f"{label} amount"
    )
    if amount < 0:
        raise UnknownEvidence(f"{label} amount is negative")
    if (volume == 0 and amount != 0) or (volume > 0 and amount <= 0):
        raise UnknownEvidence(f"{label} zero/positive volume-amount conservation failed")
    if volume > 0:
        exact_lower = Decimal(ticks["low"] * volume) / Decimal(100)
        exact_upper = Decimal(ticks["high"] * volume) / Decimal(100)
        if not exact_lower <= amount <= exact_upper:
            raise UnknownEvidence(f"{label} amount is outside exact OHLC economic units")
    payload = {
        "protocol_arm": entry.protocol_arm,
        "gap_id": entry.gap_id,
        "candidate_symbol": entry.symbol,
        "session_offset": offset,
        "qmt_code": qmt,
        "symbol": physical,
        "exchange": exchange,
        "period": QD004_PERIOD,
        "adjust": QD004_ADJUST,
        "source": QD004_SOURCE,
        "trade_date": expected_at.strftime("%Y-%m-%d"),
        "bar_end_time": expected_at.isoformat(),
        "available_at": available_at.isoformat(),
        "source_match_count": 1,
        "prices": prices,
        "volume": {
            "source_float64_bits_le_hex": volume_bits,
            "shares": volume,
        },
        "amount": {
            "source_float64_bits_le_hex": amount_bits,
            "decimal_from_float": format(amount, "f"),
        },
        "query_locator": query_locator,
        "query_partition_sha256": query_partition_sha256,
        "physical_source_locator": physical_source_locator,
        "source_snapshot_id": source_snapshot_id,
        "projection": "V30_QD004_PERMITTED_COMPLETED_MINUTE_ROW_V1",
    }
    row_sha256 = _sha256(_required(raw, "row_sha256", label), f"{label} row hash")
    if row_sha256 != normalized_json_sha256(payload):
        raise UnknownEvidence(f"{label} permitted-projection row hash mismatch")
    return ValidMinute(
        offset=offset,
        trade_date=expected_at.normalize(),
        bar_end_time=expected_at,
        open_tick=ticks["open"],
        high_tick=ticks["high"],
        low_tick=ticks["low"],
        close_tick=ticks["close"],
        volume=volume,
        amount=amount,
        row_sha256=row_sha256,
    )


def _unsupported_causal_at(
    event: ActionEvent,
    *,
    asof: pd.Timestamp,
    session_index: int,
    calendar: tuple[CalendarSession, ...],
) -> bool:
    if event.action_kind in SUPPORTED_ACTION_KINDS:
        return False
    if event.known_at_precision == "DAY_ONLY":
        notice = _first_calendar_index_on_or_after(event.known_at.normalize(), calendar)
        return notice is not None and notice <= session_index
    return event.known_at <= asof


def _cash_for_session(
    events: tuple[ActionEvent, ...],
    *,
    entry: AcceptedEntry,
    session_date: pd.Timestamp,
    freeze_at: pd.Timestamp,
    calendar: tuple[CalendarSession, ...],
) -> tuple[Decimal, Decimal]:
    cumulative_terms: list[Decimal] = []
    today_terms: list[Decimal] = []
    for event in events:
        if event.action_kind != "CASH_ONLY":
            continue
        if not (entry.entry_date < event.effective_date <= session_date):
            continue
        if not _terms_causal_at(event, freeze_at, calendar):
            raise UnknownEvidence(
                "cash entitlement is not provably causal before its effective-session open"
            )
        terms = _validated_action_terms(event)
        cumulative_terms.append(terms.cash_cents_per_original_share)
        if event.effective_date == session_date:
            today_terms.append(terms.cash_cents_per_original_share)
    return _exact_decimal_sum(cumulative_terms), _exact_decimal_sum(today_terms)


def _assert_no_unhandled_effective_action(
    events: tuple[ActionEvent, ...],
    *,
    entry: AcceptedEntry,
    session_date: pd.Timestamp,
) -> None:
    for event in events:
        if not (entry.entry_date < event.effective_date <= session_date):
            continue
        if event.action_kind != "CASH_ONLY":
            raise UnknownEvidence(
                "share, rights, or unsupported action became effective while shares were held"
            )


def _risk_known_before_bar(
    spec: RiskSpec,
    *,
    boundary: pd.Timestamp,
    session_index: int,
) -> bool:
    event = spec.event
    if event.known_at_precision == "DAY_ONLY":
        return spec.cancellation_index <= session_index
    return event.known_at <= boundary


def _scale_decimal_by_power_of_ten(value: Decimal, exponent: int) -> Decimal:
    """Scale a finite Decimal without applying the ambient precision context."""
    if not value.is_finite():
        raise UnknownEvidence("cannot scale a nonfinite Decimal")
    sign, digits, source_exponent = value.as_tuple()
    return Decimal((sign, digits, source_exponent + exponent))


def source_ohlcva_sell_quantity_lower_bound(
    minute: ValidMinute,
    sell_limit_tick: int,
) -> SellExecutionQuantityBound:
    """Conservative shares strictly above a resting sell limit.

    This is conditional on the frozen source OHLCVA aggregate.  It is not a
    claim about exchange truth, an observed broker fill, or queue position.
    """
    if not isinstance(minute, ValidMinute):
        raise UnknownEvidence("sell quantity lower bound requires a validated minute")
    limit = _positive_tick(sell_limit_tick, "sell quantity-bound limit")
    volume = _exact_int(minute.volume, "sell quantity-bound volume", minimum=0)
    raw_amount_cents = _scale_decimal_by_power_of_ten(minute.amount, 2)
    exact_low = Decimal(minute.low_tick * volume)
    exact_high = Decimal(minute.high_tick * volume)
    if raw_amount_cents < exact_low or raw_amount_cents > exact_high:
        raise UnknownEvidence("source OHLCVA amount falls outside exact geometric bounds")
    conservative_amount_cents = int(
        raw_amount_cents.to_integral_value(rounding=ROUND_FLOOR)
    )
    outward_adjustment = raw_amount_cents - Decimal(conservative_amount_cents)
    if volume == 0:
        lower_bound = 0
        classification = "NO_TRADES"
    elif minute.low_tick > limit:
        lower_bound = volume
        classification = (
            "FULL_PROXY"
            if lower_bound >= MIN_PROXY_VOLUME_SHARES
            else "POSSIBLE_PARTIAL_OR_FULL"
        )
    elif minute.high_tick <= limit:
        lower_bound = 0
        classification = (
            "POSSIBLE_PARTIAL_OR_FULL"
            if minute.high_tick == limit
            else "SAFE_NO_FILL"
        )
    else:
        denominator = minute.high_tick - limit
        numerator = conservative_amount_cents - limit * volume
        lower_bound = 0 if numerator <= 0 else (numerator + denominator - 1) // denominator
        if lower_bound > volume:
            raise UnknownEvidence("source OHLCVA strict-through lower bound exceeds volume")
        classification = (
            "FULL_PROXY"
            if lower_bound >= MIN_PROXY_VOLUME_SHARES
            else "POSSIBLE_PARTIAL_OR_FULL"
        )
    evidence = {
        "minute_row_sha256": minute.row_sha256,
        "sell_limit_tick": limit,
        "low_tick": minute.low_tick,
        "high_tick": minute.high_tick,
        "volume_shares": volume,
        "raw_amount_cents": format(raw_amount_cents, "f"),
        "conservative_amount_cents": conservative_amount_cents,
        "outward_adjustment_cents": format(outward_adjustment, "f"),
        "outward_direction": "FLOOR_SOURCE_FLOAT64_AMOUNT_CENTS",
        "source_ohlcva_conditional_lower_bound_shares": lower_bound,
        "minimum_proxy_shares": MIN_PROXY_VOLUME_SHARES,
        "classification": classification,
        "interpretation": "SOURCE_OHLCVA_CONDITIONAL_LOWER_BOUND_NOT_EXCHANGE_TRUTH",
        "projection": "V30_STAGE_B_SELL_EXECUTION_QUANTITY_BOUND_V1",
    }
    return SellExecutionQuantityBound(
        source_ohlcva_conditional_lower_bound_shares=lower_bound,
        raw_amount_cents=raw_amount_cents,
        conservative_amount_cents=conservative_amount_cents,
        outward_adjustment_cents=outward_adjustment,
        classification=classification,
        evidence_sha256=normalized_json_sha256(evidence),
    )


def _scan_session(
    rows: Sequence[Mapping[str, Any]],
    *,
    offset: int,
    entry: AcceptedEntry,
    calendar: tuple[CalendarSession, ...],
    order_limit_tick: int,
    session_reference_tick: int,
    target_order: bool,
    risk_specs: tuple[RiskSpec, ...],
    events: tuple[ActionEvent, ...],
) -> SessionScan:
    reference_tick = _positive_tick(session_reference_tick, "session exchange-reference tick")
    grid = _prepare_session_grid(rows, offset=offset, entry=entry, calendar=calendar)
    index = entry.entry_calendar_index + offset
    previous_boundary = _order_freeze_at(calendar[index].trade_date)
    reached_evidence: list[str] = []
    all_zero_volume = True
    all_zero_rows_flat_at_reference = True
    saw_possible_partial = False
    for expected_at, raw in grid:
        for event in events:
            if _unsupported_causal_at(
                event, asof=previous_boundary, session_index=index, calendar=calendar
            ):
                raise UnknownEvidence("unsupported action became causal while shares were held")
        causal_risks = tuple(
            spec
            for spec in risk_specs
            if spec.effective_index <= entry.entry_calendar_index + TERMINAL_OFFSET
            and _risk_known_before_bar(spec, boundary=previous_boundary, session_index=index)
        )
        for spec in causal_risks:
            _validated_action_terms(spec.event)
        if target_order and causal_risks:
            if saw_possible_partial:
                return SessionScan(
                    "POSSIBLE_PARTIAL_UNKNOWN",
                    reached_evidence_sha256=tuple(reached_evidence),
                    blocker=(
                        "a possible partial target fill preceded the causal risk cancellation"
                    ),
                )
            return SessionScan(
                "TARGET_CANCELLED_FOR_RISK",
                reached_evidence_sha256=tuple(reached_evidence),
            )
        source_match_count = _exact_int(
            _required(raw, "source_match_count", f"H{offset} expected minute"),
            f"H{offset} source match count",
            minimum=0,
        )
        if source_match_count not in {0, 1}:
            raise UnknownEvidence(f"H{offset} expected minute has duplicate source rows")
        if source_match_count == 0:
            _require_zero_match_physical_nulls(raw, MINUTE_PHYSICAL_FIELDS, f"H{offset}")
            raise UnknownEvidence(
                f"H{offset} reached expected minute has no QD004 physical source row"
            )
        minute = _validate_minute(raw, expected_at=expected_at, offset=offset, entry=entry)
        sell_quantity_bound = source_ohlcva_sell_quantity_lower_bound(
            minute, order_limit_tick
        )
        reached_evidence.append(sell_quantity_bound.evidence_sha256)
        if minute.volume != 0:
            all_zero_volume = False
        elif not (
            minute.open_tick
            == minute.high_tick
            == minute.low_tick
            == minute.close_tick
            == reference_tick
        ):
            all_zero_rows_flat_at_reference = False
        qualifying = sell_quantity_bound.classification == "FULL_PROXY"
        possible_partial = (
            sell_quantity_bound.classification == "POSSIBLE_PARTIAL_OR_FULL"
        )
        if possible_partial:
            saw_possible_partial = True
        exact_risk_during_bar = [
            spec
            for spec in risk_specs
            if spec.event.known_at_precision == "EXACT_TIMESTAMP"
            and previous_boundary < spec.event.known_at <= expected_at
        ]
        for spec in exact_risk_during_bar:
            _validated_action_terms(spec.event)
        exact_unsupported_during_bar = [
            event
            for event in events
            if event.action_kind not in SUPPORTED_ACTION_KINDS
            and event.known_at_precision == "EXACT_TIMESTAMP"
            and previous_boundary < event.known_at <= expected_at
        ]
        if exact_unsupported_during_bar and qualifying:
            raise UnknownEvidence("unsupported-action/fill intrabar ordering is unknowable")
        if target_order and exact_risk_during_bar:
            if qualifying or saw_possible_partial:
                return SessionScan(
                    "POSSIBLE_PARTIAL_UNKNOWN",
                    reached_evidence_sha256=tuple(reached_evidence),
                    blocker="target-fill/risk-notice intrabar ordering is unknowable",
                )
            return SessionScan(
                "TARGET_CANCELLED_FOR_RISK",
                reached_evidence_sha256=tuple(reached_evidence),
            )
        if qualifying:
            return SessionScan(
                "FILLED",
                order_limit_tick,
                minute.bar_end_time,
                reached_evidence_sha256=tuple(reached_evidence),
            )
        if exact_unsupported_during_bar:
            raise UnknownEvidence("unsupported action became causal while shares were held")
        previous_boundary = expected_at
    if all_zero_volume and not all_zero_rows_flat_at_reference:
        raise UnknownEvidence(
            f"H{offset} all-zero-volume physical session is not flat at its exchange reference"
        )
    if saw_possible_partial:
        return SessionScan(
            "POSSIBLE_PARTIAL_UNKNOWN",
            complete_physical_session=True,
            all_physical_rows_zero_volume=False,
            reached_evidence_sha256=tuple(reached_evidence),
            blocker=(f"H{offset} ended with an unresolved possible partial/full resting-sell fill"),
        )
    return SessionScan(
        "NO_FILL",
        complete_physical_session=True,
        all_physical_rows_zero_volume=all_zero_volume,
        reached_evidence_sha256=tuple(reached_evidence),
    )


def _active_risks_at_preopen(
    risk_specs: tuple[RiskSpec, ...],
    session_index: int,
    calendar: tuple[CalendarSession, ...],
) -> tuple[RiskSpec, ...]:
    freeze_at = _order_freeze_at(calendar[session_index].trade_date)
    return tuple(
        spec
        for spec in risk_specs
        if (
            spec.cancellation_index <= session_index
            if spec.event.known_at_precision == "DAY_ONLY"
            else spec.event.known_at <= freeze_at
        )
    )


def _check_risk_deadline(
    active: tuple[RiskSpec, ...], session_index: int, *, before_scan: bool
) -> None:
    if not active:
        return
    earliest_effective = min(spec.effective_index for spec in active)
    if session_index >= earliest_effective:
        when = "before scan" if before_scan else "after no-fill"
        raise UnknownEvidence(
            f"pre-action exit was not complete strictly before effectiveness ({when})"
        )


def _outcome_evidence_payload(outcome: StageBOutcome) -> dict[str, Any]:
    record = asdict(outcome)
    record.pop("outcome_evidence_sha256")
    for field in ("signal_date", "entry_date", "exit_date"):
        if record[field] is not None:
            record[field] = pd.Timestamp(record[field]).strftime("%Y-%m-%d")
    if record["exit_at"] is not None:
        record["exit_at"] = pd.Timestamp(record["exit_at"]).isoformat()
    record["reached_evidence_sha256"] = list(record["reached_evidence_sha256"])
    return {
        "outcome": record,
        "projection": "V30_STAGE_B_OUTCOME_EVIDENCE_CHAIN_V2",
    }


def _seal_outcome(outcome: StageBOutcome, reached_evidence_sha256: Sequence[str]) -> StageBOutcome:
    reached = tuple(_sha256(value, "reached evidence digest") for value in reached_evidence_sha256)
    unsealed = replace(
        outcome,
        reached_evidence_sha256=reached,
        outcome_evidence_sha256=None,
    )
    return replace(
        unsealed,
        outcome_evidence_sha256=normalized_json_sha256(_outcome_evidence_payload(unsealed)),
    )


def _validate_outcome_evidence_digest(outcome: StageBOutcome) -> str:
    observed = _sha256(outcome.outcome_evidence_sha256, "outcome evidence digest")
    for value in outcome.reached_evidence_sha256:
        _sha256(value, "reached outcome evidence digest")
    expected = normalized_json_sha256(
        _outcome_evidence_payload(replace(outcome, outcome_evidence_sha256=None))
    )
    if observed != expected:
        raise V30StageBError("outcome evidence digest does not recompute")
    return observed


def _completed_outcome(
    entry: AcceptedEntry,
    *,
    exit_reason: str,
    exit_date: pd.Timestamp,
    exit_at: pd.Timestamp,
    exit_calendar_index: int,
    exit_tick: int,
    cumulative_cash_cents: Decimal,
    reached_evidence_sha256: Sequence[str],
) -> StageBOutcome:
    if exit_reason not in EXIT_REASONS:
        raise V30StageBError("unknown terminal exit reason")
    holding = exit_calendar_index - entry.entry_calendar_index
    if holding < 1 or holding > TERMINAL_OFFSET:
        raise V30StageBError("terminal holding-session identity is outside H1:H30")
    proof_at = _local_timestamp(exit_at, "exit proof timestamp")
    if proof_at.normalize() != exit_date or proof_at.time() not in EXPECTED_BAR_END_TIMES:
        raise V30StageBError("exit proof timestamp is not one frozen minute on exit_date")
    entry_cash = Decimal(ORDER_SIZE_SHARES * entry.entry_tick) * (Decimal(1) + PER_SIDE_FEE)
    exit_cash = Decimal(ORDER_SIZE_SHARES * exit_tick) * (Decimal(1) - PER_SIDE_FEE)
    performance_cash_credit = Decimal(0)
    net_numerator = exit_tick * 998 - entry.entry_tick * 1002
    net_denominator = entry.entry_tick * 1002
    net = Fraction(net_numerator, net_denominator)
    return _seal_outcome(
        StageBOutcome(
            protocol_arm=entry.protocol_arm,
            gap_id=entry.gap_id,
            symbol=entry.symbol,
            signal_date=entry.signal_date,
            entry_date=entry.entry_date,
            entry_calendar_index=entry.entry_calendar_index,
            entry_tick=entry.entry_tick,
            outcome_status=COMPLETE_OUTCOME,
            exit_reason=exit_reason,
            exit_date=exit_date,
            exit_at=proof_at,
            exit_calendar_index=exit_calendar_index,
            exit_tick=exit_tick,
            holding_sessions=holding,
            gross_coordinate_cash_cents_per_original_share=_canonical_decimal_text(
                cumulative_cash_cents
            ),
            entry_cash_out_cents=_canonical_decimal_text(entry_cash),
            exit_cash_in_cents=_canonical_decimal_text(exit_cash),
            cash_distribution_performance_credit_cents=_canonical_decimal_text(
                performance_cash_credit
            ),
            net_return_numerator=net_numerator,
            net_return_denominator=net_denominator,
            net_return=_fraction_display_text(net),
        ),
        reached_evidence_sha256,
    )


def _unknown_outcome(
    entry: AcceptedEntry,
    blocker: str,
    reached_evidence_sha256: Sequence[str] = (),
) -> StageBOutcome:
    return _seal_outcome(
        StageBOutcome(
            protocol_arm=entry.protocol_arm,
            gap_id=entry.gap_id,
            symbol=entry.symbol,
            signal_date=entry.signal_date,
            entry_date=entry.entry_date,
            entry_calendar_index=entry.entry_calendar_index,
            entry_tick=entry.entry_tick,
            outcome_status=UNKNOWN_OUTCOME,
            blocker=blocker,
        ),
        reached_evidence_sha256,
    )


def _unexited_outcome(
    entry: AcceptedEntry, reached_evidence_sha256: Sequence[str]
) -> StageBOutcome:
    return _seal_outcome(
        StageBOutcome(
            protocol_arm=entry.protocol_arm,
            gap_id=entry.gap_id,
            symbol=entry.symbol,
            signal_date=entry.signal_date,
            entry_date=entry.entry_date,
            entry_calendar_index=entry.entry_calendar_index,
            entry_tick=entry.entry_tick,
            outcome_status=UNEXITED_OUTCOME,
            blocker="COMPLETE_H30_SCAN_WITHOUT_PROXY_EXIT",
        ),
        reached_evidence_sha256,
    )


def _evaluate_one_outcome_strict(
    entry_value: AcceptedEntry | Mapping[str, Any],
    daily_projection: Any,
    minute_projection: Any,
    action_projection: Any,
    calendar_value: Any,
) -> StageBOutcome:
    calendar = normalize_market_calendar(calendar_value)
    entry = normalize_accepted_entry(entry_value, calendar)
    daily_by_offset = _prepare_daily_projection(daily_projection, entry, calendar)
    minute_by_offset = _minute_groups(minute_projection)
    action_envelope = normalize_action_envelope(action_projection, entry, calendar)
    events = action_envelope.events
    risk_specs = _action_relevance_check(entry, events, calendar)
    validated_daily: dict[int, ValidDaily] = {}
    reached_evidence_sha256: list[str] = [
        FROZEN_CALENDAR_CANONICAL_SHA256,
        _accepted_entry_evidence_sha256(entry),
        action_envelope.completeness_sha256,
    ]

    def daily(offset: int) -> ValidDaily:
        if offset not in validated_daily:
            validated_daily[offset] = _validate_daily(
                daily_by_offset[offset],
                offset=offset,
                entry=entry,
                events=events,
                calendar=calendar,
            )
            reached_evidence_sha256.append(validated_daily[offset].row_sha256)
        return validated_daily[offset]

    # H0 is the only causal initializer for the exchange-reference ledger.
    h0_daily = daily(0)
    if _daily_market_state(h0_daily, 0) != "TRADED":
        raise UnknownEvidence("H0 cannot initialize the exchange reference as a traded session")
    exchange_reference_ledger_tick = h0_daily.close_tick
    pending_reason: str | None = None

    for offset in range(1, TERMINAL_OFFSET + 1):
        session_index = entry.entry_calendar_index + offset
        session_date = calendar[session_index].trade_date
        freeze_at = _order_freeze_at(session_date)
        if any(
            _unsupported_causal_at(
                event,
                asof=freeze_at,
                session_index=session_index,
                calendar=calendar,
            )
            for event in events
        ):
            raise UnknownEvidence("unsupported action is causal before a required session")
        cumulative_cash, cash_today = _cash_for_session(
            events,
            entry=entry,
            session_date=session_date,
            freeze_at=freeze_at,
            calendar=calendar,
        )
        session_reference_tick = exchange_reference_tick(exchange_reference_ledger_tick, cash_today)
        _assert_no_unhandled_effective_action(events, entry=entry, session_date=session_date)
        active_risks = _active_risks_at_preopen(risk_specs, session_index, calendar)
        for spec in active_risks:
            _validated_action_terms(spec.event)
        _check_risk_deadline(active_risks, session_index, before_scan=True)

        preopen_executable_risks = tuple(
            spec for spec in active_risks if spec.earliest_order_index <= session_index
        )
        risk_cancellation_wait = bool(active_risks and not preopen_executable_risks)
        if preopen_executable_risks:
            pending_reason = "PRE_ACTION_RISK"

        if pending_reason is not None:
            limit_tick = forced_sell_limit_tick(exchange_reference_ledger_tick, cash_today)
            scan = _scan_session(
                minute_by_offset.get(offset, []),
                offset=offset,
                entry=entry,
                calendar=calendar,
                order_limit_tick=limit_tick,
                session_reference_tick=session_reference_tick,
                target_order=False,
                risk_specs=risk_specs,
                events=events,
            )
            reached_evidence_sha256.extend(scan.reached_evidence_sha256)
            if scan.status == "POSSIBLE_PARTIAL_UNKNOWN":
                return _unknown_outcome(
                    entry,
                    _exact_string(scan.blocker, "possible-partial blocker"),
                    reached_evidence_sha256,
                )
            if scan.status == "FILLED":
                assert scan.exit_tick is not None and scan.exit_at is not None
                reason = "PRE_ACTION_RISK" if active_risks else pending_reason
                return _completed_outcome(
                    entry,
                    exit_reason=reason,
                    exit_date=session_date,
                    exit_at=scan.exit_at,
                    exit_calendar_index=session_index,
                    exit_tick=scan.exit_tick,
                    cumulative_cash_cents=cumulative_cash,
                    reached_evidence_sha256=reached_evidence_sha256,
                )
        elif offset <= TARGET_LAST_OFFSET and not risk_cancellation_wait:
            limit_tick = target_sell_limit_tick(
                entry.entry_tick,
                entry.raw_l_tick,
                cumulative_cash,
                exchange_reference_ledger_tick,
                cash_today,
            )
            if limit_tick is None:
                # The economic target is not replaced by U5.  There is no
                # legal universal-band order and this session's minute source
                # must remain physically unopened.
                scan = SessionScan("NO_FILL")
                close_at = session_date + pd.Timedelta(hours=15)
                if any(
                    _unsupported_causal_at(
                        event,
                        asof=close_at,
                        session_index=session_index,
                        calendar=calendar,
                    )
                    for event in events
                ):
                    raise UnknownEvidence(
                        "unsupported action became causal on a target-no-order day"
                    )
                active_risks = tuple(
                    spec
                    for spec in risk_specs
                    if _risk_known_before_bar(
                        spec,
                        boundary=close_at,
                        session_index=session_index,
                    )
                )
                for spec in active_risks:
                    _validated_action_terms(spec.event)
                if active_risks:
                    if min(spec.earliest_order_index for spec in active_risks) >= min(
                        spec.effective_index for spec in active_risks
                    ):
                        raise UnknownEvidence("risk notice leaves no pre-effective attempt")
                    pending_reason = "PRE_ACTION_RISK"
            else:
                scan = _scan_session(
                    minute_by_offset.get(offset, []),
                    offset=offset,
                    entry=entry,
                    calendar=calendar,
                    order_limit_tick=limit_tick,
                    session_reference_tick=session_reference_tick,
                    target_order=True,
                    risk_specs=risk_specs,
                    events=events,
                )
                reached_evidence_sha256.extend(scan.reached_evidence_sha256)
            if scan.status == "POSSIBLE_PARTIAL_UNKNOWN":
                return _unknown_outcome(
                    entry,
                    _exact_string(scan.blocker, "possible-partial blocker"),
                    reached_evidence_sha256,
                )
            if scan.status == "FILLED":
                assert scan.exit_tick is not None and scan.exit_at is not None
                return _completed_outcome(
                    entry,
                    exit_reason="A67_TARGET",
                    exit_date=session_date,
                    exit_at=scan.exit_at,
                    exit_calendar_index=session_index,
                    exit_tick=scan.exit_tick,
                    cumulative_cash_cents=cumulative_cash,
                    reached_evidence_sha256=reached_evidence_sha256,
                )
            if scan.status == "TARGET_CANCELLED_FOR_RISK":
                active_risks = tuple(
                    spec
                    for spec in risk_specs
                    if _risk_known_before_bar(
                        spec,
                        boundary=session_date + pd.Timedelta(hours=15),
                        session_index=session_index,
                    )
                )
                if not active_risks:
                    raise V30StageBError("risk cancellation lost its causal event")
                if min(spec.earliest_order_index for spec in active_risks) >= min(
                    spec.effective_index for spec in active_risks
                ):
                    raise UnknownEvidence("risk notice leaves no pre-effective attempt")
                pending_reason = "PRE_ACTION_RISK"
        else:
            scan = SessionScan("NO_FILL")

        if offset < TERMINAL_OFFSET:
            current_daily = daily(offset)
        else:
            current_daily = None

        if active_risks:
            _check_risk_deadline(active_risks, session_index + 1, before_scan=False)

        if pending_reason is None and not active_risks:
            if offset <= FAILURE_LAST_OFFSET:
                assert current_daily is not None
                pivot = adjusted_pivot_tick(entry.persisted_reclaimed_pivot_tick, cumulative_cash)
                if current_daily.close_tick < pivot:
                    pending_reason = "PIVOT_FAILURE"
            elif offset == TARGET_LAST_OFFSET:
                pending_reason = "H10_TIME"

        if offset == TERMINAL_OFFSET:
            return _unexited_outcome(entry, reached_evidence_sha256)
        assert current_daily is not None
        exchange_reference_ledger_tick = _advance_exchange_reference(
            session_reference_tick,
            current_daily,
            scan,
            offset,
        )

    raise V30StageBError("unreachable Stage-B terminal state")


def evaluate_one_outcome(
    entry_value: AcceptedEntry | Mapping[str, Any],
    daily_projection: Any,
    minute_projection: Any,
    action_projection: Any,
    calendar_value: Any,
) -> StageBOutcome:
    """Replay one frozen accepted row, converting evidence defects to UNKNOWN."""
    calendar = normalize_market_calendar(calendar_value)
    entry = normalize_accepted_entry(entry_value, calendar)
    try:
        return _evaluate_one_outcome_strict(
            entry, daily_projection, minute_projection, action_projection, calendar
        )
    except UnknownEvidence as exc:
        return _unknown_outcome(entry, str(exc))


def outcome_to_record(outcome: StageBOutcome) -> dict[str, Any]:
    result = asdict(outcome)
    for field in ("signal_date", "entry_date", "exit_date"):
        if result[field] is not None:
            result[field] = pd.Timestamp(result[field]).strftime("%Y-%m-%d")
    if result["exit_at"] is not None:
        result["exit_at"] = pd.Timestamp(result["exit_at"]).isoformat()
    result["reached_evidence_sha256"] = list(result["reached_evidence_sha256"])
    return result


def _not_opened_outcome(entry: AcceptedEntry) -> StageBOutcome:
    return _seal_outcome(
        StageBOutcome(
            protocol_arm=entry.protocol_arm,
            gap_id=entry.gap_id,
            symbol=entry.symbol,
            signal_date=entry.signal_date,
            entry_date=entry.entry_date,
            entry_calendar_index=entry.entry_calendar_index,
            entry_tick=entry.entry_tick,
            outcome_status=NOT_OPENED_OUTCOME,
            blocker="PRIOR_ACCEPTED_ROW_WAS_UNRESOLVED",
        ),
        (),
    )


def _accepted_entry_evidence_sha256(entry: AcceptedEntry) -> str:
    return normalized_json_sha256(
        {
            "accepted_entry": asdict(entry),
            "projection": "V30_STAGE_A_ACCEPTED_ENTRY_REVALIDATION_V1",
        }
    )


def _accepted_seal_row(entry: AcceptedEntry) -> AcceptedEntrySealRow:
    return AcceptedEntrySealRow(
        protocol_arm=entry.protocol_arm,
        gap_id=entry.gap_id,
        symbol=entry.symbol,
        signal_date=entry.signal_date,
        entry_date=entry.entry_date,
        entry_evidence_sha256=_accepted_entry_evidence_sha256(entry),
    )


def _accepted_seal_row_payload(row: AcceptedEntrySealRow) -> dict[str, Any]:
    return {
        "protocol_arm": row.protocol_arm,
        "gap_id": row.gap_id,
        "symbol": row.symbol,
        "signal_date": row.signal_date.strftime("%Y-%m-%d"),
        "entry_date": row.entry_date.strftime("%Y-%m-%d"),
        "entry_evidence_sha256": row.entry_evidence_sha256,
    }


def _accepted_key_evidence_sha256(rows: Sequence[AcceptedEntrySealRow]) -> str:
    return normalized_json_sha256(
        {
            "rows": [_accepted_seal_row_payload(row) for row in rows],
            "projection": "V30_STAGE_A_ACCEPTED_FIVE_KEY_EVIDENCE_V1",
        }
    )


def _accepted_cohort_sha256(protocol_arm: str, rows: Sequence[AcceptedEntrySealRow]) -> str:
    return normalized_json_sha256(
        {
            "protocol_arm": protocol_arm,
            "accepted_count": len(rows),
            "rows": [_accepted_seal_row_payload(row) for row in rows],
            "projection": "V30_STAGE_A_ACCEPTED_COHORT_BRIDGE_V1",
        }
    )


def _provisional_stage_a_cohort_seal(
    entries: Sequence[AcceptedEntry],
) -> StageACohortSeal:
    """Temporary bridge; replaced by the exact repaired Stage-A seal API."""
    if not entries:
        raise V30StageBError("cannot seal an empty accepted cohort")
    rows = tuple(_accepted_seal_row(entry) for entry in entries)
    arm = entries[0].protocol_arm
    return StageACohortSeal(
        protocol_arm=arm,
        accepted_count=len(rows),
        accepted_cohort_sha256=_accepted_cohort_sha256(arm, rows),
        accepted_key_evidence_sha256=_accepted_key_evidence_sha256(rows),
    )


def _terminal_ledger_sha256(outcomes: Sequence[StageBOutcome]) -> str:
    return normalized_json_sha256(
        {
            "outcomes": [outcome_to_record(item) for item in outcomes],
            "projection": "V30_STAGE_B_TERMINAL_LEDGER_V2",
        }
    )


def _stage_b_replay_seal_payload(
    *,
    selected_arm: str,
    accepted_count: int,
    stage_a_accepted_cohort_sha256: str,
    stage_a_accepted_key_evidence_sha256: str,
    accepted_rows: Sequence[AcceptedEntrySealRow],
    outcome_evidence_sha256: Sequence[str],
    terminal_ledger_sha256: str,
) -> dict[str, Any]:
    return {
        "selected_arm": selected_arm,
        "accepted_count": accepted_count,
        "stage_a_accepted_cohort_sha256": stage_a_accepted_cohort_sha256,
        "stage_a_accepted_key_evidence_sha256": stage_a_accepted_key_evidence_sha256,
        "accepted_rows": [_accepted_seal_row_payload(row) for row in accepted_rows],
        "outcome_evidence_sha256": list(outcome_evidence_sha256),
        "terminal_ledger_sha256": terminal_ledger_sha256,
        "projection": "V30_STAGE_B_CONTROLLED_REPLAY_SEAL_V1",
    }


def _seal_stage_b_replay(
    stage_a_seal: StageACohortSeal,
    accepted_rows: Sequence[AcceptedEntrySealRow],
    outcomes: Sequence[StageBOutcome],
) -> StageBReplaySeal:
    outcome_digests = tuple(_validate_outcome_evidence_digest(item) for item in outcomes)
    terminal_digest = _terminal_ledger_sha256(outcomes)
    payload = _stage_b_replay_seal_payload(
        selected_arm=stage_a_seal.protocol_arm,
        accepted_count=stage_a_seal.accepted_count,
        stage_a_accepted_cohort_sha256=stage_a_seal.accepted_cohort_sha256,
        stage_a_accepted_key_evidence_sha256=stage_a_seal.accepted_key_evidence_sha256,
        accepted_rows=accepted_rows,
        outcome_evidence_sha256=outcome_digests,
        terminal_ledger_sha256=terminal_digest,
    )
    return StageBReplaySeal(
        selected_arm=stage_a_seal.protocol_arm,
        accepted_count=stage_a_seal.accepted_count,
        stage_a_accepted_cohort_sha256=stage_a_seal.accepted_cohort_sha256,
        stage_a_accepted_key_evidence_sha256=stage_a_seal.accepted_key_evidence_sha256,
        accepted_rows=tuple(accepted_rows),
        outcomes=tuple(outcomes),
        outcome_evidence_sha256=outcome_digests,
        terminal_ledger_sha256=terminal_digest,
        replay_seal_sha256=normalized_json_sha256(payload),
    )


def replay_frozen_cohort(
    stage_a_seal: StageACohortSeal,
    accepted_entries: Any,
    calendar_value: Any,
    evidence_loader: Callable[[AcceptedEntry], StageBReplayEvidence],
) -> StageBReplaySeal:
    """Run the registered replay; callers may provide evidence, never outcomes."""
    calendar = normalize_market_calendar(calendar_value)
    if isinstance(accepted_entries, Sequence) and all(
        isinstance(item, AcceptedEntry) for item in accepted_entries
    ):
        raw_entries: Sequence[AcceptedEntry | Mapping[str, Any]] = accepted_entries
    else:
        raw_entries = _records(
            accepted_entries,
            "accepted cohort",
            expected_fields=ACCEPTED_ENTRY_FIELDS,
        )
    entries = [normalize_accepted_entry(row, calendar) for row in raw_entries]
    if not isinstance(stage_a_seal, StageACohortSeal):
        raise V30StageBError("Stage B requires the typed Stage-A accepted-cohort seal")
    if not entries:
        raise V30StageBError("selected accepted cohort is empty")
    if len(entries) < MIN_ACCEPTED:
        raise V30StageBError("Stage B cannot open a cohort below the Stage-A frequency gate")
    if len(
        {
            (
                item.protocol_arm,
                item.gap_id,
                item.symbol,
                item.signal_date,
                item.entry_date,
            )
            for item in entries
        }
    ) != len(entries):
        raise V30StageBError("selected accepted cohort five-key identity is duplicate")
    if len({item.protocol_arm for item in entries}) != 1:
        raise V30StageBError("selected accepted cohort mixes protocol arms")
    entries.sort(
        key=lambda item: (
            item.protocol_arm,
            item.gap_id,
            item.symbol,
            item.signal_date,
            item.entry_date,
        )
    )
    accepted_rows = tuple(_accepted_seal_row(entry) for entry in entries)
    if (
        stage_a_seal.protocol_arm != entries[0].protocol_arm
        or stage_a_seal.accepted_count != len(entries)
        or stage_a_seal.accepted_key_evidence_sha256 != _accepted_key_evidence_sha256(accepted_rows)
        or stage_a_seal.accepted_cohort_sha256
        != _accepted_cohort_sha256(stage_a_seal.protocol_arm, accepted_rows)
    ):
        raise V30StageBError("Stage-A accepted cohort seal does not recompute exactly")
    outcomes: list[StageBOutcome] = []
    unresolved = False
    for entry in entries:
        if unresolved:
            outcomes.append(_not_opened_outcome(entry))
            continue
        evidence = evidence_loader(entry)
        if not isinstance(evidence, StageBReplayEvidence):
            raise V30StageBError("evidence loader did not return StageBReplayEvidence")
        outcome = evaluate_one_outcome(
            entry,
            evidence.daily_projection,
            evidence.minute_projection,
            evidence.action_envelope,
            calendar,
        )
        expected_identity = (
            entry.protocol_arm,
            entry.gap_id,
            entry.symbol,
            entry.signal_date,
            entry.entry_date,
        )
        actual_identity = (
            outcome.protocol_arm,
            outcome.gap_id,
            outcome.symbol,
            outcome.signal_date,
            outcome.entry_date,
        )
        if actual_identity != expected_identity:
            raise V30StageBError("registered replay crossed an accepted-row boundary")
        if outcome.outcome_status == COMPLETE_OUTCOME:
            _sha256(outcome.outcome_evidence_sha256, "controlled outcome evidence digest")
        outcomes.append(outcome)
        if outcome.outcome_status != COMPLETE_OUTCOME:
            unresolved = True
    if len(outcomes) != len(entries):
        raise V30StageBError("accepted/outcome row conservation failed")
    return _seal_stage_b_replay(stage_a_seal, accepted_rows, outcomes)


def _mean_decimal(values: Sequence[Decimal]) -> Decimal:
    if not values:
        raise V30StageBError("cannot average an empty sequence")
    required_precision = (
        max(len(value.as_tuple().digits) for value in values) + len(str(len(values))) + 16
    )
    with localcontext() as context:
        context.prec = max(80, required_precision)
        return _exact_decimal_sum(values) / Decimal(len(values))


def _median_decimal(values: Sequence[Decimal]) -> Decimal:
    if not values:
        raise V30StageBError("cannot take the median of an empty sequence")
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    with localcontext() as context:
        context.prec = max(
            80,
            len(ordered[midpoint - 1].as_tuple().digits)
            + len(ordered[midpoint].as_tuple().digits)
            + 4,
        )
        return _exact_decimal_sum((ordered[midpoint - 1], ordered[midpoint])) / Decimal(2)


def _mean_fraction(values: Sequence[Fraction]) -> Fraction:
    if not values:
        raise V30StageBError("cannot average an empty rational sequence")
    return sum(values, start=Fraction(0, 1)) / len(values)


def _median_fraction(values: Sequence[Fraction]) -> Fraction:
    if not values:
        raise V30StageBError("cannot take the median of an empty rational sequence")
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2


def _validate_complete_outcome_ledger(outcome: StageBOutcome) -> Fraction:
    if (
        outcome.exit_tick is None
        or outcome.net_return is None
        or outcome.net_return_numerator is None
        or outcome.net_return_denominator is None
        or outcome.gross_coordinate_cash_cents_per_original_share is None
        or outcome.entry_cash_out_cents is None
        or outcome.exit_cash_in_cents is None
        or outcome.cash_distribution_performance_credit_cents is None
    ):
        raise V30StageBError("complete outcome cash ledger is missing")
    entry_tick = _positive_tick(outcome.entry_tick, "ledger entry tick")
    exit_tick = _positive_tick(outcome.exit_tick, "ledger exit tick")
    gross_coordinate_cash = _canonical_outcome_decimal(
        outcome.gross_coordinate_cash_cents_per_original_share,
        "gross-coordinate cash cents",
    )
    observed_entry = _canonical_outcome_decimal(
        outcome.entry_cash_out_cents, "ledger entry cash out"
    )
    observed_exit = _canonical_outcome_decimal(outcome.exit_cash_in_cents, "ledger exit cash in")
    observed_cash_credit = _canonical_outcome_decimal(
        outcome.cash_distribution_performance_credit_cents,
        "cash-distribution performance credit",
    )
    observed_return_text = _canonical_outcome_decimal(
        outcome.net_return, "ledger net return display"
    )
    observed_numerator = _exact_int(
        outcome.net_return_numerator, "ledger net return numerator"
    )
    observed_denominator = _exact_int(
        outcome.net_return_denominator,
        "ledger net return denominator",
        minimum=1,
    )
    if (
        gross_coordinate_cash < 0
        or observed_entry <= 0
        or observed_exit <= 0
        or observed_cash_credit < 0
    ):
        raise V30StageBError("complete outcome cash ledger has an invalid sign")
    expected_entry = Decimal(ORDER_SIZE_SHARES * entry_tick) * (Decimal(1) + PER_SIDE_FEE)
    expected_exit = Decimal(ORDER_SIZE_SHARES * exit_tick) * (Decimal(1) - PER_SIDE_FEE)
    expected_numerator = exit_tick * 998 - entry_tick * 1002
    expected_denominator = entry_tick * 1002
    expected_return = Fraction(expected_numerator, expected_denominator)
    if (
        observed_entry != expected_entry
        or observed_exit != expected_exit
        or observed_cash_credit != 0
        or observed_numerator != expected_numerator
        or observed_denominator != expected_denominator
        or outcome.net_return != _fraction_display_text(expected_return)
        or observed_return_text != Decimal(outcome.net_return)
    ):
        raise V30StageBError("complete outcome cash ledger does not conserve exactly")
    return expected_return


def _validate_stage_b_replay_seal(seal: StageBReplaySeal) -> tuple[StageBOutcome, ...]:
    if not isinstance(seal, StageBReplaySeal):
        raise V30StageBError("terminal summary requires a typed StageBReplaySeal")
    accepted = _exact_int(seal.accepted_count, "sealed accepted count", minimum=0)
    selected_arm = _exact_string(seal.selected_arm, "sealed selected arm")
    if selected_arm not in SIGNAL_ARMS:
        raise V30StageBError("sealed selected arm is not frozen")
    if not (
        accepted
        == len(seal.accepted_rows)
        == len(seal.outcomes)
        == len(seal.outcome_evidence_sha256)
    ):
        raise V30StageBError("Stage-B replay seal row counts do not conserve")
    accepted_rows: list[AcceptedEntrySealRow] = []
    for row in seal.accepted_rows:
        if not isinstance(row, AcceptedEntrySealRow):
            raise V30StageBError("Stage-B replay seal has an untyped accepted row")
        accepted_rows.append(
            AcceptedEntrySealRow(
                protocol_arm=_exact_string(row.protocol_arm, "sealed row arm"),
                gap_id=_exact_string(row.gap_id, "sealed row gap id"),
                symbol=canonical_candidate_symbol(row.symbol, "sealed row symbol"),
                signal_date=_date(row.signal_date, "sealed row signal date"),
                entry_date=_date(row.entry_date, "sealed row entry date"),
                entry_evidence_sha256=_sha256(
                    row.entry_evidence_sha256, "sealed row entry evidence digest"
                ),
            )
        )
    row_keys = [
        (row.protocol_arm, row.gap_id, row.symbol, row.signal_date, row.entry_date)
        for row in accepted_rows
    ]
    if (
        row_keys != sorted(row_keys)
        or len(row_keys) != len(set(row_keys))
        or any(row.protocol_arm != selected_arm for row in accepted_rows)
    ):
        raise V30StageBError("Stage-B accepted seal rows are not unique frozen five-keys")
    stage_a_key_digest = _sha256(
        seal.stage_a_accepted_key_evidence_sha256,
        "sealed Stage-A accepted key/evidence digest",
    )
    stage_a_cohort_digest = _sha256(
        seal.stage_a_accepted_cohort_sha256,
        "sealed Stage-A accepted cohort digest",
    )
    if stage_a_key_digest != _accepted_key_evidence_sha256(
        accepted_rows
    ) or stage_a_cohort_digest != _accepted_cohort_sha256(selected_arm, accepted_rows):
        raise V30StageBError("Stage-A accepted seal digests do not recompute")
    outcome_digests: list[str] = []
    for row, outcome, stored_digest in zip(
        accepted_rows, seal.outcomes, seal.outcome_evidence_sha256, strict=True
    ):
        if not isinstance(outcome, StageBOutcome):
            raise V30StageBError("Stage-B replay seal has an untyped outcome")
        if (
            outcome.protocol_arm,
            outcome.gap_id,
            outcome.symbol,
            outcome.signal_date,
            outcome.entry_date,
        ) != (
            row.protocol_arm,
            row.gap_id,
            row.symbol,
            row.signal_date,
            row.entry_date,
        ):
            raise V30StageBError("Stage-B outcome crosses its sealed accepted five-key")
        recomputed = _validate_outcome_evidence_digest(outcome)
        if _sha256(stored_digest, "stored outcome evidence digest") != recomputed:
            raise V30StageBError("Stage-B outcome digest vector does not conserve")
        outcome_digests.append(recomputed)
    terminal_digest = _sha256(seal.terminal_ledger_sha256, "terminal ledger digest")
    if terminal_digest != _terminal_ledger_sha256(seal.outcomes):
        raise V30StageBError("terminal ledger digest does not recompute")
    replay_payload = _stage_b_replay_seal_payload(
        selected_arm=selected_arm,
        accepted_count=accepted,
        stage_a_accepted_cohort_sha256=stage_a_cohort_digest,
        stage_a_accepted_key_evidence_sha256=stage_a_key_digest,
        accepted_rows=accepted_rows,
        outcome_evidence_sha256=outcome_digests,
        terminal_ledger_sha256=terminal_digest,
    )
    if _sha256(seal.replay_seal_sha256, "Stage-B replay seal digest") != normalized_json_sha256(
        replay_payload
    ):
        raise V30StageBError("Stage-B replay seal digest does not recompute")
    return seal.outcomes


def summarize_terminal_cohort(seal: StageBReplaySeal) -> dict[str, Any]:
    outcomes = _validate_stage_b_replay_seal(seal)
    accepted = seal.accepted_count
    counts = {
        "target_exits": 0,
        "failure_exits": 0,
        "time_exits": 0,
        "pre_action_risk_exits": 0,
        "unexited": 0,
        "unknown": 0,
    }
    seen: set[tuple[str, str, str, pd.Timestamp, pd.Timestamp]] = set()
    complete: list[StageBOutcome] = []
    for outcome in outcomes:
        identity = (
            outcome.protocol_arm,
            outcome.gap_id,
            outcome.symbol,
            outcome.signal_date,
            outcome.entry_date,
        )
        if identity in seen:
            raise V30StageBError("terminal outcome identity is duplicate")
        seen.add(identity)
        if (
            outcome.execution_proxy_name != EXECUTION_PROXY_NAME
            or outcome.real_fill_claimed is not False
        ):
            raise V30StageBError("terminal row is not the frozen conservative proxy channel")
        _positive_tick(outcome.entry_tick, "terminal entry tick")
        _exact_int(
            outcome.entry_calendar_index,
            "terminal entry calendar index",
            minimum=0,
        )
        if outcome.outcome_status == COMPLETE_OUTCOME:
            _validate_outcome_evidence_digest(outcome)
            if outcome.exit_reason == "A67_TARGET":
                counts["target_exits"] += 1
            elif outcome.exit_reason == "PIVOT_FAILURE":
                counts["failure_exits"] += 1
            elif outcome.exit_reason == "H10_TIME":
                counts["time_exits"] += 1
            elif outcome.exit_reason == "PRE_ACTION_RISK":
                counts["pre_action_risk_exits"] += 1
            else:
                raise V30StageBError("complete outcome lacks one frozen exit reason")
            if (
                outcome.net_return is None
                or outcome.holding_sessions is None
                or outcome.exit_calendar_index is None
                or outcome.exit_date is None
                or outcome.exit_at is None
                or outcome.exit_tick is None
                or outcome.blocker is not None
                or outcome.exit_calendar_index - outcome.entry_calendar_index
                != outcome.holding_sessions
            ):
                raise V30StageBError("complete outcome ledger is incomplete")
            exit_index = _exact_int(
                outcome.exit_calendar_index,
                "terminal exit calendar index",
                minimum=0,
            )
            holding = _exact_int(
                outcome.holding_sessions,
                "terminal holding sessions",
                minimum=1,
            )
            exit_date = _date(outcome.exit_date, "terminal exit date")
            exit_at = _local_timestamp(outcome.exit_at, "terminal exit proof timestamp")
            if exit_at.normalize() != exit_date or exit_at.time() not in EXPECTED_BAR_END_TIMES:
                raise V30StageBError("terminal exit proof timestamp is not a frozen minute")
            if holding > TERMINAL_OFFSET or exit_index - outcome.entry_calendar_index != holding:
                raise V30StageBError("complete outcome holding-session ledger is invalid")
            _validate_complete_outcome_ledger(outcome)
            complete.append(outcome)
        elif outcome.outcome_status == UNEXITED_OUTCOME:
            if any(
                value is not None
                for value in (
                    outcome.exit_reason,
                    outcome.exit_date,
                    outcome.exit_at,
                    outcome.exit_calendar_index,
                    outcome.exit_tick,
                    outcome.holding_sessions,
                    outcome.gross_coordinate_cash_cents_per_original_share,
                    outcome.entry_cash_out_cents,
                    outcome.exit_cash_in_cents,
                    outcome.cash_distribution_performance_credit_cents,
                    outcome.net_return_numerator,
                    outcome.net_return_denominator,
                    outcome.net_return,
                )
            ):
                raise V30StageBError("unexited outcome contains forbidden terminal values")
            if outcome.blocker != "COMPLETE_H30_SCAN_WITHOUT_PROXY_EXIT":
                raise V30StageBError("unexited outcome blocker identity drift")
            counts["unexited"] += 1
        elif outcome.outcome_status in {UNKNOWN_OUTCOME, NOT_OPENED_OUTCOME}:
            if any(
                value is not None
                for value in (
                    outcome.exit_reason,
                    outcome.exit_date,
                    outcome.exit_at,
                    outcome.exit_calendar_index,
                    outcome.exit_tick,
                    outcome.holding_sessions,
                    outcome.gross_coordinate_cash_cents_per_original_share,
                    outcome.entry_cash_out_cents,
                    outcome.exit_cash_in_cents,
                    outcome.cash_distribution_performance_credit_cents,
                    outcome.net_return_numerator,
                    outcome.net_return_denominator,
                    outcome.net_return,
                )
            ):
                raise V30StageBError("unknown outcome contains forbidden terminal values")
            blocker = _exact_string(outcome.blocker, "unknown outcome blocker")
            if (
                outcome.outcome_status == NOT_OPENED_OUTCOME
                and blocker != "PRIOR_ACCEPTED_ROW_WAS_UNRESOLVED"
            ):
                raise V30StageBError("not-opened outcome blocker identity drift")
            counts["unknown"] += 1
        else:
            raise V30StageBError("terminal outcome status is not frozen")
    if sum(counts.values()) != accepted:
        raise V30StageBError("terminal conservation identity failed")
    exited = len(complete)
    result: dict[str, Any] = {
        "accepted": accepted,
        "exited": exited,
        **counts,
        "terminal_conservation": True,
        "publishable": False,
        "development_pass": False,
        "mean_net_return": None,
        "median_net_return": None,
        "mean_holding_sessions": None,
        "median_holding_sessions": None,
        "signals_per_year": None,
        "win_count": 0,
        "zero_return_count": 0,
        "loss_count": 0,
        "win_rate": None,
        "annual": None,
        "blocker": None,
        "evidence_grade": "PIT-B_CONDITIONAL_RESEARCH_ONLY",
        "return_scope": "PRICE_ONLY_NET_OF_FROZEN_TRADING_COSTS_ZERO_DISTRIBUTION_CREDIT",
        "real_fill_claimed": False,
        "terminal_ledger_sha256": seal.terminal_ledger_sha256,
        "stage_b_replay_seal_sha256": seal.replay_seal_sha256,
    }
    if counts["unknown"] or counts["unexited"] or exited != accepted:
        result["blocker"] = "UNRESOLVED_TERMINAL_COHORT"
        return result
    if any(item.signal_date.year not in DEVELOPMENT_YEARS for item in complete):
        raise V30StageBError("complete outcome escaped the frozen development years")
    returns = [_validate_complete_outcome_ledger(item) for item in complete]
    holdings = [
        Fraction(item.holding_sessions, 1)
        for item in complete
        if item.holding_sessions is not None
    ]
    mean_return = _mean_fraction(returns)
    median_return = _median_fraction(returns)
    mean_holding = _mean_fraction(holdings)
    median_holding = _median_fraction(holdings)
    total_wins = sum(value > 0 for value in returns)
    total_zeros = sum(value == 0 for value in returns)
    total_losses = sum(value < 0 for value in returns)
    annual: dict[str, dict[str, Any]] = {}
    for year in range(2018, 2022):
        subset = [item for item in complete if item.signal_date.year == year]
        subset_returns = [_validate_complete_outcome_ledger(item) for item in subset]
        subset_holdings = [
            Fraction(item.holding_sessions, 1)
            for item in subset
            if item.holding_sessions is not None
        ]
        wins = sum(value > 0 for value in subset_returns)
        zeros = sum(value == 0 for value in subset_returns)
        losses = sum(value < 0 for value in subset_returns)
        exit_reason_counts = {
            reason: sum(item.exit_reason == reason for item in subset)
            for reason in sorted(EXIT_REASONS)
        }
        annual[str(year)] = {
            "accepted": len(subset),
            "exited": len(subset),
            "signals": len(subset),
            "win_count": wins,
            "zero_return_count": zeros,
            "loss_count": losses,
            "mean_net_return": (
                _fraction_display_text(_mean_fraction(subset_returns)) if subset else None
            ),
            "median_net_return": (
                _fraction_display_text(_median_fraction(subset_returns)) if subset else None
            ),
            "win_rate": _fraction_display_text(Fraction(wins, len(subset))) if subset else None,
            "mean_holding_sessions": (
                _fraction_display_text(_mean_fraction(subset_holdings))
                if subset
                else None
            ),
            "median_holding_sessions": (
                _fraction_display_text(_median_fraction(subset_holdings))
                if subset
                else None
            ),
            "exit_reasons": exit_reason_counts,
        }
    result.update(
        {
            "publishable": True,
            "mean_net_return": _fraction_display_text(mean_return),
            "median_net_return": _fraction_display_text(median_return),
            "mean_holding_sessions": _fraction_display_text(mean_holding),
            "median_holding_sessions": _fraction_display_text(median_holding),
            "signals_per_year": _fraction_display_text(Fraction(accepted, 4)),
            "win_count": total_wins,
            "zero_return_count": total_zeros,
            "loss_count": total_losses,
            "win_rate": _fraction_display_text(Fraction(total_wins, exited)),
            "annual": annual,
            "development_pass": (
                accepted >= MIN_ACCEPTED
                and mean_return >= MIN_MEAN_RETURN_FRACTION
                and mean_holding < MAX_MEAN_HOLDING_EXCLUSIVE_FRACTION
            ),
        }
    )
    if not result["development_pass"]:
        result["blocker"] = "COMPLETE_DEVELOPMENT_GATE_MISS"
    return result


def normalized_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def metadata_check() -> dict[str, Any]:
    """Expose the frozen code contract without touching any research row."""
    return {
        "experiment": EXPERIMENT,
        "protocol_version": PROTOCOL_VERSION,
        "mode": "METADATA_CHECK_ONLY",
        "development_interval": [str(DEVELOPMENT_START.date()), str(DEVELOPMENT_END.date())],
        "daily_projection": "H0:H29_ONLY_NO_OPEN_HIGH_LOW_LIMIT_OR_ST",
        "exact_projection_whitelists": {
            "accepted": list(ACCEPTED_ENTRY_FIELDS),
            "daily": list(DAILY_PROJECTION_FIELDS),
            "minute_scaffold": list(MINUTE_SCAFFOLD_FIELDS),
            "action": list(ACTION_PROJECTION_FIELDS),
        },
        "minute_grid": [clock.strftime("%H:%M") for clock in EXPECTED_BAR_END_TIMES],
        "minute_grid_count": len(EXPECTED_BAR_END_TIMES),
        "minute_source": QD004_SOURCE,
        "qd010_canonical_symbol_reference_sha256": (QD010_CANONICAL_SYMBOL_REFERENCE_SHA256),
        "strict_prefix": True,
        "target_sessions": "H1:H10",
        "failure_close_sessions": "H1:H9",
        "time_order_first_session": "H11",
        "forced_roll_terminal": "H30",
        "target_limit": "max(ceil(A67_raw_cents-cumulative_cash),D5)",
        "target_fill": (
            "first_valid_bar_with_source_OHLCVA_conditional_strictly_above_limit_"
            "share_lower_bound_ge_10000;exit_at_frozen_limit"
        ),
        "forced_fill": (
            "first_valid_bar_with_source_OHLCVA_conditional_strictly_above_D5_"
            "share_lower_bound_ge_10000;exit_at_frozen_limit"
        ),
        "possible_partial": (
            "positive_volume_and_high_ge_limit_without_10000_share_lower_bound;"
            "continue_same_DAY_only;"
            "later_full_proxy_resolves_at_later_time;unresolved_at_close_is_UNKNOWN"
        ),
        "execution_quantity_bound": {
            "name": "source_OHLCVA_conditional_lower_bound",
            "geometry": (
                "if low>limit:S=V;elif high<=limit:S=0;else:"
                "S=max(0,ceil((A_floor_cents-limit*V)/(high-limit)))"
            ),
            "amount_raw": "Decimal.from_float(source_amount_CNY)*100_exact_power_of_ten",
            "amount_conservative_integer_cents": "floor(raw_amount_cents)",
            "outward_direction": "SELL_FLOOR",
            "digest_binds": (
                "raw_decimal_cents,conservative_integer_cents,outward_adjustment,"
                "direction,limit,OHLC,volume,S,classification"
            ),
        },
        "execution_interpretation": (
            "counterfactual_conservative_1m_source_OHLCVA_conditional_proxy;"
            "not_L2_queue_truth;not_observed_or_true_exchange_amount"
        ),
        "order_size_shares": ORDER_SIZE_SHARES,
        "entry_minimum_bar_volume_shares": ENTRY_MIN_PROXY_VOLUME_SHARES,
        "exit_minimum_bar_volume_shares": MIN_PROXY_VOLUME_SHARES,
        "maximum_exit_participation_fraction": "0.01",
        "execution_proxy_name": EXECUTION_PROXY_NAME,
        "real_fill_claimed": False,
        "action_clock": {
            "exact_timestamp": "causal at exact known_at=available_at instant",
            "daily_order_decision_cutoff": "09:14:59 Asia/Shanghai",
            "daily_order_submitted_at": "09:15:00 Asia/Shanghai",
            "09:30_bar_role": "opening_auction_result_not_continuous_auction",
            "day_only_target_cancel": "from first market open on-or-after source date",
            "day_only_risk_order": "not earlier than following market session",
            "same_day_cash_without_preopen_proof": "UNKNOWN",
            "raw_snapshot_or_vintage_identity_required": True,
            "event_raw_event_revision_and_row_hash_each_unique": True,
        },
        "accepted_entry_revalidated": {
            "arms": sorted(SIGNAL_ARMS),
            "cap25_rank": "1:25",
            "hard_valid": True,
            "entry_order_acknowledgement": "09:35:01",
            "entry_proxy_interval": "09:36:00:09:37:00",
            "strict_entry_below_frozen_buy_limit": True,
            "a67_net_headroom_recomputed": ">=0.04",
        },
        "minute_zero_match": "UNKNOWN_ON_FIRST_REACHED_EXPECTED_BAR",
        "exchange_reference_ledger": (
            "H0_close_then_cash_adjust_once_each_effective_session;"
            "traded_day_updates_to_close;suspension_carries_computed_reference"
        ),
        "physical_zero_volume_day": (
            "VALID_NO_FILL_ONLY_WHEN_ALL_241_ROWS_ARE_FLAT_AT_COMPUTED_REFERENCE_"
            "AND_CY033_IS_EXACT_SUSPENSION"
        ),
        "holding_sessions": "exit_calendar_index-entry_calendar_index",
        "terminal_conservation": ("accepted=target+failure+time+pre_action_risk+unexited+unknown"),
        "fees_each_side": str(PER_SIDE_FEE),
        "gross_coordinate_cash_scope": (
            "gross_pre_tax_cash_per_original_entry_share_for_coordinate_adjustment_only"
        ),
        "cash_distribution_performance_credit_cents": "0",
        "net_return_formula": "(exit_cash_in_cents-entry_cash_out_cents)/entry_cash_out_cents",
        "evidence_grade": "PIT-B_CONDITIONAL_RESEARCH_ONLY",
        "market_data_rows_opened": 0,
        "post_2021_rows_opened": 0,
        "data_loader_present": False,
        "publisher_present": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("metadata-check",), default="metadata-check")
    parser.parse_args()
    print(json.dumps(metadata_check(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
