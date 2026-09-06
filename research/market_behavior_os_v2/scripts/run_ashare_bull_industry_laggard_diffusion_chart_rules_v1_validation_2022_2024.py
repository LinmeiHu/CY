#!/usr/bin/env python3
"""Freeze identities, then replay the exact 2022-2024 laggard-diffusion challenge."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

import run_ashare_first_active_demand_takeover_after_weakness_12m_chart_discovery_v1 as replay_base


EXPERIMENT = "ASHARE-BULL-INDUSTRY-LAGGARD-DIFFUSION-CHART-RULES-V1-VALIDATION-2022-2024"
REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
CONTRACT = OS_ROOT / "experiments/ASHARE-BULL-INDUSTRY-LAGGARD-DIFFUSION-CHART-RULES-V1-validation-2022-2024_contract.json"
EXPECTED_CONTRACT_SHA256 = "9aa8c253cdff883ea6b75f99e63f5f9c8f1d252fad66c77a4c75b33fe3204da5"

DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
DAILY_OLD = DATA_ROOT / "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/pit_daily_compact_2013_2023.parquet"
DAILY_NEW = DATA_ROOT / "ashare_true_gap_below_l_clean_corridor_v26_validation_2024_2025_v1/pit_daily_qd010_exact_2022_2026q1.parquet"
CY006_2024 = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily/partition_year=2024/data_0.parquet")
REGIME = DATA_ROOT / "ashare_causal_market_regime_routed_simple_strategy_v1/stage_a/causal_market_regime_2014_2023.parquet"
MARKET_2024 = DATA_ROOT / "ashare_causal_bear_strong_bull_dual_engine_v17/challenge_2022_2024/stage_a/causal_market_2024.parquet"
PREVIOUS_VALIDATION = DATA_ROOT / "ashare_causal_bull_bear_three_mechanism_v20_validation_2022_2024/stage_b"
BEAR_FAST = PREVIOUS_VALIDATION / "bear_fast_outcomes.parquet"
BEAR_SLOW = PREVIOUS_VALIDATION / "bear_slow_outcomes.parquet"

EXPECTED_SOURCE_HASHES = {
    DAILY_OLD: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    DAILY_NEW: "95ba886707811da9a0514d1d3a9b2ddf9df5debe69eed4e904502f8f3e1cfca9",
    CY006_2024: "fa10819c433224d3a3da5b1b1bb5222fdc5279aa3636abcbe6f2fa68f7a5771e",
    REGIME: "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
    MARKET_2024: "71d1bb376d1d923c175cce28e0c0623f6fee2b654f123871d4f0d2a061fd14fc",
}
EXPECTED_OUTCOME_HASHES = {
    BEAR_FAST: "eab0a33136070514fbd4337517ea9e970af0798057efaaa7629bc44dce4fcf27",
    BEAR_SLOW: "d43a5ff7c72a92f1f651e6cab06e04d44d2b1bef2c245a30ca9f28e7793ce9ce",
}

OUTPUT_ROOT = DATA_ROOT / "ashare_bull_industry_laggard_diffusion_chart_rules_v1_validation_2022_2024"
STAGE_A_ROOT = OUTPUT_ROOT / "stage_a"
STAGE_B_ROOT = OUTPUT_ROOT / "stage_b"
MOTHERS = STAGE_A_ROOT / "mother_candidates.parquet"
ACCEPTED = STAGE_A_ROOT / "accepted_confirmations.parquet"
STAGE_A_FREEZE = STAGE_A_ROOT / "stage_a_freeze.json"
BULL_OUTCOMES = STAGE_B_ROOT / "bull_outcomes.parquet"
UNION = STAGE_B_ROOT / "validation_union.parquet"
RESULT = STAGE_B_ROOT / "result.json"


class ValidationError(RuntimeError):
    """Fail closed on identity, PIT timing, lineage, or execution drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inputs(include_consumed_bear_outcomes: bool = False) -> dict[str, str]:
    expected = {CONTRACT: EXPECTED_CONTRACT_SHA256, **EXPECTED_SOURCE_HASHES}
    if include_consumed_bear_outcomes:
        expected.update(EXPECTED_OUTCOME_HASHES)
    actual: dict[str, str] = {}
    for path, identity in expected.items():
        if not path.is_file():
            raise ValidationError(f"missing frozen input: {path}")
        value = sha256(path)
        actual[str(path)] = value
        if value != identity:
            raise ValidationError(f"input identity drift: {path}: {value} != {identity}")
    return actual


def connection() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='12GB'")
    return con


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = connection()
    con.register("frame", frame)
    con.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def mother_query(source: str, regime: str, signal_years: str) -> str:
    return f"""
    WITH descriptors AS (
      SELECT d.*,
        median(turnover_fraction) OVER(
          PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS prior20_turn,
        CASE WHEN coord_high>coord_low
          THEN (coord_close-coord_low)/(coord_high-coord_low) END AS close_location
      FROM {source} d
    ), eligible_industry AS (
      SELECT trade_date,cal_idx,symbol,causal_industry,ret20,
        cume_dist() OVER(PARTITION BY trade_date,causal_industry ORDER BY ret20)
          AS industry_ret20_pct
      FROM descriptors
      WHERE current_valid AND hard_valid AND industry_valid AND historical_identity_valid
        AND causal_industry IS NOT NULL AND industry_snapshot_id IS NOT NULL
        AND ret20 IS NOT NULL
    ), industry_state AS (
      SELECT trade_date,causal_industry,count(*) AS industry_n20,
        median(ret20) AS industry_median_ret20,
        avg(CASE WHEN ret20>0 THEN 1.0 ELSE 0.0 END) AS industry_positive_ret20_share
      FROM eligible_industry GROUP BY trade_date,causal_industry
    ), joined AS (
      SELECT d.*,
        p.ret20 AS prior_session_ret20,
        p.industry_ret20_pct AS prior_session_industry_ret20_pct,
        p.trade_date AS prior_session_date,
        s.industry_n20,s.industry_median_ret20,s.industry_positive_ret20_share,
        r.market_regime,r.market_median_ret20,r.market_positive_ret20_share,
        r.market_median_ret60,r.market_positive_ret60_share,
        r.latest_source_timestamp AS market_latest_source_timestamp,
        CASE WHEN d.current_valid AND d.hard_valid AND d.trade_status=1
          AND d.current_day_data_tradable AND d.market_rule_valid
          AND d.corporate_action_valid AND NOT d.corporate_action_blocking
          AND d.industry_valid AND d.historical_identity_valid
          AND d.industry_snapshot_id IS NOT NULL
          AND p.cal_idx=d.cal_idx-1 AND p.causal_industry=d.causal_industry
          AND r.market_regime='BULL'
          AND s.industry_n20>=10 AND s.industry_median_ret20>0
          AND s.industry_positive_ret20_share>=0.55
          AND p.industry_ret20_pct<=0.25
          AND d.step_return>=0.05 AND d.close_location>=0.80
          AND d.prior20_turn>0 AND d.turnover_fraction>=1.5*d.prior20_turn
          AND round(d.close*100)<round(d.up_limit_price*100)
        THEN 1 ELSE 0 END AS raw_event
      FROM descriptors d
      JOIN eligible_industry p ON p.symbol=d.symbol AND p.cal_idx=d.cal_idx-1
      JOIN industry_state s
        ON s.trade_date=d.trade_date AND s.causal_industry=d.causal_industry
      JOIN {regime} r ON r.trade_date=d.trade_date
    ), first_event AS (
      SELECT *,max(raw_event) OVER(
        PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
      ) AS prior20_same_event
      FROM joined
    )
    SELECT
      'BILFD-' || strftime(trade_date,'%Y%m%d') || '-' || replace(symbol,'.','') AS event_id,
      symbol,sleeve,causal_industry AS industry,CAST(trade_date AS DATE) AS signal_date,cal_idx,
      invalid_step_cum,coord_close,available_at,decision_at,prior_session_date,
      prior_session_ret20,prior_session_industry_ret20_pct,
      industry_n20,industry_median_ret20,industry_positive_ret20_share,
      market_regime,market_median_ret20,market_positive_ret20_share,
      market_median_ret60,market_positive_ret60_share,
      market_median_ret20-market_median_ret60 AS market_return_acceleration,
      market_latest_source_timestamp
    FROM first_event
    WHERE raw_event=1 AND coalesce(prior20_same_event,0)=0
      AND year(trade_date) IN ({signal_years})
    ORDER BY signal_date,sleeve,symbol,event_id
    """


def prepare_2024_sources(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW daily_2023_2024 AS
        SELECT d.* FROM read_parquet('{DAILY_OLD.as_posix()}') d
        WHERE year(trade_date)=2023
        UNION ALL BY NAME
        SELECT d.*,s.industry_snapshot_id
        FROM read_parquet('{DAILY_NEW.as_posix()}') d
        JOIN (
          SELECT symbol,trade_date,industry_snapshot_id
          FROM read_parquet('{CY006_2024.as_posix()}')
        ) s ON d.symbol=s.symbol AND CAST(d.trade_date AS DATE)=s.trade_date
        WHERE year(d.trade_date)=2024
        """
    )
    snapshot = con.execute(
        """
        SELECT count(*) AS n,count(industry_snapshot_id) AS known,
          count(DISTINCT industry_snapshot_id) AS identities
        FROM daily_2023_2024 WHERE year(trade_date)=2024
        """
    ).fetchone()
    if snapshot[0] != snapshot[1] or snapshot[2] != 1:
        raise ValidationError(f"invalid 2024 industry snapshot lineage: {snapshot}")
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW daily_2023_2024_featured AS
        WITH lagged AS (
          SELECT d.*,
            lag(coord_close) OVER w AS lag1_close,
            lag(cal_idx) OVER w AS lag1_idx,
            lag(coord_close,20) OVER w AS lag20_close_x,
            lag(cal_idx,20) OVER w AS lag20_idx_x,
            lag(coord_close,60) OVER w AS lag60_close_x,
            lag(cal_idx,60) OVER w AS lag60_idx_x
          FROM daily_2023_2024 d
          WINDOW w AS (PARTITION BY symbol ORDER BY cal_idx)
        )
        SELECT * EXCLUDE(step_return,ret20,ret60),
          CASE WHEN lag1_idx=cal_idx-1 THEN coord_close/nullif(lag1_close,0)-1 END
            AS step_return,
          CASE WHEN lag20_idx_x=cal_idx-20 THEN coord_close/nullif(lag20_close_x,0)-1 END
            AS ret20,
          CASE WHEN lag60_idx_x=cal_idx-60 THEN coord_close/nullif(lag60_close_x,0)-1 END
            AS ret60
        FROM lagged
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW combined_regime AS
        SELECT * FROM read_parquet('{REGIME.as_posix()}') WHERE year(trade_date)=2023
        UNION ALL BY NAME
        SELECT * EXCLUDE(strong_bull,positive_ret20_share_lag5)
        FROM read_parquet('{MARKET_2024.as_posix()}')
        """
    )


def build_mothers() -> pd.DataFrame:
    con = connection()
    historical = con.execute(
        mother_query(
            f"read_parquet('{DAILY_OLD.as_posix()}')",
            f"read_parquet('{REGIME.as_posix()}')",
            "2022,2023",
        )
    ).fetch_df()
    prepare_2024_sources(con)
    current = con.execute(
        mother_query("daily_2023_2024_featured", "combined_regime", "2024")
    ).fetch_df()
    con.close()
    frame = pd.concat([historical, current], ignore_index=True)
    for column in (
        "signal_date", "available_at", "decision_at", "prior_session_date",
        "market_latest_source_timestamp",
    ):
        frame[column] = pd.to_datetime(frame[column])
    frame = frame.sort_values(["signal_date", "sleeve", "symbol", "event_id"], kind="mergesort").reset_index(drop=True)
    frame["same_date_mother_count"] = frame.groupby("signal_date").event_id.transform("size")
    if frame.empty or frame.event_id.duplicated().any():
        raise ValidationError("empty or duplicate mother identities")
    if frame.available_at.gt(frame.decision_at).any():
        raise ValidationError("mother stock data arrived after decision")
    if frame.market_latest_source_timestamp.gt(frame.decision_at).any():
        raise ValidationError("mother market state arrived after decision")
    if not frame.market_regime.eq("BULL").all():
        raise ValidationError("non-BULL mother escaped exact reconstruction")
    if frame.signal_date.max() > pd.Timestamp("2024-12-31"):
        raise ValidationError("post-2024 mother signal read")
    return frame


def build_accepted(mothers: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    con = connection()
    con.register("mothers", mothers)
    final_2024_cal_idx = int(
        con.execute(
            f"SELECT max(cal_idx) FROM read_parquet('{DAILY_NEW.as_posix()}') WHERE trade_date<=DATE '2024-12-31'"
        ).fetchone()[0]
    )
    frame = con.execute(
        f"""
        WITH regime_all AS (
          SELECT * FROM read_parquet('{REGIME.as_posix()}') WHERE year(trade_date) IN (2022,2023)
          UNION ALL BY NAME
          SELECT * EXCLUDE(strong_bull,positive_ret20_share_lag5)
          FROM read_parquet('{MARKET_2024.as_posix()}')
        ), joined AS (
          SELECT m.*,
            d1.trade_date AS acceptance_date_1,d1.cal_idx AS acceptance_cal_idx_1,
            d1.coord_close AS acceptance_close_1,d1.invalid_step_cum AS acceptance_invalid_cum_1,
            d1.trade_status AS acceptance_trade_status_1,
            d1.current_day_data_tradable AS acceptance_tradable_1,
            d1.market_rule_valid AS acceptance_market_rule_valid_1,
            d1.corporate_action_valid AS acceptance_corporate_action_valid_1,
            d1.corporate_action_blocking AS acceptance_corporate_action_blocking_1,
            d1.current_valid AS acceptance_current_valid_1,d1.hard_valid AS acceptance_hard_valid_1,
            d1.available_at AS acceptance_available_at_1,d1.decision_at AS acceptance_decision_at_1,
            d2.trade_date AS confirmation_date,d2.cal_idx AS confirmation_cal_idx,
            d2.coord_close AS confirmation_coord_close,d2.invalid_step_cum AS confirmation_invalid_step_cum,
            d2.trade_status AS confirmation_trade_status,
            d2.current_day_data_tradable AS confirmation_tradable,
            d2.market_rule_valid AS confirmation_market_rule_valid,
            d2.corporate_action_valid AS confirmation_corporate_action_valid,
            d2.corporate_action_blocking AS confirmation_corporate_action_blocking,
            d2.current_valid AS confirmation_current_valid,d2.hard_valid AS confirmation_hard_valid,
            d2.available_at AS confirmation_available_at,d2.decision_at AS confirmation_decision_at,
            r2.market_regime AS confirmation_market_regime,
            r2.latest_source_timestamp AS confirmation_market_latest_source_timestamp
          FROM mothers m
          JOIN read_parquet('{DAILY_NEW.as_posix()}') d1
            ON d1.symbol=m.symbol AND d1.cal_idx=m.cal_idx+1 AND d1.trade_date<=DATE '2024-12-31'
          JOIN read_parquet('{DAILY_NEW.as_posix()}') d2
            ON d2.symbol=m.symbol AND d2.cal_idx=m.cal_idx+2 AND d2.trade_date<=DATE '2024-12-31'
          JOIN regime_all r2 ON r2.trade_date=d2.trade_date
        ), flags AS (
          SELECT *,
            same_date_mother_count>=6 AS passes_diffusion_breadth,
            (market_median_ret20>=0.03 OR market_median_ret20>=market_median_ret60)
              AS passes_market_phase,
            NOT (market_median_ret60>=0.20 AND market_median_ret20<=0.10)
              AS passes_mature_exhaustion_veto,
            prior_session_ret20<0.20 AS passes_absolute_non_chaser,
            acceptance_trade_status_1=1 AND acceptance_tradable_1
              AND acceptance_market_rule_valid_1 AND acceptance_corporate_action_valid_1
              AND NOT acceptance_corporate_action_blocking_1
              AND acceptance_current_valid_1 AND acceptance_hard_valid_1
              AND confirmation_trade_status=1 AND confirmation_tradable
              AND confirmation_market_rule_valid AND confirmation_corporate_action_valid
              AND NOT confirmation_corporate_action_blocking
              AND confirmation_current_valid AND confirmation_hard_valid
              AS passes_two_session_data_contract,
            acceptance_invalid_cum_1=invalid_step_cum
              AND confirmation_invalid_step_cum=invalid_step_cum AS passes_coordinate_lineage,
            acceptance_close_1>=coord_close AND confirmation_coord_close>=coord_close
              AS passes_two_session_price_acceptance,
            confirmation_market_regime='BULL' AS passes_confirmation_market_state,
            (year(confirmation_date)<2024 OR confirmation_cal_idx+34<={final_2024_cal_idx})
              AS passes_lifecycle_completeness
          FROM joined
        )
        SELECT
          'BILFDCR-' || strftime(confirmation_date,'%Y%m%d') || '-' || replace(symbol,'.','')
            || '-' || strftime(signal_date,'%Y%m%d') AS event_id,
          event_id AS mother_event_id,symbol,sleeve,industry,
          signal_date AS mother_signal_date,cal_idx AS mother_signal_cal_idx,
          confirmation_date AS signal_date,confirmation_cal_idx AS cal_idx,
          confirmation_invalid_step_cum AS invalid_step_cum,
          confirmation_coord_close AS signal_coord_close,
          confirmation_available_at AS available_at,confirmation_decision_at AS decision_at,
          same_date_mother_count,prior_session_ret20,prior_session_industry_ret20_pct,
          industry_n20,industry_median_ret20,industry_positive_ret20_share,
          market_regime AS mother_market_regime,market_median_ret20,market_median_ret60,
          market_return_acceleration,market_positive_ret20_share,market_positive_ret60_share,
          acceptance_date_1,acceptance_close_1,confirmation_coord_close,
          confirmation_market_regime,confirmation_market_latest_source_timestamp,
          passes_diffusion_breadth,passes_market_phase,passes_mature_exhaustion_veto,
          passes_absolute_non_chaser,passes_two_session_data_contract,
          passes_coordinate_lineage,passes_two_session_price_acceptance,
          passes_confirmation_market_state,passes_lifecycle_completeness
        FROM flags
        WHERE passes_diffusion_breadth AND passes_market_phase
          AND passes_mature_exhaustion_veto AND passes_absolute_non_chaser
          AND passes_two_session_data_contract AND passes_coordinate_lineage
          AND passes_two_session_price_acceptance AND passes_confirmation_market_state
          AND passes_lifecycle_completeness
        ORDER BY signal_date,sleeve,symbol,event_id
        """
    ).fetch_df()
    con.close()
    for column in (
        "mother_signal_date", "signal_date", "available_at", "decision_at",
        "acceptance_date_1", "confirmation_market_latest_source_timestamp",
    ):
        frame[column] = pd.to_datetime(frame[column])
    if frame.empty or frame.event_id.duplicated().any():
        raise ValidationError("empty or duplicate accepted identities")
    if not frame.cal_idx.eq(frame.mother_signal_cal_idx + 2).all():
        raise ValidationError("acceptance chronology drift")
    if frame.available_at.gt(frame.decision_at).any():
        raise ValidationError("confirmation stock data arrived after decision")
    if frame.confirmation_market_latest_source_timestamp.gt(frame.decision_at).any():
        raise ValidationError("confirmation market state arrived after decision")
    if not frame.filter(like="passes_").all(axis=None):
        raise ValidationError("accepted identity failed a frozen rule")
    return frame, final_2024_cal_idx


def stage_a() -> dict[str, Any]:
    source_hashes = verify_inputs(False)
    mothers = build_mothers()
    accepted, final_2024_cal_idx = build_accepted(mothers)
    write_parquet(mothers, MOTHERS)
    write_parquet(accepted, ACCEPTED)
    payload = {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_FREE_IDENTITY_AND_ACCEPTANCE_FREEZE",
        "contract_sha256": sha256(CONTRACT),
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes,
        "mother_counts": {str(year): int(mothers.signal_date.dt.year.eq(year).sum()) for year in (2022, 2023, 2024)},
        "accepted_counts": {str(year): int(accepted.mother_signal_date.dt.year.eq(year).sum()) for year in (2022, 2023, 2024)},
        "final_2024_cal_idx": final_2024_cal_idx,
        "mother_candidates_sha256": sha256(MOTHERS),
        "accepted_confirmations_sha256": sha256(ACCEPTED),
        "return_or_exit_outcome_attached": "NO",
        "future_market_function": False,
        "max_mother_signal_date": str(mothers.signal_date.max().date()),
        "max_confirmation_date": str(accepted.signal_date.max().date()),
        "2025_2026_signal_or_outcome_read": "NO",
    }
    write_json(STAGE_A_FREEZE, payload)
    payload["stage_a_freeze_sha256"] = sha256(STAGE_A_FREEZE)
    return payload


def verify_stage_a() -> dict[str, Any]:
    verify_inputs(True)
    if not STAGE_A_FREEZE.is_file() or not MOTHERS.is_file() or not ACCEPTED.is_file():
        raise ValidationError("missing Stage-A freeze or identity ledger")
    frozen = json.loads(STAGE_A_FREEZE.read_text(encoding="utf-8"))
    current = {
        "contract_sha256": sha256(CONTRACT),
        "runner_sha256": sha256(Path(__file__)),
        "mother_candidates_sha256": sha256(MOTHERS),
        "accepted_confirmations_sha256": sha256(ACCEPTED),
    }
    drift = {key: {"frozen": frozen.get(key), "current": value} for key, value in current.items() if frozen.get(key) != value}
    if drift:
        raise ValidationError(f"Stage-A identity drift: {drift}")
    return frozen


def replay_bull(candidates: pd.DataFrame) -> pd.DataFrame:
    con = connection()
    con.register("events", candidates[["event_id", "symbol", "cal_idx"]])
    paths = con.execute(
        f"""
        SELECT e.event_id,d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.coordinate_factor,
          d.invalid_step_cum,d.trade_status,d.current_day_data_tradable,d.market_rule_valid,
          d.corporate_action_valid,d.corporate_action_blocking,d.hard_valid,
          d.up_limit_price,d.down_limit_price
        FROM events e JOIN read_parquet('{DAILY_NEW.as_posix()}') d
          ON e.symbol=d.symbol AND d.cal_idx BETWEEN e.cal_idx AND e.cal_idx+75
        WHERE d.trade_date<=DATE '2024-12-31'
        ORDER BY e.event_id,d.cal_idx
        """
    ).fetch_df()
    con.close()
    paths["trade_date"] = pd.to_datetime(paths.trade_date)
    groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    rows = [
        replay_base.replay_one(candidate, groups.get(str(candidate.event_id), pd.DataFrame()))
        for candidate in candidates.itertuples(index=False)
    ]
    outcomes = pd.DataFrame(rows)
    if outcomes.event_id.duplicated().any() or len(outcomes) != len(candidates):
        raise ValidationError("Bull replay identity drift")
    return outcomes


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    complete = frame.loc[frame.status.eq("COMPLETED")].copy()
    values = pd.to_numeric(complete.net_return, errors="coerce")
    return {
        "signals": int(len(frame)),
        "completed": int(len(complete)),
        "signal_dates": int(frame.signal_date.nunique()),
        "symbols": int(frame.symbol.nunique()),
        "mean_net": None if complete.empty else float(values.mean()),
        "median_net": None if complete.empty else float(values.median()),
        "win_rate": None if complete.empty else float(values.gt(0).mean()),
        "ge_4pct_rate": None if complete.empty else float(values.ge(0.04).mean()),
        "severe10": None if complete.empty else float(values.le(-0.10).mean()),
        "target_hit": None if complete.empty else float(complete.exit_reason.fillna("").str.startswith("TARGET").mean()),
        "mean_holding_sessions": None if complete.empty else float(complete.holding_sessions.mean()),
    }


def build_union(bull: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    fast = pd.read_parquet(BEAR_FAST)
    slow = pd.read_parquet(BEAR_SLOW)
    fast = fast.loc[fast.status.eq("COMPLETED")].copy()
    slow = slow.loc[slow.status.eq("COMPLETED")].copy()
    bull_complete = bull.loc[bull.status.eq("COMPLETED")].copy()
    common = [
        "event_id", "symbol", "sleeve", "signal_date", "signal_cal_idx", "mechanism",
        "market_regime", "entry_date", "entry_cal_idx", "entry_price", "exit_date",
        "exit_cal_idx", "exit_price", "exit_reason", "holding_sessions", "gross_return",
        "net_return", "status",
    ]
    fast["priority"] = 1
    slow["priority"] = 2
    bull_complete["signal_cal_idx"] = bull_complete.cal_idx
    bull_complete["mechanism"] = "BULL_INDUSTRY_LAGGARD_DIFFUSION_ACCEPTED"
    bull_complete["market_regime"] = "BULL"
    bull_complete["priority"] = 3
    stacked = pd.concat([fast[common + ["priority"]], slow[common + ["priority"]], bull_complete[common + ["priority"]]], ignore_index=True)
    for column in ("signal_date", "entry_date", "exit_date"):
        stacked[column] = pd.to_datetime(stacked[column])
    duplicate_count = int(stacked.duplicated(["symbol", "signal_date"], keep=False).sum())
    union = (
        stacked.sort_values(["symbol", "signal_date", "priority", "event_id"], kind="mergesort")
        .drop_duplicates(["symbol", "signal_date"], keep="first")
        .sort_values(["signal_date", "symbol", "event_id"], kind="mergesort")
        .reset_index(drop=True)
    )
    if union.entry_cal_idx.le(union.signal_cal_idx).any():
        raise ValidationError("same/prior-session entry in validation union")
    if union.exit_cal_idx.le(union.entry_cal_idx).any():
        raise ValidationError("same/prior-session exit in validation union")
    if union.exit_date.max() > pd.Timestamp("2024-12-31"):
        raise ValidationError("post-2024 outcome entered validation union")
    return union.drop(columns="priority"), duplicate_count


def outcomes() -> dict[str, Any]:
    stage_freeze = verify_stage_a()
    candidates = pd.read_parquet(ACCEPTED)
    for column in ("mother_signal_date", "signal_date", "available_at", "decision_at"):
        candidates[column] = pd.to_datetime(candidates[column])
    bull_raw = replay_bull(candidates)
    bull = candidates.merge(bull_raw, on="event_id", how="left", suffixes=("", "_out"), validate="one_to_one")
    bull["signal_date"] = pd.to_datetime(bull.signal_date)
    if bull.entry_date.notna().any():
        filled = bull.loc[bull.entry_date.notna()]
        if not pd.to_datetime(filled.entry_date).gt(filled.signal_date).all():
            raise ValidationError("Bull trade entered on/before the confirmation close")
    union, duplicate_count = build_union(bull)
    write_parquet(bull, BULL_OUTCOMES)
    write_parquet(union, UNION)
    bull_pooled = metrics(bull)
    bull_annual = {str(year): metrics(bull.loc[bull.mother_signal_date.dt.year.eq(year)]) for year in (2022, 2023, 2024)}
    pooled = metrics(union)
    annual = {str(year): metrics(union.loc[union.signal_date.dt.year.eq(year)]) for year in (2022, 2023, 2024)}
    by_mechanism = {str(name): metrics(part) for name, part in union.groupby("mechanism", sort=True)}
    gates = {
        "completed_gt_50_each_year": all(value["completed"] > 50 for value in annual.values()),
        "pooled_mean_net_gt_4pct": bool(pooled["mean_net"] is not None and pooled["mean_net"] > 0.04),
        "pooled_median_positive": bool(pooled["median_net"] is not None and pooled["median_net"] > 0),
        "severe10_lte_20pct": bool(pooled["severe10"] is not None and pooled["severe10"] <= 0.20),
    }
    strict = {year: bool(value["mean_net"] is not None and value["mean_net"] > 0.04) for year, value in annual.items()}
    payload = {
        "experiment": EXPERIMENT,
        "scientific_status": "LATER_PERIOD_CHALLENGE_NOT_PRISTINE_OOS",
        "stage_a_freeze_sha256": sha256(STAGE_A_FREEZE),
        "stage_a": stage_freeze,
        "runner_sha256": sha256(Path(__file__)),
        "bull": {"pooled": bull_pooled, "annual": bull_annual},
        "combined": {"pooled": pooled, "annual": annual, "by_mechanism": by_mechanism},
        "same_symbol_date_duplicate_rows_before_dedup": duplicate_count,
        "written_gates": gates,
        "all_written_gates_pass": all(gates.values()),
        "each_validation_year_mean_net_gt_4pct": strict,
        "future_market_function": False,
        "max_signal_date": str(union.signal_date.max().date()),
        "max_outcome_date": str(union.exit_date.max().date()),
        "2025_2026_signal_or_outcome_read": "NO",
        "independent_confirmation_claim": False,
        "verdict": "LATER_PERIOD_EVENT_ECONOMICS_PASS" if all(gates.values()) else "LATER_PERIOD_EVENT_ECONOMICS_FAIL_NO_RESCUE",
    }
    write_json(RESULT, payload)
    payload["bull_outcomes_sha256"] = sha256(BULL_OUTCOMES)
    payload["union_sha256"] = sha256(UNION)
    payload["result_sha256"] = sha256(RESULT)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("stage-a", "outcomes"), required=True)
    args = parser.parse_args()
    payload = stage_a() if args.stage == "stage-a" else outcomes()
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
