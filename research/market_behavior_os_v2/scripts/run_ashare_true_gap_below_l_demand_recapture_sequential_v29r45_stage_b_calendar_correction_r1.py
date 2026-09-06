#!/usr/bin/env python3
"""One operational retry for the frozen V29R4/V29R5 Stage-B experiment.

The predecessor consumed V29R4 without computing performance because its
orchestrator normalized the market calendar before passing it to three
functions whose unchanged contract requires the raw calendar schema.  This
runner hash-verifies and imports that immutable implementation, keeps the
calendar raw at the orchestration boundary, and delegates every scientific,
execution, accounting and publication operation to the frozen base module.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import stat
import sys
from collections.abc import Iterable
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path("/Users/linmei/Documents/CY-supermind-v6-autonomous-20260830")
BASE_RUNNER = REPO_ROOT / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_true_gap_below_l_demand_recapture_sequential_v29r45_stage_b.py"
)
BASE_RUNNER_SHA256 = "e406c671fccdc6558c8bf9f51ec6df39a2c92b01fea4b663c96358a105b929e0"
BASE_PREREGISTRATION_SHA256 = "0280a61744b64b1b9bf4f028ce3e3b237bd2324e9447b6de8e088bfac8cca4d7"
BASE_BUILDER_SHA256 = "5a082f61bd1166907dc8a1180ba132c1f25788f90d44e0db96666249b01ecf44"

CORRECTION_EXPERIMENT = (
    "ASHARE-TRUE-GAP-BELOW-L-DEMAND-RECAPTURE-SEQUENTIAL-V29R45-STAGE-B-CALENDAR-CORRECTION-R1"
)
CORRECTION_PROTOCOL_VERSION = "V1_OPERATIONAL_CORRECTION_PRE_OUTCOME"
PREREGISTRATION = REPO_ROOT / (
    "research/market_behavior_os_v2/experiments/"
    "ASHARE-TRUE-GAP-BELOW-L-DEMAND-RECAPTURE-SEQUENTIAL-V29R45_"
    "stage_b_calendar_correction_r1_preregistration.json"
)
PREREGISTRATION_SHA256 = "69b20bf0cf10376972624fdca66b0ee580f1e5e99c5ef0d8904af4dd19a918ca"
ASSET_ID = "CY-048"
AUTHORIZATION_ID = (
    "CYQ-AUTH-ASHARE-DEMAND-RECAPTURE-V29R45-STAGE-B-CALENDAR-CORRECTION-R1-2018-2021-V1"
)
WRAPPER_ROOT = Path(
    "/Users/linmei/Documents/CY/data/staging/"
    "CY-048-DEMAND-RECAPTURE-V29R45-STAGE-B-CALENDAR-CORRECTION-R1-V1"
)
WRAPPER_MANIFEST = WRAPPER_ROOT / "asset_manifest.json"
WRAPPER_AUDIT = WRAPPER_ROOT / "activation_audit.json"
OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_demand_recapture_v29r45_"
    "stage_b_calendar_correction_r1"
)

PREDECESSOR_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_demand_recapture_v29r45_stage_b/v29r4"
)
PREDECESSOR_PARENT = PREDECESSOR_ROOT.parent
PREDECESSOR_V29R5 = PREDECESSOR_PARENT / "v29r5"
PREDECESSOR_ATTEMPT = PREDECESSOR_ROOT / "attempt_seal.json"
PREDECESSOR_ATTEMPT_SHA256 = "9c56d919e35f4e544763a10ff0f36cc49d4ade0f12c5b2e6fba6020411eed9ee"
PREDECESSOR_RESULT = PREDECESSOR_ROOT / "result.json"
PREDECESSOR_RESULT_SHA256 = "9b0b62a5e5dfd237766aaa6ec1079bd0f34ac203278fd21fcb15f7463b1d6fa9"
EXPECTED_BLOCKER = "market calendar misses columns: ['calendar_index']"
BASE_MANIFEST_SHA256 = "2b1d6756a9c0401e47a2616eeac78b424c30eccbbd51bd3339caf86ec46addd0"
BASE_ACTIVATION_AUDIT_SHA256 = "82d5b944d1840817eb76592264430abcc87a5d15f5443725fcc3a9c87d4be46c"
BASE_ASSET_NORMALIZED_SHA256 = "eda8d1e6bb5ac1ae037490c02e85f0cb807cca10927b8a656290ed0456f89bc9"
BASE_AUTHORIZATION_NORMALIZED_SHA256 = (
    "43926b77d0428757a95d0aa2dc03dcb4d1f2290d6b48817fec1893a019aee690"
)
BASE_ACTIVATION_NORMALIZED_SHA256 = (
    "edb4fefc9b58ba6240068d6ef0f8e1f573986bb43aa51a889ab707601427f4c5"
)
BASE_ASSET_ROOT = Path(
    "/Users/linmei/Documents/CY/data/staging/CY-046-DEMAND-RECAPTURE-V29R45-STAGE-B-2018-2021-V1"
)

EXPECTED_REFERENCE_FILES = [
    {
        "role": "v29r4_cap25_identity",
        "path": str(BASE_ASSET_ROOT / "v29r4_cap25_identity.parquet"),
        "sha256": "cfa5ef5343e046c7be469c9d0df5c6a592d506fcac5c18874df964fb71a88005",
        "size": 19030,
        "rows": 251,
        "row_groups": 1,
        "schema_sha256": "1610b077cefaeb77ede54bea1eec7a976862b23d7c25c5aa776f8dce0871068c",
    },
    {
        "role": "v29r5_cap25_identity",
        "path": str(BASE_ASSET_ROOT / "v29r5_cap25_identity.parquet"),
        "sha256": "fa70e3716b9bb868fe78caa55e461930d2c225f4bd0a22c2150916d5702957b9",
        "size": 19392,
        "rows": 255,
        "row_groups": 1,
        "schema_sha256": "1610b077cefaeb77ede54bea1eec7a976862b23d7c25c5aa776f8dce0871068c",
    },
    {
        "role": "candidate_admin_bounds",
        "path": str(BASE_ASSET_ROOT / "candidate_admin_bounds.parquet"),
        "sha256": "697ae03699245d06a427cec6610e1992ee96fa7f29c4dff4adfcb99c135d569b",
        "size": 13668,
        "rows": 506,
        "row_groups": 1,
        "schema_sha256": "61625a38f92652c282c77e92022eaf09174f93d5ebd9aa8ae00673f0c70e7294",
    },
    {
        "role": "candidate_daily_path",
        "path": str(BASE_ASSET_ROOT / "candidate_daily_path.parquet"),
        "sha256": "5e002401e0b20ec14c9cfeec4bc3b38acbb88a2d54c15639c1c62d6a32233890",
        "size": 212517,
        "rows": 12625,
        "row_groups": 1,
        "schema_sha256": "1acc93324be6d8c933ecd9640719c611fb487e88779fd377be00a28c7304bbe6",
    },
    {
        "role": "candidate_execution_window0",
        "path": str(BASE_ASSET_ROOT / "candidate_execution_window0.parquet"),
        "sha256": "ce2bf8a376eb72143e7e9e5ffe804574f37faccf856523a285564f53f048e66a",
        "size": 246527,
        "rows": 12120,
        "row_groups": 1,
        "schema_sha256": "8d7d99391f794c8a4bcde1c824e06e243cd82632e8b8cbd576a45374ff133760",
    },
    {
        "role": "candidate_action_events",
        "path": str(BASE_ASSET_ROOT / "candidate_action_events.parquet"),
        "sha256": "cccad05457305ef898771528321ad025168fd4924b63f86a71c57a75a0e3e687",
        "size": 34521,
        "rows": 0,
        "row_groups": 1,
        "schema_sha256": "bb410c244bbe394ee8a43bcd78fdbfc18100400e9398b3fb8e2ad4f2a1833a6a",
    },
    {
        "role": "market_calendar",
        "path": str(BASE_ASSET_ROOT / "market_calendar.parquet"),
        "sha256": "d5dabc0c51769e9be1348d8a4effb0b05816e1cfea51a73046ca9e7b9d9aed2a",
        "size": 7689,
        "rows": 973,
        "row_groups": 1,
        "schema_sha256": "989f45929eb7870977ced35107a181977de3a020a4466f2e8d37ffe24d56affe",
    },
]

PIT_CONTRACT = {
    "grade": "B",
    "publication_allowed": False,
    "qd010_revision_history_complete": False,
    "strict_pit_eligible": False,
    "usage": "RESEARCH_CONDITIONAL_HYPOTHESIS_ONLY",
}


class CorrectionError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise CorrectionError(f"hash target is not one regular non-symlink file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorrectionError(f"cannot read {label}: {path}") from exc
    if not isinstance(value, dict):
        raise CorrectionError(f"{label} is not a JSON object")
    return value


def _load_frozen_base() -> ModuleType:
    if sha256(BASE_RUNNER) != BASE_RUNNER_SHA256:
        raise CorrectionError("immutable base runner hash drift before import")
    module_name = "_v29r45_stage_b_frozen_base_e406c671"
    spec = importlib.util.spec_from_file_location(module_name, BASE_RUNNER)
    if spec is None or spec.loader is None:
        raise CorrectionError("cannot load immutable base runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


BASE = _load_frozen_base()
BASE_VERIFY_ACTIVATION = BASE.verify_activation
BASE_EXPERIMENT = BASE.EXPERIMENT


def _only(rows: Iterable[dict[str, Any]], label: str) -> dict[str, Any]:
    values = list(rows)
    if len(values) != 1:
        raise CorrectionError(f"expected exactly one {label}, found {len(values)}")
    return values[0]


def _assert_immutable_file(path: Path, label: str) -> None:
    identity = path.lstat()
    if (
        stat.S_ISLNK(identity.st_mode)
        or not stat.S_ISREG(identity.st_mode)
        or stat.S_IMODE(identity.st_mode) != 0o444
        or not BASE.is_user_immutable(path)
    ):
        raise CorrectionError(f"{label} is not immutable 0444 regular data")


def verify_predecessor(base_activation: dict[str, Any]) -> dict[str, str]:
    for path, label in (
        (PREDECESSOR_PARENT, "predecessor parent"),
        (PREDECESSOR_ROOT, "predecessor V29R4 root"),
        (PREDECESSOR_V29R5, "predecessor unopened V29R5 slot"),
        (PREDECESSOR_ATTEMPT, "predecessor attempt"),
        (PREDECESSOR_RESULT, "predecessor result"),
    ):
        BASE.reject_symlink_components(path, label)
    parent_identity = PREDECESSOR_PARENT.lstat()
    v29r5_identity = PREDECESSOR_V29R5.lstat()
    if (
        stat.S_ISLNK(parent_identity.st_mode)
        or not stat.S_ISDIR(parent_identity.st_mode)
        or stat.S_IMODE(parent_identity.st_mode) != 0o555
        or not BASE.is_user_immutable(PREDECESSOR_PARENT)
        or {path.name for path in PREDECESSOR_PARENT.iterdir()} != {"v29r4", "v29r5"}
        or stat.S_ISLNK(v29r5_identity.st_mode)
        or not stat.S_ISDIR(v29r5_identity.st_mode)
        or stat.S_IMODE(v29r5_identity.st_mode) != 0o700
        or BASE.is_user_immutable(PREDECESSOR_V29R5)
        or any(PREDECESSOR_V29R5.iterdir())
    ):
        raise CorrectionError("predecessor parent or unopened V29R5 slot drift")
    root_identity = PREDECESSOR_ROOT.lstat()
    if (
        stat.S_ISLNK(root_identity.st_mode)
        or not stat.S_ISDIR(root_identity.st_mode)
        or stat.S_IMODE(root_identity.st_mode) != 0o555
        or not BASE.is_user_immutable(PREDECESSOR_ROOT)
        or {path.name for path in PREDECESSOR_ROOT.iterdir()}
        != {"attempt_seal.json", "result.json"}
    ):
        raise CorrectionError("predecessor BLOCKED directory seal drift")
    _assert_immutable_file(PREDECESSOR_ATTEMPT, "predecessor attempt")
    _assert_immutable_file(PREDECESSOR_RESULT, "predecessor result")
    if (
        sha256(PREDECESSOR_ATTEMPT) != PREDECESSOR_ATTEMPT_SHA256
        or sha256(PREDECESSOR_RESULT) != PREDECESSOR_RESULT_SHA256
    ):
        raise CorrectionError("predecessor BLOCKED hash drift")
    attempt = load_json(PREDECESSOR_ATTEMPT, "predecessor attempt")
    result = load_json(PREDECESSOR_RESULT, "predecessor result")
    if (
        set(result)
        != {
            "activation",
            "aggregate_publication_status",
            "arm",
            "attempt_seal_sha256",
            "blocker",
            "experiment",
            "performance_gates_computed",
            "pit_contract",
            "verdict",
        }
        or result.get("aggregate_publication_status") != "BLOCKED"
        or result.get("verdict") != "UNRESOLVED"
        or result.get("performance_gates_computed") is not False
        or result.get("blocker") != EXPECTED_BLOCKER
        or result.get("arm") != "v29r4"
        or result.get("experiment") != BASE_EXPERIMENT
        or result.get("attempt_seal_sha256") != PREDECESSOR_ATTEMPT_SHA256
        or result.get("pit_contract") != PIT_CONTRACT
        or result.get("activation") != base_activation
        or "summary" in result
        or "output_hashes" in result
    ):
        raise CorrectionError("predecessor is not the exact pre-performance BLOCKED result")
    if (
        set(attempt)
        != {
            "activation_audit_sha256",
            "activation_sha256",
            "arm",
            "cohort_hashes",
            "experiment",
            "manifest_sha256",
            "post_2021_access",
            "preregistration_sha256",
            "protocol_arm",
            "protocol_version",
            "runner_sha256",
            "status",
            "v29r4_failure_dependency",
        }
        or attempt.get("activation_sha256") != BASE_ACTIVATION_NORMALIZED_SHA256
        or attempt.get("runner_sha256") != BASE_RUNNER_SHA256
        or attempt.get("preregistration_sha256") != BASE_PREREGISTRATION_SHA256
        or attempt.get("manifest_sha256") != BASE_MANIFEST_SHA256
        or attempt.get("activation_audit_sha256") != BASE_ACTIVATION_AUDIT_SHA256
        or attempt.get("experiment") != BASE_EXPERIMENT
        or attempt.get("protocol_arm") != "V29R4_CAP25"
        or attempt.get("v29r4_failure_dependency") is not None
        or attempt.get("post_2021_access") != "PROHIBITED"
    ):
        raise CorrectionError("predecessor attempt seal semantics drift")
    return {
        "attempt_seal_sha256": PREDECESSOR_ATTEMPT_SHA256,
        "blocked_result_sha256": PREDECESSOR_RESULT_SHA256,
    }


def _verify_preregistration() -> dict[str, Any]:
    if sha256(PREREGISTRATION) != PREREGISTRATION_SHA256:
        raise CorrectionError("calendar-correction preregistration hash drift")
    prereg = load_json(PREREGISTRATION, "calendar-correction preregistration")
    predecessor = prereg.get("predecessor_blocked_attempt", {})
    correction = prereg.get("only_allowed_functional_change", {})
    operational = prereg.get("allowed_operational_identity_changes", {})
    wrapper = prereg.get("required_reference_wrapper", {})
    if (
        prereg.get("correction_experiment") != CORRECTION_EXPERIMENT
        or prereg.get("base_experiment") != BASE_EXPERIMENT
        or prereg.get("status")
        != "FROZEN_OPERATIONAL_CORRECTION_AWAITING_CY048_ACTIVATION_AND_RUNNER_REVIEW"
        or prereg.get("protocol_version") != CORRECTION_PROTOCOL_VERSION
        or prereg.get("development") != ["2018-01-01", "2021-12-31"]
        or prereg.get("post_2021_access") != "PROHIBITED"
        or prereg.get("scientific_change") != "NONE"
        or predecessor.get("performance_information_revealed") is not False
        or predecessor.get("completed_scientific_performance_attempts") != 0
        or predecessor.get("v29r5_unlock_authorized") is not False
        or predecessor.get("old_slot_replay_authorized") is not False
        or predecessor.get("old_v29r5_slot_required_state") != "EMPTY_0700_NOT_IMMUTABLE"
        or predecessor.get("blocked_result", {}).get("sha256") != PREDECESSOR_RESULT_SHA256
        or predecessor.get("attempt_seal", {}).get("sha256") != PREDECESSOR_ATTEMPT_SHA256
        or correction.get("normalizer_change_allowed") is not False
        or correction.get("consumer_change_allowed") is not False
        or correction.get("strategy_or_accounting_change_allowed") is not False
        or operational
        != {
            "asset_id": ASSET_ID,
            "authorization_id": AUTHORIZATION_ID,
            "experiment": CORRECTION_EXPERIMENT,
            "new_output_root": str(OUTPUT_ROOT),
            "protocol_version": CORRECTION_PROTOCOL_VERSION,
            "scientific_effect": "NONE",
        }
        or wrapper.get("asset_id") != ASSET_ID
        or wrapper.get("authorization_id") != AUTHORIZATION_ID
        or wrapper.get("parquet_rows_decoded_by_builder") is not False
        or wrapper.get("parquet_bytes_copied_by_builder") is not False
        or prereg.get("pit_contract") != PIT_CONTRACT
    ):
        raise CorrectionError("calendar-correction preregistration semantics drift")
    return prereg


def _verify_wrapper_files(base_activation: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    for path, label in (
        (WRAPPER_ROOT, "CY-048 wrapper root"),
        (WRAPPER_MANIFEST, "CY-048 manifest"),
        (WRAPPER_AUDIT, "CY-048 activation audit"),
    ):
        BASE.reject_symlink_components(path, label)
    root_identity = WRAPPER_ROOT.lstat()
    if (
        stat.S_ISLNK(root_identity.st_mode)
        or not stat.S_ISDIR(root_identity.st_mode)
        or stat.S_IMODE(root_identity.st_mode) != 0o555
        or not BASE.is_user_immutable(WRAPPER_ROOT)
        or {path.name for path in WRAPPER_ROOT.iterdir()}
        != {"asset_manifest.json", "activation_audit.json"}
    ):
        raise CorrectionError("CY-048 wrapper root is not exact immutable 0555")
    _assert_immutable_file(WRAPPER_MANIFEST, "CY-048 manifest")
    _assert_immutable_file(WRAPPER_AUDIT, "CY-048 activation audit")
    manifest = load_json(WRAPPER_MANIFEST, "CY-048 manifest")
    audit = load_json(WRAPPER_AUDIT, "CY-048 activation audit")
    protocol = manifest.get("protocol", {})
    referenced = manifest.get("referenced_asset", {})
    predecessor = manifest.get("predecessor_blocked_attempt", {})
    correction = manifest.get("correction_contract", {})
    content = manifest.get("content_contract", {})
    builder_path = Path(str(protocol.get("builder_path", "")))
    expected_referenced = {
        "activation_audit_path": str(BASE.ACTIVATION_AUDIT),
        "activation_audit_sha256": BASE_ACTIVATION_AUDIT_SHA256,
        "activation_normalized_sha256": BASE_ACTIVATION_NORMALIZED_SHA256,
        "asset_id": "CY-046",
        "manifest_path": str(BASE.ASSET_MANIFEST),
        "manifest_sha256": BASE_MANIFEST_SHA256,
        "registry_asset_normalized_sha256": BASE_ASSET_NORMALIZED_SHA256,
        "registry_authorization_normalized_sha256": (BASE_AUTHORIZATION_NORMALIZED_SHA256),
        "root": str(BASE.CY046_ROOT),
    }
    if (
        set(manifest)
        != {
            "asset_id",
            "authorization_id",
            "content_contract",
            "correction_contract",
            "coverage",
            "kind",
            "pit_contract",
            "predecessor_blocked_attempt",
            "protocol",
            "referenced_asset",
            "referenced_files",
            "status",
        }
        or manifest.get("asset_id") != ASSET_ID
        or manifest.get("authorization_id") != AUTHORIZATION_ID
        or manifest.get("kind") != "operational_correction_immutable_reference_wrapper"
        or manifest.get("status") != "PASS"
        or manifest.get("coverage") != {"start": "2018-01-01", "end": "2021-12-31"}
        or manifest.get("pit_contract") != PIT_CONTRACT
        or protocol.get("path") != str(PREREGISTRATION)
        or protocol.get("sha256") != PREREGISTRATION_SHA256
        or protocol.get("runner_path") != str(Path(__file__).resolve())
        or protocol.get("runner_sha256") != sha256(Path(__file__).resolve())
        or not builder_path.is_file()
        or protocol.get("builder_sha256") != sha256(builder_path)
        or referenced != expected_referenced
        or BASE.normalized_json_sha256(base_activation) != BASE_ACTIVATION_NORMALIZED_SHA256
        or manifest.get("referenced_files") != EXPECTED_REFERENCE_FILES
        or predecessor
        != {
            "attempt_seal_path": str(PREDECESSOR_ATTEMPT),
            "attempt_seal_sha256": PREDECESSOR_ATTEMPT_SHA256,
            "blocked_result_path": str(PREDECESSOR_RESULT),
            "blocked_result_sha256": PREDECESSOR_RESULT_SHA256,
            "performance_gates_computed": False,
        }
        or correction
        != {
            "consumer_change_allowed": False,
            "new_output_root": str(OUTPUT_ROOT),
            "normalizer_change_allowed": False,
            "only_change": "RUN_ARM_PASSES_RAW_CALENDAR_TO_EXISTING_CONSUMERS",
            "operational_experiment": CORRECTION_EXPERIMENT,
            "protocol_version": CORRECTION_PROTOCOL_VERSION,
            "scientific_change": "NONE",
            "strategy_or_accounting_change_allowed": False,
        }
        or content
        != {
            "manifest_does_not_hash_activation_audit": True,
            "outcome_or_return_rows_opened": False,
            "parquet_bytes_copied": False,
            "parquet_rows_decoded": False,
            "post_2021_rows_opened": False,
            "referenced_parquet_files": 7,
            "returns_computed": False,
        }
    ):
        raise CorrectionError("CY-048 manifest semantics drift")
    actual_manifest_sha = sha256(WRAPPER_MANIFEST)
    if (
        set(audit)
        != {
            "asset_id",
            "builder_sha256",
            "gate_pass",
            "manifest_path",
            "manifest_sha256",
            "outcome_or_return_rows_opened",
            "parquet_bytes_copied",
            "parquet_rows_decoded",
            "pit_contract",
            "post_2021_rows_opened",
            "predecessor_attempt_sha256",
            "predecessor_result_sha256",
            "preregistration_sha256",
            "referenced_asset_activation_verified_metadata_only",
            "referenced_files_verified",
            "returns_computed",
            "runner_sha256",
            "status",
        }
        or audit.get("asset_id") != ASSET_ID
        or audit.get("status") != "PASS"
        or audit.get("gate_pass") is not True
        or audit.get("manifest_path") != "asset_manifest.json"
        or audit.get("manifest_sha256") != actual_manifest_sha
        or audit.get("builder_sha256") != sha256(builder_path)
        or audit.get("runner_sha256") != sha256(Path(__file__).resolve())
        or audit.get("preregistration_sha256") != PREREGISTRATION_SHA256
        or audit.get("predecessor_attempt_sha256") != PREDECESSOR_ATTEMPT_SHA256
        or audit.get("predecessor_result_sha256") != PREDECESSOR_RESULT_SHA256
        or audit.get("referenced_asset_activation_verified_metadata_only") is not True
        or audit.get("referenced_files_verified") != 7
        or audit.get("parquet_rows_decoded") is not False
        or audit.get("parquet_bytes_copied") is not False
        or audit.get("outcome_or_return_rows_opened") is not False
        or audit.get("post_2021_rows_opened") is not False
        or audit.get("returns_computed") is not False
        or audit.get("pit_contract") != PIT_CONTRACT
    ):
        raise CorrectionError("CY-048 activation audit semantics drift")
    return manifest, audit


def _verify_registry(
    manifest: dict[str, Any], audit: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    registry = load_json(BASE.REGISTRY, "data registry")
    assets = registry.get("assets")
    authorizations = registry.get("bounded_authorizations")
    if not isinstance(assets, list) or not isinstance(authorizations, list):
        raise CorrectionError("registry lacks assets or bounded authorizations")
    asset = _only(
        (item for item in assets if item.get("asset_id") == ASSET_ID),
        "CY-048 registry asset",
    )
    authorization = _only(
        (item for item in authorizations if item.get("authorization_id") == AUTHORIZATION_ID),
        "CY-048 bounded authorization",
    )
    lineage = asset.get("lineage", {})
    coverage = asset.get("coverage", {})
    manifest_sha = sha256(WRAPPER_MANIFEST)
    audit_sha = sha256(WRAPPER_AUDIT)
    if (
        asset.get("kind") != "operational_correction_immutable_reference_wrapper"
        or asset.get("status") != "RESEARCH_CONDITIONAL"
        or asset.get("pit_grade") != "B"
        or asset.get("physical_state") != "MATERIALIZED"
        or Path(str(asset.get("location", ""))) != WRAPPER_ROOT
        or coverage.get("authorized_start") != "2018-01-01"
        or coverage.get("authorized_end") != "2021-12-31"
        or coverage.get("referenced_parquet_files") != 7
        or coverage.get("v29r4_cap25_rows") != 251
        or coverage.get("v29r5_cap25_rows") != 255
        or lineage.get("record_available_at") is not True
        or lineage.get("record_snapshot_id") is not True
        or lineage.get("immutable_manifest") is not True
        or lineage.get("manifest_path") != str(WRAPPER_MANIFEST)
        or lineage.get("manifest_sha256") != manifest_sha
        or lineage.get("component_assets") != ["CY-046"]
        or lineage.get("bounded_authorization_id") != AUTHORIZATION_ID
    ):
        raise CorrectionError("CY-048 registry asset semantics drift")
    bound_manifest = authorization.get("bound_manifest", {})
    bound_protocol = authorization.get("bound_protocol", {})
    bound_strategy = authorization.get("bound_strategy", {})
    scope = authorization.get("scope", {})
    artifact_rows = authorization.get("bound_artifacts")
    if not isinstance(artifact_rows, list):
        raise CorrectionError("CY-048 authorization lacks bound artifacts")
    by_role = {
        item.get("role"): item
        for item in artifact_rows
        if isinstance(item, dict) and isinstance(item.get("role"), str)
    }
    expected_artifacts = {
        "activation_audit": (WRAPPER_AUDIT, audit_sha),
        "reference_wrapper_builder": (
            Path(str(manifest.get("protocol", {}).get("builder_path", ""))),
            str(manifest.get("protocol", {}).get("builder_sha256", "")),
        ),
        "predecessor_blocked_result": (
            PREDECESSOR_RESULT,
            PREDECESSOR_RESULT_SHA256,
        ),
        "predecessor_attempt_seal": (
            PREDECESSOR_ATTEMPT,
            PREDECESSOR_ATTEMPT_SHA256,
        ),
        "immutable_base_runner": (BASE_RUNNER, BASE_RUNNER_SHA256),
    }
    artifacts_valid = bool(
        len(artifact_rows) == len(expected_artifacts)
        and set(by_role) == set(expected_artifacts)
        and all(
            by_role[role].get("path") == str(path) and by_role[role].get("sha256") == digest
            for role, (path, digest) in expected_artifacts.items()
        )
    )
    if (
        authorization.get("asset_id") != ASSET_ID
        or authorization.get("source_asset_id") != "CY-046"
        or authorization.get("dependency_asset_id") != "CY-046"
        or authorization.get("dependency_status") != "RESEARCH_CONDITIONAL"
        or authorization.get("purpose") != "ASHARE_FROZEN_DEVELOPMENT_OUTCOME_ATTACHMENT"
        or authorization.get("operational_correction_authorized") is not True
        or authorization.get("calendar_orchestration_correction_only") is not True
        or authorization.get("scientific_change_allowed") is not False
        or authorization.get("authorized_operational_replay_count") != 1
        or authorization.get("completed_scientific_performance_attempts_before_correction") != 0
        or authorization.get("corrected_v29r5_requires_corrected_v29r4_complete_failure")
        is not True
        or authorization.get("correction_blocked_retry_authorized") is not False
        or authorization.get("outcome_attachment_authorized") is not True
        or authorization.get("charts_authorized") is not False
        or authorization.get("validation_authorized") is not False
        or authorization.get("post_2021_read_authorized") is not False
        or authorization.get("strict_pit_claim_authorized") is not False
        or authorization.get("publication_allowed") is not False
        or authorization.get("candidate_reselection_authorized") is not False
        or authorization.get("raw_competing_cohort_outcomes_authorized") is not False
        or authorization.get("portfolio_replay_authorized") is not True
        or authorization.get("old_output_root_write_authorized") is not False
        or authorization.get("old_blocked_result_unlocks_v29r5") is not False
        or authorization.get("current_survivor_fallback_allowed") is not False
        or authorization.get("record_level_available_at_available") is not False
        or authorization.get("authorized_arms") != ["V29R4_CAP25", "V29R5_CAP25"]
        or authorization.get("sequential_order") != ["V29R4_CAP25", "V29R5_CAP25"]
        or scope.get("start") != "2018-01-01"
        or scope.get("end") != "2021-12-31"
        or scope.get("frozen_candidate_rows") != 506
        or scope.get("v29r4_cap25_rows") != 251
        or scope.get("v29r5_cap25_rows") != 255
        or bound_manifest != {"path": str(WRAPPER_MANIFEST), "sha256": manifest_sha}
        or bound_protocol
        != {
            "path": str(PREREGISTRATION),
            "sha256": PREREGISTRATION_SHA256,
            "runner_path": str(Path(__file__).resolve()),
            "runner_sha256": sha256(Path(__file__).resolve()),
        }
        or bound_strategy
        != {
            "path": str(PREREGISTRATION),
            "sha256": PREREGISTRATION_SHA256,
        }
        or not artifacts_valid
    ):
        raise CorrectionError("CY-048 bounded authorization semantics drift")
    return asset, authorization


def verify_activation() -> dict[str, Any]:
    if sha256(BASE_RUNNER) != BASE_RUNNER_SHA256:
        raise CorrectionError("immutable base runner hash drift")
    if sha256(BASE.PREREG) != BASE_PREREGISTRATION_SHA256:
        raise CorrectionError("immutable base preregistration hash drift")
    base_builder = REPO_ROOT / (
        "research/market_behavior_os_v2/scripts/"
        "build_ashare_true_gap_below_l_demand_recapture_v29r45_stage_b_asset.py"
    )
    if sha256(base_builder) != BASE_BUILDER_SHA256:
        raise CorrectionError("immutable base builder hash drift")
    prereg = _verify_preregistration()
    base_activation = BASE_VERIFY_ACTIVATION()
    if (
        base_activation.get("runner_sha256") != BASE_RUNNER_SHA256
        or base_activation.get("preregistration_sha256") != BASE_PREREGISTRATION_SHA256
        or base_activation.get("manifest_sha256") != BASE_MANIFEST_SHA256
        or base_activation.get("activation_audit_sha256") != BASE_ACTIVATION_AUDIT_SHA256
        or base_activation.get("registry_asset_normalized_sha256") != BASE_ASSET_NORMALIZED_SHA256
        or base_activation.get("registry_authorization_normalized_sha256")
        != BASE_AUTHORIZATION_NORMALIZED_SHA256
        or base_activation.get("pit_contract") != PIT_CONTRACT
    ):
        raise CorrectionError("immutable CY-046 base activation drift")
    predecessor = verify_predecessor(base_activation)
    manifest, audit = _verify_wrapper_files(base_activation)
    asset, authorization = _verify_registry(manifest, audit)
    wrapper_asset_sha = BASE.normalized_json_sha256(asset)
    correction_authorization_sha = BASE.normalized_json_sha256(authorization)
    result = dict(base_activation)
    result.update(
        {
            "mode": "METADATA_ONLY_OPERATIONAL_CORRECTION_NO_PARQUET_ROWS_DECODED",
            "runner_sha256": sha256(Path(__file__).resolve()),
            "preregistration_sha256": PREREGISTRATION_SHA256,
            "base_runner_sha256": BASE_RUNNER_SHA256,
            "base_preregistration_sha256": BASE_PREREGISTRATION_SHA256,
            "base_manifest_sha256": BASE_MANIFEST_SHA256,
            "base_activation_audit_sha256": BASE_ACTIVATION_AUDIT_SHA256,
            "base_registry_asset_normalized_sha256": BASE_ASSET_NORMALIZED_SHA256,
            "base_registry_authorization_normalized_sha256": (BASE_AUTHORIZATION_NORMALIZED_SHA256),
            "reference_wrapper_asset_id": ASSET_ID,
            "reference_wrapper_manifest_sha256": sha256(WRAPPER_MANIFEST),
            "reference_wrapper_activation_audit_sha256": sha256(WRAPPER_AUDIT),
            "manifest_sha256": sha256(WRAPPER_MANIFEST),
            "activation_audit_sha256": sha256(WRAPPER_AUDIT),
            "registry_asset_normalized_sha256": wrapper_asset_sha,
            "registry_authorization_normalized_sha256": (correction_authorization_sha),
            "correction_authorization_normalized_sha256": (correction_authorization_sha),
            "reference_wrapper_registry_asset_normalized_sha256": wrapper_asset_sha,
            "predecessor_blocked_attempt": predecessor,
            "operational_correction": {
                "correction_experiment": prereg["correction_experiment"],
                "only_change": "RUN_ARM_PASSES_RAW_CALENDAR_TO_EXISTING_CONSUMERS",
                "performance_information_revealed_by_predecessor": False,
                "scientific_change": "NONE",
            },
        }
    )
    return result


def run_arm(arm: str) -> dict[str, Any]:
    """Frozen base orchestration with exactly one change: keep calendar raw."""
    if arm not in BASE.ARM_CONFIG:
        raise CorrectionError(f"unknown arm {arm}")
    activation = verify_activation()
    BASE.OUTPUT_ROOT = OUTPUT_ROOT
    BASE.EXPERIMENT = CORRECTION_EXPERIMENT
    BASE.PROTOCOL_VERSION = CORRECTION_PROTOCOL_VERSION
    BASE.initialize_output_anchor()
    dependency = BASE._verify_v29r4_failure(activation) if arm == "v29r5" else None
    attempt = BASE._publish_attempt(arm, activation, dependency)
    try:
        config = BASE.ARM_CONFIG[arm]
        candidates = BASE.normalize_candidates(
            BASE._projected_read(config["identity"], BASE.IDENTITY_COLUMNS),
            expected_rows=config["expected_rows"],
            expected_by_year=config["expected_by_year"],
        )
        if candidates.protocol_arm.ne(config["protocol_arm"]).any():
            raise CorrectionError("identity protocol arm drift")
        raw_calendar = BASE._projected_read(BASE.MARKET_CALENDAR, BASE.CALENDAR_COLUMNS)
        censored = BASE.administrative_censor(candidates, raw_calendar)
        bad_calendar = censored.admin_status.eq("UNRESOLVED_SIGNAL_CALENDAR")
        if bad_calendar.any():
            raise CorrectionError("candidate signal is absent from frozen calendar")
        eligible = censored.loc[~censored.administratively_censored].copy()
        admin_bounds = BASE._read_arm_rows(
            BASE.ADMIN_BOUNDS, BASE.ADMIN_BOUND_COLUMNS, config["protocol_arm"]
        )
        BASE.verify_admin_bounds(censored, admin_bounds, raw_calendar, config["protocol_arm"])
        daily_entry, execution_entry, entry_actions = BASE._load_entry_inputs(
            eligible, config["protocol_arm"]
        )
        entries = BASE.build_entries(
            censored,
            daily_entry,
            execution_entry,
            entry_actions,
            config["protocol_arm"],
        )

        def resolve(row: Any) -> dict[str, Any]:
            daily, execution, actions = BASE._load_one_candidate_path(row)
            return BASE.evaluate_one_outcome(row, daily, execution, actions, raw_calendar)

        portfolio, outcomes = BASE.replay_online_portfolio(entries, resolve)
        summary = BASE.summarize(censored, entries, outcomes, portfolio)
        return BASE._write_result_bundle(
            arm,
            activation,
            attempt,
            censored,
            entries,
            outcomes,
            portfolio,
            summary,
        )
    except Exception as exc:
        return BASE._write_blocked_result(arm, activation, attempt, exc)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("verify-activation", "run-v29r4", "run-v29r5"),
        default="verify-activation",
    )
    args = parser.parse_args()
    if args.mode == "verify-activation":
        payload = verify_activation()
    elif args.mode == "run-v29r4":
        payload = run_arm("v29r4")
    else:
        payload = run_arm("v29r5")
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
