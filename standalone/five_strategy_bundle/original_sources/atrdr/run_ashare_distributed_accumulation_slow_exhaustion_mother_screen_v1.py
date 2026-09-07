#!/usr/bin/env python3
# ruff: noqa: E501
"""Screen two frozen, economically distinct A-share mother signals."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

EXPERIMENT = "ASHARE-DISTRIBUTED-ACCUMULATION-SLOW-EXHAUSTION-MOTHER-SCREEN-V1"
REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
EXPECTED_FREEZE_SHA256 = "6a54a3e82c0f4578526a189d855cc62682c896a9bbec9c17bbe911cb239c4a58"
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
DAILY = (
    DATA_ROOT
    / "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1"
    / "pit_daily_compact_2013_2023.parquet"
)
REGIME = (
    DATA_ROOT
    / "ashare_causal_market_regime_routed_simple_strategy_v1"
    / "stage_a/causal_market_regime_2014_2023.parquet"
)
EXPECTED_DAILY_SHA256 = "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00"
EXPECTED_REGIME_SHA256 = "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a"
OUTPUT_ROOT = DATA_ROOT / "ashare_distributed_accumulation_slow_exhaustion_mother_screen_v1"
CANDIDATES = OUTPUT_ROOT / "development_2014_2020_candidates.parquet"
PATHS = OUTPUT_ROOT / "development_2014_2020_paths.parquet"
OUTCOMES = OUTPUT_ROOT / "development_2014_2020_outcomes.parquet"
RESULT = OUTPUT_ROOT / "result.json"
ROUND_TRIP_COST = 0.004


class ResearchError(RuntimeError):
    """Fail closed on frozen identity, PIT timing, or executable semantics."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inputs() -> dict[str, str]:
    expected = {
        FREEZE: EXPECTED_FREEZE_SHA256,
        DAILY: EXPECTED_DAILY_SHA256,
        REGIME: EXPECTED_REGIME_SHA256,
    }
    actual = {}
    for path, digest in expected.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input: {path}")
        actual[str(path)] = sha256(path)
        if actual[str(path)] != digest:
            raise ResearchError(f"input identity drift: {path}")
    return actual


def connection() -> duckdb.DuckDBPyConnection:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    temp = OUTPUT_ROOT / "duckdb_tmp"
    temp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='10GB'")
    con.execute(f"SET temp_directory='{temp.as_posix()}'")
    return con


def build_candidates() -> pd.DataFrame:
    con = connection()
    query = f"""
    WITH base AS (
      SELECT d.*,
        r.market_regime,r.latest_source_timestamp AS market_latest_source_timestamp,
        count(*) OVER w60 AS prior60_rows,
        lag(d.cal_idx,60) OVER (PARTITION BY d.symbol ORDER BY d.cal_idx) AS lag60_cal_idx_exact,
        min(d.invalid_step_cum) OVER w60 AS prior60_lineage_min,
        max(d.invalid_step_cum) OVER w60 AS prior60_lineage_max,
        bool_and(d.hard_valid AND d.market_rule_valid AND d.corporate_action_valid
                 AND NOT d.corporate_action_blocking AND coalesce(d.corporate_action_count,0)=0)
          OVER w60 AS prior60_lineage_valid,
        max(d.coord_high) OVER w20 AS prior20_high,
        max(d.coord_high) OVER w5 AS prior5_high,
        min(d.coord_low) OVER w5 AS last5_low,
        min(d.coord_low) OVER wprev5 AS previous5_low,
        sum((d.step_return>0)::INT) OVER w20 / 20.0 AS prior20_positive_share,
        max(abs(d.step_return)) OVER w20 AS prior20_max_abs_return,
        sum(CASE WHEN d.step_return<0 THEN d.turnover_fraction ELSE 0 END) OVER w20
          AS prior20_downside_turnover,
        sum(CASE WHEN d.step_return>0 THEN d.turnover_fraction ELSE 0 END) OVER w20
          AS prior20_upside_turnover,
        sum(CASE WHEN d.step_return<0 THEN d.turnover_fraction ELSE 0 END) OVER w5
          AS last5_downside_turnover,
        sum(CASE WHEN d.step_return<0 THEN d.turnover_fraction ELSE 0 END) OVER wprev5
          AS previous5_downside_turnover,
        median(d.turnover_fraction) OVER w20 AS prior20_turnover_median,
        CASE WHEN d.coord_high>d.coord_low
             THEN (d.coord_close-d.coord_low)/(d.coord_high-d.coord_low) END AS close_location
      FROM read_parquet('{DAILY.as_posix()}') d
      LEFT JOIN read_parquet('{REGIME.as_posix()}') r USING(trade_date)
      WHERE d.trade_date BETWEEN DATE '2013-01-01' AND DATE '2020-12-31'
      WINDOW
        w60 AS (PARTITION BY d.symbol ORDER BY d.cal_idx ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING),
        w20 AS (PARTITION BY d.symbol ORDER BY d.cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
        w5 AS (PARTITION BY d.symbol ORDER BY d.cal_idx ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING),
        wprev5 AS (PARTITION BY d.symbol ORDER BY d.cal_idx ROWS BETWEEN 10 PRECEDING AND 6 PRECEDING)
    ), features AS (
      SELECT *,
        prior20_downside_turnover/nullif(prior20_upside_turnover,0) AS downside_upside_turnover_ratio,
        turnover_fraction/nullif(prior20_turnover_median,0) AS turnover_expansion,
        coord_close/nullif(lag20_close,0)-1 AS exact_prior20_return,
        (
          prior60_rows=60 AND lag60_cal_idx_exact=cal_idx-60
          AND prior60_lineage_min=invalid_step_cum AND prior60_lineage_max=invalid_step_cum
          AND prior60_lineage_valid
          AND hard_valid AND current_valid AND current_day_data_tradable AND trade_status=1
          AND market_rule_valid AND corporate_action_valid AND NOT corporate_action_blocking
          AND coalesce(corporate_action_count,0)=0
          AND industry_valid AND historical_identity_valid AND industry_snapshot_id IS NOT NULL
          AND NOT is_st
          AND available_at<=decision_at
          AND market_latest_source_timestamp<=decision_at
          AND round(close*100)<round(up_limit_price*100)
          AND coord_close>0 AND coord_high>=coord_low
          AND turnover_fraction>0 AND prior20_turnover_median>0
        ) AS row_eligible
      FROM base
    ), flagged AS (
      SELECT *,
        (
          row_eligible
          AND market_regime IN ('BULL','TRANSITION')
          AND coord_close/nullif(lag20_close,0)-1 BETWEEN 0.05 AND 0.25
          AND prior20_positive_share>=0.60
          AND prior20_max_abs_return<0.07
          AND prior20_downside_turnover/nullif(prior20_upside_turnover,0)<=0.65
          AND step_return BETWEEN 0.02 AND 0.07
          AND close_location>=0.75
          AND coord_close>prior20_high
          AND turnover_fraction/nullif(prior20_turnover_median,0) BETWEEN 1.20 AND 2.50
        ) AS raw_distributed_accumulation,
        (
          row_eligible
          AND market_regime IN ('BEAR','TRANSITION')
          AND coord_close/nullif(lag20_close,0)-1<=-0.08
          AND last5_low>=previous5_low
          AND last5_downside_turnover<=previous5_downside_turnover
          AND step_return BETWEEN 0.02 AND 0.07
          AND close_location>=0.75
          AND coord_close>prior5_high
          AND turnover_fraction/nullif(prior20_turnover_median,0) BETWEEN 1.00 AND 2.50
        ) AS raw_slow_exhaustion
      FROM features
    ), cooldown AS (
      SELECT *,
        max(CASE WHEN raw_distributed_accumulation THEN cal_idx END) OVER (
          PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS prior_distributed_cal_idx,
        max(CASE WHEN raw_slow_exhaustion THEN cal_idx END) OVER (
          PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS prior_exhaustion_cal_idx
      FROM flagged
    ), long AS (
      SELECT 'DISTRIBUTED_ACCUMULATION_ESCAPE' AS mechanism,* FROM cooldown
      WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
        AND raw_distributed_accumulation
        AND (prior_distributed_cal_idx IS NULL OR cal_idx-prior_distributed_cal_idx>20)
      UNION ALL BY NAME
      SELECT 'SLOW_SUPPLY_EXHAUSTION_TAKEOVER' AS mechanism,* FROM cooldown
      WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
        AND raw_slow_exhaustion
        AND (prior_exhaustion_cal_idx IS NULL OR cal_idx-prior_exhaustion_cal_idx>20)
    )
    SELECT mechanism || '|' || strftime(trade_date,'%Y%m%d') || '|' || symbol AS event_id,
      mechanism,symbol,sleeve,trade_date AS signal_date,cal_idx AS signal_cal_idx,
      decision_at,available_at,market_regime,market_latest_source_timestamp,
      invalid_step_cum,coordinate_factor,coord_open,coord_high,coord_low,coord_close,
      prior20_high,prior5_high,last5_low,previous5_low,exact_prior20_return,
      prior20_positive_share,prior20_max_abs_return,downside_upside_turnover_ratio,
      last5_downside_turnover,previous5_downside_turnover,turnover_expansion,
      close_location,step_return,causal_industry
    FROM long ORDER BY signal_date,mechanism,symbol
    """
    con.execute(f"COPY ({query}) TO '{CANDIDATES.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    candidates = con.execute(
        f"SELECT * FROM read_parquet('{CANDIDATES.as_posix()}') ORDER BY signal_date,mechanism,symbol"
    ).fetch_df()
    con.close()
    for column in (
        "signal_date",
        "decision_at",
        "available_at",
        "market_latest_source_timestamp",
    ):
        candidates[column] = pd.to_datetime(candidates[column])
    if candidates.event_id.duplicated().any():
        raise ResearchError("duplicate candidate identity")
    if candidates.signal_date.dt.year.gt(2020).any():
        raise ResearchError("post-2020 candidate")
    if candidates.available_at.gt(candidates.decision_at).any():
        raise ResearchError("candidate source after decision")
    if candidates.market_latest_source_timestamp.gt(candidates.decision_at).any():
        raise ResearchError("market state after decision")
    return candidates


def build_paths(candidates: pd.DataFrame) -> pd.DataFrame:
    con = connection()
    con.register(
        "events",
        candidates[["event_id", "symbol", "signal_cal_idx"]],
    )
    query = f"""
      SELECT e.event_id,d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
        d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.invalid_step_cum,
        d.coordinate_factor,d.trade_status,d.current_day_data_tradable,d.current_valid,
        d.market_rule_valid,d.corporate_action_count,d.corporate_action_valid,
        d.corporate_action_blocking,d.hard_valid,d.up_limit_price,d.down_limit_price,
        d.available_at,d.decision_at
      FROM events e JOIN read_parquet('{DAILY.as_posix()}') d
        ON e.symbol=d.symbol AND d.cal_idx>e.signal_cal_idx AND d.cal_idx<=e.signal_cal_idx+100
      WHERE d.trade_date<=DATE '2021-12-31'
      ORDER BY e.event_id,d.cal_idx
    """
    con.execute(f"COPY ({query}) TO '{PATHS.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    paths = con.execute(
        f"SELECT * FROM read_parquet('{PATHS.as_posix()}') ORDER BY event_id,cal_idx"
    ).fetch_df()
    con.close()
    for column in ("trade_date", "available_at", "decision_at"):
        paths[column] = pd.to_datetime(paths[column])
    return paths


def legal(row: Any) -> bool:
    required = (
        row.trade_status,
        row.current_day_data_tradable,
        row.current_valid,
        row.market_rule_valid,
        row.corporate_action_valid,
        row.corporate_action_blocking,
        row.hard_valid,
        row.open,
        row.coord_open,
        row.coordinate_factor,
    )
    return bool(
        not any(pd.isna(value) for value in required)
        and int(row.trade_status) == 1
        and row.current_day_data_tradable
        and row.current_valid
        and row.market_rule_valid
        and row.corporate_action_valid
        and not row.corporate_action_blocking
        and int(row.corporate_action_count) == 0
        and row.hard_valid
        and float(row.open) > 0
        and float(row.coord_open) > 0
    )


def buyable(row: Any) -> bool:
    return bool(
        legal(row)
        and np.isfinite(float(row.up_limit_price))
        and round(float(row.open) * 100) < round(float(row.up_limit_price) * 100)
    )


def sellable_open(row: Any) -> bool:
    return bool(
        legal(row)
        and np.isfinite(float(row.down_limit_price))
        and round(float(row.open) * 100) > round(float(row.down_limit_price) * 100)
    )


def replay_one(candidate: Any, path: pd.DataFrame) -> dict[str, Any]:
    target_return = 0.15 if candidate.mechanism == "DISTRIBUTED_ACCUMULATION_ESCAPE" else 0.10
    horizon = 30 if candidate.mechanism == "DISTRIBUTED_ACCUMULATION_ESCAPE" else 20
    common = {
        "event_id": candidate.event_id,
        "mechanism": candidate.mechanism,
        "symbol": candidate.symbol,
        "sleeve": candidate.sleeve,
        "signal_date": candidate.signal_date,
        "signal_cal_idx": int(candidate.signal_cal_idx),
        "market_regime": candidate.market_regime,
        "target_return": target_return,
        "horizon_sessions": horizon,
    }
    lineage = float(candidate.invalid_step_cum)
    pool = path.loc[
        path.cal_idx.gt(candidate.signal_cal_idx) & path.cal_idx.le(candidate.signal_cal_idx + 3)
    ]
    entry = next(
        (
            row
            for row in pool.itertuples(index=False)
            if float(row.invalid_step_cum) == lineage and buyable(row)
        ),
        None,
    )
    if entry is None:
        return {**common, "status": "NO_LEGAL_ENTRY"}
    entry_idx = int(entry.cal_idx)
    entry_price = float(entry.coord_open)
    target_price = entry_price * (1 + target_return)
    exit_row = None
    exit_price = math.nan
    exit_reason = None
    for row in path.loc[path.cal_idx.gt(entry_idx)].itertuples(index=False):
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != lineage:
            return {
                **common,
                "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
                "entry_date": pd.Timestamp(entry.trade_date),
                "entry_cal_idx": entry_idx,
                "entry_price": entry_price,
            }
        if (
            legal(row)
            and np.isfinite(float(row.coord_high))
            and float(row.coord_high) >= target_price
        ):
            exit_row = row
            exit_price = target_price
            exit_reason = f"TARGET_{int(target_return * 100)}"
            break
        if int(row.cal_idx) > entry_idx + horizon and sellable_open(row):
            exit_row = row
            exit_price = float(row.coord_open)
            exit_reason = f"H{horizon}_TIME_STOP"
            break
    if exit_row is None:
        return {
            **common,
            "status": "INCOMPLETE_PATH",
            "entry_date": pd.Timestamp(entry.trade_date),
            "entry_cal_idx": entry_idx,
            "entry_price": entry_price,
        }
    gross = exit_price / entry_price - 1
    return {
        **common,
        "status": "COMPLETED",
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": entry_idx,
        "entry_price": entry_price,
        "exit_date": pd.Timestamp(exit_row.trade_date),
        "exit_cal_idx": int(exit_row.cal_idx),
        "exit_price": float(exit_price),
        "exit_reason": exit_reason,
        "holding_sessions": int(exit_row.cal_idx) - entry_idx,
        "gross_return": gross,
        "net_return": gross - ROUND_TRIP_COST,
    }


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    completed = frame.loc[frame.status.eq("COMPLETED")]
    values = pd.to_numeric(completed.net_return, errors="coerce")
    return {
        "signals": len(frame),
        "completed": len(completed),
        "signal_dates": int(completed.signal_date.nunique()),
        "mean_net": float(values.mean()) if len(values) else None,
        "median_net": float(values.median()) if len(values) else None,
        "win_rate": float(values.gt(0).mean()) if len(values) else None,
        "ge_4pct_rate": float(values.ge(0.04).mean()) if len(values) else None,
        "severe10": float(values.le(-0.10).mean()) if len(values) else None,
        "target_hit": float(completed.exit_reason.str.startswith("TARGET_").mean())
        if len(values)
        else None,
        "mean_holding_sessions": float(completed.holding_sessions.mean()) if len(values) else None,
    }


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    con = connection()
    con.register("frame", frame)
    con.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    candidates = build_candidates()
    paths = build_paths(candidates)
    groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    outcomes = pd.DataFrame(
        [
            replay_one(candidate, groups.get(candidate.event_id, pd.DataFrame()))
            for candidate in candidates.itertuples(index=False)
        ]
    )
    outcomes["signal_date"] = pd.to_datetime(outcomes.signal_date)
    if len(outcomes) != len(candidates) or outcomes.event_id.duplicated().any():
        raise ResearchError("outcome identity mismatch")
    completed = outcomes.loc[outcomes.status.eq("COMPLETED")]
    chronology = {
        "entry_at_or_before_signal": int(
            completed.entry_cal_idx.le(completed.signal_cal_idx).sum()
        ),
        "exit_at_or_before_entry": int(completed.exit_cal_idx.le(completed.entry_cal_idx).sum()),
    }
    if any(chronology.values()):
        raise ResearchError(f"chronology failure: {chronology}")
    write_parquet(outcomes, OUTCOMES)
    mechanism_results = {}
    promotions = []
    for mechanism, part in outcomes.groupby("mechanism", sort=True):
        pooled = metrics(part)
        annual = {
            str(year): metrics(part.loc[part.signal_date.dt.year.eq(year)])
            for year in range(2014, 2021)
        }
        gates = {
            "completed_ge_50_each_year": all(item["completed"] >= 50 for item in annual.values()),
            "pooled_mean_net_gt_4pct": pooled["mean_net"] is not None and pooled["mean_net"] > 0.04,
            "pooled_median_positive": pooled["median_net"] is not None and pooled["median_net"] > 0,
            "severe10_le_20pct": pooled["severe10"] is not None and pooled["severe10"] <= 0.20,
        }
        if all(gates.values()):
            promotions.append(str(mechanism))
        mechanism_results[str(mechanism)] = {
            "pooled": pooled,
            "annual": annual,
            "by_market_regime": {
                str(state): metrics(state_part)
                for state, state_part in part.groupby("market_regime", sort=True)
            },
            "gates": gates,
            "chartbook_authorized": all(gates.values()),
        }
    payload = {
        "experiment": EXPERIMENT,
        "scientific_status": "CONSUMED_2014_2020_CHEAP_MOTHER_SCREEN",
        "source_hashes": source_hashes,
        "candidate_sha256": sha256(CANDIDATES),
        "paths_sha256": sha256(PATHS),
        "outcomes_sha256": sha256(OUTCOMES),
        "runner_sha256": sha256(Path(__file__)),
        "mechanisms": mechanism_results,
        "promoted_to_full_chart_review": promotions,
        "chronology_audit": chronology,
        "status_counts": {
            str(key): int(value)
            for key, value in outcomes.status.value_counts(dropna=False).sort_index().items()
        },
        "2021_signal_read": "NO",
        "2022_2024_signal_or_outcome_read": "NO",
        "future_market_function": False,
        "verdict": "CHART_REVIEW_AUTHORIZED" if promotions else "NO_MOTHER_PASSES_GATE",
    }
    write_json(RESULT, payload)
    payload["result_sha256"] = sha256(RESULT)
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True, default=str))
