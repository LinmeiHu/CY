#!/usr/bin/env python3
"""Frozen 2022-2025 challenge for fast distributed-accumulation price discovery."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

import run_ashare_bull_distributed_accumulation_fast_price_discovery_v1 as dev


EXPERIMENT = "ASHARE-BULL-DISTRIBUTED-ACCUMULATION-FAST-PRICE-DISCOVERY-V1-CHALLENGE-2022-2025"
REPO = Path(__file__).resolve().parents[3]
FREEZE = (
    REPO
    / "research/market_behavior_os_v2/experiments/"
    "ASHARE-BULL-DISTRIBUTED-ACCUMULATION-FAST-PRICE-DISCOVERY-V1_freeze.json"
)
EXPECTED_FREEZE_SHA256 = "5da29e3fee47db4c49d27fd5455738b387de3321b256628b596f232fc6f0827e"
DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_clean_corridor_v26_validation_2024_2025_v1/"
    "pit_daily_qd010_exact_2022_2026q1.parquet"
)
EXPECTED_DAILY_SHA256 = "95ba886707811da9a0514d1d3a9b2ddf9df5debe69eed4e904502f8f3e1cfca9"
OUTPUT_ROOT = (
    Path("/Volumes/quant/CY_quant_research")
    / "ashare_bull_distributed_accumulation_fast_price_discovery_v1"
    / "challenge_2022_2025"
)
MARKET = OUTPUT_ROOT / "causal_market.parquet"
MOTHERS = OUTPUT_ROOT / "mother_candidates.parquet"
RULE_PANEL = OUTPUT_ROOT / "causal_rule_panel.parquet"
PATHS = OUTPUT_ROOT / "future_paths.parquet"
OUTCOMES = OUTPUT_ROOT / "outcomes.parquet"
RESULT = OUTPUT_ROOT / "result.json"


def connection() -> duckdb.DuckDBPyConnection:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_ROOT / "duckdb_tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=8")
    con.execute("SET memory_limit='12GB'")
    con.execute(f"SET temp_directory='{temporary.as_posix()}'")
    return con


def feature_ctes() -> str:
    return f"""
    WITH source AS (
      SELECT *
      FROM read_parquet('{DAILY.as_posix()}')
      WHERE trade_date BETWEEN DATE '2022-01-04' AND DATE '2025-12-31'
    ), step_base AS (
      SELECT *,
        CASE WHEN prior_coord_close>0
          THEN coord_close/nullif(prior_coord_close,0)-1 END AS step_return
      FROM source
    ), featured AS (
      SELECT *,
        count(*) OVER w60 AS prior60_rows,
        lag(cal_idx,60) OVER symbol_window AS lag60_cal_idx,
        lag(coord_close,20) OVER symbol_window AS lag20_close,
        lag(cal_idx,20) OVER symbol_window AS lag20_cal_idx,
        lag(invalid_step_cum,20) OVER symbol_window AS lag20_lineage,
        lag(coord_close,60) OVER symbol_window AS lag60_close,
        lag(invalid_step_cum,60) OVER symbol_window AS lag60_lineage,
        min(invalid_step_cum) OVER w60 AS prior60_lineage_min,
        max(invalid_step_cum) OVER w60 AS prior60_lineage_max,
        bool_and(
          hard_valid AND market_rule_valid AND corporate_action_valid
          AND NOT corporate_action_blocking AND coalesce(corporate_action_count,0)=0
          AND available_at<=decision_at
        ) OVER w60 AS prior60_valid,
        max(coord_high) OVER w20 AS prior20_high,
        sum((step_return>0)::INT) OVER w20 / 20.0 AS prior20_positive_share,
        max(abs(step_return)) OVER w20 AS prior20_max_abs_return,
        sum(CASE WHEN step_return<0 THEN turnover_fraction ELSE 0 END) OVER w20
          AS prior20_downside_turnover,
        sum(CASE WHEN step_return>0 THEN turnover_fraction ELSE 0 END) OVER w20
          AS prior20_upside_turnover,
        median(turnover_fraction) OVER w20 AS prior20_turnover_median,
        count(*) OVER w126 AS prior126_rows,
        min(cal_idx) OVER w126 AS prior126_min_cal_idx,
        max(cal_idx) OVER w126 AS prior126_max_cal_idx,
        min(invalid_step_cum) OVER w126 AS prior126_lineage_min,
        max(invalid_step_cum) OVER w126 AS prior126_lineage_max,
        bool_and(
          hard_valid AND market_rule_valid AND corporate_action_valid
          AND NOT corporate_action_blocking AND coalesce(corporate_action_count,0)=0
          AND available_at<=decision_at AND coord_high>0
        ) OVER w126 AS prior126_valid,
        max(coord_high) OVER w126 AS prior126_high,
        CASE WHEN lag20_cal_idx=cal_idx-20 AND lag20_lineage=invalid_step_cum
          THEN coord_close/nullif(lag20_close,0)-1 END AS ret20,
        CASE WHEN lag60_cal_idx=cal_idx-60 AND lag60_lineage=invalid_step_cum
          THEN coord_close/nullif(lag60_close,0)-1 END AS ret60,
        coord_close/nullif(lag20_close,0)-1 AS exact_prior20_return,
        prior20_downside_turnover/nullif(prior20_upside_turnover,0)
          AS downside_upside_turnover_ratio,
        turnover_fraction/nullif(prior20_turnover_median,0) AS turnover_expansion,
        CASE WHEN coord_high>coord_low
          THEN (coord_close-coord_low)/(coord_high-coord_low) END AS close_location
      FROM step_base
      WINDOW
        symbol_window AS (PARTITION BY symbol ORDER BY cal_idx),
        w20 AS (PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
        w60 AS (PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING),
        w126 AS (PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 126 PRECEDING AND 1 PRECEDING)
    )
    """


def build_market(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    frame = con.execute(
        feature_ctes()
        + """
        SELECT CAST(trade_date AS DATE) AS trade_date,
          median(ret20) FILTER(WHERE current_valid AND NOT is_st AND ret20 IS NOT NULL)
            AS market_median_ret20,
          avg((ret20>0)::INT) FILTER(WHERE current_valid AND NOT is_st AND ret20 IS NOT NULL)
            AS market_positive_ret20_share,
          median(ret60) FILTER(WHERE current_valid AND NOT is_st AND ret60 IS NOT NULL)
            AS market_median_ret60,
          avg((ret60>0)::INT) FILTER(WHERE current_valid AND NOT is_st AND ret60 IS NOT NULL)
            AS market_positive_ret60_share,
          count(ret20) FILTER(WHERE current_valid AND NOT is_st AND ret20 IS NOT NULL) AS n20,
          count(ret60) FILTER(WHERE current_valid AND NOT is_st AND ret60 IS NOT NULL) AS n60,
          max(available_at) FILTER(WHERE current_valid AND NOT is_st)
            AS market_latest_source_timestamp,
          CASE
            WHEN market_median_ret20>0 AND market_positive_ret20_share>0.50
             AND market_median_ret60>0 AND market_positive_ret60_share>0.50 THEN 'BULL'
            WHEN market_median_ret20<=0 AND market_positive_ret20_share<=0.50
             AND market_median_ret60<=0 AND market_positive_ret60_share<=0.50 THEN 'BEAR'
            ELSE 'TRANSITION'
          END AS market_regime
        FROM featured
        GROUP BY trade_date
        ORDER BY trade_date
        """
    ).fetchdf()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    frame["market_latest_source_timestamp"] = pd.to_datetime(
        frame.market_latest_source_timestamp
    )
    return frame


def build_mothers(
    con: duckdb.DuckDBPyConnection, market: pd.DataFrame
) -> pd.DataFrame:
    con.register("causal_market", market)
    frame = con.execute(
        feature_ctes()
        + """
        , joined AS (
          SELECT f.*,m.market_median_ret20,m.market_positive_ret20_share,
            m.market_median_ret60,m.market_positive_ret60_share,
            m.market_latest_source_timestamp,m.market_regime,
            (
              f.prior60_rows=60 AND f.lag60_cal_idx=f.cal_idx-60
              AND f.prior60_lineage_min=f.invalid_step_cum
              AND f.prior60_lineage_max=f.invalid_step_cum
              AND f.prior60_valid
              AND f.hard_valid AND f.current_valid AND f.current_day_data_tradable
              AND f.trade_status=1 AND f.market_rule_valid
              AND f.corporate_action_valid AND NOT f.corporate_action_blocking
              AND coalesce(f.corporate_action_count,0)=0
              AND f.industry_valid AND f.historical_identity_valid
              AND f.causal_industry IS NOT NULL AND NOT f.is_st
              AND f.available_at<=f.decision_at
              AND m.market_latest_source_timestamp<=f.decision_at
              AND round(f.close*100)<round(f.up_limit_price*100)
              AND f.coord_close>0 AND f.coord_high>=f.coord_low
              AND f.turnover_fraction>0 AND f.prior20_turnover_median>0
            ) AS row_eligible
          FROM featured f
          JOIN causal_market m ON CAST(f.trade_date AS DATE)=m.trade_date
        ), flagged AS (
          SELECT *,(
            row_eligible AND market_regime='BULL'
            AND exact_prior20_return BETWEEN 0.05 AND 0.25
            AND prior20_positive_share>=0.60
            AND prior20_max_abs_return<0.07
            AND downside_upside_turnover_ratio<=0.65
            AND step_return BETWEEN 0.02 AND 0.07
            AND close_location>=0.75
            AND coord_close>prior20_high
            AND turnover_expansion BETWEEN 1.20 AND 2.50
          ) AS raw_mother
          FROM joined
        ), cooled AS (
          SELECT *,
            max(CASE WHEN raw_mother THEN cal_idx END) OVER(
              PARTITION BY symbol ORDER BY cal_idx
              ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
            ) AS prior_raw_cal_idx
          FROM flagged
        )
        SELECT
          'DISTRIBUTED_ACCUMULATION_ESCAPE|' || strftime(trade_date,'%Y%m%d')
            || '|' || symbol AS event_id,
          symbol,sleeve,CAST(trade_date AS DATE) AS signal_date,
          cal_idx AS signal_cal_idx,decision_at,available_at,invalid_step_cum,
          coord_close,causal_industry,market_regime,market_latest_source_timestamp,
          market_median_ret20,market_positive_ret20_share,
          market_median_ret60,market_positive_ret60_share,
          exact_prior20_return,prior20_positive_share,prior20_max_abs_return,
          downside_upside_turnover_ratio,turnover_expansion,close_location,step_return,
          prior126_rows,prior126_min_cal_idx,prior126_max_cal_idx,
          prior126_lineage_min,prior126_lineage_max,prior126_valid,prior126_high
        FROM cooled
        WHERE year(trade_date) BETWEEN 2022 AND 2025
          AND raw_mother
          AND (prior_raw_cal_idx IS NULL OR cal_idx-prior_raw_cal_idx>20)
        ORDER BY signal_date,symbol
        """
    ).fetchdf()
    for column in (
        "signal_date",
        "decision_at",
        "available_at",
        "market_latest_source_timestamp",
    ):
        frame[column] = pd.to_datetime(frame[column])
    if frame.empty or frame.event_id.duplicated().any():
        raise dev.ResearchError("empty or duplicate challenge mother population")
    if frame.available_at.gt(frame.decision_at).any() or frame.market_latest_source_timestamp.gt(
        frame.decision_at
    ).any():
        raise dev.ResearchError("challenge source available after decision")
    frame["same_date_mother_count"] = frame.groupby("signal_date")[
        "event_id"
    ].transform("size")
    return frame


def build_rule_panel(mothers: pd.DataFrame) -> pd.DataFrame:
    frame = mothers.copy()
    frame["rule_history_valid"] = (
        frame.prior126_rows.eq(126)
        & frame.prior126_min_cal_idx.eq(frame.signal_cal_idx - 126)
        & frame.prior126_max_cal_idx.eq(frame.signal_cal_idx - 1)
        & frame.prior126_lineage_min.eq(frame.invalid_step_cum)
        & frame.prior126_lineage_max.eq(frame.invalid_step_cum)
        & frame.prior126_valid.astype(bool)
    )
    frame["rule_clear_target_corridor"] = frame.coord_close.gt(
        frame.prior126_high
    ) | frame.prior126_high.ge(frame.coord_close * 1.15)
    frame["rule_market_strengthening"] = (
        (1.0 + frame.market_median_ret20).pow(3).ge(
            1.0 + frame.market_median_ret60
        )
        & frame.market_positive_ret20_share.ge(frame.market_positive_ret60_share)
    )
    frame["rule_crowding_supported"] = frame.market_positive_ret60_share.ge(
        0.80
    ) | frame.same_date_mother_count.le(25)
    frame["pre_confirmation_pass"] = (
        frame.rule_history_valid
        & frame.rule_clear_target_corridor
        & frame.rule_market_strengthening
        & frame.rule_crowding_supported
    )
    return frame.sort_values(
        ["signal_date", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)


def build_paths(
    con: duckdb.DuckDBPyConnection, panel: pd.DataFrame
) -> pd.DataFrame:
    con.register("challenge_events", panel[["event_id", "symbol", "signal_cal_idx"]])
    frame = con.execute(
        f"""
        SELECT e.event_id,d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.invalid_step_cum,
          d.coordinate_factor,d.trade_status,d.current_day_data_tradable,d.current_valid,
          d.market_rule_valid,d.corporate_action_count,d.corporate_action_valid,
          d.corporate_action_blocking,d.hard_valid,d.up_limit_price,d.down_limit_price,
          d.available_at,d.decision_at
        FROM challenge_events e
        JOIN read_parquet('{DAILY.as_posix()}') d
          ON e.symbol=d.symbol AND d.cal_idx>e.signal_cal_idx
         AND d.cal_idx<=e.signal_cal_idx+50
        WHERE d.trade_date<=DATE '2026-03-31'
        ORDER BY e.event_id,d.cal_idx
        """
    ).fetchdf()
    for column in ("trade_date", "available_at", "decision_at"):
        frame[column] = pd.to_datetime(frame[column])
    return frame


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    values = dev.metrics(frame)
    values["signals"] = int(len(frame))
    values["signal_dates"] = int(frame.signal_date.nunique())
    return values


def concentration(frame: pd.DataFrame) -> dict[str, Any]:
    complete = frame.loc[frame.status.eq("COMPLETED")].copy()
    grouped = (
        complete.groupby("signal_date", as_index=False)
        .agg(signals=("event_id", "size"), mean_net_return=("net_return", "mean"))
        .sort_values(["signals", "signal_date"], ascending=[False, True])
        .reset_index(drop=True)
    )
    if grouped.empty:
        return {}
    largest = pd.Timestamp(grouped.iloc[0].signal_date)
    without = complete.loc[complete.signal_date.ne(largest)]
    return {
        "distinct_signal_dates": int(len(grouped)),
        "largest_signal_date": str(largest.date()),
        "maximum_signals_on_one_date": int(grouped.iloc[0].signals),
        "largest_date_share": float(grouped.iloc[0].signals / len(complete)),
        "signal_date_equal_weight_mean_net_return": float(
            grouped.mean_net_return.mean()
        ),
        "mean_net_return_excluding_largest_date": None
        if without.empty
        else float(without.net_return.mean()),
        "top_dates": grouped.head(10).to_dict("records"),
    }


def run() -> dict[str, Any]:
    if dev.sha256(FREEZE) != EXPECTED_FREEZE_SHA256:
        raise dev.ResearchError("challenge freeze hash drift")
    if dev.sha256(DAILY) != EXPECTED_DAILY_SHA256:
        raise dev.ResearchError("challenge daily hash drift")
    con = connection()
    market = build_market(con)
    mothers = build_mothers(con, market)
    panel = build_rule_panel(mothers)
    paths = build_paths(con, panel)
    con.close()
    groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    outcomes = pd.DataFrame(
        [
            dev.replay_one(candidate, groups.get(candidate.event_id, pd.DataFrame()))
            for candidate in panel.itertuples(index=False)
        ]
    )
    outcomes["signal_date"] = pd.to_datetime(outcomes.signal_date)
    for column in ("confirmation_date", "entry_date", "exit_date"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    complete = outcomes.loc[outcomes.status.eq("COMPLETED")]
    chronology = {
        "confirmation_at_or_before_signal": int(
            complete.confirmation_cal_idx.le(complete.signal_cal_idx).sum()
        ),
        "entry_at_or_before_confirmation": int(
            complete.entry_cal_idx.le(complete.confirmation_cal_idx).sum()
        ),
        "exit_at_or_before_entry": int(
            complete.exit_cal_idx.le(complete.entry_cal_idx).sum()
        ),
    }
    if any(chronology.values()):
        raise dev.ResearchError(f"challenge chronology failure: {chronology}")
    dev.atomic_parquet(market, MARKET)
    dev.atomic_parquet(mothers, MOTHERS)
    dev.atomic_parquet(panel, RULE_PANEL)
    dev.atomic_parquet(paths, PATHS)
    dev.atomic_parquet(outcomes, OUTCOMES)
    pooled = metrics(outcomes)
    annual = {
        str(year): metrics(outcomes.loc[outcomes.signal_date.dt.year.eq(year)])
        for year in range(2022, 2026)
    }
    user_gates = {
        "mean_completed_signals_per_year_gt_50": pooled["completed"] / 4 > 50,
        "mean_net_return_ge_4pct": pooled["mean_net_return"] is not None
        and pooled["mean_net_return"] >= 0.04,
        "mean_holding_sessions_lt_15": pooled["mean_holding_sessions"] is not None
        and pooled["mean_holding_sessions"] < 15,
        "year_2025_mean_net_return_ge_4pct": annual["2025"][
            "mean_net_return"
        ]
        is not None
        and annual["2025"]["mean_net_return"] >= 0.04,
        "year_2025_mean_holding_sessions_lt_15": annual["2025"][
            "mean_holding_sessions"
        ]
        is not None
        and annual["2025"]["mean_holding_sessions"] < 15,
    }
    result = {
        "experiment": EXPERIMENT,
        "scientific_status": "FROZEN_LATER_PERIOD_CHALLENGE",
        "freeze_sha256": EXPECTED_FREEZE_SHA256,
        "status_counts": outcomes.status.value_counts().sort_index().to_dict(),
        "mother_signals": int(len(mothers)),
        "rule_pass_counts": {
            "history_valid": int(panel.rule_history_valid.sum()),
            "clear_target_corridor": int(panel.rule_clear_target_corridor.sum()),
            "market_strengthening": int(panel.rule_market_strengthening.sum()),
            "crowding_supported": int(panel.rule_crowding_supported.sum()),
            "pre_confirmation_pass": int(panel.pre_confirmation_pass.sum()),
        },
        "pooled": pooled,
        "annual": annual,
        "mean_completed_signals_per_year": pooled["completed"] / 4,
        "concentration": concentration(outcomes),
        "user_gates": user_gates,
        "all_user_and_2025_gates_pass": bool(all(user_gates.values())),
        "chronology": chronology,
        "future_market_function": False,
        "no_rescue": True,
        "input_hashes_sha256": {
            "freeze": EXPECTED_FREEZE_SHA256,
            "daily": EXPECTED_DAILY_SHA256,
        },
    }
    result["output_hashes_sha256"] = {
        "market": dev.sha256(MARKET),
        "mothers": dev.sha256(MOTHERS),
        "rule_panel": dev.sha256(RULE_PANEL),
        "paths": dev.sha256(PATHS),
        "outcomes": dev.sha256(OUTCOMES),
    }
    dev.atomic_json(result, RESULT)
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True, default=str))
