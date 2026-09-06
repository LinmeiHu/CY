#!/usr/bin/env python3
"""Render the separately authorized anonymous V32 Phase-2 chart corpus.

There are deliberately two entry modes:

``--verify-public-inputs`` validates only the frozen Phase-1/public lineage and
reconstructs the opaque order in memory.  It must never stat, hash, or parse a
Stage-B result, future-path, or outcome file.

``--run`` first performs that same public validation, then requires the exact
CY-044 Phase-2 authorization before it touches any outcome-bearing artifact.
It renders anonymous attribution charts only; no rule is aggregated or tested.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

EXPERIMENT = "ASHARE-STOCK-INDUSTRY-TURNOVER-INNOVATION-DECOUPLING-MOTHER-V32"
REPO = Path(__file__).resolve().parents[3]
EXP = REPO / "research/market_behavior_os_v2/experiments"

PARENT_SPEC = EXP / f"{EXPERIMENT}_freeze.json"
STAGE_B_SPEC = EXP / f"{EXPERIMENT}_stage_b_freeze.json"
PHASE1_SPEC = EXP / f"{EXPERIMENT}_visual_review_spec.json"
PHASE2_SPEC = EXP / f"{EXPERIMENT}_phase2_visual_attribution_freeze.json"
PHASE1_SCHEMA = EXP / "ASHARE-V32_phase1_anonymous_annotation_schema.json"
PHASE1_REVIEWER_DRIFT_FREEZE = EXP / "ASHARE-V32_phase1_reviewer_drift_freeze.json"
PHASE2_ANNOTATION_SCHEMA = EXP / "ASHARE-V32_phase2_post_path_annotation_schema.json"
CY042_MANIFEST = EXP / "ASHARE-V32-CY042_DATA_ASSET_MANIFEST.json"
CY043_MANIFEST = EXP / "ASHARE-V32-CY043_CHART_REVIEW_ASSET_MANIFEST.json"
CY044_MANIFEST = EXP / "ASHARE-V32-CY044_PHASE2_CHART_ATTRIBUTION_ASSET_MANIFEST.json"
REGISTRY = REPO / "configs/data_asset_registry.json"

STAGE_A_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_stock_industry_turnover_innovation_decoupling_mother_v32_stage_a.py"
)
STAGE_B_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_stock_industry_turnover_innovation_decoupling_mother_v32_stage_b.py"
)
PHASE1_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_stock_industry_turnover_innovation_decoupling_mother_v32_charts.py"
)
PHASE1_FINALIZER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "finalize_ashare_stock_industry_turnover_innovation_decoupling_mother_v32_phase1.py"
)
COORDINATE_BUILDER = REPO / (
    "research/market_behavior_os_v2/scripts/run_ashare_former_leader_strict_gap_reclaim_v3.py"
)

CY006_MANIFEST = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "CY-006-pit-b-daily-v2-2018-2026-20260821.json"
)
CY006_ROOT = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily")
PARTITIONS = tuple(
    CY006_ROOT / f"partition_year={year}/data_0.parquet" for year in range(2018, 2021)
)
COORDINATE_STATE = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_adjusted_daily_state_2013_2023.parquet"
)

OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_stock_industry_turnover_innovation_decoupling_mother_v32"
)
STAGE_A = OUTPUT_ROOT / "stage_a"
STAGE_B = OUTPUT_ROOT / "stage_b"
STAGE_A_RESULT = STAGE_A / "result.json"
REPRESENTATION = STAGE_A / "representation_panel.parquet"
CANDIDATES = STAGE_A / "candidates_frozen.parquet"
PREPARED = STAGE_B / "prepared_candidates.parquet"
STAGE_B_RESULT = STAGE_B / "result.json"
FUTURE_PATHS = STAGE_B / "future_paths.parquet"
OUTCOMES = STAGE_B / "outcomes.parquet"

PHASE1_CHART_ROOT = OUTPUT_ROOT / "stage_c_phase1_masked_charts"
PHASE1_CHART_MANIFEST = PHASE1_CHART_ROOT / "manifest.json"
PHASE1_BLIND_INDEX = PHASE1_CHART_ROOT / "blind_index.csv"
PHASE1_REVIEW_ROOT = OUTPUT_ROOT / "stage_d_phase1_anonymous_review"
PHASE1_REVIEW_MANIFEST = PHASE1_REVIEW_ROOT / "manifest.json"
PHASE1_LEDGER = PHASE1_REVIEW_ROOT / "phase1_annotation_ledger.csv"
PHASE2_OUTPUT = OUTPUT_ROOT / "stage_e_phase2_outcome_attribution"

ASSET_ID = "CY-044"
DEPENDENCY_ASSET_ID = "CY-043"
AUTHORIZATION_ID = (
    "CYQ-AUTH-ASHARE-TURNOVER-INNOVATION-DECOUPLING-"
    "V32-PHASE2-CY044-OUTCOME-ATTRIBUTION-2018-2020-V1"
)
AUTHORIZED_ARM = "V32_CY044_FROZEN_PHASE2_OUTCOME_ATTRIBUTION_ONLY"

# These files are safe to open during --verify-public-inputs.  None contains a
# V32 Stage-B payoff, future path, or result.  The coordinate state is handled
# separately as declared-only lineage because it physically spans later years;
# the Phase-2 query itself is hard bounded through 2020-12-31.
PUBLIC_FIXED_HASHES = {
    PARENT_SPEC: "d389cda8f743441a4c46df61a2c044169f33550d05a5153bb96bea5abab75089",
    STAGE_B_SPEC: "23103c3910a83416da52ec149135731a2589782bd539967cab630e39ee041d9b",
    PHASE1_SPEC: "493885190524c28cd916f26efd16ba99fa2660ae81887ed61268eb1d397495e2",
    PHASE1_SCHEMA: "0b2aa65e71d460439149e80538d0d317bcce8b6f1d2c43a4168c928321402c43",
    PHASE1_REVIEWER_DRIFT_FREEZE: (
        "9b1dadba17f1ae1b219a887e29bced13a0ddc304a2ebe40eb954ccd5e39d3850"
    ),
    PHASE2_ANNOTATION_SCHEMA: "f4aaade524dac4a85a79f4b8fda03c00451267e915b4c77973b0110539eda603",
    STAGE_A_RUNNER: "a892ce53141c835ee6573427d97d12629ebffbaa869b5a5b789d5f33c6292054",
    STAGE_B_RUNNER: "fc28f2be60d683ef66d7d33b7baba65043390c9b893d1410e7f004c3a56c97c5",
    PHASE1_RUNNER: "5dfd15a7857b78df5fe25dbf92e0f91c2847130213e28a50f93827004464aa9d",
    PHASE1_FINALIZER: "cfd9fb199e73c8d4b42ab1b767fbb782b18acb15de05dedce5fd4884ee995b2a",
    COORDINATE_BUILDER: "358b62014c52b7bf936937746223954512fe9451eaa5009063e14f39e1bb1787",
    CY042_MANIFEST: "3af0ab075604cf0adb7405e821cf8594d9bc1ec22d70b5bce8395bef19baf4df",
    CY043_MANIFEST: "70fc0c44c603b53f8ffc5e8879bac5e2304ea02e1ab9ad52d8da74400fed441c",
    CY006_MANIFEST: "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2",
    PARTITIONS[0]: "b906d2c21fd35128b8f65f1b00fa12ae6e5bd9ee476a368a63881304f38ceed4",
    PARTITIONS[1]: "c69a464e4a04efdca0177a8a09a13a34646531afa37a2b35b4892fd40ec3ebfd",
    PARTITIONS[2]: "1b0a00c6d2cfbce0ae4f907e1ee9dc5006f59677d556cc10f8f34a9893937c62",
    STAGE_A_RESULT: "db6dd269340e7bed1153ca160492b91f6aaedd0b44aee853e447a8f8aa4c96f4",
    REPRESENTATION: "1a67e4dfcd4cc6e20000be3890d12e37f8a91da5afa47aaf8b84960d2bf7c13d",
    CANDIDATES: "4d57fafc3418bc7923e747910add5f503313582e0b0ef9d5e8bdb4a92dcf539d",
    PREPARED: "491c8089b36907777903256d932383710b1105ad540f5109fb1a23c778a99ec5",
    PHASE1_CHART_MANIFEST: "9075ad905d6566ce93e97839da04df46c49e06f829d42799da7144c1e753b089",
    PHASE1_BLIND_INDEX: "96fc0983edf5091c7c2535f0b13b9eefefc6ee4031819d1af70ebce54b630d96",
    PHASE1_REVIEW_MANIFEST: "bd820935d8b1f492896364d7da9b7de1c9543bf5ef08add5b68c6c145ac02bee",
    PHASE1_LEDGER: "1835c4d0eec87a736e9f9f639ea6aafa281aef0f0ee96a2ddd0de8a0c4b29140",
}

DECLARED_COORDINATE_HASH = "76fe88cb7509ae33a3d32b1bfd6d0c90560083127bdfaf63da1d7d24ec72bf60"

# --verify-public-inputs may compare these literal strings in already-opened
# authorization metadata, but it must not even stat these paths.
OUTCOME_HASHES = {
    STAGE_B_RESULT: "64cb4c19b38968bb0b59cb7f0bc2a4f16bd58a3c6af2f31c7e01cd95569bf2f7",
    FUTURE_PATHS: "4d06ccb23bbf660d17f4f58fc3140364ed5fc9b9213b3cd4f2f0b69752068377",
    OUTCOMES: "9c016be56517d08419ceeca2c16da055ede39acca35aa253d90bfbe8c166ecfa",
}

EXPECTED_EVENTS = 1_781
WINDOW = 126
WINDOW_ROWS = 253
SIGNAL_START = pd.Timestamp("2018-07-31")
SIGNAL_END = pd.Timestamp("2020-06-30")
MIN_CHART_DATE = pd.Timestamp("2018-01-22")
MAX_CHART_DATE = pd.Timestamp("2020-12-31")
EXPECTED_GLOBAL_SIGNAL_MIN = 1_355
EXPECTED_GLOBAL_SIGNAL_MAX = 1_818
EXPECTED_LOCAL_TO_GLOBAL_OFFSET = 1_215
OPAQUE_ORDER_SALT = "V32_PHASE1_MASKED_ORDER_V1"
TARGET_RETURN = 0.10
HORIZON_SESSIONS = 20
ROUND_TRIP_COST = 0.004

OUTCOME_BUCKETS = (
    "PROFIT_GE_4PCT",
    "PROFIT_0_TO_4PCT",
    "LOSS_0_TO_10PCT",
    "SEVERE_LOSS",
    "NO_COMPLETED_TRADE",
)
BUCKET_DEFINITIONS = {
    "PROFIT_GE_4PCT": "status=COMPLETED and net_return>=0.04",
    "PROFIT_0_TO_4PCT": "status=COMPLETED and 0<=net_return<0.04",
    "LOSS_0_TO_10PCT": "status=COMPLETED and -0.10<net_return<0",
    "SEVERE_LOSS": "status=COMPLETED and net_return<=-0.10",
    "NO_COMPLETED_TRADE": "status!=COMPLETED or net_return is nonfinite",
}
ALLOWED_STATUSES = {
    "NO_LEGAL_ENTRY",
    "INVALID_COORDINATE_LINEAGE_BEFORE_ENTRY",
    "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
    "INVALID_CORPORATE_ACTION_STATE_BEFORE_ENTRY",
    "INVALID_CORPORATE_ACTION_STATE_AFTER_ENTRY",
    "INCOMPLETE_PATH",
    "COMPLETED",
}
PHASE1_LABELS = (
    "BASE_COMPRESSION",
    "ORDERLY_PRICE_DISCOVERY",
    "HIGH_TURNOVER_LOW_PRICE_DISPLACEMENT",
    "MATURE_EXTENSION_OR_TERMINAL_SPIKE",
    "DOWNTREND_OR_BREAKDOWN",
)
PHASE1_LEDGER_COLUMNS = (
    "chart_number",
    "blind_chart_id",
    "blind_chart_path",
    "blind_chart_sha256",
    "sheet_number",
    "slot",
    *PHASE1_LABELS,
    "NONE_CLEAR",
    "evidence",
    "reviewer",
)
BLIND_INDEX_COLUMNS = (
    "chart_number",
    "blind_chart_id",
    "blind_chart_path",
    "blind_chart_sha256",
    "sheet_number",
    "slot",
)
PHASE2_ANNOTATION_FIELDS = (
    "chart_number",
    "blind_chart_id",
    "outcome_bucket",
    "post_path_label",
    "evidence",
    "reviewer",
    "phase1_labels_modified",
    "post_signal_used_as_predictor",
)
POST_PATH_LABELS = (
    "IMMEDIATE_ACCEPTANCE",
    "DELAYED_ACCEPTANCE",
    "EARLY_REJECTION",
    "LATE_REJECTION",
    "CHOP_OR_AMBIGUOUS",
    "NO_COMPLETED_TRADE",
)

CHART_SIZE = (720, 400)
PRICE_TOP, PRICE_BOTTOM = 88, 304
VOLUME_TOP, VOLUME_BOTTOM = 320, 391
LEFT_EDGE, PRE_RIGHT = 34, 354
POST_LEFT, RIGHT_EDGE = 366, 712
GRID_COLUMNS = 5
GRID_ROWS = 5

PUBLIC_BOUND_ROLES = (
    ("parent_spec", PARENT_SPEC),
    ("stage_b_spec", STAGE_B_SPEC),
    ("phase1_visual_review_spec", PHASE1_SPEC),
    ("phase1_annotation_schema", PHASE1_SCHEMA),
    ("phase1_reviewer_drift_freeze", PHASE1_REVIEWER_DRIFT_FREEZE),
    ("phase2_annotation_schema", PHASE2_ANNOTATION_SCHEMA),
    ("stage_a_runner", STAGE_A_RUNNER),
    ("stage_b_runner", STAGE_B_RUNNER),
    ("phase1_chart_runner", PHASE1_RUNNER),
    ("phase1_annotation_finalizer", PHASE1_FINALIZER),
    ("coordinate_builder", COORDINATE_BUILDER),
    ("cy042_manifest", CY042_MANIFEST),
    ("cy043_manifest", CY043_MANIFEST),
    ("cy006_manifest", CY006_MANIFEST),
    ("cy006_2018", PARTITIONS[0]),
    ("cy006_2019", PARTITIONS[1]),
    ("cy006_2020", PARTITIONS[2]),
    ("stage_a_result", STAGE_A_RESULT),
    ("stage_a_representation", REPRESENTATION),
    ("stage_a_candidates", CANDIDATES),
    ("stage_b_prepared_candidates", PREPARED),
    ("phase1_chart_corpus_manifest", PHASE1_CHART_MANIFEST),
    ("phase1_blind_index", PHASE1_BLIND_INDEX),
    ("phase1_annotation_manifest", PHASE1_REVIEW_MANIFEST),
    ("phase1_annotation_ledger", PHASE1_LEDGER),
)
OUTCOME_BOUND_ROLES = (
    ("stage_b_result", STAGE_B_RESULT),
    ("stage_b_future_paths", FUTURE_PATHS),
    ("stage_b_outcomes", OUTCOMES),
)


class ResearchError(RuntimeError):
    """Fail closed on authorization, lineage, chronology, or coverage drift."""


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
        raise ResearchError(f"{label} must be a JSON object")
    return value


def only(items: list[dict[str, Any]], label: str) -> dict[str, Any]:
    if len(items) != 1:
        raise ResearchError(f"expected one {label}; found {len(items)}")
    return items[0]


def require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ResearchError(f"{label} missing columns: {missing}")


def bound_artifact_map(authorization: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("role")): item
        for item in authorization.get("bound_artifacts", [])
        if isinstance(item, dict)
    }


def assert_declared_artifact(
    artifacts: dict[str, dict[str, Any]], role: str, path: Path, expected_hash: str
) -> None:
    """Compare literal authorization metadata without touching ``path``."""
    item = artifacts.get(role)
    if (
        item is None
        or item.get("path") != str(path)
        or item.get("sha256") != expected_hash
    ):
        raise ResearchError(f"CY-044 does not bind exact artifact {role}")


def verify_public_authorization() -> tuple[
    dict[str, str], dict[str, Any], dict[str, Any], dict[str, Any]
]:
    """Validate CY-044 without referring to an outcome file on disk."""
    required = (REGISTRY, PHASE2_SPEC, CY044_MANIFEST, Path(__file__))
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ResearchError(f"missing Phase-2 public authorization input: {missing}")
    actual = {
        "registry": sha256(REGISTRY),
        "phase2_spec": sha256(PHASE2_SPEC),
        "cy044_manifest": sha256(CY044_MANIFEST),
        "phase2_runner": sha256(Path(__file__)),
    }
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
        f"authorization {AUTHORIZATION_ID}",
    )
    lineage = asset.get("lineage", {})
    scope = authorization.get("scope", {})
    protocol = authorization.get("bound_protocol", {})
    bound_manifest = authorization.get("bound_manifest", {})
    if (
        asset.get("status") != "RESEARCH_CONDITIONAL"
        or asset.get("pit_grade") != "B"
        or lineage.get("manifest_path") != str(CY044_MANIFEST.resolve())
        or lineage.get("manifest_sha256") != actual["cy044_manifest"]
        or lineage.get("bounded_authorization_id") != AUTHORIZATION_ID
        or authorization.get("purpose")
        != "ASHARE_FROZEN_DEVELOPMENT_OUTCOME_CHART_ATTRIBUTION"
        or authorization.get("asset_id") != ASSET_ID
        or authorization.get("dependency_asset_id") != DEPENDENCY_ASSET_ID
        or authorization.get("authorized_arms") != [AUTHORIZED_ARM]
        or authorization.get("charts_authorized") is not True
        or authorization.get("phase2_authorized") is not True
        or authorization.get("completed_stage_b_artifact_read_authorized") is not True
        or authorization.get("coordinate_artifact_hash_authorized") is not True
        or authorization.get("outcome_artifact_hash_authorized") is not True
        or authorization.get("outcome_artifact_parse_authorized") is not True
        or authorization.get("post_signal_row_read_authorized") is not True
        or authorization.get("full_charts_authorized") is not True
        or authorization.get("outcome_grouping_authorized") is not True
        or authorization.get("outcome_attachment_authorized") is not True
        or authorization.get("in_memory_identity_reconstruction_authorized") is not True
        or authorization.get("identity_crosswalk_persistence_authorized") is not False
        or authorization.get("identity_reveal_authorized") is not False
        or authorization.get("phase1_label_rewrite_authorized") is not False
        or authorization.get("rule_aggregation_authorized") is not False
        or authorization.get("portfolio_replay_authorized") is not False
        or authorization.get("candidate_reselection_authorized") is not False
        or authorization.get("post_2020_read_authorized") is not False
        or authorization.get("2021_read_authorized") is not False
        or authorization.get("2022_plus_read_authorized") is not False
        or scope.get("signal_start") != str(SIGNAL_START.date())
        or scope.get("signal_end") != str(SIGNAL_END.date())
        or scope.get("minimum_chart_date") != str(MIN_CHART_DATE.date())
        or scope.get("maximum_chart_date") != str(MAX_CHART_DATE.date())
        or scope.get("frozen_candidate_rows") != EXPECTED_EVENTS
        or scope.get("phase1_annotation_ledger_sha256") != PUBLIC_FIXED_HASHES[PHASE1_LEDGER]
        or protocol.get("path") != str(PHASE2_SPEC.resolve())
        or protocol.get("sha256") != actual["phase2_spec"]
        or protocol.get("runner_path") != str(Path(__file__).resolve())
        or protocol.get("runner_sha256") != actual["phase2_runner"]
        or bound_manifest.get("path") != str(CY044_MANIFEST.resolve())
        or bound_manifest.get("sha256") != actual["cy044_manifest"]
    ):
        raise ResearchError("CY-044 registry authorization semantics drift")

    spec = load_json(PHASE2_SPEC, "Phase-2 visual-attribution spec")
    renderer = spec.get("renderer", {})
    phase1 = spec.get("frozen_phase1_binding", {})
    phase1_ledger = phase1.get("annotation_ledger", {})
    phase1_manifest = phase1.get("annotation_manifest", {})
    blind_index = phase1.get("blind_index", {})
    chart_manifest = phase1.get("chart_corpus_manifest", {})
    reviewer_drift = phase1.get("reviewer_drift_freeze", {})
    annotation_schema = spec.get("phase2_annotation_schema", {})
    stage_b = spec.get("frozen_stage_b_identity", {})
    outcome_groups = spec.get("outcome_groups", {})
    frozen_scope = spec.get("frozen_scope", {})
    permissions = spec.get("required_authorization", {}).get("permissions", {})
    if (
        spec.get("experiment") != EXPERIMENT
        or spec.get("stage") != "STAGE_E_PHASE2_OUTCOME_ATTRIBUTION"
        or spec.get("status") != "FROZEN_AFTER_PHASE1_BEFORE_OUTCOME_READ"
        or renderer.get("path") != str(Path(__file__).relative_to(REPO))
        or renderer.get("sha256") != actual["phase2_runner"]
        or phase1_ledger.get("path") != str(PHASE1_LEDGER)
        or phase1_ledger.get("sha256") != PUBLIC_FIXED_HASHES[PHASE1_LEDGER]
        or phase1_manifest.get("path") != str(PHASE1_REVIEW_MANIFEST)
        or phase1_manifest.get("sha256") != PUBLIC_FIXED_HASHES[PHASE1_REVIEW_MANIFEST]
        or blind_index.get("path") != str(PHASE1_BLIND_INDEX)
        or blind_index.get("sha256") != PUBLIC_FIXED_HASHES[PHASE1_BLIND_INDEX]
        or chart_manifest.get("path") != str(PHASE1_CHART_MANIFEST)
        or chart_manifest.get("sha256") != PUBLIC_FIXED_HASHES[PHASE1_CHART_MANIFEST]
        or reviewer_drift.get("path")
        != str(PHASE1_REVIEWER_DRIFT_FREEZE.relative_to(REPO))
        or reviewer_drift.get("sha256")
        != PUBLIC_FIXED_HASHES[PHASE1_REVIEWER_DRIFT_FREEZE]
        or annotation_schema.get("path")
        != str(PHASE2_ANNOTATION_SCHEMA.relative_to(REPO))
        or annotation_schema.get("sha256")
        != PUBLIC_FIXED_HASHES[PHASE2_ANNOTATION_SCHEMA]
        or frozen_scope.get("event_rows") != EXPECTED_EVENTS
        or frozen_scope.get("window_relative_global_sessions") != [-WINDOW, WINDOW]
        or frozen_scope.get("maximum_chart_date") != str(MAX_CHART_DATE.date())
        or outcome_groups.get("ordered_buckets") != list(OUTCOME_BUCKETS)
        or outcome_groups.get("definitions") != BUCKET_DEFINITIONS
        or outcome_groups.get("counts_frozen_before_run") is not False
        or spec.get("phase1_labels_immutable") is not True
        or spec.get("identity_crosswalk_persisted") is not False
        or spec.get("maximum_compressed_rules") != 0
        or permissions.get("phase2_authorized") is not True
        or permissions.get("coordinate_artifact_hash_authorized") is not True
        or permissions.get("outcome_artifact_parse_authorized") is not True
        or permissions.get("post_signal_row_read_authorized") is not True
        or permissions.get("identity_reveal_authorized") is not False
        or permissions.get("rule_aggregation_authorized") is not False
        or permissions.get("post_2020_read_authorized") is not False
    ):
        raise ResearchError("Phase-2 visual-attribution spec semantics drift")
    for role, path in OUTCOME_BOUND_ROLES:
        item = stage_b.get(role.removeprefix("stage_b_"), {})
        if item.get("path") != str(path) or item.get("sha256") != OUTCOME_HASHES[path]:
            raise ResearchError(f"Phase-2 spec Stage-B identity drift: {role}")

    manifest = load_json(CY044_MANIFEST, "CY-044 manifest")
    boundary = manifest.get("authorization_boundary", {})
    manifest_protocol = manifest.get("protocol", {})
    manifest_phase1 = manifest.get("frozen_phase1_binding", {})
    manifest_stage_b = manifest.get("reserved_stage_b_identities", {})
    if (
        manifest.get("asset_id") != ASSET_ID
        or manifest.get("status")
        != "FROZEN_DEVELOPMENT_PHASE2_CHART_ATTRIBUTION_BOUNDED_INPUT"
        or boundary.get("authorization_id") != AUTHORIZATION_ID
        or boundary.get("phase2_authorized") is not True
        or boundary.get("coordinate_artifact_hash_authorized") is not True
        or boundary.get("outcome_artifact_hash_authorized") is not True
        or boundary.get("outcome_artifact_parse_authorized") is not True
        or boundary.get("post_signal_row_read_authorized") is not True
        or boundary.get("identity_crosswalk_persistence_authorized") is not False
        or boundary.get("identity_reveal_authorized") is not False
        or boundary.get("phase1_label_rewrite_authorized") is not False
        or boundary.get("rule_aggregation_authorized") is not False
        or boundary.get("portfolio_replay_authorized") is not False
        or boundary.get("post_2020_read_authorized") is not False
        or manifest_protocol.get("phase2_spec_path") != str(PHASE2_SPEC.resolve())
        or manifest_protocol.get("phase2_spec_sha256") != actual["phase2_spec"]
        or manifest_protocol.get("phase2_runner_path") != str(Path(__file__).resolve())
        or manifest_protocol.get("phase2_runner_sha256") != actual["phase2_runner"]
        or manifest_phase1.get("annotation_ledger_sha256")
        != PUBLIC_FIXED_HASHES[PHASE1_LEDGER]
        or manifest_phase1.get("annotation_manifest_sha256")
        != PUBLIC_FIXED_HASHES[PHASE1_REVIEW_MANIFEST]
        or manifest_phase1.get("blind_index_sha256")
        != PUBLIC_FIXED_HASHES[PHASE1_BLIND_INDEX]
        or manifest_phase1.get("chart_corpus_manifest_sha256")
        != PUBLIC_FIXED_HASHES[PHASE1_CHART_MANIFEST]
        or manifest_phase1.get("reviewer_drift_freeze_sha256")
        != PUBLIC_FIXED_HASHES[PHASE1_REVIEWER_DRIFT_FREEZE]
        or manifest_protocol.get("phase2_annotation_schema_sha256")
        != PUBLIC_FIXED_HASHES[PHASE2_ANNOTATION_SCHEMA]
    ):
        raise ResearchError("CY-044 manifest semantics drift")
    for role, path in OUTCOME_BOUND_ROLES:
        item = manifest_stage_b.get(role.removeprefix("stage_b_"), {})
        if item.get("path") != str(path) or item.get("sha256") != OUTCOME_HASHES[path]:
            raise ResearchError(f"CY-044 reserved Stage-B identity drift: {role}")
    return actual, authorization, spec, manifest


def verify_public_bound_inputs(
    preflight: dict[str, str], authorization: dict[str, Any]
) -> dict[str, str]:
    """Hash only inputs that are allowed in the outcome-blind public mode."""
    artifacts = bound_artifact_map(authorization)
    actual = dict(preflight)
    for role, path in PUBLIC_BOUND_ROLES:
        if not path.is_file():
            raise ResearchError(f"missing bound public input {role}: {path}")
        value = sha256(path)
        expected = PUBLIC_FIXED_HASHES[path]
        if value != expected:
            raise ResearchError(f"public input drift: {role}: {value} != {expected}")
        assert_declared_artifact(artifacts, role, path.resolve(), value)
        actual[role] = value

    # The coordinate file physically spans later dates, so public verification
    # validates only its already-frozen identity string.  --run reads a bounded
    # 2018-01-22..2020-12-31 SQL slice after authorization.
    assert_declared_artifact(
        artifacts, "coordinate_state", COORDINATE_STATE, DECLARED_COORDINATE_HASH
    )
    actual["coordinate_state_declared_sha256_only"] = DECLARED_COORDINATE_HASH

    # Critical blind boundary: literal metadata comparison only.  No exists(),
    # stat(), resolve(), open(), sha256(), parquet metadata call, or JSON load.
    for role, path in OUTCOME_BOUND_ROLES:
        assert_declared_artifact(artifacts, role, path, OUTCOME_HASHES[path])
        actual[f"{role}_declared_sha256_only"] = OUTCOME_HASHES[path]
    return actual


def validate_phase1_public_artifacts() -> tuple[pd.DataFrame, pd.DataFrame]:
    chart_manifest = load_json(PHASE1_CHART_MANIFEST, "Phase-1 chart manifest")
    review_manifest = load_json(PHASE1_REVIEW_MANIFEST, "Phase-1 review manifest")
    drift_freeze = load_json(PHASE1_REVIEWER_DRIFT_FREEZE, "Phase-1 reviewer-drift freeze")
    phase2_schema = load_json(PHASE2_ANNOTATION_SCHEMA, "Phase-2 annotation schema")
    if (
        chart_manifest.get("experiment") != EXPERIMENT
        or chart_manifest.get("stage") != "STAGE_C_PHASE1_ANONYMOUS_OUTCOME_MASKED_CORPUS"
        or chart_manifest.get("events") != EXPECTED_EVENTS
        or chart_manifest.get("blind_index_sha256") != PUBLIC_FIXED_HASHES[PHASE1_BLIND_INDEX]
        or chart_manifest.get("identity_crosswalk_persisted") is not False
        or chart_manifest.get("post_2020_row_read") is not False
        or chart_manifest.get("post_signal_row_read") is not False
        or chart_manifest.get("outcome_artifact_parsed") is not False
        or chart_manifest.get("individual_coverage_exactly_once") is not True
        or chart_manifest.get("masked_contact_sheet_coverage_exactly_once") is not True
    ):
        raise ResearchError("Phase-1 chart manifest semantics drift")
    if (
        review_manifest.get("experiment") != EXPERIMENT
        or review_manifest.get("stage") != "PHASE1_ANONYMOUS_SIGNAL_TIME_ANNOTATIONS_FROZEN"
        or review_manifest.get("events") != EXPECTED_EVENTS
        or review_manifest.get("ledger_sha256") != PUBLIC_FIXED_HASHES[PHASE1_LEDGER]
        or review_manifest.get("coverage_exactly_once") is not True
        or review_manifest.get("identity_mapping_read") is not False
        or review_manifest.get("outcomes_read") is not False
        or review_manifest.get("future_paths_read") is not False
        or review_manifest.get("stage_b_result_read") is not False
        or review_manifest.get("post_signal_used_as_predictor") is not False
    ):
        raise ResearchError("Phase-1 annotation manifest semantics drift")
    drift_inputs = drift_freeze.get("inputs", {})
    drift_governance = drift_freeze.get("governance", {})
    if (
        drift_freeze.get("experiment") != EXPERIMENT
        or drift_freeze.get("stage")
        != "PHASE1_OUTCOME_BLIND_REVIEWER_DRIFT_DECISION_FROZEN"
        or drift_inputs.get("phase1_annotation_ledger", {}).get("sha256")
        != PUBLIC_FIXED_HASHES[PHASE1_LEDGER]
        or drift_inputs.get("phase1_manifest", {}).get("sha256")
        != PUBLIC_FIXED_HASHES[PHASE1_REVIEW_MANIFEST]
        or drift_governance.get("outcomes_read") is not False
        or drift_governance.get("stage_b_result_read") is not False
        or drift_governance.get("future_paths_read") is not False
        or drift_governance.get("identity_mapping_read") is not False
        or drift_governance.get("relabeling_permitted") is not False
        or drift_governance.get("labels_frozen_as_recorded") is not True
        or drift_freeze.get("decision_locked_before_outcome_attachment") is not True
    ):
        raise ResearchError("Phase-1 reviewer-drift freeze semantics drift")
    schema_items = phase2_schema.get("items", {})
    schema_properties = schema_items.get("properties", {})
    if (
        phase2_schema.get("$id")
        != "ASHARE-V32-PHASE2-ANONYMOUS-POST-PATH-ANNOTATION-V1"
        or schema_items.get("additionalProperties") is not False
        or schema_items.get("required") != list(PHASE2_ANNOTATION_FIELDS)
        or schema_properties.get("outcome_bucket", {}).get("enum")
        != list(OUTCOME_BUCKETS)
        or schema_properties.get("post_path_label", {}).get("enum")
        != list(POST_PATH_LABELS)
        or schema_properties.get("phase1_labels_modified", {}).get("const") is not False
        or schema_properties.get("post_signal_used_as_predictor", {}).get("const") is not False
    ):
        raise ResearchError("Phase-2 annotation schema semantics drift")

    blind = pd.read_csv(PHASE1_BLIND_INDEX)
    ledger = pd.read_csv(PHASE1_LEDGER)
    if tuple(blind.columns) != BLIND_INDEX_COLUMNS:
        raise ResearchError("Phase-1 blind-index schema drift")
    if tuple(ledger.columns) != PHASE1_LEDGER_COLUMNS:
        raise ResearchError("Phase-1 annotation-ledger schema drift")
    expected_numbers = list(range(1, EXPECTED_EVENTS + 1))
    for frame, label in ((blind, "blind index"), (ledger, "Phase-1 ledger")):
        frame["chart_number"] = pd.to_numeric(frame.chart_number, errors="raise").astype(int)
        if (
            len(frame) != EXPECTED_EVENTS
            or frame.chart_number.tolist() != expected_numbers
            or frame.chart_number.duplicated().any()
            or frame.blind_chart_id.isna().any()
            or frame.blind_chart_id.duplicated().any()
        ):
            raise ResearchError(f"{label} anonymous coverage drift")
    pd.testing.assert_frame_equal(
        blind[list(BLIND_INDEX_COLUMNS)].reset_index(drop=True),
        ledger[list(BLIND_INDEX_COLUMNS)].reset_index(drop=True),
        check_dtype=False,
    )
    boolean_text = ledger[[*PHASE1_LABELS, "NONE_CLEAR"]].astype(str).apply(
        lambda column: column.str.lower()
    )
    if not boolean_text.isin({"true", "false"}).all(axis=None):
        raise ResearchError("Phase-1 annotation booleans drift")
    label_true = boolean_text[list(PHASE1_LABELS)].eq("true")
    none_clear_true = boolean_text["NONE_CLEAR"].eq("true")
    if not none_clear_true.eq(~label_true.any(axis=1)).all():
        raise ResearchError("Phase-1 NONE_CLEAR derivation drift")
    if (
        ledger.evidence.fillna("").astype(str).str.strip().eq("").any()
        or ledger.reviewer.fillna("").astype(str).str.strip().eq("").any()
    ):
        raise ResearchError("Phase-1 ledger contains an unreviewed row")
    return blind, ledger


def load_and_audit_public_identities() -> pd.DataFrame:
    candidates = pd.read_parquet(CANDIDATES)
    prepared = pd.read_parquet(PREPARED)
    require_columns(
        candidates,
        {"event_id", "symbol", "causal_industry", "signal_date", "signal_cal_idx"},
        "Stage-A candidates",
    )
    require_columns(
        prepared,
        {
            "event_id",
            "symbol",
            "causal_industry",
            "signal_date",
            "source_signal_cal_idx",
            "signal_cal_idx",
            "invalid_step_cum",
            "decision_at",
            "available_at",
            "execution_raw_signal_date",
            "coordinate_signal_date",
            "execution_raw_industry",
        },
        "Stage-B prepared candidates",
    )
    for frame in (candidates, prepared):
        frame["event_id"] = frame.event_id.astype(str)
        frame["signal_date"] = pd.to_datetime(frame.signal_date)
    for column in (
        "decision_at",
        "available_at",
        "execution_raw_signal_date",
        "coordinate_signal_date",
    ):
        prepared[column] = pd.to_datetime(prepared[column])
    if any(
        len(frame) != EXPECTED_EVENTS
        or frame.event_id.isna().any()
        or frame.event_id.duplicated().any()
        for frame in (candidates, prepared)
    ):
        raise ResearchError("Stage-A/prepared identity count drift")
    if set(candidates.event_id) != set(prepared.event_id):
        raise ResearchError("Stage-A/prepared event sets differ")
    identity = prepared.merge(
        candidates[["event_id", "symbol", "causal_industry", "signal_date", "signal_cal_idx"]],
        on="event_id",
        suffixes=("_prepared", "_stage_a"),
        validate="one_to_one",
    )
    for field in ("symbol", "causal_industry", "signal_date"):
        if not identity[f"{field}_prepared"].eq(identity[f"{field}_stage_a"]).all():
            raise ResearchError(f"prepared/Stage-A identity drift: {field}")
    if not identity.source_signal_cal_idx.eq(identity.signal_cal_idx_stage_a).all():
        raise ResearchError("prepared source_signal_cal_idx is not Stage-A local coordinate")
    if (
        not prepared.execution_raw_signal_date.eq(prepared.signal_date).all()
        or not prepared.coordinate_signal_date.eq(prepared.signal_date).all()
        or not prepared.execution_raw_industry.eq(prepared.causal_industry).all()
        or not (
            identity.signal_cal_idx_prepared - identity.source_signal_cal_idx
        ).eq(EXPECTED_LOCAL_TO_GLOBAL_OFFSET).all()
        or prepared.signal_cal_idx.min() != EXPECTED_GLOBAL_SIGNAL_MIN
        or prepared.signal_cal_idx.max() != EXPECTED_GLOBAL_SIGNAL_MAX
        or prepared.signal_date.min() != SIGNAL_START
        or prepared.signal_date.max() != SIGNAL_END
        or prepared.available_at.isna().any()
        or prepared.decision_at.isna().any()
        or prepared.available_at.gt(prepared.decision_at).any()
    ):
        raise ResearchError("prepared V32 PIT/calendar identity drift")
    return prepared


def rebuild_blind_order(prepared: pd.DataFrame, ledger: pd.DataFrame) -> pd.DataFrame:
    """Reproduce the Phase-1 mapping in memory and never serialize identity."""
    ordered = prepared.copy()
    ordered["event_id"] = ordered.event_id.astype(str)
    ordered["_blind_sort_digest"] = ordered.event_id.map(
        lambda value: hashlib.sha256(f"{OPAQUE_ORDER_SALT}|{value}".encode()).hexdigest()
    )
    ordered["blind_chart_id"] = "B-" + ordered._blind_sort_digest.str.slice(0, 20)
    ordered = ordered.sort_values(
        ["_blind_sort_digest", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    ordered.insert(0, "chart_number", np.arange(1, len(ordered) + 1, dtype=np.int64))
    if (
        len(ordered) != EXPECTED_EVENTS
        or ordered.event_id.duplicated().any()
        or ordered.blind_chart_id.duplicated().any()
        or ordered.chart_number.tolist() != list(range(1, EXPECTED_EVENTS + 1))
    ):
        raise ResearchError("reconstructed blind order coverage drift")
    pd.testing.assert_frame_equal(
        ordered[["chart_number", "blind_chart_id"]].reset_index(drop=True),
        ledger[["chart_number", "blind_chart_id"]].reset_index(drop=True),
        check_dtype=False,
    )
    return ordered


def verify_public_inputs() -> tuple[
    dict[str, str], dict[str, Any], dict[str, Any], dict[str, Any], pd.DataFrame
]:
    """Complete the no-outcome verification path."""
    preflight, authorization, spec, manifest = verify_public_authorization()
    assert_run_authorized(authorization, spec, manifest)
    source_hashes = verify_public_bound_inputs(preflight, authorization)
    _, ledger = validate_phase1_public_artifacts()
    prepared = load_and_audit_public_identities()
    blind_order = rebuild_blind_order(prepared, ledger)
    return source_hashes, authorization, spec, manifest, blind_order


def assert_run_authorized(
    authorization: dict[str, Any], spec: dict[str, Any], manifest: dict[str, Any]
) -> None:
    """Final metadata-only barrier immediately before outcome files are touched."""
    boundary = manifest.get("authorization_boundary", {})
    permissions = spec.get("required_authorization", {}).get("permissions", {})
    required_true = (
        "charts_authorized",
        "phase2_authorized",
        "completed_stage_b_artifact_read_authorized",
        "coordinate_artifact_hash_authorized",
        "outcome_artifact_hash_authorized",
        "outcome_artifact_parse_authorized",
        "post_signal_row_read_authorized",
        "full_charts_authorized",
        "outcome_grouping_authorized",
        "outcome_attachment_authorized",
        "in_memory_identity_reconstruction_authorized",
    )
    required_false = (
        "identity_crosswalk_persistence_authorized",
        "identity_reveal_authorized",
        "phase1_label_rewrite_authorized",
        "rule_aggregation_authorized",
        "portfolio_replay_authorized",
        "candidate_reselection_authorized",
        "post_2020_read_authorized",
        "2021_read_authorized",
        "2022_plus_read_authorized",
    )
    for key in required_true:
        if authorization.get(key) is not True or boundary.get(key) is not True:
            raise ResearchError(f"Phase-2 run permission not jointly true: {key}")
        if permissions.get(key) is not True:
            raise ResearchError(f"Phase-2 spec permission not true: {key}")
    for key in required_false:
        if authorization.get(key) is not False or boundary.get(key) is not False:
            raise ResearchError(f"Phase-2 forbidden permission not jointly false: {key}")
        if permissions.get(key) is not False:
            raise ResearchError(f"Phase-2 spec forbidden permission not false: {key}")


def verify_run_coordinate_state() -> str:
    """Hash coordinate lineage only after the joint CY-044 gate has passed."""
    if not COORDINATE_STATE.is_file():
        raise ResearchError(f"missing authorized coordinate state: {COORDINATE_STATE}")
    actual = sha256(COORDINATE_STATE)
    if actual != DECLARED_COORDINATE_HASH:
        raise ResearchError(
            f"authorized coordinate-state drift: {actual} != {DECLARED_COORDINATE_HASH}"
        )
    return actual


def verify_and_load_stage_b(
    blind_order: pd.DataFrame, authorization: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, str]]:
    """First function allowed to touch an outcome-bearing Stage-B artifact."""
    artifacts = bound_artifact_map(authorization)
    actual: dict[str, str] = {}
    for role, path in OUTCOME_BOUND_ROLES:
        # This is intentionally the first stat/open/hash of each outcome path.
        if not path.is_file():
            raise ResearchError(f"missing authorized Stage-B artifact {role}: {path}")
        value = sha256(path)
        if value != OUTCOME_HASHES[path]:
            raise ResearchError(f"authorized Stage-B artifact drift: {role}")
        assert_declared_artifact(artifacts, role, path, value)
        actual[role] = value

    result = load_json(STAGE_B_RESULT, "authorized Stage-B result")
    if (
        result.get("experiment") != EXPERIMENT
        or result.get("stage") != "SEPARATELY_AUTHORIZED_FROZEN_DEVELOPMENT_OUTCOME_ATTACHMENT"
        or result.get("stage_a_candidate_rows") != EXPECTED_EVENTS
        or result.get("prepared_candidates_sha256") != PUBLIC_FIXED_HASHES[PREPARED]
        or result.get("future_paths_sha256") != actual["stage_b_future_paths"]
        or result.get("outcomes_sha256") != actual["stage_b_outcomes"]
        or result.get("post_2020_row_read") is not False
        or result.get("maximum_path_row_date") != str(MAX_CHART_DATE.date())
        or result.get("target_return") != TARGET_RETURN
        or result.get("horizon_sessions") != HORIZON_SESSIONS
        or result.get("round_trip_cost") != ROUND_TRIP_COST
        or result.get("charts_rendered") is not False
        or result.get("portfolio_replay_performed") is not False
    ):
        raise ResearchError("authorized Stage-B result semantics drift")

    path_columns = [
        "event_id",
        "symbol",
        "event_signal_date",
        "event_signal_cal_idx",
        "trade_date",
        "cal_idx",
    ]
    future = pd.read_parquet(FUTURE_PATHS, columns=path_columns)
    for column in ("event_signal_date", "trade_date"):
        future[column] = pd.to_datetime(future[column])
    future["event_id"] = future.event_id.astype(str)
    expected_id_symbol = dict(
        zip(blind_order.event_id.astype(str), blind_order.symbol.astype(str), strict=True)
    )
    expected_id_signal_idx = dict(
        zip(
            blind_order.event_id.astype(str),
            blind_order.signal_cal_idx.astype(int),
            strict=True,
        )
    )
    expected_id_signal_date = dict(
        zip(
            blind_order.event_id.astype(str),
            pd.to_datetime(blind_order.signal_date),
            strict=True,
        )
    )
    observed_pairs = future[["event_id", "symbol"]].drop_duplicates()
    observed_identity = future[
        ["event_id", "event_signal_date", "event_signal_cal_idx"]
    ].drop_duplicates()
    future_ids = set(future.event_id)
    path_audit = result.get("path_audit", {})
    if (
        future.empty
        or future.duplicated(["event_id", "cal_idx"]).any()
        or not future_ids.issubset(set(expected_id_symbol))
        or int(path_audit.get("rows", -1)) != len(future)
        or int(path_audit.get("events_with_rows", -1)) != len(future_ids)
        or int(path_audit.get("candidate_events_without_rows", -1))
        != EXPECTED_EVENTS - len(future_ids)
        or future.trade_date.gt(MAX_CHART_DATE).any()
        or future.event_signal_date.gt(SIGNAL_END).any()
        or future.trade_date.le(future.event_signal_date).any()
        or future.cal_idx.le(future.event_signal_cal_idx).any()
        or any(
            expected_id_symbol.get(str(row.event_id)) != str(row.symbol)
            for row in observed_pairs.itertuples(index=False)
        )
        or any(
            expected_id_signal_idx.get(str(row.event_id)) != int(row.event_signal_cal_idx)
            or expected_id_signal_date.get(str(row.event_id))
            != pd.Timestamp(row.event_signal_date)
            for row in observed_identity.itertuples(index=False)
        )
    ):
        raise ResearchError("authorized Stage-B future-path scope/identity drift")

    outcomes = pd.read_parquet(OUTCOMES)
    require_columns(
        outcomes,
        {
            "event_id",
            "symbol",
            "causal_industry",
            "signal_date",
            "signal_cal_idx",
            "signal_invalid_step_cum",
            "target_return",
            "horizon_sessions",
            "round_trip_cost",
            "status",
            "entry_date",
            "entry_cal_idx",
            "entry_price",
            "target_price",
            "exit_date",
            "exit_cal_idx",
            "exit_price",
            "exit_reason",
            "holding_sessions",
            "net_return",
        },
        "authorized Stage-B outcomes",
    )
    outcomes["event_id"] = outcomes.event_id.astype(str)
    for column in (
        "signal_date",
        "lineage_invalid_date",
        "data_invalid_date",
        "entry_date",
        "exit_date",
    ):
        if column in outcomes:
            outcomes[column] = pd.to_datetime(outcomes[column])
    if (
        len(outcomes) != EXPECTED_EVENTS
        or outcomes.event_id.duplicated().any()
        or set(outcomes.event_id) != set(blind_order.event_id.astype(str))
        or not set(outcomes.status.astype(str)).issubset(ALLOWED_STATUSES)
        or not np.isclose(outcomes.target_return.astype(float), TARGET_RETURN).all()
        or not outcomes.horizon_sessions.eq(HORIZON_SESSIONS).all()
        or not np.isclose(outcomes.round_trip_cost.astype(float), ROUND_TRIP_COST).all()
    ):
        raise ResearchError("authorized Stage-B outcome contract drift")
    identity = blind_order.merge(
        outcomes[
            [
                "event_id",
                "symbol",
                "causal_industry",
                "signal_date",
                "signal_cal_idx",
                "signal_invalid_step_cum",
            ]
        ],
        on="event_id",
        suffixes=("_prepared", "_outcome"),
        validate="one_to_one",
    )
    for field in ("symbol", "causal_industry", "signal_date", "signal_cal_idx"):
        if not identity[f"{field}_prepared"].eq(identity[f"{field}_outcome"]).all():
            raise ResearchError(f"prepared/outcome identity drift: {field}")
    if not identity.invalid_step_cum.eq(identity.signal_invalid_step_cum).all():
        raise ResearchError("prepared/outcome coordinate-lineage drift")

    entered = outcomes.loc[outcomes.entry_cal_idx.notna()].copy()
    completed = outcomes.loc[outcomes.status.eq("COMPLETED")].copy()
    completed_net = pd.to_numeric(completed.net_return, errors="coerce")
    noncompleted = outcomes.loc[~outcomes.status.eq("COMPLETED")]
    if (
        entered.entry_cal_idx.le(entered.signal_cal_idx).any()
        or entered.entry_cal_idx.gt(entered.signal_cal_idx + 3).any()
        or completed.exit_cal_idx.le(completed.entry_cal_idx).any()
        or completed.exit_cal_idx.gt(completed.signal_cal_idx + WINDOW).any()
        or completed.exit_date.gt(MAX_CHART_DATE).any()
        or not np.isfinite(completed_net).all()
        or noncompleted.net_return.notna().any()
    ):
        raise ResearchError("authorized Stage-B lifecycle chronology drift")
    for column in (
        "signal_date",
        "lineage_invalid_date",
        "data_invalid_date",
        "entry_date",
        "exit_date",
    ):
        if column in outcomes and outcomes[column].dropna().gt(MAX_CHART_DATE).any():
            raise ResearchError(f"post-2020 outcome date found in {column}")
    return outcomes, actual


def load_windows(blind_order: pd.DataFrame) -> pd.DataFrame:
    """Read only the bounded 2018-01-22..2020-12-31 chart slice."""
    connection = duckdb.connect()
    connection.execute("SET threads=4")
    chart_keys = blind_order[
        [
            "event_id",
            "symbol",
            "signal_date",
            "signal_cal_idx",
            "decision_at",
            "invalid_step_cum",
        ]
    ].rename(columns={"invalid_step_cum": "signal_invalid_step_cum"})
    connection.register(
        "chart_keys",
        chart_keys,
    )
    paths = ",".join(f"'{path.as_posix()}'" for path in PARTITIONS)
    windows = connection.execute(
        f"""
        WITH calendar AS (
          SELECT trade_date,cal_idx
          FROM read_parquet('{COORDINATE_STATE.as_posix()}')
          WHERE trade_date BETWEEN DATE '{MIN_CHART_DATE.date()}'
                               AND DATE '{MAX_CHART_DATE.date()}'
          GROUP BY trade_date,cal_idx
        ), expanded AS (
          SELECT k.event_id,k.symbol,k.signal_date,k.signal_cal_idx,
            k.decision_at AS signal_decision_at,k.signal_invalid_step_cum,
            c.trade_date,c.cal_idx,
            c.cal_idx-k.signal_cal_idx AS relative_session
          FROM chart_keys k JOIN calendar c
            ON c.cal_idx BETWEEN k.signal_cal_idx-{WINDOW} AND k.signal_cal_idx+{WINDOW}
        ), raw AS (
          SELECT * FROM read_parquet([{paths}], union_by_name=true)
          WHERE trade_date BETWEEN DATE '{MIN_CHART_DATE.date()}'
                               AND DATE '{MAX_CHART_DATE.date()}'
        ), coord AS (
          SELECT trade_date,cal_idx AS coordinate_cal_idx,symbol,adjusted_close,
            invalid_step_cum AS coordinate_invalid_step_cum,current_valid,
            corporate_action_valid,corporate_action_blocking
          FROM read_parquet('{COORDINATE_STATE.as_posix()}')
          WHERE trade_date BETWEEN DATE '{MIN_CHART_DATE.date()}'
                               AND DATE '{MAX_CHART_DATE.date()}'
        )
        SELECT e.event_id,e.symbol,e.signal_date,e.signal_cal_idx,e.signal_decision_at,
          e.signal_invalid_step_cum,e.trade_date,e.cal_idx,e.relative_session,
          c.coordinate_cal_idx,
          r.open*c.adjusted_close/r.close AS coord_open,
          r.high*c.adjusted_close/r.close AS coord_high,
          r.low*c.adjusted_close/r.close AS coord_low,c.adjusted_close AS coord_close,
          r.turnover_fraction,r.hard_valid,r.available_at,r.decision_at AS bar_decision_at,
          c.current_valid,c.corporate_action_valid,c.corporate_action_blocking,
          c.coordinate_invalid_step_cum
        FROM expanded e
        LEFT JOIN raw r ON r.symbol=e.symbol AND r.trade_date=e.trade_date
        LEFT JOIN coord c ON c.symbol=e.symbol AND c.trade_date=e.trade_date
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
    ):
        windows[column] = pd.to_datetime(windows[column])
    counts = windows.groupby("event_id").agg(
        rows=("cal_idx", "size"),
        first=("relative_session", "min"),
        last=("relative_session", "max"),
    )
    if (
        len(counts) != EXPECTED_EVENTS
        or not counts.rows.eq(WINDOW_ROWS).all()
        or not counts["first"].eq(-WINDOW).all()
        or not counts["last"].eq(WINDOW).all()
        or windows.duplicated(["event_id", "cal_idx"]).any()
        or windows.trade_date.min() != MIN_CHART_DATE
        or windows.trade_date.max() != MAX_CHART_DATE
        or windows.trade_date.gt(MAX_CHART_DATE).any()
    ):
        raise ResearchError("global +/-126 chart-window coverage drift")
    coordinate_present = windows.coordinate_cal_idx.notna()
    if (
        coordinate_present
        & pd.to_numeric(windows.coordinate_cal_idx, errors="coerce").ne(windows.cal_idx)
    ).any():
        raise ResearchError("coordinate cal_idx differs from expanded global cal_idx")
    signal = windows.loc[windows.relative_session.eq(0)]
    if (
        len(signal) != EXPECTED_EVENTS
        or not signal.trade_date.eq(signal.signal_date).all()
        or not signal.cal_idx.eq(signal.signal_cal_idx).all()
        or len(valid_bars(signal)) != EXPECTED_EVENTS
    ):
        raise ResearchError(
            "signal bar is absent or fails coordinate/company-action/lineage validity"
        )
    valid = valid_bars(windows)
    if (
        valid.available_at.isna().any()
        or valid.bar_decision_at.isna().any()
        or valid.available_at.gt(valid.bar_decision_at).any()
    ):
        raise ResearchError("chart source violates its own availability clock")
    valid_pre = valid.loc[valid.relative_session.le(0)]
    if (
        valid_pre.available_at.gt(valid_pre.signal_decision_at).any()
        or valid_pre.bar_decision_at.gt(valid_pre.signal_decision_at).any()
    ):
        raise ResearchError("pre-signal chart row was unavailable at signal decision_at")
    return windows


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


def build_internal_event_ledger(
    blind_order: pd.DataFrame, outcomes: pd.DataFrame
) -> pd.DataFrame:
    outcome_by_id = outcomes.set_index("event_id", verify_integrity=True)
    rows: list[dict[str, Any]] = []
    for event in blind_order.itertuples(index=False):
        outcome = outcome_by_id.loc[str(event.event_id)]
        net = float(outcome.net_return) if pd.notna(outcome.net_return) else math.nan
        rows.append(
            {
                # event_id remains process-local and is dropped from every output.
                "event_id": str(event.event_id),
                "chart_number": int(event.chart_number),
                "blind_chart_id": str(event.blind_chart_id),
                "signal_cal_idx": int(event.signal_cal_idx),
                "status": str(outcome.status),
                "entry_cal_idx": outcome.entry_cal_idx,
                "entry_price": outcome.entry_price,
                "target_price": outcome.target_price,
                "exit_cal_idx": outcome.exit_cal_idx,
                "exit_price": outcome.exit_price,
                "exit_reason": outcome.exit_reason,
                "outcome_bucket": outcome_bucket(str(outcome.status), net),
            }
        )
    ledger = pd.DataFrame(rows).sort_values("chart_number", kind="mergesort")
    counts = ledger.outcome_bucket.value_counts().to_dict()
    if (
        len(ledger) != EXPECTED_EVENTS
        or ledger.event_id.duplicated().any()
        or ledger.chart_number.duplicated().any()
        or ledger.blind_chart_id.duplicated().any()
        or set(ledger.outcome_bucket) - set(OUTCOME_BUCKETS)
        or sum(int(value) for value in counts.values()) != EXPECTED_EVENTS
    ):
        raise ResearchError("internal Phase-2 outcome grouping drift")
    return ledger


def valid_bars(frame: pd.DataFrame) -> pd.DataFrame:
    numeric = frame[["coord_open", "coord_high", "coord_low", "coord_close"]].apply(
        pd.to_numeric, errors="coerce"
    )
    coordinate_cal_idx = pd.to_numeric(frame.coordinate_cal_idx, errors="coerce")
    expanded_cal_idx = pd.to_numeric(frame.cal_idx, errors="coerce")
    coordinate_lineage = pd.to_numeric(
        frame.coordinate_invalid_step_cum, errors="coerce"
    )
    signal_lineage = pd.to_numeric(frame.signal_invalid_step_cum, errors="coerce")
    return frame.loc[
        frame.current_valid.fillna(False).astype(bool)
        & frame.hard_valid.fillna(False).astype(bool)
        & frame.corporate_action_valid.fillna(False).astype(bool)
        & ~frame.corporate_action_blocking.fillna(True).astype(bool)
        & coordinate_cal_idx.notna()
        & coordinate_cal_idx.eq(expanded_cal_idx)
        & coordinate_lineage.notna()
        & signal_lineage.notna()
        & coordinate_lineage.eq(signal_lineage)
        & np.isfinite(numeric).all(axis=1)
        & numeric.gt(0).all(axis=1)
    ].sort_values("cal_idx", kind="mergesort")


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
    finite = [float(value) for value in values if math.isfinite(float(value))]
    if not finite:
        return (0.0, 1.0)
    low, high = min(finite), max(finite)
    if not high > low:
        high = low * 1.01 if low > 0 else low + 1.0
    pad = (high - low) * 0.04
    return low - pad, high + pad


def _x(relative: int, *, pre: bool) -> int:
    if pre:
        if relative < -WINDOW or relative > 0:
            raise ResearchError(f"pre relative session outside [-{WINDOW},0]: {relative}")
        return int(LEFT_EDGE + (relative + WINDOW) * (PRE_RIGHT - LEFT_EDGE) / WINDOW)
    if relative < 1 or relative > WINDOW:
        raise ResearchError(f"post relative session outside [1,{WINDOW}]: {relative}")
    return int(POST_LEFT + (relative - 1) * (RIGHT_EDGE - POST_LEFT) / (WINDOW - 1))


def _y(value: float, scale: tuple[float, float]) -> int:
    low, high = scale
    return int(PRICE_BOTTOM - (value - low) * (PRICE_BOTTOM - PRICE_TOP) / (high - low))


def _triangle(draw: ImageDraw.ImageDraw, x: int, y: int, up: bool, color: str) -> None:
    points = (
        [(x, y - 7), (x - 6, y + 5), (x + 6, y + 5)]
        if up
        else [(x, y + 7), (x - 6, y - 5), (x + 6, y - 5)]
    )
    draw.polygon(points, fill=color)


def _draw_panel(
    draw: ImageDraw.ImageDraw,
    bars: pd.DataFrame,
    *,
    pre: bool,
    background: str,
    extra_prices: list[float] | None = None,
) -> tuple[tuple[float, float], dict[int, int]]:
    x0, x1 = (LEFT_EDGE, PRE_RIGHT) if pre else (POST_LEFT, RIGHT_EDGE)
    draw.rectangle((x0, PRICE_TOP, x1, VOLUME_BOTTOM), fill=background)
    draw.rectangle((x0, PRICE_TOP, x1, PRICE_BOTTOM), outline="#9ca3af")
    draw.rectangle((x0, VOLUME_TOP, x1, VOLUME_BOTTOM), outline="#d1d5db")
    price_values = list(bars.coord_low.astype(float)) + list(bars.coord_high.astype(float))
    price_values.extend(extra_prices or [])
    scale = _scale(price_values)
    max_turnover = max(float(bars.turnover_fraction.fillna(0).max()), 1e-9) if len(bars) else 1.0
    identity: dict[int, int] = {}
    for row in bars.itertuples(index=False):
        relative = int(row.relative_session)
        x = _x(relative, pre=pre)
        identity[int(row.cal_idx)] = relative
        open_y, close_y = _y(float(row.coord_open), scale), _y(float(row.coord_close), scale)
        high_y, low_y = _y(float(row.coord_high), scale), _y(float(row.coord_low), scale)
        color = "#dc2626" if float(row.coord_close) >= float(row.coord_open) else "#16803c"
        draw.line((x, high_y, x, low_y), fill=color, width=1)
        body_top, body_bottom = sorted((open_y, close_y))
        draw.rectangle((x - 1, body_top, x + 1, max(body_top + 1, body_bottom)), fill=color)
        if pd.notna(row.turnover_fraction):
            height = int(
                float(row.turnover_fraction) / max_turnover * (VOLUME_BOTTOM - VOLUME_TOP - 2)
            )
            draw.rectangle((x - 1, VOLUME_BOTTOM - height, x + 1, VOLUME_BOTTOM), fill="#9ca3af")
    return scale, identity


def render_chart(event: pd.Series, frame: pd.DataFrame, output: Path) -> None:
    image = Image.new("RGB", CHART_SIZE, "white")
    draw = ImageDraw.Draw(image)
    font, small = _font(12), _font(10)
    bars = valid_bars(frame)
    pre = bars.loc[bars.relative_session.le(0)]
    post = bars.loc[bars.relative_session.ge(1)]
    signal = pre.loc[pre.relative_session.eq(0)]
    if len(signal) != 1 or pre.empty:
        raise ResearchError(f"chart {int(event.chart_number):05d}: missing signal-time bars")

    pre_scale, _ = _draw_panel(draw, pre, pre=True, background="#eff6ff")
    draw.text((LEFT_EDGE + 3, PRICE_TOP + 3), "PRE -126..0 | CAUSAL", fill="#1d4ed8", font=small)
    draw.text((LEFT_EDGE + 3, VOLUME_TOP + 2), "PRE TURNOVER SCALE", fill="#1d4ed8", font=small)
    for relative in (-126, -63, 0):
        x = _x(relative, pre=True)
        draw.text(
            (max(LEFT_EDGE, x - 12), PRICE_BOTTOM + 2),
            str(relative),
            fill="#4b5563",
            font=small,
        )
    signal_x = _x(0, pre=True)
    signal_y = _y(float(signal.iloc[0].coord_close), pre_scale)
    draw.line((signal_x, PRICE_TOP, signal_x, VOLUME_BOTTOM), fill="#b45309", width=2)
    draw.text((signal_x - 35, signal_y - 13), "S", fill="#92400e", font=small)

    extra_prices = [
        float(event[field])
        for field in ("entry_price", "target_price", "exit_price")
        if pd.notna(event[field]) and math.isfinite(float(event[field]))
    ]
    post_scale, post_identity = _draw_panel(
        draw,
        post,
        pre=False,
        background="#fff7ed",
        extra_prices=extra_prices,
    )
    draw.text(
        (POST_LEFT + 3, PRICE_TOP + 3),
        "POST +1..+126 | ATTRIBUTION",
        fill="#c2410c",
        font=small,
    )
    draw.text((POST_LEFT + 3, VOLUME_TOP + 2), "POST TURNOVER SCALE", fill="#c2410c", font=small)
    for relative in (1, 63, 126):
        x = _x(relative, pre=False)
        draw.text(
            (max(POST_LEFT, x - 12), PRICE_BOTTOM + 2),
            f"+{relative}",
            fill="#4b5563",
            font=small,
        )
    if post.empty:
        draw.text((POST_LEFT + 70, 190), "NO VALID POST BAR", fill="#6b7280", font=font)

    if pd.notna(event.entry_cal_idx):
        entry_idx = int(event.entry_cal_idx)
        relative = post_identity.get(entry_idx)
        if relative not in (1, 2, 3):
            raise ResearchError(
                f"chart {int(event.chart_number):05d}: illegal/missing entry marker"
            )
        entry_x = _x(int(relative), pre=False)
        entry_y = _y(float(event.entry_price), post_scale)
        _triangle(draw, entry_x, entry_y, True, "#7c3aed")
        draw.text((entry_x + 3, entry_y - 13), "E", fill="#7c3aed", font=small)
        target_y = _y(float(event.target_price), post_scale)
        for x in range(entry_x, RIGHT_EDGE + 1, 10):
            draw.line((x, target_y, min(x + 5, RIGHT_EDGE), target_y), fill="#f97316")
        draw.text((entry_x + 3, target_y - 13), "T +10%", fill="#c2410c", font=small)
    if event.status == "COMPLETED":
        exit_idx = int(event.exit_cal_idx)
        relative = post_identity.get(exit_idx)
        if relative is None or relative < 1 or relative > WINDOW:
            raise ResearchError(f"chart {int(event.chart_number):05d}: missing exit marker")
        exit_x = _x(int(relative), pre=False)
        exit_y = _y(float(event.exit_price), post_scale)
        _triangle(draw, exit_x, exit_y, False, "#111827")
        draw.text((exit_x + 3, exit_y + 4), f"X {event.exit_reason}", fill="#111827", font=small)

    draw.text(
        (6, 4),
        f"CHART {int(event.chart_number):05d} | {event.blind_chart_id}",
        fill="#111827",
        font=font,
    )
    draw.text((6, 22), "PHASE-2 ATTRIBUTION | IDENTITY HIDDEN", fill="#1e3a8a", font=small)
    draw.text((6, 39), f"OUTCOME GROUP: {event.outcome_bucket}", fill="#9a3412", font=small)
    draw.text(
        (6, 56),
        "PRE AND POST PRICE/TURNOVER SCALES ARE INDEPENDENT",
        fill="#4b5563",
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
        "chart_number": int(event.chart_number),
        "blind_chart_id": str(event.blind_chart_id),
        "outcome_bucket": str(event.outcome_bucket),
        "full_chart_path": str(output),
        "full_chart_sha256": sha256(output),
    }


def build_grids(
    frame: pd.DataFrame, output_dir: Path, bucket: str
) -> tuple[list[Path], list[dict[str, Any]]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ordered = frame.sort_values("chart_number", kind="mergesort").reset_index(drop=True)
    page_size = GRID_COLUMNS * GRID_ROWS
    paths: list[Path] = []
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
            f"V32 PHASE-2 | {bucket} | PAGE {page:04d} | {len(part)} CHARTS",
            fill="#111827",
            font=_font(13),
        )
        target = output_dir / f"sheet_{page:04d}.jpg"
        for slot, row in enumerate(part.itertuples(index=False), start=1):
            with Image.open(str(row.full_chart_path)) as chart:
                column = (slot - 1) % GRID_COLUMNS
                grid_row = (slot - 1) // GRID_COLUMNS
                sheet.paste(
                    chart.convert("RGB"),
                    (column * CHART_SIZE[0], grid_row * CHART_SIZE[1] + 28),
                )
            placements.append(
                {
                    "outcome_bucket": bucket,
                    "sheet_path": str(target),
                    "sheet_number": page,
                    "slot": slot,
                    "chart_number": int(row.chart_number),
                    "blind_chart_id": str(row.blind_chart_id),
                }
            )
        sheet.save(target, format="JPEG", quality=87, optimize=False)
        paths.append(target)
    return paths, placements


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def relative_published_path(staging: Path, value: str) -> str:
    return str(Path(value).relative_to(staging))


def reverify_before_publish(
    original_public: dict[str, str],
    original_coordinate: str,
    original_outcomes: dict[str, str],
) -> None:
    preflight, authorization, _, _ = verify_public_authorization()
    current_public = verify_public_bound_inputs(preflight, authorization)
    if current_public != original_public:
        raise ResearchError("a public bound input changed during Phase-2 rendering")
    if verify_run_coordinate_state() != original_coordinate:
        raise ResearchError("coordinate state changed during Phase-2 rendering")
    # This rehash is allowed only in --run, after authorization already passed.
    for role, path in OUTCOME_BOUND_ROLES:
        if not path.is_file() or sha256(path) != original_outcomes[role]:
            raise ResearchError(f"Stage-B artifact changed during Phase-2 rendering: {role}")


def run(workers: int) -> dict[str, Any]:
    if PHASE2_OUTPUT.exists():
        raise ResearchError(f"refusing to overwrite canonical Phase-2 output: {PHASE2_OUTPUT}")
    public_hashes, authorization, spec, manifest, blind_order = verify_public_inputs()
    assert_run_authorized(authorization, spec, manifest)
    coordinate_hash = verify_run_coordinate_state()
    run_source_hashes = {**public_hashes, "coordinate_state": coordinate_hash}

    # No Stage-B outcome-bearing path has been touched before this line.
    outcomes, outcome_hashes = verify_and_load_stage_b(blind_order, authorization)
    windows = load_windows(blind_order)
    internal_ledger = build_internal_event_ledger(blind_order, outcomes)
    window_lookup = {
        str(event_id): part for event_id, part in windows.groupby("event_id", sort=False)
    }

    PHASE2_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=".stage_e_phase2_outcome_attribution.staging-",
            dir=PHASE2_OUTPUT.parent,
        )
    )
    try:
        chart_dir = staging / "individual_full_charts"
        tasks = [
            (
                event,
                window_lookup[str(event["event_id"])],
                str(chart_dir / f"{event['blind_chart_id']}.png"),
            )
            for event in internal_ledger.to_dict("records")
        ]
        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            chart_index = pd.DataFrame(executor.map(render_worker, tasks))
        chart_index = chart_index.sort_values(
            "chart_number", kind="mergesort"
        ).reset_index(drop=True)
        if (
            len(chart_index) != EXPECTED_EVENTS
            or chart_index.chart_number.duplicated().any()
            or chart_index.blind_chart_id.duplicated().any()
            or len(list(chart_dir.glob("*.png"))) != EXPECTED_EVENTS
            or set(chart_index.outcome_bucket) - set(OUTCOME_BUCKETS)
        ):
            raise ResearchError("anonymous individual-chart coverage drift")

        all_sheet_paths: list[Path] = []
        placement_rows: list[dict[str, Any]] = []
        for bucket in OUTCOME_BUCKETS:
            subset = chart_index.loc[chart_index.outcome_bucket.eq(bucket)]
            sheets, placements = build_grids(
                subset,
                staging / "outcome_sheets" / bucket.lower(),
                bucket,
            )
            all_sheet_paths.extend(sheets)
            placement_rows.extend(placements)
        placements = pd.DataFrame(placement_rows)
        if (
            len(placements) != EXPECTED_EVENTS
            or placements.chart_number.duplicated().any()
            or placements.blind_chart_id.duplicated().any()
            or set(placements.chart_number) != set(chart_index.chart_number)
            or set(placements.outcome_bucket) != set(chart_index.outcome_bucket)
        ):
            raise ResearchError("outcome-sheet exactly-once coverage drift")
        key_columns = ["chart_number", "blind_chart_id", "outcome_bucket"]
        expected_pairs = chart_index[key_columns].sort_values("chart_number")
        actual_pairs = placements[key_columns].sort_values("chart_number")
        pd.testing.assert_frame_equal(
            expected_pairs.reset_index(drop=True),
            actual_pairs.reset_index(drop=True),
            check_dtype=False,
        )

        chart_index["full_chart_path"] = chart_index.full_chart_path.map(
            lambda value: relative_published_path(staging, value)
        )
        chart_index = chart_index[
            [
                "chart_number",
                "blind_chart_id",
                "full_chart_path",
                "full_chart_sha256",
                "outcome_bucket",
            ]
        ]
        chart_index.to_csv(staging / "phase2_chart_index.csv", index=False)

        placements["sheet_path"] = placements.sheet_path.map(
            lambda value: relative_published_path(staging, value)
        )
        placements = placements[
            [
                "outcome_bucket",
                "sheet_path",
                "sheet_number",
                "slot",
                "chart_number",
                "blind_chart_id",
            ]
        ].sort_values(["outcome_bucket", "sheet_number", "slot"], kind="mergesort")
        placements.to_csv(staging / "outcome_sheet_placements.csv", index=False)

        sheet_index_rows: list[dict[str, Any]] = []
        for (bucket, sheet_path), page in placements.groupby(
            ["outcome_bucket", "sheet_path"], sort=True
        ):
            image_path = staging / sheet_path
            sheet_index_rows.append(
                {
                    "outcome_bucket": bucket,
                    "sheet_path": sheet_path,
                    "sheet_number": int(page.sheet_number.iloc[0]),
                    "charts": len(page),
                    "first_chart": int(page.chart_number.min()),
                    "last_chart": int(page.chart_number.max()),
                    "sheet_sha256": sha256(image_path),
                }
            )
        sheet_index = pd.DataFrame(sheet_index_rows).sort_values(
            ["outcome_bucket", "sheet_number"], kind="mergesort"
        )
        if len(sheet_index) != len(all_sheet_paths) or not sheet_index.charts.between(1, 25).all():
            raise ResearchError("outcome-sheet index drift")
        sheet_index.to_csv(staging / "outcome_sheet_index.csv", index=False)

        review_template = [
            {
                "chart_number": int(row.chart_number),
                "blind_chart_id": str(row.blind_chart_id),
                "outcome_bucket": str(row.outcome_bucket),
                "post_path_label": "",
                "evidence": "",
                "reviewer": "",
                "phase1_labels_modified": False,
                "post_signal_used_as_predictor": False,
            }
            for row in chart_index.itertuples(index=False)
        ]
        write_json(staging / "phase2_review_template.json", review_template)

        bucket_counts = {
            bucket: int((chart_index.outcome_bucket == bucket).sum()) for bucket in OUTCOME_BUCKETS
        }
        bucket_pages = {
            bucket: int((sheet_index.outcome_bucket == bucket).sum()) for bucket in OUTCOME_BUCKETS
        }
        if sum(bucket_counts.values()) != EXPECTED_EVENTS:
            raise ResearchError("discovered outcome bucket counts do not sum to 1,781")
        output_hashes = {
            "phase2_chart_index": sha256(staging / "phase2_chart_index.csv"),
            "outcome_sheet_placements": sha256(staging / "outcome_sheet_placements.csv"),
            "outcome_sheet_index": sha256(staging / "outcome_sheet_index.csv"),
            "phase2_review_template": sha256(staging / "phase2_review_template.json"),
        }
        result_manifest = {
            "experiment": EXPERIMENT,
            "stage": "STAGE_E_PHASE2_ANONYMOUS_OUTCOME_ATTRIBUTION_CORPUS",
            "asset_id": ASSET_ID,
            "authorization_id": AUTHORIZATION_ID,
            "authorized_arm": AUTHORIZED_ARM,
            "events": EXPECTED_EVENTS,
            "individual_full_charts": EXPECTED_EVENTS,
            "outcome_contact_sheets": len(all_sheet_paths),
            "outcome_bucket_definitions": BUCKET_DEFINITIONS,
            "outcome_bucket_counts_discovered_after_authorized_read": bucket_counts,
            "outcome_bucket_page_counts": bucket_pages,
            "window_relative_sessions": [-WINDOW, WINDOW],
            "window_slots_per_event": WINDOW_ROWS,
            "minimum_chart_date": str(windows.trade_date.min().date()),
            "maximum_chart_date": str(windows.trade_date.max().date()),
            "source_hashes": {**run_source_hashes, **outcome_hashes},
            "coordinate_state_sha256": coordinate_hash,
            "phase1_annotation_ledger_sha256": PUBLIC_FIXED_HASHES[PHASE1_LEDGER],
            "phase1_annotation_manifest_sha256": PUBLIC_FIXED_HASHES[PHASE1_REVIEW_MANIFEST],
            "phase1_reviewer_drift_freeze_sha256": PUBLIC_FIXED_HASHES[
                PHASE1_REVIEWER_DRIFT_FREEZE
            ],
            "phase2_annotation_schema_sha256": PUBLIC_FIXED_HASHES[
                PHASE2_ANNOTATION_SCHEMA
            ],
            "phase2_chart_index_sha256": output_hashes["phase2_chart_index"],
            "outcome_sheet_placements_sha256": output_hashes[
                "outcome_sheet_placements"
            ],
            "outcome_sheet_index_sha256": output_hashes["outcome_sheet_index"],
            "phase2_review_template_sha256": output_hashes["phase2_review_template"],
            "output_hashes": output_hashes,
            "individual_coverage_exactly_once": True,
            "anonymous_identity_coverage_exactly_once": True,
            "outcome_group_coverage_exactly_once": True,
            "identity_mapping_reconstructed_in_memory": True,
            "identity_crosswalk_persisted": False,
            "identity_exposed_to_reviewer": False,
            "phase1_labels_modified": False,
            "pre_post_price_scales_independent": True,
            "pre_post_turnover_scales_independent": True,
            "post_2020_row_read": False,
            "2021_plus_row_read": False,
            "rule_search_performed": False,
            "rule_aggregation_performed": False,
            "portfolio_replay_performed": False,
            "candidate_reselection_performed": False,
            "post_signal_used_as_predictor": False,
            "next_step": "REVIEW_AND_FREEZE_ALL_1781_PHASE2_ATTRIBUTIONS_WITHOUT_REWRITING_PHASE1",
        }
        write_json(staging / "manifest.json", result_manifest)

        reverify_before_publish(public_hashes, coordinate_hash, outcome_hashes)
        if PHASE2_OUTPUT.exists():
            raise ResearchError(f"refusing publication race overwrite: {PHASE2_OUTPUT}")
        staging.replace(PHASE2_OUTPUT)
        return {
            **result_manifest,
            "manifest_sha256": sha256(PHASE2_OUTPUT / "manifest.json"),
            "output": str(PHASE2_OUTPUT),
        }
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--verify-public-inputs",
        action="store_true",
        help=(
            "verify CY-044, frozen Phase-1/public inputs, and the reconstructed blind order; "
            "never stat/hash/open Stage-B result, future_paths, or outcomes"
        ),
    )
    modes.add_argument(
        "--run",
        action="store_true",
        help="after CY-044 authorization, render the anonymous Phase-2 attribution corpus",
    )
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.verify_public_inputs:
        hashes, _, _, _, blind_order = verify_public_inputs()
        print(
            json.dumps(
                {
                    "verified": True,
                    "mode": "PUBLIC_ONLY_NO_STAGE_B_OUTCOME_FILE_TOUCH",
                    "events": len(blind_order),
                    "phase1_ledger_sha256": PUBLIC_FIXED_HASHES[PHASE1_LEDGER],
                    "phase1_manifest_sha256": PUBLIC_FIXED_HASHES[PHASE1_REVIEW_MANIFEST],
                    "source_hashes": hashes,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    print(json.dumps(run(args.workers), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
