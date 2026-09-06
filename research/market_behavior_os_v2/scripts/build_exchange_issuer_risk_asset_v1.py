#!/usr/bin/env python3
"""Build and revalidate the bounded CY-036 development risk-input wrapper.

The wrapper does not register or authorize the source for a backtest.  It binds
one already-sealed, title-only SSE/SZSE metadata capture to the frozen V29
protocol and its pre-outcome parent identities.  The nested capture remains a
limited PIT-B reconstruction with incomplete revision history.

No outcome or portfolio table is opened.  The frozen V28R2 development-result
artifact is streamed only to verify the SHA-256 identity recorded before this
wrapper was built.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from research.market_behavior_os_v2.scripts import (
    classify_exchange_issuer_risk_events_v1 as classifier,
)
from research.market_behavior_os_v2.scripts import (
    fetch_exchange_issuer_announcements_v1 as collector,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_demand_not_locked_v28r1 as v28r1,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_orderly_demand_v28r2 as v28r2,
)
from research.market_behavior_os_v2.scripts import (
    seal_exchange_issuer_announcements_v1 as source_sealer,
)

ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"

ASSET_ID = "CY-036"
BUILDER_ID = "CY-036-EXCHANGE-ISSUER-RISK-WRAPPER-BUILDER-V1"
SOURCE_CAPTURE_ASSET_ID = collector.ASSET_ID
V29_EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-ISSUER-INTEGRITY-COOLDOWN-V29"
V28R2_EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-V28R2"
V28R1_EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-DEMAND-NOT-LOCKED-V28R1"

COVERAGE_START = "2017-10-01"
COVERAGE_END = "2021-12-31"
EXPECTED_UNIVERSE_SYMBOLS = 378

UNIVERSE_NAME = "universe.parquet"
SOURCE_CAPTURE_NAME = "source_capture"
ASSET_MANIFEST_NAME = "asset_manifest.json"
ACTIVATION_AUDIT_NAME = "activation_audit.json"

PREREGISTRATION_PATH = OS_ROOT / (
    "experiments/ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-"
    "ISSUER-INTEGRITY-COOLDOWN-V29_preregistration.json"
)
CLASSIFIER_PATH = Path(classifier.__file__).resolve()
V28R1_DEVELOPMENT_SELECTED_PATH = v28r1.selected_path("DEVELOPMENT")
V28R2_RUNNER_PATH = Path(v28r2.__file__).resolve()
V28R2_STAGE_A_PATH = v28r2.STAGE_A_FREEZE
V28R2_SELECTED_PATH = v28r2.selected_path()
V28R2_DEVELOPMENT_RESULT_PATH = v28r2.DEVELOPMENT_RESULT

_BUILD_TOP_LEVEL = {UNIVERSE_NAME, SOURCE_CAPTURE_NAME}
_SEALED_TOP_LEVEL = {
    UNIVERSE_NAME,
    SOURCE_CAPTURE_NAME,
    ASSET_MANIFEST_NAME,
    ACTIVATION_AUDIT_NAME,
}
_SOURCE_CAPTURE_TOP_LEVEL = {
    "raw",
    "announcements.parquet",
    "request_pages.parquet",
    "audit.json",
    "source_manifest.json",
    source_sealer.AUDIT_VALIDATION_NAME,
    source_sealer.ASSET_MANIFEST_NAME,
}


class CY036BuildError(RuntimeError):
    """Fail closed on lineage, identity, coverage, or wrapper drift."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CY036BuildError(message)


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    _require(path.is_file() and not path.is_symlink(), f"missing or unsafe {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CY036BuildError(f"invalid {label}: {path}") from exc
    _require(isinstance(value, dict), f"{label} must be a JSON object")
    return value


def _file_facts(path: Path, label: str) -> dict[str, Any]:
    _require(path.is_file() and not path.is_symlink(), f"missing or unsafe {label}: {path}")
    return {
        "sha256": collector.sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _string(value: Any, label: str) -> str:
    _require(isinstance(value, str) and bool(value), f"{label} must be a non-empty string")
    return value


def _strict_bool(value: Any, expected: bool, label: str) -> None:
    _require(isinstance(value, bool) and value is expected, f"{label} must be {expected}")


def _strict_integer(value: Any, expected: int, label: str) -> None:
    _require(
        not isinstance(value, bool) and isinstance(value, int) and value == expected,
        f"{label} must be {expected}",
    )


def _safe_root(asset_root: Path) -> Path:
    _require(not asset_root.is_symlink(), f"asset root must not be a symlink: {asset_root}")
    try:
        root = asset_root.resolve(strict=True)
    except FileNotFoundError as exc:
        raise CY036BuildError(f"asset root does not exist: {asset_root}") from exc
    _require(root.is_dir(), f"asset root is not a directory: {root}")
    return root


def _require_exact_top_level(root: Path, expected: set[str], label: str) -> None:
    actual: set[str] = set()
    for path in root.iterdir():
        _require(not path.is_symlink(), f"{label} contains a symlink: {path.name}")
        actual.add(path.name)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    _require(not missing, f"{label} is missing entries: {missing}")
    _require(not extra, f"{label} contains extra entries: {extra}")


def _load_canonical_universe(path: Path) -> tuple[list[str], int]:
    _file_facts(path, UNIVERSE_NAME)
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        raise CY036BuildError(f"unable to read {UNIVERSE_NAME}") from exc
    _require(
        list(frame.columns) == ["symbol"],
        "universe.parquet columns must be exactly ['symbol']",
    )
    _require(
        not frame.empty and not frame.symbol.isna().any(),
        "universe symbol column is empty or missing",
    )
    raw = [str(value).strip().upper() for value in frame.symbol.tolist()]
    try:
        normalized = [collector.normalize_symbol(value) for value in raw]
    except collector.CaptureError as exc:
        raise CY036BuildError("universe contains an invalid symbol") from exc
    _require(raw == normalized, "universe symbols are not in canonical exchange-suffixed form")
    _require(len(normalized) == len(set(normalized)), "universe contains duplicate symbols")
    _require(normalized == sorted(normalized), "universe symbols must be deterministically sorted")
    _require(
        len(normalized) == EXPECTED_UNIVERSE_SYMBOLS,
        f"universe must contain exactly {EXPECTED_UNIVERSE_SYMBOLS} symbols",
    )
    return normalized, len(frame)


def _load_selected_symbols(path: Path) -> tuple[set[str], int]:
    _file_facts(path, "V28R1 development selected entries")
    try:
        frame = pd.read_parquet(path, columns=["symbol"])
    except Exception as exc:
        raise CY036BuildError("unable to read V28R1 development selected symbol identity") from exc
    _require(
        not frame.empty and not frame.symbol.isna().any(),
        "V28R1 selected symbols are empty or missing",
    )
    raw = [str(value).strip().upper() for value in frame.symbol.tolist()]
    try:
        normalized = [collector.normalize_symbol(value) for value in raw]
    except collector.CaptureError as exc:
        raise CY036BuildError("V28R1 selected entries contain an invalid symbol") from exc
    _require(raw == normalized, "V28R1 selected symbols are not canonical")
    return set(normalized), len(frame)


def _validate_preregistration_and_parent() -> dict[str, Any]:
    prereg = _read_json_object(PREREGISTRATION_PATH, "V29 preregistration")
    _require(prereg.get("experiment") == V29_EXPERIMENT, "V29 preregistration experiment drifted")
    _require(
        prereg.get("status") == "SEMANTIC_RULE_FROZEN_BEFORE_DEVELOPMENT_EVENT_OUTCOME_JOIN",
        "V29 preregistration freeze status drifted",
    )
    _require(prereg.get("parent") == V28R2_EXPERIMENT, "V29 preregistration parent drifted")

    development = prereg.get("development")
    _require(isinstance(development, dict), "V29 development declaration is missing")
    _require(
        development.get("signal_years") == [2018, 2019, 2020, 2021],
        "V29 development years drifted",
    )
    _require(
        development.get("announcement_capture_start") == COVERAGE_START
        and development.get("announcement_capture_end") == COVERAGE_END,
        "V29 announcement coverage drifted",
    )

    classifier_contract = prereg.get("classifier")
    _require(isinstance(classifier_contract, dict), "V29 classifier declaration is missing")
    _require(
        classifier_contract.get("version") == classifier.CLASSIFICATION_VERSION,
        "classifier version differs from V29 preregistration",
    )
    classifier_facts = _file_facts(CLASSIFIER_PATH, "classifier runner")
    _require(
        classifier_contract.get("runner_sha256") == classifier_facts["sha256"],
        "classifier SHA-256 differs from V29 preregistration",
    )

    parent_files = {
        "parent_runner_sha256": (V28R2_RUNNER_PATH, "V28R2 runner"),
        "parent_development_stage_a_sha256": (V28R2_STAGE_A_PATH, "V28R2 Stage A freeze"),
        "parent_development_result_sha256": (
            V28R2_DEVELOPMENT_RESULT_PATH,
            "V28R2 development-result identity",
        ),
    }
    parent_facts: dict[str, dict[str, Any]] = {}
    for prereg_key, (path, label) in parent_files.items():
        facts = _file_facts(path, label)
        _require(
            prereg.get(prereg_key) == facts["sha256"],
            f"{label} SHA-256 differs from V29 preregistration",
        )
        parent_facts[prereg_key] = facts

    stage_a = _read_json_object(V28R2_STAGE_A_PATH, "V28R2 Stage A freeze")
    _require(stage_a.get("experiment") == V28R2_EXPERIMENT, "V28R2 Stage A experiment drifted")
    _require(
        stage_a.get("development_outcomes_opened") == "NO_IN_THIS_STAGE"
        and stage_a.get("post_2021_entries_or_outcomes_opened") == "NO_IN_THIS_STAGE",
        "V28R2 Stage A is not a pre-outcome development identity freeze",
    )
    _require(
        stage_a.get("runner_sha256") == parent_facts["parent_runner_sha256"]["sha256"],
        "V28R2 Stage A runner identity drifted",
    )

    v28r1_selected_facts = _file_facts(
        V28R1_DEVELOPMENT_SELECTED_PATH, "V28R1 development selected entries"
    )
    stage_sources = stage_a.get("source_hashes")
    _require(isinstance(stage_sources, dict), "V28R2 Stage A source identities are missing")
    _require(
        stage_sources.get("v28r1_development_selected_entries") == v28r1_selected_facts["sha256"],
        "V28R1 selected identity differs from the V28R2 Stage A freeze",
    )
    v28r2_selected_facts = _file_facts(V28R2_SELECTED_PATH, "V28R2 selected identity")
    stage_development = stage_a.get("development")
    _require(isinstance(stage_development, dict), "V28R2 Stage A development identity is missing")
    _require(
        stage_development.get("selected_entries_sha256") == v28r2_selected_facts["sha256"],
        "V28R2 selected identity differs from its Stage A freeze",
    )

    return {
        "preregistration": prereg,
        "preregistration_facts": _file_facts(PREREGISTRATION_PATH, "V29 preregistration"),
        "classifier_facts": classifier_facts,
        "parent_facts": parent_facts,
        "v28r1_selected_facts": v28r1_selected_facts,
        "v28r2_selected_facts": v28r2_selected_facts,
    }


def _validate_source_capture(root: Path, universe_path: Path) -> dict[str, Any]:
    source_capture = root / SOURCE_CAPTURE_NAME
    _require(
        source_capture.is_dir() and not source_capture.is_symlink(),
        "source_capture must be a real directory",
    )
    _require_exact_top_level(source_capture, _SOURCE_CAPTURE_TOP_LEVEL, "source_capture")
    try:
        sealed = source_sealer.validate_asset(source_capture)
    except Exception as exc:
        raise CY036BuildError(f"source capture full seal validation failed: {exc}") from exc
    _require(sealed.get("status") == "PASS", "source capture seal did not pass")
    _strict_bool(sealed.get("backtest_authorized"), False, "source capture authorization")

    source_manifest = _read_json_object(source_capture / "source_manifest.json", "source manifest")
    source_asset_manifest = _read_json_object(
        source_capture / source_sealer.ASSET_MANIFEST_NAME,
        "source capture asset manifest",
    )
    _require(
        source_manifest.get("asset_id") == SOURCE_CAPTURE_ASSET_ID
        and source_asset_manifest.get("asset_id") == SOURCE_CAPTURE_ASSET_ID,
        "source capture generic asset_id drifted",
    )
    _require(
        source_manifest.get("coverage") == {"start": COVERAGE_START, "end": COVERAGE_END},
        "source capture coverage is not the fixed development interval",
    )
    audit = _read_json_object(source_capture / "audit.json", "source collector audit")
    _strict_integer(
        audit.get("universe_symbols"), EXPECTED_UNIVERSE_SYMBOLS, "source audit universe_symbols"
    )
    declared_universe = Path(
        _string(source_manifest.get("universe_source"), "source universe_source")
    )
    _require(
        declared_universe.is_absolute()
        and declared_universe.resolve(strict=True) == universe_path.resolve(strict=True),
        "source capture is not bound to the wrapper universe.parquet",
    )
    _require(
        source_asset_manifest.get("snapshot_id") == sealed.get("snapshot_id"),
        "source capture seal snapshot identity drifted",
    )
    return {
        "root": source_capture,
        "sealed": sealed,
        "source_manifest": source_manifest,
        "asset_manifest": source_asset_manifest,
    }


def _inventory_entry(
    role: str,
    path: Path,
    *,
    root: Path,
    storage_scope: str,
    access: str = "READ_AND_HASH",
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    facts = _file_facts(path, role)
    rendered = (
        path.relative_to(root).as_posix() if storage_scope == "ASSET_ROOT" else str(path.resolve())
    )
    result: dict[str, Any] = {
        "role": role,
        "storage_scope": storage_scope,
        "path": rendered,
        "sha256": facts["sha256"],
        "bytes": facts["bytes"],
        "access": access,
    }
    if extra:
        result.update(extra)
    return result


def _build_inventory(
    root: Path, source: Mapping[str, Any], activation_audit_path: Path
) -> list[dict[str, Any]]:
    source_root: Path = source["root"]
    nested_manifest = source["asset_manifest"]
    nested_extra = {
        "nested_asset_id": SOURCE_CAPTURE_ASSET_ID,
        "nested_snapshot_id": source["sealed"]["snapshot_id"],
        "nested_inventory_sha256": nested_manifest.get("inventory_sha256"),
        "nested_files_verified": source["sealed"].get("files_verified"),
        "raw_page_inventory": "COVERED_BY_NESTED_SEAL_NOT_DUPLICATED_HERE",
    }
    return [
        _inventory_entry("universe", root / UNIVERSE_NAME, root=root, storage_scope="ASSET_ROOT"),
        _inventory_entry(
            "activation_audit",
            activation_audit_path,
            root=root,
            storage_scope="ASSET_ROOT",
        ),
        _inventory_entry(
            "source_capture_asset_manifest",
            source_root / source_sealer.ASSET_MANIFEST_NAME,
            root=root,
            storage_scope="ASSET_ROOT",
            extra=nested_extra,
        ),
        _inventory_entry(
            "source_capture_source_manifest",
            source_root / "source_manifest.json",
            root=root,
            storage_scope="ASSET_ROOT",
        ),
        _inventory_entry(
            "source_capture_collector_audit",
            source_root / "audit.json",
            root=root,
            storage_scope="ASSET_ROOT",
        ),
        _inventory_entry(
            "source_capture_validation_audit",
            source_root / source_sealer.AUDIT_VALIDATION_NAME,
            root=root,
            storage_scope="ASSET_ROOT",
        ),
        _inventory_entry(
            "source_capture_announcements",
            source_root / "announcements.parquet",
            root=root,
            storage_scope="ASSET_ROOT",
        ),
        _inventory_entry(
            "source_capture_request_pages",
            source_root / "request_pages.parquet",
            root=root,
            storage_scope="ASSET_ROOT",
        ),
        _inventory_entry(
            "risk_title_classifier",
            CLASSIFIER_PATH,
            root=root,
            storage_scope="EXTERNAL_LINEAGE",
        ),
        _inventory_entry(
            "v29_preregistration",
            PREREGISTRATION_PATH,
            root=root,
            storage_scope="EXTERNAL_LINEAGE",
        ),
        _inventory_entry(
            "v28r1_development_selected_entries_identity",
            V28R1_DEVELOPMENT_SELECTED_PATH,
            root=root,
            storage_scope="EXTERNAL_LINEAGE",
            access="SYMBOL_COLUMN_AND_SHA256_ONLY",
        ),
        _inventory_entry(
            "v28r2_parent_runner",
            V28R2_RUNNER_PATH,
            root=root,
            storage_scope="EXTERNAL_LINEAGE",
        ),
        _inventory_entry(
            "v28r2_parent_stage_a_freeze",
            V28R2_STAGE_A_PATH,
            root=root,
            storage_scope="EXTERNAL_LINEAGE",
        ),
        _inventory_entry(
            "v28r2_parent_selected_entries_identity",
            V28R2_SELECTED_PATH,
            root=root,
            storage_scope="EXTERNAL_LINEAGE",
            access="SHA256_ONLY_NO_OUTCOME_COLUMNS_READ",
        ),
        _inventory_entry(
            "v28r2_parent_development_result_identity",
            V28R2_DEVELOPMENT_RESULT_PATH,
            root=root,
            storage_scope="EXTERNAL_LINEAGE",
            access="STREAMED_SHA256_ONLY_CONTENT_NOT_PARSED",
        ),
    ]


def _collect_context(root: Path) -> dict[str, Any]:
    universe_path = root / UNIVERSE_NAME
    universe, universe_rows = _load_canonical_universe(universe_path)
    protocol = _validate_preregistration_and_parent()
    selected_symbols, selected_rows = _load_selected_symbols(V28R1_DEVELOPMENT_SELECTED_PATH)
    _require(
        set(universe) == selected_symbols,
        "wrapper universe does not exactly equal the V28R1 development selected symbol set",
    )
    source = _validate_source_capture(root, universe_path)
    return {
        "root": root,
        "universe": universe,
        "universe_rows": universe_rows,
        "selected_rows": selected_rows,
        "protocol": protocol,
        "source": source,
    }


def _build_activation_audit(context: Mapping[str, Any], validated_at: str) -> dict[str, Any]:
    root: Path = context["root"]
    protocol = context["protocol"]
    source = context["source"]
    return {
        "audit_schema": "CY_BOUNDED_INPUT_ACTIVATION_AUDIT_V1",
        "audit_id": BUILDER_ID,
        "asset_id": ASSET_ID,
        "status": "PASS",
        "validated_at": validated_at,
        "registered": False,
        "backtest_authorized": False,
        "authorization_state": "SEALED_BUT_FALSE_UNTIL_EXACT_REGISTRY_BINDING",
        "coverage": {"start": COVERAGE_START, "end": COVERAGE_END},
        "universe": {
            "symbols": EXPECTED_UNIVERSE_SYMBOLS,
            "rows": context["universe_rows"],
            "universe_parquet_sha256": _file_facts(root / UNIVERSE_NAME, "universe")["sha256"],
            "v28r1_selected_rows": context["selected_rows"],
            "v28r1_development_selected_entries_sha256": protocol["v28r1_selected_facts"]["sha256"],
            "exact_symbol_set_equal": True,
        },
        "source_capture": {
            "asset_id": SOURCE_CAPTURE_ASSET_ID,
            "snapshot_id": source["sealed"]["snapshot_id"],
            "asset_manifest_sha256": source["sealed"]["asset_manifest_sha256"],
            "files_verified_by_nested_sealer": source["sealed"]["files_verified"],
            "full_nested_validate_asset_rerun": True,
        },
        "protocol": {
            "experiment": V29_EXPERIMENT,
            "preregistration_sha256": protocol["preregistration_facts"]["sha256"],
            "classifier_version": classifier.CLASSIFICATION_VERSION,
            "classifier_sha256": protocol["classifier_facts"]["sha256"],
            "parent": V28R2_EXPERIMENT,
            "parent_runner_sha256": protocol["parent_facts"]["parent_runner_sha256"]["sha256"],
            "parent_stage_a_sha256": protocol["parent_facts"]["parent_development_stage_a_sha256"][
                "sha256"
            ],
            "parent_selected_entries_sha256": protocol["v28r2_selected_facts"]["sha256"],
            "parent_development_result_sha256": protocol["parent_facts"][
                "parent_development_result_sha256"
            ]["sha256"],
            "parent_result_access": "STREAMED_SHA256_ONLY_CONTENT_NOT_PARSED",
        },
        "checks": {
            "fixed_development_coverage_exact": True,
            "exact_378_symbol_universe": True,
            "universe_equals_v28r1_development_selected_symbol_set": True,
            "source_capture_generic_asset_id_exact": True,
            "source_capture_full_seal_revalidated": True,
            "source_capture_raw_pages_rehashed_and_reparsed_by_nested_sealer": True,
            "classifier_version_and_sha_match_preregistration": True,
            "v28r2_runner_stage_and_result_hashes_match_preregistration": True,
            "v28r2_selected_identity_matches_pre_outcome_stage_a": True,
            "post_2021_data_opened": False,
            "outcome_or_portfolio_table_opened": False,
        },
        "limitations": [
            "limited PIT-B current official metadata reconstruction; revision history "
            "is incomplete",
            "announcement title metadata only; documents are not included",
            "the parent development-result artifact was hashed only and never parsed",
            "PASS means wrapper integrity passed; this asset is not registered or "
            "backtest-authorized",
        ],
    }


def _build_asset_manifest(
    context: Mapping[str, Any],
    activation_audit: Mapping[str, Any],
    inventory: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    root: Path = context["root"]
    source = context["source"]
    protocol = context["protocol"]
    inventory_list = [dict(item) for item in inventory]
    return {
        "manifest_schema": "CY_IMMUTABLE_ASSET_MANIFEST_V1",
        "asset_id": ASSET_ID,
        "name": "Bounded V29 development issuer-risk title metadata input",
        "status": "PASS",
        "physical_state": "MATERIALIZED",
        "immutable": True,
        "manifest_self_included": False,
        "registered": False,
        "backtest_authorized": False,
        "backtest_authorization_condition": (
            "false until the registry binds this exact asset_manifest.json SHA-256"
        ),
        "sealed_at": activation_audit["validated_at"],
        "builder_id": BUILDER_ID,
        "location": str(root),
        "coverage": {"start": COVERAGE_START, "end": COVERAGE_END},
        "universe": {
            "symbols": EXPECTED_UNIVERSE_SYMBOLS,
            "universe_parquet_sha256": _file_facts(root / UNIVERSE_NAME, "universe")["sha256"],
            "v28r1_development_selected_entries_sha256": protocol["v28r1_selected_facts"]["sha256"],
            "exact_symbol_set_equal": True,
        },
        "pit": {
            "grade": "B",
            "revision_history_incomplete": True,
            "strict_archival_pit_ready": False,
            "knowledge_time": "official available_at only",
        },
        "content": {
            "title_only": True,
            "title_metadata_only": True,
            "announcement_documents_included": False,
            "source_capture_asset_id": SOURCE_CAPTURE_ASSET_ID,
            "source_snapshot_id": source["sealed"]["snapshot_id"],
            "classifier_version": classifier.CLASSIFICATION_VERSION,
        },
        "protocol_binding": {
            "experiment": V29_EXPERIMENT,
            "preregistration_sha256": protocol["preregistration_facts"]["sha256"],
            "parent": V28R2_EXPERIMENT,
        },
        "nested_raw_inventory_policy": (
            "source_capture raw pages are covered by its immutable asset_manifest inventory; "
            "raw entries are not duplicated in this wrapper"
        ),
        "limitations": list(activation_audit["limitations"]),
        "inventory": inventory_list,
        "inventory_sha256": collector.sha256_bytes(
            collector.canonical_json(inventory_list).encode("utf-8")
        ),
    }


def _write_json_exclusive(path: Path, value: Mapping[str, Any], *, read_only: bool = False) -> None:
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise CY036BuildError(f"refusing to overwrite existing wrapper file: {path}") from exc
    if read_only:
        path.chmod(0o444)


def build_asset(asset_root: Path) -> dict[str, Any]:
    """Build the non-authorizing CY-036 wrapper around a sealed source capture."""

    root = _safe_root(asset_root)
    audit_path = root / ACTIVATION_AUDIT_NAME
    manifest_path = root / ASSET_MANIFEST_NAME
    _require(
        not audit_path.exists() and not manifest_path.exists(),
        "wrapper files already exist; use validate mode",
    )
    _require_exact_top_level(root, _BUILD_TOP_LEVEL, "unsealed wrapper root")
    context = _collect_context(root)
    validated_at = datetime.now(UTC).isoformat()
    audit = _build_activation_audit(context, validated_at)
    _write_json_exclusive(audit_path, audit)
    manifest_written = False
    try:
        inventory = _build_inventory(root, context["source"], audit_path)
        manifest = _build_asset_manifest(context, audit, inventory)
        _write_json_exclusive(manifest_path, manifest, read_only=True)
        manifest_written = True
        audit_path.chmod(0o444)
        _require_exact_top_level(root, _SEALED_TOP_LEVEL, "sealed wrapper root")
    except Exception:
        if manifest_written and manifest_path.exists():
            manifest_path.chmod(0o644)
            manifest_path.unlink()
        if audit_path.exists():
            audit_path.chmod(0o644)
            audit_path.unlink()
        raise
    return {
        "status": "PASS",
        "asset_id": ASSET_ID,
        "asset_manifest": str(manifest_path),
        "asset_manifest_sha256": collector.sha256_file(manifest_path),
        "activation_audit": str(audit_path),
        "source_snapshot_id": context["source"]["sealed"]["snapshot_id"],
        "registered": False,
        "backtest_authorized": False,
    }


def _require_read_only(path: Path, label: str) -> None:
    mode = stat.S_IMODE(path.stat().st_mode)
    _require(mode & 0o222 == 0, f"{label} is not filesystem read-only")


def validate_asset(asset_root: Path) -> dict[str, Any]:
    """Rehash and revalidate the wrapper and its complete nested source seal."""

    root = _safe_root(asset_root)
    _require_exact_top_level(root, _SEALED_TOP_LEVEL, "sealed wrapper root")
    context = _collect_context(root)
    audit_path = root / ACTIVATION_AUDIT_NAME
    manifest_path = root / ASSET_MANIFEST_NAME
    audit = _read_json_object(audit_path, ACTIVATION_AUDIT_NAME)
    validated_at = _string(audit.get("validated_at"), "activation audit validated_at")
    try:
        timestamp = pd.Timestamp(validated_at)
    except (TypeError, ValueError) as exc:
        raise CY036BuildError("activation audit validated_at is invalid") from exc
    _require(
        not pd.isna(timestamp) and timestamp.tzinfo is not None,
        "validated_at must be timezone-aware",
    )

    expected_audit = _build_activation_audit(context, validated_at)
    _require(
        collector.canonical_json(audit) == collector.canonical_json(expected_audit),
        "activation_audit.json content or identity drifted",
    )
    inventory = _build_inventory(root, context["source"], audit_path)
    expected_manifest = _build_asset_manifest(context, expected_audit, inventory)
    manifest = _read_json_object(manifest_path, ASSET_MANIFEST_NAME)
    _require(
        collector.canonical_json(manifest) == collector.canonical_json(expected_manifest),
        "asset_manifest.json content or inventory drifted",
    )
    _require_read_only(audit_path, ACTIVATION_AUDIT_NAME)
    _require_read_only(manifest_path, ASSET_MANIFEST_NAME)
    _require(
        all(item.get("path") != ASSET_MANIFEST_NAME for item in inventory),
        "asset manifest must not include itself",
    )
    _require(
        not any(item.get("role") == "raw_page" for item in inventory),
        "nested raw pages must not be duplicated in the wrapper inventory",
    )
    return {
        "status": "PASS",
        "asset_id": ASSET_ID,
        "asset_manifest_sha256": collector.sha256_file(manifest_path),
        "files_verified_directly": len(inventory),
        "nested_files_verified": context["source"]["sealed"]["files_verified"],
        "source_snapshot_id": context["source"]["sealed"]["snapshot_id"],
        "registered": False,
        "backtest_authorized": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)
    for mode in ("build", "validate"):
        child = subparsers.add_parser(mode)
        child.add_argument("--asset-root", type=Path, required=True)
    args = parser.parse_args()
    result = (
        build_asset(args.asset_root) if args.mode == "build" else validate_asset(args.asset_root)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
