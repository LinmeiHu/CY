#!/usr/bin/env python3
"""Attach the one frozen V34R1 development lifecycle after CY-049 authorization."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any

import duckdb
import numpy as np
import pandas as pd

EXPERIMENT = "ASHARE-CASH-DISTRIBUTION-REALIZED-PAYOUT-QUALITY-MOTHER-V34R1"
REPO = Path(__file__).resolve().parents[3]
PARENT_SPEC = REPO / (
    "research/market_behavior_os_v2/experiments/"
    f"{EXPERIMENT}_freeze.json"
)
STAGE_B_SPEC = REPO / (
    "research/market_behavior_os_v2/experiments/"
    f"{EXPERIMENT}_stage_b_freeze.json"
)
STAGE_A_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    f"run_{EXPERIMENT.lower().replace('-', '_')}_stage_a.py"
)
STAGE_A_MANIFEST = REPO / (
    "research/market_behavior_os_v2/experiments/"
    "ASHARE-V34R1-CY047_DATA_ASSET_MANIFEST.json"
)
STAGE_B_MANIFEST = REPO / (
    "research/market_behavior_os_v2/experiments/"
    "ASHARE-V34R1-CY049_DATA_ASSET_MANIFEST.json"
)
EXECUTION_REFERENCE = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_low_positive_feedback_good_news_mother_v30_stage_b.py"
)
COORDINATE_BUILDER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_former_leader_strict_gap_reclaim_v3.py"
)
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
    "/Volumes/quant/CY_quant_research/"
    "ashare_cash_distribution_realized_payout_quality_mother_v34r1"
)
STAGE_A = OUTPUT_ROOT / "stage_a"
STAGE_A_RESULT = STAGE_A / "result.json"
REPRESENTATION = STAGE_A / "representation_panel.parquet"
CANDIDATES = STAGE_A / "candidates_frozen.parquet"
STAGE_B = OUTPUT_ROOT / "stage_b"

ASSET_ID = "CY-049"
AUTHORIZATION_ID = (
    "CYQ-AUTH-ASHARE-CASH-DISTRIBUTION-PAYOUT-QUALITY-"
    "V34R1-STAGE-B-2018-2021H1-V1"
)
AUTHORIZATION_PURPOSE = "ASHARE_FROZEN_DEVELOPMENT_OUTCOME_ATTACHMENT"
AUTHORIZED_ARM = "V34R1_FROZEN_STAGE_B_OUTCOME_ATTACHMENT_ONLY"
MANIFEST_STATUS = "FROZEN_DEVELOPMENT_OUTCOME_BOUNDED_INPUT"
SIGNAL_START = pd.Timestamp("2018-03-27")
SIGNAL_END = pd.Timestamp("2020-12-01")
MAX_PATH_DATE = pd.Timestamp("2021-06-30")
EXPECTED_CANDIDATES = 1_483
YEARS = (2018, 2019, 2020)
EXPECTED_ANNUAL = {2018: 395, 2019: 520, 2020: 568}

EXPECTED_INPUTS: dict[str, tuple[Path, str]] = {
    "parent_spec": (
        PARENT_SPEC,
        "e41bfe9de6c68878ea556cf31397075adda9076adc19a4089215284436c6bdb4",
    ),
    "stage_b_spec": (
        STAGE_B_SPEC,
        "94def5859b602bde8a635d2e4079c9aea4c1c27bee4161843259ac9dfb928041",
    ),
    "stage_a_runner": (
        STAGE_A_RUNNER,
        "deb4856ab9cf21cb117428db3e54f45cc0422cf5eef5ca8eebcb2e12357167d1",
    ),
    "stage_a_manifest": (
        STAGE_A_MANIFEST,
        "4f3453d0afadf14e71fe332c7d84e49c0842253b152849281a6dfc40f3a5655f",
    ),
    "stage_a_result": (
        STAGE_A_RESULT,
        "ed8beec7bebe604a0aed9904f96b48580e5020f3709ca06dab95e7e7642dff58",
    ),
    "stage_a_representation": (
        REPRESENTATION,
        "d46729a8fc90321b7cc1d0a2572f17f9944808ccdd6bdc1145c08ed51a950fb6",
    ),
    "stage_a_candidates": (
        CANDIDATES,
        "44c55eefc7148aa530a79e71cc5569003c76e9598a2ac85193d8d5db102fbcd8",
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
        raise ResearchError(f"expected one {label}, found {len(items)}")
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


def verify_public_envelope() -> dict[str, str]:
    for path in (STAGE_B_SPEC, STAGE_B_MANIFEST, REGISTRY, Path(__file__).resolve()):
        if not path.is_file():
            raise ResearchError(f"missing public authorization artifact: {path}")
    actual = {
        "stage_b_spec": sha256(STAGE_B_SPEC),
        "stage_b_manifest": sha256(STAGE_B_MANIFEST),
        "stage_b_runner": sha256(Path(__file__).resolve()),
    }
    if actual["stage_b_spec"] != EXPECTED_INPUTS["stage_b_spec"][1]:
        raise ResearchError("Stage-B spec drift before authorization")
    registry = load_json(REGISTRY, "data registry")
    asset = only(
        [item for item in registry.get("assets", []) if item.get("asset_id") == ASSET_ID],
        f"asset {ASSET_ID}",
    )
    auth = only(
        [
            item
            for item in registry.get("bounded_authorizations", [])
            if item.get("authorization_id") == AUTHORIZATION_ID
        ],
        f"authorization {AUTHORIZATION_ID}",
    )
    lineage = asset.get("lineage", {})
    scope = auth.get("scope", {})
    bound_manifest = auth.get("bound_manifest", {})
    protocol = auth.get("bound_protocol", {})
    if (
        asset.get("status") != "RESEARCH_CONDITIONAL"
        or asset.get("pit_grade") != "B"
        or lineage.get("manifest_path") != str(STAGE_B_MANIFEST.resolve())
        or lineage.get("manifest_sha256") != actual["stage_b_manifest"]
        or lineage.get("bounded_authorization_id") != AUTHORIZATION_ID
        or auth.get("purpose") != AUTHORIZATION_PURPOSE
        or auth.get("asset_id") != ASSET_ID
        or auth.get("dependency_asset_id") != "CY-006"
        or auth.get("authorized_arms") != [AUTHORIZED_ARM]
        or auth.get("outcome_attachment_authorized") is not True
        or auth.get("charts_authorized") is not False
        or auth.get("portfolio_replay_authorized") is not False
        or auth.get("candidate_reselection_authorized") is not False
        or auth.get("post_2020_read_authorized") is not True
        or auth.get("post_2021_h1_read_authorized") is not False
        or auth.get("2022_plus_read_authorized") is not False
        or auth.get("current_survivor_fallback_allowed") is not False
        or scope.get("signal_start") != str(SIGNAL_START.date())
        or scope.get("signal_end") != str(SIGNAL_END.date())
        or scope.get("maximum_path_row_date") != str(MAX_PATH_DATE.date())
        or scope.get("frozen_candidate_rows") != EXPECTED_CANDIDATES
        or scope.get("frozen_candidate_sha256")
        != EXPECTED_INPUTS["stage_a_candidates"][1]
        or bound_manifest.get("path") != str(STAGE_B_MANIFEST.resolve())
        or bound_manifest.get("sha256") != actual["stage_b_manifest"]
        or protocol.get("path") != str(STAGE_B_SPEC.resolve())
        or protocol.get("sha256") != actual["stage_b_spec"]
        or protocol.get("runner_path") != str(Path(__file__).resolve())
        or protocol.get("runner_sha256") != actual["stage_b_runner"]
    ):
        raise ResearchError("CY-049 public registry authorization semantics drift")

    manifest = load_json(STAGE_B_MANIFEST, "CY-049 manifest")
    boundary = manifest.get("authorization_boundary", {})
    manifest_protocol = manifest.get("protocol", {})
    if (
        manifest.get("asset_id") != ASSET_ID
        or manifest.get("status") != MANIFEST_STATUS
        or boundary.get("authorization_id") != AUTHORIZATION_ID
        or boundary.get("purpose") != AUTHORIZATION_PURPOSE
        or boundary.get("authorized_arm") != AUTHORIZED_ARM
        or boundary.get("signal_start") != str(SIGNAL_START.date())
        or boundary.get("signal_end") != str(SIGNAL_END.date())
        or boundary.get("maximum_path_row_date") != str(MAX_PATH_DATE.date())
        or boundary.get("outcome_attachment_authorized") is not True
        or boundary.get("charts_authorized") is not False
        or boundary.get("portfolio_replay_authorized") is not False
        or boundary.get("candidate_reselection_authorized") is not False
        or boundary.get("post_2021_h1_read_authorized") is not False
        or boundary.get("2022_plus_read_authorized") is not False
        or boundary.get("current_survivor_fallback_allowed") is not False
        or manifest_protocol.get("stage_b_spec_path") != str(STAGE_B_SPEC.resolve())
        or manifest_protocol.get("stage_b_spec_sha256") != actual["stage_b_spec"]
        or manifest_protocol.get("stage_b_runner_path")
        != str(Path(__file__).resolve())
        or manifest_protocol.get("stage_b_runner_sha256") != actual["stage_b_runner"]
    ):
        raise ResearchError("CY-049 public manifest semantics drift")
    return actual


def verify_inputs() -> tuple[dict[str, str], dict[str, Any]]:
    public = verify_public_envelope()
    actual = dict(public)
    for role, (path, expected) in EXPECTED_INPUTS.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input {role}: {path}")
        value = sha256(path)
        if value != expected:
            raise ResearchError(f"frozen input drift {role}: {value} != {expected}")
        actual[role] = value

    registry = load_json(REGISTRY, "data registry")
    auth = only(
        [
            item
            for item in registry.get("bounded_authorizations", [])
            if item.get("authorization_id") == AUTHORIZATION_ID
        ],
        f"authorization {AUTHORIZATION_ID}",
    )
    registry_roles = role_map(auth.get("bound_artifacts"), "registry bound_artifacts")
    manifest = load_json(STAGE_B_MANIFEST, "CY-049 manifest")
    manifest_roles = role_map(manifest.get("bound_artifacts"), "manifest bound_artifacts")
    if set(registry_roles) != set(EXPECTED_INPUTS) or set(manifest_roles) != set(
        EXPECTED_INPUTS
    ):
        raise ResearchError("CY-049 bound-artifact role set drift")
    for role, (path, expected) in EXPECTED_INPUTS.items():
        for label, mapped in (
            ("registry", registry_roles),
            ("manifest", manifest_roles),
        ):
            item = mapped[role]
            if item.get("path") != str(path.resolve()) or item.get("sha256") != expected:
                raise ResearchError(f"CY-049 {label} binding drift for {role}")

    stage_a = load_json(STAGE_A_RESULT, "V34R1 Stage-A result")
    annual = stage_a.get("annual", {})
    if (
        stage_a.get("experiment") != EXPERIMENT
        or stage_a.get("status")
        != "PASSED_OUTCOME_BLIND_OPPORTUNITY_GATE_STAGE_B_NOT_AUTHORIZED"
        or stage_a.get("semantic_gate_passed") is not True
        or stage_a.get("opportunity_gate_passed") is not True
        or stage_a.get("stage_a_gate_passed") is not True
        or stage_a.get("outcome_columns_read") is not False
        or stage_a.get("post_signal_rows_read") is not False
        or stage_a.get("post_2020_rows_read") is not False
        or stage_a.get("candidate_rows") != EXPECTED_CANDIDATES
        or stage_a.get("candidates_sha256") != EXPECTED_INPUTS["stage_a_candidates"][1]
        or stage_a.get("representation_sha256")
        != EXPECTED_INPUTS["stage_a_representation"][1]
        or stage_a.get("semantic_correction", {}).get("outcome_informed") is not False
        or stage_a.get("semantic_correction", {}).get(
            "threshold_direction_universe_or_timing_changed"
        )
        is not False
        or any(
            annual.get(str(year), {}).get("retained_candidates") != expected
            or annual.get(str(year), {}).get("annual_opportunity_gate_passed") is not True
            for year, expected in EXPECTED_ANNUAL.items()
        )
    ):
        raise ResearchError("V34R1 Stage-A result does not authorize Stage B")
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
    connection.from_parquet(
        [str(path) for path in PARTITIONS], union_by_name=True
    ).create_view("cy006")
    return connection


def prepare_candidates(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    prepared = connection.execute(
        f"""
        SELECT c.mother_event_id AS event_id,
          c.* EXCLUDE(mother_event_id,cal_idx,industry,decision_at),
          c.cal_idx AS source_signal_cal_idx,c.industry AS causal_industry,
          c.decision_at,CAST('CASH_DISTRIBUTION' AS VARCHAR) AS sleeve,
          a.cal_idx AS signal_cal_idx,
          a.invalid_step_cum,r.trade_date AS execution_raw_signal_date,
          a.trade_date AS coordinate_signal_date,r.industry AS execution_raw_industry,
          r.available_at AS signal_row_available_at,
          r.decision_at AS signal_row_decision_at,
          r.corporate_action_count AS signal_corporate_action_count,
          a.adjusted_close/r.close AS signal_coordinate_factor
        FROM read_parquet('{CANDIDATES.as_posix()}') c
        JOIN cy006 r ON r.symbol=c.symbol AND r.trade_date=c.signal_date
        JOIN read_parquet('{COORDINATE_STATE.as_posix()}') a
          ON a.symbol=c.symbol AND a.trade_date=c.signal_date
        WHERE c.signal_date BETWEEN DATE '{SIGNAL_START.date()}' AND DATE '{SIGNAL_END.date()}'
          AND r.trade_date BETWEEN DATE '{SIGNAL_START.date()}' AND DATE '{SIGNAL_END.date()}'
          AND r.hard_valid AND r.bar_valid AND r.trading_state_valid
          AND r.corporate_action_valid AND NOT r.corporate_action_blocking
          AND r.market_rule_valid AND r.historical_identity_valid
          AND r.current_day_data_tradable AND r.available_at<=r.decision_at
          AND a.current_valid AND a.corporate_action_valid
          AND NOT a.corporate_action_blocking AND a.adjusted_close>0
          AND r.close>0 AND isfinite(a.adjusted_close/r.close)
          AND r.corporate_action_count=1
          AND c.event_action_identity_exact_match
          AND r.industry=c.industry
        ORDER BY c.signal_date,c.industry,c.symbol,c.mother_event_id
        """
    ).fetch_df()
    for column in (
        "signal_date",
        "execution_raw_signal_date",
        "coordinate_signal_date",
        "decision_at",
        "known_at",
        "signal_row_available_at",
        "signal_row_decision_at",
    ):
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
        "known_at",
        "signal_row_available_at",
        "signal_row_decision_at",
        "signal_corporate_action_count",
        "cash_per_share_gross",
        "preclose",
        "cash_yield",
        "event_action_identity_exact_match",
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
    numeric = prepared[
        [
            "invalid_step_cum",
            "signal_coordinate_factor",
            "cash_per_share_gross",
            "preclose",
            "signal_corporate_action_count",
        ]
    ].apply(pd.to_numeric, errors="coerce")
    snapshots = prepared[
        [
            "snapshot_id",
            "daily_snapshot_id",
            "trading_state_snapshot_id",
            "industry_snapshot_id",
            "float_snapshot_id",
            "corporate_action_snapshot_id",
            "market_snapshot_id",
        ]
    ].astype("string")
    annual_counts = {
        int(year): int(count)
        for year, count in prepared.signal_date.dt.year.value_counts().items()
    }
    coordinate_offsets = prepared.signal_cal_idx - prepared.source_signal_cal_idx
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
                prepared.execution_raw_signal_date.ne(prepared.signal_date)
                | prepared.coordinate_signal_date.ne(prepared.signal_date)
            ).sum()
        ),
        "coordinate_calendar_offset_unique_values": int(
            coordinate_offsets.nunique(dropna=False)
        ),
        "industry_identity_mismatches": int(
            prepared.execution_raw_industry.ne(prepared.causal_industry).sum()
        ),
        "event_known_after_decision_rows": int(
            prepared.known_at.gt(prepared.decision_at).sum()
        ),
        "signal_row_available_after_decision_rows": int(
            prepared.signal_row_available_at.gt(prepared.signal_row_decision_at).sum()
        ),
        "signal_decision_identity_mismatches": int(
            prepared.decision_at.ne(prepared.signal_row_decision_at).sum()
        ),
        "signal_action_count_not_one_rows": int(
            prepared.signal_corporate_action_count.ne(1).sum()
        ),
        "missing_required_values": int(prepared[list(required)].isna().any(axis=1).sum()),
        "blank_snapshot_values": int(
            (snapshots.isna() | snapshots.apply(lambda col: col.str.strip().eq("")))
            .any(axis=1)
            .sum()
        ),
        "nonfinite_numeric_values": int((~np.isfinite(numeric.to_numpy(float))).any(axis=1).sum()),
        "invalid_cash_yield_rows": int(
            (
                ~np.isfinite(pd.to_numeric(prepared.cash_yield, errors="coerce"))
                | prepared.cash_yield.lt(0.02)
            ).sum()
        ),
        "nonexact_action_identity_rows": int(
            (~prepared.event_action_identity_exact_match.astype(bool)).sum()
        ),
    }
    blocking = (
        "duplicate_event_ids",
        "signal_date_join_mismatches",
        "industry_identity_mismatches",
        "event_known_after_decision_rows",
        "signal_row_available_after_decision_rows",
        "signal_decision_identity_mismatches",
        "signal_action_count_not_one_rows",
        "missing_required_values",
        "blank_snapshot_values",
        "nonfinite_numeric_values",
        "invalid_cash_yield_rows",
        "nonexact_action_identity_rows",
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
          SELECT trade_date,count(DISTINCT cal_idx) AS cal_indices,
            min(cal_idx) AS cal_idx
          FROM read_parquet('{COORDINATE_STATE.as_posix()}')
          WHERE trade_date BETWEEN DATE '{SIGNAL_START.date()}'
            AND DATE '{MAX_PATH_DATE.date()}'
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
          WHERE trade_date BETWEEN DATE '{SIGNAL_START.date()}'
            AND DATE '{MAX_PATH_DATE.date()}'
          GROUP BY trade_date
          HAVING count(DISTINCT cal_idx)=1
        ), raw_event_path AS (
          SELECT c.event_id,c.symbol,r.trade_date,g.cal_idx
          FROM candidate_keys c JOIN cy006 r USING(symbol)
          JOIN global_calendar g USING(trade_date)
          WHERE r.trade_date BETWEEN DATE '{SIGNAL_START.date()}'
            AND DATE '{MAX_PATH_DATE.date()}'
            AND g.cal_idx>c.signal_cal_idx AND g.cal_idx<=c.signal_cal_idx+126
        ), coordinate_path AS (
          SELECT a.symbol,a.trade_date,a.cal_idx
          FROM read_parquet('{COORDINATE_STATE.as_posix()}') a
          WHERE a.trade_date BETWEEN DATE '{SIGNAL_START.date()}'
            AND DATE '{MAX_PATH_DATE.date()}'
        )
        SELECT count(*),count(*) FILTER (WHERE a.symbol IS NULL),
          count(*) FILTER (WHERE a.cal_idx<>r.cal_idx)
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
    }
    if (
        path_audit["raw_rows_missing_coordinate_state"]
        or path_audit["raw_coordinate_calendar_mismatches"]
    ):
        raise ResearchError(f"coordinate path coverage failed: {path_audit}")
    query = f"""
      WITH global_calendar AS (
        SELECT trade_date,min(cal_idx) AS cal_idx
        FROM read_parquet('{COORDINATE_STATE.as_posix()}')
        WHERE trade_date BETWEEN DATE '{SIGNAL_START.date()}'
          AND DATE '{MAX_PATH_DATE.date()}'
        GROUP BY trade_date
        HAVING count(DISTINCT cal_idx)=1
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
        WHERE r.trade_date BETWEEN DATE '{SIGNAL_START.date()}'
          AND DATE '{MAX_PATH_DATE.date()}'
          AND g.cal_idx>c.signal_cal_idx AND g.cal_idx<=c.signal_cal_idx+126
      ), coordinate_path AS (
        SELECT a.* FROM read_parquet('{COORDINATE_STATE.as_posix()}') a
        WHERE a.trade_date BETWEEN DATE '{SIGNAL_START.date()}'
          AND DATE '{MAX_PATH_DATE.date()}'
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
    path_audit["minimum_calendar_sessions_after_signal"] = int(
        path_audit["authorized_cap_cal_idx"] - int(candidates.signal_cal_idx.max())
    )
    if path_audit["minimum_calendar_sessions_after_signal"] < 126:
        raise ResearchError(f"authorized path cap cannot complete plus-126: {path_audit}")
    connection.unregister("candidate_keys")
    for column in ("event_signal_date", "trade_date", "available_at", "decision_at"):
        paths[column] = pd.to_datetime(paths[column])
    return paths, path_audit


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    connection = duckdb.connect()
    connection.register("frame", frame)
    connection.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
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
        "severe10_rate": None if completed.empty else float(completed.net_return.le(-0.10).mean()),
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
        "later_period_authorized": False,
        "charts_rendered": False,
        "portfolio_replay_performed": False,
        "2021_signal_rows_read": False,
        "2021_rows_used_only_as_late_2020_path_buffer": True,
        "2022_plus_row_read": False,
        "maximum_path_row_date": str(MAX_PATH_DATE.date()),
        "target_return": 0.10,
        "horizon_sessions": 20,
        "round_trip_cost": 0.004,
        "next_action": "FREEZE_AND_RENDER_EVERY_DEVELOPMENT_CHART_BEFORE_ANY_RULE_OR_LATER_PERIOD",
    }


def main() -> None:
    source_hashes, _stage_a = verify_inputs()
    execution = load_execution_reference()
    if STAGE_B.exists() or STAGE_B.is_symlink():
        raise ResearchError(f"canonical V34R1 Stage B already exists: {STAGE_B}")
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
        if verify_inputs()[0] != source_hashes:
            raise ResearchError("bound input changed during V34R1 Stage B")
        if STAGE_B.exists() or STAGE_B.is_symlink():
            raise ResearchError("canonical Stage-B target appeared during run")
        staging.replace(STAGE_B)
    except Exception:
        if connection is not None:
            connection.close()
        shutil.rmtree(staging, ignore_errors=True)
        raise
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
