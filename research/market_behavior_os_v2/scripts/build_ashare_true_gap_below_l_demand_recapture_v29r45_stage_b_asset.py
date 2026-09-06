#!/usr/bin/env python3
"""Build the bounded, pre-outcome CY-046 activation asset for V29R4/V29R5.

The default ``metadata-dry-run`` mode reads JSON metadata, hashes exact bound
files, and reads Parquet footers only.  It never opens a Parquet row and never
writes the canonical asset.  ``verify-metadata`` likewise verifies only the
already-built asset's JSON and Parquet footers.

``build`` is deliberately separate.  It is the only mode that may read the
two frozen Stage-A identities and the exact registered 2018-2021 CY-006,
CY-008 and QD-010 rows.  It derives no returns and contains no outcome input.
For CY-006/CY-008, the build preserves invalid or missing evidence as explicit
rows/flags for the future Stage-B runner to fail closed; it never improves a
cohort by deleting bad evidence.  Ambiguous or incomplete candidate-relevant
QD-010 evidence aborts activation instead of being silently filtered.

This builder is not an authorization.  CY-046 and its one-to-one bounded
authorization must be added to the registry only after the immutable output,
the future runner, and the frozen protocol have all been independently
reviewed and hash-bound.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
ASSET_ID = "CY-046"
AUTHORIZATION_ID = "CYQ-AUTH-ASHARE-DEMAND-RECAPTURE-V29R45-STAGE-B-2018-2021-V1"
TARGET_ROOT = Path(
    "/Users/linmei/Documents/CY/data/staging/"
    "CY-046-DEMAND-RECAPTURE-V29R45-STAGE-B-2018-2021-V1"
)
BUILD_LOCK = TARGET_ROOT.with_name(f".{TARGET_ROOT.name}.build.lock")

DEVELOPMENT_START = pd.Timestamp("2018-01-01")
DEVELOPMENT_END = pd.Timestamp("2021-12-31")
DEVELOPMENT_YEARS = (2018, 2019, 2020, 2021)

PREREGISTRATION = OS_ROOT / (
    "experiments/ASHARE-TRUE-GAP-BELOW-L-DEMAND-RECAPTURE-SEQUENTIAL-"
    "V29R45_stage_b_preregistration.json"
)
EXPECTED_PREREGISTRATION_SHA256 = (
    "0280a61744b64b1b9bf4f028ce3e3b237bd2324e9447b6de8e088bfac8cca4d7"
)
REGISTRY = ROOT / "configs/data_asset_registry.json"

R4_FREEZE = OS_ROOT / (
    "artifacts/ASHARE-TRUE-GAP-BELOW-L-FIRST-INVESTABLE-RECLAIM-"
    "V29R4_stage_a_freeze.json"
)
R4_SELECTED = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_first_investable_reclaim_v29r4/"
    "development_stage_a/first_investable_reclaim_signals.parquet"
)
R5_FREEZE = OS_ROOT / (
    "artifacts/ASHARE-TRUE-GAP-BELOW-L-RENEWED-SELL-WAVE-REFRESH-"
    "V29R5_stage_a_freeze.json"
)
R5_PRIMARY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_renewed_sell_wave_refresh_v29r5/"
    "development_stage_a/renewed_sell_wave_cap25_identity.parquet"
)

EXPECTED_R4_FREEZE_SHA256 = "7b7fe3ea6f4789a29b0cd7e846169506e079c3936c20a17860385915766fe236"
EXPECTED_R4_SELECTED_SHA256 = "dc47fd00383045957d9ee6cb94f03f09f5a9f1688821799f6e0d8d3d4047c5ba"
EXPECTED_R5_FREEZE_SHA256 = "59403e3be36351f76637aec5e4f1dd156ddfae482bacfebe1df878d93ffbdbd0"
EXPECTED_R5_PRIMARY_SHA256 = "e225daa011d3851ad406fac525281efa1b0e5e52700e613117637eb82a15857c"
EXPECTED_R4_SOURCE_ROWS = 394
EXPECTED_R4_CAP_ROWS = 251
EXPECTED_R4_CAP_BY_YEAR = {2018: 178, 2019: 25, 2020: 12, 2021: 36}
EXPECTED_R5_CAP_ROWS = 255
EXPECTED_R5_CAP_BY_YEAR = {2018: 180, 2019: 30, 2020: 16, 2021: 29}

CY006_MANIFEST = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "CY-006-pit-b-daily-v2-2018-2026-20260821.json"
)
CY006_ROOT = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily")
CY006_AUDIT = CY006_ROOT.parent / "audit.json"
CY008_MANIFEST = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "CY-008-pit-b-minute-v2-2018-2026-20260821.json"
)
CY008_ROOT = Path("/Users/linmei/Documents/CY/data/processed/pit_b_minute_2018_2026_v2")
CY008_CROSS_YEAR_AUDIT = Path(
    "/Users/linmei/Documents/CY/data/audit/CY-008-minute-pit-b-cross-year-gate.json"
)
QD010_MANIFEST = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/QD-010-cninfo-actions-20260820.json"
)
QD010_ROOT = Path(
    "/Users/linmei/Downloads/workspace/quant/data/staging/"
    "crsp_lean_corporate_actions_enrichment_20260809_v2/vintages/"
    "official_full_sh_sz_current_snapshot_20260809_v5"
)
QD010_SOURCE_MANIFEST = QD010_ROOT / "manifest.json"

EXPECTED_CY006_MANIFEST_SHA256 = "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2"
EXPECTED_CY006_AUDIT_SHA256 = "4adab25ede8b1cb5fa2db3af3ec75340ac6392e60fd83609f87d807a85ba859b"
EXPECTED_CY008_MANIFEST_SHA256 = "5903149da5d8afe37fa18719d17e8a5726856d11e8441d25d51217b05d6adf9f"
EXPECTED_CY008_AUDIT_SHA256 = "fefac612c3ad7467a87fad3c01b8fccce9b1dd6d5269d74c109d037d79f59d5d"
EXPECTED_QD010_MANIFEST_SHA256 = "e1ca622ee227ce308b44933160754d450b80d3ecca79c1470037558e1011ceb8"
EXPECTED_QD010_SOURCE_MANIFEST_SHA256 = (
    "d57afb7826aa87c3929367a989a369f087a7ecf05f1026bcfed751600a3e884c"
)
QD010_SOURCE_SNAPSHOT_ID = f"QD-010-{EXPECTED_QD010_SOURCE_MANIFEST_SHA256[:16]}"
PIT_CONTRACT = {
    "grade": "B",
    "strict_pit_eligible": False,
    "qd010_revision_history_complete": False,
    "publication_allowed": False,
    "usage": "RESEARCH_CONDITIONAL_HYPOTHESIS_ONLY",
}

MANIFEST_TOP_LEVEL_KEYS = {
    "asset_id",
    "status",
    "authorization_id",
    "coverage",
    "protocol",
    "files",
    "source_bindings",
    "pit_contract",
    "content_contract",
}
ACTIVATION_AUDIT_TOP_LEVEL_KEYS = {
    "asset_id",
    "status",
    "gate_pass",
    "manifest_path",
    "manifest_sha256",
    "preregistration_sha256",
    "runner_sha256",
    "asset_builder_sha256",
    "source_metadata_gate",
    "identity_count_gate",
    "scope_gate",
    "snapshot_nonempty_conflict_gate",
    "post_2021_rows",
    "outcome_or_return_source_columns",
    "audit_counts",
    "parquet_rows_opened_for_content_build",
    "outcome_or_return_rows_opened",
    "returns_computed",
    "registry_modified",
    "post_content_source_revalidation",
    "output_schema_sha256",
    "pit_contract",
}

# Fingerprints are over JSON [{name,type,nullable}, ...] with sorted keys and
# compact separators.  They bind the full physical source schema, not merely a
# permissive required-column subset.
EXPECTED_SOURCE_SCHEMA_SHA256 = {
    "R4_SELECTED": "5e5ea0f92fc694625476a8f91cad365e5048268578d86249afc20bac1876139a",
    "R5_PRIMARY": "404f946dcb3d089e5a94a4677ba50123e9817305bb8c3f45f108bc3e875cee64",
    "CY006_DAILY": "9c8842fa73d7bd11e2d0f05815e098931104a1f4bb806b6d0aa5e332bd01688c",
    "CY008_EXECUTION_5M": "24bb207fdff763a0ba793bc3fc39e9b0c3adb8048f47d2e06d05799fafa59680",
    "QD010_DISTRIBUTIONS": "2da964d0c6c30c629e90c8011b66a54853add0dbbb968aaf68e99c5529a53263",
    "QD010_RIGHTS": "b8f091c801dd7f6f3ae7c4910c279ceb2d5e3bd50e8a9c9ceb8ecb70dadc2834",
}

R4_IDENTITY_COLUMNS = (
    "gap_id",
    "symbol",
    "board",
    "gap_date",
    "signal_date",
    "signal_time",
    "coordinate_factor",
    "L",
    "U",
    "W",
    "signal_industry",
    "rebound_from_post_gap_low_over_l",
    "signal_available_at",
    "signal_decision_at",
    "signal_snapshot_id",
    "signal_daily_snapshot_id",
    "signal_trading_state_snapshot_id",
    "signal_industry_snapshot_id",
    "signal_corporate_action_snapshot_id",
)
R5_IDENTITY_COLUMNS = (
    "gap_id",
    "symbol",
    "board",
    "gap_date",
    "signal_date",
    "signal_time",
    "coordinate_factor",
    "L",
    "U",
    "W",
    "signal_industry",
    "rebound_from_post_gap_low_over_l",
    "signal_available_at",
    "feature_latest_timestamp",
    "signal_snapshot_id",
    "signal_daily_snapshot_id",
    "signal_trading_state_snapshot_id",
    "signal_industry_snapshot_id",
    "signal_corporate_action_snapshot_id",
    "cap25_rank",
    "cap25_primary_economic_admission",
)
IDENTITY_OUTPUT_COLUMNS = (
    "protocol_arm",
    "gap_id",
    "symbol",
    "board",
    "signal_date",
    "signal_time",
    "L",
    "coordinate_factor",
    "signal_industry",
    "cap25_rank",
    "signal_available_at",
    "signal_snapshot_id",
    "signal_daily_snapshot_id",
    "signal_corporate_action_snapshot_id",
)

CY006_COLUMNS = (
    "trade_date",
    "decision_at",
    "decision_timezone",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "preclose",
    "trade_status",
    "is_st",
    "up_limit_price",
    "down_limit_price",
    "buy_blocked_open",
    "sell_blocked_open",
    "current_day_data_tradable",
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
    "corporate_action_valid",
    "market_rule_valid",
    "historical_identity_valid",
    "hard_valid",
    "invalid_reasons",
    "available_at",
    "snapshot_id",
    "daily_snapshot_id",
    "trading_state_snapshot_id",
    "corporate_action_snapshot_id",
    "pit_grade",
    "strict_archive_ready",
)
CY008_COLUMNS = (
    "symbol",
    "trade_date",
    "window_index",
    "available_at",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "circulating_shares",
    "trade_status",
    "is_st",
    "up_limit_price",
    "down_limit_price",
    "market_rule_id",
    "market_rule_valid",
    "limit_pct",
    "source_resolution_minutes",
    "minute_count",
    "distinct_minute_count",
    "ohlc_valid",
    "unit_valid",
    "causal_inputs_valid",
    "hard_valid",
    "invalid_reasons",
    "source",
    "snapshot_id",
    "daily_snapshot_id",
)
QD010_COLUMNS = (
    "security_id",
    "symbol",
    "source",
    "source_api",
    "source_record_id",
    "announcement_date",
    "known_at",
    "known_at_precision",
    "known_at_semantics",
    "record_date",
    "effective_date",
    "pay_date",
    "cash_credit_date",
    "share_credit_date",
    "rights_listing_date",
    "subscription_start_date",
    "subscription_end_date",
    "results_announcement_date",
    "listing_announcement_date",
    "bonus_share_ratio",
    "capitalized_share_ratio",
    "cash_per_share_gross",
    "share_multiplier",
    "rights_subscription_ratio",
    "rights_subscription_price",
    "event_type",
    "source_terms_complete",
    "execution_timing_resolved",
    "resolution_status",
    "price_terms_resolved",
    "execution_resolved",
    "execution_timing_unresolved_reason",
    "execution_unresolved_reason",
    "source_description",
    "source_updated_at",
    "source_updated_at_available",
    "source_updated_at_semantics",
    "vintage_id",
    "response_sha256",
    "source_revision",
    "revision_history_complete",
    "strict_pit_eligible",
    "knowledge_quality",
    "row_hash",
    "source_natural_key",
    "source_event_key",
    "event_id",
    "event_identity_quality",
    "revision_id",
    "previous_revision_id",
    "revision_ordinal",
    "is_new_event",
    "is_changed_from_previous",
    "vintage_observation_id",
)

CANDIDATE_DATE_KEY_COLUMNS = (
    "protocol_arm",
    "gap_id",
    "symbol",
    "signal_date",
    "entry_date",
    "trade_date",
    "signal_session_offset",
    "entry_session_offset",
)
ADMIN_BOUND_COLUMNS = (
    "protocol_arm",
    "gap_id",
    "symbol",
    "signal_date",
    "signal_calendar_index",
    "entry_date",
    "h20_date",
    "h21_date",
    "h22_date",
    "h23_date",
    "admin_eligible",
)
DAILY_OUTPUT_COLUMNS = (
    *CANDIDATE_DATE_KEY_COLUMNS,
    *(column for column in CY006_COLUMNS if column not in {"symbol", "trade_date"}),
    "source_row_present",
)
EXECUTION_OUTPUT_COLUMNS = (
    *CANDIDATE_DATE_KEY_COLUMNS,
    *(column for column in CY008_COLUMNS if column not in {"symbol", "trade_date"}),
    "source_row_present",
)
ACTION_OUTPUT_COLUMNS = (
    "protocol_arm",
    "gap_id",
    "symbol",
    "signal_date",
    "entry_date",
    "h23_date",
    "action_kind",
    "source_table",
    "source_asset_id",
    "source_snapshot_id",
    "snapshot_id",
    "available_at",
    "cash_per_share",
    "rights_ratio",
    "rights_price",
    *(
        "event_symbol" if column == "symbol" else column
        for column in QD010_COLUMNS
    ),
)

OUTPUT_FILES = {
    "v29r4_cap25_identity": "v29r4_cap25_identity.parquet",
    "v29r5_cap25_identity": "v29r5_cap25_identity.parquet",
    "candidate_admin_bounds": "candidate_admin_bounds.parquet",
    "candidate_daily_path": "candidate_daily_path.parquet",
    "candidate_execution_window0": "candidate_execution_window0.parquet",
    "candidate_action_events": "candidate_action_events.parquet",
    "market_calendar": "market_calendar.parquet",
}
EXACT_CANONICAL_FILENAMES = frozenset(
    [*OUTPUT_FILES.values(), "asset_manifest.json", "activation_audit.json"]
)
EXPECTED_OUTPUT_COLUMNS = {
    "v29r4_cap25_identity": IDENTITY_OUTPUT_COLUMNS,
    "v29r5_cap25_identity": IDENTITY_OUTPUT_COLUMNS,
    "candidate_admin_bounds": ADMIN_BOUND_COLUMNS,
    "candidate_daily_path": DAILY_OUTPUT_COLUMNS,
    "candidate_execution_window0": EXECUTION_OUTPUT_COLUMNS,
    "candidate_action_events": ACTION_OUTPUT_COLUMNS,
    "market_calendar": ("trade_date", "calendar_index"),
}


def _explicit_arrow_schema(
    columns: Sequence[str], types: dict[str, pa.DataType]
) -> pa.Schema:
    missing = [column for column in columns if column not in types]
    extra = sorted(set(types).difference(columns))
    if missing or extra:
        raise RuntimeError(f"explicit Arrow schema mismatch: missing={missing}, extra={extra}")
    return pa.schema([pa.field(column, types[column], nullable=True) for column in columns])


_CANDIDATE_KEY_TYPES = {
    "protocol_arm": pa.string(),
    "gap_id": pa.string(),
    "symbol": pa.string(),
    "signal_date": pa.date32(),
    "entry_date": pa.date32(),
    "trade_date": pa.date32(),
    "signal_session_offset": pa.int64(),
    "entry_session_offset": pa.int64(),
}
_CY006_TYPES = {
    "decision_at": pa.timestamp("us"),
    "decision_timezone": pa.string(),
    "open": pa.float64(),
    "high": pa.float64(),
    "low": pa.float64(),
    "close": pa.float64(),
    "preclose": pa.float64(),
    "trade_status": pa.int32(),
    "is_st": pa.bool_(),
    "up_limit_price": pa.float64(),
    "down_limit_price": pa.float64(),
    "buy_blocked_open": pa.bool_(),
    "sell_blocked_open": pa.bool_(),
    "current_day_data_tradable": pa.bool_(),
    "corporate_action_count": pa.int64(),
    "corporate_action_ids": pa.string(),
    "corporate_action_source": pa.string(),
    "corporate_action_available_date": pa.date32(),
    "corporate_action_blocking": pa.bool_(),
    "corporate_action_problems": pa.string(),
    "share_multiplier": pa.float64(),
    "cash_per_share": pa.float64(),
    "rights_ratio": pa.float64(),
    "rights_price": pa.float64(),
    "market_rule_id": pa.string(),
    "market_rule_source": pa.string(),
    "bar_valid": pa.bool_(),
    "trading_state_valid": pa.bool_(),
    "corporate_action_valid": pa.bool_(),
    "market_rule_valid": pa.bool_(),
    "historical_identity_valid": pa.bool_(),
    "hard_valid": pa.bool_(),
    "invalid_reasons": pa.string(),
    "available_at": pa.timestamp("us"),
    "snapshot_id": pa.string(),
    "daily_snapshot_id": pa.string(),
    "trading_state_snapshot_id": pa.string(),
    "corporate_action_snapshot_id": pa.string(),
    "pit_grade": pa.string(),
    "strict_archive_ready": pa.bool_(),
    "source_row_present": pa.bool_(),
}
_CY008_TYPES = {
    "window_index": pa.int32(),
    "available_at": pa.timestamp("us"),
    "open": pa.float64(),
    "high": pa.float64(),
    "low": pa.float64(),
    "close": pa.float64(),
    "volume": pa.float64(),
    "amount": pa.float64(),
    "circulating_shares": pa.float64(),
    "trade_status": pa.int32(),
    "is_st": pa.bool_(),
    "up_limit_price": pa.float64(),
    "down_limit_price": pa.float64(),
    "market_rule_id": pa.string(),
    "market_rule_valid": pa.bool_(),
    "limit_pct": pa.float64(),
    "source_resolution_minutes": pa.int32(),
    "minute_count": pa.int64(),
    "distinct_minute_count": pa.int64(),
    "ohlc_valid": pa.bool_(),
    "unit_valid": pa.bool_(),
    "causal_inputs_valid": pa.bool_(),
    "hard_valid": pa.bool_(),
    "invalid_reasons": pa.string(),
    "source": pa.string(),
    "snapshot_id": pa.string(),
    "daily_snapshot_id": pa.string(),
    "source_row_present": pa.bool_(),
}
_QD_STRING_COLUMNS = {
    "action_kind",
    "source_table",
    "source_asset_id",
    "source_snapshot_id",
    "snapshot_id",
    "security_id",
    "event_symbol",
    "source",
    "source_api",
    "source_record_id",
    "known_at_precision",
    "known_at_semantics",
    "event_type",
    "resolution_status",
    "execution_timing_unresolved_reason",
    "execution_unresolved_reason",
    "source_description",
    "source_updated_at_semantics",
    "vintage_id",
    "response_sha256",
    "source_revision",
    "knowledge_quality",
    "row_hash",
    "source_natural_key",
    "source_event_key",
    "event_id",
    "event_identity_quality",
    "revision_id",
    "previous_revision_id",
    "vintage_observation_id",
}
_QD_TIMESTAMP_COLUMNS = {
    "available_at",
    "announcement_date",
    "known_at",
    "record_date",
    "effective_date",
    "pay_date",
    "cash_credit_date",
    "share_credit_date",
    "rights_listing_date",
    "subscription_start_date",
    "subscription_end_date",
    "results_announcement_date",
    "listing_announcement_date",
    "source_updated_at",
}
_QD_FLOAT_COLUMNS = {
    "cash_per_share",
    "rights_ratio",
    "rights_price",
    "bonus_share_ratio",
    "capitalized_share_ratio",
    "cash_per_share_gross",
    "share_multiplier",
    "rights_subscription_ratio",
    "rights_subscription_price",
}
_QD_BOOL_COLUMNS = {
    "source_terms_complete",
    "execution_timing_resolved",
    "price_terms_resolved",
    "execution_resolved",
    "source_updated_at_available",
    "revision_history_complete",
    "strict_pit_eligible",
    "is_new_event",
    "is_changed_from_previous",
}
_ACTION_TYPES = {
    **{
        "protocol_arm": pa.string(),
        "gap_id": pa.string(),
        "symbol": pa.string(),
        "signal_date": pa.date32(),
        "entry_date": pa.date32(),
        "h23_date": pa.date32(),
    },
    **{column: pa.string() for column in _QD_STRING_COLUMNS},
    **{column: pa.timestamp("ns") for column in _QD_TIMESTAMP_COLUMNS},
    **{column: pa.float64() for column in _QD_FLOAT_COLUMNS},
    **{column: pa.bool_() for column in _QD_BOOL_COLUMNS},
    "revision_ordinal": pa.int64(),
}
OUTPUT_ARROW_SCHEMAS = {
    "v29r4_cap25_identity": _explicit_arrow_schema(
        IDENTITY_OUTPUT_COLUMNS,
        {
            "protocol_arm": pa.string(),
            "gap_id": pa.string(),
            "symbol": pa.string(),
            "board": pa.string(),
            "signal_date": pa.date32(),
            "signal_time": pa.timestamp("us"),
            "L": pa.float64(),
            "coordinate_factor": pa.float64(),
            "signal_industry": pa.string(),
            "cap25_rank": pa.int64(),
            "signal_available_at": pa.timestamp("us"),
            "signal_snapshot_id": pa.string(),
            "signal_daily_snapshot_id": pa.string(),
            "signal_corporate_action_snapshot_id": pa.string(),
        },
    ),
    "v29r5_cap25_identity": _explicit_arrow_schema(
        IDENTITY_OUTPUT_COLUMNS,
        {
            "protocol_arm": pa.string(),
            "gap_id": pa.string(),
            "symbol": pa.string(),
            "board": pa.string(),
            "signal_date": pa.date32(),
            "signal_time": pa.timestamp("us"),
            "L": pa.float64(),
            "coordinate_factor": pa.float64(),
            "signal_industry": pa.string(),
            "cap25_rank": pa.int64(),
            "signal_available_at": pa.timestamp("us"),
            "signal_snapshot_id": pa.string(),
            "signal_daily_snapshot_id": pa.string(),
            "signal_corporate_action_snapshot_id": pa.string(),
        },
    ),
    "candidate_admin_bounds": _explicit_arrow_schema(
        ADMIN_BOUND_COLUMNS,
        {
            "protocol_arm": pa.string(),
            "gap_id": pa.string(),
            "symbol": pa.string(),
            "signal_date": pa.date32(),
            "signal_calendar_index": pa.int64(),
            "entry_date": pa.date32(),
            "h20_date": pa.date32(),
            "h21_date": pa.date32(),
            "h22_date": pa.date32(),
            "h23_date": pa.date32(),
            "admin_eligible": pa.bool_(),
        },
    ),
    "candidate_daily_path": _explicit_arrow_schema(
        DAILY_OUTPUT_COLUMNS, {**_CANDIDATE_KEY_TYPES, **_CY006_TYPES}
    ),
    "candidate_execution_window0": _explicit_arrow_schema(
        EXECUTION_OUTPUT_COLUMNS, {**_CANDIDATE_KEY_TYPES, **_CY008_TYPES}
    ),
    "candidate_action_events": _explicit_arrow_schema(
        ACTION_OUTPUT_COLUMNS, _ACTION_TYPES
    ),
    "market_calendar": _explicit_arrow_schema(
        ("trade_date", "calendar_index"),
        {"trade_date": pa.date32(), "calendar_index": pa.int64()},
    ),
}
FORBIDDEN_IDENTITY_COLUMN_TOKENS = (
    "outcome",
    "return",
    "pnl",
    "profit",
    "holding",
    "exit_price",
    "target_hit",
    "nav",
)


class CY046BuildError(RuntimeError):
    """Fail closed on any governance, identity, scope, or lineage drift."""


@dataclass(frozen=True)
class SourceLayout:
    registry: Path = REGISTRY
    preregistration: Path = PREREGISTRATION
    r4_freeze: Path = R4_FREEZE
    r4_selected: Path = R4_SELECTED
    r5_freeze: Path = R5_FREEZE
    r5_primary: Path = R5_PRIMARY
    cy006_manifest: Path = CY006_MANIFEST
    cy006_root: Path = CY006_ROOT
    cy006_audit: Path = CY006_AUDIT
    cy008_manifest: Path = CY008_MANIFEST
    cy008_root: Path = CY008_ROOT
    cy008_cross_year_audit: Path = CY008_CROSS_YEAR_AUDIT
    qd010_manifest: Path = QD010_MANIFEST
    qd010_root: Path = QD010_ROOT
    qd010_source_manifest: Path = QD010_SOURCE_MANIFEST


DEFAULT_LAYOUT = SourceLayout()


def _lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _reject_symlink_components(path: Path, role: str) -> Path:
    """Reject a symlink leaf or ancestor before a file is stat'ed or opened."""
    absolute = _lexical_absolute(path)
    for component in (absolute, *absolute.parents):
        try:
            mode = component.lstat().st_mode
        except OSError as exc:
            raise CY046BuildError(f"{role} path component is unavailable: {component}") from exc
        if stat.S_ISLNK(mode):
            raise CY046BuildError(f"{role} path contains a symlink: {component}")
    return absolute


def _require_safe_regular_file(
    path: Path,
    role: str,
    *,
    registered_root: Path | None = None,
) -> Path:
    """Fail before stat/hash/footer when a bound file is linked or escapes its root."""
    absolute = _lexical_absolute(path)
    root_absolute: Path | None = None
    if registered_root is not None:
        root_absolute = _lexical_absolute(registered_root)
        try:
            absolute.relative_to(root_absolute)
        except ValueError as exc:
            raise CY046BuildError(
                f"{role} is not lexically contained by its exact registered root"
            ) from exc
    absolute = _reject_symlink_components(absolute, role)
    mode = absolute.lstat().st_mode
    if not stat.S_ISREG(mode):
        raise CY046BuildError(f"{role} must be one regular file: {absolute}")
    if root_absolute is not None:
        root_mode = root_absolute.lstat().st_mode
        if not stat.S_ISDIR(root_mode):
            raise CY046BuildError(f"{role} registered root is not a directory")
        try:
            resolved_root = root_absolute.resolve(strict=True)
            resolved_file = absolute.resolve(strict=True)
        except OSError as exc:
            raise CY046BuildError(f"{role} cannot resolve its exact registered root") from exc
        if not resolved_file.is_relative_to(resolved_root):
            raise CY046BuildError(f"{role} escaped its exact registered root")
    return absolute


def atomic_publish_directory_no_replace(source: Path, destination: Path) -> None:
    """Atomically publish one directory and fail if the destination exists."""
    source_absolute = _lexical_absolute(source)
    destination_absolute = _lexical_absolute(destination)
    if source_absolute.parent != destination_absolute.parent:
        raise CY046BuildError("atomic publication requires one common parent directory")
    _reject_symlink_components(source_absolute, "publication source")
    _reject_symlink_components(destination_absolute.parent, "publication destination parent")
    if not stat.S_ISDIR(source_absolute.lstat().st_mode):
        raise CY046BuildError("atomic publication source is not a directory")

    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source_absolute)
    destination_bytes = os.fsencode(destination_absolute)
    if sys.platform == "darwin":
        try:
            native_rename = libc.renamex_np
        except AttributeError as exc:
            raise CY046BuildError("renamex_np is unavailable; refusing non-atomic publish") from exc
        native_rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        native_rename.restype = ctypes.c_int
        result = native_rename(source_bytes, destination_bytes, 0x00000004)  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        try:
            native_rename = libc.renameat2
        except AttributeError as exc:
            raise CY046BuildError("renameat2 is unavailable; refusing non-atomic publish") from exc
        native_rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        native_rename.restype = ctypes.c_int
        result = native_rename(
            -100, source_bytes, -100, destination_bytes, 0x00000001
        )  # AT_FDCWD, RENAME_NOREPLACE
    else:
        raise CY046BuildError(
            f"no reviewed atomic no-replace primitive for platform {sys.platform!r}"
        )
    if result != 0:
        error_number = ctypes.get_errno()
        if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
            raise CY046BuildError(
                f"canonical CY-046 appeared before atomic publication: {destination_absolute}"
            )
        native_error = OSError(error_number, os.strerror(error_number))
        raise CY046BuildError(
            f"atomic no-replace publication failed: {destination_absolute}"
        ) from native_error
    _fsync_directory(destination_absolute.parent)


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _uf_immutable_flag() -> int:
    flag = getattr(stat, "UF_IMMUTABLE", None)
    if sys.platform != "darwin" or not hasattr(os, "chflags") or not isinstance(flag, int):
        raise CY046BuildError("macOS UF_IMMUTABLE support is required for CY-046")
    return flag


def _has_uf_immutable(path: Path) -> bool:
    flag = _uf_immutable_flag()
    return bool(int(getattr(path.lstat(), "st_flags", 0)) & flag)


def _clear_uf_immutable(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    flag = _uf_immutable_flag()
    flags = int(getattr(path.lstat(), "st_flags", 0))
    if flags & flag:
        os.chflags(path, flags & ~flag)


def probe_uf_immutable_capability(parent: Path) -> None:
    """Use an empty same-volume file/directory probe before any content row read."""
    parent = _reject_symlink_components(parent, "CY-046 publication parent")
    if not stat.S_ISDIR(parent.lstat().st_mode):
        raise CY046BuildError("CY-046 publication parent is not a directory")
    probe_root = Path(tempfile.mkdtemp(prefix=".cy046-uf-immutable-probe-", dir=parent))
    probe_file = probe_root / "empty"
    probe_file.touch(mode=0o400, exist_ok=False)
    failure: Exception | None = None
    try:
        if probe_file.stat().st_size != 0 or probe_root.stat().st_dev != parent.stat().st_dev:
            raise CY046BuildError("CY-046 immutability probe is not zero-data/same-volume")
        flag = _uf_immutable_flag()
        os.chflags(probe_file, int(getattr(probe_file.lstat(), "st_flags", 0)) | flag)
        os.chflags(probe_root, int(getattr(probe_root.lstat(), "st_flags", 0)) | flag)
        if not _has_uf_immutable(probe_file) or not _has_uf_immutable(probe_root):
            raise CY046BuildError("CY-046 UF_IMMUTABLE probe did not persist flags")
    except Exception as exc:  # cleanup must run even when the filesystem rejects flags
        failure = exc

    cleanup_failure: Exception | None = None
    try:
        _clear_uf_immutable(probe_root)
        _clear_uf_immutable(probe_file)
        probe_root.chmod(0o700)
        probe_file.chmod(0o600)
        probe_file.unlink()
        probe_root.rmdir()
    except Exception as exc:
        cleanup_failure = exc
    if cleanup_failure is not None:
        raise CY046BuildError("CY-046 UF_IMMUTABLE probe cleanup failed") from cleanup_failure
    if failure is not None:
        raise CY046BuildError("CY-046 filesystem cannot enforce UF_IMMUTABLE") from failure


def _canonical_asset_children(root: Path) -> list[Path]:
    root = _reject_symlink_components(root, "CY-046 root")
    if not stat.S_ISDIR(root.lstat().st_mode):
        raise CY046BuildError("CY-046 root is not a directory")
    children = list(root.iterdir())
    if {path.name for path in children} != EXACT_CANONICAL_FILENAMES:
        raise CY046BuildError("CY-046 immutable inventory is not exact")
    return [
        _require_safe_regular_file(
            path, f"CY-046 canonical file {path.name}", registered_root=root
        )
        for path in sorted(children, key=lambda item: item.name)
    ]


def assert_canonical_asset_immutable(root: Path) -> None:
    children = _canonical_asset_children(root)
    if stat.S_IMODE(root.lstat().st_mode) != 0o555 or not _has_uf_immutable(root):
        raise CY046BuildError("CY-046 root is not mode 0555 and UF_IMMUTABLE")
    for path in children:
        if stat.S_IMODE(path.lstat().st_mode) != 0o444 or not _has_uf_immutable(path):
            raise CY046BuildError(f"CY-046 file is not mode 0444 and UF_IMMUTABLE: {path.name}")


def seal_canonical_asset_immutable(root: Path) -> None:
    children = _canonical_asset_children(root)
    flag = _uf_immutable_flag()
    for path in children:
        path.chmod(0o444)
        os.chflags(path, int(getattr(path.lstat(), "st_flags", 0)) | flag)
        _fsync_file(path)
    root.chmod(0o555)
    os.chflags(root, int(getattr(root.lstat(), "st_flags", 0)) | flag)
    _fsync_directory(root)
    assert_canonical_asset_immutable(root)


def clear_canonical_asset_immutability(root: Path) -> None:
    """Clear only flags created by this builder, for failed-build/test cleanup."""
    root = _lexical_absolute(root)
    if not root.exists() or root.is_symlink():
        return
    _clear_uf_immutable(root)
    for path in root.iterdir():
        if not path.is_symlink():
            _clear_uf_immutable(path)
            path.chmod(0o600)
    root.chmod(0o700)


def sha256_file(path: Path) -> str:
    path = _require_safe_regular_file(path, "hash input")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    path = _require_safe_regular_file(path, "JSON metadata")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CY046BuildError(f"cannot read bound JSON metadata: {path}") from exc
    if not isinstance(value, dict):
        raise CY046BuildError(f"JSON root must be an object: {path}")
    return value


def _canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_json_snapshot(path: Path, role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read one non-symlink JSON inode and bind the exact bytes plus file identity."""
    path = _require_safe_regular_file(path, role)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            payload_bytes = handle.read()
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    path_after = path.lstat()
    identities = {
        (before.st_dev, before.st_ino, before.st_size),
        (after.st_dev, after.st_ino, after.st_size),
        (path_after.st_dev, path_after.st_ino, path_after.st_size),
    }
    if len(identities) != 1 or before.st_size != len(payload_bytes):
        raise CY046BuildError(f"{role} changed while its snapshot was read")
    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError as exc:
        raise CY046BuildError(f"cannot decode bound JSON snapshot: {path}") from exc
    if not isinstance(payload, dict):
        raise CY046BuildError(f"JSON snapshot root must be an object: {path}")
    return payload, {
        "role": role,
        "path": str(path),
        "sha256": hashlib.sha256(payload_bytes).hexdigest(),
        "size": before.st_size,
        "device": before.st_dev,
        "inode": before.st_ino,
    }


def _require_file_hash(
    path: Path,
    expected: str,
    role: str,
    *,
    registered_root: Path | None = None,
) -> dict[str, Any]:
    path = _require_safe_regular_file(path, role, registered_root=registered_root)
    identity = path.lstat()
    observed = sha256_file(path)
    after = path.lstat()
    if (identity.st_dev, identity.st_ino, identity.st_size) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
    ):
        raise CY046BuildError(f"{role} changed while hashing: {path}")
    if observed != expected:
        raise CY046BuildError(f"{role} hash drift: {observed} != {expected}")
    return {
        "role": role,
        "path": str(path.resolve()),
        "sha256": observed,
        "size": identity.st_size,
        "device": identity.st_dev,
        "inode": identity.st_ino,
    }


def schema_descriptor(schema: pa.Schema) -> list[dict[str, Any]]:
    return [
        {"name": field.name, "type": str(field.type), "nullable": field.nullable}
        for field in schema
    ]


def schema_sha256(schema: pa.Schema) -> str:
    encoded = json.dumps(
        schema_descriptor(schema), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


OUTPUT_SCHEMA_SHA256 = {
    role: schema_sha256(schema) for role, schema in OUTPUT_ARROW_SCHEMAS.items()
}


def parquet_footer_facts(
    path: Path, *, registered_root: Path | None = None
) -> dict[str, Any]:
    """Return footer facts without scanning or decoding a Parquet data row."""
    path = _require_safe_regular_file(
        path, "Parquet source", registered_root=registered_root
    )
    parquet = pq.ParquetFile(path)
    return {
        "rows": parquet.metadata.num_rows,
        "row_groups": parquet.metadata.num_row_groups,
        "schema": schema_descriptor(parquet.schema_arrow),
        "schema_sha256": schema_sha256(parquet.schema_arrow),
    }


def _exact_asset(registry: dict[str, Any], asset_id: str) -> dict[str, Any]:
    matches = [
        item
        for item in registry.get("assets", [])
        if isinstance(item, dict) and item.get("asset_id") == asset_id
    ]
    if len(matches) != 1:
        raise CY046BuildError(f"registered asset must resolve exactly once: {asset_id}")
    return matches[0]


def _assert_input_asset(
    registry: dict[str, Any],
    asset_id: str,
    manifest_path: Path,
    expected_manifest_hash: str,
) -> dict[str, Any]:
    asset = _exact_asset(registry, asset_id)
    lineage = asset.get("lineage")
    if not isinstance(lineage, dict):
        raise CY046BuildError(f"missing lineage object for {asset_id}")
    if (
        asset.get("status") != "RESEARCH_CONDITIONAL"
        or asset.get("physical_state") != "MATERIALIZED"
        or asset.get("pit_grade") != "B"
        or lineage.get("record_available_at") is not True
        or lineage.get("immutable_manifest") is not True
        or Path(str(lineage.get("manifest_path", ""))) != manifest_path
        or lineage.get("manifest_sha256") != expected_manifest_hash
    ):
        raise CY046BuildError(f"{asset_id} registry PIT/manifest contract drift")
    if asset_id in {"CY-006", "CY-008"} and lineage.get("record_snapshot_id") is not True:
        raise CY046BuildError(f"{asset_id} lost record-level snapshot identity")
    if asset_id == "QD-010" and lineage.get("snapshot_id_from_frozen_input") is not True:
        raise CY046BuildError("QD-010 lost frozen-input snapshot semantics")
    return asset


def _assert_cy046_unregistered(registry: dict[str, Any]) -> None:
    if any(
        isinstance(item, dict) and item.get("asset_id") == ASSET_ID
        for item in registry.get("assets", [])
    ):
        raise CY046BuildError("CY-046 is already registered; immutable rebuild is prohibited")
    if any(
        isinstance(item, dict) and item.get("authorization_id") == AUTHORIZATION_ID
        for item in registry.get("bounded_authorizations", [])
    ):
        raise CY046BuildError(
            "CY-046 authorization already exists; pre-registration rebuild is prohibited"
        )


def _manifest_entries(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for item in manifest.get("files", []):
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise CY046BuildError("inventory contains a malformed file entry")
        relative = item["path"]
        if relative in entries:
            raise CY046BuildError(f"duplicate inventory path: {relative}")
        entries[relative] = item
    return entries


def assert_bounded_partition_path(path: str, component: str) -> None:
    if component == "CY006":
        prefix = "partition_year="
    elif component == "CY008":
        prefix = "execution_5m/partition_year="
    else:
        raise CY046BuildError(f"unknown bounded component: {component}")
    if not path.startswith(prefix) or not path.endswith("/data_0.parquet"):
        raise CY046BuildError(f"unexpected {component} materialization path: {path}")
    try:
        year = int(path.split("partition_year=", 1)[1].split("/", 1)[0])
    except (IndexError, ValueError) as exc:
        raise CY046BuildError(f"cannot parse partition year: {path}") from exc
    if year not in DEVELOPMENT_YEARS:
        raise CY046BuildError(f"post-2021 or out-of-scope partition rejected: {path}")


def _verify_inventory_partition(
    *,
    root: Path,
    entry: dict[str, Any],
    component: str,
    expected_rows: int,
    expected_schema_sha256: str,
) -> dict[str, Any]:
    relative = str(entry.get("path", ""))
    assert_bounded_partition_path(relative, component)
    path = root / relative
    path = _require_safe_regular_file(
        path, f"{component} partition", registered_root=root
    )
    identity = path.lstat()
    if int(entry.get("size", -1)) != identity.st_size:
        raise CY046BuildError(f"source size drift: {path}")
    observed_hash = sha256_file(path)
    after = path.lstat()
    if (identity.st_dev, identity.st_ino, identity.st_size) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
    ):
        raise CY046BuildError(f"{component} source changed while hashing: {path}")
    if observed_hash != entry.get("sha256"):
        raise CY046BuildError(f"source hash drift: {path}")
    footer = parquet_footer_facts(path, registered_root=root)
    if footer["rows"] != expected_rows:
        raise CY046BuildError(f"source footer row-count drift: {path}")
    if footer["schema_sha256"] != expected_schema_sha256:
        raise CY046BuildError(f"source footer schema drift: {path}")
    return {
        "asset_id": "CY-006" if component == "CY006" else "CY-008",
        "year": int(relative.split("partition_year=", 1)[1].split("/", 1)[0]),
        "path": str(path.resolve()),
        "inventory_path": relative,
        "sha256": observed_hash,
        "size": identity.st_size,
        "device": identity.st_dev,
        "inode": identity.st_ino,
        **footer,
        "parquet_rows_opened": False,
    }


def _validate_preregistration(payload: dict[str, Any]) -> None:
    if (
        payload.get("stage") != "DEVELOPMENT_STAGE_B_PRE_OUTCOME_EXECUTION_FREEZE"
        or payload.get("protocol_version") != "V1_PRE_OUTCOME"
        or payload.get("development") != ["2018-01-01", "2021-12-31"]
        or payload.get("post_2021_access") != "PROHIBITED"
    ):
        raise CY046BuildError("shared Stage-B protocol scope drift")
    bounded = payload.get("required_bounded_input", {})
    if (
        bounded.get("asset_id") != ASSET_ID
        or bounded.get("authorization_id") != AUTHORIZATION_ID
        or bounded.get("components") != ["CY-006", "CY-008", "QD-010"]
        or bounded.get("activation_before_outcome") is not True
    ):
        raise CY046BuildError("shared Stage-B CY-046 binding drift")
    if payload.get("sequential_testing", {}).get("order") != [
        "V29R4_CAP25",
        "V29R5_CAP25",
    ]:
        raise CY046BuildError("sequential arm order drift")
    materials = set(bounded.get("required_materializations", []))
    required_fragments = (
        "V29R4 CAP25 identity",
        "V29R5 frozen primary CAP25 identity",
        "candidate administrative-bound ledger",
        "candidate-keyed CY-006 daily rows",
        "candidate-keyed CY-008 window_index=0 rows",
        "candidate-keyed QD-010 event rows",
        "market-session calendar",
    )
    if any(not any(fragment in item for item in materials) for fragment in required_fragments):
        raise CY046BuildError("shared Stage-B required materializations drift")
    interface = bounded.get("fixed_file_interface", {})
    if interface.get("identities") != [
        "v29r4_cap25_identity.parquet",
        "v29r5_cap25_identity.parquet",
    ]:
        raise CY046BuildError("shared Stage-B identity filename interface drift")
    for key, filename in {
        "administrative_bounds": "candidate_admin_bounds.parquet",
        "daily": "candidate_daily_path.parquet",
        "execution": "candidate_execution_window0.parquet",
        "actions": "candidate_action_events.parquet",
        "calendar": "market_calendar.parquet",
    }.items():
        if filename not in str(interface.get(key, "")):
            raise CY046BuildError(f"shared Stage-B {key} filename interface drift")
    if "signal=(0,-1)" not in str(interface.get("daily", "")):
        raise CY046BuildError("shared Stage-B daily offset interface drift")
    if "signal_session_offset 1..24" not in str(interface.get("execution", "")):
        raise CY046BuildError("shared Stage-B execution offset interface drift")


def metadata_dry_run(layout: SourceLayout = DEFAULT_LAYOUT) -> dict[str, Any]:
    """Verify all exact input metadata and Parquet footers; read zero rows."""
    prereg = _require_file_hash(
        layout.preregistration, EXPECTED_PREREGISTRATION_SHA256, "stage_b_preregistration"
    )
    prereg_payload = _json(layout.preregistration)
    _validate_preregistration(prereg_payload)
    registry, registry_binding = read_json_snapshot(
        layout.registry, "DATA_ASSET_REGISTRY"
    )
    _assert_cy046_unregistered(registry)
    registry_binding["registered_input_entry_sha256"] = {
        asset_id: _canonical_json_sha256(_exact_asset(registry, asset_id))
        for asset_id in ("CY-006", "CY-008", "QD-010")
    }
    registry_binding["cy046_absent"] = True

    cy006_asset = _assert_input_asset(
        registry, "CY-006", layout.cy006_manifest, EXPECTED_CY006_MANIFEST_SHA256
    )
    cy008_asset = _assert_input_asset(
        registry, "CY-008", layout.cy008_manifest, EXPECTED_CY008_MANIFEST_SHA256
    )
    qd010_asset = _assert_input_asset(
        registry, "QD-010", layout.qd010_manifest, EXPECTED_QD010_MANIFEST_SHA256
    )
    if Path(str(cy006_asset.get("location", ""))) != layout.cy006_root:
        raise CY046BuildError("CY-006 registered root drift")
    if Path(str(cy008_asset.get("location", ""))) != layout.cy008_root:
        raise CY046BuildError("CY-008 registered root drift")
    if Path(str(qd010_asset.get("location", ""))) != layout.qd010_root:
        raise CY046BuildError("QD-010 registered root drift")
    if "CY-006" not in cy008_asset.get("lineage", {}).get("component_assets", []):
        raise CY046BuildError("CY-008 is no longer explicitly derived from CY-006")
    if not any(
        "daily causal state generation" in str(item)
        for item in cy006_asset.get("allowed_uses", [])
    ):
        raise CY046BuildError("CY-006 no longer allows bounded daily causal research")
    if not any(
        "next-window causal execution" in str(item)
        for item in cy008_asset.get("allowed_uses", [])
    ):
        raise CY046BuildError("CY-008 no longer allows next-window execution research")
    if not any(
        "bounded PIT-B causal research adaptation" in str(item)
        for item in qd010_asset.get("allowed_uses", [])
    ):
        raise CY046BuildError("QD-010 no longer allows bounded PIT-B adaptation")
    qd_lineage = qd010_asset.get("lineage", {})
    if (
        Path(str(qd_lineage.get("source_manifest_path", "")))
        != layout.qd010_source_manifest
        or qd_lineage.get("source_manifest_sha256")
        != EXPECTED_QD010_SOURCE_MANIFEST_SHA256
    ):
        raise CY046BuildError("QD-010 source-manifest registry binding drift")

    cy006_manifest = _json(layout.cy006_manifest)
    cy008_manifest = _json(layout.cy008_manifest)
    qd010_manifest = _json(layout.qd010_manifest)
    if Path(str(cy006_manifest.get("root", ""))) != layout.cy006_root:
        raise CY046BuildError("CY-006 inventory root drift")
    if Path(str(cy008_manifest.get("root", ""))) != layout.cy008_root:
        raise CY046BuildError("CY-008 inventory root drift")
    if Path(str(qd010_manifest.get("root", ""))) != layout.qd010_root:
        raise CY046BuildError("QD-010 inventory root drift")

    cy006_audit_binding = _require_file_hash(
        layout.cy006_audit,
        EXPECTED_CY006_AUDIT_SHA256,
        "CY006_AUDIT",
        registered_root=layout.cy006_root.parent,
    )
    cy006_audit = _json(layout.cy006_audit)
    required_daily_checks = {"coverage", "duplicates", "time_travel", "consistency", "cross_table"}
    checks = cy006_audit.get("checks", {})
    if (
        cy006_audit.get("gate_pass") is not True
        or not required_daily_checks.issubset(checks)
        or any(checks[name].get("status") != "PASS" for name in required_daily_checks)
    ):
        raise CY046BuildError("CY-006 registered audit is not fully PASS")
    cy006_rows = {
        int(item["year"]): int(item["rows"])
        for item in cy006_audit.get("counts", {}).get("per_year", [])
        if int(item.get("year", 0)) in DEVELOPMENT_YEARS
    }
    if set(cy006_rows) != set(DEVELOPMENT_YEARS):
        raise CY046BuildError("CY-006 audit lacks an exact 2018-2021 count binding")

    cy008_cross_binding = _require_file_hash(
        layout.cy008_cross_year_audit,
        EXPECTED_CY008_AUDIT_SHA256,
        "CY008_CROSS_YEAR_AUDIT",
    )
    cy008_cross = _json(layout.cy008_cross_year_audit)
    if cy008_cross.get("pass") is not True or any(
        value is not True for value in cy008_cross.get("checks", {}).values()
    ):
        raise CY046BuildError("CY-008 cross-year audit is not fully PASS")

    cy006_entries = _manifest_entries(cy006_manifest)
    cy008_entries = _manifest_entries(cy008_manifest)
    cy006_bindings: list[dict[str, Any]] = []
    cy008_bindings: list[dict[str, Any]] = []
    annual_audits: list[dict[str, Any]] = []
    for year in DEVELOPMENT_YEARS:
        cy006_relative = f"partition_year={year}/data_0.parquet"
        if cy006_relative not in cy006_entries:
            raise CY046BuildError(f"CY-006 inventory lacks {year}")
        cy006_bindings.append(
            _verify_inventory_partition(
                root=layout.cy006_root,
                entry=cy006_entries[cy006_relative],
                component="CY006",
                expected_rows=cy006_rows[year],
                expected_schema_sha256=EXPECTED_SOURCE_SCHEMA_SHA256["CY006_DAILY"],
            )
        )
        audit_relative = f"audits/year={year}.json"
        execution_relative = f"execution_5m/partition_year={year}/data_0.parquet"
        if audit_relative not in cy008_entries or execution_relative not in cy008_entries:
            raise CY046BuildError(f"CY-008 inventory lacks exact execution/audit pair: {year}")
        audit_path = layout.cy008_root / audit_relative
        audit_entry = cy008_entries[audit_relative]
        annual_binding = _require_file_hash(
            audit_path,
            str(audit_entry.get("sha256", "")),
            f"CY008_ANNUAL_AUDIT_{year}",
            registered_root=layout.cy008_root,
        )
        if annual_binding["size"] != audit_entry.get("size"):
            raise CY046BuildError(f"CY-008 annual audit size drift: {year}")
        annual = _json(audit_path)
        if annual.get("pass") is not True or any(
            value is not True for value in annual.get("checks", {}).values()
        ):
            raise CY046BuildError(f"CY-008 annual audit is not fully PASS: {year}")
        annual_audits.append({**annual_binding, "year": year})
        cy008_bindings.append(
            _verify_inventory_partition(
                root=layout.cy008_root,
                entry=cy008_entries[execution_relative],
                component="CY008",
                expected_rows=int(annual["execution_5m"]["rows"]),
                expected_schema_sha256=EXPECTED_SOURCE_SCHEMA_SHA256[
                    "CY008_EXECUTION_5M"
                ],
            )
        )

    qd010_source_binding = _require_file_hash(
        layout.qd010_source_manifest,
        EXPECTED_QD010_SOURCE_MANIFEST_SHA256,
        "QD010_SOURCE_MANIFEST",
        registered_root=layout.qd010_root,
    )
    qd010_source_manifest = _json(layout.qd010_source_manifest)
    if (
        qd010_source_manifest.get("capture_gate") != "VERIFIED_COMPLETE_CURRENT_SNAPSHOT"
        or qd010_source_manifest.get("complete_for_requested_symbols_and_sources") is not True
        or qd010_source_manifest.get("strict_pit_gate")
        != "BLOCKED_NO_HISTORICAL_REVISION_STREAM"
    ):
        raise CY046BuildError("QD-010 PIT-B source-manifest contract drift")
    qd_entries = _manifest_entries(qd010_manifest)
    normalized = qd010_source_manifest.get("normalized_files", {})
    qd_bindings: list[dict[str, Any]] = []
    for role, relative, schema_role in (
        ("distributions", "normalized/distributions.parquet", "QD010_DISTRIBUTIONS"),
        ("rights_issues", "normalized/rights_issues.parquet", "QD010_RIGHTS"),
    ):
        if relative not in qd_entries or role not in normalized:
            raise CY046BuildError(f"QD-010 lacks exact normalized source: {role}")
        entry = qd_entries[relative]
        path = layout.qd010_root / relative
        path = _require_safe_regular_file(
            path, f"QD-010 {role}", registered_root=layout.qd010_root
        )
        identity = path.lstat()
        observed_hash = sha256_file(path)
        after = path.lstat()
        if (
            (identity.st_dev, identity.st_ino, identity.st_size)
            != (after.st_dev, after.st_ino, after.st_size)
            or identity.st_size != entry.get("size")
            or observed_hash != entry.get("sha256")
        ):
            raise CY046BuildError(f"QD-010 source file drift: {role}")
        footer = parquet_footer_facts(path, registered_root=layout.qd010_root)
        if (
            footer["rows"] != int(normalized[role]["rows"])
            or footer["schema_sha256"] != EXPECTED_SOURCE_SCHEMA_SHA256[schema_role]
            or normalized[role]["sha256"] != entry.get("sha256")
        ):
            raise CY046BuildError(f"QD-010 schema/count/manifest drift: {role}")
        qd_bindings.append(
            {
                "asset_id": "QD-010",
                "role": role,
                "path": str(path.resolve()),
                "inventory_path": relative,
                "sha256": entry["sha256"],
                "size": entry["size"],
                "device": identity.st_dev,
                "inode": identity.st_ino,
                **footer,
                "parquet_rows_opened": False,
            }
        )

    identity_bindings = []
    for role, path, expected_hash, expected_rows, expected_schema in (
        (
            "R4_SELECTED",
            layout.r4_selected,
            EXPECTED_R4_SELECTED_SHA256,
            EXPECTED_R4_SOURCE_ROWS,
            EXPECTED_SOURCE_SCHEMA_SHA256["R4_SELECTED"],
        ),
        (
            "R5_PRIMARY",
            layout.r5_primary,
            EXPECTED_R5_PRIMARY_SHA256,
            EXPECTED_R5_CAP_ROWS,
            EXPECTED_SOURCE_SCHEMA_SHA256["R5_PRIMARY"],
        ),
    ):
        binding = _require_file_hash(path, expected_hash, role)
        footer = parquet_footer_facts(path)
        if footer["rows"] != expected_rows or footer["schema_sha256"] != expected_schema:
            raise CY046BuildError(f"{role} footer count/schema drift")
        identity_bindings.append({**binding, **footer, "parquet_rows_opened": False})

    freezes = [
        _require_file_hash(layout.r4_freeze, EXPECTED_R4_FREEZE_SHA256, "R4_STAGE_A_FREEZE"),
        _require_file_hash(layout.r5_freeze, EXPECTED_R5_FREEZE_SHA256, "R5_STAGE_A_FREEZE"),
    ]
    if _json(layout.r4_freeze).get("output_hashes", {}).get("selected_signals") != (
        EXPECTED_R4_SELECTED_SHA256
    ):
        raise CY046BuildError("R4 freeze does not bind selected identity")
    if _json(layout.r5_freeze).get("output_hashes", {}).get("cap25_identity") != (
        EXPECTED_R5_PRIMARY_SHA256
    ):
        raise CY046BuildError("R5 freeze does not bind primary identity")

    return {
        "asset_id": ASSET_ID,
        "status": "PASS_METADATA_ONLY",
        "mode": "METADATA_DRY_RUN",
        "coverage": {"start": "2018-01-01", "end": "2021-12-31"},
        "registry_snapshot": registry_binding,
        "preregistration": prereg,
        "stage_a_freezes": freezes,
        "frozen_identities": identity_bindings,
        "source_manifests": [
            _require_file_hash(
                layout.cy006_manifest, EXPECTED_CY006_MANIFEST_SHA256, "CY006_INVENTORY"
            ),
            _require_file_hash(
                layout.cy008_manifest, EXPECTED_CY008_MANIFEST_SHA256, "CY008_INVENTORY"
            ),
            _require_file_hash(
                layout.qd010_manifest, EXPECTED_QD010_MANIFEST_SHA256, "QD010_INVENTORY"
            ),
            qd010_source_binding,
        ],
        "source_audits": [cy006_audit_binding, cy008_cross_binding, *annual_audits],
        "cy006_partitions": cy006_bindings,
        "cy008_execution_partitions": cy008_bindings,
        "qd010_sources": qd_bindings,
        "selected_source_partition_years": list(DEVELOPMENT_YEARS),
        "selected_cy008_dataset": "execution_5m/window_index=0_ONLY_AT_CONTENT_BUILD",
        "parquet_rows_opened": False,
        "output_written": False,
        "outcome_or_return_sources_resolved": False,
    }


def _iter_file_bindings(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if {"path", "sha256", "size", "device", "inode"}.issubset(value):
            yield value
        for nested in value.values():
            yield from _iter_file_bindings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _iter_file_bindings(nested)


def revalidate_sources_after_content_read(plan: dict[str, Any]) -> dict[str, Any]:
    """Rehash every planned source and compare device/inode/size before publish."""
    unique: dict[str, dict[str, Any]] = {}
    for binding in _iter_file_bindings(plan):
        path = str(binding["path"])
        if path in unique and any(
            unique[path][field] != binding[field]
            for field in ("sha256", "size", "device", "inode")
        ):
            raise CY046BuildError(f"source plan contains conflicting identities: {path}")
        unique[path] = binding
    if not unique:
        raise CY046BuildError("source plan contains no revalidatable file identities")
    for path_text, expected in sorted(unique.items()):
        path = _require_safe_regular_file(Path(path_text), "post-content source revalidation")
        before = path.lstat()
        observed_hash = sha256_file(path)
        after = path.lstat()
        observed = (after.st_dev, after.st_ino, after.st_size, observed_hash)
        required = (
            int(expected["device"]),
            int(expected["inode"]),
            int(expected["size"]),
            str(expected["sha256"]),
        )
        if (
            (before.st_dev, before.st_ino, before.st_size)
            != (after.st_dev, after.st_ino, after.st_size)
            or observed != required
        ):
            raise CY046BuildError(f"source changed or was retargeted during build: {path}")
    return {
        "files_revalidated": len(unique),
        "sha256_device_inode_size_match": True,
        "path_reopen_limitation": (
            "DuckDB path reads cannot retain one OS file descriptor across the full query; "
            "pre/post SHA256+device+inode+size checks detect but cannot mathematically "
            "exclude a swap-and-restore attack during a read"
        ),
    }


def revalidate_registry_before_publish(
    plan: dict[str, Any], layout: SourceLayout = DEFAULT_LAYOUT
) -> None:
    expected = plan.get("registry_snapshot")
    if not isinstance(expected, dict):
        raise CY046BuildError("source plan lacks a registry snapshot")
    registry, observed = read_json_snapshot(layout.registry, "DATA_ASSET_REGISTRY_FINAL")
    for field in ("path", "sha256", "size", "device", "inode"):
        if observed.get(field) != expected.get(field):
            raise CY046BuildError(f"registry changed during build: {field}")
    _assert_cy046_unregistered(registry)
    observed_entries = {
        asset_id: _canonical_json_sha256(_exact_asset(registry, asset_id))
        for asset_id in ("CY-006", "CY-008", "QD-010")
    }
    if observed_entries != expected.get("registered_input_entry_sha256"):
        raise CY046BuildError("registered CY-006/CY-008/QD-010 entries changed during build")


def _nonempty(value: Any) -> bool:
    return value is not None and not pd.isna(value) and bool(str(value).strip())


def assert_no_forbidden_identity_columns(columns: Iterable[str]) -> None:
    lowered = [str(column).lower() for column in columns]
    bad = sorted(
        column
        for column in lowered
        if any(token in column for token in FORBIDDEN_IDENTITY_COLUMN_TOKENS)
    )
    if bad:
        raise CY046BuildError(f"outcome/return-like identity columns are forbidden: {bad}")


def cap25_industry_round_robin(selected: pd.DataFrame) -> pd.DataFrame:
    """Apply the exact preregistered date/industry/rebound CAP25 admission."""
    required = {
        "gap_id",
        "symbol",
        "signal_date",
        "signal_industry",
        "rebound_from_post_gap_low_over_l",
    }
    if not required.issubset(selected.columns):
        raise CY046BuildError("CAP25 input lacks required frozen identity fields")
    if selected.empty or selected["gap_id"].duplicated().any():
        raise CY046BuildError("CAP25 input is empty or has duplicate gap_id")
    if any(not _nonempty(value) for value in selected["gap_id"]):
        raise CY046BuildError("CAP25 gap identity is empty")
    if any(not _nonempty(value) for value in selected["symbol"]):
        raise CY046BuildError("CAP25 symbol identity is empty")
    if any(not _nonempty(value) for value in selected["signal_industry"]):
        raise CY046BuildError("CAP25 industry identity is empty")
    rebound = pd.to_numeric(selected["rebound_from_post_gap_low_over_l"], errors="coerce")
    if rebound.isna().any() or not np.isfinite(rebound).all():
        raise CY046BuildError("CAP25 rebound rank is missing or nonfinite")
    dates = pd.to_datetime(selected["signal_date"], errors="coerce").dt.normalize()
    if dates.isna().any() or dates.lt(DEVELOPMENT_START).any() or dates.gt(DEVELOPMENT_END).any():
        raise CY046BuildError("CAP25 signal date is missing or outside 2018-2021")

    kept: list[pd.DataFrame] = []
    for signal_date in sorted(dates.unique()):
        event = selected.loc[dates.eq(signal_date)].copy()
        queues = {
            str(industry): group.sort_values(
                ["rebound_from_post_gap_low_over_l", "symbol", "gap_id"],
                ascending=[False, True, True],
                kind="mergesort",
            ).reset_index(drop=True)
            for industry, group in event.groupby("signal_industry", sort=True)
        }
        industries = sorted(queues)
        positions = {industry: 0 for industry in industries}
        rows: list[pd.Series] = []
        while len(rows) < 25:
            advanced = False
            for industry in industries:
                position = positions[industry]
                queue = queues[industry]
                if position >= len(queue):
                    continue
                rows.append(queue.iloc[position])
                positions[industry] += 1
                advanced = True
                if len(rows) == 25:
                    break
            if not advanced:
                break
        if rows:
            frame = pd.DataFrame(rows)
            frame["cap25_rank"] = np.arange(1, len(frame) + 1, dtype=np.int64)
            frame["cap25_primary_economic_admission"] = True
            kept.append(frame)
    if not kept:
        raise CY046BuildError("CAP25 output is empty")
    result = pd.concat(kept, ignore_index=True)
    counts = result.groupby(pd.to_datetime(result.signal_date).dt.normalize()).size()
    if result.gap_id.duplicated().any() or counts.gt(25).any():
        raise CY046BuildError("CAP25 identity/cardinality invariant failed")
    return result


def assert_frozen_counts(
    identity: pd.DataFrame,
    expected_rows: int,
    expected_by_year: dict[int, int],
    role: str,
) -> None:
    years = pd.to_datetime(identity["signal_date"], errors="coerce").dt.year
    observed = {int(key): int(value) for key, value in years.value_counts().sort_index().items()}
    if len(identity) != expected_rows or observed != expected_by_year:
        raise CY046BuildError(
            f"{role} frozen count drift: rows={len(identity)}, by_year={observed}"
        )


def validate_identity_content(identity: pd.DataFrame, role: str) -> None:
    assert_no_forbidden_identity_columns(identity.columns)
    required = {
        "gap_id",
        "symbol",
        "signal_date",
        "signal_time",
        "coordinate_factor",
        "L",
        "signal_available_at",
        "signal_snapshot_id",
        "signal_daily_snapshot_id",
        "signal_trading_state_snapshot_id",
        "signal_industry_snapshot_id",
        "signal_corporate_action_snapshot_id",
    }
    if not required.issubset(identity.columns):
        raise CY046BuildError(f"{role} identity lacks required PIT fields")
    if identity.gap_id.duplicated().any():
        raise CY046BuildError(f"{role} identity has duplicate gap_id")
    dates = pd.to_datetime(identity.signal_date, errors="coerce").dt.normalize()
    times = pd.to_datetime(identity.signal_time, errors="coerce")
    available = pd.to_datetime(identity.signal_available_at, errors="coerce")
    if (
        dates.isna().any()
        or dates.lt(DEVELOPMENT_START).any()
        or dates.gt(DEVELOPMENT_END).any()
        or times.isna().any()
        or available.isna().any()
        or not times.dt.normalize().eq(dates).all()
        or times.dt.hour.ne(15).any()
        or times.dt.minute.ne(0).any()
        or times.dt.second.ne(0).any()
        or available.gt(times).any()
    ):
        raise CY046BuildError(f"{role} identity chronology/PIT failure")
    for column in (
        "gap_id",
        "symbol",
        "signal_snapshot_id",
        "signal_daily_snapshot_id",
        "signal_trading_state_snapshot_id",
        "signal_industry_snapshot_id",
        "signal_corporate_action_snapshot_id",
    ):
        if any(not _nonempty(value) for value in identity[column]):
            raise CY046BuildError(f"{role} identity has empty {column}")
    if not identity.symbol.astype(str).str.fullmatch(r"\d{6}\.(?:SH|SZ)").all():
        raise CY046BuildError(f"{role} identity contains a noncanonical A-share symbol")
    factor = pd.to_numeric(identity.coordinate_factor, errors="coerce")
    level = pd.to_numeric(identity.L, errors="coerce")
    if (
        factor.isna().any()
        or level.isna().any()
        or not np.isfinite(factor).all()
        or not np.isfinite(level).all()
    ):
        raise CY046BuildError(f"{role} coordinate contains nonfinite values")
    if factor.le(0).any() or level.le(0).any():
        raise CY046BuildError(f"{role} coordinate contains nonpositive values")


def market_calendar_frame(trade_dates: Sequence[Any]) -> pd.DataFrame:
    dates = pd.Series(pd.to_datetime(list(trade_dates), errors="coerce")).dt.normalize()
    if dates.isna().any():
        raise CY046BuildError("market calendar contains an invalid date")
    dates = dates.drop_duplicates().sort_values().reset_index(drop=True)
    if dates.empty or dates.lt(DEVELOPMENT_START).any() or dates.gt(DEVELOPMENT_END).any():
        raise CY046BuildError("market calendar is empty or outside 2018-2021")
    return pd.DataFrame(
        {
            "trade_date": dates,
            "calendar_index": np.arange(len(dates), dtype=np.int64),
        }
    )


def attach_administrative_schedule(
    identity: pd.DataFrame, calendar: pd.DataFrame
) -> pd.DataFrame:
    """Attach the fixed +1/+20/+21..+23 schedule using dates only."""
    required = {"trade_date", "calendar_index"}
    if not required.issubset(calendar.columns) or calendar.trade_date.duplicated().any():
        raise CY046BuildError("market calendar identity is invalid")
    if list(calendar.columns) != ["trade_date", "calendar_index"]:
        raise CY046BuildError("market calendar must contain exactly trade_date,calendar_index")
    ordered = calendar.sort_values("calendar_index", kind="mergesort").reset_index(drop=True)
    if not ordered.calendar_index.eq(np.arange(len(ordered))).all():
        raise CY046BuildError("market calendar index is not exact and contiguous")
    dates = pd.to_datetime(ordered.trade_date).dt.normalize().tolist()
    position = {value: index for index, value in enumerate(dates)}
    result = identity.copy()
    schedule: list[dict[str, Any]] = []
    for signal_value in pd.to_datetime(result.signal_date).dt.normalize():
        signal_position = position.get(signal_value)
        if signal_position is None:
            raise CY046BuildError(f"signal date is not a registered market session: {signal_value}")
        mapped_dates = [
            dates[signal_position + offset]
            if signal_position + offset < len(dates)
            else pd.NaT
            for offset in (1, 21, 22, 23, 24)
        ]
        entry_date, h20_date, h21_date, h22_date, h23_date = mapped_dates
        admin_eligible = not pd.isna(h23_date) and h23_date <= DEVELOPMENT_END
        schedule.append(
            {
                "signal_calendar_index": signal_position,
                "entry_date": entry_date,
                "h20_date": h20_date,
                "h21_date": h21_date,
                "h22_date": h22_date,
                "h23_date": h23_date,
                "admin_eligible": admin_eligible,
            }
        )
    schedule_frame = pd.DataFrame.from_records(schedule)
    return pd.concat([result.reset_index(drop=True), schedule_frame], axis=1)


def _sql_string(value: Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _read_parquet_list(paths: Sequence[Path]) -> str:
    safe_paths = [
        _require_safe_regular_file(path, "DuckDB Parquet input") for path in paths
    ]
    return "[" + ",".join(_sql_string(path) for path in safe_paths) + "]"


def _source_paths(plan: dict[str, Any], key: str) -> list[Path]:
    return [Path(item["path"]) for item in plan[key]]


def _load_identity_projection(path: Path, columns: Sequence[str]) -> pd.DataFrame:
    """Read only frozen identity fields through DuckDB (never pandas/pyarrow decode)."""
    path = _require_safe_regular_file(path, "frozen Stage-A identity")
    projection = ",".join(f'"{column}"' for column in columns)
    query = f"SELECT {projection} FROM read_parquet({_sql_string(path)})"
    with duckdb.connect() as connection:
        return connection.execute(query).fetch_df()


def _load_calendar(cy006_paths: Sequence[Path]) -> pd.DataFrame:
    query = f"""
        SELECT DISTINCT trade_date
        FROM read_parquet({_read_parquet_list(cy006_paths)})
        WHERE trade_date >= DATE '2018-01-01'
          AND trade_date <= DATE '2021-12-31'
        ORDER BY trade_date
    """
    with duckdb.connect() as connection:
        dates = connection.execute(query).fetch_df()["trade_date"].tolist()
    return market_calendar_frame(dates)


def _path_requests(identity: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in identity.to_dict(orient="records"):
        if row["admin_eligible"] is not True:
            continue
        signal_date = pd.Timestamp(row["signal_date"]).normalize()
        entry_date = pd.Timestamp(row["entry_date"]).normalize()
        for signal_offset in range(25):
            trade_date = pd.Timestamp(
                row["_calendar_dates"][row["signal_calendar_index"] + signal_offset]
            ).normalize()
            rows.append(
                {
                    "protocol_arm": row["protocol_arm"],
                    "gap_id": row["gap_id"],
                    "symbol": row["symbol"],
                    "signal_date": signal_date,
                    "entry_date": entry_date,
                    "trade_date": trade_date,
                    "signal_session_offset": signal_offset,
                    "entry_session_offset": signal_offset - 1,
                    "_frozen_signal_snapshot_id": row["signal_snapshot_id"],
                    "_frozen_signal_daily_snapshot_id": row[
                        "signal_daily_snapshot_id"
                    ],
                    "_frozen_signal_corporate_action_snapshot_id": row[
                        "signal_corporate_action_snapshot_id"
                    ],
                }
            )
    return pd.DataFrame.from_records(rows)


def make_path_requests(identity: pd.DataFrame, calendar: pd.DataFrame) -> pd.DataFrame:
    """Construct exact signal and entry..H23 evidence keys for eligible identities."""
    calendar_dates = pd.to_datetime(
        calendar.sort_values("calendar_index").trade_date
    ).dt.normalize().tolist()
    work = identity.copy()
    work["_calendar_dates"] = [calendar_dates] * len(work)
    requests = _path_requests(work)
    if requests.empty:
        raise CY046BuildError("administrative censor left no bounded path requests")
    key = ["protocol_arm", "gap_id", "trade_date"]
    if requests.duplicated(key).any():
        raise CY046BuildError("candidate path request contains duplicate identity/date")
    if pd.to_datetime(requests.trade_date).gt(DEVELOPMENT_END).any():
        raise CY046BuildError("candidate path request escaped 2021")
    expected_rows = int(identity.admin_eligible.eq(True).sum()) * 25
    if len(requests) != expected_rows:
        raise CY046BuildError("candidate daily request does not contain signal..H23 exactly")
    offsets = requests.groupby(["protocol_arm", "gap_id"], sort=False).agg(
        signal_min=("signal_session_offset", "min"),
        signal_max=("signal_session_offset", "max"),
        entry_min=("entry_session_offset", "min"),
        entry_max=("entry_session_offset", "max"),
        rows=("trade_date", "size"),
    )
    if not (
        offsets.signal_min.eq(0).all()
        and offsets.signal_max.eq(24).all()
        and offsets.entry_min.eq(-1).all()
        and offsets.entry_max.eq(23).all()
        and offsets.rows.eq(25).all()
    ):
        raise CY046BuildError("candidate path offset interface drift")
    return requests


def _extract_daily_path(requests: pd.DataFrame, paths: Sequence[Path]) -> pd.DataFrame:
    source_fields = [column for column in CY006_COLUMNS if column not in {"symbol", "trade_date"}]
    select_source = ",".join(f"source.{column}" for column in source_fields)
    request_fields = [
        "protocol_arm",
        "gap_id",
        "symbol",
        "signal_date",
        "entry_date",
        "trade_date",
        "signal_session_offset",
        "entry_session_offset",
    ]
    with duckdb.connect() as connection:
        connection.register("path_requests", requests)
        query = f"""
            WITH source AS (
                SELECT {','.join(CY006_COLUMNS)}
                FROM read_parquet({_read_parquet_list(paths)})
                WHERE trade_date >= DATE '2018-01-01'
                  AND trade_date <= DATE '2021-12-31'
            )
            SELECT {','.join(f'request.{field}' for field in request_fields)},
                   {select_source},
                   source.symbol IS NOT NULL AS source_row_present,
                   request._frozen_signal_snapshot_id,
                   request._frozen_signal_daily_snapshot_id,
                   request._frozen_signal_corporate_action_snapshot_id
            FROM path_requests AS request
            LEFT JOIN source
              ON source.symbol = request.symbol
             AND source.trade_date = request.trade_date
            ORDER BY request.protocol_arm, request.gap_id, request.trade_date
        """
        result = connection.execute(query).fetch_df()
    expected = len(requests)
    if len(result) != expected:
        raise CY046BuildError("CY-006 requested-key uniqueness drift")
    if pd.to_datetime(result.trade_date).gt(DEVELOPMENT_END).any():
        raise CY046BuildError("CY-006 extraction escaped 2021")
    present = result.source_row_present.eq(True)
    pit_bad = present & (
        pd.to_datetime(result.available_at, errors="coerce")
        > pd.to_datetime(result.decision_at, errors="coerce")
    )
    if pit_bad.any():
        raise CY046BuildError("CY-006 contains an available_at > decision_at violation")
    hard_valid = present & result.hard_valid.eq(True)
    for column in (
        "available_at",
        "decision_at",
        "snapshot_id",
        "daily_snapshot_id",
        "trading_state_snapshot_id",
        "corporate_action_snapshot_id",
    ):
        if result.loc[hard_valid, column].map(_nonempty).eq(False).any():
            raise CY046BuildError(f"hard-valid CY-006 row lacks {column}")
    signal_rows = result.signal_session_offset.eq(0)
    binding_bad = signal_rows & (
        ~present
        | result.snapshot_id.astype(str).ne(result._frozen_signal_snapshot_id.astype(str))
        | result.daily_snapshot_id.astype(str).ne(
            result._frozen_signal_daily_snapshot_id.astype(str)
        )
        | result.corporate_action_snapshot_id.astype(str).ne(
            result._frozen_signal_corporate_action_snapshot_id.astype(str)
        )
    )
    if binding_bad.any():
        raise CY046BuildError("frozen signal snapshots do not bind candidate CY-006 signal row")
    return result.drop(
        columns=[
            "_frozen_signal_snapshot_id",
            "_frozen_signal_daily_snapshot_id",
            "_frozen_signal_corporate_action_snapshot_id",
        ]
    )


def _extract_execution_path(requests: pd.DataFrame, paths: Sequence[Path]) -> pd.DataFrame:
    execution_requests = requests.loc[requests.entry_session_offset.ge(0)].copy()
    source_fields = [column for column in CY008_COLUMNS if column not in {"symbol", "trade_date"}]
    select_source = ",".join(f"source.{column}" for column in source_fields)
    request_fields = [
        "protocol_arm",
        "gap_id",
        "symbol",
        "signal_date",
        "entry_date",
        "trade_date",
        "signal_session_offset",
        "entry_session_offset",
    ]
    with duckdb.connect() as connection:
        connection.register("execution_requests", execution_requests)
        query = f"""
            WITH source AS (
                SELECT {','.join(CY008_COLUMNS)}
                FROM read_parquet({_read_parquet_list(paths)})
                WHERE trade_date >= DATE '2018-01-01'
                  AND trade_date <= DATE '2021-12-31'
                  AND window_index = 0
            )
            SELECT {','.join(f'request.{field}' for field in request_fields)},
                   {select_source},
                   source.symbol IS NOT NULL AS source_row_present
            FROM execution_requests AS request
            LEFT JOIN source
              ON source.symbol = request.symbol
             AND source.trade_date = request.trade_date
            ORDER BY request.protocol_arm, request.gap_id, request.trade_date
        """
        result = connection.execute(query).fetch_df()
    if len(result) != len(execution_requests):
        raise CY046BuildError("CY-008 window0 requested-key uniqueness drift")
    if result.loc[result.source_row_present.eq(True), "window_index"].ne(0).any():
        raise CY046BuildError("CY-008 extraction contains a non-window0 row")
    if pd.to_datetime(result.trade_date).gt(DEVELOPMENT_END).any():
        raise CY046BuildError("CY-008 extraction escaped 2021")
    if not (
        result.signal_session_offset.between(1, 24).all()
        and result.entry_session_offset.between(0, 23).all()
    ):
        raise CY046BuildError("CY-008 extraction offset interface drift")
    hard_valid = result.source_row_present.eq(True) & result.hard_valid.eq(True)
    for column in ("available_at", "snapshot_id", "daily_snapshot_id"):
        if result.loc[hard_valid, column].map(_nonempty).eq(False).any():
            raise CY046BuildError(f"hard-valid CY-008 row lacks {column}")
    available = pd.to_datetime(result.loc[hard_valid, "available_at"], errors="coerce")
    if (
        available.isna().any()
        or available.dt.normalize().ne(
            pd.to_datetime(result.loc[hard_valid, "trade_date"]).dt.normalize()
        ).any()
        or available.dt.hour.ne(9).any()
        or available.dt.minute.ne(35).any()
        or result.loc[hard_valid, "source_resolution_minutes"].ne(1).any()
        or result.loc[hard_valid, "minute_count"].ne(5).any()
        or result.loc[hard_valid, "distinct_minute_count"].ne(5).any()
    ):
        raise CY046BuildError("hard-valid CY-008 window0 timing/completeness drift")
    return result


def validate_execution_daily_snapshot_binding(
    execution: pd.DataFrame, daily: pd.DataFrame
) -> dict[str, int]:
    """Bind every CY-008 window0 row to the exact CY-006 daily snapshot."""
    keys = ["protocol_arm", "gap_id", "trade_date"]
    daily_binding = daily[[*keys, "source_row_present", "snapshot_id"]].rename(
        columns={
            "source_row_present": "bound_cy006_row_present",
            "snapshot_id": "bound_cy006_snapshot_id",
        }
    )
    if daily_binding.duplicated(keys).any() or execution.duplicated(keys).any():
        raise CY046BuildError("snapshot binding keys are not unique")
    result = execution.merge(daily_binding, on=keys, how="left", validate="one_to_one")
    both_present = result.source_row_present.eq(True) & result.bound_cy006_row_present.eq(
        True
    )
    both_nonempty = (
        result.daily_snapshot_id.map(_nonempty)
        & result.bound_cy006_snapshot_id.map(_nonempty)
    )
    binding_valid = (
        both_present
        & both_nonempty
        & result.daily_snapshot_id.astype(str).eq(
            result.bound_cy006_snapshot_id.astype(str)
        )
    )
    mismatch = both_present & both_nonempty & ~binding_valid
    if mismatch.any():
        raise CY046BuildError("CY-008 daily_snapshot_id conflicts with bound CY-006 snapshot_id")
    return {
        "paired_nonempty_snapshot_conflicts": int(mismatch.sum()),
        "missing_or_unbound_snapshot_rows_preserved": int((~binding_valid).sum()),
    }


def validate_action_event_timing(events: pd.DataFrame) -> None:
    """Require the conservative availability alias and strict pre-effective timing."""
    parsed: dict[str, pd.Series] = {}
    for column in ("effective_date", "known_at", "available_at"):
        try:
            values = pd.to_datetime(events[column], errors="coerce")
            timezone = values.dt.tz
        except (AttributeError, TypeError, ValueError) as exc:
            raise CY046BuildError(
                f"QD-010 candidate event has noncanonical {column} timezone"
            ) from exc
        if timezone is not None:
            raise CY046BuildError(
                f"QD-010 candidate event {column} must be timezone-naive"
            )
        parsed[column] = values
    effective = parsed["effective_date"]
    known = parsed["known_at"]
    available = parsed["available_at"]
    if effective.isna().any() or known.isna().any() or available.isna().any():
        raise CY046BuildError("QD-010 candidate event has missing known/effective/available timing")
    if not effective.eq(effective.dt.normalize()).all():
        raise CY046BuildError(
            "QD-010 effective_date must be a timezone-naive date-only midnight"
        )
    if not available.eq(known).all():
        raise CY046BuildError("QD-010 available_at alias is not exactly known_at")
    if not known.lt(effective).all() or not available.lt(effective).all():
        raise CY046BuildError("QD-010 candidate event fails strict pre-effective causal timing")


def validate_action_effective_sessions(
    events: pd.DataFrame, calendar: pd.DataFrame
) -> None:
    if list(calendar.columns) != ["trade_date", "calendar_index"]:
        raise CY046BuildError("QD-010 action calendar schema is not frozen/exact")
    dates = pd.to_datetime(calendar.trade_date, errors="coerce").dt.normalize()
    if (
        dates.isna().any()
        or dates.duplicated().any()
        or not calendar.calendar_index.eq(np.arange(len(calendar))).all()
    ):
        raise CY046BuildError("QD-010 action calendar is not unique and contiguous")
    effective = pd.to_datetime(events.effective_date, errors="coerce").dt.normalize()
    if effective.isna().any() or not effective.isin(set(dates)).all():
        raise CY046BuildError("QD-010 effective_date is not a frozen market session")


def _decimal_source_term(value: Any) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def classify_qd_action_terms(row: pd.Series | dict[str, Any]) -> str:
    """Classify exact source-string Decimals; binary floats never decide the class."""
    get = row.get
    complete = (
        get("source_terms_complete") is not None
        and not pd.isna(get("source_terms_complete"))
        and bool(get("source_terms_complete"))
    )
    if not complete:
        return "UNSUPPORTED_OR_UNKNOWN"
    cash = _decimal_source_term(get("cash_per_share_gross"))
    multiplier = _decimal_source_term(get("share_multiplier"))
    rights_ratio = _decimal_source_term(get("rights_subscription_ratio"))
    rights_price = _decimal_source_term(get("rights_subscription_price"))
    if get("source_table") == "RIGHTS":
        if (
            rights_ratio is not None
            and rights_ratio > 0
            and rights_price is not None
            and rights_price >= 0
        ):
            return "RISK_RIGHTS"
        return "UNSUPPORTED_OR_UNKNOWN"
    if get("source_table") != "DISTRIBUTION":
        return "UNSUPPORTED_OR_UNKNOWN"
    if multiplier is None or multiplier <= 0:
        return "UNSUPPORTED_OR_UNKNOWN"
    if multiplier != 1:
        if rights_ratio is not None and rights_ratio == 0 and (cash is None or cash >= 0):
            return "RISK_SHARE"
        return "UNSUPPORTED_OR_UNKNOWN"
    if cash is None or cash < 0 or rights_ratio is None or rights_ratio != 0:
        return "UNSUPPORTED_OR_UNKNOWN"
    return "CASH_ONLY"


def _extract_action_events(
    candidates: pd.DataFrame,
    paths: Sequence[Path],
    calendar: pd.DataFrame,
) -> pd.DataFrame:
    candidate_columns = [
        "protocol_arm",
        "gap_id",
        "symbol",
        "signal_date",
        "entry_date",
        "h23_date",
    ]
    candidate_scope = candidates.loc[candidates.admin_eligible.eq(True), candidate_columns].copy()
    if candidate_scope.empty or not candidate_scope.symbol.astype(str).str.fullmatch(
        r"\d{6}\.(?:SH|SZ)"
    ).all():
        raise CY046BuildError("QD-010 candidate scope has a noncanonical symbol")
    qd_projection = ",".join(
        "source.symbol AS event_symbol" if column == "symbol" else f"source.{column}"
        for column in QD010_COLUMNS
    )
    with duckdb.connect() as connection:
        connection.register("candidate_scope", candidate_scope)
        query = f"""
            WITH source AS (
                SELECT *, filename
                FROM read_parquet(
                    {_read_parquet_list(paths)}, union_by_name=true, filename=true
                )
            )
            SELECT
                candidate.protocol_arm,
                candidate.gap_id,
                candidate.symbol,
                candidate.signal_date,
                candidate.entry_date,
                candidate.h23_date,
                CAST(NULL AS VARCHAR) AS action_kind,
                CASE WHEN source.filename LIKE '%rights_issues.parquet'
                     THEN 'RIGHTS' ELSE 'DISTRIBUTION' END AS source_table,
                'QD-010' AS source_asset_id,
                {_sql_string(QD010_SOURCE_SNAPSHOT_ID)} AS source_snapshot_id,
                {_sql_string(QD010_SOURCE_SNAPSHOT_ID)} AS snapshot_id,
                source.known_at AS available_at,
                source.cash_per_share_gross AS cash_per_share,
                source.rights_subscription_ratio AS rights_ratio,
                source.rights_subscription_price AS rights_price,
                {qd_projection}
            FROM source
            INNER JOIN candidate_scope candidate
              ON source.symbol = candidate.symbol
            WHERE (
                source.effective_date > candidate.signal_date
                AND source.effective_date <= candidate.h23_date
            ) OR (
                source.effective_date IS NULL
                AND (
                    source.known_at IS NULL
                    OR source.known_at < candidate.h23_date + INTERVAL 1 DAY
                )
            )
            ORDER BY candidate.protocol_arm, candidate.gap_id,
                     source.effective_date, source.known_at, source.event_id, source_table
        """
        result = connection.execute(query).fetch_df()
    if not result.empty:
        result["action_kind"] = result.apply(classify_qd_action_terms, axis=1)
    validate_action_event_timing(result)
    validate_action_effective_sessions(result, calendar)
    for alias, source in (
        ("cash_per_share", "cash_per_share_gross"),
        ("rights_ratio", "rights_subscription_ratio"),
        ("rights_price", "rights_subscription_price"),
    ):
        equal = result[alias].eq(result[source]) | (
            result[alias].isna() & result[source].isna()
        )
        if not equal.all():
            raise CY046BuildError(f"QD-010 {alias} alias is not exactly {source}")
    effective = pd.to_datetime(result.effective_date, errors="coerce")
    if effective.gt(DEVELOPMENT_END).any():
        raise CY046BuildError("QD-010 bounded event ledger escaped 2021")
    if not result.event_symbol.astype(str).str.fullmatch(r"\d{6}\.(?:SH|SZ)").all():
        raise CY046BuildError("QD-010 event has a noncanonical symbol")
    if not result.event_symbol.astype(str).eq(result.symbol.astype(str)).all():
        raise CY046BuildError("QD-010 event symbol is not an exact candidate symbol match")
    candidate_keys = ["protocol_arm", "gap_id"]
    for event_key in (
        "event_id",
        "row_hash",
        "source_record_id",
        "source_event_key",
        "source_natural_key",
        "revision_id",
        "vintage_observation_id",
    ):
        if result.duplicated([*candidate_keys, event_key], keep=False).any():
            raise CY046BuildError(
                f"QD-010 candidate event/revision identity is duplicated: {event_key}"
            )
    required_identity = (
        "event_id",
        "row_hash",
        "revision_id",
        "vintage_observation_id",
        "source_record_id",
        "source_event_key",
        "source_natural_key",
        "source",
        "source_api",
        "known_at_precision",
        "known_at_semantics",
        "vintage_id",
        "response_sha256",
        "source_revision",
        "event_identity_quality",
        "source_snapshot_id",
        "snapshot_id",
    )
    if any(result[column].map(_nonempty).eq(False).any() for column in required_identity):
        raise CY046BuildError("QD-010 candidate event lineage is incomplete")
    if (
        not result.row_hash.astype(str).str.fullmatch(r"[0-9a-f]{64}").all()
        or not result.response_sha256.astype(str).str.fullmatch(r"[0-9a-f]{64}").all()
        or not result.source_asset_id.eq("QD-010").all()
        or not result.source_snapshot_id.eq(QD010_SOURCE_SNAPSHOT_ID).all()
        or not result.snapshot_id.eq(QD010_SOURCE_SNAPSHOT_ID).all()
    ):
        raise CY046BuildError("QD-010 candidate event frozen lineage format/binding is invalid")
    if result.source_terms_complete.ne(True).any():
        raise CY046BuildError("QD-010 candidate event source terms are incomplete")
    if result.action_kind.eq("UNSUPPORTED_OR_UNKNOWN").any():
        raise CY046BuildError("QD-010 candidate event class/terms are ambiguous")
    if not result.source_table.isin(["DISTRIBUTION", "RIGHTS"]).all():
        raise CY046BuildError("QD-010 candidate event source table is unknown")
    return result


def _write_parquet(frame: pd.DataFrame, path: Path, role: str) -> None:
    schema = OUTPUT_ARROW_SCHEMAS.get(role)
    if schema is None or tuple(frame.columns) != EXPECTED_OUTPUT_COLUMNS.get(role):
        raise CY046BuildError(f"no exact output schema for {role}")
    try:
        table = pa.Table.from_pandas(
            frame, schema=schema, preserve_index=False, safe=True
        )
    except (pa.ArrowException, ValueError, TypeError) as exc:
        raise CY046BuildError(f"{role} cannot cast to its explicit Arrow schema") from exc
    if not table.schema.equals(schema, check_metadata=False):
        raise CY046BuildError(f"{role} explicit Arrow schema drift")
    pq.write_table(table, path, compression="zstd", use_dictionary=True)
    _fsync_file(path)


def _output_binding(path: Path, role: str) -> dict[str, Any]:
    footer = parquet_footer_facts(path)
    return {
        "role": role,
        "path": path.name,
        "sha256": sha256_file(path),
        "size": path.stat().st_size,
        **footer,
    }


def _json_write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _fsync_file(path)


def candidate_admin_bounds_frame(identity: pd.DataFrame) -> pd.DataFrame:
    result = identity[list(ADMIN_BOUND_COLUMNS)].copy()
    if result.duplicated(["protocol_arm", "gap_id"]).any():
        raise CY046BuildError("administrative-bound candidate identity is duplicated")
    return result.sort_values(
        ["protocol_arm", "signal_date", "gap_id"], kind="mergesort"
    ).reset_index(drop=True)


def _audit_counts(
    r4: pd.DataFrame,
    r5: pd.DataFrame,
    admin: pd.DataFrame,
    daily: pd.DataFrame,
    execution: pd.DataFrame,
    actions: pd.DataFrame,
    snapshot_binding: dict[str, int],
) -> dict[str, Any]:
    return {
        "r4_cap25_rows": len(r4),
        "r5_cap25_rows": len(r5),
        "administrative_bound_rows": len(admin),
        "r4_administratively_eligible": int(
            admin.loc[admin.protocol_arm.eq("V29R4_CAP25"), "admin_eligible"].eq(True).sum()
        ),
        "r4_administratively_censored": int(
            admin.loc[admin.protocol_arm.eq("V29R4_CAP25"), "admin_eligible"].ne(True).sum()
        ),
        "r5_administratively_eligible": int(
            admin.loc[admin.protocol_arm.eq("V29R5_CAP25"), "admin_eligible"].eq(True).sum()
        ),
        "r5_administratively_censored": int(
            admin.loc[admin.protocol_arm.eq("V29R5_CAP25"), "admin_eligible"].ne(True).sum()
        ),
        "cy006_requested_rows": len(daily),
        "cy006_missing_rows_preserved": int(daily.source_row_present.ne(True).sum()),
        "cy006_hard_invalid_rows_preserved": int(
            (daily.source_row_present.eq(True) & daily.hard_valid.ne(True)).sum()
        ),
        "cy008_requested_window0_rows": len(execution),
        "cy008_missing_rows_preserved": int(execution.source_row_present.ne(True).sum()),
        "cy008_hard_invalid_rows_preserved": int(
            (execution.source_row_present.eq(True) & execution.hard_valid.ne(True)).sum()
        ),
        "cy008_or_cy006_snapshot_missing_rows_preserved": int(
            snapshot_binding["missing_or_unbound_snapshot_rows_preserved"]
        ),
        "cy008_cy006_nonempty_snapshot_conflicts": snapshot_binding[
            "paired_nonempty_snapshot_conflicts"
        ],
        "qd010_bounded_event_rows": len(actions),
        "qd010_cash_only_rows": int(actions.action_kind.eq("CASH_ONLY").sum()),
        "qd010_risk_share_rows": int(actions.action_kind.eq("RISK_SHARE").sum()),
        "qd010_risk_rights_rows": int(actions.action_kind.eq("RISK_RIGHTS").sum()),
        "qd010_unresolved_or_unsupported_rows": 0,
        "post_2021_rows": 0,
        "invalid_rows_filtered": 0,
    }


def build_asset(
    runner_path: Path,
    output_root: Path = TARGET_ROOT,
    layout: SourceLayout = DEFAULT_LAYOUT,
) -> dict[str, Any]:
    """Materialize CY-046 atomically.  This is never called by dry-run/verify."""
    if output_root != TARGET_ROOT:
        raise CY046BuildError(f"formal CY-046 output path is fixed: {TARGET_ROOT}")
    if output_root.exists() or output_root.is_symlink():
        raise CY046BuildError(f"canonical CY-046 already exists: {output_root}")
    runner_path = _require_safe_regular_file(runner_path, "STAGE_B_RUNNER")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    probe_uf_immutable_capability(output_root.parent)
    runner_sha256 = sha256_file(runner_path)
    runner_binding = _require_file_hash(
        runner_path, runner_sha256, "STAGE_B_RUNNER"
    )
    plan = metadata_dry_run(layout)

    r4_source = _load_identity_projection(layout.r4_selected, R4_IDENTITY_COLUMNS)
    r5 = _load_identity_projection(layout.r5_primary, R5_IDENTITY_COLUMNS)
    validate_identity_content(r4_source, "V29R4")
    validate_identity_content(r5, "V29R5")
    r4 = cap25_industry_round_robin(r4_source)
    assert_frozen_counts(r4, EXPECTED_R4_CAP_ROWS, EXPECTED_R4_CAP_BY_YEAR, "V29R4_CAP25")
    assert_frozen_counts(r5, EXPECTED_R5_CAP_ROWS, EXPECTED_R5_CAP_BY_YEAR, "V29R5_CAP25")
    if not r5.cap25_primary_economic_admission.eq(True).all():
        raise CY046BuildError("V29R5 primary admission flag drift")
    r5_rederived = cap25_industry_round_robin(r5.drop(columns=["cap25_rank"]))
    rank_compare = r5[["gap_id", "cap25_rank"]].merge(
        r5_rederived[["gap_id", "cap25_rank"]],
        on="gap_id",
        how="outer",
        suffixes=("_frozen", "_rederived"),
        validate="one_to_one",
    )
    if not rank_compare.cap25_rank_frozen.eq(rank_compare.cap25_rank_rederived).all():
        raise CY046BuildError("V29R5 frozen CAP25 rank is not algorithm-equivalent")

    calendar = _load_calendar(_source_paths(plan, "cy006_partitions"))
    r4.insert(0, "protocol_arm", "V29R4_CAP25")
    r5.insert(0, "protocol_arm", "V29R5_CAP25")
    r4_scheduled = attach_administrative_schedule(r4, calendar)
    r5_scheduled = attach_administrative_schedule(r5, calendar)
    if int(r4_scheduled.admin_eligible.eq(True).sum()) != 251:
        raise CY046BuildError("V29R4 administrative eligibility must be exactly 251/251")
    if (
        int(r5_scheduled.admin_eligible.eq(True).sum()) != 254
        or int(r5_scheduled.admin_eligible.ne(True).sum()) != 1
    ):
        raise CY046BuildError("V29R5 administrative eligibility must be exactly 254/255")
    union_identity = pd.concat([r4_scheduled, r5_scheduled], ignore_index=True, sort=False)
    if union_identity.duplicated(["protocol_arm", "gap_id"]).any():
        raise CY046BuildError("union candidate identity is duplicated")
    admin = candidate_admin_bounds_frame(union_identity)
    requests = make_path_requests(union_identity, calendar)
    daily = _extract_daily_path(requests, _source_paths(plan, "cy006_partitions"))
    execution = _extract_execution_path(
        requests, _source_paths(plan, "cy008_execution_partitions")
    )
    snapshot_binding = validate_execution_daily_snapshot_binding(execution, daily)
    actions = _extract_action_events(
        union_identity,
        [Path(item["path"]) for item in plan["qd010_sources"]],
        calendar,
    )
    if len(daily) != 505 * 25 or len(execution) != 505 * 24:
        raise CY046BuildError("candidate-keyed daily/execution bounded row count drift")
    source_revalidation = revalidate_sources_after_content_read(plan)

    r4_identity = r4[list(IDENTITY_OUTPUT_COLUMNS)].copy()
    r5_identity = r5[list(IDENTITY_OUTPUT_COLUMNS)].copy()

    lock_fd: int | None = None
    lock_owned = False
    published = False
    temporary = output_root.with_name(f".{output_root.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    try:
        lock_fd = os.open(BUILD_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o400)
        lock_owned = True
        os.write(lock_fd, f"pid={os.getpid()}\n".encode("ascii"))
        os.close(lock_fd)
        lock_fd = None
        temporary.mkdir(mode=0o700, exist_ok=False)
        frames = {
            "v29r4_cap25_identity": r4_identity,
            "v29r5_cap25_identity": r5_identity,
            "candidate_admin_bounds": admin,
            "candidate_daily_path": daily,
            "candidate_execution_window0": execution,
            "candidate_action_events": actions,
            "market_calendar": calendar,
        }
        for role, frame in frames.items():
            if tuple(frame.columns) != EXPECTED_OUTPUT_COLUMNS[role]:
                raise CY046BuildError(
                    f"{role} output schema/order drift: {list(frame.columns)}"
                )
            _write_parquet(frame, temporary / OUTPUT_FILES[role], role)
        output_bindings = [
            _output_binding(temporary / OUTPUT_FILES[role], role) for role in OUTPUT_FILES
        ]
        audit_counts = _audit_counts(
            r4_identity,
            r5_identity,
            admin,
            daily,
            execution,
            actions,
            snapshot_binding,
        )
        manifest = {
            "asset_id": ASSET_ID,
            "status": "PASS",
            "authorization_id": AUTHORIZATION_ID,
            "coverage": {"start": "2018-01-01", "end": "2021-12-31"},
            "protocol": {
                "path": str(layout.preregistration.resolve()),
                "sha256": EXPECTED_PREREGISTRATION_SHA256,
                "runner_path": runner_binding["path"],
                "runner_sha256": runner_binding["sha256"],
                "builder_path": str(Path(__file__).resolve()),
                "builder_sha256": sha256_file(Path(__file__)),
            },
            "files": output_bindings,
            "source_bindings": plan,
            "pit_contract": PIT_CONTRACT,
            "content_contract": {
                "sequential_arms": ["V29R4_CAP25", "V29R5_CAP25"],
                "v29r4_cap25_exact_rows": EXPECTED_R4_CAP_ROWS,
                "v29r4_by_signal_year": EXPECTED_R4_CAP_BY_YEAR,
                "v29r5_cap25_exact_rows": EXPECTED_R5_CAP_ROWS,
                "v29r5_by_signal_year": EXPECTED_R5_CAP_BY_YEAR,
                "v29r4_admin_eligible": 251,
                "v29r5_admin_eligible": 254,
                "v29r5_admin_censored": 1,
                "administrative_censor_before_price_or_action_join": True,
                "candidate_daily_signal_session_offsets": [0, 24],
                "candidate_daily_entry_session_offsets": [-1, 23],
                "candidate_execution_signal_session_offsets": [1, 24],
                "candidate_execution_entry_session_offsets": [0, 23],
                "cy008_window_index": 0,
                "cy008_daily_snapshot_bound_to_cy006_snapshot": True,
                "candidate_action_effective_interval": "(signal_date,h23_date]",
                "qd010_aliases": {
                    "available_at": "known_at",
                    "cash_per_share": "cash_per_share_gross",
                    "rights_ratio": "rights_subscription_ratio",
                    "rights_price": "rights_subscription_price",
                    "snapshot_id": "source_snapshot_id",
                },
                "ambiguous_or_incomplete_qd010_policy": (
                    "ABORT_ACTIVATION_WITHOUT_CANONICAL_PUBLICATION"
                ),
                "cy006_cy008_invalid_or_missing_evidence_preserved": True,
                "invalid_rows_filtered": 0,
                "post_2021_rows": 0,
                "outcome_or_return_source_columns": [],
                "returns_computed": False,
                "manifest_does_not_hash_activation_audit": True,
                "post_content_source_revalidation": source_revalidation,
                "macos_readonly_uf_immutable_required": True,
                "output_schema_sha256": OUTPUT_SCHEMA_SHA256,
            },
        }
        manifest_path = temporary / "asset_manifest.json"
        _json_write(manifest_path, manifest)
        activation_audit = {
            "asset_id": ASSET_ID,
            "status": "PASS",
            "gate_pass": True,
            "manifest_path": "asset_manifest.json",
            "manifest_sha256": sha256_file(manifest_path),
            "preregistration_sha256": EXPECTED_PREREGISTRATION_SHA256,
            "runner_sha256": runner_binding["sha256"],
            "asset_builder_sha256": sha256_file(Path(__file__)),
            "source_metadata_gate": "PASS",
            "identity_count_gate": "PASS",
            "scope_gate": "PASS",
            "snapshot_nonempty_conflict_gate": "PASS",
            "post_2021_rows": 0,
            "outcome_or_return_source_columns": [],
            "audit_counts": audit_counts,
            "parquet_rows_opened_for_content_build": True,
            "outcome_or_return_rows_opened": False,
            "returns_computed": False,
            "registry_modified": False,
            "post_content_source_revalidation": source_revalidation,
            "output_schema_sha256": OUTPUT_SCHEMA_SHA256,
            "pit_contract": PIT_CONTRACT,
        }
        _json_write(temporary / "activation_audit.json", activation_audit)
        actual = {path.name for path in temporary.iterdir()}
        if actual != EXACT_CANONICAL_FILENAMES:
            raise CY046BuildError(
                f"unexpected or missing canonical output files: {sorted(actual)}"
            )
        for path in temporary.iterdir():
            path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        revalidate_registry_before_publish(plan, layout)
        atomic_publish_directory_no_replace(temporary, output_root)
        published = True
        seal_canonical_asset_immutable(output_root)
        return verify_built_metadata(output_root)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        if published and output_root.exists() and not output_root.is_symlink():
            clear_canonical_asset_immutability(output_root)
            shutil.rmtree(output_root)
        raise
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        if lock_owned:
            try:
                BUILD_LOCK.unlink()
            except FileNotFoundError:
                pass


def validate_manifest_audit_cross_binding(
    manifest: dict[str, Any], audit: dict[str, Any], manifest_sha256: str
) -> None:
    protocol = manifest.get("protocol", {})
    if (
        set(manifest) != MANIFEST_TOP_LEVEL_KEYS
        or set(audit) != ACTIVATION_AUDIT_TOP_LEVEL_KEYS
        or audit.get("manifest_path") != "asset_manifest.json"
        or audit.get("manifest_sha256") != manifest_sha256
        or audit.get("preregistration_sha256") != protocol.get("sha256")
        or audit.get("runner_sha256") != protocol.get("runner_sha256")
        or audit.get("asset_builder_sha256") != protocol.get("builder_sha256")
        or audit.get("returns_computed") is not False
        or audit.get("outcome_or_return_rows_opened") is not False
        or audit.get("registry_modified") is not False
        or manifest.get("pit_contract") != PIT_CONTRACT
        or audit.get("pit_contract") != manifest.get("pit_contract")
    ):
        raise CY046BuildError("CY-046 activation audit/manifest cross-binding drift")


def validate_audit_counts_against_outputs(
    manifest: dict[str, Any], audit: dict[str, Any], observed_rows: dict[str, int]
) -> None:
    counts = audit.get("audit_counts")
    expected_keys = {
        "r4_cap25_rows",
        "r5_cap25_rows",
        "administrative_bound_rows",
        "r4_administratively_eligible",
        "r4_administratively_censored",
        "r5_administratively_eligible",
        "r5_administratively_censored",
        "cy006_requested_rows",
        "cy006_missing_rows_preserved",
        "cy006_hard_invalid_rows_preserved",
        "cy008_requested_window0_rows",
        "cy008_missing_rows_preserved",
        "cy008_hard_invalid_rows_preserved",
        "cy008_or_cy006_snapshot_missing_rows_preserved",
        "cy008_cy006_nonempty_snapshot_conflicts",
        "qd010_bounded_event_rows",
        "qd010_cash_only_rows",
        "qd010_risk_share_rows",
        "qd010_risk_rights_rows",
        "qd010_unresolved_or_unsupported_rows",
        "post_2021_rows",
        "invalid_rows_filtered",
    }
    if not isinstance(counts, dict) or set(counts) != expected_keys:
        raise CY046BuildError("CY-046 activation audit count interface drift")
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in counts.values()
    ):
        raise CY046BuildError("CY-046 activation audit contains invalid counts")
    content = manifest.get("content_contract", {})
    eligible_total = int(content.get("v29r4_admin_eligible", -1)) + int(
        content.get("v29r5_admin_eligible", -1)
    )
    if (
        content.get("v29r4_cap25_exact_rows")
        != observed_rows["v29r4_cap25_identity"]
        or content.get("v29r5_cap25_exact_rows")
        != observed_rows["v29r5_cap25_identity"]
        or observed_rows["candidate_admin_bounds"]
        != observed_rows["v29r4_cap25_identity"]
        + observed_rows["v29r5_cap25_identity"]
        or observed_rows["candidate_daily_path"] != eligible_total * 25
        or observed_rows["candidate_execution_window0"] != eligible_total * 24
        or observed_rows["market_calendar"] <= 0
    ):
        raise CY046BuildError("CY-046 manifest/footer bounded cardinality drift")
    required = {
        "r4_cap25_rows": observed_rows["v29r4_cap25_identity"],
        "r5_cap25_rows": observed_rows["v29r5_cap25_identity"],
        "administrative_bound_rows": observed_rows["candidate_admin_bounds"],
        "r4_administratively_eligible": content.get("v29r4_admin_eligible"),
        "r4_administratively_censored": 0,
        "r5_administratively_eligible": content.get("v29r5_admin_eligible"),
        "r5_administratively_censored": content.get("v29r5_admin_censored"),
        "cy006_requested_rows": observed_rows["candidate_daily_path"],
        "cy008_requested_window0_rows": observed_rows["candidate_execution_window0"],
        "qd010_bounded_event_rows": observed_rows["candidate_action_events"],
        "cy008_cy006_nonempty_snapshot_conflicts": 0,
        "qd010_unresolved_or_unsupported_rows": 0,
        "post_2021_rows": 0,
        "invalid_rows_filtered": 0,
    }
    if any(counts[key] != value for key, value in required.items()):
        raise CY046BuildError("CY-046 activation audit counts disagree with manifest/footer")
    if (
        counts["qd010_cash_only_rows"]
        + counts["qd010_risk_share_rows"]
        + counts["qd010_risk_rights_rows"]
        != counts["qd010_bounded_event_rows"]
        or counts["cy006_missing_rows_preserved"] > counts["cy006_requested_rows"]
        or counts["cy006_hard_invalid_rows_preserved"] > counts["cy006_requested_rows"]
        or counts["cy008_missing_rows_preserved"] > counts["cy008_requested_window0_rows"]
        or counts["cy008_hard_invalid_rows_preserved"]
        > counts["cy008_requested_window0_rows"]
        or counts["cy008_or_cy006_snapshot_missing_rows_preserved"]
        > counts["cy008_requested_window0_rows"]
    ):
        raise CY046BuildError("CY-046 activation audit count conservation drift")


def verify_built_metadata(root: Path = TARGET_ROOT) -> dict[str, Any]:
    """Verify exact output files/hashes/schemas from JSON and footers only."""
    root = _lexical_absolute(root)
    assert_canonical_asset_immutable(root)
    actual = {path.name for path in root.iterdir()}
    if actual != EXACT_CANONICAL_FILENAMES:
        raise CY046BuildError(f"CY-046 has missing or unexpected files: {sorted(actual)}")
    manifest_path = root / "asset_manifest.json"
    audit_path = root / "activation_audit.json"
    manifest = _json(manifest_path)
    audit = _json(audit_path)
    if set(manifest) != MANIFEST_TOP_LEVEL_KEYS:
        raise CY046BuildError("CY-046 manifest top-level interface drift")
    if (
        manifest.get("asset_id") != ASSET_ID
        or manifest.get("status") != "PASS"
        or manifest.get("authorization_id") != AUTHORIZATION_ID
        or manifest.get("coverage") != {"start": "2018-01-01", "end": "2021-12-31"}
        or manifest.get("pit_contract") != PIT_CONTRACT
        or manifest.get("content_contract", {}).get("v29r4_cap25_exact_rows")
        != EXPECTED_R4_CAP_ROWS
        or manifest.get("content_contract", {}).get("v29r5_cap25_exact_rows")
        != EXPECTED_R5_CAP_ROWS
        or manifest.get("content_contract", {}).get("v29r4_admin_eligible") != 251
        or manifest.get("content_contract", {}).get("v29r5_admin_eligible") != 254
        or manifest.get("content_contract", {}).get("v29r5_admin_censored") != 1
        or manifest.get("content_contract", {}).get("post_2021_rows") != 0
        or manifest.get("content_contract", {}).get("outcome_or_return_source_columns") != []
        or manifest.get("content_contract", {}).get("returns_computed") is not False
        or manifest.get("content_contract", {}).get("macos_readonly_uf_immutable_required")
        is not True
    ):
        raise CY046BuildError("CY-046 manifest semantic drift")
    observed_manifest_sha256 = sha256_file(manifest_path)
    validate_manifest_audit_cross_binding(manifest, audit, observed_manifest_sha256)
    required_gates = (
        "source_metadata_gate",
        "identity_count_gate",
        "scope_gate",
        "snapshot_nonempty_conflict_gate",
    )
    if (
        audit.get("asset_id") != ASSET_ID
        or audit.get("status") != "PASS"
        or audit.get("gate_pass") is not True
        or audit.get("post_2021_rows") != 0
        or audit.get("outcome_or_return_source_columns") != []
        or any(audit.get(gate) != "PASS" for gate in required_gates)
        or audit.get("post_content_source_revalidation")
        != manifest.get("content_contract", {}).get("post_content_source_revalidation")
        or audit.get("output_schema_sha256") != OUTPUT_SCHEMA_SHA256
        or manifest.get("content_contract", {}).get("output_schema_sha256")
        != OUTPUT_SCHEMA_SHA256
    ):
        raise CY046BuildError("CY-046 activation audit gate drift")
    protocol = manifest.get("protocol", {})
    if (
        protocol.get("sha256") != EXPECTED_PREREGISTRATION_SHA256
        or protocol.get("builder_sha256") != sha256_file(Path(__file__))
        or not _nonempty(protocol.get("runner_path"))
        or not _nonempty(protocol.get("runner_sha256"))
    ):
        raise CY046BuildError("CY-046 protocol/runner/builder binding drift")
    runner_path = _require_safe_regular_file(
        Path(str(protocol["runner_path"])), "bound Stage-B runner"
    )
    if sha256_file(runner_path) != protocol["runner_sha256"]:
        raise CY046BuildError("CY-046 bound Stage-B runner drift")
    output_bindings = manifest.get("files", [])
    if len(output_bindings) != len(OUTPUT_FILES):
        raise CY046BuildError("CY-046 manifest output cardinality drift")
    by_role = {
        item.get("role"): item for item in output_bindings if isinstance(item, dict)
    }
    if set(by_role) != set(OUTPUT_FILES):
        raise CY046BuildError("CY-046 manifest output roles drift")
    verified = []
    observed_rows: dict[str, int] = {}
    for role, filename in OUTPUT_FILES.items():
        binding = by_role[role]
        if binding.get("path") != filename:
            raise CY046BuildError(f"CY-046 output path drift: {role}")
        path = root / filename
        footer = parquet_footer_facts(path)
        observed_columns = tuple(item["name"] for item in footer["schema"])
        if (
            sha256_file(path) != binding.get("sha256")
            or path.stat().st_size != binding.get("size")
            or footer["rows"] != binding.get("rows")
            or footer["schema_sha256"] != binding.get("schema_sha256")
            or footer["schema_sha256"] != OUTPUT_SCHEMA_SHA256[role]
            or observed_columns != EXPECTED_OUTPUT_COLUMNS[role]
        ):
            raise CY046BuildError(f"CY-046 output metadata drift: {role}")
        verified.append({"role": role, **footer})
        observed_rows[role] = int(footer["rows"])
    validate_audit_counts_against_outputs(manifest, audit, observed_rows)
    return {
        "asset_id": ASSET_ID,
        "status": "PASS_METADATA_ONLY_VERIFY",
        "root": str(root.resolve()),
        "manifest_sha256": sha256_file(manifest_path),
        "activation_audit_sha256": sha256_file(audit_path),
        "verified_outputs": verified,
        "parquet_rows_opened": False,
        "outcome_or_return_rows_opened": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("metadata-dry-run", "build", "verify-metadata"),
        default="metadata-dry-run",
    )
    parser.add_argument(
        "--runner-path",
        type=Path,
        help="Required only for build; its exact path/hash is sealed into asset_manifest.json.",
    )
    args = parser.parse_args()
    if args.mode == "metadata-dry-run":
        result = metadata_dry_run()
    elif args.mode == "build":
        if args.runner_path is None:
            parser.error("--runner-path is required for --mode build")
        result = build_asset(args.runner_path)
    else:
        result = verify_built_metadata()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
