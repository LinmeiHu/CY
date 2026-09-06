#!/usr/bin/env python3
"""Build the strictly anonymous, outcome-blind V36 Phase-1 chart corpus.

Only the immutable outcome-blind Stage-A candidate ledger, canonical CY-006
2018--2020 daily partitions, and the accepted action-coordinate state are data
inputs. V36 has no Stage-B artifact: this runner contains no Stage-B path and
must never stat, hash, open, parse, or infer one. Every rendered observation is
at or before its own signal close, and no identity crosswalk is persisted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

EXPERIMENT = "ASHARE-BROAD-MARKET-PRICE-DELAY-COMPENSATION-MOTHER-V36"
REPO = Path(__file__).resolve().parents[3]
EXP = REPO / "research/market_behavior_os_v2/experiments"
PARENT_SPEC = EXP / f"{EXPERIMENT}_freeze.json"
STAGE_A_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_broad_market_price_delay_compensation_mother_v36_stage_a.py"
)
STAGE_A_MANIFEST = EXP / "ASHARE-V36-CY054_DATA_ASSET_MANIFEST.json"
STAGE_A_SUGGESTION = EXP / "ASHARE-V36-CY054_REGISTRY_SUGGESTION.json"
REVIEW_SPEC = EXP / f"{EXPERIMENT}_visual_review_spec.json"
ANNOTATION_SCHEMA = EXP / "ASHARE-V34R1_phase1_anonymous_annotation_schema.json"
CHART_ASSET_MANIFEST = EXP / "ASHARE-V36-CY055_CHART_REVIEW_ASSET_MANIFEST.json"
REGISTRY = REPO / "configs/data_asset_registry.json"
COORDINATE_BUILDER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_former_leader_strict_gap_reclaim_v3.py"
)
COORDINATE_CONTRACT = REPO / "src/cyq_game/chip/price_coordinate.py"

DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
CY006_ROOT = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2")
CY006_MANIFEST = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "CY-006-pit-b-daily-v2-2018-2026-20260821.json"
)
CY006_PARTITIONS = tuple(
    CY006_ROOT / f"daily/partition_year={year}/data_0.parquet"
    for year in range(2018, 2021)
)
QD010_INVENTORY = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "QD-010-cninfo-actions-20260820.json"
)
COORDINATE_STATE = DATA_ROOT / (
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_adjusted_daily_state_2013_2023.parquet"
)
OUTPUT_ROOT = DATA_ROOT / "ashare_broad_market_price_delay_compensation_mother_v36"
STAGE_A_ROOT = OUTPUT_ROOT / "stage_a"
CANDIDATES = STAGE_A_ROOT / "candidates_frozen.parquet"
STAGE_A_RESULT = STAGE_A_ROOT / "result.json"
CHART_ROOT = OUTPUT_ROOT / "stage_c_phase1_anonymous_charts"

ASSET_ID = "CY-055"
DEPENDENCY_ASSET_ID = "CY-054"
AUTHORIZATION_ID = (
    "CYQ-AUTH-ASHARE-BROAD-MARKET-PRICE-DELAY-V36-"
    "PHASE1-CY055-ANONYMOUS-CHARTS-2019-2020-V1"
)
AUTHORIZATION_PURPOSE = "ASHARE_FROZEN_DEVELOPMENT_CHART_REVIEW"
AUTHORIZED_ARM = "V36_CY055_PHASE1_ANONYMOUS_CAUSAL_CHARTS_ONLY"
MANIFEST_STATUS = "FROZEN_DEVELOPMENT_CHART_REVIEW_BOUNDED_INPUT"
PIPELINE_VERSION = "v36-phase1-anonymous-causal-chart-review-v1"

REPO_FIXED_HASHES: dict[Path, str] = {
    PARENT_SPEC: "2dc6e2b1ac6e29105172cddc8a6d5dbafa06b30645a8f48b08abdf8f348286fc",
    STAGE_A_RUNNER: "3cf20dead4f7a04b1e8981502d484fd1e56599747129f3ff92085a462c0edf51",
    STAGE_A_MANIFEST: "8466e1ccd6cbbff159beb4ee9d582a0917f7eba9015d7a76251f273727e4973c",
    STAGE_A_SUGGESTION: "c228f6b5e837fcd99d4feb14d9be11436f4f4a3845af79bddfb7eecce64ff014",
    COORDINATE_BUILDER: "358b62014c52b7bf936937746223954512fe9451eaa5009063e14f39e1bb1787",
    COORDINATE_CONTRACT: "60c9f80fcaa2bf4a6ebfaab37bc56e81dd716cc3bea00891b4fc28d077dd1726",
    ANNOTATION_SCHEMA: "89eeb590b025a4d126d328acbd47a803696606a891a8b804264bf326705fb90d",
}
ALLOWED_DATA_HASHES: dict[Path, str] = {
    CANDIDATES: "6f9e84f1828bb054d8baea187e72563c8454909fe71f3a932ee8ea5456ff4e0b",
    STAGE_A_RESULT: "5d05d21c78f5c4722cdcf3eb86db53e0d9d37d7a37e45a465b1ee78a924d8529",
    CY006_MANIFEST: "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2",
    CY006_PARTITIONS[0]: "b906d2c21fd35128b8f65f1b00fa12ae6e5bd9ee476a368a63881304f38ceed4",
    CY006_PARTITIONS[1]: "c69a464e4a04efdca0177a8a09a13a34646531afa37a2b35b4892fd40ec3ebfd",
    CY006_PARTITIONS[2]: "1b0a00c6d2cfbce0ae4f907e1ee9dc5006f59677d556cc10f8f34a9893937c62",
    QD010_INVENTORY: "e1ca622ee227ce308b44933160754d450b80d3ecca79c1470037558e1011ceb8",
    COORDINATE_STATE: "76fe88cb7509ae33a3d32b1bfd6d0c90560083127bdfaf63da1d7d24ec72bf60",
}
SOURCE_ROLE_BINDINGS: dict[str, tuple[Path, str]] = {
    "stage_a_frozen_candidates": (CANDIDATES, ALLOWED_DATA_HASHES[CANDIDATES]),
    "stage_a_outcome_blind_result": (
        STAGE_A_RESULT,
        ALLOWED_DATA_HASHES[STAGE_A_RESULT],
    ),
    "cy006_manifest": (CY006_MANIFEST, ALLOWED_DATA_HASHES[CY006_MANIFEST]),
    "cy006_2018": (CY006_PARTITIONS[0], ALLOWED_DATA_HASHES[CY006_PARTITIONS[0]]),
    "cy006_2019": (CY006_PARTITIONS[1], ALLOWED_DATA_HASHES[CY006_PARTITIONS[1]]),
    "cy006_2020": (CY006_PARTITIONS[2], ALLOWED_DATA_HASHES[CY006_PARTITIONS[2]]),
    "qd010_inventory": (QD010_INVENTORY, ALLOWED_DATA_HASHES[QD010_INVENTORY]),
    "coordinate_state": (COORDINATE_STATE, ALLOWED_DATA_HASHES[COORDINATE_STATE]),
}
PUBLIC_ROLE_BINDINGS: dict[str, tuple[Path, str]] = {
    "parent_spec": (PARENT_SPEC, REPO_FIXED_HASHES[PARENT_SPEC]),
    "stage_a_runner": (STAGE_A_RUNNER, REPO_FIXED_HASHES[STAGE_A_RUNNER]),
    "stage_a_manifest": (STAGE_A_MANIFEST, REPO_FIXED_HASHES[STAGE_A_MANIFEST]),
    "stage_a_registry_suggestion": (
        STAGE_A_SUGGESTION,
        REPO_FIXED_HASHES[STAGE_A_SUGGESTION],
    ),
    "coordinate_builder": (
        COORDINATE_BUILDER,
        REPO_FIXED_HASHES[COORDINATE_BUILDER],
    ),
    "corporate_action_coordinate_contract": (
        COORDINATE_CONTRACT,
        REPO_FIXED_HASHES[COORDINATE_CONTRACT],
    ),
    "phase1_annotation_schema": (
        ANNOTATION_SCHEMA,
        REPO_FIXED_HASHES[ANNOTATION_SCHEMA],
    ),
}

EXPECTED_EVENTS = 531
EXPECTED_ANNUAL = {2019: 249, 2020: 282}
SIGNAL_START = pd.Timestamp("2019-03-29")
SIGNAL_END = pd.Timestamp("2020-12-31")
SOURCE_START = pd.Timestamp("2018-01-01")
WINDOW = 126
WINDOW_ROWS = 127
OPAQUE_ORDER_SALT = "V36_PHASE1_CAUSAL_MASKED_ORDER_V1"
MIN_MARKET_MEMBERS = 500

CHART_SIZE = (720, 440)
LEFT_EDGE, RIGHT_EDGE = 42, 710
PRICE_TOP, PRICE_BOTTOM = 88, 274
MARKET_TOP, MARKET_BOTTOM = 290, 339
TURNOVER_TOP, TURNOVER_BOTTOM = 355, 424
GRID_COLUMNS, GRID_ROWS = 5, 5
EXPECTED_SHEETS = 22

SNAPSHOT_COLUMNS = (
    "snapshot_id",
    "daily_snapshot_id",
    "trading_state_snapshot_id",
    "industry_snapshot_id",
    "float_snapshot_id",
    "corporate_action_snapshot_id",
    "market_snapshot_id",
)


class ResearchError(RuntimeError):
    """Fail closed on authorization, chronology, lineage, or coverage drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ResearchError(f"{label} is not a JSON object")
    return value


def only(items: list[dict[str, Any]], label: str) -> dict[str, Any]:
    if len(items) != 1:
        raise ResearchError(f"expected exactly one {label}; found {len(items)}")
    return items[0]


def role_map(items: Any, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        raise ResearchError(f"{label} is not a list")
    mapped: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("role"), str):
            raise ResearchError(f"invalid {label} item")
        role = str(item["role"])
        if role in mapped:
            raise ResearchError(f"duplicate {label} role: {role}")
        mapped[role] = item
    return mapped


def _verify_role_bindings(
    items: Any,
    expected: dict[str, tuple[Path, str]],
    label: str,
) -> None:
    mapped = role_map(items, label)
    if set(mapped) != set(expected):
        raise ResearchError(
            f"{label} role-set drift: "
            f"missing={sorted(set(expected) - set(mapped))}, "
            f"extra={sorted(set(mapped) - set(expected))}"
        )
    for role, (path, digest) in expected.items():
        item = mapped[role]
        if item.get("path") != str(path) or item.get("sha256") != digest:
            raise ResearchError(f"{label} lexical binding drift: {role}")


def verify_public_authorization() -> tuple[dict[str, str], dict[str, Any]]:
    """Verify public contracts lexically before touching any external input."""
    required = (
        REGISTRY,
        REVIEW_SPEC,
        ANNOTATION_SCHEMA,
        CHART_ASSET_MANIFEST,
        Path(__file__),
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ResearchError(f"missing public CY-055 authorization input: {missing}")
    actual = {
        "registry": sha256(REGISTRY),
        "visual_review_spec": sha256(REVIEW_SPEC),
        "annotation_schema": sha256(ANNOTATION_SCHEMA),
        "chart_asset_manifest": sha256(CHART_ASSET_MANIFEST),
        "chart_runner": sha256(Path(__file__)),
    }
    for role, (path, expected) in PUBLIC_ROLE_BINDINGS.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen public input {role}: {path}")
        value = sha256(path)
        if value != expected:
            raise ResearchError(f"frozen public input drift: {role}")
        actual[role] = value

    registry = load_json(REGISTRY, "data registry")
    asset = only(
        [item for item in registry.get("assets", []) if item.get("asset_id") == ASSET_ID],
        f"asset {ASSET_ID}",
    )
    authorization = only(
        [
            item
            for item in registry.get("bounded_authorizations", [])
            if item.get("authorization_id") == AUTHORIZATION_ID
        ],
        AUTHORIZATION_ID,
    )
    lineage = asset.get("lineage", {})
    scope = authorization.get("scope", {})
    protocol = authorization.get("bound_protocol", {})
    bound_manifest = authorization.get("bound_manifest", {})
    required_true = (
        "charts_authorized",
        "phase1_anonymous_charts_authorized",
        "stage_a_frozen_candidates_read_authorized",
        "stage_a_outcome_blind_result_read_authorized",
        "canonical_cy006_raw_daily_read_authorized",
        "coordinate_state_bounded_row_read_authorized",
        "coordinate_artifact_hash_authorized",
        "source_lineage_metadata_hash_authorized",
        "coverage_preflight_authorized",
    )
    required_false = (
        "stage_b_authorized",
        "stage_b_artifact_any_path_declaration_authorized",
        "stage_b_artifact_stat_authorized",
        "stage_b_artifact_hash_authorized",
        "stage_b_artifact_open_authorized",
        "stage_b_artifact_parse_authorized",
        "outcome_artifact_parse_authorized",
        "outcome_artifact_hash_authorized",
        "outcome_artifact_stat_authorized",
        "outcome_artifact_open_authorized",
        "outcome_columns_read_authorized",
        "post_signal_row_read_authorized",
        "full_chart_authorized",
        "identity_reveal_authorized",
        "identity_crosswalk_persist_authorized",
        "outcome_grouping_authorized",
        "outcome_attachment_authorized",
        "phase2_authorized",
        "rule_aggregation_authorized",
        "rule_compression_authorized",
        "portfolio_replay_authorized",
        "validation_authorized",
        "candidate_reselection_authorized",
        "post_2020_read_authorized",
        "2021_read_authorized",
        "2022_plus_read_authorized",
        "current_survivor_fallback_allowed",
    )
    if (
        asset.get("status") != "RESEARCH_CONDITIONAL"
        or asset.get("pit_grade") != "B"
        or lineage.get("manifest_path") != str(CHART_ASSET_MANIFEST.resolve())
        or lineage.get("manifest_sha256") != actual["chart_asset_manifest"]
        or lineage.get("bounded_authorization_id") != AUTHORIZATION_ID
        or lineage.get("pipeline_version") != PIPELINE_VERSION
        or authorization.get("asset_id") != ASSET_ID
        or authorization.get("dependency_asset_id") != DEPENDENCY_ASSET_ID
        or authorization.get("dependency_asset_ids")
        != [DEPENDENCY_ASSET_ID, "CY-006", "QD-010"]
        or authorization.get("dependency_status") != "RESEARCH_CONDITIONAL"
        or authorization.get("purpose") != AUTHORIZATION_PURPOSE
        or authorization.get("authorized_arms") != [AUTHORIZED_ARM]
        or bound_manifest.get("path") != str(CHART_ASSET_MANIFEST)
        or bound_manifest.get("sha256") != actual["chart_asset_manifest"]
        or any(authorization.get(key) is not True for key in required_true)
        or any(authorization.get(key) is not False for key in required_false)
        or authorization.get("record_level_available_at_available") is not False
        or scope.get("start") != str(SOURCE_START.date())
        or scope.get("end") != str(SIGNAL_END.date())
        or scope.get("signal_start") != str(SIGNAL_START.date())
        or scope.get("signal_end") != str(SIGNAL_END.date())
        or scope.get("maximum_chart_date") != str(SIGNAL_END.date())
        or scope.get("frozen_candidate_rows") != EXPECTED_EVENTS
        or scope.get("phase1_relative_global_sessions") != [-WINDOW, 0]
        or protocol.get("path") != str(REVIEW_SPEC.resolve())
        or protocol.get("sha256") != actual["visual_review_spec"]
        or protocol.get("runner_path") != str(Path(__file__).resolve())
        or protocol.get("runner_sha256") != actual["chart_runner"]
    ):
        raise ResearchError("CY-055 registry authorization semantics drift")

    expected_roles = {**PUBLIC_ROLE_BINDINGS, **SOURCE_ROLE_BINDINGS}
    _verify_role_bindings(
        authorization.get("bound_artifacts", []),
        expected_roles,
        "CY-055 registry bound_artifacts",
    )

    spec = load_json(REVIEW_SPEC, "V36 visual-review spec")
    renderer = spec.get("renderer", {})
    schema = spec.get("annotation_schema", {})
    required_auth = spec.get("required_authorization", {})
    permissions = required_auth.get("permissions", {})
    stage_b_boundary = spec.get("stage_b_nonexistence_boundary", {})
    frozen_scope = spec.get("frozen_scope", {})
    blind_order = spec.get("blind_order_contract", {})
    output_contract = spec.get("output_contract", {})
    if (
        spec.get("experiment") != EXPERIMENT
        or spec.get("stage") != "PHASE1_ANONYMOUS_CAUSAL_VISUAL_REVIEW"
        or spec.get("status") != "FROZEN_BEFORE_RENDER_OR_ANNOTATION"
        or spec.get("pipeline_version") != PIPELINE_VERSION
        or spec.get("maximum_compressed_rules") != 0
        or renderer.get("path") != str(Path(__file__).relative_to(REPO))
        or renderer.get("sha256") != actual["chart_runner"]
        or schema.get("path") != str(ANNOTATION_SCHEMA.relative_to(REPO))
        or schema.get("sha256") != actual["annotation_schema"]
        or required_auth.get("asset_id") != ASSET_ID
        or required_auth.get("dependency_asset_id") != DEPENDENCY_ASSET_ID
        or required_auth.get("authorization_id") != AUTHORIZATION_ID
        or required_auth.get("purpose") != AUTHORIZATION_PURPOSE
        or required_auth.get("authorized_arm") != AUTHORIZED_ARM
        or any(permissions.get(key) is not True for key in required_true)
        or any(permissions.get(key) is not False for key in required_false)
        or stage_b_boundary.get("stage_b_artifacts_exist") is not False
        or stage_b_boundary.get("any_stage_b_path_declared") is not False
        or stage_b_boundary.get(
            "any_stage_b_artifact_may_be_statted_hashed_opened_or_parsed"
        )
        is not False
        or frozen_scope.get("event_rows") != EXPECTED_EVENTS
        or frozen_scope.get("annual_event_rows") != {"2019": 249, "2020": 282}
        or frozen_scope.get("signal_start") != str(SIGNAL_START.date())
        or frozen_scope.get("signal_end") != str(SIGNAL_END.date())
        or frozen_scope.get("phase1_relative_global_sessions") != [-WINDOW, 0]
        or frozen_scope.get("window_slots_per_event") != WINDOW_ROWS
        or frozen_scope.get("post_signal_rows") != 0
        or frozen_scope.get("post_2020_rows") != 0
        or blind_order.get("salt") != OPAQUE_ORDER_SALT
        or blind_order.get("persist_identity_crosswalk") is not False
        or output_contract.get("canonical_directory") != str(CHART_ROOT)
        or output_contract.get("individual_anonymous_charts") != EXPECTED_EVENTS
        or output_contract.get("chart_size_pixels") != list(CHART_SIZE)
        or output_contract.get("anonymous_contact_sheets") != EXPECTED_SHEETS
    ):
        raise ResearchError("V36 Phase-1 visual-review spec binding drift")
    _verify_role_bindings(
        spec.get("permitted_data_inputs", {}).get("source_artifacts", []),
        SOURCE_ROLE_BINDINGS,
        "V36 spec source_artifacts",
    )

    manifest = load_json(CHART_ASSET_MANIFEST, "CY-055 chart manifest")
    boundary = manifest.get("authorization_boundary", {})
    protocol = manifest.get("protocol", {})
    cohort = manifest.get("frozen_cohort", {})
    stage_b_boundary = manifest.get("stage_b_nonexistence_boundary", {})
    manifest_output = manifest.get("output_contract", {})
    if (
        manifest.get("asset_id") != ASSET_ID
        or manifest.get("status") != MANIFEST_STATUS
        or manifest.get("pipeline_version") != PIPELINE_VERSION
        or boundary.get("authorization_id") != AUTHORIZATION_ID
        or boundary.get("purpose") != AUTHORIZATION_PURPOSE
        or boundary.get("authorized_arm") != AUTHORIZED_ARM
        or boundary.get("dependency_asset_id") != DEPENDENCY_ASSET_ID
        or boundary.get("start") != str(SOURCE_START.date())
        or boundary.get("end") != str(SIGNAL_END.date())
        or any(boundary.get(key) is not True for key in required_true)
        or any(boundary.get(key) is not False for key in required_false)
        or boundary.get("signal_start") != str(SIGNAL_START.date())
        or boundary.get("signal_end") != str(SIGNAL_END.date())
        or boundary.get("maximum_chart_date") != str(SIGNAL_END.date())
        or boundary.get("frozen_candidate_rows") != EXPECTED_EVENTS
        or boundary.get("phase1_relative_global_sessions") != [-WINDOW, 0]
        or cohort.get("path") != str(CANDIDATES)
        or cohort.get("sha256") != ALLOWED_DATA_HASHES[CANDIDATES]
        or cohort.get("rows") != EXPECTED_EVENTS
        or cohort.get("annual_rows") != {"2019": 249, "2020": 282}
        or stage_b_boundary.get("stage_b_artifacts_exist") is not False
        or stage_b_boundary.get("any_stage_b_path_declared") is not False
        or stage_b_boundary.get(
            "any_stage_b_artifact_may_be_statted_hashed_opened_or_parsed"
        )
        is not False
        or protocol.get("visual_review_spec_sha256")
        != actual["visual_review_spec"]
        or protocol.get("visual_review_spec_path") != str(REVIEW_SPEC)
        or protocol.get("chart_runner_sha256") != actual["chart_runner"]
        or protocol.get("chart_runner_path") != str(Path(__file__).resolve())
        or protocol.get("annotation_schema_sha256")
        != actual["annotation_schema"]
        or protocol.get("annotation_schema_path") != str(ANNOTATION_SCHEMA)
        or manifest_output.get("canonical_directory") != str(CHART_ROOT)
        or manifest_output.get("individual_anonymous_charts") != EXPECTED_EVENTS
        or manifest_output.get("chart_size_pixels") != list(CHART_SIZE)
        or manifest_output.get("anonymous_contact_sheets") != EXPECTED_SHEETS
        or manifest_output.get("contact_sheet_grid")
        != [GRID_COLUMNS, GRID_ROWS]
    ):
        raise ResearchError("CY-055 chart manifest binding drift")
    _verify_role_bindings(
        manifest.get("source_artifacts", []),
        SOURCE_ROLE_BINDINGS,
        "CY-055 manifest source_artifacts",
    )
    return actual, authorization


def _require_bound_role(
    artifacts: dict[str, dict[str, Any]], role: str, path: Path, digest: str
) -> None:
    item = artifacts.get(role)
    if item is None or item.get("path") != str(path) or item.get("sha256") != digest:
        raise ResearchError(f"CY-055 authorization does not bind {role}")


def verify_allowed_bound_inputs(
    preflight: dict[str, str], authorization: dict[str, Any]
) -> dict[str, str]:
    """After joint authorization, hash only the exact permitted inputs."""
    artifacts = role_map(authorization.get("bound_artifacts", []), "bound_artifacts")
    expected_roles = {*PUBLIC_ROLE_BINDINGS, *SOURCE_ROLE_BINDINGS}
    if set(artifacts) != expected_roles:
        raise ResearchError("CY-055 bound_artifacts changed after public preflight")
    actual = dict(preflight)
    for role, (path, expected) in PUBLIC_ROLE_BINDINGS.items():
        if not path.is_file() or sha256(path) != expected:
            raise ResearchError(f"frozen public input drift: {role}")
        _require_bound_role(artifacts, role, path, expected)
        actual[role] = expected
    for role, (path, expected) in SOURCE_ROLE_BINDINGS.items():
        if not path.is_file():
            raise ResearchError(f"missing permitted input {role}: {path}")
        value = sha256(path)
        if value != expected:
            raise ResearchError(f"permitted input drift: {role}")
        _require_bound_role(artifacts, role, path, value)
        actual[role] = value
    return actual


def require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ResearchError(f"{label} missing columns: {missing}")


def load_and_audit_candidates() -> pd.DataFrame:
    stage_a = load_json(STAGE_A_RESULT, "outcome-blind V36 Stage-A result")
    if (
        stage_a.get("experiment") != EXPERIMENT
        or stage_a.get("status")
        != "PASSED_OUTCOME_BLIND_STAGE_A_STAGE_B_NOT_AUTHORIZED"
        or stage_a.get("candidate_rows") != EXPECTED_EVENTS
        or stage_a.get("candidate_annual_counts") != {"2019": 249, "2020": 282}
        or stage_a.get("candidates_sha256") != ALLOWED_DATA_HASHES[CANDIDATES]
        or stage_a.get("stage_a_gate_passed") is not True
        or stage_a.get("stage_b_authorized") is not False
        or stage_a.get("outcome_columns_read") is not False
        or stage_a.get("post_signal_rows_read") is not False
        or stage_a.get("post_2020_rows_read") is not False
        or stage_a.get("2021_plus_rows_read") is not False
    ):
        raise ResearchError("outcome-blind V36 Stage-A receipt drift")

    columns = [
        "event_id",
        "symbol",
        "signal_date",
        "signal_cal_idx",
        "causal_industry",
        "decision_at",
        "available_at",
        "selection_rank",
    ]
    candidates = pd.read_parquet(CANDIDATES, columns=columns)
    require_columns(candidates, set(columns), "Stage-A frozen candidates")
    candidates["event_id"] = candidates.event_id.astype(str)
    candidates["symbol"] = candidates.symbol.astype(str)
    candidates["causal_industry"] = candidates.causal_industry.astype(str)
    for column in ("signal_date", "decision_at", "available_at"):
        candidates[column] = pd.to_datetime(candidates[column])
    annual = {
        int(year): int(count)
        for year, count in candidates.signal_date.dt.year.value_counts().items()
    }
    expected_ids = (
        "BROAD_MARKET_PRICE_DELAY|"
        + candidates.signal_date.dt.strftime("%Y%m%d")
        + "|"
        + candidates.causal_industry
        + "|"
        + candidates.symbol
    )
    numeric = candidates[["signal_cal_idx", "selection_rank"]].apply(
        pd.to_numeric, errors="coerce"
    )
    required_nonempty = candidates[["symbol", "causal_industry"]].apply(
        lambda values: values.str.strip().ne("")
    )
    if (
        len(candidates) != EXPECTED_EVENTS
        or candidates.event_id.duplicated().any()
        or candidates.duplicated(["symbol", "signal_date"]).any()
        or candidates[list(set(columns) - {"event_id"})].isna().any(axis=1).any()
        or not np.isfinite(numeric).all(axis=None)
        or not required_nonempty.all(axis=None)
        or not candidates.event_id.eq(expected_ids).all()
        or not candidates.selection_rank.eq(1).all()
        or candidates.signal_date.min() != SIGNAL_START
        or candidates.signal_date.max() != SIGNAL_END
        or annual != EXPECTED_ANNUAL
        or candidates.available_at.gt(candidates.decision_at).any()
        or candidates.signal_date.dt.year.gt(2020).any()
    ):
        raise ResearchError("frozen Stage-A candidate identity or chronology drift")
    return candidates.rename(columns={"signal_cal_idx": "source_signal_cal_idx"})


def _raw_paths_sql() -> str:
    return "[" + ",".join(f"'{path.as_posix()}'" for path in CY006_PARTITIONS) + "]"


def load_causal_windows(candidates: pd.DataFrame) -> pd.DataFrame:
    """Build exact per-event global -126..0 windows; select no later row."""
    chart_keys = candidates[
        ["event_id", "symbol", "signal_date", "decision_at"]
    ].rename(columns={"decision_at": "signal_decision_at"})
    connection = duckdb.connect()
    connection.execute("SET threads=4")
    connection.register("chart_keys", chart_keys)
    snapshots = ",".join(f"d.{column}" for column in SNAPSHOT_COLUMNS)
    snapshot_validity = " AND ".join(
        f"{column} IS NOT NULL AND length(trim(CAST({column} AS VARCHAR)))>0"
        for column in SNAPSHOT_COLUMNS
    )
    windows = connection.execute(
        f"""
        WITH calendar_pairs AS (
          SELECT trade_date,cal_idx
          FROM read_parquet('{COORDINATE_STATE.as_posix()}')
          WHERE trade_date BETWEEN DATE '{SOURCE_START.date()}'
                               AND DATE '{SIGNAL_END.date()}'
          GROUP BY trade_date,cal_idx
        ), calendar AS (
          SELECT *,count(*) OVER(PARTITION BY trade_date) AS date_cal_idx_versions,
            count(*) OVER(PARTITION BY cal_idx) AS cal_idx_date_versions
          FROM calendar_pairs
        ), signal_anchors AS (
          SELECT k.event_id,k.symbol,k.signal_date,k.signal_decision_at,
            c.cal_idx AS signal_global_cal_idx,
            c.invalid_step_cum AS signal_invalid_step_cum
          FROM chart_keys k
          JOIN read_parquet('{COORDINATE_STATE.as_posix()}') c
            ON c.symbol=k.symbol AND c.trade_date=k.signal_date
          WHERE c.trade_date BETWEEN DATE '{SOURCE_START.date()}'
                                 AND DATE '{SIGNAL_END.date()}'
        ), bounds AS (
          SELECT min(signal_global_cal_idx)-{WINDOW} AS first_idx,
                 max(signal_global_cal_idx) AS last_idx
          FROM signal_anchors
        ), expanded AS (
          SELECT k.event_id,k.symbol,k.signal_date,k.signal_decision_at,
            k.signal_global_cal_idx,k.signal_invalid_step_cum,
            c.trade_date,c.cal_idx,
            c.cal_idx-k.signal_global_cal_idx AS relative_session,
            c.date_cal_idx_versions,c.cal_idx_date_versions
          FROM signal_anchors k
          JOIN calendar c
            ON c.cal_idx BETWEEN k.signal_global_cal_idx-{WINDOW}
                             AND k.signal_global_cal_idx
        ), raw AS (
          SELECT d.trade_date,d.symbol,d.open,d.high,d.low,d.close,
            d.turnover_fraction,d.is_st,d.trade_status,
            d.current_day_data_tradable,d.hard_valid,d.bar_valid,
            d.trading_state_valid,d.market_valid,d.market_rule_valid,
            d.corporate_action_count,d.corporate_action_valid,
            d.corporate_action_blocking,d.historical_identity_valid,
            d.industry_valid,d.float_valid,d.available_at,
            d.decision_at AS bar_decision_at,{snapshots}
          FROM read_parquet({_raw_paths_sql()},union_by_name=true) d
          JOIN calendar k USING(trade_date),bounds b
          WHERE d.trade_date BETWEEN DATE '{SOURCE_START.date()}'
                                 AND DATE '{SIGNAL_END.date()}'
            AND k.cal_idx BETWEEN b.first_idx AND b.last_idx
            AND ((d.symbol LIKE '60%.SH' AND d.symbol NOT LIKE '688%.SH')
                 OR d.symbol LIKE '00%.SZ' OR d.symbol LIKE '30%.SZ')
        ), coord AS (
          SELECT c.trade_date,c.cal_idx,c.symbol,c.low AS coordinate_raw_low,
            c.close AS coordinate_raw_close,c.adjusted_close,c.invalid_step_cum,
            c.current_valid AS coordinate_current_valid,
            c.history_valid AS coordinate_history_valid,
            c.corporate_action_count AS coordinate_action_count,
            c.corporate_action_valid AS coordinate_action_valid,
            c.corporate_action_blocking AS coordinate_action_blocking
          FROM read_parquet('{COORDINATE_STATE.as_posix()}') c,bounds b
          WHERE c.cal_idx BETWEEN b.first_idx AND b.last_idx
            AND c.trade_date BETWEEN DATE '{SOURCE_START.date()}'
                                 AND DATE '{SIGNAL_END.date()}'
        ), joined AS (
          SELECT r.*,c.cal_idx,c.coordinate_raw_low,c.coordinate_raw_close,
            c.adjusted_close,c.invalid_step_cum,c.coordinate_current_valid,
            c.coordinate_history_valid,c.coordinate_action_count,
            c.coordinate_action_valid,c.coordinate_action_blocking,
            c.adjusted_close/r.close AS coordinate_factor,
            c.adjusted_close*(r.open/r.close) AS coord_open,
            c.adjusted_close*(r.high/r.close) AS coord_high,
            c.adjusted_close*(r.low/r.close) AS coord_low,
            c.adjusted_close AS coord_close,
            (c.symbol IS NOT NULL
             AND r.close IS NOT DISTINCT FROM c.coordinate_raw_close
             AND r.low IS NOT DISTINCT FROM c.coordinate_raw_low
             AND r.corporate_action_count IS NOT DISTINCT FROM c.coordinate_action_count)
              AS source_identity_match
          FROM raw r LEFT JOIN coord c USING(symbol,trade_date)
        ), source_audit AS (
          SELECT count(*) AS raw_source_rows,
            count(*) FILTER(WHERE cal_idx IS NULL) AS raw_rows_missing_coordinate,
            count(*) FILTER(
              WHERE cal_idx IS NOT NULL AND source_identity_match IS NOT TRUE
            ) AS raw_coordinate_identity_mismatches
          FROM joined
        ), market_lagged AS (
          SELECT j.*,
            lag(cal_idx) OVER w AS prior_cal_idx,
            lag(adjusted_close) OVER w AS prior_adjusted_close,
            lag(invalid_step_cum) OVER w AS prior_invalid_step_cum,
            lag(coordinate_history_valid) OVER w AS prior_coordinate_history_valid
          FROM joined j WINDOW w AS(PARTITION BY symbol ORDER BY cal_idx)
        ), market_members AS (
          SELECT m.*,
            CASE WHEN m.cal_idx=b.first_idx THEN 0.0
                 WHEN m.prior_cal_idx=m.cal_idx-1
                  AND m.prior_adjusted_close>0
                  AND m.coordinate_history_valid
                  AND m.prior_coordinate_history_valid
                  AND m.invalid_step_cum=m.prior_invalid_step_cum
                 THEN m.adjusted_close/m.prior_adjusted_close-1 END AS step_return
          FROM market_lagged m,bounds b
        ), market AS (
          SELECT trade_date,cal_idx,median(step_return) AS market_step_return,
            count(*) AS market_member_rows,
            count(DISTINCT symbol) AS market_member_symbols,
            max(available_at) AS market_latest_available_at,
            max(bar_decision_at) AS market_latest_decision_at
          FROM market_members
          WHERE coordinate_current_valid AND coordinate_history_valid
            AND hard_valid AND bar_valid AND trading_state_valid AND market_valid
            AND current_day_data_tradable AND trade_status=1
            AND market_rule_valid AND corporate_action_valid
            AND NOT corporate_action_blocking
            AND coordinate_action_valid AND NOT coordinate_action_blocking
            AND historical_identity_valid AND industry_valid AND NOT is_st
            AND source_identity_match AND available_at<=bar_decision_at
            AND {snapshot_validity}
            AND isfinite(step_return) AND step_return>-1
          GROUP BY trade_date,cal_idx
        )
        SELECT e.event_id,e.symbol,e.signal_date,e.signal_decision_at,
          e.signal_global_cal_idx,e.signal_invalid_step_cum,
          e.trade_date,e.cal_idx,e.relative_session,e.date_cal_idx_versions,
          e.cal_idx_date_versions,s.raw_open,s.raw_high,s.raw_low,s.raw_close,
          s.coord_open,s.coord_high,s.coord_low,s.coord_close,
          s.coordinate_factor,s.turnover_fraction,s.invalid_step_cum,
          s.raw_is_st,s.raw_hard_valid,s.raw_bar_valid,
          s.raw_trading_state_valid,s.raw_market_valid,
          s.raw_current_day_data_tradable,s.coordinate_current_valid,
          s.coordinate_history_valid,s.raw_trade_status,s.raw_market_rule_valid,
          s.raw_corporate_action_count,s.raw_corporate_action_valid,
          s.raw_corporate_action_blocking,s.coordinate_action_count,
          s.coordinate_action_valid,s.coordinate_action_blocking,
          s.raw_historical_identity_valid,s.raw_industry_valid,s.raw_float_valid,
          s.source_identity_match,s.available_at,s.bar_decision_at,
          s.snapshot_id,s.daily_snapshot_id,s.trading_state_snapshot_id,
          s.industry_snapshot_id,s.float_snapshot_id,
          s.corporate_action_snapshot_id,s.market_snapshot_id,
          m.market_step_return,m.market_member_rows,m.market_member_symbols,
          m.market_latest_available_at,m.market_latest_decision_at,
          a.raw_source_rows,a.raw_rows_missing_coordinate,
          a.raw_coordinate_identity_mismatches
        FROM expanded e
        LEFT JOIN (
          SELECT symbol,trade_date,cal_idx,open AS raw_open,high AS raw_high,
            low AS raw_low,close AS raw_close,
            coord_open,coord_high,coord_low,coord_close,
            coordinate_factor,turnover_fraction,invalid_step_cum,is_st AS raw_is_st,
            hard_valid AS raw_hard_valid,bar_valid AS raw_bar_valid,
            trading_state_valid AS raw_trading_state_valid,
            market_valid AS raw_market_valid,
            current_day_data_tradable AS raw_current_day_data_tradable,
            coordinate_current_valid,coordinate_history_valid,
            trade_status AS raw_trade_status,market_rule_valid AS raw_market_rule_valid,
            corporate_action_count AS raw_corporate_action_count,
            corporate_action_valid AS raw_corporate_action_valid,
            corporate_action_blocking AS raw_corporate_action_blocking,
            coordinate_action_count,coordinate_action_valid,
            coordinate_action_blocking,
            historical_identity_valid AS raw_historical_identity_valid,
            industry_valid AS raw_industry_valid,float_valid AS raw_float_valid,
            source_identity_match,available_at,bar_decision_at,
            snapshot_id,daily_snapshot_id,trading_state_snapshot_id,
            industry_snapshot_id,float_snapshot_id,
            corporate_action_snapshot_id,market_snapshot_id
          FROM joined
        ) s ON s.symbol=e.symbol AND s.trade_date=e.trade_date AND s.cal_idx=e.cal_idx
        LEFT JOIN market m
          ON m.trade_date=e.trade_date AND m.cal_idx=e.cal_idx
        CROSS JOIN source_audit a
        ORDER BY e.event_id,e.cal_idx
        """
    ).fetch_df()
    connection.close()
    for column in (
        "signal_date",
        "signal_decision_at",
        "trade_date",
        "available_at",
        "bar_decision_at",
        "market_latest_available_at",
        "market_latest_decision_at",
    ):
        windows[column] = pd.to_datetime(windows[column])

    counts = windows.groupby("event_id", sort=False).agg(
        rows=("cal_idx", "size"),
        first=("relative_session", "min"),
        last=("relative_session", "max"),
    )
    market_numeric = windows[["market_step_return", "market_member_rows"]].apply(
        pd.to_numeric, errors="coerce"
    )
    if (
        len(counts) != EXPECTED_EVENTS
        or not counts.rows.eq(WINDOW_ROWS).all()
        or not counts["first"].eq(-WINDOW).all()
        or not counts["last"].eq(0).all()
        or windows.duplicated(["event_id", "cal_idx"]).any()
        or windows.relative_session.gt(0).any()
        or windows.trade_date.gt(windows.signal_date).any()
        or windows.trade_date.max() > SIGNAL_END
        or windows.trade_date.min() < SOURCE_START
        or not windows.date_cal_idx_versions.eq(1).all()
        or not windows.cal_idx_date_versions.eq(1).all()
        or not windows.raw_rows_missing_coordinate.eq(0).all()
        or not windows.raw_coordinate_identity_mismatches.eq(0).all()
        or not np.isfinite(market_numeric).all(axis=None)
        or market_numeric.market_step_return.le(-1).any()
        or market_numeric.market_member_rows.lt(MIN_MARKET_MEMBERS).any()
        or not windows.market_member_rows.eq(windows.market_member_symbols).all()
        or windows.market_latest_available_at.isna().any()
        or windows.market_latest_decision_at.isna().any()
        or windows.market_latest_available_at.gt(windows.signal_decision_at).any()
        or windows.market_latest_decision_at.gt(windows.signal_decision_at).any()
    ):
        raise ResearchError("global causal window or broad-market line audit failed")

    signal = valid_bars(windows).loc[lambda frame: frame.relative_session.eq(0)]
    if (
        len(signal) != EXPECTED_EVENTS
        or signal.event_id.duplicated().any()
        or not signal.trade_date.eq(signal.signal_date).all()
        or not signal.cal_idx.eq(signal.signal_global_cal_idx).all()
        or signal.raw_is_st.fillna(True).any()
        or not signal.raw_float_valid.fillna(False).all()
    ):
        raise ResearchError("one exact valid V36 signal bar is not present")

    windows["market_level"] = windows.groupby("event_id", sort=False)[
        "market_step_return"
    ].transform(lambda values: (1.0 + values.astype(float)).cumprod())
    first = windows.groupby("event_id", sort=False).market_level.transform("first")
    windows["market_level"] = 100.0 * windows.market_level / first
    if (
        not np.isfinite(windows.market_level).all()
        or windows.groupby("event_id", sort=False)
        .market_level.first()
        .sub(100.0)
        .abs()
        .gt(1e-10)
        .any()
    ):
        raise ResearchError("causal broad-market accumulation failed")
    return windows


def _nonblank_snapshots(frame: pd.DataFrame) -> pd.Series:
    return frame[list(SNAPSHOT_COLUMNS)].notna().all(axis=1) & frame[
        list(SNAPSHOT_COLUMNS)
    ].astype(str).apply(lambda values: values.str.strip().ne("")).all(axis=1)


def valid_bars(frame: pd.DataFrame) -> pd.DataFrame:
    raw = frame[["raw_open", "raw_high", "raw_low", "raw_close"]].apply(
        pd.to_numeric, errors="coerce"
    )
    adjusted = frame[["coord_open", "coord_high", "coord_low", "coord_close"]].apply(
        pd.to_numeric, errors="coerce"
    )
    factor = pd.to_numeric(frame.coordinate_factor, errors="coerce")
    mask = (
        frame.relative_session.between(-WINDOW, 0)
        & frame.trade_date.le(frame.signal_date)
        & frame.coordinate_current_valid.fillna(False)
        & frame.coordinate_history_valid.fillna(False)
        & frame.raw_hard_valid.fillna(False)
        & frame.raw_bar_valid.fillna(False)
        & frame.raw_trading_state_valid.fillna(False)
        & frame.raw_market_valid.fillna(False)
        & frame.raw_current_day_data_tradable.fillna(False)
        & frame.raw_trade_status.eq(1)
        & frame.raw_market_rule_valid.fillna(False)
        & frame.raw_corporate_action_valid.fillna(False)
        & ~frame.raw_corporate_action_blocking.fillna(True)
        & frame.coordinate_action_valid.fillna(False)
        & ~frame.coordinate_action_blocking.fillna(True)
        & frame.raw_historical_identity_valid.fillna(False)
        & frame.raw_industry_valid.fillna(False)
        & frame.source_identity_match.fillna(False)
        & frame.invalid_step_cum.eq(frame.signal_invalid_step_cum)
        & frame.available_at.notna()
        & frame.bar_decision_at.notna()
        & frame.available_at.le(frame.bar_decision_at)
        & frame.available_at.le(frame.signal_decision_at)
        & frame.bar_decision_at.le(frame.signal_decision_at)
        & _nonblank_snapshots(frame)
        & np.isfinite(raw).all(axis=1)
        & raw.gt(0).all(axis=1)
        & raw.raw_high.ge(raw[["raw_open", "raw_close", "raw_low"]].max(axis=1))
        & raw.raw_low.le(raw[["raw_open", "raw_close", "raw_high"]].min(axis=1))
        & np.isfinite(adjusted).all(axis=1)
        & adjusted.gt(0).all(axis=1)
        & np.isfinite(factor)
        & factor.gt(0)
        & adjusted.coord_high.ge(
            adjusted[["coord_open", "coord_close", "coord_low"]].max(axis=1)
        )
        & adjusted.coord_low.le(
            adjusted[["coord_open", "coord_close", "coord_high"]].min(axis=1)
        )
    )
    return frame.loc[mask].sort_values("cal_idx", kind="mergesort")


def source_coverage_receipt(
    candidates: pd.DataFrame, windows: pd.DataFrame
) -> dict[str, Any]:
    """Return aggregate coverage only; never persist an identity map."""
    bars = valid_bars(windows)
    per_event = bars.groupby("event_id", sort=False).size()
    signal = bars.loc[bars.relative_session.eq(0)]
    if (
        len(candidates) != EXPECTED_EVENTS
        or len(windows) != EXPECTED_EVENTS * WINDOW_ROWS
        or len(per_event) != EXPECTED_EVENTS
        or len(signal) != EXPECTED_EVENTS
        or signal.event_id.duplicated().any()
    ):
        raise ResearchError("source coverage cannot certify every frozen event")
    return {
        "status": "CANONICAL_SOURCE_COVERAGE_PASS",
        "events": EXPECTED_EVENTS,
        "calendar_slots_per_event": WINDOW_ROWS,
        "calendar_slots": len(windows),
        "exact_valid_signal_rows": len(signal),
        "valid_stock_bars": len(bars),
        "missing_or_invalid_stock_slots": int(len(windows) - len(bars)),
        "events_with_all_127_valid_stock_bars": int(per_event.eq(WINDOW_ROWS).sum()),
        "minimum_valid_stock_bars_per_event": int(per_event.min()),
        "maximum_valid_stock_bars_per_event": int(per_event.max()),
        "minimum_source_date": str(pd.Timestamp(windows.trade_date.min()).date()),
        "maximum_source_date": str(pd.Timestamp(windows.trade_date.max()).date()),
        "minimum_market_members": int(windows.market_member_symbols.min()),
        "maximum_market_members": int(windows.market_member_symbols.max()),
        "raw_rows_missing_coordinate": int(windows.raw_rows_missing_coordinate.max()),
        "raw_coordinate_identity_mismatches": int(
            windows.raw_coordinate_identity_mismatches.max()
        ),
        "per_event_post_signal_row_read": False,
        "post_2020_row_read": False,
        "stage_b_artifact_path_declared": False,
        "stage_b_or_outcome_artifact_statted_hashed_opened_or_parsed": False,
        "identity_crosswalk_persisted": False,
    }


def build_in_memory_blind_order(
    candidates: pd.DataFrame, windows: pd.DataFrame
) -> pd.DataFrame:
    ordered = candidates[["event_id"]].copy()
    ordered["_full_digest"] = ordered.event_id.map(
        lambda value: hashlib.sha256(
            f"{OPAQUE_ORDER_SALT}|{value}".encode()
        ).hexdigest()
    )
    ordered["blind_chart_id"] = "B-" + ordered._full_digest.str.slice(0, 20)
    ordered = ordered.sort_values(
        ["_full_digest", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    ordered.insert(0, "chart_number", np.arange(1, len(ordered) + 1, dtype=np.int64))
    if (
        len(ordered) != EXPECTED_EVENTS
        or ordered.event_id.duplicated().any()
        or ordered.blind_chart_id.duplicated().any()
        or ordered.chart_number.tolist() != list(range(1, EXPECTED_EVENTS + 1))
        or set(ordered.event_id) != set(windows.event_id.astype(str))
    ):
        raise ResearchError("opaque order or event coverage drift")
    return ordered


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


def _scale(values: list[float]) -> tuple[float, float]:
    if not values:
        raise ResearchError("cannot scale an empty panel")
    low, high = min(values), max(values)
    if not high > low:
        high = low + max(abs(low) * 0.01, 1e-6)
    pad = (high - low) * 0.04
    return low - pad, high + pad


def _x(relative: int) -> int:
    if relative < -WINDOW or relative > 0:
        raise ResearchError(f"Phase-1 relative session outside [-{WINDOW},0]")
    return int(LEFT_EDGE + (relative + WINDOW) * (RIGHT_EDGE - LEFT_EDGE) / WINDOW)


def _y(value: float, scale: tuple[float, float], top: int, bottom: int) -> int:
    low, high = scale
    return int(bottom - (value - low) * (bottom - top) / (high - low))


def render_chart(
    chart_number: int, blind_chart_id: str, frame: pd.DataFrame, output: Path
) -> None:
    if (
        frame.relative_session.gt(0).any()
        or frame.trade_date.gt(frame.signal_date).any()
        or frame.trade_date.max() > SIGNAL_END
    ):
        raise ResearchError(f"chart {chart_number:05d}: forbidden row reached renderer")
    bars = valid_bars(frame)
    signal = bars.loc[bars.relative_session.eq(0)]
    if bars.empty or len(signal) != 1:
        raise ResearchError(f"chart {chart_number:05d}: signal-time bar missing")

    image = Image.new("RGB", CHART_SIZE, "white")
    draw = ImageDraw.Draw(image)
    font, small = _font(12), _font(10)
    draw.rectangle(
        (LEFT_EDGE, PRICE_TOP, RIGHT_EDGE, PRICE_BOTTOM),
        fill="#eff6ff",
        outline="#9ca3af",
    )
    draw.rectangle(
        (LEFT_EDGE, MARKET_TOP, RIGHT_EDGE, MARKET_BOTTOM),
        fill="#f5f3ff",
        outline="#c4b5fd",
    )
    draw.rectangle(
        (LEFT_EDGE, TURNOVER_TOP, RIGHT_EDGE, TURNOVER_BOTTOM),
        fill="#f9fafb",
        outline="#d1d5db",
    )

    price_scale = _scale(
        list(bars.coord_low.astype(float)) + list(bars.coord_high.astype(float))
    )
    maximum_turnover = max(float(bars.turnover_fraction.fillna(0).max()), 1e-9)
    market = frame.sort_values("cal_idx", kind="mergesort")
    market_scale = _scale(list(market.market_level.astype(float)))
    points = [
        (
            _x(int(row.relative_session)),
            _y(float(row.market_level), market_scale, MARKET_TOP, MARKET_BOTTOM),
        )
        for row in market.itertuples(index=False)
    ]
    if len(points) != WINDOW_ROWS:
        raise ResearchError(f"chart {chart_number:05d}: broad-market line incomplete")
    draw.line(points, fill="#7c3aed", width=2)

    # The marker is drawn before candles and five pixels left of session zero,
    # so the signal candle remains fully visible for its frozen review axis.
    signal_marker_x = _x(0) - 5
    draw.line(
        (signal_marker_x, PRICE_TOP, signal_marker_x, TURNOVER_BOTTOM),
        fill="#b45309",
        width=1,
    )
    for row in bars.itertuples(index=False):
        x = _x(int(row.relative_session))
        open_y = _y(float(row.coord_open), price_scale, PRICE_TOP, PRICE_BOTTOM)
        close_y = _y(float(row.coord_close), price_scale, PRICE_TOP, PRICE_BOTTOM)
        high_y = _y(float(row.coord_high), price_scale, PRICE_TOP, PRICE_BOTTOM)
        low_y = _y(float(row.coord_low), price_scale, PRICE_TOP, PRICE_BOTTOM)
        color = "#dc2626" if float(row.coord_close) >= float(row.coord_open) else "#16803c"
        draw.line((x, high_y, x, low_y), fill=color, width=1)
        body_top, body_bottom = sorted((open_y, close_y))
        draw.rectangle(
            (x - 1, body_top, x + 1, max(body_top + 1, body_bottom)),
            fill=color,
        )
        if pd.notna(row.turnover_fraction):
            height = int(
                float(row.turnover_fraction)
                / maximum_turnover
                * (TURNOVER_BOTTOM - TURNOVER_TOP - 2)
            )
            draw.rectangle(
                (x - 1, TURNOVER_BOTTOM - height, x + 1, TURNOVER_BOTTOM),
                fill="#9ca3af",
            )

    for relative in (-126, -63, 0):
        x = _x(relative)
        draw.text(
            (max(LEFT_EDGE, x - 12), TURNOVER_BOTTOM + 2),
            str(relative),
            fill="#4b5563",
            font=small,
        )
    draw.text(
        (signal_marker_x - 42, PRICE_TOP + 3),
        "SIGNAL",
        fill="#92400e",
        font=small,
    )
    draw.text(
        (LEFT_EDGE + 3, PRICE_TOP + 3),
        "ADJUSTED OHLC | OWN CAUSAL SCALE",
        fill="#1d4ed8",
        font=small,
    )
    draw.text(
        (LEFT_EDGE + 3, MARKET_TOP + 2),
        "BROAD MARKET | SAME-DAY MEDIAN STEP | OWN SCALE",
        fill="#6d28d9",
        font=small,
    )
    draw.text(
        (LEFT_EDGE + 3, TURNOVER_TOP + 2),
        "TURNOVER | OWN CAUSAL SCALE",
        fill="#1d4ed8",
        font=small,
    )
    draw.text(
        (6, 4),
        f"CHART {chart_number:05d} | {blind_chart_id}",
        fill="#111827",
        font=font,
    )
    draw.text(
        (6, 22),
        "OPAQUE ORDER | SECURITY / DATE / YEAR / INDUSTRY / EVENT / SCORE HIDDEN",
        fill="#1e3a8a",
        font=small,
    )
    draw.text(
        (6, 39),
        "GLOBAL SESSIONS -126 THROUGH 0 ONLY | AVAILABLE BY SIGNAL CLOSE",
        fill="#1d4ed8",
        font=small,
    )
    draw.text(
        (6, 56),
        "NO STAGE-B PATH, OUTCOME ARTIFACT, OR POST-SIGNAL ROW READ",
        fill="#1d4ed8",
        font=small,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=False)


def render_worker(payload: tuple[int, str, pd.DataFrame, str]) -> dict[str, Any]:
    chart_number, blind_chart_id, frame, output_text = payload
    output = Path(output_text)
    render_chart(chart_number, blind_chart_id, frame, output)
    return {
        "chart_number": chart_number,
        "blind_chart_id": blind_chart_id,
        "chart_path": str(output),
        "chart_sha256": sha256(output),
    }


def build_contact_sheets(
    chart_index: pd.DataFrame, output_dir: Path
) -> tuple[list[Path], list[dict[str, Any]]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ordered = chart_index.sort_values("chart_number", kind="mergesort").reset_index(
        drop=True
    )
    page_size = GRID_COLUMNS * GRID_ROWS
    sheets: list[Path] = []
    placements: list[dict[str, Any]] = []
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
            f"V36 PHASE-1 ANONYMOUS | PAGE {page:04d} | "
            f"CHARTS {start + 1}-{start + len(part)}",
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
                    "sheet_number": page,
                    "slot": slot,
                    "chart_number": int(row.chart_number),
                    "blind_chart_id": str(row.blind_chart_id),
                }
            )
        sheet.save(target, format="JPEG", quality=87, optimize=False)
        sheets.append(target)
    return sheets, placements


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )


def run(workers: int) -> dict[str, Any]:
    preflight, authorization = verify_public_authorization()
    if CHART_ROOT.exists():
        raise ResearchError(f"canonical Phase-1 directory already exists: {CHART_ROOT}")
    source_hashes = verify_allowed_bound_inputs(preflight, authorization)
    candidates = load_and_audit_candidates()
    windows = load_causal_windows(candidates)
    coverage = source_coverage_receipt(candidates, windows)
    blind_order = build_in_memory_blind_order(candidates, windows)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".v36_phase1.staging.", dir=OUTPUT_ROOT))
    try:
        chart_dir = staging / "individual_anonymous_charts"
        lookup = {
            str(event_id): part
            for event_id, part in windows.groupby("event_id", sort=False)
        }
        tasks = [
            (
                int(event.chart_number),
                str(event.blind_chart_id),
                lookup[str(event.event_id)],
                str(chart_dir / f"{event.blind_chart_id}.png"),
            )
            for event in blind_order.itertuples(index=False)
        ]
        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            chart_index = pd.DataFrame(executor.map(render_worker, tasks))
        chart_index = chart_index.sort_values("chart_number", kind="mergesort")
        if (
            len(chart_index) != EXPECTED_EVENTS
            or chart_index.chart_number.duplicated().any()
            or chart_index.blind_chart_id.duplicated().any()
            or len(list(chart_dir.glob("*.png"))) != EXPECTED_EVENTS
        ):
            raise ResearchError("individual anonymous chart coverage drift")

        sheets, placement_rows = build_contact_sheets(
            chart_index, staging / "anonymous_contact_sheets"
        )
        placements = pd.DataFrame(placement_rows).sort_values(
            ["sheet_number", "slot"], kind="mergesort"
        )
        if (
            len(placements) != EXPECTED_EVENTS
            or placements.chart_number.duplicated().any()
            or placements.blind_chart_id.duplicated().any()
            or len(sheets) != EXPECTED_SHEETS
        ):
            raise ResearchError("anonymous contact-sheet coverage drift")

        chart_index["blind_chart_path"] = chart_index.chart_path.map(
            lambda value: str(Path(value).relative_to(staging))
        )
        chart_index = chart_index.rename(
            columns={"chart_sha256": "blind_chart_sha256"}
        )
        blind_index = chart_index.merge(
            placements,
            on=["chart_number", "blind_chart_id"],
            how="inner",
            validate="one_to_one",
        )[
            [
                "chart_number",
                "blind_chart_id",
                "blind_chart_path",
                "blind_chart_sha256",
                "sheet_number",
                "slot",
            ]
        ].sort_values("chart_number", kind="mergesort")
        blind_index.to_csv(staging / "blind_index.csv", index=False)
        placements.to_csv(staging / "contact_sheet_placements.csv", index=False)
        sheet_index = pd.DataFrame(
            [
                {
                    "sheet_number": number,
                    "sheet_path": str(path.relative_to(staging)),
                    "sheet_sha256": sha256(path),
                }
                for number, path in enumerate(sheets, start=1)
            ]
        )
        sheet_index.to_csv(staging / "contact_sheet_index.csv", index=False)
        review_template = [
            {
                "chart_number": int(number),
                "primary_morphology": "",
                "market_tape": "",
                "signal_candle": "",
                "turnover_state": "",
                "evidence": "",
                "reviewer": "",
            }
            for number in blind_index.chart_number
        ]
        write_json(staging / "phase1_review_template.json", review_template)

        if verify_allowed_bound_inputs(*verify_public_authorization()) != source_hashes:
            raise ResearchError("a bound input changed during chart construction")
        blind_order_digest = hashlib.sha256(
            "\n".join(blind_order.blind_chart_id.astype(str)).encode("utf-8")
        ).hexdigest()
        producer_manifest = {
            "experiment": EXPERIMENT,
            "stage": "PHASE1_ANONYMOUS_CAUSAL_VISUAL_REVIEW_CORPUS",
            "asset_id": ASSET_ID,
            "authorization_id": AUTHORIZATION_ID,
            "authorized_arm": AUTHORIZED_ARM,
            "pipeline_version": PIPELINE_VERSION,
            "source_hashes": source_hashes,
            "canonical_source_coverage": coverage,
            "events": EXPECTED_EVENTS,
            "individual_anonymous_charts": EXPECTED_EVENTS,
            "anonymous_contact_sheets": EXPECTED_SHEETS,
            "chart_size_pixels": [CHART_SIZE[0], CHART_SIZE[1]],
            "contact_sheet_grid": [GRID_COLUMNS, GRID_ROWS],
            "phase1_window_relative_global_sessions": [-WINDOW, 0],
            "window_slots_per_event": WINDOW_ROWS,
            "maximum_source_date": str(windows.trade_date.max().date()),
            "opaque_order_algorithm": (
                "SHA256(UTF8(salt + '|' + exact event_id)); ascending full digest, "
                "then exact event_id only as collision tie-break"
            ),
            "blind_chart_id_algorithm": "'B-' plus first 20 lowercase digest hex",
            "opaque_order_salt": OPAQUE_ORDER_SALT,
            "blind_order_sha256": blind_order_digest,
            "blind_index_sha256": sha256(staging / "blind_index.csv"),
            "contact_sheet_placements_sha256": sha256(
                staging / "contact_sheet_placements.csv"
            ),
            "contact_sheet_index_sha256": sha256(
                staging / "contact_sheet_index.csv"
            ),
            "phase1_review_template_sha256": sha256(
                staging / "phase1_review_template.json"
            ),
            "annotation_schema_sha256": REPO_FIXED_HASHES[ANNOTATION_SCHEMA],
            "market_line_definition": (
                "all-industry historical Main-plus-ChiNext per global date median "
                "current eligible adjusted-coordinate step return known by that "
                "close; each event compounds only -126..0 and rebases to 100"
            ),
            "ratio_first_adjusted_ohlc": True,
            "raw_ohlc_geometry_strict": True,
            "adjusted_price_scale_is_per_chart": True,
            "market_scale_is_per_chart_and_independent": True,
            "turnover_scale_is_per_chart": True,
            "anonymous_identity_coverage_exactly_once": True,
            "contact_sheet_coverage_exactly_once": True,
            "identity_crosswalk_persisted": False,
            "stage_b_artifact_path_declared": False,
            "stage_b_artifact_statted_hashed_opened_or_parsed": False,
            "outcome_artifact_statted_hashed_opened_or_parsed": False,
            "post_signal_row_read": False,
            "post_2020_row_read": False,
            "full_chart_generated": False,
            "identity_exposed_to_reviewer": False,
            "identity_mapping_persisted": False,
            "outcome_grouping_performed": False,
            "rule_aggregation_performed": False,
            "portfolio_replay_performed": False,
            "candidate_reselection_performed": False,
            "next_step": (
                "REVIEW_EVERY_ANONYMOUS_CHART_AND_FREEZE_THE_COMPLETE_LEDGER_"
                "BEFORE_ANY_SEPARATE_OUTCOME_CONTRACT_IS_CREATED"
            ),
        }
        write_json(staging / "manifest.json", producer_manifest)
        if CHART_ROOT.exists():
            raise ResearchError(f"canonical Phase-1 directory appeared: {CHART_ROOT}")
        staging.replace(CHART_ROOT)
        return producer_manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--verify-public-inputs",
        action="store_true",
        help="Verify only public registry/spec/manifest/runner bindings.",
    )
    mode.add_argument(
        "--verify-source-coverage",
        action="store_true",
        help=(
            "After CY-055 authorization, hash only permitted sources and certify "
            "aggregate -126..0 coverage without rendering or identity persistence."
        ),
    )
    mode.add_argument("--run", action="store_true", help="Build the immutable corpus.")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.verify_public_inputs:
        hashes, _ = verify_public_authorization()
        print(
            json.dumps(
                {"verified": True, "public_hashes": hashes},
                indent=2,
                sort_keys=True,
            )
        )
        return
    if args.verify_source_coverage:
        preflight, authorization = verify_public_authorization()
        source_hashes = verify_allowed_bound_inputs(preflight, authorization)
        candidates = load_and_audit_candidates()
        windows = load_causal_windows(candidates)
        receipt = source_coverage_receipt(candidates, windows)
        if verify_allowed_bound_inputs(*verify_public_authorization()) != source_hashes:
            raise ResearchError("a bound input changed during coverage preflight")
        print(
            json.dumps(
                {
                    "verified": True,
                    "source_hashes": source_hashes,
                    "coverage": receipt,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return
    print(json.dumps(run(args.workers), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
