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
    apply_cash_dividend_to_state,
    apply_split_to_state,
)
from cyq_game.chip.features import migration_mass, peaks_by_price, semantic_cost_intervals
from cyq_game.chip.peaks import TemporalPeakTracker
from cyq_game.chip.price_coordinate import (
    canonical_action_component_id,
    parse_action_ids,
)
from cyq_game.config import ChipConfig, load_config
from cyq_game.data import ChipObservation
from cyq_game.domain import Bar
from cyq_game.strategy.semantic_contract import semantic_fingerprint_fields

ROOT = Path(__file__).resolve().parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")
# v1/v3 materializations are immutable historical artifacts.  The cash-rebased
# versions explicitly encode corporate-action state semantics in their version.
STATE_VERSION = "chip-state-features-v5-canonical-peak"
SEMANTIC_STATE_VERSION = "chip-state-features-semantic-v5-canonical-peak"
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
        ("corporate_action_snapshot_id", pa.string()),
        ("corporate_action_count", pa.int32()),
        ("corporate_action_ids", pa.string()),
        ("share_multiplier", pa.float64()),
        ("cash_per_share", pa.float64()),
        ("state_version", pa.string()),
        ("config_sha256", pa.string()),
        ("code_sha256", pa.string()),
        ("chip_input_valid", pa.bool_()),
        ("daily_hard_valid", pa.bool_()),
        ("minute_hard_valid", pa.bool_()),
        ("minute_requirement_waived", pa.bool_()),
        ("state_chain_valid", pa.bool_()),
        ("warmup_count", pa.int32()),
        ("strict_sample", pa.bool_()),
        ("research_sample", pa.bool_()),
        ("daily_research_sample", pa.bool_()),
        ("research_suspension_bridge", pa.bool_()),
        ("invalid_reason", pa.string()),
        ("degraded_mode", pa.string()),
        ("source_mode", pa.string()),
        ("action_blocking", pa.bool_()),
        ("action_provenance", pa.string()),
        ("mass_sum", pa.float64()),
        ("state_quality", pa.float64()),
        ("known_cost_fraction_min", pa.float64()),
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
        ("dominant_peak_today", pa.float64()),
        ("dominant_peak_ambiguous", pa.bool_()),
        ("tracked_base_peak", pa.float64()),
        ("peak_track_id", pa.string()),
        ("peak_track_age", pa.int32()),
        ("peak_track_band_lower", pa.float64()),
        ("peak_track_band_upper", pa.float64()),
        ("peak_track_mass", pa.float64()),
        ("peak_track_prominence", pa.float64()),
        ("peak_track_ambiguous", pa.bool_()),
        ("peak_track_split", pa.bool_()),
        ("peak_track_merge", pa.bool_()),
        ("peak_track_lost", pa.bool_()),
        ("peak_fail_closed_reason", pa.string()),
        ("peak_definition_version", pa.string()),
        ("peaks_json", pa.string()),
        ("priors_json", pa.string()),
        ("opening_30m_return", pa.float64()),
        ("closing_30m_return", pa.float64()),
        ("close_vs_vwap", pa.float64()),
        ("last_hour_volume_share", pa.float64()),
        ("realized_volatility", pa.float64()),
    ]
)

SEMANTIC_OUTPUT_SCHEMA = pa.schema(
    [*OUTPUT_SCHEMA, *[
        pa.field("semantic_version", pa.string()),
        pa.field("p05", pa.float64()),
        pa.field("p15", pa.float64()),
        pa.field("p85", pa.float64()),
        pa.field("p95", pa.float64()),
        pa.field("i90_lower", pa.float64()),
        pa.field("i90_upper", pa.float64()),
        pa.field("i90_width_pct", pa.float64()),
        pa.field("i70_lower", pa.float64()),
        pa.field("i70_upper", pa.float64()),
        pa.field("i70_width_pct", pa.float64()),
        pa.field("i90_base_retention", pa.float64()),
        pa.field("i70_base_retention", pa.float64()),
        pa.field("migration_mass", pa.float64()),
        pa.field("average_cost_delta", pa.float64()),
        pa.field("upper_peak_center", pa.float64()),
        pa.field("upper_peak_mass", pa.float64()),
        pa.field("upper_peak_lower", pa.float64()),
        pa.field("upper_peak_upper", pa.float64()),
        pa.field("upper_peak_prominence", pa.float64()),
        pa.field("peaks_price_json", pa.string()),
    ]]
)


def _is_suspended(value: Any) -> bool:
    """Treat status 0 as an explicit suspension, not as a missing value."""
    return value is not None and int(value) == 0


def _minute_requirement_satisfied(
    *, trade_status: int | None, minute_hard_valid: bool, minute_available_at: Any
) -> bool:
    """Require minutes for trading days, but waive them for explicit suspension."""
    if trade_status == 0:
        return True
    return bool(minute_hard_valid and minute_available_at is not None)


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
    industry_fallback_glob: str | None,
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
    industry = (industry_fallback_glob or "").replace("'", "''")
    industry_join = (
        f"LEFT JOIN read_parquet('{industry}', union_by_name=true) i USING (symbol, trade_date)"
        if industry
        else ""
    )
    industry_projection = (
        "COALESCE(i.research_industry, NULL) AS research_industry, "
        "COALESCE(i.research_industry_valid, d.industry_valid) AS research_industry_valid, "
        "COALESCE(i.industry_research_fallback, FALSE) AS industry_research_fallback"
        if industry
        else "CAST(NULL AS VARCHAR) AS research_industry, "
        "d.industry_valid AS research_industry_valid, "
        "FALSE AS industry_research_fallback"
    )
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
                 d.corporate_action_snapshot_id, d.corporate_action_count,
                 d.corporate_action_ids, d.share_multiplier, d.cash_per_share,
                 d.history_low_2y, d.history_high_2y,
                 CASE WHEN d.bar_valid THEN d.volume ELSE m.minute_volume END AS research_volume,
                 CASE WHEN d.bar_valid THEN d.amount ELSE m.minute_amount END AS research_amount,
                 CASE WHEN d.bar_valid THEN TRUE ELSE
                   (m.minute_volume IS NOT NULL AND m.minute_volume > 0 AND m.minute_amount IS NOT NULL AND m.minute_amount > 0)
                 END AS research_bar_valid,
                 {industry_projection},
                 m.available_at AS minute_available_at,
                 m.minute_volume, m.minute_amount,
                 m.chip_prices, m.chip_volumes,
                 COALESCE(m.hard_valid, FALSE) AS minute_hard_valid,
                 m.invalid_reasons AS minute_invalid_reasons,
                 m.source AS minute_source, m.snapshot_id AS minute_snapshot_id,
                 m.opening_30m_return, m.closing_30m_return, m.close_vs_vwap,
                 m.last_hour_volume_share, m.realized_volatility
          FROM daily_window d
          LEFT JOIN minute_source m USING (symbol, trade_date)
          {industry_join}
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


def _empty_output(
    row: dict[str, Any],
    meta: dict[str, str],
    reason: str,
    *,
    schema: pa.Schema,
    state_version: str,
    semantic_v3: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {field.name: None for field in schema}
    result.update(
        {
            "symbol": row["symbol"],
            "trade_date": row["trade_date"],
            "available_at": row["daily_available_at"],
            "daily_snapshot_id": row["daily_snapshot_id"],
            "minute_snapshot_id": row["minute_snapshot_id"],
            "corporate_action_snapshot_id": row.get("corporate_action_snapshot_id"),
            "corporate_action_count": row.get("corporate_action_count"),
            "corporate_action_ids": row.get("corporate_action_ids"),
            "share_multiplier": row.get("share_multiplier"),
            "cash_per_share": row.get("cash_per_share"),
            "state_version": state_version,
            "config_sha256": meta["config_sha256"],
            "code_sha256": meta["code_sha256"],
            "chip_input_valid": False,
            "daily_hard_valid": bool(row["daily_hard_valid"]),
            "minute_hard_valid": bool(row["minute_hard_valid"]),
            "state_chain_valid": False,
            "warmup_count": 0,
            "strict_sample": False,
            "research_sample": False,
            "daily_research_sample": False,
            "research_suspension_bridge": False,
            "invalid_reason": reason,
        }
    )
    if semantic_v3:
        result["semantic_version"] = "semantic-v4"
    return result


def _flush(
    writer: pq.ParquetWriter, rows: list[dict[str, Any]], schema: pa.Schema
) -> None:
    if rows:
        writer.write_table(pa.Table.from_pylist(rows, schema=schema))
        rows.clear()


def _process_bucket(
    bucket: int,
    output_text: str,
    chip_values: dict[str, Any],
    meta: dict[str, str],
    research_relaxed: bool,
    semantic_v3: bool,
) -> dict[str, Any]:
    schema = SEMANTIC_OUTPUT_SCHEMA if semantic_v3 else OUTPUT_SCHEMA
    state_version = SEMANTIC_STATE_VERSION if semantic_v3 else STATE_VERSION
    output = Path(output_text)
    part = output / f"bucket={bucket:02d}"
    final = part / "data.parquet"
    complete = part / "complete.json"
    expected = {**meta, "bucket": bucket, "state_version": state_version}
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
        schema,
        compression="zstd",
        compression_level=1,
    )
    state = None
    symbol: str | None = None
    warmup_count = 0
    base_band: tuple[float, float, float] | None = None
    i90_band: tuple[float, float, float] | None = None
    i70_band: tuple[float, float, float] | None = None
    previous_state = None
    peak_tracker: TemporalPeakTracker | None = None
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
                    i90_band = None
                    i70_band = None
                    previous_state = None
                    peak_tracker = TemporalPeakTracker(
                        symbol=current_symbol, model=config.engine
                    )
                strict_input_valid = all(
                    bool(row[name])
                    for name in (
                        "bar_valid",
                        "trading_state_valid",
                        "float_valid",
                        "corporate_action_valid",
                        "historical_identity_valid",
                    )
                )
                effective_bar_valid = bool(
                    row["bar_valid"]
                    or (research_relaxed and row["research_bar_valid"])
                    or (
                        research_relaxed
                        and _is_suspended(row["trade_status"])
                        and all(
                            row[name] is not None and float(row[name]) > 0
                            for name in ("open", "high", "low", "close")
                        )
                    )
                )
                research_input_valid = bool(
                    effective_bar_valid
                    and row["corporate_action_valid"]
                    and row["trade_status"] is not None
                    and row["circulating_shares"] is not None
                    and float(row["circulating_shares"]) > 0
                )
                valid = strict_input_valid or (research_relaxed and research_input_valid)
                if not valid:
                    state = None
                    warmup_count = 0
                    base_band = None
                    i90_band = None
                    i70_band = None
                    previous_state = None
                    peak_tracker = TemporalPeakTracker(
                        symbol=current_symbol, model=config.engine
                    )
                    invalid_reason = (
                        row["daily_invalid_reasons"] or "CHIP_INPUT_INVALID"
                    )
                    buffered.append(
                        _empty_output(
                            row,
                            meta,
                            invalid_reason,
                            schema=schema,
                            state_version=state_version,
                            semantic_v3=semantic_v3,
                        )
                    )
                    row_count += 1
                    if len(buffered) >= IO_BATCH_ROWS:
                        _flush(writer, buffered, schema)
                    continue
                trade_date = row["trade_date"]
                cash_per_share = row["cash_per_share"]
                action_sources = parse_action_ids(row.get("corporate_action_ids"))
                action_snapshot_id = str(
                    row.get("corporate_action_snapshot_id") or row["daily_snapshot_id"]
                )
                cash_value = float(cash_per_share or 0.0)
                multiplier_value = float(row.get("share_multiplier") or 1.0)
                if (
                    peak_tracker is not None
                    and (cash_value > 0.0 or multiplier_value != 1.0)
                ):
                    peak_tracker.apply_corporate_action(
                        action_id=canonical_action_component_id(
                            symbol=current_symbol,
                            effective_date=trade_date,
                            kind="DAILY_AGGREGATE",
                            source_action_ids=action_sources,
                            snapshot_id=action_snapshot_id,
                            cash_per_share=cash_value,
                            share_multiplier=multiplier_value,
                        ),
                        cash_per_share=cash_value,
                        share_multiplier=multiplier_value,
                    )
                # Corporate-action priority is causal and matches the event
                # replay engine: cash distribution first, then split.  For a
                # combined event this yields (cost - cash) / split_ratio.
                if state is not None and cash_per_share is not None and float(cash_per_share) > 0:
                    dividend = float(cash_per_share)
                    # Do not clip or renormalize an invalid cost coordinate.
                    # A dividend at or above the lowest modeled cost bucket
                    # cannot be applied causally; fail closed for this date
                    # and restart warmup from the next usable observation.
                    if bool(np.any(state.grid.prices - dividend <= 0)):
                        state = None
                        warmup_count = 0
                        base_band = None
                        i90_band = None
                        i70_band = None
                        previous_state = None
                        peak_tracker = TemporalPeakTracker(
                            symbol=current_symbol, model=config.engine
                        )
                        buffered.append(
                            _empty_output(
                                row,
                                meta,
                                "CASH_DIVIDEND_NON_POSITIVE_PRICE_COORDINATE",
                                schema=schema,
                                state_version=state_version,
                                semantic_v3=semantic_v3,
                            )
                        )
                        row_count += 1
                        if len(buffered) >= IO_BATCH_ROWS:
                            _flush(writer, buffered, schema)
                        continue
                    state = apply_cash_dividend_to_state(
                        state,
                        dividend,
                        trade_date,
                        action_id=canonical_action_component_id(
                            symbol=current_symbol,
                            effective_date=trade_date,
                            kind="CASH_DIVIDEND",
                            source_action_ids=action_sources,
                            snapshot_id=action_snapshot_id,
                            cash_per_share=dividend,
                        ),
                    )
                    if base_band is not None:
                        base_band = (
                            base_band[0] - dividend,
                            base_band[1] - dividend,
                            base_band[2],
                        )
                    if i90_band is not None:
                        i90_band = (
                            i90_band[0] - dividend,
                            i90_band[1] - dividend,
                            i90_band[2],
                        )
                    if i70_band is not None:
                        i70_band = (
                            i70_band[0] - dividend,
                            i70_band[1] - dividend,
                            i70_band[2],
                        )
                multiplier = row["share_multiplier"]
                if state is not None and multiplier is not None and float(multiplier) != 1.0:
                    split_ratio = float(multiplier)
                    state = apply_split_to_state(
                        state,
                        split_ratio,
                        trade_date,
                        action_id=canonical_action_component_id(
                            symbol=current_symbol,
                            effective_date=trade_date,
                            kind="SPLIT",
                            source_action_ids=action_sources,
                            snapshot_id=action_snapshot_id,
                            share_multiplier=split_ratio,
                        ),
                    )
                    if base_band is not None:
                        base_band = (
                            base_band[0] / split_ratio,
                            base_band[1] / split_ratio,
                            base_band[2],
                        )
                    if i90_band is not None:
                        i90_band = (
                            i90_band[0] / split_ratio,
                            i90_band[1] / split_ratio,
                            i90_band[2],
                        )
                    if i70_band is not None:
                        i70_band = (
                            i70_band[0] / split_ratio,
                            i70_band[1] / split_ratio,
                            i70_band[2],
                        )
                previous_state = state
                bar = Bar(
                    symbol=current_symbol,
                    trade_date=trade_date,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(
                        row["research_volume"]
                        if research_relaxed and row["research_volume"] is not None
                        else (0.0 if _is_suspended(row["trade_status"]) else row["volume"])
                    ),
                    amount=float(
                        row["research_amount"]
                        if research_relaxed and row["research_amount"] is not None
                        else (0.0 if _is_suspended(row["trade_status"]) else row["amount"])
                    ),
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
                if peak_tracker is None:
                    raise AssertionError("peak tracker was not initialized")
                peak_tracking = peak_tracker.update(
                    as_of=trade_date, candidates=features.peaks
                )
                priors_json = priors_json_cache.get(features.priors)
                if priors_json is None:
                    priors_json = json.dumps(features.priors, separators=(",", ":"))
                    priors_json_cache[features.priors] = priors_json
                if semantic_v3 and transition.initial_base_band is not None:
                    intervals = semantic_cost_intervals(state)
                    i90_band = (
                        intervals["i90_lower"],
                        intervals["i90_upper"],
                        float(
                            state.mass[
                                (state.grid.prices >= intervals["i90_lower"])
                                & (state.grid.prices <= intervals["i90_upper"])
                            ].sum()
                        ),
                    )
                    i70_band = (
                        intervals["i70_lower"],
                        intervals["i70_upper"],
                        float(
                            state.mass[
                                (state.grid.prices >= intervals["i70_lower"])
                                & (state.grid.prices <= intervals["i70_upper"])
                            ].sum()
                        ),
                    )
                retained = None
                if base_band is not None:
                    left = int(np.searchsorted(state.grid.prices, base_band[0], side="left"))
                    right = int(np.searchsorted(state.grid.prices, base_band[1], side="right"))
                    retained = min(
                        1.0,
                        float(state.mass[left:right].sum()) / max(base_band[2], 1e-12),
                    )
                intervals = semantic_cost_intervals(state) if semantic_v3 else None
                i90_retained = None
                i70_retained = None
                if semantic_v3 and i90_band is not None and i70_band is not None:
                    def _retention(
                        current_state: Any, band: tuple[float, float, float]
                    ) -> float:
                        left = int(
                            np.searchsorted(
                                current_state.grid.prices, band[0], side="left"
                            )
                        )
                        right = int(
                            np.searchsorted(
                                current_state.grid.prices, band[1], side="right"
                            )
                        )
                        return min(
                            1.0,
                            float(current_state.mass[left:right].sum())
                            / max(band[2], 1e-12),
                        )

                    i90_retained = _retention(state, i90_band)
                    i70_retained = _retention(state, i70_band)
                price_peaks = peaks_by_price(features.peaks)
                dominant_peak = peak_tracking.dominant_peak_today
                tracked_base_peak = peak_tracking.tracked_base_peak
                upper_peaks = [
                    peak
                    for peak in features.peaks
                    if dominant_peak is not None
                    and peak.center_price > dominant_peak.center_price
                ]
                upper_peak = max(
                    upper_peaks,
                    key=lambda peak: peak.center_price,
                    default=None,
                )
                strict = bool(
                    row["daily_hard_valid"]
                    and _minute_requirement_satisfied(
                        trade_status=int(row["trade_status"]),
                        minute_hard_valid=minute_valid,
                        minute_available_at=row["minute_available_at"],
                    )
                    and warmup_count >= config.warmup_days
                )
                research = bool(
                    effective_bar_valid
                    and row["float_valid"]
                    and row["corporate_action_valid"]
                    and _minute_requirement_satisfied(
                        trade_status=int(row["trade_status"]),
                        minute_hard_valid=minute_valid,
                        minute_available_at=row["minute_available_at"],
                    )
                    and warmup_count >= config.warmup_days
                )
                daily_research = bool(
                    effective_bar_valid
                    and row["float_valid"]
                    and row["corporate_action_valid"]
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
                    "corporate_action_snapshot_id": row["corporate_action_snapshot_id"],
                    "corporate_action_count": row["corporate_action_count"],
                    "corporate_action_ids": row["corporate_action_ids"],
                    "share_multiplier": row["share_multiplier"],
                    "cash_per_share": row["cash_per_share"],
                    "state_version": state_version,
                    "config_sha256": meta["config_sha256"],
                    "code_sha256": meta["code_sha256"],
                    "chip_input_valid": strict_input_valid,
                    "daily_hard_valid": bool(row["daily_hard_valid"]),
                    "minute_hard_valid": minute_valid,
                    "minute_requirement_waived": int(row["trade_status"]) == 0,
                    "state_chain_valid": True,
                    "warmup_count": warmup_count,
                    "strict_sample": strict,
                    "research_sample": research,
                    "daily_research_sample": daily_research,
                    "research_suspension_bridge": bool(
                        research_relaxed
                        and not bool(row["bar_valid"])
                        and _is_suspended(row["trade_status"])
                    ),
                    "invalid_reason": (
                        None
                        if strict
                        else (
                            "RESEARCH_RELAXED_INPUT"
                            if research_relaxed and not strict_input_valid
                            else "WARMUP_OR_STRICT_INPUT_INVALID"
                        )
                    ),
                    "degraded_mode": state.degraded_mode,
                    "source_mode": (
                        "MINUTE_OBSERVED"
                        if minute_valid
                        else "SYNTHETIC_DAILY_FALLBACK"
                    ),
                    "action_blocking": state.action_blocking,
                    "action_provenance": row["corporate_action_ids"],
                    "mass_sum": state.mass_sum,
                    "state_quality": features.quality,
                    "known_cost_fraction_min": 1.0,
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
                    "base_retention": i90_retained if semantic_v3 else retained,
                    "peak_count": len(features.peaks),
                    "dominant_peak_today": (
                        dominant_peak.center_price if dominant_peak is not None else None
                    ),
                    "dominant_peak_ambiguous": (
                        True if dominant_peak is None else dominant_peak.ambiguity
                    ),
                    "tracked_base_peak": (
                        tracked_base_peak.center_price
                        if tracked_base_peak is not None
                        else None
                    ),
                    "peak_track_id": (
                        tracked_base_peak.peak_track_id
                        if tracked_base_peak is not None
                        else None
                    ),
                    "peak_track_age": (
                        tracked_base_peak.age if tracked_base_peak is not None else None
                    ),
                    "peak_track_band_lower": (
                        tracked_base_peak.band[0]
                        if tracked_base_peak is not None
                        else None
                    ),
                    "peak_track_band_upper": (
                        tracked_base_peak.band[1]
                        if tracked_base_peak is not None
                        else None
                    ),
                    "peak_track_mass": (
                        tracked_base_peak.mass if tracked_base_peak is not None else None
                    ),
                    "peak_track_prominence": (
                        tracked_base_peak.prominence
                        if tracked_base_peak is not None
                        else None
                    ),
                    "peak_track_ambiguous": tracked_base_peak is None,
                    "peak_track_split": (
                        tracked_base_peak.split if tracked_base_peak is not None else False
                    ),
                    "peak_track_merge": (
                        tracked_base_peak.merge if tracked_base_peak is not None else False
                    ),
                    "peak_track_lost": tracked_base_peak is None,
                    "peak_fail_closed_reason": peak_tracking.fail_closed_reason,
                    "peak_definition_version": (
                        dominant_peak.definition_version
                        if dominant_peak is not None
                        else None
                    ),
                    "peaks_json": json.dumps(
                        [
                            {
                                "center_bucket": peak.center_bucket,
                                "center_price": peak.center_price,
                                "lower_bucket": peak.lower_bucket,
                                "lower_price": peak.lower_price,
                                "upper_bucket": peak.upper_bucket,
                                "upper_price": peak.upper_price,
                                "mass": peak.mass,
                                "prominence": peak.prominence,
                                "width_pct": peak.width_pct,
                                "age_mean": peak.age_mean,
                                "formation_date": peak.formation_date,
                                "definition_version": peak.definition_version,
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
                if semantic_v3:
                    assert intervals is not None
                    result.update(
                        {
                            "semantic_version": "semantic-v4",
                            "p05": intervals["p05"],
                            "p15": intervals["p15"],
                            "p85": intervals["p85"],
                            "p95": intervals["p95"],
                            "i90_lower": intervals["i90_lower"],
                            "i90_upper": intervals["i90_upper"],
                            "i90_width_pct": intervals["i90_width_pct"],
                            "i70_lower": intervals["i70_lower"],
                            "i70_upper": intervals["i70_upper"],
                            "i70_width_pct": intervals["i70_width_pct"],
                            "i90_base_retention": i90_retained,
                            "i70_base_retention": i70_retained,
                            "migration_mass": (
                                migration_mass(previous_state, state)
                                if previous_state is not None
                                else None
                            ),
                            "average_cost_delta": (
                                state.average_cost - previous_state.average_cost
                                if previous_state is not None
                                else None
                            ),
                            "upper_peak_center": (
                                upper_peak.center_price if upper_peak is not None else None
                            ),
                            "upper_peak_mass": upper_peak.mass if upper_peak is not None else None,
                            "upper_peak_lower": (
                                upper_peak.lower_price if upper_peak is not None else None
                            ),
                            "upper_peak_upper": (
                                upper_peak.upper_price if upper_peak is not None else None
                            ),
                            "upper_peak_prominence": (
                                upper_peak.prominence if upper_peak is not None else None
                            ),
                            "peaks_price_json": json.dumps(
                                [
                                    {
                                        "center_price": peak.center_price,
                                        "mass": peak.mass,
                                        "lower_price": peak.lower_price,
                                        "upper_price": peak.upper_price,
                                        "width_pct": peak.width_pct,
                                        "prominence": peak.prominence,
                                        "age_mean": peak.age_mean,
                                        "formation_date": peak.formation_date,
                                    }
                                    for peak in price_peaks
                                ],
                                separators=(",", ":"),
                            ),
                        }
                    )
                buffered.append(result)
                row_count += 1
                strict_count += int(strict)
                if len(buffered) >= IO_BATCH_ROWS:
                    _flush(writer, buffered, schema)
        _flush(writer, buffered, schema)
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
        "--industry-fallback",
        default=str(ROOT / "data/processed/research_industry_fallback_2018_2026/data.parquet"),
        help="Research-only industry fallback overlay; canonical industry flags are unchanged.",
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
    parser.add_argument(
        "--research-relaxed",
        action="store_true",
        help="Continue state generation with usable PIT daily bars when auxiliary strict flags fail; never marks strict_sample true.",
    )
    parser.add_argument(
        "--semantic-v3",
        action="store_true",
        help="Emit semantic chip intervals, migration, and peak fields (v4 cash-rebased; flag retained for CLI compatibility).",
    )
    args = parser.parse_args()
    if args.buckets <= 0 or args.workers <= 0:
        parser.error("buckets and workers must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    state_version = SEMANTIC_STATE_VERSION if args.semantic_v3 else STATE_VERSION
    config_hash, code_hash = _fingerprints(args.config)
    meta = {"config_sha256": config_hash, "code_sha256": code_hash}
    fingerprint = {
        **semantic_fingerprint_fields(),
        **meta,
        "state_version": state_version,
        "daily": args.daily,
        "minute": args.minute,
        "industry_fallback": args.industry_fallback,
        "buckets": args.buckets,
        "start": args.start.isoformat() if args.start else None,
        "end": args.end.isoformat() if args.end else None,
        "symbol_limit": args.symbol_limit,
        "research_relaxed": args.research_relaxed,
        "semantic_v3": args.semantic_v3,
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
        args.industry_fallback,
        fingerprint,
    )
    config = load_config(args.config).chip
    chip_values = asdict(config)
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=min(args.workers, args.buckets)) as pool:
        futures = [
            pool.submit(
                _process_bucket,
                bucket,
                str(args.output),
                chip_values,
                meta,
                args.research_relaxed,
                args.semantic_v3,
            )
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
