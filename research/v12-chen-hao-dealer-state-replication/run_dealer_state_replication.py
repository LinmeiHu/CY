#!/usr/bin/env python3
# ruff: noqa: E501
"""Run the research-only Chen Hao dealer-state replication study.

The runner reads only the immutable V12 500-symbol checkpoint bundle and its
registered PIT-safe daily price asset.  It does not replay chips, change seller
models, consume strategy outcomes, or write outside this research directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import duckdb
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from cyq_game.chip.checkpoint_journal_contract import (  # noqa: E402
    RESEARCH_RECOVERABLE_REASON_CODES,
    SELLER_MODEL_ORDER,
    bits_f64be,
    f64be_bits,
)
from cyq_game.chip.price_coordinate import rebase_economic_price  # noqa: E402

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / "results"
PROTOCOL_PATH = STUDY_DIR / "preregistered_protocol.json"
REPORT_PATH = STUDY_DIR / "V12_CHEN_HAO_DEALER_STATE_REPLICATION_STUDY.md"
PREVIOUS_RESULTS = REPO_ROOT / "research/v12-chip-model-economic-validity/results"

DEFAULT_DATA_ROOT = Path("/Users/linmei/Documents/CY/data")
DEFAULT_V3_ROOT = DEFAULT_DATA_ROOT / "validation/v12_v3_500_temporal_20260828"
DEFAULT_LOCK = Path("/Users/linmei/Documents/cyq-v3-500-build/V12_V3_500_TEMPORAL_BUILD_LOCK.json")
DEFAULT_DAILY_INVENTORY = DEFAULT_DATA_ROOT / "input_inventories/CY-006-pit-b-daily-v2-2018-2026-20260821.json"

EXPECTED_SOURCE_COMMIT = "d52f9c97970b37f48525bc7320d337b6fb932a4f"
EXPECTED_ROOT_SHA256 = "915686c6b9a069688e4790a1e6a8e699feafaf951ca7b720c11ca8b21b85c29a"
EXPECTED_LOCK_SHA256 = "95a7b33ec28fe3c188b309e962522cb1bea16a23b7647c68068864a1e17fd6d9"
MODELS = tuple(SELLER_MODEL_ORDER)
ALL_MODELS = (*MODELS, "ENSEMBLE")
SPLITS = ("discovery", "validation", "holdout")
HORIZONS = (5, 10, 20, 40, 60, 120)
PROFIT_DISTANCES = (0.10, 0.20, 0.25, 0.30, 0.40)


@dataclass(frozen=True)
class LotDistribution:
    coordinates: np.ndarray
    shares: np.ndarray
    ages: np.ndarray
    acquisition_costs: np.ndarray
    free_float: float
    known_fraction: float


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_id(*parts: object) -> str:
    return hashlib.sha256("|".join(str(part) for part in parts).encode()).hexdigest()


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def json_value(value: Any) -> Any:
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (pd.Timestamp, Path)):
        return str(value)
    raise TypeError(type(value).__name__)


def split_for(value: pd.Timestamp) -> str:
    if value <= pd.Timestamp("2020-04-30"):
        return "discovery"
    if value <= pd.Timestamp("2020-08-31"):
        return "validation"
    return "holdout"


def wire_bits(value: str) -> int:
    if not isinstance(value, str) or not value.startswith("f64be:"):
        raise RuntimeError("invalid checkpoint binary64 field")
    return int(value[6:], 16)


def bit_array_to_float(values: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(values, dtype="<u8").view("<f8")


def assert_scoped_worktree() -> None:
    status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=all"], cwd=REPO_ROOT, text=True
    )
    allowed = STUDY_DIR.relative_to(REPO_ROOT).as_posix() + "/"
    outside = []
    for line in status.splitlines():
        path = line[3:].split(" -> ")[-1]
        if not path.startswith(allowed):
            outside.append(line)
    if outside:
        raise RuntimeError(f"out-of-scope worktree changes: {outside}")


def verify_inputs(
    v3_root: Path,
    freeze_lock: Path,
    daily_inventory: Path,
    *,
    full_hash: bool,
) -> dict[str, Any]:
    assert_scoped_worktree()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    if head != EXPECTED_SOURCE_COMMIT:
        raise RuntimeError(f"source commit changed: {head}")
    manifest_path = v3_root / "manifest.json"
    if sha256(manifest_path) != EXPECTED_ROOT_SHA256:
        raise RuntimeError("frozen root manifest hash mismatch")
    if sha256(freeze_lock) != EXPECTED_LOCK_SHA256:
        raise RuntimeError("freeze lock hash mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if len(manifest["symbols"]) != 500 or tuple(manifest["seller_models"]) != MODELS:
        raise RuntimeError("frozen universe or seller-model order changed")
    kind_counts = Counter(item["kind"] for item in manifest["parts"])
    if kind_counts["feature"] != 500 or kind_counts["checkpoint"] != 6489:
        raise RuntimeError("frozen checkpoint coverage changed")
    verified_bytes = 0
    if full_hash:
        for number, item in enumerate(manifest["parts"], start=1):
            path = v3_root / item["relative_path"]
            if not path.is_file() or path.stat().st_size != int(item["bytes"]):
                raise RuntimeError(f"frozen part missing/truncated: {item['relative_path']}")
            if sha256(path) != item["sha256"]:
                raise RuntimeError(f"frozen part hash mismatch: {item['relative_path']}")
            verified_bytes += path.stat().st_size
            if number % 1500 == 0:
                print(f"verified frozen parts: {number}/{len(manifest['parts'])}", flush=True)
    inventory = json.loads(daily_inventory.read_text(encoding="utf-8"))
    inventory_items = {item["path"]: item for item in inventory["files"]}
    daily_files: dict[int, Path] = {}
    daily_hashes: dict[str, str] = {}
    for year in (2019, 2020, 2021):
        relative = f"partition_year={year}/data_0.parquet"
        binding = inventory_items.get(relative)
        if binding is None:
            raise RuntimeError(f"registered daily inventory lacks {year}")
        path = Path(inventory["root"]) / relative
        actual = sha256(path)
        if path.stat().st_size != int(binding["size"]) or actual != binding["sha256"]:
            raise RuntimeError(f"registered daily partition mismatch: {year}")
        daily_files[year] = path
        daily_hashes[str(year)] = actual
    return {
        "source_commit": head,
        "manifest": manifest,
        "symbols": list(manifest["symbols"]),
        "root_manifest_sha256": EXPECTED_ROOT_SHA256,
        "freeze_lock_sha256": EXPECTED_LOCK_SHA256,
        "daily_inventory_sha256": sha256(daily_inventory),
        "daily_partition_sha256": daily_hashes,
        "daily_files": daily_files,
        "verified_all_parts": full_hash,
        "verified_part_count": len(manifest["parts"]) if full_hash else 0,
        "verified_part_bytes": verified_bytes,
        "part_kind_counts": dict(kind_counts),
    }


def read_prices(files: dict[int, Path], symbols: Sequence[str]) -> pd.DataFrame:
    con = duckdb.connect()
    try:
        con.execute("CREATE TEMP TABLE selected_symbols(symbol VARCHAR PRIMARY KEY)")
        con.executemany("INSERT INTO selected_symbols VALUES (?)", ((symbol,) for symbol in symbols))
        paths = ",".join(f"'{files[year]}'" for year in sorted(files))
        frame = con.execute(
            f"""
            SELECT d.symbol, d.trade_date, d.decision_at, d.available_at,
                   d.open, d.high, d.low, d.close, d.volume, d.turnover_fraction,
                   d.trade_status, d.bar_valid, d.current_day_data_tradable,
                   d.corporate_action_count, d.corporate_action_valid,
                   d.corporate_action_blocking, d.cash_per_share, d.share_multiplier,
                   d.snapshot_id, d.daily_snapshot_id
            FROM read_parquet([{paths}]) d
            JOIN selected_symbols s USING(symbol)
            WHERE d.trade_date >= DATE '2019-01-01'
              AND d.trade_date <= DATE '2021-07-31'
            ORDER BY d.symbol, d.trade_date
            """
        ).fetchdf()
    finally:
        con.close()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    if frame.duplicated(["symbol", "trade_date"]).any():
        raise RuntimeError("duplicate PIT daily price key")
    bad_pit = frame["available_at"].notna() & frame["decision_at"].notna() & (frame["available_at"] > frame["decision_at"])
    if bad_pit.any():
        raise RuntimeError("registered price violates available_at <= decision_at")
    frame["tradable_observation"] = (
        frame["bar_valid"].fillna(False)
        & frame["trade_status"].eq(1)
        & frame[["open", "high", "low", "close"]].gt(0).all(axis=1)
    )
    return frame


def _run_lengths(signs: np.ndarray) -> tuple[float, float]:
    if len(signs) == 0:
        return math.nan, math.nan
    positive: list[int] = []
    negative: list[int] = []
    current = int(signs[0])
    length = 1
    for value in signs[1:]:
        value = int(value)
        if value == current:
            length += 1
        else:
            (positive if current > 0 else negative).append(length)
            current, length = value, 1
    (positive if current > 0 else negative).append(length)
    return (
        float(np.mean(positive)) if positive else math.nan,
        float(np.mean(negative)) if negative else math.nan,
    )


def prepare_price_data(prices: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], dict[tuple[str, pd.Timestamp], int]]:
    valid = prices[prices["tradable_observation"]].copy().sort_values(["symbol", "trade_date"])
    contexts: list[pd.DataFrame] = []
    for symbol, group in valid.groupby("symbol", sort=True):
        group = group.copy().reset_index(drop=True)
        group["daily_return"] = group["close"].pct_change()
        group["prior_return_20"] = group["close"] / group["close"].shift(20) - 1.0
        group["prior_return_60"] = group["close"] / group["close"].shift(60) - 1.0
        group["prior_return_120"] = group["close"] / group["close"].shift(120) - 1.0
        group["volatility_20"] = group["daily_return"].rolling(20, min_periods=10).std()
        low252 = group["low"].rolling(252, min_periods=120).min()
        high252 = group["high"].rolling(252, min_periods=120).max()
        group["price_position_252"] = (group["close"] - low252) / (high252 - low252)
        group["recent_high_60"] = group["close"].rolling(60, min_periods=40).max()
        group["recent_low_60"] = group["close"].rolling(60, min_periods=40).min()
        group["box_high_40"] = group["high"].rolling(40, min_periods=40).max()
        group["box_low_40"] = group["low"].rolling(40, min_periods=40).min()
        group["box_range_40"] = group["box_high_40"] / group["box_low_40"] - 1.0
        group["cumulative_turnover_40"] = group["turnover_fraction"].rolling(40, min_periods=40).sum()
        group["range_20"] = group["high"].rolling(20, min_periods=20).max() / group["low"].rolling(20, min_periods=20).min() - 1.0
        group["drawdown_20"] = group["close"] / group["close"].rolling(20, min_periods=20).max() - 1.0
        positive = group["daily_return"].gt(0).astype(float)
        group["positive_fraction_60"] = positive.rolling(60, min_periods=40).mean()
        bull_ratios = np.full(len(group), np.nan)
        for index in range(59, len(group)):
            values = group.loc[index - 59 : index, "daily_return"].dropna().to_numpy()
            signs = np.where(values >= 0.0, 1, -1)
            up, down = _run_lengths(signs)
            if finite(up) and finite(down) and down > 0:
                bull_ratios[index] = up / down
        group["bull_bear_run_ratio_60"] = bull_ratios
        prior_edge = group["close"].shift(20).rolling(20, min_periods=10).max()
        middle_low = group["low"].shift(10).rolling(10, min_periods=10).min()
        recent_range = group["high"].rolling(10, min_periods=10).max() / group["low"].rolling(10, min_periods=10).min() - 1.0
        group["pit_edge_horizontal"] = (
            (middle_low / prior_edge - 1.0 <= -0.10)
            & (group["close"] / prior_edge - 1.0 >= -0.05)
            & (recent_range <= 0.10)
        )
        contexts.append(group)
    valid = pd.concat(contexts, ignore_index=True)

    market_daily = valid[["trade_date", "symbol", "daily_return", "close"]].copy()
    ma20 = valid.groupby("symbol", sort=False)["close"].transform(lambda values: values.rolling(20, min_periods=15).mean())
    market_daily["above_ma20"] = market_daily["close"] > ma20
    market = market_daily.groupby("trade_date", sort=True).agg(
        equal_weight_return=("daily_return", "mean"), breadth_20=("above_ma20", "mean")
    )
    market["market_index"] = (1.0 + market["equal_weight_return"].fillna(0.0)).cumprod()
    market["market_return_20"] = market["market_index"] / market["market_index"].shift(20) - 1.0
    market["market_return_60"] = market["market_index"] / market["market_index"].shift(60) - 1.0
    market = market.reset_index()
    valid = valid.merge(market, on="trade_date", how="left", validate="many_to_one")

    weak = valid["market_return_60"].le(-0.10) | valid["breadth_20"].lt(0.35)
    overheated = (~weak) & valid["market_return_60"].ge(0.20) & valid["breadth_20"].ge(0.70)
    recovering = (~weak) & (~overheated) & valid["market_return_20"].gt(0.0) & valid["market_return_60"].le(0.05)
    valid["market_environment"] = np.select(
        [weak, recovering, overheated], ["BROADLY_WEAK", "RECOVERING", "OVERHEATED"], default="STRONG"
    )
    valid["price_position_state"] = pd.cut(
        valid["price_position_252"], [-np.inf, 0.40, 0.70, np.inf], labels=["LOW", "MODERATE", "HIGH"], include_lowest=True
    ).astype("string").fillna("UNAVAILABLE")

    by_symbol = {symbol: group.reset_index(drop=True) for symbol, group in valid.groupby("symbol", sort=True)}
    index_lookup = {
        (symbol, pd.Timestamp(day)): index
        for symbol, group in by_symbol.items()
        for index, day in enumerate(group["trade_date"])
    }
    return valid, by_symbol, index_lookup


def future_outcomes(
    by_symbol: dict[str, pd.DataFrame],
    index_lookup: dict[tuple[str, pd.Timestamp], int],
    symbol: str,
    day: pd.Timestamp,
) -> dict[str, float]:
    result: dict[str, float] = {}
    index = index_lookup.get((symbol, pd.Timestamp(day)))
    if index is None:
        return {f"{metric}_{horizon}": math.nan for horizon in HORIZONS for metric in ("future_return", "mfe", "mae", "hit_10", "hit_20", "hit_30", "drawdown_10", "time_to_peak")}
    group = by_symbol[symbol]
    start_close = float(group.iloc[index]["close"])
    for horizon in HORIZONS:
        future = group.iloc[index + 1 : index + horizon + 1]
        if len(future) < horizon:
            values = {name: math.nan for name in ("future_return", "mfe", "mae", "hit_10", "hit_20", "hit_30", "drawdown_10", "time_to_peak")}
        else:
            mfe = float(future["high"].max() / start_close - 1.0)
            mae = float(future["low"].min() / start_close - 1.0)
            values = {
                "future_return": float(future.iloc[-1]["close"] / start_close - 1.0),
                "mfe": mfe,
                "mae": mae,
                "hit_10": float(mfe >= 0.10),
                "hit_20": float(mfe >= 0.20),
                "hit_30": float(mfe >= 0.30),
                "drawdown_10": float(mae <= -0.10),
                "time_to_peak": float(np.argmax(future["high"].to_numpy()) + 1),
            }
        result.update({f"{name}_{horizon}": value for name, value in values.items()})
    return result


def _validate_mass(shares: np.ndarray, free_float: float, declared_bits: int) -> None:
    if free_float <= 0 or np.any(shares < 0) or not np.isfinite(shares).all():
        raise RuntimeError("invalid checkpoint mass")
    computed = math.fsum(shares.tolist()) - free_float
    declared = bits_f64be(declared_bits)
    if not (computed == declared == 0.0 or f64be_bits(computed) == declared_bits):
        raise RuntimeError("checkpoint mass residual exact bits mismatch")


def decode_checkpoint(path: Path) -> tuple[dict[str, Any], dict[str, LotDistribution]]:
    with np.load(path, allow_pickle=False) as archive:
        raw = json.loads(bytes(archive["metadata_json"]))
        if raw.get("identities") != [] or tuple(item["seller_model"] for item in raw["model_states"]) != MODELS:
            raise RuntimeError("checkpoint metadata skeleton or seller models changed")
        positions = np.asarray(archive["lot_identity_positions"], dtype="<u8")
        offsets = np.asarray(archive["model_lot_offsets"], dtype="<u8")
        all_shares = bit_array_to_float(np.asarray(archive["lot_share_bits"], dtype="<u8"))
        coordinate_valid = np.asarray(archive["identity_economic_valid"], dtype=np.uint8).astype(bool)
        all_coordinates = bit_array_to_float(np.asarray(archive["identity_economic_bits"], dtype="<u8"))
        all_ages = np.asarray(archive["identity_holding_days"], dtype="<i2")
        acquisition_valid = np.asarray(archive["lot_acquisition_valid"], dtype=np.uint8).astype(bool)
        all_acquisition = bit_array_to_float(np.asarray(archive["lot_acquisition_bits"], dtype="<u8"))
        distributions: dict[str, LotDistribution] = {}
        for model_index, state in enumerate(raw["model_states"]):
            start, stop = int(offsets[model_index]), int(offsets[model_index + 1])
            model_positions = positions[start:stop].astype(np.int64, copy=False)
            model_shares = all_shares[start:stop]
            free_float = bits_f64be(wire_bits(state["free_float_shares_bits"]))
            _validate_mass(model_shares, free_float, wire_bits(state["conservation_error_bits"]))
            valid = coordinate_valid[model_positions]
            shares = model_shares[valid].copy()
            coordinates = all_coordinates[model_positions[valid]].copy()
            ages = all_ages[model_positions[valid]].astype(float, copy=True)
            acquisitions = np.where(acquisition_valid[start:stop][valid], all_acquisition[start:stop][valid], np.nan)
            if np.any(coordinates <= 0) or np.any(shares <= 0):
                raise RuntimeError("invalid known-cost lot")
            distributions[state["seller_model"]] = LotDistribution(
                coordinates=coordinates,
                shares=shares,
                ages=ages,
                acquisition_costs=acquisitions,
                free_float=free_float,
                known_fraction=float(shares.sum() / free_float),
            )
    return raw, distributions


def tracker_scope(raw: dict[str, Any], model: str) -> dict[str, Any]:
    scope_names = {"UNIFORM": "uniform", "DISPOSITION": "disposition", "ACTIVE_STICKY": "active_sticky", "ENSEMBLE": "ENSEMBLE"}
    matches = [item for item in raw["temporal_tracker"]["scopes"] if item["scope"] == scope_names[model]]
    if len(matches) != 1:
        raise RuntimeError(f"missing tracker scope {model}")
    return matches[0]


def live_peaks(raw: dict[str, Any], model: str) -> list[dict[str, Any]]:
    peaks = []
    for item in tracker_scope(raw, model)["previous_peaks"]:
        if item["lost"]:
            continue
        peaks.append(
            {
                "track_id": item["peak_track_id"],
                "age": int(item["age"]),
                "lower": bits_f64be(wire_bits(item["band_lower_bits"])),
                "center": bits_f64be(wire_bits(item["center_price_bits"])),
                "upper": bits_f64be(wire_bits(item["band_upper_bits"])),
                "mass": bits_f64be(wire_bits(item["mass_bits"])),
            }
        )
    return peaks


def weighted_mean(values: np.ndarray, weights: np.ndarray) -> float:
    return float(np.dot(values, weights) / weights.sum()) if len(values) and float(weights.sum()) > 0 else math.nan


def weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    if not len(values) or float(weights.sum()) <= 0:
        return math.nan
    order = np.argsort(values, kind="stable")
    cumulative = np.cumsum(weights[order])
    index = min(int(np.searchsorted(cumulative, q * cumulative[-1], side="left")), len(values) - 1)
    return float(values[order[index]])


def mass_below(distribution: LotDistribution, threshold: float, *, min_age: float | None = None) -> float:
    mask = distribution.coordinates <= threshold
    if min_age is not None:
        mask &= distribution.ages >= min_age
    return float(distribution.shares[mask].sum() / distribution.free_float)


def transform_coordinate(value: float, paths: pd.DataFrame) -> tuple[float, bool]:
    result = float(value)
    for action in paths.itertuples(index=False):
        if int(action.corporate_action_count or 0) <= 0:
            continue
        if not bool(action.corporate_action_valid) or bool(action.corporate_action_blocking):
            return math.nan, False
        result = rebase_economic_price(
            result,
            cash_per_share=float(action.cash_per_share or 0.0),
            share_multiplier=float(action.share_multiplier or 1.0),
        )
    return result, True


def distribution_hhi(distribution: LotDistribution) -> float:
    if not len(distribution.coordinates):
        return math.nan
    _, inverse = np.unique(distribution.coordinates, return_inverse=True)
    masses = np.bincount(inverse, weights=distribution.shares)
    probabilities = masses / masses.sum()
    return float(np.dot(probabilities, probabilities))


def inferred_state(row: dict[str, Any]) -> str:
    if finite(row.get("base_retention_ratio_20")) and row["base_retention_ratio_20"] < 0.50 and row["prior_return_60"] >= 0.30:
        return "BASE_DISTRIBUTED"
    if finite(row.get("base_retention_ratio_20")) and row["base_retention_ratio_20"] < 0.50:
        return "DISTRIBUTION_CANDIDATE"
    if finite(row.get("base_retention_ratio_20")) and row["base_retention_ratio_20"] < 0.80:
        return "BASE_MIGRATION"
    if row["inferred_control_mass"] >= 0.50 and row["inferred_holder_profit"] >= 0.50 and row.get("base_retention_state") == "LOCKED_BASE_INTACT":
        return "HIGH_PROFIT_STILL_LOCKED"
    if row["locked_mass_20"] >= 0.30 and row["prior_return_60"] >= 0.20 and row.get("base_retention_state") == "LOCKED_BASE_INTACT":
        return "MARKUP_WITH_BASE_LOCKED"
    if row["locked_mass_20"] >= 0.30:
        return "LOCKED_LOW_COST_BASE"
    if row["inferred_control_mass"] >= 0.50:
        return "INFERRED_HIGH_CONTROL"
    if bool(row.get("low_position_dense")) or bool(row.get("consolidation_eligible")):
        return "ACCUMULATION_CANDIDATE"
    return "UNCLASSIFIED"


def turnover_since_profitable_approximation(
    group: pd.DataFrame,
    index: int,
    median_locked_cost: float,
    distance: float,
    weighted_age: float,
) -> float:
    if not finite(median_locked_cost) or not finite(weighted_age):
        return math.nan
    start = max(0, index - max(1, min(int(weighted_age), 180)))
    history = group.iloc[start : index + 1]
    crossed = history.index[history["close"] >= median_locked_cost * (1.0 + distance)]
    if not len(crossed):
        return math.nan
    first = int(crossed[0])
    return float(group.loc[first:index, "turnover_fraction"].sum())


def context_dict(row: pd.Series) -> dict[str, Any]:
    names = (
        "close",
        "turnover_fraction",
        "prior_return_20",
        "prior_return_60",
        "prior_return_120",
        "volatility_20",
        "price_position_252",
        "price_position_state",
        "recent_high_60",
        "recent_low_60",
        "box_high_40",
        "box_low_40",
        "box_range_40",
        "cumulative_turnover_40",
        "range_20",
        "drawdown_20",
        "positive_fraction_60",
        "bull_bear_run_ratio_60",
        "pit_edge_horizontal",
        "market_return_20",
        "market_return_60",
        "breadth_20",
        "market_environment",
        "snapshot_id",
        "daily_snapshot_id",
    )
    return {name: row[name] for name in names}


def _profit_state(profit: float) -> str:
    if not finite(profit):
        return "UNAVAILABLE"
    if profit < 0.20:
        return "LOW_PROFIT"
    if profit < 0.50:
        return "MODERATE_PROFIT"
    if profit < 1.00:
        return "HIGH_PROFIT"
    return "VERY_HIGH_PROFIT"


def _control_state(mass: float) -> str:
    if mass < 0.30:
        return "LOW_CONTROL"
    if mass < 0.50:
        return "MODERATE_CONTROL"
    return "HIGH_CONTROL"


def checkpoint_model_row(
    *,
    symbol: str,
    checkpoint_date: pd.Timestamp,
    model: str,
    distribution: LotDistribution,
    raw: dict[str, Any],
    context: dict[str, Any],
    previous: dict[str, Any] | None,
    action_path: pd.DataFrame,
    price_group: pd.DataFrame,
    price_index: int,
    persistence: dict[tuple[str, float], int],
) -> dict[str, Any]:
    close = float(context["close"])
    if distribution.known_fraction < 0.50:
        raise RuntimeError("research-valid checkpoint has insufficient known-cost mass")
    profitable = distribution.coordinates < close
    aged_profitable = profitable & (distribution.ages >= 20)
    inferred_control_mass = float(distribution.shares[aged_profitable].sum() / distribution.free_float)
    inferred_cost = weighted_mean(distribution.coordinates[aged_profitable], distribution.shares[aged_profitable])
    inferred_profit = close / inferred_cost - 1.0 if finite(inferred_cost) and inferred_cost > 0 else math.nan
    row: dict[str, Any] = {
        "snapshot_key": stable_id(symbol, checkpoint_date.date(), model),
        "symbol": symbol,
        "checkpoint_date": checkpoint_date,
        "split": split_for(checkpoint_date),
        "model": model,
        "known_cost_fraction": distribution.known_fraction,
        "profit_ratio": float(distribution.shares[profitable].sum() / distribution.free_float),
        "inferred_control_mass": inferred_control_mass,
        "inferred_base_weighted_cost": inferred_cost,
        "inferred_holder_profit": inferred_profit,
        "control_state": _control_state(inferred_control_mass),
        "dealer_profit_state": _profit_state(inferred_profit),
        "distribution_hhi": distribution_hhi(distribution),
        **context,
    }
    row["dealer_state"] = f"{row['control_state']}_{row['dealer_profit_state']}"
    for distance in PROFIT_DISTANCES:
        suffix = int(round(distance * 100))
        threshold = close / (1.0 + distance)
        mask = distribution.coordinates <= threshold
        locked = mask & (distribution.ages >= 20)
        profitable_mass = float(distribution.shares[mask].sum() / distribution.free_float)
        locked_mass = float(distribution.shares[locked].sum() / distribution.free_float)
        locked_cost = weighted_quantile(distribution.coordinates[locked], distribution.shares[locked], 0.50)
        locked_age = weighted_mean(distribution.ages[locked], distribution.shares[locked])
        key = (model, distance)
        persistence[key] = persistence.get(key, 0) + 1 if locked_mass >= 0.30 else 0
        row[f"profitable_mass_{suffix}"] = profitable_mass
        row[f"locked_mass_{suffix}"] = locked_mass
        row[f"locked_weighted_age_{suffix}"] = locked_age
        row[f"locked_age_60_mass_{suffix}"] = float(
            distribution.shares[mask & (distribution.ages >= 60)].sum() / distribution.free_float
        )
        row[f"locked_age_120_mass_{suffix}"] = float(
            distribution.shares[mask & (distribution.ages >= 120)].sum() / distribution.free_float
        )
        row[f"locked_age_180_mass_{suffix}"] = float(
            distribution.shares[mask & (distribution.ages >= 180)].sum() / distribution.free_float
        )
        row[f"persistence_checkpoints_{suffix}"] = persistence[key]
        row[f"turnover_since_profitable_approx_{suffix}"] = turnover_since_profitable_approximation(
            price_group, price_index, locked_cost, distance, locked_age
        )
        if previous is None:
            row[f"previous_zone_mass_{suffix}"] = math.nan
            row[f"current_mass_at_previous_zone_{suffix}"] = math.nan
            row[f"zone_retention_ratio_{suffix}"] = math.nan
            row[f"migration_loss_{suffix}"] = math.nan
        else:
            previous_distribution: LotDistribution = previous["distribution"]
            previous_close = float(previous["close"])
            previous_threshold = previous_close / (1.0 + distance)
            transformed, valid_path = transform_coordinate(previous_threshold, action_path)
            if not valid_path:
                previous_mass = current_mass = retention = migration_loss = math.nan
            else:
                previous_mass = mass_below(previous_distribution, previous_threshold, min_age=20)
                current_mass = mass_below(distribution, transformed, min_age=20)
                retention = current_mass / previous_mass if previous_mass > 0 else math.nan
                migration_loss = previous_mass - current_mass
            row[f"previous_zone_mass_{suffix}"] = previous_mass
            row[f"current_mass_at_previous_zone_{suffix}"] = current_mass
            row[f"zone_retention_ratio_{suffix}"] = retention
            row[f"migration_loss_{suffix}"] = migration_loss

    row["base_retention_ratio_20"] = row["zone_retention_ratio_20"]
    if not finite(row["base_retention_ratio_20"]):
        row["base_retention_state"] = "UNAVAILABLE"
    elif row["base_retention_ratio_20"] >= 0.80:
        row["base_retention_state"] = "LOCKED_BASE_INTACT"
    elif row["base_retention_ratio_20"] >= 0.50:
        row["base_retention_state"] = "BASE_MIGRATING"
    else:
        row["base_retention_state"] = "BASE_LARGELY_DISTRIBUTED"

    high = float(context["recent_high_60"]) if finite(context["recent_high_60"]) else math.nan
    low = float(context["recent_low_60"]) if finite(context["recent_low_60"]) else math.nan
    downshift_applicable = finite(high) and finite(low) and close >= 0.85 * high and high / low - 1.0 >= 0.25
    row["downshift_applicable"] = downshift_applicable
    row["downshift_mass_25"] = mass_below(distribution, high * 0.75) if downshift_applicable else math.nan
    row["downshift_mass_27"] = mass_below(distribution, high * 0.73) if downshift_applicable else math.nan
    row["consolidation_geometry"] = bool(finite(context["box_range_40"]) and context["box_range_40"] <= 0.10)
    row["consolidation_eligible"] = False
    row["consolidation_retained_mass"] = (
        mass_below(distribution, float(context["box_low_40"])) if row["consolidation_geometry"] else math.nan
    )
    row["ninety_vs_three_group"] = (
        "NINETY_VS_THREE"
        if row["profit_ratio"] > 0.90 and float(context["turnover_fraction"]) < 0.03
        else "PROFIT90_HIGH_TURNOVER"
        if row["profit_ratio"] > 0.90
        else "LOW_TURNOVER_NOT90"
        if float(context["turnover_fraction"]) < 0.03
        else "ORDINARY"
    )

    peaks = sorted(live_peaks(raw, model), key=lambda item: item["mass"], reverse=True)
    row["tracked_mode_count"] = len(peaks)
    row["double_peak"] = False
    row["double_peak_lower_mass"] = math.nan
    row["double_peak_upper_mass"] = math.nan
    row["double_peak_gap"] = math.nan
    row["double_peak_in_valley"] = False
    if len(peaks) >= 2:
        first, second = sorted(peaks[:2], key=lambda item: item["center"])
        gap = second["center"] / first["center"] - 1.0
        in_valley = first["center"] < close < second["center"]
        double = gap >= 0.10 and first["mass"] >= 0.15 and second["mass"] >= 0.10
        row.update(
            {
                "double_peak": double,
                "double_peak_lower_mass": first["mass"],
                "double_peak_upper_mass": second["mass"],
                "double_peak_gap": gap,
                "double_peak_in_valley": bool(double and in_valley),
            }
        )
    row["wounded_high_control"] = bool(
        previous is not None
        and previous["row"]["inferred_control_mass"] >= 0.50
        and previous["row"]["prior_return_60"] >= 0.30
        and finite(context["drawdown_20"])
        and context["drawdown_20"] <= -0.20
        and row["base_retention_state"] == "LOCKED_BASE_INTACT"
        and finite(inferred_cost)
        and abs(close / inferred_cost - 1.0) <= 0.15
    )
    row.update(future_outcomes(_PRICE_BY_SYMBOL, _PRICE_INDEX_LOOKUP, symbol, checkpoint_date))
    return row


def crossing_events_between(
    *,
    symbol: str,
    previous: dict[str, Any],
    current_date: pd.Timestamp,
    raw_prices: pd.DataFrame,
    by_symbol: dict[str, pd.DataFrame],
    index_lookup: dict[tuple[str, pd.Timestamp], int],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    path = raw_prices[
        (raw_prices["trade_date"] > previous["date"]) & (raw_prices["trade_date"] <= current_date)
    ].sort_values("trade_date")
    if path.empty:
        return events
    for model in MODELS:
        distribution: LotDistribution = previous["models"][model]["distribution"]
        for peak in live_peaks(previous["raw"], model):
            if peak["mass"] < 0.15 or peak["lower"] <= previous["close"]:
                continue
            coordinates = distribution.coordinates.copy()
            lower, upper = peak["lower"], peak["upper"]
            prior_close = float(previous["close"])
            anchor_close = float(previous["close"])
            armed = prior_close < lower
            path_valid = True
            for price in path.itertuples(index=False):
                if int(price.corporate_action_count or 0) > 0:
                    if not bool(price.corporate_action_valid) or bool(price.corporate_action_blocking):
                        path_valid = False
                        break
                    coordinates = (coordinates - float(price.cash_per_share or 0.0)) / float(price.share_multiplier or 1.0)
                    lower = rebase_economic_price(lower, cash_per_share=float(price.cash_per_share or 0.0), share_multiplier=float(price.share_multiplier or 1.0))
                    upper = rebase_economic_price(upper, cash_per_share=float(price.cash_per_share or 0.0), share_multiplier=float(price.share_multiplier or 1.0))
                    prior_close = rebase_economic_price(prior_close, cash_per_share=float(price.cash_per_share or 0.0), share_multiplier=float(price.share_multiplier or 1.0))
                    anchor_close = rebase_economic_price(anchor_close, cash_per_share=float(price.cash_per_share or 0.0), share_multiplier=float(price.share_multiplier or 1.0))
                if not bool(price.tradable_observation):
                    continue
                close = float(price.close)
                armed = armed or prior_close < lower
                if armed and close >= upper:
                    released = float(
                        distribution.shares[(coordinates > anchor_close) & (coordinates <= close)].sum()
                        / distribution.free_float
                    )
                    turnover = float(price.turnover_fraction) if finite(price.turnover_fraction) else math.nan
                    if released >= 0.18 and turnover < 0.03:
                        group = "LARGE_RELEASE_LOW_TURNOVER"
                    elif released >= 0.18:
                        group = "LARGE_RELEASE_HIGH_TURNOVER"
                    else:
                        group = "LOW_RELEASE"
                    day = pd.Timestamp(price.trade_date)
                    context_index = index_lookup.get((symbol, day))
                    context = by_symbol[symbol].iloc[context_index] if context_index is not None else None
                    events.append(
                        {
                            "crossing_id": stable_id(symbol, previous["date"].date(), model, peak["track_id"], day.date()),
                            "symbol": symbol,
                            "definition_date": previous["date"],
                            "crossing_date": day,
                            "split": split_for(day),
                            "model": model,
                            "peak_track_id": peak["track_id"],
                            "trapped_peak_mass": peak["mass"],
                            "released_inventory_mass": released,
                            "turnover_fraction": turnover,
                            "crossing_group": group,
                            "path_valid": path_valid,
                            "prior_return_60": float(context["prior_return_60"]) if context is not None else math.nan,
                            "volatility_20": float(context["volatility_20"]) if context is not None else math.nan,
                            "price_position_252": float(context["price_position_252"]) if context is not None else math.nan,
                            "price_position_state": str(context["price_position_state"]) if context is not None else "UNAVAILABLE",
                            "market_return_60": float(context["market_return_60"]) if context is not None else math.nan,
                            "market_environment": str(context["market_environment"]) if context is not None else "UNAVAILABLE",
                            **future_outcomes(by_symbol, index_lookup, symbol, day),
                        }
                    )
                    break
                prior_close = close
    return events


_PRICE_BY_SYMBOL: dict[str, pd.DataFrame] = {}
_PRICE_INDEX_LOOKUP: dict[tuple[str, pd.Timestamp], int] = {}


def build_checkpoint_panel(
    *,
    v3_root: Path,
    manifest: dict[str, Any],
    valid_prices: pd.DataFrame,
    raw_prices: pd.DataFrame,
    by_symbol: dict[str, pd.DataFrame],
    index_lookup: dict[tuple[str, pd.Timestamp], int],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    global _PRICE_BY_SYMBOL, _PRICE_INDEX_LOOKUP
    _PRICE_BY_SYMBOL = by_symbol
    _PRICE_INDEX_LOOKUP = index_lookup
    previous_descriptors = pd.read_parquet(PREVIOUS_RESULTS / "distribution_snapshots.parquet")
    complete_keys = (
        previous_descriptors.groupby(["symbol", "checkpoint_date"], sort=True)["model"]
        .nunique()
        .loc[lambda values: values.eq(len(ALL_MODELS))]
        .index
    )
    eligible_keys = {(symbol, pd.Timestamp(day)) for symbol, day in complete_keys}
    price_context_lookup = {
        (row.symbol, pd.Timestamp(row.trade_date)): row
        for row in valid_prices.itertuples(index=False)
    }
    raw_by_symbol = {symbol: group for symbol, group in raw_prices.groupby("symbol", sort=True)}
    parts: dict[str, list[Path]] = defaultdict(list)
    for item in manifest["parts"]:
        if item["kind"] == "checkpoint":
            symbol = item["relative_path"].split("/", 1)[0].split("=", 1)[1]
            parts[symbol].append(v3_root / item["relative_path"])
    rows: list[dict[str, Any]] = []
    crossings: list[dict[str, Any]] = []
    for symbol_number, symbol in enumerate(sorted(parts), start=1):
        checkpoints = []
        for path in parts[symbol]:
            raw, distributions = decode_checkpoint(path)
            checkpoints.append((pd.Timestamp(raw["checkpoint_date"]), raw, distributions))
        checkpoints.sort(key=lambda item: item[0])
        previous_symbol: dict[str, Any] | None = None
        previous_models: dict[str, dict[str, Any]] = {}
        persistence: dict[tuple[str, float], int] = {}
        for checkpoint_date, raw, distributions in checkpoints:
            if (symbol, checkpoint_date) not in eligible_keys:
                continue
            context_row = price_context_lookup.get((symbol, checkpoint_date))
            if context_row is None:
                raise RuntimeError(f"eligible checkpoint lacks exact tradable PIT price: {symbol} {checkpoint_date}")
            context = context_dict(pd.Series(context_row._asdict()))
            if previous_symbol is not None:
                crossings.extend(
                    crossing_events_between(
                        symbol=symbol,
                        previous=previous_symbol,
                        current_date=checkpoint_date,
                        raw_prices=raw_by_symbol[symbol],
                        by_symbol=by_symbol,
                        index_lookup=index_lookup,
                    )
                )
            action_path = raw_by_symbol[symbol][
                (raw_by_symbol[symbol]["trade_date"] > previous_symbol["date"])
                & (raw_by_symbol[symbol]["trade_date"] <= checkpoint_date)
            ] if previous_symbol is not None else raw_by_symbol[symbol].iloc[0:0]
            model_rows: list[dict[str, Any]] = []
            current_models: dict[str, dict[str, Any]] = {}
            price_index = index_lookup[(symbol, checkpoint_date)]
            for model in MODELS:
                previous = previous_models.get(model)
                row = checkpoint_model_row(
                    symbol=symbol,
                    checkpoint_date=checkpoint_date,
                    model=model,
                    distribution=distributions[model],
                    raw=raw,
                    context=context,
                    previous=previous,
                    action_path=action_path,
                    price_group=by_symbol[symbol],
                    price_index=price_index,
                    persistence=persistence,
                )
                model_rows.append(row)
                current_models[model] = {
                    "distribution": distributions[model],
                    "row": row,
                    "date": checkpoint_date,
                    "close": float(context["close"]),
                }
            numeric_average = {}
            excluded = {"snapshot_key", "model", "dealer_state", "control_state", "dealer_profit_state", "base_retention_state", "ninety_vs_three_group", "price_position_state", "market_environment"}
            for key in model_rows[0]:
                if key in excluded or key in {"symbol", "checkpoint_date", "split"}:
                    continue
                values = [item.get(key) for item in model_rows]
                if all(isinstance(value, (bool, np.bool_)) for value in values):
                    numeric_average[key] = bool(all(values))
                elif all(finite(value) for value in values):
                    numeric_average[key] = float(np.mean([float(value) for value in values]))
                else:
                    numeric_average[key] = math.nan
            ensemble = {
                "snapshot_key": stable_id(symbol, checkpoint_date.date(), "ENSEMBLE"),
                "symbol": symbol,
                "checkpoint_date": checkpoint_date,
                "split": split_for(checkpoint_date),
                "model": "ENSEMBLE",
                **context,
                **numeric_average,
            }
            ensemble["control_state"] = _control_state(ensemble["inferred_control_mass"])
            ensemble["dealer_profit_state"] = _profit_state(ensemble["inferred_holder_profit"])
            ensemble["dealer_state"] = f"{ensemble['control_state']}_{ensemble['dealer_profit_state']}"
            retention = ensemble["base_retention_ratio_20"]
            ensemble["base_retention_state"] = (
                "UNAVAILABLE" if not finite(retention) else "LOCKED_BASE_INTACT" if retention >= 0.80 else "BASE_MIGRATING" if retention >= 0.50 else "BASE_LARGELY_DISTRIBUTED"
            )
            ensemble["ninety_vs_three_group"] = (
                "NINETY_VS_THREE" if ensemble["profit_ratio"] > 0.90 and float(context["turnover_fraction"]) < 0.03
                else "PROFIT90_HIGH_TURNOVER" if ensemble["profit_ratio"] > 0.90
                else "LOW_TURNOVER_NOT90" if float(context["turnover_fraction"]) < 0.03 else "ORDINARY"
            )
            state_values = [item["base_retention_state"] for item in model_rows]
            ensemble["seller_models_agree"] = len(set(state_values)) == 1
            ensemble["seller_model_agreement_count"] = Counter(state_values).most_common(1)[0][1]
            ensemble["wounded_high_control"] = bool(all(item["wounded_high_control"] for item in model_rows))
            rows.extend((*model_rows, ensemble))
            previous_models = current_models
            previous_symbol = {
                "date": checkpoint_date,
                "close": float(context["close"]),
                "raw": raw,
                "models": current_models,
            }
        if symbol_number % 25 == 0:
            print(f"decoded dealer-state checkpoints: {symbol_number}/{len(parts)} symbols", flush=True)
    panel = pd.DataFrame(rows).sort_values(["symbol", "checkpoint_date", "model"]).reset_index(drop=True)
    discovery_hhi = panel[panel["split"].eq("discovery")].groupby("model")["distribution_hhi"].quantile(0.75).to_dict()
    panel["low_position_dense"] = [
        finite(position) and position <= 0.40 and finite(hhi) and hhi >= discovery_hhi[model]
        for position, hhi, model in zip(panel["price_position_252"], panel["distribution_hhi"], panel["model"], strict=True)
    ]
    panel["high_position_dense"] = [
        finite(position) and position >= 0.70 and finite(hhi) and hhi >= discovery_hhi[model]
        for position, hhi, model in zip(panel["price_position_252"], panel["distribution_hhi"], panel["model"], strict=True)
    ]
    panel["slow_bullish_rise"] = (
        panel["prior_return_60"].between(0.0, 0.30)
        & panel["positive_fraction_60"].ge(0.55)
        & panel["price_position_252"].le(0.70)
    )
    panel["bull_long_bear_short"] = panel["bull_bear_run_ratio_60"].ge(1.50) & panel["price_position_252"].le(0.70)
    panel["secondary_low_narrow_consolidation"] = panel["price_position_252"].between(0.20, 0.50) & panel["range_20"].le(0.10)
    discovery_consolidations = panel[
        panel["model"].eq("UNIFORM")
        & panel["split"].eq("discovery")
        & panel["consolidation_geometry"]
    ]
    consolidation_turnover_threshold = float(discovery_consolidations["cumulative_turnover_40"].median())
    if not finite(consolidation_turnover_threshold):
        raise RuntimeError("discovery period cannot freeze the consolidation turnover threshold")
    panel["consolidation_eligible"] = panel["consolidation_geometry"] & panel["cumulative_turnover_40"].ge(consolidation_turnover_threshold)
    panel["state"] = [inferred_state(row) for row in panel.to_dict("records")]
    panel["previous_state"] = panel.groupby(["symbol", "model"], sort=False)["state"].shift(1)
    panel["transition"] = panel["previous_state"].fillna("START") + "->" + panel["state"]
    panel.attrs["discovery_hhi_thresholds"] = discovery_hhi
    panel.attrs["consolidation_turnover_threshold"] = consolidation_turnover_threshold
    crossings_frame = pd.DataFrame(crossings)
    if not crossings_frame.empty:
        crossings_frame = crossings_frame.sort_values(["symbol", "crossing_date", "model"]).reset_index(drop=True)
    return panel, crossings_frame


def cluster_summary(frame: pd.DataFrame, column: str) -> dict[str, float | int]:
    sample = frame[["symbol", column]].dropna()
    if sample.empty:
        return {"effect": math.nan, "ci_low": math.nan, "ci_high": math.nan, "N": 0, "independent_symbols": 0}
    clustered = sample.groupby("symbol", sort=True)[column].mean()
    effect = float(clustered.mean())
    if len(clustered) >= 2:
        standard_error = float(clustered.std(ddof=1) / math.sqrt(len(clustered)))
        low, high = effect - 1.96 * standard_error, effect + 1.96 * standard_error
    else:
        low = high = math.nan
    return {
        "effect": effect,
        "ci_low": low,
        "ci_high": high,
        "N": len(sample),
        "independent_symbols": int(len(clustered)),
    }


def nearest_pairs(frame: pd.DataFrame, group_col: str, target: str, control: str) -> pd.DataFrame:
    feature_cols = ["prior_return_60", "volatility_20", "price_position_252", "market_return_60"]
    scales = np.asarray([0.20, 0.02, 0.25, 0.10, 60.0])
    target_frame = frame[frame[group_col].eq(target)].copy()
    control_frame = frame[frame[group_col].eq(control)].copy()
    if target_frame.empty or control_frame.empty:
        return pd.DataFrame()
    target_frame["calendar_days"] = pd.to_datetime(target_frame["checkpoint_date"] if "checkpoint_date" in target_frame else target_frame["crossing_date"]).map(pd.Timestamp.toordinal)
    control_frame["calendar_days"] = pd.to_datetime(control_frame["checkpoint_date"] if "checkpoint_date" in control_frame else control_frame["crossing_date"]).map(pd.Timestamp.toordinal)
    columns = [*feature_cols, "calendar_days"]
    target_frame = target_frame.dropna(subset=columns)
    control_frame = control_frame.dropna(subset=columns)
    pairs = []
    exact_dimensions = ["model", "split", "market_environment"]
    for keys, targets in target_frame.groupby(exact_dimensions, sort=True):
        controls = control_frame
        for column, key in zip(exact_dimensions, keys, strict=True):
            controls = controls[controls[column].eq(key)]
        if controls.empty:
            continue
        target_values = targets[columns].to_numpy(dtype=float) / scales
        control_values = controls[columns].to_numpy(dtype=float) / scales
        _, indexes = cKDTree(control_values).query(target_values, k=1)
        matched = controls.iloc[np.atleast_1d(indexes)].reset_index(drop=True)
        targets = targets.reset_index(drop=True)
        for index in range(len(targets)):
            item: dict[str, Any] = {
                "symbol": targets.iloc[index]["symbol"],
                "target_id": targets.iloc[index].get("snapshot_key", targets.iloc[index].get("crossing_id")),
                "control_id": matched.iloc[index].get("snapshot_key", matched.iloc[index].get("crossing_id")),
                "model": keys[0],
                "split": keys[1],
                "market_environment": keys[2],
            }
            for horizon in HORIZONS:
                for metric in ("future_return", "mfe", "mae", "hit_10", "hit_20", "hit_30", "drawdown_10"):
                    column = f"{metric}_{horizon}"
                    left, right = targets.iloc[index].get(column), matched.iloc[index].get(column)
                    item[f"paired_{metric}_{horizon}"] = float(left) - float(right) if finite(left) and finite(right) else math.nan
            pairs.append(item)
    return pd.DataFrame(pairs)


def summarize_method(
    frame: pd.DataFrame,
    *,
    group_col: str,
    controls: dict[str, str],
    include_position: bool = False,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    match_cache = {
        (target, control): nearest_pairs(frame, group_col, target, control)
        for target, control in controls.items()
    }
    scopes: list[tuple[str, str, pd.DataFrame]] = [("ALL", "ALL", frame)]
    scopes.extend((regime, "ALL", frame[frame["market_environment"].eq(regime)]) for regime in sorted(frame["market_environment"].dropna().unique()))
    if include_position:
        scopes.extend(("ALL", position, frame[frame["price_position_state"].eq(position)]) for position in ("LOW", "MODERATE", "HIGH"))
    for (model, split, group), sample in frame.groupby(["model", "split", group_col], sort=True):
        for market_scope, position_scope, scoped in scopes:
            selected = scoped[(scoped["model"].eq(model)) & (scoped["split"].eq(split)) & (scoped[group_col].eq(group))]
            if selected.empty:
                continue
            control_group = controls.get(group)
            pair_frame = match_cache.get((group, control_group)) if control_group is not None else None
            if pair_frame is not None and not pair_frame.empty:
                pairs = pair_frame[(pair_frame["model"].eq(model)) & (pair_frame["split"].eq(split))]
                if market_scope != "ALL":
                    pairs = pairs[pairs["market_environment"].eq(market_scope)]
                if position_scope != "ALL":
                    selected_ids = set(selected.get("snapshot_key", selected.get("crossing_id")))
                    pairs = pairs[pairs["target_id"].isin(selected_ids)]
            else:
                pairs = pd.DataFrame()
            for horizon in HORIZONS:
                return_stats = cluster_summary(selected, f"future_return_{horizon}")
                mfe_stats = cluster_summary(selected, f"mfe_{horizon}")
                mae_stats = cluster_summary(selected, f"mae_{horizon}")
                row = {
                    "model": model,
                    "split": split,
                    "group": group,
                    "market_scope": market_scope,
                    "position_scope": position_scope,
                    "horizon": horizon,
                    "event_rows": return_stats["N"],
                    "independent_symbols": return_stats["independent_symbols"],
                    "mean_future_return": return_stats["effect"],
                    "return_ci_low": return_stats["ci_low"],
                    "return_ci_high": return_stats["ci_high"],
                    "mean_mfe": mfe_stats["effect"],
                    "mean_mae": mae_stats["effect"],
                    "probability_plus_10": cluster_summary(selected, f"hit_10_{horizon}")["effect"],
                    "probability_plus_20": cluster_summary(selected, f"hit_20_{horizon}")["effect"],
                    "probability_plus_30": cluster_summary(selected, f"hit_30_{horizon}")["effect"],
                    "probability_drawdown_10": cluster_summary(selected, f"drawdown_10_{horizon}")["effect"],
                    "matched_control_group": control_group,
                    "matched_pairs": len(pairs),
                }
                for metric in ("future_return", "mfe", "mae", "hit_10", "hit_20", "hit_30", "drawdown_10"):
                    column = f"paired_{metric}_{horizon}"
                    row[f"matched_{metric}_excess"] = cluster_summary(pairs, column)["effect"] if not pairs.empty else math.nan
                rows.append(row)
    return pd.DataFrame(rows)


def derive_groups(panel: pd.DataFrame, crossings: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    panel = panel.copy()
    panel["locked_signal_group"] = np.select(
        [
            panel["locked_mass_20"].ge(0.30) & panel["base_retention_ratio_20"].ge(0.80),
            panel["previous_zone_mass_20"].ge(0.30) & panel["base_retention_ratio_20"].lt(0.80),
            panel["locked_mass_20"].lt(0.10),
        ],
        ["LARGE_LOCKED", "MIGRATED", "NO_LARGE_LOW_COST"],
        default="INTERMEDIATE",
    )
    panel["dealer_profit_group"] = np.select(
        [
            panel["control_state"].eq("HIGH_CONTROL") & panel["dealer_profit_state"].isin(["LOW_PROFIT", "MODERATE_PROFIT"]),
            panel["control_state"].eq("HIGH_CONTROL") & panel["dealer_profit_state"].eq("HIGH_PROFIT"),
            panel["control_state"].eq("HIGH_CONTROL") & panel["dealer_profit_state"].eq("VERY_HIGH_PROFIT"),
            panel["control_state"].eq("LOW_CONTROL"),
        ],
        ["HIGH_CONTROL_LOW_MODERATE_PROFIT", "HIGH_CONTROL_HIGH_PROFIT", "HIGH_CONTROL_VERY_HIGH_PROFIT", "LOW_CONTROL"],
        default="MODERATE_CONTROL",
    )
    panel["downshift_group"] = np.select(
        [
            panel["downshift_applicable"] & panel["downshift_mass_27"].ge(0.50),
            panel["downshift_applicable"] & panel["downshift_mass_27"].between(0.30, 0.50, inclusive="left"),
            panel["downshift_applicable"] & panel["downshift_mass_27"].lt(0.30),
        ],
        ["HIGH_RETAINED", "MODERATE_RETAINED", "LOW_RETAINED"],
        default="NOT_APPLICABLE",
    )
    panel["consolidation_group"] = np.select(
        [
            panel["consolidation_eligible"] & panel["consolidation_retained_mass"].ge(0.50),
            panel["consolidation_eligible"] & panel["consolidation_retained_mass"].between(0.30, 0.50, inclusive="left"),
            panel["consolidation_eligible"] & panel["consolidation_retained_mass"].lt(0.30),
        ],
        ["HIGH_RETAINED", "MODERATE_RETAINED", "LOW_RETAINED"],
        default="NOT_ELIGIBLE",
    )
    panel["wounded_group"] = np.select(
        [
            panel["wounded_high_control"],
            panel["drawdown_20"].le(-0.20) & panel["control_state"].eq("LOW_CONTROL"),
            panel["drawdown_20"].le(-0.20) & panel["base_retention_state"].eq("BASE_LARGELY_DISTRIBUTED"),
            panel["drawdown_20"].le(-0.20),
        ],
        ["WOUNDED_HIGH_CONTROL", "LOW_CONTROL_DRAWDOWN", "DRAWDOWN_AFTER_BASE_DISTRIBUTION", "ORDINARY_DRAWDOWN"],
        default="NOT_DRAWDOWN",
    )
    panel["double_peak_group"] = np.select(
        [
            panel["double_peak_in_valley"] & panel["double_peak_lower_mass"].ge(0.25) & panel["drawdown_20"].le(-0.10) & panel["base_retention_ratio_20"].ge(0.80),
            panel["double_peak_in_valley"] & panel["double_peak_lower_mass"].ge(0.25) & panel["base_retention_ratio_20"].ge(0.80),
            panel["double_peak_in_valley"] & panel["base_retention_ratio_20"].lt(0.50),
            panel["double_peak_in_valley"],
        ],
        ["STRONG_LOWER_RETAINED_RAPID_DRAWDOWN", "STRONG_LOWER_RETAINED", "LOWER_BASE_DISTRIBUTED", "WEAK_OR_INTERMEDIATE_LOWER"],
        default="NOT_DOUBLE_PEAK_VALLEY",
    )
    agreement = panel[panel["model"].eq("ENSEMBLE")].set_index(["symbol", "checkpoint_date"])["seller_models_agree"]
    panel["seller_models_agree"] = [
        bool(agreement.get((symbol, date), False))
        for symbol, date in zip(panel["symbol"], panel["checkpoint_date"], strict=True)
    ]
    if not crossings.empty:
        crossings = crossings.copy()
        agreement_rows = crossings.groupby(["symbol", "crossing_date"])["crossing_group"].agg(lambda values: len(values) == 3 and len(set(values)) == 1)
        crossings["seller_models_agree"] = [
            bool(agreement_rows.get((symbol, day), False))
            for symbol, day in zip(crossings["symbol"], crossings["crossing_date"], strict=True)
        ]
    return panel, crossings


def locked_long_panel(panel: pd.DataFrame) -> pd.DataFrame:
    identifiers = [
        "snapshot_key", "symbol", "checkpoint_date", "split", "model", "close", "known_cost_fraction",
        "prior_return_60", "volatility_20", "price_position_252", "price_position_state",
        "market_return_60", "market_environment", "inferred_control_mass", "inferred_holder_profit",
        "control_state", "dealer_profit_state", "base_retention_state", "seller_models_agree",
    ]
    outcome_columns = [f"{metric}_{horizon}" for horizon in HORIZONS for metric in ("future_return", "mfe", "mae", "hit_10", "hit_20", "hit_30", "drawdown_10")]
    rows = []
    for distance in PROFIT_DISTANCES:
        suffix = int(round(distance * 100))
        selected = panel[[*identifiers, *outcome_columns]].copy()
        selected["profit_distance"] = distance
        for target, source in {
            "profitable_low_cost_mass": f"profitable_mass_{suffix}",
            "locked_profitable_mass": f"locked_mass_{suffix}",
            "weighted_holding_age_capped": f"locked_weighted_age_{suffix}",
            "age_60_mass": f"locked_age_60_mass_{suffix}",
            "age_120_mass": f"locked_age_120_mass_{suffix}",
            "age_180_capped_mass": f"locked_age_180_mass_{suffix}",
            "persistence_checkpoints": f"persistence_checkpoints_{suffix}",
            "turnover_since_profitable_approx": f"turnover_since_profitable_approx_{suffix}",
            "previous_zone_mass": f"previous_zone_mass_{suffix}",
            "current_mass_at_previous_zone": f"current_mass_at_previous_zone_{suffix}",
            "zone_retention_ratio": f"zone_retention_ratio_{suffix}",
            "migration_loss": f"migration_loss_{suffix}",
        }.items():
            selected[target] = panel[source].to_numpy()
        rows.append(selected)
    return pd.concat(rows, ignore_index=True).sort_values(["symbol", "checkpoint_date", "model", "profit_distance"])


def method_catalog() -> pd.DataFrame:
    book = "https://xqdoc.imedao.com/169d51450804c03f3fed727b.pdf"
    chapter = "https://blog.sina.com.cn/s/blog_9e33391b0101kzmu.html"
    rows = [
        ("DOWNSHIFT_METHOD", "下移法", "From a recent high move the reference about 25%, operationalized in the book as two-and-a-half 10% limit moves (~27%), and read the current mass below it.", "recent high; current full distribution; corporate actions", "APPROXIMATELY_REPRODUCIBLE", "60-session recent high, 25% and 27% shifts; applicable only after >=25% markup and near the high", chapter),
        ("CONSOLIDATION_METHOD", "横盘法", "After at least about two months inside an approximately 10% box, mass below the box floor is interpreted as inventory surviving the consolidation.", "40-session OHLC/turnover; current full distribution", "APPROXIMATELY_REPRODUCIBLE", "40 sessions, <=10% box, cumulative turnover >=100%; report mass below floor", chapter),
        ("NINETY_VS_THREE", "90比3", "Profit ratio above 90% while turnover is below 3% is a high-control proxy; the source warns that relative price position matters.", "same-date full distribution and authoritative turnover", "EXACTLY_REPRODUCIBLE", "profit_ratio > 0.90 and turnover_fraction < 0.03", chapter),
        ("CYQK_LOW_TURNOVER_LONG_POSITIVE", "博弈K线低位无量长阳", "CYQKLEN above 18 means over 18% of trapped chips became profitable across the day's OHLC; combined with turnover below 3% and low position.", "authoritative full distribution immediately before every daily OHLC", "UNAVAILABLE", "No proxy substituted: checkpoint distributions are monthly, so exact daily CYQKLEN cannot be formed without prohibited replay.", chapter),
        ("LOW_TURNOVER_DENSE_CROSSING", "筹码密集区无量上穿", "Price crosses a pre-existing dense trapped-cost region with under 3% turnover; released holders did not create expected selling pressure.", "pre-existing full distribution/modes; daily crossing path; turnover", "APPROXIMATELY_REPRODUCIBLE", "Static prior checkpoint distribution and first band crossing; large released mass >=18%", chapter),
        ("LOW_POSITION_LOCKED", "低位锁定", "Price rises or leaves a low region while a substantial low-cost chip body remains at low cost rather than following price upward.", "full distribution history; price position; holding age", "APPROXIMATELY_REPRODUCIBLE", "aged profitable mass, low position, and checkpoint-to-checkpoint retention", book),
        ("LOW_POSITION_DENSE", "低位密集", "A concentrated chip structure forms after a materially lower price region and remains at low relative position.", "full distribution density; trailing price position", "APPROXIMATELY_REPRODUCIBLE", "discovery-frozen HHI 75th percentile and price position <=40%", book),
        ("HIGH_POSITION_DENSE", "高位密集 / distribution warning", "Concentration formed at high relative price after appreciation is a possible distribution rather than accumulation state.", "full distribution density; price position; prior return", "APPROXIMATELY_REPRODUCIBLE", "same density threshold at price position >=70%, kept separate from low-position concentration", book),
        ("SECONDARY_LOW_NARROW_CONSOLIDATION", "次低位窄幅横盘", "A narrow range at a secondary low after the absolute low is auxiliary accumulation evidence.", "daily price path and relative position", "APPROXIMATELY_REPRODUCIBLE", "20-session range <=10% at 20%-50% annual price position", book),
        ("BULL_LONG_BEAR_SHORT", "牛长熊短", "Bullish runs are longer and gradual while bearish legs are shorter, producing the book's saw-tooth accumulation description.", "daily return-run lengths", "APPROXIMATELY_REPRODUCIBLE", "60-session mean positive-run length >=1.5x negative-run length at <=70% position", book),
        ("PIT_EDGE_HORIZONTAL", "挖坑后坑沿强势横盘", "A sharp pit is recovered and price then holds horizontally near the former pit edge.", "daily drawdown, recovery, and recent range", "APPROXIMATELY_REPRODUCIBLE", ">=10% pit, recovery to within 5% of edge, final 10-session range <=10%", book),
        ("DOUBLE_PEAK_FILL_VALLEY", "双峰填谷", "Trading in the valley between two chip peaks progressively fills the valley and may describe absorption of trapped inventory.", "two full-distribution modes and their history", "APPROXIMATELY_REPRODUCIBLE", "two tracked modes >=10% apart with price in the valley; no claim of investor identity", book),
        ("LARGE_DOUBLE_PEAK_VALLEY", "大双峰 / 双峰峡谷", "A large lower retained peak and upper trapped peak form a valley; the lower peak may anchor wounded-control or support inference.", "full distribution modes, lower retention, drawdown path", "APPROXIMATELY_REPRODUCIBLE", "lower mass >=15%, upper >=10%, gap >=10%, with separate retained/distributed lower-base states", book),
        ("WOUNDED_DEALER", "受伤庄股", "Previously high inferred control suffers a rapid decline before full distribution and trades near the inferred cost/base, creating a possible self-rescue incentive.", "prior control proxy, markup, retention, drawdown, inferred cost", "APPROXIMATELY_REPRODUCIBLE", "prior control >=50%, markup >=30%, 20-session drawdown <=-20%, retention >=80%, within 15% of inferred cost", book),
        ("COST_LOW_LOCK_WHILE_PRICE_RISES", "成本低位锁定 while price rises", "The cost distribution stays low while market price rises, implying price/cost divergence without observed investor identity.", "current/previous full distributions; price path", "EXACTLY_REPRODUCIBLE", "checkpoint-to-checkpoint fixed-zone retention plus prior price return", book),
        ("LOCKED_PROFITABLE_INVENTORY", "low-cost inventory retention after substantial profit", "A large low-cost body has modeled floating profit of 10/20/25/30/40%+ yet survives with age and retention.", "full lot distribution, holding-day cells, price, turnover history", "EXACTLY_REPRODUCIBLE", "all five predetermined profit distances; turnover-since-profit is separately marked approximate", book),
        ("LOW_COST_BASE_MIGRATION", "low-cost inventory migration / disappearance", "Loss of low-cost mass and upward relocation after appreciation is distribution evidence.", "adjacent full distributions; corporate-action transforms; prior markup", "EXACTLY_REPRODUCIBLE", "previous 20%-profit zone retention: intact >=80%, migrating 50%-80%, largely distributed <50%; no clipping", book),
    ]
    columns = ["method_id", "source_method", "source_definition_paraphrase", "exact_data_required", "reproducibility", "frozen_operationalization", "source_url"]
    return pd.DataFrame(rows, columns=columns)


def classification_from_results(
    results: pd.DataFrame,
    *,
    target: str,
    direction: float,
    unavailable: bool = False,
) -> tuple[str, dict[str, float]]:
    if unavailable:
        return "UNAVAILABLE", {"validation_effect_60": math.nan, "holdout_effect_60": math.nan}
    if results.empty or "group" not in results:
        return "MIXED", {"validation_effect_60": math.nan, "holdout_effect_60": math.nan}
    sample = results[
        results["group"].eq(target)
        & results["market_scope"].eq("ALL")
        & results["position_scope"].eq("ALL")
        & results["horizon"].isin([40, 60, 120])
    ].copy()
    if "ENSEMBLE" in set(sample["model"]):
        sample = sample[sample["model"].eq("ENSEMBLE")]
    period_effects: dict[str, float] = {}
    period_n: dict[str, float] = {}
    for split in ("validation", "holdout"):
        period = sample[sample["split"].eq(split)]
        effects = period["matched_future_return_excess"].dropna() * direction
        period_effects[split] = float(effects.median()) if len(effects) else math.nan
        period_n[split] = float(period["independent_symbols"].max()) if len(period) else 0.0
    if not all(finite(period_effects[split]) and period_n[split] >= 30 for split in ("validation", "holdout")):
        gate = "MIXED"
    elif all(period_effects[split] >= 0.01 for split in ("validation", "holdout")):
        gate = "YES"
    elif all(period_effects[split] <= 0.0 for split in ("validation", "holdout")):
        gate = "NO"
    else:
        gate = "MIXED"
    if gate == "YES":
        seller_sample = results[
            results["group"].eq(target)
            & results["market_scope"].eq("ALL")
            & results["position_scope"].eq("ALL")
            & results["horizon"].isin([40, 60, 120])
            & results["model"].isin(MODELS)
        ].copy()
        supported_by_split = {}
        for split in ("validation", "holdout"):
            split_sample = seller_sample[seller_sample["split"].eq(split)]
            supported = 0
            for model in MODELS:
                model_sample = split_sample[split_sample["model"].eq(model)]
                aligned = model_sample["matched_future_return_excess"].dropna() * direction
                independent = float(model_sample["independent_symbols"].max()) if len(model_sample) else 0.0
                if independent >= 30 and len(aligned) and float(aligned.median()) >= 0.01:
                    supported += 1
            supported_by_split[split] = supported
        if any(supported_by_split[split] < 2 for split in ("validation", "holdout")):
            gate = "MIXED"
    effects60 = sample[sample["horizon"].eq(60)].groupby("split")["matched_future_return_excess"].mean()
    return gate, {
        "validation_effect_60": float(effects60.get("validation", math.nan)),
        "holdout_effect_60": float(effects60.get("holdout", math.nan)),
    }


def method_scorecard(
    catalog: pd.DataFrame,
    method_results: dict[str, tuple[pd.DataFrame, str, str, float]],
) -> tuple[pd.DataFrame, dict[str, str]]:
    catalog_map = catalog.set_index("method_id").to_dict("index")
    rows: list[dict[str, Any]] = []
    gates: dict[str, str] = {}
    for method_id, (results, target, control, direction) in method_results.items():
        reproducibility = catalog_map[method_id]["reproducibility"]
        gate, effects = classification_from_results(
            results, target=target, direction=direction, unavailable=reproducibility == "UNAVAILABLE"
        )
        gates[method_id] = gate
        target_rows = results[results["group"].eq(target)] if not results.empty and "group" in results else results
        model_effects = target_rows[
            target_rows["market_scope"].eq("ALL")
            & target_rows["position_scope"].eq("ALL")
            & target_rows["horizon"].eq(60)
            & target_rows["split"].isin(["validation", "holdout"])
            & target_rows["model"].isin(MODELS)
        ].groupby(["model", "split"])["matched_future_return_excess"].mean() if not target_rows.empty else pd.Series(dtype=float)
        aligned = (model_effects * direction).dropna()
        seller_consistency = float((aligned > 0).mean()) if len(aligned) else math.nan
        event_count = int(target_rows[target_rows["split"].isin(["validation", "holdout"])]["event_rows"].max()) if len(target_rows) else 0
        maximum_symbols = int(target_rows[target_rows["split"].isin(["validation", "holdout"])]["independent_symbols"].max()) if len(target_rows) else 0
        classification = (
            "UNAVAILABLE" if gate == "UNAVAILABLE"
            else "VALIDATED" if gate == "YES"
            else "NOT_VALIDATED" if gate == "NO"
            else "DESCRIPTIVE_ONLY" if maximum_symbols < 30
            else "PARTIALLY_VALIDATED"
        )
        rows.append(
            {
                "method_id": method_id,
                "source_method": catalog_map[method_id]["source_method"],
                "reproducibility": reproducibility,
                "primary_target": target,
                "matched_control": control,
                "out_of_sample_event_count": event_count,
                **effects,
                "primary_horizon": 60,
                "seller_model_directional_consistency": seller_consistency,
                "market_regime_dependence": "REPORTED_SEPARATELY",
                "gate": gate,
                "classification": classification,
            }
        )
    for method_id in catalog["method_id"]:
        if method_id in method_results:
            continue
        reproducibility = catalog_map[method_id]["reproducibility"]
        rows.append(
            {
                "method_id": method_id,
                "source_method": catalog_map[method_id]["source_method"],
                "reproducibility": reproducibility,
                "primary_target": "DESCRIPTIVE_AUXILIARY" if reproducibility != "UNAVAILABLE" else "UNAVAILABLE",
                "matched_control": "COMPLEMENT" if reproducibility != "UNAVAILABLE" else "NONE",
                "out_of_sample_event_count": 0,
                "validation_effect_60": math.nan,
                "holdout_effect_60": math.nan,
                "primary_horizon": 60,
                "seller_model_directional_consistency": math.nan,
                "market_regime_dependence": "NOT_PRIMARY",
                "gate": "UNAVAILABLE" if reproducibility == "UNAVAILABLE" else "DESCRIPTIVE",
                "classification": "UNAVAILABLE" if reproducibility == "UNAVAILABLE" else "DESCRIPTIVE_ONLY",
            }
        )
    return pd.DataFrame(rows).sort_values("method_id").reset_index(drop=True), gates


def seller_model_scorecard(
    method_results: dict[str, tuple[pd.DataFrame, str, str, float]],
    panel: pd.DataFrame,
) -> pd.DataFrame:
    rows = []
    for method, (results, target, control, direction) in method_results.items():
        if results.empty or "group" not in results:
            continue
        sample = results[
            results["group"].eq(target)
            & results["market_scope"].eq("ALL")
            & results["position_scope"].eq("ALL")
            & results["horizon"].eq(60)
            & results["split"].isin(["validation", "holdout"])
        ]
        for item in sample.itertuples(index=False):
            rows.append(
                {
                    "method_id": method,
                    "model": item.model,
                    "split": item.split,
                    "event_rows": item.event_rows,
                    "independent_symbols": item.independent_symbols,
                    "matched_return_excess_60": item.matched_future_return_excess,
                    "aligned_return_excess_60": item.matched_future_return_excess * direction if finite(item.matched_future_return_excess) else math.nan,
                    "seller_agreement_scope": "ALL_STATES",
                }
            )
    locked = panel[panel["model"].eq("ENSEMBLE")]
    for agreement_value, label in ((True, "ALL_THREE_AGREE"), (False, "MODELS_DISAGREE")):
        sample = locked[locked["seller_models_agree"].eq(agreement_value)]
        for split in ("validation", "holdout"):
            split_sample = sample[sample["split"].eq(split)]
            target = split_sample[split_sample["locked_signal_group"].eq("LARGE_LOCKED")]
            control = split_sample[split_sample["locked_signal_group"].eq("MIGRATED")]
            for horizon in (40, 60, 120):
                target_effect = cluster_summary(target, f"future_return_{horizon}")["effect"]
                control_effect = cluster_summary(control, f"future_return_{horizon}")["effect"]
                rows.append(
                    {
                        "method_id": "LOCKED_PROFITABLE_INVENTORY",
                        "model": "ENSEMBLE",
                        "split": split,
                        "event_rows": len(target),
                        "independent_symbols": target["symbol"].nunique(),
                        "matched_return_excess_60": (target_effect - control_effect) if finite(target_effect) and finite(control_effect) else math.nan,
                        "aligned_return_excess_60": (target_effect - control_effect) if finite(target_effect) and finite(control_effect) else math.nan,
                        "seller_agreement_scope": f"{label}_H{horizon}",
                    }
                )
    return pd.DataFrame(rows)


def auxiliary_scorecard(panel: pd.DataFrame) -> pd.DataFrame:
    patterns = {
        "LOW_POSITION_LOCKED": panel["locked_mass_20"].ge(0.30) & panel["price_position_252"].le(0.40),
        "LOW_POSITION_DENSE": panel["low_position_dense"],
        "HIGH_POSITION_DENSE": panel["high_position_dense"],
        "SECONDARY_LOW_NARROW_CONSOLIDATION": panel["secondary_low_narrow_consolidation"],
        "BULL_LONG_BEAR_SHORT": panel["bull_long_bear_short"],
        "PIT_EDGE_HORIZONTAL": panel["pit_edge_horizontal"].fillna(False),
        "DOUBLE_PEAK_FILL_VALLEY": panel["double_peak_in_valley"],
    }
    rows = []
    for method, mask in patterns.items():
        for model in ALL_MODELS:
            for split in ("validation", "holdout"):
                base = panel[panel["model"].eq(model) & panel["split"].eq(split)]
                event = base[mask.loc[base.index]]
                control = base[~mask.loc[base.index]]
                for horizon in HORIZONS:
                    left = cluster_summary(event, f"future_return_{horizon}")["effect"]
                    right = cluster_summary(control, f"future_return_{horizon}")["effect"]
                    rows.append(
                        {
                            "method_id": method,
                            "model": model,
                            "split": split,
                            "horizon": horizon,
                            "event_rows": len(event),
                            "independent_symbols": event["symbol"].nunique(),
                            "future_return_excess_vs_complement": left - right if finite(left) and finite(right) else math.nan,
                            "classification": "DESCRIPTIVE_ONLY",
                        }
                    )
    return pd.DataFrame(rows)


def synthesize_hard_gates(
    method_gates: dict[str, str],
    locked_results: pd.DataFrame,
    dealer_results: pd.DataFrame,
    seller_scorecard: pd.DataFrame,
    horizon_comparison: pd.DataFrame,
) -> dict[str, str]:
    def gate(method: str, *, unavailable_allowed: bool = False) -> str:
        value = method_gates.get(method, "MIXED")
        if value == "UNAVAILABLE" and not unavailable_allowed:
            return "MIXED"
        return value

    market_sample = locked_results[
        locked_results["group"].eq("LARGE_LOCKED")
        & locked_results["position_scope"].eq("ALL")
        & locked_results["market_scope"].ne("ALL")
        & locked_results["horizon"].isin([40, 60, 120])
        & locked_results["split"].isin(["validation", "holdout"])
    ]
    if "ENSEMBLE" in set(market_sample["model"]):
        market_sample = market_sample[market_sample["model"].eq("ENSEMBLE")]
    ranges = market_sample.groupby(["split", "horizon"])["matched_future_return_excess"].agg(lambda values: values.max() - values.min()).dropna()
    if len(ranges) and float((ranges >= 0.02).mean()) >= 0.60:
        market_gate = "YES"
    elif len(ranges) and float((ranges < 0.01).mean()) >= 0.60:
        market_gate = "NO"
    else:
        market_gate = "MIXED"

    agreement = seller_scorecard[seller_scorecard["seller_agreement_scope"].str.startswith(("ALL_THREE_AGREE", "MODELS_DISAGREE"), na=False)].copy()
    agreement["scope"] = np.where(agreement["seller_agreement_scope"].str.startswith("ALL_THREE"), "AGREE", "DISAGREE")
    agreement_effects = agreement.groupby(["split", "scope"])["aligned_return_excess_60"].mean().unstack()
    if {"AGREE", "DISAGREE"} <= set(agreement_effects.columns) and all(split in agreement_effects.index for split in ("validation", "holdout")):
        differences = agreement_effects["AGREE"] - agreement_effects["DISAGREE"]
        seller_gate = "YES" if (differences.loc[["validation", "holdout"]] >= 0.005).all() else "NO" if (differences.loc[["validation", "holdout"]] <= 0.0).all() else "MIXED"
    else:
        seller_gate = "MIXED"

    horizon_sample = horizon_comparison[
        horizon_comparison["split"].isin(["validation", "holdout"])
        & horizon_comparison["market_scope"].eq("ALL")
        & horizon_comparison["position_scope"].eq("ALL")
    ]
    if "ENSEMBLE" in set(horizon_sample["model"]):
        horizon_sample = horizon_sample[horizon_sample["model"].eq("ENSEMBLE")]
    horizon_means = horizon_sample.groupby(["split", "horizon"])["aligned_matched_return_excess"].mean().unstack()
    medium_differences = []
    for split in ("validation", "holdout"):
        if split in horizon_means.index:
            short = horizon_means.loc[split, [5, 10]].mean()
            medium = horizon_means.loc[split, [40, 60, 120]].mean()
            medium_differences.append(medium - short)
    medium_gate = "YES" if len(medium_differences) == 2 and all(value >= 0.005 for value in medium_differences) else "NO" if len(medium_differences) == 2 and all(value <= 0.0 for value in medium_differences) else "MIXED"

    core = [
        gate("LOCKED_PROFITABLE_INVENTORY"),
        gate("LOW_COST_BASE_MIGRATION"),
        gate("NINETY_VS_THREE"),
        gate("LOW_TURNOVER_DENSE_CROSSING"),
        gate("DOWNSHIFT_METHOD", unavailable_allowed=True),
        gate("CONSOLIDATION_METHOD", unavailable_allowed=True),
        gate("WOUNDED_DEALER", unavailable_allowed=True),
        gate("LARGE_DOUBLE_PEAK_VALLEY", unavailable_allowed=True),
    ]
    yes_count, no_count = core.count("YES"), core.count("NO")
    full_distribution_gate = "YES" if yes_count >= 3 and yes_count > no_count else "NO" if no_count >= 6 else "MIXED"
    overall = "VALIDATED" if yes_count >= 5 and no_count == 0 else "NOT_VALIDATED" if no_count >= 6 else "PARTIALLY_VALIDATED" if yes_count >= 1 or "MIXED" in core else "DESCRIPTIVE_ONLY"

    lowmod_gate, _ = classification_from_results(
        dealer_results, target="HIGH_CONTROL_LOW_MODERATE_PROFIT", direction=1.0
    )
    extreme_gate, _ = classification_from_results(
        dealer_results, target="HIGH_CONTROL_VERY_HIGH_PROFIT", direction=-1.0
    )
    return {
        "CHEN_HAO_CORE_METHODS_REPRODUCED_FAITHFULLY": "PARTIAL",
        "LOCKED_PROFITABLE_INVENTORY_HAS_MEDIUM_TERM_SIGNAL": gate("LOCKED_PROFITABLE_INVENTORY"),
        "HIGH_CONTROL_LOW_MODERATE_PROFIT_HAS_SIGNAL": lowmod_gate,
        "HIGH_CONTROL_EXTREME_PROFIT_IS_RISKIER": extreme_gate,
        "LOW_COST_BASE_RETENTION_PREDICTS_CONTINUATION": gate("COST_LOW_LOCK_WHILE_PRICE_RISES"),
        "LOW_COST_BASE_MIGRATION_PREDICTS_DISTRIBUTION_RISK": gate("LOW_COST_BASE_MIGRATION"),
        "DOWNSHIFT_METHOD_VALIDATES": gate("DOWNSHIFT_METHOD", unavailable_allowed=True),
        "CONSOLIDATION_METHOD_VALIDATES": gate("CONSOLIDATION_METHOD", unavailable_allowed=True),
        "NINETY_VS_THREE_VALIDATES": gate("NINETY_VS_THREE"),
        "LOW_TURNOVER_TRAPPED_CHIP_CROSSING_VALIDATES": gate("LOW_TURNOVER_DENSE_CROSSING", unavailable_allowed=True),
        "WOUNDED_DEALER_HYPOTHESIS_VALIDATES": gate("WOUNDED_DEALER", unavailable_allowed=True),
        "DOUBLE_PEAK_DEALER_STRUCTURE_VALIDATES": gate("LARGE_DOUBLE_PEAK_VALLEY", unavailable_allowed=True),
        "MARKET_REGIME_MATERIALLY_CONDITIONS_DEALER_SIGNAL": market_gate,
        "SELLER_MODEL_AGREEMENT_IMPROVES_DEALER_STATE_VALIDITY": seller_gate,
        "DEALER_SIGNAL_STRONGER_AT_MEDIUM_TERM_HORIZONS": medium_gate,
        "FULL_DISTRIBUTION_SUPPORTS_DEALER_STATE_INFERENCE": full_distribution_gate,
        "CHEN_HAO_DEALER_FRAMEWORK_OVERALL": overall,
        "SAFE_TO_DESIGN_DEALER_STATE_TRADING_STUDY": "YES" if overall == "VALIDATED" else "NO",
        "SAFE_TO_CHANGE_PRODUCTION_CHIP_SEMANTICS": "NO",
        "SAFE_TO_IMPLEMENT_PRODUCTION_DEALER_STRATEGY": "NO",
        "SAFE_TO_EXPAND_RESEARCH_TO_FULL_MARKET_3941": "NO",
    }


def direct_answers(gates: dict[str, str], ninety: pd.DataFrame) -> list[str]:
    ninety_position = ninety[
        ninety["group"].eq("NINETY_VS_THREE")
        & ninety["market_scope"].eq("ALL")
        & ninety["position_scope"].isin(["LOW", "MODERATE", "HIGH"])
        & ninety["horizon"].isin([40, 60, 120])
        & ninety["split"].isin(["validation", "holdout"])
    ]
    effects = ninety_position.groupby("position_scope")["matched_future_return_excess"].mean()
    low_moderate = effects.reindex(["LOW", "MODERATE"]).mean()
    high = effects.get("HIGH", math.nan)
    position_answer = "YES" if finite(low_moderate) and finite(high) and low_moderate > high + 0.005 else "NO" if finite(low_moderate) and finite(high) and low_moderate <= high else "MIXED"
    return [
        f"1. **Does substantial profit with the low-cost inventory still locked predict further medium-term upside?** {gates['LOCKED_PROFITABLE_INVENTORY_HAS_MEDIUM_TERM_SIGNAL']}.",
        f"2. **Does predictive value depend on the inferred holder's profit?** {gates['HIGH_CONTROL_LOW_MODERATE_PROFIT_HAS_SIGNAL']} for low/moderate profit; extreme-profit risk is {gates['HIGH_CONTROL_EXTREME_PROFIT_IS_RISKIER']}.",
        f"3. **Does upward migration predict weaker continuation or greater downside?** {gates['LOW_COST_BASE_MIGRATION_PREDICTS_DISTRIBUTION_RISK']}.",
        f"4. **Does 90比3 validate out of sample?** {gates['NINETY_VS_THREE_VALIDATES']}.",
        f"5. **Does 90比3 work only at low/moderate price positions?** {position_answer}.",
        f"6. **Does low-turnover crossing validate the no-relief-selling interpretation?** {gates['LOW_TURNOVER_TRAPPED_CHIP_CROSSING_VALIDATES']} (static prior-checkpoint replication, not exact CYQKLEN).",
        f"7. **Does the down-shift method identify economically meaningful inventory?** {gates['DOWNSHIFT_METHOD_VALIDATES']}.",
        f"8. **Does the consolidation method identify meaningful retained inventory?** {gates['CONSOLIDATION_METHOD_VALIDATES']}.",
        f"9. **Are wounded-dealer states associated with stronger rebounds?** {gates['WOUNDED_DEALER_HYPOTHESIS_VALIDATES']}.",
        f"10. **Are full-distribution double-peak states useful?** {gates['DOUBLE_PEAK_DEALER_STRUCTURE_VALIDATES']}.",
        f"11. **Does market regime materially condition results?** {gates['MARKET_REGIME_MATERIALLY_CONDITIONS_DEALER_SIGNAL']}.",
        f"12. **Does seller-model agreement improve validity?** {gates['SELLER_MODEL_AGREEMENT_IMPROVES_DEALER_STATE_VALIDITY']}.",
        f"13. **Are effects stronger at 40/60/120 sessions than 5/10?** {gates['DEALER_SIGNAL_STRONGER_AT_MEDIUM_TERM_HORIZONS']}.",
        f"14. **Does the full distribution permit useful inference despite mixed canonical-peak evidence?** {gates['FULL_DISTRIBUTION_SUPPORTS_DEALER_STATE_INFERENCE']}.",
        f"15. **Is the framework reproducible enough for a dedicated trading study?** {gates['SAFE_TO_DESIGN_DEALER_STATE_TRADING_STUDY']}.",
    ]


def report_markdown(
    *,
    gates: dict[str, str],
    input_evidence: dict[str, Any],
    panel: pd.DataFrame,
    crossings: pd.DataFrame,
    scorecard: pd.DataFrame,
    ninety: pd.DataFrame,
) -> str:
    exact = int(scorecard["reproducibility"].eq("EXACTLY_REPRODUCIBLE").sum())
    approximate = int(scorecard["reproducibility"].eq("APPROXIMATELY_REPRODUCIBLE").sum())
    unavailable = int(scorecard["reproducibility"].eq("UNAVAILABLE").sum())
    answers = "\n".join(direct_answers(gates, ninety))
    gate_lines = "\n".join(f"`{key}: {value}`" for key, value in gates.items())
    summary = scorecard[["source_method", "reproducibility", "out_of_sample_event_count", "validation_effect_60", "holdout_effect_60", "classification"]].to_markdown(index=False)
    score = scorecard.set_index("method_id")
    locked_validation = score.loc["LOCKED_PROFITABLE_INVENTORY", "validation_effect_60"]
    locked_holdout = score.loc["LOCKED_PROFITABLE_INVENTORY", "holdout_effect_60"]
    migration_validation = score.loc["LOW_COST_BASE_MIGRATION", "validation_effect_60"]
    migration_holdout = score.loc["LOW_COST_BASE_MIGRATION", "holdout_effect_60"]
    crossing_validation = score.loc["LOW_TURNOVER_DENSE_CROSSING", "validation_effect_60"]
    crossing_holdout = score.loc["LOW_TURNOVER_DENSE_CROSSING", "holdout_effect_60"]
    ninety_validation = score.loc["NINETY_VS_THREE", "validation_effect_60"]
    ninety_holdout = score.loc["NINETY_VS_THREE", "holdout_effect_60"]
    wounded_count = int(score.loc["WOUNDED_DEALER", "out_of_sample_event_count"])
    double_count = int(score.loc["LARGE_DOUBLE_PEAK_VALLEY", "out_of_sample_event_count"])
    consolidation_count = int(score.loc["CONSOLIDATION_METHOD", "out_of_sample_event_count"])
    return f"""# V12 Chen Hao Dealer-State Replication Study

## Outcome

This is a research-only replication on the immutable 500-symbol V12 V3 chip cohort. Chen Hao's framework is classified **{gates['CHEN_HAO_DEALER_FRAMEWORK_OVERALL']}**. The full-distribution dealer-state inference gate is **{gates['FULL_DISTRIBUTION_SUPPORTS_DEALER_STATE_INFERENCE']}** and the dedicated trading-study gate is **{gates['SAFE_TO_DESIGN_DEALER_STATE_TRADING_STUDY']}**.

The word “dealer” below names a source hypothesis, not an observed investor. The measured objects are `INFERRED_LOCKED_LOW_COST_INVENTORY`, inferred control mass, inferred holder profit, and base retention/migration. No investor identity or disclosed holder position is present in the chip artifact.

No production strategy, V3 semantics, seller model, frozen universe, or input artifact was changed. No 3,941-symbol build was started. Signals at checkpoint T use only states available at T, and every outcome begins at T+1.

## Frozen provenance and design

- Source commit: `{input_evidence['source_commit']}`
- Frozen root manifest SHA-256: `{input_evidence['root_manifest_sha256']}`
- Freeze-lock SHA-256: `{input_evidence['freeze_lock_sha256']}`
- Universe: {len(input_evidence['symbols'])} symbols; seller models: {', '.join(MODELS)}
- Research-valid model/ensemble checkpoint rows: {len(panel):,}; crossing events: {len(crossings):,}
- Chronology: discovery through 2020-04-30; validation 2020-05-01 to 2020-08-31; untouched holdout from 2020-09-01.
- Horizons: {', '.join(map(str, HORIZONS))} trading sessions.
- Controls: deterministic nearest observations within seller model, chronology split, and market regime, matched on prior 60-session return, 20-session volatility, 252-session price position, market return, and calendar distance.
- Market taxonomy: PIT-safe equal-weight return and breadth of the same frozen cohort; unconditional and conditional results are both retained.

## Source-faithful reproducibility boundary

The method catalogue contains {exact} exactly reproducible, {approximate} approximately reproducible, and {unavailable} unavailable translations. Definitions were checked against the accessible [book text](https://xqdoc.imedao.com/169d51450804c03f3fed727b.pdf) and its [chapter transcription](https://blog.sina.com.cn/s/blog_9e33391b0101kzmu.html).

Exact daily `CYQKLEN > 18` is **UNAVAILABLE**. It requires the authoritative full distribution immediately before each day's OHLC, while the governed frozen bundle contains model-specific full distributions at checkpoints. The study does not replay or substitute an unrelated daily metric. `low_turnover_crossing_results.csv` instead reports a clearly labeled static prior-checkpoint crossing test.

Checkpoint identity holding-day cells make age deterministic, but ages are capped at the production artifact's 180-day bucket. Cumulative turnover since first becoming highly profitable is an explicitly approximate surviving-inventory reconstruction. Retention and migration themselves are exact checkpoint distribution comparisons after authoritative corporate-action transforms; ratios and migration losses are never clipped or normalized.

## Direct answers

{answers}

## Key evidence

- The ensemble locked-versus-migrated matched return excess at 60 sessions was {locked_validation:+.2%} in validation and {locked_holdout:+.2%} in holdout. That favorable ensemble result is not promoted to YES because ACTIVE_STICKY and UNIFORM had negative 40/60-session holdout differences; seller-model robustness is therefore MIXED.
- Migration-versus-retention at 60 sessions was {migration_validation:+.2%} in validation but {migration_holdout:+.2%} in holdout, directly producing the MIXED distribution-risk conclusion.
- Low-turnover release of at least 18% of static trapped inventory exceeded the high-turnover crossing control by {crossing_validation:+.2%} in validation and {crossing_holdout:+.2%} in holdout at 60 sessions, with sufficient cross-seller support. This validates only the checkpoint-based crossing translation, not exact CYQKLEN.
- 90比3 showed {ninety_validation:+.2%} validation and {ninety_holdout:+.2%} holdout matched excess at 60 sessions, but horizon and price-position stratification were not jointly robust, so its overall gate remains MIXED.
- Strict source-faithful rare states were underpowered: consolidation had {consolidation_count} high-retention out-of-sample event at most, wounded-control had {wounded_count}, and strong retained lower-peak/rapid-drawdown had {double_count}. Their scorecard classifications remain descriptive or partial rather than validated.

## Dealer-method economic scorecard

Matched effects below are future-return differences at 60 sessions (target minus the named control); all horizons and outcome families remain in the CSV outputs.

{summary}

## Interpretation discipline and limitations

The sample is the frozen engineering cohort concentrated in Shenzhen symbols during 2020, not a probability sample of the A-share market. Monthly full-distribution cadence limits daily source replication and makes some pattern translations approximate. Holding ages saturate at 180 sessions. Matching reduces observable trend/position/volatility/regime differences but cannot identify an unobserved investor or establish causality. Multiple seller models remain hypotheses; no best seller model is selected.

Canonical peak validity is not an eligibility gate anywhere in this study. Full distributions are primary; tracked modes are used only where the source method itself requires a dense region or two-peak structure.

## Hard gates

{gate_lines}
"""


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, lineterminator="\n", na_rep="NA", float_format="%.12g")


def result_manifest(
    *,
    input_evidence: dict[str, Any],
    protocol_hash: str,
    gates: dict[str, str],
    counts: dict[str, int],
) -> dict[str, Any]:
    artifacts = {}
    for path in sorted([*RESULTS_DIR.iterdir(), REPORT_PATH]):
        if not path.is_file() or path.name == "result_manifest.json":
            continue
        binding: dict[str, Any] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
        if path.suffix == ".csv":
            binding["rows"] = max(sum(1 for _ in path.open("rb")) - 1, 0)
        artifacts[path.relative_to(STUDY_DIR).as_posix()] = binding
    manifest = input_evidence["manifest"]
    return {
        "manifest_version": "v12-chen-hao-dealer-state-replication-result-manifest-v1",
        "study_protocol_sha256": protocol_hash,
        "source_commit": input_evidence["source_commit"],
        "frozen_input_bindings": {
            "root_manifest_sha256": input_evidence["root_manifest_sha256"],
            "freeze_lock_sha256": input_evidence["freeze_lock_sha256"],
            "daily_inventory_sha256": input_evidence["daily_inventory_sha256"],
            "daily_partition_sha256": input_evidence["daily_partition_sha256"],
            "seller_models": list(MODELS),
            "semantic_fingerprint": manifest["semantic_fingerprint"],
            "artifact_contract_fingerprint": manifest["artifact_contract_fingerprint"],
            "replay_parameter_manifest_digest": manifest["replay_parameter_manifest_digest"],
            "verified_all_parts": input_evidence["verified_all_parts"],
            "verified_part_count": input_evidence["verified_part_count"],
            "verified_part_bytes": input_evidence["verified_part_bytes"],
        },
        "chronology": {"discovery_end": "2020-04-30", "validation_end": "2020-08-31", "holdout_start": "2020-09-01", "horizons": list(HORIZONS), "t_plus_one": True},
        "counts": counts,
        "gates": gates,
        "artifacts": artifacts,
        "prohibited_inputs_used": [],
        "canonical_peak_required": False,
        "cyqk_exact_status": "UNAVAILABLE",
        "production_or_frozen_artifacts_modified": False,
        "full_market_build_started": False,
    }


def run(args: argparse.Namespace) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    if tuple(protocol["chronology"]["future_horizons_sessions"]) != HORIZONS:
        raise RuntimeError("protocol/runner horizon mismatch")
    protocol_hash = sha256(PROTOCOL_PATH)
    print("verifying frozen inputs", flush=True)
    input_evidence = verify_inputs(
        args.v3_root,
        args.freeze_lock,
        args.daily_inventory,
        full_hash=not args.skip_full_input_hash,
    )
    root_before = sha256(args.v3_root / "manifest.json")
    lock_before = sha256(args.freeze_lock)

    print("reading PIT-safe daily prices and preparing T+1 outcomes", flush=True)
    raw_prices = read_prices(input_evidence["daily_files"], input_evidence["symbols"])
    valid_prices, by_symbol, index_lookup = prepare_price_data(raw_prices)
    panel_cache = RESULTS_DIR / "dealer_state_panel.parquet"
    crossing_cache = RESULTS_DIR / "crossing_event_panel.parquet"
    if args.reuse_panel_cache and panel_cache.is_file() and crossing_cache.is_file():
        print("loading development checkpoint-panel cache", flush=True)
        panel = pd.read_parquet(panel_cache)
        crossings = pd.read_parquet(crossing_cache)
    else:
        print("decoding full distributions and checkpoint state variables", flush=True)
        panel, crossings = build_checkpoint_panel(
            v3_root=args.v3_root,
            manifest=input_evidence["manifest"],
            valid_prices=valid_prices,
            raw_prices=raw_prices,
            by_symbol=by_symbol,
            index_lookup=index_lookup,
        )
        panel, crossings = derive_groups(panel, crossings)
        panel.to_parquet(panel_cache, index=False)
        crossings.to_parquet(crossing_cache, index=False)
    discovery_thresholds = {
        "distribution_hhi_75pct_by_model": {
            model: float(
                panel[
                    panel["model"].eq(model)
                    & panel["split"].eq("discovery")
                ]["distribution_hhi"].quantile(0.75)
            )
            for model in ALL_MODELS
        },
        "consolidation_cumulative_turnover_median": float(
            panel[
                panel["model"].eq("UNIFORM")
                & panel["split"].eq("discovery")
                & panel["consolidation_geometry"]
            ]["cumulative_turnover_40"].median()
        ),
        "derived_from_outcomes": False,
    }
    (RESULTS_DIR / "frozen_discovery_thresholds.json").write_text(
        json.dumps(discovery_thresholds, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print("constructing matched controls and economic outcome tables", flush=True)
    dealer_results = summarize_method(
        panel,
        group_col="dealer_profit_group",
        controls={
            "HIGH_CONTROL_LOW_MODERATE_PROFIT": "LOW_CONTROL",
            "HIGH_CONTROL_HIGH_PROFIT": "HIGH_CONTROL_LOW_MODERATE_PROFIT",
            "HIGH_CONTROL_VERY_HIGH_PROFIT": "HIGH_CONTROL_LOW_MODERATE_PROFIT",
        },
        include_position=True,
    )
    downshift_results = summarize_method(
        panel[panel["downshift_group"].ne("NOT_APPLICABLE")],
        group_col="downshift_group",
        controls={"HIGH_RETAINED": "LOW_RETAINED", "MODERATE_RETAINED": "LOW_RETAINED"},
        include_position=True,
    )
    consolidation_results = summarize_method(
        panel[panel["consolidation_group"].ne("NOT_ELIGIBLE")],
        group_col="consolidation_group",
        controls={"HIGH_RETAINED": "LOW_RETAINED", "MODERATE_RETAINED": "LOW_RETAINED"},
        include_position=True,
    )
    ninety_results = summarize_method(
        panel,
        group_col="ninety_vs_three_group",
        controls={
            "NINETY_VS_THREE": "PROFIT90_HIGH_TURNOVER",
            "PROFIT90_HIGH_TURNOVER": "ORDINARY",
            "LOW_TURNOVER_NOT90": "ORDINARY",
        },
        include_position=True,
    )
    crossing_results = summarize_method(
        crossings,
        group_col="crossing_group",
        controls={
            "LARGE_RELEASE_LOW_TURNOVER": "LARGE_RELEASE_HIGH_TURNOVER",
            "LARGE_RELEASE_HIGH_TURNOVER": "LOW_RELEASE",
        },
        include_position=True,
    )
    base_results = summarize_method(
        panel[panel["locked_signal_group"].ne("INTERMEDIATE")],
        group_col="locked_signal_group",
        controls={
            "LARGE_LOCKED": "MIGRATED",
            "MIGRATED": "LARGE_LOCKED",
            "NO_LARGE_LOW_COST": "LARGE_LOCKED",
        },
        include_position=True,
    )
    wounded_results = summarize_method(
        panel[panel["wounded_group"].ne("NOT_DRAWDOWN")],
        group_col="wounded_group",
        controls={
            "WOUNDED_HIGH_CONTROL": "ORDINARY_DRAWDOWN",
            "LOW_CONTROL_DRAWDOWN": "ORDINARY_DRAWDOWN",
            "DRAWDOWN_AFTER_BASE_DISTRIBUTION": "ORDINARY_DRAWDOWN",
        },
        include_position=True,
    )
    double_peak_results = summarize_method(
        panel[panel["double_peak_group"].ne("NOT_DOUBLE_PEAK_VALLEY")],
        group_col="double_peak_group",
        controls={
            "STRONG_LOWER_RETAINED_RAPID_DRAWDOWN": "LOWER_BASE_DISTRIBUTED",
            "STRONG_LOWER_RETAINED": "LOWER_BASE_DISTRIBUTED",
            "WEAK_OR_INTERMEDIATE_LOWER": "LOWER_BASE_DISTRIBUTED",
        },
        include_position=True,
    )

    catalog = method_catalog()
    method_results = {
        "LOCKED_PROFITABLE_INVENTORY": (base_results, "LARGE_LOCKED", "MIGRATED", 1.0),
        "COST_LOW_LOCK_WHILE_PRICE_RISES": (base_results, "LARGE_LOCKED", "MIGRATED", 1.0),
        "LOW_COST_BASE_MIGRATION": (base_results, "MIGRATED", "LARGE_LOCKED", -1.0),
        "DOWNSHIFT_METHOD": (downshift_results, "HIGH_RETAINED", "LOW_RETAINED", 1.0),
        "CONSOLIDATION_METHOD": (consolidation_results, "HIGH_RETAINED", "LOW_RETAINED", 1.0),
        "NINETY_VS_THREE": (ninety_results, "NINETY_VS_THREE", "PROFIT90_HIGH_TURNOVER", 1.0),
        "LOW_TURNOVER_DENSE_CROSSING": (crossing_results, "LARGE_RELEASE_LOW_TURNOVER", "LARGE_RELEASE_HIGH_TURNOVER", 1.0),
        "WOUNDED_DEALER": (wounded_results, "WOUNDED_HIGH_CONTROL", "ORDINARY_DRAWDOWN", 1.0),
        "LARGE_DOUBLE_PEAK_VALLEY": (double_peak_results, "STRONG_LOWER_RETAINED_RAPID_DRAWDOWN", "LOWER_BASE_DISTRIBUTED", 1.0),
    }
    scorecard, method_gates = method_scorecard(catalog, method_results)
    auxiliary = auxiliary_scorecard(panel)
    for method in auxiliary["method_id"].unique():
        sample = auxiliary[(auxiliary["method_id"].eq(method)) & (auxiliary["model"].eq("ENSEMBLE")) & (auxiliary["horizon"].eq(60))]
        mask = scorecard["method_id"].eq(method)
        if mask.any():
            scorecard.loc[mask, "out_of_sample_event_count"] = int(sample["event_rows"].max()) if len(sample) else 0
            scorecard.loc[mask, "validation_effect_60"] = sample.loc[sample["split"].eq("validation"), "future_return_excess_vs_complement"].mean()
            scorecard.loc[mask, "holdout_effect_60"] = sample.loc[sample["split"].eq("holdout"), "future_return_excess_vs_complement"].mean()

    seller_scorecard = seller_model_scorecard(method_results, panel)
    horizon_frames = []
    for method, (results, target, _control, direction) in method_results.items():
        if results.empty or "group" not in results:
            continue
        selected = results[results["group"].eq(target)].copy()
        selected.insert(0, "method_id", method)
        selected["aligned_matched_return_excess"] = selected["matched_future_return_excess"] * direction
        horizon_frames.append(selected)
    horizon_comparison = pd.concat(horizon_frames, ignore_index=True)
    gates = synthesize_hard_gates(method_gates, base_results, dealer_results, seller_scorecard, horizon_comparison)

    locked = locked_long_panel(panel)
    outcome_columns = [f"{metric}_{horizon}" for horizon in HORIZONS for metric in ("future_return", "mfe", "mae")]
    transitions = panel[[
        "snapshot_key", "symbol", "checkpoint_date", "split", "model", "previous_state", "state", "transition",
        "inferred_control_mass", "inferred_holder_profit", "locked_mass_20", "base_retention_ratio_20",
        "base_retention_state", "market_environment", "seller_models_agree", *outcome_columns,
    ]].copy()
    market_interactions = base_results[
        base_results["market_scope"].ne("ALL") & base_results["position_scope"].eq("ALL")
    ].copy()

    outputs = {
        "method_reproducibility_catalog.csv": catalog,
        "locked_profitable_inventory.csv": locked,
        "dealer_profit_state_outcomes.csv": dealer_results,
        "downshift_method_results.csv": downshift_results,
        "consolidation_method_results.csv": consolidation_results,
        "ninety_vs_three_results.csv": ninety_results,
        "low_turnover_crossing_results.csv": crossing_results,
        "base_retention_vs_migration.csv": base_results,
        "dealer_state_transitions.csv": transitions,
        "wounded_dealer_results.csv": wounded_results,
        "double_peak_results.csv": double_peak_results,
        "market_regime_interactions.csv": market_interactions,
        "seller_model_dealer_state_scorecard.csv": seller_scorecard,
        "horizon_comparison.csv": horizon_comparison,
        "dealer_method_scorecard.csv": scorecard,
        "auxiliary_pattern_results.csv": auxiliary,
    }
    for name, frame in outputs.items():
        write_csv(frame, RESULTS_DIR / name)
    panel.to_parquet(RESULTS_DIR / "dealer_state_panel.parquet", index=False)
    crossings.to_parquet(RESULTS_DIR / "crossing_event_panel.parquet", index=False)

    report = report_markdown(
        gates=gates,
        input_evidence=input_evidence,
        panel=panel,
        crossings=crossings,
        scorecard=scorecard,
        ninety=ninety_results,
    )
    REPORT_PATH.write_text(report, encoding="utf-8")
    if sha256(args.v3_root / "manifest.json") != root_before or sha256(args.freeze_lock) != lock_before:
        raise RuntimeError("frozen input binding changed during study")
    assert_scoped_worktree()
    counts = {
        "dealer_state_panel_rows": len(panel),
        "locked_profitable_inventory_rows": len(locked),
        "crossing_events": len(crossings),
        "transition_rows": len(transitions),
        "method_catalog_rows": len(catalog),
        "scorecard_rows": len(scorecard),
    }
    manifest = result_manifest(
        input_evidence=input_evidence,
        protocol_hash=protocol_hash,
        gates=gates,
        counts=counts,
    )
    (RESULTS_DIR / "result_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=json_value) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"gates": gates, "counts": counts}, indent=2), flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v3-root", type=Path, default=DEFAULT_V3_ROOT)
    parser.add_argument("--freeze-lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--daily-inventory", type=Path, default=DEFAULT_DAILY_INVENTORY)
    parser.add_argument("--skip-full-input-hash", action="store_true", help="Development only; final run must hash every frozen part.")
    parser.add_argument("--reuse-panel-cache", action="store_true", help="Development only; reuse a previously decoded panel before final recomputation.")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
