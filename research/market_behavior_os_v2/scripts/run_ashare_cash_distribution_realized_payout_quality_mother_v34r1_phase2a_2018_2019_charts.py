#!/usr/bin/env python3
"""Build the frozen V34R1 Phase-2A 2018-2019 attribution corpus.

This runner has three deliberately separate gates:

``--verify-static-contract`` reads repository contracts only.  It never touches
the Phase-1 external corpus or any Stage-B artifact.

``--verify-public-authorization`` additionally validates the future CY-056
registry authorization using literal path/hash strings.  It still must not
stat, hash, open, or parse Stage-B prepared/result/future/outcome files.

``--run`` is unavailable until the exact CY-056 authorization exists.  Only
after that gate may it verify the frozen Phase-1 ledger, reconstruct the opaque
mapping in memory, hash the authorized Stage-B prepared/future/outcome files,
and parse rows belonging to 2018-2019 signal cohorts.  The aggregate Stage-B
result remains declared-only and is never touched.  No 2020 signal outcome or
path row is fetched, and no 2021-plus row is fetched.

The output is anonymous descriptive attribution.  It neither aggregates nor
tests a rule and cannot authorize a replay or a 2020 holdout read.
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

EXPERIMENT = "ASHARE-CASH-DISTRIBUTION-REALIZED-PAYOUT-QUALITY-MOTHER-V34R1"
STAGE = "PHASE2A_2018_2019_ANONYMOUS_OUTCOME_ATTRIBUTION"
REPO = Path(__file__).resolve().parents[3]
EXP = REPO / "research/market_behavior_os_v2/experiments"
REGISTRY = REPO / "configs/data_asset_registry.json"

PHASE2A_SPEC = EXP / (
    f"{EXPERIMENT}_phase2a_2018_2019_visual_attribution_freeze.json"
)
PARENT_SPEC = EXP / f"{EXPERIMENT}_freeze.json"
STAGE_B_SPEC = EXP / f"{EXPERIMENT}_stage_b_freeze.json"
STAGE_B_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_cash_distribution_realized_payout_quality_mother_v34r1_stage_b.py"
)
STAGE_B_MANIFEST = EXP / "ASHARE-V34R1-CY049_DATA_ASSET_MANIFEST.json"
PHASE1_SPEC = EXP / f"{EXPERIMENT}_visual_review_spec.json"
PHASE1_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_cash_distribution_realized_payout_quality_mother_v34r1_phase1_charts.py"
)
PHASE1_LEDGER_FREEZE = EXP / "ASHARE-V34R1_phase1_ledger_freeze_spec.json"
PHASE1_FINALIZER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "finalize_ashare_cash_distribution_realized_payout_quality_mother_v34r1_phase1.py"
)
PHASE1_AXIS_DECISION = EXP / "ASHARE-V34R1_phase1_axis_reliability_decision.json"
PHASE2A_MANIFEST = EXP / "ASHARE-V34R1-CY056_OUTCOME_ATTRIBUTION_ASSET_MANIFEST.json"

ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_cash_distribution_realized_payout_quality_mother_v34r1"
)
STAGE_B = ROOT / "stage_b"
PREPARED = STAGE_B / "prepared_candidates.parquet"
STAGE_B_RESULT = STAGE_B / "result.json"
FUTURE_PATHS = STAGE_B / "future_paths.parquet"
OUTCOMES = STAGE_B / "outcomes.parquet"
PHASE1_CHART_ROOT = ROOT / "stage_c_phase1_anonymous_charts"
PHASE1_CHART_MANIFEST = PHASE1_CHART_ROOT / "manifest.json"
PHASE1_REVIEW_ROOT = ROOT / "stage_d_phase1_anonymous_review"
PHASE1_LEDGER = PHASE1_REVIEW_ROOT / "phase1_annotation_ledger.csv"
PHASE1_LEDGER_MANIFEST = PHASE1_REVIEW_ROOT / "manifest.json"
OUTPUT = ROOT / "stage_e_phase2a_2018_2019_outcome_attribution"

ASSET_ID = "CY-056"
DEPENDENCY_ASSET_ID = "CY-052"
AUTHORIZATION_ID = (
    "CYQ-AUTH-ASHARE-CASH-DISTRIBUTION-PAYOUT-QUALITY-"
    "V34R1-PHASE2A-CY056-OUTCOME-ATTRIBUTION-2018-2019-V1"
)
AUTHORIZED_ARM = "V34R1_PHASE2A_2018_2019_OUTCOME_ATTRIBUTION_ONLY"
AUTHORIZATION_PURPOSE = "ASHARE_FROZEN_DEVELOPMENT_OUTCOME_CHART_ATTRIBUTION"
MANIFEST_STATUS = "FROZEN_DEVELOPMENT_OUTCOME_ATTRIBUTION_BOUNDED_INPUT"
PIPELINE_VERSION = "v34r1-phase2a-2018-2019-anonymous-outcome-attribution-v1"

EXPECTED_ALL_EVENTS = 1_483
EXPECTED_PHASE2A_EVENTS = 915
EXPECTED_PHASE2A_ANNUAL = {2018: 395, 2019: 520}
DISCOVERY_SIGNAL_START = pd.Timestamp("2018-03-27")
DISCOVERY_SIGNAL_END = pd.Timestamp("2019-12-31")
SEALED_SIGNAL_START = pd.Timestamp("2020-01-01")
SEALED_SIGNAL_END = pd.Timestamp("2020-12-31")
MAX_PARSED_PATH_DATE = pd.Timestamp("2020-12-31")
WINDOW = 126
TARGET_RETURN = 0.10
HORIZON_SESSIONS = 20
ROUND_TRIP_COST = 0.004
OPAQUE_ORDER_SALT = "V34R1_PHASE1_CAUSAL_MASKED_ORDER_V1"

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

# Repository files are safe in every mode.  The values bind the inputs that
# existed when this static package was frozen.  PHASE2A_SPEC is verified
# separately because it binds this runner and is written after the runner.
REPO_HASHES: dict[Path, str] = {
    PARENT_SPEC: "e41bfe9de6c68878ea556cf31397075adda9076adc19a4089215284436c6bdb4",
    STAGE_B_SPEC: "94def5859b602bde8a635d2e4079c9aea4c1c27bee4161843259ac9dfb928041",
    STAGE_B_RUNNER: "8755bbe18ca76c788ca74ed1743a34bbbd09c8ffc75889b49f026c7e2fad13e5",
    STAGE_B_MANIFEST: "88789d69a4cc4e68d13eefcd8ccf09376f6588b4861939c0c8b0158bdf2be877",
    PHASE1_SPEC: "91396a0792729efc5f2ab0b9535cd8b930a4d635563840ce0436eb7648a445db",
    PHASE1_RUNNER: "9f53f6ba73ce931c1c77d919d2e3b5f5fcee45954a4bad7a48d4695d2f7d5e5a",
    PHASE1_LEDGER_FREEZE: "c61fa74261a30a6ac115c594ab6cd7102591efe0e47710b930a086cdeba3ae4f",
    PHASE1_FINALIZER: "205b97379e47c2f207398d1fe1db3a1e71e1c79c4740b5942089bf9640b5f970",
    PHASE1_AXIS_DECISION: "247dea6890a4053a5c9f7f3abfef167046cbdd14535cffe9b4ae7711bfdbd68f",
}

# External Phase-1 files contain no outcomes.  They are not touched by either
# verification-only mode; --run verifies them only after CY-056 passes.
PHASE1_EXTERNAL_HASHES: dict[Path, str] = {
    PHASE1_CHART_MANIFEST: "69d660b35c8f3183cf82220888572fcca7494607c0224606b2c33064c535edcc",
    PHASE1_LEDGER_MANIFEST: "540c77afb93d61d3b729491936b720f76a77eeb6302d93e6989d2574421e041d",
    PHASE1_LEDGER: "a70aac69ca58f9302f7af59a301800f6398b806705d461b7b18a91d92a56f474",
}

# These are declaration strings in public modes.  Do not resolve, stat, hash,
# open, or parse these paths until the exact joint run authorization passes.
STAGE_B_HASHES: dict[Path, str] = {
    PREPARED: "7f103518ca4fd00628ab1d7fddf97367aa208adce099aa3894008d92afa4a52b",
    STAGE_B_RESULT: "cec33ec8e571effe73e86f7517a0c5cebcf09c07d41850202fc9ca8cf3cb84eb",
    FUTURE_PATHS: "371db6417b92974fa1d1860d67f89dab7654b97c95e97dad25be0d7f0d9050a5",
    OUTCOMES: "ef21c19376e1db63bbbbfe8b2e9b62b436a647168cbd83640f7f14ad8312c356",
}

REPO_BOUND_ROLES = (
    ("parent_freeze", PARENT_SPEC),
    ("stage_b_freeze", STAGE_B_SPEC),
    ("stage_b_runner", STAGE_B_RUNNER),
    ("stage_b_asset_manifest", STAGE_B_MANIFEST),
    ("phase1_visual_review_spec", PHASE1_SPEC),
    ("phase1_chart_runner", PHASE1_RUNNER),
    ("phase1_ledger_freeze_spec", PHASE1_LEDGER_FREEZE),
    ("phase1_finalizer", PHASE1_FINALIZER),
    ("phase1_axis_reliability_decision", PHASE1_AXIS_DECISION),
)
PHASE1_EXTERNAL_ROLES = (
    ("phase1_chart_corpus_manifest", PHASE1_CHART_MANIFEST),
    ("phase1_annotation_manifest", PHASE1_LEDGER_MANIFEST),
    ("phase1_annotation_ledger", PHASE1_LEDGER),
)
STAGE_B_ROLES = (
    ("stage_b_prepared_candidates", PREPARED),
    ("stage_b_result_declared_only_unread", STAGE_B_RESULT),
    ("stage_b_future_paths", FUTURE_PATHS),
    ("stage_b_outcomes", OUTCOMES),
)

PHASE1_LEDGER_IDENTITY_COLUMNS = (
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
    "signal_cal_idx",
    "invalid_step_cum",
    "known_at",
    "decision_at",
    "signal_row_available_at",
    "signal_row_decision_at",
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
    "trade_status",
    "current_day_data_tradable",
    "current_valid",
    "market_rule_valid",
    "corporate_action_valid",
    "corporate_action_blocking",
    "hard_valid",
    "available_at",
    "decision_at",
)


class ResearchError(RuntimeError):
    """Fail-closed contract violation."""


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
        raise ResearchError(f"expected one {label}; found {len(items)}")
    return items[0]


def require_columns(frame: pd.DataFrame, required: tuple[str, ...], label: str) -> None:
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ResearchError(f"{label} missing columns: {missing}")


def bound_artifact_map(authorization: dict[str, Any]) -> dict[str, dict[str, Any]]:
    artifacts = authorization.get("bound_artifacts", [])
    if not isinstance(artifacts, list):
        raise ResearchError("authorization bound_artifacts must be a list")
    result: dict[str, dict[str, Any]] = {}
    for item in artifacts:
        if not isinstance(item, dict) or not isinstance(item.get("role"), str):
            raise ResearchError("authorization bound_artifacts has malformed item")
        role = str(item["role"])
        if role in result:
            raise ResearchError(f"duplicate bound-artifact role: {role}")
        result[role] = item
    return result


def assert_literal_binding(
    artifacts: dict[str, dict[str, Any]], role: str, path: Path, expected_hash: str
) -> None:
    """Compare strings without touching the external ``path``."""
    item = artifacts.get(role)
    if (
        item is None
        or item.get("path") != str(path)
        or item.get("sha256") != expected_hash
    ):
        raise ResearchError(f"CY-056 does not bind exact artifact {role}")


def verify_static_contract() -> dict[str, str]:
    """Verify repository-only frozen inputs; never touch an external path."""
    required = (*REPO_HASHES, PHASE2A_SPEC, Path(__file__))
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ResearchError(f"missing repository contract input: {missing}")
    actual: dict[str, str] = {}
    for path, expected in REPO_HASHES.items():
        value = sha256(path)
        if value != expected:
            raise ResearchError(f"repository frozen input drift: {path}: {value}")
        actual[str(path.relative_to(REPO))] = value

    runner_hash = sha256(Path(__file__))
    spec_hash = sha256(PHASE2A_SPEC)
    spec = load_json(PHASE2A_SPEC, "Phase-2A freeze")
    renderer = spec.get("renderer", {})
    scope = spec.get("scope", {})
    seal = spec.get("temporal_holdout_seal", {})
    buckets = spec.get("outcome_groups", {})
    review_schema = spec.get("phase2a_review_schema", {})
    rule_boundary = spec.get("future_rule_translation_boundary", {})
    if (
        spec.get("experiment") != EXPERIMENT
        or spec.get("stage") != STAGE
        or spec.get("status") != "STATIC_FROZEN_AWAITING_CY056_AUTHORIZATION"
        or renderer.get("path") != str(Path(__file__).relative_to(REPO))
        or renderer.get("sha256") != runner_hash
        or scope.get("all_phase1_events") != EXPECTED_ALL_EVENTS
        or scope.get("phase2a_events") != EXPECTED_PHASE2A_EVENTS
        or scope.get("annual_signal_counts")
        != {str(year): count for year, count in EXPECTED_PHASE2A_ANNUAL.items()}
        or scope.get("signal_start") != str(DISCOVERY_SIGNAL_START.date())
        or scope.get("signal_end") != str(DISCOVERY_SIGNAL_END.date())
        or scope.get("post_window") != [1, WINDOW]
        or seal.get("sealed_signal_year") != 2020
        or seal.get("2020_outcome_row_parse_authorized") is not False
        or seal.get("2020_path_row_parse_authorized") is not False
        or seal.get("2020_phase1_label_parse_authorized") is not False
        or seal.get("2021_plus_row_parse_authorized") is not False
        or buckets.get("ordered_buckets") != list(OUTCOME_BUCKETS)
        or buckets.get("definitions") != BUCKET_DEFINITIONS
        or review_schema.get("exact_fields") != list(REVIEW_FIELDS)
        or review_schema.get("post_path_labels") != list(POST_PATH_LABELS)
        or review_schema.get("phase1_labels_modified") is not False
        or review_schema.get("signal_candle_used_for_rule") is not False
        or review_schema.get("post_signal_used_as_predictor") is not False
        or rule_boundary.get("maximum_objective_numeric_clauses") != 5
        or rule_boundary.get("signal_candle_axis_rule_eligible") is not False
        or rule_boundary.get("post_signal_path_rule_eligible") is not False
        or spec.get("rule_aggregation_authorized") is not False
        or spec.get("portfolio_replay_authorized") is not False
    ):
        raise ResearchError("Phase-2A static semantics drift")

    declared = spec.get("declared_artifacts", {})
    for role, path in (*PHASE1_EXTERNAL_ROLES, *STAGE_B_ROLES):
        item = declared.get(role, {})
        expected = PHASE1_EXTERNAL_HASHES.get(path, STAGE_B_HASHES.get(path))
        if item.get("path") != str(path) or item.get("sha256") != expected:
            raise ResearchError(f"Phase-2A declared artifact drift: {role}")
    if declared.get("stage_b_result_declared_only_unread", {}).get("access") != (
        "DECLARED_ONLY_NEVER_STAT_HASH_OPEN_OR_PARSE_IN_PHASE2A"
    ):
        raise ResearchError("Stage-B result is not strictly declared-only")
    actual["phase2a_spec"] = spec_hash
    actual["phase2a_runner"] = runner_hash
    return actual


def verify_public_authorization() -> tuple[dict[str, str], dict[str, Any]]:
    """Validate CY-056 metadata without touching any external file."""
    actual = verify_static_contract()
    missing = [str(path) for path in (REGISTRY, PHASE2A_MANIFEST) if not path.is_file()]
    if missing:
        raise ResearchError(f"missing public authorization input: {missing}")
    actual["registry"] = sha256(REGISTRY)
    actual["phase2a_manifest"] = sha256(PHASE2A_MANIFEST)
    registry = load_json(REGISTRY, "data registry")
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
    lineage = asset.get("lineage", {})
    protocol = authorization.get("bound_protocol", {})
    scope = authorization.get("scope", {})
    bound_manifest = authorization.get("bound_manifest", {})
    if (
        asset.get("status") != "RESEARCH_CONDITIONAL"
        or asset.get("kind")
        != "bounded_daily_pit_b_development_outcome_chart_attribution_input"
        or asset.get("pit_grade") != "B"
        or asset.get("physical_state") != "MATERIALIZED"
        or asset.get("location") != str(STAGE_B)
        or lineage.get("manifest_path") != str(PHASE2A_MANIFEST.resolve())
        or lineage.get("manifest_sha256") != actual["phase2a_manifest"]
        or lineage.get("bounded_authorization_id") != AUTHORIZATION_ID
        or lineage.get("pipeline_version") != PIPELINE_VERSION
        or authorization.get("asset_id") != ASSET_ID
        or authorization.get("dependency_asset_id") != DEPENDENCY_ASSET_ID
        or authorization.get("dependency_asset_ids")
        != [DEPENDENCY_ASSET_ID, "CY-049"]
        or authorization.get("dependency_status") != "RESEARCH_CONDITIONAL"
        or authorization.get("purpose") != AUTHORIZATION_PURPOSE
        or authorization.get("authorized_arms") != [AUTHORIZED_ARM]
        or bound_manifest.get("path") != str(PHASE2A_MANIFEST.resolve())
        or bound_manifest.get("sha256") != actual["phase2a_manifest"]
        or authorization.get("record_level_available_at_available") is not False
        or protocol.get("path") != str(PHASE2A_SPEC.resolve())
        or protocol.get("sha256") != actual["phase2a_spec"]
        or protocol.get("runner_path") != str(Path(__file__).resolve())
        or protocol.get("runner_sha256") != actual["phase2a_runner"]
        or scope.get("signal_start") != str(DISCOVERY_SIGNAL_START.date())
        or scope.get("signal_end") != str(DISCOVERY_SIGNAL_END.date())
        or scope.get("frozen_phase2a_events") != EXPECTED_PHASE2A_EVENTS
        or scope.get("sealed_signal_year") != 2020
    ):
        raise ResearchError("CY-056 authorization identity/scope drift")

    required_true = (
        "phase2a_authorized",
        "phase1_frozen_ledger_read_authorized",
        "prepared_identity_read_authorized",
        "outcome_artifact_hash_authorized",
        "2018_2019_outcome_row_parse_authorized",
        "2018_2019_post_signal_row_parse_authorized",
        "outcome_grouping_authorized",
        "anonymous_full_chart_authorized",
        "in_memory_identity_reconstruction_authorized",
    )
    required_false = (
        "stage_b_result_access_authorized",
        "2020_outcome_row_parse_authorized",
        "2020_path_row_parse_authorized",
        "2020_phase1_label_parse_authorized",
        "2021_plus_row_parse_authorized",
        "identity_crosswalk_persistence_authorized",
        "identity_reveal_authorized",
        "phase1_label_rewrite_authorized",
        "signal_candle_rule_authorized",
        "post_signal_predictor_authorized",
        "rule_aggregation_authorized",
        "portfolio_replay_authorized",
        "candidate_reselection_authorized",
    )
    permissions = load_json(PHASE2A_SPEC, "Phase-2A freeze").get(
        "required_authorization", {}
    ).get("permissions", {})
    for key in required_true:
        if authorization.get(key) is not True or permissions.get(key) is not True:
            raise ResearchError(f"Phase-2A permission not jointly true: {key}")
    for key in required_false:
        if authorization.get(key) is not False or permissions.get(key) is not False:
            raise ResearchError(f"Phase-2A forbidden permission not jointly false: {key}")

    artifacts = bound_artifact_map(authorization)
    expected_roles = {
        "phase2a_freeze",
        "phase2a_runner",
        *(role for role, _ in REPO_BOUND_ROLES),
        *(role for role, _ in PHASE1_EXTERNAL_ROLES),
        *(role for role, _ in STAGE_B_ROLES),
    }
    if set(artifacts) != expected_roles:
        raise ResearchError("CY-056 exact bound-artifact role set drift")
    assert_literal_binding(
        artifacts, "phase2a_freeze", PHASE2A_SPEC.resolve(), actual["phase2a_spec"]
    )
    assert_literal_binding(
        artifacts, "phase2a_runner", Path(__file__).resolve(), actual["phase2a_runner"]
    )
    for role, path in REPO_BOUND_ROLES:
        assert_literal_binding(artifacts, role, path.resolve(), REPO_HASHES[path])
    # Critical boundary: these comparisons use literal strings only.  No
    # resolve(), exists(), stat(), sha256(), parquet metadata call, or open().
    for role, path in PHASE1_EXTERNAL_ROLES:
        assert_literal_binding(artifacts, role, path, PHASE1_EXTERNAL_HASHES[path])
    for role, path in STAGE_B_ROLES:
        assert_literal_binding(artifacts, role, path, STAGE_B_HASHES[path])

    manifest = load_json(PHASE2A_MANIFEST, "CY-056 Phase-2A manifest")
    boundary = manifest.get("authorization_boundary", {})
    manifest_protocol = manifest.get("protocol", {})
    manifest_scope = manifest.get("frozen_scope", {})
    if (
        manifest.get("asset_id") != ASSET_ID
        or manifest.get("status") != MANIFEST_STATUS
        or manifest.get("pipeline_version") != PIPELINE_VERSION
        or boundary.get("authorization_id") != AUTHORIZATION_ID
        or boundary.get("purpose") != AUTHORIZATION_PURPOSE
        or boundary.get("authorized_arm") != AUTHORIZED_ARM
        or boundary.get("dependency_asset_id") != DEPENDENCY_ASSET_ID
        or any(boundary.get(key) is not True for key in required_true)
        or any(boundary.get(key) is not False for key in required_false)
        or manifest_protocol.get("phase2a_spec_path") != str(PHASE2A_SPEC.resolve())
        or manifest_protocol.get("phase2a_spec_sha256") != actual["phase2a_spec"]
        or manifest_protocol.get("phase2a_runner_path") != str(Path(__file__).resolve())
        or manifest_protocol.get("phase2a_runner_sha256") != actual["phase2a_runner"]
        or manifest_scope.get("phase2a_events") != EXPECTED_PHASE2A_EVENTS
        or manifest_scope.get("annual_signal_counts")
        != {str(year): count for year, count in EXPECTED_PHASE2A_ANNUAL.items()}
        or manifest_scope.get("signal_start") != str(DISCOVERY_SIGNAL_START.date())
        or manifest_scope.get("signal_end") != str(DISCOVERY_SIGNAL_END.date())
        or manifest_scope.get("sealed_signal_year") != 2020
        or manifest_scope.get("post_window") != [1, WINDOW]
    ):
        raise ResearchError("CY-056 Phase-2A manifest semantics drift")
    manifest_artifacts = bound_artifact_map(manifest)
    if set(manifest_artifacts) != expected_roles:
        raise ResearchError("CY-056 manifest bound-artifact role set drift")
    for role, item in artifacts.items():
        if manifest_artifacts.get(role) != item:
            raise ResearchError(f"CY-056 manifest/registry artifact drift: {role}")
    return actual, authorization


def verify_external_phase1() -> pd.DataFrame:
    """First external access; contains no identity crosswalk or outcome."""
    for path, expected in PHASE1_EXTERNAL_HASHES.items():
        if not path.is_file() or sha256(path) != expected:
            raise ResearchError(f"frozen Phase-1 artifact drift: {path}")
    chart_manifest = load_json(PHASE1_CHART_MANIFEST, "Phase-1 chart manifest")
    ledger_manifest = load_json(PHASE1_LEDGER_MANIFEST, "Phase-1 ledger manifest")
    if (
        chart_manifest.get("experiment") != EXPERIMENT
        or chart_manifest.get("stage") != "PHASE1_ANONYMOUS_CAUSAL_VISUAL_REVIEW_CORPUS"
        or int(chart_manifest.get("events", -1)) != EXPECTED_ALL_EVENTS
        or int(chart_manifest.get("individual_anonymous_charts", -1))
        != EXPECTED_ALL_EVENTS
        or chart_manifest.get("anonymous_identity_coverage_exactly_once") is not True
        or chart_manifest.get("post_signal_row_read") is not False
        or chart_manifest.get("outcome_artifact_opened_or_parsed") is not False
        or ledger_manifest.get("experiment") != EXPERIMENT
        or ledger_manifest.get("stage")
        != "PHASE1_ANONYMOUS_SIGNAL_TIME_ANNOTATIONS_FROZEN"
        or ledger_manifest.get("coverage_exactly_once") is not True
        or int(ledger_manifest.get("events", -1)) != EXPECTED_ALL_EVENTS
        or ledger_manifest.get("governance", {}).get("outcomes_read") is not False
        or ledger_manifest.get("governance", {}).get("post_signal_rows_read")
        is not False
    ):
        raise ResearchError("frozen Phase-1 manifest semantics drift")
    # Deliberately exclude all four manual labels, evidence, and reviewer.  In
    # particular the sealed 2020 Phase-1 labels never enter Phase-2A memory.
    ledger = pd.read_csv(PHASE1_LEDGER, usecols=list(PHASE1_LEDGER_IDENTITY_COLUMNS))
    if (
        tuple(ledger.columns) != PHASE1_LEDGER_IDENTITY_COLUMNS
        or len(ledger) != EXPECTED_ALL_EVENTS
        or ledger.chart_number.tolist() != list(range(1, EXPECTED_ALL_EVENTS + 1))
        or ledger.chart_number.duplicated().any()
        or ledger.blind_chart_id.duplicated().any()
        or ledger.blind_chart_path.duplicated().any()
    ):
        raise ResearchError("Phase-1 anonymous ledger identity coverage drift")
    return ledger


def verify_hash_after_authorization(path: Path, expected: str, label: str) -> str:
    if not path.is_file():
        raise ResearchError(f"missing authorized {label}: {path}")
    actual = sha256(path)
    if actual != expected:
        raise ResearchError(f"authorized {label} hash drift: {actual} != {expected}")
    return actual


def load_prepared_and_rebuild_blind_order(ledger: pd.DataFrame) -> pd.DataFrame:
    """Read pre-signal identity only and reconstruct the immutable blind order."""
    prepared = pd.read_parquet(PREPARED, columns=list(PREPARED_COLUMNS))
    require_columns(prepared, PREPARED_COLUMNS, "prepared candidates")
    prepared["event_id"] = prepared.event_id.astype(str)
    prepared["signal_date"] = pd.to_datetime(prepared.signal_date)
    for column in (
        "known_at",
        "decision_at",
        "signal_row_available_at",
        "signal_row_decision_at",
    ):
        prepared[column] = pd.to_datetime(prepared[column])
    annual = prepared.signal_date.dt.year.value_counts().sort_index().to_dict()
    if (
        len(prepared) != EXPECTED_ALL_EVENTS
        or prepared.event_id.duplicated().any()
        or annual != {2018: 395, 2019: 520, 2020: 568}
        or prepared.signal_date.min() != pd.Timestamp("2018-03-27")
        or prepared.signal_date.max() != pd.Timestamp("2020-12-01")
        or prepared[
            [
                "known_at",
                "decision_at",
                "signal_row_available_at",
                "signal_row_decision_at",
            ]
        ].isna().any().any()
        or prepared.known_at.gt(prepared.decision_at).any()
        or prepared.signal_row_available_at.gt(prepared.signal_row_decision_at).any()
        or prepared.decision_at.ne(prepared.signal_row_decision_at).any()
    ):
        raise ResearchError("prepared-candidate PIT/identity scope drift")
    prepared["_blind_sort_digest"] = prepared.event_id.map(
        lambda value: hashlib.sha256(f"{OPAQUE_ORDER_SALT}|{value}".encode()).hexdigest()
    )
    prepared["blind_chart_id"] = "B-" + prepared._blind_sort_digest.str.slice(0, 20)
    prepared = prepared.sort_values(
        ["_blind_sort_digest", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    prepared.insert(
        0, "chart_number", np.arange(1, EXPECTED_ALL_EVENTS + 1, dtype=np.int64)
    )
    pd.testing.assert_frame_equal(
        prepared[["chart_number", "blind_chart_id"]].reset_index(drop=True),
        ledger[["chart_number", "blind_chart_id"]].reset_index(drop=True),
        check_dtype=False,
    )
    discovery = prepared.loc[
        prepared.signal_date.dt.year.isin(EXPECTED_PHASE2A_ANNUAL)
    ].copy()
    discovery_annual = discovery.signal_date.dt.year.value_counts().sort_index().to_dict()
    if len(discovery) != EXPECTED_PHASE2A_EVENTS or discovery_annual != EXPECTED_PHASE2A_ANNUAL:
        raise ResearchError("2018-2019 Phase-2A cohort identity drift")
    # Phase-1 chart path/hash is joined only after 2020 rows have been removed.
    discovery = discovery.merge(
        ledger,
        on=["chart_number", "blind_chart_id"],
        how="left",
        validate="one_to_one",
    )
    if discovery[list(PHASE1_LEDGER_IDENTITY_COLUMNS[2:])].isna().any().any():
        raise ResearchError("Phase-1 chart identity missing for discovery cohort")
    return discovery


def quote_sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


def load_filtered_outcomes(discovery: pd.DataFrame) -> pd.DataFrame:
    """Parse only 2018-2019 outcome rows; 2020 remains sealed."""
    keys = discovery[["event_id"]].copy()
    columns = ",".join(f'o."{column}"' for column in OUTCOME_COLUMNS)
    connection = duckdb.connect()
    connection.register("phase2a_event_keys", keys)
    try:
        outcomes = connection.execute(
            f"""
            SELECT {columns}
            FROM read_parquet('{quote_sql_path(OUTCOMES)}') o
            INNER JOIN phase2a_event_keys k USING(event_id)
            WHERE o.signal_date >= DATE '2018-01-01'
              AND o.signal_date < DATE '2020-01-01'
              AND (o.entry_date IS NULL OR o.entry_date <= DATE '2020-12-31')
              AND (o.exit_date IS NULL OR o.exit_date <= DATE '2020-12-31')
            ORDER BY o.event_id
            """
        ).fetch_df()
    finally:
        connection.unregister("phase2a_event_keys")
        connection.close()
    require_columns(outcomes, OUTCOME_COLUMNS, "filtered outcomes")
    outcomes["event_id"] = outcomes.event_id.astype(str)
    for column in ("signal_date", "entry_date", "exit_date"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    annual = outcomes.signal_date.dt.year.value_counts().sort_index().to_dict()
    if (
        len(outcomes) != EXPECTED_PHASE2A_EVENTS
        or outcomes.event_id.duplicated().any()
        or annual != EXPECTED_PHASE2A_ANNUAL
        or outcomes.signal_date.ge(SEALED_SIGNAL_START).any()
        or set(outcomes.event_id) != set(discovery.event_id)
        or not outcomes.target_return.astype(float).eq(TARGET_RETURN).all()
        or not outcomes.horizon_sessions.eq(HORIZON_SESSIONS).all()
        or not outcomes.round_trip_cost.astype(float).eq(ROUND_TRIP_COST).all()
    ):
        raise ResearchError("filtered 2018-2019 outcome contract drift")
    identity = discovery.merge(
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
    completed_net = pd.to_numeric(outcomes.loc[completed, "net_return"], errors="coerce")
    entered = outcomes.entry_cal_idx.notna()
    if (
        outcomes.status.isna().any()
        or outcomes.status.astype(str).str.len().eq(0).any()
        or not set(outcomes.status.astype(str)).issubset(ALLOWED_STATUSES)
        or not np.isfinite(completed_net).all()
        or outcomes.loc[~completed, "net_return"].notna().any()
        or outcomes.loc[completed, ["entry_cal_idx", "entry_price"]].isna().any().any()
        or outcomes.loc[completed, ["exit_cal_idx", "exit_price"]].isna().any().any()
        or outcomes.loc[entered, "entry_cal_idx"].le(
            outcomes.loc[entered, "signal_cal_idx"]
        ).any()
        or outcomes.loc[entered, "entry_cal_idx"].gt(
            outcomes.loc[entered, "signal_cal_idx"] + 3
        ).any()
        or outcomes.loc[completed, "exit_cal_idx"].le(
            outcomes.loc[completed, "entry_cal_idx"]
        ).any()
        or outcomes.loc[completed, "exit_cal_idx"].gt(
            outcomes.loc[completed, "signal_cal_idx"] + WINDOW
        ).any()
    ):
        raise ResearchError("2018-2019 lifecycle chronology drift")
    for column in ("signal_date", "entry_date", "exit_date"):
        if outcomes[column].dropna().gt(MAX_PARSED_PATH_DATE).any():
            raise ResearchError(f"forbidden date parsed in outcome column {column}")
    return outcomes


def load_filtered_future_paths(discovery: pd.DataFrame) -> pd.DataFrame:
    """Parse only paths keyed by the already-filtered 2018-2019 event set."""
    keys = discovery[["event_id"]].copy()
    columns = ",".join(f'f."{column}"' for column in PATH_COLUMNS)
    connection = duckdb.connect()
    connection.register("phase2a_event_keys", keys)
    try:
        paths = connection.execute(
            f"""
            SELECT {columns}
            FROM read_parquet('{quote_sql_path(FUTURE_PATHS)}') f
            INNER JOIN phase2a_event_keys k USING(event_id)
            WHERE f.event_signal_date >= DATE '2018-01-01'
              AND f.event_signal_date < DATE '2020-01-01'
              AND f.trade_date <= DATE '2020-12-31'
            ORDER BY f.event_id,f.cal_idx
            """
        ).fetch_df()
    finally:
        connection.unregister("phase2a_event_keys")
        connection.close()
    require_columns(paths, PATH_COLUMNS, "filtered future paths")
    paths["event_id"] = paths.event_id.astype(str)
    for column in ("event_signal_date", "trade_date", "available_at", "decision_at"):
        paths[column] = pd.to_datetime(paths[column])
    if (
        paths.empty
        or paths.duplicated(["event_id", "cal_idx"]).any()
        or set(paths.event_id) != set(discovery.event_id)
        or paths.event_signal_date.ge(SEALED_SIGNAL_START).any()
        or paths.trade_date.gt(MAX_PARSED_PATH_DATE).any()
        or paths.cal_idx.le(paths.event_signal_cal_idx).any()
        or paths.cal_idx.gt(paths.event_signal_cal_idx + WINDOW).any()
        or paths.trade_date.le(paths.event_signal_date).any()
        or paths.available_at.gt(paths.decision_at).any()
    ):
        raise ResearchError("filtered 2018-2019 future-path boundary drift")
    relative = paths.cal_idx.astype(int) - paths.event_signal_cal_idx.astype(int)
    coverage = pd.DataFrame(
        {"event_id": paths.event_id, "relative": relative}
    ).groupby("event_id", sort=False).relative.agg(["count", "nunique", "min", "max"])
    if (
        len(coverage) != EXPECTED_PHASE2A_EVENTS
        or not coverage["count"].eq(WINDOW).all()
        or not coverage["nunique"].eq(WINDOW).all()
        or not coverage["min"].eq(1).all()
        or not coverage["max"].eq(WINDOW).all()
    ):
        raise ResearchError("future-path raw plus-1-through-plus-126 coverage drift")
    identity = discovery[["event_id", "symbol", "signal_date", "signal_cal_idx"]]
    observed = paths[
        ["event_id", "symbol", "event_signal_date", "event_signal_cal_idx"]
    ].drop_duplicates()
    check = identity.merge(observed, on="event_id", validate="one_to_one")
    if (
        len(check) != paths.event_id.nunique()
        or not check.symbol_x.eq(check.symbol_y).all()
        or not check.signal_date.eq(check.event_signal_date).all()
        or not check.signal_cal_idx.eq(check.event_signal_cal_idx).all()
    ):
        raise ResearchError("filtered future-path identity drift")
    return paths


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


def build_anonymous_event_ledger(
    discovery: pd.DataFrame, outcomes: pd.DataFrame
) -> pd.DataFrame:
    outcome_by_id = outcomes.set_index("event_id", verify_integrity=True)
    rows: list[dict[str, Any]] = []
    for event in discovery.itertuples(index=False):
        outcome = outcome_by_id.loc[str(event.event_id)]
        rows.append(
            {
                "chart_number": int(event.chart_number),
                "blind_chart_id": str(event.blind_chart_id),
                "blind_chart_path": str(event.blind_chart_path),
                "blind_chart_sha256": str(event.blind_chart_sha256),
                "event_id": str(event.event_id),
                "symbol": str(event.symbol),
                "signal_date": pd.Timestamp(event.signal_date),
                "signal_cal_idx": int(event.signal_cal_idx),
                "signal_invalid_step_cum": int(event.invalid_step_cum),
                "outcome_bucket": outcome_bucket(
                    str(outcome.status), outcome.net_return
                ),
                "status": str(outcome.status),
                "entry_cal_idx": outcome.entry_cal_idx,
                "entry_price": outcome.entry_price,
                "target_price": outcome.target_price,
                "exit_cal_idx": outcome.exit_cal_idx,
                "exit_price": outcome.exit_price,
            }
        )
    ledger = pd.DataFrame(rows).sort_values("chart_number", kind="mergesort")
    if (
        len(ledger) != EXPECTED_PHASE2A_EVENTS
        or ledger.chart_number.duplicated().any()
        or ledger.blind_chart_id.duplicated().any()
        or ledger.event_id.duplicated().any()
        or set(ledger.outcome_bucket) - set(OUTCOME_BUCKETS)
    ):
        raise ResearchError("anonymous Phase-2A event ledger drift")
    return ledger


def valid_post_bars(frame: pd.DataFrame, signal_invalid_step_cum: int) -> pd.DataFrame:
    raw_columns = ["open", "high", "low", "close"]
    raw = frame[raw_columns].apply(pd.to_numeric, errors="coerce")
    coord_close = pd.to_numeric(frame.coord_close, errors="coerce")
    raw_finite = np.isfinite(raw).all(axis=1) & raw.gt(0).all(axis=1)
    raw_geometry = raw.high.ge(raw[["open", "close"]].max(axis=1)) & raw.low.le(
        raw[["open", "close"]].min(axis=1)
    )
    close_valid = np.isfinite(coord_close) & coord_close.gt(0)
    mask = (
        raw_finite
        & raw_geometry
        & close_valid
        & frame.hard_valid.eq(True)
        & pd.to_numeric(frame.trade_status, errors="coerce").eq(1.0)
        & frame.current_day_data_tradable.eq(True)
        & frame.current_valid.eq(True)
        & frame.market_rule_valid.eq(True)
        & frame.corporate_action_valid.eq(True)
        & frame.corporate_action_blocking.eq(False)
        & frame.invalid_step_cum.eq(signal_invalid_step_cum)
        & frame.available_at.le(frame.decision_at)
    )
    result = frame.loc[mask].copy()
    # Ratio-first coordinate OHLC preserves exact raw equality cases and raw
    # ordering without clipping, normalization, or relaxed tolerances.
    result["render_open"] = result.coord_close * (result.open / result.close)
    result["render_high"] = result.coord_close * (result.high / result.close)
    result["render_low"] = result.coord_close * (result.low / result.close)
    result["render_close"] = result.coord_close
    result["relative"] = result.cal_idx.astype(int) - result.event_signal_cal_idx.astype(int)
    return result.loc[result.relative.between(1, WINDOW)].copy()


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
    if math.isclose(low, high):
        pad = max(abs(low) * 0.02, 1e-6)
    else:
        pad = (high - low) * 0.06
    return low - pad, high + pad


def y_coordinate(value: float, bounds: tuple[float, float]) -> int:
    low, high = bounds
    return round(380 - (value - low) / (high - low) * 300)


def x_coordinate(relative: int) -> int:
    return round(44 + (relative - 1) / (WINDOW - 1) * 648)


def render_post_panel(event: dict[str, Any], paths: pd.DataFrame) -> Image.Image:
    image = Image.new("RGB", (720, 440), "#ffffff")
    draw = ImageDraw.Draw(image)
    title_font, small = font(14), font(11)
    draw.text((8, 8), "POST-SIGNAL ATTRIBUTION +1..+126", fill="#111827", font=title_font)
    draw.text((8, 27), str(event["outcome_bucket"]), fill="#9a3412", font=small)
    draw.rectangle((42, 72, 694, 382), outline="#d1d5db", width=1)
    for relative in (1, 20, 63, 126):
        x = x_coordinate(relative)
        draw.line((x, 72, x, 382), fill="#e5e7eb", width=1)
        draw.text((x - 8, 389), f"+{relative}", fill="#6b7280", font=small)

    valid = valid_post_bars(paths, int(event["signal_invalid_step_cum"]))
    if valid.empty:
        draw.text((240, 220), "NO VALID POST BARS", fill="#6b7280", font=title_font)
        return image
    bounds = scale(
        valid[["render_open", "render_high", "render_low", "render_close"]]
        .to_numpy(dtype=float)
        .ravel()
        .tolist()
    )
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

    marker_data = (
        (event.get("entry_cal_idx"), event.get("entry_price"), "ENTRY", "#2563eb"),
        (event.get("exit_cal_idx"), event.get("exit_price"), "EXIT", "#7c3aed"),
    )
    for cal_idx, price, label, color in marker_data:
        if pd.isna(cal_idx) or pd.isna(price) or not np.isfinite(float(price)):
            continue
        relative = int(cal_idx) - int(event["signal_cal_idx"])
        if not 1 <= relative <= WINDOW:
            continue
        x = x_coordinate(relative)
        y = y_coordinate(float(price), bounds)
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=color)
        draw.text((x + 5, max(72, y - 8)), label, fill=color, font=small)
    target_price = event.get("target_price")
    if not pd.isna(target_price) and np.isfinite(float(target_price)):
        target_y = y_coordinate(float(target_price), bounds)
        if 72 <= target_y <= 382:
            draw.line((42, target_y, 694, target_y), fill="#d97706", width=1)
            draw.text((620, max(72, target_y - 13)), "TARGET", fill="#d97706", font=small)
    draw.text(
        (8, 420),
        "Attribution only; +1..+20 primary, +21..+126 context; no numeric return",
        fill="#6b7280",
        font=small,
    )
    return image


def render_one(payload: tuple[dict[str, Any], list[dict[str, Any]], str]) -> dict[str, Any]:
    event, path_records, output_text = payload
    pre_path = PHASE1_CHART_ROOT / str(event["blind_chart_path"])
    if not pre_path.is_file() or sha256(pre_path) != str(event["blind_chart_sha256"]):
        raise ResearchError(f"Phase-1 chart hash drift: {event['blind_chart_id']}")
    with Image.open(pre_path) as source:
        pre = source.convert("RGB")
    if pre.size != (720, 440):
        raise ResearchError(f"unexpected Phase-1 chart dimensions: {pre.size}")
    paths = pd.DataFrame.from_records(path_records, columns=list(PATH_COLUMNS))
    post = render_post_panel(event, paths)
    combined = Image.new("RGB", (1440, 440), "white")
    combined.paste(pre, (0, 0))
    combined.paste(post, (720, 0))
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
        for page_index, start in enumerate(range(0, len(subset), 25), start=1):
            part = subset.iloc[start : start + 25]
            sheet = Image.new("RGB", (1800, 1140), "#f8fafc")
            draw = ImageDraw.Draw(sheet)
            draw.text(
                (12, 8),
                f"V34R1 PHASE2A | {bucket} | PAGE {page_index:04d}",
                fill="#111827",
                font=font(18),
            )
            for slot, row in enumerate(part.itertuples(index=False), start=1):
                with Image.open(row.full_chart_path) as source:
                    thumb = source.convert("RGB").resize((348, 202), Image.Resampling.LANCZOS)
                col = (slot - 1) % 5
                line = (slot - 1) // 5
                x, y = 6 + col * 358, 40 + line * 218
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
                        "sheet_number": page_index,
                        "slot": slot,
                        "chart_number": int(row.chart_number),
                        "blind_chart_id": str(row.blind_chart_id),
                    }
                )
            sheet_path = bucket_dir / f"sheet_{page_index:04d}.jpg"
            sheet.save(sheet_path, format="JPEG", quality=92, subsampling=0)
            sheets.append(
                {
                    "outcome_bucket": bucket,
                    "sheet_number": page_index,
                    "sheet_path": str(sheet_path),
                    "sheet_sha256": sha256(sheet_path),
                    "charts": len(part),
                }
            )
    return pd.DataFrame(placements), pd.DataFrame(sheets)


def relative_output_path(staging: Path, path_text: str) -> str:
    path = Path(path_text)
    return str(path.relative_to(staging))


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def reverify_before_publish(
    public_hashes: dict[str, str],
    outcome_hashes: dict[str, str],
) -> None:
    current, _ = verify_public_authorization()
    if current != public_hashes:
        raise ResearchError("public contract changed during rendering")
    for path in PHASE1_EXTERNAL_HASHES:
        if sha256(path) != PHASE1_EXTERNAL_HASHES[path]:
            raise ResearchError(f"Phase-1 input changed during rendering: {path}")
    # The Stage-B result is deliberately absent: Phase-2A never touches it.
    for role, path in (
        ("stage_b_prepared_candidates", PREPARED),
        ("stage_b_future_paths", FUTURE_PATHS),
        ("stage_b_outcomes", OUTCOMES),
    ):
        if sha256(path) != outcome_hashes[role]:
            raise ResearchError(f"authorized Stage-B artifact changed: {role}")


def atomic_publish_no_replace(source: Path, destination: Path) -> None:
    """Atomically publish a directory while refusing every existing target."""
    libc = ctypes.CDLL(None, use_errno=True)
    rename_exclusive = getattr(libc, "renamex_np", None)
    if rename_exclusive is None:
        raise ResearchError("atomic exclusive directory rename is unavailable")
    rename_exclusive.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    rename_exclusive.restype = ctypes.c_int
    rename_excl = 0x00000004  # Darwin RENAME_EXCL.
    if rename_exclusive(os.fsencode(source), os.fsencode(destination), rename_excl):
        error = ctypes.get_errno()
        raise ResearchError(
            f"atomic no-overwrite publication failed: {os.strerror(error)}"
        )


def run(workers: int) -> dict[str, Any]:
    public_hashes, _authorization = verify_public_authorization()
    if OUTPUT.exists() or OUTPUT.is_symlink():
        raise ResearchError(f"refusing to overwrite Phase-2A output: {OUTPUT}")
    ledger = verify_external_phase1()

    # First Stage-B touch occurs here, strictly after the public authorization.
    stage_b_actual = {
        "stage_b_prepared_candidates": verify_hash_after_authorization(
            PREPARED, STAGE_B_HASHES[PREPARED], "prepared candidates"
        ),
        "stage_b_future_paths": verify_hash_after_authorization(
            FUTURE_PATHS, STAGE_B_HASHES[FUTURE_PATHS], "future paths"
        ),
        "stage_b_outcomes": verify_hash_after_authorization(
            OUTCOMES, STAGE_B_HASHES[OUTCOMES], "outcomes"
        ),
    }
    # STAGE_B_RESULT is intentionally never statted, hashed, opened, or parsed.
    discovery = load_prepared_and_rebuild_blind_order(ledger)
    outcomes = load_filtered_outcomes(discovery)
    paths = load_filtered_future_paths(discovery)
    events = build_anonymous_event_ledger(discovery, outcomes)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{OUTPUT.name}.staging-", dir=OUTPUT.parent))
    try:
        chart_dir = staging / "individual_attribution_charts"
        chart_dir.mkdir(parents=True, exist_ok=False)
        path_groups = {
            str(event_id): group.copy()
            for event_id, group in paths.groupby("event_id", sort=False)
        }
        tasks: list[tuple[dict[str, Any], list[dict[str, Any]], str]] = []
        for event in events.to_dict("records"):
            chart_path = chart_dir / f"{event['blind_chart_id']}.png"
            records = path_groups.get(str(event["event_id"]), pd.DataFrame()).to_dict(
                "records"
            )
            tasks.append((event, records, str(chart_path)))
        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            chart_index = pd.DataFrame(executor.map(render_one, tasks))
        chart_index = chart_index.sort_values("chart_number", kind="mergesort")
        if (
            len(chart_index) != EXPECTED_PHASE2A_EVENTS
            or chart_index.chart_number.duplicated().any()
            or chart_index.blind_chart_id.duplicated().any()
        ):
            raise ResearchError("rendered chart coverage drift")
        placements, sheet_index = build_contact_sheets(chart_index, staging)
        if (
            len(placements) != EXPECTED_PHASE2A_EVENTS
            or placements.chart_number.duplicated().any()
            or set(placements.chart_number) != set(chart_index.chart_number)
        ):
            raise ResearchError("contact-sheet coverage drift")

        for frame, path_columns in (
            (
                chart_index,
                [
                    "chart_number",
                    "blind_chart_id",
                    "full_chart_path",
                    "full_chart_sha256",
                    "outcome_bucket",
                ],
            ),
            (
                placements,
                [
                    "outcome_bucket",
                    "sheet_number",
                    "slot",
                    "chart_number",
                    "blind_chart_id",
                ],
            ),
            (
                sheet_index,
                [
                    "outcome_bucket",
                    "sheet_number",
                    "sheet_path",
                    "sheet_sha256",
                    "charts",
                ],
            ),
        ):
            for column in ("full_chart_path", "sheet_path"):
                if column in frame:
                    frame[column] = frame[column].map(
                        lambda value: relative_output_path(staging, str(value))
                    )
            output_name = {
                "full_chart_path": "phase2a_chart_index.csv",
                "slot": "outcome_sheet_placements.csv",
                "sheet_path": "outcome_sheet_index.csv",
            }[next(column for column in path_columns if column in {
                "full_chart_path", "slot", "sheet_path"
            })]
            frame[path_columns].to_csv(staging / output_name, index=False)

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
        write_json(staging / "phase2a_review_template.json", review_template)
        bucket_counts = {
            bucket: int(chart_index.outcome_bucket.eq(bucket).sum())
            for bucket in OUTCOME_BUCKETS
        }
        output_files = {
            name: sha256(staging / name)
            for name in (
                "phase2a_chart_index.csv",
                "outcome_sheet_placements.csv",
                "outcome_sheet_index.csv",
                "phase2a_review_template.json",
            )
        }
        manifest = {
            "experiment": EXPERIMENT,
            "stage": STAGE,
            "status": "PUBLISHED_ANONYMOUS_2018_2019_ATTRIBUTION_CORPUS",
            "asset_id": ASSET_ID,
            "authorization_id": AUTHORIZATION_ID,
            "phase2a_spec_sha256": public_hashes["phase2a_spec"],
            "phase2a_runner_sha256": public_hashes["phase2a_runner"],
            "phase1_annotation_ledger_sha256": PHASE1_EXTERNAL_HASHES[PHASE1_LEDGER],
            "phase1_annotation_manifest_sha256": PHASE1_EXTERNAL_HASHES[
                PHASE1_LEDGER_MANIFEST
            ],
            "source_hashes": {
                **public_hashes,
                **stage_b_actual,
                "stage_b_result_declared_sha256_only": STAGE_B_HASHES[STAGE_B_RESULT],
            },
            "output_hashes": output_files,
            "event_rows": EXPECTED_PHASE2A_EVENTS,
            "annual_signal_counts": {
                str(year): count for year, count in EXPECTED_PHASE2A_ANNUAL.items()
            },
            "outcome_bucket_counts": bucket_counts,
            "anonymous_event_coverage_exactly_once": True,
            "identity_crosswalk_persisted": False,
            "numeric_returns_persisted": False,
            "phase1_labels_parsed": False,
            "phase1_labels_modified": False,
            "signal_candle_used_for_rule": False,
            "post_signal_used_as_predictor": False,
            "rule_aggregation_performed": False,
            "portfolio_replay_performed": False,
            "stage_b_result_stat_hash_open_parse": False,
            "2020_signal_outcome_rows_parsed": False,
            "2020_signal_path_rows_parsed": False,
            "2020_phase1_labels_parsed": False,
            "2021_plus_rows_parsed": False,
            "note_on_2020_calendar_rows": (
                "Calendar-2020 rows may appear only as plus-126 completion context "
                "for 2019 signals; no 2020 signal cohort is selected."
            ),
            "next_action": (
                "REVIEW_ALL_915_CHARTS_THEN_FREEZE_AT_MOST_FIVE_OBJECTIVE_"
                "SIGNAL_TIME_NUMERIC_CLAUSES_BEFORE_ANY_2020_HOLDOUT_READ"
            ),
        }
        write_json(staging / "manifest.json", manifest)
        reverify_before_publish(public_hashes, stage_b_actual)
        atomic_publish_no_replace(staging, OUTPUT)
        return manifest
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--verify-static-contract",
        action="store_true",
        help="verify repository-only package; never touch an external artifact",
    )
    modes.add_argument(
        "--verify-public-authorization",
        action="store_true",
        help=(
            "verify future CY-056 literal bindings; never stat/hash/open Stage-B "
            "prepared/result/future/outcome artifacts"
        ),
    )
    modes.add_argument(
        "--run",
        action="store_true",
        help="render after exact CY-056 authorization; never accesses 2020 signal outcomes",
    )
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.workers < 1 or args.workers > 16:
        raise ResearchError("workers must be between 1 and 16")
    if args.verify_static_contract:
        print(json.dumps(verify_static_contract(), indent=2, sort_keys=True))
        return
    if args.verify_public_authorization:
        actual, _ = verify_public_authorization()
        print(json.dumps(actual, indent=2, sort_keys=True))
        return
    print(json.dumps(run(args.workers), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
