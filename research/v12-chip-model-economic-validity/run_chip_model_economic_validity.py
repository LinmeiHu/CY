#!/usr/bin/env python3
# ruff: noqa: E501
"""Run the research-only V12 chip-model economic-validity study.

The runner reads the immutable 500-symbol V3 checkpoint/journal bundle and the
registered PIT-B daily price asset.  It never rewrites either input and never
uses strategy decisions, strategy P&L, winner labels, or the lifecycle ledger.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import duckdb
import numpy as np
import pandas as pd

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
OUTPUT_DIR = STUDY_DIR / "results"
PROTOCOL_PATH = STUDY_DIR / "preregistered_protocol.json"
DEFAULT_DATA_ROOT = Path("/Users/linmei/Documents/CY/data")
DEFAULT_V3_ROOT = DEFAULT_DATA_ROOT / "validation/v12_v3_500_temporal_20260828"
DEFAULT_LOCK = Path("/Users/linmei/Documents/cyq-v3-500-build/V12_V3_500_TEMPORAL_BUILD_LOCK.json")
DEFAULT_DAILY_INVENTORY = (
    DEFAULT_DATA_ROOT / "input_inventories/CY-006-pit-b-daily-v2-2018-2026-20260821.json"
)

EXPECTED_ROOT_SHA256 = "915686c6b9a069688e4790a1e6a8e699feafaf951ca7b720c11ca8b21b85c29a"
EXPECTED_LOCK_SHA256 = "95a7b33ec28fe3c188b309e962522cb1bea16a23b7647c68068864a1e17fd6d9"
EXPECTED_BASELINE = "845b90bb9d1691bb7f8914b0307aee9180a75a78"
EXPECTED_SYMBOLS = 500
EXPECTED_FEATURE_ROWS = 121_251
MODELS = (*SELLER_MODEL_ORDER, "ENSEMBLE")
SPLITS = ("discovery", "validation", "holdout")
HORIZONS = (1, 3, 5, 10, 20, 40)


@dataclass(frozen=True)
class Distribution:
    coordinates: np.ndarray
    shares: np.ndarray
    free_float: float
    known_fraction: float


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_id(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts).encode()
    return hashlib.sha256(payload).hexdigest()


def _wire_bits(value: str) -> int:
    if not isinstance(value, str) or not value.startswith("f64be:") or len(value) != 22:
        raise RuntimeError("compact checkpoint contains an invalid binary64 field")
    return int(value[6:], 16)


def _wire_timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise RuntimeError("compact checkpoint contains an invalid timestamp")
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _bit_array_to_float(values: np.ndarray) -> np.ndarray:
    contiguous = np.ascontiguousarray(values, dtype="<u8")
    return contiguous.view("<f8")


def validate_frozen_mass(
    shares: np.ndarray, free_float: float, conservation_error_bits: int
) -> None:
    if (
        not math.isfinite(free_float)
        or free_float <= 0.0
        or not np.isfinite(shares).all()
        or np.any(shares < 0.0)
    ):
        raise RuntimeError("compact checkpoint contains invalid distribution mass")
    computed_error = math.fsum(shares.tolist()) - free_float
    declared_error = bits_f64be(conservation_error_bits)
    if not (
        computed_error == 0.0 == declared_error
        or f64be_bits(computed_error) == conservation_error_bits
    ):
        raise RuntimeError(
            "compact checkpoint lot/free-float residual disagrees with its exact bits"
        )


def fast_decode_checkpoint(path: Path) -> Any:
    """Read manifest-hashed compact arrays without materializing cell objects.

    The final run verifies the physical SHA-256 of every file before this reader is
    called.  This reader retains the stored binary64 bits and validates the compact
    array relationships needed by the study.
    """

    with np.load(path, allow_pickle=False) as archive:
        required = {
            "format_version",
            "union_identity",
            "logical_digest",
            "metadata_json",
            "identity_economic_valid",
            "identity_economic_bits",
            "model_lot_offsets",
            "lot_identity_positions",
            "lot_share_bits",
        }
        if not required <= set(archive.files):
            raise RuntimeError("compact checkpoint arrays are incomplete")
        if int(archive["format_version"][0]) != 1 or int(archive["union_identity"][0]) != 1:
            raise RuntimeError("compact checkpoint format/version mismatch")
        if archive["logical_digest"].shape != (32,):
            raise RuntimeError("compact checkpoint logical digest is malformed")
        raw = json.loads(bytes(archive["metadata_json"]))
        if (
            raw.get("identities") != []
            or tuple(state.get("seller_model") for state in raw.get("model_states", []))
            != SELLER_MODEL_ORDER
        ):
            raise RuntimeError("compact checkpoint metadata skeleton mismatch")
        economic_valid = np.asarray(archive["identity_economic_valid"], dtype=np.uint8)
        economic_bits = np.asarray(archive["identity_economic_bits"], dtype="<u8")
        lot_offsets = np.asarray(archive["model_lot_offsets"], dtype="<u8")
        lot_positions = np.asarray(archive["lot_identity_positions"], dtype="<u8")
        lot_share_bits = np.asarray(archive["lot_share_bits"], dtype="<u8")
        if (
            len(economic_valid) != len(economic_bits)
            or len(lot_offsets) != len(SELLER_MODEL_ORDER) + 1
            or int(lot_offsets[0]) != 0
            or int(lot_offsets[-1]) != len(lot_positions)
            or len(lot_positions) != len(lot_share_bits)
            or np.any(economic_valid > 1)
            or np.any(lot_positions >= len(economic_bits))
        ):
            raise RuntimeError("compact checkpoint array relationship mismatch")
        coordinate_values = _bit_array_to_float(economic_bits)
        share_values = _bit_array_to_float(lot_share_bits)
        states = []
        for model_index, state in enumerate(raw["model_states"]):
            start = int(lot_offsets[model_index])
            stop = int(lot_offsets[model_index + 1])
            positions = lot_positions[start:stop].astype(np.int64, copy=False)
            valid = economic_valid[positions].astype(bool)
            coordinates = coordinate_values[positions[valid]].copy()
            model_shares = share_values[start:stop]
            free_float = bits_f64be(_wire_bits(state["free_float_shares_bits"]))
            validate_frozen_mass(
                model_shares,
                free_float,
                _wire_bits(state["conservation_error_bits"]),
            )
            shares = model_shares[valid].copy()
            if (
                not np.isfinite(coordinates).all()
                or np.any(coordinates <= 0.0)
                or np.any(shares <= 0.0)
            ):
                raise RuntimeError("compact checkpoint contains invalid known-cost mass")
            known_fraction = float(shares.sum() / free_float)
            distribution = Distribution(coordinates, shares, free_float, known_fraction)
            states.append(
                SimpleNamespace(
                    seller_model=state["seller_model"],
                    snapshot_id=state["snapshot_id"],
                    decision_at=_wire_timestamp(state["decision_at"]),
                    available_at=_wire_timestamp(state["available_at"]),
                    hard_valid=bool(state["hard_valid"]),
                    quality_reason_codes=tuple(state["quality_reason_codes"]),
                    _distribution=distribution,
                )
            )
        scopes = []
        for scope in raw["temporal_tracker"]["scopes"]:
            peaks = []
            for peak in scope["previous_peaks"]:
                peaks.append(
                    SimpleNamespace(
                        peak_track_id=peak["peak_track_id"],
                        age=int(peak["age"]),
                        band_lower_bits=_wire_bits(peak["band_lower_bits"]),
                        band_upper_bits=_wire_bits(peak["band_upper_bits"]),
                        center_price_bits=_wire_bits(peak["center_price_bits"]),
                        mass_bits=_wire_bits(peak["mass_bits"]),
                        prominence_bits=_wire_bits(peak["prominence_bits"]),
                        ambiguity=bool(peak["ambiguity"]),
                        split=bool(peak["split"]),
                        merge=bool(peak["merge"]),
                        lost=bool(peak["lost"]),
                        reappear=bool(peak["reappear"]),
                        definition_version=peak["definition_version"],
                        track_version=peak["track_version"],
                    )
                )
            scopes.append(
                SimpleNamespace(
                    scope=scope["scope"],
                    base_track_id=scope["base_track_id"],
                    previous_peaks=tuple(peaks),
                )
            )
    return SimpleNamespace(
        symbol=raw["symbol"],
        checkpoint_date=date.fromisoformat(raw["checkpoint_date"]),
        model_states=tuple(states),
        temporal_tracker=SimpleNamespace(scopes=tuple(scopes)),
    )


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def split_for(value: pd.Timestamp | date) -> str:
    stamp = pd.Timestamp(value)
    if stamp <= pd.Timestamp("2020-04-30"):
        return "discovery"
    if stamp <= pd.Timestamp("2020-08-31"):
        return "validation"
    return "holdout"


def json_value(value: Any) -> Any:
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, (pd.Timestamp, date)):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    if len(values) == 0 or float(weights.sum()) <= 0.0:
        return math.nan
    order = np.argsort(values, kind="stable")
    ordered_values = values[order]
    ordered_weights = weights[order]
    cumulative = np.cumsum(ordered_weights)
    target = q * float(cumulative[-1])
    index = min(int(np.searchsorted(cumulative, target, side="left")), len(values) - 1)
    return float(ordered_values[index])


def mass_in_band(distribution: Distribution, lower: float, upper: float) -> float:
    mask = (distribution.coordinates >= lower) & (distribution.coordinates <= upper)
    return float(distribution.shares[mask].sum() / distribution.free_float)


def distribution_descriptors(distribution: Distribution, close: float) -> dict[str, float]:
    coordinates = distribution.coordinates
    shares = distribution.shares
    known = float(shares.sum())
    if len(coordinates) == 0 or known <= 0.0:
        return {
            name: math.nan
            for name in (
                "weighted_mean",
                "weighted_median",
                "p10",
                "p90",
                "p90_p10_log_width",
                "mass_below_price",
                "mass_above_price",
                "mass_within_5pct_below",
                "mass_within_5pct_above",
                "bucket_hhi",
                "normalized_entropy",
            )
        } | {"known_cost_fraction": distribution.known_fraction}
    mean = float(np.dot(coordinates, shares) / known)
    p10 = weighted_quantile(coordinates, shares, 0.10)
    median = weighted_quantile(coordinates, shares, 0.50)
    p90 = weighted_quantile(coordinates, shares, 0.90)
    _, inverse = np.unique(coordinates, return_inverse=True)
    bucket_mass = np.bincount(inverse, weights=shares)
    probabilities = bucket_mass / bucket_mass.sum()
    hhi = float(np.dot(probabilities, probabilities))
    entropy = float(-(probabilities * np.log(probabilities)).sum())
    normalized_entropy = entropy / math.log(len(probabilities)) if len(probabilities) > 1 else 0.0
    return {
        "weighted_mean": mean,
        "weighted_median": median,
        "p10": p10,
        "p90": p90,
        "p90_p10_log_width": math.log(p90 / p10) if p90 > p10 > 0.0 else 0.0,
        "known_cost_fraction": distribution.known_fraction,
        "mass_below_price": float(shares[coordinates < close].sum() / distribution.free_float),
        "mass_above_price": float(shares[coordinates > close].sum() / distribution.free_float),
        "mass_within_5pct_below": float(
            shares[(coordinates >= close * 0.95) & (coordinates < close)].sum()
            / distribution.free_float
        ),
        "mass_within_5pct_above": float(
            shares[(coordinates > close) & (coordinates <= close * 1.05)].sum()
            / distribution.free_float
        ),
        "bucket_hhi": hhi,
        "normalized_entropy": normalized_entropy,
    }


def scope_model(scope: str) -> str:
    mapping = {
        "uniform": "UNIFORM",
        "disposition": "DISPOSITION",
        "active_sticky": "ACTIVE_STICKY",
        "ENSEMBLE": "ENSEMBLE",
    }
    if scope not in mapping:
        raise RuntimeError(f"unknown tracker scope: {scope}")
    return mapping[scope]


def active_peaks(scope: Any) -> list[Any]:
    return [peak for peak in scope.previous_peaks if not peak.lost]


def base_peak(scope: Any) -> Any | None:
    if scope.base_track_id is None:
        return None
    matches = [peak for peak in active_peaks(scope) if peak.peak_track_id == scope.base_track_id]
    if len(matches) != 1:
        raise RuntimeError("tracker base lacks one live peak")
    return matches[0]


def distribution_from_checkpoint(checkpoint: Any, state: Any) -> Distribution:
    if hasattr(state, "_distribution"):
        return state._distribution
    coordinates: list[float] = []
    shares: list[float] = []
    unknown = 0.0
    for lot in state.lots:
        identity = checkpoint.identities[lot.identity_position]
        quantity = bits_f64be(lot.shares_bits)
        if identity.economic_break_even_bits is None:
            unknown += quantity
            continue
        coordinate = bits_f64be(identity.economic_break_even_bits)
        if coordinate <= 0.0 or quantity <= 0.0:
            raise RuntimeError("invalid frozen distribution coordinate or mass")
        coordinates.append(coordinate)
        shares.append(quantity)
    free_float = bits_f64be(state.free_float_shares_bits)
    known = float(sum(shares))
    if free_float <= 0.0 or known + unknown > free_float * (1.0 + 1e-10):
        raise RuntimeError("frozen distribution violates its mass boundary")
    return Distribution(
        coordinates=np.asarray(coordinates, dtype=np.float64),
        shares=np.asarray(shares, dtype=np.float64),
        free_float=free_float,
        known_fraction=known / free_float,
    )


def transform_level_between(
    value: float,
    start: pd.Timestamp,
    end: pd.Timestamp,
    price_rows: pd.DataFrame,
) -> tuple[float, bool, int]:
    result = float(value)
    actions = price_rows[
        (price_rows["trade_date"] > start)
        & (price_rows["trade_date"] <= end)
        & (price_rows["corporate_action_count"].fillna(0).astype(int) > 0)
    ]
    for action in actions.itertuples(index=False):
        if not bool(action.corporate_action_valid) or bool(action.corporate_action_blocking):
            return math.nan, False, len(actions)
        result = rebase_economic_price(
            result,
            cash_per_share=float(action.cash_per_share or 0.0),
            share_multiplier=float(action.share_multiplier or 1.0),
        )
    return result, True, len(actions)


def verify_inputs(
    v3_root: Path,
    lock_path: Path,
    daily_inventory_path: Path,
    *,
    verify_all_parts: bool,
) -> dict[str, Any]:
    root_manifest_path = v3_root / "manifest.json"
    if sha256(root_manifest_path) != EXPECTED_ROOT_SHA256:
        raise RuntimeError("frozen V3 root manifest hash mismatch")
    if sha256(lock_path) != EXPECTED_LOCK_SHA256:
        raise RuntimeError("authoritative V3 freeze-lock hash mismatch")
    manifest = json.loads(root_manifest_path.read_text(encoding="utf-8"))
    if len(manifest.get("symbols", [])) != EXPECTED_SYMBOLS:
        raise RuntimeError("frozen V3 universe is not exactly 500 symbols")
    if tuple(manifest.get("seller_models", [])) != SELLER_MODEL_ORDER:
        raise RuntimeError("frozen seller-model identities mismatch")
    kinds = Counter(item["kind"] for item in manifest["parts"])
    if kinds["feature"] != EXPECTED_SYMBOLS or kinds["checkpoint"] < EXPECTED_SYMBOLS:
        raise RuntimeError("frozen V3 part coverage mismatch")
    verified_bytes = 0
    if verify_all_parts:
        for index, item in enumerate(manifest["parts"], start=1):
            path = v3_root / item["relative_path"]
            if not path.is_file() or path.stat().st_size != int(item["bytes"]):
                raise RuntimeError(f"frozen V3 part missing/truncated: {item['relative_path']}")
            if sha256(path) != item["sha256"]:
                raise RuntimeError(f"frozen V3 part hash mismatch: {item['relative_path']}")
            verified_bytes += path.stat().st_size
            if index % 1000 == 0:
                print(f"verified frozen parts: {index}/{len(manifest['parts'])}", flush=True)

    inventory = json.loads(daily_inventory_path.read_text(encoding="utf-8"))
    items = {item["path"]: item for item in inventory["files"]}
    daily_files: dict[int, Path] = {}
    daily_hashes: dict[str, str] = {}
    for year in (2019, 2020, 2021):
        relative = f"partition_year={year}/data_0.parquet"
        if relative not in items:
            raise RuntimeError(f"registered daily inventory lacks {year}")
        path = Path(inventory["root"]) / relative
        binding = items[relative]
        actual = sha256(path)
        if path.stat().st_size != int(binding["size"]) or actual != binding["sha256"]:
            raise RuntimeError(f"registered daily partition mismatch: {year}")
        daily_files[year] = path
        daily_hashes[str(year)] = actual

    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    if head != EXPECTED_BASELINE:
        raise RuntimeError("study must execute from the requested baseline commit")
    return {
        "manifest": manifest,
        "symbols": list(manifest["symbols"]),
        "root_manifest_sha256": EXPECTED_ROOT_SHA256,
        "freeze_lock_sha256": EXPECTED_LOCK_SHA256,
        "freeze_lock": json.loads(lock_path.read_text(encoding="utf-8")),
        "part_kind_counts": dict(sorted(kinds.items())),
        "verified_all_parts": verify_all_parts,
        "verified_part_count": len(manifest["parts"]) if verify_all_parts else 0,
        "verified_part_bytes": verified_bytes,
        "daily_inventory_sha256": sha256(daily_inventory_path),
        "daily_files": daily_files,
        "daily_partition_sha256": daily_hashes,
        "source_commit": head,
    }


def read_features(v3_root: Path) -> pd.DataFrame:
    scan = str(v3_root / "symbol=*" / "daily_feature_candidate.parquet")
    con = duckdb.connect()
    try:
        frame = con.execute(
            f"""
            SELECT symbol, trade_date, snapshot_id, available_at,
                   average_cost, p01, p10, p50, p90, p99,
                   tracked_base_peak, peak_track_id, peak_track_band_lower,
                   peak_track_band_upper, peak_track_age, peak_track_mass,
                   peak_track_prominence, peak_track_state,
                   peak_track_ambiguous, peak_track_split, peak_track_merge,
                   peak_track_lost, peak_definition_version,
                   peak_track_version, hard_valid, research_valid,
                   quality_reason_codes
            FROM read_parquet('{scan}', hive_partitioning=false, union_by_name=true)
            ORDER BY symbol, trade_date
            """
        ).fetchdf()
    finally:
        con.close()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    if len(frame) != EXPECTED_FEATURE_ROWS or frame["symbol"].nunique() != EXPECTED_SYMBOLS:
        raise RuntimeError("frozen daily-feature row/symbol count mismatch")
    if frame.duplicated(["symbol", "trade_date"]).any():
        raise RuntimeError("duplicate frozen daily-feature key")
    definitions = set(frame["peak_definition_version"].dropna().unique())
    trackers = set(frame["peak_track_version"].dropna().unique())
    if definitions != {"canonical-chip-peak-v2"} or trackers != {"temporal-chip-peak-v3"}:
        raise RuntimeError("frozen peak definition/tracker versions mismatch")
    return frame


def read_prices(files: dict[int, Path], symbols: Sequence[str]) -> pd.DataFrame:
    con = duckdb.connect()
    try:
        con.execute("CREATE TEMP TABLE selected_symbols(symbol VARCHAR PRIMARY KEY)")
        con.executemany(
            "INSERT INTO selected_symbols VALUES (?)", ((symbol,) for symbol in symbols)
        )
        paths = ",".join(f"'{files[year]}'" for year in sorted(files))
        frame = con.execute(
            f"""
            SELECT d.symbol, d.trade_date, d.decision_at, d.available_at,
                   d.open, d.high, d.low, d.close, d.preclose, d.volume,
                   d.amount, d.turnover_fraction, d.trade_status, d.industry,
                   d.bar_valid, d.current_day_data_tradable,
                   d.corporate_action_count, d.corporate_action_ids,
                   d.corporate_action_valid, d.corporate_action_blocking,
                   d.cash_per_share, d.share_multiplier,
                   d.snapshot_id, d.daily_snapshot_id,
                   d.corporate_action_snapshot_id
            FROM read_parquet([{paths}]) d
            JOIN selected_symbols s USING (symbol)
            WHERE d.trade_date >= DATE '2019-11-01'
              AND d.trade_date <= DATE '2021-04-30'
            ORDER BY d.symbol, d.trade_date
            """
        ).fetchdf()
    finally:
        con.close()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    if frame.duplicated(["symbol", "trade_date"]).any():
        raise RuntimeError("duplicate registered price key")
    pit_bad = (
        frame["available_at"].notna()
        & frame["decision_at"].notna()
        & (frame["available_at"] > frame["decision_at"])
    )
    if pit_bad.any():
        raise RuntimeError("registered daily row violates available_at <= decision_at")
    frame["tradable_observation"] = (
        frame["bar_valid"].fillna(False)
        & frame["trade_status"].eq(1)
        & frame["close"].gt(0)
        & frame["high"].gt(0)
        & frame["low"].gt(0)
    )
    return frame


def choose_placebo(
    *,
    side: str,
    close: float,
    lower: float,
    center: float,
    upper: float,
    real_mass: float,
    all_bands: Sequence[tuple[float, float]],
    distributions: Sequence[Distribution],
    protocol: dict[str, Any],
) -> dict[str, float] | None:
    distance = abs(math.log(center / close))
    lower_ratio = lower / center
    upper_ratio = upper / center
    minimum = float(protocol["eligibility"]["minimum_level_distance_fraction"])
    maximum = float(protocol["eligibility"]["maximum_level_distance_fraction"])
    candidates = []
    sign = -1.0 if side == "SUPPORT" else 1.0
    for order, factor in enumerate(protocol["placebo"]["distance_multipliers"]):
        candidate_center = close * math.exp(sign * distance * float(factor))
        candidate_lower = candidate_center * lower_ratio
        candidate_upper = candidate_center * upper_ratio
        candidate_distance = abs(candidate_center / close - 1.0)
        if not minimum <= candidate_distance <= maximum:
            continue
        if side == "SUPPORT" and candidate_upper >= close:
            continue
        if side == "RESISTANCE" and candidate_lower <= close:
            continue
        if any(
            not (candidate_upper < band_lower or candidate_lower > band_upper)
            for band_lower, band_upper in all_bands
        ):
            continue
        masses = [mass_in_band(dist, candidate_lower, candidate_upper) for dist in distributions]
        candidate_mass = float(np.mean(masses))
        candidates.append(
            (candidate_mass, order, candidate_lower, candidate_center, candidate_upper)
        )
    if not candidates:
        return None
    candidate_mass, _, candidate_lower, candidate_center, candidate_upper = min(candidates)
    ratio_limit = float(protocol["placebo"]["maximum_placebo_to_real_band_mass_ratio"])
    if real_mass <= 0.0 or candidate_mass > real_mass * ratio_limit:
        return None
    return {
        "placebo_lower": candidate_lower,
        "placebo_center": candidate_center,
        "placebo_upper": candidate_upper,
        "placebo_mass": candidate_mass,
    }


def _peak_values(peak: Any) -> dict[str, Any]:
    return {
        "peak_track_id": peak.peak_track_id,
        "peak_age": int(peak.age),
        "band_lower": bits_f64be(peak.band_lower_bits),
        "center": bits_f64be(peak.center_price_bits),
        "band_upper": bits_f64be(peak.band_upper_bits),
        "peak_mass": bits_f64be(peak.mass_bits),
        "peak_prominence": bits_f64be(peak.prominence_bits),
        "peak_ambiguous": bool(peak.ambiguity),
        "peak_split": bool(peak.split),
        "peak_merge": bool(peak.merge),
        "peak_reappear": bool(peak.reappear),
        "definition_version": peak.definition_version,
        "track_version": peak.track_version,
    }


def _ensemble_descriptor(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    numeric = (
        "weighted_mean",
        "weighted_median",
        "p10",
        "p90",
        "p90_p10_log_width",
        "known_cost_fraction",
        "mass_below_price",
        "mass_above_price",
        "mass_within_5pct_below",
        "mass_within_5pct_above",
        "bucket_hhi",
        "normalized_entropy",
    )
    return {name: float(np.median([float(row[name]) for row in rows])) for name in numeric}


def extract_checkpoint_panel(
    *,
    v3_root: Path,
    manifest: dict[str, Any],
    features: pd.DataFrame,
    prices: pd.DataFrame,
    protocol: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    feature_lookup = {
        (row.symbol, pd.Timestamp(row.trade_date)): row for row in features.itertuples(index=False)
    }
    price_by_symbol = {
        symbol: group.sort_values("trade_date").reset_index(drop=True)
        for symbol, group in prices.groupby("symbol", sort=True)
    }
    close_lookup = {
        (row.symbol, pd.Timestamp(row.trade_date)): float(row.close)
        for row in prices[prices["tradable_observation"]].itertuples(index=False)
    }
    parts_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for part in manifest["parts"]:
        if part["kind"] != "checkpoint":
            continue
        symbol = part["relative_path"].split("/", 1)[0].split("=", 1)[1]
        parts_by_symbol[symbol].append(part)

    descriptor_rows: list[dict[str, Any]] = []
    peak_rows: list[dict[str, Any]] = []
    migration_rows: list[dict[str, Any]] = []
    base_transition_rows: list[dict[str, Any]] = []
    allowed = set(protocol["eligibility"]["allowed_research_quality_reasons"])

    for symbol_number, symbol in enumerate(sorted(parts_by_symbol), start=1):

        def decode_part(part: dict[str, Any], expected_symbol: str = symbol) -> Any:
            checkpoint = fast_decode_checkpoint(v3_root / part["relative_path"])
            if checkpoint.symbol != expected_symbol:
                raise RuntimeError("checkpoint symbol/path mismatch")
            return checkpoint

        with ThreadPoolExecutor(max_workers=8) as executor:
            checkpoints = list(executor.map(decode_part, parts_by_symbol[symbol]))
        checkpoints.sort(key=lambda item: item.checkpoint_date)
        symbol_prices = price_by_symbol[symbol]
        previous_by_model: dict[str, dict[str, Any]] = {}

        for checkpoint in checkpoints:
            checkpoint_date = pd.Timestamp(checkpoint.checkpoint_date)
            feature = feature_lookup.get((symbol, checkpoint_date))
            close = close_lookup.get((symbol, checkpoint_date))
            if feature is None:
                raise RuntimeError(
                    f"checkpoint lacks exact frozen fact: {symbol} {checkpoint_date.date()}"
                )
            if close is None:
                continue
            raw_quality_reasons = feature.quality_reason_codes
            quality_reasons = (
                set(raw_quality_reasons)
                if isinstance(raw_quality_reasons, (list, tuple, np.ndarray))
                else set()
            )
            if not bool(feature.research_valid):
                continue
            if quality_reasons - allowed:
                raise RuntimeError("checkpoint feature has an unregistered research quality reason")
            if pd.Timestamp(feature.available_at).date() != checkpoint.checkpoint_date:
                raise RuntimeError("checkpoint feature availability date mismatch")

            scopes = {
                scope_model(scope.scope): scope for scope in checkpoint.temporal_tracker.scopes
            }
            if set(scopes) != set(MODELS):
                raise RuntimeError("checkpoint lacks exact seller/ensemble tracker scopes")
            distributions = {
                state.seller_model: distribution_from_checkpoint(checkpoint, state)
                for state in checkpoint.model_states
            }
            if set(distributions) != set(SELLER_MODEL_ORDER):
                raise RuntimeError("checkpoint lacks exact seller-model states")
            state_by_model = {state.seller_model: state for state in checkpoint.model_states}
            if any(
                set(state.quality_reason_codes) - set(RESEARCH_RECOVERABLE_REASON_CODES)
                for state in checkpoint.model_states
            ):
                raise RuntimeError("checkpoint model state has an unsupported quality reason")

            model_descriptor_rows: list[dict[str, Any]] = []
            for model in SELLER_MODEL_ORDER:
                distribution = distributions[model]
                if distribution.known_fraction < float(
                    protocol["eligibility"]["minimum_known_cost_fraction"]
                ):
                    continue
                scope = scopes[model]
                peaks = active_peaks(scope)
                base = base_peak(scope)
                descriptor = distribution_descriptors(distribution, close)
                peak_masses = sorted((bits_f64be(peak.mass_bits) for peak in peaks), reverse=True)
                row = {
                    "snapshot_key": stable_id(symbol, checkpoint_date.date(), model),
                    "symbol": symbol,
                    "checkpoint_date": checkpoint_date,
                    "split": split_for(checkpoint_date),
                    "model": model,
                    "snapshot_id": state_by_model[model].snapshot_id,
                    "feature_snapshot_id": feature.snapshot_id,
                    "decision_at": state_by_model[model].decision_at,
                    "available_at": state_by_model[model].available_at,
                    "hard_valid": bool(state_by_model[model].hard_valid),
                    "research_valid": bool(feature.research_valid),
                    "quality_reason_codes": "|".join(sorted(quality_reasons)),
                    "close": close,
                    "tracked_mode_count": len(peaks),
                    "largest_mode_mass": peak_masses[0] if peak_masses else math.nan,
                    "second_mode_mass": peak_masses[1] if len(peak_masses) > 1 else math.nan,
                    "top_two_mode_gap": (
                        abs(
                            math.log(
                                bits_f64be(peaks[0].center_price_bits)
                                / bits_f64be(peaks[1].center_price_bits)
                            )
                        )
                        if len(peaks) >= 2
                        else math.nan
                    ),
                    "base_track_id": scope.base_track_id,
                    "base_center": bits_f64be(base.center_price_bits) if base else math.nan,
                    "base_lower": bits_f64be(base.band_lower_bits) if base else math.nan,
                    "base_upper": bits_f64be(base.band_upper_bits) if base else math.nan,
                    "base_mass": bits_f64be(base.mass_bits) if base else math.nan,
                    "base_prominence": bits_f64be(base.prominence_bits) if base else math.nan,
                    "base_age": int(base.age) if base else math.nan,
                    **descriptor,
                }
                descriptor_rows.append(row)
                model_descriptor_rows.append(row)

            if len(model_descriptor_rows) != len(SELLER_MODEL_ORDER):
                continue

            ensemble_scope = scopes["ENSEMBLE"]
            ensemble_peaks = active_peaks(ensemble_scope)
            ensemble_base = base_peak(ensemble_scope)
            ensemble_masses = sorted(
                (bits_f64be(peak.mass_bits) for peak in ensemble_peaks), reverse=True
            )
            ensemble_row = {
                "snapshot_key": stable_id(symbol, checkpoint_date.date(), "ENSEMBLE"),
                "symbol": symbol,
                "checkpoint_date": checkpoint_date,
                "split": split_for(checkpoint_date),
                "model": "ENSEMBLE",
                "snapshot_id": feature.snapshot_id,
                "feature_snapshot_id": feature.snapshot_id,
                "decision_at": max(state.decision_at for state in checkpoint.model_states),
                "available_at": max(state.available_at for state in checkpoint.model_states),
                "hard_valid": all(state.hard_valid for state in checkpoint.model_states),
                "research_valid": bool(feature.research_valid),
                "quality_reason_codes": "|".join(sorted(quality_reasons)),
                "close": close,
                "tracked_mode_count": len(ensemble_peaks),
                "largest_mode_mass": ensemble_masses[0] if ensemble_masses else math.nan,
                "second_mode_mass": ensemble_masses[1] if len(ensemble_masses) > 1 else math.nan,
                "top_two_mode_gap": (
                    abs(
                        math.log(
                            bits_f64be(ensemble_peaks[0].center_price_bits)
                            / bits_f64be(ensemble_peaks[1].center_price_bits)
                        )
                    )
                    if len(ensemble_peaks) >= 2
                    else math.nan
                ),
                "base_track_id": ensemble_scope.base_track_id,
                "base_center": bits_f64be(ensemble_base.center_price_bits)
                if ensemble_base
                else math.nan,
                "base_lower": bits_f64be(ensemble_base.band_lower_bits)
                if ensemble_base
                else math.nan,
                "base_upper": bits_f64be(ensemble_base.band_upper_bits)
                if ensemble_base
                else math.nan,
                "base_mass": bits_f64be(ensemble_base.mass_bits) if ensemble_base else math.nan,
                "base_prominence": bits_f64be(ensemble_base.prominence_bits)
                if ensemble_base
                else math.nan,
                "base_age": int(ensemble_base.age) if ensemble_base else math.nan,
                **_ensemble_descriptor(model_descriptor_rows),
            }
            descriptor_rows.append(ensemble_row)

            for model in MODELS:
                scope = scopes[model]
                peaks = active_peaks(scope)
                all_bands = [
                    (bits_f64be(peak.band_lower_bits), bits_f64be(peak.band_upper_bits))
                    for peak in peaks
                ]
                model_distributions = (
                    [distributions[model]]
                    if model != "ENSEMBLE"
                    else [distributions[name] for name in SELLER_MODEL_ORDER]
                )
                for peak in peaks:
                    values = _peak_values(peak)
                    lower = float(values["band_lower"])
                    center = float(values["center"])
                    upper = float(values["band_upper"])
                    if not 0.0 < lower <= center <= upper:
                        raise RuntimeError("tracked peak band ordering is invalid")
                    if upper < close * (
                        1.0 - float(protocol["eligibility"]["minimum_level_distance_fraction"])
                    ):
                        side = "SUPPORT"
                    elif lower > close * (
                        1.0 + float(protocol["eligibility"]["minimum_level_distance_fraction"])
                    ):
                        side = "RESISTANCE"
                    else:
                        continue
                    distance = abs(center / close - 1.0)
                    if distance > float(protocol["eligibility"]["maximum_level_distance_fraction"]):
                        continue
                    band_masses = [mass_in_band(item, lower, upper) for item in model_distributions]
                    real_mass = float(np.mean(band_masses))
                    placebo = choose_placebo(
                        side=side,
                        close=close,
                        lower=lower,
                        center=center,
                        upper=upper,
                        real_mass=real_mass,
                        all_bands=all_bands,
                        distributions=model_distributions,
                        protocol=protocol,
                    )
                    level_id = stable_id(
                        "chip-level-v1",
                        symbol,
                        checkpoint_date.date(),
                        model,
                        values["peak_track_id"],
                        side,
                    )
                    peak_rows.append(
                        {
                            "level_id": level_id,
                            "snapshot_key": stable_id(symbol, checkpoint_date.date(), model),
                            "symbol": symbol,
                            "checkpoint_date": checkpoint_date,
                            "split": split_for(checkpoint_date),
                            "model": model,
                            "side": side,
                            "close_at_definition": close,
                            "distance_fraction": distance,
                            "band_width_fraction": (upper - lower) / center,
                            "distribution_band_mass": real_mass,
                            "is_base_peak": values["peak_track_id"] == scope.base_track_id,
                            "ensemble_ambiguous": feature.peak_track_state
                            == "ENSEMBLE_PEAK_AMBIGUOUS",
                            **values,
                            **(
                                placebo
                                or {
                                    "placebo_lower": math.nan,
                                    "placebo_center": math.nan,
                                    "placebo_upper": math.nan,
                                    "placebo_mass": math.nan,
                                }
                            ),
                        }
                    )

            current_rows = {row["model"]: row for row in (*model_descriptor_rows, ensemble_row)}
            current_scopes = scopes
            current_distributions = {
                **distributions,
                "ENSEMBLE": tuple(distributions[name] for name in SELLER_MODEL_ORDER),
            }
            for model in MODELS:
                current = current_rows[model]
                previous = previous_by_model.get(model)
                current_base = base_peak(current_scopes[model])
                if previous is not None:
                    adjusted_p50, action_valid, action_count = transform_level_between(
                        previous["descriptor"]["weighted_median"],
                        previous["date"],
                        checkpoint_date,
                        symbol_prices,
                    )
                    adjusted_p10, action_valid_10, _ = transform_level_between(
                        previous["descriptor"]["p10"],
                        previous["date"],
                        checkpoint_date,
                        symbol_prices,
                    )
                    adjusted_p90, action_valid_90, _ = transform_level_between(
                        previous["descriptor"]["p90"],
                        previous["date"],
                        checkpoint_date,
                        symbol_prices,
                    )
                    action_valid = action_valid and action_valid_10 and action_valid_90
                    if action_valid:
                        shift = current["weighted_median"] / adjusted_p50 - 1.0
                        old_width = (
                            math.log(adjusted_p90 / adjusted_p10)
                            if adjusted_p90 > adjusted_p10 > 0
                            else math.nan
                        )
                        width_change = (
                            current["p90_p10_log_width"] / old_width - 1.0
                            if old_width > 0.0
                            else math.nan
                        )
                        threshold = float(protocol["migration"]["median_shift_fraction"])
                        if shift >= threshold:
                            migration_state = "UPWARD_MIGRATION"
                        elif shift <= -threshold:
                            migration_state = "DOWNWARD_MIGRATION"
                        elif finite(width_change) and width_change >= float(
                            protocol["migration"]["dispersion_width_increase_fraction"]
                        ):
                            migration_state = "DISPERSION"
                        else:
                            migration_state = "STABLE_BASE"
                        migration_rows.append(
                            {
                                "migration_id": stable_id(
                                    symbol, checkpoint_date.date(), model, "migration"
                                ),
                                "snapshot_key": current["snapshot_key"],
                                "symbol": symbol,
                                "checkpoint_date": checkpoint_date,
                                "split": current["split"],
                                "model": model,
                                "previous_checkpoint_date": previous["date"],
                                "migration_state": migration_state,
                                "median_shift_fraction": shift,
                                "width_change_fraction": width_change,
                                "corporate_action_count": action_count,
                                "corporate_action_path_valid": action_valid,
                            }
                        )

                    old_base = previous["base"]
                    if old_base is not None:
                        old_values = _peak_values(old_base)
                        adjusted_lower, valid_lower, _ = transform_level_between(
                            old_values["band_lower"],
                            previous["date"],
                            checkpoint_date,
                            symbol_prices,
                        )
                        adjusted_center, valid_center, _ = transform_level_between(
                            old_values["center"],
                            previous["date"],
                            checkpoint_date,
                            symbol_prices,
                        )
                        adjusted_upper, valid_upper, _ = transform_level_between(
                            old_values["band_upper"],
                            previous["date"],
                            checkpoint_date,
                            symbol_prices,
                        )
                        if valid_lower and valid_center and valid_upper:
                            distributions_now = (
                                [current_distributions[model]]
                                if model != "ENSEMBLE"
                                else list(current_distributions["ENSEMBLE"])
                            )
                            current_mass = float(
                                np.mean(
                                    [
                                        mass_in_band(item, adjusted_lower, adjusted_upper)
                                        for item in distributions_now
                                    ]
                                )
                            )
                            retention = (
                                current_mass / old_values["peak_mass"]
                                if old_values["peak_mass"] > 0
                                else math.nan
                            )
                            if retention >= float(
                                protocol["migration"]["base_intact_mass_retention"]
                            ):
                                integrity = "BASE_INTACT"
                            elif retention < float(
                                protocol["migration"]["base_damaged_mass_retention"]
                            ):
                                integrity = "BASE_DAMAGED_OR_LOST"
                            else:
                                integrity = "BASE_INTERMEDIATE"
                            base_transition_rows.append(
                                {
                                    "base_transition_id": stable_id(
                                        symbol,
                                        checkpoint_date.date(),
                                        model,
                                        old_values["peak_track_id"],
                                    ),
                                    "symbol": symbol,
                                    "checkpoint_date": checkpoint_date,
                                    "split": current["split"],
                                    "model": model,
                                    "old_track_id": old_values["peak_track_id"],
                                    "old_base_lower": adjusted_lower,
                                    "old_base_center": adjusted_center,
                                    "old_base_upper": adjusted_upper,
                                    "old_base_mass": old_values["peak_mass"],
                                    "current_mass_at_old_base": current_mass,
                                    "mass_retention": retention,
                                    "base_integrity": integrity,
                                    "current_close": close,
                                    "current_base_track_id": current_base.peak_track_id
                                    if current_base
                                    else None,
                                }
                            )

                previous_by_model[model] = {
                    "date": checkpoint_date,
                    "descriptor": current,
                    "base": current_base,
                }
        if symbol_number % 25 == 0:
            print(
                f"decoded checkpoint distributions: {symbol_number}/{len(parts_by_symbol)} symbols",
                flush=True,
            )

    descriptors = (
        pd.DataFrame(descriptor_rows)
        .sort_values(["symbol", "checkpoint_date", "model"])
        .reset_index(drop=True)
    )
    peaks = (
        pd.DataFrame(peak_rows)
        .sort_values(["symbol", "checkpoint_date", "model", "side", "center"])
        .reset_index(drop=True)
    )
    migrations = (
        pd.DataFrame(migration_rows)
        .sort_values(["symbol", "checkpoint_date", "model"])
        .reset_index(drop=True)
    )
    base_transitions = (
        pd.DataFrame(base_transition_rows)
        .sort_values(["symbol", "checkpoint_date", "model"])
        .reset_index(drop=True)
    )
    return descriptors, peaks, migrations, base_transitions


def price_context(prices: pd.DataFrame) -> dict[tuple[str, pd.Timestamp], dict[str, float]]:
    result: dict[tuple[str, pd.Timestamp], dict[str, float]] = {}
    for symbol, group in prices.groupby("symbol", sort=True):
        valid = group[group["tradable_observation"]].sort_values("trade_date").copy()
        valid["daily_return"] = valid["close"].pct_change()
        valid["recent_volatility"] = valid["daily_return"].rolling(20, min_periods=10).std()
        valid["recent_trend"] = valid["close"] / valid["close"].shift(20) - 1.0
        valid["swing_low_20"] = valid["low"].shift(1).rolling(20, min_periods=10).min()
        valid["swing_high_20"] = valid["high"].shift(1).rolling(20, min_periods=10).max()
        valid["pre_volume_20"] = valid["volume"].shift(1).rolling(20, min_periods=10).mean()
        valid["pre_turnover_20"] = (
            valid["turnover_fraction"].shift(1).rolling(20, min_periods=10).mean()
        )
        for row in valid.itertuples(index=False):
            result[(symbol, pd.Timestamp(row.trade_date))] = {
                "recent_volatility": float(row.recent_volatility)
                if finite(row.recent_volatility)
                else math.nan,
                "recent_trend": float(row.recent_trend) if finite(row.recent_trend) else math.nan,
                "swing_low_20": float(row.swing_low_20) if finite(row.swing_low_20) else math.nan,
                "swing_high_20": float(row.swing_high_20)
                if finite(row.swing_high_20)
                else math.nan,
                "pre_volume_20": float(row.pre_volume_20)
                if finite(row.pre_volume_20)
                else math.nan,
                "pre_turnover_20": float(row.pre_turnover_20)
                if finite(row.pre_turnover_20)
                else math.nan,
            }
    return result


def add_price_context(
    descriptors: pd.DataFrame,
    peaks: pd.DataFrame,
    context: dict[tuple[str, pd.Timestamp], dict[str, float]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    context_rows = [
        {"symbol": key[0], "checkpoint_date": key[1], **values} for key, values in context.items()
    ]
    context_frame = pd.DataFrame(context_rows)
    descriptors = descriptors.merge(
        context_frame, on=["symbol", "checkpoint_date"], how="left", validate="many_to_one"
    )
    peaks = peaks.merge(
        context_frame, on=["symbol", "checkpoint_date"], how="left", validate="many_to_one"
    )
    return descriptors, peaks


def valid_price_records(
    prices: pd.DataFrame,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[pd.Timestamp, int]]]:
    records_by_symbol: dict[str, list[dict[str, Any]]] = {}
    index_by_symbol: dict[str, dict[pd.Timestamp, int]] = {}
    for symbol, group in prices.groupby("symbol", sort=True):
        records: list[dict[str, Any]] = []
        date_index: dict[pd.Timestamp, int] = {}
        valid_index = -1
        for row in group.sort_values("trade_date").itertuples(index=False):
            if bool(row.tradable_observation):
                valid_index += 1
            item = {
                "trade_date": pd.Timestamp(row.trade_date),
                "open": float(row.open) if finite(row.open) else math.nan,
                "high": float(row.high) if finite(row.high) else math.nan,
                "low": float(row.low) if finite(row.low) else math.nan,
                "close": float(row.close) if finite(row.close) else math.nan,
                "volume": float(row.volume) if finite(row.volume) else math.nan,
                "turnover_fraction": float(row.turnover_fraction)
                if finite(row.turnover_fraction)
                else math.nan,
                "tradable": bool(row.tradable_observation),
                "valid_index": valid_index if bool(row.tradable_observation) else None,
                "corporate_action_count": int(row.corporate_action_count or 0),
                "corporate_action_valid": bool(row.corporate_action_valid),
                "corporate_action_blocking": bool(row.corporate_action_blocking),
                "cash_per_share": float(row.cash_per_share or 0.0),
                "share_multiplier": float(row.share_multiplier or 1.0),
            }
            date_index[item["trade_date"]] = len(records)
            records.append(item)
        records_by_symbol[symbol] = records
        index_by_symbol[symbol] = date_index
    return records_by_symbol, index_by_symbol


def _mean_ratio(values: Sequence[float], baseline: Sequence[float]) -> float:
    numerator = np.asarray([value for value in values if finite(value)], dtype=float)
    denominator = np.asarray([value for value in baseline if finite(value)], dtype=float)
    if len(numerator) == 0 or len(denominator) < 5 or float(denominator.mean()) <= 0.0:
        return math.nan
    return float(numerator.mean() / denominator.mean())


def simulate_level(
    *,
    symbol: str,
    checkpoint_date: pd.Timestamp,
    side: str,
    lower: float,
    center: float,
    upper: float,
    records: list[dict[str, Any]],
    date_index: dict[pd.Timestamp, int],
    protocol: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not (finite(lower) and finite(center) and finite(upper) and 0.0 < lower <= center <= upper):
        return {"touched": False, "path_valid": False, "invalid_reason": "INVALID_LEVEL"}, []
    start = date_index.get(checkpoint_date)
    if start is None or not records[start]["tradable"]:
        return {
            "touched": False,
            "path_valid": False,
            "invalid_reason": "MISSING_DEFINITION_PRICE",
        }, []
    current_lower = float(lower)
    current_center = float(center)
    current_upper = float(upper)
    last_close = float(records[start]["close"])
    future: list[dict[str, Any]] = []
    search_sessions = int(protocol["chronology"]["level_search_sessions"])
    for item in records[start + 1 :]:
        if item["corporate_action_count"] > 0:
            if not item["corporate_action_valid"] or item["corporate_action_blocking"]:
                return {
                    "touched": False,
                    "path_valid": False,
                    "invalid_reason": "INVALID_CORPORATE_ACTION_PATH",
                }, []
            kwargs = {
                "cash_per_share": item["cash_per_share"],
                "share_multiplier": item["share_multiplier"],
            }
            current_lower = rebase_economic_price(current_lower, **kwargs)
            current_center = rebase_economic_price(current_center, **kwargs)
            current_upper = rebase_economic_price(current_upper, **kwargs)
            last_close = rebase_economic_price(last_close, **kwargs)
        if not item["tradable"]:
            continue
        enriched = {
            **item,
            "band_lower": current_lower,
            "band_center": current_center,
            "band_upper": current_upper,
            "prior_close": last_close,
        }
        future.append(enriched)
        last_close = item["close"]
        if len(future) >= search_sessions:
            break
    if not future:
        return {"touched": False, "path_valid": True, "invalid_reason": None}, []

    cooldown = int(protocol["level_events"]["touch_cooldown_sessions"])
    material = float(protocol["level_events"]["material_break_fraction"])
    reaction = float(protocol["level_events"]["bounce_or_rejection_fraction"])
    reaction_sessions = int(protocol["level_events"]["reaction_sessions"])
    touch_indexes: list[int] = []
    last_touch = -10_000
    for index, item in enumerate(future):
        approached = (
            item["prior_close"] > item["band_upper"] and item["low"] <= item["band_upper"]
            if side == "SUPPORT"
            else item["prior_close"] < item["band_lower"] and item["high"] >= item["band_lower"]
        )
        if approached and index - last_touch >= cooldown:
            touch_indexes.append(index)
            last_touch = index

    touch_rows: list[dict[str, Any]] = []
    for touch_number, touch_index in enumerate(touch_indexes, start=1):
        touch = future[touch_index]
        global_index = int(touch["valid_index"])
        prior_valid = [
            item
            for item in records
            if item["tradable"]
            and item["valid_index"] is not None
            and global_index - 20 <= int(item["valid_index"]) < global_index
        ]
        next_reaction = future[touch_index + 1 : touch_index + 1 + reaction_sessions]
        if side == "SUPPORT":
            reaction_probability = (
                any(
                    item["close"] >= item["band_upper"] * (1.0 + reaction) for item in next_reaction
                )
                if len(next_reaction) == reaction_sessions
                else None
            )
            close_favorable = touch["close"] >= touch["band_upper"]
        else:
            reaction_probability = (
                any(
                    item["close"] <= item["band_lower"] * (1.0 - reaction) for item in next_reaction
                )
                if len(next_reaction) == reaction_sessions
                else None
            )
            close_favorable = touch["close"] <= touch["band_lower"]
        row: dict[str, Any] = {
            "touch_number": touch_number,
            "touch_bucket": "FIRST"
            if touch_number == 1
            else ("SECOND" if touch_number == 2 else "THIRD_PLUS"),
            "touch_date": touch["trade_date"],
            "touch_close": touch["close"],
            "touch_band_lower": touch["band_lower"],
            "touch_band_center": touch["band_center"],
            "touch_band_upper": touch["band_upper"],
            "reaction_probability": reaction_probability,
            "close_favorable_probability": close_favorable,
            "volume_response_ratio": _mean_ratio(
                [item["volume"] for item in future[touch_index : touch_index + 3]],
                [item["volume"] for item in prior_valid],
            ),
            "turnover_response_ratio": _mean_ratio(
                [item["turnover_fraction"] for item in future[touch_index : touch_index + 3]],
                [item["turnover_fraction"] for item in prior_valid],
            ),
            "range_response_ratio": _mean_ratio(
                [
                    item["high"] / item["low"] - 1.0
                    for item in future[touch_index : touch_index + 3]
                    if item["low"] > 0
                ],
                [item["high"] / item["low"] - 1.0 for item in prior_valid if item["low"] > 0],
            ),
        }
        for horizon in HORIZONS:
            window = future[touch_index + 1 : touch_index + 1 + horizon]
            complete = len(window) == horizon
            row[f"future_return_{horizon}"] = (
                window[-1]["close"] / touch["close"] - 1.0 if complete else math.nan
            )
            row[f"mfe_{horizon}"] = (
                max(item["high"] for item in window) / touch["close"] - 1.0
                if complete
                else math.nan
            )
            row[f"mae_{horizon}"] = (
                min(item["low"] for item in window) / touch["close"] - 1.0 if complete else math.nan
            )
            if side == "SUPPORT":
                crossed = [
                    offset + 1
                    for offset, item in enumerate(window)
                    if item["close"] < item["band_lower"] * (1.0 - material)
                ]
                below = [item["close"] < item["band_lower"] for item in window]
            else:
                crossed = [
                    offset + 1
                    for offset, item in enumerate(window)
                    if item["close"] > item["band_upper"] * (1.0 + material)
                ]
                below = [item["close"] > item["band_upper"] for item in window]
            row[f"cross_probability_{horizon}"] = bool(crossed) if complete else None
            row[f"time_to_cross_{horizon}"] = (
                min(crossed) if crossed else (horizon + 1 if complete else math.nan)
            )
            row[f"sessions_beyond_{horizon}"] = sum(below) if complete else math.nan
        touch_rows.append(row)
    return {
        "touched": bool(touch_rows),
        "path_valid": True,
        "invalid_reason": None,
        "touch_count": len(touch_rows),
        "first_touch_session": touch_indexes[0] + 1 if touch_indexes else math.nan,
    }, touch_rows


def construct_level_events(
    peaks: pd.DataFrame,
    prices: pd.DataFrame,
    protocol: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    records_by_symbol, index_by_symbol = valid_price_records(prices)
    event_rows: list[dict[str, Any]] = []
    status_rows: list[dict[str, Any]] = []
    minimum = float(protocol["eligibility"]["minimum_level_distance_fraction"])
    for number, peak in enumerate(peaks.itertuples(index=False), start=1):
        sources = [
            ("REAL_CHIP", peak.band_lower, peak.center, peak.band_upper),
            ("MATCHED_PLACEBO", peak.placebo_lower, peak.placebo_center, peak.placebo_upper),
        ]
        benchmark_center = peak.swing_low_20 if peak.side == "SUPPORT" else peak.swing_high_20
        if finite(benchmark_center):
            benchmark_lower = float(benchmark_center) * peak.band_lower / peak.center
            benchmark_upper = float(benchmark_center) * peak.band_upper / peak.center
            benchmark_ok = (
                benchmark_upper < peak.close_at_definition * (1.0 - minimum)
                if peak.side == "SUPPORT"
                else benchmark_lower > peak.close_at_definition * (1.0 + minimum)
            )
            if benchmark_ok:
                sources.append(
                    (
                        "PRICE_ONLY_20_SWING",
                        benchmark_lower,
                        float(benchmark_center),
                        benchmark_upper,
                    )
                )
        for source, lower, center, upper in sources:
            if not (finite(lower) and finite(center) and finite(upper)):
                continue
            status, touches = simulate_level(
                symbol=peak.symbol,
                checkpoint_date=pd.Timestamp(peak.checkpoint_date),
                side=peak.side,
                lower=float(lower),
                center=float(center),
                upper=float(upper),
                records=records_by_symbol[peak.symbol],
                date_index=index_by_symbol[peak.symbol],
                protocol=protocol,
            )
            common = {
                "level_id": peak.level_id,
                "snapshot_key": peak.snapshot_key,
                "level_cluster_id": stable_id(peak.symbol, peak.checkpoint_date, peak.model),
                "source_level_id": stable_id(peak.level_id, source),
                "source": source,
                "symbol": peak.symbol,
                "checkpoint_date": pd.Timestamp(peak.checkpoint_date),
                "split": peak.split,
                "model": peak.model,
                "side": peak.side,
                "peak_track_id": peak.peak_track_id,
                "is_base_peak": bool(peak.is_base_peak),
                "peak_age": peak.peak_age,
                "peak_mass": peak.peak_mass,
                "peak_prominence": peak.peak_prominence,
                "distribution_band_mass": peak.distribution_band_mass,
                "distance_fraction": peak.distance_fraction,
                "band_width_fraction": peak.band_width_fraction,
                "recent_volatility": peak.recent_volatility,
                "recent_trend": peak.recent_trend,
                "ensemble_ambiguous": bool(peak.ensemble_ambiguous),
                "defined_lower": float(lower),
                "defined_center": float(center),
                "defined_upper": float(upper),
            }
            status_rows.append({**common, **status})
            event_rows.extend({**common, **touch} for touch in touches)
        if number % 10_000 == 0:
            print(f"constructed future level paths: {number}/{len(peaks)}", flush=True)
    events = pd.DataFrame(event_rows)
    statuses = pd.DataFrame(status_rows)
    if not events.empty:
        events = events.sort_values(
            ["symbol", "checkpoint_date", "model", "side", "source", "touch_number"]
        ).reset_index(drop=True)
    statuses = statuses.sort_values(
        ["symbol", "checkpoint_date", "model", "side", "source"]
    ).reset_index(drop=True)
    return events, statuses


def add_checkpoint_outcomes(descriptors: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    valid_by_symbol = {
        symbol: group[group["tradable_observation"]]
        .sort_values("trade_date")
        .reset_index(drop=True)
        for symbol, group in prices.groupby("symbol", sort=True)
    }
    index_by_symbol = {
        symbol: {pd.Timestamp(value): index for index, value in enumerate(group["trade_date"])}
        for symbol, group in valid_by_symbol.items()
    }
    rows = []
    for descriptor in descriptors.itertuples(index=False):
        group = valid_by_symbol[descriptor.symbol]
        start = index_by_symbol[descriptor.symbol].get(pd.Timestamp(descriptor.checkpoint_date))
        row = (
            asdict(descriptor)
            if hasattr(descriptor, "__dataclass_fields__")
            else descriptor._asdict()
        )
        if start is None:
            rows.append(row)
            continue
        start_close = float(group.iloc[start]["close"])
        prior = group.iloc[max(0, start - 20) : start]
        for horizon in HORIZONS:
            future = group.iloc[start + 1 : start + 1 + horizon]
            if len(future) != horizon:
                row[f"future_return_{horizon}"] = math.nan
                row[f"mfe_{horizon}"] = math.nan
                row[f"mae_{horizon}"] = math.nan
                row[f"future_volatility_{horizon}"] = math.nan
                row[f"future_volume_ratio_{horizon}"] = math.nan
                continue
            returns = future["close"].pct_change().dropna()
            row[f"future_return_{horizon}"] = float(future.iloc[-1]["close"] / start_close - 1.0)
            row[f"mfe_{horizon}"] = float(future["high"].max() / start_close - 1.0)
            row[f"mae_{horizon}"] = float(future["low"].min() / start_close - 1.0)
            row[f"future_volatility_{horizon}"] = (
                float(returns.std()) if len(returns) >= 2 else math.nan
            )
            row[f"future_volume_ratio_{horizon}"] = _mean_ratio(
                future["volume"].tolist(), prior["volume"].tolist()
            )
        future10 = group.iloc[start + 1 : start + 11]
        if len(future10) == 10:
            signs = np.sign(future10["close"].pct_change().dropna().to_numpy())
            row["future_chop_10"] = (
                float(np.mean(signs[1:] != signs[:-1])) if len(signs) >= 2 else math.nan
            )
        else:
            row["future_chop_10"] = math.nan
        rows.append(row)
    return pd.DataFrame(rows)


def cluster_ci(
    frame: pd.DataFrame,
    metric: str,
    cluster: str,
    *,
    seed: int,
    replicates: int,
) -> dict[str, Any]:
    sample = frame[[metric, cluster]].dropna()
    if sample.empty:
        return {
            "N": 0,
            "independent_event_count": 0,
            "effect": math.nan,
            "ci_low": math.nan,
            "ci_high": math.nan,
        }
    values = sample.groupby(cluster, sort=True)[metric].mean().to_numpy(dtype=float)
    effect = float(values.mean())
    if len(values) < 2:
        return {
            "N": len(sample),
            "independent_event_count": len(values),
            "effect": effect,
            "ci_low": math.nan,
            "ci_high": math.nan,
        }
    rng = np.random.default_rng(seed)
    draws = values[rng.integers(0, len(values), size=(replicates, len(values)))].mean(axis=1)
    low, high = np.quantile(draws, [0.025, 0.975])
    return {
        "N": len(sample),
        "independent_event_count": len(values),
        "effect": effect,
        "ci_low": float(low),
        "ci_high": float(high),
    }


def summarize_metrics(
    frame: pd.DataFrame,
    *,
    group_columns: Sequence[str],
    metric_horizons: Sequence[tuple[str, int]],
    cluster: str,
    protocol: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    seed_base = int(protocol["statistics"]["bootstrap_seed"])
    replicates = int(protocol["statistics"]["cluster_bootstrap_replicates"])
    grouped: Iterable[tuple[Any, pd.DataFrame]]
    if group_columns:
        grouped = frame.groupby(list(group_columns), sort=True, dropna=False)
    else:
        grouped = [((), frame)]
    for key, group in grouped:
        keys = key if isinstance(key, tuple) else (key,)
        identity = dict(zip(group_columns, keys, strict=True))
        for metric, horizon in metric_horizons:
            if metric not in group:
                continue
            seed = int(stable_id(seed_base, *keys, metric, horizon)[:16], 16) % (2**32)
            result = cluster_ci(group, metric, cluster, seed=seed, replicates=replicates)
            rows.append(
                {**(extra or {}), **identity, "metric": metric, "horizon": horizon, **result}
            )
    return pd.DataFrame(rows)


def side_metric_horizons(side: str) -> list[tuple[str, int]]:
    metrics = [
        ("reaction_probability", 3),
        ("close_favorable_probability", 0),
        ("volume_response_ratio", 3),
        ("turnover_response_ratio", 3),
        ("range_response_ratio", 3),
    ]
    for horizon in HORIZONS:
        metrics.extend(
            [
                (f"future_return_{horizon}", horizon),
                (f"mfe_{horizon}", horizon),
                (f"mae_{horizon}", horizon),
                (f"cross_probability_{horizon}", horizon),
                (f"time_to_cross_{horizon}", horizon),
                (f"sessions_beyond_{horizon}", horizon),
            ]
        )
    return metrics


def primary_event_results(
    events: pd.DataFrame, side: str, protocol: dict[str, Any]
) -> pd.DataFrame:
    sample = events[
        events["side"].eq(side) & events["source"].eq("REAL_CHIP") & events["touch_number"].eq(1)
    ].copy()
    result = summarize_metrics(
        sample,
        group_columns=("model", "split"),
        metric_horizons=side_metric_horizons(side),
        cluster="level_cluster_id",
        protocol=protocol,
        extra={"side": side, "source": "REAL_CHIP"},
    )
    expected = {
        "reaction_probability": "HIGHER_IS_SUPPORTIVE",
        "close_favorable_probability": "HIGHER_IS_SUPPORTIVE",
        "volume_response_ratio": "HIGHER_IS_SUPPORTIVE",
        "turnover_response_ratio": "HIGHER_IS_SUPPORTIVE",
        "range_response_ratio": "HIGHER_IS_SUPPORTIVE",
    }
    result["expected_direction"] = (
        result["metric"]
        .map(expected)
        .fillna(
            result["metric"].map(
                lambda name: (
                    "LOWER_IS_SUPPORTIVE"
                    if name.startswith(("cross_probability", "sessions_beyond"))
                    else "CONTEXT_DEPENDENT"
                )
            )
        )
    )
    return result


def paired_control_results(
    events: pd.DataFrame,
    statuses: pd.DataFrame,
    control_source: str,
    protocol: dict[str, Any],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    replicates = int(protocol["statistics"]["cluster_bootstrap_replicates"])
    seed_base = int(protocol["statistics"]["bootstrap_seed"])
    real_status = statuses[statuses["source"].eq("REAL_CHIP")]
    control_status = statuses[statuses["source"].eq(control_source)]
    status_pair = real_status.merge(
        control_status,
        on="level_id",
        suffixes=("_chip", "_control"),
        validate="one_to_one",
    )
    if not status_pair.empty:
        status_pair["paired_effect"] = status_pair["touched_chip"].astype(float) - status_pair[
            "touched_control"
        ].astype(float)
        for keys, group in status_pair.groupby(
            ["model_chip", "split_chip", "side_chip"], sort=True
        ):
            model, split, side = keys
            seed = int(stable_id(seed_base, control_source, *keys, "touch")[:16], 16) % (2**32)
            result = cluster_ci(
                group, "paired_effect", "level_cluster_id_chip", seed=seed, replicates=replicates
            )
            rows.append(
                {
                    "control": control_source,
                    "model": model,
                    "split": split,
                    "side": side,
                    "metric": "touch_probability",
                    "horizon": 40,
                    "expected_direction": "CONTEXT_DEPENDENT",
                    **result,
                }
            )

    first = events[events["touch_number"].eq(1)]
    real = first[first["source"].eq("REAL_CHIP")]
    control = first[first["source"].eq(control_source)]
    pair = real.merge(control, on="level_id", suffixes=("_chip", "_control"), validate="one_to_one")
    for side in ("SUPPORT", "RESISTANCE"):
        side_pair = pair[pair["side_chip"].eq(side)].copy()
        for metric, horizon in side_metric_horizons(side):
            left = f"{metric}_chip"
            right = f"{metric}_control"
            if left not in side_pair or right not in side_pair:
                continue
            side_pair["paired_effect"] = side_pair[left].astype(float) - side_pair[right].astype(
                float
            )
            for keys, group in side_pair.groupby(["model_chip", "split_chip"], sort=True):
                model, split = keys
                seed = int(
                    stable_id(seed_base, control_source, side, model, split, metric)[:16], 16
                ) % (2**32)
                result = cluster_ci(
                    group,
                    "paired_effect",
                    "level_cluster_id_chip",
                    seed=seed,
                    replicates=replicates,
                )
                if metric.startswith(("cross_probability", "sessions_beyond")):
                    expected = "NEGATIVE_IS_CHIP_BETTER"
                elif metric in {
                    "reaction_probability",
                    "close_favorable_probability",
                    "volume_response_ratio",
                    "turnover_response_ratio",
                    "range_response_ratio",
                }:
                    expected = "POSITIVE_IS_CHIP_BETTER"
                elif metric.startswith("mae_"):
                    expected = (
                        "POSITIVE_IS_CHIP_BETTER"
                        if side == "SUPPORT"
                        else "NEGATIVE_IS_CHIP_BETTER"
                    )
                elif metric.startswith("mfe_"):
                    expected = (
                        "CONTEXT_DEPENDENT" if side == "SUPPORT" else "NEGATIVE_IS_CHIP_BETTER"
                    )
                elif metric.startswith("future_return_"):
                    expected = (
                        "POSITIVE_IS_CHIP_BETTER"
                        if side == "SUPPORT"
                        else "NEGATIVE_IS_CHIP_BETTER"
                    )
                else:
                    expected = "CONTEXT_DEPENDENT"
                rows.append(
                    {
                        "control": control_source,
                        "model": model,
                        "split": split,
                        "side": side,
                        "metric": metric,
                        "horizon": horizon,
                        "expected_direction": expected,
                        **result,
                    }
                )
    return pd.DataFrame(rows)


def discovery_thresholds(descriptors: pd.DataFrame, peaks: pd.DataFrame) -> dict[str, Any]:
    thresholds: dict[str, Any] = {"strength": {}, "shape": {}, "ambiguity": {}}
    discovery_peaks = peaks[peaks["split"].eq("discovery")]
    for model in MODELS:
        sample = discovery_peaks[discovery_peaks["model"].eq(model)]
        thresholds["strength"][model] = {}
        for feature in ("peak_mass", "peak_prominence", "peak_age", "distribution_band_mass"):
            values = sample[feature].dropna().to_numpy(dtype=float)
            thresholds["strength"][model][feature] = (
                [float(value) for value in np.quantile(values, [0.2, 0.4, 0.6, 0.8])]
                if len(values) >= 5
                else []
            )
    discovery_descriptors = descriptors[descriptors["split"].eq("discovery")]
    for model in MODELS:
        sample = discovery_descriptors[discovery_descriptors["model"].eq(model)]
        thresholds["shape"][model] = {
            "width_q75": float(sample["p90_p10_log_width"].quantile(0.75)),
            "hhi_q25": float(sample["bucket_hhi"].quantile(0.25)),
            "entropy_q75": float(sample["normalized_entropy"].quantile(0.75)),
        }
    return thresholds


def assign_strength_bins(peaks: pd.DataFrame, thresholds: dict[str, Any]) -> pd.DataFrame:
    result = peaks.copy()
    labels = ("LOW", "MEDIUM_LOW", "MEDIUM", "MEDIUM_HIGH", "HIGH")
    for feature in ("peak_mass", "peak_prominence", "peak_age", "distribution_band_mass"):
        bins = []
        for row in result.itertuples(index=False):
            cuts = thresholds["strength"][row.model][feature]
            if len(cuts) != 4 or not finite(getattr(row, feature)):
                bins.append(None)
                continue
            index = int(
                np.searchsorted(np.asarray(cuts), float(getattr(row, feature)), side="right")
            )
            bins.append(labels[index])
        result[f"{feature}_bin"] = bins
    return result


def peak_strength_results(
    events: pd.DataFrame,
    peaks: pd.DataFrame,
    protocol: dict[str, Any],
) -> pd.DataFrame:
    bin_columns = [
        "level_id",
        "peak_mass_bin",
        "peak_prominence_bin",
        "peak_age_bin",
        "distribution_band_mass_bin",
    ]
    sample = events[events["source"].eq("REAL_CHIP") & events["touch_number"].eq(1)].merge(
        peaks[bin_columns], on="level_id", how="left", validate="one_to_one"
    )
    order = {
        name: index
        for index, name in enumerate(("LOW", "MEDIUM_LOW", "MEDIUM", "MEDIUM_HIGH", "HIGH"))
    }
    rows = []
    metrics = (
        ("reaction_probability", "HIGHER"),
        ("cross_probability_10", "LOWER"),
        ("future_return_5", "SIDE_DEPENDENT"),
        ("mae_10", "SIDE_DEPENDENT"),
    )
    for feature in ("peak_mass", "peak_prominence", "peak_age", "distribution_band_mass"):
        bin_column = f"{feature}_bin"
        for keys, group in sample.groupby(["model", "split", "side"], sort=True):
            model, split, side = keys
            for metric, direction in metrics:
                means = group.groupby(bin_column, sort=False)[metric].mean().dropna()
                points = sorted(
                    (order[name], float(value)) for name, value in means.items() if name in order
                )
                if len(points) < 3:
                    rho = math.nan
                    monotonic_steps = math.nan
                else:
                    x = np.asarray([item[0] for item in points], dtype=float)
                    y = np.asarray([item[1] for item in points], dtype=float)
                    rho = float(pd.Series(x).corr(pd.Series(y), method="spearman"))
                    differences = np.diff(y)
                    expected_sign = -1.0 if direction == "LOWER" else 1.0
                    if direction == "SIDE_DEPENDENT":
                        expected_sign = 1.0 if side == "SUPPORT" else -1.0
                    monotonic_steps = float(np.mean(expected_sign * differences >= 0.0))
                low = means.get("LOW", math.nan)
                high = means.get("HIGH", math.nan)
                rows.append(
                    {
                        "model": model,
                        "split": split,
                        "side": side,
                        "strength_feature": feature,
                        "outcome": metric,
                        "N": int(group[[metric, bin_column]].dropna().shape[0]),
                        "independent_event_count": int(
                            group.loc[group[metric].notna(), "level_cluster_id"].nunique()
                        ),
                        "low_bin_mean": low,
                        "high_bin_mean": high,
                        "high_minus_low": high - low if finite(high) and finite(low) else math.nan,
                        "spearman_bin_mean": rho,
                        "directionally_coherent_step_fraction": monotonic_steps,
                    }
                )
    return pd.DataFrame(rows)


def classify_distribution_shapes(
    descriptors: pd.DataFrame, thresholds: dict[str, Any]
) -> pd.DataFrame:
    result = descriptors.copy()
    shapes = []
    for row in result.itertuples(index=False):
        mode_count = int(row.tracked_mode_count)
        largest = float(row.largest_mode_mass) if finite(row.largest_mode_mass) else 0.0
        second = float(row.second_mode_mass) if finite(row.second_mode_mass) else 0.0
        shape_threshold = thresholds["shape"][row.model]
        if mode_count <= 1 or (largest > 0.0 and largest / max(largest + second, 1e-12) >= 0.60):
            shape = "SINGLE_DOMINANT"
        elif mode_count == 2 or (largest > 0.0 and second / largest >= 0.50):
            shape = "DOUBLE_PEAK"
        elif (
            row.p90_p10_log_width >= shape_threshold["width_q75"]
            and row.bucket_hhi <= shape_threshold["hhi_q25"]
        ):
            shape = "BROAD"
        else:
            shape = "FRAGMENTED_MULTI"
        shapes.append(shape)
    result["distribution_shape"] = shapes
    return result


def distribution_shape_results(descriptors: pd.DataFrame, protocol: dict[str, Any]) -> pd.DataFrame:
    metrics = []
    for horizon in (5, 10, 20, 40):
        metrics.extend(
            [
                (f"future_return_{horizon}", horizon),
                (f"mfe_{horizon}", horizon),
                (f"mae_{horizon}", horizon),
                (f"future_volatility_{horizon}", horizon),
                (f"future_volume_ratio_{horizon}", horizon),
            ]
        )
    return summarize_metrics(
        descriptors,
        group_columns=("model", "split", "distribution_shape"),
        metric_horizons=metrics,
        cluster="symbol",
        protocol=protocol,
    )


def full_distribution_vs_peak(
    events: pd.DataFrame,
    descriptors: pd.DataFrame,
    peaks: pd.DataFrame,
    protocol: dict[str, Any],
) -> pd.DataFrame:
    first = (
        events[events["source"].eq("REAL_CHIP") & events["touch_number"].eq(1)]
        .merge(
            peaks[
                [
                    "level_id",
                    "peak_mass_bin",
                    "peak_prominence_bin",
                    "distribution_band_mass_bin",
                ]
            ],
            on="level_id",
            how="left",
            validate="one_to_one",
        )
        .merge(
            descriptors[
                [
                    "snapshot_key",
                    "mass_within_5pct_below",
                    "mass_within_5pct_above",
                    "bucket_hhi",
                    "normalized_entropy",
                    "p90_p10_log_width",
                ]
            ],
            on="snapshot_key",
            how="left",
            validate="many_to_one",
        )
    )
    rows = []
    features = (
        ("PEAK", "peak_mass_bin"),
        ("PEAK", "peak_prominence_bin"),
        ("FULL_DISTRIBUTION", "distribution_band_mass_bin"),
    )
    for representation, feature in features:
        for keys, group in first.groupby(["model", "split", "side"], sort=True):
            model, split, side = keys
            low = group[group[feature].eq("LOW")]
            high = group[group[feature].eq("HIGH")]
            for metric in (
                "reaction_probability",
                "cross_probability_10",
                "future_return_5",
                "mae_10",
                "mfe_10",
            ):
                low_mean = float(low[metric].mean()) if low[metric].notna().any() else math.nan
                high_mean = float(high[metric].mean()) if high[metric].notna().any() else math.nan
                rows.append(
                    {
                        "representation": representation,
                        "feature": feature.removesuffix("_bin"),
                        "model": model,
                        "split": split,
                        "side": side,
                        "metric": metric,
                        "N_low": int(low[metric].notna().sum()),
                        "N_high": int(high[metric].notna().sum()),
                        "independent_event_count": int(
                            group.loc[group[metric].notna(), "level_cluster_id"].nunique()
                        ),
                        "low_mean": low_mean,
                        "high_mean": high_mean,
                        "high_minus_low": high_mean - low_mean
                        if finite(high_mean) and finite(low_mean)
                        else math.nan,
                    }
                )
    return pd.DataFrame(rows)


def ambiguity_decomposition(descriptors: pd.DataFrame, protocol: dict[str, Any]) -> pd.DataFrame:
    ensemble = descriptors[descriptors["model"].eq("ENSEMBLE")].copy()
    sellers = descriptors[descriptors["model"].isin(SELLER_MODEL_ORDER)]
    seller_groups = {
        (symbol, checkpoint): group
        for (symbol, checkpoint), group in sellers.groupby(["symbol", "checkpoint_date"], sort=True)
    }
    categories = []
    spreads = []
    mass_cvs = []
    mode_disagreements = []
    for row in ensemble.itertuples(index=False):
        group = seller_groups[(row.symbol, row.checkpoint_date)]
        centers = group["base_center"].dropna().to_numpy(dtype=float)
        masses = group["base_mass"].dropna().to_numpy(dtype=float)
        modes = group["tracked_mode_count"].to_numpy(dtype=int)
        spread = float(centers.max() / centers.min() - 1.0) if len(centers) >= 2 else math.nan
        mass_cv = (
            float(masses.std() / masses.mean())
            if len(masses) >= 2 and masses.mean() > 0
            else math.nan
        )
        mode_disagreement = int(modes.max() - modes.min())
        ambiguous = pd.isna(row.base_track_id)
        if not ambiguous:
            category = "NON_AMBIGUOUS"
        elif len(centers) < len(SELLER_MODEL_ORDER):
            category = "MODEL_BASE_MISSING"
        elif spread >= 0.05:
            category = "LEVEL_DISAGREEMENT"
        elif mode_disagreement > 0:
            category = "MODE_COUNT_DISAGREEMENT"
        elif mass_cv >= 0.25:
            category = "MASS_DISAGREEMENT"
        elif (
            row.normalized_entropy
            >= protocol["derived_thresholds"]["shape"]["ENSEMBLE"]["entropy_q75"]
        ):
            category = "DIFFUSE_DISTRIBUTION"
        else:
            category = "TRANSITIONAL_OR_UNRESOLVED"
        categories.append(category)
        spreads.append(spread)
        mass_cvs.append(mass_cv)
        mode_disagreements.append(mode_disagreement)
    ensemble["ambiguity_category"] = categories
    ensemble["model_base_level_spread"] = spreads
    ensemble["model_base_mass_cv"] = mass_cvs
    ensemble["model_mode_count_range"] = mode_disagreements
    metrics = [
        ("model_base_level_spread", 0),
        ("model_base_mass_cv", 0),
        ("model_mode_count_range", 0),
        ("future_chop_10", 10),
    ]
    for horizon in (5, 10, 20):
        metrics.extend(
            [
                (f"future_return_{horizon}", horizon),
                (f"mfe_{horizon}", horizon),
                (f"mae_{horizon}", horizon),
                (f"future_volatility_{horizon}", horizon),
                (f"future_volume_ratio_{horizon}", horizon),
            ]
        )
    summary = summarize_metrics(
        ensemble,
        group_columns=("split", "ambiguity_category"),
        metric_horizons=metrics,
        cluster="symbol",
        protocol=protocol,
    )
    matched_rows = []
    outcome_metrics = [
        name
        for name, _ in metrics
        if name.startswith("future_") or name.startswith(("mfe_", "mae_"))
    ]
    ambiguous_rows = ensemble[ensemble["ambiguity_category"].ne("NON_AMBIGUOUS")]
    for ambiguous in ambiguous_rows.itertuples(index=False):
        candidates = ensemble[
            ensemble["ambiguity_category"].eq("NON_AMBIGUOUS")
            & ensemble["symbol"].eq(ambiguous.symbol)
            & ensemble["split"].eq(ambiguous.split)
        ].copy()
        if candidates.empty:
            continue
        candidates["match_score"] = (
            (candidates["recent_volatility"] - ambiguous.recent_volatility).abs() / 0.02
            + (candidates["recent_trend"] - ambiguous.recent_trend).abs() / 0.10
            + (
                pd.to_datetime(candidates["checkpoint_date"])
                - pd.Timestamp(ambiguous.checkpoint_date)
            )
            .abs()
            .dt.days
            / 120.0
        )
        control = candidates.sort_values(
            ["match_score", "checkpoint_date", "snapshot_key"], kind="stable"
        ).iloc[0]
        matched = {
            "split": ambiguous.split,
            "ambiguity_category": "MATCHED_AMBIGUOUS_MINUS_NON_AMBIGUOUS",
            "symbol": ambiguous.symbol,
        }
        for metric in outcome_metrics:
            ambiguous_value = getattr(ambiguous, metric)
            control_value = control[metric]
            matched[metric] = (
                float(ambiguous_value) - float(control_value)
                if finite(ambiguous_value) and finite(control_value)
                else math.nan
            )
        matched_rows.append(matched)
    if matched_rows:
        matched_metric_horizons = [item for item in metrics if item[0] in outcome_metrics]
        matched_summary = summarize_metrics(
            pd.DataFrame(matched_rows),
            group_columns=("split", "ambiguity_category"),
            metric_horizons=matched_metric_horizons,
            cluster="symbol",
            protocol=protocol,
        )
        summary = pd.concat([summary, matched_summary], ignore_index=True, sort=False)
    return summary


def migration_results(
    migrations: pd.DataFrame,
    descriptors: pd.DataFrame,
    protocol: dict[str, Any],
) -> pd.DataFrame:
    merged = migrations.merge(
        descriptors[
            [
                "snapshot_key",
                *[
                    f"{metric}_{horizon}"
                    for horizon in (5, 10, 20, 40)
                    for metric in ("future_return", "mfe", "mae", "future_volatility")
                ],
            ]
        ],
        on="snapshot_key",
        how="left",
        validate="one_to_one",
    )
    metrics = [("median_shift_fraction", 0), ("width_change_fraction", 0)]
    for horizon in (5, 10, 20, 40):
        metrics.extend(
            [
                (f"future_return_{horizon}", horizon),
                (f"mfe_{horizon}", horizon),
                (f"mae_{horizon}", horizon),
                (f"future_volatility_{horizon}", horizon),
            ]
        )
    return summarize_metrics(
        merged[merged["corporate_action_path_valid"]],
        group_columns=("model", "split", "migration_state"),
        metric_horizons=metrics,
        cluster="symbol",
        protocol=protocol,
    )


def old_base_destruction_results(
    transitions: pd.DataFrame,
    prices: pd.DataFrame,
    protocol: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    records_by_symbol, index_by_symbol = valid_price_records(prices)
    contexts = price_context(prices)
    rows = []
    statuses = []
    for item in transitions.itertuples(index=False):
        if item.base_integrity == "BASE_INTERMEDIATE" or item.old_base_upper >= item.current_close:
            continue
        status, touches = simulate_level(
            symbol=item.symbol,
            checkpoint_date=pd.Timestamp(item.checkpoint_date),
            side="SUPPORT",
            lower=float(item.old_base_lower),
            center=float(item.old_base_center),
            upper=float(item.old_base_upper),
            records=records_by_symbol[item.symbol],
            date_index=index_by_symbol[item.symbol],
            protocol=protocol,
        )
        common = {
            "base_transition_id": item.base_transition_id,
            "symbol": item.symbol,
            "checkpoint_date": item.checkpoint_date,
            "split": item.split,
            "model": item.model,
            "base_integrity": item.base_integrity,
            "mass_retention": item.mass_retention,
            "distance_fraction": abs(item.old_base_center / item.current_close - 1.0),
            "recent_volatility": contexts.get(
                (item.symbol, pd.Timestamp(item.checkpoint_date)), {}
            ).get("recent_volatility", math.nan),
            "recent_trend": contexts.get((item.symbol, pd.Timestamp(item.checkpoint_date)), {}).get(
                "recent_trend", math.nan
            ),
        }
        statuses.append({**common, **status})
        rows.extend({**common, **touch} for touch in touches)
    raw = pd.DataFrame(rows)
    status_frame = pd.DataFrame(statuses)
    metrics = [("reaction_probability", 3), ("close_favorable_probability", 0)]
    for horizon in (5, 10, 20, 40):
        metrics.extend(
            [
                (f"future_return_{horizon}", horizon),
                (f"mae_{horizon}", horizon),
                (f"cross_probability_{horizon}", horizon),
                (f"sessions_beyond_{horizon}", horizon),
            ]
        )
    first = raw[raw["touch_number"].eq(1)] if not raw.empty else raw
    summary = (
        summarize_metrics(
            first,
            group_columns=("model", "split", "base_integrity"),
            metric_horizons=metrics,
            cluster="symbol",
            protocol=protocol,
        )
        if not first.empty
        else pd.DataFrame()
    )
    if not first.empty:
        paired_rows = []
        metric_names = [name for name, _ in metrics]
        for damaged in first[first["base_integrity"].eq("BASE_DAMAGED_OR_LOST")].itertuples(
            index=False
        ):
            candidates = first[
                first["base_integrity"].eq("BASE_INTACT")
                & first["model"].eq(damaged.model)
                & first["split"].eq(damaged.split)
                & first["symbol"].eq(damaged.symbol)
            ].copy()
            if candidates.empty:
                continue
            candidates["match_score"] = (
                (candidates["distance_fraction"] - damaged.distance_fraction).abs() / 0.05
                + (candidates["recent_volatility"] - damaged.recent_volatility).abs() / 0.02
                + (candidates["recent_trend"] - damaged.recent_trend).abs() / 0.10
                + (
                    pd.to_datetime(candidates["checkpoint_date"])
                    - pd.Timestamp(damaged.checkpoint_date)
                )
                .abs()
                .dt.days
                / 120.0
            )
            intact = candidates.sort_values(
                ["match_score", "checkpoint_date", "base_transition_id"], kind="stable"
            ).iloc[0]
            paired = {
                "model": damaged.model,
                "split": damaged.split,
                "base_integrity": "MATCHED_INTACT_MINUS_DAMAGED",
                "symbol": damaged.symbol,
            }
            for metric in metric_names:
                damaged_value = getattr(damaged, metric)
                intact_value = intact[metric]
                paired[metric] = (
                    float(intact_value) - float(damaged_value)
                    if finite(intact_value) and finite(damaged_value)
                    else math.nan
                )
            paired_rows.append(paired)
        if paired_rows:
            matched_summary = summarize_metrics(
                pd.DataFrame(paired_rows),
                group_columns=("model", "split", "base_integrity"),
                metric_horizons=metrics,
                cluster="symbol",
                protocol=protocol,
            )
            summary = pd.concat([summary, matched_summary], ignore_index=True, sort=False)
    return summary, status_frame


def new_base_formation_results(
    events: pd.DataFrame,
    protocol: dict[str, Any],
) -> pd.DataFrame:
    sample = events[
        events["source"].isin(["REAL_CHIP", "MATCHED_PLACEBO"])
        & events["touch_number"].eq(1)
        & events["is_base_peak"]
    ].copy()
    sample["base_age_group"] = pd.cut(
        sample["peak_age"],
        bins=[
            0,
            int(protocol["migration"]["new_base_max_age"]),
            int(protocol["migration"]["persistent_base_min_age"]) - 1,
            math.inf,
        ],
        labels=["NEW_AGE_1_5", "MATURING_AGE_6_19", "PERSISTENT_AGE_20_PLUS"],
        include_lowest=True,
    ).astype(str)
    metrics = [("reaction_probability", 3), ("close_favorable_probability", 0)]
    for horizon in (5, 10, 20, 40):
        metrics.extend(
            [
                (f"future_return_{horizon}", horizon),
                (f"mae_{horizon}", horizon),
                (f"cross_probability_{horizon}", horizon),
            ]
        )
    return summarize_metrics(
        sample,
        group_columns=("model", "split", "source", "base_age_group"),
        metric_horizons=metrics,
        cluster="level_cluster_id",
        protocol=protocol,
    )


def repeated_touch_results(events: pd.DataFrame, protocol: dict[str, Any]) -> pd.DataFrame:
    sample = events[events["source"].eq("REAL_CHIP")].copy()
    sample.loc[sample["touch_number"] >= 3, "touch_bucket"] = "THIRD_PLUS"
    metrics = [
        ("reaction_probability", 3),
        ("close_favorable_probability", 0),
        ("cross_probability_10", 10),
        ("time_to_cross_10", 10),
        ("future_return_5", 5),
        ("mae_10", 10),
        ("mfe_10", 10),
    ]
    return summarize_metrics(
        sample,
        group_columns=("model", "split", "side", "touch_bucket"),
        metric_horizons=metrics,
        cluster="level_id",
        protocol=protocol,
    )


def crossing_difficulty_results(events: pd.DataFrame, protocol: dict[str, Any]) -> pd.DataFrame:
    sample = events[events["touch_number"].eq(1)].copy()
    metrics = []
    for horizon in (1, 5, 10, 20, 40):
        metrics.extend(
            [
                (f"cross_probability_{horizon}", horizon),
                (f"time_to_cross_{horizon}", horizon),
                (f"sessions_beyond_{horizon}", horizon),
            ]
        )
    return summarize_metrics(
        sample,
        group_columns=("model", "split", "side", "source"),
        metric_horizons=metrics,
        cluster="level_cluster_id",
        protocol=protocol,
    )


def turnover_results(events: pd.DataFrame, protocol: dict[str, Any]) -> pd.DataFrame:
    sample = events[events["touch_number"].eq(1)]
    return summarize_metrics(
        sample,
        group_columns=("model", "split", "side", "source"),
        metric_horizons=(
            ("volume_response_ratio", 3),
            ("turnover_response_ratio", 3),
            ("range_response_ratio", 3),
        ),
        cluster="level_cluster_id",
        protocol=protocol,
    )


def horizon_map_results(events: pd.DataFrame, protocol: dict[str, Any]) -> pd.DataFrame:
    sample = events[events["source"].eq("REAL_CHIP") & events["touch_number"].eq(1)]
    metrics = []
    for horizon in HORIZONS:
        metrics.extend(
            [
                (f"future_return_{horizon}", horizon),
                (f"mfe_{horizon}", horizon),
                (f"mae_{horizon}", horizon),
                (f"cross_probability_{horizon}", horizon),
            ]
        )
    return summarize_metrics(
        sample,
        group_columns=("model", "split", "side"),
        metric_horizons=metrics,
        cluster="level_cluster_id",
        protocol=protocol,
    )


def corporate_action_sanity(
    features: pd.DataFrame,
    prices: pd.DataFrame,
    protocol: dict[str, Any],
) -> pd.DataFrame:
    rows = []
    for action in prices[
        prices["corporate_action_count"].fillna(0).astype(int).gt(0)
        & prices["trade_date"].between("2020-01-02", "2020-12-31")
    ].itertuples(index=False):
        symbol_features = features[
            features["symbol"].eq(action.symbol) & features["trade_date"].le(action.trade_date)
        ].sort_values("trade_date")
        if len(symbol_features) < 2:
            continue
        current = symbol_features.iloc[-1]
        previous = symbol_features.iloc[-2]
        if current["trade_date"] != action.trade_date:
            continue
        valid_path = bool(action.corporate_action_valid) and not bool(
            action.corporate_action_blocking
        )
        for field in (
            "average_cost",
            "p10",
            "p50",
            "p90",
            "tracked_base_peak",
            "peak_track_band_lower",
            "peak_track_band_upper",
        ):
            old = previous[field]
            observed = current[field]
            if not valid_path or not finite(old) or not finite(observed):
                expected = math.nan
                error = math.nan
            else:
                expected = rebase_economic_price(
                    float(old),
                    cash_per_share=float(action.cash_per_share or 0.0),
                    share_multiplier=float(action.share_multiplier or 1.0),
                )
                error = float(observed) / expected - 1.0
            track_preserved = (
                pd.notna(previous["peak_track_id"])
                and previous["peak_track_id"] == current["peak_track_id"]
            )
            review = (
                track_preserved
                and finite(error)
                and abs(error)
                > float(
                    protocol["corporate_action_sanity"]["level_relative_error_review_threshold"]
                )
            )
            rows.append(
                {
                    "symbol": action.symbol,
                    "action_date": action.trade_date,
                    "split": split_for(action.trade_date),
                    "metric": field,
                    "corporate_action_ids": action.corporate_action_ids,
                    "corporate_action_snapshot_id": action.corporate_action_snapshot_id,
                    "cash_per_share": action.cash_per_share,
                    "share_multiplier": action.share_multiplier,
                    "action_path_valid": valid_path,
                    "previous_value": old,
                    "expected_transformed_previous": expected,
                    "observed_action_day": observed,
                    "relative_error_after_ordinary_transition": error,
                    "track_identity_preserved": track_preserved,
                    "review_anomaly": review,
                    "exact_daily_full_distribution_test": "UNAVAILABLE_WITHOUT_REPLAY",
                }
            )
    return pd.DataFrame(rows)


def time_shifted_future_state_control(
    peaks: pd.DataFrame,
    prices: pd.DataFrame,
    protocol: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Construct an explicitly non-primary look-ahead falsification control."""
    records_by_symbol, index_by_symbol = valid_price_records(prices)
    bases = peaks[peaks["is_base_peak"]].sort_values(["symbol", "model", "checkpoint_date"]).copy()
    for column in ("band_lower", "center", "band_upper", "close_at_definition", "side"):
        bases[f"next_{column}"] = bases.groupby(["symbol", "model"], sort=True)[column].shift(-1)
    event_rows = []
    status_rows = []
    for row in bases.itertuples(index=False):
        if row.side != row.next_side or not finite(row.next_center):
            continue
        lower = row.close_at_definition * row.next_band_lower / row.next_close_at_definition
        center = row.close_at_definition * row.next_center / row.next_close_at_definition
        upper = row.close_at_definition * row.next_band_upper / row.next_close_at_definition
        status, touches = simulate_level(
            symbol=row.symbol,
            checkpoint_date=pd.Timestamp(row.checkpoint_date),
            side=row.side,
            lower=float(lower),
            center=float(center),
            upper=float(upper),
            records=records_by_symbol[row.symbol],
            date_index=index_by_symbol[row.symbol],
            protocol=protocol,
        )
        common = {
            "level_id": row.level_id,
            "snapshot_key": row.snapshot_key,
            "level_cluster_id": stable_id(row.symbol, row.checkpoint_date, row.model),
            "source_level_id": stable_id(row.level_id, "TIME_SHIFTED_FUTURE_STATE"),
            "source": "TIME_SHIFTED_FUTURE_STATE",
            "symbol": row.symbol,
            "checkpoint_date": row.checkpoint_date,
            "split": row.split,
            "model": row.model,
            "side": row.side,
            "peak_track_id": row.peak_track_id,
            "is_base_peak": True,
            "peak_age": row.peak_age,
            "peak_mass": row.peak_mass,
            "peak_prominence": row.peak_prominence,
            "distribution_band_mass": row.distribution_band_mass,
            "distance_fraction": abs(center / row.close_at_definition - 1.0),
            "band_width_fraction": (upper - lower) / center,
            "recent_volatility": row.recent_volatility,
            "recent_trend": row.recent_trend,
            "ensemble_ambiguous": row.ensemble_ambiguous,
            "defined_lower": lower,
            "defined_center": center,
            "defined_upper": upper,
        }
        status_rows.append({**common, **status})
        event_rows.extend({**common, **touch} for touch in touches)
    return pd.DataFrame(event_rows), pd.DataFrame(status_rows)


def falsification_results(
    matched_placebo: pd.DataFrame,
    time_shifted: pd.DataFrame,
    strength: pd.DataFrame,
    ambiguity: pd.DataFrame,
) -> pd.DataFrame:
    rows = []
    for source_name, frame in (
        ("RANDOM_LOW_MASS_MATCHED_LEVEL", matched_placebo),
        ("FUTURE_CHECKPOINT_TIME_SHIFT", time_shifted),
    ):
        selected = frame[
            frame["metric"].isin(
                ["reaction_probability", "cross_probability_10", "turnover_response_ratio"]
            )
            & frame["split"].isin(["validation", "holdout"])
        ]
        for row in selected.itertuples(index=False):
            rows.append(
                {
                    "falsification": source_name,
                    "model": row.model,
                    "split": row.split,
                    "side": row.side,
                    "metric": row.metric,
                    "N": row.N,
                    "independent_event_count": row.independent_event_count,
                    "effect_chip_minus_control": row.effect,
                    "ci_low": row.ci_low,
                    "ci_high": row.ci_high,
                    "expected_direction": row.expected_direction,
                }
            )
    weak = strength[
        strength["strength_feature"].isin(["peak_mass", "peak_prominence"])
        & strength["outcome"].isin(["reaction_probability", "cross_probability_10"])
        & strength["split"].isin(["validation", "holdout"])
    ]
    for row in weak.itertuples(index=False):
        rows.append(
            {
                "falsification": "WEAK_LOW_MASS_PEAK",
                "model": row.model,
                "split": row.split,
                "side": row.side,
                "metric": row.outcome,
                "N": row.N,
                "independent_event_count": row.independent_event_count,
                "effect_chip_minus_control": row.high_minus_low,
                "ci_low": math.nan,
                "ci_high": math.nan,
                "expected_direction": "STRONG_SHOULD_BE_MORE_DIRECTIONALLY_COHERENT",
            }
        )
    ambiguous = ambiguity[
        ambiguity["ambiguity_category"].ne("NON_AMBIGUOUS")
        & ambiguity["metric"].isin(["future_chop_10", "future_volatility_10"])
        & ambiguity["split"].isin(["validation", "holdout"])
    ]
    for row in ambiguous.itertuples(index=False):
        rows.append(
            {
                "falsification": "MODEL_DISAGREEMENT_STATE",
                "model": "ENSEMBLE",
                "split": row.split,
                "side": "STATE",
                "metric": row.metric,
                "N": row.N,
                "independent_event_count": row.independent_event_count,
                "effect_chip_minus_control": row.effect,
                "ci_low": row.ci_low,
                "ci_high": row.ci_high,
                "expected_direction": "NO_DIRECTIONAL_RETURN_SIGN_PREREGISTERED",
            }
        )
    return pd.DataFrame(rows)


def _paired_metric_value(
    frame: pd.DataFrame,
    *,
    model: str,
    split: str,
    side: str,
    metric: str,
) -> tuple[float, int]:
    selected = frame[
        frame["model"].eq(model)
        & frame["split"].eq(split)
        & frame["side"].eq(side)
        & frame["metric"].eq(metric)
    ]
    if len(selected) != 1:
        return math.nan, 0
    row = selected.iloc[0]
    return float(row["effect"]), int(row["independent_event_count"])


def _side_period_evidence(
    paired: pd.DataFrame,
    model: str,
    split: str,
    side: str,
    protocol: dict[str, Any],
) -> tuple[str, int, int]:
    limits = protocol["gate_rules"]["minimum_economic_effects"]
    minimum_n = int(protocol["statistics"]["minimum_effective_events_for_gate"])
    specifications = (
        [
            ("reaction_probability", 1.0, limits["probability_difference"]),
            ("cross_probability_10", -1.0, limits["probability_difference"]),
            ("future_return_5", 1.0, limits["five_session_return_difference"]),
            ("mae_10", 1.0, limits["ten_session_excursion_difference"]),
            ("turnover_response_ratio", 1.0, limits["activity_ratio_difference"]),
        ]
        if side == "SUPPORT"
        else [
            ("reaction_probability", 1.0, limits["probability_difference"]),
            ("cross_probability_10", -1.0, limits["probability_difference"]),
            ("future_return_5", -1.0, limits["five_session_return_difference"]),
            ("mfe_10", -1.0, limits["ten_session_excursion_difference"]),
            ("turnover_response_ratio", 1.0, limits["activity_ratio_difference"]),
        ]
    )
    supportive = 0
    powered = 0
    opposite = 0
    for metric, sign, threshold in specifications:
        effect, count = _paired_metric_value(
            paired, model=model, split=split, side=side, metric=metric
        )
        if count < minimum_n or not finite(effect):
            continue
        powered += 1
        directed = sign * effect
        supportive += directed >= float(threshold)
        opposite += directed <= -float(threshold)
    if powered < 3:
        return "MIXED", supportive, powered
    if supportive >= 3 and opposite == 0:
        return "YES", supportive, powered
    if supportive == 0 and opposite >= 2:
        return "NO", supportive, powered
    return "MIXED", supportive, powered


def _combine_model_periods(statuses: dict[tuple[str, str], str]) -> str:
    seller_status = {
        model: [statuses.get((model, split), "MIXED") for split in ("validation", "holdout")]
        for model in SELLER_MODEL_ORDER
    }
    yes_models = sum(all(value == "YES" for value in periods) for periods in seller_status.values())
    no_models = sum(all(value == "NO" for value in periods) for periods in seller_status.values())
    if yes_models >= 2:
        return "YES"
    if no_models == len(SELLER_MODEL_ORDER):
        return "NO"
    return "MIXED"


def _classification(*statuses: str, descriptive: bool = False) -> str:
    if statuses and all(value == "YES" for value in statuses):
        return "ECONOMICALLY_VALIDATED"
    if any(value in {"YES", "MIXED"} for value in statuses):
        return "PARTIALLY_VALIDATED"
    return "DESCRIPTIVE_ONLY" if descriptive else "NOT_VALIDATED"


def synthesize_gates(
    *,
    matched_placebo: pd.DataFrame,
    price_only: pd.DataFrame,
    strength: pd.DataFrame,
    repeated: pd.DataFrame,
    migration: pd.DataFrame,
    old_base: pd.DataFrame,
    new_base: pd.DataFrame,
    ambiguity: pd.DataFrame,
    representation: pd.DataFrame,
    shapes: pd.DataFrame,
    protocol: dict[str, Any],
) -> tuple[dict[str, str], pd.DataFrame, pd.DataFrame]:
    score_rows = []
    side_statuses: dict[str, dict[tuple[str, str], str]] = {"SUPPORT": {}, "RESISTANCE": {}}
    for model in MODELS:
        for split in ("validation", "holdout"):
            for side in ("SUPPORT", "RESISTANCE"):
                status, supportive, powered = _side_period_evidence(
                    matched_placebo, model, split, side, protocol
                )
                side_statuses[side][(model, split)] = status
                score_rows.append(
                    {
                        "model": model,
                        "test": f"{side.lower()}_vs_matched_placebo",
                        "split": split,
                        "classification": status,
                        "supportive_primary_metrics": supportive,
                        "powered_primary_metrics": powered,
                    }
                )
    support_gate = _combine_model_periods(side_statuses["SUPPORT"])
    resistance_gate = _combine_model_periods(side_statuses["RESISTANCE"])

    minimum_n = int(protocol["statistics"]["minimum_effective_events_for_gate"])
    economic_limits = protocol["gate_rules"]["minimum_economic_effects"]
    tournament_metrics = (
        (
            "crossing_prediction",
            "cross_probability_10",
            -1.0,
            economic_limits["probability_difference"],
        ),
        (
            "volume_response",
            "turnover_response_ratio",
            1.0,
            economic_limits["activity_ratio_difference"],
        ),
    )
    for model in MODELS:
        for split in ("validation", "holdout"):
            for test, metric, sign, threshold in tournament_metrics:
                evidence = []
                counts = []
                for side in ("SUPPORT", "RESISTANCE"):
                    effect, count = _paired_metric_value(
                        matched_placebo,
                        model=model,
                        split=split,
                        side=side,
                        metric=metric,
                    )
                    if count >= minimum_n and finite(effect):
                        evidence.append(sign * effect)
                        counts.append(count)
                if len(evidence) < 2:
                    classification = "MIXED"
                elif all(value >= float(threshold) for value in evidence):
                    classification = "YES"
                elif all(value <= 0.0 for value in evidence):
                    classification = "NO"
                else:
                    classification = "MIXED"
                score_rows.append(
                    {
                        "model": model,
                        "test": test,
                        "split": split,
                        "classification": classification,
                        "supportive_primary_metrics": sum(
                            value >= float(threshold) for value in evidence
                        ),
                        "powered_primary_metrics": len(evidence),
                    }
                )

            for test, frame, metric, threshold in (
                ("cost_migration_validity", migration, "future_return_20", 0.01),
                ("full_distribution_shape_validity", shapes, "future_volatility_10", 0.003),
            ):
                selected = frame[
                    frame["model"].eq(model)
                    & frame["split"].eq(split)
                    & frame["metric"].eq(metric)
                    & frame["independent_event_count"].ge(minimum_n)
                ]
                effect_range = (
                    float(selected["effect"].max() - selected["effect"].min())
                    if len(selected) >= 2
                    else math.nan
                )
                classification = (
                    "YES"
                    if finite(effect_range) and effect_range >= threshold
                    else ("NO" if finite(effect_range) else "MIXED")
                )
                score_rows.append(
                    {
                        "model": model,
                        "test": test,
                        "split": split,
                        "classification": classification,
                        "supportive_primary_metrics": int(classification == "YES"),
                        "powered_primary_metrics": len(selected),
                    }
                )

    price_status: dict[tuple[str, str], str] = {}
    for model in SELLER_MODEL_ORDER:
        for split in ("validation", "holdout"):
            statuses = [
                _side_period_evidence(price_only, model, split, side, protocol)[0]
                for side in ("SUPPORT", "RESISTANCE")
            ]
            price_status[(model, split)] = (
                "YES"
                if statuses.count("YES") == 2
                else ("NO" if statuses.count("NO") == 2 else "MIXED")
            )
    price_gate = _combine_model_periods(price_status)

    strength_sample = strength[
        strength["model"].isin(SELLER_MODEL_ORDER)
        & strength["split"].isin(["validation", "holdout"])
        & strength["strength_feature"].isin(["peak_mass", "peak_prominence"])
        & strength["outcome"].isin(["reaction_probability", "cross_probability_10"])
    ].copy()
    if not strength_sample.empty:
        strength_sample["directed_rho"] = np.where(
            strength_sample["outcome"].eq("cross_probability_10"),
            -strength_sample["spearman_bin_mean"],
            strength_sample["spearman_bin_mean"],
        )
        coherent = strength_sample["directed_rho"] >= float(
            protocol["gate_rules"]["minimum_economic_effects"]["dose_response_spearman"]
        )
        by_split = strength_sample.assign(coherent=coherent).groupby("split")["coherent"].mean()
        if all(by_split.get(split, 0.0) >= 0.60 for split in ("validation", "holdout")):
            strength_gate = "YES"
        elif all(by_split.get(split, 0.0) <= 0.20 for split in ("validation", "holdout")):
            strength_gate = "NO"
        else:
            strength_gate = "MIXED"
    else:
        strength_gate = "MIXED"

    def group_range_gate(frame: pd.DataFrame, group: str, metric: str, threshold: float) -> str:
        sample = frame[
            frame["split"].isin(["validation", "holdout"]) & frame["metric"].eq(metric)
        ].copy()
        sample = sample[
            sample["independent_event_count"]
            >= int(protocol["statistics"]["minimum_effective_events_for_gate"])
        ]
        if group in sample:
            sample = sample[~sample[group].astype(str).str.startswith("MATCHED_")]
        if "model" not in sample:
            sample["model"] = "ENSEMBLE"
        ranges = sample.groupby(["model", "split"])["effect"].agg(
            lambda values: values.max() - values.min()
        )
        if len(ranges) == 0:
            return "MIXED"
        period_ok = {
            split: bool(
                (ranges.xs(split, level="split", drop_level=False) >= threshold).mean() >= 0.5
            )
            if split in ranges.index.get_level_values("split")
            else False
            for split in ("validation", "holdout")
        }
        return (
            "YES" if all(period_ok.values()) else ("NO" if not any(period_ok.values()) else "MIXED")
        )

    migration_gate = group_range_gate(migration, "migration_state", "future_return_20", 0.01)
    ambiguity_periods = []
    for split in ("validation", "holdout"):
        matched = ambiguity[
            ambiguity["split"].eq(split)
            & ambiguity["ambiguity_category"].eq("MATCHED_AMBIGUOUS_MINUS_NON_AMBIGUOUS")
            & ambiguity["independent_event_count"].ge(minimum_n)
        ]
        chop = matched.loc[matched["metric"].eq("future_chop_10"), "effect"]
        volatility = matched.loc[matched["metric"].eq("future_volatility_10"), "effect"]
        interpretable = (not chop.empty and abs(float(chop.iloc[0])) >= 0.05) or (
            not volatility.empty and abs(float(volatility.iloc[0])) >= 0.003
        )
        ambiguity_periods.append(interpretable)
    ambiguity_gate = (
        "YES" if all(ambiguity_periods) else ("NO" if not any(ambiguity_periods) else "MIXED")
    )
    shape_gate = group_range_gate(shapes, "distribution_shape", "future_volatility_10", 0.003)

    def ordered_group_gate(
        frame: pd.DataFrame, group_col: str, favorable: str, unfavorable: str
    ) -> str:
        if frame.empty:
            return "MIXED"
        statuses = []
        for split in ("validation", "holdout"):
            sample = frame[
                frame["split"].eq(split) & frame["metric"].eq("reaction_probability")
            ].copy()
            sample = sample[
                sample["independent_event_count"]
                >= int(protocol["statistics"]["minimum_effective_events_for_gate"])
            ]
            pivot = sample.pivot_table(
                index="model", columns=group_col, values="effect", aggfunc="first"
            )
            if favorable not in pivot or unfavorable not in pivot:
                statuses.append("MIXED")
                continue
            difference = pivot[favorable] - pivot[unfavorable]
            statuses.append(
                "YES"
                if (difference >= 0.03).mean() >= 0.5
                else ("NO" if (difference <= 0).all() else "MIXED")
            )
        return (
            "YES" if statuses == ["YES", "YES"] else ("NO" if statuses == ["NO", "NO"] else "MIXED")
        )

    old_base_gate = ordered_group_gate(
        old_base, "base_integrity", "BASE_INTACT", "BASE_DAMAGED_OR_LOST"
    )
    new_base_gate = ordered_group_gate(
        new_base[new_base["source"].eq("REAL_CHIP")],
        "base_age_group",
        "PERSISTENT_AGE_20_PLUS",
        "NEW_AGE_1_5",
    )
    touch_gate = ordered_group_gate(repeated, "touch_bucket", "FIRST", "THIRD_PLUS")

    representation_sample = representation[
        representation["split"].isin(["validation", "holdout"])
        & representation["metric"].isin(
            ["reaction_probability", "cross_probability_10", "future_return_5", "mae_10"]
        )
    ].copy()
    representation_sample["directed_effect"] = representation_sample["high_minus_low"]
    representation_sample.loc[
        representation_sample["metric"].eq("cross_probability_10"), "directed_effect"
    ] *= -1
    representation_sample.loc[
        representation_sample["side"].eq("RESISTANCE")
        & representation_sample["metric"].isin(["future_return_5", "mae_10"]),
        "directed_effect",
    ] *= -1
    rep_means = representation_sample.groupby(["representation", "split"])["directed_effect"].mean()
    full_superior = []
    for split in ("validation", "holdout"):
        full_value = rep_means.get(("FULL_DISTRIBUTION", split), math.nan)
        peak_value = rep_means.get(("PEAK", split), math.nan)
        full_superior.append(finite(full_value) and finite(peak_value) and full_value > peak_value)
    full_gate = "YES" if all(full_superior) else ("NO" if not any(full_superior) else "MIXED")

    seller_totals: dict[str, int] = {}
    for model in MODELS:
        values = [
            side_statuses[side].get((model, split), "MIXED")
            for side in ("SUPPORT", "RESISTANCE")
            for split in ("validation", "holdout")
        ]
        seller_totals[model] = values.count("YES") - values.count("NO")
    best_score = max(seller_totals.values())
    best_models = [model for model, score in seller_totals.items() if score == best_score]
    ranked_scores = [*sorted(seller_totals.values(), reverse=True), -99]
    if best_score <= 0:
        best_model = "NONE"
    elif len(best_models) == 1 and ranked_scores[0] - ranked_scores[1] >= 2:
        best_model = best_models[0]
    else:
        best_model = "MIXED"
    seller_diff = (
        "YES" if max(seller_totals.values()) - min(seller_totals.values()) >= 2 else "MIXED"
    )
    ensemble_improves = (
        "YES"
        if seller_totals["ENSEMBLE"] > max(seller_totals[model] for model in SELLER_MODEL_ORDER)
        else (
            "NO"
            if seller_totals["ENSEMBLE"] < max(seller_totals[model] for model in SELLER_MODEL_ORDER)
            else "MIXED"
        )
    )

    canonical_class = _classification(support_gate, resistance_gate, strength_gate)
    full_class = _classification(full_gate, shape_gate, migration_gate, descriptive=True)
    overall = (
        "YES"
        if canonical_class == "ECONOMICALLY_VALIDATED" or full_class == "ECONOMICALLY_VALIDATED"
        else (
            "NO"
            if canonical_class == "NOT_VALIDATED"
            and full_class in {"NOT_VALIDATED", "DESCRIPTIVE_ONLY"}
            else "MIXED"
        )
    )
    gates = {
        "SUPPORT_HYPOTHESIS_VALIDATES_OUT_OF_SAMPLE": support_gate,
        "RESISTANCE_HYPOTHESIS_VALIDATES_OUT_OF_SAMPLE": resistance_gate,
        "CHIP_LEVELS_OUTPERFORM_MATCHED_PLACEBOS": (
            "YES"
            if support_gate == resistance_gate == "YES"
            else ("NO" if support_gate == resistance_gate == "NO" else "MIXED")
        ),
        "CHIP_ADDS_VALUE_BEYOND_PRICE_ONLY_LEVELS": price_gate,
        "PEAK_STRENGTH_SHOWS_ECONOMIC_DOSE_RESPONSE": strength_gate,
        "REPEATED_TOUCH_DECAY_SUPPORTS_INVENTORY_INTERPRETATION": touch_gate,
        "COST_MIGRATION_HAS_ECONOMIC_VALIDITY": migration_gate,
        "OLD_BASE_DESTRUCTION_REDUCES_FUTURE_SUPPORT": old_base_gate,
        "NEW_ROLLING_BASE_ACQUIRES_SUPPORT_VALUE": new_base_gate,
        "BEST_VALIDATED_SELLER_MODEL": best_model,
        "SELLER_MODELS_DIFFER_ECONOMICALLY": seller_diff,
        "ENSEMBLE_CONSENSUS_IMPROVES_VALIDITY": ensemble_improves,
        "ENSEMBLE_AMBIGUITY_HAS_INTERPRETABLE_ECONOMIC_MEANING": ambiguity_gate,
        "FULL_DISTRIBUTION_OUTPERFORMS_CANONICAL_PEAK": full_gate,
        "MULTI_PEAK_STRUCTURE_HAS_ECONOMIC_INFORMATION": shape_gate,
        "CHIP_INFORMATION_HAS_VALIDATED_SWING_HORIZON_EFFECT": (
            "YES"
            if support_gate == "YES" or resistance_gate == "YES"
            else ("NO" if support_gate == resistance_gate == "NO" else "MIXED")
        ),
        "CANONICAL_PEAK_ECONOMIC_CLASSIFICATION": canonical_class,
        "FULL_DISTRIBUTION_ECONOMIC_CLASSIFICATION": full_class,
        "CHIP_MODEL_ECONOMIC_VALIDITY_OVERALL": overall,
        "SELLER_MODEL_REDESIGN_STUDY_JUSTIFIED": "YES"
        if seller_diff != "NO" and overall != "YES"
        else "NO",
        "CANONICAL_PEAK_COMPRESSION_REDESIGN_STUDY_JUSTIFIED": "YES"
        if full_gate in {"YES", "MIXED"}
        else "NO",
        "SAFE_TO_CONTINUE_USING_V3_CHIP_FOR_RESEARCH": "YES"
        if overall == "YES"
        else ("NO" if overall == "NO" else "MIXED"),
        "SAFE_TO_CHANGE_PRODUCTION_CHIP_SEMANTICS": "NO",
        "SAFE_TO_DESIGN_PRODUCTION_STRATEGY": "NO",
        "SAFE_TO_EXPAND_RESEARCH_TO_FULL_MARKET_3941": "NO",
    }

    for model, score in seller_totals.items():
        support_periods = [
            side_statuses["SUPPORT"].get((model, split), "MIXED")
            for split in ("validation", "holdout")
        ]
        resistance_periods = [
            side_statuses["RESISTANCE"].get((model, split), "MIXED")
            for split in ("validation", "holdout")
        ]
        score_rows.append(
            {
                "model": model,
                "test": "unaggregated_directional_tournament_summary",
                "split": "out_of_sample",
                "classification": _classification(
                    side_statuses["SUPPORT"].get((model, "validation"), "MIXED"),
                    side_statuses["SUPPORT"].get((model, "holdout"), "MIXED"),
                    side_statuses["RESISTANCE"].get((model, "validation"), "MIXED"),
                    side_statuses["RESISTANCE"].get((model, "holdout"), "MIXED"),
                ),
                "supportive_primary_metrics": score,
                "powered_primary_metrics": 4,
            }
        )
        stable_sides = sum(
            periods[0] == periods[1] and periods[0] != "MIXED"
            for periods in (support_periods, resistance_periods)
        )
        score_rows.append(
            {
                "model": model,
                "test": "temporal_stability",
                "split": "out_of_sample",
                "classification": (
                    "YES" if stable_sides == 2 else ("NO" if stable_sides == 0 else "MIXED")
                ),
                "supportive_primary_metrics": stable_sides,
                "powered_primary_metrics": 2,
            }
        )
        robust_sides = sum(
            periods == ["YES", "YES"] for periods in (support_periods, resistance_periods)
        )
        score_rows.append(
            {
                "model": model,
                "test": "out_of_sample_robustness",
                "split": "out_of_sample",
                "classification": (
                    "YES" if robust_sides == 2 else ("NO" if robust_sides == 0 else "MIXED")
                ),
                "supportive_primary_metrics": robust_sides,
                "powered_primary_metrics": 2,
            }
        )
    scorecard = pd.DataFrame(score_rows)

    classifications = [
        {
            "representation": "CANONICAL_TEMPORAL_PEAK",
            "classification": canonical_class,
            "evidence": f"support={support_gate}; resistance={resistance_gate}; strength={strength_gate}",
        },
        {
            "representation": "FULL_CHIP_DISTRIBUTION",
            "classification": full_class,
            "evidence": f"vs_peak={full_gate}; shapes={shape_gate}; migration={migration_gate}",
        },
        {
            "representation": "ENSEMBLE_CANONICAL_CONSENSUS",
            "classification": _classification(ensemble_improves, ambiguity_gate),
            "evidence": f"consensus={ensemble_improves}; ambiguity={ambiguity_gate}",
        },
    ]
    for model in SELLER_MODEL_ORDER:
        classifications.append(
            {
                "representation": model,
                "classification": _classification(
                    side_statuses["SUPPORT"].get((model, "validation"), "MIXED"),
                    side_statuses["SUPPORT"].get((model, "holdout"), "MIXED"),
                    side_statuses["RESISTANCE"].get((model, "validation"), "MIXED"),
                    side_statuses["RESISTANCE"].get((model, "holdout"), "MIXED"),
                ),
                "evidence": "seller-model support/resistance matched-placebo tournament",
            }
        )
    return gates, scorecard, pd.DataFrame(classifications)


def universe_summary(
    symbols: Sequence[str],
    features: pd.DataFrame,
    prices: pd.DataFrame,
) -> dict[str, Any]:
    exchange_counts = Counter(symbol.rsplit(".", 1)[-1] for symbol in symbols)
    prefix_counts = Counter(symbol.split(".", 1)[0][:3] for symbol in symbols)
    year2020 = prices[prices["trade_date"].between("2020-01-01", "2020-12-31")]
    industry_by_symbol = (
        year2020.dropna(subset=["industry"])
        .sort_values("trade_date")
        .groupby("symbol", sort=True)["industry"]
        .last()
    )
    row_counts = features.groupby("symbol").size()
    return {
        "symbols": len(symbols),
        "exchange_counts": dict(sorted(exchange_counts.items())),
        "prefix_counts": dict(sorted(prefix_counts.items())),
        "industry_available_symbols": int(industry_by_symbol.shape[0]),
        "industry_counts": dict(
            sorted(Counter(industry_by_symbol).items(), key=lambda item: (-item[1], item[0]))
        ),
        "feature_date_min": str(features["trade_date"].min().date()),
        "feature_date_max": str(features["trade_date"].max().date()),
        "feature_rows": len(features),
        "feature_hard_valid_rows": int(features["hard_valid"].fillna(False).sum()),
        "per_symbol_feature_row_counts": {
            str(key): int(value) for key, value in sorted(Counter(row_counts).items())
        },
        "sampling_bias": (
            "Frozen engineering research cohort, not a probability sample of the A-share market; "
            "coverage is concentrated in the manifest's prefixes/exchanges and cannot establish "
            "full-market, delisting, or later-listing generality."
        ),
    }


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n", float_format="%.12g")


def report_markdown(
    *,
    gates: dict[str, str],
    universe: dict[str, Any],
    input_evidence: dict[str, Any],
    descriptors: pd.DataFrame,
    peaks: pd.DataFrame,
    events: pd.DataFrame,
    statuses: pd.DataFrame,
    corporate: pd.DataFrame,
    scorecard: pd.DataFrame,
) -> str:
    exchange_text = ", ".join(
        f"{key}: {value}" for key, value in universe["exchange_counts"].items()
    )
    prefix_text = ", ".join(f"{key}: {value}" for key, value in universe["prefix_counts"].items())
    industries = list(universe["industry_counts"].items())[:15]
    industry_text = ", ".join(f"{key}: {value}" for key, value in industries) or "UNAVAILABLE"
    hard_valid = int(descriptors["hard_valid"].sum())
    research_valid = int(descriptors["research_valid"].sum())
    first_touches = events[events["touch_number"].eq(1)]
    placebo_pairs = statuses[statuses["source"].eq("MATCHED_PLACEBO")]["level_id"].nunique()
    action_anomalies = int(corporate["review_anomaly"].sum()) if not corporate.empty else 0
    questions = [
        f"1. **Do lower concentrations behave like support?** {gates['SUPPORT_HYPOTHESIS_VALIDATES_OUT_OF_SAMPLE']}.",
        f"2. **Do upper concentrations behave like resistance?** {gates['RESISTANCE_HYPOTHESIS_VALIDATES_OUT_OF_SAMPLE']}.",
        f"3. **Do chip levels outperform matched arbitrary levels?** {gates['CHIP_LEVELS_OUTPERFORM_MATCHED_PLACEBOS']}.",
        f"4. **Do chip levels add beyond prior price support/resistance?** {gates['CHIP_ADDS_VALUE_BEYOND_PRICE_ONLY_LEVELS']}.",
        f"5. **Is there a mass/prominence dose response?** {gates['PEAK_STRENGTH_SHOWS_ECONOMIC_DOSE_RESPONSE']}.",
        f"6. **Does repeated touching show inventory-depletion decay?** {gates['REPEATED_TOUCH_DECAY_SUPPORTS_INVENTORY_INTERPRETATION']}.",
        f"7. **Does cost migration map to future structure?** {gates['COST_MIGRATION_HAS_ECONOMIC_VALIDITY']}.",
        f"8. **Does old-base destruction reduce support?** {gates['OLD_BASE_DESTRUCTION_REDUCES_FUTURE_SUPPORT']}.",
        f"9. **Does a new rolling base acquire support value?** {gates['NEW_ROLLING_BASE_ACQUIRES_SUPPORT_VALUE']}.",
        f"10. **Best seller model?** {gates['BEST_VALIDATED_SELLER_MODEL']}.",
        f"11. **Does ensemble consensus improve validity?** {gates['ENSEMBLE_CONSENSUS_IMPROVES_VALIDITY']}.",
        f"12. **Does ambiguity have interpretable economic meaning?** {gates['ENSEMBLE_AMBIGUITY_HAS_INTERPRETABLE_ECONOMIC_MEANING']}.",
        f"13. **Is the full distribution more informative than the canonical peak?** {gates['FULL_DISTRIBUTION_OUTPERFORMS_CANONICAL_PEAK']}.",
        f"14. **Are multi-peak/broad states meaningful?** {gates['MULTI_PEAK_STRUCTURE_HAS_ECONOMIC_INFORMATION']}.",
        f"15. **Is there a validated swing-horizon effect?** {gates['CHIP_INFORMATION_HAS_VALIDATED_SWING_HORIZON_EFFECT']}; all 1/3/5/10/20/40-session results remain visible in `horizon_map.csv`.",
        f"16. **Does chip modeling add beyond ordinary price/volume structure?** Price-only: {gates['CHIP_ADDS_VALUE_BEYOND_PRICE_ONLY_LEVELS']}; authoritative non-chip volume-at-price benchmark: UNAVAILABLE.",
        f"17. **Valid enough to continue strategy research?** {gates['SAFE_TO_CONTINUE_USING_V3_CHIP_FOR_RESEARCH']}; this does not authorize a production strategy.",
        f"18. **Is seller-model redesign study warranted?** {gates['SELLER_MODEL_REDESIGN_STUDY_JUSTIFIED']}.",
        f"19. **Is peak compression a likely information-loss source?** {gates['CANONICAL_PEAK_COMPRESSION_REDESIGN_STUDY_JUSTIFIED']}.",
    ]
    gate_lines = "\n".join(f"`{key}: {value}`" for key, value in gates.items())
    return f"""# V12 Chip Model Economic Validity Study

## Outcome

This is a research-only economic-validity result on the frozen 500-symbol V3 cohort. The evidence classification is **{gates["CHIP_MODEL_ECONOMIC_VALIDITY_OVERALL"]}**. No production strategy code, V3 temporal semantics, seller-model semantics, frozen chip artifact, or authoritative lifecycle ledger was modified. No full-market build was started.

The study does not use setup pass/fail, entries, exits, P&L, winner labels, profitable trades, or strategy-derived feature selection. Every primary level is frozen at an immutable opening/month-end checkpoint; all reaction windows start at T+1. Corporate actions transform the fixed level with the authoritative `(C-D)/R` coordinate before later price comparisons.

## Frozen provenance and population

- Baseline/source commit: `{input_evidence["source_commit"]}`
- Frozen root manifest SHA-256: `{input_evidence["root_manifest_sha256"]}`
- Freeze-lock SHA-256: `{input_evidence["freeze_lock_sha256"]}`
- Build source commit: `{input_evidence["manifest"]["git_head_provenance"]}`
- Peak definition: `canonical-chip-peak-v2`; temporal tracker: `temporal-chip-peak-v3`
- Seller models: `UNIFORM`, `DISPOSITION`, `ACTIVE_STICKY`; ensemble is reported separately
- Universe: {universe["symbols"]} symbols; exchanges — {exchange_text}
- Symbol prefixes — {prefix_text}
- Industry availability: {universe["industry_available_symbols"]}/{universe["symbols"]}; largest groups — {industry_text}
- Feature coverage: {universe["feature_date_min"]} through {universe["feature_date_max"]}; {universe["feature_rows"]:,} daily rows
- Checkpoint/model snapshots analyzed: {len(descriptors):,}; eligible tracked levels: {len(peaks):,}; first-touch observations: {len(first_touches):,}; placebo definitions: {placebo_pairs:,}
- Checkpoint model/ensemble state-level `hard_valid` flags: {hard_valid:,}; frozen daily-fact `hard_valid` rows: {universe["feature_hard_valid_rows"]:,}; research-valid checkpoint/model snapshots: {research_valid:,}. `hard_valid` is not weakened: the study uses the separately governed B-grade research-valid contract and preserves unknown-cost mass explicitly.
- Sampling limitation: {universe["sampling_bias"]}

## Method fixed before aggregate outcomes

The exact operational definitions and economic directions are in `preregistered_protocol.json`. Discovery ends 2020-04-30, validation covers 2020-05-01 through 2020-08-31, and holdout begins 2020-09-01. Discovery determines only quintile/shape bins. Bands never move using future observations except the required authoritative corporate-action coordinate transform.

Matched placebos keep symbol, checkpoint, side, recent volatility/trend, relative width, calendar regime, and a nearby fixed distance. From four preregistered distance shifts, the lowest modeled-mass non-overlapping band is retained only when its mass is no more than half the real band's. Price-only controls use the prior 20-session swing low/high. Old-base and ambiguity comparisons use deterministic same-symbol nearest controls on distance/volatility/trend/calendar geometry. Repeated touches remain clustered by deterministic `level_id`; checkpoint-state uncertainty is clustered by symbol.

The full-distribution descriptors are intentionally small and interpretable: weighted mean/median, p10/p90, width, known-cost fraction, mass below/above and within 5% of price, bucket HHI, normalized entropy, tracked mode count, and top-mode separation. There is no black-box feature search and no threshold optimization on validation or holdout.

Corporate-action sanity reports {len(corporate):,} metric comparisons and {action_anomalies:,} review-threshold anomalies. Exact daily full-distribution pre/post comparison is `UNAVAILABLE_WITHOUT_REPLAY`; the study does not invent it or rebuild the frozen root.

## Required questions

{chr(10).join(questions)}

## Seller-model tournament

The machine-readable `seller_model_scorecard.csv` preserves every model/test/period result rather than collapsing heterogeneous metrics into an optimized score. The best-model gate is `{gates["BEST_VALIDATED_SELLER_MODEL"]}` and the seller-model-difference gate is `{gates["SELLER_MODELS_DIFFER_ECONOMICALLY"]}`. Any `MIXED` result means period, model, representation, outcome, or power disagreed; it is not silently promoted.

## Falsification and limitations

The falsification table includes matched low-mass non-chip levels, an explicitly non-primary future-checkpoint time shift, weak-versus-strong peaks, and model-disagreement states. A separate authoritative PIT-safe non-chip volume-at-price artifact was not found in the frozen governed inputs, so that benchmark is reported `UNAVAILABLE` rather than constructed ad hoc.

Monthly checkpoints make full seller-model distributions authoritative and immutable but reduce event-definition cadence. The daily canonical fact supports action sanity and daily future outcomes; exact daily model-specific full distributions would require governed replay and are outside this no-rebuild study. Results therefore establish, weaken, or fail economic interpretations only for this frozen cohort and cadence.

## Hard gates

{gate_lines}
"""


def assert_scoped_worktree() -> None:
    output = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=REPO_ROOT,
        text=True,
    )
    allowed_prefix = "research/v12-chip-model-economic-validity/"
    outside = []
    for line in output.splitlines():
        path = line[3:].split(" -> ")[-1]
        if not path.startswith(allowed_prefix):
            outside.append(line)
    if outside:
        raise RuntimeError(f"study worktree has out-of-scope changes: {outside}")


def build_result_manifest(
    *,
    input_evidence: dict[str, Any],
    protocol_hash: str,
    thresholds_hash: str,
    universe: dict[str, Any],
    gates: dict[str, str],
    counts: dict[str, int],
) -> dict[str, Any]:
    artifacts = {}
    report_path = STUDY_DIR / "V12_CHIP_MODEL_ECONOMIC_VALIDITY_STUDY.md"
    artifact_paths = [*OUTPUT_DIR.iterdir(), report_path]
    for path in sorted(artifact_paths):
        if not path.is_file() or path.name == "result_manifest.json":
            continue
        binding: dict[str, Any] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
        if path.suffix == ".csv":
            binding["rows"] = max(sum(1 for _ in path.open("rb")) - 1, 0)
        artifacts[path.relative_to(STUDY_DIR).as_posix()] = binding
    return {
        "manifest_version": "v12-chip-model-economic-validity-result-manifest-v1",
        "study_protocol_sha256": protocol_hash,
        "frozen_discovery_thresholds_sha256": thresholds_hash,
        "source_commit": input_evidence["source_commit"],
        "frozen_input_bindings": {
            "root_manifest_sha256": input_evidence["root_manifest_sha256"],
            "freeze_lock_sha256": input_evidence["freeze_lock_sha256"],
            "daily_inventory_sha256": input_evidence["daily_inventory_sha256"],
            "daily_partition_sha256": input_evidence["daily_partition_sha256"],
            "seller_models": list(SELLER_MODEL_ORDER),
            "semantic_fingerprint": input_evidence["manifest"]["semantic_fingerprint"],
            "artifact_contract_fingerprint": input_evidence["manifest"][
                "artifact_contract_fingerprint"
            ],
            "replay_parameter_manifest_digest": input_evidence["manifest"][
                "replay_parameter_manifest_digest"
            ],
            "verified_all_parts": input_evidence["verified_all_parts"],
            "verified_part_count": input_evidence["verified_part_count"],
            "verified_part_bytes": input_evidence["verified_part_bytes"],
        },
        "universe": universe,
        "counts": counts,
        "gates": gates,
        "artifacts": artifacts,
        "prohibited_inputs_used": [],
        "volume_profile_benchmark": "UNAVAILABLE",
        "production_or_frozen_artifacts_modified": False,
    }


def run(args: argparse.Namespace) -> None:
    assert_scoped_worktree()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    protocol_hash = sha256(PROTOCOL_PATH)
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    print("verifying frozen inputs", flush=True)
    input_evidence = verify_inputs(
        args.v3_root,
        args.freeze_lock,
        args.daily_inventory,
        verify_all_parts=not args.skip_full_input_hash,
    )
    frozen_root_hash_before = sha256(args.v3_root / "manifest.json")
    lock_hash_before = sha256(args.freeze_lock)
    features = read_features(args.v3_root)
    prices = read_prices(input_evidence["daily_files"], input_evidence["symbols"])
    universe = universe_summary(input_evidence["symbols"], features, prices)

    print("extracting authoritative checkpoint distributions", flush=True)
    descriptors, peaks, migrations, base_transitions = extract_checkpoint_panel(
        v3_root=args.v3_root,
        manifest=input_evidence["manifest"],
        features=features,
        prices=prices,
        protocol=protocol,
    )
    context = price_context(prices)
    descriptors, peaks = add_price_context(descriptors, peaks, context)
    thresholds = discovery_thresholds(descriptors, peaks)
    thresholds_path = OUTPUT_DIR / "frozen_discovery_thresholds.json"
    thresholds_path.write_text(
        json.dumps(thresholds, indent=2, sort_keys=True, default=json_value) + "\n",
        encoding="utf-8",
    )
    thresholds_hash = sha256(thresholds_path)
    protocol["derived_thresholds"] = thresholds
    peaks = assign_strength_bins(peaks, thresholds)
    descriptors = add_checkpoint_outcomes(descriptors, prices)
    descriptors = classify_distribution_shapes(descriptors, thresholds)

    print("constructing T+1 future level reactions", flush=True)
    events, statuses = construct_level_events(peaks, prices, protocol)
    shifted_events, shifted_statuses = time_shifted_future_state_control(peaks, prices, protocol)
    if not shifted_events.empty:
        events = pd.concat([events, shifted_events], ignore_index=True, sort=False)
    if not shifted_statuses.empty:
        statuses = pd.concat([statuses, shifted_statuses], ignore_index=True, sort=False)

    support = primary_event_results(events, "SUPPORT", protocol)
    resistance = primary_event_results(events, "RESISTANCE", protocol)
    matched_placebo = paired_control_results(events, statuses, "MATCHED_PLACEBO", protocol)
    price_only = paired_control_results(events, statuses, "PRICE_ONLY_20_SWING", protocol)
    time_shifted = paired_control_results(events, statuses, "TIME_SHIFTED_FUTURE_STATE", protocol)
    crossing = crossing_difficulty_results(events, protocol)
    turnover = turnover_results(events, protocol)
    repeated = repeated_touch_results(events, protocol)
    horizon_map = horizon_map_results(events, protocol)
    strength = peak_strength_results(events, peaks, protocol)
    shape_outcomes = distribution_shape_results(descriptors, protocol)
    representation = full_distribution_vs_peak(events, descriptors, peaks, protocol)
    ambiguity = ambiguity_decomposition(descriptors, protocol)
    migration = migration_results(migrations, descriptors, protocol)
    old_base, old_base_status = old_base_destruction_results(base_transitions, prices, protocol)
    new_base = new_base_formation_results(events, protocol)
    corporate = corporate_action_sanity(features, prices, protocol)
    falsification = falsification_results(matched_placebo, time_shifted, strength, ambiguity)

    gates, scorecard, classifications = synthesize_gates(
        matched_placebo=matched_placebo,
        price_only=price_only,
        strength=strength,
        repeated=repeated,
        migration=migration,
        old_base=old_base,
        new_base=new_base,
        ambiguity=ambiguity,
        representation=representation,
        shapes=shape_outcomes,
        protocol=protocol,
    )

    outputs = {
        "support_event_results.csv": support,
        "resistance_event_results.csv": resistance,
        "matched_placebo_results.csv": matched_placebo,
        "crossing_difficulty.csv": crossing,
        "turnover_response.csv": turnover,
        "repeated_touch_decay.csv": repeated,
        "cost_migration_validity.csv": migration,
        "old_base_destruction.csv": old_base,
        "new_base_formation.csv": new_base,
        "seller_model_scorecard.csv": scorecard,
        "full_distribution_vs_peak.csv": representation,
        "distribution_shape_outcomes.csv": shape_outcomes,
        "ambiguity_decomposition.csv": ambiguity,
        "horizon_map.csv": horizon_map,
        "price_only_benchmark_comparison.csv": price_only,
        "corporate_action_sanity.csv": corporate,
        "falsification_tests.csv": falsification,
        "representation_classification.csv": classifications,
        "peak_strength_monotonicity.csv": strength,
        "time_shifted_control_results.csv": time_shifted,
    }
    for name, frame in outputs.items():
        write_csv(frame, OUTPUT_DIR / name)

    descriptors.to_parquet(OUTPUT_DIR / "distribution_snapshots.parquet", index=False)
    peaks.to_parquet(OUTPUT_DIR / "defined_chip_levels.parquet", index=False)
    events.to_parquet(OUTPUT_DIR / "level_event_panel.parquet", index=False)
    statuses.to_parquet(OUTPUT_DIR / "level_status_panel.parquet", index=False)
    migrations.to_parquet(OUTPUT_DIR / "migration_event_panel.parquet", index=False)
    base_transitions.to_parquet(OUTPUT_DIR / "base_transition_panel.parquet", index=False)
    old_base_status.to_parquet(OUTPUT_DIR / "old_base_status_panel.parquet", index=False)

    report = report_markdown(
        gates=gates,
        universe=universe,
        input_evidence=input_evidence,
        descriptors=descriptors,
        peaks=peaks,
        events=events,
        statuses=statuses,
        corporate=corporate,
        scorecard=scorecard,
    )
    report_path = STUDY_DIR / "V12_CHIP_MODEL_ECONOMIC_VALIDITY_STUDY.md"
    report_path.write_text(report, encoding="utf-8")

    if sha256(args.v3_root / "manifest.json") != frozen_root_hash_before:
        raise RuntimeError("frozen V3 root manifest changed during study")
    if sha256(args.freeze_lock) != lock_hash_before:
        raise RuntimeError("authoritative freeze lock changed during study")
    assert_scoped_worktree()
    counts = {
        "feature_rows": len(features),
        "descriptor_rows": len(descriptors),
        "defined_levels": len(peaks),
        "level_status_rows": len(statuses),
        "level_touch_rows": len(events),
        "migration_events": len(migrations),
        "base_transitions": len(base_transitions),
        "corporate_action_checks": len(corporate),
    }
    manifest = build_result_manifest(
        input_evidence=input_evidence,
        protocol_hash=protocol_hash,
        thresholds_hash=thresholds_hash,
        universe=universe,
        gates=gates,
        counts=counts,
    )
    (OUTPUT_DIR / "result_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=json_value) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"gates": gates, "counts": counts}, indent=2), flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v3-root", type=Path, default=DEFAULT_V3_ROOT)
    parser.add_argument("--freeze-lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--daily-inventory", type=Path, default=DEFAULT_DAILY_INVENTORY)
    parser.add_argument(
        "--skip-full-input-hash",
        action="store_true",
        help="development-only speed option; final results must not use it",
    )
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
