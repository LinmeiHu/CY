#!/usr/bin/env python3
"""Build/validate the CY-063 immutable correction wrapper over registered CY-062."""

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

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    build_exchange_issuer_fact_rollforward_asset_v29r2 as predecessor_builder,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_issuer_fact_cooldown_v29r2_rollforward as predecessor_runner,
)
from scripts import validate_data_registry as registry_validator

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "configs/data_asset_registry.json"
ASSET_ID = "CY-063"
PREDECESSOR_ASSET_ID = "CY-062"
PREDECESSOR_AUTHORIZATION_ID = "CYQ-AUTH-ASHARE-ISSUER-FACT-V29R2-ROLLFORWARD-2022-2026-V1"
AUTHORIZATION_ID = "CYQ-AUTH-ASHARE-ISSUER-FACT-V29R2-ROLLFORWARD-2022-2026-INDEX-CORRECTION-V1"
EXPECTED_ROOT = Path(
    "/Users/linmei/Documents/CY/data/staging/"
    "CY-063-V29R2-ISSUER-FACT-ROLLFORWARD-INDEX-CORRECTION-2022-2026-V1"
)
PREDECESSOR_ROOT = Path(
    "/Users/linmei/Documents/CY/data/staging/CY-062-V29R2-ISSUER-FACT-ROLLFORWARD-2022-2026-V1"
)
FAILED_OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_v29r2_issuer_fact_rollforward_through_20260904_v1"
)
CORRECTED_OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_v29r2_issuer_fact_rollforward_cy063_through_20260904_v1"
)
NEW_RUNNER = ROOT / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_true_gap_below_l_issuer_fact_cooldown_v29r2_index_correction.py"
)
CORRECTION_R2 = ROOT / (
    "research/market_behavior_os_v2/experiments/"
    "ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-ISSUER-FACT-COOLDOWN-V29R2_"
    "rollforward_2022_2026_stage_a_index_correction_r2_freeze.json"
)
FAILURE_AUDIT = ROOT / (
    "research/market_behavior_os_v2/artifacts/"
    "ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-ISSUER-FACT-COOLDOWN-V29R2_"
    "rollforward_stage_a_attempt1_index_failure.json"
)
FAILURE_AUDIT_V2 = ROOT / (
    "research/market_behavior_os_v2/artifacts/"
    "ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-ISSUER-FACT-COOLDOWN-V29R2_"
    "rollforward_stage_a_attempt1_failure_audit_correction_v2.json"
)
PREDECESSOR_RUNNER = ROOT / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_true_gap_below_l_issuer_fact_cooldown_v29r2_rollforward.py"
)
PREDECESSOR_BUILDER = Path(predecessor_builder.__file__).resolve()
CORRECTION_R1 = ROOT / (
    "research/market_behavior_os_v2/experiments/"
    "ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-ISSUER-FACT-COOLDOWN-V29R2_"
    "rollforward_2022_2026_calendar_coverage_correction_r1_freeze.json"
)
PARENT_SELECTED = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_v28_family_rollforward_through_20260904_v1/"
    "v28r2/selected_signals_2022_2026.parquet"
)
PARENT_OUTCOMES = PARENT_SELECTED.with_name("outcomes_2022_2026.parquet")
PARENT_DAILY = PARENT_SELECTED.parents[1] / "common/outcome_daily_2022_2026.parquet"
CLASSIFIER = ROOT / (
    "research/market_behavior_os_v2/scripts/classify_exchange_issuer_risk_events_v2.py"
)
COLLECTOR = ROOT / (
    "research/market_behavior_os_v2/scripts/fetch_exchange_issuer_announcements_v1.py"
)
SEALER = ROOT / ("research/market_behavior_os_v2/scripts/seal_exchange_issuer_announcements_v1.py")
PREREG = ROOT / (
    "research/market_behavior_os_v2/experiments/"
    "ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-ISSUER-FACT-COOLDOWN-V29R2_"
    "preregistration.json"
)
DEVELOPMENT_RESULT = ROOT / (
    "research/market_behavior_os_v2/artifacts/"
    "ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-ISSUER-FACT-COOLDOWN-V29R2_"
    "development_result.json"
)
SEMANTIC_BLOCKER = ROOT / (
    "research/market_behavior_os_v2/artifacts/"
    "ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-ISSUER-INTEGRITY-COOLDOWN-V29R1_"
    "semantic_blocker.json"
)

EXPECTED_HASHES = {
    "predecessor_asset_manifest": (
        "6a4f1bcbeb443aff7d7233948e6236ae16f1b2a75461a8598acf62b6bb530922"
    ),
    "predecessor_activation_audit": (
        "436f1d9445184ac08d5c0ddb0baa1bdcecdb64d64662d1cfa93c616481800f6c"
    ),
    "announcement_route_index": "ddcd4717bf3301d99d4df3d4b6908620b701b95eaebbc06215107409f2fda679",
    "predecessor_asset_builder": "3eeeca68c8160ddaee564a5319b4be49a4f4e84be26b2a9d6a1293d5387e1e8f",
    "predecessor_rollforward_runner": (
        "bf810eb80cf7ee1b71c780515cfdc8cb1bbde26b640d32b6d97c9c22a6bd594b"
    ),
    "calendar_coverage_correction_r1_freeze": (
        "9634653e47f6578091cfc6f95ff732dfad8678829e578be81204f62c5cca6f2a"
    ),
    "stage_a_attempt1_failure_audit": (
        "3e3d644e1bdf18df6b31385a41941c2d8a280af5357b53474d582df65a19c2d4"
    ),
    "stage_a_attempt1_failure_audit_correction_v2": (
        "49f4fa1a2079f0c4533e13c78e19724d67ac77dd7338e4fe13b17043c1864810"
    ),
    "failed_stage_a_title_route_selection": (
        "d5ec0a5f89fdd4d0fba05dc3954241fdca0aa62d7190ea3049ae1a8dfb94fad3"
    ),
    "failed_stage_a_pretitle_route_freeze": (
        "7cc9c9493251cf647f555cc2c157a13bf24428b678b2272412f409b882cc0925"
    ),
    "parent_selected": "825d5a0dc81a1c242d8e8fb250511f298876f8750ae7374d4657d49abe1fb918",
    "parent_outcomes": "973e90149f04a2545443e5ec117c1326eafee849c27748f0739d53f71782ac62",
    "parent_outcome_daily": "4a7f0351c19ca6584c5b686a3e90d833583a44910f96dc96f45f1d4db8fee93c",
    "issuer_fact_classifier": "127f62e551d4344ede9d41970ea7a6634f5f4b192fe2829a78eed8c72cf2da9d",
    "collector": "52eadae39e507667098ad389e7e44c60870c2a3f8722887f362218838ec098e3",
    "sealer": "dda822be65f78debacba0f1943a353fed0f6efe140a2f5ab94cbfd3e6c0039f8",
    "v29r2_frozen_preregistration": (
        "076566c5cd85158997d39e4690c090e98110e85597d55ebf7d5b4fa0e63a5a3a"
    ),
    "v29r2_development_result": "dc1539b1bfaf6de09c0be34483a226643f167232e5df0e5caa2c5a2d8b3fec4b",
    "retired_v29r1_semantic_blocker": (
        "df1654f143cf534c4101cd12671092e3dc61d475b439ff7ee75daca83cc5bd45"
    ),
}

INVENTORY_ROLE_ORDER = (
    "activation_audit",
    "correction_asset_builder",
    "stage_a_index_correction_r2_freeze",
    "rollforward_runner",
    "predecessor_asset_manifest",
    "predecessor_activation_audit",
    "announcement_route_index",
    "predecessor_asset_builder",
    "predecessor_rollforward_runner",
    "calendar_coverage_correction_r1_freeze",
    "stage_a_attempt1_failure_audit",
    "stage_a_attempt1_failure_audit_correction_v2",
    "failed_stage_a_title_route_selection",
    "failed_stage_a_pretitle_route_freeze",
    "parent_selected",
    "parent_outcomes",
    "parent_outcome_daily",
    "issuer_fact_classifier",
    "collector",
    "sealer",
    "v29r2_frozen_preregistration",
    "v29r2_development_result",
    "retired_v29r1_semantic_blocker",
)


class CorrectionAssetError(RuntimeError):
    """Fail closed on correction-wrapper identity or provenance drift."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CorrectionAssetError(message)


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
        raise CorrectionAssetError(f"invalid {label}: {path}") from exc
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
        raise CorrectionAssetError(f"refusing to overwrite {path}") from exc
    path.chmod(0o444)


def exact_top(root: Path, expected: set[str]) -> None:
    require(root.is_dir() and not root.is_symlink(), f"unsafe correction root: {root}")
    actual = {item.name for item in root.iterdir()}
    require(actual == expected, f"correction root inventory drifted: {sorted(actual)}")
    require(all(not item.is_symlink() for item in root.iterdir()), "correction root has symlink")


def file_fact(role: str, path: Path, *, content_parsed: bool) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"missing or unsafe {role}: {path}")
    return {
        "role": role,
        "path": str(path),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "identity_bytes_hashed_during_wrapper_build": True,
        "content_rows_or_semantics_parsed_during_wrapper_build": content_parsed,
    }


def require_hash(role: str, path: Path) -> None:
    require(
        path.is_file() and not path.is_symlink() and sha256(path) == EXPECTED_HASHES[role],
        f"frozen predecessor artifact drifted: {role}",
    )


def validate_failure_boundary() -> None:
    require_hash("stage_a_attempt1_failure_audit", FAILURE_AUDIT)
    require_hash("stage_a_attempt1_failure_audit_correction_v2", FAILURE_AUDIT_V2)
    failure = read_json(FAILURE_AUDIT, "Stage-A attempt-1 failure audit V1")
    correction = read_json(FAILURE_AUDIT_V2, "Stage-A attempt-1 failure audit V2")
    require(
        failure.get("status") == "ABORTED_BEFORE_TITLE_ACCESS"
        and failure.get("first_difference_proof", {}).get("only_difference")
        == "DataFrame index labels"
        and failure.get("stage_b_remained_closed") is True,
        "preserved Stage-A V1 failure evidence drifted",
    )
    flags = correction.get("precise_access_flags", {})
    require(
        correction.get("status") == "AUTHORITATIVE_DISCLOSURE_CORRECTION"
        and correction.get("superseded_wording_artifact", {}).get("sha256")
        == EXPECTED_HASHES["stage_a_attempt1_failure_audit"]
        and flags.get("sealed_title_bearing_sources_mechanically_read_or_reparsed_for_integrity")
        is True
        and flags.get("candidate_window_title_projection_before_key_freeze") is False
        and flags.get("candidate_window_title_classification_before_key_freeze") is False
        and flags.get("parent_outcome_bytes_hashed_for_identity") is True
        and flags.get("parent_outcomes_parquet_content_rows_parsed_or_viewed_by_attempt") is False
        and flags.get("parent_daily_parquet_content_rows_parsed_or_viewed_by_attempt") is False
        and flags.get("performance_statistics_computed_or_viewed_by_attempt") is False
        and flags.get("stage_b_started") is False,
        "authoritative Stage-A V2 failure disclosure drifted",
    )
    require(
        {item.name for item in FAILED_OUTPUT_ROOT.iterdir()} == {"stage_a"}
        and not (FAILED_OUTPUT_ROOT / "stage_a").is_symlink()
        and {item.name for item in (FAILED_OUTPUT_ROOT / "stage_a").iterdir()}
        == {"title_route_selection.parquet", "pretitle_route_freeze.json"},
        "failed Stage-A output is no longer the exact two-file pretitle state",
    )
    for directory in (FAILED_OUTPUT_ROOT, FAILED_OUTPUT_ROOT / "stage_a"):
        require(
            directory.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0,
            f"failed Stage-A evidence directory is writable: {directory}",
        )
    for role, path in (
        (
            "failed_stage_a_title_route_selection",
            FAILED_OUTPUT_ROOT / "stage_a/title_route_selection.parquet",
        ),
        (
            "failed_stage_a_pretitle_route_freeze",
            FAILED_OUTPUT_ROOT / "stage_a/pretitle_route_freeze.json",
        ),
    ):
        require_hash(role, path)
        require(
            path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0,
            f"failed Stage-A evidence is writable: {role}",
        )
    route_path = FAILED_OUTPUT_ROOT / "stage_a/title_route_selection.parquet"
    pretitle_path = FAILED_OUTPUT_ROOT / "stage_a/pretitle_route_freeze.json"
    route = pd.read_parquet(route_path)
    pretitle = read_json(pretitle_path, "failed Stage-A pretitle freeze")
    require(
        len(route) == 7925
        and list(route.columns) == [*predecessor_runner.ROUTE_COLUMNS, "causal_available_at"]
        and "title" not in route.columns
        and not route.announcement_key.astype(str).duplicated().any()
        and pretitle.get("stage") == "TITLE_FREE_CAUSAL_WINDOW_KEYS_FROZEN_BEFORE_TITLE_PROJECTION"
        and pretitle.get("route_rows") == 7925
        and pretitle.get("route_columns") == list(route.columns)
        and pretitle.get("route_sha256") == EXPECTED_HASHES["failed_stage_a_title_route_selection"]
        and pretitle.get("stage_a_process_outcome_content_opened") is False,
        "failed Stage-A title-free route/pretitle semantics drifted",
    )


def validate_correction(runner: Path) -> dict[str, Any]:
    correction = read_json(CORRECTION_R2, "Stage-A index correction R2")
    require(
        correction.get("status")
        == "FROZEN_AFTER_FAIL_CLOSED_PRETITLE_ATTEMPT_BEFORE_TITLE_CLASSIFICATION"
        and correction.get("trigger") == "PARQUET_RANGEINDEX_VS_SOURCE_INDEX_IDENTITY_CHECK"
        and correction.get("rule_or_threshold_changed") is False
        and correction.get("title_classification_had_started") is False
        and correction.get("stage_b_had_started") is False
        and correction.get("fix", {}).get("operation") == "reset_index(drop=True)"
        and correction.get("fix", {}).get("applied_before")
        == "exclusive title_route_selection parquet persistence",
        "Stage-A index correction semantics drifted",
    )
    expected = {
        "correction_asset_builder": Path(__file__).resolve(),
        "rollforward_runner": runner,
        "predecessor_asset_builder": PREDECESSOR_BUILDER,
        "predecessor_rollforward_runner": PREDECESSOR_RUNNER,
    }
    software = correction.get("software_identity", {})
    require(set(software) == set(expected), "R2 correction software roles drifted")
    for role, path in expected.items():
        require(
            Path(str(software[role].get("path", ""))).resolve() == path
            and software[role].get("sha256") == sha256(path),
            f"R2 correction software binding drifted: {role}",
        )
    predecessor = correction.get("predecessor_identity", {})
    require(
        predecessor.get("asset_id") == PREDECESSOR_ASSET_ID
        and predecessor.get("asset_manifest_sha256")
        == EXPECTED_HASHES["predecessor_asset_manifest"]
        and predecessor.get("failure_audit_sha256")
        == EXPECTED_HASHES["stage_a_attempt1_failure_audit"]
        and predecessor.get("failed_title_route_sha256")
        == EXPECTED_HASHES["failed_stage_a_title_route_selection"]
        and predecessor.get("failed_pretitle_freeze_sha256")
        == EXPECTED_HASHES["failed_stage_a_pretitle_route_freeze"],
        "R2 correction predecessor identity drifted",
    )
    return correction


def validate_dependencies(
    runner: Path, *, require_corrected_output_absent: bool = False
) -> dict[str, Any]:
    require(runner.resolve() == NEW_RUNNER and runner.is_file(), "unexpected corrected runner")
    if require_corrected_output_absent:
        require(
            not CORRECTED_OUTPUT_ROOT.exists(),
            f"corrected output root must be absent at wrapper build: {CORRECTED_OUTPUT_ROOT}",
        )
    require_hash("predecessor_asset_manifest", PREDECESSOR_ROOT / "asset_manifest.json")
    require_hash("predecessor_activation_audit", PREDECESSOR_ROOT / "activation_audit.json")
    require_hash("announcement_route_index", PREDECESSOR_ROOT / "announcement_route_index.parquet")
    require_hash("predecessor_asset_builder", PREDECESSOR_BUILDER)
    require_hash("predecessor_rollforward_runner", PREDECESSOR_RUNNER)
    require_hash("calendar_coverage_correction_r1_freeze", CORRECTION_R1)
    for role, path in (
        ("parent_selected", PARENT_SELECTED),
        ("parent_outcomes", PARENT_OUTCOMES),
        ("parent_outcome_daily", PARENT_DAILY),
        ("issuer_fact_classifier", CLASSIFIER),
        ("collector", COLLECTOR),
        ("sealer", SEALER),
        ("v29r2_frozen_preregistration", PREREG),
        ("v29r2_development_result", DEVELOPMENT_RESULT),
        ("retired_v29r1_semantic_blocker", SEMANTIC_BLOCKER),
    ):
        require_hash(role, path)
    predecessor_validation = predecessor_builder.validate(PREDECESSOR_ROOT)
    require(
        predecessor_validation.get("valid") is True
        and predecessor_validation.get("manifest_sha256")
        == EXPECTED_HASHES["predecessor_asset_manifest"]
        and predecessor_validation.get("route_rows") == 149545,
        "registered CY-062 predecessor no longer validates",
    )
    validate_failure_boundary()
    validate_correction(runner)
    registry = read_json(REGISTRY, "central registry")
    errors = registry_validator.validate_registry(registry, verify_paths=True, verify_hashes=True)
    require(not errors, f"central registry validation failed: {errors}")
    assets = [x for x in registry.get("assets", []) if x.get("asset_id") == PREDECESSOR_ASSET_ID]
    auths = [
        x
        for x in registry.get("bounded_authorizations", [])
        if x.get("authorization_id") == PREDECESSOR_AUTHORIZATION_ID
    ]
    require(len(assets) == len(auths) == 1, "registered CY-062 identity is missing")
    require(
        assets[0].get("lineage", {}).get("manifest_sha256")
        == EXPECTED_HASHES["predecessor_asset_manifest"]
        and auths[0].get("asset_id") == PREDECESSOR_ASSET_ID,
        "registered CY-062 identity drifted",
    )
    return {
        "predecessor_validation": predecessor_validation,
        "predecessor_registry_identity": {
            "asset_value_sha256": value_sha256(assets[0]),
            "authorization_value_sha256": value_sha256(auths[0]),
        },
    }


def external_paths() -> list[tuple[str, Path, bool]]:
    return [
        ("correction_asset_builder", Path(__file__).resolve(), False),
        ("stage_a_index_correction_r2_freeze", CORRECTION_R2, True),
        ("rollforward_runner", NEW_RUNNER, False),
        ("predecessor_asset_manifest", PREDECESSOR_ROOT / "asset_manifest.json", True),
        ("predecessor_activation_audit", PREDECESSOR_ROOT / "activation_audit.json", True),
        ("announcement_route_index", PREDECESSOR_ROOT / "announcement_route_index.parquet", True),
        ("predecessor_asset_builder", PREDECESSOR_BUILDER, False),
        ("predecessor_rollforward_runner", PREDECESSOR_RUNNER, False),
        ("calendar_coverage_correction_r1_freeze", CORRECTION_R1, True),
        ("stage_a_attempt1_failure_audit", FAILURE_AUDIT, True),
        ("stage_a_attempt1_failure_audit_correction_v2", FAILURE_AUDIT_V2, True),
        (
            "failed_stage_a_title_route_selection",
            FAILED_OUTPUT_ROOT / "stage_a/title_route_selection.parquet",
            True,
        ),
        (
            "failed_stage_a_pretitle_route_freeze",
            FAILED_OUTPUT_ROOT / "stage_a/pretitle_route_freeze.json",
            True,
        ),
        ("parent_selected", PARENT_SELECTED, True),
        ("parent_outcomes", PARENT_OUTCOMES, False),
        ("parent_outcome_daily", PARENT_DAILY, False),
        ("issuer_fact_classifier", CLASSIFIER, False),
        ("collector", COLLECTOR, False),
        ("sealer", SEALER, False),
        ("v29r2_frozen_preregistration", PREREG, False),
        ("v29r2_development_result", DEVELOPMENT_RESULT, False),
        ("retired_v29r1_semantic_blocker", SEMANTIC_BLOCKER, False),
    ]


def build_audit(deps: Mapping[str, Any], created_at: str) -> dict[str, Any]:
    return {
        "audit_schema": "CY_CORRECTION_WRAPPER_ACTIVATION_AUDIT_V1",
        "asset_id": ASSET_ID,
        "created_at": created_at,
        "status": "PASS_PENDING_CENTRAL_REGISTRATION",
        "predecessor_asset_id": PREDECESSOR_ASSET_ID,
        "predecessor_manifest_sha256": EXPECTED_HASHES["predecessor_asset_manifest"],
        "predecessor_route_sha256": EXPECTED_HASHES["announcement_route_index"],
        "predecessor_route_rows": 149545,
        "predecessor_registry_identity": deps["predecessor_registry_identity"],
        "failed_stage_a_evidence": {
            "failure_audit_sha256": EXPECTED_HASHES["stage_a_attempt1_failure_audit"],
            "authoritative_disclosure_correction_sha256": EXPECTED_HASHES[
                "stage_a_attempt1_failure_audit_correction_v2"
            ],
            "title_route_selection_sha256": EXPECTED_HASHES["failed_stage_a_title_route_selection"],
            "pretitle_route_freeze_sha256": EXPECTED_HASHES["failed_stage_a_pretitle_route_freeze"],
            "failure_was_before_candidate_title_projection_or_classification": True,
            "failure_was_before_outcome_or_daily_parquet_content_parse": True,
            "integrity_validation_mechanically_read_title_bearing_source_bytes": True,
            "identity_validation_hashed_parent_outcome_and_daily_bytes": True,
        },
        "correction": {
            "only_operation": "reset_index(drop=True) before title-free parquet persistence",
            "selector_or_threshold_changed": False,
            "source_or_causal_rule_changed": False,
            "execution_or_portfolio_rule_changed": False,
        },
        "stage_boundary": {
            "wrapper_build_mechanically_revalidates_title_bearing_predecessor_sources": True,
            "wrapper_build_candidate_title_projection_or_classification": False,
            "wrapper_build_hashes_outcome_and_daily_bytes": True,
            "wrapper_build_parses_outcome_or_daily_content_rows": False,
            "stage_a_requires_new_output_root": True,
            "stage_b_requires_expected_stage_a_sha256": True,
            "stage_b_requires_exclusive_read_only_pre_outcome_attempt_seal": True,
            "corrected_output_root": str(CORRECTED_OUTPUT_ROOT),
        },
    }


def inventory(asset_root: Path, audit_path: Path) -> list[dict[str, Any]]:
    result = [file_fact("activation_audit", audit_path, content_parsed=True)]
    result.extend(
        file_fact(role, path, content_parsed=content_parsed)
        for role, path, content_parsed in external_paths()
    )
    require(
        tuple(item["role"] for item in result) == INVENTORY_ROLE_ORDER,
        "correction inventory role/order drifted",
    )
    return result


def build_manifest(
    asset_root: Path,
    deps: Mapping[str, Any],
    created_at: str,
    bound_inventory: list[dict[str, Any]],
) -> dict[str, Any]:
    predecessor = deps["predecessor_validation"]
    return {
        "manifest_schema": "CY_IMMUTABLE_CORRECTION_WRAPPER_MANIFEST_V1",
        "asset_id": ASSET_ID,
        "status": "SEALED_PENDING_CENTRAL_REGISTRATION",
        "immutable": True,
        "manifest_self_included": False,
        "location": str(asset_root),
        "created_at": created_at,
        "component_assets": [PREDECESSOR_ASSET_ID],
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
        "predecessor": {
            "asset_id": PREDECESSOR_ASSET_ID,
            "root": str(PREDECESSOR_ROOT),
            "manifest_path": str(PREDECESSOR_ROOT / "asset_manifest.json"),
            "manifest_sha256": EXPECTED_HASHES["predecessor_asset_manifest"],
            "activation_audit_sha256": EXPECTED_HASHES["predecessor_activation_audit"],
            "route_path": str(PREDECESSOR_ROOT / "announcement_route_index.parquet"),
            "route_sha256": EXPECTED_HASHES["announcement_route_index"],
            "route_rows": predecessor["route_rows"],
            "source_snapshot_ids": predecessor["source_snapshot_ids"],
            "source_counts": predecessor["source_counts"],
            "registry_identity": deps["predecessor_registry_identity"],
        },
        "correction": {
            "failure_audit_path": str(FAILURE_AUDIT),
            "failure_audit_sha256": EXPECTED_HASHES["stage_a_attempt1_failure_audit"],
            "failure_audit_correction_v2_path": str(FAILURE_AUDIT_V2),
            "failure_audit_correction_v2_sha256": EXPECTED_HASHES[
                "stage_a_attempt1_failure_audit_correction_v2"
            ],
            "freeze_path": str(CORRECTION_R2),
            "freeze_sha256": sha256(CORRECTION_R2),
            "operation": "reset_index(drop=True) before persisting title-free route selection",
            "rule_or_threshold_changed": False,
        },
        "corrected_output_root": str(CORRECTED_OUTPUT_ROOT),
        "parent_selected": {
            "path": str(PARENT_SELECTED),
            "sha256": EXPECTED_HASHES["parent_selected"],
        },
        "route_index": {
            "path": str(PREDECESSOR_ROOT / "announcement_route_index.parquet"),
            "sha256": EXPECTED_HASHES["announcement_route_index"],
            "rows": predecessor["route_rows"],
        },
        "inventory": bound_inventory,
        "stage_boundary": {
            "stage_a_uses_predecessor_source_bytes_read_only": True,
            "stage_a_must_persist_range_indexed_title_free_keys_before_title_projection": True,
            "stage_a_may_parse_parent_outcomes_or_daily": False,
            "stage_b_requires_expected_stage_a_sha256": True,
            "stage_b_requires_exclusive_read_only_pre_outcome_attempt_seal": True,
        },
        "limitations": [
            "inherits CY-062 PIT-B current-enumeration revision/deletion-history limitations",
            "corrects only an implementation-only DataFrame index persistence check",
            "2022-2024 are dependent fixed-rule validation, not pristine OOS",
            "2025-2026 are post-selection temporal diagnostics, not pristine validation",
            "strict PIT-A, live trading, sizing and order generation remain prohibited",
        ],
    }


def build(asset_root: Path, runner: Path) -> dict[str, Any]:
    require(asset_root.resolve() == EXPECTED_ROOT, "unexpected CY-063 root")
    require(not asset_root.exists(), f"refusing non-pristine correction root: {asset_root}")
    deps = validate_dependencies(runner.resolve(), require_corrected_output_absent=True)
    asset_root.mkdir(parents=False, exist_ok=False)
    created_at = datetime.now(UTC).isoformat()
    audit = build_audit(deps, created_at)
    audit_path = asset_root / "activation_audit.json"
    write_json_exclusive(audit_path, audit)
    bound_inventory = inventory(asset_root, audit_path)
    manifest = build_manifest(asset_root, deps, created_at, bound_inventory)
    manifest_path = asset_root / "asset_manifest.json"
    write_json_exclusive(manifest_path, manifest)
    exact_top(asset_root, {"activation_audit.json", "asset_manifest.json"})
    asset_root.chmod(0o555)
    return {
        "asset_manifest": str(manifest_path),
        "asset_manifest_sha256": sha256(manifest_path),
        "activation_audit_sha256": sha256(audit_path),
        "predecessor_manifest_sha256": EXPECTED_HASHES["predecessor_asset_manifest"],
        "route_rows": deps["predecessor_validation"]["route_rows"],
    }


def validate(asset_root: Path) -> dict[str, Any]:
    require(asset_root.resolve() == EXPECTED_ROOT, "unexpected CY-063 root")
    exact_top(asset_root, {"activation_audit.json", "asset_manifest.json"})
    require(
        asset_root.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0,
        "CY-063 correction root is writable",
    )
    manifest_path = asset_root / "asset_manifest.json"
    audit_path = asset_root / "activation_audit.json"
    for path in (manifest_path, audit_path):
        require(
            path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0,
            f"correction wrapper is writable: {path.name}",
        )
    manifest = read_json(manifest_path, "CY-063 manifest")
    runner_fact = next(
        (
            item
            for item in manifest.get("inventory", [])
            if item.get("role") == "rollforward_runner"
        ),
        None,
    )
    require(runner_fact is not None, "CY-063 manifest lacks corrected runner")
    runner = Path(str(runner_fact.get("path", ""))).resolve()
    deps = validate_dependencies(runner)
    expected_audit = build_audit(deps, str(manifest.get("created_at")))
    require(read_json(audit_path, "CY-063 audit") == expected_audit, "CY-063 audit drifted")
    expected_inventory = inventory(asset_root, audit_path)
    expected_manifest = build_manifest(
        asset_root, deps, str(manifest.get("created_at")), expected_inventory
    )
    require(manifest == expected_manifest, "CY-063 manifest semantic reconstruction failed")
    return {
        "valid": True,
        "manifest_sha256": sha256(manifest_path),
        "activation_audit_sha256": sha256(audit_path),
        "predecessor_manifest_sha256": EXPECTED_HASHES["predecessor_asset_manifest"],
        "predecessor_registry_identity": deps["predecessor_registry_identity"],
        "route_rows": deps["predecessor_validation"]["route_rows"],
        "source_snapshot_ids": deps["predecessor_validation"]["source_snapshot_ids"],
        "source_counts": deps["predecessor_validation"]["source_counts"],
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
