#!/usr/bin/env python3
"""Build the outcome-blind V30 low-positive-feedback mother."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

EXPERIMENT = "ASHARE-LOW-POSITIVE-FEEDBACK-GOOD-NEWS-MOTHER-V30"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
REGISTRY = REPO / "configs/data_asset_registry.json"
ASSET_MANIFEST = (
    REPO / "research/market_behavior_os_v2/experiments/ASHARE-V30-CY034_DATA_ASSET_MANIFEST.json"
)
ASSET_ID = "CY-034"
AUTHORIZATION_ID = "CYQ-AUTH-ASHARE-TURNOVER-PFC-V30-STAGE-A-2013-2020-V1"
BUILDER = (
    REPO / "research/market_behavior_os_v2/scripts/"
    "run_ashare_collapse_gap_zone_pattern_fidelity_audit_v1.py"
)
BUILD_WRAPPER = (
    REPO / "research/market_behavior_os_v2/scripts/"
    "run_ashare_collapse_gap_zone_dual_fresh_k10_validation_v1.py"
)
ADJUSTED_COORDINATE_BUILDER = (
    REPO / "research/market_behavior_os_v2/scripts/"
    "run_ashare_former_leader_strict_gap_reclaim_v3.py"
)
CHRONOLOGY_AUDIT = (
    REPO / "research/market_behavior_os_v2/experiments/"
    "ASHARE-TAIL-OPEN-LGBM-V1_chronology_extension_audit.json"
)
DAILY_PREP_MANIFEST = (
    REPO / "research/market_behavior_os_v2/experiments/"
    "ASHARE-TAIL-OPEN-LGBM-V1_daily_prep_2013_2023_input_manifest.json"
)
DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
DAILY_CONTRACT = Path(
    "/Volumes/quant/CY_quant_research/ashare_tail_open_lgbm_v1/daily_contract_2013_2023.parquet"
)
DAILY_PIT_AUDIT = Path(
    "/Volumes/quant/CY_quant_research/ashare_tail_open_lgbm_v1/pit_daily_2013_2023_cy006/audit.json"
)
ADJUSTED_COORDINATE_SOURCE = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_adjusted_daily_state_2013_2023.parquet"
)
OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_low_positive_feedback_good_news_mother_v30"
)
STAGE_A = OUTPUT_ROOT / "stage_a"
EXPECTED_SPEC = "c0f8c1c0617099f2705a873608fae390dbb30dd929b38ce040bab649e5841b0d"
EXPECTED_DAILY = "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00"
EXPECTED_BUILDER = "2b8b5c09df390b8ff2133244fad4a3fdfecbadf6052884b4f9c567e40edccee0"
EXPECTED_BUILD_WRAPPER = "3d6c9a887b36cb15c712acab2fb391c9b2a8c6afd62cc6e142b0322f5f070dc4"
EXPECTED_ADJUSTED_COORDINATE_BUILDER = (
    "358b62014c52b7bf936937746223954512fe9451eaa5009063e14f39e1bb1787"
)
EXPECTED_CHRONOLOGY_AUDIT = "e57ed5cf1730d53cd156cad162271c6be29f1c7074a257bbad81f22b09cd993f"
EXPECTED_DAILY_PREP_MANIFEST = "4746a5873b351a0c925bc21ca005b02d4f759a9b38c473702f58130ccfa20394"
EXPECTED_DAILY_CONTRACT = "4bb61e07eaa72f04e0d01e8585066010cf2e8ab0d1025d5a9cb634f5839c84df"
EXPECTED_DAILY_PIT_AUDIT = "8071fdae37f38f9ef8bca18815c3ddc1ddd9a89a83df6761aec015818249c752"
EXPECTED_ADJUSTED_COORDINATE_SOURCE = (
    "76fe88cb7509ae33a3d32b1bfd6d0c90560083127bdfaf63da1d7d24ec72bf60"
)
YEARS = tuple(range(2014, 2021))
MAX_SIGNAL_DATE = pd.Timestamp("2020-06-30")
MAX_CONTEXT_CAL_IDX = 1944
CONTEXT_SESSIONS = 126
REDUNDANCY_LIMIT = 0.80


class ResearchError(RuntimeError):
    """Fail closed on frozen identity, PIT chronology, or representation drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inputs() -> dict[str, str]:
    actual = {
        "spec": sha256(SPEC),
        "runner": sha256(Path(__file__)),
        "asset_manifest": sha256(ASSET_MANIFEST),
        "daily": sha256(DAILY),
        "builder": sha256(BUILDER),
        "build_wrapper": sha256(BUILD_WRAPPER),
        "adjusted_coordinate_builder": sha256(ADJUSTED_COORDINATE_BUILDER),
        "chronology_audit": sha256(CHRONOLOGY_AUDIT),
        "daily_prep_manifest": sha256(DAILY_PREP_MANIFEST),
        "daily_contract": sha256(DAILY_CONTRACT),
        "daily_pit_audit": sha256(DAILY_PIT_AUDIT),
        "adjusted_coordinate_source": sha256(ADJUSTED_COORDINATE_SOURCE),
    }
    expected = {
        "spec": EXPECTED_SPEC,
        "daily": EXPECTED_DAILY,
        "builder": EXPECTED_BUILDER,
        "build_wrapper": EXPECTED_BUILD_WRAPPER,
        "adjusted_coordinate_builder": EXPECTED_ADJUSTED_COORDINATE_BUILDER,
        "chronology_audit": EXPECTED_CHRONOLOGY_AUDIT,
        "daily_prep_manifest": EXPECTED_DAILY_PREP_MANIFEST,
        "daily_contract": EXPECTED_DAILY_CONTRACT,
        "daily_pit_audit": EXPECTED_DAILY_PIT_AUDIT,
        "adjusted_coordinate_source": EXPECTED_ADJUSTED_COORDINATE_SOURCE,
    }
    direct_actual = {key: actual[key] for key in expected}
    if direct_actual != expected:
        raise ResearchError(f"frozen input identity drift: {actual}")

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assets = [item for item in registry["assets"] if item.get("asset_id") == ASSET_ID]
    authorizations = [
        item
        for item in registry["bounded_authorizations"]
        if item.get("authorization_id") == AUTHORIZATION_ID
    ]
    if len(assets) != 1 or len(authorizations) != 1:
        raise ResearchError("missing or duplicate bounded V30 data authorization")
    asset = assets[0]
    authorization = authorizations[0]
    dependencies = [
        item
        for item in registry["assets"]
        if item.get("asset_id") == authorization.get("dependency_asset_id")
    ]
    manifest_sha = actual["asset_manifest"]
    if (
        len(dependencies) != 1
        or dependencies[0].get("status") != authorization.get("dependency_status")
        or asset.get("status") != "RESEARCH_CONDITIONAL"
        or asset.get("lineage", {}).get("manifest_sha256") != manifest_sha
        or authorization.get("asset_id") != ASSET_ID
        or authorization.get("purpose") != "ASHARE_OUTCOME_BLIND_MOTHER_REPRESENTATION"
        or authorization.get("dependency_asset_id") != "QD-001"
        or authorization.get("dependency_status") != "RESEARCH_CONDITIONAL"
        or authorization.get("bound_manifest", {}).get("sha256") != manifest_sha
        or authorization.get("scope", {}).get("project") != "research/market_behavior_os_v2"
        or authorization.get("scope", {}).get("start") != "2013-01-04"
        or authorization.get("scope", {}).get("end") != "2020-06-30"
        or authorization.get("scope", {}).get("warmup_start") != "2013-01-04"
        or authorization.get("scope", {}).get("signal_start") != "2014-01-01"
        or authorization.get("scope", {}).get("signal_end") != "2020-06-30"
        or authorization.get("scope", {}).get("maximum_physical_row_date") != "2020-06-30"
        or authorization.get("authorized_arms") != ["V30_OUTCOME_BLIND_STAGE_A_ONLY"]
        or authorization.get("outcome_attachment_authorized") is not False
        or authorization.get("current_survivor_fallback_allowed") is not False
        or authorization.get("record_level_available_at_available") is not False
        or asset.get("lineage", {}).get("bounded_authorization_id") != AUTHORIZATION_ID
    ):
        raise ResearchError("V30 bounded authorization semantics drift")
    protocol = authorization.get("bound_protocol", {})
    if (
        protocol.get("path") != str(SPEC)
        or protocol.get("sha256") != actual["spec"]
        or protocol.get("runner_path") != str(Path(__file__).resolve())
        or protocol.get("runner_sha256") != actual["runner"]
    ):
        raise ResearchError("V30 protocol or runner is not registry-bound")

    manifest = json.loads(ASSET_MANIFEST.read_text(encoding="utf-8"))
    if (
        manifest.get("asset_id") != ASSET_ID
        or manifest.get("artifact", {}).get("path") != str(DAILY)
        or manifest.get("artifact", {}).get("sha256") != actual["daily"]
        or manifest.get("authorization_boundary", {}).get("stage_a_outcome_read") is not False
        or manifest.get("authorization_boundary", {}).get("maximum_physical_row_date")
        != "2020-06-30"
    ):
        raise ResearchError("V30 asset manifest semantics drift")
    return actual


def connect(temporary: Path) -> duckdb.DuckDBPyConnection:
    temporary.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='10GB'")
    con.execute(f"SET temp_directory='{temporary.as_posix()}'")
    return con


def materialize_representation(
    con: duckdb.DuckDBPyConnection, representation_path: Path
) -> pd.DataFrame:
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE representation AS
        WITH raw AS (
          SELECT *,
            coalesce(hard_valid AND history_valid AND current_valid
              AND current_day_data_tradable AND trade_status=1
              AND market_rule_valid AND corporate_action_valid
              AND NOT corporate_action_blocking
              AND corporate_action_count IS NOT NULL
              AND corporate_action_count=0
              AND historical_identity_valid AND industry_valid
              AND causal_industry IS NOT NULL
              AND industry_snapshot_id IS NOT NULL
              AND NOT is_st AND available_at<=decision_at
              AND coord_open>0 AND coord_high>0
              AND coord_low>0 AND coord_close>0
              AND coord_high>=coord_open AND coord_high>=coord_close
              AND coord_low<=coord_open AND coord_low<=coord_close
              AND isfinite(coord_open) AND isfinite(coord_high)
              AND isfinite(coord_low) AND isfinite(coord_close)
              AND coordinate_factor>0 AND isfinite(coordinate_factor)
              AND invalid_step_cum IS NOT NULL
              AND amount>0 AND turnover_fraction>0
              AND isfinite(amount) AND isfinite(turnover_fraction)
            ,false) AS pfc_row_valid
          FROM read_parquet('{DAILY.as_posix()}')
          WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2020-06-30'
        ), market_calendar AS (
          SELECT trade_date,cal_idx,
            lead(date_trunc('month',trade_date)) OVER (ORDER BY cal_idx)
              AS next_month
          FROM (SELECT DISTINCT trade_date,cal_idx FROM raw)
        ), month_ends AS (
          SELECT trade_date,cal_idx
          FROM market_calendar
          WHERE next_month IS NULL
            OR next_month>date_trunc('month',trade_date)
        ), lagged AS (
          SELECT *,
            lag(step_return,1) OVER w AS lag1_step_return,
            lag(coord_close,1) OVER w AS lag1_close,
            lag(coord_close,6) OVER w AS lag6_close,
            lag(coord_close,23) OVER w AS lag23_close,
            lag(invalid_step_cum,1) OVER w AS lag1_invalid,
            lag(invalid_step_cum,2) OVER w AS lag2_invalid,
            lag(invalid_step_cum,6) OVER w AS lag6_invalid,
            lag(invalid_step_cum,23) OVER w AS lag23_invalid,
            lag(pfc_row_valid,1) OVER w AS lag1_valid,
            lag(pfc_row_valid,2) OVER w AS lag2_valid,
            lag(pfc_row_valid,6) OVER w AS lag6_valid,
            lag(pfc_row_valid,23) OVER w AS lag23_valid
          FROM raw
          WINDOW w AS (PARTITION BY symbol ORDER BY cal_idx)
        ), drivers AS (
          SELECT *,
            CASE WHEN lag1_valid AND lag2_valid
                AND lag1_invalid=lag2_invalid
                AND lag1_step_return IS NOT NULL
                AND isfinite(lag1_step_return)
              THEN greatest(lag1_step_return,0.0) END AS positive_lag_r1,
            CASE WHEN lag1_valid AND lag6_valid
                AND lag1_invalid=lag6_invalid
                AND lag1_close>0 AND lag6_close>0
              THEN greatest(lag1_close/lag6_close-1.0,0.0) END
              AS positive_lag_r5,
            CASE WHEN lag1_valid AND lag23_valid
                AND lag1_invalid=lag23_invalid
                AND lag1_close>0 AND lag23_close>0
              THEN greatest(lag1_close/lag23_close-1.0,0.0) END
              AS positive_lag_r22
          FROM lagged
        ), windowed AS (
          SELECT *,
            count(*) OVER w60 AS pfc_window_rows,
            min(cal_idx) OVER w60 AS pfc_window_first_cal_idx,
            bool_and(pfc_row_valid) OVER w60 AS pfc_window_valid,
            count(*) OVER w83 AS pfc_history_rows,
            min(cal_idx) OVER w83 AS pfc_history_first_cal_idx,
            bool_and(pfc_row_valid) OVER w83 AS pfc_history_valid,
            min(invalid_step_cum) OVER w83 AS pfc_history_min_invalid,
            max(invalid_step_cum) OVER w83 AS pfc_history_max_invalid,
            count(CASE WHEN step_return IS NOT NULL AND isfinite(step_return)
                  THEN 1 END) OVER w60 AS finite_step_return_count_60,
            count(positive_lag_r1) OVER w60 AS r1_pair_count,
            count(positive_lag_r5) OVER w60 AS r5_pair_count,
            count(positive_lag_r22) OVER w60 AS r22_pair_count,
            corr(turnover_fraction,positive_lag_r1) OVER w60 AS pfc_r1,
            corr(turnover_fraction,positive_lag_r5) OVER w60 AS pfc_r5,
            corr(turnover_fraction,positive_lag_r22) OVER w60 AS turnover_pfc_r22,
            avg(turnover_fraction) OVER w60 AS mean_turnover_60,
            stddev_samp(step_return) OVER w60 AS return_volatility_60,
            max(step_return) OVER w20 AS max_step_return_20
          FROM drivers
          WINDOW
            w60 AS (
              PARTITION BY symbol ORDER BY cal_idx
              ROWS BETWEEN 59 PRECEDING AND CURRENT ROW
            ),
            w83 AS (
              PARTITION BY symbol ORDER BY cal_idx
              ROWS BETWEEN 82 PRECEDING AND CURRENT ROW
            ),
            w20 AS (
              PARTITION BY symbol ORDER BY cal_idx
              ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
            )
        ), scored AS (
          SELECT *, (pfc_r1+pfc_r5+turnover_pfc_r22)/3.0 AS turnover_pfc_score,
            step_return*turnover_fraction AS signed_return_turnover
          FROM windowed
          WHERE pfc_window_rows=60
            AND pfc_window_first_cal_idx=cal_idx-59
            AND pfc_window_valid
            AND pfc_history_rows=83
            AND pfc_history_first_cal_idx=cal_idx-82
            AND pfc_history_valid
            AND pfc_history_min_invalid=pfc_history_max_invalid
            AND finite_step_return_count_60=60
            AND r1_pair_count=60 AND r5_pair_count=60 AND r22_pair_count=60
            AND pfc_r1 IS NOT NULL AND isfinite(pfc_r1)
            AND pfc_r5 IS NOT NULL AND isfinite(pfc_r5)
            AND turnover_pfc_r22 IS NOT NULL AND isfinite(turnover_pfc_r22)
            AND ret60 IS NOT NULL AND isfinite(ret60)
            AND mean_turnover_60 IS NOT NULL AND isfinite(mean_turnover_60)
            AND return_volatility_60 IS NOT NULL
            AND isfinite(return_volatility_60)
            AND max_step_return_20 IS NOT NULL
            AND isfinite(max_step_return_20)
        ), month_end_scored AS (
          SELECT s.*,
            median(amount) OVER (PARTITION BY s.trade_date)
              AS same_date_median_amount,
            count(*) OVER (PARTITION BY s.trade_date,s.causal_industry)
              AS industry_eligible_n,
            median(ret60) OVER (PARTITION BY s.trade_date,s.causal_industry)
              AS industry_median_ret60
          FROM scored s
          JOIN month_ends m USING(trade_date,cal_idx)
          WHERE s.trade_date BETWEEN DATE '2014-01-01' AND DATE '2020-06-30'
        )
        SELECT * FROM month_end_scored
        """
    )
    con.execute(
        f"""
        COPY (
          SELECT trade_date,cal_idx,symbol,sleeve,causal_industry,
            decision_at,available_at,industry_snapshot_id,
            industry_eligible_n,same_date_median_amount,industry_median_ret60,
            amount,turnover_fraction,mean_turnover_60,return_volatility_60,
            max_step_return_20,signed_return_turnover,ret20,ret60,step_return,
            turnover_pfc_score,pfc_r1,pfc_r5,turnover_pfc_r22,pfc_window_rows,
            pfc_window_first_cal_idx,pfc_history_rows,pfc_history_first_cal_idx,
            pfc_history_min_invalid,pfc_history_max_invalid,
            finite_step_return_count_60,
            r1_pair_count,r5_pair_count,r22_pair_count,
            invalid_step_cum,coordinate_factor,
            coord_open,coord_high,coord_low,coord_close
          FROM representation
          ORDER BY trade_date,causal_industry,turnover_pfc_score,amount DESC,symbol
        ) TO '{representation_path.as_posix()}'
        (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    return con.execute(
        "SELECT * FROM representation "
        "ORDER BY trade_date,causal_industry,turnover_pfc_score,amount DESC,symbol"
    ).fetch_df()


def select_candidates(
    con: duckdb.DuckDBPyConnection,
    representation: pd.DataFrame,
    candidates_path: Path,
) -> pd.DataFrame:
    con.register("representation_frame", representation)
    selected = con.execute(
        """
        SELECT * EXCLUDE(industry_pick_rank)
        FROM (
          SELECT *,row_number() OVER (
              PARTITION BY trade_date,causal_industry
              ORDER BY turnover_pfc_score,amount DESC,symbol
            ) AS industry_pick_rank
          FROM representation_frame
          WHERE industry_eligible_n>=10
            AND amount>=same_date_median_amount
            AND ret60>0
            AND ret60>=industry_median_ret60
        )
        WHERE industry_pick_rank=1
        ORDER BY cal_idx,causal_industry,symbol
        """
    ).fetch_df()
    con.unregister("representation_frame")

    keep: list[int] = []
    last_cal_idx: dict[str, int] = {}
    for index, row in selected.iterrows():
        symbol = str(row.symbol)
        cal_idx = int(row.cal_idx)
        if symbol in last_cal_idx and cal_idx <= last_cal_idx[symbol] + 20:
            continue
        keep.append(index)
        last_cal_idx[symbol] = cal_idx
    selected = selected.loc[keep].reset_index(drop=True)
    selected.insert(
        0,
        "event_id",
        selected.apply(
            lambda row: (
                f"LOW_PFC|{pd.Timestamp(row.trade_date):%Y%m%d}|{row.causal_industry}|{row.symbol}"
            ),
            axis=1,
        ),
    )
    selected = selected.rename(columns={"trade_date": "signal_date", "cal_idx": "signal_cal_idx"})
    con.register("candidate_frame", selected)
    con.execute(
        f"COPY candidate_frame TO '{candidates_path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    con.unregister("candidate_frame")
    return selected


def median_group_spearman(
    frame: pd.DataFrame,
    control: str,
    groups: list[str],
    minimum_group_size: int,
) -> tuple[float | None, int]:
    values: list[float] = []
    for _, part in frame.groupby(groups, sort=True):
        clean = part[["turnover_pfc_score", control]].replace([np.inf, -np.inf], np.nan).dropna()
        if (
            len(clean) < minimum_group_size
            or clean.turnover_pfc_score.nunique() < 2
            or clean[control].nunique() < 2
        ):
            continue
        rho = clean.turnover_pfc_score.corr(clean[control], method="spearman")
        if pd.notna(rho):
            values.append(float(rho))
    return (None if not values else float(np.median(values)), len(values))


def summarize(
    representation: pd.DataFrame,
    candidates: pd.DataFrame,
    source_hashes: dict[str, str],
    representation_path: Path,
    candidates_path: Path,
) -> dict[str, Any]:
    for column in ("trade_date", "decision_at", "available_at"):
        representation[column] = pd.to_datetime(representation[column])
    for column in ("signal_date", "decision_at", "available_at"):
        candidates[column] = pd.to_datetime(candidates[column])

    controls = (
        "ret60",
        "mean_turnover_60",
        "return_volatility_60",
        "max_step_return_20",
        "signed_return_turnover",
    )
    redundancy: dict[str, Any] = {}
    redundancy_passed = True
    for control in controls:
        global_rho, global_groups = median_group_spearman(
            representation, control, ["trade_date"], 20
        )
        industry_rho, industry_groups = median_group_spearman(
            representation, control, ["trade_date", "causal_industry"], 10
        )
        redundancy[control] = {
            "global_same_date_median_spearman": global_rho,
            "global_date_groups": global_groups,
            "pit_industry_same_date_median_spearman": industry_rho,
            "pit_industry_date_groups": industry_groups,
            "absolute_limit": REDUNDANCY_LIMIT,
        }
        redundancy_passed &= (
            global_rho is not None
            and abs(global_rho) < REDUNDANCY_LIMIT
            and industry_rho is not None
            and abs(industry_rho) < REDUNDANCY_LIMIT
        )

    cooldown_failures = 0
    for _, part in candidates.sort_values("signal_cal_idx").groupby("symbol"):
        diffs = part.signal_cal_idx.diff().dropna()
        cooldown_failures += int(diffs.le(20).sum())
    audit = {
        "representation_rows": len(representation),
        "candidate_rows": len(candidates),
        "duplicate_events": int(candidates.event_id.duplicated().sum()),
        "post_max_signal_date": int(candidates.signal_date.gt(MAX_SIGNAL_DATE).sum()),
        "chart_boundary_failures": int(
            candidates.signal_cal_idx.add(CONTEXT_SESSIONS).gt(MAX_CONTEXT_CAL_IDX).sum()
        ),
        "timing_failures": int(candidates.available_at.gt(candidates.decision_at).sum()),
        "window_failures": int(
            (
                candidates.pfc_window_rows.ne(60)
                | candidates.pfc_window_first_cal_idx.ne(candidates.signal_cal_idx - 59)
                | candidates.r1_pair_count.ne(60)
                | candidates.r5_pair_count.ne(60)
                | candidates.r22_pair_count.ne(60)
                | candidates.pfc_history_rows.ne(83)
                | candidates.pfc_history_first_cal_idx.ne(candidates.signal_cal_idx - 82)
                | candidates.pfc_history_min_invalid.ne(candidates.pfc_history_max_invalid)
                | candidates.finite_step_return_count_60.ne(60)
            ).sum()
        ),
        "nonfinite_pfc": int(
            (~np.isfinite(pd.to_numeric(candidates.turnover_pfc_score, errors="coerce"))).sum()
        ),
        "liquidity_failures": int(candidates.amount.lt(candidates.same_date_median_amount).sum()),
        "good_news_failures": int(
            (candidates.ret60.le(0) | candidates.ret60.lt(candidates.industry_median_ret60)).sum()
        ),
        "industry_support_failures": int(candidates.industry_eligible_n.lt(10).sum()),
        "cooldown_failures": cooldown_failures,
    }
    if any(audit[key] for key in audit if key not in {"representation_rows", "candidate_rows"}):
        raise ResearchError(f"stage-A audit failed: {audit}")

    annual: dict[str, Any] = {}
    opportunity_passed = True
    for year in YEARS:
        part = candidates.loc[candidates.signal_date.dt.year.eq(year)]
        annual[str(year)] = {
            "events": len(part),
            "decision_dates": int(part.signal_date.nunique()),
            "symbols": int(part.symbol.nunique()),
            "industries": int(part.causal_industry.nunique()),
        }
        opportunity_passed &= len(part) >= 50 and part.signal_date.nunique() >= 5

    stage_a_passed = bool(opportunity_passed and redundancy_passed)
    return {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_REPRESENTATION_AND_CANDIDATE_FREEZE",
        "source_hashes": source_hashes,
        "representation_sha256": sha256(representation_path),
        "candidate_sha256": sha256(candidates_path),
        "audit": audit,
        "annual": annual,
        "redundancy": redundancy,
        "opportunity_gate_passed": bool(opportunity_passed),
        "redundancy_gate_passed": bool(redundancy_passed),
        "stage_a_gate_passed": stage_a_passed,
        "outcomes_read": False,
        "post_signal_end_row_read": False,
        "post_2020_row_read": False,
        "maximum_signal_date": str(MAX_SIGNAL_DATE.date()),
        "next_action": (
            "ATTACH_FROZEN_DEVELOPMENT_OUTCOMES_AND_RENDER_ALL_CHARTS"
            if stage_a_passed
            else "CLOSE_BEFORE_OUTCOMES_NO_DEFINITION_RESCUE"
        ),
    }


def main() -> None:
    source_hashes = verify_inputs()
    if STAGE_A.exists():
        raise ResearchError(f"canonical Stage A already exists: {STAGE_A}")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".stage_a_staging_", dir=OUTPUT_ROOT))
    representation_path = staging / "representation_panel.parquet"
    candidates_path = staging / "candidates_frozen.parquet"
    result_path = staging / "result.json"
    con: duckdb.DuckDBPyConnection | None = None
    try:
        con = connect(staging / "duckdb_tmp")
        representation = materialize_representation(con, representation_path)
        candidates = select_candidates(con, representation, candidates_path)
        con.close()
        con = None
        result = summarize(
            representation,
            candidates,
            source_hashes,
            representation_path,
            candidates_path,
        )
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        shutil.rmtree(staging / "duckdb_tmp", ignore_errors=True)
        staging.replace(STAGE_A)
    except Exception:
        if con is not None:
            con.close()
        shutil.rmtree(staging, ignore_errors=True)
        raise
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
