#!/usr/bin/env python3
"""Pure, outcome-blind Stage-A primitives for causal demand recapture V30.

This file deliberately has no Stage-A data reader or publisher.  The only CLI
mode is ``metadata-check``.  A future, separately frozen builder may use these
primitives after it binds exact source assets and an authorization.

Chronology is explicit: all candidate, CAP25, K50 and QD010 decisions are sealed
at 09:14:59.  A 100-share DAY limit order is submitted at 09:15:00 and joins the
opening auction.  The only entry evidence is an exact, lazy, ordered scan of the
eight completed QD-004 minute keys 09:30..09:37.  A fully valid bar with at
least 10,000 shares and a high strictly below the frozen limit is the frozen
one-percent counterfactual fill proxy; it is not an L2 or broker-fill claim.
Earlier ambiguous touches remain open until such a later full proxy resolves
them.  A terminal unresolved touch, or missing/duplicate/invalid evidence,
fails closed.  H0 CY033 state is opened only after a terminal minute result and
can corroborate, but never create, either a proxy fill or a no-fill.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-CAUSAL-DEMAND-RECAPTURE-V30"
PROTOCOL_VERSION = "V30_OUTCOME_BLIND_STAGE_A_IMPLEMENTATION_DRAFT_V1"
DEVELOPMENT_START = pd.Timestamp("2018-01-01")
DEVELOPMENT_END = pd.Timestamp("2021-12-31")

FROZEN_V29R4_RUNNER = OS_ROOT / (
    "scripts/run_ashare_true_gap_below_l_first_investable_reclaim_v29r4.py"
)
FROZEN_V29R4_RUNNER_SHA256 = (
    "085870fb8cb03dda25848a70fb2de6550b9289f6e4296da00923a50a7bee0ebe"
)

AMOUNT_ARM = "V30_AMOUNT_1X_TO_2X_CAP25"
SHARE_VOLUME_FALLBACK_ARM = "V30_SHARE_VOLUME_1X_AMOUNT_LE_2X_CAP25"
SIGNAL_ARMS = (AMOUNT_ARM, SHARE_VOLUME_FALLBACK_ARM)
CAP_PER_SIGNAL_DATE = 25
MIN_CAUSAL_ACCEPTED = 201
MAX_POSITIONS = 50
SAMPLE_CAP_SEMANTICS = "CONCURRENT_SAMPLE_CAP_NOT_CAPITAL_CLAIM"

MIN_GAP_AGE = 10
MAX_GAP_AGE = 14
MIN_PRIOR_PEAK_TO_GAP = 20
PRIOR_WINDOW = 20
MIN_MAX_DEPTH = Decimal("0.10")
MIN_CURRENT_DEPTH = Decimal("0.05")
MIN_RECOVERY_FROM_LOW20 = Decimal("0.03")
MIN_LOW20_AGE = 1
MAX_LOW20_AGE = 10
MAX_PRIOR_ONE_PRICE_LIMIT_DOWNS = 1
MAX_SIGNAL_AMOUNT_TO_PRIOR_MEDIAN = Decimal("2")
MIN_VOLUME_SIGNAL_AMOUNT_TO_PRIOR_MEDIAN = Decimal("1")

TARGET_ACTIVE_HORIZON = 10
TIME_EXIT_OFFSETS = (11, 12, 13)
INITIAL_TIME_EXIT_ATTEMPT_END = 13
CAPACITY_AUDIT_HORIZON = 30
TARGET_FRACTION = Decimal("0.67")
PER_SIDE_COST = Decimal("0.002")
MIN_EXACT_TARGET_NET = Decimal("0.04")

ENTRY_CUTOFF_TIME = "09:14:59"
ORDER_SUBMITTED_TIME = "09:15:00"
ENTRY_SCAN_BAR_END_TIMES = (
    "09:30",
    "09:31",
    "09:32",
    "09:33",
    "09:34",
    "09:35",
    "09:36",
    "09:37",
)
ORDER_CANCEL_TIME = "09:37:01"
ENTRY_EXECUTION_EVIDENCE_LABEL = "PREOPEN_RESTING_LIMIT_STRICT_PRICE_CROSS_PROXY"
TERMINAL_AUDIT_TIME = "15:00:00"
UNIVERSAL_MINIMUM_UP_CAP = Decimal("1.05")
ORDER_SIZE_SHARES = 100
MIN_PROXY_VOLUME_SHARES = 10_000
ORDER_TIME_IN_FORCE = "DAY"
QD004_REQUIRED_SOURCE = "day_parquet_none"
QD004_CANONICAL_SOURCE_SHA256 = (
    "b1a6c88996e5015a23544d63398b49d5dd269d50c71567dc03344fbb83e69e8e"
)

QD004_DEVELOPMENT_PARTITION_SHA256 = {
    2018: "83fbb3e0fda4b278e1072836a9695b7d9a6dfa396a07248e40f85db0d2ba0812",
    2019: "b31fccebb8f2319099b412233263dbc99f965a091b0995e62d275997b411130c",
    2020: "67d6b958f2b4113750df8f1a98d6e48d93ef00e04cab0fbf0cf0661b1600d45e",
    2021: "efd3b1a4bf60c47ba36b83792c97fc08d600aa8cde58014ff44e3c005eebac61",
}
CY033_ASSET_MANIFEST_SHA256 = (
    "95905858212f9a79a4f99ba8746fe47c66619ea5f4815eeeb4f0ead195219977"
)
CY033_REGISTERED_SNAPSHOT_ID = "PITB-CURRENT-6EED78D779E22BDF5B61"
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
FROZEN_CALENDAR_ROW_COUNT = 973
FROZEN_CALENDAR_MIN_DATE = pd.Timestamp("2018-01-02")
FROZEN_CALENDAR_MAX_DATE = pd.Timestamp("2021-12-31")
FROZEN_CALENDAR_CANONICAL_SHA256 = (
    "bf5da2b2e1436758b59086d3a6cb29952ed9b3385309c7e445876f8b18490e8a"
)
FROZEN_CALENDAR_NEWLINE_SHA256 = (
    "220988be72d36581dfbf279730116ae34427df21f192fca2cd7972f1c67b3676"
)
FROZEN_CALENDAR_DERIVATION = "CY033_DISTINCT_TRADE_DATE_SORT_ASC_ZERO_BASED"

QD010_SUPPORTED_ACTION_KINDS = ("CASH_ONLY", "RISK_SHARE", "RISK_RIGHTS")
QD010_UNSUPPORTED_ACTION_KIND = "UNSUPPORTED"
QD010_SOURCE_VALUE_EXACT = "SOURCE_VALUE_EXACT"
QD010_SOURCE_NOT_APPLICABLE_NEUTRAL_0 = "SOURCE_NOT_APPLICABLE_NEUTRAL_0"
QD010_SOURCE_NOT_APPLICABLE_NEUTRAL_1 = "SOURCE_NOT_APPLICABLE_NEUTRAL_1"
PREORDER_ORDER_FROZEN = "PREORDER_ORDER_FROZEN"
PREORDER_RESOLVED_NO_ORDER = "PREORDER_RESOLVED_NO_ORDER"
PREORDER_UNKNOWN = "PREORDER_UNKNOWN"

# The builder must first project these fourteen physical Parquet columns, then
# append only the exact query scaffold.  A zero-match scaffold carries None in
# every physical column and in every physical-row-only scaffold field.
QD004_PHYSICAL_SOURCE_COLUMNS = (
    "qmt_code",
    "symbol",
    "exchange",
    "period",
    "adjust",
    "trade_date",
    "bar_end_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "source",
)
QD004_DERIVED_QUERY_SCAFFOLD_COLUMNS = (
    "protocol_arm",
    "gap_id",
    "candidate_symbol",
    "expected_trade_date",
    "expected_bar_end_time",
    "available_at",
    "bar_valid",
    "source_snapshot_id",
    "query_partition_sha256",
    "query_locator",
    "physical_source_locator",
    "source_match_count",
    "permitted_projection_sha256",
)
QD004_ENTRY_SCAN_INPUT_COLUMNS = (
    *QD004_PHYSICAL_SOURCE_COLUMNS,
    *QD004_DERIVED_QUERY_SCAFFOLD_COLUMNS,
)
QD004_ENTRY_KEY_SCAFFOLD_COLUMNS = QD004_ENTRY_SCAN_INPUT_COLUMNS
CY033_H0_SOURCE_PROJECTION_COLUMNS = (
    "trade_date",
    "decision_at",
    "decision_timezone",
    "symbol",
    "volume",
    "amount",
    "trade_status",
    "is_st",
    "state_source",
    "float_effective_date",
    "float_announced_date",
    "float_available_date",
    "circulating_shares",
    "float_source",
    "corporate_action_count",
    "corporate_action_ids",
    "corporate_action_source",
    "corporate_action_available_date",
    "corporate_action_blocking",
    "corporate_action_problems",
    "share_multiplier",
    "cash_per_share",
    "rights_ratio",
    "rights_price",
    "market_rule_id",
    "market_rule_source",
    "bar_valid",
    "trading_state_valid",
    "industry_valid",
    "float_valid",
    "corporate_action_valid",
    "market_valid",
    "market_rule_valid",
    "historical_identity_valid",
    "hard_valid",
    "invalid_reasons",
    "current_day_data_tradable",
    "available_at",
    "snapshot_id",
    "pit_grade",
    "strict_archive_ready",
    "daily_snapshot_id",
    "trading_state_snapshot_id",
    "industry_snapshot_id",
    "float_snapshot_id",
    "corporate_action_snapshot_id",
    "market_snapshot_id",
)
CY033_H0_DERIVED_SCAFFOLD_COLUMNS = (
    "protocol_arm",
    "gap_id",
    "expected_trade_date",
    "source_match_count",
    "query_locator",
    "query_partition_sha256",
    "physical_source_locator",
    "source_snapshot_id",
    "permitted_projection_sha256",
)
CY033_H0_AUDIT_INPUT_COLUMNS = (
    *CY033_H0_SOURCE_PROJECTION_COLUMNS,
    *CY033_H0_DERIVED_SCAFFOLD_COLUMNS,
)
QD010_ACTION_INPUT_COLUMNS = (
    "raw_symbol",
    "canonical_symbol",
    "event_id",
    "source_row_hash",
    "permitted_projection_sha256",
    "source_table",
    "source_file_sha256",
    "source_locator",
    "snapshot_id",
    "vintage_id",
    "known_at",
    "available_at",
    "known_at_precision",
    "effective_date",
    "action_kind",
    "source_terms_complete",
    "cash_per_share_gross_source_is_null",
    "cash_per_share_gross_source_float64_bits",
    "cash_per_share_gross",
    "cash_per_share_gross_normalization_status",
    "share_multiplier_source_is_null",
    "share_multiplier_source_float64_bits",
    "share_multiplier",
    "share_multiplier_normalization_status",
    "rights_ratio_source_is_null",
    "rights_ratio_source_float64_bits",
    "rights_ratio",
    "rights_ratio_normalization_status",
    "rights_price_source_is_null",
    "rights_price_source_float64_bits",
    "rights_price",
    "rights_price_normalization_status",
)
PARENT_GAP_INPUT_COLUMNS = (
    "gap_id",
    "symbol",
    "board",
    "gap_date",
    "pre_peak_to_gap_sessions",
    "L",
    "coordinate_factor",
)
SHARE_VOLUME_FALLBACK_DAILY_SIGNAL_INPUT_COLUMNS = (
    "trade_date",
    "decision_at",
    "decision_timezone",
    "symbol",
    "open",
    "open_source_float64_bits",
    "high",
    "high_source_float64_bits",
    "low",
    "low_source_float64_bits",
    "close",
    "close_source_float64_bits",
    "preclose",
    "preclose_source_float64_bits",
    "volume",
    "volume_source_float64_bits",
    "amount",
    "amount_source_float64_bits",
    "trade_status",
    "is_st",
    "up_limit_price",
    "up_limit_price_source_float64_bits",
    "down_limit_price",
    "down_limit_price_source_float64_bits",
    "current_day_data_tradable",
    "industry",
    "corporate_action_count",
    "corporate_action_blocking",
    "share_multiplier",
    "share_multiplier_source_float64_bits",
    "cash_per_share",
    "cash_per_share_source_float64_bits",
    "bar_valid",
    "trading_state_valid",
    "industry_valid",
    "corporate_action_valid",
    "market_rule_valid",
    "hard_valid",
    "available_at",
    "snapshot_id",
    "daily_snapshot_id",
    "trading_state_snapshot_id",
    "industry_snapshot_id",
    "corporate_action_snapshot_id",
    "permitted_projection_sha256",
)
AMOUNT_ARM_DAILY_SIGNAL_INPUT_COLUMNS = tuple(
    column
    for column in SHARE_VOLUME_FALLBACK_DAILY_SIGNAL_INPUT_COLUMNS
    if column not in {"volume", "volume_source_float64_bits"}
)
SIGNAL_STATE_INPUT_COLUMNS = tuple(
    column
    for column in AMOUNT_ARM_DAILY_SIGNAL_INPUT_COLUMNS
    if column
    not in {
        "open",
        "open_source_float64_bits",
        "high",
        "high_source_float64_bits",
        "low",
        "low_source_float64_bits",
        "preclose",
        "preclose_source_float64_bits",
        "amount",
        "amount_source_float64_bits",
        "industry",
        "up_limit_price",
        "up_limit_price_source_float64_bits",
        "down_limit_price",
        "down_limit_price_source_float64_bits",
    }
)
MARKET_CALENDAR_INPUT_COLUMNS = ("trade_date", "calendar_index")
FORBIDDEN_ENTRY_DAY_DERIVED_FIELDS = (
    "CY006_ENTRY_DAY_STATE",
    "CY006_ENTRY_DAY_HARD_VALID",
    "CY006_ENTRY_DAY_LIMITS",
    "CY008_ENTRY_DAY_STATE",
    "CY008_ENTRY_DAY_HARD_VALID",
    "CY008_ENTRY_DAY_LIMITS",
    "QD004_ENTRY_DAY_DERIVED_STATE",
)

SIGNAL_OUTPUT_COLUMNS = (
    "protocol_arm",
    "gap_id",
    "symbol",
    "board",
    "gap_date",
    "signal_date",
    "signal_time",
    "signal_decision_at",
    "signal_available_at",
    "signal_snapshot_id",
    "signal_daily_snapshot_id",
    "signal_corporate_action_snapshot_id",
    "signal_trading_state_snapshot_id",
    "signal_industry_snapshot_id",
    "coordinate_factor",
    "L",
    "raw_l_tick",
    "legacy_l_over_factor_decimal",
    "legacy_l_over_factor_matches_raw_l_tick",
    "reclaimed_pivot_tick",
    "reclaimed_pivot_source_trade_date",
    "reclaimed_pivot_snapshot_id",
    "reclaimed_pivot_daily_snapshot_id",
    "signal_industry",
    "rebound_from_post_gap_low_over_l",
    "rebound_tick_numerator",
    "rebound_tick_denominator",
    "signal_raw_close_tick",
    "signal_raw_close_source_float64_bits",
    "signal_daily_permitted_projection_sha256",
    "signal_raw_amount_exact",
    "signal_raw_amount_source_float64_bits",
    "prior20_median_amount_exact",
    "signal_amount_to_prior20_median",
    "signal_raw_share_volume_exact",
    "signal_raw_share_volume_float64_bits",
    "prior20_raw_share_volume_median_numerator",
    "prior20_raw_share_volume_median_denominator",
    "signal_share_volume_ge_prior20_median",
    "cap25_rank",
)
ADMIN_OUTPUT_COLUMNS = (
    "protocol_arm",
    "gap_id",
    "symbol",
    "signal_date",
    "signal_calendar_index",
    "entry_date",
    "h10_date",
    "h11_date",
    "h12_date",
    "h13_date",
    "h30_capacity_audit_date",
    "market_calendar_sha256",
    "candidate_key_sha256",
    "admin_eligible",
    "admin_status",
)
PREORDER_LEDGER_OUTPUT_COLUMNS = (
    "protocol_arm",
    "gap_id",
    "symbol",
    "signal_date",
    "entry_date",
    "preorder_status",
    "preorder_reason",
    "candidate_key_sha256",
    "market_calendar_sha256",
    "action_scope_digest",
    "frozen_order_digest",
)
PREALLOCATION_OUTPUT_COLUMNS = (
    "protocol_arm",
    "gap_id",
    "symbol",
    "signal_date",
    "entry_date",
    "h30_capacity_audit_date",
    "cap25_rank",
    "preorder_status",
    "occupied_sample_slots_before",
    "preallocation_status",
    "sample_cap_semantics",
    "candidate_key_sha256",
    "market_calendar_sha256",
    "action_scope_digest",
    "frozen_order_digest",
    "order_decision_at",
    "order_submitted_at",
)
PREALLOCATION_INPUT_COLUMNS = (
    "protocol_arm",
    "gap_id",
    "symbol",
    "signal_date",
    "entry_date",
    "h30_capacity_audit_date",
    "cap25_rank",
    "preorder_status",
    "candidate_key_sha256",
    "market_calendar_sha256",
    "action_scope_digest",
    "frozen_order_digest",
    "order_decision_at",
    "order_submitted_at",
)
ENTRY_EVIDENCE_OUTPUT_COLUMNS = (
    "protocol_arm",
    "gap_id",
    "symbol",
    "signal_date",
    "entry_date",
    "order_decision_at",
    "order_submitted_at",
    "candidate_key_sha256",
    "market_calendar_sha256",
    "action_scope_digest",
    "frozen_order_digest",
    "entry_execution_evidence_label",
    "opened_bar_end_times",
    "opened_row_sha256",
    "opened_bar_transitions",
    "opened_provable_strict_cross_volume_shares",
    "opened_row_count",
    "last_opened_bar_end_time",
    "proof_bar_end_time",
    "proof_row_sha256",
    "proof_low_tick",
    "proof_high_tick",
    "proof_volume_exact",
    "proof_volume_source_float64_bits",
    "proof_amount_exact",
    "proof_amount_exact_cents",
    "proof_amount_conservative_upper_cents",
    "proof_amount_outward_adjustment_cents",
    "proof_amount_source_float64_bits",
    "proof_provable_strict_cross_volume_shares",
    "entry_scan_digest",
    "settlement_digest",
    "fill_tick",
    "cancel_at",
    "order_size_shares",
    "time_in_force",
    "qd010_action_status",
    "signal_raw_close_tick",
    "universal_maximum_down_floor_tick",
    "universal_minimum_up_cap_tick",
    "max_headroom_buy_tick",
    "frozen_buy_limit_tick",
    "raw_l_tick",
    "reclaimed_pivot_tick",
    "h30_capacity_audit_date",
    "entry_hard_valid",
    "entry_status",
    "entry_evidence_accepted",
    "counterfactual_proxy_fill_proved",
    "h0_audit_status",
    "h0_decision_at",
    "h0_available_at",
    "h0_trade_status",
    "h0_current_day_data_tradable",
    "h0_is_st",
    "h0_state_source",
    "h0_daily_volume_exact",
    "h0_daily_volume_float64_bits",
    "h0_daily_amount_exact",
    "h0_daily_amount_float64_bits",
    "h0_float_effective_date",
    "h0_float_announced_date",
    "h0_float_available_date",
    "h0_circulating_shares_exact",
    "h0_circulating_shares_float64_bits",
    "h0_float_source",
    "h0_corporate_action_count",
    "h0_corporate_action_ids",
    "h0_corporate_action_source",
    "h0_corporate_action_available_date",
    "h0_corporate_action_blocking",
    "h0_corporate_action_problems",
    "h0_share_multiplier_exact",
    "h0_share_multiplier_float64_bits",
    "h0_cash_per_share_exact",
    "h0_cash_per_share_float64_bits",
    "h0_rights_ratio_exact",
    "h0_rights_ratio_float64_bits",
    "h0_rights_price_exact",
    "h0_rights_price_float64_bits",
    "h0_market_rule_id",
    "h0_market_rule_source",
    "h0_bar_valid",
    "h0_trading_state_valid",
    "h0_industry_valid",
    "h0_float_valid",
    "h0_corporate_action_valid",
    "h0_market_valid",
    "h0_market_rule_valid",
    "h0_historical_identity_valid",
    "h0_hard_valid",
    "h0_invalid_reasons",
    "h0_snapshot_id",
    "h0_pit_grade",
    "h0_strict_archive_ready",
    "h0_daily_snapshot_id",
    "h0_trading_state_snapshot_id",
    "h0_industry_snapshot_id",
    "h0_float_snapshot_id",
    "h0_corporate_action_snapshot_id",
    "h0_market_snapshot_id",
    "h0_query_partition_sha256",
    "h0_query_locator",
    "h0_physical_source_locator",
    "h0_source_snapshot_id",
    "h0_source_match_count",
    "h0_permitted_projection_sha256",
    "h0_audit_digest",
)
SETTLED_ORDER_OUTPUT_COLUMNS = tuple(
    dict.fromkeys(
        (
            *PREALLOCATION_OUTPUT_COLUMNS,
            *ENTRY_EVIDENCE_OUTPUT_COLUMNS,
            "entry_settlement_status",
            "entry_evidence_opened",
        )
    )
)
ARM_ACCOUNTING_OUTPUT_COLUMNS = (
    "protocol_arm",
    "complete",
    "candidate_total",
    "admin_censored",
    "preorder_resolved_no_order",
    "preorder_unknown",
    "preallocation_rejected",
    "preallocated_no_fill",
    "k50_accepted",
    "settlement_unknown",
    "sample_cap_semantics",
)
CAP25_LEDGER_OUTPUT_COLUMNS = (
    "protocol_arm",
    "gap_id",
    "symbol",
    "signal_date",
    "cap25_status",
    "cap25_rank",
)
ACCEPTED_COHORT_OUTPUT_COLUMNS = (
    "protocol_arm",
    "gap_id",
    "symbol",
    "signal_date",
    "entry_date",
    "candidate_key_sha256",
    "market_calendar_sha256",
    "action_scope_digest",
    "frozen_order_digest",
    "entry_scan_digest",
    "settlement_digest",
    "entry_tick",
    "signal_raw_close_tick",
    "universal_maximum_down_floor_tick",
    "universal_minimum_up_cap_tick",
    "raw_l_tick",
    "reclaimed_pivot_tick",
    "h30_capacity_audit_date",
    "h0_snapshot_id",
    "h0_query_partition_sha256",
    "h0_source_snapshot_id",
    "h0_permitted_projection_sha256",
    "h0_audit_digest",
)
ARM_CANDIDATE_IDENTITY_COLUMNS = (
    "protocol_arm",
    "gap_id",
    "symbol",
    "signal_date",
    "entry_date",
)
SIGNAL_DAILY_LINEAGE_OUTPUT_COLUMNS = (
    "protocol_arm",
    "gap_id",
    "symbol",
    "source_trade_date",
    "lineage_roles",
    "decision_at",
    "available_at",
    "snapshot_id",
    "daily_snapshot_id",
    "trading_state_snapshot_id",
    "industry_snapshot_id",
    "corporate_action_snapshot_id",
    "permitted_projection_sha256",
    "role_gap_day_raw_l_authority",
    "role_gap_identity",
    "role_post_gap_path",
    "role_rolling20",
    "role_prior20_limit",
    "role_prior20_amount",
    "role_prior20_share_volume",
    "role_reclaimed_pivot",
    "role_signal_bar",
)

FORBIDDEN_OUTPUT_FIELD_TOKENS = (
    "return",
    "pnl",
    "profit",
    "win_rate",
    "exit_price",
    "outcome",
)


class V30StageAError(RuntimeError):
    """Fail closed on unknown, chronology, source or conservation state."""


def sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise V30StageAError(f"hash target is not one regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_frozen_v29r4_hash() -> str:
    """Verify the parent identity without importing or executing its module."""
    if sha256(FROZEN_V29R4_RUNNER) != FROZEN_V29R4_RUNNER_SHA256:
        raise V30StageAError("frozen V29R4 runner hash drift")
    return FROZEN_V29R4_RUNNER_SHA256


verify_frozen_v29r4_hash()


def _nonempty(value: Any) -> bool:
    try:
        return bool(pd.notna(value) and str(value).strip())
    except (TypeError, ValueError):
        return False


def _decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, (bool, np.bool_, float, np.floating)) or value is None:
        raise V30StageAError(f"{label} is not a finite decimal")
    if not isinstance(value, (str, Decimal, int, np.integer)):
        raise V30StageAError(f"{label} is not a typed exact decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise V30StageAError(f"{label} is not Decimal-compatible") from exc
    if not result.is_finite():
        raise V30StageAError(f"{label} is not finite")
    canonical = format(result, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    if canonical in {"-0", ""}:
        canonical = "0"
    if not re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?", canonical):
        raise V30StageAError(f"{label} cannot be canonically encoded")
    if isinstance(value, str) and value != canonical:
        raise V30StageAError(f"{label} is not the unique canonical decimal string")
    return Decimal(canonical)


def _canonical_decimal_text(value: Any, label: str) -> str:
    return format(_decimal(value, label), "f")


def _float64_from_le_bits(value: Any, label: str) -> np.float64:
    """Decode exactly one finite source DOUBLE from canonical LE hex bits."""
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[0-9a-f]{16}", value)
    ):
        raise V30StageAError(f"{label} is not canonical float64 LE bits")
    decoded = np.float64(struct.unpack("<d", bytes.fromhex(value))[0])
    if not np.isfinite(decoded):
        raise V30StageAError(f"{label} decodes to non-finite float64")
    if struct.pack("<d", float(decoded)).hex() != value:
        raise V30StageAError(f"{label} float64 bits do not round-trip")
    return decoded


def _positive_decimal(value: Any, label: str) -> Decimal:
    result = _decimal(value, label)
    if result <= 0:
        raise V30StageAError(f"{label} is not positive")
    return result


def _nonnegative_decimal(value: Any, label: str) -> Decimal:
    result = _decimal(value, label)
    if result < 0:
        raise V30StageAError(f"{label} is negative")
    return result


def canonical_daily_cent_tick(value: Any, label: str = "daily price") -> np.int64:
    """Decode a daily price only when it is already an exact whole cent."""
    cents = _positive_decimal(value, label) * 100
    integral = cents.to_integral_value()
    if cents != integral:
        raise V30StageAError(f"{label} is not an exact daily 0.01-CNY tick")
    tick = int(integral)
    if tick <= 0 or tick > np.iinfo(np.int64).max:
        raise V30StageAError(f"{label} cent tick is outside int64")
    return np.int64(tick)


def _daily_source_price_projection(
    value: Any, raw_bits: Any, label: str
) -> dict[str, Any]:
    """Bind one builder-normalized cent value to the exact CY033 DOUBLE bits."""
    tick = canonical_daily_cent_tick(value, label)
    source = _float64_from_le_bits(raw_bits, f"{label} source bits")
    expected = np.float64(int(tick) / 100.0)
    if struct.pack("<d", float(source)) != struct.pack("<d", float(expected)):
        raise V30StageAError(
            f"{label} normalized cent does not reproduce source float64 bits"
        )
    return {
        "typed_decimal_cny": format(_positive_decimal(value, label), "f"),
        "int64_cent_tick": int(tick),
        "source_float64_bits_le_hex": str(raw_bits),
    }


def _daily_source_price_tick(
    row: Mapping[str, Any], field: str, label: str
) -> np.int64:
    projection = _daily_source_price_projection(
        _required(row, field, label),
        _required(row, f"{field}_source_float64_bits", label),
        f"{label} {field}",
    )
    return np.int64(projection["int64_cent_tick"])


def _source_float64_decimal_projection(
    value: Any,
    raw_bits: Any,
    label: str,
    *,
    nonnegative: bool = True,
    integral: bool = False,
) -> dict[str, Any]:
    """Bind a canonical typed decimal to its frozen source DOUBLE exactly."""
    typed = _decimal(value, label)
    source = _float64_from_le_bits(raw_bits, f"{label} source bits")
    exact = Decimal.from_float(float(source))
    if typed != exact:
        raise V30StageAError(f"{label} typed decimal differs from source float64 bits")
    if nonnegative and exact < 0:
        raise V30StageAError(f"{label} is negative")
    if integral and exact != exact.to_integral_value():
        raise V30StageAError(f"{label} is not exact integer source units")
    if integral and exact > 2**53:
        raise V30StageAError(f"{label} exceeds exact source float integer range")
    return {
        "typed_exact_decimal": format(typed, "f"),
        "source_float64_bits_le_hex": str(raw_bits),
    }


def _daily_schema_for_arm(protocol_arm: Any) -> tuple[str, ...]:
    arm = _require_nonempty_exact_string(protocol_arm, "CY033 daily protocol arm")
    if arm == AMOUNT_ARM:
        return AMOUNT_ARM_DAILY_SIGNAL_INPUT_COLUMNS
    if arm == SHARE_VOLUME_FALLBACK_ARM:
        return SHARE_VOLUME_FALLBACK_DAILY_SIGNAL_INPUT_COLUMNS
    raise V30StageAError("CY033 daily protocol arm is not frozen")


def cy033_daily_permitted_projection_sha256(
    row: Mapping[str, Any], *, protocol_arm: Any
) -> str:
    """Recompute one exact signal-search CY033 row projection.

    The preferred amount arm has no share-volume keys at this boundary.  This
    function therefore cannot accidentally decode or hash the fallback feature.
    """
    arm = _require_nonempty_exact_string(protocol_arm, "CY033 daily protocol arm")
    schema = _daily_schema_for_arm(arm)
    _require_exact_projection(row, schema, f"{arm} CY033 daily row")
    date = _normalized_date(row["trade_date"], "CY033 daily trade_date")
    decision_at = _local_naive_timestamp(row["decision_at"], "CY033 decision_at")
    available_at = _local_naive_timestamp(row["available_at"], "CY033 available_at")
    expected_close = pd.Timestamp(f"{date.date()} 15:00:00")
    if (
        decision_at != expected_close
        or available_at != expected_close
        or row["decision_timezone"] != "Asia/Shanghai"
    ):
        raise V30StageAError("CY033 daily completed-bar clock is not exact")
    symbol = canonical_candidate_symbol(row["symbol"])
    prices = {
        name: _daily_source_price_projection(
            row[name], row[f"{name}_source_float64_bits"], f"CY033 {name}"
        )
        for name in (
            "open",
            "high",
            "low",
            "close",
            "preclose",
            "up_limit_price",
            "down_limit_price",
        )
    }
    ticks = {name: int(value["int64_cent_tick"]) for name, value in prices.items()}
    if (
        ticks["high"] < max(ticks["open"], ticks["close"])
        or ticks["low"] > min(ticks["open"], ticks["close"])
        or ticks["low"] > ticks["high"]
    ):
        raise V30StageAError("CY033 daily OHLC geometry is invalid")
    amount = _source_float64_decimal_projection(
        row["amount"], row["amount_source_float64_bits"], "CY033 amount"
    )
    volume: dict[str, Any] | None = None
    if arm == SHARE_VOLUME_FALLBACK_ARM:
        volume = _source_float64_decimal_projection(
            row["volume"],
            row["volume_source_float64_bits"],
            "CY033 raw share volume",
            integral=True,
        )
    action_terms = {
        name: _source_float64_decimal_projection(
            row[name], row[f"{name}_source_float64_bits"], f"CY033 {name}"
        )
        for name in ("share_multiplier", "cash_per_share")
    }
    trade_status = row["trade_status"]
    action_count = row["corporate_action_count"]
    if (
        isinstance(trade_status, (bool, np.bool_))
        or not isinstance(trade_status, (int, np.integer))
        or int(trade_status) not in (0, 1)
        or isinstance(action_count, (bool, np.bool_))
        or not isinstance(action_count, (int, np.integer))
        or int(action_count) < 0
    ):
        raise V30StageAError("CY033 daily state/action integers are invalid")
    booleans = {}
    for name in (
        "is_st",
        "current_day_data_tradable",
        "corporate_action_blocking",
        "bar_valid",
        "trading_state_valid",
        "industry_valid",
        "corporate_action_valid",
        "market_rule_valid",
        "hard_valid",
    ):
        booleans[name] = _strict_bool_value(row[name], f"CY033 {name}")
    snapshots = {
        name: _require_nonempty_exact_string(row[name], f"CY033 {name}")
        for name in (
            "snapshot_id",
            "daily_snapshot_id",
            "trading_state_snapshot_id",
            "industry_snapshot_id",
            "corporate_action_snapshot_id",
        )
    }
    payload = {
        "protocol_arm": arm,
        "source_projection_exact_order": list(schema[:-1]),
        "trade_date": date.strftime("%Y-%m-%d"),
        "decision_at": decision_at.isoformat(),
        "decision_timezone": "Asia/Shanghai",
        "symbol": symbol,
        "prices": prices,
        "volume": volume,
        "amount": amount,
        "trade_status": int(trade_status),
        "industry": _require_nonempty_exact_string(row["industry"], "CY033 industry"),
        "corporate_action_count": int(action_count),
        "action_terms": action_terms,
        "booleans": booleans,
        "available_at": available_at.isoformat(),
        "snapshots": snapshots,
        "projection": "V30_CY033_SIGNAL_DAILY_PERMITTED_ROW_V1",
    }
    return _canonical_json_sha256(payload)


def _float32_value_and_bits(value: Any, label: str) -> tuple[np.float32, int]:
    """Require a real float32 value or its exact float32-to-float widening."""
    if isinstance(value, (bool, np.bool_)) or not isinstance(
        value, (float, np.float64)
    ):
        raise V30StageAError(f"{label} is not float32")
    try:
        f32 = np.float32(value)
        widened = float(f32)
        original = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise V30StageAError(f"{label} is not float32-compatible") from exc
    if not math.isfinite(widened) or widened <= 0:
        raise V30StageAError(f"{label} is not positive finite float32")
    if original != widened:
        raise V30StageAError(
            f"{label} is not an exact widening of the source float32 bits"
        )
    bits = int(np.asarray([f32], dtype="<f4").view("<u4")[0])
    return f32, bits


def _float64_value_and_bits(value: Any, label: str) -> tuple[np.float64, str]:
    """Return one finite source float64 and its little-endian raw bits."""
    if isinstance(value, (bool, np.bool_)) or not isinstance(
        value, (float, np.float64)
    ):
        raise V30StageAError(f"{label} is not a source float64")
    canonical = np.float64(value)
    if not np.isfinite(canonical):
        raise V30StageAError(f"{label} is not finite")
    return canonical, struct.pack("<d", float(canonical)).hex()


def _float64_exact_decimal(value: np.float64) -> Decimal:
    return Decimal.from_float(float(value))


def qd004_float32_cent_tick(
    value: Any, label: str = "QD004 price"
) -> np.int64:
    """Decode a QD-004 float32 cent by exact IEEE-754 bit reproduction.

    No epsilon decides validity.  A candidate cent is accepted only when
    encoding that cent as float32 reproduces the source's exact 32 bits, and
    the mapping is unique across the adjacent cent ticks.
    """
    source, source_bits = _float32_value_and_bits(value, label)
    exact_scaled = Decimal.from_float(float(source)) * 100
    candidate = int(exact_scaled.to_integral_value(rounding=ROUND_HALF_UP))
    matches: list[int] = []
    for tick in range(max(1, candidate - 1), candidate + 2):
        encoded = np.float32(tick / 100.0)
        bits = int(np.asarray([encoded], dtype="<f4").view("<u4")[0])
        if bits == source_bits:
            matches.append(tick)
    if matches != [candidate]:
        raise V30StageAError(f"{label} is not one unique float32-encoded cent")
    return np.int64(candidate)


def _qd004_price_projection(value: Any, label: str) -> dict[str, Any]:
    source, source_bits = _float64_value_and_bits(value, label)
    _, bits = _float32_value_and_bits(source, label)
    tick = qd004_float32_cent_tick(value, label)
    return {
        "float64_bits_le_hex": source_bits,
        "float32_bits_le_hex": f"{bits:08x}",
        "tick": int(tick),
    }


def _canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _required(row: Mapping[str, Any], key: str, label: str) -> Any:
    try:
        return row[key]
    except (KeyError, TypeError) as exc:
        raise V30StageAError(f"{label} lacks required field {key}") from exc


def _require_exact_projection(
    row: Mapping[str, Any], expected_columns: Sequence[str], label: str
) -> None:
    """Reject a row that was decoded with either missing or unauthorized fields."""
    try:
        actual = tuple(str(key) for key in row.keys())
    except (AttributeError, TypeError) as exc:
        raise V30StageAError(f"{label} is not a keyed exact projection") from exc
    expected = tuple(expected_columns)
    if len(actual) != len(set(actual)) or actual != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        raise V30StageAError(
            f"{label} exact projection failed; missing={missing}, extra={extra}, "
            f"order_drift={not missing and not extra and actual != expected}"
        )


def _require_exact_frame_projection(
    frame: pd.DataFrame, expected_columns: Sequence[str], label: str
) -> None:
    actual = tuple(str(column) for column in frame.columns)
    expected = tuple(expected_columns)
    if len(actual) != len(set(actual)) or actual != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        raise V30StageAError(
            f"{label} exact projection failed; missing={missing}, extra={extra}, "
            f"order_drift={not missing and not extra and actual != expected}"
        )


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise V30StageAError(f"{label} is not a lowercase SHA-256")
    return value


def _require_nonempty_exact_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise V30StageAError(f"{label} is not an exact nonempty string")
    return value


def _require_int64_tick(value: Any, label: str, *, positive: bool = True) -> np.int64:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise V30StageAError(f"{label} is not an exact integer tick")
    integer = int(value)
    minimum = 1 if positive else 0
    if integer < minimum or integer > np.iinfo(np.int64).max:
        raise V30StageAError(f"{label} is outside int64 tick range")
    return np.int64(integer)


def _local_naive_timestamp(value: Any, label: str) -> pd.Timestamp:
    try:
        result = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise V30StageAError(f"{label} is not a timestamp") from exc
    if pd.isna(result):
        raise V30StageAError(f"{label} is missing")
    if result.tzinfo is not None:
        raise V30StageAError(f"{label} must be exact local-naive time")
    return result


def _normalized_date(value: Any, label: str) -> pd.Timestamp:
    result = _local_naive_timestamp(value, label)
    if result != result.normalize():
        raise V30StageAError(f"{label} must be a date at midnight")
    return result


def canonicalize_qd010_symbol(raw_symbol: Any) -> str:
    """Implement the bound ``full_market.py::_canonical_symbol_sql`` semantics."""
    if not isinstance(raw_symbol, str) or not raw_symbol:
        raise V30StageAError("QD010 symbol is empty")
    text = raw_symbol.upper()
    if text.endswith((".SH", ".SZ", ".BJ")):
        return text
    if len(raw_symbol) != 6:
        raise V30StageAError("QD010 symbol shape is invalid")
    if raw_symbol[:2] == "92" or raw_symbol[:1] in {"4", "8"}:
        return f"{raw_symbol}.BJ"
    if raw_symbol[:1] in {"5", "6", "9"}:
        return f"{raw_symbol}.SH"
    return f"{raw_symbol}.SZ"


def canonical_candidate_symbol(value: Any) -> str:
    """Require one exact six-digit Main/ChiNext ``CODE.EXCHANGE`` identity."""
    text = _require_nonempty_exact_string(value, "candidate symbol")
    if text != text.upper() or len(text) != 9 or text[6] != ".":
        raise V30StageAError("candidate symbol is not exact CODE.EXCHANGE")
    code, exchange = text[:6], text[7:]
    if not code.isdigit() or exchange not in {"SH", "SZ"}:
        raise V30StageAError("candidate symbol is outside exact SH/SZ scope")
    inferred = canonicalize_qd010_symbol(code)
    if inferred != text:
        raise V30StageAError("candidate symbol conflicts with bound exchange semantics")
    return text


@dataclass(frozen=True)
class CandidateKey:
    protocol_arm: str
    gap_id: str
    symbol: str
    signal_date: pd.Timestamp
    entry_date: pd.Timestamp
    sha256: str


def make_candidate_key(
    *,
    protocol_arm: Any,
    gap_id: Any,
    symbol: Any,
    signal_date: Any,
    entry_date: Any,
) -> CandidateKey:
    arm = _require_nonempty_exact_string(protocol_arm, "candidate protocol arm")
    if arm not in SIGNAL_ARMS:
        raise V30StageAError("candidate protocol arm is not frozen")
    identifier = _require_nonempty_exact_string(gap_id, "candidate gap_id")
    canonical_symbol = canonical_candidate_symbol(symbol)
    signal = _normalized_date(signal_date, "candidate signal_date")
    entry = _normalized_date(entry_date, "candidate entry_date")
    if signal < DEVELOPMENT_START or signal > DEVELOPMENT_END or entry <= signal:
        raise V30StageAError("candidate date ordering is invalid")
    payload = {
        "entry_date": entry.strftime("%Y-%m-%d"),
        "gap_id": identifier,
        "protocol_arm": arm,
        "signal_date": signal.strftime("%Y-%m-%d"),
        "symbol": canonical_symbol,
    }
    return CandidateKey(
        protocol_arm=arm,
        gap_id=identifier,
        symbol=canonical_symbol,
        signal_date=signal,
        entry_date=entry,
        sha256=_canonical_json_sha256(payload),
    )


def validate_candidate_key(value: Any, label: str = "candidate key") -> CandidateKey:
    if not isinstance(value, CandidateKey):
        raise V30StageAError(f"{label} is not a CandidateKey")
    rebuilt = make_candidate_key(
        protocol_arm=value.protocol_arm,
        gap_id=value.gap_id,
        symbol=value.symbol,
        signal_date=value.signal_date,
        entry_date=value.entry_date,
    )
    if value != rebuilt:
        raise V30StageAError(f"{label} digest or fields are inconsistent")
    return value


def strict_row_lineage_valid(
    row: Mapping[str, Any], asof: Any, *, protocol_arm: Any
) -> bool:
    """Return true only for exact-boolean, fully identified PIT daily lineage."""
    try:
        supplied_projection = _require_sha256(
            _required(row, "permitted_projection_sha256", "daily lineage"),
            "daily permitted projection SHA",
        )
        if supplied_projection != cy033_daily_permitted_projection_sha256(
            row, protocol_arm=protocol_arm
        ):
            return False
        observed = _local_naive_timestamp(asof, "lineage asof")
        for field in (
            "bar_valid",
            "trading_state_valid",
            "industry_valid",
            "corporate_action_valid",
            "market_rule_valid",
            "hard_valid",
        ):
            value = _required(row, field, "daily lineage")
            if not isinstance(value, (bool, np.bool_)) or not bool(value):
                return False
        if str(_required(row, "decision_timezone", "daily lineage")) != "Asia/Shanghai":
            return False
        for field in (
            "snapshot_id",
            "daily_snapshot_id",
            "trading_state_snapshot_id",
            "industry_snapshot_id",
            "corporate_action_snapshot_id",
        ):
            if not _nonempty(_required(row, field, "daily lineage")):
                return False
        available = _local_naive_timestamp(
            _required(row, "available_at", "daily lineage"), "daily available_at"
        )
        decision = _local_naive_timestamp(
            _required(row, "decision_at", "daily lineage"), "daily decision_at"
        )
        return bool(available <= decision <= observed and available <= observed)
    except V30StageAError:
        return False


def strict_action_free_status(row: Mapping[str, Any], label: str) -> bool:
    """Return exact action-free state; malformed ledgers remain unknown."""
    blocking = _required(row, "corporate_action_blocking", label)
    if not isinstance(blocking, (bool, np.bool_)):
        raise V30StageAError(f"{label} corporate_action_blocking is not boolean")
    count = _nonnegative_decimal(
        _required(row, "corporate_action_count", label), f"{label} action count"
    )
    multiplier = _positive_decimal(
        _source_float64_decimal_projection(
            _required(row, "share_multiplier", label),
            _required(row, "share_multiplier_source_float64_bits", label),
            f"{label} multiplier",
        )["typed_exact_decimal"],
        f"{label} multiplier",
    )
    cash = _nonnegative_decimal(
        _source_float64_decimal_projection(
            _required(row, "cash_per_share", label),
            _required(row, "cash_per_share_source_float64_bits", label),
            f"{label} cash",
        )["typed_exact_decimal"],
        f"{label} cash",
    )
    if count != count.to_integral_value():
        raise V30StageAError(f"{label} action count is not an integer")
    if count == 0:
        if bool(blocking) or multiplier != 1 or cash != 0:
            raise V30StageAError(f"{label} zero-count action ledger conflicts with terms")
        return True
    return False


def require_strict_action_free(row: Mapping[str, Any], label: str) -> None:
    """Require action-free when a caller's semantics specifically demand it."""
    if not strict_action_free_status(row, label):
        raise V30StageAError(f"{label} contains a known corporate action")


def _qd004_query_scaffold_projection(
    row: Mapping[str, Any],
    *,
    key: CandidateKey,
    expected_end: pd.Timestamp,
    expected_match_count: int,
    label: str,
) -> dict[str, Any]:
    """Validate query identity without pretending that an absent row is physical."""
    key = validate_candidate_key(key)
    partition = QD004_DEVELOPMENT_PARTITION_SHA256.get(int(key.entry_date.year))
    if partition is None:
        raise V30StageAError("QD004 entry partition is outside development")
    expected_end = _local_naive_timestamp(expected_end, "expected QD004 bar end")
    expected_query, expected_physical = _expected_qd004_locators(
        key, expected_end, partition
    )
    match_count = _required(row, "source_match_count", label)
    if (
        isinstance(match_count, (bool, np.bool_))
        or not isinstance(match_count, (int, np.integer))
        or int(match_count) != expected_match_count
    ):
        raise V30StageAError("QD004 source match count is not exact 0/1")
    protocol_arm = _require_nonempty_exact_string(
        row["protocol_arm"], f"{label} protocol_arm"
    )
    gap_id = _require_nonempty_exact_string(row["gap_id"], f"{label} gap_id")
    candidate_symbol = canonical_candidate_symbol(row["candidate_symbol"])
    expected_trade_date = _normalized_date(
        row["expected_trade_date"], f"{label} expected_trade_date"
    )
    actual_expected_end = _local_naive_timestamp(
        row["expected_bar_end_time"], f"{label} expected_bar_end_time"
    )
    partition_sha256 = _require_sha256(
        row["query_partition_sha256"], f"{label} query_partition_sha256"
    )
    query_locator = _require_nonempty_exact_string(
        row["query_locator"], f"{label} query_locator"
    )
    if (
        protocol_arm != key.protocol_arm
        or gap_id != key.gap_id
        or candidate_symbol != key.symbol
        or expected_trade_date != key.entry_date
        or actual_expected_end != expected_end
        or partition_sha256 != partition
        or query_locator != expected_query
    ):
        raise V30StageAError("QD004 query scaffold is not bound to its candidate key")
    physical_locator = row["physical_source_locator"]
    source_snapshot_id = row["source_snapshot_id"]
    available_at = row["available_at"]
    bar_valid = row["bar_valid"]
    projection_sha256 = row["permitted_projection_sha256"]
    if expected_match_count == 0:
        if any(row[name] is not None for name in QD004_PHYSICAL_SOURCE_COLUMNS) or any(
            value is not None
            for value in (
                physical_locator,
                source_snapshot_id,
                available_at,
                bar_valid,
                projection_sha256,
            )
        ):
            raise V30StageAError("zero-match QD004 scaffold fabricates physical fields")
        normalized_available_at: str | None = None
        normalized_bar_valid: bool | None = None
        normalized_physical: str | None = None
        normalized_snapshot: str | None = None
    else:
        normalized_physical = _require_nonempty_exact_string(
            physical_locator, f"{label} physical_source_locator"
        )
        normalized_snapshot = _require_nonempty_exact_string(
            source_snapshot_id, f"{label} source_snapshot_id"
        )
        normalized_available = _local_naive_timestamp(
            available_at, f"{label} available_at"
        )
        normalized_bar_valid = _strict_bool_value(bar_valid, f"{label} bar_valid")
        expected_snapshot = f"QD004:{QD004_CANONICAL_SOURCE_SHA256}:{partition}"
        if (
            normalized_physical != expected_physical
            or normalized_snapshot != expected_snapshot
            or normalized_available != expected_end
            or not normalized_bar_valid
        ):
            raise V30StageAError("QD004 physical scaffold lineage/clock is invalid")
        _require_sha256(projection_sha256, f"{label} permitted projection SHA-256")
        normalized_available_at = normalized_available.isoformat()
    return {
        "protocol_arm": protocol_arm,
        "gap_id": gap_id,
        "candidate_symbol": candidate_symbol,
        "expected_trade_date": expected_trade_date.strftime("%Y-%m-%d"),
        "expected_bar_end_time": actual_expected_end.isoformat(),
        "available_at": normalized_available_at,
        "bar_valid": normalized_bar_valid,
        "source_snapshot_id": normalized_snapshot,
        "query_partition_sha256": partition_sha256,
        "query_locator": query_locator,
        "physical_source_locator": normalized_physical,
        "source_match_count": expected_match_count,
    }


def _expected_qd004_locators(
    key: CandidateKey, bar_end_time: pd.Timestamp, partition_sha256: str
) -> tuple[str, str]:
    stamp = bar_end_time.strftime("%Y-%m-%dT%H:%M:%S")
    query = f"QD004_QUERY_V1:{key.symbol}:{stamp}"
    physical = f"QD004_ROW_V1:{partition_sha256}:{key.symbol}:{stamp}:0"
    return query, physical


@dataclass(frozen=True)
class FrozenEntryOrder:
    candidate_key: CandidateKey
    order_decision_at: pd.Timestamp
    order_submitted_at: pd.Timestamp
    market_calendar_sha256: str
    signal_raw_close_tick: np.int64
    signal_raw_close_source_float64_bits: str
    signal_daily_permitted_projection_sha256: str
    universal_maximum_down_floor_tick: np.int64
    raw_l_tick: np.int64
    universal_minimum_up_cap_tick: np.int64
    max_headroom_buy_tick: np.int64 | None
    frozen_buy_limit_tick: np.int64 | None
    entry_hard_valid: bool
    entry_status: str
    qd010_action_status: str
    action_scope_digest: str
    reclaimed_pivot_tick: np.int64
    h30_capacity_audit_date: pd.Timestamp
    order_size_shares: int
    time_in_force: str
    frozen_order_digest: str


@dataclass(frozen=True)
class QD004EntryBar:
    candidate_key: CandidateKey
    bar_end_time: pd.Timestamp
    available_at: pd.Timestamp
    open_tick: np.int64
    high_tick: np.int64
    low_tick: np.int64
    close_tick: np.int64
    open_source_float64_bits: str
    high_source_float64_bits: str
    low_source_float64_bits: str
    close_source_float64_bits: str
    volume_exact: str
    volume_source_float64_bits: str
    amount_exact: str
    amount_source_float64_bits: str
    amount_conservative_upper_cents: int
    amount_outward_adjustment_cents: str
    provable_strict_cross_volume_shares: int
    bar_transition: str
    source_snapshot_id: str
    query_partition_sha256: str
    query_locator: str
    physical_source_locator: str
    row_sha256: str
    prior_prefix_digest: str
    prefix_digest: str


@dataclass(frozen=True)
class QD004AbsentKey:
    candidate_key: CandidateKey
    bar_end_time: pd.Timestamp
    query_partition_sha256: str
    query_locator: str
    row_sha256: str


@dataclass(frozen=True)
class CY033H0TerminalAudit:
    candidate_key: CandidateKey
    decision_at: pd.Timestamp
    available_at: pd.Timestamp
    trade_status: int
    current_day_data_tradable: bool
    is_st: bool
    state_source: str
    daily_volume_exact: str
    daily_volume_float64_bits: str
    daily_amount_exact: str
    daily_amount_float64_bits: str
    float_effective_date: pd.Timestamp
    float_announced_date: pd.Timestamp
    float_available_date: pd.Timestamp
    circulating_shares_exact: str
    circulating_shares_float64_bits: str
    float_source: str
    corporate_action_count: int
    corporate_action_ids: str | None
    corporate_action_source: str
    corporate_action_available_date: pd.Timestamp
    corporate_action_blocking: bool
    corporate_action_problems: str | None
    share_multiplier_exact: str
    share_multiplier_float64_bits: str
    cash_per_share_exact: str
    cash_per_share_float64_bits: str
    rights_ratio_exact: str | None
    rights_ratio_float64_bits: str
    rights_price_exact: str | None
    rights_price_float64_bits: str
    market_rule_id: str
    market_rule_source: str
    bar_valid: bool
    trading_state_valid: bool
    industry_valid: bool
    float_valid: bool
    corporate_action_valid: bool
    market_valid: bool
    market_rule_valid: bool
    historical_identity_valid: bool
    hard_valid: bool
    invalid_reasons: str
    snapshot_id: str
    pit_grade: str
    strict_archive_ready: bool
    daily_snapshot_id: str
    trading_state_snapshot_id: str
    industry_snapshot_id: str
    float_snapshot_id: str
    corporate_action_snapshot_id: str
    market_snapshot_id: str
    query_partition_sha256: str
    query_locator: str
    physical_source_locator: str
    source_snapshot_id: str
    source_match_count: int
    permitted_projection_sha256: str
    audit_status: str
    audit_digest: str


@dataclass(frozen=True)
class QD010ScopeProof:
    candidate_key: CandidateKey
    observation_at: pd.Timestamp
    effective_start_exclusive: pd.Timestamp
    effective_end_inclusive: pd.Timestamp
    projected_row_count: int
    projected_source_row_hashes: tuple[str, ...]
    permitted_projection_sha256s: tuple[str, ...]
    source_row_counts: tuple[tuple[str, int], ...]
    query_complete: bool
    source_bindings: tuple[tuple[str, str], ...]
    scope_digest: str


@dataclass(frozen=True)
class EntrySettlementEvidence:
    candidate_key: CandidateKey
    order: FrozenEntryOrder
    opened_bars: tuple[QD004EntryBar, ...]
    opened_key_sha256: tuple[str, ...]
    h0_audit: CY033H0TerminalAudit
    entry_scan_digest: str
    entry_hard_valid: bool
    entry_status: str
    entry_evidence_accepted: bool
    fill_tick: np.int64 | None
    cancel_at: pd.Timestamp | None
    counterfactual_proxy_fill_proved: bool
    settlement_digest: str


@dataclass(frozen=True)
class SealedAcceptedCohort:
    protocol_arm: str
    rows: pd.DataFrame
    accepted_count: int
    cohort_sha256: str


@dataclass(frozen=True)
class SealedSettlementLedger:
    protocol_arm: str
    rows: pd.DataFrame
    terminal_evidence: tuple[EntrySettlementEvidence, ...]
    row_count: int
    settlement_ledger_sha256: str


@dataclass(frozen=True)
class CAP25Result:
    protocol_arm: str
    selected: pd.DataFrame
    ledger: pd.DataFrame


@dataclass(frozen=True)
class LazyArmEvidenceAudit:
    protocol_arm: str
    status: str
    reader_call_count: int
    materialized_row_count: int
    unlock_amount_accepted_count: int | None
    audit_sha256: str


def provable_strict_cross_volume_shares(
    *,
    volume_shares: Any,
    amount_cny_exact: Any,
    low_tick: Any,
    high_tick: Any,
    buy_limit_tick: Any,
) -> int:
    """Exact OHLCVA lower bound on shares proved to have traded below a bid.

    In the mixed case, minimizing below-limit shares puts every such share at
    ``L`` and every remaining share at the lowest non-crossing tick ``P``.
    Therefore ``A >= B*L + (V-B)*P`` in integer cents and the lower bound is
    ``ceil((P*V-A)/(P-L))``.  No observed input is clipped or repaired.
    """
    if isinstance(volume_shares, (bool, np.bool_)) or not isinstance(
        volume_shares, (int, np.integer)
    ):
        raise V30StageAError("QD004 volume is not exact integer shares")
    volume = int(volume_shares)
    if volume < 0 or volume > 2**53 or volume > np.iinfo(np.int64).max:
        raise V30StageAError("QD004 volume is outside exact source-float range")
    amount_cny = _nonnegative_decimal(amount_cny_exact, "QD004 exact amount")
    low = int(_require_int64_tick(low_tick, "QD004 low tick"))
    high = int(_require_int64_tick(high_tick, "QD004 high tick"))
    limit = int(_require_int64_tick(buy_limit_tick, "QD004 buy limit tick"))
    if low > high:
        raise V30StageAError("QD004 price interval is inverted")
    amount_cents = amount_cny * 100
    minimum_amount = Decimal(low) * volume
    maximum_amount = Decimal(high) * volume
    if amount_cents < minimum_amount or amount_cents > maximum_amount:
        raise V30StageAError("QD004 amount is outside the exact OHLC-volume bounds")
    if volume == 0:
        if amount_cents != 0:
            raise V30StageAError("zero-volume QD004 bar has nonzero amount")
        return 0
    if amount_cents <= 0:
        raise V30StageAError("positive-volume QD004 bar has nonpositive amount")
    if high < limit:
        bound = volume
    elif low >= limit:
        bound = 0
    else:
        amount_upper_cents = amount_cents.to_integral_value(rounding=ROUND_CEILING)
        raw_bound = (
            Decimal(limit) * volume - amount_upper_cents
        ) / Decimal(limit - low)
        bound = max(0, int(raw_bound.to_integral_value(rounding=ROUND_CEILING)))
    if bound > volume:
        raise V30StageAError("QD004 strict-cross lower bound exceeds total volume")
    return bound


def _qd004_physical_projection(
    row: Mapping[str, Any],
    *,
    key: CandidateKey,
    expected_end: pd.Timestamp,
    query_projection: Mapping[str, Any],
    label: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    expected_code, expected_exchange = key.symbol.rsplit(".", 1)
    strings = {
        name: _require_nonempty_exact_string(row[name], f"{label} {name}")
        for name in ("qmt_code", "symbol", "exchange", "period", "adjust", "source")
    }
    trade_date = _normalized_date(row["trade_date"], f"{label} trade_date")
    bar_end_time = _local_naive_timestamp(row["bar_end_time"], f"{label} bar_end_time")
    if (
        strings["qmt_code"] != key.symbol
        or strings["symbol"] != expected_code
        or strings["exchange"] != expected_exchange
        or strings["period"] != "1m"
        or strings["adjust"] != "none"
        or strings["source"] != QD004_REQUIRED_SOURCE
        or trade_date != key.entry_date
        or bar_end_time != expected_end
    ):
        raise V30StageAError("QD004 physical row identity/source is invalid")
    prices = {
        name: _qd004_price_projection(row[name], f"{label} {name}")
        for name in ("open", "high", "low", "close")
    }
    ticks = {name: int(value["tick"]) for name, value in prices.items()}
    if (
        ticks["high"] < max(ticks["open"], ticks["close"])
        or ticks["low"] > min(ticks["open"], ticks["close"])
        or ticks["low"] > ticks["high"]
    ):
        raise V30StageAError("QD004 entry bar OHLC geometry is invalid")
    volume_source, volume_bits = _float64_value_and_bits(row["volume"], f"{label} volume")
    amount_source, amount_bits = _float64_value_and_bits(row["amount"], f"{label} amount")
    volume_exact = _float64_exact_decimal(volume_source)
    amount_exact = _float64_exact_decimal(amount_source)
    if (
        volume_source < 0
        or volume_exact != volume_exact.to_integral_value()
        or volume_exact > 2**53
        or volume_exact > np.iinfo(np.int64).max
        or amount_source < 0
        or (volume_source == 0) != (amount_source == 0)
    ):
        raise V30StageAError("QD004 source volume/amount codec is invalid")
    volume_shares = int(volume_exact)
    amount_raw_cents = amount_exact * 100
    amount_upper_cents = int(
        amount_raw_cents.to_integral_value(rounding=ROUND_CEILING)
    )
    amount_outward_adjustment = Decimal(amount_upper_cents) - amount_raw_cents
    key_limit = int(
        _require_int64_tick(
            query_projection["frozen_buy_limit_tick"], "QD004 frozen buy limit"
        )
    )
    cross_bound = provable_strict_cross_volume_shares(
        volume_shares=volume_shares,
        amount_cny_exact=amount_exact,
        low_tick=ticks["low"],
        high_tick=ticks["high"],
        buy_limit_tick=key_limit,
    )
    if volume_shares == 0:
        transition = "ZERO_VOLUME_CONTINUE"
    elif cross_bound >= MIN_PROXY_VOLUME_SHARES:
        transition = "FULL_PROXY_PROVED"
    elif ticks["low"] <= key_limit:
        transition = "POSSIBLE_PARTIAL_OR_FULL_FILL"
    else:
        transition = "SAFE_ABOVE_LIMIT_CONTINUE"
    physical_payload = {
        "qmt_code": strings["qmt_code"],
        "symbol": strings["symbol"],
        "exchange": strings["exchange"],
        "period": strings["period"],
        "adjust": strings["adjust"],
        "trade_date": trade_date.strftime("%Y-%m-%d"),
        "bar_end_time": bar_end_time.isoformat(),
        **prices,
        "volume": {
            "float64_bits_le_hex": volume_bits,
            "exact_decimal": format(volume_exact, "f"),
            "integer_shares": volume_shares,
        },
        "amount": {
            "float64_bits_le_hex": amount_bits,
            "exact_decimal_cny": format(amount_exact, "f"),
            "raw_exact_decimal_cents": format(amount_raw_cents, "f"),
            "conservative_integer_cents": amount_upper_cents,
            "outward_adjustment_cents": format(amount_outward_adjustment, "f"),
            "outward_direction": "UP_FOR_BUY_LOWER_BOUND",
        },
        "source": strings["source"],
    }
    derived_payload = {
        name: query_projection[name]
        for name in QD004_DERIVED_QUERY_SCAFFOLD_COLUMNS
        if name != "permitted_projection_sha256"
    }
    derived_payload.update(
        {
            "provable_strict_cross_volume_shares": cross_bound,
            "bar_transition": transition,
        }
    )
    payload = {
        "physical_source_projection": physical_payload,
        "derived_query_scaffold": derived_payload,
        "physical_source_exact_order": list(QD004_PHYSICAL_SOURCE_COLUMNS),
        "derived_scaffold_hashed_fields_exact_order": list(
            QD004_DERIVED_QUERY_SCAFFOLD_COLUMNS[:-1]
        ),
        "strict_cross_lower_bound_formula": (
            "H<P=>B=V;L>=P=>B=0;else "
            "B=max(0,ceil((P*V-ceil(A_raw_cents))/(P-L)))"
        ),
        "claim_scope": "source_OHLCVA_conditional_lower_bound",
        "strict_cross_exact_terms": {
            "L_tick": ticks["low"],
            "H_tick": ticks["high"],
            "P_buy_limit_tick": key_limit,
            "V_integer_shares": volume_shares,
            "A_raw_exact_decimal_cents": format(amount_raw_cents, "f"),
            "A_conservative_upper_integer_cents": amount_upper_cents,
            "A_outward_adjustment_cents": format(amount_outward_adjustment, "f"),
            "B_provable_strict_cross_shares": cross_bound,
        },
        "projection": "V30_QD004_PERMITTED_ENTRY_ROW_V2",
    }
    parsed = {
        "trade_date": trade_date,
        "bar_end_time": bar_end_time,
        "prices": prices,
        "ticks": ticks,
        "volume_exact": volume_exact,
        "volume_bits": volume_bits,
        "amount_exact": amount_exact,
        "amount_bits": amount_bits,
        "amount_upper_cents": amount_upper_cents,
        "amount_outward_adjustment": amount_outward_adjustment,
        "cross_bound": cross_bound,
        "transition": transition,
    }
    return payload, parsed


def qd004_permitted_projection_sha256(
    row: Mapping[str, Any],
    *,
    order: FrozenEntryOrder,
    expected_bar_end_time: Any,
) -> str:
    """Recompute the hit-row hash from exactly 14 physical plus derived fields."""
    order = validate_frozen_order(order)
    label = "QD004 permitted projection"
    _require_exact_projection(row, QD004_ENTRY_SCAN_INPUT_COLUMNS, label)
    if tuple(row.keys()) != QD004_ENTRY_SCAN_INPUT_COLUMNS:
        raise V30StageAError("QD004 exact projection order differs from preregistration")
    expected_end = _local_naive_timestamp(expected_bar_end_time, "expected bar end")
    query = _qd004_query_scaffold_projection(
        row,
        key=order.candidate_key,
        expected_end=expected_end,
        expected_match_count=1,
        label=label,
    )
    query["frozen_buy_limit_tick"] = int(order.frozen_buy_limit_tick)
    payload, _ = _qd004_physical_projection(
        row,
        key=order.candidate_key,
        expected_end=expected_end,
        query_projection=query,
        label=label,
    )
    return _canonical_json_sha256(payload)


def validate_qd004_entry_bar(
    row: Mapping[str, Any],
    *,
    order: FrozenEntryOrder,
    expected_bar_end_time: Any,
    prior_prefix_digest: str,
    expected_row_sha256: str | None = None,
) -> QD004EntryBar:
    """Validate one exact QD004 key and extend the immutable prefix chain."""
    order = validate_frozen_order(order)
    label = "QD004 ordered entry bar"
    _require_exact_projection(row, QD004_ENTRY_SCAN_INPUT_COLUMNS, label)
    if tuple(row.keys()) != QD004_ENTRY_SCAN_INPUT_COLUMNS:
        raise V30StageAError("QD004 exact projection order differs from preregistration")
    key = order.candidate_key
    expected_end = _local_naive_timestamp(expected_bar_end_time, "expected bar end")
    query = _qd004_query_scaffold_projection(
        row,
        key=key,
        expected_end=expected_end,
        expected_match_count=1,
        label=label,
    )
    query["frozen_buy_limit_tick"] = int(order.frozen_buy_limit_tick)
    payload, parsed = _qd004_physical_projection(
        row,
        key=key,
        expected_end=expected_end,
        query_projection=query,
        label=label,
    )
    row_sha256 = _canonical_json_sha256(payload)
    supplied_sha256 = _require_sha256(
        row["permitted_projection_sha256"], "QD004 permitted projection SHA-256"
    )
    if row_sha256 != supplied_sha256:
        raise V30StageAError("QD004 permitted projection hash mismatch")
    if expected_row_sha256 is not None and supplied_sha256 != _require_sha256(
        expected_row_sha256, "expected QD004 row SHA-256"
    ):
        raise V30StageAError("QD004 entry row hash binding failed")
    prior = _require_sha256(prior_prefix_digest, "prior entry prefix digest")
    prefix_digest = _canonical_json_sha256(
        {
            "bar_end_time": expected_end.isoformat(),
            "bar_transition": parsed["transition"],
            "candidate_key_sha256": key.sha256,
            "frozen_order_digest": order.frozen_order_digest,
            "prior_prefix_digest": prior,
            "row_sha256": row_sha256,
            "provable_strict_cross_volume_shares": parsed["cross_bound"],
            "projection": "V30_ORDERED_ENTRY_PREFIX_V2",
        }
    )
    ticks = parsed["ticks"]
    prices = parsed["prices"]
    return QD004EntryBar(
        candidate_key=key,
        bar_end_time=expected_end,
        available_at=expected_end,
        open_tick=np.int64(ticks["open"]),
        high_tick=np.int64(ticks["high"]),
        low_tick=np.int64(ticks["low"]),
        close_tick=np.int64(ticks["close"]),
        open_source_float64_bits=prices["open"]["float64_bits_le_hex"],
        high_source_float64_bits=prices["high"]["float64_bits_le_hex"],
        low_source_float64_bits=prices["low"]["float64_bits_le_hex"],
        close_source_float64_bits=prices["close"]["float64_bits_le_hex"],
        volume_exact=format(parsed["volume_exact"], "f"),
        volume_source_float64_bits=parsed["volume_bits"],
        amount_exact=format(parsed["amount_exact"], "f"),
        amount_source_float64_bits=parsed["amount_bits"],
        amount_conservative_upper_cents=parsed["amount_upper_cents"],
        amount_outward_adjustment_cents=format(
            parsed["amount_outward_adjustment"], "f"
        ),
        provable_strict_cross_volume_shares=parsed["cross_bound"],
        bar_transition=parsed["transition"],
        source_snapshot_id=str(query["source_snapshot_id"]),
        query_partition_sha256=str(query["query_partition_sha256"]),
        query_locator=str(query["query_locator"]),
        physical_source_locator=str(query["physical_source_locator"]),
        row_sha256=row_sha256,
        prior_prefix_digest=prior,
        prefix_digest=prefix_digest,
    )


def universal_minimum_up_cap_tick(signal_close_tick: Any) -> np.int64:
    tick = int(_require_int64_tick(signal_close_tick, "signal close tick"))
    cap = (Decimal(tick) * UNIVERSAL_MINIMUM_UP_CAP).to_integral_value(
        rounding=ROUND_HALF_UP
    )
    cap_int = int(cap)
    if cap_int > np.iinfo(np.int64).max:
        raise V30StageAError("universal minimum cap tick exceeds int64")
    return np.int64(cap_int)


def universal_maximum_down_floor_tick(signal_close_tick: Any) -> np.int64:
    """Return the universal D5 lower legal cent using half-up rounding."""
    close = int(_require_int64_tick(signal_close_tick, "signal close tick"))
    floor = (Decimal(close) * Decimal("0.95")).to_integral_value(
        rounding=ROUND_HALF_UP
    )
    floor_int = int(floor)
    if floor_int <= 0 or floor_int > np.iinfo(np.int64).max:
        raise V30StageAError("universal D5 floor tick exceeds int64")
    return np.int64(floor_int)


def a67_target_tick(entry_tick: Any, raw_l_tick: Any) -> np.int64:
    """Legal cent-ceiling A67 target for one hypothetical integer-cent buy."""
    entry = int(_require_int64_tick(entry_tick, "A67 entry tick"))
    boundary = int(_require_int64_tick(raw_l_tick, "A67 raw L tick"))
    if boundary <= entry:
        raise V30StageAError("A67 requires 0 < entry_tick < raw_l_tick")
    theoretical = Decimal(entry) + TARGET_FRACTION * Decimal(boundary - entry)
    target = int(theoretical.to_integral_value(rounding=ROUND_CEILING))
    if target > np.iinfo(np.int64).max:
        raise V30StageAError("A67 target tick exceeds int64")
    return np.int64(target)


def exact_target_net(entry_tick: Any, raw_l_tick: Any) -> Decimal:
    target = int(a67_target_tick(entry_tick, raw_l_tick))
    entry = int(entry_tick)
    return (
        Decimal(target) * (Decimal("1") - PER_SIDE_COST)
        / (Decimal(entry) * (Decimal("1") + PER_SIDE_COST))
        - Decimal("1")
    )


def max_buy_limit_tick_for_headroom(raw_l_tick: Any) -> np.int64 | None:
    """Solve the maximum executable buy cent before entry price is observed.

    Validity is monotone in the integer buy tick.  The binary search uses only
    ``raw_l_tick`` and frozen A67/cost/+4% constants available at 09:35.
    """
    boundary = int(_require_int64_tick(raw_l_tick, "raw L tick"))
    if boundary <= 1:
        return None

    def passes(entry: int) -> bool:
        target = int(a67_target_tick(entry, boundary))
        return bool(
            target < boundary
            and exact_target_net(entry, boundary) >= MIN_EXACT_TARGET_NET
        )

    low = 1
    high = boundary - 1
    answer = 0
    while low <= high:
        middle = (low + high) // 2
        if passes(middle):
            answer = middle
            low = middle + 1
        else:
            high = middle - 1
    if answer <= 0:
        return None
    if not passes(answer) or (
        answer + 1 < boundary and passes(answer + 1)
    ):
        raise V30StageAError("cannot solve a conserved A67 +4% buy limit")
    return np.int64(answer)


def planned_strict_buy_limit_tick(max_buy_tick: Any, u5_tick: Any) -> np.int64:
    """Freeze the executable DAY limit as ``min(A67 headroom, U5)``."""
    for value, label in ((max_buy_tick, "max buy"), (u5_tick, "U5")):
        if (
            isinstance(value, (bool, np.bool_))
            or not isinstance(value, (int, np.integer))
            or int(value) <= 0
            or int(value) > np.iinfo(np.int64).max
        ):
            raise V30StageAError(f"{label} tick is not a positive integer")
    maximum = int(max_buy_tick)
    u5 = int(u5_tick)
    planned = min(maximum, u5)
    if planned <= 0:
        raise V30StageAError("planned buy limit has no positive fill tick")
    return np.int64(planned)


def _require_exact_true(value: Any, label: str) -> None:
    if not isinstance(value, (bool, np.bool_)) or not bool(value):
        raise V30StageAError(f"{label} is unknown or false")


def validate_signal_day_state(
    state: Mapping[str, Any],
    *,
    expected_signal_date: Any,
    expected_symbol: Any,
    expected_signal_close_tick: Any,
    expected_snapshot_ids: Mapping[str, Any],
) -> tuple[np.int64, str, str]:
    """Validate completed signal-day state and its previously sealed row identity."""
    _require_exact_projection(state, SIGNAL_STATE_INPUT_COLUMNS, "signal state")
    signal_date = _normalized_date(expected_signal_date, "expected signal date")
    canonical_symbol = canonical_candidate_symbol(expected_symbol)
    raw_row_symbol = _required(state, "symbol", "signal state")
    row_symbol = canonical_candidate_symbol(raw_row_symbol)
    row_date = _normalized_date(_required(state, "trade_date", "signal state"), "signal date")
    decision_at = _local_naive_timestamp(
        _required(state, "decision_at", "signal state"), "signal decision_at"
    )
    available_at = _local_naive_timestamp(
        _required(state, "available_at", "signal state"), "signal available_at"
    )
    if (
        row_date != signal_date
        or row_symbol != canonical_symbol
        or raw_row_symbol != row_symbol
        or decision_at != pd.Timestamp(f"{signal_date.date()} 15:00:00")
        or available_at != decision_at
        or str(_required(state, "decision_timezone", "signal state"))
        != "Asia/Shanghai"
    ):
        raise V30StageAError("signal-day chronology/identity failed")
    for field in (
        "bar_valid",
        "trading_state_valid",
        "industry_valid",
        "corporate_action_valid",
        "market_rule_valid",
        "hard_valid",
        "current_day_data_tradable",
    ):
        _require_exact_true(_required(state, field, "signal state"), f"signal {field}")
    trade_status = _required(state, "trade_status", "signal state")
    if (
        isinstance(trade_status, (bool, np.bool_))
        or not isinstance(trade_status, (int, np.integer))
        or int(trade_status) != 1
        or not isinstance(_required(state, "is_st", "signal state"), (bool, np.bool_))
        or bool(_required(state, "is_st", "signal state"))
        or not isinstance(
            _required(state, "corporate_action_blocking", "signal state"),
            (bool, np.bool_),
        )
        or bool(_required(state, "corporate_action_blocking", "signal state"))
        or _decimal(
            _required(state, "corporate_action_count", "signal state"),
            "signal corporate_action_count",
        )
        != 0
        or _decimal(
            _source_float64_decimal_projection(
                _required(state, "share_multiplier", "signal state"),
                _required(
                    state,
                    "share_multiplier_source_float64_bits",
                    "signal state",
                ),
                "signal share_multiplier",
            )["typed_exact_decimal"],
            "signal share_multiplier",
        )
        != 1
        or _decimal(
            _source_float64_decimal_projection(
                _required(state, "cash_per_share", "signal state"),
                _required(
                    state,
                    "cash_per_share_source_float64_bits",
                    "signal state",
                ),
                "signal cash_per_share",
            )["typed_exact_decimal"],
            "signal cash_per_share",
        )
        != 0
    ):
        raise V30StageAError("signal-day state/action gate failed")
    for field in (
        "snapshot_id",
        "daily_snapshot_id",
        "trading_state_snapshot_id",
        "industry_snapshot_id",
        "corporate_action_snapshot_id",
        "permitted_projection_sha256",
    ):
        if not _nonempty(_required(state, field, "signal state")):
            raise V30StageAError(f"signal {field} is missing")
    allowed = {
        "snapshot_id",
        "daily_snapshot_id",
        "trading_state_snapshot_id",
        "industry_snapshot_id",
        "corporate_action_snapshot_id",
        "permitted_projection_sha256",
    }
    if set(expected_snapshot_ids) != allowed:
        raise V30StageAError("signal-day snapshot binding is not complete and exact")
    for field, expected in expected_snapshot_ids.items():
        if str(_required(state, field, "signal state")) != str(expected):
            raise V30StageAError("signal-day snapshot binding differs from frozen signal")
    close_tick = _daily_source_price_tick(state, "close", "signal-day")
    expected_tick = _require_int64_tick(
        expected_signal_close_tick, "expected frozen signal close tick"
    )
    if int(close_tick) != int(expected_tick):
        raise V30StageAError("signal-day close tick differs from frozen signal")
    close_bits = _require_nonempty_exact_string(
        state["close_source_float64_bits"], "signal close source float64 bits"
    )
    projection_sha256 = _require_sha256(
        state["permitted_projection_sha256"],
        "signal daily permitted projection SHA",
    )
    return close_tick, close_bits, projection_sha256


def _qd010_normalized_term_projection(
    row: Mapping[str, Any], *, name: str, source_table: str, label: str
) -> tuple[Decimal, dict[str, Any]]:
    """Bind one physical QD010 DOUBLE or its table-specific N/A neutral."""
    source_is_null = _strict_bool_value(
        row[f"{name}_source_is_null"], f"{label} {name} source_is_null"
    )
    raw_bits = row[f"{name}_source_float64_bits"]
    typed = _decimal(row[name], f"{label} {name} typed decimal")
    status = _require_nonempty_exact_string(
        row[f"{name}_normalization_status"], f"{label} {name} normalization status"
    )
    neutral_by_table = {
        "distributions": {
            "rights_ratio": (
                Decimal(0),
                QD010_SOURCE_NOT_APPLICABLE_NEUTRAL_0,
            ),
            "rights_price": (
                Decimal(0),
                QD010_SOURCE_NOT_APPLICABLE_NEUTRAL_0,
            ),
        },
        "rights_issues": {
            "cash_per_share_gross": (
                Decimal(0),
                QD010_SOURCE_NOT_APPLICABLE_NEUTRAL_0,
            ),
            "share_multiplier": (
                Decimal(1),
                QD010_SOURCE_NOT_APPLICABLE_NEUTRAL_1,
            ),
        },
    }
    neutral = neutral_by_table[source_table].get(name)
    if neutral is not None:
        expected_value, expected_status = neutral
        if (
            not source_is_null
            or raw_bits is not None
            or typed != expected_value
            or status != expected_status
        ):
            raise V30StageAError(
                f"{label} {source_table}.{name} N/A neutral codec is invalid"
            )
        return typed, {
            "source_is_null": True,
            "source_float64_bits_le_hex": None,
            "typed_exact_decimal": format(typed, "f"),
            "normalization_status": status,
        }
    if source_is_null or raw_bits is None or status != QD010_SOURCE_VALUE_EXACT:
        raise V30StageAError(
            f"{label} {source_table}.{name} source-value codec is invalid"
        )
    source = _float64_from_le_bits(raw_bits, f"{label} {name} source bits")
    exact = Decimal.from_float(float(source))
    if typed != exact:
        raise V30StageAError(
            f"{label} {name} typed decimal differs from source float64 bits"
        )
    if name == "share_multiplier":
        if exact <= 0:
            raise V30StageAError(f"{label} share_multiplier is not positive")
    elif exact < 0:
        raise V30StageAError(f"{label} {name} is negative")
    return typed, {
        "source_is_null": False,
        "source_float64_bits_le_hex": str(raw_bits),
        "typed_exact_decimal": format(typed, "f"),
        "normalization_status": status,
    }


def qd010_permitted_projection_sha256(row: Mapping[str, Any]) -> str:
    """Hash only the frozen, typed QD010 projection; retain the source hash separately."""
    label = "QD010 permitted projection"
    _require_exact_projection(row, QD010_ACTION_INPUT_COLUMNS, label)
    raw_symbol = _require_nonempty_exact_string(row["raw_symbol"], f"{label} raw symbol")
    canonical_symbol = _require_nonempty_exact_string(
        row["canonical_symbol"], f"{label} canonical symbol"
    )
    if canonicalize_qd010_symbol(raw_symbol) != canonical_symbol:
        raise V30StageAError("QD010 raw/canonical symbol binding failed")
    source_table = _require_nonempty_exact_string(row["source_table"], f"{label} source")
    source_sha = _require_sha256(row["source_file_sha256"], f"{label} source SHA")
    if source_table not in QD010_SOURCE_SHA256 or source_sha != QD010_SOURCE_SHA256[source_table]:
        raise V30StageAError("QD010 source binding failed")
    source_row_hash = _require_sha256(row["source_row_hash"], f"{label} source row hash")
    terms_complete = row["source_terms_complete"]
    if not isinstance(terms_complete, (bool, np.bool_)):
        raise V30StageAError("QD010 source_terms_complete is not boolean")
    precision = _require_nonempty_exact_string(
        row["known_at_precision"], f"{label} known_at_precision"
    )
    if precision not in {"EXACT_TIMESTAMP", "DAY_ONLY"}:
        raise V30StageAError("QD010 known_at_precision is unsupported")
    known_at = _local_naive_timestamp(row["known_at"], f"{label} known_at")
    available_at = _local_naive_timestamp(row["available_at"], f"{label} available_at")
    if precision == "DAY_ONLY" and known_at != known_at.normalize():
        raise V30StageAError("QD010 DAY_ONLY knowledge is not normalized to midnight")
    effective = _normalized_date(row["effective_date"], f"{label} effective_date")
    terms = {
        name: _qd010_normalized_term_projection(
            row, name=name, source_table=source_table, label=label
        )[1]
        for name in (
            "cash_per_share_gross",
            "share_multiplier",
            "rights_ratio",
            "rights_price",
        )
    }
    payload = {
        "raw_symbol": raw_symbol,
        "canonical_symbol": canonical_symbol,
        "event_id": _require_nonempty_exact_string(row["event_id"], f"{label} event_id"),
        "source_row_hash": source_row_hash,
        "source_table": source_table,
        "source_file_sha256": source_sha,
        "source_locator": _require_nonempty_exact_string(
            row["source_locator"], f"{label} source_locator"
        ),
        "snapshot_id": _require_nonempty_exact_string(
            row["snapshot_id"], f"{label} snapshot_id"
        ),
        "vintage_id": _require_nonempty_exact_string(
            row["vintage_id"], f"{label} vintage_id"
        ),
        "known_at": known_at.isoformat(),
        "available_at": available_at.isoformat(),
        "known_at_precision": precision,
        "effective_date": effective.strftime("%Y-%m-%d"),
        "action_kind": _require_nonempty_exact_string(
            row["action_kind"], f"{label} action_kind"
        ),
        "source_terms_complete": bool(terms_complete),
        "normalized_terms": terms,
        "projection": "V30_QD010_PERMITTED_PROJECTION_V2",
    }
    return _canonical_json_sha256(payload)


def make_qd010_scope_proof(
    action_rows: Sequence[Mapping[str, Any]],
    *,
    candidate_key: CandidateKey,
    observation_at: Any,
    effective_end_date: Any,
    projected_row_count: Any,
    query_complete: Any,
) -> QD010ScopeProof:
    """Seal the exact causal QD010 projection before classifying action terms."""
    key = validate_candidate_key(candidate_key)
    observed = _local_naive_timestamp(observation_at, "QD010 scope observation_at")
    expected_observed = pd.Timestamp(f"{key.entry_date.date()} {ENTRY_CUTOFF_TIME}")
    end = _normalized_date(effective_end_date, "QD010 scope effective end")
    if observed != expected_observed or end <= key.entry_date:
        raise V30StageAError("QD010 scope chronology differs from the candidate clock")
    if not isinstance(query_complete, (bool, np.bool_)) or not bool(query_complete):
        raise V30StageAError("QD010 scoped query is incomplete")
    if (
        isinstance(projected_row_count, (bool, np.bool_))
        or not isinstance(projected_row_count, (int, np.integer))
        or int(projected_row_count) != len(action_rows)
    ):
        raise V30StageAError("QD010 scoped query row count does not conserve")
    source_row_hashes: list[str] = []
    projection_hashes: list[str] = []
    source_counts = {name: 0 for name in QD010_SOURCE_SHA256}
    for index, row in enumerate(action_rows):
        label = f"QD010 projected row {index}"
        _require_exact_projection(row, QD010_ACTION_INPUT_COLUMNS, label)
        source_row_hashes.append(
            _require_sha256(row["source_row_hash"], f"{label} source_row_hash")
        )
        supplied_projection = _require_sha256(
            row["permitted_projection_sha256"], f"{label} projection SHA"
        )
        computed_projection = qd010_permitted_projection_sha256(row)
        if supplied_projection != computed_projection:
            raise V30StageAError("QD010 permitted projection hash mismatch")
        projection_hashes.append(computed_projection)
        source_counts[str(row["source_table"])] += 1
    if (
        len(source_row_hashes) != len(set(source_row_hashes))
        or len(projection_hashes) != len(set(projection_hashes))
    ):
        raise V30StageAError("QD010 scoped query contains duplicate row identity")
    source_bindings = tuple(sorted(QD010_SOURCE_SHA256.items()))
    payload = {
        "candidate_key_sha256": key.sha256,
        "effective_end_inclusive": end.strftime("%Y-%m-%d"),
        "effective_start_exclusive": key.signal_date.strftime("%Y-%m-%d"),
        "observation_at": observed.isoformat(),
        "projected_row_count": int(projected_row_count),
        "projected_source_row_hashes": sorted(source_row_hashes),
        "permitted_projection_sha256s": sorted(projection_hashes),
        "source_row_counts": sorted(source_counts.items()),
        "query_complete": True,
        "query_predicate": (
            "canonical_symbol=candidate AND "
            "(effective_date IS NULL OR signal_date<effective_date<=H30) "
            "AND (known_at IS NULL OR known_at<=09:14:59)"
        ),
        "source_bindings": source_bindings,
    }
    return QD010ScopeProof(
        candidate_key=key,
        observation_at=observed,
        effective_start_exclusive=key.signal_date,
        effective_end_inclusive=end,
        projected_row_count=int(projected_row_count),
        projected_source_row_hashes=tuple(sorted(source_row_hashes)),
        permitted_projection_sha256s=tuple(sorted(projection_hashes)),
        source_row_counts=tuple(sorted(source_counts.items())),
        query_complete=True,
        source_bindings=source_bindings,
        scope_digest=_canonical_json_sha256(payload),
    )


def validate_qd010_scope_proof(
    proof: Any, action_rows: Sequence[Mapping[str, Any]]
) -> QD010ScopeProof:
    if not isinstance(proof, QD010ScopeProof):
        raise V30StageAError("QD010 ledger completeness lacks a typed scope proof")
    rebuilt = make_qd010_scope_proof(
        action_rows,
        candidate_key=proof.candidate_key,
        observation_at=proof.observation_at,
        effective_end_date=proof.effective_end_inclusive,
        projected_row_count=proof.projected_row_count,
        query_complete=proof.query_complete,
    )
    if proof != rebuilt:
        raise V30StageAError("QD010 scope proof fields or digest are inconsistent")
    return proof


def classify_qd010_action_row(row: Mapping[str, Any]) -> str:
    """Validate direct terms and return one normalized action risk class."""
    label = "QD010 action row"
    terms_complete = _required(row, "source_terms_complete", label)
    if not isinstance(terms_complete, (bool, np.bool_)) or not bool(terms_complete):
        raise V30StageAError("QD010 direct action terms are incomplete")
    declared = str(_required(row, "action_kind", label)).strip().upper()
    if not declared:
        raise V30StageAError("QD010 action kind is empty")
    _require_exact_projection(row, QD010_ACTION_INPUT_COLUMNS, label)
    if _require_sha256(
        row["permitted_projection_sha256"], "QD010 permitted projection SHA"
    ) != qd010_permitted_projection_sha256(row):
        raise V30StageAError("QD010 permitted projection hash mismatch")
    source_table = _require_nonempty_exact_string(
        row["source_table"], "QD010 action source table"
    )
    cash = _qd010_normalized_term_projection(
        row, name="cash_per_share_gross", source_table=source_table, label=label
    )[0]
    multiplier = _qd010_normalized_term_projection(
        row, name="share_multiplier", source_table=source_table, label=label
    )[0]
    rights_ratio = _qd010_normalized_term_projection(
        row, name="rights_ratio", source_table=source_table, label=label
    )[0]
    rights_price = _qd010_normalized_term_projection(
        row, name="rights_price", source_table=source_table, label=label
    )[0]
    if declared == "CASH_ONLY":
        valid = multiplier == 1 and rights_ratio == 0 and rights_price == 0
    elif declared == "RISK_SHARE":
        valid = multiplier != 1 and rights_ratio == 0 and rights_price == 0
    elif declared == "RISK_RIGHTS":
        valid = cash == 0 and multiplier == 1 and rights_ratio > 0
    else:
        return QD010_UNSUPPORTED_ACTION_KIND
    if not valid:
        raise V30StageAError("QD010 declared action kind conflicts with direct terms")
    return declared


def classify_entry_known_actions(
    action_rows: Sequence[Mapping[str, Any]],
    *,
    scope_proof: QD010ScopeProof,
) -> dict[str, Any]:
    """Classify only QD010 rows causally known by the 09:14:59 cutoff.

    The builder must apply the candidate/effective-date scope first and retain
    ``known_at IS NULL OR known_at <= observation``.  A null or mistakenly
    supplied future row therefore remains visible here and fails closed.
    """
    proof = validate_qd010_scope_proof(scope_proof, action_rows)
    key = proof.candidate_key
    observed = proof.observation_at
    start = proof.effective_start_exclusive
    entry = key.entry_date
    end = proof.effective_end_inclusive
    canonical_symbol = key.symbol
    seen: set[str] = set()
    seen_hashes: set[str] = set()
    seen_locators: set[tuple[str, str]] = set()
    classifications: list[dict[str, Any]] = []
    for index, row in enumerate(action_rows):
        label = f"QD010 row {index}"
        _require_exact_projection(row, QD010_ACTION_INPUT_COLUMNS, label)
        event_id = _require_nonempty_exact_string(
            _required(row, "event_id", label), f"{label} event_id"
        )
        source_row_hash = _require_sha256(
            _required(row, "source_row_hash", label), f"{label} source_row_hash"
        )
        permitted_projection_sha256 = _require_sha256(
            _required(row, "permitted_projection_sha256", label),
            f"{label} permitted projection SHA",
        )
        if permitted_projection_sha256 != qd010_permitted_projection_sha256(row):
            raise V30StageAError("QD010 permitted projection hash mismatch")
        snapshot_id = _require_nonempty_exact_string(
            _required(row, "snapshot_id", label), f"{label} snapshot_id"
        )
        vintage_id = _require_nonempty_exact_string(
            _required(row, "vintage_id", label), f"{label} vintage_id"
        )
        raw_symbol = _require_nonempty_exact_string(
            _required(row, "raw_symbol", label), f"{label} raw_symbol"
        )
        row_symbol = _require_nonempty_exact_string(
            _required(row, "canonical_symbol", label), f"{label} canonical_symbol"
        )
        source_table = _require_nonempty_exact_string(
            _required(row, "source_table", label), f"{label} source_table"
        )
        source_sha256 = _require_sha256(
            _required(row, "source_file_sha256", label), f"{label} source SHA-256"
        )
        source_locator = _require_nonempty_exact_string(
            _required(row, "source_locator", label), f"{label} source_locator"
        )
        if source_table not in QD010_SOURCE_SHA256 or source_sha256 != QD010_SOURCE_SHA256[source_table]:
            raise V30StageAError(f"{label} QD010 source binding failed")
        if canonicalize_qd010_symbol(raw_symbol) != row_symbol:
            raise V30StageAError(f"{label} raw/canonical symbol binding failed")
        known_at = _local_naive_timestamp(_required(row, "known_at", label), f"{label} known_at")
        available_at = _local_naive_timestamp(
            _required(row, "available_at", label), f"{label} available_at"
        )
        effective = _normalized_date(
            _required(row, "effective_date", label), f"{label} effective_date"
        )
        precision = _require_nonempty_exact_string(
            _required(row, "known_at_precision", label), f"{label} known_at_precision"
        )
        if precision not in {"EXACT_TIMESTAMP", "DAY_ONLY"}:
            raise V30StageAError(f"{label} known_at_precision is unsupported")
        if precision == "DAY_ONLY" and known_at != known_at.normalize():
            raise V30StageAError(f"{label} DAY_ONLY knowledge is not normalized to midnight")
        source_identity = (source_table, source_locator)
        if (
            event_id in seen
            or source_row_hash in seen_hashes
            or source_identity in seen_locators
            or row_symbol != canonical_symbol
            or known_at > observed
            or available_at > observed
            or available_at != known_at
            or not (start < effective <= end)
        ):
            raise V30StageAError("QD010 dual-time/scope/identity validation failed")
        seen.add(event_id)
        seen_hashes.add(source_row_hash)
        seen_locators.add(source_identity)
        action_class = classify_qd010_action_row(row)
        normalized_terms = {
            name: _qd010_normalized_term_projection(
                row, name=name, source_table=source_table, label=label
            )
            for name in (
                "cash_per_share_gross",
                "share_multiplier",
                "rights_ratio",
                "rights_price",
            )
        }
        if effective <= entry:
            entry_effect = "BLOCK_EFFECTIVE_BY_ENTRY"
        elif action_class in {
            "RISK_SHARE",
            "RISK_RIGHTS",
            QD010_UNSUPPORTED_ACTION_KIND,
        }:
            entry_effect = "BLOCK_POST_ENTRY_COORDINATE_RISK"
        else:
            entry_effect = "ALLOW_POST_ENTRY_CASH_ONLY_STAGE_B_REPLAY"
        classifications.append(
            {
                "event_id": event_id,
                "source_row_hash": source_row_hash,
                "permitted_projection_sha256": permitted_projection_sha256,
                "raw_symbol": raw_symbol,
                "canonical_symbol": row_symbol,
                "action_class": action_class,
                "effective_date": effective,
                "known_at": known_at,
                "available_at": available_at,
                "known_at_precision": precision,
                "entry_effect": entry_effect,
                "snapshot_id": snapshot_id,
                "vintage_id": vintage_id,
                "source_table": source_table,
                "source_file_sha256": source_sha256,
                "source_locator": source_locator,
                **{
                    name: format(value[0], "f")
                    for name, value in normalized_terms.items()
                },
                **{
                    f"{name}_source_is_null": value[1]["source_is_null"]
                    for name, value in normalized_terms.items()
                },
                **{
                    f"{name}_source_float64_bits": value[1][
                        "source_float64_bits_le_hex"
                    ]
                    for name, value in normalized_terms.items()
                },
                **{
                    f"{name}_normalization_status": value[1][
                        "normalization_status"
                    ]
                    for name, value in normalized_terms.items()
                },
            }
        )
    blockers = [
        item for item in classifications if str(item["entry_effect"]).startswith("BLOCK_")
    ]
    return {
        "status": "ACTION_BLOCKS_ENTRY" if blockers else "ACTION_FREE_FOR_ENTRY",
        "entry_blocked": bool(blockers),
        "known_action_count": len(classifications),
        "blocking_action_count": len(blockers),
        "post_entry_cash_only_count": sum(
            item["entry_effect"] == "ALLOW_POST_ENTRY_CASH_ONLY_STAGE_B_REPLAY"
            for item in classifications
        ),
        "classifications": tuple(classifications),
        "action_scope_digest": proof.scope_digest,
    }


def freeze_entry_order_at_0915(
    signal_state: Mapping[str, Any],
    action_rows: Sequence[Mapping[str, Any]],
    *,
    candidate_key: CandidateKey,
    action_scope_proof: QD010ScopeProof,
    administrative_row: Mapping[str, Any],
    market_calendar: pd.DataFrame,
    raw_l_tick: Any,
    reclaimed_pivot_tick: Any,
    expected_signal_close_tick: Any,
    expected_signal_snapshot_ids: Mapping[str, Any],
) -> FrozenEntryOrder:
    """Seal a 09:15 auction-participating 100-share DAY limit instruction."""
    key = validate_candidate_key(candidate_key)
    admin = validate_administrative_candidate(
        administrative_row, calendar=market_calendar, candidate_key=key
    )
    h30_date = _normalized_date(admin["h30_capacity_audit_date"], "entry H30 date")
    calendar_sha256 = _require_sha256(
        admin["market_calendar_sha256"], "entry market calendar SHA"
    )
    proof = validate_qd010_scope_proof(action_scope_proof, action_rows)
    if proof.candidate_key != key or proof.effective_end_inclusive != h30_date:
        raise V30StageAError("QD010 scope is not bound to candidate/H30")
    (
        signal_close_tick,
        signal_close_source_bits,
        signal_daily_projection_sha256,
    ) = validate_signal_day_state(
        signal_state,
        expected_signal_date=key.signal_date,
        expected_symbol=key.symbol,
        expected_signal_close_tick=expected_signal_close_tick,
        expected_snapshot_ids=expected_signal_snapshot_ids,
    )
    floor_tick = universal_maximum_down_floor_tick(signal_close_tick)
    cap_tick = universal_minimum_up_cap_tick(signal_close_tick)
    boundary_tick = _require_int64_tick(raw_l_tick, "authoritative raw L tick")
    pivot_tick = _require_int64_tick(reclaimed_pivot_tick, "reclaimed pivot tick")
    headroom_tick = max_buy_limit_tick_for_headroom(boundary_tick)
    actions = classify_entry_known_actions(action_rows, scope_proof=proof)
    status = "ENTRY_ORDER_FROZEN_FOR_0915_SUBMISSION"
    if bool(actions["entry_blocked"]):
        status = "NO_ENTRY_CAUSALLY_KNOWN_ACTION"
    elif headroom_tick is None:
        status = "NO_ENTRY_NO_VIABLE_A67_HEADROOM_TICK"
    proposed_limit = (
        planned_strict_buy_limit_tick(headroom_tick, cap_tick)
        if headroom_tick is not None
        else None
    )
    if (
        status == "ENTRY_ORDER_FROZEN_FOR_0915_SUBMISSION"
        and proposed_limit is not None
        and int(proposed_limit) < int(floor_tick)
    ):
        status = "NO_ENTRY_PLANNED_LIMIT_BELOW_D5"
    frozen_limit = (
        proposed_limit if status == "ENTRY_ORDER_FROZEN_FOR_0915_SUBMISSION" else None
    )
    decision_at = pd.Timestamp(f"{key.entry_date.date()} {ENTRY_CUTOFF_TIME}")
    submitted_at = pd.Timestamp(f"{key.entry_date.date()} {ORDER_SUBMITTED_TIME}")
    payload = {
        "action_scope_digest": proof.scope_digest,
        "candidate_key_sha256": key.sha256,
        "entry_hard_valid": frozen_limit is not None,
        "entry_status": status,
        "frozen_buy_limit_tick": int(frozen_limit) if frozen_limit is not None else None,
        "h30_capacity_audit_date": h30_date.strftime("%Y-%m-%d"),
        "market_calendar_sha256": calendar_sha256,
        "max_headroom_buy_tick": int(headroom_tick) if headroom_tick is not None else None,
        "order_decision_at": decision_at.isoformat(),
        "order_size_shares": ORDER_SIZE_SHARES,
        "order_submitted_at": submitted_at.isoformat(),
        "qd010_action_status": str(actions["status"]),
        "raw_l_tick": int(boundary_tick),
        "reclaimed_pivot_tick": int(pivot_tick),
        "signal_raw_close_tick": int(signal_close_tick),
        "signal_raw_close_source_float64_bits": signal_close_source_bits,
        "signal_daily_permitted_projection_sha256": (
            signal_daily_projection_sha256
        ),
        "entry_execution_evidence_label": ENTRY_EXECUTION_EVIDENCE_LABEL,
        "minimum_provable_strict_through_volume_shares": (
            MIN_PROXY_VOLUME_SHARES
        ),
        "maximum_research_lot_participation_numerator": ORDER_SIZE_SHARES,
        "maximum_research_lot_participation_denominator": (
            MIN_PROXY_VOLUME_SHARES
        ),
        "time_in_force": ORDER_TIME_IN_FORCE,
        "universal_maximum_down_floor_tick": int(floor_tick),
        "universal_minimum_up_cap_tick": int(cap_tick),
        "projection": "V30_FROZEN_0915_DAY_ORDER_CHAIN_V1",
    }
    return FrozenEntryOrder(
        candidate_key=key,
        order_decision_at=decision_at,
        order_submitted_at=submitted_at,
        market_calendar_sha256=calendar_sha256,
        signal_raw_close_tick=signal_close_tick,
        signal_raw_close_source_float64_bits=signal_close_source_bits,
        signal_daily_permitted_projection_sha256=(
            signal_daily_projection_sha256
        ),
        universal_maximum_down_floor_tick=floor_tick,
        raw_l_tick=boundary_tick,
        universal_minimum_up_cap_tick=cap_tick,
        max_headroom_buy_tick=headroom_tick,
        frozen_buy_limit_tick=frozen_limit,
        entry_hard_valid=frozen_limit is not None,
        entry_status=status,
        qd010_action_status=str(actions["status"]),
        action_scope_digest=proof.scope_digest,
        reclaimed_pivot_tick=pivot_tick,
        h30_capacity_audit_date=h30_date,
        order_size_shares=ORDER_SIZE_SHARES,
        time_in_force=ORDER_TIME_IN_FORCE,
        frozen_order_digest=_canonical_json_sha256(payload),
    )


def validate_frozen_order(value: Any) -> FrozenEntryOrder:
    if not isinstance(value, FrozenEntryOrder):
        raise V30StageAError("entry order is not a typed FrozenEntryOrder")
    key = validate_candidate_key(value.candidate_key)
    decision_at = pd.Timestamp(f"{key.entry_date.date()} {ENTRY_CUTOFF_TIME}")
    submitted_at = pd.Timestamp(f"{key.entry_date.date()} {ORDER_SUBMITTED_TIME}")
    signal_close = _require_int64_tick(value.signal_raw_close_tick, "order signal close")
    signal_close_source_bits = _require_nonempty_exact_string(
        value.signal_raw_close_source_float64_bits,
        "order signal close source float64 bits",
    )
    _daily_source_price_projection(
        _canonical_decimal_text(
            Decimal(int(signal_close)) / 100, "order signal close decimal"
        ),
        signal_close_source_bits,
        "order signal close",
    )
    signal_daily_projection_sha256 = _require_sha256(
        value.signal_daily_permitted_projection_sha256,
        "order signal daily permitted projection SHA",
    )
    floor = _require_int64_tick(
        value.universal_maximum_down_floor_tick, "order D5 floor tick"
    )
    raw_l = _require_int64_tick(value.raw_l_tick, "order raw L tick")
    cap = _require_int64_tick(value.universal_minimum_up_cap_tick, "order U5 tick")
    pivot = _require_int64_tick(value.reclaimed_pivot_tick, "order pivot tick")
    h30 = _normalized_date(value.h30_capacity_audit_date, "order H30 date")
    calendar_sha256 = _require_sha256(
        value.market_calendar_sha256, "order market calendar SHA"
    )
    action_digest = _require_sha256(value.action_scope_digest, "order action digest")
    if (
        value.order_decision_at != decision_at
        or value.order_submitted_at != submitted_at
        or not decision_at < submitted_at
        or h30 <= key.entry_date
        or isinstance(value.order_size_shares, (bool, np.bool_))
        or not isinstance(value.order_size_shares, (int, np.integer))
        or int(value.order_size_shares) != ORDER_SIZE_SHARES
        or value.time_in_force != ORDER_TIME_IN_FORCE
        or not isinstance(value.entry_hard_valid, (bool, np.bool_))
        or int(floor) != int(universal_maximum_down_floor_tick(signal_close))
        or int(cap) != int(universal_minimum_up_cap_tick(signal_close))
        or calendar_sha256 != FROZEN_CALENDAR_CANONICAL_SHA256
    ):
        raise V30StageAError("frozen 09:15 DAY order chronology/type is inconsistent")
    maximum = (
        None
        if value.max_headroom_buy_tick is None
        else _require_int64_tick(value.max_headroom_buy_tick, "order headroom tick")
    )
    limit = (
        None
        if value.frozen_buy_limit_tick is None
        else _require_int64_tick(value.frozen_buy_limit_tick, "order limit tick")
    )
    if bool(value.entry_hard_valid):
        if (
            value.entry_status != "ENTRY_ORDER_FROZEN_FOR_0915_SUBMISSION"
            or value.qd010_action_status != "ACTION_FREE_FOR_ENTRY"
            or maximum is None
            or limit is None
            or int(limit) != int(planned_strict_buy_limit_tick(maximum, cap))
            or int(limit) < int(floor)
            or int(limit) > int(cap)
            or exact_target_net(limit, raw_l) < MIN_EXACT_TARGET_NET
        ):
            raise V30StageAError("hard-valid frozen order is internally inconsistent")
    elif limit is not None or not value.entry_status.startswith("NO_ENTRY_"):
        raise V30StageAError("resolved no-order classification is inconsistent")
    payload = {
        "action_scope_digest": action_digest,
        "candidate_key_sha256": key.sha256,
        "entry_hard_valid": bool(value.entry_hard_valid),
        "entry_status": value.entry_status,
        "frozen_buy_limit_tick": int(limit) if limit is not None else None,
        "h30_capacity_audit_date": h30.strftime("%Y-%m-%d"),
        "market_calendar_sha256": calendar_sha256,
        "max_headroom_buy_tick": int(maximum) if maximum is not None else None,
        "order_decision_at": decision_at.isoformat(),
        "order_size_shares": ORDER_SIZE_SHARES,
        "order_submitted_at": submitted_at.isoformat(),
        "qd010_action_status": value.qd010_action_status,
        "raw_l_tick": int(raw_l),
        "reclaimed_pivot_tick": int(pivot),
        "signal_raw_close_tick": int(signal_close),
        "signal_raw_close_source_float64_bits": signal_close_source_bits,
        "signal_daily_permitted_projection_sha256": (
            signal_daily_projection_sha256
        ),
        "entry_execution_evidence_label": ENTRY_EXECUTION_EVIDENCE_LABEL,
        "minimum_provable_strict_through_volume_shares": (
            MIN_PROXY_VOLUME_SHARES
        ),
        "maximum_research_lot_participation_numerator": ORDER_SIZE_SHARES,
        "maximum_research_lot_participation_denominator": (
            MIN_PROXY_VOLUME_SHARES
        ),
        "time_in_force": ORDER_TIME_IN_FORCE,
        "universal_maximum_down_floor_tick": int(floor),
        "universal_minimum_up_cap_tick": int(cap),
        "projection": "V30_FROZEN_0915_DAY_ORDER_CHAIN_V1",
    }
    if value.frozen_order_digest != _canonical_json_sha256(payload):
        raise V30StageAError("frozen order digest is inconsistent")
    return value


def preorder_status_from_frozen_order(order: FrozenEntryOrder) -> str:
    order = validate_frozen_order(order)
    return PREORDER_ORDER_FROZEN if bool(order.entry_hard_valid) else PREORDER_RESOLVED_NO_ORDER


def _zero_scaffold_hash(
    row: Mapping[str, Any], *, order: FrozenEntryOrder, expected_end: pd.Timestamp
) -> QD004AbsentKey:
    label = "QD004 absent-key scaffold"
    _require_exact_projection(row, QD004_ENTRY_KEY_SCAFFOLD_COLUMNS, label)
    if tuple(row.keys()) != QD004_ENTRY_KEY_SCAFFOLD_COLUMNS:
        raise V30StageAError("QD004 exact projection order differs from preregistration")
    key = order.candidate_key
    identity = _qd004_query_scaffold_projection(
        row,
        key=key,
        expected_end=expected_end,
        expected_match_count=0,
        label=label,
    )
    row_sha256 = _canonical_json_sha256(
        {
            **identity,
            "physical_source_exact_order": list(QD004_PHYSICAL_SOURCE_COLUMNS),
            "physical_source_values": [None] * len(QD004_PHYSICAL_SOURCE_COLUMNS),
            "projection": "V30_QD004_CONFIRMED_ABSENT_KEY_V2",
        }
    )
    return QD004AbsentKey(
        candidate_key=key,
        bar_end_time=expected_end,
        query_partition_sha256=identity["query_partition_sha256"],
        query_locator=identity["query_locator"],
        row_sha256=row_sha256,
    )


def _initial_entry_prefix_digest(order: FrozenEntryOrder) -> str:
    return _canonical_json_sha256(
        {
            "candidate_key_sha256": order.candidate_key.sha256,
            "frozen_order_digest": order.frozen_order_digest,
            "projection": "V30_ORDERED_ENTRY_PREFIX_INITIAL_V1",
        }
    )


def validate_qd004_entry_bar_object(
    value: Any,
    *,
    order: FrozenEntryOrder,
    expected_end: pd.Timestamp,
    expected_prior_digest: str,
) -> QD004EntryBar:
    if not isinstance(value, QD004EntryBar):
        raise V30StageAError("entry bar is not a typed QD004EntryBar")
    key = validate_candidate_key(value.candidate_key)
    order = validate_frozen_order(order)
    if key != order.candidate_key or value.bar_end_time != expected_end:
        raise V30StageAError("typed QD004 entry bar identity failed")
    code, exchange = key.symbol.rsplit(".", 1)
    raw_prices = {
        name: _float64_from_bits(
            getattr(value, f"{name}_source_float64_bits"), f"typed entry {name}"
        )
        for name in ("open", "high", "low", "close")
    }
    raw_volume = _float64_from_bits(
        value.volume_source_float64_bits, "typed entry volume"
    )
    raw_amount = _float64_from_bits(
        value.amount_source_float64_bits, "typed entry amount"
    )
    row = {
        "qmt_code": key.symbol,
        "symbol": code,
        "exchange": exchange,
        "period": "1m",
        "adjust": "none",
        "trade_date": key.entry_date,
        "bar_end_time": expected_end,
        "open": raw_prices["open"],
        "high": raw_prices["high"],
        "low": raw_prices["low"],
        "close": raw_prices["close"],
        "volume": raw_volume,
        "amount": raw_amount,
        "source": QD004_REQUIRED_SOURCE,
        "protocol_arm": key.protocol_arm,
        "gap_id": key.gap_id,
        "candidate_symbol": key.symbol,
        "expected_trade_date": key.entry_date,
        "expected_bar_end_time": expected_end,
        "available_at": value.available_at,
        "bar_valid": True,
        "source_snapshot_id": value.source_snapshot_id,
        "query_partition_sha256": value.query_partition_sha256,
        "query_locator": value.query_locator,
        "physical_source_locator": value.physical_source_locator,
        "source_match_count": np.int64(1),
        "permitted_projection_sha256": value.row_sha256,
    }
    rebuilt = validate_qd004_entry_bar(
        row,
        order=order,
        expected_bar_end_time=expected_end,
        prior_prefix_digest=expected_prior_digest,
        expected_row_sha256=value.row_sha256,
    )
    if value != rebuilt:
        raise V30StageAError("typed QD004 entry fields or hash chain failed")
    return value


def validate_qd004_absent_key_object(
    value: Any, *, order: FrozenEntryOrder, expected_end: pd.Timestamp
) -> QD004AbsentKey:
    if not isinstance(value, QD004AbsentKey):
        raise V30StageAError("absent key is not typed")
    key = validate_candidate_key(value.candidate_key)
    partition = _require_sha256(value.query_partition_sha256, "absent-key partition")
    expected_partition = QD004_DEVELOPMENT_PARTITION_SHA256[int(key.entry_date.year)]
    query_locator = _require_nonempty_exact_string(
        value.query_locator, "absent-key query locator"
    )
    expected_query, _ = _expected_qd004_locators(key, expected_end, expected_partition)
    digest = _canonical_json_sha256(
        {
            "protocol_arm": key.protocol_arm,
            "gap_id": key.gap_id,
            "candidate_symbol": key.symbol,
            "expected_trade_date": key.entry_date.strftime("%Y-%m-%d"),
            "expected_bar_end_time": expected_end.isoformat(),
            "available_at": None,
            "bar_valid": None,
            "source_snapshot_id": None,
            "query_partition_sha256": partition,
            "query_locator": query_locator,
            "physical_source_locator": None,
            "source_match_count": 0,
            "physical_source_exact_order": list(QD004_PHYSICAL_SOURCE_COLUMNS),
            "physical_source_values": [None] * len(QD004_PHYSICAL_SOURCE_COLUMNS),
            "projection": "V30_QD004_CONFIRMED_ABSENT_KEY_V2",
        }
    )
    if (
        key != order.candidate_key
        or value.bar_end_time != expected_end
        or partition != expected_partition
        or query_locator != expected_query
        or value.row_sha256 != digest
    ):
        raise V30StageAError("absent QD004 key digest/identity failed")
    return value


def _expected_cy033_h0_locators(
    key: CandidateKey, partition_sha256: str
) -> tuple[str, str, str]:
    date_text = key.entry_date.strftime("%Y-%m-%d")
    query = f"CY033_H0_QUERY_V1:{key.symbol}:{date_text}"
    physical = f"CY033_H0_ROW_V1:{partition_sha256}:{key.symbol}:{date_text}:0"
    snapshot = (
        f"CY033:{CY033_ASSET_MANIFEST_SHA256}:{partition_sha256}"
    )
    return query, physical, snapshot


def _strict_bool_value(value: Any, label: str) -> bool:
    if not isinstance(value, (bool, np.bool_)):
        raise V30StageAError(f"{label} is not boolean")
    return bool(value)


def _nullable_float64_projection(
    value: Any, label: str
) -> tuple[np.float64, str, str | None]:
    if isinstance(value, (bool, np.bool_)) or not isinstance(
        value, (float, np.floating)
    ):
        raise V30StageAError(f"{label} is not a source float64")
    result = np.float64(value)
    bits = struct.pack("<d", float(result)).hex()
    if np.isnan(result):
        return result, bits, None
    if not np.isfinite(result):
        raise V30StageAError(f"{label} is infinite")
    return result, bits, format(_float64_exact_decimal(result), "f")


def _optional_exact_text(value: Any, label: str) -> str | None:
    if value is None or pd.isna(value):
        return None
    if not isinstance(value, str) or value != value.strip():
        raise V30StageAError(f"{label} is not exact nullable text")
    return value


def _cy033_h0_projection(
    row: Mapping[str, Any], *, candidate_key: CandidateKey
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Canonicalize exactly 47 physical CY033 columns plus 9 scaffold fields."""
    label = "CY033 H0 terminal audit"
    _require_exact_projection(row, CY033_H0_AUDIT_INPUT_COLUMNS, label)
    if tuple(row.keys()) != CY033_H0_AUDIT_INPUT_COLUMNS:
        raise V30StageAError("CY033 H0 exact projection order differs from preregistration")
    key = validate_candidate_key(candidate_key)
    protocol_arm = _require_nonempty_exact_string(
        row["protocol_arm"], "CY033 H0 protocol arm"
    )
    gap_id = _require_nonempty_exact_string(row["gap_id"], "CY033 H0 gap_id")
    symbol = canonical_candidate_symbol(row["symbol"])
    trade_date = _normalized_date(row["trade_date"], f"{label} trade_date")
    expected_trade_date = _normalized_date(
        row["expected_trade_date"], f"{label} expected_trade_date"
    )
    decision_at = _local_naive_timestamp(row["decision_at"], f"{label} decision_at")
    available_at = _local_naive_timestamp(
        row["available_at"], f"{label} available_at"
    )
    expected_at = pd.Timestamp(f"{key.entry_date.date()} {TERMINAL_AUDIT_TIME}")
    if (
        protocol_arm != key.protocol_arm
        or gap_id != key.gap_id
        or symbol != key.symbol
        or trade_date != key.entry_date
        or expected_trade_date != key.entry_date
        or decision_at != expected_at
        or available_at != expected_at
        or available_at
        < pd.Timestamp(f"{key.entry_date.date()} {ORDER_CANCEL_TIME}")
        or row["decision_timezone"] != "Asia/Shanghai"
    ):
        raise V30StageAError("CY033 H0 identity/PIT clock is inconsistent")

    integer_fields: dict[str, int] = {}
    for name in ("trade_status", "corporate_action_count", "source_match_count"):
        value = row[name]
        if isinstance(value, (bool, np.bool_)) or not isinstance(
            value, (int, np.integer)
        ):
            raise V30StageAError(f"CY033 H0 {name} is not an integer")
        integer_fields[name] = int(value)
    if (
        integer_fields["trade_status"] not in {0, 1}
        or integer_fields["corporate_action_count"] < 0
        or integer_fields["source_match_count"] != 1
    ):
        raise V30StageAError("CY033 H0 status/count is outside the registered domain")

    bool_fields = (
        "is_st",
        "corporate_action_blocking",
        "bar_valid",
        "trading_state_valid",
        "industry_valid",
        "float_valid",
        "corporate_action_valid",
        "market_valid",
        "market_rule_valid",
        "historical_identity_valid",
        "hard_valid",
        "current_day_data_tradable",
        "strict_archive_ready",
    )
    booleans = {
        name: _strict_bool_value(row[name], f"CY033 H0 {name}")
        for name in bool_fields
    }
    required_validity = (
        "bar_valid",
        "trading_state_valid",
        "industry_valid",
        "float_valid",
        "corporate_action_valid",
        "market_valid",
        "market_rule_valid",
        "historical_identity_valid",
        "hard_valid",
    )
    if (
        not all(booleans[name] for name in required_validity)
        or booleans["current_day_data_tradable"]
        != (integer_fields["trade_status"] == 1)
        or booleans["strict_archive_ready"]
    ):
        raise V30StageAError("CY033 H0 validity/tradability flags do not conserve")
    invalid_reasons = row["invalid_reasons"]
    if not isinstance(invalid_reasons, str) or invalid_reasons != "":
        raise V30StageAError("CY033 H0 invalid-reason ledger is not empty")

    numeric: dict[str, tuple[np.float64, str, str | None]] = {}
    for name in (
        "volume",
        "amount",
        "circulating_shares",
        "share_multiplier",
        "cash_per_share",
        "rights_ratio",
        "rights_price",
    ):
        numeric[name] = _nullable_float64_projection(row[name], f"CY033 H0 {name}")
    volume, volume_bits, volume_exact = numeric["volume"]
    amount, amount_bits, amount_exact = numeric["amount"]
    circulating, circulating_bits, circulating_exact = numeric["circulating_shares"]
    share_multiplier, share_bits, share_exact = numeric["share_multiplier"]
    cash, cash_bits, cash_exact = numeric["cash_per_share"]
    rights_ratio, rights_ratio_bits, rights_ratio_exact = numeric["rights_ratio"]
    rights_price, rights_price_bits, rights_price_exact = numeric["rights_price"]
    if (
        volume_exact is None
        or amount_exact is None
        or circulating_exact is None
        or share_exact is None
        or cash_exact is None
        or volume < 0
        or amount < 0
        or circulating <= 0
        or not float(volume).is_integer()
        or volume > 2**53
        or volume > np.iinfo(np.int64).max
        or (volume == 0) != (amount == 0)
        or share_multiplier != 1
        or cash != 0
        or (not np.isnan(rights_ratio) and rights_ratio != 0)
        or (not np.isnan(rights_price) and rights_price != 0)
    ):
        raise V30StageAError("CY033 H0 raw numeric/action terms are inconsistent")

    float_effective_date = _normalized_date(
        row["float_effective_date"], "CY033 H0 float effective date"
    )
    float_announced_date = _normalized_date(
        row["float_announced_date"], "CY033 H0 float announced date"
    )
    float_available_date = _normalized_date(
        row["float_available_date"], "CY033 H0 float available date"
    )
    action_available_date = _normalized_date(
        row["corporate_action_available_date"],
        "CY033 H0 action available date",
    )
    if (
        float_available_date != max(float_effective_date, float_announced_date)
        or float_available_date > trade_date
        or float_effective_date > trade_date
        or float_announced_date > trade_date
        or action_available_date > trade_date
    ):
        raise V30StageAError("CY033 H0 float/action dates are noncausal")

    text_fields = {
        name: _require_nonempty_exact_string(row[name], f"CY033 H0 {name}")
        for name in (
            "state_source",
            "float_source",
            "corporate_action_source",
            "market_rule_id",
            "market_rule_source",
            "snapshot_id",
            "pit_grade",
            "daily_snapshot_id",
            "trading_state_snapshot_id",
            "industry_snapshot_id",
            "float_snapshot_id",
            "corporate_action_snapshot_id",
            "market_snapshot_id",
        )
    }
    if (
        text_fields["snapshot_id"] != CY033_REGISTERED_SNAPSHOT_ID
        or text_fields["pit_grade"] != "B_CAUSAL_RESEARCH"
    ):
        raise V30StageAError("CY033 H0 record snapshot/PIT grade is unregistered")
    action_ids = _optional_exact_text(
        row["corporate_action_ids"], "CY033 H0 action ids"
    )
    action_problems = _optional_exact_text(
        row["corporate_action_problems"], "CY033 H0 action problems"
    )
    if (
        integer_fields["corporate_action_count"] != 0
        or booleans["corporate_action_blocking"]
        or action_ids not in {None, ""}
        or action_problems not in {None, ""}
    ):
        raise V30StageAError("CY033 H0 contains a corporate-action conflict")

    partition_sha = _require_sha256(
        row["query_partition_sha256"], "CY033 H0 partition SHA"
    )
    expected_partition = CY033_DEVELOPMENT_PARTITION_SHA256.get(int(trade_date.year))
    query_locator = _require_nonempty_exact_string(
        row["query_locator"], "CY033 H0 query locator"
    )
    physical_locator = _require_nonempty_exact_string(
        row["physical_source_locator"], "CY033 H0 physical locator"
    )
    source_snapshot_id = _require_nonempty_exact_string(
        row["source_snapshot_id"], "CY033 H0 source snapshot"
    )
    expected_query, expected_physical, expected_source_snapshot = (
        _expected_cy033_h0_locators(key, partition_sha)
    )
    if (
        expected_partition is None
        or partition_sha != expected_partition
        or query_locator != expected_query
        or physical_locator != expected_physical
        or source_snapshot_id != expected_source_snapshot
    ):
        raise V30StageAError("CY033 H0 registered partition/locator binding failed")

    source_payload = {
        "trade_date": trade_date.strftime("%Y-%m-%d"),
        "decision_at": decision_at.isoformat(),
        "decision_timezone": "Asia/Shanghai",
        "symbol": symbol,
        "volume": {"exact_decimal": volume_exact, "float64_bits_le_hex": volume_bits},
        "amount": {"exact_decimal": amount_exact, "float64_bits_le_hex": amount_bits},
        "trade_status": integer_fields["trade_status"],
        "is_st": booleans["is_st"],
        "state_source": text_fields["state_source"],
        "float_effective_date": float_effective_date.strftime("%Y-%m-%d"),
        "float_announced_date": float_announced_date.strftime("%Y-%m-%d"),
        "float_available_date": float_available_date.strftime("%Y-%m-%d"),
        "circulating_shares": {
            "exact_decimal": circulating_exact,
            "float64_bits_le_hex": circulating_bits,
        },
        "float_source": text_fields["float_source"],
        "corporate_action_count": integer_fields["corporate_action_count"],
        "corporate_action_ids": action_ids,
        "corporate_action_source": text_fields["corporate_action_source"],
        "corporate_action_available_date": action_available_date.strftime("%Y-%m-%d"),
        "corporate_action_blocking": booleans["corporate_action_blocking"],
        "corporate_action_problems": action_problems,
        "share_multiplier": {
            "exact_decimal": share_exact,
            "float64_bits_le_hex": share_bits,
        },
        "cash_per_share": {
            "exact_decimal": cash_exact,
            "float64_bits_le_hex": cash_bits,
        },
        "rights_ratio": {
            "exact_decimal": rights_ratio_exact,
            "float64_bits_le_hex": rights_ratio_bits,
        },
        "rights_price": {
            "exact_decimal": rights_price_exact,
            "float64_bits_le_hex": rights_price_bits,
        },
        "market_rule_id": text_fields["market_rule_id"],
        "market_rule_source": text_fields["market_rule_source"],
        **{name: booleans[name] for name in required_validity},
        "invalid_reasons": invalid_reasons,
        "current_day_data_tradable": booleans["current_day_data_tradable"],
        "available_at": available_at.isoformat(),
        "snapshot_id": text_fields["snapshot_id"],
        "pit_grade": text_fields["pit_grade"],
        "strict_archive_ready": booleans["strict_archive_ready"],
        **{
            name: text_fields[name]
            for name in (
                "daily_snapshot_id",
                "trading_state_snapshot_id",
                "industry_snapshot_id",
                "float_snapshot_id",
                "corporate_action_snapshot_id",
                "market_snapshot_id",
            )
        },
    }
    derived_payload = {
        "protocol_arm": protocol_arm,
        "gap_id": gap_id,
        "expected_trade_date": expected_trade_date.strftime("%Y-%m-%d"),
        "source_match_count": integer_fields["source_match_count"],
        "query_locator": query_locator,
        "query_partition_sha256": partition_sha,
        "physical_source_locator": physical_locator,
        "source_snapshot_id": source_snapshot_id,
    }
    payload = {
        "source_projection": source_payload,
        "derived_scaffold": derived_payload,
        "source_projection_exact_order": list(CY033_H0_SOURCE_PROJECTION_COLUMNS),
        "derived_scaffold_hashed_fields_exact_order": list(
            CY033_H0_DERIVED_SCAFFOLD_COLUMNS[:-1]
        ),
        "input_envelope_exact_order": list(CY033_H0_AUDIT_INPUT_COLUMNS),
        "projection": "V30_CY033_H0_PERMITTED_TERMINAL_AUDIT_V2",
    }
    parsed = {
        **source_payload,
        **derived_payload,
        "trade_date": trade_date,
        "expected_trade_date": expected_trade_date,
        "decision_at": decision_at,
        "available_at": available_at,
        "float_effective_date": float_effective_date,
        "float_announced_date": float_announced_date,
        "float_available_date": float_available_date,
        "corporate_action_available_date": action_available_date,
        "volume_decimal": _float64_exact_decimal(volume),
        "amount_decimal": _float64_exact_decimal(amount),
        "volume_bits": volume_bits,
        "amount_bits": amount_bits,
        "circulating_exact": circulating_exact,
        "circulating_bits": circulating_bits,
        "share_exact": share_exact,
        "share_bits": share_bits,
        "cash_exact": cash_exact,
        "cash_bits": cash_bits,
        "rights_ratio_exact": rights_ratio_exact,
        "rights_ratio_bits": rights_ratio_bits,
        "rights_price_exact": rights_price_exact,
        "rights_price_bits": rights_price_bits,
    }
    return payload, parsed


def cy033_h0_permitted_projection_sha256(
    row: Mapping[str, Any], *, candidate_key: CandidateKey
) -> str:
    payload, _ = _cy033_h0_projection(row, candidate_key=candidate_key)
    return _canonical_json_sha256(payload)


def validate_cy033_h0_terminal_audit(
    row: Mapping[str, Any],
    *,
    order: FrozenEntryOrder,
    opened_bars: Sequence[QD004EntryBar],
    minute_status: str,
) -> CY033H0TerminalAudit:
    """Corroborate a finished minute settlement; never infer an entry from H0."""
    order = validate_frozen_order(order)
    if not opened_bars or order.qd010_action_status != "ACTION_FREE_FOR_ENTRY":
        raise V30StageAError("CY033 H0 cannot audit an unfinished/action-conflicted order")
    payload, parsed = _cy033_h0_projection(row, candidate_key=order.candidate_key)
    supplied_projection = _require_sha256(
        row["permitted_projection_sha256"], "CY033 H0 projection SHA"
    )
    if supplied_projection != _canonical_json_sha256(payload):
        raise V30StageAError("CY033 H0 permitted projection hash mismatch")

    minute_volume = sum(
        (_nonnegative_decimal(bar.volume_exact, "H0 minute volume") for bar in opened_bars),
        Decimal(0),
    )
    minute_amount = sum(
        (_nonnegative_decimal(bar.amount_exact, "H0 minute amount") for bar in opened_bars),
        Decimal(0),
    )
    daily_volume = parsed["volume_decimal"]
    daily_amount = parsed["amount_decimal"]
    if daily_volume < minute_volume or daily_amount < minute_amount:
        raise V30StageAError("CY033 H0 daily mass is below the opened minute prefix")
    if daily_volume == 0:
        if (
            minute_volume != 0
            or minute_amount != 0
            or parsed["trade_status"] != 0
            or parsed["current_day_data_tradable"]
            or minute_status != "DAY_LIMIT_CANCELLED_093701_NO_FILL"
            or len(opened_bars) != len(ENTRY_SCAN_BAR_END_TIMES)
        ):
            raise V30StageAError("CY033 H0 suspension state contradicts minute evidence")
        audit_status = "H0_CORROBORATED_SUSPENSION_NO_FILL"
    else:
        if (
            daily_amount <= 0
            or parsed["trade_status"] != 1
            or not parsed["current_day_data_tradable"]
        ):
            raise V30StageAError("CY033 H0 traded-day state is inconsistent")
        if minute_status == "COUNTERFACTUAL_1PCT_BAR_CROSS_PROXY_FILL_PROVED":
            audit_status = "H0_CORROBORATED_COUNTERFACTUAL_PROXY_FILL"
        elif (
            minute_status == "DAY_LIMIT_CANCELLED_093701_NO_FILL"
            and len(opened_bars) == len(ENTRY_SCAN_BAR_END_TIMES)
        ):
            audit_status = "H0_CORROBORATED_TRADED_DAY_NO_FILL"
        else:
            raise V30StageAError("CY033 H0 was asked to settle a nonterminal minute state")
    opened_hashes = [
        _require_sha256(bar.row_sha256, "H0 opened minute hash") for bar in opened_bars
    ]
    audit_digest = _canonical_json_sha256(
        {
            "audit_status": audit_status,
            "candidate_key_sha256": order.candidate_key.sha256,
            "frozen_order_digest": order.frozen_order_digest,
            "minute_status": minute_status,
            "opened_row_sha256": opened_hashes,
            "permitted_projection_sha256": supplied_projection,
            "projection": "V30_CY033_H0_TERMINAL_AUDIT_CHAIN_V2",
        }
    )
    return CY033H0TerminalAudit(
        candidate_key=order.candidate_key,
        decision_at=parsed["decision_at"],
        available_at=parsed["available_at"],
        trade_status=parsed["trade_status"],
        current_day_data_tradable=parsed["current_day_data_tradable"],
        is_st=parsed["is_st"],
        state_source=parsed["state_source"],
        daily_volume_exact=parsed["volume"]["exact_decimal"],
        daily_volume_float64_bits=parsed["volume_bits"],
        daily_amount_exact=parsed["amount"]["exact_decimal"],
        daily_amount_float64_bits=parsed["amount_bits"],
        float_effective_date=parsed["float_effective_date"],
        float_announced_date=parsed["float_announced_date"],
        float_available_date=parsed["float_available_date"],
        circulating_shares_exact=parsed["circulating_exact"],
        circulating_shares_float64_bits=parsed["circulating_bits"],
        float_source=parsed["float_source"],
        corporate_action_count=parsed["corporate_action_count"],
        corporate_action_ids=parsed["corporate_action_ids"],
        corporate_action_source=parsed["corporate_action_source"],
        corporate_action_available_date=parsed["corporate_action_available_date"],
        corporate_action_blocking=parsed["corporate_action_blocking"],
        corporate_action_problems=parsed["corporate_action_problems"],
        share_multiplier_exact=parsed["share_exact"],
        share_multiplier_float64_bits=parsed["share_bits"],
        cash_per_share_exact=parsed["cash_exact"],
        cash_per_share_float64_bits=parsed["cash_bits"],
        rights_ratio_exact=parsed["rights_ratio_exact"],
        rights_ratio_float64_bits=parsed["rights_ratio_bits"],
        rights_price_exact=parsed["rights_price_exact"],
        rights_price_float64_bits=parsed["rights_price_bits"],
        market_rule_id=parsed["market_rule_id"],
        market_rule_source=parsed["market_rule_source"],
        bar_valid=parsed["bar_valid"],
        trading_state_valid=parsed["trading_state_valid"],
        industry_valid=parsed["industry_valid"],
        float_valid=parsed["float_valid"],
        corporate_action_valid=parsed["corporate_action_valid"],
        market_valid=parsed["market_valid"],
        market_rule_valid=parsed["market_rule_valid"],
        historical_identity_valid=parsed["historical_identity_valid"],
        hard_valid=parsed["hard_valid"],
        invalid_reasons=parsed["invalid_reasons"],
        snapshot_id=parsed["snapshot_id"],
        pit_grade=parsed["pit_grade"],
        strict_archive_ready=parsed["strict_archive_ready"],
        daily_snapshot_id=parsed["daily_snapshot_id"],
        trading_state_snapshot_id=parsed["trading_state_snapshot_id"],
        industry_snapshot_id=parsed["industry_snapshot_id"],
        float_snapshot_id=parsed["float_snapshot_id"],
        corporate_action_snapshot_id=parsed["corporate_action_snapshot_id"],
        market_snapshot_id=parsed["market_snapshot_id"],
        query_partition_sha256=parsed["query_partition_sha256"],
        query_locator=parsed["query_locator"],
        physical_source_locator=parsed["physical_source_locator"],
        source_snapshot_id=parsed["source_snapshot_id"],
        source_match_count=parsed["source_match_count"],
        permitted_projection_sha256=supplied_projection,
        audit_status=audit_status,
        audit_digest=audit_digest,
    )


def _float64_from_bits(bits: str, label: str) -> np.float64:
    if not isinstance(bits, str) or len(bits) != 16:
        raise V30StageAError(f"{label} bits are malformed")
    try:
        return np.float64(struct.unpack("<d", bytes.fromhex(bits))[0])
    except (ValueError, struct.error) as exc:
        raise V30StageAError(f"{label} bits are malformed") from exc


def validate_cy033_h0_terminal_audit_object(
    value: Any,
    *,
    order: FrozenEntryOrder,
    opened_bars: Sequence[QD004EntryBar],
    minute_status: str,
) -> CY033H0TerminalAudit:
    if not isinstance(value, CY033H0TerminalAudit):
        raise V30StageAError("H0 terminal audit is not a typed sealed object")
    row = {
        "trade_date": value.candidate_key.entry_date,
        "decision_at": value.decision_at,
        "decision_timezone": "Asia/Shanghai",
        "symbol": value.candidate_key.symbol,
        "volume": _float64_from_bits(value.daily_volume_float64_bits, "typed H0 volume"),
        "amount": _float64_from_bits(value.daily_amount_float64_bits, "typed H0 amount"),
        "trade_status": value.trade_status,
        "is_st": value.is_st,
        "state_source": value.state_source,
        "float_effective_date": value.float_effective_date,
        "float_announced_date": value.float_announced_date,
        "float_available_date": value.float_available_date,
        "circulating_shares": _float64_from_bits(
            value.circulating_shares_float64_bits, "typed H0 circulating shares"
        ),
        "float_source": value.float_source,
        "corporate_action_count": value.corporate_action_count,
        "corporate_action_ids": value.corporate_action_ids,
        "corporate_action_source": value.corporate_action_source,
        "corporate_action_available_date": value.corporate_action_available_date,
        "corporate_action_blocking": value.corporate_action_blocking,
        "corporate_action_problems": value.corporate_action_problems,
        "share_multiplier": _float64_from_bits(
            value.share_multiplier_float64_bits, "typed H0 share multiplier"
        ),
        "cash_per_share": _float64_from_bits(
            value.cash_per_share_float64_bits, "typed H0 cash per share"
        ),
        "rights_ratio": _float64_from_bits(
            value.rights_ratio_float64_bits, "typed H0 rights ratio"
        ),
        "rights_price": _float64_from_bits(
            value.rights_price_float64_bits, "typed H0 rights price"
        ),
        "market_rule_id": value.market_rule_id,
        "market_rule_source": value.market_rule_source,
        "bar_valid": value.bar_valid,
        "trading_state_valid": value.trading_state_valid,
        "industry_valid": value.industry_valid,
        "float_valid": value.float_valid,
        "corporate_action_valid": value.corporate_action_valid,
        "market_valid": value.market_valid,
        "market_rule_valid": value.market_rule_valid,
        "historical_identity_valid": value.historical_identity_valid,
        "hard_valid": value.hard_valid,
        "invalid_reasons": value.invalid_reasons,
        "current_day_data_tradable": value.current_day_data_tradable,
        "available_at": value.available_at,
        "snapshot_id": value.snapshot_id,
        "pit_grade": value.pit_grade,
        "strict_archive_ready": value.strict_archive_ready,
        "daily_snapshot_id": value.daily_snapshot_id,
        "trading_state_snapshot_id": value.trading_state_snapshot_id,
        "industry_snapshot_id": value.industry_snapshot_id,
        "float_snapshot_id": value.float_snapshot_id,
        "corporate_action_snapshot_id": value.corporate_action_snapshot_id,
        "market_snapshot_id": value.market_snapshot_id,
        "protocol_arm": value.candidate_key.protocol_arm,
        "gap_id": value.candidate_key.gap_id,
        "expected_trade_date": value.candidate_key.entry_date,
        "source_match_count": value.source_match_count,
        "query_locator": value.query_locator,
        "query_partition_sha256": value.query_partition_sha256,
        "physical_source_locator": value.physical_source_locator,
        "source_snapshot_id": value.source_snapshot_id,
        "permitted_projection_sha256": value.permitted_projection_sha256,
    }
    rebuilt = validate_cy033_h0_terminal_audit(
        row,
        order=order,
        opened_bars=opened_bars,
        minute_status=minute_status,
    )
    if value != rebuilt:
        raise V30StageAError("H0 terminal audit fields or digest are inconsistent")
    return value


def _terminal_minute_outcome(
    order: FrozenEntryOrder, bars: Sequence[QD004EntryBar]
) -> tuple[bool, np.int64 | None, pd.Timestamp | None, str]:
    crossing = [
        index
        for index, bar in enumerate(bars)
        if bar.provable_strict_cross_volume_shares >= MIN_PROXY_VOLUME_SHARES
        and bar.bar_transition == "FULL_PROXY_PROVED"
    ]
    if crossing:
        if crossing != [len(bars) - 1]:
            raise V30StageAError("entry evidence did not stop at the first proof bar")
        return (
            True,
            np.int64(order.frozen_buy_limit_tick),
            None,
            "COUNTERFACTUAL_1PCT_BAR_CROSS_PROXY_FILL_PROVED",
        )
    if len(bars) == len(ENTRY_SCAN_BAR_END_TIMES):
        possible_partial = any(
            bar.bar_transition == "POSSIBLE_PARTIAL_OR_FULL_FILL"
            for bar in bars
        )
        if possible_partial:
            raise V30StageAError(
                "terminal minute window contains unresolved possible partial fill"
            )
        return (
            False,
            None,
            pd.Timestamp(f"{order.candidate_key.entry_date.date()} {ORDER_CANCEL_TIME}"),
            "DAY_LIMIT_CANCELLED_093701_NO_FILL",
        )
    raise V30StageAError("non-crossing entry evidence ended before 09:37")


def _build_entry_settlement(
    order: FrozenEntryOrder,
    bars: Sequence[QD004EntryBar],
    opened_key_sha256: Sequence[str],
    h0_audit: CY033H0TerminalAudit,
) -> EntrySettlementEvidence:
    order = validate_frozen_order(order)
    if not order.entry_hard_valid or order.frozen_buy_limit_tick is None:
        raise V30StageAError("resolved no-order row cannot open entry evidence")
    opened_hashes = tuple(_require_sha256(value, "opened entry key hash") for value in opened_key_sha256)
    if not bars or len(bars) != len(opened_hashes):
        raise V30StageAError("entry bar/hash evidence does not conserve")
    locators: set[str] = set()
    previous = _initial_entry_prefix_digest(order)
    for index, bar in enumerate(bars):
        expected_end = pd.Timestamp(
            f"{order.candidate_key.entry_date.date()} {ENTRY_SCAN_BAR_END_TIMES[index]}:00"
        )
        validate_qd004_entry_bar_object(
            bar,
            order=order,
            expected_end=expected_end,
            expected_prior_digest=previous,
        )
        if bar.physical_source_locator in locators or bar.row_sha256 != opened_hashes[index]:
            raise V30StageAError("typed entry prefix is reordered, duplicate or unbound")
        _require_sha256(bar.prefix_digest, "entry prefix digest")
        locators.add(bar.physical_source_locator)
        previous = bar.prefix_digest
    accepted, fill_tick, cancel_at, status = _terminal_minute_outcome(order, bars)
    h0_audit = validate_cy033_h0_terminal_audit_object(
        h0_audit,
        order=order,
        opened_bars=bars,
        minute_status=status,
    )
    terminal_digest = bars[-1].prefix_digest
    entry_scan_digest = _canonical_json_sha256(
        {
            "candidate_key_sha256": order.candidate_key.sha256,
            "frozen_order_digest": order.frozen_order_digest,
            "opened_bar_transitions": [bar.bar_transition for bar in bars],
            "opened_provable_strict_cross_volume_shares": [
                bar.provable_strict_cross_volume_shares for bar in bars
            ],
            "opened_key_sha256": list(opened_hashes),
            "status": status,
            "terminal_digest": terminal_digest,
            "projection": "V30_LAZY_0930_0937_ENTRY_SCAN_V2",
        }
    )
    settlement_digest = _canonical_json_sha256(
        {
            "candidate_key_sha256": order.candidate_key.sha256,
            "counterfactual_proxy_fill_proved": accepted,
            "entry_evidence_accepted": accepted,
            "entry_scan_digest": entry_scan_digest,
            "entry_status": status,
            "fill_tick": int(fill_tick) if fill_tick is not None else None,
            "cancel_at": cancel_at.isoformat() if cancel_at is not None else None,
            "frozen_order_digest": order.frozen_order_digest,
            "h0_audit_digest": h0_audit.audit_digest,
            "h0_permitted_projection_sha256": (
                h0_audit.permitted_projection_sha256
            ),
            "projection": "V30_ENTRY_SETTLEMENT_CHAIN_V3",
        }
    )
    return EntrySettlementEvidence(
        candidate_key=order.candidate_key,
        order=order,
        opened_bars=tuple(bars),
        opened_key_sha256=opened_hashes,
        h0_audit=h0_audit,
        entry_scan_digest=entry_scan_digest,
        entry_hard_valid=True,
        entry_status=status,
        entry_evidence_accepted=accepted,
        fill_tick=fill_tick,
        cancel_at=cancel_at,
        counterfactual_proxy_fill_proved=accepted,
        settlement_digest=settlement_digest,
    )


def evaluate_entry_order_execution(
    order: FrozenEntryOrder,
    bar_loader: Callable[[pd.Timestamp], Mapping[str, Any]],
    h0_audit_loader: Callable[[pd.Timestamp], Mapping[str, Any]],
) -> EntrySettlementEvidence:
    """Finish the lazy minute scan, then open exactly one 15:00 H0 audit row."""
    order = validate_frozen_order(order)
    if not order.entry_hard_valid:
        raise V30StageAError("resolved no-order row cannot open entry evidence")
    bars: list[QD004EntryBar] = []
    hashes: list[str] = []
    prefix = _initial_entry_prefix_digest(order)
    for time_text in ENTRY_SCAN_BAR_END_TIMES:
        expected_end = pd.Timestamp(f"{order.candidate_key.entry_date.date()} {time_text}:00")
        row = bar_loader(expected_end)
        if not isinstance(row, Mapping):
            raise V30StageAError("QD004 entry reader did not return one keyed projection")
        raw_count = _required(row, "source_match_count", "QD004 entry key")
        if isinstance(raw_count, (bool, np.bool_)) or not isinstance(
            raw_count, (int, np.integer)
        ):
            raise V30StageAError("QD004 entry key match count is unknown")
        count = int(raw_count)
        if count not in {0, 1}:
            raise V30StageAError("QD004 entry scaffold is duplicate or unknown")
        if count == 0:
            _zero_scaffold_hash(row, order=order, expected_end=expected_end)
            raise V30StageAError("reached QD004 minute key is absent")
        bar = validate_qd004_entry_bar(
            row,
            order=order,
            expected_bar_end_time=expected_end,
            prior_prefix_digest=prefix,
        )
        if bar.physical_source_locator in {
            item.physical_source_locator for item in bars
        }:
            raise V30StageAError("QD004 entry prefix contains a duplicate locator")
        bars.append(bar)
        hashes.append(bar.row_sha256)
        prefix = bar.prefix_digest
        if (
            bar.provable_strict_cross_volume_shares >= MIN_PROXY_VOLUME_SHARES
            and bar.bar_transition == "FULL_PROXY_PROVED"
        ):
            minute_status = _terminal_minute_outcome(order, bars)[3]
            audit_at = pd.Timestamp(
                f"{order.candidate_key.entry_date.date()} {TERMINAL_AUDIT_TIME}"
            )
            audit_row = h0_audit_loader(audit_at)
            audit = validate_cy033_h0_terminal_audit(
                audit_row,
                order=order,
                opened_bars=bars,
                minute_status=minute_status,
            )
            return _build_entry_settlement(order, bars, hashes, audit)
    minute_status = _terminal_minute_outcome(order, bars)[3]
    audit_at = pd.Timestamp(
        f"{order.candidate_key.entry_date.date()} {TERMINAL_AUDIT_TIME}"
    )
    audit_row = h0_audit_loader(audit_at)
    audit = validate_cy033_h0_terminal_audit(
        audit_row,
        order=order,
        opened_bars=bars,
        minute_status=minute_status,
    )
    return _build_entry_settlement(order, bars, hashes, audit)


def derive_gap_day_raw_l_tick(gap: Mapping[str, Any], gap_day: Mapping[str, Any]) -> np.int64:
    """Persist the authoritative source gap-day high as an exact int64 cent."""
    gap_date = _normalized_date(_required(gap, "gap_date", "gap"), "gap date")
    row_date = _normalized_date(
        _required(gap_day, "trade_date", "gap day"), "gap-day trade_date"
    )
    if gap_date != row_date or str(_required(gap, "symbol", "gap")) != str(
        _required(gap_day, "symbol", "gap day")
    ):
        raise V30StageAError("gap-day identity mismatch")
    high_tick = _daily_source_price_tick(gap_day, "high", "gap day")
    return np.int64(high_tick)


def legacy_raw_l_audit(
    gap: Mapping[str, Any], authoritative_raw_l_tick: Any
) -> dict[str, Any]:
    """Describe legacy L/factor without letting it authorize or reject a row."""
    try:
        boundary = _positive_decimal(_required(gap, "L", "gap"), "legacy L")
        factor = _positive_decimal(
            _required(gap, "coordinate_factor", "gap"), "legacy coordinate_factor"
        )
        raw = boundary / factor
        return {
            "legacy_l_over_factor_decimal": format(raw, "f"),
            "legacy_l_over_factor_matches_raw_l_tick": (
                raw * 100 == Decimal(int(authoritative_raw_l_tick))
            ),
            "legacy_l_over_factor_status": "NON_AUTHORITATIVE_AUDIT_ONLY",
        }
    except (V30StageAError, InvalidOperation, ZeroDivisionError):
        return {
            "legacy_l_over_factor_decimal": None,
            "legacy_l_over_factor_matches_raw_l_tick": None,
            "legacy_l_over_factor_status": "NON_AUTHORITATIVE_AUDIT_UNKNOWN",
        }


def _strict_daily_ohlc(row: Mapping[str, Any], label: str) -> dict[str, np.int64]:
    ticks = {
        field: _daily_source_price_tick(row, field, label)
        for field in ("open", "high", "low", "close")
    }
    if (
        int(ticks["high"]) < max(int(ticks["open"]), int(ticks["close"]))
        or int(ticks["low"]) > min(int(ticks["open"]), int(ticks["close"]))
        or int(ticks["low"]) > int(ticks["high"])
    ):
        raise V30StageAError(f"{label} strict-cent OHLC geometry is invalid")
    return ticks


def _strict_history_state(
    frame: pd.DataFrame, *, asof: pd.Timestamp, label: str, protocol_arm: str
) -> None:
    for index, row in frame.iterrows():
        if not strict_row_lineage_valid(row, asof, protocol_arm=protocol_arm):
            raise V30StageAError(f"{label} lineage is unknown at row {index}")


def _strict_one_price_limit_down(row: Mapping[str, Any], label: str) -> bool:
    ticks = _strict_daily_ohlc(row, label)
    down_tick = _daily_source_price_tick(row, "down_limit_price", label)
    return all(int(tick) == int(down_tick) for tick in ticks.values())


def _exact_amount_feature(
    group: pd.DataFrame,
    current_index: int,
    signal_time: pd.Timestamp,
    *,
    protocol_arm: str,
) -> tuple[dict[str, Any], list[int]]:
    before = group.iloc[:current_index]
    selected_indices: list[int] = []
    used_indices: list[int] = []
    for index in reversed(before.index.tolist()):
        status = before.loc[index, "trade_status"]
        if (
            isinstance(status, (bool, np.bool_))
            or not isinstance(status, (int, np.integer))
            or int(status) not in (0, 1)
        ):
            raise V30StageAError("prior20 trading state contains an unknown row")
        used_indices.append(int(index))
        if int(status) == 1:
            selected_indices.append(int(index))
            if len(selected_indices) == PRIOR_WINDOW:
                break
    selected_indices.reverse()
    used_indices = sorted(used_indices)
    traded = group.loc[selected_indices]
    if len(traded) != PRIOR_WINDOW:
        raise V30StageAError(
            "prior20 amount history is incomplete; missing denominator is UNKNOWN"
        )
    start_date = traded.trade_date.iloc[0]
    between = before.loc[before.trade_date.ge(start_date)]
    used_indices = sorted(set(used_indices) | set(between.index.astype(int)))
    unknown = int((~between.trade_status.isin([0, 1])).sum())
    if unknown:
        raise V30StageAError("prior20 trading state contains unknown rows")
    _strict_history_state(
        traded,
        asof=signal_time,
        label="prior20 amount history",
        protocol_arm=protocol_arm,
    )
    _strict_history_state(
        between,
        asof=signal_time,
        label="prior20 calendar span",
        protocol_arm=protocol_arm,
    )
    amounts = sorted(
        _positive_decimal(
            _source_float64_decimal_projection(
                row.amount,
                row.amount_source_float64_bits,
                f"prior20 amount row {index}",
            )["typed_exact_decimal"],
            f"prior20 amount row {index}",
        )
        for index, row in traded.iterrows()
    )
    median = (amounts[9] + amounts[10]) / 2
    return (
        {
            "prior20_completed_trading_sessions": PRIOR_WINDOW,
            "prior20_unknown_trading_state_rows": 0,
            "prior20_amount_history_complete": True,
            "prior20_median_amount_exact": format(median, "f"),
        },
        used_indices,
    )


def _cy033_raw_share_volume(
    value: Any, raw_bits: Any, label: str
) -> tuple[int, str, str]:
    projection = _source_float64_decimal_projection(
        value, raw_bits, label, integral=True
    )
    exact = Decimal(projection["typed_exact_decimal"])
    if (
        exact < 0
        or exact != exact.to_integral_value()
        or exact > 2**53
        or exact > np.iinfo(np.int64).max
    ):
        raise V30StageAError(f"{label} is not exact nonnegative raw shares")
    return (
        int(exact),
        str(projection["source_float64_bits_le_hex"]),
        format(exact, "f"),
    )


def _share_coordinate_unchanged(row: Mapping[str, Any], label: str) -> bool:
    blocking = _required(row, "corporate_action_blocking", label)
    if not isinstance(blocking, (bool, np.bool_)):
        raise V30StageAError(f"{label} action blocking flag is unknown")
    if bool(blocking):
        raise V30StageAError(f"{label} has unresolved coordinate action")
    count = _required(row, "corporate_action_count", label)
    if isinstance(count, (bool, np.bool_)) or not isinstance(count, (int, np.integer)):
        raise V30StageAError(f"{label} action count is not exact integer")
    if int(count) < 0:
        raise V30StageAError(f"{label} action count is negative")
    multiplier = _positive_decimal(
        _source_float64_decimal_projection(
            _required(row, "share_multiplier", label),
            _required(row, "share_multiplier_source_float64_bits", label),
            f"{label} share multiplier",
        )["typed_exact_decimal"],
        f"{label} share multiplier",
    )
    if int(count) == 0 and multiplier != 1:
        raise V30StageAError(f"{label} zero-count action conflicts with multiplier")
    return multiplier == 1


def _exact_share_volume_feature(
    group: pd.DataFrame,
    current_index: int,
    signal_time: pd.Timestamp,
    *,
    protocol_arm: str,
) -> tuple[dict[str, Any], list[int]]:
    """Fallback-only complete prior20 raw-share median and exact comparison."""
    before = group.iloc[:current_index]
    selected_indices: list[int] = []
    used_indices: list[int] = []
    for index in reversed(before.index.tolist()):
        status = before.loc[index, "trade_status"]
        if (
            isinstance(status, (bool, np.bool_))
            or not isinstance(status, (int, np.integer))
            or int(status) not in (0, 1)
        ):
            raise V30StageAError("prior20 share-volume trading state is unknown")
        used_indices.append(int(index))
        if int(status) == 1:
            selected_indices.append(int(index))
            if len(selected_indices) == PRIOR_WINDOW:
                break
    selected_indices.reverse()
    if len(selected_indices) != PRIOR_WINDOW:
        raise V30StageAError("prior20 share-volume history is incomplete")
    traded = group.loc[selected_indices]
    start_date = traded.trade_date.iloc[0]
    between = before.loc[before.trade_date.ge(start_date)]
    used_indices = sorted(set(used_indices) | set(between.index.astype(int)))
    _strict_history_state(
        traded,
        asof=signal_time,
        label="prior20 share-volume history",
        protocol_arm=protocol_arm,
    )
    _strict_history_state(
        between,
        asof=signal_time,
        label="prior20 share-volume span",
        protocol_arm=protocol_arm,
    )
    coordinate_unchanged = all(
        _share_coordinate_unchanged(row, f"prior20 share-volume row {index}")
        for index, row in between.iterrows()
    )
    volumes = sorted(
        _cy033_raw_share_volume(
            row.volume,
            row.volume_source_float64_bits,
            f"prior20 share volume row {index}",
        )[0]
        for index, row in traded.iterrows()
    )
    numerator = volumes[9] + volumes[10]
    denominator = 2
    current = group.loc[current_index]
    signal_shares, signal_bits, signal_exact = _cy033_raw_share_volume(
        current.volume,
        current.volume_source_float64_bits,
        "signal raw share volume",
    )
    median_positive = numerator > 0
    comparison = bool(
        coordinate_unchanged
        and median_positive
        and signal_shares * denominator >= numerator
    )
    return (
        {
            "signal_raw_share_volume_exact": signal_exact,
            "signal_raw_share_volume_float64_bits": signal_bits,
            "prior20_raw_share_volume_median_numerator": np.int64(numerator),
            "prior20_raw_share_volume_median_denominator": np.int64(denominator),
            "prior20_share_volume_history_complete": True,
            "prior20_share_coordinate_unchanged": coordinate_unchanged,
            "prior20_share_volume_median_positive": median_positive,
            "signal_share_volume_ge_prior20_median": comparison,
        },
        used_indices,
    )


def evaluate_v30_signal_bar(
    gap: pd.Series,
    group: pd.DataFrame,
    gap_index: int,
    current_index: int,
    *,
    raw_l_tick: Any,
    protocol_arm: Any,
) -> tuple[dict[str, Any], dict[str, list[int]]]:
    """Evaluate V29R4-minus-R5 using only strict raw-cent price gates."""
    arm = _require_nonempty_exact_string(protocol_arm, "signal evaluation arm")
    if arm not in SIGNAL_ARMS:
        raise V30StageAError("signal evaluation arm is not frozen")
    require_share_volume_fallback = arm == SHARE_VOLUME_FALLBACK_ARM
    boundary_tick = int(_require_int64_tick(raw_l_tick, "authoritative raw_l_tick"))
    if current_index <= gap_index or current_index >= len(group):
        raise V30StageAError("signal index is outside the post-gap path")
    current = group.loc[current_index]
    previous = group.loc[current_index - 1]
    signal_time = _local_naive_timestamp(current.decision_at, "signal decision_at")
    path = group.loc[gap_index + 1 : current_index]
    rolling20 = group.loc[current_index - 19 : current_index]
    prior20 = group.loc[current_index - PRIOR_WINDOW : current_index - 1]
    roles = {
        "V30_ROLLING20": list(rolling20.index.astype(int)),
        "V30_PRIOR20_LIMIT": list(prior20.index.astype(int)),
        "RECLAIMED_PIVOT": [int(current_index - 1)],
        "SIGNAL_BAR": [int(current_index)],
    }
    if len(rolling20) != PRIOR_WINDOW or len(prior20) != PRIOR_WINDOW or path.empty:
        raise V30StageAError("strict price/history window is incomplete")
    _strict_history_state(
        path,
        asof=signal_time,
        label="post-gap price path",
        protocol_arm=arm,
    )
    _strict_history_state(
        rolling20,
        asof=signal_time,
        label="rolling20 price path",
        protocol_arm=arm,
    )
    coordinate_indices = sorted(
        set(path.index.astype(int)) | set(rolling20.index.astype(int))
    )
    coordinate_action_free = all(
        strict_action_free_status(group.loc[index], f"coordinate row {index}")
        for index in coordinate_indices
    )
    path_ticks = [
        _strict_daily_ohlc(row, f"post-gap row {index}")
        for index, row in path.iterrows()
    ]
    rolling_ticks = [
        _strict_daily_ohlc(row, f"rolling20 row {index}")
        for index, row in rolling20.iterrows()
    ]
    current_ticks = rolling_ticks[-1]
    previous_ticks = _strict_daily_ohlc(previous, "previous signal row")
    path_low_ticks = [int(item["low"]) for item in path_ticks]
    if any(int(item["high"]) >= boundary_tick for item in path_ticks):
        raise V30StageAError("post-gap path touched or crossed raw L before admission")
    rolling_low_ticks = [int(item["low"]) for item in rolling_ticks]
    post_gap_low_tick = min(path_low_ticks)
    low20_tick = min(rolling_low_ticks)
    low20_offset = max(
        index for index, tick in enumerate(rolling_low_ticks) if tick == low20_tick
    )
    days_since_low20 = len(rolling20) - 1 - low20_offset
    close_tick = int(current_ticks["close"])
    max_depth = Decimal(boundary_tick - post_gap_low_tick) / Decimal(boundary_tick)
    current_depth = Decimal(boundary_tick - close_tick) / Decimal(boundary_tick)
    recovery = Decimal(close_tick - low20_tick) / Decimal(low20_tick)
    rebound_numerator = close_tick - post_gap_low_tick
    rebound = Decimal(rebound_numerator) / Decimal(boundary_tick)
    prior_high_break = close_tick > int(previous_ticks["high"])

    v13_gate = bool(
        coordinate_action_free
        and (boundary_tick - post_gap_low_tick) * 100 >= 10 * boundary_tick
        and (boundary_tick - close_tick) * 100 >= 5 * boundary_tick
        and MIN_LOW20_AGE <= days_since_low20 <= MAX_LOW20_AGE
        and close_tick * 100 >= 103 * low20_tick
        and prior_high_break
    )
    gap_age = int(current_index - gap_index)
    pre_peak_to_gap = gap.pre_peak_to_gap_sessions
    if (
        isinstance(pre_peak_to_gap, (bool, np.bool_))
        or not isinstance(pre_peak_to_gap, (int, np.integer))
    ):
        raise V30StageAError("pre-peak-to-gap session count is not an integer")
    v27_without_r5 = bool(
        v13_gate
        and int(pre_peak_to_gap) >= MIN_PRIOR_PEAK_TO_GAP
        and MIN_GAP_AGE <= gap_age <= MAX_GAP_AGE
    )

    if not strict_row_lineage_valid(current, signal_time, protocol_arm=arm):
        raise V30StageAError("current signal lineage is unknown")
    if not isinstance(current.current_day_data_tradable, (bool, np.bool_)):
        raise V30StageAError("current tradable state is unknown")
    if not isinstance(current.is_st, (bool, np.bool_)):
        raise V30StageAError("current ST state is unknown")
    trade_status = current.trade_status
    if (
        isinstance(trade_status, (bool, np.bool_))
        or not isinstance(trade_status, (int, np.integer))
        or int(trade_status) not in (0, 1)
    ):
        raise V30StageAError("current trade status is unknown")
    current_action_free = strict_action_free_status(current, "current signal row")
    if not _nonempty(current.industry):
        raise V30StageAError("signal industry identity is missing")
    current_state = bool(
        current.current_day_data_tradable
        and int(current.trade_status) == 1
        and not bool(current.is_st)
        and current_action_free
    )
    _strict_history_state(
        prior20,
        asof=signal_time,
        label="prior20 limit history",
        protocol_arm=arm,
    )
    prior_limit_count = sum(
        _strict_one_price_limit_down(row, f"prior20 limit row {index}")
        for index, row in prior20.iterrows()
    )
    state_without_r5 = bool(
        v27_without_r5
        and current_state
        and prior_limit_count <= MAX_PRIOR_ONE_PRICE_LIMIT_DOWNS
    )
    up_limit_tick = _daily_source_price_tick(current, "up_limit_price", "signal")
    unlocked_without_r5 = bool(state_without_r5 and close_tick < int(up_limit_tick))

    amount_feature, amount_indices = _exact_amount_feature(
        group, current_index, signal_time, protocol_arm=arm
    )
    roles["V30_PRIOR20_AMOUNT"] = amount_indices
    signal_amount_projection = _source_float64_decimal_projection(
        current.amount,
        current.amount_source_float64_bits,
        "signal amount",
    )
    signal_amount = _nonnegative_decimal(
        signal_amount_projection["typed_exact_decimal"], "signal amount"
    )
    median_text = amount_feature["prior20_median_amount_exact"]
    median = Decimal(median_text) if median_text is not None else None
    amount_ratio = signal_amount / median if median is not None else None
    fallback_amount_base_gate = bool(
        unlocked_without_r5
        and signal_amount > 0
        and amount_feature["prior20_amount_history_complete"]
        and median is not None
        and signal_amount <= MAX_SIGNAL_AMOUNT_TO_PRIOR_MEDIAN * median
    )
    amount_gate = bool(
        fallback_amount_base_gate
        and median is not None
        and signal_amount >= MIN_VOLUME_SIGNAL_AMOUNT_TO_PRIOR_MEDIAN * median
    )
    share_feature: dict[str, Any] = {
        "signal_raw_share_volume_exact": None,
        "signal_raw_share_volume_float64_bits": None,
        "prior20_raw_share_volume_median_numerator": None,
        "prior20_raw_share_volume_median_denominator": None,
        "prior20_share_volume_history_complete": False,
        "prior20_share_coordinate_unchanged": None,
        "prior20_share_volume_median_positive": None,
        "signal_share_volume_ge_prior20_median": None,
    }
    share_feature_status = "NOT_REQUIRED_OR_NOT_OPENED"
    if require_share_volume_fallback:
        try:
            share_feature, share_indices = _exact_share_volume_feature(
                group, current_index, signal_time, protocol_arm=arm
            )
            roles["V30_PRIOR20_SHARE_VOLUME"] = share_indices
            share_feature_status = "COMPLETE"
        except V30StageAError as exc:
            share_feature_status = f"UNKNOWN:{exc}"
    fallback_gate = bool(
        fallback_amount_base_gate
        and share_feature_status == "COMPLETE"
        and share_feature["signal_share_volume_ge_prior20_median"] is True
    )
    record = {
        "gap_age": gap_age,
        "signal_date": _normalized_date(current.trade_date, "signal trade_date"),
        "signal_time": signal_time,
        "max_depth": max_depth,
        "current_depth": current_depth,
        "rebound_from_post_gap_low_over_l": rebound,
        "rebound_tick_numerator": np.int64(rebound_numerator),
        "rebound_tick_denominator": np.int64(boundary_tick),
        "days_since_low20": days_since_low20,
        "low20_raw_tick": np.int64(low20_tick),
        "recovery_from_low20": recovery,
        "coordinate_window_action_free": coordinate_action_free,
        "prior_high_raw_tick_break": prior_high_break,
        "reclaimed_pivot_tick": np.int64(previous_ticks["high"]),
        "reclaimed_pivot_source_trade_date": _normalized_date(
            previous.trade_date, "reclaimed pivot trade_date"
        ),
        "reclaimed_pivot_snapshot_id": previous.snapshot_id,
        "reclaimed_pivot_daily_snapshot_id": previous.daily_snapshot_id,
        "v13_prior_high_reversal_gate": v13_gate,
        "v27_without_r5_gate": v27_without_r5,
        "prior20_one_price_limit_down_count": prior_limit_count,
        "v28_prior20_history_valid": True,
        "v28_state_without_r5_gate": state_without_r5,
        "v28r1_unlocked_without_r5_gate": unlocked_without_r5,
        "signal_raw_close_tick": np.int64(close_tick),
        "signal_raw_close_source_float64_bits": current.close_source_float64_bits,
        "signal_daily_permitted_projection_sha256": (
            current.permitted_projection_sha256
        ),
        "signal_up_limit_tick": np.int64(up_limit_tick),
        "signal_raw_amount_exact": format(signal_amount, "f"),
        "signal_raw_amount_source_float64_bits": (
            current.amount_source_float64_bits
        ),
        **amount_feature,
        "signal_amount_to_prior20_median": (
            format(amount_ratio, "f") if amount_ratio is not None else None
        ),
        **share_feature,
        "v30_fallback_amount_base_gate": fallback_amount_base_gate,
        "v30_share_volume_feature_status": share_feature_status,
        "v30_share_volume_fallback_gate": fallback_gate,
        "v30_amount_gate": amount_gate,
        "r5_used_for_signal_admission": False,
        "amount_lower_bound_used_by_fallback": False,
        "amount_lower_bound_used_by_amount_arm": True,
        "signal_industry": current.industry,
        "signal_available_at": current.available_at,
        "signal_decision_at": current.decision_at,
        "signal_snapshot_id": current.snapshot_id,
        "signal_daily_snapshot_id": current.daily_snapshot_id,
        "signal_trading_state_snapshot_id": current.trading_state_snapshot_id,
        "signal_industry_snapshot_id": current.industry_snapshot_id,
        "signal_corporate_action_snapshot_id": current.corporate_action_snapshot_id,
        "signal_feature_uses_post_signal_information": False,
        "raw_price_gate_arithmetic": "INT64_CENTS_AND_DECIMAL_ONLY",
    }
    return record, roles


def _capture_signal(
    gap: pd.Series,
    record: Mapping[str, Any],
    *,
    protocol_arm: str,
    raw_l_tick: np.int64,
) -> dict[str, Any]:
    if protocol_arm == AMOUNT_ARM:
        fallback_fields: dict[str, Any] = {
            "signal_raw_share_volume_exact": None,
            "signal_raw_share_volume_float64_bits": None,
            "prior20_raw_share_volume_median_numerator": None,
            "prior20_raw_share_volume_median_denominator": None,
            "signal_share_volume_ge_prior20_median": None,
        }
    elif protocol_arm == SHARE_VOLUME_FALLBACK_ARM:
        fallback_fields = {
            name: record[name]
            for name in (
                "signal_raw_share_volume_exact",
                "signal_raw_share_volume_float64_bits",
                "prior20_raw_share_volume_median_numerator",
                "prior20_raw_share_volume_median_denominator",
                "signal_share_volume_ge_prior20_median",
            )
        }
        if (
            any(value is None for value in fallback_fields.values())
            or fallback_fields["signal_share_volume_ge_prior20_median"] is not True
        ):
            raise V30StageAError("fallback signal lacks its exact share-volume proof")
    else:
        raise V30StageAError("signal capture arm is not frozen")
    combined = {
        **gap.to_dict(),
        **dict(record),
        **legacy_raw_l_audit(gap, raw_l_tick),
        "protocol_arm": protocol_arm,
        "raw_l_tick": np.int64(raw_l_tick),
        **fallback_fields,
        "cap25_rank": None,
    }
    missing = [column for column in SIGNAL_OUTPUT_COLUMNS if column not in combined]
    if missing:
        raise V30StageAError(f"signal output lacks exact fields: {missing}")
    return {column: combined[column] for column in SIGNAL_OUTPUT_COLUMNS}


def _signal_lineage_frame(
    gap: pd.Series,
    group: pd.DataFrame,
    accessed: Mapping[int, set[str]],
    *,
    protocol_arm: str,
) -> pd.DataFrame:
    arm = _require_nonempty_exact_string(protocol_arm, "signal lineage arm")
    if arm not in SIGNAL_ARMS:
        raise V30StageAError("signal lineage arm is not frozen")
    role_columns = {
        "GAP_DAY_RAW_L_AUTHORITY": "role_gap_day_raw_l_authority",
        "GAP_IDENTITY": "role_gap_identity",
        "POST_GAP_PATH": "role_post_gap_path",
        "V30_ROLLING20": "role_rolling20",
        "V30_PRIOR20_LIMIT": "role_prior20_limit",
        "V30_PRIOR20_AMOUNT": "role_prior20_amount",
        "V30_PRIOR20_SHARE_VOLUME": "role_prior20_share_volume",
        "RECLAIMED_PIVOT": "role_reclaimed_pivot",
        "SIGNAL_BAR": "role_signal_bar",
    }
    rows: list[dict[str, Any]] = []
    for index in sorted(accessed):
        row = group.loc[index]
        roles = accessed[index]
        unknown_roles = set(roles) - set(role_columns)
        if unknown_roles:
            raise V30StageAError(f"unknown signal lineage roles: {unknown_roles}")
        permitted_projection_sha256 = _require_sha256(
            row.permitted_projection_sha256,
            f"signal lineage row {index} permitted projection",
        )
        if permitted_projection_sha256 != cy033_daily_permitted_projection_sha256(
            row, protocol_arm=arm
        ):
            raise V30StageAError("signal lineage row permitted projection drift")
        rows.append(
            {
                "protocol_arm": arm,
                "gap_id": str(gap.gap_id),
                "symbol": str(gap.symbol),
                "source_trade_date": _normalized_date(
                    row.trade_date, "lineage source trade_date"
                ),
                "lineage_roles": "|".join(sorted(roles)),
                "decision_at": row.get("decision_at"),
                "available_at": row.get("available_at"),
                "snapshot_id": row.get("snapshot_id"),
                "daily_snapshot_id": row.get("daily_snapshot_id"),
                "trading_state_snapshot_id": row.get("trading_state_snapshot_id"),
                "industry_snapshot_id": row.get("industry_snapshot_id"),
                "corporate_action_snapshot_id": row.get(
                    "corporate_action_snapshot_id"
                ),
                "permitted_projection_sha256": permitted_projection_sha256,
                **{column: role in roles for role, column in role_columns.items()},
            }
        )
    result = pd.DataFrame.from_records(
        rows, columns=SIGNAL_DAILY_LINEAGE_OUTPUT_COLUMNS
    )
    if not result.empty and result.duplicated(
        ["protocol_arm", "gap_id", "source_trade_date"]
    ).any():
        raise V30StageAError("signal daily lineage identity does not conserve")
    return result


def select_first_v30_signal_for_gap(
    gap: pd.Series,
    symbol_daily: pd.DataFrame,
    *,
    protocol_arm: str,
) -> tuple[dict[str, Any] | None, dict[str, Any], pd.DataFrame]:
    """Scan exactly one arm; the sibling arm is neither decoded nor produced."""
    arm = _require_nonempty_exact_string(protocol_arm, "first-only signal arm")
    if arm not in SIGNAL_ARMS:
        raise V30StageAError("first-only signal arm is not frozen")
    requires_share_volume = arm == SHARE_VOLUME_FALLBACK_ARM
    gap_date = pd.Timestamp(gap.gap_date).normalize()
    if gap_date < DEVELOPMENT_START:
        return (
            None,
            {
                "protocol_arm": arm,
                "gap_id": str(gap.gap_id),
                "raw_l_tick": None,
                "bars_scanned": 0,
                "selected": False,
                "terminal_status": "GAP_BEFORE_CY033_BOUND",
            },
            pd.DataFrame(columns=SIGNAL_DAILY_LINEAGE_OUTPUT_COLUMNS),
        )
    group = symbol_daily.sort_values("trade_date", kind="mergesort").reset_index(drop=True)
    group.index = np.arange(len(group), dtype=int)
    matches = group.index[pd.to_datetime(group.trade_date).dt.normalize().eq(gap_date)].tolist()
    if len(matches) != 1:
        raise V30StageAError("missing or duplicate gap date")
    gap_index = int(matches[0])
    gap_row = group.loc[gap_index]
    gap_asof = _local_naive_timestamp(gap_row.decision_at, "gap-day decision_at")
    if not strict_row_lineage_valid(gap_row, gap_asof, protocol_arm=arm):
        raise V30StageAError("gap-day lineage state is invalid")
    raw_l_tick = derive_gap_day_raw_l_tick(gap, gap_row)
    _strict_daily_ohlc(gap_row, "gap-day row")
    if not strict_action_free_status(gap_row, "gap-day row"):
        accessed = {gap_index: {"GAP_DAY_RAW_L_AUTHORITY", "GAP_IDENTITY"}}
        return (
            None,
            {
                "protocol_arm": arm,
                "gap_id": str(gap.gap_id),
                "raw_l_tick": int(raw_l_tick),
                "bars_scanned": 0,
                "selected": False,
                "terminal_status": "GAP_ACTION_COORDINATE_BARRIER",
            },
            _signal_lineage_frame(gap, group, accessed, protocol_arm=arm),
        )

    selected: dict[str, Any] | None = None
    accessed: dict[int, set[str]] = {
        gap_index: {"GAP_DAY_RAW_L_AUTHORITY", "GAP_IDENTITY"}
    }
    audit: dict[str, Any] = {
        "protocol_arm": arm,
        "gap_id": str(gap.gap_id),
        "raw_l_tick": int(raw_l_tick),
        "bars_scanned": 0,
        "selected": False,
        "terminal_status": "EXHAUSTED_WITHOUT_SIGNAL",
    }
    stop = min(len(group), gap_index + MAX_GAP_AGE + 1)
    for current_index in range(gap_index + 1, stop):
        current = group.loc[current_index]
        audit["bars_scanned"] += 1
        accessed.setdefault(current_index, set()).add("POST_GAP_PATH")
        current_asof = _local_naive_timestamp(
            current.decision_at, "post-gap decision_at"
        )
        if not strict_row_lineage_valid(
            current, current_asof, protocol_arm=arm
        ):
            raise V30StageAError("post-gap daily lineage break")
        if not strict_action_free_status(current, f"post-gap row {current_index}"):
            audit["terminal_status"] = "ACTION_COORDINATE_BARRIER"
            break
        current_ticks = _strict_daily_ohlc(current, f"post-gap scan row {current_index}")
        if int(current_ticks["high"]) >= int(raw_l_tick):
            audit["terminal_status"] = "L_TOUCHED_BEFORE_SIGNAL"
            break
        gap_age = current_index - gap_index
        if gap_age < MIN_GAP_AGE:
            continue
        if current_index < PRIOR_WINDOW:
            raise V30StageAError("prior20 signal window is incomplete")
        record, roles = evaluate_v30_signal_bar(
            gap,
            group,
            gap_index,
            current_index,
            raw_l_tick=raw_l_tick,
            protocol_arm=arm,
        )
        for role, indices in roles.items():
            for index in indices:
                accessed.setdefault(int(index), set()).add(role)
        if (
            requires_share_volume
            and record["v30_fallback_amount_base_gate"]
            and str(record["v30_share_volume_feature_status"]).startswith("UNKNOWN:")
        ):
            raise V30StageAError("fallback first-only share-volume evidence is UNKNOWN")
        gate = (
            record["v30_share_volume_fallback_gate"]
            if requires_share_volume
            else record["v30_amount_gate"]
        )
        if gate:
            selected = _capture_signal(
                gap, record, protocol_arm=arm, raw_l_tick=raw_l_tick
            )
            audit["selected"] = True
            audit["signal_date"] = record["signal_date"]
            audit["terminal_status"] = "FIRST_SIGNAL_SELECTED"
            break
    lineage = _signal_lineage_frame(gap, group, accessed, protocol_arm=arm)
    if selected is not None:
        maximum = lineage.loc[lineage.protocol_arm.eq(arm), "source_trade_date"].max()
        if maximum > pd.Timestamp(selected["signal_date"]).normalize():
            raise V30StageAError("arm lineage crossed its first-only signal boundary")
    return selected, audit, lineage


def build_v30_signal_cohort(
    parent_gaps: pd.DataFrame,
    daily: pd.DataFrame,
    *,
    protocol_arm: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Materialize exactly one arm; callers enforce the lazy arm sequence."""
    arm = _require_nonempty_exact_string(protocol_arm, "signal cohort arm")
    if arm not in SIGNAL_ARMS:
        raise V30StageAError("signal cohort arm is not frozen")
    _require_exact_frame_projection(parent_gaps, PARENT_GAP_INPUT_COLUMNS, "parent gaps")
    daily_schema = (
        SHARE_VOLUME_FALLBACK_DAILY_SIGNAL_INPUT_COLUMNS
        if arm == SHARE_VOLUME_FALLBACK_ARM
        else AMOUNT_ARM_DAILY_SIGNAL_INPUT_COLUMNS
    )
    _require_exact_frame_projection(daily, daily_schema, f"{arm} CY033 daily")
    if parent_gaps.gap_id.duplicated().any():
        raise V30StageAError("parent gap cohort is duplicate")
    daily_dates = pd.to_datetime(daily.trade_date, errors="coerce").dt.normalize()
    if (
        daily_dates.isna().any()
        or pd.DataFrame(
            {"symbol": daily.symbol.astype(str), "trade_date": daily_dates}
        ).duplicated().any()
        or daily_dates.gt(DEVELOPMENT_END).any()
    ):
        raise V30StageAError("CY033 daily identity/scope is invalid")
    groups = {
        str(symbol): group.reset_index(drop=True)
        for symbol, group in daily.groupby("symbol", sort=False)
    }
    for symbol in groups:
        canonical_candidate_symbol(symbol)
    signal_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    lineage_frames: list[pd.DataFrame] = []
    for gap_row in parent_gaps.itertuples(index=False):
        gap = pd.Series(gap_row._asdict())
        canonical_candidate_symbol(gap.symbol)
        gap_date = pd.Timestamp(gap.gap_date).normalize()
        group = groups.get(str(gap.symbol))
        if group is None and gap_date >= DEVELOPMENT_START:
            raise V30StageAError("in-scope gap symbol is absent from CY033")
        signal, audit, lineage = select_first_v30_signal_for_gap(
            gap,
            pd.DataFrame() if group is None else group,
            protocol_arm=arm,
        )
        if signal is not None:
            signal_rows.append(signal)
        audit_rows.append(audit)
        if not lineage.empty:
            lineage_frames.append(lineage)
    signal_frame = pd.DataFrame.from_records(signal_rows, columns=SIGNAL_OUTPUT_COLUMNS)
    audit_frame = pd.DataFrame.from_records(audit_rows)
    lineage_frame = (
        pd.concat(lineage_frames, ignore_index=True)
        if lineage_frames
        else pd.DataFrame(columns=SIGNAL_DAILY_LINEAGE_OUTPUT_COLUMNS)
    )
    if len(audit_frame) != len(parent_gaps) or (
        not audit_frame.empty and audit_frame.gap_id.duplicated().any()
    ):
        raise V30StageAError("parent-to-audit identity conservation failed")
    if not signal_frame.empty and (
        signal_frame.gap_id.duplicated().any()
        or not signal_frame.protocol_arm.eq(arm).all()
        or pd.to_datetime(signal_frame.signal_date)
        .dt.normalize()
        .gt(DEVELOPMENT_END)
        .any()
    ):
        raise V30StageAError("single-arm first-only cohort identity failed")
    share_fields = (
        "signal_raw_share_volume_exact",
        "signal_raw_share_volume_float64_bits",
        "prior20_raw_share_volume_median_numerator",
        "prior20_raw_share_volume_median_denominator",
        "signal_share_volume_ge_prior20_median",
    )
    if arm == AMOUNT_ARM and not signal_frame.empty:
        if not signal_frame.loc[:, share_fields].isna().all().all():
            raise V30StageAError("amount arm decoded fallback-only share-volume evidence")
    elif arm == SHARE_VOLUME_FALLBACK_ARM and not signal_frame.empty:
        if (
            signal_frame.loc[:, share_fields].isna().any().any()
            or not signal_frame.signal_share_volume_ge_prior20_median.eq(True).all()
        ):
            raise V30StageAError("fallback arm lacks complete share-volume evidence")
    if not lineage_frame.empty and lineage_frame.duplicated(
        ["protocol_arm", "gap_id", "source_trade_date"]
    ).any():
        raise V30StageAError("batch signal lineage identity failed")
    return signal_frame, audit_frame, lineage_frame


def cap25_industry_round_robin(
    selected: pd.DataFrame, *, protocol_arm: str
) -> CAP25Result:
    """Return an exact selected/excluded ledger for one independent arm."""
    arm = _require_nonempty_exact_string(protocol_arm, "CAP25 protocol arm")
    if arm not in SIGNAL_ARMS:
        raise V30StageAError("CAP25 protocol arm is not frozen")
    _require_exact_frame_projection(selected, SIGNAL_OUTPUT_COLUMNS, "CAP25 input")
    if selected.empty:
        return CAP25Result(
            protocol_arm=arm,
            selected=pd.DataFrame(columns=SIGNAL_OUTPUT_COLUMNS),
            ledger=pd.DataFrame(columns=CAP25_LEDGER_OUTPUT_COLUMNS),
        )
    if selected.gap_id.duplicated().any() or not selected.protocol_arm.eq(arm).all():
        raise V30StageAError("CAP25 input is duplicate or not one exact protocol arm")
    if selected.cap25_rank.notna().any():
        raise V30StageAError("CAP25 input was already ranked")
    for value in selected.gap_id:
        _require_nonempty_exact_string(value, "CAP25 gap identity")
    for value in selected.symbol:
        canonical_candidate_symbol(value)
    for value in selected.signal_industry:
        industry = _require_nonempty_exact_string(value, "CAP25 industry identity")
        if industry.upper() in {"UNKNOWN", "NONE", "NULL", "N/A", "NA"}:
            raise V30StageAError("CAP25 industry identity is unresolved")
    for value in selected.signal_industry_snapshot_id:
        _require_nonempty_exact_string(value, "CAP25 industry snapshot identity")
    work = selected.copy()
    exact_rebounds: list[Fraction] = []
    for numerator_raw, denominator_raw in zip(
        work.rebound_tick_numerator,
        work.rebound_tick_denominator,
        strict=True,
    ):
        if (
            isinstance(numerator_raw, (bool, np.bool_))
            or isinstance(denominator_raw, (bool, np.bool_))
            or not isinstance(numerator_raw, (int, np.integer))
            or not isinstance(denominator_raw, (int, np.integer))
        ):
            raise V30StageAError("CAP25 rebound tick ratio is invalid")
        try:
            numerator = int(numerator_raw)
            denominator = int(denominator_raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise V30StageAError("CAP25 rebound tick ratio is invalid") from exc
        if (
            numerator != numerator_raw
            or denominator != denominator_raw
            or numerator < 0
            or denominator <= 0
            or numerator > np.iinfo(np.int64).max
            or denominator > np.iinfo(np.int64).max
        ):
            raise V30StageAError("CAP25 rebound tick ratio is invalid")
        exact_rebounds.append(Fraction(numerator, denominator))
    work["_exact_rebound_rank"] = exact_rebounds
    work["_gap_date_rank"] = [
        _normalized_date(value, "CAP25 gap_date") for value in work.gap_date
    ]
    work["_signal_date_rank"] = [
        _normalized_date(value, "CAP25 signal_date") for value in work.signal_date
    ]
    dates = work["_signal_date_rank"]
    if (
        dates.lt(DEVELOPMENT_START).any()
        or dates.gt(DEVELOPMENT_END).any()
        or (work["_gap_date_rank"] >= work["_signal_date_rank"]).any()
    ):
        raise V30StageAError("CAP25 signal date is outside development")

    kept: list[pd.DataFrame] = []
    for signal_date in sorted(dates.unique()):
        event = work.loc[dates.eq(signal_date)].copy()
        queues = {
            str(industry): group.sort_values(
                [
                    "_exact_rebound_rank",
                    "symbol",
                    "_gap_date_rank",
                    "_signal_date_rank",
                    "gap_id",
                ],
                ascending=[False, True, True, True, True],
                kind="mergesort",
            ).reset_index(drop=True)
            for industry, group in event.groupby("signal_industry", sort=False)
        }
        industries = sorted(queues, key=lambda value: value.encode("utf-8"))
        positions = {industry: 0 for industry in industries}
        rows: list[pd.Series] = []
        while len(rows) < CAP_PER_SIGNAL_DATE:
            advanced = False
            for industry in industries:
                position = positions[industry]
                if position >= len(queues[industry]):
                    continue
                rows.append(queues[industry].iloc[position])
                positions[industry] += 1
                advanced = True
                if len(rows) == CAP_PER_SIGNAL_DATE:
                    break
            if not advanced:
                break
        frame = pd.DataFrame(rows)
        frame["cap25_rank"] = np.arange(1, len(frame) + 1, dtype=np.int64)
        kept.append(frame)
    result = pd.concat(kept, ignore_index=True)
    result = result.drop(
        columns=["_exact_rebound_rank", "_gap_date_rank", "_signal_date_rank"]
    )
    counts = result.groupby(pd.to_datetime(result.signal_date).dt.normalize()).size()
    if result.gap_id.duplicated().any() or counts.gt(CAP_PER_SIGNAL_DATE).any():
        raise V30StageAError("CAP25 identity/cardinality conservation failed")
    result = result.loc[:, SIGNAL_OUTPUT_COLUMNS].copy()
    rank_by_gap = {
        str(row.gap_id): int(row.cap25_rank) for row in result.itertuples(index=False)
    }
    ledger_rows = []
    for row in selected.itertuples(index=False):
        rank = rank_by_gap.get(str(row.gap_id))
        ledger_rows.append(
            {
                "protocol_arm": arm,
                "gap_id": str(row.gap_id),
                "symbol": str(row.symbol),
                "signal_date": _normalized_date(row.signal_date, "CAP25 ledger date"),
                "cap25_status": "CAP25_SELECTED" if rank is not None else "CAP25_EXCLUDED",
                "cap25_rank": rank,
            }
        )
    ledger = pd.DataFrame.from_records(ledger_rows, columns=CAP25_LEDGER_OUTPUT_COLUMNS)
    if (
        len(ledger) != len(selected)
        or ledger.duplicated(["protocol_arm", "gap_id"]).any()
        or int(ledger.cap25_status.eq("CAP25_SELECTED").sum()) != len(result)
        or int(ledger.cap25_status.eq("CAP25_EXCLUDED").sum()) + len(result)
        != len(selected)
    ):
        raise V30StageAError("CAP25 selected/excluded identity mass does not conserve")
    return CAP25Result(protocol_arm=arm, selected=result, ledger=ledger)


def validate_market_calendar(calendar: pd.DataFrame) -> pd.DataFrame:
    _require_exact_frame_projection(calendar, MARKET_CALENDAR_INPUT_COLUMNS, "market calendar")
    if calendar.empty:
        raise V30StageAError("market calendar is empty or incomplete")
    raw_dates = calendar.trade_date.tolist()
    if any(not isinstance(value, (pd.Timestamp, np.datetime64)) for value in raw_dates):
        raise V30StageAError("market calendar date is not an exact timestamp/date64")
    result = calendar[["trade_date", "calendar_index"]].copy()
    result["trade_date"] = pd.to_datetime(result.trade_date, errors="coerce").dt.normalize()
    raw_indices = result.calendar_index.tolist()
    if any(
        isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer))
        for value in raw_indices
    ):
        raise V30StageAError("market calendar index is not exact integer")
    indices = np.asarray([int(value) for value in raw_indices], dtype=np.int64)
    if (
        result.trade_date.isna().any()
        or result.trade_date.duplicated().any()
        or len(indices) != len(set(indices.tolist()))
    ):
        raise V30StageAError("market calendar identity is unknown or duplicate")
    result["calendar_index"] = indices
    result = result.sort_values("calendar_index", kind="mergesort").reset_index(drop=True)
    if (
        result.calendar_index.tolist() != list(range(len(result)))
        or not result.trade_date.is_monotonic_increasing
        or result.trade_date.duplicated().any()
        or len(result) != FROZEN_CALENDAR_ROW_COUNT
        or result.trade_date.min() != FROZEN_CALENDAR_MIN_DATE
        or result.trade_date.max() != FROZEN_CALENDAR_MAX_DATE
    ):
        raise V30StageAError("market calendar grid is not contiguous bounded development")
    iso_dates = [item.date().isoformat() for item in result.trade_date]
    canonical_digest = _canonical_json_sha256(
        {"dates": iso_dates, "derivation": FROZEN_CALENDAR_DERIVATION}
    )
    newline_digest = hashlib.sha256(
        ("\n".join(iso_dates) + "\n").encode("utf-8")
    ).hexdigest()
    if (
        canonical_digest != FROZEN_CALENDAR_CANONICAL_SHA256
        or newline_digest != FROZEN_CALENDAR_NEWLINE_SHA256
    ):
        raise V30StageAError("market calendar frozen digest mismatch")
    result.attrs["canonical_payload_sha256"] = canonical_digest
    result.attrs["newline_iso_date_sha256"] = newline_digest
    return result


def administrative_bound(signal_date: Any, calendar: pd.DataFrame) -> dict[str, Any]:
    """Map H10/H11..H13 plus an outcome-blind H30 capacity audit bound."""
    cal = validate_market_calendar(calendar)
    date = _normalized_date(signal_date, "administrative signal_date")
    matches = cal.index[cal.trade_date.eq(date)].tolist()
    if len(matches) != 1:
        raise V30StageAError("signal date is absent or duplicate in market calendar")
    signal_index = int(cal.loc[matches[0], "calendar_index"])
    offsets = {
        "entry_date": 1,
        "h10_date": 1 + TARGET_ACTIVE_HORIZON,
        "h11_date": 1 + TIME_EXIT_OFFSETS[0],
        "h12_date": 1 + TIME_EXIT_OFFSETS[1],
        "h13_date": 1 + TIME_EXIT_OFFSETS[2],
        "h30_capacity_audit_date": 1 + CAPACITY_AUDIT_HORIZON,
    }
    result: dict[str, Any] = {
        "signal_calendar_index": signal_index,
        "market_calendar_sha256": str(
            cal.attrs["canonical_payload_sha256"]
        ),
        "admin_eligible": False,
        "admin_status": "RIGHT_CENSORED_2021_ADMINISTRATIVE",
    }
    for name, offset in offsets.items():
        target_index = signal_index + offset
        result[name] = pd.NaT if target_index >= len(cal) else pd.Timestamp(
            cal.loc[target_index, "trade_date"]
        )
    if (
        pd.notna(result["h30_capacity_audit_date"])
        and result["h30_capacity_audit_date"] <= DEVELOPMENT_END
    ):
        result["admin_eligible"] = True
        result["admin_status"] = "ADMIN_ELIGIBLE_H30_CAPACITY_AUDIT_COMPLETE"
    return result


def validate_administrative_candidate(
    row: Mapping[str, Any], *, calendar: pd.DataFrame, candidate_key: CandidateKey
) -> Mapping[str, Any]:
    """Bind the candidate to the frozen calendar's exact next session and H30."""
    _require_exact_projection(row, ADMIN_OUTPUT_COLUMNS, "administrative candidate")
    key = validate_candidate_key(candidate_key)
    computed = administrative_bound(key.signal_date, calendar)
    if (
        row["protocol_arm"] != key.protocol_arm
        or row["gap_id"] != key.gap_id
        or row["symbol"] != key.symbol
        or _normalized_date(row["signal_date"], "admin signal date") != key.signal_date
        or _normalized_date(row["entry_date"], "admin entry date") != key.entry_date
        or row["candidate_key_sha256"] != key.sha256
        or not isinstance(row["admin_eligible"], (bool, np.bool_))
        or not bool(row["admin_eligible"])
        or row["admin_status"] != "ADMIN_ELIGIBLE_H30_CAPACITY_AUDIT_COMPLETE"
    ):
        raise V30StageAError("administrative candidate identity/eligibility failed")
    for field in (
        "signal_calendar_index",
        "entry_date",
        "h10_date",
        "h11_date",
        "h12_date",
        "h13_date",
        "h30_capacity_audit_date",
        "market_calendar_sha256",
        "admin_eligible",
        "admin_status",
    ):
        actual = row[field]
        expected = computed[field]
        if field.endswith("_date"):
            actual = _normalized_date(actual, f"administrative {field}")
            expected = _normalized_date(expected, f"expected administrative {field}")
        if actual != expected:
            raise V30StageAError("administrative calendar binding differs from frozen grid")
    return row


def build_administrative_bounds(
    signals: pd.DataFrame, calendar: pd.DataFrame, *, protocol_arm: str
) -> pd.DataFrame:
    arm = _require_nonempty_exact_string(protocol_arm, "administrative protocol arm")
    if arm not in SIGNAL_ARMS:
        raise V30StageAError("administrative protocol arm is not frozen")
    _require_exact_frame_projection(signals, SIGNAL_OUTPUT_COLUMNS, "administrative signals")
    if signals.empty:
        validate_market_calendar(calendar)
        return pd.DataFrame(columns=ADMIN_OUTPUT_COLUMNS)
    if signals.duplicated(["protocol_arm", "gap_id"]).any():
        raise V30StageAError("administrative signal identity is duplicate")
    if not signals.protocol_arm.eq(arm).all():
        raise V30StageAError("administrative signals are not one expected arm")
    cal = validate_market_calendar(calendar)
    rows: list[dict[str, Any]] = []
    for row in signals.itertuples(index=False):
        bound = administrative_bound(row.signal_date, cal)
        key_digest: str | None = None
        if pd.notna(bound["entry_date"]):
            key_digest = make_candidate_key(
                protocol_arm=arm,
                gap_id=row.gap_id,
                symbol=row.symbol,
                signal_date=row.signal_date,
                entry_date=bound["entry_date"],
            ).sha256
        rows.append(
            {
                "protocol_arm": arm,
                "gap_id": str(row.gap_id),
                "symbol": str(row.symbol),
                "signal_date": _normalized_date(row.signal_date, "admin signal date"),
                **bound,
                "candidate_key_sha256": key_digest,
            }
        )
    result = pd.DataFrame.from_records(rows, columns=ADMIN_OUTPUT_COLUMNS)
    if len(result) != len(signals):
        raise V30StageAError("administrative identity conservation failed")
    return result


def preallocate_order_slots(
    candidates: pd.DataFrame,
    *,
    active_frozen_slots: Sequence[Mapping[str, Any]] = (),
) -> pd.DataFrame:
    """Preallocate one arm/date at 09:14:59 before any entry evidence."""
    _require_exact_frame_projection(candidates, PREALLOCATION_INPUT_COLUMNS, "sample-slot input")
    if candidates.empty:
        return pd.DataFrame(columns=PREALLOCATION_OUTPUT_COLUMNS)
    if candidates.duplicated(list(ARM_CANDIDATE_IDENTITY_COLUMNS)).any():
        raise V30StageAError("sample-slot candidate identity is duplicate")
    work = candidates.copy()
    if any(not _nonempty(value) for value in work.gap_id):
        raise V30StageAError("sample-slot gap identity is empty")
    for value in work.symbol:
        canonical_candidate_symbol(value)
    for column in ("signal_date", "entry_date", "h30_capacity_audit_date"):
        work[column] = pd.to_datetime(work[column], errors="coerce").dt.normalize()
    raw_ranks = work.cap25_rank.tolist()
    if any(
        isinstance(value, (bool, np.bool_))
        or not isinstance(value, (int, np.integer))
        for value in raw_ranks
    ):
        raise V30StageAError("sample-slot CAP25 rank is not an exact integer")
    ranks = pd.Series(
        np.asarray([int(value) for value in raw_ranks], dtype=np.int64),
        index=work.index,
    )
    if (
        work[["signal_date", "entry_date", "h30_capacity_audit_date"]]
        .isna()
        .any()
        .any()
        or ranks.isna().any()
        or (ranks <= 0).any()
        or (ranks > CAP_PER_SIGNAL_DATE).any()
        or ranks.duplicated().any()
        or (work.h30_capacity_audit_date <= work.entry_date).any()
        or (work.signal_date >= work.entry_date).any()
        or work.protocol_arm.nunique() != 1
        or work.entry_date.nunique() != 1
        or not work.protocol_arm.isin(SIGNAL_ARMS).all()
        or not work.preorder_status.eq(PREORDER_ORDER_FROZEN).all()
    ):
        raise V30StageAError("sample-slot input contains unknown or mixed state")
    for row in work.itertuples(index=False):
        key = make_candidate_key(
            protocol_arm=row.protocol_arm,
            gap_id=row.gap_id,
            symbol=row.symbol,
            signal_date=row.signal_date,
            entry_date=row.entry_date,
        )
        if str(row.candidate_key_sha256) != key.sha256:
            raise V30StageAError("sample-slot candidate key digest mismatch")
        for field in ("action_scope_digest", "frozen_order_digest"):
            _require_sha256(getattr(row, field), f"sample-slot {field}")
        if _require_sha256(
            row.market_calendar_sha256, "sample-slot market calendar SHA"
        ) != FROZEN_CALENDAR_CANONICAL_SHA256:
            raise V30StageAError("sample-slot market calendar binding failed")
        decision_at = _local_naive_timestamp(
            row.order_decision_at, "sample-slot order decision"
        )
        submitted_at = _local_naive_timestamp(
            row.order_submitted_at, "sample-slot order submission"
        )
        if (
            decision_at != pd.Timestamp(f"{key.entry_date.date()} {ENTRY_CUTOFF_TIME}")
            or submitted_at
            != pd.Timestamp(f"{key.entry_date.date()} {ORDER_SUBMITTED_TIME}")
        ):
            raise V30StageAError("sample-slot order clock is not frozen")
    work["cap25_rank"] = ranks.astype(np.int64)
    work = work.sort_values(
        ["entry_date", "signal_date", "cap25_rank", "symbol", "gap_id"],
        kind="mergesort",
    ).reset_index(drop=True)

    entry_date = pd.Timestamp(work.entry_date.iloc[0])
    arm = str(work.protocol_arm.iloc[0])
    active: list[dict[str, Any]] = []
    for raw in active_frozen_slots:
        _require_exact_projection(
            raw,
            (
                "protocol_arm",
                "gap_id",
                "symbol",
                "signal_date",
                "entry_date",
                "candidate_key_sha256",
                "frozen_order_digest",
                "capacity_release_date",
            ),
            "active sample slot",
        )
        active_arm = str(_required(raw, "protocol_arm", "active sample slot"))
        symbol = canonical_candidate_symbol(
            _required(raw, "symbol", "active sample slot")
        )
        _require_nonempty_exact_string(
            _required(raw, "gap_id", "active sample slot"), "active gap_id"
        )
        _require_sha256(
            _required(raw, "candidate_key_sha256", "active sample slot"),
            "active candidate key digest",
        )
        _require_sha256(
            _required(raw, "frozen_order_digest", "active sample slot"),
            "active frozen order digest",
        )
        release = _normalized_date(
            _required(raw, "capacity_release_date", "active sample slot"),
            "active sample release date",
        )
        active_key = make_candidate_key(
            protocol_arm=active_arm,
            gap_id=raw["gap_id"],
            symbol=symbol,
            signal_date=raw["signal_date"],
            entry_date=raw["entry_date"],
        )
        if active_arm != arm or raw["candidate_key_sha256"] != active_key.sha256:
            raise V30StageAError("active sample slot identity/arm is invalid")
        if release >= entry_date:
            active.append(
                {
                    "protocol_arm": active_arm,
                    "gap_id": str(raw["gap_id"]),
                    "symbol": symbol,
                    "signal_date": active_key.signal_date,
                    "entry_date": active_key.entry_date,
                    "candidate_key_sha256": str(raw["candidate_key_sha256"]),
                    "frozen_order_digest": str(raw["frozen_order_digest"]),
                    "capacity_release_date": release,
                }
            )
    if len({item["symbol"] for item in active}) != len(active):
        raise V30StageAError("active sample slots contain duplicate symbols")
    if len(active) > MAX_POSITIONS:
        raise V30StageAError("active sample slots exceed the fixed cap")
    statuses: list[str] = []
    active_before: list[int] = []
    provisional: list[str] = []
    for row in work.itertuples(index=False):
        occupied = len(active) + len(provisional)
        active_before.append(occupied)
        if any(item["symbol"] == str(row.symbol) for item in active) or str(
            row.symbol
        ) in provisional:
            statuses.append("PREALLOCATION_REJECT_SAME_SYMBOL")
        elif occupied >= MAX_POSITIONS:
            statuses.append("PREALLOCATION_REJECT_K50")
        else:
            statuses.append("PREALLOCATED_ORDER_SAMPLE_SLOT")
            provisional.append(str(row.symbol))
    work["occupied_sample_slots_before"] = np.asarray(active_before, dtype=np.int64)
    work["preallocation_status"] = statuses
    work["sample_cap_semantics"] = SAMPLE_CAP_SEMANTICS
    if len(work) != len(statuses):
        raise V30StageAError("sample-slot preallocation conservation failed")
    return work.loc[:, PREALLOCATION_OUTPUT_COLUMNS].copy()


def validate_entry_settlement_evidence(
    value: Any, *, expected_row: Mapping[str, Any]
) -> EntrySettlementEvidence:
    if not isinstance(value, EntrySettlementEvidence):
        raise V30StageAError("entry settlement lacks a typed complete evidence object")
    rebuilt = _build_entry_settlement(
        value.order,
        value.opened_bars,
        value.opened_key_sha256,
        value.h0_audit,
    )
    if value != rebuilt:
        raise V30StageAError("entry settlement fields or digest are inconsistent")
    key = make_candidate_key(
        protocol_arm=_required(expected_row, "protocol_arm", "settlement candidate"),
        gap_id=_required(expected_row, "gap_id", "settlement candidate"),
        symbol=_required(expected_row, "symbol", "settlement candidate"),
        signal_date=_required(expected_row, "signal_date", "settlement candidate"),
        entry_date=_required(expected_row, "entry_date", "settlement candidate"),
    )
    if (
        value.candidate_key != key
        or str(_required(expected_row, "candidate_key_sha256", "settlement candidate"))
        != key.sha256
        or str(_required(expected_row, "action_scope_digest", "settlement candidate"))
        != value.order.action_scope_digest
        or str(_required(expected_row, "frozen_order_digest", "settlement candidate"))
        != value.order.frozen_order_digest
        or str(_required(expected_row, "market_calendar_sha256", "settlement candidate"))
        != value.order.market_calendar_sha256
        or _normalized_date(
            _required(expected_row, "h30_capacity_audit_date", "settlement candidate"),
            "settlement H30 date",
        )
        != value.order.h30_capacity_audit_date
        or _local_naive_timestamp(
            _required(expected_row, "order_decision_at", "settlement candidate"),
            "settlement order decision",
        )
        != value.order.order_decision_at
        or _local_naive_timestamp(
            _required(expected_row, "order_submitted_at", "settlement candidate"),
            "settlement order submission",
        )
        != value.order.order_submitted_at
    ):
        raise V30StageAError("entry settlement is not one-to-one with preallocation")
    return value


def _entry_evidence_record(value: EntrySettlementEvidence) -> dict[str, Any]:
    evidence = validate_entry_settlement_evidence(
        value,
        expected_row={
            "protocol_arm": value.candidate_key.protocol_arm,
            "gap_id": value.candidate_key.gap_id,
            "symbol": value.candidate_key.symbol,
            "signal_date": value.candidate_key.signal_date,
            "entry_date": value.candidate_key.entry_date,
            "h30_capacity_audit_date": value.order.h30_capacity_audit_date,
            "candidate_key_sha256": value.candidate_key.sha256,
            "market_calendar_sha256": value.order.market_calendar_sha256,
            "action_scope_digest": value.order.action_scope_digest,
            "frozen_order_digest": value.order.frozen_order_digest,
            "order_decision_at": value.order.order_decision_at,
            "order_submitted_at": value.order.order_submitted_at,
        },
    )
    key = evidence.candidate_key
    maximum = evidence.order.max_headroom_buy_tick
    return {
        "protocol_arm": key.protocol_arm,
        "gap_id": key.gap_id,
        "symbol": key.symbol,
        "signal_date": key.signal_date,
        "entry_date": key.entry_date,
        "order_decision_at": evidence.order.order_decision_at,
        "order_submitted_at": evidence.order.order_submitted_at,
        "candidate_key_sha256": key.sha256,
        "market_calendar_sha256": evidence.order.market_calendar_sha256,
        "action_scope_digest": evidence.order.action_scope_digest,
        "frozen_order_digest": evidence.order.frozen_order_digest,
        "entry_execution_evidence_label": ENTRY_EXECUTION_EVIDENCE_LABEL,
        "opened_bar_end_times": tuple(
            item.bar_end_time.isoformat() for item in evidence.opened_bars
        ),
        "opened_row_sha256": evidence.opened_key_sha256,
        "opened_bar_transitions": tuple(
            item.bar_transition for item in evidence.opened_bars
        ),
        "opened_provable_strict_cross_volume_shares": tuple(
            item.provable_strict_cross_volume_shares for item in evidence.opened_bars
        ),
        "opened_row_count": len(evidence.opened_key_sha256),
        "last_opened_bar_end_time": (
            pd.Timestamp(
                f"{key.entry_date.date()} {ENTRY_SCAN_BAR_END_TIMES[len(evidence.opened_key_sha256) - 1]}:00"
            )
            if evidence.opened_key_sha256
            else None
        ),
        "proof_bar_end_time": (
            evidence.opened_bars[-1].bar_end_time
            if evidence.entry_evidence_accepted
            else None
        ),
        "proof_row_sha256": (
            evidence.opened_bars[-1].row_sha256
            if evidence.entry_evidence_accepted
            else None
        ),
        "proof_low_tick": (
            int(evidence.opened_bars[-1].low_tick)
            if evidence.entry_evidence_accepted
            else None
        ),
        "proof_high_tick": (
            int(evidence.opened_bars[-1].high_tick)
            if evidence.entry_evidence_accepted
            else None
        ),
        "proof_volume_exact": (
            evidence.opened_bars[-1].volume_exact
            if evidence.entry_evidence_accepted
            else None
        ),
        "proof_volume_source_float64_bits": (
            evidence.opened_bars[-1].volume_source_float64_bits
            if evidence.entry_evidence_accepted
            else None
        ),
        "proof_amount_exact": (
            evidence.opened_bars[-1].amount_exact
            if evidence.entry_evidence_accepted
            else None
        ),
        "proof_amount_exact_cents": (
            format(
                _nonnegative_decimal(
                    evidence.opened_bars[-1].amount_exact, "proof amount"
                )
                * 100,
                "f",
            )
            if evidence.entry_evidence_accepted
            else None
        ),
        "proof_amount_conservative_upper_cents": (
            evidence.opened_bars[-1].amount_conservative_upper_cents
            if evidence.entry_evidence_accepted
            else None
        ),
        "proof_amount_outward_adjustment_cents": (
            evidence.opened_bars[-1].amount_outward_adjustment_cents
            if evidence.entry_evidence_accepted
            else None
        ),
        "proof_amount_source_float64_bits": (
            evidence.opened_bars[-1].amount_source_float64_bits
            if evidence.entry_evidence_accepted
            else None
        ),
        "proof_provable_strict_cross_volume_shares": (
            evidence.opened_bars[-1].provable_strict_cross_volume_shares
            if evidence.entry_evidence_accepted
            else None
        ),
        "entry_scan_digest": evidence.entry_scan_digest,
        "settlement_digest": evidence.settlement_digest,
        "fill_tick": (
            int(evidence.fill_tick)
            if evidence.fill_tick is not None
            else None
        ),
        "cancel_at": evidence.cancel_at,
        "order_size_shares": evidence.order.order_size_shares,
        "time_in_force": evidence.order.time_in_force,
        "qd010_action_status": evidence.order.qd010_action_status,
        "signal_raw_close_tick": int(evidence.order.signal_raw_close_tick),
        "universal_maximum_down_floor_tick": int(
            evidence.order.universal_maximum_down_floor_tick
        ),
        "universal_minimum_up_cap_tick": int(
            evidence.order.universal_minimum_up_cap_tick
        ),
        "max_headroom_buy_tick": int(maximum) if maximum is not None else None,
        "frozen_buy_limit_tick": (
            int(evidence.order.frozen_buy_limit_tick)
            if evidence.order.frozen_buy_limit_tick is not None
            else None
        ),
        "raw_l_tick": int(evidence.order.raw_l_tick),
        "reclaimed_pivot_tick": int(evidence.order.reclaimed_pivot_tick),
        "h30_capacity_audit_date": evidence.order.h30_capacity_audit_date,
        "entry_hard_valid": evidence.entry_hard_valid,
        "entry_status": evidence.entry_status,
        "entry_evidence_accepted": evidence.entry_evidence_accepted,
        "counterfactual_proxy_fill_proved": (
            evidence.counterfactual_proxy_fill_proved
        ),
        "h0_audit_status": evidence.h0_audit.audit_status,
        "h0_decision_at": evidence.h0_audit.decision_at,
        "h0_available_at": evidence.h0_audit.available_at,
        "h0_trade_status": evidence.h0_audit.trade_status,
        "h0_current_day_data_tradable": (
            evidence.h0_audit.current_day_data_tradable
        ),
        "h0_is_st": evidence.h0_audit.is_st,
        "h0_state_source": evidence.h0_audit.state_source,
        "h0_daily_volume_exact": evidence.h0_audit.daily_volume_exact,
        "h0_daily_volume_float64_bits": (
            evidence.h0_audit.daily_volume_float64_bits
        ),
        "h0_daily_amount_exact": evidence.h0_audit.daily_amount_exact,
        "h0_daily_amount_float64_bits": (
            evidence.h0_audit.daily_amount_float64_bits
        ),
        "h0_float_effective_date": evidence.h0_audit.float_effective_date,
        "h0_float_announced_date": evidence.h0_audit.float_announced_date,
        "h0_float_available_date": evidence.h0_audit.float_available_date,
        "h0_circulating_shares_exact": (
            evidence.h0_audit.circulating_shares_exact
        ),
        "h0_circulating_shares_float64_bits": (
            evidence.h0_audit.circulating_shares_float64_bits
        ),
        "h0_float_source": evidence.h0_audit.float_source,
        "h0_corporate_action_count": evidence.h0_audit.corporate_action_count,
        "h0_corporate_action_ids": evidence.h0_audit.corporate_action_ids,
        "h0_corporate_action_source": evidence.h0_audit.corporate_action_source,
        "h0_corporate_action_available_date": (
            evidence.h0_audit.corporate_action_available_date
        ),
        "h0_corporate_action_blocking": (
            evidence.h0_audit.corporate_action_blocking
        ),
        "h0_corporate_action_problems": (
            evidence.h0_audit.corporate_action_problems
        ),
        "h0_share_multiplier_exact": evidence.h0_audit.share_multiplier_exact,
        "h0_share_multiplier_float64_bits": (
            evidence.h0_audit.share_multiplier_float64_bits
        ),
        "h0_cash_per_share_exact": evidence.h0_audit.cash_per_share_exact,
        "h0_cash_per_share_float64_bits": (
            evidence.h0_audit.cash_per_share_float64_bits
        ),
        "h0_rights_ratio_exact": evidence.h0_audit.rights_ratio_exact,
        "h0_rights_ratio_float64_bits": (
            evidence.h0_audit.rights_ratio_float64_bits
        ),
        "h0_rights_price_exact": evidence.h0_audit.rights_price_exact,
        "h0_rights_price_float64_bits": (
            evidence.h0_audit.rights_price_float64_bits
        ),
        "h0_market_rule_id": evidence.h0_audit.market_rule_id,
        "h0_market_rule_source": evidence.h0_audit.market_rule_source,
        "h0_bar_valid": evidence.h0_audit.bar_valid,
        "h0_trading_state_valid": evidence.h0_audit.trading_state_valid,
        "h0_industry_valid": evidence.h0_audit.industry_valid,
        "h0_float_valid": evidence.h0_audit.float_valid,
        "h0_corporate_action_valid": evidence.h0_audit.corporate_action_valid,
        "h0_market_valid": evidence.h0_audit.market_valid,
        "h0_market_rule_valid": evidence.h0_audit.market_rule_valid,
        "h0_historical_identity_valid": (
            evidence.h0_audit.historical_identity_valid
        ),
        "h0_hard_valid": evidence.h0_audit.hard_valid,
        "h0_invalid_reasons": evidence.h0_audit.invalid_reasons,
        "h0_snapshot_id": evidence.h0_audit.snapshot_id,
        "h0_pit_grade": evidence.h0_audit.pit_grade,
        "h0_strict_archive_ready": evidence.h0_audit.strict_archive_ready,
        "h0_daily_snapshot_id": evidence.h0_audit.daily_snapshot_id,
        "h0_trading_state_snapshot_id": (
            evidence.h0_audit.trading_state_snapshot_id
        ),
        "h0_industry_snapshot_id": evidence.h0_audit.industry_snapshot_id,
        "h0_float_snapshot_id": evidence.h0_audit.float_snapshot_id,
        "h0_corporate_action_snapshot_id": (
            evidence.h0_audit.corporate_action_snapshot_id
        ),
        "h0_market_snapshot_id": evidence.h0_audit.market_snapshot_id,
        "h0_query_partition_sha256": evidence.h0_audit.query_partition_sha256,
        "h0_query_locator": evidence.h0_audit.query_locator,
        "h0_physical_source_locator": evidence.h0_audit.physical_source_locator,
        "h0_source_snapshot_id": evidence.h0_audit.source_snapshot_id,
        "h0_source_match_count": evidence.h0_audit.source_match_count,
        "h0_permitted_projection_sha256": (
            evidence.h0_audit.permitted_projection_sha256
        ),
        "h0_audit_digest": evidence.h0_audit.audit_digest,
    }


def settle_preallocated_orders(
    preallocated: pd.DataFrame,
    evidence_loader: Callable[[pd.Series], EntrySettlementEvidence],
) -> tuple[pd.DataFrame, tuple[EntrySettlementEvidence, ...]]:
    """Open entry evidence only for preallocated rows, stopping on unknown."""
    _require_exact_frame_projection(
        preallocated, PREALLOCATION_OUTPUT_COLUMNS, "preallocated settlement input"
    )
    if preallocated.empty or preallocated.entry_date.nunique() != 1:
        raise V30StageAError("preallocated day is empty or malformed")
    rows: list[dict[str, Any]] = []
    terminal_evidence: list[EntrySettlementEvidence] = []
    unknown_seen = False
    for _, row in preallocated.iterrows():
        base = row.to_dict()
        blank_evidence = {
            column: None
            for column in ENTRY_EVIDENCE_OUTPUT_COLUMNS
            if column not in base
        }
        if row.preallocation_status != "PREALLOCATED_ORDER_SAMPLE_SLOT":
            rows.append(
                {
                    **base,
                    **blank_evidence,
                    "entry_settlement_status": str(row.preallocation_status),
                    "entry_evidence_accepted": False,
                    "entry_evidence_opened": False,
                }
            )
            continue
        if unknown_seen:
            rows.append(
                {
                    **base,
                    **blank_evidence,
                    "entry_settlement_status": "UNKNOWN_NOT_OPENED_AFTER_PRIOR_UNKNOWN",
                    "entry_evidence_accepted": None,
                    "entry_evidence_opened": False,
                }
            )
            continue
        try:
            evidence = evidence_loader(row.copy())
            evidence = validate_entry_settlement_evidence(evidence, expected_row=base)
            evidence_record = _entry_evidence_record(evidence)
            accepted = evidence.entry_evidence_accepted
            terminal_evidence.append(evidence)
            rows.append(
                {
                    **base,
                    **evidence_record,
                    "entry_settlement_status": (
                        "SETTLED_COUNTERFACTUAL_PROXY_FILL"
                        if bool(accepted)
                        else "SETTLED_MECHANICAL_NO_FILL"
                    ),
                    "entry_evidence_accepted": bool(accepted),
                    "entry_evidence_opened": True,
                }
            )
        except (V30StageAError, KeyError, TypeError, ValueError):
            unknown_seen = True
            rows.append(
                {
                    **base,
                    **blank_evidence,
                    "entry_settlement_status": "UNKNOWN_ENTRY_EVIDENCE",
                    "entry_evidence_accepted": None,
                    "entry_evidence_opened": True,
                }
            )
    result = pd.DataFrame.from_records(rows, columns=SETTLED_ORDER_OUTPUT_COLUMNS)
    if len(result) != len(preallocated):
        raise V30StageAError("daily entry settlement conservation failed")
    return result, tuple(terminal_evidence)


def settle_arm_entry_evidence(
    candidates: pd.DataFrame,
    evidence_loader: Callable[[pd.Series], EntrySettlementEvidence],
    *,
    protocol_arm: str,
) -> SealedSettlementLedger:
    """Preallocate then settle one arm chronologically; arms call separately."""
    arm = _require_nonempty_exact_string(protocol_arm, "settlement protocol arm")
    if arm not in SIGNAL_ARMS:
        raise V30StageAError("settlement protocol arm is not frozen")
    _require_exact_frame_projection(candidates, PREALLOCATION_INPUT_COLUMNS, "arm settlement")
    if candidates.empty:
        return seal_settlement_ledger(
            pd.DataFrame(columns=SETTLED_ORDER_OUTPUT_COLUMNS), protocol_arm=arm
        )
    if candidates.protocol_arm.nunique() != 1 or not candidates.protocol_arm.eq(arm).all():
        raise V30StageAError("arm settlement requires one expected arm")
    work = candidates.copy()
    work["entry_date"] = pd.to_datetime(work.entry_date, errors="coerce").dt.normalize()
    if work.entry_date.isna().any():
        raise V30StageAError("arm settlement entry date is unknown")
    active_slots: list[dict[str, Any]] = []
    settled_frames: list[pd.DataFrame] = []
    terminal_evidence: list[EntrySettlementEvidence] = []
    arm_unknown = False
    for entry_date, day in work.groupby("entry_date", sort=True):
        if arm_unknown:
            remainder_rows = []
            for _, row in day.iterrows():
                base = row.to_dict()
                base.update(
                    {
                        "occupied_sample_slots_before": None,
                        "preallocation_status": "UNKNOWN_NOT_PREALLOCATED_AFTER_ARM_UNKNOWN",
                        "sample_cap_semantics": SAMPLE_CAP_SEMANTICS,
                    }
                )
                base.update(
                    {
                        column: None
                        for column in ENTRY_EVIDENCE_OUTPUT_COLUMNS
                        if column not in base
                    }
                )
                base["entry_settlement_status"] = "UNKNOWN_NOT_OPENED_AFTER_ARM_UNKNOWN"
                base["entry_evidence_accepted"] = None
                base["entry_evidence_opened"] = False
                remainder_rows.append(base)
            settled_frames.append(
                pd.DataFrame.from_records(
                    remainder_rows, columns=SETTLED_ORDER_OUTPUT_COLUMNS
                )
            )
            continue
        allocation = preallocate_order_slots(
            day,
            active_frozen_slots=active_slots,
        )
        settlement, day_evidence = settle_preallocated_orders(
            allocation, evidence_loader
        )
        terminal_evidence.extend(day_evidence)
        settled_frames.append(settlement)
        if settlement.entry_evidence_accepted.isna().any():
            arm_unknown = True
            continue
        accepted = settlement.loc[settlement.entry_evidence_accepted.eq(True)]
        active_slots = [
            slot
            for slot in active_slots
            if pd.Timestamp(slot["capacity_release_date"])
            >= pd.Timestamp(entry_date)
        ]
        active_slots.extend(
            {
                "protocol_arm": str(row.protocol_arm),
                "gap_id": str(row.gap_id),
                "symbol": str(row.symbol),
                "signal_date": pd.Timestamp(row.signal_date).normalize(),
                "entry_date": pd.Timestamp(row.entry_date).normalize(),
                "candidate_key_sha256": str(row.candidate_key_sha256),
                "frozen_order_digest": str(row.frozen_order_digest),
                "capacity_release_date": pd.Timestamp(
                    row.h30_capacity_audit_date
                ).normalize(),
            }
            for row in accepted.itertuples(index=False)
        )
    result = pd.concat(settled_frames, ignore_index=True)
    if len(result) != len(candidates):
        raise V30StageAError("arm settlement identity conservation failed")
    return seal_settlement_ledger(
        result.loc[:, SETTLED_ORDER_OUTPUT_COLUMNS].copy(),
        protocol_arm=arm,
        terminal_evidence=tuple(terminal_evidence),
    )


def _canonical_output_value(value: Any) -> Any:
    if value is None or (not isinstance(value, (tuple, list)) and pd.isna(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (tuple, list)):
        return [_canonical_output_value(item) for item in value]
    return value


def _is_missing_scalar(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (tuple, list, dict, np.ndarray, pd.Series, pd.DataFrame)):
        return False
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return bool(missing) if isinstance(missing, (bool, np.bool_)) else False


def seal_settlement_ledger(
    settled: pd.DataFrame,
    *,
    protocol_arm: str,
    terminal_evidence: Sequence[EntrySettlementEvidence] = (),
) -> SealedSettlementLedger:
    """Seal the exact immutable settlement ledger before cohort derivation."""
    arm = _require_nonempty_exact_string(protocol_arm, "settlement ledger arm")
    if arm not in SIGNAL_ARMS:
        raise V30StageAError("settlement ledger arm is not frozen")
    _require_exact_frame_projection(settled, SETTLED_ORDER_OUTPUT_COLUMNS, "settlement ledger")
    frame = settled.loc[:, SETTLED_ORDER_OUTPUT_COLUMNS].copy()
    if (
        (not frame.empty and not frame.protocol_arm.eq(arm).all())
        or frame.duplicated(list(ARM_CANDIDATE_IDENTITY_COLUMNS)).any()
    ):
        raise V30StageAError("settlement ledger is mixed-arm or duplicate")
    evidence_by_key: dict[tuple[Any, ...], EntrySettlementEvidence] = {}
    for item in terminal_evidence:
        if not isinstance(item, EntrySettlementEvidence):
            raise V30StageAError("settlement seal received untyped terminal evidence")
        key = validate_candidate_key(item.candidate_key)
        identity = (
            key.protocol_arm,
            key.gap_id,
            key.symbol,
            key.signal_date,
            key.entry_date,
        )
        if key.protocol_arm != arm or identity in evidence_by_key:
            raise V30StageAError("terminal evidence is mixed-arm or duplicate")
        evidence_by_key[identity] = item
    if not frame.empty:
        frame = frame.sort_values(
            ["entry_date", "signal_date", "gap_id", "symbol"], kind="mergesort"
        ).reset_index(drop=True)
    terminal_statuses = {
        "SETTLED_COUNTERFACTUAL_PROXY_FILL",
        "SETTLED_MECHANICAL_NO_FILL",
    }
    used_evidence: set[tuple[Any, ...]] = set()
    evidence_only_columns = tuple(
        column
        for column in ENTRY_EVIDENCE_OUTPUT_COLUMNS
        if column not in PREALLOCATION_OUTPUT_COLUMNS
    )
    for raw in frame.to_dict(orient="records"):
        key = make_candidate_key(
            protocol_arm=raw["protocol_arm"],
            gap_id=raw["gap_id"],
            symbol=raw["symbol"],
            signal_date=raw["signal_date"],
            entry_date=raw["entry_date"],
        )
        identity = (
            key.protocol_arm,
            key.gap_id,
            key.symbol,
            key.signal_date,
            key.entry_date,
        )
        if raw["candidate_key_sha256"] != key.sha256:
            raise V30StageAError("settlement row candidate-key digest mismatch")
        status = str(raw["entry_settlement_status"])
        preallocation_status = str(raw["preallocation_status"])
        evidence = evidence_by_key.get(identity)
        if status in terminal_statuses:
            opened = raw["entry_evidence_opened"]
            accepted = raw["entry_evidence_accepted"]
            if (
                preallocation_status != "PREALLOCATED_ORDER_SAMPLE_SLOT"
                or evidence is None
                or not isinstance(opened, (bool, np.bool_))
                or not bool(opened)
                or not isinstance(accepted, (bool, np.bool_))
            ):
                raise V30StageAError("terminal settlement lacks its typed evidence")
            expected = _entry_evidence_record(evidence)
            if any(
                _canonical_output_value(raw[column])
                != _canonical_output_value(expected[column])
                for column in ENTRY_EVIDENCE_OUTPUT_COLUMNS
            ):
                raise V30StageAError("settlement row differs from typed evidence")
            expected_status = (
                "SETTLED_COUNTERFACTUAL_PROXY_FILL"
                if evidence.entry_evidence_accepted
                else "SETTLED_MECHANICAL_NO_FILL"
            )
            if status != expected_status:
                raise V30StageAError("settlement terminal status contradicts evidence")
            used_evidence.add(identity)
        else:
            if evidence is not None:
                raise V30StageAError("nonterminal settlement smuggles terminal evidence")
            is_rejection = status.startswith("PREALLOCATION_REJECT_")
            is_unknown = status.startswith("UNKNOWN_")
            if not (is_rejection or is_unknown):
                raise V30StageAError("settlement row has an unclassified terminal state")
            if is_rejection and (
                status != preallocation_status
                or not isinstance(raw["entry_evidence_opened"], (bool, np.bool_))
                or bool(raw["entry_evidence_opened"])
                or not isinstance(raw["entry_evidence_accepted"], (bool, np.bool_))
                or bool(raw["entry_evidence_accepted"])
            ):
                raise V30StageAError("preallocation rejection evidence is inconsistent")
            if is_unknown and not _is_missing_scalar(raw["entry_evidence_accepted"]):
                raise V30StageAError("UNKNOWN settlement contains a boolean acceptance")
            for column in evidence_only_columns:
                if column == "entry_evidence_accepted":
                    continue
                if not _is_missing_scalar(raw[column]):
                    raise V30StageAError("nonterminal settlement fabricates evidence fields")
    if used_evidence != set(evidence_by_key):
        raise V30StageAError("terminal evidence and settlement identities do not conserve")
    ordered_evidence = tuple(
        evidence_by_key[
            (
                str(row.protocol_arm),
                str(row.gap_id),
                str(row.symbol),
                _normalized_date(row.signal_date, "sealed signal date"),
                _normalized_date(row.entry_date, "sealed entry date"),
            )
        ]
        for row in frame.loc[
            frame.entry_settlement_status.isin(terminal_statuses)
        ].itertuples(index=False)
    )
    payload_rows = [
        {
            column: _canonical_output_value(value)
            for column, value in zip(SETTLED_ORDER_OUTPUT_COLUMNS, row, strict=True)
        }
        for row in frame.itertuples(index=False, name=None)
    ]
    digest = _canonical_json_sha256(
        {
            "protocol_arm": arm,
            "rows": payload_rows,
            "terminal_settlement_digests": [
                item.settlement_digest for item in ordered_evidence
            ],
            "schema": list(SETTLED_ORDER_OUTPUT_COLUMNS),
            "projection": "V30_SEALED_SETTLEMENT_LEDGER_V2",
        }
    )
    return SealedSettlementLedger(arm, frame, ordered_evidence, len(frame), digest)


def validate_sealed_settlement_ledger(value: Any) -> SealedSettlementLedger:
    if not isinstance(value, SealedSettlementLedger):
        raise V30StageAError("settlement ledger is not a typed sealed object")
    rebuilt = seal_settlement_ledger(
        value.rows,
        protocol_arm=value.protocol_arm,
        terminal_evidence=value.terminal_evidence,
    )
    if (
        value.row_count != rebuilt.row_count
        or value.terminal_evidence != rebuilt.terminal_evidence
        or value.settlement_ledger_sha256 != rebuilt.settlement_ledger_sha256
        or not value.rows.equals(rebuilt.rows)
    ):
        raise V30StageAError("sealed settlement ledger fields/digest are inconsistent")
    return value


def seal_accepted_cohort(
    settled: SealedSettlementLedger, *, protocol_arm: str
) -> SealedAcceptedCohort:
    """Derive the only Stage-B-authorized cohort from sealed Stage-A settlement."""
    arm = _require_nonempty_exact_string(protocol_arm, "accepted cohort protocol arm")
    if arm not in SIGNAL_ARMS:
        raise V30StageAError("accepted cohort protocol arm is not frozen")
    sealed = validate_sealed_settlement_ledger(settled)
    if sealed.protocol_arm != arm:
        raise V30StageAError("sealed settlement ledger arm differs from cohort arm")
    settled = sealed.rows
    if settled.empty:
        empty = pd.DataFrame(columns=ACCEPTED_COHORT_OUTPUT_COLUMNS)
        digest = _canonical_json_sha256(
            {"accepted_rows": [], "protocol_arm": arm, "projection": "V30_ACCEPTED_COHORT_V1"}
        )
        return SealedAcceptedCohort(arm, empty, 0, digest)
    if not settled.protocol_arm.eq(arm).all() or settled.duplicated(
        list(ARM_CANDIDATE_IDENTITY_COLUMNS)
    ).any():
        raise V30StageAError("settled cohort is mixed-arm or duplicate")
    if settled.entry_evidence_accepted.isna().any() or settled.entry_settlement_status.astype(
        str
    ).str.startswith("UNKNOWN_").any():
        raise V30StageAError("accepted cohort cannot be sealed from UNKNOWN settlement")
    status = settled.entry_settlement_status.astype(str)
    accepted_mask = status.eq("SETTLED_COUNTERFACTUAL_PROXY_FILL")
    no_fill_mask = status.eq("SETTLED_MECHANICAL_NO_FILL")
    rejected_mask = status.str.startswith("PREALLOCATION_REJECT_")
    if (
        not (accepted_mask | no_fill_mask | rejected_mask).all()
        or not settled.loc[accepted_mask, "entry_evidence_accepted"].eq(True).all()
        or not settled.loc[no_fill_mask | rejected_mask, "entry_evidence_accepted"].eq(False).all()
    ):
        raise V30StageAError("settled cohort statuses do not conserve")
    accepted = settled.loc[
        accepted_mask & settled.entry_evidence_accepted.eq(True)
    ].copy()
    rows: list[dict[str, Any]] = []
    for row in accepted.itertuples(index=False):
        key = make_candidate_key(
            protocol_arm=row.protocol_arm,
            gap_id=row.gap_id,
            symbol=row.symbol,
            signal_date=row.signal_date,
            entry_date=row.entry_date,
        )
        if str(row.candidate_key_sha256) != key.sha256:
            raise V30StageAError("accepted cohort candidate key digest mismatch")
        for field in (
            "market_calendar_sha256",
            "action_scope_digest",
            "frozen_order_digest",
            "entry_scan_digest",
            "settlement_digest",
            "h0_query_partition_sha256",
            "h0_permitted_projection_sha256",
            "h0_audit_digest",
        ):
            _require_sha256(getattr(row, field), f"accepted cohort {field}")
        if row.market_calendar_sha256 != FROZEN_CALENDAR_CANONICAL_SHA256:
            raise V30StageAError("accepted cohort calendar binding failed")
        entry_tick = _require_int64_tick(row.fill_tick, "accepted entry tick")
        signal_close = _require_int64_tick(
            row.signal_raw_close_tick, "accepted signal close tick"
        )
        d5_tick = _require_int64_tick(
            row.universal_maximum_down_floor_tick, "accepted D5 tick"
        )
        u5_tick = _require_int64_tick(
            row.universal_minimum_up_cap_tick, "accepted U5 tick"
        )
        raw_l = _require_int64_tick(row.raw_l_tick, "accepted raw L tick")
        pivot = _require_int64_tick(row.reclaimed_pivot_tick, "accepted pivot tick")
        expected_h0_partition = CY033_DEVELOPMENT_PARTITION_SHA256.get(
            int(key.entry_date.year)
        )
        if expected_h0_partition is None:
            raise V30StageAError("accepted H0 partition is outside development")
        expected_h0_source_snapshot = (
            f"CY033:{CY033_ASSET_MANIFEST_SHA256}:{expected_h0_partition}"
        )
        proof_low = _require_int64_tick(row.proof_low_tick, "proof low tick")
        proof_high = _require_int64_tick(row.proof_high_tick, "proof high tick")
        proof_volume_source = _float64_from_bits(
            row.proof_volume_source_float64_bits, "proof volume source"
        )
        proof_amount_source = _float64_from_bits(
            row.proof_amount_source_float64_bits, "proof amount source"
        )
        proof_volume_exact = _float64_exact_decimal(proof_volume_source)
        proof_amount_exact = _float64_exact_decimal(proof_amount_source)
        proof_amount_raw_cents = proof_amount_exact * 100
        proof_amount_upper_cents = int(
            proof_amount_raw_cents.to_integral_value(rounding=ROUND_CEILING)
        )
        proof_amount_adjustment = (
            Decimal(proof_amount_upper_cents) - proof_amount_raw_cents
        )
        if (
            proof_volume_exact != proof_volume_exact.to_integral_value()
            or format(proof_volume_exact, "f") != row.proof_volume_exact
            or format(proof_amount_exact, "f") != row.proof_amount_exact
            or format(proof_amount_exact * 100, "f")
            != row.proof_amount_exact_cents
            or isinstance(
                row.proof_amount_conservative_upper_cents, (bool, np.bool_)
            )
            or not isinstance(
                row.proof_amount_conservative_upper_cents, (int, np.integer)
            )
            or int(row.proof_amount_conservative_upper_cents)
            != proof_amount_upper_cents
            or row.proof_amount_outward_adjustment_cents
            != format(proof_amount_adjustment, "f")
        ):
            raise V30StageAError("accepted proof raw float64 bits/exact values differ")
        proof_bound = provable_strict_cross_volume_shares(
            volume_shares=int(proof_volume_exact),
            amount_cny_exact=proof_amount_exact,
            low_tick=proof_low,
            high_tick=proof_high,
            buy_limit_tick=entry_tick,
        )
        proxy_proved = _strict_bool_value(
            row.counterfactual_proxy_fill_proved, "accepted proxy proof flag"
        )
        h0_trade_status = row.h0_trade_status
        if isinstance(h0_trade_status, (bool, np.bool_)) or not isinstance(
            h0_trade_status, (int, np.integer)
        ):
            raise V30StageAError("accepted H0 trade status is not exact integer")
        if (
            int(entry_tick) != int(row.frozen_buy_limit_tick)
            or int(entry_tick) > int(row.max_headroom_buy_tick)
            or int(entry_tick) < int(d5_tick)
            or int(entry_tick) > int(u5_tick)
            or int(d5_tick) != int(universal_maximum_down_floor_tick(signal_close))
            or int(u5_tick) != int(universal_minimum_up_cap_tick(signal_close))
            or not proxy_proved
            or row.entry_status
            != "COUNTERFACTUAL_1PCT_BAR_CROSS_PROXY_FILL_PROVED"
            or row.h0_audit_status
            != "H0_CORROBORATED_COUNTERFACTUAL_PROXY_FILL"
            or not _strict_bool_value(row.h0_hard_valid, "accepted H0 hard_valid")
            or not _strict_bool_value(
                row.h0_current_day_data_tradable, "accepted H0 tradability"
            )
            or int(h0_trade_status) != 1
            or row.h0_snapshot_id != CY033_REGISTERED_SNAPSHOT_ID
            or row.h0_query_partition_sha256 != expected_h0_partition
            or row.h0_source_snapshot_id != expected_h0_source_snapshot
            or _strict_bool_value(
                row.h0_corporate_action_blocking, "accepted H0 action blocking"
            )
            or int(row.h0_corporate_action_count) != 0
            or proof_bound < MIN_PROXY_VOLUME_SHARES
            or isinstance(
                row.proof_provable_strict_cross_volume_shares, (bool, np.bool_)
            )
            or not isinstance(
                row.proof_provable_strict_cross_volume_shares, (int, np.integer)
            )
            or int(row.proof_provable_strict_cross_volume_shares) != proof_bound
            or exact_target_net(entry_tick, raw_l) < MIN_EXACT_TARGET_NET
        ):
            raise V30StageAError("accepted entry violates frozen price/headroom chain")
        rows.append(
            {
                "protocol_arm": arm,
                "gap_id": key.gap_id,
                "symbol": key.symbol,
                "signal_date": key.signal_date,
                "entry_date": key.entry_date,
                "candidate_key_sha256": key.sha256,
                "market_calendar_sha256": str(row.market_calendar_sha256),
                "action_scope_digest": str(row.action_scope_digest),
                "frozen_order_digest": str(row.frozen_order_digest),
                "entry_scan_digest": str(row.entry_scan_digest),
                "settlement_digest": str(row.settlement_digest),
                "entry_tick": int(entry_tick),
                "signal_raw_close_tick": int(signal_close),
                "universal_maximum_down_floor_tick": int(d5_tick),
                "universal_minimum_up_cap_tick": int(u5_tick),
                "raw_l_tick": int(raw_l),
                "reclaimed_pivot_tick": int(pivot),
                "h30_capacity_audit_date": _normalized_date(
                    row.h30_capacity_audit_date, "accepted H30 date"
                ),
                "h0_snapshot_id": _require_nonempty_exact_string(
                    row.h0_snapshot_id, "accepted H0 snapshot"
                ),
                "h0_query_partition_sha256": str(
                    row.h0_query_partition_sha256
                ),
                "h0_source_snapshot_id": _require_nonempty_exact_string(
                    row.h0_source_snapshot_id, "accepted H0 source snapshot"
                ),
                "h0_permitted_projection_sha256": str(
                    row.h0_permitted_projection_sha256
                ),
                "h0_audit_digest": str(row.h0_audit_digest),
            }
        )
    result = pd.DataFrame.from_records(rows, columns=ACCEPTED_COHORT_OUTPUT_COLUMNS)
    if not result.empty:
        result = result.sort_values(
            ["entry_date", "protocol_arm", "gap_id", "symbol"], kind="mergesort"
        ).reset_index(drop=True)
    payload_rows = []
    for row in result.itertuples(index=False, name=None):
        payload_rows.append(
            {
                column: _canonical_output_value(value)
                for column, value in zip(ACCEPTED_COHORT_OUTPUT_COLUMNS, row, strict=True)
            }
        )
    cohort_sha256 = _canonical_json_sha256(
        {
            "accepted_rows": payload_rows,
            "protocol_arm": arm,
            "projection": "V30_ACCEPTED_COHORT_V1",
        }
    )
    return SealedAcceptedCohort(arm, result, len(result), cohort_sha256)


def validate_sealed_accepted_cohort(value: Any) -> SealedAcceptedCohort:
    if not isinstance(value, SealedAcceptedCohort):
        raise V30StageAError("accepted cohort is not a typed sealed object")
    arm = _require_nonempty_exact_string(value.protocol_arm, "accepted cohort arm")
    if arm not in SIGNAL_ARMS:
        raise V30StageAError("accepted cohort arm is not frozen")
    _require_exact_frame_projection(value.rows, ACCEPTED_COHORT_OUTPUT_COLUMNS, "accepted cohort")
    rows = value.rows.loc[:, ACCEPTED_COHORT_OUTPUT_COLUMNS].copy()
    if (
        (not rows.empty and not rows.protocol_arm.eq(arm).all())
        or rows.duplicated(list(ARM_CANDIDATE_IDENTITY_COLUMNS)).any()
        or value.accepted_count != len(rows)
    ):
        raise V30StageAError("accepted cohort identity/count is inconsistent")
    if not rows.empty:
        rows = rows.sort_values(
            ["entry_date", "protocol_arm", "gap_id", "symbol"], kind="mergesort"
        ).reset_index(drop=True)
    payload_rows = [
        {
            column: _canonical_output_value(item)
            for column, item in zip(ACCEPTED_COHORT_OUTPUT_COLUMNS, row, strict=True)
        }
        for row in rows.itertuples(index=False, name=None)
    ]
    digest = _canonical_json_sha256(
        {
            "accepted_rows": payload_rows,
            "protocol_arm": arm,
            "projection": "V30_ACCEPTED_COHORT_V1",
        }
    )
    if value.cohort_sha256 != digest or not value.rows.equals(rows):
        raise V30StageAError("accepted cohort digest/order is inconsistent")
    return value


ACCOUNTING_FIELDS = (
    "candidate_total",
    "admin_censored",
    "preorder_resolved_no_order",
    "preorder_unknown",
    "preallocation_rejected",
    "preallocated_no_fill",
    "k50_accepted",
    "settlement_unknown",
)


def summarize_arm_accounting(
    *,
    protocol_arm: str,
    candidate_ledger: pd.DataFrame,
    admin_censored_ledger: pd.DataFrame,
    preorder_ledger: pd.DataFrame,
    settled_frozen_orders: SealedSettlementLedger,
    accepted_cohort: SealedAcceptedCohort | None,
) -> dict[str, Any]:
    arm = _require_nonempty_exact_string(protocol_arm, "accounting protocol arm")
    if arm not in SIGNAL_ARMS:
        raise V30StageAError("accounting protocol arm is not frozen")
    for label, frame in (
        ("candidate", candidate_ledger),
        ("admin-censored", admin_censored_ledger),
    ):
        _require_exact_frame_projection(frame, ARM_CANDIDATE_IDENTITY_COLUMNS, f"{label} ledger")
        if frame.duplicated(list(ARM_CANDIDATE_IDENTITY_COLUMNS)).any():
            raise V30StageAError(f"{label} ledger contains duplicate identity")
        if not frame.empty and not frame.protocol_arm.eq(arm).all():
            raise V30StageAError("arm accounting does not contain one single expected arm")
        for value in frame.gap_id:
            _require_nonempty_exact_string(value, f"{label} gap_id")
    _require_exact_frame_projection(
        preorder_ledger, PREORDER_LEDGER_OUTPUT_COLUMNS, "preorder ledger"
    )
    sealed_settlement = validate_sealed_settlement_ledger(settled_frozen_orders)
    if sealed_settlement.protocol_arm != arm:
        raise V30StageAError("settled ledger arm differs from accounting arm")
    settled_frame = sealed_settlement.rows
    if (
        preorder_ledger.duplicated(list(ARM_CANDIDATE_IDENTITY_COLUMNS)).any()
        or settled_frame.duplicated(list(ARM_CANDIDATE_IDENTITY_COLUMNS)).any()
        or (not preorder_ledger.empty and not preorder_ledger.protocol_arm.eq(arm).all())
        or (
            not settled_frame.empty
            and not settled_frame.protocol_arm.eq(arm).all()
        )
    ):
        raise V30StageAError("arm accounting does not contain one single expected arm")

    def keys(frame: pd.DataFrame) -> set[tuple[Any, ...]]:
        identities: set[tuple[Any, ...]] = set()
        for row in frame.loc[:, ARM_CANDIDATE_IDENTITY_COLUMNS].itertuples(
            index=False
        ):
            key = make_candidate_key(
                protocol_arm=row.protocol_arm,
                gap_id=row.gap_id,
                symbol=row.symbol,
                signal_date=row.signal_date,
                entry_date=row.entry_date,
            )
            identities.add(
                (
                    key.protocol_arm,
                    key.gap_id,
                    key.symbol,
                    key.signal_date,
                    key.entry_date,
                )
            )
        return identities

    candidate_keys = keys(candidate_ledger)
    admin_keys = keys(admin_censored_ledger)
    preorder_keys = keys(preorder_ledger)
    if admin_keys & preorder_keys or candidate_keys != admin_keys | preorder_keys:
        raise V30StageAError("candidate/admin/preorder identity sets do not conserve")
    preorder_statuses = preorder_ledger.preorder_status.astype(str)
    allowed_preorder = {
        PREORDER_ORDER_FROZEN,
        PREORDER_RESOLVED_NO_ORDER,
        PREORDER_UNKNOWN,
    }
    if not preorder_statuses.isin(allowed_preorder).all():
        raise V30StageAError("preorder ledger contains an unclassified state")
    for row in preorder_ledger.itertuples(index=False):
        key = make_candidate_key(
            protocol_arm=row.protocol_arm,
            gap_id=row.gap_id,
            symbol=row.symbol,
            signal_date=row.signal_date,
            entry_date=row.entry_date,
        )
        if row.candidate_key_sha256 != key.sha256:
            raise V30StageAError("preorder candidate key digest mismatch")
        if row.preorder_status == PREORDER_UNKNOWN:
            if any(
                value is not None and not pd.isna(value)
                for value in (row.action_scope_digest, row.frozen_order_digest)
            ):
                raise V30StageAError("UNKNOWN preorder contains fabricated digests")
        else:
            _require_sha256(row.action_scope_digest, "preorder action digest")
            _require_sha256(row.frozen_order_digest, "preorder order digest")
    frozen = preorder_ledger.loc[
        preorder_statuses.eq(PREORDER_ORDER_FROZEN), list(ARM_CANDIDATE_IDENTITY_COLUMNS)
    ]
    settlement_keys = settled_frame.loc[:, list(ARM_CANDIDATE_IDENTITY_COLUMNS)]
    if (
        len(settled_frame) != len(frozen)
        or settlement_keys.duplicated().any()
        or keys(settlement_keys) != keys(frozen)
    ):
        raise V30StageAError("frozen-order settlement identities do not conserve")
    statuses = settled_frame.entry_settlement_status.astype(str)
    preallocation_rejected = int(statuses.str.startswith("PREALLOCATION_REJECT_").sum())
    no_fill_mask = statuses.eq("SETTLED_MECHANICAL_NO_FILL")
    preallocated_no_fill = int(no_fill_mask.sum())
    accepted = int(statuses.eq("SETTLED_COUNTERFACTUAL_PROXY_FILL").sum())
    known_mask = (
        statuses.str.startswith("PREALLOCATION_REJECT_")
        | no_fill_mask
        | statuses.eq("SETTLED_COUNTERFACTUAL_PROXY_FILL")
    )
    unknown = int((~known_mask).sum())
    preallocated_count = int(
        settled_frame.preallocation_status.eq("PREALLOCATED_ORDER_SAMPLE_SLOT").sum()
    )
    if (
        len(frozen) != preallocation_rejected + preallocated_count
        or preallocated_count != preallocated_no_fill + accepted + unknown
        or not settled_frame.loc[
            statuses.str.startswith("PREALLOCATION_REJECT_"), "entry_evidence_opened"
        ].eq(False).all()
    ):
        raise V30StageAError("preorder/preallocation/settlement intermediate mass failed")
    preorder_resolved = int(
        preorder_statuses.eq(PREORDER_RESOLVED_NO_ORDER).sum()
    )
    preorder_unknown = int(preorder_statuses.eq(PREORDER_UNKNOWN).sum())
    accepted_rows = settled_frame.loc[
        statuses.eq("SETTLED_COUNTERFACTUAL_PROXY_FILL"),
        list(ARM_CANDIDATE_IDENTITY_COLUMNS),
    ]
    if unknown == 0 and preorder_unknown == 0:
        accepted_cohort = validate_sealed_accepted_cohort(accepted_cohort)
        if (
            accepted_cohort.protocol_arm != arm
            or accepted_cohort.accepted_count != accepted
            or keys(accepted_cohort.rows) != keys(accepted_rows)
        ):
            raise V30StageAError("sealed accepted cohort does not conserve with settlement")
        _require_sha256(accepted_cohort.cohort_sha256, "accepted cohort SHA-256")
    elif accepted_cohort is not None:
        raise V30StageAError("incomplete arm cannot publish a sealed accepted cohort")
    result = {
        "protocol_arm": arm,
        "complete": preorder_unknown == 0 and unknown == 0,
        "candidate_total": len(candidate_ledger),
        "admin_censored": len(admin_censored_ledger),
        "preorder_resolved_no_order": preorder_resolved,
        "preorder_unknown": preorder_unknown,
        "preallocation_rejected": preallocation_rejected,
        "preallocated_no_fill": preallocated_no_fill,
        "k50_accepted": accepted,
        "settlement_unknown": unknown,
        "sample_cap_semantics": SAMPLE_CAP_SEMANTICS,
    }
    conserved = sum(int(result[field]) for field in ACCOUNTING_FIELDS[1:])
    if conserved != len(candidate_ledger):
        raise V30StageAError("generated arm accounting does not conserve")
    return result


def _validated_arm_accounting(
    value: Mapping[str, Any], label: str, *, expected_arm: str
) -> dict[str, int]:
    _require_exact_projection(value, ARM_ACCOUNTING_OUTPUT_COLUMNS, f"{label} accounting")
    if (
        value.get("protocol_arm") != expected_arm
        or value.get("sample_cap_semantics") != SAMPLE_CAP_SEMANTICS
        or not isinstance(value.get("complete"), (bool, np.bool_))
    ):
        raise V30StageAError(f"{label} accounting arm/type is invalid")
    result: dict[str, int] = {}
    for field in ACCOUNTING_FIELDS:
        raw = value.get(field)
        if isinstance(raw, (bool, np.bool_)) or not isinstance(raw, (int, np.integer)):
            raise V30StageAError(f"{label} {field} is unknown")
        result[field] = int(raw)
        if result[field] < 0:
            raise V30StageAError(f"{label} {field} is negative")
    if result["candidate_total"] != sum(
        result[field]
        for field in (
            "admin_censored",
            "preorder_resolved_no_order",
            "preorder_unknown",
            "preallocation_rejected",
            "preallocated_no_fill",
            "k50_accepted",
            "settlement_unknown",
        )
    ):
        raise V30StageAError(f"{label} accounting does not conserve")
    if (
        result["preorder_unknown"] != 0
        or result["settlement_unknown"] != 0
        or value.get("complete") is not True
    ):
        raise V30StageAError(f"{label} accounting is unknown or incomplete")
    return result


def make_lazy_arm_evidence_audit(
    *,
    status: str,
    reader_call_count: Any,
    materialized_row_count: Any,
    unlock_amount_accepted_count: Any = None,
) -> LazyArmEvidenceAudit:
    if status not in {"NOT_OPENED", "OPENED_AFTER_AMOUNT_LT_201"}:
        raise V30StageAError("lazy fallback status is invalid")
    counts: list[int] = []
    for value, label in (
        (reader_call_count, "lazy reader calls"),
        (materialized_row_count, "lazy materialized rows"),
    ):
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
            raise V30StageAError(f"{label} is not an integer")
        counts.append(int(value))
    reader_calls, materialized = counts
    if reader_calls < 0 or materialized < 0:
        raise V30StageAError("lazy fallback counts are negative")
    if status == "NOT_OPENED":
        if reader_calls != 0 or materialized != 0 or unlock_amount_accepted_count is not None:
            raise V30StageAError("unopened fallback arm contains evidence access")
        unlock: int | None = None
    else:
        if (
            reader_calls <= 0
            or isinstance(unlock_amount_accepted_count, (bool, np.bool_))
            or not isinstance(unlock_amount_accepted_count, (int, np.integer))
            or not 0 <= int(unlock_amount_accepted_count) < MIN_CAUSAL_ACCEPTED
        ):
            raise V30StageAError(
                "fallback arm was not causally unlocked by known Namount<201"
            )
        unlock = int(unlock_amount_accepted_count)
    payload = {
        "materialized_row_count": materialized,
        "protocol_arm": SHARE_VOLUME_FALLBACK_ARM,
        "reader_call_count": reader_calls,
        "status": status,
        "unlock_amount_accepted_count": unlock,
        "projection": "V30_LAZY_SHARE_VOLUME_FALLBACK_EVIDENCE_AUDIT_V1",
    }
    return LazyArmEvidenceAudit(
        protocol_arm=SHARE_VOLUME_FALLBACK_ARM,
        status=status,
        reader_call_count=reader_calls,
        materialized_row_count=materialized,
        unlock_amount_accepted_count=unlock,
        audit_sha256=_canonical_json_sha256(payload),
    )


def validate_lazy_arm_evidence_audit(value: Any) -> LazyArmEvidenceAudit:
    if not isinstance(value, LazyArmEvidenceAudit):
        raise V30StageAError("lazy fallback proof is not typed")
    rebuilt = make_lazy_arm_evidence_audit(
        status=value.status,
        reader_call_count=value.reader_call_count,
        materialized_row_count=value.materialized_row_count,
        unlock_amount_accepted_count=value.unlock_amount_accepted_count,
    )
    if value != rebuilt:
        raise V30StageAError("lazy fallback proof digest/fields are inconsistent")
    return value


def choose_stage_a_arm(
    amount_accounting: Mapping[str, Any],
    share_volume_fallback_accounting: Mapping[str, Any] | None,
    *,
    fallback_lazy_audit: LazyArmEvidenceAudit,
) -> dict[str, Any]:
    """Prefer Namount>=201; open fallback only after known Namount<201."""
    try:
        amount = _validated_arm_accounting(
            amount_accounting, "amount", expected_arm=AMOUNT_ARM
        )
        lazy = validate_lazy_arm_evidence_audit(fallback_lazy_audit)
    except V30StageAError as exc:
        return {
            "status": "BLOCKED",
            "selected_arm": None,
            "blocker": "UNKNOWN_OR_NONCONSERVING_STAGE_A_ACCOUNTING",
            "detail": str(exc),
        }
    n_amount = amount["k50_accepted"]
    if n_amount >= MIN_CAUSAL_ACCEPTED:
        if share_volume_fallback_accounting is not None or lazy.status != "NOT_OPENED":
            return {
                "status": "BLOCKED",
                "selected_arm": None,
                "n_amount": n_amount,
                "blocker": "FALLBACK_WAS_OPENED_BEFORE_LAZY_UNLOCK",
            }
        return {
            "status": "SELECTED",
            "selected_arm": AMOUNT_ARM,
            "n_amount": n_amount,
            "n_share_volume_fallback": None,
            "rule": "N_AMOUNT_GE_201_PREFERRED",
        }
    try:
        if share_volume_fallback_accounting is None:
            raise V30StageAError(
                "share-volume fallback accounting is missing after known Namount<201"
            )
        if (
            lazy.status != "OPENED_AFTER_AMOUNT_LT_201"
            or lazy.unlock_amount_accepted_count != n_amount
        ):
            raise V30StageAError("fallback lazy audit is not bound to known Namount")
        fallback = _validated_arm_accounting(
            share_volume_fallback_accounting,
            "share-volume fallback",
            expected_arm=SHARE_VOLUME_FALLBACK_ARM,
        )
    except V30StageAError as exc:
        return {
            "status": "BLOCKED",
            "selected_arm": None,
            "n_amount": n_amount,
            "blocker": "UNKNOWN_OR_NONCONSERVING_STAGE_A_ACCOUNTING",
            "detail": str(exc),
        }
    n_fallback = fallback["k50_accepted"]
    if n_fallback >= MIN_CAUSAL_ACCEPTED:
        return {
            "status": "SELECTED",
            "selected_arm": SHARE_VOLUME_FALLBACK_ARM,
            "n_amount": n_amount,
            "n_share_volume_fallback": n_fallback,
            "rule": "N_AMOUNT_LT_201_COMPLETE_N_FALLBACK_GE_201",
        }
    return {
        "status": "FAILED_FREQUENCY",
        "selected_arm": None,
        "n_amount": n_amount,
        "n_share_volume_fallback": n_fallback,
        "reason": "FEWER_THAN_201_CAUSAL_K50_ACCEPTS_IN_BOTH_ARMS",
    }


def metadata_check() -> dict[str, Any]:
    """Return code-contract metadata without reading any market-data row."""
    verify_frozen_v29r4_hash()
    schemas = {
        "signal": SIGNAL_OUTPUT_COLUMNS,
        "administrative": ADMIN_OUTPUT_COLUMNS,
        "preorder_ledger": PREORDER_LEDGER_OUTPUT_COLUMNS,
        "preallocation": PREALLOCATION_OUTPUT_COLUMNS,
        "entry_evidence": ENTRY_EVIDENCE_OUTPUT_COLUMNS,
        "settled_order": SETTLED_ORDER_OUTPUT_COLUMNS,
        "accepted_cohort": ACCEPTED_COHORT_OUTPUT_COLUMNS,
        "arm_accounting": ARM_ACCOUNTING_OUTPUT_COLUMNS,
        "signal_daily_lineage": SIGNAL_DAILY_LINEAGE_OUTPUT_COLUMNS,
        "amount_arm_cy033_daily_input": AMOUNT_ARM_DAILY_SIGNAL_INPUT_COLUMNS,
        "share_volume_fallback_cy033_daily_input": (
            SHARE_VOLUME_FALLBACK_DAILY_SIGNAL_INPUT_COLUMNS
        ),
        "qd004_physical_source": QD004_PHYSICAL_SOURCE_COLUMNS,
        "qd004_derived_query_scaffold": QD004_DERIVED_QUERY_SCAFFOLD_COLUMNS,
        "qd004_entry_input": QD004_ENTRY_SCAN_INPUT_COLUMNS,
        "qd004_zero_match_input": QD004_ENTRY_KEY_SCAFFOLD_COLUMNS,
        "cy033_h0_terminal_audit_input": CY033_H0_AUDIT_INPUT_COLUMNS,
        "qd010_action_input": QD010_ACTION_INPUT_COLUMNS,
    }
    bad = sorted(
        field
        for fields in schemas.values()
        for field in fields
        if any(token in field.lower() for token in FORBIDDEN_OUTPUT_FIELD_TOKENS)
    )
    if bad:
        raise V30StageAError(f"outcome-like Stage-A output fields are forbidden: {bad}")
    return {
        "experiment": EXPERIMENT,
        "protocol_version": PROTOCOL_VERSION,
        "mode": "METADATA_CHECK_ONLY",
        "frozen_v29r4_runner": {
            "path": str(FROZEN_V29R4_RUNNER),
            "sha256": FROZEN_V29R4_RUNNER_SHA256,
            "hash_before_import": True,
            "parent_module_executed": False,
        },
        "signal_arms": {
            AMOUNT_ARM: "preferred arm; exact amount ratio in [1,2]",
            SHARE_VOLUME_FALLBACK_ARM: (
                "fallback arm; exact amount ratio in (0,2] and signal raw-share "
                "volume at least its complete prior20 raw-share median"
            ),
            "first_only_scans_are_independent": True,
            "price_gates": "strict int64 daily cents and integer cross-products",
            "raw_l_authority": "CY033 gap-day raw high exact daily-cent tick",
            "legacy_L_and_factor_authorize_raw_l": False,
            "cap25_rank": (
                "date, lexical industry cycle, exact rebound rational descending, "
                "canonical symbol, gap_date, signal_date, gap_id"
            ),
            "reclaimed_pivot": "signal-previous complete day raw high exact cent, frozen",
        },
        "entry_clock": {
            "candidate_cap25_k50_qd010_cutoff": ENTRY_CUTOFF_TIME,
            "order_submitted_time": ORDER_SUBMITTED_TIME,
            "order_size_shares": ORDER_SIZE_SHARES,
            "minimum_provable_strict_through_volume_shares": (
                MIN_PROXY_VOLUME_SHARES
            ),
            "proxy_participation_upper_bound": "100/proved_B<=1%",
            "time_in_force": ORDER_TIME_IN_FORCE,
            "opening_auction_participation": True,
            "ordered_entry_keys": ENTRY_SCAN_BAR_END_TIMES,
            "cancel_time_after_no_proof": ORDER_CANCEL_TIME,
            "fill_proof": (
                "first fully-valid counterfactual proxy bar with source-OHLCVA "
                "conditional strict-through lower bound B>=10000"
            ),
            "strict_through_lower_bound": (
                "H<P => B=V; L>=P => B=0; otherwise "
                "B=max(0,ceil((P*V-ceil(A_raw_decimal_cents))/(P-L)))"
            ),
            "amount_projection_for_buy_proof": (
                "A_upper=ceil(Decimal.from_float(source_amount)*100); preserve "
                "raw little-endian float64 bits, exact raw decimal cents, "
                "A_upper, outward adjustment, and direction in digest"
            ),
            "lower_bound_claim_scope": "source_OHLCVA_conditional_lower_bound",
            "fill_tick": "frozen_planned_limit",
            "real_broker_or_L2_fill_claimed": False,
            "historical_bar_counterfactual_assumption_explicit": True,
            "high_equal_limit_proves_fill": False,
            "low_only_cross_proves_fill": False,
            "unresolved_positive_volume_touch": "UNKNOWN unless a later full proxy resolves",
            "zero_volume_physical_bar": "valid prefix; continue",
            "first_zero_match_scaffold": "immediate UNKNOWN; later keys NOT_OPENED",
            "entry_day_cy033_authorized": (
                "H0_TERMINAL_INTEGRITY_AUDIT_ONLY_AFTER_MINUTE_SETTLEMENT"
            ),
            "h0_audit_time": TERMINAL_AUDIT_TIME,
            "h0_can_create_fill_or_resolve_missing_minute": False,
            "h0_forbidden_fields": [
                "open",
                "high",
                "low",
                "close",
                "preclose",
                "up_limit_price",
                "down_limit_price",
            ],
            "cy033_manifest_sha256": CY033_ASSET_MANIFEST_SHA256,
            "cy033_registered_snapshot_id": CY033_REGISTERED_SNAPSHOT_ID,
            "limit_formula": "min(A67_4pct_max_executable_buy_tick, U5_tick)",
            "legal_price_interval": "D5<=planned<=U5; otherwise PREOPEN_NO_ORDER",
            "qd004_source": QD004_REQUIRED_SOURCE,
            "qd004_source_manifest_sha256": QD004_CANONICAL_SOURCE_SHA256,
            "qd004_source_snapshot_id": "QD004:<manifest_sha256>:<year_partition_sha256>",
            "qd004_manifest_removed_anomalies": True,
            "qd004_manifest_inventory_builder_binding_required": True,
            "lazy_stop_after_first_proof": True,
        },
        "qd010_entry_policy": {
            "symbol_canonicalizer": "full_market.py::_canonical_symbol_sql semantics",
            "builder_known_at_filter": (
                "known_at IS NULL OR known_at<=observation_at; NULL remains blocking"
            ),
            "future_rows_materialized_in_stage_a": False,
            "known_at_precision_exact_domain": ["EXACT_TIMESTAMP", "DAY_ONLY"],
            "effective_by_entry": "any causally-known action blocks",
            "post_entry_through_h30": (
                "RISK_SHARE/RISK_RIGHTS/UNSUPPORTED block; complete CASH_ONLY replays in Stage B"
            ),
        },
        "administrative_clock": {
            "target_active_through": "H10",
            "initial_time_exit_attempts": ["H11", "H12", "H13"],
            "h13_is_a_guaranteed_exit": False,
            "capacity_count": SAMPLE_CAP_SEMANTICS,
            "slot_preallocation": "09:14:59 frozen orders before 09:15 submission",
            "slot_release": "after H30 close; no same-day no-fill backfill",
            "actual_holding_must_be_measured": True,
            "holding_below_15_guaranteed": False,
        },
        "accounting": (
            "admin_censored + preorder_resolved_no_order + preorder_unknown + "
            "preallocation_rejected + preallocated_no_fill + k50_accepted + "
            "settlement_unknown == candidate_total"
        ),
        "selection_rule": (
            "known Namount>=201 selects amount; only known Namount<201 opens the "
            "share-volume fallback; unknown/nonconservation BLOCKED"
        ),
        "schemas": {name: list(fields) for name, fields in schemas.items()},
        "actual_market_data_rows_opened": 0,
        "outcome_rows_opened": 0,
        "post_2021_rows_opened": 0,
        "registry_read": False,
        "stage_a_execution_authorized": False,
        "stage_a_publisher_present": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("metadata-check",), default="metadata-check")
    parser.parse_args()
    print(json.dumps(metadata_check(), indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
