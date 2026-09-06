#!/usr/bin/env python3
"""Replay the one frozen chart-derived laggard-diffusion rule compression."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

import run_ashare_first_active_demand_takeover_after_weakness_12m_chart_discovery_v1 as replay_base


EXPERIMENT = "ASHARE-BULL-INDUSTRY-LAGGARD-DIFFUSION-CHART-RULES-V1"
REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
EXPECTED_FREEZE_SHA256 = "13d688e699e958e9151c47ba189a0e1516946e292341a92f7743186e716ca5e3"

DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
DAILY = DATA_ROOT / "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/pit_daily_compact_2013_2023.parquet"
REGIME = DATA_ROOT / "ashare_causal_market_regime_routed_simple_strategy_v1/stage_a/causal_market_regime_2014_2023.parquet"
MOTHER_ROOT = DATA_ROOT / "ashare_bull_industry_laggard_first_demand_diffusion_12m_chart_discovery_v1/development_2014_2020"
MOTHER_CANDIDATES = MOTHER_ROOT / "candidates_frozen.parquet"
MOTHER_OUTCOMES = MOTHER_ROOT / "outcomes.parquet"
MOTHER_REVIEW = MOTHER_ROOT / "review_ledger.parquet"
V19 = DATA_ROOT / "ashare_causal_bear_bull_dual_engine_lane_specific_acceptance_v19r2/development_2014_2020_outcomes.parquet"
SLOW = DATA_ROOT / "ashare_distributed_accumulation_slow_exhaustion_mother_screen_v1/development_2014_2020_outcomes.parquet"

EXPECTED_HASHES = {
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    REGIME: "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
    MOTHER_CANDIDATES: "92d46c214bd20f357077c7ce018ba26fec2a6ca274f539f24efc59d5ef1583f7",
    MOTHER_OUTCOMES: "1787803fba540c1eeb947a3cb7c2ea95b6021be46ebdce7a03057346aa453472",
    MOTHER_REVIEW: "f4a203a355ce61a0210b69209575df0bfd159b57b9835687bce7a9276c1d1547",
    V19: "53d552de91a87b31eb3a81c16d5acd00a44e89c10e95fc31edcf71af7e2e60fe",
    SLOW: "8e410688aba5f07f1a36c87bd0e061c8d052fe6d2b051656b59970589320285d",
}

OUTPUT_ROOT = DATA_ROOT / "ashare_bull_industry_laggard_diffusion_chart_rules_v1/development_2014_2020"
ACCEPTED_CANDIDATES = OUTPUT_ROOT / "accepted_candidates.parquet"
BULL_OUTCOMES = OUTPUT_ROOT / "bull_outcomes.parquet"
COMBINED_LEDGER = OUTPUT_ROOT / "combined_bull_bear_outcomes.parquet"
RESULT = OUTPUT_ROOT / "result.json"


class ResearchError(RuntimeError):
    """Fail closed on identity, PIT chronology, lineage, or execution drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inputs() -> dict[str, str]:
    expected = {FREEZE: EXPECTED_FREEZE_SHA256, **EXPECTED_HASHES}
    actual: dict[str, str] = {}
    for path, identity in expected.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input: {path}")
        value = sha256(path)
        actual[str(path)] = value
        if value != identity:
            raise ResearchError(f"input identity drift: {path}: {value} != {identity}")
    return actual


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.register("frame", frame)
    connection.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    connection.close()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def build_accepted_candidates() -> tuple[pd.DataFrame, dict[str, int]]:
    connection = duckdb.connect()
    result = connection.execute(
        f"""
        WITH mother AS (
          SELECT m.*,
            count(*) OVER (PARTITION BY CAST(signal_date AS DATE)) AS same_date_mother_count
          FROM read_parquet('{MOTHER_CANDIDATES.as_posix()}') m
        ), joined AS (
          SELECT m.*,
            d1.trade_date AS acceptance_date_1,d1.cal_idx AS acceptance_cal_idx_1,
            d1.coord_close AS acceptance_close_1,d1.invalid_step_cum AS acceptance_invalid_cum_1,
            d1.available_at AS acceptance_available_at_1,d1.decision_at AS acceptance_decision_at_1,
            d1.trade_status AS acceptance_trade_status_1,
            d1.current_day_data_tradable AS acceptance_tradable_1,
            d1.market_rule_valid AS acceptance_market_rule_valid_1,
            d1.corporate_action_valid AS acceptance_corporate_action_valid_1,
            d1.corporate_action_blocking AS acceptance_corporate_action_blocking_1,
            d1.current_valid AS acceptance_current_valid_1,d1.hard_valid AS acceptance_hard_valid_1,
            d2.trade_date AS confirmation_date,d2.cal_idx AS confirmation_cal_idx,
            d2.coord_close AS confirmation_coord_close,d2.invalid_step_cum AS confirmation_invalid_step_cum,
            d2.available_at AS confirmation_available_at,d2.decision_at AS confirmation_decision_at,
            d2.trade_status AS confirmation_trade_status,
            d2.current_day_data_tradable AS confirmation_tradable,
            d2.market_rule_valid AS confirmation_market_rule_valid,
            d2.corporate_action_valid AS confirmation_corporate_action_valid,
            d2.corporate_action_blocking AS confirmation_corporate_action_blocking,
            d2.current_valid AS confirmation_current_valid,d2.hard_valid AS confirmation_hard_valid,
            r2.market_regime AS confirmation_market_regime,
            r2.latest_source_timestamp AS confirmation_market_latest_source_timestamp
          FROM mother m
          JOIN read_parquet('{DAILY.as_posix()}') d1
            ON d1.symbol=m.symbol AND d1.cal_idx=m.cal_idx+1
          JOIN read_parquet('{DAILY.as_posix()}') d2
            ON d2.symbol=m.symbol AND d2.cal_idx=m.cal_idx+2
          JOIN read_parquet('{REGIME.as_posix()}') r2
            ON r2.trade_date=d2.trade_date
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
              AND confirmation_invalid_step_cum=invalid_step_cum
              AS passes_coordinate_lineage,
            acceptance_close_1>=coord_close AND confirmation_coord_close>=coord_close
              AS passes_two_session_price_acceptance,
            confirmation_market_regime='BULL' AS passes_confirmation_market_state
          FROM joined
        )
        SELECT
          'BILFDCR-' || strftime(confirmation_date,'%Y%m%d') || '-' || replace(symbol,'.','')
            || '-' || replace(event_id,'BILFD-','') AS event_id,
          event_id AS mother_event_id,symbol,sleeve,industry,
          signal_date AS mother_signal_date,cal_idx AS mother_signal_cal_idx,
          confirmation_date AS signal_date,confirmation_cal_idx AS cal_idx,
          confirmation_invalid_step_cum AS invalid_step_cum,
          confirmation_coord_close AS signal_coord_close,
          confirmation_available_at AS available_at,confirmation_decision_at AS decision_at,
          same_date_mother_count,prior_session_ret20,prior_session_industry_ret20_pct,
          industry_n20,industry_median_ret20,industry_positive_ret20_share,
          market_regime AS mother_market_regime,
          market_median_ret20,market_median_ret60,market_return_acceleration,
          market_positive_ret20_share,market_positive_ret60_share,
          acceptance_date_1,acceptance_close_1,confirmation_coord_close,
          confirmation_market_regime,confirmation_market_latest_source_timestamp,
          passes_diffusion_breadth,passes_market_phase,passes_mature_exhaustion_veto,
          passes_absolute_non_chaser,passes_two_session_data_contract,
          passes_coordinate_lineage,passes_two_session_price_acceptance,
          passes_confirmation_market_state
        FROM flags
        WHERE passes_diffusion_breadth AND passes_market_phase
          AND passes_mature_exhaustion_veto AND passes_absolute_non_chaser
          AND passes_two_session_data_contract AND passes_coordinate_lineage
          AND passes_two_session_price_acceptance AND passes_confirmation_market_state
        ORDER BY signal_date,sleeve,symbol,event_id
        """
    ).fetch_df()
    connection.close()
    date_columns = ("mother_signal_date", "signal_date", "available_at", "decision_at", "acceptance_date_1", "confirmation_market_latest_source_timestamp")
    for column in date_columns:
        result[column] = pd.to_datetime(result[column])
    if result.empty or result.event_id.duplicated().any():
        raise ResearchError("empty or duplicate accepted candidate identities")
    if not result.signal_date.gt(result.mother_signal_date).all():
        raise ResearchError("confirmation does not follow the mother signal")
    if not result.cal_idx.eq(result.mother_signal_cal_idx + 2).all():
        raise ResearchError("confirmation is not the second consecutive exchange session")
    if result.available_at.gt(result.decision_at).any():
        raise ResearchError("confirmation stock data arrived after decision time")
    if result.confirmation_market_latest_source_timestamp.gt(result.decision_at).any():
        raise ResearchError("confirmation market state arrived after decision time")
    if not result.confirmation_market_regime.eq("BULL").all():
        raise ResearchError("non-BULL confirmation escaped the frozen rule")
    if result.signal_date.max() > pd.Timestamp("2020-12-31"):
        raise ResearchError("post-2020 confirmation signal entered development replay")
    if not result.filter(like="passes_").all(axis=None):
        raise ResearchError("an accepted candidate failed a frozen chart rule")
    mother = pd.read_parquet(MOTHER_CANDIDATES, columns=["event_id", "signal_date"])
    mother["signal_date"] = pd.to_datetime(mother.signal_date)
    stage_counts = {
        "mother": int(len(mother)),
        "same_date_breadth": int((mother.groupby("signal_date").event_id.transform("size") >= 6).sum()),
        "accepted": int(len(result)),
    }
    return result, stage_counts


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


def build_combined(bull: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    connection = duckdb.connect()
    connection.register("bull", bull)
    overlap = connection.execute(
        f"""
        WITH bear_fast AS (
          SELECT chart_event_id AS event_id,symbol,sleeve,signal_date,signal_cal_idx,
            'BEAR_FAST_CAPITULATION_ACTIVE_DEMAND' AS mechanism,'BEAR' AS market_regime,
            entry_date,entry_cal_idx,entry_price,exit_date,exit_cal_idx,exit_price,exit_reason,
            holding_sessions,gross_return,net_return,1 AS priority
          FROM read_parquet('{V19.as_posix()}')
          WHERE engine='BEAR_REPAIR' AND status='COMPLETED'
        ), slow AS (
          SELECT event_id,symbol,sleeve,signal_date,signal_cal_idx,
            'BEAR_SLOW_SUPPLY_EXHAUSTION_TAKEOVER' AS mechanism,market_regime,
            entry_date,entry_cal_idx,entry_price,exit_date,exit_cal_idx,exit_price,exit_reason,
            holding_sessions,gross_return,net_return,2 AS priority
          FROM read_parquet('{SLOW.as_posix()}')
          WHERE mechanism='SLOW_SUPPLY_EXHAUSTION_TAKEOVER'
            AND market_regime='BEAR' AND status='COMPLETED'
        ), new_bull AS (
          SELECT event_id,symbol,sleeve,signal_date,cal_idx AS signal_cal_idx,
            'BULL_INDUSTRY_LAGGARD_DIFFUSION_ACCEPTED' AS mechanism,
            'BULL' AS market_regime,entry_date,entry_cal_idx,entry_price,
            exit_date,exit_cal_idx,exit_price,exit_reason,holding_sessions,gross_return,net_return,
            3 AS priority
          FROM bull WHERE status='COMPLETED'
        ), stacked AS (
          SELECT * FROM bear_fast UNION ALL SELECT * FROM slow UNION ALL SELECT * FROM new_bull
        )
        SELECT count(*)-count(DISTINCT symbol || '|' || CAST(signal_date AS VARCHAR)) FROM stacked
        """
    ).fetchone()[0]
    combined = connection.execute(
        f"""
        WITH bear_fast AS (
          SELECT chart_event_id AS event_id,symbol,sleeve,signal_date,signal_cal_idx,
            'BEAR_FAST_CAPITULATION_ACTIVE_DEMAND' AS mechanism,'BEAR' AS market_regime,
            entry_date,entry_cal_idx,entry_price,exit_date,exit_cal_idx,exit_price,exit_reason,
            holding_sessions,gross_return,net_return,1 AS priority
          FROM read_parquet('{V19.as_posix()}')
          WHERE engine='BEAR_REPAIR' AND status='COMPLETED'
        ), slow AS (
          SELECT event_id,symbol,sleeve,signal_date,signal_cal_idx,
            'BEAR_SLOW_SUPPLY_EXHAUSTION_TAKEOVER' AS mechanism,market_regime,
            entry_date,entry_cal_idx,entry_price,exit_date,exit_cal_idx,exit_price,exit_reason,
            holding_sessions,gross_return,net_return,2 AS priority
          FROM read_parquet('{SLOW.as_posix()}')
          WHERE mechanism='SLOW_SUPPLY_EXHAUSTION_TAKEOVER'
            AND market_regime='BEAR' AND status='COMPLETED'
        ), new_bull AS (
          SELECT event_id,symbol,sleeve,signal_date,cal_idx AS signal_cal_idx,
            'BULL_INDUSTRY_LAGGARD_DIFFUSION_ACCEPTED' AS mechanism,
            'BULL' AS market_regime,entry_date,entry_cal_idx,entry_price,
            exit_date,exit_cal_idx,exit_price,exit_reason,holding_sessions,gross_return,net_return,
            3 AS priority
          FROM bull WHERE status='COMPLETED'
        ), stacked AS (
          SELECT * FROM bear_fast UNION ALL SELECT * FROM slow UNION ALL SELECT * FROM new_bull
        ), chosen AS (
          SELECT *,row_number() OVER(
            PARTITION BY symbol,CAST(signal_date AS DATE) ORDER BY priority,event_id
          ) AS dedup_rank
          FROM stacked
        )
        SELECT * EXCLUDE(priority,dedup_rank),'COMPLETED' AS status
        FROM chosen WHERE dedup_rank=1
        ORDER BY signal_date,symbol,event_id
        """
    ).fetch_df()
    connection.close()
    for column in ("signal_date", "entry_date", "exit_date"):
        combined[column] = pd.to_datetime(combined[column])
    if combined.event_id.duplicated().any() or combined.duplicated(["symbol", "signal_date"]).any():
        raise ResearchError("combined ledger identity drift")
    if combined.entry_cal_idx.le(combined.signal_cal_idx).any():
        raise ResearchError("combined ledger contains same/prior-session entry")
    return combined, int(overlap)


def run() -> dict[str, Any]:
    input_hashes = verify_inputs()
    candidates, stage_counts = build_accepted_candidates()
    replay_base.DAILY = DAILY
    bull_outcomes = replay_base.replay(candidates)
    bull_joined = candidates.merge(bull_outcomes, on="event_id", how="left", suffixes=("", "_out"), validate="one_to_one")
    bull_joined["signal_date"] = pd.to_datetime(bull_joined.signal_date)
    if bull_joined.entry_date.notna().any():
        filled = bull_joined.loc[bull_joined.entry_date.notna()]
        if not pd.to_datetime(filled.entry_date).gt(filled.signal_date).all():
            raise ResearchError("bull replay entered on/before confirmation decision")
    combined, overlap = build_combined(bull_joined)
    write_parquet(candidates, ACCEPTED_CANDIDATES)
    write_parquet(bull_joined, BULL_OUTCOMES)
    write_parquet(combined, COMBINED_LEDGER)
    bull_pooled = metrics(bull_joined)
    bull_annual = {
        str(year): metrics(bull_joined.loc[bull_joined.mother_signal_date.dt.year.eq(year)])
        for year in range(2014, 2021)
    }
    combined_pooled = metrics(combined)
    combined_annual = {
        str(year): metrics(combined.loc[combined.signal_date.dt.year.eq(year)])
        for year in range(2014, 2021)
    }
    gates = {
        "completed_gt_50_each_year": all(value["completed"] > 50 for value in combined_annual.values()),
        "pooled_mean_net_gt_4pct": bool(combined_pooled["mean_net"] is not None and combined_pooled["mean_net"] > 0.04),
        "pooled_median_positive": bool(combined_pooled["median_net"] is not None and combined_pooled["median_net"] > 0),
        "severe10_lte_20pct": bool(combined_pooled["severe10"] is not None and combined_pooled["severe10"] <= 0.20),
    }
    payload = {
        "experiment": EXPERIMENT,
        "scientific_status": "CONSUMED_2014_2020_POST_CHART_RULE_REPLAY",
        "freeze_sha256": EXPECTED_FREEZE_SHA256,
        "input_hashes": input_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "stage_counts": stage_counts,
        "bull": {"pooled": bull_pooled, "annual": bull_annual},
        "combined": {"pooled": combined_pooled, "annual": combined_annual},
        "same_symbol_date_overlap_removed": overlap,
        "gates": gates,
        "all_gates_pass": all(gates.values()),
        "future_market_function": False,
        "max_mother_signal_date": str(candidates.mother_signal_date.max().date()),
        "max_confirmation_signal_date": str(candidates.signal_date.max().date()),
        "max_bull_outcome_date": str(pd.to_datetime(bull_joined.exit_date).max().date()),
        "max_combined_outcome_date": str(pd.to_datetime(combined.exit_date).max().date()),
        "2021_signal_read": "NO",
        "2021_outcome_read": "YES_THROUGH_2021_01_21_FOR_FROZEN_2020_BEAR_SIGNAL_LIFECYCLES",
        "post_2021_signal_or_outcome_read": "NO",
        "2022_2024_signal_or_outcome_read": "NO",
        "later_period_status": "AUTHORIZED" if all(gates.values()) else "CLOSED",
        "verdict": "DEVELOPMENT_GATE_PASS" if all(gates.values()) else "DEVELOPMENT_GATE_FAIL_NO_RESCUE",
    }
    write_json(RESULT, payload)
    payload["accepted_candidates_sha256"] = sha256(ACCEPTED_CANDIDATES)
    payload["bull_outcomes_sha256"] = sha256(BULL_OUTCOMES)
    payload["combined_ledger_sha256"] = sha256(COMBINED_LEDGER)
    payload["result_sha256"] = sha256(RESULT)
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True, default=str))
