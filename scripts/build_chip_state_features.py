#!/usr/bin/env python3
"""Build checkpointed daily chip features from the frozen PIT-B inputs.

This is state generation, not a backtest.  The source Parquet inventory is scanned
once into stable symbol buckets; each bucket can then be resumed independently.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import duckdb
import numpy as np
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from cyq_game.chip import (
    CohortChipEngine,
    UniformChipEngine,
    advance_chip_state,
    apply_split_to_state,
)
from cyq_game.config import ChipConfig, load_config
from cyq_game.data import ChipObservation
from cyq_game.domain import Bar

ROOT = Path(__file__).resolve().parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")
STATE_VERSION = "chip-state-features-v1"
# A larger batch materially reduces Arrow conversion and Parquet row-group
# overhead.  Ten workers still remain comfortably below the host's memory
# capacity at this size.
IO_BATCH_ROWS = 16_384
OUTPUT_SCHEMA = pa.schema(
    [
        ("symbol", pa.string()),
        ("trade_date", pa.date32()),
        ("available_at", pa.timestamp("us")),
        ("daily_snapshot_id", pa.string()),
        ("minute_snapshot_id", pa.string()),
        ("state_version", pa.string()),
        ("config_sha256", pa.string()),
        ("code_sha256", pa.string()),
        ("chip_input_valid", pa.bool_()),
        ("daily_hard_valid", pa.bool_()),
        ("minute_hard_valid", pa.bool_()),
        ("state_chain_valid", pa.bool_()),
        ("warmup_count", pa.int32()),
        ("strict_sample", pa.bool_()),
        ("invalid_reason", pa.string()),
        ("mass_sum", pa.float64()),
        ("state_quality", pa.float64()),
        ("profit_ratio", pa.float64()),
        ("trapped_ratio", pa.float64()),
        ("average_cost", pa.float64()),
        ("p01", pa.float64()),
        ("p10", pa.float64()),
        ("p50", pa.float64()),
        ("p90", pa.float64()),
        ("p99", pa.float64()),
        ("asr", pa.float64()),
        ("space20", pa.float64()),
        ("ckdp", pa.float64()),
        ("ckdw", pa.float64()),
        ("cbw", pa.float64()),
        ("cyqk_open_pre", pa.float64()),
        ("cyqk_high_pre", pa.float64()),
        ("cyqk_low_pre", pa.float64()),
        ("cyqk_close_pre", pa.float64()),
        ("cyc5", pa.float64()),
        ("cyc13", pa.float64()),
        ("cyc34", pa.float64()),
        ("cys13", pa.float64()),
        ("cys34", pa.float64()),
        ("rpy2", pa.float64()),
        ("concentration_20", pa.float64()),
        ("base_retention", pa.float64()),
        ("peak_count", pa.int32()),
        ("peaks_json", pa.string()),
        ("priors_json", pa.string()),
        ("opening_30m_return", pa.float64()),
        ("closing_30m_return", pa.float64()),
        ("close_vs_vwap", pa.float64()),
        ("last_hour_volume_share", pa.float64()),
        ("realized_volatility", pa.float64()),
    ]
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _fingerprints(config_path: Path) -> tuple[str, str]:
    config_hash = _sha256_bytes(config_path.read_bytes())
    code = b"".join(
        path.read_bytes()
        for path in (
            ROOT / "src/cyq_game/chip/core.py",
            ROOT / "src/cyq_game/chip/features.py",
            ROOT / "src/cyq_game/chip/transition.py",
            Path(__file__),
        )
    )
    return config_hash, _sha256_bytes(code)


def _stage_inputs(
    output: Path,
    daily_glob: str,
    minute_glob: str,
    buckets: int,
    start: date | None,
    end: date | None,
    symbol_limit: int | None,
    fingerprint: dict[str, Any],
) -> None:
    stage = output / "_staging"
    manifest = stage / "manifest.json"
    if manifest.exists() and json.loads(manifest.read_text()) == fingerprint:
        return
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    filters: list[str] = []
    if start:
        filters.append(f"trade_date >= DATE '{start.isoformat()}'")
    if end:
        filters.append(f"trade_date <= DATE '{end.isoformat()}'")
    where = " AND ".join(filters) or "TRUE"
    symbol_cte = ""
    symbol_join = ""
    if symbol_limit:
        symbol_cte = f""", selected_symbols AS (
            SELECT symbol FROM daily_source GROUP BY symbol ORDER BY symbol LIMIT {symbol_limit}
        )"""
        symbol_join = "JOIN selected_symbols s USING (symbol)"
    target = str(stage / "rows").replace("'", "''")
    daily = daily_glob.replace("'", "''")
    minute = minute_glob.replace("'", "''")
    query = f"""
        COPY (
          WITH daily_source AS (
            SELECT * FROM read_parquet('{daily}', union_by_name=true)
            WHERE {where}
          ){symbol_cte}, daily_window AS (
            SELECT d.*,
                   MIN(low) FILTER (WHERE bar_valid) OVER hist AS history_low_2y,
                   MAX(high) FILTER (WHERE bar_valid) OVER hist AS history_high_2y
            FROM daily_source d {symbol_join}
            WINDOW hist AS (
              PARTITION BY symbol ORDER BY trade_date
              ROWS BETWEEN 503 PRECEDING AND CURRENT ROW
            )
          ), minute_source AS (
            SELECT * FROM read_parquet('{minute}', union_by_name=true)
            WHERE {where}
          )
          SELECT CAST(hash(d.symbol) % {buckets} AS INTEGER) AS bucket,
                 d.symbol, d.trade_date, d.decision_at, d.open, d.high, d.low,
                 d.close, d.volume, d.amount, d.circulating_shares,
                 d.trade_status, d.bar_valid, d.trading_state_valid,
                 d.float_valid, d.corporate_action_valid,
                 d.historical_identity_valid, d.hard_valid AS daily_hard_valid,
                 d.invalid_reasons AS daily_invalid_reasons,
                 d.available_at AS daily_available_at, d.snapshot_id AS daily_snapshot_id,
                 d.corporate_action_count, d.corporate_action_ids,
                 d.share_multiplier, d.history_low_2y, d.history_high_2y,
                 m.available_at AS minute_available_at,
                 m.chip_prices, m.chip_volumes,
                 COALESCE(m.hard_valid, FALSE) AS minute_hard_valid,
                 m.invalid_reasons AS minute_invalid_reasons,
                 m.source AS minute_source, m.snapshot_id AS minute_snapshot_id,
                 m.opening_30m_return, m.closing_30m_return, m.close_vs_vwap,
                 m.last_hour_volume_share, m.realized_volatility
          FROM daily_window d
          LEFT JOIN minute_source m USING (symbol, trade_date)
        ) TO '{target}' (
          FORMAT PARQUET, PARTITION_BY (bucket), COMPRESSION ZSTD,
          ROW_GROUP_SIZE 65536
        )
    """
    connection = duckdb.connect()
    try:
        connection.execute("PRAGMA threads=10")
        connection.execute(query)
    finally:
        connection.close()
    manifest.write_text(json.dumps(fingerprint, sort_keys=True, indent=2) + "\n")


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=SHANGHAI) if value.tzinfo is None else value


def _engine(config: ChipConfig) -> CohortChipEngine | UniformChipEngine:
    if config.engine == "cohort":
        return CohortChipEngine(config.lambda_turnover)
    return UniformChipEngine(config.lambda_turnover)


def _empty_output(row: dict[str, Any], meta: dict[str, str], reason: str) -> dict[str, Any]:
    result: dict[str, Any] = {field.name: None for field in OUTPUT_SCHEMA}
    result.update(
        {
            "symbol": row["symbol"],
            "trade_date": row["trade_date"],
            "available_at": row["daily_available_at"],
            "daily_snapshot_id": row["daily_snapshot_id"],
            "minute_snapshot_id": row["minute_snapshot_id"],
            "state_version": STATE_VERSION,
            "config_sha256": meta["config_sha256"],
            "code_sha256": meta["code_sha256"],
            "chip_input_valid": False,
            "daily_hard_valid": bool(row["daily_hard_valid"]),
            "minute_hard_valid": bool(row["minute_hard_valid"]),
            "state_chain_valid": False,
            "warmup_count": 0,
            "strict_sample": False,
            "invalid_reason": reason,
        }
    )
    return result


def _flush(writer: pq.ParquetWriter, rows: list[dict[str, Any]]) -> None:
    if rows:
        writer.write_table(pa.Table.from_pylist(rows, schema=OUTPUT_SCHEMA))
        rows.clear()


def _process_bucket(
    bucket: int,
    output_text: str,
    chip_values: dict[str, Any],
    meta: dict[str, str],
) -> dict[str, Any]:
    output = Path(output_text)
    part = output / f"bucket={bucket:02d}"
    final = part / "data.parquet"
    complete = part / "complete.json"
    expected = {**meta, "bucket": bucket, "state_version": STATE_VERSION}
    if final.exists() and complete.exists():
        prior = json.loads(complete.read_text())
        if all(prior.get(key) == value for key, value in expected.items()):
            return cast(dict[str, Any], prior)
    part.mkdir(parents=True, exist_ok=True)
    temporary = part / f"data.{os.getpid()}.tmp.parquet"
    source = output / "_staging" / "rows" / f"bucket={bucket}" / "*.parquet"
    if not list(source.parent.glob("*.parquet")):
        result = {**expected, "rows": 0, "strict_rows": 0, "seconds": 0.0}
        complete.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
        return result
    connection = duckdb.connect()
    cursor = connection.execute(
        f"SELECT * EXCLUDE(bucket) FROM read_parquet('{source}') ORDER BY symbol, trade_date"
    )
    description = cursor.description
    if description is None:
        raise RuntimeError(f"bucket {bucket} query returned no schema")
    columns = [item[0] for item in description]
    config = ChipConfig(**chip_values)
    engine = _engine(config)
    # Level 1 is the Pareto point for this numeric/JSON-heavy schema: it writes
    # about 30% faster than the default level in a representative frozen bucket
    # and does not increase its output size.
    writer = pq.ParquetWriter(
        temporary,
        OUTPUT_SCHEMA,
        compression="zstd",
        compression_level=1,
    )
    state = None
    symbol: str | None = None
    warmup_count = 0
    base_band: tuple[float, float, float] | None = None
    buffered: list[dict[str, Any]] = []
    priors_json_cache: dict[tuple[str, ...], str] = {(): "[]"}
    row_count = 0
    strict_count = 0
    started = time.monotonic()
    try:
        while batch := cursor.fetchmany(IO_BATCH_ROWS):
            for values in batch:
                row = dict(zip(columns, values, strict=True))
                current_symbol = cast(str, row["symbol"])
                if current_symbol != symbol:
                    symbol = current_symbol
                    state = None
                    warmup_count = 0
                    base_band = None
                valid = all(
                    bool(row[name])
                    for name in (
                        "bar_valid",
                        "trading_state_valid",
                        "float_valid",
                        "corporate_action_valid",
                        "historical_identity_valid",
                    )
                )
                if not valid:
                    state = None
                    warmup_count = 0
                    base_band = None
                    invalid_reason = (
                        row["daily_invalid_reasons"] or "CHIP_INPUT_INVALID"
                    )
                    buffered.append(_empty_output(row, meta, invalid_reason))
                    row_count += 1
                    if len(buffered) >= IO_BATCH_ROWS:
                        _flush(writer, buffered)
                    continue
                trade_date = row["trade_date"]
                multiplier = row["share_multiplier"]
                if state is not None and multiplier is not None and float(multiplier) != 1.0:
                    split_ratio = float(multiplier)
                    state = apply_split_to_state(state, split_ratio, trade_date)
                    if base_band is not None:
                        base_band = (
                            base_band[0] / split_ratio,
                            base_band[1] / split_ratio,
                            base_band[2],
                        )
                bar = Bar(
                    symbol=current_symbol,
                    trade_date=trade_date,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                    amount=float(row["amount"]),
                    free_float_shares=float(row["circulating_shares"]),
                    available_at=_aware(row["daily_available_at"]),
                    suspended=int(row["trade_status"]) != 1,
                )
                observation = None
                minute_valid = bool(
                    row["minute_hard_valid"]
                    and row["minute_available_at"] is not None
                )
                if minute_valid:
                    observation = ChipObservation(
                        symbol=current_symbol,
                        trade_date=trade_date,
                        prices=tuple(float(item) for item in row["chip_prices"]),
                        volumes=tuple(float(item) for item in row["chip_volumes"]),
                        available_at=_aware(row["minute_available_at"]),
                        source=row["minute_source"],
                        snapshot_id=row["minute_snapshot_id"],
                        hard_valid=True,
                    )
                transition = advance_chip_state(
                    engine,
                    state,
                    bar,
                    observation,
                    grid_step_pct=config.grid_step_pct,
                    history_low_2y=row["history_low_2y"],
                    history_high_2y=row["history_high_2y"],
                    smoothing_sigma=config.smoothing_sigma_bins,
                    peak_prominence=config.peak_prominence,
                )
                state = transition.state
                warmup_count += 1
                if transition.initial_base_band is not None:
                    base_band = transition.initial_base_band
                features = transition.features
                if features is None:
                    raise AssertionError("feature generation unexpectedly disabled")
                priors_json = priors_json_cache.get(features.priors)
                if priors_json is None:
                    priors_json = json.dumps(features.priors, separators=(",", ":"))
                    priors_json_cache[features.priors] = priors_json
                retained = None
                if base_band is not None:
                    left = int(np.searchsorted(state.grid.prices, base_band[0], side="left"))
                    right = int(np.searchsorted(state.grid.prices, base_band[1], side="right"))
                    retained = min(
                        1.0,
                        float(state.mass[left:right].sum()) / max(base_band[2], 1e-12),
                    )
                strict = bool(
                    row["daily_hard_valid"]
                    and minute_valid
                    and warmup_count >= config.warmup_days
                )
                available_at = (
                    max(row["daily_available_at"], row["minute_available_at"])
                    if minute_valid
                    else row["daily_available_at"]
                )
                result = {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "available_at": available_at,
                    "daily_snapshot_id": row["daily_snapshot_id"],
                    "minute_snapshot_id": row["minute_snapshot_id"],
                    "state_version": STATE_VERSION,
                    "config_sha256": meta["config_sha256"],
                    "code_sha256": meta["code_sha256"],
                    "chip_input_valid": True,
                    "daily_hard_valid": bool(row["daily_hard_valid"]),
                    "minute_hard_valid": minute_valid,
                    "state_chain_valid": True,
                    "warmup_count": warmup_count,
                    "strict_sample": strict,
                    "invalid_reason": None if strict else "WARMUP_OR_STRICT_INPUT_INVALID",
                    "mass_sum": state.mass_sum,
                    "state_quality": features.quality,
                    "profit_ratio": features.profit_ratio,
                    "trapped_ratio": features.trapped_ratio,
                    "average_cost": features.average_cost,
                    "p01": features.p01,
                    "p10": features.p10,
                    "p50": features.p50,
                    "p90": features.p90,
                    "p99": features.p99,
                    "asr": features.asr,
                    "space20": features.space20,
                    "ckdp": features.ckdp,
                    "ckdw": features.ckdw,
                    "cbw": features.cbw,
                    "cyqk_open_pre": features.cyqk_pre.open,
                    "cyqk_high_pre": features.cyqk_pre.high,
                    "cyqk_low_pre": features.cyqk_pre.low,
                    "cyqk_close_pre": features.cyqk_pre.close,
                    "cyc5": features.cyc5,
                    "cyc13": features.cyc13,
                    "cyc34": features.cyc34,
                    "cys13": features.cys13,
                    "cys34": features.cys34,
                    "rpy2": features.rpy2,
                    "concentration_20": features.concentration_20,
                    "base_retention": retained,
                    "peak_count": len(features.peaks),
                    "peaks_json": json.dumps(
                        [
                            {
                                "center_price": peak.center_price,
                                "mass": peak.mass,
                                "width_pct": peak.width_pct,
                                "prominence": peak.prominence,
                                "age_mean": peak.age_mean,
                                "formation_date": peak.formation_date,
                            }
                            for peak in features.peaks
                        ],
                        separators=(",", ":"),
                    ),
                    "priors_json": priors_json,
                    "opening_30m_return": row["opening_30m_return"],
                    "closing_30m_return": row["closing_30m_return"],
                    "close_vs_vwap": row["close_vs_vwap"],
                    "last_hour_volume_share": row["last_hour_volume_share"],
                    "realized_volatility": row["realized_volatility"],
                }
                buffered.append(result)
                row_count += 1
                strict_count += int(strict)
                if len(buffered) >= IO_BATCH_ROWS:
                    _flush(writer, buffered)
        _flush(writer, buffered)
    finally:
        writer.close()
        connection.close()
    os.replace(temporary, final)
    result = {
        **expected,
        "rows": row_count,
        "strict_rows": strict_count,
        "seconds": round(time.monotonic() - started, 3),
    }
    complete.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "configs/research.yaml")
    parser.add_argument(
        "--daily",
        default=str(
            ROOT / "data/processed/pit_b_daily_2018_2026_v2/daily/**/*.parquet"
        ),
    )
    parser.add_argument(
        "--minute",
        default=str(
            ROOT / "data/processed/pit_b_minute_2018_2026_v2/daily/**/*.parquet"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data/processed/chip_state_features_2018_2026_v1",
    )
    parser.add_argument("--buckets", type=int, default=40)
    parser.add_argument("--workers", type=int, default=min(10, os.cpu_count() or 1))
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--symbol-limit", type=int)
    args = parser.parse_args()
    if args.buckets <= 0 or args.workers <= 0:
        parser.error("buckets and workers must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    config_hash, code_hash = _fingerprints(args.config)
    meta = {"config_sha256": config_hash, "code_sha256": code_hash}
    fingerprint = {
        **meta,
        "state_version": STATE_VERSION,
        "daily": args.daily,
        "minute": args.minute,
        "buckets": args.buckets,
        "start": args.start.isoformat() if args.start else None,
        "end": args.end.isoformat() if args.end else None,
        "symbol_limit": args.symbol_limit,
    }
    started = time.monotonic()
    _stage_inputs(
        args.output,
        args.daily,
        args.minute,
        args.buckets,
        args.start,
        args.end,
        args.symbol_limit,
        fingerprint,
    )
    config = load_config(args.config).chip
    chip_values = asdict(config)
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=min(args.workers, args.buckets)) as pool:
        futures = [
            pool.submit(_process_bucket, bucket, str(args.output), chip_values, meta)
            for bucket in range(args.buckets)
        ]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(json.dumps(result, sort_keys=True), flush=True)
    summary = {
        **fingerprint,
        "rows": sum(item["rows"] for item in results),
        "strict_rows": sum(item["strict_rows"] for item in results),
        "seconds": round(time.monotonic() - started, 3),
        "completed_buckets": len(results),
    }
    (args.output / "manifest.json").write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n")
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
