#!/usr/bin/env python3
"""Build/validate CY-065, the root-seal successor to blocked unregistered CY-064."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from research.market_behavior_os_v2.scripts import (
    build_exchange_issuer_fact_rollforward_verifier_correction_asset_v29r2 as cy064_builder,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_issuer_fact_cooldown_v29r2_verifier_correction as cy064_runner,
)
from scripts import validate_data_registry as registry_validator

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "configs/data_asset_registry.json"
ASSET_ID = "CY-065"
DEPENDENCY_ASSET_ID = "CY-063"
DEPENDENCY_AUTHORIZATION_ID = cy064_builder.PREDECESSOR_AUTHORIZATION_ID
AUTHORIZATION_ID = "CYQ-AUTH-ASHARE-ISSUER-FACT-V29R2-ROLLFORWARD-2022-2026-ROOT-SEAL-CORRECTION-V1"
EXPECTED_ROOT = Path(
    "/Users/linmei/Documents/CY/data/staging/"
    "CY-065-V29R2-ISSUER-FACT-ROLLFORWARD-ROOT-SEAL-CORRECTION-2022-2026-V1"
)
CY063_ROOT = cy064_builder.CY063_ROOT
CY063_OUTPUT_ROOT = cy064_builder.CY063_OUTPUT_ROOT
CY064_ROOT = cy064_builder.EXPECTED_ROOT
CY064_VERIFICATION_ROOT = cy064_builder.VERIFICATION_ROOT
CY064_STAGE_B_ROOT = cy064_builder.STAGE_B_ROOT
VERIFICATION_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_v29r2_issuer_fact_rollforward_cy065_stage_a_verification_v1"
)
STAGE_B_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_v29r2_issuer_fact_rollforward_cy065_through_20260904_v1"
)
NEW_RUNNER = ROOT / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_true_gap_below_l_issuer_fact_cooldown_v29r2_root_seal_correction.py"
)
PROTOCOL = ROOT / (
    "research/market_behavior_os_v2/experiments/"
    "ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-ISSUER-FACT-COOLDOWN-V29R2_"
    "rollforward_2022_2026_stage_output_root_seal_correction_r4_freeze.json"
)
CY064_BLOCKER = ROOT / (
    "research/market_behavior_os_v2/artifacts/"
    "ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-ISSUER-FACT-COOLDOWN-V29R2_"
    "rollforward_cy064_unregistered_root_seal_blocker.json"
)
CY064_DISCREPANCY = cy064_builder.DISCREPANCY_AUDIT
CY064_PROTOCOL = cy064_builder.PROTOCOL
CY064_SUGGESTION = ROOT / (
    "research/market_behavior_os_v2/artifacts/"
    "CY-064_V29R2_rollforward_verifier_correction_registry_suggestion.json"
)
PARENT_SELECTED = cy064_builder.PARENT_SELECTED
PARENT_OUTCOMES = cy064_builder.PARENT_OUTCOMES
PARENT_DAILY = cy064_builder.PARENT_DAILY

CY064_HASHES = {
    "asset_manifest": "c0e0ad5d5a7cca834a0eb0361a3105f7c6b13991252ddfbb0399f9c9d0b1eda6",
    "activation_audit": "f2ae2265cf6e0305524d7560312fa3c5daaa8f741ac9c1575f3880851a594779",
    "builder": "62a2ee454ab61fbd8d72a08725c751a710aa1cc52300095461b821b4c8d873cf",
    "runner": "9f4088144e41d1370830e25cfd0927feb98f230af2774bd8e5df382d112a7480",
    "r3_protocol": "3ddb06396629e084d5741caf127e567aec08edd2f09fef28af3391caff6ff1ff",
    "cy063_discrepancy_audit": ("e54169c257fff4d8aa6008c760f86f7db5c6abaad7558c82ad197472ce1d887f"),
    "registry_suggestion": "332ec8eb04f0cd4c89a3e4f913ba69204c6e92e1a021435b120646001bb51029",
    "root_seal_blocker": "f33fe34a16f7b1f44fb024b54ecc1f2a82cf16449f43a7ae38797403ef9ea869",
}


class RootSealCorrectionAssetError(RuntimeError):
    """Fail closed on CY-065 identity, predecessor, or boundary drift."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RootSealCorrectionAssetError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def value_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def read_json(path: Path, label: str) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"missing or unsafe {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RootSealCorrectionAssetError(f"invalid {label}: {path}") from exc
    require(isinstance(value, dict), f"{label} must be an object")
    return value


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise RootSealCorrectionAssetError(f"refusing to overwrite {path}") from exc
    path.chmod(0o444)


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
            raise RootSealCorrectionAssetError(
                f"cannot inspect dedicated root: {directory}"
            ) from exc
        for entry in entries:
            path = Path(entry.path)
            require(not entry.is_symlink(), f"refusing symlink in dedicated root: {path}")
            if entry.is_dir(follow_symlinks=False):
                directories.append(path)
                inspect(path)
            elif entry.is_file(follow_symlinks=False):
                files.append(path)
            else:
                raise RootSealCorrectionAssetError(f"unsupported node in dedicated root: {path}")

    inspect(root)
    for path in files:
        path.chmod(0o444, follow_symlinks=False)
    for path in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        path.chmod(0o555, follow_symlinks=False)


def exact_top(root: Path, expected: set[str]) -> None:
    require(root.is_dir() and not root.is_symlink(), f"unsafe root: {root}")
    actual = {item.name for item in root.iterdir()}
    require(actual == expected, f"inventory drifted at {root}: {sorted(actual)}")
    require(all(not item.is_symlink() for item in root.iterdir()), f"symlink at {root}")


def require_read_only(path: Path, label: str) -> None:
    require(
        path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0,
        f"{label} is writable: {path}",
    )


def _require_hash(path: Path, expected: str, label: str) -> None:
    require(
        path.is_file() and not path.is_symlink() and sha256(path) == expected,
        f"{label} drifted",
    )


def validate_cy064_blocked_predecessor() -> dict[str, Any]:
    exact_top(CY064_ROOT, {"activation_audit.json", "asset_manifest.json"})
    require_read_only(CY064_ROOT, "CY-064 wrapper root")
    for path, expected, label in (
        (CY064_ROOT / "asset_manifest.json", CY064_HASHES["asset_manifest"], "CY-064 manifest"),
        (
            CY064_ROOT / "activation_audit.json",
            CY064_HASHES["activation_audit"],
            "CY-064 activation audit",
        ),
        (Path(cy064_builder.__file__).resolve(), CY064_HASHES["builder"], "CY-064 builder"),
        (Path(cy064_runner.__file__).resolve(), CY064_HASHES["runner"], "CY-064 runner"),
        (CY064_PROTOCOL, CY064_HASHES["r3_protocol"], "CY-064 R3 protocol"),
        (
            CY064_DISCREPANCY,
            CY064_HASHES["cy063_discrepancy_audit"],
            "CY-064 discrepancy audit",
        ),
        (
            CY064_SUGGESTION,
            CY064_HASHES["registry_suggestion"],
            "CY-064 registry suggestion",
        ),
    ):
        _require_hash(path, expected, label)
        require_read_only(path, label)
    _require_hash(CY064_BLOCKER, CY064_HASHES["root_seal_blocker"], "CY-064 blocker audit")
    require_read_only(CY064_BLOCKER, "CY-064 blocker audit")
    blocker = read_json(CY064_BLOCKER, "CY-064 blocker audit")
    require(
        blocker.get("status") == "SUPERSEDED_UNREGISTERED_BLOCKED_WRAPPER"
        and blocker.get("central_registration", {}).get("asset_entries") == 0
        and blocker.get("central_registration", {}).get("bounded_authorization_entries") == 0
        and blocker.get("first_difference", {}).get("component") == "failure-path root sealing"
        and blocker.get("first_difference", {}).get(
            "create_then_raise_fault_injection_reproduces_writable_root"
        )
        is True
        and blocker.get("unused_output_boundaries", {}).get("verification_root_exists") is False
        and blocker.get("unused_output_boundaries", {}).get("stage_b_output_root_exists") is False
        and blocker.get("unused_output_boundaries", {}).get(
            "outcome_or_daily_parquet_content_rows_parsed"
        )
        is False
        and blocker.get("disposition", {}).get("delete_overwrite_rebind_register_or_execute_cy064")
        is False
        and blocker.get("disposition", {}).get("required_successor")
        == "CY-065 root-seal correction wrapper",
        "CY-064 blocker semantics drifted",
    )
    require(
        not CY064_VERIFICATION_ROOT.exists()
        and not CY064_VERIFICATION_ROOT.is_symlink()
        and not CY064_STAGE_B_ROOT.exists()
        and not CY064_STAGE_B_ROOT.is_symlink(),
        "blocked CY-064 output root unexpectedly exists",
    )
    try:
        validation = cy064_builder.validate(CY064_ROOT)
    except cy064_builder.VerifierCorrectionAssetError as exc:
        raise RootSealCorrectionAssetError(
            f"blocked CY-064 wrapper no longer validates: {exc}"
        ) from exc
    require(
        validation.get("valid") is True
        and validation.get("manifest_sha256") == CY064_HASHES["asset_manifest"]
        and validation.get("stage_a_verification", {}).get("verified") is True,
        "blocked CY-064 semantic reconstruction drifted",
    )
    return validation


def validate_protocol(runner: Path) -> dict[str, Any]:
    protocol = read_json(PROTOCOL, "CY-065 R4 protocol")
    expected_software = {
        "root_seal_correction_asset_builder": Path(__file__).resolve(),
        "root_seal_stage_b_runner": runner,
        "blocked_cy064_asset_builder": Path(cy064_builder.__file__).resolve(),
        "blocked_cy064_runner": Path(cy064_runner.__file__).resolve(),
    }
    require(
        protocol.get("status") == "FROZEN_ROOT_SEAL_CORRECTION_BEFORE_OUTER_VERIFICATION"
        and protocol.get("asset_id") == ASSET_ID
        and protocol.get("dependency_asset_id") == DEPENDENCY_ASSET_ID
        and protocol.get("superseded_unregistered_wrapper") == "CY-064"
        and protocol.get("verification_root") == str(VERIFICATION_ROOT)
        and protocol.get("stage_b_output_root") == str(STAGE_B_ROOT)
        and protocol.get("fix", {}).get("seal_if_dedicated_root_exists_or_is_symlink") is True
        and protocol.get("fix", {}).get("reject_symlink_or_non_directory_without_following") is True
        and protocol.get("fix", {}).get("try_finally_begins_before_mkdir") is True
        and protocol.get("fix", {}).get("covered_dedicated_roots")
        == ["asset_wrapper_root", "verification_root", "stage_b_output_root"]
        and protocol.get("stage_b_contract", {}).get("expected_outer_freeze_sha256_required")
        is True
        and protocol.get("asset_root_contract", {}).get(
            "create_then_raise_is_sealed_and_blocks_retry"
        )
        is True
        and protocol.get("stage_b_contract", {}).get("single_attempt_only") is True
        and protocol.get("new_stage_a_artifacts_or_selection_materialization") is False
        and protocol.get("in_memory_deterministic_stage_a_verification_replay") is True
        and protocol.get("rule_or_research_logic_changed") is False,
        "CY-065 protocol semantics drifted",
    )
    require(
        protocol.get("canonical_comparator")
        == read_json(CY064_PROTOCOL, "CY-064 R3 protocol").get("canonical_comparator"),
        "CY-065 comparator differs from frozen R3 comparator",
    )
    software = protocol.get("software_identity", {})
    require(set(software) == set(expected_software), "CY-065 software roles drifted")
    for role, path in expected_software.items():
        fact = software[role]
        require(
            Path(str(fact.get("path", ""))).resolve() == path
            and fact.get("sha256") == sha256(path),
            f"CY-065 protocol software identity drifted: {role}",
        )
    require(
        protocol.get("cy064_blocker_audit")
        == {"path": str(CY064_BLOCKER), "sha256": sha256(CY064_BLOCKER)},
        "CY-065 protocol blocker audit identity drifted",
    )
    require(
        protocol.get("cy064_execution_boundary")
        == {
            "registered_or_cli_outer_verification_or_stage_b_workflow_run": False,
            "exact_bound_read_only_validation_and_comparator_software_invoked_under_cy065": True,
        },
        "CY-064 execution-boundary disclosure drifted",
    )
    return protocol


def _external_paths() -> list[tuple[str, Path, bool, bool]]:
    paths = [
        ("root_seal_correction_asset_builder", Path(__file__).resolve(), False, True),
        ("stage_output_root_seal_correction_r4_freeze", PROTOCOL, True, False),
        ("root_seal_stage_b_runner", NEW_RUNNER, False, False),
        ("cy064_unregistered_root_seal_blocker", CY064_BLOCKER, True, False),
        ("cy064_asset_manifest", CY064_ROOT / "asset_manifest.json", True, False),
        ("cy064_activation_audit", CY064_ROOT / "activation_audit.json", True, False),
        ("cy064_asset_builder", Path(cy064_builder.__file__).resolve(), False, True),
        ("cy064_runner", Path(cy064_runner.__file__).resolve(), False, True),
        ("cy064_r3_protocol", CY064_PROTOCOL, True, False),
        ("cy064_cy063_discrepancy_audit", CY064_DISCREPANCY, True, False),
        ("cy064_registry_suggestion", CY064_SUGGESTION, False, False),
        ("cy063_asset_manifest", CY063_ROOT / "asset_manifest.json", True, False),
        ("cy063_activation_audit", CY063_ROOT / "activation_audit.json", True, False),
    ]
    for name, role in cy064_builder.CY063_STAGE_ROLE_BY_FILE.items():
        paths.append((role, CY063_OUTPUT_ROOT / "stage_a" / name, True, False))
    paths.extend(
        [
            ("parent_selected", PARENT_SELECTED, True, False),
            ("parent_outcomes", PARENT_OUTCOMES, False, False),
            ("parent_outcome_daily", PARENT_DAILY, False, False),
        ]
    )
    return paths


def file_fact(
    role: str,
    path: Path,
    *,
    payload_deserialized: bool,
    runtime_invoked: bool,
) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"missing or unsafe {role}: {path}")
    return {
        "role": role,
        "path": str(path),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "identity_bytes_hashed_during_wrapper_build": True,
        "artifact_payload_directly_deserialized_as_data_during_wrapper_build": (
            payload_deserialized
        ),
        "runtime_software_invoked_during_wrapper_build": runtime_invoked,
    }


def inventory(audit_path: Path) -> list[dict[str, Any]]:
    result = [
        file_fact("activation_audit", audit_path, payload_deserialized=True, runtime_invoked=False)
    ]
    result.extend(
        file_fact(
            role,
            path,
            payload_deserialized=deserialized,
            runtime_invoked=invoked,
        )
        for role, path, deserialized, invoked in _external_paths()
    )
    roles = [item["role"] for item in result]
    require(len(roles) == len(set(roles)), "CY-065 inventory has duplicate roles")
    return result


def validate_dependencies(runner: Path, *, require_outputs_absent: bool = False) -> dict[str, Any]:
    require(runner.resolve() == NEW_RUNNER and runner.is_file(), "unexpected CY-065 runner")
    if require_outputs_absent:
        require(
            not VERIFICATION_ROOT.exists() and not VERIFICATION_ROOT.is_symlink(),
            "CY-065 verification root must be absent at build",
        )
        require(
            not STAGE_B_ROOT.exists() and not STAGE_B_ROOT.is_symlink(),
            "CY-065 Stage-B root must be absent at build",
        )
    protocol = validate_protocol(runner)
    cy064_validation = validate_cy064_blocked_predecessor()
    registry = read_json(REGISTRY, "central registry")
    errors = registry_validator.validate_registry(registry, verify_paths=True, verify_hashes=True)
    require(not errors, f"central registry validation failed: {errors}")
    require(
        not any(item.get("asset_id") == "CY-064" for item in registry.get("assets", []))
        and not any(
            item.get("asset_id") == "CY-064" for item in registry.get("bounded_authorizations", [])
        ),
        "superseded CY-064 must remain unregistered",
    )
    assets = [
        item for item in registry.get("assets", []) if item.get("asset_id") == DEPENDENCY_ASSET_ID
    ]
    auths = [
        item
        for item in registry.get("bounded_authorizations", [])
        if item.get("authorization_id") == DEPENDENCY_AUTHORIZATION_ID
    ]
    require(len(assets) == len(auths) == 1, "registered CY-063 dependency is missing")
    return {
        "protocol": protocol,
        "cy064_validation": cy064_validation,
        "cy063_stage_a_verification": cy064_validation["stage_a_verification"],
        "cy063_registry_identity": {
            "asset_value_sha256": value_sha256(assets[0]),
            "authorization_value_sha256": value_sha256(auths[0]),
        },
    }


def build_audit(deps: Mapping[str, Any], created_at: str) -> dict[str, Any]:
    return {
        "audit_schema": "CY_ROOT_SEAL_CORRECTION_WRAPPER_ACTIVATION_AUDIT_V1",
        "asset_id": ASSET_ID,
        "created_at": created_at,
        "status": "PASS_PENDING_CENTRAL_REGISTRATION",
        "dependency_asset_id": DEPENDENCY_ASSET_ID,
        "dependency_manifest_sha256": cy064_builder.CY063_MANIFEST_SHA256,
        "dependency_registry_identity": deps["cy063_registry_identity"],
        "superseded_unregistered_wrapper": {
            "asset_id": "CY-064",
            "manifest_sha256": CY064_HASHES["asset_manifest"],
            "activation_audit_sha256": CY064_HASHES["activation_audit"],
            "blocker_audit_sha256": sha256(CY064_BLOCKER),
            "never_registered": True,
            "cli_outer_verification_or_stage_b_workflow_executed": False,
            "bound_read_only_validation_and_comparator_software_invoked_by_cy065": True,
        },
        "correction": {
            "only_change": "cover create-then-raise root creation inside fail-closed sealing",
            "covered_dedicated_roots": [
                "asset_wrapper_root",
                "verification_root",
                "stage_b_output_root",
            ],
            "seal_if_dedicated_root_exists_or_is_symlink": True,
            "reject_symlink_or_non_directory_without_following": True,
            "new_stage_a_materialization_or_selection": False,
            "in_memory_deterministic_verification_replay": True,
            "rule_or_research_logic_changed": False,
        },
        "stage_boundary": {
            "verification_root": str(VERIFICATION_ROOT),
            "stage_b_output_root": str(STAGE_B_ROOT),
            "both_roots_absent_at_build": True,
            "parent_outcomes_and_daily_identity_bytes_hashed": True,
            "parent_outcomes_and_daily_parquet_content_rows_parsed": False,
            "stage_b_attempt_seal_precedes_outcome_content_parse": True,
            "single_stage_b_attempt_only": True,
        },
    }


def build_manifest(
    asset_root: Path,
    deps: Mapping[str, Any],
    created_at: str,
    bound_inventory: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "manifest_schema": "CY_IMMUTABLE_ROOT_SEAL_CORRECTION_WRAPPER_MANIFEST_V1",
        "asset_id": ASSET_ID,
        "status": "SEALED_PENDING_CENTRAL_REGISTRATION",
        "immutable": True,
        "manifest_self_included": False,
        "location": str(asset_root),
        "created_at": created_at,
        "component_assets": [DEPENDENCY_ASSET_ID],
        "pit": {
            "grade": "B",
            "current_enumeration": True,
            "revision_history_incomplete": True,
            "strict_archival_pit_ready": False,
            "inherited_without_source_mutation": True,
        },
        "coverage": {
            "sse_query_start": "1990-12-19",
            "szse_query_start": "2021-10-18",
            "announcement_query_end": "2026-08-03",
            "signal_start": "2022-01-01",
            "signal_end": "2026-08-03",
            "outcome_end": "2026-09-04",
        },
        "dependency": {
            "asset_id": DEPENDENCY_ASSET_ID,
            "root": str(CY063_ROOT),
            "manifest_sha256": cy064_builder.CY063_MANIFEST_SHA256,
            "registry_identity": deps["cy063_registry_identity"],
        },
        "superseded_unregistered_wrapper": {
            "asset_id": "CY-064",
            "root": str(CY064_ROOT),
            "manifest_sha256": CY064_HASHES["asset_manifest"],
            "activation_audit_sha256": CY064_HASHES["activation_audit"],
            "blocker_audit_path": str(CY064_BLOCKER),
            "blocker_audit_sha256": sha256(CY064_BLOCKER),
            "verification_root_never_created": True,
            "stage_b_root_never_created": True,
            "cli_outer_verification_or_stage_b_workflow_executed": False,
            "bound_read_only_validation_and_comparator_software_invoked_by_cy065": True,
        },
        "cy063_stage_a": {
            "root": str(CY063_OUTPUT_ROOT),
            "freeze_sha256": cy064_builder.CY063_STAGE_HASHES["freeze.json"],
            "artifact_hashes": dict(cy064_builder.CY063_STAGE_HASHES),
            "selected_signals": 186,
            "rejected_signals": 11,
        },
        "correction": {
            "protocol_path": str(PROTOCOL),
            "protocol_sha256": sha256(PROTOCOL),
            "only_change": "fail-closed dedicated-root sealing covers create-then-raise",
            "rule_or_research_logic_changed": False,
        },
        "verification_root": str(VERIFICATION_ROOT),
        "stage_b_output_root": str(STAGE_B_ROOT),
        "parent_sources": {
            "selected": {"path": str(PARENT_SELECTED), "sha256": sha256(PARENT_SELECTED)},
            "outcomes": {"path": str(PARENT_OUTCOMES), "sha256": sha256(PARENT_OUTCOMES)},
            "outcome_daily": {"path": str(PARENT_DAILY), "sha256": sha256(PARENT_DAILY)},
        },
        "inventory": bound_inventory,
        "stage_boundary": {
            "outer_verification_may_not_parse_parent_outcome_or_daily_content_rows": True,
            "outer_freeze_only_in_read_only_verification_root": True,
            "stage_b_requires_expected_outer_freeze_sha256": True,
            "stage_b_attempt_seal_precedes_any_outcome_or_daily_parquet_read": True,
            "all_created_partial_trees_are_sealed_or_fail_on_unsafe_node": True,
            "covered_dedicated_roots": [
                "asset_wrapper_root",
                "verification_root",
                "stage_b_output_root",
            ],
        },
        "limitations": [
            "inherits CY-063/CY-062 PIT-B current-enumeration revision/deletion-history limits",
            (
                "CY-064 registration, CLI, outer-verification and Stage-B workflows "
                "are prohibited; CY-065 invokes only its exactly bound validation/"
                "comparator software read-only"
            ),
            "corrects only create-then-raise fail-closed root sealing",
            "2022-2024 are dependent fixed-rule validation, not pristine OOS",
            "2025-2026 are post-selection temporal diagnostics, not pristine validation",
            "strict PIT-A, live trading, sizing and order generation remain prohibited",
        ],
    }


def build(asset_root: Path, runner: Path) -> dict[str, Any]:
    require(asset_root.resolve() == EXPECTED_ROOT, "unexpected CY-065 root")
    require(not asset_root.exists() and not asset_root.is_symlink(), "non-pristine CY-065 root")
    deps = validate_dependencies(runner.resolve(), require_outputs_absent=True)
    try:
        asset_root.mkdir(parents=False, exist_ok=False)
        created_at = datetime.now(UTC).isoformat()
        audit_path = asset_root / "activation_audit.json"
        write_json_exclusive(audit_path, build_audit(deps, created_at))
        bound_inventory = inventory(audit_path)
        manifest_path = asset_root / "asset_manifest.json"
        write_json_exclusive(
            manifest_path, build_manifest(asset_root, deps, created_at, bound_inventory)
        )
        exact_top(asset_root, {"activation_audit.json", "asset_manifest.json"})
        return {
            "asset_manifest": str(manifest_path),
            "asset_manifest_sha256": sha256(manifest_path),
            "activation_audit_sha256": sha256(audit_path),
            "inventory_roles": len(bound_inventory),
        }
    finally:
        if _root_present(asset_root):
            seal_dedicated_tree_without_following(asset_root)


def validate(asset_root: Path) -> dict[str, Any]:
    require(asset_root.resolve() == EXPECTED_ROOT, "unexpected CY-065 root")
    exact_top(asset_root, {"activation_audit.json", "asset_manifest.json"})
    require_read_only(asset_root, "CY-065 root")
    manifest_path = asset_root / "asset_manifest.json"
    audit_path = asset_root / "activation_audit.json"
    require_read_only(manifest_path, "CY-065 manifest")
    require_read_only(audit_path, "CY-065 audit")
    manifest = read_json(manifest_path, "CY-065 manifest")
    inventory_by_role = {item.get("role"): item for item in manifest.get("inventory", [])}
    runner_fact = inventory_by_role.get("root_seal_stage_b_runner")
    require(runner_fact is not None, "CY-065 manifest lacks runner")
    runner = Path(str(runner_fact.get("path", ""))).resolve()
    deps = validate_dependencies(runner)
    expected_audit = build_audit(deps, str(manifest.get("created_at")))
    require(read_json(audit_path, "CY-065 audit") == expected_audit, "CY-065 audit drifted")
    expected_inventory = inventory(audit_path)
    expected_manifest = build_manifest(
        asset_root, deps, str(manifest.get("created_at")), expected_inventory
    )
    require(manifest == expected_manifest, "CY-065 manifest semantic reconstruction failed")
    return {
        "valid": True,
        "manifest_sha256": sha256(manifest_path),
        "activation_audit_sha256": sha256(audit_path),
        "inventory_roles": len(expected_inventory),
        "cy063_registry_identity": deps["cy063_registry_identity"],
        "cy063_stage_a_verification": deps["cy063_stage_a_verification"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("build", "validate"))
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--runner", type=Path)
    args = parser.parse_args()
    if args.mode == "build":
        require(args.runner is not None, "build requires --runner")
        result = build(args.asset_root.resolve(), args.runner.resolve())
    else:
        result = validate(args.asset_root.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
