#!/usr/bin/env python3
"""Freeze the outcome-blind long-suspension reopening mother events."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb


EXPERIMENT = "ASHARE-LONG-SUSPENSION-REOPENING-PRICE-DISCOVERY-MOTHER-V1"
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
OUTPUT_ROOT = DATA_ROOT / "ashare_long_suspension_reopening_price_discovery_mother_v1"
CANDIDATES = OUTPUT_ROOT / "stage_a/candidates_frozen.parquet"
FREEZE = OUTPUT_ROOT / "stage_a/stage_a_freeze.json"
EXPECTED_HASHES = {
    SPEC: "25f9ea72762bb092df739c7ca4bba7bfca2d7d68083f420ee12c0756200d8365",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    REGIME: "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
}


class ResearchError(RuntimeError):
    """Fail closed on frozen identity, PIT timing, or event semantics."""


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


def connection() -> duckdb.DuckDBPyConnection:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_ROOT / "duckdb_tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='10GB'")
    con.execute(f"SET temp_directory='{temporary.as_posix()}'")
    return con


def build(con: duckdb.DuckDBPyConnection) -> None:
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    query = f"""
      WITH ordered AS (
        SELECT d.*,
          lag(trade_status,1) OVER w AS previous_trade_status,
          max(CASE WHEN trade_status=1 THEN 1 ELSE 0 END)
            OVER (w ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) AS any_trade_previous5,
          lag(cal_idx,5) OVER w AS lag5_cal_idx,
          lag(cal_idx,125) OVER w AS lag125_cal_idx,
          lag(invalid_step_cum,125) OVER w AS lag125_invalid_step_cum,
          last_value(CASE WHEN trade_status=1 AND coord_close>0
            THEN trade_date END IGNORE NULLS)
            OVER (w ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)
            AS pre_suspension_trade_date,
          last_value(CASE WHEN trade_status=1 AND coord_close>0
            THEN cal_idx END IGNORE NULLS)
            OVER (w ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)
            AS pre_suspension_cal_idx,
          last_value(CASE WHEN trade_status=1 AND coord_close>0
            THEN coord_close END IGNORE NULLS)
            OVER (w ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)
            AS pre_suspension_close,
          last_value(CASE WHEN trade_status=1 AND coord_close>0
            THEN invalid_step_cum END IGNORE NULLS)
            OVER (w ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)
            AS pre_suspension_invalid_step_cum
        FROM read_parquet('{DAILY.as_posix()}') d
        WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2020-12-31'
        WINDOW w AS (PARTITION BY symbol ORDER BY cal_idx)
      ), reopening AS (
        SELECT *,
          cal_idx-pre_suspension_cal_idx-1 AS suspension_market_sessions,
          coord_open/pre_suspension_close-1 AS reopening_open_return,
          coord_close/pre_suspension_close-1 AS reopening_close_return,
          CASE WHEN coord_high>coord_low
            THEN (coord_close-coord_low)/(coord_high-coord_low)
            ELSE NULL END AS close_location
        FROM ordered
        WHERE trade_date BETWEEN DATE '2015-01-01' AND DATE '2020-12-31'
          AND trade_status=1 AND previous_trade_status<>1
          AND any_trade_previous5=0 AND lag5_cal_idx=cal_idx-5
          AND lag125_cal_idx=cal_idx-125
          AND invalid_step_cum=lag125_invalid_step_cum
          AND invalid_step_cum=pre_suspension_invalid_step_cum
          AND hard_valid AND current_valid AND current_day_data_tradable
          AND market_rule_valid AND corporate_action_valid
          AND NOT corporate_action_blocking
          AND coalesce(corporate_action_count,0)=0
          AND historical_identity_valid AND industry_valid
          AND causal_industry IS NOT NULL AND industry_snapshot_id IS NOT NULL
          AND NOT is_st AND available_at<=decision_at
          AND coord_open>0 AND coord_high>=coord_low AND coord_close>0
          AND pre_suspension_close>0
      )
      SELECT r.symbol || '|' || strftime(r.pre_suspension_trade_date,'%Y%m%d')
          || '|' || strftime(r.trade_date,'%Y%m%d') AS event_id,
        r.symbol,r.sleeve,r.causal_industry,r.industry_snapshot_id,
        r.pre_suspension_trade_date,r.pre_suspension_cal_idx,
        r.pre_suspension_close,r.suspension_market_sessions,
        r.trade_date AS signal_date,r.cal_idx AS signal_cal_idx,
        r.decision_at,r.available_at,r.invalid_step_cum,r.coordinate_factor,
        r.open,r.high,r.low,r.close,
        r.coord_open,r.coord_high,r.coord_low,r.coord_close,
        r.volume,r.amount,r.turnover_fraction,r.step_return,r.ret20,r.ret60,
        r.reopening_open_return,r.reopening_close_return,r.close_location,
        m.market_regime,m.market_median_ret20,m.market_median_ret60,
        m.market_positive_ret20_share,m.market_positive_ret60_share,
        m.latest_source_timestamp AS market_latest_source_timestamp
      FROM reopening r
      JOIN read_parquet('{REGIME.as_posix()}') m ON r.trade_date=m.trade_date
      WHERE m.latest_source_timestamp<=r.decision_at
      ORDER BY signal_date,symbol,event_id
    """
    con.execute(
        f"COPY ({query}) TO '{CANDIDATES.as_posix()}' "
        "(FORMAT PARQUET, COMPRESSION ZSTD)"
    )


def summarize(con: duckdb.DuckDBPyConnection, source_hashes: dict[str, str]) -> dict[str, Any]:
    audit_row = con.execute(
        f"""SELECT count(*),count(*)-count(DISTINCT event_id),
          count(*) FILTER(WHERE signal_date>DATE '2020-12-31'),
          count(*) FILTER(WHERE available_at>decision_at
             OR market_latest_source_timestamp>decision_at),
          count(*) FILTER(WHERE suspension_market_sessions<5),
          count(*) FILTER(WHERE pre_suspension_cal_idx>=signal_cal_idx),
          count(*) FILTER(WHERE pre_suspension_close<=0),
          count(*) FILTER(WHERE invalid_step_cum IS NULL)
        FROM read_parquet('{CANDIDATES.as_posix()}')"""
    ).fetchone()
    audit = {
        "events": int(audit_row[0]),
        "duplicates": int(audit_row[1]),
        "post_2020_signals": int(audit_row[2]),
        "timing_failures": int(audit_row[3]),
        "short_suspension_failures": int(audit_row[4]),
        "reference_chronology_failures": int(audit_row[5]),
        "invalid_reference_prices": int(audit_row[6]),
        "missing_lineage": int(audit_row[7]),
    }
    if any(audit[key] for key in audit if key != "events"):
        raise ResearchError(f"candidate audit failed: {audit}")
    rows = con.execute(
        f"""SELECT year(signal_date),count(*),count(DISTINCT symbol),
          count(DISTINCT signal_date),
          sum(CASE WHEN reopening_close_return>0 THEN 1 ELSE 0 END),
          sum(CASE WHEN reopening_close_return<0 THEN 1 ELSE 0 END),
          median(reopening_close_return)
        FROM read_parquet('{CANDIDATES.as_posix()}')
        GROUP BY 1 ORDER BY 1"""
    ).fetchall()
    annual = {
        str(year): {
            "events": int(events),
            "symbols": int(symbols),
            "dates": int(dates),
            "positive_reopening": int(positive),
            "negative_reopening": int(negative),
            "median_reopening_close_return": float(median_return),
        }
        for year, events, symbols, dates, positive, negative, median_return in rows
    }
    return {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_MOTHER_EVENT_FREEZE",
        "source_hashes": source_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "candidate_sha256": sha256(CANDIDATES),
        "audit": audit,
        "annual": annual,
        "outcomes_read": "NO",
        "post_2020_signal_or_outcome_read": "NO",
        "future_market_function": False,
        "cy011_read": "NO",
    }


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    con = connection()
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
