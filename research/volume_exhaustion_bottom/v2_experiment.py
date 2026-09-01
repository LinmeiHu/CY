#!/usr/bin/env python3
"""V2 falsification: continuous dry-up incrementality inside the frozen V1 LOW universe."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from research.volume_exhaustion_bottom.experiment import (  # noqa: E402
    DEFAULT_CONFIG,
    create_analysis_tables,
    json_default,
    validate_inputs,
)

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "reports"


def rows_as_dicts(cursor: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def make_v2_tables(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TEMP TABLE v2_marked AS
        SELECT *,
               (a_flag AND NOT coalesce(bool_or(a_flag) OVER (
                   PARTITION BY symbol ORDER BY trade_date
                   ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING), false)) AS dedup20_flag
        FROM analysis_rows
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE v2_low0 AS
        SELECT *,
               -ln(dryup_ratio) AS dryness,
               CASE WHEN drawdown_60 <= -0.30 THEN 1
                    WHEN drawdown_60 <= -0.20 THEN 2 ELSE 3 END AS drawdown_bucket,
               CASE WHEN distance_from_low_60 <= 0.01 THEN 1
                    WHEN distance_from_low_60 <= 0.03 THEN 2 ELSE 3 END AS low_distance_bucket,
        FROM v2_marked
        WHERE a_flag AND entry_valid AND path_valid_20 AND close_h20 IS NOT NULL
          AND dryup_ratio > 0 AND isfinite(dryup_ratio)
          AND industry IS NOT NULL AND trim(industry) <> ''
          AND return_20 IS NOT NULL AND volatility_20 IS NOT NULL
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE v2_low AS
        WITH liquidity AS (
            SELECT *, ntile(3) OVER (
                PARTITION BY trade_date ORDER BY amount_median_20
            ) AS liquidity_bucket
            FROM v2_low0
        )
        SELECT *,
               ntile(3) OVER (PARTITION BY trade_date ORDER BY return_20) AS return_bucket,
               ntile(3) OVER (
                   PARTITION BY trade_date ORDER BY volatility_20
               ) AS volatility_bucket
        FROM liquidity
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE v2_matched AS
        WITH sized AS (
            SELECT *, count(*) OVER (
                PARTITION BY trade_date, drawdown_bucket,
                             low_distance_bucket, liquidity_bucket
            ) AS cell_n
            FROM v2_low
        )
        SELECT *, ntile(5) OVER (
            PARTITION BY trade_date, drawdown_bucket,
                         low_distance_bucket, liquidity_bucket
            ORDER BY dryup_ratio
        ) AS dry_quintile
        FROM sized
        WHERE cell_n >= 10
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE v2_daily_rho AS
        WITH ranked AS (
            SELECT *, rank() OVER (
                PARTITION BY trade_date ORDER BY dryness
            ) AS dryness_rank
            FROM v2_low
        )
        SELECT trade_date, count(*) AS n,
               corr(dryness_rank, ret_5) AS rho_ret_5,
               corr(dryness_rank, ret_10) AS rho_ret_10,
               corr(dryness_rank, ret_20) AS rho_ret_20
        FROM ranked
        GROUP BY trade_date
        HAVING count(*) >= 10
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE v2_industry_rho AS
        WITH neutral AS (
            SELECT *,
                   dryness - avg(dryness) OVER (
                       PARTITION BY trade_date, industry
                   ) AS industry_neutral_dryness
            FROM v2_low
        ), ranked AS (
            SELECT *, rank() OVER (
                PARTITION BY trade_date ORDER BY industry_neutral_dryness
            ) AS neutral_rank
            FROM neutral
        )
        SELECT trade_date, count(*) AS n,
               corr(neutral_rank, ret_20) AS rho_ret_20
        FROM ranked
        GROUP BY trade_date
        HAVING count(*) >= 10
        """
    )


def quintile_metrics(
    con: duckdb.DuckDBPyConnection, table: str = "v2_matched", where: str = "true"
) -> list[dict[str, Any]]:
    return rows_as_dicts(
        con.execute(
            f"""
            SELECT dry_quintile AS quintile, count(*) AS n,
                   avg(ret_5) AS mean_ret_5, avg(ret_10) AS mean_ret_10,
                   avg(ret_20) AS mean_ret_20, median(ret_20) AS median_ret_20,
                   avg((ret_20 > 0)::INTEGER) AS positive_rate_20,
                   avg(mfe_20) AS mean_mfe_20, avg(mae_20) AS mean_mae_20,
                   count(DISTINCT trade_date) AS days
            FROM {table}
            WHERE {where}
            GROUP BY dry_quintile ORDER BY dry_quintile
            """
        )
    )


def cell_spread(con: duckdb.DuckDBPyConnection, where: str = "true") -> dict[str, Any]:
    rows = rows_as_dicts(
        con.execute(
            f"""
            WITH cells AS (
                SELECT trade_date, drawdown_bucket, low_distance_bucket, liquidity_bucket,
                       avg(ret_5) FILTER (WHERE dry_quintile = 5) AS q5_ret_5,
                       avg(ret_5) FILTER (WHERE dry_quintile = 1) AS q1_ret_5,
                       avg(ret_10) FILTER (WHERE dry_quintile = 5) AS q5_ret_10,
                       avg(ret_10) FILTER (WHERE dry_quintile = 1) AS q1_ret_10,
                       avg(ret_20) FILTER (WHERE dry_quintile = 5) AS q5_ret_20,
                       avg(ret_20) FILTER (WHERE dry_quintile = 1) AS q1_ret_20,
                       median(ret_20) FILTER (WHERE dry_quintile = 5) AS q5_med_ret_20,
                       median(ret_20) FILTER (WHERE dry_quintile = 1) AS q1_med_ret_20,
                       avg((ret_20 > 0)::INTEGER) FILTER (WHERE dry_quintile = 5)
                           AS q5_hit_20,
                       avg((ret_20 > 0)::INTEGER) FILTER (WHERE dry_quintile = 1)
                           AS q1_hit_20,
                       avg(mfe_20) FILTER (WHERE dry_quintile = 5) AS q5_mfe_20,
                       avg(mfe_20) FILTER (WHERE dry_quintile = 1) AS q1_mfe_20,
                       avg(mae_20) FILTER (WHERE dry_quintile = 5) AS q5_mae_20,
                       avg(mae_20) FILTER (WHERE dry_quintile = 1) AS q1_mae_20,
                       count(DISTINCT dry_quintile) AS q_count
                FROM v2_matched
                WHERE {where}
                GROUP BY trade_date, drawdown_bucket, low_distance_bucket, liquidity_bucket
            )
            SELECT count(*) FILTER (WHERE q_count = 5) AS cells,
                   avg(q5_ret_5 - q1_ret_5) FILTER (WHERE q_count = 5) AS spread_ret_5,
                   avg(q5_ret_10 - q1_ret_10) FILTER (WHERE q_count = 5) AS spread_ret_10,
                   avg(q5_ret_20 - q1_ret_20) FILTER (WHERE q_count = 5) AS spread_ret_20,
                   median(q5_ret_20 - q1_ret_20) FILTER (WHERE q_count = 5)
                       AS median_spread_ret_20,
                   avg(q5_med_ret_20 - q1_med_ret_20) FILTER (WHERE q_count = 5)
                       AS spread_median_ret_20,
                   avg(q5_hit_20 - q1_hit_20) FILTER (WHERE q_count = 5)
                       AS spread_hit_rate_20,
                   avg(q5_mfe_20 - q1_mfe_20) FILTER (WHERE q_count = 5) AS spread_mfe_20,
                   avg(q5_mae_20 - q1_mae_20) FILTER (WHERE q_count = 5) AS spread_mae_20
            FROM cells
            """
        )
    )
    return rows[0]


def daily_rho_summary(
    con: duckdb.DuckDBPyConnection, table: str = "v2_daily_rho"
) -> dict[str, Any]:
    rows = rows_as_dicts(
        con.execute(
            f"""
            SELECT count(*) AS days,
                   avg(rho_ret_5) AS mean_rho_ret_5, median(rho_ret_5) AS median_rho_ret_5,
                   avg((rho_ret_5 > 0)::INTEGER) AS positive_day_fraction_ret_5,
                   avg(rho_ret_10) AS mean_rho_ret_10, median(rho_ret_10) AS median_rho_ret_10,
                   avg((rho_ret_10 > 0)::INTEGER) AS positive_day_fraction_ret_10,
                   avg(rho_ret_20) AS mean_rho_ret_20, median(rho_ret_20) AS median_rho_ret_20,
                   avg((rho_ret_20 > 0)::INTEGER) AS positive_day_fraction_ret_20
            FROM {table}
            """
        )
    )
    return rows[0]


def time_blocks(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    return rows_as_dicts(
        con.execute(
            """
            WITH spreads AS (
                SELECT *,
                       CASE WHEN trade_date < DATE '2023-01-01' THEN '2020-2022'
                            WHEN trade_date < DATE '2025-01-01' THEN '2023-2024'
                            ELSE '2025-2026' END AS time_block
                FROM v2_matched
            ), cells AS (
                SELECT time_block, trade_date, drawdown_bucket, low_distance_bucket,
                       liquidity_bucket,
                       avg(ret_20) FILTER (WHERE dry_quintile = 5) AS q5,
                       avg(ret_20) FILTER (WHERE dry_quintile = 1) AS q1,
                       count(DISTINCT dry_quintile) AS q_count
                FROM spreads
                GROUP BY time_block, trade_date, drawdown_bucket,
                         low_distance_bucket, liquidity_bucket
            ), daily AS (
                SELECT CASE WHEN trade_date < DATE '2023-01-01' THEN '2020-2022'
                            WHEN trade_date < DATE '2025-01-01' THEN '2023-2024'
                            ELSE '2025-2026' END AS time_block,
                       avg(rho_ret_20) AS mean_rho_ret_20,
                       median(rho_ret_20) AS median_rho_ret_20,
                       avg((rho_ret_20 > 0)::INTEGER) AS positive_day_fraction_ret_20
                FROM v2_daily_rho GROUP BY 1
            )
            SELECT c.time_block, count(*) FILTER (WHERE c.q_count = 5) AS cells,
                   avg(c.q5 - c.q1) FILTER (WHERE c.q_count = 5) AS spread_ret_20,
                   d.mean_rho_ret_20, d.median_rho_ret_20,
                   d.positive_day_fraction_ret_20
            FROM cells c JOIN daily d USING (time_block)
            GROUP BY c.time_block, d.mean_rho_ret_20, d.median_rho_ret_20,
                     d.positive_day_fraction_ret_20
            ORDER BY c.time_block
            """
        )
    )


def liquidity_control(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    return rows_as_dicts(
        con.execute(
            """
            SELECT liquidity_bucket, count(*) AS n,
                   avg(ret_20) FILTER (WHERE dry_quintile = 5)
                       - avg(ret_20) FILTER (WHERE dry_quintile = 1) AS spread_ret_20,
                   avg((ret_20 > 0)::INTEGER) FILTER (WHERE dry_quintile = 5)
                       - avg((ret_20 > 0)::INTEGER) FILTER (WHERE dry_quintile = 1)
                       AS spread_hit_rate_20
            FROM v2_matched
            GROUP BY liquidity_bucket ORDER BY liquidity_bucket
            """
        )
    )


def industry_summary(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    result = rows_as_dicts(
        con.execute(
            """
            SELECT count(*) AS days, avg(rho_ret_20) AS mean_rho_ret_20,
                   median(rho_ret_20) AS median_rho_ret_20,
                   avg((rho_ret_20 > 0)::INTEGER) AS positive_day_fraction_ret_20
            FROM v2_industry_rho
            """
        )
    )[0]
    matched = rows_as_dicts(
        con.execute(
            """
            WITH ranked AS (
                SELECT *,
                       dryness - avg(dryness) OVER (
                           PARTITION BY trade_date, industry
                       ) AS neutral_dryness
                FROM v2_matched
            ), q AS (
                SELECT *, ntile(5) OVER (
                    PARTITION BY trade_date, drawdown_bucket,
                                 low_distance_bucket, liquidity_bucket
                    ORDER BY neutral_dryness
                ) AS neutral_quintile
                FROM ranked
            )
            SELECT avg(ret_20) FILTER (WHERE neutral_quintile = 5)
                       - avg(ret_20) FILTER (WHERE neutral_quintile = 1) AS spread_ret_20,
                   avg((ret_20 > 0)::INTEGER) FILTER (WHERE neutral_quintile = 5)
                       - avg((ret_20 > 0)::INTEGER) FILTER (WHERE neutral_quintile = 1)
                       AS spread_hit_rate_20
            FROM q
            """
        )
    )[0]
    return {
        **result,
        "matched_spread_ret_20": matched["spread_ret_20"],
        "matched_spread_hit_rate_20": matched["spread_hit_rate_20"],
    }


def residualized(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    con.execute(
        """
        CREATE TEMP TABLE v2_residual AS
        WITH grouped AS (
            SELECT *, count(*) OVER (
                PARTITION BY trade_date, industry, drawdown_bucket,
                             low_distance_bucket, liquidity_bucket,
                             return_bucket, volatility_bucket
            ) AS group_n,
            dryness - avg(dryness) OVER (
                PARTITION BY trade_date, industry, drawdown_bucket,
                             low_distance_bucket, liquidity_bucket,
                             return_bucket, volatility_bucket
            ) AS residual_dryness
            FROM v2_low
        )
        SELECT * FROM grouped
        WHERE group_n >= 5 AND residual_dryness IS NOT NULL
        """
    )
    stats = rows_as_dicts(
        con.execute(
            """
            SELECT count(*) AS n, count(DISTINCT trade_date) AS dates,
                   count(DISTINCT industry) AS industries,
                   regr_slope(ret_20, residual_dryness)
                       AS slope_ret20_on_residual_dryness,
                   corr(residual_dryness, ret_20)
                       AS correlation_residual_dryness_ret20
            FROM v2_residual
            """
        )
    )[0]
    quintiles = rows_as_dicts(
        con.execute(
            """
            WITH ranked AS (
                SELECT *, ntile(5) OVER (ORDER BY residual_dryness) AS quintile
                FROM v2_residual
            )
            SELECT quintile, count(*) AS n,
                   avg(ret_5) AS mean_ret_5, avg(ret_10) AS mean_ret_10,
                   avg(ret_20) AS mean_ret_20, median(ret_20) AS median_ret_20,
                   avg((ret_20 > 0)::INTEGER) AS positive_rate_20,
                   avg(mfe_20) AS mean_mfe_20, avg(mae_20) AS mean_mae_20
            FROM ranked GROUP BY quintile ORDER BY quintile
            """
        )
    )
    return {**stats, "quintiles": quintiles}


def run(output_dir: Path) -> None:
    config = json.loads(DEFAULT_CONFIG.read_text())
    identities = validate_inputs(config, hash_data_files=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='8GB'")
    create_analysis_tables(con, config)
    make_v2_tables(con)
    checks = rows_as_dicts(
        con.execute(
            """
            SELECT count(*) FILTER (WHERE available_at > decision_at) AS time_travel,
                   count(*) FILTER (WHERE entry_valid AND raw_next_date <= trade_date)
                       AS non_t_plus_one_entries,
                   count(*) FILTER (WHERE NOT a_flag) AS low_universe_inversion
            FROM v2_low
            """
        )
    )[0]
    if any(value != 0 for value in checks.values()):
        raise RuntimeError(f"V2 chronology checks failed: {checks}")
    all_quintiles = quintile_metrics(con)
    dedup_quintiles = quintile_metrics(con, where="dedup20_flag")
    matched_spread = cell_spread(con)
    dedup_spread = cell_spread(con, where="dedup20_flag")
    daily = daily_rho_summary(con)
    times = time_blocks(con)
    liquidity = liquidity_control(con)
    industry = industry_summary(con)
    residual = residualized(con)
    sample = rows_as_dicts(
        con.execute(
            """
            SELECT count(*) AS low_observations, count(DISTINCT symbol) AS securities,
                   min(trade_date) AS first_date, max(trade_date) AS last_date,
                   count(*) FILTER (WHERE dedup20_flag) AS dedup_events,
                   count(DISTINCT trade_date) AS signal_days
            FROM v2_low
            """
        )
    )[0]
    matched_sample = rows_as_dicts(
        con.execute(
            """
            SELECT count(*) AS matched_observations,
                   count(DISTINCT trade_date) AS matched_days
            FROM v2_matched
            """
        )
    )[0]
    sample.update(matched_sample)
    con.close()
    payload = {
        "input_identities": identities,
        "checks": checks,
        "sample": sample,
        "primary_matching_design": {
            "dimensions": [
                "trade_date",
                "drawdown_bucket",
                "low_distance_bucket",
                "liquidity_bucket",
            ],
            "drawdown_buckets": "<= -30%, (-30%, -20%], (-20%, -15%]",
            "low_distance_buckets": "<=1%, (1%,3%], (3%,5%]",
            "liquidity": "date-relative terciles of 20-session median amount",
            "minimum_cell_size": 10,
            "within_cell_quintiles": "Q1 most active through Q5 driest",
            "industry": "separate PIT-industry demean/rank sanity check",
        },
        "all_low_quintiles": all_quintiles,
        "dedup20_quintiles": dedup_quintiles,
        "matched_cell_spread": matched_spread,
        "dedup20_matched_cell_spread": dedup_spread,
        "daily_cross_section": daily,
        "time_blocks": times,
        "liquidity_control": liquidity,
        "industry_control": industry,
        "residualized": residual,
    }
    (output_dir / "v2_results.json").write_text(
        json.dumps(payload, indent=2, default=json_default) + "\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    run(args.output)


if __name__ == "__main__":
    main()
