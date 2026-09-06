#!/usr/bin/env python3
"""Build the separately authorized anonymous V36 Phase-2 chart corpus.

``--verify-static-contract`` and ``--verify-public-authorization`` are public
metadata-only modes.  Neither may stat, hash, open, or parse a V36 Stage-B
artifact or an external Phase-1 artifact.  ``--run`` first passes the exact
CY-058 registry/spec/manifest gate, then reads only the three authorized CY-057
Stage-B tables (prepared candidates, future paths, and outcomes) plus the
existing anonymous Phase-1 chart corpus.  The Stage-B aggregate result is a
declared lexical binding and is never touched.

The produced charts are anonymous descriptive attribution.  No identity
crosswalk, numeric return, manual Phase-1 label, rule, or portfolio is emitted.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

EXPERIMENT = "ASHARE-BROAD-MARKET-PRICE-DELAY-COMPENSATION-MOTHER-V36"
STAGE = "PHASE2_2019_2020_ANONYMOUS_OUTCOME_ATTRIBUTION"
REPO = Path(__file__).resolve().parents[3]
EXP = REPO / "research/market_behavior_os_v2/experiments"
REGISTRY = REPO / "configs/data_asset_registry.json"

PHASE2_SPEC = EXP / (
    "ASHARE-BROAD-MARKET-PRICE-DELAY-COMPENSATION-MOTHER-V36_phase2_visual_attribution_freeze.json"
)
PHASE2_MANIFEST = EXP / "ASHARE-V36-CY058_OUTCOME_ATTRIBUTION_ASSET_MANIFEST.json"
REGISTRY_SUGGESTION = EXP / "ASHARE-V36-CY058_REGISTRY_SUGGESTION.json"
PARENT_SPEC = EXP / f"{EXPERIMENT}_freeze.json"
STAGE_B_SPEC = EXP / f"{EXPERIMENT}_stage_b_freeze.json"
STAGE_B_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_broad_market_price_delay_compensation_mother_v36_stage_b.py"
)
STAGE_B_MANIFEST = EXP / "ASHARE-V36-CY057_DATA_ASSET_MANIFEST.json"
PHASE1_SPEC = EXP / f"{EXPERIMENT}_visual_review_spec.json"
PHASE1_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_broad_market_price_delay_compensation_mother_v36_phase1_charts.py"
)
PHASE1_ASSET_MANIFEST = EXP / "ASHARE-V36-CY055_CHART_REVIEW_ASSET_MANIFEST.json"
PHASE1_LEDGER_FREEZE = EXP / "ASHARE-V36_phase1_ledger_freeze_spec.json"
PHASE1_FINALIZER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "finalize_ashare_broad_market_price_delay_compensation_mother_v36_phase1.py"
)
PHASE1_AXIS_DECISION = EXP / "ASHARE-V36_phase1_axis_reliability_decision.json"

ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_broad_market_price_delay_compensation_mother_v36"
)
STAGE_B = ROOT / "stage_b"
PREPARED = STAGE_B / "prepared_candidates.parquet"
STAGE_B_RESULT = STAGE_B / "result.json"
FUTURE_PATHS = STAGE_B / "future_paths.parquet"
OUTCOMES = STAGE_B / "outcomes.parquet"
PHASE1_CHART_ROOT = ROOT / "stage_c_phase1_anonymous_charts"
PHASE1_CHART_MANIFEST = PHASE1_CHART_ROOT / "manifest.json"
PHASE1_BLIND_INDEX = PHASE1_CHART_ROOT / "blind_index.csv"
OUTPUT = ROOT / "stage_e_phase2_outcome_attribution"

ASSET_ID = "CY-058"
DEPENDENCY_ASSET_IDS = ["CY-055", "CY-057"]
AUTHORIZATION_ID = (
    "CYQ-AUTH-ASHARE-BROAD-MARKET-PRICE-DELAY-V36-PHASE2-CY058-OUTCOME-ATTRIBUTION-2019-2020-V1"
)
AUTHORIZED_ARM = "V36_PHASE2_2019_2020_OUTCOME_ATTRIBUTION_ONLY"
AUTHORIZATION_PURPOSE = "ASHARE_FROZEN_DEVELOPMENT_OUTCOME_CHART_ATTRIBUTION"
MANIFEST_STATUS = "FROZEN_DEVELOPMENT_OUTCOME_ATTRIBUTION_BOUNDED_INPUT"
PIPELINE_VERSION = "v36-phase2-2019-2020-anonymous-outcome-attribution-v1"

EXPECTED_EVENTS = 531
EXPECTED_ANNUAL = {2019: 249, 2020: 282}
SIGNAL_START = pd.Timestamp("2019-03-29")
SIGNAL_END = pd.Timestamp("2020-12-31")
MAX_PATH_DATE = pd.Timestamp("2021-09-30")
WINDOW = 126
TARGET_RETURN = 0.10
HORIZON_SESSIONS = 20
ROUND_TRIP_COST = 0.004
OPAQUE_ORDER_SALT = "V36_PHASE1_CAUSAL_MASKED_ORDER_V1"

OUTCOME_BUCKETS = (
    "PROFIT_GE_4PCT",
    "PROFIT_0_TO_4PCT",
    "LOSS_0_TO_10PCT",
    "SEVERE_LOSS",
    "NO_COMPLETED_TRADE",
)
BUCKET_DEFINITIONS = {
    "PROFIT_GE_4PCT": "status=COMPLETED and net_return>=0.04",
    "PROFIT_0_TO_4PCT": "status=COMPLETED and 0<=net_return<0.04",
    "LOSS_0_TO_10PCT": "status=COMPLETED and -0.10<net_return<0",
    "SEVERE_LOSS": "status=COMPLETED and net_return<=-0.10",
    "NO_COMPLETED_TRADE": "status!=COMPLETED or net_return is nonfinite",
}
POST_PATH_LABELS = (
    "IMMEDIATE_ACCEPTANCE",
    "DELAYED_ACCEPTANCE",
    "EARLY_REJECTION",
    "LATE_REJECTION",
    "CHOP_OR_AMBIGUOUS",
    "NO_COMPLETED_TRADE",
)
REVIEW_FIELDS = (
    "chart_number",
    "blind_chart_id",
    "outcome_bucket",
    "post_path_label",
    "evidence",
    "reviewer",
    "phase1_labels_modified",
    "signal_candle_used_for_rule",
    "post_signal_used_as_predictor",
)
ALLOWED_STATUSES = {
    "NO_LEGAL_ENTRY",
    "INVALID_COORDINATE_LINEAGE_BEFORE_ENTRY",
    "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
    "INVALID_CORPORATE_ACTION_STATE_BEFORE_ENTRY",
    "INVALID_CORPORATE_ACTION_STATE_AFTER_ENTRY",
    "INCOMPLETE_PATH",
    "COMPLETED",
}
ALLOWED_EXIT_REASONS = {"TARGET_10", "H20_TIME_STOP"}

# Repository hashes are safe in both verification-only modes.  PHASE2_SPEC,
# PHASE2_MANIFEST, REGISTRY_SUGGESTION, REGISTRY, and this runner are verified
# dynamically because they are finalized together after this runner exists.
REPO_HASHES: dict[Path, str] = {
    PARENT_SPEC: "2dc6e2b1ac6e29105172cddc8a6d5dbafa06b30645a8f48b08abdf8f348286fc",
    STAGE_B_SPEC: "c3867b272c05c5e558b56abe6097aa5a7ee6b3bca5c649d577643e0446f47655",
    STAGE_B_RUNNER: "85097db23525a357664073ded605fb3ab92ca3454f5fc40b2f173e8c2e35b96e",
    STAGE_B_MANIFEST: "76b065449793e8c2ebc66b272fffa4dd7af1e812f9a39984c7ea11da0da4812a",
    PHASE1_SPEC: "5ece0d1f5cd1c269a9eda771fee756ae7e0ff96560384eb810dc6a4957166d56",
    PHASE1_RUNNER: "1c9fffcaee7701af87858cb29b3e7ccf6aae89c9ec63e72439b0811ad7bf5ad8",
    PHASE1_ASSET_MANIFEST: ("71b07ee62502ebd08fcc9ff8e1f89943b243abe8bdceebf6d95883048e34eb9c"),
    PHASE1_LEDGER_FREEZE: ("4ee8ef1b2912bebd857c3fbb19b9f9d94227f5f16c15583a81bf1c7f8a53f390"),
    PHASE1_FINALIZER: ("c1fe1d2fe3f48f4d55878348d0125c7a34d3461a6b77f8530ccc17a8781d68ea"),
    PHASE1_AXIS_DECISION: ("6f5c76d0abcb0ad2e7836f32ae48587036ffa5c5a585919996b6d0370f3ea1e6"),
}

# These external Phase-1 files are outcome blind.  They remain literal-only in
# public modes and are touched only by --run after the full CY-058 gate.
PHASE1_EXTERNAL_HASHES: dict[Path, str] = {
    PHASE1_CHART_MANIFEST: ("322ff9ce07e183de52d12dccab59d50e813c7377f80bb4462f0011898aeee162"),
    PHASE1_BLIND_INDEX: ("088e639a187fc92a8c246876254cc6ab3657c29dfdb2ac499f3af040833cbc0b"),
}

REPO_BOUND_ROLES = (
    ("parent_freeze", PARENT_SPEC),
    ("stage_b_freeze", STAGE_B_SPEC),
    ("stage_b_runner", STAGE_B_RUNNER),
    ("stage_b_asset_manifest", STAGE_B_MANIFEST),
    ("phase1_visual_review_spec", PHASE1_SPEC),
    ("phase1_chart_runner", PHASE1_RUNNER),
    ("phase1_asset_manifest", PHASE1_ASSET_MANIFEST),
    ("phase1_ledger_freeze_spec", PHASE1_LEDGER_FREEZE),
    ("phase1_finalizer", PHASE1_FINALIZER),
    ("phase1_axis_reliability_decision", PHASE1_AXIS_DECISION),
)
PHASE1_EXTERNAL_ROLES = (
    ("phase1_chart_corpus_manifest", PHASE1_CHART_MANIFEST),
    ("phase1_blind_index", PHASE1_BLIND_INDEX),
)
STAGE_B_ROLES = (
    ("stage_b_prepared_candidates", PREPARED),
    ("stage_b_result_declared_only_unread", STAGE_B_RESULT),
    ("stage_b_future_paths", FUTURE_PATHS),
    ("stage_b_outcomes", OUTCOMES),
)

REQUIRED_TRUE_PERMISSIONS = (
    "phase2_authorized",
    "charts_authorized",
    "completed_stage_b_artifact_read_authorized",
    "prepared_identity_read_authorized",
    "outcome_artifact_hash_authorized",
    "outcome_artifact_parse_authorized",
    "post_signal_row_read_authorized",
    "2021_path_completion_authorized",
    "outcome_grouping_authorized",
    "anonymous_full_chart_authorized",
    "in_memory_identity_reconstruction_authorized",
    "phase1_anonymous_chart_read_authorized",
)
REQUIRED_FALSE_PERMISSIONS = (
    "stage_b_result_access_authorized",
    "manual_labels_read_authorized",
    "phase1_label_rewrite_authorized",
    "identity_crosswalk_persistence_authorized",
    "identity_reveal_authorized",
    "numeric_return_persistence_authorized",
    "signal_candle_rule_authorized",
    "post_signal_predictor_authorized",
    "rule_aggregation_authorized",
    "portfolio_replay_authorized",
    "candidate_reselection_authorized",
    "parameter_search_authorized",
    "2021_signal_read_authorized",
    "post_2021_q3_read_authorized",
    "2022_plus_read_authorized",
)

BLIND_INDEX_COLUMNS = (
    "chart_number",
    "blind_chart_id",
    "blind_chart_path",
    "blind_chart_sha256",
    "sheet_number",
    "slot",
)
PREPARED_COLUMNS = (
    "event_id",
    "symbol",
    "causal_industry",
    "signal_date",
    "source_signal_cal_idx",
    "signal_cal_idx",
    "invalid_step_cum",
    "sleeve",
    "available_at",
    "decision_at",
    "raw_signal_date",
    "coordinate_signal_date",
    "raw_signal_industry",
    "signal_row_available_at",
    "signal_row_decision_at",
    "snapshot_id",
    "daily_snapshot_id",
    "trading_state_snapshot_id",
    "industry_snapshot_id",
    "float_snapshot_id",
    "corporate_action_snapshot_id",
    "market_snapshot_id",
)
OUTCOME_COLUMNS = (
    "event_id",
    "symbol",
    "causal_industry",
    "signal_date",
    "signal_cal_idx",
    "signal_invalid_step_cum",
    "target_return",
    "horizon_sessions",
    "round_trip_cost",
    "status",
    "entry_date",
    "entry_cal_idx",
    "entry_price",
    "target_price",
    "exit_date",
    "exit_cal_idx",
    "exit_price",
    "exit_reason",
    "holding_sessions",
    "net_return",
)
PATH_COLUMNS = (
    "event_id",
    "symbol",
    "event_signal_date",
    "event_signal_cal_idx",
    "trade_date",
    "cal_idx",
    "open",
    "high",
    "low",
    "close",
    "coord_open",
    "coord_high",
    "coord_low",
    "coord_close",
    "invalid_step_cum",
    "coordinate_factor",
    "trade_status",
    "current_day_data_tradable",
    "current_valid",
    "market_rule_valid",
    "corporate_action_count",
    "corporate_action_valid",
    "corporate_action_blocking",
    "hard_valid",
    "available_at",
    "decision_at",
)

CHART_SIZE = (720, 440)
FULL_CHART_SIZE = (1440, 440)
CONTACT_SIZE = (1800, 1140)
GRID_COLUMNS = 5
GRID_ROWS = 5


class ResearchError(RuntimeError):
    """Fail-closed contract, chronology, lineage, or anonymity violation."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ResearchError(f"{label} must be a JSON object")
    return value


def only(items: list[dict[str, Any]], label: str) -> dict[str, Any]:
    if len(items) != 1:
        raise ResearchError(f"expected exactly one {label}; found {len(items)}")
    return items[0]


def require_columns(frame: pd.DataFrame, columns: tuple[str, ...], label: str) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ResearchError(f"{label} missing columns: {missing}")


def bound_artifact_map(container: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items = container.get("bound_artifacts", [])
    if not isinstance(items, list):
        raise ResearchError("bound_artifacts must be a list")
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("role"), str):
            raise ResearchError("malformed bound_artifacts item")
        role = str(item["role"])
        if role in result:
            raise ResearchError(f"duplicate bound-artifact role: {role}")
        result[role] = item
    return result


def assert_literal_binding(
    artifacts: dict[str, dict[str, Any]], role: str, path: Path, expected_hash: str
) -> None:
    """Compare path/hash strings without touching the path."""
    item = artifacts.get(role)
    if item is None or item.get("path") != str(path) or item.get("sha256") != expected_hash:
        raise ResearchError(f"CY-058 does not bind exact artifact {role}")


def valid_sha(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def verify_static_contract() -> dict[str, str]:
    """Validate repository-only contracts; never touch an external artifact."""
    required = (*REPO_HASHES, PHASE2_SPEC, Path(__file__))
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ResearchError(f"missing repository contract input: {missing}")
    actual: dict[str, str] = {}
    for path, expected in REPO_HASHES.items():
        observed = sha256(path)
        if observed != expected:
            raise ResearchError(f"repository input drift: {path}: {observed}")
        actual[str(path.relative_to(REPO))] = observed

    runner_hash = sha256(Path(__file__))
    spec_hash = sha256(PHASE2_SPEC)
    spec = load_json(PHASE2_SPEC, "V36 Phase-2 freeze")
    renderer = spec.get("renderer", {})
    scope = spec.get("scope", {})
    buckets = spec.get("outcome_groups", {})
    review = spec.get("phase2_review_schema", {})
    required_authorization = spec.get("required_authorization", {})
    permissions = required_authorization.get("permissions", {})
    outputs = spec.get("outputs", {})
    if (
        spec.get("experiment") != EXPERIMENT
        or spec.get("stage") != STAGE
        or spec.get("status") != "STATIC_FROZEN_AWAITING_CY058_AUTHORIZATION"
        or spec.get("pipeline_version") != PIPELINE_VERSION
        or renderer.get("path") != str(Path(__file__).relative_to(REPO))
        or renderer.get("sha256") != runner_hash
        or scope.get("events") != EXPECTED_EVENTS
        or scope.get("annual_signal_counts")
        != {str(year): count for year, count in EXPECTED_ANNUAL.items()}
        or scope.get("signal_start") != str(SIGNAL_START.date())
        or scope.get("signal_end") != str(SIGNAL_END.date())
        or scope.get("maximum_path_row_date") != str(MAX_PATH_DATE.date())
        or scope.get("post_window") != [1, WINDOW]
        or scope.get("2021_role") != "LATE_2020_PATH_COMPLETION_ONLY_NO_2021_SIGNAL"
        or buckets.get("ordered_buckets") != list(OUTCOME_BUCKETS)
        or buckets.get("definitions") != BUCKET_DEFINITIONS
        or review.get("exact_fields") != list(REVIEW_FIELDS)
        or review.get("post_path_labels") != list(POST_PATH_LABELS)
        or review.get("phase1_labels_modified") is not False
        or review.get("signal_candle_used_for_rule") is not False
        or review.get("post_signal_used_as_predictor") is not False
        or required_authorization.get("asset_id") != ASSET_ID
        or required_authorization.get("authorization_id") != AUTHORIZATION_ID
        or required_authorization.get("authorized_arm") != AUTHORIZED_ARM
        or any(permissions.get(key) is not True for key in REQUIRED_TRUE_PERMISSIONS)
        or any(permissions.get(key) is not False for key in REQUIRED_FALSE_PERMISSIONS)
        or outputs.get("canonical_directory") != str(OUTPUT)
        or outputs.get("individual_charts") != EXPECTED_EVENTS
        or outputs.get("chart_size_pixels") != list(FULL_CHART_SIZE)
        or outputs.get("contact_sheet_grid") != [GRID_COLUMNS, GRID_ROWS]
        or outputs.get("files")
        != [
            "phase2_chart_index.csv",
            "outcome_sheet_placements.csv",
            "outcome_sheet_index.csv",
            "phase2_review_template.json",
            "manifest.json",
        ]
        or outputs.get("atomic_no_overwrite") is not True
        or spec.get("identity_crosswalk_persisted") is not False
        or spec.get("numeric_returns_persisted") is not False
        or spec.get("phase1_labels_read") is not False
        or spec.get("rule_aggregation_authorized") is not False
        or spec.get("portfolio_replay_authorized") is not False
    ):
        raise ResearchError("V36 Phase-2 static semantics drift")

    declared = bound_artifact_map(spec)
    expected_roles = {
        *(role for role, _ in REPO_BOUND_ROLES),
        *(role for role, _ in PHASE1_EXTERNAL_ROLES),
        *(role for role, _ in STAGE_B_ROLES),
    }
    if set(declared) != expected_roles:
        raise ResearchError("V36 Phase-2 declared-artifact role set drift")
    for role, path in REPO_BOUND_ROLES:
        assert_literal_binding(declared, role, path.resolve(), REPO_HASHES[path])
    # Literal comparisons only: no resolve/stat/hash/open of external paths.
    for role, path in PHASE1_EXTERNAL_ROLES:
        assert_literal_binding(declared, role, path, PHASE1_EXTERNAL_HASHES[path])
    for role, path in STAGE_B_ROLES:
        item = declared.get(role, {})
        if item.get("path") != str(path) or not valid_sha(item.get("sha256")):
            raise ResearchError(f"invalid declared Stage-B binding: {role}")
    if declared["stage_b_result_declared_only_unread"].get("access") != (
        "DECLARED_ONLY_NEVER_STAT_HASH_OPEN_OR_PARSE_IN_PHASE2"
    ):
        raise ResearchError("Stage-B result is not strictly declared-only")

    actual["phase2_spec"] = spec_hash
    actual["phase2_runner"] = runner_hash
    return actual


def verify_public_authorization() -> tuple[dict[str, str], dict[str, Any], dict[str, str]]:
    """Validate spec/manifest/suggestion/registry with no external file access."""
    actual = verify_static_contract()
    public = (REGISTRY, PHASE2_MANIFEST, REGISTRY_SUGGESTION)
    missing = [str(path) for path in public if not path.is_file()]
    if missing:
        raise ResearchError(f"missing CY-058 public authorization input: {missing}")
    actual["registry"] = sha256(REGISTRY)
    actual["phase2_manifest"] = sha256(PHASE2_MANIFEST)
    actual["registry_suggestion"] = sha256(REGISTRY_SUGGESTION)

    registry = load_json(REGISTRY, "data registry")
    suggestion = load_json(REGISTRY_SUGGESTION, "CY-058 registry suggestion")
    suggested_asset = suggestion.get("asset")
    suggested_authorization = suggestion.get("bounded_authorization")
    if not isinstance(suggested_asset, dict) or not isinstance(suggested_authorization, dict):
        raise ResearchError("CY-058 suggestion does not contain exact registry objects")
    asset = only(
        [item for item in registry.get("assets", []) if item.get("asset_id") == ASSET_ID],
        f"asset {ASSET_ID}",
    )
    authorization = only(
        [
            item
            for item in registry.get("bounded_authorizations", [])
            if item.get("authorization_id") == AUTHORIZATION_ID
        ],
        f"authorization {AUTHORIZATION_ID}",
    )
    if asset != suggested_asset or authorization != suggested_authorization:
        raise ResearchError("installed CY-058 objects do not exactly match suggestion")

    lineage = asset.get("lineage", {})
    protocol = authorization.get("bound_protocol", {})
    bound_manifest = authorization.get("bound_manifest", {})
    scope = authorization.get("scope", {})
    if (
        asset.get("status") != "RESEARCH_CONDITIONAL"
        or asset.get("kind") != "bounded_daily_pit_b_development_outcome_chart_attribution_input"
        or asset.get("pit_grade") != "B"
        or asset.get("physical_state") != "MATERIALIZED"
        or asset.get("location") != str(STAGE_B)
        or lineage.get("manifest_path") != str(PHASE2_MANIFEST.resolve())
        or lineage.get("manifest_sha256") != actual["phase2_manifest"]
        or lineage.get("bounded_authorization_id") != AUTHORIZATION_ID
        or lineage.get("pipeline_version") != PIPELINE_VERSION
        or authorization.get("asset_id") != ASSET_ID
        or authorization.get("dependency_asset_id") != DEPENDENCY_ASSET_IDS[0]
        or authorization.get("dependency_asset_ids") != DEPENDENCY_ASSET_IDS
        or authorization.get("purpose") != AUTHORIZATION_PURPOSE
        or authorization.get("authorized_arms") != [AUTHORIZED_ARM]
        or bound_manifest.get("path") != str(PHASE2_MANIFEST.resolve())
        or bound_manifest.get("sha256") != actual["phase2_manifest"]
        or protocol.get("path") != str(PHASE2_SPEC.resolve())
        or protocol.get("sha256") != actual["phase2_spec"]
        or protocol.get("runner_path") != str(Path(__file__).resolve())
        or protocol.get("runner_sha256") != actual["phase2_runner"]
        or scope.get("signal_start") != str(SIGNAL_START.date())
        or scope.get("signal_end") != str(SIGNAL_END.date())
        or scope.get("maximum_path_row_date") != str(MAX_PATH_DATE.date())
        or scope.get("frozen_events") != EXPECTED_EVENTS
    ):
        raise ResearchError("installed CY-058 identity/scope drift")
    for key in REQUIRED_TRUE_PERMISSIONS:
        if authorization.get(key) is not True:
            raise ResearchError(f"CY-058 permission not true: {key}")
    for key in REQUIRED_FALSE_PERMISSIONS:
        if authorization.get(key) is not False:
            raise ResearchError(f"CY-058 forbidden permission not false: {key}")

    manifest = load_json(PHASE2_MANIFEST, "CY-058 Phase-2 manifest")
    boundary = manifest.get("authorization_boundary", {})
    manifest_protocol = manifest.get("protocol", {})
    manifest_scope = manifest.get("frozen_scope", {})
    publication = manifest.get("publication_contract", {})
    if (
        manifest.get("asset_id") != ASSET_ID
        or manifest.get("status") != MANIFEST_STATUS
        or manifest.get("pipeline_version") != PIPELINE_VERSION
        or boundary.get("authorization_id") != AUTHORIZATION_ID
        or boundary.get("purpose") != AUTHORIZATION_PURPOSE
        or boundary.get("authorized_arm") != AUTHORIZED_ARM
        or boundary.get("dependency_asset_ids") != DEPENDENCY_ASSET_IDS
        or any(boundary.get(key) is not True for key in REQUIRED_TRUE_PERMISSIONS)
        or any(boundary.get(key) is not False for key in REQUIRED_FALSE_PERMISSIONS)
        or manifest_protocol.get("phase2_spec_path") != str(PHASE2_SPEC.resolve())
        or manifest_protocol.get("phase2_spec_sha256") != actual["phase2_spec"]
        or manifest_protocol.get("phase2_runner_path") != str(Path(__file__).resolve())
        or manifest_protocol.get("phase2_runner_sha256") != actual["phase2_runner"]
        or manifest_scope.get("events") != EXPECTED_EVENTS
        or manifest_scope.get("annual_signal_counts")
        != {str(year): count for year, count in EXPECTED_ANNUAL.items()}
        or manifest_scope.get("signal_start") != str(SIGNAL_START.date())
        or manifest_scope.get("signal_end") != str(SIGNAL_END.date())
        or manifest_scope.get("maximum_path_row_date") != str(MAX_PATH_DATE.date())
        or manifest_scope.get("post_window") != [1, WINDOW]
        or publication.get("canonical_directory") != str(OUTPUT)
        or publication.get("outputs")
        != [
            "phase2_chart_index.csv",
            "outcome_sheet_placements.csv",
            "outcome_sheet_index.csv",
            "phase2_review_template.json",
            "manifest.json",
        ]
        or publication.get("atomic_no_overwrite") is not True
    ):
        raise ResearchError("CY-058 manifest semantics drift")

    spec_roles = {
        *(role for role, _ in REPO_BOUND_ROLES),
        *(role for role, _ in PHASE1_EXTERNAL_ROLES),
        *(role for role, _ in STAGE_B_ROLES),
    }
    authorization_roles = {
        "phase2_freeze",
        "phase2_runner",
        *spec_roles,
    }
    spec_artifacts = bound_artifact_map(load_json(PHASE2_SPEC, "V36 Phase-2 freeze"))
    manifest_artifacts = bound_artifact_map(manifest)
    authorization_artifacts = bound_artifact_map(authorization)
    if (
        set(spec_artifacts) != spec_roles
        or set(manifest_artifacts) != authorization_roles
        or set(authorization_artifacts) != authorization_roles
        or manifest_artifacts != authorization_artifacts
    ):
        raise ResearchError("CY-058 three-party artifact binding drift")
    assert_literal_binding(
        manifest_artifacts, "phase2_freeze", PHASE2_SPEC.resolve(), actual["phase2_spec"]
    )
    assert_literal_binding(
        manifest_artifacts,
        "phase2_runner",
        Path(__file__).resolve(),
        actual["phase2_runner"],
    )
    for role, item in spec_artifacts.items():
        if manifest_artifacts.get(role) != item:
            raise ResearchError(f"CY-058 spec/manifest artifact drift: {role}")

    stage_b_hashes: dict[str, str] = {}
    for role, path in STAGE_B_ROLES:
        item = spec_artifacts[role]
        if item.get("path") != str(path) or not valid_sha(item.get("sha256")):
            raise ResearchError(f"CY-058 invalid Stage-B binding: {role}")
        stage_b_hashes[role] = str(item["sha256"])
    if spec_artifacts["stage_b_result_declared_only_unread"].get("access") != (
        "DECLARED_ONLY_NEVER_STAT_HASH_OPEN_OR_PARSE_IN_PHASE2"
    ):
        raise ResearchError("CY-058 result binding permits access")
    return actual, authorization, stage_b_hashes


def verify_hash_after_authorization(path: Path, expected: str, label: str) -> str:
    if not path.is_file():
        raise ResearchError(f"missing authorized {label}: {path}")
    observed = sha256(path)
    if observed != expected:
        raise ResearchError(f"authorized {label} hash drift: {observed} != {expected}")
    return observed


def verify_phase1_external() -> pd.DataFrame:
    """First Phase-1 access; reads only public anonymous corpus metadata."""
    for path, expected in PHASE1_EXTERNAL_HASHES.items():
        verify_hash_after_authorization(path, expected, f"Phase-1 input {path.name}")
    manifest = load_json(PHASE1_CHART_MANIFEST, "Phase-1 chart manifest")
    if (
        manifest.get("experiment") != EXPERIMENT
        or manifest.get("stage") != "PHASE1_ANONYMOUS_CAUSAL_VISUAL_REVIEW_CORPUS"
        or manifest.get("events") != EXPECTED_EVENTS
        or manifest.get("individual_anonymous_charts") != EXPECTED_EVENTS
        or manifest.get("chart_size_pixels") != list(CHART_SIZE)
        or manifest.get("phase1_window_relative_global_sessions") != [-WINDOW, 0]
        or manifest.get("opaque_order_salt") != OPAQUE_ORDER_SALT
        or manifest.get("blind_index_sha256") != PHASE1_EXTERNAL_HASHES[PHASE1_BLIND_INDEX]
        or manifest.get("anonymous_identity_coverage_exactly_once") is not True
        or manifest.get("identity_crosswalk_persisted") is not False
        or manifest.get("post_signal_row_read") is not False
        or manifest.get("post_2020_row_read") is not False
        or manifest.get("outcome_artifact_statted_hashed_opened_or_parsed") is not False
    ):
        raise ResearchError("Phase-1 anonymous chart manifest drift")
    blind = pd.read_csv(PHASE1_BLIND_INDEX)
    if tuple(blind.columns) != BLIND_INDEX_COLUMNS:
        raise ResearchError("Phase-1 blind-index schema drift")
    blind["chart_number"] = pd.to_numeric(blind.chart_number, errors="raise").astype(int)
    safe_paths = blind.blind_chart_path.astype(str).map(Path)
    blind_ids = blind.blind_chart_id.astype(str)
    if (
        len(blind) != EXPECTED_EVENTS
        or blind.chart_number.tolist() != list(range(1, EXPECTED_EVENTS + 1))
        or blind.chart_number.duplicated().any()
        or blind_ids.duplicated().any()
        or not blind_ids.str.fullmatch(r"B-[0-9a-f]{20}").all()
        or blind.blind_chart_sha256.map(valid_sha).eq(False).any()
        or any(path.is_absolute() or ".." in path.parts for path in safe_paths)
        or safe_paths.astype(str).duplicated().any()
    ):
        raise ResearchError("Phase-1 blind-index anonymous coverage/path drift")
    return blind


def load_prepared_and_rebuild_blind_order(blind: pd.DataFrame) -> pd.DataFrame:
    prepared = pd.read_parquet(PREPARED, columns=list(PREPARED_COLUMNS))
    require_columns(prepared, PREPARED_COLUMNS, "prepared candidates")
    prepared["event_id"] = prepared.event_id.astype(str)
    prepared["signal_date"] = pd.to_datetime(prepared.signal_date)
    date_columns = (
        "available_at",
        "decision_at",
        "raw_signal_date",
        "coordinate_signal_date",
        "signal_row_available_at",
        "signal_row_decision_at",
    )
    for column in date_columns:
        prepared[column] = pd.to_datetime(prepared[column])
    annual = prepared.signal_date.dt.year.value_counts().sort_index().to_dict()
    snapshots = prepared[
        [column for column in PREPARED_COLUMNS if column.endswith("snapshot_id")]
    ].astype("string")
    numeric = prepared[["source_signal_cal_idx", "signal_cal_idx", "invalid_step_cum"]].apply(
        pd.to_numeric, errors="coerce"
    )
    offsets = numeric.signal_cal_idx - numeric.source_signal_cal_idx
    if (
        len(prepared) != EXPECTED_EVENTS
        or prepared.event_id.duplicated().any()
        or annual != EXPECTED_ANNUAL
        or prepared.signal_date.min() != SIGNAL_START
        or prepared.signal_date.max() != SIGNAL_END
        or prepared.signal_date.gt(SIGNAL_END).any()
        or prepared[["event_id", "symbol", "causal_industry"]].isna().any().any()
        or prepared.event_id.str.strip().eq("").any()
        or prepared.symbol.astype(str).str.strip().eq("").any()
        or prepared.causal_industry.astype(str).str.strip().eq("").any()
        or prepared.sleeve.astype(str).ne("PRICE_DELAY").any()
        or prepared[list(date_columns)].isna().any().any()
        or prepared.available_at.gt(prepared.decision_at).any()
        or prepared.signal_row_available_at.gt(prepared.signal_row_decision_at).any()
        or prepared.decision_at.ne(prepared.signal_row_decision_at).any()
        or prepared.raw_signal_date.ne(prepared.signal_date).any()
        or prepared.coordinate_signal_date.ne(prepared.signal_date).any()
        or prepared.raw_signal_industry.ne(prepared.causal_industry).any()
        or snapshots.isna().any().any()
        or snapshots.apply(lambda values: values.str.strip().eq("")).any().any()
        or not np.isfinite(numeric.to_numpy(dtype=float)).all()
        or offsets.nunique(dropna=False) != 1
    ):
        raise ResearchError("prepared-candidate PIT/identity/calendar drift")

    prepared["_blind_sort_digest"] = prepared.event_id.map(
        lambda event_id: hashlib.sha256(f"{OPAQUE_ORDER_SALT}|{event_id}".encode()).hexdigest()
    )
    prepared["blind_chart_id"] = "B-" + prepared._blind_sort_digest.str.slice(0, 20)
    prepared = prepared.sort_values(
        ["_blind_sort_digest", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    prepared.insert(0, "chart_number", np.arange(1, EXPECTED_EVENTS + 1, dtype=int))
    pd.testing.assert_frame_equal(
        prepared[["chart_number", "blind_chart_id"]].reset_index(drop=True),
        blind[["chart_number", "blind_chart_id"]].reset_index(drop=True),
        check_dtype=False,
    )
    joined = prepared.merge(
        blind,
        on=["chart_number", "blind_chart_id"],
        how="left",
        validate="one_to_one",
    )
    if joined[list(BLIND_INDEX_COLUMNS[2:])].isna().any().any():
        raise ResearchError("Phase-1 chart binding missing after blind-order reconstruction")
    return joined


def quote_sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


def load_outcomes(prepared: pd.DataFrame) -> pd.DataFrame:
    keys = prepared[["event_id"]].copy()
    columns = ",".join(f'o."{column}"' for column in OUTCOME_COLUMNS)
    connection = duckdb.connect()
    connection.register("phase2_event_keys", keys)
    try:
        outcomes = connection.execute(
            f"""
            SELECT {columns}
            FROM read_parquet('{quote_sql_path(OUTCOMES)}') o
            INNER JOIN phase2_event_keys k USING(event_id)
            WHERE o.signal_date BETWEEN DATE '{SIGNAL_START.date()}'
                                    AND DATE '{SIGNAL_END.date()}'
              AND (o.entry_date IS NULL OR o.entry_date <= DATE '{MAX_PATH_DATE.date()}')
              AND (o.exit_date IS NULL OR o.exit_date <= DATE '{MAX_PATH_DATE.date()}')
            ORDER BY o.event_id
            """
        ).fetch_df()
    finally:
        connection.unregister("phase2_event_keys")
        connection.close()
    require_columns(outcomes, OUTCOME_COLUMNS, "authorized Stage-B outcomes")
    outcomes["event_id"] = outcomes.event_id.astype(str)
    for column in ("signal_date", "entry_date", "exit_date"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    annual = outcomes.signal_date.dt.year.value_counts().sort_index().to_dict()
    if (
        len(outcomes) != EXPECTED_EVENTS
        or outcomes.event_id.duplicated().any()
        or set(outcomes.event_id) != set(prepared.event_id)
        or annual != EXPECTED_ANNUAL
        or outcomes.signal_date.min() != SIGNAL_START
        or outcomes.signal_date.max() != SIGNAL_END
        or outcomes.signal_date.gt(SIGNAL_END).any()
        or not outcomes.target_return.astype(float).eq(TARGET_RETURN).all()
        or not outcomes.horizon_sessions.astype(int).eq(HORIZON_SESSIONS).all()
        or not outcomes.round_trip_cost.astype(float).eq(ROUND_TRIP_COST).all()
        or outcomes.status.isna().any()
        or not set(outcomes.status.astype(str)).issubset(ALLOWED_STATUSES)
    ):
        raise ResearchError("authorized Stage-B outcome scope/constant drift")
    identity = prepared.merge(
        outcomes[
            [
                "event_id",
                "symbol",
                "causal_industry",
                "signal_date",
                "signal_cal_idx",
                "signal_invalid_step_cum",
            ]
        ],
        on="event_id",
        suffixes=("_prepared", "_outcome"),
        validate="one_to_one",
    )
    for field in ("symbol", "causal_industry", "signal_date", "signal_cal_idx"):
        if not identity[f"{field}_prepared"].eq(identity[f"{field}_outcome"]).all():
            raise ResearchError(f"prepared/outcome identity drift: {field}")
    if not identity.invalid_step_cum.eq(identity.signal_invalid_step_cum).all():
        raise ResearchError("prepared/outcome coordinate-lineage drift")

    completed = outcomes.status.astype(str).eq("COMPLETED")
    entered = outcomes.entry_cal_idx.notna()
    completed_net = pd.to_numeric(outcomes.loc[completed, "net_return"], errors="coerce")
    entered_prices = outcomes.loc[entered, ["entry_price", "target_price"]].apply(
        pd.to_numeric, errors="coerce"
    )
    completed_prices = outcomes.loc[completed, ["entry_price", "target_price", "exit_price"]].apply(
        pd.to_numeric, errors="coerce"
    )
    if (
        not np.isfinite(completed_net).all()
        or outcomes.loc[~completed, "net_return"].notna().any()
        or outcomes.loc[entered, ["entry_date", "entry_cal_idx", "entry_price", "target_price"]]
        .isna()
        .any(axis=None)
        or outcomes.loc[~entered, ["entry_date", "entry_price", "target_price"]]
        .notna()
        .any(axis=None)
        or outcomes.loc[completed, ["exit_date", "exit_cal_idx", "exit_price", "exit_reason"]]
        .isna()
        .any(axis=None)
        or outcomes.loc[~completed, ["exit_date", "exit_cal_idx", "exit_price", "exit_reason"]]
        .notna()
        .any(axis=None)
        or not np.isfinite(entered_prices).all(axis=None)
        or entered_prices.le(0).any(axis=None)
        or not np.isfinite(completed_prices).all(axis=None)
        or completed_prices.le(0).any(axis=None)
        or outcomes.loc[entered, "entry_cal_idx"].le(outcomes.loc[entered, "signal_cal_idx"]).any()
        or outcomes.loc[entered, "entry_cal_idx"]
        .gt(outcomes.loc[entered, "signal_cal_idx"] + 3)
        .any()
        or outcomes.loc[completed, "exit_cal_idx"]
        .le(outcomes.loc[completed, "entry_cal_idx"])
        .any()
        or outcomes.loc[completed, "exit_cal_idx"]
        .gt(outcomes.loc[completed, "signal_cal_idx"] + WINDOW)
        .any()
        or not outcomes.loc[completed, "exit_reason"].isin(ALLOWED_EXIT_REASONS).all()
        or not np.isclose(
            entered_prices.target_price.to_numpy(dtype=float),
            entered_prices.entry_price.to_numpy(dtype=float) * (1.0 + TARGET_RETURN),
            rtol=1e-12,
            atol=0.0,
        ).all()
        or any(
            outcomes[column].dropna().gt(MAX_PATH_DATE).any()
            for column in ("signal_date", "entry_date", "exit_date")
        )
    ):
        raise ResearchError("authorized Stage-B lifecycle chronology/value drift")
    return outcomes


def load_future_paths(prepared: pd.DataFrame) -> pd.DataFrame:
    keys = prepared[["event_id"]].copy()
    columns = ",".join(f'f."{column}"' for column in PATH_COLUMNS)
    connection = duckdb.connect()
    connection.register("phase2_event_keys", keys)
    try:
        paths = connection.execute(
            f"""
            SELECT {columns}
            FROM read_parquet('{quote_sql_path(FUTURE_PATHS)}') f
            INNER JOIN phase2_event_keys k USING(event_id)
            WHERE f.event_signal_date BETWEEN DATE '{SIGNAL_START.date()}'
                                          AND DATE '{SIGNAL_END.date()}'
              AND f.trade_date <= DATE '{MAX_PATH_DATE.date()}'
            ORDER BY f.event_id,f.cal_idx
            """
        ).fetch_df()
    finally:
        connection.unregister("phase2_event_keys")
        connection.close()
    require_columns(paths, PATH_COLUMNS, "authorized Stage-B future paths")
    paths["event_id"] = paths.event_id.astype(str)
    for column in ("event_signal_date", "trade_date", "available_at", "decision_at"):
        paths[column] = pd.to_datetime(paths[column])
    relative = paths.cal_idx.astype(int) - paths.event_signal_cal_idx.astype(int)
    coverage = (
        pd.DataFrame({"event_id": paths.event_id, "relative": relative})
        .groupby("event_id", sort=False)
        .relative.agg(["count", "nunique", "min", "max"])
    )
    if (
        paths.empty
        or paths.duplicated(["event_id", "cal_idx"]).any()
        or set(paths.event_id) != set(prepared.event_id)
        or paths.event_signal_date.lt(SIGNAL_START).any()
        or paths.event_signal_date.gt(SIGNAL_END).any()
        or paths.trade_date.gt(MAX_PATH_DATE).any()
        or paths.trade_date.le(paths.event_signal_date).any()
        or paths.cal_idx.le(paths.event_signal_cal_idx).any()
        or paths.cal_idx.gt(paths.event_signal_cal_idx + WINDOW).any()
        or paths.available_at.isna().any()
        or paths.decision_at.isna().any()
        or paths.available_at.gt(paths.decision_at).any()
        or len(coverage) != EXPECTED_EVENTS
        or not coverage["count"].eq(WINDOW).all()
        or not coverage["nunique"].eq(WINDOW).all()
        or not coverage["min"].eq(1).all()
        or not coverage["max"].eq(WINDOW).all()
        or paths.loc[paths.trade_date.dt.year.gt(2020), "event_signal_date"].dt.year.ne(2020).any()
    ):
        raise ResearchError("future-path +1..+126/buffer/PIT boundary drift")
    identity = prepared[["event_id", "symbol", "signal_date", "signal_cal_idx"]]
    observed = paths[
        ["event_id", "symbol", "event_signal_date", "event_signal_cal_idx"]
    ].drop_duplicates()
    check = identity.merge(observed, on="event_id", validate="one_to_one")
    if (
        len(check) != EXPECTED_EVENTS
        or not check.symbol_x.eq(check.symbol_y).all()
        or not check.signal_date.eq(check.event_signal_date).all()
        or not check.signal_cal_idx.eq(check.event_signal_cal_idx).all()
    ):
        raise ResearchError("future-path identity drift")
    return paths


def audit_lifecycle_markers(outcomes: pd.DataFrame, paths: pd.DataFrame) -> None:
    path_keys = paths[["event_id", "cal_idx", "trade_date"]].copy()
    for prefix in ("entry", "exit"):
        subset = outcomes.loc[
            outcomes[f"{prefix}_cal_idx"].notna(),
            ["event_id", f"{prefix}_cal_idx", f"{prefix}_date"],
        ].copy()
        if subset.empty:
            continue
        subset[f"{prefix}_cal_idx"] = subset[f"{prefix}_cal_idx"].astype(int)
        merged = subset.merge(
            path_keys,
            left_on=["event_id", f"{prefix}_cal_idx"],
            right_on=["event_id", "cal_idx"],
            how="left",
            validate="one_to_one",
        )
        if (
            merged.trade_date.isna().any()
            or not merged[f"{prefix}_date"].eq(merged.trade_date).all()
        ):
            raise ResearchError(f"{prefix} marker is not on the exact authorized path")


def outcome_bucket(status: str, net_return: Any) -> str:
    value = pd.to_numeric(pd.Series([net_return]), errors="coerce").iloc[0]
    if status != "COMPLETED" or not np.isfinite(value):
        return "NO_COMPLETED_TRADE"
    if value >= 0.04:
        return "PROFIT_GE_4PCT"
    if value >= 0.0:
        return "PROFIT_0_TO_4PCT"
    if value > -0.10:
        return "LOSS_0_TO_10PCT"
    return "SEVERE_LOSS"


def build_internal_event_ledger(prepared: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    outcome_by_id = outcomes.set_index("event_id", verify_integrity=True)
    rows: list[dict[str, Any]] = []
    for event in prepared.itertuples(index=False):
        outcome = outcome_by_id.loc[str(event.event_id)]
        rows.append(
            {
                "chart_number": int(event.chart_number),
                "blind_chart_id": str(event.blind_chart_id),
                "blind_chart_path": str(event.blind_chart_path),
                "blind_chart_sha256": str(event.blind_chart_sha256),
                # The following identity/execution fields remain in memory only.
                "event_id": str(event.event_id),
                "symbol": str(event.symbol),
                "signal_date": pd.Timestamp(event.signal_date),
                "signal_cal_idx": int(event.signal_cal_idx),
                "signal_invalid_step_cum": float(event.invalid_step_cum),
                "outcome_bucket": outcome_bucket(str(outcome.status), outcome.net_return),
                "status": str(outcome.status),
                "entry_cal_idx": outcome.entry_cal_idx,
                "entry_price": outcome.entry_price,
                "target_price": outcome.target_price,
                "exit_cal_idx": outcome.exit_cal_idx,
                "exit_price": outcome.exit_price,
                "exit_reason": outcome.exit_reason,
            }
        )
    ledger = pd.DataFrame(rows).sort_values("chart_number", kind="mergesort")
    if (
        len(ledger) != EXPECTED_EVENTS
        or ledger.chart_number.duplicated().any()
        or ledger.blind_chart_id.duplicated().any()
        or ledger.event_id.duplicated().any()
        or set(ledger.outcome_bucket) - set(OUTCOME_BUCKETS)
    ):
        raise ResearchError("internal anonymous event-ledger coverage drift")
    return ledger


def _strict_bool(frame: pd.DataFrame, column: str, expected: bool) -> pd.Series:
    return frame[column].notna() & frame[column].eq(expected)


def valid_post_bars(frame: pd.DataFrame, signal_invalid_step_cum: float) -> pd.DataFrame:
    raw = frame[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    stored = frame[["coord_open", "coord_high", "coord_low", "coord_close"]].apply(
        pd.to_numeric, errors="coerce"
    )
    factor = pd.to_numeric(frame.coordinate_factor, errors="coerce")
    raw_geometry = raw.high.ge(raw[["open", "close", "low"]].max(axis=1)) & raw.low.le(
        raw[["open", "close", "high"]].min(axis=1)
    )
    stored_geometry = stored.coord_high.ge(
        stored[["coord_open", "coord_close", "coord_low"]].max(axis=1)
    ) & stored.coord_low.le(stored[["coord_open", "coord_close", "coord_high"]].min(axis=1))
    relative = frame.cal_idx.astype(int) - frame.event_signal_cal_idx.astype(int)
    mask = (
        relative.between(1, WINDOW)
        & np.isfinite(raw).all(axis=1)
        & raw.gt(0).all(axis=1)
        & raw_geometry
        & np.isfinite(stored).all(axis=1)
        & stored.gt(0).all(axis=1)
        & stored_geometry
        & np.isfinite(factor)
        & factor.gt(0)
        & pd.to_numeric(frame.trade_status, errors="coerce").eq(1.0)
        & _strict_bool(frame, "current_day_data_tradable", True)
        & _strict_bool(frame, "current_valid", True)
        & _strict_bool(frame, "market_rule_valid", True)
        & _strict_bool(frame, "corporate_action_valid", True)
        & _strict_bool(frame, "corporate_action_blocking", False)
        & _strict_bool(frame, "hard_valid", True)
        & pd.to_numeric(frame.invalid_step_cum, errors="coerce").eq(float(signal_invalid_step_cum))
        & frame.available_at.notna()
        & frame.decision_at.notna()
        & frame.available_at.le(frame.decision_at)
    )
    result = frame.loc[mask].copy()
    # Ratio-first rendering is deliberate.  It preserves the raw candle
    # geometry without clipping or hidden normalization.
    result["render_open"] = result.coord_close * (result.open / result.close)
    result["render_high"] = result.coord_close * (result.high / result.close)
    result["render_low"] = result.coord_close * (result.low / result.close)
    result["render_close"] = result.coord_close
    result["relative"] = result.cal_idx.astype(int) - result.event_signal_cal_idx.astype(int)
    rendered = result[["render_open", "render_high", "render_low", "render_close"]].apply(
        pd.to_numeric, errors="coerce"
    )
    if (
        not np.isfinite(rendered).all(axis=None)
        or rendered.le(0).any(axis=None)
        or not rendered.render_high.ge(
            rendered[["render_open", "render_close", "render_low"]].max(axis=1)
        ).all()
        or not rendered.render_low.le(
            rendered[["render_open", "render_close", "render_high"]].min(axis=1)
        ).all()
    ):
        raise ResearchError("ratio-first coordinate candle geometry failed")
    return result.sort_values("cal_idx", kind="mergesort")


def font(size: int) -> ImageFont.ImageFont:
    for name in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def scale(values: list[float]) -> tuple[float, float]:
    finite = [float(value) for value in values if np.isfinite(value) and value > 0]
    if not finite:
        return 0.0, 1.0
    low, high = min(finite), max(finite)
    pad = max(abs(low) * 0.02, 1e-6) if math.isclose(low, high) else (high - low) * 0.06
    return low - pad, high + pad


def y_coordinate(value: float, bounds: tuple[float, float]) -> int:
    low, high = bounds
    return round(380 - (value - low) / (high - low) * 300)


def x_coordinate(relative: int) -> int:
    return round(44 + (relative - 1) / (WINDOW - 1) * 648)


def render_post_panel(event: dict[str, Any], paths: pd.DataFrame) -> Image.Image:
    image = Image.new("RGB", CHART_SIZE, "#ffffff")
    draw = ImageDraw.Draw(image)
    title_font, small = font(14), font(11)
    draw.text((8, 8), "POST-SIGNAL ATTRIBUTION +1..+126", fill="#111827", font=title_font)
    draw.text((8, 27), str(event["outcome_bucket"]), fill="#9a3412", font=small)
    draw.rectangle((42, 72, 694, 382), outline="#d1d5db", width=1)
    for relative in (1, 20, 63, 126):
        x = x_coordinate(relative)
        draw.line((x, 72, x, 382), fill="#e5e7eb", width=1)
        draw.text((x - 8, 389), f"+{relative}", fill="#6b7280", font=small)

    valid = valid_post_bars(paths, float(event["signal_invalid_step_cum"]))
    valid_cal_indices = set(valid.cal_idx.astype(int))
    marker_prices = [
        float(event[field])
        for field in ("entry_price", "target_price", "exit_price")
        if pd.notna(event.get(field)) and np.isfinite(float(event[field]))
    ]
    if valid.empty and not marker_prices:
        draw.text((240, 220), "NO VALID POST BARS", fill="#6b7280", font=title_font)
        return image
    price_values = (
        valid[["render_open", "render_high", "render_low", "render_close"]]
        .to_numpy(dtype=float)
        .ravel()
        .tolist()
        + marker_prices
    )
    bounds = scale(price_values)
    for row in valid.itertuples(index=False):
        x = x_coordinate(int(row.relative))
        open_y = y_coordinate(float(row.render_open), bounds)
        close_y = y_coordinate(float(row.render_close), bounds)
        high_y = y_coordinate(float(row.render_high), bounds)
        low_y = y_coordinate(float(row.render_low), bounds)
        color = "#dc2626" if float(row.render_close) >= float(row.render_open) else "#059669"
        draw.line((x, high_y, x, low_y), fill=color, width=1)
        draw.rectangle(
            (x - 1, min(open_y, close_y), x + 1, max(open_y, close_y) + 1),
            fill=color,
        )

    markers = (
        (event.get("entry_cal_idx"), event.get("entry_price"), "ENTRY", "#2563eb"),
        (event.get("exit_cal_idx"), event.get("exit_price"), "EXIT", "#7c3aed"),
    )
    for cal_idx, price, label, color in markers:
        if pd.isna(cal_idx) or pd.isna(price) or not np.isfinite(float(price)):
            continue
        relative = int(cal_idx) - int(event["signal_cal_idx"])
        if not 1 <= relative <= WINDOW:
            raise ResearchError(f"{label} marker outside +1..+126")
        if int(cal_idx) not in valid_cal_indices:
            raise ResearchError(f"{label} marker is not on a valid same-lineage bar")
        x = x_coordinate(relative)
        y = y_coordinate(float(price), bounds)
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=color)
        draw.text((x + 5, max(72, y - 8)), label, fill=color, font=small)
    target = event.get("target_price")
    if pd.notna(target) and np.isfinite(float(target)):
        target_y = y_coordinate(float(target), bounds)
        draw.line((42, target_y, 694, target_y), fill="#d97706", width=1)
        draw.text((620, max(72, target_y - 13)), "TARGET", fill="#d97706", font=small)
    draw.text(
        (8, 420),
        "Attribution only; +1..+20 primary, +21..+126 context; no numeric return",
        fill="#6b7280",
        font=small,
    )
    return image


def safe_phase1_chart(event: dict[str, Any]) -> Path:
    relative = Path(str(event["blind_chart_path"]))
    if relative.is_absolute() or ".." in relative.parts:
        raise ResearchError("unsafe Phase-1 chart path")
    path = PHASE1_CHART_ROOT / relative
    resolved_root = PHASE1_CHART_ROOT.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(resolved_root) or path.is_symlink():
        raise ResearchError("Phase-1 chart escapes anonymous corpus")
    if not path.is_file() or sha256(path) != str(event["blind_chart_sha256"]):
        raise ResearchError(f"Phase-1 chart hash drift: {event['blind_chart_id']}")
    return path


def render_one(payload: tuple[dict[str, Any], list[dict[str, Any]], str]) -> dict[str, Any]:
    event, path_records, output_text = payload
    with Image.open(safe_phase1_chart(event)) as source:
        left = source.convert("RGB")
    if left.size != CHART_SIZE:
        raise ResearchError(f"unexpected Phase-1 chart dimensions: {left.size}")
    paths = pd.DataFrame.from_records(path_records, columns=list(PATH_COLUMNS))
    right = render_post_panel(event, paths)
    combined = Image.new("RGB", FULL_CHART_SIZE, "white")
    combined.paste(left, (0, 0))
    combined.paste(right, (CHART_SIZE[0], 0))
    draw = ImageDraw.Draw(combined)
    draw.line((719, 0, 719, 439), fill="#111827", width=2)
    output = Path(output_text)
    combined.save(output, format="PNG", optimize=True)
    return {
        "chart_number": int(event["chart_number"]),
        "blind_chart_id": str(event["blind_chart_id"]),
        "full_chart_path": str(output),
        "full_chart_sha256": sha256(output),
        "outcome_bucket": str(event["outcome_bucket"]),
    }


def build_contact_sheets(
    chart_index: pd.DataFrame, output_root: Path
) -> tuple[pd.DataFrame, pd.DataFrame]:
    placements: list[dict[str, Any]] = []
    sheets: list[dict[str, Any]] = []
    for bucket in OUTCOME_BUCKETS:
        subset = chart_index.loc[chart_index.outcome_bucket.eq(bucket)].sort_values(
            "chart_number", kind="mergesort"
        )
        bucket_dir = output_root / "outcome_sheets" / bucket.lower()
        bucket_dir.mkdir(parents=True, exist_ok=False)
        for sheet_number, start in enumerate(range(0, len(subset), 25), start=1):
            part = subset.iloc[start : start + 25]
            sheet = Image.new("RGB", CONTACT_SIZE, "#f8fafc")
            draw = ImageDraw.Draw(sheet)
            draw.text(
                (12, 8),
                f"V36 PHASE2 | {bucket} | PAGE {sheet_number:04d}",
                fill="#111827",
                font=font(18),
            )
            sheet_path = bucket_dir / f"sheet_{sheet_number:04d}.jpg"
            for slot, row in enumerate(part.itertuples(index=False), start=1):
                with Image.open(row.full_chart_path) as source:
                    thumb = source.convert("RGB").resize((348, 202), Image.Resampling.LANCZOS)
                column = (slot - 1) % GRID_COLUMNS
                grid_row = (slot - 1) // GRID_COLUMNS
                x, y = 6 + column * 358, 40 + grid_row * 218
                sheet.paste(thumb, (x, y))
                draw.text(
                    (x + 3, y + 204),
                    f"#{int(row.chart_number):04d} {row.blind_chart_id}",
                    fill="#111827",
                    font=font(10),
                )
                placements.append(
                    {
                        "outcome_bucket": bucket,
                        "sheet_path": str(sheet_path),
                        "sheet_number": sheet_number,
                        "slot": slot,
                        "chart_number": int(row.chart_number),
                        "blind_chart_id": str(row.blind_chart_id),
                    }
                )
            sheet.save(sheet_path, format="JPEG", quality=92, subsampling=0)
            sheets.append(
                {
                    "outcome_bucket": bucket,
                    "sheet_path": str(sheet_path),
                    "sheet_number": sheet_number,
                    "sheet_sha256": sha256(sheet_path),
                    "charts": len(part),
                }
            )
    return pd.DataFrame(placements), pd.DataFrame(sheets)


def relative_output_path(staging: Path, path_text: str) -> str:
    path = Path(path_text)
    relative = path.relative_to(staging)
    if relative.is_absolute() or ".." in relative.parts:
        raise ResearchError("unsafe output-relative path")
    return str(relative)


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def reverify_before_publish(
    public_hashes: dict[str, str],
    phase1_hashes: dict[str, str],
    stage_b_hashes: dict[str, str],
) -> None:
    current, _authorization, current_stage_b = verify_public_authorization()
    if current != public_hashes or current_stage_b != stage_b_hashes:
        raise ResearchError("public CY-058 contract changed during rendering")
    for role, path in PHASE1_EXTERNAL_ROLES:
        if sha256(path) != phase1_hashes[role]:
            raise ResearchError(f"Phase-1 input changed during rendering: {role}")
    # STAGE_B_RESULT is deliberately omitted and therefore remains untouched.
    for role, path in (
        ("stage_b_prepared_candidates", PREPARED),
        ("stage_b_future_paths", FUTURE_PATHS),
        ("stage_b_outcomes", OUTCOMES),
    ):
        if sha256(path) != stage_b_hashes[role]:
            raise ResearchError(f"authorized Stage-B artifact changed: {role}")


def atomic_publish_no_replace(source: Path, destination: Path) -> None:
    """Atomically publish a directory while refusing every existing target."""
    libc = ctypes.CDLL(None, use_errno=True)
    rename_exclusive = getattr(libc, "renamex_np", None)
    if rename_exclusive is None:
        raise ResearchError("atomic exclusive directory rename is unavailable")
    rename_exclusive.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    rename_exclusive.restype = ctypes.c_int
    if rename_exclusive(os.fsencode(source), os.fsencode(destination), 0x00000004):
        error = ctypes.get_errno()
        raise ResearchError(f"atomic no-overwrite publication failed: {os.strerror(error)}")


def run(workers: int) -> dict[str, Any]:
    public_hashes, _authorization, expected_stage_b = verify_public_authorization()
    if OUTPUT.exists() or OUTPUT.is_symlink():
        raise ResearchError(f"refusing to overwrite V36 Phase-2 output: {OUTPUT}")

    # No external Phase-1 or Stage-B path is touched before the joint gate above.
    blind = verify_phase1_external()
    phase1_hashes = {role: PHASE1_EXTERNAL_HASHES[path] for role, path in PHASE1_EXTERNAL_ROLES}
    stage_b_hashes = {
        "stage_b_prepared_candidates": verify_hash_after_authorization(
            PREPARED,
            expected_stage_b["stage_b_prepared_candidates"],
            "Stage-B prepared candidates",
        ),
        "stage_b_future_paths": verify_hash_after_authorization(
            FUTURE_PATHS,
            expected_stage_b["stage_b_future_paths"],
            "Stage-B future paths",
        ),
        "stage_b_outcomes": verify_hash_after_authorization(
            OUTCOMES,
            expected_stage_b["stage_b_outcomes"],
            "Stage-B outcomes",
        ),
        "stage_b_result_declared_sha256_only": expected_stage_b[
            "stage_b_result_declared_only_unread"
        ],
    }
    # STAGE_B_RESULT is intentionally never statted, hashed, opened, or parsed.
    prepared = load_prepared_and_rebuild_blind_order(blind)
    outcomes = load_outcomes(prepared)
    paths = load_future_paths(prepared)
    audit_lifecycle_markers(outcomes, paths)
    events = build_internal_event_ledger(prepared, outcomes)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{OUTPUT.name}.staging-", dir=OUTPUT.parent))
    try:
        chart_dir = staging / "individual_attribution_charts"
        chart_dir.mkdir(parents=True, exist_ok=False)
        path_groups = {
            str(event_id): group.copy() for event_id, group in paths.groupby("event_id", sort=False)
        }
        tasks: list[tuple[dict[str, Any], list[dict[str, Any]], str]] = []
        for event in events.to_dict("records"):
            path_group = path_groups.get(str(event["event_id"]))
            if path_group is None or len(path_group) != WINDOW:
                raise ResearchError("missing exact +1..+126 event path before rendering")
            output_path = chart_dir / f"{event['blind_chart_id']}.png"
            tasks.append((event, path_group.to_dict("records"), str(output_path)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            chart_index = pd.DataFrame(executor.map(render_one, tasks))
        chart_index = chart_index.sort_values("chart_number", kind="mergesort")
        if (
            len(chart_index) != EXPECTED_EVENTS
            or chart_index.chart_number.tolist() != list(range(1, EXPECTED_EVENTS + 1))
            or chart_index.chart_number.duplicated().any()
            or chart_index.blind_chart_id.duplicated().any()
            or len(list(chart_dir.glob("*.png"))) != EXPECTED_EVENTS
            or set(chart_index.outcome_bucket) - set(OUTCOME_BUCKETS)
        ):
            raise ResearchError("rendered individual-chart coverage drift")

        placements, sheet_index = build_contact_sheets(chart_index, staging)
        if (
            len(placements) != EXPECTED_EVENTS
            or placements.chart_number.duplicated().any()
            or placements.blind_chart_id.duplicated().any()
            or set(placements.chart_number) != set(chart_index.chart_number)
        ):
            raise ResearchError("outcome-sheet exactly-once coverage drift")
        pd.testing.assert_frame_equal(
            placements[["chart_number", "blind_chart_id", "outcome_bucket"]]
            .sort_values("chart_number")
            .reset_index(drop=True),
            chart_index[["chart_number", "blind_chart_id", "outcome_bucket"]]
            .sort_values("chart_number")
            .reset_index(drop=True),
            check_dtype=False,
        )

        chart_index["full_chart_path"] = chart_index.full_chart_path.map(
            lambda value: relative_output_path(staging, str(value))
        )
        chart_index = chart_index[
            [
                "chart_number",
                "blind_chart_id",
                "full_chart_path",
                "full_chart_sha256",
                "outcome_bucket",
            ]
        ]
        chart_index.to_csv(staging / "phase2_chart_index.csv", index=False)

        placements["sheet_path"] = placements.sheet_path.map(
            lambda value: relative_output_path(staging, str(value))
        )
        placements = placements[
            [
                "outcome_bucket",
                "sheet_path",
                "sheet_number",
                "slot",
                "chart_number",
                "blind_chart_id",
            ]
        ].sort_values(["outcome_bucket", "sheet_number", "slot"], kind="mergesort")
        placements.to_csv(staging / "outcome_sheet_placements.csv", index=False)

        sheet_index["sheet_path"] = sheet_index.sheet_path.map(
            lambda value: relative_output_path(staging, str(value))
        )
        sheet_index = sheet_index[
            [
                "outcome_bucket",
                "sheet_path",
                "sheet_number",
                "sheet_sha256",
                "charts",
            ]
        ].sort_values(["outcome_bucket", "sheet_number"], kind="mergesort")
        if (
            int(sheet_index.charts.sum()) != EXPECTED_EVENTS
            or not sheet_index.charts.between(1, GRID_COLUMNS * GRID_ROWS).all()
        ):
            raise ResearchError("outcome-sheet index coverage drift")
        sheet_index.to_csv(staging / "outcome_sheet_index.csv", index=False)

        review_template = [
            {
                "chart_number": int(row.chart_number),
                "blind_chart_id": str(row.blind_chart_id),
                "outcome_bucket": str(row.outcome_bucket),
                "post_path_label": "",
                "evidence": "",
                "reviewer": "",
                "phase1_labels_modified": False,
                "signal_candle_used_for_rule": False,
                "post_signal_used_as_predictor": False,
            }
            for row in chart_index.itertuples(index=False)
        ]
        write_json(staging / "phase2_review_template.json", review_template)

        output_names = (
            "phase2_chart_index.csv",
            "outcome_sheet_placements.csv",
            "outcome_sheet_index.csv",
            "phase2_review_template.json",
        )
        output_hashes = {name: sha256(staging / name) for name in output_names}
        bucket_counts = {
            bucket: int(chart_index.outcome_bucket.eq(bucket).sum()) for bucket in OUTCOME_BUCKETS
        }
        bucket_pages = {
            bucket: int(sheet_index.outcome_bucket.eq(bucket).sum()) for bucket in OUTCOME_BUCKETS
        }
        if sum(bucket_counts.values()) != EXPECTED_EVENTS:
            raise ResearchError("outcome buckets do not sum to all 531 events")
        result_manifest = {
            "experiment": EXPERIMENT,
            "stage": STAGE,
            "status": "PUBLISHED_ANONYMOUS_2019_2020_ATTRIBUTION_CORPUS",
            "asset_id": ASSET_ID,
            "authorization_id": AUTHORIZATION_ID,
            "authorized_arm": AUTHORIZED_ARM,
            "pipeline_version": PIPELINE_VERSION,
            "events": EXPECTED_EVENTS,
            "annual_signal_counts": {str(year): count for year, count in EXPECTED_ANNUAL.items()},
            "signal_start": str(SIGNAL_START.date()),
            "signal_end": str(SIGNAL_END.date()),
            "maximum_path_row_date": str(paths.trade_date.max().date()),
            "path_relative_global_sessions": [1, WINDOW],
            "path_rows_per_event": WINDOW,
            "individual_attribution_charts": EXPECTED_EVENTS,
            "chart_size_pixels": list(FULL_CHART_SIZE),
            "outcome_contact_sheets": len(sheet_index),
            "contact_sheet_grid": [GRID_COLUMNS, GRID_ROWS],
            "outcome_bucket_definitions": BUCKET_DEFINITIONS,
            "outcome_bucket_counts": bucket_counts,
            "outcome_bucket_page_counts": bucket_pages,
            "source_hashes": {
                **public_hashes,
                **phase1_hashes,
                **stage_b_hashes,
            },
            "output_hashes": output_hashes,
            "opaque_order_algorithm": (
                "SHA256(UTF8('V36_PHASE1_CAUSAL_MASKED_ORDER_V1|' + exact event_id)); "
                "ascending full digest, then exact event_id as collision tie-break"
            ),
            "blind_chart_id_algorithm": "'B-' plus first 20 lowercase digest hex",
            "anonymous_identity_coverage_exactly_once": True,
            "outcome_group_coverage_exactly_once": True,
            "identity_mapping_reconstructed_in_memory": True,
            "identity_crosswalk_persisted": False,
            "identity_exposed_to_reviewer": False,
            "numeric_returns_persisted": False,
            "phase1_labels_read": False,
            "phase1_labels_modified": False,
            "signal_candle_used_for_rule": False,
            "post_signal_used_as_predictor": False,
            "rule_search_performed": False,
            "rule_aggregation_performed": False,
            "portfolio_replay_performed": False,
            "candidate_reselection_performed": False,
            "stage_b_result_stat_hash_open_parse": False,
            "post_2020_signal_row_read": False,
            "2021_signal_row_read": False,
            "2021_rows_used_only_as_late_2020_path_completion": bool(
                paths.trade_date.dt.year.eq(2021).any()
            ),
            "post_2021_q3_row_read": False,
            "2022_plus_row_read": False,
            "next_action": "REVIEW_AND_FREEZE_ALL_531_ANONYMOUS_PHASE2_ATTRIBUTIONS",
        }
        write_json(staging / "manifest.json", result_manifest)

        reverify_before_publish(public_hashes, phase1_hashes, expected_stage_b)
        if OUTPUT.exists() or OUTPUT.is_symlink():
            raise ResearchError(f"canonical V36 Phase-2 output appeared: {OUTPUT}")
        atomic_publish_no_replace(staging, OUTPUT)
        return {
            **result_manifest,
            "manifest_sha256": sha256(OUTPUT / "manifest.json"),
            "output": str(OUTPUT),
        }
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--verify-static-contract",
        action="store_true",
        help="verify repository-only package; never touch an external artifact",
    )
    mode.add_argument(
        "--verify-public-authorization",
        action="store_true",
        help="verify CY-058 literal bindings; never touch external Phase-1/Stage-B files",
    )
    mode.add_argument(
        "--run",
        action="store_true",
        help="render all 531 charts after exact CY-058 authorization",
    )
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.workers < 1 or args.workers > 16:
        raise ResearchError("workers must be between 1 and 16")
    if args.verify_static_contract:
        print(json.dumps(verify_static_contract(), indent=2, sort_keys=True))
        return
    if args.verify_public_authorization:
        actual, _authorization, stage_b_hashes = verify_public_authorization()
        print(
            json.dumps(
                {
                    "verified": True,
                    "public_hashes": actual,
                    "stage_b_hashes_compared_as_literals_only": stage_b_hashes,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    print(json.dumps(run(args.workers), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
