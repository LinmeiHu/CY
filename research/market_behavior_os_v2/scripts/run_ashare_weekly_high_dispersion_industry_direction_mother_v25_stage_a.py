#!/usr/bin/env python3
"""Freeze outcome-blind 2014-2020 V25 weekly dispersion mother identities."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb


EXPERIMENT = "ASHARE-WEEKLY-HIGH-DISPERSION-INDUSTRY-DIRECTION-MOTHER-V25"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
DAILY = Path("/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/pit_daily_compact_2013_2023.parquet")
OUTPUT_ROOT = Path("/Volumes/quant/CY_quant_research/ashare_weekly_high_dispersion_industry_direction_mother_v25")
CANDIDATES = OUTPUT_ROOT / "stage_a/candidates_frozen.parquet"
FREEZE = OUTPUT_ROOT / "stage_a/stage_a_freeze.json"
EXPECTED_SPEC = "a44eb1175f983084461e98a672ca402f6ed32b94fd786a53d69fe27c226966ec"
EXPECTED_DAILY = "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00"


class ResearchError(RuntimeError):
    """Fail closed on identity, PIT timing, history, or candidate drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify() -> None:
    if sha256(SPEC) != EXPECTED_SPEC or sha256(DAILY) != EXPECTED_DAILY:
        raise ResearchError("frozen input identity drift")


def connection() -> duckdb.DuckDBPyConnection:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    temp = OUTPUT_ROOT / "duckdb_tmp"
    temp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='10GB'")
    con.execute(f"SET temp_directory='{temp.as_posix()}'")
    return con


def build(con: duckdb.DuckDBPyConnection) -> None:
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    query = f"""
    WITH history AS (
      SELECT d.*,
        count(*) OVER w60 AS prior60_rows,
        lag(cal_idx,60) OVER (PARTITION BY symbol ORDER BY cal_idx) AS lag60_cal_idx,
        min(invalid_step_cum) OVER w60 AS prior60_invalid_min,
        max(invalid_step_cum) OVER w60 AS prior60_invalid_max,
        bool_and(hard_valid AND current_valid AND current_day_data_tradable
          AND market_rule_valid AND corporate_action_valid
          AND NOT corporate_action_blocking AND coalesce(corporate_action_count,0)=0
          AND historical_identity_valid AND industry_valid
          AND causal_industry IS NOT NULL AND industry_snapshot_id IS NOT NULL
          AND available_at<=decision_at) OVER w60 AS prior60_valid
      FROM read_parquet('{DAILY.as_posix()}') d
      WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2020-12-31'
      WINDOW w60 AS (PARTITION BY symbol ORDER BY cal_idx
        ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING)
    ), eligible AS (
      SELECT * FROM history
      WHERE prior60_rows=60 AND lag60_cal_idx=cal_idx-60
        AND prior60_invalid_min=invalid_step_cum
        AND prior60_invalid_max=invalid_step_cum AND prior60_valid
        AND hard_valid AND current_valid AND current_day_data_tradable
        AND trade_status=1 AND market_rule_valid AND corporate_action_valid
        AND NOT corporate_action_blocking AND coalesce(corporate_action_count,0)=0
        AND historical_identity_valid AND industry_valid
        AND causal_industry IS NOT NULL AND industry_snapshot_id IS NOT NULL
        AND NOT is_st AND available_at<=decision_at
        AND coord_close>0 AND coord_high>=coord_low AND amount>0
        AND step_return IS NOT NULL
    ), industry_daily AS (
      SELECT trade_date,cal_idx,causal_industry,count(*) AS industry_n,
        median(step_return) AS industry_score,
        max(available_at) AS industry_latest_available_at
      FROM eligible GROUP BY trade_date,cal_idx,causal_industry
      HAVING count(*)>=10
    ), market_daily AS (
      SELECT trade_date,cal_idx,count(*) AS industry_count,
        quantile_cont(industry_score,0.75)-quantile_cont(industry_score,0.25)
          AS industry_dispersion_iqr,
        max(industry_latest_available_at) AS market_latest_available_at
      FROM industry_daily GROUP BY trade_date,cal_idx
      HAVING count(*)>=20
    ), causal_dispersion AS (
      SELECT *,count(*) OVER w252 AS prior252_market_rows,
        quantile_cont(industry_dispersion_iqr,0.80) OVER w252
          AS prior252_dispersion_p80,
        lag(cal_idx,252) OVER (ORDER BY cal_idx) AS lag252_cal_idx
      FROM market_daily
      WINDOW w252 AS (ORDER BY cal_idx ROWS BETWEEN 252 PRECEDING AND 1 PRECEDING)
    ), industry_ranked AS (
      SELECT i.*,m.industry_count,m.industry_dispersion_iqr,
        m.prior252_dispersion_p80,m.prior252_market_rows,m.lag252_cal_idx,
        m.market_latest_available_at,
        ntile(5) OVER (PARTITION BY i.trade_date ORDER BY i.industry_score)
          AS industry_quintile
      FROM industry_daily i JOIN causal_dispersion m USING(trade_date,cal_idx)
      WHERE m.prior252_market_rows=252 AND m.lag252_cal_idx=m.cal_idx-252
        AND m.industry_dispersion_iqr>=m.prior252_dispersion_p80
        AND dayofweek(m.trade_date)=5
    ), lanes AS (
      SELECT CASE WHEN industry_quintile=5 THEN 'CONTINUATION'
                  WHEN industry_quintile=1 THEN 'REVERSAL' END AS direction_lane,
        *
      FROM industry_ranked WHERE industry_quintile IN (1,5)
    ), representatives AS (
      SELECT l.*,e.symbol,e.sleeve,e.decision_at,e.available_at,
        e.industry_snapshot_id,e.invalid_step_cum,e.coordinate_factor,
        e.coord_open,e.coord_high,e.coord_low,e.coord_close,e.step_return,
        e.amount,e.turnover_fraction,
        abs(e.step_return-l.industry_score) AS industry_median_distance,
        row_number() OVER (
          PARTITION BY l.trade_date,l.causal_industry,l.direction_lane
          ORDER BY abs(e.step_return-l.industry_score),e.amount DESC,e.symbol
        ) AS representative_rank
      FROM lanes l JOIN eligible e
        ON e.trade_date=l.trade_date AND e.cal_idx=l.cal_idx
       AND e.causal_industry=l.causal_industry
    )
    SELECT direction_lane || '|' || strftime(trade_date,'%Y%m%d') || '|'
        || causal_industry || '|' || symbol AS event_id,
      direction_lane,symbol,sleeve,causal_industry,trade_date AS signal_date,
      cal_idx AS signal_cal_idx,decision_at,available_at,
      industry_snapshot_id,industry_n,industry_score,industry_quintile,
      industry_count,industry_dispersion_iqr,prior252_dispersion_p80,
      prior252_market_rows,lag252_cal_idx,industry_latest_available_at,
      market_latest_available_at,invalid_step_cum,coordinate_factor,
      coord_open,coord_high,coord_low,coord_close,step_return,amount,
      turnover_fraction,industry_median_distance
    FROM representatives
    WHERE representative_rank=1
      AND trade_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
    ORDER BY signal_date,direction_lane,causal_industry,symbol
    """
    con.execute(f"COPY ({query}) TO '{CANDIDATES.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")


def summarize(con: duckdb.DuckDBPyConnection) -> dict[str, object]:
    audit_row = con.execute(
        f"""SELECT count(*),count(*)-count(DISTINCT event_id),
          count(*) FILTER(WHERE signal_date>DATE '2020-12-31'),
          count(*) FILTER(WHERE available_at>decision_at
             OR industry_latest_available_at>decision_at
             OR market_latest_available_at>decision_at),
          count(*) FILTER(WHERE prior252_market_rows!=252
             OR lag252_cal_idx!=signal_cal_idx-252),
          count(*) FILTER(WHERE dayofweek(signal_date)!=5),
          count(*) FILTER(WHERE industry_quintile NOT IN(1,5))
        FROM read_parquet('{CANDIDATES.as_posix()}')"""
    ).fetchone()
    audit = {
        "rows": int(audit_row[0]), "duplicates": int(audit_row[1]),
        "post_2020_signals": int(audit_row[2]), "timing_failures": int(audit_row[3]),
        "history_failures": int(audit_row[4]), "non_friday_signals": int(audit_row[5]),
        "lane_failures": int(audit_row[6]),
    }
    if any(audit[key] for key in audit if key != "rows"):
        raise ResearchError(f"candidate audit failed: {audit}")
    rows = con.execute(
        f"""SELECT year(signal_date),direction_lane,count(*),
          count(DISTINCT signal_date),count(DISTINCT causal_industry),count(DISTINCT symbol)
        FROM read_parquet('{CANDIDATES.as_posix()}') GROUP BY ALL ORDER BY 1,2"""
    ).fetchall()
    annual: dict[str, dict[str, dict[str, int]]] = {}
    for year,lane,n,dates,industries,symbols in rows:
        annual.setdefault(str(year),{})[str(lane)] = {
            "events": int(n), "dates": int(dates), "industries": int(industries),
            "symbols": int(symbols),
        }
    return {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_CANDIDATE_IDENTITY_FREEZE",
        "spec_sha256": sha256(SPEC), "daily_sha256": sha256(DAILY),
        "candidate_sha256": sha256(CANDIDATES), "audit": audit,
        "annual": annual, "outcomes_read": False,
        "post_2021_signal_or_outcome_read": False,
    }


def main() -> None:
    verify()
    con = connection()
    build(con)
    result = summarize(con)
    con.close()
    FREEZE.write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True))


if __name__ == "__main__":
    main()
