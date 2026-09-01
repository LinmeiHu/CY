#!/usr/bin/env python3
"""V4: event-level risk-aware sizing with the frozen V3 score."""

# Explicit SQL keeps the score reuse, weight normalization, and contribution arithmetic
# auditable. The long statements are intentional.
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

from research.oversold_reversal_ranking.v2_timing import (  # noqa: E402
    create_timing_tables,
)
from research.oversold_reversal_ranking.v3_risk_filter import (  # noqa: E402
    LARGE_WINNER_MIN,
    SEVERE_MAE_MAX,
    create_risk_tables,
    rows_as_dicts,
)
from research.oversold_reversal_ranking.v3_risk_filter import (  # noqa: E402
    semantic_checks as v3_semantic_checks,
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
CAPITAL_SEVERE_MAE_MAX = -0.10

# Fixed after the first broad V4 outcome-bearing run. The methodology and maps were already
# frozen and were not altered in response to results.
VERDICT = "SIZING_SURVIVES"
SINGLE_NEXT_STEP = "Freeze the carrier, V3 risk score, and V4 sizing map, then run the first true overlapping-position portfolio backtest with realistic capital competition and transaction costs."

POLICIES = (
    "EQUAL_SIZE",
    "RISK_AWARE_CAPITAL_PRESERVING",
    "CONSERVATIVE_OVERLAY",
    "CLV_ONLY_CAPITAL_PRESERVING",
)


def create_sizing_tables(con: duckdb.DuckDBPyConnection) -> None:
    """Create weights from frozen V3 buckets before rejoining future outcomes."""
    con.execute(
        """
        CREATE TEMP TABLE v4_weight_map(
          risk_q INTEGER, primary_raw DOUBLE, conservative DOUBLE
        );
        INSERT INTO v4_weight_map VALUES
          (1, 1.25,  1.00),
          (2, 1.125, 0.95),
          (3, 1.00,  0.90),
          (4, 0.875, 0.80),
          (5, 0.75,  0.70)
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE v4_weight_base AS
        SELECT e.symbol, e.trade_date, e.risk_q, e.close_location_q,
               r.primary_raw, r.conservative AS conservative_weight,
               c.primary_raw AS clv_primary_raw
        FROM v3_events e
        JOIN v4_weight_map r ON r.risk_q = e.risk_q
        JOIN v4_weight_map c ON c.risk_q = e.close_location_q
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE v4_normalizers AS
        SELECT avg(primary_raw) AS primary_raw_mean,
               avg(clv_primary_raw) AS clv_primary_raw_mean
        FROM v4_weight_base
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE v4_weights_only AS
        SELECT b.symbol, b.trade_date, b.risk_q, b.close_location_q,
               1.0::DOUBLE AS equal_weight,
               b.primary_raw / n.primary_raw_mean AS primary_weight,
               b.conservative_weight,
               b.clv_primary_raw / n.clv_primary_raw_mean AS clv_primary_weight
        FROM v4_weight_base b CROSS JOIN v4_normalizers n
        """
    )
    # Outcome labels and returns enter only after all four policy weights are complete.
    con.execute(
        """
        CREATE TEMP TABLE v4_events AS
        SELECT e.*, w.equal_weight, w.primary_weight,
               w.conservative_weight, w.clv_primary_weight,
               CASE WHEN e.trade_date < DATE '2021-01-01' THEN '2018-2020'
                    WHEN e.trade_date < DATE '2024-01-01' THEN '2021-2023'
                    ELSE '2024-2026' END AS v4_time_block
        FROM v3_events e JOIN v4_weights_only w USING (symbol, trade_date)
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE v4_policy_events AS
        SELECT e.*, p.policy, p.position_weight,
               p.position_weight * e.ret_5 AS weighted_ret_5,
               p.position_weight * e.ret_10 AS weighted_ret_10,
               p.position_weight * e.ret_20 AS weighted_ret_20,
               p.position_weight * e.mfe_20 AS capital_mfe_20,
               p.position_weight * e.mae_20 AS capital_mae_20
        FROM v4_events e
        CROSS JOIN LATERAL (
          VALUES
            ('EQUAL_SIZE', e.equal_weight),
            ('RISK_AWARE_CAPITAL_PRESERVING', e.primary_weight),
            ('CONSERVATIVE_OVERLAY', e.conservative_weight),
            ('CLV_ONLY_CAPITAL_PRESERVING', e.clv_primary_weight)
        ) p(policy, position_weight)
        """
    )


def sample_and_weights(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    profile = rows_as_dicts(
        con.execute(
            """
            SELECT count(*) AS events, count(DISTINCT symbol) AS securities,
                   min(trade_date) AS first_event_date,
                   max(trade_date) AS last_event_date,
                   count(DISTINCT industry) AS industries,
                   count(DISTINCT trade_date) AS event_dates
            FROM v4_events
            """
        )
    )[0]
    weights = rows_as_dicts(
        con.execute(
            """
            SELECT risk_q, count(*) AS n,
                   any_value(primary_raw) AS primary_raw_weight,
                   any_value(primary_raw / primary_raw_mean) AS primary_weight,
                   any_value(conservative_weight) AS conservative_weight
            FROM v4_weight_base CROSS JOIN v4_normalizers
            GROUP BY risk_q ORDER BY risk_q
            """
        )
    )
    means = rows_as_dicts(
        con.execute(
            """
            SELECT avg(equal_weight) AS equal_mean_weight,
                   avg(primary_weight) AS primary_mean_weight,
                   avg(conservative_weight) AS conservative_mean_weight,
                   avg(clv_primary_weight) AS clv_primary_mean_weight,
                   min(primary_weight) AS primary_min_weight,
                   max(primary_weight) AS primary_max_weight
            FROM v4_events
            """
        )
    )[0]
    return {**profile, "quintile_weights": weights, **means}


def policy_metrics(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    return rows_as_dicts(
        con.execute(
            f"""
            SELECT policy, count(*) AS n, sum(position_weight) AS total_weight,
                   avg(position_weight) AS mean_position_weight,
                   min(position_weight) AS min_position_weight,
                   max(position_weight) AS max_position_weight,
                   avg(weighted_ret_5) AS mean_weighted_ret_5,
                   avg(weighted_ret_10) AS mean_weighted_ret_10,
                   avg(weighted_ret_20) AS mean_weighted_ret_20,
                   sum(weighted_ret_20) AS total_weighted_ret_20,
                   median(weighted_ret_20) AS median_weighted_ret_20,
                   avg(capital_mae_20) AS mean_capital_mae_20,
                   median(capital_mae_20) AS median_capital_mae_20,
                   quantile_cont(capital_mae_20, 0.10) AS q10_capital_mae_20,
                   quantile_cont(capital_mae_20, 0.25) AS q25_capital_mae_20,
                   avg(capital_mfe_20) AS mean_capital_mfe_20,
                   avg((mae_20 <= {SEVERE_MAE_MAX})::INTEGER)
                     AS underlying_severe_event_rate,
                   avg((capital_mae_20 <= {CAPITAL_SEVERE_MAE_MAX})::INTEGER)
                     AS capital_severe_loss_rate,
                   avg(weighted_ret_20) / abs(avg(capital_mae_20))
                     AS return_downside_efficiency
            FROM v4_policy_events GROUP BY policy ORDER BY policy
            """
        )
    )


def capital_allocation(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    return rows_as_dicts(
        con.execute(
            f"""
            WITH groups AS (
              SELECT policy, position_weight, label
              FROM v4_policy_events
              CROSS JOIN LATERAL (
                VALUES
                  ('UNDERLYING_SEVERE', mae_20 <= {SEVERE_MAE_MAX}),
                  ('UNDERLYING_NON_SEVERE', mae_20 > {SEVERE_MAE_MAX}),
                  ('V2_NO_TRIGGER', NOT trigger_signal),
                  ('POSITIVE_RET20', ret_20 > 0),
                  ('LARGE_WINNER_RET20_GE_10', ret_20 >= {LARGE_WINNER_MIN}),
                  ('LOSING_RET20', ret_20 <= 0)
              ) g(label, in_group)
              WHERE in_group
            ), totals AS (
              SELECT policy, sum(position_weight) AS total_weight
              FROM v4_policy_events GROUP BY policy
            )
            SELECT g.policy, g.label, count(*) AS events,
                   sum(g.position_weight) AS allocated_weight,
                   avg(g.position_weight) AS mean_group_weight,
                   sum(g.position_weight) / any_value(t.total_weight) AS capital_share,
                   avg(g.position_weight) AS capital_retention_vs_equal
            FROM groups g JOIN totals t USING (policy)
            GROUP BY g.policy, g.label ORDER BY g.policy, g.label
            """
        )
    )


def quintile_contributions(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    return rows_as_dicts(
        con.execute(
            f"""
            WITH total AS (SELECT count(*) AS n FROM v4_events)
            SELECT e.risk_q, count(*) AS n,
                   avg(e.ret_20) AS raw_mean_ret_20,
                   avg(e.mae_20) AS raw_mean_mae_20,
                   avg((e.mae_20 <= {SEVERE_MAE_MAX})::INTEGER) AS raw_severe_mae_rate,
                   any_value(e.primary_weight) AS primary_weight,
                   sum(e.primary_weight) / any_value(t.n) AS cohort_capital_share,
                   sum(e.primary_weight * e.ret_20) / any_value(t.n)
                     AS weighted_ret_20_contribution,
                   sum(e.primary_weight * e.mae_20) / any_value(t.n)
                     AS capital_mae_20_contribution,
                   sum(e.primary_weight * e.mfe_20) / any_value(t.n)
                     AS capital_mfe_20_contribution
            FROM v4_events e CROSS JOIN total t
            GROUP BY e.risk_q ORDER BY e.risk_q
            """
        )
    )


def time_stability(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    return rows_as_dicts(
        con.execute(
            f"""
            SELECT v4_time_block, policy, count(*) AS n,
                   avg(position_weight) AS mean_position_weight,
                   avg(weighted_ret_20) AS mean_weighted_ret_20,
                   avg(capital_mae_20) AS mean_capital_mae_20,
                   quantile_cont(capital_mae_20, 0.10) AS q10_capital_mae_20,
                   avg(weighted_ret_20) / abs(avg(capital_mae_20))
                     AS return_downside_efficiency,
                   sum(position_weight) FILTER (WHERE mae_20 <= {SEVERE_MAE_MAX})
                     / sum(position_weight) AS severe_event_capital_share,
                   avg(position_weight) FILTER (WHERE mae_20 <= {SEVERE_MAE_MAX})
                     AS severe_event_mean_weight,
                   sum(position_weight) FILTER (WHERE NOT trigger_signal)
                     / sum(position_weight) AS no_trigger_capital_share
            FROM v4_policy_events
            WHERE policy IN ('EQUAL_SIZE','RISK_AWARE_CAPITAL_PRESERVING')
            GROUP BY v4_time_block, policy ORDER BY v4_time_block, policy
            """
        )
    )


def liquidity_sanity(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    return rows_as_dicts(
        con.execute(
            f"""
            SELECT liquidity_tercile, policy, count(*) AS n,
                   avg(position_weight) AS mean_position_weight,
                   avg(weighted_ret_20) AS mean_weighted_ret_20,
                   avg(capital_mae_20) AS mean_capital_mae_20,
                   avg(weighted_ret_20) / abs(avg(capital_mae_20))
                     AS return_downside_efficiency,
                   sum(position_weight) FILTER (WHERE mae_20 <= {SEVERE_MAE_MAX})
                     / sum(position_weight) AS severe_event_capital_share
            FROM v4_policy_events
            WHERE policy IN ('EQUAL_SIZE','RISK_AWARE_CAPITAL_PRESERVING')
            GROUP BY liquidity_tercile, policy ORDER BY liquidity_tercile, policy
            """
        )
    )


def industry_sanity(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    rows = rows_as_dicts(
        con.execute(
            f"""
            SELECT industry, count(*) AS n,
                   avg(primary_weight * ret_20) - avg(ret_20) AS ret_20_difference,
                   avg(primary_weight * mae_20) - avg(mae_20) AS capital_mae_difference,
                   avg(primary_weight * ret_20) / abs(avg(primary_weight * mae_20))
                     - avg(ret_20) / abs(avg(mae_20)) AS efficiency_difference,
                   sum(primary_weight) FILTER (WHERE mae_20 <= {SEVERE_MAE_MAX})
                     / sum(primary_weight)
                     - avg((mae_20 <= {SEVERE_MAE_MAX})::INTEGER)
                       AS severe_capital_share_difference
            FROM v4_events GROUP BY industry ORDER BY n DESC
            """
        )
    )
    eligible = [row for row in rows if row["n"] >= 50]
    total = sum(row["n"] for row in rows)
    return {
        "industries": len(rows),
        "industries_n_ge_50": len(eligible),
        "largest_industry_share": rows[0]["n"] / total,
        "positive_return_difference_fraction_n_ge_50": (
            sum(row["ret_20_difference"] > 0 for row in eligible) / len(eligible)
            if eligible
            else None
        ),
        "improved_capital_mae_fraction_n_ge_50": (
            sum(row["capital_mae_difference"] > 0 for row in eligible)
            / len(eligible)
            if eligible
            else None
        ),
        "improved_efficiency_fraction_n_ge_50": (
            sum(row["efficiency_difference"] > 0 for row in eligible) / len(eligible)
            if eligible
            else None
        ),
        "reduced_severe_capital_share_fraction_n_ge_50": (
            sum(row["severe_capital_share_difference"] < 0 for row in eligible)
            / len(eligible)
            if eligible
            else None
        ),
        "top_industries": rows[:10],
    }


def semantic_checks(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    v3_checks = v3_semantic_checks(con)
    checks = rows_as_dicts(
        con.execute(
            f"""
            SELECT
              (SELECT count(*) FROM v4_weights_only) -
                (SELECT count(*) FROM v3_events) AS cohort_count_difference,
              (SELECT count(*) - count(DISTINCT (symbol, trade_date))
                 FROM v4_weights_only) AS duplicate_weights,
              (SELECT CASE WHEN abs(avg(primary_weight)-1.0) > 1e-12
                           THEN 1 ELSE 0 END FROM v4_weights_only)
                AS primary_mean_weight_not_one,
              (SELECT CASE WHEN abs(avg(clv_primary_weight)-1.0) > 1e-12
                           THEN 1 ELSE 0 END FROM v4_weights_only)
                AS clv_mean_weight_not_one,
              (SELECT count(*) FROM v4_weights_only
                 WHERE primary_weight <= 0 OR conservative_weight <= 0
                    OR clv_primary_weight <= 0) AS nonpositive_weight,
              (SELECT count(*) FROM (
                 SELECT risk_q, any_value(primary_weight) AS w
                 FROM v4_weights_only GROUP BY risk_q
               ) a JOIN (
                 SELECT risk_q, any_value(primary_weight) AS w
                 FROM v4_weights_only GROUP BY risk_q
               ) b ON b.risk_q = a.risk_q + 1 WHERE a.w <= b.w)
                AS primary_nonmonotone,
              (SELECT count(*) FROM (
                 SELECT risk_q, any_value(conservative_weight) AS w
                 FROM v4_weights_only GROUP BY risk_q
               ) a JOIN (
                 SELECT risk_q, any_value(conservative_weight) AS w
                 FROM v4_weights_only GROUP BY risk_q
               ) b ON b.risk_q = a.risk_q + 1 WHERE a.w <= b.w)
                AS conservative_nonmonotone,
              (SELECT count(*) FROM v4_policy_events
                 WHERE abs(weighted_ret_20-position_weight*ret_20) > 1e-12)
                AS weighted_return_formula,
              (SELECT count(*) FROM v4_policy_events
                 WHERE abs(capital_mae_20-position_weight*mae_20) > 1e-12)
                AS capital_mae_formula,
              (SELECT count(*) FROM v4_policy_events
                 WHERE abs(capital_mfe_20-position_weight*mfe_20) > 1e-12)
                AS capital_mfe_formula,
              (SELECT count(*) FROM v4_policy_events
                 WHERE (mae_20 <= {SEVERE_MAE_MAX}) !=
                       (immediate_event_mae_20 <= {SEVERE_MAE_MAX}))
                AS underlying_severe_label_mismatch,
              (SELECT count(*) FROM v4_policy_events
                 WHERE raw_next_date <= trade_date) AS non_t_plus_one_entry,
              (SELECT count(*) FROM v4_policy_events
                 WHERE deep_event AND prior_deep_20) AS dedup_violation,
              (SELECT count(*) FROM v4_policy_events) -
                4*(SELECT count(*) FROM v3_events) AS policy_row_difference
            """
        )
    )[0]
    weight_columns = {
        row[1] for row in con.execute("PRAGMA table_info('v4_weights_only')").fetchall()
    }
    forbidden = {
        "ret_5",
        "ret_10",
        "ret_20",
        "mae_20",
        "mfe_20",
        "trigger_signal",
        "trigger_lag",
        "trigger_date",
    }
    checks["future_columns_in_weights"] = len(weight_columns & forbidden)
    checks.update({f"v3_{key}": value for key, value in v3_checks.items()})
    if any(value != 0 for value in checks.values()):
        raise RuntimeError(f"V4 sizing invariants failed: {checks}")
    return checks


def consistency_checks(payload: dict[str, Any]) -> dict[str, Any]:
    n = payload["sample_profile"]["events"]
    policies = payload["policy_metrics"]
    primary = next(
        row for row in policies if row["policy"] == "RISK_AWARE_CAPITAL_PRESERVING"
    )
    contributions = payload["quintile_contributions"]
    allocation = payload["capital_allocation"]
    checks = {
        "policy_n_differences": {row["policy"]: row["n"] - n for row in policies},
        "quintile_count_difference": sum(row["n"] for row in contributions) - n,
        "weighted_ret_contribution_difference": sum(
            row["weighted_ret_20_contribution"] for row in contributions
        )
        - primary["mean_weighted_ret_20"],
        "capital_mae_contribution_difference": sum(
            row["capital_mae_20_contribution"] for row in contributions
        )
        - primary["mean_capital_mae_20"],
        "period_policy_count_differences": {},
        "severe_nonsevere_share_differences": {},
        "winner_loser_share_differences": {},
    }
    for policy in ("EQUAL_SIZE", "RISK_AWARE_CAPITAL_PRESERVING"):
        period_n = sum(
            row["n"] for row in payload["time_stability"] if row["policy"] == policy
        )
        checks["period_policy_count_differences"][policy] = period_n - n
        by_label = {
            row["label"]: row
            for row in allocation
            if row["policy"] == policy
        }
        checks["severe_nonsevere_share_differences"][policy] = (
            by_label["UNDERLYING_SEVERE"]["capital_share"]
            + by_label["UNDERLYING_NON_SEVERE"]["capital_share"]
            - 1.0
        )
        checks["winner_loser_share_differences"][policy] = (
            by_label["POSITIVE_RET20"]["capital_share"]
            + by_label["LOSING_RET20"]["capital_share"]
            - 1.0
        )
    if any(checks["policy_n_differences"].values()):
        raise RuntimeError(f"policy counts do not reconcile: {checks}")
    if checks["quintile_count_difference"] != 0:
        raise RuntimeError(f"quintiles do not reconcile: {checks}")
    if abs(checks["weighted_ret_contribution_difference"]) > 1e-12:
        raise RuntimeError(f"return contributions do not reconcile: {checks}")
    if abs(checks["capital_mae_contribution_difference"]) > 1e-12:
        raise RuntimeError(f"MAE contributions do not reconcile: {checks}")
    for family in (
        "period_policy_count_differences",
        "severe_nonsevere_share_differences",
        "winner_loser_share_differences",
    ):
        if any(abs(value) > 1e-12 for value in checks[family].values()):
            raise RuntimeError(f"{family} does not reconcile: {checks}")
    return checks


def comparison_summaries(
    metrics: list[dict[str, Any]], allocation: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    by_policy = {row["policy"]: row for row in metrics}
    equal = by_policy["EQUAL_SIZE"]
    primary = by_policy["RISK_AWARE_CAPITAL_PRESERVING"]
    conservative = by_policy["CONSERVATIVE_OVERLAY"]
    clv = by_policy["CLV_ONLY_CAPITAL_PRESERVING"]
    primary_comparison = {
        "mean_exposure_difference": primary["mean_position_weight"]
        - equal["mean_position_weight"],
        "mean_weighted_ret_5_difference": primary["mean_weighted_ret_5"]
        - equal["mean_weighted_ret_5"],
        "mean_weighted_ret_10_difference": primary["mean_weighted_ret_10"]
        - equal["mean_weighted_ret_10"],
        "mean_weighted_ret_20_difference": primary["mean_weighted_ret_20"]
        - equal["mean_weighted_ret_20"],
        "median_weighted_ret_20_difference": primary["median_weighted_ret_20"]
        - equal["median_weighted_ret_20"],
        "mean_capital_mae_20_difference": primary["mean_capital_mae_20"]
        - equal["mean_capital_mae_20"],
        "median_capital_mae_20_difference": primary["median_capital_mae_20"]
        - equal["median_capital_mae_20"],
        "q10_capital_mae_20_difference": primary["q10_capital_mae_20"]
        - equal["q10_capital_mae_20"],
        "q25_capital_mae_20_difference": primary["q25_capital_mae_20"]
        - equal["q25_capital_mae_20"],
        "mean_capital_mfe_20_difference": primary["mean_capital_mfe_20"]
        - equal["mean_capital_mfe_20"],
        "capital_severe_loss_rate_difference": primary["capital_severe_loss_rate"]
        - equal["capital_severe_loss_rate"],
        "return_downside_efficiency_difference": primary[
            "return_downside_efficiency"
        ]
        - equal["return_downside_efficiency"],
        "return_downside_efficiency_ratio": primary["return_downside_efficiency"]
        / equal["return_downside_efficiency"],
    }
    labels = {
        (row["policy"], row["label"]): row for row in allocation
    }
    allocation_comparison = {
        label: {
            "equal_capital_share": labels[("EQUAL_SIZE", label)]["capital_share"],
            "primary_capital_share": labels[
                ("RISK_AWARE_CAPITAL_PRESERVING", label)
            ]["capital_share"],
            "capital_share_difference": labels[
                ("RISK_AWARE_CAPITAL_PRESERVING", label)
            ]["capital_share"]
            - labels[("EQUAL_SIZE", label)]["capital_share"],
            "primary_mean_group_weight": labels[
                ("RISK_AWARE_CAPITAL_PRESERVING", label)
            ]["mean_group_weight"],
        }
        for label in (
            "UNDERLYING_SEVERE",
            "UNDERLYING_NON_SEVERE",
            "V2_NO_TRIGGER",
            "POSITIVE_RET20",
            "LARGE_WINNER_RET20_GE_10",
            "LOSING_RET20",
        )
    }
    exposure = conservative["mean_position_weight"]
    uniform_reference = {
        "matched_mean_exposure": exposure,
        "uniform_mean_weighted_ret_20": exposure * equal["mean_weighted_ret_20"],
        "uniform_mean_capital_mae_20": exposure * equal["mean_capital_mae_20"],
        "uniform_q10_capital_mae_20": exposure * equal["q10_capital_mae_20"],
        "uniform_mean_capital_mfe_20": exposure * equal["mean_capital_mfe_20"],
        "uniform_return_downside_efficiency": equal["return_downside_efficiency"],
        "conservative_minus_uniform_ret_20": conservative["mean_weighted_ret_20"]
        - exposure * equal["mean_weighted_ret_20"],
        "conservative_minus_uniform_mean_capital_mae_20": conservative[
            "mean_capital_mae_20"
        ]
        - exposure * equal["mean_capital_mae_20"],
        "conservative_minus_uniform_efficiency": conservative[
            "return_downside_efficiency"
        ]
        - equal["return_downside_efficiency"],
        "return_retained_vs_equal": conservative["mean_weighted_ret_20"]
        / equal["mean_weighted_ret_20"],
        "clv_minus_equal_ret_20": clv["mean_weighted_ret_20"]
        - equal["mean_weighted_ret_20"],
        "clv_minus_equal_mean_capital_mae_20": clv["mean_capital_mae_20"]
        - equal["mean_capital_mae_20"],
        "clv_minus_equal_efficiency": clv["return_downside_efficiency"]
        - equal["return_downside_efficiency"],
    }
    return primary_comparison, allocation_comparison, uniform_reference


def collect_results(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    metrics = policy_metrics(con)
    allocation = capital_allocation(con)
    primary_comparison, allocation_comparison, conservative_attribution = (
        comparison_summaries(metrics, allocation)
    )
    payload: dict[str, Any] = {
        "research_version": "oversold-reversal-ranking-v4-sizing",
        "verdict": VERDICT,
        "single_next_step": SINGLE_NEXT_STEP,
        "definitions": {
            "v1_verdict": "DEPTH_ONLY",
            "v2_verdict": "RISK_FILTER_ONLY",
            "v3_verdict": "SIZING_SIGNAL_ONLY",
            "carrier": "exact V1 LOW plus causal drawdown_60 <= -30%; exact V3 event cohort",
            "score_reuse": "imports and executes V3 create_risk_tables unchanged; equal average of four same-date causal danger ranks; higher is more dangerous",
            "primary_mapping": "raw risk_q weights Q1-Q5 = 1.25/1.125/1.0/0.875/0.75, divided by exact cohort-weighted raw mean",
            "conservative_mapping": "risk_q weights Q1-Q5 = 1.0/0.95/0.90/0.80/0.70 without normalization",
            "simple_baseline": "V3 close_location_q with the same normalized primary weight schedule",
            "capital_outcomes": "position weight multiplied by inherited immediate-entry Ret5/10/20, MFE20, and MAE20",
            "underlying_severe": f"unchanged stock-path label MAE20 <= {SEVERE_MAE_MAX}",
            "capital_severe": f"position_weight * MAE20 <= {CAPITAL_SEVERE_MAE_MAX}",
            "return_downside_efficiency": "mean weighted Ret20 / abs(mean capital MAE20)",
            "large_winner": f"inherited immediate Ret20 >= {LARGE_WINNER_MIN}",
            "deployability": "V3 continuous score is causal at t0 close; pooled V3 quintile boundaries are descriptive full-sample assignments, not production thresholds",
        },
        "sample_profile": sample_and_weights(con),
        "checks": semantic_checks(con),
        "policy_metrics": metrics,
        "primary_equal_capital_comparison": primary_comparison,
        "capital_allocation": allocation,
        "capital_allocation_comparison": allocation_comparison,
        "quintile_contributions": quintile_contributions(con),
        "conservative_overlay_attribution": conservative_attribution,
        "time_stability": time_stability(con),
        "liquidity_sanity": liquidity_sanity(con),
        "industry_sanity": industry_sanity(con),
    }
    payload["consistency_checks"] = consistency_checks(payload)
    return payload


def run(
    output_dir: Path,
    *,
    hash_data_files: bool = True,
    symbol_filter: list[str] | None = None,
) -> dict[str, Any]:
    config = json.loads(PREDECESSOR_CONFIG.read_text())
    config["research_version"] = "oversold-reversal-ranking-v4-sizing"
    if symbol_filter:
        config.setdefault("runtime", {})["symbol_filter"] = symbol_filter
    identities = validate_inputs(config, hash_data_files=hash_data_files)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="oversold-sizing-v4-") as temp_dir:
        con = duckdb.connect()
        con.execute(f"SET threads={int(config['runtime']['threads'])}")
        con.execute(f"SET memory_limit='{config['runtime']['memory_limit']}'")
        con.execute(f"SET temp_directory='{temp_dir}'")
        con.execute("SET preserve_insertion_order=false")
        create_analysis_tables(con, config)
        create_timing_tables(con)
        create_risk_tables(con)
        create_sizing_tables(con)
        payload = collect_results(con)
        payload["input_identities"] = identities
        con.close()
    (output_dir / "v4_sizing_results.json").write_text(
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
