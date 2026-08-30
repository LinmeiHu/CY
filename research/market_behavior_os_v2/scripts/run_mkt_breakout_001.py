#!/usr/bin/env python3
"""Construct and compress objective breakout acceptance/rejection roles."""

from __future__ import annotations

import gc
import hashlib
import importlib.util
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psutil
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-BREAKOUT-001_spec.json"
DATA_RUNNER_PATH = PROGRAM / "scripts/run_mkt_breakout_data_001.py"
DATA_AUDIT_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-DATA-001_coordinate_event_audit.csv"
PANEL_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-001_session_panel.csv"
STABILITY_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-001_stability_audit.csv"
GEOMETRY_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-001_geometry_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-BREAKOUT-001_representation.md"
EXPECTED_SPEC_SHA256 = "f314165c8cfaefe9cb0ba761dc8ced6884abd192d36481a8d740f2c0a592821f"


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


data_runner = _load_module("run_mkt_breakout_data_001_for_representation", DATA_RUNNER_PATH)
data003 = data_runner.data003
base = data_runner.base
adapter = data_runner.adapter
sha256_file = data_runner.sha256_file
DEFINITIONS = data_runner.DEFINITIONS


class BreakoutRepresentationError(RuntimeError):
    """Fail-closed MKT-BREAKOUT-001 error."""


ROLE_NAMES = [
    "continuation30_log_return",
    "follow_through_excursion",
    "rejection_depth",
    "below_level_close_fraction",
    "loss_episode_count",
    "reacquisition_bars",
    "closing_acceptance_margin",
    "post_cross_cumulative_vwap_acceptance_fraction",
    "post_cross_activity_ratio",
    "above_level_close_episode_count",
]


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise BreakoutRepresentationError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec["status"] != "FROZEN_BEFORE_POST_CROSS_MAGNITUDE_CONSTRUCTION"
        or spec["outcome_access"] is not False
    ):
        raise BreakoutRepresentationError("experiment activation changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise BreakoutRepresentationError(f"input identity mismatch: {name}")
    if list(spec["roles"]) != ROLE_NAMES:
        raise BreakoutRepresentationError("role order or identity changed")
    if spec["definitions"]["primary"] != "L20_CONTINUOUS":
        raise BreakoutRepresentationError("primary definition changed")
    return spec


def _resource_guard(spec: dict[str, Any], started: float) -> None:
    budget = spec["resource_budget"]
    if psutil.virtual_memory().available < budget["system_memory_headroom_floor_gib"] * 2**30:
        raise BreakoutRepresentationError("system memory headroom floor breached")
    if adapter._max_rss_bytes() > budget["peak_rss_ceiling_gib"] * 2**30:
        raise BreakoutRepresentationError("process RSS ceiling breached")
    if time.monotonic() - started > budget["wall_clock_ceiling_minutes"] * 60:
        raise BreakoutRepresentationError("wall-clock ceiling breached")


def _longest_true_run(values: np.ndarray) -> int:
    best = 0
    current = 0
    for value in np.asarray(values, dtype=bool):
        if bool(value):
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def path_descriptor(
    raw_open: np.ndarray,
    raw_high: np.ndarray,
    raw_low: np.ndarray,
    raw_close: np.ndarray,
    volume: np.ndarray,
    amount: np.ndarray,
    scale: float,
    level: float,
    *,
    include_auction: bool,
) -> dict[str, Any]:
    """Vector path descriptor for one strict-crossing session/definition."""
    start = 0 if include_auction else 1
    open_price = np.asarray(raw_open, float)[start:] * scale
    high = np.asarray(raw_high, float)[start:] * scale
    low = np.asarray(raw_low, float)[start:] * scale
    close = np.asarray(raw_close, float)[start:] * scale
    vol = np.asarray(volume, float)[start:]
    amt = np.asarray(amount, float)[start:]
    crossed = np.flatnonzero(high > level)
    if len(crossed) == 0:
        raise BreakoutRepresentationError("descriptor received non-crossing path")
    first = int(crossed[0])
    remaining = int(len(close) - first - 1)
    post_close = close[first:]
    post_volume = vol[first:]
    strictly_after_high = high[first + 1 :]
    strictly_after_low = low[first + 1 :]
    below = post_close < level
    above = post_close > level
    loss_transitions = int(np.sum((post_close[1:] < level) & (post_close[:-1] >= level)))
    above_episode_count = int(above[0]) + int(np.sum(above[1:] & ~above[:-1]))
    losses = np.flatnonzero(below)
    reacquisition_bars: float | None = None
    reacquired = False
    if len(losses):
        first_loss = int(losses[0])
        later = np.flatnonzero(post_close[first_loss + 1 :] > level)
        if len(later):
            reacquisition_bars = float(int(later[0]) + 1)
            reacquired = True

    total_volume = float(np.sum(vol))
    total_amount = float(np.sum(amt))
    if total_volume <= 0 or total_amount <= 0:
        raise BreakoutRepresentationError("invalid session volume/amount")
    cumulative_volume = np.cumsum(vol)
    cumulative_amount = np.cumsum(amt)
    if np.any(cumulative_volume[first:] <= 0):
        raise BreakoutRepresentationError("nonpositive post-cross cumulative volume")
    cumulative_vwap = (
        np.divide(
            cumulative_amount,
            cumulative_volume,
            out=np.full_like(cumulative_amount, np.nan),
            where=cumulative_volume > 0,
        )
        * scale
    )
    session_vwap = total_amount / total_volume * scale
    minute_start = np.concatenate(([open_price[0]], close[:-1]))
    minute_returns = np.log(close / minute_start)
    session_low = float(np.min(low))
    session_high = float(np.max(high))
    low_index = int(np.argmin(low))
    range_width = session_high - session_low
    close_location = float((close[-1] - session_low) / range_width) if range_width > 0 else 0.5
    volume_weights = vol / total_volume
    above_vwap = close > session_vwap
    below_vwap = close < session_vwap
    bars_from_low = max(1, len(close) - 1 - low_index)
    prior_volume = vol[:first]
    crossing_activity: float | None = None
    if len(prior_volume) and float(np.median(prior_volume)) > 0:
        crossing_activity = float(vol[first] / np.median(prior_volume))

    output: dict[str, Any] = {
        "first_cross_index": first,
        "remaining_bars": remaining,
        "continuation5_log_return": None,
        "continuation15_log_return": None,
        "continuation30_log_return": None,
        "continuation60_log_return": None,
        "follow_through_excursion": None,
        "rejection_depth": None,
        "below_level_close_fraction": float(np.mean(below)),
        "longest_below_level_run_fraction": float(_longest_true_run(below) / len(post_close)),
        "loss_episode_count": float(loss_transitions),
        "reacquisition_bars": reacquisition_bars,
        "closing_acceptance_margin": float(close[-1] / level - 1.0),
        "post_cross_cumulative_vwap_acceptance_fraction": float(
            np.mean(post_close > cumulative_vwap[first:])
        ),
        "final_session_vwap_margin": float(close[-1] / session_vwap - 1.0),
        "post_cross_activity_ratio": float(
            (np.sum(post_volume) / total_volume) / (len(post_volume) / len(vol))
        ),
        "crossing_bar_activity_ratio": crossing_activity,
        "above_level_close_episode_count": float(above_episode_count),
        "first_cross_fraction": float(first / (len(close) - 1)),
        "open_close_log_return": float(np.log(close[-1] / open_price[0])),
        "daily_high_margin": float(session_high / level - 1.0),
        "close_location": close_location,
        "high_time_fraction": float((int(np.argmax(high)) + 1) / len(high)),
        "minute_realized_volatility": float(np.std(minute_returns, ddof=1)),
        "intraday_log_range": float(np.log(session_high / session_low)),
        "minute_volume_concentration": float(np.sum(np.square(volume_weights))),
        "closing30_volume_share": float(np.sum(vol[-30:]) / total_volume),
        "session_vwap_recovery_count": float(np.sum(above_vwap[1:] & ~above_vwap[:-1])),
        "session_longest_below_vwap_fraction": float(_longest_true_run(below_vwap) / len(close)),
        "session_downside_excursion": float(max(0.0, -np.log(session_low / open_price[0]))),
        "session_recovery_speed_30bar": float(np.log(close[-1] / session_low) * 30 / bars_from_low),
        "domain_main": remaining >= 60,
        "domain_closing": True,
        "domain_reacquisition": reacquired,
    }
    for horizon in (5, 15, 30, 60):
        if remaining >= horizon:
            output[f"continuation{horizon}_log_return"] = float(
                np.log(close[first + horizon] / close[first])
            )
    if remaining >= 1:
        output["follow_through_excursion"] = float(np.max(strictly_after_high) / level - 1.0)
        output["rejection_depth"] = float(np.min(strictly_after_low) / level - 1.0)
    numeric = [value for value in output.values() if isinstance(value, float)]
    if any(not np.isfinite(value) for value in numeric):
        raise BreakoutRepresentationError("nonfinite path descriptor")
    return output


def _load_data_audit(spec: dict[str, Any]) -> pd.DataFrame:
    frame = pd.read_csv(
        DATA_AUDIT_PATH,
        dtype={"source_symbol": str},
        float_precision="round_trip",
    )
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise")
    if (
        len(frame) != spec["population"]["expected_cohort_rows"]
        or frame["sequence_id"].nunique() != spec["population"]["expected_sequences"]
        or len(frame[["symbol", "trade_date"]].drop_duplicates())
        != spec["population"]["expected_unique_sessions"]
    ):
        raise BreakoutRepresentationError("bound event population changed")
    return frame.sort_values("audit_id").reset_index(drop=True)


def _case_hash(symbol: str, trade_date: pd.Timestamp) -> str:
    payload = f"MKT-BREAKOUT-001|{symbol}|{trade_date.date()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_event_fields(unique_row: pd.Series, name: str, summary: dict[str, Any]) -> None:
    prefix = name.lower()
    expected = {
        "cross": bool(unique_row[f"{prefix}_cross"]),
        "first_cross_index": (
            None
            if pd.isna(unique_row[f"{prefix}_first_cross_index"])
            else int(unique_row[f"{prefix}_first_cross_index"])
        ),
        "remaining_bars": (
            None
            if pd.isna(unique_row[f"{prefix}_remaining_bars"])
            else int(unique_row[f"{prefix}_remaining_bars"])
        ),
        "closing_state": str(unique_row[f"{prefix}_closing_state"]),
        "close_loss": bool(unique_row[f"{prefix}_close_loss"]),
        "reacquired": bool(unique_row[f"{prefix}_reacquired"]),
    }
    if summary != expected:
        raise BreakoutRepresentationError(
            f"bound event disagreement: {unique_row.symbol}:{unique_row.trade_date}:{name}"
        )


def _construct_panel(
    spec: dict[str, Any],
    audit: pd.DataFrame,
    partitions: dict[str, dict[str, Path]],
    started: float,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    identity_columns = [
        "audit_id",
        "sequence_id",
        "cohort",
        "market_view",
        "symbol",
        "source_symbol",
        "trade_date",
        "target_year",
        "block_id",
        "market_sequence_rank",
        "relative_day",
    ]
    unique = audit.drop_duplicates(["symbol", "trade_date"]).copy()
    unique_index = unique.set_index(["symbol", "trade_date"])
    target_columns = [
        "symbol",
        "source_symbol",
        "trade_date",
        "target_year",
        "block_id",
    ]
    targets_all = unique[target_columns]
    descriptor_records: list[dict[str, Any]] = []
    scalar_candidates: list[dict[str, Any]] = []
    raw_rows_read = 0
    for (raw_year, raw_block), targets in targets_all.groupby(
        ["target_year", "block_id"], sort=True
    ):
        _resource_guard(spec, started)
        year = int(raw_year)
        table = adapter.read_raw_table(
            partitions["qd004"][f"bars/{year}_day_parquet_none.parquet"],
            pd.to_datetime(targets["trade_date"]).dt.date,
            targets["source_symbol"].astype(str),
        )
        try:
            descriptors, opening, vector_audit = adapter.vectorized_session_descriptors(table)
        except adapter.VectorMinuteAdapterError as exc:
            raise BreakoutRepresentationError(str(exc)) from exc
        del descriptors, opening
        raw_rows_read += int(vector_audit["raw_rows"])
        raw = table.to_pandas()
        del table
        raw["trade_date"] = pd.to_datetime(raw["trade_date"], errors="raise")
        raw["symbol"] = raw["symbol"].astype(str).str.zfill(6) + "." + raw["exchange"].astype(str)
        raw = raw.merge(
            targets[["symbol", "trade_date"]],
            on=["symbol", "trade_date"],
            validate="many_to_one",
        )
        cy8_coordinates = unique.loc[
            unique["target_year"].eq(year) & unique["block_id"].eq(raw_block),
            ["symbol", "trade_date", "daily_snapshot_id"],
        ].rename(columns={"daily_snapshot_id": "snapshot_id"})
        try:
            data003._read_and_validate_cy008(year, targets, cy8_coordinates, partitions)
        except data003.SupportDataError as exc:
            raise BreakoutRepresentationError(str(exc)) from exc

        for (symbol, trade_date), rows in raw.groupby(["symbol", "trade_date"], sort=True):
            rows = rows.sort_values("bar_end_time").reset_index(drop=True)
            if len(rows) != 241:
                raise BreakoutRepresentationError("minute grid changed")
            bound = unique_index.loc[(symbol, pd.Timestamp(trade_date))]
            raw_open = rows["open"].to_numpy(float)
            raw_high = rows["high"].to_numpy(float)
            raw_low = rows["low"].to_numpy(float)
            raw_close = rows["close"].to_numpy(float)
            volume = rows["volume"].to_numpy(float)
            amount = rows["amount"].to_numpy(float)
            scale = float(bound.coordinate_scale)
            primary_descriptor: dict[str, Any] | None = None
            for name, (level_field, include_auction) in DEFINITIONS.items():
                level = float(bound[level_field])
                mapped_high = raw_high * scale
                mapped_close = raw_close * scale
                summary = data_runner.event_summary(
                    mapped_high,
                    mapped_close,
                    level,
                    include_auction=include_auction,
                )
                _validate_event_fields(bound, name, summary)
                if not summary["cross"]:
                    continue
                try:
                    descriptor = path_descriptor(
                        raw_open,
                        raw_high,
                        raw_low,
                        raw_close,
                        volume,
                        amount,
                        scale,
                        level,
                        include_auction=include_auction,
                    )
                except BreakoutRepresentationError as exc:
                    raise BreakoutRepresentationError(
                        f"descriptor failure: {symbol}:{trade_date}:{name}: {exc}"
                    ) from exc
                if (
                    descriptor["first_cross_index"] != summary["first_cross_index"]
                    or descriptor["remaining_bars"] != summary["remaining_bars"]
                    or descriptor["domain_reacquisition"] != summary["reacquired"]
                ):
                    raise BreakoutRepresentationError("descriptor/event identity failed")
                descriptor_records.append(
                    {
                        "symbol": symbol,
                        "trade_date": pd.Timestamp(trade_date),
                        "definition": name,
                        "level": level,
                        **descriptor,
                    }
                )
                if name == "L20_CONTINUOUS":
                    primary_descriptor = descriptor
            if (
                primary_descriptor is not None
                and primary_descriptor["domain_main"]
                and primary_descriptor["domain_reacquisition"]
            ):
                scalar_candidates.append(
                    {
                        "selection_hash": _case_hash(symbol, pd.Timestamp(trade_date)),
                        "symbol": symbol,
                        "trade_date": pd.Timestamp(trade_date),
                        "raw_open": raw_open.copy(),
                        "raw_high": raw_high.copy(),
                        "raw_low": raw_low.copy(),
                        "raw_close": raw_close.copy(),
                        "volume": volume.copy(),
                        "amount": amount.copy(),
                        "scale": scale,
                        "level": float(bound.resistance_high20),
                        "vector": primary_descriptor,
                    }
                )
                scalar_candidates.sort(key=lambda item: item["selection_hash"])
                del scalar_candidates[5:]
        del raw, cy8_coordinates
        gc.collect()
        _resource_guard(spec, started)
    if raw_rows_read != spec["population"]["expected_raw_minute_rows"]:
        raise BreakoutRepresentationError("raw row conservation changed")
    unique_descriptors = pd.DataFrame(descriptor_records)
    pieces: list[pd.DataFrame] = []
    for name in DEFINITIONS:
        prefix = name.lower()
        identities = audit.loc[audit[f"{prefix}_cross"].astype(bool), identity_columns]
        descriptors = unique_descriptors.loc[unique_descriptors["definition"].eq(name)]
        piece = identities.merge(
            descriptors,
            on=["symbol", "trade_date"],
            validate="many_to_one",
        )
        pieces.append(piece)
    panel = pd.concat(pieces, ignore_index=True)
    panel["temporal_block"] = np.where(panel["target_year"].le(2020), "A", "B")
    return (
        panel.sort_values(["definition", "audit_id"]).reset_index(drop=True),
        scalar_candidates,
    )


def _scalar_descriptor(case: dict[str, Any]) -> dict[str, Any]:
    """Independent scalar reconstruction; never calls path_descriptor."""
    start = 1
    open_price = [float(value) * case["scale"] for value in case["raw_open"][start:]]
    high = [float(value) * case["scale"] for value in case["raw_high"][start:]]
    low = [float(value) * case["scale"] for value in case["raw_low"][start:]]
    close = [float(value) * case["scale"] for value in case["raw_close"][start:]]
    vol = [float(value) for value in case["volume"][start:]]
    amt = [float(value) for value in case["amount"][start:]]
    level = float(case["level"])
    first = next(index for index, value in enumerate(high) if value > level)
    remaining = len(close) - first - 1
    post_close = close[first:]
    below = [value < level for value in post_close]
    above = [value > level for value in post_close]
    loss_episodes = sum(
        post_close[index] < level and post_close[index - 1] >= level
        for index in range(1, len(post_close))
    )
    above_episodes = int(above[0]) + sum(
        above[index] and not above[index - 1] for index in range(1, len(above))
    )
    first_loss = next(index for index, value in enumerate(below) if value)
    reacq_offset = next(
        index for index, value in enumerate(post_close[first_loss + 1 :], start=1) if value > level
    )
    total_volume = sum(vol)
    total_amount = sum(amt)
    cumulative_volume: list[float] = []
    cumulative_amount: list[float] = []
    running_volume = 0.0
    running_amount = 0.0
    for volume_value, amount_value in zip(vol, amt, strict=True):
        running_volume += volume_value
        running_amount += amount_value
        cumulative_volume.append(running_volume)
        cumulative_amount.append(running_amount)
    cumulative_vwap = [
        amount_value / volume_value * case["scale"]
        for amount_value, volume_value in zip(cumulative_amount, cumulative_volume, strict=True)
    ]
    session_vwap = total_amount / total_volume * case["scale"]
    minute_start = [open_price[0], *close[:-1]]
    minute_returns = [math.log(end / begin) for end, begin in zip(close, minute_start, strict=True)]
    mean_return = sum(minute_returns) / len(minute_returns)
    rv = math.sqrt(
        sum((value - mean_return) ** 2 for value in minute_returns) / (len(minute_returns) - 1)
    )
    session_low = min(low)
    session_high = max(high)
    low_index = low.index(session_low)
    high_index = high.index(session_high)
    close_location = (close[-1] - session_low) / (session_high - session_low)
    weights = [value / total_volume for value in vol]
    above_vwap = [value > session_vwap for value in close]
    below_vwap = [value < session_vwap for value in close]
    prior = vol[:first]
    crossing_activity = None
    if prior:
        ordered = sorted(prior)
        middle = len(ordered) // 2
        prior_median = (
            ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
        )
        if prior_median > 0:
            crossing_activity = vol[first] / prior_median
    return {
        "first_cross_index": first,
        "remaining_bars": remaining,
        "continuation5_log_return": math.log(close[first + 5] / close[first]),
        "continuation15_log_return": math.log(close[first + 15] / close[first]),
        "continuation30_log_return": math.log(close[first + 30] / close[first]),
        "continuation60_log_return": math.log(close[first + 60] / close[first]),
        "follow_through_excursion": max(high[first + 1 :]) / level - 1.0,
        "rejection_depth": min(low[first + 1 :]) / level - 1.0,
        "below_level_close_fraction": sum(below) / len(below),
        "longest_below_level_run_fraction": _longest_true_run(np.array(below)) / len(below),
        "loss_episode_count": float(loss_episodes),
        "reacquisition_bars": float(reacq_offset),
        "closing_acceptance_margin": close[-1] / level - 1.0,
        "post_cross_cumulative_vwap_acceptance_fraction": sum(
            close[index] > cumulative_vwap[index] for index in range(first, len(close))
        )
        / len(post_close),
        "final_session_vwap_margin": close[-1] / session_vwap - 1.0,
        "post_cross_activity_ratio": (sum(vol[first:]) / total_volume)
        / (len(post_close) / len(vol)),
        "crossing_bar_activity_ratio": crossing_activity,
        "above_level_close_episode_count": float(above_episodes),
        "first_cross_fraction": first / (len(close) - 1),
        "open_close_log_return": math.log(close[-1] / open_price[0]),
        "daily_high_margin": session_high / level - 1.0,
        "close_location": close_location,
        "high_time_fraction": (high_index + 1) / len(high),
        "minute_realized_volatility": rv,
        "intraday_log_range": math.log(session_high / session_low),
        "minute_volume_concentration": sum(value**2 for value in weights),
        "closing30_volume_share": sum(vol[-30:]) / total_volume,
        "session_vwap_recovery_count": float(
            sum(
                above_vwap[index] and not above_vwap[index - 1]
                for index in range(1, len(above_vwap))
            )
        ),
        "session_longest_below_vwap_fraction": _longest_true_run(np.array(below_vwap)) / len(close),
        "session_downside_excursion": max(0.0, -math.log(session_low / open_price[0])),
        "session_recovery_speed_30bar": math.log(close[-1] / session_low)
        * 30
        / max(1, len(close) - 1 - low_index),
        "domain_main": True,
        "domain_closing": True,
        "domain_reacquisition": True,
    }


def _verify_scalar_cases(spec: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if len(candidates) != spec["scalar_reconstruction"]["cases"]:
        raise BreakoutRepresentationError("scalar case count changed")
    exact_fields = [
        "first_cross_index",
        "remaining_bars",
        "loss_episode_count",
        "above_level_close_episode_count",
        "reacquisition_bars",
        "domain_main",
        "domain_closing",
        "domain_reacquisition",
    ]
    maximum_difference = 0.0
    records: list[dict[str, Any]] = []
    for case in candidates:
        scalar = _scalar_descriptor(case)
        vector = case["vector"]
        for field in exact_fields:
            if scalar[field] != vector[field]:
                raise BreakoutRepresentationError(f"scalar exact disagreement: {field}")
        for field, scalar_value in scalar.items():
            if field in exact_fields or isinstance(scalar_value, bool):
                continue
            vector_value = vector[field]
            if scalar_value is None and vector_value is None:
                continue
            if scalar_value is None or vector_value is None:
                raise BreakoutRepresentationError(f"scalar missingness disagreement: {field}")
            difference = abs(float(scalar_value) - float(vector_value))
            maximum_difference = max(maximum_difference, difference)
            if difference > spec["scalar_reconstruction"]["maximum_aggregate_absolute_difference"]:
                raise BreakoutRepresentationError(
                    f"scalar aggregate disagreement: {field}:{difference}"
                )
        records.append(
            {
                "selection_hash": case["selection_hash"],
                "symbol": case["symbol"],
                "trade_date": str(case["trade_date"].date()),
                "exact_fields_match": True,
            }
        )
    return {
        "cases": records,
        "maximum_aggregate_absolute_difference": maximum_difference,
    }


def _role_domain(frame: pd.DataFrame, role: str, spec: dict[str, Any]) -> pd.DataFrame:
    domain = spec["roles"][role]["domain"]
    flag = {
        "matched_main_domain": "domain_main",
        "closing_domain": "domain_closing",
        "reacquisition_domain": "domain_reacquisition",
    }[domain]
    output = frame.loc[frame[flag].astype(bool)].copy()
    output[role] = pd.to_numeric(output[role], errors="coerce")
    return output.loc[np.isfinite(output[role])]


def _rho(left: pd.Series, right: pd.Series) -> float:
    if len(left) < 3 or left.nunique() < 2 or right.nunique() < 2:
        return float("nan")
    return float(spearmanr(left.to_numpy(float), right.to_numpy(float)).statistic)


def _sign_agreement(left: pd.Series, right: pd.Series) -> float:
    return float(np.mean(np.sign(left.to_numpy(float)) == np.sign(right.to_numpy(float))))


def _pair_scopes(joined: pd.DataFrame, left: str, right: str) -> list[dict[str, Any]]:
    scopes: list[tuple[str, pd.Series]] = [
        ("GLOBAL", pd.Series(True, index=joined.index)),
        ("BLOCK_A", joined["temporal_block"].eq("A")),
        ("BLOCK_B", joined["temporal_block"].eq("B")),
    ]
    scopes.extend(
        (f"VIEW_{view}", joined["market_view"].eq(view))
        for view in ["ALL_A", "SH_A", "SZ_A", "CHINEXT_BOARD"]
    )
    records: list[dict[str, Any]] = []
    for scope, mask in scopes:
        cell = joined.loc[mask, [left, right]].dropna()
        records.append(
            {
                "scope": scope,
                "n": len(cell),
                "spearman": _rho(cell[left], cell[right]),
                "sign_agreement": _sign_agreement(cell[left], cell[right])
                if len(cell)
                else float("nan"),
                "within_one": float(
                    np.mean(np.abs(cell[left].to_numpy(float) - cell[right].to_numpy(float)) <= 1)
                )
                if len(cell)
                else float("nan"),
                "exact_agreement": float(
                    np.mean(cell[left].to_numpy(float) == cell[right].to_numpy(float))
                )
                if len(cell)
                else float("nan"),
            }
        )
    return records


def _definition_pair(
    panel: pd.DataFrame,
    role: str,
    challenge: str,
    spec: dict[str, Any],
) -> pd.DataFrame:
    primary = _role_domain(panel.loc[panel["definition"].eq("L20_CONTINUOUS")], role, spec)[
        ["audit_id", "market_view", "target_year", "temporal_block", role]
    ].rename(columns={role: "primary_value"})
    other = _role_domain(panel.loc[panel["definition"].eq(challenge)], role, spec)[
        ["audit_id", role]
    ].rename(columns={role: "challenge_value"})
    return primary.merge(other, on="audit_id", validate="one_to_one")


def _nondegenerate(role_frame: pd.DataFrame, role: str, spec: dict[str, Any]) -> bool:
    kind = spec["roles"][role]["kind"]
    gates = spec["representation_gates"]
    if kind == "continuous":
        return role_frame[role].nunique() >= gates["continuous_nondegeneracy"][
            "minimum_unique_global"
        ] and all(
            role_frame.loc[role_frame["target_year"].eq(year), role].nunique()
            >= gates["continuous_nondegeneracy"]["minimum_unique_each_year"]
            for year in spec["population"]["years"]
        )
    return role_frame[role].nunique() >= gates["discrete_nondegeneracy"][
        "minimum_unique_global"
    ] and all(
        role_frame.loc[role_frame["temporal_block"].eq(block), role].nunique()
        >= gates["discrete_nondegeneracy"]["minimum_unique_each_block"]
        for block in ("A", "B")
    )


def _definition_gate(
    records: list[dict[str, Any]],
    role: str,
    challenge: str,
    spec: dict[str, Any],
) -> bool:
    indexed = {record["scope"]: record for record in records}
    gates = spec["representation_gates"]
    domain = spec["roles"][role]["domain"]
    support = gates["definition_support"]
    minimum_total = (
        support["reacquisition_total"]
        if domain == "reacquisition_domain"
        else support["main_total"]
    )
    minimum_block = (
        support["reacquisition_each_block"]
        if domain == "reacquisition_domain"
        else support["main_each_block"]
    )
    if (
        indexed["GLOBAL"]["n"] < minimum_total
        or indexed["BLOCK_A"]["n"] < minimum_block
        or indexed["BLOCK_B"]["n"] < minimum_block
    ):
        return False
    kind = spec["roles"][role]["kind"]
    if kind == "discrete":
        threshold = gates["discrete_neighbor"]
        if challenge == "L20_AUCTION":
            metrics_pass = (
                indexed["GLOBAL"]["exact_agreement"] >= threshold["minimum_auction_exact_global"]
                and indexed["BLOCK_A"]["exact_agreement"]
                >= threshold["minimum_auction_exact_each_block"]
                and indexed["BLOCK_B"]["exact_agreement"]
                >= threshold["minimum_auction_exact_each_block"]
            )
        else:
            metrics_pass = (
                indexed["GLOBAL"]["spearman"] >= threshold["minimum_global_spearman"]
                and indexed["BLOCK_A"]["spearman"] >= threshold["minimum_each_block_spearman"]
                and indexed["BLOCK_B"]["spearman"] >= threshold["minimum_each_block_spearman"]
                and indexed["GLOBAL"]["within_one"] >= threshold["minimum_within_one_global"]
                and indexed["BLOCK_A"]["within_one"] >= threshold["minimum_within_one_each_block"]
                and indexed["BLOCK_B"]["within_one"] >= threshold["minimum_within_one_each_block"]
            )
    else:
        threshold = (
            gates["auction_challenge"] if challenge == "L20_AUCTION" else gates["level_neighbor"]
        )
        metrics_pass = (
            indexed["GLOBAL"]["spearman"] >= threshold["minimum_global_spearman"]
            and indexed["BLOCK_A"]["spearman"] >= threshold["minimum_each_block_spearman"]
            and indexed["BLOCK_B"]["spearman"] >= threshold["minimum_each_block_spearman"]
        )
        if spec["roles"][role]["signed"]:
            metrics_pass = metrics_pass and (
                indexed["GLOBAL"]["sign_agreement"] >= threshold["minimum_signed_global_agreement"]
                and indexed["BLOCK_A"]["sign_agreement"]
                >= threshold["minimum_signed_each_block_agreement"]
                and indexed["BLOCK_B"]["sign_agreement"]
                >= threshold["minimum_signed_each_block_agreement"]
            )
    portability = gates["view_portability"]
    supported_views = [
        item
        for scope, item in indexed.items()
        if scope.startswith("VIEW_")
        and item["n"] >= portability["minimum_supported_view_intersection"]
    ]
    required_views = (
        portability["conditional_reacquisition_minimum_supported_views"]
        if domain == "reacquisition_domain"
        else 4
    )
    view_threshold = (
        portability["minimum_auction_spearman"]
        if challenge == "L20_AUCTION"
        else portability["minimum_level_neighbor_spearman"]
    )
    view_pass = len(supported_views) >= required_views and all(
        np.isfinite(item["spearman"]) and item["spearman"] >= view_threshold
        for item in supported_views
    )
    return bool(metrics_pass and view_pass)


def _shape_audit(
    primary: pd.DataFrame, role: str, spec: dict[str, Any]
) -> tuple[list[dict[str, Any]], bool]:
    challenges = spec["roles"][role].get("shape_challenges", [])
    records: list[dict[str, Any]] = []
    passes: list[bool] = []
    for challenge in challenges:
        domain = _role_domain(primary, role, spec)
        pair = domain[["market_view", "target_year", "temporal_block", role, challenge]].dropna()
        scoped = _pair_scopes(pair, role, challenge)
        for record in scoped:
            records.append(
                {
                    "role": role,
                    "challenge": f"SHAPE_{challenge}",
                    **record,
                }
            )
        indexed = {record["scope"]: record for record in scoped}
        if role == "continuation30_log_return":
            gate = spec["representation_gates"]["continuation_shape"]
            if challenge == "continuation5_log_return":
                global_min = gate["horizon5_minimum_global_spearman"]
                block_min = gate["horizon5_minimum_each_block_spearman"]
            else:
                global_min = gate["horizon15_60_minimum_global_spearman"]
                block_min = gate["horizon15_60_minimum_each_block_spearman"]
            passed = (
                indexed["GLOBAL"]["spearman"] >= global_min
                and indexed["BLOCK_A"]["spearman"] >= block_min
                and indexed["BLOCK_B"]["spearman"] >= block_min
                and indexed["GLOBAL"]["sign_agreement"] >= gate["minimum_sign_agreement"]
            )
        elif role == "below_level_close_fraction":
            gate = spec["representation_gates"]["dwell_shape"]
            passed = (
                indexed["GLOBAL"]["spearman"] >= gate["minimum_global_spearman"]
                and indexed["BLOCK_A"]["spearman"] >= gate["minimum_each_block_spearman"]
                and indexed["BLOCK_B"]["spearman"] >= gate["minimum_each_block_spearman"]
            )
        else:
            gate = spec["representation_gates"]["vwap_shape"]
            passed = (
                indexed["GLOBAL"]["spearman"] >= gate["minimum_global_spearman"]
                and indexed["BLOCK_A"]["spearman"] >= gate["minimum_each_block_spearman"]
                and indexed["BLOCK_B"]["spearman"] >= gate["minimum_each_block_spearman"]
            )
        passes.append(bool(passed))
    return records, all(passes) if passes else True


def _rank_adjusted_r2(frame: pd.DataFrame, target: str, controls: list[str]) -> float:
    working = frame[[target, *controls]].dropna()
    n = len(working)
    p = len(controls)
    if n <= p + 1 or working[target].nunique() < 2:
        return float("nan")
    ranked = working.rank(method="average")
    y = ranked[target].to_numpy(float)
    x = np.column_stack([np.ones(n), *[ranked[name].to_numpy(float) for name in controls]])
    fitted = x @ np.linalg.lstsq(x, y, rcond=None)[0]
    total = float(np.sum(np.square(y - np.mean(y))))
    residual = float(np.sum(np.square(y - fitted)))
    r2 = 1.0 - residual / total
    return float(1.0 - (1.0 - r2) * (n - 1) / (n - p - 1))


def _geometry_audit(
    primary: pd.DataFrame,
    role: str,
    spec: dict[str, Any],
) -> tuple[list[dict[str, Any]], bool]:
    frame = _role_domain(primary, role, spec)
    controls = spec["roles"][role]["controls"]
    records: list[dict[str, Any]] = []
    pairwise_pass = True
    joint_pass = True
    pair_max = spec["representation_gates"]["external_pairwise_absolute_spearman_maximum"]
    joint_global_max = spec["representation_gates"][
        "external_joint_rank_adjusted_r2_global_maximum"
    ]
    joint_block_max = spec["representation_gates"][
        "external_joint_rank_adjusted_r2_each_block_maximum"
    ]
    for scope, mask in [
        ("GLOBAL", pd.Series(True, index=frame.index)),
        ("BLOCK_A", frame["temporal_block"].eq("A")),
        ("BLOCK_B", frame["temporal_block"].eq("B")),
    ]:
        cell = frame.loc[mask]
        for control in controls:
            complete = cell[[role, control]].dropna()
            rho = _rho(complete[role], complete[control])
            records.append(
                {
                    "role": role,
                    "metric": "PAIRWISE_SPEARMAN",
                    "control_or_role": control,
                    "scope": scope,
                    "n": len(complete),
                    "value": rho,
                }
            )
            pairwise_pass = pairwise_pass and np.isfinite(rho) and abs(rho) < pair_max
        adjusted = _rank_adjusted_r2(cell, role, controls)
        records.append(
            {
                "role": role,
                "metric": "JOINT_ADJUSTED_R2",
                "control_or_role": "|".join(controls),
                "scope": scope,
                "n": len(cell[[role, *controls]].dropna()),
                "value": adjusted,
            }
        )
        maximum = joint_global_max if scope == "GLOBAL" else joint_block_max
        joint_pass = joint_pass and np.isfinite(adjusted) and adjusted < maximum
    return records, bool(pairwise_pass and joint_pass)


def _analyze(
    panel: pd.DataFrame, spec: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    primary = panel.loc[panel["definition"].eq("L20_CONTINUOUS")].copy()
    stability_records: list[dict[str, Any]] = []
    geometry_records: list[dict[str, Any]] = []
    roles: dict[str, Any] = {}
    for role in ROLE_NAMES:
        role_frame = _role_domain(primary, role, spec)
        definition_passes: dict[str, bool] = {}
        for challenge in ["L10_CONTINUOUS", "L40_CONTINUOUS", "L20_AUCTION"]:
            joined = _definition_pair(panel, role, challenge, spec)
            scoped = _pair_scopes(joined, "primary_value", "challenge_value")
            for record in scoped:
                stability_records.append({"role": role, "challenge": challenge, **record})
            definition_passes[challenge] = _definition_gate(scoped, role, challenge, spec)
        shape_records, shape_pass = _shape_audit(primary, role, spec)
        stability_records.extend(shape_records)
        nondegenerate = _nondegenerate(role_frame, role, spec)
        definition_pass = all(definition_passes.values())
        internal_pass = nondegenerate and definition_pass and shape_pass
        external_pass = False
        if internal_pass:
            records, external_pass = _geometry_audit(primary, role, spec)
            geometry_records.extend(records)
        annual = {
            str(year): {
                "n": int(role_frame["target_year"].eq(year).sum()),
                "unique": int(role_frame.loc[role_frame["target_year"].eq(year), role].nunique()),
                "q25": float(
                    role_frame.loc[role_frame["target_year"].eq(year), role].quantile(0.25)
                ),
                "median": float(role_frame.loc[role_frame["target_year"].eq(year), role].median()),
                "q75": float(
                    role_frame.loc[role_frame["target_year"].eq(year), role].quantile(0.75)
                ),
            }
            for year in spec["population"]["years"]
        }
        status = (
            "REPRESENTATION_PASS_DISTINCT"
            if internal_pass and external_pass
            else "REPRESENTATION_PASS_EXTERNAL_REDUNDANT"
            if internal_pass
            else "REPRESENTATION_FAIL_INTERNAL"
        )
        roles[role] = {
            "status": status,
            "domain_rows": len(role_frame),
            "nondegenerate": nondegenerate,
            "definition_passes": definition_passes,
            "shape_pass": shape_pass,
            "internal_pass": internal_pass,
            "external_pass": external_pass,
            "annual_absolute_distribution": annual,
        }

    direct = [role for role in spec["compression_priority"] if roles[role]["external_pass"]]
    retained: list[str] = []
    compressed_to: dict[str, str] = {}
    threshold = spec["representation_gates"]["role_compression_absolute_spearman"]
    minimum = spec["representation_gates"]["role_compression_minimum_intersection"]
    for role in direct:
        role_frame = _role_domain(primary, role, spec)[["audit_id", role]]
        redundant_to: str | None = None
        for kept in retained:
            kept_frame = _role_domain(primary, kept, spec)[["audit_id", kept]]
            joined = role_frame.merge(kept_frame, on="audit_id")
            rho = _rho(joined[role], joined[kept])
            geometry_records.append(
                {
                    "role": role,
                    "metric": "ROLE_PAIRWISE_SPEARMAN",
                    "control_or_role": kept,
                    "scope": "GLOBAL",
                    "n": len(joined),
                    "value": rho,
                }
            )
            if len(joined) >= minimum and np.isfinite(rho) and abs(rho) >= threshold:
                redundant_to = kept
                break
        if redundant_to is None:
            retained.append(role)
        else:
            compressed_to[role] = redundant_to
    for role, target in compressed_to.items():
        roles[role]["status"] = "REPRESENTATION_PASS_ROLE_REDUNDANT"
        roles[role]["compressed_to"] = target
    summary = {
        "roles": roles,
        "internally_stable_roles": [role for role in ROLE_NAMES if roles[role]["internal_pass"]],
        "externally_distinct_before_role_compression": direct,
        "minimal_roles": retained,
        "role_compression": compressed_to,
    }
    return (
        pd.DataFrame(stability_records).sort_values(["role", "challenge", "scope"]),
        pd.DataFrame(geometry_records).sort_values(["role", "metric", "control_or_role", "scope"]),
        summary,
    )


def _render_report(result: dict[str, Any]) -> str:
    summary = result["representation_summary"]
    lines = [
        "# MKT-BREAKOUT-001 same-session representation",
        "",
        "## Result",
        "",
        f"- Status: `{result['status']}`",
        f"- Internally stable roles: {', '.join(summary['internally_stable_roles']) or 'NONE'}.",
        "- Externally distinct before role compression: "
        f"{', '.join(summary['externally_distinct_before_role_compression']) or 'NONE'}.",
        f"- Minimal retained roles: {', '.join(summary['minimal_roles']) or 'NONE'}.",
        "- Absolute values use unchanged semantics across 2018--2023. The 48 "
        "isolated blocks do not support PIT historical normalization or a full "
        "contemporaneous relative rank.",
        "- Every +5/+15/+30/+60 and end-of-session value is post-cross "
        "attribution available only after its completed bar; the full artifact is "
        "available at 15:30.",
        "- No future return, outcome, strategy field, post-2023 partition, or "
        "CY-011 was read. Representation quality is not breakout usefulness.",
        "",
        "## Role decisions",
        "",
        "| Role | Status | Domain rows |",
        "|---|---|---:|",
    ]
    for role in ROLE_NAMES:
        item = summary["roles"][role]
        lines.append(f"| {role} | {item['status']} | {item['domain_rows']} |")
    lines.extend(
        [
            "",
            "## Reproducibility",
            "",
            f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
            f"- Runner SHA-256: `{result['hashes']['runner_sha256']}`",
            f"- Panel SHA-256: `{result['hashes']['panel_sha256']}`",
            f"- Stability SHA-256: `{result['hashes']['stability_sha256']}`",
            f"- Geometry SHA-256: `{result['hashes']['geometry_sha256']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def run(*, verify_partition_content: bool = True) -> dict[str, Any]:
    started = time.monotonic()
    spec = _load_spec()
    _resource_guard(spec, started)
    base._verify_registry_assets(spec)
    partitions = base.bind_partitions(spec, verify_content=verify_partition_content)
    audit = _load_data_audit(spec)
    panel, scalar_candidates = _construct_panel(spec, audit, partitions, started)
    scalar = _verify_scalar_cases(spec, scalar_candidates)
    stability, geometry, summary = _analyze(panel, spec)

    panel_out = panel.copy()
    panel_out["trade_date"] = panel_out["trade_date"].dt.strftime("%Y-%m-%d")
    panel_out.to_csv(PANEL_PATH, index=False, float_format="%.17g", lineterminator="\n")
    stability.to_csv(STABILITY_PATH, index=False, float_format="%.17g", lineterminator="\n")
    geometry.to_csv(GEOMETRY_PATH, index=False, float_format="%.17g", lineterminator="\n")
    minimal = summary["minimal_roles"]
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": (
            "COMPLETE_REPRESENTATION_PASS"
            if minimal
            else "COMPLETE_NO_EXTERNALLY_DISTINCT_REPRESENTATION"
        ),
        "population": {
            "input_cohort_rows": len(audit),
            "input_unique_sessions": len(audit[["symbol", "trade_date"]].drop_duplicates()),
            "panel_rows": len(panel),
            "primary_crossings": int(panel["definition"].eq("L20_CONTINUOUS").sum()),
            "primary_matched60": int(
                (panel["definition"].eq("L20_CONTINUOUS") & panel["domain_main"].astype(bool)).sum()
            ),
            "primary_reacquisitions": int(
                (
                    panel["definition"].eq("L20_CONTINUOUS")
                    & panel["domain_reacquisition"].astype(bool)
                ).sum()
            ),
            "raw_minute_rows_read": spec["population"]["expected_raw_minute_rows"],
        },
        "representation_summary": summary,
        "scalar_reconstruction": scalar,
        "coordinate_systems": spec["coordinate_systems"],
        "resource_checks": {
            "raw_rows_exact": True,
            "peak_rss_below_ceiling": True,
            "memory_headroom_above_floor": True,
            "wall_clock_below_ceiling": True,
        },
        "process_claim": "NONE",
        "prediction_or_usefulness_claim": "NONE",
        "strategy_or_outcome_fields_read": [],
        "future_fields_read": [],
        "post_2023_data_read": False,
        "cy011_read": False,
        "partition_content_hashes_verified": verify_partition_content,
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "runner_sha256": sha256_file(Path(__file__)),
            "panel_sha256": sha256_file(PANEL_PATH),
            "stability_sha256": sha256_file(STABILITY_PATH),
            "geometry_sha256": sha256_file(GEOMETRY_PATH),
            "bound_inputs": {name: binding["sha256"] for name, binding in spec["inputs"].items()},
        },
    }
    result = _clean(result)
    RESULT_PATH.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    REPORT_PATH.write_text(_render_report(result), encoding="utf-8")
    durable_bytes = sum(
        path.stat().st_size
        for path in [PANEL_PATH, STABILITY_PATH, GEOMETRY_PATH, RESULT_PATH, REPORT_PATH]
    )
    if durable_bytes > spec["resource_budget"]["durable_output_ceiling_mib"] * 2**20:
        raise BreakoutRepresentationError("durable output ceiling breached")
    _resource_guard(spec, started)
    return result


if __name__ == "__main__":
    completed = run()
    print(
        json.dumps(
            {
                "status": completed["status"],
                "minimal_roles": completed["representation_summary"]["minimal_roles"],
                "role_status": {
                    role: item["status"]
                    for role, item in completed["representation_summary"]["roles"].items()
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
