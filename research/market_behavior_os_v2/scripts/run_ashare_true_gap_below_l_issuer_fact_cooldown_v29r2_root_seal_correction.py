#!/usr/bin/env python3
"""Verify CY-063 Stage A and run one CY-065 replay with fail-closed root sealing."""

from __future__ import annotations

import argparse
import json
import os
import stat
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    build_exchange_issuer_fact_rollforward_root_seal_correction_asset_v29r2 as builder,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_issuer_fact_cooldown_v29r2_index_correction as cy063,
)
from scripts import validate_data_registry as registry_validator

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "configs/data_asset_registry.json"
ASSET_ID = builder.ASSET_ID
AUTHORIZATION_ID = builder.AUTHORIZATION_ID
AUTHORIZATION_PURPOSE = "ASHARE_ISSUER_FACT_V29R2_ROLLFORWARD_2022_2026"
DEPENDENCY_ASSET_ID = builder.DEPENDENCY_ASSET_ID
DEPENDENCY_AUTHORIZATION_ID = builder.DEPENDENCY_AUTHORIZATION_ID
EXPECTED_ASSET_ROOT = builder.EXPECTED_ROOT
EXPECTED_VERIFICATION_ROOT = builder.VERIFICATION_ROOT
EXPECTED_STAGE_B_ROOT = builder.STAGE_B_ROOT
CY063_OUTPUT_ROOT = builder.CY063_OUTPUT_ROOT
YEARS = cy063.YEARS
DATA_END = cy063.DATA_END
MATURE_SIGNAL_CUTOFF = cy063.MATURE_SIGNAL_CUTOFF
PROTOCOL_ROLE = "stage_output_root_seal_correction_r4_freeze"

EXPECTED_AUTH_ALLOWED_USES = [
    (
        "verify the immutable CY-063 Stage-A seven-file cohort in memory under the frozen "
        "R3 comparator and write one CY-065 outer verification freeze"
    ),
    (
        "after independent outer-freeze SHA review, run one unchanged A67 H20 40-bp K80 "
        "Stage-B replay in the exact CY-065 root under fail-closed root sealing"
    ),
]
EXPECTED_AUTH_BLOCKED_USES = [
    (
        "registering or running superseded CY-064 CLI, outer-verification or Stage-B "
        "workflows; materializing or selecting a new Stage-A cohort; or mutating any "
        "CY-063/CY-064 artifact"
    ),
    (
        "changing the R3 comparator, source, causal, title taxonomy, cooldown, selector, "
        "threshold, execution, portfolio or reporting semantics"
    ),
    (
        "alternate roots, repeated attempts, symlink following, strict PIT-A, "
        "pristine-OOS or live claims"
    ),
]


class RootSealCorrectionError(RuntimeError):
    """Fail closed on registry, immutable-stage, filesystem, or replay drift."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RootSealCorrectionError(message)


def sha256(path: Path) -> str:
    return builder.sha256(path)


def value_sha256(value: Any) -> str:
    return builder.value_sha256(value)


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        return builder.read_json(path, label)
    except builder.RootSealCorrectionAssetError as exc:
        raise RootSealCorrectionError(str(exc)) from exc


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    try:
        builder.write_json_exclusive(path, value)
    except builder.RootSealCorrectionAssetError as exc:
        raise RootSealCorrectionError(str(exc)) from exc


def _root_present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def seal_dedicated_tree_without_following(root: Path) -> None:
    """Validate every node without following links, then seal files 0444/dirs 0555."""

    require(_root_present(root), f"dedicated root does not exist: {root}")
    require(not root.is_symlink() and root.is_dir(), f"unsafe dedicated root: {root}")
    files: list[Path] = []
    directories: list[Path] = [root]

    def inspect(directory: Path) -> None:
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise RootSealCorrectionError(f"cannot inspect dedicated root: {directory}") from exc
        for entry in entries:
            path = Path(entry.path)
            require(not entry.is_symlink(), f"refusing symlink in dedicated root: {path}")
            if entry.is_dir(follow_symlinks=False):
                directories.append(path)
                inspect(path)
            elif entry.is_file(follow_symlinks=False):
                files.append(path)
            else:
                raise RootSealCorrectionError(f"unsupported node in dedicated root: {path}")

    inspect(root)
    for path in files:
        path.chmod(0o444, follow_symlinks=False)
    for path in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        path.chmod(0o555, follow_symlinks=False)


def require_read_only(path: Path, label: str) -> None:
    require(
        path.stat(follow_symlinks=False).st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        == 0,
        f"{label} is writable: {path}",
    )


def verify_registration(asset_root: Path) -> dict[str, Any]:
    registry = read_json(REGISTRY, "central registry")
    errors = registry_validator.validate_registry(registry, verify_paths=True, verify_hashes=True)
    require(not errors, f"central data registry validation failed: {errors}")
    require(
        registry.get("global_gate", {}).get("free_causal_research_ready") is True
        and registry.get("global_gate", {}).get("backtest_authorized") is True,
        "central causal-research/backtest gate is closed",
    )
    require(
        not any(item.get("asset_id") == "CY-064" for item in registry.get("assets", []))
        and not any(
            item.get("asset_id") == "CY-064" for item in registry.get("bounded_authorizations", [])
        ),
        "superseded CY-064 must remain unregistered",
    )
    assets = [item for item in registry.get("assets", []) if item.get("asset_id") == ASSET_ID]
    auths = [
        item
        for item in registry.get("bounded_authorizations", [])
        if item.get("authorization_id") == AUTHORIZATION_ID
    ]
    dependencies = [
        item for item in registry.get("assets", []) if item.get("asset_id") == DEPENDENCY_ASSET_ID
    ]
    dependency_auths = [
        item
        for item in registry.get("bounded_authorizations", [])
        if item.get("authorization_id") == DEPENDENCY_AUTHORIZATION_ID
    ]
    require(
        len(assets) == len(auths) == len(dependencies) == len(dependency_auths) == 1,
        "CY-065 or registered CY-063 dependency is missing",
    )
    asset, auth = assets[0], auths[0]
    dependency, dependency_auth = dependencies[0], dependency_auths[0]
    manifest_path = asset_root / "asset_manifest.json"
    manifest = read_json(manifest_path, "CY-065 manifest")
    lineage = asset.get("lineage", {})
    require(
        asset.get("status") == "RESEARCH_CONDITIONAL"
        and asset.get("physical_state") == "MATERIALIZED"
        and asset.get("pit_grade") == "B"
        and Path(str(asset.get("location"))).resolve() == asset_root
        and lineage.get("record_available_at") is True
        and lineage.get("record_snapshot_id") is True
        and lineage.get("immutable_manifest") is True
        and lineage.get("manifest_path") == str(manifest_path)
        and lineage.get("manifest_sha256") == sha256(manifest_path)
        and lineage.get("component_assets") == [DEPENDENCY_ASSET_ID]
        and lineage.get("bounded_authorization_id") == AUTHORIZATION_ID
        and auth.get("asset_id") == ASSET_ID
        and auth.get("purpose") == AUTHORIZATION_PURPOSE,
        "CY-065 registry semantics drifted",
    )
    coverage = asset.get("coverage", {})
    require(
        coverage.get("sse_query_start") == "1990-12-19"
        and coverage.get("szse_query_start") == "2021-10-18"
        and coverage.get("query_end") == "2026-08-03"
        and coverage.get("signal_start") == "2022-01-01"
        and coverage.get("signal_end") == "2026-08-03"
        and coverage.get("outcome_end") == "2026-09-04"
        and coverage.get("source_capture_symbols") == 227
        and coverage.get("symbols") == 188
        and coverage.get("sse_symbols") == 39
        and coverage.get("szse_symbols") == 149
        and coverage.get("route_rows") == 149545
        and coverage.get("verification_root") == str(EXPECTED_VERIFICATION_ROOT)
        and coverage.get("stage_b_output_root") == str(EXPECTED_STAGE_B_ROOT),
        "CY-065 registered coverage/output roots drifted",
    )
    scope = auth.get("scope", {})
    require(
        auth.get("dependency_asset_id") == DEPENDENCY_ASSET_ID
        and auth.get("dependency_status") == "RESEARCH_CONDITIONAL"
        and dependency.get("status") == auth.get("dependency_status")
        and dependency.get("lineage", {}).get("manifest_sha256")
        == builder.cy064_builder.CY063_MANIFEST_SHA256
        and dependency_auth.get("asset_id") == DEPENDENCY_ASSET_ID
        and scope.get("project") == "research/market_behavior_os_v2"
        and scope.get("start") == "1990-12-19"
        and scope.get("end") == "2026-09-04"
        and scope.get("sse_query_start") == "1990-12-19"
        and scope.get("szse_query_start") == "2021-10-18"
        and scope.get("announcement_query_end") == "2026-08-03"
        and scope.get("signal_start") == "2022-01-01"
        and scope.get("signal_end") == "2026-08-03"
        and scope.get("outcome_end") == "2026-09-04"
        and scope.get("verification_root") == str(EXPECTED_VERIFICATION_ROOT)
        and scope.get("stage_b_output_root") == str(EXPECTED_STAGE_B_ROOT),
        "CY-065 dependency/scope drifted",
    )
    require(
        auth.get("current_survivor_fallback_allowed") is False
        and auth.get("record_level_available_at_available") is True
        and auth.get("new_event_classification_or_selection_authorized") is False
        and auth.get("new_stage_a_artifacts_or_selection_materialization_authorized") is False
        and auth.get("in_memory_deterministic_stage_a_verification_replay_authorized") is True
        and auth.get("in_memory_title_classification_verification_replay_authorized") is True
        and auth.get("root_seal_correction_only") is True
        and auth.get("bounded_serialization_representation_comparison") is True
        and auth.get("validation_outcome_join_authorized") is True
        and auth.get("portfolio_replay_authorized") is True
        and auth.get("strict_pit_a_authorized") is False
        and auth.get("live_trading_authorized") is False
        and auth.get("v29r1_fallback_authorized") is False
        and auth.get("post_2024_pristine_validation_claim_authorized") is False
        and auth.get("single_stage_b_attempt_authorized") is True,
        "CY-065 authorization flags drifted",
    )
    require(
        auth.get("bound_manifest") == {"path": str(manifest_path), "sha256": sha256(manifest_path)},
        "CY-065 bound manifest drifted",
    )
    inventory = {item.get("role"): item for item in manifest.get("inventory", [])}
    artifacts = auth.get("bound_artifacts", [])
    fingerprints = {item.get("role"): item for item in artifacts}
    require(
        isinstance(artifacts, list)
        and len(fingerprints) == len(artifacts)
        and set(fingerprints) == set(inventory),
        "CY-065 exact artifact role set drifted",
    )
    for role, item in fingerprints.items():
        path = Path(str(item.get("path", "")))
        manifest_item = inventory[role]
        require(
            path.is_file()
            and not path.is_symlink()
            and sha256(path) == item.get("sha256")
            and {"path": item.get("path"), "sha256": item.get("sha256")}
            == {"path": manifest_item.get("path"), "sha256": manifest_item.get("sha256")},
            f"CY-065 artifact/manifest fingerprint drifted: {role}",
        )
    protocol_fact = inventory.get(PROTOCOL_ROLE)
    require(protocol_fact is not None, "CY-065 manifest lacks R4 protocol")
    expected_protocol = {
        "path": protocol_fact.get("path"),
        "sha256": protocol_fact.get("sha256"),
    }
    bound_protocol = auth.get("bound_protocol", {})
    require(
        auth.get("bound_strategy") == expected_protocol
        and bound_protocol.get("path") == expected_protocol["path"]
        and bound_protocol.get("sha256") == expected_protocol["sha256"]
        and bound_protocol.get("runner_path") == str(Path(__file__).resolve())
        and bound_protocol.get("runner_sha256") == sha256(Path(__file__).resolve()),
        "CY-065 protocol/runner binding drifted",
    )
    require(
        auth.get("allowed_uses") == EXPECTED_AUTH_ALLOWED_USES
        and auth.get("blocked_uses") == EXPECTED_AUTH_BLOCKED_USES,
        "CY-065 allowed/blocked use contract drifted",
    )
    dependency_identity = manifest.get("dependency", {}).get("registry_identity", {})
    require(
        dependency_identity
        == {
            "asset_value_sha256": value_sha256(dependency),
            "authorization_value_sha256": value_sha256(dependency_auth),
        },
        "CY-063 dependency registry identity drifted",
    )
    return {
        "asset": asset,
        "authorization": auth,
        "fingerprints": fingerprints,
        "dependency_asset": dependency,
        "dependency_authorization": dependency_auth,
    }


def verify_asset(asset_root: Path, parent_selected: Path) -> dict[str, Any]:
    require(asset_root.resolve() == EXPECTED_ASSET_ROOT, "unexpected CY-065 asset root")
    registered = verify_registration(asset_root)
    try:
        validation = builder.validate(asset_root)
    except builder.RootSealCorrectionAssetError as exc:
        raise RootSealCorrectionError(f"CY-065 wrapper validation failed: {exc}") from exc
    manifest_path = asset_root / "asset_manifest.json"
    manifest = read_json(manifest_path, "CY-065 manifest")
    require(
        validation.get("valid") is True
        and validation.get("manifest_sha256") == sha256(manifest_path)
        and manifest.get("parent_sources", {}).get("selected")
        == {"path": str(parent_selected), "sha256": sha256(parent_selected)},
        "CY-065 wrapper or parent-selected identity drifted",
    )
    return {
        "asset_id": ASSET_ID,
        "wrapper_manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path)},
        "registered_asset_entry_sha256": value_sha256(registered["asset"]),
        "bounded_authorization_sha256": value_sha256(registered["authorization"]),
        "protocol": {
            "path": str(builder.PROTOCOL),
            "sha256": sha256(builder.PROTOCOL),
            "runner": {
                "path": str(Path(__file__).resolve()),
                "sha256": sha256(Path(__file__).resolve()),
            },
        },
        "dependency_cy063_identity": validation["cy063_stage_a_verification"]["cy063_identity"],
        "cy063_stage_a_verification": validation["cy063_stage_a_verification"],
        "superseded_cy064": manifest["superseded_unregistered_wrapper"],
        "bound_artifacts": {
            role: {"path": str(item["path"]), "sha256": str(item["sha256"])}
            for role, item in sorted(registered["fingerprints"].items())
        },
        "parent_sources": manifest["parent_sources"],
    }


def outer_freeze_payload(
    identity: Mapping[str, Any], stage: Mapping[str, Any], created_at: str
) -> dict[str, Any]:
    return {
        "stage": "CY065_CY063_STAGE_A_CANONICALLY_VERIFIED_BEFORE_OUTCOME_ACCESS",
        "created_at": created_at,
        "root_seal_correction_wrapper_identity": identity,
        "superseded_unregistered_wrapper": identity["superseded_cy064"],
        "cy063_stage_a_root": str(CY063_OUTPUT_ROOT),
        "cy063_stage_a_freeze": {
            "path": str(CY063_OUTPUT_ROOT / "stage_a/freeze.json"),
            "sha256": builder.cy064_builder.CY063_STAGE_HASHES["freeze.json"],
        },
        "cy063_stage_a_artifact_hashes": dict(builder.cy064_builder.CY063_STAGE_HASHES),
        "verification_contract": stage["classified_comparator"],
        "parent_signals": stage["parent_signals"],
        "selected_signals": stage["selected_signals"],
        "rejected_signals": stage["rejected_signals"],
        "selected_by_signal_year": stage["selected_by_signal_year"],
        "route_audit": stage["route_audit"],
        "selector_outputs_strict_exact": stage["selector_outputs_strict_exact"],
        "execution_contract": stage["execution_contract"],
        "new_stage_a_artifacts_or_selection_materialized": False,
        "in_memory_deterministic_stage_a_verification_replay_performed": True,
        "in_memory_title_classification_verification_replay_performed": True,
        "outcome_or_daily_parquet_content_rows_parsed": False,
        "performance_statistics_computed": False,
        "rule_selector_threshold_source_causal_execution_or_portfolio_changed": False,
        "stage_b_started": False,
        "evidence_grade": "PIT_B_CURRENT_OFFICIAL_ENUMERATION_REVISION_HISTORY_INCOMPLETE",
        "v29r1_later_period_status": "BLOCKED_BY_IMMUTABLE_SEMANTIC_INVALIDITY",
    }


def run_verify_only(
    asset_root: Path,
    parent_selected: Path,
    verification_root: Path,
    stage_b_root: Path,
) -> dict[str, Any]:
    require(
        verification_root.resolve() == EXPECTED_VERIFICATION_ROOT,
        "CY-065 verifier requires the frozen verification root",
    )
    require(
        stage_b_root.resolve() == EXPECTED_STAGE_B_ROOT,
        "CY-065 verifier requires the frozen Stage-B root",
    )
    require(not _root_present(verification_root), "non-pristine CY-065 verification root")
    require(not _root_present(stage_b_root), "CY-065 Stage-B root must remain absent")
    identity = verify_asset(asset_root, parent_selected)
    stage = identity["cy063_stage_a_verification"]
    freeze = outer_freeze_payload(identity, stage, datetime.now(UTC).isoformat())
    try:
        verification_root.mkdir(parents=False, exist_ok=False)
        freeze_path = verification_root / "verified_stage_a_freeze.json"
        write_json_exclusive(freeze_path, freeze)
        builder.exact_top(verification_root, {"verified_stage_a_freeze.json"})
        require(
            read_json(freeze_path, "CY-065 outer freeze") == freeze,
            "CY-065 outer freeze did not round-trip exactly",
        )
        return {
            "verified": True,
            "outer_freeze": {"path": str(freeze_path), "sha256": sha256(freeze_path)},
            "selected_signals": stage["selected_signals"],
            "rejected_signals": stage["rejected_signals"],
            "selected_by_signal_year": stage["selected_by_signal_year"],
            "stage_b_root_absent": not _root_present(stage_b_root),
        }
    finally:
        if _root_present(verification_root):
            seal_dedicated_tree_without_following(verification_root)


def verify_outer_freeze(
    asset_root: Path, parent_selected: Path, verification_root: Path
) -> dict[str, Any]:
    require(
        verification_root.resolve() == EXPECTED_VERIFICATION_ROOT,
        "unexpected CY-065 verification root",
    )
    builder.exact_top(verification_root, {"verified_stage_a_freeze.json"})
    require_read_only(verification_root, "CY-065 verification root")
    freeze_path = verification_root / "verified_stage_a_freeze.json"
    require_read_only(freeze_path, "CY-065 outer freeze")
    freeze = read_json(freeze_path, "CY-065 outer freeze")
    identity = verify_asset(asset_root, parent_selected)
    expected = outer_freeze_payload(
        identity, identity["cy063_stage_a_verification"], str(freeze.get("created_at"))
    )
    require(freeze == expected, "CY-065 outer freeze semantic reconstruction failed")
    return {
        "verified": True,
        "outer_freeze_sha256": sha256(freeze_path),
        "outer_freeze_path": str(freeze_path),
        "asset_identity": identity,
        "cy063_stage_a_hashes": dict(builder.cy064_builder.CY063_STAGE_HASHES),
    }


def _complete_stage_b_after_seal(
    *,
    asset_root: Path,
    parent_selected: Path,
    parent_outcomes: Path,
    parent_daily: Path,
    verification_root: Path,
    output_root: Path,
    expected_outer_freeze_sha256: str,
    verification: Mapping[str, Any],
    identity: Mapping[str, Any],
    selected_path: Path,
    attempt_path: Path,
    attempt: Mapping[str, Any],
) -> dict[str, Any]:
    selected = pd.read_parquet(selected_path)
    outcomes = pd.read_parquet(parent_outcomes)
    join_audit = cy063.predecessor.verify_exact_selected_outcome_join(selected, outcomes)
    outcome_contract = cy063.predecessor.verify_outcome_contract(selected, outcomes)
    execution_contract = cy063.predecessor.verify_execution_contract(selected)
    source_hashes = {
        "parent_outcomes": sha256(parent_outcomes),
        "parent_outcome_daily": sha256(parent_daily),
    }
    lane_root = output_root / "stage_b/lane"
    with cy063.replay_context(selected_path, parent_outcomes, parent_daily, lane_root):
        lane = cy063.predecessor.replay.run_lane("ROLLFORWARD", YEARS)
    portfolio_audit = lane.get("portfolio", {}).get("audit", {})
    require(
        portfolio_audit.get("max_k_violation_count") == 0
        and portfolio_audit.get("negative_cash_or_leverage_count") == 0,
        "K80 replay violates capacity or cash/leverage invariants",
    )
    require(
        source_hashes
        == {
            "parent_outcomes": sha256(parent_outcomes),
            "parent_outcome_daily": sha256(parent_daily),
        },
        "parent outcome sources drifted during replay",
    )
    post = verify_outer_freeze(asset_root, parent_selected, verification_root)
    require(
        post["outer_freeze_sha256"] == expected_outer_freeze_sha256
        and post["cy063_stage_a_hashes"] == verification["cy063_stage_a_hashes"],
        "CY-065 outer freeze or CY-063 Stage-A bytes drifted during Stage B",
    )
    accepted_path = lane_root / "portfolio_accepted.parquet"
    accepted = pd.read_parquet(accepted_path)
    accepted_contract = cy063.predecessor.verify_accepted_contract(accepted)
    yearly = cy063.predecessor.detailed_yearly(selected, accepted)
    result = {
        "strategy": "V29R2-CY065-ROOT-SEAL-CORRECTION",
        "status": "COMPLETE_PIT_B_FIXED_RULE_ROLLFORWARD_ROOT_SEAL_CORRECTION",
        "scientific_periods": {
            "2022-2024": "DEPENDENT_FIXED_RULE_VALIDATION_NOT_PRISTINE_OOS",
            "2025-2026": "POST_SELECTION_TEMPORAL_DIAGNOSTIC",
        },
        "data_end": DATA_END.date().isoformat(),
        "fully_mature_signal_cutoff": MATURE_SIGNAL_CUTOFF.date().isoformat(),
        "evidence_grade": "PIT_B_CURRENT_OFFICIAL_ENUMERATION_REVISION_HISTORY_INCOMPLETE",
        "root_seal_correction_wrapper_identity": identity,
        "dependency_cy063_identity": identity["dependency_cy063_identity"],
        "superseded_unregistered_cy064": identity["superseded_cy064"],
        "outer_stage_a_verification": verification,
        "pre_outcome_attempt_seal": {
            "path": str(attempt_path),
            "sha256": sha256(attempt_path),
        },
        "exact_join_audit": join_audit,
        "outcome_contract": outcome_contract,
        "accepted_contract": accepted_contract,
        "execution_contract": execution_contract,
        "portfolio_audit": portfolio_audit,
        "parent_sources": attempt["parent_sources"],
        "yearly_by_signal_year": yearly,
        "lane": lane,
        "output_hashes": {
            "portfolio_accepted": sha256(accepted_path),
            "filtered_outcomes": sha256(lane_root / "outcomes.parquet"),
            "portfolio_nav": sha256(lane_root / "portfolio_nav.parquet"),
        },
        "new_stage_a_artifacts_or_selection_materialized": False,
        "in_memory_deterministic_stage_a_verification_replay_performed": True,
        "in_memory_title_classification_verification_replay_performed": True,
        "rule_changed": False,
        "root_seal_correction_only": True,
        "v29r1_later_period_status": "BLOCKED_BY_IMMUTABLE_SEMANTIC_INVALIDITY",
    }
    write_json_exclusive(output_root / "result.json", result)
    return result


def run_stage_b(
    asset_root: Path,
    parent_selected: Path,
    parent_outcomes: Path,
    parent_daily: Path,
    verification_root: Path,
    output_root: Path,
    expected_outer_freeze_sha256: str,
) -> dict[str, Any]:
    require(output_root.resolve() == EXPECTED_STAGE_B_ROOT, "unexpected CY-065 Stage-B root")
    require(not _root_present(output_root), "repeated/non-pristine CY-065 Stage-B attempt")
    verification = verify_outer_freeze(asset_root, parent_selected, verification_root)
    require(
        len(expected_outer_freeze_sha256) == 64
        and verification["outer_freeze_sha256"] == expected_outer_freeze_sha256,
        "independently supplied expected outer-freeze SHA does not match",
    )
    identity = verification["asset_identity"]
    supplied = {
        "selected": parent_selected,
        "outcomes": parent_outcomes,
        "outcome_daily": parent_daily,
    }
    for role, path in supplied.items():
        fact = identity["parent_sources"][role]
        require(
            Path(str(fact["path"])).resolve() == path.resolve() and fact["sha256"] == sha256(path),
            f"CLI parent {role} differs from CY-065 authorization",
        )
    selected_path = CY063_OUTPUT_ROOT / "stage_a/selected_entries.parquet"
    require(
        sha256(selected_path)
        == builder.cy064_builder.CY063_STAGE_HASHES["selected_entries.parquet"],
        "CY-063 selected cohort drifted before Stage B",
    )
    try:
        output_root.mkdir(parents=False, exist_ok=False)
        attempt_path = output_root / "stage_b_pre_outcome_attempt_seal.json"
        attempt = {
            "stage": "CY065_STAGE_B_EXCLUSIVE_PRE_OUTCOME_ATTEMPT_SEAL",
            "created_at": datetime.now(UTC).isoformat(),
            "outer_freeze": {
                "path": verification["outer_freeze_path"],
                "sha256": expected_outer_freeze_sha256,
            },
            "root_seal_correction_wrapper_identity": identity,
            "cy063_stage_a_artifact_hashes": dict(builder.cy064_builder.CY063_STAGE_HASHES),
            "parent_sources": {
                role: {"path": str(path), "sha256": sha256(path)} for role, path in supplied.items()
            },
            "all_preflight_and_canonical_replay_checks_passed": True,
            "outcome_or_daily_parquet_content_rows_parsed": False,
            "single_attempt_only": True,
        }
        write_json_exclusive(attempt_path, attempt)
        builder.exact_top(output_root, {"stage_b_pre_outcome_attempt_seal.json"})
        require_read_only(attempt_path, "CY-065 pre-outcome attempt seal")
        require(
            read_json(attempt_path, "CY-065 pre-outcome attempt seal") == attempt,
            "CY-065 pre-outcome attempt seal did not round-trip exactly",
        )
        return _complete_stage_b_after_seal(
            asset_root=asset_root,
            parent_selected=parent_selected,
            parent_outcomes=parent_outcomes,
            parent_daily=parent_daily,
            verification_root=verification_root,
            output_root=output_root,
            expected_outer_freeze_sha256=expected_outer_freeze_sha256,
            verification=verification,
            identity=identity,
            selected_path=selected_path,
            attempt_path=attempt_path,
            attempt=attempt,
        )
    finally:
        if _root_present(output_root):
            seal_dedicated_tree_without_following(output_root)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("verify-only", "stage-b"))
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--parent-selected", type=Path, required=True)
    parser.add_argument("--parent-outcomes", type=Path)
    parser.add_argument("--parent-daily", type=Path)
    parser.add_argument("--verification-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--expected-outer-freeze-sha256")
    args = parser.parse_args()
    if args.mode == "verify-only":
        require(
            args.parent_outcomes is None
            and args.parent_daily is None
            and args.expected_outer_freeze_sha256 is None,
            "verify-only does not accept outcome inputs or expected outer SHA",
        )
        result = run_verify_only(
            args.asset_root.resolve(),
            args.parent_selected.resolve(),
            args.verification_root.resolve(),
            args.output_root.resolve(),
        )
    else:
        require(
            args.parent_outcomes is not None
            and args.parent_daily is not None
            and args.expected_outer_freeze_sha256 is not None,
            "Stage B requires outcomes, daily and independently supplied outer-freeze SHA",
        )
        result = run_stage_b(
            args.asset_root.resolve(),
            args.parent_selected.resolve(),
            args.parent_outcomes.resolve(),
            args.parent_daily.resolve(),
            args.verification_root.resolve(),
            args.output_root.resolve(),
            args.expected_outer_freeze_sha256,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
