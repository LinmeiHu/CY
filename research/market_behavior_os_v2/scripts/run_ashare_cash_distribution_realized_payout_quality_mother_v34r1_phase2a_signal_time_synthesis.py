#!/usr/bin/env python3
"""Bounded anonymous categorical synthesis for V34R1 Phase-2A.

``--verify-static-contract`` reads repository code/spec only.
``--verify-public-authorization`` additionally reads repository registry and the
future CY-060 manifest, but never touches an external research artifact.
``--run`` may read exactly four immutable anonymous inputs, and only after the
joint CY-060 gate passes.  It never reads a Stage-B artifact, an identity/date
field, or a numeric return and cannot construct or rank a trading rule.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import hashlib
import itertools
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

EXPERIMENT = "ASHARE-CASH-DISTRIBUTION-REALIZED-PAYOUT-QUALITY-MOTHER-V34R1"
SPEC_ID = "ASHARE-V34R1-PHASE2A-SIGNAL-TIME-ANONYMOUS-SYNTHESIS-FREEZE-V1"
STAGE = "PHASE2A_SIGNAL_TIME_ANONYMOUS_DESCRIPTIVE_SYNTHESIS"
STATUS = "STATIC_FROZEN_AWAITING_CY060_MANIFEST_AND_REGISTRY_AUTHORIZATION"

REPO = Path(__file__).resolve().parents[3]
SPEC_REL = (
    "research/market_behavior_os_v2/experiments/"
    "ASHARE-CASH-DISTRIBUTION-REALIZED-PAYOUT-QUALITY-MOTHER-V34R1_"
    "phase2a_signal_time_synthesis_freeze.json"
)
RUNNER_REL = (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_cash_distribution_realized_payout_quality_mother_v34r1_"
    "phase2a_signal_time_synthesis.py"
)
MANIFEST_REL = (
    "research/market_behavior_os_v2/experiments/"
    "ASHARE-V34R1-CY060_SIGNAL_TIME_SYNTHESIS_ASSET_MANIFEST.json"
)
SPEC = REPO / SPEC_REL
REGISTRY = REPO / "configs/data_asset_registry.json"
CY060_MANIFEST = REPO / MANIFEST_REL

SPEC_SHA256 = "ec0881ac1a648d456883d82d729ffaf4ef6047d93f3e2acd3606cf46dab61121"
ASSET_ID = "CY-060"
AUTHORIZATION_ID = (
    "CYQ-AUTH-ASHARE-CASH-DISTRIBUTION-PAYOUT-QUALITY-"
    "V34R1-PHASE2A-SYNTHESIS-CY060-V1"
)
AUTHORIZED_ARM = "V34R1_PHASE2A_FROZEN_ANONYMOUS_SYNTHESIS_ONLY"
AUTHORIZATION_PURPOSE = "ASHARE_FROZEN_DEVELOPMENT_OUTCOME_ATTACHMENT"
PIPELINE_VERSION = "v34r1-phase2a-signal-time-anonymous-synthesis-v1"
ASSET_KIND = "bounded_anonymous_categorical_signal_time_synthesis_input"
MANIFEST_STATUS = "FROZEN_ANONYMOUS_CATEGORICAL_SYNTHESIS_BOUNDED_INPUT"

ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_cash_distribution_realized_payout_quality_mother_v34r1"
)
PHASE1_ROOT = ROOT / "stage_d_phase1_anonymous_review"
PHASE2A_ROOT = ROOT / "stage_f_phase2a_anonymous_review"
PHASE1_LEDGER = PHASE1_ROOT / "phase1_annotation_ledger.csv"
PHASE1_MANIFEST = PHASE1_ROOT / "manifest.json"
PHASE2A_LEDGER = PHASE2A_ROOT / "phase2a_annotation_ledger.json"
PHASE2A_MANIFEST = PHASE2A_ROOT / "manifest.json"
OUTPUT = ROOT / "stage_g_phase2a_signal_time_outcome_synthesis"

EXTERNAL_HASHES: dict[Path, str] = {
    PHASE1_LEDGER: "a70aac69ca58f9302f7af59a301800f6398b806705d461b7b18a91d92a56f474",
    PHASE1_MANIFEST: "540c77afb93d61d3b729491936b720f76a77eeb6302d93e6989d2574421e041d",
    PHASE2A_LEDGER: "777e7a86fb3adfb8293248d503cee91f4ce40131fdd5bd2888ab11ac6142c6c4",
    PHASE2A_MANIFEST: "51095ce31fe1b96327cda489cfe601940cd54611596a6f5affa34f76e2c08460",
}
EXTERNAL_ROLES = (
    ("phase1_annotation_ledger", PHASE1_LEDGER),
    ("phase1_annotation_manifest", PHASE1_MANIFEST),
    ("phase2a_annotation_ledger", PHASE2A_LEDGER),
    ("phase2a_annotation_manifest", PHASE2A_MANIFEST),
)

EXPECTED_PHASE1_EVENTS = 1_483
EXPECTED_PHASE2A_EVENTS = 915
EXPECTED_PHASE1_UNMATCHED = 568
MINIMUM_SUPPORT = 25
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
OPAQUE_ID_PATTERN = re.compile(r"B-[0-9a-f]{20}")
POSITIVE_INTEGER_PATTERN = re.compile(r"[1-9][0-9]*")

PHASE1_LEDGER_FIELDS = (
    "chart_number",
    "blind_chart_id",
    "blind_chart_path",
    "blind_chart_sha256",
    "sheet_number",
    "slot",
    "primary_morphology",
    "market_tape",
    "signal_candle",
    "turnover_state",
    "evidence",
    "reviewer",
)
PHASE2A_LEDGER_FIELDS = (
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
AXIS_LABELS: dict[str, tuple[str, ...]] = {
    "primary_morphology": (
        "BASE_COMPRESSION",
        "ORDERLY_UPTREND",
        "EXTENDED_OR_SPIKE",
        "DOWNTREND_OR_BREAKDOWN",
        "CHOPPY_NO_STRUCTURE",
    ),
    "market_tape": ("BROAD_UP", "BROAD_DOWN", "MIXED_TRANSITION"),
    "turnover_state": (
        "DRY_OR_CONTRACTING",
        "SURGE_OR_EXPANDING",
        "NORMAL_MIXED",
    ),
}
SINGLE_AXES = tuple(AXIS_LABELS)
PAIRWISE_AXES = (
    ("primary_morphology", "market_tape"),
    ("primary_morphology", "turnover_state"),
    ("market_tape", "turnover_state"),
)
OUTCOME_BUCKETS = (
    "PROFIT_GE_4PCT",
    "PROFIT_0_TO_4PCT",
    "LOSS_0_TO_10PCT",
    "SEVERE_LOSS",
    "NO_COMPLETED_TRADE",
)
COMPLETED_BUCKETS = OUTCOME_BUCKETS[:-1]
POST_PATH_LABELS = (
    "IMMEDIATE_ACCEPTANCE",
    "DELAYED_ACCEPTANCE",
    "EARLY_REJECTION",
    "LATE_REJECTION",
    "CHOP_OR_AMBIGUOUS",
    "NO_COMPLETED_TRADE",
)
ACCEPTANCE_LABELS = ("IMMEDIATE_ACCEPTANCE", "DELAYED_ACCEPTANCE")
REJECTION_LABELS = ("EARLY_REJECTION", "LATE_REJECTION")

OUTPUT_FILES = (
    "coverage.json",
    "single_axis_contingencies.json",
    "pairwise_contingencies.json",
    "summary.json",
    "manifest.json",
)
REQUIRED_TRUE = (
    "phase2a_synthesis_authorized",
    "phase1_frozen_anonymous_ledger_read_authorized",
    "phase2a_frozen_anonymous_ledger_read_authorized",
    "anonymous_join_authorized",
    "outcome_bucket_parse_authorized",
    "post_path_label_parse_authorized",
    "categorical_descriptive_aggregation_authorized",
    "single_axis_contingency_authorized",
    "fixed_pairwise_contingency_authorized",
    "atomic_publication_authorized",
)
REQUIRED_FALSE = (
    "identity_read_authorized",
    "date_or_year_read_authorized",
    "stage_b_artifact_read_authorized",
    "numeric_return_read_authorized",
    "signal_candle_use_authorized",
    "phase1_label_rewrite_authorized",
    "post_signal_predictor_authorized",
    "threshold_search_authorized",
    "rule_generation_authorized",
    "combination_ranking_authorized",
    "portfolio_replay_authorized",
    "2020_signal_outcome_read_authorized",
    "2021_plus_read_authorized",
)


class SynthesisError(RuntimeError):
    """Fail closed on every contract, input, coverage, or publication drift."""


def sha256_file(path: Path, label: str, *, reject_symlink: bool = True) -> str:
    if reject_symlink and path.is_symlink():
        raise SynthesisError(f"{label} must not be a symbolic link: {path}")
    if not path.is_file():
        raise SynthesisError(f"missing regular file for {label}: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise SynthesisError(f"cannot hash {label} at {path}: {exc}") from exc
    return digest.hexdigest()


def strict_json(path: Path, label: str) -> Any:
    def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        keys = [key for key, _ in pairs]
        duplicates = sorted(key for key, count in Counter(keys).items() if count > 1)
        if duplicates:
            raise SynthesisError(f"duplicate JSON keys in {label}: {duplicates}")
        return dict(pairs)

    if path.is_symlink():
        raise SynthesisError(f"{label} must not be a symbolic link: {path}")
    try:
        return json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicate_keys
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SynthesisError(f"cannot read {label} at {path}: {exc}") from exc


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SynthesisError(f"{label} must be a JSON object")
    return value


def require_exact_keys(value: Any, expected: Iterable[str], label: str) -> dict[str, Any]:
    expected_tuple = tuple(expected)
    if not isinstance(value, dict) or set(value) != set(expected_tuple):
        raise SynthesisError(f"{label} must contain exactly {expected_tuple}")
    return value


def require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise SynthesisError(f"{label} must be one lowercase SHA-256 digest")
    return value


def require_positive_integer(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise SynthesisError(f"{label} must be a positive integer")
    return value


def only(items: list[dict[str, Any]], label: str) -> dict[str, Any]:
    if len(items) != 1:
        raise SynthesisError(f"expected one {label}; found {len(items)}")
    return items[0]


def bound_artifact_map(value: Any, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        raise SynthesisError(f"{label} must be a list")
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("role"), str):
            raise SynthesisError(f"{label} contains a malformed item")
        role = item["role"]
        if role in result:
            raise SynthesisError(f"duplicate {label} role: {role}")
        result[role] = item
    return result


def assert_literal_binding(
    artifacts: dict[str, dict[str, Any]],
    role: str,
    path_text: str,
    expected_hash: str,
) -> None:
    item = artifacts.get(role)
    if (
        item is None
        or item.get("path") != path_text
        or item.get("sha256") != expected_hash
    ):
        raise SynthesisError(f"CY-060 does not bind exact artifact {role}")


def validate_static_contract() -> dict[str, Any]:
    """Verify only repository code and the frozen spec."""
    actual_spec_hash = sha256_file(SPEC, "CY-060 synthesis freeze")
    if actual_spec_hash != SPEC_SHA256:
        raise SynthesisError(
            f"frozen synthesis spec drift: {actual_spec_hash} != {SPEC_SHA256}"
        )
    runner_hash = sha256_file(Path(__file__), "synthesis runner", reject_symlink=False)
    spec = require_object(strict_json(SPEC, "CY-060 synthesis freeze"), "freeze")
    identity = require_object(spec.get("protocol_identity"), "protocol_identity")
    binding = require_object(spec.get("runner_binding"), "runner_binding")
    frozen_inputs = require_object(
        spec.get("frozen_anonymous_inputs"), "frozen_anonymous_inputs"
    )
    input_boundary = require_object(spec.get("input_boundary"), "input_boundary")
    join = require_object(spec.get("join_contract"), "join_contract")
    attribution = require_object(
        spec.get("frozen_categorical_attribution"), "frozen attribution"
    )
    aggregations = require_object(spec.get("fixed_aggregations"), "fixed aggregations")
    support = require_object(spec.get("support_policy"), "support policy")
    output = require_object(spec.get("output_contract"), "output contract")
    permissions = require_object(
        spec.get("required_authorization_permissions"), "authorization permissions"
    )

    expected_inputs = {
        role: {"path": str(path), "sha256": EXTERNAL_HASHES[path]}
        for role, path in EXTERNAL_ROLES
    }
    for role, expected in expected_inputs.items():
        item = require_object(frozen_inputs.get(role), f"frozen input {role}")
        if item.get("path") != expected["path"] or item.get("sha256") != expected["sha256"]:
            raise SynthesisError(f"frozen external input identity drift: {role}")

    if (
        spec.get("spec_id") != SPEC_ID
        or spec.get("experiment") != EXPERIMENT
        or spec.get("stage") != STAGE
        or spec.get("status") != STATUS
        or identity.get("asset_id") != ASSET_ID
        or identity.get("authorization_id") != AUTHORIZATION_ID
        or identity.get("authorized_arm") != AUTHORIZED_ARM
        or identity.get("authorization_purpose") != AUTHORIZATION_PURPOSE
        or identity.get("pipeline_version") != PIPELINE_VERSION
        or binding.get("path") != RUNNER_REL
        or binding.get("spec_sha256_must_be_hardcoded_by_runner") is not True
        or input_boundary.get("only_external_files")
        != [role for role, _ in EXTERNAL_ROLES]
        or any(
            input_boundary.get(key) is not False
            for key in (
                "public_modes_external_file_touch",
                "external_access_before_joint_authorization",
                "identity_or_crosswalk_read",
                "date_or_year_read",
                "stage_b_artifact_read_or_hash",
                "numeric_return_read",
                "2020_signal_outcome_or_label_read",
                "2021_plus_read",
            )
        )
        or input_boundary.get("reverify_all_four_inputs_before_publication") is not True
        or join.get("keys_exact") != ["chart_number", "blind_chart_id"]
        or join.get("phase1_population") != EXPECTED_PHASE1_EVENTS
        or join.get("phase2a_population") != EXPECTED_PHASE2A_EVENTS
        or join.get("expected_exact_matches") != EXPECTED_PHASE2A_EVENTS
        or join.get("expected_phase1_unmatched") != EXPECTED_PHASE1_UNMATCHED
        or join.get("phase2a_unmatched_allowed") != 0
        or join.get("duplicate_key_allowed") is not False
        or join.get("persist_row_level_join") is not False
        or join.get("persist_identity_crosswalk") is not False
        or spec.get("pre_outcome_eligible_axes")
        != {axis: list(labels) for axis, labels in AXIS_LABELS.items()}
        or spec.get("excluded_phase1_fields", {}).get("signal_candle")
        != (
            "COMPLETELY_EXCLUDED_FROM_SYNTHESIS_AND_OUTPUTS_BECAUSE_"
            "PRE_OUTCOME_RELIABILITY_GATE_FAILED"
        )
        or attribution.get("outcome_buckets") != list(OUTCOME_BUCKETS)
        or attribution.get("post_path_labels") != list(POST_PATH_LABELS)
        or attribution.get("acceptance_labels") != list(ACCEPTANCE_LABELS)
        or attribution.get("rejection_labels") != list(REJECTION_LABELS)
        or attribution.get("completed_outcome_buckets") != list(COMPLETED_BUCKETS)
        or attribution.get("numeric_return_available_to_runner") is not False
        or attribution.get("post_path_label_predictor_use") is not False
        or aggregations.get("single_axes") != list(SINGLE_AXES)
        or aggregations.get("pairwise_axes") != [list(pair) for pair in PAIRWISE_AXES]
        or aggregations.get("emit_every_predeclared_level_and_cartesian_cell_in_frozen_order")
        is not True
        or aggregations.get("best_cell_selection") is not False
        or aggregations.get("combination_ordering_or_ranking") is not False
        or aggregations.get("threshold_or_rule_generation") is not False
        or support.get("minimum_total_n") != MINIMUM_SUPPORT
        or support.get("minimum_completed_n") != MINIMUM_SUPPORT
        or support.get("flags_only") is not True
        or output.get("root") != str(OUTPUT)
        or output.get("files") != list(OUTPUT_FILES)
        or any(
            output.get(key) is not False
            for key in (
                "row_level_output",
                "identity_or_date_output",
                "signal_candle_output",
                "numeric_return_output",
                "rule_or_threshold_output",
            )
        )
        or output.get("atomic_exclusive_no_overwrite") is not True
        or output.get("deterministic_serialization") is not True
    ):
        raise SynthesisError("CY-060 frozen static semantics drift")
    if set(permissions) != set((*REQUIRED_TRUE, *REQUIRED_FALSE)):
        raise SynthesisError("CY-060 permission key set drift")
    for key in REQUIRED_TRUE:
        if permissions.get(key) is not True:
            raise SynthesisError(f"frozen permission must be true: {key}")
    for key in REQUIRED_FALSE:
        if permissions.get(key) is not False:
            raise SynthesisError(f"frozen permission must be false: {key}")
    if OUTPUT.parent != ROOT or OUTPUT.name != "stage_g_phase2a_signal_time_outcome_synthesis":
        raise SynthesisError("bounded output location drift")
    return {
        "status": "STATIC_CONTRACT_PASS",
        "experiment": EXPERIMENT,
        "spec_sha256": actual_spec_hash,
        "runner_sha256": runner_hash,
        "external_artifacts_touched": False,
        "stage_b_artifacts_touched": False,
    }


def verify_public_authorization() -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify repository authorization only; external paths remain lexical strings."""
    actual = validate_static_contract()
    for path, label in ((REGISTRY, "central registry"), (CY060_MANIFEST, "CY-060 manifest")):
        if not path.is_file() or path.is_symlink():
            raise SynthesisError(f"missing regular repository {label}: {path}")
    registry_hash = sha256_file(REGISTRY, "central registry", reject_symlink=False)
    manifest_hash = sha256_file(CY060_MANIFEST, "CY-060 manifest")
    registry = require_object(strict_json(REGISTRY, "central registry"), "registry")
    manifest = require_object(strict_json(CY060_MANIFEST, "CY-060 manifest"), "manifest")
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
    lineage = require_object(asset.get("lineage"), "CY-060 asset lineage")
    bound_manifest = require_object(
        authorization.get("bound_manifest"), "CY-060 bound_manifest"
    )
    protocol = require_object(
        authorization.get("bound_protocol"), "CY-060 bound_protocol"
    )
    scope = require_object(authorization.get("scope"), "CY-060 scope")
    if (
        asset.get("status") != "RESEARCH_CONDITIONAL"
        or asset.get("kind") != ASSET_KIND
        or asset.get("pit_grade") != "B"
        or asset.get("physical_state") != "MATERIALIZED"
        or asset.get("location") != str(PHASE2A_ROOT)
        or lineage.get("manifest_path") != str(CY060_MANIFEST.resolve())
        or lineage.get("manifest_sha256") != manifest_hash
        or lineage.get("bounded_authorization_id") != AUTHORIZATION_ID
        or lineage.get("pipeline_version") != PIPELINE_VERSION
        or authorization.get("asset_id") != ASSET_ID
        or authorization.get("dependency_asset_id") != "CY-056"
        or authorization.get("dependency_asset_ids") != ["CY-052", "CY-056"]
        or authorization.get("dependency_status") != "RESEARCH_CONDITIONAL"
        or authorization.get("purpose") != AUTHORIZATION_PURPOSE
        or authorization.get("authorized_arms") != [AUTHORIZED_ARM]
        or authorization.get("record_level_available_at_available") is not False
        or bound_manifest.get("path") != str(CY060_MANIFEST.resolve())
        or bound_manifest.get("sha256") != manifest_hash
        or protocol.get("path") != str(SPEC.resolve())
        or protocol.get("sha256") != actual["spec_sha256"]
        or protocol.get("runner_path") != str(Path(__file__).resolve())
        or protocol.get("runner_sha256") != actual["runner_sha256"]
        or scope.get("project") != "research/market_behavior_os_v2"
        or scope.get("start") != "2018-03-27"
        or scope.get("end") != "2019-12-31"
        or scope.get("frozen_phase1_events") != EXPECTED_PHASE1_EVENTS
        or scope.get("frozen_phase2a_events") != EXPECTED_PHASE2A_EVENTS
        or scope.get("phase1_unmatched_not_parsed") != EXPECTED_PHASE1_UNMATCHED
    ):
        raise SynthesisError("CY-060 asset/authorization identity or scope drift")

    frozen_permissions = require_object(
        strict_json(SPEC, "CY-060 synthesis freeze").get(
            "required_authorization_permissions"
        ),
        "frozen permissions",
    )
    for key in REQUIRED_TRUE:
        if authorization.get(key) is not True or frozen_permissions.get(key) is not True:
            raise SynthesisError(f"CY-060 permission is not jointly true: {key}")
    for key in REQUIRED_FALSE:
        if authorization.get(key) is not False or frozen_permissions.get(key) is not False:
            raise SynthesisError(f"CY-060 forbidden permission is not jointly false: {key}")

    artifacts = bound_artifact_map(
        authorization.get("bound_artifacts"), "CY-060 authorization bound_artifacts"
    )
    expected_roles = {
        "synthesis_freeze",
        "synthesis_runner",
        *(role for role, _ in EXTERNAL_ROLES),
    }
    if set(artifacts) != expected_roles:
        raise SynthesisError("CY-060 authorization exact bound-artifact role set drift")
    assert_literal_binding(
        artifacts, "synthesis_freeze", str(SPEC.resolve()), actual["spec_sha256"]
    )
    assert_literal_binding(
        artifacts,
        "synthesis_runner",
        str(Path(__file__).resolve()),
        actual["runner_sha256"],
    )
    for role, path in EXTERNAL_ROLES:
        # Literal comparison only: do not resolve/stat/hash/open an external path.
        assert_literal_binding(artifacts, role, str(path), EXTERNAL_HASHES[path])

    manifest_protocol = require_object(manifest.get("protocol"), "manifest protocol")
    manifest_boundary = require_object(
        manifest.get("authorization_boundary"), "manifest authorization boundary"
    )
    manifest_scope = require_object(manifest.get("frozen_scope"), "manifest scope")
    if (
        manifest.get("asset_id") != ASSET_ID
        or manifest.get("status") != MANIFEST_STATUS
        or manifest.get("pipeline_version") != PIPELINE_VERSION
        or manifest_protocol.get("spec_path") != str(SPEC.resolve())
        or manifest_protocol.get("spec_sha256") != actual["spec_sha256"]
        or manifest_protocol.get("runner_path") != str(Path(__file__).resolve())
        or manifest_protocol.get("runner_sha256") != actual["runner_sha256"]
        or manifest_boundary.get("authorization_id") != AUTHORIZATION_ID
        or manifest_boundary.get("purpose") != AUTHORIZATION_PURPOSE
        or manifest_boundary.get("authorized_arm") != AUTHORIZED_ARM
        or manifest_scope.get("phase1_events") != EXPECTED_PHASE1_EVENTS
        or manifest_scope.get("phase2a_events") != EXPECTED_PHASE2A_EVENTS
        or manifest_scope.get("phase1_unmatched") != EXPECTED_PHASE1_UNMATCHED
        or manifest_scope.get("join_keys") != ["chart_number", "blind_chart_id"]
        or manifest.get("canonical_output") != str(OUTPUT)
    ):
        raise SynthesisError("CY-060 manifest semantics drift")
    for key in REQUIRED_TRUE:
        if manifest_boundary.get(key) is not True:
            raise SynthesisError(f"CY-060 manifest permission is not true: {key}")
    for key in REQUIRED_FALSE:
        if manifest_boundary.get(key) is not False:
            raise SynthesisError(f"CY-060 manifest forbidden permission is not false: {key}")
    manifest_artifacts = bound_artifact_map(
        manifest.get("bound_artifacts"), "CY-060 manifest bound_artifacts"
    )
    if set(manifest_artifacts) != expected_roles:
        raise SynthesisError("CY-060 manifest exact bound-artifact role set drift")
    for role, item in artifacts.items():
        if manifest_artifacts.get(role) != item:
            raise SynthesisError(f"CY-060 manifest/registry artifact drift: {role}")

    actual.update(
        {
            "registry_sha256": registry_hash,
            "cy060_manifest_sha256": manifest_hash,
            "external_artifacts_touched": False,
            "stage_b_artifacts_touched": False,
            "status": "PUBLIC_AUTHORIZATION_PASS",
        }
    )
    return actual, authorization


def verify_external_hashes() -> dict[str, str]:
    """First permitted external access; hashes exactly four anonymous files."""
    actual: dict[str, str] = {}
    for role, path in EXTERNAL_ROLES:
        value = sha256_file(path, role)
        if value != EXTERNAL_HASHES[path]:
            raise SynthesisError(f"frozen anonymous input drift: {role}: {value}")
        actual[role] = value
    return actual


def validate_external_manifests() -> None:
    phase1 = require_object(strict_json(PHASE1_MANIFEST, "Phase-1 manifest"), "Phase-1 manifest")
    phase2a = require_object(
        strict_json(PHASE2A_MANIFEST, "Phase-2A manifest"), "Phase-2A manifest"
    )
    phase1_ledger = require_object(phase1.get("ledger"), "Phase-1 manifest ledger")
    phase2a_ledger = require_object(phase2a.get("ledger"), "Phase-2A manifest ledger")
    phase1_governance = require_object(
        phase1.get("governance"), "Phase-1 manifest governance"
    )
    phase2a_governance = require_object(
        phase2a.get("governance"), "Phase-2A manifest governance"
    )
    if (
        phase1.get("experiment") != EXPERIMENT
        or phase1.get("stage") != "PHASE1_ANONYMOUS_SIGNAL_TIME_ANNOTATIONS_FROZEN"
        or phase1.get("status") != "FROZEN_OUTCOME_BLIND"
        or phase1.get("events") != EXPECTED_PHASE1_EVENTS
        or phase1.get("coverage_exactly_once") is not True
        or phase1_ledger.get("file") != PHASE1_LEDGER.name
        or phase1_ledger.get("sha256") != EXTERNAL_HASHES[PHASE1_LEDGER]
        or phase1_ledger.get("rows") != EXPECTED_PHASE1_EVENTS
        or phase1_ledger.get("columns") != list(PHASE1_LEDGER_FIELDS)
        or phase1_governance.get("stage_b_result_read") is not False
        or phase1_governance.get("future_paths_read") is not False
        or phase1_governance.get("outcomes_read") is not False
        or phase1_governance.get("post_signal_rows_read") is not False
        or phase1_governance.get("returns_aggregated") is not False
        or phase1_governance.get("signal_candle_rule_use_permitted") is not False
    ):
        raise SynthesisError("frozen Phase-1 manifest semantics drift")
    if (
        phase2a.get("experiment") != EXPERIMENT
        or phase2a.get("stage") != "PHASE2A_ANONYMOUS_ATTRIBUTION_REVIEW_FROZEN"
        or phase2a.get("status") != "FROZEN_ANONYMOUS_REVIEW_ONLY"
        or phase2a.get("events") != EXPECTED_PHASE2A_EVENTS
        or phase2a.get("coverage_exactly_once") is not True
        or phase2a_ledger.get("file") != PHASE2A_LEDGER.name
        or phase2a_ledger.get("sha256") != EXTERNAL_HASHES[PHASE2A_LEDGER]
        or phase2a_ledger.get("rows") != EXPECTED_PHASE2A_EVENTS
        or phase2a_ledger.get("exact_fields") != list(PHASE2A_LEDGER_FIELDS)
        or phase2a_governance.get("phase1_labels_modified") is not False
        or phase2a_governance.get("signal_candle_used_for_rule") is not False
        or phase2a_governance.get("post_signal_used_as_predictor") is not False
        or phase2a_governance.get("stage_b_artifact_read") is not False
        or phase2a_governance.get("numeric_return_read") is not False
        or phase2a_governance.get("numeric_return_persisted") is not False
        or phase2a_governance.get("rule_generated") is not False
        or phase2a_governance.get("rule_aggregation_performed") is not False
        or phase2a_governance.get("identity_mapping_read") is not False
        or phase2a_governance.get("identity_crosswalk_read") is not False
    ):
        raise SynthesisError("frozen Phase-2A manifest semantics drift")


def parse_chart_key(number_text: str, blind_id: str, label: str) -> tuple[int, str]:
    if POSITIVE_INTEGER_PATTERN.fullmatch(number_text) is None:
        raise SynthesisError(f"invalid anonymous chart number in {label}: {number_text!r}")
    number = int(number_text)
    if OPAQUE_ID_PATTERN.fullmatch(blind_id) is None:
        raise SynthesisError(f"invalid blind chart id in {label}: {blind_id!r}")
    return number, blind_id


def load_phase2a_rows() -> tuple[list[dict[str, Any]], set[tuple[int, str]]]:
    value = strict_json(PHASE2A_LEDGER, "Phase-2A annotation ledger")
    if not isinstance(value, list) or len(value) != EXPECTED_PHASE2A_EVENTS:
        raise SynthesisError("Phase-2A ledger must contain exactly 915 rows")
    rows: list[dict[str, Any]] = []
    keys: set[tuple[int, str]] = set()
    for position, raw in enumerate(value, start=1):
        row = require_exact_keys(raw, PHASE2A_LEDGER_FIELDS, f"Phase-2A row {position}")
        if type(row["chart_number"]) is not int:
            raise SynthesisError(f"Phase-2A chart_number must be integer at row {position}")
        key = parse_chart_key(
            str(row["chart_number"]), row["blind_chart_id"], f"Phase-2A row {position}"
        )
        if key in keys:
            raise SynthesisError(f"duplicate Phase-2A anonymous key: {key}")
        bucket = row["outcome_bucket"]
        post_label = row["post_path_label"]
        if bucket not in OUTCOME_BUCKETS or post_label not in POST_PATH_LABELS:
            raise SynthesisError(f"invalid categorical attribution at Phase-2A row {position}")
        if (bucket == "NO_COMPLETED_TRADE") != (post_label == "NO_COMPLETED_TRADE"):
            raise SynthesisError(f"no-completed bucket/path mismatch at Phase-2A row {position}")
        for field in (
            "phase1_labels_modified",
            "signal_candle_used_for_rule",
            "post_signal_used_as_predictor",
        ):
            if row[field] is not False:
                raise SynthesisError(f"Phase-2A governance drift in {field} at row {position}")
        keys.add(key)
        rows.append(
            {
                "chart_number": key[0],
                "blind_chart_id": key[1],
                "outcome_bucket": bucket,
                "post_path_label": post_label,
            }
        )
    if [row["chart_number"] for row in rows] != sorted(
        row["chart_number"] for row in rows
    ):
        raise SynthesisError("Phase-2A ledger must be in ascending chart_number order")
    return rows, keys


def load_matching_phase1_axes(
    phase2a_keys: set[tuple[int, str]],
) -> tuple[dict[tuple[int, str], dict[str, str]], int]:
    """Project axes only for Phase-2A keys; unmatched Phase-1 labels stay unparsed."""
    selected: dict[tuple[int, str], dict[str, str]] = {}
    seen_keys: set[tuple[int, str]] = set()
    physical_rows = 0
    try:
        with PHASE1_LEDGER.open("r", encoding="utf-8", newline="") as handle:
            header_line = handle.readline()
            header = next(csv.reader([header_line]))
            if tuple(header) != PHASE1_LEDGER_FIELDS:
                raise SynthesisError("Phase-1 ledger header drift")
            positions = {name: index for index, name in enumerate(header)}
            for line_number, line in enumerate(handle, start=2):
                if not line.endswith("\n") or "\r" in line:
                    raise SynthesisError(
                        f"Phase-1 ledger must have one LF-terminated physical row at {line_number}"
                    )
                # The first two fields are unquoted canonical anonymous keys.  Split
                # only that prefix first, so unmatched rows' label fields are never
                # projected or interpreted by this process.
                prefix = line[:-1].split(",", 2)
                if len(prefix) != 3:
                    raise SynthesisError(f"malformed Phase-1 row prefix at line {line_number}")
                key = parse_chart_key(prefix[0], prefix[1], f"Phase-1 line {line_number}")
                if key in seen_keys:
                    raise SynthesisError(f"duplicate Phase-1 anonymous key: {key}")
                seen_keys.add(key)
                physical_rows += 1
                if key not in phase2a_keys:
                    continue
                parsed = next(csv.reader([line]))
                if len(parsed) != len(header):
                    raise SynthesisError(f"Phase-1 field count drift at line {line_number}")
                projected: dict[str, str] = {}
                for axis, labels in AXIS_LABELS.items():
                    label = parsed[positions[axis]]
                    if label not in labels:
                        raise SynthesisError(
                            f"invalid {axis} label for matched Phase-1 key {key}: {label}"
                        )
                    projected[axis] = label
                selected[key] = projected
    except (OSError, UnicodeError, csv.Error) as exc:
        raise SynthesisError(f"cannot parse frozen Phase-1 ledger: {exc}") from exc
    if physical_rows != EXPECTED_PHASE1_EVENTS or len(seen_keys) != EXPECTED_PHASE1_EVENTS:
        raise SynthesisError("Phase-1 anonymous key population drift")
    if {number for number, _blind_id in seen_keys} != set(
        range(1, EXPECTED_PHASE1_EVENTS + 1)
    ):
        raise SynthesisError("Phase-1 chart-number coverage is not exactly 1..1483")
    if len(selected) != EXPECTED_PHASE2A_EVENTS or set(selected) != phase2a_keys:
        raise SynthesisError("Phase-1 to Phase-2A anonymous coverage is not exact")
    unmatched = EXPECTED_PHASE1_EVENTS - len(selected)
    if unmatched != EXPECTED_PHASE1_UNMATCHED:
        raise SynthesisError("Phase-1 unmatched count drift")
    return selected, unmatched


def build_joined_rows() -> tuple[list[dict[str, str]], int]:
    phase2a_rows, phase2a_keys = load_phase2a_rows()
    phase1_axes, unmatched = load_matching_phase1_axes(phase2a_keys)
    joined: list[dict[str, str]] = []
    for row in phase2a_rows:
        key = (row["chart_number"], row["blind_chart_id"])
        axes = phase1_axes.get(key)
        if axes is None:
            raise SynthesisError(f"missing Phase-1 match for anonymous key: {key}")
        joined.append(
            {
                **axes,
                "outcome_bucket": row["outcome_bucket"],
                "post_path_label": row["post_path_label"],
            }
        )
    if len(joined) != EXPECTED_PHASE2A_EVENTS:
        raise SynthesisError("anonymous joined population drift")
    return joined, unmatched


def safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def summarize_cell(rows: Sequence[dict[str, str]]) -> dict[str, Any]:
    total_n = len(rows)
    bucket_counts = {
        bucket: sum(row["outcome_bucket"] == bucket for row in rows)
        for bucket in OUTCOME_BUCKETS
    }
    path_counts = {
        label: sum(row["post_path_label"] == label for row in rows)
        for label in POST_PATH_LABELS
    }
    if sum(bucket_counts.values()) != total_n or sum(path_counts.values()) != total_n:
        raise SynthesisError("categorical count conservation failed")
    completed_n = total_n - bucket_counts["NO_COMPLETED_TRADE"]
    acceptance_n = sum(path_counts[label] for label in ACCEPTANCE_LABELS)
    rejection_n = sum(path_counts[label] for label in REJECTION_LABELS)
    chop_n = path_counts["CHOP_OR_AMBIGUOUS"]
    if acceptance_n + rejection_n + chop_n != completed_n:
        raise SynthesisError("completed post-path count conservation failed")
    total_support = total_n >= MINIMUM_SUPPORT
    completed_support = completed_n >= MINIMUM_SUPPORT
    return {
        "n": total_n,
        "completed_n": completed_n,
        "completion_rate": safe_rate(completed_n, total_n),
        "outcome_bucket_counts": bucket_counts,
        "outcome_bucket_rates": {
            bucket: safe_rate(bucket_counts[bucket], total_n) for bucket in OUTCOME_BUCKETS
        },
        "post_path_label_counts": path_counts,
        "post_path_label_rates": {
            label: safe_rate(path_counts[label], total_n) for label in POST_PATH_LABELS
        },
        "acceptance_n": acceptance_n,
        "acceptance_rate_completed": safe_rate(acceptance_n, completed_n),
        "rejection_n": rejection_n,
        "rejection_rate_completed": safe_rate(rejection_n, completed_n),
        "chop_or_ambiguous_n": chop_n,
        "chop_or_ambiguous_rate_completed": safe_rate(chop_n, completed_n),
        "support_flags": {
            "total_n_ge_25": total_support,
            "completed_n_ge_25": completed_support,
            "all_four_completed_outcome_buckets_observed": all(
                bucket_counts[bucket] > 0 for bucket in COMPLETED_BUCKETS
            ),
            "acceptance_and_rejection_both_observed": acceptance_n > 0
            and rejection_n > 0,
            "descriptive_rate_support": total_support and completed_support,
        },
    }


def build_single_axis_tables(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for axis in SINGLE_AXES:
        for level in AXIS_LABELS[axis]:
            cell_rows = [row for row in rows if row[axis] == level]
            output.append(
                {
                    "axis": axis,
                    "level": level,
                    "population_rate": safe_rate(len(cell_rows), len(rows)),
                    **summarize_cell(cell_rows),
                }
            )
    return output


def build_pairwise_tables(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for axis_a, axis_b in PAIRWISE_AXES:
        for level_a, level_b in itertools.product(
            AXIS_LABELS[axis_a], AXIS_LABELS[axis_b]
        ):
            cell_rows = [
                row
                for row in rows
                if row[axis_a] == level_a and row[axis_b] == level_b
            ]
            output.append(
                {
                    "axis_a": axis_a,
                    "level_a": level_a,
                    "axis_b": axis_b,
                    "level_b": level_b,
                    "population_rate": safe_rate(len(cell_rows), len(rows)),
                    **summarize_cell(cell_rows),
                }
            )
    return output


def write_json_exclusive(path: Path, value: Any) -> None:
    encoded = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise SynthesisError(f"cannot exclusively write {path}: {exc}") from exc


def fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise SynthesisError(f"cannot fsync directory {path}: {exc}") from exc


def atomic_publish_no_replace(source: Path, destination: Path) -> None:
    """Atomically publish a directory while rejecting every existing target."""
    libc = ctypes.CDLL(None, use_errno=True)
    rename_exclusive = getattr(libc, "renamex_np", None)
    if rename_exclusive is None:
        raise SynthesisError("atomic exclusive directory rename is unavailable")
    rename_exclusive.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    rename_exclusive.restype = ctypes.c_int
    rename_excl = 0x00000004  # Darwin RENAME_EXCL.
    if rename_exclusive(os.fsencode(source), os.fsencode(destination), rename_excl):
        error = ctypes.get_errno()
        raise SynthesisError(
            f"atomic no-overwrite publication failed: {os.strerror(error)}"
        )


def write_outputs(
    staging: Path,
    joined: list[dict[str, str]],
    unmatched: int,
    external_hashes: dict[str, str],
    public_hashes: dict[str, Any],
) -> dict[str, Any]:
    coverage = {
        "phase1_events": EXPECTED_PHASE1_EVENTS,
        "phase2a_events": EXPECTED_PHASE2A_EVENTS,
        "anonymous_exact_matches": len(joined),
        "phase1_unmatched_labels_not_projected": unmatched,
        "phase2a_unmatched": 0,
        "duplicate_keys": 0,
        "join_keys": ["chart_number", "blind_chart_id"],
        "row_level_join_persisted": False,
    }
    single_axis = {
        "stage": STAGE,
        "axes": list(SINGLE_AXES),
        "cells": build_single_axis_tables(joined),
        "selection_or_ranking_performed": False,
    }
    pairwise = {
        "stage": STAGE,
        "fixed_pairs": [list(pair) for pair in PAIRWISE_AXES],
        "cells": build_pairwise_tables(joined),
        "selection_or_ranking_performed": False,
    }
    summary = {
        "experiment": EXPERIMENT,
        "stage": STAGE,
        "status": "ANONYMOUS_DESCRIPTIVE_SYNTHESIS_ONLY",
        "coverage": coverage,
        "overall": summarize_cell(joined),
        "single_axis_cells": len(single_axis["cells"]),
        "pairwise_cells": len(pairwise["cells"]),
        "support_thresholds": {
            "minimum_total_n": MINIMUM_SUPPORT,
            "minimum_completed_n": MINIMUM_SUPPORT,
            "flags_only": True,
        },
        "rate_denominators": {
            "outcome_bucket_rates": "cell total N",
            "post_path_label_rates": "cell total N",
            "acceptance_rejection_chop_rates": "cell completed N",
        },
        "governance": {
            "identity_or_crosswalk_read": False,
            "date_or_year_data_read": False,
            "stage_b_artifact_read_or_hashed": False,
            "numeric_return_read_or_aggregated": False,
            "phase1_unmatched_labels_projected": False,
            "signal_candle_consumed_or_output": False,
            "phase1_labels_modified": False,
            "phase2a_labels_modified": False,
            "post_signal_used_as_predictor": False,
            "best_cell_selected": False,
            "combination_ranked": False,
            "threshold_or_rule_generated": False,
            "portfolio_replayed": False,
            "2020_signal_outcome_read": False,
            "2021_plus_read": False,
        },
    }
    payloads = {
        "coverage.json": coverage,
        "single_axis_contingencies.json": single_axis,
        "pairwise_contingencies.json": pairwise,
        "summary.json": summary,
    }
    output_hashes: dict[str, str] = {}
    for name, payload in payloads.items():
        path = staging / name
        write_json_exclusive(path, payload)
        output_hashes[name] = sha256_file(path, f"staged {name}", reject_symlink=False)

    manifest = {
        "experiment": EXPERIMENT,
        "stage": STAGE,
        "status": "ANONYMOUS_DESCRIPTIVE_SYNTHESIS_ONLY",
        "asset_id": ASSET_ID,
        "authorization_id": AUTHORIZATION_ID,
        "events": len(joined),
        "coverage_exactly_once": True,
        "spec": {"path": SPEC_REL, "sha256": public_hashes["spec_sha256"]},
        "runner": {"path": RUNNER_REL, "sha256": public_hashes["runner_sha256"]},
        "source_hashes": external_hashes,
        "public_authorization_hashes": {
            "registry_sha256": public_hashes["registry_sha256"],
            "cy060_manifest_sha256": public_hashes["cy060_manifest_sha256"],
        },
        "outputs": output_hashes,
        "fixed_single_axes": list(SINGLE_AXES),
        "fixed_pairwise_axes": [list(pair) for pair in PAIRWISE_AXES],
        "support_flags_only": True,
        "row_level_output": False,
        "identity_or_date_output": False,
        "numeric_return_output": False,
        "signal_candle_output": False,
        "rule_or_threshold_output": False,
        "best_cell_selection": False,
        "combination_ranking": False,
        "stage_b_artifact_read_or_hashed": False,
        "post_signal_used_as_predictor": False,
        "2020_signal_outcome_read": False,
        "2021_plus_read": False,
    }
    write_json_exclusive(staging / "manifest.json", manifest)
    return manifest


def reverify_before_publish(
    external_hashes: dict[str, str], public_hashes: dict[str, Any]
) -> None:
    if sha256_file(SPEC, "synthesis freeze changed") != SPEC_SHA256:
        raise SynthesisError("synthesis freeze changed during execution")
    if (
        sha256_file(Path(__file__), "synthesis runner changed", reject_symlink=False)
        != public_hashes["runner_sha256"]
    ):
        raise SynthesisError("synthesis runner changed during execution")
    for role, path in EXTERNAL_ROLES:
        if sha256_file(path, f"{role} changed") != external_hashes[role]:
            raise SynthesisError(f"frozen anonymous input changed during run: {role}")
    refreshed, _ = verify_public_authorization()
    if (
        refreshed["registry_sha256"] != public_hashes["registry_sha256"]
        or refreshed["cy060_manifest_sha256"]
        != public_hashes["cy060_manifest_sha256"]
    ):
        raise SynthesisError("public authorization changed during execution")


def run_synthesis() -> dict[str, Any]:
    public_hashes, _authorization = verify_public_authorization()
    # No external path is resolved, statted, hashed, opened, or parsed before
    # the exact joint public gate above returns successfully.
    external_hashes = verify_external_hashes()
    validate_external_manifests()
    joined, unmatched = build_joined_rows()

    if OUTPUT.exists() or OUTPUT.is_symlink():
        raise SynthesisError(f"refusing to overwrite frozen synthesis output: {OUTPUT}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{OUTPUT.name}.staging-", dir=OUTPUT.parent)
    )
    try:
        manifest = write_outputs(
            staging, joined, unmatched, external_hashes, public_hashes
        )
        fsync_directory(staging)
        reverify_before_publish(external_hashes, public_hashes)
        if OUTPUT.exists() or OUTPUT.is_symlink():
            raise SynthesisError(f"synthesis output appeared during run: {OUTPUT}")
        atomic_publish_no_replace(staging, OUTPUT)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "status": manifest["status"],
        "output": str(OUTPUT),
        "events": len(joined),
        "manifest_sha256": sha256_file(
            OUTPUT / "manifest.json", "published manifest", reject_symlink=False
        ),
        "stage_b_artifact_read_or_hashed": False,
        "numeric_return_read_or_aggregated": False,
        "rule_or_threshold_generated": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--verify-static-contract", action="store_true")
    mode.add_argument("--verify-public-authorization", action="store_true")
    mode.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.verify_static_contract:
        result = validate_static_contract()
    elif args.verify_public_authorization:
        result, _authorization = verify_public_authorization()
    else:
        result = run_synthesis()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
