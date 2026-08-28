#!/usr/bin/env python3
"""Run Reverse Wave Study V2 from the immutable V3 fact and production ledger.

The script only reads governed inputs.  Every generated artifact is written below
``research/v12-reverse-wave-v2/results``.  Outcome labels are constructed from
registered CY-006 price fields before any chip feature is joined to the event sample.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from scipy.stats import rankdata


EXPECTED_ROOT_SHA256 = "915686c6b9a069688e4790a1e6a8e699feafaf951ca7b720c11ca8b21b85c29a"
EXPECTED_LOCK_SHA256 = "95a7b33ec28fe3c188b309e962522cb1bea16a23b7647c68068864a1e17fd6d9"
EXPECTED_PARAMETER_ID = "9baed76ec299161c"
EXPECTED_FEATURE_ROWS = 121_251
EXPECTED_STRICT_TEMPORAL_ROWS = 36_219
EXPECTED_SYMBOLS = 500

DEFAULT_DATA_ROOT = Path("/Users/linmei/Documents/CY/data")
DEFAULT_V3_ROOT = DEFAULT_DATA_ROOT / "validation/v12_v3_500_temporal_20260828"
DEFAULT_LOCK = Path(
    "/Users/linmei/Documents/cyq-v3-500-build/V12_V3_500_TEMPORAL_BUILD_LOCK.json"
)
DEFAULT_LEDGER_ROOT = (
    DEFAULT_DATA_ROOT / "validation/v12_lifecycle_entry_exit_ledger_500_20260828"
)
DEFAULT_DAILY_INVENTORY = (
    DEFAULT_DATA_ROOT / "input_inventories/CY-006-pit-b-daily-v2-2018-2026-20260821.json"
)
OUTPUT_DIR = Path(__file__).resolve().parent / "results"

SPLIT_ORDER = ("discovery", "validation", "holdout")
TARGETS = ("any_upside", "up20_20", "up30_40", "up50_60")
REQUESTED_GATES = (
    ("setup_score", ">=", 1.00, "accumulation score"),
    ("breakout_excess_atr", ">=", 0.25, "breakout excess (ATR)"),
    ("retest_depth_atr", "<=", 0.50, "retest depth (ATR)"),
    ("cost_migration_atr", ">=", 0.50, "cost migration (ATR)"),
    ("retest_volume_ratio", "<=", 0.80, "volume ratio"),
    ("retest_turnover_ratio", "<=", 0.80, "turnover ratio"),
    ("exact_root_retention", ">=", 0.70, "root-anchor retention"),
)


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    family: str
    kind: str
    category: str
    description: str


def feature_specs() -> tuple[FeatureSpec, ...]:
    base = (
        FeatureSpec("base_exists", "structural_base", "binary", "absolute_state", "Canonical rolling structural base exists."),
        FeatureSpec("strict_temporal_valid", "structural_base", "binary", "absolute_state", "Base exists with no ambiguity, split, merge, or loss flag."),
        FeatureSpec("peak_track_age", "peak_age", "continuous", "absolute_state", "Canonical V3 tracked-peak age."),
        FeatureSpec("peak_track_mass", "peak_mass", "continuous", "absolute_state", "Canonical V3 tracked-peak mass; never substituted."),
        FeatureSpec("peak_track_prominence", "peak_prominence", "continuous", "absolute_state", "Canonical V3 tracked-peak prominence; never substituted."),
        FeatureSpec("peak_band_width_abs", "peak_shape", "continuous", "absolute_state", "Tracked band upper minus lower in the causal price coordinate."),
        FeatureSpec("peak_band_width_rel_price", "peak_shape", "continuous", "absolute_state", "Tracked band width divided by same-day close."),
        FeatureSpec("peak_location_rel_price", "peak_shape", "continuous", "absolute_state", "Tracked peak divided by same-day close minus one."),
        FeatureSpec("rolling_base_episode_age", "base_persistence", "continuous", "persistence", "Observed consecutive same-base binding age; left-censored when necessary."),
        FeatureSpec("days_since_rebinding", "base_persistence", "continuous", "persistence", "Trading sessions since an in-window observed rebind; left-censored episodes are null."),
        FeatureSpec("rebinding_observed", "base_persistence", "binary", "lifecycle_event", "Current base episode has an observed in-window rebind."),
        FeatureSpec("base_presence_5", "base_persistence", "continuous", "persistence", "Base-existence fraction over T through T-4."),
        FeatureSpec("base_presence_10", "base_persistence", "continuous", "persistence", "Base-existence fraction over T through T-9."),
        FeatureSpec("base_presence_20", "base_persistence", "continuous", "persistence", "Base-existence fraction over T through T-19."),
        FeatureSpec("peak_track_split", "lifecycle_events", "binary", "lifecycle_event", "Canonical V3 split flag."),
        FeatureSpec("peak_track_merge", "lifecycle_events", "binary", "lifecycle_event", "Canonical V3 merge flag."),
        FeatureSpec("peak_track_lost", "lifecycle_events", "binary", "lifecycle_event", "Canonical V3 lost flag."),
        FeatureSpec("split_count_20", "lifecycle_events", "continuous", "persistence", "Split-event count over T through T-19."),
        FeatureSpec("merge_count_20", "lifecycle_events", "continuous", "persistence", "Merge-event count over T through T-19."),
        FeatureSpec("lost_count_20", "lifecycle_events", "continuous", "persistence", "Lost-event count over T through T-19."),
        FeatureSpec("ensemble_ambiguity", "ensemble_ambiguity", "binary", "absolute_state", "Exact-three-model ensemble ambiguity state."),
        FeatureSpec("ambiguity_rate_20", "ensemble_ambiguity", "continuous", "persistence", "Ensemble ambiguity fraction over T through T-19."),
        FeatureSpec("concentration_20", "scalar_chip", "continuous", "absolute_state", "Frozen fact concentration within 20%."),
        FeatureSpec("profit_ratio", "scalar_chip", "continuous", "absolute_state", "Frozen fact profit ratio."),
        FeatureSpec("asr", "scalar_chip", "continuous", "absolute_state", "Frozen fact ASR scalar."),
        FeatureSpec("cbw", "scalar_chip", "continuous", "absolute_state", "Frozen fact CBW scalar."),
        FeatureSpec("average_cost_rel_price", "cost_anchors", "continuous", "absolute_state", "Average cost divided by close minus one."),
        FeatureSpec("p01_rel_price", "cost_anchors", "continuous", "absolute_state", "p01 cost divided by close minus one."),
        FeatureSpec("p10_rel_price", "cost_anchors", "continuous", "absolute_state", "p10 cost divided by close minus one."),
        FeatureSpec("p50_rel_price", "cost_anchors", "continuous", "absolute_state", "p50 cost divided by close minus one."),
        FeatureSpec("p90_rel_price", "cost_anchors", "continuous", "absolute_state", "p90 cost divided by close minus one."),
        FeatureSpec("p99_rel_price", "cost_anchors", "continuous", "absolute_state", "p99 cost divided by close minus one."),
        FeatureSpec("model_spread_cost_p50", "model_consensus", "continuous", "absolute_state", "Seller-model p50 spread from the frozen fact."),
        FeatureSpec("model_spread_cost_p90", "model_consensus", "continuous", "absolute_state", "Seller-model p90 spread from the frozen fact."),
        FeatureSpec("model_spread_dominant_peak_today", "model_consensus", "continuous", "absolute_state", "Seller-model dominant-peak spread."),
    )
    change_sources = (
        ("peak_track_age", "peak_age"),
        ("peak_track_mass", "peak_mass"),
        ("peak_track_prominence", "peak_prominence"),
        ("peak_band_width_rel_price", "peak_shape"),
        ("peak_location_rel_price", "peak_shape"),
        ("base_presence_20", "base_persistence"),
        ("concentration_20", "scalar_chip"),
        ("profit_ratio", "scalar_chip"),
        ("average_cost_rel_price", "cost_anchors"),
        ("p10_rel_price", "cost_anchors"),
        ("p50_rel_price", "cost_anchors"),
        ("p90_rel_price", "cost_anchors"),
    )
    changes = tuple(
        FeatureSpec(
            f"{name}_chg_{lag}",
            family,
            "continuous",
            "recent_change",
            f"PIT-safe T minus T-{lag} change in {name}.",
        )
        for name, family in change_sources
        for lag in (5, 10, 20)
    )
    return base + changes


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_id(*parts: object) -> str:
    return hashlib.sha256("|".join(str(part) for part in parts).encode()).hexdigest()


def json_value(value: Any) -> Any:
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=json_value)


def verify_inputs(v3_root: Path, lock_path: Path, ledger_root: Path, daily_inventory: Path) -> dict[str, Any]:
    root_manifest_path = v3_root / "manifest.json"
    ledger_manifest_path = ledger_root / "manifest.json"
    if sha256(root_manifest_path) != EXPECTED_ROOT_SHA256:
        raise RuntimeError("frozen V3 root manifest hash mismatch")
    if sha256(lock_path) != EXPECTED_LOCK_SHA256:
        raise RuntimeError("authoritative V3 freeze-lock hash mismatch")
    root_manifest = json.loads(root_manifest_path.read_text(encoding="utf-8"))
    symbols = root_manifest.get("symbols", [])
    if len(symbols) != EXPECTED_SYMBOLS or len(set(symbols)) != EXPECTED_SYMBOLS:
        raise RuntimeError("frozen V3 symbol count/uniqueness mismatch")

    feature_parts = {
        item["relative_path"]: item
        for item in root_manifest["parts"]
        if item["relative_path"].endswith("daily_feature_candidate.parquet")
    }
    if len(feature_parts) != EXPECTED_SYMBOLS:
        raise RuntimeError("root manifest does not bind exactly 500 daily feature parts")
    feature_bytes = 0
    for relative, binding in sorted(feature_parts.items()):
        path = v3_root / relative
        if path.stat().st_size != int(binding["bytes"]) or sha256(path) != binding["sha256"]:
            raise RuntimeError(f"frozen feature part mismatch: {relative}")
        feature_bytes += path.stat().st_size

    ledger_manifest = json.loads(ledger_manifest_path.read_text(encoding="utf-8"))
    provenance = ledger_manifest["provenance"]
    if provenance["frozen_root_manifest_sha256"] != EXPECTED_ROOT_SHA256:
        raise RuntimeError("ledger is not bound to the requested V3 root")
    if provenance["frozen_lock_sha256"] != EXPECTED_LOCK_SHA256:
        raise RuntimeError("ledger is not bound to the requested freeze lock")
    if provenance["strategy_parameter_id"] != EXPECTED_PARAMETER_ID:
        raise RuntimeError("ledger parameter ID mismatch")
    ledger_hashes: dict[str, str] = {}
    for name, binding in ledger_manifest["artifacts"].items():
        path = ledger_root / name
        actual = sha256(path)
        if actual != binding["sha256"]:
            raise RuntimeError(f"ledger artifact hash mismatch: {name}")
        ledger_hashes[name] = actual

    inventory = json.loads(daily_inventory.read_text(encoding="utf-8"))
    inventory_items = {item["path"]: item for item in inventory["files"]}
    daily_files: dict[int, Path] = {}
    daily_hashes: dict[str, str] = {}
    for year in (2020, 2021):
        relative = f"partition_year={year}/data_0.parquet"
        item = inventory_items[relative]
        path = Path(inventory["root"]) / relative
        actual = sha256(path)
        if path.stat().st_size != int(item["size"]) or actual != item["sha256"]:
            raise RuntimeError(f"registered CY-006 price partition mismatch: {year}")
        daily_files[year] = path
        daily_hashes[str(year)] = actual
    return {
        "symbols": symbols,
        "daily_files": daily_files,
        "root_manifest_sha256": EXPECTED_ROOT_SHA256,
        "freeze_lock_sha256": EXPECTED_LOCK_SHA256,
        "feature_parts_verified": len(feature_parts),
        "feature_part_bytes_verified": feature_bytes,
        "ledger_manifest_sha256": sha256(ledger_manifest_path),
        "ledger_artifact_sha256": ledger_hashes,
        "daily_inventory_path": str(daily_inventory),
        "daily_inventory_sha256": sha256(daily_inventory),
        "daily_partition_sha256": daily_hashes,
        "ledger_provenance": provenance,
    }


def read_features(v3_root: Path) -> pd.DataFrame:
    columns = (
        "symbol", "trade_date", "snapshot_id", "available_at", "average_cost", "p01", "p10",
        "p50", "p90", "p99", "profit_ratio", "asr", "cbw", "concentration_20",
        "model_spread_cost_p50", "model_spread_cost_p90", "model_spread_dominant_peak_today",
        "tracked_base_peak", "peak_track_id", "peak_track_band_lower", "peak_track_band_upper",
        "peak_track_age", "peak_track_mass", "peak_track_prominence", "peak_track_state",
        "peak_track_ambiguous", "peak_track_split", "peak_track_merge", "peak_track_lost",
        "peak_definition_version", "peak_track_version", "research_valid",
    )
    scan = str(v3_root / "symbol=*" / "daily_feature_candidate.parquet")
    con = duckdb.connect()
    try:
        selected = ",".join(columns)
        frame = con.execute(
            f"SELECT {selected} FROM read_parquet('{scan}', hive_partitioning=false, union_by_name=true) ORDER BY symbol, trade_date"
        ).fetchdf()
    finally:
        con.close()
    if len(frame) != EXPECTED_FEATURE_ROWS or frame["symbol"].nunique() != EXPECTED_SYMBOLS:
        raise RuntimeError("frozen feature row/symbol count mismatch")
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    if frame.duplicated(["symbol", "trade_date"]).any():
        raise RuntimeError("duplicate symbol/date in frozen feature fact")
    return frame


def read_prices(daily_files: dict[int, Path], symbols: list[str]) -> pd.DataFrame:
    con = duckdb.connect()
    try:
        con.execute("CREATE TEMP TABLE selected_symbols(symbol VARCHAR PRIMARY KEY)")
        con.executemany("INSERT INTO selected_symbols VALUES (?)", ((symbol,) for symbol in symbols))
        files = ",".join(f"'{daily_files[year]}'" for year in sorted(daily_files))
        frame = con.execute(
            f"""
            SELECT d.symbol, d.trade_date, d.open, d.high, d.low, d.close, d.preclose,
                   d.bar_valid, d.trade_status, d.share_multiplier, d.corporate_action_count,
                   d.daily_snapshot_id, d.corporate_action_snapshot_id
            FROM read_parquet([{files}]) d
            JOIN selected_symbols s USING (symbol)
            WHERE d.trade_date >= DATE '2020-01-02'
              AND d.trade_date <= DATE '2021-04-30'
            ORDER BY d.symbol, d.trade_date
            """
        ).fetchdf()
    finally:
        con.close()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    if frame.duplicated(["symbol", "trade_date"]).any():
        raise RuntimeError("duplicate symbol/date in registered price input")
    return frame


def _binding_runs(group: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    ids = group["peak_track_id"].astype(object).to_numpy()
    run_age = np.zeros(len(group), dtype=float)
    exact = np.zeros(len(group), dtype=bool)
    previous: object | None = None
    age = 0
    episode_exact = False
    for index, value in enumerate(ids):
        present = value is not None and not pd.isna(value)
        if not present:
            previous = None
            age = 0
            episode_exact = False
            continue
        if previous == value:
            age += 1
        else:
            age = 1
            episode_exact = index > 0
        run_age[index] = age
        exact[index] = episode_exact
        previous = value
    return run_age, exact


def derive_features(features: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    close = prices[["symbol", "trade_date", "close"]]
    frame = features.merge(close, on=["symbol", "trade_date"], how="left", validate="one_to_one")
    if frame["close"].isna().any():
        raise RuntimeError("feature fact does not have exact registered same-day close coverage")
    frame["base_exists"] = frame["peak_track_id"].notna()
    frame["strict_temporal_valid"] = (
        frame["base_exists"]
        & ~frame["peak_track_ambiguous"]
        & ~frame["peak_track_split"]
        & ~frame["peak_track_merge"]
        & ~frame["peak_track_lost"]
    )
    if int(frame["strict_temporal_valid"].sum()) != EXPECTED_STRICT_TEMPORAL_ROWS:
        raise RuntimeError("canonical strict temporal-valid count mismatch")
    frame["ensemble_ambiguity"] = frame["peak_track_state"].eq("ENSEMBLE_PEAK_AMBIGUOUS")
    frame["peak_band_width_abs"] = frame["peak_track_band_upper"] - frame["peak_track_band_lower"]
    frame["peak_band_width_rel_price"] = frame["peak_band_width_abs"] / frame["close"]
    frame["peak_location_rel_price"] = frame["tracked_base_peak"] / frame["close"] - 1.0
    for source in ("average_cost", "p01", "p10", "p50", "p90", "p99"):
        frame[f"{source}_rel_price"] = frame[source] / frame["close"] - 1.0

    groups: list[pd.DataFrame] = []
    peak_specific = {
        "peak_track_age", "peak_track_mass", "peak_track_prominence",
        "peak_band_width_rel_price", "peak_location_rel_price",
    }
    change_sources = (
        "peak_track_age", "peak_track_mass", "peak_track_prominence",
        "peak_band_width_rel_price", "peak_location_rel_price", "base_presence_20",
        "concentration_20", "profit_ratio", "average_cost_rel_price",
        "p10_rel_price", "p50_rel_price", "p90_rel_price",
    )
    for _, group in frame.groupby("symbol", sort=False):
        group = group.sort_values("trade_date").copy()
        run_age, exact = _binding_runs(group)
        group["rolling_base_episode_age"] = np.where(group["base_exists"], run_age, np.nan)
        group["rebinding_observed"] = exact & group["base_exists"].to_numpy()
        group["days_since_rebinding"] = np.where(group["rebinding_observed"], run_age - 1.0, np.nan)
        for window in (5, 10, 20):
            group[f"base_presence_{window}"] = group["base_exists"].astype(float).rolling(window, min_periods=window).mean()
        group["split_count_20"] = group["peak_track_split"].astype(int).rolling(20, min_periods=20).sum()
        group["merge_count_20"] = group["peak_track_merge"].astype(int).rolling(20, min_periods=20).sum()
        group["lost_count_20"] = group["peak_track_lost"].astype(int).rolling(20, min_periods=20).sum()
        group["ambiguity_rate_20"] = group["ensemble_ambiguity"].astype(float).rolling(20, min_periods=20).mean()
        for source in change_sources:
            for lag in (5, 10, 20):
                prior = group[source].shift(lag)
                change = group[source] - prior
                if source in peak_specific:
                    same_id = group["peak_track_id"].notna() & group["peak_track_id"].eq(group["peak_track_id"].shift(lag))
                    change = change.where(same_id)
                group[f"{source}_chg_{lag}"] = change
        groups.append(group)
    return pd.concat(groups, ignore_index=True).sort_values(["symbol", "trade_date"]).reset_index(drop=True)


def construct_price_only_labels(features: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Create T+1 labels using only registered OHLC/preclose price fields."""

    records: list[dict[str, Any]] = []
    price_groups = {symbol: group.reset_index(drop=True) for symbol, group in prices.groupby("symbol", sort=False)}
    for symbol, feature_group in features.groupby("symbol", sort=False):
        price = price_groups.get(symbol)
        if price is None or price.empty:
            continue
        close = price["close"].to_numpy(dtype=float)
        preclose = price["preclose"].to_numpy(dtype=float)
        high = price["high"].to_numpy(dtype=float)
        low = price["low"].to_numpy(dtype=float)
        valid = (
            price["bar_valid"].fillna(False).to_numpy(dtype=bool)
            & np.isfinite(close) & (close > 0)
            & np.isfinite(preclose) & (preclose > 0)
            & np.isfinite(high) & (high > 0)
            & np.isfinite(low) & (low > 0)
        )
        gross = np.where(valid, close / preclose, 1.0)
        economic_close = np.cumprod(gross)
        economic_before = np.r_[1.0, economic_close[:-1]]
        economic_high = economic_before * high / preclose
        economic_low = economic_before * low / preclose
        dates = price["trade_date"].to_numpy()
        positions = {pd.Timestamp(date): index for index, date in enumerate(dates)}
        for feature_position, row in enumerate(feature_group.itertuples(index=False)):
            feature_date = pd.Timestamp(row.trade_date)
            price_position = positions.get(feature_date)
            if price_position is None or price_position + 60 >= len(price):
                continue
            window = slice(price_position, price_position + 61)
            if not bool(valid[window].all()):
                continue
            baseline = float(economic_close[price_position])
            output: dict[str, Any] = {
                "symbol": symbol,
                "feature_date": feature_date,
                "event_start": pd.Timestamp(dates[price_position + 1]),
                "feature_position": feature_position,
                "baseline_economic_close": baseline,
                "price_coordinate": "CY006_CLOSE_PRECLOSE_CHAIN_V1",
                "daily_snapshot_id": str(price.iloc[price_position]["daily_snapshot_id"]),
                "corporate_action_snapshot_id": str(price.iloc[price_position]["corporate_action_snapshot_id"]),
            }
            for pct, horizon in ((20, 20), (30, 40), (50, 60)):
                returns = economic_high[price_position + 1 : price_position + horizon + 1] / baseline - 1.0
                hits = np.flatnonzero(returns >= pct / 100.0)
                output[f"up{pct}_{horizon}"] = bool(len(hits))
                output[f"hit_date_{pct}_{horizon}"] = (
                    pd.Timestamp(dates[price_position + 1 + int(hits[0])]) if len(hits) else pd.NaT
                )
                output[f"max_return_{horizon}"] = float(np.max(returns))
            output["min_return_20"] = float(
                np.min(economic_low[price_position + 1 : price_position + 21] / baseline - 1.0)
            )
            output["min_return_60"] = float(
                np.min(economic_low[price_position + 1 : price_position + 61] / baseline - 1.0)
            )
            output["down10_20"] = output["min_return_20"] <= -0.10
            output["down20_60"] = output["min_return_60"] <= -0.20
            output["neutral_60"] = output["max_return_60"] < 0.10 and output["min_return_60"] > -0.10
            records.append(output)
    labels = pd.DataFrame.from_records(records).sort_values(["symbol", "feature_date"]).reset_index(drop=True)
    labels["any_upside"] = labels[["up20_20", "up30_40", "up50_60"]].any(axis=1)
    labels["split"] = np.select(
        [labels["feature_date"] <= pd.Timestamp("2020-04-30"), labels["feature_date"] <= pd.Timestamp("2020-08-31")],
        ["discovery", "validation"],
        default="holdout",
    )
    if not bool((labels["feature_date"] < labels["event_start"]).all()):
        raise RuntimeError("price label does not start strictly after its feature observation")
    return labels


def segment_events(labels: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Select one trough per near-contiguous winner run and spaced controls."""

    wave_indices: list[int] = []
    segment_details: dict[int, dict[str, Any]] = {}
    wave_positions: dict[str, list[int]] = defaultdict(list)
    for symbol, group in labels.groupby("symbol", sort=False):
        candidate_positions = np.flatnonzero(group["any_upside"].to_numpy(dtype=bool))
        if not len(candidate_positions):
            continue
        chunks = np.split(candidate_positions, np.flatnonzero(np.diff(candidate_positions) > 6) + 1)
        for chunk in chunks:
            candidates = group.iloc[chunk]
            selected_index = int(
                candidates.sort_values(["baseline_economic_close", "feature_date"], kind="stable").index[0]
            )
            wave_indices.append(selected_index)
            selected_position = int(labels.loc[selected_index, "feature_position"])
            wave_positions[symbol].append(selected_position)
            segment_details[selected_index] = {
                "segment_candidate_start": candidates["feature_date"].min(),
                "segment_candidate_end": candidates["feature_date"].max(),
                "segment_candidate_count": len(candidates),
                "segmentation_rule": "UNION_POSITIVE_RUN_GAP_LE_5_SELECT_LOWEST_BASELINE_EARLIEST_TIE",
            }
    waves = labels.loc[sorted(wave_indices)].copy()
    for name in ("segment_candidate_start", "segment_candidate_end", "segment_candidate_count", "segmentation_rule"):
        waves[name] = [segment_details[index][name] for index in waves.index]
    waves["sample_type"] = "upside_wave"
    waves["event_id"] = [
        stable_id("PRICE_WAVE_V2", row.symbol, row.event_start.date(), row.feature_date.date())
        for row in waves.itertuples(index=False)
    ]

    control_indices: list[int] = []
    for symbol, group in labels.groupby("symbol", sort=False):
        selected_wave_positions = np.asarray(wave_positions.get(symbol, []), dtype=int)
        last_selected = -10_000
        for index, row in group.iterrows():
            position = int(row["feature_position"])
            if position < 20 or bool(row["any_upside"]) or position - last_selected < 60:
                continue
            if len(selected_wave_positions) and bool((np.abs(selected_wave_positions - position) <= 60).any()):
                continue
            control_indices.append(int(index))
            last_selected = position
    controls = labels.loc[sorted(control_indices)].copy()
    controls["sample_type"] = "control_window"
    controls["event_id"] = [
        stable_id("PRICE_CONTROL_V2", row.symbol, row.event_start.date(), row.feature_date.date())
        for row in controls.itertuples(index=False)
    ]
    controls["segment_candidate_start"] = pd.NaT
    controls["segment_candidate_end"] = pd.NaT
    controls["segment_candidate_count"] = 0
    controls["segmentation_rule"] = "NONWINNER_AFTER_20_SESSION_HISTORY_GREEDY_60_SESSION_SPACING_EXCLUDE_PLUS_MINUS_60_FROM_WAVE"

    if waves["event_id"].duplicated().any() or controls["event_id"].duplicated().any():
        raise RuntimeError("duplicate deterministic event ID")
    if bool(controls["any_upside"].any()):
        raise RuntimeError("control sample contains an upside winner")
    event_sample = pd.concat([waves, controls], ignore_index=True).sort_values(
        ["feature_date", "symbol", "sample_type"]
    ).reset_index(drop=True)
    return waves.reset_index(drop=True), controls.reset_index(drop=True), event_sample


def auc_rank(y: np.ndarray, values: np.ndarray) -> float:
    mask = np.isfinite(values)
    y = y[mask].astype(bool)
    values = values[mask]
    n1 = int(y.sum())
    n0 = len(y) - n1
    if n1 == 0 or n0 == 0:
        return math.nan
    ranks = rankdata(values, method="average")
    return float((ranks[y].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def wilson(successes: int, total: int) -> tuple[float, float]:
    if total <= 0:
        return math.nan, math.nan
    z = 1.959963984540054
    p = successes / total
    denominator = 1.0 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return center - half, center + half


def cluster_bootstrap_auc(frame: pd.DataFrame, target: str, feature: str, *, repetitions: int = 200) -> tuple[float, float]:
    subset = frame[["symbol", target, feature]].dropna()
    grouped = {symbol: group for symbol, group in subset.groupby("symbol", sort=False)}
    symbols = np.asarray(sorted(grouped))
    if len(symbols) < 10:
        return math.nan, math.nan
    rng = np.random.default_rng(20260828)
    estimates: list[float] = []
    for _ in range(repetitions):
        sampled = rng.choice(symbols, size=len(symbols), replace=True)
        parts = [grouped[str(symbol)] for symbol in sampled]
        boot = pd.concat(parts, ignore_index=True)
        estimate = auc_rank(boot[target].to_numpy(), boot[feature].to_numpy(dtype=float))
        if math.isfinite(estimate):
            estimates.append(estimate)
    if len(estimates) < repetitions * 0.8:
        return math.nan, math.nan
    return float(np.quantile(estimates, 0.025)), float(np.quantile(estimates, 0.975))


def distribution(values: Iterable[float]) -> dict[str, Any]:
    array = np.asarray(list(values), dtype=float)
    array = array[np.isfinite(array)]
    if not len(array):
        return {"n": 0, "min": None, "p10": None, "p25": None, "median": None, "p75": None, "p90": None, "max": None}
    quantiles = np.quantile(array, [0.10, 0.25, 0.50, 0.75, 0.90])
    return {
        "n": len(array), "min": float(array.min()), "p10": float(quantiles[0]),
        "p25": float(quantiles[1]), "median": float(quantiles[2]),
        "p75": float(quantiles[3]), "p90": float(quantiles[4]), "max": float(array.max()),
    }


def feature_analysis(event_sample: pd.DataFrame, specs: tuple[FeatureSpec, ...]) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    threshold_rows: list[dict[str, Any]] = []
    for target in TARGETS:
        for split in SPLIT_ORDER:
            split_frame = event_sample[event_sample["split"].eq(split)]
            for spec in specs:
                winner = split_frame[split_frame[target]][spec.name].dropna().astype(float)
                nonwinner = split_frame[~split_frame[target]][spec.name].dropna().astype(float)
                auc = auc_rank(split_frame[target].to_numpy(), split_frame[spec.name].to_numpy(dtype=float))
                ci_low = ci_high = math.nan
                if target == "any_upside" and len(winner) >= 20 and len(nonwinner) >= 20:
                    ci_low, ci_high = cluster_bootstrap_auc(split_frame, target, spec.name)
                winner_total = int(split_frame[target].sum())
                nonwinner_total = len(split_frame) - winner_total
                rows.append(
                    {
                        "target": target, "split": split, "feature": spec.name,
                        "family": spec.family, "kind": spec.kind, "category": spec.category,
                        "winner_total": winner_total, "winner_available": len(winner),
                        "winner_coverage": len(winner) / winner_total if winner_total else math.nan,
                        "nonwinner_total": nonwinner_total, "nonwinner_available": len(nonwinner),
                        "nonwinner_coverage": len(nonwinner) / nonwinner_total if nonwinner_total else math.nan,
                        "winner_median": winner.median() if len(winner) else math.nan,
                        "nonwinner_median": nonwinner.median() if len(nonwinner) else math.nan,
                        "auc_winner_higher": auc, "auc_cluster_ci_low": ci_low, "auc_cluster_ci_high": ci_high,
                    }
                )

        discovery = event_sample[event_sample["split"].eq("discovery")]
        for spec in (item for item in specs if item.kind == "continuous"):
            discovery_winners = discovery[discovery[target]][spec.name].dropna().astype(float)
            discovery_auc = auc_rank(discovery[target].to_numpy(), discovery[spec.name].to_numpy(dtype=float))
            if len(discovery_winners) < 20 or not math.isfinite(discovery_auc):
                continue
            direction = "higher" if discovery_auc >= 0.5 else "lower"
            for requested_coverage in (0.80, 0.90, 0.95):
                quantile = 1.0 - requested_coverage if direction == "higher" else requested_coverage
                threshold = float(np.quantile(discovery_winners, quantile, method="nearest"))
                for split in SPLIT_ORDER:
                    evaluation = event_sample[event_sample["split"].eq(split)]
                    values = evaluation[spec.name].astype(float)
                    passed = values.ge(threshold) if direction == "higher" else values.le(threshold)
                    passed = passed & values.notna()
                    winners = evaluation[target]
                    winner_pass = int((passed & winners).sum())
                    winner_total = int(winners.sum())
                    winner_available = int((winners & values.notna()).sum())
                    nonwinner_pass = int((passed & ~winners).sum())
                    nonwinner_total = int((~winners).sum())
                    pass_total = int(passed.sum())
                    precision = winner_pass / pass_total if pass_total else math.nan
                    base_rate = winner_total / len(evaluation) if len(evaluation) else math.nan
                    low, high = wilson(winner_pass, winner_total)
                    threshold_rows.append(
                        {
                            "target": target, "feature": spec.name, "family": spec.family,
                            "direction_fit_discovery": direction, "requested_discovery_coverage": requested_coverage,
                            "threshold_fit_discovery": threshold, "evaluation_split": split,
                            "winner_total": winner_total, "winner_available": winner_available,
                            "winner_pass": winner_pass,
                            "winner_recall_missing_as_fail": winner_pass / winner_total if winner_total else math.nan,
                            "winner_recall_ci_low": low, "winner_recall_ci_high": high,
                            "winner_recall_available": winner_pass / winner_available if winner_available else math.nan,
                            "nonwinner_total": nonwinner_total, "nonwinner_pass": nonwinner_pass,
                            "nonwinner_pass_rate": nonwinner_pass / nonwinner_total if nonwinner_total else math.nan,
                            "precision_in_event_sample": precision, "event_sample_base_rate": base_rate,
                            "lift_in_event_sample": precision / base_rate if base_rate and math.isfinite(precision) else math.nan,
                        }
                    )
    return pd.DataFrame(rows), pd.DataFrame(threshold_rows)


def lead_analysis(event_sample: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    core = (
        "base_exists", "peak_track_age", "peak_track_mass", "peak_track_prominence",
        "peak_band_width_rel_price", "peak_location_rel_price", "base_presence_20",
        "ensemble_ambiguity", "concentration_20", "profit_ratio", "average_cost_rel_price", "p50_rel_price",
    )
    indexed = {symbol: group.reset_index(drop=True) for symbol, group in features.groupby("symbol", sort=False)}
    records: list[dict[str, Any]] = []
    for event in event_sample.itertuples(index=False):
        group = indexed[event.symbol]
        position = int(event.feature_position)
        for lead in (1, 5, 10, 20):
            source_position = position - (lead - 1)
            if source_position < 0:
                continue
            source = group.iloc[source_position]
            for feature in core:
                records.append(
                    {
                        "event_id": event.event_id, "symbol": event.symbol, "split": event.split,
                        "lead_trading_sessions": lead, "feature": feature, "value": source[feature],
                        **{target: bool(getattr(event, target)) for target in TARGETS},
                    }
                )
    long = pd.DataFrame(records)
    output: list[dict[str, Any]] = []
    for target in TARGETS:
        for (split, lead, feature), group in long.groupby(["split", "lead_trading_sessions", "feature"], sort=True):
            values = pd.to_numeric(group["value"], errors="coerce").astype(float)
            winners = group[target].astype(bool)
            output.append(
                {
                    "target": target, "split": split, "lead_trading_sessions": lead, "feature": feature,
                    "winner_total": int(winners.sum()), "winner_available": int((winners & values.notna()).sum()),
                    "nonwinner_total": int((~winners).sum()), "nonwinner_available": int((~winners & values.notna()).sum()),
                    "winner_median": values[winners].median(), "nonwinner_median": values[~winners].median(),
                    "auc_winner_higher": auc_rank(winners.to_numpy(), values.to_numpy(dtype=float)),
                }
            )
    return pd.DataFrame(output)


def read_ledgers(ledger_root: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    lifecycle = pq.read_table(ledger_root / "lifecycle_events.parquet").to_pandas()
    gates = pq.read_table(ledger_root / "decision_gates.parquet").to_pandas()
    execution = pq.read_table(ledger_root / "execution_events.parquet").to_pandas()
    lifecycle["decision_date"] = pd.to_datetime(lifecycle["decision_at"], utc=True).dt.tz_convert("Asia/Shanghai").dt.tz_localize(None).dt.normalize()
    gates["decision_date"] = pd.to_datetime(gates["decision_at"], utc=True).dt.tz_convert("Asia/Shanghai").dt.tz_localize(None).dt.normalize()
    if len(execution):
        execution["decision_date"] = pd.to_datetime(execution["decision_at"], utc=True).dt.tz_convert("Asia/Shanghai").dt.tz_localize(None).dt.normalize()
    return lifecycle, gates, execution


def production_attribution(
    waves: pd.DataFrame,
    lifecycle: pd.DataFrame,
    gates: pd.DataFrame,
    execution: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    lifecycle_day = {
        key: group.sort_values(["event_at", "event_id"])
        for key, group in lifecycle.groupby(["symbol", "decision_date"], sort=False)
    }
    gates_day = {
        key: group.sort_values(["gate_order", "gate_id"])
        for key, group in gates.groupby(["symbol", "decision_date"], sort=False)
    }
    execution_symbol = {symbol: group for symbol, group in execution.groupby("symbol", sort=False)} if len(execution) else {}
    rows: list[dict[str, Any]] = []
    failed_rows: list[dict[str, Any]] = []
    for event in waves.itertuples(index=False):
        key = (event.symbol, pd.Timestamp(event.feature_date).normalize())
        day_events = lifecycle_day.get(key)
        day_gates = gates_day.get(key)
        exact_coverage = day_events is not None and day_gates is not None
        prior_execution = execution_symbol.get(event.symbol)
        if prior_execution is not None:
            prior_execution = prior_execution[
                pd.to_datetime(prior_execution["decision_at"], utc=True)
                < pd.Timestamp(event.event_start, tz="Asia/Shanghai").tz_convert("UTC")
            ]
        types = set(day_events["event_type"].astype(str)) if day_events is not None else set()
        states = set(day_events["state_after"].dropna().astype(str)) if day_events is not None else set()
        execution_types = set(prior_execution["event_type"].astype(str)) if prior_execution is not None else set()
        if "ENTRY_FILLED" in execution_types:
            category = "already holding before event" if "EXIT_FILLED" not in execution_types else "actually entered before the wave"
        elif "ENTRY_EXECUTION_ATTEMPT" in execution_types or "ENTRY_DEFERRED_OR_FAILED" in execution_types:
            category = "execution attempted but not filled"
        elif "ENTRY_INTENT" in execution_types:
            category = "entry intent created"
        elif "QUALIFIED" in types:
            category = "qualified"
        elif "BREAKOUT_OBSERVED" in types or "BREAKOUT" in states:
            category = "breakout qualified but retest/gates failed"
        elif "BREAKOUT_REJECTED" in types or "ACCUMULATING" in states:
            category = "breakout not qualified"
        elif "SETUP_OBSERVED" in types:
            category = "setup observed"
        elif exact_coverage:
            category = "no setup"
        else:
            category = "unavailable/other authoritative state"

        failed = (
            day_gates[day_gates["blocking"] & ~day_gates["passed"]].copy()
            if day_gates is not None else pd.DataFrame()
        )
        first = day_gates[day_gates["first_failed"]] if day_gates is not None else pd.DataFrame()
        first_name = str(first.iloc[0]["gate_name"]) if len(first) else None
        all_failed = failed["gate_name"].astype(str).tolist() if len(failed) else []
        details = []
        for gate in failed.itertuples(index=False):
            detail = {
                "gate_name": gate.gate_name, "gate_order": int(gate.gate_order),
                "observed_json": gate.observed_json, "operator": gate.operator,
                "threshold_json": gate.threshold_json, "reason_code": gate.reason_code,
                "source_function": gate.source_function, "first_failed": bool(gate.first_failed),
            }
            details.append(detail)
            failed_rows.append({"event_id": event.event_id, "symbol": event.symbol, "event_start": event.event_start, **detail})
        entered = "ENTRY_FILLED" in execution_types
        authoritative_miss = bool(exact_coverage and not entered)
        rows.append(
            {
                "event_id": event.event_id, "symbol": event.symbol, "feature_date": event.feature_date,
                "event_start": event.event_start, "production_category": category,
                "production_state_after_json": canonical_json(sorted(states)),
                "production_event_types_json": canonical_json(sorted(types)),
                "first_failed_gate": first_name, "all_failed_gates_json": canonical_json(all_failed),
                "failed_gate_details_json": canonical_json(details),
                "exact_same_decision_ledger_coverage": bool(exact_coverage),
                "entry_fill_before_event": entered,
                "missed_winner_authoritatively_proven": authoritative_miss,
            }
        )
    return pd.DataFrame(rows), pd.DataFrame(failed_rows)


def threshold_audit(event_sample: pd.DataFrame, gates: pd.DataFrame) -> pd.DataFrame:
    event_keys = event_sample[["event_id", "symbol", "feature_date", "sample_type", *TARGETS]].copy()
    event_keys["decision_date"] = pd.to_datetime(event_keys["feature_date"]).dt.normalize()
    requested_names = [item[0] for item in REQUESTED_GATES]
    gate_subset = gates[gates["gate_name"].isin(requested_names)].copy()
    joined = event_keys.merge(gate_subset, on=["symbol", "decision_date"], how="left", validate="one_to_many")
    all_day_gates = event_keys[["event_id", "symbol", "decision_date"]].merge(
        gates[["symbol", "decision_date", "gate_order", "blocking", "passed"]],
        on=["symbol", "decision_date"], how="left",
    )
    prior_status: dict[tuple[str, int], bool] = {}
    for event_id, group in all_day_gates.groupby("event_id", sort=False):
        group = group.dropna(subset=["gate_order"]).sort_values("gate_order")
        prior_pass = True
        for row in group.itertuples(index=False):
            prior_status[(str(event_id), int(row.gate_order))] = prior_pass
            if bool(row.blocking) and not bool(row.passed):
                prior_pass = False
    joined["prior_blocking_pass"] = [
        prior_status.get((str(row.event_id), int(row.gate_order)), False)
        if pd.notna(row.gate_order) else False
        for row in joined.itertuples(index=False)
    ]
    rows: list[dict[str, Any]] = []
    for gate_name, expected_operator, expected_threshold, label in REQUESTED_GATES:
        global_gate = gates[gates["gate_name"].eq(gate_name)].copy()
        evaluated = joined[joined["gate_name"].eq(gate_name)].copy()
        winners = evaluated[evaluated["sample_type"].eq("upside_wave")]
        controls = evaluated[evaluated["sample_type"].eq("control_window")]
        winner_pass = int(winners["passed"].sum()) if len(winners) else 0
        control_pass = int(controls["passed"].sum()) if len(controls) else 0
        pass_total = winner_pass + control_pass
        base_rate = len(winners) / len(evaluated) if len(evaluated) else math.nan
        precision = winner_pass / pass_total if pass_total else math.nan
        conditional = evaluated[evaluated["prior_blocking_pass"]]
        cw = conditional[conditional["sample_type"].eq("upside_wave")]
        cc = conditional[conditional["sample_type"].eq("control_window")]
        observed_thresholds = sorted(set(evaluated["threshold_json"].dropna().astype(str)))
        observed_operators = sorted(set(evaluated["operator"].dropna().astype(str)))
        rows.append(
            {
                "gate_name": gate_name, "gate_label": label,
                "expected_operator": expected_operator, "expected_threshold": expected_threshold,
                "authoritative_status": "EVALUATED" if len(evaluated) else "NOT_REACHED_AUTHORITATIVE",
                "observed_operators_json": canonical_json(observed_operators),
                "observed_thresholds_json": canonical_json(observed_thresholds),
                "global_evaluated_rows": len(global_gate),
                "global_pass_rows": int(global_gate["passed"].astype(bool).sum()) if len(global_gate) else 0,
                "global_pass_rate": global_gate["passed"].astype(bool).mean() if len(global_gate) else math.nan,
                "global_distribution_json": canonical_json(distribution(global_gate["observed_number"])),
                "winner_evaluated": len(winners), "winner_distribution_json": canonical_json(distribution(winners["observed_number"])),
                "winner_pass": winner_pass, "winner_pass_rate": winner_pass / len(winners) if len(winners) else math.nan,
                "missed_winner_rejection_count": int((~winners["passed"].astype(bool)).sum()) if len(winners) else 0,
                "control_evaluated": len(controls), "control_distribution_json": canonical_json(distribution(controls["observed_number"])),
                "control_pass": control_pass, "control_pass_rate": control_pass / len(controls) if len(controls) else math.nan,
                "precision_in_evaluated_event_sample": precision, "evaluated_event_base_rate": base_rate,
                "lift_in_evaluated_event_sample": precision / base_rate if base_rate and math.isfinite(precision) else math.nan,
                "conditional_winner_n": len(cw), "conditional_winner_pass_rate": cw["passed"].mean() if len(cw) else math.nan,
                "conditional_control_n": len(cc), "conditional_control_pass_rate": cc["passed"].mean() if len(cc) else math.nan,
                "conditional_pass_rate_delta": (
                    cw["passed"].mean() - cc["passed"].mean() if len(cw) and len(cc) else math.nan
                ),
            }
        )
    return pd.DataFrame(rows)


def sample_summary(labels: pd.DataFrame, event_sample: pd.DataFrame, attribution: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for split in SPLIT_ORDER:
        raw = labels[labels["split"].eq(split)]
        events = event_sample[event_sample["split"].eq(split)]
        winners = events[events["sample_type"].eq("upside_wave")]
        controls = events[events["sample_type"].eq("control_window")]
        for target in TARGETS:
            raw_count = int(raw[target].sum())
            event_count = int(winners[target].sum())
            low, high = wilson(raw_count, len(raw))
            rows.append(
                {
                    "split": split, "target": target, "raw_candidate_rows": len(raw),
                    "raw_positive_rows": raw_count, "raw_base_rate": raw_count / len(raw) if len(raw) else math.nan,
                    "raw_base_rate_ci_low": low, "raw_base_rate_ci_high": high,
                    "deduplicated_wave_events": event_count, "all_deduplicated_waves": len(winners),
                    "spaced_control_events": len(controls),
                }
            )
    rows.append(
        {
            "split": "all", "target": "authoritative_attribution", "raw_candidate_rows": len(labels),
            "raw_positive_rows": int(labels["any_upside"].sum()),
            "raw_base_rate": labels["any_upside"].mean(), "raw_base_rate_ci_low": math.nan,
            "raw_base_rate_ci_high": math.nan,
            "deduplicated_wave_events": len(attribution),
            "all_deduplicated_waves": len(attribution),
            "spaced_control_events": int(event_sample["sample_type"].eq("control_window").sum()),
            "attribution_exact_count": int(attribution["exact_same_decision_ledger_coverage"].sum()),
            "authoritative_missed_winners": int(attribution["missed_winner_authoritatively_proven"].sum()),
        }
    )
    return pd.DataFrame(rows)


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    table = pa.Table.from_pandas(frame, preserve_index=False)
    pq.write_table(table, path, compression="zstd", use_dictionary=True)


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, float_format="%.10g")


def output_manifest(output_dir: Path, input_evidence: dict[str, Any], counts: dict[str, Any]) -> dict[str, Any]:
    artifacts = {}
    for path in sorted(output_dir.iterdir()):
        if path.name == "manifest.json" or not path.is_file():
            continue
        artifacts[path.name] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    payload = {
        "study": "Reverse Wave Study V2",
        "study_contract_version": "reverse-wave-v2-pit-price-ledger-v1",
        "baseline_implementation_commit": "f502367049ad291dc703c63fdd594798171c9e97",
        "price_wave_label_policy": {
            "feature_observation": "bar T available at 15:00 Asia/Shanghai",
            "event_start": "next recorded trading session T+1",
            "coordinate": "cumulative close/preclose; future high and low mapped through the same chain",
            "upside_labels": ["+20% within 20", "+30% within 40", "+50% within 60"],
            "downside_labels": ["-10% within 20", "-20% within 60", "neutral +/-10% within 60"],
            "wave_segmentation": "union-positive candidate runs allowing <=5 intervening noncandidates; select lowest economic baseline, earliest tie",
            "control_segmentation": "nonwinner starts after 20 sessions of feature history, >=60 sessions apart, and >60 sessions from selected wave starts",
        },
        "chronological_splits": {
            "discovery": "feature_date <= 2020-04-30",
            "validation": "2020-05-01 <= feature_date <= 2020-08-31",
            "holdout": "feature_date >= 2020-09-01",
        },
        "input_evidence": input_evidence,
        "counts": counts,
        "artifacts": artifacts,
    }
    (output_dir / "manifest.json").write_text(json.dumps(payload, indent=2, sort_keys=True, default=json_value) + "\n", encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v3-root", type=Path, default=DEFAULT_V3_ROOT)
    parser.add_argument("--freeze-lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--ledger-root", type=Path, default=DEFAULT_LEDGER_ROOT)
    parser.add_argument("--daily-inventory", type=Path, default=DEFAULT_DAILY_INVENTORY)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    input_evidence = verify_inputs(args.v3_root, args.freeze_lock, args.ledger_root, args.daily_inventory)
    features = read_features(args.v3_root)
    prices = read_prices(input_evidence["daily_files"], input_evidence["symbols"])
    derived = derive_features(features, prices)
    labels = construct_price_only_labels(features, prices)
    waves, controls, event_sample = segment_events(labels)
    specs = feature_specs()
    catalog = pd.DataFrame([spec.__dict__ for spec in specs])
    event_sample = event_sample.merge(
        derived[["symbol", "trade_date", *[spec.name for spec in specs], "snapshot_id", "available_at", "peak_track_id", "peak_track_state"]],
        left_on=["symbol", "feature_date"], right_on=["symbol", "trade_date"], how="left", validate="one_to_one",
    ).drop(columns=["trade_date"])
    feature_stats, coverage_thresholds = feature_analysis(event_sample, specs)
    lead_stats = lead_analysis(event_sample, derived)
    lifecycle, gates, execution = read_ledgers(args.ledger_root)
    attribution, failed_gates = production_attribution(waves, lifecycle, gates, execution)
    gate_audit = threshold_audit(event_sample, gates)
    summary = sample_summary(labels, event_sample, attribution)

    if not bool((pd.to_datetime(event_sample["available_at"]).dt.tz_localize(None) < event_sample["event_start"]).all()):
        raise RuntimeError("event sample contains a feature not strictly available before event start")
    if not bool(attribution["exact_same_decision_ledger_coverage"].all()):
        raise RuntimeError("not every price-defined wave has exact same-decision ledger coverage")
    if not bool(attribution["missed_winner_authoritatively_proven"].all()):
        raise RuntimeError("not every claimed missed winner is authoritatively proven")

    price_columns = [
        "symbol", "feature_date", "event_start", "feature_position", "baseline_economic_close",
        "price_coordinate", "daily_snapshot_id", "corporate_action_snapshot_id", "split",
        "up20_20", "hit_date_20_20", "max_return_20", "up30_40", "hit_date_30_40",
        "max_return_40", "up50_60", "hit_date_50_60", "max_return_60", "any_upside",
        "min_return_20", "min_return_60", "down10_20", "down20_60", "neutral_60",
    ]
    write_parquet(labels[price_columns], args.output_dir / "price_wave_labels.parquet")
    write_parquet(event_sample, args.output_dir / "event_sample.parquet")
    write_parquet(event_sample[event_sample["sample_type"].eq("upside_wave")], args.output_dir / "wave_events.parquet")
    write_parquet(event_sample[event_sample["sample_type"].eq("control_window")], args.output_dir / "control_events.parquet")
    write_parquet(attribution, args.output_dir / "production_attribution.parquet")
    write_parquet(failed_gates, args.output_dir / "rejected_winner_gates.parquet")
    write_csv(catalog, args.output_dir / "feature_catalog.csv")
    write_csv(feature_stats, args.output_dir / "feature_univariate.csv")
    write_csv(coverage_thresholds, args.output_dir / "feature_threshold_coverage.csv")
    write_csv(lead_stats, args.output_dir / "feature_lead_analysis.csv")
    write_csv(gate_audit, args.output_dir / "threshold_audit.csv")
    write_csv(summary, args.output_dir / "sample_summary.csv")
    write_csv(
        attribution.groupby("production_category", dropna=False).size().rename("wave_events").reset_index(),
        args.output_dir / "production_attribution_counts.csv",
    )

    counts = {
        "frozen_feature_rows": len(features),
        "strict_temporal_valid_rows": int(derived["strict_temporal_valid"].sum()),
        "price_label_candidate_rows": len(labels),
        "raw_any_upside_rows": int(labels["any_upside"].sum()),
        "deduplicated_wave_events": len(waves),
        "spaced_control_events": len(controls),
        "authoritative_attributed_waves": int(attribution["exact_same_decision_ledger_coverage"].sum()),
        "authoritative_missed_winners": int(attribution["missed_winner_authoritatively_proven"].sum()),
        "entry_execution_rows": len(execution),
    }
    output_manifest(args.output_dir, {key: value for key, value in input_evidence.items() if key not in {"symbols", "daily_files"}}, counts)
    if sha256(args.v3_root / "manifest.json") != EXPECTED_ROOT_SHA256 or sha256(args.freeze_lock) != EXPECTED_LOCK_SHA256:
        raise RuntimeError("frozen input identity changed during the study")
    print(json.dumps(counts, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
