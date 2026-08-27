"""Deterministic compact production container for logical chip checkpoints.

The wide identity/lot state uses the union-array layout proven by the Final-RC
capacity prototype.  Small continuation metadata remains canonical logical
JSON inside the compressed NPZ container so the logical digest is unchanged.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
import zipfile
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from cyq_game.chip.checkpoint_codec import decode_checkpoint_logical_bytes
from cyq_game.chip.checkpoint_journal_contract import (
    CheckpointLogical,
    ContractError,
    bits_f64be,
    canonical_json_bytes,
    strict_json_loads,
    validate_checkpoint_logical,
)
from cyq_game.chip.state_v2 import TurnoverSensitivity, stable_cell_id

PRODUCTION_CHECKPOINT_CODEC_VERSION = "chip-checkpoint-compact-union-npz-v1"
PRODUCTION_CHECKPOINT_LAYOUT = "union-identity-columnar-arrays-v1"
PRODUCTION_CHECKPOINT_CONTAINER = "deterministic-npz-deflate"
PRODUCTION_CHECKPOINT_COMPRESSION_LEVEL = 6

_FORMAT_VERSION = 1
_SENSITIVITY_TO_CODE = {"ACTIVE": 0, "NEUTRAL": 1, "STICKY": 2}
_CODE_TO_SENSITIVITY = {value: key for key, value in _SENSITIVITY_TO_CODE.items()}
_ARRAY_NAMES = frozenset(
    {
        "format_version",
        "union_identity",
        "logical_digest",
        "metadata_json",
        "identity_cost_bucket_valid",
        "identity_cost_bucket",
        "identity_holding_days",
        "identity_sensitivity",
        "identity_economic_valid",
        "identity_economic_bits",
        "identity_coordinate_refs",
        "model_lot_offsets",
        "lot_identity_positions",
        "lot_share_bits",
        "lot_acquisition_valid",
        "lot_acquisition_bits",
        "lot_prior_units_bits",
        "string_bytes",
        "string_offsets",
    }
)


def _canonical_wire_json_bytes(value: Any) -> bytes:
    """Serialize values already expressed in the canonical wire domain."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


class _StringPool:
    def __init__(self) -> None:
        self._values: list[str] = []
        self._positions: dict[str, int] = {}

    def add(self, value: str) -> int:
        position = self._positions.get(value)
        if position is None:
            position = len(self._values)
            self._positions[value] = position
            self._values.append(value)
        return position

    def arrays(self) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]]:
        encoded = [value.encode("utf-8") for value in self._values]
        offsets = [0]
        for value in encoded:
            offsets.append(offsets[-1] + len(value))
        return (
            np.frombuffer(b"".join(encoded), dtype=np.uint8).copy(),
            np.asarray(offsets, dtype="<u8"),
        )


def _checkpoint_arrays(value: CheckpointLogical) -> dict[str, np.ndarray[Any, Any]]:
    validate_checkpoint_logical(value)
    pool = _StringPool()
    physical_order = sorted(
        range(len(value.identities)),
        key=lambda index: (
            -(1 << 63)
            if value.identities[index].cost_bucket_id is None
            else value.identities[index].cost_bucket_id,
            value.identities[index].holding_days,
            _SENSITIVITY_TO_CODE[value.identities[index].sensitivity],
            int(value.identities[index].economic_break_even_bits is not None),
            0
            if value.identities[index].economic_break_even_bits is None
            else value.identities[index].economic_break_even_bits,
        ),
    )
    physical_identities = tuple(value.identities[index] for index in physical_order)
    logical_to_physical = {
        logical_position: physical_position
        for physical_position, logical_position in enumerate(physical_order)
    }
    for identity in physical_identities:
        derived_cell_id = stable_cell_id(
            cost_bucket_id=identity.cost_bucket_id,
            holding_days=identity.holding_days,
            sensitivity=TurnoverSensitivity(identity.sensitivity),
            economic_break_even=(
                None
                if identity.economic_break_even_bits is None
                else bits_f64be(identity.economic_break_even_bits)
            ),
        )
        if identity.cell_id != derived_cell_id:
            raise ContractError("checkpoint cell_id differs from canonical identity primitives")
    skeleton = replace(
        value,
        identities=(),
        model_states=tuple(replace(state, lots=()) for state in value.model_states),
    )
    metadata = canonical_json_bytes(skeleton)
    lot_offsets = [0]
    identity_positions: list[int] = []
    share_bits: list[int] = []
    acquisition_valid: list[int] = []
    acquisition_bits: list[int] = []
    prior_bits: list[int] = []
    for state in value.model_states:
        for lot in state.lots:
            identity_positions.append(logical_to_physical[lot.identity_position])
            share_bits.append(lot.shares_bits)
            acquisition_valid.append(int(lot.acquisition_cost_bits is not None))
            acquisition_bits.append(
                0 if lot.acquisition_cost_bits is None else lot.acquisition_cost_bits
            )
            prior_bits.append(lot.initialization_prior_units_bits)
        lot_offsets.append(len(identity_positions))
    coordinate_refs = np.asarray(
        [pool.add(identity.economic_coordinate_version) for identity in physical_identities],
        dtype="<i4",
    )
    string_bytes, string_offsets = pool.arrays()
    logical_digest = hashlib.sha256(canonical_json_bytes(value)).digest()
    return {
        "format_version": np.asarray([_FORMAT_VERSION], dtype="<u2"),
        "union_identity": np.asarray([1], dtype=np.uint8),
        "logical_digest": np.frombuffer(logical_digest, dtype=np.uint8).copy(),
        "metadata_json": np.frombuffer(metadata, dtype=np.uint8).copy(),
        "identity_cost_bucket_valid": np.asarray(
            [identity.cost_bucket_id is not None for identity in physical_identities],
            dtype=np.uint8,
        ),
        "identity_cost_bucket": np.asarray(
            [
                -(1 << 63) if identity.cost_bucket_id is None else identity.cost_bucket_id
                for identity in physical_identities
            ],
            dtype="<i8",
        ),
        "identity_holding_days": np.asarray(
            [identity.holding_days for identity in physical_identities], dtype="<i2"
        ),
        "identity_sensitivity": np.asarray(
            [_SENSITIVITY_TO_CODE[identity.sensitivity] for identity in physical_identities],
            dtype=np.uint8,
        ),
        "identity_economic_valid": np.asarray(
            [identity.economic_break_even_bits is not None for identity in physical_identities],
            dtype=np.uint8,
        ),
        "identity_economic_bits": np.asarray(
            [
                0
                if identity.economic_break_even_bits is None
                else identity.economic_break_even_bits
                for identity in physical_identities
            ],
            dtype="<u8",
        ),
        "identity_coordinate_refs": coordinate_refs,
        "model_lot_offsets": np.asarray(lot_offsets, dtype="<u8"),
        "lot_identity_positions": np.asarray(identity_positions, dtype="<u8"),
        "lot_share_bits": np.asarray(share_bits, dtype="<u8"),
        "lot_acquisition_valid": np.asarray(acquisition_valid, dtype=np.uint8),
        "lot_acquisition_bits": np.asarray(acquisition_bits, dtype="<u8"),
        "lot_prior_units_bits": np.asarray(prior_bits, dtype="<u8"),
        "string_bytes": string_bytes,
        "string_offsets": string_offsets,
    }


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(f"{name}.npy", date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info._compresslevel = PRODUCTION_CHECKPOINT_COMPRESSION_LEVEL
    info.create_system = 3
    info.external_attr = 0o600 << 16
    return info


def _write_arrays(path: Path, arrays: Mapping[str, np.ndarray[Any, Any]]) -> None:
    with zipfile.ZipFile(
        path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=PRODUCTION_CHECKPOINT_COMPRESSION_LEVEL,
        allowZip64=True,
    ) as archive:
        for name in sorted(arrays):
            with archive.open(_zip_info(name), mode="w", force_zip64=True) as handle:
                np.lib.format.write_array(handle, arrays[name], allow_pickle=False)


def write_compact_checkpoint(path: Path, value: CheckpointLogical) -> int:
    """Atomically write the one normal production checkpoint container."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        _write_arrays(temporary, _checkpoint_arrays(value))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path.stat().st_size


def _load_arrays(path: Path) -> dict[str, np.ndarray[Any, Any]]:
    try:
        with np.load(path, allow_pickle=False) as archive:
            if set(archive.files) != _ARRAY_NAMES:
                raise ContractError("compact checkpoint array fields mismatch")
            return {name: archive[name] for name in archive.files}
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise ContractError("invalid compact checkpoint container") from exc


def _require_vector(
    data: Mapping[str, np.ndarray[Any, Any]], name: str, dtype: str | type[np.generic]
) -> np.ndarray[Any, Any]:
    value = data[name]
    if value.ndim != 1 or value.dtype != np.dtype(dtype):
        raise ContractError(f"compact checkpoint {name} array contract mismatch")
    return value


def _pool_value(
    string_bytes: np.ndarray[Any, Any],
    string_offsets: np.ndarray[Any, Any],
    reference: int,
) -> str:
    if reference < 0 or reference + 1 >= len(string_offsets):
        raise ContractError("compact checkpoint string reference is out of range")
    start = int(string_offsets[reference])
    stop = int(string_offsets[reference + 1])
    if not 0 <= start <= stop <= len(string_bytes):
        raise ContractError("compact checkpoint string offsets are invalid")
    try:
        return bytes(string_bytes[start:stop]).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError("compact checkpoint string pool is not UTF-8") from exc


def decode_compact_checkpoint(path: Path) -> CheckpointLogical:
    """Decode a compact checkpoint and verify its canonical logical digest."""

    data = _load_arrays(path)
    format_version = _require_vector(data, "format_version", "<u2")
    union_identity = _require_vector(data, "union_identity", np.uint8)
    if (
        format_version.shape != (1,)
        or int(format_version[0]) != _FORMAT_VERSION
        or union_identity.shape != (1,)
        or int(union_identity[0]) != 1
    ):
        raise ContractError("unsupported compact checkpoint format")
    logical_digest = _require_vector(data, "logical_digest", np.uint8)
    metadata_json = _require_vector(data, "metadata_json", np.uint8)
    if logical_digest.shape != (32,):
        raise ContractError("compact checkpoint logical digest has invalid length")
    raw = strict_json_loads(bytes(metadata_json))
    if not isinstance(raw, dict) or _canonical_wire_json_bytes(raw) != bytes(metadata_json):
        raise ContractError("compact checkpoint metadata is not canonical")
    identities = raw.get("identities")
    models = raw.get("model_states")
    if identities != [] or not isinstance(models, list):
        raise ContractError("compact checkpoint metadata skeleton is invalid")

    cost_valid = _require_vector(data, "identity_cost_bucket_valid", np.uint8)
    cost_buckets = _require_vector(data, "identity_cost_bucket", "<i8")
    holding_days = _require_vector(data, "identity_holding_days", "<i2")
    sensitivities = _require_vector(data, "identity_sensitivity", np.uint8)
    economic_valid = _require_vector(data, "identity_economic_valid", np.uint8)
    economic_bits = _require_vector(data, "identity_economic_bits", "<u8")
    coordinate_refs = _require_vector(data, "identity_coordinate_refs", "<i4")
    identity_count = len(cost_valid)
    if any(
        len(array) != identity_count
        for array in (
            cost_buckets,
            holding_days,
            sensitivities,
            economic_valid,
            economic_bits,
            coordinate_refs,
        )
    ):
        raise ContractError("compact checkpoint identity array lengths mismatch")
    if np.any(cost_valid > 1) or np.any(economic_valid > 1):
        raise ContractError("compact checkpoint identity validity flag is invalid")
    if not np.array_equal(cost_valid, economic_valid):
        raise ContractError("compact checkpoint identity nullability mismatch")
    if np.any(sensitivities > max(_CODE_TO_SENSITIVITY)):
        raise ContractError("compact checkpoint turnover sensitivity is invalid")

    string_bytes = _require_vector(data, "string_bytes", np.uint8)
    string_offsets = _require_vector(data, "string_offsets", "<u8")
    if len(string_offsets) == 0 or int(string_offsets[0]) != 0:
        raise ContractError("compact checkpoint string offsets lack zero origin")
    if np.any(string_offsets[1:] < string_offsets[:-1]):
        raise ContractError("compact checkpoint string offsets are not monotonic")
    if int(string_offsets[-1]) != len(string_bytes):
        raise ContractError("compact checkpoint string offsets do not cover bytes")
    physical_identities = [
        {
            "cell_id": str(
                stable_cell_id(
                    cost_bucket_id=(int(cost_buckets[index]) if int(cost_valid[index]) else None),
                    holding_days=int(holding_days[index]),
                    sensitivity=TurnoverSensitivity(
                        _CODE_TO_SENSITIVITY[int(sensitivities[index])]
                    ),
                    economic_break_even=(
                        bits_f64be(int(economic_bits[index]))
                        if int(economic_valid[index])
                        else None
                    ),
                )
            ),
            "cost_bucket_id": (str(int(cost_buckets[index])) if int(cost_valid[index]) else None),
            "holding_days": str(int(holding_days[index])),
            "sensitivity": _CODE_TO_SENSITIVITY.get(int(sensitivities[index])),
            "economic_break_even_bits": (
                f"f64be:{int(economic_bits[index]):016x}" if int(economic_valid[index]) else None
            ),
            "economic_coordinate_version": _pool_value(
                string_bytes, string_offsets, int(coordinate_refs[index])
            ),
        }
        for index in range(identity_count)
    ]
    logical_order = sorted(
        range(identity_count), key=lambda index: int(physical_identities[index]["cell_id"])
    )
    if len({physical_identities[index]["cell_id"] for index in logical_order}) != identity_count:
        raise ContractError("compact checkpoint derived cell IDs are not unique")
    physical_to_logical = {
        physical_position: logical_position
        for logical_position, physical_position in enumerate(logical_order)
    }
    raw["identities"] = [physical_identities[index] for index in logical_order]

    lot_offsets = _require_vector(data, "model_lot_offsets", "<u8")
    lot_positions = _require_vector(data, "lot_identity_positions", "<u8")
    lot_share_bits = _require_vector(data, "lot_share_bits", "<u8")
    lot_acquisition_valid = _require_vector(data, "lot_acquisition_valid", np.uint8)
    lot_acquisition_bits = _require_vector(data, "lot_acquisition_bits", "<u8")
    lot_prior_bits = _require_vector(data, "lot_prior_units_bits", "<u8")
    lot_count = len(lot_positions)
    if len(lot_offsets) != len(models) + 1 or int(lot_offsets[0]) != 0:
        raise ContractError("compact checkpoint model lot offsets are invalid")
    if np.any(lot_offsets[1:] < lot_offsets[:-1]) or int(lot_offsets[-1]) != lot_count:
        raise ContractError("compact checkpoint model lot offsets do not cover lots")
    if any(
        len(array) != lot_count
        for array in (
            lot_share_bits,
            lot_acquisition_valid,
            lot_acquisition_bits,
            lot_prior_bits,
        )
    ) or np.any(lot_acquisition_valid > 1):
        raise ContractError("compact checkpoint lot array contract mismatch")
    if np.any(lot_positions >= identity_count):
        raise ContractError("compact checkpoint lot identity position is out of range")
    for model_index, model in enumerate(models):
        if not isinstance(model, dict) or model.get("lots") != []:
            raise ContractError("compact checkpoint model metadata skeleton is invalid")
        start = int(lot_offsets[model_index])
        stop = int(lot_offsets[model_index + 1])
        model["lots"] = [
            {
                "identity_position": str(physical_to_logical[int(lot_positions[index])]),
                "shares_bits": f"f64be:{int(lot_share_bits[index]):016x}",
                "acquisition_cost_bits": (
                    f"f64be:{int(lot_acquisition_bits[index]):016x}"
                    if int(lot_acquisition_valid[index])
                    else None
                ),
                "initialization_prior_units_bits": (f"f64be:{int(lot_prior_bits[index]):016x}"),
            }
            for index in range(start, stop)
        ]
    logical = _canonical_wire_json_bytes(raw)
    if hashlib.sha256(logical).digest() != bytes(logical_digest):
        raise ContractError("compact checkpoint logical digest mismatch")
    return decode_checkpoint_logical_bytes(logical)
