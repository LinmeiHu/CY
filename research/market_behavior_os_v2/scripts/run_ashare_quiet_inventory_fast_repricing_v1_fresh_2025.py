#!/usr/bin/env python3
"""Fresh 2025 signal-year extension of frozen fast-repricing V1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

import run_ashare_quiet_inventory_fast_repricing_v1 as v1


EXPERIMENT = "ASHARE-QUIET-INVENTORY-FAST-REPRICING-V1-FRESH-2025"
OUTPUT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_quiet_inventory_fast_repricing_v1/fresh_2025"
)
MARKET = OUTPUT / "causal_market_regime_2025.parquet"
CANDIDATES = OUTPUT / "frozen_rule_candidates_2025.parquet"
OUTCOMES = OUTPUT / "frozen_rule_outcomes_2025.parquet"
RESULT = OUTPUT / "result.json"
SIGNAL_YEAR = 2025
OUTCOME_END = pd.Timestamp("2026-03-31")


def feature_ctes_2025() -> str:
    original = v1.feature_ctes()
    updated = original.replace("DATE '2024-12-31'", "DATE '2025-12-31'")
    if updated == original:
        raise v1.ValidationError("failed to extend frozen feature generator through 2025")
    return updated


def build_market(connection: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    frame = connection.execute(
        feature_ctes_2025()
        + """
        SELECT
          CAST(trade_date AS DATE) AS trade_date,
          median(ret20) FILTER(WHERE current_valid AND NOT is_st AND ret20 IS NOT NULL)
            AS market_median_ret20,
          avg((ret20>0)::INTEGER) FILTER(WHERE current_valid AND NOT is_st AND ret20 IS NOT NULL)
            AS market_positive_ret20_share,
          median(ret60) FILTER(WHERE current_valid AND NOT is_st AND ret60 IS NOT NULL)
            AS market_median_ret60,
          avg((ret60>0)::INTEGER) FILTER(WHERE current_valid AND NOT is_st AND ret60 IS NOT NULL)
            AS market_positive_ret60_share,
          count(ret20) FILTER(WHERE current_valid AND NOT is_st AND ret20 IS NOT NULL) AS n20,
          count(ret60) FILTER(WHERE current_valid AND NOT is_st AND ret60 IS NOT NULL) AS n60,
          max(available_at) FILTER(WHERE current_valid AND NOT is_st) AS latest_source_timestamp,
          CASE
            WHEN market_median_ret20>0 AND market_positive_ret20_share>0.50
             AND market_median_ret60>0 AND market_positive_ret60_share>0.50 THEN 'BULL'
            WHEN market_median_ret20<=0 AND market_positive_ret20_share<=0.50
             AND market_median_ret60<=0 AND market_positive_ret60_share<=0.50 THEN 'BEAR'
            ELSE 'TRANSITION'
          END AS market_regime
        FROM featured
        WHERE year(trade_date)=2025
        GROUP BY trade_date
        ORDER BY trade_date
        """
    ).fetchdf()
    if not 230 <= len(frame) <= 250:
        raise v1.ValidationError(f"unexpected 2025 market-session count: {len(frame)}")
    return frame


def build_candidates(
    connection: duckdb.DuckDBPyConnection, market: pd.DataFrame
) -> pd.DataFrame:
    connection.register("market_2025_frame", market)
    frame = connection.execute(
        feature_ctes_2025()
        + f"""
        SELECT
          'ASHARE-QUIET-INVENTORY-INFORMATION-GAP-BREAKOUT-V1|' || f.symbol ||
            '|' || strftime(f.trade_date,'%Y-%m-%d') AS event_id,
          f.symbol,f.sleeve,CAST(f.trade_date AS DATE) AS signal_date,
          f.cal_idx AS signal_cal_idx,
          f.invalid_step_cum AS signal_invalid_step_cum,
          f.large_up_days120,f.platform_high,f.platform_low,
          f.platform_width,f.turnover_contraction,
          f.open_gap,f.turnover_expansion,f.close_location,f.causal_industry,
          m.market_regime,m.market_median_ret20,m.market_positive_ret20_share,
          m.market_median_ret60,m.market_positive_ret60_share,
          'EXACT_PIT_2025_REBUILD' AS candidate_source
        FROM featured f
        JOIN market_2025_frame m ON CAST(f.trade_date AS DATE)=m.trade_date
        WHERE year(f.trade_date)=2025
          AND {v1.mother_condition()}
          AND m.market_regime='BULL'
          AND m.market_median_ret60 BETWEEN 0.025 AND 0.18
          AND f.large_up_days120<=9
        ORDER BY f.trade_date,f.symbol
        """
    ).fetchdf()
    frame["signal_date"] = pd.to_datetime(frame.signal_date)
    if frame.event_id.duplicated().any():
        raise v1.ValidationError("duplicate 2025 event_id")
    required = (
        "event_id",
        "symbol",
        "signal_date",
        "signal_cal_idx",
        "signal_invalid_step_cum",
        "market_median_ret60",
        "large_up_days120",
    )
    if frame[list(required)].isna().any().any():
        raise v1.ValidationError("unknown required 2025 candidate lineage")
    return frame


def concentration(frame: pd.DataFrame) -> dict[str, Any]:
    completed = frame.loc[frame.status.eq("COMPLETED")].copy()
    if completed.empty:
        return {}
    grouped = (
        completed.groupby("signal_date", as_index=False)
        .agg(signals=("event_id", "size"), mean_net_return=("net_return", "mean"))
        .sort_values(["signals", "signal_date"], ascending=[False, True])
        .reset_index(drop=True)
    )
    largest = pd.Timestamp(grouped.iloc[0].signal_date)
    without = completed.loc[completed.signal_date.ne(largest)]
    return {
        "distinct_signal_dates": int(len(grouped)),
        "maximum_signals_on_one_date": int(grouped.iloc[0].signals),
        "largest_signal_date": str(largest.date()),
        "largest_date_share": float(grouped.iloc[0].signals / len(completed)),
        "signal_date_equal_weight_mean_net_return": float(grouped.mean_net_return.mean()),
        "mean_net_return_excluding_largest_date": None
        if without.empty
        else float(without.net_return.mean()),
        "top_dates": grouped.head(10).to_dict("records"),
    }


def run() -> dict[str, Any]:
    for path in (v1.FREEZE, v1.DAILY):
        if not path.is_file():
            raise v1.ValidationError(f"missing frozen input: {path}")
    freeze_hash = v1.sha256(v1.FREEZE)
    if freeze_hash != v1.EXPECTED_FREEZE_SHA256:
        raise v1.ValidationError(f"V1 freeze hash changed: {freeze_hash}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    connection = v1.connection()
    market = build_market(connection)
    candidates = build_candidates(connection, market)
    original_end = v1.OUTCOME_DATA_END
    try:
        v1.OUTCOME_DATA_END = OUTCOME_END
        outcomes = v1.replay(connection, candidates)
    finally:
        v1.OUTCOME_DATA_END = original_end
        connection.close()
    v1.atomic_parquet(market, MARKET)
    v1.atomic_parquet(candidates, CANDIDATES)
    v1.atomic_parquet(outcomes, OUTCOMES)
    pooled = v1.metrics(outcomes)
    result = {
        "experiment": EXPERIMENT,
        "status": "FRESH_2025_COMPLETE",
        "chronology": {
            "rule_frozen_before_2022_2024_validation": True,
            "threshold_changes_for_2025": False,
            "signal_year": SIGNAL_YEAR,
            "outcome_tail_end": str(OUTCOME_END.date()),
        },
        "pooled": pooled,
        "signals_per_year": int(len(outcomes)),
        "completed_trades_per_year": int(outcomes.status.eq("COMPLETED").sum()),
        "concentration": concentration(outcomes),
        "user_gates": {
            "signals_strictly_above_50": len(outcomes) > 50,
            "mean_net_return_at_least_4pct": pooled["mean_net_return"] is not None
            and pooled["mean_net_return"] >= 0.04,
            "mean_holding_sessions_strictly_below_15": pooled["mean_holding_sessions"]
            is not None
            and pooled["mean_holding_sessions"] < 15,
        },
        "input_hashes_sha256": {
            "v1_freeze": freeze_hash,
            "exact_daily_2022_2026q1": v1.sha256(v1.DAILY),
        },
    }
    v1.atomic_json(RESULT, result)
    result["output_hashes_sha256"] = {
        "market": v1.sha256(MARKET),
        "candidates": v1.sha256(CANDIDATES),
        "outcomes": v1.sha256(OUTCOMES),
    }
    v1.atomic_json(RESULT, result)
    return result


if __name__ == "__main__":
    print(json.dumps(v1.json_ready(run()), ensure_ascii=False, indent=2))
