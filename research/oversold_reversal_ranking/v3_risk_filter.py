#!/usr/bin/env python3
"""V3: causal t0 falling-knife risk inside the frozen V2 carrier."""

# SQL is explicit so feature chronology, bucket assignment, and cash-policy math remain
# auditable. Long query lines are preferable to hidden dataframe transformations here.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from research.oversold_reversal_ranking.v2_timing import (  # noqa: E402
    DEEP_DRAWDOWN_MAX,
    create_timing_tables,
)
from research.volume_exhaustion_bottom.experiment import (  # noqa: E402
    DEFAULT_CONFIG as PREDECESSOR_CONFIG,
)
from research.volume_exhaustion_bottom.experiment import (  # noqa: E402
    create_analysis_tables,
    json_default,
    validate_inputs,
)

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "reports"
SEVERE_MAE_MAX = -0.10
LARGE_WINNER_MIN = 0.10
VETO_FRACTIONS = (0.10, 0.20, 0.30)

# Fixed after the first broad outcome-bearing run. The methodology and feature family were
# already frozen and were not altered in response to the result.
VERDICT = "SIZING_SIGNAL_ONLY"
SINGLE_NEXT_STEP = "Lock the frozen V3 score and run one focused V4 on causal position sizing that preserves participation while reducing exposure to high-risk events."

FEATURES = {
    "close_location": {
        "column": "close_location_danger",
        "bucket": "close_location_q",
        "definition": "1 - (close-low)/(high-low) at t0; zero-range unavailable; higher means the close is nearer the low",
    },
    "current_day_loss": {
        "column": "current_day_loss_danger",
        "bucket": "current_day_loss_q",
        "definition": "-(close/preclose-1) at t0; higher means a more adverse t0 close-to-preclose shock",
    },
    "negative_day_persistence_5": {
        "column": "negative_days_5",
        "bucket": "negative_days_5_q",
        "definition": "count of negative close/preclose sessions over t0-4..t0; higher means more persistent selling",
    },
    "adverse_gap": {
        "column": "adverse_gap_danger",
        "bucket": "adverse_gap_q",
        "definition": "-(open/preclose-1) at t0; higher means a more adverse overnight repricing",
    },
}


def rows_as_dicts(cursor: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    columns = [item[0] for item in cursor.description]
    return [
        {
            key: float(value) if isinstance(value, Decimal) else value
            for key, value in zip(columns, row, strict=True)
        }
        for row in cursor.fetchall()
    ]


def create_risk_tables(con: duckdb.DuckDBPyConnection) -> None:
    """Construct the causal score before joining any V2 outcome or trigger fields."""
    con.execute(
        """
        CREATE TEMP TABLE v3_feature_history AS
        SELECT symbol, trade_date, trade_seq, deep_flag, deep_event,
               available_at, decision_at, high, low, open, close, preclose,
               drawdown_60, bar_return,
               sum((bar_return < 0)::INTEGER) OVER (
                   PARTITION BY symbol ORDER BY trade_date
                   ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS negative_days_5,
               count(*) OVER (
                   PARTITION BY symbol ORDER BY trade_date
                   ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS history_n_5
        FROM v2_marked
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE v3_rank_universe AS
        SELECT symbol, trade_date, trade_seq, deep_event, drawdown_60,
               1.0 - (close - low) / (high - low) AS close_location_danger,
               -(close / preclose - 1.0) AS current_day_loss_danger,
               negative_days_5,
               -(open / preclose - 1.0) AS adverse_gap_danger
        FROM v3_feature_history
        WHERE deep_flag AND high > low AND open > 0 AND preclose > 0
          AND history_n_5 = 5
          AND isfinite(1.0 - (close - low) / (high - low))
          AND isfinite(close / preclose - 1.0)
          AND isfinite(open / preclose - 1.0)
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE v3_component_ranks AS
        SELECT *,
               percent_rank() OVER (
                   PARTITION BY trade_date ORDER BY close_location_danger
               ) AS close_location_rank,
               percent_rank() OVER (
                   PARTITION BY trade_date ORDER BY current_day_loss_danger
               ) AS current_day_loss_rank,
               percent_rank() OVER (
                   PARTITION BY trade_date ORDER BY negative_days_5
               ) AS negative_days_5_rank,
               percent_rank() OVER (
                   PARTITION BY trade_date ORDER BY adverse_gap_danger
               ) AS adverse_gap_rank,
               count(*) OVER (PARTITION BY trade_date) AS rank_universe_n
        FROM v3_rank_universe
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE v3_score_universe AS
        SELECT *,
               (close_location_rank + current_day_loss_rank
                + negative_days_5_rank + adverse_gap_rank) / 4.0 AS risk_score
        FROM v3_component_ranks
        """
    )
    # Outcome and future-trigger fields enter only here, after the score is complete.
    con.execute(
        """
        CREATE TEMP TABLE v3_events_base AS
        SELECT p.*, s.close_location_danger, s.current_day_loss_danger,
               s.negative_days_5, s.adverse_gap_danger,
               s.close_location_rank, s.current_day_loss_rank,
               s.negative_days_5_rank, s.adverse_gap_rank,
               s.rank_universe_n, s.risk_score,
               CASE WHEN p.drawdown_60 > -0.35 THEN 'D1_30_TO_35'
                    WHEN p.drawdown_60 > -0.40 THEN 'D2_35_TO_40'
                    WHEN p.drawdown_60 > -0.45 THEN 'D3_40_TO_45'
                    ELSE 'D4_LE_45' END AS depth_control_bin,
               CASE WHEN p.symbol LIKE '300%' THEN 'CHINEXT'
                    WHEN p.symbol LIKE '688%' THEN 'STAR'
                    WHEN p.symbol LIKE '8%' OR p.symbol LIKE '4%' THEN 'BSE'
                    ELSE 'MAIN' END AS market_segment
        FROM v2_policy_events p
        JOIN v3_score_universe s USING (symbol, trade_date)
        WHERE p.deep_event
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE v3_events AS
        SELECT *,
               ntile(5) OVER (
                   ORDER BY close_location_danger, symbol, trade_date
               ) AS close_location_q,
               ntile(5) OVER (
                   ORDER BY current_day_loss_danger, symbol, trade_date
               ) AS current_day_loss_q,
               CASE WHEN negative_days_5 <= 1 THEN 1
                    WHEN negative_days_5 = 2 THEN 2
                    WHEN negative_days_5 = 3 THEN 3
                    WHEN negative_days_5 = 4 THEN 4 ELSE 5 END AS negative_days_5_q,
               ntile(5) OVER (
                   ORDER BY adverse_gap_danger, symbol, trade_date
               ) AS adverse_gap_q,
               ntile(5) OVER (
                   ORDER BY risk_score, symbol, trade_date
               ) AS risk_q,
               row_number() OVER (
                   ORDER BY risk_score DESC, symbol, trade_date
               ) AS risk_order,
               count(*) OVER () AS event_n
        FROM v3_events_base
        """
    )


def sample_profile(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    v2 = rows_as_dicts(
        con.execute(
            """
            SELECT count(*) AS v2_valid_events,
                   count(DISTINCT symbol) AS v2_event_securities,
                   min(trade_date) AS v2_first_event_date,
                   max(trade_date) AS v2_last_event_date
            FROM v2_policy_events WHERE deep_event
            """
        )
    )[0]
    v3 = rows_as_dicts(
        con.execute(
            """
            SELECT count(*) AS valid_v3_events,
                   count(DISTINCT symbol) AS event_securities,
                   min(trade_date) AS first_event_date,
                   max(trade_date) AS last_event_date,
                   count(DISTINCT industry) AS industries,
                   count(DISTINCT trade_date) AS event_dates,
                   min(rank_universe_n) AS min_rank_universe_n,
                   avg(rank_universe_n) AS mean_rank_universe_n,
                   max(rank_universe_n) AS max_rank_universe_n
            FROM v3_events
            """
        )
    )[0]
    attrition_rows = rows_as_dicts(
        con.execute(
            """
            WITH missing AS (
              SELECT p.symbol, p.trade_date,
                     CASE WHEN h.symbol IS NULL THEN 'MISSING_HISTORY_ROW'
                          WHEN h.high <= h.low THEN 'ZERO_RANGE_T0'
                          WHEN h.open <= 0 OR h.preclose <= 0 THEN 'INVALID_OPEN_PRECLOSE'
                          WHEN h.history_n_5 != 5 THEN 'INCOMPLETE_FIVE_SESSION_HISTORY'
                          WHEN NOT isfinite(1.0-(h.close-h.low)/(h.high-h.low))
                            OR NOT isfinite(h.close/h.preclose-1.0)
                            OR NOT isfinite(h.open/h.preclose-1.0) THEN 'NONFINITE_FEATURE'
                          ELSE 'UNEXPLAINED' END AS reason
              FROM v2_policy_events p
              LEFT JOIN v3_feature_history h USING (symbol, trade_date)
              LEFT JOIN v3_score_universe s USING (symbol, trade_date)
              WHERE p.deep_event AND s.symbol IS NULL
            )
            SELECT reason, count(*) AS n FROM missing GROUP BY reason ORDER BY reason
            """
        )
    )
    v3["feature_unavailable_events"] = v2["v2_valid_events"] - v3["valid_v3_events"]
    v3["feature_attrition_reasons"] = {
        row["reason"]: row["n"] for row in attrition_rows
    }
    return {**v2, **v3}


def baseline_summary(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    return rows_as_dicts(
        con.execute(
            f"""
            SELECT count(*) AS n, avg(mae_20) AS mean_mae_20,
                   median(mae_20) AS median_mae_20,
                   count(*) FILTER (WHERE mae_20 <= {SEVERE_MAE_MAX}) AS severe_events,
                   avg((mae_20 <= {SEVERE_MAE_MAX})::INTEGER) AS severe_mae_rate_20,
                   avg(ret_20) AS mean_ret_20, median(ret_20) AS median_ret_20,
                   avg((ret_20 > 0)::INTEGER) AS positive_rate_20,
                   avg(mfe_20) AS mean_mfe_20,
                   count(*) FILTER (WHERE NOT trigger_signal) AS no_trigger_events,
                   avg((NOT trigger_signal)::INTEGER) AS no_trigger_rate
            FROM v3_events
            """
        )
    )[0]


def bucket_metrics(
    con: duckdb.DuckDBPyConnection, bucket: str, value: str
) -> list[dict[str, Any]]:
    return rows_as_dicts(
        con.execute(
            f"""
            SELECT {bucket} AS quintile, count(*) AS n,
                   min({value}) AS feature_min, max({value}) AS feature_max,
                   avg(mae_20) AS mean_mae_20, median(mae_20) AS median_mae_20,
                   avg((mae_20 <= {SEVERE_MAE_MAX})::INTEGER) AS severe_mae_rate_20,
                   avg(ret_20) AS mean_ret_20, median(ret_20) AS median_ret_20,
                   avg((ret_20 > 0)::INTEGER) AS positive_rate_20,
                   avg((NOT trigger_signal)::INTEGER) AS no_trigger_rate,
                   avg(mfe_20) AS mean_mfe_20
            FROM v3_events GROUP BY {bucket} ORDER BY {bucket}
            """
        )
    )


def separation(
    con: duckdb.DuckDBPyConnection, bucket: str
) -> dict[str, Any]:
    return rows_as_dicts(
        con.execute(
            f"""
            SELECT
              avg((mae_20 <= {SEVERE_MAE_MAX})::INTEGER) FILTER (WHERE {bucket}=5)
                - avg((mae_20 <= {SEVERE_MAE_MAX})::INTEGER) FILTER (WHERE {bucket}=1)
                  AS q5_minus_q1_severe_mae_rate,
              avg(mae_20) FILTER (WHERE {bucket}=5)
                - avg(mae_20) FILTER (WHERE {bucket}=1) AS q5_minus_q1_mean_mae_20,
              median(mae_20) FILTER (WHERE {bucket}=5)
                - median(mae_20) FILTER (WHERE {bucket}=1) AS q5_minus_q1_median_mae_20,
              avg((NOT trigger_signal)::INTEGER) FILTER (WHERE {bucket}=5)
                - avg((NOT trigger_signal)::INTEGER) FILTER (WHERE {bucket}=1)
                  AS q5_minus_q1_no_trigger_rate,
              avg(ret_20) FILTER (WHERE {bucket}=5)
                - avg(ret_20) FILTER (WHERE {bucket}=1) AS q5_minus_q1_mean_ret_20
            FROM v3_events
            """
        )
    )[0]


def conditional_date_depth(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    return rows_as_dicts(
        con.execute(
            f"""
            WITH counted AS (
              SELECT *, count(*) OVER (
                PARTITION BY trade_date, depth_control_bin) AS cell_n
              FROM v3_events
            ), ranked AS (
              SELECT *, ntile(3) OVER (
                PARTITION BY trade_date, depth_control_bin
                ORDER BY risk_score, symbol) AS risk_tercile
              FROM counted WHERE cell_n >= 6
            ), cells AS (
              SELECT trade_date, depth_control_bin, count(*) AS n,
                avg((mae_20 <= {SEVERE_MAE_MAX})::INTEGER) FILTER (WHERE risk_tercile=3)
                  - avg((mae_20 <= {SEVERE_MAE_MAX})::INTEGER) FILTER (WHERE risk_tercile=1)
                    AS severe_spread,
                avg(mae_20) FILTER (WHERE risk_tercile=3)
                  - avg(mae_20) FILTER (WHERE risk_tercile=1) AS mean_mae_spread,
                avg((NOT trigger_signal)::INTEGER) FILTER (WHERE risk_tercile=3)
                  - avg((NOT trigger_signal)::INTEGER) FILTER (WHERE risk_tercile=1)
                    AS no_trigger_spread,
                avg(ret_20) FILTER (WHERE risk_tercile=3)
                  - avg(ret_20) FILTER (WHERE risk_tercile=1) AS mean_ret_spread
              FROM ranked GROUP BY trade_date, depth_control_bin
            )
            SELECT count(*) AS cells, sum(n) AS event_assignments,
                   avg(severe_spread) AS high_minus_low_severe_mae_rate,
                   avg(mean_mae_spread) AS high_minus_low_mean_mae_20,
                   avg(no_trigger_spread) AS high_minus_low_no_trigger_rate,
                   avg(mean_ret_spread) AS high_minus_low_mean_ret_20,
                   avg((severe_spread > 0)::INTEGER) AS positive_severe_spread_cell_fraction,
                   avg((mean_mae_spread < 0)::INTEGER) AS worse_mae_cell_fraction
            FROM cells
            """
        )
    )[0]


def capture_and_policy(
    con: duckdb.DuckDBPyConnection, fraction: float
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    condition = f"risk_order <= ceil(event_n * {fraction})"
    capture = rows_as_dicts(
        con.execute(
            f"""
            SELECT {fraction} AS highest_risk_fraction,
                   count(*) FILTER (WHERE {condition}) AS highest_risk_n,
                   count(*) FILTER (WHERE {condition} AND mae_20 <= {SEVERE_MAE_MAX})
                     / count(*) FILTER (WHERE mae_20 <= {SEVERE_MAE_MAX})::DOUBLE
                       AS severe_events_captured,
                   count(*) FILTER (WHERE {condition} AND NOT trigger_signal)
                     / count(*) FILTER (WHERE NOT trigger_signal)::DOUBLE
                       AS no_trigger_events_captured,
                   avg((mae_20 <= {SEVERE_MAE_MAX})::INTEGER) FILTER (WHERE {condition})
                     AS severe_mae_rate_20,
                   avg(mae_20) FILTER (WHERE {condition}) AS mean_mae_20,
                   avg(ret_20) FILTER (WHERE {condition}) AS mean_ret_20
            FROM v3_events
            """
        )
    )[0]
    policy = rows_as_dicts(
        con.execute(
            f"""
            SELECT concat('VETO_TOP_', cast(round({fraction}*100) AS INTEGER), '_PCT') AS policy,
                   count(*) AS original_opportunities,
                   count(*) FILTER (WHERE NOT ({condition})) AS entered_trades,
                   avg((NOT ({condition}))::INTEGER) AS participation_rate,
                   avg(({condition})::INTEGER) AS skipped_event_rate,
                   avg(CASE WHEN {condition} THEN 0.0 ELSE ret_20 END)
                     AS opportunity_mean_ret_20,
                   median(CASE WHEN {condition} THEN 0.0 ELSE ret_20 END)
                     AS opportunity_median_ret_20,
                   avg((CASE WHEN {condition} THEN 0.0 ELSE ret_20 END > 0)::INTEGER)
                     AS opportunity_positive_rate_20,
                   avg(ret_20) FILTER (WHERE NOT ({condition})) AS retained_mean_ret_20,
                   median(ret_20) FILTER (WHERE NOT ({condition})) AS retained_median_ret_20,
                   avg((ret_20 > 0)::INTEGER) FILTER (WHERE NOT ({condition}))
                     AS retained_positive_rate_20,
                   avg(mae_20) FILTER (WHERE NOT ({condition})) AS retained_mean_mae_20,
                   avg((mae_20 <= {SEVERE_MAE_MAX})::INTEGER) FILTER (WHERE NOT ({condition}))
                     AS retained_severe_mae_rate_20,
                   count(*) FILTER (WHERE {condition} AND mae_20 <= {SEVERE_MAE_MAX})
                     AS severe_events_avoided,
                   count(*) FILTER (WHERE {condition} AND ret_20 > 0) AS winners_skipped,
                   avg(mfe_20) FILTER (WHERE {condition}) AS average_mfe_skipped
            FROM v3_events
            """
        )
    )[0]
    skipped = rows_as_dicts(
        con.execute(
            f"""
            SELECT {fraction} AS highest_risk_fraction,
                   count(*) FILTER (WHERE {condition}) AS n,
                   avg(ret_20) FILTER (WHERE {condition}) AS mean_ret_20,
                   median(ret_20) FILTER (WHERE {condition}) AS median_ret_20,
                   avg((mae_20 <= {SEVERE_MAE_MAX})::INTEGER) FILTER (WHERE {condition})
                     AS severe_mae_rate_20,
                   avg((ret_20 > 0)::INTEGER) FILTER (WHERE {condition}) AS positive_rate_20,
                   count(*) FILTER (WHERE {condition} AND ret_20 >= {LARGE_WINNER_MIN})
                     AS large_winners_skipped,
                   count(*) FILTER (WHERE {condition} AND ret_20 >= {LARGE_WINNER_MIN})
                     / nullif(count(*) FILTER (WHERE ret_20 >= {LARGE_WINNER_MIN}), 0)::DOUBLE
                       AS fraction_all_large_winners_skipped,
                   count(*) FILTER (WHERE {condition} AND mae_20 <= {SEVERE_MAE_MAX})
                     / count(*) FILTER (WHERE mae_20 <= {SEVERE_MAE_MAX})::DOUBLE
                       AS fraction_all_severe_losers_avoided,
                   avg(mfe_20) FILTER (WHERE {condition}) AS mean_mfe_20
            FROM v3_events
            """
        )
    )[0]
    return capture, policy, skipped


def baseline_policy(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    return rows_as_dicts(
        con.execute(
            f"""
            SELECT 'BUY_ALL' AS policy, count(*) AS original_opportunities,
                   count(*) AS entered_trades, 1.0 AS participation_rate,
                   0.0 AS skipped_event_rate, avg(ret_20) AS opportunity_mean_ret_20,
                   median(ret_20) AS opportunity_median_ret_20,
                   avg((ret_20 > 0)::INTEGER) AS opportunity_positive_rate_20,
                   avg(ret_20) AS retained_mean_ret_20,
                   median(ret_20) AS retained_median_ret_20,
                   avg((ret_20 > 0)::INTEGER) AS retained_positive_rate_20,
                   avg(mae_20) AS retained_mean_mae_20,
                   avg((mae_20 <= {SEVERE_MAE_MAX})::INTEGER) AS retained_severe_mae_rate_20,
                   0 AS severe_events_avoided, 0 AS winners_skipped,
                   NULL::DOUBLE AS average_mfe_skipped
            FROM v3_events
            """
        )
    )[0]


def time_stability(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    return rows_as_dicts(
        con.execute(
            f"""
            WITH ranked AS (
              SELECT *,
                     ntile(5) OVER (
                       PARTITION BY time_block ORDER BY risk_score, symbol, trade_date
                     ) AS period_q,
                     row_number() OVER (
                       PARTITION BY time_block ORDER BY risk_score DESC, symbol, trade_date
                     ) AS period_risk_order,
                     count(*) OVER (PARTITION BY time_block) AS period_n
              FROM v3_events
            )
            SELECT time_block, count(*) AS n,
                   avg((mae_20 <= {SEVERE_MAE_MAX})::INTEGER) FILTER (WHERE period_q=5)
                     - avg((mae_20 <= {SEVERE_MAE_MAX})::INTEGER) FILTER (WHERE period_q=1)
                       AS q5_minus_q1_severe_mae_rate,
                   avg(mae_20) FILTER (WHERE period_q=5)
                     - avg(mae_20) FILTER (WHERE period_q=1)
                       AS q5_minus_q1_mean_mae_20,
                   count(*) FILTER (
                     WHERE period_risk_order <= ceil(period_n*0.20)
                       AND mae_20 <= {SEVERE_MAE_MAX})
                     / count(*) FILTER (WHERE mae_20 <= {SEVERE_MAE_MAX})::DOUBLE
                       AS top20_severe_event_capture,
                   avg(ret_20) AS baseline_mean_ret_20,
                   avg(CASE WHEN period_risk_order <= ceil(period_n*0.20)
                            THEN 0.0 ELSE ret_20 END) AS top20_veto_opportunity_mean_ret_20
            FROM ranked GROUP BY time_block ORDER BY time_block
            """
        )
    )


def grouped_gradient(
    con: duckdb.DuckDBPyConnection, group: str
) -> list[dict[str, Any]]:
    return rows_as_dicts(
        con.execute(
            f"""
            WITH ranked AS (
              SELECT *, ntile(5) OVER (
                PARTITION BY {group} ORDER BY risk_score, symbol, trade_date
              ) AS group_q
              FROM v3_events
            )
            SELECT {group}, count(*) AS n,
                   avg((mae_20 <= {SEVERE_MAE_MAX})::INTEGER) FILTER (WHERE group_q=5)
                     - avg((mae_20 <= {SEVERE_MAE_MAX})::INTEGER) FILTER (WHERE group_q=1)
                       AS q5_minus_q1_severe_mae_rate,
                   avg(mae_20) FILTER (WHERE group_q=5)
                     - avg(mae_20) FILTER (WHERE group_q=1)
                       AS q5_minus_q1_mean_mae_20,
                   avg((NOT trigger_signal)::INTEGER) FILTER (WHERE group_q=5)
                     - avg((NOT trigger_signal)::INTEGER) FILTER (WHERE group_q=1)
                       AS q5_minus_q1_no_trigger_rate
            FROM ranked GROUP BY {group} ORDER BY {group}
            """
        )
    )


def industry_neutral_check(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    return rows_as_dicts(
        con.execute(
            f"""
            WITH neutral AS (
              SELECT *, percent_rank() OVER (
                PARTITION BY industry ORDER BY risk_score
              ) AS industry_neutral_risk
              FROM v3_events
            ), ranked AS (
              SELECT *, ntile(5) OVER (
                ORDER BY industry_neutral_risk, symbol, trade_date
              ) AS neutral_q
              FROM neutral
            )
            SELECT count(*) AS n, count(DISTINCT industry) AS industries,
                   avg((mae_20 <= {SEVERE_MAE_MAX})::INTEGER) FILTER (WHERE neutral_q=5)
                     - avg((mae_20 <= {SEVERE_MAE_MAX})::INTEGER) FILTER (WHERE neutral_q=1)
                       AS q5_minus_q1_severe_mae_rate,
                   avg(mae_20) FILTER (WHERE neutral_q=5)
                     - avg(mae_20) FILTER (WHERE neutral_q=1)
                       AS q5_minus_q1_mean_mae_20,
                   avg((NOT trigger_signal)::INTEGER) FILTER (WHERE neutral_q=5)
                     - avg((NOT trigger_signal)::INTEGER) FILTER (WHERE neutral_q=1)
                       AS q5_minus_q1_no_trigger_rate
            FROM ranked
            """
        )
    )[0]


def semantic_checks(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    checks = rows_as_dicts(
        con.execute(
            f"""
            SELECT
              (SELECT count(*) FROM v3_feature_history
                WHERE deep_flag AND available_at > decision_at) AS time_travel,
              (SELECT count(*) FROM v3_rank_universe
                WHERE drawdown_60 > {DEEP_DRAWDOWN_MAX}) AS carrier_inversion,
              (SELECT count(*) FROM v3_rank_universe
                WHERE close_location_danger NOT BETWEEN 0 AND 1) AS clv_bounds,
              (SELECT count(*) FROM v3_rank_universe
                WHERE negative_days_5 NOT BETWEEN 0 AND 5) AS persistence_bounds,
              (SELECT count(*) FROM v3_component_ranks
                WHERE close_location_rank NOT BETWEEN 0 AND 1
                   OR current_day_loss_rank NOT BETWEEN 0 AND 1
                   OR negative_days_5_rank NOT BETWEEN 0 AND 1
                   OR adverse_gap_rank NOT BETWEEN 0 AND 1) AS rank_bounds,
              (SELECT count(*) FROM v3_score_universe
                WHERE abs(risk_score - (close_location_rank + current_day_loss_rank
                    + negative_days_5_rank + adverse_gap_rank)/4.0) > 1e-12)
                  AS equal_weight_formula,
              (SELECT count(*) FROM v3_score_universe
                WHERE risk_score NOT BETWEEN 0 AND 1) AS score_bounds,
              (SELECT count(*) FROM v3_events
                WHERE abs(close_location_danger
                  - (1.0-(close-low)/(high-low))) > 1e-12) AS close_location_formula,
              (SELECT count(*) FROM v3_events
                WHERE abs(current_day_loss_danger
                  - (-(close/preclose-1.0))) > 1e-12) AS current_day_loss_formula,
              (SELECT count(*) FROM v3_events
                WHERE abs(adverse_gap_danger
                  - (-(open/preclose-1.0))) > 1e-12) AS adverse_gap_formula,
              (SELECT count(*) FROM v3_events
                WHERE risk_q NOT BETWEEN 1 AND 5
                   OR close_location_q NOT BETWEEN 1 AND 5
                   OR current_day_loss_q NOT BETWEEN 1 AND 5
                   OR negative_days_5_q NOT BETWEEN 1 AND 5
                   OR adverse_gap_q NOT BETWEEN 1 AND 5) AS bucket_bounds,
              (SELECT count(*) - count(DISTINCT (symbol, trade_date)) FROM v3_events)
                AS duplicate_events,
              (SELECT count(*) FROM v3_events
                WHERE (mae_20 <= {SEVERE_MAE_MAX}) !=
                      (immediate_event_mae_20 <= {SEVERE_MAE_MAX}))
                AS severe_label_mismatch,
              (SELECT count(*) FROM v3_events
                WHERE raw_next_date <= trade_date) AS non_t_plus_one_entry,
              (SELECT count(*) FROM v3_events
                WHERE deep_event AND prior_deep_20) AS dedup_violation
            """
        )
    )[0]
    score_columns = {
        row[1]
        for row in con.execute("PRAGMA table_info('v3_score_universe')").fetchall()
    }
    forbidden = {
        "ret_20",
        "mae_20",
        "mfe_20",
        "trigger_signal",
        "trigger_lag",
        "trigger_date",
    }
    checks["future_columns_in_score"] = len(score_columns & forbidden)
    if any(value != 0 for value in checks.values()):
        raise RuntimeError(f"V3 risk invariants failed: {checks}")
    return checks


def result_consistency_checks(
    payload: dict[str, Any], con: duckdb.DuckDBPyConnection
) -> dict[str, Any]:
    n = payload["sample_profile"]["valid_v3_events"]
    severe = payload["baseline"]["severe_events"]
    no_trigger = payload["baseline"]["no_trigger_events"]
    checks: dict[str, Any] = {
        "composite_bucket_count_difference": sum(
            row["n"] for row in payload["composite_gradient"]
        )
        - n,
        "feature_bucket_count_differences": {
            name: sum(row["n"] for row in rows) - n
            for name, rows in payload["individual_feature_gradients"].items()
        },
        "policy_opportunity_count_differences": {
            row["policy"]: row["original_opportunities"] - n
            for row in payload["veto_policies"]
        },
        "policy_participation_count_differences": {
            row["policy"]: row["entered_trades"]
            + round(row["skipped_event_rate"] * n)
            - n
            for row in payload["veto_policies"]
        },
        "maximum_capture_severe_count": max(
            round(row["severe_events_captured"] * severe)
            for row in payload["risk_capture"]
        ),
        "maximum_capture_no_trigger_count": max(
            round(row["no_trigger_events_captured"] * no_trigger)
            for row in payload["risk_capture"]
        ),
    }
    sql = rows_as_dicts(
        con.execute(
            f"""
            SELECT count(*) AS n,
                   count(*) FILTER (WHERE mae_20 <= {SEVERE_MAE_MAX}) AS severe,
                   count(*) FILTER (WHERE NOT trigger_signal) AS no_trigger
            FROM v3_events
            """
        )
    )[0]
    checks["sql_event_count_difference"] = sql["n"] - n
    checks["sql_severe_count_difference"] = sql["severe"] - severe
    checks["sql_no_trigger_count_difference"] = sql["no_trigger"] - no_trigger
    if checks["composite_bucket_count_difference"] != 0:
        raise RuntimeError(f"composite buckets do not reconcile: {checks}")
    if any(checks["feature_bucket_count_differences"].values()):
        raise RuntimeError(f"feature buckets do not reconcile: {checks}")
    if any(checks["policy_opportunity_count_differences"].values()):
        raise RuntimeError(f"policy opportunities do not reconcile: {checks}")
    if any(checks["policy_participation_count_differences"].values()):
        raise RuntimeError(f"policy participation does not reconcile: {checks}")
    if any(checks[key] != 0 for key in (
        "sql_event_count_difference",
        "sql_severe_count_difference",
        "sql_no_trigger_count_difference",
    )):
        raise RuntimeError(f"outcome labels do not reconcile: {checks}")
    return checks


def collect_results(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    individual = {
        name: bucket_metrics(con, spec["bucket"], spec["column"])
        for name, spec in FEATURES.items()
    }
    captures: list[dict[str, Any]] = []
    policies = [baseline_policy(con)]
    skipped: list[dict[str, Any]] = []
    baseline = baseline_summary(con)
    for fraction in VETO_FRACTIONS:
        capture, policy, skipped_row = capture_and_policy(con, fraction)
        policy["alpha_retention"] = (
            policy["opportunity_mean_ret_20"] / baseline["mean_ret_20"]
        )
        capture["participation_rate"] = 1.0 - fraction
        captures.append(capture)
        policies.append(policy)
        skipped.append(skipped_row)
    payload: dict[str, Any] = {
        "research_version": "oversold-reversal-ranking-v3-risk-filter",
        "verdict": VERDICT,
        "single_next_step": SINGLE_NEXT_STEP,
        "definitions": {
            "v1_verdict": "DEPTH_ONLY",
            "v2_verdict": "RISK_FILTER_ONLY",
            "causal_carrier": f"exact V1 LOW plus drawdown_60 <= {DEEP_DRAWDOWN_MAX}",
            "event_deduplication": "first causal deep-carrier observation after no deep-carrier observation in the prior 20 trading rows",
            "t0": "original causal de-duplicated deep-carrier signal date; all V3 predictors end at its close",
            "primary_outcome": f"V2 immediate-entry MAE20 <= {SEVERE_MAE_MAX}; next legal open through the adjusted 20-session path",
            "no_trigger_role": "future V2 no-trigger status is an outcome-only secondary diagnostic and never enters features",
            "features": {name: spec["definition"] for name, spec in FEATURES.items()},
            "composite": "equal average of four same-date percent ranks computed among all causal valid deep-carrier observations before event/outcome filtering; higher is more dangerous",
            "quintiles": "Q1 safest to Q5 most dangerous; pooled descriptive event buckets; persistence uses fixed 0-1/2/3/4/5 bins",
            "conditional_control": "equal-weight high-minus-low risk terciles within date x fixed 5-point drawdown cells with N>=6",
            "veto_policy": "descriptive full-sample highest-risk 10/20/30%; skipped events earn 0% cash at the original-cohort opportunity level",
            "large_winner": f"immediate Ret20 >= {LARGE_WINNER_MIN}",
        },
        "sample_profile": sample_profile(con),
        "checks": semantic_checks(con),
        "baseline": baseline,
        "individual_feature_gradients": individual,
        "composite_gradient": bucket_metrics(con, "risk_q", "risk_score"),
        "severe_risk_separation": separation(con, "risk_q"),
        "simple_baseline_separation": separation(con, "close_location_q"),
        "conditional_date_depth": conditional_date_depth(con),
        "risk_capture": captures,
        "veto_policies": policies,
        "skipped_events": skipped,
        "time_stability": time_stability(con),
        "liquidity_sanity": grouped_gradient(con, "liquidity_tercile"),
        "industry_neutral_sanity": industry_neutral_check(con),
        "market_segment_sanity": grouped_gradient(con, "market_segment"),
    }
    payload["consistency_checks"] = result_consistency_checks(payload, con)
    return payload


def run(
    output_dir: Path,
    *,
    hash_data_files: bool = True,
    symbol_filter: list[str] | None = None,
) -> dict[str, Any]:
    config = json.loads(PREDECESSOR_CONFIG.read_text())
    config["research_version"] = "oversold-reversal-ranking-v3-risk-filter"
    if symbol_filter:
        config.setdefault("runtime", {})["symbol_filter"] = symbol_filter
    identities = validate_inputs(config, hash_data_files=hash_data_files)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="oversold-risk-v3-") as temp_dir:
        con = duckdb.connect()
        con.execute(f"SET threads={int(config['runtime']['threads'])}")
        con.execute(f"SET memory_limit='{config['runtime']['memory_limit']}'")
        con.execute(f"SET temp_directory='{temp_dir}'")
        con.execute("SET preserve_insertion_order=false")
        create_analysis_tables(con, config)
        create_timing_tables(con)
        create_risk_tables(con)
        payload = collect_results(con)
        payload["input_identities"] = identities
        con.close()
    (output_dir / "v3_risk_results.json").write_text(
        json.dumps(payload, indent=2, default=json_default) + "\n"
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-data-file-hashes", action="store_true")
    parser.add_argument("--symbols", nargs="*")
    args = parser.parse_args()
    run(
        args.output,
        hash_data_files=not args.skip_data_file_hashes,
        symbol_filter=args.symbols,
    )


if __name__ == "__main__":
    main()
