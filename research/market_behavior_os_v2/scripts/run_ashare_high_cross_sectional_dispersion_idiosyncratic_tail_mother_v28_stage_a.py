#!/usr/bin/env python3
"""Build the outcome-blind V28 high-dispersion idiosyncratic-tail mother."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


EXPERIMENT = "ASHARE-HIGH-CROSS-SECTIONAL-DISPERSION-IDIOSYNCRATIC-TAIL-MOTHER-V28"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
OUT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_high_cross_sectional_dispersion_idiosyncratic_tail_mother_v28/stage_a"
)
CANDIDATES = OUT / "candidates_frozen.parquet"
FREEZE = OUT / "stage_a_freeze.json"
EXPECTED_SPEC = "907508790f8f46ff29c32ea0af3c98d87c84715c333967e27f77e260bbfba196"
EXPECTED_DAILY = "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00"
YEARS = tuple(range(2014, 2021))


class ResearchError(RuntimeError):
    """Fail closed on identity, history, timing, or candidate drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify() -> dict[str, str]:
    actual = {"spec": sha256(SPEC), "daily": sha256(DAILY)}
    if actual != {"spec": EXPECTED_SPEC, "daily": EXPECTED_DAILY}:
        raise ResearchError(f"frozen input identity drift: {actual}")
    return actual


def connect() -> duckdb.DuckDBPyConnection:
    OUT.mkdir(parents=True, exist_ok=True)
    temp = OUT / "duckdb_tmp"
    temp.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute("SET threads=4")
    connection.execute("SET memory_limit='10GB'")
    connection.execute(f"SET temp_directory='{temp.as_posix()}'")
    return connection


def raw_candidates(connection: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return connection.execute(
        f"""
        WITH history AS (
          SELECT d.*,
            count(*) OVER w60 AS prior60_rows,
            lag(cal_idx,60) OVER (PARTITION BY symbol ORDER BY cal_idx) AS lag60_cal_idx,
            min(invalid_step_cum) OVER w60 AS prior60_invalid_min,
            max(invalid_step_cum) OVER w60 AS prior60_invalid_max,
            bool_and(hard_valid AND current_valid AND current_day_data_tradable
              AND market_rule_valid AND corporate_action_valid
              AND NOT corporate_action_blocking
              AND coalesce(corporate_action_count,0)=0
              AND historical_identity_valid AND industry_valid
              AND causal_industry IS NOT NULL
              AND industry_snapshot_id IS NOT NULL
              AND available_at<=decision_at) OVER w60 AS prior60_valid
          FROM read_parquet('{DAILY.as_posix()}') d
          WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2020-12-31'
          WINDOW w60 AS (
            PARTITION BY symbol ORDER BY cal_idx
            ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING
          )
        ), eligible AS (
          SELECT * FROM history
          WHERE prior60_rows=60 AND lag60_cal_idx=cal_idx-60
            AND prior60_invalid_min=invalid_step_cum
            AND prior60_invalid_max=invalid_step_cum AND prior60_valid
            AND hard_valid AND current_valid AND current_day_data_tradable
            AND trade_status=1 AND market_rule_valid AND corporate_action_valid
            AND NOT corporate_action_blocking
            AND coalesce(corporate_action_count,0)=0
            AND historical_identity_valid AND industry_valid
            AND causal_industry IS NOT NULL
            AND industry_snapshot_id IS NOT NULL
            AND NOT is_st AND available_at<=decision_at
            AND coord_open>0 AND coord_high>=coord_low AND coord_close>0
            AND amount>0 AND step_return IS NOT NULL
        ), industry AS (
          SELECT trade_date,cal_idx,causal_industry,
            count(*) AS industry_n,
            median(step_return) AS industry_step_return,
            max(available_at) AS industry_latest_available_at
          FROM eligible
          GROUP BY trade_date,cal_idx,causal_industry
          HAVING count(*)>=10
        ), stock_specific AS (
          SELECT e.*,i.industry_n,i.industry_step_return,
            i.industry_latest_available_at,
            e.step_return-i.industry_step_return AS stock_specific_step_return,
            median(e.amount) OVER (PARTITION BY e.trade_date) AS same_date_median_amount
          FROM eligible e
          JOIN industry i USING(trade_date,cal_idx,causal_industry)
        ), liquid AS (
          SELECT * FROM stock_specific WHERE amount>=same_date_median_amount
        ), market AS (
          SELECT trade_date,cal_idx,count(*) AS eligible_liquid_n,
            count(DISTINCT causal_industry) AS industry_count,
            quantile_cont(stock_specific_step_return,0.75)
              -quantile_cont(stock_specific_step_return,0.25)
              AS stock_specific_dispersion_iqr,
            max(available_at) AS market_latest_available_at
          FROM liquid
          GROUP BY trade_date,cal_idx
          HAVING count(*)>=500 AND count(DISTINCT causal_industry)>=20
        ), causal_state AS (
          SELECT *,count(*) OVER w252 AS prior252_market_rows,
            quantile_cont(stock_specific_dispersion_iqr,0.80) OVER w252
              AS prior252_dispersion_p80,
            lag(cal_idx,252) OVER (ORDER BY cal_idx) AS lag252_cal_idx
          FROM market
          WINDOW w252 AS (
            ORDER BY cal_idx ROWS BETWEEN 252 PRECEDING AND 1 PRECEDING
          )
        ), ranked AS (
          SELECT l.*,m.eligible_liquid_n,m.industry_count,
            m.stock_specific_dispersion_iqr,m.market_latest_available_at,
            m.prior252_market_rows,m.prior252_dispersion_p80,m.lag252_cal_idx,
            ntile(10) OVER (
              PARTITION BY l.trade_date ORDER BY l.stock_specific_step_return
            ) AS stock_specific_decile
          FROM liquid l JOIN causal_state m USING(trade_date,cal_idx)
          WHERE m.prior252_market_rows=252
            AND m.lag252_cal_idx=m.cal_idx-252
            AND m.stock_specific_dispersion_iqr>=m.prior252_dispersion_p80
            AND dayofweek(m.trade_date)=5
        ), tails AS (
          SELECT CASE
              WHEN stock_specific_decile=10 THEN 'IDIOSYNCRATIC_UP_SHOCK'
              WHEN stock_specific_decile=1 THEN 'IDIOSYNCRATIC_DOWN_SHOCK'
            END AS direction_lane,
            *,row_number() OVER (
              PARTITION BY trade_date,causal_industry,stock_specific_decile
              ORDER BY amount DESC,symbol
            ) AS industry_lane_rank
          FROM ranked WHERE stock_specific_decile IN (1,10)
        )
        SELECT direction_lane || '|' || strftime(trade_date,'%Y%m%d') || '|'
            || causal_industry || '|' || symbol AS event_id,
          direction_lane,symbol,sleeve,causal_industry,
          trade_date AS signal_date,cal_idx AS signal_cal_idx,
          decision_at,available_at,industry_snapshot_id,
          industry_n,industry_step_return,stock_specific_step_return,
          stock_specific_decile,eligible_liquid_n,industry_count,
          stock_specific_dispersion_iqr,prior252_dispersion_p80,
          prior252_market_rows,lag252_cal_idx,
          industry_latest_available_at,market_latest_available_at,
          same_date_median_amount,amount,turnover_fraction,
          invalid_step_cum,coordinate_factor,
          coord_open,coord_high,coord_low,coord_close,step_return
        FROM tails
        WHERE industry_lane_rank=1
          AND trade_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
        ORDER BY signal_date,direction_lane,causal_industry,symbol
        """
    ).fetch_df()


def apply_cooldown(frame: pd.DataFrame) -> pd.DataFrame:
    selected: list[int] = []
    last_cal_idx: dict[str, int] = {}
    ordered = frame.sort_values(
        ["signal_cal_idx", "direction_lane", "causal_industry", "symbol"],
        kind="mergesort",
    ).reset_index(drop=True)
    for index, row in ordered.iterrows():
        symbol = str(row.symbol)
        cal_idx = int(row.signal_cal_idx)
        if symbol in last_cal_idx and cal_idx <= last_cal_idx[symbol] + 20:
            continue
        selected.append(index)
        last_cal_idx[symbol] = cal_idx
    return ordered.loc[selected].reset_index(drop=True)


def write_parquet(connection: duckdb.DuckDBPyConnection, frame: pd.DataFrame) -> None:
    connection.register("candidates", frame)
    connection.execute(
        f"COPY candidates TO '{CANDIDATES.as_posix()}' "
        "(FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    connection.unregister("candidates")


def summarize(frame: pd.DataFrame, source_hashes: dict[str, str]) -> dict[str, Any]:
    for column in (
        "signal_date",
        "decision_at",
        "available_at",
        "industry_latest_available_at",
        "market_latest_available_at",
    ):
        frame[column] = pd.to_datetime(frame[column])
    audit = {
        "rows": int(len(frame)),
        "duplicates": int(frame.event_id.duplicated().sum()),
        "post_2020_signals": int(frame.signal_date.dt.year.gt(2020).sum()),
        "timing_failures": int(
            (
                frame.available_at.gt(frame.decision_at)
                | frame.industry_latest_available_at.gt(frame.decision_at)
                | frame.market_latest_available_at.gt(frame.decision_at)
            ).sum()
        ),
        "history_failures": int(
            (
                frame.prior252_market_rows.ne(252)
                | frame.lag252_cal_idx.ne(frame.signal_cal_idx - 252)
            ).sum()
        ),
        "non_friday_signals": int(
            frame.signal_date.dt.dayofweek.ne(4).sum()
        ),
        "lane_failures": int(
            (~frame.direction_lane.isin(
                ["IDIOSYNCRATIC_UP_SHOCK", "IDIOSYNCRATIC_DOWN_SHOCK"]
            )).sum()
        ),
    }
    if any(value for key, value in audit.items() if key != "rows"):
        raise ResearchError(f"candidate audit failed: {audit}")

    annual: dict[str, Any] = {}
    gate = True
    for year in YEARS:
        part = frame.loc[frame.signal_date.dt.year.eq(year)]
        annual[str(year)] = {
            "events": int(len(part)),
            "decision_dates": int(part.signal_date.nunique()),
            "symbols": int(part.symbol.nunique()),
            "industries": int(part.causal_industry.nunique()),
            "up_shock_events": int(part.direction_lane.eq("IDIOSYNCRATIC_UP_SHOCK").sum()),
            "down_shock_events": int(part.direction_lane.eq("IDIOSYNCRATIC_DOWN_SHOCK").sum()),
        }
        gate &= len(part) >= 50 and part.signal_date.nunique() >= 5

    return {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_CANDIDATE_IDENTITY_FREEZE",
        "source_hashes": source_hashes,
        "candidate_sha256": sha256(CANDIDATES),
        "audit": audit,
        "annual": annual,
        "stage_a_gate_passed": bool(gate),
        "outcomes_read": False,
        "post_2020_outcome_read": False,
        "next_action": (
            "RENDER_COMPLETE_CHART_CORPUS"
            if gate
            else "CLOSE_BEFORE_CHARTS_NO_DEFINITION_RESCUE"
        ),
    }


def main() -> None:
    source_hashes = verify()
    connection = connect()
    frame = apply_cooldown(raw_candidates(connection))
    write_parquet(connection, frame)
    result = summarize(frame, source_hashes)
    connection.close()
    FREEZE.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
