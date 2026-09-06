#!/usr/bin/env python3
"""Build the frozen outcome-blind V37 aggregate-volatility-exposure mother.

The three modes are deliberately separated.  ``--verify-static-contract``
reads only this runner and its frozen repository spec.  The future
``--verify-public-authorization`` additionally reads the repository manifest,
registry suggestion and central registry, but never stats, hashes, opens or
resolves any declared source.  ``--run`` reaches a source only after the exact
CY-059 public package and central installation have passed.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

EXPERIMENT = (
    "ASHARE-AGGREGATE-VOLATILITY-INNOVATION-EXPOSURE-COMPENSATION-MOTHER-V37"
)
STAGE = "OUTCOME_BLIND_REPRESENTATION_OPPORTUNITY_STABILITY_AND_REDUNDANCY_FREEZE"
REPO = Path(__file__).resolve().parents[3]
EXPERIMENTS = REPO / "research/market_behavior_os_v2/experiments"
SPEC = EXPERIMENTS / f"{EXPERIMENT}_freeze.json"
RUNNER = REPO / "research/market_behavior_os_v2/scripts" / Path(__file__).name
MANIFEST = EXPERIMENTS / "ASHARE-V37-CY059_DATA_ASSET_MANIFEST.json"
REGISTRY_SUGGESTION = EXPERIMENTS / "ASHARE-V37-CY059_REGISTRY_SUGGESTION.json"
REGISTRY = REPO / "configs/data_asset_registry.json"
ACTION_CONTRACT = REPO / "src/cyq_game/chip/price_coordinate.py"

CY006_ROOT = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily")
CY006_INVENTORY = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "CY-006-pit-b-daily-v2-2018-2026-20260821.json"
)
QD010_INVENTORY = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/QD-010-cninfo-actions-20260820.json"
)
PARTITIONS = tuple(
    CY006_ROOT / f"partition_year={year}/data_0.parquet" for year in (2018, 2019, 2020)
)
V36_REPRESENTATION = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_broad_market_price_delay_compensation_mother_v36/"
    "stage_a/representation_panel.parquet"
)

OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_aggregate_volatility_innovation_exposure_compensation_mother_v37"
)
STAGE_A = OUTPUT_ROOT / "stage_a"

ASSET_ID = "CY-059"
AUTHORIZATION_ID = (
    "CYQ-AUTH-ASHARE-AGGREGATE-VOLATILITY-INNOVATION-EXPOSURE-"
    "V37-STAGE-A-2018-2020-V1"
)
AUTHORIZATION_PURPOSE = "ASHARE_OUTCOME_BLIND_MOTHER_REPRESENTATION"
AUTHORIZED_ARM = "V37_FROZEN_OUTCOME_BLIND_STAGE_A_ONLY"
MANIFEST_STATUS = "FROZEN_OUTCOME_BLIND_BOUNDED_INPUT"
PIPELINE_VERSION = (
    "v37-aggregate-volatility-innovation-exposure-outcome-blind-stage-a-v1"
)

EXPECTED_SPEC_SHA256 = "e1d3f55df399ece5f1395894e8be285a60bf424ebac5bbfa254b020e408e8d44"
EXPECTED_INPUTS: dict[str, tuple[Path, str]] = {
    "corporate_action_coordinate_contract": (
        ACTION_CONTRACT,
        "60c9f80fcaa2bf4a6ebfaab37bc56e81dd716cc3bea00891b4fc28d077dd1726",
    ),
    "cy006_inventory": (
        CY006_INVENTORY,
        "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2",
    ),
    "cy006_2018": (
        PARTITIONS[0],
        "b906d2c21fd35128b8f65f1b00fa12ae6e5bd9ee476a368a63881304f38ceed4",
    ),
    "cy006_2019": (
        PARTITIONS[1],
        "c69a464e4a04efdca0177a8a09a13a34646531afa37a2b35b4892fd40ec3ebfd",
    ),
    "cy006_2020": (
        PARTITIONS[2],
        "1b0a00c6d2cfbce0ae4f907e1ee9dc5006f59677d556cc10f8f34a9893937c62",
    ),
    "qd010_inventory": (
        QD010_INVENTORY,
        "e1ca622ee227ce308b44933160754d450b80d3ecca79c1470037558e1011ceb8",
    ),
    "v36_representation_control": (
        V36_REPRESENTATION,
        "17a50b0aeb4a9ae36d10754280ca43c8bc06504920f51ba66d34ef506b03a3ec",
    ),
}

SOURCE_START = pd.Timestamp("2018-01-01")
MAX_ROW_DATE = pd.Timestamp("2020-12-31")
SIGNAL_START = pd.Timestamp("2018-08-01")
SIGNAL_END = pd.Timestamp("2020-12-31")
YEARS = (2018, 2019, 2020)
MARKET_RV_WINDOW = 20
CANONICAL_RESPONSE_SESSIONS = 120
NEIGHBOR_RESPONSE_SESSIONS = (100, 140)
MAX_RESPONSE_SESSIONS = max(NEIGHBOR_RESPONSE_SESSIONS)
REQUIRED_HISTORY_SESSIONS = MARKET_RV_WINDOW + MAX_RESPONSE_SESSIONS
MIN_OTHER_MARKET_PEERS = 500
MIN_INDUSTRY_REPRESENTATIONS = 12
COOLDOWN_SESSIONS = 60
MIN_ANNUAL_CANDIDATES_EXCLUSIVE = 50
MIN_ANNUAL_INDUSTRIES = 20
MIN_ANNUAL_SYMBOLS_EXCLUSIVE = 50
MIN_DECISION_MONTHS = {2018: 4, 2019: 10, 2020: 10}
MIN_DATE_CORRELATION_ROWS = 50
MIN_INDUSTRY_CORRELATION_ROWS = 8
MIN_CORRELATION_DATES = 8
STABILITY_MINIMUM = 0.50
REDUNDANCY_LIMIT = 0.80

SCORE_COLUMN = "negative_aggregate_volatility_innovation_beta_120"
NEIGHBOR_COLUMNS = (
    "negative_aggregate_volatility_innovation_beta_100",
    "negative_aggregate_volatility_innovation_beta_140",
)
CONTROL_COLUMNS = (
    "beta_market_120",
    "down_market_beta_120",
    "idiosyncratic_volatility_60",
    "stock_rv5_volatility_60",
    "stock_return_skewness_60",
    "maximum_stock_log_return_20",
    "cumulative_stock_log_return_60",
    "mean_turnover_fraction_60",
    "v36_price_delay_52w_4l",
)
V36_CONTROL_COLUMN = "v36_price_delay_52w_4l"
SPEC_CONTROL_LABELS = (
    "ordinary 120-session contemporaneous market beta from the canonical regression",
    "120-session market-down-day beta using the same causal market return and at least "
    "30 negative-market observations",
    "60-session idiosyncratic volatility against the causal leave-one-out market return",
    "60-session volatility of the stock's own fixed RV5 path using the existing Cycle-009 formula",
    "60-session stock-return skewness",
    "20-session maximum daily stock return",
    "60-session cumulative stock log return",
    "60-session mean turnover_fraction",
    "exact V36 price_delay_52w_4l on signal-date/symbol overlaps",
)
METRIC_FIELDS = (
    "alpha_120",
    "beta_market_120",
    "beta_volatility_innovation_120",
    SCORE_COLUMN,
    "canonical_status",
    "negative_aggregate_volatility_innovation_beta_100",
    "neighbor_100_status",
    "negative_aggregate_volatility_innovation_beta_140",
    "neighbor_140_status",
    "down_market_beta_120",
    "down_market_observations_120",
    "idiosyncratic_volatility_60",
    "stock_rv5_volatility_60",
    "stock_return_skewness_60",
    "maximum_stock_log_return_20",
    "cumulative_stock_log_return_60",
    "mean_turnover_fraction_60",
)

REQUIRED_TRUE_PERMISSIONS = (
    "stage_a_authorized",
    "whole_artifact_hash_authorized",
    "inventory_metadata_parse_authorized",
    "source_parquet_stage_a_parse_authorized",
    "v36_representation_control_parse_authorized",
)
REQUIRED_FALSE_PERMISSIONS = (
    "stage_b_authorized",
    "outcome_attachment_authorized",
    "outcome_artifact_parse_authorized",
    "outcome_columns_read_authorized",
    "post_signal_row_read_authorized",
    "charts_authorized",
    "portfolio_replay_authorized",
    "parameter_search_authorized",
    "post_2020_read_authorized",
    "2021_read_authorized",
    "2022_plus_read_authorized",
    "current_survivor_fallback_allowed",
)


class ResearchError(RuntimeError):
    """Fail closed on authorization, PIT, chronology, semantics or publication."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise ResearchError(f"cannot hash authorized file {path}: {exc}") from exc
    return digest.hexdigest()


def strict_json(path: Path, label: str) -> dict[str, Any]:
    def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        keys = [key for key, _ in pairs]
        duplicates = sorted(key for key, count in Counter(keys).items() if count > 1)
        if duplicates:
            raise ResearchError(f"duplicate JSON keys in {label}: {duplicates}")
        return dict(pairs)

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicate_keys
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ResearchError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ResearchError(f"{label} must be one JSON object")
    return value


def only(items: list[dict[str, Any]], label: str) -> dict[str, Any]:
    if len(items) != 1:
        raise ResearchError(f"expected exactly one {label}, found {len(items)}")
    return items[0]


def role_map(items: object, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        raise ResearchError(f"{label} must be a list")
    mapped: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("role"), str):
            raise ResearchError(f"malformed {label} row")
        role = str(item["role"])
        if role in mapped or set(item) != {"role", "path", "sha256"}:
            raise ResearchError(f"duplicate or malformed {label} role: {role}")
        mapped[role] = item
    return mapped


def expected_input_objects() -> dict[str, dict[str, str]]:
    return {
        role: {"path": str(path), "sha256": expected_hash}
        for role, (path, expected_hash) in EXPECTED_INPUTS.items()
    }


def verify_role_declarations(items: object, label: str) -> None:
    mapped = role_map(items, label)
    if set(mapped) != set(EXPECTED_INPUTS):
        raise ResearchError(f"{label} exact role set drift")
    for role, expected in expected_input_objects().items():
        if mapped[role] != {"role": role, **expected}:
            raise ResearchError(f"{label} lexical binding drift for {role}")


def verify_input_binding(binding: object, label: str) -> None:
    if binding != expected_input_objects():
        raise ResearchError(f"{label} exact input binding drift")


def verify_static_contract() -> dict[str, Any]:
    """Read the frozen repository spec and runner only; never touch a source."""

    for path in (SPEC, RUNNER):
        if not path.is_file():
            raise ResearchError(f"missing V37 repository contract: {path}")
    spec_hash = sha256(SPEC)
    runner_hash = sha256(RUNNER)
    if spec_hash != EXPECTED_SPEC_SHA256:
        raise ResearchError(f"V37 spec drift: {spec_hash} != {EXPECTED_SPEC_SHA256}")
    spec = strict_json(SPEC, "V37 frozen spec")

    inputs = spec.get("inputs", {})
    boundary = spec.get("source_and_time_boundary", {})
    representation = spec.get("canonical_representation", {})
    stability = spec.get("neighboring_definition_stability", {})
    candidates = spec.get("candidate_contract", {})
    redundancy = spec.get("outcome_blind_redundancy_controls", {})
    gates = spec.get("stage_a_gates", {})
    protocol = spec.get("stage_a_protocol", {})
    output = spec.get("output_contract", {})
    later = spec.get("later_stage_boundary", {})

    expected_partitions = [
        {"year": year, "path": str(path), "sha256": expected_hash}
        for year, (path, expected_hash) in zip(
            YEARS,
            (EXPECTED_INPUTS[f"cy006_{year}"] for year in YEARS),
            strict=True,
        )
    ]
    if (
        spec.get("experiment") != EXPERIMENT
        or spec.get("stage") != STAGE
        or spec.get("status")
        != "FROZEN_BEFORE_SOURCE_ACCESS_AWAITING_CY059_IMPLEMENTATION_AND_REGISTRATION"
        or inputs.get("registry", {}).get("path") != "configs/data_asset_registry.json"
        or inputs.get("registry", {}).get("required_assets")
        != [ASSET_ID, "CY-006", "QD-010", "CY-054"]
        or inputs.get("cy006_inventory")
        != {
            "path": str(CY006_INVENTORY),
            "sha256": EXPECTED_INPUTS["cy006_inventory"][1],
        }
        or inputs.get("cy006_partitions") != expected_partitions
        or inputs.get("qd010_inventory")
        != {
            "path": str(QD010_INVENTORY),
            "sha256": EXPECTED_INPUTS["qd010_inventory"][1],
        }
        or inputs.get("corporate_action_coordinate_contract")
        != {
            "path": "src/cyq_game/chip/price_coordinate.py",
            "sha256": EXPECTED_INPUTS["corporate_action_coordinate_contract"][1],
        }
        or inputs.get("v36_outcome_blind_representation_control", {}).get("asset_id")
        != "CY-054"
        or inputs.get("v36_outcome_blind_representation_control", {}).get("path")
        != str(V36_REPRESENTATION)
        or inputs.get("v36_outcome_blind_representation_control", {}).get("sha256")
        != EXPECTED_INPUTS["v36_representation_control"][1]
        or inputs.get("v36_outcome_blind_representation_control", {}).get("access")
        != (
            "Exact signal-date/symbol overlap and price_delay_52w_4l column only; "
            "no V36 outcome or chart artifact."
        )
    ):
        raise ResearchError("V37 frozen input declarations drift")

    if (
        boundary.get("source_start") != str(SOURCE_START.date())
        or boundary.get("maximum_source_row_date") != str(MAX_ROW_DATE.date())
        or boundary.get("signal_start") != str(SIGNAL_START.date())
        or boundary.get("signal_end") != str(SIGNAL_END.date())
        or boundary.get("decision_schedule")
        != "Last completed A-share market session of each calendar month."
        or boundary.get("post_2020_row_read") is not False
        or boundary.get("forward_or_post_signal_row_read") is not False
        or boundary.get("outcome_columns_read") is not False
        or representation.get("regression_window")
        != "Exactly 120 consecutive response sessions ending at the signal close."
        or representation.get("score")
        != (
            "NEGATIVE_AGGREGATE_VOLATILITY_INNOVATION_BETA_120 = -beta_vol_i. "
            "Higher score means a more negative signed return exposure to an increase "
            "in aggregate volatility."
        )
        or representation.get("direction")
        != "MOST_NEGATIVE_BETA_VOL_BETTER_FROZEN_NO_SIGN_RESCUE"
        or stability.get("neighbors")
        != [
            "the identical regression over the latest 100 complete response sessions",
            "the identical regression over the latest 140 complete response sessions",
        ]
        or stability.get("minimum_same_date_observations")
        != MIN_DATE_CORRELATION_ROWS
        or stability.get("minimum_within_industry_observations")
        != MIN_INDUSTRY_CORRELATION_ROWS
        or stability.get("minimum_supported_decision_dates_per_neighbor")
        != MIN_CORRELATION_DATES
        or stability.get("required_median_spearman") != STABILITY_MINIMUM
    ):
        raise ResearchError("V37 time, representation or neighbor contract drift")

    if (
        candidates.get("industry_support")
        != (
            "At least 12 amount-eligible complete canonical representations in the "
            "same current PIT industry and decision date."
        )
        or candidates.get("cooldown")
        != (
            "After ranking, retain a repeated symbol only when its global signal "
            "calendar index is strictly more than 60 sessions after its last retained "
            "V37 event."
        )
        or candidates.get("event_id")
        != "AGGREGATE_VOLATILITY_INNOVATION_EXPOSURE|YYYYMMDD|PIT_INDUSTRY|SYMBOL"
        or any(
            candidates.get(name) != "NONE"
            for name in (
                "market_filter",
                "past_return_sign_filter",
                "chart_filter",
                "outcome_filter",
            )
        )
        or redundancy.get("controls") != list(SPEC_CONTROL_LABELS)
        or redundancy.get("minimum_same_date_observations")
        != MIN_DATE_CORRELATION_ROWS
        or redundancy.get("minimum_within_industry_observations")
        != MIN_INDUSTRY_CORRELATION_ROWS
        or redundancy.get("minimum_supported_decision_dates") != MIN_CORRELATION_DATES
        or redundancy.get("absolute_redundancy_limit") != REDUNDANCY_LIMIT
    ):
        raise ResearchError("V37 candidate or redundancy contract drift")

    if (
        gates.get("years") != list(YEARS)
        or gates.get("retained_candidates_each_year_strictly_greater_than")
        != MIN_ANNUAL_CANDIDATES_EXCLUSIVE
        or gates.get("decision_months_minimum")
        != {str(year): minimum for year, minimum in MIN_DECISION_MONTHS.items()}
        or gates.get("pit_industries_each_year_at_least") != MIN_ANNUAL_INDUSTRIES
        or gates.get("unique_symbols_each_year_strictly_greater_than")
        != MIN_ANNUAL_SYMBOLS_EXCLUSIVE
        or gates.get("canonical_coefficients_finite") is not True
        or gates.get("neighboring_definition_stability_gate_must_pass") is not True
        or gates.get("redundancy_gate_must_pass") is not True
        or gates.get("all_must_pass") is not True
        or not isinstance(protocol.get("allowed"), list)
        or not isinstance(protocol.get("forbidden"), list)
        or output.get("canonical_directory") != str(STAGE_A)
        or output.get("files_if_passed")
        != ["representation_panel.parquet", "candidates_frozen.parquet", "result.json"]
        or output.get("files_if_failed_gate") != ["result.json"]
        or any(
            later.get(field) is not False
            for field in (
                "stage_b_authorized",
                "charts_authorized",
                "outcome_read_authorized",
                "portfolio_replay_authorized",
                "2021_plus_read_authorized",
            )
        )
    ):
        raise ResearchError("V37 Stage-A gate, output or later-stage contract drift")

    if (
        MARKET_RV_WINDOW != 20
        or CANONICAL_RESPONSE_SESSIONS != 120
        or NEIGHBOR_RESPONSE_SESSIONS != (100, 140)
        or REQUIRED_HISTORY_SESSIONS != 160
        or MIN_OTHER_MARKET_PEERS != 500
        or MIN_INDUSTRY_REPRESENTATIONS != 12
        or COOLDOWN_SESSIONS != 60
    ):
        raise ResearchError("V37 runner algorithm constants drift")
    return {
        "status": "STATIC_CONTRACT_VALID_SOURCE_UNTOUCHED",
        "asset_id": ASSET_ID,
        "spec": spec_hash,
        "runner": runner_hash,
        "future_manifest": str(MANIFEST.relative_to(REPO)),
        "future_registry_suggestion": str(REGISTRY_SUGGESTION.relative_to(REPO)),
        "source_paths_touched": False,
    }


def verify_public_authorization() -> dict[str, Any]:
    """Validate the future CY-059 public package without touching a source."""

    static = verify_static_contract()
    for path in (MANIFEST, REGISTRY_SUGGESTION, REGISTRY):
        if not path.is_file():
            raise ResearchError(f"missing V37 public authorization artifact: {path}")
    public_hashes = {
        **static,
        "manifest": sha256(MANIFEST),
        "registry_suggestion": sha256(REGISTRY_SUGGESTION),
        "registry": sha256(REGISTRY),
    }
    manifest = strict_json(MANIFEST, "CY-059 manifest")
    suggestion = strict_json(REGISTRY_SUGGESTION, "CY-059 registry suggestion")
    registry = strict_json(REGISTRY, "central data registry")

    expected_binding = {
        "spec": {"path": str(SPEC), "sha256": static["spec"]},
        "runner": {"path": str(RUNNER), "sha256": static["runner"]},
        "inputs": expected_input_objects(),
    }
    boundary = manifest.get("authorization_boundary", {})
    if (
        manifest.get("asset_id") != ASSET_ID
        or manifest.get("status") != MANIFEST_STATUS
        or manifest.get("pit_grade") != "B"
        or manifest.get("pipeline_version") != PIPELINE_VERSION
        or manifest.get("stage_a_binding") != expected_binding
        or boundary.get("authorization_id") != AUTHORIZATION_ID
        or boundary.get("purpose") != AUTHORIZATION_PURPOSE
        or boundary.get("authorized_arm") != AUTHORIZED_ARM
        or boundary.get("start") != str(SOURCE_START.date())
        or boundary.get("end") != str(MAX_ROW_DATE.date())
        or boundary.get("signal_start") != str(SIGNAL_START.date())
        or boundary.get("signal_end") != str(SIGNAL_END.date())
        or boundary.get("maximum_source_row_date") != str(MAX_ROW_DATE.date())
        or any(boundary.get(field) is not True for field in REQUIRED_TRUE_PERMISSIONS)
        or any(boundary.get(field) is not False for field in REQUIRED_FALSE_PERMISSIONS)
    ):
        raise ResearchError("CY-059 manifest public semantics drift")
    verify_role_declarations(manifest.get("bound_artifacts"), "manifest bound_artifacts")

    if suggestion.get("central_registry_modified") is not False:
        raise ResearchError("CY-059 suggestion falsely claims central installation")
    asset = suggestion.get("asset")
    authorization = suggestion.get("bounded_authorization")
    if not isinstance(asset, dict) or not isinstance(authorization, dict):
        raise ResearchError("CY-059 suggestion lacks exact registry objects")
    asset_lineage = asset.get("lineage", {})
    scope = authorization.get("scope", {})
    protocol = authorization.get("bound_protocol", {})
    bound_manifest = authorization.get("bound_manifest", {})
    if (
        asset.get("asset_id") != ASSET_ID
        or asset.get("kind")
        != "bounded_daily_pit_b_aggregate_volatility_innovation_exposure_input"
        or asset.get("status") != "RESEARCH_CONDITIONAL"
        or asset.get("pit_grade") != "B"
        or asset.get("physical_state") != "MATERIALIZED"
        or asset.get("location") != str(MANIFEST)
        or asset_lineage.get("bounded_authorization_id") != AUTHORIZATION_ID
        or asset_lineage.get("component_assets") != ["CY-006", "QD-010", "CY-054"]
        or asset_lineage.get("immutable_manifest") is not True
        or asset_lineage.get("manifest_path") != str(MANIFEST)
        or asset_lineage.get("manifest_sha256") != public_hashes["manifest"]
        or asset_lineage.get("pipeline_version") != PIPELINE_VERSION
        or asset_lineage.get("record_available_at") is not True
        or asset_lineage.get("record_snapshot_id") is not True
        or asset.get("stage_a_binding") != expected_binding
        or not asset.get("source")
        or not asset.get("quality_evidence")
        or not asset.get("activation_gates")
        or authorization.get("authorization_id") != AUTHORIZATION_ID
        or authorization.get("asset_id") != ASSET_ID
        or authorization.get("purpose") != AUTHORIZATION_PURPOSE
        or authorization.get("authorized_arms") != [AUTHORIZED_ARM]
        or authorization.get("dependency_asset_id") != "CY-006"
        or authorization.get("dependency_asset_ids") != ["CY-006", "QD-010", "CY-054"]
        or authorization.get("dependency_status") != "RESEARCH_CONDITIONAL"
        or scope.get("project") != "research/market_behavior_os_v2"
        or scope.get("start") != str(SOURCE_START.date())
        or scope.get("end") != str(MAX_ROW_DATE.date())
        or scope.get("signal_start") != str(SIGNAL_START.date())
        or scope.get("signal_end") != str(SIGNAL_END.date())
        or scope.get("maximum_source_row_date") != str(MAX_ROW_DATE.date())
        or bound_manifest
        != {"path": str(MANIFEST), "sha256": public_hashes["manifest"]}
        or protocol.get("path") != str(SPEC)
        or protocol.get("sha256") != static["spec"]
        or protocol.get("runner_path") != str(RUNNER)
        or protocol.get("runner_sha256") != static["runner"]
        or authorization.get("bound_strategy")
        != {"path": str(SPEC), "sha256": static["spec"]}
        or authorization.get("stage_a_binding") != expected_binding
        or authorization.get("record_level_available_at_available") is not False
        or any(
            authorization.get(field) is not True for field in REQUIRED_TRUE_PERMISSIONS
        )
        or any(
            authorization.get(field) is not False
            for field in REQUIRED_FALSE_PERMISSIONS
        )
    ):
        raise ResearchError("CY-059 registry suggestion semantics drift")
    verify_role_declarations(
        authorization.get("bound_artifacts"), "authorization bound_artifacts"
    )
    if authorization.get("bound_artifacts") != manifest.get("bound_artifacts"):
        raise ResearchError("CY-059 manifest/authorization artifact declarations differ")

    installed_asset = only(
        [item for item in registry.get("assets", []) if item.get("asset_id") == ASSET_ID],
        f"central asset {ASSET_ID}",
    )
    installed_authorization = only(
        [
            item
            for item in registry.get("bounded_authorizations", [])
            if item.get("authorization_id") == AUTHORIZATION_ID
        ],
        f"central authorization {AUTHORIZATION_ID}",
    )
    if installed_asset != asset or installed_authorization != authorization:
        raise ResearchError("central CY-059 objects do not exactly match suggestion")
    for dependency in ("CY-006", "QD-010", "CY-054"):
        dependency_asset = only(
            [
                item
                for item in registry.get("assets", [])
                if item.get("asset_id") == dependency
            ],
            f"dependency asset {dependency}",
        )
        if dependency_asset.get("status") != "RESEARCH_CONDITIONAL":
            raise ResearchError(f"dependency asset status drift: {dependency}")
    return {
        "hashes": public_hashes,
        "asset": asset,
        "authorization": authorization,
    }


def verify_source_inputs() -> dict[str, str]:
    """First function allowed to stat, hash, open or parse a declared source."""

    actual: dict[str, str] = {}
    for role, (path, expected_hash) in EXPECTED_INPUTS.items():
        if not path.is_file() or path.is_symlink():
            raise ResearchError(f"missing regular V37 source {role}: {path}")
        value = sha256(path)
        if value != expected_hash:
            raise ResearchError(f"V37 source drift {role}: {value} != {expected_hash}")
        actual[role] = value

    inventory = strict_json(CY006_INVENTORY, "CY-006 inventory")
    entries = {item["path"]: item["sha256"] for item in inventory.get("files", [])}
    if inventory.get("root") != str(CY006_ROOT):
        raise ResearchError("CY-006 inventory root drift")
    for year in YEARS:
        role = f"cy006_{year}"
        path, expected_hash = EXPECTED_INPUTS[role]
        if entries.get(str(path.relative_to(CY006_ROOT))) != expected_hash:
            raise ResearchError(f"CY-006 inventory partition drift: {role}")
    return actual


def connect(temporary: Path) -> duckdb.DuckDBPyConnection:
    temporary.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute("SET threads=2")
    connection.execute("SET memory_limit='12GB'")
    connection.execute("SET preserve_insertion_order=false")
    connection.execute(f"SET temp_directory='{temporary.as_posix()}'")
    connection.from_parquet(
        [str(path) for path in PARTITIONS], union_by_name=True
    ).create_view("cy006")
    return connection


def loo_median_sql(value: str, count: str, values: str) -> str:
    """Return the exact leave-one-out median from a sorted one-based list."""

    return f"""
      CASE
        WHEN {count}%2=0 AND {value}<=list_extract({values},floor({count}/2)::BIGINT)
          THEN list_extract({values},floor({count}/2)::BIGINT+1)
        WHEN {count}%2=0
          THEN list_extract({values},floor({count}/2)::BIGINT)
        WHEN {value}<list_extract({values},floor({count}/2)::BIGINT+1)
          THEN (list_extract({values},floor({count}/2)::BIGINT+1)
                +list_extract({values},floor({count}/2)::BIGINT+2))/2.0
        WHEN {value}>list_extract({values},floor({count}/2)::BIGINT+1)
          THEN (list_extract({values},floor({count}/2)::BIGINT)
                +list_extract({values},floor({count}/2)::BIGINT+1))/2.0
        ELSE (list_extract({values},floor({count}/2)::BIGINT)
              +list_extract({values},floor({count}/2)::BIGINT+2))/2.0
      END
    """


def build_histories(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    paths = ",".join(f"'{path.as_posix()}'" for path in PARTITIONS)
    source = connection.execute(
        f"""
        SELECT count(*),count(*)-count(DISTINCT (trade_date,symbol)),
          count(*) FILTER (WHERE hard_valid AND available_at>decision_at),
          min(trade_date),max(trade_date)
        FROM read_parquet([{paths}],union_by_name=true)
        WHERE trade_date BETWEEN DATE '{SOURCE_START.date()}' AND DATE '{MAX_ROW_DATE.date()}'
        """
    ).fetchone()
    if source is None or source[0] == 0 or source[3] is None or source[4] is None:
        raise ResearchError("V37 bounded CY-006 source is empty")
    audit: dict[str, Any] = {
        "source_rows": int(source[0]),
        "duplicate_source_keys": int(source[1]),
        "hard_valid_time_travel_rows": int(source[2]),
        "source_first_date": str(pd.Timestamp(source[3]).date()),
        "source_last_date": str(pd.Timestamp(source[4]).date()),
        "maximum_source_row_date": str(MAX_ROW_DATE.date()),
    }
    if (
        audit["duplicate_source_keys"]
        or audit["hard_valid_time_travel_rows"]
        or pd.Timestamp(source[3]) < SOURCE_START
        or pd.Timestamp(source[4]) > MAX_ROW_DATE
    ):
        raise ResearchError(f"V37 source semantic audit failed: {audit}")

    connection.execute(
        f"""
        CREATE TEMP TABLE market_calendar AS
        SELECT trade_date,row_number() OVER (ORDER BY trade_date)-1 AS cal_idx
        FROM (
          SELECT DISTINCT trade_date FROM cy006
          WHERE trade_date BETWEEN DATE '{SOURCE_START.date()}' AND DATE '{MAX_ROW_DATE.date()}'
        )
        """
    )
    snapshot_gate = " AND ".join(
        f"d.{name} IS NOT NULL AND trim(CAST(d.{name} AS VARCHAR))<>''"
        for name in (
            "snapshot_id",
            "daily_snapshot_id",
            "trading_state_snapshot_id",
            "industry_snapshot_id",
            "float_snapshot_id",
            "corporate_action_snapshot_id",
            "market_snapshot_id",
        )
    )
    connection.execute(
        f"""
        CREATE TEMP TABLE base_daily AS
        SELECT d.trade_date,c.cal_idx,d.symbol,
          ln(d.close/d.preclose) AS stock_log_return,
          CASE WHEN d.turnover_fraction IS NOT NULL
                 AND isfinite(d.turnover_fraction) AND d.turnover_fraction>=0
               THEN d.turnover_fraction ELSE NULL END AS turnover_fraction
        FROM cy006 d JOIN market_calendar c USING(trade_date)
        WHERE d.trade_date BETWEEN DATE '{SOURCE_START.date()}' AND DATE '{MAX_ROW_DATE.date()}'
          AND (
            regexp_matches(d.symbol,'^(600|601|603|605)[0-9]{{3}}[.]SH$')
            OR regexp_matches(d.symbol,'^(000|001|002|300|301)[0-9]{{3}}[.]SZ$')
          )
          AND coalesce(d.hard_valid AND d.bar_valid AND d.trading_state_valid
            AND d.corporate_action_valid AND NOT d.corporate_action_blocking
            AND d.market_valid AND d.market_rule_valid AND d.historical_identity_valid
            AND d.available_at<=d.decision_at
            AND d.open>0 AND d.high>0 AND d.low>0 AND d.close>0 AND d.preclose>0
            AND d.high>=d.open AND d.high>=d.close
            AND d.low<=d.open AND d.low<=d.close
            AND isfinite(d.open) AND isfinite(d.high) AND isfinite(d.low)
            AND isfinite(d.close) AND isfinite(d.preclose)
            AND isfinite(ln(d.close/d.preclose)),false)
          AND {snapshot_gate}
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE daily_groups AS
        SELECT trade_date,count(*) AS member_count,
          list_sort(list(stock_log_return)) AS sorted_returns
        FROM base_daily GROUP BY trade_date
        HAVING count(*)>=501
        """
    )
    daily_loo = loo_median_sql(
        "b.stock_log_return", "g.member_count", "g.sorted_returns"
    )
    connection.execute(
        f"""
        CREATE TEMP TABLE daily_context AS
        SELECT b.*,{daily_loo} AS loo_market_log_return,
          g.member_count-1 AS other_market_peers
        FROM base_daily b JOIN daily_groups g USING(trade_date)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE month_ends AS
        SELECT trade_date,cal_idx FROM (
          SELECT trade_date,cal_idx,
            lead(date_trunc('month',trade_date)) OVER (ORDER BY cal_idx) AS next_month
          FROM market_calendar
        ) WHERE next_month IS NULL OR next_month>date_trunc('month',trade_date)
        """
    )
    connection.execute(
        f"""
        CREATE TEMP TABLE signal_universe AS
        SELECT d.trade_date AS signal_date,c.cal_idx AS signal_cal_idx,d.symbol,
          d.industry AS causal_industry,d.decision_at,d.available_at,d.amount,
          d.turnover_fraction,d.circulating_shares,
          d.snapshot_id,d.daily_snapshot_id,d.trading_state_snapshot_id,
          d.industry_snapshot_id,d.float_snapshot_id,
          d.corporate_action_snapshot_id,d.market_snapshot_id
        FROM cy006 d JOIN month_ends m ON m.trade_date=d.trade_date
        JOIN market_calendar c ON c.trade_date=d.trade_date AND c.cal_idx=m.cal_idx
        WHERE d.trade_date BETWEEN DATE '{SIGNAL_START.date()}' AND DATE '{SIGNAL_END.date()}'
          AND (
            regexp_matches(d.symbol,'^(600|601|603|605)[0-9]{{3}}[.]SH$')
            OR regexp_matches(d.symbol,'^(000|001|002|300|301)[0-9]{{3}}[.]SZ$')
          )
          AND coalesce(d.hard_valid AND d.bar_valid AND d.trading_state_valid
            AND d.industry_valid AND d.float_valid AND d.corporate_action_valid
            AND NOT d.corporate_action_blocking AND d.market_valid
            AND d.market_rule_valid AND d.historical_identity_valid
            AND d.current_day_data_tradable AND d.trade_status=1 AND NOT d.is_st
            AND d.available_at<=d.decision_at
            AND d.industry IS NOT NULL AND trim(CAST(d.industry AS VARCHAR))<>''
            AND d.open>0 AND d.high>0 AND d.low>0 AND d.close>0 AND d.preclose>0
            AND d.high>=d.open AND d.high>=d.close
            AND d.low<=d.open AND d.low<=d.close
            AND d.amount>0 AND d.turnover_fraction>0 AND d.circulating_shares>0
            AND isfinite(d.open) AND isfinite(d.high) AND isfinite(d.low)
            AND isfinite(d.close) AND isfinite(d.preclose) AND isfinite(d.amount)
            AND isfinite(d.turnover_fraction) AND isfinite(d.circulating_shares)
            AND isfinite(ln(d.close/d.preclose)),false)
          AND {snapshot_gate}
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE signal_amounts AS
        SELECT signal_date,median(amount) AS same_date_median_amount,
          count(*) AS same_date_eligible_n
        FROM signal_universe GROUP BY signal_date
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE signal_rankable AS
        SELECT s.*,a.same_date_median_amount,a.same_date_eligible_n
        FROM signal_universe s JOIN signal_amounts a USING(signal_date)
        WHERE s.amount>=a.same_date_median_amount
        """
    )
    connection.execute(
        f"""
        CREATE TEMP TABLE exact_history_keys AS
        SELECT s.signal_date,s.signal_cal_idx,s.symbol,
          count(*) AS history_session_count,
          count(DISTINCT h.cal_idx) AS distinct_history_sessions,
          min(h.cal_idx) AS history_first_cal_idx,
          max(h.cal_idx) AS history_last_cal_idx,
          min(h.other_market_peers) AS minimum_other_market_peers
        FROM signal_rankable s JOIN daily_context h ON h.symbol=s.symbol
          AND h.cal_idx BETWEEN s.signal_cal_idx-{REQUIRED_HISTORY_SESSIONS - 1}
                            AND s.signal_cal_idx
        GROUP BY s.signal_date,s.signal_cal_idx,s.symbol
        HAVING count(*)={REQUIRED_HISTORY_SESSIONS}
          AND count(DISTINCT h.cal_idx)={REQUIRED_HISTORY_SESSIONS}
          AND min(h.cal_idx)=s.signal_cal_idx-{REQUIRED_HISTORY_SESSIONS - 1}
          AND max(h.cal_idx)=s.signal_cal_idx
          AND min(h.other_market_peers)>={MIN_OTHER_MARKET_PEERS}
        """
    )

    key_audit = connection.execute(
        """
        SELECT (SELECT count(*) FROM market_calendar),
          (SELECT count(*) FROM base_daily),
          (SELECT count(*) FROM daily_context),
          (SELECT count(*) FROM signal_universe),
          (SELECT count(*) FROM signal_rankable),
          (SELECT count(*) FROM exact_history_keys),
          (SELECT min(signal_date) FROM signal_universe),
          (SELECT max(signal_date) FROM signal_universe)
        """
    ).fetchone()
    audit.update(
        {
            "global_market_sessions": int(key_audit[0]),
            "valid_base_rows": int(key_audit[1]),
            "leave_one_out_context_rows": int(key_audit[2]),
            "signal_universe_rows": int(key_audit[3]),
            "amount_eligible_signal_rows": int(key_audit[4]),
            "exact_160_session_history_rows": int(key_audit[5]),
            "first_signal_date": (
                None if key_audit[6] is None else str(pd.Timestamp(key_audit[6]).date())
            ),
            "last_signal_date": (
                None if key_audit[7] is None else str(pd.Timestamp(key_audit[7]).date())
            ),
        }
    )

    histories = connection.execute(
        f"""
        SELECT s.*,k.history_session_count,k.distinct_history_sessions,
          k.history_first_cal_idx,k.history_last_cal_idx,k.minimum_other_market_peers,
          list(h.stock_log_return ORDER BY h.cal_idx) AS stock_log_returns,
          list(h.loo_market_log_return ORDER BY h.cal_idx) AS market_log_returns,
          list(h.turnover_fraction ORDER BY h.cal_idx) AS turnover_fractions
        FROM signal_rankable s JOIN exact_history_keys k
          USING(signal_date,signal_cal_idx,symbol)
        JOIN daily_context h ON h.symbol=s.symbol
          AND h.cal_idx BETWEEN s.signal_cal_idx-{REQUIRED_HISTORY_SESSIONS - 1}
                            AND s.signal_cal_idx
        GROUP BY ALL
        ORDER BY s.signal_date,s.causal_industry,s.symbol
        """
    ).fetch_df()
    audit["history_rows_after_exact_join"] = len(histories)
    if len(histories) != audit["exact_160_session_history_rows"]:
        raise ResearchError(f"V37 exact history join lost rows: {audit}")
    return histories, audit


def load_v36_control(connection: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Read only V36 date, symbol and exact price-delay control columns."""

    control = connection.execute(
        f"""
        SELECT CAST(signal_date AS DATE) AS signal_date,
          CAST(symbol AS VARCHAR) AS symbol,
          CAST(price_delay_52w_4l AS DOUBLE) AS {V36_CONTROL_COLUMN}
        FROM read_parquet('{V36_REPRESENTATION.as_posix()}')
        WHERE signal_date BETWEEN DATE '{SIGNAL_START.date()}' AND DATE '{SIGNAL_END.date()}'
        ORDER BY signal_date,symbol
        """
    ).fetch_df()
    if control.duplicated(["signal_date", "symbol"]).any():
        raise ResearchError("V36 exact date/symbol control contains duplicate keys")
    if not control.empty:
        control["signal_date"] = pd.to_datetime(control.signal_date)
        values = pd.to_numeric(control[V36_CONTROL_COLUMN], errors="coerce")
        if (
            control.signal_date.lt(SIGNAL_START).any()
            or control.signal_date.gt(SIGNAL_END).any()
            or (~np.isfinite(values)).any()
            or values.lt(0).any()
            or values.gt(1).any()
        ):
            raise ResearchError("V36 exact price-delay control semantic drift")
        control[V36_CONTROL_COLUMN] = values
    return control


def invalid_metric_row(status: str) -> dict[str, Any]:
    row = {field: math.nan for field in METRIC_FIELDS}
    row["canonical_status"] = status
    row["neighbor_100_status"] = status
    row["neighbor_140_status"] = status
    row["down_market_observations_120"] = 0
    return row


def exposure_regression(
    stock_return: np.ndarray,
    market_return: np.ndarray,
    volatility_innovation: np.ndarray,
) -> tuple[float, float, float, float, str]:
    length = len(stock_return)
    if (
        market_return.shape != (length,)
        or volatility_innovation.shape != (length,)
        or not np.isfinite(stock_return).all()
        or not np.isfinite(market_return).all()
        or not np.isfinite(volatility_innovation).all()
    ):
        return math.nan, math.nan, math.nan, math.nan, "NONFINITE_OR_MISALIGNED"
    if (
        float(np.sum(np.square(market_return - market_return.mean()))) <= 0.0
        or float(
            np.sum(np.square(volatility_innovation - volatility_innovation.mean()))
        )
        <= 0.0
    ):
        return math.nan, math.nan, math.nan, math.nan, "DEGENERATE_REGRESSOR"
    design = np.column_stack(
        (np.ones(length, dtype=float), market_return, volatility_innovation)
    )
    coefficients, _, rank, _ = np.linalg.lstsq(design, stock_return, rcond=None)
    if rank != 3:
        return math.nan, math.nan, math.nan, math.nan, "RANK_DEFICIENT_DESIGN"
    if not np.isfinite(coefficients).all():
        return math.nan, math.nan, math.nan, math.nan, "NONFINITE_COEFFICIENT"
    alpha, beta_market, beta_volatility = (float(value) for value in coefficients)
    return alpha, beta_market, beta_volatility, -beta_volatility, "VALID"


def simple_beta(response: np.ndarray, regressor: np.ndarray) -> float:
    if (
        response.shape != regressor.shape
        or len(response) < 3
        or not np.isfinite(response).all()
        or not np.isfinite(regressor).all()
        or float(np.sum(np.square(regressor - regressor.mean()))) <= 0.0
    ):
        return math.nan
    design = np.column_stack((np.ones(len(response), dtype=float), regressor))
    coefficients, _, rank, _ = np.linalg.lstsq(design, response, rcond=None)
    if rank != 2 or not np.isfinite(coefficients).all():
        return math.nan
    return float(coefficients[1])


def idiosyncratic_volatility(response: np.ndarray, market: np.ndarray) -> float:
    beta = simple_beta(response, market)
    if not math.isfinite(beta):
        return math.nan
    alpha = float(response.mean() - beta * market.mean())
    residual = response - alpha - beta * market
    value = float(np.std(residual, ddof=1))
    return value if math.isfinite(value) else math.nan


def sample_skewness(values: np.ndarray) -> float:
    value = pd.Series(values, dtype=float).skew()
    return math.nan if pd.isna(value) or not math.isfinite(float(value)) else float(value)


def compute_one_representation(
    stock: object, market: object, turnover: object
) -> dict[str, Any]:
    try:
        stock_values = np.asarray(stock, dtype=float)
        market_values = np.asarray(market, dtype=float)
        turnover_values = np.asarray(turnover, dtype=float)
    except (TypeError, ValueError):
        return invalid_metric_row("NONNUMERIC_HISTORY")
    expected_shape = (REQUIRED_HISTORY_SESSIONS,)
    if stock_values.shape != expected_shape or market_values.shape != expected_shape:
        return invalid_metric_row("BAD_HISTORY_LENGTH")
    if not np.isfinite(stock_values).all() or not np.isfinite(market_values).all():
        return invalid_metric_row("NONFINITE_RETURN_HISTORY")

    rv20 = np.sqrt(
        np.convolve(
            np.square(market_values),
            np.ones(MARKET_RV_WINDOW, dtype=float),
            mode="valid",
        )
    )
    if (
        rv20.shape != (MAX_RESPONSE_SESSIONS + 1,)
        or not np.isfinite(rv20).all()
        or np.any(rv20 <= 0.0)
    ):
        return invalid_metric_row("NONPOSITIVE_OR_NONFINITE_RV20")
    innovations = np.diff(np.log(rv20))
    response = stock_values[MARKET_RV_WINDOW:]
    market_response = market_values[MARKET_RV_WINDOW:]
    if (
        response.shape != (MAX_RESPONSE_SESSIONS,)
        or market_response.shape != (MAX_RESPONSE_SESSIONS,)
        or innovations.shape != (MAX_RESPONSE_SESSIONS,)
    ):
        return invalid_metric_row("INNOVATION_ALIGNMENT_FAILURE")

    regressions: dict[int, tuple[float, float, float, float, str]] = {}
    for length in (*NEIGHBOR_RESPONSE_SESSIONS, CANONICAL_RESPONSE_SESSIONS):
        regressions[length] = exposure_regression(
            response[-length:], market_response[-length:], innovations[-length:]
        )
    alpha, beta_market, beta_volatility, score, canonical_status = regressions[
        CANONICAL_RESPONSE_SESSIONS
    ]

    canonical_market = market_response[-CANONICAL_RESPONSE_SESSIONS:]
    canonical_stock = response[-CANONICAL_RESPONSE_SESSIONS:]
    down_mask = canonical_market < 0.0
    down_count = int(down_mask.sum())
    down_beta = (
        simple_beta(canonical_stock[down_mask], canonical_market[down_mask])
        if down_count >= 30
        else math.nan
    )
    idio = idiosyncratic_volatility(response[-60:], market_response[-60:])

    stock_for_rv5 = stock_values[-64:]
    stock_rv5 = np.sqrt(
        np.convolve(np.square(stock_for_rv5), np.ones(5, dtype=float), mode="valid")
    )
    stock_rv5_volatility = float(np.std(stock_rv5, ddof=1))
    if not math.isfinite(stock_rv5_volatility):
        stock_rv5_volatility = math.nan
    skewness = sample_skewness(response[-60:])
    maximum_return = float(np.max(response[-20:]))
    cumulative_return = float(np.sum(response[-60:]))
    mean_turnover = (
        float(np.mean(turnover_values[-60:]))
        if turnover_values.shape == expected_shape
        and np.isfinite(turnover_values[-60:]).all()
        else math.nan
    )
    neighbor_100 = regressions[100]
    neighbor_140 = regressions[140]
    return {
        "alpha_120": alpha,
        "beta_market_120": beta_market,
        "beta_volatility_innovation_120": beta_volatility,
        SCORE_COLUMN: score,
        "canonical_status": canonical_status,
        "negative_aggregate_volatility_innovation_beta_100": neighbor_100[3],
        "neighbor_100_status": neighbor_100[4],
        "negative_aggregate_volatility_innovation_beta_140": neighbor_140[3],
        "neighbor_140_status": neighbor_140[4],
        "down_market_beta_120": down_beta,
        "down_market_observations_120": down_count,
        "idiosyncratic_volatility_60": idio,
        "stock_rv5_volatility_60": stock_rv5_volatility,
        "stock_return_skewness_60": skewness,
        "maximum_stock_log_return_20": maximum_return,
        "cumulative_stock_log_return_60": cumulative_return,
        "mean_turnover_fraction_60": mean_turnover,
    }


def make_representation(
    histories: pd.DataFrame, v36_control: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any]]:
    history_columns = ("stock_log_returns", "market_log_returns", "turnover_fractions")
    rows = [
        compute_one_representation(stock, market, turnover)
        for stock, market, turnover in zip(
            histories.get("stock_log_returns", pd.Series(dtype=object)),
            histories.get("market_log_returns", pd.Series(dtype=object)),
            histories.get("turnover_fractions", pd.Series(dtype=object)),
            strict=True,
        )
    ]
    metadata = histories.drop(columns=list(history_columns), errors="ignore").reset_index(drop=True)
    metrics = pd.DataFrame(rows, columns=METRIC_FIELDS)
    representation = pd.concat([metadata, metrics], axis=1)
    canonical_counts = {
        str(key): int(value)
        for key, value in representation.get(
            "canonical_status", pd.Series(dtype=str)
        ).value_counts().items()
    }
    neighbor_counts = {
        str(length): {
            str(key): int(value)
            for key, value in representation.get(
                f"neighbor_{length}_status", pd.Series(dtype=str)
            ).value_counts().items()
        }
        for length in NEIGHBOR_RESPONSE_SESSIONS
    }
    if representation.empty:
        representation["industry_representation_count"] = pd.Series(dtype="int64")
    else:
        representation = representation.loc[
            representation.canonical_status.eq("VALID")
        ].copy()
        representation["industry_representation_count"] = representation.groupby(
            ["signal_date", "causal_industry"]
        )["symbol"].transform("size")
        representation = representation.loc[
            representation.industry_representation_count.ge(
                MIN_INDUSTRY_REPRESENTATIONS
            )
        ].copy()
    if V36_CONTROL_COLUMN in representation:
        raise ResearchError("V36 control column unexpectedly exists before bounded join")
    representation = representation.merge(
        v36_control,
        on=["signal_date", "symbol"],
        how="left",
        validate="many_to_one",
    )
    representation = representation.sort_values(
        ["signal_date", "causal_industry", "symbol"], kind="mergesort"
    ).reset_index(drop=True)
    audit = {
        "regression_input_rows": len(histories),
        "canonical_status_counts": canonical_counts,
        "neighbor_status_counts": neighbor_counts,
        "valid_canonical_rows_before_industry_support": canonical_counts.get("VALID", 0),
        "supported_representation_rows": len(representation),
        "supported_decision_dates": int(representation.signal_date.nunique()),
        "supported_industries": int(representation.causal_industry.nunique()),
        "v36_overlap_rows": int(representation[V36_CONTROL_COLUMN].notna().sum()),
    }
    return representation, audit


def spearman(left: pd.Series, right: pd.Series) -> float | None:
    frame = pd.DataFrame(
        {
            "left": pd.to_numeric(left, errors="coerce"),
            "right": pd.to_numeric(right, errors="coerce"),
        }
    ).dropna()
    frame = frame.loc[np.isfinite(frame.left) & np.isfinite(frame.right)]
    if len(frame) < 3 or frame.left.nunique() < 2 or frame.right.nunique() < 2:
        return None
    value = frame.left.rank(method="average").corr(frame.right.rank(method="average"))
    return None if pd.isna(value) else float(value)


def correlation_support(
    representation: pd.DataFrame, comparison: str
) -> dict[str, Any]:
    per_date: list[dict[str, Any]] = []
    for signal_date, part in representation.groupby("signal_date", sort=True):
        valid = part[[SCORE_COLUMN, comparison]].dropna()
        rho = (
            spearman(valid[SCORE_COLUMN], valid[comparison])
            if len(valid) >= MIN_DATE_CORRELATION_ROWS
            else None
        )
        if rho is not None:
            per_date.append(
                {"signal_date": str(pd.Timestamp(signal_date).date()), "n": len(valid), "rho": rho}
            )

    within_industry: list[dict[str, Any]] = []
    for (signal_date, industry), part in representation.groupby(
        ["signal_date", "causal_industry"], sort=True
    ):
        valid = part[[SCORE_COLUMN, comparison]].dropna()
        rho = (
            spearman(valid[SCORE_COLUMN], valid[comparison])
            if len(valid) >= MIN_INDUSTRY_CORRELATION_ROWS
            else None
        )
        if rho is not None:
            within_industry.append(
                {
                    "signal_date": str(pd.Timestamp(signal_date).date()),
                    "industry": str(industry),
                    "n": len(valid),
                    "rho": rho,
                }
            )
    supported_dates = len(per_date)
    within_dates = len({item["signal_date"] for item in within_industry})
    raw_date_median = (
        None if not per_date else float(np.median([item["rho"] for item in per_date]))
    )
    raw_industry_median = (
        None
        if not within_industry
        else float(np.median([item["rho"] for item in within_industry]))
    )
    return {
        "non_null_overlap_rows": int(
            representation[[SCORE_COLUMN, comparison]].dropna().shape[0]
        ),
        "same_date_supported_rows": int(sum(item["n"] for item in per_date)),
        "same_date_supported_dates": supported_dates,
        "same_date_raw_median_spearman": raw_date_median,
        "same_date_gated_median_spearman": (
            raw_date_median if supported_dates >= MIN_CORRELATION_DATES else None
        ),
        "within_industry_supported_rows": int(
            sum(item["n"] for item in within_industry)
        ),
        "within_industry_supported_groups": len(within_industry),
        "within_industry_supported_dates": within_dates,
        "within_industry_raw_median_spearman": raw_industry_median,
        "within_industry_gated_median_spearman": (
            raw_industry_median if within_dates >= MIN_CORRELATION_DATES else None
        ),
    }


def stability_diagnostics(
    representation: pd.DataFrame,
) -> tuple[dict[str, Any], bool]:
    result: dict[str, Any] = {}
    passed = True
    for neighbor in NEIGHBOR_COLUMNS:
        summary = correlation_support(representation, neighbor)
        date_median = summary["same_date_gated_median_spearman"]
        industry_median = summary["within_industry_gated_median_spearman"]
        neighbor_pass = bool(
            date_median is not None
            and industry_median is not None
            and date_median >= STABILITY_MINIMUM
            and industry_median >= STABILITY_MINIMUM
        )
        summary["minimum_required_median_spearman"] = STABILITY_MINIMUM
        summary["gate_passed"] = neighbor_pass
        result[neighbor] = summary
        passed &= neighbor_pass
    return result, passed


def redundancy_diagnostics(
    representation: pd.DataFrame,
) -> tuple[dict[str, Any], bool]:
    result: dict[str, Any] = {}
    passed = True
    for control in CONTROL_COLUMNS:
        summary = correlation_support(representation, control)
        date_median = summary["same_date_gated_median_spearman"]
        industry_median = summary["within_industry_gated_median_spearman"]
        correlation_safe = bool(
            (date_median is None or abs(date_median) < REDUNDANCY_LIMIT)
            and (industry_median is None or abs(industry_median) < REDUNDANCY_LIMIT)
        )
        coverage_pass = bool(date_median is not None and industry_median is not None)
        control_pass = correlation_safe and (
            coverage_pass or control == V36_CONTROL_COLUMN
        )
        summary["absolute_redundancy_limit_exclusive"] = REDUNDANCY_LIMIT
        summary["coverage_gate_applies"] = control != V36_CONTROL_COLUMN
        summary["coverage_gate_passed"] = coverage_pass
        summary["correlation_gate_passed"] = correlation_safe
        summary["gate_passed"] = control_pass
        result[control] = summary
        passed &= control_pass
    return result, passed


def select_candidates(
    representation: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    ranked = representation.sort_values(
        ["signal_date", "causal_industry", SCORE_COLUMN, "amount", "symbol"],
        ascending=[True, True, False, False, True],
        kind="mergesort",
    ).copy()
    ranked["selection_rank"] = ranked.groupby(
        ["signal_date", "causal_industry"], sort=False
    ).cumcount() + 1
    winners = ranked.loc[ranked.selection_rank.eq(1)].copy()
    winners["event_id"] = (
        "AGGREGATE_VOLATILITY_INNOVATION_EXPOSURE|"
        + winners.signal_date.dt.strftime("%Y%m%d")
        + "|"
        + winners.causal_industry.astype(str)
        + "|"
        + winners.symbol.astype(str)
    )
    winners = winners.sort_values(
        ["signal_cal_idx", "causal_industry", "symbol", "event_id"],
        kind="mergesort",
    )
    retained: list[bool] = []
    last_retained_index: dict[str, int] = {}
    for row in winners.itertuples(index=False):
        previous = last_retained_index.get(str(row.symbol))
        keep = previous is None or int(row.signal_cal_idx) - previous > COOLDOWN_SESSIONS
        retained.append(keep)
        if keep:
            last_retained_index[str(row.symbol)] = int(row.signal_cal_idx)
    winners["retained_after_60_session_cooldown"] = retained
    candidates = winners.loc[winners.retained_after_60_session_cooldown].drop(
        columns=["retained_after_60_session_cooldown"]
    )
    candidates = candidates.sort_values(
        ["signal_date", "causal_industry", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)

    for _, group in candidates.groupby("symbol", sort=False):
        gaps = np.diff(
            group.sort_values("signal_cal_idx").signal_cal_idx.to_numpy(dtype=int)
        )
        if len(gaps) and int(gaps.min()) <= COOLDOWN_SESSIONS:
            raise ResearchError("V37 strictly-more-than-60-session cooldown drift")
    audit = {
        "pre_cooldown_winners": len(winners),
        "retained_candidates": len(candidates),
        "cooldown_rejections": int(
            (~winners.retained_after_60_session_cooldown).sum()
        ),
        "duplicate_date_industry_winners": int(
            winners.duplicated(["signal_date", "causal_industry"]).sum()
        ),
        "duplicate_event_ids": int(candidates.event_id.duplicated().sum()),
        "exact_maximum_frozen_score_selection_verified": True,
        "tie_break_order": "larger current amount, then lexical symbol",
    }
    return candidates, audit


def opportunity_and_semantic_audit(
    representation: pd.DataFrame,
    candidates: pd.DataFrame,
    source_audit: dict[str, Any],
) -> tuple[dict[str, Any], bool, bool, bool]:
    finite_columns = [
        "alpha_120",
        "beta_market_120",
        "beta_volatility_innovation_120",
        SCORE_COLUMN,
    ]
    nonfinite_coefficients = (
        0
        if representation.empty
        else int((~np.isfinite(representation[finite_columns])).any(axis=1).sum())
    )
    semantic = {
        "representation_duplicate_symbol_dates": int(
            representation.duplicated(["signal_date", "symbol"]).sum()
        ),
        "candidate_duplicate_event_ids": int(candidates.event_id.duplicated().sum()),
        "pre_signal_rows": int(representation.signal_date.lt(SIGNAL_START).sum()),
        "post_2020_signal_rows": int(representation.signal_date.gt(SIGNAL_END).sum()),
        "predictor_after_decision_rows": int(
            representation.available_at.gt(representation.decision_at).sum()
        ),
        "post_signal_history_rows": int(
            representation.history_last_cal_idx.gt(representation.signal_cal_idx).sum()
        ),
        "amount_floor_failures": int(
            representation.amount.lt(representation.same_date_median_amount).sum()
        ),
        "industry_support_failures": int(
            representation.industry_representation_count.lt(
                MIN_INDUSTRY_REPRESENTATIONS
            ).sum()
        ),
        "nonfinite_canonical_coefficient_rows": nonfinite_coefficients,
        "history_count_failures": int(
            representation.history_session_count.ne(REQUIRED_HISTORY_SESSIONS).sum()
        ),
        "history_contiguity_failures": int(
            (
                representation.distinct_history_sessions.ne(
                    REQUIRED_HISTORY_SESSIONS
                )
                | representation.history_first_cal_idx.ne(
                    representation.signal_cal_idx - REQUIRED_HISTORY_SESSIONS + 1
                )
                | representation.history_last_cal_idx.ne(
                    representation.signal_cal_idx
                )
            ).sum()
        ),
        "market_peer_failures": int(
            representation.minimum_other_market_peers.lt(
                MIN_OTHER_MARKET_PEERS
            ).sum()
        ),
        "source_duplicate_keys": int(source_audit["duplicate_source_keys"]),
        "source_time_travel_rows": int(source_audit["hard_valid_time_travel_rows"]),
    }
    semantic_pass = all(value == 0 for value in semantic.values())
    representation_pass = bool(not representation.empty and nonfinite_coefficients == 0)

    annual: dict[str, Any] = {}
    opportunity_pass = True
    for year in YEARS:
        part = candidates.loc[candidates.signal_date.dt.year.eq(year)]
        count = len(part)
        industries = int(part.causal_industry.nunique())
        months = int(part.signal_date.dt.to_period("M").nunique())
        symbols = int(part.symbol.nunique())
        passed = bool(
            count > MIN_ANNUAL_CANDIDATES_EXCLUSIVE
            and industries >= MIN_ANNUAL_INDUSTRIES
            and months >= MIN_DECISION_MONTHS[year]
            and symbols > MIN_ANNUAL_SYMBOLS_EXCLUSIVE
        )
        opportunity_pass &= passed
        annual[str(year)] = {
            "retained_candidates": count,
            "pit_industries": industries,
            "decision_months": months,
            "unique_symbols": symbols,
            "candidate_count_gt_50": count > 50,
            "industry_count_ge_20": industries >= 20,
            "decision_month_gate_passed": months >= MIN_DECISION_MONTHS[year],
            "unique_symbols_gt_50": symbols > 50,
            "annual_opportunity_gate_passed": passed,
        }
    return (
        {"semantic_checks": semantic, "annual": annual},
        semantic_pass,
        representation_pass,
        opportunity_pass,
    )


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    connection = duckdb.connect()
    try:
        connection.register("frame", frame)
        connection.execute(
            f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    finally:
        connection.close()


def atomic_publish_no_replace(staging: Path, target: Path) -> None:
    if target.exists() or target.is_symlink():
        raise ResearchError(f"canonical V37 Stage-A target already exists: {target}")
    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(staging)
    target_bytes = os.fsencode(target)
    if sys.platform == "darwin" and hasattr(libc, "renamex_np"):
        rename_exclusive = libc.renamex_np
        rename_exclusive.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename_exclusive.restype = ctypes.c_int
        result = rename_exclusive(source_bytes, target_bytes, 0x00000004)
    elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        rename_exclusive = libc.renameat2
        rename_exclusive.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename_exclusive.restype = ctypes.c_int
        result = rename_exclusive(-100, source_bytes, -100, target_bytes, 1)
    else:
        raise ResearchError("platform lacks audited atomic no-replace rename")
    if result != 0:
        error = ctypes.get_errno()
        if error in (errno.EEXIST, errno.ENOTEMPTY):
            raise ResearchError(f"canonical V37 Stage-A target appeared: {target}")
        raise OSError(error, os.strerror(error), str(target))


def run_stage_a() -> dict[str, Any]:
    public = verify_public_authorization()
    source_hashes = verify_source_inputs()
    if STAGE_A.exists() or STAGE_A.is_symlink():
        raise ResearchError(f"canonical V37 Stage A already exists: {STAGE_A}")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".stage_a_staging_", dir=OUTPUT_ROOT))
    connection: duckdb.DuckDBPyConnection | None = None
    try:
        connection = connect(staging / "duckdb_tmp")
        histories, source_audit = build_histories(connection)
        v36_control = load_v36_control(connection)
        connection.close()
        connection = None

        representation, regression_audit = make_representation(histories, v36_control)
        stability, stability_pass = stability_diagnostics(representation)
        redundancy, redundancy_pass = redundancy_diagnostics(representation)
        candidates, selection_audit = select_candidates(representation)
        (
            gate_audit,
            semantic_pass,
            representation_pass,
            opportunity_pass,
        ) = opportunity_and_semantic_audit(representation, candidates, source_audit)
        if not semantic_pass:
            raise ResearchError(f"V37 hard semantic checks failed: {gate_audit}")
        stage_a_pass = bool(
            representation_pass
            and opportunity_pass
            and stability_pass
            and redundancy_pass
        )
        result: dict[str, Any] = {
            "experiment": EXPERIMENT,
            "stage": "OUTCOME_BLIND_REPRESENTATION_OPPORTUNITY_STABILITY_AND_REDUNDANCY",
            "status": (
                "PASSED_OUTCOME_BLIND_STAGE_A_STAGE_B_NOT_AUTHORIZED"
                if stage_a_pass
                else "FAILED_OUTCOME_BLIND_GATE_PERMANENTLY_CLOSED"
            ),
            "asset_id": ASSET_ID,
            "authorization_id": AUTHORIZATION_ID,
            "authorized_arm": AUTHORIZED_ARM,
            "public_contract_hashes": public["hashes"],
            "source_hashes": source_hashes,
            "source_audit": source_audit,
            "regression_audit": regression_audit,
            "selection_audit": selection_audit,
            "gate_audit": gate_audit,
            "neighboring_definition_stability": stability,
            "redundancy_diagnostics": redundancy,
            "semantic_gate_passed": semantic_pass,
            "representation_gate_passed": representation_pass,
            "opportunity_gate_passed": opportunity_pass,
            "neighboring_definition_stability_gate_passed": stability_pass,
            "redundancy_gate_passed": redundancy_pass,
            "stage_a_gate_passed": stage_a_pass,
            "representation_rows": len(representation),
            "candidate_rows": len(candidates),
            "candidate_annual_counts": {
                str(year): int(candidates.signal_date.dt.year.eq(year).sum())
                for year in YEARS
            },
            "first_candidate_date": (
                None if candidates.empty else str(candidates.signal_date.min().date())
            ),
            "last_candidate_date": (
                None if candidates.empty else str(candidates.signal_date.max().date())
            ),
            "candidate_symbols": int(candidates.symbol.nunique()),
            "candidate_industries": int(candidates.causal_industry.nunique()),
            "outcome_columns_read": False,
            "forward_or_post_signal_rows_read_as_predictors": False,
            "post_2020_rows_read": False,
            "2021_plus_rows_read": False,
            "charts_rendered": False,
            "stage_b_authorized": False,
            "portfolio_replay_performed": False,
            "alternate_sign_window_or_threshold_tested": False,
            "next_action": (
                "INDEPENDENTLY_AUDIT_STAGE_A; FREEZE_SEPARATE_STAGE_B_BEFORE_OUTCOMES"
                if stage_a_pass
                else (
                    "CLOSE_EXACT_V37_WITHOUT_ALTERNATE_VOLATILITY_ESTIMATOR_"
                    "INNOVATION_TRANSFORM_SIGN_WINDOW_SCHEDULE_PROXY_OR_THRESHOLD"
                )
            ),
        }
        if stage_a_pass:
            representation_path = staging / "representation_panel.parquet"
            candidates_path = staging / "candidates_frozen.parquet"
            write_parquet(representation, representation_path)
            write_parquet(candidates, candidates_path)
            result["representation_sha256"] = sha256(representation_path)
            result["candidates_sha256"] = sha256(candidates_path)
        (staging / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        shutil.rmtree(staging / "duckdb_tmp", ignore_errors=True)

        second_public = verify_public_authorization()
        if second_public["hashes"] != public["hashes"]:
            raise ResearchError("V37 public contract changed during run")
        if verify_source_inputs() != source_hashes:
            raise ResearchError("V37 source inputs changed during run")
        if STAGE_A.exists() or STAGE_A.is_symlink():
            raise ResearchError(f"canonical V37 Stage A appeared: {STAGE_A}")
        atomic_publish_no_replace(staging, STAGE_A)
        return result
    except BaseException:
        if connection is not None:
            connection.close()
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--verify-static-contract",
        action="store_true",
        help="verify only runner/spec; never touch a source or future CY-059 file",
    )
    modes.add_argument(
        "--verify-public-authorization",
        action="store_true",
        help="verify CY-059 public metadata and registry; never touch a source",
    )
    modes.add_argument(
        "--run",
        action="store_true",
        help="run once only after exact CY-059 central installation",
    )
    args = parser.parse_args()
    if args.verify_static_contract:
        print(json.dumps(verify_static_contract(), indent=2, sort_keys=True))
        return
    if args.verify_public_authorization:
        public = verify_public_authorization()
        print(json.dumps(public["hashes"], indent=2, sort_keys=True))
        return
    print(json.dumps(run_stage_a(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
