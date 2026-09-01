#!/usr/bin/env python3
"""PIT-safe A-share oversold reversal ranking V1 study."""

# SQL window clauses are intentionally explicit and long.
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


def rows_as_dicts(cursor: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def create_axis_tables(con: duckdb.DuckDBPyConnection) -> None:
    """Add causal benchmark, axis, bucket, and 20-session event tables."""
    con.execute(
        """
        CREATE TEMP TABLE oversold_marked AS
        SELECT *,
               adjusted_close / lag(adjusted_close, 10) OVER (
                   PARTITION BY symbol ORDER BY trade_date) - 1.0 AS return_10,
               (a_flag AND NOT coalesce(bool_or(a_flag) OVER (
                   PARTITION BY symbol ORDER BY trade_date
                   ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING), false)) AS dedup20_flag
        FROM analysis_rows
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE market_daily AS
        SELECT trade_date, avg(bar_return) AS market_bar_return
        FROM analysis_rows
        WHERE trade_seq >= 120 AND bad_cum = bad_cum_at_60_start AND NOT is_st
          AND amount_median_20 >= 10000000.0
        GROUP BY trade_date
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE market_features AS
        SELECT trade_date,
               exp(sum(ln(1.0 + market_bar_return)) OVER (
                   ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)) - 1.0
                   AS market_return_20,
               count(*) OVER (
                   ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)
                   AS market_window_n
        FROM market_daily
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE industry_daily AS
        SELECT trade_date, industry, avg(bar_return) AS industry_bar_return
        FROM analysis_rows
        WHERE trade_seq >= 120 AND bad_cum = bad_cum_at_60_start AND NOT is_st
          AND amount_median_20 >= 10000000.0
          AND industry IS NOT NULL AND trim(industry) <> ''
        GROUP BY trade_date, industry
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE industry_features AS
        SELECT trade_date, industry,
               exp(sum(ln(1.0 + industry_bar_return)) OVER (
                   PARTITION BY industry ORDER BY trade_date
                   ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)) - 1.0
                   AS industry_return_20,
               count(*) OVER (
                   PARTITION BY industry ORDER BY trade_date
                   ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS industry_window_n
        FROM industry_daily
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE axis_base AS
        SELECT o.*,
               -o.drawdown_60 AS depth_score,
               -o.return_10 / nullif(-o.drawdown_60, 0.0) AS crash_speed,
               o.return_20 - m.market_return_20 AS market_relative_20,
               o.return_20 - i.industry_return_20 AS industry_relative_20,
               -o.distance_from_low_60 AS near_low_score,
               m.market_return_20,
               i.industry_return_20
        FROM oversold_marked o
        JOIN market_features m USING (trade_date)
        JOIN industry_features i USING (trade_date, industry)
        WHERE o.a_flag AND o.entry_valid AND o.path_valid_20 AND o.close_h20 IS NOT NULL
          AND m.market_window_n = 20 AND i.industry_window_n = 20
          AND o.return_10 IS NOT NULL AND o.return_20 IS NOT NULL
          AND isfinite(o.return_10) AND isfinite(o.return_20)
          AND o.industry IS NOT NULL AND trim(o.industry) <> ''
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE axis_panel AS
        WITH labelled AS (
            SELECT * EXCLUDE (time_block, segment),
                   CASE WHEN drawdown_60 <= -0.40 THEN 'D4_EXTREME'
                        WHEN drawdown_60 <= -0.30 THEN 'D3_VERY_DEEP'
                        WHEN drawdown_60 <= -0.20 THEN 'D2_DEEP'
                        ELSE 'D1_MODERATE' END AS depth_bucket,
                   CASE WHEN trade_date < DATE '2021-01-01' THEN '2020'
                        WHEN trade_date < DATE '2024-01-01' THEN '2021-2023'
                        ELSE '2024-2026' END AS time_block,
                   CASE WHEN symbol LIKE '300%' THEN 'CHINEXT'
                        WHEN symbol LIKE '688%' THEN 'STAR'
                        WHEN symbol LIKE '8%' OR symbol LIKE '4%' THEN 'BSE'
                        ELSE 'MAIN' END AS segment,
                   ntile(3) OVER (PARTITION BY trade_date ORDER BY amount_median_20)
                       AS liquidity_tercile
            FROM axis_base
        )
        SELECT *,
               ntile(3) OVER (PARTITION BY depth_bucket ORDER BY crash_speed)
                   AS crash_tercile,
               ntile(3) OVER (PARTITION BY depth_bucket ORDER BY market_relative_20)
                   AS relative_tercile
        FROM labelled
        """
    )


def metric_sql(table: str, group: str, where: str = "true") -> str:
    return f"""
        SELECT {group}, count(*) AS n,
               avg(ret_5) AS mean_ret_5, median(ret_5) AS median_ret_5,
               avg((ret_5 > 0)::INTEGER) AS positive_rate_5,
               avg(ret_10) AS mean_ret_10, median(ret_10) AS median_ret_10,
               avg((ret_10 > 0)::INTEGER) AS positive_rate_10,
               avg(ret_20) AS mean_ret_20, median(ret_20) AS median_ret_20,
               avg((ret_20 > 0)::INTEGER) AS positive_rate_20,
               avg(mfe_20) AS mean_mfe_20, avg(mae_20) AS mean_mae_20,
               quantile_cont(ret_20, 0.9) AS p90_ret_20
        FROM {table} WHERE {where}
        GROUP BY {group} ORDER BY {group}
    """


def depth_curve(con: duckdb.DuckDBPyConnection, where: str = "true") -> list[dict[str, Any]]:
    return rows_as_dicts(
        con.execute(
            f"""
            WITH ranked AS (
                SELECT *, ntile(5) OVER (ORDER BY depth_score) AS depth_quintile
                FROM axis_panel WHERE {where}
            )
            SELECT depth_quintile, count(*) AS n,
                   min(drawdown_60) AS drawdown_min, max(drawdown_60) AS drawdown_max,
                   avg(ret_5) AS mean_ret_5, median(ret_5) AS median_ret_5,
                   avg((ret_5 > 0)::INTEGER) AS positive_rate_5,
                   avg(ret_10) AS mean_ret_10, median(ret_10) AS median_ret_10,
                   avg((ret_10 > 0)::INTEGER) AS positive_rate_10,
                   avg(ret_20) AS mean_ret_20, median(ret_20) AS median_ret_20,
                   avg((ret_20 > 0)::INTEGER) AS positive_rate_20,
                   avg(mfe_20) AS mean_mfe_20, avg(mae_20) AS mean_mae_20,
                   quantile_cont(ret_20, 0.9) AS p90_ret_20
            FROM ranked GROUP BY depth_quintile ORDER BY depth_quintile
            """
        )
    )


def economic_depth_regions(
    con: duckdb.DuckDBPyConnection, where: str = "true"
) -> list[dict[str, Any]]:
    return rows_as_dicts(con.execute(metric_sql("axis_panel", "depth_bucket", where)))


def matrix_metrics(
    con: duckdb.DuckDBPyConnection,
    axis: str,
    *,
    where: str = "true",
) -> list[dict[str, Any]]:
    if axis not in {"crash", "relative"}:
        raise ValueError(axis)
    column = f"{axis}_tercile"
    return rows_as_dicts(
        con.execute(
            f"""
            SELECT depth_bucket, {column}, count(*) AS n,
                   avg(ret_5) AS mean_ret_5, avg(ret_10) AS mean_ret_10,
                   avg(ret_20) AS mean_ret_20, median(ret_20) AS median_ret_20,
                   avg((ret_20 > 0)::INTEGER) AS positive_rate_20,
                   avg(mfe_20) AS mean_mfe_20, avg(mae_20) AS mean_mae_20
            FROM axis_panel WHERE {where}
            GROUP BY depth_bucket, {column}
            ORDER BY depth_bucket, {column}
            """
        )
    )


def three_axis(con: duckdb.DuckDBPyConnection, where: str = "true") -> list[dict[str, Any]]:
    return rows_as_dicts(
        con.execute(
            f"""
            WITH deep AS (
                SELECT *,
                       CASE WHEN crash_tercile = 3 THEN 'FAST'
                            WHEN crash_tercile = 1 THEN 'SLOW' END AS crash_group,
                       CASE WHEN relative_tercile = 3 THEN 'SYSTEMATIC'
                            WHEN relative_tercile = 1 THEN 'IDIOSYNCRATIC' END AS relative_group
                FROM axis_panel
                WHERE depth_score >= (SELECT median(depth_score) FROM axis_panel)
                  AND crash_tercile IN (1, 3) AND relative_tercile IN (1, 3)
                  AND {where}
            )
            SELECT crash_group, relative_group, count(*) AS n,
                   avg(ret_5) AS mean_ret_5, avg(ret_10) AS mean_ret_10,
                   avg(ret_20) AS mean_ret_20, median(ret_20) AS median_ret_20,
                   avg((ret_20 > 0)::INTEGER) AS positive_rate_20,
                   avg(mfe_20) AS mean_mfe_20, avg(mae_20) AS mean_mae_20,
                   quantile_cont(ret_20, 0.9) AS p90_ret_20
            FROM deep GROUP BY crash_group, relative_group
            ORDER BY crash_group, relative_group
            """
        )
    )


FEATURES = {
    "depth": "depth_score",
    "crash_speed": "crash_speed",
    "market_systematic": "market_relative_20",
    "industry_systematic": "industry_relative_20",
    "near_low": "near_low_score",
}


def daily_cross_section(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for name, expression in FEATURES.items():
        for horizon in (5, 10, 20):
            output.extend(
                rows_as_dicts(
                    con.execute(
                        f"""
                        WITH ranked AS (
                            SELECT trade_date,
                                   rank() OVER (PARTITION BY trade_date ORDER BY {expression}) AS feature_rank,
                                   rank() OVER (PARTITION BY trade_date ORDER BY ret_{horizon}) AS outcome_rank,
                                   count(*) OVER (PARTITION BY trade_date) AS day_n
                            FROM axis_panel
                            WHERE {expression} IS NOT NULL AND isfinite({expression})
                        ), daily AS (
                            SELECT trade_date, corr(feature_rank, outcome_rank) AS rho
                            FROM ranked WHERE day_n >= 10 GROUP BY trade_date
                        )
                        SELECT '{name}' AS variable, {horizon} AS horizon,
                               count(*) AS days, avg(rho) AS mean_rho,
                               median(rho) AS median_rho,
                               avg((rho > 0)::INTEGER) AS expected_sign_fraction
                        FROM daily WHERE rho IS NOT NULL AND isfinite(rho)
                        """
                    )
                )
            )
    return output


def incremental_spread(
    con: duckdb.DuckDBPyConnection,
    name: str,
    expression: str,
    *,
    where: str = "true",
) -> dict[str, Any]:
    return rows_as_dicts(
        con.execute(
            f"""
            WITH sized AS (
                SELECT *, count(*) OVER (PARTITION BY trade_date, depth_bucket) AS cell_n
                FROM axis_panel WHERE {where} AND {expression} IS NOT NULL AND isfinite({expression})
            ), ranked AS (
                SELECT *, ntile(3) OVER (
                    PARTITION BY trade_date, depth_bucket ORDER BY {expression}
                ) AS score_tercile
                FROM sized WHERE cell_n >= 9
            ), cells AS (
                SELECT trade_date, depth_bucket,
                       avg(ret_5) FILTER (WHERE score_tercile = 3) - avg(ret_5) FILTER (WHERE score_tercile = 1) AS spread_ret_5,
                       avg(ret_10) FILTER (WHERE score_tercile = 3) - avg(ret_10) FILTER (WHERE score_tercile = 1) AS spread_ret_10,
                       avg(ret_20) FILTER (WHERE score_tercile = 3) - avg(ret_20) FILTER (WHERE score_tercile = 1) AS spread_ret_20,
                       median(ret_20) FILTER (WHERE score_tercile = 3) - median(ret_20) FILTER (WHERE score_tercile = 1) AS spread_median_ret_20,
                       avg((ret_20 > 0)::INTEGER) FILTER (WHERE score_tercile = 3) - avg((ret_20 > 0)::INTEGER) FILTER (WHERE score_tercile = 1) AS spread_hit_rate_20,
                       count(DISTINCT score_tercile) AS terciles
                FROM ranked GROUP BY trade_date, depth_bucket
            )
            SELECT '{name}' AS variable,
                   count(*) FILTER (WHERE terciles = 3) AS cells,
                   avg(spread_ret_5) FILTER (WHERE terciles = 3) AS spread_ret_5,
                   avg(spread_ret_10) FILTER (WHERE terciles = 3) AS spread_ret_10,
                   avg(spread_ret_20) FILTER (WHERE terciles = 3) AS spread_ret_20,
                   avg(spread_median_ret_20) FILTER (WHERE terciles = 3) AS spread_median_ret_20,
                   avg(spread_hit_rate_20) FILTER (WHERE terciles = 3) AS spread_hit_rate_20
            FROM cells
            """
        )
    )[0]


def incrementality(con: duckdb.DuckDBPyConnection, where: str = "true") -> list[dict[str, Any]]:
    return [
        incremental_spread(con, "crash_speed", "crash_speed", where=where),
        incremental_spread(con, "market_systematic", "market_relative_20", where=where),
        incremental_spread(con, "industry_systematic", "industry_relative_20", where=where),
        incremental_spread(con, "near_low", "near_low_score", where=where),
    ]


def distance_curve(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    return rows_as_dicts(
        con.execute(
            """
            WITH ranked AS (
                SELECT *, ntile(5) OVER (ORDER BY distance_from_low_60) AS quintile
                FROM axis_panel
            )
            SELECT quintile, count(*) AS n,
                   min(distance_from_low_60) AS distance_min,
                   max(distance_from_low_60) AS distance_max,
                   avg(ret_20) AS mean_ret_20, median(ret_20) AS median_ret_20,
                   avg((ret_20 > 0)::INTEGER) AS positive_rate_20,
                   avg(mfe_20) AS mean_mfe_20, avg(mae_20) AS mean_mae_20
            FROM ranked GROUP BY quintile ORDER BY quintile
            """
        )
    )


def time_stability(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    return rows_as_dicts(
        con.execute(
            """
            WITH depth_rank AS (
                SELECT *, ntile(3) OVER (PARTITION BY time_block ORDER BY depth_score) AS depth_tercile
                FROM axis_panel
            ), pooled AS (
                SELECT time_block,
                       avg(ret_20) FILTER (WHERE depth_tercile = 3) - avg(ret_20) FILTER (WHERE depth_tercile = 1) AS deep_minus_shallow_ret_20
                FROM depth_rank GROUP BY time_block
            ), cells AS (
                SELECT time_block, depth_bucket,
                       avg(ret_20) FILTER (WHERE crash_tercile = 3) - avg(ret_20) FILTER (WHERE crash_tercile = 1) AS fast_minus_slow_ret_20,
                       avg(ret_20) FILTER (WHERE relative_tercile = 3) - avg(ret_20) FILTER (WHERE relative_tercile = 1) AS systematic_minus_idio_ret_20
                FROM axis_panel GROUP BY time_block, depth_bucket
            ), spreads AS (
                SELECT time_block, avg(fast_minus_slow_ret_20) AS fast_minus_slow_ret_20,
                       avg(systematic_minus_idio_ret_20) AS systematic_minus_idio_ret_20
                FROM cells GROUP BY time_block
            ), ranked AS (
                SELECT time_block, trade_date,
                       rank() OVER (PARTITION BY trade_date ORDER BY depth_score) AS depth_rank,
                       rank() OVER (PARTITION BY trade_date ORDER BY crash_speed) AS crash_rank,
                       rank() OVER (PARTITION BY trade_date ORDER BY market_relative_20) AS relative_rank,
                       rank() OVER (PARTITION BY trade_date ORDER BY ret_20) AS outcome_rank,
                       count(*) OVER (PARTITION BY trade_date) AS day_n
                FROM axis_panel
            ), daily AS (
                SELECT time_block, trade_date, corr(depth_rank, outcome_rank) AS depth_rho,
                       corr(crash_rank, outcome_rank) AS crash_rho,
                       corr(relative_rank, outcome_rank) AS relative_rho
                FROM ranked WHERE day_n >= 10 GROUP BY time_block, trade_date
            ), rho AS (
                SELECT time_block, count(*) AS days,
                       avg(depth_rho) AS mean_depth_rho_ret_20,
                       avg(crash_rho) AS mean_crash_rho_ret_20,
                       avg(relative_rho) AS mean_relative_rho_ret_20
                FROM daily GROUP BY time_block
            )
            SELECT p.time_block, p.deep_minus_shallow_ret_20,
                   s.fast_minus_slow_ret_20, s.systematic_minus_idio_ret_20,
                   r.days, r.mean_depth_rho_ret_20, r.mean_crash_rho_ret_20,
                   r.mean_relative_rho_ret_20
            FROM pooled p JOIN spreads s USING (time_block) JOIN rho r USING (time_block)
            ORDER BY p.time_block
            """
        )
    )


def liquidity_check(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    return rows_as_dicts(
        con.execute(
            """
            SELECT liquidity_tercile, count(*) AS n,
                   avg(ret_20) FILTER (WHERE crash_tercile = 3) - avg(ret_20) FILTER (WHERE crash_tercile = 1) AS fast_minus_slow_ret_20,
                   avg(ret_20) FILTER (WHERE relative_tercile = 3) - avg(ret_20) FILTER (WHERE relative_tercile = 1) AS systematic_minus_idio_ret_20
            FROM axis_panel GROUP BY liquidity_tercile ORDER BY liquidity_tercile
            """
        )
    )


def industry_neutral_check(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for name, expression in {
        "depth": "depth_score",
        "crash_speed": "crash_speed",
        "market_systematic": "market_relative_20",
    }.items():
        output.extend(
            rows_as_dicts(
                con.execute(
                    f"""
                    WITH neutral AS (
                        SELECT *, {expression} - avg({expression}) OVER (
                            PARTITION BY trade_date, industry) AS neutral_feature
                        FROM axis_panel
                    ), ranked AS (
                        SELECT trade_date,
                               rank() OVER (PARTITION BY trade_date ORDER BY neutral_feature) AS feature_rank,
                               rank() OVER (PARTITION BY trade_date ORDER BY ret_20) AS outcome_rank,
                               count(*) OVER (PARTITION BY trade_date) AS day_n
                        FROM neutral
                    ), daily AS (
                        SELECT trade_date, corr(feature_rank, outcome_rank) AS rho
                        FROM ranked WHERE day_n >= 10 GROUP BY trade_date
                    )
                    SELECT '{name}' AS variable, count(*) AS days,
                           avg(rho) AS mean_rho_ret_20, median(rho) AS median_rho_ret_20,
                           avg((rho > 0)::INTEGER) AS expected_sign_fraction_ret_20
                    FROM daily WHERE rho IS NOT NULL AND isfinite(rho)
                    """
                )
            )
        )
    return output


def segment_check(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    return rows_as_dicts(
        con.execute(
            """
            SELECT segment, count(*) AS n, count(DISTINCT symbol) AS securities,
                   avg(ret_20) AS mean_ret_20, median(ret_20) AS median_ret_20,
                   avg((ret_20 > 0)::INTEGER) AS positive_rate_20,
                   avg(ret_20) FILTER (WHERE crash_tercile = 3) - avg(ret_20) FILTER (WHERE crash_tercile = 1) AS fast_minus_slow_ret_20,
                   avg(ret_20) FILTER (WHERE relative_tercile = 3) - avg(ret_20) FILTER (WHERE relative_tercile = 1) AS systematic_minus_idio_ret_20
            FROM axis_panel GROUP BY segment ORDER BY segment
            """
        )
    )


def profiles(con: duckdb.DuckDBPyConnection) -> tuple[dict[str, Any], dict[str, Any]]:
    data = rows_as_dicts(
        con.execute(
            """
            SELECT min(trade_date) AS first_date, max(trade_date) AS last_date,
                   count(*) AS rows, count(DISTINCT symbol) AS symbols,
                   sum(hard_valid::INTEGER) AS hard_valid_rows,
                   sum((available_at > decision_at)::INTEGER) AS time_travel_rows
            FROM raw_ordered
            """
        )
    )[0]
    sample = rows_as_dicts(
        con.execute(
            """
            SELECT count(*) AS observations, count(DISTINCT symbol) AS securities,
                   count(DISTINCT trade_date) AS signal_days,
                   min(trade_date) AS first_date, max(trade_date) AS last_date,
                   count(*) FILTER (WHERE dedup20_flag) AS dedup20_events,
                   count(DISTINCT industry) AS industries
            FROM axis_panel
            """
        )
    )[0]
    return data, sample


def semantic_checks(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    checks = rows_as_dicts(
        con.execute(
            """
            SELECT count(*) FILTER (WHERE available_at > decision_at) AS time_travel,
                   count(*) FILTER (WHERE raw_next_date <= trade_date) AS non_t_plus_one_entries,
                   count(*) FILTER (WHERE NOT a_flag) AS low_universe_inversion,
                   count(*) FILTER (WHERE bad_cum != bad_cum_at_60_start) AS invalid_history,
                   count(*) FILTER (WHERE depth_score != -drawdown_60) AS depth_orientation,
                   count(*) FILTER (WHERE abs(crash_speed - (-return_10 / -drawdown_60)) > 1e-12) AS crash_formula,
                   count(*) FILTER (WHERE crash_tercile NOT BETWEEN 1 AND 3) AS crash_bins,
                   count(*) FILTER (WHERE relative_tercile NOT BETWEEN 1 AND 3) AS relative_bins,
                   count(*) FILTER (WHERE market_return_20 IS NULL) AS missing_market,
                   count(*) FILTER (WHERE industry_return_20 IS NULL) AS missing_industry
            FROM axis_panel
            """
        )
    )[0]
    if any(value != 0 for value in checks.values()):
        raise RuntimeError(f"research invariants failed: {checks}")
    return checks


def run(
    output_dir: Path,
    *,
    hash_data_files: bool = True,
    symbol_filter: list[str] | None = None,
) -> dict[str, Any]:
    config = json.loads(PREDECESSOR_CONFIG.read_text())
    config["research_version"] = "oversold-reversal-ranking-v1"
    if symbol_filter:
        config.setdefault("runtime", {})["symbol_filter"] = symbol_filter
    identities = validate_inputs(config, hash_data_files=hash_data_files)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="oversold-ranking-v1-") as temp_dir:
        con = duckdb.connect()
        con.execute(f"SET threads={int(config['runtime']['threads'])}")
        con.execute(f"SET memory_limit='{config['runtime']['memory_limit']}'")
        con.execute(f"SET temp_directory='{temp_dir}'")
        con.execute("SET preserve_insertion_order=false")
        create_analysis_tables(con, config)
        create_axis_tables(con)
        checks = semantic_checks(con)
        data_profile, sample_profile = profiles(con)
        payload = {
            "research_version": config["research_version"],
            "input_identities": identities,
            "checks": checks,
            "data_profile": data_profile,
            "sample_profile": sample_profile,
            "definitions": {
                "low": "drawdown_60 <= -15%; adjusted close <=5% above causal 60-session adjusted intraday low; >=120 valid sessions; 20-session median amount >= CNY10m; hard-valid trading non-ST row with clean 60-session lineage",
                "depth_score": "-drawdown_60; larger is deeper",
                "crash_speed": "-causal adjusted Ret10 / -drawdown_60; larger means more of the current 60-session peak drawdown was accumulated recently",
                "market_relative_20": "causal stock Ret20 minus compounded 20-session return of the equal-weight eligible market; larger means less stock-specific underperformance / more systematic decline",
                "industry_relative_20": "causal stock Ret20 minus compounded 20-session return of its PIT-industry equal-weight eligible universe",
                "near_low_score": "-distance_from_low_60; larger means closer to the causal 60-session low",
                "outcomes": "gross adjusted returns from next legal session open through adjusted close at 5/10/20 sessions; full hard-valid 20-session path required",
                "deduplication": "first LOW observation after no LOW in the previous 20 trading rows",
                "primary_depth_buckets": "D1 (-20%,-15%], D2 (-30%,-20%], D3 (-40%,-30%], D4 <=-40%",
                "axis_terciles": "pooled Slow/Medium/Fast or Idiosyncratic/Mixed/Systematic terciles formed separately within each primary depth bucket",
            },
            "depth_curve": depth_curve(con),
            "dedup20_depth_curve": depth_curve(con, "dedup20_flag"),
            "economic_depth_regions": economic_depth_regions(con),
            "dedup20_economic_depth_regions": economic_depth_regions(con, "dedup20_flag"),
            "drawdown_x_crash_speed": matrix_metrics(con, "crash"),
            "dedup20_drawdown_x_crash_speed": matrix_metrics(con, "crash", where="dedup20_flag"),
            "drawdown_x_relative_decline": matrix_metrics(con, "relative"),
            "dedup20_drawdown_x_relative_decline": matrix_metrics(con, "relative", where="dedup20_flag"),
            "three_axis_interaction": three_axis(con),
            "dedup20_three_axis_interaction": three_axis(con, "dedup20_flag"),
            "daily_cross_section": daily_cross_section(con),
            "incrementality": incrementality(con),
            "dedup20_incrementality": incrementality(con, "dedup20_flag"),
            "distance_to_low_curve": distance_curve(con),
            "time_stability": time_stability(con),
            "liquidity_check": liquidity_check(con),
            "industry_neutral_check": industry_neutral_check(con),
            "segment_check": segment_check(con),
        }
        con.close()
    (output_dir / "results.json").write_text(
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
