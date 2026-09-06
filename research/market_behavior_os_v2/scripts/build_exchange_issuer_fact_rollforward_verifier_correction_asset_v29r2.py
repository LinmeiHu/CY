#!/usr/bin/env python3
"""Build/validate CY-064, a verifier-only wrapper over immutable CY-063 Stage A."""

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
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from pytz.tzinfo import BaseTzInfo

from research.market_behavior_os_v2.scripts import (
    build_exchange_issuer_fact_rollforward_index_correction_asset_v29r2 as cy063_builder,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_issuer_fact_cooldown_v29r2_index_correction as cy063,
)
from scripts import validate_data_registry as registry_validator

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "configs/data_asset_registry.json"
ASSET_ID = "CY-064"
PREDECESSOR_ASSET_ID = "CY-063"
PREDECESSOR_AUTHORIZATION_ID = cy063.AUTHORIZATION_ID
AUTHORIZATION_ID = (
    "CYQ-AUTH-ASHARE-ISSUER-FACT-V29R2-ROLLFORWARD-2022-2026-VERIFIER-CORRECTION-V1"
)
EXPECTED_ROOT = Path(
    "/Users/linmei/Documents/CY/data/staging/"
    "CY-064-V29R2-ISSUER-FACT-ROLLFORWARD-VERIFIER-CORRECTION-2022-2026-V1"
)
CY063_ROOT = cy063_builder.EXPECTED_ROOT
CY063_OUTPUT_ROOT = cy063.EXPECTED_CORRECTED_OUTPUT_ROOT
VERIFICATION_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_v29r2_issuer_fact_rollforward_cy064_stage_a_verification_v1"
)
STAGE_B_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_v29r2_issuer_fact_rollforward_cy064_through_20260904_v1"
)
NEW_RUNNER = ROOT / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_true_gap_below_l_issuer_fact_cooldown_v29r2_verifier_correction.py"
)
PROTOCOL = ROOT / (
    "research/market_behavior_os_v2/experiments/"
    "ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-ISSUER-FACT-COOLDOWN-V29R2_"
    "rollforward_2022_2026_stage_a_verifier_correction_r3_freeze.json"
)
DISCREPANCY_AUDIT = ROOT / (
    "research/market_behavior_os_v2/artifacts/"
    "ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-ISSUER-FACT-COOLDOWN-V29R2_"
    "rollforward_cy063_stage_a_verifier_representation_failure.json"
)
PARENT_SELECTED = cy063_builder.PARENT_SELECTED
PARENT_OUTCOMES = cy063_builder.PARENT_OUTCOMES
PARENT_DAILY = cy063_builder.PARENT_DAILY

CY063_MANIFEST_SHA256 = "9f5e02860e28eb94157599b9bc2572bd04fd2cc195ee091e9d7b6a7a8cb8f2c4"
CY063_AUDIT_SHA256 = "2148823bbf5a98d3c5bf007f91a070f239d06ab354ef3ff00312b6f1e6880688"
CY063_BUILDER_SHA256 = "69e6443cc15dd892b8581799f84d20936d8435e5b1a02ba0c88b33eb04b0f34f"
CY063_RUNNER_SHA256 = "a867e5bbf54e09fa9b492df3eea437773e995e75c2d2093dab60b7e59438e584"
CY063_PROTOCOL_SHA256 = "e323cd126af2ef144b2fb42550e6545b6d21f976f2bcb28958118402fd667828"
CY063_STAGE_HASHES = {
    "classified_events.parquet": (
        "1140acde5b10686371a51d6ac3a40573e21a8eb4feacd2c37373f5eb7f866d51"
    ),
    "freeze.json": "a71733a36d423cc69c2880df5f8b50f1336b9dc57551d9a8784ef8edb11f0658",
    "pretitle_route_freeze.json": (
        "5b142633fbde9f953bbb5376f0a7b653ce42e973d04d71e1ff485c7debb0eac0"
    ),
    "rejected_entries.parquet": (
        "f79baf069ec7b92aead6cac7fdf2107082b31bafce61a8801dda1f7752c7810d"
    ),
    "selected_entries.parquet": (
        "e5d4aba6aac8474b2e8580ebafc8a5089a0f621224d6ca4b0a061a612ba8a767"
    ),
    "selector_audit.parquet": (
        "d5e95fbb14905db793fdd68e2e782416601a4690dc121a480b1d85bbc4e11d24"
    ),
    "title_route_selection.parquet": (
        "d5ec0a5f89fdd4d0fba05dc3954241fdca0aa62d7190ea3049ae1a8dfb94fad3"
    ),
}
CY063_STAGE_ROLE_BY_FILE = {
    "classified_events.parquet": "cy063_stage_a_classified_events",
    "freeze.json": "cy063_stage_a_freeze",
    "pretitle_route_freeze.json": "cy063_stage_a_pretitle_route_freeze",
    "rejected_entries.parquet": "cy063_stage_a_rejected_entries",
    "selected_entries.parquet": "cy063_stage_a_selected_entries",
    "selector_audit.parquet": "cy063_stage_a_selector_audit",
    "title_route_selection.parquet": "cy063_stage_a_title_route_selection",
}


class VerifierCorrectionAssetError(RuntimeError):
    """Fail closed on any CY-064 identity, comparison, or boundary drift."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerifierCorrectionAssetError(message)


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
        raise VerifierCorrectionAssetError(f"invalid {label}: {path}") from exc
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
        raise VerifierCorrectionAssetError(f"refusing to overwrite {path}") from exc
    path.chmod(0o444)


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


def require_frame_exact(label: str, persisted: pd.DataFrame, reproduced: pd.DataFrame) -> None:
    try:
        pd.testing.assert_frame_equal(persisted, reproduced, check_dtype=True, check_exact=True)
    except AssertionError as exc:
        raise VerifierCorrectionAssetError(f"{label}: {exc}") from exc


def require_classified_canonical_exact(
    persisted: pd.DataFrame, reproduced: pd.DataFrame
) -> dict[str, Any]:
    """Permit exactly two proven parquet/in-memory representation differences."""

    require(
        list(persisted.columns) == list(reproduced.columns),
        "classified columns/order drifted",
    )
    try:
        pd.testing.assert_index_equal(persisted.index, reproduced.index, exact=True)
    except AssertionError as exc:
        raise VerifierCorrectionAssetError(f"classified index drifted: {exc}") from exc
    require(
        "available_at" in persisted.columns and "risk_family" in persisted.columns,
        "canonical comparison columns are missing",
    )

    left_time = persisted["available_at"]
    right_time = reproduced["available_at"]
    for side, series in (("persisted", left_time), ("reproduced", right_time)):
        require(
            isinstance(series.dtype, pd.DatetimeTZDtype)
            and series.dtype.unit == "ns"
            and str(series.dtype.tz) == "Asia/Shanghai",
            f"{side} available_at is not datetime64[ns, Asia/Shanghai]",
        )
    require(
        isinstance(left_time.dtype.tz, BaseTzInfo)
        and getattr(left_time.dtype.tz, "zone", None) == "Asia/Shanghai"
        and isinstance(right_time.dtype.tz, ZoneInfo)
        and right_time.dtype.tz.key == "Asia/Shanghai",
        "available_at timezone backends are not the frozen persisted-pytz/reproduced-zoneinfo pair",
    )
    require(
        np.array_equal(left_time.isna().to_numpy(), right_time.isna().to_numpy())
        and np.array_equal(left_time.array.asi8, right_time.array.asi8),
        "available_at NA mask or UTC nanoseconds drifted",
    )

    left_risk = persisted["risk_family"]
    right_risk = reproduced["risk_family"]
    require(
        left_risk.dtype == object and right_risk.dtype == object,
        "risk_family must remain object dtype on both sides",
    )
    left_missing = left_risk.isna().to_numpy()
    right_missing = right_risk.isna().to_numpy()
    require(
        np.array_equal(left_missing, right_missing),
        "risk_family NA mask drifted",
    )
    for values, missing, side in (
        (left_risk.tolist(), left_missing, "persisted"),
        (right_risk.tolist(), right_missing, "reproduced"),
    ):
        require(
            all(
                (value is None or value is pd.NA)
                for value, is_missing in zip(values, missing, strict=True)
                if is_missing
            ),
            f"{side} risk_family has an unapproved missing representation",
        )
        require(
            all(
                isinstance(value, str)
                for value, is_missing in zip(values, missing, strict=True)
                if not is_missing
            ),
            f"{side} risk_family has a non-string non-null value",
        )
    require(
        left_risk.loc[~left_missing].tolist() == right_risk.loc[~right_missing].tolist(),
        "risk_family non-null values drifted",
    )

    exact_columns = [
        column for column in persisted.columns if column not in {"available_at", "risk_family"}
    ]
    require_frame_exact(
        "classified columns outside the two approved representations drifted",
        persisted[exact_columns],
        reproduced[exact_columns],
    )
    return {
        "frame_rows": len(persisted),
        "frame_columns": len(persisted.columns),
        "columns_order_and_index_exact": True,
        "available_at_contract": (
            "both DatetimeTZDtype ns Asia/Shanghai; identical NA mask and UTC nanoseconds; "
            "timezone backend object identity alone may differ"
        ),
        "risk_family_contract": (
            "both object dtype; identical NA mask; missing scalar only None or pd.NA; "
            "all non-null strings exact"
        ),
        "all_other_columns_dtype_value_order_exact": True,
    }


def _stage_path(name: str) -> Path:
    return CY063_OUTPUT_ROOT / "stage_a" / name


def validate_discrepancy_audit() -> dict[str, Any]:
    audit = read_json(DISCREPANCY_AUDIT, "CY-063 verifier discrepancy audit")
    require(
        audit.get("status") == "FAILED_CLOSED_BEFORE_STAGE_B"
        and audit.get("asset_id") == PREDECESSOR_ASSET_ID
        and audit.get("stage_a_freeze", {}).get("sha256") == CY063_STAGE_HASHES["freeze.json"]
        and audit.get("immutable_inventory") == CY063_STAGE_HASHES
        and audit.get("first_difference", {}).get("column_name") == "available_at"
        and audit.get("first_difference", {}).get("na_mask_exact") is True
        and audit.get("first_difference", {}).get("utc_nanoseconds_exact") is True
        and audit.get("second_serialization_representation", {}).get("column_name")
        == "risk_family"
        and audit.get("second_serialization_representation", {}).get("missing_rows") == 7908
        and audit.get("full_reproduction", {}).get(
            "selector_audit_strict_exact_after_canonical_classified_comparison"
        )
        is True
        and audit.get("scientific_boundary", {}).get("stage_b_started") is False
        and audit.get("scientific_boundary", {}).get("stage_b_attempt_seal_created") is False
        and audit.get("disposition", {}).get("cy063_output_is_immutable_failure_evidence") is True
        and audit.get("disposition", {}).get("cy063_stage_b_authorized") is False
        and audit.get("disposition", {}).get(
            "successor_must_not_materialize_new_stage_a_artifacts_or_selection"
        )
        is True
        and audit.get("disposition", {}).get(
            "successor_must_perform_in_memory_deterministic_stage_a_verification_replay"
        )
        is True,
        "CY-063 verifier discrepancy disclosure drifted",
    )
    return audit


def verify_cy063_frozen_stage_a() -> dict[str, Any]:
    """Reproduce CY-063 Stage A without rewriting it or reading outcome content rows."""

    exact_top(CY063_OUTPUT_ROOT, {"stage_a"})
    exact_top(CY063_OUTPUT_ROOT / "stage_a", set(CY063_STAGE_HASHES))
    require_read_only(CY063_OUTPUT_ROOT, "CY-063 output root")
    require_read_only(CY063_OUTPUT_ROOT / "stage_a", "CY-063 Stage-A directory")
    for name, expected_hash in CY063_STAGE_HASHES.items():
        path = _stage_path(name)
        require(
            path.is_file() and not path.is_symlink() and sha256(path) == expected_hash,
            f"CY-063 Stage-A artifact drifted: {name}",
        )
        require_read_only(path, f"CY-063 Stage-A artifact {name}")

    identity = cy063.verify_asset(CY063_ROOT, PARENT_SELECTED)
    freeze = read_json(_stage_path("freeze.json"), "CY-063 Stage-A freeze")
    require(
        freeze.get("stage") == "CY063_V29R2_FIXED_RULE_COHORT_FROZEN_BEFORE_OUTCOME_ACCESS"
        and freeze.get("correction_wrapper_identity") == identity
        and freeze.get("selected_signals") == 186
        and freeze.get("rejected_signals") == 11
        and freeze.get("selected_by_signal_year")
        == {"2022": 40, "2023": 10, "2024": 68, "2025": 36, "2026": 32}
        and freeze.get("outcome_or_daily_parquet_content_rows_parsed") is False
        and freeze.get("hashes", {}).get("classified_events")
        == CY063_STAGE_HASHES["classified_events.parquet"]
        and freeze.get("hashes", {}).get("title_route_selection")
        == CY063_STAGE_HASHES["title_route_selection.parquet"]
        and freeze.get("hashes", {}).get("selector_audit")
        == CY063_STAGE_HASHES["selector_audit.parquet"]
        and freeze.get("hashes", {}).get("selected_entries")
        == CY063_STAGE_HASHES["selected_entries.parquet"]
        and freeze.get("hashes", {}).get("rejected_entries")
        == CY063_STAGE_HASHES["rejected_entries.parquet"],
        "CY-063 Stage-A freeze identity/counts drifted",
    )

    parent = pd.read_parquet(PARENT_SELECTED)
    title_routes = pd.read_parquet(_stage_path("title_route_selection.parquet"))
    classified = pd.read_parquet(_stage_path("classified_events.parquet"))
    selector_audit = pd.read_parquet(_stage_path("selector_audit.parquet"))
    selected = pd.read_parquet(_stage_path("selected_entries.parquet"))
    rejected = pd.read_parquet(_stage_path("rejected_entries.parquet"))

    timed = cy063.predecessor.derive_causal_available_at(cy063._source_route())
    current_selection, route_audit = cy063.corrected_select_window_routes(timed, parent)
    current_title_routes = current_selection[
        [*cy063.ROUTE_COLUMNS, "causal_available_at"]
    ].reset_index(drop=True)
    require_frame_exact(
        "CY-063 title-free route no longer reproduces", title_routes, current_title_routes
    )
    require(freeze.get("route_audit") == route_audit, "CY-063 route audit no longer reproduces")

    current_with_titles = cy063.predecessor.attach_titles(cy063.PREDECESSOR_ROOT, title_routes)
    current_classified = cy063.predecessor.classify_titles(current_with_titles)
    comparator = require_classified_canonical_exact(classified, current_classified)

    current_audit = cy063.predecessor.apply_cooldown(parent, current_classified)
    current_selected = current_audit.loc[
        current_audit.v29r2_issuer_fact_cooldown_gate
    ].reset_index(drop=True)
    current_rejected = current_audit.loc[
        ~current_audit.v29r2_issuer_fact_cooldown_gate
    ].reset_index(drop=True)
    for label, persisted, reproduced in (
        ("selector audit", selector_audit, current_audit.reset_index(drop=True)),
        ("selected entries", selected, current_selected),
        ("rejected entries", rejected, current_rejected),
    ):
        require_frame_exact(f"CY-063 {label} no longer reproduces", persisted, reproduced)

    require(
        len(parent) == len(selector_audit) == 197
        and len(selected) == 186
        and len(rejected) == 11
        and set(selected.gap_id.astype(str)).isdisjoint(set(rejected.gap_id.astype(str)))
        and set(selected.gap_id.astype(str)).union(set(rejected.gap_id.astype(str)))
        == set(parent.gap_id.astype(str)),
        "CY-063 selector partition drifted",
    )
    execution_contract = cy063.predecessor.verify_execution_contract(selected)
    require(
        freeze.get("execution_contract") == execution_contract,
        "CY-063 execution contract drifted",
    )
    require(
        classified.empty
        or pd.to_datetime(classified.available_at, errors="raise")
        .le(
            pd.Timestamp(cy063.MATURE_SIGNAL_CUTOFF, tz="Asia/Shanghai")
            + pd.Timedelta(hours=23, minutes=59, seconds=59)
        )
        .all(),
        "CY-063 classifications exceed mature signal boundary",
    )
    validate_discrepancy_audit()
    return {
        "verified": True,
        "cy063_identity": identity,
        "cy063_stage_a_freeze_sha256": CY063_STAGE_HASHES["freeze.json"],
        "cy063_stage_a_hashes": dict(CY063_STAGE_HASHES),
        "parent_signals": 197,
        "selected_signals": 186,
        "rejected_signals": 11,
        "selected_by_signal_year": {
            "2022": 40,
            "2023": 10,
            "2024": 68,
            "2025": 36,
            "2026": 32,
        },
        "route_audit": route_audit,
        "classified_comparator": comparator,
        "selector_outputs_strict_exact": True,
        "execution_contract": execution_contract,
        "outcome_or_daily_parquet_content_rows_parsed": False,
        "stage_b_started": False,
    }


def validate_protocol(runner: Path) -> dict[str, Any]:
    protocol = read_json(PROTOCOL, "CY-064 verifier correction protocol")
    software = protocol.get("software_identity", {})
    expected_software = {
        "verifier_correction_asset_builder": Path(__file__).resolve(),
        "verifier_stage_b_runner": runner,
        "cy063_correction_asset_builder": Path(cy063_builder.__file__).resolve(),
        "cy063_rollforward_runner": Path(cy063.__file__).resolve(),
    }
    require(
        protocol.get("status") == "FROZEN_VERIFIER_ONLY_BEFORE_OUTCOME_ACCESS"
        and protocol.get("asset_id") == ASSET_ID
        and protocol.get("predecessor_asset_id") == PREDECESSOR_ASSET_ID
        and protocol.get("cy063_stage_a_freeze_sha256") == CY063_STAGE_HASHES["freeze.json"]
        and protocol.get("verifier_only") is True
        and protocol.get("new_stage_a_artifacts_or_selection_materialization") is False
        and protocol.get("in_memory_deterministic_stage_a_verification_replay") is True
        and protocol.get("in_memory_title_classification_verification_replay") is True
        and protocol.get("rule_or_threshold_changed") is False
        and protocol.get("verification_root") == str(VERIFICATION_ROOT)
        and protocol.get("stage_b_output_root") == str(STAGE_B_ROOT)
        and protocol.get("stage_b_contract", {}).get("expected_outer_freeze_sha256_required")
        is True
        and protocol.get("stage_b_contract", {}).get("pre_outcome_attempt_seal_required") is True
        and protocol.get("stage_b_contract", {}).get("single_attempt_only") is True,
        "CY-064 protocol semantics drifted",
    )
    require(
        protocol.get("cy063_stage_a_artifact_hashes") == CY063_STAGE_HASHES
        and protocol.get("scientific_boundary", {}).get(
            "outcome_or_daily_parquet_content_rows_parsed_before_stage_b_attempt_seal"
        )
        is False
        and protocol.get("scientific_boundary", {}).get(
            "performance_statistics_computed_before_stage_b_attempt_seal"
        )
        is False,
        "CY-064 protocol frozen stage/scientific boundary drifted",
    )
    require(
        protocol.get("canonical_comparator")
        == {
            "permitted_representation_columns": ["available_at", "risk_family"],
            "available_at": {
                "dtype_both": "DatetimeTZDtype[ns, Asia/Shanghai]",
                "na_mask": "exact",
                "utc_nanoseconds": "exact",
                "only_permitted_difference": "pytz versus zoneinfo timezone backend object",
            },
            "risk_family": {
                "dtype_both": "object",
                "na_mask": "exact",
                "non_null_type": "str",
                "non_null_values": "exact",
                "only_permitted_missing_scalars": ["None", "pd.NA"],
            },
            "all_other_columns": "dtype, value, column order, row order and index exact",
            "selector_audit_selected_rejected": "strict frame exact after reclassification",
        },
        "CY-064 canonical comparator scope drifted",
    )
    require(set(software) == set(expected_software), "CY-064 software roles drifted")
    for role, path in expected_software.items():
        fact = software[role]
        require(
            Path(str(fact.get("path", ""))).resolve() == path
            and fact.get("sha256") == sha256(path),
            f"CY-064 protocol software identity drifted: {role}",
        )
    require(
        protocol.get("discrepancy_audit")
        == {"path": str(DISCREPANCY_AUDIT), "sha256": sha256(DISCREPANCY_AUDIT)},
        "CY-064 protocol discrepancy audit identity drifted",
    )
    return protocol


def _cy063_manifest() -> dict[str, Any]:
    return read_json(CY063_ROOT / "asset_manifest.json", "CY-063 manifest")


def _external_paths() -> list[tuple[str, Path, bool, bool]]:
    paths: list[tuple[str, Path, bool, bool]] = [
        ("verifier_correction_asset_builder", Path(__file__).resolve(), False, True),
        ("stage_a_verifier_correction_r3_freeze", PROTOCOL, True, False),
        ("verifier_stage_b_runner", NEW_RUNNER, False, False),
        ("cy063_stage_a_verifier_discrepancy_audit", DISCREPANCY_AUDIT, True, False),
        ("cy063_asset_manifest", CY063_ROOT / "asset_manifest.json", True, False),
    ]
    parsed_cy063_roles = {
        "activation_audit",
        "stage_a_index_correction_r2_freeze",
        "predecessor_asset_manifest",
        "predecessor_activation_audit",
        "announcement_route_index",
        "calendar_coverage_correction_r1_freeze",
        "stage_a_attempt1_failure_audit",
        "stage_a_attempt1_failure_audit_correction_v2",
        "failed_stage_a_title_route_selection",
        "failed_stage_a_pretitle_route_freeze",
        "parent_selected",
    }
    invoked_cy063_roles = {
        "correction_asset_builder",
        "rollforward_runner",
        "predecessor_asset_builder",
        "predecessor_rollforward_runner",
        "issuer_fact_classifier",
        "collector",
        "sealer",
    }
    for item in _cy063_manifest().get("inventory", []):
        role = str(item.get("role"))
        paths.append(
            (
                f"cy063_bound_{role}",
                Path(str(item.get("path", ""))),
                role in parsed_cy063_roles,
                role in invoked_cy063_roles,
            )
        )
    for name, role in CY063_STAGE_ROLE_BY_FILE.items():
        paths.append((role, _stage_path(name), True, False))
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
        file_fact(
            "activation_audit",
            audit_path,
            payload_deserialized=True,
            runtime_invoked=False,
        )
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
    require(len(roles) == len(set(roles)), "CY-064 inventory has duplicate roles")
    return result


def validate_dependencies(
    runner: Path, *, require_outputs_absent: bool = False
) -> dict[str, Any]:
    require(runner.resolve() == NEW_RUNNER and runner.is_file(), "unexpected CY-064 runner")
    if require_outputs_absent:
        require(not VERIFICATION_ROOT.exists(), "CY-064 verification root must be absent at build")
        require(not STAGE_B_ROOT.exists(), "CY-064 Stage-B root must be absent at build")
    require(
        sha256(CY063_ROOT / "asset_manifest.json") == CY063_MANIFEST_SHA256
        and sha256(CY063_ROOT / "activation_audit.json") == CY063_AUDIT_SHA256
        and sha256(Path(cy063_builder.__file__).resolve()) == CY063_BUILDER_SHA256
        and sha256(Path(cy063.__file__).resolve()) == CY063_RUNNER_SHA256
        and sha256(cy063_builder.CORRECTION_R2) == CY063_PROTOCOL_SHA256,
        "CY-063 registered wrapper identity drifted",
    )
    protocol = validate_protocol(runner)
    stage = verify_cy063_frozen_stage_a()
    registry = read_json(REGISTRY, "central registry")
    errors = registry_validator.validate_registry(registry, verify_paths=True, verify_hashes=True)
    require(not errors, f"central registry validation failed: {errors}")
    assets = [x for x in registry.get("assets", []) if x.get("asset_id") == PREDECESSOR_ASSET_ID]
    auths = [
        x
        for x in registry.get("bounded_authorizations", [])
        if x.get("authorization_id") == PREDECESSOR_AUTHORIZATION_ID
    ]
    require(len(assets) == len(auths) == 1, "registered CY-063 identity is missing")
    require(
        assets[0].get("lineage", {}).get("manifest_sha256") == CY063_MANIFEST_SHA256
        and auths[0].get("asset_id") == PREDECESSOR_ASSET_ID,
        "registered CY-063 identity drifted",
    )
    return {
        "protocol": protocol,
        "cy063_stage_a_verification": stage,
        "cy063_registry_identity": {
            "asset_value_sha256": value_sha256(assets[0]),
            "authorization_value_sha256": value_sha256(auths[0]),
        },
    }


def build_audit(deps: Mapping[str, Any], created_at: str) -> dict[str, Any]:
    return {
        "audit_schema": "CY_VERIFIER_ONLY_CORRECTION_WRAPPER_ACTIVATION_AUDIT_V1",
        "asset_id": ASSET_ID,
        "created_at": created_at,
        "status": "PASS_PENDING_CENTRAL_REGISTRATION",
        "predecessor_asset_id": PREDECESSOR_ASSET_ID,
        "predecessor_manifest_sha256": CY063_MANIFEST_SHA256,
        "predecessor_registry_identity": deps["cy063_registry_identity"],
        "cy063_stage_a_freeze_sha256": CY063_STAGE_HASHES["freeze.json"],
        "cy063_stage_a_artifact_hashes": dict(CY063_STAGE_HASHES),
        "discrepancy_audit": {
            "path": str(DISCREPANCY_AUDIT),
            "sha256": sha256(DISCREPANCY_AUDIT),
        },
        "correction": {
            "verifier_only": True,
            "new_stage_a_artifacts_or_selection_materialization": False,
            "in_memory_deterministic_stage_a_verification_replay": True,
            "in_memory_title_classification_verification_replay": True,
            "available_at_timezone_backend_only": True,
            "risk_family_none_pd_na_only": True,
            "all_other_columns_and_selector_outputs_strict_exact": True,
            "rule_selector_threshold_source_causal_execution_or_portfolio_changed": False,
        },
        "stage_boundary": {
            "verification_root": str(VERIFICATION_ROOT),
            "verification_root_initially_absent": True,
            "outer_freeze_only_exact_top": True,
            "stage_b_output_root": str(STAGE_B_ROOT),
            "stage_b_root_initially_absent": True,
            "stage_b_requires_independently_supplied_outer_freeze_sha256": True,
            "stage_b_replays_canonical_verifier_before_outcome_parse": True,
            "stage_b_attempt_seal_is_first_top_level_file_and_read_only": True,
            "single_stage_b_attempt_only": True,
            "parent_outcomes_and_daily_identity_bytes_hashed": True,
            "parent_outcomes_and_daily_parquet_content_rows_parsed": False,
        },
    }


def build_manifest(
    asset_root: Path,
    deps: Mapping[str, Any],
    created_at: str,
    bound_inventory: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "manifest_schema": "CY_IMMUTABLE_VERIFIER_CORRECTION_WRAPPER_MANIFEST_V1",
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
            "root": str(CY063_ROOT),
            "manifest_path": str(CY063_ROOT / "asset_manifest.json"),
            "manifest_sha256": CY063_MANIFEST_SHA256,
            "activation_audit_sha256": CY063_AUDIT_SHA256,
            "registry_identity": deps["cy063_registry_identity"],
        },
        "cy063_stage_a": {
            "root": str(CY063_OUTPUT_ROOT),
            "freeze_sha256": CY063_STAGE_HASHES["freeze.json"],
            "artifact_hashes": dict(CY063_STAGE_HASHES),
            "selected_signals": 186,
            "rejected_signals": 11,
            "stage_b_started": False,
        },
        "correction": {
            "protocol_path": str(PROTOCOL),
            "protocol_sha256": sha256(PROTOCOL),
            "discrepancy_audit_path": str(DISCREPANCY_AUDIT),
            "discrepancy_audit_sha256": sha256(DISCREPANCY_AUDIT),
            "verifier_only": True,
            "new_stage_a_artifacts_or_selection_materialization": False,
            "in_memory_deterministic_stage_a_verification_replay": True,
            "rule_or_threshold_changed": False,
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
            "outer_freeze_is_only_file_in_read_only_verification_root": True,
            "stage_b_requires_expected_outer_freeze_sha256": True,
            "stage_b_revalidates_cy063_seven_files_and_canonical_reproduction": True,
            "stage_b_attempt_seal_precedes_any_outcome_or_daily_parquet_read": True,
        },
        "limitations": [
            (
                "inherits CY-063/CY-062 PIT-B current-enumeration "
                "revision/deletion-history limitations"
            ),
            "corrects only the verifier treatment of two proven serialization representations",
            "does not materialize, copy, mutate, or reinterpret CY-063 Stage-A artifacts",
            "does replay Stage-A transforms in memory solely for deterministic verification",
            "2022-2024 are dependent fixed-rule validation, not pristine OOS",
            "2025-2026 are post-selection temporal diagnostics, not pristine validation",
            "strict PIT-A, live trading, sizing and order generation remain prohibited",
        ],
    }


def build(asset_root: Path, runner: Path) -> dict[str, Any]:
    require(asset_root.resolve() == EXPECTED_ROOT, "unexpected CY-064 root")
    require(not asset_root.exists(), f"refusing non-pristine CY-064 root: {asset_root}")
    deps = validate_dependencies(runner.resolve(), require_outputs_absent=True)
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
    asset_root.chmod(0o555)
    return {
        "asset_manifest": str(manifest_path),
        "asset_manifest_sha256": sha256(manifest_path),
        "activation_audit_sha256": sha256(audit_path),
        "inventory_roles": len(bound_inventory),
        "cy063_stage_a_freeze_sha256": CY063_STAGE_HASHES["freeze.json"],
    }


def validate(asset_root: Path) -> dict[str, Any]:
    require(asset_root.resolve() == EXPECTED_ROOT, "unexpected CY-064 root")
    exact_top(asset_root, {"activation_audit.json", "asset_manifest.json"})
    require_read_only(asset_root, "CY-064 root")
    manifest_path = asset_root / "asset_manifest.json"
    audit_path = asset_root / "activation_audit.json"
    require_read_only(manifest_path, "CY-064 manifest")
    require_read_only(audit_path, "CY-064 audit")
    manifest = read_json(manifest_path, "CY-064 manifest")
    inventory_by_role = {item.get("role"): item for item in manifest.get("inventory", [])}
    runner_fact = inventory_by_role.get("verifier_stage_b_runner")
    require(runner_fact is not None, "CY-064 manifest lacks verifier runner")
    runner = Path(str(runner_fact.get("path", ""))).resolve()
    deps = validate_dependencies(runner)
    expected_audit = build_audit(deps, str(manifest.get("created_at")))
    require(read_json(audit_path, "CY-064 audit") == expected_audit, "CY-064 audit drifted")
    expected_inventory = inventory(audit_path)
    expected_manifest = build_manifest(
        asset_root, deps, str(manifest.get("created_at")), expected_inventory
    )
    require(manifest == expected_manifest, "CY-064 manifest semantic reconstruction failed")
    return {
        "valid": True,
        "manifest_sha256": sha256(manifest_path),
        "activation_audit_sha256": sha256(audit_path),
        "inventory_roles": len(expected_inventory),
        "cy063_registry_identity": deps["cy063_registry_identity"],
        "cy063_stage_a_freeze_sha256": CY063_STAGE_HASHES["freeze.json"],
        "stage_a_verification": deps["cy063_stage_a_verification"],
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
