#!/usr/bin/env python3
"""Freeze identities, then evaluate the exact V20 later-period challenge."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import run_ashare_bear_fast_capitulation_active_demand_short_ranking_v13r1 as v13  # noqa: E402
import run_ashare_causal_bear_bull_dual_engine_lane_specific_acceptance_v19r2 as v19  # noqa: E402
import run_ashare_distributed_accumulation_slow_exhaustion_mother_screen_v1 as slow  # noqa: E402
import run_ashare_quiet_inventory_fast_repricing_v1 as qfast  # noqa: E402

EXPERIMENT = "ASHARE-CAUSAL-BULL-BEAR-THREE-MECHANISM-V20-VALIDATION-2022-2024"
REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
CONTRACT = OS_ROOT / (
    "experiments/ASHARE-CAUSAL-BULL-BEAR-THREE-MECHANISM-"
    "V20-validation-2022-2024_contract.json"
)
EXPECTED_CONTRACT_SHA256 = "1f3fd1dd31f1202fab9a8170a359f8452fde73313190fa2ac1a56274acfdaf60"
EXPECTED_STAGE_A_RUNNER_SHA256 = "73e1047528347a61b163c81d56a784969e2f48540ac298cd91b685c454782fa3"

DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
DAILY_OLD = (
    DATA_ROOT
    / "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1"
    / "pit_daily_compact_2013_2023.parquet"
)
DAILY_NEW = (
    DATA_ROOT
    / "ashare_true_gap_below_l_clean_corridor_v26_validation_2024_2025_v1"
    / "pit_daily_qd010_exact_2022_2026q1.parquet"
)
CY006_2024 = Path(
    "/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/"
    "daily/partition_year=2024/data_0.parquet"
)
REGIME = (
    DATA_ROOT
    / "ashare_causal_market_regime_routed_simple_strategy_v1"
    / "stage_a/causal_market_regime_2014_2023.parquet"
)
MARKET_2024 = (
    DATA_ROOT
    / "ashare_causal_bear_strong_bull_dual_engine_v17"
    / "challenge_2022_2024/stage_a/causal_market_2024.parquet"
)
V24_CANDIDATES = (
    DATA_ROOT / "ashare_bull_quiet_platform_dual_demand_v24/stage_a/candidates.parquet"
)
V13_SELECTED = (
    DATA_ROOT
    / "ashare_bear_fast_capitulation_active_demand_short_ranking_v13r1"
    / "selected_accepted_trades.parquet"
)
V17_BEAR_RAW_2024 = (
    DATA_ROOT
    / "ashare_causal_bear_strong_bull_dual_engine_v17"
    / "challenge_2022_2024/stage_a/bear_raw_candidates_2024.parquet"
)

EXPECTED_HASHES = {
    "daily_old": "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    "daily_new": "95ba886707811da9a0514d1d3a9b2ddf9df5debe69eed4e904502f8f3e1cfca9",
    "cy006_2024": "fa10819c433224d3a3da5b1b1bb5222fdc5279aa3636abcbe6f2fa68f7a5771e",
    "regime": "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
    "market_2024": "71d1bb376d1d923c175cce28e0c0623f6fee2b654f123871d4f0d2a061fd14fc",
    "v24_candidates": "ad25518cb1e04ca58db6cd4d49e1e00dc65da049b7e089c489d83c6464819cab",
    "v13_selected": "8e62f4b3a9552cac769e95eb6e172ec65e8d53af207cccb06a60c6ad21ca8140",
    "v17_bear_raw_2024": "f2f6117c6651bb412f0b0d87312f08784653056234a1ebc5852fa18f59f70d41",
    "qfast_runner": "42be0aed77c63197320b127b483bd7bb0b9518c8dc999405be80ab1b84d45da5",
    "slow_runner": "4c4992e333c9f7931ca84454e1f71742cf49bcfa8ff333ba8876cc202f351870",
    "v19_runner": "3d51514bfd1d1f0d731312251618d2952823552cc55d360b3b88a1f96571617b",
    "v13_runner": "354695574d68b6861f61861b6710ee7eb27360f13dced0da34df9a90a5097047",
}

OUTPUT_ROOT = DATA_ROOT / "ashare_causal_bull_bear_three_mechanism_v20_validation_2022_2024"
STAGE_A = OUTPUT_ROOT / "stage_a"
STAGE_B = OUTPUT_ROOT / "stage_b"
BULL_MOTHERS = STAGE_A / "bull_mothers_2022_2024.parquet"
BULL_ACCEPTED = STAGE_A / "bull_r2_accepted_2022_2024.parquet"
SLOW_CANDIDATES = STAGE_A / "bear_slow_candidates_2022_2024.parquet"
BEAR_FAST_IDENTITIES = STAGE_A / "bear_fast_identities_2022_2024.parquet"
STAGE_A_FREEZE = STAGE_A / "stage_a_freeze.json"
BULL_OUTCOMES = STAGE_B / "bull_outcomes.parquet"
SLOW_OUTCOMES = STAGE_B / "bear_slow_outcomes.parquet"
BEAR_FAST_OUTCOMES = STAGE_B / "bear_fast_outcomes.parquet"
UNION = STAGE_B / "validation_union.parquet"
RESULT = STAGE_B / "result.json"


class ValidationError(RuntimeError):
    """Fail closed on identity, PIT timing, reconstruction, or execution drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def connection() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='12GB'")
    return con


def verify_inputs() -> dict[str, str]:
    paths = {
        "contract": CONTRACT,
        "daily_old": DAILY_OLD,
        "daily_new": DAILY_NEW,
        "cy006_2024": CY006_2024,
        "regime": REGIME,
        "market_2024": MARKET_2024,
        "v24_candidates": V24_CANDIDATES,
        "v13_selected": V13_SELECTED,
        "v17_bear_raw_2024": V17_BEAR_RAW_2024,
        "qfast_runner": Path(qfast.__file__),
        "slow_runner": Path(slow.__file__),
        "v19_runner": Path(v19.__file__),
        "v13_runner": Path(v13.__file__),
    }
    expected = {"contract": EXPECTED_CONTRACT_SHA256, **EXPECTED_HASHES}
    actual: dict[str, str] = {}
    for name, path in paths.items():
        if not path.is_file():
            raise ValidationError(f"missing frozen source: {path}")
        actual[name] = sha256(path)
        if actual[name] != expected[name]:
            raise ValidationError(f"{name} identity drift: {actual[name]} != {expected[name]}")
    return actual


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = connection()
    con.register("frame", frame)
    con.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def state_feature_ctes() -> str:
    return qfast.feature_ctes() + """
    , market_state AS (
      SELECT CAST(trade_date AS DATE) AS state_date,
        median(ret20) FILTER(WHERE current_valid AND NOT is_st AND ret20 IS NOT NULL)
          AS market_median_ret20_x,
        avg((ret20>0)::INTEGER) FILTER(
          WHERE current_valid AND NOT is_st AND ret20 IS NOT NULL
        ) AS market_positive_ret20_share_x,
        median(ret60) FILTER(WHERE current_valid AND NOT is_st AND ret60 IS NOT NULL)
          AS market_median_ret60_x,
        avg((ret60>0)::INTEGER) FILTER(
          WHERE current_valid AND NOT is_st AND ret60 IS NOT NULL
        ) AS market_positive_ret60_share_x,
        median(step_return) FILTER(
          WHERE current_valid AND NOT is_st AND step_return IS NOT NULL
        ) AS market_median_ret1,
        avg((step_return>0)::INTEGER) FILTER(
          WHERE current_valid AND NOT is_st AND step_return IS NOT NULL
        ) AS market_positive_ret1_share,
        max(available_at) FILTER(WHERE current_valid AND NOT is_st) AS market_state_latest
      FROM featured GROUP BY trade_date
    ), industry_state AS (
      SELECT CAST(trade_date AS DATE) AS state_date,causal_industry,
        median(ret20) FILTER(WHERE current_valid AND NOT is_st AND ret20 IS NOT NULL)
          AS industry_median_ret20,
        avg((ret20>0)::INTEGER) FILTER(
          WHERE current_valid AND NOT is_st AND ret20 IS NOT NULL
        ) AS industry_positive_ret20_share,
        median(step_return) FILTER(
          WHERE current_valid AND NOT is_st AND step_return IS NOT NULL
        ) AS industry_median_ret1,
        avg((step_return>0)::INTEGER) FILTER(
          WHERE current_valid AND NOT is_st AND step_return IS NOT NULL
        ) AS industry_positive_ret1_share,
        max(available_at) FILTER(WHERE current_valid AND NOT is_st) AS industry_state_latest
      FROM featured GROUP BY trade_date,causal_industry
    ), joined_state AS (
      SELECT f.*,m.market_median_ret1,m.market_positive_ret1_share,m.market_state_latest,
        i.industry_median_ret20,i.industry_positive_ret20_share,
        i.industry_median_ret1,i.industry_positive_ret1_share,i.industry_state_latest,
        r.market_regime,r.market_median_ret20,r.market_positive_ret20_share,
        r.market_median_ret60,r.market_positive_ret60_share,
        r.latest_source_timestamp AS regime_latest_source
      FROM featured f
      JOIN market_state m ON CAST(f.trade_date AS DATE)=m.state_date
      JOIN industry_state i
        ON CAST(f.trade_date AS DATE)=i.state_date AND f.causal_industry=i.causal_industry
      JOIN (
        SELECT * FROM read_parquet('""" + REGIME.as_posix() + """')
        WHERE year(trade_date)=2023
        UNION ALL BY NAME
        SELECT * EXCLUDE(strong_bull,positive_ret20_share_lag5)
        FROM read_parquet('""" + MARKET_2024.as_posix() + """')
      ) r ON CAST(f.trade_date AS DATE)=r.trade_date
      WHERE year(f.trade_date) IN (2023,2024)
    )
    """


def rebuilt_bull_candidates(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    query = state_feature_ctes() + f"""
    , flags AS (
      SELECT *,
        market_regime='BULL'
          AND industry_median_ret20>0 AND industry_positive_ret20_share>0.50
          AS pass_base,
        market_median_ret1>0 AND market_positive_ret1_share>0.50
          AND industry_median_ret1>0 AND industry_positive_ret1_share>0.50
          AS synchronized,
        open_gap>=0.02 AND step_return-industry_median_ret1>=0.02
          AS idiosyncratic
      FROM joined_state
      WHERE {qfast.mother_condition()}
    )
    SELECT 'QIG-' || strftime(trade_date,'%Y%m%d') || '-' || symbol AS source_event_id,
      'BULL|QIG-' || strftime(trade_date,'%Y%m%d') || '-' || symbol AS chart_event_id,
      symbol,sleeve,CAST(trade_date AS DATE) AS signal_date,cal_idx AS signal_cal_idx,
      invalid_step_cum AS signal_lineage,coord_close AS signal_coord_close,
      platform_high AS structural_level,'BULL_CONTINUATION' AS engine,
      CASE WHEN pass_base AND synchronized THEN 'SYNCHRONIZED_MAJORITY_DEMAND'
           WHEN pass_base AND NOT synchronized AND idiosyncratic
             THEN 'IDIOSYNCRATIC_INFORMATION_JUMP' END AS admission_lane,
      greatest(available_at,market_state_latest,industry_state_latest,regime_latest_source)
        AS feature_latest_timestamp,
      market_state_latest,industry_state_latest,
      regime_latest_source
    FROM flags
    WHERE pass_base AND (
      synchronized OR (NOT synchronized AND idiosyncratic)
    )
    ORDER BY signal_date,symbol,source_event_id
    """
    frame = con.execute(query).fetch_df()
    for column in (
        "signal_date",
        "feature_latest_timestamp",
        "market_state_latest",
        "industry_state_latest",
        "regime_latest_source",
    ):
        frame[column] = pd.to_datetime(frame[column])
    return frame


def load_bull_mothers(con: duckdb.DuckDBPyConnection) -> tuple[pd.DataFrame, dict[str, Any]]:
    rebuilt = rebuilt_bull_candidates(con)
    rebuilt_2023 = rebuilt.loc[rebuilt.signal_date.dt.year.eq(2023)].copy()
    frozen_2023 = con.execute(
        f"""
        SELECT symbol,CAST(signal_date AS DATE) AS signal_date,admission_lane
        FROM read_parquet('{V24_CANDIDATES.as_posix()}')
        WHERE year(signal_date)=2023
        ORDER BY signal_date,symbol,event_id
        """
    ).fetch_df()
    frozen_2023["signal_date"] = pd.to_datetime(frozen_2023.signal_date)
    comparison = rebuilt_2023.merge(
        frozen_2023,
        on=["symbol", "signal_date"],
        how="outer",
        suffixes=("_rebuilt", "_frozen"),
        indicator=True,
    )
    audit = {
        "rebuilt_2023": len(rebuilt_2023),
        "frozen_2023": len(frozen_2023),
        "rebuilt_only": int(comparison._merge.eq("left_only").sum()),
        "frozen_only": int(comparison._merge.eq("right_only").sum()),
        "lane_mismatch": int(
            (
                comparison._merge.eq("both")
                & comparison.admission_lane_rebuilt.ne(comparison.admission_lane_frozen)
            ).sum()
        ),
    }
    if audit["rebuilt_only"] or audit["frozen_only"] or audit["lane_mismatch"]:
        raise ValidationError(f"V24 candidate reconstruction failed: {audit}")

    historical = con.execute(
        f"""
        SELECT event_id AS source_event_id,'BULL|' || event_id AS chart_event_id,
          symbol,sleeve,CAST(signal_date AS DATE) AS signal_date,cal_idx AS signal_cal_idx,
          invalid_step_cum AS signal_lineage,coord_close AS signal_coord_close,
          platform_high AS structural_level,'BULL_CONTINUATION' AS engine,admission_lane,
          feature_latest_timestamp,market_state_latest,industry_state_latest,
          market_latest_source AS regime_latest_source
        FROM read_parquet('{V24_CANDIDATES.as_posix()}')
        WHERE year(signal_date) IN (2022,2023)
        ORDER BY signal_date,symbol,event_id
        """
    ).fetch_df()
    current = rebuilt.loc[rebuilt.signal_date.dt.year.eq(2024)].copy()
    frame = pd.concat([historical, current], ignore_index=True)
    for column in (
        "signal_date",
        "feature_latest_timestamp",
        "market_state_latest",
        "industry_state_latest",
        "regime_latest_source",
    ):
        frame[column] = pd.to_datetime(frame[column])
    if frame.chart_event_id.duplicated().any():
        raise ValidationError("duplicate Bull candidate identity")
    latest = frame[
        [
            "feature_latest_timestamp",
            "market_state_latest",
            "industry_state_latest",
            "regime_latest_source",
        ]
    ].max(axis=1)
    if latest.gt(frame.signal_date + pd.Timedelta(hours=15)).any():
        raise ValidationError("Bull predictor source after signal close")
    return frame.sort_values(["signal_date", "symbol"]).reset_index(drop=True), audit


def bull_acceptance(con: duckdb.DuckDBPyConnection, mothers: pd.DataFrame) -> pd.DataFrame:
    base = v19.load_base()
    con.register("bull_mothers", mothers[["chart_event_id", "symbol", "signal_cal_idx"]])
    paths = con.execute(
        f"""
        SELECT m.chart_event_id,d.*
        FROM bull_mothers m
        JOIN read_parquet('{DAILY_NEW.as_posix()}') d
          ON m.symbol=d.symbol AND d.cal_idx=m.signal_cal_idx+1
        ORDER BY m.chart_event_id,d.cal_idx
        """
    ).fetch_df()
    paths["trade_date"] = pd.to_datetime(paths.trade_date)
    groups = {key: part for key, part in paths.groupby("chart_event_id", sort=False)}
    rows = []
    for candidate in mothers.itertuples(index=False):
        path = groups.get(candidate.chart_event_id, pd.DataFrame())
        payload = dict(candidate._asdict())
        if len(path) != 1:
            rows.append({**payload, "accepted": False, "acceptance_status": "NO_EXACT_NEXT_BAR"})
            continue
        row = path.iloc[0]
        threshold = float(candidate.structural_level)
        if candidate.admission_lane == "IDIOSYNCRATIC_INFORMATION_JUMP":
            threshold = max(threshold, float(candidate.signal_coord_close))
        valid = (
            np.isfinite(float(row.invalid_step_cum))
            and float(row.invalid_step_cum) == float(candidate.signal_lineage)
            and base.legal_observation(row)
        )
        accepted = bool(valid and float(row.coord_close) >= threshold)
        rows.append(
            {
                **payload,
                "confirmation_date": pd.Timestamp(row.trade_date),
                "confirmation_cal_idx": int(row.cal_idx),
                "confirmation_coord_close": float(row.coord_close),
                "confirmation_threshold": threshold,
                "accepted": accepted,
                "acceptance_status": "ACCEPTED" if accepted else "REJECTED_NOT_ACCEPTED",
            }
        )
    result = pd.DataFrame(rows)
    result["signal_date"] = pd.to_datetime(result.signal_date)
    result["confirmation_date"] = pd.to_datetime(result.confirmation_date)
    return result


def slow_query(daily_relation: str, regime_relation: str, signal_years: str) -> str:
    return f"""
    WITH source AS (
      SELECT *,coord_close/nullif(prior_coord_close,0)-1 AS step_return_x
      FROM {daily_relation}
    ), base AS (
      SELECT d.*,r.market_regime,r.latest_source_timestamp AS market_latest_source_timestamp,
        count(*) OVER w60 AS prior60_rows,
        lag(d.cal_idx,60) OVER (PARTITION BY d.symbol ORDER BY d.cal_idx) AS lag60_cal_idx_exact,
        lag(d.coord_close,20) OVER (PARTITION BY d.symbol ORDER BY d.cal_idx) AS lag20_close_x,
        min(d.invalid_step_cum) OVER w60 AS prior60_lineage_min,
        max(d.invalid_step_cum) OVER w60 AS prior60_lineage_max,
        bool_and(d.hard_valid AND d.market_rule_valid AND d.corporate_action_valid
          AND NOT d.corporate_action_blocking AND coalesce(d.corporate_action_count,0)=0)
          OVER w60 AS prior60_lineage_valid,
        max(d.coord_high) OVER w5 AS prior5_high,
        min(d.coord_low) OVER w5 AS last5_low,
        min(d.coord_low) OVER wprev5 AS previous5_low,
        sum(CASE WHEN d.step_return_x<0 THEN d.turnover_fraction ELSE 0 END) OVER w5
          AS last5_downside_turnover,
        sum(CASE WHEN d.step_return_x<0 THEN d.turnover_fraction ELSE 0 END) OVER wprev5
          AS previous5_downside_turnover,
        median(d.turnover_fraction) OVER w20 AS prior20_turnover_median,
        CASE WHEN d.coord_high>d.coord_low
          THEN (d.coord_close-d.coord_low)/(d.coord_high-d.coord_low) END AS close_location
      FROM source d
      LEFT JOIN {regime_relation} r USING(trade_date)
      WINDOW
        w60 AS (PARTITION BY d.symbol ORDER BY d.cal_idx ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING),
        w20 AS (PARTITION BY d.symbol ORDER BY d.cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
        w5 AS (PARTITION BY d.symbol ORDER BY d.cal_idx ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING),
        wprev5 AS (
          PARTITION BY d.symbol ORDER BY d.cal_idx ROWS BETWEEN 10 PRECEDING AND 6 PRECEDING
        )
    ), flagged AS (
      SELECT *,turnover_fraction/nullif(prior20_turnover_median,0) AS turnover_expansion,
        coord_close/nullif(lag20_close_x,0)-1 AS exact_prior20_return,
        (
          prior60_rows=60 AND lag60_cal_idx_exact=cal_idx-60
          AND prior60_lineage_min=invalid_step_cum AND prior60_lineage_max=invalid_step_cum
          AND prior60_lineage_valid AND hard_valid AND current_valid
          AND current_day_data_tradable AND trade_status=1 AND market_rule_valid
          AND corporate_action_valid AND NOT corporate_action_blocking
          AND coalesce(corporate_action_count,0)=0 AND industry_valid
          AND historical_identity_valid AND industry_snapshot_id IS NOT NULL AND NOT is_st
          AND available_at<=decision_at AND market_latest_source_timestamp<=decision_at
          AND round(close*100)<round(up_limit_price*100) AND coord_close>0
          AND coord_high>=coord_low AND turnover_fraction>0 AND prior20_turnover_median>0
          AND market_regime='BEAR' AND coord_close/nullif(lag20_close_x,0)-1<=-0.08
          AND last5_low>=previous5_low
          AND last5_downside_turnover<=previous5_downside_turnover
          AND step_return_x BETWEEN 0.02 AND 0.07 AND close_location>=0.75
          AND coord_close>prior5_high
          AND turnover_fraction/nullif(prior20_turnover_median,0) BETWEEN 1.00 AND 2.50
        ) AS raw_slow
      FROM base
    ), cooldown AS (
      SELECT *,max(CASE WHEN raw_slow THEN cal_idx END) OVER(
        PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
      ) AS prior_raw_cal_idx
      FROM flagged
    )
    SELECT 'SLOW_SUPPLY_EXHAUSTION_TAKEOVER|' || strftime(trade_date,'%Y%m%d') || '|'
        || symbol AS event_id,
      'SLOW_SUPPLY_EXHAUSTION_TAKEOVER' AS mechanism,symbol,sleeve,
      CAST(trade_date AS DATE) AS signal_date,cal_idx AS signal_cal_idx,
      decision_at,available_at,market_regime,market_latest_source_timestamp,
      invalid_step_cum,coordinate_factor,prior5_high,exact_prior20_return,
      last5_low,previous5_low,last5_downside_turnover,previous5_downside_turnover,
      turnover_expansion,close_location,step_return_x AS step_return,causal_industry
    FROM cooldown
    WHERE year(trade_date) IN ({signal_years}) AND raw_slow
      AND (prior_raw_cal_idx IS NULL OR cal_idx-prior_raw_cal_idx>20)
    ORDER BY signal_date,symbol,event_id
    """


def build_slow_candidates(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    historical = con.execute(
        slow_query(
            f"read_parquet('{DAILY_OLD.as_posix()}')",
            f"read_parquet('{REGIME.as_posix()}')",
            "2022,2023",
        )
    ).fetch_df()
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW combined_regime AS
        SELECT * FROM read_parquet('{REGIME.as_posix()}') WHERE year(trade_date) IN (2022,2023)
        UNION ALL BY NAME
        SELECT * EXCLUDE(strong_bull,positive_ret20_share_lag5)
        FROM read_parquet('{MARKET_2024.as_posix()}')
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW daily_new_with_industry_snapshot AS
        SELECT d.*,s.industry_snapshot_id
        FROM read_parquet('{DAILY_NEW.as_posix()}') d
        LEFT JOIN read_parquet('{CY006_2024.as_posix()}') s
          ON d.symbol=s.symbol AND CAST(d.trade_date AS DATE)=s.trade_date
        """
    )
    snapshot_audit = con.execute(
        """
        SELECT count(*) AS n,count(industry_snapshot_id) AS known,
          count(DISTINCT industry_snapshot_id) AS snapshot_count
        FROM daily_new_with_industry_snapshot WHERE year(trade_date)=2024
        """
    ).fetchone()
    if snapshot_audit[0] != snapshot_audit[1] or snapshot_audit[2] != 1:
        raise ValidationError(f"invalid 2024 industry snapshot lineage: {snapshot_audit}")
    current = con.execute(
        slow_query("daily_new_with_industry_snapshot", "combined_regime", "2024")
    ).fetch_df()
    frame = pd.concat([historical, current], ignore_index=True)
    for column in ("signal_date", "decision_at", "available_at", "market_latest_source_timestamp"):
        frame[column] = pd.to_datetime(frame[column])
    if frame.event_id.duplicated().any():
        raise ValidationError("duplicate slow-exhaustion candidate identity")
    if frame.available_at.gt(frame.decision_at).any():
        raise ValidationError("slow candidate source after decision")
    if frame.market_latest_source_timestamp.gt(frame.decision_at).any():
        raise ValidationError("slow market state source after decision")
    return frame.sort_values(["signal_date", "symbol"]).reset_index(drop=True)


def build_bear_fast_identities(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    historical = con.execute(
        f"""
        SELECT event_id,symbol,sleeve,CAST(signal_date AS DATE) AS signal_date,
          signal_cal_idx,'FROZEN_V13R1_SELECTED_IDENTITY' AS candidate_source,
          NULL::DOUBLE AS signal_invalid_step_cum,NULL::DOUBLE AS stock_minus_industry_ret20,
          NULL::DOUBLE AS close_vs_prior10_high,NULL::DOUBLE AS close_location_x_f
        FROM read_parquet('{V13_SELECTED.as_posix()}')
        WHERE year(signal_date) IN (2022,2023)
        ORDER BY signal_date,symbol,event_id
        """
    ).fetch_df()
    con.execute(
        "CREATE OR REPLACE TEMP TABLE fast_rank_features AS "
        + qfast.feature_ctes()
        + """
        , ranked AS (
          SELECT *,max(coord_high) OVER(
            PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
          ) AS prior10_high
          FROM featured
        ), industry AS (
          SELECT CAST(trade_date AS DATE) AS state_date,causal_industry,
            median(ret20) FILTER(WHERE current_valid AND NOT is_st AND ret20 IS NOT NULL)
              AS industry_median_ret20
          FROM ranked GROUP BY trade_date,causal_industry
        )
        SELECT r.symbol,CAST(r.trade_date AS DATE) AS signal_date,r.invalid_step_cum,
          r.ret20-i.industry_median_ret20 AS stock_minus_industry_ret20,
          r.coord_close/nullif(r.prior10_high,0)-1 AS close_vs_prior10_high,
          r.close_location AS close_location_x_f
        FROM ranked r JOIN industry i
          ON CAST(r.trade_date AS DATE)=i.state_date AND r.causal_industry=i.causal_industry
        WHERE year(r.trade_date)=2024
        """
    )
    current = con.execute(
        f"""
        SELECT b.event_id,b.symbol,b.sleeve,CAST(b.signal_date AS DATE) AS signal_date,
          b.signal_cal_idx,'OUTCOME_BLIND_V17_REBUILT_RAW' AS candidate_source,
          f.invalid_step_cum AS signal_invalid_step_cum,f.stock_minus_industry_ret20,
          f.close_vs_prior10_high,f.close_location_x_f
        FROM read_parquet('{V17_BEAR_RAW_2024.as_posix()}') b
        JOIN fast_rank_features f
          ON b.symbol=f.symbol AND CAST(b.signal_date AS DATE)=f.signal_date
        ORDER BY signal_date,b.symbol,b.event_id
        """
    ).fetch_df()
    required = [
        "signal_invalid_step_cum",
        "stock_minus_industry_ret20",
        "close_vs_prior10_high",
        "close_location_x_f",
    ]
    if current[required].isna().any().any() or len(current) != 520:
        raise ValidationError("missing 2024 fast-Bear identity/rank lineage")
    frame = pd.concat([historical, current], ignore_index=True)
    frame["signal_date"] = pd.to_datetime(frame.signal_date)
    if frame.event_id.duplicated().any():
        raise ValidationError("duplicate fast-Bear candidate identity")
    return frame.sort_values(["signal_date", "symbol"]).reset_index(drop=True)


def stage_a() -> dict[str, Any]:
    source_hashes = verify_inputs()
    con = connection()
    bull_mothers, bull_audit = load_bull_mothers(con)
    bull_accepted = bull_acceptance(con, bull_mothers)
    slow_candidates = build_slow_candidates(con)
    bear_fast = build_bear_fast_identities(con)
    con.close()
    write_parquet(bull_mothers, BULL_MOTHERS)
    write_parquet(bull_accepted, BULL_ACCEPTED)
    write_parquet(slow_candidates, SLOW_CANDIDATES)
    write_parquet(bear_fast, BEAR_FAST_IDENTITIES)
    payload = {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_FREE_IDENTITY_AND_ACCEPTANCE_FREEZE",
        "contract_sha256": sha256(CONTRACT),
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes,
        "bull_2023_reproduction_audit": bull_audit,
        "bull_mother_counts": {
            str(year): int(bull_mothers.signal_date.dt.year.eq(year).sum())
            for year in (2022, 2023, 2024)
        },
        "bull_accepted_counts": {
            str(year): int(
                (
                    bull_accepted.signal_date.dt.year.eq(year)
                    & bull_accepted.accepted.fillna(False)
                ).sum()
            )
            for year in (2022, 2023, 2024)
        },
        "slow_candidate_counts": {
            str(year): int(slow_candidates.signal_date.dt.year.eq(year).sum())
            for year in (2022, 2023, 2024)
        },
        "bear_fast_identity_counts": {
            str(year): int(bear_fast.signal_date.dt.year.eq(year).sum())
            for year in (2022, 2023, 2024)
        },
        "bull_mothers_sha256": sha256(BULL_MOTHERS),
        "bull_accepted_sha256": sha256(BULL_ACCEPTED),
        "slow_candidates_sha256": sha256(SLOW_CANDIDATES),
        "bear_fast_identities_sha256": sha256(BEAR_FAST_IDENTITIES),
        "return_or_exit_outcome_attached": "NO",
        "future_market_function": False,
        "2025_2026_signal_read": "NO",
    }
    write_json(STAGE_A_FREEZE, payload)
    return payload


def verify_stage_a() -> dict[str, Any]:
    if not STAGE_A_FREEZE.is_file():
        raise ValidationError("missing Stage-A freeze")
    frozen = json.loads(STAGE_A_FREEZE.read_text(encoding="utf-8"))
    current = {
        "contract_sha256": sha256(CONTRACT),
        "runner_sha256": EXPECTED_STAGE_A_RUNNER_SHA256,
        "bull_mothers_sha256": sha256(BULL_MOTHERS),
        "bull_accepted_sha256": sha256(BULL_ACCEPTED),
        "slow_candidates_sha256": sha256(SLOW_CANDIDATES),
        "bear_fast_identities_sha256": sha256(BEAR_FAST_IDENTITIES),
    }
    drift = {
        key: {"frozen": frozen.get(key), "current": value}
        for key, value in current.items()
        if frozen.get(key) != value
    }
    if drift:
        raise ValidationError(f"Stage-A identity drift: {drift}")
    verify_inputs()
    return frozen


def load_paths(candidates: pd.DataFrame, id_column: str) -> dict[str, pd.DataFrame]:
    con = connection()
    con.register(
        "events",
        candidates[[id_column, "symbol", "signal_cal_idx"]].rename(
            columns={id_column: "event_key"}
        ),
    )
    paths = con.execute(
        f"""
        SELECT e.event_key,d.*,r.market_regime
        FROM events e JOIN read_parquet('{DAILY_NEW.as_posix()}') d
          ON e.symbol=d.symbol AND d.cal_idx>e.signal_cal_idx
             AND d.cal_idx<=e.signal_cal_idx+100
        LEFT JOIN (
          SELECT trade_date,market_regime
          FROM read_parquet('{REGIME.as_posix()}') WHERE year(trade_date) IN (2022,2023)
          UNION ALL BY NAME
          SELECT trade_date,market_regime FROM read_parquet('{MARKET_2024.as_posix()}')
        ) r ON CAST(d.trade_date AS DATE)=r.trade_date
        ORDER BY e.event_key,d.cal_idx
        """
    ).fetch_df()
    con.close()
    for column in ("trade_date", "available_at", "decision_at"):
        paths[column] = pd.to_datetime(paths[column])
    return {str(key): part for key, part in paths.groupby("event_key", sort=False)}


def replay_bull() -> pd.DataFrame:
    mothers = pd.read_parquet(BULL_MOTHERS)
    paths = load_paths(mothers, "chart_event_id")
    base = v19.load_base()
    outcomes = pd.DataFrame(
        [
            v19.replay_bull(
                base,
                candidate,
                paths.get(str(candidate.chart_event_id), pd.DataFrame()),
            )
            for candidate in mothers.itertuples(index=False)
        ]
    )
    outcomes["signal_date"] = pd.to_datetime(outcomes.signal_date)
    return outcomes


def replay_slow() -> pd.DataFrame:
    candidates = pd.read_parquet(SLOW_CANDIDATES)
    paths = load_paths(candidates, "event_id")
    outcomes = pd.DataFrame(
        [
            slow.replay_one(candidate, paths.get(str(candidate.event_id), pd.DataFrame()))
            for candidate in candidates.itertuples(index=False)
        ]
    )
    outcomes["signal_date"] = pd.to_datetime(outcomes.signal_date)
    return outcomes


def normalize_historical_bear() -> pd.DataFrame:
    con = connection()
    historical = con.execute(
        f"""
        SELECT event_id,symbol,sleeve,signal_date,signal_cal_idx,
          'BEAR_FAST_CAPITULATION_ACTIVE_DEMAND' AS mechanism,'BEAR' AS market_regime,
          entry_date,entry_cal_idx,entry_price,exit_date,exit_cal_idx,exit_price,
          exit_reason,holding_sessions,gross_return,net_return,'COMPLETED' AS status
        FROM read_parquet('{V13_SELECTED.as_posix()}')
        WHERE year(signal_date) IN (2022,2023)
        ORDER BY signal_date,symbol,event_id
        """
    ).fetch_df()
    con.close()
    for column in ("signal_date", "entry_date", "exit_date"):
        historical[column] = pd.to_datetime(historical[column])
    return historical


def replay_bear_fast() -> pd.DataFrame:
    identities = pd.read_parquet(BEAR_FAST_IDENTITIES)
    current = identities.loc[identities.signal_date.dt.year.eq(2024)].copy()
    replay_input = current.rename(columns={"signal_invalid_step_cum": "invalid_step_cum"})
    replay_input["mechanism"] = "BEAR_FAST_CAPITULATION_ACTIVE_DEMAND"
    replay_input["market_regime"] = "BEAR"
    paths = load_paths(replay_input, "event_id")
    raw = pd.DataFrame(
        [
            slow.replay_one(candidate, paths.get(str(candidate.event_id), pd.DataFrame()))
            for candidate in replay_input.itertuples(index=False)
        ]
    )
    raw["signal_date"] = pd.to_datetime(raw.signal_date)
    complete = raw.loc[raw.status.eq("COMPLETED")].merge(
        current[
            [
                "event_id",
                "stock_minus_industry_ret20",
                "close_vs_prior10_high",
                "close_location_x_f",
            ]
        ],
        on="event_id",
        how="left",
        validate="one_to_one",
    )
    accepted, _, _ = v13.select_capacity(complete)
    accepted = accepted.copy()
    accepted["mechanism"] = "BEAR_FAST_CAPITULATION_ACTIVE_DEMAND"
    accepted["market_regime"] = "BEAR"
    accepted["status"] = "COMPLETED"
    historical = normalize_historical_bear()
    columns = list(historical.columns)
    return pd.concat([historical, accepted[columns]], ignore_index=True)


def normalize_for_union(
    frame: pd.DataFrame, mechanism: str, priority: int, id_column: str
) -> pd.DataFrame:
    completed = frame.loc[frame.status.eq("COMPLETED")].copy()
    completed["event_id"] = completed[id_column].astype(str)
    completed["mechanism"] = mechanism
    completed["priority"] = priority
    keep = [
        "event_id",
        "symbol",
        "sleeve",
        "signal_date",
        "signal_cal_idx",
        "mechanism",
        "entry_date",
        "entry_cal_idx",
        "entry_price",
        "exit_date",
        "exit_cal_idx",
        "exit_price",
        "exit_reason",
        "holding_sessions",
        "gross_return",
        "net_return",
        "priority",
    ]
    return completed[keep]


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    values = pd.to_numeric(frame.net_return, errors="coerce")
    return {
        "completed": len(frame),
        "signal_dates": int(frame.signal_date.nunique()),
        "symbols": int(frame.symbol.nunique()),
        "mean_net": float(values.mean()) if len(frame) else None,
        "median_net": float(values.median()) if len(frame) else None,
        "win_rate": float(values.gt(0).mean()) if len(frame) else None,
        "ge_4pct_rate": float(values.ge(0.04).mean()) if len(frame) else None,
        "severe10": float(values.le(-0.10).mean()) if len(frame) else None,
        "target_hit": float(frame.exit_reason.str.startswith("TARGET_").mean())
        if len(frame)
        else None,
        "mean_holding_sessions": float(frame.holding_sessions.mean()) if len(frame) else None,
    }


def run_outcomes() -> dict[str, Any]:
    stage_freeze = verify_stage_a()
    bull = replay_bull()
    slow_frame = replay_slow()
    fast = replay_bear_fast()
    write_parquet(bull, BULL_OUTCOMES)
    write_parquet(slow_frame, SLOW_OUTCOMES)
    write_parquet(fast, BEAR_FAST_OUTCOMES)
    stacked = pd.concat(
        [
            normalize_for_union(
                bull,
                "BULL_QUIET_INVENTORY_CONTINUATION",
                1,
                "chart_event_id",
            ),
            normalize_for_union(
                fast,
                "BEAR_FAST_CAPITULATION_ACTIVE_DEMAND",
                1,
                "event_id",
            ),
            normalize_for_union(
                slow_frame,
                "BEAR_SLOW_SUPPLY_EXHAUSTION_TAKEOVER",
                2,
                "event_id",
            ),
        ],
        ignore_index=True,
    )
    stacked["signal_date"] = pd.to_datetime(stacked.signal_date)
    union = (
        stacked.sort_values(
            ["symbol", "signal_date", "priority", "event_id"], kind="mergesort"
        )
        .drop_duplicates(["symbol", "signal_date"], keep="first")
        .sort_values(["signal_date", "symbol", "event_id"], kind="mergesort")
        .reset_index(drop=True)
    )
    if union.entry_cal_idx.le(union.signal_cal_idx).any():
        raise ValidationError("same/prior-session entry in validation union")
    if union.exit_cal_idx.le(union.entry_cal_idx).any():
        raise ValidationError("same/prior-session exit in validation union")
    write_parquet(union.drop(columns="priority"), UNION)
    pooled = metrics(union)
    annual = {
        str(year): metrics(union.loc[union.signal_date.dt.year.eq(year)])
        for year in (2022, 2023, 2024)
    }
    by_mechanism = {
        str(name): metrics(part) for name, part in union.groupby("mechanism", sort=True)
    }
    written_gates = {
        "completed_gt_50_each_year": all(item["completed"] > 50 for item in annual.values()),
        "pooled_mean_net_gt_4pct": pooled["mean_net"] is not None and pooled["mean_net"] > 0.04,
        "pooled_median_positive": pooled["median_net"] is not None and pooled["median_net"] > 0,
        "severe10_le_20pct": pooled["severe10"] is not None and pooled["severe10"] <= 0.20,
    }
    strict_annual = {
        year: bool(item["mean_net"] is not None and item["mean_net"] > 0.04)
        for year, item in annual.items()
    }
    payload = {
        "experiment": EXPERIMENT,
        "scientific_status": "LATER_PERIOD_CHALLENGE_NOT_PRISTINE_OOS",
        "stage_a_freeze_sha256": sha256(STAGE_A_FREEZE),
        "stage_a": stage_freeze,
        "runner_sha256": sha256(Path(__file__)),
        "bull_outcomes_sha256": sha256(BULL_OUTCOMES),
        "slow_outcomes_sha256": sha256(SLOW_OUTCOMES),
        "bear_fast_outcomes_sha256": sha256(BEAR_FAST_OUTCOMES),
        "union_sha256": sha256(UNION),
        "pooled": pooled,
        "annual": annual,
        "by_mechanism": by_mechanism,
        "written_gates": written_gates,
        "all_written_gates_pass": all(written_gates.values()),
        "each_validation_year_mean_net_gt_4pct": strict_annual,
        "future_market_function": False,
        "2025_2026_signal_read": "NO",
        "verdict": (
            "LATER_PERIOD_EVENT_ECONOMICS_PASS"
            if all(written_gates.values())
            else "LATER_PERIOD_EVENT_ECONOMICS_FAIL"
        ),
    }
    write_json(RESULT, payload)
    payload["result_sha256"] = sha256(RESULT)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("stage-a", "verify-stage-a", "run"))
    args = parser.parse_args()
    if args.stage == "stage-a":
        payload = stage_a()
    elif args.stage == "verify-stage-a":
        payload = verify_stage_a()
    else:
        payload = run_outcomes()
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
