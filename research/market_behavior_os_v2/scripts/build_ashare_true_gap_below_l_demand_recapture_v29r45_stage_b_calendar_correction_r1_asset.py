#!/usr/bin/env python3
"""Build the metadata-only CY-048 operational-correction reference wrapper.

This builder decodes no Parquet row and copies no Parquet byte. It hashes the
exact referenced files and reads their footers through the frozen CY-046
activation verifier, binds the pre-performance BLOCKED predecessor, and
publishes two immutable JSON files.
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
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path("/Users/linmei/Documents/CY-supermind-v6-autonomous-20260830")
RUNNER = REPO_ROOT / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_true_gap_below_l_demand_recapture_sequential_v29r45_"
    "stage_b_calendar_correction_r1.py"
)
RUNNER_SHA256 = "9d4f03694606e3135392bbcb9eae909bbe55644a7cee17baf86022d3e8d6f569"
ASSET_ID = "CY-048"
TARGET_ROOT = Path(
    "/Users/linmei/Documents/CY/data/staging/"
    "CY-048-DEMAND-RECAPTURE-V29R45-STAGE-B-CALENDAR-CORRECTION-R1-V1"
)
BUILD_LOCK = TARGET_ROOT.parent / ".CY-048-CALENDAR-CORRECTION-R1.lock"
EXACT_FILENAMES = {"asset_manifest.json", "activation_audit.json"}


class CY048BuildError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise CY048BuildError(f"hash target is not one regular non-symlink file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_correction_runner() -> ModuleType:
    if sha256(RUNNER) != RUNNER_SHA256:
        raise CY048BuildError("correction runner hash drift before import")
    module_name = "_v29r45_calendar_correction_runner_9d4f0369"
    spec = importlib.util.spec_from_file_location(module_name, RUNNER)
    if spec is None or spec.loader is None:
        raise CY048BuildError("cannot load correction runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


CORRECTION = _load_correction_runner()
BASE = CORRECTION.BASE


def _cy048_absent_from_registry() -> None:
    registry = CORRECTION.load_json(BASE.REGISTRY, "data registry")
    assets = registry.get("assets")
    authorizations = registry.get("bounded_authorizations")
    if not isinstance(assets, list) or not isinstance(authorizations, list):
        raise CY048BuildError("registry lacks assets or bounded authorizations")
    if any(item.get("asset_id") == ASSET_ID for item in assets if isinstance(item, dict)):
        raise CY048BuildError("CY-048 is already registered")
    if any(
        item.get("authorization_id") == CORRECTION.AUTHORIZATION_ID
        for item in authorizations
        if isinstance(item, dict)
    ):
        raise CY048BuildError("CY-048 authorization is already registered")


def _verify_reference_metadata() -> dict[str, Any]:
    if sha256(RUNNER) != RUNNER_SHA256:
        raise CY048BuildError("correction runner hash drift")
    CORRECTION._verify_preregistration()
    base_activation = CORRECTION.BASE_VERIFY_ACTIVATION()
    if BASE.normalized_json_sha256(base_activation) != CORRECTION.BASE_ACTIVATION_NORMALIZED_SHA256:
        raise CY048BuildError("CY-046 activation normalized hash drift")
    CORRECTION.verify_predecessor(base_activation)
    observed = base_activation.get("files")
    expected = {item["role"]: item["sha256"] for item in CORRECTION.EXPECTED_REFERENCE_FILES}
    if observed != expected:
        raise CY048BuildError("CY-046 seven-file content identity drift")
    for item in CORRECTION.EXPECTED_REFERENCE_FILES:
        path = Path(item["path"])
        identity = path.lstat()
        if (
            stat.S_ISLNK(identity.st_mode)
            or not stat.S_ISREG(identity.st_mode)
            or stat.S_IMODE(identity.st_mode) != 0o444
            or not BASE.is_user_immutable(path)
            or identity.st_size != item["size"]
            or sha256(path) != item["sha256"]
        ):
            raise CY048BuildError(f"referenced CY-046 file seal drift: {item['role']}")
    return base_activation


def _probe_publication_capabilities() -> None:
    parent = BASE.reject_symlink_components(TARGET_ROOT.parent, "CY-048 wrapper parent")
    probe = Path(tempfile.mkdtemp(prefix=".CY-048-SEAL-PROBE-", dir=parent))
    try:
        BASE.preflight_slot_capabilities(probe)
    finally:
        if probe.exists():
            shutil.rmtree(probe)


def metadata_plan(*, require_absent: bool) -> dict[str, Any]:
    if require_absent:
        parent = BASE.reject_symlink_components(TARGET_ROOT.parent, "CY-048 wrapper parent")
        if not stat.S_ISDIR(parent.lstat().st_mode):
            raise CY048BuildError("CY-048 wrapper parent is not a directory")
        if os.path.lexists(TARGET_ROOT):
            raise CY048BuildError("CY-048 canonical target already exists")
        if os.path.lexists(BUILD_LOCK):
            raise CY048BuildError("CY-048 build lock already exists")
        _cy048_absent_from_registry()
    activation = _verify_reference_metadata()
    return {
        "asset_id": ASSET_ID,
        "status": "PASS_METADATA_ONLY",
        "target_root": str(TARGET_ROOT),
        "correction_runner_sha256": RUNNER_SHA256,
        "correction_preregistration_sha256": CORRECTION.PREREGISTRATION_SHA256,
        "base_activation_normalized_sha256": BASE.normalized_json_sha256(activation),
        "predecessor_attempt_sha256": CORRECTION.PREDECESSOR_ATTEMPT_SHA256,
        "predecessor_result_sha256": CORRECTION.PREDECESSOR_RESULT_SHA256,
        "referenced_files": len(CORRECTION.EXPECTED_REFERENCE_FILES),
        "parquet_rows_decoded": False,
        "parquet_bytes_copied": False,
        "outcome_or_return_rows_opened": False,
        "returns_computed": False,
        "output_written": False,
    }


def _manifest() -> dict[str, Any]:
    return {
        "asset_id": ASSET_ID,
        "authorization_id": CORRECTION.AUTHORIZATION_ID,
        "kind": "operational_correction_immutable_reference_wrapper",
        "status": "PASS",
        "coverage": {"start": "2018-01-01", "end": "2021-12-31"},
        "pit_contract": CORRECTION.PIT_CONTRACT,
        "protocol": {
            "path": str(CORRECTION.PREREGISTRATION),
            "sha256": CORRECTION.PREREGISTRATION_SHA256,
            "runner_path": str(RUNNER),
            "runner_sha256": RUNNER_SHA256,
            "builder_path": str(Path(__file__).resolve()),
            "builder_sha256": sha256(Path(__file__).resolve()),
        },
        "referenced_asset": {
            "asset_id": "CY-046",
            "root": str(BASE.CY046_ROOT),
            "manifest_path": str(BASE.ASSET_MANIFEST),
            "manifest_sha256": CORRECTION.BASE_MANIFEST_SHA256,
            "activation_audit_path": str(BASE.ACTIVATION_AUDIT),
            "activation_audit_sha256": CORRECTION.BASE_ACTIVATION_AUDIT_SHA256,
            "registry_asset_normalized_sha256": CORRECTION.BASE_ASSET_NORMALIZED_SHA256,
            "registry_authorization_normalized_sha256": (
                CORRECTION.BASE_AUTHORIZATION_NORMALIZED_SHA256
            ),
            "activation_normalized_sha256": CORRECTION.BASE_ACTIVATION_NORMALIZED_SHA256,
        },
        "referenced_files": CORRECTION.EXPECTED_REFERENCE_FILES,
        "predecessor_blocked_attempt": {
            "attempt_seal_path": str(CORRECTION.PREDECESSOR_ATTEMPT),
            "attempt_seal_sha256": CORRECTION.PREDECESSOR_ATTEMPT_SHA256,
            "blocked_result_path": str(CORRECTION.PREDECESSOR_RESULT),
            "blocked_result_sha256": CORRECTION.PREDECESSOR_RESULT_SHA256,
            "performance_gates_computed": False,
        },
        "correction_contract": {
            "consumer_change_allowed": False,
            "new_output_root": str(CORRECTION.OUTPUT_ROOT),
            "normalizer_change_allowed": False,
            "only_change": "RUN_ARM_PASSES_RAW_CALENDAR_TO_EXISTING_CONSUMERS",
            "operational_experiment": CORRECTION.CORRECTION_EXPERIMENT,
            "protocol_version": CORRECTION.CORRECTION_PROTOCOL_VERSION,
            "scientific_change": "NONE",
            "strategy_or_accounting_change_allowed": False,
        },
        "content_contract": {
            "manifest_does_not_hash_activation_audit": True,
            "outcome_or_return_rows_opened": False,
            "parquet_bytes_copied": False,
            "parquet_rows_decoded": False,
            "post_2021_rows_opened": False,
            "referenced_parquet_files": 7,
            "returns_computed": False,
        },
    }


def _audit(manifest_sha256: str) -> dict[str, Any]:
    return {
        "asset_id": ASSET_ID,
        "status": "PASS",
        "gate_pass": True,
        "manifest_path": "asset_manifest.json",
        "manifest_sha256": manifest_sha256,
        "builder_sha256": sha256(Path(__file__).resolve()),
        "runner_sha256": RUNNER_SHA256,
        "preregistration_sha256": CORRECTION.PREREGISTRATION_SHA256,
        "predecessor_attempt_sha256": CORRECTION.PREDECESSOR_ATTEMPT_SHA256,
        "predecessor_result_sha256": CORRECTION.PREDECESSOR_RESULT_SHA256,
        "referenced_asset_activation_verified_metadata_only": True,
        "referenced_files_verified": 7,
        "parquet_rows_decoded": False,
        "parquet_bytes_copied": False,
        "outcome_or_return_rows_opened": False,
        "post_2021_rows_opened": False,
        "returns_computed": False,
        "pit_contract": CORRECTION.PIT_CONTRACT,
    }


def verify_built_metadata() -> dict[str, Any]:
    base_activation = _verify_reference_metadata()
    manifest, audit = CORRECTION._verify_wrapper_files(base_activation)
    return {
        "asset_id": ASSET_ID,
        "status": "PASS_METADATA_ONLY_VERIFY",
        "root": str(TARGET_ROOT),
        "manifest_sha256": sha256(TARGET_ROOT / "asset_manifest.json"),
        "activation_audit_sha256": sha256(TARGET_ROOT / "activation_audit.json"),
        "referenced_files": len(manifest["referenced_files"]),
        "parquet_rows_decoded": audit["parquet_rows_decoded"],
        "parquet_bytes_copied": audit["parquet_bytes_copied"],
        "outcome_or_return_rows_opened": audit["outcome_or_return_rows_opened"],
    }


def build() -> dict[str, Any]:
    metadata_plan(require_absent=True)
    TARGET_ROOT.parent.mkdir(parents=True, exist_ok=True)
    lock_fd: int | None = None
    temporary: Path | None = None
    try:
        lock_fd = os.open(BUILD_LOCK, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
        os.fsync(lock_fd)
        _probe_publication_capabilities()
        temporary = Path(
            tempfile.mkdtemp(prefix=".CY-048-CALENDAR-CORRECTION-R1-", dir=TARGET_ROOT.parent)
        )
        manifest = _manifest()
        manifest_path = temporary / "asset_manifest.json"
        BASE.write_json(manifest_path, manifest)
        audit_path = temporary / "activation_audit.json"
        BASE.write_json(audit_path, _audit(sha256(manifest_path)))
        if {path.name for path in temporary.iterdir()} != EXACT_FILENAMES:
            raise CY048BuildError("CY-048 temporary inventory drift")
        for path in temporary.iterdir():
            path.chmod(0o444)
        BASE.fsync_directory(temporary)
        _verify_reference_metadata()
        _cy048_absent_from_registry()
        if os.path.lexists(TARGET_ROOT):
            raise CY048BuildError("CY-048 appeared before no-replace publication")
        BASE.publish_directory_no_replace(temporary, TARGET_ROOT)
        temporary = None
        BASE.freeze_published_tree(TARGET_ROOT, EXACT_FILENAMES)
        BASE.fsync_directory(TARGET_ROOT.parent)
        return verify_built_metadata()
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        try:
            BUILD_LOCK.unlink()
        except FileNotFoundError:
            pass
        if temporary is not None and temporary.exists():
            shutil.rmtree(temporary)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("metadata-dry-run", "build", "verify-metadata"),
        default="metadata-dry-run",
    )
    args = parser.parse_args()
    if args.mode == "metadata-dry-run":
        payload = metadata_plan(require_absent=True)
    elif args.mode == "build":
        payload = build()
    else:
        payload = verify_built_metadata()
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
