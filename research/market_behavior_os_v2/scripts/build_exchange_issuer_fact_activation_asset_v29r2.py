#!/usr/bin/env python3
"""Build the non-authorizing V29R2 issuer-fact activation wrapper.

V29R2 changes only the frozen title-classification semantics.  It therefore
reuses, but does not silently inherit, the V29R1 development source route.  On
every build and validation this wrapper:

* invokes the V29R1 validator, which fully revalidates both sealed raw captures;
* binds the exact frozen V29R1 manifest, audit and route-index byte identities;
* copies the title-free route index byte-for-byte into an independent asset;
* binds the frozen V29R2 preregistration and V2 classifier source identity.

The wrapper never projects or classifies a title and never opens an outcome,
return, portfolio or daily-price table.  The resulting asset remains PIT-B,
revision-incomplete, unregistered and backtest-unauthorized until a separate
registry authorization binds its exact manifest and runner identities.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from research.market_behavior_os_v2.scripts import (
    build_exchange_issuer_risk_composite_asset_v29r1 as v29r1_asset,
)
from research.market_behavior_os_v2.scripts import (
    classify_exchange_issuer_risk_events_v2 as classifier_v2,
)
from research.market_behavior_os_v2.scripts import (
    fetch_exchange_issuer_announcements_v1 as collector,
)

ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"

ASSET_ID = "CY-036-R2"
BUILDER_ID = "CY-036-R2-EXCHANGE-ISSUER-FACT-ACTIVATION-BUILDER-V1"
EXPERIMENT = (
    "ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-"
    "ISSUER-FACT-COOLDOWN-V29R2"
)
PARENT_EXPERIMENT = v29r1_asset.PARENT_EXPERIMENT

PREREGISTRATION_PATH = OS_ROOT / f"experiments/{EXPERIMENT}_preregistration.json"
EXPECTED_PREREGISTRATION_SHA256 = (
    "076566c5cd85158997d39e4690c090e98110e85597d55ebf7d5b4fa0e63a5a3a"
)
CLASSIFIER_PATH = Path(classifier_v2.__file__).resolve()
EXPECTED_CLASSIFIER_SHA256 = (
    "127f62e551d4344ede9d41970ea7a6634f5f4b192fe2829a78eed8c72cf2da9d"
)

UPSTREAM_ASSET_ID = "CY-036-R1"
EXPECTED_UPSTREAM_MANIFEST_SHA256 = (
    "327d1ded0866405cfb1ca9d8f5c371042dae3fbea6f89cd32dca4d096ed12d98"
)
EXPECTED_UPSTREAM_AUDIT_SHA256 = (
    "a54d35adab885e1aa789685f7c56cb916f15fdc167d46a320804b05538c9ddb0"
)
EXPECTED_UPSTREAM_ROUTE_SHA256 = (
    "f9bf1a275fa5a3294ed7c571eef583cb88c7f3e011a397acfd5d616bf4225af3"
)

ROUTE_INDEX_NAME = "announcement_route_index.parquet"
ACTIVATION_AUDIT_NAME = "activation_audit.json"
ASSET_MANIFEST_NAME = "asset_manifest.json"
_SEALED_TOP_LEVEL = {
    ROUTE_INDEX_NAME,
    ACTIVATION_AUDIT_NAME,
    ASSET_MANIFEST_NAME,
}
_EXPECTED_ROUTE_COLUMNS = [
    "component_role",
    "original_adddate",
    "original_ssedate",
    "original_publish_time",
    "causal_available_at",
    *v29r1_asset._IDENTITY_COLUMNS,
]
_EXPECTED_COMPONENT_ROLES = {
    "SSE_FULL_HISTORY_AUTHORITATIVE",
    "BASE_SZSE_AUTHORITATIVE",
}


class V29R2AssetError(RuntimeError):
    """Fail closed on protocol, source, route or immutable-wrapper drift."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise V29R2AssetError(message)


def _file_facts(path: Path, label: str) -> dict[str, Any]:
    _require(path.is_file() and not path.is_symlink(), f"missing or unsafe {label}: {path}")
    return {"sha256": collector.sha256_file(path), "bytes": path.stat().st_size}


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    _file_facts(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V29R2AssetError(f"invalid {label}: {path}") from exc
    _require(isinstance(value, dict), f"{label} must be a JSON object")
    return value


def _strict_bool(value: Any, expected: bool, label: str) -> None:
    _require(isinstance(value, bool) and value is expected, f"{label} must be {expected}")


def _string(value: Any, label: str) -> str:
    _require(isinstance(value, str) and bool(value), f"{label} must be a non-empty string")
    return value


def _safe_existing_dir(path: Path, label: str) -> Path:
    _require(not path.is_symlink(), f"{label} must not be a symlink: {path}")
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise V29R2AssetError(f"{label} does not exist: {path}") from exc
    _require(resolved.is_dir(), f"{label} is not a directory: {resolved}")
    return resolved


def _safe_output_root(path: Path, *, create: bool = False) -> Path:
    _require(not path.is_symlink(), f"asset root must not be a symlink: {path}")
    if create and not path.exists():
        path.mkdir(parents=True)
    return _safe_existing_dir(path, "asset root")


def _require_exact_top_level(root: Path, expected: set[str], label: str) -> None:
    actual: set[str] = set()
    for path in root.iterdir():
        _require(not path.is_symlink(), f"{label} contains a symlink: {path.name}")
        actual.add(path.name)
    _require(not expected - actual, f"{label} is missing entries: {sorted(expected - actual)}")
    _require(not actual - expected, f"{label} contains extra entries: {sorted(actual - expected)}")


def _require_read_only(path: Path, label: str) -> None:
    _require(stat.S_IMODE(path.stat().st_mode) & 0o222 == 0, f"{label} is not read-only")


def _validate_protocol() -> dict[str, Any]:
    preregistration_facts = _file_facts(PREREGISTRATION_PATH, "V29R2 preregistration")
    _require(
        preregistration_facts["sha256"] == EXPECTED_PREREGISTRATION_SHA256,
        "V29R2 preregistration SHA-256 differs from the frozen identity",
    )
    prereg = _read_json_object(PREREGISTRATION_PATH, "V29R2 preregistration")
    _require(prereg.get("experiment") == EXPERIMENT, "V29R2 experiment drifted")
    _require(
        prereg.get("status")
        == "SEMANTIC_REPAIR_AND_SELECTOR_IDENTITY_FROZEN_BEFORE_V29R2_OUTCOME_REPLAY",
        "V29R2 is not frozen before outcome replay",
    )
    _require(prereg.get("parent") == PARENT_EXPERIMENT, "V29R2 parent drifted")
    development = prereg.get("development")
    _require(isinstance(development, dict), "V29R2 development contract is missing")
    _require(
        development.get("signal_years") == [2018, 2019, 2020, 2021],
        "V29R2 development years drifted",
    )
    later = prereg.get("later_period_protocol")
    _require(isinstance(later, dict), "V29R2 later-period protocol is missing")
    _strict_bool(later.get("no_rule_change_after_open"), True, "later-data rule lock")
    _require(
        "2022_2024" in later and "2025_plus" in later,
        "V29R2 later-period lock is incomplete",
    )
    knowledge = prereg.get("knowledge_time")
    _require(isinstance(knowledge, dict), "V29R2 knowledge-time contract is missing")
    _require(
        knowledge.get("window")
        == "signal_time - 120 calendar days <= causal_available_at <= signal_time"
        and knowledge.get("unknown_missing_or_unprovable") == "FAIL_CLOSED",
        "V29R2 causal-window contract drifted",
    )
    semantic = prereg.get("semantic_rule")
    _require(isinstance(semantic, dict), "V29R2 semantic rule is missing")
    _require(
        semantic.get("threshold_search")
        == (
            "NONE; 120 calendar days is carried unchanged from V29R1 so this "
            "experiment isolates the semantic repair."
        ),
        "V29R2 threshold-search contract drifted",
    )
    software = prereg.get("software_frozen_before_v29r2_outcome_replay")
    _require(isinstance(software, dict), "V29R2 software freeze is missing")
    classifier_facts = _file_facts(CLASSIFIER_PATH, "V29R2 classifier")
    _require(
        classifier_facts["sha256"] == EXPECTED_CLASSIFIER_SHA256,
        "V29R2 classifier differs from its frozen byte identity",
    )
    _require(
        software.get("classifier_sha256") == classifier_facts["sha256"],
        "V29R2 classifier differs from the preregistration",
    )
    declared_classifier = Path(
        _string(software.get("classifier_path"), "V29R2 classifier path")
    )
    _require(
        not declared_classifier.is_absolute()
        and (ROOT / declared_classifier).resolve(strict=True) == CLASSIFIER_PATH,
        "V29R2 classifier path differs from the frozen source",
    )
    return {
        "preregistration": prereg,
        "preregistration_facts": preregistration_facts,
        "classifier_facts": classifier_facts,
    }


def _validate_route_frame(path: Path) -> tuple[pd.DataFrame, dict[str, int]]:
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        raise V29R2AssetError("unable to read the title-free upstream route index") from exc
    _require(list(frame.columns) == _EXPECTED_ROUTE_COLUMNS, "route-index columns drifted")
    _require("title" not in frame.columns, "route index must never contain title")
    _require(not frame.empty, "route index is empty")
    _require(
        frame["announcement_key"].notna().all()
        and not frame.duplicated("announcement_key").any(),
        "route-index announcement identity is missing or duplicated",
    )
    _require(
        set(frame["component_role"].astype(str)) == _EXPECTED_COMPONENT_ROLES,
        "route-index component roles drifted",
    )
    _require(
        all(value is True for value in frame["hard_valid"].tolist()),
        "route index contains a non-hard-valid row",
    )
    _require(
        all(value is False for value in frame["revision_history_complete"].tolist())
        and all(value is False for value in frame["strict_pit_eligible"].tolist()),
        "route-index PIT-B limitations drifted",
    )
    try:
        available = pd.to_datetime(frame["available_at"], errors="raise")
        causal = pd.to_datetime(frame["causal_available_at"], errors="raise")
        query_date = pd.to_datetime(frame["source_query_date"], errors="raise")
    except (TypeError, ValueError) as exc:
        raise V29R2AssetError("route-index time fields are invalid") from exc
    _require(
        available.notna().all() and causal.notna().all() and query_date.notna().all(),
        "route-index time fields are missing",
    )
    _require(causal.ge(available).all(), "causal_available_at precedes available_at")
    _require(
        query_date.le(pd.Timestamp("2021-12-31")).all(),
        "route index contains a post-2021 source query partition",
    )
    counts = {
        "route_rows": len(frame),
        "unique_announcement_keys": int(frame["announcement_key"].nunique()),
        "causal_available_at_from_2022_rows": int(
            causal.ge(pd.Timestamp("2022-01-01")).sum()
        ),
    }
    return frame, counts


def _validate_upstream(
    upstream_root: Path, base_capture_root: Path
) -> dict[str, Any]:
    root = _safe_existing_dir(upstream_root, "CY-036-R1 upstream asset")
    base_root = _safe_existing_dir(base_capture_root, "base source capture")
    manifest_path = root / v29r1_asset.ASSET_MANIFEST_NAME
    audit_path = root / v29r1_asset.ACTIVATION_AUDIT_NAME
    route_path = root / v29r1_asset.COMPOSITE_NAME
    expected = (
        (manifest_path, "CY-036-R1 manifest", EXPECTED_UPSTREAM_MANIFEST_SHA256),
        (audit_path, "CY-036-R1 activation audit", EXPECTED_UPSTREAM_AUDIT_SHA256),
        (route_path, "CY-036-R1 route index", EXPECTED_UPSTREAM_ROUTE_SHA256),
    )
    facts: dict[str, dict[str, Any]] = {}
    for path, label, expected_sha in expected:
        value = _file_facts(path, label)
        _require(value["sha256"] == expected_sha, f"{label} differs from frozen identity")
        _require_read_only(path, label)
        facts[path.name] = value
    try:
        revalidated = v29r1_asset.validate_asset(root, base_root)
    except Exception as exc:
        raise V29R2AssetError(f"CY-036-R1 full source revalidation failed: {exc}") from exc
    _require(revalidated.get("status") == "PASS", "CY-036-R1 validation did not pass")
    _require(revalidated.get("asset_id") == UPSTREAM_ASSET_ID, "upstream asset_id drifted")
    _strict_bool(revalidated.get("registered"), False, "upstream registered state")
    _strict_bool(
        revalidated.get("backtest_authorized"), False, "upstream authorization state"
    )
    manifest = _read_json_object(manifest_path, "CY-036-R1 manifest")
    _require(manifest.get("asset_id") == UPSTREAM_ASSET_ID, "upstream manifest asset_id drifted")
    _strict_bool(manifest.get("registered"), False, "upstream manifest registered state")
    _strict_bool(
        manifest.get("backtest_authorized"),
        False,
        "upstream manifest authorization state",
    )
    content = manifest.get("content")
    _require(
        isinstance(content, dict) and content.get("route_index_includes_title") is False,
        "upstream route is not declared title-free",
    )
    routing = manifest.get("source_routing")
    _require(
        isinstance(routing, dict) and set(routing) == _EXPECTED_COMPONENT_ROLES,
        "upstream source routing drifted",
    )
    declared_base = Path(
        _string(routing["BASE_SZSE_AUTHORITATIVE"].get("root"), "base route root")
    )
    declared_sse = Path(
        _string(routing["SSE_FULL_HISTORY_AUTHORITATIVE"].get("root"), "SSE route root")
    )
    _require(
        declared_base.resolve(strict=True) == base_root,
        "upstream manifest is not bound to the requested base capture",
    )
    _require(
        declared_sse.resolve(strict=True)
        == (root / v29r1_asset.SSE_CAPTURE_NAME).resolve(strict=True),
        "upstream manifest is not bound to its nested SSE capture",
    )
    title_contract = manifest.get("title_route_contract")
    _require(isinstance(title_contract, dict), "upstream title-route contract is missing")
    _require(
        title_contract.get("nested_title_column") == "title"
        and title_contract.get("join_cardinality") == "one_to_one",
        "upstream nested title-route contract drifted",
    )
    frame, counts = _validate_route_frame(route_path)
    return {
        "root": root,
        "base_root": base_root,
        "manifest": manifest,
        "manifest_path": manifest_path,
        "audit_path": audit_path,
        "route_path": route_path,
        "facts": facts,
        "revalidated": revalidated,
        "route_frame": frame,
        "counts": counts,
    }


def _title_route_contract(upstream_manifest: Mapping[str, Any]) -> dict[str, Any]:
    source = upstream_manifest.get("title_route_contract")
    _require(isinstance(source, dict), "upstream title-route contract is missing")
    contract = json.loads(collector.canonical_json(source))
    access_order = contract.get("required_access_order")
    _require(
        isinstance(access_order, list) and len(access_order) >= 3,
        "upstream title access order is incomplete",
    )
    access_order[0] = (
        "Validate CY-036-R2 and filter announcement_route_index.parquet using "
        "window_start <= causal_available_at <= decision_at."
    )
    contract["activation_wrapper"] = {
        "upstream_asset_id": UPSTREAM_ASSET_ID,
        "route_index_byte_identical_to_upstream": True,
        "title_column_projected_or_opened_by_builder": False,
        "title_classification_performed_by_builder": False,
    }
    return contract


def _collect_context(upstream_root: Path, base_capture_root: Path) -> dict[str, Any]:
    protocol = _validate_protocol()
    upstream = _validate_upstream(upstream_root, base_capture_root)
    return {"protocol": protocol, "upstream": upstream}


def _software_lineage() -> dict[str, Any]:
    paths = {
        "builder": Path(__file__).resolve(),
        "v29r2_classifier": CLASSIFIER_PATH,
        "v29r1_composite_builder": Path(v29r1_asset.__file__).resolve(),
    }
    return {
        role: {
            "path": str(path),
            **_file_facts(path, f"{role} code"),
        }
        for role, path in paths.items()
    }


def _build_audit(context: Mapping[str, Any], sealed_at: str) -> dict[str, Any]:
    protocol = context["protocol"]
    upstream = context["upstream"]
    counts = upstream["counts"]
    return {
        "audit_schema": "CY_BOUNDED_INPUT_ACTIVATION_AUDIT_V1",
        "audit_id": BUILDER_ID,
        "asset_id": ASSET_ID,
        "status": "PASS",
        "validated_at": sealed_at,
        "registered": False,
        "backtest_authorized": False,
        "authorization_state": "SEALED_BUT_FALSE_UNTIL_EXACT_REGISTRY_BINDING",
        "protocol": {
            "experiment": EXPERIMENT,
            "preregistration_sha256": protocol["preregistration_facts"]["sha256"],
            "classifier_sha256": protocol["classifier_facts"]["sha256"],
            "parent": PARENT_EXPERIMENT,
            "outcome_files_access": "NONE",
        },
        "software_lineage": _software_lineage(),
        "upstream_activation": {
            "asset_id": UPSTREAM_ASSET_ID,
            "root": str(upstream["root"]),
            "asset_manifest_sha256": upstream["facts"][
                v29r1_asset.ASSET_MANIFEST_NAME
            ]["sha256"],
            "activation_audit_sha256": upstream["facts"][
                v29r1_asset.ACTIVATION_AUDIT_NAME
            ]["sha256"],
            "route_index_sha256": upstream["facts"][v29r1_asset.COMPOSITE_NAME][
                "sha256"
            ],
            "route_index_byte_identical": True,
            "base_nested_files_verified": upstream["revalidated"].get(
                "base_nested_files_verified"
            ),
            "sse_nested_files_verified": upstream["revalidated"].get(
                "sse_nested_files_verified"
            ),
        },
        "source_routing": upstream["manifest"]["source_routing"],
        "title_route_contract": _title_route_contract(upstream["manifest"]),
        "counts": dict(counts),
        "checks": {
            "v29r1_full_wrapper_and_both_nested_source_seals_revalidated": True,
            "v29r1_manifest_audit_and_route_exact_frozen_hashes": True,
            "independent_route_index_byte_identical_to_v29r1": True,
            "route_index_title_column_absent": True,
            "post_2021_source_query_partition_opened": False,
            "title_column_projected_or_opened_by_wrapper": False,
            "post_2021_title_opened_or_classified": False,
            "classifier_executed": False,
            "outcome_return_portfolio_or_daily_table_opened": False,
        },
        "limitations": [
            (
                "PIT-B current official metadata reconstruction; revision-vintage history "
                "is incomplete"
            ),
            (
                "nested source seal validation reparses source metadata, but this activation "
                "wrapper never projects, opens or classifies the nested title column"
            ),
            (
                "causal_available_at may fall in 2022 for a pre-2022 query-partition record; "
                "such route metadata is retained but no corresponding title is opened here"
            ),
            "PASS does not register or authorize this asset for a backtest",
        ],
    }


def _inventory_entry(
    role: str,
    path: Path,
    *,
    root: Path,
    storage_scope: str,
) -> dict[str, Any]:
    facts = _file_facts(path, role)
    rendered = path.relative_to(root).as_posix() if storage_scope == "ASSET_ROOT" else str(path)
    return {
        "role": role,
        "storage_scope": storage_scope,
        "path": rendered,
        **facts,
    }


def _build_inventory(
    context: Mapping[str, Any],
    root: Path,
    route_path: Path,
    audit_path: Path,
) -> list[dict[str, Any]]:
    upstream = context["upstream"]
    return [
        _inventory_entry(
            "announcement_route_index",
            route_path,
            root=root,
            storage_scope="ASSET_ROOT",
        ),
        _inventory_entry(
            "activation_audit", audit_path, root=root, storage_scope="ASSET_ROOT"
        ),
        _inventory_entry(
            "v29r2_activation_builder_code",
            Path(__file__).resolve(),
            root=root,
            storage_scope="EXTERNAL_LINEAGE",
        ),
        _inventory_entry(
            "v29r2_preregistration",
            PREREGISTRATION_PATH,
            root=root,
            storage_scope="EXTERNAL_LINEAGE",
        ),
        _inventory_entry(
            "v29r2_classifier_source_not_executed",
            CLASSIFIER_PATH,
            root=root,
            storage_scope="EXTERNAL_LINEAGE",
        ),
        _inventory_entry(
            "v29r1_composite_builder_code",
            Path(v29r1_asset.__file__).resolve(),
            root=root,
            storage_scope="EXTERNAL_LINEAGE",
        ),
        _inventory_entry(
            "v29r1_asset_manifest",
            upstream["manifest_path"],
            root=root,
            storage_scope="EXTERNAL_LINEAGE",
        ),
        _inventory_entry(
            "v29r1_activation_audit",
            upstream["audit_path"],
            root=root,
            storage_scope="EXTERNAL_LINEAGE",
        ),
        _inventory_entry(
            "v29r1_route_index",
            upstream["route_path"],
            root=root,
            storage_scope="EXTERNAL_LINEAGE",
        ),
    ]


def _build_manifest(
    context: Mapping[str, Any],
    root: Path,
    audit: Mapping[str, Any],
    inventory: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    upstream = context["upstream"]
    inventory_rows = [dict(row) for row in inventory]
    return {
        "manifest_schema": "CY_IMMUTABLE_ASSET_MANIFEST_V1",
        "asset_id": ASSET_ID,
        "name": "V29R2 issuer-fact title-route activation wrapper",
        "status": "PASS",
        "physical_state": "MATERIALIZED",
        "immutable": True,
        "manifest_self_included": False,
        "registered": False,
        "backtest_authorized": False,
        "backtest_authorization_condition": (
            "false until the registry binds this exact manifest SHA-256 and the "
            "separate frozen V29R2 replay runner"
        ),
        "sealed_at": audit["validated_at"],
        "builder_id": BUILDER_ID,
        "location": str(root),
        "route_index_path": ROUTE_INDEX_NAME,
        "protocol_binding": dict(audit["protocol"]),
        "software_lineage": _software_lineage(),
        "upstream_activation": dict(audit["upstream_activation"]),
        "source_routing": upstream["manifest"]["source_routing"],
        "title_route_contract": _title_route_contract(upstream["manifest"]),
        "query_coverage": upstream["manifest"].get("query_coverage"),
        "pit": {
            "grade": "B",
            "revision_history_incomplete": True,
            "strict_archival_pit_ready": False,
            "knowledge_time": "causal_available_at only",
        },
        "content": {
            "source_tables_title_metadata_only": True,
            "route_index_includes_title": False,
            "route_index_columns": list(_EXPECTED_ROUTE_COLUMNS),
            "route_index_sha256": EXPECTED_UPSTREAM_ROUTE_SHA256,
            "route_index_byte_identical_to_v29r1": True,
            "announcement_documents_included": False,
            "classification_included": False,
            "classifier_executed_during_build": False,
            "outcomes_included_or_opened": False,
        },
        "counts": dict(upstream["counts"]),
        "limitations": list(audit["limitations"]),
        "inventory": inventory_rows,
        "inventory_sha256": collector.sha256_bytes(
            collector.canonical_json(inventory_rows).encode("utf-8")
        ),
    }


def _write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise V29R2AssetError(f"refusing to overwrite existing wrapper file: {path}") from exc


def _copy_file_exclusive(source: Path, destination: Path) -> None:
    _require(
        not destination.exists(),
        f"refusing to overwrite existing wrapper file: {destination}",
    )
    fd, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with source.open("rb") as reader, temporary.open("wb") as writer:
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
        _require(
            collector.sha256_file(temporary) == EXPECTED_UPSTREAM_ROUTE_SHA256,
            "copied route-index byte identity drifted",
        )
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def build_asset(
    asset_root: Path, upstream_root: Path, base_capture_root: Path
) -> dict[str, Any]:
    """Build an independent, title-free V29R2 activation wrapper."""

    root = _safe_output_root(asset_root, create=True)
    _require_exact_top_level(root, set(), "new V29R2 activation root")
    context = _collect_context(upstream_root, base_capture_root)
    route_path = root / ROUTE_INDEX_NAME
    audit_path = root / ACTIVATION_AUDIT_NAME
    manifest_path = root / ASSET_MANIFEST_NAME
    created: list[Path] = []
    try:
        _copy_file_exclusive(context["upstream"]["route_path"], route_path)
        created.append(route_path)
        sealed_at = datetime.now(UTC).isoformat()
        audit = _build_audit(context, sealed_at)
        _write_json_exclusive(audit_path, audit)
        created.append(audit_path)
        inventory = _build_inventory(context, root, route_path, audit_path)
        manifest = _build_manifest(context, root, audit, inventory)
        _write_json_exclusive(manifest_path, manifest)
        created.append(manifest_path)
        for path in (route_path, audit_path, manifest_path):
            path.chmod(0o444)
        _require_exact_top_level(root, _SEALED_TOP_LEVEL, "sealed V29R2 activation root")
    except Exception:
        for path in reversed(created):
            if path.exists():
                path.chmod(0o644)
                path.unlink()
        raise
    return {
        "status": "PASS",
        "asset_id": ASSET_ID,
        "asset_manifest": str(manifest_path),
        "asset_manifest_sha256": collector.sha256_file(manifest_path),
        "route_index_sha256": collector.sha256_file(route_path),
        "route_rows": context["upstream"]["counts"]["route_rows"],
        "registered": False,
        "backtest_authorized": False,
    }


def validate_asset(
    asset_root: Path, upstream_root: Path, base_capture_root: Path
) -> dict[str, Any]:
    """Revalidate both source seals, the upstream route and this immutable wrapper."""

    root = _safe_output_root(asset_root)
    _require_exact_top_level(root, _SEALED_TOP_LEVEL, "sealed V29R2 activation root")
    context = _collect_context(upstream_root, base_capture_root)
    route_path = root / ROUTE_INDEX_NAME
    audit_path = root / ACTIVATION_AUDIT_NAME
    manifest_path = root / ASSET_MANIFEST_NAME
    route_facts = _file_facts(route_path, ROUTE_INDEX_NAME)
    _require(
        route_facts["sha256"] == EXPECTED_UPSTREAM_ROUTE_SHA256
        and route_facts["sha256"]
        == context["upstream"]["facts"][v29r1_asset.COMPOSITE_NAME]["sha256"],
        "sealed V29R2 route is not byte-identical to the frozen V29R1 route",
    )
    frame, counts = _validate_route_frame(route_path)
    _require(counts == context["upstream"]["counts"], "sealed route counts drifted")
    _require(len(frame) == len(context["upstream"]["route_frame"]), "sealed route rows drifted")

    audit = _read_json_object(audit_path, ACTIVATION_AUDIT_NAME)
    sealed_at = _string(audit.get("validated_at"), "activation validated_at")
    try:
        parsed = pd.Timestamp(sealed_at)
    except (TypeError, ValueError) as exc:
        raise V29R2AssetError("activation validated_at is invalid") from exc
    _require(not pd.isna(parsed) and parsed.tzinfo is not None, "validated_at lacks timezone")
    expected_audit = _build_audit(context, sealed_at)
    _require(
        collector.canonical_json(audit) == collector.canonical_json(expected_audit),
        "activation audit content drifted",
    )
    inventory = _build_inventory(context, root, route_path, audit_path)
    expected_manifest = _build_manifest(context, root, expected_audit, inventory)
    manifest = _read_json_object(manifest_path, ASSET_MANIFEST_NAME)
    _require(
        collector.canonical_json(manifest) == collector.canonical_json(expected_manifest),
        "asset manifest content or inventory drifted",
    )
    for path, label in (
        (route_path, ROUTE_INDEX_NAME),
        (audit_path, ACTIVATION_AUDIT_NAME),
        (manifest_path, ASSET_MANIFEST_NAME),
    ):
        _require_read_only(path, label)
    return {
        "status": "PASS",
        "asset_id": ASSET_ID,
        "asset_manifest_sha256": collector.sha256_file(manifest_path),
        "route_index_sha256": route_facts["sha256"],
        "route_rows": counts["route_rows"],
        "base_nested_files_verified": context["upstream"]["revalidated"].get(
            "base_nested_files_verified"
        ),
        "sse_nested_files_verified": context["upstream"]["revalidated"].get(
            "sse_nested_files_verified"
        ),
        "registered": False,
        "backtest_authorized": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("build", "validate"))
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--upstream-root", type=Path, required=True)
    parser.add_argument("--base-capture-root", type=Path, required=True)
    args = parser.parse_args()
    action = build_asset if args.mode == "build" else validate_asset
    result = action(args.asset_root, args.upstream_root, args.base_capture_root)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
