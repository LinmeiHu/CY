#!/usr/bin/env python3
"""Attach the frozen V35 development lifecycle, but only after exact CY-053 install."""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import importlib.util
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any

import duckdb
import numpy as np
import pandas as pd

EXPERIMENT = "ASHARE-BOARD-LOT-AFFORDABILITY-CLIENTELE-MOTHER-V35"
REPO = Path(__file__).resolve().parents[3]
EXPERIMENTS = REPO / "research/market_behavior_os_v2/experiments"
SCRIPTS = REPO / "research/market_behavior_os_v2/scripts"
RUNNER = SCRIPTS / "run_ashare_board_lot_affordability_clientele_mother_v35_stage_b.py"
PARENT_SPEC = EXPERIMENTS / f"{EXPERIMENT}_freeze.json"
STAGE_B_SPEC = EXPERIMENTS / f"{EXPERIMENT}_stage_b_freeze.json"
STAGE_A_RUNNER = SCRIPTS / f"run_{EXPERIMENT.lower().replace('-', '_')}_stage_a.py"
STAGE_A_MANIFEST = EXPERIMENTS / "ASHARE-V35-CY051_DATA_ASSET_MANIFEST.json"
STAGE_B_MANIFEST = EXPERIMENTS / "ASHARE-V35-CY053_DATA_ASSET_MANIFEST.json"
REGISTRY_SUGGESTION = EXPERIMENTS / "ASHARE-V35-CY053_REGISTRY_SUGGESTION.json"
EXECUTION_REFERENCE = SCRIPTS / "run_ashare_low_positive_feedback_good_news_mother_v30_stage_b.py"
COORDINATE_BUILDER = SCRIPTS / "run_ashare_former_leader_strict_gap_reclaim_v3.py"
COORDINATE_CONTRACT = REPO / "src/cyq_game/chip/price_coordinate.py"
REGISTRY = REPO / "configs/data_asset_registry.json"
CY006_MANIFEST = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "CY-006-pit-b-daily-v2-2018-2026-20260821.json"
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
    "/Volumes/quant/CY_quant_research/ashare_board_lot_affordability_clientele_mother_v35"
)
STAGE_A_RESULT = OUTPUT_ROOT / "stage_a/result.json"
CANDIDATES = OUTPUT_ROOT / "stage_a/candidates_frozen.parquet"
STAGE_B = OUTPUT_ROOT / "stage_b"

ASSET_ID = "CY-053"
AUTHORIZATION_ID = "CYQ-AUTH-ASHARE-BOARD-LOT-AFFORDABILITY-V35-STAGE-B-2018-2021H1-V1"
AUTHORIZATION_PURPOSE = "ASHARE_FROZEN_DEVELOPMENT_OUTCOME_ATTACHMENT"
AUTHORIZED_ARM = "V35_FROZEN_STAGE_B_OUTCOME_ATTACHMENT_ONLY"
MANIFEST_STATUS = "FROZEN_DEVELOPMENT_OUTCOME_BOUNDED_INPUT"
SIGNAL_START = pd.Timestamp("2018-01-05")
SIGNAL_END = pd.Timestamp("2020-12-04")
MAX_PATH_DATE = pd.Timestamp("2021-06-30")
EXPECTED_CANDIDATES = 1_047
YEARS = (2018, 2019, 2020)
EXPECTED_ANNUAL = {2018: 365, 2019: 326, 2020: 356}
STAGE_B_SPEC_SHA256 = "a8c1d010bc8bf150e55264267d46c9d73168811ea721356d39f28395527dae0d"

# Merely constructing this map performs no filesystem resolution. The exact lexical
# path/hash declarations are checked publicly before any member is opened or stated.
EXPECTED_INPUTS: dict[str, tuple[Path, str]] = {
    "parent_spec": (
        PARENT_SPEC,
        "31d2da975d9d1d6c57b91dfd5eac26b2cb0fc0001cb4055c5c1c629dded9ffe0",
    ),
    "stage_b_spec": (STAGE_B_SPEC, STAGE_B_SPEC_SHA256),
    "stage_a_runner": (
        STAGE_A_RUNNER,
        "5b403fddf00112ea62c9c67a10a78a131bc7936a329c62f0fdd2dd9b69a7d814",
    ),
    "stage_a_manifest": (
        STAGE_A_MANIFEST,
        "74ec117836c04003e600fc105096ef4ae8ec95e60b418f68abe84ab991d63b94",
    ),
    "stage_a_result": (
        STAGE_A_RESULT,
        "a0a425be6995809689c310bf0a373283abe6e9623890942075b8bd0feea9c976",
    ),
    "stage_a_candidates": (
        CANDIDATES,
        "4fef77ac834a55a2805dd93c2359e218c0c47dec5a154f7cb9585e8d15b2cd81",
    ),
    "cy006_manifest": (
        CY006_MANIFEST,
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
        raise ResearchError(f"{label} is not an object")
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


def verify_role_declarations(items: Any, label: str) -> None:
    mapped = role_map(items, label)
    if set(mapped) != set(EXPECTED_INPUTS):
        raise ResearchError(f"{label} exact role set drift")
    for role, (path, expected_hash) in EXPECTED_INPUTS.items():
        item = mapped[role]
        if set(item) != {"role", "path", "sha256"}:
            raise ResearchError(f"{label} unexpected fields for {role}")
        if item["path"] != str(path) or item["sha256"] != expected_hash:
            raise ResearchError(f"{label} lexical binding drift for {role}")


def verify_public_contract() -> dict[str, Any]:
    """Validate repository declarations only; never touch a bound source path."""

    public_paths = (STAGE_B_SPEC, STAGE_B_MANIFEST, REGISTRY_SUGGESTION, RUNNER)
    for path in public_paths:
        if not path.is_file():
            raise ResearchError(f"missing public contract artifact: {path}")
    public_hashes = {
        "stage_b_spec": sha256(STAGE_B_SPEC),
        "stage_b_manifest": sha256(STAGE_B_MANIFEST),
        "registry_suggestion": sha256(REGISTRY_SUGGESTION),
        "stage_b_runner": sha256(RUNNER),
    }
    if public_hashes["stage_b_spec"] != STAGE_B_SPEC_SHA256:
        raise ResearchError("V35 Stage-B spec drift")

    spec = load_json(STAGE_B_SPEC, "V35 Stage-B spec")
    manifest = load_json(STAGE_B_MANIFEST, "CY-053 manifest")
    suggestion = load_json(REGISTRY_SUGGESTION, "CY-053 registry suggestion")
    protocol = manifest.get("protocol", {})
    boundary = manifest.get("authorization_boundary", {})
    if (
        spec.get("research_status") != "PRE_OUTCOME_EXECUTION_FREEZE_AWAITING_CY053_REGISTRATION"
        or spec.get("frozen_before_any_v35_forward_path_or_payoff_read") is not True
        or manifest.get("asset_id") != ASSET_ID
        or manifest.get("status") != MANIFEST_STATUS
        or boundary.get("authorization_id") != AUTHORIZATION_ID
        or boundary.get("purpose") != AUTHORIZATION_PURPOSE
        or boundary.get("authorized_arm") != AUTHORIZED_ARM
        or boundary.get("signal_start") != str(SIGNAL_START.date())
        or boundary.get("signal_end") != str(SIGNAL_END.date())
        or boundary.get("maximum_path_row_date") != str(MAX_PATH_DATE.date())
        or boundary.get("frozen_candidate_rows") != EXPECTED_CANDIDATES
        or boundary.get("outcome_attachment_authorized") is not True
        or boundary.get("charts_authorized") is not False
        or boundary.get("portfolio_replay_authorized") is not False
        or boundary.get("candidate_reselection_authorized") is not False
        or boundary.get("post_2021_h1_read_authorized") is not False
        or boundary.get("2022_plus_read_authorized") is not False
        or boundary.get("current_survivor_fallback_allowed") is not False
        or protocol.get("stage_b_spec_path") != str(STAGE_B_SPEC)
        or protocol.get("stage_b_spec_sha256") != public_hashes["stage_b_spec"]
        or protocol.get("stage_b_runner_path") != str(RUNNER)
        or protocol.get("stage_b_runner_sha256") != public_hashes["stage_b_runner"]
    ):
        raise ResearchError("CY-053 public manifest semantics drift")
    verify_role_declarations(manifest.get("bound_artifacts"), "manifest bound_artifacts")

    if suggestion.get("central_registry_modified") is not False:
        raise ResearchError("CY-053 suggestion falsely claims central installation")
    asset = suggestion.get("asset")
    auth = suggestion.get("bounded_authorization")
    if not isinstance(asset, dict) or not isinstance(auth, dict):
        raise ResearchError("CY-053 suggestion lacks exact registry objects")
    lineage = asset.get("lineage", {})
    scope = auth.get("scope", {})
    bound_manifest = auth.get("bound_manifest", {})
    bound_protocol = auth.get("bound_protocol", {})
    bound_strategy = auth.get("bound_strategy", {})
    if (
        asset.get("asset_id") != ASSET_ID
        or asset.get("status") != "RESEARCH_CONDITIONAL"
        or asset.get("pit_grade") != "B"
        or lineage.get("manifest_path") != str(STAGE_B_MANIFEST)
        or lineage.get("manifest_sha256") != public_hashes["stage_b_manifest"]
        or lineage.get("bounded_authorization_id") != AUTHORIZATION_ID
        or auth.get("authorization_id") != AUTHORIZATION_ID
        or auth.get("asset_id") != ASSET_ID
        or auth.get("purpose") != AUTHORIZATION_PURPOSE
        or auth.get("authorized_arms") != [AUTHORIZED_ARM]
        or auth.get("dependency_asset_id") != "CY-051"
        or auth.get("dependency_status") != "RESEARCH_CONDITIONAL"
        or scope.get("signal_start") != str(SIGNAL_START.date())
        or scope.get("signal_end") != str(SIGNAL_END.date())
        or scope.get("maximum_path_row_date") != str(MAX_PATH_DATE.date())
        or scope.get("frozen_candidate_rows") != EXPECTED_CANDIDATES
        or scope.get("frozen_candidate_sha256") != EXPECTED_INPUTS["stage_a_candidates"][1]
        or bound_manifest
        != {"path": str(STAGE_B_MANIFEST), "sha256": public_hashes["stage_b_manifest"]}
        or bound_protocol
        != {
            "path": str(STAGE_B_SPEC),
            "sha256": public_hashes["stage_b_spec"],
            "runner_path": str(RUNNER),
            "runner_sha256": public_hashes["stage_b_runner"],
        }
        or bound_strategy != {"path": str(STAGE_B_SPEC), "sha256": public_hashes["stage_b_spec"]}
        or auth.get("outcome_attachment_authorized") is not True
        or auth.get("stage_b_authorized") is not True
        or auth.get("whole_artifact_hash_authorized") is not True
        or auth.get("source_parquet_stage_b_parse_authorized") is not True
        or auth.get("post_signal_row_read_authorized") is not True
        or auth.get("post_2020_read_authorized") is not True
        or auth.get("2021_h1_path_completion_authorized") is not True
        or auth.get("post_2021_h1_read_authorized") is not False
        or auth.get("2022_plus_read_authorized") is not False
        or auth.get("charts_authorized") is not False
        or auth.get("portfolio_replay_authorized") is not False
        or auth.get("parameter_search_authorized") is not False
        or auth.get("candidate_reselection_authorized") is not False
        or auth.get("current_survivor_fallback_allowed") is not False
        or auth.get("record_level_available_at_available") is not False
    ):
        raise ResearchError("CY-053 registry suggestion semantics drift")
    for field in ("source", "quality_evidence", "activation_gates"):
        if field not in asset or not asset[field]:
            raise ResearchError(f"CY-053 asset misses required {field}")
    verify_role_declarations(auth.get("bound_artifacts"), "suggestion bound_artifacts")
    if auth["bound_artifacts"] != manifest["bound_artifacts"]:
        raise ResearchError("manifest/suggestion bound_artifacts differ")
    return {"hashes": public_hashes, "asset": asset, "authorization": auth}


def verify_registry_install(public: dict[str, Any]) -> None:
    """Require exact reviewed suggestion installation before any source syscall."""

    registry = load_json(REGISTRY, "central data registry")
    asset = only(
        [item for item in registry.get("assets", []) if item.get("asset_id") == ASSET_ID],
        f"central asset {ASSET_ID}",
    )
    auth = only(
        [
            item
            for item in registry.get("bounded_authorizations", [])
            if item.get("authorization_id") == AUTHORIZATION_ID
        ],
        f"central authorization {AUTHORIZATION_ID}",
    )
    if asset != public["asset"] or auth != public["authorization"]:
        raise ResearchError("central CY-053 objects do not exactly match reviewed suggestion")


def verify_source_inputs() -> tuple[dict[str, str], dict[str, Any]]:
    """This is the first function authorized to stat, hash or open source paths."""

    actual: dict[str, str] = {}
    for role, (path, expected_hash) in EXPECTED_INPUTS.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input {role}: {path}")
        value = sha256(path)
        if value != expected_hash:
            raise ResearchError(f"frozen input drift {role}: {value} != {expected_hash}")
        actual[role] = value
    stage_a = load_json(STAGE_A_RESULT, "V35 Stage-A result")
    annual = stage_a.get("gate_audit", {}).get("annual", {})
    if (
        stage_a.get("experiment") != EXPERIMENT
        or stage_a.get("status") != "PASSED_OUTCOME_BLIND_OPPORTUNITY_GATE_STAGE_B_NOT_AUTHORIZED"
        or stage_a.get("semantic_gate_passed") is not True
        or stage_a.get("opportunity_gate_passed") is not True
        or stage_a.get("stage_a_gate_passed") is not True
        or stage_a.get("outcome_columns_read") is not False
        or stage_a.get("post_signal_rows_read") is not False
        or stage_a.get("post_2020_rows_read") is not False
        or stage_a.get("candidate_rows") != EXPECTED_CANDIDATES
        or stage_a.get("candidates_sha256") != EXPECTED_INPUTS["stage_a_candidates"][1]
        or any(
            annual.get(str(year), {}).get("retained_candidates") != expected
            or annual.get(str(year), {}).get("annual_opportunity_gate_passed") is not True
            for year, expected in EXPECTED_ANNUAL.items()
        )
    ):
        raise ResearchError("V35 Stage-A result does not satisfy the frozen handoff")
    return actual, stage_a


def load_execution_reference() -> ModuleType:
    module_spec = importlib.util.spec_from_file_location(
        "v30_frozen_execution_reference", EXECUTION_REFERENCE
    )
    if module_spec is None or module_spec.loader is None:
        raise ResearchError("cannot load frozen execution reference")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    if (
        module.TARGET_RETURN != 0.10
        or module.HORIZON_SESSIONS != 20
        or module.ROUND_TRIP_COST != 0.004
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
    connection.from_parquet([str(path) for path in PARTITIONS], union_by_name=True).create_view(
        "cy006"
    )
    return connection


def parse_action_ids_strict(raw: object) -> tuple[str, ...]:
    if raw is None or raw is pd.NA or (isinstance(raw, float) and math.isnan(raw)):
        return ()
    values: list[object]
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return ()
        if text.startswith("["):
            decoded = json.loads(text)
            if not isinstance(decoded, list):
                raise ResearchError("corporate_action_ids JSON must be a list")
            values = decoded
        else:
            values = text.split("|")
    elif isinstance(raw, (list, tuple)):
        values = list(raw)
    else:
        raise ResearchError("corporate_action_ids has unsupported encoding")
    parsed = [str(value) for value in values]
    if any(not value or value != value.strip() for value in parsed):
        raise ResearchError("corporate_action_ids contains empty/padded member")
    if len(parsed) != len(set(parsed)):
        raise ResearchError("corporate_action_ids contains duplicate members")
    return tuple(sorted(parsed))


def optional_zero(value: object) -> bool:
    if value is None or value is pd.NA:
        return True
    try:
        missing = pd.isna(value)
        if isinstance(missing, (bool, np.bool_)) and bool(missing):
            return True
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(numeric) and numeric == 0.0


def prepare_candidates(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    prepared = connection.execute(
        f"""
        SELECT c.* EXCLUDE(signal_cal_idx,industry,decision_at,available_at),
          c.signal_cal_idx AS source_signal_cal_idx,
          c.industry AS causal_industry,
          c.decision_at AS candidate_decision_at,
          c.available_at AS candidate_available_at,
          CAST('BOARD_LOT_AFFORDABILITY' AS VARCHAR) AS sleeve,
          r.trade_date AS raw_signal_date,
          r.industry AS raw_industry,
          r.decision_at AS raw_decision_at,
          r.available_at AS raw_available_at,
          r.close AS raw_join_close,
          r.preclose AS raw_join_preclose,
          r.trade_status AS raw_trade_status,
          r.is_st AS raw_is_st,
          r.corporate_action_count AS raw_action_count,
          r.corporate_action_ids AS raw_action_ids,
          r.corporate_action_blocking AS raw_action_blocking,
          r.share_multiplier AS raw_share_multiplier,
          r.cash_per_share AS raw_cash_per_share,
          r.rights_ratio AS raw_rights_ratio,
          r.hard_valid AS raw_hard_valid,
          r.bar_valid AS raw_bar_valid,
          r.trading_state_valid AS raw_trading_state_valid,
          r.industry_valid AS raw_industry_valid,
          r.float_valid AS raw_float_valid,
          r.corporate_action_valid AS raw_corporate_action_valid,
          r.market_valid AS raw_market_valid,
          r.market_rule_valid AS raw_market_rule_valid,
          r.historical_identity_valid AS raw_historical_identity_valid,
          r.current_day_data_tradable AS raw_current_day_data_tradable,
          r.snapshot_id AS raw_snapshot_id,
          r.daily_snapshot_id AS raw_daily_snapshot_id,
          r.trading_state_snapshot_id AS raw_trading_state_snapshot_id,
          r.industry_snapshot_id AS raw_industry_snapshot_id,
          r.float_snapshot_id AS raw_float_snapshot_id,
          r.corporate_action_snapshot_id AS raw_corporate_action_snapshot_id,
          r.market_snapshot_id AS raw_market_snapshot_id,
          a.trade_date AS coordinate_signal_date,
          a.cal_idx AS signal_cal_idx,
          a.invalid_step_cum,
          a.current_valid AS coordinate_current_valid,
          a.corporate_action_valid AS coordinate_action_valid,
          a.corporate_action_blocking AS coordinate_action_blocking,
          a.adjusted_close/r.close AS signal_coordinate_factor
        FROM read_parquet('{CANDIDATES.as_posix()}') c
        JOIN cy006 r ON r.symbol=c.symbol AND r.trade_date=c.signal_date
        JOIN read_parquet('{COORDINATE_STATE.as_posix()}') a
          ON a.symbol=c.symbol AND a.trade_date=c.signal_date
        WHERE c.signal_date BETWEEN DATE '{SIGNAL_START.date()}' AND DATE '{SIGNAL_END.date()}'
          AND r.trade_date BETWEEN DATE '{SIGNAL_START.date()}' AND DATE '{SIGNAL_END.date()}'
        ORDER BY c.signal_date,c.industry,c.symbol,c.event_id
        """
    ).fetch_df()
    for column in (
        "signal_date",
        "raw_signal_date",
        "coordinate_signal_date",
        "candidate_decision_at",
        "candidate_available_at",
        "raw_decision_at",
        "raw_available_at",
    ):
        prepared[column] = pd.to_datetime(prepared[column], errors="coerce")

    snapshot_names = (
        "snapshot_id",
        "daily_snapshot_id",
        "trading_state_snapshot_id",
        "industry_snapshot_id",
        "float_snapshot_id",
        "corporate_action_snapshot_id",
        "market_snapshot_id",
    )
    candidate_validity = (
        "hard_valid",
        "bar_valid",
        "trading_state_valid",
        "industry_valid",
        "float_valid",
        "corporate_action_valid",
        "market_valid",
        "market_rule_valid",
        "historical_identity_valid",
        "current_day_data_tradable",
    )
    raw_validity = tuple(f"raw_{name}" for name in candidate_validity)
    required = (
        "event_id",
        "symbol",
        "signal_date",
        "source_signal_cal_idx",
        "signal_cal_idx",
        "invalid_step_cum",
        "causal_industry",
        "candidate_decision_at",
        "candidate_available_at",
        "raw_decision_at",
        "raw_available_at",
        "signal_coordinate_factor",
        "sleeve",
        *snapshot_names,
        *candidate_validity,
        *raw_validity,
    )
    missing = sorted(set(required).difference(prepared.columns))
    if missing:
        raise ResearchError(f"prepared candidate schema misses state: {missing}")

    def neutral_actions(frame: pd.DataFrame, names: tuple[str, ...]) -> pd.Series:
        ids_name, count_name, blocking_name, multiplier_name, cash_name, rights_name = names
        ids = frame[ids_name].map(parse_action_ids_strict)
        counts = pd.to_numeric(frame[count_name], errors="coerce")
        multipliers = pd.to_numeric(frame[multiplier_name], errors="coerce")
        cash = pd.to_numeric(frame[cash_name], errors="coerce")
        rights = frame[rights_name].map(optional_zero)
        blocking = frame[blocking_name]
        return (
            ids.map(len).eq(0)
            & np.isfinite(counts)
            & counts.eq(0)
            & blocking.notna()
            & blocking.eq(False).fillna(False)
            & np.isfinite(multipliers)
            & multipliers.eq(1.0)
            & np.isfinite(cash)
            & cash.eq(0.0)
            & rights
        ).fillna(False)

    candidate_neutral = neutral_actions(
        prepared,
        (
            "corporate_action_ids",
            "corporate_action_count",
            "corporate_action_blocking",
            "share_multiplier",
            "cash_per_share",
            "rights_ratio",
        ),
    )
    raw_neutral = neutral_actions(
        prepared,
        (
            "raw_action_ids",
            "raw_action_count",
            "raw_action_blocking",
            "raw_share_multiplier",
            "raw_cash_per_share",
            "raw_rights_ratio",
        ),
    )
    annual_counts = {
        int(year): int(count) for year, count in prepared.signal_date.dt.year.value_counts().items()
    }
    offsets = prepared.signal_cal_idx - prepared.source_signal_cal_idx
    snapshots = prepared[list(snapshot_names)].astype("string")
    snapshot_identity_mismatches = sum(
        int(prepared[name].astype("string").ne(prepared[f"raw_{name}"].astype("string")).sum())
        for name in snapshot_names
    )
    audit: dict[str, Any] = {
        "rows": len(prepared),
        "expected_rows": EXPECTED_CANDIDATES,
        "unique_event_ids": int(prepared.event_id.nunique()),
        "duplicate_event_ids": int(prepared.event_id.duplicated().sum()),
        "first_signal_date": str(prepared.signal_date.min().date()),
        "last_signal_date": str(prepared.signal_date.max().date()),
        "annual_counts": {str(key): value for key, value in sorted(annual_counts.items())},
        "signal_date_join_mismatches": int(
            (
                prepared.raw_signal_date.ne(prepared.signal_date)
                | prepared.coordinate_signal_date.ne(prepared.signal_date)
            ).sum()
        ),
        "coordinate_calendar_offset_unique_values": int(offsets.nunique(dropna=False)),
        "industry_identity_mismatches": int(
            prepared.raw_industry.ne(prepared.causal_industry).sum()
        ),
        "candidate_available_after_decision_rows": int(
            prepared.candidate_available_at.gt(prepared.candidate_decision_at).sum()
        ),
        "raw_available_after_decision_rows": int(
            prepared.raw_available_at.gt(prepared.raw_decision_at).sum()
        ),
        "decision_identity_mismatches": int(
            prepared.candidate_decision_at.ne(prepared.raw_decision_at).sum()
        ),
        "availability_identity_mismatches": int(
            prepared.candidate_available_at.ne(prepared.raw_available_at).sum()
        ),
        "close_identity_mismatches": int(
            pd.to_numeric(prepared.raw_close, errors="coerce")
            .ne(pd.to_numeric(prepared.raw_join_close, errors="coerce"))
            .sum()
        ),
        "preclose_identity_mismatches": int(
            pd.to_numeric(prepared.preclose, errors="coerce")
            .ne(pd.to_numeric(prepared.raw_join_preclose, errors="coerce"))
            .sum()
        ),
        "candidate_non_neutral_action_rows": int((~candidate_neutral).sum()),
        "raw_non_neutral_action_rows": int((~raw_neutral).sum()),
        "candidate_invalidity_rows": int(
            (~prepared[list(candidate_validity)].eq(True).all(axis=1)).sum()
        ),
        "raw_invalidity_rows": int((~prepared[list(raw_validity)].eq(True).all(axis=1)).sum()),
        "raw_not_normal_trading_rows": int(
            (
                pd.to_numeric(prepared.raw_trade_status, errors="coerce").ne(1)
                | prepared.raw_is_st.ne(False).fillna(True)
            ).sum()
        ),
        "coordinate_invalid_rows": int(
            (
                prepared.coordinate_current_valid.ne(True).fillna(True)
                | prepared.coordinate_action_valid.ne(True).fillna(True)
                | prepared.coordinate_action_blocking.ne(False).fillna(True)
            ).sum()
        ),
        "snapshot_identity_mismatches": int(snapshot_identity_mismatches),
        "blank_snapshot_values": int(
            (snapshots.isna() | snapshots.apply(lambda col: col.str.strip().eq("")))
            .any(axis=1)
            .sum()
        ),
        "missing_required_values": int(prepared[list(required)].isna().any(axis=1).sum()),
        "nonfinite_coordinate_rows": int(
            (
                ~np.isfinite(pd.to_numeric(prepared.invalid_step_cum, errors="coerce"))
                | ~np.isfinite(pd.to_numeric(prepared.signal_coordinate_factor, errors="coerce"))
                | pd.to_numeric(prepared.signal_coordinate_factor, errors="coerce").le(0)
            ).sum()
        ),
    }
    blocking = (
        "duplicate_event_ids",
        "signal_date_join_mismatches",
        "industry_identity_mismatches",
        "candidate_available_after_decision_rows",
        "raw_available_after_decision_rows",
        "decision_identity_mismatches",
        "availability_identity_mismatches",
        "close_identity_mismatches",
        "preclose_identity_mismatches",
        "candidate_non_neutral_action_rows",
        "raw_non_neutral_action_rows",
        "candidate_invalidity_rows",
        "raw_invalidity_rows",
        "raw_not_normal_trading_rows",
        "coordinate_invalid_rows",
        "snapshot_identity_mismatches",
        "blank_snapshot_values",
        "missing_required_values",
        "nonfinite_coordinate_rows",
    )
    if (
        audit["rows"] != EXPECTED_CANDIDATES
        or audit["unique_event_ids"] != EXPECTED_CANDIDATES
        or audit["first_signal_date"] != str(SIGNAL_START.date())
        or audit["last_signal_date"] != str(SIGNAL_END.date())
        or annual_counts != EXPECTED_ANNUAL
        or audit["coordinate_calendar_offset_unique_values"] != 1
        or any(audit[key] for key in blocking)
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
    calendar_audit = connection.execute(
        f"""
        WITH calendar_rows AS (
          SELECT trade_date,count(DISTINCT cal_idx) AS cal_indices,min(cal_idx) AS cal_idx
          FROM read_parquet('{COORDINATE_STATE.as_posix()}')
          WHERE trade_date BETWEEN DATE '{SIGNAL_START.date()}' AND DATE '{MAX_PATH_DATE.date()}'
          GROUP BY trade_date
        )
        SELECT count(*),count(*) FILTER (WHERE cal_indices<>1),max(cal_idx)
        FROM calendar_rows
        """
    ).fetchone()
    if int(calendar_audit[1]):
        raise ResearchError(f"coordinate global calendar is not unique: {calendar_audit}")
    coverage = connection.execute(
        f"""
        WITH global_calendar AS (
          SELECT trade_date,min(cal_idx) AS cal_idx
          FROM read_parquet('{COORDINATE_STATE.as_posix()}')
          WHERE trade_date BETWEEN DATE '{SIGNAL_START.date()}' AND DATE '{MAX_PATH_DATE.date()}'
          GROUP BY trade_date HAVING count(DISTINCT cal_idx)=1
        ), raw_event_path AS (
          SELECT c.event_id,c.symbol,r.trade_date,g.cal_idx,c.signal_cal_idx
          FROM candidate_keys c JOIN cy006 r USING(symbol)
          JOIN global_calendar g USING(trade_date)
          WHERE r.trade_date BETWEEN DATE '{SIGNAL_START.date()}' AND DATE '{MAX_PATH_DATE.date()}'
            AND g.cal_idx>c.signal_cal_idx AND g.cal_idx<=c.signal_cal_idx+126
        ), coordinate_path AS (
          SELECT symbol,trade_date,cal_idx
          FROM read_parquet('{COORDINATE_STATE.as_posix()}')
          WHERE trade_date BETWEEN DATE '{SIGNAL_START.date()}' AND DATE '{MAX_PATH_DATE.date()}'
        )
        SELECT count(*),
          count(*) FILTER (WHERE a.symbol IS NULL),
          count(*) FILTER (WHERE a.symbol IS NOT NULL AND a.cal_idx<>r.cal_idx),
          count(*) FILTER (WHERE r.cal_idx>r.signal_cal_idx+126)
        FROM raw_event_path r LEFT JOIN coordinate_path a USING(symbol,trade_date)
        """
    ).fetchone()
    path_audit = {
        "global_calendar_dates": int(calendar_audit[0]),
        "global_calendar_nonunique_dates": int(calendar_audit[1]),
        "authorized_cap_cal_idx": int(calendar_audit[2]),
        "candidate_event_raw_rows_within_plus126": int(coverage[0]),
        "raw_rows_missing_coordinate_state": int(coverage[1]),
        "raw_coordinate_calendar_mismatches": int(coverage[2]),
        "beyond_plus126_rows": int(coverage[3]),
    }
    if any(
        path_audit[key]
        for key in (
            "raw_rows_missing_coordinate_state",
            "raw_coordinate_calendar_mismatches",
            "beyond_plus126_rows",
        )
    ):
        raise ResearchError(f"coordinate path coverage failed: {path_audit}")
    query = f"""
      WITH global_calendar AS (
        SELECT trade_date,min(cal_idx) AS cal_idx
        FROM read_parquet('{COORDINATE_STATE.as_posix()}')
        WHERE trade_date BETWEEN DATE '{SIGNAL_START.date()}' AND DATE '{MAX_PATH_DATE.date()}'
        GROUP BY trade_date HAVING count(DISTINCT cal_idx)=1
      ), raw_event_path AS (
        SELECT c.event_id,c.symbol,c.signal_date AS event_signal_date,
          c.signal_cal_idx AS event_signal_cal_idx,g.cal_idx,r.trade_date,
          r.open,r.high,r.low,r.close,r.trade_status,
          r.current_day_data_tradable,r.market_rule_valid,
          r.corporate_action_count,r.corporate_action_valid,
          r.corporate_action_blocking,r.hard_valid,r.up_limit_price,
          r.down_limit_price,r.available_at,r.decision_at
        FROM candidate_keys c JOIN cy006 r USING(symbol)
        JOIN global_calendar g USING(trade_date)
        WHERE r.trade_date BETWEEN DATE '{SIGNAL_START.date()}' AND DATE '{MAX_PATH_DATE.date()}'
          AND g.cal_idx>c.signal_cal_idx AND g.cal_idx<=c.signal_cal_idx+126
      ), coordinate_path AS (
        SELECT * FROM read_parquet('{COORDINATE_STATE.as_posix()}')
        WHERE trade_date BETWEEN DATE '{SIGNAL_START.date()}' AND DATE '{MAX_PATH_DATE.date()}'
      )
      SELECT r.event_id,r.symbol,r.event_signal_date,r.event_signal_cal_idx,
        r.trade_date,r.cal_idx,r.open,r.high,r.low,r.close,
        r.open*a.adjusted_close/r.close AS coord_open,
        r.high*a.adjusted_close/r.close AS coord_high,
        r.low*a.adjusted_close/r.close AS coord_low,
        a.adjusted_close AS coord_close,a.invalid_step_cum,
        a.adjusted_close/r.close AS coordinate_factor,
        r.trade_status,r.current_day_data_tradable,a.current_valid,
        r.market_rule_valid,r.corporate_action_count,r.corporate_action_valid,
        r.corporate_action_blocking,r.hard_valid,r.up_limit_price,
        r.down_limit_price,r.available_at,r.decision_at
      FROM raw_event_path r JOIN coordinate_path a USING(symbol,trade_date)
      WHERE a.cal_idx=r.cal_idx AND r.close>0 AND a.adjusted_close>0
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
    path_audit["minimum_calendar_sessions_after_latest_signal"] = int(
        path_audit["authorized_cap_cal_idx"] - int(candidates.signal_cal_idx.max())
    )
    path_audit["path_rows_beyond_plus126"] = int(
        paths.cal_idx.gt(paths.event_signal_cal_idx + 126).sum()
    )
    if (
        path_audit["minimum_calendar_sessions_after_latest_signal"] < 126
        or path_audit["path_rows_beyond_plus126"]
    ):
        raise ResearchError(f"authorized path cannot satisfy exact plus-126 scope: {path_audit}")
    return paths, path_audit


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    connection = duckdb.connect()
    try:
        connection.register("frame", frame)
        connection.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
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
        "ge_4pct_rate": None if completed.empty else float(completed.net_return.ge(0.04).mean()),
        "target_hit_rate": None
        if completed.empty
        else float(completed.exit_reason.eq("TARGET_10").mean()),
        "mean_holding_sessions": None
        if completed.empty
        else float(completed.holding_sessions.mean()),
    }


def summarize(
    outcomes: pd.DataFrame,
    candidates: pd.DataFrame,
    source_hashes: dict[str, str],
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
        ids = set(cohort.event_id.astype(str))
        result = group_summary(outcomes.loc[outcomes.event_id.isin(ids)], cohort)
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
        "gate_definition": (
            "for each of 2018, 2019 and 2020: "
            "completed > 50 and mean net return > 0.04"
        ),
        "later_period_authorized": False,
        "charts_rendered": False,
        "portfolio_replay_performed": False,
        "signal_years": list(YEARS),
        "2021_signal_rows_read": False,
        "2021_rows_used_only_as_late_2020_path_buffer": True,
        "2022_plus_row_read": False,
        "maximum_path_row_date": str(MAX_PATH_DATE.date()),
        "target_return": 0.10,
        "horizon_sessions": 20,
        "round_trip_cost": 0.004,
        "next_action": "STOP_AND_REVIEW_DEVELOPMENT_GATE; NO_LATER_PERIOD_IS_AUTHORIZED",
    }


def atomic_publish_no_replace(staging: Path, target: Path) -> None:
    """Atomically rename a directory while refusing any pre-existing destination."""

    if target.exists() or target.is_symlink():
        raise ResearchError(f"canonical Stage-B target already exists: {target}")
    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(staging)
    target_bytes = os.fsencode(target)
    if sys.platform == "darwin" and hasattr(libc, "renamex_np"):
        result = libc.renamex_np(source_bytes, target_bytes, 0x00000004)  # RENAME_EXCL
    elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        result = libc.renameat2(-100, source_bytes, -100, target_bytes, 1)  # NOREPLACE
    else:
        raise ResearchError("platform lacks an audited atomic no-replace rename primitive")
    if result != 0:
        error = ctypes.get_errno()
        if error in (errno.EEXIST, errno.ENOTEMPTY):
            raise ResearchError(f"canonical Stage-B target appeared during run: {target}")
        raise OSError(error, os.strerror(error), str(target))


def run_stage_b() -> dict[str, Any]:
    # Required blind order: repository-only contract, exact central install, sources.
    public = verify_public_contract()
    verify_registry_install(public)
    source_hashes, _stage_a = verify_source_inputs()
    execution = load_execution_reference()
    if STAGE_B.exists() or STAGE_B.is_symlink():
        raise ResearchError(f"canonical V35 Stage B already exists: {STAGE_B}")
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
            raise ResearchError(f"candidate lacks any authorized future path: {path_audit}")
        outcomes = execution.attach_outcomes(candidates, paths)
        outcome_audit = execution.audit_outcomes(outcomes, candidates)
        write_parquet(outcomes, outcomes_path)
        result = summarize(
            outcomes,
            candidates,
            source_hashes,
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
        second_public = verify_public_contract()
        verify_registry_install(second_public)
        if second_public["hashes"] != public["hashes"]:
            raise ResearchError("public CY-053 contract changed during run")
        if verify_source_inputs()[0] != source_hashes:
            raise ResearchError("bound CY-053 input changed during run")
        atomic_publish_no_replace(staging, STAGE_B)
        return result
    except Exception:
        if connection is not None:
            connection.close()
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--verify-public-contract",
        action="store_true",
        help="verify only repository-side declarations; never stat/hash/open a source",
    )
    mode.add_argument(
        "--run",
        action="store_true",
        help="run only after exact CY-053 central registry installation",
    )
    args = parser.parse_args()
    if args.verify_public_contract:
        public = verify_public_contract()
        print(
            json.dumps(
                {
                    "status": "PUBLIC_CONTRACT_VALID_SOURCE_UNTOUCHED",
                    "asset_id": ASSET_ID,
                    **public["hashes"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    print(json.dumps(run_stage_b(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
