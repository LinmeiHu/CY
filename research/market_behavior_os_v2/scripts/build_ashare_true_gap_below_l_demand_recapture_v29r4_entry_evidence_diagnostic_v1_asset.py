#!/usr/bin/env python3
"""Build the metadata-only CY-050 entry-diagnostic reference wrapper.

The builder decodes no Parquet row and copies no Parquet byte. It verifies the
exact CY-048 activation and consumed corrected-R4 bundle, then publishes two
immutable JSON control files for one outcome-blind entry-evidence diagnostic.
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
    "run_ashare_true_gap_below_l_demand_recapture_v29r4_"
    "entry_evidence_diagnostic_v1.py"
)
RUNNER_SHA256 = "dfb7a809e48a5209b499918b983352f7e08fb699d3e229a8570a47f768920bb4"
ASSET_ID = "CY-050"
TARGET_ROOT = Path(
    "/Users/linmei/Documents/CY/data/staging/"
    "CY-050-DEMAND-RECAPTURE-V29R4-ENTRY-EVIDENCE-DIAGNOSTIC-V1"
)
BUILD_LOCK = TARGET_ROOT.parent / ".CY-050-ENTRY-EVIDENCE-DIAGNOSTIC.lock"
EXACT_FILENAMES = {"asset_manifest.json", "activation_audit.json"}


class CY050BuildError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise CY050BuildError(f"hash target is not one regular non-symlink file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_runner() -> ModuleType:
    if sha256(RUNNER) != RUNNER_SHA256:
        raise CY050BuildError("entry-diagnostic runner hash drift before import")
    module_name = "_v29r4_entry_evidence_diagnostic_dfb7a809"
    spec = importlib.util.spec_from_file_location(module_name, RUNNER)
    if spec is None or spec.loader is None:
        raise CY050BuildError("cannot load entry-diagnostic runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


DIAGNOSTIC = _load_runner()
BASE = DIAGNOSTIC.BASE


def _cy050_absent_from_registry() -> None:
    registry = DIAGNOSTIC.load_json(BASE.REGISTRY, "data registry")
    assets = registry.get("assets")
    authorizations = registry.get("bounded_authorizations")
    if not isinstance(assets, list) or not isinstance(authorizations, list):
        raise CY050BuildError("registry lacks assets or bounded authorizations")
    if any(item.get("asset_id") == ASSET_ID for item in assets if isinstance(item, dict)):
        raise CY050BuildError("CY-050 is already registered")
    if any(
        item.get("authorization_id") == DIAGNOSTIC.AUTHORIZATION_ID
        for item in authorizations
        if isinstance(item, dict)
    ):
        raise CY050BuildError("CY-050 authorization is already registered")


def _verify_reference_metadata() -> tuple[dict[str, Any], dict[str, str]]:
    if sha256(RUNNER) != RUNNER_SHA256:
        raise CY050BuildError("entry-diagnostic runner hash drift")
    activation, predecessor = DIAGNOSTIC.verify_source_state()
    if activation.get("reference_wrapper_asset_id") != "CY-048":
        raise CY050BuildError("CY-048 activation identity drift")
    if predecessor != {
        "attempt_seal_sha256": DIAGNOSTIC.CORRECTED_ATTEMPT_SHA256,
        "blocked_result_sha256": DIAGNOSTIC.CORRECTED_RESULT_SHA256,
    }:
        raise CY050BuildError("consumed corrected-R4 identity drift")
    return activation, predecessor


def _probe_publication_capabilities() -> None:
    parent = BASE.reject_symlink_components(TARGET_ROOT.parent, "CY-050 wrapper parent")
    probe = Path(tempfile.mkdtemp(prefix=".CY-050-SEAL-PROBE-", dir=parent))
    try:
        BASE.preflight_slot_capabilities(probe)
    finally:
        if probe.exists():
            shutil.rmtree(probe)


def metadata_plan(*, require_absent: bool) -> dict[str, Any]:
    if require_absent:
        parent = BASE.reject_symlink_components(TARGET_ROOT.parent, "CY-050 wrapper parent")
        if not stat.S_ISDIR(parent.lstat().st_mode):
            raise CY050BuildError("CY-050 wrapper parent is not a directory")
        if os.path.lexists(TARGET_ROOT):
            raise CY050BuildError("CY-050 canonical target already exists")
        if os.path.lexists(BUILD_LOCK):
            raise CY050BuildError("CY-050 build lock already exists")
        _cy050_absent_from_registry()
    activation, predecessor = _verify_reference_metadata()
    return {
        "asset_id": ASSET_ID,
        "status": "PASS_METADATA_ONLY",
        "target_root": str(TARGET_ROOT),
        "runner_sha256": RUNNER_SHA256,
        "preregistration_sha256": DIAGNOSTIC.PREREGISTRATION_SHA256,
        "base_correction_activation_sha256": BASE.normalized_json_sha256(activation),
        "predecessor_attempt_sha256": predecessor["attempt_seal_sha256"],
        "predecessor_result_sha256": predecessor["blocked_result_sha256"],
        "parquet_rows_decoded": False,
        "parquet_bytes_copied": False,
        "outcome_or_return_rows_opened": False,
        "post_2021_rows_opened": False,
        "output_written": False,
    }


def _manifest() -> dict[str, Any]:
    return {
        "asset_id": ASSET_ID,
        "authorization_id": DIAGNOSTIC.AUTHORIZATION_ID,
        "kind": "outcome_blind_entry_evidence_diagnostic_reference_wrapper",
        "status": "PASS",
        "coverage": {"start": "2018-01-01", "end": "2021-12-31"},
        "pit_contract": DIAGNOSTIC.PIT_CONTRACT,
        "protocol": {
            "path": str(DIAGNOSTIC.PREREGISTRATION),
            "sha256": DIAGNOSTIC.PREREGISTRATION_SHA256,
            "runner_path": str(RUNNER),
            "runner_sha256": RUNNER_SHA256,
            "builder_path": str(Path(__file__).resolve()),
            "builder_sha256": sha256(Path(__file__).resolve()),
        },
        "referenced_assets": {
            "CY-046": {
                "activation_audit_sha256": (DIAGNOSTIC.CORRECTION.BASE_ACTIVATION_AUDIT_SHA256),
                "manifest_sha256": DIAGNOSTIC.CORRECTION.BASE_MANIFEST_SHA256,
                "root": str(DIAGNOSTIC.CORRECTION.BASE_ASSET_ROOT),
            },
            "CY-048": {
                "activation_audit_sha256": DIAGNOSTIC.sha256(DIAGNOSTIC.CORRECTION.WRAPPER_AUDIT),
                "manifest_sha256": DIAGNOSTIC.sha256(DIAGNOSTIC.CORRECTION.WRAPPER_MANIFEST),
                "root": str(DIAGNOSTIC.CORRECTION.WRAPPER_ROOT),
            },
        },
        "predecessor": {
            "attempt_seal_path": str(DIAGNOSTIC.CORRECTED_ATTEMPT),
            "attempt_seal_sha256": DIAGNOSTIC.CORRECTED_ATTEMPT_SHA256,
            "blocked_result_path": str(DIAGNOSTIC.CORRECTED_RESULT),
            "blocked_result_sha256": DIAGNOSTIC.CORRECTED_RESULT_SHA256,
            "replay_boundary_crossed": True,
        },
        "content_contract": {
            "builder_outcome_or_return_rows_opened": False,
            "builder_parquet_bytes_copied": False,
            "builder_parquet_rows_decoded": False,
            "diagnostic_arm": "V29R4_CAP25_ONLY",
            "diagnostic_maximum_entry_session_offset": 0,
            "diagnostic_outcome_paths_authorized": False,
            "diagnostic_performance_replay_authorized": False,
            "post_2021_rows_authorized": False,
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
        "preregistration_sha256": DIAGNOSTIC.PREREGISTRATION_SHA256,
        "predecessor_attempt_sha256": DIAGNOSTIC.CORRECTED_ATTEMPT_SHA256,
        "predecessor_result_sha256": DIAGNOSTIC.CORRECTED_RESULT_SHA256,
        "builder_parquet_rows_decoded": False,
        "builder_parquet_bytes_copied": False,
        "builder_outcome_or_return_rows_opened": False,
        "post_2021_rows_opened": False,
        "pit_contract": DIAGNOSTIC.PIT_CONTRACT,
    }


def verify_built_metadata() -> dict[str, Any]:
    _verify_reference_metadata()
    _manifest_value, audit = DIAGNOSTIC._verify_wrapper_files()
    return {
        "asset_id": ASSET_ID,
        "status": "PASS_METADATA_ONLY_VERIFY",
        "root": str(TARGET_ROOT),
        "manifest_sha256": sha256(TARGET_ROOT / "asset_manifest.json"),
        "activation_audit_sha256": sha256(TARGET_ROOT / "activation_audit.json"),
        "parquet_rows_decoded": audit["builder_parquet_rows_decoded"],
        "parquet_bytes_copied": audit["builder_parquet_bytes_copied"],
        "outcome_or_return_rows_opened": audit["builder_outcome_or_return_rows_opened"],
        "post_2021_rows_opened": audit["post_2021_rows_opened"],
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
            tempfile.mkdtemp(
                prefix=".CY-050-ENTRY-EVIDENCE-DIAGNOSTIC-",
                dir=TARGET_ROOT.parent,
            )
        )
        manifest = _manifest()
        manifest_path = temporary / "asset_manifest.json"
        BASE.write_json(manifest_path, manifest)
        audit_path = temporary / "activation_audit.json"
        BASE.write_json(audit_path, _audit(sha256(manifest_path)))
        if {path.name for path in temporary.iterdir()} != EXACT_FILENAMES:
            raise CY050BuildError("CY-050 temporary inventory drift")
        for path in temporary.iterdir():
            path.chmod(0o444)
        BASE.fsync_directory(temporary)
        _verify_reference_metadata()
        _cy050_absent_from_registry()
        if os.path.lexists(TARGET_ROOT):
            raise CY050BuildError("CY-050 appeared before no-replace publication")
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
