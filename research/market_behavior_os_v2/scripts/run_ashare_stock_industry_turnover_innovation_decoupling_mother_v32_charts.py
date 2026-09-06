#!/usr/bin/env python3
"""Render only the anonymous, outcome-masked V32 Phase-1 chart corpus.

This runner never parses a V32 outcome or a post-signal bar.  It exposes only
an opaque chart number and the causal signal-through-t candlestick path.  A
separate, future Phase-2 specification may bind the frozen Phase-1 annotation
hash before any outcome chart is created.
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

EXPERIMENT = "ASHARE-STOCK-INDUSTRY-TURNOVER-INNOVATION-DECOUPLING-MOTHER-V32"
REPO = Path(__file__).resolve().parents[3]
EXP = REPO / "research/market_behavior_os_v2/experiments"
PARENT_SPEC = EXP / f"{EXPERIMENT}_freeze.json"
STAGE_B_SPEC = EXP / f"{EXPERIMENT}_stage_b_freeze.json"
REVIEW_SPEC = EXP / f"{EXPERIMENT}_visual_review_spec.json"
ANNOTATION_SCHEMA = EXP / "ASHARE-V32_phase1_anonymous_annotation_schema.json"
STAGE_A_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_stock_industry_turnover_innovation_decoupling_mother_v32_stage_a.py"
)
STAGE_B_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_stock_industry_turnover_innovation_decoupling_mother_v32_stage_b.py"
)
PHASE1_FINALIZER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "finalize_ashare_stock_industry_turnover_innovation_decoupling_mother_v32_phase1.py"
)
COORDINATE_BUILDER = REPO / (
    "research/market_behavior_os_v2/scripts/run_ashare_former_leader_strict_gap_reclaim_v3.py"
)
CY042_MANIFEST = EXP / "ASHARE-V32-CY042_DATA_ASSET_MANIFEST.json"
CHART_MANIFEST = EXP / "ASHARE-V32-CY043_CHART_REVIEW_ASSET_MANIFEST.json"
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
    "/Volumes/quant/CY_quant_research/ashare_stock_industry_turnover_innovation_decoupling_mother_v32"
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
CHART_ROOT = OUTPUT_ROOT / "stage_c_phase1_masked_charts"

ASSET_ID = "CY-043"
DEPENDENCY_ASSET_ID = "CY-042"
AUTHORIZATION_ID = (
    "CYQ-AUTH-ASHARE-TURNOVER-INNOVATION-DECOUPLING-"
    "V32-STAGE-C-CY043-CHART-REVIEW-2018-2020-V1"
)
AUTHORIZED_ARM = "V32_CY043_FROZEN_STAGE_C_CHART_REVIEW_ONLY"

FIXED_HASHES = {
    PARENT_SPEC: "d389cda8f743441a4c46df61a2c044169f33550d05a5153bb96bea5abab75089",
    STAGE_B_SPEC: "23103c3910a83416da52ec149135731a2589782bd539967cab630e39ee041d9b",
    STAGE_A_RUNNER: "a892ce53141c835ee6573427d97d12629ebffbaa869b5a5b789d5f33c6292054",
    STAGE_B_RUNNER: "fc28f2be60d683ef66d7d33b7baba65043390c9b893d1410e7f004c3a56c97c5",
    ANNOTATION_SCHEMA: "0b2aa65e71d460439149e80538d0d317bcce8b6f1d2c43a4168c928321402c43",
    PHASE1_FINALIZER: "cfd9fb199e73c8d4b42ab1b767fbb782b18acb15de05dedce5fd4884ee995b2a",
    COORDINATE_BUILDER: "358b62014c52b7bf936937746223954512fe9451eaa5009063e14f39e1bb1787",
    CY042_MANIFEST: "3af0ab075604cf0adb7405e821cf8594d9bc1ec22d70b5bce8395bef19baf4df",
    CY006_MANIFEST: "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2",
    PARTITIONS[0]: "b906d2c21fd35128b8f65f1b00fa12ae6e5bd9ee476a368a63881304f38ceed4",
    PARTITIONS[1]: "c69a464e4a04efdca0177a8a09a13a34646531afa37a2b35b4892fd40ec3ebfd",
    PARTITIONS[2]: "1b0a00c6d2cfbce0ae4f907e1ee9dc5006f59677d556cc10f8f34a9893937c62",
    COORDINATE_STATE: "76fe88cb7509ae33a3d32b1bfd6d0c90560083127bdfaf63da1d7d24ec72bf60",
    STAGE_A_RESULT: "db6dd269340e7bed1153ca160492b91f6aaedd0b44aee853e447a8f8aa4c96f4",
    REPRESENTATION: "1a67e4dfcd4cc6e20000be3890d12e37f8a91da5afa47aaf8b84960d2bf7c13d",
    CANDIDATES: "4d57fafc3418bc7923e747910add5f503313582e0b0ef9d5e8bdb4a92dcf539d",
    PREPARED: "491c8089b36907777903256d932383710b1105ad540f5109fb1a23c778a99ec5",
}

# Frozen now for a future, separately authorized Phase 2.  Phase 1 records
# these identities in its spec/manifest but deliberately does not open them.
BLOCKED_PHASE2_HASHES = {
    STAGE_B_RESULT: "64cb4c19b38968bb0b59cb7f0bc2a4f16bd58a3c6af2f31c7e01cd95569bf2f7",
    FUTURE_PATHS: "4d06ccb23bbf660d17f4f58fc3140364ed5fc9b9213b3cd4f2f0b69752068377",
    OUTCOMES: "9c016be56517d08419ceeca2c16da055ede39acca35aa253d90bfbe8c166ecfa",
}

EXPECTED_EVENTS = 1_781
WINDOW = 126
WINDOW_ROWS = 127
SIGNAL_START = pd.Timestamp("2018-07-31")
SIGNAL_END = pd.Timestamp("2020-06-30")
MIN_CHART_DATE = pd.Timestamp("2018-01-22")
MAX_PHASE1_SOURCE_DATE = SIGNAL_END
RESERVED_PHASE2_MAX_DATE = pd.Timestamp("2020-12-31")
EXPECTED_GLOBAL_SIGNAL_MIN = 1_355
EXPECTED_GLOBAL_SIGNAL_MAX = 1_818
EXPECTED_LOCAL_TO_GLOBAL_OFFSET = 1_215
OPAQUE_ORDER_SALT = "V32_PHASE1_MASKED_ORDER_V1"

CHART_SIZE = (720, 400)
HEADER_BOTTOM = 78
PRICE_TOP, PRICE_BOTTOM = 88, 304
VOLUME_TOP, VOLUME_BOTTOM = 320, 391
LEFT_EDGE, PRE_RIGHT = 34, 712
RIGHT_EDGE = 712
GRID_COLUMNS = 5
GRID_ROWS = 5


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
    """Authorize the masked Phase-1 arm before opening prepared identities."""
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
        or authorization.get("phase1_masked_charts_authorized") is not True
        or authorization.get("stage_b_prepared_candidates_read_authorized") is not True
        or authorization.get("outcome_artifact_parse_authorized") is not False
        or authorization.get("post_signal_row_read_authorized") is not False
        or authorization.get("full_charts_authorized") is not False
        or authorization.get("outcome_grouping_authorized") is not False
        or authorization.get("identity_reveal_authorized") is not False
        or authorization.get("phase2_authorized") is not False
        or authorization.get("outcome_attachment_authorized") is not False
        or authorization.get("rule_aggregation_authorized") is not False
        or authorization.get("portfolio_replay_authorized") is not False
        or authorization.get("candidate_reselection_authorized") is not False
        or authorization.get("post_2020_read_authorized") is not False
        or scope.get("signal_start") != str(SIGNAL_START.date())
        or scope.get("signal_end") != str(SIGNAL_END.date())
        or scope.get("minimum_chart_date") != str(MIN_CHART_DATE.date())
        or scope.get("maximum_chart_date") != str(MAX_PHASE1_SOURCE_DATE.date())
        or scope.get("frozen_candidate_rows") != EXPECTED_EVENTS
        or protocol.get("path") != str(REVIEW_SPEC.resolve())
        or protocol.get("sha256") != actual["review_spec"]
        or protocol.get("runner_path") != str(Path(__file__).resolve())
        or protocol.get("runner_sha256") != actual["chart_runner"]
    ):
        raise ResearchError("CY-043 registry authorization semantics drift")

    spec = load_json(REVIEW_SPEC, "visual-review spec")
    renderer = spec.get("renderer", {})
    freeze_tooling = spec.get("phase1_annotation_freeze_tooling", {})
    if (
        spec.get("experiment") != EXPERIMENT
        or spec.get("stage") != "STAGE_C_PHASE1_ANONYMOUS_MASKED_REVIEW"
        or spec.get("status") != "FROZEN_BEFORE_PHASE1_RENDER_AND_ANNOTATION"
        or spec.get("maximum_compressed_rules") != 0
        or renderer.get("path") != str(Path(__file__).relative_to(REPO))
        or renderer.get("sha256") != actual["chart_runner"]
        or freeze_tooling.get("schema_path") != str(ANNOTATION_SCHEMA.relative_to(REPO))
        or freeze_tooling.get("schema_sha256") != FIXED_HASHES[ANNOTATION_SCHEMA]
        or freeze_tooling.get("finalizer_path") != str(PHASE1_FINALIZER.relative_to(REPO))
        or freeze_tooling.get("finalizer_sha256") != FIXED_HASHES[PHASE1_FINALIZER]
    ):
        raise ResearchError("visual-review spec does not bind this renderer")

    manifest = load_json(CHART_MANIFEST, "CY-043 manifest")
    boundary = manifest.get("authorization_boundary", {})
    protocol_manifest = manifest.get("protocol", {})
    if (
        manifest.get("asset_id") != ASSET_ID
        or manifest.get("status") != "FROZEN_DEVELOPMENT_CHART_REVIEW_BOUNDED_INPUT"
        or boundary.get("authorization_id") != AUTHORIZATION_ID
        or boundary.get("charts_authorized") is not True
        or boundary.get("phase1_masked_charts_authorized") is not True
        or boundary.get("outcome_artifact_parse_authorized") is not False
        or boundary.get("full_charts_authorized") is not False
        or boundary.get("phase2_authorized") is not False
        or boundary.get("rule_aggregation_authorized") is not False
        or boundary.get("maximum_chart_date") != str(MAX_PHASE1_SOURCE_DATE.date())
        or protocol_manifest.get("visual_review_spec_sha256") != actual["review_spec"]
        or protocol_manifest.get("chart_runner_sha256") != actual["chart_runner"]
    ):
        raise ResearchError("CY-043 manifest semantics drift")
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
        ("phase1_annotation_schema", ANNOTATION_SCHEMA),
        ("phase1_annotation_finalizer", PHASE1_FINALIZER),
        ("cy042_manifest", CY042_MANIFEST),
        ("stage_b_prepared_candidates", PREPARED),
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
            raise ResearchError(f"CY-043 authorization does not bind {role}")
        actual[role] = value
    # These identities are reserved for a separately frozen Phase 2.  Verify
    # only the authorization's declared path/hash strings: do not open or hash
    # an outcome-bearing file during Phase 1.
    for role, path in (
        ("stage_b_result", STAGE_B_RESULT),
        ("stage_b_future_paths", FUTURE_PATHS),
        ("stage_b_outcomes", OUTCOMES),
    ):
        item = artifacts.get(role)
        expected = BLOCKED_PHASE2_HASHES[path]
        if (
            item is None
            or item.get("path") != str(path.resolve())
            or item.get("sha256") != expected
        ):
            raise ResearchError(f"CY-043 does not reserve frozen Phase-2 identity {role}")
        actual[f"{role}_declared_sha256_only"] = expected
    return actual


def require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ResearchError(f"{label} missing columns: {missing}")


def load_and_audit_identities() -> pd.DataFrame:
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
            "history_endpoint_count",
            "coupling_pair_count",
            "minimum_other_peer_count",
            "industry_exact_history_n",
            "rho_40",
            "rho_60",
            "rho_80",
            "independence_d40",
            "independence_d60",
            "independence_d80",
            "current_turnover_innovation",
            "turnover_to_prior20_median",
            "mean_turnover_20_to_60",
            "raw_return_20",
            "raw_return_60",
            "return_volatility_60",
        },
        "Stage-B prepared candidates",
    )
    for frame in (candidates, prepared):
        frame["signal_date"] = pd.to_datetime(frame["signal_date"])
    for column in ("decision_at", "available_at"):
        prepared[column] = pd.to_datetime(prepared[column])
    for column in ("execution_raw_signal_date", "coordinate_signal_date"):
        prepared[column] = pd.to_datetime(prepared[column])
    if any(
        len(frame) != EXPECTED_EVENTS
        or frame.event_id.isna().any()
        or frame.event_id.duplicated().any()
        for frame in (candidates, prepared)
    ):
        raise ResearchError("frozen event count or identity drift")
    ids = set(candidates.event_id.astype(str))
    if ids != set(prepared.event_id.astype(str)):
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
        raise ResearchError("prepared source_signal_cal_idx is not Stage-A local cal_idx")
    if (
        not prepared.execution_raw_signal_date.eq(prepared.signal_date).all()
        or not prepared.coordinate_signal_date.eq(prepared.signal_date).all()
        or not prepared.execution_raw_industry.eq(prepared.causal_industry).all()
    ):
        raise ResearchError("prepared V32 date or PIT-industry identity drift")
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
    v32_numeric = prepared[
        [
            "rho_40",
            "rho_60",
            "rho_80",
            "independence_d40",
            "independence_d60",
            "independence_d80",
            "current_turnover_innovation",
            "turnover_to_prior20_median",
            "mean_turnover_20_to_60",
        ]
    ].apply(pd.to_numeric, errors="coerce")
    if (
        not np.isfinite(v32_numeric).all(axis=None)
        or not v32_numeric[
            ["independence_d40", "independence_d60", "independence_d80"]
        ].ge(0).all(axis=None)
        or not v32_numeric[
            ["independence_d40", "independence_d60", "independence_d80"]
        ].le(1).all(axis=None)
        or not prepared.history_endpoint_count.eq(83).all()
        or not prepared.coupling_pair_count.eq(80).all()
        or prepared.minimum_other_peer_count.lt(10).any()
        or prepared.industry_exact_history_n.lt(10).any()
    ):
        raise ResearchError("prepared V32 representation contract drift")
    return prepared


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
                               AND DATE '{MAX_PHASE1_SOURCE_DATE.date()}'
          GROUP BY trade_date,cal_idx
        ), expanded AS (
          SELECT k.event_id,k.symbol,k.signal_date,k.signal_cal_idx,
            k.decision_at AS signal_decision_at,c.trade_date,c.cal_idx,
            c.cal_idx-k.signal_cal_idx AS relative_session
          FROM chart_keys k JOIN calendar c
            ON c.cal_idx BETWEEN k.signal_cal_idx-{WINDOW} AND k.signal_cal_idx
        ), raw AS (
          SELECT * FROM read_parquet([{paths}], union_by_name=true)
          WHERE trade_date BETWEEN DATE '{MIN_CHART_DATE.date()}'
                               AND DATE '{MAX_PHASE1_SOURCE_DATE.date()}'
        ), coord AS (
          SELECT trade_date,cal_idx,symbol,adjusted_close,invalid_step_cum,current_valid,
            corporate_action_valid,corporate_action_blocking
          FROM read_parquet('{COORDINATE_STATE.as_posix()}')
          WHERE trade_date BETWEEN DATE '{MIN_CHART_DATE.date()}'
                               AND DATE '{MAX_PHASE1_SOURCE_DATE.date()}'
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
        or not counts["last"].eq(0).all()
        or windows.duplicated(["event_id", "cal_idx"]).any()
        or windows.trade_date.min() != MIN_CHART_DATE
        or windows.trade_date.max() != MAX_PHASE1_SOURCE_DATE
    ):
        raise ResearchError("global signal-minus-126 through signal window coverage drift")
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
        or valid_pre.bar_decision_at.isna().any()
        or valid_pre.bar_decision_at.gt(valid_pre.signal_decision_at).any()
    ):
        raise ResearchError("pre-signal chart row was unavailable at decision_at")
    return windows


def build_in_memory_blind_order(prepared: pd.DataFrame, windows: pd.DataFrame) -> pd.DataFrame:
    """Assign opaque chart numbers without persisting an identity crosswalk."""
    window_ids = set(windows.event_id.astype(str))
    ordered = prepared.copy()
    ordered["event_id"] = ordered.event_id.astype(str)
    ordered["_blind_sort_digest"] = ordered.event_id.map(
        lambda value: hashlib.sha256(
            f"{OPAQUE_ORDER_SALT}|{value}".encode()
        ).hexdigest()
    )
    ordered["blind_chart_id"] = "B-" + ordered._blind_sort_digest.str.slice(0, 20)
    ordered = ordered.sort_values(
        ["_blind_sort_digest", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    ordered.insert(0, "chart_number", np.arange(1, len(ordered) + 1, dtype=np.int64))
    expected_numbers = list(range(1, EXPECTED_EVENTS + 1))
    if (
        len(ordered) != EXPECTED_EVENTS
        or ordered.event_id.duplicated().any()
        or ordered.blind_chart_id.duplicated().any()
        or ordered.chart_number.tolist() != expected_numbers
        or set(ordered.event_id) != window_ids
    ):
        raise ResearchError("deterministic blind order coverage drift")
    return ordered


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


def _x(relative: int) -> int:
    if relative < -WINDOW or relative > 0:
        raise ResearchError(f"Phase-1 relative session outside [-{WINDOW},0]: {relative}")
    return int(LEFT_EDGE + (relative + WINDOW) * (PRE_RIGHT - LEFT_EDGE) / WINDOW)


def _y(value: float, scale: tuple[float, float]) -> int:
    low, high = scale
    return int(PRICE_BOTTOM - (value - low) * (PRICE_BOTTOM - PRICE_TOP) / (high - low))


def _draw_phase1_panel(
    draw: ImageDraw.ImageDraw, bars: pd.DataFrame
) -> tuple[float, float]:
    draw.rectangle((LEFT_EDGE, PRICE_TOP, RIGHT_EDGE, VOLUME_BOTTOM), fill="#eff6ff")
    draw.rectangle((LEFT_EDGE, PRICE_TOP, RIGHT_EDGE, PRICE_BOTTOM), outline="#9ca3af")
    draw.rectangle((LEFT_EDGE, VOLUME_TOP, RIGHT_EDGE, VOLUME_BOTTOM), outline="#d1d5db")
    price_values = list(bars.coord_low.astype(float)) + list(bars.coord_high.astype(float))
    scale = _scale(price_values)
    max_turnover = max(float(bars.turnover_fraction.fillna(0).max()), 1e-9)
    for row in bars.itertuples(index=False):
        relative = int(row.relative_session)
        x = _x(relative)
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
    return scale


def render_chart(
    chart_number: int, blind_chart_id: str, frame: pd.DataFrame, output: Path
) -> None:
    """Render one anonymous causal chart; no identity or outcome enters the image."""
    if frame.relative_session.gt(0).any():
        raise ResearchError(f"chart {chart_number:05d}: post-signal row reached renderer")
    image = Image.new("RGB", CHART_SIZE, "white")
    draw = ImageDraw.Draw(image)
    font, small = _font(12), _font(10)
    bars = valid_bars(frame)
    signal = bars.loc[bars.relative_session.eq(0)]
    if len(signal) != 1 or bars.empty:
        raise ResearchError(f"chart {chart_number:05d}: missing signal-time bars")
    scale = _draw_phase1_panel(draw, bars)
    draw.text(
        (LEFT_EDGE + 3, PRICE_TOP + 3),
        "CAUSAL WINDOW: GLOBAL SESSIONS -126 THROUGH 0",
        fill="#1d4ed8",
        font=small,
    )
    draw.text(
        (LEFT_EDGE + 3, VOLUME_TOP + 2),
        "TURNOVER | SCALE PER CHART",
        fill="#1d4ed8",
        font=small,
    )
    for relative in (-126, -63, 0):
        x = _x(relative)
        draw.text(
            (max(LEFT_EDGE, x - 12), PRICE_BOTTOM + 2),
            str(relative),
            fill="#4b5563",
            font=small,
        )
    signal_x = _x(0)
    signal_y = _y(float(signal.iloc[0].coord_close), scale)
    draw.line((signal_x, PRICE_TOP, signal_x, VOLUME_BOTTOM), fill="#b45309", width=2)
    draw.text((signal_x - 42, signal_y - 13), "SIGNAL", fill="#92400e", font=small)
    draw.text(
        (6, 4),
        f"CHART {chart_number:05d} | {blind_chart_id}",
        fill="#111827",
        font=font,
    )
    draw.text(
        (6, 22),
        "OPAQUE ORDER | SYMBOL / DATE / INDUSTRY / EVENT ID HIDDEN",
        fill="#1e3a8a",
        font=small,
    )
    draw.text(
        (6, 39),
        "ONLY OBSERVATIONS AVAILABLE BY SIGNAL-TIME CLOSE ARE SHOWN",
        fill="#1d4ed8",
        font=small,
    )
    draw.text((6, 56), "NO POST-SIGNAL ROW WAS READ", fill="#1d4ed8", font=small)
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


def build_grids(
    frame: pd.DataFrame,
    output_dir: Path,
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
            f"V32 PHASE-1 OPAQUE MASKED | PAGE {page:04d} | "
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
                    chart.convert("RGB"), (column * CHART_SIZE[0], grid_row * CHART_SIZE[1] + 28)
                )
            placements.append(
                {
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def run(workers: int) -> dict[str, Any]:
    if CHART_ROOT.exists():
        raise ResearchError(f"canonical Stage-C directory already exists: {CHART_ROOT}")
    preflight, authorization = verify_preflight_authorization()
    source_hashes = verify_bound_inputs(preflight, authorization)
    prepared = load_and_audit_identities()
    windows = load_windows(prepared)
    blind_order = build_in_memory_blind_order(prepared, windows)
    staging = Path(tempfile.mkdtemp(prefix=".stage_c_charts.staging.", dir=OUTPUT_ROOT))
    try:
        masked_dir = staging / "individual_masked_charts"
        lookup = {str(key): part for key, part in windows.groupby("event_id", sort=False)}
        tasks = []
        for event in blind_order.itertuples(index=False):
            stem = f"{event.blind_chart_id}.png"
            tasks.append(
                (
                    int(event.chart_number),
                    str(event.blind_chart_id),
                    lookup[str(event.event_id)],
                    str(masked_dir / stem),
                )
            )
        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            chart_index = pd.DataFrame(executor.map(render_worker, tasks))
        chart_index = chart_index.sort_values("chart_number", kind="mergesort")
        if (
            len(chart_index) != EXPECTED_EVENTS
            or chart_index.chart_number.duplicated().any()
            or chart_index.blind_chart_id.duplicated().any()
            or len(list(masked_dir.glob("*.png"))) != EXPECTED_EVENTS
        ):
            raise ResearchError("individual chart coverage drift")

        sheets, placements_list = build_grids(
            chart_index,
            staging / "masked_contact_sheets",
        )
        placements = pd.DataFrame(placements_list)
        if (
            len(placements) != EXPECTED_EVENTS
            or placements.chart_number.duplicated().any()
            or placements.blind_chart_id.duplicated().any()
            or len(sheets) != 72
        ):
            raise ResearchError("contact-sheet count drift")
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
        )
        blind_index = blind_index[
            [
                "chart_number",
                "blind_chart_id",
                "blind_chart_path",
                "blind_chart_sha256",
                "sheet_number",
                "slot",
            ]
        ].sort_values("chart_number", kind="mergesort")
        if len(blind_index) != EXPECTED_EVENTS or blind_index.chart_number.duplicated().any():
            raise ResearchError("public blind index coverage drift")
        blind_index.to_csv(staging / "blind_index.csv", index=False)

        review_template = [
            {
                "chart_number": int(chart_number),
                "BASE_COMPRESSION": False,
                "ORDERLY_PRICE_DISCOVERY": False,
                "HIGH_TURNOVER_LOW_PRICE_DISPLACEMENT": False,
                "MATURE_EXTENSION_OR_TERMINAL_SPIKE": False,
                "DOWNTREND_OR_BREAKDOWN": False,
                "evidence": "",
                "reviewer": "",
            }
            for chart_number in blind_index.chart_number
        ]
        write_json(staging / "phase1_review_template.json", review_template)

        if verify_bound_inputs(*verify_preflight_authorization()) != source_hashes:
            raise ResearchError("bound input changed during Stage-C construction")
        blind_order_digest = hashlib.sha256(
            "\n".join(blind_order.blind_chart_id.astype(str)).encode("utf-8")
        ).hexdigest()
        manifest = {
            "experiment": EXPERIMENT,
            "stage": "STAGE_C_PHASE1_ANONYMOUS_OUTCOME_MASKED_CORPUS",
            "asset_id": ASSET_ID,
            "authorization_id": AUTHORIZATION_ID,
            "authorized_arm": AUTHORIZED_ARM,
            "source_hashes": source_hashes,
            "events": EXPECTED_EVENTS,
            "individual_masked_charts": EXPECTED_EVENTS,
            "masked_contact_sheets": len(sheets),
            "phase1_window_relative_sessions": [-WINDOW, 0],
            "reserved_phase2_window_relative_sessions": [1, WINDOW],
            "window_slots_per_event": WINDOW_ROWS,
            "minimum_chart_date": str(windows.trade_date.min().date()),
            "maximum_chart_date": str(windows.trade_date.max().date()),
            "opaque_order_algorithm": (
                "SHA256(UTF8(salt + '|' + event_id)); ascending full digest then event_id"
            ),
            "blind_chart_id_algorithm": (
                "'B-' + first 20 lowercase hex characters of the full order digest"
            ),
            "opaque_order_salt": OPAQUE_ORDER_SALT,
            "blind_order_sha256": blind_order_digest,
            "identity_crosswalk_persisted": False,
            "blind_index_sha256": sha256(staging / "blind_index.csv"),
            "phase1_review_template_sha256": sha256(
                staging / "phase1_review_template.json"
            ),
            "phase1_annotation_rows_required_before_phase2": EXPECTED_EVENTS,
            "post_2020_row_read": False,
            "post_signal_row_read": False,
            "outcome_artifact_parsed": False,
            "identity_exposed_to_reviewer": False,
            "full_chart_generated": False,
            "outcome_sheet_generated": False,
            "outcome_grouping_performed": False,
            "outcome_attachment_performed": False,
            "rule_search_performed": False,
            "rule_aggregation_performed": False,
            "portfolio_replay_performed": False,
            "candidate_reselection_performed": False,
            "individual_coverage_exactly_once": True,
            "masked_contact_sheet_coverage_exactly_once": True,
            "phase1_price_scale_is_per_chart": True,
            "post_signal_used_as_predictor": False,
            "next_step": (
                "COMPLETE_ALL_1781_PHASE1_ANNOTATIONS_AND_FREEZE_THEIR_HASH_"
                "BEFORE_A_SEPARATE_PHASE2_SPEC"
            ),
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
