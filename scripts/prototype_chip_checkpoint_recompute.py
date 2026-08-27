#!/usr/bin/env python3
"""Offline monthly checkpoint + source-recompute prototype for canonical V12.

This research-only program deliberately imports the frozen production builder
without changing its schema or persistence path.  Durable prototype state is
flat NumPy SoA with explicit offsets; daily journals contain hashes and input /
corporate-action facts only, never transition vectors or full inventories.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
import platform
import resource
import struct
import sys
import tempfile
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cyq_game.chip.daily_feature_fact import (  # noqa: E402
    FACT_SCHEMA,
    _ensemble_row,
)
from cyq_game.chip.ensemble_v2 import SELLER_MODEL_ORDER  # noqa: E402
from cyq_game.chip.migration_v2 import (  # noqa: E402
    DailyMigrationEngine,
    MutableChipState,
    StableLogPriceGrid,
    _PackedWorkingLots,
    _UNKNOWN_BUCKET_ID,
    initial_unknown_snapshot,
    prepare_minute_path,
)
from cyq_game.chip.peaks import (  # noqa: E402
    EnsembleTemporalPeakTracker,
    TrackedPeak,
)
from cyq_game.chip.state_v2 import (  # noqa: E402
    ChipSnapshotV2,
    InventoryCell,
    SellerModel,
    SnapshotPhase,
    SparseChipInventory,
    TurnoverSensitivity,
    tolerance,
)
from cyq_game.strategy.semantic_contract import (  # noqa: E402
    semantic_fingerprint_fields,
)

DEFAULT_SAMPLE = ROOT / "configs/v12_checkpoint_recompute_50_symbols_v1.txt"
DEFAULT_STAGE = ROOT / "data/validation/v12_rc1_2020_stage"
DEFAULT_ORACLE = ROOT / "data/validation/v12_rc1_2020_output"
DEFAULT_OUTPUT = ROOT / "data/validation/v12_checkpoint_recompute_50_v1"
DAY_EPOCH = date(1970, 1, 1)
TIME_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
MODEL_INDEX = {model: index for index, model in enumerate(SELLER_MODEL_ORDER)}
SENSITIVITY_INDEX = {
    TurnoverSensitivity.ACTIVE: 0,
    TurnoverSensitivity.NEUTRAL: 1,
    TurnoverSensitivity.STICKY: 2,
}
INDEX_SENSITIVITY = tuple(SENSITIVITY_INDEX)
TRACKER_MODELS = ("uniform", "disposition", "active_sticky")
TRACKER_SCOPES = (*TRACKER_MODELS, "ENSEMBLE")
NULL_BUCKET = np.iinfo(np.int64).min
HASH_BYTES = 32
PROTOTYPE_VERSION = "monthly-checkpoint-recompute-v2"
RESULT_CACHE_NAME = "benchmark_result.json"
LEGACY_DAILY_CHECKPOINT_COLUMNS = frozenset(
    {"checkpoint_local_ids", "checkpoint_shares", "checkpoint_economic_bucket_ids"}
)


def _load_builder() -> Any:
    path = ROOT / "scripts/build_real_chip_year.py"
    spec = importlib.util.spec_from_file_location("cy_v12_frozen_builder", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import frozen builder: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BUILD = _load_builder()
ORACLE_OUTPUT_SCHEMA = pa.schema(
    field for field in BUILD.OUTPUT_SCHEMA if field.name not in LEGACY_DAILY_CHECKPOINT_COLUMNS
)


def _f64_bits(value: float | None) -> int:
    if value is None:
        return 0
    return struct.unpack("<Q", struct.pack("<d", float(value)))[0]


def _bits_f64(value: int) -> float:
    return struct.unpack("<d", struct.pack("<Q", int(value)))[0]


def _day_code(value: date) -> int:
    return (value - DAY_EPOCH).days


def _code_day(value: int) -> date:
    return DAY_EPOCH + timedelta(days=int(value))


def _time_code(value: datetime) -> int:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("checkpoint timestamp must be timezone-aware")
    delta = value.astimezone(timezone.utc) - TIME_EPOCH
    return delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds


def _code_time(value: int) -> datetime:
    return (TIME_EPOCH + timedelta(microseconds=int(value))).astimezone(BUILD.TZ)


class _StringPool:
    def __init__(self) -> None:
        self.values: list[str] = []
        self.index: dict[str, int] = {}

    def add(self, value: str | None) -> int:
        if value is None:
            return -1
        text = str(value)
        existing = self.index.get(text)
        if existing is not None:
            return existing
        result = len(self.values)
        self.index[text] = result
        self.values.append(text)
        return result

    def arrays(self) -> tuple[np.ndarray[Any, np.dtype[np.uint8]], np.ndarray[Any, np.dtype[np.uint64]]]:
        encoded = [value.encode("utf-8") for value in self.values]
        offsets = np.zeros(len(encoded) + 1, dtype=np.uint64)
        for index, value in enumerate(encoded):
            offsets[index + 1] = offsets[index] + len(value)
        payload = np.frombuffer(b"".join(encoded), dtype=np.uint8).copy()
        return payload, offsets


def _pool_value(data: Mapping[str, np.ndarray[Any, Any]], ref: int) -> str | None:
    if int(ref) < 0:
        return None
    offsets = data["string_offsets"]
    start, stop = int(offsets[int(ref)]), int(offsets[int(ref) + 1])
    return bytes(data["string_bytes"][start:stop]).decode("utf-8")


def _update_hash(hasher: Any, value: Any) -> None:
    if value is None:
        hasher.update(b"N")
    elif isinstance(value, (bool, np.bool_)):
        hasher.update(b"B\x01" if bool(value) else b"B\x00")
    elif isinstance(value, (int, np.integer)):
        payload = str(int(value)).encode("ascii")
        hasher.update(b"I" + len(payload).to_bytes(4, "little") + payload)
    elif isinstance(value, (float, np.floating)):
        hasher.update(b"F" + struct.pack("<d", float(value)))
    elif isinstance(value, str):
        payload = value.encode("utf-8")
        hasher.update(b"S" + len(payload).to_bytes(8, "little") + payload)
    elif isinstance(value, bytes):
        hasher.update(b"Y" + len(value).to_bytes(8, "little") + value)
    elif isinstance(value, date) and not isinstance(value, datetime):
        hasher.update(b"D" + struct.pack("<i", _day_code(value)))
    elif isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            payload = value.isoformat(timespec="microseconds").encode("ascii")
            hasher.update(b"t" + len(payload).to_bytes(4, "little") + payload)
        else:
            hasher.update(b"T" + struct.pack("<q", _time_code(value)))
    elif is_dataclass(value):
        hasher.update(b"C")
        for field in fields(value):
            _update_hash(hasher, field.name)
            _update_hash(hasher, getattr(value, field.name))
    elif isinstance(value, Mapping):
        hasher.update(b"M" + len(value).to_bytes(8, "little"))
        for key in sorted(value, key=lambda item: str(item)):
            _update_hash(hasher, key)
            _update_hash(hasher, value[key])
    elif isinstance(value, (tuple, list)):
        hasher.update(b"L" + len(value).to_bytes(8, "little"))
        for item in value:
            _update_hash(hasher, item)
    elif isinstance(value, np.ndarray):
        array = np.ascontiguousarray(value)
        _update_hash(hasher, array.dtype.str)
        _update_hash(hasher, tuple(array.shape))
        _update_hash(hasher, array.tobytes())
    else:
        raise TypeError(f"unsupported digest value: {type(value)!r}")


def _digest(value: Any) -> bytes:
    hasher = hashlib.sha256()
    _update_hash(hasher, value)
    return hasher.digest()


def _hash_matrix(values: Sequence[bytes]) -> np.ndarray[Any, np.dtype[np.uint8]]:
    if any(len(value) != HASH_BYTES for value in values):
        raise ValueError("digest column contains a non-SHA256 value")
    if not values:
        return np.empty((0, HASH_BYTES), dtype=np.uint8)
    return np.frombuffer(b"".join(values), dtype=np.uint8).reshape(-1, HASH_BYTES).copy()


def _snapshot_digest(snapshot: ChipSnapshotV2) -> bytes:
    cells = tuple(
        (
            cell.cost_bucket_id,
            cell.holding_days,
            cell.sensitivity.value,
            cell.acquisition_cost,
            cell.economic_break_even,
            cell.shares,
            cell.initialization_prior_units,
        )
        for cell in snapshot.inventory.cells
    )
    return _digest(
        (
            snapshot.symbol,
            snapshot.trading_date,
            snapshot.decision_at,
            snapshot.effective_at,
            snapshot.available_at,
            snapshot.phase.value,
            snapshot.snapshot_id,
            snapshot.model_version,
            snapshot.grid_version,
            snapshot.seller_model.value,
            snapshot.free_float_shares,
            snapshot.latent_supply_shares,
            snapshot.input_snapshot_ids,
            snapshot.pit_grade,
            snapshot.hard_valid,
            snapshot.quality_reason_codes,
            cells,
        )
    )


def _continuation_digest(state: ChipSnapshotV2 | MutableChipState) -> bytes:
    """Commit the exact engine continuation, including physical lot order."""

    packed = state.packed_lots if isinstance(state, MutableChipState) else None
    return _digest(
        (
            state.symbol,
            state.trading_date,
            state.decision_at,
            state.effective_at,
            state.available_at,
            state.snapshot_id,
            state.model_version,
            state.grid_version,
            state.seller_model.value,
            state.free_float_shares,
            state.latent_supply_shares,
            state.input_snapshot_ids,
            state.pit_grade,
            state.hard_valid,
            state.quality_reason_codes,
            state.conservation_error,
            True if packed is None else packed._cell_ids_current,
            tuple(_state_lots(state)),
        )
    )


def _inventory_identity_digest(snapshot: ChipSnapshotV2) -> bytes:
    return _digest(
        tuple(
            (
                cell.cost_bucket_id,
                cell.holding_days,
                cell.sensitivity.value,
                cell.economic_break_even,
            )
            for cell in snapshot.inventory.cells
        )
    )


def _inventory_share_digest(snapshot: ChipSnapshotV2) -> bytes:
    return _digest(tuple(cell.shares for cell in snapshot.inventory.cells))


def _transition_digest(transition: Any) -> bytes:
    return _digest(
        (
            transition.transition_id,
            tuple(int(value) for value in transition.source_cell_ids),
            tuple(int(value) for value in transition.destination_cell_ids),
            tuple(float(value) for value in transition.retained_fractions),
            float(transition.fixed_pre_eligible_shares),
            float(transition.executed_sell_shares),
            float(transition.same_day_resale_shares),
        )
    )


def _feature_digest(row: Mapping[str, Any]) -> bytes:
    return _digest(tuple(row[name] for name in FACT_SCHEMA.names))


def _arrow_row_digest(row: Mapping[str, Any], schema: pa.Schema) -> bytes:
    """Canonical bit-level digest for one typed Arrow row."""

    table = pa.Table.from_pylist([dict(row)], schema=schema).combine_chunks()
    batches = table.to_batches(max_chunksize=1)
    if len(batches) != 1:
        raise ValueError("expected exactly one Arrow record batch")
    hasher = hashlib.sha256()
    hasher.update(schema.serialize().to_pybytes())
    hasher.update(batches[0].serialize().to_pybytes())
    return hasher.digest()


def _runtime_hash() -> bytes:
    sources = (
        ROOT / "scripts/build_real_chip_year.py",
        ROOT / "src/cyq_game/chip/migration_v2.py",
        ROOT / "src/cyq_game/chip/_migration_kernel.py",
        ROOT / "src/cyq_game/chip/daily_feature_fact.py",
    )
    return _digest(
        (
            semantic_fingerprint_fields(),
            tuple((str(path.relative_to(ROOT)), hashlib.sha256(path.read_bytes()).digest()) for path in sources),
            sys.version,
            platform.platform(),
            np.__version__,
            pa.__version__,
        )
    )


def _tracker_parts(tracker: EnsembleTemporalPeakTracker) -> tuple[Any, ...]:
    result: list[Any] = []
    scoped = {**tracker._local, "ENSEMBLE": tracker._ensemble}
    for scope in TRACKER_SCOPES:
        item = scoped[scope]
        result.append(
            (
                scope,
                item._base_track_id,
                tuple(sorted(item._applied_action_ids)),
                tuple(item._previous),
            )
        )
    return tuple(result)


def _tracker_digest(tracker: EnsembleTemporalPeakTracker) -> bytes:
    return _digest(_tracker_parts(tracker))


def _tracker_arrays(
    tracker: EnsembleTemporalPeakTracker, pool: _StringPool
) -> dict[str, np.ndarray[Any, Any]]:
    base_refs: list[int] = []
    action_offsets = [0]
    action_refs: list[int] = []
    peak_offsets = [0]
    peak_id_refs: list[int] = []
    peak_ages: list[int] = []
    peak_band_lower_bits: list[int] = []
    peak_band_upper_bits: list[int] = []
    peak_center_bits: list[int] = []
    peak_mass_bits: list[int] = []
    peak_prominence_bits: list[int] = []
    peak_flags: list[int] = []
    peak_definition_refs: list[int] = []
    peak_version_refs: list[int] = []
    scoped = {**tracker._local, "ENSEMBLE": tracker._ensemble}
    for scope in TRACKER_SCOPES:
        item = scoped[scope]
        base_refs.append(pool.add(item._base_track_id))
        action_refs.extend(pool.add(value) for value in sorted(item._applied_action_ids))
        action_offsets.append(len(action_refs))
        for peak in item._previous:
            peak_id_refs.append(pool.add(peak.peak_track_id))
            peak_ages.append(peak.age)
            peak_band_lower_bits.append(_f64_bits(peak.band[0]))
            peak_band_upper_bits.append(_f64_bits(peak.band[1]))
            peak_center_bits.append(_f64_bits(peak.center_price))
            peak_mass_bits.append(_f64_bits(peak.mass))
            peak_prominence_bits.append(_f64_bits(peak.prominence))
            peak_flags.append(
                int(peak.ambiguity)
                | int(peak.split) << 1
                | int(peak.merge) << 2
                | int(peak.lost) << 3
            )
            peak_definition_refs.append(pool.add(peak.definition_version))
            peak_version_refs.append(pool.add(peak.track_version))
        peak_offsets.append(len(peak_id_refs))
    return {
        "tracker_base_refs": np.asarray(base_refs, dtype=np.int32),
        "tracker_action_offsets": np.asarray(action_offsets, dtype=np.uint64),
        "tracker_action_refs": np.asarray(action_refs, dtype=np.int32),
        "tracker_peak_offsets": np.asarray(peak_offsets, dtype=np.uint64),
        "tracker_peak_id_refs": np.asarray(peak_id_refs, dtype=np.int32),
        "tracker_peak_ages": np.asarray(peak_ages, dtype=np.int32),
        "tracker_peak_band_lower_bits": np.asarray(peak_band_lower_bits, dtype=np.uint64),
        "tracker_peak_band_upper_bits": np.asarray(peak_band_upper_bits, dtype=np.uint64),
        "tracker_peak_center_bits": np.asarray(peak_center_bits, dtype=np.uint64),
        "tracker_peak_mass_bits": np.asarray(peak_mass_bits, dtype=np.uint64),
        "tracker_peak_prominence_bits": np.asarray(peak_prominence_bits, dtype=np.uint64),
        "tracker_peak_flags": np.asarray(peak_flags, dtype=np.uint8),
        "tracker_peak_definition_refs": np.asarray(peak_definition_refs, dtype=np.int32),
        "tracker_peak_version_refs": np.asarray(peak_version_refs, dtype=np.int32),
    }


def _restore_tracker(data: Mapping[str, np.ndarray[Any, Any]], symbol: str) -> EnsembleTemporalPeakTracker:
    tracker = EnsembleTemporalPeakTracker(symbol=symbol, models=TRACKER_MODELS)
    scoped = {**tracker._local, "ENSEMBLE": tracker._ensemble}
    for scope_index, scope in enumerate(TRACKER_SCOPES):
        item = scoped[scope]
        item._base_track_id = _pool_value(data, int(data["tracker_base_refs"][scope_index]))
        action_start = int(data["tracker_action_offsets"][scope_index])
        action_stop = int(data["tracker_action_offsets"][scope_index + 1])
        item._applied_action_ids = {
            str(_pool_value(data, int(ref)))
            for ref in data["tracker_action_refs"][action_start:action_stop]
        }
        peak_start = int(data["tracker_peak_offsets"][scope_index])
        peak_stop = int(data["tracker_peak_offsets"][scope_index + 1])
        peaks: list[TrackedPeak] = []
        for index in range(peak_start, peak_stop):
            flags = int(data["tracker_peak_flags"][index])
            peaks.append(
                TrackedPeak(
                    peak_track_id=str(_pool_value(data, int(data["tracker_peak_id_refs"][index]))),
                    age=int(data["tracker_peak_ages"][index]),
                    band=(
                        _bits_f64(int(data["tracker_peak_band_lower_bits"][index])),
                        _bits_f64(int(data["tracker_peak_band_upper_bits"][index])),
                    ),
                    center_price=_bits_f64(int(data["tracker_peak_center_bits"][index])),
                    mass=_bits_f64(int(data["tracker_peak_mass_bits"][index])),
                    prominence=_bits_f64(int(data["tracker_peak_prominence_bits"][index])),
                    ambiguity=bool(flags & 1),
                    split=bool(flags & 2),
                    merge=bool(flags & 4),
                    lost=bool(flags & 8),
                    definition_version=str(
                        _pool_value(data, int(data["tracker_peak_definition_refs"][index]))
                    ),
                    track_version=str(
                        _pool_value(data, int(data["tracker_peak_version_refs"][index]))
                    ),
                )
            )
        item._previous = tuple(peaks)
    return tracker


@dataclass(frozen=True)
class Checkpoint:
    label: str
    snapshots: Mapping[SellerModel, ChipSnapshotV2 | MutableChipState]
    tracker: EnsembleTemporalPeakTracker


def _identity_key(cell: InventoryCell) -> tuple[int, int, int, int, int]:
    return (
        NULL_BUCKET if cell.cost_bucket_id is None else int(cell.cost_bucket_id),
        int(cell.holding_days),
        SENSITIVITY_INDEX[cell.sensitivity],
        int(cell.economic_break_even is not None),
        _f64_bits(cell.economic_break_even),
    )


def _state_lots(
    state: ChipSnapshotV2 | MutableChipState,
) -> list[tuple[tuple[int, int, int, int, int], float | None, float, float]]:
    """Return exact physical continuation lots in their engine order."""

    packed = state.packed_lots if isinstance(state, MutableChipState) else None
    if packed is None:
        return [
            (
                _identity_key(cell),
                cell.acquisition_cost,
                cell.shares,
                cell.initialization_prior_units,
            )
            for cell in state.inventory.cells
        ]
    result: list[tuple[tuple[int, int, int, int, int], float | None, float, float]] = []
    for index in range(len(packed)):
        bucket = int(packed.cost_bucket_ids[index])
        known = bucket != _UNKNOWN_BUCKET_ID
        result.append(
            (
                (
                    NULL_BUCKET if not known else bucket,
                    int(packed.holding_days[index]),
                    int(packed.sensitivity_codes[index]),
                    int(known),
                    _f64_bits(float(packed.economic_break_evens[index])) if known else 0,
                ),
                float(packed.acquisition_costs[index]) if known else None,
                float(packed.shares[index]),
                float(packed.initialization_prior_units[index]),
            )
        )
    return result


def _checkpoint_arrays(checkpoint: Checkpoint, *, union: bool) -> tuple[dict[str, np.ndarray[Any, Any]], dict[str, int]]:
    pool = _StringPool()
    snapshots = [checkpoint.snapshots[model] for model in SELLER_MODEL_ORDER]
    if not all(snapshot.symbol == snapshots[0].symbol for snapshot in snapshots):
        raise ValueError("checkpoint seller models have different symbols")
    if not all(snapshot.trading_date == snapshots[0].trading_date for snapshot in snapshots):
        raise ValueError("checkpoint seller models have different dates")

    lots_by_model = [_state_lots(state) for state in snapshots]
    unique_by_model = [sorted({lot[0] for lot in lots}) for lots in lots_by_model]
    identity_rows: list[tuple[int, int, int, int, int]] = []
    identity_model: list[int] = []
    if union:
        identity_rows = sorted({key for keys in unique_by_model for key in keys})
        positions: dict[Any, int] = {key: index for index, key in enumerate(identity_rows)}
    else:
        positions = {}
        for model_index, keys in enumerate(unique_by_model):
            for key in keys:
                positions[(model_index, key)] = len(identity_rows)
                identity_rows.append(key)
                identity_model.append(model_index)

    lot_offsets = [0]
    lot_identity_positions: list[int] = []
    lot_share_bits: list[int] = []
    lot_acquisition_bits: list[int] = []
    lot_prior_bits: list[int] = []
    for model_index, lots in enumerate(lots_by_model):
        for identity, acquisition, shares, prior in lots:
            lot_identity_positions.append(
                positions[identity] if union else positions[(model_index, identity)]
            )
            lot_share_bits.append(_f64_bits(shares))
            lot_acquisition_bits.append(_f64_bits(acquisition))
            lot_prior_bits.append(_f64_bits(prior))
        lot_offsets.append(len(lot_identity_positions))

    input_offsets = [0]
    input_refs: list[int] = []
    quality_offsets = [0]
    quality_refs: list[int] = []
    snapshot_refs: list[int] = []
    model_version_refs: list[int] = []
    grid_version_refs: list[int] = []
    pit_refs: list[int] = []
    for snapshot in snapshots:
        snapshot_refs.append(pool.add(snapshot.snapshot_id))
        model_version_refs.append(pool.add(snapshot.model_version))
        grid_version_refs.append(pool.add(snapshot.grid_version))
        pit_refs.append(pool.add(snapshot.pit_grade))
        input_refs.extend(pool.add(value) for value in snapshot.input_snapshot_ids)
        input_offsets.append(len(input_refs))
        quality_refs.extend(pool.add(value) for value in snapshot.quality_reason_codes)
        quality_offsets.append(len(quality_refs))

    arrays: dict[str, np.ndarray[Any, Any]] = {
        "format_version": np.asarray([1], dtype=np.uint16),
        "union_identity": np.asarray([int(union)], dtype=np.uint8),
        "checkpoint_date": np.asarray([_day_code(snapshots[0].trading_date)], dtype=np.int32),
        "symbol_ref": np.asarray([pool.add(snapshots[0].symbol)], dtype=np.int32),
        "identity_cost_bucket": np.asarray([row[0] for row in identity_rows], dtype=np.int64),
        "identity_holding_days": np.asarray([row[1] for row in identity_rows], dtype=np.int16),
        "identity_sensitivity": np.asarray([row[2] for row in identity_rows], dtype=np.uint8),
        "identity_economic_valid": np.asarray([row[3] for row in identity_rows], dtype=np.uint8),
        "identity_economic_bits": np.asarray([row[4] for row in identity_rows], dtype=np.uint64),
        "identity_model": np.asarray(identity_model, dtype=np.int8),
        "model_lot_offsets": np.asarray(lot_offsets, dtype=np.uint64),
        "lot_identity_positions": np.asarray(lot_identity_positions, dtype=np.uint64),
        "lot_share_bits": np.asarray(lot_share_bits, dtype=np.uint64),
        "lot_acquisition_bits": np.asarray(lot_acquisition_bits, dtype=np.uint64),
        "lot_prior_units_bits": np.asarray(lot_prior_bits, dtype=np.uint64),
        "model_decision_us": np.asarray([_time_code(item.decision_at) for item in snapshots], dtype=np.int64),
        "model_effective_us": np.asarray([_time_code(item.effective_at) for item in snapshots], dtype=np.int64),
        "model_available_us": np.asarray([_time_code(item.available_at) for item in snapshots], dtype=np.int64),
        "model_snapshot_refs": np.asarray(snapshot_refs, dtype=np.int32),
        "model_version_refs": np.asarray(model_version_refs, dtype=np.int32),
        "model_grid_refs": np.asarray(grid_version_refs, dtype=np.int32),
        "model_free_float_bits": np.asarray([_f64_bits(item.free_float_shares) for item in snapshots], dtype=np.uint64),
        "model_latent_supply_bits": np.asarray([_f64_bits(item.latent_supply_shares) for item in snapshots], dtype=np.uint64),
        "model_conservation_error_bits": np.asarray(
            [_f64_bits(item.conservation_error) for item in snapshots], dtype=np.uint64
        ),
        "model_cell_ids_current": np.asarray(
            [
                1
                if not isinstance(item, MutableChipState) or item.packed_lots is None
                else int(item.packed_lots._cell_ids_current)
                for item in snapshots
            ],
            dtype=np.uint8,
        ),
        "model_pit_refs": np.asarray(pit_refs, dtype=np.int32),
        "model_hard_valid": np.asarray([item.hard_valid for item in snapshots], dtype=np.uint8),
        "model_input_offsets": np.asarray(input_offsets, dtype=np.uint64),
        "model_input_refs": np.asarray(input_refs, dtype=np.int32),
        "model_quality_offsets": np.asarray(quality_offsets, dtype=np.uint64),
        "model_quality_refs": np.asarray(quality_refs, dtype=np.int32),
    }
    arrays.update(_tracker_arrays(checkpoint.tracker, pool))
    arrays["string_bytes"], arrays["string_offsets"] = pool.arrays()
    counts = {
        "union_identities": len({key for keys in unique_by_model for key in keys}),
        "independent_identities": sum(len(keys) for keys in unique_by_model),
    }
    return arrays, counts


def _atomic_savez(path: Path, arrays: Mapping[str, np.ndarray[Any, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        np.savez_compressed(handle, **arrays)
    temporary.replace(path)


def write_checkpoint(
    path: Path,
    checkpoint: Checkpoint,
    *,
    measure_separate_models: bool = True,
) -> dict[str, int]:
    arrays, counts = _checkpoint_arrays(checkpoint, union=True)
    _atomic_savez(path, arrays)
    separate_bytes = path.stat().st_size
    if measure_separate_models:
        with tempfile.TemporaryDirectory(prefix="cy-checkpoint-counterfactual-") as directory:
            counterfactual = Path(directory) / path.name
            separate_arrays, _ = _checkpoint_arrays(checkpoint, union=False)
            _atomic_savez(counterfactual, separate_arrays)
            separate_bytes = counterfactual.stat().st_size
    return {
        **counts,
        "shared_bytes": path.stat().st_size,
        "separate_bytes": separate_bytes,
        "actual_saved_bytes": separate_bytes - path.stat().st_size,
    }


def _load_npz(path: Path) -> dict[str, np.ndarray[Any, Any]]:
    with np.load(path, allow_pickle=False) as archive:
        return {name: archive[name] for name in archive.files}


def load_checkpoint(
    path: Path,
) -> tuple[
    dict[SellerModel, ChipSnapshotV2 | MutableChipState],
    EnsembleTemporalPeakTracker,
]:
    data = _load_npz(path)
    if int(data["format_version"][0]) != 1 or int(data["union_identity"][0]) != 1:
        raise ValueError("unsupported or non-union checkpoint")
    symbol = str(_pool_value(data, int(data["symbol_ref"][0])))
    trading_date = _code_day(int(data["checkpoint_date"][0]))
    snapshots: dict[SellerModel, ChipSnapshotV2 | MutableChipState] = {}
    for model_index, model in enumerate(SELLER_MODEL_ORDER):
        lot_start = int(data["model_lot_offsets"][model_index])
        lot_stop = int(data["model_lot_offsets"][model_index + 1])
        identity_positions = data["lot_identity_positions"][lot_start:lot_stop].astype(np.int64)
        raw_buckets = data["identity_cost_bucket"][identity_positions].astype(np.int64)
        known = data["identity_economic_valid"][identity_positions].astype(bool)
        packed = _PackedWorkingLots(
            cell_ids=np.zeros(lot_stop - lot_start, dtype=np.int64),
            cost_bucket_ids=np.where(known, raw_buckets, _UNKNOWN_BUCKET_ID).astype(np.int64),
            holding_days=data["identity_holding_days"][identity_positions].astype(np.int16),
            sensitivity_codes=data["identity_sensitivity"][identity_positions].astype(np.int8),
            acquisition_costs=np.asarray(
                [
                    _bits_f64(int(value)) if valid else np.nan
                    for value, valid in zip(
                        data["lot_acquisition_bits"][lot_start:lot_stop], known, strict=True
                    )
                ],
                dtype=np.float64,
            ),
            economic_break_evens=np.asarray(
                [
                    _bits_f64(int(data["identity_economic_bits"][position]))
                    if valid
                    else np.nan
                    for position, valid in zip(identity_positions, known, strict=True)
                ],
                dtype=np.float64,
            ),
            shares=np.asarray(
                [_bits_f64(int(value)) for value in data["lot_share_bits"][lot_start:lot_stop]],
                dtype=np.float64,
            ),
            initialization_prior_units=np.asarray(
                [_bits_f64(int(value)) for value in data["lot_prior_units_bits"][lot_start:lot_stop]],
                dtype=np.float64,
            ),
        )
        packed._cell_ids_current = False
        packed.refresh_cell_ids()
        packed._cell_ids_current = bool(data["model_cell_ids_current"][model_index])
        input_start, input_stop = (
            int(data["model_input_offsets"][model_index]),
            int(data["model_input_offsets"][model_index + 1]),
        )
        quality_start, quality_stop = (
            int(data["model_quality_offsets"][model_index]),
            int(data["model_quality_offsets"][model_index + 1]),
        )
        snapshots[model] = MutableChipState(
            symbol=symbol,
            trading_date=trading_date,
            decision_at=_code_time(int(data["model_decision_us"][model_index])),
            effective_at=_code_time(int(data["model_effective_us"][model_index])),
            available_at=_code_time(int(data["model_available_us"][model_index])),
            snapshot_id=str(_pool_value(data, int(data["model_snapshot_refs"][model_index]))),
            model_version=str(_pool_value(data, int(data["model_version_refs"][model_index]))),
            grid_version=str(_pool_value(data, int(data["model_grid_refs"][model_index]))),
            seller_model=model,
            lots=packed,
            free_float_shares=_bits_f64(int(data["model_free_float_bits"][model_index])),
            latent_supply_shares=_bits_f64(int(data["model_latent_supply_bits"][model_index])),
            input_snapshot_ids=tuple(
                str(_pool_value(data, int(ref)))
                for ref in data["model_input_refs"][input_start:input_stop]
            ),
            hard_valid=bool(data["model_hard_valid"][model_index]),
            quality_reason_codes=tuple(
                str(_pool_value(data, int(ref)))
                for ref in data["model_quality_refs"][quality_start:quality_stop]
            ),
            last_transition=None,
            _conservation_error=_bits_f64(
                int(data["model_conservation_error_bits"][model_index])
            ),
        )
    return snapshots, _restore_tracker(data, symbol)


def _raw_input_digest(row: Mapping[str, Any], minute_rows: Sequence[Mapping[str, Any]]) -> bytes:
    daily_fields = tuple(sorted((str(key), value) for key, value in row.items()))
    ordered_minutes = sorted(
        minute_rows,
        key=lambda item: BUILD._timestamp(item["bar_end_time"]),
    )
    minute_fields = tuple(
        tuple(
            (name, minute.get(name))
            for name in (
                "bar_end_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "minute_source",
            )
        )
        for minute in ordered_minutes
    )
    return _digest((daily_fields, minute_fields))


def _input_references(row: Mapping[str, Any], minute_rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    minute_digest = _digest(
        tuple(
            tuple(
                minute.get(name)
                for name in ("bar_end_time", "open", "high", "low", "close", "volume", "amount", "minute_source")
            )
            for minute in sorted(minute_rows, key=lambda item: BUILD._timestamp(item["bar_end_time"]))
        )
    ).hex()
    return (*BUILD._snapshot_ids(dict(row)), f"minute-day-sha256:{minute_digest}")


@dataclass
class DayEvidence:
    trading_date: date
    input_digest: bytes
    input_refs: tuple[str, ...]
    action_refs: tuple[str, ...]
    cash_bits: int
    multiplier_bits: int
    circulating_bits: int
    model_hashes: tuple[bytes, bytes, bytes]
    transition_hashes: tuple[bytes, bytes, bytes]
    runtime_hashes: tuple[bytes, bytes, bytes]
    operator_digests: tuple[bytes, bytes, bytes]
    post_digests: tuple[bytes, bytes, bytes]
    identity_digests: tuple[bytes, bytes, bytes]
    share_digests: tuple[bytes, bytes, bytes]
    feature_digest: bytes
    snapshot_ids: tuple[str, str, str]
    transition_ids: tuple[str, str, str]
    oracle_row_digests: tuple[bytes, ...] = ()


def write_journal(path: Path, evidence: Sequence[DayEvidence]) -> int:
    pool = _StringPool()
    input_offsets = [0]
    input_refs: list[int] = []
    action_offsets = [0]
    action_refs: list[int] = []
    snapshot_refs: list[int] = []
    transition_refs: list[int] = []
    for day in evidence:
        input_refs.extend(pool.add(value) for value in day.input_refs)
        input_offsets.append(len(input_refs))
        action_refs.extend(pool.add(value) for value in day.action_refs)
        action_offsets.append(len(action_refs))
        snapshot_refs.extend(pool.add(value) for value in day.snapshot_ids)
        transition_refs.extend(pool.add(value) for value in day.transition_ids)
    arrays: dict[str, np.ndarray[Any, Any]] = {
        "format_version": np.asarray([1], dtype=np.uint16),
        "day_dates": np.asarray([_day_code(day.trading_date) for day in evidence], dtype=np.int32),
        "day_input_digest": _hash_matrix([day.input_digest for day in evidence]),
        "day_input_offsets": np.asarray(input_offsets, dtype=np.uint64),
        "day_input_refs": np.asarray(input_refs, dtype=np.int32),
        "day_action_offsets": np.asarray(action_offsets, dtype=np.uint64),
        "day_action_refs": np.asarray(action_refs, dtype=np.int32),
        "day_cash_bits": np.asarray([day.cash_bits for day in evidence], dtype=np.uint64),
        "day_multiplier_bits": np.asarray([day.multiplier_bits for day in evidence], dtype=np.uint64),
        "day_circulating_bits": np.asarray([day.circulating_bits for day in evidence], dtype=np.uint64),
        "day_feature_digest": _hash_matrix([day.feature_digest for day in evidence]),
        "model_offsets": np.arange(0, len(evidence) * 3 + 1, 3, dtype=np.uint64),
        "model_code": np.tile(np.arange(3, dtype=np.uint8), len(evidence)),
        "model_hash": _hash_matrix([value for day in evidence for value in day.model_hashes]),
        "model_transition_hash": _hash_matrix([value for day in evidence for value in day.transition_hashes]),
        "model_runtime_hash": _hash_matrix([value for day in evidence for value in day.runtime_hashes]),
        "model_operator_digest": _hash_matrix([value for day in evidence for value in day.operator_digests]),
        "model_post_digest": _hash_matrix([value for day in evidence for value in day.post_digests]),
        "model_snapshot_refs": np.asarray(snapshot_refs, dtype=np.int32),
        "model_transition_refs": np.asarray(transition_refs, dtype=np.int32),
    }
    arrays["string_bytes"], arrays["string_offsets"] = pool.arrays()
    _atomic_savez(path, arrays)
    return path.stat().st_size


def load_journal(path: Path) -> dict[date, dict[str, Any]]:
    data = _load_npz(path)
    result: dict[date, dict[str, Any]] = {}
    for day_index, raw_date in enumerate(data["day_dates"]):
        start, stop = int(data["model_offsets"][day_index]), int(data["model_offsets"][day_index + 1])
        input_start, input_stop = int(data["day_input_offsets"][day_index]), int(data["day_input_offsets"][day_index + 1])
        action_start, action_stop = int(data["day_action_offsets"][day_index]), int(data["day_action_offsets"][day_index + 1])
        result[_code_day(int(raw_date))] = {
            "input_digest": bytes(data["day_input_digest"][day_index]),
            "input_refs": tuple(str(_pool_value(data, int(ref))) for ref in data["day_input_refs"][input_start:input_stop]),
            "action_refs": tuple(str(_pool_value(data, int(ref))) for ref in data["day_action_refs"][action_start:action_stop]),
            "cash_bits": int(data["day_cash_bits"][day_index]),
            "multiplier_bits": int(data["day_multiplier_bits"][day_index]),
            "circulating_bits": int(data["day_circulating_bits"][day_index]),
            "feature_digest": bytes(data["day_feature_digest"][day_index]),
            "model_hashes": tuple(bytes(value) for value in data["model_hash"][start:stop]),
            "transition_hashes": tuple(bytes(value) for value in data["model_transition_hash"][start:stop]),
            "runtime_hashes": tuple(bytes(value) for value in data["model_runtime_hash"][start:stop]),
            "operator_digests": tuple(bytes(value) for value in data["model_operator_digest"][start:stop]),
            "post_digests": tuple(bytes(value) for value in data["model_post_digest"][start:stop]),
            "snapshot_ids": tuple(str(_pool_value(data, int(ref))) for ref in data["model_snapshot_refs"][start:stop]),
            "transition_ids": tuple(str(_pool_value(data, int(ref))) for ref in data["model_transition_refs"][start:stop]),
        }
    return result


def _prepare_day(
    current: Mapping[SellerModel, ChipSnapshotV2 | MutableChipState],
    row: Mapping[str, Any],
    raw_minutes: Sequence[Mapping[str, Any]],
    grid: StableLogPriceGrid,
) -> tuple[Any, float, tuple[str, ...], bool, tuple[str, ...]]:
    trading_date = BUILD._date(row["trade_date"])
    input_hard_valid = bool(row.get("hard_valid", False))
    raw_free_float = row.get("circulating_shares")
    missing_free_float = raw_free_float is None or float(raw_free_float) <= 0
    if missing_free_float and input_hard_valid:
        raise ValueError("hard-valid daily row has no positive circulating share count")
    bars = [] if missing_free_float else BUILD._minute_bars(list(raw_minutes), trading_date)
    fallback = False
    if not missing_free_float and not bars and float(row.get("volume") or 0.0) > 0:
        bars = BUILD._daily_fallback_bar(dict(row))
        fallback = True
    decision_at = BUILD._aware(trading_date, 15)
    prepared = prepare_minute_path(grid=grid, decision_at=decision_at, minute_bars=bars)
    expected_float = (
        next(iter(current.values())).free_float_shares
        if missing_free_float
        else float(raw_free_float)
    )
    reasons: list[str] = []
    if missing_free_float:
        reasons.append("MISSING_FLOAT_STATE_CARRIED")
    elif fallback:
        reasons.append("DAILY_BAR_FALLBACK")
    if prepared.total_volume > expected_float + tolerance(expected_float):
        prepared = BUILD._cap_prepared_minute_path(prepared, max_volume=expected_float)
        reasons.append("TURNOVER_CAPPED_AT_FLOAT")
    return prepared, expected_float, tuple(reasons), fallback, BUILD._snapshot_ids(dict(row))


def _month_ends(rows: Sequence[Mapping[str, Any]]) -> dict[int, date]:
    result: dict[int, date] = {}
    for row in rows:
        value = BUILD._date(row["trade_date"])
        result[value.month] = max(value, result.get(value.month, value))
    return result


def _advance_lineage(
    lineage: Mapping[int, float], transition: Any
) -> dict[int, float]:
    parts: dict[int, list[float]] = defaultdict(list)
    for source, destination, retention in zip(
        transition.source_cell_ids,
        transition.destination_cell_ids,
        transition.retained_fractions,
        strict=True,
    ):
        shares = lineage.get(int(source))
        if shares is None:
            continue
        retained = shares * float(retention)
        if retained > 0.0:
            parts[int(destination)].append(retained)
    return {key: math.fsum(values) for key, values in sorted(parts.items())}


def _lineage_evidence(
    lineage: Mapping[int, float], root_total: float, transition: Any | None
) -> tuple[bytes, int, bytes, bytes]:
    ordered = tuple(sorted((int(key), float(value)) for key, value in lineage.items()))
    total = math.fsum(value for _, value in ordered)
    retention_bits = _f64_bits(total / root_total)
    survival = _digest((bool(ordered), tuple(key for key, _ in ordered), total))
    destination = _digest(
        ()
        if transition is None
        else tuple(
            (int(source), int(destination))
            for source, destination in zip(
                transition.source_cell_ids,
                transition.destination_cell_ids,
                strict=True,
            )
        )
    )
    return _digest(ordered), retention_bits, survival, destination


@dataclass
class ReplayOutput:
    days: list[DayEvidence]
    checkpoints: list[Checkpoint]
    lifecycle: dict[tuple[date, SellerModel], tuple[bytes, int, bytes, bytes]]
    final_snapshots: dict[SellerModel, ChipSnapshotV2]
    elapsed_by_day_count: dict[int, float]


def replay_target(
    *,
    symbol: str,
    rows: Sequence[Mapping[str, Any]],
    minute_by_date: Mapping[date, Sequence[Mapping[str, Any]]],
    initial_snapshots: Mapping[SellerModel, ChipSnapshotV2],
    tracker: EnsembleTemporalPeakTracker,
    capture_checkpoints: bool,
    timing_horizons: Iterable[int] = (),
    validation_evidence: bool = True,
    capture_oracle_rows: bool = False,
    checkpoint_sink: Callable[[Checkpoint], None] | None = None,
) -> ReplayOutput:
    replay_started = time.perf_counter()
    timed_counts = frozenset(int(value) for value in timing_horizons)
    elapsed_by_day_count: dict[int, float] = {}
    ordered_rows = sorted(rows, key=lambda row: BUILD._date(row["trade_date"]))
    current: dict[SellerModel, ChipSnapshotV2 | MutableChipState] = dict(initial_snapshots)
    grid = StableLogPriceGrid(1.0, 0.0025, BUILD.GRID_VERSION)
    aged_cache: dict[int, int] = {}
    engines = {
        model: DailyMigrationEngine(
            grid=grid,
            seller_model=model,
            model_version=BUILD.MODEL_VERSION,
            aged_cell_id_cache=aged_cache,
        )
        for model in SELLER_MODEL_ORDER
    }
    codec = BUILD._CellCodec()
    previous_views: dict[SellerModel, Any] = {}
    previous_economic: dict[SellerModel, Any] = {}
    for model, snapshot in current.items():
        if isinstance(snapshot, ChipSnapshotV2):
            previous_views[model], previous_economic[model] = (
                codec.snapshot_view_and_economic_buckets(snapshot, grid)
            )
        else:
            (
                previous_views[model],
                _,
                _,
                previous_economic[model],
            ) = codec.register_state_and_profile(snapshot, grid)

    ends = _month_ends(ordered_rows)
    runtime = _runtime_hash()
    model_hashes = tuple(
        _digest((BUILD.MODEL_VERSION, BUILD.GRID_VERSION, model.value))
        for model in SELLER_MODEL_ORDER
    )
    evidence: list[DayEvidence] = []
    checkpoints: list[Checkpoint] = []
    lifecycle: dict[tuple[date, SellerModel], tuple[bytes, int, bytes, bytes]] = {}
    active_lineage: dict[SellerModel, dict[int, float]] = {}
    lineage_roots: dict[SellerModel, float] = {}
    active_month: int | None = None

    for row in ordered_rows:
        trading_date = BUILD._date(row["trade_date"])
        raw_minutes = minute_by_date.get(trading_date, ())
        prepared, expected_float, reasons, fallback, additional_ids = _prepare_day(
            current, row, raw_minutes, grid
        )
        model_rows: list[dict[str, Any]] = []
        snapshots: dict[SellerModel, ChipSnapshotV2] = {}
        transitions: dict[SellerModel, Any] = {}
        for model in SELLER_MODEL_ORDER:
            previous = current[model]
            events = BUILD._inventory_events(previous, dict(row))
            state = engines[model].advance_packed_warmup_day(
                previous_post=previous,
                decision_at=BUILD._aware(trading_date, 15),
                available_at=BUILD._aware(trading_date, 15),
                inventory_events=events,
                expected_free_float_shares=expected_float,
                additional_input_snapshot_ids=additional_ids,
                input_hard_valid=bool(row.get("hard_valid", False)),
                input_quality_reason_codes=reasons,
                prepared_minute_path=prepared,
                build_transition=True,
            )
            transition = state.last_transition
            if transition is None:
                raise RuntimeError("canonical target replay did not build a transition")
            output_tuple, next_view, next_economic = BUILD._output_row(
                state=state,
                transition=transition,
                fallback=fallback,
                previous_post=previous_views[model],
                previous_economic_buckets=previous_economic[model],
                codec=codec,
                grid=grid,
                cash_dividend_per_share=float(row.get("cash_per_share") or 0.0),
                share_multiplier=float(row.get("share_multiplier") or 1.0),
                action_provenance_ids=BUILD.parse_action_ids(row.get("corporate_action_ids")),
                force_checkpoint=False,
                current_price=float(row["close"]),
            )
            model_rows.append(dict(zip(BUILD.OUTPUT_SCHEMA.names, output_tuple, strict=True)))
            previous_views[model] = next_view
            previous_economic[model] = next_economic
            current[model] = state
            snapshots[model] = state.to_snapshot()
            transitions[model] = transition

        feature_tuple = _ensemble_row(model_rows, tracker)
        feature_row = dict(zip(FACT_SCHEMA.names, feature_tuple, strict=True))
        transition_hashes = tuple(
            hashlib.sha256(transitions[model].transition_id.encode("utf-8")).digest()
            for model in SELLER_MODEL_ORDER
        )
        raw_circulating = row.get("circulating_shares")
        evidence.append(
            DayEvidence(
                trading_date=trading_date,
                input_digest=_raw_input_digest(row, raw_minutes),
                input_refs=_input_references(row, raw_minutes),
                action_refs=BUILD.parse_action_ids(row.get("corporate_action_ids")),
                cash_bits=_f64_bits(float(row.get("cash_per_share") or 0.0)),
                multiplier_bits=_f64_bits(float(row.get("share_multiplier") or 1.0)),
                circulating_bits=_f64_bits(None if raw_circulating is None else float(raw_circulating)),
                model_hashes=model_hashes,  # type: ignore[arg-type]
                transition_hashes=transition_hashes,  # type: ignore[arg-type]
                runtime_hashes=(runtime, runtime, runtime),
                operator_digests=tuple(_transition_digest(transitions[model]) for model in SELLER_MODEL_ORDER),  # type: ignore[arg-type]
                post_digests=tuple(_continuation_digest(current[model]) for model in SELLER_MODEL_ORDER),  # type: ignore[arg-type]
                identity_digests=(
                    tuple(_inventory_identity_digest(snapshots[model]) for model in SELLER_MODEL_ORDER)
                    if validation_evidence
                    else ()
                ),  # type: ignore[arg-type]
                share_digests=(
                    tuple(_inventory_share_digest(snapshots[model]) for model in SELLER_MODEL_ORDER)
                    if validation_evidence
                    else ()
                ),  # type: ignore[arg-type]
                feature_digest=_feature_digest(feature_row),
                snapshot_ids=tuple(snapshots[model].snapshot_id for model in SELLER_MODEL_ORDER),  # type: ignore[arg-type]
                transition_ids=tuple(transitions[model].transition_id for model in SELLER_MODEL_ORDER),  # type: ignore[arg-type]
                oracle_row_digests=(
                    tuple(_arrow_row_digest(value, ORACLE_OUTPUT_SCHEMA) for value in model_rows)
                    if capture_oracle_rows
                    else ()
                ),
            )
        )

        if validation_evidence and active_month != trading_date.month:
            active_month = trading_date.month
            active_lineage = {
                model: {cell.cell_id: cell.shares for cell in snapshots[model].inventory.cells}
                for model in SELLER_MODEL_ORDER
            }
            lineage_roots = {
                model: math.fsum(active_lineage[model].values()) for model in SELLER_MODEL_ORDER
            }
            for model in SELLER_MODEL_ORDER:
                lifecycle[(trading_date, model)] = _lineage_evidence(
                    active_lineage[model], lineage_roots[model], None
                )
        elif validation_evidence:
            for model in SELLER_MODEL_ORDER:
                active_lineage[model] = _advance_lineage(active_lineage[model], transitions[model])
                lifecycle[(trading_date, model)] = _lineage_evidence(
                    active_lineage[model], lineage_roots[model], transitions[model]
                )

        if capture_checkpoints and trading_date == ends[trading_date.month]:
            checkpoint = Checkpoint(
                label=f"month-{trading_date.month:02d}",
                snapshots={model: copy.deepcopy(current[model]) for model in SELLER_MODEL_ORDER},
                tracker=copy.deepcopy(tracker),
            )
            if checkpoint_sink is None:
                checkpoints.append(checkpoint)
            else:
                checkpoint_sink(checkpoint)
        day_count = len(evidence)
        if day_count in timed_counts:
            elapsed_by_day_count[day_count] = time.perf_counter() - replay_started
    final = {
        model: state if isinstance(state, ChipSnapshotV2) else state.to_snapshot()
        for model, state in current.items()
    }
    return ReplayOutput(evidence, checkpoints, lifecycle, final, elapsed_by_day_count)


def _read_symbol_inputs(stage: Path, symbol: str) -> tuple[list[dict[str, Any]], dict[date, list[dict[str, Any]]]]:
    daily_path = next(stage.glob(f"daily/bucket=*/symbol={symbol}"), None)
    minute_path = next(stage.glob(f"minute/bucket=*/symbol={symbol}"), None)
    if daily_path is None:
        raise FileNotFoundError(f"staged daily input missing for {symbol}")
    daily = BUILD._read_symbol_partition(daily_path, symbol)
    minute = BUILD._read_symbol_partition(minute_path, symbol) if minute_path else []
    minute_by_date: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for row in minute:
        minute_by_date[BUILD._date(row["trade_date"])].append(row)
    return daily, minute_by_date


def _oracle_paths(root: Path, symbol: str) -> tuple[Path, Path]:
    stem = symbol.replace(".", "_") + ".parquet"
    part = next(root.glob(f"parts/bucket=*/{stem}"), None)
    fact = next(root.glob(f"daily_feature_fact/symbol_bucket=*/{stem}"), None)
    if part is None or fact is None:
        raise FileNotFoundError(f"completed V12 oracle missing for {symbol}")
    return part, fact


def _verify_oracle(root: Path, symbol: str, evidence: Sequence[DayEvidence]) -> dict[str, int]:
    part_path, fact_path = _oracle_paths(root, symbol)
    operator = pq.read_table(
        part_path,
        columns=["trade_date", "seller_model", "snapshot_id", "transition_id"],
        use_threads=False,
    ).to_pylist()
    operator_map = {
        (BUILD._date(row["trade_date"]), SellerModel(row["seller_model"])): row
        for row in operator
    }
    facts = pq.read_table(fact_path, use_threads=False).to_pylist()
    fact_map = {BUILD._date(row["trade_date"]): row for row in facts}
    mismatches = {"snapshot_id": 0, "transition_id": 0, "feature_digest": 0}
    for day in evidence:
        for model_index, model in enumerate(SELLER_MODEL_ORDER):
            row = operator_map[(day.trading_date, model)]
            mismatches["snapshot_id"] += int(str(row["snapshot_id"]) != day.snapshot_ids[model_index])
            mismatches["transition_id"] += int(str(row["transition_id"]) != day.transition_ids[model_index])
        mismatches["feature_digest"] += int(
            _feature_digest(fact_map[day.trading_date]) != day.feature_digest
        )
    return mismatches


def _assert_day(expected: Mapping[str, Any], actual: DayEvidence) -> None:
    pairs = (
        (expected["input_digest"], actual.input_digest, "input digest"),
        (expected["input_refs"], actual.input_refs, "input references"),
        (expected["action_refs"], actual.action_refs, "corporate actions"),
        (expected["cash_bits"], actual.cash_bits, "cash bits"),
        (expected["multiplier_bits"], actual.multiplier_bits, "multiplier bits"),
        (expected["circulating_bits"], actual.circulating_bits, "circulating-share bits"),
        (expected["model_hashes"], actual.model_hashes, "model hashes"),
        (expected["transition_hashes"], actual.transition_hashes, "transition hashes"),
        (expected["runtime_hashes"], actual.runtime_hashes, "runtime hashes"),
        (expected["operator_digests"], actual.operator_digests, "operator digests"),
        (expected["post_digests"], actual.post_digests, "post-state digests"),
        (expected["feature_digest"], actual.feature_digest, "feature digest"),
        (expected["snapshot_ids"], actual.snapshot_ids, "snapshot ids"),
        (expected["transition_ids"], actual.transition_ids, "transition ids"),
    )
    for wanted, observed, label in pairs:
        if wanted != observed:
            detail = ""
            if label in {"transition hashes", "operator digests", "post-state digests"}:
                detail = (
                    f"; expected_transition_ids={expected['transition_ids']}, "
                    f"actual_transition_ids={actual.transition_ids}, "
                    f"operator_equal={tuple(a == b for a, b in zip(expected['operator_digests'], actual.operator_digests, strict=True))}, "
                    f"post_equal={tuple(a == b for a, b in zip(expected['post_digests'], actual.post_digests, strict=True))}"
                )
            raise AssertionError(
                f"{actual.trading_date}: exact {label} mismatch{detail}"
            )


def _rss_mib() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform != "darwin":
        value *= 1024.0
    return value / (1024.0 * 1024.0)


def _checkpoint_name(checkpoint: Checkpoint) -> str:
    day = next(iter(checkpoint.snapshots.values())).trading_date
    return f"{checkpoint.label}-{day.isoformat()}.npz"


def _source_files(stage: Path, oracle: Path, symbol: str) -> list[Path]:
    roots = [
        next(stage.glob(f"daily/bucket=*/symbol={symbol}"), None),
        next(stage.glob(f"minute/bucket=*/symbol={symbol}"), None),
    ]
    part, fact = _oracle_paths(oracle, symbol)
    files = [part, fact, Path(__file__).resolve(), (ROOT / "scripts/build_real_chip_year.py").resolve()]
    for root in roots:
        if root is None:
            continue
        files.extend(path for path in root.rglob("*") if path.is_file())
    return sorted(set(files), key=lambda path: str(path))


def _benchmark_fingerprint(stage: Path, oracle: Path, symbol: str, year: int, mode: str) -> str:
    hasher = hashlib.sha256()
    _update_hash(
        hasher,
        (PROTOTYPE_VERSION, symbol, year, mode, semantic_fingerprint_fields()),
    )
    for path in _source_files(stage, oracle, symbol):
        _update_hash(hasher, str(path.resolve()))
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                hasher.update(chunk)
    return hasher.hexdigest()


def _load_cached_result(output: Path, symbol: str, fingerprint: str) -> dict[str, Any] | None:
    path = output / f"symbol={symbol}" / RESULT_CACHE_NAME
    if not path.exists():
        return None
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if envelope.get("fingerprint") != fingerprint:
        return None
    result = envelope.get("result")
    if not isinstance(result, dict) or result.get("symbol") != symbol:
        return None
    return result


def _write_cached_result(symbol_root: Path, fingerprint: str, result: Mapping[str, Any]) -> None:
    path = symbol_root / RESULT_CACHE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"fingerprint": fingerprint, "result": result},
        ensure_ascii=False,
        indent=2,
    )
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    temporary.replace(path)


def _run_symbol_benchmark(args: tuple[str, str, str, str, int, str, str]) -> dict[str, Any]:
    symbol, stage_raw, oracle_raw, output_raw, year, mode, fingerprint = args
    stage, oracle, output = Path(stage_raw), Path(oracle_raw), Path(output_raw)
    symbol_root = output / f"symbol={symbol}"
    checkpoint_root = symbol_root / "checkpoints"
    daily, minute_by_date = _read_symbol_inputs(stage, symbol)
    warmup = [row for row in daily if BUILD._date(row["trade_date"]).year < year]
    target = [row for row in daily if BUILD._date(row["trade_date"]).year == year]
    warmup.sort(key=lambda row: BUILD._date(row["trade_date"]))
    target.sort(key=lambda row: BUILD._date(row["trade_date"]))
    if not warmup or not target:
        raise ValueError(f"{symbol}: opening or target-year inputs missing")
    warmup_minute = [
        row
        for day, rows in minute_by_date.items()
        if day.year < year
        for row in rows
    ]
    _, opening_snapshots = BUILD._run_symbol(
        symbol,
        warmup,
        warmup_minute,
        year - 1,
        None,
        emit_operators=False,
    )
    opening_tracker = EnsembleTemporalPeakTracker(symbol=symbol, models=TRACKER_MODELS)
    opening = Checkpoint("opening", opening_snapshots, copy.deepcopy(opening_tracker))

    baseline_started = time.perf_counter()
    baseline = replay_target(
        symbol=symbol,
        rows=target,
        minute_by_date=minute_by_date,
        initial_snapshots=opening_snapshots,
        tracker=opening_tracker,
        capture_checkpoints=True,
    )
    baseline_seconds = time.perf_counter() - baseline_started
    if len(baseline.checkpoints) != 12:
        raise AssertionError(f"{symbol}: expected 12 month-end checkpoints")
    checkpoints = [opening, *baseline.checkpoints]
    checkpoint_stats: list[dict[str, int]] = []
    checkpoint_paths: list[Path] = []
    for checkpoint in checkpoints:
        path = checkpoint_root / _checkpoint_name(checkpoint)
        checkpoint_stats.append(write_checkpoint(path, checkpoint))
        checkpoint_paths.append(path)
        restored, restored_tracker = load_checkpoint(path)
        for model in SELLER_MODEL_ORDER:
            if _continuation_digest(restored[model]) != _continuation_digest(checkpoint.snapshots[model]):
                raise AssertionError(f"{symbol}: checkpoint state roundtrip mismatch")
            if _inventory_identity_digest(restored[model]) != _inventory_identity_digest(checkpoint.snapshots[model]):
                raise AssertionError(f"{symbol}: checkpoint identity roundtrip mismatch")
            if _inventory_share_digest(restored[model]) != _inventory_share_digest(checkpoint.snapshots[model]):
                raise AssertionError(f"{symbol}: checkpoint share-bit roundtrip mismatch")
        if _tracker_digest(restored_tracker) != _tracker_digest(checkpoint.tracker):
            raise AssertionError(f"{symbol}: feature continuation roundtrip mismatch")

    journal_path = symbol_root / "daily_replay_journal.npz"
    journal_bytes = write_journal(journal_path, baseline.days)
    journal = load_journal(journal_path)
    oracle_mismatches = _verify_oracle(oracle, symbol, baseline.days)
    if any(oracle_mismatches.values()):
        raise AssertionError(f"{symbol}: frozen V12 oracle mismatch: {oracle_mismatches}")

    target_by_month: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in target:
        target_by_month[BUILD._date(row["trade_date"]).month].append(row)
    daily_comparisons = 0
    lifecycle_comparisons = 0
    for month in range(1, 13):
        source_path = checkpoint_paths[month - 1]
        snapshots, tracker = load_checkpoint(source_path)
        replay = replay_target(
            symbol=symbol,
            rows=target_by_month[month],
            minute_by_date=minute_by_date,
            initial_snapshots=snapshots,
            tracker=tracker,
            capture_checkpoints=False,
        )
        for day in replay.days:
            _assert_day(journal[day.trading_date], day)
            expected_day = next(item for item in baseline.days if item.trading_date == day.trading_date)
            if expected_day.identity_digests != day.identity_digests:
                raise AssertionError(f"{symbol} {day.trading_date}: inventory cell identity mismatch")
            if expected_day.share_digests != day.share_digests:
                raise AssertionError(f"{symbol} {day.trading_date}: exact share bits mismatch")
            daily_comparisons += 3
        for key, value in replay.lifecycle.items():
            if baseline.lifecycle[key] != value:
                raise AssertionError(f"{symbol} {key}: lifecycle exact comparison mismatch")
            lifecycle_comparisons += 1

    load_times: list[float] = []
    for path in checkpoint_paths:
        started = time.perf_counter()
        load_checkpoint(path)
        load_times.append(time.perf_counter() - started)

    if mode == "fast":
        snapshots, tracker = load_checkpoint(checkpoint_paths[0])
        prefix = replay_target(
            symbol=symbol,
            rows=target[:22],
            minute_by_date=minute_by_date,
            initial_snapshots=snapshots,
            tracker=tracker,
            capture_checkpoints=False,
            timing_horizons=(1, 5, 10, 22),
        )
        horizons = dict(prefix.elapsed_by_day_count)
        if set(horizons) != {1, 5, 10, 22}:
            raise AssertionError(f"{symbol}: fast timing horizons were not captured")
        for day in prefix.days:
            _assert_day(journal[day.trading_date], day)
        sequential_seconds = baseline_seconds
    else:
        horizons: dict[int, float] = {}
        for horizon in (1, 5, 10, 22):
            snapshots, tracker = load_checkpoint(checkpoint_paths[0])
            started = time.perf_counter()
            replay = replay_target(
                symbol=symbol,
                rows=target[:horizon],
                minute_by_date=minute_by_date,
                initial_snapshots=snapshots,
                tracker=tracker,
                capture_checkpoints=False,
            )
            horizons[horizon] = time.perf_counter() - started
            for day in replay.days:
                _assert_day(journal[day.trading_date], day)

        snapshots, tracker = load_checkpoint(checkpoint_paths[0])
        sequential_started = time.perf_counter()
        sequential = replay_target(
            symbol=symbol,
            rows=target,
            minute_by_date=minute_by_date,
            initial_snapshots=snapshots,
            tracker=tracker,
            capture_checkpoints=False,
        )
        sequential_seconds = time.perf_counter() - sequential_started
        for day in sequential.days:
            _assert_day(journal[day.trading_date], day)

    manifest = {
        "prototype": PROTOTYPE_VERSION,
        "benchmark_mode": mode,
        "symbol": symbol,
        "year": year,
        "checkpoint_count": 13,
        "journal_days": len(baseline.days),
        "checkpoint_files": [path.name for path in checkpoint_paths],
        "journal_file": journal_path.name,
        "daily_payload_contract": [
            "immutable_input_references_and_digests",
            "corporate_action_facts",
            "model_transition_runtime_hashes",
            "operator_digest",
            "post_state_digest",
            "feature_digest",
        ],
        "forbidden_daily_payloads": [
            "destination_vectors",
            "retention_vectors",
            "full_state",
        ],
        "semantic_fingerprint": semantic_fingerprint_fields(),
    }
    manifest_path = symbol_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    checkpoint_bytes = sum(item["shared_bytes"] for item in checkpoint_stats)
    result = {
        "symbol": symbol,
        "benchmark_mode": mode,
        "days": len(baseline.days),
        "checkpoint_count": len(checkpoints),
        "checkpoint_bytes": checkpoint_bytes,
        "checkpoint_file_bytes": [item["shared_bytes"] for item in checkpoint_stats],
        "journal_bytes": journal_bytes,
        "manifest_bytes": manifest_path.stat().st_size,
        "total_bytes": checkpoint_bytes + journal_bytes + manifest_path.stat().st_size,
        "union_identities": sum(item["union_identities"] for item in checkpoint_stats),
        "independent_identities": sum(item["independent_identities"] for item in checkpoint_stats),
        "separate_checkpoint_bytes": sum(item["separate_bytes"] for item in checkpoint_stats),
        "actual_saved_bytes": sum(item["actual_saved_bytes"] for item in checkpoint_stats),
        "daily_exact_comparisons": daily_comparisons,
        "lifecycle_exact_comparisons": lifecycle_comparisons,
        "oracle_mismatches": oracle_mismatches,
        "checkpoint_load_seconds": load_times,
        "replay_seconds": {str(key): value for key, value in horizons.items()},
        "full_year_sequential_seconds": sequential_seconds,
        "baseline_seconds": baseline_seconds,
        "peak_memory_mib": _rss_mib(),
    }
    _write_cached_result(symbol_root, fingerprint, result)
    return result


def _quantiles(values: Sequence[float], scale: float = 1.0) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float64) * scale
    return {
        "mean": float(np.mean(array)),
        "p50": float(np.percentile(array, 50)),
        "p90": float(np.percentile(array, 90)),
        "p99": float(np.percentile(array, 99)),
    }


def _capacity(results: Sequence[Mapping[str, Any]], *, symbols: int = 5210) -> dict[str, Any]:
    annualized = mean(float(item["total_bytes"]) for item in results) * symbols / (1024**3)
    status = "TARGET_PASS" if annualized <= 45.0 else "TARGET_MISS"
    if annualized > 50.0:
        status = "HARD_FAILURE"
    return {
        "symbols": symbols,
        "annualized_gib": annualized,
        "target_gib": 45.0,
        "hard_limit_gib": 50.0,
        "status": status,
    }


def _bimonthly_capacity(results: Sequence[Mapping[str, Any]], *, symbols: int = 5210) -> dict[str, Any]:
    totals: list[float] = []
    for result in results:
        files = result["checkpoint_file_bytes"]
        # opening + February/April/June/August/October/December month ends.
        checkpoint_bytes = float(files[0] + sum(files[index] for index in (2, 4, 6, 8, 10, 12)))
        totals.append(checkpoint_bytes + float(result["journal_bytes"]) + float(result["manifest_bytes"]))
    annualized = mean(totals) * symbols / (1024**3)
    status = "TARGET_PASS" if annualized <= 45.0 else "TARGET_MISS"
    if annualized > 50.0:
        status = "HARD_FAILURE"
    return {
        "checkpoint_count": 7,
        "annualized_gib": annualized,
        "status": status,
    }


def _markdown(report: Mapping[str, Any]) -> str:
    storage = report["storage"]
    timing = report["timing"]
    overlap = report["identity_union"]
    capacity = report["capacity_gate"]
    lines = [
        "# V12 checkpoint-recompute prototype — 50-symbol validation",
        "",
        f"Status: **{report['status']}**. Production schema/code was not changed and no V13 full-market build was run.",
        "",
        "## Exactness",
        "",
        f"- Daily model comparisons: {report['validation']['daily_exact_comparisons']:,}; mismatches: 0.",
        f"- Lifecycle anchor comparisons: {report['validation']['lifecycle_exact_comparisons']:,}; mismatches: 0.",
        "- Compared operator digest, full POST digest, inventory economic identities, IEEE-754 share bits, daily feature digest, lineage shares, anchor retention bits, survival result, and destination mapping with no tolerance/rounding/float32/normalization.",
        "",
        "## Storage (MiB/symbol)",
        "",
        "| Artifact | Mean | P50 | P90 | P99 |",
        "|---|---:|---:|---:|---:|",
        f"| 13 checkpoints | {storage['checkpoint_mib_per_symbol']['mean']:.3f} | {storage['checkpoint_mib_per_symbol']['p50']:.3f} | {storage['checkpoint_mib_per_symbol']['p90']:.3f} | {storage['checkpoint_mib_per_symbol']['p99']:.3f} |",
        f"| Daily journal | {storage['journal_mib_per_symbol']['mean']:.3f} | {storage['journal_mib_per_symbol']['p50']:.3f} | {storage['journal_mib_per_symbol']['p90']:.3f} | {storage['journal_mib_per_symbol']['p99']:.3f} |",
        f"| Annual total | {storage['total_mib_per_symbol']['mean']:.3f} | {storage['total_mib_per_symbol']['p50']:.3f} | {storage['total_mib_per_symbol']['p90']:.3f} | {storage['total_mib_per_symbol']['p99']:.3f} |",
        "",
        f"5210-symbol annualized: **{capacity['annualized_gib']:.3f} GiB**; gate: **{capacity['status']}** (target ≤45 GiB, hard failure >50 GiB).",
        "",
        "## Shared identity table",
        "",
        f"- Independent model identities: {overlap['independent_identities']:,}; union identities: {overlap['union_identities']:,}; overlap: {overlap['overlap_pct']:.2f}%.",
        f"- Actual compressed checkpoint saving: {overlap['actual_saved_mib']:.3f} MiB ({overlap['actual_saved_pct']:.2f}%) against physically written separate-model counterfactuals.",
        "",
        "## Timing",
        "",
        f"- Benchmark mode: {report.get('benchmark_mode', 'strict')}; resumed symbols: {report.get('resumed_symbols', 0)}; current-run wall time: {timing['benchmark_wall_seconds']:.1f} s.",
        f"- Checkpoint load P50/P90/P99: {timing['checkpoint_load_ms']['p50']:.2f}/{timing['checkpoint_load_ms']['p90']:.2f}/{timing['checkpoint_load_ms']['p99']:.2f} ms.",
        f"- Replay 1/5/10/22 trading days (P50): {timing['replay_ms']['1']['p50']:.2f}/{timing['replay_ms']['5']['p50']:.2f}/{timing['replay_ms']['10']['p50']:.2f}/{timing['replay_ms']['22']['p50']:.2f} ms.",
        f"- Full-year sequential replay P50/P90/P99: {timing['full_year_seconds']['p50']:.3f}/{timing['full_year_seconds']['p90']:.3f}/{timing['full_year_seconds']['p99']:.3f} s/symbol.",
        f"- Peak worker memory P50/P90/P99: {timing['peak_memory_mib']['p50']:.1f}/{timing['peak_memory_mib']['p90']:.1f}/{timing['peak_memory_mib']['p99']:.1f} MiB.",
    ]
    if report.get("every_two_month") is not None:
        alternate = report["every_two_month"]
        lines.extend(
            [
                "",
                "## Every-two-month fallback",
                "",
                f"Monthly exceeded 45 GiB, so opening + 6 bimonthly checkpoints was benchmarked automatically: {alternate['annualized_gib']:.3f} GiB ({alternate['status']}).",
            ]
        )
    return "\n".join(lines) + "\n"


def aggregate_report(
    results: Sequence[Mapping[str, Any]],
    elapsed: float,
    *,
    mode: str = "strict",
    resumed_symbols: int = 0,
) -> dict[str, Any]:
    mib = 1.0 / (1024**2)
    independent = sum(int(item["independent_identities"]) for item in results)
    union = sum(int(item["union_identities"]) for item in results)
    separate_bytes = sum(int(item["separate_checkpoint_bytes"]) for item in results)
    saved_bytes = sum(int(item["actual_saved_bytes"]) for item in results)
    capacity = _capacity(results)
    alternate = _bimonthly_capacity(results) if capacity["annualized_gib"] > 45.0 else None
    hard_failure = capacity["status"] == "HARD_FAILURE" and (
        alternate is None or alternate["status"] == "HARD_FAILURE"
    )
    report: dict[str, Any] = {
        "prototype": PROTOTYPE_VERSION,
        "benchmark_mode": mode,
        "resumed_symbols": resumed_symbols,
        "status": "HARD_FAILURE" if hard_failure else "PASS",
        "sample_symbols": len(results),
        "checkpoint_policy": "opening + 12 month-end",
        "daily_policy": "immutable refs/digests + CA facts + hashes/digests only",
        "physical_representation": "compressed flat NumPy SoA + offsets; no object arrays or nested rows",
        "storage": {
            "checkpoint_mib_per_symbol": _quantiles([float(item["checkpoint_bytes"]) for item in results], mib),
            "journal_mib_per_symbol": _quantiles([float(item["journal_bytes"]) for item in results], mib),
            "total_mib_per_symbol": _quantiles([float(item["total_bytes"]) for item in results], mib),
        },
        "identity_union": {
            "independent_identities": independent,
            "union_identities": union,
            "overlap_pct": 100.0 * (independent - union) / independent,
            "actual_saved_bytes": saved_bytes,
            "actual_saved_mib": saved_bytes * mib,
            "actual_saved_pct": 100.0 * saved_bytes / separate_bytes,
        },
        "capacity_gate": capacity,
        "every_two_month": alternate,
        "validation": {
            "daily_exact_comparisons": sum(int(item["daily_exact_comparisons"]) for item in results),
            "lifecycle_exact_comparisons": sum(int(item["lifecycle_exact_comparisons"]) for item in results),
            "mismatches": 0,
            "oracle_mismatches": {
                name: sum(int(item["oracle_mismatches"][name]) for item in results)
                for name in ("snapshot_id", "transition_id", "feature_digest")
            },
        },
        "timing": {
            "checkpoint_load_ms": _quantiles(
                [float(value) for item in results for value in item["checkpoint_load_seconds"]],
                1000.0,
            ),
            "replay_ms": {
                horizon: _quantiles(
                    [float(item["replay_seconds"][horizon]) for item in results], 1000.0
                )
                for horizon in ("1", "5", "10", "22")
            },
            "full_year_seconds": _quantiles([float(item["full_year_sequential_seconds"]) for item in results]),
            "peak_memory_mib": _quantiles([float(item["peak_memory_mib"]) for item in results]),
            "benchmark_wall_seconds": elapsed,
        },
        "symbols": list(results),
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2020)
    parser.add_argument("--symbols-file", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--stage-root", type=Path, default=DEFAULT_STAGE)
    parser.add_argument("--oracle-root", type=Path, default=DEFAULT_ORACLE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--fast-validation",
        action="store_true",
        help="reuse baseline timing and skip duplicate horizon/full-year timing replays",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="ignore fingerprint-matched per-symbol benchmark result caches",
    )
    args = parser.parse_args()
    symbols = [line.strip() for line in args.symbols_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.limit is not None:
        symbols = symbols[: args.limit]
    if not symbols:
        parser.error("symbol sample is empty")
    args.output.mkdir(parents=True, exist_ok=True)
    mode = "fast" if args.fast_validation else "strict"
    fingerprints = {
        symbol: _benchmark_fingerprint(args.stage_root, args.oracle_root, symbol, args.year, mode)
        for symbol in symbols
    }
    results: list[dict[str, Any]] = []
    if not args.no_resume:
        for symbol in symbols:
            cached = _load_cached_result(args.output, symbol, fingerprints[symbol])
            if cached is not None:
                results.append(cached)
                print(json.dumps({"symbol": symbol, "status": "RESUMED"}), flush=True)
    resumed_symbols = len(results)
    completed = {str(item["symbol"]) for item in results}
    remaining = [symbol for symbol in symbols if symbol not in completed]
    # Largest staged/oracle footprints first reduces the long tail without changing semantics.
    remaining.sort(
        key=lambda symbol: sum(
            path.stat().st_size for path in _source_files(args.stage_root, args.oracle_root, symbol)
        ),
        reverse=True,
    )
    payloads = [
        (
            symbol,
            str(args.stage_root),
            str(args.oracle_root),
            str(args.output),
            args.year,
            mode,
            fingerprints[symbol],
        )
        for symbol in remaining
    ]
    started = time.perf_counter()
    if args.workers == 1 or len(payloads) == 1:
        for payload in payloads:
            result = _run_symbol_benchmark(payload)
            results.append(result)
            print(json.dumps({"symbol": result["symbol"], "status": "PASS"}), flush=True)
    elif payloads:
        with ProcessPoolExecutor(max_workers=min(args.workers, len(payloads))) as executor:
            futures = {executor.submit(_run_symbol_benchmark, payload): payload[0] for payload in payloads}
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                print(json.dumps({"symbol": result["symbol"], "status": "PASS"}), flush=True)
    results.sort(key=lambda item: symbols.index(str(item["symbol"])))
    report = aggregate_report(
        results,
        time.perf_counter() - started,
        mode=mode,
        resumed_symbols=resumed_symbols,
    )
    report_path = args.output / "benchmark_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path = args.output / "benchmark_report.md"
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    print(report_path)
    print(markdown_path)
    return 2 if report["status"] == "HARD_FAILURE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
