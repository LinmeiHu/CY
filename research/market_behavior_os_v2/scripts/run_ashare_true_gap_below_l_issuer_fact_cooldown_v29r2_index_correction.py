#!/usr/bin/env python3
"""Run the CY-063 index-only correction of the frozen V29R2 roll-forward."""

from __future__ import annotations

import argparse
import json
import stat
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    build_exchange_issuer_fact_rollforward_asset_v29r2 as predecessor_builder,
)
from research.market_behavior_os_v2.scripts import (
    build_exchange_issuer_fact_rollforward_index_correction_asset_v29r2 as correction_builder,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_issuer_fact_cooldown_v29r2_rollforward as predecessor,
)
from scripts import validate_data_registry as registry_validator

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "configs/data_asset_registry.json"
ASSET_ID = "CY-063"
AUTHORIZATION_ID = "CYQ-AUTH-ASHARE-ISSUER-FACT-V29R2-ROLLFORWARD-2022-2026-INDEX-CORRECTION-V1"
AUTHORIZATION_PURPOSE = "ASHARE_ISSUER_FACT_V29R2_ROLLFORWARD_2022_2026"
PREDECESSOR_ASSET_ID = "CY-062"
PREDECESSOR_AUTHORIZATION_ID = "CYQ-AUTH-ASHARE-ISSUER-FACT-V29R2-ROLLFORWARD-2022-2026-V1"
PREDECESSOR_ROOT = correction_builder.PREDECESSOR_ROOT
EXPECTED_CORRECTED_OUTPUT_ROOT = correction_builder.CORRECTED_OUTPUT_ROOT
CORRECTION_ROLE = "stage_a_index_correction_r2_freeze"
YEARS = predecessor.YEARS
DATA_END = predecessor.DATA_END
MATURE_SIGNAL_CUTOFF = predecessor.MATURE_SIGNAL_CUTOFF
ROUTE_COLUMNS = predecessor.ROUTE_COLUMNS

AUTH_REQUIRED_ARTIFACT_ROLES = set(correction_builder.INVENTORY_ROLE_ORDER)
EXPECTED_AUTH_ALLOWED_USES = [
    (
        "apply only the index-normalization correction to the frozen V29R2 2022-2026 "
        "title-free route persistence check, then classify the exact routed title rows"
    ),
    (
        "after an independently verified CY-063 Stage-A SHA, run one exclusive unchanged "
        "A67 H20 40-bp K80 replay under a read-only pre-outcome attempt seal"
    ),
]
EXPECTED_AUTH_BLOCKED_USES = [
    (
        "overwriting CY-062 or its failed Stage-A evidence, changing source, causal, "
        "taxonomy, cooldown, threshold, execution or portfolio semantics"
    ),
    "unbound files, repeated Stage-B attempts, strict PIT-A claims, live trading or sizing",
    (
        "claiming any period as untouched pristine OOS or treating missing unproven "
        "announcement coverage as zero events"
    ),
]


class IndexCorrectionError(RuntimeError):
    """Fail closed on wrapper, stage, outcome-boundary, or replay drift."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise IndexCorrectionError(message)


def sha256(path: Path) -> str:
    return predecessor.sha256(path)


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        return predecessor.read_json(path, label)
    except predecessor.RollforwardError as exc:
        raise IndexCorrectionError(str(exc)) from exc


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    try:
        predecessor.write_json_exclusive(path, value)
    except predecessor.RollforwardError as exc:
        raise IndexCorrectionError(str(exc)) from exc


def write_parquet_exclusive(path: Path, frame: pd.DataFrame) -> None:
    try:
        predecessor.write_parquet_exclusive(path, frame)
    except predecessor.RollforwardError as exc:
        raise IndexCorrectionError(str(exc)) from exc


def value_sha256(value: Any) -> str:
    return predecessor.value_sha256(value)


def corrected_select_window_routes(
    timed: pd.DataFrame, entries: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Apply the sole R2 correction: normalize the non-semantic row index before freeze."""

    selected, audit = predecessor.select_window_routes(timed, entries)
    return selected.reset_index(drop=True), audit


def require_frame_exact(label: str, persisted: pd.DataFrame, reproduced: pd.DataFrame) -> None:
    try:
        pd.testing.assert_frame_equal(persisted, reproduced, check_dtype=True, check_exact=True)
    except AssertionError as exc:
        raise IndexCorrectionError(f"{label}: {exc}") from exc


def verify_registration(asset_root: Path) -> dict[str, Any]:
    registry = read_json(REGISTRY, "data registry")
    errors = registry_validator.validate_registry(registry, verify_paths=True, verify_hashes=True)
    require(not errors, f"central data registry validation failed: {errors}")
    require(
        registry.get("global_gate", {}).get("free_causal_research_ready") is True
        and registry.get("global_gate", {}).get("backtest_authorized") is True,
        "central causal-research/backtest gate is closed",
    )
    assets = [x for x in registry.get("assets", []) if x.get("asset_id") == ASSET_ID]
    auths = [
        x
        for x in registry.get("bounded_authorizations", [])
        if x.get("authorization_id") == AUTHORIZATION_ID
    ]
    predecessors = [
        x for x in registry.get("assets", []) if x.get("asset_id") == PREDECESSOR_ASSET_ID
    ]
    predecessor_auths = [
        x
        for x in registry.get("bounded_authorizations", [])
        if x.get("authorization_id") == PREDECESSOR_AUTHORIZATION_ID
    ]
    require(
        len(assets) == len(auths) == len(predecessors) == len(predecessor_auths) == 1,
        "CY-063 or immutable CY-062 predecessor registration is missing",
    )
    asset, auth = assets[0], auths[0]
    predecessor_asset, predecessor_auth = predecessors[0], predecessor_auths[0]
    manifest_path = asset_root / "asset_manifest.json"
    manifest = read_json(manifest_path, "CY-063 manifest")
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
        and lineage.get("component_assets") == [PREDECESSOR_ASSET_ID]
        and lineage.get("bounded_authorization_id") == AUTHORIZATION_ID
        and auth.get("asset_id") == ASSET_ID
        and auth.get("purpose") == AUTHORIZATION_PURPOSE,
        "CY-063 registry semantics drifted",
    )
    coverage = asset.get("coverage", {})
    require(
        coverage.get("sse_query_start") == "1990-12-19"
        and coverage.get("szse_query_start") == "2021-10-18"
        and coverage.get("query_end") == "2026-08-03"
        and coverage.get("signal_start") == "2022-01-01"
        and coverage.get("signal_end") == "2026-08-03"
        and coverage.get("outcome_end") == "2026-09-04"
        and coverage.get("route_rows") == 149545,
        "CY-063 registered coverage drifted",
    )
    require(
        auth.get("dependency_asset_id") == PREDECESSOR_ASSET_ID
        and auth.get("dependency_status") == "RESEARCH_CONDITIONAL"
        and predecessor_asset.get("status") == auth.get("dependency_status")
        and predecessor_asset.get("lineage", {}).get("manifest_sha256")
        == correction_builder.EXPECTED_HASHES["predecessor_asset_manifest"]
        and predecessor_auth.get("asset_id") == PREDECESSOR_ASSET_ID,
        "CY-063 predecessor dependency drifted",
    )
    scope = auth.get("scope", {})
    require(
        scope.get("project") == "research/market_behavior_os_v2"
        and scope.get("start") == "1990-12-19"
        and scope.get("end") == "2026-09-04"
        and scope.get("sse_query_start") == "1990-12-19"
        and scope.get("szse_query_start") == "2021-10-18"
        and scope.get("announcement_query_end") == "2026-08-03"
        and scope.get("signal_start") == "2022-01-01"
        and scope.get("signal_end") == "2026-08-03"
        and scope.get("outcome_end") == "2026-09-04"
        and scope.get("corrected_output_root") == str(EXPECTED_CORRECTED_OUTPUT_ROOT),
        "CY-063 authorization scope drifted",
    )
    require(
        auth.get("current_survivor_fallback_allowed") is False
        and auth.get("record_level_available_at_available") is True
        and auth.get("event_classification_authorized") is True
        and auth.get("validation_outcome_join_authorized") is True
        and auth.get("portfolio_replay_authorized") is True
        and auth.get("strict_pit_a_authorized") is False
        and auth.get("live_trading_authorized") is False
        and auth.get("v29r1_fallback_authorized") is False
        and auth.get("post_2024_pristine_validation_claim_authorized") is False
        and auth.get("index_normalization_only") is True
        and auth.get("single_stage_b_attempt_authorized") is True,
        "CY-063 authorization flags drifted",
    )
    require(
        auth.get("bound_manifest") == {"path": str(manifest_path), "sha256": sha256(manifest_path)},
        "CY-063 bound manifest drifted",
    )
    inventory = {item.get("role"): item for item in manifest.get("inventory", [])}
    correction_fact = inventory.get(CORRECTION_ROLE)
    require(correction_fact is not None, "CY-063 correction artifact is missing")
    expected_strategy = {
        "path": correction_fact.get("path"),
        "sha256": correction_fact.get("sha256"),
    }
    protocol = auth.get("bound_protocol", {})
    require(
        auth.get("bound_strategy") == expected_strategy
        and protocol.get("path") == expected_strategy["path"]
        and protocol.get("sha256") == expected_strategy["sha256"]
        and protocol.get("runner_path") == str(Path(__file__).resolve())
        and protocol.get("runner_sha256") == sha256(Path(__file__).resolve()),
        "CY-063 strategy/protocol binding drifted",
    )
    artifacts = auth.get("bound_artifacts", [])
    fingerprints = {item.get("role"): item for item in artifacts}
    require(
        isinstance(artifacts, list)
        and len(fingerprints) == len(artifacts)
        and set(fingerprints) == AUTH_REQUIRED_ARTIFACT_ROLES
        and set(inventory) == AUTH_REQUIRED_ARTIFACT_ROLES,
        "CY-063 exact artifact role set drifted",
    )
    for role, item in fingerprints.items():
        path = Path(str(item.get("path", "")))
        manifest_item = inventory[role]
        require(
            path.is_file()
            and not path.is_symlink()
            and sha256(path) == item.get("sha256")
            and {"path": item.get("path"), "sha256": item.get("sha256")}
            == {
                "path": manifest_item.get("path"),
                "sha256": manifest_item.get("sha256"),
            },
            f"CY-063 artifact/manifest fingerprint drifted: {role}",
        )
    registry_identity = manifest.get("predecessor", {}).get("registry_identity", {})
    require(
        registry_identity
        == {
            "asset_value_sha256": value_sha256(predecessor_asset),
            "authorization_value_sha256": value_sha256(predecessor_auth),
        },
        "CY-062 predecessor registry identity drifted",
    )
    limitation_text = " ".join(str(x) for x in auth.get("known_limitations", []))
    require(
        auth.get("allowed_uses") == EXPECTED_AUTH_ALLOWED_USES
        and auth.get("blocked_uses") == EXPECTED_AUTH_BLOCKED_USES
        and all(token in limitation_text for token in ("PIT-B", "revision", "2025-2026")),
        "CY-063 authorization use/limitation contract drifted",
    )
    return {
        "asset": asset,
        "authorization": auth,
        "fingerprints": fingerprints,
        "predecessor_asset": predecessor_asset,
        "predecessor_authorization": predecessor_auth,
    }


def verify_correction(manifest: Mapping[str, Any]) -> dict[str, Any]:
    inventory = {item.get("role"): item for item in manifest.get("inventory", [])}
    fact = inventory.get(CORRECTION_ROLE)
    require(fact is not None, "CY-063 manifest does not bind R2 correction")
    path = Path(str(fact.get("path", "")))
    require(path.is_file() and sha256(path) == fact.get("sha256"), "R2 correction drifted")
    correction = correction_builder.validate_correction(Path(__file__).resolve())
    require(
        correction.get("failed_attempt", {}).get(
            "sealed_title_bearing_sources_mechanically_revalidated"
        )
        is True
        and correction.get("failed_attempt", {}).get(
            "candidate_title_projection_or_classification_before_key_freeze"
        )
        is False
        and correction.get("failed_attempt", {}).get("outcome_or_daily_parquet_content_rows_parsed")
        is False
        and correction.get("stage_b_contract", {}).get("expected_stage_a_sha256_required") is True
        and correction.get("stage_b_contract", {}).get("pre_outcome_attempt_seal_required") is True,
        "R2 correction boundary contract drifted",
    )
    return {
        "path": str(path),
        "sha256": sha256(path),
        "predecessor_runner": {
            "path": str(correction_builder.PREDECESSOR_RUNNER),
            "sha256": sha256(correction_builder.PREDECESSOR_RUNNER),
        },
        "corrected_runner": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256(Path(__file__).resolve()),
        },
    }


def verify_asset(asset_root: Path, parent_selected: Path) -> dict[str, Any]:
    require(asset_root.resolve() == correction_builder.EXPECTED_ROOT, "unexpected CY-063 root")
    registered = verify_registration(asset_root)
    try:
        wrapper_validation = correction_builder.validate(asset_root)
        source_validation = predecessor_builder.validate(PREDECESSOR_ROOT)
    except (
        correction_builder.CorrectionAssetError,
        predecessor_builder.AssetError,
    ) as exc:
        raise IndexCorrectionError(f"correction/source wrapper validation failed: {exc}") from exc
    manifest_path = asset_root / "asset_manifest.json"
    manifest = read_json(manifest_path, "CY-063 manifest")
    require(
        wrapper_validation.get("valid") is True
        and wrapper_validation.get("manifest_sha256") == sha256(manifest_path)
        and source_validation.get("valid") is True
        and source_validation.get("manifest_sha256")
        == correction_builder.EXPECTED_HASHES["predecessor_asset_manifest"],
        "CY-063/CY-062 reconstruction identity drifted",
    )
    require(
        manifest.get("parent_selected")
        == {"path": str(parent_selected), "sha256": sha256(parent_selected)},
        "CY-063 parent selected identity drifted",
    )
    correction = verify_correction(manifest)
    route = manifest.get("route_index", {})
    route_path = PREDECESSOR_ROOT / "announcement_route_index.parquet"
    require(
        route
        == {
            "path": str(route_path),
            "sha256": sha256(route_path),
            "rows": 149545,
        },
        "CY-063 inherited route identity drifted",
    )
    return {
        "asset_id": ASSET_ID,
        "wrapper_manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path)},
        "registered_asset_entry_sha256": value_sha256(registered["asset"]),
        "bounded_authorization_sha256": value_sha256(registered["authorization"]),
        "correction": correction,
        "predecessor_source_identity": {
            "asset_id": PREDECESSOR_ASSET_ID,
            "root": str(PREDECESSOR_ROOT),
            "manifest_sha256": source_validation["manifest_sha256"],
            "activation_audit_sha256": correction_builder.EXPECTED_HASHES[
                "predecessor_activation_audit"
            ],
            "registered_asset_entry_sha256": value_sha256(registered["predecessor_asset"]),
            "bounded_authorization_sha256": value_sha256(registered["predecessor_authorization"]),
            "route_index": route,
            "source_snapshot_ids": source_validation["source_snapshot_ids"],
            "source_counts": source_validation["source_counts"],
        },
        "bound_artifacts": {
            role: {
                "path": str(item["path"]),
                "sha256": str(item["sha256"]),
            }
            for role, item in sorted(registered["fingerprints"].items())
        },
    }


def _source_route() -> pd.DataFrame:
    return pd.read_parquet(PREDECESSOR_ROOT / "announcement_route_index.parquet")


def run_stage_a(asset_root: Path, parent_selected: Path, output_root: Path) -> dict[str, Any]:
    require(
        output_root.resolve() == EXPECTED_CORRECTED_OUTPUT_ROOT,
        "CY-063 Stage A requires the frozen corrected output root",
    )
    require(not output_root.exists(), f"refusing non-pristine CY-063 output: {output_root}")
    identity = verify_asset(asset_root, parent_selected)
    entries = pd.read_parquet(parent_selected)
    signal_dates = pd.to_datetime(entries.signal_date, errors="raise").dt.normalize()
    require(signal_dates.dt.year.isin(YEARS).all(), "parent signal year drifted")
    require(signal_dates.max() <= MATURE_SIGNAL_CUTOFF, "parent contains immature signal")
    timed = predecessor.derive_causal_available_at(_source_route())
    selected_routes, route_audit = corrected_select_window_routes(timed, entries)
    szse_coverage = read_json(
        PREDECESSOR_ROOT / "source_capture/source_manifest.json", "SZSE source manifest"
    )["coverage"]
    sse_coverage = read_json(
        PREDECESSOR_ROOT / "sse_full_history_capture/source_manifest.json",
        "SSE source manifest",
    )["coverage"]
    require(
        pd.Timestamp(szse_coverage["start"])
        <= pd.Timestamp(route_audit["minimum_window_start"]).tz_localize(None).normalize()
        and pd.Timestamp(szse_coverage["end"]) >= signal_dates.max(),
        "SZSE source does not cover every candidate window",
    )
    require(
        pd.Timestamp(sse_coverage["start"]) == pd.Timestamp("1990-12-19")
        and pd.Timestamp(sse_coverage["end"]) >= signal_dates.max(),
        "SSE source is not full-history through every candidate signal",
    )
    stage = output_root / "stage_a"
    route_path = stage / "title_route_selection.parquet"
    pretitle_path = stage / "pretitle_route_freeze.json"
    title_free = selected_routes[[*ROUTE_COLUMNS, "causal_available_at"]].reset_index(drop=True)
    write_parquet_exclusive(route_path, title_free)
    pretitle = {
        "stage": "CY063_TITLE_FREE_RANGEINDEX_KEYS_FROZEN_BEFORE_TITLE_PROJECTION",
        "correction_wrapper_identity": identity,
        "source_asset_identity": identity["predecessor_source_identity"],
        "parent_selected": {"path": str(parent_selected), "sha256": sha256(parent_selected)},
        "route_audit": route_audit,
        "route_columns": list(title_free.columns),
        "route_rows": len(title_free),
        "route_sha256": sha256(route_path),
        "index_contract": "RangeIndex materialized only as row order; index is not a data column",
        "correction_identity": identity["correction"],
        "sealed_title_bearing_sources_mechanically_revalidated_for_integrity": True,
        "candidate_title_projection_or_classification_before_key_freeze": False,
        "parent_outcome_and_daily_bytes_hashed_for_identity": True,
        "outcome_or_daily_parquet_content_rows_parsed": False,
    }
    write_json_exclusive(pretitle_path, pretitle)
    persisted = pd.read_parquet(route_path)
    require_frame_exact("CY-063 persisted pretitle route differs", persisted, title_free)
    require(
        isinstance(persisted.index, pd.RangeIndex)
        and persisted.index.start == 0
        and persisted.index.step == 1
        and read_json(pretitle_path, "CY-063 pretitle freeze") == pretitle,
        "CY-063 persisted RangeIndex freeze drifted",
    )
    for frozen_path in (route_path, pretitle_path):
        require(
            frozen_path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0,
            f"CY-063 pretitle artifact is writable before title projection: {frozen_path.name}",
        )
    with_titles = predecessor.attach_titles(PREDECESSOR_ROOT, persisted)
    classified = predecessor.classify_titles(with_titles)
    audit = predecessor.apply_cooldown(entries, classified)
    selected = audit.loc[audit.v29r2_issuer_fact_cooldown_gate].copy()
    rejected = audit.loc[~audit.v29r2_issuer_fact_cooldown_gate].copy()
    execution_contract = predecessor.verify_execution_contract(selected)
    write_parquet_exclusive(stage / "classified_events.parquet", classified)
    write_parquet_exclusive(stage / "selector_audit.parquet", audit)
    write_parquet_exclusive(stage / "selected_entries.parquet", selected)
    write_parquet_exclusive(stage / "rejected_entries.parquet", rejected)
    freeze = {
        "stage": "CY063_V29R2_FIXED_RULE_COHORT_FROZEN_BEFORE_OUTCOME_ACCESS",
        "correction_wrapper_identity": identity,
        "source_asset_identity": identity["predecessor_source_identity"],
        "correction_identity": identity["correction"],
        "software_identity": {
            "corrected_runner": identity["correction"]["corrected_runner"],
            "predecessor_runner": identity["correction"]["predecessor_runner"],
        },
        "parent_selected": {"path": str(parent_selected), "sha256": sha256(parent_selected)},
        "pretitle_route_freeze": {"path": str(pretitle_path), "sha256": sha256(pretitle_path)},
        "route_audit": route_audit,
        "parent_signals": len(entries),
        "selected_signals": len(selected),
        "rejected_signals": len(rejected),
        "selected_by_signal_year": {
            str(year): int(pd.to_datetime(selected.signal_date).dt.year.eq(year).sum())
            for year in YEARS
        },
        "classified_open_by_family": {
            str(key): int(value)
            for key, value in classified.loc[
                classified.action.eq(predecessor.classifier.ACTION_OPEN), "risk_family"
            ]
            .value_counts()
            .sort_index()
            .items()
        },
        "execution_contract": execution_contract,
        "hashes": {
            "classified_events": sha256(stage / "classified_events.parquet"),
            "title_route_selection": sha256(route_path),
            "selector_audit": sha256(stage / "selector_audit.parquet"),
            "selected_entries": sha256(stage / "selected_entries.parquet"),
            "rejected_entries": sha256(stage / "rejected_entries.parquet"),
        },
        "parent_outcome_and_daily_bytes_hashed_for_identity": True,
        "outcome_or_daily_parquet_content_rows_parsed": False,
        "rule_changed": False,
        "index_normalization_only": True,
        "v29r1_later_period_status": "BLOCKED_BY_IMMUTABLE_SEMANTIC_INVALIDITY",
    }
    write_json_exclusive(stage / "freeze.json", freeze)
    return freeze


def verify_stage_a(asset_root: Path, parent_selected: Path, output_root: Path) -> dict[str, Any]:
    require(
        output_root.resolve() == EXPECTED_CORRECTED_OUTPUT_ROOT,
        "CY-063 Stage-A verification requires the frozen corrected output root",
    )
    identity = verify_asset(asset_root, parent_selected)
    stage = output_root / "stage_a"
    require(
        stage.is_dir()
        and not stage.is_symlink()
        and {item.name for item in stage.iterdir()}
        == {
            "classified_events.parquet",
            "title_route_selection.parquet",
            "selector_audit.parquet",
            "selected_entries.parquet",
            "rejected_entries.parquet",
            "pretitle_route_freeze.json",
            "freeze.json",
        },
        "CY-063 Stage-A exact inventory drifted",
    )
    freeze_path = stage / "freeze.json"
    freeze = read_json(freeze_path, "CY-063 Stage-A freeze")
    require(
        freeze.get("stage") == "CY063_V29R2_FIXED_RULE_COHORT_FROZEN_BEFORE_OUTCOME_ACCESS"
        and freeze.get("correction_wrapper_identity") == identity
        and freeze.get("source_asset_identity") == identity["predecessor_source_identity"]
        and freeze.get("correction_identity") == identity["correction"]
        and freeze.get("parent_outcome_and_daily_bytes_hashed_for_identity") is True
        and freeze.get("outcome_or_daily_parquet_content_rows_parsed") is False
        and freeze.get("rule_changed") is False
        and freeze.get("index_normalization_only") is True,
        "CY-063 Stage-A provenance/status drifted",
    )
    require(
        freeze.get("parent_selected")
        == {"path": str(parent_selected), "sha256": sha256(parent_selected)},
        "CY-063 Stage-A parent identity drifted",
    )
    paths = {
        "classified_events": stage / "classified_events.parquet",
        "title_route_selection": stage / "title_route_selection.parquet",
        "selector_audit": stage / "selector_audit.parquet",
        "selected_entries": stage / "selected_entries.parquet",
        "rejected_entries": stage / "rejected_entries.parquet",
    }
    for role, path in paths.items():
        require(
            path.is_file()
            and not path.is_symlink()
            and freeze.get("hashes", {}).get(role) == sha256(path)
            and path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0,
            f"CY-063 Stage-A artifact drifted/writable: {role}",
        )
    classified = pd.read_parquet(paths["classified_events"])
    title_routes = pd.read_parquet(paths["title_route_selection"])
    audit = pd.read_parquet(paths["selector_audit"])
    selected = pd.read_parquet(paths["selected_entries"])
    rejected = pd.read_parquet(paths["rejected_entries"])
    parent = pd.read_parquet(parent_selected)
    parent_ids = set(parent.gap_id.astype(str))
    selected_ids = set(selected.gap_id.astype(str))
    rejected_ids = set(rejected.gap_id.astype(str))
    require(
        len(audit) == len(parent) == freeze.get("parent_signals")
        and set(audit.gap_id.astype(str)) == parent_ids
        and not selected_ids.intersection(rejected_ids)
        and selected_ids.union(rejected_ids) == parent_ids
        and selected.v29r2_issuer_fact_cooldown_gate.eq(True).all()
        and rejected.v29r2_issuer_fact_cooldown_gate.eq(False).all(),
        "CY-063 selected/rejected partition drifted",
    )
    require(
        len(selected) == freeze.get("selected_signals")
        and len(rejected) == freeze.get("rejected_signals")
        and freeze.get("selected_by_signal_year")
        == {
            str(year): int(pd.to_datetime(selected.signal_date).dt.year.eq(year).sum())
            for year in YEARS
        },
        "CY-063 selector counts drifted",
    )
    pretitle_path = stage / "pretitle_route_freeze.json"
    pretitle = read_json(pretitle_path, "CY-063 pretitle freeze")
    require(
        freeze.get("pretitle_route_freeze")
        == {"path": str(pretitle_path), "sha256": sha256(pretitle_path)}
        and pretitle.get("stage")
        == "CY063_TITLE_FREE_RANGEINDEX_KEYS_FROZEN_BEFORE_TITLE_PROJECTION"
        and pretitle.get("correction_wrapper_identity") == identity
        and pretitle.get("source_asset_identity") == identity["predecessor_source_identity"]
        and pretitle.get("route_sha256") == sha256(paths["title_route_selection"])
        and pretitle.get("route_rows") == len(title_routes)
        and pretitle.get("route_columns") == list(title_routes.columns)
        and pretitle.get("sealed_title_bearing_sources_mechanically_revalidated_for_integrity")
        is True
        and pretitle.get("candidate_title_projection_or_classification_before_key_freeze") is False
        and pretitle.get("parent_outcome_and_daily_bytes_hashed_for_identity") is True
        and pretitle.get("outcome_or_daily_parquet_content_rows_parsed") is False
        and list(title_routes.columns) == [*ROUTE_COLUMNS, "causal_available_at"]
        and isinstance(title_routes.index, pd.RangeIndex),
        "CY-063 pretitle route freeze drifted",
    )
    current_timed = predecessor.derive_causal_available_at(_source_route())
    current_selection, current_audit = corrected_select_window_routes(current_timed, parent)
    current_title_free = current_selection[[*ROUTE_COLUMNS, "causal_available_at"]].reset_index(
        drop=True
    )
    require_frame_exact(
        "CY-063 route selection no longer reproduces", title_routes, current_title_free
    )
    require(
        pretitle.get("route_audit") == current_audit and freeze.get("route_audit") == current_audit,
        "CY-063 route audit no longer reproduces",
    )
    require(
        set(classified.announcement_key.astype(str))
        == set(title_routes.announcement_key.astype(str)),
        "CY-063 classified announcement keys do not conserve the frozen route keys",
    )
    current_with_titles = predecessor.attach_titles(PREDECESSOR_ROOT, title_routes)
    current_classified = predecessor.classify_titles(current_with_titles)
    require_frame_exact(
        "CY-063 title classification no longer reproduces", classified, current_classified
    )
    current_selector_audit = predecessor.apply_cooldown(parent, current_classified)
    current_selected = current_selector_audit.loc[
        current_selector_audit.v29r2_issuer_fact_cooldown_gate
    ].reset_index(drop=True)
    current_rejected = current_selector_audit.loc[
        ~current_selector_audit.v29r2_issuer_fact_cooldown_gate
    ].reset_index(drop=True)
    for role, persisted_frame, current_frame in (
        ("selector_audit", audit, current_selector_audit.reset_index(drop=True)),
        ("selected_entries", selected, current_selected),
        ("rejected_entries", rejected, current_rejected),
    ):
        require_frame_exact(
            f"CY-063 frozen selector output no longer reproduces at {role}",
            persisted_frame,
            current_frame,
        )
    for frozen_json in (pretitle_path, freeze_path):
        require(
            frozen_json.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0,
            f"CY-063 freeze is writable: {frozen_json.name}",
        )
    require(
        classified.empty
        or pd.to_datetime(classified.available_at, errors="raise")
        .le(
            pd.Timestamp(MATURE_SIGNAL_CUTOFF, tz="Asia/Shanghai")
            + pd.Timedelta(hours=23, minutes=59, seconds=59)
        )
        .all(),
        "CY-063 classifications exceed mature signal boundary",
    )
    execution_contract = predecessor.verify_execution_contract(selected)
    require(
        freeze.get("execution_contract") == execution_contract,
        "CY-063 execution contract drifted",
    )
    return {
        "verified": True,
        "stage_a_freeze_sha256": sha256(freeze_path),
        "asset_identity": identity,
        "hashes": freeze["hashes"],
        "execution_contract": execution_contract,
    }


@contextmanager
def replay_context(
    selected_path: Path, outcomes_path: Path, daily_path: Path, lane_root: Path
) -> Iterator[None]:
    replay = predecessor.replay
    old_source = replay.source_paths
    old_selected = replay.selected_entries_path
    old_lane = replay.lane_root
    try:
        replay.source_paths = lambda _label: {
            "root": outcomes_path.parent,
            "outcomes": outcomes_path,
            "outcome_daily": daily_path,
        }
        replay.selected_entries_path = lambda _label: selected_path
        replay.lane_root = lambda _label: lane_root
        yield
    finally:
        replay.source_paths = old_source
        replay.selected_entries_path = old_selected
        replay.lane_root = old_lane


def run_stage_b(
    asset_root: Path,
    parent_selected: Path,
    parent_outcomes: Path,
    parent_daily: Path,
    output_root: Path,
    expected_stage_a_sha256: str,
) -> dict[str, Any]:
    require(
        output_root.resolve() == EXPECTED_CORRECTED_OUTPUT_ROOT,
        "CY-063 Stage B requires the frozen corrected output root",
    )
    attempt_path = output_root / "stage_b_pre_outcome_attempt_seal.json"
    require(
        not attempt_path.exists()
        and not (output_root / "stage_b").exists()
        and not (output_root / "result.json").exists(),
        "refusing repeated or non-pristine CY-063 Stage-B attempt",
    )
    verification = verify_stage_a(asset_root, parent_selected, output_root)
    require(
        len(expected_stage_a_sha256) == 64
        and verification["stage_a_freeze_sha256"] == expected_stage_a_sha256,
        "independently supplied expected Stage-A SHA does not match",
    )
    identity = verification["asset_identity"]
    for role, path in (
        ("parent_selected", parent_selected),
        ("parent_outcomes", parent_outcomes),
        ("parent_outcome_daily", parent_daily),
    ):
        fact = identity["bound_artifacts"][role]
        require(
            Path(fact["path"]).resolve() == path.resolve() and fact["sha256"] == sha256(path),
            f"CLI {role} differs from CY-063 authorization",
        )
    freeze_path = output_root / "stage_a/freeze.json"
    freeze = read_json(freeze_path, "CY-063 Stage-A freeze")
    selected_path = output_root / "stage_a/selected_entries.parquet"
    require(
        freeze.get("parent_outcome_and_daily_bytes_hashed_for_identity") is True
        and freeze.get("outcome_or_daily_parquet_content_rows_parsed") is False
        and freeze.get("hashes", {}).get("selected_entries") == sha256(selected_path),
        "CY-063 Stage-A outcome boundary/selected identity drifted",
    )
    attempt = {
        "stage": "CY063_STAGE_B_EXCLUSIVE_PRE_OUTCOME_ATTEMPT_SEAL",
        "created_at": datetime.now(UTC).isoformat(),
        "stage_a_freeze": {"path": str(freeze_path), "sha256": expected_stage_a_sha256},
        "correction_wrapper_identity": identity,
        "correction_identity": identity["correction"],
        "parent_sources": {
            "selected": {"path": str(parent_selected), "sha256": sha256(parent_selected)},
            "outcomes": {"path": str(parent_outcomes), "sha256": sha256(parent_outcomes)},
            "outcome_daily": {"path": str(parent_daily), "sha256": sha256(parent_daily)},
        },
        "all_preflight_checks_passed": True,
        "outcome_or_daily_parquet_content_rows_parsed": False,
        "single_attempt_only": True,
    }
    write_json_exclusive(attempt_path, attempt)
    require(
        read_json(attempt_path, "CY-063 pre-outcome attempt seal") == attempt
        and attempt_path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0,
        "CY-063 pre-outcome attempt seal did not freeze",
    )
    selected = pd.read_parquet(selected_path)
    outcomes = pd.read_parquet(parent_outcomes)
    join_audit = predecessor.verify_exact_selected_outcome_join(selected, outcomes)
    outcome_contract = predecessor.verify_outcome_contract(selected, outcomes)
    execution_contract = predecessor.verify_execution_contract(selected)
    source_hashes = {
        "parent_outcomes": sha256(parent_outcomes),
        "parent_outcome_daily": sha256(parent_daily),
    }
    lane_root = output_root / "stage_b/lane"
    with replay_context(selected_path, parent_outcomes, parent_daily, lane_root):
        lane = predecessor.replay.run_lane("ROLLFORWARD", YEARS)
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
    post = verify_stage_a(asset_root, parent_selected, output_root)
    require(
        post["stage_a_freeze_sha256"] == expected_stage_a_sha256
        and post["hashes"] == verification["hashes"],
        "CY-063 Stage-A bytes drifted during Stage B",
    )
    accepted_path = lane_root / "portfolio_accepted.parquet"
    accepted = pd.read_parquet(accepted_path)
    accepted_contract = predecessor.verify_accepted_contract(accepted)
    yearly = predecessor.detailed_yearly(selected, accepted)
    result = {
        "strategy": "V29R2-CY063-INDEX-CORRECTION",
        "status": "COMPLETE_PIT_B_FIXED_RULE_ROLLFORWARD_INDEX_CORRECTION",
        "scientific_periods": {
            "2022-2024": "DEPENDENT_FIXED_RULE_VALIDATION_NOT_PRISTINE_OOS",
            "2025-2026": "POST_SELECTION_TEMPORAL_DIAGNOSTIC",
        },
        "data_end": DATA_END.date().isoformat(),
        "fully_mature_signal_cutoff": MATURE_SIGNAL_CUTOFF.date().isoformat(),
        "evidence_grade": "PIT_B_CURRENT_OFFICIAL_ENUMERATION_REVISION_HISTORY_INCOMPLETE",
        "correction_wrapper_identity": identity,
        "source_asset_identity": identity["predecessor_source_identity"],
        "correction_identity": identity["correction"],
        "stage_a_verification": verification,
        "stage_a_freeze": {"path": str(freeze_path), "sha256": expected_stage_a_sha256},
        "pre_outcome_attempt_seal": {"path": str(attempt_path), "sha256": sha256(attempt_path)},
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
        "rule_changed": False,
        "index_normalization_only": True,
        "v29r1_later_period_status": "BLOCKED_BY_IMMUTABLE_SEMANTIC_INVALIDITY",
    }
    write_json_exclusive(output_root / "result.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage-a", "stage-b"))
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--parent-selected", type=Path, required=True)
    parser.add_argument("--parent-outcomes", type=Path)
    parser.add_argument("--parent-daily", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--expected-stage-a-sha256")
    args = parser.parse_args()
    if args.mode == "stage-a":
        require(
            args.expected_stage_a_sha256 is None,
            "Stage A does not accept an expected Stage-A SHA",
        )
        result = run_stage_a(
            args.asset_root.resolve(), args.parent_selected.resolve(), args.output_root.resolve()
        )
    else:
        require(
            args.parent_outcomes is not None
            and args.parent_daily is not None
            and args.expected_stage_a_sha256 is not None,
            "Stage B requires outcomes, daily and independently supplied Stage-A SHA",
        )
        result = run_stage_b(
            args.asset_root.resolve(),
            args.parent_selected.resolve(),
            args.parent_outcomes.resolve(),
            args.parent_daily.resolve(),
            args.output_root.resolve(),
            args.expected_stage_a_sha256,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
