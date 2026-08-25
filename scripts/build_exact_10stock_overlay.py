#!/usr/bin/env python3
"""Build a small exact feature overlay for the ten-stock diagnostic."""

from __future__ import annotations

import argparse
import hashlib
import shutil
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import duckdb
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from cyq_game.strategy.exact_chip_features import build_exact_ensemble_features


def _sql_paths(paths: list[Path]) -> str:
    return "[" + ",".join("'" + str(path).replace("'", "''") + "'" for path in paths) + "]"


def _build_symbol_exact(
    task: tuple[Path, str, dict[date, float], date, date, Path],
) -> tuple[str, int, bool]:
    root, symbol, closes, start_date, end_date, output_path = task
    if output_path.is_file() and "feature_source" in (
        pq.ParquetFile(output_path).schema_arrow.names
    ):
        return symbol, pq.ParquetFile(output_path).metadata.num_rows, True
    output_path.unlink(missing_ok=True)
    rows = build_exact_ensemble_features(
        root,
        symbol,
        closes,
        start_date,
        end_date,
    )
    if not rows:
        raise RuntimeError(f"no exact feature rows for {symbol}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(".tmp.parquet")
    temp_path.unlink(missing_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), temp_path, compression="zstd")
    temp_path.replace(output_path)
    return symbol, len(rows), False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--symbols", nargs="+")
    parser.add_argument("--symbols-file", type=Path)
    parser.add_argument("--primary-root", type=Path, required=True)
    parser.add_argument("--secondary-root", type=Path, required=True)
    parser.add_argument("--exact-start", type=date.fromisoformat, default=date(2020, 1, 1))
    parser.add_argument("--exact-end", type=date.fromisoformat, default=date(2023, 12, 31))
    parser.add_argument("--feature-start-year", type=int, default=2018)
    parser.add_argument("--feature-end-year", type=int, default=2023)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument(
        "--symbol-root",
        action="append",
        default=[],
        metavar="SYMBOL=PATH",
        help="Override one symbol's exact inventory root",
    )
    args = parser.parse_args()
    if bool(args.symbols) == bool(args.symbols_file):
        parser.error("provide exactly one of --symbols or --symbols-file")
    symbols = tuple(
        args.symbols
        or (
            line.strip()
            for line in args.symbols_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    )
    if not symbols or len(set(symbols)) != len(symbols):
        parser.error("symbols must be non-empty and unique")
    if args.exact_end < args.exact_start:
        parser.error("--exact-end must not precede --exact-start")
    if args.feature_end_year < args.feature_start_year:
        parser.error("--feature-end-year must not precede --feature-start-year")
    if args.workers < 1:
        parser.error("--workers must be positive")
    symbol_roots: dict[str, Path] = {}
    for item in args.symbol_root:
        symbol, separator, raw_path = item.partition("=")
        if not separator or not symbol or not raw_path:
            parser.error("--symbol-root must use SYMBOL=PATH")
        symbol_roots[symbol] = Path(raw_path)

    years = range(args.feature_start_year, args.feature_end_year + 1)
    daily_files = [
        Path(f"data/processed/pit_b_daily_2018_2026_v2/daily/partition_year={year}/data_0.parquet")
        for year in years
    ]
    feature_files = {
        year: Path(f"data/processed/chip_state_features_by_year_2018_2026_v2/year={year}/data.parquet")
        for year in years
    }
    symbol_sql = ",".join("'" + symbol.replace("'", "''") + "'" for symbol in symbols)
    con = duckdb.connect()
    con.execute("SET memory_limit='8GiB'")
    con.execute(f"SET threads={min(args.workers, 8)}")
    con.execute("SET preserve_insertion_order=false")
    close_rows = con.execute(
        f"""
        SELECT symbol, trade_date, close
        FROM read_parquet({_sql_paths(daily_files)}, union_by_name=true)
        WHERE symbol IN ({symbol_sql})
        ORDER BY symbol, trade_date
        """
    ).fetchall()
    closes: dict[str, dict[date, float]] = {symbol: {} for symbol in symbols}
    for symbol, trade_date, close in close_rows:
        closes[str(symbol)][trade_date] = float(close)

    args.output.mkdir(parents=True, exist_ok=True)
    exact_path = args.output / "exact_features.parquet"
    exact_parts = args.output / "_exact_parts"
    required_exact_columns = {
        "dominant_band_lower",
        "dominant_band_upper",
        "dominant_band_mass",
        "model_spread_cost_p50",
        "model_spread_cost_p90",
        "model_spread_main_peak",
        "feature_source",
    }
    exact_ready = False
    if exact_path.exists() and required_exact_columns.issubset(
        pq.ParquetFile(exact_path).schema_arrow.names
    ):
        exact_metrics = con.execute(
            f"SELECT count(*), count(DISTINCT symbol) FROM read_parquet('{exact_path}')"
        ).fetchone()
        exact_ready = exact_metrics is not None and int(exact_metrics[1]) == len(symbols)
    if exact_ready:
        exact_rows_count = pq.ParquetFile(exact_path).metadata.num_rows
    else:
        exact_path.unlink(missing_ok=True)
        tasks = [
            (
                symbol_roots.get(
                    symbol,
                    args.primary_root if symbol == "000001.SZ" else args.secondary_root,
                ),
                symbol,
                closes[symbol],
                args.exact_start,
                args.exact_end,
                exact_parts / f"{symbol.replace('.', '_')}.parquet",
            )
            for symbol in symbols
        ]
        completed = 0
        exact_rows_count = 0
        with ProcessPoolExecutor(max_workers=min(args.workers, len(tasks))) as pool:
            futures = [pool.submit(_build_symbol_exact, task) for task in tasks]
            for future in as_completed(futures):
                _, rows, _ = future.result()
                completed += 1
                exact_rows_count += rows
                if completed % 100 == 0 or completed == len(tasks):
                    print(
                        f"exact_progress={completed}/{len(tasks)} rows={exact_rows_count}",
                        flush=True,
                    )
        temp_exact_path = exact_path.with_suffix(".tmp.parquet")
        temp_exact_path.unlink(missing_ok=True)
        con.execute(
            f"""
            COPY (
                SELECT * FROM read_parquet('{exact_parts}/*.parquet', union_by_name=true)
            ) TO '{temp_exact_path}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
        temp_exact_path.replace(exact_path)
        exact_metrics = con.execute(
            f"SELECT count(*), count(DISTINCT symbol) FROM read_parquet('{exact_path}')"
        ).fetchone()
        if exact_metrics is None or int(exact_metrics[1]) != len(symbols):
            raise RuntimeError(f"exact feature coverage failed: {exact_metrics}")
        exact_rows_count = int(exact_metrics[0])
        shutil.rmtree(exact_parts)

    feature_code_path = Path(build_exact_ensemble_features.__code__.co_filename)
    feature_code_sha256 = hashlib.sha256(feature_code_path.read_bytes()).hexdigest()
    feature_config_sha256 = hashlib.sha256(
        b"exact-chip-ensemble-features-v4|persisted-daily-metrics-v13|median-three-models|log-grid-25bp-v1"
    ).hexdigest()

    for year in years:
        target = args.output / f"year={year}" / "data.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        if year < 2020:
            query = f"""
                SELECT * REPLACE (
                    false AS chip_input_valid,
                    false AS state_chain_valid,
                    false AS strict_sample,
                    concat_ws('|', invalid_reason, 'LEGACY_WARMUP_ONLY') AS invalid_reason
                )
                FROM read_parquet('{feature_files[year]}')
                WHERE symbol IN ({symbol_sql})
            """
        else:
            query = f"""
                SELECT f.* REPLACE (
                    coalesce(CAST(e.available_at AS TIMESTAMP), f.available_at) AS available_at,
                    coalesce(e.snapshot_id, f.daily_snapshot_id) AS daily_snapshot_id,
                    CASE
                        WHEN e.feature_source = 'PERSISTED_DAILY_METRICS_V13'
                            THEN 'real-chip-inventory-v2.1/chip-operator-log-v13'
                        ELSE 'real-chip-inventory-v2.1/replayed-legacy-operator-log'
                    END AS state_version,
                    coalesce(e.research_valid, false) AS chip_input_valid,
                    coalesce(e.research_valid, false) AS state_chain_valid,
                    false AS strict_sample,
                    CASE
                        WHEN e.symbol IS NULL THEN 'B_RESEARCH_ONLY_UNKNOWN_COST'
                        WHEN NOT coalesce(e.research_valid, false) THEN concat_ws(
                            '|',
                            'B_RESEARCH_ONLY_EXACT',
                            coalesce(
                                CAST(e.invalid_reason AS VARCHAR),
                                'SOURCE_RESEARCH_INVALID'
                            )
                        )
                        ELSE 'B_RESEARCH_ONLY_EXACT'
                    END AS invalid_reason,
                    1.0 AS mass_sum,
                    coalesce(e.known_cost_fraction_min, 0.0) AS state_quality,
                    e.profit_ratio AS profit_ratio,
                    1.0 - e.profit_ratio AS trapped_ratio,
                    e.average_cost AS average_cost,
                    e.cost_p01 AS p01,
                    e.cost_p10 AS p10,
                    e.cost_p50 AS p50,
                    e.cost_p90 AS p90,
                    e.cost_p99 AS p99,
                    e.asr AS asr,
                    e.cbw AS cbw,
                    e.concentration_20 AS concentration_20,
                    CAST(e.peak_count AS INTEGER) AS peak_count
                    ,printf('[{{"center_price":%.17g}}]', e.main_peak) AS peaks_json
                    ,'{feature_config_sha256}' AS config_sha256
                    ,'{feature_code_sha256}' AS code_sha256
                ),
                    e.dominant_band_lower,
                    e.dominant_band_upper,
                    e.dominant_band_mass,
                    e.model_min_cost_p50,
                    e.model_max_cost_p50,
                    e.model_spread_cost_p50,
                    e.model_min_cost_p90,
                    e.model_max_cost_p90,
                    e.model_spread_cost_p90,
                    e.model_min_main_peak,
                    e.model_max_main_peak,
                    e.model_spread_main_peak
                FROM read_parquet('{feature_files[year]}') f
                LEFT JOIN read_parquet('{exact_path}') e USING (symbol, trade_date)
                WHERE f.symbol IN ({symbol_sql})
            """
        target.unlink(missing_ok=True)
        con.execute(
            f"COPY ({query}) TO '{target}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    con.close()
    print(f"PASS symbols={len(symbols)} exact_rows={exact_rows_count} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
