#!/usr/bin/env python3
"""Attach the one frozen V37 development lifecycle after future CY-061 authorization."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path
from types import ModuleType
from typing import Any

import duckdb
import numpy as np
import pandas as pd

EXPERIMENT = "ASHARE-AGGREGATE-VOLATILITY-INNOVATION-EXPOSURE-COMPENSATION-MOTHER-V37"
REPO = Path(__file__).resolve().parents[3]
EXPERIMENTS = REPO / "research/market_behavior_os_v2/experiments"
SCRIPTS = REPO / "research/market_behavior_os_v2/scripts"
RUNNER = SCRIPTS / (
    "run_ashare_aggregate_volatility_innovation_exposure_compensation_mother_v37_stage_b.py"
)
PARENT_SPEC = EXPERIMENTS / f"{EXPERIMENT}_freeze.json"
STAGE_B_SPEC = EXPERIMENTS / f"{EXPERIMENT}_stage_b_freeze.json"
STAGE_A_RUNNER = SCRIPTS / (
    "run_ashare_aggregate_volatility_innovation_exposure_compensation_mother_v37_stage_a.py"
)
STAGE_A_MANIFEST = EXPERIMENTS / "ASHARE-V37-CY059_DATA_ASSET_MANIFEST.json"
STAGE_B_MANIFEST = EXPERIMENTS / "ASHARE-V37-CY061_DATA_ASSET_MANIFEST.json"
REGISTRY_SUGGESTION = EXPERIMENTS / "ASHARE-V37-CY061_REGISTRY_SUGGESTION.json"
V36_STAGE_B_SPEC = EXPERIMENTS / (
    "ASHARE-BROAD-MARKET-PRICE-DELAY-COMPENSATION-MOTHER-V36_stage_b_freeze.json"
)
EXECUTION_REFERENCE = SCRIPTS / "run_ashare_low_positive_feedback_good_news_mother_v30_stage_b.py"
COORDINATE_BUILDER = SCRIPTS / "run_ashare_former_leader_strict_gap_reclaim_v3.py"
COORDINATE_CONTRACT = REPO / "src/cyq_game/chip/price_coordinate.py"
REGISTRY = REPO / "configs/data_asset_registry.json"
CY006_INVENTORY = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "CY-006-pit-b-daily-v2-2018-2026-20260821.json"
)
QD010_INVENTORY = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/QD-010-cninfo-actions-20260820.json"
)
CY006_ROOT = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily")
PARTITIONS = tuple(
    CY006_ROOT / f"partition_year={year}/data_0.parquet" for year in range(2018, 2022)
)
COORDINATE_STATE = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_adjusted_daily_state_2013_2023.parquet"
)
OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_aggregate_volatility_innovation_exposure_compensation_mother_v37"
)
STAGE_A_RESULT = OUTPUT_ROOT / "stage_a/result.json"
REPRESENTATION = OUTPUT_ROOT / "stage_a/representation_panel.parquet"
CANDIDATES = OUTPUT_ROOT / "stage_a/candidates_frozen.parquet"
STAGE_B = OUTPUT_ROOT / "stage_b"

ASSET_ID = "CY-061"
AUTHORIZATION_ID = (
    "CYQ-AUTH-ASHARE-AGGREGATE-VOLATILITY-INNOVATION-EXPOSURE-"
    "V37-STAGE-B-2018-2021Q3-V1"
)
AUTHORIZATION_PURPOSE = "ASHARE_FROZEN_DEVELOPMENT_OUTCOME_ATTACHMENT"
AUTHORIZED_ARM = "V37_FROZEN_STAGE_B_OUTCOME_ATTACHMENT_ONLY"
MANIFEST_STATUS = "FROZEN_DEVELOPMENT_OUTCOME_BOUNDED_INPUT"
SIGNAL_START = pd.Timestamp("2018-08-31")
SIGNAL_END = pd.Timestamp("2020-12-31")
MAX_PATH_DATE = pd.Timestamp("2021-09-30")
EXPECTED_CANDIDATES = 854
EXPECTED_ANNUAL = {2018: 163, 2019: 357, 2020: 334}
EXPECTED_DECISION_DATES = 29
EXPECTED_SYMBOLS = 688
EXPECTED_INDUSTRIES = 68
EXPECTED_EVENT_SET_SHA256 = "1d716ae548a2feff4b6722242cbe92c82eefdf683b6b3b7add4b22aae952ea70"
YEARS = (2018, 2019, 2020)
TARGET_RETURN = 0.10
HORIZON_SESSIONS = 20
ROUND_TRIP_COST = 0.004
STAGE_B_SPEC_SHA256 = "f2a1f5b7bdfa9d8c960892300b88f4dd55aa8c064dad2c1706710a5b3a4d00aa"

EXPECTED_INPUTS: dict[str, tuple[Path, str]] = {
    "parent_spec": (
        PARENT_SPEC,
        "e1d3f55df399ece5f1395894e8be285a60bf424ebac5bbfa254b020e408e8d44",
    ),
    "stage_b_spec": (STAGE_B_SPEC, STAGE_B_SPEC_SHA256),
    "stage_a_runner": (
        STAGE_A_RUNNER,
        "39eea0f3a9790c53ab4dcbc495dfee5f420fd797bf23f3bc0479d126dd9f9836",
    ),
    "stage_a_manifest": (
        STAGE_A_MANIFEST,
        "d2d16fbf17ff47fc6d6376b129b843d4be061812fc60658f13efdd214ec17f7e",
    ),
    "stage_a_result": (
        STAGE_A_RESULT,
        "ae24cd37c0629abccc8973c5262acfed4bbe9eb0374a371def89e1cfe09b439a",
    ),
    "stage_a_representation": (
        REPRESENTATION,
        "a657e259111291fd3eea66ac3d492e179a4dcba4b5cea573afa00a2162223159",
    ),
    "stage_a_candidates": (
        CANDIDATES,
        "1f890b90b8cdaf26242cd876875d0929bd0050ad9c3dceb71d0c45a49880e509",
    ),
    "accepted_v36_stage_b_spec": (
        V36_STAGE_B_SPEC,
        "c3867b272c05c5e558b56abe6097aa5a7ee6b3bca5c649d577643e0446f47655",
    ),
    "cy006_inventory": (
        CY006_INVENTORY,
        "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2",
    ),
    "qd010_inventory": (
        QD010_INVENTORY,
        "e1ca622ee227ce308b44933160754d450b80d3ecca79c1470037558e1011ceb8",
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
    "cy006_2021": (
        PARTITIONS[3],
        "cbd4b2d2ccdff32b09ed1a2e9347f8045cde89ff7e4e1b189577bc353e4d9311",
    ),
    "coordinate_state": (
        COORDINATE_STATE,
        "76fe88cb7509ae33a3d32b1bfd6d0c90560083127bdfaf63da1d7d24ec72bf60",
    ),
    "coordinate_builder": (
        COORDINATE_BUILDER,
        "358b62014c52b7bf936937746223954512fe9451eaa5009063e14f39e1bb1787",
    ),
    "corporate_action_coordinate_contract": (
        COORDINATE_CONTRACT,
        "60c9f80fcaa2bf4a6ebfaab37bc56e81dd716cc3bea00891b4fc28d077dd1726",
    ),
    "execution_reference": (
        EXECUTION_REFERENCE,
        "1774512c6811fdd0b7c3ea24234254327378faa078f5ecc9fd9078c86d996997",
    ),
}


class ResearchError(RuntimeError):
    """Fail closed on authorization, identity, chronology, or execution drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise ResearchError(f"cannot hash authorized input {path}: {exc}") from exc
    return digest.hexdigest()


def event_set_sha256(values: Iterable[Any]) -> str:
    normalized = sorted(str(value) for value in values)
    return hashlib.sha256(("\n".join(normalized) + "\n").encode("utf-8")).hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ResearchError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ResearchError(f"{label} is not a JSON object")
    return value


def only(items: list[dict[str, Any]], label: str) -> dict[str, Any]:
    if len(items) != 1:
        raise ResearchError(f"expected exactly one {label}, found {len(items)}")
    return items[0]


def role_map(items: Any, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        raise ResearchError(f"{label} is not a list")
    mapped = {
        str(item.get("role")): item
        for item in items
        if isinstance(item, dict) and isinstance(item.get("role"), str)
    }
    if len(mapped) != len(items):
        raise ResearchError(f"{label} contains duplicate or invalid roles")
    return mapped


def public_expected_declarations() -> dict[str, dict[str, str]]:
    return {
        role: {"path": str(path.resolve()), "sha256": digest}
        for role, (path, digest) in EXPECTED_INPUTS.items()
    }


def verify_static_contract() -> dict[str, Any]:
    if sha256(STAGE_B_SPEC) != STAGE_B_SPEC_SHA256:
        raise ResearchError("V37 Stage-B freeze hash drift")
    spec = load_json(STAGE_B_SPEC, "V37 Stage-B freeze")
    parent = spec.get("parent_stage_a", {})
    scope = spec.get("signal_scope", {})
    outcome = spec.get("outcome_attachment", {})
    data = spec.get("outcome_data", {})
    gate = spec.get("development_gate", {})
    auth = spec.get("required_registry_authorization", {})
    if (
        spec.get("frozen_before_any_v37_forward_path_or_payoff_read") is not True
        or parent.get("candidate_rows") != EXPECTED_CANDIDATES
        or parent.get("candidates_sha256") != EXPECTED_INPUTS["stage_a_candidates"][1]
        or parent.get("candidate_event_id_set_sha256") != EXPECTED_EVENT_SET_SHA256
        or scope.get("signal_start") != str(SIGNAL_START.date())
        or scope.get("signal_end") != str(SIGNAL_END.date())
        or scope.get("annual_candidate_rows")
        != {str(year): count for year, count in EXPECTED_ANNUAL.items()}
        or scope.get("candidate_definition_change") is not False
        or scope.get("candidate_sign_or_rank_change") is not False
        or data.get("maximum_path_row_date") != str(MAX_PATH_DATE.date())
        or data.get("2022_plus") != "FORBIDDEN"
        or outcome.get("target_return") != TARGET_RETURN
        or outcome.get("horizon_sessions") != HORIZON_SESSIONS
        or outcome.get("round_trip_cost") != ROUND_TRIP_COST
        or outcome.get("t_plus_one") is not True
        or gate.get("completed_signals_strictly_greater_than_each_year") != 50
        or gate.get("mean_net_return_strictly_greater_than_each_year") != 0.04
        or gate.get("years") != list(YEARS)
        or gate.get("all_years_must_pass") is not True
        or auth.get("asset_id") != ASSET_ID
        or auth.get("authorization_id") != AUTHORIZATION_ID
        or auth.get("purpose") != AUTHORIZATION_PURPOSE
        or auth.get("authorized_arm") != AUTHORIZED_ARM
        or auth.get("outcome_attachment_authorized") is not True
        or auth.get("charts_authorized") is not False
        or auth.get("manual_labels_read_authorized") is not False
        or auth.get("rule_aggregation_authorized") is not False
        or auth.get("portfolio_replay_authorized") is not False
        or auth.get("2022_plus_read_authorized") is not False
    ):
        raise ResearchError("V37 Stage-B static semantic contract drift")
    return {
        "asset_id": ASSET_ID,
        "authorization_id": AUTHORIZATION_ID,
        "candidate_rows": EXPECTED_CANDIDATES,
        "runner": sha256(RUNNER),
        "stage_b_spec": STAGE_B_SPEC_SHA256,
        "status": "STATIC_CONTRACT_VALID_NO_RESEARCH_SOURCE_TOUCHED",
    }


def verify_public_envelope() -> dict[str, str]:
    verify_static_contract()
    public_files = [
        RUNNER,
        STAGE_B_MANIFEST,
        REGISTRY_SUGGESTION,
        REGISTRY,
    ]
    public_files.extend(
        path for path, _digest in EXPECTED_INPUTS.values() if path.is_relative_to(REPO)
    )
    for path in public_files:
        if not path.is_file():
            raise ResearchError(f"missing public authorization artifact: {path}")
    for role, (path, expected) in EXPECTED_INPUTS.items():
        if path.is_relative_to(REPO) and sha256(path) != expected:
            raise ResearchError(f"public frozen input drift: {role}")

    runner_hash = sha256(RUNNER)
    manifest_hash = sha256(STAGE_B_MANIFEST)
    suggestion_hash = sha256(REGISTRY_SUGGESTION)
    manifest = load_json(STAGE_B_MANIFEST, "CY-061 manifest")
    suggestion = load_json(REGISTRY_SUGGESTION, "CY-061 registry suggestion")
    declared = public_expected_declarations()
    source = role_map(manifest.get("source_artifacts"), "manifest source artifacts")
    lineage = role_map(manifest.get("public_lineage_artifacts"), "manifest lineage artifacts")
    if set(source) | set(lineage) != set(declared) or set(source) & set(lineage):
        raise ResearchError("CY-061 manifest role partition drift")
    for role, item in {**source, **lineage}.items():
        if (
            item.get("path") != declared[role]["path"]
            or item.get("sha256") != declared[role]["sha256"]
        ):
            raise ResearchError(f"CY-061 manifest binding drift: {role}")
    boundary = manifest.get("authorization_boundary", {})
    protocol = manifest.get("protocol", {})
    cohort = manifest.get("frozen_cohort", {})
    if (
        manifest.get("asset_id") != ASSET_ID
        or manifest.get("status") != MANIFEST_STATUS
        or manifest.get("pit_grade") != "B"
        or protocol.get("stage_b_spec_path") != str(STAGE_B_SPEC.resolve())
        or protocol.get("stage_b_spec_sha256") != STAGE_B_SPEC_SHA256
        or protocol.get("stage_b_runner_path") != str(RUNNER.resolve())
        or protocol.get("stage_b_runner_sha256") != runner_hash
        or cohort.get("rows") != EXPECTED_CANDIDATES
        or cohort.get("sha256") != EXPECTED_INPUTS["stage_a_candidates"][1]
        or cohort.get("event_id_set_sha256") != EXPECTED_EVENT_SET_SHA256
        or boundary.get("authorization_id") != AUTHORIZATION_ID
        or boundary.get("purpose") != AUTHORIZATION_PURPOSE
        or boundary.get("authorized_arm") != AUTHORIZED_ARM
        or boundary.get("signal_start") != str(SIGNAL_START.date())
        or boundary.get("signal_end") != str(SIGNAL_END.date())
        or boundary.get("maximum_path_row_date") != str(MAX_PATH_DATE.date())
        or boundary.get("frozen_candidate_rows") != EXPECTED_CANDIDATES
        or boundary.get("outcome_attachment_authorized") is not True
        or boundary.get("charts_authorized") is not False
        or boundary.get("manual_labels_read_authorized") is not False
        or boundary.get("rule_aggregation_authorized") is not False
        or boundary.get("portfolio_replay_authorized") is not False
        or boundary.get("2022_plus_read_authorized") is not False
    ):
        raise ResearchError("CY-061 manifest semantics drift")

    suggested_asset = suggestion.get("asset")
    suggested_auth = suggestion.get("bounded_authorization")
    if not isinstance(suggested_asset, dict) or not isinstance(suggested_auth, dict):
        raise ResearchError("CY-061 suggestion structure drift")
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
    if asset != suggested_asset or authorization != suggested_auth:
        raise ResearchError("installed CY-061 registry objects differ from frozen suggestion")
    asset_lineage = asset.get("lineage", {})
    bound_protocol = authorization.get("bound_protocol", {})
    if (
        asset_lineage.get("manifest_path") != str(STAGE_B_MANIFEST.resolve())
        or asset_lineage.get("manifest_sha256") != manifest_hash
        or bound_protocol.get("path") != str(STAGE_B_SPEC.resolve())
        or bound_protocol.get("sha256") != STAGE_B_SPEC_SHA256
        or bound_protocol.get("runner_path") != str(RUNNER.resolve())
        or bound_protocol.get("runner_sha256") != runner_hash
    ):
        raise ResearchError("installed CY-061 lineage/protocol drift")
    bound = role_map(authorization.get("bound_artifacts"), "CY-061 bound artifacts")
    if set(bound) != set(declared):
        raise ResearchError("CY-061 bound-artifact role set drift")
    for role, expected in declared.items():
        if (
            bound[role].get("path") != expected["path"]
            or bound[role].get("sha256") != expected["sha256"]
        ):
            raise ResearchError(f"CY-061 authorization binding drift: {role}")
    return {
        "runner": runner_hash,
        "manifest": manifest_hash,
        "registry_suggestion": suggestion_hash,
        "registry": sha256(REGISTRY),
    }


def verify_inputs() -> tuple[dict[str, str], dict[str, Any], dict[str, str]]:
    public = verify_public_envelope()
    actual: dict[str, str] = {}
    for role, (path, expected) in EXPECTED_INPUTS.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input: {role}: {path}")
        value = sha256(path)
        if value != expected:
            raise ResearchError(f"frozen input drift: {role}: {value} != {expected}")
        actual[role] = value
    stage_a = load_json(STAGE_A_RESULT, "V37 Stage-A result")
    if (
        stage_a.get("semantic_gate_passed") is not True
        or stage_a.get("representation_gate_passed") is not True
        or stage_a.get("opportunity_gate_passed") is not True
        or stage_a.get("neighboring_definition_stability_gate_passed") is not True
        or stage_a.get("redundancy_gate_passed") is not True
        or stage_a.get("stage_a_gate_passed") is not True
        or stage_a.get("outcome_columns_read") is not False
        or stage_a.get("forward_or_post_signal_rows_read_as_predictors") is not False
        or stage_a.get("post_2020_rows_read") is not False
        or stage_a.get("candidate_rows") != EXPECTED_CANDIDATES
        or stage_a.get("candidate_annual_counts")
        != {str(year): count for year, count in EXPECTED_ANNUAL.items()}
        or stage_a.get("first_candidate_date") != str(SIGNAL_START.date())
        or stage_a.get("last_candidate_date") != str(SIGNAL_END.date())
        or stage_a.get("candidates_sha256") != EXPECTED_INPUTS["stage_a_candidates"][1]
        or stage_a.get("representation_sha256")
        != EXPECTED_INPUTS["stage_a_representation"][1]
    ):
        raise ResearchError("V37 Stage-A result does not authorize Stage B")
    return actual, stage_a, public


def load_execution_reference() -> ModuleType:
    module_spec = importlib.util.spec_from_file_location(
        "v30_frozen_execution_reference_for_v37", EXECUTION_REFERENCE
    )
    if module_spec is None or module_spec.loader is None:
        raise ResearchError("cannot load frozen execution reference")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    if (
        module.TARGET_RETURN != TARGET_RETURN
        or module.HORIZON_SESSIONS != HORIZON_SESSIONS
        or module.ROUND_TRIP_COST != ROUND_TRIP_COST
    ):
        raise ResearchError("frozen execution-reference constants drift")
    module.MAX_PATH_DATE = MAX_PATH_DATE
    return module


def connect(temporary: Path) -> duckdb.DuckDBPyConnection:
    temporary.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute("SET threads=4")
    connection.execute("SET memory_limit='12GB'")
    connection.execute(f"SET temp_directory='{temporary.as_posix()}'")
    connection.from_parquet(
        [str(path) for path in PARTITIONS], union_by_name=True
    ).create_view("cy006")
    return connection


def prepare_candidates(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    prepared = connection.execute(
        f"""
        SELECT c.* EXCLUDE(signal_cal_idx),c.signal_cal_idx AS source_signal_cal_idx,
          a.cal_idx AS signal_cal_idx,a.invalid_step_cum,
          CAST('AGGREGATE_VOLATILITY_INNOVATION_EXPOSURE' AS VARCHAR) AS sleeve,
          r.trade_date AS raw_signal_date,a.trade_date AS coordinate_signal_date,
          r.industry AS raw_signal_industry,r.available_at AS signal_row_available_at,
          r.decision_at AS signal_row_decision_at,
          r.corporate_action_count AS signal_corporate_action_count,
          a.adjusted_close/r.close AS signal_coordinate_factor
        FROM read_parquet('{CANDIDATES.as_posix()}') c
        JOIN cy006 r ON r.symbol=c.symbol AND r.trade_date=c.signal_date
        JOIN read_parquet('{COORDINATE_STATE.as_posix()}') a
          ON a.symbol=c.symbol AND a.trade_date=c.signal_date
        WHERE c.signal_date BETWEEN DATE '{SIGNAL_START.date()}' AND DATE '{SIGNAL_END.date()}'
          AND c.selection_rank=1 AND c.canonical_status='VALID'
          AND isfinite(c.negative_aggregate_volatility_innovation_beta_120)
          AND isfinite(c.beta_volatility_innovation_120)
          AND c.available_at<=c.decision_at
          AND r.trade_status=1 AND r.hard_valid AND r.bar_valid
          AND r.trading_state_valid AND r.corporate_action_valid
          AND NOT r.corporate_action_blocking AND r.market_valid
          AND r.market_rule_valid AND r.historical_identity_valid
          AND r.current_day_data_tradable AND r.available_at<=r.decision_at
          AND r.open>0 AND r.high>0 AND r.low>0 AND r.close>0
          AND isfinite(r.open) AND isfinite(r.high) AND isfinite(r.low) AND isfinite(r.close)
          AND r.high>=r.open AND r.high>=r.close
          AND r.low<=r.open AND r.low<=r.close
          AND a.current_valid AND a.corporate_action_valid
          AND NOT a.corporate_action_blocking AND a.adjusted_close>0
          AND isfinite(a.adjusted_close) AND isfinite(a.invalid_step_cum)
          AND isfinite(a.adjusted_close/r.close)
          AND r.industry=c.causal_industry
        ORDER BY c.signal_date,c.causal_industry,c.symbol,c.event_id
        """
    ).fetch_df()
    date_columns = (
        "signal_date",
        "decision_at",
        "available_at",
        "raw_signal_date",
        "coordinate_signal_date",
        "signal_row_available_at",
        "signal_row_decision_at",
    )
    for column in date_columns:
        prepared[column] = pd.to_datetime(prepared[column])
    required = (
        "event_id",
        "symbol",
        "signal_date",
        "source_signal_cal_idx",
        "signal_cal_idx",
        "invalid_step_cum",
        "causal_industry",
        "decision_at",
        "available_at",
        "signal_row_available_at",
        "signal_row_decision_at",
        "signal_corporate_action_count",
        "negative_aggregate_volatility_innovation_beta_120",
        "beta_volatility_innovation_120",
        "canonical_status",
        "selection_rank",
        "snapshot_id",
        "daily_snapshot_id",
        "trading_state_snapshot_id",
        "industry_snapshot_id",
        "float_snapshot_id",
        "corporate_action_snapshot_id",
        "market_snapshot_id",
        "signal_coordinate_factor",
        "sleeve",
    )
    missing = sorted(set(required).difference(prepared.columns))
    if missing:
        raise ResearchError(f"prepared candidate schema misses state: {missing}")
    annual = {
        int(year): int(count)
        for year, count in prepared.signal_date.dt.year.value_counts().items()
    }
    snapshot_columns = [name for name in required if name.endswith("snapshot_id")]
    snapshots = prepared[snapshot_columns].astype("string")
    numeric = prepared[
        [
            "invalid_step_cum",
            "signal_coordinate_factor",
            "signal_corporate_action_count",
            "negative_aggregate_volatility_innovation_beta_120",
            "beta_volatility_innovation_120",
        ]
    ].apply(pd.to_numeric, errors="coerce")
    offsets = prepared.signal_cal_idx - prepared.source_signal_cal_idx
    expected_ids = (
        "AGGREGATE_VOLATILITY_INNOVATION_EXPOSURE|"
        + prepared.signal_date.dt.strftime("%Y%m%d")
        + "|"
        + prepared.causal_industry.astype(str)
        + "|"
        + prepared.symbol.astype(str)
    )
    audit = {
        "rows": len(prepared),
        "expected_rows": EXPECTED_CANDIDATES,
        "unique_event_ids": int(prepared.event_id.nunique()),
        "duplicate_event_ids": int(prepared.event_id.duplicated().sum()),
        "event_id_set_sha256": event_set_sha256(prepared.event_id.astype(str)),
        "event_id_reconstruction_mismatches": int(prepared.event_id.ne(expected_ids).sum()),
        "first_signal_date": str(prepared.signal_date.min().date()),
        "last_signal_date": str(prepared.signal_date.max().date()),
        "decision_dates": int(prepared.signal_date.nunique()),
        "symbols": int(prepared.symbol.nunique()),
        "industries": int(prepared.causal_industry.nunique()),
        "annual_counts": {str(key): value for key, value in sorted(annual.items())},
        "signal_date_join_mismatches": int(
            (
                prepared.raw_signal_date.ne(prepared.signal_date)
                | prepared.coordinate_signal_date.ne(prepared.signal_date)
            ).sum()
        ),
        "coordinate_calendar_offset_unique_values": int(offsets.nunique(dropna=False)),
        "coordinate_calendar_offset": None
        if offsets.empty or offsets.nunique(dropna=False) != 1
        else int(offsets.iloc[0]),
        "industry_identity_mismatches": int(
            prepared.raw_signal_industry.ne(prepared.causal_industry).sum()
        ),
        "candidate_available_after_decision_rows": int(
            prepared.available_at.gt(prepared.decision_at).sum()
        ),
        "signal_row_available_after_decision_rows": int(
            prepared.signal_row_available_at.gt(prepared.signal_row_decision_at).sum()
        ),
        "signal_decision_identity_mismatches": int(
            prepared.decision_at.ne(prepared.signal_row_decision_at).sum()
        ),
        "missing_required_values": int(prepared[list(required)].isna().any(axis=1).sum()),
        "blank_snapshot_values": int(
            (snapshots.isna() | snapshots.apply(lambda column: column.str.strip().eq("")))
            .any(axis=1)
            .sum()
        ),
        "nonfinite_numeric_values": int((~np.isfinite(numeric.to_numpy(float))).any(axis=1).sum()),
        "non_rank_one_rows": int(prepared.selection_rank.ne(1).sum()),
        "invalid_canonical_status_rows": int(prepared.canonical_status.ne("VALID").sum()),
    }
    zero_keys = (
        "duplicate_event_ids",
        "event_id_reconstruction_mismatches",
        "signal_date_join_mismatches",
        "industry_identity_mismatches",
        "candidate_available_after_decision_rows",
        "signal_row_available_after_decision_rows",
        "signal_decision_identity_mismatches",
        "missing_required_values",
        "blank_snapshot_values",
        "nonfinite_numeric_values",
        "non_rank_one_rows",
        "invalid_canonical_status_rows",
    )
    if (
        audit["rows"] != EXPECTED_CANDIDATES
        or audit["unique_event_ids"] != EXPECTED_CANDIDATES
        or audit["event_id_set_sha256"] != EXPECTED_EVENT_SET_SHA256
        or audit["first_signal_date"] != str(SIGNAL_START.date())
        or audit["last_signal_date"] != str(SIGNAL_END.date())
        or audit["decision_dates"] != EXPECTED_DECISION_DATES
        or audit["symbols"] != EXPECTED_SYMBOLS
        or audit["industries"] != EXPECTED_INDUSTRIES
        or annual != EXPECTED_ANNUAL
        or audit["coordinate_calendar_offset_unique_values"] != 1
        or any(audit[key] for key in zero_keys)
    ):
        raise ResearchError(f"candidate execution-coordinate join failed: {audit}")
    return prepared, audit


def build_paths(
    connection: duckdb.DuckDBPyConnection,
    candidates: pd.DataFrame,
    output: Path,
) -> tuple[pd.DataFrame, dict[str, int]]:
    keys = candidates[["event_id", "symbol", "signal_date", "signal_cal_idx"]].copy()
    connection.register("candidate_keys", keys)
    calendar = connection.execute(
        f"""
        SELECT count(*),count(*) FILTER (WHERE cal_indices<>1),max(cal_idx)
        FROM (
          SELECT trade_date,count(DISTINCT cal_idx) AS cal_indices,min(cal_idx) AS cal_idx
          FROM read_parquet('{COORDINATE_STATE.as_posix()}')
          WHERE trade_date BETWEEN DATE '{SIGNAL_START.date()}' AND DATE '{MAX_PATH_DATE.date()}'
          GROUP BY trade_date
        )
        """
    ).fetchone()
    if calendar is None or calendar[0] is None or int(calendar[1]):
        raise ResearchError(f"coordinate global calendar is not unique: {calendar}")
    query = f"""
      WITH global_calendar AS (
        SELECT trade_date,min(cal_idx) AS cal_idx
        FROM read_parquet('{COORDINATE_STATE.as_posix()}')
        WHERE trade_date BETWEEN DATE '{SIGNAL_START.date()}' AND DATE '{MAX_PATH_DATE.date()}'
        GROUP BY trade_date HAVING count(DISTINCT cal_idx)=1
      ), raw_event_path AS (
        SELECT c.event_id,c.symbol,c.signal_date AS event_signal_date,
          c.signal_cal_idx AS event_signal_cal_idx,g.cal_idx,r.* EXCLUDE(symbol,trade_date),
          r.trade_date
        FROM candidate_keys c JOIN cy006 r USING(symbol)
        JOIN global_calendar g USING(trade_date)
        WHERE r.trade_date BETWEEN DATE '{SIGNAL_START.date()}' AND DATE '{MAX_PATH_DATE.date()}'
          AND g.cal_idx>c.signal_cal_idx AND g.cal_idx<=c.signal_cal_idx+126
          AND (year(r.trade_date)<=2020 OR year(c.signal_date)=2020)
      ), coordinate_path AS (
        SELECT a.* FROM read_parquet('{COORDINATE_STATE.as_posix()}') a
        WHERE a.trade_date BETWEEN DATE '{SIGNAL_START.date()}' AND DATE '{MAX_PATH_DATE.date()}'
      )
      SELECT r.event_id,r.symbol,r.event_signal_date,r.event_signal_cal_idx,
        r.trade_date,r.cal_idx,r.open,r.high,r.low,r.close,
        a.adjusted_close*(r.open/r.close) AS coord_open,
        a.adjusted_close*(r.high/r.close) AS coord_high,
        a.adjusted_close*(r.low/r.close) AS coord_low,a.adjusted_close AS coord_close,
        a.invalid_step_cum,a.adjusted_close/r.close AS coordinate_factor,
        r.trade_status,r.current_day_data_tradable,a.current_valid,r.market_rule_valid,
        r.corporate_action_count,r.corporate_action_valid,r.corporate_action_blocking,
        r.hard_valid,r.up_limit_price,r.down_limit_price,r.available_at,r.decision_at
      FROM raw_event_path r JOIN coordinate_path a USING(symbol,trade_date)
      WHERE a.cal_idx=r.cal_idx AND r.close>0 AND a.adjusted_close>0
        AND isfinite(r.close) AND isfinite(a.adjusted_close)
      ORDER BY r.event_id,r.cal_idx
    """
    connection.execute(
        f"COPY ({query}) TO '{output.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    paths = connection.execute(
        f"SELECT * FROM read_parquet('{output.as_posix()}') ORDER BY event_id,cal_idx"
    ).fetch_df()
    connection.unregister("candidate_keys")
    for column in ("event_signal_date", "trade_date", "available_at", "decision_at"):
        paths[column] = pd.to_datetime(paths[column])
    raw_prices = paths[["open", "high", "low", "close"]].apply(
        pd.to_numeric, errors="coerce"
    )
    raw_finite_positive = np.isfinite(raw_prices.to_numpy(float)).all(axis=1) & raw_prices.gt(
        0
    ).all(axis=1)
    raw_geometry = (
        paths.high.ge(paths.open)
        & paths.high.ge(paths.close)
        & paths.low.le(paths.open)
        & paths.low.le(paths.close)
    )
    coordinate_prices = paths[["coord_open", "coord_high", "coord_low", "coord_close"]].apply(
        pd.to_numeric, errors="coerce"
    )
    audit = {
        "global_calendar_dates": int(calendar[0]),
        "global_calendar_nonunique_dates": int(calendar[1]),
        "authorized_cap_cal_idx": int(calendar[2]),
        "minimum_calendar_sessions_after_latest_signal": int(
            int(calendar[2]) - int(candidates.signal_cal_idx.max())
        ),
        "rows": len(paths),
        "events_with_rows": int(paths.event_id.nunique()),
        "events_without_exact_126_slots": int(
            paths.groupby("event_id").cal_idx.nunique().ne(126).sum()
        ),
        "duplicate_event_cal_idx": int(paths.duplicated(["event_id", "cal_idx"]).sum()),
        "at_or_before_signal_rows": int(
            paths.cal_idx.le(paths.event_signal_cal_idx).sum()
        ),
        "post_cap_rows": int(paths.trade_date.gt(MAX_PATH_DATE).sum()),
        "after_plus126_rows": int(
            paths.cal_idx.gt(paths.event_signal_cal_idx + 126).sum()
        ),
        "2021_rows_for_pre_2020_signals": int(
            (paths.trade_date.dt.year.eq(2021) & paths.event_signal_date.dt.year.lt(2020)).sum()
        ),
        "2022_plus_rows": int(paths.trade_date.dt.year.ge(2022).sum()),
        "raw_ohlc_nonfinite_or_nonpositive_rows": int((~raw_finite_positive).sum()),
        "raw_ohlc_geometry_failures": int((~raw_geometry).sum()),
        "coordinate_ohlc_nonfinite_or_nonpositive_rows": int(
            (
                (~np.isfinite(coordinate_prices.to_numpy(float))).any(axis=1)
                | coordinate_prices.le(0).any(axis=1)
            ).sum()
        ),
    }
    blocking = (
        "events_without_exact_126_slots",
        "duplicate_event_cal_idx",
        "at_or_before_signal_rows",
        "post_cap_rows",
        "after_plus126_rows",
        "2021_rows_for_pre_2020_signals",
        "2022_plus_rows",
        "raw_ohlc_nonfinite_or_nonpositive_rows",
        "raw_ohlc_geometry_failures",
        "coordinate_ohlc_nonfinite_or_nonpositive_rows",
    )
    if (
        audit["minimum_calendar_sessions_after_latest_signal"] < 126
        or audit["events_with_rows"] != EXPECTED_CANDIDATES
        or any(audit[key] for key in blocking)
    ):
        raise ResearchError(f"future-path coverage failed: {audit}")
    return paths, audit


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    connection = duckdb.connect()
    try:
        connection.register("frame", frame)
        connection.execute(
            f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    finally:
        connection.close()


def group_summary(outcomes: pd.DataFrame, candidates: pd.DataFrame) -> dict[str, Any]:
    completed = outcomes.loc[outcomes.status.eq("COMPLETED")].copy()
    return {
        "signals": len(candidates),
        "completed": len(completed),
        "decision_dates": int(candidates.signal_date.nunique()),
        "symbols": int(candidates.symbol.nunique()),
        "industries": int(candidates.causal_industry.nunique()),
        "mean_net": None if completed.empty else float(completed.net_return.mean()),
        "median_net": None if completed.empty else float(completed.net_return.median()),
        "positive_rate": None if completed.empty else float(completed.net_return.gt(0).mean()),
        "severe10_rate": None if completed.empty else float(completed.net_return.le(-0.10).mean()),
        "target_hit_rate": None
        if completed.empty
        else float(completed.exit_reason.eq("TARGET_10").mean()),
    }


def summarize(
    outcomes: pd.DataFrame,
    candidates: pd.DataFrame,
    source_hashes: dict[str, str],
    public_hashes: dict[str, str],
    candidate_audit: dict[str, Any],
    path_audit: dict[str, Any],
    outcome_audit: dict[str, Any],
    prepared_path: Path,
    paths_path: Path,
    outcomes_path: Path,
) -> dict[str, Any]:
    annual: dict[str, Any] = {}
    gate = True
    for year in YEARS:
        cohort = candidates.loc[candidates.signal_date.dt.year.eq(year)]
        event_ids = set(cohort.event_id.astype(str))
        result = group_summary(outcomes.loc[outcomes.event_id.isin(event_ids)], cohort)
        annual[str(year)] = result
        gate &= (
            result["completed"] > 50
            and result["mean_net"] is not None
            and result["mean_net"] > 0.04
        )
    return {
        "experiment": EXPERIMENT,
        "stage": "SEPARATELY_AUTHORIZED_FROZEN_DEVELOPMENT_OUTCOME_ATTACHMENT",
        "asset_id": ASSET_ID,
        "authorization_id": AUTHORIZATION_ID,
        "authorized_arm": AUTHORIZED_ARM,
        "source_hashes": source_hashes,
        "public_authorization_hashes": public_hashes,
        "prepared_candidates_sha256": sha256(prepared_path),
        "future_paths_sha256": sha256(paths_path),
        "outcomes_sha256": sha256(outcomes_path),
        "candidate_coordinate_audit": candidate_audit,
        "path_audit": path_audit,
        "outcome_audit": outcome_audit,
        "status_counts": {
            str(key): int(value) for key, value in outcomes.status.value_counts().items()
        },
        "overall": group_summary(outcomes, candidates),
        "annual": annual,
        "development_gate_passed": bool(gate),
        "annual_gate_definition": "completed>50 AND mean_net>0.04 in every 2018-2020 cohort",
        "later_period_authorized": False,
        "manual_labels_read_or_grouped": False,
        "charts_rendered": False,
        "rule_aggregation_performed": False,
        "portfolio_replay_performed": False,
        "2021_signal_rows_read": False,
        "2021_rows_used_only_as_late_2020_path_buffer": True,
        "2022_plus_row_read": False,
        "maximum_path_row_date": str(MAX_PATH_DATE.date()),
        "maximum_event_path_sessions": 126,
        "target_return": TARGET_RETURN,
        "horizon_sessions": HORIZON_SESSIONS,
        "round_trip_cost": ROUND_TRIP_COST,
        "next_action": (
            "CLOSE_EXACT_V37_STRATEGY_USEFULNESS_CLAIM_WITHOUT_RESCUE"
            if not gate
            else "FREEZE_ANY_NEXT_ANATOMY_BEFORE_READING_OR_GROUPING_MORE_INFORMATION"
        ),
    }


def atomic_publish_no_replace(source: Path, destination: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    rename_exclusive = getattr(libc, "renamex_np", None)
    if rename_exclusive is None:
        raise ResearchError("atomic exclusive directory rename is unavailable")
    rename_exclusive.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    rename_exclusive.restype = ctypes.c_int
    if rename_exclusive(os.fsencode(source), os.fsencode(destination), 0x00000004):
        error = ctypes.get_errno()
        raise ResearchError(f"atomic no-overwrite publication failed: {os.strerror(error)}")


def run() -> dict[str, Any]:
    if STAGE_B.exists() or STAGE_B.is_symlink():
        raise ResearchError(f"canonical V37 Stage B already exists: {STAGE_B}")
    source_hashes, _stage_a, public_hashes = verify_inputs()
    execution = load_execution_reference()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".stage_b_staging_", dir=OUTPUT_ROOT))
    connection: duckdb.DuckDBPyConnection | None = None
    try:
        connection = connect(staging / "duckdb_tmp")
        candidates, candidate_audit = prepare_candidates(connection)
        prepared_path = staging / "prepared_candidates.parquet"
        paths_path = staging / "future_paths.parquet"
        outcomes_path = staging / "outcomes.parquet"
        write_parquet(candidates, prepared_path)
        paths, path_source_audit = build_paths(connection, candidates, paths_path)
        path_audit = execution.audit_paths(paths, candidates)
        path_audit.update(path_source_audit)
        if path_audit["candidate_events_without_rows"]:
            raise ResearchError(f"candidate lacks authorized future path: {path_audit}")
        outcomes = execution.attach_outcomes(candidates, paths)
        outcome_audit = execution.audit_outcomes(outcomes, candidates)
        write_parquet(outcomes, outcomes_path)
        result = summarize(
            outcomes,
            candidates,
            source_hashes,
            public_hashes,
            candidate_audit,
            path_audit,
            outcome_audit,
            prepared_path,
            paths_path,
            outcomes_path,
        )
        (staging / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        connection.close()
        connection = None
        shutil.rmtree(staging / "duckdb_tmp", ignore_errors=True)
        if verify_inputs()[0] != source_hashes:
            raise ResearchError("bound source changed during V37 Stage B")
        if verify_public_envelope() != public_hashes:
            raise ResearchError("public authorization changed during V37 Stage B")
        atomic_publish_no_replace(staging, STAGE_B)
    except Exception:
        if connection is not None:
            connection.close()
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--verify-static-contract", action="store_true")
    mode.add_argument("--verify-public-inputs", action="store_true")
    mode.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.verify_static_contract:
        print(json.dumps(verify_static_contract(), indent=2, sort_keys=True))
        return
    if args.verify_public_inputs:
        print(json.dumps(verify_public_envelope(), indent=2, sort_keys=True))
        return
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
