#!/usr/bin/env python3
"""V2: causal reversal timing inside a frozen deep-oversold carrier."""

# SQL is kept explicit so chronology and policy alignment remain auditable.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from research.volume_exhaustion_bottom.experiment import (  # noqa: E402
    DEFAULT_CONFIG as PREDECESSOR_CONFIG,
)
from research.volume_exhaustion_bottom.experiment import (  # noqa: E402
    create_analysis_tables,
    json_default,
    validate_inputs,
)

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "reports"
DEEP_DRAWDOWN_MAX = -0.30
V1_Q5_REFERENCE_MAX = -0.3066666666666664
WAIT_SESSIONS = 5
CLV_MIN = 0.70


def rows_as_dicts(cursor: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def create_timing_tables(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TEMP TABLE v2_ordered AS
        SELECT *,
               lead(trade_seq, 20) OVER w AS endpoint_seq_20,
               lead(trade_date, 20) OVER w AS endpoint_date_20,
               lead(adjusted_close, 25) OVER w AS close_h25,
               lead(bad_cum, 25) OVER w AS bad_cum_h25
        FROM analysis_rows
        WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
        """
    )
    con.execute(
        f"""
        CREATE TEMP TABLE v2_flags AS
        SELECT *, (a_flag AND drawdown_60 <= {DEEP_DRAWDOWN_MAX}) AS deep_flag
        FROM v2_ordered
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE v2_marked AS
        SELECT *,
               coalesce(bool_or(deep_flag) OVER (
                   PARTITION BY symbol ORDER BY trade_date
                   ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING), false) AS prior_deep_20,
               (deep_flag AND NOT coalesce(bool_or(deep_flag) OVER (
                   PARTITION BY symbol ORDER BY trade_date
                   ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING), false)) AS deep_event
        FROM v2_flags
        """
    )
    con.execute(
        f"""
        CREATE TEMP TABLE v2_cohort AS
        WITH eligible AS (
            SELECT * EXCLUDE (time_block),
                   drawdown_60 <= {V1_Q5_REFERENCE_MAX} AS v1_q5_reference,
                   CASE WHEN drawdown_60 <= -0.40 THEN 'EXTREME_LE_40'
                        ELSE 'DEEP_30_TO_40' END AS depth_group,
                   CASE WHEN trade_date < DATE '2021-01-01' THEN '2020'
                        WHEN trade_date < DATE '2024-01-01' THEN '2021-2023'
                        ELSE '2024-2026' END AS time_block
            FROM v2_marked
            WHERE deep_flag AND entry_valid AND path_valid_20 AND close_h20 IS NOT NULL
              AND close_h25 IS NOT NULL AND bad_cum_h25 = bad_cum
              AND endpoint_seq_20 = trade_seq + 20
              AND industry IS NOT NULL AND trim(industry) <> ''
        )
        SELECT *, ntile(3) OVER (ORDER BY amount_median_20) AS liquidity_tercile
        FROM eligible
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE v2_fixed AS
        SELECT c.symbol, c.trade_date AS t0_date,
               f.trade_date AS fixed_signal_date, f.trade_seq AS fixed_signal_seq,
               f.entry_valid AND f.path_valid_20 AND f.close_h20 IS NOT NULL
                   AS fixed_executable,
               f.raw_next_date AS fixed_entry_date, f.entry_scale AS fixed_entry_scale,
               f.ret_5 AS fixed_ret_5, f.ret_10 AS fixed_ret_10,
               f.ret_20 AS fixed_ret_20, f.mfe_20 AS fixed_mfe_20,
               f.mae_20 AS fixed_mae_20
        FROM v2_cohort c
        LEFT JOIN analysis_rows f
          ON f.symbol = c.symbol AND f.trade_seq = c.trade_seq + 1
        """
    )
    con.execute(
        f"""
        CREATE TEMP TABLE v2_trigger AS
        SELECT * EXCLUDE (rn)
        FROM (
            SELECT c.symbol, c.trade_date AS t0_date,
                   t.trade_date AS trigger_date, t.trade_seq AS trigger_seq,
                   t.trade_seq - c.trade_seq AS trigger_lag,
                   (t.close - t.low) / nullif(t.high - t.low, 0.0) AS trigger_clv,
                   t.entry_valid AND t.path_valid_20 AND t.close_h20 IS NOT NULL
                       AS trigger_executable,
                   t.raw_next_date AS trigger_entry_date,
                   t.entry_scale AS trigger_entry_scale,
                   t.ret_5 AS trigger_ret_5, t.ret_10 AS trigger_ret_10,
                   t.ret_20 AS trigger_ret_20, t.mfe_20 AS trigger_mfe_20,
                   t.mae_20 AS trigger_mae_20,
                   row_number() OVER (
                       PARTITION BY c.symbol, c.trade_date ORDER BY t.trade_seq
                   ) AS rn
            FROM v2_cohort c
            JOIN analysis_rows t
              ON t.symbol = c.symbol
             AND t.trade_seq BETWEEN c.trade_seq + 1 AND c.trade_seq + {WAIT_SESSIONS}
            WHERE t.close > t.preclose AND t.high > t.low
              AND (t.close - t.low) / (t.high - t.low) >= {CLV_MIN}
        )
        WHERE rn = 1
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE v2_policy_base AS
        SELECT c.*,
               f.fixed_signal_date, f.fixed_signal_seq,
               coalesce(f.fixed_executable, false) AS fixed_executable,
               f.fixed_entry_date, f.fixed_entry_scale,
               f.fixed_ret_5, f.fixed_ret_10, f.fixed_ret_20,
               f.fixed_mfe_20, f.fixed_mae_20,
               t.trigger_date, t.trigger_seq, t.trigger_lag, t.trigger_clv,
               (t.trigger_seq IS NOT NULL) AS trigger_signal,
               coalesce(t.trigger_executable, false) AS trigger_executable,
               t.trigger_entry_date, t.trigger_entry_scale,
               t.trigger_ret_5, t.trigger_ret_10, t.trigger_ret_20,
               t.trigger_mfe_20, t.trigger_mae_20
        FROM v2_cohort c
        LEFT JOIN v2_fixed f ON f.symbol = c.symbol AND f.t0_date = c.trade_date
        LEFT JOIN v2_trigger t ON t.symbol = c.symbol AND t.t0_date = c.trade_date
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE v2_policy_paths AS
        SELECT b.symbol, b.trade_date AS t0_date,
               min(p.adjusted_low) AS immediate_common_low,
               min(p.adjusted_low) FILTER (
                   WHERE p.trade_seq >= b.trade_seq + 2) AS fixed_common_low,
               min(p.adjusted_low) FILTER (
                   WHERE p.trade_seq >= b.trigger_seq + 1) AS trigger_common_low,
               max(p.adjusted_high) FILTER (
                   WHERE p.trade_seq <= b.trigger_seq) AS pre_entry_high
        FROM v2_policy_base b
        JOIN analysis_rows p
          ON p.symbol = b.symbol
         AND p.trade_seq BETWEEN b.trade_seq + 1 AND b.trade_seq + 20
        GROUP BY b.symbol, b.trade_date
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE v2_policy_events AS
        SELECT b.*,
               b.ret_20 AS immediate_event_ret_20,
               b.mae_20 AS immediate_event_mae_20,
               CASE WHEN b.fixed_executable
                    THEN b.fixed_entry_scale * b.close_h20 - 1.0 ELSE 0.0 END
                    AS fixed_event_ret_20,
               CASE WHEN b.fixed_executable
                    THEN b.fixed_entry_scale * p.fixed_common_low - 1.0 ELSE 0.0 END
                    AS fixed_event_mae_20,
               CASE WHEN b.trigger_executable
                    THEN b.trigger_entry_scale * b.close_h20 - 1.0 ELSE 0.0 END
                    AS trigger_event_ret_20,
               CASE WHEN b.trigger_executable
                    THEN b.trigger_entry_scale * p.trigger_common_low - 1.0 ELSE 0.0 END
                    AS trigger_event_mae_20,
               CASE WHEN b.trigger_executable
                    THEN b.entry_scale / b.trigger_entry_scale - 1.0 END
                    AS pre_entry_price_move,
               CASE WHEN b.trigger_executable
                    THEN b.entry_scale * p.pre_entry_high - 1.0 END
                    AS immediate_mfe_before_delayed_entry
        FROM v2_policy_base b
        JOIN v2_policy_paths p
          ON p.symbol = b.symbol AND p.t0_date = b.trade_date
        """
    )


def entry_anchored_metrics(
    con: duckdb.DuckDBPyConnection, where: str
) -> list[dict[str, Any]]:
    return rows_as_dicts(
        con.execute(
            f"""
            WITH policies AS (
                SELECT 'IMMEDIATE' AS policy, true AS executed,
                       ret_5, ret_10, ret_20, mfe_20, mae_20
                FROM v2_policy_events WHERE {where}
                UNION ALL
                SELECT 'FIXED_DELAY_1', fixed_executable,
                       fixed_ret_5, fixed_ret_10, fixed_ret_20,
                       fixed_mfe_20, fixed_mae_20
                FROM v2_policy_events WHERE {where}
                UNION ALL
                SELECT 'REVERSAL_WAIT', trigger_executable,
                       trigger_ret_5, trigger_ret_10, trigger_ret_20,
                       trigger_mfe_20, trigger_mae_20
                FROM v2_policy_events WHERE {where}
            )
            SELECT policy, count(*) AS opportunities,
                   count(*) FILTER (WHERE executed) AS n_trades,
                   avg(executed::INTEGER) AS participation_rate,
                   avg(ret_5) FILTER (WHERE executed) AS mean_ret_5,
                   median(ret_5) FILTER (WHERE executed) AS median_ret_5,
                   avg((ret_5 > 0)::INTEGER) FILTER (WHERE executed) AS positive_rate_5,
                   avg(ret_10) FILTER (WHERE executed) AS mean_ret_10,
                   median(ret_10) FILTER (WHERE executed) AS median_ret_10,
                   avg((ret_10 > 0)::INTEGER) FILTER (WHERE executed) AS positive_rate_10,
                   avg(ret_20) FILTER (WHERE executed) AS mean_ret_20,
                   median(ret_20) FILTER (WHERE executed) AS median_ret_20,
                   avg((ret_20 > 0)::INTEGER) FILTER (WHERE executed) AS positive_rate_20,
                   avg(mfe_20) FILTER (WHERE executed) AS mean_mfe_20,
                   avg(mae_20) FILTER (WHERE executed) AS mean_mae_20,
                   quantile_cont(ret_20, 0.10) FILTER (WHERE executed) AS q10_ret_20,
                   avg((mae_20 <= -0.10)::INTEGER) FILTER (WHERE executed)
                       AS severe_mae_rate_20
            FROM policies GROUP BY policy ORDER BY policy
            """
        )
    )


def event_anchored_metrics(
    con: duckdb.DuckDBPyConnection, where: str
) -> list[dict[str, Any]]:
    return rows_as_dicts(
        con.execute(
            f"""
            WITH policies AS (
                SELECT 'IMMEDIATE' AS policy, true AS executed, 0 AS entry_lag,
                       immediate_event_ret_20 AS policy_ret_20,
                       immediate_event_mae_20 AS policy_mae_20
                FROM v2_policy_events WHERE {where}
                UNION ALL
                SELECT 'FIXED_DELAY_1', fixed_executable, 1,
                       fixed_event_ret_20, fixed_event_mae_20
                FROM v2_policy_events WHERE {where}
                UNION ALL
                SELECT 'REVERSAL_WAIT', trigger_executable, trigger_lag,
                       trigger_event_ret_20, trigger_event_mae_20
                FROM v2_policy_events WHERE {where}
            )
            SELECT policy, count(*) AS opportunities,
                   count(*) FILTER (WHERE executed) AS n_trades,
                   avg(executed::INTEGER) AS participation_rate,
                   avg(policy_ret_20) AS mean_event_ret_20,
                   median(policy_ret_20) AS median_event_ret_20,
                   avg((policy_ret_20 > 0)::INTEGER) AS positive_event_rate_20,
                   quantile_cont(policy_ret_20, 0.10) AS q10_event_ret_20,
                   quantile_cont(policy_ret_20, 0.25) AS q25_event_ret_20,
                   quantile_cont(policy_ret_20, 0.75) AS q75_event_ret_20,
                   avg(policy_mae_20) AS mean_event_mae_20,
                   avg((policy_mae_20 <= -0.10)::INTEGER) AS severe_mae_rate_20,
                   avg((policy_ret_20 <= -0.10)::INTEGER) AS severe_return_rate_20,
                   avg(entry_lag) FILTER (WHERE executed) AS mean_entry_lag,
                   median(entry_lag) FILTER (WHERE executed) AS median_entry_lag
            FROM policies GROUP BY policy ORDER BY policy
            """
        )
    )


def waiting_summary(con: duckdb.DuckDBPyConnection, where: str) -> dict[str, Any]:
    return rows_as_dicts(
        con.execute(
            f"""
            SELECT count(*) AS opportunities,
                   count(*) FILTER (WHERE trigger_signal) AS trigger_signals,
                   avg(trigger_signal::INTEGER) AS trigger_rate,
                   count(*) FILTER (WHERE trigger_executable) AS executed_triggers,
                   avg(trigger_executable::INTEGER) AS participation_rate,
                   count(*) FILTER (WHERE NOT trigger_signal) AS no_trigger_events,
                   avg((NOT trigger_signal)::INTEGER) AS no_trigger_rate,
                   count(*) FILTER (WHERE trigger_signal AND NOT trigger_executable)
                       AS rejected_trigger_entries,
                   avg(trigger_lag) FILTER (WHERE trigger_signal) AS mean_trigger_lag,
                   median(trigger_lag) FILTER (WHERE trigger_signal) AS median_trigger_lag,
                   avg(pre_entry_price_move) FILTER (WHERE trigger_executable)
                       AS mean_pre_entry_price_move,
                   median(pre_entry_price_move) FILTER (WHERE trigger_executable)
                       AS median_pre_entry_price_move,
                   quantile_cont(pre_entry_price_move, 0.25) FILTER (WHERE trigger_executable)
                       AS q25_pre_entry_price_move,
                   quantile_cont(pre_entry_price_move, 0.75) FILTER (WHERE trigger_executable)
                       AS q75_pre_entry_price_move,
                   avg(immediate_mfe_before_delayed_entry) FILTER (WHERE trigger_executable)
                       AS mean_immediate_mfe_before_delayed_entry,
                   avg((pre_entry_price_move > 0)::INTEGER) FILTER (WHERE trigger_executable)
                       AS positive_pre_entry_move_rate,
                   avg((immediate_mfe_before_delayed_entry >= 0.05)::INTEGER)
                       FILTER (WHERE trigger_executable) AS pre_entry_mfe_ge_5_rate,
                   avg((ret_20 >= 0.10)::INTEGER) FILTER (WHERE NOT trigger_signal)
                       AS no_trigger_immediate_ret20_ge_10_rate,
                   avg((mfe_20 >= 0.10)::INTEGER) FILTER (WHERE NOT trigger_signal)
                       AS no_trigger_immediate_mfe20_ge_10_rate
            FROM v2_policy_events WHERE {where}
            """
        )
    )[0]


def trigger_curve(con: duckdb.DuckDBPyConnection, where: str) -> list[dict[str, Any]]:
    return rows_as_dicts(
        con.execute(
            f"""
            WITH horizons AS (SELECT range AS session FROM range(1, {WAIT_SESSIONS + 1})),
            totals AS (SELECT count(*) AS n FROM v2_policy_events WHERE {where})
            SELECT h.session,
                   count(*) FILTER (WHERE e.trigger_signal AND e.trigger_lag <= h.session)
                       AS cumulative_triggered,
                   count(*) FILTER (WHERE e.trigger_executable AND e.trigger_lag <= h.session)
                       AS cumulative_executed,
                   count(*) FILTER (WHERE e.trigger_signal AND e.trigger_lag <= h.session)
                       / any_value(t.n)::DOUBLE AS cumulative_trigger_rate
            FROM horizons h CROSS JOIN v2_policy_events e CROSS JOIN totals t
            WHERE {where}
            GROUP BY h.session ORDER BY h.session
            """
        )
    )


def lag_distribution(con: duckdb.DuckDBPyConnection, where: str) -> list[dict[str, Any]]:
    return rows_as_dicts(
        con.execute(
            f"""
            WITH total AS (SELECT count(*) AS n FROM v2_policy_events WHERE {where})
            SELECT trigger_lag, count(*) AS trigger_signals,
                   count(*) FILTER (WHERE trigger_executable) AS executed_triggers,
                   count(*) / any_value(total.n)::DOUBLE AS cohort_fraction
            FROM v2_policy_events CROSS JOIN total
            WHERE ({where}) AND trigger_signal
            GROUP BY trigger_lag ORDER BY trigger_lag
            """
        )
    )


def immediate_counterfactuals(
    con: duckdb.DuckDBPyConnection, where: str
) -> list[dict[str, Any]]:
    return rows_as_dicts(
        con.execute(
            f"""
            WITH labelled AS (
                SELECT *, CASE WHEN NOT trigger_signal THEN 'NO_TRIGGER'
                               WHEN trigger_executable THEN 'TRIGGERED_EXECUTED'
                               ELSE 'TRIGGERED_ENTRY_REJECTED' END AS cohort
                FROM v2_policy_events WHERE {where}
            )
            SELECT cohort, count(*) AS n,
                   avg(ret_5) AS mean_ret_5, median(ret_5) AS median_ret_5,
                   avg((ret_5 > 0)::INTEGER) AS positive_rate_5,
                   avg(ret_10) AS mean_ret_10, median(ret_10) AS median_ret_10,
                   avg((ret_10 > 0)::INTEGER) AS positive_rate_10,
                   avg(ret_20) AS mean_ret_20, median(ret_20) AS median_ret_20,
                   avg((ret_20 > 0)::INTEGER) AS positive_rate_20,
                   avg(mfe_20) AS mean_mfe_20, avg(mae_20) AS mean_mae_20,
                   quantile_cont(ret_20, 0.10) AS q10_ret_20,
                   avg((mae_20 <= -0.10)::INTEGER) AS severe_mae_rate_20
            FROM labelled GROUP BY cohort ORDER BY cohort
            """
        )
    )


def grouped_policy_check(
    con: duckdb.DuckDBPyConnection, group: str, where: str
) -> list[dict[str, Any]]:
    return rows_as_dicts(
        con.execute(
            f"""
            SELECT {group}, count(*) AS opportunities,
                   avg(trigger_signal::INTEGER) AS trigger_rate,
                   avg(trigger_executable::INTEGER) AS participation_rate,
                   avg(trigger_event_ret_20 - immediate_event_ret_20)
                       AS reversal_minus_immediate_event_ret_20,
                   avg(trigger_event_ret_20 - fixed_event_ret_20)
                       AS reversal_minus_fixed_event_ret_20,
                   median(trigger_event_ret_20) - median(immediate_event_ret_20)
                       AS median_event_ret_20_difference,
                   avg(trigger_ret_20) FILTER (WHERE trigger_executable)
                       - avg(ret_20) AS entry_ret_20_difference,
                   avg(trigger_mae_20) FILTER (WHERE trigger_executable)
                       - avg(mae_20) AS entry_mae_20_difference,
                   avg(trigger_event_mae_20 - immediate_event_mae_20)
                       AS event_mae_20_difference,
                   avg((trigger_event_mae_20 <= -0.10)::INTEGER)
                       - avg((immediate_event_mae_20 <= -0.10)::INTEGER)
                       AS severe_mae_rate_difference,
                   avg(pre_entry_price_move) FILTER (WHERE trigger_executable)
                       AS mean_pre_entry_price_move
            FROM v2_policy_events WHERE {where}
            GROUP BY {group} ORDER BY {group}
            """
        )
    )


def industry_sanity(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    groups = rows_as_dicts(
        con.execute(
            """
            SELECT industry, count(*) AS n,
                   avg(trigger_signal::INTEGER) AS trigger_rate,
                   avg(trigger_event_ret_20 - immediate_event_ret_20)
                       AS reversal_minus_immediate_event_ret_20,
                   avg(trigger_event_mae_20 - immediate_event_mae_20)
                       AS event_mae_20_difference
            FROM v2_policy_events WHERE deep_event
            GROUP BY industry ORDER BY n DESC
            """
        )
    )
    eligible = [row for row in groups if row["n"] >= 50]
    total = sum(row["n"] for row in groups)
    return {
        "industries": len(groups),
        "industries_n_ge_50": len(eligible),
        "largest_industry_share": groups[0]["n"] / total,
        "positive_policy_improvement_fraction_n_ge_50": (
            sum(row["reversal_minus_immediate_event_ret_20"] > 0 for row in eligible)
            / len(eligible)
            if eligible
            else None
        ),
        "top_industries": groups[:10],
    }


def sample_profile(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    raw = rows_as_dicts(
        con.execute(
            """
            SELECT count(*) FILTER (WHERE deep_flag) AS raw_deep_observations,
                   count(*) FILTER (WHERE deep_event) AS raw_deep_events
            FROM v2_marked
            """
        )
    )[0]
    valid = rows_as_dicts(
        con.execute(
            """
            SELECT count(*) AS valid_deep_observations,
                   count(*) FILTER (WHERE deep_event) AS valid_deep_events,
                   count(DISTINCT symbol) AS valid_securities,
                   count(DISTINCT symbol) FILTER (WHERE deep_event) AS event_securities,
                   min(trade_date) FILTER (WHERE deep_event) AS first_event_date,
                   max(trade_date) FILTER (WHERE deep_event) AS last_event_date,
                   count(*) FILTER (WHERE v1_q5_reference) AS q5_reference_observations,
                   count(*) FILTER (WHERE deep_event AND v1_q5_reference)
                       AS q5_reference_events,
                   count(DISTINCT industry) FILTER (WHERE deep_event) AS event_industries
            FROM v2_cohort
            """
        )
    )[0]
    return {**raw, **valid}


def semantic_checks(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    checks = rows_as_dicts(
        con.execute(
            f"""
            SELECT count(*) FILTER (WHERE NOT deep_flag OR drawdown_60 > {DEEP_DRAWDOWN_MAX})
                       AS carrier_inversion,
                   count(*) FILTER (WHERE available_at > decision_at) AS time_travel,
                   count(*) FILTER (WHERE raw_next_date <= trade_date)
                       AS non_t_plus_one_immediate,
                   count(*) FILTER (WHERE endpoint_seq_20 != trade_seq + 20)
                       AS common_endpoint_misaligned,
                   count(*) FILTER (WHERE bad_cum_h25 != bad_cum) AS invalid_25_path,
                   count(*) FILTER (WHERE deep_event AND prior_deep_20)
                       AS dedup_violation,
                   count(*) FILTER (WHERE fixed_signal_seq != trade_seq + 1)
                       AS fixed_delay_misaligned,
                   count(*) FILTER (WHERE fixed_executable AND fixed_entry_date <= fixed_signal_date)
                       AS fixed_non_t_plus_one,
                   count(*) FILTER (WHERE trigger_signal AND trigger_lag NOT BETWEEN 1 AND {WAIT_SESSIONS})
                       AS trigger_lag_invalid,
                   count(*) FILTER (WHERE trigger_signal AND trigger_date <= trade_date)
                       AS noncausal_trigger_date,
                   count(*) FILTER (WHERE trigger_signal AND
                       (trigger_clv < {CLV_MIN} OR trigger_clv > 1.0)) AS trigger_formula_invalid,
                   count(*) FILTER (WHERE trigger_executable AND trigger_entry_date <= trigger_date)
                       AS trigger_non_t_plus_one,
                   count(*) FILTER (WHERE NOT trigger_signal AND trigger_event_ret_20 != 0.0)
                       AS no_trigger_nonzero_policy_return,
                   count(*) FILTER (WHERE NOT trigger_executable AND trigger_event_ret_20 != 0.0)
                       AS nonexecuted_nonzero_policy_return,
                   count(*) FILTER (WHERE NOT fixed_executable AND fixed_event_ret_20 != 0.0)
                       AS fixed_nonexecuted_nonzero_policy_return,
                   count(*) FILTER (WHERE trigger_signal != (trigger_seq IS NOT NULL))
                       AS trigger_reconciliation
            FROM v2_policy_events
            """
        )
    )[0]
    if any(value != 0 for value in checks.values()):
        raise RuntimeError(f"V2 timing invariants failed: {checks}")
    return checks


def run(
    output_dir: Path,
    *,
    hash_data_files: bool = True,
    symbol_filter: list[str] | None = None,
) -> dict[str, Any]:
    config = json.loads(PREDECESSOR_CONFIG.read_text())
    config["research_version"] = "oversold-reversal-ranking-v2-timing"
    if symbol_filter:
        config.setdefault("runtime", {})["symbol_filter"] = symbol_filter
    identities = validate_inputs(config, hash_data_files=hash_data_files)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="oversold-timing-v2-") as temp_dir:
        con = duckdb.connect()
        con.execute(f"SET threads={int(config['runtime']['threads'])}")
        con.execute(f"SET memory_limit='{config['runtime']['memory_limit']}'")
        con.execute(f"SET temp_directory='{temp_dir}'")
        con.execute("SET preserve_insertion_order=false")
        create_analysis_tables(con, config)
        create_timing_tables(con)
        checks = semantic_checks(con)
        payload = {
            "research_version": config["research_version"],
            "verdict": "RISK_FILTER_ONLY",
            "single_next_step": "Test one frozen staged-entry risk overlay: partial immediate exposure at t0 and the remaining exposure only after the unchanged primary reversal trigger, judged on common-horizon return and downside after costs.",
            "input_identities": identities,
            "definitions": {
                "v1_verdict": "DEPTH_ONLY",
                "v1_q5_research_reference": f"drawdown_60 <= {V1_Q5_REFERENCE_MAX}; ex-post feature-percentile reference only",
                "causal_carrier": f"exact V1 LOW plus drawdown_60 <= {DEEP_DRAWDOWN_MAX}",
                "event_deduplication": "first causal deep-carrier observation after no deep-carrier observation in the prior 20 trading rows",
                "primary_trigger": f"first session t0+1..t0+{WAIT_SESSIONS} with close > preclose and CLV=(close-low)/(high-low) >= {CLV_MIN}; zero-range days fail closed",
                "waiting_window_sessions": WAIT_SESSIONS,
                "immediate_policy": "enter next listed legal open after t0 close",
                "fixed_delay_policy": "observe t0+1 session, enter next listed legal open after that close regardless of price pattern",
                "reversal_policy": "enter next listed legal open after first primary trigger; cash at 0% if no trigger or rejected entry",
                "common_event_endpoint": "adjusted close 20 trading sessions after original t0 for every policy",
                "entry_anchored_horizons": "5/10/20 trading sessions from each policy's actual legal entry open",
                "severe_downside": "Ret20 <= -10% or MAE20 <= -10%",
            },
            "checks": checks,
            "sample_profile": sample_profile(con),
            "primary_entry_anchored": entry_anchored_metrics(con, "deep_event"),
            "primary_event_anchored": event_anchored_metrics(con, "deep_event"),
            "primary_waiting_summary": waiting_summary(con, "deep_event"),
            "primary_trigger_curve": trigger_curve(con, "deep_event"),
            "primary_lag_distribution": lag_distribution(con, "deep_event"),
            "primary_immediate_counterfactuals": immediate_counterfactuals(con, "deep_event"),
            "depth_interaction": grouped_policy_check(con, "depth_group", "deep_event"),
            "time_stability": grouped_policy_check(con, "time_block", "deep_event"),
            "liquidity_sanity": grouped_policy_check(con, "liquidity_tercile", "deep_event"),
            "industry_sanity": industry_sanity(con),
            "all_observation_support": {
                "entry_anchored": entry_anchored_metrics(con, "true"),
                "event_anchored": event_anchored_metrics(con, "true"),
                "waiting_summary": waiting_summary(con, "true"),
            },
        }
        con.close()
    (output_dir / "v2_timing_results.json").write_text(
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
