#!/usr/bin/env python3
"""Render and index every frozen V30 development event for visual review.

This Stage-C runner is intentionally inert until a separate CY-037 authorization
and manifest bind this exact runner, the frozen visual protocol, the exact Stage-A
candidates, and the completed Stage-B artifacts.  It does not create outcomes or
select rules.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

EXPERIMENT = "ASHARE-LOW-POSITIVE-FEEDBACK-GOOD-NEWS-MOTHER-V30"
REPO = Path(__file__).resolve().parents[3]
FREEZE = REPO / (f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json")
REVIEW_SPEC = REPO / (
    f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_visual_review_spec.json"
)
STAGE_A_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_low_positive_feedback_good_news_mother_v30_stage_a.py"
)
STAGE_B_SPEC = REPO / (
    f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_stage_b_freeze.json"
)
STAGE_B_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_low_positive_feedback_good_news_mother_v30_stage_b.py"
)
STAGE_B_ASSET_MANIFEST = REPO / (
    "research/market_behavior_os_v2/experiments/ASHARE-V30-CY035_DATA_ASSET_MANIFEST.json"
)
CY034_ASSET_MANIFEST = REPO / (
    "research/market_behavior_os_v2/experiments/ASHARE-V30-CY034_DATA_ASSET_MANIFEST.json"
)
REGISTRY = REPO / "configs/data_asset_registry.json"
CHART_ASSET_MANIFEST = REPO / (
    "research/market_behavior_os_v2/experiments/ASHARE-V30-CY037_CHART_REVIEW_ASSET_MANIFEST.json"
)
CHART_ASSET_ID = "CY-037"
CHART_DEPENDENCY_ASSET_ID = "CY-035"
STAGE_B_AUTHORIZATION_ID = "CYQ-AUTH-ASHARE-TURNOVER-PFC-V30-STAGE-B-2013-2020-V1"
STAGE_B_AUTHORIZED_ARM = "V30_FROZEN_STAGE_B_OUTCOME_ATTACHMENT_ONLY"
CHART_AUTHORIZATION_ID = "CYQ-AUTH-ASHARE-TURNOVER-PFC-V30-STAGE-C-CY037-CHART-REVIEW-2013-2020-V1"
CHART_AUTHORIZED_ARM = "V30_CY037_FROZEN_STAGE_C_CHART_REVIEW_ONLY"
DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_low_positive_feedback_good_news_mother_v30"
)
STAGE_A_RESULT = OUTPUT_ROOT / "stage_a/result.json"
REPRESENTATION = OUTPUT_ROOT / "stage_a/representation_panel.parquet"
CANDIDATES = OUTPUT_ROOT / "stage_a/candidates_frozen.parquet"
STAGE_B_RESULT = OUTPUT_ROOT / "stage_b/result.json"
STAGE_B_PATHS = OUTPUT_ROOT / "stage_b/future_paths.parquet"
OUTCOMES = OUTPUT_ROOT / "stage_b/outcomes.parquet"
CHART_ROOT = OUTPUT_ROOT / "stage_c_charts"
WINDOW_PANEL = CHART_ROOT / "chart_window_panel.parquet"
REVIEW_LEDGER = CHART_ROOT / "review_ledger.parquet"
REVIEW_CSV = CHART_ROOT / "review_ledger.csv"
REVIEW_TEMPLATE = CHART_ROOT / "per_chart_review_template.csv"
CHART_DIR = CHART_ROOT / "individual_charts"
CHART_INDEX = CHART_ROOT / "chart_index.csv"
PLACEMENTS = CHART_ROOT / "contact_sheet_placements.csv"
SHEET_INDEX = CHART_ROOT / "contact_sheet_index.csv"
SHEET_DIR = CHART_ROOT / "contact_sheets"
OUTCOME_SHEET_ROOT = CHART_ROOT / "review_sheets_by_outcome"
MANIFEST = CHART_ROOT / "manifest.json"

EXPECTED_STATIC_HASHES = {
    "parent_spec": (
        FREEZE,
        "c0f8c1c0617099f2705a873608fae390dbb30dd929b38ce040bab649e5841b0d",
    ),
    "stage_a_runner": (
        STAGE_A_RUNNER,
        "e3c8bccdb21644e2cc7cd6bfa3cdfe7820684a8157311e7fead76c67c9b27c28",
    ),
}
EXPECTED_DAILY_SHA256 = "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00"
CONTEXT_START = pd.Timestamp("2013-01-04")
COHORT_SIGNAL_START = pd.Timestamp("2014-01-30")
MAX_SIGNAL_DATE = pd.Timestamp("2020-06-30")
MAX_CHART_DATE = pd.Timestamp("2020-12-31")
WINDOW_SESSIONS = 126
TARGET_RETURN = 0.10
HORIZON_SESSIONS = 20
ROUND_TRIP_COST = 0.004
CHART_SIZE = (720, 380)
GRID_COLUMNS = 5
GRID_ROWS = 5
EXPECTED_OUT_OF_WINDOW_COMPLETED_EXITS = 4
IN_WINDOW_EXIT_MARKER = "IN_WINDOW_PRICE_MARKER"
OUT_OF_WINDOW_EXIT_MARKER = "RIGHT_BOUNDARY_TEXT_NO_PRICE_POINT"
NO_COMPLETED_EXIT_MARKER = "NO_COMPLETED_EXIT"

CANDIDATE_COLUMNS = (
    "event_id",
    "signal_date",
    "signal_cal_idx",
    "symbol",
    "sleeve",
    "causal_industry",
    "decision_at",
    "available_at",
    "amount",
    "turnover_fraction",
    "mean_turnover_60",
    "ret20",
    "ret60",
    "step_return",
    "turnover_pfc_score",
    "pfc_r1",
    "pfc_r5",
    "turnover_pfc_r22",
    "invalid_step_cum",
    "coord_open",
    "coord_high",
    "coord_low",
    "coord_close",
)
OUTCOME_COLUMNS = (
    "event_id",
    "symbol",
    "sleeve",
    "causal_industry",
    "signal_date",
    "signal_cal_idx",
    "signal_invalid_step_cum",
    "target_return",
    "horizon_sessions",
    "round_trip_cost",
    "status",
    "lineage_invalid_date",
    "lineage_invalid_cal_idx",
    "data_invalid_date",
    "data_invalid_cal_idx",
    "data_invalid_reason",
    "entry_date",
    "entry_cal_idx",
    "entry_price",
    "target_price",
    "exit_date",
    "exit_cal_idx",
    "exit_price",
    "exit_reason",
    "exit_execution_phase",
    "exit_coord_open",
    "exit_coord_high",
    "exit_raw_open",
    "exit_raw_high",
    "exit_raw_down_limit_price",
    "holding_sessions",
    "gross_return",
    "net_return",
)
ALLOWED_STATUSES = {
    "COMPLETED",
    "NO_LEGAL_ENTRY",
    "INVALID_COORDINATE_LINEAGE_BEFORE_ENTRY",
    "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
    "INVALID_CORPORATE_ACTION_STATE_BEFORE_ENTRY",
    "INVALID_CORPORATE_ACTION_STATE_AFTER_ENTRY",
    "INCOMPLETE_PATH",
}
OUTCOME_BUCKETS = (
    "SEVERE_LOSS",
    "LOSS_0_TO_10PCT",
    "PROFIT_0_TO_4PCT",
    "PROFIT_GE_4PCT",
    "NO_COMPLETED_TRADE",
)


class ResearchError(RuntimeError):
    """Fail closed on missing schema, identity, chronology, or coverage."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ResearchError(f"missing required frozen input: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ResearchError(f"expected JSON object: {path}")
    return value


def _require_columns(path: Path, required: tuple[str, ...], *, exact: bool = False) -> None:
    if not path.is_file():
        raise ResearchError(f"missing required frozen input: {path}")
    con = duckdb.connect()
    try:
        names = {
            str(row[0])
            for row in con.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{path.as_posix()}')"
            ).fetchall()
        }
    finally:
        con.close()
    missing = sorted(set(required) - names)
    if missing:
        raise ResearchError(f"{path}: missing exact frozen V30 columns: {missing}")
    extra = sorted(names - set(required))
    if exact and extra:
        raise ResearchError(f"{path}: unexpected frozen V30 columns: {extra}")


def _only(items: list[dict[str, Any]], label: str) -> dict[str, Any]:
    if len(items) != 1:
        raise ResearchError(f"expected exactly one {label}, found {len(items)}")
    return items[0]


def _role_map(items: Any, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ResearchError(f"{label} must be a list of objects")
    mapped: dict[str, dict[str, Any]] = {}
    for item in items:
        role = item.get("role")
        if not isinstance(role, str) or not role or role in mapped:
            raise ResearchError(f"{label} has a missing or duplicate role: {role!r}")
        mapped[role] = item
    return mapped


def _require_bound_item(
    mapped: dict[str, dict[str, Any]],
    role: str,
    path: Path,
    digest: str,
    label: str,
) -> None:
    item = mapped.get(role)
    if item is None:
        raise ResearchError(f"{label} does not bind required role {role}")
    if item.get("path") != str(path.resolve()) or item.get("sha256") != digest:
        raise ResearchError(f"{label} identity drift for role {role}")


def _require_bound_hash(payload: dict[str, Any], key: str, actual: str) -> None:
    source_hashes = payload.get("source_hashes")
    if not isinstance(source_hashes, dict) or source_hashes.get(key) != actual:
        raise ResearchError(f"Stage-B result does not bind short-key input: {key}")


def _chart_artifact_requirements() -> tuple[tuple[str, Path, str], ...]:
    return (
        ("daily_compact", DAILY, "daily"),
        ("stage_a_candidates", CANDIDATES, "candidates"),
        ("stage_b_spec", STAGE_B_SPEC, "stage_b_spec"),
        ("stage_b_runner", STAGE_B_RUNNER, "stage_b_runner"),
        ("stage_b_result", STAGE_B_RESULT, "stage_b_result"),
        ("stage_b_future_paths", STAGE_B_PATHS, "stage_b_future_paths"),
        ("stage_b_outcomes", OUTCOMES, "stage_b_outcomes"),
    )


def _preflight_declared_chart_artifacts(
    authorization: dict[str, Any], manifest: dict[str, Any]
) -> None:
    hexadecimal = set("0123456789abcdef")
    for label, items in (
        ("CY-037 authorization", authorization.get("bound_artifacts")),
        ("CY-037 manifest", manifest.get("bound_artifacts")),
    ):
        mapped = _role_map(items, f"{label} bound_artifacts")
        for role, path, _digest_key in _chart_artifact_requirements():
            item = mapped.get(role)
            digest = None if item is None else item.get("sha256")
            if (
                item is None
                or item.get("path") != str(path.resolve())
                or not isinstance(digest, str)
                or len(digest) != 64
                or not set(digest).issubset(hexadecimal)
            ):
                raise ResearchError(f"{label} has no valid declared binding for {role}")


def _load_chart_authorization(
    actual: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fail before any completed Stage-B artifact is opened unless CY-037 exists."""
    missing = [str(path) for path in (REGISTRY, CHART_ASSET_MANIFEST) if not path.is_file()]
    if missing:
        raise ResearchError(
            "CY-037 chart authorization is not installed; missing registry/manifest "
            f"input: {missing}"
        )
    actual["registry"] = sha256(REGISTRY)
    actual["chart_asset_manifest"] = sha256(CHART_ASSET_MANIFEST)
    registry = _load_json(REGISTRY)
    assets = registry.get("assets")
    authorizations = registry.get("bounded_authorizations")
    if not isinstance(assets, list) or not isinstance(authorizations, list):
        raise ResearchError("data registry has no asset/authorization lists")
    asset = _only(
        [item for item in assets if item.get("asset_id") == CHART_ASSET_ID],
        f"registry asset {CHART_ASSET_ID}",
    )
    dependency = _only(
        [item for item in assets if item.get("asset_id") == CHART_DEPENDENCY_ASSET_ID],
        f"registry asset {CHART_DEPENDENCY_ASSET_ID}",
    )
    authorization = _only(
        [item for item in authorizations if item.get("authorization_id") == CHART_AUTHORIZATION_ID],
        f"registry authorization {CHART_AUTHORIZATION_ID}",
    )

    lineage = asset.get("lineage", {})
    if (
        asset.get("status") != "RESEARCH_CONDITIONAL"
        or lineage.get("immutable_manifest") is not True
        or lineage.get("manifest_path") != str(CHART_ASSET_MANIFEST.resolve())
        or lineage.get("manifest_sha256") != actual["chart_asset_manifest"]
        or lineage.get("bounded_authorization_id") != CHART_AUTHORIZATION_ID
    ):
        raise ResearchError("CY-037 registry asset semantics drift")

    scope = authorization.get("scope", {})
    bound_manifest = authorization.get("bound_manifest", {})
    bound_strategy = authorization.get("bound_strategy", {})
    bound_protocol = authorization.get("bound_protocol", {})
    if (
        authorization.get("purpose") != "ASHARE_FROZEN_DEVELOPMENT_CHART_REVIEW"
        or authorization.get("asset_id") != CHART_ASSET_ID
        or authorization.get("dependency_asset_id") != CHART_DEPENDENCY_ASSET_ID
        or authorization.get("dependency_status") != dependency.get("status")
        or dependency.get("status") != "RESEARCH_CONDITIONAL"
        or scope.get("project") != "research/market_behavior_os_v2"
        or scope.get("start") != str(CONTEXT_START.date())
        or scope.get("end") != str(MAX_CHART_DATE.date())
        or scope.get("signal_start") != str(COHORT_SIGNAL_START.date())
        or scope.get("signal_end") != str(MAX_SIGNAL_DATE.date())
        or scope.get("maximum_physical_row_date") != str(MAX_CHART_DATE.date())
        or authorization.get("authorized_arms") != [CHART_AUTHORIZED_ARM]
        or authorization.get("completed_stage_b_artifact_read_authorized") is not True
        or authorization.get("charts_authorized") is not True
        or authorization.get("outcome_attachment_authorized") is not False
        or authorization.get("portfolio_replay_authorized") is not False
        or authorization.get("post_2020_read_authorized") is not False
        or authorization.get("2021_read_authorized") is not False
        or authorization.get("2022_plus_read_authorized") is not False
        or authorization.get("current_survivor_fallback_allowed") is not False
        or bound_manifest.get("path") != str(CHART_ASSET_MANIFEST.resolve())
        or bound_manifest.get("sha256") != actual["chart_asset_manifest"]
        or bound_strategy.get("path") != str(FREEZE.resolve())
        or bound_strategy.get("sha256") != actual["parent_spec"]
        or bound_protocol.get("path") != str(REVIEW_SPEC.resolve())
        or bound_protocol.get("sha256") != actual["review_spec"]
        or bound_protocol.get("runner_path") != str(Path(__file__).resolve())
        or bound_protocol.get("runner_sha256") != actual["chart_runner"]
    ):
        raise ResearchError("CY-037 bounded authorization semantics drift")

    manifest = _load_json(CHART_ASSET_MANIFEST)
    upstream = manifest.get("upstream_bounded_asset", {})
    boundary = manifest.get("authorization_boundary", {})
    upstream_registry_sha = upstream.get("stage_b_registry_sha256")
    if (
        manifest.get("asset_id") != CHART_ASSET_ID
        or manifest.get("status") != "FROZEN_DEVELOPMENT_CHART_REVIEW_BOUNDED_INPUT"
        or upstream.get("asset_id") != CHART_DEPENDENCY_ASSET_ID
        or upstream.get("authorization_id") != STAGE_B_AUTHORIZATION_ID
        or not isinstance(upstream_registry_sha, str)
        or len(upstream_registry_sha) != 64
        or not set(upstream_registry_sha).issubset(set("0123456789abcdef"))
        or boundary.get("authorization_id") != CHART_AUTHORIZATION_ID
        or boundary.get("purpose") != "ASHARE_FROZEN_DEVELOPMENT_CHART_REVIEW"
        or boundary.get("authorized_arm") != CHART_AUTHORIZED_ARM
        or boundary.get("candidate_signal_start") != str(COHORT_SIGNAL_START.date())
        or boundary.get("candidate_signal_end") != str(MAX_SIGNAL_DATE.date())
        or boundary.get("maximum_chart_date") != str(MAX_CHART_DATE.date())
        or boundary.get("completed_stage_b_artifact_read_authorized") is not True
        or boundary.get("charts_authorized") is not True
        or boundary.get("outcome_attachment_authorized") is not False
        or boundary.get("portfolio_replay_authorized") is not False
        or boundary.get("2021_read_authorized") is not False
        or boundary.get("2022_plus_read_authorized") is not False
    ):
        raise ResearchError("CY-037 chart manifest semantics drift")
    _preflight_declared_chart_artifacts(authorization, manifest)
    return authorization, manifest


def _verify_chart_artifact_bindings(
    authorization: dict[str, Any], manifest: dict[str, Any], actual: dict[str, str]
) -> None:
    for label, items in (
        ("CY-037 authorization", authorization.get("bound_artifacts")),
        ("CY-037 manifest", manifest.get("bound_artifacts")),
    ):
        mapped = _role_map(items, f"{label} bound_artifacts")
        for role, path, digest_key in _chart_artifact_requirements():
            _require_bound_item(mapped, role, path, actual[digest_key], label)


def _rehash_all_bound_inputs(expected: dict[str, str]) -> None:
    paths = {
        "parent_spec": FREEZE,
        "stage_a_runner": STAGE_A_RUNNER,
        "review_spec": REVIEW_SPEC,
        "chart_runner": Path(__file__),
        "registry": REGISTRY,
        "chart_asset_manifest": CHART_ASSET_MANIFEST,
        "daily": DAILY,
        "stage_b_spec": STAGE_B_SPEC,
        "stage_b_runner": STAGE_B_RUNNER,
        "stage_b_asset_manifest": STAGE_B_ASSET_MANIFEST,
        "cy034_manifest": CY034_ASSET_MANIFEST,
        "stage_a_result": STAGE_A_RESULT,
        "representation": REPRESENTATION,
        "candidates": CANDIDATES,
        "stage_b_result": STAGE_B_RESULT,
        "stage_b_future_paths": STAGE_B_PATHS,
        "stage_b_outcomes": OUTCOMES,
    }
    if set(paths) != set(expected):
        raise ResearchError("bound-input rehash inventory drift")
    found = {key: sha256(path) for key, path in paths.items()}
    if found != expected:
        raise ResearchError("a bound input changed before atomic chart publication")


def verify_inputs() -> tuple[dict[str, str], dict[str, Any]]:
    actual: dict[str, str] = {}
    for key, (path, expected) in EXPECTED_STATIC_HASHES.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input: {path}")
        found = sha256(path)
        if found != expected:
            raise ResearchError(f"input identity drift: {path}: {found} != {expected}")
        actual[key] = found

    review_spec = _load_json(REVIEW_SPEC)
    renderer = review_spec.get("renderer", {})
    if (
        review_spec.get("experiment") != EXPERIMENT
        or review_spec.get("outcome_blind_authorship") is not True
        or review_spec.get("maximum_compressed_rules") != 5
        or renderer.get("path") != str(Path(__file__).relative_to(REPO))
        or renderer.get("sha256") != sha256(Path(__file__))
    ):
        raise ResearchError("visual-review spec does not bind this frozen renderer")
    actual["review_spec"] = sha256(REVIEW_SPEC)
    actual["chart_runner"] = sha256(Path(__file__))

    authorization, chart_manifest = _load_chart_authorization(actual)

    if not DAILY.is_file():
        raise ResearchError(f"missing frozen daily input: {DAILY}")
    actual["daily"] = sha256(DAILY)
    if actual["daily"] != EXPECTED_DAILY_SHA256:
        raise ResearchError(f"daily identity drift: {actual['daily']} != {EXPECTED_DAILY_SHA256}")

    completed_inputs = (
        STAGE_B_SPEC,
        STAGE_B_RUNNER,
        STAGE_B_ASSET_MANIFEST,
        CY034_ASSET_MANIFEST,
        STAGE_A_RESULT,
        REPRESENTATION,
        CANDIDATES,
        STAGE_B_RESULT,
        STAGE_B_PATHS,
        OUTCOMES,
    )
    missing = [str(path) for path in completed_inputs if not path.is_file()]
    if missing:
        raise ResearchError(f"missing frozen Stage-A/B input: {missing}")
    actual.update(
        {
            "stage_b_spec": sha256(STAGE_B_SPEC),
            "stage_b_runner": sha256(STAGE_B_RUNNER),
            "stage_b_asset_manifest": sha256(STAGE_B_ASSET_MANIFEST),
            "cy034_manifest": sha256(CY034_ASSET_MANIFEST),
            "stage_a_result": sha256(STAGE_A_RESULT),
            "representation": sha256(REPRESENTATION),
            "candidates": sha256(CANDIDATES),
            "stage_b_result": sha256(STAGE_B_RESULT),
            "stage_b_future_paths": sha256(STAGE_B_PATHS),
            "stage_b_outcomes": sha256(OUTCOMES),
        }
    )
    _verify_chart_artifact_bindings(authorization, chart_manifest, actual)

    stage_a = _load_json(STAGE_A_RESULT)
    if (
        stage_a.get("experiment") != EXPERIMENT
        or stage_a.get("stage") != "OUTCOME_BLIND_REPRESENTATION_AND_CANDIDATE_FREEZE"
        or stage_a.get("stage_a_gate_passed") is not True
        or stage_a.get("outcomes_read") is not False
        or stage_a.get("post_signal_end_row_read") is not False
        or stage_a.get("post_2020_row_read") is not False
    ):
        raise ResearchError("Stage A did not authorize a later outcome attachment")
    candidate_hash = actual["candidates"]
    if stage_a.get("candidate_sha256") != candidate_hash:
        raise ResearchError("Stage-A candidate hash drift")
    if stage_a.get("representation_sha256") != actual["representation"]:
        raise ResearchError("Stage-A representation hash drift")
    stage_a_hashes = stage_a.get("source_hashes")
    if (
        not isinstance(stage_a_hashes, dict)
        or stage_a_hashes.get("spec") != actual["parent_spec"]
        or stage_a_hashes.get("runner") != actual["stage_a_runner"]
        or stage_a_hashes.get("daily") != actual["daily"]
    ):
        raise ResearchError("Stage-A short-key source identity drift")

    stage_b = _load_json(STAGE_B_RESULT)
    if (
        stage_b.get("experiment") != EXPERIMENT
        or stage_b.get("stage") != "SEPARATELY_AUTHORIZED_FROZEN_DEVELOPMENT_OUTCOME_ATTACHMENT"
        or stage_b.get("asset_id") != CHART_DEPENDENCY_ASSET_ID
        or stage_b.get("authorization_id") != STAGE_B_AUTHORIZATION_ID
        or stage_b.get("authorized_arm") != STAGE_B_AUTHORIZED_ARM
        or stage_b.get("post_2020_row_read") is not False
        or stage_b.get("maximum_evaluation_path_date") != "2020-12-31"
        or stage_b.get("target_return") != TARGET_RETURN
        or stage_b.get("round_trip_cost") != ROUND_TRIP_COST
        or stage_b.get("fallback_eligible_open_precedes_same_day_high") is not True
        or stage_b.get("intraday_target_limit_evidence_required") is not True
        or stage_b.get("unknown_corporate_action_state_invalidates_event") is not True
        or stage_b.get("all_bound_inputs_rehashed_immediately_before_publish") is not True
        or stage_b.get("canonical_stage_b_preexisted") is not False
        or stage_b.get("preexisting_v30_outcome_artifact_read") is not False
        or stage_b.get("portfolio_replay_performed") is not False
        or stage_b.get("charts_rendered") is not False
    ):
        raise ResearchError("Stage-B result violates the frozen V30 contract")
    outcome_hash = actual["stage_b_outcomes"]
    if stage_b.get("outcomes_sha256") != outcome_hash:
        raise ResearchError("Stage-B outcome hash drift")
    if stage_b.get("future_paths_sha256") != actual["stage_b_future_paths"]:
        raise ResearchError("Stage-B future-path hash drift")
    for key in (
        "parent_spec",
        "stage_b_spec",
        "stage_a_runner",
        "stage_b_runner",
        "stage_b_asset_manifest",
        "cy034_manifest",
        "daily",
        "stage_a_result",
        "representation",
        "candidates",
    ):
        source_key = "asset_manifest" if key == "stage_b_asset_manifest" else key
        _require_bound_hash(stage_b, source_key, actual[key])
    _require_bound_hash(
        stage_b,
        "registry",
        chart_manifest["upstream_bounded_asset"]["stage_b_registry_sha256"],
    )

    _require_columns(CANDIDATES, CANDIDATE_COLUMNS)
    _require_columns(OUTCOMES, OUTCOME_COLUMNS, exact=True)
    return actual, review_spec


def outcome_bucket(status: str, net_return: float) -> str:
    if status != "COMPLETED" or not math.isfinite(net_return):
        return "NO_COMPLETED_TRADE"
    if net_return >= 0.04:
        return "PROFIT_GE_4PCT"
    if net_return >= 0:
        return "PROFIT_0_TO_4PCT"
    if net_return > -0.10:
        return "LOSS_0_TO_10PCT"
    return "SEVERE_LOSS"


def audit_exit_marker_contract(outcomes: pd.DataFrame) -> None:
    completed_mask = outcomes.status.eq("COMPLETED")
    exit_relative = pd.to_numeric(outcomes.exit_cal_idx, errors="coerce") - pd.to_numeric(
        outcomes.signal_cal_idx, errors="coerce"
    )
    if (
        exit_relative.loc[completed_mask].isna().any()
        or exit_relative.loc[completed_mask].le(0).any()
    ):
        raise ResearchError("completed exit has a missing or nonpositive relative session")
    outcomes["exit_relative_session"] = exit_relative
    outcomes["exit_marker_mode"] = NO_COMPLETED_EXIT_MARKER
    outcomes.loc[completed_mask & exit_relative.le(WINDOW_SESSIONS), "exit_marker_mode"] = (
        IN_WINDOW_EXIT_MARKER
    )
    outside_mask = completed_mask & exit_relative.gt(WINDOW_SESSIONS)
    outcomes.loc[outside_mask, "exit_marker_mode"] = OUT_OF_WINDOW_EXIT_MARKER
    outside = outcomes.loc[outside_mask, ["event_id", "symbol", "exit_date", "exit_cal_idx"]].copy()
    if len(outside) != EXPECTED_OUT_OF_WINDOW_COMPLETED_EXITS:
        raise ResearchError(
            "out-of-window completed-exit count drift: "
            f"{len(outside)} != {EXPECTED_OUT_OF_WINDOW_COMPLETED_EXITS}"
        )

    con = duckdb.connect()
    con.register("outside_exit_keys", outside)
    rows = con.execute(
        f"""
        SELECT k.event_id,k.symbol,k.exit_date,k.exit_cal_idx,
          d.symbol AS daily_symbol,d.trade_date AS daily_trade_date,
          d.cal_idx AS daily_cal_idx,d.current_valid,d.hard_valid,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,
          d.available_at,d.decision_at
        FROM outside_exit_keys k LEFT JOIN (
          SELECT * FROM read_parquet('{DAILY.as_posix()}')
          WHERE trade_date BETWEEN DATE '2013-01-04' AND DATE '2020-12-31'
        ) d ON d.symbol=k.symbol AND d.cal_idx=k.exit_cal_idx
        ORDER BY k.event_id
        """
    ).fetch_df()
    con.close()
    for column in ("exit_date", "daily_trade_date", "available_at", "decision_at"):
        rows[column] = pd.to_datetime(rows[column])
    numeric = rows[["coord_open", "coord_high", "coord_low", "coord_close"]].apply(
        pd.to_numeric, errors="coerce"
    )
    if (
        len(rows) != len(outside)
        or rows.event_id.duplicated().any()
        or rows.daily_symbol.isna().any()
        or not rows.symbol.eq(rows.daily_symbol).all()
        or not rows.exit_date.eq(rows.daily_trade_date).all()
        or not rows.exit_cal_idx.eq(rows.daily_cal_idx).all()
        or not rows.current_valid.fillna(False).all()
        or not rows.hard_valid.fillna(False).all()
        or not np.isfinite(numeric).all(axis=1).all()
        or not numeric.gt(0).all(axis=1).all()
        or rows.available_at.isna().any()
        or rows.decision_at.isna().any()
        or rows.available_at.gt(rows.decision_at).any()
    ):
        raise ResearchError("out-of-window exit daily identity/validity audit failed")


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    candidates = pd.read_parquet(CANDIDATES, columns=list(CANDIDATE_COLUMNS))
    outcomes = pd.read_parquet(OUTCOMES, columns=list(OUTCOME_COLUMNS))
    for column in ("signal_date", "decision_at", "available_at"):
        candidates[column] = pd.to_datetime(candidates[column])
    for column in (
        "signal_date",
        "lineage_invalid_date",
        "data_invalid_date",
        "entry_date",
        "exit_date",
    ):
        outcomes[column] = pd.to_datetime(outcomes[column])

    if (
        candidates.empty
        or candidates.event_id.isna().any()
        or candidates.event_id.duplicated().any()
    ):
        raise ResearchError("Stage-A candidate identity is empty, null, or duplicated")
    if outcomes.event_id.isna().any() or outcomes.event_id.duplicated().any():
        raise ResearchError("Stage-B outcome identity is null or duplicated")
    candidate_ids = set(candidates.event_id.astype(str))
    outcome_ids = set(outcomes.event_id.astype(str))
    if candidate_ids != outcome_ids or len(candidates) != len(outcomes):
        raise ResearchError("candidate/outcome event_id sets are not exactly one-to-one")
    if candidates.signal_date.max() > MAX_SIGNAL_DATE:
        raise ResearchError("candidate signal crossed the frozen development boundary")
    if candidates.available_at.gt(candidates.decision_at).any():
        raise ResearchError("candidate information arrived after signal decision_at")
    if not set(outcomes.status.astype(str)).issubset(ALLOWED_STATUSES):
        raise ResearchError("unknown Stage-B lifecycle status")
    if not np.isclose(pd.to_numeric(outcomes.target_return, errors="coerce"), TARGET_RETURN).all():
        raise ResearchError("Stage-B target differs from frozen +10 percent")
    if not pd.to_numeric(outcomes.horizon_sessions, errors="coerce").eq(HORIZON_SESSIONS).all():
        raise ResearchError("Stage-B horizon differs from frozen 20 sessions")
    if not np.isclose(
        pd.to_numeric(outcomes.round_trip_cost, errors="coerce"), ROUND_TRIP_COST
    ).all():
        raise ResearchError("Stage-B round-trip cost differs from frozen 40 bps")

    identity = candidates[
        ["event_id", "symbol", "sleeve", "causal_industry", "signal_date", "signal_cal_idx"]
    ].merge(
        outcomes[
            ["event_id", "symbol", "sleeve", "causal_industry", "signal_date", "signal_cal_idx"]
        ],
        on="event_id",
        suffixes=("_candidate", "_outcome"),
        validate="one_to_one",
    )
    for column in ("symbol", "sleeve", "causal_industry", "signal_date", "signal_cal_idx"):
        if not identity[f"{column}_candidate"].eq(identity[f"{column}_outcome"]).all():
            raise ResearchError(f"candidate/outcome identity mismatch: {column}")
    lineage = candidates[["event_id", "invalid_step_cum"]].merge(
        outcomes[["event_id", "signal_invalid_step_cum"]],
        on="event_id",
        validate="one_to_one",
    )
    if not lineage.invalid_step_cum.eq(lineage.signal_invalid_step_cum).all():
        raise ResearchError("candidate/outcome signal coordinate-lineage mismatch")

    completed = outcomes.loc[outcomes.status.eq("COMPLETED")].copy()
    entered = outcomes.loc[outcomes.entry_cal_idx.notna()].copy()
    no_entry = outcomes.loc[
        outcomes.status.isin(
            [
                "NO_LEGAL_ENTRY",
                "INVALID_COORDINATE_LINEAGE_BEFORE_ENTRY",
                "INVALID_CORPORATE_ACTION_STATE_BEFORE_ENTRY",
            ]
        )
    ]
    if no_entry[["entry_date", "entry_cal_idx", "entry_price", "target_price"]].notna().any().any():
        raise ResearchError("pre-entry terminal status carries an entry or target")
    if entered[["entry_date", "entry_price", "target_price"]].isna().any().any():
        raise ResearchError("entered lifecycle has a missing entry or target field")
    if not entered.empty:
        entry_price = pd.to_numeric(entered.entry_price, errors="coerce")
        target_price = pd.to_numeric(entered.target_price, errors="coerce")
        if (
            (~np.isfinite(entry_price)).any()
            or (~np.isfinite(target_price)).any()
            or not np.isclose(
                target_price,
                entry_price * (1.0 + TARGET_RETURN),
                atol=1e-12,
            ).all()
        ):
            raise ResearchError("Stage-B target-price identity drift")
        if (
            entered.entry_cal_idx.le(entered.signal_cal_idx).any()
            or entered.entry_cal_idx.gt(entered.signal_cal_idx + 3).any()
        ):
            raise ResearchError("entered lifecycle violates the +1 through +3 window")
    required_completed = (
        "entry_date",
        "entry_cal_idx",
        "entry_price",
        "exit_date",
        "exit_cal_idx",
        "exit_price",
        "exit_reason",
        "holding_sessions",
        "gross_return",
        "net_return",
    )
    if completed[list(required_completed)].isna().any().any():
        raise ResearchError("completed outcome has a missing lifecycle field")
    if not completed.empty:
        if (
            completed.exit_cal_idx.le(completed.entry_cal_idx).any()
            or completed.exit_date.gt(MAX_CHART_DATE).any()
        ):
            raise ResearchError("completed outcome violates T+1 or chart chronology")
        gross = pd.to_numeric(completed.gross_return, errors="coerce")
        net = pd.to_numeric(completed.net_return, errors="coerce")
        if (
            (~np.isfinite(gross)).any()
            or (~np.isfinite(net)).any()
            or not np.isclose(net, gross - ROUND_TRIP_COST, atol=1e-12).all()
        ):
            raise ResearchError("completed outcome return contract drift")

    audit_exit_marker_contract(outcomes)
    windows = load_windows(candidates)
    return candidates, outcomes, windows


def load_windows(candidates: pd.DataFrame) -> pd.DataFrame:
    con = duckdb.connect()
    con.register(
        "chart_keys",
        candidates[["event_id", "symbol", "signal_date", "signal_cal_idx", "decision_at"]],
    )
    windows = con.execute(
        f"""
        WITH calendar AS (
          SELECT DISTINCT trade_date,cal_idx
          FROM read_parquet('{DAILY.as_posix()}')
          WHERE trade_date BETWEEN DATE '2013-01-04' AND DATE '2020-12-31'
        ), expanded AS (
          SELECT k.event_id,k.symbol,k.signal_date,k.signal_cal_idx,
            k.decision_at AS signal_decision_at,
            c.trade_date,c.cal_idx,c.cal_idx-k.signal_cal_idx AS relative_session
          FROM chart_keys k JOIN calendar c
            ON c.cal_idx BETWEEN k.signal_cal_idx-126 AND k.signal_cal_idx+126
        )
        SELECT e.event_id,e.signal_date,e.signal_cal_idx,e.signal_decision_at,
          e.trade_date,e.cal_idx,
          e.relative_session,d.coord_open,d.coord_high,d.coord_low,d.coord_close,
          d.turnover_fraction,d.current_valid,d.hard_valid,d.available_at,
          d.decision_at AS bar_decision_at
        FROM expanded e LEFT JOIN (
          SELECT * FROM read_parquet('{DAILY.as_posix()}')
          WHERE trade_date BETWEEN DATE '2013-01-04' AND DATE '2020-12-31'
        ) d
          ON d.symbol=e.symbol AND d.cal_idx=e.cal_idx
        ORDER BY e.event_id,e.cal_idx
        """
    ).fetch_df()
    con.close()
    for column in (
        "signal_date",
        "signal_decision_at",
        "trade_date",
        "available_at",
        "bar_decision_at",
    ):
        windows[column] = pd.to_datetime(windows[column])
    counts = windows.groupby("event_id").agg(
        rows=("cal_idx", "size"),
        first=("relative_session", "min"),
        last=("relative_session", "max"),
    )
    if (
        not counts.rows.eq(2 * WINDOW_SESSIONS + 1).all()
        or not counts["first"].eq(-WINDOW_SESSIONS).all()
        or not counts["last"].eq(WINDOW_SESSIONS).all()
        or windows.duplicated(["event_id", "cal_idx"]).any()
        or windows.trade_date.max() > MAX_CHART_DATE
    ):
        raise ResearchError("signal +/-126 global-session window is incomplete")
    signal = windows.loc[windows.relative_session.eq(0)]
    if (
        len(signal) != len(candidates)
        or signal.coord_close.isna().any()
        or not signal.trade_date.eq(signal.signal_date).all()
        or not signal.cal_idx.eq(signal.signal_cal_idx).all()
    ):
        raise ResearchError("chart window lacks one exact signal bar per event")
    eligible_numeric = windows[["coord_open", "coord_high", "coord_low", "coord_close"]].apply(
        pd.to_numeric, errors="coerce"
    )
    eligible = windows.loc[
        windows.relative_session.le(0)
        & windows.current_valid.fillna(False)
        & windows.hard_valid.fillna(False)
        & np.isfinite(eligible_numeric).all(axis=1)
    ]
    if (
        eligible.available_at.isna().any()
        or eligible.signal_decision_at.isna().any()
        or eligible.available_at.gt(eligible.signal_decision_at).any()
    ):
        raise ResearchError("pre-signal chart row was unavailable at signal decision_at")
    return windows


def build_ledger(
    candidates: pd.DataFrame, outcomes: pd.DataFrame, windows: pd.DataFrame
) -> pd.DataFrame:
    outcome_lookup = {str(row.event_id): row for row in outcomes.itertuples(index=False)}
    window_lookup = {str(key): part for key, part in windows.groupby("event_id", sort=False)}
    rows: list[dict[str, Any]] = []
    ordered = candidates.sort_values(
        ["signal_date", "causal_industry", "symbol", "event_id"], kind="mergesort"
    )
    for chart_number, event in enumerate(ordered.itertuples(index=False), start=1):
        frame = window_lookup[str(event.event_id)]
        numeric = frame[["coord_open", "coord_high", "coord_low", "coord_close"]].apply(
            pd.to_numeric, errors="coerce"
        )
        valid = frame.loc[
            frame.current_valid.fillna(False)
            & frame.hard_valid.fillna(False)
            & np.isfinite(numeric).all(axis=1)
            & numeric.gt(0).all(axis=1)
        ].sort_values("cal_idx", kind="mergesort")
        signal = valid.loc[valid.relative_session.eq(0)]
        if len(signal) != 1:
            raise ResearchError(f"{event.event_id}: signal chart bar not unique")
        before = valid.loc[valid.relative_session.lt(0)]
        if before.empty:
            raise ResearchError(f"{event.event_id}: no pre-signal chart history")
        signal_close = float(signal.iloc[0].coord_close)
        prior_high = float(before.coord_high.max())
        prior_low = float(before.coord_low.min())
        outcome = outcome_lookup[str(event.event_id)]
        net_return = float(outcome.net_return) if pd.notna(outcome.net_return) else math.nan
        rows.append(
            {
                "event_id": str(event.event_id),
                "chart_number": chart_number,
                "symbol": str(event.symbol),
                "sleeve": str(event.sleeve),
                "causal_industry": str(event.causal_industry),
                "signal_date": pd.Timestamp(event.signal_date),
                "signal_cal_idx": int(event.signal_cal_idx),
                "turnover_pfc_score": float(event.turnover_pfc_score),
                "pfc_r1": float(event.pfc_r1),
                "pfc_r5": float(event.pfc_r5),
                "pfc_r22": float(event.turnover_pfc_r22),
                "ret20": float(event.ret20),
                "ret60": float(event.ret60),
                "signal_turnover_ratio": float(event.turnover_fraction)
                / float(event.mean_turnover_60),
                "pre126_return": signal_close / float(before.coord_close.iloc[0]) - 1,
                "pre126_drawdown_from_high": signal_close / prior_high - 1,
                "pre126_position": (signal_close - prior_low) / (prior_high - prior_low)
                if prior_high > prior_low
                else math.nan,
                "status": str(outcome.status),
                "entry_date": pd.Timestamp(outcome.entry_date)
                if pd.notna(outcome.entry_date)
                else pd.NaT,
                "entry_cal_idx": int(outcome.entry_cal_idx)
                if pd.notna(outcome.entry_cal_idx)
                else math.nan,
                "entry_price": float(outcome.entry_price)
                if pd.notna(outcome.entry_price)
                else math.nan,
                "target_price": float(outcome.target_price)
                if pd.notna(outcome.target_price)
                else math.nan,
                "exit_date": pd.Timestamp(outcome.exit_date)
                if pd.notna(outcome.exit_date)
                else pd.NaT,
                "exit_cal_idx": int(outcome.exit_cal_idx)
                if pd.notna(outcome.exit_cal_idx)
                else math.nan,
                "exit_relative_session": int(outcome.exit_relative_session)
                if pd.notna(outcome.exit_relative_session)
                else math.nan,
                "exit_marker_mode": str(outcome.exit_marker_mode),
                "exit_price": float(outcome.exit_price)
                if pd.notna(outcome.exit_price)
                else math.nan,
                "exit_reason": str(outcome.exit_reason) if pd.notna(outcome.exit_reason) else "",
                "net_return": net_return,
                "outcome_bucket": outcome_bucket(str(outcome.status), net_return),
            }
        )
    ledger = pd.DataFrame(rows)
    if ledger.event_id.duplicated().any() or set(ledger.event_id) != set(candidates.event_id):
        raise ResearchError("review ledger does not cover every event exactly once")
    return ledger


def _font(size: int) -> ImageFont.ImageFont:
    for path in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ):
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _triangle(draw: ImageDraw.ImageDraw, x: int, y: int, up: bool, color: str) -> None:
    points = (
        [(x, y - 7), (x - 6, y + 5), (x + 6, y + 5)]
        if up
        else [(x, y + 7), (x - 6, y - 5), (x + 6, y - 5)]
    )
    draw.polygon(points, fill=color)


def render_chart(event: pd.Series, frame: pd.DataFrame, output: Path) -> None:
    image = Image.new("RGB", CHART_SIZE, "white")
    draw = ImageDraw.Draw(image)
    font, small = _font(12), _font(10)
    left, right = 34, CHART_SIZE[0] - 8
    price_top, price_bottom = 82, 294
    volume_top, volume_bottom = 308, CHART_SIZE[1] - 8

    numeric = frame[["coord_open", "coord_high", "coord_low", "coord_close"]].apply(
        pd.to_numeric, errors="coerce"
    )
    valid = frame.loc[
        frame.current_valid.fillna(False)
        & frame.hard_valid.fillna(False)
        & np.isfinite(numeric).all(axis=1)
        & numeric.gt(0).all(axis=1)
    ].sort_values("cal_idx", kind="mergesort")
    signal = valid.loc[valid.relative_session.eq(0)]
    if len(signal) != 1:
        raise ResearchError(f"{event.event_id}: chart signal bar not unique")
    signal_close = float(signal.iloc[0].coord_close)
    exit_relative = (
        int(event.exit_cal_idx) - int(event.signal_cal_idx)
        if pd.notna(event.exit_cal_idx)
        else None
    )

    lows = list(valid.coord_low.astype(float))
    highs = list(valid.coord_high.astype(float))
    if math.isfinite(float(event.entry_price)):
        lows.append(float(event.entry_price))
    if math.isfinite(float(event.target_price)):
        highs.append(float(event.target_price))
    if event.exit_marker_mode == IN_WINDOW_EXIT_MARKER and math.isfinite(float(event.exit_price)):
        lows.append(float(event.exit_price))
        highs.append(float(event.exit_price))
    low, high = min(lows), max(highs)
    if not high > low:
        high = low * 1.01
    pad = (high - low) * 0.04
    low, high = low - pad, high + pad

    def x_at(relative_session: int) -> int:
        return int(
            left + (relative_session + WINDOW_SESSIONS) * (right - left) / (2 * WINDOW_SESSIONS)
        )

    def y_at(value: float) -> int:
        return int(price_bottom - (value - low) * (price_bottom - price_top) / (high - low))

    signal_x = x_at(0)
    draw.rectangle((left, price_top, signal_x, volume_bottom), fill="#eff6ff")
    draw.rectangle((signal_x + 1, price_top, right, volume_bottom), fill="#fff7ed")
    draw.text((left + 4, price_top + 3), "PRE-SIGNAL: RULE EVIDENCE", fill="#1d4ed8", font=small)
    draw.text(
        (signal_x + 5, price_top + 3),
        "POST-SIGNAL: ATTRIBUTION ONLY",
        fill="#c2410c",
        font=small,
    )
    draw.rectangle((left, price_top, right, price_bottom), outline="#9ca3af")
    draw.rectangle((left, volume_top, right, volume_bottom), outline="#d1d5db")
    max_turn = max(float(valid.turnover_fraction.fillna(0).max()), 1e-9)
    date_to_relative: dict[pd.Timestamp, int] = {}
    cal_idx_to_relative: dict[int, int] = {}
    cal_idx_to_date: dict[int, pd.Timestamp] = {}
    for row in valid.itertuples(index=False):
        relative = int(row.relative_session)
        date_to_relative[pd.Timestamp(row.trade_date)] = relative
        cal_idx_to_relative[int(row.cal_idx)] = relative
        cal_idx_to_date[int(row.cal_idx)] = pd.Timestamp(row.trade_date)
        x = x_at(relative)
        open_y, close_y = y_at(float(row.coord_open)), y_at(float(row.coord_close))
        high_y, low_y = y_at(float(row.coord_high)), y_at(float(row.coord_low))
        color = "#dc2626" if float(row.coord_close) >= float(row.coord_open) else "#16803c"
        draw.line((x, high_y, x, low_y), fill=color, width=1)
        body_top, body_bottom = sorted((open_y, close_y))
        draw.rectangle((x - 1, body_top, x + 1, max(body_top + 1, body_bottom)), fill=color)
        if pd.notna(row.turnover_fraction):
            bar = int(float(row.turnover_fraction) / max_turn * (volume_bottom - volume_top - 2))
            draw.rectangle((x - 1, volume_bottom - bar, x + 1, volume_bottom), fill="#9ca3af")

    draw.line((signal_x, price_top, signal_x, volume_bottom), fill="#b45309", width=2)
    signal_y = y_at(signal_close)
    for x in range(left, signal_x + 1, 8):
        draw.line((x, signal_y, min(x + 4, signal_x), signal_y), fill="#b45309")
    draw.text((signal_x + 3, signal_y - 13), "S close", fill="#92400e", font=small)

    if (
        pd.notna(event.entry_date)
        and pd.notna(event.entry_cal_idx)
        and math.isfinite(float(event.entry_price))
        and math.isfinite(float(event.target_price))
    ):
        entry_cal_idx = int(event.entry_cal_idx)
        relative = cal_idx_to_relative.get(entry_cal_idx)
        if (
            relative is None
            or relative < 1
            or relative > 3
            or cal_idx_to_date.get(entry_cal_idx) != pd.Timestamp(event.entry_date)
            or date_to_relative.get(pd.Timestamp(event.entry_date)) != relative
        ):
            raise ResearchError(f"{event.event_id}: entry is outside chart bars")
        entry_x, entry_y = x_at(relative), y_at(float(event.entry_price))
        _triangle(draw, entry_x, entry_y, True, "#7c3aed")
        draw.text((entry_x + 3, entry_y - 13), "E", fill="#7c3aed", font=small)
        target_y = y_at(float(event.target_price))
        for x in range(entry_x, right + 1, 10):
            draw.line((x, target_y, min(x + 5, right), target_y), fill="#f97316")
        draw.text((entry_x + 3, target_y - 13), "T +10%", fill="#c2410c", font=small)
    if event.status == "COMPLETED":
        if (
            pd.isna(event.exit_date)
            or exit_relative is None
            or not math.isfinite(float(event.exit_price))
        ):
            raise ResearchError(f"{event.event_id}: completed exit identity is missing")
        if event.exit_marker_mode == IN_WINDOW_EXIT_MARKER:
            exit_cal_idx = int(event.exit_cal_idx)
            relative = cal_idx_to_relative.get(exit_cal_idx)
            if (
                relative is None
                or relative < 1
                or relative > WINDOW_SESSIONS
                or relative != exit_relative
                or cal_idx_to_date.get(exit_cal_idx) != pd.Timestamp(event.exit_date)
                or date_to_relative.get(pd.Timestamp(event.exit_date)) != relative
            ):
                raise ResearchError(f"{event.event_id}: in-window exit bar is invalid")
            exit_x, exit_y = x_at(relative), y_at(float(event.exit_price))
            _triangle(draw, exit_x, exit_y, False, "#111827")
            draw.text(
                (exit_x + 3, exit_y + 4),
                f"X {event.exit_reason}",
                fill="#111827",
                font=small,
            )
        elif event.exit_marker_mode == OUT_OF_WINDOW_EXIT_MARKER:
            if exit_relative <= WINDOW_SESSIONS:
                raise ResearchError(f"{event.event_id}: false out-of-window exit marker")
            annotation_y = price_top - 8
            draw.line((right - 18, annotation_y, right - 3, annotation_y), fill="#111827", width=2)
            draw.polygon(
                [
                    (right - 1, annotation_y),
                    (right - 7, annotation_y - 4),
                    (right - 7, annotation_y + 4),
                ],
                fill="#111827",
            )
            draw.text(
                (6, 65),
                f"POST X OUTSIDE WINDOW date={pd.Timestamp(event.exit_date):%Y-%m-%d} "
                f"rel=+{exit_relative} reason={event.exit_reason}; price not plotted",
                fill="#111827",
                font=small,
            )
        else:
            raise ResearchError(f"{event.event_id}: unknown completed-exit marker mode")
    elif event.exit_marker_mode != NO_COMPLETED_EXIT_MARKER:
        raise ResearchError(f"{event.event_id}: noncompleted event has an exit marker")

    net = "NA" if not math.isfinite(float(event.net_return)) else f"{float(event.net_return):+.1%}"
    draw.text(
        (6, 4),
        f"{int(event.chart_number):05d} {event.symbol} {pd.Timestamp(event.signal_date):%Y-%m-%d} "
        f"{event.causal_industry}",
        fill="#111827",
        font=font,
    )
    draw.text(
        (6, 21),
        f"PRE pfc={float(event.turnover_pfc_score):+.2f} "
        f"(1/5/22={float(event.pfc_r1):+.2f}/{float(event.pfc_r5):+.2f}/"
        f"{float(event.pfc_r22):+.2f}) r20/60={float(event.ret20):+.1%}/"
        f"{float(event.ret60):+.1%}",
        fill="#1e3a8a",
        font=small,
    )
    draw.text((6, 38), str(event.event_id), fill="#4b5563", font=small)
    draw.text(
        (6, 51),
        f"POST status={event.status} bucket={event.outcome_bucket} net={net}",
        fill="#9a3412",
        font=small,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=False)


def render_worker(payload: tuple[dict[str, Any], pd.DataFrame, str]) -> dict[str, Any]:
    event_dict, frame, output_text = payload
    event = pd.Series(event_dict)
    output = Path(output_text)
    render_chart(event, frame, output)
    return {
        "event_id": str(event.event_id),
        "chart_number": int(event.chart_number),
        "symbol": str(event.symbol),
        "signal_date": pd.Timestamp(event.signal_date),
        "outcome_bucket": str(event.outcome_bucket),
        "exit_marker_mode": str(event.exit_marker_mode),
        "exit_date": pd.Timestamp(event.exit_date) if pd.notna(event.exit_date) else pd.NaT,
        "exit_relative_session": int(event.exit_relative_session)
        if pd.notna(event.exit_relative_session)
        else math.nan,
        "chart_path": str(output),
        "chart_sha256": sha256(output),
    }


def build_grids(
    frame: pd.DataFrame, output_dir: Path, label: str, collection: str
) -> tuple[list[Path], list[dict[str, Any]]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    placements: list[dict[str, Any]] = []
    page_size = GRID_COLUMNS * GRID_ROWS
    ordered = frame.reset_index(drop=True)
    for page, start in enumerate(range(0, len(ordered), page_size), start=1):
        part = ordered.iloc[start : start + page_size]
        sheet = Image.new(
            "RGB",
            (CHART_SIZE[0] * GRID_COLUMNS, CHART_SIZE[1] * GRID_ROWS + 28),
            "#e5e7eb",
        )
        draw = ImageDraw.Draw(sheet)
        draw.text(
            (8, 7),
            f"{label} page {page:04d} charts {start + 1}-{start + len(part)}",
            fill="#111827",
            font=_font(13),
        )
        target = output_dir / f"sheet_{page:04d}.jpg"
        for slot, row in enumerate(part.itertuples(index=False), start=1):
            with Image.open(str(row.chart_path)) as chart:
                column = (slot - 1) % GRID_COLUMNS
                grid_row = (slot - 1) // GRID_COLUMNS
                sheet.paste(
                    chart.convert("RGB"),
                    (column * CHART_SIZE[0], grid_row * CHART_SIZE[1] + 28),
                )
            placements.append(
                {
                    "collection": collection,
                    "sheet_path": str(target),
                    "sheet_number": page,
                    "slot": slot,
                    "event_id": str(row.event_id),
                    "chart_number": int(row.chart_number),
                    "outcome_bucket": str(row.outcome_bucket),
                }
            )
        sheet.save(target, format="JPEG", quality=87, optimize=False)
        paths.append(target)
    return paths, placements


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    con = duckdb.connect()
    con.register("frame", frame)
    con.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def run(workers: int) -> dict[str, Any]:
    if CHART_ROOT.exists():
        raise ResearchError(f"canonical chart root already exists: {CHART_ROOT}")
    source_hashes, review_spec = verify_inputs()
    if not OUTPUT_ROOT.is_dir():
        raise ResearchError(f"missing same-parent output root: {OUTPUT_ROOT}")
    staging_root = Path(tempfile.mkdtemp(prefix=".stage_c_charts.staging.", dir=str(OUTPUT_ROOT)))
    window_panel = staging_root / WINDOW_PANEL.relative_to(CHART_ROOT)
    review_ledger = staging_root / REVIEW_LEDGER.relative_to(CHART_ROOT)
    review_csv = staging_root / REVIEW_CSV.relative_to(CHART_ROOT)
    review_template_path = staging_root / REVIEW_TEMPLATE.relative_to(CHART_ROOT)
    chart_dir = staging_root / CHART_DIR.relative_to(CHART_ROOT)
    chart_index_path = staging_root / CHART_INDEX.relative_to(CHART_ROOT)
    placements_path = staging_root / PLACEMENTS.relative_to(CHART_ROOT)
    sheet_index_path = staging_root / SHEET_INDEX.relative_to(CHART_ROOT)
    sheet_dir = staging_root / SHEET_DIR.relative_to(CHART_ROOT)
    outcome_sheet_root = staging_root / OUTCOME_SHEET_ROOT.relative_to(CHART_ROOT)
    manifest_path = staging_root / MANIFEST.relative_to(CHART_ROOT)
    try:
        candidates, outcomes, windows = load_inputs()
        ledger = build_ledger(candidates, outcomes, windows)
        write_parquet(windows, window_panel)
        write_parquet(ledger, review_ledger)
        ledger.to_csv(review_csv, index=False, float_format="%.10g")

        groups = {str(key): part for key, part in windows.groupby("event_id", sort=False)}
        tasks = []
        for event in ledger.itertuples(index=False):
            target = chart_dir / (
                f"{int(event.chart_number):05d}_{event.symbol.replace('.', '_')}_"
                f"{pd.Timestamp(event.signal_date):%Y%m%d}.png"
            )
            tasks.append((event._asdict(), groups[str(event.event_id)], str(target)))
        with ProcessPoolExecutor(max_workers=max(1, workers)) as executor:
            chart_index = pd.DataFrame(list(executor.map(render_worker, tasks, chunksize=8)))
        chart_index = chart_index.sort_values("chart_number", kind="mergesort")
        out_of_window_exit_count = int(
            chart_index.exit_marker_mode.eq(OUT_OF_WINDOW_EXIT_MARKER).sum()
        )
        if (
            len(chart_index) != len(candidates)
            or chart_index.event_id.duplicated().any()
            or set(chart_index.event_id) != set(candidates.event_id.astype(str))
            or chart_index.chart_number.duplicated().any()
            or set(chart_index.chart_number) != set(range(1, len(candidates) + 1))
            or chart_index.chart_path.duplicated().any()
            or out_of_window_exit_count != EXPECTED_OUT_OF_WINDOW_COMPLETED_EXITS
        ):
            raise ResearchError("individual charts do not cover each event exactly once")

        chronological_sheets, placements = build_grids(
            chart_index,
            sheet_dir,
            f"{EXPERIMENT} chronological",
            "chronological",
        )
        outcome_sheets: list[Path] = []
        for bucket in OUTCOME_BUCKETS:
            subset = chart_index.loc[chart_index.outcome_bucket.eq(bucket)].sort_values(
                ["signal_date", "symbol", "event_id"], kind="mergesort"
            )
            if subset.empty:
                continue
            sheets, rows = build_grids(
                subset,
                outcome_sheet_root / bucket.lower(),
                f"{EXPERIMENT} {bucket}",
                "outcome_group",
            )
            outcome_sheets.extend(sheets)
            placements.extend(rows)
        placement_frame = pd.DataFrame(placements)
        for collection in ("chronological", "outcome_group"):
            counts = placement_frame.loc[
                placement_frame.collection.eq(collection), "event_id"
            ].value_counts()
            if set(counts.index) != set(candidates.event_id.astype(str)) or not counts.eq(1).all():
                raise ResearchError(f"{collection} sheets do not cover every event exactly once")
        if placement_frame.groupby(["collection", "sheet_path"]).size().gt(25).any():
            raise ResearchError("contact sheet exceeds 25 charts")
        if (
            placement_frame.duplicated(["collection", "sheet_path", "slot"]).any()
            or not placement_frame.slot.between(1, 25).all()
        ):
            raise ResearchError("contact-sheet slot identity drift")
        sheet_index = (
            placement_frame.groupby(["collection", "sheet_path"], as_index=False)
            .agg(
                charts=("event_id", "size"),
                first_chart_number=("chart_number", "min"),
                last_chart_number=("chart_number", "max"),
            )
            .sort_values(["collection", "sheet_path"], kind="mergesort")
        )
        if (
            len(sheet_index) != len(chronological_sheets) + len(outcome_sheets)
            or sheet_index.sheet_path.duplicated().any()
            or not sheet_index.charts.between(1, 25).all()
        ):
            raise ResearchError("contact-sheet index coverage drift")
        sheet_index["sheet_sha256"] = sheet_index.sheet_path.map(lambda value: sha256(Path(value)))

        review_columns = review_spec["per_chart_review"]["columns"]
        review_template = chart_index[["event_id", "chart_number", "outcome_bucket"]].copy()
        for column in review_columns:
            if column not in review_template:
                review_template[column] = (
                    False
                    if column
                    in {
                        "reviewed",
                        "counterexample_flag",
                        "post_signal_used_as_rule",
                    }
                    else ""
                )
        if (
            len(review_template) != len(candidates)
            or review_template.event_id.duplicated().any()
            or set(review_template.event_id) != set(candidates.event_id.astype(str))
        ):
            raise ResearchError("manual review template coverage drift")
        review_template.to_csv(review_template_path, index=False)

        def published(path_text: str) -> str:
            return str(CHART_ROOT / Path(path_text).relative_to(staging_root))

        published_index = chart_index.copy()
        published_index["chart_path"] = published_index.chart_path.map(published)
        published_index.to_csv(chart_index_path, index=False, float_format="%.10g")
        placement_frame["sheet_path"] = placement_frame.sheet_path.map(published)
        placement_frame.to_csv(placements_path, index=False)
        sheet_index["sheet_path"] = sheet_index.sheet_path.map(published)
        sheet_index.to_csv(sheet_index_path, index=False)

        chart_files = [Path(path) for path in chart_index.chart_path]
        sheet_files = chronological_sheets + outcome_sheets
        if (
            any(not path.is_file() for path in chart_files)
            or any(
                sha256(path) != digest
                for path, digest in zip(chart_files, chart_index.chart_sha256, strict=True)
            )
            or len(list(chart_dir.glob("*.png"))) != len(chart_index)
            or any(not path.is_file() for path in sheet_files)
            or len(list(staging_root.glob("**/sheet_*.jpg"))) != len(sheet_index)
        ):
            raise ResearchError("staged chart-corpus file audit failed")

        payload = {
            "experiment": EXPERIMENT,
            "stage": "SEPARATELY_AUTHORIZED_FROZEN_DEVELOPMENT_CHART_REVIEW_CORPUS",
            "asset_id": CHART_ASSET_ID,
            "authorization_id": CHART_AUTHORIZATION_ID,
            "authorized_arm": CHART_AUTHORIZED_ARM,
            "source_hashes": source_hashes,
            "runner_sha256": sha256(Path(__file__)),
            "review_spec_sha256": sha256(REVIEW_SPEC),
            "window_panel_sha256": sha256(window_panel),
            "review_ledger_sha256": sha256(review_ledger),
            "chart_index_sha256": sha256(chart_index_path),
            "contact_sheet_placements_sha256": sha256(placements_path),
            "contact_sheet_index_sha256": sha256(sheet_index_path),
            "review_template_sha256": sha256(review_template_path),
            "events": len(candidates),
            "individual_charts": len(chart_index),
            "chronological_contact_sheets": len(chronological_sheets),
            "outcome_contact_sheets": len(outcome_sheets),
            "charts_per_sheet": GRID_COLUMNS * GRID_ROWS,
            "window_relative_sessions": [-WINDOW_SESSIONS, WINDOW_SESSIONS],
            "maximum_chart_date": str(MAX_CHART_DATE.date()),
            "exit_marker_mode": (
                "IN_WINDOW_PRICE_MARKER_OR_AUDITED_RIGHT_BOUNDARY_TEXT_NO_PRICE_POINT"
            ),
            "out_of_window_completed_exit_count": out_of_window_exit_count,
            "out_of_window_completed_exit_expected_count": (EXPECTED_OUT_OF_WINDOW_COMPLETED_EXITS),
            "out_of_window_exit_price_used_in_y_axis": False,
            "post_2020_row_read": False,
            "outcome_attachment_performed": False,
            "portfolio_replay_performed": False,
            "individual_event_coverage_exactly_once": True,
            "chronological_sheet_event_coverage_exactly_once": True,
            "outcome_group_sheet_event_coverage_exactly_once": True,
            "staged_file_identity_audit_passed": True,
            "all_bound_inputs_rehashed_immediately_before_publish": True,
            "published_by_same_parent_atomic_rename": True,
            "all_chronological_sheets_reviewed": False,
            "all_outcome_group_sheets_reviewed": False,
            "next_step": "REVIEW_EVERY_SHEET_AND_COMPLETE_PER_CHART_REVIEW_TEMPLATE",
        }
        write_json(manifest_path, payload)
        required_outputs = (
            window_panel,
            review_ledger,
            review_csv,
            review_template_path,
            chart_index_path,
            placements_path,
            sheet_index_path,
            manifest_path,
        )
        if any(not path.is_file() for path in required_outputs):
            raise ResearchError("staged chart corpus is incomplete")
        _rehash_all_bound_inputs(source_hashes)
        if CHART_ROOT.exists():
            raise ResearchError(f"canonical chart root appeared during build: {CHART_ROOT}")
        staging_root.rename(CHART_ROOT)
        return payload
    except BaseException:
        if staging_root.exists():
            shutil.rmtree(staging_root)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    print(json.dumps(run(args.workers), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
