#!/usr/bin/env python3
"""Freeze outcome-blind annual Amihud illiquidity mother candidates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb


EXPERIMENT = "ASHARE-ANNUAL-AMIHUD-ILLIQUIDITY-COMPENSATION-MOTHER-V1"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
DAILY = DATA_ROOT / (
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
REGIME = DATA_ROOT / (
    "ashare_causal_market_regime_routed_simple_strategy_v1/"
    "stage_a/causal_market_regime_2014_2023.parquet"
)
OUTPUT_ROOT = DATA_ROOT / "ashare_annual_amihud_illiquidity_compensation_mother_v1"
CANDIDATES = OUTPUT_ROOT / "stage_a/candidates_frozen.parquet"
FREEZE = OUTPUT_ROOT / "stage_a/stage_a_freeze.json"
EXPECTED_HASHES = {
    SPEC: "91acf13d0cb0dd1995ed119ca65eba59f1e652b90ab93eaa5328eb47cb13969d",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    REGIME: "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
}


class ResearchError(RuntimeError):
    """Fail closed on frozen identity, timing, or candidate semantics."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inputs() -> dict[str, str]:
    actual: dict[str, str] = {}
    for path, expected in EXPECTED_HASHES.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input: {path}")
        actual[str(path)] = sha256(path)
        if actual[str(path)] != expected:
            raise ResearchError(
                f"frozen input drift: {path}: {actual[str(path)]} != {expected}"
            )
    return actual


def annual_measure_sql() -> str:
    """Return the exact canonical daily-to-annual aggregation expression."""
    return "avg(abs(step_return) / amount)"


def build(con: duckdb.DuckDBPyConnection) -> None:
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    query = f"""
      WITH year_ends AS (
        SELECT year(trade_date) AS formation_year,
          max(trade_date) AS decision_date,
          max(cal_idx) AS decision_cal_idx
        FROM read_parquet('{DAILY.as_posix()}')
        WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2019-12-31'
        GROUP BY 1
      ), annual AS (
        SELECT symbol,year(trade_date) AS formation_year,
          min(trade_date) AS formation_start_date,
          max(trade_date) AS formation_end_date,
          count(*) AS valid_daily_observations,
          {annual_measure_sql()} AS annual_amihud
        FROM read_parquet('{DAILY.as_posix()}')
        WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2019-12-31'
          AND sleeve IN ('MAIN','CHINEXT')
          AND trade_status=1 AND current_day_data_tradable
          AND current_valid AND history_valid AND market_rule_valid
          AND historical_identity_valid AND hard_valid
          AND corporate_action_valid AND NOT corporate_action_blocking
          AND coalesce(corporate_action_count,0)=0
          AND available_at<=decision_at
          AND amount>0 AND step_return IS NOT NULL AND isfinite(step_return)
        GROUP BY symbol,year(trade_date)
        HAVING count(*)>=200 AND {annual_measure_sql()}>0
      ), eligible AS (
        SELECT a.symbol,a.formation_year,a.formation_start_date,
          a.formation_end_date,a.valid_daily_observations,a.annual_amihud,
          y.decision_date,y.decision_cal_idx,
          d.sleeve,d.causal_industry,d.industry_snapshot_id,
          d.decision_at,d.available_at,d.invalid_step_cum,d.coordinate_factor,
          d.open,d.high,d.low,d.close,d.coord_open,d.coord_high,d.coord_low,
          d.coord_close,d.volume,d.amount,d.turnover_fraction,d.step_return,
          d.ret20,d.ret60
        FROM annual a
        JOIN year_ends y USING(formation_year)
        JOIN read_parquet('{DAILY.as_posix()}') d
          ON d.symbol=a.symbol AND d.trade_date=y.decision_date
        WHERE d.sleeve IN ('MAIN','CHINEXT') AND NOT d.is_st
          AND d.trade_status=1 AND d.current_day_data_tradable
          AND d.current_valid AND d.history_valid AND d.market_rule_valid
          AND d.historical_identity_valid AND d.hard_valid
          AND d.corporate_action_valid AND NOT d.corporate_action_blocking
          AND coalesce(d.corporate_action_count,0)=0
          AND d.available_at<=d.decision_at AND d.amount>0
          AND d.causal_industry IS NOT NULL
          AND d.industry_snapshot_id IS NOT NULL
      ), ranked AS (
        SELECT *,ntile(5) OVER (
          PARTITION BY formation_year ORDER BY annual_amihud DESC,symbol
        ) AS illiquidity_quintile
        FROM eligible
      )
      SELECT concat(r.symbol,'|',cast(r.decision_date AS VARCHAR)) AS event_id,
        r.formation_year+1 AS portfolio_year,r.formation_year,
        r.formation_start_date,r.formation_end_date,r.valid_daily_observations,
        r.annual_amihud,r.illiquidity_quintile,
        r.symbol,r.sleeve,r.causal_industry,r.industry_snapshot_id,
        r.decision_date AS signal_date,r.decision_cal_idx AS signal_cal_idx,
        r.decision_at,r.available_at,r.invalid_step_cum,r.coordinate_factor,
        r.open,r.high,r.low,r.close,r.coord_open,r.coord_high,r.coord_low,
        r.coord_close,r.volume,r.amount,r.turnover_fraction,r.step_return,
        r.ret20,r.ret60,
        m.market_regime,m.market_median_ret20,m.market_median_ret60,
        m.market_positive_ret20_share,m.market_positive_ret60_share,
        m.latest_source_timestamp AS market_latest_source_timestamp
      FROM ranked r
      JOIN read_parquet('{REGIME.as_posix()}') m ON m.trade_date=r.decision_date
      WHERE r.illiquidity_quintile=1
        AND m.latest_source_timestamp<=r.decision_at
      ORDER BY portfolio_year,signal_date,symbol,event_id
    """
    con.execute(
        f"COPY ({query}) TO '{CANDIDATES.as_posix()}' "
        "(FORMAT PARQUET, COMPRESSION ZSTD)"
    )


def summarize(
    con: duckdb.DuckDBPyConnection, source_hashes: dict[str, str]
) -> dict[str, Any]:
    row = con.execute(
        f"""SELECT count(*),count(*)-count(DISTINCT event_id),
          min(portfolio_year),max(portfolio_year),
          count(*) FILTER(WHERE portfolio_year<2015 OR portfolio_year>2020),
          count(*) FILTER(WHERE formation_year<>portfolio_year-1),
          count(*) FILTER(WHERE formation_end_date<>signal_date),
          count(*) FILTER(WHERE valid_daily_observations<200),
          count(*) FILTER(WHERE annual_amihud<=0 OR annual_amihud IS NULL),
          count(*) FILTER(WHERE illiquidity_quintile<>1),
          count(*) FILTER(WHERE available_at>decision_at
             OR market_latest_source_timestamp>decision_at)
        FROM read_parquet('{CANDIDATES.as_posix()}')"""
    ).fetchone()
    audit = {
        "candidates": int(row[0]),
        "duplicates": int(row[1]),
        "minimum_portfolio_year": int(row[2]),
        "maximum_portfolio_year": int(row[3]),
        "portfolio_year_failures": int(row[4]),
        "formation_year_failures": int(row[5]),
        "decision_date_failures": int(row[6]),
        "minimum_observation_failures": int(row[7]),
        "measure_failures": int(row[8]),
        "quintile_failures": int(row[9]),
        "timing_failures": int(row[10]),
    }
    failure_keys = [key for key in audit if key not in {
        "candidates", "minimum_portfolio_year", "maximum_portfolio_year"
    }]
    if audit["candidates"] == 0 or any(audit[key] for key in failure_keys):
        raise ResearchError(f"candidate audit failed: {audit}")
    annual_rows = con.execute(
        f"""SELECT portfolio_year,count(*),count(DISTINCT symbol),
          count(DISTINCT signal_date),min(valid_daily_observations),
          median(annual_amihud),max(annual_amihud)
        FROM read_parquet('{CANDIDATES.as_posix()}')
        GROUP BY 1 ORDER BY 1"""
    ).fetchall()
    annual = {
        str(year): {
            "candidates": int(count),
            "symbols": int(symbols),
            "decision_dates": int(dates),
            "minimum_valid_daily_observations": int(minimum_observations),
            "median_annual_amihud": float(median_measure),
            "maximum_annual_amihud": float(maximum_measure),
        }
        for year, count, symbols, dates, minimum_observations,
        median_measure, maximum_measure in annual_rows
    }
    return {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_MOTHER_CANDIDATE_FREEZE",
        "source_hashes": source_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "candidate_path": str(CANDIDATES),
        "candidate_sha256": sha256(CANDIDATES),
        "audit": audit,
        "annual": annual,
        "outcomes_read": "NO",
        "post_2020_portfolio_year_read": "NO",
        "post_2023_outcome_read": "NO",
        "cy011_read": "NO",
    }


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_ROOT / "duckdb_tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='10GB'")
    con.execute(f"SET temp_directory='{temporary.as_posix()}'")
    build(con)
    result = summarize(con, source_hashes)
    con.close()
    FREEZE.parent.mkdir(parents=True, exist_ok=True)
    FREEZE.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result["freeze_sha256"] = sha256(FREEZE)
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True))
