#!/usr/bin/env python3
"""Attach the separately authorized frozen V30 development outcomes."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

EXPERIMENT = "ASHARE-LOW-POSITIVE-FEEDBACK-GOOD-NEWS-MOTHER-V30"
REPO = Path(__file__).resolve().parents[3]
PARENT_SPEC = REPO / (f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json")
STAGE_B_SPEC = REPO / (
    f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_stage_b_freeze.json"
)
STAGE_A_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_low_positive_feedback_good_news_mother_v30_stage_a.py"
)
REGISTRY = REPO / "configs/data_asset_registry.json"
ASSET_MANIFEST = REPO / (
    "research/market_behavior_os_v2/experiments/ASHARE-V30-CY035_DATA_ASSET_MANIFEST.json"
)
CY034_MANIFEST = REPO / (
    "research/market_behavior_os_v2/experiments/ASHARE-V30-CY034_DATA_ASSET_MANIFEST.json"
)
ASSET_ID = "CY-035"
DEPENDENCY_ASSET_ID = "CY-034"
AUTHORIZATION_ID = "CYQ-AUTH-ASHARE-TURNOVER-PFC-V30-STAGE-B-2013-2020-V1"
AUTHORIZED_ARM = "V30_FROZEN_STAGE_B_OUTCOME_ATTACHMENT_ONLY"

DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_low_positive_feedback_good_news_mother_v30"
)
STAGE_A = OUTPUT_ROOT / "stage_a"
STAGE_A_RESULT = STAGE_A / "result.json"
REPRESENTATION = STAGE_A / "representation_panel.parquet"
CANDIDATES = STAGE_A / "candidates_frozen.parquet"
STAGE_B = OUTPUT_ROOT / "stage_b"

EXPECTED_PARENT_SPEC = "c0f8c1c0617099f2705a873608fae390dbb30dd929b38ce040bab649e5841b0d"
EXPECTED_STAGE_B_SPEC = "cef22a12d0216d42a397c5d263f6efb0344cfd581e24ec0091f471e09d0ce779"
EXPECTED_DAILY = "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00"
EXPECTED_CY034_MANIFEST = "e56bb0b79132a3c355c87e15ce12997295eb8817bfc295e9a07fd6c8592d2077"
EXPECTED_REPRESENTATION = "3408f5728764331ec910c649ef8ef65afb80703d6e22e7bfaefd845b3be5ba4b"
EXPECTED_CANDIDATES = "ef1b4126637382071f0d9d563f83205bff04731c7b51a5e3a83a07bee8324c3f"

CONTEXT_START = pd.Timestamp("2013-01-04")
SIGNAL_START = pd.Timestamp("2014-01-01")
COHORT_SIGNAL_START = pd.Timestamp("2014-01-30")
SIGNAL_END = pd.Timestamp("2020-06-30")
MAX_PATH_DATE = pd.Timestamp("2020-12-31")
TARGET_RETURN = 0.10
HORIZON_SESSIONS = 20
ROUND_TRIP_COST = 0.004
ALLOWED_STATUSES = {
    "NO_LEGAL_ENTRY",
    "INVALID_COORDINATE_LINEAGE_BEFORE_ENTRY",
    "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
    "INVALID_CORPORATE_ACTION_STATE_BEFORE_ENTRY",
    "INVALID_CORPORATE_ACTION_STATE_AFTER_ENTRY",
    "INCOMPLETE_PATH",
    "COMPLETED",
}


class ResearchError(RuntimeError):
    """Fail closed on authorization, identity, chronology, or execution drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def event_set_sha256(values: Iterable[Any]) -> str:
    normalized = sorted(str(value) for value in values)
    return hashlib.sha256(("\n".join(normalized) + "\n").encode("utf-8")).hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ResearchError(f"{label} is not a JSON object: {path}")
    return value


def only(items: list[dict[str, Any]], label: str) -> dict[str, Any]:
    if len(items) != 1:
        raise ResearchError(f"expected exactly one {label}, found {len(items)}")
    return items[0]


def role_map(items: Any, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ResearchError(f"{label} must be a list of objects")
    mapped: dict[str, dict[str, Any]] = {}
    for item in items:
        role = item.get("role")
        if not isinstance(role, str) or not role or role in mapped:
            raise ResearchError(f"{label} has a missing or duplicate role: {role!r}")
        mapped[role] = item
    return mapped


def require_bound_item(
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


def verify_stage_a_result(result: dict[str, Any], actual: dict[str, str]) -> None:
    if (
        result.get("stage_a_gate_passed") is not True
        or result.get("outcomes_read") is not False
        or result.get("post_2020_row_read") is not False
        or result.get("post_signal_end_row_read") is not False
        or result.get("candidate_sha256") != EXPECTED_CANDIDATES
        or result.get("representation_sha256") != EXPECTED_REPRESENTATION
        or result.get("maximum_signal_date") != str(SIGNAL_END.date())
    ):
        raise ResearchError("Stage-A result does not authorize frozen outcome attachment")
    source_hashes = result.get("source_hashes")
    if not isinstance(source_hashes, dict):
        raise ResearchError("Stage-A result has no source hash map")
    if (
        source_hashes.get("spec") != actual["parent_spec"]
        or source_hashes.get("daily") != actual["daily"]
        or source_hashes.get("runner") != actual["stage_a_runner"]
    ):
        raise ResearchError("Stage-A result source identity drift")
    audit = result.get("audit")
    if not isinstance(audit, dict) or not isinstance(audit.get("candidate_rows"), int):
        raise ResearchError("Stage-A result has no exact candidate-row audit")


def verify_registry_and_manifest(actual: dict[str, str]) -> None:
    registry = load_json(REGISTRY, "data registry")
    assets = registry.get("assets")
    authorizations = registry.get("bounded_authorizations")
    if not isinstance(assets, list) or not isinstance(authorizations, list):
        raise ResearchError("data registry has no asset/authorization lists")
    asset = only(
        [item for item in assets if item.get("asset_id") == ASSET_ID],
        f"registry asset {ASSET_ID}",
    )
    dependency = only(
        [item for item in assets if item.get("asset_id") == DEPENDENCY_ASSET_ID],
        f"registry asset {DEPENDENCY_ASSET_ID}",
    )
    authorization = only(
        [item for item in authorizations if item.get("authorization_id") == AUTHORIZATION_ID],
        f"registry authorization {AUTHORIZATION_ID}",
    )

    lineage = asset.get("lineage", {})
    coverage = asset.get("coverage", {})
    if (
        asset.get("status") != "RESEARCH_CONDITIONAL"
        or asset.get("location") != str(DAILY)
        or lineage.get("immutable_manifest") is not True
        or lineage.get("manifest_path") != str(ASSET_MANIFEST.resolve())
        or lineage.get("manifest_sha256") != actual["asset_manifest"]
        or lineage.get("bounded_authorization_id") != AUTHORIZATION_ID
        or coverage.get("authorized_start") != str(CONTEXT_START.date())
        or coverage.get("authorized_end") != str(MAX_PATH_DATE.date())
    ):
        raise ResearchError(f"registry asset {ASSET_ID} semantics drift")

    scope = authorization.get("scope", {})
    bound_manifest = authorization.get("bound_manifest", {})
    bound_strategy = authorization.get("bound_strategy", {})
    bound_protocol = authorization.get("bound_protocol", {})
    if (
        authorization.get("purpose") != "ASHARE_FROZEN_DEVELOPMENT_OUTCOME_ATTACHMENT"
        or authorization.get("asset_id") != ASSET_ID
        or authorization.get("dependency_asset_id") != DEPENDENCY_ASSET_ID
        or authorization.get("dependency_status") != dependency.get("status")
        or dependency.get("status") != "RESEARCH_CONDITIONAL"
        or scope.get("project") != "research/market_behavior_os_v2"
        or scope.get("start") != str(CONTEXT_START.date())
        or scope.get("end") != str(MAX_PATH_DATE.date())
        or scope.get("warmup_start") != str(CONTEXT_START.date())
        or scope.get("signal_start") != str(SIGNAL_START.date())
        or scope.get("signal_end") != str(SIGNAL_END.date())
        or scope.get("actual_candidate_signal_start") != str(COHORT_SIGNAL_START.date())
        or scope.get("maximum_physical_row_date") != str(MAX_PATH_DATE.date())
        or scope.get("frozen_candidate_rows") != 2312
        or scope.get("frozen_candidate_sha256") != EXPECTED_CANDIDATES
        or authorization.get("authorized_arms") != [AUTHORIZED_ARM]
        or authorization.get("outcome_attachment_authorized") is not True
        or authorization.get("charts_authorized") is not False
        or authorization.get("portfolio_replay_authorized") is not False
        or authorization.get("post_2020_read_authorized") is not False
        or authorization.get("current_survivor_fallback_allowed") is not False
        or bound_manifest.get("path") != str(ASSET_MANIFEST.resolve())
        or bound_manifest.get("sha256") != actual["asset_manifest"]
        or bound_strategy.get("path") != str(PARENT_SPEC.resolve())
        or bound_strategy.get("sha256") != actual["parent_spec"]
        or bound_protocol.get("path") != str(STAGE_B_SPEC.resolve())
        or bound_protocol.get("sha256") != actual["stage_b_spec"]
        or bound_protocol.get("runner_path") != str(Path(__file__).resolve())
        or bound_protocol.get("runner_sha256") != actual["stage_b_runner"]
    ):
        raise ResearchError("CY-035 bounded authorization semantics drift")

    authorized_artifacts = role_map(
        authorization.get("bound_artifacts"), "authorization bound_artifacts"
    )
    for role, path, digest_key in (
        ("daily_compact", DAILY, "daily"),
        ("cy034_manifest", CY034_MANIFEST, "cy034_manifest"),
        ("stage_a_runner", STAGE_A_RUNNER, "stage_a_runner"),
        ("stage_a_result", STAGE_A_RESULT, "stage_a_result"),
        ("stage_a_representation", REPRESENTATION, "representation"),
        ("stage_a_candidates", CANDIDATES, "candidates"),
    ):
        require_bound_item(authorized_artifacts, role, path, actual[digest_key], "authorization")

    manifest = load_json(ASSET_MANIFEST, "CY-035 asset manifest")
    artifact = manifest.get("artifact", {})
    authorized_slice = artifact.get("authorized_context_slice", {})
    upstream = manifest.get("upstream_bounded_asset", {})
    cohort = manifest.get("frozen_cohort", {})
    boundary = manifest.get("authorization_boundary", {})
    if (
        manifest.get("asset_id") != ASSET_ID
        or artifact.get("path") != str(DAILY)
        or artifact.get("sha256") != actual["daily"]
        or authorized_slice.get("start") != str(CONTEXT_START.date())
        or authorized_slice.get("end") != str(MAX_PATH_DATE.date())
        or upstream.get("asset_id") != DEPENDENCY_ASSET_ID
        or upstream.get("authorization_id")
        != "CYQ-AUTH-ASHARE-TURNOVER-PFC-V30-STAGE-A-2013-2020-V1"
        or upstream.get("manifest_path")
        != "research/market_behavior_os_v2/experiments/ASHARE-V30-CY034_DATA_ASSET_MANIFEST.json"
        or upstream.get("manifest_sha256") != actual["cy034_manifest"]
        or boundary.get("authorization_id") != AUTHORIZATION_ID
        or boundary.get("purpose") != "ASHARE_FROZEN_DEVELOPMENT_OUTCOME_ATTACHMENT"
        or boundary.get("authorized_arm") != AUTHORIZED_ARM
        or boundary.get("candidate_signal_start") != str(COHORT_SIGNAL_START.date())
        or boundary.get("candidate_signal_end") != str(SIGNAL_END.date())
        or boundary.get("maximum_physical_row_date") != str(MAX_PATH_DATE.date())
        or boundary.get("maximum_evaluation_path_date") != str(MAX_PATH_DATE.date())
        or boundary.get("outcome_attachment_authorized") is not True
        or boundary.get("charts_authorized") is not False
        or boundary.get("portfolio_replay_authorized") is not False
        or boundary.get("2021_read_authorized") is not False
        or boundary.get("2022_plus_read_authorized") is not False
    ):
        raise ResearchError("CY-035 asset manifest semantics drift")
    frozen_items = (
        (
            "parent_spec",
            "research/market_behavior_os_v2/experiments/"
            "ASHARE-LOW-POSITIVE-FEEDBACK-GOOD-NEWS-MOTHER-V30_freeze.json",
            actual["parent_spec"],
        ),
        (
            "stage_a_runner",
            "research/market_behavior_os_v2/scripts/"
            "run_ashare_low_positive_feedback_good_news_mother_v30_stage_a.py",
            actual["stage_a_runner"],
        ),
        ("stage_a_result", str(STAGE_A_RESULT), actual["stage_a_result"]),
        ("representation", str(REPRESENTATION), actual["representation"]),
        ("candidates", str(CANDIDATES), actual["candidates"]),
    )
    for key, expected_path, expected_digest in frozen_items:
        item = cohort.get(key)
        if (
            not isinstance(item, dict)
            or item.get("path") != expected_path
            or item.get("sha256") != expected_digest
        ):
            raise ResearchError(f"CY-035 manifest frozen_cohort drift for {key}")
    candidate_cohort = cohort.get("candidates", {})
    if (
        candidate_cohort.get("rows") != 2312
        or candidate_cohort.get("unique_event_ids") != 2312
        or candidate_cohort.get("signal_start") != str(COHORT_SIGNAL_START.date())
        or candidate_cohort.get("signal_end") != str(SIGNAL_END.date())
    ):
        raise ResearchError("CY-035 manifest candidate-cohort audit drift")


def verify_inputs() -> tuple[dict[str, str], dict[str, Any]]:
    required = (
        PARENT_SPEC,
        STAGE_B_SPEC,
        STAGE_A_RUNNER,
        CY034_MANIFEST,
        REGISTRY,
        ASSET_MANIFEST,
        DAILY,
        STAGE_A_RESULT,
        REPRESENTATION,
        CANDIDATES,
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ResearchError(f"missing frozen or authorized input: {missing}")
    actual = {
        "parent_spec": sha256(PARENT_SPEC),
        "stage_b_spec": sha256(STAGE_B_SPEC),
        "stage_a_runner": sha256(STAGE_A_RUNNER),
        "cy034_manifest": sha256(CY034_MANIFEST),
        "stage_b_runner": sha256(Path(__file__)),
        "registry": sha256(REGISTRY),
        "asset_manifest": sha256(ASSET_MANIFEST),
        "daily": sha256(DAILY),
        "stage_a_result": sha256(STAGE_A_RESULT),
        "representation": sha256(REPRESENTATION),
        "candidates": sha256(CANDIDATES),
    }
    expected = {
        "parent_spec": EXPECTED_PARENT_SPEC,
        "stage_b_spec": EXPECTED_STAGE_B_SPEC,
        "daily": EXPECTED_DAILY,
        "cy034_manifest": EXPECTED_CY034_MANIFEST,
        "representation": EXPECTED_REPRESENTATION,
        "candidates": EXPECTED_CANDIDATES,
    }
    if {key: actual[key] for key in expected} != expected:
        raise ResearchError(f"frozen V30 input identity drift: {actual}")
    verify_registry_and_manifest(actual)
    stage_a_result = load_json(STAGE_A_RESULT, "Stage-A result")
    verify_stage_a_result(stage_a_result, actual)
    return actual, stage_a_result


def connect(temporary: Path) -> duckdb.DuckDBPyConnection:
    temporary.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='10GB'")
    con.execute(f"SET temp_directory='{temporary.as_posix()}'")
    return con


def load_candidates(stage_a_result: dict[str, Any]) -> pd.DataFrame:
    candidates = pd.read_parquet(CANDIDATES)
    required = {
        "event_id",
        "symbol",
        "sleeve",
        "causal_industry",
        "signal_date",
        "signal_cal_idx",
        "decision_at",
        "available_at",
        "invalid_step_cum",
    }
    missing = sorted(required.difference(candidates.columns))
    if missing:
        raise ResearchError(f"candidate schema misses required columns: {missing}")
    for column in ("signal_date", "decision_at", "available_at"):
        candidates[column] = pd.to_datetime(candidates[column])
    candidates["event_id"] = candidates.event_id.astype("string")
    candidates["symbol"] = candidates.symbol.astype("string")
    expected_rows = stage_a_result["audit"]["candidate_rows"]
    annual = stage_a_result.get("annual", {})
    annual_rows = (
        sum(item.get("events", -1) for item in annual.values())
        if isinstance(annual, dict) and all(isinstance(item, dict) for item in annual.values())
        else -1
    )
    invalid_identity = (
        candidates.event_id.isna()
        | candidates.event_id.str.strip().eq("")
        | candidates.symbol.isna()
        | candidates.symbol.str.strip().eq("")
    )
    missing_required_values = candidates[list(sorted(required))].isna().any(axis=1)
    lineage = pd.to_numeric(candidates.invalid_step_cum, errors="coerce")
    audit = {
        "rows": len(candidates),
        "expected_rows": int(expected_rows),
        "annual_rows": int(annual_rows),
        "invalid_identity_rows": int(invalid_identity.sum()),
        "missing_required_value_rows": int(missing_required_values.sum()),
        "duplicate_event_ids": int(candidates.event_id.duplicated().sum()),
        "pre_signal_start": int(candidates.signal_date.lt(SIGNAL_START).sum()),
        "post_signal_end": int(candidates.signal_date.gt(SIGNAL_END).sum()),
        "unexpected_first_signal_date": int(candidates.signal_date.min() != COHORT_SIGNAL_START),
        "unexpected_last_signal_date": int(candidates.signal_date.max() != SIGNAL_END),
        "timing_failures": int(candidates.available_at.gt(candidates.decision_at).sum()),
        "nonfinite_signal_lineage": int((~np.isfinite(lineage)).sum()),
        "noninteger_signal_cal_idx": int(
            pd.to_numeric(candidates.signal_cal_idx, errors="coerce").mod(1).fillna(1).ne(0).sum()
        ),
    }
    if (
        audit["rows"] != audit["expected_rows"]
        or audit["rows"] != audit["annual_rows"]
        or any(
            value
            for key, value in audit.items()
            if key not in {"rows", "expected_rows", "annual_rows"}
        )
    ):
        raise ResearchError(f"candidate identity audit failed: {audit}")
    candidates["signal_cal_idx"] = candidates.signal_cal_idx.astype("int64")
    candidates["invalid_step_cum"] = lineage.astype(float)
    return candidates.sort_values(
        ["signal_cal_idx", "causal_industry", "symbol", "event_id"],
        kind="mergesort",
    ).reset_index(drop=True)


def sql_path(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def build_paths(
    con: duckdb.DuckDBPyConnection,
    candidates: pd.DataFrame,
    output: Path,
) -> pd.DataFrame:
    keys = candidates[["event_id", "symbol", "signal_date", "signal_cal_idx"]].copy()
    con.register("candidate_keys", keys)
    query = f"""
      WITH candidate_symbols AS (
        SELECT DISTINCT symbol FROM candidate_keys
      ), authorized_daily AS (
        SELECT d.symbol,d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,
          d.invalid_step_cum,d.coordinate_factor,d.trade_status,
          d.current_day_data_tradable,d.current_valid,d.market_rule_valid,
          d.corporate_action_count,d.corporate_action_valid,
          d.corporate_action_blocking,d.hard_valid,
          d.up_limit_price,d.down_limit_price,d.available_at,d.decision_at
        FROM read_parquet('{sql_path(DAILY)}') d
        INNER JOIN candidate_symbols s USING(symbol)
        WHERE d.trade_date<=DATE '2020-12-31'
      )
      SELECT c.event_id,c.symbol,c.signal_date AS event_signal_date,
        c.signal_cal_idx AS event_signal_cal_idx,
        d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
        d.coord_open,d.coord_high,d.coord_low,d.coord_close,
        d.invalid_step_cum,d.coordinate_factor,d.trade_status,
        d.current_day_data_tradable,d.current_valid,d.market_rule_valid,
        d.corporate_action_count,d.corporate_action_valid,
        d.corporate_action_blocking,d.hard_valid,
        d.up_limit_price,d.down_limit_price,d.available_at,d.decision_at
      FROM candidate_keys c
      INNER JOIN authorized_daily d
        ON d.symbol=c.symbol AND d.cal_idx>c.signal_cal_idx
      ORDER BY c.event_id,d.cal_idx
    """
    con.execute(f"COPY ({query}) TO '{sql_path(output)}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    paths = con.execute(
        f"SELECT * FROM read_parquet('{sql_path(output)}') ORDER BY event_id,cal_idx"
    ).fetch_df()
    con.unregister("candidate_keys")
    for column in (
        "event_signal_date",
        "trade_date",
        "available_at",
        "decision_at",
    ):
        paths[column] = pd.to_datetime(paths[column])
    return paths


def audit_paths(paths: pd.DataFrame, candidates: pd.DataFrame) -> dict[str, Any]:
    candidate_ids = set(candidates.event_id.astype(str))
    candidate_symbols = set(candidates.symbol.astype(str))
    expected_pair = dict(
        zip(candidates.event_id.astype(str), candidates.symbol.astype(str), strict=True)
    )
    path_ids = set(paths.event_id.astype(str)) if not paths.empty else set()
    path_symbols = set(paths.symbol.astype(str)) if not paths.empty else set()
    mapped_symbol_failures = (
        int(
            sum(
                expected_pair.get(str(row.event_id)) != str(row.symbol)
                for row in paths[["event_id", "symbol"]].drop_duplicates().itertuples(index=False)
            )
        )
        if not paths.empty
        else 0
    )
    audit = {
        "rows": len(paths),
        "events_with_rows": len(path_ids),
        "candidate_events_without_rows": len(candidate_ids.difference(path_ids)),
        "duplicate_event_cal_idx": int(paths.duplicated(["event_id", "cal_idx"]).sum()),
        "non_candidate_event_ids": len(path_ids.difference(candidate_ids)),
        "non_candidate_symbols": len(path_symbols.difference(candidate_symbols)),
        "event_symbol_mapping_failures": mapped_symbol_failures,
        "at_or_before_signal": int(paths.cal_idx.le(paths.event_signal_cal_idx).sum()),
        "post_cap_rows": int(paths.trade_date.gt(MAX_PATH_DATE).sum()),
        "at_or_before_signal_date": int(paths.trade_date.le(paths.event_signal_date).sum()),
        "candidate_event_id_set_sha256": event_set_sha256(candidate_ids),
        "path_event_id_set_sha256": event_set_sha256(path_ids),
        "candidate_symbol_set_sha256": event_set_sha256(candidate_symbols),
        "path_symbol_set_sha256": event_set_sha256(path_symbols),
    }
    blocking = (
        "duplicate_event_cal_idx",
        "non_candidate_event_ids",
        "non_candidate_symbols",
        "event_symbol_mapping_failures",
        "at_or_before_signal",
        "post_cap_rows",
        "at_or_before_signal_date",
    )
    if any(audit[key] for key in blocking):
        raise ResearchError(f"future-path scope audit failed: {audit}")
    return audit


def finite(value: Any) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def legal(row: Any) -> bool:
    required = (
        row.trade_status,
        row.current_day_data_tradable,
        row.current_valid,
        row.market_rule_valid,
        row.corporate_action_count,
        row.corporate_action_valid,
        row.corporate_action_blocking,
        row.hard_valid,
        row.available_at,
        row.decision_at,
    )
    return bool(
        not any(pd.isna(value) for value in required)
        and finite(row.trade_status)
        and float(row.trade_status) == 1.0
        and bool(row.current_day_data_tradable)
        and bool(row.current_valid)
        and bool(row.market_rule_valid)
        and finite(row.corporate_action_count)
        and float(row.corporate_action_count) == 0.0
        and bool(row.corporate_action_valid)
        and not bool(row.corporate_action_blocking)
        and bool(row.hard_valid)
        and pd.Timestamp(row.available_at) <= pd.Timestamp(row.decision_at)
        and finite(row.open)
        and float(row.open) > 0
        and finite(row.coord_open)
        and float(row.coord_open) > 0
        and finite(row.coordinate_factor)
        and float(row.coordinate_factor) > 0
    )


def fen(value: Any) -> int:
    return round(float(value) * 100)


def buyable(row: Any) -> bool:
    return bool(
        legal(row)
        and finite(row.up_limit_price)
        and float(row.up_limit_price) > 0
        and fen(row.open) < fen(row.up_limit_price)
    )


def sellable_open(row: Any) -> bool:
    return bool(
        legal(row)
        and finite(row.down_limit_price)
        and float(row.down_limit_price) > 0
        and fen(row.open) > fen(row.down_limit_price)
    )


def missing_corporate_action_fields(row: Any) -> list[str]:
    return [
        name
        for name in (
            "corporate_action_count",
            "corporate_action_valid",
            "corporate_action_blocking",
        )
        if pd.isna(getattr(row, name))
    ]


def intraday_target_fillable(row: Any, target_price: float) -> bool:
    return bool(
        legal(row)
        and finite(row.coord_high)
        and float(row.coord_high) >= target_price
        and finite(row.high)
        and float(row.high) > 0
        and finite(row.down_limit_price)
        and float(row.down_limit_price) > 0
        and fen(row.high) > fen(row.down_limit_price)
    )


def same_lineage(value: Any, expected: float) -> bool:
    return bool(finite(value) and float(value) == expected)


def outcome_base(candidate: Any) -> dict[str, Any]:
    return {
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "causal_industry": str(candidate.causal_industry),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_cal_idx": int(candidate.signal_cal_idx),
        "signal_invalid_step_cum": float(candidate.invalid_step_cum),
        "target_return": TARGET_RETURN,
        "horizon_sessions": HORIZON_SESSIONS,
        "round_trip_cost": ROUND_TRIP_COST,
        "status": "NO_LEGAL_ENTRY",
        "lineage_invalid_date": pd.NaT,
        "lineage_invalid_cal_idx": math.nan,
        "data_invalid_date": pd.NaT,
        "data_invalid_cal_idx": math.nan,
        "data_invalid_reason": None,
        "entry_date": pd.NaT,
        "entry_cal_idx": math.nan,
        "entry_price": math.nan,
        "target_price": math.nan,
        "exit_date": pd.NaT,
        "exit_cal_idx": math.nan,
        "exit_price": math.nan,
        "exit_reason": None,
        "exit_execution_phase": None,
        "exit_coord_open": math.nan,
        "exit_coord_high": math.nan,
        "exit_raw_open": math.nan,
        "exit_raw_high": math.nan,
        "exit_raw_down_limit_price": math.nan,
        "holding_sessions": math.nan,
        "gross_return": math.nan,
        "net_return": math.nan,
    }


def replay_one(candidate: Any, path: pd.DataFrame) -> dict[str, Any]:
    result = outcome_base(candidate)
    lineage = float(candidate.invalid_step_cum)
    ordered = path.sort_values("cal_idx", kind="mergesort")
    entry = None
    entry_pool = ordered.loc[
        ordered.cal_idx.gt(int(candidate.signal_cal_idx))
        & ordered.cal_idx.le(int(candidate.signal_cal_idx) + 3)
    ]
    for row in entry_pool.itertuples(index=False):
        missing_action = missing_corporate_action_fields(row)
        if missing_action:
            return {
                **result,
                "status": "INVALID_CORPORATE_ACTION_STATE_BEFORE_ENTRY",
                "data_invalid_date": pd.Timestamp(row.trade_date),
                "data_invalid_cal_idx": int(row.cal_idx),
                "data_invalid_reason": "MISSING_" + "_".join(missing_action).upper(),
            }
        if not same_lineage(row.invalid_step_cum, lineage):
            return {
                **result,
                "status": "INVALID_COORDINATE_LINEAGE_BEFORE_ENTRY",
                "lineage_invalid_date": pd.Timestamp(row.trade_date),
                "lineage_invalid_cal_idx": int(row.cal_idx),
            }
        if buyable(row):
            entry = row
            break
    if entry is None:
        return result

    entry_idx = int(entry.cal_idx)
    entry_price = float(entry.coord_open)
    target_price = entry_price * (1.0 + TARGET_RETURN)
    entered = {
        **result,
        "status": "INCOMPLETE_PATH",
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": entry_idx,
        "entry_price": entry_price,
        "target_price": target_price,
    }
    for row in ordered.loc[ordered.cal_idx.gt(entry_idx)].itertuples(index=False):
        missing_action = missing_corporate_action_fields(row)
        if missing_action:
            return {
                **entered,
                "status": "INVALID_CORPORATE_ACTION_STATE_AFTER_ENTRY",
                "data_invalid_date": pd.Timestamp(row.trade_date),
                "data_invalid_cal_idx": int(row.cal_idx),
                "data_invalid_reason": "MISSING_" + "_".join(missing_action).upper(),
            }
        if not same_lineage(row.invalid_step_cum, lineage):
            return {
                **entered,
                "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
                "lineage_invalid_date": pd.Timestamp(row.trade_date),
                "lineage_invalid_cal_idx": int(row.cal_idx),
            }
        fallback_eligible = int(row.cal_idx) > entry_idx + HORIZON_SESSIONS
        if fallback_eligible and sellable_open(row):
            if float(row.coord_open) >= target_price:
                exit_price = target_price
                exit_reason = "TARGET_10"
                exit_execution_phase = "FALLBACK_ELIGIBLE_OPEN_TARGET"
            else:
                exit_price = float(row.coord_open)
                exit_reason = "H20_TIME_STOP"
                exit_execution_phase = "FALLBACK_ELIGIBLE_OPEN_TIME_STOP"
        elif intraday_target_fillable(row, target_price):
            exit_price = target_price
            exit_reason = "TARGET_10"
            exit_execution_phase = (
                "INTRADAY_TARGET_AFTER_UNSELLABLE_FALLBACK_OPEN"
                if fallback_eligible
                else "INTRADAY_TARGET_BEFORE_FALLBACK"
            )
        else:
            continue
        gross_return = exit_price / entry_price - 1.0
        return {
            **entered,
            "status": "COMPLETED",
            "exit_date": pd.Timestamp(row.trade_date),
            "exit_cal_idx": int(row.cal_idx),
            "exit_price": float(exit_price),
            "exit_reason": exit_reason,
            "exit_execution_phase": exit_execution_phase,
            "exit_coord_open": float(row.coord_open) if finite(row.coord_open) else math.nan,
            "exit_coord_high": float(row.coord_high) if finite(row.coord_high) else math.nan,
            "exit_raw_open": float(row.open) if finite(row.open) else math.nan,
            "exit_raw_high": float(row.high) if finite(row.high) else math.nan,
            "exit_raw_down_limit_price": float(row.down_limit_price)
            if finite(row.down_limit_price)
            else math.nan,
            "holding_sessions": int(row.cal_idx) - entry_idx,
            "gross_return": float(gross_return),
            "net_return": float(gross_return - ROUND_TRIP_COST),
        }
    return entered


def attach_outcomes(candidates: pd.DataFrame, paths: pd.DataFrame) -> pd.DataFrame:
    empty_path = paths.iloc[0:0]
    path_lookup = {str(event_id): part for event_id, part in paths.groupby("event_id", sort=False)}
    rows = [
        replay_one(
            candidate,
            path_lookup.get(str(candidate.event_id), empty_path),
        )
        for candidate in candidates.itertuples(index=False)
    ]
    outcomes = (
        pd.DataFrame(rows)
        .sort_values(
            ["signal_date", "causal_industry", "symbol", "event_id"],
            kind="mergesort",
        )
        .reset_index(drop=True)
    )
    return outcomes


def audit_outcomes(
    outcomes: pd.DataFrame,
    candidates: pd.DataFrame,
) -> dict[str, Any]:
    candidate_ids = set(candidates.event_id.astype(str))
    outcome_ids = set(outcomes.event_id.astype(str))
    entered = outcomes.loc[outcomes.entry_cal_idx.notna()].copy()
    completed = outcomes.loc[outcomes.status.eq("COMPLETED")].copy()
    incomplete = outcomes.loc[~outcomes.status.eq("COMPLETED")]
    numeric_returns = pd.to_numeric(completed.net_return, errors="coerce")
    target_phases = {
        "FALLBACK_ELIGIBLE_OPEN_TARGET",
        "INTRADAY_TARGET_AFTER_UNSELLABLE_FALLBACK_OPEN",
        "INTRADAY_TARGET_BEFORE_FALLBACK",
    }
    target_rows = completed.loc[completed.exit_reason.eq("TARGET_10")].copy()
    open_targets = target_rows.loc[
        target_rows.exit_execution_phase.eq("FALLBACK_ELIGIBLE_OPEN_TARGET")
    ]
    intraday_targets = target_rows.loc[
        target_rows.exit_execution_phase.isin(
            {
                "INTRADAY_TARGET_AFTER_UNSELLABLE_FALLBACK_OPEN",
                "INTRADAY_TARGET_BEFORE_FALLBACK",
            }
        )
    ]
    h20_rows = completed.loc[completed.exit_reason.eq("H20_TIME_STOP")].copy()
    action_invalid = outcomes.loc[
        outcomes.status.isin(
            {
                "INVALID_CORPORATE_ACTION_STATE_BEFORE_ENTRY",
                "INVALID_CORPORATE_ACTION_STATE_AFTER_ENTRY",
            }
        )
    ]
    other_rows = outcomes.loc[~outcomes.index.isin(action_invalid.index)]

    def bad_positive_finite(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
        if frame.empty:
            return pd.Series(dtype=bool)
        values = frame[columns].apply(pd.to_numeric, errors="coerce")
        return (~np.isfinite(values)).any(axis=1) | values.le(0).any(axis=1)

    audit = {
        "rows": len(outcomes),
        "candidate_rows": len(candidates),
        "duplicate_event_ids": int(outcomes.event_id.duplicated().sum()),
        "missing_candidate_event_ids": len(candidate_ids.difference(outcome_ids)),
        "extra_outcome_event_ids": len(outcome_ids.difference(candidate_ids)),
        "unknown_statuses": len(set(outcomes.status).difference(ALLOWED_STATUSES)),
        "entry_before_plus1": int(entered.entry_cal_idx.lt(entered.signal_cal_idx + 1).sum()),
        "entry_after_plus3": int(entered.entry_cal_idx.gt(entered.signal_cal_idx + 3).sum()),
        "exit_at_or_before_entry": int(completed.exit_cal_idx.le(completed.entry_cal_idx).sum()),
        "post_cap_completed_exits": int(completed.exit_date.gt(MAX_PATH_DATE).sum()),
        "nonfinite_completed_returns": int((~np.isfinite(numeric_returns)).sum()),
        "bad_target_holding": int(
            completed.loc[completed.exit_reason.eq("TARGET_10")].holding_sessions.lt(1).sum()
        ),
        "bad_fallback_holding": int(
            completed.loc[completed.exit_reason.eq("H20_TIME_STOP")]
            .holding_sessions.le(HORIZON_SESSIONS)
            .sum()
        ),
        "unknown_exit_reasons": int(
            (~completed.exit_reason.isin(["TARGET_10", "H20_TIME_STOP"])).sum()
        ),
        "bad_target_execution_phase": int(
            (
                ~completed.loc[completed.exit_reason.eq("TARGET_10")].exit_execution_phase.isin(
                    target_phases
                )
            ).sum()
        ),
        "bad_h20_execution_phase": int(
            (
                ~completed.loc[completed.exit_reason.eq("H20_TIME_STOP")].exit_execution_phase.eq(
                    "FALLBACK_ELIGIBLE_OPEN_TIME_STOP"
                )
            ).sum()
        ),
        "noncompleted_exit_execution_phase": int(incomplete.exit_execution_phase.notna().sum()),
        "bad_action_invalid_evidence": int(
            action_invalid[["data_invalid_date", "data_invalid_cal_idx", "data_invalid_reason"]]
            .isna()
            .any(axis=1)
            .sum()
        ),
        "unexpected_action_invalid_evidence": int(
            other_rows[["data_invalid_date", "data_invalid_cal_idx", "data_invalid_reason"]]
            .notna()
            .any(axis=1)
            .sum()
        ),
        "bad_target_exit_price": int(
            (
                ~np.isclose(
                    pd.to_numeric(target_rows.exit_price, errors="coerce"),
                    pd.to_numeric(target_rows.target_price, errors="coerce"),
                    atol=1e-12,
                )
            ).sum()
        ),
        "bad_open_target_limit_evidence": int(
            (
                bad_positive_finite(
                    open_targets,
                    ["exit_raw_open", "exit_raw_down_limit_price"],
                )
                | (
                    np.rint(pd.to_numeric(open_targets.exit_raw_open, errors="coerce") * 100)
                    <= np.rint(
                        pd.to_numeric(open_targets.exit_raw_down_limit_price, errors="coerce") * 100
                    )
                )
            ).sum()
        ),
        "bad_intraday_target_limit_evidence": int(
            (
                bad_positive_finite(
                    intraday_targets,
                    ["exit_raw_high", "exit_raw_down_limit_price"],
                )
                | (
                    np.rint(pd.to_numeric(intraday_targets.exit_raw_high, errors="coerce") * 100)
                    <= np.rint(
                        pd.to_numeric(
                            intraday_targets.exit_raw_down_limit_price,
                            errors="coerce",
                        )
                        * 100
                    )
                )
            ).sum()
        ),
        "bad_h20_exit_price": int(
            (
                ~np.isclose(
                    pd.to_numeric(h20_rows.exit_price, errors="coerce"),
                    pd.to_numeric(h20_rows.exit_coord_open, errors="coerce"),
                    atol=1e-12,
                )
            ).sum()
        ),
        "candidate_event_id_set_sha256": event_set_sha256(candidate_ids),
        "outcome_event_id_set_sha256": event_set_sha256(outcome_ids),
    }
    blocking = (
        "duplicate_event_ids",
        "missing_candidate_event_ids",
        "extra_outcome_event_ids",
        "unknown_statuses",
        "entry_before_plus1",
        "entry_after_plus3",
        "exit_at_or_before_entry",
        "post_cap_completed_exits",
        "nonfinite_completed_returns",
        "bad_target_holding",
        "bad_fallback_holding",
        "unknown_exit_reasons",
        "bad_target_execution_phase",
        "bad_h20_execution_phase",
        "noncompleted_exit_execution_phase",
        "bad_action_invalid_evidence",
        "unexpected_action_invalid_evidence",
        "bad_target_exit_price",
        "bad_open_target_limit_evidence",
        "bad_intraday_target_limit_evidence",
        "bad_h20_exit_price",
    )
    if audit["rows"] != audit["candidate_rows"] or any(audit[key] for key in blocking):
        raise ResearchError(f"outcome identity/execution audit failed: {audit}")
    if audit["candidate_event_id_set_sha256"] != audit["outcome_event_id_set_sha256"]:
        raise ResearchError("candidate/outcome event-id set digest mismatch")
    return audit


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    completed = frame.loc[frame.status.eq("COMPLETED")]
    values = pd.to_numeric(completed.net_return, errors="coerce")
    return {
        "signals": len(frame),
        "completed": len(completed),
        "decision_dates": int(frame.signal_date.nunique()),
        "symbols": int(frame.symbol.nunique()),
        "mean_net": None if completed.empty else float(values.mean()),
        "median_net": None if completed.empty else float(values.median()),
        "positive_rate": None if completed.empty else float(values.gt(0).mean()),
        "ge_4pct_rate": None if completed.empty else float(values.ge(0.04).mean()),
        "severe10_rate": None if completed.empty else float(values.le(-0.10).mean()),
        "target_hit_rate": None
        if completed.empty
        else float(completed.exit_reason.eq("TARGET_10").mean()),
        "mean_holding_sessions": None
        if completed.empty
        else float(completed.holding_sessions.mean()),
    }


def summarize(
    outcomes: pd.DataFrame,
    paths: pd.DataFrame,
    source_hashes: dict[str, str],
    path_audit: dict[str, Any],
    outcome_audit: dict[str, Any],
    paths_path: Path,
    outcomes_path: Path,
) -> dict[str, Any]:
    annual = {
        str(year): metrics(outcomes.loc[outcomes.signal_date.dt.year.eq(year)])
        for year in range(2014, 2021)
    }
    return {
        "experiment": EXPERIMENT,
        "stage": "SEPARATELY_AUTHORIZED_FROZEN_DEVELOPMENT_OUTCOME_ATTACHMENT",
        "asset_id": ASSET_ID,
        "authorization_id": AUTHORIZATION_ID,
        "authorized_arm": AUTHORIZED_ARM,
        "source_hashes": source_hashes,
        "future_paths_sha256": sha256(paths_path),
        "outcomes_sha256": sha256(outcomes_path),
        "path_audit": path_audit,
        "outcome_audit": outcome_audit,
        "status_counts": {
            str(key): int(value)
            for key, value in outcomes.status.value_counts(dropna=False).sort_index().items()
        },
        "exit_execution_phase_counts": {
            str(key): int(value)
            for key, value in outcomes.exit_execution_phase.value_counts(dropna=True)
            .sort_index()
            .items()
        },
        "overall": metrics(outcomes),
        "annual": annual,
        "maximum_signal_date": str(outcomes.signal_date.max().date()),
        "maximum_path_row_date": None if paths.empty else str(paths.trade_date.max().date()),
        "maximum_evaluation_path_date": str(MAX_PATH_DATE.date()),
        "target_return": TARGET_RETURN,
        "horizon_rule": (
            "on cal_idx > entry_cal_idx + 20, evaluate the open before the same-day high"
        ),
        "round_trip_cost": ROUND_TRIP_COST,
        "fallback_eligible_open_precedes_same_day_high": True,
        "fallback_day_conservative_semantics": (
            "sellable open at/above target fills only at exact target; sellable open "
            "below target exits immediately at open; only an unsellable open permits "
            "a later legal same-day high target touch"
        ),
        "intraday_target_limit_evidence_required": True,
        "unknown_corporate_action_state_invalidates_event": True,
        "canonical_stage_b_preexisted": False,
        "preexisting_v30_outcome_artifact_read": False,
        "post_2020_row_read": False,
        "portfolio_replay_performed": False,
        "charts_rendered": False,
        "all_bound_inputs_rehashed_immediately_before_publish": True,
        "next_action": (
            "OBTAIN_A_SEPARATE_RUNNER_BOUND_CHART_AUTHORIZATION_BEFORE_RENDERING_"
            "EVERY_FROZEN_CANDIDATE"
        ),
    }


def write_parquet(
    con: duckdb.DuckDBPyConnection,
    frame: pd.DataFrame,
    path: Path,
) -> None:
    con.register("output_frame", frame)
    try:
        con.execute(f"COPY output_frame TO '{sql_path(path)}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    finally:
        con.unregister("output_frame")


def main() -> None:
    if STAGE_B.exists():
        raise ResearchError(f"canonical Stage B already exists: {STAGE_B}")
    source_hashes, stage_a_result = verify_inputs()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".stage_b_staging_", dir=OUTPUT_ROOT))
    paths_path = staging / "future_paths.parquet"
    outcomes_path = staging / "outcomes.parquet"
    result_path = staging / "result.json"
    con: duckdb.DuckDBPyConnection | None = None
    try:
        candidates = load_candidates(stage_a_result)
        con = connect(staging / "duckdb_tmp")
        paths = build_paths(con, candidates, paths_path)
        path_audit = audit_paths(paths, candidates)
        outcomes = attach_outcomes(candidates, paths)
        outcome_audit = audit_outcomes(outcomes, candidates)
        write_parquet(con, outcomes, outcomes_path)
        con.close()
        con = None
        result = summarize(
            outcomes,
            paths,
            source_hashes,
            path_audit,
            outcome_audit,
            paths_path,
            outcomes_path,
        )
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        shutil.rmtree(staging / "duckdb_tmp", ignore_errors=True)
        final_hashes, _ = verify_inputs()
        if final_hashes != source_hashes:
            raise ResearchError("bound input identity changed during Stage-B execution")
        if STAGE_B.exists():
            raise ResearchError(f"canonical Stage B appeared before publish: {STAGE_B}")
        staging.rename(STAGE_B)
    except Exception:
        if con is not None:
            con.close()
        shutil.rmtree(staging, ignore_errors=True)
        raise
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
