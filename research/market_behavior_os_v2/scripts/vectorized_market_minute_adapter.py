#!/usr/bin/env python3
"""Vectorized, fail-closed adapter for governed A-share minute sessions.

The adapter computes the exact 34 same-session descriptors accepted by the
Research OS reference.  It never compares raw prices across sessions and never
uses a Python loop over source minute rows or security sessions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import resource
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
LEGACY_SCRIPTS = ROOT / "research/chinext_v1/research_os_v2/scripts"
if str(LEGACY_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(LEGACY_SCRIPTS))

from audit_five_day_minute_data import DESCRIPTOR_COLUMNS  # noqa: E402


SPEC_PATH = PROGRAM / "experiments/MKT-MIN-001_spec.json"
VALIDATION_PATH = PROGRAM / "artifacts/MKT-MIN-001_adapter_validation.json"
SAMPLE_PATH = PROGRAM / "artifacts/AUDIT-MKT-MIN-001_sample.csv"
REFERENCE_DESCRIPTOR_PATH = PROGRAM / "artifacts/AUDIT-MKT-MIN-001_daily_descriptors.csv"

EXPECTED_MINUTES = np.array(
    [9 * 60 + 30]
    + list(range(9 * 60 + 31, 11 * 60 + 31))
    + list(range(13 * 60 + 1, 15 * 60 + 1)),
    dtype=np.int16,
)
RAW_COLUMNS = (
    "symbol",
    "exchange",
    "period",
    "adjust",
    "trade_date",
    "bar_end_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "source",
)
FLOAT_COLUMNS = ("open", "high", "low", "close", "volume", "amount")


class VectorMinuteAdapterError(RuntimeError):
    """Raised when a frozen identity, semantic, or resource gate fails."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def load_frozen_spec() -> dict[str, Any]:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec.get("experiment_id") != "MKT-MIN-001"
        or spec.get("outcome_access") is not False
        or spec.get("status")
        != "FROZEN_BEFORE_OPTIMIZED_IMPLEMENTATION_AND_REQUIRED_SCALE_ACCESS"
    ):
        raise VectorMinuteAdapterError("MKT-MIN-001 is not frozen outcome-blind")
    for role, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise VectorMinuteAdapterError(f"frozen input identity mismatch: {role}")
    reference_hash_keys = {
        "implementation": "sha256",
        "accepted_market_sample": "sample_sha256",
        "accepted_descriptors": "descriptors_sha256",
    }
    for role, hash_key in reference_hash_keys.items():
        path = _resolve(spec["reference"][role])
        expected = spec["reference"][hash_key]
        if not path.is_file() or sha256_file(path) != expected:
            raise VectorMinuteAdapterError(f"frozen reference identity mismatch: {role}")
    return spec


def inventory_files(inventory_path: Path, required: Iterable[str]) -> dict[str, Path]:
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    root = Path(inventory["root"])
    indexed = {item["path"]: item for item in inventory["files"]}
    output: dict[str, Path] = {}
    for relative in required:
        item = indexed.get(relative)
        if item is None:
            raise VectorMinuteAdapterError(f"inventory entry missing: {relative}")
        path = root / relative
        if not path.is_file() or path.stat().st_size != int(item["size"]):
            raise VectorMinuteAdapterError(f"inventory file mismatch: {relative}")
        # Full content hashes are verified once by the stage driver, before any
        # minute access.  Per-date calls never repeat a multi-gigabyte hash.
        output[relative] = path
    return output


def verify_inventory_hashes(inventory_path: Path, required: Iterable[str]) -> None:
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    root = Path(inventory["root"])
    indexed = {item["path"]: item for item in inventory["files"]}
    for relative in required:
        item = indexed[relative]
        path = root / relative
        if sha256_file(path) != item["sha256"]:
            raise VectorMinuteAdapterError(f"inventory content hash mismatch: {relative}")


def _unique_strings(table: pa.Table, column: str) -> set[str]:
    return {str(value) for value in pc.unique(table[column]).to_pylist()}


def read_raw_table(
    path: Path,
    dates: Iterable[date],
    source_symbols: Iterable[str] | None = None,
) -> pa.Table:
    selected_dates = sorted(set(dates))
    if not selected_dates:
        raise VectorMinuteAdapterError("raw read requires at least one date")
    filters: list[tuple[str, str, Any]] = [
        ("trade_date", "in", selected_dates),
        ("exchange", "in", ["SH", "SZ"]),
        ("period", "=", "1m"),
        ("adjust", "=", "none"),
    ]
    if source_symbols is not None:
        symbols = sorted(set(source_symbols))
        if not symbols:
            raise VectorMinuteAdapterError("symbol-pruned read received no symbols")
        filters.append(("symbol", "in", symbols))
    table = pq.read_table(
        path,
        columns=list(RAW_COLUMNS),
        filters=filters,
        use_threads=False,
        pre_buffer=True,
    )
    if table.num_rows == 0:
        raise VectorMinuteAdapterError(f"raw predicate returned no rows: {path.name}")
    return table


def _longest_true_run(mask: np.ndarray) -> np.ndarray:
    current = np.zeros(mask.shape[0], dtype=np.int16)
    longest = np.zeros(mask.shape[0], dtype=np.int16)
    # The fixed 240-column loop is vectorized across every session.  There is no
    # Python loop over source rows or session groups.
    for column in range(mask.shape[1]):
        current = np.where(mask[:, column], current + 1, 0)
        longest = np.maximum(longest, current)
    return longest


def _numeric_column(table: pa.Table, name: str) -> np.ndarray:
    values = table[name].combine_chunks().to_numpy(zero_copy_only=False)
    return np.asarray(values, dtype=np.float64)


def vectorized_session_descriptors(
    table: pa.Table,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Validate raw sessions and compute the frozen descriptors in bulk."""

    missing = sorted(set(RAW_COLUMNS) - set(table.column_names))
    if missing:
        raise VectorMinuteAdapterError(f"raw columns missing: {missing}")
    if _unique_strings(table, "period") != {"1m"}:
        raise VectorMinuteAdapterError("non-1m raw row entered adapter")
    if _unique_strings(table, "adjust") != {"none"}:
        raise VectorMinuteAdapterError("adjusted raw row entered adapter")
    if not _unique_strings(table, "exchange").issubset({"SH", "SZ"}):
        raise VectorMinuteAdapterError("unsupported exchange entered adapter")
    if any(table[name].null_count for name in RAW_COLUMNS):
        raise VectorMinuteAdapterError("required raw null entered adapter")

    row_count = table.num_rows
    symbols = table["symbol"].combine_chunks()
    trade_dates = table["trade_date"].combine_chunks()
    if row_count == 1:
        same_key = np.empty(0, dtype=bool)
    else:
        same_key = np.asarray(
            pc.and_(
                pc.equal(symbols.slice(1), symbols.slice(0, row_count - 1)),
                pc.equal(trade_dates.slice(1), trade_dates.slice(0, row_count - 1)),
            ).to_numpy(zero_copy_only=False),
            dtype=bool,
        )
    starts = np.r_[0, np.flatnonzero(~same_key) + 1].astype(np.int64)
    counts = np.diff(np.r_[starts, row_count]).astype(np.int32)
    group_count = len(starts)
    positions = np.arange(row_count, dtype=np.int32) - np.repeat(starts, counts)

    timestamps = table["bar_end_time"].combine_chunks().to_numpy(zero_copy_only=False)
    timestamps = np.asarray(timestamps).astype("datetime64[ns]")
    minute_of_day = (
        timestamps.astype("datetime64[m]").astype(np.int64) % (24 * 60)
    ).astype(np.int16)
    expected_for_row = EXPECTED_MINUTES[np.minimum(positions, 240)]
    row_time_ok = (positions < 241) & (minute_of_day == expected_for_row)
    timestamp_day = timestamps.astype("datetime64[D]").astype(np.int64)
    source_day = np.asarray(
        trade_dates.to_numpy(zero_copy_only=False)
    ).astype("datetime64[D]").astype(np.int64)
    row_time_ok &= timestamp_day == source_day
    group_time_ok = np.logical_and.reduceat(row_time_ok, starts)

    numeric = {name: _numeric_column(table, name) for name in FLOAT_COLUMNS}
    finite = np.ones(row_count, dtype=bool)
    for values in numeric.values():
        finite &= np.isfinite(values)
    finite &= (
        (numeric["open"] > 0)
        & (numeric["high"] > 0)
        & (numeric["low"] > 0)
        & (numeric["close"] > 0)
        & (numeric["volume"] >= 0)
        & (numeric["amount"] >= 0)
        & (numeric["high"] >= np.maximum(numeric["open"], numeric["close"]))
        & (numeric["low"] <= np.minimum(numeric["open"], numeric["close"]))
        & (numeric["high"] >= numeric["low"])
    )
    group_numeric_ok = np.logical_and.reduceat(finite, starts)
    valid_group = (counts == 241) & group_time_ok & group_numeric_ok

    group_symbols = np.asarray(symbols.take(pa.array(starts)).to_pylist(), dtype=object)
    group_dates = pd.to_datetime(trade_dates.take(pa.array(starts)).to_pylist())
    group_exchanges = np.asarray(
        table["exchange"].combine_chunks().take(pa.array(starts)).to_pylist(),
        dtype=object,
    )
    suffixed_symbols = np.char.add(
        group_symbols.astype(str), np.where(group_exchanges == "SH", ".SH", ".SZ")
    )
    key_frame = pd.DataFrame({"symbol": suffixed_symbols, "trade_date": group_dates})
    if key_frame.duplicated(["symbol", "trade_date"]).any():
        raise VectorMinuteAdapterError("noncontiguous duplicate session key")

    selected_rows = np.repeat(valid_group, counts)
    valid_count = int(valid_group.sum())
    if valid_count == 0:
        return (
            pd.DataFrame(columns=["symbol", "trade_date", *DESCRIPTOR_COLUMNS]),
            pd.DataFrame(columns=["symbol", "trade_date", "window_index", *FLOAT_COLUMNS]),
            {
                "raw_rows": int(row_count),
                "raw_sessions": int(group_count),
                "valid_grid_sessions": 0,
                "invalid_grid_sessions": int((counts != 241).sum() + ((counts == 241) & ~group_time_ok).sum()),
                "invalid_numeric_sessions": int((~group_numeric_ok).sum()),
                "descriptor_sessions": 0,
                "maximum_five_minute_volume_conservation_difference": None,
                "maximum_five_minute_amount_conservation_difference": None,
            },
        )

    arrays = {
        name: values[selected_rows].reshape(valid_count, 241)
        for name, values in numeric.items()
    }
    auction_close = arrays["close"][:, 0]
    open_continuous = arrays["open"][:, 1:]
    high = arrays["high"][:, 1:]
    low = arrays["low"][:, 1:]
    close = arrays["close"][:, 1:]
    volume = arrays["volume"][:, 1:]
    amount = arrays["amount"][:, 1:]
    open_price = open_continuous[:, 0]

    with np.errstate(divide="ignore", invalid="ignore"):
        minute_start = np.concatenate([open_price[:, None], close[:, :-1]], axis=1)
        minute_returns = np.log(close / minute_start)
        log_close = np.log(close)
        path_length = np.abs(
            np.diff(np.concatenate([np.log(open_price)[:, None], log_close], axis=1), axis=1)
        ).sum(axis=1)
        open_close = log_close[:, -1] - np.log(open_price)
        signed_efficiency = np.divide(
            open_close,
            path_length,
            out=np.zeros_like(open_close),
            where=path_length > 0,
        )
        x = np.arange(240, dtype=np.float64)
        x_centered = x - x.mean()
        y_centered = log_close - log_close.mean(axis=1, keepdims=True)
        correlation_denominator = np.sqrt(
            np.square(x_centered).sum() * np.square(y_centered).sum(axis=1)
        )
        correlation = np.divide(
            (y_centered * x_centered).sum(axis=1),
            correlation_denominator,
            out=np.zeros(valid_count, dtype=np.float64),
            where=correlation_denominator > 0,
        )
        path_r2 = np.square(correlation)

        total_volume = volume.sum(axis=1)
        total_amount = amount.sum(axis=1)
        session_vwap = total_amount / total_volume
        above_vwap = close > session_vwap[:, None]
        below_vwap = close < session_vwap[:, None]
        positive = minute_returns > 0
        negative = minute_returns < 0
        first_half_vwap = amount[:, :120].sum(axis=1) / volume[:, :120].sum(axis=1)
        second_half_vwap = amount[:, 120:].sum(axis=1) / volume[:, 120:].sum(axis=1)
        range_low = low.min(axis=1)
        range_high = high.max(axis=1)
        low_index = low.argmin(axis=1)
        bars_remaining = np.maximum(1, 239 - low_index)
        close_location = np.divide(
            close[:, -1] - range_low,
            range_high - range_low,
            out=np.full(valid_count, 0.5, dtype=np.float64),
            where=range_high > range_low,
        )
        previous_high = np.empty_like(high)
        previous_high[:, 0] = -np.inf
        previous_high[:, 1:] = np.maximum.accumulate(high[:, :-1], axis=1)
        new_high = high > previous_high
        volume_weights = volume / total_volume[:, None]

        descriptor_values: dict[str, np.ndarray] = {
            "open_close_log_return": open_close,
            "morning_log_return": np.log(close[:, 119] / open_price),
            "afternoon_log_return": np.log(close[:, -1] / open_continuous[:, 120]),
            "final30_log_return": np.log(close[:, -1] / open_continuous[:, 210]),
            "high_time_fraction": (high.argmax(axis=1) + 1) / 240,
            "low_time_fraction": (low_index + 1) / 240,
            "close_location": close_location,
            "signed_directional_efficiency": signed_efficiency,
            "path_r2": path_r2,
            "close_vs_vwap_log": np.log(close[:, -1] / session_vwap),
            "time_above_vwap_fraction": above_vwap.mean(axis=1),
            "volume_above_vwap_fraction": np.where(
                above_vwap, volume, 0.0
            ).sum(axis=1) / total_volume,
            "vwap_halfday_log_slope": np.log(second_half_vwap / first_half_vwap),
            "vwap_recovery_count": (
                above_vwap[:, 1:] & ~above_vwap[:, :-1]
            ).sum(axis=1),
            "longest_below_vwap_fraction": _longest_true_run(below_vwap) / 240,
            "late_vwap_acceptance_fraction": above_vwap[:, -30:].mean(axis=1),
            "downside_excursion": np.maximum(0.0, -np.log(range_low / open_price)),
            "downside_realized_volatility": np.sqrt(
                np.square(np.minimum(minute_returns, 0.0)).mean(axis=1)
            ),
            "down_minute_volume_share": np.where(negative, volume, 0.0).sum(axis=1)
            / total_volume,
            "selloff_duration_fraction": _longest_true_run(negative) / 240,
            "recovery_speed_30bar": np.log(close[:, -1] / range_low)
            * 30
            / bars_remaining,
            "upside_excursion": np.maximum(0.0, np.log(range_high / open_price)),
            "up_minute_volume_share": np.where(positive, volume, 0.0).sum(axis=1)
            / total_volume,
            "positive_minute_fraction": positive.mean(axis=1),
            "new_intraday_high_fraction": new_high.mean(axis=1),
            "intraday_log_range": np.log(range_high / range_low),
            "minute_realized_volatility": minute_returns.std(axis=1, ddof=1),
            "vwap_deviation_std": np.log(close / session_vwap[:, None]).std(
                axis=1, ddof=1
            ),
            "vwap_crossing_fraction": (
                above_vwap[:, 1:] != above_vwap[:, :-1]
            ).sum(axis=1)
            / 239,
            "opening30_volume_share": volume[:, :30].sum(axis=1) / total_volume,
            "afternoon_volume_share": volume[:, 120:].sum(axis=1) / total_volume,
            "closing30_volume_share": volume[:, -30:].sum(axis=1) / total_volume,
            "minute_volume_concentration": np.square(volume_weights).sum(axis=1),
            "auction_to_continuous_open_log_return": np.log(open_price / auction_close),
        }

    if tuple(descriptor_values) != tuple(DESCRIPTOR_COLUMNS):
        raise VectorMinuteAdapterError("descriptor order differs from frozen reference")
    descriptor_matrix = np.column_stack(
        [descriptor_values[name] for name in DESCRIPTOR_COLUMNS]
    ).astype(np.float64)
    descriptor_valid = np.isfinite(descriptor_matrix).all(axis=1)

    five_volume = volume.reshape(valid_count, 48, 5).sum(axis=2)
    five_amount = amount.reshape(valid_count, 48, 5).sum(axis=2)
    volume_difference = np.abs(five_volume.sum(axis=1) - total_volume)
    amount_difference = np.abs(five_amount.sum(axis=1) - total_amount)
    if np.any(volume_difference != 0.0) or np.any(amount_difference != 0.0):
        first = int(np.flatnonzero((volume_difference != 0) | (amount_difference != 0))[0])
        raise VectorMinuteAdapterError(
            "exact five-minute conservation failure at vector session "
            f"{first}: volume={volume_difference[first]!r}, amount={amount_difference[first]!r}"
        )

    valid_keys = key_frame.loc[valid_group].reset_index(drop=True)
    descriptors = valid_keys.loc[descriptor_valid].reset_index(drop=True)
    descriptor_matrix = descriptor_matrix[descriptor_valid]
    for index, name in enumerate(DESCRIPTOR_COLUMNS):
        descriptors[name] = descriptor_matrix[:, index]
    descriptors["feature_available_at"] = (
        pd.to_datetime(descriptors.trade_date) + pd.Timedelta(hours=15, minutes=30)
    )

    valid_opening_keys = valid_keys.loc[descriptor_valid].reset_index(drop=True)
    opening_index = np.repeat(np.arange(6, dtype=np.int16)[None, :], len(valid_opening_keys), axis=0)
    opening = pd.DataFrame(
        {
            "symbol": np.repeat(valid_opening_keys.symbol.to_numpy(), 6),
            "trade_date": np.repeat(valid_opening_keys.trade_date.to_numpy(), 6),
            "window_index": opening_index.ravel(),
            "open": open_continuous[descriptor_valid, :30].reshape(-1, 5)[:, 0],
            "high": high[descriptor_valid, :30].reshape(-1, 5).max(axis=1),
            "low": low[descriptor_valid, :30].reshape(-1, 5).min(axis=1),
            "close": close[descriptor_valid, :30].reshape(-1, 5)[:, -1],
            "volume": five_volume[descriptor_valid, :6].ravel(),
            "amount": five_amount[descriptor_valid, :6].ravel(),
        }
    )

    audit = {
        "raw_rows": int(row_count),
        "raw_sessions": int(group_count),
        "valid_grid_sessions": int(valid_group.sum()),
        "invalid_grid_sessions": int(
            (counts != 241).sum() + ((counts == 241) & ~group_time_ok).sum()
        ),
        "invalid_numeric_sessions": int((~group_numeric_ok).sum()),
        "nonfinite_descriptor_sessions": int((~descriptor_valid).sum()),
        "descriptor_sessions": int(len(descriptors)),
        "maximum_five_minute_volume_conservation_difference": float(volume_difference.max()),
        "maximum_five_minute_amount_conservation_difference": float(amount_difference.max()),
    }
    return descriptors, opening, audit


def _max_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def stable_frame_sha256(frame: pd.DataFrame, columns: list[str]) -> str:
    working = frame[columns].copy()
    for name in columns:
        if pd.api.types.is_datetime64_any_dtype(working[name]):
            working[name] = pd.to_datetime(working[name]).dt.strftime("%Y-%m-%dT%H:%M:%S")
    payload = working.to_csv(
        index=False, float_format="%.17g", lineterminator="\n"
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _reference_targets(limit: int | None = None) -> pd.DataFrame:
    sample = pd.read_csv(SAMPLE_PATH, dtype={"symbol": str, "source_symbol": str})
    sample["trade_date"] = pd.to_datetime(sample.trade_date, errors="raise")
    unique = (
        sample[["symbol", "source_symbol", "trade_date", "target_year"]]
        .drop_duplicates(["symbol", "trade_date"])
        .sort_values(["trade_date", "symbol"])
        .reset_index(drop=True)
    )
    return unique if limit is None else unique.iloc[:limit].copy()


def _opening_reference(
    path: Path, targets: pd.DataFrame
) -> pd.DataFrame:
    dates = sorted(targets.trade_date.dt.date.unique())
    symbols = sorted(targets.symbol.unique())
    columns = [
        "symbol",
        "trade_date",
        "window_index",
        "available_at",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "market_rule_valid",
        "causal_inputs_valid",
        "source_resolution_minutes",
        "minute_count",
        "distinct_minute_count",
        "hard_valid",
    ]
    frame = pq.read_table(
        path,
        columns=columns,
        filters=[("trade_date", "in", dates), ("symbol", "in", symbols)],
        use_threads=False,
    ).to_pandas()
    frame["trade_date"] = pd.to_datetime(frame.trade_date, errors="raise")
    frame = frame.merge(targets[["symbol", "trade_date"]], on=["symbol", "trade_date"])
    checks = (
        frame.hard_valid.astype(bool)
        & frame.market_rule_valid.astype(bool)
        & frame.causal_inputs_valid.astype(bool)
        & frame.source_resolution_minutes.astype(int).eq(1)
        & frame.minute_count.astype(int).eq(5)
        & frame.distinct_minute_count.astype(int).eq(5)
        & (
            pd.to_datetime(frame.available_at)
            <= frame.trade_date + pd.Timedelta(hours=10)
        )
    )
    if not checks.all():
        raise VectorMinuteAdapterError("CY-008 opening causal gate failed")
    return frame.sort_values(["symbol", "trade_date", "window_index"])


def _validate_daily_context(
    cy006_path: Path,
    cy008_daily_path: Path,
    targets: pd.DataFrame,
) -> dict[str, int]:
    dates = sorted(targets.trade_date.dt.date.unique())
    symbols = sorted(targets.symbol.unique())
    key_columns = ["symbol", "trade_date"]
    cy6_columns = [
        *key_columns,
        "hard_valid",
        "bar_valid",
        "trading_state_valid",
        "corporate_action_valid",
        "market_rule_valid",
        "historical_identity_valid",
        "corporate_action_blocking",
        "corporate_action_count",
        "available_at",
        "decision_at",
        "close",
        "volume",
        "trade_status",
        "current_day_data_tradable",
        "snapshot_id",
    ]
    cy8_columns = [
        *key_columns,
        "available_at",
        "minute_count",
        "distinct_minute_count",
        "source_resolution_minutes",
        "session_complete",
        "ohlc_valid",
        "unit_valid",
        "volume_reconciled",
        "amount_reconciled",
        "daily_hard_valid",
        "hard_valid",
        "snapshot_id",
        "daily_snapshot_id",
    ]
    filters = [("trade_date", "in", dates), ("symbol", "in", symbols)]
    cy6 = pq.read_table(
        cy006_path, columns=cy6_columns, filters=filters, use_threads=False
    ).to_pandas()
    cy8 = pq.read_table(
        cy008_daily_path, columns=cy8_columns, filters=filters, use_threads=False
    ).to_pandas()
    for frame in (cy6, cy8):
        frame["trade_date"] = pd.to_datetime(frame.trade_date, errors="raise")
    keys = targets[key_columns].drop_duplicates()
    cy6 = cy6.merge(keys, on=key_columns, validate="one_to_one")
    cy8 = cy8.merge(keys, on=key_columns, validate="one_to_one")
    if len(cy6) != len(keys) or len(cy8) != len(keys):
        raise VectorMinuteAdapterError("daily causal context coverage differs from targets")
    cy6_gate = (
        cy6.hard_valid.astype(bool)
        & cy6.bar_valid.astype(bool)
        & cy6.trading_state_valid.astype(bool)
        & cy6.corporate_action_valid.astype(bool)
        & cy6.market_rule_valid.astype(bool)
        & cy6.historical_identity_valid.astype(bool)
        & ~cy6.corporate_action_blocking.astype(bool)
        & (
            pd.to_datetime(cy6.available_at, utc=True)
            <= pd.to_datetime(cy6.decision_at, utc=True)
        )
        & pd.to_numeric(cy6.close, errors="coerce").gt(0)
        & pd.to_numeric(cy6.volume, errors="coerce").gt(0)
        & pd.to_numeric(cy6.trade_status, errors="coerce").eq(1)
        & cy6.current_day_data_tradable.astype(bool)
    )
    expected_available = cy8.trade_date + pd.Timedelta(hours=15, minutes=30)
    cy8_gate = (
        pd.to_datetime(cy8.available_at).eq(expected_available)
        & cy8.minute_count.astype(int).eq(241)
        & cy8.distinct_minute_count.astype(int).eq(241)
        & cy8.source_resolution_minutes.astype(int).eq(1)
        & cy8.session_complete.astype(bool)
        & cy8.ohlc_valid.astype(bool)
        & cy8.unit_valid.astype(bool)
        & cy8.volume_reconciled.astype(bool)
        & cy8.amount_reconciled.astype(bool)
        & cy8.daily_hard_valid.astype(bool)
        & cy8.hard_valid.astype(bool)
    )
    if not cy6_gate.all() or not cy8_gate.all():
        raise VectorMinuteAdapterError("daily causal hard-valid gate failed")
    lineage = cy8[key_columns + ["daily_snapshot_id"]].merge(
        cy6[key_columns + ["snapshot_id"]], on=key_columns, validate="one_to_one"
    )
    if not lineage.daily_snapshot_id.eq(lineage.snapshot_id).all():
        raise VectorMinuteAdapterError("CY-006/CY-008 snapshot binding failed")
    return {
        "daily_context_sessions": int(len(keys)),
        "causal_corporate_action_sessions": int(
            pd.to_numeric(cy6.corporate_action_count, errors="raise").gt(0).sum()
        ),
    }


def validate_reference(stage: str) -> dict[str, Any]:
    if stage not in {"tiny", "small"}:
        raise VectorMinuteAdapterError(f"unsupported reference stage: {stage}")
    spec = load_frozen_spec()
    targets = _reference_targets(10 if stage == "tiny" else None)
    years = sorted(targets.target_year.astype(int).unique())
    qd_required = [f"bars/{year}_day_parquet_none.parquet" for year in years]
    cy6_required = [f"partition_year={year}/data_0.parquet" for year in years]
    cy8_required = [
        relative
        for year in years
        for relative in (
            f"daily/partition_year={year}/data_0.parquet",
            f"execution_5m/partition_year={year}/data_0.parquet",
        )
    ]
    qd_inventory = _resolve(spec["inputs"]["qd004_inventory"]["path"])
    cy6_inventory = _resolve(spec["inputs"]["cy006_inventory"]["path"])
    cy8_inventory = _resolve(spec["inputs"]["cy008_inventory"]["path"])
    qd = inventory_files(qd_inventory, qd_required)
    cy6 = inventory_files(cy6_inventory, cy6_required)
    cy8 = inventory_files(cy8_inventory, cy8_required)
    verify_inventory_hashes(qd_inventory, qd_required)
    verify_inventory_hashes(cy6_inventory, cy6_required)
    verify_inventory_hashes(cy8_inventory, cy8_required)

    started = time.perf_counter()
    descriptor_frames: list[pd.DataFrame] = []
    opening_frames: list[pd.DataFrame] = []
    audits: list[dict[str, Any]] = []
    context_audits: list[dict[str, int]] = []
    opening_reference_frames: list[pd.DataFrame] = []
    for year in years:
        year_targets = targets.loc[targets.target_year.astype(int) == year]
        raw = read_raw_table(
            qd[f"bars/{year}_day_parquet_none.parquet"],
            year_targets.trade_date.dt.date,
            year_targets.source_symbol,
        )
        descriptors, opening, audit = vectorized_session_descriptors(raw)
        keys = year_targets[["symbol", "trade_date"]]
        descriptor_frames.append(descriptors.merge(keys, on=["symbol", "trade_date"]))
        opening_frames.append(opening.merge(keys, on=["symbol", "trade_date"]))
        opening_reference_frames.append(
            _opening_reference(
                cy8[f"execution_5m/partition_year={year}/data_0.parquet"], year_targets
            )
        )
        context_audits.append(
            _validate_daily_context(
                cy6[f"partition_year={year}/data_0.parquet"],
                cy8[f"daily/partition_year={year}/data_0.parquet"],
                year_targets,
            )
        )
        audits.append(audit)

    actual = pd.concat(descriptor_frames, ignore_index=True).sort_values(
        ["symbol", "trade_date"]
    )
    expected = pd.read_csv(REFERENCE_DESCRIPTOR_PATH, dtype={"symbol": str})
    expected["trade_date"] = pd.to_datetime(expected.trade_date, errors="raise")
    expected = expected.merge(targets[["symbol", "trade_date"]], on=["symbol", "trade_date"])
    duplicate_spread = expected.groupby(["symbol", "trade_date"])[list(DESCRIPTOR_COLUMNS)].nunique()
    if (duplicate_spread > 1).any().any():
        raise VectorMinuteAdapterError("accepted mapped descriptors disagree for a source session")
    expected = expected.drop_duplicates(["symbol", "trade_date"]).sort_values(
        ["symbol", "trade_date"]
    )
    if actual[["symbol", "trade_date"]].reset_index(drop=True).equals(
        expected[["symbol", "trade_date"]].reset_index(drop=True)
    ) is False:
        raise VectorMinuteAdapterError("optimized/reference session keys disagree")
    actual_values = actual[list(DESCRIPTOR_COLUMNS)].to_numpy(float)
    expected_values = expected[list(DESCRIPTOR_COLUMNS)].to_numpy(float)
    differences = np.abs(actual_values - expected_values)
    tolerances = 1e-12 + 1e-12 * np.abs(expected_values)
    if np.any(differences > tolerances):
        row, column = np.argwhere(differences > tolerances)[0]
        raise VectorMinuteAdapterError(
            "optimized/reference descriptor disagreement: "
            f"{DESCRIPTOR_COLUMNS[column]} expected={expected_values[row, column]!r} "
            f"actual={actual_values[row, column]!r} diff={differences[row, column]!r}"
        )

    actual_opening = pd.concat(opening_frames, ignore_index=True).sort_values(
        ["symbol", "trade_date", "window_index"]
    )
    expected_opening = pd.concat(opening_reference_frames, ignore_index=True).sort_values(
        ["symbol", "trade_date", "window_index"]
    )
    opening_keys = ["symbol", "trade_date", "window_index"]
    actual_opening_keys = actual_opening[opening_keys].reset_index(drop=True).copy()
    expected_opening_keys = expected_opening[opening_keys].reset_index(drop=True).copy()
    actual_opening_keys["window_index"] = actual_opening_keys.window_index.astype(int)
    expected_opening_keys["window_index"] = expected_opening_keys.window_index.astype(int)
    if not actual_opening_keys.equals(expected_opening_keys):
        raise VectorMinuteAdapterError("optimized/CY-008 opening keys disagree")
    opening_columns = list(FLOAT_COLUMNS)
    opening_actual_values = actual_opening[opening_columns].to_numpy(float)
    opening_expected_values = expected_opening[opening_columns].to_numpy(float)
    opening_scale = np.maximum(1.0, np.abs(opening_expected_values))
    opening_relative = np.abs(opening_actual_values - opening_expected_values) / opening_scale
    if np.any(opening_relative > 1e-12):
        row, column = np.argwhere(opening_relative > 1e-12)[0]
        raise VectorMinuteAdapterError(
            f"optimized/CY-008 opening disagreement: {opening_columns[column]} "
            f"relative={opening_relative[row, column]!r}"
        )

    result = {
        "stage": stage,
        "decision": "PASS_OPTIMIZED_REFERENCE_EQUIVALENCE",
        "distinct_source_sessions": int(len(actual)),
        "mapped_reference_sessions": int(len(expected.merge(
            pd.read_csv(SAMPLE_PATH)[["symbol", "trade_date"]].assign(
                trade_date=lambda frame: pd.to_datetime(frame.trade_date)
            ), on=["symbol", "trade_date"]
        ))) if stage == "small" else int(len(actual)),
        "descriptor_count": len(DESCRIPTOR_COLUMNS),
        "daily_context_sessions": int(
            sum(item["daily_context_sessions"] for item in context_audits)
        ),
        "causal_corporate_action_sessions": int(
            sum(item["causal_corporate_action_sessions"] for item in context_audits)
        ),
        "maximum_absolute_descriptor_difference": float(differences.max()),
        "maximum_relative_opening_difference": float(opening_relative.max()),
        "optimized_descriptor_sha256": stable_frame_sha256(
            actual.sort_values(["symbol", "trade_date"]),
            ["symbol", "trade_date", *DESCRIPTOR_COLUMNS],
        ),
        "optimized_opening_sha256": stable_frame_sha256(
            actual_opening.sort_values(["symbol", "trade_date", "window_index"]),
            ["symbol", "trade_date", "window_index", *opening_columns],
        ),
        "raw_rows": int(sum(item["raw_rows"] for item in audits)),
        "maximum_five_minute_volume_conservation_difference": float(max(item["maximum_five_minute_volume_conservation_difference"] for item in audits)),
        "maximum_five_minute_amount_conservation_difference": float(max(item["maximum_five_minute_amount_conservation_difference"] for item in audits)),
        "wall_seconds": time.perf_counter() - started,
        "peak_rss_bytes": _max_rss_bytes(),
        "spec_sha256": sha256_file(SPEC_PATH),
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["tiny", "small"], required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    result = validate_reference(args.stage)
    if args.write:
        VALIDATION_PATH.parent.mkdir(parents=True, exist_ok=True)
        VALIDATION_PATH.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
