#!/usr/bin/env python3
"""Outcome-blind entry-evidence forensic for the consumed V29R4 arm.

The runner stops after signal/entry evidence.  It cannot open a candidate
outcome path, run a portfolio, compute an exit, return, holding period or any
performance aggregate.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import sys
import tempfile
import uuid
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from types import ModuleType
from typing import Any

import duckdb
import pandas as pd

REPO_ROOT = Path("/Users/linmei/Documents/CY-supermind-v6-autonomous-20260830")
PREREGISTRATION = REPO_ROOT / (
    "research/market_behavior_os_v2/experiments/"
    "ASHARE-TRUE-GAP-BELOW-L-DEMAND-RECAPTURE-V29R4_"
    "entry_evidence_diagnostic_v1_preregistration.json"
)
PREREGISTRATION_SHA256 = "dae23e23983bff0e915a583931b6fd3f3f7987e0e7b7e3d1a14c3a7d7731a037"
CORRECTION_RUNNER = REPO_ROOT / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_true_gap_below_l_demand_recapture_sequential_v29r45_"
    "stage_b_calendar_correction_r1.py"
)
CORRECTION_RUNNER_SHA256 = "9d4f03694606e3135392bbcb9eae909bbe55644a7cee17baf86022d3e8d6f569"

EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-DEMAND-RECAPTURE-V29R4-ENTRY-EVIDENCE-DIAGNOSTIC-V1"
PROTOCOL_VERSION = "V1_OUTCOME_BLIND_ENTRY_EVIDENCE_FORENSIC"
ASSET_ID = "CY-050"
AUTHORIZATION_ID = "CYQ-AUTH-ASHARE-DEMAND-RECAPTURE-V29R4-ENTRY-EVIDENCE-DIAGNOSTIC-2018-2021-V1"
WRAPPER_ROOT = Path(
    "/Users/linmei/Documents/CY/data/staging/"
    "CY-050-DEMAND-RECAPTURE-V29R4-ENTRY-EVIDENCE-DIAGNOSTIC-V1"
)
WRAPPER_MANIFEST = WRAPPER_ROOT / "asset_manifest.json"
WRAPPER_AUDIT = WRAPPER_ROOT / "activation_audit.json"
OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_demand_recapture_v29r4_entry_evidence_diagnostic_v1"
)
SLOT = OUTPUT_ROOT / "diagnostic"

CORRECTED_PARENT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_demand_recapture_v29r45_stage_b_calendar_correction_r1"
)
CORRECTED_R4 = CORRECTED_PARENT / "v29r4"
CORRECTED_R5 = CORRECTED_PARENT / "v29r5"
CORRECTED_ATTEMPT = CORRECTED_R4 / "attempt_seal.json"
CORRECTED_ATTEMPT_SHA256 = "9f7a5cf926d9a87e8a461e18856248120e6ac6c3427aa46955b6fa55568b1524"
CORRECTED_RESULT = CORRECTED_R4 / "result.json"
CORRECTED_RESULT_SHA256 = "643a35fc9004c174cf1523401f4ab81ea65778beb4f773ad281985ef5cfcdf87"
EXPECTED_BLOCKER = "unexpected unresolved blocks aggregate publication"

PIT_CONTRACT = {
    "grade": "B",
    "publication_allowed": False,
    "qd010_revision_history_complete": False,
    "strict_pit_eligible": False,
    "usage": "RESEARCH_CONDITIONAL_HYPOTHESIS_ONLY",
}

FIRST_FAILURES = (
    "DAILY_CARDINALITY_OR_OFFSETS",
    "SIGNAL_BINDING_OR_LINEAGE",
    "ENTRY_BINDING_OR_LINEAGE",
    "ENTRY_DAILY_CONTEXT_AFTER_EXECUTION_OBSERVATION",
    "ACTION_RECONCILIATION",
    "ENTRY_DAILY_STATE",
    "EXECUTION_CARDINALITY_OR_DATE",
    "EXECUTION_TIMING_OR_COMPLETENESS",
    "EXECUTION_SNAPSHOT_BINDING",
    "ENTRY_PRICE_NONCANONICAL",
    "RAW_L_COORDINATE_NONCANONICAL",
    "LIMIT_GEOMETRY_INVALID",
    "RESOLVED_MECHANICAL_NO_ENTRY",
    "RESOLVED_ENTRY_EVIDENCE",
)
INDEPENDENT_MASKS = (
    "ENTRY_DAILY_AVAILABLE_AFTER_EXECUTION_OBSERVATION",
    "ENTRY_DAILY_DECISION_AFTER_EXECUTION_OBSERVATION",
    "EXECUTION_DAILY_CONTEXT_AVAILABLE_AFTER_EXECUTION_OBSERVATION",
    "RAW_L_COORDINATE_NONCANONICAL",
    "ENTRY_OPEN_NONCANONICAL",
    "UP_LIMIT_NONCANONICAL",
    "DOWN_LIMIT_NONCANONICAL",
    "ACTION_COUNT_OR_TERMS_MISMATCH",
    "ENTRY_DAILY_STATE_UNRESOLVED",
    "EXECUTION_CARDINALITY_OR_DATE",
    "EXECUTION_AVAILABLE_AT_MISSING_OR_MISMATCH",
    "EXECUTION_MINUTE_SHAPE_OR_RESOLUTION_INVALID",
    "EXECUTION_VALIDITY_FLAGS_INVALID",
    "EXECUTION_TRADE_STATUS_INVALID",
    "EXECUTION_SNAPSHOT_ID_MISSING",
    "EXECUTION_DAILY_SNAPSHOT_ID_MISSING",
    "EXECUTION_TIMING_OR_COMPLETENESS",
    "EXECUTION_SNAPSHOT_BINDING_MISMATCH",
    "LIMIT_GEOMETRY_INVALID",
    "BASE_ENTRY_UNRESOLVED",
)

# Deliberately exclude entry-day daily OHLC. Those fields are not complete at
# the frozen 09:35 observation and are unnecessary for this lineage diagnostic.
DIAGNOSTIC_DAILY_COLUMNS = (
    "protocol_arm",
    "gap_id",
    "symbol",
    "signal_date",
    "entry_date",
    "entry_session_offset",
    "trade_date",
    "decision_at",
    "available_at",
    "trade_status",
    "current_day_data_tradable",
    "market_rule_valid",
    "corporate_action_count",
    "corporate_action_ids",
    "share_multiplier",
    "cash_per_share",
    "rights_ratio",
    "rights_price",
    "corporate_action_valid",
    "corporate_action_blocking",
    "corporate_action_snapshot_id",
    "hard_valid",
    "snapshot_id",
    "daily_snapshot_id",
)
DIAGNOSTIC_EXECUTION_COLUMNS = (
    "protocol_arm",
    "gap_id",
    "symbol",
    "signal_date",
    "entry_date",
    "entry_session_offset",
    "trade_date",
    "window_index",
    "available_at",
    "open",
    "trade_status",
    "up_limit_price",
    "down_limit_price",
    "market_rule_valid",
    "source_resolution_minutes",
    "minute_count",
    "distinct_minute_count",
    "ohlc_valid",
    "unit_valid",
    "causal_inputs_valid",
    "hard_valid",
    "snapshot_id",
    "daily_snapshot_id",
)


class DiagnosticError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise DiagnosticError(f"hash target is not one regular non-symlink file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DiagnosticError(f"cannot read {label}: {path}") from exc
    if not isinstance(value, dict):
        raise DiagnosticError(f"{label} is not a JSON object")
    return value


def _load_correction() -> ModuleType:
    if sha256(CORRECTION_RUNNER) != CORRECTION_RUNNER_SHA256:
        raise DiagnosticError("calendar-correction runner hash drift before import")
    name = "_v29r45_calendar_correction_9d4f0369_for_entry_diagnostic"
    spec = importlib.util.spec_from_file_location(name, CORRECTION_RUNNER)
    if spec is None or spec.loader is None:
        raise DiagnosticError("cannot load frozen calendar-correction runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CORRECTION = _load_correction()
BASE = CORRECTION.BASE


def _only(rows: Iterable[dict[str, Any]], label: str) -> dict[str, Any]:
    values = list(rows)
    if len(values) != 1:
        raise DiagnosticError(f"expected exactly one {label}, found {len(values)}")
    return values[0]


def _assert_immutable_file(path: Path, label: str) -> None:
    bound = BASE.reject_symlink_components(path, label)
    identity = bound.lstat()
    if (
        not stat.S_ISREG(identity.st_mode)
        or stat.S_IMODE(identity.st_mode) != 0o444
        or not BASE.is_user_immutable(bound)
    ):
        raise DiagnosticError(f"{label} is not immutable 0444 regular data")


def verify_preregistration() -> dict[str, Any]:
    if sha256(PREREGISTRATION) != PREREGISTRATION_SHA256:
        raise DiagnosticError("entry diagnostic preregistration hash drift")
    value = load_json(PREREGISTRATION, "entry diagnostic preregistration")
    predecessor = value.get("predecessor", {})
    disclosure = predecessor.get("conservative_outcome_disclosure", {})
    authorized = value.get("authorized_input", {})
    output = value.get("required_output", {})
    branch = value.get("predeclared_branch", {})
    wrapper = value.get("wrapper", {})
    if (
        value.get("experiment") != EXPERIMENT
        or value.get("status") != "FROZEN_PRE_ROW_AWAITING_CY050_ACTIVATION_AND_RUNNER_REVIEW"
        or value.get("protocol_version") != PROTOCOL_VERSION
        or value.get("development") != ["2018-01-01", "2021-12-31"]
        or value.get("arm") != "V29R4_CAP25_ONLY"
        or value.get("post_2021_access") != "PROHIBITED"
        or value.get("alpha_selection_allowed") is not False
        or value.get("threshold_selection_allowed") is not False
        or value.get("performance_replay_allowed") is not False
        or disclosure.get("replay_boundary_crossed") is not True
        or disclosure.get("accepted_candidate_paths_may_have_been_decoded") is not True
        or disclosure.get("aggregate_performance_observed") is not False
        or predecessor.get("v29r4_retry_authorized") is not False
        or predecessor.get("v29r5_unlock_authorized") is not False
        or value.get("first_failure_order") != list(FIRST_FAILURES)
        or value.get("independent_static_masks") != list(INDEPENDENT_MASKS)
        or authorized.get("daily_entry_session_offsets") != [-1, 0]
        or authorized.get("execution_entry_session_offsets") != [0]
        or authorized.get("execution_window_indices") != [0]
        or authorized.get("entry_day_daily_ohlc_authorized") is not False
        or authorized.get("action_cutoff")
        != (
            "known_at and available_at must both be no later than entry 09:35; "
            "effective_date can only further bound an already-causal row and can "
            "never bypass that cutoff"
        )
        or output.get("total_candidates") != 251
        or output.get("candidate_outcome_paths_opened") != 0
        or output.get("outcomes_computed") != 0
        or output.get("return_columns_opened") != []
        or output.get("portfolio_replay_run") is not False
        or output.get("charts_run") is not False
        or output.get("post_2021_rows_opened") != 0
        or output.get("blocked_exception_text_persisted") is not False
        or output.get("blocked_row_scope_is_null_until_audit_complete") is not True
        or output.get("unresolved_first_failure_total") is not True
        or output.get("deterministic_repair_directive") is not True
        or branch.get("directives_are_cumulative") is not True
        or branch.get("performance_run_from_this_result") != "PROHIBITED"
        or wrapper.get("asset_id") != ASSET_ID
        or wrapper.get("authorization_id") != AUTHORIZATION_ID
        or wrapper.get("root") != str(WRAPPER_ROOT)
        or value.get("publication", {}).get("output_root") != str(OUTPUT_ROOT)
        or value.get("pit_contract") != PIT_CONTRACT
    ):
        raise DiagnosticError("entry diagnostic preregistration semantics drift")
    return value


def verify_consumed_predecessor(
    correction_activation: dict[str, Any],
) -> dict[str, str]:
    for path, label in (
        (CORRECTED_PARENT, "corrected parent"),
        (CORRECTED_R4, "corrected R4"),
        (CORRECTED_R5, "corrected unopened R5"),
        (CORRECTED_ATTEMPT, "corrected attempt"),
        (CORRECTED_RESULT, "corrected result"),
    ):
        BASE.reject_symlink_components(path, label)
    parent = CORRECTED_PARENT.lstat()
    r4 = CORRECTED_R4.lstat()
    r5 = CORRECTED_R5.lstat()
    if (
        not stat.S_ISDIR(parent.st_mode)
        or stat.S_IMODE(parent.st_mode) != 0o555
        or not BASE.is_user_immutable(CORRECTED_PARENT)
        or {path.name for path in CORRECTED_PARENT.iterdir()} != {"v29r4", "v29r5"}
        or not stat.S_ISDIR(r4.st_mode)
        or stat.S_IMODE(r4.st_mode) != 0o555
        or not BASE.is_user_immutable(CORRECTED_R4)
        or {path.name for path in CORRECTED_R4.iterdir()} != {"attempt_seal.json", "result.json"}
        or not stat.S_ISDIR(r5.st_mode)
        or stat.S_IMODE(r5.st_mode) != 0o700
        or BASE.is_user_immutable(CORRECTED_R5)
        or any(CORRECTED_R5.iterdir())
    ):
        raise DiagnosticError("consumed correction root or unopened R5 drift")
    _assert_immutable_file(CORRECTED_ATTEMPT, "corrected attempt")
    _assert_immutable_file(CORRECTED_RESULT, "corrected result")
    if (
        sha256(CORRECTED_ATTEMPT) != CORRECTED_ATTEMPT_SHA256
        or sha256(CORRECTED_RESULT) != CORRECTED_RESULT_SHA256
    ):
        raise DiagnosticError("consumed correction hashes drift")
    attempt = load_json(CORRECTED_ATTEMPT, "corrected attempt")
    result = load_json(CORRECTED_RESULT, "corrected result")
    if (
        result.get("experiment") != CORRECTION.CORRECTION_EXPERIMENT
        or result.get("arm") != "v29r4"
        or result.get("aggregate_publication_status") != "BLOCKED"
        or result.get("verdict") != "UNRESOLVED"
        or result.get("blocker") != EXPECTED_BLOCKER
        or result.get("performance_gates_computed") is not False
        or result.get("activation") != correction_activation
        or result.get("attempt_seal_sha256") != CORRECTED_ATTEMPT_SHA256
        or "summary" in result
        or "output_hashes" in result
        or attempt.get("experiment") != CORRECTION.CORRECTION_EXPERIMENT
        or attempt.get("arm") != "v29r4"
        or attempt.get("protocol_arm") != "V29R4_CAP25"
        or attempt.get("runner_sha256") != CORRECTION_RUNNER_SHA256
        or attempt.get("activation_sha256") != BASE.normalized_json_sha256(correction_activation)
        or attempt.get("v29r4_failure_dependency") is not None
        or attempt.get("post_2021_access") != "PROHIBITED"
    ):
        raise DiagnosticError("consumed correction semantics drift")
    return {
        "attempt_seal_sha256": CORRECTED_ATTEMPT_SHA256,
        "blocked_result_sha256": CORRECTED_RESULT_SHA256,
    }


def verify_source_state() -> tuple[dict[str, Any], dict[str, str]]:
    verify_preregistration()
    if sha256(CORRECTION_RUNNER) != CORRECTION_RUNNER_SHA256:
        raise DiagnosticError("calendar-correction runner hash drift")
    correction_activation = CORRECTION.verify_activation()
    predecessor = verify_consumed_predecessor(correction_activation)
    return correction_activation, predecessor


def _verify_wrapper_files() -> tuple[dict[str, Any], dict[str, Any]]:
    for path, label in (
        (WRAPPER_ROOT, "CY-050 wrapper root"),
        (WRAPPER_MANIFEST, "CY-050 manifest"),
        (WRAPPER_AUDIT, "CY-050 activation audit"),
    ):
        BASE.reject_symlink_components(path, label)
    root = WRAPPER_ROOT.lstat()
    if (
        not stat.S_ISDIR(root.st_mode)
        or stat.S_IMODE(root.st_mode) != 0o555
        or not BASE.is_user_immutable(WRAPPER_ROOT)
        or {path.name for path in WRAPPER_ROOT.iterdir()}
        != {"asset_manifest.json", "activation_audit.json"}
    ):
        raise DiagnosticError("CY-050 wrapper root seal drift")
    _assert_immutable_file(WRAPPER_MANIFEST, "CY-050 manifest")
    _assert_immutable_file(WRAPPER_AUDIT, "CY-050 activation audit")
    manifest = load_json(WRAPPER_MANIFEST, "CY-050 manifest")
    audit = load_json(WRAPPER_AUDIT, "CY-050 activation audit")
    protocol = manifest.get("protocol", {})
    builder = Path(str(protocol.get("builder_path", "")))
    expected_assets = {
        "CY-046": {
            "activation_audit_sha256": CORRECTION.BASE_ACTIVATION_AUDIT_SHA256,
            "manifest_sha256": CORRECTION.BASE_MANIFEST_SHA256,
            "root": str(CORRECTION.BASE_ASSET_ROOT),
        },
        "CY-048": {
            "activation_audit_sha256": CORRECTION.sha256(CORRECTION.WRAPPER_AUDIT),
            "manifest_sha256": CORRECTION.sha256(CORRECTION.WRAPPER_MANIFEST),
            "root": str(CORRECTION.WRAPPER_ROOT),
        },
    }
    expected_content = {
        "builder_outcome_or_return_rows_opened": False,
        "builder_parquet_bytes_copied": False,
        "builder_parquet_rows_decoded": False,
        "diagnostic_arm": "V29R4_CAP25_ONLY",
        "diagnostic_maximum_entry_session_offset": 0,
        "diagnostic_outcome_paths_authorized": False,
        "diagnostic_performance_replay_authorized": False,
        "post_2021_rows_authorized": False,
    }
    if (
        set(manifest)
        != {
            "asset_id",
            "authorization_id",
            "content_contract",
            "coverage",
            "kind",
            "pit_contract",
            "predecessor",
            "protocol",
            "referenced_assets",
            "status",
        }
        or manifest.get("asset_id") != ASSET_ID
        or manifest.get("authorization_id") != AUTHORIZATION_ID
        or manifest.get("kind") != "outcome_blind_entry_evidence_diagnostic_reference_wrapper"
        or manifest.get("status") != "PASS"
        or manifest.get("coverage") != {"start": "2018-01-01", "end": "2021-12-31"}
        or manifest.get("pit_contract") != PIT_CONTRACT
        or protocol.get("path") != str(PREREGISTRATION)
        or protocol.get("sha256") != PREREGISTRATION_SHA256
        or protocol.get("runner_path") != str(Path(__file__).resolve())
        or protocol.get("runner_sha256") != sha256(Path(__file__).resolve())
        or not builder.is_file()
        or protocol.get("builder_sha256") != sha256(builder)
        or manifest.get("referenced_assets") != expected_assets
        or manifest.get("predecessor")
        != {
            "attempt_seal_path": str(CORRECTED_ATTEMPT),
            "attempt_seal_sha256": CORRECTED_ATTEMPT_SHA256,
            "blocked_result_path": str(CORRECTED_RESULT),
            "blocked_result_sha256": CORRECTED_RESULT_SHA256,
            "replay_boundary_crossed": True,
        }
        or manifest.get("content_contract") != expected_content
    ):
        raise DiagnosticError("CY-050 manifest semantics drift")
    manifest_sha = sha256(WRAPPER_MANIFEST)
    if (
        set(audit)
        != {
            "asset_id",
            "builder_outcome_or_return_rows_opened",
            "builder_parquet_bytes_copied",
            "builder_parquet_rows_decoded",
            "builder_sha256",
            "gate_pass",
            "manifest_path",
            "manifest_sha256",
            "pit_contract",
            "post_2021_rows_opened",
            "predecessor_attempt_sha256",
            "predecessor_result_sha256",
            "preregistration_sha256",
            "runner_sha256",
            "status",
        }
        or audit.get("asset_id") != ASSET_ID
        or audit.get("status") != "PASS"
        or audit.get("gate_pass") is not True
        or audit.get("manifest_path") != "asset_manifest.json"
        or audit.get("manifest_sha256") != manifest_sha
        or audit.get("builder_sha256") != sha256(builder)
        or audit.get("runner_sha256") != sha256(Path(__file__).resolve())
        or audit.get("preregistration_sha256") != PREREGISTRATION_SHA256
        or audit.get("predecessor_attempt_sha256") != CORRECTED_ATTEMPT_SHA256
        or audit.get("predecessor_result_sha256") != CORRECTED_RESULT_SHA256
        or audit.get("builder_parquet_rows_decoded") is not False
        or audit.get("builder_parquet_bytes_copied") is not False
        or audit.get("builder_outcome_or_return_rows_opened") is not False
        or audit.get("post_2021_rows_opened") is not False
        or audit.get("pit_contract") != PIT_CONTRACT
    ):
        raise DiagnosticError("CY-050 activation audit semantics drift")
    return manifest, audit


def _verify_registry(
    manifest: dict[str, Any], audit: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    registry = load_json(BASE.REGISTRY, "data registry")
    assets = registry.get("assets")
    authorizations = registry.get("bounded_authorizations")
    if not isinstance(assets, list) or not isinstance(authorizations, list):
        raise DiagnosticError("registry lacks assets or bounded authorizations")
    asset = _only(
        (item for item in assets if item.get("asset_id") == ASSET_ID),
        "CY-050 registry asset",
    )
    authorization = _only(
        (item for item in authorizations if item.get("authorization_id") == AUTHORIZATION_ID),
        "CY-050 bounded authorization",
    )
    coverage = asset.get("coverage", {})
    lineage = asset.get("lineage", {})
    manifest_sha = sha256(WRAPPER_MANIFEST)
    audit_sha = sha256(WRAPPER_AUDIT)
    if (
        asset.get("kind") != "outcome_blind_entry_evidence_diagnostic_reference_wrapper"
        or asset.get("status") != "RESEARCH_CONDITIONAL"
        or asset.get("pit_grade") != "B"
        or asset.get("physical_state") != "MATERIALIZED"
        or Path(str(asset.get("location", ""))) != WRAPPER_ROOT
        or coverage.get("authorized_start") != "2018-01-01"
        or coverage.get("authorized_end") != "2021-12-31"
        or coverage.get("v29r4_candidates") != 251
        or coverage.get("maximum_entry_session_offset") != 0
        or lineage.get("record_available_at") is not True
        or lineage.get("record_snapshot_id") is not True
        or lineage.get("immutable_manifest") is not True
        or lineage.get("manifest_path") != str(WRAPPER_MANIFEST)
        or lineage.get("manifest_sha256") != manifest_sha
        or lineage.get("component_assets") != ["CY-046", "CY-048"]
        or lineage.get("bounded_authorization_id") != AUTHORIZATION_ID
    ):
        raise DiagnosticError("CY-050 registry asset semantics drift")
    artifacts = authorization.get("bound_artifacts")
    if not isinstance(artifacts, list):
        raise DiagnosticError("CY-050 authorization lacks bound artifacts")
    by_role = {
        item.get("role"): item
        for item in artifacts
        if isinstance(item, dict) and isinstance(item.get("role"), str)
    }
    builder = Path(str(manifest.get("protocol", {}).get("builder_path", "")))
    expected_artifacts = {
        "activation_audit": (WRAPPER_AUDIT, audit_sha),
        "reference_wrapper_builder": (builder, sha256(builder)),
        "predecessor_blocked_result": (CORRECTED_RESULT, CORRECTED_RESULT_SHA256),
        "predecessor_attempt_seal": (CORRECTED_ATTEMPT, CORRECTED_ATTEMPT_SHA256),
        "calendar_correction_runner": (CORRECTION_RUNNER, CORRECTION_RUNNER_SHA256),
    }
    artifacts_valid = bool(
        len(artifacts) == len(expected_artifacts)
        and set(by_role) == set(expected_artifacts)
        and all(
            by_role[role].get("path") == str(path) and by_role[role].get("sha256") == digest
            for role, (path, digest) in expected_artifacts.items()
        )
    )
    scope = authorization.get("scope", {})
    protocol = authorization.get("bound_protocol", {})
    strategy = authorization.get("bound_strategy", {})
    if (
        authorization.get("asset_id") != ASSET_ID
        or authorization.get("source_asset_id") != "CY-046"
        or authorization.get("dependency_asset_id") != "CY-046"
        or authorization.get("dependency_status") != "RESEARCH_CONDITIONAL"
        or authorization.get("purpose") != "ASHARE_OUTCOME_BLIND_MOTHER_REPRESENTATION"
        or scope.get("start") != "2018-01-01"
        or scope.get("end") != "2021-12-31"
        or scope.get("frozen_candidate_rows") != 251
        or scope.get("maximum_entry_session_offset") != 0
        or authorization.get("bound_manifest")
        != {"path": str(WRAPPER_MANIFEST), "sha256": manifest_sha}
        or protocol
        != {
            "path": str(PREREGISTRATION),
            "sha256": PREREGISTRATION_SHA256,
            "runner_path": str(Path(__file__).resolve()),
            "runner_sha256": sha256(Path(__file__).resolve()),
        }
        or strategy != {"path": str(PREREGISTRATION), "sha256": PREREGISTRATION_SHA256}
        or authorization.get("diagnostic_only") is not True
        or authorization.get("v29r4_only") is not True
        or authorization.get("single_attempt_no_retry") is not True
        or authorization.get("entry_offsets_authorized") != [-1, 0]
        or authorization.get("execution_window_indices_authorized") != [0]
        or authorization.get("candidate_outcome_paths_authorized") is not False
        or authorization.get("portfolio_replay_authorized") is not False
        or authorization.get("returns_authorized") is not False
        or authorization.get("charts_authorized") is not False
        or authorization.get("validation_authorized") is not False
        or authorization.get("post_2021_read_authorized") is not False
        or authorization.get("candidate_reselection_authorized") is not False
        or authorization.get("threshold_selection_authorized") is not False
        or authorization.get("publication_allowed") is not False
        or authorization.get("current_survivor_fallback_allowed") is not False
        or authorization.get("record_level_available_at_available") is not False
        or not artifacts_valid
    ):
        raise DiagnosticError("CY-050 bounded authorization semantics drift")
    return asset, authorization


def verify_activation() -> dict[str, Any]:
    correction_activation, predecessor = verify_source_state()
    manifest, audit = _verify_wrapper_files()
    asset, authorization = _verify_registry(manifest, audit)
    result = dict(correction_activation)
    result.update(
        {
            "mode": "OUTCOME_BLIND_ENTRY_EVIDENCE_DIAGNOSTIC",
            "experiment": EXPERIMENT,
            "protocol_version": PROTOCOL_VERSION,
            "runner_sha256": sha256(Path(__file__).resolve()),
            "preregistration_sha256": PREREGISTRATION_SHA256,
            "base_correction_activation_sha256": BASE.normalized_json_sha256(correction_activation),
            "base_correction_runner_sha256": CORRECTION_RUNNER_SHA256,
            "base_registry_asset_normalized_sha256": correction_activation[
                "registry_asset_normalized_sha256"
            ],
            "base_registry_authorization_normalized_sha256": correction_activation[
                "registry_authorization_normalized_sha256"
            ],
            "manifest_sha256": sha256(WRAPPER_MANIFEST),
            "activation_audit_sha256": sha256(WRAPPER_AUDIT),
            "registry_asset_normalized_sha256": BASE.normalized_json_sha256(asset),
            "registry_authorization_normalized_sha256": BASE.normalized_json_sha256(authorization),
            "reference_wrapper_asset_id": ASSET_ID,
            "predecessor_blocked_attempt": predecessor,
            "candidate_outcome_paths_authorized": False,
            "performance_replay_authorized": False,
            "post_2021_access": "PROHIBITED",
            "pit_contract": PIT_CONTRACT,
        }
    )
    return result


def _truth(value: Any) -> bool:
    return bool(pd.notna(value) and bool(value))


def _nonempty(value: Any) -> bool:
    return bool(pd.notna(value) and str(value).strip())


def _canonical_tick(value: Any, label: str) -> bool:
    try:
        BASE.observed_price_tick(value, label)
    except BASE.StageBError:
        return False
    return True


def _local_naive_timestamp(value: Any) -> pd.Timestamp:
    result = pd.Timestamp(value)
    if pd.isna(result):
        return pd.NaT
    if result.tzinfo is not None:
        result = result.tz_convert("Asia/Shanghai").tz_localize(None)
    return result


def _diagnostic_candidate_join(alias: str) -> str:
    return " AND ".join(
        (
            f"{alias}.protocol_arm=b.protocol_arm",
            f"{alias}.gap_id=b.gap_id",
            f"{alias}.symbol=b.symbol",
            f"{alias}.signal_date=b.signal_date",
            f"{alias}.entry_date=b.entry_date",
        )
    )


def _load_diagnostic_entry_inputs(
    eligible: pd.DataFrame, protocol_arm: str
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Decode only fields needed at or before the fixed entry observation."""
    bounds = eligible[["gap_id", "symbol", "signal_date", "entry_date"]].copy()
    bounds.insert(0, "protocol_arm", protocol_arm)
    with duckdb.connect() as con:
        con.register("candidate_bounds", bounds)
        daily_projection = ",".join(f'd."{column}"' for column in DIAGNOSTIC_DAILY_COLUMNS)
        execution_projection = ",".join(f'e."{column}"' for column in DIAGNOSTIC_EXECUTION_COLUMNS)
        action_projection = ",".join(f'a."{column}"' for column in BASE.ACTION_COLUMNS)
        daily = con.execute(
            f"""
            SELECT {daily_projection}
            FROM read_parquet(?) d JOIN candidate_bounds b
              ON {_diagnostic_candidate_join("d")}
            WHERE d.entry_session_offset IN (-1,0)
              AND d.trade_date BETWEEN DATE '2018-01-01' AND DATE '2021-12-31'
            """,
            [str(BASE.DAILY_TARGET_PATH)],
        ).fetchdf()
        execution = con.execute(
            f"""
            SELECT {execution_projection}
            FROM read_parquet(?) e JOIN candidate_bounds b
              ON {_diagnostic_candidate_join("e")}
            WHERE e.entry_session_offset=0 AND e.window_index=0
              AND e.trade_date BETWEEN DATE '2018-01-01' AND DATE '2021-12-31'
            """,
            [str(BASE.EXECUTION_WINDOW0)],
        ).fetchdf()
        actions = con.execute(
            f"""
            SELECT {action_projection}
            FROM read_parquet(?) a JOIN candidate_bounds b
              ON {_diagnostic_candidate_join("a")}
            WHERE a.known_at<=CAST(a.entry_date AS TIMESTAMP)
                    +INTERVAL 9 HOUR+INTERVAL 35 MINUTE
              AND a.available_at<=CAST(a.entry_date AS TIMESTAMP)
                    +INTERVAL 9 HOUR+INTERVAL 35 MINUTE
              AND (a.effective_date IS NULL OR
                   (a.effective_date>a.signal_date AND a.effective_date<=a.h23_date))
            """,
            [str(BASE.ACTION_EVENTS)],
        ).fetchdf()
    return daily, execution, actions


def _integer_equals(value: Any, expected: int) -> bool:
    numeric = pd.to_numeric(value, errors="coerce")
    return bool(pd.notna(numeric) and float(numeric).is_integer() and int(numeric) == expected)


def _signal_binding_valid(candidate: Any, row: pd.Series | None) -> bool:
    if row is None:
        return False
    available = _local_naive_timestamp(row.get("available_at"))
    decision = _local_naive_timestamp(row.get("decision_at"))
    required_true = (
        row.get("hard_valid"),
        row.get("market_rule_valid"),
        row.get("corporate_action_valid"),
        row.get("current_day_data_tradable"),
    )
    return bool(
        str(row.get("snapshot_id")) == str(candidate.signal_snapshot_id)
        and str(row.get("daily_snapshot_id")) == str(candidate.signal_daily_snapshot_id)
        and str(row.get("corporate_action_snapshot_id"))
        == str(candidate.signal_corporate_action_snapshot_id)
        and _local_naive_timestamp(row.get("trade_date")).normalize()
        == _local_naive_timestamp(candidate.signal_date).normalize()
        and pd.notna(decision)
        and pd.notna(available)
        and available <= decision
        and available <= _local_naive_timestamp(candidate.signal_time)
        and all(_truth(value) for value in required_true)
        and pd.notna(row.get("corporate_action_blocking"))
        and not bool(row.get("corporate_action_blocking"))
        and _integer_equals(row.get("trade_status"), 1)
    )


def _entry_binding_valid(candidate: Any, row: pd.Series | None) -> bool:
    if row is None:
        return False
    available = _local_naive_timestamp(row.get("available_at"))
    decision = _local_naive_timestamp(row.get("decision_at"))
    return bool(
        _local_naive_timestamp(row.get("trade_date")).normalize()
        == _local_naive_timestamp(candidate.entry_date).normalize()
        and pd.notna(row.get("corporate_action_count"))
        and pd.notna(decision)
        and pd.notna(available)
        and available <= decision
        and _nonempty(row.get("snapshot_id"))
        and _nonempty(row.get("corporate_action_snapshot_id"))
    )


def diagnose_entry_evidence(
    candidates: pd.DataFrame,
    daily: pd.DataFrame,
    execution: pd.DataFrame,
    actions: pd.DataFrame,
) -> dict[str, Any]:
    """Publish only conserved aggregate categories and tri-state masks."""
    normalized_actions = BASE.normalize_actions(actions)
    daily = daily.copy()
    execution = execution.copy()
    for column in ("trade_date", "decision_at", "available_at"):
        daily[column] = pd.to_datetime(daily[column])
    for column in ("trade_date", "available_at"):
        execution[column] = pd.to_datetime(execution[column])
    daily_groups = {
        (str(arm), str(gap), str(symbol)): part
        for (arm, gap, symbol), part in daily.groupby(
            ["protocol_arm", "gap_id", "symbol"], sort=False
        )
    }
    execution_groups = {
        (str(arm), str(gap), str(symbol)): part
        for (arm, gap, symbol), part in execution.groupby(
            ["protocol_arm", "gap_id", "symbol"], sort=False
        )
    }
    action_groups = {
        (str(arm), str(gap), str(symbol)): part
        for (arm, gap, symbol), part in normalized_actions.groupby(
            ["protocol_arm", "gap_id", "symbol"], sort=False
        )
    }
    classifications: Counter[str] = Counter()
    mask_states = {name: Counter() for name in INDEPENDENT_MASKS}
    censored = 0
    for candidate in candidates.itertuples(index=False):
        if bool(candidate.administratively_censored):
            censored += 1
            continue
        states: dict[str, bool | None] = dict.fromkeys(INDEPENDENT_MASKS)
        key = ("V29R4_CAP25", str(candidate.gap_id), str(candidate.symbol))
        dpart = daily_groups.get(key, daily.iloc[0:0])
        epart = execution_groups.get(key, execution.iloc[0:0])
        events = action_groups.get(key, normalized_actions.iloc[0:0])

        numeric_offsets = pd.to_numeric(dpart.get("entry_session_offset"), errors="coerce")
        daily_exact = bool(
            len(dpart) == 2
            and numeric_offsets.notna().all()
            and numeric_offsets.mod(1).eq(0).all()
            and set(numeric_offsets.astype(int).tolist()) == {-1, 0}
        )
        signal_daily = dpart.loc[numeric_offsets.eq(-1)].iloc[0] if daily_exact else None
        entry_daily = dpart.loc[numeric_offsets.eq(0)].iloc[0] if daily_exact else None
        execution_exact = bool(
            len(epart) == 1
            and _integer_equals(epart.iloc[0].get("entry_session_offset"), 0)
            and _integer_equals(epart.iloc[0].get("window_index"), 0)
            and _local_naive_timestamp(epart.iloc[0].get("trade_date")).normalize()
            == _local_naive_timestamp(candidate.entry_date).normalize()
        )
        execution_row = epart.iloc[0] if execution_exact else None
        states["EXECUTION_CARDINALITY_OR_DATE"] = not execution_exact
        fixed_observation = _local_naive_timestamp(candidate.entry_date).normalize() + pd.Timedelta(
            hours=9, minutes=35
        )

        raw_l_canonical = False
        try:
            raw_l = BASE.positive_decimal(candidate.L, "diagnostic L") / BASE.positive_decimal(
                candidate.coordinate_factor, "diagnostic coordinate factor"
            )
            raw_l_canonical = _canonical_tick(raw_l, "diagnostic raw L")
        except BASE.StageBError:
            raw_l_canonical = False
        states["RAW_L_COORDINATE_NONCANONICAL"] = not raw_l_canonical

        action_reconciles = False
        entry_daily_state: str | None = None
        temporal_failure: bool | None = None
        if entry_daily is not None:
            entry_available = _local_naive_timestamp(entry_daily.get("available_at"))
            entry_decision = _local_naive_timestamp(entry_daily.get("decision_at"))
            available_after = (
                None if pd.isna(entry_available) else bool(entry_available > fixed_observation)
            )
            decision_after = (
                None if pd.isna(entry_decision) else bool(entry_decision > fixed_observation)
            )
            states["ENTRY_DAILY_AVAILABLE_AFTER_EXECUTION_OBSERVATION"] = available_after
            states["ENTRY_DAILY_DECISION_AFTER_EXECUTION_OBSERVATION"] = decision_after
            if available_after is True or decision_after is True:
                temporal_failure = True
            elif available_after is False and decision_after is False:
                temporal_failure = False
            try:
                BASE._reconcile_action_day(entry_daily, events)
                action_reconciles = True
                states["ACTION_COUNT_OR_TERMS_MISMATCH"] = False
            except BASE.StageBError:
                states["ACTION_COUNT_OR_TERMS_MISMATCH"] = True
            entry_daily_state = BASE._daily_state(entry_daily, events)
            states["ENTRY_DAILY_STATE_UNRESOLVED"] = entry_daily_state == "UNRESOLVED_DATA_QUALITY"

        ticks: dict[str, int] = {}
        execution_complete: bool | None = None
        snapshot_mismatch: bool | None = None
        limit_geometry_invalid: bool | None = None
        if execution_row is not None:
            observed_available = _local_naive_timestamp(execution_row.get("available_at"))
            available_invalid = bool(
                pd.isna(observed_available) or observed_available != fixed_observation
            )
            minute_shape_invalid = not bool(
                _integer_equals(execution_row.get("source_resolution_minutes"), 1)
                and _integer_equals(execution_row.get("minute_count"), 5)
                and _integer_equals(execution_row.get("distinct_minute_count"), 5)
            )
            validity_flags_invalid = not all(
                _truth(execution_row.get(name))
                for name in (
                    "ohlc_valid",
                    "unit_valid",
                    "causal_inputs_valid",
                    "market_rule_valid",
                    "hard_valid",
                )
            )
            trade_status_invalid = not _integer_equals(execution_row.get("trade_status"), 1)
            snapshot_missing = not _nonempty(execution_row.get("snapshot_id"))
            daily_snapshot_missing = not _nonempty(execution_row.get("daily_snapshot_id"))
            states["EXECUTION_AVAILABLE_AT_MISSING_OR_MISMATCH"] = available_invalid
            states["EXECUTION_MINUTE_SHAPE_OR_RESOLUTION_INVALID"] = minute_shape_invalid
            states["EXECUTION_VALIDITY_FLAGS_INVALID"] = validity_flags_invalid
            states["EXECUTION_TRADE_STATUS_INVALID"] = trade_status_invalid
            states["EXECUTION_SNAPSHOT_ID_MISSING"] = snapshot_missing
            states["EXECUTION_DAILY_SNAPSHOT_ID_MISSING"] = daily_snapshot_missing
            execution_complete = not any(
                (
                    available_invalid,
                    minute_shape_invalid,
                    validity_flags_invalid,
                    trade_status_invalid,
                    snapshot_missing,
                    daily_snapshot_missing,
                )
            )
            states["EXECUTION_TIMING_OR_COMPLETENESS"] = not execution_complete
            for field, mask in (
                ("open", "ENTRY_OPEN_NONCANONICAL"),
                ("up_limit_price", "UP_LIMIT_NONCANONICAL"),
                ("down_limit_price", "DOWN_LIMIT_NONCANONICAL"),
            ):
                canonical = _canonical_tick(execution_row.get(field), f"diagnostic {field}")
                states[mask] = not canonical
                if canonical:
                    ticks[field] = BASE.observed_price_tick(
                        execution_row.get(field), f"diagnostic {field}"
                    )
            if entry_daily is not None:
                execution_daily_snapshot = execution_row.get("daily_snapshot_id")
                entry_snapshot = entry_daily.get("snapshot_id")
                if _nonempty(execution_daily_snapshot) and _nonempty(entry_snapshot):
                    snapshot_mismatch = str(execution_daily_snapshot) != str(entry_snapshot)
                    states["EXECUTION_SNAPSHOT_BINDING_MISMATCH"] = snapshot_mismatch
                    if not snapshot_mismatch:
                        states["EXECUTION_DAILY_CONTEXT_AVAILABLE_AFTER_EXECUTION_OBSERVATION"] = (
                            temporal_failure
                        )
            if len(ticks) == 3:
                limit_geometry_invalid = bool(
                    ticks["down_limit_price"] >= ticks["up_limit_price"]
                    or not (ticks["down_limit_price"] <= ticks["open"] <= ticks["up_limit_price"])
                )
                states["LIMIT_GEOMETRY_INVALID"] = limit_geometry_invalid

        signal_binding = _signal_binding_valid(candidate, signal_daily)
        entry_binding = _entry_binding_valid(candidate, entry_daily)
        effective_between = False
        pending_risk = False
        if daily_exact and action_reconciles and not events.empty:
            effective_between = bool(
                events.effective_date.dt.normalize()
                .gt(_local_naive_timestamp(candidate.signal_date).normalize())
                .mul(
                    events.effective_date.dt.normalize().le(
                        _local_naive_timestamp(candidate.entry_date).normalize()
                    )
                )
                .any()
            )
        if (
            execution_row is not None
            and execution_complete is True
            and snapshot_mismatch is False
            and not events.empty
        ):
            observed_at = _local_naive_timestamp(execution_row.get("available_at"))
            last_exit = _local_naive_timestamp(
                getattr(candidate, "last_exit_date", candidate.entry_date)
            ).normalize()
            pending_risk = bool(
                events.action_kind.isin(["RISK_SHARE", "RISK_RIGHTS"])
                .mul(events.known_at.le(observed_at))
                .mul(events.available_at.le(observed_at))
                .mul(events.effective_date.dt.normalize().le(last_exit))
                .any()
            )
        if not daily_exact or not signal_binding or not entry_binding:
            base_entry_unresolved = True
        elif not action_reconciles:
            base_entry_unresolved = True
        elif effective_between:
            base_entry_unresolved = False
        elif entry_daily_state == "UNRESOLVED_DATA_QUALITY":
            base_entry_unresolved = True
        elif entry_daily_state == "KNOWN_NOT_TRADED":
            base_entry_unresolved = False
        elif not execution_exact or execution_complete is not True:
            base_entry_unresolved = True
        elif snapshot_mismatch is not False:
            base_entry_unresolved = True
        elif pending_risk:
            base_entry_unresolved = False
        elif len(ticks) != 3 or not raw_l_canonical:
            base_entry_unresolved = True
        elif limit_geometry_invalid is not False:
            base_entry_unresolved = True
        else:
            base_entry_unresolved = False
        states["BASE_ENTRY_UNRESOLVED"] = base_entry_unresolved

        for name, state in states.items():
            label = "unknown" if state is None else "true" if state else "false"
            mask_states[name][label] += 1

        if not daily_exact:
            classifications["DAILY_CARDINALITY_OR_OFFSETS"] += 1
            continue
        assert signal_daily is not None and entry_daily is not None
        if not signal_binding:
            classifications["SIGNAL_BINDING_OR_LINEAGE"] += 1
            continue
        if not entry_binding:
            classifications["ENTRY_BINDING_OR_LINEAGE"] += 1
            continue
        if temporal_failure:
            classifications["ENTRY_DAILY_CONTEXT_AFTER_EXECUTION_OBSERVATION"] += 1
            continue
        if not action_reconciles:
            classifications["ACTION_RECONCILIATION"] += 1
            continue
        if effective_between:
            classifications["RESOLVED_MECHANICAL_NO_ENTRY"] += 1
            continue
        if entry_daily_state == "UNRESOLVED_DATA_QUALITY":
            classifications["ENTRY_DAILY_STATE"] += 1
            continue
        if entry_daily_state == "KNOWN_NOT_TRADED":
            classifications["RESOLVED_MECHANICAL_NO_ENTRY"] += 1
            continue
        if not execution_exact:
            classifications["EXECUTION_CARDINALITY_OR_DATE"] += 1
            continue
        assert execution_row is not None
        if execution_complete is not True:
            classifications["EXECUTION_TIMING_OR_COMPLETENESS"] += 1
            continue
        if snapshot_mismatch is not False:
            classifications["EXECUTION_SNAPSHOT_BINDING"] += 1
            continue
        if pending_risk:
            classifications["RESOLVED_MECHANICAL_NO_ENTRY"] += 1
            continue
        if len(ticks) != 3:
            classifications["ENTRY_PRICE_NONCANONICAL"] += 1
            continue
        if not raw_l_canonical:
            classifications["RAW_L_COORDINATE_NONCANONICAL"] += 1
            continue
        if limit_geometry_invalid is not False:
            classifications["LIMIT_GEOMETRY_INVALID"] += 1
            continue
        if ticks["open"] == ticks["up_limit_price"]:
            classifications["RESOLVED_MECHANICAL_NO_ENTRY"] += 1
            continue
        classifications["RESOLVED_ENTRY_EVIDENCE"] += 1

    eligible = len(candidates) - censored
    first_failure_counts = {name: int(classifications[name]) for name in FIRST_FAILURES}
    mask_counts: dict[str, dict[str, int]] = {}
    for name, counts in mask_states.items():
        true_count = int(counts["true"])
        false_count = int(counts["false"])
        unknown_count = int(counts["unknown"])
        if true_count + false_count + unknown_count != eligible:
            raise DiagnosticError(f"entry diagnostic mask conservation failure: {name}")
        mask_counts[name] = {
            "true": true_count,
            "false": false_count,
            "unknown": unknown_count,
            "evaluated": true_count + false_count,
        }
    if len(candidates) != censored + sum(first_failure_counts.values()):
        raise DiagnosticError("entry diagnostic candidate conservation failure")
    unresolved_first_failure_total = sum(
        count
        for name, count in first_failure_counts.items()
        if name not in {"RESOLVED_MECHANICAL_NO_ENTRY", "RESOLVED_ENTRY_EVIDENCE"}
    )

    def has_true(*names: str) -> bool:
        return any(mask_counts[name]["true"] > 0 for name in names)

    causal_adapter_required = has_true(
        "ENTRY_DAILY_AVAILABLE_AFTER_EXECUTION_OBSERVATION",
        "ENTRY_DAILY_DECISION_AFTER_EXECUTION_OBSERVATION",
        "EXECUTION_DAILY_CONTEXT_AVAILABLE_AFTER_EXECUTION_OBSERVATION",
    )
    raw_l_tick_regeneration_required = has_true("RAW_L_COORDINATE_NONCANONICAL")
    execution_evidence_rebuild_required = has_true(
        "EXECUTION_CARDINALITY_OR_DATE",
        "EXECUTION_AVAILABLE_AT_MISSING_OR_MISMATCH",
        "EXECUTION_MINUTE_SHAPE_OR_RESOLUTION_INVALID",
        "EXECUTION_VALIDITY_FLAGS_INVALID",
        "EXECUTION_TRADE_STATUS_INVALID",
        "EXECUTION_SNAPSHOT_ID_MISSING",
        "EXECUTION_DAILY_SNAPSHOT_ID_MISSING",
        "EXECUTION_SNAPSHOT_BINDING_MISMATCH",
    )
    price_limit_evidence_repair_required = has_true(
        "ENTRY_OPEN_NONCANONICAL",
        "UP_LIMIT_NONCANONICAL",
        "DOWN_LIMIT_NONCANONICAL",
        "LIMIT_GEOMETRY_INVALID",
    )
    upstream_lineage_repair_required = bool(
        first_failure_counts["DAILY_CARDINALITY_OR_OFFSETS"]
        + first_failure_counts["SIGNAL_BINDING_OR_LINEAGE"]
        + first_failure_counts["ENTRY_BINDING_OR_LINEAGE"]
        + first_failure_counts["ACTION_RECONCILIATION"]
        + first_failure_counts["ENTRY_DAILY_STATE"]
        or has_true(
            "ACTION_COUNT_OR_TERMS_MISMATCH",
            "ENTRY_DAILY_STATE_UNRESOLVED",
        )
    )
    repair_flags = (
        causal_adapter_required,
        raw_l_tick_regeneration_required,
        execution_evidence_rebuild_required,
        price_limit_evidence_repair_required,
        upstream_lineage_repair_required,
    )
    repair_directive = {
        "causal_adapter_required": causal_adapter_required,
        "raw_l_tick_regeneration_required": raw_l_tick_regeneration_required,
        "execution_evidence_rebuild_required": execution_evidence_rebuild_required,
        "price_limit_evidence_repair_required": (price_limit_evidence_repair_required),
        "upstream_lineage_repair_required": upstream_lineage_repair_required,
        "combined_rebuild_required": sum(repair_flags) > 1,
        "classifier_parity_failure": mask_counts["BASE_ENTRY_UNRESOLVED"]["true"] == 0,
        "performance_run_authorized": False,
    }
    return {
        "total_candidates": len(candidates),
        "administratively_censored": int(censored),
        "administratively_eligible": int(eligible),
        "first_failure_counts": first_failure_counts,
        "independent_static_mask_counts": mask_counts,
        "unresolved_first_failure_total": int(unresolved_first_failure_total),
        "repair_directive": repair_directive,
        "candidate_conservation_passed": True,
        "mask_conservation_passed": True,
    }


def _initialize_output() -> None:
    parent = BASE.reject_symlink_components(OUTPUT_ROOT.parent, "diagnostic output parent")
    if not stat.S_ISDIR(parent.lstat().st_mode):
        raise DiagnosticError("diagnostic output parent is not a directory")
    if not BASE.path_lexists(OUTPUT_ROOT):
        staged = OUTPUT_ROOT.with_name(
            f".{OUTPUT_ROOT.name}.anchor-{os.getpid()}-{uuid.uuid4().hex}"
        )
        try:
            staged.mkdir(mode=0o700)
            (staged / "diagnostic").mkdir(mode=0o700)
            os.chmod(staged, 0o555)
            BASE.publish_directory_no_replace(staged, OUTPUT_ROOT)
            BASE.set_user_immutable(OUTPUT_ROOT)
            BASE.fsync_directory(parent)
        except Exception:
            if staged.exists():
                shutil.rmtree(staged)
            raise
    root = BASE.reject_symlink_components(OUTPUT_ROOT, "diagnostic output root")
    if (
        not stat.S_ISDIR(root.lstat().st_mode)
        or stat.S_IMODE(root.lstat().st_mode) != 0o555
        or not BASE.is_user_immutable(root)
        or {path.name for path in root.iterdir()} != {"diagnostic"}
    ):
        raise DiagnosticError("diagnostic output anchor drift")
    slot = BASE.reject_symlink_components(SLOT, "diagnostic output slot")
    if (
        not stat.S_ISDIR(slot.lstat().st_mode)
        or BASE.is_user_immutable(slot)
        or stat.S_IMODE(slot.lstat().st_mode) != 0o700
    ):
        raise DiagnosticError("diagnostic output slot is not pristine mutable 0700")


def _publish_attempt(activation: dict[str, Any]) -> Path:
    _initialize_output()
    if any(SLOT.iterdir()):
        raise DiagnosticError("entry diagnostic attempt already consumed")
    BASE.preflight_slot_capabilities(SLOT)
    path = SLOT / "attempt_seal.json"
    payload = {
        "experiment": EXPERIMENT,
        "protocol_version": PROTOCOL_VERSION,
        "status": "ATTEMPT_OPENED_BEFORE_ANY_CY046_PARQUET_ROW",
        "runner_sha256": activation["runner_sha256"],
        "preregistration_sha256": activation["preregistration_sha256"],
        "manifest_sha256": activation["manifest_sha256"],
        "activation_audit_sha256": activation["activation_audit_sha256"],
        "activation_sha256": BASE.normalized_json_sha256(activation),
        "source_arm": "V29R4_CAP25",
        "maximum_entry_session_offset": 0,
        "candidate_outcome_paths_authorized": False,
        "post_2021_access": "PROHIBITED",
    }
    encoded = (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(
        "utf-8"
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        written = 0
        while written < len(encoded):
            count = os.write(descriptor, encoded[written:])
            if count <= 0:
                raise DiagnosticError("short write while publishing diagnostic attempt")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.chmod(path, 0o444)
    BASE.set_user_immutable(path)
    if path.read_bytes() != encoded:
        raise DiagnosticError("diagnostic attempt seal readback mismatch")
    BASE.fsync_directory(SLOT)
    return path


def _write_terminal(payload: dict[str, Any], attempt: Path) -> dict[str, Any]:
    if (
        {path.name for path in SLOT.iterdir()} != {"attempt_seal.json"}
        or attempt != SLOT / "attempt_seal.json"
        or not BASE.is_user_immutable(attempt)
    ):
        raise DiagnosticError("diagnostic slot is not one consumed attempt")
    temporary = Path(tempfile.mkdtemp(prefix=".terminal-", dir=SLOT))
    try:
        result_path = temporary / "result.json"
        BASE.write_json(result_path, payload)
        os.chmod(result_path, 0o444)
        BASE.fsync_directory(temporary)
        BASE.publish_no_replace(result_path, SLOT / "result.json")
        temporary.rmdir()
        BASE.fsync_directory(SLOT)
        BASE.freeze_published_tree(SLOT, {"attempt_seal.json", "result.json"})
        BASE.fsync_directory(OUTPUT_ROOT)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return payload


def run_diagnostic() -> dict[str, Any]:
    activation = verify_activation()
    attempt = _publish_attempt(activation)
    stage = "ATTEMPT_SEALED"
    row_scope_audit: dict[str, Any] = {
        "complete": False,
        "source_row_counts": None,
        "maximum_daily_entry_session_offset_opened": None,
        "maximum_execution_entry_session_offset_opened": None,
        "post_2021_rows_opened": None,
    }
    try:
        config = BASE.ARM_CONFIG["v29r4"]
        candidates = BASE.normalize_candidates(
            BASE._projected_read(config["identity"], BASE.IDENTITY_COLUMNS),
            expected_rows=251,
            expected_by_year={2018: 178, 2019: 25, 2020: 12, 2021: 36},
        )
        if candidates.protocol_arm.ne("V29R4_CAP25").any():
            raise DiagnosticError("frozen diagnostic arm identity drift")
        stage = "IDENTITY_OPENED"
        raw_calendar = BASE._projected_read(BASE.MARKET_CALENDAR, BASE.CALENDAR_COLUMNS)
        candidates = BASE.administrative_censor(candidates, raw_calendar)
        if candidates.admin_status.eq("UNRESOLVED_SIGNAL_CALENDAR").any():
            raise DiagnosticError("candidate signal is absent from frozen calendar")
        admin = BASE._read_arm_rows(BASE.ADMIN_BOUNDS, BASE.ADMIN_BOUND_COLUMNS, "V29R4_CAP25")
        BASE.verify_admin_bounds(candidates, admin, raw_calendar, "V29R4_CAP25")
        stage = "ADMIN_BOUNDS_VERIFIED"
        eligible = candidates.loc[~candidates.administratively_censored].copy()
        daily, execution, actions = _load_diagnostic_entry_inputs(eligible, "V29R4_CAP25")
        stage = "ENTRY_INPUTS_OPENED"
        daily_offsets = set(
            pd.to_numeric(daily.entry_session_offset, errors="coerce").dropna().astype(int).tolist()
        )
        execution_offsets = set(
            pd.to_numeric(execution.entry_session_offset, errors="coerce")
            .dropna()
            .astype(int)
            .tolist()
        )
        post_2021_rows = int(
            pd.to_datetime(daily.trade_date).dt.normalize().gt(BASE.END).sum()
            + pd.to_datetime(execution.trade_date).dt.normalize().gt(BASE.END).sum()
            + pd.to_datetime(actions.effective_date, errors="coerce")
            .dt.normalize()
            .gt(BASE.END)
            .sum()
        )
        row_scope_audit = {
            "complete": True,
            "source_row_counts": {
                "identity": len(candidates),
                "market_calendar": len(raw_calendar),
                "administrative_bounds": len(admin),
                "daily_signal_and_entry": len(daily),
                "execution_entry_window0": len(execution),
                "entry_known_actions": len(actions),
            },
            "maximum_daily_entry_session_offset_opened": max(daily_offsets, default=None),
            "maximum_execution_entry_session_offset_opened": max(execution_offsets, default=None),
            "post_2021_rows_opened": post_2021_rows,
        }
        if not daily_offsets.issubset({-1, 0}) or not execution_offsets.issubset({0}):
            raise DiagnosticError("diagnostic loader crossed the entry-only offset boundary")
        if post_2021_rows:
            raise DiagnosticError("post-2021 row reached entry diagnostic")
        diagnosis = diagnose_entry_evidence(candidates, daily, execution, actions)
        stage = "ENTRY_DIAGNOSIS_COMPLETE"
        result = {
            "experiment": EXPERIMENT,
            "aggregate_publication_status": "COMPLETE_DIAGNOSTIC",
            "verdict": "ENTRY_EVIDENCE_DIAGNOSED_NOT_PERFORMANCE",
            "activation": activation,
            "attempt_seal_sha256": sha256(attempt),
            "diagnosis": diagnosis,
            "row_scope_audit_complete": row_scope_audit["complete"],
            "source_row_counts": row_scope_audit["source_row_counts"],
            "maximum_daily_entry_session_offset_opened": row_scope_audit[
                "maximum_daily_entry_session_offset_opened"
            ],
            "maximum_execution_entry_session_offset_opened": row_scope_audit[
                "maximum_execution_entry_session_offset_opened"
            ],
            "candidate_outcome_paths_opened": 0,
            "outcomes_computed": 0,
            "return_columns_opened": [],
            "portfolio_replay_run": False,
            "performance_gates_computed": False,
            "charts_run": False,
            "post_2021_rows_opened": row_scope_audit["post_2021_rows_opened"],
            "pit_contract": PIT_CONTRACT,
        }
        return _write_terminal(result, attempt)
    except Exception as exc:
        blocked = {
            "experiment": EXPERIMENT,
            "aggregate_publication_status": "BLOCKED",
            "verdict": "UNRESOLVED",
            "blocker_code": "FAIL_CLOSED_ENTRY_DIAGNOSTIC_ABORT",
            "error_class": type(exc).__name__,
            "stage": stage,
            "activation": activation,
            "attempt_seal_sha256": sha256(attempt),
            "row_scope_audit_complete": row_scope_audit["complete"],
            "source_row_counts": row_scope_audit["source_row_counts"],
            "maximum_daily_entry_session_offset_opened": row_scope_audit[
                "maximum_daily_entry_session_offset_opened"
            ],
            "maximum_execution_entry_session_offset_opened": row_scope_audit[
                "maximum_execution_entry_session_offset_opened"
            ],
            "candidate_outcome_paths_opened": 0,
            "outcomes_computed": 0,
            "return_columns_opened": [],
            "portfolio_replay_run": False,
            "performance_gates_computed": False,
            "charts_run": False,
            "post_2021_rows_opened": row_scope_audit["post_2021_rows_opened"],
            "pit_contract": PIT_CONTRACT,
        }
        return _write_terminal(blocked, attempt)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode", choices=("verify-activation", "run-diagnostic"), default="verify-activation"
    )
    args = parser.parse_args()
    payload = verify_activation() if args.mode == "verify-activation" else run_diagnostic()
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
