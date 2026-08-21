"""Measure frozen PIT-B daily runtime reads without running a backtest."""

from __future__ import annotations

import argparse
import statistics
import time
from datetime import date, datetime
from datetime import time as wall_time
from pathlib import Path

import duckdb


def _timed_days(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
    dates: list[date],
) -> list[float]:
    samples: list[float] = []
    for trade_date in dates:
        started = time.perf_counter()
        connection.execute(
            sql,
            [trade_date, datetime.combine(trade_date, wall_time(15, 30))],
        ).fetchall()
        samples.append(time.perf_counter() - started)
    return samples


def _timed_month_cache(
    connection: duckdb.DuckDBPyConnection,
    dates: list[date],
) -> tuple[float, list[float]]:
    load_seconds = 0.0
    samples: list[float] = []
    current_month: tuple[int, int] | None = None
    for trade_date in dates:
        month = (trade_date.year, trade_date.month)
        if month != current_month:
            month_start = trade_date.replace(day=1)
            month_end = (
                date(trade_date.year + 1, 1, 1)
                if trade_date.month == 12
                else date(trade_date.year, trade_date.month + 1, 1)
            )
            started = time.perf_counter()
            connection.execute(
                """
                CREATE OR REPLACE TEMP TABLE minute_month AS
                SELECT symbol, trade_date, chip_prices, chip_volumes, available_at
                FROM minute
                WHERE trade_date >= ? AND trade_date < ? AND hard_valid = TRUE
                """,
                [month_start, month_end],
            )
            load_seconds += time.perf_counter() - started
            current_month = month
        started = time.perf_counter()
        connection.execute(
            """
            SELECT symbol, chip_prices, chip_volumes FROM minute_month
            WHERE trade_date = ? AND available_at <= ?
            QUALIFY ROW_NUMBER() OVER (
              PARTITION BY symbol, trade_date ORDER BY available_at DESC
            ) = 1
            """,
            [trade_date, datetime.combine(trade_date, wall_time(15, 30))],
        ).fetchall()
        samples.append(time.perf_counter() - started)
    return load_seconds, samples


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=50)
    parser.add_argument("--year", type=int, default=2024)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    daily = sorted((root / "data/processed/pit_b_daily_2018_2026_v2").rglob("*.parquet"))
    minute = sorted(
        (root / "data/processed/pit_b_minute_2018_2026_v2/daily").rglob("*.parquet")
    )
    if not daily or not minute:
        raise SystemExit("frozen PIT-B daily or minute files are missing")

    connection = duckdb.connect(":memory:")
    connection.read_parquet([str(path) for path in daily]).create_view("daily")
    connection.read_parquet([str(path) for path in minute]).create_view("minute")
    dates = [
        row[0]
        for row in connection.execute(
            """
            SELECT DISTINCT trade_date FROM daily
            WHERE YEAR(trade_date) = ? ORDER BY trade_date LIMIT ?
            """,
            [args.year, args.days],
        ).fetchall()
    ]
    daily_samples = _timed_days(
        connection,
        """
        SELECT symbol, close, hard_valid, corporate_action_count
        FROM daily WHERE trade_date = ? AND available_at <= ?
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY symbol ORDER BY available_at DESC
        ) = 1
        """,
        dates,
    )
    minute_samples = _timed_days(
        connection,
        """
        SELECT symbol, chip_prices, chip_volumes
        FROM minute
        WHERE trade_date = ? AND available_at <= ? AND hard_valid = TRUE
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY symbol, trade_date ORDER BY available_at DESC
        ) = 1
        """,
        dates,
    )
    month_load, cached_samples = _timed_month_cache(connection, dates)
    average = (sum(daily_samples) + sum(minute_samples)) / len(dates)
    cached_average = (sum(daily_samples) + month_load + sum(cached_samples)) / len(dates)
    print(
        {
            "days": len(dates),
            "daily_total_s": round(sum(daily_samples), 3),
            "daily_median_ms": round(statistics.median(daily_samples) * 1_000, 2),
            "minute_total_s": round(sum(minute_samples), 3),
            "minute_median_ms": round(statistics.median(minute_samples) * 1_000, 2),
            "projected_2200_days_io_s": round(average * 2_200, 1),
            "month_cache_load_s": round(month_load, 3),
            "cached_minute_total_s": round(month_load + sum(cached_samples), 3),
            "cached_minute_median_ms": round(
                statistics.median(cached_samples) * 1_000, 2
            ),
            "cached_projected_2200_days_io_s": round(cached_average * 2_200, 1),
            "measured_speedup": round(
                sum(minute_samples) / (month_load + sum(cached_samples)), 2
            ),
        }
    )


if __name__ == "__main__":
    main()
