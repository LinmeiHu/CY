#!/usr/bin/env python3
"""Build the frozen outcome-blind 2014-2020 local-industry mother identities."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb

EXPERIMENT = "ASHARE-CAUSAL-LOCAL-INDUSTRY-DEMAND-STATE-MOTHER-V22"
REPO = Path(__file__).resolve().parents[3]
FREEZE = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
EXPECTED_FREEZE_SHA256 = "9098c3380e3b95f09aaee06b47fccbf8504a8eb93e6e69463b598d7c70e92288"
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
DAILY = (
    DATA_ROOT
    / "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1"
    / "pit_daily_compact_2013_2023.parquet"
)
EXPECTED_DAILY_SHA256 = "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00"
OUTPUT_ROOT = DATA_ROOT / "ashare_causal_local_industry_demand_state_mother_v22"
CANDIDATES = OUTPUT_ROOT / "stage_a" / "candidates_frozen.parquet"
STAGE_A_FREEZE = OUTPUT_ROOT / "stage_a" / "stage_a_freeze.json"


class ResearchError(RuntimeError):
    """Fail closed on identity, lineage, or PIT-timing drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(path: Path, expected: str) -> str:
    if not path.is_file():
        raise ResearchError(f"missing frozen input: {path}")
    actual = sha256(path)
    if actual != expected:
        raise ResearchError(f"identity drift: {path}: {actual} != {expected}")
    return actual


def connection() -> duckdb.DuckDBPyConnection:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_ROOT / "duckdb_tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='10GB'")
    con.execute(f"SET temp_directory='{temporary.as_posix()}'")
    return con


def build_candidates() -> None:
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    con = connection()
    query = f"""
    WITH industry_state AS (
      SELECT trade_date,causal_industry,
        count(*) AS industry_n,
        median(ret20) AS industry_median_ret20,
        median(ret60) AS industry_median_ret60,
        avg((ret20>0)::INT) AS industry_positive_ret20_share,
        avg((ret60>0)::INT) AS industry_positive_ret60_share,
        max(available_at) AS industry_latest_source_timestamp
      FROM read_parquet('{DAILY.as_posix()}')
      WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2020-12-31'
        AND hard_valid AND current_valid AND current_day_data_tradable
        AND market_rule_valid AND corporate_action_valid
        AND NOT corporate_action_blocking AND coalesce(corporate_action_count,0)=0
        AND historical_identity_valid AND industry_valid
        AND causal_industry IS NOT NULL AND industry_snapshot_id IS NOT NULL
        AND NOT is_st AND ret20 IS NOT NULL AND ret60 IS NOT NULL
        AND available_at<=decision_at
      GROUP BY trade_date,causal_industry
    ), base AS (
      SELECT d.*,
        s.industry_n,s.industry_median_ret20,s.industry_median_ret60,
        s.industry_positive_ret20_share,s.industry_positive_ret60_share,
        s.industry_latest_source_timestamp,
        count(*) OVER w60 AS prior60_rows,
        lag(d.cal_idx,60) OVER (PARTITION BY d.symbol ORDER BY d.cal_idx)
          AS lag60_cal_idx_exact,
        min(d.invalid_step_cum) OVER w60 AS prior60_lineage_min,
        max(d.invalid_step_cum) OVER w60 AS prior60_lineage_max,
        bool_and(d.hard_valid AND d.market_rule_valid AND d.corporate_action_valid
                 AND NOT d.corporate_action_blocking
                 AND coalesce(d.corporate_action_count,0)=0) OVER w60
          AS prior60_lineage_valid,
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
             THEN (d.coord_close-d.coord_low)/(d.coord_high-d.coord_low) END
          AS close_location
      FROM read_parquet('{DAILY.as_posix()}') d
      LEFT JOIN industry_state s
        ON s.trade_date=d.trade_date AND s.causal_industry=d.causal_industry
      WHERE d.trade_date BETWEEN DATE '2013-01-01' AND DATE '2020-12-31'
      WINDOW
        w60 AS (PARTITION BY d.symbol ORDER BY d.cal_idx
          ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING),
        w20 AS (PARTITION BY d.symbol ORDER BY d.cal_idx
          ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
        w5 AS (PARTITION BY d.symbol ORDER BY d.cal_idx
          ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING),
        wprev5 AS (PARTITION BY d.symbol ORDER BY d.cal_idx
          ROWS BETWEEN 10 PRECEDING AND 6 PRECEDING)
    ), features AS (
      SELECT *,
        prior20_downside_turnover/nullif(prior20_upside_turnover,0)
          AS downside_upside_turnover_ratio,
        turnover_fraction/nullif(prior20_turnover_median,0) AS turnover_expansion,
        coord_close/nullif(lag20_close,0)-1 AS exact_prior20_return,
        CASE
          WHEN industry_n>=10
           AND industry_median_ret20>0 AND industry_median_ret60>0
           AND industry_positive_ret20_share>0.50
           AND industry_positive_ret60_share>0.50 THEN 'LOCAL_BULL'
          WHEN industry_n>=10
           AND industry_median_ret20<=0 AND industry_median_ret60<=0
           AND industry_positive_ret20_share<=0.50
           AND industry_positive_ret60_share<=0.50 THEN 'LOCAL_BEAR'
          WHEN industry_n>=10 THEN 'LOCAL_TRANSITION'
          ELSE 'LOCAL_UNAVAILABLE'
        END AS local_industry_state,
        (
          prior60_rows=60 AND lag60_cal_idx_exact=cal_idx-60
          AND prior60_lineage_min=invalid_step_cum
          AND prior60_lineage_max=invalid_step_cum AND prior60_lineage_valid
          AND hard_valid AND current_valid AND current_day_data_tradable
          AND trade_status=1 AND market_rule_valid AND corporate_action_valid
          AND NOT corporate_action_blocking AND coalesce(corporate_action_count,0)=0
          AND industry_valid AND historical_identity_valid
          AND causal_industry IS NOT NULL AND industry_snapshot_id IS NOT NULL
          AND NOT is_st AND available_at<=decision_at
          AND industry_latest_source_timestamp<=decision_at
          AND round(close*100)<round(up_limit_price*100)
          AND coord_close>0 AND coord_high>=coord_low
          AND turnover_fraction>0 AND prior20_turnover_median>0
        ) AS row_eligible
      FROM base
    ), flagged AS (
      SELECT *,
        (
          row_eligible AND local_industry_state='LOCAL_BULL'
          AND exact_prior20_return BETWEEN 0.05 AND 0.25
          AND prior20_positive_share>=0.60 AND prior20_max_abs_return<0.07
          AND downside_upside_turnover_ratio<=0.65
          AND step_return BETWEEN 0.02 AND 0.07 AND close_location>=0.75
          AND coord_close>prior20_high
          AND turnover_expansion BETWEEN 1.20 AND 2.50
        ) AS raw_local_bull,
        (
          row_eligible AND local_industry_state='LOCAL_BEAR'
          AND exact_prior20_return<=-0.08
          AND last5_low>=previous5_low
          AND last5_downside_turnover<=previous5_downside_turnover
          AND step_return BETWEEN 0.02 AND 0.07 AND close_location>=0.75
          AND coord_close>prior5_high
          AND turnover_expansion BETWEEN 1.00 AND 2.50
        ) AS raw_local_bear
      FROM features
    ), cooldown AS (
      SELECT *,
        max(CASE WHEN raw_local_bull THEN cal_idx END) OVER (
          PARTITION BY symbol ORDER BY cal_idx
          ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS prior_local_bull_cal_idx,
        max(CASE WHEN raw_local_bear THEN cal_idx END) OVER (
          PARTITION BY symbol ORDER BY cal_idx
          ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS prior_local_bear_cal_idx
      FROM flagged
    ), routed AS (
      SELECT 'LOCAL_BULL_DISTRIBUTED_ACCUMULATION_ESCAPE' AS mechanism,*
      FROM cooldown
      WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
        AND raw_local_bull
        AND (prior_local_bull_cal_idx IS NULL OR cal_idx-prior_local_bull_cal_idx>20)
      UNION ALL BY NAME
      SELECT 'LOCAL_BEAR_SLOW_SUPPLY_EXHAUSTION_TAKEOVER' AS mechanism,*
      FROM cooldown
      WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
        AND raw_local_bear
        AND (prior_local_bear_cal_idx IS NULL OR cal_idx-prior_local_bear_cal_idx>20)
    )
    SELECT mechanism || '|' || strftime(trade_date,'%Y%m%d') || '|' || symbol AS event_id,
      mechanism,symbol,sleeve,causal_industry,trade_date AS signal_date,
      cal_idx AS signal_cal_idx,decision_at,available_at,
      industry_latest_source_timestamp,industry_n,industry_median_ret20,
      industry_median_ret60,industry_positive_ret20_share,
      industry_positive_ret60_share,local_industry_state,
      invalid_step_cum,coordinate_factor,coord_open,coord_high,coord_low,coord_close,
      prior20_high,prior5_high,last5_low,previous5_low,exact_prior20_return,
      prior20_positive_share,prior20_max_abs_return,downside_upside_turnover_ratio,
      last5_downside_turnover,previous5_downside_turnover,turnover_expansion,
      close_location,step_return
    FROM routed ORDER BY signal_date,mechanism,symbol
    """
    con.execute(
        f"COPY ({query}) TO '{CANDIDATES.as_posix()}' "
        "(FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    con.close()


def summarize() -> dict[str, object]:
    con = connection()
    total = con.execute(
        f"SELECT count(*) FROM read_parquet('{CANDIDATES.as_posix()}')"
    ).fetchone()[0]
    duplicates = con.execute(
        f"SELECT count(*)-count(DISTINCT event_id) FROM read_parquet('{CANDIDATES.as_posix()}')"
    ).fetchone()[0]
    timing = con.execute(
        f"""SELECT
          count(*) FILTER(WHERE available_at>decision_at),
          count(*) FILTER(WHERE industry_latest_source_timestamp>decision_at),
          count(*) FILTER(WHERE signal_date>DATE '2020-12-31')
        FROM read_parquet('{CANDIDATES.as_posix()}')"""
    ).fetchone()
    annual_rows = con.execute(
        f"""SELECT year(signal_date) AS signal_year,mechanism,count(*) AS signals,
          count(DISTINCT signal_date) AS signal_dates,count(DISTINCT symbol) AS symbols
        FROM read_parquet('{CANDIDATES.as_posix()}')
        GROUP BY ALL ORDER BY 1,2"""
    ).fetchall()
    state_mismatch = con.execute(
        f"""SELECT count(*) FROM read_parquet('{CANDIDATES.as_posix()}')
        WHERE (mechanism LIKE 'LOCAL_BULL%' AND local_industry_state!='LOCAL_BULL')
           OR (mechanism LIKE 'LOCAL_BEAR%' AND local_industry_state!='LOCAL_BEAR')"""
    ).fetchone()[0]
    con.close()
    annual: dict[str, dict[str, dict[str, int]]] = {}
    for year, mechanism, signals, dates, symbols in annual_rows:
        annual.setdefault(str(year), {})[str(mechanism)] = {
            "signals": int(signals),
            "signal_dates": int(dates),
            "symbols": int(symbols),
        }
    combined = {
        year: {
            "signals": sum(item["signals"] for item in mechanisms.values()),
            "signal_dates_note": "not additive across mechanisms",
        }
        for year, mechanisms in annual.items()
    }
    audit = {
        "event_id_duplicates": int(duplicates),
        "available_after_decision": int(timing[0]),
        "industry_state_after_decision": int(timing[1]),
        "post_2020_signal": int(timing[2]),
        "local_state_route_mismatch": int(state_mismatch),
    }
    if any(audit.values()):
        raise ResearchError(f"stage-A audit failed: {audit}")
    return {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_CANDIDATE_IDENTITY_FREEZE",
        "freeze_sha256": sha256(FREEZE),
        "daily_sha256": sha256(DAILY),
        "runner_sha256": sha256(Path(__file__)),
        "candidate_sha256": sha256(CANDIDATES),
        "candidate_count": int(total),
        "annual_by_mechanism": annual,
        "annual_combined": combined,
        "coverage_gate_gt_50_each_year": all(
            item["signals"] > 50 for item in combined.values()
        ) and set(combined) == {str(year) for year in range(2014, 2021)},
        "audit": audit,
        "outcome_columns_read": [],
        "2021_signal_or_outcome_read": "NO",
        "2022_2024_signal_or_outcome_read": "NO",
        "future_market_or_industry_function": False,
    }


def write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run() -> dict[str, object]:
    verify(FREEZE, EXPECTED_FREEZE_SHA256)
    verify(DAILY, EXPECTED_DAILY_SHA256)
    build_candidates()
    result = summarize()
    write_json(STAGE_A_FREEZE, result)
    result["stage_a_freeze_sha256"] = sha256(STAGE_A_FREEZE)
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True))
