#!/usr/bin/env python3
"""Build the strictly anonymous, outcome-blind V34R1 Phase-1 chart corpus.

Only the frozen Stage-B prepared candidate identities, the certified 2017
chronology extension, canonical CY-006 2018--2020 partitions, and the accepted
action-coordinate state are data inputs.  Result, future-path, and outcome
artifacts are declaration-only strings: this module never stats, hashes, opens,
or parses them.  No post-signal row can reach a query or renderer.
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

EXPERIMENT = "ASHARE-CASH-DISTRIBUTION-REALIZED-PAYOUT-QUALITY-MOTHER-V34R1"
REPO = Path(__file__).resolve().parents[3]
EXP = REPO / "research/market_behavior_os_v2/experiments"
PARENT_SPEC = EXP / f"{EXPERIMENT}_freeze.json"
STAGE_B_SPEC = EXP / f"{EXPERIMENT}_stage_b_freeze.json"
STAGE_A_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_cash_distribution_realized_payout_quality_mother_v34r1_stage_a.py"
)
STAGE_B_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_cash_distribution_realized_payout_quality_mother_v34r1_stage_b.py"
)
STAGE_A_MANIFEST = EXP / "ASHARE-V34R1-CY047_DATA_ASSET_MANIFEST.json"
STAGE_B_MANIFEST = EXP / "ASHARE-V34R1-CY049_DATA_ASSET_MANIFEST.json"
CHRONOLOGY_AUDIT = EXP / "ASHARE-TAIL-OPEN-LGBM-V1_chronology_extension_audit.json"
REVIEW_SPEC = EXP / f"{EXPERIMENT}_visual_review_spec.json"
ANNOTATION_SCHEMA = EXP / "ASHARE-V34R1_phase1_anonymous_annotation_schema.json"
CHART_ASSET_MANIFEST = EXP / "ASHARE-V34R1-CY052_CHART_REVIEW_ASSET_MANIFEST.json"
REGISTRY = REPO / "configs/data_asset_registry.json"
COORDINATE_BUILDER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_former_leader_strict_gap_reclaim_v3.py"
)
COORDINATE_CONTRACT = REPO / "src/cyq_game/chip/price_coordinate.py"

DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
CHRONOLOGY_ROOT = DATA_ROOT / "ashare_tail_open_lgbm_v1/pit_daily_2013_2023_cy006"
CHRONOLOGY_2017 = CHRONOLOGY_ROOT / "daily/partition_year=2017/data_0.parquet"
CHRONOLOGY_DAILY_AUDIT = CHRONOLOGY_ROOT / "audit.json"
CY006_ROOT = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2")
CY006_MANIFEST = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "CY-006-pit-b-daily-v2-2018-2026-20260821.json"
)
CY006_PARTITIONS = tuple(
    CY006_ROOT / f"daily/partition_year={year}/data_0.parquet"
    for year in range(2018, 2021)
)
RAW_DAILY_PARTITIONS = (CHRONOLOGY_2017, *CY006_PARTITIONS)
COORDINATE_STATE = DATA_ROOT / (
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_adjusted_daily_state_2013_2023.parquet"
)
OUTPUT_ROOT = DATA_ROOT / "ashare_cash_distribution_realized_payout_quality_mother_v34r1"
STAGE_B = OUTPUT_ROOT / "stage_b"
PREPARED = STAGE_B / "prepared_candidates.parquet"

# Declaration-only identities.  These constants may be compared with public
# authorization metadata, but their Path objects must never be inspected in
# Phase 1.  A separate Phase-2 authorization must bind and verify them.
STAGE_B_RESULT = STAGE_B / "result.json"
FUTURE_PATHS = STAGE_B / "future_paths.parquet"
OUTCOMES = STAGE_B / "outcomes.parquet"
DECLARED_ONLY_STAGE_B_OUTCOMES = {
    "stage_b_result": (
        STAGE_B_RESULT,
        "cec33ec8e571effe73e86f7517a0c5cebcf09c07d41850202fc9ca8cf3cb84eb",
    ),
    "stage_b_future_paths": (
        FUTURE_PATHS,
        "371db6417b92974fa1d1860d67f89dab7654b97c95e97dad25be0d7f0d9050a5",
    ),
    "stage_b_outcomes": (
        OUTCOMES,
        "ef21c19376e1db63bbbbfe8b2e9b62b436a647168cbd83640f7f14ad8312c356",
    ),
}

CHART_ROOT = OUTPUT_ROOT / "stage_c_phase1_anonymous_charts"
ASSET_ID = "CY-052"
DEPENDENCY_ASSET_ID = "CY-049"
AUTHORIZATION_ID = (
    "CYQ-AUTH-ASHARE-CASH-DISTRIBUTION-PAYOUT-QUALITY-"
    "V34R1-PHASE1-CY052-ANONYMOUS-CHARTS-2018-2020-V1"
)
AUTHORIZATION_PURPOSE = "ASHARE_FROZEN_DEVELOPMENT_CHART_REVIEW"
AUTHORIZED_ARM = "V34R1_CY052_PHASE1_ANONYMOUS_CAUSAL_CHARTS_ONLY"
MANIFEST_STATUS = "FROZEN_DEVELOPMENT_CHART_REVIEW_BOUNDED_INPUT"
PIPELINE_VERSION = "v34r1-phase1-anonymous-causal-chart-review-v2"

REPO_FIXED_HASHES: dict[Path, str] = {
    PARENT_SPEC: "e41bfe9de6c68878ea556cf31397075adda9076adc19a4089215284436c6bdb4",
    STAGE_B_SPEC: "94def5859b602bde8a635d2e4079c9aea4c1c27bee4161843259ac9dfb928041",
    STAGE_A_RUNNER: "deb4856ab9cf21cb117428db3e54f45cc0422cf5eef5ca8eebcb2e12357167d1",
    STAGE_B_RUNNER: "8755bbe18ca76c788ca74ed1743a34bbbd09c8ffc75889b49f026c7e2fad13e5",
    STAGE_A_MANIFEST: "4f3453d0afadf14e71fe332c7d84e49c0842253b152849281a6dfc40f3a5655f",
    STAGE_B_MANIFEST: "88789d69a4cc4e68d13eefcd8ccf09376f6588b4861939c0c8b0158bdf2be877",
    CHRONOLOGY_AUDIT: "e57ed5cf1730d53cd156cad162271c6be29f1c7074a257bbad81f22b09cd993f",
    COORDINATE_BUILDER: "358b62014c52b7bf936937746223954512fe9451eaa5009063e14f39e1bb1787",
    COORDINATE_CONTRACT: "60c9f80fcaa2bf4a6ebfaab37bc56e81dd716cc3bea00891b4fc28d077dd1726",
    ANNOTATION_SCHEMA: "89eeb590b025a4d126d328acbd47a803696606a891a8b804264bf326705fb90d",
}
ALLOWED_DATA_HASHES: dict[Path, str] = {
    PREPARED: "7f103518ca4fd00628ab1d7fddf97367aa208adce099aa3894008d92afa4a52b",
    CHRONOLOGY_2017: "5a8d7b0d48d4ff3b9323c53a812539115bb62a2cfe197369ef3b5f5499816f88",
    CY006_MANIFEST: "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2",
    CY006_PARTITIONS[0]: "b906d2c21fd35128b8f65f1b00fa12ae6e5bd9ee476a368a63881304f38ceed4",
    CY006_PARTITIONS[1]: "c69a464e4a04efdca0177a8a09a13a34646531afa37a2b35b4892fd40ec3ebfd",
    CY006_PARTITIONS[2]: "1b0a00c6d2cfbce0ae4f907e1ee9dc5006f59677d556cc10f8f34a9893937c62",
    COORDINATE_STATE: "76fe88cb7509ae33a3d32b1bfd6d0c90560083127bdfaf63da1d7d24ec72bf60",
    CHRONOLOGY_DAILY_AUDIT: "8071fdae37f38f9ef8bca18815c3ddc1ddd9a89a83df6761aec015818249c752",
}
SOURCE_ROLE_BINDINGS: dict[str, tuple[Path, str]] = {
    "stage_b_prepared_candidates": (PREPARED, ALLOWED_DATA_HASHES[PREPARED]),
    "chronology_extension_2017": (
        CHRONOLOGY_2017,
        ALLOWED_DATA_HASHES[CHRONOLOGY_2017],
    ),
    "cy006_manifest": (CY006_MANIFEST, ALLOWED_DATA_HASHES[CY006_MANIFEST]),
    "cy006_2018": (CY006_PARTITIONS[0], ALLOWED_DATA_HASHES[CY006_PARTITIONS[0]]),
    "cy006_2019": (CY006_PARTITIONS[1], ALLOWED_DATA_HASHES[CY006_PARTITIONS[1]]),
    "cy006_2020": (CY006_PARTITIONS[2], ALLOWED_DATA_HASHES[CY006_PARTITIONS[2]]),
    "coordinate_state": (COORDINATE_STATE, ALLOWED_DATA_HASHES[COORDINATE_STATE]),
    "chronology_daily_pit_audit": (
        CHRONOLOGY_DAILY_AUDIT,
        ALLOWED_DATA_HASHES[CHRONOLOGY_DAILY_AUDIT],
    ),
}
PUBLIC_ROLE_BINDINGS: dict[str, tuple[Path, str]] = {
    "parent_spec": (PARENT_SPEC, REPO_FIXED_HASHES[PARENT_SPEC]),
    "stage_b_spec": (STAGE_B_SPEC, REPO_FIXED_HASHES[STAGE_B_SPEC]),
    "stage_a_runner": (STAGE_A_RUNNER, REPO_FIXED_HASHES[STAGE_A_RUNNER]),
    "stage_b_runner": (STAGE_B_RUNNER, REPO_FIXED_HASHES[STAGE_B_RUNNER]),
    "stage_a_manifest": (STAGE_A_MANIFEST, REPO_FIXED_HASHES[STAGE_A_MANIFEST]),
    "stage_b_manifest": (STAGE_B_MANIFEST, REPO_FIXED_HASHES[STAGE_B_MANIFEST]),
    "chronology_extension_audit": (
        CHRONOLOGY_AUDIT,
        REPO_FIXED_HASHES[CHRONOLOGY_AUDIT],
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
SOURCE_LINEAGE_PUBLIC_ROLES = {
    role: PUBLIC_ROLE_BINDINGS[role]
    for role in (
        "chronology_extension_audit",
        "coordinate_builder",
        "corporate_action_coordinate_contract",
    )
}

EXPECTED_EVENTS = 1_483
EXPECTED_ANNUAL = {2018: 395, 2019: 520, 2020: 568}
SIGNAL_START = pd.Timestamp("2018-03-27")
SIGNAL_END = pd.Timestamp("2020-12-01")
WINDOW = 126
WINDOW_ROWS = 127
OPAQUE_ORDER_SALT = "V34R1_PHASE1_CAUSAL_MASKED_ORDER_V1"
MIN_MARKET_MEMBERS = 500
FAILED_PREPUBLICATION_SOURCE_ATTEMPT = {
    "status": "FAILED_PREPUBLICATION_SOURCE_COVERAGE",
    "source_role": "retired_v30_causal_daily_compact",
    "expected_signal_rows": 1_483,
    "present_exact_valid_signal_rows": 1_149,
    "absent_exact_signal_rows": 334,
    "missing_exact_signal_identity_set_sha256": (
        "9cdbad45139fb75bd98ad5ba25d08c4ad48712a0c0019330547ef3885a37ed0b"
    ),
    "canonical_output_created": False,
    "runner_owned_staging_left": False,
    "outcome_artifact_statted_hashed_opened_or_parsed": False,
}
FAILED_PREPUBLICATION_TRANSFORM_ATTEMPT = {
    "status": "FAILED_PREPUBLICATION_TRANSFORM_GEOMETRY",
    "expected_signal_rows": 1_483,
    "present_exact_valid_signal_rows": 1_480,
    "rejected_signal_rows": 3,
    "rejected_event_identity_set_sha256": (
        "e956a03428885a7350cf97f60c30598482c0fd072eac5314b7694cc2f8e39c07"
    ),
    "first_differing_predicate": "transformed_ohlc_geometry_only",
    "raw_source_ohlc_geometry_failures": 0,
    "maximum_high_deficit": 1.1102230246251565e-16,
    "maximum_low_excess": 2.220446049250313e-16,
    "scientific_correction": (
        "preserve raw values; compute adjusted OHLC as adjusted_close times "
        "raw_price divided by raw_close so exact raw equality remains exact"
    ),
    "canonical_output_created": False,
    "runner_owned_staging_left": False,
    "outcome_artifact_statted_hashed_opened_or_parsed": False,
}

PRIMARY_MORPHOLOGY = (
    "BASE_COMPRESSION",
    "ORDERLY_UPTREND",
    "EXTENDED_OR_SPIKE",
    "DOWNTREND_OR_BREAKDOWN",
    "CHOPPY_NO_STRUCTURE",
)
MARKET_TAPE = ("BROAD_UP", "BROAD_DOWN", "MIXED_TRANSITION")
SIGNAL_CANDLE = ("STRONG_CLOSE", "WEAK_CLOSE", "NEUTRAL")
TURNOVER_STATE = ("DRY_OR_CONTRACTING", "SURGE_OR_EXPANDING", "NORMAL_MIXED")

CHART_SIZE = (720, 440)
LEFT_EDGE, RIGHT_EDGE = 42, 710
PRICE_TOP, PRICE_BOTTOM = 88, 274
MARKET_TOP, MARKET_BOTTOM = 290, 339
TURNOVER_TOP, TURNOVER_BOTTOM = 355, 424
GRID_COLUMNS, GRID_ROWS = 5, 5
EXPECTED_SHEETS = 60


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


def verify_failed_source_receipt(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise ResearchError(f"{label} failed-source receipt missing")
    required = {
        "status": "FAILED_PREPUBLICATION_SOURCE_COVERAGE",
        "expected_signal_rows": 1_483,
        "present_exact_valid_signal_rows": 1_149,
        "absent_exact_signal_rows": 334,
        "missing_exact_signal_identity_set_sha256": (
            "9cdbad45139fb75bd98ad5ba25d08c4ad48712a0c0019330547ef3885a37ed0b"
        ),
        "canonical_output_created": False,
        "runner_owned_staging_left": False,
    }
    if any(value.get(key) != expected for key, expected in required.items()):
        raise ResearchError(f"{label} failed-source receipt drift")
    outcome_key = (
        "stage_b_outcome_artifact_statted_hashed_opened_or_parsed"
        if "stage_b_outcome_artifact_statted_hashed_opened_or_parsed" in value
        else "outcome_artifact_statted_hashed_opened_or_parsed"
    )
    if value.get(outcome_key) is not False:
        raise ResearchError(f"{label} failed-source outcome boundary drift")


def verify_failed_transform_receipt(value: Any, label: str) -> None:
    if value != FAILED_PREPUBLICATION_TRANSFORM_ATTEMPT:
        raise ResearchError(f"{label} failed-transform receipt drift")


def verify_public_authorization() -> tuple[dict[str, str], dict[str, Any]]:
    """Verify only public repository contracts; do not touch any data artifact."""
    required = (
        REGISTRY,
        REVIEW_SPEC,
        ANNOTATION_SCHEMA,
        CHART_ASSET_MANIFEST,
        Path(__file__),
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ResearchError(f"missing public CY-052 authorization input: {missing}")
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
    required_false = (
        "outcome_artifact_parse_authorized",
        "outcome_artifact_hash_authorized",
        "outcome_artifact_stat_authorized",
        "outcome_artifact_open_authorized",
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
        "causal_daily_compact_read_authorized",
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
        or authorization.get("purpose") != AUTHORIZATION_PURPOSE
        or authorization.get("authorized_arms") != [AUTHORIZED_ARM]
        or bound_manifest.get("path") != str(CHART_ASSET_MANIFEST)
        or bound_manifest.get("sha256") != actual["chart_asset_manifest"]
        or authorization.get("charts_authorized") is not True
        or authorization.get("phase1_anonymous_charts_authorized") is not True
        or authorization.get("stage_b_prepared_candidates_read_authorized") is not True
        or authorization.get("hybrid_raw_daily_partitions_read_authorized") is not True
        or authorization.get("coordinate_state_bounded_row_read_authorized") is not True
        or authorization.get("source_lineage_metadata_hash_authorized") is not True
        or authorization.get("coverage_preflight_authorized") is not True
        or any(authorization.get(key) is not False for key in required_false)
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
        raise ResearchError("CY-052 registry authorization semantics drift")
    verify_failed_source_receipt(
        asset.get("quality_evidence", {}).get("failed_prepublication_source_attempt"),
        "CY-052 registry asset",
    )
    verify_failed_transform_receipt(
        asset.get("quality_evidence", {}).get(
            "failed_prepublication_transform_attempt"
        ),
        "CY-052 registry asset",
    )

    # Complete lexical joint binding precedes every external-data stat/hash/read.
    # Absolute Path construction and str() are pure here; no artifact is resolved.
    artifacts = role_map(authorization.get("bound_artifacts", []), "bound_artifacts")
    expected_declarations = {
        **{
            role: (str(path), digest)
            for role, (path, digest) in PUBLIC_ROLE_BINDINGS.items()
        },
        **{
            role: (str(path), digest)
            for role, (path, digest) in SOURCE_ROLE_BINDINGS.items()
        },
        **{
            role: (str(path), digest)
            for role, (path, digest) in DECLARED_ONLY_STAGE_B_OUTCOMES.items()
        },
    }
    if set(artifacts) != set(expected_declarations):
        raise ResearchError(
            "CY-052 public bound_artifacts role-set drift: "
            f"missing={sorted(set(expected_declarations) - set(artifacts))}, "
            f"extra={sorted(set(artifacts) - set(expected_declarations))}"
        )
    for role, (path_text, digest) in expected_declarations.items():
        item = artifacts[role]
        if item.get("path") != path_text or item.get("sha256") != digest:
            raise ResearchError(f"CY-052 public lexical binding drift: {role}")

    spec = load_json(REVIEW_SPEC, "V34R1 visual-review spec")
    renderer = spec.get("renderer", {})
    schema = spec.get("annotation_schema", {})
    spec_authorization = spec.get("required_authorization", {})
    permissions = spec_authorization.get("permissions", {})
    spec_inputs = spec.get("permitted_data_inputs", {})
    spec_prepared = spec_inputs.get("stage_b_prepared_candidates", {})
    spec_source_roles = role_map(
        spec_inputs.get("hybrid_source_artifacts", []),
        "spec hybrid_source_artifacts",
    )
    spec_lineage_roles = role_map(
        spec.get("source_lineage_contracts", []),
        "spec source_lineage_contracts",
    )
    spec_declared = spec.get("declared_only_unread_stage_b_artifacts", {})
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
        or spec_authorization.get("asset_id") != ASSET_ID
        or spec_authorization.get("dependency_asset_id") != DEPENDENCY_ASSET_ID
        or spec_authorization.get("authorization_id") != AUTHORIZATION_ID
        or spec_authorization.get("purpose") != AUTHORIZATION_PURPOSE
        or spec_authorization.get("authorized_arm") != AUTHORIZED_ARM
        or permissions.get("charts_authorized") is not True
        or permissions.get("phase1_anonymous_charts_authorized") is not True
        or permissions.get("stage_b_prepared_candidates_read_authorized") is not True
        or permissions.get("hybrid_raw_daily_partitions_read_authorized") is not True
        or permissions.get("coordinate_state_bounded_row_read_authorized") is not True
        or permissions.get("source_lineage_metadata_hash_authorized") is not True
        or permissions.get("coverage_preflight_authorized") is not True
        or spec_prepared.get("path") != str(PREPARED)
        or spec_prepared.get("sha256") != ALLOWED_DATA_HASHES[PREPARED]
        or spec_prepared.get("rows") != EXPECTED_EVENTS
        or set(spec_source_roles) != set(SOURCE_ROLE_BINDINGS)
        or any(
            spec_source_roles[role].get("path") != str(path)
            or spec_source_roles[role].get("sha256") != digest
            for role, (path, digest) in SOURCE_ROLE_BINDINGS.items()
        )
        or set(spec_lineage_roles) != set(SOURCE_LINEAGE_PUBLIC_ROLES)
        or any(
            spec_lineage_roles[role].get("path") != str(path)
            or spec_lineage_roles[role].get("sha256") != digest
            for role, (path, digest) in SOURCE_LINEAGE_PUBLIC_ROLES.items()
        )
        or spec_declared.get("result", {}).get("path") != str(STAGE_B_RESULT)
        or spec_declared.get("result", {}).get("sha256")
        != DECLARED_ONLY_STAGE_B_OUTCOMES["stage_b_result"][1]
        or spec_declared.get("future_paths", {}).get("path") != str(FUTURE_PATHS)
        or spec_declared.get("future_paths", {}).get("sha256")
        != DECLARED_ONLY_STAGE_B_OUTCOMES["stage_b_future_paths"][1]
        or spec_declared.get("outcomes", {}).get("path") != str(OUTCOMES)
        or spec_declared.get("outcomes", {}).get("sha256")
        != DECLARED_ONLY_STAGE_B_OUTCOMES["stage_b_outcomes"][1]
        or any(permissions.get(key) is not False for key in required_false)
    ):
        raise ResearchError("V34R1 Phase-1 visual-review spec binding drift")
    verify_failed_source_receipt(
        spec.get("failed_prepublication_source_attempt"), "V34R1 Phase-1 spec"
    )
    verify_failed_transform_receipt(
        spec.get("failed_prepublication_transform_attempt"),
        "V34R1 Phase-1 spec",
    )

    manifest = load_json(CHART_ASSET_MANIFEST, "CY-052 chart manifest")
    boundary = manifest.get("authorization_boundary", {})
    manifest_protocol = manifest.get("protocol", {})
    manifest_prepared = manifest.get("frozen_cohort", {}).get(
        "stage_b_prepared_candidates", {}
    )
    manifest_source_roles = role_map(
        manifest.get("hybrid_source_artifacts", []),
        "manifest hybrid_source_artifacts",
    )
    manifest_lineage_roles = role_map(
        manifest.get("source_lineage_contracts", []),
        "manifest source_lineage_contracts",
    )
    manifest_declared = manifest.get("declared_only_unread_stage_b_artifacts", {})
    if (
        manifest.get("asset_id") != ASSET_ID
        or manifest.get("status") != MANIFEST_STATUS
        or manifest.get("pipeline_version") != PIPELINE_VERSION
        or boundary.get("authorization_id") != AUTHORIZATION_ID
        or boundary.get("purpose") != AUTHORIZATION_PURPOSE
        or boundary.get("authorized_arm") != AUTHORIZED_ARM
        or boundary.get("dependency_asset_id") != DEPENDENCY_ASSET_ID
        or boundary.get("charts_authorized") is not True
        or boundary.get("phase1_anonymous_charts_authorized") is not True
        or boundary.get("stage_b_prepared_candidates_read_authorized") is not True
        or boundary.get("hybrid_raw_daily_partitions_read_authorized") is not True
        or boundary.get("coordinate_state_bounded_row_read_authorized") is not True
        or boundary.get("source_lineage_metadata_hash_authorized") is not True
        or boundary.get("coverage_preflight_authorized") is not True
        or boundary.get("signal_start") != str(SIGNAL_START.date())
        or boundary.get("signal_end") != str(SIGNAL_END.date())
        or boundary.get("maximum_chart_date") != str(SIGNAL_END.date())
        or boundary.get("phase1_relative_global_sessions") != [-WINDOW, 0]
        or any(boundary.get(key) is not False for key in required_false)
        or manifest_prepared.get("path") != str(PREPARED)
        or manifest_prepared.get("sha256") != ALLOWED_DATA_HASHES[PREPARED]
        or manifest_prepared.get("rows") != EXPECTED_EVENTS
        or set(manifest_source_roles) != set(SOURCE_ROLE_BINDINGS)
        or any(
            manifest_source_roles[role].get("path") != str(path)
            or manifest_source_roles[role].get("sha256") != digest
            for role, (path, digest) in SOURCE_ROLE_BINDINGS.items()
        )
        or set(manifest_lineage_roles) != set(SOURCE_LINEAGE_PUBLIC_ROLES)
        or any(
            manifest_lineage_roles[role].get("path") != str(path)
            or manifest_lineage_roles[role].get("sha256") != digest
            for role, (path, digest) in SOURCE_LINEAGE_PUBLIC_ROLES.items()
        )
        or manifest_declared.get("result", {}).get("path") != str(STAGE_B_RESULT)
        or manifest_declared.get("result", {}).get("sha256")
        != DECLARED_ONLY_STAGE_B_OUTCOMES["stage_b_result"][1]
        or manifest_declared.get("future_paths", {}).get("path") != str(FUTURE_PATHS)
        or manifest_declared.get("future_paths", {}).get("sha256")
        != DECLARED_ONLY_STAGE_B_OUTCOMES["stage_b_future_paths"][1]
        or manifest_declared.get("outcomes", {}).get("path") != str(OUTCOMES)
        or manifest_declared.get("outcomes", {}).get("sha256")
        != DECLARED_ONLY_STAGE_B_OUTCOMES["stage_b_outcomes"][1]
        or manifest_protocol.get("visual_review_spec_sha256")
        != actual["visual_review_spec"]
        or manifest_protocol.get("chart_runner_sha256") != actual["chart_runner"]
        or manifest_protocol.get("annotation_schema_sha256")
        != actual["annotation_schema"]
    ):
        raise ResearchError("CY-052 chart manifest binding drift")
    verify_failed_source_receipt(
        manifest.get("failed_prepublication_source_attempt"), "CY-052 manifest"
    )
    verify_failed_transform_receipt(
        manifest.get("failed_prepublication_transform_attempt"),
        "CY-052 manifest",
    )
    return actual, authorization


def _require_bound_role(
    artifacts: dict[str, dict[str, Any]], role: str, path: Path, digest: str
) -> None:
    item = artifacts.get(role)
    if item is None or item.get("path") != str(path) or item.get("sha256") != digest:
        raise ResearchError(f"CY-052 authorization does not bind {role}")


def verify_allowed_bound_inputs(
    preflight: dict[str, str], authorization: dict[str, Any]
) -> dict[str, str]:
    """After joint authorization, hash only explicitly permitted source inputs."""
    artifacts = role_map(authorization.get("bound_artifacts", []), "bound_artifacts")
    expected_roles = {
        *PUBLIC_ROLE_BINDINGS,
        *SOURCE_ROLE_BINDINGS,
        *DECLARED_ONLY_STAGE_B_OUTCOMES,
    }
    if set(artifacts) != expected_roles:
        raise ResearchError(
            "CY-052 bound_artifacts role-set drift: "
            f"missing={sorted(expected_roles - set(artifacts))}, "
            f"extra={sorted(set(artifacts) - expected_roles)}"
        )
    actual = dict(preflight)
    for role, (path, expected) in PUBLIC_ROLE_BINDINGS.items():
        if not path.is_file():
            raise ResearchError(f"missing bound public input {role}: {path}")
        value = sha256(path)
        if value != expected:
            raise ResearchError(f"frozen public input drift: {role}")
        _require_bound_role(artifacts, role, path, value)
        actual[role] = value

    for role, (path, expected) in SOURCE_ROLE_BINDINGS.items():
        if not path.is_file():
            raise ResearchError(f"missing permitted data input {role}: {path}")
        value = sha256(path)
        if value != expected:
            raise ResearchError(f"permitted data input drift: {role}")
        _require_bound_role(artifacts, role, path, value)
        actual[role] = value

    # Declaration checks only.  Never call exists/is_file/stat/resolve/sha256/open
    # on any path in DECLARED_ONLY_STAGE_B_OUTCOMES in this Phase-1 runner.
    for role, (path, digest) in DECLARED_ONLY_STAGE_B_OUTCOMES.items():
        _require_bound_role(artifacts, role, path, digest)
        actual[f"{role}_declared_only_unread_in_phase1"] = digest
    return actual


def require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ResearchError(f"{label} missing columns: {missing}")


def load_and_audit_identities() -> pd.DataFrame:
    columns = [
        "event_id",
        "symbol",
        "signal_date",
        "source_signal_cal_idx",
        "signal_cal_idx",
        "invalid_step_cum",
        "decision_at",
        "known_at",
        "signal_row_available_at",
        "signal_row_decision_at",
        "execution_raw_signal_date",
        "coordinate_signal_date",
        "signal_corporate_action_count",
    ]
    prepared = pd.read_parquet(PREPARED, columns=columns)
    require_columns(prepared, set(columns), "Stage-B prepared candidates")
    if prepared.event_id.isna().any():
        raise ResearchError("prepared candidates contain a null event_id")
    prepared["event_id"] = prepared.event_id.astype(str)
    for column in (
        "signal_date",
        "decision_at",
        "known_at",
        "signal_row_available_at",
        "signal_row_decision_at",
        "execution_raw_signal_date",
        "coordinate_signal_date",
    ):
        prepared[column] = pd.to_datetime(prepared[column])
    annual = {
        int(year): int(count)
        for year, count in prepared.signal_date.dt.year.value_counts().items()
    }
    offset = prepared.signal_cal_idx - prepared.source_signal_cal_idx
    required_numeric = prepared[
        [
            "source_signal_cal_idx",
            "signal_cal_idx",
            "invalid_step_cum",
            "signal_corporate_action_count",
        ]
    ].apply(pd.to_numeric, errors="coerce")
    if (
        len(prepared) != EXPECTED_EVENTS
        or prepared.event_id.duplicated().any()
        or prepared[list(set(columns) - {"event_id"})].isna().any(axis=1).any()
        or not np.isfinite(required_numeric).all(axis=None)
        or prepared.signal_date.min() != SIGNAL_START
        or prepared.signal_date.max() != SIGNAL_END
        or annual != EXPECTED_ANNUAL
        or offset.nunique(dropna=False) != 1
        or not prepared.execution_raw_signal_date.eq(prepared.signal_date).all()
        or not prepared.coordinate_signal_date.eq(prepared.signal_date).all()
        or prepared.known_at.gt(prepared.decision_at).any()
        or prepared.signal_row_available_at.gt(prepared.signal_row_decision_at).any()
        or not prepared.signal_row_decision_at.eq(prepared.decision_at).all()
        or not prepared.signal_corporate_action_count.eq(1).all()
    ):
        raise ResearchError("frozen prepared-candidate identity or chronology drift")
    return prepared


def load_causal_windows(prepared: pd.DataFrame) -> pd.DataFrame:
    """Join bounded raw daily OHLC to the accepted causal coordinate."""
    chart_keys = prepared[
        [
            "event_id",
            "symbol",
            "signal_date",
            "signal_cal_idx",
            "invalid_step_cum",
            "decision_at",
        ]
    ].rename(
        columns={
            "invalid_step_cum": "signal_invalid_step_cum",
            "decision_at": "signal_decision_at",
        }
    )
    connection = duckdb.connect()
    connection.execute("SET threads=4")
    connection.register("chart_keys", chart_keys)
    raw_paths = "[" + ",".join(
        f"'{path.as_posix()}'" for path in RAW_DAILY_PARTITIONS
    ) + "]"
    windows = connection.execute(
        f"""
        WITH calendar_pairs AS (
          SELECT trade_date,cal_idx
          FROM read_parquet('{COORDINATE_STATE.as_posix()}')
          WHERE trade_date BETWEEN DATE '2017-01-01' AND DATE '{SIGNAL_END.date()}'
          GROUP BY trade_date,cal_idx
        ), calendar AS (
          SELECT *,count(*) OVER(PARTITION BY trade_date) AS date_cal_idx_versions,
            count(*) OVER(PARTITION BY cal_idx) AS cal_idx_date_versions
          FROM calendar_pairs
        ), bounds AS (
          SELECT min(signal_cal_idx)-{WINDOW} AS first_idx,
                 max(signal_cal_idx) AS last_idx
          FROM chart_keys
        ), expanded AS (
          SELECT k.event_id,k.symbol,k.signal_date,k.signal_cal_idx,
            k.signal_invalid_step_cum,k.signal_decision_at,
            c.trade_date,c.cal_idx,c.cal_idx-k.signal_cal_idx AS relative_session,
            c.date_cal_idx_versions,c.cal_idx_date_versions
          FROM chart_keys k
          JOIN calendar c
            ON c.cal_idx BETWEEN k.signal_cal_idx-{WINDOW} AND k.signal_cal_idx
        ), raw AS (
          SELECT d.trade_date,d.symbol,d.open,d.high,d.low,d.close,
            d.turnover_fraction,d.is_st,d.trade_status,
            d.current_day_data_tradable,d.hard_valid,d.bar_valid,
            d.trading_state_valid,d.market_rule_valid,d.corporate_action_count,
            d.corporate_action_valid,d.corporate_action_blocking,
            d.historical_identity_valid,d.industry_valid,
            d.available_at,d.decision_at AS bar_decision_at
          FROM read_parquet({raw_paths},union_by_name=true) d
          JOIN calendar k USING(trade_date),bounds b
          WHERE d.trade_date BETWEEN DATE '2017-01-01' AND DATE '{SIGNAL_END.date()}'
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
            AND c.trade_date BETWEEN DATE '2017-01-01' AND DATE '{SIGNAL_END.date()}'
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
            count(*) FILTER(WHERE cal_idx IS NOT NULL AND source_identity_match IS NOT TRUE)
              AS raw_coordinate_identity_mismatches
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
            AND hard_valid AND bar_valid AND trading_state_valid
            AND current_day_data_tradable AND trade_status=1
            AND market_rule_valid AND corporate_action_valid
            AND NOT corporate_action_blocking
            AND coordinate_action_valid AND NOT coordinate_action_blocking
            AND historical_identity_valid AND industry_valid AND NOT is_st
            AND source_identity_match AND available_at<=bar_decision_at
            AND isfinite(step_return) AND step_return>-1
          GROUP BY trade_date,cal_idx
        )
        SELECT e.event_id,e.symbol,e.signal_date,e.signal_cal_idx,
          e.signal_invalid_step_cum,e.signal_decision_at,
          e.trade_date,e.cal_idx,e.relative_session,e.date_cal_idx_versions,
          e.cal_idx_date_versions,s.raw_open,s.raw_high,s.raw_low,s.raw_close,
          s.coord_open,s.coord_high,s.coord_low,s.coord_close,
          s.coordinate_factor,s.turnover_fraction,s.invalid_step_cum,
          s.raw_hard_valid,s.raw_bar_valid,s.raw_trading_state_valid,
          s.raw_current_day_data_tradable,s.coordinate_current_valid,
          s.coordinate_history_valid,s.raw_trade_status,s.raw_market_rule_valid,
          s.raw_corporate_action_count,s.raw_corporate_action_valid,
          s.raw_corporate_action_blocking,s.coordinate_action_count,
          s.coordinate_action_valid,s.coordinate_action_blocking,
          s.raw_historical_identity_valid,s.raw_industry_valid,
          s.source_identity_match,s.available_at,s.bar_decision_at,
          m.market_step_return,m.market_member_rows,m.market_member_symbols,
          m.market_latest_available_at,m.market_latest_decision_at,
          a.raw_source_rows,a.raw_rows_missing_coordinate,
          a.raw_coordinate_identity_mismatches
        FROM expanded e
        LEFT JOIN (
          SELECT symbol,trade_date,cal_idx,open AS raw_open,high AS raw_high,
            low AS raw_low,close AS raw_close,
            coord_open,coord_high,coord_low,coord_close,
            coordinate_factor,turnover_fraction,invalid_step_cum,
            hard_valid AS raw_hard_valid,bar_valid AS raw_bar_valid,
            trading_state_valid AS raw_trading_state_valid,
            current_day_data_tradable AS raw_current_day_data_tradable,
            coordinate_current_valid,coordinate_history_valid,
            trade_status AS raw_trade_status,market_rule_valid AS raw_market_rule_valid,
            corporate_action_count AS raw_corporate_action_count,
            corporate_action_valid AS raw_corporate_action_valid,
            corporate_action_blocking AS raw_corporate_action_blocking,
            coordinate_action_count,coordinate_action_valid,
            coordinate_action_blocking,
            historical_identity_valid AS raw_historical_identity_valid,
            industry_valid AS raw_industry_valid,source_identity_match,
            available_at,bar_decision_at
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
        or windows.trade_date.max() > SIGNAL_END
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

    valid = valid_bars(windows)
    signal = valid.loc[valid.relative_session.eq(0)]
    if (
        len(signal) != EXPECTED_EVENTS
        or signal.event_id.duplicated().any()
        or not signal.trade_date.eq(signal.signal_date).all()
        or not signal.cal_idx.eq(signal.signal_cal_idx).all()
        or not signal.raw_corporate_action_count.eq(1).all()
        or not signal.coordinate_action_count.eq(1).all()
    ):
        raise ResearchError("one exact valid cash-distribution signal bar is not present")

    windows["market_level"] = windows.groupby("event_id", sort=False)[
        "market_step_return"
    ].transform(lambda values: (1.0 + values.astype(float)).cumprod())
    first_level = windows.groupby("event_id", sort=False).market_level.transform("first")
    windows["market_level"] = 100.0 * windows.market_level / first_level
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


def source_coverage_receipt(
    prepared: pd.DataFrame, windows: pd.DataFrame
) -> dict[str, Any]:
    """Return anonymous aggregate coverage only; never persist an identity map."""
    bars = valid_bars(windows)
    per_event = bars.groupby("event_id", sort=False).size()
    signal = bars.loc[bars.relative_session.eq(0)]
    if (
        len(prepared) != EXPECTED_EVENTS
        or len(windows) != EXPECTED_EVENTS * WINDOW_ROWS
        or len(per_event) != EXPECTED_EVENTS
        or len(signal) != EXPECTED_EVENTS
        or signal.event_id.duplicated().any()
    ):
        raise ResearchError("hybrid-source coverage receipt cannot certify every event")
    return {
        "status": "HYBRID_SOURCE_COVERAGE_PASS",
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
        "post_signal_row_read": False,
        "post_2020_row_read": False,
        "outcome_artifact_statted_hashed_opened_or_parsed": False,
        "identity_crosswalk_persisted": False,
    }


def valid_bars(frame: pd.DataFrame) -> pd.DataFrame:
    raw = frame[["raw_open", "raw_high", "raw_low", "raw_close"]].apply(
        pd.to_numeric, errors="coerce"
    )
    numeric = frame[["coord_open", "coord_high", "coord_low", "coord_close"]].apply(
        pd.to_numeric, errors="coerce"
    )
    mask = (
        frame.relative_session.between(-WINDOW, 0)
        & frame.coordinate_current_valid.fillna(False)
        & frame.coordinate_history_valid.fillna(False)
        & frame.raw_hard_valid.fillna(False)
        & frame.raw_bar_valid.fillna(False)
        & frame.raw_trading_state_valid.fillna(False)
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
        & frame.available_at.le(frame.signal_decision_at)
        & frame.bar_decision_at.le(frame.signal_decision_at)
        & np.isfinite(raw).all(axis=1)
        & raw.gt(0).all(axis=1)
        & raw.raw_high.ge(raw[["raw_open", "raw_close", "raw_low"]].max(axis=1))
        & raw.raw_low.le(raw[["raw_open", "raw_close", "raw_high"]].min(axis=1))
        & np.isfinite(numeric).all(axis=1)
        & numeric.gt(0).all(axis=1)
        & np.isfinite(pd.to_numeric(frame.coordinate_factor, errors="coerce"))
        & pd.to_numeric(frame.coordinate_factor, errors="coerce").gt(0)
        & numeric.coord_high.ge(numeric[["coord_open", "coord_close", "coord_low"]].max(axis=1))
        & numeric.coord_low.le(numeric[["coord_open", "coord_close", "coord_high"]].min(axis=1))
    )
    return frame.loc[mask].sort_values("cal_idx", kind="mergesort")


def build_in_memory_blind_order(
    prepared: pd.DataFrame, windows: pd.DataFrame
) -> pd.DataFrame:
    """Assign opaque chart numbers without ever persisting an identity crosswalk."""
    ordered = prepared[["event_id"]].copy()
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
    """Render only anonymous causal price, market-tape, and turnover panels."""
    if frame.relative_session.gt(0).any() or frame.trade_date.max() > SIGNAL_END:
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
    for row in bars.itertuples(index=False):
        x = _x(int(row.relative_session))
        open_y = _y(float(row.coord_open), price_scale, PRICE_TOP, PRICE_BOTTOM)
        close_y = _y(float(row.coord_close), price_scale, PRICE_TOP, PRICE_BOTTOM)
        high_y = _y(float(row.coord_high), price_scale, PRICE_TOP, PRICE_BOTTOM)
        low_y = _y(float(row.coord_low), price_scale, PRICE_TOP, PRICE_BOTTOM)
        color = "#dc2626" if float(row.coord_close) >= float(row.coord_open) else "#16803c"
        draw.line((x, high_y, x, low_y), fill=color, width=1)
        body_top, body_bottom = sorted((open_y, close_y))
        draw.rectangle((x - 1, body_top, x + 1, max(body_top + 1, body_bottom)), fill=color)
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

    for relative in (-126, -63, 0):
        x = _x(relative)
        draw.text(
            (max(LEFT_EDGE, x - 12), TURNOVER_BOTTOM + 2),
            str(relative),
            fill="#4b5563",
            font=small,
        )
    # Keep the marker five pixels left of session zero so it cannot obscure the
    # signal candle that reviewers must classify on a frozen axis.
    signal_x = _x(0)
    signal_marker_x = signal_x - 5
    draw.line(
        (signal_marker_x, PRICE_TOP, signal_marker_x, TURNOVER_BOTTOM),
        fill="#b45309",
        width=1,
    )
    draw.text((signal_marker_x - 42, PRICE_TOP + 3), "SIGNAL", fill="#92400e", font=small)
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
        "OPAQUE ORDER | SECURITY / DATE / YEAR / INDUSTRY / EVENT / YIELD HIDDEN",
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
        "NO OUTCOME ARTIFACT OR POST-SIGNAL ROW READ",
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
    ordered = chart_index.sort_values("chart_number", kind="mergesort").reset_index(drop=True)
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
            f"V34R1 PHASE-1 ANONYMOUS | PAGE {page:04d} | "
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
    prepared = load_and_audit_identities()
    windows = load_causal_windows(prepared)
    coverage = source_coverage_receipt(prepared, windows)
    blind_order = build_in_memory_blind_order(prepared, windows)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".v34r1_phase1.staging.", dir=OUTPUT_ROOT))
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

        sheets, placements_rows = build_contact_sheets(
            chart_index, staging / "anonymous_contact_sheets"
        )
        placements = pd.DataFrame(placements_rows).sort_values(
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
        chart_index = chart_index.rename(columns={"chart_sha256": "blind_chart_sha256"})
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
            raise ResearchError("a bound allowed input changed during chart construction")
        blind_order_digest = hashlib.sha256(
            "\n".join(blind_order.blind_chart_id.astype(str)).encode("utf-8")
        ).hexdigest()
        producer_manifest = {
            "experiment": EXPERIMENT,
            "stage": "PHASE1_ANONYMOUS_CAUSAL_VISUAL_REVIEW_CORPUS",
            "asset_id": ASSET_ID,
            "authorization_id": AUTHORIZATION_ID,
            "authorized_arm": AUTHORIZED_ARM,
            "source_hashes": source_hashes,
            "pipeline_version": PIPELINE_VERSION,
            "failed_prepublication_source_attempt": FAILED_PREPUBLICATION_SOURCE_ATTEMPT,
            "failed_prepublication_transform_attempt": (
                FAILED_PREPUBLICATION_TRANSFORM_ATTEMPT
            ),
            "hybrid_source_coverage": coverage,
            "events": EXPECTED_EVENTS,
            "individual_anonymous_charts": EXPECTED_EVENTS,
            "anonymous_contact_sheets": EXPECTED_SHEETS,
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
            "identity_crosswalk_persisted": False,
            "blind_index_sha256": sha256(staging / "blind_index.csv"),
            "contact_sheet_placements_sha256": sha256(
                staging / "contact_sheet_placements.csv"
            ),
            "contact_sheet_index_sha256": sha256(staging / "contact_sheet_index.csv"),
            "phase1_review_template_sha256": sha256(
                staging / "phase1_review_template.json"
            ),
            "annotation_schema_sha256": REPO_FIXED_HASHES[ANNOTATION_SCHEMA],
            "market_line_definition": (
                "all-industry Main-plus-ChiNext per global date median current eligible "
                "adjusted-coordinate step_return known by that close; event line compounds "
                "only relative sessions -126 through 0, rebased to 100 at -126 and "
                "independently scaled"
            ),
            "adjusted_price_scale_is_per_chart": True,
            "market_scale_is_per_chart_and_independent": True,
            "turnover_scale_is_per_chart": True,
            "anonymous_identity_coverage_exactly_once": True,
            "contact_sheet_coverage_exactly_once": True,
            "post_signal_row_read": False,
            "post_2020_row_read": False,
            "outcome_artifact_statted": False,
            "outcome_artifact_hashed": False,
            "outcome_artifact_opened_or_parsed": False,
            "full_chart_generated": False,
            "identity_exposed_to_reviewer": False,
            "identity_mapping_persisted": False,
            "outcome_grouping_performed": False,
            "rule_aggregation_performed": False,
            "portfolio_replay_performed": False,
            "candidate_reselection_performed": False,
            "next_step": (
                "REVIEW_EVERY_ANONYMOUS_CHART_AND_FREEZE_THE_COMPLETE_LEDGER_"
                "BEFORE_ANY_SEPARATE_OUTCOME_ATTRIBUTION_AUTHORIZATION"
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
        help="Verify only registry/spec/manifest/runner/schema bindings; touch no data.",
    )
    mode.add_argument(
        "--verify-source-coverage",
        action="store_true",
        help=(
            "After public authorization, hash permitted hybrid sources and certify "
            "aggregate -126..0 coverage without rendering or persisting identities."
        ),
    )
    mode.add_argument("--run", action="store_true", help="Build the immutable corpus.")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.verify_public_inputs:
        hashes, _ = verify_public_authorization()
        print(json.dumps({"verified": True, "public_hashes": hashes}, indent=2, sort_keys=True))
        return
    if args.verify_source_coverage:
        preflight, authorization = verify_public_authorization()
        source_hashes = verify_allowed_bound_inputs(preflight, authorization)
        prepared = load_and_audit_identities()
        windows = load_causal_windows(prepared)
        receipt = source_coverage_receipt(prepared, windows)
        if verify_allowed_bound_inputs(*verify_public_authorization()) != source_hashes:
            raise ResearchError("a bound source changed during coverage preflight")
        print(
            json.dumps(
                {
                    "verified": True,
                    "source_hashes": source_hashes,
                    "coverage": receipt,
                    "failed_prepublication_source_attempt": (
                        FAILED_PREPUBLICATION_SOURCE_ATTEMPT
                    ),
                    "failed_prepublication_transform_attempt": (
                        FAILED_PREPUBLICATION_TRANSFORM_ATTEMPT
                    ),
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
