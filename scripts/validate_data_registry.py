#!/usr/bin/env python3
"""Validate the CYQ-GAME authoritative data asset registry."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = PROJECT_ROOT / "configs" / "data_asset_registry.json"
REQUIRED_ASSET_FIELDS = {
    "asset_id",
    "name",
    "kind",
    "status",
    "pit_grade",
    "physical_state",
    "location",
    "source",
    "coverage",
    "schema_and_units",
    "quality_evidence",
    "lineage",
    "allowed_uses",
    "blocked_uses",
    "activation_gates",
}
PATH_REQUIRED_STATES = {"MATERIALIZED", "GENERATED_MUTABLE"}
NO_PATH_STATES = {"VIRTUAL", "CANDIDATE_NOT_MATERIALIZED", "NOT_AVAILABLE"}
INPUT_CAPABLE_STATUS = {"RESEARCH_CONDITIONAL"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_registry(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("registry root must be a JSON object")
    return value


def validate_registry(
    registry: dict[str, Any],
    *,
    verify_paths: bool = True,
    verify_hashes: bool = True,
) -> list[str]:
    errors: list[str] = []
    for field in (
        "schema_version",
        "registry_id",
        "updated_at",
        "authority",
        "pit_grade_definitions",
        "status_definitions",
        "global_gate",
        "assets",
        "bounded_authorizations",
        "evidence",
        "change_log",
    ):
        if field not in registry:
            errors.append(f"registry is missing required field: {field}")

    assets = registry.get("assets", [])
    statuses = registry.get("status_definitions", {})
    grades = registry.get("pit_grade_definitions", {})
    if not isinstance(assets, list) or not assets:
        errors.append("assets must be a non-empty list")
        return errors

    asset_ids: list[str] = []
    for asset in assets:
        if isinstance(asset, dict) and isinstance(asset.get("asset_id"), str):
            asset_ids.append(asset["asset_id"])
    duplicates = sorted(item for item, count in Counter(asset_ids).items() if count > 1)
    if duplicates:
        errors.append(f"duplicate asset_id values: {', '.join(duplicates)}")

    for index, asset in enumerate(assets):
        if not isinstance(asset, dict):
            errors.append(f"assets[{index}] must be an object")
            continue
        asset_id = str(asset.get("asset_id", f"assets[{index}]"))
        missing = sorted(REQUIRED_ASSET_FIELDS - asset.keys())
        if missing:
            errors.append(f"{asset_id}: missing fields: {', '.join(missing)}")
        status = asset.get("status")
        grade = asset.get("pit_grade")
        physical_state = asset.get("physical_state")
        location = asset.get("location")
        if status not in statuses:
            errors.append(f"{asset_id}: unknown status {status!r}")
        if grade not in grades:
            errors.append(f"{asset_id}: unknown PIT grade {grade!r}")
        if physical_state in PATH_REQUIRED_STATES and not location:
            errors.append(f"{asset_id}: {physical_state} requires a location")
        if physical_state in NO_PATH_STATES and location is not None:
            errors.append(f"{asset_id}: {physical_state} must not declare a location")
        if verify_paths and physical_state in PATH_REQUIRED_STATES and location:
            if not Path(location).exists():
                errors.append(f"{asset_id}: materialized path does not exist: {location}")
        for list_field in ("allowed_uses", "blocked_uses", "activation_gates"):
            value = asset.get(list_field)
            if not isinstance(value, list) or not value:
                errors.append(f"{asset_id}: {list_field} must be a non-empty list")
        lineage = asset.get("lineage")
        if not isinstance(lineage, dict):
            errors.append(f"{asset_id}: lineage must be an object")
        elif not {"record_available_at", "record_snapshot_id", "immutable_manifest"}.issubset(
            lineage
        ):
            errors.append(
                f"{asset_id}: lineage must record available_at, snapshot_id, and manifest status"
            )
        else:
            _validate_lineage_manifests(
                lineage,
                asset_id,
                errors,
                verify_paths=verify_paths,
                verify_hashes=verify_hashes,
            )
        if status in INPUT_CAPABLE_STATUS and not asset.get("activation_gates"):
            errors.append(f"{asset_id}: input-capable asset has no activation gates")
        if grade == "A" and status != "RESEARCH_CONDITIONAL":
            errors.append(f"{asset_id}: PIT A asset must use RESEARCH_CONDITIONAL status")
        for fingerprint in asset.get("fingerprints", []):
            _validate_fingerprint(
                fingerprint,
                f"{asset_id} fingerprint",
                errors,
                verify_paths=verify_paths,
                verify_hashes=verify_hashes,
            )

    _validate_bounded_authorizations(
        registry.get("bounded_authorizations"),
        assets={
            asset["asset_id"]: asset
            for asset in assets
            if isinstance(asset, dict) and "asset_id" in asset
        },
        errors=errors,
        verify_paths=verify_paths,
        verify_hashes=verify_hashes,
    )

    evidence = registry.get("evidence", [])
    evidence_ids: list[str] = []
    for item in evidence:
        if isinstance(item, dict) and isinstance(item.get("evidence_id"), str):
            evidence_ids.append(item["evidence_id"])
    duplicate_evidence = sorted(item for item, count in Counter(evidence_ids).items() if count > 1)
    if duplicate_evidence:
        errors.append(f"duplicate evidence_id values: {', '.join(duplicate_evidence)}")
    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            errors.append(f"evidence[{index}] must be an object")
            continue
        label = str(item.get("evidence_id", f"evidence[{index}]"))
        if not item.get("role"):
            errors.append(f"{label}: evidence role is required")
        _validate_fingerprint(
            item,
            label,
            errors,
            verify_paths=verify_paths,
            verify_hashes=verify_hashes,
        )

    gate = registry.get("global_gate", {})
    for field in ("strict_archival_pit_ready", "free_causal_research_ready", "backtest_authorized"):
        if not isinstance(gate.get(field), bool):
            errors.append(f"global_gate.{field} must be boolean")
    if gate.get("strict_archival_pit_ready") and not gate.get("free_causal_research_ready"):
        errors.append(
            "strict_archival_pit_ready cannot be true while free_causal_research_ready is false"
        )
    if gate.get("backtest_authorized") and not gate.get("free_causal_research_ready"):
        errors.append("backtest_authorized cannot be true before free_causal_research_ready")

    authority = registry.get("authority", {})
    if authority.get("fail_closed") is not True:
        errors.append("authority.fail_closed must be true")
    if authority.get("silent_substitution_forbidden") is not True:
        errors.append("authority.silent_substitution_forbidden must be true")
    if not registry.get("change_log"):
        errors.append("change_log must contain at least one append-only entry")
    return errors


def _validate_bounded_authorizations(
    value: Any,
    *,
    assets: dict[str, dict[str, Any]],
    errors: list[str],
    verify_paths: bool,
    verify_hashes: bool,
) -> None:
    if not isinstance(value, list):
        errors.append("bounded_authorizations must be a list")
        return
    ids = [
        item.get("authorization_id")
        for item in value
        if isinstance(item, dict) and isinstance(item.get("authorization_id"), str)
    ]
    duplicates = sorted(item for item, count in Counter(ids).items() if count > 1)
    if duplicates:
        errors.append("duplicate bounded authorization_id values: " + ", ".join(duplicates))
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"bounded_authorizations[{index}] must be an object")
            continue
        label = str(item.get("authorization_id", f"bounded_authorizations[{index}]"))
        required = {
            "authorization_id",
            "purpose",
            "asset_id",
            "dependency_asset_id",
            "dependency_status",
            "scope",
            "bound_manifest",
            "bound_artifacts",
            "bound_strategy",
            "current_survivor_fallback_allowed",
            "record_level_available_at_available",
            "allowed_uses",
            "blocked_uses",
            "known_limitations",
        }
        missing = sorted(required - item.keys())
        if missing:
            errors.append(f"{label}: missing fields: {', '.join(missing)}")
            continue
        if item["purpose"] != "CHINEXT_PIT_B_RESEARCH":
            errors.append(f"{label}: unsupported bounded purpose {item['purpose']!r}")
        asset = assets.get(item["asset_id"])
        if asset is None or asset.get("status") != "RESEARCH_CONDITIONAL":
            errors.append(f"{label}: asset must be registered RESEARCH_CONDITIONAL")
        elif asset.get("lineage", {}).get("bounded_authorization_id") != label:
            errors.append(f"{label}: asset lineage must bind this authorization_id")
        dependency = assets.get(item["dependency_asset_id"])
        if dependency is None:
            errors.append(f"{label}: dependency asset is unregistered")
        elif dependency.get("status") != item["dependency_status"]:
            errors.append(f"{label}: dependency status does not match registry")
        scope = item.get("scope")
        if not isinstance(scope, dict):
            errors.append(f"{label}: scope must be an object")
        else:
            project = scope.get("project")
            if (
                not isinstance(project, str)
                or not project
                or Path(project).is_absolute()
                or ".." in Path(project).parts
            ):
                errors.append(f"{label}: project scope must be repository-relative")
            try:
                start = date.fromisoformat(str(scope.get("start")))
                end = date.fromisoformat(str(scope.get("end")))
                if end < start:
                    errors.append(f"{label}: scope end precedes start")
            except ValueError:
                errors.append(f"{label}: scope dates must be ISO dates")
        _validate_fingerprint(
            item.get("bound_manifest"),
            f"{label} bound manifest",
            errors,
            verify_paths=verify_paths,
            verify_hashes=verify_hashes,
        )
        strategy = item.get("bound_strategy")
        _validate_fingerprint(
            strategy,
            f"{label} bound strategy",
            errors,
            verify_paths=verify_paths,
            verify_hashes=verify_hashes,
        )
        artifacts = item.get("bound_artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            errors.append(f"{label}: bound_artifacts must be a non-empty list")
        else:
            roles = [
                artifact["role"]
                for artifact in artifacts
                if isinstance(artifact, dict) and isinstance(artifact.get("role"), str)
            ]
            duplicate_roles = sorted(role for role, count in Counter(roles).items() if count > 1)
            if duplicate_roles:
                errors.append(f"{label}: duplicate artifact roles: {', '.join(duplicate_roles)}")
            for artifact_index, artifact in enumerate(artifacts):
                if not isinstance(artifact, dict) or not artifact.get("role"):
                    errors.append(f"{label}: artifact {artifact_index} requires role")
                    continue
                _validate_fingerprint(
                    artifact,
                    f"{label} artifact {artifact['role']}",
                    errors,
                    verify_paths=verify_paths,
                    verify_hashes=verify_hashes,
                )
        if item.get("current_survivor_fallback_allowed") is not False:
            errors.append(f"{label}: current-survivor fallback must be false")
        if item.get("record_level_available_at_available") is not False:
            errors.append(f"{label}: missing record-level available_at must remain explicit")
        for list_field in ("allowed_uses", "blocked_uses", "known_limitations"):
            if not isinstance(item.get(list_field), list) or not item[list_field]:
                errors.append(f"{label}: {list_field} must be a non-empty list")


def _validate_lineage_manifests(
    lineage: dict[str, Any],
    asset_id: str,
    errors: list[str],
    *,
    verify_paths: bool,
    verify_hashes: bool,
) -> None:
    immutable = lineage.get("immutable_manifest")
    if not isinstance(immutable, bool):
        errors.append(f"{asset_id}: lineage.immutable_manifest must be boolean")
    manifest_path = lineage.get("manifest_path")
    manifest_hash = lineage.get("manifest_sha256")
    if immutable and (not manifest_path or not manifest_hash):
        errors.append(
            f"{asset_id}: immutable_manifest=true requires manifest_path and manifest_sha256"
        )
    if manifest_path is not None or manifest_hash is not None:
        _validate_fingerprint(
            {"path": manifest_path, "sha256": manifest_hash},
            f"{asset_id} immutable content manifest",
            errors,
            verify_paths=verify_paths,
            verify_hashes=verify_hashes,
        )
    source_path = lineage.get("source_manifest_path")
    source_hash = lineage.get("source_manifest_sha256")
    if source_path is not None or source_hash is not None:
        _validate_fingerprint(
            {"path": source_path, "sha256": source_hash},
            f"{asset_id} source lineage manifest",
            errors,
            verify_paths=verify_paths,
            verify_hashes=verify_hashes,
        )


def _validate_fingerprint(
    value: Any,
    label: str,
    errors: list[str],
    *,
    verify_paths: bool,
    verify_hashes: bool,
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{label}: fingerprint must be an object")
        return
    path_value = value.get("path")
    expected = value.get("sha256")
    if not path_value or not expected:
        errors.append(f"{label}: path and sha256 are required")
        return
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        errors.append(f"{label}: sha256 must be 64 lowercase hexadecimal characters")
        return
    path = Path(path_value)
    if verify_paths and not path.is_file():
        errors.append(f"{label}: fingerprint path is not a file: {path}")
        return
    if verify_paths and verify_hashes:
        actual = sha256_file(path)
        if actual != expected:
            errors.append(f"{label}: sha256 mismatch for {path}: expected {expected}, got {actual}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument(
        "--schema-only",
        action="store_true",
        help="validate structure without checking external paths or hashes",
    )
    parser.add_argument(
        "--skip-hashes",
        action="store_true",
        help="check paths but do not recompute declared file hashes",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        registry = load_registry(args.registry)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL data registry: {exc}")
        return 1
    errors = validate_registry(
        registry,
        verify_paths=not args.schema_only,
        verify_hashes=not args.schema_only and not args.skip_hashes,
    )
    if errors:
        print(f"FAIL data registry: {len(errors)} error(s)")
        for error in errors:
            print(f"- {error}")
        return 1
    status_counts = Counter(asset["status"] for asset in registry["assets"])
    status_summary = ", ".join(f"{key}={status_counts[key]}" for key in sorted(status_counts))
    gate = registry["global_gate"]
    print(
        "PASS data registry: "
        f"registry_id={registry['registry_id']} assets={len(registry['assets'])} "
        f"evidence={len(registry['evidence'])} {status_summary}"
    )
    print(
        "GLOBAL GATE: "
        f"free_causal_research_ready={str(gate['free_causal_research_ready']).lower()} "
        f"strict_archival_pit_ready={str(gate['strict_archival_pit_ready']).lower()} "
        f"backtest_authorized={str(gate['backtest_authorized']).lower()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
