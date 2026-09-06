#!/usr/bin/env python3
"""Attach the one frozen V32 development lifecycle after CY-042 authorization."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

EXPERIMENT = "ASHARE-STOCK-INDUSTRY-TURNOVER-INNOVATION-DECOUPLING-MOTHER-V32"
REPO = Path(__file__).resolve().parents[3]
PARENT_SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
STAGE_B_SPEC = REPO / (
    f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_stage_b_freeze.json"
)
STAGE_A_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_stock_industry_turnover_innovation_decoupling_mother_v32_stage_a.py"
)
EXECUTION_REFERENCE = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_low_positive_feedback_good_news_mother_v30_stage_b.py"
)
ASSET_MANIFEST = REPO / (
    "research/market_behavior_os_v2/experiments/ASHARE-V32-CY042_DATA_ASSET_MANIFEST.json"
)
REGISTRY = REPO / "configs/data_asset_registry.json"
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
COORDINATE_BUILDER = REPO / (
    "research/market_behavior_os_v2/scripts/run_ashare_former_leader_strict_gap_reclaim_v3.py"
)
OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_stock_industry_turnover_innovation_decoupling_mother_v32"
)
STAGE_A = OUTPUT_ROOT / "stage_a"
STAGE_A_RESULT = STAGE_A / "result.json"
REPRESENTATION = STAGE_A / "representation_panel.parquet"
CANDIDATES = STAGE_A / "candidates_frozen.parquet"
STAGE_B = OUTPUT_ROOT / "stage_b"

ASSET_ID = "CY-042"
AUTHORIZATION_ID = "CYQ-AUTH-ASHARE-TURNOVER-INNOVATION-DECOUPLING-V32-STAGE-B-2018-2020-V1"
AUTHORIZED_ARM = "V32_FROZEN_STAGE_B_OUTCOME_ATTACHMENT_ONLY"
EXPECTED = {
    PARENT_SPEC: "d389cda8f743441a4c46df61a2c044169f33550d05a5153bb96bea5abab75089",
    STAGE_B_SPEC: "23103c3910a83416da52ec149135731a2589782bd539967cab630e39ee041d9b",
    STAGE_A_RUNNER: "a892ce53141c835ee6573427d97d12629ebffbaa869b5a5b789d5f33c6292054",
    EXECUTION_REFERENCE: "1774512c6811fdd0b7c3ea24234254327378faa078f5ecc9fd9078c86d996997",
    STAGE_A_RESULT: "db6dd269340e7bed1153ca160492b91f6aaedd0b44aee853e447a8f8aa4c96f4",
    REPRESENTATION: "1a67e4dfcd4cc6e20000be3890d12e37f8a91da5afa47aaf8b84960d2bf7c13d",
    CANDIDATES: "4d57fafc3418bc7923e747910add5f503313582e0b0ef9d5e8bdb4a92dcf539d",
    CY006_MANIFEST: "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2",
    PARTITIONS[0]: "b906d2c21fd35128b8f65f1b00fa12ae6e5bd9ee476a368a63881304f38ceed4",
    PARTITIONS[1]: "c69a464e4a04efdca0177a8a09a13a34646531afa37a2b35b4892fd40ec3ebfd",
    PARTITIONS[2]: "1b0a00c6d2cfbce0ae4f907e1ee9dc5006f59677d556cc10f8f34a9893937c62",
    COORDINATE_STATE: "76fe88cb7509ae33a3d32b1bfd6d0c90560083127bdfaf63da1d7d24ec72bf60",
    COORDINATE_BUILDER: "358b62014c52b7bf936937746223954512fe9451eaa5009063e14f39e1bb1787",
}
SIGNAL_START = pd.Timestamp("2018-07-31")
SIGNAL_END = pd.Timestamp("2020-06-30")
MAX_PATH_DATE = pd.Timestamp("2020-12-31")
EXPECTED_CANDIDATES = 1_781
YEARS = (2018, 2019, 2020)


class ResearchError(RuntimeError):
    """Fail closed on authorization, identity, chronology, or execution drift."""


def load_execution_reference() -> Any:
    module_spec = importlib.util.spec_from_file_location(
        "v30_execution_reference", EXECUTION_REFERENCE
    )
    if module_spec is None or module_spec.loader is None:
        raise ResearchError("cannot load frozen execution reference")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    if (
        module.TARGET_RETURN != 0.10
        or module.HORIZON_SESSIONS != 20
        or module.ROUND_TRIP_COST != 0.004
        or module.MAX_PATH_DATE != MAX_PATH_DATE
    ):
        raise ResearchError("frozen execution-reference constants drift")
    return module


EXECUTION = load_execution_reference()


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


def verify_registry_and_manifest(actual: dict[str, str]) -> None:
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
        or lineage.get("manifest_path") != str(ASSET_MANIFEST.resolve())
        or lineage.get("manifest_sha256") != actual["asset_manifest"]
        or lineage.get("bounded_authorization_id") != AUTHORIZATION_ID
        or authorization.get("purpose") != "ASHARE_FROZEN_DEVELOPMENT_OUTCOME_ATTACHMENT"
        or authorization.get("asset_id") != ASSET_ID
        or authorization.get("dependency_asset_id") != "CY-006"
        or authorization.get("authorized_arms") != [AUTHORIZED_ARM]
        or authorization.get("outcome_attachment_authorized") is not True
        or authorization.get("charts_authorized") is not False
        or authorization.get("portfolio_replay_authorized") is not False
        or authorization.get("post_2020_read_authorized") is not False
        or bound_manifest.get("path") != str(ASSET_MANIFEST.resolve())
        or bound_manifest.get("sha256") != actual["asset_manifest"]
        or scope.get("signal_start") != str(SIGNAL_START.date())
        or scope.get("signal_end") != str(SIGNAL_END.date())
        or scope.get("maximum_path_row_date") != str(MAX_PATH_DATE.date())
        or scope.get("frozen_candidate_rows") != EXPECTED_CANDIDATES
        or scope.get("frozen_candidate_sha256") != EXPECTED[CANDIDATES]
        or protocol.get("path") != str(STAGE_B_SPEC.resolve())
        or protocol.get("sha256") != actual["stage_b_spec"]
        or protocol.get("runner_path") != str(Path(__file__).resolve())
        or protocol.get("runner_sha256") != actual["stage_b_runner"]
    ):
        raise ResearchError("CY-042 registry authorization semantics drift")

    artifacts = {
        item.get("role"): item
        for item in authorization.get("bound_artifacts", [])
        if isinstance(item, dict)
    }
    required = (
        ("cy006_manifest", CY006_MANIFEST, "cy006_manifest"),
        ("cy006_2018", PARTITIONS[0], "partition_2018"),
        ("cy006_2019", PARTITIONS[1], "partition_2019"),
        ("cy006_2020", PARTITIONS[2], "partition_2020"),
        ("coordinate_state", COORDINATE_STATE, "coordinate_state"),
        ("coordinate_builder", COORDINATE_BUILDER, "coordinate_builder"),
        ("parent_spec", PARENT_SPEC, "parent_spec"),
        ("stage_a_runner", STAGE_A_RUNNER, "stage_a_runner"),
        ("stage_a_result", STAGE_A_RESULT, "stage_a_result"),
        ("stage_a_representation", REPRESENTATION, "representation"),
        ("stage_a_candidates", CANDIDATES, "candidates"),
        ("execution_reference", EXECUTION_REFERENCE, "execution_reference"),
    )
    for role, path, key in required:
        item = artifacts.get(role)
        if (
            item is None
            or item.get("path") != str(path.resolve())
            or item.get("sha256") != actual[key]
        ):
            raise ResearchError(f"CY-042 authorization does not bind {role}")

    manifest = load_json(ASSET_MANIFEST, "CY-042 manifest")
    boundary = manifest.get("authorization_boundary", {})
    cohort = manifest.get("frozen_cohort", {})
    manifest_protocol = manifest.get("protocol", {})
    coordinate = manifest.get("coordinate_state", {})
    if (
        manifest.get("asset_id") != ASSET_ID
        or manifest.get("status") != "FROZEN_DEVELOPMENT_OUTCOME_BOUNDED_INPUT"
        or manifest.get("raw_daily", {}).get("manifest_sha256") != actual["cy006_manifest"]
        or coordinate.get("path") != str(COORDINATE_STATE.resolve())
        or coordinate.get("sha256") != actual["coordinate_state"]
        or coordinate.get("builder_path") != str(COORDINATE_BUILDER.resolve())
        or coordinate.get("builder_sha256") != actual["coordinate_builder"]
        or cohort.get("candidates", {}).get("sha256") != actual["candidates"]
        or cohort.get("candidates", {}).get("rows") != EXPECTED_CANDIDATES
        or cohort.get("candidates", {}).get("unique_event_ids") != EXPECTED_CANDIDATES
        or cohort.get("candidates", {}).get("signal_start") != str(SIGNAL_START.date())
        or cohort.get("candidates", {}).get("signal_end") != str(SIGNAL_END.date())
        or boundary.get("authorization_id") != AUTHORIZATION_ID
        or boundary.get("purpose") != "ASHARE_FROZEN_DEVELOPMENT_OUTCOME_ATTACHMENT"
        or boundary.get("authorized_arm") != AUTHORIZED_ARM
        or boundary.get("candidate_signal_start") != str(SIGNAL_START.date())
        or boundary.get("candidate_signal_end") != str(SIGNAL_END.date())
        or boundary.get("maximum_path_row_date") != str(MAX_PATH_DATE.date())
        or boundary.get("outcome_attachment_authorized") is not True
        or boundary.get("charts_authorized") is not False
        or boundary.get("portfolio_replay_authorized") is not False
        or boundary.get("2021_read_authorized") is not False
        or boundary.get("2022_plus_read_authorized") is not False
        or manifest_protocol.get("stage_b_spec_path") != str(STAGE_B_SPEC.resolve())
        or manifest_protocol.get("stage_b_spec_sha256") != actual["stage_b_spec"]
        or manifest_protocol.get("stage_b_runner_path") != str(Path(__file__).resolve())
        or manifest_protocol.get("stage_b_runner_sha256") != actual["stage_b_runner"]
        or manifest_protocol.get("execution_reference_path")
        != str(EXECUTION_REFERENCE.resolve())
        or manifest_protocol.get("execution_reference_sha256")
        != actual["execution_reference"]
    ):
        raise ResearchError("CY-042 manifest semantics drift")

    cohort_items = (
        ("parent_spec", PARENT_SPEC, "parent_spec"),
        ("stage_a_runner", STAGE_A_RUNNER, "stage_a_runner"),
        ("stage_a_result", STAGE_A_RESULT, "stage_a_result"),
        ("representation", REPRESENTATION, "representation"),
        ("candidates", CANDIDATES, "candidates"),
    )
    for name, path, key in cohort_items:
        item = cohort.get(name, {})
        if item.get("path") != str(path.resolve()) or item.get("sha256") != actual[key]:
            raise ResearchError(f"CY-042 manifest does not bind frozen cohort {name}")

    partition_records = {
        int(item.get("year")): item
        for item in manifest.get("raw_daily", {}).get("partitions", [])
        if isinstance(item, dict) and item.get("year") is not None
    }
    for year, path, key in (
        (2018, PARTITIONS[0], "partition_2018"),
        (2019, PARTITIONS[1], "partition_2019"),
        (2020, PARTITIONS[2], "partition_2020"),
    ):
        item = partition_records.get(year, {})
        if item.get("path") != str(path.resolve()) or item.get("sha256") != actual[key]:
            raise ResearchError(f"CY-042 manifest does not bind CY-006 {year}")


def verify_inputs() -> tuple[dict[str, str], dict[str, Any]]:
    actual: dict[str, str] = {}
    for path, expected in EXPECTED.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input: {path}")
        value = sha256(path)
        actual[str(path)] = value
        if value != expected:
            raise ResearchError(f"frozen input drift: {path}: {value} != {expected}")
    if not ASSET_MANIFEST.is_file():
        raise ResearchError(f"missing CY-042 manifest: {ASSET_MANIFEST}")
    actual["asset_manifest"] = sha256(ASSET_MANIFEST)
    actual["stage_b_runner"] = sha256(Path(__file__).resolve())
    actual.update(
        {
            "parent_spec": actual[str(PARENT_SPEC)],
            "stage_b_spec": actual[str(STAGE_B_SPEC)],
            "stage_a_runner": actual[str(STAGE_A_RUNNER)],
            "execution_reference": actual[str(EXECUTION_REFERENCE)],
            "stage_a_result": actual[str(STAGE_A_RESULT)],
            "representation": actual[str(REPRESENTATION)],
            "candidates": actual[str(CANDIDATES)],
            "cy006_manifest": actual[str(CY006_MANIFEST)],
            "partition_2018": actual[str(PARTITIONS[0])],
            "partition_2019": actual[str(PARTITIONS[1])],
            "partition_2020": actual[str(PARTITIONS[2])],
            "coordinate_state": actual[str(COORDINATE_STATE)],
            "coordinate_builder": actual[str(COORDINATE_BUILDER)],
        }
    )
    stage_a = load_json(STAGE_A_RESULT, "Stage-A result")
    if (
        stage_a.get("stage_a_gate_passed") is not True
        or stage_a.get("opportunity_gate_passed") is not True
        or stage_a.get("neighboring_stability_gate_passed") is not True
        or stage_a.get("non_reconstruction_gate_passed") is not True
        or not isinstance(stage_a.get("neighboring_definition_stability"), dict)
        or not isinstance(stage_a.get("non_reconstruction"), dict)
        or stage_a.get("outcome_columns_read") is not False
        or stage_a.get("post_signal_primary_rows_read") is not False
        or stage_a.get("post_2020_rows_read") is not False
        or stage_a.get("direction") != "HIGH_D60_ONLY_FROZEN_BEFORE_OUTCOMES"
        or stage_a.get("d40_d80_candidate_use") is not False
        or stage_a.get("price_or_return_candidate_condition") is not False
        or stage_a.get("maximum_primary_source_row_date") != str(SIGNAL_END.date())
        or stage_a.get("maximum_signal_date") != str(SIGNAL_END.date())
        or stage_a.get("candidate_sha256") != EXPECTED[CANDIDATES]
        or stage_a.get("representation_sha256") != EXPECTED[REPRESENTATION]
        or stage_a.get("audit", {}).get("candidate_rows") != EXPECTED_CANDIDATES
        or stage_a.get("audit", {}).get("duplicate_event_ids") != 0
        or stage_a.get("audit", {}).get("deterministic_industry_winner_failures") != 0
        or stage_a.get("audit", {}).get("history_failures") != 0
        or stage_a.get("audit", {}).get("liquidity_failures") != 0
        or stage_a.get("audit", {}).get("industry_support_failures") != 0
        or stage_a.get("audit", {}).get("d60_bounds_failures") != 0
        or stage_a.get("audit", {}).get("v30_control_max_queried_date")
        != str(SIGNAL_END.date())
        or stage_a.get("audit", {}).get("v31_control_max_queried_date")
        != str(SIGNAL_END.date())
        or stage_a.get("audit", {}).get("v30_control_out_of_range_rows") != 0
        or stage_a.get("audit", {}).get("v31_control_out_of_range_rows") != 0
    ):
        raise ResearchError("Stage-A result does not authorize Stage B")
    verify_registry_and_manifest(actual)
    return actual, stage_a


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


def prepare_candidates(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[pd.DataFrame, dict[str, int]]:
    prepared = connection.execute(
        f"""
        SELECT c.* EXCLUDE(signal_cal_idx),c.signal_cal_idx AS source_signal_cal_idx,
          a.cal_idx AS signal_cal_idx,a.sleeve,a.invalid_step_cum,
          r.trade_date AS execution_raw_signal_date,
          a.trade_date AS coordinate_signal_date,r.industry AS execution_raw_industry,
          a.adjusted_close/r.close AS signal_coordinate_factor
        FROM read_parquet('{CANDIDATES.as_posix()}') c
        JOIN cy006 r ON r.symbol=c.symbol AND r.trade_date=c.signal_date
        JOIN read_parquet('{COORDINATE_STATE.as_posix()}') a
          ON a.symbol=c.symbol AND a.trade_date=c.signal_date
        WHERE r.trade_date BETWEEN DATE '{SIGNAL_START.date()}' AND DATE '{SIGNAL_END.date()}'
          AND r.hard_valid AND r.bar_valid AND r.trading_state_valid
          AND r.corporate_action_valid AND NOT r.corporate_action_blocking
          AND r.market_rule_valid AND r.historical_identity_valid
          AND r.current_day_data_tradable AND r.available_at<=r.decision_at
          AND a.current_valid AND a.corporate_action_valid
          AND NOT a.corporate_action_blocking AND a.adjusted_close>0
          AND r.close>0 AND isfinite(a.adjusted_close/r.close)
        ORDER BY c.signal_date,c.causal_industry,c.symbol,c.event_id
        """
    ).fetch_df()
    for column in (
        "signal_date",
        "execution_raw_signal_date",
        "coordinate_signal_date",
        "decision_at",
        "available_at",
    ):
        prepared[column] = pd.to_datetime(prepared[column])
    required_state = (
        "event_id",
        "signal_date",
        "execution_raw_signal_date",
        "coordinate_signal_date",
        "source_signal_cal_idx",
        "signal_cal_idx",
        "symbol",
        "sleeve",
        "causal_industry",
        "execution_raw_industry",
        "decision_at",
        "available_at",
        "snapshot_id",
        "daily_snapshot_id",
        "trading_state_snapshot_id",
        "industry_snapshot_id",
        "float_snapshot_id",
        "corporate_action_snapshot_id",
        "market_snapshot_id",
        "history_endpoint_count",
        "history_first_cal_idx",
        "history_last_cal_idx",
        "history_industry_mismatch_rows",
        "history_rows_with_complete_snapshot_identity",
        "same_date_exact_history_n",
        "same_date_median_amount",
        "coupling_pair_count",
        "coupling_first_cal_idx",
        "coupling_last_cal_idx",
        "minimum_other_peer_count",
        "current_turnover_innovation",
        "prior20_median_turnover",
        "turnover_to_prior20_median",
        "independence_d40",
        "independence_d60",
        "independence_d80",
        "industry_exact_history_n",
        "amount",
    )
    missing_state = sorted(set(required_state).difference(prepared.columns))
    if missing_state:
        raise ResearchError(f"prepared candidate schema misses V32 state: {missing_state}")
    source_cal_idx = pd.to_numeric(prepared.source_signal_cal_idx, errors="coerce")
    execution_cal_idx = pd.to_numeric(prepared.signal_cal_idx, errors="coerce")
    calendar_offsets = execution_cal_idx - source_cal_idx
    d_values = prepared[
        ["independence_d40", "independence_d60", "independence_d80"]
    ].apply(pd.to_numeric, errors="coerce")
    d_array = d_values.to_numpy(dtype=float)
    d_failures = (
        ~np.isfinite(d_array).all(axis=1)
        | (d_array < 0).any(axis=1)
        | (d_array > 1).any(axis=1)
    )
    sleeve = prepared.sleeve.astype("string").str.strip()
    audit = {
        "rows": len(prepared),
        "expected_rows": EXPECTED_CANDIDATES,
        "unique_event_ids": int(prepared.event_id.nunique()),
        "duplicate_event_ids": int(prepared.event_id.duplicated().sum()),
        "first_signal_date_matches": int(prepared.signal_date.min() == SIGNAL_START),
        "last_signal_date_matches": int(prepared.signal_date.max() == SIGNAL_END),
        "signal_date_join_mismatches": int(
            (
                prepared.execution_raw_signal_date.ne(prepared.signal_date)
                | prepared.coordinate_signal_date.ne(prepared.signal_date)
            ).sum()
        ),
        "signal_calendar_offset_unique_values": int(calendar_offsets.nunique(dropna=False)),
        "signal_calendar_offset_min": int(calendar_offsets.min()),
        "signal_calendar_offset_max": int(calendar_offsets.max()),
        "signal_industry_identity_mismatches": int(
            prepared.execution_raw_industry.ne(prepared.causal_industry).sum()
        ),
        "signal_timing_failures": int(prepared.available_at.gt(prepared.decision_at).sum()),
        "nonfinite_signal_lineage": int(
            (~np.isfinite(pd.to_numeric(prepared.invalid_step_cum, errors="coerce"))).sum()
        ),
        "nonfinite_signal_factor": int(
            (~np.isfinite(pd.to_numeric(prepared.signal_coordinate_factor, errors="coerce"))).sum()
        ),
        "missing_execution_sleeve": int(
            (sleeve.isna() | sleeve.eq("").fillna(True)).sum()
        ),
        "missing_v32_state_values": int(prepared[list(required_state)].isna().any(axis=1).sum()),
        "v32_exact_history_failures": int(
            (
                prepared.history_endpoint_count.ne(83)
                | prepared.history_first_cal_idx.ne(source_cal_idx - 82)
                | prepared.history_last_cal_idx.ne(source_cal_idx)
                | prepared.history_industry_mismatch_rows.ne(0)
                | prepared.history_rows_with_complete_snapshot_identity.ne(83)
                | prepared.coupling_pair_count.ne(80)
                | prepared.coupling_first_cal_idx.ne(source_cal_idx - 79)
                | prepared.coupling_last_cal_idx.ne(source_cal_idx)
                | prepared.minimum_other_peer_count.lt(10)
            ).sum()
        ),
        "v32_independence_bounds_failures": int(d_failures.sum()),
        "v32_liquidity_or_industry_support_failures": int(
            (
                prepared.amount.lt(prepared.same_date_median_amount)
                | prepared.industry_exact_history_n.lt(10)
            ).sum()
        ),
    }
    if (
        audit["rows"] != EXPECTED_CANDIDATES
        or audit["unique_event_ids"] != EXPECTED_CANDIDATES
        or audit["duplicate_event_ids"]
        or not audit["first_signal_date_matches"]
        or not audit["last_signal_date_matches"]
        or audit["signal_date_join_mismatches"]
        or audit["signal_industry_identity_mismatches"]
        or audit["signal_timing_failures"]
        or audit["nonfinite_signal_lineage"]
        or audit["nonfinite_signal_factor"]
        or audit["missing_execution_sleeve"]
        or audit["missing_v32_state_values"]
        or audit["v32_exact_history_failures"]
        or audit["v32_independence_bounds_failures"]
        or audit["v32_liquidity_or_industry_support_failures"]
    ):
        raise ResearchError(f"candidate execution-coordinate join failed: {audit}")
    return prepared, audit


def build_paths(
    connection: duckdb.DuckDBPyConnection, candidates: pd.DataFrame, output: Path
) -> tuple[pd.DataFrame, dict[str, int]]:
    keys = candidates[["event_id", "symbol", "signal_date", "signal_cal_idx"]].copy()
    connection.register("candidate_keys", keys)
    coverage = connection.execute(
        f"""
        WITH candidate_symbols AS (
          SELECT DISTINCT symbol FROM candidate_keys
        ), raw_path AS (
          SELECT r.symbol,r.trade_date FROM cy006 r
          JOIN candidate_symbols s USING(symbol)
          WHERE r.trade_date<=DATE '{MAX_PATH_DATE.date()}'
        ), coordinate_path AS (
          SELECT a.symbol,a.trade_date FROM read_parquet('{COORDINATE_STATE.as_posix()}') a
          JOIN candidate_symbols s USING(symbol)
          WHERE a.trade_date BETWEEN DATE '2018-01-01' AND DATE '{MAX_PATH_DATE.date()}'
        )
        SELECT count(*) AS raw_rows,
          count(*) FILTER (WHERE a.symbol IS NULL) AS missing_coordinate_rows
        FROM raw_path r LEFT JOIN coordinate_path a USING(symbol,trade_date)
        """
    ).fetchone()
    coverage_audit = {
        "candidate_symbol_raw_rows_through_cap": int(coverage[0]),
        "raw_rows_missing_coordinate_state": int(coverage[1]),
    }
    if coverage_audit["raw_rows_missing_coordinate_state"]:
        raise ResearchError(f"coordinate path coverage failed: {coverage_audit}")
    query = f"""
      WITH candidate_symbols AS (
        SELECT DISTINCT symbol FROM candidate_keys
      ), raw_path AS (
        SELECT r.* FROM cy006 r JOIN candidate_symbols s USING(symbol)
        WHERE r.trade_date<=DATE '{MAX_PATH_DATE.date()}'
      ), coordinate_path AS (
        SELECT a.* FROM read_parquet('{COORDINATE_STATE.as_posix()}') a
        JOIN candidate_symbols s USING(symbol)
        WHERE a.trade_date<=DATE '{MAX_PATH_DATE.date()}'
      ), joined AS (
        SELECT r.symbol,r.trade_date,a.cal_idx,r.open,r.high,r.low,r.close,
          r.open*a.adjusted_close/r.close AS coord_open,
          r.high*a.adjusted_close/r.close AS coord_high,
          r.low*a.adjusted_close/r.close AS coord_low,
          a.adjusted_close AS coord_close,a.invalid_step_cum,
          a.adjusted_close/r.close AS coordinate_factor,
          r.trade_status,r.current_day_data_tradable,a.current_valid,
          r.market_rule_valid,r.corporate_action_count,r.corporate_action_valid,
          r.corporate_action_blocking,r.hard_valid,r.up_limit_price,
          r.down_limit_price,r.available_at,r.decision_at
        FROM raw_path r JOIN coordinate_path a USING(symbol,trade_date)
        WHERE r.close>0 AND a.adjusted_close>0
      )
      SELECT c.event_id,c.symbol,c.signal_date AS event_signal_date,
        c.signal_cal_idx AS event_signal_cal_idx,j.* EXCLUDE(symbol)
      FROM candidate_keys c JOIN joined j ON j.symbol=c.symbol
        AND j.cal_idx>c.signal_cal_idx
      ORDER BY c.event_id,j.cal_idx
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
    return paths, coverage_audit


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
        "mean_net": None if completed.empty else float(completed.net_return.mean()),
        "median_net": None if completed.empty else float(completed.net_return.median()),
        "positive_rate": None if completed.empty else float(completed.net_return.gt(0).mean()),
        "ge_4pct_rate": None if completed.empty else float(completed.net_return.gt(0.04).mean()),
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
    stage_a: dict[str, Any],
    candidate_audit: dict[str, int],
    path_audit: dict[str, Any],
    outcome_audit: dict[str, Any],
    prepared_path: Path,
    paths_path: Path,
    outcomes_path: Path,
) -> dict[str, Any]:
    annual: dict[str, Any] = {}
    development_gate_pass = True
    for year in YEARS:
        cohort = candidates.loc[candidates.signal_date.dt.year.eq(year)]
        event_ids = set(cohort.event_id.astype(str))
        result = group_summary(outcomes.loc[outcomes.event_id.isin(event_ids)], cohort)
        annual[str(year)] = result
        development_gate_pass &= (
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
        "stage_a_candidate_rows": stage_a["audit"]["candidate_rows"],
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
        "development_gate_passed": bool(development_gate_pass),
        "later_period_authorized": False,
        "charts_rendered": False,
        "portfolio_replay_performed": False,
        "post_2020_row_read": False,
        "maximum_path_row_date": str(MAX_PATH_DATE.date()),
        "target_return": EXECUTION.TARGET_RETURN,
        "horizon_sessions": EXECUTION.HORIZON_SESSIONS,
        "round_trip_cost": EXECUTION.ROUND_TRIP_COST,
        "next_action": (
            "FREEZE_COMPLETE_DEVELOPMENT_CHART_PROTOCOL_BEFORE_ANY_LATER_PERIOD"
            if development_gate_pass
            else "RENDER_AND_REVIEW_ALL_DEVELOPMENT_CHARTS_BUT_KEEP_2022_2024_CLOSED"
        ),
    }


def main() -> None:
    source_hashes, stage_a = verify_inputs()
    if STAGE_B.exists():
        raise ResearchError(f"canonical V32 Stage B already exists: {STAGE_B}")
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
        path_audit = EXECUTION.audit_paths(paths, candidates)
        path_audit.update(path_source_audit)
        outcomes = EXECUTION.attach_outcomes(candidates, paths)
        outcome_audit = EXECUTION.audit_outcomes(outcomes, candidates)
        write_parquet(outcomes, outcomes_path)
        result = summarize(
            outcomes,
            candidates,
            source_hashes,
            stage_a,
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
            raise ResearchError("bound input changed during V32 Stage B")
        staging.replace(STAGE_B)
    except Exception:
        if connection is not None:
            connection.close()
        shutil.rmtree(staging, ignore_errors=True)
        raise
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
