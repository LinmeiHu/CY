#!/usr/bin/env python3
"""Render the separately authorized, frozen V31 development chart corpus.

The chronological review images deliberately hide every post-signal candle and
outcome label.  Full images are used only in the second, outcome-attribution
pass.  The pre-signal and post-signal panels also have independent price and
turnover scales so that a future move cannot change the apparent signal-time
shape.
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

EXPERIMENT = "ASHARE-INDUSTRY-RESIDUAL-SERIAL-PHASE-CHANGE-MOTHER-V31"
REPO = Path(__file__).resolve().parents[3]
EXP = REPO / "research/market_behavior_os_v2/experiments"
PARENT_SPEC = EXP / f"{EXPERIMENT}_freeze.json"
STAGE_B_SPEC = EXP / f"{EXPERIMENT}_stage_b_freeze.json"
REVIEW_SPEC = EXP / f"{EXPERIMENT}_visual_review_spec.json"
STAGE_A_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_industry_residual_serial_phase_change_mother_v31_stage_a.py"
)
STAGE_B_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_industry_residual_serial_phase_change_mother_v31_stage_b.py"
)
COORDINATE_BUILDER = REPO / (
    "research/market_behavior_os_v2/scripts/run_ashare_former_leader_strict_gap_reclaim_v3.py"
)
CY038_MANIFEST = EXP / "ASHARE-V31-CY038_DATA_ASSET_MANIFEST.json"
CHART_MANIFEST = EXP / "ASHARE-V31-CY039_CHART_REVIEW_ASSET_MANIFEST.json"
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
OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_industry_residual_serial_phase_change_mother_v31"
)
STAGE_A = OUTPUT_ROOT / "stage_a"
STAGE_B = OUTPUT_ROOT / "stage_b"
STAGE_A_RESULT = STAGE_A / "result.json"
REPRESENTATION = STAGE_A / "representation_panel.parquet"
CANDIDATES = STAGE_A / "candidates_frozen.parquet"
PREPARED = STAGE_B / "prepared_candidates.parquet"
FUTURE_PATHS = STAGE_B / "future_paths.parquet"
OUTCOMES = STAGE_B / "outcomes.parquet"
STAGE_B_RESULT = STAGE_B / "result.json"
CHART_ROOT = OUTPUT_ROOT / "stage_c_charts"

ASSET_ID = "CY-039"
DEPENDENCY_ASSET_ID = "CY-038"
AUTHORIZATION_ID = "CYQ-AUTH-ASHARE-RESIDUAL-SERIAL-V31-STAGE-C-CY039-CHART-REVIEW-2018-2020-V1"
AUTHORIZED_ARM = "V31_CY039_FROZEN_STAGE_C_CHART_REVIEW_ONLY"

FIXED_HASHES = {
    PARENT_SPEC: "d43d03bc04b26fbc0b79207c5d0598024f5d60921522e186283d523ed670c65c",
    STAGE_B_SPEC: "036b165d6fbeac85dd3af52b83365ead620fd2541d0ed76fe150a4636b7ab48a",
    STAGE_A_RUNNER: "620cb7b32c95e62d82b2bccf0638048f2522d36071da48273afabd66d1495f9a",
    STAGE_B_RUNNER: "af3248c0070d2440cf3c82f72c2459c430b7adef27c6fe613703b2e418ac2aa8",
    COORDINATE_BUILDER: "358b62014c52b7bf936937746223954512fe9451eaa5009063e14f39e1bb1787",
    CY038_MANIFEST: "86d6f448b938468c3e9bd106ec3086e3dd1665dc3ec053ac44cc1ee7fd79a2ed",
    CY006_MANIFEST: "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2",
    PARTITIONS[0]: "b906d2c21fd35128b8f65f1b00fa12ae6e5bd9ee476a368a63881304f38ceed4",
    PARTITIONS[1]: "c69a464e4a04efdca0177a8a09a13a34646531afa37a2b35b4892fd40ec3ebfd",
    PARTITIONS[2]: "1b0a00c6d2cfbce0ae4f907e1ee9dc5006f59677d556cc10f8f34a9893937c62",
    COORDINATE_STATE: "76fe88cb7509ae33a3d32b1bfd6d0c90560083127bdfaf63da1d7d24ec72bf60",
    STAGE_A_RESULT: "55c772d5c77ff4ee2c333aececa08d24a787dc3a4033952d7d2371e70ccba165",
    REPRESENTATION: "91f18e9ca0646a33ceb172ad45293ee4e4979f0b4e5ffce865dca9841249f62c",
    CANDIDATES: "0585a0da912626f6403a90e9345622cbf2c34fe6aeefec636ffa6276a13df9b8",
    PREPARED: "9184615d9c24b408c0895c17f0162aed39c0073c785a3df82e032b2698fe6f79",
    FUTURE_PATHS: "680dac2abdd6464383fc360b022194f388d74e2f2b6117697639b502c8c0f2b0",
    OUTCOMES: "d0ceeaee1e68f86eada2a2566a607aeba54163c005b48f998bf81d7b2a8e60de",
    STAGE_B_RESULT: "2c28f3b4ee1437d9dbdb1460792a72c09063d55067cdcb74aff918b58fb988b0",
}

EXPECTED_EVENTS = 1_602
WINDOW = 126
WINDOW_ROWS = 253
SIGNAL_START = pd.Timestamp("2018-07-31")
SIGNAL_END = pd.Timestamp("2020-06-30")
MIN_CHART_DATE = pd.Timestamp("2018-01-22")
MAX_CHART_DATE = pd.Timestamp("2020-12-31")
EXPECTED_GLOBAL_SIGNAL_MIN = 1_355
EXPECTED_GLOBAL_SIGNAL_MAX = 1_818
EXPECTED_LOCAL_TO_GLOBAL_OFFSET = 1_215
TARGET_RETURN = 0.10
HORIZON_SESSIONS = 20
ROUND_TRIP_COST = 0.004

CHART_SIZE = (720, 400)
HEADER_BOTTOM = 78
PRICE_TOP, PRICE_BOTTOM = 88, 304
VOLUME_TOP, VOLUME_BOTTOM = 320, 391
LEFT_EDGE, PRE_RIGHT = 34, 354
POST_LEFT, RIGHT_EDGE = 366, 712
GRID_COLUMNS = 5
GRID_ROWS = 5
PRE_PLOT_BOX = (LEFT_EDGE, PRICE_TOP, PRE_RIGHT + 1, VOLUME_BOTTOM + 1)

OUTCOME_BUCKETS = (
    "PROFIT_GE_4PCT",
    "PROFIT_0_TO_4PCT",
    "LOSS_0_TO_10PCT",
    "SEVERE_LOSS",
    "NO_COMPLETED_TRADE",
)
EXPECTED_BUCKET_COUNTS = {
    "PROFIT_GE_4PCT": 815,
    "PROFIT_0_TO_4PCT": 113,
    "LOSS_0_TO_10PCT": 421,
    "SEVERE_LOSS": 245,
    "NO_COMPLETED_TRADE": 8,
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
        raise ResearchError(f"{label} is not an object")
    return value


def only(items: list[dict[str, Any]], label: str) -> dict[str, Any]:
    if len(items) != 1:
        raise ResearchError(f"expected one {label}; found {len(items)}")
    return items[0]


def verify_preflight_authorization() -> tuple[dict[str, str], dict[str, Any]]:
    """Authorize Stage-B reads before opening any completed Stage-B artifact."""
    required = (REGISTRY, REVIEW_SPEC, CHART_MANIFEST, Path(__file__))
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ResearchError(f"missing Stage-C authorization input: {missing}")
    actual = {
        "registry": sha256(REGISTRY),
        "review_spec": sha256(REVIEW_SPEC),
        "chart_manifest": sha256(CHART_MANIFEST),
        "chart_runner": sha256(Path(__file__)),
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
    if (
        asset.get("status") != "RESEARCH_CONDITIONAL"
        or asset.get("pit_grade") != "B"
        or lineage.get("manifest_path") != str(CHART_MANIFEST.resolve())
        or lineage.get("manifest_sha256") != actual["chart_manifest"]
        or lineage.get("bounded_authorization_id") != AUTHORIZATION_ID
        or authorization.get("purpose") != "ASHARE_FROZEN_DEVELOPMENT_CHART_REVIEW"
        or authorization.get("asset_id") != ASSET_ID
        or authorization.get("dependency_asset_id") != DEPENDENCY_ASSET_ID
        or authorization.get("authorized_arms") != [AUTHORIZED_ARM]
        or authorization.get("charts_authorized") is not True
        or authorization.get("completed_stage_b_artifact_read_authorized") is not True
        or authorization.get("outcome_attachment_authorized") is not False
        or authorization.get("rule_aggregation_authorized") is not False
        or authorization.get("portfolio_replay_authorized") is not False
        or authorization.get("candidate_reselection_authorized") is not False
        or authorization.get("post_2020_read_authorized") is not False
        or scope.get("signal_start") != str(SIGNAL_START.date())
        or scope.get("signal_end") != str(SIGNAL_END.date())
        or scope.get("minimum_chart_date") != str(MIN_CHART_DATE.date())
        or scope.get("maximum_chart_date") != str(MAX_CHART_DATE.date())
        or scope.get("frozen_candidate_rows") != EXPECTED_EVENTS
        or protocol.get("path") != str(REVIEW_SPEC.resolve())
        or protocol.get("sha256") != actual["review_spec"]
        or protocol.get("runner_path") != str(Path(__file__).resolve())
        or protocol.get("runner_sha256") != actual["chart_runner"]
    ):
        raise ResearchError("CY-039 registry authorization semantics drift")

    spec = load_json(REVIEW_SPEC, "visual-review spec")
    renderer = spec.get("renderer", {})
    if (
        spec.get("experiment") != EXPERIMENT
        or spec.get("status") != "PRE_VISUAL_REVIEW_BUT_POST_STAGE_B_AGGREGATE"
        or spec.get("maximum_compressed_rules") != 0
        or renderer.get("path") != str(Path(__file__).relative_to(REPO))
        or renderer.get("sha256") != actual["chart_runner"]
    ):
        raise ResearchError("visual-review spec does not bind this renderer")

    manifest = load_json(CHART_MANIFEST, "CY-039 manifest")
    boundary = manifest.get("authorization_boundary", {})
    protocol_manifest = manifest.get("protocol", {})
    if (
        manifest.get("asset_id") != ASSET_ID
        or manifest.get("status") != "FROZEN_DEVELOPMENT_CHART_REVIEW_BOUNDED_INPUT"
        or boundary.get("authorization_id") != AUTHORIZATION_ID
        or boundary.get("charts_authorized") is not True
        or boundary.get("rule_aggregation_authorized") is not False
        or boundary.get("maximum_chart_date") != str(MAX_CHART_DATE.date())
        or protocol_manifest.get("visual_review_spec_sha256") != actual["review_spec"]
        or protocol_manifest.get("chart_runner_sha256") != actual["chart_runner"]
    ):
        raise ResearchError("CY-039 manifest semantics drift")
    return actual, authorization


def verify_bound_inputs(preflight: dict[str, str], authorization: dict[str, Any]) -> dict[str, str]:
    artifacts = {
        item.get("role"): item
        for item in authorization.get("bound_artifacts", [])
        if isinstance(item, dict)
    }
    roles = (
        ("cy006_manifest", CY006_MANIFEST),
        ("cy006_2018", PARTITIONS[0]),
        ("cy006_2019", PARTITIONS[1]),
        ("cy006_2020", PARTITIONS[2]),
        ("coordinate_state", COORDINATE_STATE),
        ("coordinate_builder", COORDINATE_BUILDER),
        ("parent_spec", PARENT_SPEC),
        ("stage_a_runner", STAGE_A_RUNNER),
        ("stage_a_result", STAGE_A_RESULT),
        ("stage_a_representation", REPRESENTATION),
        ("stage_a_candidates", CANDIDATES),
        ("stage_b_spec", STAGE_B_SPEC),
        ("stage_b_runner", STAGE_B_RUNNER),
        ("cy038_manifest", CY038_MANIFEST),
        ("stage_b_prepared_candidates", PREPARED),
        ("stage_b_future_paths", FUTURE_PATHS),
        ("stage_b_outcomes", OUTCOMES),
        ("stage_b_result", STAGE_B_RESULT),
    )
    actual = dict(preflight)
    for role, path in roles:
        if not path.is_file():
            raise ResearchError(f"missing bound input {role}: {path}")
        value = sha256(path)
        expected = FIXED_HASHES[path]
        item = artifacts.get(role)
        if value != expected:
            raise ResearchError(f"frozen input drift: {role}: {value} != {expected}")
        if item is None or item.get("path") != str(path.resolve()) or item.get("sha256") != value:
            raise ResearchError(f"CY-039 authorization does not bind {role}")
        actual[role] = value
    return actual


def require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ResearchError(f"{label} missing columns: {missing}")


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


def load_and_audit_identities() -> tuple[pd.DataFrame, pd.DataFrame]:
    candidates = pd.read_parquet(CANDIDATES)
    prepared = pd.read_parquet(PREPARED)
    outcomes = pd.read_parquet(OUTCOMES)
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
            "prior_serial_dependence",
            "recent_serial_dependence",
            "serial_phase_change",
            "current_residual_return",
            "raw_return_20",
            "raw_return_60",
            "return_volatility_60",
            "turnover_ratio_1_to_60",
        },
        "Stage-B prepared candidates",
    )
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
            "net_return",
        },
        "Stage-B outcomes",
    )
    for frame in (candidates, prepared, outcomes):
        frame["signal_date"] = pd.to_datetime(frame["signal_date"])
    for column in ("decision_at", "available_at"):
        prepared[column] = pd.to_datetime(prepared[column])
    for column in ("entry_date", "exit_date"):
        outcomes[column] = pd.to_datetime(outcomes[column])

    if any(
        len(frame) != EXPECTED_EVENTS
        or frame.event_id.isna().any()
        or frame.event_id.duplicated().any()
        for frame in (candidates, prepared, outcomes)
    ):
        raise ResearchError("frozen event count or identity drift")
    ids = set(candidates.event_id.astype(str))
    if ids != set(prepared.event_id.astype(str)) or ids != set(outcomes.event_id.astype(str)):
        raise ResearchError("Stage-A/prepared/outcome event sets differ")

    identity = prepared.merge(
        candidates[["event_id", "symbol", "causal_industry", "signal_date", "signal_cal_idx"]],
        on="event_id",
        suffixes=("_prepared", "_stage_a"),
        validate="one_to_one",
    ).merge(
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
        validate="one_to_one",
    )
    for field in ("symbol", "causal_industry", "signal_date"):
        if not identity[f"{field}_prepared"].eq(identity[f"{field}_stage_a"]).all():
            raise ResearchError(f"prepared/Stage-A identity drift: {field}")
        if not identity[f"{field}_prepared"].eq(identity[field]).all():
            raise ResearchError(f"prepared/outcome identity drift: {field}")
    if not identity.source_signal_cal_idx.eq(identity.signal_cal_idx_stage_a).all():
        raise ResearchError("prepared source_signal_cal_idx is not Stage-A local cal_idx")
    if not identity.signal_cal_idx_prepared.eq(identity.signal_cal_idx).all():
        raise ResearchError("prepared global signal_cal_idx differs from outcome")
    if not identity.invalid_step_cum.eq(identity.signal_invalid_step_cum).all():
        raise ResearchError("prepared/outcome signal lineage drift")
    if (
        not (identity.signal_cal_idx_prepared - identity.source_signal_cal_idx)
        .eq(EXPECTED_LOCAL_TO_GLOBAL_OFFSET)
        .all()
    ):
        raise ResearchError("local/global calendar offset drift")
    if (
        prepared.signal_cal_idx.min() != EXPECTED_GLOBAL_SIGNAL_MIN
        or prepared.signal_cal_idx.max() != EXPECTED_GLOBAL_SIGNAL_MAX
        or prepared.signal_date.min() != SIGNAL_START
        or prepared.signal_date.max() != SIGNAL_END
        or prepared.available_at.gt(prepared.decision_at).any()
    ):
        raise ResearchError("prepared signal chronology drift")
    if not set(outcomes.status.astype(str)).issubset(ALLOWED_STATUSES):
        raise ResearchError("unknown lifecycle status")
    if (
        not np.isclose(outcomes.target_return, TARGET_RETURN).all()
        or not outcomes.horizon_sessions.eq(HORIZON_SESSIONS).all()
        or not np.isclose(outcomes.round_trip_cost, ROUND_TRIP_COST).all()
    ):
        raise ResearchError("outcome target/horizon/cost drift")
    entered = outcomes.loc[outcomes.entry_cal_idx.notna()]
    completed = outcomes.loc[outcomes.status.eq("COMPLETED")]
    if (
        entered.entry_cal_idx.le(entered.signal_cal_idx).any()
        or entered.entry_cal_idx.gt(entered.signal_cal_idx + 3).any()
        or completed.exit_cal_idx.le(completed.entry_cal_idx).any()
        or completed.exit_cal_idx.gt(completed.signal_cal_idx + WINDOW).any()
        or completed.exit_date.gt(MAX_CHART_DATE).any()
    ):
        raise ResearchError("outcome markers violate chart chronology")
    stage_b = load_json(STAGE_B_RESULT, "Stage-B result")
    if (
        stage_b.get("stage") != "SEPARATELY_AUTHORIZED_FROZEN_DEVELOPMENT_OUTCOME_ATTACHMENT"
        or stage_b.get("post_2020_row_read") is not False
        or stage_b.get("charts_rendered") is not False
        or stage_b.get("portfolio_replay_performed") is not False
        or stage_b.get("prepared_candidates_sha256") != FIXED_HASHES[PREPARED]
        or stage_b.get("future_paths_sha256") != FIXED_HASHES[FUTURE_PATHS]
        or stage_b.get("outcomes_sha256") != FIXED_HASHES[OUTCOMES]
    ):
        raise ResearchError("Stage-B result state drift")
    return prepared, outcomes


def load_windows(prepared: pd.DataFrame) -> pd.DataFrame:
    connection = duckdb.connect()
    connection.execute("SET threads=4")
    connection.register(
        "chart_keys",
        prepared[["event_id", "symbol", "signal_date", "signal_cal_idx", "decision_at"]],
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
            k.decision_at AS signal_decision_at,c.trade_date,c.cal_idx,
            c.cal_idx-k.signal_cal_idx AS relative_session
          FROM chart_keys k JOIN calendar c
            ON c.cal_idx BETWEEN k.signal_cal_idx-{WINDOW} AND k.signal_cal_idx+{WINDOW}
        ), raw AS (
          SELECT * FROM read_parquet([{paths}], union_by_name=true)
          WHERE trade_date BETWEEN DATE '{MIN_CHART_DATE.date()}'
                               AND DATE '{MAX_CHART_DATE.date()}'
        ), coord AS (
          SELECT trade_date,cal_idx,symbol,adjusted_close,invalid_step_cum,current_valid,
            corporate_action_valid,corporate_action_blocking
          FROM read_parquet('{COORDINATE_STATE.as_posix()}')
          WHERE trade_date BETWEEN DATE '{MIN_CHART_DATE.date()}'
                               AND DATE '{MAX_CHART_DATE.date()}'
        )
        SELECT e.event_id,e.symbol,e.signal_date,e.signal_cal_idx,e.signal_decision_at,
          e.trade_date,e.cal_idx,e.relative_session,
          r.open*c.adjusted_close/r.close AS coord_open,
          r.high*c.adjusted_close/r.close AS coord_high,
          r.low*c.adjusted_close/r.close AS coord_low,c.adjusted_close AS coord_close,
          r.turnover_fraction,r.hard_valid,r.available_at,r.decision_at AS bar_decision_at,
          c.current_valid,c.corporate_action_valid,c.corporate_action_blocking,
          c.invalid_step_cum
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
    ):
        raise ResearchError("global +/-126 window coverage drift")
    signal = windows.loc[windows.relative_session.eq(0)]
    if (
        len(signal) != EXPECTED_EVENTS
        or signal.coord_close.isna().any()
        or not signal.trade_date.eq(signal.signal_date).all()
        or not signal.cal_idx.eq(signal.signal_cal_idx).all()
    ):
        raise ResearchError("one exact global signal bar is not present per event")
    numeric = windows[["coord_open", "coord_high", "coord_low", "coord_close"]].apply(
        pd.to_numeric, errors="coerce"
    )
    valid_pre = windows.loc[
        windows.relative_session.le(0)
        & windows.current_valid.fillna(False)
        & windows.hard_valid.fillna(False)
        & np.isfinite(numeric).all(axis=1)
        & numeric.gt(0).all(axis=1)
    ]
    if (
        valid_pre.available_at.isna().any()
        or valid_pre.available_at.gt(valid_pre.signal_decision_at).any()
    ):
        raise ResearchError("pre-signal chart row was unavailable at decision_at")
    return windows


def build_ledger(
    prepared: pd.DataFrame, outcomes: pd.DataFrame, windows: pd.DataFrame
) -> pd.DataFrame:
    outcome_lookup = {str(row.event_id): row for row in outcomes.itertuples(index=False)}
    window_lookup = {str(key): part for key, part in windows.groupby("event_id", sort=False)}
    ordered = prepared.sort_values(
        ["signal_date", "causal_industry", "symbol", "event_id"], kind="mergesort"
    )
    rows: list[dict[str, Any]] = []
    for chart_number, event in enumerate(ordered.itertuples(index=False), start=1):
        frame = valid_bars(window_lookup[str(event.event_id)])
        signal = frame.loc[frame.relative_session.eq(0)]
        pre = frame.loc[frame.relative_session.lt(0)]
        if len(signal) != 1 or pre.empty:
            raise ResearchError(f"{event.event_id}: signal/pre chart bars missing")
        outcome = outcome_lookup[str(event.event_id)]
        net = float(outcome.net_return) if pd.notna(outcome.net_return) else math.nan
        signal_close = float(signal.iloc[0].coord_close)
        prior_high = float(pre.coord_high.max())
        prior_low = float(pre.coord_low.min())
        rows.append(
            {
                "event_id": str(event.event_id),
                "chart_number": chart_number,
                "symbol": str(event.symbol),
                "signal_date": pd.Timestamp(event.signal_date),
                "signal_cal_idx": int(event.signal_cal_idx),
                "causal_industry": str(event.causal_industry),
                "prior_serial_dependence": float(event.prior_serial_dependence),
                "recent_serial_dependence": float(event.recent_serial_dependence),
                "serial_phase_change": float(event.serial_phase_change),
                "current_residual_return": float(event.current_residual_return),
                "raw_return_20": float(event.raw_return_20),
                "raw_return_60": float(event.raw_return_60),
                "return_volatility_60": float(event.return_volatility_60),
                "turnover_ratio_1_to_60": float(event.turnover_ratio_1_to_60),
                "pre126_return": signal_close / float(pre.iloc[0].coord_close) - 1,
                "pre126_drawdown_from_high": signal_close / prior_high - 1,
                "pre126_position": (signal_close - prior_low) / (prior_high - prior_low)
                if prior_high > prior_low
                else math.nan,
                "status": str(outcome.status),
                "entry_date": pd.Timestamp(outcome.entry_date)
                if pd.notna(outcome.entry_date)
                else pd.NaT,
                "entry_cal_idx": float(outcome.entry_cal_idx),
                "entry_price": float(outcome.entry_price),
                "target_price": float(outcome.target_price),
                "exit_date": pd.Timestamp(outcome.exit_date)
                if pd.notna(outcome.exit_date)
                else pd.NaT,
                "exit_cal_idx": float(outcome.exit_cal_idx),
                "exit_price": float(outcome.exit_price),
                "exit_reason": str(outcome.exit_reason) if pd.notna(outcome.exit_reason) else "",
                "net_return": net,
                "outcome_bucket": outcome_bucket(str(outcome.status), net),
            }
        )
    ledger = pd.DataFrame(rows)
    counts = ledger.outcome_bucket.value_counts().to_dict()
    if (
        ledger.event_id.duplicated().any()
        or set(ledger.event_id) != set(prepared.event_id.astype(str))
        or counts != EXPECTED_BUCKET_COUNTS
    ):
        raise ResearchError(f"review-ledger identity/outcome groups drift: {counts}")
    return ledger


def valid_bars(frame: pd.DataFrame) -> pd.DataFrame:
    numeric = frame[["coord_open", "coord_high", "coord_low", "coord_close"]].apply(
        pd.to_numeric, errors="coerce"
    )
    return frame.loc[
        frame.current_valid.fillna(False)
        & frame.hard_valid.fillna(False)
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
    if not values:
        raise ResearchError("cannot scale an empty chart panel")
    low, high = min(values), max(values)
    if not high > low:
        high = low * 1.01
    pad = (high - low) * 0.04
    return low - pad, high + pad


def _x(relative: int, pre: bool) -> int:
    if pre:
        return int(LEFT_EDGE + (relative + WINDOW) * (PRE_RIGHT - LEFT_EDGE) / WINDOW)
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
) -> tuple[tuple[float, float], dict[int, tuple[int, pd.Timestamp]]]:
    x0, x1 = (LEFT_EDGE, PRE_RIGHT) if pre else (POST_LEFT, RIGHT_EDGE)
    draw.rectangle((x0, PRICE_TOP, x1, VOLUME_BOTTOM), fill=background)
    draw.rectangle((x0, PRICE_TOP, x1, PRICE_BOTTOM), outline="#9ca3af")
    draw.rectangle((x0, VOLUME_TOP, x1, VOLUME_BOTTOM), outline="#d1d5db")
    price_values = list(bars.coord_low.astype(float)) + list(bars.coord_high.astype(float))
    scale = _scale(price_values)
    max_turnover = max(float(bars.turnover_fraction.fillna(0).max()), 1e-9)
    identity: dict[int, tuple[int, pd.Timestamp]] = {}
    for row in bars.itertuples(index=False):
        relative = int(row.relative_session)
        x = _x(relative, pre)
        identity[int(row.cal_idx)] = (relative, pd.Timestamp(row.trade_date))
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


def render_chart(event: pd.Series, frame: pd.DataFrame, output: Path, *, reveal_post: bool) -> None:
    image = Image.new("RGB", CHART_SIZE, "white")
    draw = ImageDraw.Draw(image)
    font, small = _font(12), _font(10)
    valid = valid_bars(frame)
    pre = valid.loc[valid.relative_session.le(0)]
    post = valid.loc[valid.relative_session.ge(1)]
    signal = pre.loc[pre.relative_session.eq(0)]
    if len(signal) != 1 or pre.empty:
        raise ResearchError(f"{event.event_id}: missing signal-time bars")
    pre_scale, _ = _draw_panel(draw, pre, pre=True, background="#eff6ff")
    draw.text(
        (LEFT_EDGE + 3, PRICE_TOP + 3),
        "SIGNAL-TIME <=t: PATTERN EVIDENCE",
        fill="#1d4ed8",
        font=small,
    )
    draw.text((LEFT_EDGE + 3, VOLUME_TOP + 2), "PRE scale", fill="#1d4ed8", font=small)
    signal_x = _x(0, True)
    signal_y = _y(float(signal.iloc[0].coord_close), pre_scale)
    draw.line((signal_x, PRICE_TOP, signal_x, VOLUME_BOTTOM), fill="#b45309", width=2)
    draw.text((signal_x - 35, signal_y - 13), "S close", fill="#92400e", font=small)

    if reveal_post:
        if post.empty:
            raise ResearchError(f"{event.event_id}: no post-signal chart bars")
        post_values = list(post.coord_low.astype(float)) + list(post.coord_high.astype(float))
        for field in ("entry_price", "target_price", "exit_price"):
            value = float(event[field])
            if math.isfinite(value):
                post_values.append(value)
        post_scale = _scale(post_values)
        _, post_identity = _draw_panel(draw, post, pre=False, background="#fff7ed")
        # Redraw using the expanded attribution scale when markers extend it.
        draw.rectangle((POST_LEFT, PRICE_TOP, RIGHT_EDGE, VOLUME_BOTTOM), fill="#fff7ed")
        draw.rectangle((POST_LEFT, PRICE_TOP, RIGHT_EDGE, PRICE_BOTTOM), outline="#9ca3af")
        draw.rectangle((POST_LEFT, VOLUME_TOP, RIGHT_EDGE, VOLUME_BOTTOM), outline="#d1d5db")
        max_turnover = max(float(post.turnover_fraction.fillna(0).max()), 1e-9)
        for row in post.itertuples(index=False):
            x = _x(int(row.relative_session), False)
            open_y = _y(float(row.coord_open), post_scale)
            close_y = _y(float(row.coord_close), post_scale)
            high_y = _y(float(row.coord_high), post_scale)
            low_y = _y(float(row.coord_low), post_scale)
            color = "#dc2626" if float(row.coord_close) >= float(row.coord_open) else "#16803c"
            draw.line((x, high_y, x, low_y), fill=color, width=1)
            body_top, body_bottom = sorted((open_y, close_y))
            draw.rectangle((x - 1, body_top, x + 1, max(body_top + 1, body_bottom)), fill=color)
            if pd.notna(row.turnover_fraction):
                height = int(
                    float(row.turnover_fraction) / max_turnover * (VOLUME_BOTTOM - VOLUME_TOP - 2)
                )
                draw.rectangle(
                    (x - 1, VOLUME_BOTTOM - height, x + 1, VOLUME_BOTTOM), fill="#9ca3af"
                )
        draw.text(
            (POST_LEFT + 3, PRICE_TOP + 3),
            "POST-SIGNAL >t: ATTRIBUTION ONLY",
            fill="#c2410c",
            font=small,
        )
        draw.text((POST_LEFT + 3, VOLUME_TOP + 2), "POST scale", fill="#c2410c", font=small)
        if math.isfinite(float(event.entry_cal_idx)):
            entry_idx = int(event.entry_cal_idx)
            marker = post_identity.get(entry_idx)
            if marker is None or marker[0] not in (1, 2, 3):
                raise ResearchError(f"{event.event_id}: entry marker outside legal chart bars")
            entry_x, entry_y = _x(marker[0], False), _y(float(event.entry_price), post_scale)
            _triangle(draw, entry_x, entry_y, True, "#7c3aed")
            draw.text((entry_x + 3, entry_y - 13), "E", fill="#7c3aed", font=small)
            target_y = _y(float(event.target_price), post_scale)
            for x in range(entry_x, RIGHT_EDGE + 1, 10):
                draw.line((x, target_y, min(x + 5, RIGHT_EDGE), target_y), fill="#f97316")
            draw.text((entry_x + 3, target_y - 13), "T +10%", fill="#c2410c", font=small)
        if event.status == "COMPLETED":
            exit_idx = int(event.exit_cal_idx)
            marker = post_identity.get(exit_idx)
            if marker is None or marker[0] < 1 or marker[0] > WINDOW:
                raise ResearchError(f"{event.event_id}: exit marker outside chart bars")
            exit_x, exit_y = _x(marker[0], False), _y(float(event.exit_price), post_scale)
            _triangle(draw, exit_x, exit_y, False, "#111827")
            draw.text(
                (exit_x + 3, exit_y + 4), f"X {event.exit_reason}", fill="#111827", font=small
            )
    else:
        draw.rectangle((POST_LEFT, PRICE_TOP, RIGHT_EDGE, VOLUME_BOTTOM), fill="#f3f4f6")
        draw.rectangle((POST_LEFT, PRICE_TOP, RIGHT_EDGE, VOLUME_BOTTOM), outline="#9ca3af")
        draw.text((POST_LEFT + 35, 185), "POST-SIGNAL MASKED", fill="#6b7280", font=font)
        draw.text(
            (POST_LEFT + 12, 204), "freeze signal-time labels first", fill="#6b7280", font=small
        )

    draw.text(
        (6, 4),
        f"{int(event.chart_number):05d} {event.symbol} "
        f"{pd.Timestamp(event.signal_date):%Y-%m-%d} {event.causal_industry}",
        fill="#111827",
        font=font,
    )
    draw.text(
        (6, 22),
        f"SIGNAL prior/recent/delta={event.prior_serial_dependence:+.2f}/"
        f"{event.recent_serial_dependence:+.2f}/{event.serial_phase_change:+.2f} "
        f"residual={event.current_residual_return:+.2%}",
        fill="#1e3a8a",
        font=small,
    )
    draw.text((6, 39), str(event.event_id), fill="#4b5563", font=small)
    if reveal_post:
        net = "NA" if not math.isfinite(float(event.net_return)) else f"{event.net_return:+.1%}"
        draw.text(
            (6, 56),
            f"POST status={event.status} bucket={event.outcome_bucket} net={net}",
            fill="#9a3412",
            font=small,
        )
    else:
        draw.text(
            (6, 56),
            "CHRONOLOGY PASS: outcome, entry, exit and future candles hidden",
            fill="#1d4ed8",
            font=small,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=False)


def render_worker(payload: tuple[dict[str, Any], pd.DataFrame, str, str]) -> dict[str, Any]:
    event_dict, frame, full_text, masked_text = payload
    event = pd.Series(event_dict)
    full, masked = Path(full_text), Path(masked_text)
    render_chart(event, frame, full, reveal_post=True)
    render_chart(event, frame, masked, reveal_post=False)
    return {
        "event_id": str(event.event_id),
        "chart_number": int(event.chart_number),
        "symbol": str(event.symbol),
        "signal_date": pd.Timestamp(event.signal_date),
        "outcome_bucket": str(event.outcome_bucket),
        "chart_path": str(full),
        "chart_sha256": sha256(full),
        "chronology_masked_chart_path": str(masked),
        "chronology_masked_chart_sha256": sha256(masked),
    }


def build_grids(
    frame: pd.DataFrame,
    output_dir: Path,
    *,
    label: str,
    collection: str,
    chart_path_column: str,
) -> tuple[list[Path], list[dict[str, Any]]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ordered = frame.reset_index(drop=True)
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
            f"{label} page {page:04d} charts {start + 1}-{start + len(part)}",
            fill="#111827",
            font=_font(13),
        )
        target = output_dir / f"sheet_{page:04d}.jpg"
        for slot, row in enumerate(part.itertuples(index=False), start=1):
            with Image.open(str(getattr(row, chart_path_column))) as chart:
                column = (slot - 1) % GRID_COLUMNS
                grid_row = (slot - 1) // GRID_COLUMNS
                sheet.paste(
                    chart.convert("RGB"), (column * CHART_SIZE[0], grid_row * CHART_SIZE[1] + 28)
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
    connection = duckdb.connect()
    connection.register("frame", frame)
    connection.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    connection.close()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def published_path(staging: Path, value: str) -> str:
    return str(CHART_ROOT / Path(value).relative_to(staging))


def run(workers: int) -> dict[str, Any]:
    if CHART_ROOT.exists():
        raise ResearchError(f"canonical Stage-C directory already exists: {CHART_ROOT}")
    preflight, authorization = verify_preflight_authorization()
    source_hashes = verify_bound_inputs(preflight, authorization)
    prepared, outcomes = load_and_audit_identities()
    windows = load_windows(prepared)
    ledger = build_ledger(prepared, outcomes, windows)
    staging = Path(tempfile.mkdtemp(prefix=".stage_c_charts.staging.", dir=OUTPUT_ROOT))
    try:
        full_dir = staging / "individual_charts"
        masked_dir = staging / "chronology_masked_charts"
        window_path = staging / "chart_window_panel.parquet"
        ledger_path = staging / "review_ledger.parquet"
        write_parquet(windows, window_path)
        write_parquet(ledger, ledger_path)
        ledger.to_csv(staging / "review_ledger.csv", index=False, float_format="%.10g")
        lookup = {str(key): part for key, part in windows.groupby("event_id", sort=False)}
        tasks = []
        for event in ledger.to_dict("records"):
            symbol = event["symbol"].replace(".", "_")
            signal_date = pd.Timestamp(event["signal_date"])
            stem = f"{int(event['chart_number']):05d}_{symbol}_{signal_date:%Y%m%d}.png"
            tasks.append(
                (
                    event,
                    lookup[str(event["event_id"])],
                    str(full_dir / stem),
                    str(masked_dir / stem),
                )
            )
        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            chart_index = pd.DataFrame(executor.map(render_worker, tasks))
        chart_index = chart_index.sort_values("chart_number", kind="mergesort")
        if (
            len(chart_index) != EXPECTED_EVENTS
            or chart_index.event_id.duplicated().any()
            or len(list(full_dir.glob("*.png"))) != EXPECTED_EVENTS
            or len(list(masked_dir.glob("*.png"))) != EXPECTED_EVENTS
        ):
            raise ResearchError("individual chart coverage drift")

        chronological, chrono_placements = build_grids(
            chart_index,
            staging / "chronological_masked_sheets",
            label="V31 CHRONOLOGY MASKED",
            collection="chronological_masked",
            chart_path_column="chronology_masked_chart_path",
        )
        outcome_sheets: list[Path] = []
        outcome_placements: list[dict[str, Any]] = []
        for bucket in OUTCOME_BUCKETS:
            subset = chart_index.loc[chart_index.outcome_bucket.eq(bucket)]
            sheets, placements = build_grids(
                subset,
                staging / "outcome_sheets" / bucket.lower(),
                label=f"V31 OUTCOME {bucket}",
                collection="outcome_group",
                chart_path_column="chart_path",
            )
            outcome_sheets.extend(sheets)
            outcome_placements.extend(placements)
        placements = pd.DataFrame(chrono_placements + outcome_placements)
        for collection in ("chronological_masked", "outcome_group"):
            part = placements.loc[placements.collection.eq(collection)]
            if (
                len(part) != EXPECTED_EVENTS
                or part.event_id.duplicated().any()
                or set(part.event_id) != set(ledger.event_id)
            ):
                raise ResearchError(f"{collection} exactly-once coverage drift")
        if len(chronological) != 65 or len(outcome_sheets) != 66:
            raise ResearchError("contact-sheet count drift")
        placements["sheet_path"] = placements.sheet_path.map(
            lambda value: published_path(staging, value)
        )
        placements.to_csv(staging / "contact_sheet_placements.csv", index=False)
        sheet_index = (
            placements.groupby(["collection", "sheet_path"], as_index=False)
            .agg(
                sheet_number=("sheet_number", "first"),
                charts=("event_id", "size"),
                first_chart=("chart_number", "min"),
                last_chart=("chart_number", "max"),
            )
            .sort_values(["collection", "sheet_path"], kind="mergesort")
        )
        if len(sheet_index) != 131 or not sheet_index.charts.between(1, 25).all():
            raise ResearchError("contact-sheet index drift")
        sheet_index["sheet_sha256"] = sheet_index.sheet_path.map(
            lambda value: sha256(staging / Path(value).relative_to(CHART_ROOT))
        )
        sheet_index.to_csv(staging / "contact_sheet_index.csv", index=False)

        chart_index["chart_path"] = chart_index.chart_path.map(
            lambda value: published_path(staging, value)
        )
        chart_index["chronology_masked_chart_path"] = chart_index.chronology_masked_chart_path.map(
            lambda value: published_path(staging, value)
        )
        chart_index.to_csv(staging / "chart_index.csv", index=False)

        chronology_template = ledger[
            ["event_id", "chart_number", "symbol", "signal_date", "causal_industry"]
        ].copy()
        chronology_template["chronology_reviewed"] = False
        for column in (
            "signal_time_trend_structure",
            "signal_time_level_location",
            "signal_time_turnover_structure",
            "signal_candle_structure",
            "signal_time_pattern_note",
            "chronology_reviewer",
        ):
            chronology_template[column] = ""
        chronology_template["post_signal_used_as_predictor"] = False
        chronology_template.to_csv(staging / "chronology_review_template.csv", index=False)

        outcome_template = ledger[["event_id", "chart_number", "outcome_bucket"]].copy()
        outcome_template["outcome_group_reviewed"] = False
        for column in (
            "post_signal_attribution",
            "profit_loss_group_observation",
            "counterexample_flag",
            "counterexample_to_motif_ids",
            "outcome_reviewer",
            "reviewer_notes",
        ):
            outcome_template[column] = ""
        outcome_template["post_signal_used_as_predictor"] = False
        outcome_template.to_csv(staging / "outcome_review_template.csv", index=False)

        if verify_bound_inputs(*verify_preflight_authorization()) != source_hashes:
            raise ResearchError("bound input changed during Stage-C construction")
        manifest = {
            "experiment": EXPERIMENT,
            "stage": "SEPARATELY_AUTHORIZED_FROZEN_DEVELOPMENT_CHART_CORPUS",
            "asset_id": ASSET_ID,
            "authorization_id": AUTHORIZATION_ID,
            "authorized_arm": AUTHORIZED_ARM,
            "source_hashes": source_hashes,
            "events": EXPECTED_EVENTS,
            "individual_full_charts": EXPECTED_EVENTS,
            "chronology_masked_charts": EXPECTED_EVENTS,
            "chronological_contact_sheets": len(chronological),
            "outcome_contact_sheets": len(outcome_sheets),
            "window_relative_sessions": [-WINDOW, WINDOW],
            "window_slots_per_event": WINDOW_ROWS,
            "minimum_chart_date": str(windows.trade_date.min().date()),
            "maximum_chart_date": str(windows.trade_date.max().date()),
            "outcome_bucket_counts": EXPECTED_BUCKET_COUNTS,
            "review_ledger_sha256": sha256(ledger_path),
            "chart_window_panel_sha256": sha256(window_path),
            "chart_index_sha256": sha256(staging / "chart_index.csv"),
            "contact_sheet_placements_sha256": sha256(staging / "contact_sheet_placements.csv"),
            "contact_sheet_index_sha256": sha256(staging / "contact_sheet_index.csv"),
            "chronology_review_template_sha256": sha256(staging / "chronology_review_template.csv"),
            "outcome_review_template_sha256": sha256(staging / "outcome_review_template.csv"),
            "post_2020_row_read": False,
            "outcome_attachment_performed": False,
            "rule_search_performed": False,
            "rule_aggregation_performed": False,
            "portfolio_replay_performed": False,
            "candidate_reselection_performed": False,
            "individual_coverage_exactly_once": True,
            "chronological_coverage_exactly_once": True,
            "outcome_group_coverage_exactly_once": True,
            "blue_region_scale_post_signal_independent": True,
            "chronology_pass_post_signal_masked": True,
            "post_signal_used_as_predictor": False,
            "next_step": "COMPLETE_AND_HASH_CHRONOLOGY_REVIEW_BEFORE_OPENING_OUTCOME_GROUP_SHEETS",
        }
        write_json(staging / "manifest.json", manifest)
        if CHART_ROOT.exists():
            raise ResearchError(f"canonical Stage-C directory appeared: {CHART_ROOT}")
        staging.replace(CHART_ROOT)
        return manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--verify-inputs", action="store_true")
    args = parser.parse_args()
    preflight, authorization = verify_preflight_authorization()
    hashes = verify_bound_inputs(preflight, authorization)
    if args.verify_inputs:
        print(json.dumps({"verified": True, "source_hashes": hashes}, indent=2, sort_keys=True))
        return
    print(json.dumps(run(args.workers), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
